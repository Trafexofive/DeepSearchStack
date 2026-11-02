"""browser-renderer — Playwright Chromium rendering service.

Responsibilities:
  1. Render a URL with a realistic UA + viewport, return HTML + optional
     screenshot + blocked classification.
  2. Real article extraction on the rendered HTML via trafilatura
     (no nav/footer/sidebar pollution).
  3. Real OCR (RapidOCR / ONNX) on the screenshot — purpose-built, no
     hallucination. Used as the fallback when HTML extraction is thin.

Stateless; one shared browser context, one shared OCR engine.
"""
import asyncio
import base64
import io
import logging
import os
import re
import time
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional, List

from fastapi import FastAPI, HTTPException, Request
from playwright.async_api import async_playwright, Browser, BrowserContext, TimeoutError as PWTimeoutError
from pydantic import BaseModel, Field

from libs.common.text import extract_article

logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"))
log = logging.getLogger("browser-renderer")

UA = os.environ.get(
    "BROWSER_USER_AGENT",
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36",
)
VIEWPORT_W = int(os.environ.get("BROWSER_VIEWPORT_W", "1366"))
VIEWPORT_H = int(os.environ.get("BROWSER_VIEWPORT_H", "850"))
DEFAULT_WAIT = os.environ.get("BROWSER_DEFAULT_WAIT", "networkidle")
NAV_TIMEOUT_MS = int(os.environ.get("BROWSER_NAV_TIMEOUT_MS", "25000"))
MAX_CONCURRENT = int(os.environ.get("BROWSER_MAX_CONCURRENT", "4"))
SCREENSHOT_DIR = Path(os.environ.get("BROWSER_SCREENSHOT_DIR", "/app/screenshots"))
SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)

BLOCKED_PATTERNS = [
    re.compile(p, re.I) for p in [
        r"just a moment",
        r"checking your browser",
        r"cloudflare",
        r"please enable (javascript|js)",
        r"access denied",
        r"are you a robot",
        r"unusual traffic",
        r"captcha",
        r"cf-challenge",
        r"ddos protection",
    ]
]

_state: dict = {}
_sem = asyncio.Semaphore(MAX_CONCURRENT)
_ocr_engine = None  # initialized lazily; CPU-bound, shared across requests
_ocr_lock = asyncio.Lock()


def _init_ocr():
    """Initialize RapidOCR once. ONNX-based, CPU-only, no API key, ~80 MB."""
    global _ocr_engine
    if _ocr_engine is not None:
        return _ocr_engine
    try:
        from rapidocr_onnxruntime import RapidOCR
        _ocr_engine = RapidOCR()
        log.info("rapidocr_ready")
    except Exception as e:
        log.warning("rapidocr_init_failed: %s", e)
        _ocr_engine = False
    return _ocr_engine


def _ocr_png_bytes_sync(png_bytes: bytes) -> str:
    """Run RapidOCR on PNG bytes. Returns extracted text in reading order."""
    eng = _init_ocr()
    if not eng:
        return ""
    try:
        import numpy as np
        import cv2
        arr = np.frombuffer(png_bytes, dtype=np.uint8)
        img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
        if img is None:
            return ""
        result, _elapsed = eng(img)
        if not result:
            return ""
        # result: list of [box, text, score]; keep reading order
        lines = [r[1] for r in result if r and len(r) >= 2 and r[1]]
        return "\n".join(lines)
    except Exception as e:
        log.warning("rapidocr_run_failed: %s", e)
        return ""


async def _ocr_png_bytes(png_bytes: bytes) -> str:
    """Async wrapper — runs OCR off the event loop."""
    async with _ocr_lock:
        return await asyncio.to_thread(_ocr_png_bytes_sync, png_bytes)


# Stealth init script — overrides the obvious bot-detection signals so
# Cloudflare/Akamai/DataDome/G2 don't immediately fingerprint us as headless.
# Standard techniques (used by puppeteer-extra-plugin-stealth + playwright-extra):
#   navigator.webdriver -> false (default headless: true)
#   navigator.plugins   -> non-empty
#   navigator.languages -> set to UA-like
#   chrome.runtime      -> defined
#   permissions.query   -> return 'granted' for Notification (real Chrome does)
#   WebGL renderer/vendor -> realistic strings
_STEALTH_JS = r"""
// 1. navigator.webdriver
Object.defineProperty(navigator, 'webdriver', { get: () => false });

// 2. navigator.plugins — fake a Chrome PDF plugin list
Object.defineProperty(navigator, 'plugins', {
  get: () => {
    const arr = [
      { name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format' },
      { name: 'Chrome PDF Plugin', filename: 'internal-pdf-viewer', description: '' },
      { name: 'Chromium PDF Plugin', filename: 'internal-pdf-viewer', description: '' },
      { name: 'Microsoft Edge PDF Plugin', filename: 'internal-pdf-viewer', description: '' },
      { name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: '' },
    ];
    arr.refresh = () => {};
    return arr;
  },
});

// 3. navigator.languages — match the UA
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });

// 4. chrome.runtime — define it (headless chrome doesn't have it)
if (!window.chrome) window.chrome = {};
if (!window.chrome.runtime) window.chrome.runtime = {};

// 5. permissions.query — return granted for notifications (real Chrome's behavior)
const origQuery = navigator.permissions && navigator.permissions.query;
if (origQuery) {
  navigator.permissions.query = (params) =>
    params && params.name === 'notifications'
      ? Promise.resolve({ state: Notification.permission })
      : origQuery.call(navigator.permissions, params);
}

// 6. WebGL renderer/vendor — real Chrome on Linux returns these
const getParam = WebGLRenderingContext.prototype.getParameter;
WebGLRenderingContext.prototype.getParameter = function (p) {
  if (p === 37445) return 'Intel Inc.';                  // UNMASKED_VENDOR_WEBGL
  if (p === 37446) return 'Intel Iris OpenGL Engine';    // UNMASKED_RENDERER_WEBGL
  return getParam.call(this, p);
};

// 7. Hide playwright globals if any leaked through
delete window.__playwright;
delete window.__pwInitScripts;
"""


@asynccontextmanager
async def _lifespan(app: FastAPI):
    log.info("starting playwright (chromium, ua=%s)", UA[:60])
    pw = await async_playwright().start()
    browser = await pw.chromium.launch(
        headless=True,
        args=[
            "--no-sandbox",
            "--disable-blink-features=AutomationControlled",
            "--disable-dev-shm-usage",
            # Stealth helpers
            "--disable-features=IsolateOrigins,site-per-process,AutomationControlled",
            "--disable-site-isolation-trials",
            "--no-first-run",
            "--no-default-browser-check",
        ],
    )
    ctx = await browser.new_context(
        user_agent=UA,
        viewport={"width": VIEWPORT_W, "height": VIEWPORT_H},
        locale="en-US",
        timezone_id="America/Los_Angeles",
        # Realistic header set
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Sec-Ch-Ua": '"Chromium";v="131", "Not_A Brand";v="24"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"Linux"',
        },
    )
    # Inject stealth patches into every new page in this context.
    await ctx.add_init_script(_STEALTH_JS)
    _state.update(pw=pw, browser=browser, ctx=ctx)
    # Eager-init OCR so the first request doesn't pay the cost.
    await asyncio.to_thread(_init_ocr)
    log.info("ready (max_concurrent=%d, ocr=%s)", MAX_CONCURRENT, bool(_ocr_engine))
    try:
        yield
    finally:
        await ctx.close()
        await browser.close()
        await pw.stop()


app = FastAPI(title="DSS Browser Renderer", version="1.0.0", lifespan=_lifespan)


class RenderRequest(BaseModel):
    url: str = Field(..., min_length=1)
    screenshot: bool = False
    full_page_screenshot: bool = True
    wait: str = Field(default=DEFAULT_WAIT, description="load | domcontentloaded | networkidle")
    timeout_ms: int = Field(default=NAV_TIMEOUT_MS, ge=1000, le=60000)
    save_screenshot: bool = Field(default=False, description="Persist screenshot to volume for debug")
    extract_article: bool = Field(default=True, description="Run trafilatura on the rendered HTML")
    run_ocr: bool = Field(default=False, description="Run RapidOCR on the screenshot")
    # Auto-scroll for lazy-loaded SPAs (infinite scroll, lazy comments, etc.)
    # Each pass scrolls to bottom, waits for network-idle, then checks if new
    # content was added. Stops when no growth or scroll_passes hit. 0 disables.
    auto_scroll: bool = Field(default=False, description="Scroll-to-bottom loop for lazy content")
    scroll_passes: int = Field(default=6, ge=0, le=20)
    scroll_pause_ms: int = Field(default=900, ge=100, le=5000)


class RenderResponse(BaseModel):
    url: str
    final_url: str
    status: Optional[int]
    html: str
    html_length: int
    blocked: bool
    block_reason: Optional[str] = None
    screenshot_b64: Optional[str] = None
    screenshot_path: Optional[str] = None
    # Extracted article (trafilatura)
    article_text: Optional[str] = None
    article_title: Optional[str] = None
    article_author: Optional[str] = None
    article_published: Optional[str] = None
    article_language: Optional[str] = None
    # OCR (RapidOCR)
    ocr_text: Optional[str] = None
    elapsed_ms: int


def _classify_blocked(html: str, status: Optional[int]) -> tuple[bool, Optional[str]]:
    """Bot-interstitial detection. Anti-bot pages are TINY — full article pages
    that incidentally mention 'captcha' must not be flagged. So we only check
    patterns when the document is small enough to be an interstitial."""
    if status and status >= 400:
        return True, f"http_{status}"
    if not html:
        return True, "empty_body"
    if len(html) < 500:
        return True, "thin_body"
    # Only classify as bot-blocked if the doc is suspiciously small (Cloudflare
    # interstitials are typically <30 KB). Above that, content rules.
    if len(html) < 30_000:
        head = html[:4000].lower()
        for pat in BLOCKED_PATTERNS:
            m = pat.search(head)
            if m:
                return True, f"pattern:{m.group(0)[:40]}"
    return False, None


@app.post("/render", response_model=RenderResponse)
async def render(req: RenderRequest):
    ctx: BrowserContext = _state.get("ctx")
    if ctx is None:
        raise HTTPException(503, "browser not ready")

    t0 = time.time()
    async with _sem:
        page = await ctx.new_page()
        try:
            try:
                resp = await page.goto(req.url, wait_until=req.wait, timeout=req.timeout_ms)
            except PWTimeoutError:
                resp = None  # fall through, capture whatever rendered
            status = resp.status if resp else None

            # Auto-scroll loop for lazy-loaded SPAs. Stop when page height
            # stops growing or after scroll_passes — whichever comes first.
            if req.auto_scroll and req.scroll_passes > 0:
                last_h = 0
                for _i in range(req.scroll_passes):
                    try:
                        h = await page.evaluate(
                            "() => { window.scrollTo(0, document.body.scrollHeight); "
                            "return document.body.scrollHeight; }"
                        )
                    except Exception:
                        break
                    if int(h or 0) <= last_h:
                        break
                    last_h = int(h)
                    try:
                        await page.wait_for_load_state(
                            "networkidle", timeout=req.scroll_pause_ms
                        )
                    except PWTimeoutError:
                        pass
                # Scroll back to top so trafilatura sees full document order
                try:
                    await page.evaluate("() => window.scrollTo(0, 0)")
                except Exception:
                    pass

            html = await page.content()
            final_url = page.url

            blocked, reason = _classify_blocked(html, status)

            shot_b64 = None
            shot_path = None
            png_bytes: Optional[bytes] = None
            if req.screenshot or req.run_ocr or blocked:
                png_bytes = await page.screenshot(full_page=req.full_page_screenshot, type="png")
                shot_b64 = base64.b64encode(png_bytes).decode("ascii")
                if req.save_screenshot:
                    safe = re.sub(r"[^A-Za-z0-9._-]", "_", req.url)[:120]
                    p = SCREENSHOT_DIR / f"{int(time.time())}_{safe}.png"
                    p.write_bytes(png_bytes)
                    shot_path = str(p)

            article_text = None
            article_title = None
            article_author = None
            article_published = None
            article_language = None
            if req.extract_article and html:
                meta = extract_article(html, url=final_url or req.url, output_format="markdown")
                article_text = meta.get("content") or None
                article_title = meta.get("title")
                article_author = meta.get("author")
                article_published = meta.get("published")
                article_language = meta.get("language")

            ocr_text = None
            if req.run_ocr and png_bytes:
                ocr_text = await _ocr_png_bytes(png_bytes) or None

            return RenderResponse(
                url=req.url,
                final_url=final_url,
                status=status,
                html=html,
                html_length=len(html),
                blocked=blocked,
                block_reason=reason,
                screenshot_b64=shot_b64,
                screenshot_path=shot_path,
                article_text=article_text,
                article_title=article_title,
                article_author=article_author,
                article_published=article_published,
                article_language=article_language,
                ocr_text=ocr_text,
                elapsed_ms=int((time.time() - t0) * 1000),
            )
        finally:
            await page.close()


@app.post("/ocr-image")
async def ocr_image(request: Request):
    """OCR a single PNG/JPG POSTed as raw body bytes. Returns plain text.

    Used by the crawler's scanned-PDF fallback: PyMuPDF returns <200 words
    from a PDF → crawler renders each page to PNG → POSTs here → OCR text.
    """
    body = await request.body()
    if not body:
        raise HTTPException(400, "empty body")
    if not _init_ocr():
        raise HTTPException(503, "ocr engine not initialized")
    text = await _ocr_png_bytes(body)
    return {"text": text, "length": len(text)}


@app.get("/health")
async def health():
    ready = _state.get("ctx") is not None
    return {
        "status": "ok" if ready else "starting",
        "ready": ready,
        "ua": UA[:60],
        "ocr": bool(_ocr_engine),
    }


@app.get("/")
async def root():
    return {"service": "browser-renderer", "version": "1.0.0"}
