"""清洗 + 去重 + 分块。"""

import hashlib
import json
import logging
from datetime import datetime
from typing import Any

from pipeline.config import RAW_DIR, CLEAN_DIR
from pipeline.dedup import DedupChecker

logger = logging.getLogger(__name__)


def process_all() -> list[dict[str, Any]]:
    """读取所有原始 JSONL，去重、分块，写入清洗后 JSONL。"""
    dedup = DedupChecker()
    clean_records: list[dict[str, Any]] = []

    raw_files = sorted(RAW_DIR.glob("*.jsonl"))
    if not raw_files:
        logger.warning("无原始数据需要处理")
        return []

    for fpath in raw_files:
        logger.info("处理 %s", fpath.name)
        with open(fpath, encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rec: dict[str, Any] = json.loads(line)
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

    logger.info("清洗完成: %d 条 → %s", len(clean_records), out_path)
    return clean_records


def _process_record(rec: dict[str, Any], dedup: DedupChecker) -> list[dict[str, Any]]:
    source_type = rec.get("source_type", "unknown")
    text = rec.get("full_text", "")
    if not text or len(text.strip()) < 20:
        return []

    # 内容去重
    h = hashlib.sha256(text.strip().encode()).hexdigest()
    if dedup.is_duplicate(h):
        return []
    dedup.mark_seen(h)

    # 按源类型选择分块策略
    if source_type == "price":
        chunks = [rec]  # 价格数据已是一条一行
    else:
        chunks = _chunk_text(rec)

    for i, chunk in enumerate(chunks):
        chunk["content_hash"] = h
        doc_text = chunk.get("full_text", "")
        chunk["chunk_index"] = i
        chunk["chunk_total"] = len(chunks)
        chunk["document"] = doc_text  # embedding 用字段

    return chunks


def _chunk_text(rec: dict[str, Any]) -> list[dict[str, Any]]:
    """按段落分块长文本，合并短段以达到目标字符数。"""
    text = rec.get("full_text", "")
    if not text:
        return [rec]

    # 优先用双换行分割段落
    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]

    # 若无双换行，尝试单换行
    if len(paragraphs) <= 1:
        paragraphs = [p.strip() for p in text.split("\n") if p.strip()]

    # 文本过短或不可分，作为单块
    if len(paragraphs) <= 1:
        return [rec]

    chunks: list[dict[str, Any]] = []
    current: list[str] = []
    current_len = 0
    target = 800  # 每块目标字符数（≈中文字符数）

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

