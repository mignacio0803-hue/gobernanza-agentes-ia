# Catálogo de requisitos de seguridad

Cada historia, tarea, spike o bug marca en su sección **🔐 Requisitos de seguridad** los códigos de este catálogo que debe cumplir, y agrega al menos un criterio de seguridad verificable (formato *Dado / cuando / entonces*) por requisito marcado.

Los requisitos traducen los invariantes de `AGENTS.md` (sección 2) a controles verificables. Si un cambio rompe uno de ellos, se rechaza en revisión.

| Código | Requisito | Invariante | Cómo se verifica |
|---|---|---|---|
| RS-GW-01 | Todo pasa por el gateway: el agente nunca se conecta directo a un servidor MCP ni a Odoo. | 1 | El agente solo conoce la dirección del gateway; prueba de que no existe otra conexión configurada. |
| RS-POL-01 | Denegación por defecto: una herramienta o acción sin política explícita no se lista ni se ejecuta. | 2 | Prueba con una herramienta sin política: no aparece en el listado y su invocación se rechaza. |
| RS-RSK-01 | Riesgo alto exige aprobación humana registrada antes de ejecutarse. | 4 | Prueba de que una acción de riesgo alto queda pendiente y no llega a Odoo sin aprobación. |
| RS-INJ-01 | Las instrucciones que llegan dentro de los datos (correos, notas, descripciones) no amplían los permisos del agente. | 2, 4 | Escenario de inyección de instrucciones: la acción inducida se bloquea y se registra. |
| RS-DAT-01 | RUT, correo, teléfono y dirección se enmascaran antes de enviarse al proveedor del modelo. | 3 | Revisión de `logs/llm_outbound.jsonl`: cero datos sensibles en claro. |
| RS-DAT-02 | Todo lo enviado al modelo queda registrado en `logs/llm_outbound.jsonl`. | 3 | Cada llamada al modelo tiene su entrada en el registro de salida. |
| RS-DAT-03 | Solo datos ficticios: nunca datos reales de personas o empresas. | 8 | Los datos de carga y de prueba se generan con `faker` o son inventados. |
| RS-AZ-01 | Mínimo privilegio: el usuario técnico de Odoo solo tiene los permisos que usan las herramientas. | 2 | Prueba de que una operación fuera de esos permisos falla en Odoo. |
| RS-AUD-01 | Toda decisión (permitida, bloqueada, pendiente, aprobada, rechazada, fallida) se registra en la traza encadenada, de solo escritura. | 5 | Prueba por cada tipo de decisión; la verificación de integridad detecta cambios. |
| RS-AUD-02 | La traza y los logs no contienen datos sensibles en claro. | 3, 5 | Búsqueda de patrones de RUT, correo y teléfono en la traza y los logs. |
| RS-AUT-01 | El panel exige autenticación y aplica roles (supervisor, auditor, administrador) en el servidor. | 4, 5 | Prueba de acceso sin sesión y con un rol sin permiso: ambos se rechazan. |
| RS-VAL-01 | Las entradas y la configuración se validan antes de usarse (esquemas `pydantic`). | 2 | Prueba con configuración o argumentos inválidos: error claro, sin ejecución parcial. |
| RS-SEC-01 | Sin secretos en el repositorio: credenciales y claves solo en `.env`. | 6 | Revisión del diff y `.gitignore`; `.env.example` sin valores reales. |
| RS-MCP-01 | Solo servidores MCP propios; no se agregan servidores de terceros. | 7 | Revisión de `config/mcp_servers.yaml` y de las dependencias. |

## Datos involucrados

Cada issue indica qué datos toca:

- **PII ficticia** (nombres, RUT, correos, teléfonos, direcciones).
- **Comerciales** (oportunidades, montos, facturas).
- **Credenciales** (claves de API de Odoo o Gemini, clave de la bóveda, secreto del panel).
- **Ninguno.**
