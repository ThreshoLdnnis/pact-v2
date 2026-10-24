import pytest
from fastapi.testclient import TestClient
from pact.app import create_app


@pytest.fixture
def app(tmp_path, monkeypatch):
    monkeypatch.delenv("PACT_OLLAMA_URL", raising=False)
    monkeypatch.delenv("PACT_OLLAMA_MODEL", raising=False)
    monkeypatch.setenv("PACT_MODEL_PROVIDER", "")
    monkeypatch.setenv("PACT_DEMO_PIN", "246810")
    return create_app("sqlite:///" + (tmp_path / "pact.db").as_posix(), scheduler=False)


@pytest.fixture
def client(app):
    with TestClient(app) as c:
        yield c


def login(client, user="alice"):
    r = client.post("/api/v1/auth/demo-session", json={"user_id": user, "pin": "246810"})
    assert r.status_code == 200, r.text
    return {"Authorization": "Bearer " + r.json()["access_token"]}


@pytest.fixture
def auth(client):
    return login(client)
