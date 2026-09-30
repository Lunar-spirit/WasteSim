"""Module M15 (chat). No ANTHROPIC_API_KEY is set in the test environment,
so every one of these exercises the deterministic keyword matcher — which
is itself the point of T-57 (LLM unreachable/unconfigured still answers,
never with an invented number)."""

from tests.conftest import TestSessionLocal
from tests.test_simulation import _make_ready_habitation
from app.workers.tasks_simulate import run_simulation


async def _make_completed_run(client, headers, habitation_id, horizon_years=2):
    resp = await client.post(
        f"/api/v1/habitations/{habitation_id}/simulations", json={"horizon_years": horizon_years}, headers=headers
    )
    run_id = resp.json()["data"]["id"]
    await run_simulation(run_id, session_factory=TestSessionLocal)
    return run_id


async def test_read_question_grounds_every_number_in_citations(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Chatville")
    run_id = await _make_completed_run(client, planner_headers, habitation_id)

    session_resp = await client.post(
        "/api/v1/chat/sessions", json={"habitation_id": habitation_id}, headers=planner_headers
    )
    assert session_resp.status_code == 201, session_resp.text
    session_id = session_resp.json()["data"]["id"]

    query_resp = await client.post(
        f"/api/v1/chat/sessions/{session_id}/query",
        json={"message": f"What are the findings for run {run_id}?"},
        headers=planner_headers,
    )
    assert query_resp.status_code == 200, query_resp.text
    answer = query_resp.json()["data"]
    assert answer["role"] == "ASSISTANT"
    assert len(answer["citations"]) > 0
    for citation in answer["citations"]:
        assert citation["run_id"] == run_id

    messages_resp = await client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=planner_headers)
    messages = messages_resp.json()["data"]
    assert len(messages) == 2  # USER + ASSISTANT
    assert messages[0]["role"] == "USER"

    tool_calls_resp = await client.get(
        f"/api/v1/chat/sessions/{session_id}/messages/{answer['id']}/tool-calls", headers=planner_headers
    )
    tool_calls = tool_calls_resp.json()["data"]
    assert len(tool_calls) == 1
    assert tool_calls[0]["tool_name"] == "get_run_findings"
    assert tool_calls[0]["status"] == "OK"


async def test_researcher_write_request_is_denied_and_recorded(client, planner_headers, researcher_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Deniedville")
    await _make_completed_run(client, planner_headers, habitation_id)

    session_resp = await client.post(
        "/api/v1/chat/sessions", json={"habitation_id": habitation_id}, headers=researcher_headers
    )
    assert session_resp.status_code == 201, session_resp.text
    session_id = session_resp.json()["data"]["id"]

    query_resp = await client.post(
        f"/api/v1/chat/sessions/{session_id}/query",
        json={"message": "please optimize this habitation's waste plan"},
        headers=researcher_headers,
    )
    assert query_resp.status_code == 200  # a refusal is a normal chat outcome, not an HTTP error
    answer = query_resp.json()["data"]
    assert "can't" in answer["content"].lower()

    tool_calls_resp = await client.get(
        f"/api/v1/chat/sessions/{session_id}/messages/{answer['id']}/tool-calls", headers=researcher_headers
    )
    tool_calls = tool_calls_resp.json()["data"]
    assert tool_calls[0]["tool_name"] == "create_optimization"
    assert tool_calls[0]["status"] == "DENIED"


async def test_ambiguous_question_returns_clarification_not_a_guess(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Fuzzville")
    session_resp = await client.post(
        "/api/v1/chat/sessions", json={"habitation_id": habitation_id}, headers=planner_headers
    )
    session_id = session_resp.json()["data"]["id"]

    query_resp = await client.post(
        f"/api/v1/chat/sessions/{session_id}/query",
        json={"message": "asdkjqwoe unrelated gibberish"},
        headers=planner_headers,
    )
    assert query_resp.status_code == 200
    answer = query_resp.json()["data"]
    assert answer["citations"] == []


async def test_write_tool_via_chat_actually_starts_a_scenario_run(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Chatscenarioville")
    await _make_completed_run(client, planner_headers, habitation_id)

    session_resp = await client.post(
        "/api/v1/chat/sessions", json={"habitation_id": habitation_id}, headers=planner_headers
    )
    session_id = session_resp.json()["data"]["id"]

    query_resp = await client.post(
        f"/api/v1/chat/sessions/{session_id}/query",
        json={"message": "what if there's a flood scenario next year?"},
        headers=planner_headers,
    )
    assert query_resp.status_code == 200, query_resp.text
    answer = query_resp.json()["data"]

    tool_calls_resp = await client.get(
        f"/api/v1/chat/sessions/{session_id}/messages/{answer['id']}/tool-calls", headers=planner_headers
    )
    tool_calls = tool_calls_resp.json()["data"]
    assert tool_calls[0]["tool_name"] == "create_scenario_run"
    assert tool_calls[0]["status"] == "OK", tool_calls[0]
    new_run_id = tool_calls[0]["result_summary"]["run_id"]

    run_status = await client.get(f"/api/v1/simulations/{new_run_id}", headers=planner_headers)
    assert run_status.json()["data"]["run_type"] == "SCENARIO"


async def test_session_not_owned_by_caller_is_forbidden(client, planner_headers, researcher_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Ownerville")
    session_resp = await client.post(
        "/api/v1/chat/sessions", json={"habitation_id": habitation_id}, headers=planner_headers
    )
    session_id = session_resp.json()["data"]["id"]

    resp = await client.get(f"/api/v1/chat/sessions/{session_id}/messages", headers=researcher_headers)
    assert resp.status_code == 403


# --- POST /api/v1/chat/message (stateless floating-copilot endpoint) --------


async def test_message_faq_optimization_blocked_reflects_real_db_state(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Faqoptville")
    # Parameters are VALIDATED (via _make_ready_habitation) but no base
    # simulation exists yet — the FAQ answer should name that specific gap,
    # not a generic "something's missing".
    resp = await client.post(
        "/api/v1/chat/message",
        json={"habitation_id": habitation_id, "message": "Why can't I run optimization?"},
        headers=planner_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["source"] == "faq"
    assert "baseline simulation" in data["content"]
    assert data["citations"] == []


async def test_message_faq_optimization_blocked_reports_ready_once_base_run_exists(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Faqoptreadyville")
    await _make_completed_run(client, planner_headers, habitation_id)

    resp = await client.post(
        "/api/v1/chat/message",
        json={"habitation_id": habitation_id, "message": "why is optimization blocked?"},
        headers=planner_headers,
    )
    data = resp.json()["data"]
    assert data["source"] == "faq"
    assert "all set" in data["content"].lower()


async def test_message_faq_fix_parameters_needs_no_habitation(client, planner_headers):
    resp = await client.post(
        "/api/v1/chat/message",
        json={"message": "How do I fix parameters?"},
        headers=planner_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["source"] == "faq"
    assert "100%" in data["content"]
    assert "Commit" in data["content"]


async def test_message_faq_tornado_chart(client, planner_headers):
    resp = await client.post(
        "/api/v1/chat/message", json={"message": "What is the Tornado chart?"}, headers=planner_headers
    )
    data = resp.json()["data"]
    assert data["source"] == "faq"
    assert "elasticity" in data["content"].lower()


async def test_message_grounded_tool_path_still_cites_real_numbers(client, planner_headers):
    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Msgtoolville")
    run_id = await _make_completed_run(client, planner_headers, habitation_id)

    resp = await client.post(
        "/api/v1/chat/message",
        json={"habitation_id": habitation_id, "message": f"What are the findings for run {run_id}?"},
        headers=planner_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["source"] == "tool"
    assert len(data["citations"]) > 0
    for citation in data["citations"]:
        assert citation["run_id"] == run_id


async def test_message_write_tool_is_described_not_executed(client, planner_headers, db_session):
    from sqlalchemy import func, select

    from app.optimization.models import OptimizationRun

    habitation_id, _psid = await _make_ready_habitation(client, planner_headers, "Msgnowriteville")
    await _make_completed_run(client, planner_headers, habitation_id)

    before = await db_session.scalar(select(func.count()).select_from(OptimizationRun))

    resp = await client.post(
        "/api/v1/chat/message",
        json={"habitation_id": habitation_id, "message": "please optimize this habitation's waste plan"},
        headers=planner_headers,
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["source"] == "faq"
    assert "won't start" in data["content"]

    after = await db_session.scalar(select(func.count()).select_from(OptimizationRun))
    assert after == before  # nothing was actually created


async def test_message_without_habitation_falls_back_without_error(client, planner_headers):
    resp = await client.post(
        "/api/v1/chat/message", json={"message": "asdkjqwoe unrelated gibberish"}, headers=planner_headers
    )
    assert resp.status_code == 200, resp.text
    data = resp.json()["data"]
    assert data["source"] == "fallback"
    assert data["content"]


async def test_message_unknown_habitation_returns_404(client, planner_headers):
    resp = await client.post(
        "/api/v1/chat/message",
        json={"habitation_id": "00000000-0000-0000-0000-000000000000", "message": "hello"},
        headers=planner_headers,
    )
    assert resp.status_code == 404
