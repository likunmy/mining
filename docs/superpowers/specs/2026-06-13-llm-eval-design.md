# LLM-Based Evaluation for Mining Aggregator

Date: 2026-06-13

## Motivation

The current eval uses keyword overlap (title+snippet) for recall@5 and
faithfulness. This is brittle: semantically relevant results that use different
vocabulary are counted as misses, and keyword coverage does not measure whether
the answer is actually faithful to the retrieved context.

## Design

### Flow per question

```
Retriever.query() ─→  top-10 results
                         │
                   ┌─────┴──────┐
                   │            │
           keyword 评估     LLM 评估
           (unchanged)       │
                   │    ┌────┴────┐
                   │   生成回答   │
                   │   (question  │
                   │    + top-5   │
                   │    → DS API) │
                   │       │      │
                   │   评分 faith │
                   │   (answer    │
                   │    + context  │
                   │    → DS API) │
                   │       │      │
                   └───┬───┘──────┘
                       │
                  merge → report
```

### Module layout

- `eval/evaluate.py` — main entry (unchanged call signature)
- `eval/prompts.py` — **new**: prompt templates for generation + scoring
- `eval/evaluate.py` — extended to call `llm.client.call_llm`

No new files beyond `prompts.py`. The LLM logic lives inline in `evaluate.py`
for simplicity (only ~40 lines of orchestration).

### Prompts

**Generation prompt** (system + user):
- System: "You are a professional mining industry analyst. Answer concisely
  based only on the provided context."
- User: lists top-5 docs with relevance score + question
- Output: free-text answer (2-4 sentences)

**Scoring prompt** (system + user):
- System: "You are an evaluation judge. Rate answer faithfulness 0-5."
- User: question + context + generated answer
- Output: JSON `{"score": <0-5>, "reasoning": "<explanation>"}`

### Scoring rubric (0-5)

| Score | Meaning |
|-------|---------|
| 5     | Every claim directly supported by context |
| 4     | Most supported, minor extrapolation |
| 3     | Mixed support |
| 2     | Several unsupported or contradictory claims |
| 1     | Most claims unsupported |
| 0     | Completely unrelated |

Normalized to 0-1 as `llm_faithfulness` for comparison with keyword metrics.

### Report additions

Each per-item result gains:
- `llm_faithfulness`: normalized score (0-1)
- `llm_score`: raw 0-5 score
- `llm_reasoning`: one-sentence justification
- `generated_answer`: the LLM-generated answer

Aggregate:
- `avg_llm_faithfulness`
- `llm_calls`
- `llm_failures`

### Error handling

- API failure → mark `llm_failure=true`, skip, continue
- JSON parse failure → regex fallback for score, then skip
- No API key → warning, run keyword-only eval
- 500 ms delay between consecutive LLM calls

### Call budget

20 questions × 2 calls = 40 DeepSeek flash API calls per full eval run.
~500-1500 tokens per call.
