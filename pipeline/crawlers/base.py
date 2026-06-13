import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from pathlib import Path
from random import choice

import httpx

from pipeline.config import (
    RAW_DIR,
    ERROR_LOG,
    CHECKPOINT,
    REQUEST_TIMEOUT,
    USER_AGENTS,
)

logger = logging.getLogger(__name__)


class BaseCrawler(ABC):
    """Base class for all crawlers."""

    source_type: str = ""  # "news" | "policy" | "price"

    def __init__(self):
        self.client = httpx.Client(
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": choice(USER_AGENTS)},
        )

    @abstractmethod
    def crawl(self, max_count: int = 200) -> list[dict]:
        """Crawl source and return list of raw records."""
        ...

    def fetch(self, url: str) -> str | None:
        """Fetch URL content with error handling."""
        try:
            resp = self.client.get(url)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.warning("fetch failed: %s — %s", url, e)
            return None

    def make_id(self, url: str) -> str:
        raw = f"{self.source_type}_{url}".encode()
        return hashlib.sha256(raw).hexdigest()[:32]

    def content_hash(self, text: str) -> str:
        normalized = " ".join(text.strip().split())
        return hashlib.sha256(normalized.encode()).hexdigest()

    def save_raw(self, records: list[dict], name: str | None = None):
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        tag = name or self.source_type
        path = RAW_DIR / f"{tag}_{ts}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        logger.info("saved %d records → %s", len(records), path)

    def log_error(self, url: str, msg: str):
        entry = {"url": url, "error": msg, "ts": datetime.now().isoformat()}
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def save_checkpoint(self, source: str, dt: datetime | None = None):
        try:
            with open(CHECKPOINT, "r") as f:
                cp = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            cp = {}
        cp[source] = (dt or datetime.now()).isoformat()
        with open(CHECKPOINT, "w") as f:
            json.dump(cp, f, indent=2)

    def load_checkpoint(self, source: str) -> datetime | None:
        try:
            with open(CHECKPOINT, "r") as f:
                cp = json.load(f)
            val = cp.get(source)
            return datetime.fromisoformat(val) if val else None
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def close(self):
        self.client.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
