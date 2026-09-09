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
    candidates = [Path("C:/Windows/Fonts/impact.ttf") if bold else Path("C:/Windows/Fonts/arial.ttf"), Path("C:/Windows/Fonts/ARIALBD.TTF") if bold else Path("C:/Windows/Fonts/ARIAL.TTF")]
    for path in candidates:
        if path.exists(): return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()

async def download_image(url: str) -> Image.Image | None:
    if not url or not url.startswith(("http://", "https://")): return None
    try:
        timeout = aiohttp.ClientTimeout(total=20)
        async with aiohttp.ClientSession(timeout=timeout) as session:
            async with session.get(url) as response:
                if response.status != 200: return None
                return Image.open(io.BytesIO(await response.read())).convert("RGBA")
    except Exception: return None

def _cover(image: Image.Image, size: tuple[int, int]) -> Image.Image:
    return ImageOps.fit(image, size, method=Image.Resampling.LANCZOS, centering=(0.5, 0.38))

async def create_welcome_card(data: dict[str, Any], photo_url: str | None, approved: bool = False) -> Path | None:
    name = str(data.get("nombre") or data.get("name") or "Jugador")
    role = str(data.get("rol") or data.get("role") or "Jugador").upper()
    rank = str(data.get("rango") or data.get("rank") or "Por confirmar").upper()
    status = "APROBADA" if approved else "EN REVISIÓN"
    if TEMPLATE.exists(): canvas = Image.open(TEMPLATE).convert("RGBA")
    else:
        canvas = Image.new("RGBA", (1920, 1920), (8, 8, 8, 255)); draw = ImageDraw.Draw(canvas)
        draw.rectangle((18, 18, 1902, 1902), outline=(190, 255, 0, 255), width=8)
        draw.text((960, 100), "CROSAIM", anchor="mm", fill=(190, 255, 0), font=_font(92, True))
        draw.text((960, 260), "BIENVENIDO AL ROSTER", anchor="mm", fill="white", font=_font(120, True))
    player = await download_image(photo_url or "")
    if player: canvas.alpha_composite(_cover(player, (900, 1050)), (510, 720))
    draw = ImageDraw.Draw(canvas); lime = (190, 255, 0, 255); white = (245, 245, 245, 255)
    draw.text((125, 735), role, fill=lime, font=_font(54, True)); draw.text((125, 805), rank, fill=white, font=_font(72, True))
    draw.text((1440, 805), status, fill=lime, font=_font(58, True), anchor="mm"); draw.text((960, 1740), name, fill=white, font=_font(82, True), anchor="mm"); draw.text((960, 1840), "CROSAIM", fill=lime, font=_font(52, True), anchor="mm")
    safe = "".join(ch if ch.isalnum() or ch in "-_" else "_" for ch in name)[:50]
    output = OUTPUT_DIR / f"{safe or 'jugador'}_{'aprobada' if approved else 'revision'}.png"
    canvas.convert("RGB").save(output, "PNG", optimize=True)
    return output
