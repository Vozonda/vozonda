"""Tests for billing read endpoint authentication (DUE-VOZONDA-BILLING-READ-AUTH).

Covers:
- Unauthenticated requests -> 401
- Another user's access token -> 403
- Own access token -> 200 with data
- Operator write auth (VOZONDA_TOKEN) -> 200
- Forced internal error returns no exception text in response body
"""

import tempfile
import unittest.mock
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from vozonda_api.billing import (
    add_user_balance,
    create_access_token,
    create_user,
    get_user_balance,
    init_billing_db,
)
from vozonda_api.main import app


@pytest.fixture
def billing_env(monkeypatch):
    """Set up temporary database and environment for billing tests."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        monkeypatch.setenv("VOZONDA_DB", str(db_path))
        monkeypatch.delenv("VOZONDA_TOKEN", raising=False)
        monkeypatch.delenv("VOZONDA_COSTS", raising=False)
        init_billing_db()
        yield db_path


def _ensure_user(user_id, balance=5000):
    """Create a user with balance if they don't exist yet."""
    if get_user_balance(user_id) is None:
        create_user(user_id)
    add_user_balance(user_id, balance - (get_user_balance(user_id) or 0))


class TestUnauthenticated:
    """Unauthenticated requests to read endpoints return 401."""

    @pytest.mark.parametrize(
        "path",
        [
            "/billing/tokens/test-user-auth",
            "/billing/balance/test-user-auth",
            "/billing/charges/test-user-auth",
        ],
    )
    def test_no_auth_returns_401(self, billing_env, monkeypatch, path):
        monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")
        client = TestClient(app)
        resp = client.get(path)
        assert resp.status_code == 401, f"{path} should return 401 without auth"

    @pytest.mark.parametrize(
        "path",
        [
            "/billing/tokens/test-user-auth",
            "/billing/balance/test-user-auth",
            "/billing/charges/test-user-auth",
        ],
    )
    def test_invalid_token_returns_401(self, billing_env, monkeypatch, path):
        monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")
        monkeypatch.setenv("VOZONDA_TOKEN", "secret")
        client = TestClient(app)
        resp = client.get(path, headers={"Authorization": "Bearer invalid"})
        assert resp.status_code == 401, f"{path} should return 401 with invalid token"

    def test_balance_invalid_token_returns_401(self, billing_env, monkeypatch):
        """Invalid operator token returns 401 (not public read)."""
        monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")
        monkeypatch.setenv("VOZONDA_TOKEN", "secret")
        _ensure_user("test-user-auth", 3000)
        client = TestClient(app)
        resp = client.get(
            "/billing/balance/test-user-auth",
            headers={"Authorization": "Bearer invalid"},
        )
        assert resp.status_code == 401


class TestTokenAccess:
    """Access token belonging to the path user_id is allowed; another user's is not."""

    def test_own_token_gives_200(self, billing_env, monkeypatch):
        monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")
        _ensure_user("test-user-auth", 5000)
        token_value, _ = create_access_token("test-user-auth", name="test")
        client = TestClient(app)

        resp = client.get(
            "/billing/tokens/test-user-auth",
            headers={"Authorization": f"Bearer {token_value}"},
        )
        assert resp.status_code == 200
        assert "tokens" in resp.json()

        resp = client.get(
            "/billing/balance/test-user-auth",
            headers={"Authorization": f"Bearer {token_value}"},
        )
        assert resp.status_code == 200
        assert resp.json()["balance_sats"] == 5000

        resp = client.get(
            "/billing/charges/test-user-auth",
            headers={"Authorization": f"Bearer {token_value}"},
        )
        assert resp.status_code == 200
        assert "charges" in resp.json()

    def test_token_via_query_param(self, billing_env, monkeypatch):
        """?token=... query parameter also works."""
        monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")
        _ensure_user("test-user-auth", 5000)
        tv, _ = create_access_token("test-user-auth", name="test")
        client = TestClient(app)

        resp = client.get(f"/billing/balance/test-user-auth?token={tv}")
        assert resp.status_code == 200
        assert resp.json()["balance_sats"] == 5000

    def test_another_users_token_returns_403(self, billing_env, monkeypatch):
        monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")
        _ensure_user("user1", 1000)
        token1_value, _ = create_access_token("user1", name="token1")
        _ensure_user("user2", 2000)

        client = TestClient(app)
        for path in [
            "/billing/tokens/user2",
            "/billing/balance/user2",
            "/billing/charges/user2",
        ]:
            resp = client.get(path, headers={"Authorization": f"Bearer {token1_value}"})
            assert resp.status_code == 403, f"{path} should return 403"

    def test_token_for_nonexistent_user_id_returns_403(self, billing_env, monkeypatch):
        monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")
        _ensure_user("real-user", 1000)
        token_value, _ = create_access_token("real-user", name="t")
        client = TestClient(app)

        resp = client.get(
            "/billing/balance/fake-user",
            headers={"Authorization": f"Bearer {token_value}"},
        )
        assert resp.status_code == 403


class TestOperatorAuth:
    """Operator with VOZONDA_TOKEN bearer auth can read all three endpoints."""

    @pytest.mark.parametrize(
        "path",
        [
            "/billing/tokens/test-user-op",
            "/billing/balance/test-user-op",
            "/billing/charges/test-user-op",
        ],
    )
    def test_operator_token_allows_read(self, billing_env, monkeypatch, path):
        monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")
        monkeypatch.setenv("VOZONDA_TOKEN", "operator-secret")
        _ensure_user("test-user-op", 3000)
        client = TestClient(app)

        resp = client.get(
            path,
            headers={"Authorization": "Bearer operator-secret"},
        )
        assert resp.status_code == 200, f"{path} should return 200 for operator"

    def test_operator_wrong_token_returns_401(self, billing_env, monkeypatch):
        """A wrong VOZONDA_TOKEN bearer returns 401 (no fallthrough to public read)."""
        monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")
        monkeypatch.setenv("VOZONDA_TOKEN", "correct-secret")
        _ensure_user("test-user-op2", 1000)
        client = TestClient(app)

        resp = client.get(
            "/billing/balance/test-user-op2",
            headers={"Authorization": "Bearer wrong-secret"},
        )
        # Invalid operator auth returns 401
        assert resp.status_code == 401

    def test_different_user_token_returns_403(self, billing_env, monkeypatch):
        """A valid access token belonging to user A trying to read user B's data -> 403."""
        monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")
        _ensure_user("user-a", 1000)
        _ensure_user("user-b", 2000)
        token_a_value, _ = create_access_token("user-a", name="a")
        client = TestClient(app)

        for path in [
            "/billing/balance/user-b",
            "/billing/tokens/user-b",
            "/billing/charges/user-b",
        ]:
            resp = client.get(path, headers={"Authorization": f"Bearer {token_a_value}"})
            assert resp.status_code == 403, f"{path} should return 403"


class TestNoExceptionLeak:
    """500 responses must not leak exception details in the body."""

    def test_list_tokens_no_leak(self, billing_env, monkeypatch):
        monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")
        _ensure_user("test-user-auth", 5000)
        token_value, _ = create_access_token("test-user-auth", name="t")
        client = TestClient(app)

        with unittest.mock.patch(
            "vozonda_api.billing.list_user_tokens",
            side_effect=RuntimeError("database is corrupted"),
        ):
            resp = client.get(
                "/billing/tokens/test-user-auth",
                headers={"Authorization": f"Bearer {token_value}"},
            )
            assert resp.status_code == 500
            body = resp.json()
            assert "database is corrupted" not in body.get("detail", "")
            assert body["detail"] == "failed to list tokens"

    def test_get_balance_no_leak(self, billing_env, monkeypatch):
        monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")
        _ensure_user("test-user-auth", 1000)
        token_value, _ = create_access_token("test-user-auth", name="t")
        client = TestClient(app)

        with unittest.mock.patch(
            "vozonda_api.billing.get_user_balance",
            side_effect=RuntimeError("bad db"),
        ):
            resp = client.get(
                "/billing/balance/test-user-auth",
                headers={"Authorization": f"Bearer {token_value}"},
            )
            assert resp.status_code == 500
            body = resp.json()
            assert "bad" not in body.get("detail", "")
            assert body["detail"] == "failed to get balance"

    def test_list_charges_no_leak(self, billing_env, monkeypatch):
        monkeypatch.setenv("VOZONDA_ENABLE_BILLING", "true")
        _ensure_user("test-user-auth", 5000)
        token_value, _ = create_access_token("test-user-auth", name="t")
        client = TestClient(app)

        with unittest.mock.patch(
            "vozonda_api.billing.list_user_charges",
            side_effect=RuntimeError("corrupt index"),
        ):
            resp = client.get(
                "/billing/charges/test-user-auth",
                headers={"Authorization": f"Bearer {token_value}"},
            )
            assert resp.status_code == 500
            body = resp.json()
            assert "corrupt index" not in body.get("detail", "")
            assert body["detail"] == "failed to list charges"