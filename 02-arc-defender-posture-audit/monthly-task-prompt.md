# Monthly LIVE Defender for Cloud evidence audit

This is an **optional customer setup recipe**, not a task created or executed
by the repository. Complete [README Steps 0-4](README.md#step-0---configure-scope-and-read-permissions)
first: approved fixed subscription, runtime-available UAMI, correct human/source
roles, exact saved source/schema, one-tool/one-skill specialist, and all four
actual native downloads. No additional connector or notification destination is
required; output stays in the task's SRE thread and downloaded files.

This is a **point-in-time snapshot taken monthly**, not a report of all events,
vulnerabilities introduced or risks present during the previous calendar month.
The tool has no month/lookback/baseline parameter or persistent comparison
store. Source retrieval/evaluation times and blind spots remain explicit.

## 1. Find the owned task before creating one

In **Automation**, search for
`Monthly Defender for Cloud live evidence audit` and any known customer-owned
legacy name such as `Monthly Arc Defender live evidence audit`. Check its owner,
responder, scope, prompt, cron, status and execution history. If the intended
owned task already exists, review/edit it in place with the customer's approval;
do not create a duplicate, change an unrelated task or discard history.

The historical lab retained an `arc-defender-live` responder alias after a
preview migration. That is acceptable only when the owner verifies that its
effective allowlists point to the same canonical **general LIVE** tool and
skill. New installations select `defender-cloud-live` directly. A matching
display name is not proof of those bindings.

## 2. Fill the task form

For a new approved task, use **Automation > Create > Scheduled task**.
Alternatively, on the saved LIVE specialist's canvas node select **+ > Trigger >
Add scheduled task**, which preselects the responder. Older portal navigation
may call Automation **Scheduled tasks**.

| Field | Value |
|---|---|
| Task name | `Monthly Defender for Cloud live evidence audit` |
| Response custom agent / Response subagent | `defender-cloud-live`; do not leave empty (empty uses the main agent) |
| Task details | Complete prompt in the next section |
| Start on | Customer-approved activation date; do not copy a historical lab date |
| Frequency | Custom cron |
| Cron (UTC) | `0 9 1 * *` |
| Meaning | Day 1 of each month at 09:00 UTC |
| Message grouping for updates | A **new/separate thread per run**, not reuse of the previous run's conversation; select the equivalent wording in your portal |
| Model tier | General Purpose, subject to the customer's approved model policy |
| Agent autonomy level | **Autonomous** only after the bounded read-only reporter and effective allowlists have passed manual acceptance |
| Repeat until / Run limit, if shown | Customer-approved lifetime/limit; recurring execution continues consuming usage while enabled |

Do not inherit all global tools to make Autonomous work. Review mode can pause
for approval and is not equivalent to unattended monthly execution. Neither
mode gives the reporter authority to enable plans, grant roles, manage tasks,
fix sensors or run remediation.

## 3. Copy-ready Task details

Paste this **whole prompt** into **Task details**, not into the Python editor:

```text
Use defender-cloud-live and generate-defender-cloud-report only.
Make exactly one generate-defender-cloud-report call with operation="report"
and every other parameter at its default, over the complete fixed Enabled
subscription. This is a current snapshot, not previous-month event history.
Do not make follow-up query calls, enumerate pages, retry/repeat reports,
narrow scope, drop evidence or change byte limits to complete this task.
Deliver the four actual returned files: self-contained HTML, inventory CSV,
finding CSV and complete JSON snapshot, using their exact runtime-owned paths
and the normal native thread-sharing flow. Do not invent paths or links.
Summarize only the returned compact evidence and top_actions, including LIVE
provenance, UTC reference, declared scope, source coverage and at most three
evidence-led owner-review priorities. Detail already in the artifacts must
stay there, not trigger extra queries or unsupported chat claims.
Keep native risk separate from technical severity, subscription context
separate from Arc-only metrics, and finding/CVE occurrences separate from
distinct resources or IDs. Retain all recommendation statuses in the files.
Keep independent MDE sensor health explicitly Unknown when not sourced.
Plans, extensions and AKS configuration do not prove runtime health; graph
context is not a confirmed attack, root cause or certification.
Disclose partial/unavailable sources and indexed/evaluation-time limits.
Empty returned data is not a zero-risk or complete-coverage guarantee.
Declare Action required for observed gaps or incomplete assurance, not an
invented score. On status="error", report the sanitized source/code and stop
without invented files/results. On sharing failure, report that failure
without recollecting. Never modify plans, roles, services, tasks or resources.
```

This prompt requests one bounded report. The HTTP client's internal bounded
retry/pagination is part of that one invocation, not permission for the model
to run extra reports or queries. Complete evidence is preserved in the four
artifacts; the compact response is not a reason to recollect.
**Action required** is a human-facing summary label, not a new tool parameter
or a promised structured `action_required` field.

## 4. Save, reopen and check UTC / DST

Select **Create task** or **Save** only for the approved owned task. Reopen its
edit form and confirm the exact responder, full prompt, cron, new-thread
grouping, autonomy and status. Check **Next run time**, and `nextUTCtime` if the
service exposes it, against the intended UTC occurrence.

`0 9 1 * *` is a five-field **UTC** cron expression. With activation before
that occurrence, the next run after **15 October 2026** is
**1 November 2026 at 09:00 UTC**. This is an interpretation example, not a
readback of a deployed task's next time.

If using **Monthly > Day of month 1 > Time of day** instead, read the browser
time-zone label carefully. The current product saves that choice as a fixed
UTC schedule, not a DST-aware local time zone. A fixed 09:00 UTC is 11:00 at
UTC+02 and 10:00 at UTC+01. Prefer Custom cron when the agreed schedule is UTC,
and verify the saved next UTC occurrence after any DST/local-time change.

## 5. Separate manual acceptance from timer evidence

After customer approval, perform **one** manual acceptance run from the
**Automation list**: select the owned row's checkbox, then the enabled toolbar
**Run now**. Do not run an unrelated row or submit again merely because the
history page has a disabled button.

Open the actual execution thread and verify the selected responder, exactly
one report call, its UTC reference and honest partial-source result, and all
four nonempty native downloads. A task row marked **Success** can mean work was
handed to a thread; it does not prove the later tool/share succeeded. If the
history shows **No thread found**, inspect the matching actual thread/download
evidence if it exists; otherwise acceptance is unverified/failed. The historical
preview lookup caveat is not proof that a new missing thread is harmless.

An accepted **Run now** proves a manual execution only. Recheck the saved next
UTC time and later verify the first timer-triggered occurrence separately;
do not label a manual execution as a successful cron firing. The retained
9 October task receipt and 13 October normal-chat receipt in the
[README](README.md#verification-and-troubleshooting) are different historical
events, not a new customer task or a current-source timer validation.

If automation fails, preserve the sanitized error and stop. Resolve the exact
identity/source/budget/publication blocker through the approved operator
process, then request a deliberate rerun. Never hide failure with a smaller
scope, missing files, invented links or a SIMULATED result.

The optional demo would need a **separate, explicitly SIMULATED** task and its
simulation specialist, only if requested. Do not install or schedule it as
part of the default LIVE workshop.

Official references: [Automate workflows](https://learn.microsoft.com/azure/sre-agent/automate-workflows),
[create/edit scheduled tasks](https://learn.microsoft.com/azure/sre-agent/create-scheduled-task),
[user roles](https://learn.microsoft.com/azure/sre-agent/user-roles).
