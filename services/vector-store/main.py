"""Vector Store — ChromaDB persistent storage for DeepSearch RAG pipeline.

Uses ChromaDB's built-in ONNX embedding function (all-MiniLM-L6-v2, 384-dim).
No external model download needed — ChromaDB bundles it.
"""
import os
import logging
import hashlib
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
import chromadb
from chromadb.utils import embedding_functions

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s [vector-store] %(message)s")
log = logging.getLogger("vector-store")

PERSIST_DIR = os.environ.get("CHROMA_PERSIST_DIR", "/app/data")
COLLECTION_NAME = os.environ.get("CHROMA_COLLECTION", "documents")

app = FastAPI(title="DeepSearch Vector Store", version="1.0.0")

os.makedirs(PERSIST_DIR, exist_ok=True)
client = chromadb.PersistentClient(path=PERSIST_DIR)

# ChromaDB's built-in ONNX embedding — auto-downloads on first use
embed_fn = embedding_functions.DefaultEmbeddingFunction()
collection = client.get_or_create_collection(
    COLLECTION_NAME,
    embedding_function=embed_fn,
)
log.info(f"ChromaDB ready: {collection.count()} docs in {PERSIST_DIR}/{COLLECTION_NAME}")


# ─── Models ──────────────────────────────────────────────────────────────────

class Document(BaseModel):
    id: Optional[str] = None
    text: str = Field(..., min_length=1)
    metadata: Optional[Dict[str, Any]] = None
    url: Optional[str] = None
    title: Optional[str] = None


class EmbedRequest(BaseModel):
    documents: List[Document]
    namespace: Optional[str] = None


class DeleteRequest(BaseModel):
    ids: Optional[List[str]] = None
    namespace: Optional[str] = None
    delete_all: bool = False


def _generate_id(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:16]


def _sanitize_metadata(meta: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    if not meta:
        return {}
    return {k: v if isinstance(v, (str, int, float, bool)) else str(v) for k, v in meta.items() if v is not None}


# ─── Endpoints ───────────────────────────────────────────────────────────────

@app.post("/embed")
async def embed_documents(req: EmbedRequest):
    if not req.documents:
        raise HTTPException(status_code=400, detail="No documents provided")

    ids, texts, metadatas = [], [], []
    for doc in req.documents:
        doc_id = doc.id or _generate_id(doc.text)
        if namespace := req.namespace:
            doc_id = f"{namespace}:{doc_id}"
        meta = _sanitize_metadata(doc.metadata)
        meta["namespace"] = req.namespace or ""
        if doc.url:
            meta["url"] = doc.url
        if doc.title:
            meta["title"] = doc.title
        ids.append(doc_id)
        texts.append(doc.text)
        metadatas.append(meta)

    log.info(f"Embedding {len(texts)} documents")
    collection.upsert(ids=ids, documents=texts, metadatas=metadatas)
    log.info(f"Total docs after embed: {collection.count()}")
    return {"message": f"Embedded {len(texts)} documents", "count": len(texts), "total_docs": collection.count()}


@app.post("/query")
async def query_post(req: dict):
    query_text = req.get("query_text") or req.get("query", "")
    n_results = req.get("n_results", 5)
    namespace = req.get("namespace")
    return await _do_query(query_text, n_results, namespace)


@app.get("/query")
async def query_get(query_text: str = "", n_results: int = 5, namespace: Optional[str] = None):
    return await _do_query(query_text, n_results, namespace)


async def _do_query(query_text: str, n_results: int, namespace: Optional[str]):
    if not query_text:
        raise HTTPException(status_code=400, detail="query_text required")
    where = {"namespace": namespace} if namespace else None
    results = collection.query(query_texts=[query_text], n_results=n_results, where=where)
    return results


@app.delete("/documents")
async def delete_documents(req: DeleteRequest):
    if req.delete_all:
        count = collection.count()
        if count > 0:
            all_ids = collection.get()["ids"]
            collection.delete(ids=all_ids)
        return {"deleted": count, "action": "delete_all"}
    elif req.ids:
        collection.delete(ids=req.ids)
        return {"deleted": len(req.ids)}
    elif req.namespace:
        collection.delete(where={"namespace": req.namespace})
        return {"deleted": "namespace", "namespace": req.namespace}
    raise HTTPException(status_code=400, detail="ids, namespace, or delete_all required")


@app.get("/health")
def health_check():
    try:
        return {"status": "healthy", "documents": collection.count(), "persist_dir": PERSIST_DIR}
    except Exception as e:
        return {"status": "degraded", "error": str(e)}


@app.get("/")
def root():
    return {
        "service": "vector-store",
        "version": "1.0.0",
        "embedding": "chromadb-default (all-MiniLM-L6-v2 ONNX)",
        "endpoints": {
            "POST /embed": "Embed documents",
            "POST /query": "Semantic query",
            "GET /query?query_text=...": "Semantic query (GET)",
            "DELETE /documents": "Delete by ID or namespace",
            "GET /health": "Health check",
        },
    }
