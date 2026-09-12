from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from supabase import Client, create_client

APPLICATION_STATUSES = {
    "POSTULACIÓN",
    "REVISIÓN",
    "ENTREVISTA",
    "APROBADA",
    "RECHAZADA",
    "ROSTER",
    "TRYOUT",
}
STATUS_ALIASES = {
    "pendiente": "POSTULACIÓN",
    "postulacion": "POSTULACIÓN",
    "postulación": "POSTULACIÓN",
    "revision": "REVISIÓN",
    "revisión": "REVISIÓN",
    "en revision": "REVISIÓN",
    "en revisión": "REVISIÓN",
    "entrevista": "ENTREVISTA",
    "aprobada": "APROBADA",
    "rechazada": "RECHAZADA",
    "roster": "ROSTER",
    "tryout": "TRYOUT",
}

_client: Client | None = None


def client() -> Client:
    global _client
    if _client is None:
        url = os.environ.get("SUPABASE_URL")
        key = os.environ.get("SUPABASE_SERVICE_ROLE_KEY")
        if not url or not key:
            raise RuntimeError("Faltan SUPABASE_URL o SUPABASE_SERVICE_ROLE_KEY en .env")
        _client = create_client(url, key)
    return _client


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def canonical_status(status: str) -> str:
    candidate = (status or "").strip()
    if candidate.upper() in APPLICATION_STATUSES:
        return candidate.upper()
    normalized = " ".join(candidate.lower().replace("_", " ").split())
    if normalized in STATUS_ALIASES:
        return STATUS_ALIASES[normalized]
    raise ValueError(f"Estado CROSAIM no válido: {status!r}")


def append_audit_event(
    submission_id: str,
    *,
    previous_status: str | None,
    next_status: str,
    actor_discord_id: int | str | None,
    actor_type: str,
    source: str,
    detail: dict[str, Any] | None = None,
) -> None:
    client().table("postulaciones_auditoria").insert({
        "postulación_id": submission_id,
        "estado_anterior": previous_status,
        "estado_nuevo": next_status,
        "actor_discord_id": str(actor_discord_id) if actor_discord_id else None,
        "actor_tipo": actor_type,
        "fuente": source,
        "detalle": detail or {},
    }).execute()


def find_submission_by_review_message(message_id: int) -> dict[str, Any] | None:
    """Carga los datos completos para que los botones sobrevivan a reinicios del bot."""
    result = (
        client()
        .table("postulaciones")
        .select("id, nombre, discord_id, discord_username, rol, rango, descripcion, foto_url, payload_original, estado")
        .eq("discord_revision_message_id", str(message_id))
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def find_submission_by_message(message_id: int) -> dict[str, Any] | None:
    """Busca una postulación ya creada para un mensaje de Discord."""
    result = (
        client()
        .table("postulaciones")
        .select("id, estado, discord_revision_message_id, discord_aprobacion_message_id")
        .eq("discord_postulacion_message_id", str(message_id))
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None


def get_submission(submission_id: str) -> dict[str, Any] | None:
    result = client().table("postulaciones").select("id, estado").eq("id", submission_id).limit(1).execute()
    return result.data[0] if result.data else None


def save_submission(data: dict[str, Any], webhook_message_id: int | None = None, webhook_id: int | None = None) -> str:
    row = {
        "nombre": str(data.get("nombre") or data.get("name") or "Jugador"),
        "discord_id": str(data.get("discord_id") or data.get("id discord") or "") or None,
        "discord_username": str(data.get("discord_username") or data.get("usuario") or "") or None,
        "rol": str(data.get("rol") or data.get("role") or "") or None,
        "rango": str(data.get("rango") or data.get("rank") or "") or None,
        "region": str(data.get("region") or "") or None,
        "descripcion": str(data.get("descripcion") or data.get("description") or data.get("texto") or "") or None,
        "foto_url": str(data.get("foto_url") or "") or None,
        "estado": "POSTULACIÓN",
        "state_changed_at": now_iso(),
        "state_changed_by_type": "bot",
        "discord_webhook_id": str(webhook_id) if webhook_id else None,
        "discord_postulacion_message_id": str(webhook_message_id) if webhook_message_id else None,
        "payload_original": data,
    }
    result = client().table("postulaciones").insert(row).execute()
    if not result.data:
        raise RuntimeError("Supabase no devolvió la postulación insertada")
    submission_id = str(result.data[0]["id"])
    append_audit_event(
        submission_id,
        previous_status=None,
        next_status="POSTULACIÓN",
        actor_discord_id=None,
        actor_type="bot",
        source="discord",
        detail={"discord_message_id": str(webhook_message_id) if webhook_message_id else None},
    )
    return submission_id


def set_review_message(submission_id: str, message_id: int) -> None:
    client().table("postulaciones").update({
        "discord_revision_message_id": str(message_id),
        "updated_at": now_iso(),
    }).eq("id", submission_id).execute()


def set_status(
    submission_id: str,
    status: str,
    reviewer_id: int | str | None,
    *,
    approval_message_id: int | None = None,
    reason: str | None = None,
    source: str = "discord",
    actor_type: str = "staff",
    detail: dict[str, Any] | None = None,
) -> str:
    """Changes a state while preserving actor, timestamp and audit history."""
    next_status = canonical_status(status)
    current = get_submission(submission_id)
    if current is None:
        raise RuntimeError("No existe la postulación a actualizar")
    previous_status = canonical_status(str(current.get("estado") or "POSTULACIÓN"))
    timestamp = now_iso()
    row: dict[str, Any] = {
        "estado": next_status,
        "state_changed_at": timestamp,
        "state_changed_by_discord_id": str(reviewer_id) if reviewer_id else None,
        "state_changed_by_type": actor_type,
        "revisado_por_discord_id": str(reviewer_id) if reviewer_id else None,
        "reviewed_at": timestamp,
        "updated_at": timestamp,
    }
    state_timestamp_column = {
        "ENTREVISTA": "interview_at",
        "APROBADA": "approved_at",
        "RECHAZADA": "rejected_at",
        "ROSTER": "roster_at",
        "TRYOUT": "tryout_at",
    }.get(next_status)
    if state_timestamp_column:
        row[state_timestamp_column] = timestamp
    if approval_message_id:
        row["discord_aprobacion_message_id"] = str(approval_message_id)
    if reason:
        row["motivo_rechazo"] = reason[:1000]
    client().table("postulaciones").update(row).eq("id", submission_id).execute()
    append_audit_event(
        submission_id,
        previous_status=previous_status,
        next_status=next_status,
        actor_discord_id=reviewer_id,
        actor_type=actor_type,
        source=source,
        detail=detail or ({"reason": reason} if reason else {}),
    )
    return next_status
