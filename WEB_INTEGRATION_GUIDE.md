# Guía de integración de la web CROSAIM

## Objetivo

Mantener **Manus OAuth como inicio de sesión principal** y añadir Discord como identidad vinculada. El usuario inicia sesión con Manus, conecta su cuenta de Discord y administra un perfil de jugador con foto, redes, rol, rango, región, disponibilidad y descripción.

La web debe guardar la información en Supabase y publicar eventos para que el bot los envíe al canal `REVISION_CHANNEL_ID`.

## Archivos de referencia

- `supabase_profile_schema.sql`: migración versionada para perfiles, vínculo Discord y cola.
- `examples/application_submitted.json`: payload oficial de una postulación web.
- `SYNC_CONTRACT.md`: contrato entre la web, Supabase y el bot.
- `ARQUITECTURA_CROSAIM.md`: arquitectura completa del sistema.
- `skills/crosaim-discord-supabase-sync/SKILL.md`: procedimiento reutilizable para otra cuenta de Manus.

## Flujo de conexión Discord

```text
Manus OAuth inicia sesión
    ↓
GET /api/discord/connect
    ↓
Discord OAuth2 con scope identify
    ↓
GET /api/discord/callback
    ↓
Validar state y code en backend
    ↓
Consultar Discord /users/@me
    ↓
Guardar manus_user_id + discord_id
    ↓
Actualizar avatar y username
    ↓
Crear evento profile_updated
```

La aplicación debe configurar en Discord Developer Portal una redirect URI de backend. El `state` debe estar firmado y relacionado con la sesión Manus. No se debe confiar en un `manus_user_id` enviado por el navegador.

## Endpoints recomendados

| Método | Endpoint | Responsabilidad |
|---|---|---|
| GET | `/api/discord/connect` | Crear la URL OAuth2 con `state` seguro |
| GET | `/api/discord/callback` | Validar callback, obtener identidad y guardar vínculo |
| POST | `/api/profile` | Guardar cambios del perfil autenticado |
| POST | `/api/applications` | Crear postulación y evento `application_submitted` |
| GET | `/api/discord/events` | Entregar lote de eventos pendientes al bot |
| POST | `/api/discord/events/:id/ack` | Confirmar entrega o registrar fallo |

Las rutas de eventos deben exigir `x-crosaim-sync-secret`. Las rutas de perfil deben usar la sesión Manus. El navegador no debe insertar directamente eventos como `delivered` ni modificar `discord_id` sin pasar por OAuth.

## Perfil mínimo

El perfil utiliza `manus_user_id` como propietario y `discord_id` como identidad vinculada. Los campos recomendados son `display_name`, `photo_url`, `role`, `secondary_roles`, `rank`, `peak_rank`, `region`, `availability`, `bio`, `socials` y `profile_version`.

## Evento de postulación

Crear un registro en `discord_events` con una clave idempotente como `application:{applicationId}:submitted`. El payload debe seguir `examples/application_submitted.json`.

El bot publica los datos como texto y enlaces en `REVISION_CHANNEL_ID`. **No se genera tarjeta gráfica para este evento.** La tarjeta solo se usa opcionalmente en una bienvenida o aprobación.

## Evento de actualización

Para cambios importantes del perfil, crear `profile_updated` con una clave como `profile:{profileId}:updated:{profileVersion}`. Incrementar `profile_version` dentro de la misma operación que actualiza el perfil y crea el evento.

## Seguridad

- Mantener los secretos en Manus/WebDev/Railway, nunca en GitHub.
- No enviar `SUPABASE_SERVICE_ROLE_KEY` al frontend.
- Validar tamaño y tipo de fotos.
- Validar URLs de redes sociales.
- Aplicar RLS en Supabase.
- Guardar solo el Discord ID y datos públicos necesarios.
- Permitir desconectar Discord mediante una ruta autenticada.
- Registrar auditoría de conexión, desconexión y cambios de perfil.

## Orden de implementación

1. Revisar cómo la web actual guarda usuarios Manus.
2. Aplicar `supabase_profile_schema.sql` como migración revisada.
3. Configurar Discord OAuth y sus redirect URIs.
4. Implementar las rutas de conexión y callback.
5. Crear la pantalla de edición de perfil.
6. Crear `application_submitted` y `profile_updated` en la cola.
7. Configurar el secreto compartido con Railway.
8. Probar una postulación en staging.
9. Confirmar que el bot publica en revisión y hace ACK.
10. Promover a producción.
