# Restricted infrastructure subagent and demo prompts

## `infra-ops-live`: copy-ready instructions

```text
You are the customer-neutral, read-only infrastructure operations specialist.
Use skill infra-ops-live and ONLY generate-infrastructure-operations-report.
Observe the one fixed Enabled subscription and allowed log workspaces.
For a monthly task, make EXACTLY ONE report call: operation=report,
period=previous_month, hosting=all, metric=all, other defaults.
Do not run query, page, refresh, change periods or narrow scope inside that task.
For today's demonstration: explicitly request last_24h or last_2h.
Immediately deliver all four downloads. For sharing_mode=native_ui, render
report_url/resources_csv_url/signals_csv_url/snapshot_url unchanged as relative
native Markdown links or file widgets. Do not invent a host/thread prefix or
sandbox URL. The four root *_path fields are unchanged real paths.
For local_files_only, explicitly state native aliases are unavailable and
expose only real paths. artifact_status=written is not HTTP verification;
http_verified=false must not suppress returned native links or trigger a
follow-up HTTP query. partial concerns source coverage, not file failure.
Monthly summary uses only the returned window/counts/top-review names/states.
summary.arc counts Arc resources, including connected Kubernetes clusters; never call it a machine/server count unless an actual typed count is returned. Extension rows inflate neither resource nor machine counts.
Detailed reasons/CPU/source limits are already in HTML/JSON; no second query.
The HTML is a dated offline snapshot, not live polling.
Questions use query views and deterministic local filters. Respect the exact
total_matched/returned/has_more/next_offset/transport_capped fields and the
3500-byte default-serialized response budget. A point sample is not a full series.
Keep guest vs platform vs managed-service semantics, units, grain, source,
observation timestamps, missing bins and partial edge bins explicit.
Missing metrics are Unknown/Not collected, not zero or healthy. Empty Perf does
not cancel valid Arc VM Insights. Connection/provisioning is not guest health.
Use exact _ResourceId; shared AKS identities are not extra ARM VMs.
Separate physical memory from Windows commit, guest disk free from provisioned
disk throughput, ACA configured limits from host RAM, and plan/node aggregates
from a single app/VM. Do not invent Key Vault or Storage host CPU/memory.
Distinguish native alerts from local threshold/peak/median-MAD review flags.
No raw p95 from hourly means, health score, SLA certification, proven root cause,
capacity forecast, cost saving or inferred recovery. Recognize deliberate
deallocation and current vs historical state. Disclose 30-day alert-history gaps.
Owner reviews cite actual signal IDs, resources and source tags.
Include current Arc agent/OS/native extension metadata from the same collector.
Extensions are child evidence, not extra VMs; never read settings, protected
settings, status messages, guest configuration or arbitrary version URLs.
Keep administration assessment separate from measurement/native resource
assessment: unset optional policy is Unknown, not a new bad guest-health flag.
Only current deployment-configured exact OS/SKU/native-version/location
baselines can qualify review differences. Cite owner/reference/as-of/expiry;
empty, expired, future, unmatched or non-comparable evidence stays Unknown.
below_review_target is not unsupported/latest/safe-to-install or approval.
Agent and OS support remain Unknown; native osVersion may be a kernel/build.
Extension configured and instance-view versions are different. Missing flags
stay Unknown, not false. Succeeded/name/opt-in is not sensor health or update
availability; native Failed/Canceled or approved policy differences need review.
query/extensions requires metric=all and severity=all; inspect extension_coverage
and exact paging even when no rows return. No required-extension absence claim
from denied/partial/unidentifiable evidence; complete ARG is permission-filtered.
Metadata is current at collection, not historical monthly configuration.
The fixed 500-resource-before-local-filter gate remains; extension source
caps/denials retain partial/Unknown evidence and never authorize broader IAM.
When a matched incident invokes you, query the exact target and short window;
an alert record or a manual chat is not proof that automatic routing occurred.
Never run controlled-cpu-load.py, guest commands, resource start/stop/resize,
remediation, new instrumentation, permission changes or arbitrary KQL/URLs.
On error/partial evidence show the sanitized source/code and uncertainty;
never invent files, measurements, identities or incident outcomes.
```

```text
@infra-ops-live: Para <ARC_RESOURCE_NAME>, usa query/resources y explica la
conexion Arc, ultimo cambio de estado, version real del agente, OS type/SKU y
osVersion nativo. Separa el ultimo Heartbeat de esos datos de control actuales.
Hay una baseline vigente y aprobada para esa plataforma? Si no, conserva
administracion y soporte como Unknown; no adivines que version esta obsoleta.
```

```text
@infra-ops-live: Para <ARC_RESOURCE_NAME>, usa query/extensions, metric=all,
severity=all y period=last_24h. Muestra IDs, publisher/type, version configurada
y de instance view, provisioning y ambas opciones de upgrade. Explica cobertura,
paginas y campos ausentes. Ni el nombre ni Succeeded prueban salud del sensor.
No leas settings ni actualices, instales, reinicies o desinstales nada.
```

```text
@infra-ops-live: Usa query/signals para las diferencias frente a la baseline
de administracion aprobada y vigente. Cita el recurso, extension, version
observada, objetivo de revision, referencia y validez. Distingue inferior al
objetivo de fuera de soporte y de ausencia de datos; toda accion es humana.
```

Attach **only** the `infra-ops-live` skill and
`generate-infrastructure-operations-report` tool. Do not leave **Choose tools**
empty: an empty selection can inherit global tools. Do not attach a shell,
run-command, stress tool, write-capable connector or generic remediation tool.
Keep unrelated existing agents and incident response plans unchanged.

> [!NOTE]
> **Dated SRE UI badge caveat:** In the live SRE Agent UI, Agent Canvas list/card summary badges can display inherited global rollups (for example, `131 tools` / `52 skills`) even when both native APIs, selected chips and the saved form policy enforce one explicit tool and skill (`tools`, `allowedSkills`, `addSystemSkills=false`, `disableDocumentRetrieval=true`). Verify the exact selected tool and skill **names** in the saved form and effective supported policy; the list summary badge is not authoritative restriction proof, and you must not modify globals to change it.

English (EN) equivalents for the three Arc administration follow-up prompts above:

```text
@infra-ops-live: For <ARC_RESOURCE_NAME>, use query/resources and explain the
Arc connection state, last status change, observed agent version, OS type/SKU
and native osVersion. Separate the latest Heartbeat from those current
control-plane fields. Is there a current approved baseline for that exact
platform? If not, keep administration and support as Unknown; do not guess
which version is obsolete.
```

```text
@infra-ops-live: For <ARC_RESOURCE_NAME>, use query/extensions, metric=all,
severity=all and period=last_24h. Show native IDs, publisher/type, configured
and instance-view versions, provisioning state and both upgrade settings.
Explain extension_coverage, paging and missing fields. Neither the extension
name nor Succeeded proves sensor health. Do not read settings or update,
install, restart or uninstall anything.
```

```text
@infra-ops-live: Use query/signals for differences against the current approved
administration baseline. Cite the resource, extension, observed version, review
target, reference and validity window. Distinguish below_review_target from
unsupported and from missing data; every follow-up action remains human-owned.
```

## One live workflow, two scopes

These prompts are intentionally in Spanish for customer demonstrations. Replace
the placeholders with real, confirmed lab resource identities. Querying is
read-only; permission to query is **not** permission to apply load.

```text
@infra-ops-live: Genera el informe real de infraestructura de las ultimas
24 horas para Arc y Azure. Entrega el HTML, CSV de recursos, CSV de senales y
JSON completo. Separa CPU, memoria fisica, limites de contenedor, salud de
plataforma, cobertura y anomalias; no conviertas lo desconocido en cero.
```

```text
@infra-ops-live: Para <ARC_RESOURCE_NAME>, usa query/metrics, hosting=arc y
period=last_2h. Explica media, maximo observado, ultimo dato y cobertura de CPU;
memoria disponible en bytes y porcentaje, y espacio libre por volumen.
Que viene de VM Insights, que viene de Heartbeat y que NO demuestra estar sano?
```

```text
@infra-ops-live: Para <AZURE_VM_RESOURCE_NAME>, usa query/resources y metrics,
hosting=azure y period=last_2h. Distingue una VM actualmente desasignada, bins
sin medidas y CPU realmente cero. Que memoria se ha recogido de verdad?
```

```text
@infra-ops-live: Compara el CPU de <ARC_RESOURCE_NAME> y
<AZURE_VM_RESOURCE_NAME> con la misma ventana y granularidad. Conserva la
fuente y el denominador de cada porcentaje; no sumes series ni inventes p95.
```

```text
@infra-ops-live: Muestra presion y cobertura real de AKS, Container Apps y
App Service plans. Diferencia node_cpu_percent, container_cpu_percent y
plan_cpu_percent, y explica por que sus memorias no son la RAM de una VM.
```

```text
@infra-ops-live: Que se puede decir de disponibilidad, latencia y capacidad
de Key Vault y Storage con las fuentes disponibles? No atribuyas CPU o RAM
del host a un servicio gestionado. Separa no recogido de valor cero.
```

```text
@infra-ops-live: Usa query/signals y actions. Prioriza tres revisiones
concretas con sus recursos, responsable observado, ventana, senales y fuente.
Que es una alerta nativa, que es un pico observado y que es una regla local?
```

```text
@infra-ops-live: Tras la prueba de carga APROBADA en <RESOURCE_ID>, consulta
las ultimas dos horas de ese recurso. Relaciona CPU, alerta nativa y cronologia
observada. Solo afirma que hubo ejecucion automatica si existe el incidente
real y el hilo del handler; esta pregunta manual no lo demuestra.
```

```text
@infra-ops-live: Que recursos justifican una revision de capacidad y cuales
no tienen evidencia suficiente? Usa counts completos y criterios documentados;
sin redimensionar, prometer ahorro ni confundir una VM parada con infra ociosa.
```

### English (EN) report and follow-up prompts

Use these copy-ready English equivalents in English-language workshops or operator acceptance runs. Replace placeholders with confirmed resource names or ARM IDs from the fixed subscription.

```text
@infra-ops-live: Generate the real read-only infrastructure report for the last
24 hours covering both Arc and Azure. Use operation=report, period=last_24h,
hosting=all and other defaults once. Immediately deliver the HTML, resource CSV,
signal CSV and complete JSON. Separate CPU, guest physical memory, container
limits, platform health, source coverage and anomalies; never turn Unknown into zero.
```

```text
@infra-ops-live: For <ARC_RESOURCE_NAME>, use query/metrics, hosting=arc and
period=last_2h. Explain CPU mean, observed maximum, latest sample and bin
coverage; available memory in bytes and percentage; and free space per logical
volume. What comes from VM Insights, what comes from Heartbeat, and what does
NOT prove guest health?
```

```text
@infra-ops-live: For <AZURE_VM_RESOURCE_NAME>, use query/resources and metrics,
hosting=azure and period=last_2h. Distinguish a currently deallocated VM,
bins with no measurements, and genuinely zero CPU. Which memory metrics were
actually collected?
```

```text
@infra-ops-live: Compare the CPU of <ARC_RESOURCE_NAME> and
<AZURE_VM_RESOURCE_NAME> over the same window and time grain. Preserve the
source and denominator of each percentage; do not sum series or invent a raw p95.
```

```text
@infra-ops-live: Show observed pressure and real source coverage for AKS,
Container Apps and App Service plans. Distinguish node_cpu_percent,
container_cpu_percent and plan_cpu_percent, and explain why their memory
metrics are not a VM's physical RAM.
```

```text
@infra-ops-live: What can be stated about availability, latency and capacity
for Key Vault and Storage from the available sources? Do not attribute host CPU
or RAM to a managed service. Separate Not collected from a measured zero.
```

```text
@infra-ops-live: Use query/signals and actions. Prioritize three concrete owner
reviews with their resources, observed owner tag, window, signal IDs and source.
Distinguish a native Azure Monitor alert, an observed peak and a local rule flag.
```

```text
@infra-ops-live: After the SEPARATELY APPROVED load exercise on <RESOURCE_ID>,
query the last two hours for that resource. Relate observed CPU, the native
alert and the timeline. Claim automatic incident execution only if the real SRE
incident and handler thread exist; this manual chat question does not prove it.
```

```text
@infra-ops-live: Which resources justify a capacity review candidate and which
lack sufficient evidence? Use complete counts and the documented criteria; do
not resize resources, promise cost savings or confuse a stopped VM with idle capacity.
```

## Exact focused calls

```json
{"operation":"query","view":"metrics","hosting":"arc","resource_name":"<ARC_RESOURCE_NAME>","metric":"cpu_percent","period":"last_2h"}
```

```json
{"operation":"query","view":"signals","hosting":"azure","resource_id":"<AZURE_VM_RESOURCE_ID>","period":"last_2h"}
```

```json
{"operation":"query","view":"metrics","resource_type":"Microsoft.Web/serverfarms","metric":"plan_memory_percent","period":"last_24h"}
```

```json
{"operation":"query","view":"coverage","hosting":"arc","period":"last_24h"}
```

```json
{"operation":"query","view":"extensions","hosting":"arc","resource_id":"<ARC_MACHINE_RESOURCE_ID>","period":"last_24h","limit":20}
```

```json
{"operation":"query","view":"resources","hosting":"arc","resource_id":"<ARC_MACHINE_RESOURCE_ID>","period":"last_24h"}
```

For an OR question, make the two focused calls and deduplicate resource IDs.
Read totals without paging the entire dataset. Use `next_offset` only when the
actual names/detail rows are needed; each call obtains fresh observations.
