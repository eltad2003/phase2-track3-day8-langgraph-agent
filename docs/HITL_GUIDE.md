# Human-in-the-Loop (HITL) Approval Guide

This guide explains how to use the real LangGraph `interrupt()` API for production-grade human approval during graph execution.

## Overview

By default, the `approval_node` uses **mock approval** (`approved=True`) so that tests and CI pipelines run offline. For real demos or production use, set `LANGGRAPH_INTERRUPT=true` to trigger actual human approval via LangGraph's `interrupt()` API.

## Architecture

```
Query (risky keyword) 
    ↓
classify_node (detects risky route)
    ↓
risky_action_node (prepares action + risk justification)
    ↓
approval_node (pauses execution, waits for human decision)
    ↓ [interrupt triggered]
Waiting for human input...
    ↓ [human resumes with decision payload]
approval_node (receives decision, continues)
    ↓
route_after_approval (approved → tool | rejected → clarify)
```

## Interrupt Payload Format

When `LANGGRAPH_INTERRUPT=true` and the graph hits `approval_node`, execution pauses and waits for a resume signal with this JSON payload:

```json
{
  "approved": true,
  "reviewer": "alice@example.com",
  "comment": "Verified customer identity"
}
```

### Field Reference

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `approved` | `bool` | Yes | `true` to proceed to tool execution, `false` to ask for clarification |
| `reviewer` | `str` | No | Reviewer's name or email (default: `"human-reviewer"`) |
| `comment` | `str` | No | Approval reason or rejection reason (default: `""`) |

## Quick Start

### 1. Enable HITL in CLI

```bash
# Set environment variable and run scenarios
LANGGRAPH_INTERRUPT=true python -m langgraph_agent_lab.cli run-scenarios \
  --config configs/lab.yaml \
  --output outputs/metrics.json
```

The graph will pause when a risky action is detected, waiting for external resume signal.

### 2. Resume with Approval

In a separate terminal or UI (e.g., Streamlit), resume the paused execution:

```python
from langgraph.types import interrupt

# Inside approval_node, this blocks until resumed
value = interrupt({
    "proposed_action": "Refund order $500",
    "risk_level": "HIGH"
})

# External process/UI resumes here with:
approval_decision = {
    "approved": True,
    "reviewer": "alice",
    "comment": "Verified order exists"
}

# Graph continues from this point
```

### 3. Verify Event Logging

After execution, check the event log in final state:

```python
final_state = graph.invoke(state, config=run_config)

# Events will include "interrupt" event type
for event in final_state.get("events", []):
    if event["event_type"] == "interrupt":
        print(f"Approval interrupt: {event['message']}")
```

## Examples

### Example 1: Approve a Risky Action

**Scenario**: `"Refund this customer and send confirmation email"`

1. User runs: `LANGGRAPH_INTERRUPT=true python -m langgraph_agent_lab.cli run-scenarios ...`
2. Graph detects risky keywords (`refund`, `send`)
3. Execution pauses at `approval_node`, displays:

   ```
   Interrupt with data: {
       "proposed_action": "Refund order + send email confirmation",
       "risk_level": "HIGH"
   }
   ```

4. Human reviews and resumes with:

   ```json
   {"approved": true, "reviewer": "bob", "comment": "Verified customer"}
   ```

5. Graph continues → `tool_node` → `answer_node` → `END`
6. Final state includes event: `{"event_type": "interrupt", "message": "approved=true, reviewer=bob, ..."}`

### Example 2: Reject and Ask for Clarification

**Scenario**: `"Delete customer account after support verification"`

1. Graph detects risky keyword (`delete`)
2. Pauses at `approval_node`
3. Human resumes with:

   ```json
   {"approved": false, "comment": "Need customer written consent"}
   ```

4. Graph routes to `ask_clarification_node`
5. Final route: MISSING_INFO (instead of risky)

### Example 3: Interrupt Timeout/Cancel

If human doesn't respond or cancels the interrupt:

```python
# approval_node catches exception
except Exception as e:
    decision = ApprovalDecision(
        approved=False,
        comment=f"Interrupt failed: {str(e)}"
    )
# Routes to clarification (safe default)
```

## Integration with Streamlit UI

The Streamlit app (`src/langgraph_agent_lab/ui_approval.py`) can act as a human-facing UI for approval:

```bash
# Terminal 1: Run graph with HITL enabled
LANGGRAPH_INTERRUPT=true python -m langgraph_agent_lab.cli run-scenarios \
  --config configs/lab.yaml \
  --output outputs/metrics.json

# Terminal 2: Launch approval UI
streamlit run src/langgraph_agent_lab/ui_approval.py
```

The Streamlit app will:

1. Poll for pending interrupts (via checkpoint state)
2. Display risky action details (query, proposed_action, risk_level)
3. Capture approval decision from user (Approve/Reject/Comment)
4. Resume graph execution with decision payload

## Testing HITL Behavior

Unit tests mock the interrupt behavior without needing external input:

```bash
# Run HITL tests
LANGGRAPH_INTERRUPT=true pytest tests/test_hitl_interrupt.py -v

# Expected: All tests pass, no external prompts
```

See [tests/test_hitl_interrupt.py](../tests/test_hitl_interrupt.py) for full examples.

## Production Considerations

1. **Timeout handling**: Set max wait time before auto-rejecting:

   ```python
   # In approval_node, wrap interrupt call with timeout
   import signal
   
   def timeout_handler(signum, frame):
       raise TimeoutError("Approval timeout after 5 min")
   
   signal.signal(signal.SIGALRM, timeout_handler)
   signal.alarm(300)  # 5 minutes
   ```

2. **Audit trail**: All approval decisions are logged in `state.events` with:
   - Timestamp (implicit via event ordering)
   - Reviewer name
   - Approval decision (approved/rejected)
   - Reason/comment

3. **Persistence**: With SQLite checkpointer, approval decisions are persisted:

   ```bash
   # Verify approval history
   sqlite3 checkpoints.db \
     "SELECT thread_id, route, approval FROM checkpoints WHERE route='risky' LIMIT 5"
   ```

4. **Recovery**: Use `replay-history --thread-id <id>` to debug approval decisions:

   ```bash
   python -m langgraph_agent_lab.cli replay-history \
     --thread-id abc123 \
     --checkpoint-db checkpoints.db
   ```

## Debugging

### Issue: Graph hangs at approval_node

**Cause**: `LANGGRAPH_INTERRUPT=true` but no external process is resuming.

**Solution**:

```bash
# Kill hung process
pkill -f "python -m langgraph_agent_lab.cli run-scenarios"

# Or set timeout:
timeout 30 python -m langgraph_agent_lab.cli run-scenarios ...
```

### Issue: Approval decision not persisted

**Cause**: Using in-memory checkpointer (default).

**Solution**:

```bash
# Use SQLite checkpointer
python -m langgraph_agent_lab.cli run-scenarios \
  --config configs/lab.yaml \
  --checkpointer sqlite \
  --database-url checkpoints.db
```

### Issue: state.events missing "interrupt" event

**Cause**: approval_node didn't trigger interrupt (e.g., route was "simple", not "risky").

**Solution**: Verify scenario has risky keywords (refund, delete, send, cancel, remove).

## See Also

- [EXTENSIONS.md](./EXTENSIONS.md) — Full extension architecture overview
- [Real Streamlit UI](../src/langgraph_agent_lab/ui_approval.py) — Interactive approval interface
- [Time-travel debugging](./EXTENSIONS.md#time-travel) — Replay state history for post-mortems
