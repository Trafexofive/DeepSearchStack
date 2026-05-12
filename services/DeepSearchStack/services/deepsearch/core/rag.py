"""RAG stage — embed, chunk, and retrieve relevant content via vector-store."""
import hashlib
import logging
import re
from typing import List

from models import ScrapedContent, VectorChunk
from config import config

logger = logging.getLogger("deepsearch.rag")

_SENTENCE_RE = re.compile(r'(?<=[.!?])\s+')


def split_into_chunks(text: str, chunk_size: int = 1000, overlap_sentences: int = 2) -> List[str]:
    """Split text into sentence-aware overlapping chunks for embedding."""
    sentences = _SENTENCE_RE.split(text)
    if not sentences:
        return []

    chunks = []
    current_chunk = []
    current_length = 0

    for i, sentence in enumerate(sentences):
        sent_len = len(sentence)
        if current_length + sent_len > chunk_size and current_chunk:
            chunks.append(" ".join(current_chunk))
            # Keep overlap_sentences sentences for context overlap
            current_chunk = current_chunk[-overlap_sentences:] if len(current_chunk) > overlap_sentences else []
            current_length = sum(len(s) for s in current_chunk)
        current_chunk.append(sentence)
        current_length += sent_len

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks or [text]


async def embed(client, query: str, scraped_content: List[ScrapedContent], vector_store_url: str):
    """Chunk and embed scraped content into the vector store."""
    if not config.rag_config.get("store_scraped_content", True):
        return

    documents = []
    for content in scraped_content:
        chunks = split_into_chunks(
            content.content,
            chunk_size=config.rag_config.get("chunk_size", 1000),
            overlap=config.rag_config.get("chunk_overlap", 200),
        )
        for i, chunk in enumerate(chunks):
            documents.append({
                "id": hashlib.md5(f"{content.url}_{i}".encode()).hexdigest(),
                "text": chunk,
                "metadata": {
                    "url": content.url,
                    "title": content.title,
                    "chunk_index": i,
                    "query": query,
                },
            })

    if documents:
        try:
            await client.post(f"{vector_store_url}/embed", json={"documents": documents}, timeout=30.0)
        except Exception as e:
            logger.error(f"Vector store embed error: {e}")


async def retrieve(client, query: str, top_k: int, vector_store_url: str) -> List[VectorChunk]:
    """Retrieve most relevant chunks from the vector store."""
    try:
        response = await client.post(
            f"{vector_store_url}/query",
            json={"query_text": query, "n_results": top_k},
            timeout=10.0,
        )
        response.raise_for_status()
        data = response.json()

        chunks = []
        if "documents" in data and data["documents"]:
            for i, doc in enumerate(data["documents"][0]):
                metadata = data.get("metadatas", [[]])[0][i] if "metadatas" in data else {}
                distance = data.get("distances", [[]])[0][i] if "distances" in data else None
                chunks.append(VectorChunk(
                    chunk_id=data.get("ids", [[]])[0][i],
                    content=doc,
                    url=metadata.get("url", ""),
                    title=metadata.get("title", ""),
                    similarity_score=1 - distance if distance is not None else None,
                    metadata=metadata,
                ))
        return chunks
    except Exception as e:
        logger.error(f"Vector store query error: {e}")
        return []
