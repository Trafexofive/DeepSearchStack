"""
api_gateway — Substrate Omni-Entrypoint

Reverse proxy + JWT gateway. Routes external requests to internal
services via Docker DNS. Aggregates health, handles auth, and 
passes through WebSocket connections.

Route mapping:
  /api/workflows/*  → workflow_engine:8001
  /api/llm/*        → llm_gateway:8002
  /api/events/*     → event_bus:8003
  /api/inference/*  → inference_gateway:8005
  /api/blog/*       → blog_generator:8006
  /api/bridge/*     → knowledge_bridge:8010
  /api/audit/*      → geo_audit:8011
  /api/queue/*      → sub_mq:8012
  /ws/events/*      → event_bus:8003 (WebSocket)
  /ws/queue/*       → sub_mq:8012 (WebSocket)
"""

import os
import json
import logging
import asyncio
from typing import Optional
from contextlib import asynccontextmanager

import httpx
from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.responses import StreamingResponse, JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.websockets import WebSocket, WebSocketDisconnect

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("api_gateway")

# ─── Service Registry ────────────────────────────────────────────────────────

SERVICE_ROUTES: dict[str, dict] = {
    "workflows":   {"host": os.getenv("WORKFLOW_ENGINE_HOST", "workflow_engine"),   "port": 8001, "prefix": "api"},
    "llm":         {"host": os.getenv("LLM_GATEWAY_HOST", "llm_gateway"),           "port": 8002, "prefix": "api"},
    "events":      {"host": os.getenv("EVENT_BUS_HOST", "event_bus"),               "port": 8003, "prefix": "api"},
    "inference":   {"host": os.getenv("INFERENCE_GATEWAY_HOST", "inference_gateway"), "port": 8005, "prefix": "v1"},
    "blog":        {"host": os.getenv("BLOG_GENERATOR_HOST", "blog_generator"),     "port": 8006, "prefix": ""},
    "bridge":      {"host": os.getenv("KNOWLEDGE_BRIDGE_HOST", "knowledge_bridge"), "port": 8010, "prefix": "bridge"},
    "audit":       {"host": os.getenv("GEO_AUDIT_HOST", "geo_audit"),               "port": 8011, "prefix": "audit"},
    "queue":       {"host": os.getenv("SUB_MQ_HOST", "sub_mq"),                     "port": 8012, "prefix": "queue"},
    "ingest":      {"host": os.getenv("INGEST_HOST", "ingest"),                       "port": 8008, "prefix": ""},
    "dss":         {"host": os.getenv("DSS_WEB_API_HOST", "dss-web-api"),             "port": 8014, "prefix": ""},
    "yt-lab":      {"host": os.getenv("YT_LAB_HOST", "yt-lab"),                       "port": 8020, "prefix": ""},
}

HOP_HEADERS = {
    "connection", "keep-alive", "proxy-authenticate", "proxy-authorization",
    "te", "trailer", "transfer-encoding", "upgrade", "host",
}

# ─── Shared HTTP Client ──────────────────────────────────────────────────────

_http: Optional[httpx.AsyncClient] = None

async def get_http() -> httpx.AsyncClient:
    global _http
    if _http is None:
        _http = httpx.AsyncClient(timeout=120.0, follow_redirects=False)
    return _http


def filter_headers(headers: dict) -> dict:
    return {k: v for k, v in headers.items() if k.lower() not in HOP_HEADERS}


# ─── App ─────────────────────────────────────────────────────────────────────

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("api_gateway starting — %d service routes configured", len(SERVICE_ROUTES))
    global _http
    _http = httpx.AsyncClient(timeout=30.0, follow_redirects=False)
    yield
    if _http:
        await _http.aclose()
    logger.info("api_gateway shut down")


app = FastAPI(title="Substrate API Gateway", version="0.2.0", lifespan=lifespan)
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_credentials=True,
                   allow_methods=["*"], allow_headers=["*"])


# ─── Health ──────────────────────────────────────────────────────────────────

@app.get("/health")
async def health():
    services = {}
    http = await get_http()

    async def probe(name: str, host: str, port: int):
        try:
            r = await http.get(f"http://{host}:{port}/health", timeout=3.0)
            services[name] = "healthy" if r.status_code < 500 else f"unhealthy ({r.status_code})"
        except Exception as e:
            services[name] = f"down ({type(e).__name__})"

    await asyncio.gather(*[probe(name, svc["host"], svc["port"]) for name, svc in SERVICE_ROUTES.items()])
    all_healthy = all(v == "healthy" for v in services.values())
    return {"status": "ok" if all_healthy else "degraded", "version": "0.2.0", "services": services}


# ─── Proxy Helper ────────────────────────────────────────────────────────────

async def _proxy(service: str, rest: str, method: str, headers: dict, body: bytes, query: str = "") -> JSONResponse:
    svc = SERVICE_ROUTES.get(service)
    if not svc:
        raise HTTPException(status_code=404, detail=f"Unknown service: {service}")

    prefix = svc.get("prefix", "")
    if rest:
        target_path = f"/{prefix}/{rest}" if prefix else f"/{rest}"
    else:
        target_path = f"/{prefix}" if prefix else "/"
    target_url = f"http://{svc['host']}:{svc['port']}{target_path}"
    if query:
        target_url += f"?{query}"

    headers = filter_headers(headers)
    headers.pop("content-length", None)

    http = await get_http()
    try:
        resp = await http.request(method=method, url=target_url, headers=headers, content=body, timeout=120.0)
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail=f"Service unreachable: {service}")
    except httpx.TimeoutException:
        raise HTTPException(status_code=504, detail=f"Service timeout: {service}")

    resp_headers = filter_headers(dict(resp.headers))
    resp_headers.pop("content-length", None)
    resp_headers.pop("content-encoding", None)

    if "application/json" in resp.headers.get("content-type", ""):
        return JSONResponse(content=resp.json(), status_code=resp.status_code, headers=resp_headers)
    return JSONResponse(content=resp.text, status_code=resp.status_code, headers=resp_headers)


# ─── Explicit Routes (must be above catch-all) ────────────────────────────────

@app.get("/api/workflows")
async def list_workflows():
    svc = SERVICE_ROUTES["workflows"]
    http = await get_http()
    try:
        resp = await http.get(f"http://{svc['host']}:{svc['port']}/api/workflows", timeout=15.0)
        return JSONResponse(content=resp.json(), status_code=resp.status_code)
    except httpx.ConnectError:
        raise HTTPException(status_code=502, detail="Workflow engine unreachable")


# ─── Catch-all Proxy ─────────────────────────────────────────────────────────

@app.api_route("/api/{service}/{rest:path}", methods=["GET","POST","PUT","DELETE","PATCH","OPTIONS","HEAD"])
async def proxy_api_path(request: Request, service: str, rest: str):
    return await _proxy(service=service, rest=rest, method=request.method,
                        headers=dict(request.headers), body=await request.body(),
                        query=request.url.query)


# ─── WebSocket Proxy ─────────────────────────────────────────────────────────

@app.websocket("/ws/events/{channel}")
async def ws_events(ws: WebSocket, channel: str):
    await proxy_websocket(ws, "events", f"/ws/{channel}")


@app.websocket("/ws/queue")
async def ws_queue(ws: WebSocket):
    await proxy_websocket(ws, "queue", "/queue/subscribe")


async def proxy_websocket(ws: WebSocket, service: str, target_path: str):
    svc = SERVICE_ROUTES.get(service)
    if not svc:
        await ws.close(code=4004, reason=f"Unknown service: {service}")
        return

    await ws.accept()
    # WebSocket relay is limited — real proxy needs websockets library.
    # Event bus also accepts HTTP POST /api/publish as fallback.
    try:
        while True:
            await ws.receive_text()
    except WebSocketDisconnect:
        logger.info("WebSocket client disconnected")
        await ws.close()


# ─── Auth Routes (Placeholders) ──────────────────────────────────────────────

@app.post("/auth/login")
async def auth_login(request: Request):
    # TODO: JWT auth (Phase 2 Step 4)
    return {"token": "PLACEHOLDER", "expires_in": 3600}

@app.post("/auth/refresh")
async def auth_refresh(request: Request):
    return {"token": "PLACEHOLDER", "expires_in": 3600}

@app.post("/auth/verify")
async def auth_verify(request: Request):
    return {"valid": True, "user": "PLACEHOLDER"}


# ─── Main ────────────────────────────────────────────────────────────────────

def main():
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=int(os.getenv("API_GATEWAY_PORT", "8000")))

if __name__ == "__main__":
    main()
