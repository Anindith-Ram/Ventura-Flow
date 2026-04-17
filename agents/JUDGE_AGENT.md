# Judge Agent

## Overview

The Judge Agent is the final evaluator in the Ventura Flow pipeline. It sits downstream of the **Bull Agent** (which argues aggressively FOR investment) and the **Bear Agent** (which argues skeptically AGAINST investment). The Judge Agent's job is to act as a senior VC partner: it reads both sides of the debate, traces every claim back to the underlying research evidence, and produces a rigorous investment evaluation that a real venture capitalist can act on.

The core output is the **Investability Score** — a 0-100 rating representing how worthy this signal (paper, patent, repo, etc.) is of further VC attention. This score is not computed from any formula or weighted average. It is the LLM's reasoned judgment after synthesizing the bull and bear arguments against the raw evidence.

## How It Works

The Judge Agent runs in **two passes**, both using `llama3.1:8b` via Ollama:

### Pass 1 — Investability Evaluation

The agent receives:
- The signal metadata (title, abstract, authors, institution, source type)
- The Bull Agent's full thesis (arguments, confidence, comparables, best-case scenario)
- The Bear Agent's full thesis (arguments, risks, what would change their mind)
- All raw research evidence collected by the tool registry (Semantic Scholar lookups, patent searches, GitHub data, prior signal matches)
- Graph context from prior signals in the database

It then produces six independently-reasoned scores, each with a written rationale:

| Metric | What It Captures |
|--------|-----------------|
| **Investability Score** (0-100) | The headline number. Should a VC spend time on this? Synthesizes everything below into a single judgment. |
| **Commercial Viability** (0-100) | Is there a path from this research/product to revenue? How clear is the market? How defensible is the business model? |
| **Team Signal Strength** (0-100) | What do we actually know about execution capability? Author h-index, institutional affiliation, prior exits, industry connections. |
| **Timing & Market Readiness** (0-100) | Is the market ready for this? Is there a catalyst or inflection point? Too early and too late are both problems. |
| **Competitive Moat** (0-100) | IP protection, data advantages, network effects, switching costs. What defensibility exists or is plausible? |
| **Risk-Adjusted Conviction** (0-100) | After fully accounting for the bear's strongest points, how convicted is the judge? What is the risk/reward asymmetry? |

The evaluation also includes:
- **Bull vs. Bear Adjudication**: Specific points where each side prevailed, and unresolved tensions where neither had enough evidence.
- **Evidence Quality Assessment**: How good was the evidence the research agents collected, and what gaps remain that a real diligence process would want filled.
- **One-Line Verdict**: A single sentence a GP can read in 5 seconds.
- **Recommendation**: `STRONG_FLAG`, `FLAG`, `WATCH_LIST`, or `PASS`.

### Pass 2 — Pitch Deck Memo

Using the evaluation from Pass 1, the agent generates a narrative investment memo structured for a partner meeting. This is not bullet-point output — each section is written as a paragraph a senior associate would produce.

The memo contains:
- **Executive Summary** — 2-3 sentences. What is this, why should we care, what's the conviction level.
- **The Opportunity** — What problem does this solve, market size, why now.
- **Technology Differentiation** — What is novel, what can this do that alternatives cannot.
- **Team Assessment** — What we know about the people. Honest about gaps.
- **Market Landscape** — Competitive positioning, crowded vs. white space.
- **Bull Case Narrative** — The best version of the future, with a specific path.
- **Bear Case Narrative** — The realistic failure modes, not strawmen.
- **Key Risks Ranked** — Each risk rated HIGH/MEDIUM/LOW with severity and mitigation paths.
- **What We Need to Believe** — The 2-3 core assumptions that must hold for this to be a good investment.
- **Comparable Transactions** — Relevant exits, funding rounds, or public comps.
- **Suggested Next Steps** — Concrete actions: who to call, what to research, what milestone to wait for.
- **Partner Meeting Recommendation** — `TAKE_MEETING`, `MONITOR`, or `PASS` with a one-sentence justification.

## Why Non-Formulaic Scoring Matters

Traditional approaches to scoring investment signals use weighted formulas: assign weights to categories, compute sub-scores, multiply and add. This is fast but brittle — it cannot capture the contextual reasoning a real investor uses.

For example:
- A researcher with a low h-index at a no-name institution might score poorly on "team" in a formula — but if that researcher just published the first successful demonstration of a new technique with 500 citations in 3 months, the context changes everything.
- A patent filing from a small company might have low "commercial viability" on paper, but if the bear agent couldn't find any prior art and the bull agent identified a $50B addressable market, the judge should weigh that.

The Judge Agent handles this by passing all arguments and evidence to the LLM in full context and asking it to reason through the score. The rationale field for each metric explains exactly what moved the number up and what held it back, so a VC reading the output can agree or disagree with the reasoning rather than being handed an opaque number.

## Integration

The Judge Agent plugs into the LangGraph pipeline as the `"judge"` node:

```
bull -> bear -> judge_agent -> verify -> save
```

It writes to three state fields:
- `state["scout_report"]` — Backward-compatible summary (score, recommendation, strengths, risks) used by the verification layer and the save node.
- `state["judge_evaluation"]` — The full investability evaluation with all six scored dimensions and rationales.
- `state["pitch_deck"]` — The narrative investment memo.

If the verification layer finds unsupported claims, the pipeline routes through the `reflect` node and retries the judge. On retry, the `correction_guidance` from the reflection is injected into the judge's system prompt so it avoids the same errors.

## Dependencies

- `tools/llm.py` — `call_llm(model, system_prompt, user_prompt)` for Ollama inference
- `graph/state.py` — `AgentState` TypedDict (the shared pipeline contract)
- Ollama model: `llama3.1:8b` (must be pulled before running: `ollama pull llama3.1:8b`)
