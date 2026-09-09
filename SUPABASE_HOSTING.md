# Supabase y alojamiento 24/7

## Arquitectura recomendada

Supabase guarda las postulaciones; un proceso Python 24/7 mantiene conectado el bot de Discord. Supabase por sí solo no mantiene abierta la conexión Gateway de Discord.

## Alojamiento

| Opción | Coste aproximado | ¿Sirve para este bot? | Observación |
|---|---:|---|---|
| PC local | $0 | Solo mientras está encendida | Es la configuración actual. |
| Render Free | $0 | No recomendado para 24/7 | Los servicios web gratuitos se duermen después de 15 minutos sin tráfico; los workers no tienen plan Free. |
| Railway Free | $0 | Solo pruebas | Incluye $1 de crédito mensual; puede no cubrir un proceso 24/7. |
| Fly.io | Desde aproximadamente $2/mes para una máquina pequeña | Sí | Requiere tarjeta y debes controlar el consumo. |
| Servidor Linux básico | Desde aproximadamente $10/mes | Sí, recomendado | Permite mantener Python, Pillow y systemd con reinicio automático. |
| WebDev Reserved | Hasta ~$37.50/mes a uso completo, menos $10 de crédito mensual | Sí, si el proyecto se adapta | Es gestionado, pero requiere adaptar el bot a ese entorno. |

Para tu bot Python actual, recomiendo un servidor Linux básico porque evita reescribirlo y permite ejecutarlo como servicio `systemd`.

## Configurar Supabase

1. Crea o abre un proyecto en Supabase.
2. En **SQL Editor**, ejecuta `supabase_schema.sql`.
3. En **Project Settings > API**, copia la URL del proyecto y la clave privada `service_role`.
4. Instala la dependencia en el entorno virtual:

```powershell
python -m pip install supabase
```

5. Añade estas variables a `.env` local o al servidor:

```env
SUPABASE_URL=https://TU_PROYECTO.supabase.co
SUPABASE_SERVICE_ROLE_KEY=TU_CLAVE_PRIVADA
```

6. El módulo `supabase_db.py` ya contiene funciones para insertar una postulación, guardar el mensaje de revisión y cambiar el estado.

## Integración en bot.py

En `bot.py`, añade:

```python
from supabase_db import save_submission, set_review_message, set_status
```

Después de construir `data` dentro de `on_message`:

```python
submission_id = save_submission(
    data,
    webhook_message_id=message.id,
    webhook_id=message.webhook_id,
)
```

Después de enviar el mensaje a revisión:

```python
review_message = await target.send(
    content=summary,
    file=discord.File(path) if path else None,
    view=ReviewView(data, player),
)
set_review_message(submission_id, review_message.id)
```

Para guardar el resultado de aprobación, la vista debe recibir también `submission_id` y, después de enviar al canal de aprobación, ejecutar:

```python
set_status(
    submission_id,
    "aprobada",
    interaction.user.id,
    approval_message_id=approval_message.id,
)
```

Para rechazo:

```python
set_status(submission_id, "rechazada", interaction.user.id, reason="Motivo indicado por el moderador")
```

La clave `SUPABASE_SERVICE_ROLE_KEY` solo debe estar en el proceso del bot. Nunca la pongas en JavaScript del navegador, una web pública, GitHub o un archivo compartido públicamente.
