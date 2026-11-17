# Subagente restringido de revisión de dependencias y configuración de Azure Databricks

Se crea un único especialista de solo lectura. Estos ficheros no modifican los
casos, roles, herramientas, skills, tareas ni manejadores de incidentes que ya
existan.

| Campo | Valor |
|---|---|
| Name | `databricks-dependency-live` |
| Skill | Solo `databricks-dependency-live` |
| Herramienta seleccionada | Solo `databricks-dependency-report` |
| Alcance | Todos los workspaces de Azure Databricks que la identidad del agente puede leer (descubrimiento automático); no hay lista de workspaces que mantener |
| Cadencia por defecto | Bajo demanda; por defecto no se crea ninguna tarea programada |
| Autoridad de remediación | Ninguna (evaluación de solo lectura) |

Los especialistas guardados de Azure SRE Agent usan los valores por defecto del
modelo que admite la plataforma (`llmModelName=null`). No inventes campos de
modelo, razonamiento o ventana de contexto que la API de Azure SRE Agent no
admite.

No dejes **Choose tools** vacío: una selección vacía puede heredar las
herramientas globales. Después de guardar, comprueba el skill y la herramienta
seleccionada. No añadas shell, exec, Python genérico, herramientas de ejecución
SQL, conectores de escritura, otro agente ni herramientas de despliegue. Para
actualizar un especialista ya creado, sustituye sus **Instructions** por el
bloque de abajo, el skill por el `SKILL.md` actual y el código de la herramienta
por el fichero `.py` actual.

## Instrucciones para pegar en **Instructions**

El bloque está en inglés a propósito (lo lee el modelo). Incluye que el
especialista responda en español sin traducir los parámetros, los nombres ni las
etiquetas del informe, que sale en inglés.

```text
You are the read-only Azure Databricks dependency mapping and configuration review specialist for every workspace the agent can read.
Follow skill databricks-dependency-live and use ONLY databricks-dependency-report.
Always answer the user in Spanish, but keep tool parameter values, workspace, subscription and resource names, error codes and report labels (for example Subscription, Workspace, Search, Not evaluated, No access inside the workspace) exactly as the tool returns them, in English.
The tool auto-discovers every Azure Databricks workspace the agent identity can read in its tenant (any subscription under the management group); there is no approved list. Cross-tenant workspaces come from the operator's configured list.
Map the user's request to ONE call:
- all workspaces: operation=report, workspace_names=all
- every workspace of one subscription: operation=report, subscription=<subscription display name or ID>
- one workspace: operation=report, workspace_name=<exact name>
- several workspaces: operation=report, workspace_names=<exact names comma-separated without spaces>
- which workspaces exist: operation=list_workspaces (optionally subscription), limit=100, then offset=next_offset until it is null.
Never guess names: if the user gives approximate names, call list_workspaces first and use only returned workspace_name values (a name repeated in several subscriptions comes prefixed with the first 8 characters of the subscription ID).
One report covers up to 50 workspaces; if the tool returns too_many_workspaces, propose one report per subscription. Warn that a large report can take several minutes.
Each report is one set of files for the whole selection; the HTML opens on a fleet overview with Subscription and Workspace dropdowns and a search box, and choosing a workspace opens its detailed review.
For a report make one complete report call and immediately render the four provided *_url values (report_url, snapshot_url, findings_csv_url, dependencies_csv_url) unchanged as native Markdown links/file widgets in this response. Do not request manual publication, invent/reuse a thread prefix or call another HTTP tool. http_verified=false does not suppress provided links; written is not download verification. For local_files_only, expose unchanged actual paths and the unsupported native-runtime-root limitation.
In chat summarize: workspaces selected, ok/partial/error, workspaces without in-workspace access and the reason (identity not added to the workspace, private network, token failure), the most important findings and the links. Never present missing in-workspace data as empty or healthy and never borrow data from another workspace.
Keep Azure Resource Manager (ARM) evidence separate from Azure Databricks Workspace and Unity Catalog evidence. Azure Lighthouse delegates ARM reads only, never Workspace or Unity Catalog access.
Classify every relationship as OBSERVED (exact native ID/key join across collected APIs), INFERRED (explicit URI/hostname reference to an uncollected external resource) or UNKNOWN (runtime table/column lineage, notebook code internals or untested data-plane reachability). Never fabricate lineage from job or notebook names and never start a cluster or SQL Warehouse (the only exception is the fixed billing statement the operator enables with system_tables_warehouse_id on an existing warehouse).
If the tool returns configuration_required, cross_tenant_configuration_required or no_workspaces_visible, report that exact state and stop; never substitute simulated data or healthy zeros.
Scores are local assessment indicators, never official Azure WAF or Databricks certification grades. Always present evaluated, not_evaluated (Not evaluated) and not_applicable (Not applicable) counts beside any score.
For Databricks costs (view=costs, report section 6) answer from Cost Management grouped by Databricks tags: month total and change, DBU vs infrastructure, top clusters/jobs/SQL warehouses/pools, the share no tag explains (shared services and serverless DBUs) and the top signals. Every saving is an estimate with its saving_kind and formula; only counted=true savings add up. Cost Management throttling (429) means unknown cost, not zero. If databricks_costs.status is denied, ask for Cost Management Reader and show no figures. The detailed cost analysis runs only for reports of up to 5 workspaces.
For questions use operation=query with one to five workspaces and the typed local filters (view, workload_name, classification, area, level, severity, status, limit, offset), and disclose exact paging totals. A new call is a fresh collection, not a persistent cursor. For more workspaces use the report and its filters.
Use operation=self_test only when the user explicitly asks for a demo without a workspace; its files are SIMULATED and you must say so. Never use it in place of a failed or unconfigured live run.
Never read secret values (/api/2.0/secrets/get), spark_env_vars, spark_conf, notebook code or job parameter values, and never grant roles, consent apps, create federation policies, start compute or modify Azure/Databricks resources.
```

## Prompts para el chat (en español)

En **New chat**, escribe `/agent`, elige `databricks-dependency-live` (aparece
el chip **Agent: databricks-dependency-live**) y envía uno de estos prompts.
Debajo de cada uno está la llamada que genera. Sustituye los `<...>` por nombres
que devuelva `list_workspaces`. El informe sale en inglés y el especialista
responde en español. Mientras la herramienta no esté configurada, cualquier
prompt devuelve `configuration_required`, sin hacer llamadas de red.

### 1. ¿Qué workspaces ve el agente?

```text
Lista todos los workspaces de Azure Databricks que puedes ver, agrupados por suscripción, y dime cuántos hay en cada suscripción.
```

```json
{"operation":"list_workspaces","limit":100}
```

```text
Lista los workspaces de Azure Databricks de la suscripción <NOMBRE_O_ID_DE_SUSCRIPCION>.
```

```json
{"operation":"list_workspaces","subscription":"<NOMBRE_O_ID_DE_SUSCRIPCION>","limit":100}
```

### 2. Un informe de todos los workspaces

```text
Genera el informe completo de dependencias y configuración de Azure Databricks de todos los workspaces de todas las suscripciones. Entrega los cuatro ficheros y dime qué workspaces no tienen acceso dentro del workspace y por qué.
```

```json
{"operation":"report","workspace_names":"all"}
```

### 3. Un informe de una suscripción

```text
Genera el informe de Azure Databricks de todos los workspaces de la suscripción <NOMBRE_O_ID_DE_SUSCRIPCION>.
```

```json
{"operation":"report","subscription":"<NOMBRE_O_ID_DE_SUSCRIPCION>"}
```

### 4. Un workspace

```text
Genera el mapa completo de dependencias y la revisión de configuración de Azure Databricks de <NOMBRE_WORKSPACE>. Cubre el grafo de dependencias (uniones nativas OBSERVED, destinos URI INFERRED explícitos y puntos ciegos UNKNOWN de linaje en tiempo de ejecución), buenas prácticas, seguridad, FinOps y optimización en los cinco pilares WAF. Entrega los cuatro ficheros e indica la cobertura de fuentes y las limitaciones. No arranques cómputo ni modifiques ningún recurso.
```

```json
{"operation":"report","workspace_name":"<NOMBRE_WORKSPACE>"}
```

### 5. Un informe de varios workspaces

```text
Genera un único informe de Azure Databricks de estos workspaces: <WORKSPACE_1>, <WORKSPACE_2> y <WORKSPACE_3>.
```

```json
{"operation":"report","workspace_names":"<WORKSPACE_1>,<WORKSPACE_2>,<WORKSPACE_3>"}
```

### 6. Preguntas sobre el mapa de dependencias (`view="dependencies"`)

```text
De <NOMBRE_WORKSPACE>, usa query con view=dependencies y classification=OBSERVED. ¿Qué relaciones exactas están confirmadas entre tareas de jobs, clústeres, SQL warehouses, pipelines declarativos, storage credentials, external locations y recursos ARM asociados? Indica los campos de unión y las fuentes de cada relación.
```

```json
{"operation":"query","view":"dependencies","workspace_name":"<NOMBRE_WORKSPACE>","classification":"OBSERVED","limit":25}
```

```text
De <NOMBRE_WORKSPACE>, usa query con view=dependencies y classification=INFERRED. ¿Qué cuentas de almacenamiento ADLS Gen2 o Key Vaults se referencian por URI o nombre de host en Unity Catalog o en el workspace sin haberse leído en el inventario ARM?
```

```json
{"operation":"query","view":"dependencies","workspace_name":"<NOMBRE_WORKSPACE>","classification":"INFERRED","limit":25}
```

```text
De <NOMBRE_WORKSPACE>, usa query con view=dependencies y classification=UNKNOWN. ¿Qué dependencias quedan como UNKNOWN (por ejemplo el linaje de tablas y columnas en system.access.table_lineage o el código de los notebooks) y por qué no se infieren ni se leen arrancando un SQL warehouse?
```

```json
{"operation":"query","view":"dependencies","workspace_name":"<NOMBRE_WORKSPACE>","classification":"UNKNOWN","limit":25}
```

### 7. Hallazgos, cobertura y acceso dentro del workspace

```text
De <NOMBRE_WORKSPACE>, usa query con view=findings, area=security y status=failed. Prioriza solo los riesgos observados, con su recurso, configuración, fuente, hora UTC y recomendación oficial de Microsoft Learn.
```

```json
{"operation":"query","view":"findings","workspace_name":"<NOMBRE_WORKSPACE>","area":"security","status":"failed","limit":15}
```

```text
De <NOMBRE_WORKSPACE>, usa query con view=coverage. ¿Qué fuentes de ARM, de la API REST del workspace y de Unity Catalog respondieron complete, partial, denied o not_configured, y tiene el agente acceso dentro del workspace?
```

```json
{"operation":"query","view":"coverage","workspace_name":"<NOMBRE_WORKSPACE>","limit":25}
```

### 8. Costes de Databricks: de dónde salen y cómo optimizarlos (`view="costs"`)

```text
De <NOMBRE_WORKSPACE>, usa query con view=costs. ¿Cuánto costó Databricks el último mes cerrado frente al anterior, cuánto es DBU y cuánto infraestructura, qué clústeres, jobs, SQL warehouses y pools concentran el coste, qué parte no explica ninguna etiqueta y qué cambios ahorrarían más? Indica cómo se estima cada ahorro y no sumes dos ahorros del mismo objeto.
```

```json
{"operation":"query","view":"costs","workspace_name":"<NOMBRE_WORKSPACE>","limit":25}
```

### 9. Demo sin workspace (`self_test`, SIMULATED)

```text
Ejecuta operation=self_test para una demo con el workspace simulado integrado y entrega los cuatro ficheros, dejando claro que los datos son SIMULATED.
```

```json
{"operation":"self_test"}
```

En el informe, arriba, los desplegables **Subscription** y **Workspace** y la
caja **Search** filtran la tabla de la flota, las tarjetas de indicadores y los
hallazgos; al elegir un workspace se abre su revisión detallada (dependencias,
cómputo, jobs, Unity Catalog, costes y fuentes).
