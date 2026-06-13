"""Content dedup logic."""

import json
from pathlib import Path
from pipeline.config import CLEAN_DIR


class DedupChecker:
    """Tracks content_hash values to skip duplicates within a run + across prior runs."""

    def __init__(self):
        self._seen: set[str] = set()
        self._load_prior()

    def _load_prior(self):
        if not CLEAN_DIR.exists():
            return
        for f in sorted(CLEAN_DIR.glob("*.jsonl")):
            with open(f, encoding="utf-8") as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                        if h := rec.get("content_hash"):
                            self._seen.add(h)
                    except json.JSONDecodeError:
                        continue

    def is_duplicate(self, content_hash: str) -> bool:
        return content_hash in self._seen

    def mark_seen(self, content_hash: str):
        self._seen.add(content_hash)
