# Subagent credential-monitor-full: instructions and prompts

Use this reference alongside [README Steps 2–6](README.md#step-2--create-the-python-tool). It provides the copy-ready subagent instructions, English and Spanish chat prompts, and monthly scheduled-task configuration.

## Setup and post-save readback table

Reopen the saved Python tool, skill, and custom agent in the SRE Agent portal after creation and verify every setting below. Leaving **Choose tools** or **Choose skills** empty inherits all global tools or skills instead of restricting the subagent to read-only auditing.

| Component / field | Expected value | Post-save readback check |
|---|---|---|
| **Subagent name** | `credential-monitor-full` | Exact match in **Builder > Agent Canvas** |
| **Attached skill** | `entra-full-credential-inventory` | Verify the exact selected skill **name** in the reopened saved form and effective policy (`allowedSkills: ["entra-full-credential-inventory"]`, `addSystemSkills=false`); never leave empty or rely on the list summary badge |
| **Selected tool** | `generate-entra-credential-expiration` | Verify the exact selected tool **name** in the reopened saved form and effective policy (`tools: ["generate-entra-credential-expiration"]`, `disableDocumentRetrieval=true`); never leave empty or rely on the list summary badge |
| **Tool parameters** | `0` (`{}`) | `def main() -> dict:` takes no arguments |
| **Portal Identity tab** | `Enable Azure Identity = On`, Scope = `https://graph.microsoft.com/.default` only | Default ARM scope removed; code also authenticates explicitly with `ManagedIdentityCredential(client_id=...)` |
| **Output** | `1 HTML file with embedded CSV export` | Self-contained `/mnt/data/entra-credential-expiration-audit-<UTC-DATE>.html` plus chat summary |
| **Remediation authority** | `None` | Read-only (`Application.Read.All`); never rotates, creates, or deletes credentials |

> [!NOTE]
> **Dated SRE UI badge caveat:** In the live SRE Agent UI, Agent Canvas list/card summary badges can display inherited global rollups (for example, `131 tools` / `52 skills`) even when both native APIs, selected chips and the saved form policy enforce one explicit tool and skill (`tools`, `allowedSkills`, `addSystemSkills=false`, `disableDocumentRetrieval=true`). Always verify the exact selected tool and skill **names** in the saved form and effective supported policy; the list summary badge is not authoritative restriction proof, and you must not modify globals to change it.

## Subagent instructions
Copy this text into the **Instructions** field of the `credential-monitor-full` subagent:

```
You are the specialized executor of monthly Microsoft Entra credential
expiration audits. Use the entra-full-credential-inventory skill.
Generate the validated HTML report for Applications and non-managed
Service Principals. Always operate in read-only mode. If there is a Graph
error or incomplete data, declare partial coverage; never invent results
or run any remediation.
```

## Test prompt (from chat, before you automate)

Select `credential-monitor-full` explicitly in **New chat** (`/agent` where supported) before sending the prompt.

### English (EN) – Full audit report
```
Run the full Microsoft Entra credential expiration audit and deliver the HTML report with the coverage and risk summary.
```

### Spanish (ES) – Informe completo de auditoría
```
Ejecuta la auditoría completa de caducidad de credenciales de Microsoft Entra y entrega el informe HTML junto con el resumen de cobertura y niveles de riesgo.
```

## Grounded follow-up questions in chat (EN / ES)

Because `generate-entra-credential-expiration` takes **zero parameters** (`main() -> dict`), it has no server-side filter arguments for application name, status, or horizon days. Grounded follow-up questions in the same chat thread should either interpret the returned coverage/status summary or guide the operator to filter and export the **already downloaded HTML report** locally (using its built-in **Credential name**, **Minimum/Maximum days**, **Risk status**, **Object type**, and **Export visible rows as CSV** controls) without claiming a partial re-query of Microsoft Graph.

### English (EN) – Grounded follow-up examples
```
Based on the audit result in this thread, summarize the coverage fields (reference_utc, pagination_completed, applications_scanned, service_principals_scanned, managed_identities_excluded, credential_rows), explain whether Action required applies, and list which status filters I should select in the downloaded HTML report to review immediate rotation priorities and unknown expiration dates.
```

```
Explain why a credential expiring later today is classified as EXPIRED under this tool's UTC calendar-date rule, and how to export only EXPIRED and CRITICAL rows to CSV from the downloaded HTML report.
```

### Spanish (ES) – Ejemplos de preguntas de seguimiento
```
A partir del resultado de la auditoría en este hilo, resume los campos de cobertura (reference_utc, pagination_completed, applications_scanned, service_principals_scanned, managed_identities_excluded, credential_rows), indica si aplica Action required y explica qué filtros de estado debo seleccionar en el informe HTML descargado para revisar las prioridades inmediatas de rotación y las fechas UNKNOWN.
```

```
Explica por qué una credencial que caduca hoy más tarde se clasifica como EXPIRED según la regla de fecha de calendario UTC de esta herramienta, y cómo exportar únicamente las filas EXPIRED y CRITICAL a CSV desde el informe HTML descargado.
```

## Monthly scheduled task
- Response subagent: `credential-monitor-full`
- Recommended schedule: day 1 of every month at 09:00 UTC
- Cron expression:

```
0 9 1 * *
```

- Task prompt:

```
Run the full Microsoft Entra credential expiration audit. Deliver the HTML report, coverage, risk counters and Action required when applicable.
```

### Portal field-by-field configuration table

| Portal field | Recommended value | Notes / verification |
|---|---|---|
| **Task name** | `Monthly Microsoft Entra credential expiration audit` | Search **Automation** first and reuse an existing customer-owned task if already created |
| **Response subagent** | `credential-monitor-full` | Do not leave empty (empty falls back to the main agent) |
| **Task details** | Copy-ready task prompt above | Calls `generate-entra-credential-expiration` once with `{}` |
| **Frequency** | `Custom cron` | Prefer explicit UTC cron over browser-local time pickers |
| **Cron expression (UTC)** | `0 9 1 * *` | Runs on day 1 of every month at `09:00 UTC` |
| **Message grouping** | `New chat thread for each run` | Keeps each monthly snapshot isolated in its own execution thread |
| **Agent autonomy level** | `Autonomous` (when approved for unattended read-only execution) | `Review` pauses for human approval before running |
| **Evidence meaning** | `Current point-in-time credential snapshot each month, not previous-month history` | Microsoft Graph is queried at run time; compare retained monthly HTML/CSV snapshots to track trends |

### Run-now verification checklist

1. Reopen the saved scheduled task and confirm **Response subagent = `credential-monitor-full`**, the exact task prompt, `0 9 1 * *`, and the next scheduled UTC run time.
2. With customer approval for an acceptance test, select only this task in **Automation** and click **Run now** (or **Run task now**) once.
3. Open the task's **Run history** and click into the actual **execution thread** (`Success` on the list view only confirms thread handoff, not file delivery).
4. Verify that `generate-entra-credential-expiration` ran with `{}` (no arguments), returned `coverage.status == "complete"` and `coverage.pagination_completed == true`, and attached a downloadable HTML report.
5. Download the HTML report, open it in a browser, verify the `Reference UTC` banner and status cards, and test **Export visible rows as CSV**.
