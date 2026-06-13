"""爬虫基类。"""

import hashlib
import json
import logging
import time
from abc import ABC, abstractmethod
from datetime import datetime, timezone
from random import choice
from typing import Any

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
    """所有爬虫的基类。"""

    source_type: str = ""  # "news" | "policy" | "price"

    def __init__(self) -> None:
        self.client = httpx.Client(
            timeout=REQUEST_TIMEOUT,
            follow_redirects=True,
            headers={"User-Agent": choice(USER_AGENTS)},
        )

    @abstractmethod
    def crawl(self, max_count: int = 200) -> list[dict[str, Any]]:
        """爬取数据源，返回原始记录列表。"""
        ...

    def fetch(self, url: str) -> str | None:
        """抓取 URL 内容（含错误处理）。"""
        try:
            resp = self.client.get(url)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.warning("抓取失败: %s — %s", url, e)
            return None

    def post(self, url: str, data: dict[str, str] | str | None = None,
             headers: dict[str, str] | None = None) -> str | None:
        """POST 请求（含错误处理）。"""
        try:
            resp = self.client.post(url, content=data, headers=headers)
            resp.raise_for_status()
            return resp.text
        except Exception as e:
            logger.warning("POST 失败: %s — %s", url, e)
            return None

    def make_id(self, url: str) -> str:
        raw = f"{self.source_type}_{url}".encode()
        return hashlib.sha256(raw).hexdigest()[:32]

    def content_hash(self, text: str) -> str:
        normalized = " ".join(text.strip().split())
        return hashlib.sha256(normalized.encode()).hexdigest()

    def save_raw(self, records: list[dict[str, Any]], name: str | None = None) -> None:
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        tag = name or self.source_type
        path = RAW_DIR / f"{tag}_{ts}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            for r in records:
                f.write(json.dumps(r, ensure_ascii=False) + "\n")
        logger.info("已保存 %d 条记录 → %s", len(records), path)

    def log_error(self, url: str, msg: str) -> None:
        entry = {"url": url, "error": msg, "ts": datetime.now().isoformat()}
        with open(ERROR_LOG, "a", encoding="utf-8") as f:
            f.write(json.dumps(entry, ensure_ascii=False) + "\n")

    def save_checkpoint(self, source: str, dt: datetime | None = None) -> None:
        try:
            with open(CHECKPOINT, "r") as f:
                cp: dict[str, str] = json.load(f)
        except (FileNotFoundError, json.JSONDecodeError):
            cp = {}
        cp[source] = (dt or datetime.now()).isoformat()
        with open(CHECKPOINT, "w") as f:
            json.dump(cp, f, indent=2)

    def load_checkpoint(self, source: str) -> datetime | None:
        try:
            with open(CHECKPOINT, "r") as f:
                cp: dict[str, str] = json.load(f)
            val = cp.get(source)
            return datetime.fromisoformat(val) if val else None
        except (FileNotFoundError, json.JSONDecodeError):
            return None

    def close(self) -> None:
        self.client.close()

    def sleep(self, seconds: float) -> None:
        time.sleep(seconds)

    @staticmethod
    def sanitize_text(text: str) -> str:
        """清洗爬取文本：替换非标准空白字符、统一编码问题。"""
        text = text.replace("\xa0", " ")   # non-breaking space
        text = text.replace("　", " ")  # CJK full-width space
        text = text.replace("\r\n", "\n")
        text = text.replace("\r", "\n")
        return text

    def __enter__(self) -> "BaseCrawler":
        return self

    def __exit__(self, *args: Any) -> None:
        self.close()
