"""Script provider - LLM dialogue script generation via streaming JSON lines.

One provider per file contract. This module talks to any OpenAI-compatible
chat endpoint (vLLM, Anthropic, any OAI-proxy) and streams the response as
JSON lines, extracting the first JSON array from the accumulated content.

Usage from pipeline (after nemo wires it into _script()):
    from .providers.script import script_call

    lines, description = await script_call(
        prompt=full_prompt,
        model="qwen3.6-35b",
        base="http://127.0.0.1:30001/v1",
        key="",
        max_tokens=8192,
    )
"""

import json
import re
from typing import Any

import httpx

from ..plugins.types import Permission, PluginKind, PluginMeta

META = PluginMeta(
    id="script_llm",
    kind=PluginKind.SCRIPT_ENGINE,
    label="OpenAI-compatible / Anthropic LLM script generator",
    permissions=frozenset({Permission.NETWORK}),
    ui_badge="streaming JSON",
)


def _is_local_llm(base: str) -> bool:
    """True for an LLM on this machine (the vLLM qwen on :30001 and friends)."""
    host = re.sub(r"^[a-z]+://", "", base or "").split("/")[0].split(":")[0].lower()
    return host in ("127.0.0.1", "localhost", "0.0.0.0", "::1", "host.docker.internal")


def with_thinking_off(payload: dict, base: str) -> dict:
    """Turn the local model's thinking off for script writing.

    Qwen3.6 thinks first and thinking shares max_tokens with the answer: on
    2026-09-23 a script planned at 1280 words arrived as 86 (bench s1, cut
    mid-sentence, then 'repaired' into a 45 s episode). Writing a script is
    not a reasoning task. Only sent to a local server; hosted APIs may reject
    the unknown field.
    """
    if _is_local_llm(base):
        payload["chat_template_kwargs"] = {"enable_thinking": False}
    return payload


def _repair_json(s: str) -> str | None:
    """Attempt to repair truncated/incomplete JSON output from LLM token cutoff.

    When Qwen3.6 exhausts its token budget (max_tokens shared between
    thinking and output), the JSON array arrives truncated:
      - Unclosed brackets:  [{"a":1   -> [{"a":1}]
      - Unclosed braces:    [{"a":1   -> [{"a":1}]
      - Unclosed strings:    [{"a":"foo  -> [{"a":"foo"}]
      - Trailing commas:   [{"a":1,}   -> [{"a":1}]

    Returns the repaired string on success, None if repair is hopeless.
    """
    # Remove trailing whitespace
    s = s.strip()

    # Fix trailing commas before ] or }
    s = re.sub(r",\s*([}\]])", r"\1", s)

    # Balance brackets by tracking depth
    stack: list[str] = []
    in_string = False
    escape = False
    i = 0
    while i < len(s):
        ch = s[i]
        if escape:
            escape = False
            i += 1
            continue
        if ch == "\\" and in_string:
            escape = True
            i += 1
            continue
        if ch == '"':
            in_string = not in_string
        elif not in_string:
            if ch in ("{", "["):
                stack.append(ch)
            elif ch == "}":
                if stack and stack[-1] == "{":
                    stack.pop()
                else:
                    return None  # unbalanced in a way we can't fix
            elif ch == "]":
                if stack and stack[-1] == "[":
                    stack.pop()
                else:
                    return None
        i += 1

    # If we're inside an unclosed string, close it with content intact
    # Everything after the opening quote of this string is content — just close it
    if in_string:
        for ci in range(len(s) - 1, -1, -1):
            if s[ci] == '"':
                # ci is the position of the opening quote of the unclosed string.
                # Everything from ci+1 to end is string content.
                # Close: append quote + close remaining brackets in LIFO order.
                closings = "".join("]" if ch == "[" else "}" for ch in reversed(stack))
                s = s + '"' + closings
                return s
        return None

    # Close any unclosed brackets in reverse order (stack is LIFO — last opened first)
    while stack:
        open_ch = stack.pop()
        if open_ch == "{":
            s += "}"
        elif open_ch == "[":
            s += "]"

    return s


_SENTENCE_END_CHARS = (".", "!", "?", "…", '"', "'", "”", "’", ")")


def _drop_cut_off_tail(items: list) -> list:
    """A repaired (truncated) answer ends in a half-written turn: drop it.

    2026-10-02: the LLM crashed mid-stream, the repair closed the half JSON and a script
    ending in 'Lightning moves transactions off-chain for' was voiced. Only repaired
    answers are touched; a complete answer keeps its last turn whatever it ends with."""
    if items and isinstance(items[-1], dict):
        text = str(items[-1].get("text", "")).rstrip()
        if not text.endswith(_SENTENCE_END_CHARS):
            return items[:-1]
    return items


def _parse_first_json_array(content: str) -> tuple[list[dict[str, Any]], int]:
    """Parse the FIRST valid JSON array in content.

    Returns (parsed_list, end_offset_in_content). Trailing data is
    tolerated on purpose: digest scripts append a CHAPTERS json block
    after the script array (sonnet's #122 design), which the old greedy
    regex swallowed and then died on with json 'Extra data'.

    If raw_decode fails (truncated output from token cutoff), attempts
    to repair the JSON by closing unclosed brackets/braces/strings.
    """
    bracket_positions = [i for i, ch in enumerate(content) if ch == "["]
    if not bracket_positions:
        raise ValueError("no JSON array in output")

    for start in bracket_positions:
        try:
            raw, end = json.JSONDecoder().raw_decode(content[start:])
            if isinstance(raw, list) and (not raw or isinstance(raw[0], dict)):
                return raw, start + end
        except json.JSONDecodeError:
            pass

    for start in bracket_positions:
        repaired = _repair_json(content[start:])
        if repaired is not None:
            try:
                raw, end = json.JSONDecoder().raw_decode(repaired)
                if isinstance(raw, list) and (not raw or isinstance(raw[0], dict)):
                    return _drop_cut_off_tail(raw), start + end
            except json.JSONDecodeError:
                pass

    raise ValueError("no JSON array in output")


async def script_call(
    *,
    prompt: str,
    model: str = "qwen3.6-35b",
    base: str = "http://127.0.0.1:30001/v1",
    key: str = "",
    max_tokens: int = 16384,
    temperature: float = 0.7,
    timeout: float = 600.0,
) -> tuple[list[dict[str, Any]], str]:
    """Call an LLM for script generation with streaming JSON lines.

    Default max_tokens=16384 to reserve headroom for Qwen3.6 reasoning tokens.

    Returns (lines, description) where lines is the JSON array of turns
    and description is the DESCRIPTION: line extracted from the tail.
    """
    from . import OPENCODE_BASE

    if base == OPENCODE_BASE:
        return _parse_script_content(await opencode_run(model, prompt, timeout=timeout))

    is_anthropic = "api.anthropic.com" in base
    if is_anthropic and base.endswith("/v1"):
        base = base[: -len("/v1")]

    content = ""
    async with httpx.AsyncClient(timeout=timeout) as c:
        if is_anthropic:
            payload = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
            url = f"{base}/v1/messages"
        else:
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
                "stream": True,
            }
            with_thinking_off(payload, base)
            headers = {}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            url = f"{base}/chat/completions"

        async with c.stream("POST", url, json=payload, headers=headers) as r:
            r.raise_for_status()
            # aiter_lines yields decoded str; calling .decode on it blew up
            # on the very first live request (bitcoin-0815, 2026-08-25)
            async for raw in r.aiter_lines():
                raw = raw.strip()
                if not raw:
                    continue
                # OpenAI streaming format: "data: {...}"
                if raw.startswith("data: "):
                    payload_str = raw[6:].strip()
                    if payload_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload_str)
                    except json.JSONDecodeError:
                        continue
                    # Extract delta content from streaming chunk
                    if is_anthropic:
                        delta = chunk.get("delta", {})
                        text = delta.get("text", "")
                        if text:
                            content += text
                    else:
                        choices = chunk.get("choices")
                        if choices:
                            delta = choices[0].get("delta", {})
                            text = delta.get("content", "")
                            if text:
                                content += text
                elif raw.startswith("data:"):
                    # Some proxies send "data:{...}" without space
                    payload_str = raw[5:].strip()
                    if payload_str == "[DONE]":
                        break
                    try:
                        chunk = json.loads(payload_str)
                    except json.JSONDecodeError:
                        continue
                    choices = chunk.get("choices")
                    if choices:
                        delta = choices[0].get("delta", {})
                        text = delta.get("content", "")
                        if text:
                            content += text

    return _parse_script_content(content)


def _parse_script_content(content: str) -> tuple[list[dict[str, Any]], str]:
    # Strip thinking tags if present
    content = re.sub(r"<(?:think|thinking)>[\s\S]*?(?:</(?:think|thinking)>|$)", "", content).strip()

    raw, array_end = _parse_first_json_array(content)

    # Extract DESCRIPTION line from tail (digest scripts append
    # CHAPTERS json here too, both must not break the array parse)
    tail = content[array_end:]
    dm = re.search(r"DESCRIPTION:\s*(.+)", tail)
    description = (dm.group(1).strip().strip('"') if dm else "")[:280]

    return raw, description


_ANSI = re.compile(r"\x1b\[[0-9;]*m")
_CLI_HEADER = re.compile(r"^> \S+ · .*$", re.MULTILINE)


async def opencode_run(model: str, prompt: str, timeout: float = 900.0) -> str:
    """Run one prompt through the local opencode CLI and return the answer text.

    The prompt goes in as an attached file (it can be 30 KB) and runs with the
    read-only plan agent in an empty directory, so the agent has nothing to edit.
    """
    import asyncio
    import tempfile
    from pathlib import Path

    from . import opencode_bin

    exe = opencode_bin()
    if not exe:
        raise RuntimeError("opencode CLI not found (install it or set VOZONDA_OPENCODE_BIN)")
    with tempfile.TemporaryDirectory(prefix="vozonda-opencode-") as d:
        prompt_file = Path(d) / "prompt.txt"
        prompt_file.write_text(prompt)
        proc = await asyncio.create_subprocess_exec(
            exe, "run", "-m", model, "--agent", "plan",
            "Follow the instructions in the attached file exactly. Answer with the requested output only.",
            "-f", str(prompt_file),
            cwd=d, stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
        try:
            out, err = await asyncio.wait_for(proc.communicate(), timeout=timeout)
        except TimeoutError:
            proc.kill()
            await proc.wait()
            raise RuntimeError(f"opencode {model} timed out after {timeout:.0f} s") from None
    if proc.returncode != 0:
        raise RuntimeError(f"opencode {model} exited {proc.returncode}: {err.decode(errors='ignore')[-300:]}")
    text = _CLI_HEADER.sub("", _ANSI.sub("", out.decode(errors="ignore"))).strip()
    if not text:
        raise RuntimeError(f"opencode {model} returned no text")
    return text


async def script_call_nonstreaming(
    *,
    prompt: str,
    model: str = "qwen3.6-35b",
    base: str = "http://127.0.0.1:30001/v1",
    key: str = "",
    max_tokens: int = 16384,
    temperature: float = 0.7,
    timeout: float = 600.0,
) -> tuple[list[dict[str, Any]], str]:
    """Non-streaming fallback - same contract, single-shot response.

    Default max_tokens=16384 to reserve headroom for Qwen3.6 reasoning tokens.
    """
    is_anthropic = "api.anthropic.com" in base
    if is_anthropic and base.endswith("/v1"):
        base = base[: -len("/v1")]

    async with httpx.AsyncClient(timeout=timeout) as c:
        if is_anthropic:
            payload = {
                "model": model,
                "max_tokens": max_tokens,
                "messages": [{"role": "user", "content": prompt}],
            }
            headers = {"x-api-key": key, "anthropic-version": "2023-06-01"}
            url = f"{base}/v1/messages"
        else:
            payload = {
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "temperature": temperature,
                "max_tokens": max_tokens,
            }
            with_thinking_off(payload, base)
            headers = {}
            if key:
                headers["Authorization"] = f"Bearer {key}"
            url = f"{base}/chat/completions"

        r = await c.post(url, json=payload, headers=headers)
        r.raise_for_status()
        data = r.json()
        if is_anthropic:
            content = data["content"][0]["text"]
        else:
            content = data["choices"][0]["message"]["content"]

    content = re.sub(r"<(?:think|thinking)>[\s\S]*?(?:</(?:think|thinking)>|$)", "", content).strip()

    raw, array_end = _parse_first_json_array(content)

    tail = content[array_end:]
    dm = re.search(r"DESCRIPTION:\s*(.+)", tail)
    description = (dm.group(1).strip().strip('"') if dm else "")[:280]

    return raw, description
