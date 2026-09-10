from __future__ import annotations

import logging
import os
import re
from typing import Any

import discord
from discord.ext import commands
from dotenv import load_dotenv

from image_generator import create_welcome_card
from supabase_db import save_submission, set_review_message, set_status

load_dotenv()
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
TOKEN = os.getenv("DISCORD_BOT_TOKEN")
POSTULACION_CHANNEL_ID = int(os.getenv("POSTULACION_CHANNEL_ID", "0"))
REVISION_CHANNEL_ID = int(os.getenv("REVISION_CHANNEL_ID", "0"))
APROBACION_CHANNEL_ID = int(os.getenv("APROBACION_CHANNEL_ID", "0"))
POSTULACION_WEBHOOK_ID = int(os.getenv("POSTULACION_WEBHOOK_ID", "0"))
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
    for embed in message.embeds:
        if embed.title:
            data.setdefault("titulo", embed.title)
        if embed.description:
            data.setdefault("descripcion", embed.description)
        for field in embed.fields:
            data[field.name.strip().lower()] = field.value
        if embed.image and embed.image.url:
            data.setdefault("foto_url", embed.image.url)
        if embed.thumbnail and embed.thumbnail.url:
            data.setdefault("foto_url", embed.thumbnail.url)
    for attachment in message.attachments:
        if attachment.content_type and attachment.content_type.startswith("image/"):
            data.setdefault("foto_url", attachment.url)
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


def approval_description(data: dict[str, Any]) -> str:
    name = value(data, "nombre", "name", default="Jugador")
    role = value(data, "rol", "role")
    rank = value(data, "rango", "rank")
    return (
        f"¡Bienvenido al roster, {name}!\n\n"
        f"Nos complace anunciar oficialmente la incorporación de {name} a CROSAIM.\n\n"
        f"**Rol:** {role}\n"
        f"**Rango:** {rank}\n"
        f"**Estado:** Aprobado\n\n"
        "A partir de ahora forma parte de nuestra familia competitiva. "
        "Le deseamos muchos éxitos, grandes partidas y el mejor desempeño "
        "representando los colores de CROSAIM.\n\n"
        f"¡Bienvenido al equipo, {name}!"
    )


class ReviewView(discord.ui.View):
    def __init__(self, data: dict[str, Any], player_mention: str | None, submission_id: str):
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
        approval_message = await channel.send(
            content=content,
            file=discord.File(path) if path else None,
        )
        set_status(self.submission_id, "aprobada", interaction.user.id, approval_message_id=approval_message.id)
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)
        await interaction.followup.send("Postulación aprobada y enviada a ✅ Aprobación.", ephemeral=True)

    @discord.ui.button(label="Rechazar", style=discord.ButtonStyle.danger, custom_id="crosaim:reject")
    async def reject(self, interaction: discord.Interaction, button: discord.ui.Button):
        set_status(self.submission_id, "rechazada", interaction.user.id, reason="Rechazada desde el canal de revisión")
        await interaction.response.send_message("Postulación rechazada. Puedes escribir el motivo en este canal.", ephemeral=True)
        for child in self.children:
            child.disabled = True
        await interaction.message.edit(view=self)


@bot.event
async def on_ready():
    logging.info("Conectado como %s (%s)", bot.user, bot.user.id if bot.user else "?")


@bot.event
async def on_message(message: discord.Message):
    if message.author.bot and not message.webhook_id:
        return
    if message.channel.id != POSTULACION_CHANNEL_ID:
        await bot.process_commands(message)
        return
    if POSTULACION_WEBHOOK_ID and message.webhook_id != POSTULACION_WEBHOOK_ID:
        return
    target = bot.get_channel(REVISION_CHANNEL_ID)
    if not target:
        logging.error("No encuentro REVISION_CHANNEL_ID=%s", REVISION_CHANNEL_ID)
        return
    data = parse_submission(message)
    submission_id = save_submission(data, webhook_message_id=message.id, webhook_id=message.webhook_id)
    player = find_player_mention(data, message.content)
    path = await create_welcome_card(data, data.get("foto_url"), approved=False)
    summary = "**Nueva postulación para revisión**\n"
    summary += f"**Jugador:** {value(data, 'nombre', 'name', default='No indicado')}\n"
    summary += f"**Rol:** {value(data, 'rol', 'role', default='No indicado')}\n"
    summary += f"**Rango:** {value(data, 'rango', 'rank', default='No indicado')}\n"
    summary += f"**Origen:** {message.channel.mention}"
    review_message = await target.send(
        content=summary,
        file=discord.File(path) if path else None,
        view=ReviewView(data, player, submission_id),
    )
    set_review_message(submission_id, review_message.id)


@bot.command(name="salud")
async def health(ctx: commands.Context):
    await ctx.send("Crosaim está conectado y listo para revisar postulaciones.")


bot.run(TOKEN)
