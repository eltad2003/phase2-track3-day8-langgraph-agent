"""CLI for the lab."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Annotated

import typer
import yaml

from .graph import build_graph
from .metrics import MetricsReport, metric_from_state, summarize_metrics, write_metrics
from .persistence import build_checkpointer, persist_dead_letter
from .report import write_report
from .scenarios import load_scenarios
from .state import initial_state

app = typer.Typer(no_args_is_help=True)


@app.command("run-scenarios")
def run_scenarios(
    config: Annotated[Path, typer.Option("--config")],
    output: Annotated[Path, typer.Option("--output")],
) -> None:
    """Run all grading scenarios and write metrics JSON.

    Executes test scenarios against the graph, tracks metrics, and persists
    any dead-letter (unresolvable) failures for manual review.
    """
    cfg = yaml.safe_load(config.read_text(encoding="utf-8"))
    scenarios_path = cfg.get("scenarios_path")
    if not scenarios_path:
        raise typer.BadParameter("scenarios_path not found in config")

    scenarios = load_scenarios(scenarios_path)
    checkpointer = build_checkpointer(
        cfg.get("checkpointer", "memory"), cfg.get("database_url"))
    graph = build_graph(checkpointer=checkpointer)

    metrics = []
    dead_letter_count = 0

    for scenario in scenarios:
        state = initial_state(scenario)
        run_config = {"configurable": {"thread_id": state["thread_id"]}}
        final_state = graph.invoke(state, config=run_config)

        # Track metrics
        metric = metric_from_state(
            final_state, scenario.expected_route.value, scenario.requires_approval)
        metrics.append(metric)

        # Persist dead-letter failures for review
        if final_state.get("route") == "dead_letter" or final_state.get("attempt", 0) >= scenario.max_attempts:
            persist_dead_letter(final_state, cfg.get("output_dir", "outputs"))
            dead_letter_count += 1

    # Generate and write reports
    report = summarize_metrics(metrics)
    write_metrics(report, output)

    if cfg.get("report_path"):
        write_report(report, cfg["report_path"])

    typer.echo(
        f"Ran {len(scenarios)} scenarios. Dead-letter count: {dead_letter_count}")
    typer.echo(f"Wrote metrics to {output}")


@app.command("validate-metrics")
def validate_metrics(metrics: Annotated[Path, typer.Option("--metrics")]) -> None:
    """Validate metrics JSON schema for grading."""
    payload = json.loads(metrics.read_text(encoding="utf-8"))
    report = MetricsReport.model_validate(payload)
    if report.total_scenarios < 6:
        raise typer.BadParameter("Expected at least 6 scenarios")
    typer.echo(f"Metrics valid. success_rate={report.success_rate:.2%}")


if __name__ == "__main__":
    app()
