# CROSAIM Discord Bot

Bot Python para el flujo `POSTULACIÓN → REVISIÓN → ENTREVISTA → APROBADA/RECHAZADA → TRYOUT/ROSTER`, con botones, generación de imagen, roles y registro auditable en Supabase.

## Ejecutar localmente

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
Copy-Item .env.example .env
python bot.py
```

Configura el token, los IDs de canales y Supabase únicamente en `.env`. Nunca publiques `.env`.

Consulta `SUPABASE_HOSTING.md` para el esquema de base de datos y las opciones de alojamiento 24/7.

## Sincronización con el panel CROSAIM

El bot puede consultar la cola protegida de eventos del panel y publicar en Discord las nuevas postulaciones aprobadas, entrevistas, tryouts y clips. Configura en Railway las variables `CROSAIM_WEB_BASE_URL`, `CROSAIM_BOT_SYNC_SECRET`, `CLIPS_CHANNEL_ID` e `INTERVIEW_VOICE_CHANNEL_ID`. La clave `CROSAIM_BOT_SYNC_SECRET` debe ser idéntica en la web y en Railway.

Cuando una postulación pasa a entrevista, el bot menciona al candidato y, si el usuario ya está conectado a un canal de voz y el bot tiene el permiso **Mover miembros** con una posición superior en la jerarquía, lo mueve a `𝑽𝑨𝑳𝑶𝑹𝑨𝑵𝑻`. Discord no permite mover automáticamente a un usuario que todavía no está conectado a voz; en ese caso el bot deja el aviso y el enlace del canal.

Las postulaciones recibidas desde el canal configurado se sincronizan con el panel mediante el ID del mensaje de Discord. Esto evita duplicados cuando Railway reintenta el proceso. La imagen de bienvenida se genera con el nombre, rol y rango reales del jugador al aprobarlo.

## Configuración del servidor

El comando administrativo `/crosaim setup` audita el servidor, reutiliza canales y roles equivalentes, crea solo los recursos faltantes y guarda los IDs descubiertos en `CROSAIM_RUNTIME_CONFIG_PATH`. Ejecutarlo dos veces no duplica canales. `/crosaim status` muestra los permisos, recursos faltantes y el estado de la configuración.

El directorio elegido para `CROSAIM_RUNTIME_CONFIG_PATH` debe pertenecer a un volumen persistente del proveedor de ejecución. El bot requiere **Gestionar canales**, **Gestionar roles** y **Mover miembros** para ejecutar por completo setup, roles automáticos y entrevistas; no requiere Administrator.

Antes de desplegar la actualización, ejecutar `supabase_migration_application_state.sql` en Supabase. Esa migración incorpora los siete estados operativos, timestamps y la tabla de auditoría sin exponer secretos.

## Integración web, perfiles y Discord

La documentación reutilizable está organizada en estos archivos:

- `WEB_INTEGRATION_GUIDE.md`: flujo de Manus OAuth, conexión Discord y endpoints.
- `supabase_profile_schema.sql`: migración versionada para perfiles, cuentas Discord y eventos.
- `examples/application_submitted.json`: payload oficial de una postulación web.
- `SYNC_CONTRACT.md`: contrato de eventos, ACK y reintentos.
- `ARQUITECTURA_CROSAIM.md`: arquitectura completa de GitHub, Railway, bot, web y Supabase.
- `skills/crosaim-discord-supabase-sync/SKILL.md`: habilidad reutilizable para otra cuenta de Manus.

La migración SQL debe revisarse contra el esquema real de la web antes de ejecutarse en Supabase. GitHub guarda la migración y la documentación; Supabase guarda los datos. La tarjeta gráfica no se genera para eventos normales de perfiles o postulaciones.
