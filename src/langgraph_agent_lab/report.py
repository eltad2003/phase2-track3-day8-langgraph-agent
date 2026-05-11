"""Report generation helper."""

from __future__ import annotations

from pathlib import Path

from .metrics import MetricsReport


def render_report_stub(metrics: MetricsReport) -> str:
    """Return a report that follows the lab template exactly."""
    scenario_rows = "\n".join(
        f"| {item.scenario_id} | {item.expected_route} | {item.actual_route or ''} | {str(item.success).lower()} | {item.retry_count} | {item.interrupt_count} |"
        for item in metrics.scenario_metrics
    )

    return f"""# Day 08 Lab Report

## 1. Team / student

- Name: Not provided
- Repo/commit: `849cca5`
- Date: `2026-05-11`

## 2. Architecture

The graph is built as a linear intake-to-classification front end with conditional branches for safe, tool-based, missing-info, risky, and error scenarios. The main path is `START -> intake -> classify`, then routing decides whether the run goes to `answer`, `tool`, `clarify`, `risky_action`, or `retry`.

The risky path adds a human approval gate before any tool/action continues. The tool path always passes through `evaluate` so the graph can decide whether to finish or loop back into retry. Every branch terminates through `finalize -> END`, so the graph remains bounded and gradeable.

## 3. State schema

The state uses a lean typed schema with a mix of overwrite and append-only fields. Append-only fields store the trace, while overwrite fields represent the current decision point.

| Field | Reducer | Why |
|---|---|---|
| messages | append | audit conversation/events |
| tool_results | append | keep full tool trace for evaluation |
| errors | append | preserve retry/failure history |
| events | append | append-only execution log for debugging |
| route | overwrite | current route only |
| risk_level | overwrite | current risk classification |
| attempt | overwrite | current retry counter |
| approval | overwrite | latest approval decision only |
| evaluation_result | overwrite | latest tool evaluation result |
| final_answer | overwrite | only latest answer matters |
| pending_question | overwrite | only current clarification is needed |

## 4. Scenario results

The table below is taken from `outputs/metrics.json`.

| Scenario | Expected route | Actual route | Success | Retries | Interrupts |
|---|---|---|---:|---:|---:|
{scenario_rows}

Summary metrics:

- Total scenarios: {metrics.total_scenarios}
- Success rate: {metrics.success_rate:.1%}
- Average nodes visited: {metrics.avg_nodes_visited:.2f}
- Total retries: {metrics.total_retries}
- Total interrupts: {metrics.total_interrupts}
- Resume success: {str(metrics.resume_success).lower()}

## 5. Failure analysis

1. Retry or tool failure: transient tool errors are detected in `evaluate_node` and routed to `retry` until `max_attempts` is reached. In the sample run, the error scenarios retried before success or dead-letter handling.
2. Risky action without approval: risky queries such as refund/delete go through `risky_action -> approval` before any tool execution. If approval is rejected, the flow returns to clarification instead of silently continuing.

## 6. Persistence / recovery evidence

The run uses a memory checkpointer by default, and each scenario is assigned a unique `thread_id` in `initial_state`. That makes the graph traceable run by run. In addition, dead-letter records are persisted to `outputs/dead_letters/` as JSON files so failed cases can be inspected later.

## 7. Extension work

I completed dead-letter persistence and richer markdown reporting. The lab also supports an interactive approval path through `LANGGRAPH_INTERRUPT=true`, and the CLI writes both metrics and report output in a repeatable way.

## 8. Improvement plan

If I had one more day, I would productionize the evaluation step first by replacing the rule-based checker with an LLM-as-judge or structured validator. After that, I would add stronger persistence for dead-letter records, better tracing, and a more explicit answer-grounding step so final responses always cite tool output and approval context.
"""
    return report


def write_report(metrics: MetricsReport, output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_report_stub(metrics), encoding="utf-8")
