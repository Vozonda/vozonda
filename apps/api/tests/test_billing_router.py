import tempfile
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vozonda_api.billing import charge_job, init_billing_db
from vozonda_api.main import app
from vozonda_api.routers.billing import router as billing_router


@pytest.fixture
def billing_env(monkeypatch):
    """Set up temporary database and environment for billing tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        monkeypatch.setenv("VOZONDA_DB", str(db_path))
        monkeypatch.delenv("VOZONDA_COSTS", raising=False)
        init_billing_db()
        yield db_path


def test_billing_routes_registered_exactly_once():
    """Verify each billing path is registered exactly once via the router and in app."""
    router_routes = [
        (method, r.path)
        for r in billing_router.routes
        if hasattr(r, "methods") and hasattr(r, "path")
        for method in r.methods
        if method not in ("HEAD", "OPTIONS")
    ]
    expected_routes = {
        ("POST", "/billing/tokens"),
        ("GET", "/billing/tokens/{user_id}"),
        ("POST", "/billing/tokens/{token_id}/revoke"),
        ("GET", "/billing/balance/{user_id}"),
        ("POST", "/billing/balance/{user_id}"),
        ("GET", "/billing/charges/{user_id}"),
    }
    assert len(router_routes) == 6
    assert set(router_routes) == expected_routes

    # Verify the paths are registered in the main FastAPI app exactly once.
    # FastAPI wraps included routers in _IncludedRouter; unwrap it.
    app_routes_unwrapped = []
    pending = list(app.routes)
    while pending:
        r = pending.pop(0)
        if type(r).__name__ == "_IncludedRouter":
            pending.extend(r.effective_candidates())  # type: ignore[attr-defined]
        else:
            app_routes_unwrapped.append(r)

    app_billing_routes = [
        (method, r.path)
        for r in app_routes_unwrapped
        if hasattr(r, "methods") and hasattr(r, "path") and r.path and r.path.startswith("/billing/")
        for method in r.methods
        if method not in ("HEAD", "OPTIONS")
    ]
    assert len(app_billing_routes) == 6
    assert set(app_billing_routes) == expected_routes
    for route_item in expected_routes:
        assert app_billing_routes.count(route_item) == 1


def test_fixed_scenario_responses(billing_env, monkeypatch):
    """Verify responses for a fixed scenario equal pre-refactor outputs."""
    monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")
    monkeypatch.setenv("VOZONDA_TOKEN", "test-secret-token")
    monkeypatch.delenv("VOZONDA_COSTS", raising=False)
    client = TestClient(app)
    auth_headers = {"Authorization": "Bearer test-secret-token"}
    user_id = "test-user-fixed"

    # Step 1: Create token
    create_token_resp = client.post(
        "/billing/tokens",
        json={"user_id": user_id, "name": "primary-key"},
        headers=auth_headers,
    )
    assert create_token_resp.status_code == 200
    token_data = create_token_resp.json()
    assert token_data["user_id"] == user_id
    assert token_data["name"] == "primary-key"
    assert isinstance(token_data["token"], str) and len(token_data["token"]) >= 32
    assert isinstance(token_data["id"], str) and len(token_data["id"]) == 16
    assert isinstance(token_data["created_at"], (int, float))

    token_id = token_data["id"]
    token_created_at = token_data["created_at"]

    # Verify listing user tokens
    list_tokens_resp = client.get(f"/billing/tokens/{user_id}", headers=auth_headers)
    assert list_tokens_resp.status_code == 200
    assert list_tokens_resp.json() == {
        "tokens": [
            {
                "id": token_id,
                "name": "primary-key",
                "created_at": token_created_at,
                "last_used": None,
            }
        ]
    }

    # Step 2: Set balance
    add_balance_resp = client.post(
        f"/billing/balance/{user_id}",
        json={"amount_sats": 5000},
        headers=auth_headers,
    )
    assert add_balance_resp.status_code == 200
    assert add_balance_resp.json() == {"user_id": user_id, "balance_sats": 5000}

    # Verify balance lookup
    get_balance_resp = client.get(f"/billing/balance/{user_id}", headers=auth_headers)
    assert get_balance_resp.status_code == 200
    assert get_balance_resp.json() == {"user_id": user_id, "balance_sats": 5000}

    # Step 3: Charge listed
    charge = charge_job("job-fixed-101", user_id, "qwen", "standard")
    assert charge["amount_sats"] == 1000

    list_charges_resp = client.get(f"/billing/charges/{user_id}", headers=auth_headers)
    assert list_charges_resp.status_code == 200
    assert list_charges_resp.json() == {
        "user_id": user_id,
        "charges": [
            {
                "id": charge["charge_id"],
                "job_id": "job-fixed-101",
                "user_id": user_id,
                "provider": "qwen",
                "job_type": "standard",
                "amount_sats": 1000,
                "charged_at": charge["charged_at"],
                "status": "pending",
                "notes": None,
            }
        ],
    }

    # Balance after charge is 5000 - 1000 = 4000
    bal_after = client.get(f"/billing/balance/{user_id}", headers=auth_headers)
    assert bal_after.status_code == 200
    assert bal_after.json() == {"user_id": user_id, "balance_sats": 4000}

    # Step 4: Revoke token
    revoke_resp = client.post(
        f"/billing/tokens/{token_id}/revoke",
        headers=auth_headers,
    )
    assert revoke_resp.status_code == 200
    assert revoke_resp.json() == {"revoked": token_id}

    # Verify listing tokens is now empty
    empty_tokens_resp = client.get(f"/billing/tokens/{user_id}", headers=auth_headers)
    assert empty_tokens_resp.status_code == 200
    assert empty_tokens_resp.json() == {"tokens": []}


def test_billing_disabled_responses(monkeypatch):
    """Verify all billing routes return 503 billing disabled when disabled."""
    monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "false")
    client = TestClient(app)

    endpoints = [
        ("POST", "/billing/tokens", {"user_id": "u1"}),
        ("GET", "/billing/tokens/u1", None),
        ("POST", "/billing/tokens/tok1/revoke", None),
        ("GET", "/billing/balance/u1", None),
        ("POST", "/billing/balance/u1", {"amount_sats": 500}),
        ("GET", "/billing/charges/u1", None),
    ]

    for method, path, payload in endpoints:
        if method == "POST":
            resp = client.post(path, json=payload or {})
        else:
            resp = client.get(path)
        assert resp.status_code == 503, f"{method} {path} should return 503"
        assert resp.json() == {"detail": "billing disabled"}


def test_billing_auth_required_when_enabled(billing_env, monkeypatch):
    """Verify write endpoints require VOZONDA_TOKEN auth when billing is enabled."""
    monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")
    monkeypatch.setenv("VOZONDA_TOKEN", "valid-secret")
    client = TestClient(app)

    # Missing auth header
    resp = client.post("/billing/tokens", json={"user_id": "u1"})
    assert resp.status_code == 401
    assert resp.json() == {"detail": "missing or invalid token"}

    resp = client.post("/billing/balance/u1", json={"amount_sats": 100})
    assert resp.status_code == 401
    assert resp.json() == {"detail": "missing or invalid token"}

    resp = client.post("/billing/tokens/tok1/revoke")
    assert resp.status_code == 401
    assert resp.json() == {"detail": "missing or invalid token"}

    # Invalid token
    bad_auth = {"Authorization": "Bearer wrong-secret"}
    resp = client.post("/billing/tokens", json={"user_id": "u1"}, headers=bad_auth)
    assert resp.status_code == 401
    assert resp.json() == {"detail": "missing or invalid token"}


def test_billing_error_cases(billing_env, monkeypatch):
    """Verify edge cases like user not found and invalid amount."""
    monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")
    monkeypatch.setenv("VOZONDA_TOKEN", "test-secret-token")
    client = TestClient(app)
    auth_headers = {"Authorization": "Bearer test-secret-token"}

    # 404 on get balance for nonexistent user
    resp = client.get("/billing/balance/nonexistent-user", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json() == {"detail": "user not found"}

    # 422 on non-positive balance top-up
    resp = client.post(
        "/billing/balance/u1",
        json={"amount_sats": 0},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "amount must be positive"}

    resp = client.post(
        "/billing/balance/u1",
        json={"amount_sats": -50},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert resp.json() == {"detail": "amount must be positive"}
