"""Agent-readable API docs: llms.txt, OpenAPI summaries, JobIn schema."""

import pathlib
import re

import pytest
from fastapi.testclient import TestClient

from vozonda_api import mcp_server
from vozonda_api.main import JobIn, app


@pytest.fixture
def client(monkeypatch):
    for var in ("VOZONDA_TOKEN", "VOZONDA_ENABLE_BILLING", "VOZONDA_HOST"):
        monkeypatch.delenv(var, raising=False)
    return TestClient(app)


@pytest.fixture
def schema():
    return app.openapi()


# ---------------------------------------------------------------------------
# /llms.txt
# ---------------------------------------------------------------------------


def test_llms_txt_returns_200_text_plain(client):
    r = client.get("/llms.txt")
    assert r.status_code == 200
    assert "text/plain" in r.headers["content-type"]


def test_llms_txt_mentions_post_jobs_and_target_minutes(client):
    body = client.get("/llms.txt").text
    assert "POST /jobs" in body
    assert "target_minutes" in body


def test_llms_txt_mentions_polling_and_audio(client):
    body = client.get("/llms.txt").text
    assert "/jobs/{" in body
    assert "/audio/" in body


def test_llms_txt_mentions_billing_402(client):
    body = client.get("/llms.txt").text
    assert "402" in body


def test_llms_txt_mentions_rss_feed(client):
    body = client.get("/llms.txt").text
    assert "feed.xml" in body


def test_llms_txt_mentions_review_script(client):
    body = client.get("/llms.txt").text
    assert "review_script" in body


def test_llms_txt_mentions_openapi_json(client):
    body = client.get("/llms.txt").text
    assert "openapi.json" in body


def test_llms_txt_mentions_mcp_server_and_tools(client):
    body = client.get("/llms.txt").text
    assert "mcp_server" in body
    assert "#agents" in body

    tools = mcp_server.mcp._tool_manager.list_tools()
    tool_names = [t.name for t in tools]
    assert len(tool_names) >= 5, "mcp_server should register at least 5 tools"
    for name in tool_names:
        fn = getattr(mcp_server, name, None)
        assert fn is not None and callable(fn), f"mcp_server missing tool function {name}"
        assert name in body, f"Tool {name!r} not mentioned in /llms.txt"


# ---------------------------------------------------------------------------
# OpenAPI schema: summary + description on key routes
# ---------------------------------------------------------------------------


def _ops(sch):
    """Return {path: {method: op}} from the OpenAPI schema."""
    return {
        path: {m.lower(): ops for m, ops in path_ops.items() if ops}
        for path, path_ops in sch.get("paths", {}).items()
    }


def test_openapi_has_summary_and_description_post_jobs(schema):
    ops = _ops(schema)
    post = ops["/jobs"]["post"]
    assert post.get("summary")
    assert post.get("description")


def test_openapi_has_summary_and_description_get_job(schema):
    ops = _ops(schema)
    get = ops["/jobs/{job_id}"]["get"]
    assert get.get("summary")
    assert get.get("description")


def test_openapi_has_summary_and_description_get_jobs(schema):
    ops = _ops(schema)
    get = ops["/jobs"]["get"]
    assert get.get("summary")
    assert get.get("description")


def test_openapi_has_summary_and_description_get_audio(schema):
    ops = _ops(schema)
    # FastAPI normalizes {filename:path} to {filename} in the OpenAPI schema
    audio_ops = ops.get("/audio/{filename}.mp3", {})
    get = audio_ops.get("get") or audio_ops.get("head")
    assert get.get("summary")
    assert get.get("description")


def test_openapi_has_summary_and_description_get_meta(schema):
    ops = _ops(schema)
    get = ops["/meta"]["get"]
    assert get.get("summary")
    assert get.get("description")


# ---------------------------------------------------------------------------
# JobIn schema: all properties have descriptions
# ---------------------------------------------------------------------------


def _schema_props():
    """Return {prop: schema} from the JobIn JSON schema."""
    ref = JobIn.model_json_schema()
    defs = ref.get("$defs", {})
    jobin = defs.get("JobIn", ref)
    return jobin.get("properties", {})


def test_jobin_properties_all_have_descriptions():
    props = _schema_props()
    missing = [k for k, v in props.items() if not v.get("description")]
    assert not missing, f"Missing description on: {missing}"


def test_jobin_schema_has_example():
    extra = JobIn.model_config.get("json_schema_extra", {})
    assert extra.get("example"), "JobIn model_config json_schema_extra must include an example"


def test_jobin_example_contains_expected_fields():
    extra = JobIn.model_config.get("json_schema_extra", {})
    ex = extra.get("example", {})
    assert "url" in ex, "example must include 'url'"
    assert "style" in ex, "example must include 'style'"


# ---------------------------------------------------------------------------
# /llms.txt does not appear in the OpenAPI schema (include_in_schema=False)
# ---------------------------------------------------------------------------


def test_llms_txt_not_in_schema(schema):
    assert "/llms.txt" not in schema.get("paths", {})


# ---------------------------------------------------------------------------
# Trailing newline and state list (review F-2 / F-3)
# ---------------------------------------------------------------------------


def test_llms_txt_ends_with_newline():
    llms_path = pathlib.Path(__file__).resolve().parent.parent / "src" / "vozonda_api" / "llms.txt"
    text = llms_path.read_text(encoding="utf-8")
    assert text.endswith("\n"), "llms.txt must end with a POSIX newline"


def test_llms_txt_states_match_code():
    """llms.txt state list must match states actually written by the code."""
    llms_path = pathlib.Path(__file__).resolve().parent.parent / "src" / "vozonda_api" / "llms.txt"
    text = llms_path.read_text(encoding="utf-8")

    # States the code actually writes via state= in jobs/pipeline/main
    code_states = {"queued", "running", "done", "failed", "cancelled", "awaiting_review"}

    # Extract backtick-quoted tokens from the "States:" line only
    match = re.search(r"States: *(.+?)\.", text)
    assert match, "llms.txt must contain a 'States:' line"
    doc_states = set(re.findall(r"`(\w+)`", match.group(1)))

    missing_in_doc = code_states - doc_states
    extra_in_doc = doc_states - code_states - {"fetch", "script", "voice", "master"}
    assert not missing_in_doc, f"States in code but not in llms.txt: {missing_in_doc}"
    assert not extra_in_doc, f"States in llms.txt but not in code: {extra_in_doc}"


def test_openapi_get_job_description_includes_all_states(schema):
    """OpenAPI GET /jobs/{job_id} description must list every code state."""
    desc = schema["paths"]["/jobs/{job_id}"]["get"].get("description", "")
    # Normal flow states listed in the description
    flow_states = {"queued", "running", "fetch", "script", "voice", "master", "done", "failed"}
    for state in flow_states:
        assert state in desc, f"State {state!r} missing from OpenAPI description"