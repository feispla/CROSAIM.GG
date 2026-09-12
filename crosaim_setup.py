from __future__ import annotations

import hashlib
import json
import os
import re
import unicodedata
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Literal

import discord
from discord import app_commands
from discord.ext import commands


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
class RoleSpec:
    """A business role managed by CROSAIM, never a Discord Administrator role."""

    key: str
    name: str
    aliases: tuple[str, ...]
    position: int
    capabilities: frozenset[str]


@dataclass(frozen=True)
class ChannelSpec:
    key: str
    name: str
    kind: discord.ChannelType
    position: int
    access: Literal["information", "community", "competitive", "voice", "recruiting", "operations"]
    aliases: tuple[str, ...] = ()


@dataclass(frozen=True)
class CategorySpec:
    key: str
    name: str
    position: int
    access: Literal["information", "community", "competitive", "voice", "recruiting", "operations"]
    channels: tuple[ChannelSpec, ...]


TEXT = discord.ChannelType.text
VOICE = discord.ChannelType.voice

# The canonical role contract. The permissions in this file are application
# capabilities and channel access inputs; Discord guild Administrator is never
# assigned by this bot.
BUSINESS_ROLE_SPECS: tuple[RoleSpec, ...] = (
    RoleSpec("SUPER_ADMIN", "SUPER_ADMIN", ("SUPER ADMIN",), 9, frozenset({"dashboard.view", "players.manage", "applications.review", "roster.manage", "tournaments.manage", "content.publish", "settings.manage", "discord.reconcile", "roles.manage"})),
    RoleSpec("ADMIN", "ADMIN", ("Admin", "Administrador"), 8, frozenset({"dashboard.view", "players.manage", "applications.review", "roster.manage", "tournaments.manage", "content.publish", "settings.manage", "discord.reconcile", "roles.manage"})),
    RoleSpec("MANAGER", "MANAGER", ("Manager", "Gestor"), 7, frozenset({"dashboard.view", "players.manage", "applications.review", "roster.manage", "tournaments.manage"})),
    RoleSpec("COACH", "COACH", ("Coach", "Entrenador", "Entrevistador"), 6, frozenset({"dashboard.view", "players.manage", "applications.review", "roster.manage"})),
    RoleSpec("SCOUT", "SCOUT", ("Scout", "Ojeador"), 5, frozenset({"dashboard.view", "players.manage", "applications.review"})),
    RoleSpec("CONTENT", "CONTENT", ("Content", "Contenido"), 4, frozenset({"dashboard.view", "content.publish"})),
    RoleSpec("PLAYER", "PLAYER", ("Player", "Jugador", "Roster"), 3, frozenset({"dashboard.view"})),
    RoleSpec("TRYOUT", "TRYOUT", ("Tryout",), 2, frozenset({"dashboard.view"})),
    RoleSpec("VIEWER", "VIEWER", ("Viewer", "Espectador"), 1, frozenset({"dashboard.view"})),
)

ROLE_BY_KEY = {spec.key: spec for spec in BUSINESS_ROLE_SPECS}
ROLE_CAPABILITIES = {spec.key: spec.capabilities for spec in BUSINESS_ROLE_SPECS}
RECRUITING_ROLE_KEYS = ("SUPER_ADMIN", "ADMIN", "MANAGER", "COACH", "SCOUT")
OPERATIONS_ROLE_KEYS = ("SUPER_ADMIN", "ADMIN", "MANAGER", "COACH", "SCOUT", "CONTENT")

LAYOUT: tuple[CategorySpec, ...] = (
    CategorySpec(
        "information",
        "📢 INFORMACIÓN",
        0,
        "information",
        (
            ChannelSpec("welcome", "bienvenida", TEXT, 0, "information", ("welcome", "bienvenido")),
            ChannelSpec("rules", "reglas", TEXT, 1, "information", ("normas",)),
            ChannelSpec("announcements", "anuncios", TEXT, 2, "information"),
            ChannelSpec("news", "noticias", TEXT, 3, "information"),
            ChannelSpec("service_status", "estado-del-servicio", TEXT, 4, "information"),
            ChannelSpec("faq", "preguntas-frecuentes", TEXT, 5, "information"),
        ),
    ),
    CategorySpec(
        "community",
        "👥 COMUNIDAD",
        1,
        "community",
        (
            ChannelSpec("general", "general", TEXT, 0, "community", ("lobby",)),
            ChannelSpec("introductions", "presentación", TEXT, 1, "community", ("presentacion",)),
            ChannelSpec("media", "media", TEXT, 2, "community"),
            ChannelSpec("clips", "clips", TEXT, 3, "community"),
            ChannelSpec("looking_for_team", "buscar-equipo", TEXT, 4, "community", ("lfg",)),
            ChannelSpec("off_topic", "off-topic", TEXT, 5, "community"),
        ),
    ),
    CategorySpec(
        "competitive",
        "🎯 COMPETITIVO",
        2,
        "competitive",
        (
            ChannelSpec("applications", "postulaciones", TEXT, 0, "competitive", ("postulacion", "postulación")),
            ChannelSpec("review", "revisión", TEXT, 1, "recruiting", ("revision",)),
            ChannelSpec("interviews", "entrevistas", TEXT, 2, "recruiting"),
            ChannelSpec("tryouts", "tryouts", TEXT, 3, "competitive"),
            ChannelSpec("roster", "roster", TEXT, 4, "competitive"),
            ChannelSpec("competitive_results", "resultados", TEXT, 5, "competitive"),
        ),
    ),
    CategorySpec(
        "voice",
        "🎙️ VOZ",
        3,
        "voice",
        (
            ChannelSpec("interview_voice", "𝑽𝑨𝑳𝑶𝑹𝑨𝑵𝑻", VOICE, 0, "recruiting", ("valorant",)),
            ChannelSpec("voice_2", "Sala 2", VOICE, 1, "voice", ("sala 2", "sala2")),
            ChannelSpec("voice_3", "Sala 3", VOICE, 2, "voice", ("sala 3", "sala3")),
            ChannelSpec("scrim_1", "Scrim 1", VOICE, 3, "voice"),
            ChannelSpec("scrim_2", "Scrim 2", VOICE, 4, "voice"),
            ChannelSpec("waiting_room", "Espera", VOICE, 5, "voice", ("waiting", "espera")),
        ),
    ),
    CategorySpec(
        "tournaments",
        "🏆 TORNEOS",
        4,
        "competitive",
        (
            ChannelSpec("tpg", "tpg", TEXT, 0, "competitive"),
            ChannelSpec("tournament_calendar", "calendario-torneos", TEXT, 1, "competitive"),
            ChannelSpec("tournament_results", "resultados", TEXT, 2, "competitive"),
            ChannelSpec("tournament_announcements", "anuncios-torneos", TEXT, 3, "competitive"),
        ),
    ),
    CategorySpec(
        "crosaim",
        "🎮 CROSAIM",
        5,
        "community",
        (
            ChannelSpec("game_news", "novedades-juego", TEXT, 0, "information"),
            ChannelSpec("game_support", "soporte-juego", TEXT, 1, "community"),
            ChannelSpec("ranking", "ranking", TEXT, 2, "community"),
            ChannelSpec("profiles", "perfiles", TEXT, 3, "community"),
            ChannelSpec("events", "eventos", TEXT, 4, "community"),
        ),
    ),
    CategorySpec(
        "bot",
        "🤖 BOT",
        6,
        "operations",
        (
            ChannelSpec("bot_logs", "bot-logs", TEXT, 0, "operations", ("security logs",)),
            ChannelSpec("bot_alerts", "bot-alertas", TEXT, 1, "operations"),
            ChannelSpec("sync", "sincronización", TEXT, 2, "operations", ("sincronizacion",)),
            ChannelSpec("audit", "auditoría", TEXT, 3, "operations", ("auditoria",)),
        ),
    ),
    CategorySpec(
        "staff",
        "🔒 STAFF",
        7,
        "operations",
        (
            ChannelSpec("staff", "staff", TEXT, 0, "operations"),
            ChannelSpec("staff_review", "revisión-staff", TEXT, 1, "operations", ("revision staff",)),
            ChannelSpec("cases", "casos", TEXT, 2, "recruiting"),
            ChannelSpec("staff_applications", "postulaciones-staff", TEXT, 3, "recruiting"),
            ChannelSpec("staff_logs", "logs-staff", TEXT, 4, "operations", ("moderator only",)),
        ),
    ),
)

# Compatibility name retained for integrations that used the old constant.
ROLE_SPECS = tuple((spec.name, spec.aliases) for spec in BUSINESS_ROLE_SPECS)

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
RUNTIME_SCHEMA_VERSION = 2


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


def has_capability(role_keys: Iterable[str], capability: str) -> bool:
    return any(capability in ROLE_CAPABILITIES.get(role_key, frozenset()) for role_key in role_keys)


@dataclass(frozen=True)
class ReconciliationAction:
    action: Literal["create", "rename", "move", "reorder", "overwrite", "reuse", "blocked", "warning"]
    kind: Literal["role", "category", "channel", "registry", "permission"]
    key: str
    detail: str


@dataclass
class ReconciliationPlan:
    actions: list[ReconciliationAction] = field(default_factory=list)
    blocked: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    roles: dict[str, discord.Role] = field(default_factory=dict)
    categories: dict[str, discord.CategoryChannel] = field(default_factory=dict)
    channels: dict[str, discord.abc.GuildChannel] = field(default_factory=dict)

    def add(self, action: ReconciliationAction) -> None:
        self.actions.append(action)
        if action.action == "blocked":
            self.blocked.append(action.detail)
        elif action.action == "warning":
            self.warnings.append(action.detail)

    @property
    def mutation_count(self) -> int:
        return sum(action.action in {"create", "rename", "move", "reorder", "overwrite"} for action in self.actions)

    def render(self, limit: int = 1800) -> str:
        counts = {name: sum(action.action == name for action in self.actions) for name in ("create", "rename", "move", "reorder", "overwrite", "reuse", "blocked", "warning")}
        lines = [
            "**CROSAIM · Plan de reconciliación**",
            " · ".join(f"{name}: {count}" for name, count in counts.items() if count),
        ]
        for action in self.actions:
            if action.action in {"blocked", "warning"}:
                lines.append(f"- {action.action.upper()} · {action.kind}:{action.key} · {action.detail}")
        if not self.blocked:
            lines.append("Sin bloqueos detectados. El plan solo gestionará recursos CROSAIM declarados.")
        rendered = "\n".join(lines)
        return rendered if len(rendered) <= limit else rendered[: limit - 40] + "\n… Consulta los logs para el informe completo."


class RuntimeConfig:
    """Stores a versioned reconciler registry outside Git on persistent storage."""

    def __init__(self) -> None:
        configured = os.getenv("CROSAIM_RUNTIME_CONFIG_PATH", "data/crosaim-discord.json")
        self.path = Path(configured)

    def load(self) -> dict[str, object]:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return {"schema_version": RUNTIME_SCHEMA_VERSION, "channels": {}, "roles": {}, "registry_status": "missing"}
        except (OSError, ValueError):
            return {"schema_version": RUNTIME_SCHEMA_VERSION, "channels": {}, "roles": {}, "registry_status": "invalid"}
        if not isinstance(raw, dict):
            return {"schema_version": RUNTIME_SCHEMA_VERSION, "channels": {}, "roles": {}, "registry_status": "invalid"}
        raw.setdefault("channels", {})
        raw.setdefault("roles", {})
        raw.setdefault("registry_status", "healthy")
        return raw

    def save(
        self,
        *,
        guild_id: int,
        channels: dict[str, int],
        roles: dict[str, int],
        desired_state_hash: str,
        actor: str,
        run_id: str,
        outcomes: list[ReconciliationAction],
    ) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        content = {
            "schema_version": RUNTIME_SCHEMA_VERSION,
            "guild_id": str(guild_id),
            "desired_state_hash": desired_state_hash,
            "updated_at": datetime.now(timezone.utc).isoformat(),
            "actor": actor,
            "run_id": run_id,
            "channels": {key: str(value) for key, value in sorted(channels.items())},
            "roles": {key: str(value) for key, value in sorted(roles.items())},
            "outcomes": [action.__dict__ for action in outcomes],
            "registry_status": "healthy",
        }
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(content, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        temporary.replace(self.path)


def desired_state_hash() -> str:
    document = {
        "roles": [(role.key, role.name, role.aliases, role.position, sorted(role.capabilities)) for role in BUSINESS_ROLE_SPECS],
        "layout": [
            (category.key, category.name, category.position, category.access, [(channel.key, channel.name, str(channel.kind), channel.position, channel.access, channel.aliases) for channel in category.channels])
            for category in LAYOUT
        ],
    }
    return hashlib.sha256(json.dumps(document, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()[:16]


class DiscordLayoutManager:
    """Plans and applies conservative, non-destructive CROSAIM Discord drift repair."""

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

    def _registry_id(self, section: Literal["channels", "roles"], key: str) -> int | None:
        registry = self.runtime_config.load()
        if str(registry.get("guild_id") or "") not in {"", str(self.guild.id)}:
            return None
        values = registry.get(section, {})
        raw = values.get(key) if isinstance(values, dict) else None
        return int(str(raw)) if str(raw).isdigit() else None

    def _find_unique_role(self, spec: RoleSpec) -> tuple[discord.Role | None, str | None]:
        persisted = self._registry_id("roles", spec.key)
        if persisted:
            found = self.guild.get_role(persisted)
            if found:
                return found, None
        matches = [role for role in self.guild.roles if self._name_matches(role.name, (spec.name, *spec.aliases))]
        if len(matches) > 1:
            return None, f"Hay {len(matches)} roles equivalentes para {spec.name}; requiere resolución manual."
        return (matches[0], None) if matches else (None, None)

    def _find_unique_category(self, spec: CategorySpec) -> tuple[discord.CategoryChannel | None, str | None]:
        matches = [category for category in self.guild.categories if self._name_matches(category.name, (spec.name, spec.key))]
        if len(matches) > 1:
            return None, f"Hay {len(matches)} categorías equivalentes para {spec.name}; requiere resolución manual."
        return (matches[0], None) if matches else (None, None)

    def _find_unique_channel(self, spec: ChannelSpec, category: discord.CategoryChannel | None) -> tuple[discord.abc.GuildChannel | None, str | None]:
        persisted = self._registry_id("channels", spec.key)
        if persisted:
            found = self.guild.get_channel(persisted)
            if found and found.type == spec.kind:
                return found, None
        candidates = (spec.name, spec.key, *spec.aliases)
        matches = [channel for channel in self.guild.channels if channel.type == spec.kind and self._name_matches(channel.name, candidates)]
        if category:
            same_parent = [channel for channel in matches if getattr(channel, "category_id", None) == category.id]
            if len(same_parent) == 1:
                return same_parent[0], None
            if len(same_parent) > 1:
                return None, f"Hay {len(same_parent)} canales equivalentes de {spec.name} en {category.name}; requiere resolución manual."
        if len(matches) == 1:
            return matches[0], None
        if len(matches) > 1:
            return None, f"Hay {len(matches)} canales equivalentes para {spec.name}; requiere resolución manual."
        # Type collision is intentionally blocked rather than changed or deleted.
        type_conflicts = [channel for channel in self.guild.channels if self._name_matches(channel.name, candidates)]
        if type_conflicts:
            return None, f"Existe un recurso con tipo incompatible para {spec.name}; requiere resolución manual."
        return None, None

    def _desired_overwrites(self, access: str, roles: dict[str, discord.Role]) -> dict[discord.abc.Snowflake, discord.PermissionOverwrite]:
        overwrites: dict[discord.abc.Snowflake, discord.PermissionOverwrite] = {}
        if access == "information":
            overwrites[self.guild.default_role] = discord.PermissionOverwrite(view_channel=True, send_messages=False, add_reactions=False, read_message_history=True)
        elif access == "community":
            overwrites[self.guild.default_role] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, embed_links=True, attach_files=True)
        elif access == "competitive":
            overwrites[self.guild.default_role] = discord.PermissionOverwrite(view_channel=True, send_messages=False, read_message_history=True)
            for key in ("SUPER_ADMIN", "ADMIN", "MANAGER", "COACH", "SCOUT", "CONTENT", "PLAYER", "TRYOUT"):
                if key in roles:
                    overwrites[roles[key]] = discord.PermissionOverwrite(send_messages=True, read_message_history=True)
        elif access == "voice":
            overwrites[self.guild.default_role] = discord.PermissionOverwrite(view_channel=True, connect=True, speak=True)
        else:
            # Recruiting and operations are private by default. This deliberately
            # uses business roles rather than Discord's Administrator permission.
            overwrites[self.guild.default_role] = discord.PermissionOverwrite(view_channel=False)
            keys = RECRUITING_ROLE_KEYS if access == "recruiting" else OPERATIONS_ROLE_KEYS
            for key in keys:
                if key in roles:
                    overwrites[roles[key]] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, embed_links=True, attach_files=True, connect=True, speak=True)
        if self.bot_member:
            overwrites[self.bot_member] = discord.PermissionOverwrite(view_channel=True, send_messages=True, read_message_history=True, embed_links=True, attach_files=True, connect=True, speak=True, move_members=True)
        return overwrites

    def _required_permission_report(self) -> tuple[dict[str, bool], list[str]]:
        member = self.bot_member
        if not member:
            return {}, ["No se pudo resolver el miembro del bot en este servidor."]
        permissions = member.guild_permissions
        required = {
            "Manage Channels": permissions.manage_channels,
            "Manage Roles": permissions.manage_roles,
            "Move Members": permissions.move_members,
            "Send Messages": permissions.send_messages,
            "Embed Links": permissions.embed_links,
            "Attach Files": permissions.attach_files,
            "View Channels": permissions.view_channel,
            "Read Message History": permissions.read_message_history,
            "Administrator": permissions.administrator,
        }
        findings = [f"Falta permiso del bot: {name}" for name, granted in required.items() if not granted and name != "Administrator"]
        if required["Administrator"]:
            findings.append("El bot tiene Administrator; el reconciliador exige mínimo privilegio y no aplicará cambios hasta retirarlo.")
        return required, findings

    def _preflight(self, plan: ReconciliationPlan) -> None:
        required, findings = self._required_permission_report()
        for finding in findings:
            plan.add(ReconciliationAction("blocked", "permission", "bot", finding))
        member = self.bot_member
        if not member:
            return
        for key, role in plan.roles.items():
            if role.is_default():
                plan.add(ReconciliationAction("blocked", "role", key, "No se puede administrar el rol @everyone."))
            elif role >= member.top_role:
                plan.add(ReconciliationAction("blocked", "role", key, f"El rol {role.name} está en o por encima del rol del bot."))
        registry = self.runtime_config.load()
        registry_status = str(registry.get("registry_status") or "healthy")
        registered_guild = str(registry.get("guild_id") or "")
        if registry_status != "healthy":
            plan.add(ReconciliationAction("warning", "registry", "runtime", "El registro persistido es inválido o no existe; se reconstruirá sin borrar recursos."))
        if registered_guild and registered_guild != str(self.guild.id):
            plan.add(ReconciliationAction("warning", "registry", "runtime", "El registro pertenece a otro servidor y será ignorado."))

    def plan(self) -> ReconciliationPlan:
        plan = ReconciliationPlan()
        for role_spec in BUSINESS_ROLE_SPECS:
            role, problem = self._find_unique_role(role_spec)
            if problem:
                plan.add(ReconciliationAction("blocked", "role", role_spec.key, problem))
                continue
            if role:
                plan.roles[role_spec.key] = role
                plan.add(ReconciliationAction("reuse", "role", role_spec.key, role.name))
                if role.position != role_spec.position:
                    plan.add(ReconciliationAction("reorder", "role", role_spec.key, f"posición {role.position} → {role_spec.position}"))
            else:
                plan.add(ReconciliationAction("create", "role", role_spec.key, role_spec.name))

        for category_spec in LAYOUT:
            category, problem = self._find_unique_category(category_spec)
            if problem:
                plan.add(ReconciliationAction("blocked", "category", category_spec.key, problem))
                continue
            if category:
                plan.categories[category_spec.key] = category
                plan.add(ReconciliationAction("reuse", "category", category_spec.key, category.name))
                if category.name != category_spec.name:
                    plan.add(ReconciliationAction("rename", "category", category_spec.key, f"{category.name} → {category_spec.name}"))
                if category.position != category_spec.position:
                    plan.add(ReconciliationAction("reorder", "category", category_spec.key, f"posición {category.position} → {category_spec.position}"))
            else:
                plan.add(ReconciliationAction("create", "category", category_spec.key, category_spec.name))

            for channel_spec in category_spec.channels:
                channel, channel_problem = self._find_unique_channel(channel_spec, category)
                if channel_problem:
                    plan.add(ReconciliationAction("blocked", "channel", channel_spec.key, channel_problem))
                    continue
                if channel:
                    plan.channels[channel_spec.key] = channel
                    plan.add(ReconciliationAction("reuse", "channel", channel_spec.key, channel.name))
                    if channel.name != channel_spec.name:
                        plan.add(ReconciliationAction("rename", "channel", channel_spec.key, f"{channel.name} → {channel_spec.name}"))
                    if category and getattr(channel, "category_id", None) != category.id:
                        plan.add(ReconciliationAction("move", "channel", channel_spec.key, f"{getattr(channel, 'category', None)} → {category_spec.name}"))
                    if channel.position != channel_spec.position:
                        plan.add(ReconciliationAction("reorder", "channel", channel_spec.key, f"posición {channel.position} → {channel_spec.position}"))
                    plan.add(ReconciliationAction("overwrite", "channel", channel_spec.key, f"aplicar matriz {channel_spec.access}"))
                else:
                    plan.add(ReconciliationAction("create", "channel", channel_spec.key, channel_spec.name))
        self._preflight(plan)
        return plan

    async def apply(self, plan: ReconciliationPlan, *, actor: str) -> ReconciliationPlan:
        if plan.blocked:
            raise PermissionError("No se aplicó el plan: " + " · ".join(plan.blocked[:4]))
        run_id = uuid.uuid4().hex[:12]
        reason = f"CROSAIM reconcile run={run_id} actor={actor}"[:512]

        # Create roles before they are referenced by access-control overwrites.
        for spec in BUSINESS_ROLE_SPECS:
            role = plan.roles.get(spec.key)
            if role is None:
                role = await self.guild.create_role(name=spec.name, permissions=discord.Permissions.none(), reason=reason)
                plan.roles[spec.key] = role
                self.created.append(f"rol:{spec.name}")
            else:
                self.reused.append(f"rol:{role.name}")
            if role.position != spec.position:
                await role.edit(position=spec.position, reason=reason)
            self.roles[spec.key] = role.id

        for category_spec in LAYOUT:
            category = plan.categories.get(category_spec.key)
            overwrites = self._desired_overwrites(category_spec.access, plan.roles)
            if category is None:
                category = await self.guild.create_category(category_spec.name, position=category_spec.position, overwrites=overwrites, reason=reason)
                plan.categories[category_spec.key] = category
                self.created.append(f"categoría:{category_spec.name}")
            else:
                await category.edit(name=category_spec.name, position=category_spec.position, overwrites=overwrites, reason=reason)
                self.reused.append(f"categoría:{category.name}")

        for category_spec in LAYOUT:
            category = plan.categories[category_spec.key]
            for channel_spec in category_spec.channels:
                channel = plan.channels.get(channel_spec.key)
                overwrites = self._desired_overwrites(channel_spec.access, plan.roles)
                if channel is None:
                    kwargs: dict[str, object] = {"name": channel_spec.name, "category": category, "position": channel_spec.position, "overwrites": overwrites, "reason": reason}
                    if channel_spec.kind == TEXT:
                        channel = await self.guild.create_text_channel(**kwargs)
                    elif channel_spec.kind == VOICE:
                        channel = await self.guild.create_voice_channel(**kwargs)
                    else:
                        raise RuntimeError(f"Tipo de canal no soportado para {channel_spec.key}")
                    self.created.append(f"canal:{channel_spec.name}")
                else:
                    await channel.edit(name=channel_spec.name, category=category, position=channel_spec.position, overwrites=overwrites, reason=reason)
                    self.reused.append(f"canal:{channel.name}")
                self.channels[channel_spec.key] = channel.id

        self.runtime_config.save(
            guild_id=self.guild.id,
            channels=self.channels,
            roles=self.roles,
            desired_state_hash=desired_state_hash(),
            actor=actor,
            run_id=run_id,
            outcomes=plan.actions,
        )
        return plan

    async def audit(self) -> str:
        plan = self.plan()
        permissions, _ = self._required_permission_report()
        registry = self.runtime_config.load()
        report = [
            f"Servidor: **{self.guild.name}** (`{self.guild.id}`)",
            f"Categorías: {len(self.guild.categories)} · Canales: {len(self.guild.channels)} · Roles: {len(self.guild.roles)}",
            "Permisos bot: " + ", ".join(f"{label}={'sí' if granted else 'no'}" for label, granted in permissions.items()),
            f"Registry: {registry.get('registry_status', 'healthy')} · versión objetivo: {desired_state_hash()}",
            plan.render(),
        ]
        return "\n".join(report)

    async def setup(self, *, actor: str = "unknown") -> str:
        plan = self.plan()
        await self.apply(plan, actor=actor)
        return self.summary(plan)

    def summary(self, plan: ReconciliationPlan | None = None) -> str:
        plan = plan or self.plan()
        chunks = [
            "**CROSAIM reconcile finalizado**",
            f"Creados: {len(self.created)} · Reutilizados/normalizados: {len(self.reused)} · Acciones planificadas: {plan.mutation_count}",
            "Roles canónicos: " + ", ".join(spec.key for spec in BUSINESS_ROLE_SPECS),
            "No se han eliminado ni fusionado recursos ambiguos; se reportan para resolución manual.",
            "La configuración de IDs y el resultado se guardaron en el almacenamiento persistente.",
        ]
        if self.warnings or plan.warnings:
            chunks.append("Avisos: " + " · ".join((self.warnings + plan.warnings)[:4]))
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

    @app_commands.command(name="plan", description="Muestra cambios CROSAIM antes de aplicar la reconciliación.")
    async def plan_command(self, interaction: discord.Interaction) -> None:
        try:
            guild = await self._require_manager(interaction)
            await interaction.response.defer(ephemeral=True, thinking=True)
            report = (await DiscordLayoutManager(guild).audit())
            await interaction.followup.send(report[:1900], ephemeral=True)
        except app_commands.CheckFailure as error:
            await interaction.response.send_message(str(error), ephemeral=True)

    @app_commands.command(name="setup", description="Reconcilia la estructura CROSAIM sin eliminar recursos ambiguos.")
    async def setup(self, interaction: discord.Interaction) -> None:
        try:
            guild = await self._require_manager(interaction)
            await interaction.response.defer(ephemeral=True, thinking=True)
            manager = DiscordLayoutManager(guild)
            result = await manager.setup(actor=f"discord:{interaction.user.id}")
            await interaction.followup.send(result[:1900], ephemeral=True)
        except (PermissionError, RuntimeError, app_commands.CheckFailure) as error:
            if interaction.response.is_done():
                await interaction.followup.send(f"No se ejecutó el setup: {error}", ephemeral=True)
            else:
                await interaction.response.send_message(f"No se ejecutó el setup: {error}", ephemeral=True)
        except discord.Forbidden:
            message = "Discord rechazó la reconciliación. Revisa permisos mínimos, jerarquía y que el bot no tenga Administrator."
            if interaction.response.is_done():
                await interaction.followup.send(message, ephemeral=True)
            else:
                await interaction.response.send_message(message, ephemeral=True)

    @app_commands.command(name="status", description="Muestra permisos, drift, jerarquía y registro CROSAIM.")
    async def status(self, interaction: discord.Interaction) -> None:
        try:
            guild = await self._require_manager(interaction)
            await interaction.response.defer(ephemeral=True, thinking=True)
            report = await DiscordLayoutManager(guild).audit()
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


def managed_role_keys_for_member(member: discord.Member) -> set[str]:
    role_names = {normalize(role.name) for role in member.roles}
    keys: set[str] = set()
    for spec in BUSINESS_ROLE_SPECS:
        if any(normalize(candidate) in role_names for candidate in (spec.name, *spec.aliases)):
            keys.add(spec.key)
    return keys


def can_manage_recruiting(member: discord.Member) -> bool:
    if member.guild_permissions.manage_guild or member.guild_permissions.manage_roles:
        return True
    return has_capability(managed_role_keys_for_member(member), "applications.review")
