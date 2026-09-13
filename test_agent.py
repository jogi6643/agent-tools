# test_agent.py -- unit tests for the deterministic layers (no LLM, no network)
from agent import (
    approve_all,
    collect_ids,
    execute_tool,
    extract_ids,
    is_grounded,
    looks_malicious,
    needs_tool,
    verify_reply,
)
from tools import TICKETS


# ---------------------------------------------- input guardrail
def test_guardrail_blocks_sql_injection():
    assert looks_malicious("order 4471'; DROP TABLE orders--")


def test_guardrail_blocks_script_tag():
    assert looks_malicious("my order is <script>alert(1)</script>")


def test_guardrail_allows_normal_question():
    assert not looks_malicious("what is the status of order 4471?")


# ---------------------------------------------- routing
def test_routing_detects_lookup():
    assert needs_tool("what is the status of order 4471?")


def test_routing_ignores_question_without_id():
    assert not needs_tool("what is your return policy?")


def test_routing_detects_very_long_id():
    """The regex bug we fixed: \\b\\d{3,12}\\b missed this."""
    assert needs_tool("what is the address of 99999999999999999999999?")


# ---------------------------------------------- id extraction
def test_extract_ids_finds_all():
    assert extract_ids("order 4471 and address 123") == ["4471", "123"]


def test_extract_ids_empty_when_no_digits():
    assert extract_ids("where is my order?") == []


def test_collect_ids_reads_tool_results():
    """Multi-step: ids observed in a tool result become usable."""
    result = {"ok": True, "data": {"orders": [{"order_id": "4471"},
                                              {"order_id": "5502"}]}}
    assert collect_ids(result) == {"4471", "5502"}


# ---------------------------------------------- grounding
def test_grounding_accepts_exact_id():
    ok, _ = is_grounded({"4471"}, {"order_id": "4471"})
    assert ok


def test_grounding_rejects_model_corrected_id():
    """The dangerous case: customer typed 44712, model 'fixed' it to 4471."""
    ok, why = is_grounded({"44712"}, {"order_id": "4471"})
    assert not ok
    assert "44712" in why


def test_grounding_rejects_invented_id():
    ok, _ = is_grounded(set(), {"order_id": "1234"})
    assert not ok


def test_grounding_ignores_non_id_fields():
    ok, _ = is_grounded({"4471"}, {"order_id": "4471", "issue": "broken item"})
    assert ok


# ---------------------------------------------- output guardrail
def test_verify_reply_accepts_known_numbers():
    ok, _ = verify_reply("Order 4471 costs 1299 rupees.", {"4471", "1299"})
    assert ok


def test_verify_reply_rejects_invented_number():
    ok, why = verify_reply("Your order 441 was shipped.", {"4471"})
    assert not ok
    assert "441" in why


def test_verify_reply_ignores_small_numbers():
    """2-digit numbers like '12 MG Road' are not ids."""
    ok, _ = verify_reply("Delivered to 12 MG Road in 7 days.", set())
    assert ok


# ---------------------------------------------- execute_tool gates
def test_gate1_unknown_tool():
    result = execute_tool("delete_everything", "{}", set())
    assert result["error"] == "unknown_tool"


def test_gate2_invalid_json():
    result = execute_tool("get_order_status", '{"order_id": "4471"', set())
    assert result["error"] == "invalid_json"


def test_gate3_rejects_non_digit_id():
    result = execute_tool("get_order_status", '{"order_id": "abc"}', set())
    assert result["error"] == "invalid_arguments"


def test_gate3_rejects_too_long_id():
    long_id = "9" * 23
    result = execute_tool(
        "get_order_status", f'{{"order_id": "{long_id}"}}', {long_id}
    )
    assert result["error"] == "invalid_arguments"


def test_gate4_rejects_ungrounded_id():
    result = execute_tool("get_order_status", '{"order_id": "4471"}', {"44712"})
    assert result["error"] == "ungrounded_argument"


def test_gate4_accepts_id_from_tool_result():
    """The id came from a previous tool result, not the customer's message."""
    result = execute_tool("get_order_status", '{"order_id": "4471"}', {"4471"})
    assert result["ok"] is True


def test_happy_path_returns_data():
    result = execute_tool("get_order_status", '{"order_id": "4471"}', {"4471"})
    assert result["ok"] is True
    assert result["data"]["status"] == "shipped"


def test_read_tool_leaks_no_email():
    """PII: customer_email must never reach the prompt."""
    result = execute_tool("get_order_status", '{"order_id": "4471"}', {"4471"})
    assert "customer_email" not in result["data"]


def test_read_tool_needs_no_approval():
    result = execute_tool("get_order_status", '{"order_id": "4471"}', {"4471"})
    assert result["ok"] is True


# ---------------------------------------------- permissions
TICKET_ARGS = '{"order_id": "4471", "issue": "the laptop stand arrived broken"}'


def test_write_tool_denied_by_default():
    result = execute_tool("create_support_ticket", TICKET_ARGS, {"4471"})
    assert result["error"] == "not_approved"


def test_write_tool_runs_when_approved():
    TICKETS.clear()
    result = execute_tool("create_support_ticket", TICKET_ARGS, {"4471"},
                          approver=approve_all)
    assert result["ok"] is True
    assert result["data"]["created"] is True


def test_write_tool_is_idempotent():
    TICKETS.clear()

    first = execute_tool("create_support_ticket", TICKET_ARGS, {"4471"},
                         approver=approve_all)
    second = execute_tool("create_support_ticket", TICKET_ARGS, {"4471"},
                          approver=approve_all)

    assert first["data"]["created"] is True
    assert second["data"]["created"] is False
    assert second["data"]["reason"] == "duplicate"
    assert len(TICKETS) == 1


def test_precondition_blocks_ticket_for_unknown_order():
    """Approval must never be asked for a request that cannot succeed."""
    result = execute_tool(
        "create_support_ticket",
        '{"order_id": "9999", "issue": "the item arrived damaged"}',
        {"9999"},
        approver=approve_all,     # would approve -- precheck must stop it first
    )
    assert result["error"] == "precondition_failed"
    assert "9999" in result["message"]