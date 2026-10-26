# Monthly infrastructure operations review

| Field | Value |
|---|---|
| Task name | `Monthly infrastructure operations review` |
| Response custom agent / subagent | `infra-ops-live` |
| Frequency | Custom cron |
| Cron (UTC) | `0 9 1 * *` |
| Meaning | First day of each month at 09:00 UTC |
| Evidence period | Previous complete UTC calendar month |
| Behavior | Read-only collection and actual file sharing |

The existing single report call now also includes Arc administration metadata,
extension evidence and any current approved deployment baseline. Those facts
are **current at collection**, not historical month-long configuration. An empty
or expired baseline stays Unknown. No additional query, new task, cadence change
or automatic maintenance is required; the saved Task details block below stays
unchanged. Validate normal chat/downloads before approving monthly recurrence.

Paste into **Task details**:

```text
Use infra-ops-live and generate-infrastructure-operations-report only.
Make EXACTLY ONE tool call: operation="report", period="previous_month",
grain="auto", hosting="all", metric="all", other defaults. The fixed full scope
includes both Arc and Azure. Do not call operation="query", collect another
snapshot, page, retry with a different period or request a narrower report.
If status="error", stop with the sanitized source/code and no invented files.
Otherwise IMMEDIATELY show all four file downloads using the returned
report_url, resources_csv_url, signals_csv_url and snapshot_url when
sharing_mode="native_ui". These are relative native UI aliases derived from
the real guarded runtime paths; render them as Markdown links or normal file
widgets exactly as returned. Do not invent a host, prepend a thread ID, replace
them with sandbox URLs, or demand an unavailable HTTP-verification tool.
The unchanged report_path/resources_csv_path/signals_csv_path/snapshot_path
remain the real file paths. If sharing_mode="local_files_only", state that
native UI aliases are unavailable here and show the real paths only.
artifact_status="written" means files were written, not HTTP verified.
http_verified=false is not a sharing failure and must not suppress provided
native aliases. status="partial" means evidence coverage is partial; it is
not a file-publication failure.
After the four links, give at most one short paragraph using only the returned
window, summary counts and top_review_resources names/states. Do not query
again to explain CPU, causes, owners or partial coverage. Direct the reader to
the report's Evidence coverage/Owner review sections for detailed facts.
Keep the dated offline-snapshot qualification and any returned coverage status;
do not invent a reason, SLA, root cause, forecast, health score or savings.
Never turn an artifact-size failure into success by splitting Arc/Azure,
shortening the previous month or removing resources/series. Rerun the complete
requested scope after a validated lossless fix; preserve the failed history.
Never execute load, controlled-cpu-load.py, guest commands, resource writes,
start/stop/resize, remediation, instrumentation, permissions or other workflows.
```

## Run once immediately

Creating the task is not validation. In **Automation**, select its row checkbox
and the enabled toolbar **Run now**. Open the actual execution thread and inspect
the tool result, all four real downloads, the report interactions and one
source-grounded question. An automation status of **Success** alone is not proof
that the tool or file sharing finished. **No thread found** also requires a
separate check of the actual thread/files, not an invented success claim.

The monthly run itself makes one report call and immediately shares its result.
Ask any source-grounded follow-up question in a **separate explicit chat**,
not as hidden follow-up queries inside the scheduled run. The operator's HTTP
verification is an acceptance check, not a required tool for rendering the
derived native links.

The exported HTML remains a snapshot after download. Run a new query/report for
new measurements; the monthly task does not stream updates into an older file.
These repository files do not create the schedule by themselves.
