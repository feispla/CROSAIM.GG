---
name: crosaim-discord-supabase-sync
description: Implement and maintain CROSAIM player profiles, Manus OAuth plus Discord linking, Supabase event queues, and Discord bot synchronization. Use when connecting a scouting web app with Discord or operating the bot through GitHub and Railway.
---

# CROSAIM synchronization workflow

1. Inspect the web repository and bot repository separately. Do not assume the bot repository contains the web source.
2. Preserve Manus OAuth as the primary identity. Add Discord OAuth as a linked account.
3. Use `manus_user_id` for ownership and a unique `discord_id` for Discord identity.
4. Store player profiles, applications and a durable `discord_events` queue in Supabase.
5. Use idempotency keys for applications and profile versions for updates.
6. Keep Discord credentials, Supabase service role and sync secrets outside GitHub.
7. Let the bot consume events, publish to the review channel, and ACK only after successful delivery.
8. Keep Railway as the persistent worker. Use Docker as packaging and systemd only as an alternative server supervisor.
9. Run tests, compile checks and diff checks before committing.
10. Commit code, SQL migrations, payload examples, API contracts and documentation to GitHub.

## Event rule

Use text and links for web application and profile events. Do not generate the welcome graphic for ordinary synchronization. Generate the graphic only for an explicit approval or welcome announcement.

## Required references

Read `WEB_INTEGRATION_GUIDE.md`, `SYNC_CONTRACT.md`, `supabase_profile_schema.sql` and `examples/application_submitted.json` before implementing the web side.
