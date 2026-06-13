"""FastAPI retrieval server."""

from serve.app import app
from serve.retriever import Retriever

__all__ = ["app", "Retriever"]
