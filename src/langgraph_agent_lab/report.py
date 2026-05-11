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


def render_state_history(
    thread_id: str,
    history: list[dict],
    scenario_id: str = "unknown",
) -> str:
    """Generate markdown report of state history for time-travel debugging.

    Creates a timeline showing all checkpoint visits, node transitions, and
    state changes for post-mortem analysis of graph execution.

    Args:
        thread_id: Thread identifier for execution
        history: Checkpoint history from load_state_history()
        scenario_id: Scenario identifier (optional, for context)

    Returns:
        Markdown-formatted state history timeline
    """
    from datetime import datetime

    # Extract node path from history
    nodes_path = _extract_node_path(history)

    # Build timeline
    timeline_lines = [
        f"# State History Replay: {scenario_id}",
        f"**Thread ID**: `{thread_id}`",
        f"**Checkpoints**: {len(history)}",
        f"**Node Path**: {' → '.join(nodes_path)}",
        "",
        "## Timeline",
        "",
    ]

    for idx, record in enumerate(history, 1):
        checkpoint_id = record.get("checkpoint_id", f"ckpt_{idx}")
        metadata = record.get("metadata", {})
        checkpoint = record.get("checkpoint", {})

        # Extract state values
        state_values = checkpoint.get(
            "values", {}) if isinstance(checkpoint, dict) else {}

        # Build checkpoint section
        timeline_lines.append(f"### Checkpoint {idx}: {checkpoint_id}")
        timeline_lines.append("")

        # State snapshot
        if state_values:
            timeline_lines.append("**State Snapshot**:")
            timeline_lines.append("```python")

            # Show key fields
            important_fields = [
                "route",
                "risk_level",
                "attempt",
                "approval",
                "evaluation_result",
            ]
            for field in important_fields:
                if field in state_values:
                    value = state_values[field]
                    timeline_lines.append(f"{field}: {repr(value)}")

            timeline_lines.append("```")
            timeline_lines.append("")

        # Metadata
        if metadata:
            if "step" in metadata:
                step_info = metadata["step"]
                if isinstance(step_info, dict) and "node" in step_info:
                    node_name = step_info["node"]
                    timeline_lines.append(f"**Node**: `{node_name}`")

            if "index" in metadata:
                timeline_lines.append(f"**Step**: {metadata['index']}")

        # Append-only fields summary
        if "messages" in state_values:
            msg_count = len(state_values["messages"]) if isinstance(
                state_values["messages"], list) else 0
            timeline_lines.append(f"**Messages**: {msg_count} events")

        if "events" in state_values:
            events = state_values["events"]
            if isinstance(events, list) and events:
                latest_event = events[-1]
                if isinstance(latest_event, dict):
                    event_msg = latest_event.get("message", "")
                    timeline_lines.append(f"**Latest Event**: {event_msg}")

        if "errors" in state_values:
            err_count = len(state_values["errors"]) if isinstance(
                state_values["errors"], list) else 0
            if err_count > 0:
                timeline_lines.append(f"⚠️ **Errors**: {err_count} recorded")

        timeline_lines.append("")

    # Summary section
    timeline_lines.extend([
        "---",
        "",
        "## Execution Summary",
        "",
        f"- **Total Checkpoints**: {len(history)}",
        f"- **Node Sequence**: {' → '.join(nodes_path)}",
        f"- **Length**: {len(nodes_path)} nodes visited",
    ])

    # Add routing decisions if detectable
    if len(nodes_path) > 2:
        timeline_lines.append(f"- **Key Decision Points**:")
        for i, node in enumerate(nodes_path):
            if node in ["classify", "evaluate", "approval", "route_after_retry"]:
                next_node = nodes_path[i + 1] if i + \
                    1 < len(nodes_path) else "END"
                timeline_lines.append(f"  - {node} → {next_node}")

    timeline_lines.extend([
        "",
        "---",
        "",
        "## How to Use This Report",
        "",
        "1. **Trace Execution**: Follow node sequence to understand decision path",
        "2. **Debug Routing**: Check state values at each checkpoint to verify routing logic",
        "3. **Verify Retries**: Count nodes to see if retry loop executed correctly",
        "4. **Approval History**: Look for 'interrupt' event types in events list",
        "5. **Error Recovery**: Inspect errors list to understand failure modes",
        "",
        "## See Also",
        "",
        "- [HITL Guide](../../docs/HITL_GUIDE.md) — Human approval debugging",
        "- [EXTENSIONS.md](../../docs/EXTENSIONS.md) — Full extension architecture",
    ])

    return "\n".join(timeline_lines)


def _extract_node_path(history: list[dict]) -> list[str]:
    """Extract node visitation sequence from checkpoint history."""
    from .persistence import get_checkpoint_nodes_path
    return get_checkpoint_nodes_path(history)


def write_state_history(
    thread_id: str,
    history: list[dict],
    output_path: str | Path,
    scenario_id: str = "unknown",
) -> None:
    """Write state history report to markdown file."""
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = render_state_history(thread_id, history, scenario_id)
    path.write_text(content, encoding="utf-8")
