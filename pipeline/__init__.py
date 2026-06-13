"""Mining data aggregation pipeline."""

from pipeline.config import (
    BASE_DIR, DATA_DIR, CHROMA_DIR, EMBEDDING_MODEL, CHROMA_COLLECTION,
)

__all__ = [
    "BASE_DIR", "DATA_DIR", "CHROMA_DIR", "EMBEDDING_MODEL", "CHROMA_COLLECTION",
    "DedupChecker", "process_all", "embed_all", "run", "cli",
]


def __getattr__(name):
    """Lazy import for heavy modules (embedder pulls in torch/sentence-transformers)."""
    if name == "DedupChecker":
        from pipeline.dedup import DedupChecker
        return DedupChecker
    if name == "process_all":
        from pipeline.processor import process_all
        return process_all
    if name == "embed_all":
        from pipeline.embedder import embed_all
        return embed_all
    if name in ("run", "cli"):
        from pipeline.run import run as _run, cli as _cli
        return {"run": _run, "cli": _cli}[name]
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
