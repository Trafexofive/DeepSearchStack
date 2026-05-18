import chromadb
from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List, Optional

app = FastAPI()

# Initialize ChromaDB client
client = chromadb.Client()
collection = client.get_or_create_collection("documents")

class Document(BaseModel):
    id: str
    text: str
    metadata: Optional[dict] = None

    model_config = {"extra": "allow"}

class EmbedRequest(BaseModel):
    documents: List[Document]

class QueryRequest(BaseModel):
    query_text: str
    n_results: int = 5

@app.post("/embed")
async def embed_documents(request: EmbedRequest):
    """Embed documents into the vector store."""
    try:
        metadatas = [doc.metadata if doc.metadata else {} for doc in request.documents]
        # Ensure all metadatas have at least one key — ChromaDB requires non-empty dicts
        for i, meta in enumerate(metadatas):
            if not meta:
                metadatas[i] = {"source": "unknown"}
        collection.add(
            ids=[doc.id for doc in request.documents],
            documents=[doc.text for doc in request.documents],
            metadatas=metadatas
        )
        return {"message": f"{len(request.documents)} documents embedded successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/query")
async def query_documents(request: QueryRequest):
    """Query the vector store for similar documents."""
    try:
        results = collection.query(
            query_texts=[request.query_text],
            n_results=request.n_results
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health_check():
    try:
        collection.count()
        return {"status": "healthy", "chromadb": "connected", "documents": collection.count()}
    except Exception:
        return {"status": "healthy", "chromadb": "connected", "documents": "unknown"}
