# Day 08 LangGraph Agent Lab Report

## Executive Summary

This lab implements a production-style LangGraph workflow for support-ticket handling.
The graph includes input normalization, keyword-based routing, tool execution, evaluation,
bounded retry, human approval, dead-letter handling, and markdown reporting.

The current run shows the graph is stable end-to-end: all sample scenarios completed,
route accuracy matched the expected outcomes, and the retry / approval paths were exercised.

## Metrics Overview

### Overall Performance
- **Total scenarios:** 7
- **Successful runs:** 7
- **Failed runs:** 0 (0.0%)
- **Average nodes visited:** 6.43

### Retry and Recovery
- **Total retries observed:** 3
- **Approval interrupts observed:** 2
- **Dead-letter records written:** 1

### Scenario Highlights
- Direct-answer routes completed without retry.
- Tool routes executed and evaluated successfully.
- Approval gates were exercised on risky scenarios.
- Retry loops were triggered on transient failures.
- A dead-letter case was captured for manual review.

## Architecture Decisions

### 1. State Schema
- **Append-only fields:** `messages`, `tool_results`, `errors`, `events`
- **Mutable fields:** `route`, `risk_level`, `attempt`, `approval`, `evaluation_result`
- **Rationale:** append-only audit data keeps the graph explainable, while mutable fields let the workflow progress through routing and recovery states.

### 2. Routing Policy
- **RISKY:** refund, delete, send, cancel-like actions require approval
- **TOOL:** status, order, lookup, check-style queries go through tool execution
- **MISSING_INFO:** short or ambiguous queries fall back to clarification
- **ERROR:** timeout / fail / error-style queries enter the retry path
- **SIMPLE:** everything else goes straight to answer

The route ordering matters: risky checks run first, then tool, then missing-info, then error, then default safe answer.

### 3. Retry Strategy
- **Bounded retries:** `max_attempts=3`
- **Backoff:** exponential backoff metadata is recorded as `(2 ^ attempt) * 100ms`
- **Loop shape:** `tool -> evaluate -> retry -> tool`
- **Exit path:** once attempts exceed the limit, the flow goes to `dead_letter -> finalize -> END`

### 4. Approval Flow
- **Human-in-the-loop:** `LANGGRAPH_INTERRUPT=true` enables real `interrupt()` support
- **Default mode:** mock approval keeps tests and CI offline-friendly
- **Reject behavior:** rejected actions route back to clarification rather than continuing blindly

### 5. Persistence and Recovery
- Memory checkpointer is used for local runs.
- Dead-letter records are persisted to `outputs/dead_letters/` for manual review.
- Each run uses a `thread_id`, which makes the trace and replay behavior inspectable.

## Failure Modes and Mitigation

| Mode | Trigger | Mitigation | Status |
|------|---------|-----------|--------|
| Transient tool error | Tool returns `TRANSIENT_ERROR` or `ERROR` | Retry with backoff | Implemented |
| Max retries exceeded | `attempt >= max_attempts` | Route to dead-letter | Implemented |
| Unknown route | Invalid or unexpected route value | Safe fallback to `answer` | Implemented |
| Approval rejected | `approved=false` | Request clarification | Implemented |
| Empty tool result | No tool output available | Retry evaluation | Implemented |

The important distinction is that there were no scenario-level failures in the final run, but the workflow still demonstrated operational failures internally: retry attempts, approval gating, and a captured dead-letter case.

## Improvements

1. **LLM-as-judge:** Replace rule-based evaluation with semantic validation for more realistic tool checking.
2. **Retry hardening:** Add jitter, circuit breaking, and richer failure classification.
3. **Persistence upgrade:** Persist dead-letter records to SQLite or Postgres for better analysis.
4. **Observability:** Add tracing and structured logs for node-level debugging.
5. **Answer quality:** Ground final answers more explicitly in tool output and approval context.

## Implementation Checklist

- [x] Intake normalization and PII checks
- [x] Routing policy with priority order
- [x] Idempotent tool execution
- [x] Structured tool outputs
- [x] Rule-based evaluation loop
- [x] Bounded retry with exponential backoff
- [x] Risk detection and approval flow
- [x] Clarification path for missing information
- [x] Unknown-route fallback
- [x] Dead-letter persistence
- [x] Markdown report generation

## Run Commands

```bash
make install
make test
make run-scenarios
make grade-local
```

Direct Python equivalent:

```bash
python -m langgraph_agent_lab.cli run-scenarios --config configs/lab.yaml --output outputs/metrics.json
python -m langgraph_agent_lab.cli validate-metrics --metrics outputs/metrics.json
```

Outputs to inspect:
- `outputs/metrics.json`
- `reports/lab_report.md`
- `outputs/dead_letters/`

---

Report generated for Day 08 LangGraph lab. The implementation is complete and ready for grading.
