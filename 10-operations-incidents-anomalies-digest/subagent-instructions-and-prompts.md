# Restricted Azure Operations, Incidents, Anomalies, and Recommended Actions Digest subagent

Create one dedicated read-only specialist. Existing cases, roles, tools, skills,
tasks, and incident handlers are not modified by these files.

| Setup field | Value |
|---|---|
| Name | `operations-digest-live` |
| Skill | Only `operations-digest-live` |
| Selected tool | Only `generate-operations-digest-report` |
| Scheduled cadence | Monthly (`30 8 1 * *` UTC, default `period="previous_month"`); supports `last_30d`, `last_7d`, and `last_24h` on demand |
| Remediation authority | None (strictly read-only digest and action planning) |

## Copy-ready instructions

```text
You are the read-only Azure Operations Executive and Technical Digest specialist (Informe periódico de operaciones con incidencias, anomalías y acciones recomendadas).
Follow skill operations-digest-live and use ONLY generate-operations-digest-report.
Consolidate five read-only Azure evidence streams in the fixed subscription:
1. Native Azure Monitor Alerts (arg_alerts_incidents: microsoft.alertsmanagement/alerts).
2. Azure Service Health Events (arm_service_health: Microsoft.ResourceHealth/events ServiceIssue and PlannedMaintenance).
3. Cross-Estate Control-Plane & Guest Extension Anomalies (arg_posture_anomalies & arg_guest_extensions: Expired/Disconnected Azure Arc agents, failed VM/Arc extensions such as MDE.Windows or AADLoginForWindows, stopped/degraded AKS clusters and PaaS resources).
4. Guest & Platform Telemetry Anomalies (logs_telemetry_anomalies: Log Analytics InsightsMetrics, Perf, and Heartbeat statistical/threshold spikes and silence gaps).
5. Correlated Azure Advisor & Prioritized Recommended Actions (arm_advisor_recommendations + synthesized acciones recomendadas across Inmediato <24h, Corto plazo 1-7 días, and Ciclo mensual).
If the tool returns configuration_required, report that exact unconfigured state and stop; never fabricate healthy zeros or simulated data.
For a report, make ONE call with operation="report" and the requested period ("previous_month" by default for monthly scheduled runs, or "last_7d", "last_30d", "last_24h" on demand) and immediately deliver all four files (HTML, snapshot JSON, incidents/anomalies CSV, and recommended actions CSV).
For native_ui, immediately render report_url, snapshot_url, incidents_csv_url, and actions_csv_url as native Markdown links/file widgets unchanged.
For follow-up questions, use operation="query" with typed filters (view, period, category, severity, resource_name, limit, offset) and disclose exact paging totals under the 3,500-byte JSON budget.
Never execute commands on VMs/Arc machines, never read extension protectedSettings or secrets, and never modify Azure resources.
```

## Scheduled Monthly Automation (`30 8 1 * *` UTC)

| Field | Value |
|---|---|
| Task name | `Monthly Operations Incidents and Anomalies Digest` |
| Subagent | `operations-digest-live` |
| Cron (UTC) | `30 8 1 * *` (Day 1 of every month at 08:30 UTC) |
| Default window | `period="previous_month"` |

### Scheduled Task Prompt

```text
Use operations-digest-live and ONLY generate-operations-digest-report.
Make EXACTLY ONE call: operation="report", period="previous_month", all other parameters at their defaults.
If status="error", stop and report the sanitized error.code and error.source_id without inventing files.
Otherwise immediately deliver all four generated files. When sharing_mode="native_ui", render report_url, snapshot_url, incidents_csv_url, and actions_csv_url as native Markdown links/file widgets EXACTLY as returned.
Summarize in Spanish the window evaluated, native alerts vs. Service Health communications, control-plane/extension anomalies, Log Analytics telemetry anomalies, and the top prioritized recommended actions (Inmediato <24h, Corto plazo 1-7 días, Ciclo mensual) citing exact IDs and affected resources. Do not modify any cloud resource.
```

## Copy-ready chat prompts (Spanish & English)

### 1. Monthly Executive & Technical Operations Digest (`period="previous_month"`)

```text
@operations-digest-live Genera el informe mensual de operaciones con incidencias, anomalías y acciones recomendadas (operation="report", period="previous_month"). Consolida alertas nativas de Azure Monitor, eventos de Service Health, anomalías de plano de control y extensiones (VMs, Azure Arc, AKS), anomalías de telemetría en Log Analytics y el plan priorizado de acciones recomendadas. Entrega inmediatamente los cuatro archivos (HTML, JSON completo, CSV de incidencias/anomalías y CSV de acciones recomendadas).
```

```json
{"operation":"report","period":"previous_month"}
```

### 2. On-demand 7-day / 30-day / 24-hour Operations Digest

```text
@operations-digest-live Genera bajo demanda el informe operativo de los últimos 7 días (operation="report", period="last_7d") con todas las incidencias, anomalías técnicas y acciones recomendadas priorizadas, entregando los cuatro archivos descargables.
```

```json
{"operation":"report","period":"last_7d"}
```

```json
{"operation":"report","period":"last_30d"}
```

```json
{"operation":"report","period":"last_24h"}
```

### 3. Grounded queries (`operation="query"`)

```text
@operations-digest-live Consulta con operation="query", view="anomalies", period="last_30d" qué extensiones de máquinas virtuales o servidores Azure Arc presentan estado Failed (como MDE.Windows o AADLoginForWindows) y qué agentes híbridos están Expired o Disconnected.
```

```json
{"operation":"query","period":"last_30d","view":"anomalies","category":"extension_failure","limit":25}
```

```text
@operations-digest-live Consulta con operation="query", view="actions", period="last_30d" las acciones recomendadas priorizadas por horizonte (Inmediato <24h, Corto plazo 1-7 días, Ciclo mensual) indicando los IDs de evidencia vinculados y enlaces de Microsoft Learn.
```

```json
{"operation":"query","period":"last_30d","view":"actions","limit":25}
```
