# Gobernanza de agentes de IA (prototipo)

Prototipo académico que permite a un agente de IA operar sobre Odoo Community (CRM y Facturación) de forma **controlada, auditable y sin exponer datos sensibles**: conectores MCP configurables, políticas con denegación por defecto, aprobación humana en acciones de riesgo alto, enmascaramiento de datos y registro de auditoría encadenado con hash.

- Contexto para colaboradores y agentes de IA: [`AGENTS.md`](AGENTS.md)
- Arquitectura: [`docs/arquitectura.md`](docs/arquitectura.md)
- Backlog (fuente de verdad de los issues): [`backlog/backlog.yaml`](backlog/backlog.yaml)

## Cargar el backlog en GitHub (una sola vez)

Requisitos: [GitHub CLI](https://cli.github.com/) autenticada (`gh auth login`) con permisos sobre este repositorio, y Python 3 con PyYAML.

```bash
pip install pyyaml
python scripts/crear_backlog.py --repo <usuario>/<repositorio> --dry-run   # revisar
python scripts/crear_backlog.py --repo <usuario>/<repositorio>             # crear
```

El script crea etiquetas, los milestones de cada sprint y 60 issues (6 épicas, 14 historias y 40 tareas), los enlaza como sub-issues y registra las dependencias. Es re-ejecutable: no duplica issues con el mismo título.

## Puesta en marcha

Se completa durante el Sprint 1 (tareas de entorno y repositorio base).
