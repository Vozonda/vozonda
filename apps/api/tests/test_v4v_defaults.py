"""VOZONDA-V4V: no hardcoded operator payout address; zap block is opt-in."""

import pytest
from fastapi.testclient import TestClient

from vozonda_api import jobs as jobs_mod
from vozonda_api import main as main_mod
from vozonda_api import settings_store as ss


@pytest.fixture()
def client(tmp_path, monkeypatch: pytest.MonkeyPatch) -> TestClient:
    db = tmp_path / "vozonda-test.db"
    monkeypatch.setattr(jobs_mod, "DB_PATH", db)
    monkeypatch.setattr(ss, "DB_PATH", db)
    jobs_mod.init_db()
    ss.ensure_table()
    return TestClient(main_mod.app)


def _make_done_job(job_id: str = "job-default", url: str = "https://example.com/article") -> None:
    main_mod.store.create(job_id, url, "balanced", "dialog", "neutral", "en", hosts=2)
    main_mod.store.update(job_id, state="done")


class TestSettingsDefaults:
    """The /settings endpoint must ship with an empty creator address."""

    def test_settings_defaults_empty_creator_address(self, client: TestClient) -> None:
        r = client.get("/settings")
        assert r.status_code == 200
        data = r.json()
        defaults = data.get("defaults", {})
        assert defaults.get("feed.creator.address") == ""

    def test_no_rizful_in_main(self) -> None:
        """Assert that main.py does not reference rizful.com."""
        import vozonda_api.main as m
        path = getattr(m, "__file__", "")
        if path:
            with open(path) as f:
                content = f.read()
            assert "rizful.com" not in content


class TestSharePageNoZap:
    """When no creator address is set, the share page must have no zap block."""

    def test_share_page_no_zap_row(self, client: TestClient) -> None:
        _make_done_job("job-nozap")
        r = client.get("/e/job-nozap")
        assert r.status_code == 200
        assert 'id="zap-row"' not in r.text

    def test_share_page_no_zap_modal(self, client: TestClient) -> None:
        _make_done_job("job-nozap2")
        r = client.get("/e/job-nozap2")
        assert r.status_code == 200
        assert 'id="zap-modal"' not in r.text

    def test_share_page_no_zap_addr_element(self, client: TestClient) -> None:
        _make_done_job("job-nozap3")
        r = client.get("/e/job-nozap3")
        assert r.status_code == 200
        assert 'id="zap-addr"' not in r.text


class TestSharePageWithZap:
    """When feed.creator.address is set, the share page must render the zap block."""

    def test_share_page_zap_when_address_set(self, client: TestClient) -> None:
        ss.set_setting("feed.creator.address", "alice@primal.net")
        _make_done_job("job-withzap")
        r = client.get("/e/job-withzap")
        assert r.status_code == 200
        body = r.text
        assert 'id="zap-row"' in body
        assert 'id="zap-modal"' in body
        assert 'id="zap-addr"' in body
        assert "alice@primal.net" in body

    def test_share_page_zap_footer_text(self, client: TestClient) -> None:
        ss.set_setting("feed.creator.address", "bob@lnaddress.io")
        _make_done_job("job-footer")
        r = client.get("/e/job-footer")
        assert r.status_code == 200
        # Footer line contains zap address
        assert "bob@lnaddress.io" in r.text

class TestProjectAppAddress:
    """The app's split goes to the open-source project unless the install says otherwise."""

    def test_default_is_the_project_address(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VOZONDA_NODE_V4V_ADDRESS", raising=False)
        monkeypatch.delenv("VOZONDA_APP_V4V_ADDRESS", raising=False)
        assert ss.get_setting("feed.app.address") == ss.PROJECT_V4V_ADDRESS == "vozonda@rizful.com"
        assert client.get("/settings").json()["settings"]["feed.app.address"] == "vozonda@rizful.com"

    def test_own_setting_wins(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.delenv("VOZONDA_NODE_V4V_ADDRESS", raising=False)
        monkeypatch.delenv("VOZONDA_APP_V4V_ADDRESS", raising=False)
        ss.set_setting("feed.app.address", "node@example.org")
        assert ss.get_setting("feed.app.address") == "node@example.org"

    def test_env_wins(self, client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setenv("VOZONDA_NODE_V4V_ADDRESS", "host@example.org")
        assert ss.get_setting("feed.app.address") == "host@example.org"
