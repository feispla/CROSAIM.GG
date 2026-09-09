from __future__ import annotations

import os
from datetime import datetime, timezone
from typing import Any

from supabase import Client, create_client

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
        "discord_webhook_id": str(webhook_id) if webhook_id else None,
        "discord_postulacion_message_id": str(webhook_message_id) if webhook_message_id else None,
        "payload_original": data,
    }
    result = client().table("postulaciones").insert(row).execute()
    if not result.data:
        raise RuntimeError("Supabase no devolvió la postulación insertada")
    return str(result.data[0]["id"])


def set_review_message(submission_id: str, message_id: int) -> None:
    client().table("postulaciones").update({
        "discord_revision_message_id": str(message_id)
    }).eq("id", submission_id).execute()


def set_status(submission_id: str, status: str, reviewer_id: int, approval_message_id: int | None = None, reason: str | None = None) -> None:
    row: dict[str, Any] = {
        "estado": status,
        "revisado_por_discord_id": str(reviewer_id),
        "reviewed_at": datetime.now(timezone.utc).isoformat(),
    }
    if approval_message_id:
        row["discord_aprobacion_message_id"] = str(approval_message_id)
    if reason:
        row["motivo_rechazo"] = reason
    client().table("postulaciones").update(row).eq("id", submission_id).execute()
