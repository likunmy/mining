"""LLM 配置 — DeepSeek API。

API Key 从环境变量或项目根目录的 .env 文件读取。
"""

import os
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# 尝试加载 .env（项目根目录）
_env_path = Path(__file__).resolve().parent.parent / ".env"
if _env_path.exists():
    with open(_env_path, encoding="utf-8") as _f:
        for _line in _f:
            _line = _line.strip()
            if not _line or _line.startswith("#") or "=" not in _line:
                continue
            _key, _val = _line.split("=", 1)
            _key, _val = _key.strip(), _val.strip().strip("\"'")
            if _key and _val:
                os.environ.setdefault(_key, _val)

DEEPSEEK_API_KEY = os.environ.get("DEEPSEEK_API_KEY")
DEEPSEEK_BASE_URL = os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com")
DEEPSEEK_MODEL = os.environ.get("DEEPSEEK_MODEL", "deepseek-chat")

if not DEEPSEEK_API_KEY:
    logger.warning(
        "DEEPSEEK_API_KEY 未设置。请在 .env 文件中配置: "
        "DEEPSEEK_API_KEY=sk-xxx"
    )
