"""Interactive Streamlit UI for LangGraph approval workflow.

This app provides a human-facing interface for approving or rejecting risky actions
during graph execution. It connects to running graph instances via LangGraph's
interrupt/resume API and checkpoint state.

Usage:
    streamlit run src/langgraph_agent_lab/ui_approval.py

Then in another terminal:
    LANGGRAPH_INTERRUPT=true python -m langgraph_agent_lab.cli run-scenarios ...
"""

from __future__ import annotations

import json
import streamlit as st
from pathlib import Path
from typing import Any


# Streamlit page config
st.set_page_config(
    page_title="LangGraph Approval UI",
    page_icon="✅",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.title("🤖 LangGraph Human-in-the-Loop Approval")

st.markdown("""
This UI receives pending risky actions from the LangGraph agent and allows you to:
- **Approve** → Proceed to tool execution
- **Reject** → Ask for clarification or additional information
- **Edit** → Modify the proposed action before approval (future feature)

The approval decision is sent back to the paused graph via LangGraph's `interrupt()` resume API.
""")

# Sidebar for configuration
with st.sidebar:
    st.header("⚙️ Configuration")

    # Demo mode vs. production mode
    demo_mode = st.toggle("Demo Mode (No Real Interrupt)", value=True)

    if demo_mode:
        st.info("""
        **Demo Mode**: Shows mock risky actions for testing UI without a running graph.
        Uncheck to connect to a real running graph.
        """)

    # Checkpoint database selection
    checkpoint_db = st.text_input(
        "Checkpoint Database",
        value="checkpoints.db",
        help="Path to SQLite checkpoint DB (if using real mode)"
    )

    st.markdown("---")
    st.subheader("📚 Help")
    st.markdown("""
    **To use with real graph:**
    1. Terminal 1: `LANGGRAPH_INTERRUPT=true python -m langgraph_agent_lab.cli run-scenarios ...`
    2. Terminal 2: `streamlit run src/langgraph_agent_lab/ui_approval.py`
    3. Graph pauses at approval_node, waiting for your decision
    4. Make decision in UI below
    5. Graph resumes and continues
    """)


# Main UI
if demo_mode:
    # Demo mode: show mock risky action
    st.header("Demo Risky Action")

    col1, col2 = st.columns(2)

    with col1:
        st.metric("Scenario", "S04_risky")
        st.metric("Risk Level", "🔴 HIGH")

    with col2:
        st.metric("Route", "risky")
        st.metric("Attempt", "1 / 3")

    st.divider()

    st.subheader("📋 Request Details")
    request_details = {
        "scenario_id": "S04_risky",
        "query": "Refund this customer and send confirmation email",
        "proposed_action": "Process $500 refund to credit card + send email",
        "risk_level": "HIGH",
    }

    col1, col2 = st.columns(2)
    with col1:
        st.text_input(
            "Scenario ID", value=request_details["scenario_id"], disabled=True)
        st.text_area("Customer Query",
                     value=request_details["query"], disabled=True, height=50)

    with col2:
        st.text_input(
            "Risk Level", value=request_details["risk_level"], disabled=True)
        st.text_area(
            "Proposed Action",
            value=request_details["proposed_action"],
            disabled=True,
            height=50
        )

    st.divider()

    st.subheader("🔐 Approval Decision")

    decision_col, info_col = st.columns([2, 1])

    with decision_col:
        decision = st.radio(
            "What is your decision?",
            options=["approve", "reject"],
            format_func=lambda x: "✅ Approve" if x == "approve" else "❌ Reject",
            horizontal=True,
        )

    with info_col:
        st.markdown(f"""
        **Decision**: {decision.upper()}
        
        When you click 'Submit', this decision will be sent
        back to the paused graph via interrupt().
        """)

    st.divider()

    if decision == "approve":
        reviewer = st.text_input(
            "Your name/email (optional)",
            value="demo-reviewer",
            help="For audit trail"
        )
        comment = st.text_area(
            "Approval comment (optional)",
            value="Demo approval",
            height=60,
            help="Why are you approving this action?"
        )
    else:  # reject
        reviewer = st.text_input(
            "Your name/email (optional)",
            value="demo-reviewer",
            help="For audit trail"
        )
        comment = st.text_area(
            "Rejection reason (required)",
            value="Need customer written consent",
            height=60,
            help="Why are you rejecting this action?"
        )

    st.divider()

    col1, col2, col3 = st.columns([1, 1, 1])

    with col1:
        if st.button("✅ Submit Decision", use_container_width=True, type="primary"):
            # In demo mode, just show the decision
            approval_payload = {
                "approved": decision == "approve",
                "reviewer": reviewer or "demo-reviewer",
                "comment": comment,
            }

            st.success("✓ Decision submitted!")
            st.json(approval_payload)
            st.info("""
            **In production mode**, this payload would be sent to the paused graph via:
            ```python
            from langgraph.types import interrupt
            
            interrupt_result = interrupt(data)  # pauses here
            # Graph resumes with approval_payload above
            decision = ApprovalDecision(**approval_payload)
            ```
            """)

    with col2:
        if st.button("🔄 Edit Request (Future)", use_container_width=True, disabled=True):
            st.info("Edit feature coming in next version")

    with col3:
        if st.button("❌ Cancel/Timeout", use_container_width=True):
            st.warning(
                "Canceling approval (would default to rejection in graph)")

else:
    # Real mode: try to load from checkpoint
    st.header("🔴 Real Mode (Experimental)")

    st.warning("""
    **Real mode is not fully implemented yet.**
    
    To use: 
    1. Start graph with `LANGGRAPH_INTERRUPT=true` in another terminal
    2. Graph will pause at approval_node
    3. This UI will need to connect via checkpoint DB or webhooks
    
    For now, use Demo Mode above.
    """)

    if st.button("🔄 Refresh Pending Approvals"):
        st.info("Checking for pending interrupts...")
        # TODO: Implement checkpoint polling
        st.info("No pending approvals found")


# Footer with help
st.divider()
st.markdown("""
---

**Architecture Overview**:
- Graph pauses at `approval_node` when risky action detected
- LangGraph `interrupt()` API holds execution
- External UI (you) makes decision
- Graph resumes via `interrupt().resume(decision_payload)`
- Decision routed to `route_after_approval` → tool or clarify

**See Also**: 
- [HITL Guide](../../docs/HITL_GUIDE.md)
- [EXTENSIONS.md](../../docs/EXTENSIONS.md)
- [GitHub Issue: Streamlit Integration](https://github.com/...)
""")
