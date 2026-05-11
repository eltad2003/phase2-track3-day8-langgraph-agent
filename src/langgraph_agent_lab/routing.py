"""Routing functions for conditional edges."""

from __future__ import annotations

from .state import AgentState, Route


def route_after_classify(state: AgentState) -> str:
    """Map classified route to the next graph node.

    Safely handles unknown routes by defaulting to 'answer' node.
    Validates route enum before mapping.
    """
    route = state.get("route", Route.SIMPLE.value)
    mapping = {
        Route.SIMPLE.value: "answer",
        Route.TOOL.value: "tool",
        Route.MISSING_INFO.value: "clarify",
        Route.RISKY.value: "risky_action",
        Route.ERROR.value: "retry",
    }
    next_node = mapping.get(route, "answer")
    if route not in mapping:
        # Log unknown route and fall back to safe node
        print(f"[WARNING] Unknown route: {route}, falling back to 'answer'")
    return next_node


def route_after_retry(state: AgentState) -> str:
    """Decide whether to retry, fallback, or dead-letter.

    Bounded retry logic:
    - If attempts >= max_attempts: route to dead_letter for manual review.
    - Otherwise: retry the tool execution with exponential backoff.
    """
    attempt = int(state.get("attempt", 0))
    max_attempts = int(state.get("max_attempts", 3))
    
    if attempt >= max_attempts:
        print(f"[INFO] Max retry attempts ({max_attempts}) reached. Routing to dead_letter.")
        return "dead_letter"
    
    print(f"[INFO] Retry {attempt + 1}/{max_attempts}")
    return "tool"


def route_after_evaluate(state: AgentState) -> str:
    """Decide whether tool result is satisfactory or needs retry.

    This is the 'done?' check that enables retry loops — a key LangGraph advantage over LCEL.
    Evaluation results from evaluate_node determine routing:
    - 'needs_retry': route back to retry/tool for another attempt
    - 'success' (default): route to answer for final response generation
    """
    eval_result = state.get("evaluation_result", "success")
    if eval_result == "needs_retry":
        print(f"[INFO] Evaluation indicates retry needed.")
        return "retry"
    print(f"[INFO] Evaluation result: {eval_result}, proceeding to answer.")
    return "answer"


def route_after_approval(state: AgentState) -> str:
    """Continue only if approved.

    Approval outcomes:
    - approved=True: proceed to tool execution
    - approved=False: route to clarify for user feedback
    Falls back to clarify if approval decision is missing.
    """
    approval = state.get("approval") or {}
    is_approved = approval.get("approved", False)
    
    if is_approved:
        print(f"[INFO] Action approved by {approval.get('reviewer', 'unknown')}. Proceeding to tool.")
        return "tool"
    else:
        reason = approval.get("comment", "no reason provided")
        print(f"[INFO] Action rejected: {reason}. Requesting clarification.")
        return "clarify"
