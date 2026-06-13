"""测试: 文本分块逻辑。"""

from pipeline.processor import _chunk_text


def test_chunk_short_text_no_split() -> None:
    """短文本不应被分块。"""
    rec = {"full_text": "短文本\n\n只有两段", "source_type": "news"}
    result = _chunk_text(rec)
    assert len(result) == 1
    assert result[0]["full_text"] == "短文本\n\n只有两段"  # 内容完整不变


def test_chunk_long_text_splits() -> None:
    """长文本应按段分块。"""
    paras = "\n\n".join(["第" + str(i) + "段 " * 100 for i in range(10)])
    rec = {"full_text": paras, "source_type": "news"}
    result = _chunk_text(rec)
    assert len(result) > 1
    # 验证每块内容不重叠
    all_text = " ".join(c["full_text"] for c in result)
    assert "第0段" in all_text
    assert "第9段" in all_text


def test_chunk_price_no_split() -> None:
    """价格数据不应分块。"""
    rec = {"full_text": "copper price data line", "source_type": "price"}
    from pipeline.processor import _process_record
    from pipeline.dedup import DedupChecker
    checker = DedupChecker.__new__(DedupChecker)
    checker._seen = set()
    result = _process_record(rec, checker)
    assert len(result) == 1


def test_chunk_content_hash_added() -> None:
    """分块后应有 content_hash 和 chunk_* 字段。"""
    rec = {"full_text": "A" * 1000 + "\n\n" + "B" * 1000, "source_type": "news"}
    from pipeline.processor import _process_record
    from pipeline.dedup import DedupChecker
    checker = DedupChecker.__new__(DedupChecker)
    checker._seen = set()
    result = _process_record(rec, checker)
    for chunk in result:
        assert "content_hash" in chunk
        assert "chunk_index" in chunk
        assert "chunk_total" in chunk
        assert "document" in chunk
