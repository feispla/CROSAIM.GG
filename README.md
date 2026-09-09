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
