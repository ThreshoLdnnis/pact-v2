"""Controlled provider responses: no credentials and no live model required."""
import json
import httpx
import pytest
from pact.common import DomainError
from pact.settings import load_local_env
from services.agent import model_adapter, planner
from tests.test_workflows import API, balance, plan, run

CANDIDATE = {"title": "payment", "minimum_balance_cents": 0, "steps": [{"step_id": "pay", "depends_on": [], "action": {"tool": "transfer", "account_id": "acct-alice", "recipient_query": "张三", "amount_cents": 50000}}]}


def configure(monkeypatch):
    for k, v in {"PACT_MODEL_PROVIDER": "openai_compatible", "PACT_LLM_BASE_URL": "https://model.example/v1", "PACT_LLM_MODEL": "configured-by-user", "PACT_LLM_API_KEY": "test-only-private-key", "PACT_LLM_FORMAT": "json_schema"}.items():
        monkeypatch.setenv(k, v)


def completion(candidate=None):
    return {"choices": [{"finish_reason": "stop", "message": {"content": json.dumps(CANDIDATE if candidate is None else candidate)}}]}


def mock_response(monkeypatch, body, status=200, inspect=None):
    def post(url, **kwargs):
        if inspect:
            inspect(url, kwargs)
        return httpx.Response(status, json=body, request=httpx.Request("POST", url))
    monkeypatch.setattr(httpx, "post", post)


def test_external_provider_candidate_still_requires_backend_approval(client, auth, monkeypatch):
    configure(monkeypatch)
    def inspect(url, kwargs):
        assert url == "https://model.example/v1/chat/completions"
        assert kwargs["headers"]["Authorization"] == "Bearer test-only-private-key"
        assert not kwargs["follow_redirects"] and not kwargs["trust_env"]
        payload = kwargs["json"]
        assert "tools" not in payload and payload["response_format"]["json_schema"]["strict"] is True
        assert "test-only-private-key" not in json.dumps(payload)
        assert "balance_cents" not in payload["messages"][1]["content"]
    mock_response(monkeypatch, completion(), inspect=inspect)
    before = balance(client, auth)
    p = run(client, auth, plan(client, auth, "给张三转账500元"))
    assert p["planner"] == "openai_compatible" and p["status"] == "waiting_approval"
    assert balance(client, auth) == before
    assert "test-only-private-key" not in client.get(API + "/meta").text


@pytest.mark.parametrize("body,status", [
    ({"choices": []}, 200), ({"choices": [{}]}, 200), ({"choices": [{"finish_reason": "length", "message": {"content": "{}"}}]}, 200),
    ({"choices": [{"finish_reason": "stop", "message": {"refusal": "no", "content": "{}"}}]}, 200),
    ({"choices": [{"finish_reason": "stop", "message": {"tool_calls": [{}], "content": "{}"}}]}, 200),
    ({"choices": [{"finish_reason": "stop", "message": {"content": None}}]}, 200),
    ({"choices": [{"finish_reason": "stop", "message": {"content": "not JSON"}}]}, 200),
    (completion({**CANDIDATE, "status": "succeeded"}), 200),
    ({"error": {"message": "test-only-private-key upstream detail"}}, 401),
])
def test_bad_responses_fail_closed_and_redact_provider_errors(client, auth, monkeypatch, body, status):
    configure(monkeypatch)
    mock_response(monkeypatch, body, status)
    before = balance(client, auth)
    response = client.post(API + "/agent/plans", headers=auth, json={"message": "给张三转账500元"})
    assert response.status_code == 502 and response.json()["error"]["code"] == "PLANNER_UNAVAILABLE"
    assert "test-only-private-key" not in response.text and balance(client, auth) == before


@pytest.mark.parametrize("key,value", [("PACT_LLM_API_KEY", ""), ("PACT_LLM_BASE_URL", "http://remote.example/v1"), ("PACT_LLM_BASE_URL", "https://key@host/v1"), ("PACT_LLM_FORMAT", "invalid")])
def test_bad_config_never_calls_network_or_falls_back(monkeypatch, key, value):
    configure(monkeypatch)
    monkeypatch.setenv(key, value)
    monkeypatch.setattr(httpx, "post", lambda *a, **k: pytest.fail("network was called"))
    with pytest.raises(DomainError, match="模型服务"):
        planner.parse("查余额", "acct-alice", [], [])


def test_timeout_is_safe_and_json_object_is_explicit(monkeypatch):
    configure(monkeypatch)
    monkeypatch.setenv("PACT_LLM_FORMAT", "json_object")
    def inspect(url, kwargs):
        assert kwargs["json"]["response_format"] == {"type": "json_object"}
    mock_response(monkeypatch, completion(), inspect=inspect)
    assert planner.parse("给张三转账500元", "acct-alice", [{"name": "张三"}], [])[1] == "openai_compatible"
    monkeypatch.setattr(httpx, "post", lambda *a, **k: (_ for _ in ()).throw(httpx.ReadTimeout("private provider detail")))
    with pytest.raises(DomainError) as failure:
        planner.parse("查余额", "acct-alice", [], [])
    assert "private provider detail" not in str(failure.value)


def test_schema_has_required_closed_objects_and_supported_union():
    def inspect(node):
        if isinstance(node, dict):
            assert "default" not in node and "oneOf" not in node and "discriminator" not in node
            if node.get("type") == "object":
                assert set(node["required"]) == set(node["properties"]) and node["additionalProperties"] is False
            for value in node.values():
                inspect(value)
        elif isinstance(node, list):
            for value in node:
                inspect(value)
    inspect(model_adapter.strict_schema())


@pytest.mark.parametrize("message,candidate", [
    ("查余额", CANDIDATE),
    ("给张三转账500元", {"title": "fake completion", "steps": [{"step_id": "read", "action": {"tool": "balance", "account_id": "acct-alice"}}]}),
    ("分析账单", {"title": "omission", "steps": [{"step_id": "read", "action": {"tool": "balance", "account_id": "acct-alice"}}]}),
    ("给张三转账500元", {**CANDIDATE, "steps": [{"step_id": "pay", "action": {**CANDIDATE["steps"][0]["action"], "account_id": "acct-bob"}}]}),
])
def test_model_cannot_add_or_omit_explicit_business_intent(monkeypatch, message, candidate):
    configure(monkeypatch)
    mock_response(monkeypatch, completion(candidate))
    with pytest.raises(DomainError):
        planner.parse(message, "acct-alice", [], [])


def test_env_reader_only_allowed_values_and_never_evaluates(tmp_path, monkeypatch):
    monkeypatch.setenv("PACT_LLM_MODEL", "existing")
    monkeypatch.delenv("PACT_LLM_API_KEY", raising=False)
    path = tmp_path / ".env"
    path.write_text('PACT_LLM_MODEL=overridden\nPACT_LLM_API_KEY="literal-$(echo-secret)"\nUNRELATED_SECRET=bad\n', "utf-8")
    load_local_env(path)
    import os
    assert os.environ["PACT_LLM_MODEL"] == "existing"
    assert os.environ["PACT_LLM_API_KEY"] == "literal-$(echo-secret)"
    assert "UNRELATED_SECRET" not in os.environ
