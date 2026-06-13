"""内容去重逻辑。"""

import json
from pipeline.config import CLEAN_DIR


class DedupChecker:
    """追踪 content_hash 值，避免本次运行及历史运行中的重复。"""

    def __init__(self) -> None:
        self._seen: set[str] = set()
        self._load_prior()

    def _load_prior(self) -> None:
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

    def mark_seen(self, content_hash: str) -> None:
        self._seen.add(content_hash)
