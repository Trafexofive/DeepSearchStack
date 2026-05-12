"""Vector Store — ChromaDB with persistent storage for DeepSearch RAG pipeline."""
import os
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional
import chromadb
from chromadb.config import Settings

# Persistent storage path (volume-mounted in Docker)
PERSIST_DIR = os.environ.get("CHROMA_PERSIST_DIR", "/app/data")

app = FastAPI(title="Vector Store", version="1.0.0")

# Initialize ChromaDB with persistent storage
client = chromadb.Client(Settings(
    chroma_db_impl="duckdb+parquet",
    persist_directory=PERSIST_DIR,
    anonymized_telemetry=False,
))
collection = client.get_or_create_collection("documents")


class Document(BaseModel):
    id: str
    text: str
    metadata: Optional[dict] = None


class EmbedRequest(BaseModel):
    documents: List[Document]


@app.post("/embed")
async def embed_documents(req: EmbedRequest):
    try:
        collection.add(
            ids=[doc.id for doc in req.documents],
            documents=[doc.text for doc in req.documents],
            metadatas=[doc.metadata or {} for doc in req.documents],
        )
        client.persist()
        return {"message": f"Embedded {len(req.documents)} documents", "count": len(req.documents)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/query")
async def query_documents(query_text: str, n_results: int = 5):
    try:
        results = collection.query(
            query_texts=[query_text],
            n_results=n_results,
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/health")
def health_check():
    try:
        count = collection.count()
        return {"status": "healthy", "documents": count, "persist_dir": PERSIST_DIR}
    except Exception:
        return {"status": "healthy", "persist_dir": PERSIST_DIR}


@app.get("/")
def root():
    return {
        "service": "vector-store",
        "version": "1.0.0",
        "endpoints": {
            "POST /embed": "Embed documents",
            "POST /query": "Query by text",
            "GET /health": "Health check",
        },
    }
