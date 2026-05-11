"""Checkpointer adapter."""

from __future__ import annotations

from typing import Any


def build_checkpointer(kind: str = "memory", database_url: str | None = None) -> Any | None:
    """Return a LangGraph checkpointer.

    Supports:
    - memory (default): MemorySaver for dev/testing
    - sqlite: Persists checkpoints to local SQLite database
    - postgres: Persists checkpoints to PostgreSQL (extension track)
    - none: No checkpointing (stateless execution)
    """
    if kind == "none":
        return None
    if kind == "memory":
        from langgraph.checkpoint.memory import MemorySaver

        return MemorySaver()
    if kind == "sqlite":
        try:
            from langgraph.checkpoint.sqlite import SqliteSaver
        except ImportError as exc:
            raise RuntimeError(
                "SQLite checkpointer requires: pip install langgraph-checkpoint-sqlite") from exc
        return SqliteSaver.from_conn_string(database_url or "checkpoints.db")
    if kind == "postgres":
        try:
            from langgraph.checkpoint.postgres import PostgresSaver
        except ImportError as exc:
            raise RuntimeError(
                "Postgres checkpointer requires: pip install langgraph-checkpoint-postgres") from exc
        return PostgresSaver.from_conn_string(database_url or "")
    raise ValueError(f"Unknown checkpointer kind: {kind}")


def persist_dead_letter(state: dict, output_dir: str = "outputs") -> None:
    """Persist dead-letter state for manual review.

    Saves unresolvable failures to disk for post-mortem analysis.
    Each dead-letter record includes:
    - scenario_id, query, final error state
    - Events log for debugging
    - Timestamp and attempt count
    """
    from pathlib import Path
    import json
    from datetime import datetime

    path = Path(output_dir) / "dead_letters"
    path.mkdir(parents=True, exist_ok=True)

    scenario_id = state.get("scenario_id", "unknown")
    timestamp = datetime.utcnow().isoformat()
    filename = f"{scenario_id}_{timestamp.replace(':', '-')}.json"

    record = {
        "scenario_id": scenario_id,
        "query": state.get("query", ""),
        "route": state.get("route", ""),
        "final_answer": state.get("final_answer", ""),
        "attempt": state.get("attempt", 0),
        "max_attempts": state.get("max_attempts", 3),
        "errors": state.get("errors", []),
        "events": state.get("events", []),
        "timestamp": timestamp,
    }

    with open(path / filename, "w", encoding="utf-8") as f:
        json.dump(record, f, indent=2, default=str)

    print(f"[INFO] Dead-letter record saved: {path / filename}")
