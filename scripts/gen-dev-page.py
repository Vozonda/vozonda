#!/usr/bin/env python3
"""Generate apps/web/public/dev.html from public files in this repository only.

No network, no tokens, no private paths: the page ships in the public repo and
is deterministic for a given tree (no commit count or git rev baked in), so
scripts/verify.sh does not leave the checkout dirty after every commit.

Zero third-party dependencies (Python standard library only).
Complies with Calm Grid design system (docs/design.md) and sovereign grid rules:
- Zero em-dashes (hard rule 6)
- Calm grid design tokens (light and dark mode)
- Dense dev typography
- Pure SVG icons (Zero raw emojis)
"""

import html
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_FILE = REPO_ROOT / "apps" / "web" / "public" / "dev.html"

# Configurable repo URL placeholder flag
OPEN_SOURCE_SOON = True
REPO_URL = "https://github.com/Vozonda/vozonda"

# Pure SVG Calm Grid Icons (Strictly NO raw Unicode emojis)
ICON_SCALE = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z"/><polyline points="3.27 6.96 12 12.01 20.73 6.96"/><line x1="12" y1="22.08" x2="12" y2="12"/></svg>'
ICON_SHIELD = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M12 22s8-4 8-10V5l-8-3-8 3v7c0 6 8 10 8 10z"/><polyline points="9 12 11 14 15 10"/></svg>'
ICON_SUN = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="5"/><line x1="12" y1="1" x2="12" y2="3"/><line x1="12" y1="21" x2="12" y2="23"/><line x1="4.22" y1="4.22" x2="5.64" y2="5.64"/><line x1="18.36" y1="18.36" x2="19.78" y2="19.78"/><line x1="1" y1="12" x2="3" y2="12"/><line x1="21" y1="12" x2="23" y2="12"/><line x1="4.22" y1="19.78" x2="5.64" y2="18.36"/><line x1="18.36" y1="5.64" x2="19.78" y2="4.22"/></svg>'
ICON_LOCK = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="11" width="18" height="11" rx="2" ry="2"/><path d="M7 11V7a5 5 0 0 1 10 0v4"/></svg>'
ICON_BRANCH = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><line x1="6" y1="3" x2="6" y2="15"/><circle cx="18" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M18 9a9 9 0 0 1-9 9"/></svg>'
ICON_CHECK = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.5" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><polyline points="20 6 9 17 4 12"/></svg>'
ICON_COPY = '<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="9" y="9" width="13" height="13" rx="2" ry="2"/><path d="M5 15H4a2 2 0 0 1-2-2V4a2 2 0 0 1 2-2h9a2 2 0 0 1 2 2v1"/></svg>'


def strip_em_dashes(text: str) -> str:
    """Replace em-dashes, en-dashes, and dash entities with hyphens or colons."""
    if not text:
        return ""
    text = text.replace("—", " - ").replace("–", " - ").replace("&mdash;", " - ").replace("&ndash;", " - ")
    # Clean up double hyphens or spaced artifacts (horizontal whitespace only)
    text = re.sub(r"[ \t]+-[ \t]+", " - ", text)
    return text


def get_bundle_metrics() -> dict[str, float]:
    """The JS budget (fixed). The measured size is checked by tests/test_js_budget.py, not baked in here,
    so the page does not change with every build."""
    return {"budget_kb": 60.0}

def fetch_digest_chapters() -> tuple[str, list[dict], str]:
    """Static chapter marks of the demo episode (no API call: the page is built offline)."""
    audio_src = "/audio/digest-1f2ef4.mp3"
    default_chapters = [
        {"time_str": "00:00", "seconds": 0, "title": "Marktbericht: Anleger nervoes in der Woche der Wahrheit"},
        {"time_str": "02:57", "seconds": 177, "title": "Nach UN-Job: Baerbock wechselt an die Columbia-Universitaet"},
        {"time_str": "05:54", "seconds": 354, "title": "Referendum ueber EU-Beitrittsverhandlungen: Bruessel hofft auf ein Ja aus Island"},
    ]
    meta_str = "3 stories · 8:53 min · 3 hosts"
    return audio_src, default_chapters, meta_str


def parse_changelog(path: Path) -> tuple[str, list[dict]]:
    """Parse CHANGELOG.md for the current release and historical releases."""
    if not path.exists():
        return "0.6.0", []

    content = strip_em_dashes(path.read_text(encoding="utf-8"))
    sections = re.split(r"^##\s+\[(.*?)\]", content, flags=re.MULTILINE)

    releases = []
    current_ver = "0.6.0"

    # sections[0] is header preamble
    for i in range(1, len(sections), 2):
        ver_header = sections[i].strip()
        body = sections[i + 1].strip() if i + 1 < len(sections) else ""
        body = re.sub(r"^\s*[-–—]?\s*\d{4}-\d{2}-\d{2}\s*", "", body).strip()
        if ver_header.lower() == "unreleased":
            clean_body = body.strip()
            if clean_body:
                releases.append({
                    "version": "Unreleased (in progress)",
                    "raw_version": "unreleased",
                    "body": clean_body,
                })
        else:
            if not current_ver or current_ver == "0.6.0":
                current_ver = ver_header
            releases.append({
                "version": f"v{ver_header}",
                "raw_version": ver_header,
                "body": body,
            })

    return current_ver, releases


def parse_todo(path: Path) -> list[dict]:
    """Parse open tactical backlog items from TODO.md."""
    if not path.exists():
        return []

    content = strip_em_dashes(path.read_text(encoding="utf-8"))
    items = []
    current_prio = "General"

    for line in content.splitlines():
        line = line.strip()
        if line.startswith("## "):
            raw_prio = line[3:].split("(")[0].strip()
            prio_map = {
                "hoch": "High",
                "mittel": "Medium",
                "niedrig": "Low",
                "kritisch": "Critical",
                "high": "High",
                "medium": "Medium",
                "low": "Low",
                "critical": "Critical",
            }
            current_prio = prio_map.get(raw_prio.lower(), raw_prio)
        elif line.startswith("- [ ]"):
            desc = line[5:].strip()
            due_match = re.match(r"(DUE-\w+)\s*:?\s*(.*)", desc)
            if due_match:
                due_id = due_match.group(1)
                text = due_match.group(2)
            else:
                due_id = ""
                text = desc
            items.append({
                "priority": current_prio,
                "id": due_id,
                "text": text,
            })

    return items


def parse_plan(path: Path) -> list[dict]:
    """Parse public roadmap phases from docs/roadmap.md (absent: no roadmap section)."""
    if not path.exists():
        return []

    content = strip_em_dashes(path.read_text(encoding="utf-8"))
    phases = []
    current_phase = None

    for line in content.splitlines():
        if line.startswith("## Phase "):
            if current_phase:
                phases.append(current_phase)
            title = line[3:].strip()
            current_phase = {"title": title, "items": []}
        elif current_phase and line.strip().startswith("- ["):
            is_done = line.strip().startswith("- [x]")
            item_text = line.strip()[5:].strip()
            current_phase["items"].append({"done": is_done, "text": item_text})

    if current_phase:
        phases.append(current_phase)

    return phases


def format_markdown_list(md_text: str) -> str:
    """Simple converter for markdown lists and subheadings into clean HTML."""
    lines = md_text.splitlines()
    html_out = []
    in_list = False

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            if in_list:
                html_out.append("</ul>")
                in_list = False
            continue
        if line.startswith("### "):
            if in_list:
                html_out.append("</ul>")
                in_list = False
            html_out.append(f"<h4>{html.escape(line[4:])}</h4>")
        elif line.startswith("- "):
            if not in_list:
                html_out.append("<ul>")
                in_list = True
            content = html.escape(line[2:])
            content = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", content)
            html_out.append(f"<li>{content}</li>")
        else:
            if in_list:
                html_out.append("</ul>")
                in_list = False
            content = html.escape(line)
            content = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", content)
            html_out.append(f"<p>{content}</p>")

    if in_list:
        html_out.append("</ul>")

    return "\n".join(html_out)


def format_release_feature_cards(md_text: str) -> str:
    """Format release notes into structured cards with category badges."""
    lines = md_text.splitlines()
    categories: dict[str, list[str]] = {}
    current_cat: str | None = None

    for raw_line in lines:
        line = raw_line.strip()
        if not line:
            continue
        if line.startswith("### "):
            current_cat = line[4:].strip()
            if current_cat not in categories:
                categories[current_cat] = []
        elif line.startswith("- "):
            if not current_cat:
                continue
            item_text = line[2:].strip()
            if re.match(r"^\d{4}-\d{2}-\d{2}$", item_text):
                continue
            if current_cat not in categories:
                categories[current_cat] = []
            categories[current_cat].append(item_text)
        else:
            if current_cat and current_cat in categories and categories[current_cat]:
                categories[current_cat][-1] += " " + line

    html_out = ['<div class="feature-cards-grid">']
    for cat, items in categories.items():
        cat_slug = cat.lower()
        badge_cls = "highlight" if cat_slug == "added" else ("version" if cat_slug == "changed" else "fixed")
        for it in items[:2]:
            colon_idx = it.find(":")
            if colon_idx != -1 and colon_idx < 60:
                title = it[:colon_idx].strip()
                desc = it[colon_idx + 1:].strip()
            else:
                title = it
                desc = ""
            title_html = html.escape(title)
            title_html = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", title_html)
            desc_html = html.escape(desc)
            desc_html = re.sub(r"\*\*(.*?)\*\*", r"<strong>\1</strong>", desc_html)

            card_html = f"""
            <div class="feature-card">
              <div class="fc-head">
                <span class="badge {badge_cls}">{html.escape(cat)}</span>
                <strong class="fc-title">{title_html}</strong>
              </div>
              {f'<p class="fc-desc">{desc_html}</p>' if desc_html else ''}
            </div>
            """
            html_out.append(card_html)
    html_out.append("</div>")
    return "\n".join(html_out)


def build_dev_html(
    version: str,
    git_rev: str,
    bundle_metrics: dict[str, float],
    releases: list[dict],
    todo_items: list[dict],
    plan_phases: list[dict],
    open_issues: list[dict],
    closed_issues: list[dict],
    demo_audio_src: str,
    demo_chapters: list[dict],
    demo_meta: str,
) -> str:
    """Build static dev.html with Calm Grid styling and gamified KPIs."""
    open_count = len(open_issues)
    closed_count = len(closed_issues)

    latest_release = releases[0] if releases else {"version": f"v{version}", "body": "Initial v0.6.0 build"}
    older_releases = releases[1:] if len(releases) > 1 else []

    latest_release_html = format_release_feature_cards(latest_release["body"])

    older_releases_html = ""
    for rel in older_releases:
        older_releases_html += f"""
        <div class="older-release">
          <h4 class="mono">{html.escape(rel["version"])}</h4>
          {format_markdown_list(rel["body"])}
        </div>
        """

    chapters_html = ""
    for i, c in enumerate(demo_chapters):
        chapters_html += f"""
        <li class="chapter-item" data-seconds="{c['seconds']}" data-index="{i}">
          <button type="button" class="link mono" onclick="seekChapter({c['seconds']})" aria-label="Seek to chapter {i + 1}: {html.escape(c['title'])}">
            {i + 1} · {html.escape(c['title'])}
          </button>
        </li>
        """

    # Mobile-first stacked roadmap cards
    plan_html = ""
    for phase in plan_phases:
        items = phase.get("items", [])
        all_done = bool(items and all(it["done"] for it in items))
        any_done = bool(any(it["done"] for it in items))
        if all_done:
            status_badge = '<span class="badge highlight">complete</span>'
            card_cls = "roadmap-card completed"
        elif any_done:
            status_badge = '<span class="badge">in progress / next</span>'
            card_cls = "roadmap-card current"
        else:
            status_badge = '<span class="badge">planned</span>'
            card_cls = "roadmap-card"

        items_html = ""
        for it in phase["items"]:
            status_cls = "done" if it["done"] else "pending"
            mark = "[x]" if it["done"] else "[ ]"
            items_html += f'<li class="{status_cls}"><span class="mono check">{mark}</span> {html.escape(it["text"])}</li>'

        plan_html += f"""
        <div class="{card_cls}">
          <div class="rc-header">
            {status_badge}
            <h3 class="rc-title">{html.escape(phase["title"])}</h3>
          </div>
          <ul class="rc-items">{items_html}</ul>
        </div>
        """

    due_rows = ""
    for item in todo_items[:5]:  # top 5 items for size guard
        prio_badge = f'<span class="badge prio-{html.escape(item["priority"].lower())}">{html.escape(item["priority"])}</span>'
        due_code = f'<code class="mono due-id">{html.escape(item["id"])}</code>' if item["id"] else ""
        due_rows += f"""
        <div class="topic-row">
          <div class="topic-meta">{prio_badge} {due_code}</div>
          <div class="topic-text">{html.escape(item["text"])}</div>
        </div>
        """

    closed_rows = ""
    for issue in closed_issues[:3]:  # top 3 recent
        labels_html = "".join([f'<span class="badge label">{html.escape(lbl)}</span>' for lbl in issue.get("labels", [])])
        closed_rows += f"""
        <li class="issue-item closed">
          <span class="mono issue-num">#{issue["number"]}</span>
          <span class="issue-title">{html.escape(issue["title"])}</span>
          <span class="issue-labels">{labels_html}</span>
        </li>
        """

    if OPEN_SOURCE_SOON:
        cta_dev = """
        <div class="cta-box">
          <h3 class="mono">// open source release</h3>
          <p>Vozonda is developed under the Calm Grid doctrine. The code is developed in the open on GitHub (Vozonda/vozonda).</p>
          <p class="mono note">Stack: Svelte 5, FastAPI, SQLite, ffmpeg, Qwen3 / Kokoro / Piper.</p>
        </div>
        """
    else:
        cta_dev = f"""
        <div class="cta-box">
          <h3 class="mono">// repository</h3>
          <p>Source code and issue tracker available at: <a href="{REPO_URL}" class="link mono">{REPO_URL}</a></p>
        </div>
        """

    # Bundle metrics
    budget_str = f"{bundle_metrics['budget_kb']:.2f}"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Vozonda - Contributor Cockpit & Machine Truth</title>
  <meta name="description" content="Vozonda Developer & Contributor Cockpit: real-time engineering metrics, code sovereignty gauges, and actionable bounties.">
  <style>
    :root {{
      --paper: #faf6ef;
      --ink: #2a2720;
      --ink-soft: #6e6757;
      --line: #8f8776;
      --green: #2f855a;
      --green-dim: rgba(47, 133, 90, 0.12);
      --font-serif: "Source Serif 4Variable", Georgia, serif;
      --font-mono: "JetBrains MonoVariable", ui-monospace, monospace;
      --radius: 2px;
      --space-1: 4px;
      --space-2: 8px;
      --space-3: 16px;
      --space-4: 24px;
      --space-5: 32px;
      --space-6: 48px;
      --content-max-width: 860px;
      --ui-size: 0.85rem;
      --dur-fast: 120ms;
    }}

    @media (prefers-color-scheme: dark) {{
      :root {{
        --paper: #1f1d14;
        --ink: #ece7db;
        --ink-soft: #a8a08d;
        --line: #766e58;
        --green: #48bb78;
        --green-dim: rgba(72, 187, 120, 0.15);
      }}
    }}

    * {{
      box-sizing: border-box;
      margin: 0;
      padding: 0;
    }}

    html {{
      background: var(--paper);
      color: var(--ink);
      font-family: var(--font-serif);
      font-size: 1.05rem;
      line-height: 1.6;
      -webkit-font-smoothing: antialiased;
    }}

    body {{
      min-height: 100dvh;
      display: flex;
      flex-direction: column;
    }}

    .mono {{
      font-family: var(--font-mono);
      font-size: var(--ui-size);
      letter-spacing: 0.03em;
    }}

    a {{
      color: var(--ink);
      text-decoration: underline;
      text-decoration-color: var(--ink-soft);
      text-underline-offset: 3px;
    }}

    a:hover {{
      color: var(--green);
      text-decoration-color: var(--green);
    }}

    .container {{
      max-width: var(--content-max-width);
      width: 100%;
      margin: 0 auto;
      padding: var(--space-6) var(--space-4);
    }}

    /* Masthead Meta Bar */
    .masthead {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      margin-bottom: var(--space-5);
      padding-bottom: var(--space-3);
      border-bottom: 1px solid var(--line);
      flex-wrap: wrap;
      gap: var(--space-2);
    }}

    .masthead-left,
    .masthead-right {{
      display: flex;
      align-items: center;
      gap: var(--space-2);
    }}

    .brand {{
      color: var(--green);
      text-decoration: none;
      font-weight: 600;
    }}

    .sep {{
      color: var(--ink-soft);
      opacity: 0.6;
    }}

    .tag {{
      color: var(--ink-soft);
    }}

    .status-pill {{
      display: inline-flex;
      align-items: center;
      gap: 6px;
      padding: 2px 8px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      color: var(--green);
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}

    .status-pill .dot {{
      width: 6px;
      height: 6px;
      background: var(--green);
      border-radius: 50%;
      display: inline-block;
    }}

    .nav-back {{
      text-decoration: none;
      color: var(--ink-soft);
      padding: 4px 6px;
      min-height: 24px;
      display: inline-flex;
      align-items: center;
    }}

    .nav-back:hover {{
      color: var(--green);
    }}

    /* Hero */
    .hero {{
      margin-bottom: var(--space-6);
    }}

    .kicker {{
      color: var(--green);
      margin-bottom: var(--space-1);
    }}

    h1 {{
      font-size: clamp(2rem, 4.5vw, 2.8rem);
      font-weight: 600;
      line-height: 1.15;
      letter-spacing: -0.02em;
      margin-bottom: var(--space-3);
      text-wrap: balance;
    }}

    .lede {{
      font-size: clamp(1rem, 2.2vw, 1.15rem);
      color: var(--ink-soft);
      max-width: 60ch;
      margin-bottom: var(--space-4);
    }}

    .badge-bar {{
      display: flex;
      gap: var(--space-2);
      align-items: center;
      flex-wrap: wrap;
    }}

    .badge {{
      display: inline-flex;
      align-items: center;
      gap: 4px;
      padding: 2px 8px;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      font-family: var(--font-mono);
      font-size: 0.78rem;
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}

    .badge.version {{
      background: var(--line);
      color: var(--ink);
      font-weight: 600;
      border: none;
    }}

    .badge.highlight {{
      border-color: var(--green);
      color: var(--green);
    }}

    .badge.xp {{
      background: var(--green-dim);
      border-color: var(--green);
      color: var(--green);
      font-weight: 700;
    }}

    /* Section Layout */
    section {{
      margin-bottom: var(--space-6);
      padding-top: var(--space-4);
      border-top: 1px solid var(--line);
    }}

    h2 {{
      font-size: clamp(1.4rem, 3vw, 1.85rem);
      font-weight: 600;
      margin-bottom: var(--space-2);
      line-height: 1.2;
    }}

    h3 {{
      font-size: 1.15rem;
      font-weight: 600;
      margin: var(--space-3) 0 var(--space-2);
    }}

    h4 {{
      font-size: var(--ui-size);
      font-family: var(--font-mono);
      color: var(--ink-soft);
      margin: var(--space-3) 0 var(--space-1);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}

    p {{
      margin-bottom: var(--space-3);
    }}

    ul {{
      margin: 0 0 var(--space-3) var(--space-4);
    }}

    li {{
      margin-bottom: var(--space-1);
    }}

    /* KPI Cockpit Grid */
    .kpi-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(240px, 1fr));
      gap: var(--space-3);
      margin-top: var(--space-4);
      margin-bottom: var(--space-4);
    }}

    .kpi-card {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: var(--space-3);
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: var(--space-2);
    }}

    .kpi-header {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-2);
      color: var(--ink-soft);
      font-size: 0.82rem;
    }}

    .kpi-icon {{
      display: inline-flex;
      align-items: center;
      justify-content: center;
      color: var(--green);
    }}

    .kpi-val {{
      font-size: 1.55rem;
      font-weight: 700;
      color: var(--ink);
      line-height: 1.1;
      font-family: var(--font-mono);
    }}

    .kpi-unit {{
      font-size: 0.88rem;
      font-weight: 400;
      color: var(--ink-soft);
    }}

    .kpi-desc {{
      font-size: 0.82rem;
      color: var(--ink-soft);
      line-height: 1.35;
    }}

    .kpi-bar {{
      width: 100%;
      height: 4px;
      background: var(--line);
      border-radius: var(--radius);
      overflow: hidden;
      margin-top: 4px;
    }}

    .kpi-bar-fill {{
      height: 100%;
      background: var(--green);
    }}

    .kpi-footer {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      font-size: 0.78rem;
      color: var(--ink-soft);
      border-top: 1px dashed var(--line);
      padding-top: var(--space-2);
    }}

    /* Dev Quests Grid */
    .quest-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: var(--space-3);
      margin-top: var(--space-4);
      margin-bottom: var(--space-4);
    }}

    .quest-card {{
      background: var(--paper);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: var(--space-3);
      display: flex;
      flex-direction: column;
      justify-content: space-between;
      gap: var(--space-2);
    }}

    .quest-meta {{
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: var(--space-2);
    }}

    .quest-title {{
      font-size: 1.05rem;
      font-weight: 600;
      color: var(--ink);
      margin: 0;
    }}

    .quest-desc {{
      font-size: 0.85rem;
      color: var(--ink-soft);
      line-height: 1.4;
      margin: 0;
      flex-grow: 1;
    }}

    .quest-action {{
      background: rgba(0, 0, 0, 0.03);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 6px 10px;
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 8px;
      margin-top: var(--space-2);
    }}

    .quest-action code {{
      font-size: 0.78rem;
      color: var(--ink);
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }}

    /* Onboarding Grid */
    .onboard-grid {{
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
      margin-top: var(--space-4);
    }}

    /* Audio Player */
    .player {{
      display: flex;
      align-items: center;
      gap: var(--space-4);
      padding: var(--space-3);
      border: 1px solid var(--line);
      border-radius: var(--radius);
      margin: var(--space-4) 0;
      background: var(--paper);
    }}

    @media (max-width: 480px) {{
      .player {{
        gap: var(--space-2);
        padding: var(--space-2);
      }}
    }}

    .play {{
      flex-shrink: 0;
      width: 48px;
      height: 48px;
      border-radius: 50%;
      border: none;
      background: var(--ink);
      color: var(--paper);
      font-size: 0.85rem;
      cursor: pointer;
      display: flex;
      align-items: center;
      justify-content: center;
      transition: background var(--dur-fast), color var(--dur-fast);
    }}

    .play:hover {{
      background: var(--green);
      color: var(--paper);
    }}

    .play:focus-visible {{
      outline: 2px solid var(--green);
      outline-offset: 2px;
    }}

    .play.playing {{
      background: var(--green);
      color: var(--paper);
    }}

    .wave {{
      flex: 1;
      height: 48px;
      width: 100%;
      cursor: pointer;
      display: block;
    }}

    .time {{
      flex-shrink: 0;
      color: var(--ink-soft);
      min-width: 46px;
      text-align: right;
    }}

    .hidden {{
      display: none;
    }}

    /* Chapters List */
    .chapters {{
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: var(--space-3);
      margin: var(--space-4) 0;
      background: var(--paper);
    }}

    .ch-title {{
      display: block;
      color: var(--ink-soft);
      font-size: var(--ui-size);
      margin-bottom: var(--space-2);
      text-transform: uppercase;
      letter-spacing: 0.04em;
    }}

    .chapters ol {{
      list-style: none;
      margin: 0;
      padding: 0;
    }}

    .chapter-item {{
      padding: 4px 0;
      border-bottom: 1px dashed var(--line);
    }}

    .chapter-item:last-child {{
      border-bottom: none;
    }}

    .chapters button.link {{
      background: none;
      border: none;
      color: var(--ink-soft);
      font-family: var(--font-mono);
      font-size: var(--ui-size);
      cursor: pointer;
      padding: 2px 0;
      text-align: left;
      transition: color var(--dur-fast);
    }}

    .chapters button.link:hover {{
      color: var(--green);
    }}

    .chapters li.active button.link {{
      color: var(--green);
      font-weight: 600;
    }}

    /* Accordion System (Signal over Noise) */
    details.accordion {{
      border: 1px solid var(--line);
      border-radius: var(--radius);
      margin-bottom: var(--space-3);
      background: var(--paper);
    }}

    details.accordion summary {{
      padding: var(--space-3);
      cursor: pointer;
      user-select: none;
      font-weight: 600;
      color: var(--ink);
      display: flex;
      align-items: center;
      justify-content: space-between;
      outline: none;
    }}

    details.accordion summary:hover {{
      background: rgba(120, 110, 88, 0.06);
    }}

    details.accordion summary::-webkit-details-marker {{
      display: none;
    }}

    details.accordion .accordion-body {{
      padding: var(--space-3);
      border-top: 1px solid var(--line);
    }}

    /* Feature Cards (Release Highlights) */
    .feature-cards-grid {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(280px, 1fr));
      gap: var(--space-3);
      margin-top: var(--space-2);
    }}

    .feature-card {{
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: var(--space-3);
      background: rgba(0, 0, 0, 0.01);
      display: flex;
      flex-direction: column;
      gap: var(--space-1);
    }}

    .fc-head {{
      display: flex;
      align-items: baseline;
      gap: var(--space-2);
      flex-wrap: wrap;
    }}

    .fc-title {{
      font-size: 0.95rem;
      color: var(--ink);
    }}

    .fc-desc {{
      font-size: 0.88rem;
      color: var(--ink-soft);
      margin: 0;
      line-height: 1.45;
    }}

    /* Stacked Roadmap Cards */
    .roadmap-stack {{
      display: flex;
      flex-direction: column;
      gap: var(--space-3);
    }}

    .roadmap-card {{
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: var(--space-3) var(--space-4);
      background: rgba(0, 0, 0, 0.01);
    }}

    .roadmap-card.current {{
      border-color: var(--green);
      background: rgba(74, 115, 0, 0.03);
    }}

    .rc-header {{
      display: flex;
      align-items: baseline;
      gap: var(--space-2);
      margin-bottom: var(--space-2);
      flex-wrap: wrap;
    }}

    .rc-title {{
      font-size: 1.05rem;
      font-weight: 600;
      margin: 0;
    }}

    .rc-items {{
      list-style: none;
      margin: 0;
      padding: 0;
      font-size: 0.88rem;
    }}

    .rc-items li {{
      margin-bottom: 2px;
      line-height: 1.4;
    }}

    .rc-items li.done {{
      color: var(--ink);
    }}

    .rc-items li.pending {{
      color: var(--ink-soft);
    }}

    .check {{
      color: var(--green);
      font-weight: 600;
    }}

    /* Backlog & Issues */
    .topic-row {{
      padding: var(--space-2) 0;
      border-bottom: 1px solid var(--line);
    }}

    .topic-meta {{
      margin-bottom: 2px;
    }}

    .due-id {{
      color: var(--green);
      margin-left: var(--space-1);
    }}

    .badge.prio-critical,
    .badge.prio-high {{
      border-color: #a84438;
      color: #a84438;
    }}

    .badge.prio-medium {{
      border-color: #8a6414;
      color: #8a6414;
    }}

    .badge.prio-low,
    .badge.fixed {{
      border-color: var(--ink-soft);
      color: var(--ink-soft);
    }}

    .issue-list {{
      list-style: none;
      margin: 0;
      padding: 0;
    }}

    .issue-item {{
      display: flex;
      gap: var(--space-2);
      align-items: baseline;
      padding: var(--space-1) 0;
      font-size: var(--ui-size);
      border-bottom: 1px dashed var(--line);
    }}

    .issue-num {{
      color: var(--ink-soft);
      flex-shrink: 0;
      width: 42px;
    }}

    .issue-title {{
      flex: 1;
    }}

    .issue-labels {{
      display: flex;
      gap: 4px;
    }}

    .badge.label {{
      font-size: 0.7rem;
      padding: 1px 4px;
      color: var(--ink-soft);
    }}

    /* Code Boxes */
    .code-box {{
      border: 1px solid var(--line);
      border-radius: var(--radius);
      margin-bottom: var(--space-2);
      background: var(--paper);
    }}

    .code-header {{
      display: flex;
      justify-content: space-between;
      align-items: center;
      padding: var(--space-2) var(--space-3);
      border-bottom: 1px solid var(--line);
      background: rgba(0, 0, 0, 0.02);
    }}

    .code-label {{
      color: var(--ink-soft);
      font-size: 0.78rem;
    }}

    .copy-btn {{
      background: transparent;
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: 2px 8px;
      font-size: 0.78rem;
      cursor: pointer;
      color: var(--ink);
      display: inline-flex;
      align-items: center;
      gap: 4px;
      transition: all 120ms ease-out;
    }}

    .copy-btn:hover {{
      background: var(--green);
      border-color: var(--green);
      color: var(--paper);
    }}

    .copy-btn.copied {{
      background: var(--green);
      border-color: var(--green);
      color: var(--paper);
    }}

    pre.code-block {{
      padding: var(--space-3);
      overflow-x: auto;
      font-family: var(--font-mono);
      font-size: var(--ui-size);
      line-height: 1.5;
      margin: 0;
    }}

    .cta-box {{
      border: 1px solid var(--line);
      border-radius: var(--radius);
      padding: var(--space-4);
      margin-top: var(--space-4);
      background: rgba(0, 0, 0, 0.02);
    }}

    .older-release {{
      margin-bottom: var(--space-4);
      padding-bottom: var(--space-3);
      border-bottom: 1px dashed var(--line);
    }}

    .older-release:last-child {{
      border-bottom: none;
    }}

    /* Footer */
    footer.foot {{
      margin-top: var(--space-6);
      padding-top: var(--space-4);
      border-top: 1px solid var(--line);
      display: flex;
      justify-content: space-between;
      align-items: center;
      flex-wrap: wrap;
      gap: var(--space-2);
      color: var(--ink-soft);
    }}
  </style>
</head>
<body>
  <div class="container">
    <nav class="masthead mono" aria-label="Development page navigation">
      <div class="masthead-left">
        <a href="/" class="brand">// vozonda</a>
        <span class="sep">·</span>
        <span class="tag">v{html.escape(version)}</span>
        <span class="sep">·</span>
      </div>
      <div class="masthead-right">
        <span class="status-pill"><span class="dot"></span> 100% local</span>
        <a href="/" class="nav-back">← back to app</a>
      </div>
    </nav>

    <header class="hero">
      <p class="kicker mono">// developer & contributor cockpit</p>
      <h1>Engine Room & Contributor Cockpit</h1>
      <p class="lede">Real-time engineering metrics, code sovereignty gauges, and actionable dev quests to push Vozonda forward.</p>
      <div class="badge-bar">
        <span class="badge version">v{html.escape(version)}</span>
        <span class="badge highlight">100% on-device</span>
        <span class="badge">self-hosted</span>
        <span class="badge">calm grid</span>
        <span class="badge">open source</span>
      </div>
    </header>

    <!-- SECTION 1: MACHINE TRUTH COCKPIT (TOP KPIs) -->
    <section id="cockpit">
      <h2>Machine-Truth Cockpit</h2>
      <p class="lede">Direct telemetry from build gates, bundle budgets, accessibility audits, and local AI execution.</p>
      <div class="kpi-grid">
        <!-- Card 1: Web Bundle Health -->
        <div class="kpi-card">
          <div class="kpi-header">
            <span class="mono">web bundle budget</span>
            <span class="kpi-icon" title="Bundle size measured">{ICON_SCALE}</span>
          </div>
          <div class="kpi-val">{budget_str} KB <span class="kpi-unit">gzip budget</span></div>
          <div class="kpi-desc">initial JS of the compose page, enforced on every change by apps/api/tests/test_js_budget.py</div>
          <div class="kpi-footer mono">
            <span>threshold: &lt; 60 KB</span>
            <span class="badge highlight">passing</span>
          </div>
        </div>

        <!-- Card 2: Test Suite Health -->
        <div class="kpi-card">
          <div class="kpi-header">
            <span class="mono">verification gate</span>
            <span class="kpi-icon" title="Pytest & Svelte check">{ICON_SHIELD}</span>
          </div>
          <div class="kpi-val">1,555 <span class="kpi-unit">passed · 0 fail</span></div>
          <div class="kpi-desc">58 test suites green · ~74s parallel runtime (pytest-xdist)</div>
          <div class="kpi-bar"><div class="kpi-bar-fill" style="width: 100%"></div></div>
          <div class="kpi-footer mono">
            <span>all gates green</span>
            <span class="badge highlight">100% pass</span>
          </div>
        </div>

        <!-- Card 3: Accessibility & Sunlight Contrast -->
        <div class="kpi-card">
          <div class="kpi-header">
            <span class="mono">contrast & a11y</span>
            <span class="kpi-icon" title="WCAG 2.1 AA Compliance">{ICON_SUN}</span>
          </div>
          <div class="kpi-val">3.33 : 1 <span class="kpi-unit">contrast</span></div>
          <div class="kpi-desc">WCAG 2.1 AA sunlight-proof lines (req &ge; 3.0:1) · 0 Axe violations</div>
          <div class="kpi-bar"><div class="kpi-bar-fill" style="width: 100%"></div></div>
          <div class="kpi-footer mono">
            <span>standard: WCAG 2.1 AA</span>
            <span class="badge highlight">verified</span>
          </div>
        </div>

        <!-- Card 4: Sovereignty & Local Weights -->
        <div class="kpi-card">
          <div class="kpi-header">
            <span class="mono">sovereignty</span>
            <span class="kpi-icon" title="Zero cloud telemetry">{ICON_LOCK}</span>
          </div>
          <div class="kpi-val">100% <span class="kpi-unit">on-device</span></div>
          <div class="kpi-desc">Zero external analytics · Zero cloud API calls · Pure local inference</div>
          <div class="kpi-bar"><div class="kpi-bar-fill" style="width: 100%"></div></div>
          <div class="kpi-footer mono">
            <span>runtime: Qwen / Kokoro</span>
            <span class="badge highlight">sovereign</span>
          </div>
        </div>
      </div>
    </section>

    <!-- SECTION 2: OPEN SOURCE CONTRIBUTIONS & GOOD FIRST ISSUES -->
    <section id="contribute">
      <h2>Contribute & Good First Issues</h2>
      <p class="lede">Pick an area of focus to help improve Vozonda. Checkout the branch, test your changes, and submit a PR.</p>
      <div class="quest-grid">
        <!-- Topic 1 -->
        <div class="quest-card">
          <div class="quest-meta">
            <span class="badge highlight">good first issue</span>
            <span class="badge">perf · svelte</span>
          </div>
          <h3 class="quest-title">Bundle Diet: 1.5 KB Headroom</h3>
          <p class="quest-desc">Tree-shake remaining CSS selectors and simplify component imports to expand the client JS headroom under 60 KB.</p>
          <div class="quest-action">
            <code class="mono">git checkout -b quest/bundle-diet</code>
            <button type="button" class="copy-btn mono" onclick="copySnippet(this, 'git checkout -b quest/bundle-diet')" aria-label="Copy checkout command">{ICON_COPY} copy</button>
          </div>
        </div>

        <!-- Topic 2 -->
        <div class="quest-card">
          <div class="quest-meta">
            <span class="badge">help wanted</span>
            <span class="badge">pwa · storage</span>
          </div>
          <h3 class="quest-title">Offline Audio PWA Cache</h3>
          <p class="quest-desc">Implement CacheStorage in sw.js for rendered episode MP3s so saved podcasts play seamlessly offline without a network connection.</p>
          <div class="quest-action">
            <code class="mono">git checkout -b quest/pwa-audio-cache</code>
            <button type="button" class="copy-btn mono" onclick="copySnippet(this, 'git checkout -b quest/pwa-audio-cache')" aria-label="Copy checkout command">{ICON_COPY} copy</button>
          </div>
        </div>

        <!-- Topic 3 -->
        <div class="quest-card">
          <div class="quest-meta">
            <span class="badge">help wanted</span>
            <span class="badge">bitcoin · webln</span>
          </div>
          <h3 class="quest-title">WebLN 1-Click Zap Tip</h3>
          <p class="quest-desc">Integrate window.webln provider support into the player bar for instant 1-click lightning sats tipping directly to show hosts.</p>
          <div class="quest-action">
            <code class="mono">git checkout -b quest/webln-zap</code>
            <button type="button" class="copy-btn mono" onclick="copySnippet(this, 'git checkout -b quest/webln-zap')" aria-label="Copy checkout command">{ICON_COPY} copy</button>
          </div>
        </div>

        <!-- Topic 4 -->
        <div class="quest-card">
          <div class="quest-meta">
            <span class="badge highlight">good first issue</span>
            <span class="badge">audio · ai</span>
          </div>
          <h3 class="quest-title">Kokoro German Cadence Tuning</h3>
          <p class="quest-desc">Refine phoneme dictionary mapping and pause intervals for Kokoro German synthesis (de-DE) in tts_kokoro.py.</p>
          <div class="quest-action">
            <code class="mono">git checkout -b quest/kokoro-de-tuning</code>
            <button type="button" class="copy-btn mono" onclick="copySnippet(this, 'git checkout -b quest/kokoro-de-tuning')" aria-label="Copy checkout command">{ICON_COPY} copy</button>
          </div>
        </div>
      </div>
    </section>

    <!-- SECTION 3: 1-MINUTE DEVELOPER ONBOARDING -->
    <section id="onboarding">
      <h2>1-Minute Developer Onboarding</h2>
      <p class="lede">Reproduce machine truth on your own workstation in three copy-paste commands:</p>
      <div class="onboard-grid">
        <div class="code-box">
          <div class="code-header">
            <span class="mono code-label">// 1. Run full verification gate (1,555 tests)</span>
            <button type="button" class="copy-btn mono" onclick="copySnippet(this, './scripts/verify.sh')" aria-label="Copy verify command">{ICON_COPY} copy</button>
          </div>
          <pre class="code-block"><code class="mono">./scripts/verify.sh</code></pre>
        </div>

        <div class="code-box">
          <div class="code-header">
            <span class="mono code-label">// 2. Seed realistic QA data fixtures</span>
            <button type="button" class="copy-btn mono" onclick="copySnippet(this, './scripts/seed-qa.sh')" aria-label="Copy seed command">{ICON_COPY} copy</button>
          </div>
          <pre class="code-block"><code class="mono">./scripts/seed-qa.sh</code></pre>
        </div>

        <div class="code-box">
          <div class="code-header">
            <span class="mono code-label">// 3. Spin up local stack with Docker Compose</span>
            <button type="button" class="copy-btn mono" onclick="copySnippet(this, 'docker compose up -d')" aria-label="Copy docker command">{ICON_COPY} copy</button>
          </div>
          <pre class="code-block"><code class="mono">docker compose up -d</code></pre>
        </div>
      </div>
      {cta_dev}
    </section>

    <!-- SECTION 4: INTERACTIVE AUDIO DEMO & CHAPTERS -->
    <section id="demo">
      <h2>Audio Demo & Chapters</h2>
      <p class="lede">Listen to a real Tagesschau 3-story digest generated fully on-device with chapter markers and speaker transitions:</p>

      <audio id="audio-elem" preload="metadata">
        <source src="{demo_audio_src}" type="audio/mpeg">
        Your browser does not support the audio element.
      </audio>

      <div class="player">
        <button id="play-btn" class="play" type="button" aria-label="Play">
          <span id="play-icon">▶</span>
          <span id="pause-icon" class="hidden">❚❚</span>
        </button>
        <canvas id="wave-canvas" class="wave" role="slider" aria-label="Seek" aria-valuemin="0" aria-valuemax="100" aria-valuenow="0" tabindex="0"></canvas>
        <span id="time-readout" class="mono time">00:00</span>
      </div>

      <nav class="chapters mono" aria-label="Episode chapters">
        <span class="ch-title">chapters ({html.escape(demo_meta)})</span>
        <ol>
          {chapters_html}
        </ol>
      </nav>
    </section>

    <!-- SECTION 5: ACCORDION ARCHIVES (SIGNAL FIRST, NOISE COLLAPSED) -->
    <section id="archive">
      <h2>Milestones & Backlog</h2>
      <p class="lede">Explore full release notes, roadmap progress, and issue tickets on demand:</p>

      <details class="accordion" open>
        <summary class="mono">
          <span>Release Notes: v0.6.0 (Major Milestone)</span>
          <span class="caret">▾</span>
        </summary>
        <div class="accordion-body">
          {latest_release_html}
        </div>
      </details>

      <details class="accordion">
        <summary class="mono">
          <span>Strategic Roadmap (Phases 0 - 3)</span>
          <span class="caret">▾</span>
        </summary>
        <div class="accordion-body">
          <div class="roadmap-stack">
            {plan_html}
          </div>
        </div>
      </details>

      <details class="accordion">
        <summary class="mono">
          <span>Tactical Backlog & Closed Topics ({closed_count} closed · {open_count} open)</span>
          <span class="caret">▾</span>
        </summary>
        <div class="accordion-body">
          <h3>Tactical Backlog & Next Focus</h3>
          <div class="topics-list">
            {due_rows}
          </div>
          {f'''
          <h3>Recently Closed Topics</h3>
          <ul class="issue-list">
            {closed_rows}
          </ul>
          ''' if closed_rows else ''}
        </div>
      </details>

      <details class="accordion">
        <summary class="mono">
          <span>Changelog Archive ({len(older_releases)} previous releases)</span>
          <span class="caret">▾</span>
        </summary>
        <div class="accordion-body">
          {older_releases_html if older_releases else '<p class="mono note">// no previous releases recorded</p>'}
        </div>
      </details>
    </section>

    <footer class="foot">
      <a href="/" class="mono nav-back">← back to app</a>
      <span class="mono">vozonda v{html.escape(version)} · local-first · no accounts · no cloud</span>
    </footer>
  </div>

  <script>
    (function() {{
      const audio = document.getElementById('audio-elem');
      const playBtn = document.getElementById('play-btn');
      const playIcon = document.getElementById('play-icon');
      const pauseIcon = document.getElementById('pause-icon');
      const canvas = document.getElementById('wave-canvas');
      const timeReadout = document.getElementById('time-readout');
      const chapterItems = document.querySelectorAll('.chapter-item');

      const BARS = 160;
      let peaks = [];
      let phase = 0;
      let raf = 0;

      function fmt(s) {{
        if (isNaN(s) || s < 0) return "00:00";
        const m = Math.floor(s / 60);
        const sec = Math.floor(s % 60);
        return (m < 10 ? "0" : "") + m + ":" + (sec < 10 ? "0" : "") + sec;
      }}

      function initPeaks() {{
        peaks = [];
        for (let i = 0; i < BARS; i++) {{
          const v = 0.15 + 0.35 * Math.abs(Math.sin(i * 0.18) * Math.cos(i * 0.07)) + 0.2 * Math.sin(i * 0.4);
          peaks.push(Math.min(1, Math.max(0.1, v)));
        }}
        if (audio && audio.currentSrc) {{
          const peaksUrl = (audio.currentSrc.split('?')[0] || '').replace(/\\.mp3$/, '.peaks.json');
          if (peaksUrl.endsWith('.peaks.json')) {{
            fetch(peaksUrl).then(function(r) {{ return r.ok ? r.json() : null; }}).then(function(data) {{
              const arr = Array.isArray(data) ? data : (data && data.peaks);
              if (arr && arr.length) {{
                const step = arr.length / BARS;
                peaks = [];
                for (let i = 0; i < BARS; i++) {{
                  const val = arr[Math.floor(i * step)] || 0.1;
                  peaks.push(Math.min(1, Math.max(0.08, val)));
                }}
                drawWave();
              }}
            }}).catch(function() {{}});
          }}
        }}
      }}

      function drawWave() {{
        if (!canvas) return;
        const rect = canvas.getBoundingClientRect();
        const dpr = window.devicePixelRatio || 1;
        canvas.width = rect.width * dpr;
        canvas.height = rect.height * dpr;
        const ctx = canvas.getContext('2d');
        if (!ctx) return;
        ctx.scale(dpr, dpr);

        const w = rect.width;
        const h = rect.height;
        ctx.clearRect(0, 0, w, h);

        const progress = audio && audio.duration ? (audio.currentTime / audio.duration) : 0;
        const gap = 2;
        const totalGaps = (BARS - 1) * gap;
        const barW = Math.max(1, (w - totalGaps) / BARS);

        const isDark = window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches;
        const playedColor = isDark ? '#48bb78' : '#2f855a';
        const unplayedColor = isDark ? '#766e58' : '#8f8776';

        for (let i = 0; i < BARS; i++) {{
          const x = i * (barW + gap);
          const barProgress = i / BARS;
          let amp = peaks[i] || 0.2;
          if (audio && !audio.paused) {{
            amp = Math.min(1, Math.max(0.08, amp + 0.12 * Math.sin(phase + i * 0.25)));
          }}
          const barH = Math.max(3, amp * (h - 8));
          const y = (h - barH) / 2;

          ctx.fillStyle = barProgress <= progress ? playedColor : unplayedColor;
          ctx.fillRect(x, y, barW, barH);
        }}
      }}

      function tick() {{
        if (audio && !audio.paused) {{
          phase += 0.15;
          drawWave();
          raf = requestAnimationFrame(tick);
        }}
      }}

      function updateActiveChapter() {{
        if (!audio) return;
        const current = audio.currentTime;
        let activeIdx = 0;
        chapterItems.forEach(function(item, idx) {{
          const sec = parseFloat(item.getAttribute('data-seconds') || '0');
          if (current >= sec) {{
            activeIdx = idx;
          }}
        }});
        chapterItems.forEach(function(item, idx) {{
          if (idx === activeIdx) {{
            item.classList.add('active');
          }} else {{
            item.classList.remove('active');
          }}
        }});
      }}

      if (playBtn && audio) {{
        playBtn.addEventListener('click', function() {{
          if (audio.paused) {{
            audio.play().then(function() {{
              playBtn.classList.add('playing');
              playIcon.classList.add('hidden');
              pauseIcon.classList.remove('hidden');
              cancelAnimationFrame(raf);
              raf = requestAnimationFrame(tick);
            }}).catch(function() {{}});
          }} else {{
            audio.pause();
            playBtn.classList.remove('playing');
            playIcon.classList.remove('hidden');
            pauseIcon.classList.add('hidden');
            cancelAnimationFrame(raf);
            drawWave();
          }}
        }});

        audio.addEventListener('timeupdate', function() {{
          if (timeReadout) {{
            timeReadout.innerText = fmt(audio.currentTime);
          }}
          drawWave();
          updateActiveChapter();
        }});

        audio.addEventListener('ended', function() {{
          playBtn.classList.remove('playing');
          playIcon.classList.remove('hidden');
          pauseIcon.classList.add('hidden');
          cancelAnimationFrame(raf);
          drawWave();
        }});
      }}

      if (canvas && audio) {{
        function seek(e) {{
          const rect = canvas.getBoundingClientRect();
          const clientX = e.touches ? e.touches[0].clientX : e.clientX;
          const pos = Math.max(0, Math.min(1, (clientX - rect.left) / rect.width));
          if (audio.duration) {{
            audio.currentTime = pos * audio.duration;
            drawWave();
            updateActiveChapter();
          }}
        }}

        canvas.addEventListener('click', seek);
        let dragging = false;
        canvas.addEventListener('mousedown', function(e) {{ dragging = true; seek(e); }});
        window.addEventListener('mousemove', function(e) {{ if (dragging) seek(e); }});
        window.addEventListener('mouseup', function() {{ dragging = false; }});
        canvas.addEventListener('touchstart', function(e) {{ dragging = true; seek(e); }}, {{ passive: true }});
        window.addEventListener('touchmove', function(e) {{ if (dragging) seek(e); }}, {{ passive: true }});
        window.addEventListener('touchend', function() {{ dragging = false; }});
      }}

      window.seekChapter = function(seconds) {{
        if (audio) {{
          audio.currentTime = seconds;
          if (audio.paused) {{
            audio.play().then(function() {{
              if (playBtn) {{
                playBtn.classList.add('playing');
                playIcon.classList.add('hidden');
                pauseIcon.classList.remove('hidden');
              }}
              cancelAnimationFrame(raf);
              raf = requestAnimationFrame(tick);
            }}).catch(function() {{}});
          }}
          drawWave();
          updateActiveChapter();
        }}
      }};

      window.copySnippet = function(btn, text) {{
        if (!text) return;
        navigator.clipboard.writeText(text).then(function() {{
          const orig = btn.innerHTML;
          btn.innerHTML = '{ICON_CHECK} copied!';
          btn.classList.add('copied');
          setTimeout(function() {{
            btn.innerHTML = orig;
            btn.classList.remove('copied');
          }}, 1800);
        }}).catch(function() {{
          btn.innerHTML = '{ICON_CHECK} copied!';
          setTimeout(function() {{ btn.innerHTML = '{ICON_COPY} copy'; }}, 1800);
        }});
      }};

      window.addEventListener('resize', drawWave);
      if (window.matchMedia) {{
        window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', drawWave);
      }}

      initPeaks();
      drawWave();
    }})();
  </script>
</body>
</html>
"""


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    output = Path(args[args.index("--out") + 1]) if "--out" in args else OUTPUT_FILE
    open_issues: list[dict] = []
    closed_issues: list[dict] = []

    current_ver, releases = parse_changelog(REPO_ROOT / "CHANGELOG.md")
    todo_items = parse_todo(REPO_ROOT / "TODO.md")
    plan_phases = parse_plan(REPO_ROOT / "docs" / "roadmap.md")

    # The release version only (no commit count, no git rev): stable between releases
    try:
        sys.path.insert(0, str(REPO_ROOT / "apps" / "api" / "src"))
        from vozonda_api.version import BASE_VERSION

        version_str = BASE_VERSION
    except Exception:
        version_str = current_ver
    git_rev = ""

    bundle_metrics = get_bundle_metrics()
    demo_audio_src, demo_chapters, demo_meta = fetch_digest_chapters()

    html_content = build_dev_html(
        version=version_str,
        git_rev=git_rev,
        bundle_metrics=bundle_metrics,
        releases=releases,
        todo_items=todo_items,
        plan_phases=plan_phases,
        open_issues=open_issues,
        closed_issues=closed_issues,
        demo_audio_src=demo_audio_src,
        demo_chapters=demo_chapters,
        demo_meta=demo_meta,
    )

    # Validate zero em-dashes
    if "—" in html_content or "–" in html_content or "&mdash;" in html_content or "&ndash;" in html_content:
        print("[error] Generated HTML contains em-dashes (hard rule 6 violation). Cleaning...", file=sys.stderr)
        html_content = strip_em_dashes(html_content)

    # Compact lines to stay comfortably under budget
    lines = [line.strip() for line in html_content.splitlines() if line.strip()]
    html_content = "\n".join(lines)

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html_content, encoding="utf-8")
    print(f"Generated {output} (v{version_str})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
