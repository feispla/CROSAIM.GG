from __future__ import annotations

import logging
import json
import os
import re
import hashlib
import hmac
import secrets
import time
from typing import Any

import discord
from discord.ext import commands, tasks
import aiohttp
from dotenv import load_dotenv

from crosaim_setup import (
    LAYOUT,
    BUSINESS_ROLE_SPECS,
    can_manage_recruiting,
    canonical_status,
    load_runtime_channel_id,
    load_runtime_role_id,
    normalize,
    register_crosaim_admin_cog,
)
from image_generator import create_welcome_card
from supabase_db import find_submission_by_message, find_submission_by_review_message, save_submission, set_review_message, set_status

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
POSTULACION_CHANNEL_ID = int(os.getenv("POSTULACION_CHANNEL_ID", "0"))
REVISION_CHANNEL_ID = int(os.getenv("REVISION_CHANNEL_ID", "0"))
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
APROBACION_CHANNEL_ID = int(os.getenv("APROBACION_CHANNEL_ID", "0"))
CLIPS_CHANNEL_ID = int(os.getenv("CLIPS_CHANNEL_ID", "0"))
INTERVIEW_VOICE_CHANNEL_ID = int(os.getenv("INTERVIEW_VOICE_CHANNEL_ID", "0"))
INTERVIEW_NOTICE_CHANNEL_ID = int(os.getenv("INTERVIEW_NOTICE_CHANNEL_ID", "0"))
CROSAIM_WEB_BASE_URL = os.getenv("CROSAIM_WEB_BASE_URL", "https://crosaimdash-h9bxzuxs.manus.space").rstrip("/")
CROSAIM_BOT_SYNC_SECRET = os.getenv("CROSAIM_BOT_SYNC_SECRET", "")
# Optional: leave empty to accept any webhook message arriving in the postulation channel.
POSTULACION_WEBHOOK_ID = int(os.getenv("POSTULACION_WEBHOOK_ID", "0") or "0")
if not TOKEN:
    raise RuntimeError("Falta DISCORD_BOT_TOKEN en .env")
intents = discord.Intents.default()
intents.message_content = True
intents.members = True
bot = commands.Bot(command_prefix="!", intents=intents)


def get_crosaim_channel(key: str) -> discord.abc.GuildChannel | None:
    """Resolves an environment ID first and the idempotent setup registry second."""
    configured_id = load_runtime_channel_id(key)
    channel = bot.get_channel(configured_id) if configured_id else None
    if channel:
        return channel
    for category_spec in LAYOUT:
        for spec in category_spec.channels:
            if spec.key != key:
                continue
            candidates = (spec.name, spec.key, *spec.aliases)
            for existing in bot.get_all_channels():
                if existing.type == spec.kind and any(normalize(existing.name) == normalize(candidate) for candidate in candidates):
                    return existing
    return None


def get_text_channel(key: str) -> discord.TextChannel | None:
    channel = get_crosaim_channel(key)
    return channel if isinstance(channel, discord.TextChannel) else None


async def write_audit_log(action: str, detail: str, *, level: str = "info") -> None:
    channel = get_text_channel("audit") or get_text_channel("bot_logs")
    if not channel:
        logging.info("AUDIT [%s] %s — %s", level.upper(), action, detail)
        return
    icon = {"info": "ℹ️", "warning": "⚠️", "error": "❌", "success": "✅"}.get(level, "ℹ️")
    try:
        await channel.send(
            f"{icon} **CROSAIM · {action}**\n{detail}",
            allowed_mentions=discord.AllowedMentions.none(),
        )
    except discord.HTTPException:
        logging.exception("No se pudo publicar auditoría Discord")


def value(data: dict[str, Any], *keys: str, default: str = "Por confirmar") -> str:
    for key in keys:
        raw = data.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return default


def signed_sync_headers(method: str, path: str, body: dict[str, Any] | None = None) -> tuple[dict[str, str], str]:
    """Creates a replay-resistant service-to-service request signature."""
    if not CROSAIM_BOT_SYNC_SECRET:
        raise RuntimeError("Falta CROSAIM_BOT_SYNC_SECRET")
    serialized = "" if body is None else json.dumps(body, ensure_ascii=False, separators=(",", ":"))
    timestamp = str(int(time.time() * 1000))
    nonce = secrets.token_hex(16)
    body_hash = hashlib.sha256(serialized.encode("utf-8")).hexdigest()
    signing_payload = "\n".join((method.upper(), path, timestamp, nonce, body_hash))
    signature = hmac.new(CROSAIM_BOT_SYNC_SECRET.encode("utf-8"), signing_payload.encode("utf-8"), hashlib.sha256).hexdigest()
    return {
        "Content-Type": "application/json",
        # Transitional compatibility: the Control Center can accept this while
        # CROSAIM_SIGNED_SYNC_REQUIRED=false during the coordinated rollout.
        "x-crosaim-sync-secret": CROSAIM_BOT_SYNC_SECRET,
        "x-crosaim-sync-key-id": "v1",
        "x-crosaim-sync-timestamp": timestamp,
        "x-crosaim-sync-nonce": nonce,
        "x-crosaim-sync-body-sha256": body_hash,
        "x-crosaim-sync-signature": signature,
    }, serialized


def parse_submission(message: discord.Message) -> dict[str, Any]:
    data: dict[str, Any] = {"texto": message.content or ""}

    def normalize_key(raw_key: str) -> str:
        return re.sub(r"[^a-z0-9]+", " ", raw_key.lower()).strip()

    def store_field(raw_key: str, raw_value: str) -> None:
        key = normalize_key(raw_key)
        value_text = str(raw_value).strip()
        if not value_text:
            return
        data[key] = value_text
        aliases = {
            "jugador": "nombre", "player": "nombre", "nombre": "nombre",
            "nombre del jugador": "nombre", "name": "nombre", "usuario": "nombre",
            "rol": "rol", "role": "rol", "posicion": "rol", "posición": "rol",
            "rango": "rango", "rank": "rango", "elo": "rango",
            "discord id": "discord_id", "id discord": "discord_id",
            "discord_id": "discord_id", "id": "discord_id",
            "discord": "discord_username", "discord username": "discord_username",
            "usuario de discord": "discord_username", "nombre de discord": "discord_username",
            "contacto": "contact", "contact": "contact",
            "mensaje": "mensaje", "message": "mensaje",
        }
        if key in aliases:
            data.setdefault(aliases[key], value_text)

    def parse_labeled_text(text: str) -> None:
        for line in (text or "").splitlines():
            match = re.match(r"\s*(?:[-•*]\s*)?([^:：\-]{2,40})\s*[:：\-]\s*(.+?)\s*$", line)
            if match:
                store_field(match.group(1), match.group(2))

    for embed in message.embeds:
        if embed.title:
            data.setdefault("titulo", embed.title)
            parse_labeled_text(embed.title)
        if embed.description:
            data.setdefault("descripcion", embed.description)
            parse_labeled_text(embed.description)
        for field in embed.fields:
            store_field(field.name, field.value)
            parse_labeled_text(field.value)
        if embed.image and embed.image.url:
            data.setdefault("foto_url", embed.image.url)
        if embed.thumbnail and embed.thumbnail.url:
            data.setdefault("foto_url", embed.thumbnail.url)
    for attachment in message.attachments:
        if attachment.content_type and attachment.content_type.startswith("image/"):
            data.setdefault("foto_url", attachment.url)
    parse_labeled_text(message.content or "")
    return data


def find_player_mention(data: dict[str, Any], content: str) -> str | None:
    mention = re.search(r"<@!?\d{15,22}>", content or "")
    if mention:
        return mention.group(0)
    for key in ("discord_id", "discord id", "id discord", "usuario_id"):
        value_found = str(data.get(key, "")).strip()
        if value_found.isdigit():
            return f"<@{value_found}>"
    return None


async def sync_application_to_web(data: dict[str, Any], message: discord.Message) -> str | None:
    if not CROSAIM_BOT_SYNC_SECRET:
        logging.warning("No se sincroniza la postulación web: falta CROSAIM_BOT_SYNC_SECRET")
        return None
    discord_id = str(data.get("discord_id") or "").strip()
    mention = re.search(r"<@!?(\d{15,22})>", message.content or "")
    if not discord_id and mention:
        discord_id = mention.group(1)
    payload = {
        "discordMessageId": str(message.id),
        "playerName": value(data, "nombre", "name", default="Jugador"),
        "discordUsername": value(data, "discord_username", "usuario de discord", "discord", default=message.author.name),
        "discordUserId": discord_id or None,
        "contact": value(data, "contact", "contacto", default=""),
        "role": value(data, "rol", "role", default="Por confirmar"),
        "rank": value(data, "rango", "rank", default="Por confirmar"),
        "message": value(data, "mensaje", "message", "descripcion", "texto", default="Postulación recibida desde Discord."),
    }
    headers, serialized = signed_sync_headers("POST", "/api/discord/applications", payload)
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{CROSAIM_WEB_BASE_URL}/api/discord/applications",
            headers=headers,
            data=serialized,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status >= 300:
                raise RuntimeError(f"web application sync HTTP {response.status}: {await response.text()}")
            response_data = await response.json()
            return str(response_data.get("publicLookupNumber") or "") or None


async def acknowledge_web_event(event_id: int, lease_token: str, ok: bool, error: str | None = None) -> None:
    if not CROSAIM_BOT_SYNC_SECRET:
        raise RuntimeError("Falta CROSAIM_BOT_SYNC_SECRET")
    payload = {"ok": ok, "leaseToken": lease_token}
    if error:
        payload["error"] = error[:500]
    headers, serialized = signed_sync_headers("POST", f"/api/discord/events/{event_id}/ack", payload)
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{CROSAIM_WEB_BASE_URL}/api/discord/events/{event_id}/ack",
            headers=headers,
            data=serialized,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status >= 300:
                raise RuntimeError(f"ack HTTP {response.status}")


def event_mention(payload: dict[str, Any]) -> str:
    discord_id = str(payload.get("discordUserId") or "").strip()
    return f"<@{discord_id}>" if discord_id.isdigit() else f"**{payload.get('discordUsername') or 'Jugador'}**"


def event_summary(payload: dict[str, Any]) -> str:
    return (
        f"**Jugador:** {payload.get('playerName') or 'No indicado'}\n"
        f"**Discord:** {payload.get('discordUsername') or 'No indicado'}\n"
        f"**Rol:** {payload.get('role') or 'No indicado'} · **Rango:** {payload.get('rank') or 'No indicado'}"
    )


def web_profile_summary(payload: dict[str, Any]) -> str:
    socials = payload.get("socials") or payload.get("redesSociales") or {}
    if isinstance(socials, dict):
        social_text = " · ".join(f"{key}: {value}" for key, value in socials.items() if value)
    else:
        social_text = str(socials)
    lines = [event_summary(payload)]
    for label, key in (("Región", "region"), ("Disponibilidad", "availability"), ("Discord ID", "discordUserId")):
        if payload.get(key):
            lines.append(f"**{label}:** {payload[key]}")
    if social_text:
        lines.append(f"**Redes:** {social_text}")
    if payload.get("bio") or payload.get("description"):
        lines.append(f"**Descripción:** {payload.get('bio') or payload.get('description')}")
    return "\n".join(lines)


async def move_member_to_interview_voice(payload: dict[str, Any]) -> str:
    discord_id = str(payload.get("discordUserId") or "").strip()
    if not discord_id.isdigit():
        await write_audit_log("ENTREVISTA", "No se pudo mover al candidato: falta Discord ID válido.", level="warning")
        return "No se pudo mover automáticamente: falta un ID de Discord válido."
    guild = bot.get_guild(GUILD_ID) if GUILD_ID else None
    voice_channel = get_crosaim_channel("interview_voice")
    if not guild or not isinstance(voice_channel, discord.VoiceChannel):
        await write_audit_log("ENTREVISTA", "No se pudo mover al candidato: canal 𝑽𝑨𝑳𝑶𝑹𝑨𝑵𝑻 o servidor no disponible.", level="error")
        return "No se pudo mover automáticamente: canal o servidor no disponible."
    try:
        member = guild.get_member(int(discord_id)) or await guild.fetch_member(int(discord_id))
        if not member.voice or not member.voice.channel:
            await write_audit_log("ENTREVISTA", f"{member.mention} no estaba conectado a voz; no se intentó moverlo.", level="warning")
            return "El candidato debe entrar primero a un canal de voz para poder moverlo."
        await member.move_to(voice_channel, reason="Candidato CROSAIM pasó a entrevista")
        await write_audit_log("ENTREVISTA", f"{member.mention} fue movido a {voice_channel.mention}.", level="success")
        return f"Candidato movido a {voice_channel.mention}."
    except discord.Forbidden:
        await write_audit_log("ENTREVISTA", "Discord denegó Mover miembros o el rol del bot está por debajo del candidato.", level="error")
        return "Falta el permiso Mover miembros o el bot está debajo del candidato en la jerarquía."
    except discord.NotFound:
        await write_audit_log("ENTREVISTA", f"El Discord ID {discord_id} no es miembro del servidor.", level="warning")
        return "El ID de Discord no pertenece a un miembro de este servidor."
    except Exception as error:
        logging.exception("No se pudo mover al candidato al canal de entrevista")
        await write_audit_log("ENTREVISTA", f"Error controlado al mover candidato: {error}", level="error")
        return f"No se pudo mover automáticamente: {error}"


async def deliver_web_event(event: dict[str, Any]) -> None:
    event_type = str(event.get('eventType') or "")
    raw_payload = event.get("payload") or {}
    payload = raw_payload if isinstance(raw_payload, dict) else json.loads(str(raw_payload))
    event_id = event.get("id", "?")
    if event_type in {"application_submitted", "application_created", "profile_updated", "player_profile_updated"}:
        channel = get_text_channel("review")
        if not channel:
            raise RuntimeError("No encuentro el canal CROSAIM de revisión")
        title = "📝 **NUEVA POSTULACIÓN DESDE LA WEB**" if "application" in event_type else "🔄 **PERFIL ACTUALIZADO DESDE LA WEB**"
        await channel.send(
            f"{title}\n{web_profile_summary(payload)}\n`evento:{event_id}`",
            allowed_mentions=discord.AllowedMentions.none(),
        )
    elif event_type == "clip_uploaded":
        channel = get_text_channel("clips")
        if not channel:
            raise RuntimeError("No encuentro el canal CROSAIM de clips")
        await channel.send(
            f"**NUEVO CLIP CROSAIM**\n**Archivo:** {payload.get('name', 'clip')}\n"
            f"**Tamaño:** {float(payload.get('size', 0)) / (1024 * 1024):.1f} MB\n"
            f"**Abrir clip:** {payload.get('url', '')}\n`evento:{event_id}`",
            allowed_mentions=discord.AllowedMentions.none(),
        )
    elif event_type == "application_interview":
        notice_channel = get_text_channel("interviews") or get_text_channel("review") or get_text_channel("applications")
        if not notice_channel:
            raise RuntimeError("No encuentro canal de aviso para entrevista")
        move_result = await move_member_to_interview_voice(payload)
        mention = event_mention(payload)
        interview_voice = get_crosaim_channel("interview_voice")
        target = interview_voice.mention if interview_voice else "𝑽𝑨𝑳𝑶𝑹𝑨𝑵𝑻 (no disponible)"
        text = f"🎙️ **ENTREVISTA CROSAIM**\n{mention}\n{event_summary(payload)}\n**Voz:** {move_result}\nCanal objetivo: {target}\n`evento:{event_id}`"
        await notice_channel.send(text, allowed_mentions=discord.AllowedMentions(users=True))
    elif event_type == "application_approved":
        channel = get_text_channel("roster")
        if not channel:
            raise RuntimeError("No encuentro el canal CROSAIM de roster")
        image_path = await create_welcome_card(payload, payload.get("photoUrl") or payload.get("foto_url"), approved=True)
        await channel.send(content=f"✅ **POSTULACIÓN APROBADA DESDE CROSAIM**\n{event_mention(payload)}\n{event_summary(payload)}\n`evento:{event_id}`", file=discord.File(image_path) if image_path else None, allowed_mentions=discord.AllowedMentions(users=True))
    elif event_type == "application_rejected":
        channel = get_text_channel("review")
        if not channel:
            raise RuntimeError("No encuentro el canal CROSAIM de revisión")
        await channel.send(f"❌ **Postulación rechazada desde el panel**\n{event_summary(payload)}\n`evento:{event_id}`", allowed_mentions=discord.AllowedMentions.none())
    elif event_type == "roster_tryout":
        channel = get_text_channel("tryouts") or get_text_channel("roster")
        if not channel:
            raise RuntimeError("No encuentro canal para avisar el tryout")
        role_result = await assign_application_role(payload, "TRYOUT")
        await channel.send(f"🟣 **NUEVO TRYOUT EN PLANTILLA**\n{event_summary(payload)}\n**Discord:** {role_result}\n`evento:{event_id}`", allowed_mentions=discord.AllowedMentions.none())
    elif event_type in {"player_joined", "player_left", "role_updated"}:
        channel = get_text_channel("general") or get_text_channel("audit")
        if not channel:
            raise RuntimeError("No encuentro un canal de comunidad para el evento")
        role_result = ""
        if event_type == "role_updated":
            target_role = "PLAYER" if str(payload.get("status") or "").upper() == "ROSTER" else "TRYOUT" if str(payload.get("status") or "").upper() == "TRYOUT" else ""
            if target_role:
                role_result = await assign_application_role(payload, target_role, remove_roles=("TRYOUT",) if target_role == "PLAYER" else ())
        await channel.send(f"👥 **CROSAIM · {event_type.replace('_', ' ').upper()}**\n{event_summary(payload)}\n**Discord:** {role_result}\n`evento:{event_id}`", allowed_mentions=discord.AllowedMentions.none())
    elif event_type in {"tournament_created", "tournament_updated", "tournament_result"}:
        channel = get_text_channel("tournament_announcements") or get_text_channel("tournament_results")
        if not channel:
            raise RuntimeError("No encuentro el canal de torneos")
        title = str(payload.get("title") or payload.get("name") or "Actualización de torneo")
        await channel.send(f"🏆 **CROSAIM · {event_type.replace('_', ' ').upper()}**\n**{title}**\n{payload.get('detail') or payload.get('description') or ''}\n`evento:{event_id}`", allowed_mentions=discord.AllowedMentions.none())
    elif event_type in {"system_error", "sync_error"}:
        channel = get_text_channel("bot_alerts") or get_text_channel("audit")
        if not channel:
            raise RuntimeError("No encuentro el canal de alertas del bot")
        await channel.send(f"⚠️ **CROSAIM · {event_type.upper()}**\n{payload.get('message') or payload.get('error') or 'Error no especificado'}\n`evento:{event_id}`", allowed_mentions=discord.AllowedMentions.none())
    else:
        raise RuntimeError(f"Tipo de evento no soportado: {event_type}")


@tasks.loop(seconds=8)
async def poll_web_events() -> None:
    if not CROSAIM_BOT_SYNC_SECRET:
        return
    try:
        headers, _ = signed_sync_headers("GET", "/api/discord/events")
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{CROSAIM_WEB_BASE_URL}/api/discord/events",
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status != 200:
                    logging.warning("Web event polling returned HTTP %s", response.status)
                    return
                events = await response.json()
        for event in events[:20]:
            event_id = int(event["id"])
            lease_token = str(event.get("leaseToken") or "")
            if len(lease_token) < 16:
                logging.error("Evento web %s no tiene un lease válido; no se entrega.", event_id)
                continue
            try:
                await deliver_web_event(event)
                await acknowledge_web_event(event_id, lease_token, True)
                logging.info("Evento web %s entregado en Discord", event_id)
            except Exception as error:
                logging.exception("No se pudo entregar evento web %s", event_id)
                try:
                    await acknowledge_web_event(event_id, lease_token, False, str(error))
                except Exception:
                    logging.exception("No se pudo confirmar fallo del evento %s", event_id)
    except Exception:
        logging.exception("Error consultando eventos de CROSAIM")


@poll_web_events.before_loop
async def before_poll_web_events() -> None:
    await bot.wait_until_ready()


def approval_description(data: dict[str, Any]) -> str:
    name = value(data, "nombre", "name", default="Jugador")
    role = value(data, "rol", "role")
    rank = value(data, "rango", "rank")
    return (
        f"¡Bienvenido al roster, {name}!\n\n"
        f"Nos complace anunciar oficialmente la incorporación de {name} a CROSAIM.\n\n"
        f"**Rol:** {role}\n**Rango:** {rank}\n**Estado:** Aprobado\n\n"
        "A partir de ahora forma parte de nuestra familia competitiva. "
        "Le deseamos muchos éxitos, grandes partidas y el mejor desempeño "
        "representando los colores de CROSAIM.\n\n"
        f"¡Bienvenido al equipo, {name}!"
    )


def is_recruiting_staff(member: discord.Member) -> bool:
    """Uses the canonical CROSAIM business-role contract for recruiting actions."""
    return can_manage_recruiting(member)


def submission_context(record: dict[str, Any]) -> tuple[dict[str, Any], str | None, str | None]:
    payload = record.get("payload_original") or {}
    if not isinstance(payload, dict):
        payload = {}
    data: dict[str, Any] = dict(payload)
    data.setdefault("nombre", record.get("nombre"))
    data.setdefault("discord_id", record.get("discord_id"))
    data.setdefault("discord_username", record.get("discord_username"))
    data.setdefault("rol", record.get("rol"))
    data.setdefault("rango", record.get("rango"))
    data.setdefault("descripcion", record.get("descripcion"))
    data.setdefault("foto_url", record.get("foto_url"))
    discord_id = str(data.get("discord_id") or "").strip()
    mention = f"<@{discord_id}>" if discord_id.isdigit() else None
    return data, mention, str(record.get("id")) if record.get("id") else None


def find_role_for_assignment(guild: discord.Guild, role_name: str) -> discord.Role | None:
    role_id = load_runtime_role_id(role_name)
    role = guild.get_role(role_id) if role_id else None
    if role:
        return role
    aliases = {"PLAYER": ("player", "jugador", "roster"), "TRYOUT": ("tryout", "tryouts")}
    candidates = (role_name, *aliases.get(role_name, ()))
    for spec in BUSINESS_ROLE_SPECS:
        if normalize(spec.key) == normalize(role_name):
            candidates = (spec.name, *spec.aliases)
            break
    return next((item for item in guild.roles if any(normalize(item.name) == normalize(candidate) for candidate in candidates)), None)


async def assign_application_role(data: dict[str, Any], role_name: str, *, remove_roles: tuple[str, ...] = ()) -> str:
    discord_id = str(data.get("discord_id") or data.get("discordUserId") or "").strip()
    guild = bot.get_guild(GUILD_ID) if GUILD_ID else None
    role = find_role_for_assignment(guild, role_name) if guild else None
    if not guild or not role or not discord_id.isdigit():
        return f"No se asignó {role_name}: falta servidor, rol o Discord ID válido."
    try:
        member = guild.get_member(int(discord_id)) or await guild.fetch_member(int(discord_id))
        for old_name in remove_roles:
            old_role = find_role_for_assignment(guild, old_name)
            if old_role and old_role in member.roles and old_role != role:
                await member.remove_roles(old_role, reason=f"CROSAIM: retirar {old_name} al pasar a {role_name}")
        if role not in member.roles:
            await member.add_roles(role, reason=f"CROSAIM: cambio de candidatura a {role_name}")
        await write_audit_log("ROL", f"Se asignó {role.mention} a {member.mention} por candidatura {role_name}.", level="success")
        return f"Rol {role.name} asignado."
    except discord.Forbidden:
        await write_audit_log("ROL", f"No se pudo asignar {role_name}; revisa permisos y jerarquía del bot.", level="error")
        return "No se asignó rol: faltan permisos o jerarquía del bot."
    except discord.NotFound:
        return "No se asignó rol: el jugador no está en el servidor."
    except Exception as error:
        logging.exception("No se pudo asignar rol CROSAIM")
        return f"No se asignó rol: {error}"


class ReviewView(discord.ui.View):
    def __init__(self, data: dict[str, Any] | None = None, player_mention: str | None = None, submission_id: str | None = None):
        super().__init__(timeout=None)
        self.data = data or {}
        self.player_mention = player_mention
        self.submission_id = submission_id

    def resolve_context(self, interaction: discord.Interaction) -> tuple[dict[str, Any], str | None, str | None]:
        if self.data and self.submission_id:
            return self.data, self.player_mention, self.submission_id
        record = find_submission_by_review_message(interaction.message.id) if interaction.message else None
        if not record:
            return {}, None, None
        return submission_context(record)

    async def disable_message(self, interaction: discord.Interaction) -> None:
        for child in self.children:
            child.disabled = True
        if interaction.message:
            await interaction.message.edit(view=self)

    @discord.ui.button(label="Aprobar", style=discord.ButtonStyle.success, custom_id="crosaim:approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not is_recruiting_staff(interaction.user):
            await interaction.response.send_message("Solo el staff de CROSAIM puede aprobar postulaciones.", ephemeral=True)
            return
        await interaction.response.defer(ephemeral=True)
        data, player_mention, submission_id = self.resolve_context(interaction)
        if not submission_id:
            await interaction.followup.send("No encontré los datos de esta postulación. Ejecuta una nueva revisión desde el panel.", ephemeral=True)
            return
        channel = get_text_channel("tryouts") or get_text_channel("roster")
        if not channel:
            await interaction.followup.send("No encuentro el canal de tryout/roster.", ephemeral=True)
            return
        path = await create_welcome_card(data, data.get("foto_url"), approved=True)
        content = f"{player_mention}\n" if player_mention else ""
        content += approval_description(data).replace("Bienvenido al roster", "Candidato enviado a tryout").replace("incorporación", "inicio del tryout")
        approval_message = await channel.send(content=content, file=discord.File(path) if path else None, allowed_mentions=discord.AllowedMentions(users=True))
        approval_result = assign_result = ""
        try:
            set_status(submission_id, "APROBADA", interaction.user.id, detail={"approval_message_id": str(approval_message.id)})
            assign_result = await assign_application_role(data, "TRYOUT")
            set_status(submission_id, "TRYOUT", interaction.user.id, detail={"role_result": assign_result, "approval_message_id": str(approval_message.id)})
            approval_result = "Candidato aprobado y enviado a Tryout."
        except Exception as error:
            logging.exception("No se pudo completar la transición aprobación→tryout")
            await write_audit_log("TRYOUT", f"Error al completar aprobación de candidatura: {error}", level="error")
            approval_result = f"El anuncio fue publicado, pero la transición quedó pendiente: {error}"
        await write_audit_log("TRYOUT", f"{interaction.user.mention} aprobó una postulación y la envió a Tryout. {assign_result}", level="success")
        await self.disable_message(interaction)
        await interaction.followup.send(f"{approval_result} {assign_result}", ephemeral=True)

    @discord.ui.button(label="Rechazar", style=discord.ButtonStyle.danger, custom_id="crosaim:reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not is_recruiting_staff(interaction.user):
            await interaction.response.send_message("Solo el staff de CROSAIM puede rechazar postulaciones.", ephemeral=True)
            return
        data, player_mention, submission_id = self.resolve_context(interaction)
        if not submission_id:
            await interaction.response.send_message("No encontré los datos de esta postulación.", ephemeral=True)
            return
        try:
            set_status(submission_id, "RECHAZADA", interaction.user.id, reason="Rechazada desde el canal de revisión")
        except Exception as error:
            logging.exception("No se pudo actualizar Supabase tras rechazar")
            await interaction.response.send_message(f"No se pudo rechazar: {error}", ephemeral=True)
            return
        await write_audit_log("RECHAZO", f"{interaction.user.mention} rechazó una postulación.", level="warning")
        await interaction.response.send_message("Postulación rechazada y sincronizada.", ephemeral=True)
        await self.disable_message(interaction)

    @discord.ui.button(label="Entrevista", style=discord.ButtonStyle.primary, custom_id="crosaim:interview")
    async def interview(self, interaction: discord.Interaction, button: discord.ui.Button):
        if not isinstance(interaction.user, discord.Member) or not is_recruiting_staff(interaction.user):
            await interaction.response.send_message("Solo el staff de CROSAIM puede pasar a entrevista.", ephemeral=True)
            return
        data, player_mention, submission_id = self.resolve_context(interaction)
        if not submission_id:
            await interaction.response.send_message("No encontré los datos de esta postulación.", ephemeral=True)
            return
        try:
            set_status(submission_id, "ENTREVISTA", interaction.user.id, detail={"source_message_id": interaction.message.id if interaction.message else None})
        except Exception as error:
            logging.exception("No se pudo actualizar Supabase para entrevista")
            await interaction.response.send_message(f"No se pudo pasar a entrevista: {error}", ephemeral=True)
            return
        notice_channel = get_text_channel("interviews") or get_text_channel("review")
        move_result = await move_member_to_interview_voice(data)
        target = get_crosaim_channel("interview_voice")
        if notice_channel:
            await notice_channel.send(
                f"🎙️ **ENTREVISTA CROSAIM**\n{player_mention or value(data, 'nombre', default='Jugador')}\n"
                f"**Voz:** {move_result}\nCanal objetivo: {target.mention if target else '𝑽𝑨𝑳𝑶𝑹𝑨𝑵𝑻 no disponible'}",
                allowed_mentions=discord.AllowedMentions(users=True),
            )
        await write_audit_log("ENTREVISTA", f"{interaction.user.mention} cambió una postulación a entrevista. {move_result}", level="info")
        await interaction.response.send_message(f"Candidatura pasada a entrevista. {move_result}", ephemeral=True)
        await self.disable_message(interaction)


@bot.event
async def on_ready():
    logging.info("Conectado como %s (%s)", bot.user, bot.user.id if bot.user else "?")
    logging.info("Canales: postulacion=%s revision=%s aprobacion=%s clips=%s entrevista=%s aviso_entrevista=%s guild=%s", POSTULACION_CHANNEL_ID, REVISION_CHANNEL_ID, APROBACION_CHANNEL_ID, CLIPS_CHANNEL_ID, INTERVIEW_VOICE_CHANNEL_ID, INTERVIEW_NOTICE_CHANNEL_ID, GUILD_ID)
    try:
        await register_crosaim_admin_cog(bot)
        logging.info("Comandos /crosaim sincronizados")
        bot.add_view(ReviewView())
        logging.info("Vista persistente de revisión registrada")
    except Exception:
        logging.exception("No se pudieron sincronizar los comandos /crosaim")
    if not poll_web_events.is_running():
        poll_web_events.start()


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot and not message.webhook_id:
        return
    application_channel = get_text_channel("applications")
    if message.guild is None or message.guild.id != GUILD_ID or not application_channel or message.channel.id != application_channel.id:
        await bot.process_commands(message)
        return
    # A channel ACL is defense in depth; the bot must also authenticate the
    # privileged source before it writes with its Supabase service identity.
    if not POSTULACION_WEBHOOK_ID:
        logging.error("Postulación ignorada: falta POSTULACION_WEBHOOK_ID autorizado en la configuración.")
        return
    if message.webhook_id != POSTULACION_WEBHOOK_ID:
        logging.warning("Postulación ignorada: webhook no autorizado (%s).", message.webhook_id)
        return
    logging.info("Postulación recibida: message_id=%s webhook_id=%s", message.id, message.webhook_id)
    target = get_text_channel("review")
    if not target:
        logging.error("No encuentro el canal CROSAIM de revisión; revisa setup, IDs y permisos")
        return
    data = parse_submission(message)
    submission_id: str | None = None
    try:
        existing = find_submission_by_message(message.id)
        if existing:
            logging.warning("Postulación duplicada ignorada: message_id=%s submission_id=%s", message.id, existing["id"])
            return
        submission_id = save_submission(data, webhook_message_id=message.id, webhook_id=message.webhook_id)
    except Exception:
        # El índice único cubre la carrera entre dos entregas simultáneas.
        # Si otra entrega ganó, no se debe publicar una segunda revisión.
        try:
            existing = find_submission_by_message(message.id)
        except Exception:
            existing = None
        if existing:
            logging.warning("Postulación duplicada detectada tras inserción: message_id=%s", message.id)
            return
        logging.exception("Supabase falló; se continuará enviando la postulación a revisión")
    public_lookup_number: str | None = None
    try:
        public_lookup_number = await sync_application_to_web(data, message)
        if public_lookup_number and message.author and not message.author.bot:
            try:
                await message.author.send(f"Tu postulación CROSAIM fue recibida. Número privado de consulta: **{public_lookup_number}**\nConsulta el estado en {CROSAIM_WEB_BASE_URL} sin iniciar sesión.")
            except discord.HTTPException:
                logging.info("No se pudo enviar DM de consulta a %s", message.author)
    except Exception:
        logging.exception("La postulación llegó a Discord, pero no se pudo reflejar en la web")
    player = find_player_mention(data, message.content)
    try:
        path = await create_welcome_card(data, data.get("foto_url"), approved=False)
    except Exception:
        logging.exception("No se pudo generar la tarjeta de postulación")
        path = None
    summary = "**Nueva postulación para revisión**\n"
    summary += f"**Jugador:** {value(data, 'nombre', 'name', default='No indicado')}\n"
    summary += f"**Rol:** {value(data, 'rol', 'role', default='No indicado')}\n"
    summary += f"**Rango:** {value(data, 'rango', 'rank', default='No indicado')}\n"
    summary += f"**Origen:** {message.channel.mention}"
    review_message = await target.send(content=summary, file=discord.File(path) if path else None, view=ReviewView(data, player, submission_id), allowed_mentions=discord.AllowedMentions.none())
    if submission_id:
        try:
            set_review_message(submission_id, review_message.id)
            set_status(submission_id, "REVISIÓN", None, source="discord", actor_type="bot", detail={"review_message_id": str(review_message.id)})
        except Exception:
            logging.exception("No se pudo guardar en Supabase el mensaje/estado de revisión")
    await write_audit_log("POSTULACIÓN", f"Nueva postulación recibida en {message.channel.mention}; revisión publicada en {target.mention}.", level="info")


@bot.command(name="salud")
async def health(ctx: commands.Context):
    await ctx.send("Crosaim está conectado y listo para revisar postulaciones.")


bot.run(TOKEN)
