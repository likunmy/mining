# RAG Query + Ragas Evaluation Design

Date: 2026-06-13

## Motivation

- `/query` endpoint currently returns raw ChromaDB results only — callers must stitch together
  an answer themselves.
- Eval uses brittle keyword matching for recall@5 and faithfulness, plus a separate LLM scoring
  pass that doubles the number of LLM calls per question.
- Consolidating to ragas reduces metric noise, removes redundant LLM calls (generation only,
  no separate scoring round), and standardizes on a well-known RAG evaluation framework.

## Design

### File Changes

| File | Action | Description |
|------|--------|-------------|
| `serve/generator.py` | **Add** | Prompt templates + `format_context()` + `generate_answer()` |
| `serve/app.py` | **Edit** | `/query` calls generator; response includes `generated_answer` |
| `eval/prompts.py` | **Edit** | Remove `SCORING_*` prompts; import generation from `serve.generator` |
| `eval/evaluate.py` | **Edit** | Use ragas metrics; call `serve.generator.generate_answer()` |
| `pyproject.toml` | **Review** | `ragas>=0.3.0` and `datasets>=3.0` already present |

### Module Dependency

```
serve/generator.py          # standalone: no deps on eval or serve.app
  └─ uses llm.client.call_llm

serve/app.py                # imports generator
  └─ uses serve.retriever, serve.generator

eval/evaluate.py            # imports serve.generator.generate_answer
  └─ uses serve.retriever, serve.generator, ragas, datasets

eval/prompts.py             # re-exports from serve.generator for backward compat
  └─ imports serve.generator
```

### Data Flow

```
POST /query {question, k=10, filters...}
  ├─ retriever.query() → top-k results
  └─ generator.generate_answer(question, results[:5])
  └─ return {question, results, generated_answer, total, query_time_ms}

eval run()
  for each ground_truth item:
    ├─ retriever.query(q, k=10) → top-k results
    ├─ generator.generate_answer(question, results[:5]) → answer
    └─ ragas: context_recall + faithfulness using (question, contexts, answer, ground_truth)
```

### LLM Call Reduction

Before: per item → 1 generation + 1 scoring = 2 LLM calls (40 total for 20 questions).
After: per item → 1 generation. Ragas metrics run locally. (20 total.)

## Server Side

### `serve/generator.py` — New Module

Moves generation logic from `eval/` to `serve/`:

- `GENERATION_SYSTEM` — system prompt
- `GENERATION_USER` — user prompt template with `{context}` and `{question}`
- `format_context(docs, max_snippet_chars=600) → str` — format docs into context text
- `generate_answer(question, docs) → str | None` — retrieve, format, call LLM, return answer

No dependency on `eval.*` or `serve.app`. Pure function of `(question, docs) → answer`.

### `serve/app.py` Changes

```python
from serve.generator import generate_answer

class QueryResponse(BaseModel):
    question: str
    results: list
    generated_answer: str | None = None  # NEW
    total: int
    query_time_ms: float

# In query() handler:
result = retriever.query(req.question, k=req.k, where=where or None)
result["generated_answer"] = generate_answer(req.question, result["results"][:5])
result["question"] = req.question
return result
```

On LLM failure (`generate_answer` returns `None`), the query still returns successful HTTP 200
with `generated_answer: null` and the full result set. No partial-failure semantics.

## Evaluation Side

### `eval/prompts.py`

- Remove `SCORING_SYSTEM`, `SCORING_USER` (no longer needed)
- Re-export `GENERATION_SYSTEM`, `GENERATION_USER`, `format_context` from
  `serve.generator` for any external consumers

### `eval/evaluate.py` Changes

**Removed:**
- `recall_at_5()` — replaced by ragas `context_recall`
- `faithfulness()` — replaced by ragas `faithfulness`
- `llm_score_faithfulness()` — replaced by ragas
- `_parse_score()` — no longer needed
- `_LLM_ENABLED` flag — generation is unconditional
- Per-question LLM scoring call (the second API call per item)

**New ragas step:**

```python
from datasets import Dataset
from ragas.metrics import context_recall, faithfulness

def compute_ragas_metrics(
    question: str,
    contexts: list[str],
    answer: str,
    ground_truth: str,
) -> dict[str, float]:
    ds = Dataset.from_dict({
        "question": [question],
        "contexts": [contexts],
        "answer": [answer],
        "ground_truth": [ground_truth],
    })
    return {
        "recall@5": context_recall.score(ds),
        "faithfulness": faithfulness.score(ds),
    }
```

### Per-item Output in `eval_report.json`

```json
{
  "id": 1,
  "question": "...",
  "recall@5": 0.95,
  "faithfulness": 0.88,
  "generated_answer": "...",
  "top5_hits": ["title1", "title2", ...]
}
```

### Ragas LLM Config

Ragas internally uses LangChain for its judge LLM calls (decomposing claims, checking
faithfulness). We configure it to use the same DeepSeek endpoint:

```python
from langchain_openai import ChatOpenAI
from ragas.metrics import context_recall, faithfulness

llm = ChatOpenAI(
    model=DEEPSEEK_MODEL,
    api_key=DEEPSEEK_API_KEY,
    base_url=f"{DEEPSEEK_BASE_URL}/v1",
    temperature=0.0,
)

context_recall.llm = llm
faithfulness.llm = llm
```

## API Contract

### `POST /query` Response

```json
{
  "question": "LME铜价最近一周的走势如何？",
  "results": [
    {"id": "...", "title": "LME copper 2026-06-13", "snippet": "...", "score": 0.92, ...},
    {"id": "...", "title": "LME copper 2026-06-12", "snippet": "...", "score": 0.88, ...}
  ],
  "generated_answer": "根据2026年6月9日至13日的LME铜期货数据...",
  "total": 10,
  "query_time_ms": 152.3
}
```

Backward-compatible: `generated_answer` is additive. Existing callers ignore unrecognized fields
by default with Pydantic.

## Error Handling

- **LLM generation failure** → `generated_answer: null`, eval skips ragas for that item
  (sets `recall@5: null, faithfulness: null`)
- **Ragas metric failure** → logged as warning, null in output, rest of eval continues
- **Ground truth missing** → skip `context_recall` for that item
- **Empty retrieval results** → `generated_answer: "No relevant documents found."`

## Out of Scope

- Streaming generation for `/query`
- Multi-turn conversation
- Answer caching
- Alternative LLM providers for generation
- Batch ragas evaluation (per-item scoring is simpler and more debuggable)

## Dependencies

Already present in `pyproject.toml`:
- `ragas>=0.3.0`
- `datasets>=3.0`
