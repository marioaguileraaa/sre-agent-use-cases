# Azure SQL Managed Instance maintenance resilience subagent (`sqlmi-maintenance-advisor`)

Create one dedicated read-only specialist. It does not change any existing case, role, tool, skill, task or incident
handler.

| Setup field | Value |
|---|---|
| Name | `sqlmi-maintenance-advisor` |
| Skill | Only `sqlmi-maintenance-resilience` ([`skills/sqlmi-maintenance-resilience/SKILL.md`](skills/sqlmi-maintenance-resilience/SKILL.md)) |
| Selected tool | Only `generate-sqlmi-maintenance-report` |
| Tool timeout | `180` seconds (the tool keeps its own 105 s data-collection budget inside it) |
| Scheduled cadence | Weekly, `0 7 * * 1` UTC (`operation="report"`, `period="last_7d"`) |
| Remediation authority | None. Strictly read-only; commands are handed to a human to validate and run |

## Python tool settings

| Field | Value |
|---|---|
| Name | `generate-sqlmi-maintenance-report` |
| Description | `Read-only Azure SQL Managed Instance maintenance resilience report: maintenance windows, connection type, failover groups, real reconfigurations (Resource Health, Activity Log), upcoming planned maintenance (Service Health), per-application user impact from Application Insights and recommended window from real load. HTML + JSON + 2 CSV. Never changes anything.` |
| Code | [`generate-sqlmi-maintenance-report.py`](generate-sqlmi-maintenance-report.py) with the 3 constants of the `CONFIGURE` block set (see [README, step 4](README.md#step-4---configure-the-tool-code)). Leave them as `<...>` for demo mode |
| Timeout | `180` |
| Identity tab | Leave **Enable Azure Identity** **Off**. The tool gets its own ARM and Log Analytics tokens with the agent managed identity (`MANAGED_IDENTITY_CLIENT_ID`) |

| Parameter | Type | Required | Description (paste as is) |
|---|---|---|---|
| `operation` | string | No | `report (HTML+JSON+2 CSV, default), summary (KPIs, findings, apps) or upcoming (next planned maintenance and at-risk apps).` |
| `period` | string | No | `History window: last_30d (default), last_14d or last_7d.` |
| `data_source` | string | No | `auto (default: live if configured, otherwise demo), live or demo (simulated data).` |

The same contract as JSON Schema: [`tool-parameters.schema.json`](tool-parameters.schema.json).

## Skill settings

| Field | Value |
|---|---|
| Name | `sqlmi-maintenance-resilience` |
| Description | `Azure SQL Managed Instance resilience to maintenance windows: windows, reconfigurations, upcoming maintenance, per-application user impact and recommended window. Read-only.` |
| Content | Paste [`skills/sqlmi-maintenance-resilience/SKILL.md`](skills/sqlmi-maintenance-resilience/SKILL.md) |
| Tools | Choose tools -> `generate-sqlmi-maintenance-report` |

## Subagent settings

| Field | Value |
|---|---|
| Name | `sqlmi-maintenance-advisor` |
| Instructions | Paste [`subagent-instructions.txt`](subagent-instructions.txt) (copy-ready block below) |
| Handoff description | `Read-only advisor for Azure SQL Managed Instance maintenance windows, reconfiguration impact on applications and retry readiness.` |
| Choose skills | Only `sqlmi-maintenance-resilience` |
| Choose tools | Only `generate-sqlmi-maintenance-report` |

## Copy-ready subagent instructions

```text
You are the read-only advisor for Azure SQL Managed Instance maintenance windows and application resilience. Reply in the user's language (English or Spanish).
Use the sqlmi-maintenance-resilience skill and ONLY the generate-sqlmi-maintenance-report tool (read-only).

Choose the operation from the request and make ONE call:
- Full report, analysis, "why are there errors", "which window should we use": operation=report, period=last_30d.
- Quick summary or KPIs: operation=summary.
- "When is the next maintenance", "which apps are at risk": operation=upcoming.
- If the user explicitly asks for simulated data or a demo: data_source=demo. Otherwise leave data_source=auto.
- Weekly scheduled task: operation=report, period=last_7d.

When answering:
1. If mode=demo, say clearly that the data is simulated (the message field already starts with "MODO DEMO (datos simulados)": do not repeat it).
2. For operation=report copy the message field as is: it contains the native download links (HTML, JSON, 2 CSV). Never change or rebuild the URLs.
3. Summarize: short answer (answer), next maintenance (next_maintenance or upcoming) and the actions (top_actions or findings) with their command.
4. Close with: "The window decides WHEN the reconfiguration happens; retries decide IF users notice."

What to explain if asked about window granularity:
- Azure SQL MI offers 3 windows: default 17:00-08:00 every day, weekday Mon-Thu 22:00-06:00 and weekend Fri-Sun 22:00-06:00, in the region's local time.
- You cannot choose an exact day and hour or postpone a specific maintenance. Service Health alerts notify 24 h before, at the start and at the end.
- Unplanned events and some critical updates do not respect any window.
- The real fix is retry logic with backoff in the applications (transient errors such as 40613, 40197, 4060, 233).

Rules:
- Never change windows, connection type, alerts or failover groups, and never run a failover. Only give the commands from the report so the team validates and runs them.
- Do not invent instances, applications, dates or figures. Use only what the tool returns.
- If status=no_data or error, show message and point to the case README (steps 2 to 4).
- "Sin telemetría" (no telemetry) does not mean resilient: it means there is no Application Insights for that application.
```

## Scheduled weekly automation (`0 7 * * 1` UTC)

| Field | Value |
|---|---|
| Task name | `SQL MI - Weekly maintenance resilience report` |
| Description | `Every Monday: last week's SQL MI reconfigurations, user impact, applications without retries and upcoming maintenance (read-only).` |
| Response subagent | `sqlmi-maintenance-advisor` |
| Frequency | Weekly, Monday, time of day = 07:00 UTC in your local zone (08:00 in GMT+1, 09:00 in GMT+2) |
| Cron (UTC) | `0 7 * * 1` |
| Agent autonomy level | Autonomous (the tool is read-only) |

### Scheduled task prompt

```text
@sqlmi-maintenance-advisor Generate the weekly SQL Managed Instance maintenance resilience report (operation=report, period=last_7d). Deliver the 4 download links (HTML, JSON, instances CSV and impact CSV), the short answer, the next maintenance with the applications at risk and the High priority actions.
```

## Copy-ready chat prompts (English and Spanish)

Open **New chat**, type `/agent sqlmi`, select `sqlmi-maintenance-advisor`, then paste a prompt. For a demo, add
`Use demo data.` / `Usa datos de demo.` at the end.

### 1. Full report (`operation="report"`)

```text
Users see errors when SQL Managed Instance maintenance happens. Generate the resilience report for the last 30 days: windows, reconfigurations, impact per application, next maintenance and recommended window.
```

```text
Los usuarios ven errores cuando hay mantenimiento en las SQL Managed Instance. Genera el informe de resiliencia de los últimos 30 días: ventanas, reconfiguraciones, impacto por aplicación, próximo mantenimiento y ventana recomendada.
```

```json
{"operation":"report","period":"last_30d","data_source":"auto"}
```

### 2. Targeted questions

| Goal | English | Castellano | Operation |
|---|---|---|---|
| Executive summary | Give me only the summary: KPIs for the last 30 days, the 3 most important actions and which applications have no retries. | Dame solo el resumen: KPI de los últimos 30 días, las 3 acciones más importantes y qué aplicaciones no tienen reintentos. | `summary` |
| Next maintenance | When is the next planned SQL MI maintenance, which instances does it affect and which applications are at risk? | ¿Cuándo es el próximo mantenimiento planificado de SQL MI, qué instancias afecta y qué aplicaciones están en riesgo? | `upcoming` |
| Windows | Which maintenance window does each Managed Instance have and which one should it have based on real load? Include the command to change it. | ¿Qué ventana de mantenimiento tiene cada Managed Instance y cuál debería tener según la carga real? Incluye el comando para cambiarla. | `report` |
| The customer question | Can we choose the exact day and hour of maintenance as we did on-premises? Answer with what Azure allows and with our data. | ¿Podemos elegir el día y la hora exactos del mantenimiento como en on-premises? Responde con lo que permite Azure y con nuestros datos. | `summary` |
| After an incident | Generate the report for the last 7 days and explain what happened in each reconfiguration and how many users noticed. | Genera el informe de los últimos 7 días y explica qué pasó en cada reconfiguración y cuántos usuarios lo notaron. | `report`, `last_7d` |
| After the failover drill | Generate the report for the last 7 days and tell me which applications are already resilient and which still surface errors to users. | Genera el informe de los últimos 7 días y dime qué aplicaciones ya son resilientes y cuáles siguen mostrando errores al usuario. | `report`, `last_7d` |

```json
{"operation":"upcoming","period":"last_30d","data_source":"auto"}
```
