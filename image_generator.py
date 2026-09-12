from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).parent
TEMPLATE = ROOT / "media" / "template_clean.png"
FALLBACK_TEMPLATE = ROOT / "media" / "template.png"
OUTPUT_DIR = ROOT / "media" / "generated"
OUTPUT_DIR.mkdir(parents=True, exist_ok=True)


def _font(size: int, bold: bool = False):
    candidates = [
        Path("C:/Windows/Fonts/impact.ttf") if bold else Path("C:/Windows/Fonts/arial.ttf"),
        Path("C:/Windows/Fonts/ARIALBD.TTF") if bold else Path("C:/Windows/Fonts/ARIAL.TTF"),
        Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf") if bold else Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, start_size: int, *, min_size: int = 18, bold: bool = True):
    size = start_size
    while size > min_size:
        font = _font(size, bold)
        bbox = draw.textbbox((0, 0), text, font=font)
        if bbox[2] - bbox[0] <= max_width:
            return font
        size -= 2
    return _font(min_size, bold)


def _ellipsize(draw: ImageDraw.ImageDraw, text: str, max_width: int, font: ImageFont.FreeTypeFont) -> str:
    if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
        return text
    candidate = text
    while candidate and draw.textbbox((0, 0), candidate + "…", font=font)[2] > max_width:
        candidate = candidate[:-1]
    return (candidate.rstrip() or "—") + "…"


def _safe_label(value: Any, fallback: str, limit: int = 120) -> str:
    label = str(value or fallback).replace("\n", " ").strip().upper()
    return " ".join(label.split())[:limit] or fallback


async def download_image(url: str) -> Image.Image | None:
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url, allow_redirects=True) as response:
                content_type = response.headers.get("content-type", "")
                if response.status != 200 or not content_type.startswith("image/"):
                    return None
                payload = await response.read()
                if len(payload) > 8 * 1024 * 1024:
                    return None
                return Image.open(io.BytesIO(payload)).convert("RGBA")
    except Exception:
        return None


def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.38))


def _draw_centered_label(draw: ImageDraw.ImageDraw, *, center: tuple[int, int], text: str, max_width: int, start_size: int, color: tuple[int, int, int, int], min_size: int = 18) -> None:
    font = _fit_text(draw, text, max_width, start_size, min_size=min_size)
    label = _ellipsize(draw, text, max_width, font)
    draw.text(center, label, anchor="mm", fill=color, font=font)


async def create_welcome_card(data: dict[str, Any], photo_url: str | None, approved: bool = False) -> Path | None:
    name = _safe_label(data.get("nombre") or data.get("name") or data.get("playerName"), "NOMBRE DEL JUGADOR")
    role = _safe_label(data.get("rol") or data.get("role"), "ROL")
    rank = _safe_label(data.get("rango") or data.get("rank"), "RANGO")
    raw_status = data.get("status") or data.get("estado")
    status = "APROBADA" if approved else _safe_label(raw_status, "EN REVISIÓN", limit=32)

    source_template = TEMPLATE if TEMPLATE.exists() else FALLBACK_TEMPLATE
    canvas = Image.open(source_template).convert("RGBA") if source_template.exists() else Image.new("RGBA", (1920, 1920), "black")
    draw = ImageDraw.Draw(canvas)
    lime = (190, 255, 0, 255)
    white = (245, 245, 245, 255)

    # All labels are constrained to explicit safe areas; no caller-controlled text
    # can extend outside the canvas or overlap the player image.
    _draw_centered_label(draw, center=(960, 105), text="BIENVENIDO", max_width=1480, start_size=112, color=white, min_size=54)
    _draw_centered_label(draw, center=(960, 235), text="AL ROSTER", max_width=1480, start_size=112, color=lime, min_size=54)
    _draw_centered_label(draw, center=(960, 455), text=name, max_width=1540, start_size=210, color=lime, min_size=34)
    _draw_centered_label(draw, center=(235, 785), text=role, max_width=390, start_size=52, color=lime, min_size=18)
    _draw_centered_label(draw, center=(245, 875), text=rank, max_width=360, start_size=70, color=white, min_size=18)
    _draw_centered_label(draw, center=(1285, 875), text=status, max_width=540, start_size=58, color=lime, min_size=18)
    _draw_centered_label(draw, center=(960, 1325), text="CROSAIM", max_width=680, start_size=54, color=lime, min_size=28)

    player = await download_image(photo_url or "")
    if player:
        canvas.alpha_composite(_cover(player, (780, 780)), (570, 690))

    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)[:50]
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output = OUTPUT_DIR / f"{safe or 'jugador'}_{'aprobada' if approved else 'revision'}.png"
    canvas.convert("RGB").save(output, "PNG", optimize=True)
    return output
