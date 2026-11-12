# Case 00 — SRE use-case builder

**Describe an operations idea in one sentence. Get back a working, tested Azure SRE Agent use case.**

`/agent sre-usecase-builder` turns *"I need a weekly report of orphaned managed disks"* into a Python tool whose code was
generated, linted, self-tested with the network blocked and checked against your real data. It also gives you
the Skill, Subagent and Scheduled task blocks to paste in Builder, the exact permissions the agent needs, and a setup guide.
It asks no questions unless it cannot know where the data lives.

| | |
|---|---|
| **Audience** | Microsoft and partner engineers, customer platform / SRE teams building their own SRE Agent scenarios |
| **Time to install** | 5 minutes with the deploy script, about 15 minutes by hand in Builder |
| **Time per new use case** | 2–4 minutes of chat plus 10 minutes of copy-paste in Builder |
| **Permissions it needs** | None of its own. It reads only what the agent managed identity can already read, so it can live-check the generated tool |
| **Status** | Deployed and run live end to end: builder → generated tool → generated subagent → report → scheduled task (evidence below) |

### Watch it: from one sentence to a scheduled use case

[![Tutorial video: the SRE use-case builder from one sentence to a scheduled use case](docs/video/sre-usecase-builder-tutorial-poster.jpg)](docs/video/sre-usecase-builder-tutorial.mp4)

*Click the image to play the video (MP4, 2:06, no voice-over: it opens on the finished report, every step is captioned on screen, and the camera zooms into each highlighted area so it reads well on a projector). It is also on the [use-case field guide](https://marioaguileraaa.github.io/sre-agent-use-cases/#tutorial).*

A real run on a lab Azure SRE Agent (names and identifiers replaced), sped up while the agent works. Steps 5 and 6 were
recorded again with kit 3.1, after updating the generated tool, to show the new report design and its PDF:

| Step | What you see |
|---|---|
| 1 | **Describe the idea.** New chat, `/agent sre-usecase-builder`, and one sentence: *"I need a weekly report of Azure resources that are missing the mandatory tags owner and environment, grouped by resource group and resource type, so each team can fix its own resources."* |
| 2 | **The builder works on its own.** No questions: recipe, environment, JSON spec, code generation, lint, self-test and a live read. About 2 minutes |
| 3 | **Review the answer.** Status `READY_LIVE_VERIFIED`, the permissions with exact `az` commands, and the 4 Builder blocks |
| 4 | **Create it in Builder.** Python tool (paste the code, Identity off, `mode=self_test` test, Create), then the skill and the subagent with their blocks |
| 5 | **Run it.** `/agent missing-mandatory-tags`: 464 resources in 34 resource groups missing tags, with the verdict, indicators, top findings and the report files (HTML, PDF, CSV, JSON) |
| 6 | **Open the report.** The interactive HTML report on live data: verdict, indicators, charts, a findings register you can search and filter, the data tables, and the same report as PDF |
| 7 | **Schedule it.** Automation > Scheduled task, with the cron from block 4 (`0 7 * * 1`, Mondays 07:00 UTC) |

---

## Contents

1. [Business value](#business-value)
2. [Why this design: lessons from the previous designer](#why-this-design-lessons-from-the-previous-designer)
3. [How it works](#how-it-works)
4. [Prerequisites](#prerequisites)
5. [Install — option A: deploy script (5 minutes)](#install--option-a-deploy-script-5-minutes)
6. [Install — option B: by hand in Builder, step by step](#install--option-b-by-hand-in-builder-step-by-step)
7. [Use it: create a new use case from chat](#use-it-create-a-new-use-case-from-chat)
8. [Deploy, run and schedule the generated use case](#deploy-run-and-schedule-the-generated-use-case)
9. [Report design: branded HTML and PDF](#report-design-branded-html-and-pdf)
10. [Permissions for the generated use cases](#permissions-for-the-generated-use-cases)
11. [What it can build](#what-it-can-build)
12. [Live evidence](#live-evidence)
13. [Troubleshooting and Builder gotchas](#troubleshooting-and-builder-gotchas)
14. [For maintainers: build and test the kit](#for-maintainers-build-and-test-the-kit)
15. [Files in this folder](#files-in-this-folder)

---

## Business value

| Without the builder | With the builder |
|---|---|
| Each new scenario is a small software project: discovering the API, writing Python, guessing column names, debugging in the Builder playground, and writing a skill and subagent prompts | One sentence in chat. The kit writes the code from a declarative spec, so each use case starts from the same tested engine |
| Code is often handed over untested, with placeholders that fail on the first run | The code is linted, self-tested and, when the identity allows it, run against live data **before** it reaches the user |
| Every report looks different, and there is no "what changed since last time" | Every generated report has the same polished, interactive design: verdict, KPIs with trend, findings by severity, charts, changes since the previous run, a searchable findings register, and downloadable HTML, **PDF**, CSV and JSON files. Name a company and the report carries its logo, colours and font, read from its website |
| Permissions are found by trial and error (`403` in production) | The exact `az` commands per data source come with the blocks, and the agent's existing roles are detected |
| Customers wait for an expert to build each scenario | Customer teams build their own scenarios safely: generated tools are **read-only by design** |

The result is less time from idea to a scheduled, trustworthy report, and a repeatable pattern that field teams
can show in a customer session and leave behind as a self-service capability.

---

## Why this design: lessons from the previous designer

The previous designer (`sre-scenario-designer`, now retired and replaced by this builder) was used by real customer teams. Their feedback was consistent: *"it keeps asking for
more parameters and we don't know how to continue."* Reviewing it against the live platform found 7 root causes:

| # | Previous designer | This builder |
|---|---|---|
| 1 | **Question-driven.** It interviewed the user, and any unknown value blocked delivery | Acts on the first message. It picks defaults, says which ones it chose, and turns unknown values into `<placeholders>` (status `READY_WITH_INPUTS`) instead of more questions. At most one message with 3 questions, and only when the data source itself is unknown |
| 2 | **Contradictory instructions** between the skill, the subagent and the blueprint | One short skill, one short subagent prompt and a single workflow table |
| 3 | **The LLM wrote the Python by hand.** The code was untested and had placeholders, so it broke on the first run | The LLM writes only a **JSON spec**. A fixed, tested engine generates the code, then lints it, self-tests it and live-checks it |
| 4 | **Closed catalog** of 6 hard-coded scenarios | 8 generic source types plus 6 recipes as templates. Any KQL, Resource Graph, Graph, ARM, Cost Management, ADX, SharePoint Excel/CSV or Blob file source works |
| 5 | **A 128 KB blueprint** returned to the model | Compact results, always under the platform's ~4,000-character tool-result limit, with paged `get` for long parts |
| 6 | **Tool results over 4 KB were silently truncated** by the platform, so the model invented the missing code | A budget and paging system (`get <name>/<part>/<page>`): nothing is ever cut |
| 7 | **The Builder Test playground did not detect `main()` parameters** in long files | `main()` sits at the top of every generated file; the build asserts it |

---

## How it works

```mermaid
flowchart LR
    U["User idea<br/>(one sentence, any language)"] --> A["Subagent<br/>sre-usecase-builder"]
    A -- "catalog / environment / brand" --> K["Python tool<br/>sre-usecase-builder-kit"]
    A -- "writes JSON spec" --> K
    K --> G["Generated tool<br/>run-&lt;name&gt;.py"]
    G --> L["lint"] --> S["self_test<br/>(network blocked)"] --> D["live discover<br/>(agent identity)"]
    D --> B["4 Builder blocks<br/>+ permissions + SETUP.md"]
    B --> U
```

1. **catalog**: the subagent reads the compact list of recipes, source types and spec fields, and picks the closest recipe.
2. **environment**: the kit discovers what the agent managed identity can see: subscriptions, Log Analytics workspaces (real `customerId`), storage accounts, and the Azure roles and Graph app roles already granted.
3. **brand** (only when the idea names a company or a website): the kit reads the public website once and returns the official logo (SVG when the site has one), the primary and accent colours and the closest font preset. The logo is cached and embedded by the kit; it never passes through the chat.
4. **spec**: the subagent writes a declarative JSON spec with sources, rules, KPIs, tables, charts, labels and schedule.
5. **scaffold**: the kit validates the spec, generates `run-<name>.py`, lints it, runs it in `self_test` mode with the network blocked, and then runs `discover` against live data when the identity can.
6. **get answer**: the kit returns the ready-to-paste answer: verification, permissions, values to fill, the 4 Builder blocks and file links, including the self-test report in HTML and PDF.

**The generated tool** is one Python file driven entirely by a `CONFIG = {...}` block:

`main(mode = report | discover | self_test, publish = no | yes, lookback_days = 0)`

| Mode | What it does |
|---|---|
| `self_test` | Synthetic data, no network. Proves the rules, KPIs, comparison, HTML and PDF |
| `discover` | Reads a few live rows per source and lists the real columns. Writes nothing |
| `report` | Live run that produces the HTML report, its PDF, CSV and JSON. `publish=yes` also uploads the report and its history snapshot to SharePoint or Blob for the next comparison |

To change a use case later, edit only `CONFIG` (queries, thresholds, rules, KPIs, tables, charts, brand, publishing). No other code changes are needed.

---

## Prerequisites

| Need | Detail |
|---|---|
| Azure SRE Agent | An existing agent and access to its portal |
| Your role on the SRE Agent resource | **SRE Agent Administrator**, or **SRE Agent Author** plus **SRE Agent Standard User** (Azure portal > the SRE Agent resource > Access control (IAM)) |
| Option A only | Python 3.9+, `pip install requests`, Azure CLI signed in (`az login`) |
| Agent managed identity | Nothing extra for the builder itself. For live checks, the generated use cases need read roles on their sources (see [Permissions](#permissions-for-the-generated-use-cases)) |

Find the agent identity: **SRE Agent portal > Settings > Azure settings > Managed Identity > Go to Identity**.
The Azure portal **Overview** page shows the **Client ID** and the **Object (principal) ID**.

---

## Install — option A: deploy script (5 minutes)

Download this folder (or clone the repo) and run:

```powershell
az login
pip install requests
python deploy-to-sre-agent.py --endpoint https://<your-agent>.azuresre.ai --subscription <subscription id of the agent>
```

The agent URL is the address in your browser when the SRE Agent portal is open, up to `.azuresre.ai`.

The script:

1. Creates or updates the Python tool `sre-usecase-builder-kit` (timeout 300 s), the skill `sre-usecase-builder`, and the subagent `sre-usecase-builder` with the skill and tool linked.
2. Runs the kit once in the agent sandbox (`operation=catalog`) and prints `status: OK`, `kit_version: 3.1.1` and the 6 recipes.

```text
OK  tools/sre-usecase-builder-kit  (202)
OK  skills/sre-usecase-builder  (202)
OK  agents/sre-usecase-builder  (202)
Sandbox smoke test: {'status': 'OK', 'kit_version': '3.1.1', 'recipes': ['vm-heartbeat-gaps', ...]}
Done. In the agent chat run:  /agent sre-usecase-builder  and describe your use case.
```

Use `--dry-run` to see what would be sent without changing anything. Running it again updates the three objects in place.

Then go to [Use it](#use-it-create-a-new-use-case-from-chat).

---

## Install — option B: by hand in Builder, step by step

Three objects, created in this order: **Python tool → Skill → Subagent**. Red numbered boxes show where to click.

### B1. Python tool `sre-usecase-builder-kit`

**Builder > Agent Canvas > Create (arrow ▾) > Tool > Python tool**

![Create > Tool > Python tool](docs/images/01-builder-create-python-tool.png)

On the **Code** tab:

| Field | Value |
|---|---|
| Tool name | `sre-usecase-builder-kit` |
| Description | Copy `TOOL_DESCRIPTION` from [`deploy-to-sre-agent.py`](deploy-to-sre-agent.py) (lines 28–35) |
| Timeout | `300` seconds |
| Code | Paste the whole [`sre-usecase-builder-kit.py`](sre-usecase-builder-kit.py). No edits needed |

![Code tab: name, description, timeout, code](docs/images/02-python-tool-code.png)

On the **Identity** tab, leave **Enable Azure Identity OFF**. The kit uses the agent managed identity that the sandbox already provides.

![Identity tab: leave OFF](docs/images/03-python-tool-identity-off.png)

**Create tool stays disabled until you run a test.** Open **Test playground**, set `operation` = `catalog`, and click **Test**:

![Test playground: operation=catalog, Test](docs/images/04-python-tool-test-playground.png)

Expected result: **Function test succeeded**, with `status: OK`, `kit_version: 3.1.1` (the capture below is from an earlier 3.0.0 run) and the recipe list:

![Function test succeeded](docs/images/04b-python-tool-test-result.png)

Then click **Create tool**:

![Create tool](docs/images/05-python-tool-create.png)

### B2. Skill `sre-usecase-builder`

**Builder > Agent Canvas > Create ▾ > Skill**

![Create > Skill](docs/images/06-builder-create-skill.png)

| Field | Value |
|---|---|
| Name | `sre-usecase-builder` |
| Description | First paragraph of the front matter in [`skills/sre-usecase-builder/SKILL.md`](skills/sre-usecase-builder/SKILL.md) (`description:`) |
| SKILL.md content | The whole [`SKILL.md`](skills/sre-usecase-builder/SKILL.md) |

![Skill form](docs/images/07-skill-form.png)

In **Choose tools**, select `sre-usecase-builder-kit`:

![Skill: choose tools](docs/images/08-skill-choose-tools.png)

Click **Create**:

![Skill: create](docs/images/09-skill-create.png)

### B3. Subagent `sre-usecase-builder`

**Builder > Agent Canvas > Create ▾ > Custom Agent**

![Create > Custom Agent](docs/images/10-builder-create-agent.png)

| Field | Value |
|---|---|
| Name | `sre-usecase-builder` |
| Instructions | The whole [`skills/subagent-instructions.md`](skills/subagent-instructions.md) |

![Agent name and instructions](docs/images/11-agent-name-instructions.png)

**Choose skills** → `sre-usecase-builder`:

![Agent: choose skills](docs/images/12-agent-choose-skills.png)

**Choose tools** → `sre-usecase-builder-kit`:

![Agent: choose tools](docs/images/13-agent-choose-tools.png)

Click **Create**:

![Agent: create](docs/images/14-agent-create.png)

> Selecting skills or tools on a custom agent **replaces** the global defaults for that agent. This is intended: the builder only needs its own skill and tool.

---

## Use it: create a new use case from chat

Open a **New chat**, type `/agent` and pick **sre-usecase-builder**:

![Type /agent](docs/images/15-chat-agent-command.png)

![Pick sre-usecase-builder](docs/images/16-chat-pick-subagent.png)

Describe the idea in one or two sentences, in any language. Mention the data if you know where it is (workspace,
SharePoint site, storage account); if you don't, the builder discovers it or leaves a placeholder.

> I need a weekly report of orphaned managed disks (not attached to any VM) across my subscriptions, with size and SKU, so we can clean up waste.

![Describe the idea](docs/images/17-chat-describe-idea.png)

To get a report in a customer's look, name the company or its website, for example *"… for Contoso (https://www.contoso.com), with its logo and colours"*.
The builder reads the logo, colours and font from the website (see [Report design](#report-design-branded-html-and-pdf)).

More ready-to-use prompts are in **[prompts.md](prompts.md)**.

The builder works on its own: catalog → recipe → environment → spec → scaffold → answer. It needed **no questions** in any of our test runs:

![Builder workflow in the thread](docs/images/18-builder-workflow.png)

The answer always has the same sections:

| Section | What you get |
|---|---|
| 1. Use case | What it reports, the defaults it chose (thresholds, schedule, names) and the design applied (brand, charts) |
| 2. Verification | `lint`, `self_test`, `live_discover`, `field_check` and the final **status** |
| 3. Permissions | Roles already granted and the exact `az` commands for the missing ones |
| 4. Values to fill | Only when something could not be discovered (for example a SharePoint folder) |
| 5. Builder blocks | Python tool, Skill, Subagent and Scheduled task, ready to paste |
| 6. Files | Links to download the tool `.py`, `BUILDER-BLOCKS.md`, `SETUP.md`, the spec and the self-test report (HTML and PDF) |

![Verification and permissions](docs/images/19-builder-verification.png)

![Builder blocks](docs/images/20-builder-blocks.png)

![Scheduled task block](docs/images/21-builder-blocks-task.png)

![Downloadable files](docs/images/22-builder-files.png)

### Status values

| Status | Meaning | Next step |
|---|---|---|
| `READY_LIVE_VERIFIED` | Lint, self-test and live read of every source OK | Paste the blocks |
| `READY` | Lint and self-test OK; live read not possible here (no identity in this context) | Paste the blocks, run `discover` in the Test playground |
| `READY_WITH_INPUTS` | Code ready; some `<placeholders>` must be filled (listed in *Values to fill*) | Fill the values in `CONFIG`, then test |
| `READY_LIVE_ISSUES` | Code ready; a live source failed (usually a missing role) | Grant the role in *Permissions*, wait 5–10 min, run `discover` |
| `INVALID` / `FAILED` | Spec or generation error | The builder fixes it automatically (up to 3 retries) |

Follow-up messages work in the same thread, for example *"change the threshold to 60 days"*, *"also publish to my
SharePoint site"* or *"explain the permissions"*. The builder regenerates and re-tests.

---

## Deploy, run and schedule the generated use case

The answer and the downloadable `<name>-SETUP.md` contain the exact steps. In short:

| Step | Where | What |
|---|---|---|
| 1 | Azure Cloud Shell | Run the `az role assignment create ...` commands from *Permissions* (skip those marked already granted) |
| 2 | **Builder > Agent Canvas > Create ▾ > Tool > Python tool** | Block 1: name, description, timeout, parameters, code. Identity tab OFF |
| 3 | Test playground of that tool | Test in order: `mode=self_test` → `mode=discover` → `mode=report, publish=no` → `publish=yes` (only if publishing). Then **Create tool** |
| 4 | **Create ▾ > Skill** | Block 2, with the new tool selected |
| 5 | **Create ▾ > Custom Agent** | Block 3, with the new skill and tool selected |
| 6 | Chat: `/agent <name>` | Run the report |
| 7 | **Automation > Create > Scheduled task** | Block 4: task name, response subagent, prompt, frequency |

A complete example of every generated file is in [`examples/orphaned-managed-disks/`](examples/orphaned-managed-disks/).

**Run the generated subagent.** In a new chat, type `/agent` and pick the generated subagent (`orphaned-managed-disks` in this example):

![Pick the generated subagent](docs/images/23-generated-agent-pick.png)

It runs the tool and answers with the verdict, KPIs, top findings and what changed:

![Generated subagent: live report](docs/images/24-generated-agent-run.png)

The downloads are attached in the thread: HTML report, PDF, one CSV per table, findings CSV and full JSON
(this capture is from a kit 3.0 run, before the PDF was added):

![Downloads](docs/images/25-generated-agent-downloads.png)

The report itself is described in [Report design](#report-design-branded-html-and-pdf).

**Schedule it.** Go to **Automation > Create > Scheduled task**. Use the task name, **Response subagent** and prompt from block 4.
Set **Frequency** to the generated cron (`0 7 * * 1` = Mondays 07:00 UTC) via **Custom cron**, or pick the equivalent Weekly option.
The time list is in **your local time zone**, so 08:00 CET is 07:00 UTC.

![Scheduled task](docs/images/26-scheduled-task.png)

When publishing is enabled (`publish=yes` in the prompt), each run stores a history snapshot. The next run compares
against it: new findings, resolved findings, and added, removed and changed rows, with KPI trend arrows.

---

## Report design: branded HTML and PDF

Field teams show these reports to customers, so they must look as good as a hand-made demo. That is why **the agent never
writes report code**. Every generated tool embeds the same tested design engine, so a scheduled run on a Monday morning
looks exactly like the demo did. The LLM only chooses *what* to show (charts, column titles, brand), in the spec.

**Default design** (no company named), on synthetic `self_test` data:
[open the HTML](examples/orphaned-managed-disks/selftest-report.html) · [open the PDF](examples/orphaned-managed-disks/selftest-report.pdf)

![Generated HTML report, default design (self-test data)](docs/images/27-generated-report-selftest.png)

**Branded design**, the same use case for a fictional company, Contoso (logo, colours and font preset):
[open the HTML](examples/orphaned-managed-disks/selftest-report-branded.html) · [open the PDF](examples/orphaned-managed-disks/selftest-report-branded.pdf)

![Generated HTML report with a customer brand](docs/images/28-generated-report-branded.png)

**The PDF** is the same HTML, printed by headless Chromium inside the agent sandbox, so both always match:

![PDF pages of the same report](docs/images/29-generated-report-pdf.png)

<img src="docs/images/30-generated-report-mobile.png" alt="The same report on a phone" width="260" align="right">

**What every report contains**

| Part | Detail |
|---|---|
| Top bar | Customer logo (or a wordmark), section links and a **Print / PDF** button |
| Hero | Title, purpose, the verdict (*Urgent action*, *Needs attention* or *No relevant issues*) and a severity bar |
| KPI cards | Each indicator with its change versus the previous run, coloured by whether up is good or bad |
| Findings by rule and changes | Bars per rule; new and resolved findings since the previous report |
| Charts | Bar charts declared in the spec: count, sum, average, distinct, or buckets such as *days to expiry* |
| Findings register | Search, filter by severity and rule, sort by any column, paging and CSV export |
| Data tables | Smart cells: dates, Azure resource IDs as portal links, GUIDs, status pills, *days left* in colour, numbers in the report language |
| Data changes and coverage | Added, removed and changed rows; every source with its status and row count, so a failed source is never shown as zero |

The report is fully responsive (phone, tablet, desktop) and is a single, self-contained file. It makes no external
requests, has a strict Content-Security-Policy (`default-src 'none'`), and embeds its fonts and logo, so it opens offline
from a Teams chat, an email or SharePoint. The PDF is A4, switches to landscape when a table has more than 6 columns,
and has page numbers. If Chromium is not available in a sandbox, the run still succeeds (`pdf: skipped`) and the
HTML **Print / PDF** button does the same.

**Spec fields that control the design** (all optional):

| Field | What it does |
|---|---|
| `brand` | `{name, website, logo_url, primary, accent, dark, font, hero, logo_on_dark}`. `font` is `plex` (default, technical), `nunito` (rounded) or `fira` (humanist). `hero` is `auto`, `brand`, `dark` or `light` |
| `charts` | `[{title, dataset, by, agg, field, where, buckets, limit}]`, for example `{"title": "Capacity by resource group", "dataset": "disks", "by": "resourceGroup", "agg": "sum", "field": "SizeGB"}` |
| `labels` | Column titles: `{"SizeGB": "Size (GB)", "displayName": "Application"}` |
| `pdf` | `auto` (default) or `off` |

**Brand from a website.** With `operation=brand` (the builder calls it when the idea names a company or a URL), the kit
reads the public home page and its stylesheets once. It keeps the official logo (SVG when available, otherwise PNG), the
colours of the logo and the site, and the closest font preset. Text on brand colours is kept at WCAG AA contrast (4.5:1),
darkening a colour when needed. SVG logos are sanitised (no scripts, event handlers or external references). Discovery
only calls public HTTPS addresses, with a timeout and a size limit. If a site cannot be read, the builder says so and uses
the default design; you can always give the colours or a `logo_url` yourself.

Fonts: three subsets of SIL Open Font License fonts are embedded: *Report Sans* (IBM Plex Sans, renamed because "Plex"
is a Reserved Font Name), Nunito Sans and Fira Sans. The license texts are in [`src/fonts-OFL.txt`](src/fonts-OFL.txt).

---

## Permissions for the generated use cases

The generated tool authenticates with the **agent managed identity** (`AZURE_CLIENT_ID` in the sandbox). It never uses user
credentials. The builder detects roles already granted and only lists the missing ones.

| Source type | Role or permission on the agent managed identity |
|---|---|
| `log_analytics` | **Log Analytics Reader** on the workspace |
| `resource_graph`, `arm` | **Reader** on the subscription or management group |
| `cost_management` | **Cost Management Reader** on the subscription |
| `graph` | Microsoft Graph **application** role for the path, for example `Application.Read.All`, `User.Read.All`, `AuditLog.Read.All` + `Directory.Read.All` |
| `adx` | **Viewer** on the ADX database |
| `sharepoint_file` | Graph `Sites.Selected` plus a **read** grant on that one site |
| `blob_file` | **Storage Blob Data Reader** on the storage account or container |
| Publish to SharePoint | `Sites.Selected` plus a **write** grant on that one site |
| Publish to Blob | **Storage Blob Data Contributor** on the container |

Azure role assignments take 5–10 minutes to apply. Microsoft Graph app roles can take up to 30 minutes.
Graph app roles need a tenant admin (Privileged Role Administrator or Global Administrator) to grant them once.
The generated SETUP.md contains the exact commands.

---

## What it can build

**Source types** (any number per use case, combined in one report):

| Type | Reads |
|---|---|
| `log_analytics` | Any KQL on a Log Analytics workspace (Heartbeat, Perf, AzureDiagnostics, custom tables...) |
| `resource_graph` | Any Azure Resource Graph query across subscriptions |
| `arm` | Any ARM REST `GET` (Advisor, Service Health, Backup, Defender...) |
| `cost_management` | Cost Management query API (cost by resource group, service, tag...) |
| `graph` | Microsoft Graph `GET` with paging (apps, users, sign-ins, sites...) |
| `adx` | Azure Data Explorer KQL |
| `sharepoint_file` | Latest Excel or CSV in a SharePoint folder, read in memory |
| `blob_file` | Latest Excel or CSV in a Blob container |

**Recipes** (starting templates, never limits):

| Recipe | Example idea |
|---|---|
| `vm-heartbeat-gaps` | "Which VMs or Arc servers stopped sending heartbeat this week?" |
| `entra-app-secrets-expiry` | "Warn me about app secrets and certificates that expire in the next 30 days" |
| `advisor-high-impact` | "Monthly list of high-impact Advisor recommendations by subscription" |
| `sharepoint-excel-register` | "Read our server register Excel in SharePoint and flag rows without owner or past end of support" |
| `cost-by-resource-group` | "Weekly cost by resource group with the biggest increases" |
| `activity-deletes` | "Who deleted resources in the last 7 days?" |

**Rules and KPIs** are declarative: `eq`, `ne`, `gt/gte/lt/lte`, `in/not_in`, `contains`, `empty/not_empty`,
`expired`, `expires_within_days`, `older_than_days`, `newer_than_days`, combined with `all`, `any` and `not`.
KPIs are `count`, `sum`, `avg`, `min`, `max` or `distinct`, with a `where` filter and `good: up|down` for trend colour.

**By design, generated tools are read-only.** They read data and publish their own report. The builder refuses to generate
tools that delete, restart, change configuration or grant permissions.

---

## Live evidence

Verified on a lab Azure SRE Agent (identifiers removed):

| Step | Result |
|---|---|
| Install with `deploy-to-sre-agent.py` | Tool, skill and subagent created (`202`); sandbox smoke test `OK`, kit 3.1.1 |
| Builder test, idea: orphaned managed disks | **0 questions**. `READY_LIVE_VERIFIED`: lint PASS · self_test SIMULATED OK, 4/4 rules fired · live_discover OK (4 rows, 14 columns) · field_check OK |
| 4 different ideas, in Spanish and English | All 4 Builder blocks delivered in every thread, **0 questions**: Entra app secrets expiry (`READY_LIVE_VERIFIED`) · orphaned disks (`READY_LIVE_VERIFIED`) · VMs stopped but not deallocated (`READY_LIVE_VERIFIED`) · certificate inventory Excel in SharePoint, site not given (`READY_WITH_INPUTS`, placeholders listed instead of questions) |
| Generated use case deployed | Tool, skill and subagent created from the generated blocks |
| Generated subagent run | **4 orphaned disks, 196 GB, 0 Premium, 4 unattached 30+ days**, with verdict, KPIs, top findings and 4 downloads |
| Scheduled task | Weekly, Monday, cron `0 7 * * 1` UTC |
| Report design (kit 3.1), idea naming a company and its website, in Spanish | `brand` found the official SVG logo and the primary and accent colours on the public site. Spec with the brand, 3 charts and Spanish column titles. `READY_LIVE_VERIFIED`; self-test HTML and PDF written in the agent sandbox |
| Report design, idea with no company (weekly Advisor review, in Spanish) | Default design, 3 charts. `READY_LIVE_VERIFIED`, 3/3 rules fired, HTML and PDF |
| Generated branded tool (235 KB with logo and fonts), `mode=report` on live data in the agent sandbox | `status: OK`, `pdf: OK`, 5 servers read, 1 second |
| `operation=brand` on two public company websites from the agent sandbox | Both `OK`: SVG logo on one, PNG on the other, primary and accent colours, redirects validated hop by hop |
| Kit test suites | `tests/test_kit.py` and `tests/test_report_mocked.py`: **0 failures** |

---

## Troubleshooting and Builder gotchas

| Symptom | Cause and fix |
|---|---|
| **Create tool** is greyed out | Builder requires a test first. Open **Test playground** and click **Test** (`operation=catalog` for the kit, `mode=self_test` for a generated tool) |
| The Test playground shows no parameters | `main()` must be near the top of the file. The kit and every generated tool already do this; do not move code above it |
| `401` / `403` / `FORBIDDEN` in `discover` | A missing role on the agent managed identity. Run the command from *Permissions*, wait 5–10 minutes (Graph: up to 30) |
| The builder answer looks cut | It never is: long parts are paged and the subagent reads every page. If you edited the instructions, keep the line about `get` and `next` |
| Builder asks for things | Tell it *"use defaults and placeholders"*. By design it asks at most one message, and only about the data location |
| `READY` instead of `READY_LIVE_VERIFIED` | The live check had no identity or no access. Paste the blocks and run `mode=discover` in the Test playground |
| The time in the scheduled task is wrong | The Daily/Weekly time list uses your local time zone; the generated cron is UTC. Use **Custom cron** to be exact |
| Enable Azure Identity | Leave it **OFF** for the kit and generated tools. They use the sandbox agent identity |
| A generated subagent uses other tools | Selecting tools and skills on a custom agent overrides the global defaults; select only the generated ones |
| The report has no PDF (`pdf: skipped: ...`) | Headless Chromium was not available in that sandbox. The run still succeeds; open the HTML and use **Print / PDF** |
| Wrong logo or colours | Say it in the same thread: *"use primary #0E5A5A and accent #FF7A59"* or *"use the logo at https://.../logo.svg"*. The builder regenerates and re-tests |
| You want no brand | Say *"use the default design"* |
| The tool code is large (150–250 KB) | Normal: the fonts and the logo are embedded so the report works offline. Paste the whole file; do not remove the constants at the end |

---

## For maintainers: build and test the kit

The kit is a single file built from modules:

```powershell
python src\build_kit.py            # writes sre-usecase-builder-kit.py and prints size + sha256
python tests\test_kit.py           # catalog, spec validation, scaffold, lint, self_test, paging, budget, report design
python tests\test_report_mocked.py # every source type with mocked HTTP, report, PDF, publish, comparison
```

| Module | Content |
|---|---|
| `src/kit_1_catalog.py` | Source types, operators, Graph roles and recipes |
| `src/kit_2_build.py` | Spec validation with fix hints (including brand, charts, labels and pdf), and code generation |
| `src/kit_3_blocks.py` | The 4 Builder blocks and the permission plan by source type |
| `src/kit_4_ops.py` | Operations (catalog, environment, probe, scaffold, get, lint, brand), budget and paging, SETUP and BUILDER-BLOCKS templates |
| `src/kit_5_brand.py` | Brand discovery from a public website: logo (SVG sanitiser, trimming, PNG fallback), palette, font preset, cache |
| `src/kit_6_assets.py` | Embedded font presets, generated by `src/make_assets.py` (license texts in `src/fonts-OFL.txt`) |
| `src/usecase_tool_template.py` | The engine every generated tool is built from: sources, rules, KPIs, comparison, the HTML design engine and PDF, CSV and JSON, publishing, self-test |

Rules for contributions: keep every tool result under 3,800 characters (use `get` paging), keep `main()` at the top, keep generated tools read-only,
and change the report look only in `usecase_tool_template.py` (the agent must never write report code).

---

## Files in this folder

| Path | Purpose |
|---|---|
| [`sre-usecase-builder-kit.py`](sre-usecase-builder-kit.py) | **The Python tool** to paste in Builder (built artifact) |
| [`skills/sre-usecase-builder/SKILL.md`](skills/sre-usecase-builder/SKILL.md) | **The skill** |
| [`skills/subagent-instructions.md`](skills/subagent-instructions.md) | **The subagent instructions** |
| [`deploy-to-sre-agent.py`](deploy-to-sre-agent.py) | Installs the three objects with one command and smoke-tests them |
| [`prompts.md`](prompts.md) | Ready-to-use prompts in English and Spanish |
| [`examples/orphaned-managed-disks/`](examples/orphaned-managed-disks/) | Full output for one idea: spec, generated tool, Builder blocks, setup guide, self-test report in HTML and PDF (default and branded design) |
| `src/`, `tests/` | Kit source and tests |
| `docs/images/` | Screenshots used in this guide |
