"""Tests for Real HITL (Human-in-the-Loop) approval via interrupt() API."""

import os
from unittest.mock import MagicMock, patch

import pytest

from langgraph_agent_lab.nodes import approval_node
from langgraph_agent_lab.state import AgentState, ApprovalDecision, initial_state


class TestHITLApprovalNode:
    """Test approval_node with real interrupt() and fallback behavior."""

    def test_approval_node_mock_mode_default(self) -> None:
        """Verify mock approval works when LANGGRAPH_INTERRUPT is not set."""
        # Arrange
        state: AgentState = {
            "thread_id": "test-thread-001",
            "scenario_id": "S04_risky",
            "query": "Refund this customer",
            "proposed_action": "Process $500 refund",
            "risk_level": "HIGH",
            "route": "risky",
            "messages": [],
            "tool_results": [],
            "errors": [],
            "events": [],
        }

        # Ensure LANGGRAPH_INTERRUPT is not set
        with patch.dict(os.environ, {}, clear=False):
            if "LANGGRAPH_INTERRUPT" in os.environ:
                del os.environ["LANGGRAPH_INTERRUPT"]

            # Act
            result = approval_node(state)

        # Assert
        assert "approval" in result
        # Mock defaults to approved
        assert result["approval"]["approved"] is True
        assert result["approval"]["reviewer"] == "mock-reviewer"
        assert "events" in result
        assert len(result["events"]) == 1
        assert result["events"][0]["event_type"] == "auto_approved"

    def test_approval_node_interrupt_mode_approved(self) -> None:
        """Verify interrupt mode accepts approval decision."""
        # Arrange
        state: AgentState = {
            "thread_id": "test-thread-002",
            "scenario_id": "S04_risky",
            "query": "Refund this customer",
            "proposed_action": "Process $500 refund",
            "risk_level": "HIGH",
            "route": "risky",
            "messages": [],
            "tool_results": [],
            "errors": [],
            "events": [],
        }

        approval_payload = {
            "approved": True,
            "reviewer": "alice@example.com",
            "comment": "Verified customer identity",
        }

        # Mock interrupt() to return approval decision
        with patch.dict(os.environ, {"LANGGRAPH_INTERRUPT": "true"}):
            with patch("langgraph.types.interrupt") as mock_interrupt:
                mock_interrupt.return_value = approval_payload

                # Act
                result = approval_node(state)

        # Assert
        assert "approval" in result
        assert result["approval"]["approved"] is True
        assert result["approval"]["reviewer"] == "alice@example.com"
        assert result["approval"]["comment"] == "Verified customer identity"
        assert "events" in result
        assert len(result["events"]) == 1
        assert result["events"][0]["event_type"] == "interrupt"
        assert "alice@example.com" in result["events"][0]["message"]

    def test_approval_node_interrupt_mode_rejected(self) -> None:
        """Verify interrupt mode accepts rejection decision."""
        # Arrange
        state: AgentState = {
            "thread_id": "test-thread-003",
            "scenario_id": "S06_delete",
            "query": "Delete customer account",
            "proposed_action": "Delete account after verification",
            "risk_level": "CRITICAL",
            "route": "risky",
            "messages": [],
            "tool_results": [],
            "errors": [],
            "events": [],
        }

        rejection_payload = {
            "approved": False,
            "reviewer": "bob",
            "comment": "Need written customer consent",
        }

        # Mock interrupt() to return rejection
        with patch.dict(os.environ, {"LANGGRAPH_INTERRUPT": "true"}):
            with patch("langgraph.types.interrupt") as mock_interrupt:
                mock_interrupt.return_value = rejection_payload

                # Act
                result = approval_node(state)

        # Assert
        assert "approval" in result
        assert result["approval"]["approved"] is False
        assert result["approval"]["reviewer"] == "bob"
        assert result["approval"]["comment"] == "Need written customer consent"
        assert "events" in result
        assert len(result["events"]) == 1
        assert result["events"][0]["event_type"] == "interrupt"
        assert "approved=False" in result["events"][0]["message"]

    def test_approval_node_interrupt_timeout(self) -> None:
        """Verify timeout/cancel during interrupt safely defaults to rejection."""
        # Arrange
        state: AgentState = {
            "thread_id": "test-thread-004",
            "scenario_id": "S04_risky",
            "query": "Refund this customer",
            "proposed_action": "Process $500 refund",
            "risk_level": "HIGH",
            "route": "risky",
            "messages": [],
            "tool_results": [],
            "errors": [],
            "events": [],
        }

        # Mock interrupt() to raise timeout
        with patch.dict(os.environ, {"LANGGRAPH_INTERRUPT": "true"}):
            with patch("langgraph.types.interrupt") as mock_interrupt:
                mock_interrupt.side_effect = TimeoutError(
                    "User did not respond in 5 minutes")

                # Act
                result = approval_node(state)

        # Assert
        assert "approval" in result
        assert result["approval"]["approved"] is False  # Safe default
        assert "Interrupt failed or canceled" in result["approval"]["comment"]
        assert "events" in result
        assert result["events"][0]["event_type"] == "interrupt"

    def test_approval_node_interrupt_malformed_response(self) -> None:
        """Verify malformed interrupt response doesn't crash."""
        # Arrange
        state: AgentState = {
            "thread_id": "test-thread-005",
            "scenario_id": "S04_risky",
            "query": "Refund this customer",
            "proposed_action": "Process $500 refund",
            "risk_level": "HIGH",
            "route": "risky",
            "messages": [],
            "tool_results": [],
            "errors": [],
            "events": [],
        }

        # Mock interrupt() to return invalid value
        with patch.dict(os.environ, {"LANGGRAPH_INTERRUPT": "true"}):
            with patch("langgraph.types.interrupt") as mock_interrupt:
                mock_interrupt.return_value = "invalid"  # Not dict or bool

                # Act
                result = approval_node(state)

        # Assert
        assert "approval" in result
        # String "invalid" is truthy, so it becomes approved=True
        assert result["approval"]["approved"] is True

    def test_approval_node_interrupt_includes_context(self) -> None:
        """Verify interrupt payload includes necessary context for human review."""
        # Arrange
        state: AgentState = {
            "thread_id": "test-thread-006",
            "scenario_id": "S04_risky",
            "query": "Refund order #12345",
            "proposed_action": "Process $99.99 refund to credit card",
            "risk_level": "MEDIUM",
            "route": "risky",
            "messages": [],
            "tool_results": [],
            "errors": [],
            "events": [],
        }

        interrupt_capture = {"payload": None}

        def capture_interrupt(data: dict) -> dict:
            interrupt_capture["payload"] = data
            return {"approved": True, "reviewer": "test"}

        # Mock interrupt() to capture payload
        with patch.dict(os.environ, {"LANGGRAPH_INTERRUPT": "true"}):
            with patch("langgraph.types.interrupt") as mock_interrupt:
                mock_interrupt.side_effect = capture_interrupt

                # Act
                approval_node(state)

        # Assert: interrupt was called with context
        assert interrupt_capture["payload"] is not None
        payload = interrupt_capture["payload"]
        assert "proposed_action" in payload
        assert "risk_level" in payload
        assert "query" in payload
        assert payload["proposed_action"] == "Process $99.99 refund to credit card"
        assert payload["risk_level"] == "MEDIUM"
        assert payload["query"] == "Refund order #12345"

    def test_approval_node_event_type_distinguishes_interrupt(self) -> None:
        """Verify event_type differs between mock and real interrupt."""
        # Arrange
        state: AgentState = {
            "thread_id": "test-thread-007",
            "scenario_id": "S04_risky",
            "query": "Delete account",
            "route": "risky",
            "messages": [],
            "tool_results": [],
            "errors": [],
            "events": [],
        }

        # Test 1: Mock mode
        with patch.dict(os.environ, {}, clear=False):
            if "LANGGRAPH_INTERRUPT" in os.environ:
                del os.environ["LANGGRAPH_INTERRUPT"]
            result_mock = approval_node(state)

        # Test 2: Interrupt mode
        with patch.dict(os.environ, {"LANGGRAPH_INTERRUPT": "true"}):
            with patch("langgraph.types.interrupt") as mock_interrupt:
                mock_interrupt.return_value = {"approved": True}
                result_interrupt = approval_node(state)

        # Assert
        assert result_mock["events"][0]["event_type"] == "auto_approved"
        assert result_interrupt["events"][0]["event_type"] == "interrupt"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
