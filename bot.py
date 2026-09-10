from __future__ import annotations

import logging
import json
import os
import re
from typing import Any

import discord
from discord.ext import commands, tasks
import aiohttp
from dotenv import load_dotenv

from image_generator import create_welcome_card
from supabase_db import find_submission_by_message, save_submission, set_review_message, set_status

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
POSTULACION_CHANNEL_ID = int(os.getenv("POSTULACION_CHANNEL_ID", "0"))
REVISION_CHANNEL_ID = int(os.getenv("REVISION_CHANNEL_ID", "0"))
GUILD_ID = int(os.getenv("GUILD_ID", "0"))
APROBACION_CHANNEL_ID = int(os.getenv("APROBACION_CHANNEL_ID", "0"))
CLIPS_CHANNEL_ID = int(os.getenv("CLIPS_CHANNEL_ID", "1546651682383855627"))
INTERVIEW_VOICE_CHANNEL_ID = int(os.getenv("INTERVIEW_VOICE_CHANNEL_ID", "1546641332632817689"))
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


def value(data: dict[str, Any], *keys: str, default: str = "Por confirmar") -> str:
    for key in keys:
        raw = data.get(key)
        if raw is not None and str(raw).strip():
            return str(raw).strip()
    return default


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


async def sync_application_to_web(data: dict[str, Any], message: discord.Message) -> None:
    if not CROSAIM_BOT_SYNC_SECRET:
        logging.warning("No se sincroniza la postulación web: falta CROSAIM_BOT_SYNC_SECRET")
        return
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
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{CROSAIM_WEB_BASE_URL}/api/discord/applications",
            headers={"x-crosaim-sync-secret": CROSAIM_BOT_SYNC_SECRET},
            json=payload,
            timeout=aiohttp.ClientTimeout(total=15),
        ) as response:
            if response.status >= 300:
                raise RuntimeError(f"web application sync HTTP {response.status}: {await response.text()}")


async def acknowledge_web_event(event_id: int, ok: bool, error: str | None = None) -> None:
    if not CROSAIM_BOT_SYNC_SECRET:
        raise RuntimeError("Falta CROSAIM_BOT_SYNC_SECRET")
    payload = {"ok": ok}
    if error:
        payload["error"] = error[:500]
    async with aiohttp.ClientSession() as session:
        async with session.post(
            f"{CROSAIM_WEB_BASE_URL}/api/discord/events/{event_id}/ack",
            headers={"x-crosaim-sync-secret": CROSAIM_BOT_SYNC_SECRET},
            json=payload,
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
        return "No se pudo mover automáticamente: falta un ID de Discord válido."
    guild = bot.get_guild(GUILD_ID) if GUILD_ID else None
    voice_channel = bot.get_channel(INTERVIEW_VOICE_CHANNEL_ID)
    if not guild or not isinstance(voice_channel, discord.VoiceChannel):
        return "No se pudo mover automáticamente: canal o servidor no disponible."
    try:
        member = guild.get_member(int(discord_id)) or await guild.fetch_member(int(discord_id))
        if not member.voice or not member.voice.channel:
            return "El candidato debe entrar primero a un canal de voz para poder moverlo."
        await member.move_to(voice_channel, reason="Candidato CROSAIM pasó a entrevista")
        return f"Candidato movido a <#{INTERVIEW_VOICE_CHANNEL_ID}>."
    except discord.Forbidden:
        return "Falta el permiso Mover miembros o el bot está debajo del candidato en la jerarquía."
    except discord.NotFound:
        return "El ID de Discord no pertenece a un miembro de este servidor."
    except Exception as error:
        logging.exception("No se pudo mover al candidato al canal de entrevista")
        return f"No se pudo mover automáticamente: {error}"


async def deliver_web_event(event: dict[str, Any]) -> None:
    event_type = str(event.get('eventType') or "")
    payload = json.loads(str(event.get('payload') or "{}"))
    if event_type in {"application_submitted", "application_created", "profile_updated", "player_profile_updated"}:
        channel = bot.get_channel(REVISION_CHANNEL_ID)
        if not channel:
            raise RuntimeError(f"No encuentro REVISION_CHANNEL_ID={REVISION_CHANNEL_ID}")
        title = "📝 **NUEVA POSTULACIÓN DESDE LA WEB**" if "application" in event_type else "🔄 **PERFIL ACTUALIZADO DESDE LA WEB**"
        await channel.send(
            f"{title}\n{web_profile_summary(payload)}",
            allowed_mentions=discord.AllowedMentions.none(),
        )
    elif event_type == "clip_uploaded":
        channel = bot.get_channel(CLIPS_CHANNEL_ID)
        if not channel:
            raise RuntimeError(f"No encuentro CLIPS_CHANNEL_ID={CLIPS_CHANNEL_ID}")
        await channel.send(
            f"**NUEVO CLIP CROSAIM**\n**Archivo:** {payload.get('name', 'clip')}\n"
            f"**Tamaño:** {float(payload.get('size', 0)) / (1024 * 1024):.1f} MB\n"
            f"**Abrir clip:** {payload.get('url', '')}",
            allowed_mentions=discord.AllowedMentions.none(),
        )
    elif event_type == "application_interview":
        notice_channel = bot.get_channel(INTERVIEW_NOTICE_CHANNEL_ID) if INTERVIEW_NOTICE_CHANNEL_ID else None
        notice_channel = notice_channel or bot.get_channel(REVISION_CHANNEL_ID) or bot.get_channel(POSTULACION_CHANNEL_ID)
        if not notice_channel:
            raise RuntimeError("No encuentro canal de aviso para entrevista")
        move_result = await move_member_to_interview_voice(payload)
        mention = event_mention(payload)
        text = f"🎙️ **ENTREVISTA CROSAIM**\n{mention}\n{event_summary(payload)}\n**Voz:** {move_result}\nCanal objetivo: <#{INTERVIEW_VOICE_CHANNEL_ID}>"
        await notice_channel.send(text, allowed_mentions=discord.AllowedMentions(users=True))
    elif event_type == "application_approved":
        channel = bot.get_channel(APROBACION_CHANNEL_ID)
        if not channel:
            raise RuntimeError(f"No encuentro APROBACION_CHANNEL_ID={APROBACION_CHANNEL_ID}")
        image_path = await create_welcome_card(payload, payload.get("photoUrl") or payload.get("foto_url"), approved=True)
        await channel.send(content=f"✅ **POSTULACIÓN APROBADA DESDE CROSAIM**\n{event_mention(payload)}\n{event_summary(payload)}", file=discord.File(image_path) if image_path else None, allowed_mentions=discord.AllowedMentions(users=True))
    elif event_type == "application_rejected":
        channel = bot.get_channel(REVISION_CHANNEL_ID)
        if not channel:
            raise RuntimeError(f"No encuentro REVISION_CHANNEL_ID={REVISION_CHANNEL_ID}")
        await channel.send(f"❌ **Postulación rechazada desde el panel**\n{event_summary(payload)}", allowed_mentions=discord.AllowedMentions.none())
    elif event_type == "roster_tryout":
        channel = bot.get_channel(APROBACION_CHANNEL_ID) or bot.get_channel(REVISION_CHANNEL_ID)
        if not channel:
            raise RuntimeError("No encuentro canal para avisar el tryout")
        await channel.send(f"🟣 **NUEVO TRYOUT EN PLANTILLA**\n{event_summary(payload)}", allowed_mentions=discord.AllowedMentions.none())
    else:
        raise RuntimeError(f"Tipo de evento no soportado: {event_type}")


@tasks.loop(seconds=8)
async def poll_web_events() -> None:
    if not CROSAIM_BOT_SYNC_SECRET:
        return
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{CROSAIM_WEB_BASE_URL}/api/discord/events",
                headers={"x-crosaim-sync-secret": CROSAIM_BOT_SYNC_SECRET},
                timeout=aiohttp.ClientTimeout(total=15),
            ) as response:
                if response.status != 200:
                    logging.warning("Web event polling returned HTTP %s", response.status)
                    return
                events = await response.json()
        for event in events[:20]:
            event_id = int(event["id"])
            try:
                await deliver_web_event(event)
                await acknowledge_web_event(event_id, True)
                logging.info("Evento web %s entregado en Discord", event_id)
            except Exception as error:
                logging.exception("No se pudo entregar evento web %s", event_id)
                try:
                    await acknowledge_web_event(event_id, False, str(error))
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


class ReviewView(discord.ui.View):
    def __init__(self, data: dict[str, Any], player_mention: str | None, submission_id: str | None):
        super().__init__(timeout=None)
        self.data, self.player_mention, self.submission_id = data, player_mention, submission_id

    @discord.ui.button(label="Aprobar", style=discord.ButtonStyle.success, custom_id="crosaim:approve")
    async def approve(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.defer(ephemeral=True)
        channel = bot.get_channel(APROBACION_CHANNEL_ID)
        if not channel:
            await interaction.followup.send("No encuentro el canal de aprobación.", ephemeral=True)
            return
        path = await create_welcome_card(self.data, self.data.get("foto_url"), approved=True)
        content = f"{self.player_mention}\n" if self.player_mention else ""
        content += approval_description(self.data)
        approval_message = await channel.send(content=content, file=discord.File(path) if path else None)
        if self.submission_id:
            try:
                set_status(self.submission_id, "aprobada", interaction.user.id, approval_message_id=approval_message.id)
            except Exception:
                logging.exception("No se pudo actualizar Supabase tras aprobar")
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.followup.send("Postulación aprobada y enviada a ✅ Aprobación.", ephemeral=True)

    @discord.ui.button(label="Rechazar", style=discord.ButtonStyle.danger, custom_id="crosaim:reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        if self.submission_id:
            try:
                set_status(self.submission_id, "rechazada", interaction.user.id, reason="Rechazada desde el canal de revisión")
            except Exception:
                logging.exception("No se pudo actualizar Supabase tras rechazar")
        await interaction.response.send_message("Postulación rechazada.", ephemeral=True)
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)


@bot.event
async def on_ready():
    logging.info("Conectado como %s (%s)", bot.user, bot.user.id if bot.user else "?")
    logging.info("Canales: postulacion=%s revision=%s aprobacion=%s clips=%s entrevista=%s aviso_entrevista=%s guild=%s", POSTULACION_CHANNEL_ID, REVISION_CHANNEL_ID, APROBACION_CHANNEL_ID, CLIPS_CHANNEL_ID, INTERVIEW_VOICE_CHANNEL_ID, INTERVIEW_NOTICE_CHANNEL_ID, GUILD_ID)
    if not poll_web_events.is_running():
        poll_web_events.start()


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot and not message.webhook_id:
        return
    if message.channel.id != POSTULACION_CHANNEL_ID:
        await bot.process_commands(message)
        return
    # Do not reject the message merely because a webhook was regenerated.
    if POSTULACION_WEBHOOK_ID and message.webhook_id and message.webhook_id != POSTULACION_WEBHOOK_ID:
        logging.warning("Webhook distinto detectado (%s); se procesa porque está en el canal correcto", message.webhook_id)
    logging.info("Postulación recibida: message_id=%s webhook_id=%s", message.id, message.webhook_id)
    target = bot.get_channel(REVISION_CHANNEL_ID)
    if not target:
        logging.error("No encuentro REVISION_CHANNEL_ID=%s; revisa el ID y permisos del canal", REVISION_CHANNEL_ID)
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
    try:
        await sync_application_to_web(data, message)
    except Exception:
        logging.exception("La postulación llegó a Discord, pero no se pudo reflejar en la web")
    player = find_player_mention(data, message.content)
    path = await create_welcome_card(data, data.get("foto_url"), approved=False)
    summary = "**Nueva postulación para revisión**\n"
    summary += f"**Jugador:** {value(data, 'nombre', 'name', default='No indicado')}\n"
    summary += f"**Rol:** {value(data, 'rol', 'role', default='No indicado')}\n"
    summary += f"**Rango:** {value(data, 'rango', 'rank', default='No indicado')}\n"
    summary += f"**Origen:** {message.channel.mention}"
    review_message = await target.send(content=summary, file=discord.File(path) if path else None, view=ReviewView(data, player, submission_id))
    if submission_id:
        try:
            set_review_message(submission_id, review_message.id)
        except Exception:
            logging.exception("No se pudo guardar en Supabase el mensaje de revisión")


@bot.command(name="salud")
async def health(ctx: commands.Context):
    await ctx.send("Crosaim está conectado y listo para revisar postulaciones.")


bot.run(TOKEN)
