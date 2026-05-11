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


@app.command("draw-graph")
def draw_graph(
    output: Annotated[Path, typer.Option(
        "--output", help="Output file for Mermaid diagram")] = Path("outputs/graph_diagram.md"),
) -> None:
    """Export graph structure as Mermaid diagram.

    Generates a Mermaid flowchart visualization of the complete LangGraph workflow,
    including all nodes, edges, and conditional routing branches.
    """
    try:
        graph = build_graph()

        # Get Mermaid diagram from compiled graph
        mermaid_str = graph.get_graph().draw_mermaid()

        # Wrap in markdown code block for readability
        output_path = Path(output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        markdown_content = f"""# LangGraph Architecture Diagram

Generated via `graph.get_graph().draw_mermaid()`

```mermaid
{mermaid_str}
```

## Legend

- **Nodes**: rectangles represent processing nodes (intake, classify, tool, etc.)
- **Edges**: arrows represent control flow transitions
- **Conditional**: diamonds represent routing decisions (classify, evaluate, approval, retry)
- **START/END**: special nodes marking graph boundaries

## Key Paths

1. **Simple Route**: START → intake → classify → answer → finalize → END
2. **Tool Route**: START → intake → classify → tool → evaluate → answer → finalize → END
3. **Risky Route**: START → intake → classify → risky_action → approval → [tool/clarify] → finalize → END
4. **Error/Retry**: START → intake → classify → retry → tool → evaluate → [retry/answer] → finalize → END
5. **Dead Letter**: Any path with exhausted retries → dead_letter → finalize → END

## Generating Updated Diagrams

To regenerate after code changes:

```bash
python -m langgraph_agent_lab.cli draw-graph --output outputs/graph_diagram.md
```

Or directly in Python:

```python
from langgraph_agent_lab.graph import build_graph

graph = build_graph()
diagram = graph.get_graph().draw_mermaid()
print(diagram)
```
"""

        output_path.write_text(markdown_content, encoding="utf-8")
        typer.echo(f"✓ Graph diagram exported to {output_path}")
        typer.echo(f"✓ View with: cat {output_path}")

    except Exception as e:
        typer.echo(f"✗ Failed to generate diagram: {e}", err=True)
        raise typer.Exit(code=1)


@app.command("ui-server")
def ui_server(
    port: Annotated[int, typer.Option(
        "--port", help="Port to run Streamlit on")] = 8501,
    checkpoint_db: Annotated[
        str, typer.Option("--checkpoint-db",
                          help="Path to checkpoint database (SQLite)")
    ] = "checkpoints.db",
) -> None:
    """Launch interactive Streamlit approval UI.

    Provides a human-facing interface for approving/rejecting risky actions during
    graph execution via LangGraph's interrupt() API.

    Usage:
        # Terminal 1: Run graph with HITL enabled
        LANGGRAPH_INTERRUPT=true python -m langgraph_agent_lab.cli run-scenarios ...

        # Terminal 2: Launch approval UI
        python -m langgraph_agent_lab.cli ui-server --port 8501

    The UI will be available at http://localhost:8501
    """
    try:
        import subprocess
        import sys

        # Get path to ui_approval.py
        ui_script = Path(__file__).parent / "ui_approval.py"

        if not ui_script.exists():
            typer.echo(f"✗ UI script not found: {ui_script}", err=True)
            raise typer.Exit(code=1)

        typer.echo(f"🚀 Launching Streamlit UI on port {port}...")
        typer.echo(f"📍 Open browser: http://localhost:{port}")
        typer.echo(f"📝 Checkpoint DB: {checkpoint_db}")
        typer.echo("")
        typer.echo("Press Ctrl+C to stop")

        # Launch streamlit
        subprocess.run(
            [
                sys.executable,
                "-m",
                "streamlit",
                "run",
                str(ui_script),
                f"--server.port={port}",
                "--server.headless=false",
            ],
            check=False,
        )

    except ModuleNotFoundError:
        typer.echo(
            "✗ Streamlit not installed. Install with: pip install -e '.[ui]'",
            err=True,
        )
        raise typer.Exit(code=1)
    except Exception as e:
        typer.echo(f"✗ Failed to launch UI: {e}", err=True)
        raise typer.Exit(code=1)


@app.command("replay-history")
def replay_history(
    thread_id: Annotated[str, typer.Option("--thread-id", help="Thread ID to replay")],
    checkpoint_db: Annotated[
        str, typer.Option("--checkpoint-db",
                          help="Path to SQLite checkpoint database")
    ] = "checkpoints.db",
    output: Annotated[
        Path, typer.Option(
            "--output", help="Output markdown file for replay report")
    ] = Path("outputs/replay_history.md"),
    scenario_id: Annotated[
        str, typer.Option(
            "--scenario-id", help="Scenario identifier (optional)")
    ] = "unknown",
) -> None:
    """Replay execution history from checkpoint database for debugging.

    Loads checkpoint history for a given thread_id and generates a markdown report
    showing the node sequence, state transitions, and routing decisions.

    Usage:
        # After running scenarios with SQLite checkpointer:
        python -m langgraph_agent_lab.cli replay-history \\
            --thread-id abc123 \\
            --checkpoint-db checkpoints.db \\
            --output outputs/replay_abc123.md

    This creates a time-travel debugging report showing:
    - Chronological node visitation
    - State values at each checkpoint
    - Retry loop execution (if any)
    - Approval interrupts (if any)
    - Error propagation
    """
    try:
        from .persistence import load_state_history
        from .report import write_state_history

        typer.echo(f"📖 Loading checkpoint history for thread: {thread_id}")

        # Load history
        history = load_state_history(thread_id, checkpoint_db)

        if not history:
            typer.echo(
                f"⚠️  No checkpoints found for thread_id: {thread_id}", err=True)
            raise typer.Exit(code=1)

        typer.echo(f"✓ Found {len(history)} checkpoints")

        # Write report
        output_path = Path(output)
        write_state_history(thread_id, history, output_path, scenario_id)

        typer.echo(f"✓ Replay report written to: {output_path}")
        typer.echo("")
        typer.echo("📝 View report:")
        typer.echo(f"  cat {output_path}")

    except FileNotFoundError as e:
        typer.echo(f"✗ {e}", err=True)
        raise typer.Exit(code=1)
    except Exception as e:
        typer.echo(f"✗ Failed to replay history: {e}", err=True)
        raise typer.Exit(code=1)


if __name__ == "__main__":
    app()
