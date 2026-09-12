import asyncio
from pathlib import Path

from PIL import Image

import image_generator


def test_create_welcome_card_uses_defaults_and_writes_png(tmp_path, monkeypatch):
    template = tmp_path / "template.png"
    Image.new("RGBA", (1920, 1920), "black").save(template)
    monkeypatch.setattr(image_generator, "TEMPLATE", template)
    monkeypatch.setattr(image_generator, "FALLBACK_TEMPLATE", template)
    monkeypatch.setattr(image_generator, "OUTPUT_DIR", tmp_path / "generated")

    result = asyncio.run(
        image_generator.create_welcome_card(
            {"nombre": "Ana/Prueba", "rol": "Duelista", "rango": "Diamante"},
            None,
            approved=True,
        )
    )

    assert result == tmp_path / "generated" / "ANA_PRUEBA_aprobada.png"
    assert result.exists()
    with Image.open(result) as output:
        assert output.format == "PNG"
        assert output.size == (1920, 1920)


def test_create_welcome_card_composites_member_photo(tmp_path, monkeypatch):
    template = tmp_path / "template.png"
    Image.new("RGBA", (1920, 1920), "black").save(template)
    photo = Image.new("RGBA", (100, 100), (255, 0, 0, 255))
    monkeypatch.setattr(image_generator, "TEMPLATE", template)
    monkeypatch.setattr(image_generator, "FALLBACK_TEMPLATE", template)
    monkeypatch.setattr(image_generator, "OUTPUT_DIR", tmp_path / "generated")
    async def fake_download(_url):
        return photo
    monkeypatch.setattr(image_generator, "download_image", fake_download)

    result = asyncio.run(
        image_generator.create_welcome_card(
            {"nombre": "Jugador", "rol": "Controller", "rango": "Oro"},
            "https://example.com/player.png",
            approved=False,
        )
    )

    assert result.name == "JUGADOR_revision.png"
    with Image.open(result) as output:
        assert output.getpixel((960, 1080))[:3] == (255, 0, 0)


def test_download_image_rejects_non_http_urls():
    assert asyncio.run(image_generator.download_image("not-a-url")) is None


def test_create_welcome_card_handles_long_labels_without_leaving_canvas(tmp_path, monkeypatch):
    template = tmp_path / "template.png"
    Image.new("RGBA", (1920, 1920), "black").save(template)
    monkeypatch.setattr(image_generator, "TEMPLATE", template)
    monkeypatch.setattr(image_generator, "FALLBACK_TEMPLATE", template)
    monkeypatch.setattr(image_generator, "OUTPUT_DIR", tmp_path / "generated")

    result = asyncio.run(
        image_generator.create_welcome_card(
            {
                "nombre": "Jugador Con Un Alias Excepcionalmente Largo Para Validar El Ajuste Visual",
                "rol": "Controlador Estratégico de Utilidad",
                "rango": "Ascendant 3 Con Pico Competitivo",
                "estado": "ENTREVISTA PROGRAMADA",
            },
            None,
            approved=False,
        )
    )

    with Image.open(result) as output:
        assert output.size == (1920, 1920)
        bbox = output.getbbox()
        assert bbox is not None
        assert 0 <= bbox[0] < bbox[2] <= 1920
        assert 0 <= bbox[1] < bbox[3] <= 1920
