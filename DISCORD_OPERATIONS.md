# CROSAIM Discord Operations Contract

**CROSAIM Discord Bot** manages a declared server topology. It uses a conservative desired-state reconciler: it can create missing CROSAIM roles, categories, and channels, and it can normalize the managed objects it resolves unambiguously. It never deletes or merges a resource. Duplicate or type-conflicting matches are reported as manual-resolution blockers.

## Business-role contract

The server topology manages exactly the following CROSAIM business roles. They are separate from game-position and rank labels. The bot creates these roles with **no guild permissions**, and it must never have the Discord `Administrator` permission.

| Role | Dashboard | Players | Applications | Roster | Tournaments | Content | Settings / Discord topology |
| --- | --- | --- | --- | --- | --- | --- | --- |
| `SUPER_ADMIN` | View | Manage | Review | Manage | Manage | Publish | Manage |
| `ADMIN` | View | Manage | Review | Manage | Manage | Publish | Manage |
| `MANAGER` | View | Manage | Review | Manage | Manage | — | — |
| `COACH` | View | Manage | Review | Manage | — | — | — |
| `SCOUT` | View | Manage | Review | — | — | — | — |
| `CONTENT` | View | — | — | — | — | Publish | — |
| `PLAYER` | View | — | — | — | — | — | — |
| `TRYOUT` | View | — | — | — | — | — | — |
| `VIEWER` | View | — | — | — | — | — | — |

> Discord permissions and Control Center permissions are distinct layers. The table defines CROSAIM product capabilities. Channel overwrites are derived from the declared access class and are always least-privilege.

## Managed topology

The reconciler manages the categories `INFORMACIÓN`, `COMUNIDAD`, `COMPETITIVO`, `VOZ`, `TORNEOS`, `CROSAIM`, `BOT`, and `STAFF`. Public information channels are read-only, community channels permit normal member participation, and operations/recruiting channels remain private to the role matrix. The two channels named `resultados` are intentionally scoped to different parent categories. The reconciler matches channels inside the intended category before considering any global match.

The specific declared resource list lives in `crosaim_setup.py` as typed `CategorySpec` and `ChannelSpec` records. This makes the desired name, parent category, type, display order, and access class explicit and testable.

## Required bot permissions

The bot must be invited with the `bot` and `applications.commands` OAuth2 scopes and the following least-privilege permissions:

| Capability | Why it is required |
| --- | --- |
| Manage Channels | Create and reconcile declared categories/channels. |
| Manage Roles | Create and assign only CROSAIM managed roles. |
| Move Members | Move an interviewee already connected to voice. |
| Send Messages | Publish operational messages. |
| Embed Links | Publish rich operational links. |
| Attach Files | Publish optional approval cards. |
| View Channels | Access public and private declared targets. |
| Read Message History | Resolve and audit existing workflow messages. |

Enable **Message Content Intent** and **Server Members Intent** in the Discord Developer Portal because the bot reads authorized application webhook messages and resolves members for role/voice actions. Place the bot role above only the CROSAIM roles it must manage. Do not grant `Administrator`; `/crosaim plan`, `/crosaim status`, and `/crosaim setup` block application if it is enabled.

## Safe reconciliation workflow

1. Configure the environment variables from `.env.example` in the persistent bot host. Set `CROSAIM_RUNTIME_CONFIG_PATH` on a persistent volume.
2. Configure the exact authorized `POSTULACION_WEBHOOK_ID`. The bot rejects ordinary member messages and unknown webhooks in the applications channel before it can use its Supabase service identity.
3. In a staging guild, run `/crosaim plan`. Resolve every reported duplicate, type collision, or hierarchy blocker manually.
4. Run `/crosaim status`. Confirm every required bot permission is `sí`, `Administrator=no`, the registry is healthy, and the plan contains no blockers.
5. Run `/crosaim setup` only after the plan is clean. The command writes the versioned registry to the persistent path and supplies a run ID in Discord audit reasons.
6. Repeat `/crosaim plan`. A converged topology contains no create, rename, move, reorder, or overwrite mutations.

The runtime registry contains only resolved IDs, a desired-state hash, timestamp, actor, run ID, and sanitized outcomes. A missing, corrupt, stale, or cross-guild registry is reported and rebuilt safely; it never authorizes a destructive cleanup.

## Production boundary

The Discord bot requires a single, authoritative application and event store. The current repository contains Supabase-facing recruitment code while the Control Center still contains a MySQL/Drizzle queue. Do not treat both as peer sources of truth. The implementation plan is to converge Control Center writes and bot workflow records on Supabase before a production cutover, using a backup and a staging canary.

## Verification

Run locally before opening a pull request:

```bash
python -m pytest -q
python -m compileall -q bot.py image_generator.py supabase_db.py crosaim_setup.py
```

Run the end-to-end canary in a staging guild only after secrets and the persistent host are configured:

```text
authorized application webhook → Supabase application/audit record → review → interview → tryout → roster
```

The canary must assert one application record, one audit record per transition, one role assignment, and no duplicate Discord delivery.
