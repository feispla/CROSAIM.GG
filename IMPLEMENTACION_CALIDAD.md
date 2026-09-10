# Protección contra postulaciones duplicadas y pruebas

## 1. Dónde proteger los duplicados

La protección debe existir en dos capas:

1. **Aplicación (`bot.py`)**: evita volver a publicar en el canal de revisión cuando Discord reintenta un evento.
2. **Base de datos (`supabase_schema.sql`)**: impide duplicados por condición de carrera cuando dos procesos reciben el mismo evento al mismo tiempo.

La clave más fiable para el flujo actual es `discord_postulacion_message_id`, porque Discord conserva el ID del mensaje aunque el webhook se regenere. No conviene usar solamente nombre o username: pueden cambiar y varias personas pueden compartirlos.

### Cambio recomendado en `supabase_db.py`

Añade una consulta reutilizable:

```python
def find_submission_by_message(message_id: int) -> dict[str, Any] | None:
    result = (
        client()
        .table("postulaciones")
        .select("id, estado, discord_revision_message_id, discord_aprobacion_message_id")
        .eq("discord_postulacion_message_id", str(message_id))
        .limit(1)
        .execute()
    )
    return result.data[0] if result.data else None
```

### Cambio recomendado en `bot.py`

Importa la función:

```python
from supabase_db import (
    find_submission_by_message,
    save_submission,
    set_review_message,
    set_status,
)
```

Antes de llamar a `save_submission` dentro de `on_message`:

```python
existing = find_submission_by_message(message.id)
if existing:
    logging.warning(
        "Postulación duplicada ignorada: message_id=%s submission_id=%s",
        message.id,
        existing["id"],
    )
    return
```

### Restricción de base de datos

Ejecuta una vez en Supabase:

```sql
create unique index if not exists postulaciones_discord_message_unique_idx
  on public.postulaciones (discord_postulacion_message_id)
  where discord_postulacion_message_id is not null;
```

La comprobación en Python mejora la experiencia y el índice evita duplicados bajo concurrencia. Para hacer el flujo completamente idempotente, captura también el error de restricción única de Supabase: si ocurre, vuelve a consultar el mensaje y termina silenciosamente en vez de enviar una segunda tarjeta a revisión.

Antes de activar el índice, comprueba duplicados existentes:

```sql
select discord_postulacion_message_id, count(*)
from public.postulaciones
where discord_postulacion_message_id is not null
group by discord_postulacion_message_id
having count(*) > 1;
```

## 2. Ejecutar las pruebas

Las pruebas añadidas no utilizan Discord, internet ni un proyecto Supabase real:

```bash
python -m pip install -r requirements.txt
pytest -q
```

`tests/test_image_generator.py` verifica que:

- se generen archivos PNG con el tamaño esperado;
- los nombres se limpien correctamente para el nombre del archivo;
- el estado aprobado y en revisión cambie el nombre de salida;
- la foto del integrante se componga en la tarjeta;
- URLs no válidas no provoquen una descarga.

`tests/test_supabase_db.py` usa un cliente falso y verifica el mapeo de datos, el manejo de respuestas vacías y la actualización del estado de aprobación.

## 3. Mejoras competitivas para la web CROSAIM

### Experiencia del jugador

El producto debería ofrecer un formulario corto, móvil y progresivo: primero Discord, región, rol y rango; después clips, disponibilidad y experiencia. Mostrar una barra de progreso, ejemplos de respuestas y validación en tiempo real reduce abandonos. La página debe cargar rápido desde móvil y permitir subir clips sin obligar al usuario a abandonar el formulario.

### Conversión y confianza

Conviene crear una página de reclutamiento con una propuesta de valor concreta: qué recibe el jugador, qué nivel competitivo busca CROSAIM, tiempos de respuesta y próximos pasos. Añade roster visible, resultados, clips destacados, staff, reglas de convivencia y testimonios verificables. Incluye estados claros de la postulación: recibida, en revisión, entrevista, tryout y decisión.

### Competición y datos

El panel debería incluir un pipeline tipo Kanban, filtros por rol/rango/región, etiquetas, notas privadas, historial de cambios y asignación de entrevistadores. Un sistema de puntuación configurable puede evaluar mecánicas, comunicación, disponibilidad, experiencia y encaje cultural; la decisión final debe seguir siendo humana. Mide conversión por fuente, tiempo hasta primera respuesta, tiempo por etapa, abandono y tasa de aceptación.

### Operación y automatización

Añade recordatorios automáticos para entrevistas, enlaces de calendario, plantillas de mensajes, control de duplicados por Discord ID y un registro de auditoría. Los webhooks deberían tener firma, timestamp, nonce e idempotency key. Usa reintentos con backoff, una cola de eventos y estados `pending`, `processing`, `delivered` y `failed` para no perder sincronizaciones.

### Seguridad y privacidad

Separa los datos públicos de los privados, aplica mínimo privilegio, cifra secretos, valida tipo y tamaño de archivos, limita URLs de imágenes y define retención/borrado de postulaciones. La clave `SUPABASE_SERVICE_ROLE_KEY` nunca debe llegar al navegador. Añade rate limiting, protección anti-spam y logs sin exponer tokens ni información personal innecesaria.

### Diferenciación

Para competir mejor, CROSAIM puede ofrecer perfiles de jugador con clips, métricas verificadas, disponibilidad y roles secundarios; un sistema de tryouts con rúbricas iguales para todos; y una experiencia de comunidad que conecte noticias, clips, roster y convocatorias. La ventaja no debe ser solamente visual: debe ser la velocidad, transparencia y consistencia del proceso de scouting.
