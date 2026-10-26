# 05 - Read-only Service Health events review

**Implementation state: LIVE_VALIDATED in the approved lab on 2026-10-14 UTC.**
The normal default-window run and one manual execution of the monthly task
each produced four verified native downloads. The generic package and masked
lab captures are published in this **private repository**. Those dated receipts
are reference evidence, not a deployment into your subscription or proof of
complete historical coverage. Follow the customer setup below in your own
approved SRE Agent.

This case gives operators one source-qualified review of Microsoft-published
service incidents and planned maintenance for a fixed approved subscription.
It complements resource availability/alert reviews: those are different sources
from `Microsoft.ResourceHealth/events`. Consolidation can reduce repeated portal
inspection; no incident-prevention, outage, SLA, compliance or savings outcome
is claimed.

## Before the meeting: customer inputs and access

| Bring or confirm privately | Ready when |
|---|---|
| Access to this guide and its files | Attendees have approved read access to the private repository, or an approved offline copy/screen-shared guide. Do not change repository visibility or share another person's GitHub credentials. |
| Existing SRE Agent and human setup access | You can open the intended agent; the setup user has the SRE roles in step 1. No new agent, paid resource or GitHub connector is required to paste the standalone tool. |
| Approved source scope | Record the **monitored** tenant/subscription, existing SRE UAMI Client ID and separate Object/Principal ID privately. The monitored subscription is not automatically the subscription hosting the SRE Agent. |
| Source-read access and an access administrator | Existing assignments cover the two ARM reads below, or the customer's authorized administrator has approved the required scoped access. No Graph/Global Administrator step from another case applies. |
| Deployment files and editor | Download the complete standalone Python file, parameter schema, runtime `SKILL.md`, specialist instructions and monthly prompt. Use private staging outside the generic Git checkout; cloning/building is optional. |
| Branding and acceptance owner | Blank logo/`CLIENTE` is acceptable. If desired, prepare an authorized small PNG/JPEG privately. Agree who may submit the first chat and, separately, one manual task acceptance, download the files and review blind spots. |

**Walkthrough:** [1. Permissions](#1-confirm-scope-and-separate-permissions) |
[2. Configure/create tool](#2-configure-a-private-copy-and-install-the-actual-tool) |
[3. Create skill/specialist](#3-install-and-restrict-the-runtime-specialist) |
[4. First chat](#4-generate-a-report-and-ask-grounded-questions) |
[5. Four files](#5-inspect-the-actual-files-and-native-delivery) |
[6. Monthly task](#6-configure-and-verify-the-monthly-task) |
[Troubleshooting](#troubleshooting-and-boundaries).

The annotated pictures show **actual saved lab objects and dated reports**,
not creation wizards or customer-specific values to copy. Portal releases can
call the authoring area **Builder** or **Build + setup**, and **Skills** or
**Skill builder**. Use the named object/field and saved readback when a label
differs; do not infer access or successful deployment from a visible button.

![Actual Service Health report overview, with customer branding replaced by CLIENTE and opaque identifiers masked](images/report-01-overview.png)

**Actual normal snapshot, 2026-10-14 22:14:58 UTC.** Callout **1** separates
the requested September last-update interval from the source-read times and
365-day retained query. Callout **2** keeps the overlapping temporal lanes
separate. Customer-name/logo pixels are replaced by `CLIENTE`; dates, counts,
provider text and uncertainty are unchanged.

## Source and evidence contract

```mermaid
flowchart LR
    subgraph Triggers["1. Invocation"]
        CHAT["Normal Chat<br/>(report or query)"]
        TASK["Monthly Task<br/>0 10 1 * * UTC"]
    end
    subgraph Runtime["2. Restricted SRE Specialist"]
        AGENT["Custom Agent: service-health-live<br/>Explicit tool + skill names · No shell/writes"]
        TOOL["generate-service-health-report<br/>11 typed params (limit/offset = int)<br/>ManagedIdentityCredential(client_id=...)"]
    end
    subgraph AzureARM["3. Fixed Subscription Native GETs (2025-05-01)"]
        EVENTS["GET .../providers/Microsoft.ResourceHealth/events<br/>No eventType OData filter · 365d queryStartTime"]
        IMPACT["GET .../events/{id}/impactedResources<br/>Per-event potential resource associations"]
    end
    subgraph Processing["4. Local Selection & 3 Overlapping Views"]
        FILTER["Keep ServiceIssue & PlannedMaintenance<br/>Count & exclude other categories without bodies"]
        LANES["1. Requested updates (lastUpdateTime)<br/>2. Active observed at collection<br/>3. Future communicated maintenance"]
    end
    subgraph Outputs["5. Native 4-File Bundle (<= 4.8 MB each)"]
        FILES["1. Self-contained HTML workpaper<br/>2. Complete source JSON<br/>3. Events CSV · 4. Impacted-resources CSV"]
    end
    CHAT --> AGENT
    TASK --> AGENT
    AGENT --> TOOL
    TOOL --> EVENTS
    EVENTS --> FILTER
    FILTER --> IMPACT
    IMPACT --> LANES
    LANES --> FILES
```

```mermaid
flowchart LR
    S1["1. Scope & 3 permission layers<br/>(Author + Standard User + UAMI Reader)"] --> S2["2. Configure 6 private constants<br/>& create Python tool (11 params)"]
    S2 --> S3["3. Create runtime skill &<br/>restricted specialist (1 tool, 1 skill)"]
    S3 --> S4["4. Validate normal chat<br/>(single report call)"]
    S4 --> S5["5. Verify 4 native downloads<br/>(HTML, JSON, 2 CSVs)"]
    S5 --> S6["6. Optional monthly task<br/>(0 10 1 * * UTC)"]
```

| Source | Read contract and scope | Time and completeness |
|---|---|---|
| Native subscription events | HTTPS GET `https://management.azure.com/subscriptions/{configured-id}/providers/Microsoft.ResourceHealth/events`, API `2025-05-01`, **no OData filter**; fixed local selection of `ServiceIssue` and `PlannedMaintenance` | Explicit ISO UTC `queryStartTime` uses **lastUpdateTime**, not impact start. A retention-qualified lookback also keeps returned older Active events and future maintenance visible. |
| Per-event impacted resources | GET the same subscription/event path plus `/impactedResources`, API `2025-05-01`; event identifiers come from validated source records | Published potential association, not workload outage. Missing, denied, partial and successful-empty receipts remain distinct. |
| Complete JSON | Every accepted in-scope response field, page, record, native ID and original timestamp, plus derived views and source request/status receipts | No auth headers/tokens. Declared other event categories are counted and excluded without retaining advisory bodies. Unexpected sensitive/invalid/cross-subscription business records cause explicit redaction and partial coverage. |

The REST reference does not guarantee a complete monthly history. Current
[Health history documentation](https://learn.microsoft.com/azure/service-health/health-history-overview)
describes 90 days in the portal and backend storage **up to a year**. Neither
that upper bound nor HTTP 200 proves every relevant event was returned.
The report does not reconstruct historical daily status or automatically call
an announcement new/changed. `lastUpdateTime` is not a reliable publication
timestamp, and this package does not collect a previous-run baseline.

`ServiceIssue` and `PlannedMaintenance` remain distinct. Security/tenant
advisories, sensitive-event detail endpoints, emerging issues, support-case
reads/writes, Jira, alerts, workload telemetry and remediation are excluded.
An event name/Tracking ID and `externalIncidentId` are **not** Microsoft support
case references. No support integration is included.

The no-filter native feed is intentional: the `eventType` OData-filter variant
was rejected with `400 InvalidODataQueryOptions` in source preflight. That is
not `403` or a reason to grant broader permissions. Other categories can arrive
in the same subscription response. The ledger records received, in-scope and
excluded-category counts separately; exclusion by declared business scope is
not hidden size truncation. No sensitive-event detail endpoint is called.

REST examples show provider-scoped IDs, and the source also returns
`Microsoft.ResourceHealth/events/<name>` IDs. Both those literal forms and
fixed-subscription ARM IDs are retained unchanged. Subscription scope comes
from the validated request and receipt, not a fabricated ID prefix.

## Package

| File | Purpose |
|---|---|
| [generate-service-health-report.py](generate-service-health-report.py) | Standalone, pasteable Python tool; no runtime import of local assets |
| [engine.py](engine.py), [report_template.html](report_template.html), [build_tool.py](build_tool.py) | Maintainable source and reproducible build; no additional runtime service |
| [tool-parameters.schema.json](tool-parameters.schema.json) | Matching Azure SRE parameter schema; numeric runtime type **int**, not `integer` |
| [requirements.txt](requirements.txt) | `azure-identity` and Pillow; remaining code uses the standard library |
| [Runtime skill](skills/service-health-live/SKILL.md) | Source/time/output interpretation and strict action boundaries |
| [Subagent setup and prompts](subagent-instructions-and-prompts.md) | Only `service-health-live` with only `generate-service-health-report` |
| [Monthly task prompt](monthly-task-prompt.md) | Copy-ready monthly fields/prompt; creates no actual task |
| [Tests](tests/test_contract.py), [browser check](tests/test_report_ui.py) | Permanently SIMULATED source-shaped checks and offline UI verification |
| [Private replay helper](tests/private_replay.py) | Explicit opt-in operator-receipt replay/budget check; no source call or bundled private input |
| [PRODUCT.md](PRODUCT.md), [SURFACE.md](SURFACE.md), [DESIGN.md](DESIGN.md) | Case-local product, surface and built design contracts |

No other case, root navigation, IAM or infrastructure is changed by this
package. The authorized rollout created only this case's new tool, skill,
restricted specialist and monthly task; existing task configurations were
preserved.

## Temporal and coverage rules

The normal report requests the previous complete UTC calendar month of
**lastUpdateTime** updates. Its native feed explicitly asks from
`reference_utc - 365 days` so returned Active records are not removed merely
because their impact started before the requested month. The backend's
"up to a year" is an upper retention description, not proof of full data or
of Active events older than the retained response.

The HTML makes the three views independent:

| View | Exact meaning | Does not establish |
|---|---|---|
| Requested updates | `requested_start <= lastUpdateTime < requested_end` | Impact-start history, first publication or new/changed since last run |
| Active observed | Native current `status == Active` when the page was read | Ongoing impact interval, historical as-of state or actual workload outage |
| Future maintenance | `PlannedMaintenance`, not reported Resolved, future source impact start and no contradictory start/mitigation ordering | Guaranteed execution, first announcement or newness |

An event can occupy multiple views. The recorded published-date context keeps
Active separate from source mitigation at/before the reference, unknown/open
dates, future starts and inconsistent dates. It never silently changes Active
to Resolved or calls a source interval measured workload downtime.

One run reference, actual per-page read times, requested interval, source query
lower bound and observed last-update extent travel with the JSON. An observed
extent is not complete coverage. Native timestamps remain untouched in source
records; comparisons support source fractions up to nanoseconds. Custom
requested bounds preserve microseconds and reject nonzero finer input rather
than round silently. Invalid/missing native dates remain Unknown.

| Outcome | Interpretation |
|---|---|
| `complete` | Accepted returned records and pagination finished; not full history or health proof |
| `successful_empty` | Valid completed native list with no accepted/received records |
| `successful_empty_in_scope` | Native list completed but contained only declared excluded categories |
| `not_collected` | No receipt supplied in an explicitly marked private replay; no invented fresh read |
| `denied` | First unavailable page returned 401/403; never healthy zero |
| `unavailable` | Failed/invalid first source page with no accepted records |
| `partial` | Accepted records retained alongside unfinished paging, failure, redaction, duplication or bounds |

The top-level `complete_returned_pages` means precisely that. HTTP 200, a
first-page count, one empty impacted-resource receipt or a successful-empty
event feed cannot prove historical completeness, no impacted workloads or
resilience.

## 1. Confirm scope and separate permissions

There are **three separate permission decisions**:

| Who / layer | Required access and scope |
|---|---|
| Human creating tools, skill and specialist | **SRE Agent Author** on the **SRE Agent resource > Access control (IAM)**. Author alone cannot chat or create scheduled tasks. |
| Human running chat and managing the reporting task | **SRE Agent Standard User** on that SRE resource. For one person doing the whole walkthrough use **Author + Standard User**; **SRE Agent Administrator** is the full-management alternative, not an automatic requirement. |
| Runtime UAMI reading Azure | Approved ARM read access at the subscription scope for `Microsoft.ResourceHealth/events/read` and `Microsoft.ResourceHealth/events/impactedResources/read`. Existing subscription **Reader** (`*/read`) covers these normal reads; an organization may approve a narrower custom read role. Resource-group-only scope does not cover this subscription feed. |
| Customer access administrator | Separate authority to assign roles at the intended scope, such as an appropriately scoped **Role Based Access Control Administrator** or **User Access Administrator**, subject to organizational conditions. SRE Author/Standard User does not itself grant IAM assignment authority. |

The first two rows are SRE **data-action** roles, not source permissions.
Azure Owner/Contributor alone does not replace them. Conversely, giving a
human a SRE role does not give the configured UAMI subscription access.
See [SRE user roles](https://learn.microsoft.com/azure/sre-agent/user-roles),
[Resource Health read operations](https://learn.microsoft.com/azure/role-based-access-control/permissions/management-and-governance#microsoftresourcehealth)
and [role-assignment prerequisites](https://learn.microsoft.com/azure/role-based-access-control/role-assignments-portal).
These operation names identify the reader's needs; they are not an untested
custom-role deployment template. Sensitive/advisory fetch permissions are
separate and are not required by this case.

Collect the values without putting them in chat or generic Git:

1. Open the customer's existing agent in the SRE portal. Go to
   **Settings > Azure settings > Managed Identity > Go to Identity**.
   On the user-assigned identity's Azure page, copy **Client ID** for
   `MANAGED_IDENTITY_CLIENT_ID` and **Object (principal) ID** for the
   administrator's IAM checks. These two GUIDs are not interchangeable.
2. Confirm this is the UAMI associated with and available to the intended
   SRE runtime, not an arbitrary identity that merely exists in the directory.
   Do not substitute the agent's internal system-assigned identity. If the
   association/runtime availability is missing, stop for the customer's SRE
   administrator; pasting a Client ID does not attach an identity.
3. In Azure portal **Subscriptions > the approved subscription > Overview**,
   copy its **Subscription ID**. Confirm its tenant in subscription
   **Properties** or **Microsoft Entra ID > Overview > Tenant ID**, using the
   correct directory. Do not copy the SRE agent's resource ID into either field.
4. Review the human's access at the SRE resource and the UAMI's assignments at
   the approved subscription, using IAM **Check access** / role assignments.
   If reads are missing, the customer's authorized access administrator owns
   approval and assignment outside this specialist. Do not use an auto-assign
   Administrator banner, mute a warning as a fix, or grant Owner/Contributor
   to make a read succeed.

If the SRE Agent and monitored resources are in different subscriptions,
retain the approved monitored subscription in the code and the actual SRE
resource for human role checks. Confirm compatible tenant/identity and
explicit approved cross-subscription read access; do not move/create resources
or assume the SRE subscription ID is the reporting scope.

Use the UAMI's **Client ID**, not Principal/Object ID, in the tool.
The code uses `ManagedIdentityCredential(client_id=...)` exclusively and checks
token tenant, client and ARM audience against fixed configuration. There is no
Azure CLI, human account, `DefaultAzureCredential`, secret, token-in-chat,
alternate tenant or fallback identity.

No Microsoft Graph grant, Entra Global Administrator, secret or extra connector
is needed for these subscription ARM reads. Verify the actual event and
per-event resource receipts in the authorized first report, not just inventory
visibility. A valid empty feed checks access/shape, not nonempty relationships
or resilience. Do not create events or start infrastructure for a demonstration.

### Customer-admin only: assign already-approved missing access

**Only the customer's authorized access administrator performs these portal
steps, outside the reporting specialist.** First check direct and inherited
assignments with **Check access** / **Role assignments**; do not duplicate
effective access. If **Add role assignment** is disabled, stop for the
authorized administrator rather than self-elevating.

1. Open the **approved scope > Access control (IAM) > Role assignments >
   Add > Add role assignment**. On **Role**, select the **preapproved role**,
   then **Next > Members**.
2. **For humans:** the scope is the **actual SRE Agent resource**. For the
   Author + Standard User setup, select **SRE Agent Author**, then on
   **Members** choose **User, group, or service principal > Select members**.
   Select the approved operator/group and **Select**. Complete the review in
   step 4 for each missing role; repeat the full flow separately for
   **SRE Agent Standard User** only if that access is missing.
3. **For source reads:** the scope is the **approved MONITORED subscription**,
   not automatically the SRE-host subscription or the UAMI resource. Select
   **Reader only if subscription-wide Reader was explicitly approved and is
   missing**. On **Members**, choose **Managed identity > Select members >
   User-assigned managed identity**. If a subscription filter appears, use
   the UAMI's **hosting subscription** to find it; this does not change the
   assignment's monitored scope. Select the **exact existing UAMI**, verify
   its **Object/Principal ID** against the identity details collected above
   (not its Client ID), then **Select**. Approved subscription Reader covers
   both cases05/06; do not add a redundant Backup Reader role.
4. Only the authorized customer administrator may finish **Review + assign**,
   after checking the exact **principal, role, scope, conditions and approved
   assignment type/duration**. Review the summary, then select
   **Review + assign** only when it matches the customer's approval.

For a customer-approved narrower design, use the customer's separate
custom-role approval process; this guide does not generate grants or widen
scope. Honor customer PIM and conditions: humans may need normal PIM
activation; **managed identities cannot activate eligible PIM roles**, so the
administrator must ensure the approved UAMI access is active. Do not change
PIM/Conditional Access policies, force permanent access or use auto-assign Admin.
See the [official portal and assignment-type instructions](https://learn.microsoft.com/azure/role-based-access-control/role-assignments-portal).

The customer handles propagation and any required access/session refresh under
normal policy. Confirm the saved assignments, then verify actual access through
the first authorized report's source receipts; a portal row or guessed status
does not prove the reads succeed.

**Checkpoint:** the customer has approved the exact subscription, identified
the runtime-available UAMI and recorded both ID types correctly; human SRE
access and UAMI source access have been reviewed independently.

## 2. Configure a private copy and install the actual tool

### Download and configure, without rebuilding

Open [generate-service-health-report.py](generate-service-health-report.py)
in the approved repository view and use **Download raw file**, or open **Raw**
and save the complete plain Python file into **private staging**. Do not save
the GitHub HTML page, a screenshot, a copied code viewport or a `.py.txt` file.
With an approved offline package, use the supplied complete `.py` directly.
Download the linked schema and runtime skill/instruction files as well.

You do **not** need to clone the repository, edit `engine.py`, rebuild the
template, install authoring dependencies or run local tests to deploy the
existing standalone file. Those optional maintainer steps are in step 7.
Keep the original generic download, then edit **only these six administrator
fields** in a separate private deployment copy:

```python
SUBSCRIPTION_ID = "<APPROVED_SUBSCRIPTION_ID>"
TENANT_ID = "<APPROVED_TENANT_ID>"
MANAGED_IDENTITY_CLIENT_ID = "<APPROVED_UAMI_CLIENT_ID>"
CLIENT_NAME = "CLIENTE"
COMPANY_LOGO_DATA_URI = ""
COMPANY_LOGO_ALT_TEXT = "Customer logo"
```

| Fixed field | Value to use |
|---|---|
| `SUBSCRIPTION_ID` | Approved **monitored** subscription GUID from step 1, not its display name or automatically the SRE-host subscription |
| `TENANT_ID` | That subscription's tenant GUID |
| `MANAGED_IDENTITY_CLIENT_ID` | The existing SRE UAMI **Client ID**, not Object/Principal ID |
| `CLIENT_NAME` | `CLIENTE` is valid; an authorized private customer label must be 1-120 plain characters |
| `COMPANY_LOGO_DATA_URI` | Leave `""` for the placeholder, or one authorized embedded PNG/JPEG data URI |
| `COMPANY_LOGO_ALT_TEXT` | Descriptive plain text, 1-120 characters; keep `Customer logo` when blank |

On an explicit `main()` call, placeholders fail **before authentication or
source collection**.
Never put actual identifiers, private configuration, source exports, customer
name/logo/Base64 or source URLs in the generic Git version.

The explicit configuration comment marks where the customer's logo goes.
An optional authorized embedded PNG/JPEG must decode as a real Pillow-validated
raster, matching its MIME, one frame, at most **100,000 bytes** and
**2048 x 2048 pixels**. Invalid branding fails before collection. No remote logo
fetch or SVG is accepted. Use adjacent short Base64 strings, **less than 10,000
characters per line**, for the target editor. With an empty logo the visible
`CLIENTE` / Customer logo frame remains.

For an optional logo, prepare the data URI locally in approved private tooling:
`data:image/png;base64,` plus the Base64 of the **complete file bytes** (or
`data:image/jpeg;base64,` for JPEG). It is not a filename, URL, SVG or the Base64
of a PDF. Keep all preparation/output outside Git. If logo preparation is not
ready, leave the logo empty rather than blocking the source review or changing
the report design.

To generate a ready-to-paste `COMPANY_LOGO_DATA_URI = (...)` block with
88-character data chunks, roughly 94-character Python source lines (the runtime
editor requirement remains `< 10,000` characters per line), from a local PNG
file on Windows PowerShell (change `image/png` to `image/jpeg` if using a
`.jpg`/`.jpeg` file):

```powershell
python -c "import base64, sys, textwrap; from pathlib import Path; b = Path(r'C:\path\company-logo.png').read_bytes(); 0 < len(b) <= 100000 or sys.exit('Use a logo of 1 to 100000 bytes'); u = 'data:image/png;base64,' + base64.b64encode(b).decode('ascii'); print('COMPANY_LOGO_DATA_URI = (\n' + '\n'.join('    ' + repr(s) for s in textwrap.wrap(u, 88)) + '\n)')"
```

### Create the Python tool in the customer's SRE Agent

If a tool, skill or specialist with the exact case name already exists, verify
customer ownership and the complete saved contract before reusing it. Do not
overwrite an unrelated name collision or create duplicate case objects.

1. In the intended agent, open **Builder > Agent Canvas > Create > Tool >
   Python tool**. Use the existing-code **Code** tab, not **Generate** or
   **Refine with AI**: the complete reviewed implementation already exists.
2. Set the exact name **`generate-service-health-report`**. For its description
   use: `Read-only ServiceIssue and PlannedMaintenance review for the fixed
   approved subscription; complete HTML, JSON and two CSV files, or bounded
   source-qualified queries. No Azure writes.`
3. Paste the **entire privately configured standalone file** into the code
   editor, without Markdown fences. Do not paste just `main()` or import
   `engine.py`; the standalone file already embeds its HTML template.
4. Review the runtime settings below, then match **all 11** parameter rows
   in the following table to [tool-parameters.schema.json](tool-parameters.schema.json).
   Do not let a generated schema rename or drop fields.
5. Select **Create tool** when the form is complete, then reopen the saved tool.
   If this portal version requires a playground test before creation, treat
   that as an additional customer-authorized live read, not a harmless syntax
   check. Do not repeatedly press **Test** or use tests to collect screenshots.
   The first normal-chat acceptance in step 4 is still a separate delivery gate.

| Setting | Customer setup / accepted lab reference |
|---|---|
| Timeout (`timeoutSeconds`) | **900 seconds**, matching the saved lab setting, within the documented 5-900 second range. The code retains its own 180-second collection guard; the platform default 120 seconds is not the accepted setting. |
| Runtime packages | [requirements.txt](requirements.txt): `azure-identity>=1.19,<2` and `Pillow>=12.2,<13`. `azure-identity` supplies explicit UAMI auth; Pillow validates a nonempty logo. No extra runtime template/library is needed. |
| Dependencies/packages field, if exposed | The accepted lab had `dependencies=[]`: the packages were already installed. Verify availability in the customer's runtime. Only if missing, have the runtime administrator use the supported dependency configuration and the manifest's compatible versions; field syntax/availability varies. Do not add `pip install` to the tool or give this specialist a shell. |
| Identity / platform authentication | Saved lab values: `authEnabled=false`, `authScopes=null`, `toolMode=Auto`. Authentication is **disabled** at this platform layer because the code acquires its own ARM token through the fixed UAMI Client ID. Do not enable generic preset scopes or replace this flow with the product tutorial's separate Identity-tab example. |

These are saved configuration fields, **not additional `main()` parameters**.
If an advanced setting is not exposed in your portal, use the customer's
approved administrator configuration/readback route rather than inventing a
wizard field. Source code enforces enum/bound constraints even when a parameter
editor exposes only name/type/value; retain the documented Python defaults.

This case's schema is an Azure SRE runtime schema, not standards-compliant JSON
Schema: the runtime numeric type is **`int`**, not `integer` or a quoted number.
Keep Python's typed signature and runtime rows aligned:

| Parameter | Runtime type | Default | Allowed values / constraint |
|---|---|---|---|
| `operation` | `string` | `report` | `report`, `query` |
| `period` | `string` | `auto` | `auto`, `previous_month`, `last_24h`, `last_7d`, `custom`; `auto` means previous UTC month for report, last 24 hours for query |
| `start_utc` | `string` | `""` (empty) | Only `custom`; ISO UTC `Z`/zero offset, at most 40 characters and microsecond precision |
| `end_utc` | `string` | `""` (empty) | Only `custom`; exclusive end after start, no later than the run reference; at most 40 characters |
| `view` | `string` | `summary` | `summary`, `events`, `resources`, `coverage`; query projection |
| `event_type` | `string` | `all` | `all`, `ServiceIssue`, `PlannedMaintenance` |
| `state` | `string` | `all` | `all`, `Active`, `Resolved`, `Unknown` |
| `time_scope` | `string` | `all` | `all`, `requested_updates`, `active_now`, `future_maintenance` |
| `search` | `string` | `""` (empty) | At most 160 plain characters; case-insensitive local substring, not KQL/URL |
| `limit` | `int` | `10` | 1-50; no float, boolean or numeric string |
| `offset` | `int` | `0` | 0-10,000; use returned `next_offset` for an explicitly requested query page |

Reports require the default `view`, filters, search, limit and offset.
Event filters apply only to `events`/`resources` queries, not `summary` or
`coverage`. Non-custom periods require empty start/end. Custom windows must be
ordered, past, at most 93 days and within the 365-day retained-source lookback.
Do not expose identity, branding, URL, path, subscription or token parameters.

The canonical tool is **definitions-only at load/exec time**, including when
the SRE loader sets `__name__="__main__"`. It has no CLI autorun block,
environment-guessing guard, load-time authentication, collection, printing or
artifact writes. The platform owns the single explicit `main(...)` invocation.
Running the canonical file directly does not collect a report; use the
explicitly SIMULATED offline helper below for a local demonstration. Preserve
this pure-load contract when editing or deploying the code: an autorun guard
can collect once during hydration and again during normal invocation.

**Checkpoint:** reopen the newly saved `generate-service-health-report` in
**Agent Canvas** (or **Table view > Python tools**). Inspect **Python Code**,
**Query parameters** and runtime settings: complete source, only the six
private configuration edits, one `main`, all 11 types/defaults, timeout and
dependencies. Search for the tool itself; the specialist does not exist yet.
After step 3 you can also find it by filtering to `service-health-live`.

![Actual saved Python tool, main entry point and eleven typed parameters](images/setup-01-saved-tool-main-parameters.png)

Callout **1** is the saved tool. **2** shows its actual `main()` entry point;
the separately verified full source has no CLI autorun block. **3** shows all
11 runtime parameters, including `limit` and `offset` as `int`. Private
configuration and logo Base64 are outside the captured code viewport and
are not included in this repository. Blank **Value** cells in this saved-detail
table are not instructions to delete defaults: use the schema/main defaults
listed above.

### Bounded native reads

- HTTPS GET only, fixed ARM origin/subscription and API `2025-05-01`.
- One native event feed with explicit ISO queryStartTime; local category
  selection; per-event impactedResources from validated source names.
- No redirects, custom requests, user-supplied URL/path/token/KQL or source
  scope overrides. No tenant/sensitive detail APIs or writes.
- At most 25 pages per list, 500 accepted event records, 5,000 accepted
  impacted-resource records per list and 250 shared HTTP attempts. A
  180-second collection deadline is checked between bounded acquisition/read
  steps; it is not a claim of process preemption during a blocking I/O step.
- One bounded retry for 429/500/502/503/504; at most 20 seconds per HTTPS read;
  response body bound 20,000,000 bytes so an unrelated advisory-rich native
  page can be read and excluded honestly rather than clipped.
- Managed-identity transport uses 5-second connection / 10-second read timeouts
  and no SDK retries. Deadline expiry during token acquisition cannot start an
  ARM read. Native response streaming checks the deadline between buffered
  reads; an incomplete body never becomes a completed list.
- Loop/duplicate detection. Full accepted records in the received page remain
  in JSON when a bound or later page fails.
- Continuation origin/path/version and explicit scope cannot change. For the
  documented native continuation form omitting queryStartTime, the original
  fixed lower bound is restored and recorded; explicit changed bounds are
  rejected. Original returned nextLink and effective page request both remain.
- Ambiguous duplicate JSON keys, nonfinite values, invalid JSON and nesting
  beyond 50 levels fail explicitly rather than become plausible data.
- A shared accepted-evidence byte guard stops collection if its retained pages
  alone cannot fit the complete JSON limit. Unrelated excluded-category bodies
  do not consume that retained-evidence budget; no eligible fields are dropped.

No cloud infrastructure is needed by the adapter. Existing SRE/runtime/AI costs,
requests and operational review effort still exist; read-only does not mean
zero cost. No savings, cost forecast or extra-resource deployment is promised.

## 3. Install and restrict the runtime specialist

Create the **runtime skill first**, then its separate restricted specialist:

1. Open **Builder > Skills** (called **Skill builder** in the lab captures).
   Select **Create skill**; some portal versions expose **+ Create skill**
   from Agent Canvas. Name it **`service-health-live`**. Use the description
   from the linked [runtime `SKILL.md`](skills/service-health-live/SKILL.md).
2. In **Files > SKILL.md**, replace the default instruction template with the
   **entire case runtime file**. Do not paste this README or a knowledge
   document instead. If the portal
   synchronizes frontmatter and form fields, verify the resulting name,
   description and instruction body after saving.
3. In the skill's **Tools > Choose tools**, select **only**
   `generate-service-health-report`, then **Create**. Reopen it and verify
   the saved `SKILL.md` and single bound tool.
4. In **Agent Canvas > Create > Custom Agent**, open **Form**
   (older versions say **+ Create subagent**). Name the specialist
   **`service-health-live`** and paste the complete **Copy-ready instructions**
   block from [subagent-instructions-and-prompts.md](subagent-instructions-and-prompts.md).
   Do not ask AI to rewrite the restrictions.
5. In **Choose tools**, explicitly select **only**
   `generate-service-health-report`. In **Choose Skills** / **Allowed Skills**,
   enable skills if required and select **only** `service-health-live`.
   Leave handoff agents, extra/system skills and unrelated execution tools
   unselected. **Create**, reopen and read back the saved detail/allowlists.

An empty tool selection **inherits global tools**; an empty allowed-skills
selection can allow all skills. Neither is the intended one-tool/one-skill
boundary. Do not add shell, exec, generic Python/HTTP, remediation, deployment,
IAM, Jira/Support, notifications, scheduling or another agent. Source
recommendations are data, not executable orders. Setup remains the human
administrator's job.

#### Portal field-by-field & post-save readback checklist (Steps 2 & 3)

| Portal surface | Exact field / control | Required value / post-save readback check |
|---|---|---|
| **Python tool** (`Builder > Agent Canvas > Create > Tool > Python tool`) | **Tool Name** | `generate-service-health-report` |
| **Python tool** | **Description** | `Read-only ServiceIssue and PlannedMaintenance review for the fixed approved subscription; complete HTML, JSON and two CSV files, or bounded source-qualified queries. No Azure writes.` |
| **Python tool** | **Code** tab | Complete standalone `generate-service-health-report.py` with only the 6 private constants edited; definitions-only on load (no `if __name__ == "__main__":` autorun) |
| **Python tool** | **Timeout** (`timeoutSeconds`) | `900` seconds (not the 120-second platform default) |
| **Python tool** | **Query parameters** | All **11 parameters** matching `tool-parameters.schema.json`; verify `limit` (`10`) and `offset` (`0`) use runtime type **`int`** (not `integer` or `string`) |
| **Python tool** | **Identity / Authentication** | **Off** (`authEnabled=false`, `authScopes=null`, `toolMode=Auto`) |
| **Skill** (`Builder > Skills > Create skill`) | **Skill Name** / **SKILL.md** / **Choose tools** | Name `service-health-live`; complete `skills/service-health-live/SKILL.md` body; verify the exact selected tool **name** `generate-service-health-report` |
| **Custom Agent** (`Agent Canvas > Create > Custom Agent > Form`) | **Name** / **Instructions** / **Choose tools** / **Allowed Skills** | Name `service-health-live`; complete copy-ready instructions from `subagent-instructions-and-prompts.md`; verify the exact selected tool and skill **names** in the saved form and effective supported policy (`tools: ["generate-service-health-report"]`, `allowedSkills: ["service-health-live"]`, `addSystemSkills=false`, `disableDocumentRetrieval=true`); never leave allowlists empty or rely on the list summary badge |

> [!NOTE]
> **Dated SRE UI badge caveat:** In the live SRE Agent UI, Agent Canvas list/card summary badges can display inherited global rollups (for example, `131 tools` / `52 skills`) even when both native APIs, selected chips and the saved form policy enforce one explicit tool and skill (`tools`, `allowedSkills`, `addSystemSkills=false`, `disableDocumentRetrieval=true`). Verify the exact selected tool and skill **names** in the saved form and effective supported policy; the list summary badge is not authoritative restriction proof, and you must not modify globals to change it.

**Checkpoint:** the saved skill contains the correct complete `SKILL.md` and
one bound tool; the saved specialist has the exact name/instructions, **one
explicit selected tool and one selected skill**, with no inherited execution
tools. The pictures below are historical readbacks, not new-object forms.

![Actual saved runtime skill and its single reporting tool](images/setup-03-saved-runtime-skill.png)

Callouts **1-3** identify the saved skill, its single case05 tool and its
`SKILL.md` file. The reusable instruction content is linked in the package
table above.

![Actual restricted Service Health specialist with one selected tool and matching skill](images/setup-02-restricted-agent.png)

Callout **1** shows **Tools - 1**. **2** identifies the selected
`generate-service-health-report`; **3** identifies the attached
`service-health-live` skill. No global execution/remediation tools were
added to this specialist.

## 4. Generate a report and ask grounded questions

After customer approval for a source read, select **New chat thread** in the
customer's agent. Select the **`service-health-live`** specialist using the
agent picker or the portal's `/agent` selection. Verify the selected responder,
not just a typed name in the message. Paste this **natural-language prompt**:

```text
Use service-health-live and only generate-service-health-report. Generate one
read-only Service Health review with operation="report", period="previous_month",
and every other parameter at its default. Do not run another query or report.
Deliver the four actual files: HTML, complete JSON, events CSV and
impacted-resources CSV, using the returned native links unchanged.
State the actual UTC lastUpdateTime interval, reference, retained query start
and partial/unknown coverage. Keep observed Active and future maintenance
separate from requested-month updates. Do not change Azure or create tickets.
```

The expected **single tool call** is
`{"operation":"report","period":"previous_month"}` with the remaining defaults.
This is the call to inspect in the thread, not JSON you must run manually.
No CLI, token, subscription or credential belongs in the chat.
Reports retain all collected in-scope evidence, including records outside the
requested-update view.

Optional **Spanish (ES)** equivalent natural-language prompt for the same single
`previous_month` report call:

```text
Usa service-health-live y únicamente generate-service-health-report. Genera una
única revisión de solo lectura de Service Health con operation="report",
period="previous_month" y todos los demás parámetros en su valor por defecto.
No ejecutes otra consulta ni otro informe. Entrega los cuatro archivos reales:
HTML, JSON completo, CSV de eventos y CSV de recursos impactados, usando sin
cambios los enlaces nativos devueltos. Indica el intervalo UTC real de
lastUpdateTime, la referencia, el queryStartTime retenido y cualquier cobertura
parcial o desconocida. Mantén separados los eventos Active observados y el
mantenimiento futuro respecto de las actualizaciones del mes solicitado. No
modifiques Azure ni crees tickets.
```

Wait for the tool result, then use step 5 to open/download **all four files**.
Read the actual UTC interval and source ledger before counts. `partial` files
are still usable with their blind spots; a successful-empty feed is not a
healthy-workload finding. On `status="error"`, keep the sanitized error and
stop: there are no valid report links to invent. Customer counts, dates and
empty/denied outcomes need not match the lab.

**Checkpoint:** exactly one explicit report invocation, the intended fixed
scope/window, a final result and four actual downloadable files, with each
source/coverage limitation retained. A chat summary or one HTML link alone
does not complete this gate.

### Historical normal-run reference

The accepted normal run used `operation="report", period="auto"` with the
other defaults. Here `auto` resolves to the same previous UTC month as the
explicit report example above. It collected once at **22:14:58 UTC**; opening
its downloaded report later did not recollect data.

![Actual normal execution thread and its four native file links](images/setup-04-normal-files.png)

Callouts **1-3** mark the actual HTML, complete JSON and ordinary CSV delivery
in that thread. The reporting assistant correctly left HTTP verification to
the operator; the four independent HTTP 200/file-byte receipts were obtained
afterward. No live artifact URL, thread UUID or private raw export is
published here.

### Optional, explicitly requested grounded questions

For questions about the downloaded snapshot, inspect its local HTML/JSON;
the tool does not reopen a prior report by path. For a **fresh source query**,
keep the same specialist selected and use a separate explicit prompt, for
example:

```text
Using service-health-live, make one fresh generate-service-health-report call
with operation="query", period="last_24h", view="events",
time_scope="requested_updates", limit=5, and all other defaults.
Show the returned totals and source coverage. These are last-updated records,
not necessarily new incidents or measured workload outages. Do not fetch
additional pages or create another report.
```

Copy-ready maintenance and coverage questions, with exact expected calls, are
in [the specialist prompt guide](subagent-instructions-and-prompts.md#report-and-grounded-question-prompts).

Optional **Spanish (ES)** equivalent natural-language prompt for the same fresh
`last_24h` query call:

```text
Usando service-health-live, realiza una única llamada nueva a
generate-service-health-report con operation="query", period="last_24h",
view="events", time_scope="requested_updates", limit=5 y el resto de valores
por defecto. Muestra los totales devueltos y la cobertura de las fuentes. Estos
son registros actualizados recientemente, no necesariamente incidentes nuevos ni
caídas medidas de cargas de trabajo. No consultes páginas adicionales ni generes
otro informe.
```

Queries disclose total, returned count, requested limit, next offset, has_more
and transport cap. **Each invocation is a fresh collection**, not a stable
cursor or a read of the previous report. Do not secretly enumerate pages just
to learn a total already returned. A single oversized projected row returns
an explicit error directing the operator to complete report JSON.

## 5. Inspect the actual files and native delivery

In the completed customer thread, open each of the four returned native file
links/widgets and **download** it to approved private storage. Open the saved
HTML in a browser; it is self-contained and makes no Azure reads. Check its
requested UTC last-update interval, temporal lanes, event/resource detail and
source ledger. Open the JSON in a text/JSON viewer and both ordinary CSVs in a
spreadsheet or CSV viewer. Keep the files from the **same run** together;
do not mix normal and monthly snapshots.

All four artifacts use unique names in the fixed **service-health-reports**
child of the actual guarded runtime cwd:

| File | Contract |
|---|---|
| HTML | Self-contained offline report, filters, complete filtered exports, event/resource detail, source ledger and print; no network, CDN, fonts or live polling |
| Complete JSON | All accepted in-scope fields/records, source envelopes, original timestamps/IDs, partial pages, source status/request/attempts and uncertainty |
| Events CSV | One row per accepted event observation, ordinary columns and complete `details_json` |
| Impacted-resources CSV | One row per accepted association record, ordinary columns and complete `details_json`; absent target IDs remain explicit |

JSON/HTML are UTF-8; CSV is UTF-8 with BOM and CRLF. CSV formula-leading values
receive an apostrophe safety prefix; original values remain in `details_json`
and complete JSON. Each CSV also retains subscription, API version and the
event-feed lower bound so provider-relative IDs stay source-qualified.
Full JSON download in HTML uses the **original embedded bytes**, not a
JavaScript reserialization. The raw JSON is embedded once. Record details and
complete filtered event/resource JSON and CSV details use validated **UTF-8
byte references** into those original bytes; only small CSV cells and receipt
metadata remain in the display manifest. Neither JS number conversion nor
UTF-16 character indexing can round numeric values or split Unicode source
text. The JSON display formatter changes whitespace only, not numeric
lexemes. Receipt exports retain their Python-produced exact JSON strings.
No codec or source/export-format change is required. Filtering/paging never
limits export rows to what is visible.

The tool prepares and checks every complete artifact **before writes**:
each plain file is at most **4,800,000 bytes**; complete normal tool-result
JSON is at most **3,500 UTF-8 bytes measured with default `json.dumps`**.
No record/window dropping, ZIP/Blob/Storage substitute or malformed response
is used to fit. Unique atomic writes, readback and cleanup errors are explicit.
These are repository/runtime compatibility guards, not published Azure API
quotas.
Filesystem roots, linked/junction cwd ancestors and output escapes are rejected.

Only an actual validated cwd matching either
`/root/sreagent/terminalRoot/tmp/ThreadFiles/<UUID>` or
`/usr/terminalRoot/tmp/ThreadFiles/<UUID>` yields native aliases. The actual
UUID and generated filenames are derived, never supplied as parameters or
static configuration. Immediately render returned `report_url`,
`snapshot_url`, `events_csv_url`, `resources_csv_url` unchanged. Do not invent
a host, thread prefix or sandbox URL.

For `local_files_only`, show unchanged real paths and disclose the unsupported
native root. `artifact_status=written` is not an HTTP/download receipt;
`http_verified=false` does not suppress provided native links. A partial
collection can still have valid files, which should be delivered with its
blind spots. The customer acceptance owner must verify all four real native
downloads, not just the existence of links.

**Checkpoint:** HTML opens, complete JSON parses, both CSVs open with their
headers/complete records, and all four downloads belong to the same reference
and scope. Retain real download failures separately from source blind spots.
Zero data rows with successful source receipts is a valid empty report, not
proof of no impact; denied/partial reads cannot be signed off as healthy zeroes.

### Read the actual report without changing its evidence

The following views all come from the **same unchanged downloaded normal
HTML**, collected at **2026-10-14T22:14:58Z**. Filters, expanded details and
viewport changes are report interactions, not new Azure reads.

<details>
<summary>Requested updates: four records, not four new incidents</summary>

![Actual requested-updates lane showing four September last-update records](images/report-02-requested-updates.png)

Callout **1** selects the last-update lane for the requested September UTC
interval. **2** shows all four matching records and explains complete filtered
exports. A September update does not establish a September impact start or
first publication.

</details>

<details>
<summary>Active maintenance: retain the source state and qualify its dates</summary>

![Actual Active maintenance communication with source dates and explicit impact uncertainty](images/report-03-active-date-context.png)

Callout **1** preserves the native **Active** state. **2** preserves the source
dates and their interpretation: this record's published mitigation precedes
the report reference, so an ongoing or future impact is **not established**.
The source state is not silently changed to Resolved, and no workload outage
is inferred.

</details>

<details>
<summary>Potential resource associations: source evidence, not outage proof</summary>

![Actual published resource association with opaque identifiers masked](images/report-04-potential-resource.png)

Callout **1** expands an actual returned association. Its resource type,
region and observation time remain visible; opaque resource/event IDs are
masked. **2** preserves the workload, support-case, ownership and newness
limits. There are two association records across the accepted full report,
not two measured workload outages.

</details>

<details>
<summary>Source ledger: received, in-scope and excluded are different counts</summary>

![Actual complete returned-page ledger with declared category exclusions and per-event resource receipts](images/report-05-source-ledger.png)

Callout **1** keeps the completeness qualification visible. **2** shows the
actual feed receipt: **29 received, 15 in scope, 14 other-category exclusions**.
The per-event resource reads below retain their individual complete or
successful-empty outcomes. Zero incomplete sources is not a complete-history
or healthy-workload claim.

</details>

<details>
<summary>Mobile: retain UTC context and coverage</summary>

![Actual narrow-screen report with CLIENTE branding and dated UTC context](images/report-06-mobile.png)

Callouts **1-2** preserve the dated LIVE snapshot, requested interval,
observed reads, retained lower bound and uncertainty on a 430-pixel viewport.
The mobile check also selected an event, moved focus to its detail, and
confirmed no page-wide horizontal overflow.

</details>

The accepted HTML's **Full source JSON** download matched the original native
JSON bytes exactly. Full/filtered JSON and CSV checks preserved every selected
record/field; browser CSV quoting can differ from the standalone CSV while
parsed cells remain equal. The requested-updates print check included all
four matching rows and hid interactive controls. The report made **no HTTP
requests** during these offline interactions.

Some ordinary `details_json` CSV cells exceed Python's default 131,072-byte
parser field bound. A local verifier should explicitly set
`csv.field_size_limit(4_800_000)` before reading these complete files. This is
a verifier setting, not evidence of artifact/source truncation and not a
reason to shorten or discard details.

## 6. Configure and verify the monthly task

Do this **after the normal-chat/four-download gate**, only in the customer's
approved agent. This is a reporting schedule, not an incident/alert workflow.

1. Open **Automation** and search for the exact name
   **`Monthly Service Health events review`**. Inspect any match's owner,
   responder, prompt and UTC schedule. Reuse a matching customer-owned task;
   do not duplicate it, edit an unrelated task or operate the historical lab
   task shown below. A name match alone is not ownership/configuration proof.
2. If no matching owned task exists, select the **`service-health-live`**
   node in **Agent Canvas**, then its **+ > Trigger > Add scheduled task**.
   **Response custom agent** should already be `service-health-live`; verify
   it explicitly.
3. Set **Task name** to the exact name above. Paste the **entire Task details
   prompt** from [monthly-task-prompt.md](monthly-task-prompt.md), not just its
   opening lines. It calls `operation="report", period="previous_month"`
   exactly once with every other parameter at its default.
4. Set the schedule to **day 1, 10:00 UTC**, equivalent to **`0 10 1 * *`**.
   Check the displayed time-zone label. The lab picture genuinely says
   **Time of day (UTC)**; other portal versions use the **browser's zone**.
   If the picker is not explicitly UTC, choose **Frequency > Custom cron**
   and enter `0 10 1 * *` in **Cron expression (UTC)**. Do not enter 10:00
   local and assume UTC. Stored UTC is fixed; local display time can shift
   with daylight saving.
5. Set **Agent autonomy level > Autonomous** and **Message grouping for
   updates > New chat thread for each run**. Choose the customer's approved
   **Start on** date and any run limit/end date; do not copy the lab's dates.
   Review the customer-approved model tier/usage policy without changing
   global defaults. The one-tool/code boundary, not the autonomy label,
   restricts actions to reads.
6. Select **Create task**, reopen it and confirm name, responder, complete
   prompt, grouping, autonomy, **On/Active** status and the next execution
   converted to UTC. For a reused matching task, inspect it without saving
   unnecessary changes.
7. Only with separate customer authorization for a manual acceptance, select
   just this task's checkbox in **Automation > Run now**
   (some detail views say **Run task now**). Open its history **Thread name**
   link, or find the matching thread in **Chats**. Verify one exact report
   call and all four downloads as in steps 4-5. Do not run it again merely to
   obtain a history badge or screenshot.

A **Success** row can mean work was handed to a thread, not that the tool
finished or files downloaded. If the history says **No thread found**, preserve
the limitation and inspect the actual matching thread if available; do not
guess a thread ID or automatically launch another report. Follow-up questions
are separate explicit chats, not hidden queries inside the scheduled run.

**Checkpoint:** the saved customer-owned task has the correct responder,
one-call prompt and next **UTC** slot. Record a separately authorized manual
run's actual thread/result/four downloads if performed. A future timer-fired
execution needs its own later receipt; manual acceptance does not prove it.

### Historical lab schedule and manual acceptance

In the saved UI this equivalent schedule is displayed as **Monthly**, **day 1**,
**10:00**, with the time control explicitly labeled **UTC**. It replaces the
earlier proposed 09:00 example; the actual task is Active and its recorded next
execution is **2026-11-01T10:00:00Z**.

![Actual saved monthly task configuration showing day one at ten UTC](images/setup-06-monthly-configuration.png)

Callout **1** shows the one-report task prompt. **2** shows the actual monthly
day/time controls, equivalent to the configured cron above; it is not a
fabricated raw-cron form. **3** shows Autonomous. The dialog was opened only
for readback and closed with **Cancel**; neither Save nor Run was clicked
during documentation capture. This is the saved lab configuration, not a
customer task-creation screenshot.

The authorized operator started **one** manual execution at
**2026-10-14T22:21:05.2073321Z**. Its actual report reference is
**2026-10-14T22:21:09Z**, distinct from the normal run's 22:14:58Z reference.
The task execution count was **1**, and all four resulting native downloads
were independently verified as HTTP 200 with exact file hashes.

![Actual monthly task history with its single manual execution](images/setup-05-monthly-history.png)

The history readback showed a Success row at 22:21. One readback temporarily
displayed **No thread found**; task success or that missing link was not used
as completion proof. The actual execution thread and its files were checked
separately.

![Actual completed monthly execution thread and four file links](images/setup-07-monthly-files.png)

Callouts **1-3** show the real monthly execution's HTML, complete JSON and
ordinary CSV delivery. The thread's initial **Active** badge and the scheduler
metadata's early `completed=false` value were not treated as report-completion
receipts. The actual final tool result, one report generation and four
verified downloads establish this manual gate; future scheduled executions
have not yet been observed.

## 7. Optional maintainer checks, private replay and release gates

**Not a prerequisite for a customer pasting the complete tool.** These commands
are for maintainers changing generic source or explicitly replaying approved
offline evidence. They do not install or validate a customer's SRE deployment.
Develop generic changes in `engine.py` / `report_template.html`, then rebuild
with `python "05-service-health-events-review\build_tool.py"`. Do not rebuild
over your private configuration.

From the repository root, check the generated file and run offline tests:

```powershell
python "05-service-health-events-review\build_tool.py" --check
python -m unittest discover -s "05-service-health-events-review\tests" -v
```

The browser test is opt-in. Windows uses installed Edge by default; elsewhere
install Playwright's local Chromium if missing. The UI run reads only local
SIMULATED HTML:

```powershell
$env:CASE05_BROWSER_TESTS = "1"
$env:CASE05_UI_ARTIFACTS = "<PRIVATE_SCRATCH_DIRECTORY>"
python -m unittest discover -s "05-service-health-events-review\tests" -v
```

An explicitly supplied complete recorded default snapshot can opt into the
private 365-day byte/export regression; it is not auto-discovered, bundled or
collected by the test:

```powershell
$env:CASE05_BROWSER_TESTS = "1"
$env:CASE05_PRIVATE_SNAPSHOT = "<PRIVATE_COMPLETE_RECORDED_SNAPSHOT_JSON>"
python -m unittest discover -s "05-service-health-events-review\tests" -v
```

Tests cover source shapes, declared category exclusions, provider-relative
IDs, pagination/scope attacks, partial pages, exact UTC boundaries, missing/
empty/denied outcomes, source-date versus Active semantics, typed schema/main
parity, complete JSON/CSV rows/fields, integer precision, byte limits, branding,
atomic writes/cleanup, native aliases, safe DOM rendering and desktop/mobile
filters/print/exports. A physical symlink-creation test can skip on Windows
without symlink privilege; mocked symlink/junction guards still run.

The recorded authoring run completed **52 tests: 51 passed, one physical Windows
symlink-creation check skipped for missing host privilege** (the current test
suite includes **53 tests** with the documentation link/anchor and logo-generator
one-liner check added). Desktop/mobile
checks include a late-register-row selection returning focus and visible
context to its dossier. The generated standalone build and schema/signature
parity were checked. Synthetic fixture renders remain SIMULATED; the opt-in
full-model check re-renders already recorded private evidence without changing
its source model or treating it as a fresh authenticated collection. Neither
path asserts deployment or a new live source/native-download receipt.

The hydration regression executes both configured engine and canonical source
as `__main__` with credential/network/artifact operations forbidden and stdout
captured. Loading must be inert; one subsequent explicit report invocation
must collect and write exactly once. The former CLI autorun behavior was
reproduced offline with that forbidden-operation test before removal.

The full 365-day default-model render originally exceeded the plain HTML
guard while its JSON and CSVs fitted. That failure is retained in private
rollout evidence; the earlier 90-day replay was not acceptance of the default
window. The lossless reference-based renderer was then checked against the
complete recorded default model and a valid maximum-size test logo, with
unchanged JSON/CSV bytes and all selected records/receipt fields. These are
offline rendering/export checks, not a new authenticated runtime execution
or native-download receipt.

For a meaningful manually inspectable **SIMULATED** report, use an existing
private scratch directory; the helper never invokes NativeReader:

```powershell
python "05-service-health-events-review\tests\offline_demo.py" --output "<PRIVATE_SCRATCH_DIRECTORY>"
```

Private source receipts are never bundled or auto-discovered. An authorized
operator can explicitly opt into the replay/budget helper:

```powershell
python "05-service-health-events-review\tests\private_replay.py" --input "<PRIVATE_SOURCE_RECEIPTS_JSON>" --output "<PRIVATE_SCRATCH_DIRECTORY>"
```

It asserts all in-scope raw-record/field parity, checks all plain-file budgets
including a validated 100,000-byte test-logo overhead, and marks output
**PRIVATE_REPLAY**, not fresh live validation. Only recorded per-event resource
receipts are reused; missing ones stay Not collected. It authenticates nobody
and calls no source. Keep all inputs/outputs private and outside Git.

| Gate | Evidence required |
|---|---|
| DRAFT | Unknown access/source/runtime gates disclosed; no working-live claim |
| OFFLINE_VALIDATED | Actual mocked execution, asserted artifacts, meaningful UI/byte checks |
| LIVE_VALIDATED | Fresh approved UAMI collection with disclosed retention/coverage and actual four native downloads; no invented events |
| PUBLISHED | Privacy review, authorized private target and remote publication receipt; local commit is not publication |

The normal and manual-monthly lab gates below were accepted, and their generic
package/masked captures were published to the private repository. A customer
must establish their own approved scope, saved objects and actual downloads.
The source remains customer-neutral and frozen; this guide does not perform
deployment, role assignment, a collection or a task execution.

## Dated lab acceptance and evidence limits

| Evidence | Accepted observation |
|---|---|
| Generic source | Render-corrected definitions-only tool from commit `aa4d4a66e169c03b2bfe747339634e276525c7ef`; deployed private branding/configuration was separately read back |
| Canonical generic Python | LF SHA-256 `d65678b0c03f09088b2e3fc704e0d269d2d95088618219fde4f60afac3d6c7a7`; private configuration changes have a different hash |
| Normal execution | One collection, **2026-10-14T22:14:58Z**; `report/auto`, all other defaults; no stdout from source hydration |
| Manual monthly execution | One collection, **2026-10-14T22:21:09Z**; previous-month request, execution count **1** |
| Requested last-update interval | Both runs: **2026-09-01T00:00:00Z <= lastUpdateTime < 2026-10-01T00:00:00Z** |
| Retained lower bound | Normal: **2025-10-14T22:14:58Z**; monthly: **2025-10-14T22:21:09Z**; neither was narrowed |
| Feed and business scope | Each run: **29 received, 15 retained, 14 declared other-category exclusions** |
| In-scope records | **13 ServiceIssue + 2 PlannedMaintenance**, **15 distinct events**, **2 impacted-resource records** |
| Separate temporal views | **4 requested updates**, **1 Active observed**, **0 future communicated maintenance**; views overlap |
| Source receipts | **0 incomplete sources**, returned pages/per-event reads completed; historical completeness remains **not proven** |
| Native files | Both runs: HTML **1,641,201 bytes**, complete JSON **1,010,342**, events CSV **1,009,927**, impacted-resources CSV **4,561**; all four downloads HTTP **200** |
| Export fidelity | Native ordinary CSV bytes reconciled to the complete model; accepted HTML full-JSON bytes and all selected JSON/CSV fields reconciled without recollection |
| Saved runtime boundary | One new tool, matching skill and restricted specialist; **11 typed parameters**, numeric fields `int`, **one selected tool** and **one matching skill**, no global extras |
| Existing assets | The original **7 tools / 10 skills / 13 agents / 10 tasks** remained unchanged when cases05/06 were added; these are historical baseline counts, not required customer totals |
| Recurrence | Active monthly task, **day 1, 10:00 UTC**, equivalent cron **`0 10 1 * *`**; next recorded time **2026-11-01T10:00:00Z** |
| Not established | Complete historical coverage, historical daily status, first publication/newness, actual workload outage, support case, root cause, SLA, savings or future scheduled-run completion |

The early oversized default HTML and the diagnostic-only model were rejected
as normal-report acceptance. Their private failure history was retained.
The accepted screenshots above use the later actual normal bundle; they do
not relabel a replay, diagnostic render or test-logo image as live evidence.

There are **six actual report captures and seven actual saved-setup/chat/task
captures**. Only the final masked PNGs and English captions are committed.
Report customer-name/logo pixels are replaced by **CLIENTE**; opaque
identifiers, profiles and private configuration are masked or outside the
crop. Facts, source text, dates, counts and uncertainty remain intact. Sparse
red numbered boxes are annotations, not original UI controls. Raw captures,
privacy-mask rectangles, annotation rectangles, credentials, native URLs,
private code/configuration and full source/export receipts remain outside Git.
No synthetic or recreated setup screen is presented as actual evidence.

## Troubleshooting and boundaries

| Symptom | Check | Safe action |
|---|---|---|
| `configuration_required` | Placeholder GUIDs, monitored subscription versus SRE-host subscription, Client ID versus Principal ID | Correct only the fixed private block and read it back; never add scope/token inputs or change generic Git placeholders |
| `authentication_failed` / `identity_mismatch` | UAMI is available to this SRE runtime; configured tenant/client/ARM audience agree | Customer SRE administrator checks the identity association/configuration; no CLI/human-token/system-identity fallback |
| `invalid_company_logo` / `invalid_branding` | Complete PNG/JPEG data URI, MIME, real dimensions/bytes and plain name/alt text | Correct the authorized private raster or deliberately leave logo `""`; do not change the palette or fetch a remote image |
| `dependency_missing` | `azure-identity`; Pillow for a nonempty logo; compatible manifest versions | Runtime administrator checks preinstalled packages or the supported dependency field; no in-tool package installation |
| Paste/syntax/type/default error or `invalid_combination` | Complete standalone source, no Markdown fences/ellipsis; 11 rows; `int` limit/offset; report filters at defaults | Restore the complete approved file, reapply only fixed private config and match the table/schema; do not regenerate code with AI |
| Two collections / extra stdout | Appended `print(main())`, `main()` call or `if __name__ == "__main__"` guard | Restore definition-only code; loading is inert and the platform makes the one explicit call |
| Portal 403, expired sign-in or Conditional Access prompt | Human SRE roles and approved interactive session, not merely visible Builder buttons | Customer follows normal sign-in/access policy with their administrator; do not bypass authentication/security warnings or auto-assign Admin |
| ARM receipt 401/403 | Which source failed, UAMI identity, approved scope and read assignments | Preserve denied coverage and have the authorized access administrator investigate; do not prescribe Owner/Contributor or Graph grants |
| HTTP 400 `InvalidODataQueryOptions` | Copied code still uses the native no-filter feed | Restore the canonical source's local category selection; this is a query problem, not a permission denial |
| 404 / malformed list / timeout / unfinished continuation | Exact source receipt, source API version, retained prior pages and bounds | Disclose unavailable/partial evidence; preserve accepted pages, never replace them with empty success |
| Only excluded categories / zero eligible events | Received/in-scope/excluded counts and completed pagination | Deliver honest empty files/receipts; successful source access does not establish resilience |
| Active with old mitigation / Unknown dates | Original source state and date context in the dossier | Keep both observations; do not infer ongoing impact, first publication or newness |
| Empty tool/skill allowlist or wrong responder | Saved detail, **Tools - 1**, selected `service-health-live` skill and chat picker | Correct only the owned specialist's explicit selections; empty inherits broader access, not zero tools |
| `artifact_size_exceeded`, `collected_evidence_too_large` or `response_size_exceeded` | Exact complete-file/result guard and sanitized error | Stop and escalate a complete implementation fix to its maintainer; never shorten history, drop fields/records, split scope or substitute Storage/ZIP |
| `local_files_only` / missing native aliases | Actual returned cwd/paths, not a hardcoded thread route | Show actual paths and disclose native delivery is unaccepted; customer runtime administrator checks the supported ThreadFiles root |
| Four links missing / failed download / Task Success / No thread found | Actual final tool result, selected responder, execution thread and each file | Render existing returned links unchanged, check each download separately and retain failures; no invented URL/thread, hidden rerun or badge-only acceptance |

No workload telemetry, support cases, ticket writes, root-cause verification,
resource starts/stops, CPU exercises, cloud mutation, IAM or new infrastructure
is part of this case.

## Official references

- [Events - List by subscription ID](https://learn.microsoft.com/rest/api/resourcehealth/events/list-by-subscription-id)
- [Impacted resources - List by subscription and event](https://learn.microsoft.com/rest/api/resourcehealth/impacted-resources/list-by-subscription-id-and-event-id)
- [Service Health ARG samples](https://learn.microsoft.com/azure/service-health/resource-graph-samples) - comparison/reference only; this adapter does not issue arbitrary ARG queries
- [Service Health history and retention](https://learn.microsoft.com/azure/service-health/health-history-overview)
- [SRE user roles](https://learn.microsoft.com/azure/sre-agent/user-roles)
- [Agent identity and UAMI discovery](https://learn.microsoft.com/azure/sre-agent/agent-identity)
- [Resource Health ARM operations](https://learn.microsoft.com/azure/role-based-access-control/permissions/management-and-governance#microsoftresourcehealth)
- [Service Health access FAQ](https://learn.microsoft.com/azure/service-health/service-health-faq)
- [Azure role-assignment prerequisites](https://learn.microsoft.com/azure/role-based-access-control/role-assignments-portal)
- [Create a Python tool](https://learn.microsoft.com/azure/sre-agent/create-python-tool) and [runtime environment](https://learn.microsoft.com/azure/sre-agent/python-code-execution)
- [Create a skill](https://learn.microsoft.com/azure/sre-agent/create-skill) and [custom agent](https://learn.microsoft.com/azure/sre-agent/create-subagent)
- [Create automation and verify schedule time zones](https://learn.microsoft.com/azure/sre-agent/automate-workflows)
- [SRE scheduled tasks](https://learn.microsoft.com/azure/sre-agent/scheduled-tasks)
- [SRE run modes](https://learn.microsoft.com/azure/sre-agent/run-modes)

<!-- BILINGUAL_QA_PROMPT_PACK -->

---

## Copy-Ready Bilingual Q&A Prompt Pack (Castellano & English)

Select `/agent service-health-live` in **New chat** and use any of these prompts in **Spanish (Castellano)** or **English**:

### 1. Full Service Health Report (Previous UTC Month + Active Now + Planned Maintenance) / Informe Completo de Service Health (4 Archivos)
- **Castellano:**
  ```text
  @service-health-live Genera el informe completo de eventos de Azure Service Health (operation="report", period="previous_calendar_month", event_type="all", status="all") y entregame los 4 archivos descargables (HTML, JSON, CSV de eventos y CSV de recursos impactados).
  ```
- **English:**
  ```text
  @service-health-live Generate the complete Azure Service Health events report (operation="report", period="previous_calendar_month", event_type="all", status="all") and deliver all 4 downloadable files (HTML, JSON, events CSV, and impacted resources CSV).
  ```

### 2. Active Service Issues & Advisories Right Now / Incidentes y Avisos Activos Ahora Mismo
- **Castellano:**
  ```text
  @service-health-live Consulta en modo query los eventos con estado Active ahora mismo (operation="query", view="events", status="Active") e indicame su tracking ID, tipo de evento (ServiceIssue, PlannedMaintenance, HealthAdvisory, SecurityAdvisory), regiones y servicios afectados.
  ```
- **English:**
  ```text
  @service-health-live Query the events currently in Active status (operation="query", view="events", status="Active") and list their tracking ID, eventType (ServiceIssue, PlannedMaintenance, HealthAdvisory, SecurityAdvisory), impacted regions, and services.
  ```

### 3. Upcoming & Recent Planned Maintenance Windows / Ventanas de Mantenimiento Planificado
- **Castellano:**
  ```text
  @service-health-live Filtra únicamente los eventos de mantenimiento planificado (operation="query", view="events", event_type="PlannedMaintenance", period="last_90d") y resume las fechas de inicio/fin comunicadas por Microsoft y los servicios implicados.
  ```
- **English:**
  ```text
  @service-health-live Filter only Planned Maintenance communications (operation="query", view="events", event_type="PlannedMaintenance", period="last_90d") and summarize the communicated start/end windows and affected Azure services.
  ```

### 4. Impacted Subscription Resources Drill-Down / Recursos de la Suscripcion Afectados por Evento
- **Castellano:**
  ```text
  @service-health-live Consulta la vista de recursos impactados (operation="query", view="impacted_resources", period="last_90d") y explicame para que eventos Microsoft expone recursos concretos de la suscripcion frente a comunicados generales de servicio/region.
  ```
- **English:**
  ```text
  @service-health-live Query the impacted resources view (operation="query", view="impacted_resources", period="last_90d") and explain which events list specific subscription resource IDs versus regional/service-level communications.
  ```

### 5. Security & Health Advisories Review / Revision de Avisos de Seguridad y Retiradas (Health & Security Advisories)
- **Castellano:**
  ```text
  @service-health-live Muestra los eventos de tipo HealthAdvisory y SecurityAdvisory comunicados en los ultimos 90 dias y resume si requieren alguna accion preventiva por parte del equipo de plataforma.
  ```
- **English:**
  ```text
  @service-health-live Show all HealthAdvisory and SecurityAdvisory events communicated in the last 90 days and summarize whether any preventive action is required from the platform team.
  ```
