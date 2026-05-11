"""Node skeletons for the LangGraph workflow.

Each function should be small, testable, and return a partial state update. Avoid mutating the
input state in place.
"""

from __future__ import annotations

from .state import AgentState, ApprovalDecision, Route, make_event


def intake_node(state: AgentState) -> dict:
    """Normalize raw query into state fields.

    TODO(student): add normalization, PII checks, and metadata extraction.
    """
    query = state.get("query", "").strip()
    normalized_query = " ".join(query.split())
    # Placeholder for PII checking
    has_pii = "ssn" in normalized_query.lower()

    return {
        "query": normalized_query,
        "messages": [f"intake:{normalized_query[:40]}"],
        "events": [make_event("intake", "completed", f"query normalized, PII={has_pii}")],
    }


def classify_node(state: AgentState) -> dict:
    """Classify the query into a route.

    Routing policy:
    - RISKY: contains refund/delete/send (high risk)
    - TOOL: contains status/order/lookup (requires external tool)
    - MISSING_INFO: ambiguous pronouns or incomplete context
    - ERROR: failure-related keywords (simulate transient error)
    - SIMPLE: default safe route
    """
    query = state.get("query", "").lower()
    words = query.split()
    clean_words = [w.strip("?!.,;:") for w in words]
    route = Route.SIMPLE
    risk_level = "low"
    confidence = 0.7  # Default confidence for simple route

    # High-risk actions require approval
    if any(kw in query for kw in ["refund", "delete", "cancel", "send money"]):
        route = Route.RISKY
        risk_level = "high"
        confidence = 0.95
    # Tool-dependent queries
    elif any(kw in query for kw in ["status", "order", "lookup", "check"]):
        route = Route.TOOL
        risk_level = "low"
        confidence = 0.85
    # Incomplete queries (missing required context)
    elif len(clean_words) < 4 or (len(clean_words) < 5 and "it" in clean_words):
        route = Route.MISSING_INFO
        risk_level = "low"
        confidence = 0.6
    # Error simulation for retry demonstrations
    elif any(kw in query for kw in ["timeout", "fail", "error", "test error"]):
        route = Route.ERROR
        risk_level = "medium"
        confidence = 0.8

    return {
        "route": route.value,
        "risk_level": risk_level,
        "events": [make_event("classify", "completed", f"route={route.value}, confidence={confidence}")],
    }


def ask_clarification_node(state: AgentState) -> dict:
    """Ask for missing information instead of hallucinating.

    TODO(student): generate a specific clarification question from state.
    """
    question = "Can you provide the order id or the missing context?"
    return {
        "pending_question": question,
        "final_answer": question,
        "events": [make_event("clarify", "completed", "missing information requested")],
    }


def tool_node(state: AgentState) -> dict:
    """Call a mock tool with idempotent execution and structured results.

    Simulates transient failures for error-route scenarios to demonstrate retry loops.
    Uses status field to track execution state and avoid duplicate side effects.
    """
    attempt = int(state.get("attempt", 0))
    scenario_id = state.get('scenario_id', 'unknown')

    # Idempotent: check if tool already executed successfully
    tool_results = state.get("tool_results", [])
    if tool_results and "SUCCESS" in tool_results[-1]:
        return {
            "tool_results": tool_results,  # Return existing result, no side effects
            "events": [make_event("tool", "skipped", f"idempotent: already executed, attempt={attempt}")],
        }

    # Simulate transient failures for error-route scenarios
    if state.get("route") == Route.ERROR.value and attempt < 2:
        result = f"TRANSIENT_ERROR: scenario={scenario_id}, attempt={attempt}, retry_needed=true"
    else:
        result = f"SUCCESS: tool_execution_completed, scenario={scenario_id}, data_fetched=true"

    return {
        "tool_results": [result],
        "events": [make_event("tool", "completed", f"tool executed at attempt {attempt}")],
    }


def risky_action_node(state: AgentState) -> dict:
    """Prepare a risky action for approval with evidence and risk justification.

    High-risk routes (refund, delete, send) require human-in-the-loop approval.
    Evidence includes query context, risk level, and proposed mitigation.
    """
    query = state.get("query", "")
    risk_level = state.get("risk_level", "unknown")
    scenario_id = state.get("scenario_id", "unknown")

    # Construct a detailed proposed action with evidence
    proposed_action = (
        f"Scenario: {scenario_id}\n"
        f"Risk Level: {risk_level}\n"
        f"Query: {query}\n"
        f"Action: Execute requested operation\n"
        f"Mitigation: Reviewer confirmation required before proceeding."
    )

    return {
        "proposed_action": proposed_action,
        "events": [make_event("risky_action", "pending_approval", f"risk_level={risk_level}, approval required")],
    }


def approval_node(state: AgentState) -> dict:
    """Human approval step with optional LangGraph interrupt() and rejection handling.

    Set LANGGRAPH_INTERRUPT=true to use real interrupt() for HITL demos.
    Default uses mock decision so tests and CI run offline.
    Supports approve/reject/edit outcomes; reject flows to clarification.
    """
    import os

    if os.getenv("LANGGRAPH_INTERRUPT", "").lower() == "true":
        from langgraph.types import interrupt

        value = interrupt({
            "proposed_action": state.get("proposed_action"),
            "risk_level": state.get("risk_level"),
        })
        if isinstance(value, dict):
            decision = ApprovalDecision(**value)
        else:
            decision = ApprovalDecision(approved=bool(value))
    else:
        # Mock approval; in production, this would block until human review
        decision = ApprovalDecision(
            approved=True, comment="mock approval for lab")

    event_msg = f"approved={decision.approved}, reviewer={decision.reviewer}"
    if not decision.approved:
        event_msg += f", reason={decision.comment}"

    return {
        "approval": decision.model_dump(),
        "events": [make_event("approval", "completed", event_msg)],
    }


def retry_or_fallback_node(state: AgentState) -> dict:
    """Record a retry attempt or fallback decision.

    TODO(student): implement bounded retry, exponential backoff metadata, and fallback route.
    """
    attempt = int(state.get("attempt", 0)) + 1
    wait_time_ms = (2 ** attempt) * 100  # Exponential backoff
    errors = [f"transient failure attempt={attempt}, wait={wait_time_ms}ms"]
    return {
        "attempt": attempt,
        "errors": errors,
        "events": [make_event("retry", "completed", f"retry recorded, backoff {wait_time_ms}ms", attempt=attempt)],
    }


def answer_node(state: AgentState) -> dict:
    """Produce a final response.

    TODO(student): ground the answer in tool_results and approval where relevant.
    """
    if state.get("tool_results"):
        answer = f"I found: {state['tool_results'][-1]}"
    else:
        answer = "This is a safe mock answer. Replace with your agent response."
    return {
        "final_answer": answer,
        "events": [make_event("answer", "completed", "answer generated")],
    }


def evaluate_node(state: AgentState) -> dict:
    """Evaluate tool results — the 'done?' check that enables retry loops.

    Validation rules:
    - TRANSIENT_ERROR or ERROR: retry needed
    - SUCCESS: evaluation passes
    - Empty results: retry needed
    Can be replaced with LLM-as-judge for semantic evaluation.
    """
    tool_results = state.get("tool_results", [])
    latest = tool_results[-1] if tool_results else ""

    # Rule-based evaluation
    if not latest:
        return {
            "evaluation_result": "needs_retry",
            "events": [make_event("evaluate", "completed", "no tool result, retry needed")],
        }
    elif "TRANSIENT_ERROR" in latest or "ERROR" in latest:
        return {
            "evaluation_result": "needs_retry",
            "events": [make_event("evaluate", "completed", "transient error detected, retry needed")],
        }
    elif "SUCCESS" in latest:
        return {
            "evaluation_result": "success",
            "events": [make_event("evaluate", "completed", "tool result valid and complete")],
        }
    else:
        # Ambiguous result: retry for safety
        return {
            "evaluation_result": "needs_retry",
            "events": [make_event("evaluate", "completed", "ambiguous result, retry for validation")],
        }


def dead_letter_node(state: AgentState) -> dict:
    """Log unresolvable failures for manual review.

    Third layer of error strategy: retry -> fallback -> dead letter.
    TODO(student): persist to dead-letter queue, alert on-call, or create support ticket.
    """
    return {
        "final_answer": "Request could not be completed after maximum retry attempts. Logged for manual review.",
        "events": [make_event("dead_letter", "completed", f"max retries exceeded, attempt={state.get('attempt', 0)}")],
    }


def finalize_node(state: AgentState) -> dict:
    """Finalize the run and emit a final audit event."""
    return {"events": [make_event("finalize", "completed", "workflow finished")]}
