# 矿业信息聚合管道 — 数据与技术说明

## 项目架构

```
                        ┌─────────────┐
                        │ NewsCrawler │─── RSS feeds
                        ├─────────────┤
                        │PolicyCrawler│─── 政策源 (handler 分发)
                        ├─────────────┤
                        │ PriceCrawler│─── 新浪财经期货 API
                        └──────┬──────┘
                               │ raw/*.jsonl
                               ▼
                        ┌─────────────┐
                        │  processor  │─── 清洗 + 去重 + 分块
                        └──────┬──────┘
                               │ clean/*.jsonl
                               ▼
                        ┌─────────────┐
                        │  embedder   │─── BGE embedding → ChromaDB
                        └─────────────┘

    ┌────────────┐     ┌────────────┐     ┌────────────┐     ┌────────────┐
    │   Router   │ ──▶ │  Retriever │ ──▶ │  Reranker  │ ──▶ │  Generator │
    │ (LLM 路由) │     │ (ChromaDB) │     │ (CrossEnc) │     │ (LLM 生成) │
    └────────────┘     └────────────┘     └────────────┘     └────────────┘
                                                                   │
    POST /query ────────────────────────────────────────────────────┘
                              response { answer, results }
```

---

## 目录

- [管线：crawl → process → embed](#管线crawl--process--embed)
  - [1. 爬虫 Crawlers](#1-爬虫-crawlers)
  - [2. 清洗 Processor](#2-清洗-processor)
  - [3. 入库 Embedder](#3-入库-embedder)
- [查询：POST /query](#查询post-query)
  - [Router — LLM 路由](#router--llm-路由)
  - [Retriever — ChromaDB 检索](#retriever--chromadb-检索)
  - [Reranker — Cross-Encoder 重排](#reranker--cross-encoder-重排)
  - [Generator — LLM 答案生成](#generator--llm-答案生成)
- [LLM 模块](#llm-模块)
- [评估 Eval](#评估-eval)
- [CLI 用法](#cli-用法)

---

## 管线：crawl → process → embed

### 1. 爬虫 Crawlers

三种爬虫统一继承 `BaseCrawler`，提供 `fetch()` / `post()` / `save_raw()` / `log_error()` / `checkpoint` 等基础能力。

#### NewsCrawler — 矿业新闻

- **源**：RSS feeds + Sitemap 补充
- **配置**：`NEWS_RSS_URLS`（7 个矿业媒体 RSS）
- **策略**：解析 RSS → 提取链接 → trafilatura 全文提取 → 过滤 30 天内的文章
- **目标**：每源最高 200 条

#### PolicyCrawler — 政策文档

基于 handler 的分发架构：

1. `_crawl_source(src, max_count)` 读取 `src["handler"]` 字段
2. 路由到 `_crawl_{handler}(src, max_count)` 方法
3. 各 handler 实现自己的抓取策略

| Handler | 策略 | 适用场景 |
|---------|------|----------|
| `ac_rei` | POST JSON 分页 API → 逐篇抓取文章 | 中国稀土学会（JSON API） |
| `aus_pdf` | httpx 流式下载 → 临时文件 → pypdf 提取 | 大型 PDF 文件（如战略规划） |
| `aus_req` | 列表页 → 版本链接 → PDF 下载 | Resources and Energy Quarterly |
| `aus_policy` | 直接 fetch → trafilatura 正文提取 | 普通政策网站 |

当前政策源：

| 配置 key | 名称 | jurisdiction | handler |
|----------|------|-------------|---------|
| `ac_rei` | 中国稀土学会 | CN | `ac_rei` |
| `aus_critical_minerals` | Australia's Critical Minerals Strategy 2023-2030 | AU | `aus_pdf` |
| `aus_req` | Resources and Energy Quarterly 2025 | AU | `aus_req` |
| `aus_aimr` | Australia's Identified Mineral Resources 2025 | AU | `aus_policy` |
| `aus_industry` | Australian Government - Resources | AU | `aus_policy` |

注意：澳洲政府站点（industry.gov.au、ga.gov.au）在中国网络下可能超时，需在海外网络运行。

#### PriceCrawler — 期货价格

- **源**：新浪财经期货 API（实时行情，无模拟回退）
- **品种**：铜(CAD) / 锌(ZSD) / 镍(NID) / 锂(LC0) / 铁矿石(I0)
- **API 差异处理**：外盘 GlobalFuturesService（标准字段名）vs 内盘 InnerFuturesNewService（短字段名 `d/o/h/l/c/v`），通过 `_normalize_item()` 统一映射
- **日期**：自动获取最近 30 个交易日
- **数据字段**：open / high / low / close / settle / volume

### 2. 清洗 Processor

`pipeline/processor.py` — `process_all()`

- 读取 `data/raw/*.jsonl`
- 内容去重（`DedupChecker`，基于 `content_hash`，跨运行 + 运行内）
- 价格数据保持单条，新闻/政策按段落分块（~800 chars/块）
- 写入 `data/clean/all_{timestamp}.jsonl`

### 3. 入库 Embedder

`pipeline/embedder.py` — `embed_all()`

- 加载 `BAAI/bge-small-zh-v1.5` 嵌入模型
- 连接 ChromaDB（持久化存储在 `chroma_data/`）
- 批量 upsert（每批 100 条），幂等覆盖
- 单集合 `mining_aggregator` + 富元数据模式，距离度量 cosine

---

## 查询：POST /query

完整流程：

```
question → Router(LLM) → search_plan[ ]
                              │
                    Retriever.multi_query(plans)
                              │
                     Reranker.rerank(question, results)
                              │
                news_policy[:5] + price_all → context_docs
                              │
                    Generator(LLM) → answer
```

### Router — LLM 路由

`serve/router.py` → `plan(question)` → `SearchPlanResult`

- 调用 DeepSeek 分析问题，输出 JSON 格式搜索计划
- 根据问题类型确定：source_types（news/policy/price）、查询文本、过滤条件
- 价格类问题 → query 设为 null，通过 commodity where 条件精确查找
- 中文新闻 → 同时搜索中英文；中国政策 → 中文搜索；国际政策 → 英文搜索
- 解析失败时有兜底策略（单次混合向量搜索）

### Retriever — ChromaDB 检索

`serve/retriever.py` → `Retriever`

- **价格数据**：不经过向量检索，按品种 + 日期降序精确匹配（`collection.get` + where 过滤）
- **新闻/政策**：BGE embedding 编码 → ChromaDB 向量检索（top-10）
- 品种自动检测（中英文别名匹配，如 "copper" / "铜" / "cu"）
- `multi_query()` 执行多个搜索计划并去重合并

### Reranker — Cross-Encoder 重排

`serve/reranker.py` → `Reranker`

- 模型：`BAAI/bge-reranker-v2-m3`
- **价格数据不参与重排**，直接追加到结果末尾
- 仅对 news/policy 结果进行 cross-encoder 评分 → 降序排列
- 最终输出：`news_policy_top5 + price_all`

### Generator — LLM 答案生成

`serve/generator.py` → `generate_answer(question, docs)`

- 将检索结果格式化为上下文（title + snippet + score）
- 调用 DeepSeek，严格基于上下文回答问题
- 提示词为中文，约束 2-4 句简洁回答
- 上下文不足时说明缺失内容

---

## LLM 模块

`llm/client.py` — 统一封装 DeepSeek API 调用（OpenAI-compatible）

- `call_llm(messages, **kwargs)` — 基础调用
- `call_llm_structured(messages, system_prompt=...)` — 带 system prompt 的便捷封装
- 配置通过 `.env` 或环境变量：`DEEPSEEK_API_KEY`, `DEEPSEEK_BASE_URL`, `DEEPSEEK_MODEL`
- 错误处理：API key 缺失、HTTP 错误、JSON 解析错误
- 支持推理模型（`reasoning_content` 回退）

---

## 评估 Eval

`eval/evaluate.py` — 基于 RAGAS 的离线评估

- **指标**：`context_recall`（recall@5）、`faithfulness`（忠实度）
- **评估流程**：
  1. 加载 `ground_truth.json`（含 question + expected_answer）
  2. 对每个问题：Router → Retriever → Reranker → Generator
  3. RAGAS 评分（以 DeepSeek 为 judge LLM）
- 结果写入 `eval/results/eval_report.json`

---

## CLI 用法

### 运行完整管线

```bash
uv run mining-pipeline             # crawl → process → embed
uv run mining-pipeline --skip-crawl   # 仅处理 + 入库
uv run mining-pipeline --skip-process # 仅抓取 + 入库
uv run mining-pipeline --skip-embed   # 仅抓取 + 处理
```

### 启动服务

```bash
uv run mining-server    # 默认 0.0.0.0:8000
```

API：

- `POST /query` — `{"question": "..."}` → `{answer, results}`
- `GET /health` — 健康检查

### 测试爬虫

```bash
# 列出可用政策源
uv run -m pipeline.crawlers.policy_crawler --list

# 测试单源
uv run -m pipeline.crawlers.policy_crawler --source ac_rei --count 3 --full

# 测试价格爬虫
uv run -m pipeline.crawlers.price_crawler

# 测试新闻爬虫
uv run -m pipeline.crawlers.news_crawler
```

### 运行评估

```bash
uv run -m eval.evaluate
```

### 测试查询

项目根目录有 `test_query.http`，可在 VS Code REST Client 中直接测试各种查询场景。

---

## 数据存储结构

### ChromaDB 核心元数据字段

| 字段 | 类型 | 说明 |
|------|------|------|
| `id` | str (hash) | 主键：`sha256(source_type + url)` 前 32 字符 |
| `document` | str | embedding 用文本（段落级分块） |
| `metadata.source_type` | str | `news` / `policy` / `price` |
| `metadata.url` | str | 原文链接 |
| `metadata.title` | str | 标题 |
| `metadata.published_at` | str | 发布时间（ISO 8601） |
| `metadata.language` | str | `zh` / `en` |
| `metadata.content_hash` | str | `sha256(归一化文本)`，用于跨 URL 去重 |

### 元数据约束

- 仅支持 `str` / `int` / `float` / `bool`
- 字符串截断至 1000 字符
- 无嵌套 dict（写入前拍平）
- 最小文本长度：20 字符

### 文件存储

```
data/
├── raw/{source_type}_{timestamp}.jsonl    # 原始爬取
├── clean/all_{timestamp}.jsonl            # 清洗分块后
chroma_data/                               # ChromaDB 持久化
```
