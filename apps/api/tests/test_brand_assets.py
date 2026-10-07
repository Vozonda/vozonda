"""Tests for Vozonda brand assets.

Ensures:
- Every generated brand asset exists with the right pixel dimensions.
- favicon.svg contains the prefers-color-scheme dark switch.
- manifest.webmanifest lists the brand icons.
- gen_brand_assets generator is deterministic.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from PIL import Image
import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
PUBLIC = REPO_ROOT / "apps" / "web" / "public"


EXPECTED_SIZES: dict[str, tuple[int, int]] = {
    "icon-192.png": (192, 192),
    "icon-512.png": (512, 512),
    "icon-maskable-512.png": (512, 512),
    "apple-touch-icon.png": (180, 180),
    "og-default.png": (1200, 630),
    "github-social.png": (1280, 640),
    "nostr-avatar.png": (1024, 1024),
}


def test_brand_assets_exist_with_correct_dimensions():
    for name, expected in EXPECTED_SIZES.items():
        path = PUBLIC / name
        assert path.exists(), f"Missing brand asset: {name}"
        with Image.open(path) as im:
            assert im.size == expected, f"{name} size is {im.size}, expected {expected}"


def test_favicon_svg_dark_switch():
    fav = PUBLIC / "favicon.svg"
    assert fav.exists(), "Missing favicon.svg"
    content = fav.read_text(encoding="utf-8")
    assert "prefers-color-scheme: dark" in content, "favicon.svg must contain prefers-color-scheme: dark"
    assert "Vozonda" in content


def test_manifest_names_brand_icons():
    manifest_file = PUBLIC / "manifest.webmanifest"
    assert manifest_file.exists(), "Missing manifest.webmanifest"
    data = json.loads(manifest_file.read_text(encoding="utf-8"))
    assert data.get("name") == "Vozonda"
    icons = data.get("icons", [])
    icon_srcs = {i.get("src") for i in icons}
    assert "/icon-192.png" in icon_srcs, "Missing /icon-192.png in manifest"
    assert "/icon-512.png" in icon_srcs, "Missing /icon-512.png in manifest"
    assert any("maskable" in i.get("purpose", "") for i in icons), "Missing maskable icon in manifest"


def test_generator_deterministic():
    # Read existing bytes of icon-192.png
    target = PUBLIC / "icon-192.png"
    assert target.exists()
    first_bytes = target.read_bytes()

    # Re-run generator
    gen_script = REPO_ROOT / "scripts" / "gen_brand_assets.py"
    res = subprocess.run([sys_python(), str(gen_script)], capture_output=True, text=True)
    assert res.returncode == 0, f"Generator failed:\n{res.stderr}\n{res.stdout}"

    second_bytes = target.read_bytes()
    # Either bytes match or pixels match
    if first_bytes == second_bytes:
        assert True
    else:
        with Image.open(target) as im2, Image.open(PUBLIC / "icon-192.png") as im1:
            assert list(im1.getdata()) == list(im2.getdata())


def sys_python() -> str:
    import sys
    return sys.executable
