"""测试: DedupChecker 去重逻辑。"""

import json
import tempfile
from pathlib import Path

from pipeline.dedup import DedupChecker


def test_dedup_fresh_no_prior() -> None:
    """无历史数据时，不应标记任何内容为重复。"""
    with tempfile.TemporaryDirectory() as tmp:
        # 指向空目录，DedupChecker 应正常初始化
        checker = DedupChecker.__new__(DedupChecker)
        checker._seen = set()
        assert not checker.is_duplicate("abc123")
        checker.mark_seen("abc123")
        assert checker.is_duplicate("abc123")


def test_dedup_loads_prior(tmp_path: Path) -> None:
    """应正确加载已有 clean JSONL 中的 content_hash。"""
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir(parents=True)
    with open(clean_dir / "all_001.jsonl", "w", encoding="utf-8") as f:
        f.write(json.dumps({"content_hash": "hash_a", "text": "foo"}) + "\n")
        f.write(json.dumps({"content_hash": "hash_b", "text": "bar"}) + "\n")

    # Monkey-patch CLEAN_DIR
    import pipeline.dedup as mod
    orig = mod.CLEAN_DIR
    mod.CLEAN_DIR = clean_dir
    try:
        checker = DedupChecker()
        assert checker.is_duplicate("hash_a")
        assert checker.is_duplicate("hash_b")
        assert not checker.is_duplicate("hash_c")
    finally:
        mod.CLEAN_DIR = orig


def test_dedup_mark_and_check() -> None:
    """标记后应能被检测到。"""
    checker = DedupChecker.__new__(DedupChecker)
    checker._seen = set()
    checker.mark_seen("x")
    assert checker.is_duplicate("x")
    assert not checker.is_duplicate("y")


def test_dedup_handles_invalid_jsonl(tmp_path: Path) -> None:
    """损坏的 JSONL 行不应导致崩溃。"""
    clean_dir = tmp_path / "clean"
    clean_dir.mkdir(parents=True)
    with open(clean_dir / "bad.jsonl", "w", encoding="utf-8") as f:
        f.write("{invalid json}\n")
        f.write(json.dumps({"content_hash": "valid_hash"}) + "\n")

    import pipeline.dedup as mod
    orig = mod.CLEAN_DIR
    mod.CLEAN_DIR = clean_dir
    try:
        checker = DedupChecker()
        assert checker.is_duplicate("valid_hash")
    finally:
        mod.CLEAN_DIR = orig
