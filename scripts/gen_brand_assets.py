#!/usr/bin/env python3
"""Generate Vozonda brand assets from brand/*.svg into apps/web/public.

Renders:
  - favicon.svg: brand/vozonda-icon.svg with prefers-color-scheme dark switch
  - icon-192.png: 192x192
  - icon-512.png: 512x512
  - icon-maskable-512.png: 512x512 with icon inside the 80% safe zone on paper
  - apple-touch-icon.png: 180x180
  - og-default.png: 1200x630 (lockup on paper with tagline 'Turn sources into your podcast')
  - github-social.png: 1280x640
  - nostr-avatar.png: 1024x1024
  - vozonda-mark.svg / vozonda-mark-dark.svg: mark assets for app header
"""
from __future__ import annotations

import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from PIL import Image

REPO_ROOT = Path(__file__).resolve().parents[1]
BRAND = REPO_ROOT / "brand"
PUBLIC = REPO_ROOT / "apps" / "web" / "public"

PAPER_LIGHT = "#faf6ef"
INK_DARK = "#1a1815"
TAGLINE = "Turn sources into your podcast"


def _find_chrome() -> str:
    for cmd in ("google-chrome-stable", "google-chrome", "chromium", "/snap/bin/chromium"):
        p = shutil.which(cmd)
        if p:
            return p
    raise RuntimeError("No headless chrome/chromium found to render SVGs")


def render_html_to_png(html_content: str, width: int, height: int, dest_path: Path, chrome_bin: str) -> None:
    """Render an HTML string to a screenshot of exactly width x height."""
    with tempfile.NamedTemporaryFile("w", suffix=".html", delete=False) as f:
        f.write(html_content)
        f.flush()
        temp_html = Path(f.name)

    temp_png = temp_html.with_suffix(".png")
    try:
        cmd = [
            chrome_bin,
            "--headless",
            "--disable-gpu",
            "--hide-scrollbars",
            f"--window-size={width},{height}",
            f"--screenshot={temp_png}",
            f"file://{temp_html.resolve()}",
        ]
        res = subprocess.run(cmd, capture_output=True, text=True, check=True)
        # Load and normalize with Pillow to ensure deterministic compression & exact dimensions
        im = Image.open(temp_png)
        if im.size != (width, height):
            im = im.resize((width, height), Image.Resampling.LANCZOS)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        im.save(dest_path, "PNG")
    finally:
        temp_html.unlink(missing_ok=True)
        temp_png.unlink(missing_ok=True)


def generate_favicon(dest: Path) -> None:
    """Create favicon.svg with a prefers-color-scheme switch."""
    svg = f"""<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 64 64" role="img" aria-label="Vozonda">
<title>Vozonda</title>
<style>
  :root {{
    --bubble: #1a1815;
    --bar: #faf6ef;
  }}
  @media (prefers-color-scheme: dark) {{
    :root {{
      --bubble: #ede8dd;
      --bar: #1f1d14;
    }}
  }}
  .bubble {{ fill: var(--bubble); }}
  .bar {{ fill: var(--bar); }}
</style>
<path class="bubble" d="M6 6H58V48H27L14 59V48H6Z"/>
<rect class="bar" x="13.5" y="22" width="4" height="10"/>
<rect class="bar" x="19.5" y="17" width="4" height="20"/>
<rect class="bar" x="25.5" y="13" width="4" height="28"/>
<rect class="bar" x="31.5" y="19" width="4" height="16"/>
<rect class="bar" x="37.5" y="14" width="4" height="26"/>
<rect class="bar" x="43.5" y="21" width="4" height="12"/>
<rect class="bar" x="49.5" y="18" width="4" height="18"/>
</svg>
"""
    dest.write_text(svg, encoding="utf-8")


def generate_all() -> None:
    chrome = _find_chrome()
    PUBLIC.mkdir(parents=True, exist_ok=True)

    # 1. Copy mark SVGs for web header
    shutil.copyfile(BRAND / "vozonda-mark.svg", PUBLIC / "vozonda-mark.svg")
    shutil.copyfile(BRAND / "vozonda-mark-dark.svg", PUBLIC / "vozonda-mark-dark.svg")

    # 2. favicon.svg with prefers-color-scheme
    generate_favicon(PUBLIC / "favicon.svg")

    icon_svg_url = f"file://{(BRAND / 'vozonda-icon.svg').resolve()}"
    lockup_svg_url = f"file://{(BRAND / 'vozonda-lockup.svg').resolve()}"

    # 3. Simple square icons (transparent or native SVG aspect)
    for name, size in (
        ("icon-192.png", 192),
        ("icon-512.png", 512),
        ("nostr-avatar.png", 1024),
    ):
        html = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ width:{size}px; height:{size}px; overflow:hidden; background:transparent; display:flex; align-items:center; justify-content:center; }}
  img {{ width:{size}px; height:{size}px; display:block; }}
</style></head>
<body><img src="{icon_svg_url}"></body>
</html>"""
        render_html_to_png(html, size, size, PUBLIC / name, chrome)

    # 4. apple-touch-icon.png (180x180 on paper background)
    apple_html = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ width:180px; height:180px; overflow:hidden; background:{PAPER_LIGHT}; display:flex; align-items:center; justify-content:center; }}
  img {{ width:144px; height:144px; display:block; }}
</style></head>
<body><img src="{icon_svg_url}"></body>
</html>"""
    render_html_to_png(apple_html, 180, 180, PUBLIC / "apple-touch-icon.png", chrome)

    # 5. icon-maskable-512.png (512x512 on paper background, safe zone center 80%)
    maskable_html = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><style>
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{ width:512px; height:512px; overflow:hidden; background:{PAPER_LIGHT}; display:flex; align-items:center; justify-content:center; }}
  img {{ width:384px; height:384px; display:block; }}
</style></head>
<body><img src="{icon_svg_url}"></body>
</html>"""
    render_html_to_png(maskable_html, 512, 512, PUBLIC / "icon-maskable-512.png", chrome)

    # 6. og-default.png (1200x630, lockup on paper with tagline)
    font_file = (PUBLIC / "fonts" / "source-serif-4-latin-wght-normal.woff2").resolve()
    og_html = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><style>
  @font-face {{
    font-family: 'Source Serif 4';
    src: url('file://{font_file}') format('woff2');
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{
    width:1200px;
    height:630px;
    overflow:hidden;
    background:{PAPER_LIGHT};
    display:flex;
    flex-direction:column;
    align-items:center;
    justify-content:center;
    font-family:'Source Serif 4', Georgia, serif;
  }}
  .lockup {{ width:480px; margin-bottom:28px; }}
  .tagline {{
    font-size:38px;
    font-weight:600;
    color:{INK_DARK};
    letter-spacing:-0.01em;
  }}
</style></head>
<body>
  <img class="lockup" src="{lockup_svg_url}">
  <div class="tagline">{TAGLINE}</div>
</body>
</html>"""
    render_html_to_png(og_html, 1200, 630, PUBLIC / "og-default.png", chrome)

    # 7. github-social.png (1280x640, lockup on paper with tagline)
    github_html = f"""<!doctype html>
<html>
<head><meta charset="utf-8"><style>
  @font-face {{
    font-family: 'Source Serif 4';
    src: url('file://{font_file}') format('woff2');
  }}
  * {{ margin:0; padding:0; box-sizing:border-box; }}
  html, body {{
    width:1200px;
    height:640px;
    overflow:hidden;
    background:{PAPER_LIGHT};
    display:flex;
    flex-direction:column;
    align-items:center;
    justify-content:center;
    font-family:'Source Serif 4', Georgia, serif;
  }}
  .lockup {{ width:512px; margin-bottom:30px; }}
  .tagline {{
    font-size:40px;
    font-weight:600;
    color:{INK_DARK};
    letter-spacing:-0.01em;
  }}
</style></head>
<body>
  <img class="lockup" src="{lockup_svg_url}">
  <div class="tagline">{TAGLINE}</div>
</body>
</html>"""
    render_html_to_png(github_html, 1280, 640, PUBLIC / "github-social.png", chrome)


if __name__ == "__main__":
    generate_all()
    print("[gen_brand_assets] All brand assets rendered successfully.")
