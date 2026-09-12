import pytest

from crosaim_setup import APPLICATION_STATUSES, LAYOUT, can_transition, canonical_status, normalize


def test_layout_contains_the_required_interview_voice_channel_once():
    voice_channels = [channel for category in LAYOUT for channel in category.channels if channel.key == "interview_voice"]
    assert len(voice_channels) == 1
    assert voice_channels[0].name == "𝑽𝑨𝑳𝑶𝑹𝑨𝑵𝑻"


def test_statuses_are_canonical_and_transitions_are_bounded():
    assert set(APPLICATION_STATUSES) == {"POSTULACIÓN", "REVISIÓN", "ENTREVISTA", "APROBADA", "RECHAZADA", "ROSTER", "TRYOUT"}
    assert canonical_status("pendiente") == "POSTULACIÓN"
    assert canonical_status("en revision") == "REVISIÓN"
    assert can_transition("REVISIÓN", "ENTREVISTA")
    assert can_transition("ENTREVISTA", "TRYOUT")
    assert not can_transition("RECHAZADA", "ROSTER")


def test_normalize_reuses_decorated_existing_channel_names():
    assert normalize("🖥️𝗣𝗼𝘀𝘁𝘂𝗹𝗮𝗰𝗶𝗼𝗻") == "postulacion"
    assert normalize("𝑽𝑨𝑳𝑶𝑹𝑨𝑵𝑻") == "valorant"


def test_invalid_status_is_rejected():
    with pytest.raises(ValueError):
        canonical_status("publicada")
