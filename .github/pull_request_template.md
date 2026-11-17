## Qué cambia y por qué

<!-- Resumen del cambio. Enlaza la tarea con "Closes #N" y menciona la historia (Refs #N). -->

Closes #

## Cómo se probó

<!-- Pruebas automatizadas o pasos manuales para cada criterio de aceptación de la tarea. -->

## Checklist de seguridad

<!-- Marca cada punto o escribe "N/A" con la razón. Catálogo: docs/seguridad.md -->

**Autor**

- [ ] Los requisitos de seguridad de la historia o tarea están cubiertos (o el cambio no tiene impacto de seguridad).
- [ ] Respeta los invariantes de `AGENTS.md`: todo pasa por el gateway, denegación por defecto, sin datos sensibles al modelo, aprobación en riesgo alto, auditoría y solo servidores MCP propios.
- [ ] Las entradas y la configuración nuevas se validan y no hay riesgo de inyección.
- [ ] No hay secretos, claves ni datos reales en el diff, en los logs ni en la configuración versionada.
- [ ] Las dependencias nuevas están justificadas.
- [ ] Hay pruebas nuevas o actualizadas (`uv run pytest`) y `ruff` está sin errores; las pruebas usan solo datos ficticios.
- [ ] Se actualizó la documentación (README, ADR o arquitectura) si cambió la configuración, los comandos o la superficie expuesta.
- [ ] Si lo generó o asistió un agente de IA, una persona lo revisó.

**Revisor**

- [ ] Revisé el checklist anterior y dejé comentarios donde corresponde.
- [ ] La CI está en verde.
