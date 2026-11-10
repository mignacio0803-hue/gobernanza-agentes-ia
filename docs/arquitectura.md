# Arquitectura del prototipo

> Documento base. Se completa y ajusta en la tarea de arquitectura del Sprint 1. Las decisiones se registran como ADR en `docs/decisiones/`.

## Componentes

```
 Usuario (operador)                     Supervisor / Auditor
        │                                        │
        ▼                                        ▼
 ┌──────────────┐  MCP (HTTP)   ┌───────────────────────────────────────┐
 │ Agente CLI   │──────────────▶│ Gateway de gobernanza (FastAPI)       │
 │ (Gemini)     │◀──────────────│  /mcp    servidor MCP agregador       │
 └──────┬───────┘               │  /panel  panel web                     │
        │ /api/mask             │  /api    enmascaramiento, estado       │
        └──────────────────────▶│                                       │
                                │  policy · approvals · masking · vault │
                                │  audit (SQLite, hash encadenado)      │
                                └──────────────┬────────────────────────┘
                                               │ MCP (stdio)
                              ┌────────────────┴───────────────┐
                              ▼                                ▼
                     ┌─────────────────┐             ┌──────────────────┐
                     │ MCP server CRM  │             │ MCP server       │
                     │                 │             │ Facturación      │
                     └────────┬────────┘             └────────┬─────────┘
                              └───────────┬───────────────────┘
                                          ▼ API externa (usuario técnico)
                                 ┌──────────────────┐
                                 │ Odoo Community   │
                                 │ (Docker + PG)    │
                                 └──────────────────┘
```

## Flujo de una acción

1. El operador escribe en el agente. El agente **enmascara** su mensaje vía `POST /api/mask` antes de enviarlo a Gemini.
2. Gemini propone invocar una herramienta (por ejemplo, `facturacion.validar_factura`) con argumentos que pueden contener *tokens* (`<RUT_7f3a>`).
3. El agente envía la invocación al **gateway** por MCP.
4. El gateway:
   1. **Evalúa la política** (agente + herramienta + argumentos). Sin política ⇒ bloqueo.
   2. **Clasifica el riesgo**: bajo ⇒ ejecuta; medio ⇒ ejecuta y marca para revisión; alto ⇒ crea una **solicitud de aprobación** y responde al agente con su identificador.
   3. **Desenmascara** los argumentos (bóveda local) y ejecuta en el servidor MCP correspondiente.
   4. **Enmascara** el resultado antes de devolverlo al agente.
   5. **Registra** la decisión y el resultado en el **registro de auditoría** encadenado con hash.
5. El supervisor aprueba o rechaza en el panel. Al aprobar, el gateway ejecuta la acción y la registra.

## Datos persistentes (SQLite, `data/gateway.db`)

| Tabla | Contenido |
|---|---|
| `approvals` | Solicitudes de aprobación y su estado |
| `audit_log` | Registro de solo escritura, cada fila con `prev_hash` y `hash` |
| `vault` | Token ↔ valor real cifrado (Fernet, clave en `.env`) |

## Configuración (`config/`)

| Archivo | Uso |
|---|---|
| `mcp_servers.yaml` | Qué servidores levanta el gateway y qué herramientas expone cada uno |
| `policies.yaml` | Política activa: agentes, herramientas permitidas, nivel de riesgo, condiciones |
| `policies/base/*.yaml` | Plantillas base que la empresa selecciona y ajusta |
| `masking.yaml` | Campos y patrones considerados sensibles |
| `users.yaml` | Usuarios del panel con contraseña cifrada y rol |

## Decisiones iniciales (a formalizar como ADR)

- **ADR-001:** La gobernanza se implementa como **gateway MCP** (proxy agregador). Así cualquier cliente MCP queda gobernado sin modificar los servidores.
- **ADR-002:** Python 3.12 + uv; SDK MCP oficial.
- **ADR-003:** Gemini como proveedor inicial detrás de una interfaz `LLMProvider` intercambiable. En el plan gratuito, Google puede usar el contenido para mejorar sus productos: solo se envían datos ficticios y enmascarados.
- **ADR-004:** SQLite para estado local (aprobaciones, auditoría, bóveda).
- **ADR-005:** API externa de Odoo a utilizar (se decide en el Sprint 1 según la versión fijada).
