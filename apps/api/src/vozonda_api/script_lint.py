"""Deterministic quality lint for generated dialogue scripts.

Warn-only by design: per the KB Goodhart caveat we never auto-rewrite or
block a job on these signals, we surface them so a human can listen with
context. Metrics follow the sovereign-kb stylometry guidance:
turn-length variance and reactivity matter more than word lists.
"""

import re
import statistics
import unicodedata

# adapted from sovereign-kb mistral-overuse-phrases + stylometry addendum
SLOP_PHRASES = [
    "fascinating",
    "great question",
    "let's dive",
    "it's worth noting",
    "at the end of the day",
    "when it comes to",
    "the key takeaway",
    "that's a great point",
    "i couldn't agree more",
    "essentially",
    "fundamentally",
    "ultimately",
    "notably",
    "interestingly",
    "crucially",
    "remarkably",
]

_REACTIVE = re.compile(
    r"\b(you|your|wait|exactly|hmm+|right|no no|hold on|that's what|"
    r"see,|so the|okay but)\b",
    re.IGNORECASE,
)
_EXACTLY_OPENER = re.compile(r"^exactly\b", re.IGNORECASE)


def lint_script(lines: list[dict]) -> dict:
    texts = [str(ln.get("text", "")).strip() for ln in lines]
    lens = [len(t.split()) for t in texts if t]
    joined = " ".join(texts).lower()

    turns_count = len(lens)
    words_count = sum(lens)
    len_stdev = round(statistics.stdev(lens), 1) if len(lens) > 2 else 0.0
    len_min = min(lens) if lens else 0
    len_max = max(lens) if lens else 0
    short_turns = sum(1 for l in lens if l <= 6)
    overlong_turns = sum(1 for l in lens if l > 45)
    reactive_turns = sum(1 for t in texts if _REACTIVE.search(t))
    em_dashes = sum(t.count("\u2014") + t.count("\u2013") for t in texts)
    exactly_openers = sum(1 for t in texts if _EXACTLY_OPENER.match(t))
    slop_hits = {p: joined.count(p) for p in SLOP_PHRASES if p in joined}

    stats = {
        "turns": turns_count,
        "words": words_count,
        "len_stdev": len_stdev,
        "len_min": len_min,
        "len_max": len_max,
        "short_turns": short_turns,
        "overlong_turns": overlong_turns,
        "reactive_turns": reactive_turns,
        "em_dashes": em_dashes,
        "exactly_openers": exactly_openers,
        "slop_hits": slop_hits,
    }

    warnings: list[str] = []
    n = turns_count or 1
    if len_stdev < 7:
        warnings.append(f"turn lengths too uniform (stdev {len_stdev}, want >7)")
    if reactive_turns / n < 0.5:
        warnings.append(f"only {reactive_turns}/{n} turns reference the other speaker")
    if short_turns < 3:
        warnings.append(f"only {short_turns} sub-6-word reactions (want >=3)")
    if overlong_turns:
        warnings.append(f"{overlong_turns} turns exceed 45 words")
    if em_dashes:
        warnings.append(f"{em_dashes} dash characters in spoken text")
    if exactly_openers > 4:
        warnings.append(f"'exactly' opens {exactly_openers} turns (max 4)")
    slop_total = sum(slop_hits.values())
    if slop_total > 3:
        warnings.append(f"{slop_total} slop phrase hits: {slop_hits}")

    return {"stats": stats, "warnings": warnings}


_TRANSITION_RE = re.compile(
    r"\b(next up|coming up|now|moving on|turning to|our next story|next we|that brings us)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Hallucination-Guard & Source-Grounded Insights (DUE-077 / #262)
# ---------------------------------------------------------------------------

FACTUALITY_THRESHOLD = 0.85

_FILLER_RE = re.compile(
    r"\b(this article|the article|the author states|the author|"
    r"the text (says|states|discusses)|this paper|according to the article|"
    r"the study (shows|states)|discusses how|talks about)\b",
    re.IGNORECASE,
)

# maps curly typography to ascii for verbatim matching
_QUOTE_NORM_TABLE = str.maketrans({
    "\u2018": "'",
    "\u2019": "'",
    "\u201c": '"',
    "\u201d": '"',
    "\u2014": "-",
    "\u2013": "-",
    "\u2026": "...",
    "\u00a0": " ",
})


def normalize_for_match(s: str) -> str:
    """Normalize for verbatim quote matching: NFKC, lower, strip typography, collapse ws."""
    if not s:
        return ""
    t = unicodedata.normalize("NFKC", s)
    t = t.translate(_QUOTE_NORM_TABLE)
    t = t.lower()
    t = re.sub(r"\s+", " ", t).strip()
    return t


def verify_quote_exists(quote: str, source: str) -> bool:
    """Return True iff normalized quote is a substring of normalized source.

    Quotes shorter than 10 chars are considered unreliable and return False.
    """
    if not quote or not source:
        return False
    q = normalize_for_match(quote)
    if len(q) < 10:
        return False
    s = normalize_for_match(source)
    return q in s


def calculate_factuality_score(takeaways: list[dict], source_text: str) -> float:
    """Factuality score = verified_quotes / total (0.0-1.0). Empty list => 0.0."""
    if not takeaways:
        return 0.0
    verified = sum(1 for tk in takeaways if verify_quote_exists(str(tk.get("source_quote", "")), source_text))
    return round(verified / len(takeaways), 3)


def _lint_single_takeaway(tk: dict, source_text: str) -> list[str]:
    w: list[str] = []
    title = str(tk.get("title", "")).strip()
    text = str(tk.get("text", "")).strip()
    quote = str(tk.get("source_quote", "")).strip()

    if not title:
        w.append("takeaway missing title")
    elif len(title.split()) > 10:
        w.append(f"takeaway title too long ({len(title.split())} words, want <=10): {title[:40]}")
    if not text:
        w.append("takeaway missing text")
    else:
        wc = len(text.split())
        if wc > 45:
            w.append(f"takeaway text too long ({wc} words, want <=45)")
        if wc < 6:
            w.append(f"takeaway text too short ({wc} words)")
        if _FILLER_RE.search(text):
            w.append(f"takeaway contains filler meta-language: {text[:60]}")
        if _FILLER_RE.search(title):
            w.append(f"takeaway title contains filler meta-language: {title[:40]}")

    if not quote:
        w.append("takeaway missing source_quote")
    else:
        if len(quote) < 15:
            w.append(f"source_quote too short ({len(quote)} chars, want >=15)")
        if len(quote) > 400:
            w.append(f"source_quote too long ({len(quote)} chars, want <=400)")
        if not verify_quote_exists(quote, source_text):
            w.append(f"source_quote not found verbatim in source: {quote[:80]}")

    return w


def lint_takeaways(
    takeaways: list[dict],
    source_text: str,
) -> dict:
    """Hallucination-Guard validator for Blinkist-grade key takeaways.

    Returns dict with factuality_score, warnings, verified/total counts, and per-item details.
    Warn-only; does not raise. Threshold check is FACTUALITY_THRESHOLD = 0.85.
    """
    warnings: list[str] = []
    total = len(takeaways) if isinstance(takeaways, list) else 0
    if total == 0:
        return {
            "factuality_score": 0.0,
            "verified": 0,
            "total": 0,
            "threshold": FACTUALITY_THRESHOLD,
            "passed": False,
            "warnings": ["no takeaways to validate"],
            "details": [],
        }

    details: list[dict] = []
    verified = 0
    for idx, tk in enumerate(takeaways):
        item_warnings = _lint_single_takeaway(tk if isinstance(tk, dict) else {}, source_text)
        is_verified = verify_quote_exists(str(tk.get("source_quote", "")), source_text) if isinstance(tk, dict) else False
        if is_verified:
            verified += 1
        # filter quote-not-found warnings already in item_warnings
        details.append({
            "index": idx,
            "id": str(tk.get("id", f"t{idx+1}")) if isinstance(tk, dict) else f"t{idx+1}",
            "verified": is_verified,
            "warnings": item_warnings,
        })
        warnings.extend([f"[t{idx+1}] {x}" for x in item_warnings])

    factuality_score = round(verified / total, 3) if total else 0.0
    passed = factuality_score >= FACTUALITY_THRESHOLD
    if not passed:
        warnings.insert(0, f"factuality_score {factuality_score} below threshold {FACTUALITY_THRESHOLD} ({verified}/{total} verified)")

    # overall density check: takeaways should be 3-5 for Blinkist-grade
    if total < 3:
        warnings.append(f"only {total} takeaways (want 3-5 for density)")
    if total > 5:
        warnings.append(f"{total} takeaways (want 3-5, too many dilutes density)")

    return {
        "factuality_score": factuality_score,
        "verified": verified,
        "total": total,
        "threshold": FACTUALITY_THRESHOLD,
        "passed": passed,
        "warnings": warnings,
        "details": details,
    }


def lint_executive_summary(
    summary: str,
    source_quote: str | None,
    source_text: str,
) -> dict:
    """Validate executive summary grounding and density."""
    warnings: list[str] = []
    txt = (summary or "").strip()
    if not txt:
        warnings.append("executive_summary missing or empty")
        return {"factuality_score": 0.0, "verified": False, "warnings": warnings, "passed": False}
    wc = len(txt.split())
    if wc > 50:
        warnings.append(f"executive_summary too long ({wc} words, want <=50)")
    if wc < 8:
        warnings.append(f"executive_summary too short ({wc} words, want >=8)")
    if _FILLER_RE.search(txt):
        warnings.append(f"executive_summary contains filler meta-language: {txt[:60]}")

    verified = False
    if source_quote:
        verified = verify_quote_exists(source_quote, source_text)
        if not verified:
            warnings.append(f"executive source_quote not found verbatim: {source_quote[:80]}")
        if len(source_quote.strip()) < 15:
            warnings.append("executive source_quote too short")
    # pass if either no quote required but no filler, or quote verified
    passed = len(warnings) == 0 or (source_quote is not None and verified and not any("filler" in x for x in warnings))
    # factuality for exec is 1.0 if verified else 0.5 if no filler else 0
    score = 1.0 if verified else (0.7 if not warnings else 0.0)
    if source_quote is None:
        score = 0.7 if not warnings else 0.0
        passed = len(warnings) == 0
    return {"factuality_score": score, "verified": verified, "warnings": warnings, "passed": passed}


def lint_insights(
    executive_summary: str | None,
    executive_quote: str | None,
    takeaways: list[dict],
    source_text: str,
) -> dict:
    """Top-level insights lint combining summary + takeaways."""
    tk_result = lint_takeaways(takeaways, source_text)
    exec_result = lint_executive_summary(executive_summary or "", executive_quote, source_text)
    all_warnings: list[str] = []
    if exec_result["warnings"]:
        all_warnings.extend([f"[exec] {w}" for w in exec_result["warnings"]])
    if tk_result["warnings"]:
        all_warnings.extend(tk_result["warnings"])
    # overall factuality is the takeaways score (primary gate)
    overall_passed = tk_result["passed"] and exec_result["passed"]
    return {
        "executive": exec_result,
        "takeaways": tk_result,
        "factuality_score": tk_result["factuality_score"],
        "passed": overall_passed,
        "warnings": all_warnings,
        "threshold": FACTUALITY_THRESHOLD,
    }


def lint_digest_script(
    lines: list[dict],
    sections: list[dict],
) -> dict:
    """Digest-specific lint checks (run in addition to standard lint_script).

    sections: list of {"index": int, "title": str, "url": str, "body": str}

    Checks:
    - Transition count: expect n_sections - 1 transitions
    - Per-section turn count: warn if any section is very thin (<3 turns estimated)
    - Total words vs digest budget
    """
    warnings: list[str] = []
    n_sections = len(sections)
    texts = [str(ln.get("text", "")).strip() for ln in lines]
    n_turns = len(texts)

    # Transition check: count turns with transition language
    transition_count = sum(1 for t in texts if _TRANSITION_RE.search(t))
    expected_transitions = max(0, n_sections - 1)
    if transition_count < expected_transitions:
        warnings.append(
            f"found {transition_count} transition turns, expected {expected_transitions} "
            f"(one per story boundary)"
        )

    # Total word count vs budget
    total_words = sum(len(t.split()) for t in texts if t)
    _targets: dict[int, int] = {2: 800, 3: 1200, 4: 1500}
    target = _targets.get(n_sections, 1800)
    if total_words < target * 0.5:
        warnings.append(
            f"digest only {total_words} words, target is {target} "
            f"(below 50% of budget)"
        )

    # Estimated turns per section: if script is short, sections are too thin
    if n_sections > 0 and n_turns > 0:
        avg_turns_per_section = n_turns / n_sections
        if avg_turns_per_section < 3:
            warnings.append(
                f"avg {avg_turns_per_section:.1f} turns per section (want >= 3)"
            )

    return {"warnings": warnings, "sections": n_sections, "transitions": transition_count, "total_words": total_words}
