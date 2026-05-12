from fastapi import FastAPI, HTTPException
from pydantic import BaseModel
from typing import List
import chromadb

app = FastAPI()

# Initialize ChromaDB client
client = chromadb.Client()
collection = client.get_or_create_collection("documents")

class Document(BaseModel):
    id: str
    text: str

@app.post("/embed")
async def embed_documents(documents: List[Document]):
    try:
        collection.add(
            ids=[doc.id for doc in documents],
            documents=[doc.text for doc in documents]
        )
        return {"message": "Documents embedded successfully"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/query")
async def query_documents(query_text: str, n_results: int = 5):
    try:
        results = collection.query(
            query_texts=[query_text],
            n_results=n_results
        )
        return results
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health")
def health_check():
    return {"status": "healthy"}