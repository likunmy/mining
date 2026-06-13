# Mining Aggregator — 矿业信息聚合管线

矿业新闻 + 关键矿产政策 + 大宗商品价格三源聚合检索系统。采集、清洗、向量化入库，通过自然语言查询接口检索。

## 快速开始

### 环境要求

- Python ≥ 3.11
- [uv](https://docs.astral.sh/uv/)（推荐包管理器）

### 安装依赖

```bash
uv sync
```

`uv sync` 会自动创建虚拟环境（`.venv/`）并安装所有依赖。

### 运行管线

一键执行采集 → 清洗 → 入库全流程（价格数据从新浪财经 API 实时获取）：

```bash
uv run python -m pipeline.run
```

支持分阶段执行：

```bash
uv run python -m pipeline.run --skip-crawl    # 仅处理已有数据
uv run python -m pipeline.run --skip-embed    # 只爬不入库
```

### 启动检索服务

```bash
uv run python -m serve.app
# 服务运行在 http://localhost:8000
```

### 查询示例

```bash
curl -X POST http://localhost:8000/query \
  -H "Content-Type: application/json" \
  -d '{"question": "近7天澳洲锂出口政策有何变化？", "k": 5}'
```

### 运行评估（RAGAS）

评估使用 [RAGAS](https://docs.ragas.io/) 框架计算 `context_recall`（recall@5）和
`faithfulness` 两项指标，指标由 LLM judge 逐条判断：

- **context_recall**: ground truth 中的信息有多少被检索结果覆盖
- **faithfulness**: 生成的回答有多少内容有上下文依据

```bash
uv run python -m eval.evaluate
```

### 进入虚拟环境（可选）

```bash
source .venv/Scripts/activate    # Windows Git Bash
# 之后可直接 python -m pipeline.run
```

## 项目结构

```
pipeline/         采集管线（爬虫 → 清洗 → embedding → ChromaDB）
serve/            FastAPI RAG 检索服务
  ├─ app.py       /query 端点（编排路由→检索→重排→生成）
  ├─ router.py    LLM 路由：问题 → 多路搜索计划
  ├─ retriever.py ChromaDB 多路向量/元数据检索
  ├─ reranker.py  Cross-encoder 重排
  └─ generator.py LLM 回答生成（DeepSeek）
eval/             评估套件（RAGAS: recall@5 + faithfulness，20 条 ground truth）
llm/              DeepSeek API 调用封装
tests/            单元测试
data/             （原始 JSONL / 清洗后 JSONL）
docs/             设计文档与实现计划
```

## 数据源

| 类别 | 源 | 策略 |
|------|-----|------|
| 新闻 | mining.com (RSS + Sitemap) | feedparser + trafilatura 全文提取 |
| 政策 | 中国稀土学会 / 澳洲政府政策 | handler 分发 + pypdf + trafilatura |
| 价格 | SHFE / DCE / GFEX 期货（新浪财经 API） | 实时日 K 线数据|

## 数据 Schema

详见 [DATA_NOTES.md](./DATA_NOTES.md)。

## 接口

### `POST /query`

只接受自然语言问题，所有过滤条件由 LLM 路由自动判断。

| 参数 | 类型 | 说明 |
|------|------|------|
| `question` | str | 自然语言问题 |

内部流程：LLM 路由（问题分析 → 搜索计划）→ 多路检索 → Cross-encoder 重排 → LLM 生成回答。

**响应格式：**
```json
{
  "question": "LME铜价最近一周的走势如何？",
  "results": [...],
  "generated_answer": "根据2026年6月9日至13日的LME铜期货数据...",
  "total": 10,
  "query_time_ms": 152.3
}
```

## 许可

MIT
