# Contrato de sincronización web ↔ Supabase ↔ Discord

El repositorio del bot es la base operativa versionada. **GitHub guarda el código y la configuración no secreta; Supabase guarda los datos y la cola de eventos; el proceso de ejecución mantiene el bot conectado a Discord.** Los tokens nunca se guardan en GitHub.

## Eventos que el bot consume

La API de la web debe devolver eventos pendientes desde `GET /api/discord/events` usando el header `x-crosaim-sync-secret`. Cada evento debe tener:

```json
{
  "id": 123,
  "eventType": "application_submitted",
  "payload": "{\"playerName\":\"RazeOne\",\"discordUserId\":\"123456789012345678\",\"role\":\"Duelista\",\"rank\":\"Diamante\",\"region\":\"LATAM\",\"photoUrl\":\"https://...\",\"socials\":{\"twitch\":\"...\",\"youtube\":\"...\"}}"
}
```

El bot publica en `REVISION_CHANNEL_ID` los siguientes tipos:

- `application_submitted` o `application_created`: nueva postulación web, con tarjeta y datos del jugador.
- `profile_updated` o `player_profile_updated`: cambios de foto, redes, rol, rango, región, disponibilidad o descripción.

También mantiene los eventos existentes `application_interview`, `application_approved`, `application_rejected`, `roster_tryout` y `clip_uploaded`.

## Confirmación y reintentos

Después de publicar correctamente, el bot llama a `POST /api/discord/events/{id}/ack` con `{ "ok": true }`. Si falla Discord, llama con `{ "ok": false, "error": "..." }`. La web debe conservar los eventos fallidos para reintento y no eliminarlos antes de un ACK exitoso.

La tabla de eventos debe tener una clave única para evitar duplicados, por ejemplo:

```sql
create unique index if not exists discord_events_idempotency_idx
  on discord_events (idempotency_key);
```

La clave puede ser `application:{application_id}:submitted` o `profile:{profile_id}:updated:{version}`. Una actualización debe incrementar `version` para que un cambio legítimo no se descarte.

## Campos recomendados del perfil

```text
playerName, discordUserId, discordUsername, photoUrl,
role, secondaryRoles, rank, peakRank, region, availability,
bio, socials, clips, applicationId, profileVersion
```

El perfil web debe vincularse al usuario Manus mediante `manus_user_id` y a Discord mediante `discordUserId`. Manus OAuth sigue siendo el inicio de sesión principal; Discord OAuth solo añade la identidad vinculada.

## Ejecución 24/7

La imagen `Dockerfile` permite ejecutar el bot en Railway, Render Worker, Fly.io o un servidor Linux. Configura estas variables como secretos del proveedor:

```env
DISCORD_BOT_TOKEN=...
SUPABASE_URL=...
SUPABASE_SERVICE_ROLE_KEY=...
CROSAIM_WEB_BASE_URL=https://crosaimdash-h9bxzuxs.manus.space
CROSAIM_BOT_SYNC_SECRET=...
```

No subas `.env` al repositorio. El workflow de GitHub ejecuta pruebas, pero **GitHub Actions no debe usarse como proceso 24/7**: sus runners son temporales. El bot debe ejecutarse en un worker o servicio persistente.
