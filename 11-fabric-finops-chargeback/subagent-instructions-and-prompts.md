# Microsoft Fabric FinOps and chargeback subagent (`fabric-chargeback-live`)

Create one dedicated read-only specialist. It does not change any existing case, role, tool, skill, task or incident
handler.

| Setup field | Value |
|---|---|
| Name | `fabric-chargeback-live` |
| Skill | Only `fabric-chargeback-live` ([`skills/fabric-chargeback-live/SKILL.md`](skills/fabric-chargeback-live/SKILL.md)) |
| Selected tool | Only `generate-fabric-chargeback-report` |
| Tool timeout | `150` seconds (the tool keeps its own 105 s data-collection budget inside it) |
| Scheduled cadence | Monthly, `0 7 2 * *` UTC (`period="last_30d"`). Optional weekly run `0 7 * * 1` UTC (`period="last_7d"`) |
| Remediation authority | None. Strictly read-only; actions are recommended for a human to apply |

## Python tool settings

| Field | Value |
|---|---|
| Name | `generate-fabric-chargeback-report` |
| Description | `Microsoft Fabric FinOps and chargeback report from REAL tenant data (same-tenant or cross-tenant, read-only): billed cost per meter, monthly trend, idle capacity, savings (pause schedule, reservation, right-size), chargeback by workspace, who consumes what, and governance. Writes HTML + JSON + 2 CSV.` |
| Code | [`generate-fabric-chargeback-report.py`](generate-fabric-chargeback-report.py) with the 3 constants of the `CONFIGURE` block set (see README, step 4) |
| Timeout | `150` |
| Identity tab | Leave the switch **Off**. The tool authenticates with the agent managed identity itself (`MANAGED_IDENTITY_CLIENT_ID`) |

| Parameter | Type | Required | Description (paste as is) |
|---|---|---|---|
| `operation` | string | No | `report (writes 4 files) or summary (JSON only, faster)` |
| `period` | string | No | `last_30d (default), last_14d or last_7d` |
| `identities` | string | No | `masked (default) or visible (only when explicitly requested and authorized)` |

The same contract as JSON Schema: [`tool-parameters.schema.json`](tool-parameters.schema.json).

## Skill settings

| Field | Value |
|---|---|
| Name | `fabric-chargeback-live` |
| Description | `Microsoft Fabric FinOps and chargeback on real tenant data only: billed cost by meter, idle capacity, savings, who consumes what and governance (same-tenant or cross-tenant, read-only).` |
| Content | Paste [`skills/fabric-chargeback-live/SKILL.md`](skills/fabric-chargeback-live/SKILL.md) |
| Tools | Choose tools -> `generate-fabric-chargeback-report` |

## Copy-ready subagent instructions

```text
You are the Microsoft Fabric FinOps and chargeback specialist (`fabric-chargeback-live`).
Use the `fabric-chargeback-live` skill and ONLY the `generate-fabric-chargeback-report` tool.
Reply in the user's language (Spanish or English).
For a full report call the tool with operation="report" (period last_30d unless the user asks for 7 or 14 days).
For a targeted question call it with operation="summary" and answer only from the returned JSON.
Keep identities="masked" unless the user explicitly asks to see identities and says the recipient is authorized.
REAL DATA ONLY: report exclusively what the tool returned from the tenant (billed cost by meter, monthly trend,
idle hours, savings actions with evidence, pause what-if, reservation breakeven, right-size, chargeback by
workspace, top identities and items, governance findings). Never invent amounts, users or savings; for any source
that is not ok, say what is missing.
For a report finish with an "Artifacts & links" bulleted list of the 4 returned URLs (report_url, snapshot_url,
chargeback_csv_url, meters_csv_url) as markdown links, unchanged, never inside a table.
Never print tokens or credentials. Never modify capacities, workspaces, access, tenant settings or billing.
Do not create, overwrite or delete memory files while producing a report; it is a read-only, stateless task.
```

## Scheduled monthly automation (`0 7 2 * *` UTC)

Day 2 instead of day 1 because Azure Cost Management publishes cost with a 24-48 h delay.

| Field | Value |
|---|---|
| Task name | `Monthly Fabric FinOps and chargeback report` |
| Description | `Monthly read-only Fabric FinOps report: real cost by meter, idle capacity, savings and chargeback by workspace.` |
| Response subagent | `fabric-chargeback-live` |
| Frequency | Monthly, day of month `2`, time of day = 07:00 UTC in your local zone (08:00 in GMT+1) |
| Cron (UTC) | `0 7 2 * *` |

### Scheduled task prompt

```text
Generate the Microsoft Fabric FinOps and chargeback report for the last 30 days (operation="report", period="last_30d", identities="masked").
Make exactly one tool call. If the tool returns status="error", report the sanitized error and the sources that failed, and stop; never invent figures.
Otherwise summarize in Spanish: total billed cost, % consumed vs switched on without use, hours on and utilization, the top 5 actions with their value and evidence, the reservation verdict and the chargeback by workspace.
Finish with an "Artifacts & links" bulleted list with the 4 returned URLs (report_url, snapshot_url, chargeback_csv_url, meters_csv_url) unchanged.
Do not modify any Fabric or Azure resource.
```

Optional weekly variant: same prompt with `period="last_7d"`, cron `0 7 * * 1` (Mondays 07:00 UTC).

## Copy-ready chat prompts (Spanish and English)

Open **New chat**, type `/agent`, select `fabric-chargeback-live`, then paste a prompt.

### 1. Full report (`operation="report"`)

```text
Genera el informe FinOps de Fabric de los últimos 30 días.
```

```text
Generate the Fabric FinOps report for the last 30 days.
```

```json
{"operation":"report","period":"last_30d","identities":"masked"}
```

### 2. Targeted questions (`operation="summary"`, answer in seconds, no files)

| Topic | Castellano | English |
|---|---|---|
| Cost by meter | ¿Cuánto me ha costado Fabric este mes y por qué piezas? | How much did Fabric cost this month and which meters drive it? |
| Idle capacity | ¿Cuántas horas ha estado la capacidad encendida sin trabajar y cuánto ha costado? | How many hours was the capacity on without work, and what did it cost? |
| Pause schedule | ¿A qué hora debería pausar la capacidad y cuánto ahorraría? | When should I pause the capacity and how much would I save? |
| Reservation | ¿Me compensa una reserva de 1 o 3 años? | Is a 1- or 3-year reservation worth it? |
| Right-size | ¿Puedo bajar de SKU sin afectar a la carga? | Can I move to a smaller SKU without hurting the workload? |
| Chargeback | ¿Qué workspaces consumen más y cuánto les toca en el reparto? | Which workspaces consume most and what is their chargeback share? |
| Spark | ¿Qué notebooks Spark cuestan más y cuáles fallan? | Which Spark notebooks cost most and which fail? |
| AI | ¿Cuánto cuestan Copilot y los Data Agents, y en qué workspaces? | How much do Copilot and Data Agents cost, and in which workspaces? |
| Refreshes | ¿Qué refrescos fallan o llevan más de 60 días sin ejecutarse? | Which refreshes fail or have not run for 60+ days? |
| Risk | ¿Hay capacidades pausadas o vacías que supongan un riesgo de coste? | Are there paused or empty capacities that are a cost risk? |
| Trend | ¿Cómo ha evolucionado la factura de Fabric mes a mes? | How has the Fabric bill evolved month by month? |
| Governance | ¿Qué ajustes del tenant deberíamos revisar (Publish to web, invitados, IA)? | Which tenant settings should we review (Publish to web, guests, AI)? |
| Clean-up | ¿Cuántos items llevan más de 90 días sin cambios y de qué tipo son? | How many items have not changed in 90+ days, and of what type? |

```json
{"operation":"summary","period":"last_30d","identities":"masked"}
```

### 3. Unmasked identities (only for an authorized recipient)

```text
Show me the identities unmasked; the recipient is authorized. Generate the Fabric FinOps report for the last 30 days.
```

```json
{"operation":"report","period":"last_30d","identities":"visible"}
```
