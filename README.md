# CROSAIM Discord Bot

Bot Python para el flujo `Postulación → Revisión → Aprobación`, con botones, generación de imagen y registro opcional en Supabase.

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
