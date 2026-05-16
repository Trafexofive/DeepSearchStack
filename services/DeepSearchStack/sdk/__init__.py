"""DeepSearchStack SDK — Python client for the full DSS pipeline."""
from .client import DSSClient, SearchResult, AggregateResponse, IngestResult

__version__ = "1.0.0"
__all__ = ["DSSClient", "SearchResult", "AggregateResponse", "IngestResult"]
