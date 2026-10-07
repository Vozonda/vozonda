"""Script calls to the local LLM run with thinking off: Qwen3.6's thinking shares
max_tokens with the answer and cut a 1280-word script to 86 words (bench s1)."""

from vozonda_api.providers.script import with_thinking_off


def test_local_llm_gets_thinking_off():
    for base in ("http://127.0.0.1:30001/v1", "http://localhost:30001/v1"):
        assert with_thinking_off({}, base)["chat_template_kwargs"] == {"enable_thinking": False}


def test_hosted_apis_do_not_get_the_unknown_field():
    for base in ("https://api.mistral.ai/v1", "https://api.ppq.ai/v1", "https://integrate.api.nvidia.com/v1"):
        assert "chat_template_kwargs" not in with_thinking_off({}, base)
