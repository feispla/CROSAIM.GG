from __future__ import annotations

import json
import os
import re
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import discord
from discord import app_commands
from discord.ext import commands


# Canonical names are intentionally plain so they remain stable in environment
# configuration, logs and code even when the visual Discord name has an emoji.
APPLICATION_STATUSES = (
    "POSTULACIÓN",
    "REVISIÓN",
    "ENTREVISTA",
    "APROBADA",
    "RECHAZADA",
    "ROSTER",
    "TRYOUT",
)

STATUS_ALIASES = {
    "pendiente": "POSTULACIÓN",
    "postulacion": "POSTULACIÓN",
    "postulación": "POSTULACIÓN",
    "en revision": "REVISIÓN",
    "revision": "REVISIÓN",
    "revisión": "REVISIÓN",
    "entrevista": "ENTREVISTA",
    "aprobada": "APROBADA",
    "approved": "APROBADA",
    "rechazada": "RECHAZADA",
    "rejected": "RECHAZADA",
    "roster": "ROSTER",
    "tryout": "TRYOUT",
}

ALLOWED_TRANSITIONS = {
    "POSTULACIÓN": {"REVISIÓN", "RECHAZADA"},
    "REVISIÓN": {"ENTREVISTA", "RECHAZADA"},
    "ENTREVISTA": {"APROBADA", "RECHAZADA", "TRYOUT"},
    "APROBADA": {"ROSTER", "TRYOUT"},
    "TRYOUT": {"ROSTER", "RECHAZADA"},
    "ROSTER": set(),
    "RECHAZADA": set(),
}


@dataclass(frozen=True)
class ChannelSpec:
    key: str
    name: str
    kind: discord.ChannelType
    aliases: tuple[str, ...] = ()
    private: bool = False


@dataclass(frozen=True)
class CategorySpec:
    key: str
    name: str
    channels: tuple[ChannelSpec, ...]


TEXT = discord.ChannelType.text
VOICE = discord.ChannelType.voice

LAYOUT: tuple[CategorySpec, ...] = (
    CategorySpec(
        "information",
        "📢 INFORMACIÓN",
        (
            ChannelSpec("welcome", "bienvenida", TEXT, ("welcome", "bienvenido")),
            ChannelSpec("rules", "reglas", TEXT, ("normas",)),
            ChannelSpec("announcements", "anuncios", TEXT),
            ChannelSpec("news", "noticias", TEXT),
            ChannelSpec("service_status", "estado-del-servicio", TEXT),
            ChannelSpec("faq", "preguntas-frecuentes", TEXT),
        ),
    ),
    CategorySpec(
        "community",
        "👥 COMUNIDAD",
        (
            ChannelSpec("general", "general", TEXT, ("lobby",)),
            ChannelSpec("introductions", "presentación", TEXT, ("presentacion",)),
            ChannelSpec("media", "media", TEXT),
            ChannelSpec("clips", "clips", TEXT),
            ChannelSpec("looking_for_team", "buscar-equipo", TEXT, ("lfg",)),
            ChannelSpec("off_topic", "off-topic", TEXT),
        ),
    ),
    CategorySpec(
        "competitive",
        "🎯 COMPETITIVO",
        (
            ChannelSpec("applications", "postulaciones", TEXT, ("postulacion", "postulación")),
            ChannelSpec("review", "revisión", TEXT, ("revision",), True),
            ChannelSpec("interviews", "entrevistas", TEXT, (), True),
            ChannelSpec("tryouts", "tryouts", TEXT),
            ChannelSpec("roster", "roster", TEXT),
            ChannelSpec("competitive_results", "resultados", TEXT),
        ),
    ),
    CategorySpec(
        "voice",
        "🎙️ VOZ",
        (
            ChannelSpec("interview_voice", "𝑽𝑨𝑳𝑶𝑹𝑨𝑵𝑻", VOICE, ("valorant",)),
            ChannelSpec("voice_2", "Sala 2", VOICE, ("sala 2", "sala2")),
            ChannelSpec("voice_3", "Sala 3", VOICE, ("sala 3", "sala3")),
            ChannelSpec("scrim_1", "Scrim 1", VOICE),
            ChannelSpec("scrim_2", "Scrim 2", VOICE),
            ChannelSpec("waiting_room", "Espera", VOICE, ("waiting", "espera")),
        ),
    ),
    CategorySpec(
        "tournaments",
        "🏆 TORNEOS",
        (
            ChannelSpec("tpg", "tpg", TEXT),
            ChannelSpec("tournament_calendar", "calendario-torneos", TEXT),
            ChannelSpec("tournament_results", "resultados", TEXT),
            ChannelSpec("tournament_announcements", "anuncios-torneos", TEXT),
        ),
    ),
    CategorySpec(
        "crosaim",
        "🎮 CROSAIM",
        (
            ChannelSpec("game_news", "novedades-juego", TEXT),
            ChannelSpec("game_support", "soporte-juego", TEXT),
            ChannelSpec("ranking", "ranking", TEXT),
            ChannelSpec("profiles", "perfiles", TEXT),
            ChannelSpec("events", "eventos", TEXT),
        ),
    ),
    CategorySpec(
        "bot",
        "🤖 BOT",
        (
            ChannelSpec("bot_logs", "bot-logs", TEXT, ("security logs",)),
            ChannelSpec("bot_alerts", "bot-alertas", TEXT),
            ChannelSpec("sync", "sincronización", TEXT, ("sincronizacion",)),
            ChannelSpec("audit", "auditoría", TEXT, ("auditoria",)),
        ),
    ),
    CategorySpec(
        "staff",
        "🔒 STAFF",
        (
            ChannelSpec("staff", "staff", TEXT, (), True),
            ChannelSpec("staff_review", "revisión-staff", TEXT, ("revision staff",), True),
            ChannelSpec("cases", "casos", TEXT, (), True),
            ChannelSpec("staff_applications", "postulaciones-staff", TEXT, (), True),
            ChannelSpec("staff_logs", "logs-staff", TEXT, ("moderator only",), True),
        ),
    ),
)

# Role names drive only the capabilities present in the bot. Existing equivalents,
# especially Spanish rank labels, are reused instead of creating parallel roles.
ROLE_SPECS: tuple[tuple[str, tuple[str, ...]], ...] = (
    ("CROSAIM", ("ca",)),
    ("Roster", ()),
    ("Staff", ()),
    ("Admin", ("administrador",)),
    ("Moderador", ("moderator",)),
    ("Entrevistador", ("interviewer",)),
    ("Tryout", ()),
    ("Postulante", ("applicant",)),
    ("Duelista", ("duelist",)),
    ("Iniciador", ("initiator",)),
    ("Controlador", ("controller",)),
    ("Centinela", ("sentinela", "sentinel")),
    ("Flex", ()),
    ("IGL", ()),
    ("Iron", ("hierro",)),
    ("Bronze", ("bronce",)),
    ("Silver", ("plata",)),
    ("Gold", ("oro",)),
    ("Platinum", ("platino",)),
    ("Diamond", ("diamante",)),
    ("Ascendant", ("ascendente",)),
    ("Immortal", ("inmortal",)),
    ("Radiant", ("radiante",)),
)

ENV_TO_CHANNEL_KEY = {
    "POSTULACION_CHANNEL_ID": "applications",
    "REVISION_CHANNEL_ID": "review",
    "APROBACION_CHANNEL_ID": "roster",
    "CLIPS_CHANNEL_ID": "clips",
    "INTERVIEW_VOICE_CHANNEL_ID": "interview_voice",
    "INTERVIEW_NOTICE_CHANNEL_ID": "interviews",
    "BOT_LOGS_CHANNEL_ID": "bot_logs",
    "BOT_ALERTS_CHANNEL_ID": "bot_alerts",
    "SYNC_CHANNEL_ID": "sync",
    "AUDIT_CHANNEL_ID": "audit",
}


def normalize(value: str) -> str:
    """Produces an accent/emoji-insensitive key for Discord object matching."""
    decomposed = unicodedata.normalize("NFKD", value or "")
    plain = "".join(char for char in decomposed if not unicodedata.combining(char))
    return re.sub(r"[^a-z0-9]+", " ", plain.lower()).strip()


def canonical_status(value: str) -> str:
    candidate = normalize(value)
    if candidate in STATUS_ALIASES:
        return STATUS_ALIASES[candidate]
    upper = (value or "").strip().upper()
    if upper in APPLICATION_STATUSES:
        return upper
    raise ValueError(f"Estado de postulación no reconocido: {value!r}")


def can_transition(current: str, target: str) -> bool:
    source = canonical_status(current)
    destination = canonical_status(target)
    return source == destination or destination in ALLOWED_TRANSITIONS[source]


class RuntimeConfig:
    """Stores discovered IDs outside Git. The deployment path must be persistent."""

    def __init__(self) -> None:
        configured = os.getenv("CROSAIM_RUNTIME_CONFIG_PATH", "data/crosaim-discord.json")
        self.path = Path(configured)

    def load(self) -> dict[str, object]:
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {"channels": {}, "roles": {}}

    def save(self, *, guild_id: int, channels: dict[str, int], roles: dict[str, int]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = {
            "guild_id": str(guild_id),
            "channels": {key: str(value) for key, value in sorted(channels.items())},
            "roles": {key: str(value) for key, value in sorted(roles.items())},
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(self.path)


class DiscordLayoutManager:
    def __init__(self, guild: discord.Guild, runtime_config: RuntimeConfig | None = None) -> None:
        self.guild = guild
        self.runtime_config = runtime_config or RuntimeConfig()
        self.created: list[str] = []
        self.reused: list[str] = []
        self.warnings: list[str] = []
        self.channels: dict[str, int] = {}
        self.roles: dict[str, int] = {}

    @property
    def bot_member(self) -> discord.Member | None:
        return self.guild.me

    def _name_matches(self, name: str, candidates: Iterable[str]) -> bool:
        normalized = normalize(name)
        return any(normalized == normalize(candidate) for candidate in candidates)

    def _find_category(self, spec: CategorySpec) -> discord.CategoryChannel | None:
        matches = [category for category in self.guild.categories if self._name_matches(category.name, (spec.name, spec.key))]
        return matches[0] if matches else None

    def _find_channel(self, spec: ChannelSpec) -> discord.abc.GuildChannel | None:
        candidates = (spec.name, spec.key, *spec.aliases)
        matching = [channel for channel in self.guild.channels if channel.type == spec.kind and self._name_matches(channel.name, candidates)]
        if not matching:
            return None
        # Prefer the existing VALORANT voice area where Sala 2/Sala 3 have
        # contextual ambiguity with the legacy CS2 section.
        if len(matching) > 1:
            valorant = [channel for channel in matching if channel.category and "valorant" in normalize(channel.category.name)]
            if valorant:
                return valorant[0]
            self.warnings.append(f"Coincidencia ambigua para {spec.key}; se reutilizó {matching[0].mention}.")
        return matching[0]

    def _find_role(self, name: str, aliases: tuple[str, ...]) -> discord.Role | None:
        candidates = (name, *aliases)
        for role in self.guild.roles:
            if self._name_matches(role.name, candidates):
                return role
        return None

    def _staff_overwrites(self) -> dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {
            self.guild.default_role: discord.PermissionOverwrite(view_channel=False)
        }
        for role_name in ("Staff", "Admin", "Moderador", "Entrevistador"):
            role = self._find_role(role_name, ())
            if role:
                overwrites[role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        if self.bot_member:
            overwrites[self.bot_member] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True)
        return overwrites

    async def audit(self) -> str:
        lines = [
            f"Servidor: **{self.guild.name}** (`{self.guild.id}`)",
            f"Categorías: {len(self.guild.categories)} · Canales: {len(self.guild.channels)} · Roles: {len(self.guild.roles)}",
        ]
        missing_categories = [spec.name for spec in LAYOUT if not self._find_category(spec)]
        missing_channels = [spec.name for category in LAYOUT for spec in category.channels if not self._find_channel(spec)]
        missing_roles = [name for name, aliases in ROLE_SPECS if not self._find_role(name, aliases)]
        lines.append("Categorías faltantes: " + (", ".join(missing_categories) if missing_categories else "ninguna"))
        lines.append("Canales faltantes: " + (", ".join(missing_channels) if missing_channels else "ninguno"))
        lines.append("Roles faltantes: " + (", ".join(missing_roles) if missing_roles else "ninguno"))
        member = self.bot_member
        if member:
            permissions = member.guild_permissions
            required = {
                "Gestionar canales": permissions.manage_channels,
                "Gestionar roles": permissions.manage_roles,
                "Mover miembros": permissions.move_members,
                "Enviar mensajes": permissions.send_messages,
                "Adjuntar archivos": permissions.attach_files,
            }
            lines.append("Permisos bot: " + ", ".join(f"{label}={'sí' if granted else 'no'}" for label, granted in required.items()))
        return "\n".join(lines)

    async def setup(self) -> str:
        member = self.bot_member
        if not member:
            raise RuntimeError("No se pudo resolver el miembro del bot en este servidor.")
        if not member.guild_permissions.manage_channels:
            raise PermissionError("Falta el permiso Gestionar canales para ejecutar la configuración.")
        if not member.guild_permissions.manage_roles:
            raise PermissionError("Falta el permiso Gestionar roles para crear o reutilizar roles operativos.")

        for role_name, aliases in ROLE_SPECS:
            role = self._find_role(role_name, aliases)
            if role is None:
                role = await self.guild.create_role(name=role_name, reason="CROSAIM setup idempotente")
                self.created.append(f"rol:{role_name}")
            else:
                self.reused.append(f"rol:{role.name}")
            self.roles[role_name] = role.id

        categories: dict[str, discord.CategoryChannel] = {}
        for category_spec in LAYOUT:
            category = self._find_category(category_spec)
            if category is None:
                overwrites = self._staff_overwrites() if category_spec.key == "staff" else None
                category = await self.guild.create_category(category_spec.name, overwrites=overwrites, reason="CROSAIM setup idempotente")
                self.created.append(f"categoría:{category_spec.name}")
            else:
                self.reused.append(f"categoría:{category.name}")
            categories[category_spec.key] = category

        for category_spec in LAYOUT:
            category = categories[category_spec.key]
            for spec in category_spec.channels:
                channel = self._find_channel(spec)
                if channel is None:
                    kwargs: dict[str, object] = {"name": spec.name, "category": category, "reason": "CROSAIM setup idempotente"}
                    if spec.private:
                        kwargs["overwrites"] = self._staff_overwrites()
                    if spec.kind == TEXT:
                        channel = await self.guild.create_text_channel(**kwargs)
                    elif spec.kind == VOICE:
                        channel = await self.guild.create_voice_channel(**kwargs)
                    else:
                        raise RuntimeError(f"Tipo de canal no soportado para {spec.key}")
                    self.created.append(f"canal:{spec.name}")
                else:
                    self.reused.append(f"canal:{channel.name}")
                self.channels[spec.key] = channel.id

        self.runtime_config.save(guild_id=self.guild.id, channels=self.channels, roles=self.roles)
        return self.summary()

    def summary(self) -> str:
        chunks = [
            "**CROSAIM setup finalizado**",
            f"Creados: {len(self.created)} · Reutilizados: {len(self.reused)} · Avisos: {len(self.warnings)}",
            "Canal de entrevista: " + (f"<#{self.channels['interview_voice']}>" if self.channels.get("interview_voice") else "no encontrado"),
            "La configuración de IDs se guardó en el almacenamiento de ejecución; configura la ruta en un volumen persistente.",
        ]
        if self.warnings:
            chunks.append("Avisos: " + " · ".join(self.warnings[:4]))
        return "\n".join(chunks)


class CrosaimAdminCog(commands.GroupCog, group_name="crosaim", group_description="Operación y configuración de CROSAIM"):
    def __init__(self, bot: commands.Bot) -> None:
        self.bot = bot

    async def _require_manager(self, interaction: discord.Interaction) -> discord.Guild:
        if interaction.guild is None:
            raise app_commands.CheckFailure("Este comando solo está disponible en un servidor.")
        member = interaction.user if isinstance(interaction.user, discord.Member) else None
        if member is None or not member.guild_permissions.manage_guild:
            raise app_commands.CheckFailure("Se requiere el permiso Gestionar servidor.")
        return interaction.guild

    @app_commands.command(name="setup", description="Audita y crea solo la estructura CROSAIM que falta.")
    async def setup(self, interaction: discord.Interaction) -> None:
        try:
            guild = await self._require_manager(interaction)
            await interaction.response.defer(ephemeral=True, thinking=True)
            manager = DiscordLayoutManager(guild)
            result = await manager.setup()
            await interaction.followup.send(result[:1900], ephemeral=True)
        except (PermissionError, RuntimeError, app_commands.CheckFailure) as error:
            if interaction.response.is_done():
                await interaction.followup.send(f"No se ejecutó el setup: {error}", ephemeral=True)
            else:
                await interaction.response.send_message(f"No se ejecutó el setup: {error}", ephemeral=True)
        except discord.Forbidden:
            message = "Discord rechazó la configuración. Revisa Gestionar canales, Gestionar roles y la jerarquía del rol Crosaim."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="status", description="Muestra el estado de Discord, roles y sincronización CROSAIM.")
    async def status(self, interaction: discord.Interaction) -> None:
        try:
            guild = await self._require_manager(interaction)
            await interaction.response.defer(ephemeral=True, thinking=True)
            manager = DiscordLayoutManager(guild)
            report = await manager.audit()
            runtime = RuntimeConfig().load()
            configured = runtime.get("channels", {}) if isinstance(runtime, dict) else {}
            report += f"\nIDs persistidos: {len(configured) if isinstance(configured, dict) else 0}"
            await interaction.followup.send(report[:1900], ephemeral=True)
        except app_commands.CheckFailure as error:
            await interaction.response.send_message(str(error), ephemeral=True)


async def register_crosaim_admin_cog(bot: commands.Bot) -> None:
    if bot.get_cog("CrosaimAdminCog") is None:
        await bot.add_cog(CrosaimAdminCog(bot))
    guild_id = int(os.getenv("GUILD_ID", "0") or "0")
    if guild_id:
        guild = discord.Object(id=guild_id)
        bot.tree.copy_global_to(guild=guild)
        await bot.tree.sync(guild=guild)
    else:
        await bot.tree.sync()


def load_runtime_channel_id(key: str) -> int | None:
    env_name = next((name for name, channel_key in ENV_TO_CHANNEL_KEY.items() if channel_key == key), None)
    if env_name:
        raw = os.getenv(env_name, "").strip()
        if raw.isdigit() and int(raw) > 0:
            return int(raw)
    configured = RuntimeConfig().load().get("channels", {})
    if isinstance(configured, dict):
        raw = str(configured.get(key, ""))
        if raw.isdigit():
            return int(raw)
    return None


def load_runtime_role_id(role_name: str) -> int | None:
    configured = RuntimeConfig().load().get("roles", {})
    if isinstance(configured, dict):
        raw = str(configured.get(role_name, ""))
        if raw.isdigit():
            return int(raw)
    return None
