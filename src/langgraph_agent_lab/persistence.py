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


def load_state_history(
    thread_id: str,
    checkpoint_db: str = "checkpoints.db",
) -> list[dict[str, Any]]:
    """Load state history from SQLite checkpoint database.

    Queries checkpoint table for all snapshots with given thread_id,
    sorted chronologically. Returns list of (timestamp, node_name, state_dict) tuples
    for post-mortem debugging and state replay.

    Args:
        thread_id: The thread identifier to query
        checkpoint_db: Path to SQLite checkpoint database

    Returns:
        List of checkpoint records with timestamp, thread_id, node info, and state snapshot

    Raises:
        ImportError: If langgraph-checkpoint-sqlite not installed
        FileNotFoundError: If checkpoint DB doesn't exist
    """
    import sqlite3
    import json
    from pathlib import Path

    db_path = Path(checkpoint_db)
    if not db_path.exists():
        raise FileNotFoundError(
            f"Checkpoint database not found: {checkpoint_db}")

    try:
        conn = sqlite3.connect(checkpoint_db)
        cursor = conn.cursor()

        # Query checkpoint table (LangGraph stores checkpoints in this table)
        # Note: Table structure may vary between versions; this assumes standard schema
        cursor.execute(
            """
            SELECT checkpoint_id, checkpoint, metadata
            FROM checkpoints
            WHERE thread_id = ?
            ORDER BY checkpoint_id ASC
            """,
            (thread_id,),
        )

        records = cursor.fetchall()
        conn.close()

        if not records:
            return []

        # Parse checkpoint data
        history: list[dict[str, Any]] = []
        for checkpoint_id, checkpoint_json, metadata_json in records:
            try:
                checkpoint_data = json.loads(checkpoint_json) if isinstance(
                    checkpoint_json, str) else checkpoint_json
                metadata = json.loads(metadata_json) if isinstance(
                    metadata_json, str) else metadata_json
            except (json.JSONDecodeError, TypeError):
                # Fallback for binary or malformed data
                checkpoint_data = {"raw": str(checkpoint_json)[:200]}
                metadata = {}

            history.append({
                "checkpoint_id": checkpoint_id,
                "thread_id": thread_id,
                "checkpoint": checkpoint_data,
                "metadata": metadata,
            })

        return history

    except sqlite3.Error as e:
        raise RuntimeError(f"Database error querying checkpoints: {e}") from e


def get_checkpoint_nodes_path(history: list[dict[str, Any]]) -> list[str]:
    """Extract node visitation sequence from checkpoint history.

    Parses checkpoint metadata to determine which nodes were visited and in what order.
    Useful for understanding execution flow and routing decisions.

    Args:
        history: List of checkpoint records from load_state_history()

    Returns:
        List of node names in visitation order
    """
    nodes_path = []

    for record in history:
        # Try to extract node name from various checkpoint metadata formats
        metadata = record.get("metadata", {})

        # LangGraph stores current node in metadata
        if "node" in metadata:
            node_name = metadata["node"]
        elif "step" in metadata:
            node_name = metadata.get("step", {}).get("node", "unknown")
        else:
            # Fallback: try to infer from checkpoint content
            checkpoint = record.get("checkpoint", {})
            node_name = checkpoint.get("current_node", "unknown")

        # Only add if different from last (avoid duplicates)
        if not nodes_path or nodes_path[-1] != node_name:
            nodes_path.append(node_name)

    return nodes_path
