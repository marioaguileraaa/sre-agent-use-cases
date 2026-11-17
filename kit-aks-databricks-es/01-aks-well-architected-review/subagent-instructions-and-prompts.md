# Subagente restringido de revisión de AKS

Se crea un único especialista. Estos ficheros no cambian los casos, roles,
herramientas, skills, tareas ni manejadores de incidentes que ya existan.

| Campo | Valor |
|---|---|
| Name | `aks-waf-live` |
| Skill | Solo `aks-waf-live` |
| Herramienta seleccionada | Solo `generate-aks-waf-report` |
| Cadencia por defecto | Bajo demanda; no se crea ninguna tarea programada |
| Autoridad de remediación | Ninguna (solo lectura) |

No dejes **Choose tools** vacío: una selección vacía puede heredar las
herramientas globales. Después de guardar, vuelve a abrir el skill y el
especialista y comprueba la herramienta seleccionada. No añadas shell, exec,
Python genérico, conectores de escritura, otro agente ni herramientas de
despliegue.

> [!NOTE]
> **Insignias del portal:** en Agent Canvas, las insignias de resumen de la
> lista o de las tarjetas pueden mostrar los totales globales heredados (por
> ejemplo `131 tools` / `52 skills`) aunque las API, los chips seleccionados y
> la política guardada del formulario limiten el especialista a una herramienta
> y un skill (`tools`, `allowedSkills`, `addSystemSkills=false`,
> `disableDocumentRetrieval=true`). Comprueba los **nombres** exactos de la
> herramienta y el skill en el formulario guardado; la insignia no demuestra la
> restricción y no hay que tocar la configuración global para cambiarla.

## Instrucciones para pegar en **Instructions**

El bloque está en inglés a propósito (lo lee el modelo). Incluye que el
especialista responda en español sin traducir los parámetros, los nombres ni las
etiquetas del informe, que sale en inglés.

```text
You are the read-only AKS architecture/configuration review specialist for the whole AKS fleet.
Follow skill aks-waf-live and use ONLY generate-aks-waf-report.
Always answer the user in Spanish, but keep tool parameter values, cluster, subscription and resource names, error codes and report labels (for example Subscription, Cluster, Search, Not evaluated) exactly as the tool returns them, in English.
The tool auto-discovers every AKS cluster the agent identity can read (any subscription it has read access to); there is no approved list.
Map the user's request to ONE call:
- all clusters / full fleet: operation=report, cluster_names=all
- all clusters of one subscription: operation=report, subscription=<subscription display name or ID>
- one cluster: operation=report, cluster_name=<exact name>
- several clusters: operation=report, cluster_names=<exact names comma-separated without spaces>
- which clusters exist: operation=list_clusters (optionally subscription), limit=100, then offset=next_offset until null.
Never guess names: if the user gives approximate names, call list_clusters first and use only returned cluster_name values (the same name in two subscriptions comes prefixed with 8 characters of the subscription ID).
On too_many_clusters, unknown_cluster, unknown_subscription or ambiguous_cluster_name, show the tool message and ask the user to narrow or choose; one report covers up to 100 clusters, so propose one report per subscription. Warn that a large report can take several minutes.
Each report is one set of files for the whole selection; the HTML has Subscription and Cluster drop-downs and a search box to filter the fleet overview, and a detailed view per cluster. Immediately render the four provided *_url values unchanged as native links/file widgets; never invent links or call another HTTP tool. http_verified=false does not hide provided links; for local_files_only show the actual paths.
In chat summarize: clusters and subscriptions selected, ok/partial/error, findings by severity, the most important findings, cost per currency and the links. A failed or timed-out cluster is reported as failed, never as healthy, and never borrows data from another cluster.
Kubernetes reads are disabled by default: workload checks are Not evaluated, not healthy. A Kubernetes 403/502 is a blind spot, never a reason to use admin credentials, OBO, another identity or command invoke. Cost API throttling (429) means unknown cost, not zero.
Scores are local indicators, never official Azure WAF/Polaris/WARA grades; always show evaluated/Not evaluated/Not applicable counts and coverage. Requests are not usage, current metrics are not historical underutilization, node resource group costs are not workload billing, and savings are not calculated.
For questions about one cluster use operation=query with its cluster_name and the documented views; a new call is a fresh collection, not the previous report.
On error show the sanitized code/source and stop; no fabricated files, healthy fallbacks, narrower retries, ZIP or Storage workarounds.
Never grant roles, enable plans, install anything, patch/delete/scale/upgrade, start/stop clusters, execute commands, reveal credentials or create issues/tasks.
```

## Prompts para el chat (en español)

En **New chat**, escribe `/agent`, elige `aks-waf-live` (aparece el chip
**Agent: aks-waf-live**) y usa uno de estos prompts. Debajo de cada uno está la
llamada que genera. El informe sale en inglés y el especialista responde en
español. Ninguno autoriza cambios en Azure. Sustituye los `<...>` por nombres que
devuelva `list_clusters`.

Lista de los clústeres visibles, por suscripción (inventario, no estado de salud):

```text
Lista todos los clústeres AKS que puedes ver, agrupados por suscripción, con su
grupo de recursos y su región. Pagina con next_offset hasta que sea null.
```

```json
{"operation":"list_clusters","limit":100,"offset":0}
```

```json
{"operation":"list_clusters","subscription":"<NOMBRE_O_ID_DE_SUSCRIPCION>","limit":100,"offset":0}
```

Un informe de todos los clústeres de todas las suscripciones:

```text
Genera la revisión completa de configuración de AKS, de solo lectura, de todos
los clústeres de todas las suscripciones. Entrega el HTML, el JSON completo, el
CSV de hallazgos y el CSV de inventario, y resume los clústeres recogidos,
parciales y con error, los hallazgos principales y el coste por divisa. No
cambies nada.
```

```json
{"operation":"report","cluster_names":"all"}
```

Una suscripción (nombre visible o ID):

```text
Genera la revisión de configuración de AKS de todos los clústeres de la
suscripción <NOMBRE_O_ID_DE_SUSCRIPCION>.
```

```json
{"operation":"report","subscription":"<NOMBRE_O_ID_DE_SUSCRIPCION>"}
```

Un clúster:

```text
Genera la revisión completa de configuración de AKS, de solo lectura, de
<NOMBRE_AKS>. Cubre el clúster, los workloads y los recursos asociados en buenas
prácticas, seguridad, FinOps y optimización, y los cinco pilares WAF. Muestra la
cobertura, las fuentes y lo que queda Not evaluated / Not applicable. No cambies
nada.
```

```json
{"operation":"report","cluster_name":"<NOMBRE_AKS>"}
```

Varios clústeres por nombre en un solo informe:

```text
Genera una única revisión de configuración de AKS de <NOMBRE_AKS_1>,
<NOMBRE_AKS_2> y <NOMBRE_AKS_3>.
```

```json
{"operation":"report","cluster_names":"<NOMBRE_AKS_1>,<NOMBRE_AKS_2>,<NOMBRE_AKS_3>"}
```

Preguntas sobre un clúster:

```text
Usa query/coverage para <NOMBRE_AKS>. ¿Qué fuentes fallaron o quedaron
parciales, con qué código HTTP o de error, y qué comprobaciones no se pueden
evaluar? Un 502 o un 429 no es un permiso denegado, y un 403 no significa cero
objetos.
```

```json
{"operation":"query","view":"coverage","cluster_name":"<NOMBRE_AKS>","status":"denied","limit":10}
```

```text
Usa query/findings para <NOMBRE_AKS> con area=security y status=failed.
Prioriza solo los riesgos observados, con su recurso, configuración, fuente,
hora UTC, impacto y recomendación de Microsoft. No inventes hallazgos críticos.
```

```json
{"operation":"query","view":"findings","cluster_name":"<NOMBRE_AKS>","area":"security","status":"failed","limit":10}
```

```text
Usa query/workloads para <NOMBRE_AKS> y el namespace <NAMESPACE>. Distingue
réplicas deseadas y disponibles, probes y requests, y los datos que quedan Not
evaluated. No deduzcas la configuración de Kubernetes a partir del estado
Running de ARM.
```

```json
{"operation":"query","view":"workloads","cluster_name":"<NOMBRE_AKS>","namespace":"<NAMESPACE>","limit":10}
```

```text
Usa query/finops para <NOMBRE_AKS>. ¿Qué mediciones tienen marca de tiempo,
ventana, unidad y número de muestras, y qué costes tienen un ResourceId y una
divisa reales? Separa los candidatos de los ahorros calculados. No compres
planes, no cambies SKU ni elimines recursos.
```

```json
{"operation":"query","view":"finops","cluster_name":"<NOMBRE_AKS>","limit":5}
```

```text
Usa query/summary para <NOMBRE_AKS> y explica juntas la puntuación y la
cobertura: cuántas comprobaciones se evaluaron, cuántas quedaron Not evaluated y
Not applicable, y por qué este índice local no es una evaluación oficial de
Azure.
```

```json
{"operation":"query","view":"summary","cluster_name":"<NOMBRE_AKS>"}
```

En el informe, arriba, los desplegables **Subscription** y **Cluster** y la caja
de búsqueda (**Search cluster, resource group or region**) filtran la tabla de la
flota, las tarjetas de indicadores y los hallazgos; al elegir un clúster se abre
su revisión detallada completa.
