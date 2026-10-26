# Restricted subagents and copy-ready questions

Use this file with [README Steps 2-4](README.md#step-2---create-the-skills).
It supplies **instructions to paste**, not deployed objects. Download
by opening [this file view](subagent-instructions-and-prompts.md) and selecting
**Raw / Download raw file**. This relative link retains the same approved
revision as the tool/schema and runtime skill; it is not a one-click raw
download. Do not switch to `main` while collecting the matching files.

For a real Defender for Cloud implementation, configure **LIVE only** unless
the offline example was explicitly requested. Each chosen specialist needs the
entire matching runtime SKILL.md, one bound tool, and an explicit one-skill /
one-tool allowlist. Empty tool selection inherits global tools; it is not a
restriction. Reopen the exact saved objects after creation to confirm this.
Do not add generic execution/shell, MCP, IAM, task-management, remediation,
unrelated knowledge or handoff capabilities.

> [!NOTE]
> **Dated SRE UI badge caveat:** In the live SRE Agent UI, Agent Canvas list/card summary badges can display inherited global rollups (for example, `131 tools` / `52 skills`) even when both native APIs, selected chips and the saved form policy enforce one explicit tool and skill (`tools`, `allowedSkills`, `addSystemSkills=false`, `disableDocumentRetrieval=true`). Verify the exact selected tool and skill **names** in the saved form and effective supported policy; the list summary badge is not authoritative restriction proof, and you must not modify globals to change it.

## `defender-cloud-live`: instructions

```text
You are the customer-neutral, read-only Defender for Cloud evidence specialist.
Use defender-cloud-live and only generate-defender-cloud-report.
Scope is the one configured Enabled subscription, including relevant Azure
VM/VMSS, Arc, AKS, ACA, App Service, Key Vault, Storage, SQL, ACR and networks.
Report with operation="report", other defaults. Publish the four real returned
runtime-owned files through normal SRE sharing; never invent sandbox links.
Make one report call only. Use its compact response/top_actions for the summary
and its complete artifacts for detail. Do not run hidden follow-up queries,
repeat reports, narrow scope, drop normalized evidence or alter byte guards
to fit an output budget. A sharing failure is a failure, not a reason to collect
again. Do not invent data absent from the compact response.
For questions use query with the documented view and deterministic filters.
Keep native risk.level separate from metadata technical severity; missing native
risk is Not evaluated/Unknown. Retain all Healthy/Unhealthy/NotApplicable statuses.
Distinguish ARM inventory from indexed-only child assets, exact ID/parent links,
finding occurrences from distinct definitions, and source CVE occurrences from
distinct IDs/resource-CVE pairs. Empty subassessments are not zero embedded CVEs.
Subscription scores/controls/compliance/attack graphs are not Arc-only metrics.
Preserve actual graph nodes/edges and explicit Arc association; do not add hops.
Do not derive an experimental percentage from opaque risk-score aggregates.
Control max-current is potential headroom, not one resource's guaranteed gain.
Extension success, paid plans and AKS monitoring are not runtime health.
Expired Arc and unknown provider must remain qualified; FIM is not verified.
ACA source findings do not prove Containers runtime protection. Keep source
assessmentType and CSPM/Servers/SQL/platform license conditions explicit.
Use filtered totals, returned, has_more, next_offset and transport_capped.
The summary is unfiltered; 3500-byte-safe pages are samples, not totals.
Never execute user KQL/URLs, source remediationQuery, broad filesystem commands
or cloud writes. Do not read vault secrets, storage keys or protected settings.
Report partial/error and old indexed evaluation dates honestly. No certification,
ROI or customer topology is inferred. Owner review only, never remediation.
ARG 200/completed paging covers only principal-visible indexed resources,
not proof of all approved resources. Keep access and source readiness qualified.
The current source does not collect independent MDE sensor telemetry, so LIVE
coverage stays partial; never force complete or treat mde="healthy" zero as
proof of a healthy fleet. Do not paste private tenant IDs/tokens into chat.
On status="error", show the sanitized source/code and stop without invented
files/counts. Do not switch to simulation when LIVE fails.
```

Attach **only** skill `defender-cloud-live` and tool
`generate-defender-cloud-report`. Use the **entire**
[`skills/defender-cloud-live/SKILL.md`](skills/defender-cloud-live/SKILL.md)
as the runtime skill instructions.
Enable skills and explicitly select this allowed skill; do not leave an
all-skills default. An already-owned `arc-defender-live` may remain as
an explicitly labeled legacy alias to this same general tool/skill; there is no
need to create that alias for a new customer. Verify effective bindings instead
of trusting a legacy name or silently deleting existing components.

## `arc-defender-mercadona`: instructions

```text
You are the Mercadona-inspired Arc on-premises/GCP SIMULATED demo specialist.
Use arc-defender-mercadona and only simulate-arc-defender-mercadona.
All 200 servers, findings, software, native-like risks and teaching graphs are
synthetic assumptions, not customer facts. Label every answer/file SIMULATED.
Preserve the approved Mercadona forest/emerald branding for this demo only.
Report with operation="report". Deliver the four actual runtime-owned files
through normal sharing; never invent sandbox links.
Make one report call with all other defaults. No hidden follow-up queries,
repeated reports, narrowed scope, omitted evidence or raised byte guards are
allowed to finish it. Use returned compact facts/top_actions for the summary.
Questions use query views and deterministic local filters, with exact totals
and explicit returned/has_more/next_offset/transport_capped. Never count the
sample as the estate. Native-like risk and technical severity remain separate.
Illustrative simulated chains are not real Defender detections, current customer
topology or a promise of on-premises Arc attack-graph support. Use DEMO-VA IDs,
never invented CVEs. The illustrative baseline ratio is not native Secure Score.
Do not call Azure, acquire tokens, change resources or read the confidential PDF.
Do not claim all CSPM/SQL/Containers features are in Servers P2, general
on-prem/GCP JIT, standalone on-prem agentless scanning or ENS/GDPR certification.
Never invent ROI or avoided-loss claims. Report errors without fictitious files.
```

Attach **only** skill `arc-defender-mercadona` and tool
`simulate-arc-defender-mercadona`, with the entire
[`skills/arc-defender-mercadona/SKILL.md`](skills/arc-defender-mercadona/SKILL.md).
Keep this optional path in a different specialist and thread, never as another
LIVE connector or fallback.

## Select the specialist, then use normal chat

Open **New chat**, type `/agent` and explicitly select the intended saved
specialist. Confirm `defender-cloud-live` for LIVE, or
`arc-defender-mercadona` for the separate offline path, before sending the
natural-language text. Older screenshots show `@name:` prefixes; those are
historical notation, not proof of the current selected responder.

Report routing acceptance requires the exact selected Python tool call:

| Path | Expected call | Native files |
|---|---|---|
| LIVE | `generate-defender-cloud-report` with `{"operation":"report"}` and otherwise defaults | `report_path`, `csv_path`, `findings_csv_path`, `snapshot_path` |
| SIMULATED | `simulate-arc-defender-mercadona` with `{"operation":"report"}` and otherwise defaults | Same four path fields, all SIMULATED |

Download each actual nonempty file through native sharing. Returned paths are
not authenticated-download receipts, permanent links or current filename
aliases. A report's complete normalized evidence belongs in the files, not
extra tool calls or an oversized chat response.

## LIVE report prompt

```text
Generate the complete LIVE Defender for Cloud report for the configured
subscription. Call generate-defender-cloud-report once with operation="report"
and every other parameter at its default. Deliver the returned HTML, inventory
CSV, finding CSV and JSON through the normal native file-sharing flow.
Summarize only the returned compact evidence and top actions. Keep native risk
separate from technical severity, subscription context separate from Arc-only
metrics, and partial/unavailable sources explicit. The complete detail stays in
the files; do not run extra queries, repeat the report, narrow scope or omit
evidence to fit an output budget. If a tool or publication fails, report that
failure without invented results or download links. Do not change resources.
```

### Spanish (ES) – Informe general LIVE (`operation="report"`)

```text
Genera el informe LIVE completo de Microsoft Defender for Cloud para la
suscripción configurada. Invoca generate-defender-cloud-report una sola vez con
operation="report" y el resto de parámetros en su valor predeterminado. Entrega
los cuatro archivos reales devueltos (HTML, CSV de inventario, CSV de hallazgos
y JSON) mediante el flujo nativo de compartición de archivos. Resume únicamente
la evidencia compacta devuelta y las acciones prioritarias, manteniendo el
riesgo nativo separado de la severidad técnica, el contexto de suscripción
separado de las métricas exclusivas de Arc, y las fuentes parciales o no
disponibles de forma explícita. No ejecutes consultas adicionales ni modifiques
recursos.
```

## LIVE grounded questions

Ask these separately when needed; they are not hidden steps of report
generation. A LIVE query recollects the full configured sources and then
filters locally, so a later page/question is a new snapshot. Never use a page
length as the complete count or enumerate pages merely to learn a returned
total. Use `total_matched`, `returned`, `has_more`, `next_offset`,
`requested_limit` and `transport_capped`; the top summary is unfiltered.

```text
Which Key Vault, AKS and Container Apps resources have Unhealthy
recommendations? Use exact resource types, keep native risk separate from
technical severity, and show full filtered totals rather than counting the
returned page. Do not generate another report.
```

Use explicit `findings` queries for the three exact types
`Microsoft.KeyVault/vaults`, `Microsoft.ContainerService/managedClusters`,
`Microsoft.App/containerApps`, with `status="Unhealthy"`. Distinct affected
native resource IDs are not the number of finding occurrences.

```text
Show the observed subscription attack paths with entry point, target, native
risk and source-recommended breaks. Are any actually Arc-related? Preserve
observed nodes and edges, state source limitations, and do not generate files.
```

```text
What is the subscription Secure Score, and which controls
have the largest potential headroom? Do not promise one host will deliver it.
Use the subscription posture and controls views, not an Arc-filtered score.
```

```text
For ArcBox-SQL, reconcile Healthy/Unhealthy recommendations,
native risk, technical severity and the source SQL/KB update evidence.
Keep missing fix versions and independent sensor health explicitly unknown.
```

```text
Count embedded CVE occurrences, distinct CVE IDs and
resource/CVE pairs. Explain why zero subassessments is not zero vulnerability risk.
```

`ArcBox-SQL` is a historical lab resource label. Substitute an already-observed
customer resource privately, or report that the requested evidence does not
exist. Do not invent CVEs, updates, fix versions, topology or owners from a
name. A `query_item_exceeds_budget` response requires disclosure and inspection
of the full downloaded evidence, not a shortened/fabricated graph or row.

### Spanish (ES) – Preguntas LIVE fundamentadas en fuentes (`operation="query"`)

- **Hallazgos en Key Vault, AKS y Container Apps (`view="findings"`, `status="Unhealthy"`):**
  ```text
  ¿Qué recursos de Key Vault, AKS y Container Apps tienen recomendaciones Unhealthy? Usa los tipos de recurso exactos (Microsoft.KeyVault/vaults, Microsoft.ContainerService/managedClusters y Microsoft.App/containerApps), mantén el riesgo nativo separado de la severidad técnica y muestra los totales filtrados completos en lugar de contar la página devuelta. No generes otro informe.
  ```
- **Rutas de ataque de la suscripción (`view="attack_paths"`):**
  ```text
  Muestra las rutas de ataque observadas en la suscripción con punto de entrada, destino, riesgo nativo y puntos de corte recomendados por la fuente. ¿Alguna está realmente asociada a Arc? Conserva los nodos y enlaces observados, indica las limitaciones de la fuente y no generes archivos.
  ```
- **Secure Score y margen de controles (`view="posture"` y `view="controls"`):**
  ```text
  ¿Cuál es el Secure Score de la suscripción y qué controles tienen el mayor margen potencial de mejora? Usa las vistas posture y controls de la suscripción, no una puntuación filtrada por Arc, y no prometas una mejora garantizada por un solo host.
  ```
- **Detalle de un recurso observado (`view="resource_details"`):**
  ```text
  Para ArcBox-SQL, concilia las recomendaciones Healthy y Unhealthy, el riesgo nativo, la severidad técnica y la evidencia de actualizaciones SQL/KB de la fuente. Mantén explícitamente como desconocidos las versiones de corrección ausentes y la salud independiente del sensor MDE.
  ```
- **Ocurrencias de CVEs incrustadas (`view="vulnerabilities"`):**
  ```text
  Cuenta las ocurrencias de CVE incrustadas, los identificadores CVE únicos y los pares recurso/CVE. Explica por qué cero subassessments independientes no significa cero riesgo de vulnerabilidades.
  ```

## SIMULATED Arc demo prompts

In a **different thread**, select `arc-defender-mercadona` first.

```text
Generate the SIMULATED 200-server on-premises/GCP
report with illustrative chains, source-like risks, owner tags and DEMO-VA
evidence. Keep synthetic topology and feature/licensing boundaries explicit.
Call simulate-arc-defender-mercadona once with operation="report" and all other
defaults. Deliver its four actual returned files without extra query calls,
repeated reports or invented links. Label every result SIMULATED.
```

```text
Explain an illustrative GCP/on-premises chain and
the proposed breaks, without calling it a real customer or Defender detection.
```

```text
En la simulacion, cuantos servidores de Production
son on-premises y cuantos estan en GCP? Usa los totales completos, no la pagina.
```

The deterministic Production answer is **90 = 62 on-premises + 28 GCP**, using
the full filtered result (`matched_by_provider`), not the small returned page.
Those are fictional fixture counts, not a current customer's allocation.
Monthly automation is a separate optional setup in
[`monthly-task-prompt.md`](monthly-task-prompt.md).

### Paired Spanish (ES) and English (EN) SIMULATED prompts

- **ES – Informe SIMULATED de 200 servidores (`operation="report"`):**
  ```text
  Genera el informe SIMULATED de 200 servidores on-premises/GCP con cadenas ilustrativas, riesgos tipo fuente, etiquetas de propietario y evidencia DEMO-VA. Mantén explícitos la topología sintética y los límites de licenciamiento. Invoca simulate-arc-defender-mercadona una sola vez con operation="report" y el resto de valores predeterminados. Entrega los cuatro archivos reales devueltos y etiqueta cada resultado como SIMULATED.
  ```
- **ES – Cadena ilustrativa GCP/on-premises (`operation="query", view="attack_paths"`):**
  ```text
  Explica una cadena ilustrativa GCP/on-premises y los puntos de corte propuestos, sin presentarla como un cliente real ni como una detección nativa de Defender. Etiqueta la respuesta como SIMULATED.
  ```
- **EN – SIMULATED Production servers by provider (`operation="query", view="inventory", environment="Production"`):**
  ```text
  In the simulation, how many Production servers are on-premises and how many are in GCP? Use the full filtered totals rather than the returned page, and label the response SIMULATED.
  ```
