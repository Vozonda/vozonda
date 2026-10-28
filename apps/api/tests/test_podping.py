"""Tests for Podping module (apps/api/src/vozonda_api/podping.py).

No network is used; the HTTP client is monkeypatched.
"""

import json
import time
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from vozonda_api.jobs import JobStore
from vozonda_api.podping import ping_job


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_job(show_name: str = "Test Show", show_slug: str = "s1",
              show_number: str = "1") -> dict:
    return {
        "id": "test-job-1",
        "state": "done",
        "show_name": show_name,
        "show_slug": show_slug,
        "watchlist_id": "",
    }


def _mock_store(job: dict) -> MagicMock:
    store_mock = MagicMock(spec=JobStore)
    store_mock.get.return_value = job
    return store_mock


class _Patches:
    """Stack multiple context managers."""
    def __init__(self, *ctx_managers):
        self.ctx_managers = list(ctx_managers)

    def __enter__(self):
        for cm in self.ctx_managers:
            cm.__enter__()
        return self

    def __exit__(self, *exc):
        for cm in reversed(self.ctx_managers):
            cm.__exit__(*exc)


def _make_resp(status: int) -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.__aenter__ = AsyncMock(return_value=r)
    r.__aexit__ = AsyncMock(return_value=None)
    return r


def _settings_patch(scenario: dict[str, str]):
    return patch(
        "vozonda_api.podping.get_setting",
        side_effect=lambda key: scenario.get(key),
    )


def _configured_base_patch(value: str):
    return patch("vozonda_api.podping.configured_base", return_value=value)


def _public_checker_patch(predicate: bool):
    return patch(
        "vozonda_api.podping._public_checker",
        return_value=lambda job: predicate,
    )


def _setup_http_mock(mock_httpx, status_code: int, status_codes: list | None = None):
    if status_codes is None:
        status_codes = [status_code]
    responses = []
    for sc in status_codes:
        resp = MagicMock()
        resp.status_code = sc
        responses.append(resp)
    mock_client = MagicMock()
    mock_client.get = AsyncMock(side_effect=responses)
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    mock_httpx.return_value = mock_client
    return mock_client, responses


def _build_context(mock_client, scenario: dict[str, str]):
    """Return (_Patches, context_dict)."""
    job = _make_job()
    store = _mock_store(job)
    set_setting_mock = MagicMock()
    ctx_managers = [
        _settings_patch(scenario),
        _configured_base_patch(scenario["address.public"]),
        _public_checker_patch(True),
        patch("vozonda_api.podping.JobStore", return_value=store),
        patch("vozonda_api.podping.set_setting", set_setting_mock),
    ]
    ctx = {
        "store": store,
        "set_setting_mock": set_setting_mock,
        "job": job,
    }
    return _Patches(*ctx_managers), ctx


# ---------------------------------------------------------------------------
# Scenarios
# ---------------------------------------------------------------------------

PUBLIC_SCENARIO = {
    "podping.enabled": "1",
    "podping.token": "test-podping-token",
    "privacy.mode": "",
    "address.public": "https://example.org",
    "show.1.name": "Test Show",
}

PUBLIC_SCENARIO_TKN = {
    "podping.enabled": "1",
    "podping.token": "tkn",
    "privacy.mode": "",
    "address.public": "https://example.org",
    "show.1.name": "Test Show",
}


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_debounce(monkeypatch):
    import vozonda_api.podping as podping_mod
    podping_mod._DEBOUNCE_CACHE.clear()
    # the default show unless a test says otherwise: the real lookup reads the settings DB, which
    # another test running in parallel may have given a show 1 (then the URL, and the debounce key, change)
    monkeypatch.setattr(podping_mod, "_job_show_num", lambda job: "default")
    yield
    podping_mod._DEBOUNCE_CACHE.clear()


@pytest.fixture
def mock_httpx():
    with patch("vozonda_api.podping.httpx.AsyncClient") as mock:
        yield mock


# ---------------------------------------------------------------------------
# Tests: gating conditions
# ---------------------------------------------------------------------------


class TestDisabled:
    def test_disabled_no_call(self, mock_httpx):
        scenario = {
            "podping.enabled": "0",
            "podping.token": "tkn",
            "privacy.mode": "",
            "address.public": "https://example.org",
        }
        with _settings_patch(scenario):
            job = _make_job()
            store = _mock_store(job)
            with patch("vozonda_api.podping.JobStore", return_value=store):
                asyncio_run(ping_job("test-job-1"))
        mock_httpx.assert_not_called()

    def test_unset_no_call(self, mock_httpx):
        scenario = {
            "podping.token": "x",
            "privacy.mode": "",
            "address.public": "https://example.org",
        }
        with _settings_patch(scenario):
            job = _make_job()
            store = _mock_store(job)
            with patch("vozonda_api.podping.JobStore", return_value=store):
                asyncio_run(ping_job("test-job-1"))
        mock_httpx.assert_not_called()


class TestNoToken:
    def test_no_token(self, mock_httpx):
        scenario = {
            "podping.enabled": "1",
            "podping.token": "",
            "privacy.mode": "",
            "address.public": "https://example.org",
        }
        with _settings_patch(scenario):
            job = _make_job()
            store = _mock_store(job)
            with patch("vozonda_api.podping.JobStore", return_value=store):
                asyncio_run(ping_job("test-job-1"))
        mock_httpx.assert_not_called()


class TestConfidential:
    def test_confidential_mode(self, mock_httpx):
        scenario = {
            "podping.enabled": "1",
            "podping.token": "tkn",
            "privacy.mode": "confidential",
            "address.public": "https://example.org",
        }
        with _settings_patch(scenario):
            job = _make_job()
            store = _mock_store(job)
            with patch("vozonda_api.podping.JobStore", return_value=store):
                asyncio_run(ping_job("test-job-1"))
        mock_httpx.assert_not_called()


class TestPrivateShow:
    def test_private_show_no_ping(self, mock_httpx):
        job = _make_job(show_name="Private Show", show_slug="s1")
        store = _mock_store(job)
        with _settings_patch(PUBLIC_SCENARIO_TKN), \
                _configured_base_patch("https://example.org"), \
                _public_checker_patch(False), \
                patch("vozonda_api.podping.JobStore", return_value=store):
            asyncio_run(ping_job("test-job-1"))
        mock_httpx.assert_not_called()


class TestPrivateBaseAddress:
    def test_loopback_address(self, mock_httpx):
        job = _make_job()
        store = _mock_store(job)
        with _settings_patch(PUBLIC_SCENARIO_TKN), \
                _configured_base_patch("http://127.0.0.1:8787"), \
                _public_checker_patch(True), \
                patch("vozonda_api.podping.JobStore", return_value=store):
            asyncio_run(ping_job("test-job-1"))
        mock_httpx.assert_not_called()

    def test_private_ip(self, mock_httpx):
        job = _make_job()
        store = _mock_store(job)
        with _settings_patch(PUBLIC_SCENARIO_TKN), \
                _configured_base_patch("https://172.16.5.20:8787"), \
                _public_checker_patch(True), \
                patch("vozonda_api.podping.JobStore", return_value=store):
            asyncio_run(ping_job("test-job-1"))
        mock_httpx.assert_not_called()

    def test_empty_base(self, mock_httpx):
        scenario = {
            "podping.enabled": "1",
            "podping.token": "tkn",
            "privacy.mode": "",
            "address.public": "",
        }
        job = _make_job()
        store = _mock_store(job)
        with _settings_patch(scenario), \
                _configured_base_patch(""), \
                _public_checker_patch(True), \
                patch("vozonda_api.podping.JobStore", return_value=store):
            asyncio_run(ping_job("test-job-1"))
        mock_httpx.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: success path
# ---------------------------------------------------------------------------


class TestPublicFeedPing:
    def test_success_single_call(self, mock_httpx):
        mock_client, _ = _setup_http_mock(mock_httpx, 200)
        job = _make_job(show_name="Test Show", show_slug="s1", show_number="1")
        store = _mock_store(job)
        set_setting_mock = MagicMock()

        with _settings_patch(PUBLIC_SCENARIO), \
                _configured_base_patch("https://example.org"), \
                _public_checker_patch(True), \
                patch("vozonda_api.podping.JobStore", return_value=store), \
                patch("vozonda_api.podping.set_setting", set_setting_mock), \
                patch("vozonda_api.podping._job_show_num", return_value="1"):
            asyncio_run(ping_job("test-job-1"))

        mock_client.get.assert_called_once()
        call_kwargs = mock_client.get.call_args
        assert call_kwargs[1]["params"] == {
            "url": "https://example.org/s1/Test-Show/feed.xml",
            "reason": "update",
            "medium": "podcast",
        }
        headers = call_kwargs[1]["headers"]
        assert headers["Authorization"] == "test-podping-token"
        assert "Vozonda/" in headers["User-Agent"]

    def test_default_show_url(self, mock_httpx):
        mock_client, _ = _setup_http_mock(mock_httpx, 200)

        job = _make_job(show_name="My Show", show_slug="", show_number="default")
        store = _mock_store(job)
        set_setting_mock = MagicMock()

        with _settings_patch(PUBLIC_SCENARIO), \
                _configured_base_patch("https://example.org"), \
                _public_checker_patch(True), \
                patch("vozonda_api.podping.JobStore", return_value=store), \
                patch("vozonda_api.podping.set_setting", set_setting_mock), \
                patch("vozonda_api.podping._job_show_num", return_value="default"):
            asyncio_run(ping_job("test-job-1"))

        mock_client.get.assert_called_once()
        params = mock_client.get.call_args[1]["params"]
        assert params["url"] == "https://example.org/feed.xml"


class TestNoKeyInUrl:
    def test_key_in_url_not_pinged(self, mock_httpx):
        from vozonda_api.podping import _build_feed_url
        job = _make_job(show_name="Test Show", show_slug="s1", show_number="1")
        with _settings_patch(PUBLIC_SCENARIO), patch("vozonda_api.podping._job_show_num", return_value="1"):
            url = _build_feed_url("https://example.org", job)
        assert url == "https://example.org/s1/Test-Show/feed.xml"


class TestFeedUrlMatchesTheSettingsScreen:
    """The URL podping announces is the one routers/distribution.py shows as the show's feed_url."""

    def test_the_show_name_comes_from_the_settings_and_is_quoted(self):
        from vozonda_api.podping import _build_feed_url
        job = _make_job(show_name="old name on the job", show_slug="s2")
        with _settings_patch({"show.2.name": "Zeit & Geld"}), \
                patch("vozonda_api.podping._job_show_num", return_value="2"):
            assert _build_feed_url("https://example.org", job) == "https://example.org/s2/Zeit-%26-Geld/feed.xml"

    def test_a_show_without_a_name_is_not_announced(self, mock_httpx):
        mock_client, _ = _setup_http_mock(mock_httpx, 200)
        scenario = {k: v for k, v in PUBLIC_SCENARIO.items() if k != "show.1.name"}
        with _settings_patch(scenario), \
                _configured_base_patch("https://example.org"), \
                _public_checker_patch(True), \
                patch("vozonda_api.podping.JobStore", return_value=_mock_store(_make_job())), \
                patch("vozonda_api.podping.set_setting", MagicMock()), \
                patch("vozonda_api.podping._job_show_num", return_value="1"):
            asyncio_run(ping_job("test-job-1"))
        mock_client.get.assert_not_called()


# ---------------------------------------------------------------------------
# Tests: error handling
# ---------------------------------------------------------------------------


class TestHttpStatusHandling:
    def test_404_once(self, mock_httpx):
        mock_client, _ = _setup_http_mock(mock_httpx, 404)

        job = _make_job()
        store = _mock_store(job)

        with _settings_patch(PUBLIC_SCENARIO_TKN), \
                _configured_base_patch("https://example.org"), \
                _public_checker_patch(True), \
                patch("vozonda_api.podping.JobStore", return_value=store):
            asyncio_run(ping_job("test-job-1"))

        assert mock_client.get.call_count == 1

    def test_500_then_200_two_calls(self, mock_httpx):
        mock_client, _ = _setup_http_mock(mock_httpx, 200, status_codes=[500, 200])

        job = _make_job()
        store = _mock_store(job)

        with _settings_patch(PUBLIC_SCENARIO_TKN), \
                _configured_base_patch("https://example.org"), \
                _public_checker_patch(True), \
                patch("vozonda_api.podping.JobStore", return_value=store):
            asyncio_run(ping_job("test-job-1"))

        assert mock_client.get.call_count == 2


class TestConnectionError:
    def test_connection_error_then_success(self, mock_httpx):
        # Set up: mock 500 response first, then success
        mock_client, _ = _setup_http_mock(mock_httpx, 200, status_codes=[500, 200])

        # Override get: first call raises httpx.ConnectError, second returns 200
        resp200 = _make_resp(200)
        mock_client.get = AsyncMock(side_effect=[httpx.ConnectError("connection refused"), resp200])

        job = _make_job()
        store = _mock_store(job)

        with _settings_patch(PUBLIC_SCENARIO_TKN), \
                _configured_base_patch("https://example.org"), \
                _public_checker_patch(True), \
                patch("vozonda_api.podping.JobStore", return_value=store):
            asyncio_run(ping_job("test-job-1"))

        assert mock_client.get.call_count == 2


# ---------------------------------------------------------------------------
# Tests: debounce
# ---------------------------------------------------------------------------


class TestDebounce:
    def test_debounce_within_60s(self, mock_httpx):
        mock_client, _ = _setup_http_mock(mock_httpx, 200)

        import vozonda_api.podping as mod

        job = _make_job()
        store = _mock_store(job)

        with _settings_patch(PUBLIC_SCENARIO_TKN), \
                _configured_base_patch("https://example.org"), \
                _public_checker_patch(True), \
                patch("vozonda_api.podping.JobStore", return_value=store):
            asyncio_run(ping_job("test-job-1"))
            asyncio_run(ping_job("test-job-2"))

        assert mock_client.get.call_count == 1

    def test_debounce_clears_after_60s(self, mock_httpx):
        mock_client, _ = _setup_http_mock(mock_httpx, 200)

        import vozonda_api.podping as mod

        job = _make_job()
        store = _mock_store(job)

        with _settings_patch(PUBLIC_SCENARIO_TKN), \
                _configured_base_patch("https://example.org"), \
                _public_checker_patch(True), \
                patch("vozonda_api.podping.JobStore", return_value=store):
            asyncio_run(ping_job("test-job-1"))

            mod._DEBOUNCE_CACHE["https://example.org/feed.xml"] = time.time() - 61

            asyncio_run(ping_job("test-job-2"))

        assert mock_client.get.call_count == 2


# ---------------------------------------------------------------------------
# Tests: last result recording
# ---------------------------------------------------------------------------


class TestLastResult:
    def test_last_result_on_success(self, mock_httpx):
        mock_client, _ = _setup_http_mock(mock_httpx, 200)
        patches, ctx = _build_context(mock_client, PUBLIC_SCENARIO)

        with patches:
            asyncio_run(ping_job("test-job-1"))

        assert ctx["set_setting_mock"].call_count == 1
        args = ctx["set_setting_mock"].call_args
        assert args[0][0] == "podping.last"
        result = json.loads(args[0][1])
        assert "url" in result
        assert "at" in result
        assert "status" in result
        assert "token" not in result.get("url", "")

    def test_last_result_on_error(self, mock_httpx):
        mock_client, _ = _setup_http_mock(mock_httpx, 404)
        patches, ctx = _build_context(mock_client, PUBLIC_SCENARIO)

        with patches:
            asyncio_run(ping_job("test-job-1"))

        assert ctx["set_setting_mock"].call_count == 1
        args = ctx["set_setting_mock"].call_args
        assert args[0][0] == "podping.last"
        result = json.loads(args[0][1])
        assert result["status"] == 404


# ---------------------------------------------------------------------------
# Tests: never raises
# ---------------------------------------------------------------------------


class TestNeverRaises:
    def test_no_exception_on_disabled(self, mock_httpx):
        scenario = {
            "podping.enabled": "0",
            "podping.token": "tkn",
            "privacy.mode": "",
            "address.public": "https://example.org",
        }
        with _settings_patch(scenario):
            job = _make_job()
            store = _mock_store(job)
            with patch("vozonda_api.podping.JobStore", return_value=store):
                asyncio_run(ping_job("test-job-1"))

    def test_no_exception_on_connection_error(self, mock_httpx):
        scenario = {
            "podping.enabled": "1",
            "podping.token": "tkn",
            "privacy.mode": "",
            "address.public": "https://example.org",
        }
        mock_client, _ = _setup_http_mock(mock_httpx, 200)
        mock_client.get = AsyncMock(side_effect=httpx.ConnectError("nope"))

        job = _make_job()
        store = _mock_store(job)

        with _settings_patch(scenario), \
                _configured_base_patch("https://example.org"), \
                _public_checker_patch(True), \
                patch("vozonda_api.podping.JobStore", return_value=store):
            asyncio_run(ping_job("test-job-1"))


# ---------------------------------------------------------------------------
# Tests: GET /settings mask
# ---------------------------------------------------------------------------


class TestSettingsMask:
    def test_token_masked(self):
        from vozonda_api.settings_store import SECRET_SETTINGS, public_settings

        assert "podping.token" in SECRET_SETTINGS

        with patch("vozonda_api.settings_store.all_settings", return_value={
            "podping.token": "secret-token-value",
            "llm.api_key": "llm-secret",
        }):
            settings = public_settings()
            assert settings["podping.token"] == "********"
            assert settings["llm.api_key"] == "********"


# ---------------------------------------------------------------------------
# Test utility
# ---------------------------------------------------------------------------

def asyncio_run(coro):
    import asyncio
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()
