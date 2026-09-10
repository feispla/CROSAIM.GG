from __future__ import annotations

import io
from pathlib import Path
from typing import Any

import aiohttp
from PIL import Image, ImageDraw, ImageFont, ImageOps

ROOT = Path(__file__).parent
TEMPLATE = ROOT / "media" / "template.png"
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


def _fit_text(draw: ImageDraw.ImageDraw, text: str, max_width: int, start_size: int, bold: bool = True):
    size = start_size
    while size > 20:
        font = _font(size, bold)
        if draw.textbbox((0, 0), text, font=font)[2] <= max_width:
            return font
        size -= 2
    return _font(20, bold)


async def download_image(url: str) -> Image.Image | None:
    if not url or not url.startswith(("http://", "https://")):
        return None
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200:
                    return None
                return Image.open(io.BytesIO(await response.read())).convert("RGBA")
    except Exception:
        return None


def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.38))


async def create_welcome_card(data: dict[str, Any], photo_url: str | None, approved: bool = False) -> Path | None:
    name = str(data.get("nombre") or data.get("name") or "NOMBRE DEL JUGADOR").strip().upper()
    role = str(data.get("rol") or data.get("role") or "ROL").strip().upper()
    rank = str(data.get("rango") or data.get("rank") or "RANGO").strip().upper()
    status = "APROBADA" if approved else "EN REVISIÓN"

    canvas = Image.open(TEMPLATE).convert("RGBA") if TEMPLATE.exists() else Image.new("RGBA", (1920, 1920), "black")
    draw = ImageDraw.Draw(canvas)
    lime = (190, 255, 0, 255)
    white = (245, 245, 245, 255)

    # Dynamic text positions match the approved CROSAIM layout.
    title_font = _font(112, True)
    draw.text((960, 105), "BIENVENIDO", anchor="mm", fill=white, font=title_font)
    draw.text((960, 235), "AL ROSTER", anchor="mm", fill=lime, font=title_font)
    name_font = _fit_text(draw, name, 1540, 210, True)
    draw.text((960, 455), name, anchor="mm", fill=lime, font=name_font)
    draw.text((215, 785), role, anchor="mm", fill=lime, font=_font(52, True))
    draw.text((245, 875), rank, anchor="mm", fill=white, font=_fit_text(draw, rank, 330, 70, True))
    draw.text((1285, 875), status, anchor="mm", fill=lime, font=_fit_text(draw, status, 540, 58, True))
    draw.text((960, 1325), "CROSAIM", anchor="mm", fill=lime, font=_font(54, True))

    # If the application includes a photo, place it over the logo area; otherwise the template logo remains.
    player = await download_image(photo_url or "")
    if player:
        canvas.alpha_composite(_cover(player, (780, 780)), (570, 690))

    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)[:50]
    output = OUTPUT_DIR / f"{safe or 'jugador'}_{'aprobada' if approved else 'revision'}.png"
    canvas.convert("RGB").save(output, "PNG", optimize=True)
    return output
