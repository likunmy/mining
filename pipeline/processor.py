import hashlib
import json
import logging
from datetime import datetime
from pathlib import Path

from pipeline.config import RAW_DIR, CLEAN_DIR
from pipeline.dedup import DedupChecker

logger = logging.getLogger(__name__)


def process_all():
    """Read all raw JSONL, dedup, chunk, write clean JSONL."""
    dedup = DedupChecker()
    clean_records = []

    raw_files = sorted(RAW_DIR.glob("*.jsonl"))
    if not raw_files:
        logger.warning("no raw files to process")
        return []

    for fpath in raw_files:
        logger.info("processing %s", fpath.name)
        with open(fpath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue

                chunks = _process_record(rec, dedup)
                clean_records.extend(chunks)

    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    out_path = CLEAN_DIR / f"all_{ts}.jsonl"
    CLEAN_DIR.mkdir(parents=True, exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        for rec in clean_records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")

    logger.info("clean records written: %d → %s", len(clean_records), out_path)
    return clean_records


def _process_record(rec: dict, dedup: DedupChecker) -> list[dict]:
    source_type = rec.get("source_type", "unknown")
    text = rec.get("full_text", "")
    if not text or len(text.strip()) < 20:
        return []

    # Content dedup
    h = hashlib.sha256(text.strip().encode()).hexdigest()
    if dedup.is_duplicate(h):
        return []
    dedup.mark_seen(h)

    # Determine chunk strategy
    if source_type == "price":
        chunks = [rec]  # price records are already single-row
    else:
        chunks = _chunk_text(rec)

    for i, chunk in enumerate(chunks):
        chunk["content_hash"] = h
        doc_text = chunk.get("full_text", "")
        chunk["chunk_index"] = i
        chunk["chunk_total"] = len(chunks)
        # document field = full_text for embedding
        chunk["document"] = doc_text

    return chunks


def _chunk_text(rec: dict) -> list[dict]:
    """Split long text into paragraph-level chunks."""
    text = rec.get("full_text", "")
    if not text:
        return [rec]

    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
    # If few paragraphs, keep as single chunk
    if len(paragraphs) <= 3:
        return [rec]

    chunks = []
    current = []
    current_len = 0
    target = 500  # approximate char target per chunk

    for para in paragraphs:
        if current_len + len(para) > target and current:
            chunk_rec = dict(rec)
            chunk_rec["full_text"] = "\n\n".join(current)
            chunks.append(chunk_rec)
            current = []
            current_len = 0
        current.append(para)
        current_len += len(para)

    if current:
        chunk_rec = dict(rec)
        chunk_rec["full_text"] = "\n\n".join(current)
        chunks.append(chunk_rec)

    return chunks
