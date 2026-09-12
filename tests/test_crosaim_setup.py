import pytest

from crosaim_setup import (
    APPLICATION_STATUSES,
    BUSINESS_ROLE_SPECS,
    LAYOUT,
    RECRUITING_ROLE_KEYS,
    ROLE_CAPABILITIES,
    can_transition,
    canonical_status,
    desired_state_hash,
    has_capability,
    normalize,
)


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


def test_exactly_nine_business_roles_are_declared_without_administrator():
    assert [role.key for role in BUSINESS_ROLE_SPECS] == [
        "SUPER_ADMIN",
        "ADMIN",
        "MANAGER",
        "COACH",
        "SCOUT",
        "CONTENT",
        "PLAYER",
        "TRYOUT",
        "VIEWER",
    ]
    assert len({normalize(role.name) for role in BUSINESS_ROLE_SPECS}) == 9
    assert len({role.position for role in BUSINESS_ROLE_SPECS}) == 9
    assert all("administrator" not in role.capabilities for role in BUSINESS_ROLE_SPECS)


def test_recruiting_capabilities_follow_the_business_role_matrix():
    assert has_capability(RECRUITING_ROLE_KEYS, "applications.review")
    assert has_capability(("ADMIN",), "discord.reconcile")
    assert has_capability(("CONTENT",), "content.publish")
    assert not has_capability(("PLAYER", "TRYOUT", "VIEWER"), "applications.review")
    assert ROLE_CAPABILITIES["VIEWER"] == frozenset({"dashboard.view"})


def test_layout_keys_are_unique_and_duplicate_display_names_are_scoped_by_category():
    category_keys = [category.key for category in LAYOUT]
    channel_keys = [channel.key for category in LAYOUT for channel in category.channels]
    assert len(category_keys) == len(set(category_keys))
    assert len(channel_keys) == len(set(channel_keys))
    results = [(category.key, channel.key) for category in LAYOUT for channel in category.channels if normalize(channel.name) == "resultados"]
    assert results == [("competitive", "competitive_results"), ("tournaments", "tournament_results")]


def test_desired_state_hash_is_stable_for_a_fixed_contract():
    assert desired_state_hash() == desired_state_hash()
    assert len(desired_state_hash()) == 16


def test_private_recruiting_channels_are_explicit_in_the_layout():
    review = next(channel for category in LAYOUT for channel in category.channels if channel.key == "review")
    interviews = next(channel for category in LAYOUT for channel in category.channels if channel.key == "interviews")
    assert review.access == "recruiting"
    assert interviews.access == "recruiting"
