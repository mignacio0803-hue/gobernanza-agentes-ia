# AGENTS.md — Contexto para agentes de código y colaboradores

Este archivo es el punto de entrada para cualquier agente de IA (Claude Code, Gemini CLI, Copilot, Codex, etc.) o persona que trabaje en este repositorio. Léelo completo antes de tomar una tarea.

## 1. Qué es este proyecto

Prototipo académico (MVP) de una **plataforma de gobernanza para agentes de IA**. Permite que un agente opere sobre los sistemas de una empresa (en este prototipo, **Odoo Community**: CRM y Facturación) de forma **controlada, auditable y sin exponer datos sensibles** al proveedor del modelo.

Tres capas:

| Capa | Qué hace | Módulos |
|---|---|---|
| Operaciones | Servidores MCP propios que exponen herramientas sobre Odoo, configurables por archivo | `src/odoo_client`, `src/mcp_servers` |
| Gobernanza | Gateway MCP que aplica políticas (denegación por defecto), clasifica riesgo y exige aprobación humana en riesgo alto | `src/gateway` (policy, approvals) |
| Seguridad y trazabilidad | Enmascaramiento de datos sensibles y registro de auditoría encadenado con hash | `src/gateway` (masking, vault, audit) |

Además: un agente CLI (`src/agent`) que usa Gemini y un panel web (`src/panel`) para supervisores y auditores.

Documentación clave: `docs/arquitectura.md` (diseño y flujo), `docs/decisiones/` (ADR), `docs/amenazas.md` (STRIDE).

## 2. Invariantes (no negociables)

Cualquier cambio que rompa uno de estos puntos debe rechazarse en revisión:

1. **Todo pasa por el gateway.** El agente nunca se conecta directamente a los servidores MCP ni a Odoo.
2. **Denegación por defecto.** Una herramienta o acción sin política explícita no se lista ni se ejecuta.
3. **Ningún dato sensible en claro sale del entorno local.** RUT, correo, teléfono y dirección se enmascaran antes de llegar al modelo. Todo lo enviado al modelo se registra en `logs/llm_outbound.jsonl` y debe poder auditarse.
4. **Riesgo alto ⇒ aprobación humana.** Nunca se ejecuta una acción de riesgo alto sin una aprobación registrada.
5. **Toda decisión se audita.** Acciones permitidas, bloqueadas, pendientes, aprobadas, rechazadas y fallidas quedan en el registro encadenado. El registro es de solo escritura.
6. **Sin secretos en el repositorio.** Credenciales y claves solo en `.env` (ver `.env.example`).
7. **Solo servidores MCP propios.** No se agregan servidores MCP de terceros.
8. **Solo datos ficticios.** Nunca se usan datos reales de personas o empresas.

## 3. Stack y convenciones

- Python 3.12, gestor de dependencias **uv** (`uv sync`, `uv run`).
- SDK MCP oficial para Python (`mcp`, con `FastMCP`), FastAPI + Jinja2 para el panel, SQLite para estado, `pydantic` para configuración, `google-genai` para Gemini.
- Calidad: `ruff` (lint + formato), `pytest` (unitarias en `tests/unit`, integración en `tests/integration` con marca `@pytest.mark.integration`, seguridad en `tests/security`).
- Tipado estático en funciones públicas. Docstrings breves.
- **Idioma:** identificadores de código en inglés; documentación, mensajes de commit, issues y textos de interfaz en español. Los nombres de herramientas MCP expuestas al agente van en español (`crm.buscar_clientes`), porque el agente conversa en español.
- Configuración en `config/` (YAML), nunca valores fijos en el código.

Comandos habituales:

```bash
uv sync                          # instalar dependencias
docker compose up -d odoo db     # levantar Odoo
uv run python scripts/seed_odoo.py
uv run pytest -m "not integration"   # pruebas rápidas
uv run pytest                    # todas (requiere Odoo arriba)
uv run ruff check . && uv run ruff format --check .
```

## 4. Cómo trabajar con las tareas (issues)

El backlog vive en GitHub Issues con jerarquía **Épica → Historia → Tarea** (sub-issues).

1. **Toma una tarea** (`tipo:tarea`) del sprint activo (milestone) que no esté bloqueada.
2. **Lee el contexto completo antes de programar:** la tarea, su historia padre (criterios de aceptación de usuario), su épica y las tareas de las que depende. Si usas la CLI: `gh issue view <n> --comments`.
3. **Rama:** `feat/<n>-descripcion-corta` (o `fix/`, `docs/`, `chore/`).
4. **Implementa solo el alcance de la tarea.** Si descubres trabajo adicional, crea un issue nuevo en vez de ampliar el PR.
5. **Pruebas:** cada criterio de aceptación de la tarea debe quedar cubierto por una prueba o por una verificación manual descrita en el PR.
6. **PR:** usa la plantilla, enlaza con `Closes #<n>` y marca la lista de verificación.
7. **Al cerrar** la última tarea de una historia, verifica los criterios de aceptación de la historia y ciérrala.

### Definición de terminado (DoD)

- [ ] Criterios de aceptación de la tarea cumplidos.
- [ ] Pruebas nuevas en verde y `ruff` sin errores.
- [ ] Ningún invariante de la sección 2 roto.
- [ ] Documentación actualizada si cambió configuración, comandos o arquitectura.
- [ ] Revisión cruzada aprobada por el otro integrante.

## 5. Mapa de responsabilidades (referencial)

- **Integración (operaciones):** Odoo, `odoo_client`, `mcp_servers`, agente, panel.
- **Gobernanza y seguridad:** `gateway` (políticas, aprobaciones, enmascaramiento, auditoría).

Las asignaciones concretas se hacen en cada issue.
