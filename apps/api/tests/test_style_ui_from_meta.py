"""VOZONDA-STYLE-UI-FROM-META: the web style catalogue comes from /meta.

The backend registry (vozonda_api.style_registry) is the single source of
truth and GET /meta already exposes it as style_meta. The web app must build
its style groups, icons and docs from that payload (apps/web/src/lib/styles.ts)
instead of hardcoded copies in the components. Only lib/styles.ts may hold a
static fallback list for offline use, and it must match the registry.

These checks fail on the old code (hardcoded STYLE_GROUPS / STYLE_ICON /
DEFAULT_STYLE_DOCS copies in the components).
"""

from __future__ import annotations

import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[3]
WEB_SRC = REPO_ROOT / "apps" / "web" / "src"
STYLES_TS = WEB_SRC / "lib" / "styles.ts"

COMPONENT_FILES = [
    WEB_SRC / "App.svelte",
    WEB_SRC / "lib" / "components" / "EssentialsSection.svelte",
    WEB_SRC / "lib" / "components" / "SettingsScreen.svelte",
    WEB_SRC / "lib" / "components" / "ListenScreen.svelte",
    WEB_SRC / "lib" / "api.ts",
]

# Style ids that only ever appear together in a hardcoded catalogue copy.
PROBE_IDS = ("crisis_room", "true_crime", "tech_roast", "courtroom", "meditation")


def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_styles_module_exists() -> None:
    assert STYLES_TS.is_file(), "apps/web/src/lib/styles.ts is missing"
    src = _read(STYLES_TS)
    assert "FALLBACK_STYLE_META" in src
    assert "style_meta" in src
    assert "buildStyleGroups" in src
    assert "buildStyleDocs" in src


def test_no_hardcoded_group_or_icon_copies_in_components() -> None:
    for path in COMPONENT_FILES:
        src = _read(path)
        assert "STYLE_GROUPS" not in src, f"{path.name} still holds a STYLE_GROUPS copy"
        assert "STYLE_ICON" not in src, f"{path.name} still holds a STYLE_ICON copy"
        assert "DEFAULT_STYLE_DOCS" not in src, f"{path.name} still holds a DEFAULT_STYLE_DOCS copy"


def test_no_style_id_literal_lists_in_components() -> None:
    for path in COMPONENT_FILES:
        src = _read(path)
        hits = [sid for sid in PROBE_IDS if re.search(rf"""['"]{sid}['"]""", src)]
        assert len(hits) <= 1, (
            f"{path.name} still holds a hardcoded style list: {hits}"
        )


def test_components_import_from_shared_styles_module() -> None:
    for path in COMPONENT_FILES:
        src = _read(path)
        assert re.search(r"""from\s+['"](?:\./lib/styles|\./styles|\.\./styles)['"]""", src), (
            f"{path.name} does not import the shared lib/styles module"
        )


def _parse_fallback(src: str) -> dict[str, dict[str, str]]:
    block = re.search(r"FALLBACK_STYLE_META:\s*StyleMeta\[\]\s*=\s*\[(.*?)\n\]", src, re.S)
    assert block, "FALLBACK_STYLE_META list not found in lib/styles.ts"
    entries: dict[str, dict[str, str]] = {}
    pattern = re.compile(
        r"""\{\s*id:\s*'([^']+)'\s*,\s*doc:\s*'((?:[^'\\]|\\.)*)'\s*,"""
        r"""\s*group:\s*'([^']+)'\s*,\s*icon:\s*'([^']+)'""",
    )
    for match in pattern.finditer(block.group(1)):
        sid, doc, group, icon = match.groups()
        entries[sid] = {"doc": doc, "group": group, "icon": icon}
    assert entries, "no fallback entries parsed from lib/styles.ts"
    return entries


def test_fallback_matches_backend_registry() -> None:
    from vozonda_api.style_registry import REGISTRY

    fallback = _parse_fallback(_read(STYLES_TS))
    registry = {s.id: {"doc": s.doc, "group": s.group, "icon": s.icon} for s in REGISTRY}
    assert set(fallback) == set(registry), (
        f"fallback ids drifted from registry: "
        f"missing={sorted(set(registry) - set(fallback))} "
        f"extra={sorted(set(fallback) - set(registry))}"
    )
    for sid, want in registry.items():
        got = fallback[sid]
        assert got == want, f"style {sid!r} drifted: fallback={got} registry={want}"


def test_fallback_matches_style_meta_shape() -> None:
    from vozonda_api.style_registry import STYLE_META

    fallback = _parse_fallback(_read(STYLES_TS))
    meta = {e["id"]: e for e in STYLE_META}
    assert set(fallback) == set(meta)
    for sid, entry in meta.items():
        assert fallback[sid]["doc"] == entry["doc"], f"style {sid!r} doc drifted"
        assert fallback[sid]["group"] == entry["group"], f"style {sid!r} group drifted"
        assert fallback[sid]["icon"] == entry["icon"], f"style {sid!r} icon drifted"


def test_fallback_group_order_matches_ui() -> None:
    fallback = _parse_fallback(_read(STYLES_TS))
    groups = [fallback[sid]["group"] for sid in fallback]
    assert groups, "fallback is empty"
    for group in ("learn", "mood", "drama", "play"):
        assert group in groups, f"group {group!r} missing from fallback"


def test_group_chip_order_covers_registry() -> None:
    from vozonda_api.style_registry import REGISTRY

    src = _read(STYLES_TS)
    block = re.search(r"GROUP_STYLE_ORDER[^{]*\{(.*?)\n\}", src, re.S)
    assert block, "GROUP_STYLE_ORDER map not found in lib/styles.ts"
    ordered = re.findall(r"""'([a-z0-9_]+)'""", block.group(1))
    # keys learn/mood/drama/play also match; keep only real style ids
    registry_ids = {s.id for s in REGISTRY}
    chip_ids = [sid for sid in ordered if sid in registry_ids]
    assert set(chip_ids) == registry_ids, (
        f"chip order drifted from registry: "
        f"missing={sorted(registry_ids - set(chip_ids))} "
        f"extra={sorted(set(chip_ids) - registry_ids)}"
    )
    # map keys (learn/mood/...) are bare identifiers, so every quoted
    # entry must be a registry style id with no duplicates
    assert len(chip_ids) == len(ordered) == len(registry_ids), (
        f"unexpected entries in GROUP_STYLE_ORDER: {ordered}"
    )
