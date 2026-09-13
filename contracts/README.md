# Contratos compartidos CROSAIM Web–Discord

Este directorio contiene los contratos JSON versionados que comparten `crosaim-control-center` y `Crosaim.botdiscord`. La versión inicial es **1.0.0**.

## Archivos

| Contrato | Uso |
|---|---|
| `content_compliance.schema.json` | Respuesta estructurada de IA para revisión de contenido. Mantiene los campos del ejemplo original y añade confianza, revisión manual, versión de política y evidencia. |
| `sync_event.schema.json` | Sobre común para eventos publicados por la web y consumidos por el bot mediante la cola Discord. |
| `application_sync.schema.json` | Payload que el bot envía a `POST /api/discord/applications`. |

## Reglas

Todos los contratos usan JSON Schema Draft 2020-12, `additionalProperties: false` y versionado semántico. El campo `contractVersion` identifica la versión del sobre cuando está presente; no se debe cambiar la semántica de un contrato existente sin subir la versión mayor.

Los nombres actuales del sistema se conservan deliberadamente: `eventType`, `payload`, `discordUserId`, `discordUsername`, `applicationId`, `profileVersion` y `publicLookupNumber`.

El contrato no contiene secretos, tokens de sincronización ni credenciales. Las cabeceras HMAC continúan siendo responsabilidad de la capa de transporte y no deben entrar en `payload`.

## Evolución

- Cambios compatibles, como añadir un nuevo evento soportado, deben documentarse y aumentar la versión menor.
- Cambios incompatibles, como renombrar un campo obligatorio o cambiar su tipo, requieren una nueva versión mayor y una migración coordinada.
- Los consumidores deben rechazar propiedades desconocidas y eventos no incluidos en el `enum`.
- `content_compliance` debe devolver `violation_categories: []` y `violation_reason: ""` cuando `violates` sea `false`; esa regla semántica debe comprobarse además del JSON Schema.

## Ejemplo de `response_format`

```json
{
  "type": "json_schema",
  "json_schema": {
    "name": "content_compliance",
    "strict": true,
    "schema": "<contenido de content_compliance.schema.json>"
  }
}
```
