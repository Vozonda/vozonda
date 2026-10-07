"""Episode cover image generation (#155).

Og-image extraction from HTML + Pillow template cover generation.
"""
import re
from pathlib import Path
from urllib.parse import urljoin

from .fetcher import guard_url, guarded_client


def extract_og_image(html: str, base_url: str) -> str | None:
    """Extract og:image URL from HTML.

    Returns absolute URL or None. Does NOT download the image.
    """
    m = re.search(
        r'<meta[^>]+property=["\x27]og:image["\x27][^>]+content=["\x27]([^"\x27]+)',
        html,
        re.IGNORECASE,
    )
    if m:
        return urljoin(base_url, m.group(1))

    m = re.search(
        r'<meta[^>]+name=["\x27]twitter:image["\x27][^>]+content=["\x27]([^"\x27]+)',
        html,
        re.IGNORECASE,
    )
    if m:
        return urljoin(base_url, m.group(1))

    return None


async def download_og_image(url: str, dest: Path) -> bool:
    """Download og:image to dest path. Returns True on success."""

    try:
        guard_url(url)
    except Exception:
        return False

    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/128.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        async with guarded_client(timeout=30, follow_redirects=True, headers=headers) as client:
            r = await client.get(url)
            if r.status_code != 200:
                return False
            content_type = r.headers.get("content-type", "")
            if "image" not in content_type and not url.lower().endswith((".png", ".jpg", ".jpeg", ".webp")):
                return False
            data = b""
            for chunk in r.iter_bytes():
                data += chunk
                if len(data) > 5 * 1024 * 1024:
                    return False
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return True
    except Exception:
        return False


STYLE_PALETTES: dict[str, tuple[str, str, str]] = {
    "balanced": ("#1a1a2e", "#e0e0e0", "#4a90d9"),
    "serious": ("#1c1c1c", "#f0f0f0", "#c0392b"),
    "casual": ("#2d3436", "#dfe6e9", "#00b894"),
    "witty": ("#2c3e50", "#ecf0f1", "#e74c3c"),
    "narration": ("#1a1a2e", "#e0e0e0", "#6c5ce7"),
    "educational": ("#0d1b2a", "#e0e0e0", "#1b9aaa"),
    "storyteller": ("#2c1810", "#f5e6d3", "#d4a574"),
    "asmr-adjacent": ("#2d2d3f", "#e8e0f0", "#b8a9c9"),
    "eli5": ("#fff9c4", "#333333", "#ff8a65"),
    "classic": ("#1a1a1a", "#f0f0f0", "#888888"),
}

DEFAULT_PALETTE = ("#1a1a2e", "#e0e0e0", "#4a90d9")


def generate_template_cover(
    title: str,
    style: str = "balanced",
    output: Path | None = None,
    size: int = 3000,
) -> Path:
    """Generate a deterministic cover image with Pillow.

    Returns the output path. Creates a 3000x3000 PNG with:
    - Background color from style palette
    - Title text (wrapped, centered)
    - Vozonda brand icon in a corner
    """
    from PIL import Image, ImageDraw, ImageFont

    if output is None:
        output = Path("/tmp/vozonda-cover.png")
    output.parent.mkdir(parents=True, exist_ok=True)

    bg_color, text_color, accent_color = STYLE_PALETTES.get(style, DEFAULT_PALETTE)

    img = Image.new("RGB", (size, size), bg_color)
    draw = ImageDraw.Draw(img)

    try:
        title_font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", 72)
    except OSError:
        try:
            title_font = ImageFont.truetype("/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf", 72)
        except OSError:
            title_font = ImageFont.load_default()

    max_width = size - 200
    lines = _wrap_text(title, title_font, max_width)

    line_height = 88
    title_block_h = len(lines) * line_height

    y_start = (size // 2) - (title_block_h // 2)
    for i, line in enumerate(lines):
        bbox = draw.textbbox((0, 0), line, font=title_font)
        w = bbox[2] - bbox[0]
        x = (size - w) // 2
        draw.text((x, y_start + i * line_height), line, fill=text_color, font=title_font)

    accent_y = y_start + title_block_h + 40
    draw.line([(size // 4, accent_y), (3 * size // 4, accent_y)], fill=accent_color, width=6)

    # Place the brand icon in a corner
    repo_root = Path(__file__).resolve().parents[4]
    icon_path = repo_root / "apps" / "web" / "public" / "icon-512.png"
    icon_size = max(48, int(size * 0.08))
    pad = max(16, int(size * 0.04))

    if icon_path.exists():
        try:
            icon = Image.open(icon_path).convert("RGBA")
            icon = icon.resize((icon_size, icon_size), Image.Resampling.LANCZOS)
            img.paste(icon, (pad, pad), icon)
        except (OSError, ValueError):  # silent: non-fatal fallback if icon file is unreadable
            pass

    img.save(output, "PNG")
    return output


def _wrap_text(text: str, font, max_width: int) -> list[str]:
    """Wrap text to fit within max_width using the given font."""
    from PIL import Image
    from PIL import ImageDraw as _ID

    img_dummy = Image.new("RGB", (1, 1))
    draw_dummy = _ID.Draw(img_dummy)

    words = text.split()
    lines: list[str] = []
    current_line = ""

    for word in words:
        test = f"{current_line} {word}".strip() if current_line else word
        bbox = draw_dummy.textbbox((0, 0), test, font=font)
        w = bbox[2] - bbox[0]
        if w <= max_width:
            current_line = test
        else:
            if current_line:
                lines.append(current_line)
            current_line = word

    if current_line:
        lines.append(current_line)

    return lines if lines else ["..."]
