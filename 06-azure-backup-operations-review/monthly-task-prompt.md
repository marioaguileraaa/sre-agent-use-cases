# Monthly Azure Backup operations review

**Customer setup and reusable prompt, followed by a dated lab reference.**
The lab operator created/read back the historical task and manually validated
it once. That does not deploy a task into your agent. Complete the customer's
[normal-chat/four-download gate](README.md#5-run-in-chat-and-verify-all-four-actual-downloads)
first, and keep unrelated existing tasks unchanged.

| Task field | Customer value, matching the verified lab contract |
|---|---|
| Name | `Monthly Azure Backup operations review` |
| Responder / custom subagent | `azure-backup-live` |
| Frequency | Monthly, day 1; use Custom cron for the explicit UTC field when needed |
| Cron / timezone | `30 10 1 * *`, **UTC** |
| Meaning | First day of each month at 10:30 UTC |
| Run mode | Saved **Autonomous**, report-only using the one restricted read tool; new chat thread for each run |
| Message grouping for updates | `New chat thread for each run` |
| Start on / repeat until / run limit | Customer-approved activation date and usage/end policy, not copied lab dates |
| Evidence | Recent 14-day job-start window at collection; current item/vault metadata |
| Source interval guarantee | Only explicitly verified per-vault availability; otherwise Unknown |
| Expected protection / policy schedule | Unknown / not evaluated |
| Writes | Local four-file creation only; no Azure, protection, IAM, logs or ticket writes |

Monthly is the explicitly selected test cadence, **not** a full-month backup
control. A 14-day report run once a month leaves inter-run history gaps. There
is no full previous-month option, hidden archive or assumption that existing
workspaces contain Backup Logs. Do not silently substitute a 24-hour report.

## Create or reuse the task

1. In the approved customer's **Automation** page, search for the exact name.
   Check ownership, responder, complete prompt and UTC slot; reuse a matching
   owned task rather than duplicate it. Do not modify unrelated automations
   or operate the lab reference task.
2. If absent, select `azure-backup-live` in **Agent Canvas**, then
   **+ > Trigger > Add scheduled task**. Verify **Response custom agent =
   azure-backup-live**. Enter **Task name** and paste the entire prompt below
   into **Task details**, without AI refinement.
3. Set **day 1, 10:30 UTC**. The lab image genuinely shows **Time of day (UTC)**;
   other portal versions label the picker with the **browser's zone**.
   If it is not explicitly UTC, select **Frequency > Custom cron** and enter
   `30 10 1 * *` in **Cron expression (UTC)**. Do not assume 10:30 local means
   UTC. Stored UTC is fixed; local time can shift after daylight saving.
4. Set **Agent autonomy level > Autonomous** and **Message grouping for
   updates > New chat thread for each run**. Review approved activation date,
   model tier and end/run limits without changing global defaults.
5. **Create task**, reopen and verify all fields, **On/Active** status and the
   next execution **in UTC**. No unnecessary Save is needed for an existing
   matching task. Manual acceptance is a separate customer authorization
   and source read, not an automatic extra invocation.

## Paste into Task details

```text
Use azure-backup-live and ONLY generate-azure-backup-report.
Make EXACTLY ONE tool call with period="last_14d".
Use the complete fixed approved vault scope and other tool defaults.
Do not add query, previous_month, scope/path/identity overrides or parameters.
Do not collect a second report, page, refresh or retry with narrower coverage.
If status="error", show the sanitized source/code, state no valid report was
produced, and stop. Do not invent files/counts or work around a size failure by
dropping rows/fields/details, shortening the period, splitting vaults or storage.
Otherwise immediately deliver all four files. For sharing_mode="native_ui",
render report_url, snapshot_url, jobs_csv_url and coverage_csv_url unchanged
as native relative Markdown links/file widgets. Do not invent or prepend a host,
thread UUID or sandbox prefix. The four corresponding *_path values are real
guarded paths. For local_files_only, disclose that native aliases are unavailable
and show only those actual paths.
artifact_status="written" is not HTTP/download validation. http_verified=false
does not suppress returned links or require another tool call.
status="partial" is an evidence-coverage qualification, not a file-write failure.
After the links, provide one short paragraph grounded only in the returned
UTC reference/window, observed counts and unknown/source coverage. Detail is
already in the HTML/JSON; do not recollect to explain it.
Keep native Failed/warnings/InProgress/Completed/Cancelled/unknown states
separate, and Backup separate from Restore/Delete/other operations.
Monthly is cadence, not full-month coverage. No jobs is not all backups
successful; observed items are not expected protection; no friendly-name joins,
invented missed occurrences, recovery/integrity/RPO/RTO claims or SLA score.
Human review is not incident creation, attachment or closure. No backup,
restore, cancel/retry, policy/protection/IAM/resource/log changes, CLI/shell,
new diagnostics, ticket writes, alerts/load or other tools.
```

## Customer run-now acceptance procedure

1. Read back the saved responder, single selected tool, skill, code and typed
   `period` default. Confirm only the owned task is in scope.
2. With separate customer authorization, select **only this task's checkbox >
   Run now** in **Automation** (detail views may say **Run task now**). Run once
   and retain the real history **Thread name** / matching **Chats** thread and exact tool arguments.
   A saved cron or Success badge alone does not establish tool/file completion.
3. Retain the returned UTC interval, actual source statuses/counts and any
   partial result. Empty Backup jobs/items reads are not failed backups; vault
   names do not establish ASR configuration or replication health.
4. Download all four actual native files. Compare the JSON SHA-256/bytes and
   CSV counts, then exercise filters, details and exact HTML downloads.
5. Record real download failures separately from source blind spots and retain
   genuine error attempts. Grounded questions are separate explicit chats.
6. Capture real report/task/download evidence only after privacy masking.
   Normal-report captures alone do not prove the task path; retain its separate
   configuration, execution history, thread and downloads.

A Success row can mean work was handed to a thread, not that the tool finished.
For **No thread found**, retain the limitation, verify the responder still
exists and inspect any actual matching thread. Do not fabricate a thread ID,
guess file links or silently launch another report. Partial history with valid
files is different from missing file delivery. A manual run is not proof of
future timer firing, monthly history or a changed backup policy.

## Actual manual validation receipt

The operator manually executed this saved task **once**, beginning at
`2026-10-14T22:02:57.614316Z`. The execution history displays **Success** and
`executionCount=1`; the next saved execution remains
`2026-11-01T10:30:00Z`. The resulting report reference is
`2026-10-14T22:03:00Z`, with requested UTC job-start interval
`2026-09-30T22:03:00Z` to `2026-10-14T22:03:00Z`, end-exclusive.

That later snapshot retained **56 Completed Backup jobs, all 56 details, four
distinct items, zero source errors and three unverified vault histories**.
Its `partial` status concerns history, not failed reads or missing files.
All four native downloads returned HTTP 200; both CSVs reconcile byte-for-byte
with the complete model. The JSON is 277,490 bytes, SHA-256
`932f9b84276b165d3e2da54b674258613193229d00314c0717b9c9f3b76e938e`.

See the [actual task/configuration/history and delivered-file
captures](report-evidence.md#active-monthly-task-and-its-manual-execution).
The earlier normal report at `19:55:26Z` had **54 Completed / 2 InProgress**;
do not relabel those screenshots with this later all-Completed result.
Manual validation is not a claim that the future calendar occurrence has
already fired, or that 14 recent days provide complete monthly history.
