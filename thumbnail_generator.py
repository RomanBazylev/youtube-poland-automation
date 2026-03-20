"""
Thumbnail generator for «Я в Польше» YouTube channel.
Composes eye-catching 1280×720 thumbnails with:
  - Pexels photo background (topic-relevant)
  - Dark gradient overlay for text contrast
  - Large bold text from LLM-generated thumbnail_text
  - Accent stripe and emoji badge
"""

import os
import random
import re
from io import BytesIO
from pathlib import Path
from typing import Optional

import requests
from PIL import Image, ImageDraw, ImageFont

THUMB_W, THUMB_H = 1280, 720

# ── Accent colours (YouTube-style vibrant palette) ─────────────────────
_ACCENT_COLORS = [
    (255, 59, 48),    # Red
    (255, 149, 0),    # Orange
    (0, 199, 190),    # Teal
    (88, 86, 214),    # Purple
    (255, 45, 85),    # Pink
    (52, 199, 89),    # Green
    (255, 204, 0),    # Yellow
]

_FLAG_EMOJI = "🇵🇱"

_PEXELS_FALLBACK_QUERIES = [
    "Poland city landscape",
    "Krakow old town",
    "Warsaw skyline",
    "European street cafe",
    "Poland nature",
]


# ── Resolve thumbnail text ────────────────────────────────────────────
def _clean_title_for_thumbnail(title: str) -> str:
    """Strip emoji, #shorts, and trim to fit as fallback thumbnail text."""
    text = re.sub(r'#\w+', '', title)
    text = re.sub(r'[^\w\s\-–—.,!?]', '', text)
    text = text.strip().strip('–—-').strip()
    words = text.split()
    if len(words) > 5:
        words = words[:5]
    return ' '.join(words).upper()


# ── Download Pexels photo ─────────────────────────────────────────────
def _download_pexels_photo(query: str) -> Optional[Image.Image]:
    """Download a landscape photo from Pexels for thumbnail background."""
    api_key = os.getenv("PEXELS_API_KEY")
    if not api_key:
        return None

    headers = {"Authorization": api_key}
    try:
        resp = requests.get(
            "https://api.pexels.com/v1/search",
            headers=headers,
            params={"query": query, "per_page": 15, "orientation": "landscape"},
            timeout=30,
        )
        resp.raise_for_status()
    except Exception as exc:
        print(f"[THUMB] Pexels search failed: {exc}")
        return None

    photos = resp.json().get("photos", [])
    if not photos:
        return None

    photo = random.choice(photos[:10])
    # Use 'large' size (typically ~1200-1900px wide)
    photo_url = photo.get("src", {}).get("large2x") or photo.get("src", {}).get("large")
    if not photo_url:
        return None

    try:
        img_resp = requests.get(photo_url, timeout=30)
        img_resp.raise_for_status()
        return Image.open(BytesIO(img_resp.content)).convert("RGB")
    except Exception as exc:
        print(f"[THUMB] Photo download failed: {exc}")
        return None


# ── Image composition ─────────────────────────────────────────────────
def _crop_cover(img: Image.Image, target_w: int, target_h: int) -> Image.Image:
    """Resize & crop image to exactly fill target dimensions (cover mode)."""
    src_ratio = img.width / img.height
    tgt_ratio = target_w / target_h

    if src_ratio > tgt_ratio:
        # Source is wider — fit by height, crop width
        new_h = target_h
        new_w = int(img.width * (target_h / img.height))
    else:
        # Source is taller — fit by width, crop height
        new_w = target_w
        new_h = int(img.height * (target_w / img.width))

    img = img.resize((new_w, new_h), Image.LANCZOS)
    left = (new_w - target_w) // 2
    top = (new_h - target_h) // 2
    return img.crop((left, top, left + target_w, top + target_h))


def _draw_gradient(img: Image.Image) -> Image.Image:
    """Apply a bottom-to-top dark gradient overlay."""
    overlay = Image.new("RGBA", img.size, (0, 0, 0, 0))
    draw = ImageDraw.Draw(overlay)

    gradient_start = int(THUMB_H * 0.25)  # gradient starts at 25% from top
    for y in range(gradient_start, THUMB_H):
        progress = (y - gradient_start) / (THUMB_H - gradient_start)
        alpha = int(180 * progress)  # max ~70% opacity at bottom
        draw.line([(0, y), (THUMB_W, y)], fill=(0, 0, 0, alpha))

    img_rgba = img.convert("RGBA")
    return Image.alpha_composite(img_rgba, overlay).convert("RGB")


def _find_font(size: int) -> ImageFont.FreeTypeFont:
    """Find DejaVu Sans Bold or fall back to default."""
    font_paths = [
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Linux/CI
        "C:/Windows/Fonts/arialbd.ttf",  # Windows fallback
        "/System/Library/Fonts/Helvetica.ttc",  # macOS fallback
    ]
    for fp in font_paths:
        if Path(fp).exists():
            return ImageFont.truetype(fp, size)
    return ImageFont.load_default()


def _draw_text_with_outline(
    draw: ImageDraw.Draw,
    xy: tuple,
    text: str,
    font: ImageFont.FreeTypeFont,
    fill: tuple,
    outline_color: tuple = (0, 0, 0),
    outline_width: int = 4,
):
    """Draw text with thick outline for readability."""
    x, y = xy
    for dx in range(-outline_width, outline_width + 1):
        for dy in range(-outline_width, outline_width + 1):
            if dx * dx + dy * dy <= outline_width * outline_width:
                draw.text((x + dx, y + dy), text, font=font, fill=outline_color)
    draw.text(xy, text, font=font, fill=fill)


def _wrap_text(text: str, font: ImageFont.FreeTypeFont, max_width: int) -> list[str]:
    """Split text into lines that fit within max_width."""
    words = text.split()
    lines = []
    current = ""
    for word in words:
        test = f"{current} {word}".strip()
        bbox = font.getbbox(test)
        if bbox[2] - bbox[0] <= max_width:
            current = test
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines or [text]


def compose_thumbnail(
    background: Optional[Image.Image],
    hook_text: str,
    accent_color: tuple,
    output_path: Path,
) -> Path:
    """Compose the final thumbnail image."""
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Background
    if background:
        img = _crop_cover(background, THUMB_W, THUMB_H)
    else:
        # Solid dark fallback
        img = Image.new("RGB", (THUMB_W, THUMB_H), (30, 30, 50))

    # Gradient overlay
    img = _draw_gradient(img)

    draw = ImageDraw.Draw(img)

    # Accent stripe on left edge
    stripe_w = 12
    draw.rectangle([(0, 0), (stripe_w, THUMB_H)], fill=accent_color)

    # Flag badge in top-right corner
    badge_font = _find_font(48)
    draw.text((THUMB_W - 70, 15), _FLAG_EMOJI, font=badge_font, fill=(255, 255, 255))

    # Hook text — large, bold, bottom-center
    text_area_w = THUMB_W - 120  # padding
    font_size = 82
    font = _find_font(font_size)
    lines = _wrap_text(hook_text, font, text_area_w)

    # If too many lines, reduce font size
    while len(lines) > 3 and font_size > 48:
        font_size -= 6
        font = _find_font(font_size)
        lines = _wrap_text(hook_text, font, text_area_w)

    # Calculate total text block height
    line_spacing = 10
    line_heights = []
    for line in lines:
        bbox = font.getbbox(line)
        line_heights.append(bbox[3] - bbox[1])
    total_text_h = sum(line_heights) + line_spacing * (len(lines) - 1)

    # Position: vertically centered in bottom 45% of image
    y_start = THUMB_H - total_text_h - 50

    for i, line in enumerate(lines):
        bbox = font.getbbox(line)
        line_w = bbox[2] - bbox[0]
        x = (THUMB_W - line_w) // 2
        y = y_start + sum(line_heights[:i]) + line_spacing * i

        _draw_text_with_outline(
            draw, (x, y), line, font,
            fill=(255, 255, 255),
            outline_color=(0, 0, 0),
            outline_width=5,
        )

    # Small accent underline below text
    underline_y = y_start + total_text_h + 15
    underline_w = min(total_text_h * 2, 300)
    underline_x = (THUMB_W - underline_w) // 2
    draw.rectangle(
        [(underline_x, underline_y), (underline_x + underline_w, underline_y + 5)],
        fill=accent_color,
    )

    # Save
    img.save(str(output_path), "JPEG", quality=95)
    print(f"[THUMB] Saved thumbnail: {output_path} ({THUMB_W}x{THUMB_H})")
    return output_path


# ── Public API ─────────────────────────────────────────────────────────
def generate_thumbnail(
    title: str,
    topic: str = "",
    output_path: Optional[Path] = None,
    thumbnail_text: str = "",
) -> Optional[Path]:
    """Full pipeline: resolve text → Pexels photo → compose → save JPEG."""
    if output_path is None:
        output_path = Path("build") / "thumbnail.jpg"

    print("[THUMB] Generating thumbnail...")

    # 1) Determine display text
    hook_text = thumbnail_text.strip().upper() if thumbnail_text.strip() else _clean_title_for_thumbnail(title)
    print(f"[THUMB] Text: {hook_text}")

    # 2) Download background photo
    pexels_query = "Poland " + random.choice(["city", "landscape", "street", "travel", "nature"])
    print(f"[THUMB] Pexels query: {pexels_query}")

    bg = _download_pexels_photo(pexels_query)
    if not bg:
        bg = _download_pexels_photo(random.choice(_PEXELS_FALLBACK_QUERIES))
    if bg:
        print(f"[THUMB] Background: {bg.size[0]}x{bg.size[1]}")
    else:
        print("[THUMB] No background photo, using solid color fallback")

    # 3) Compose
    accent = random.choice(_ACCENT_COLORS)
    return compose_thumbnail(bg, hook_text, accent, output_path)
