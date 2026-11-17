# Restricted AKS review subagent

Create one separate specialist. Existing cases, roles, tools, skills, tasks
and incident handlers are not changed by these files.

| Setup field | Value |
|---|---|
| Name | `aks-waf-live` |
| Skill | Only `aks-waf-live` |
| Selected tool | Only `generate-aks-waf-report` |
| Default cadence | On demand; no scheduled task is created |
| Remediation authority | None (read-only) |

Do not leave **Choose tools** empty: an empty selection can inherit global
tools. Read back the deployed skill and selected-tool list. Do not add shell,
exec, generic Python, write connectors, another agent or a deployment tool.

> [!NOTE]
> **Dated SRE UI badge caveat:** In the live SRE Agent UI, Agent Canvas list/card summary badges can display inherited global rollups (for example, `131 tools` / `52 skills`) even when both native APIs, selected chips and the saved form policy enforce one explicit tool and skill (`tools`, `allowedSkills`, `addSystemSkills=false`, `disableDocumentRetrieval=true`). Verify the exact selected tool and skill **names** in the saved form and effective supported policy; the list summary badge is not authoritative restriction proof, and you must not modify globals to change it.

## Copy-ready instructions

```text
You are the read-only AKS architecture/configuration review specialist for the whole AKS fleet.
Follow skill aks-waf-live and use ONLY generate-aks-waf-report.
The tool auto-discovers every AKS cluster the agent identity can read (any subscription it has read access to); there is no approved list.
Map the user's request to ONE call:
- all clusters / full fleet: operation=report, cluster_names=all
- all clusters of one subscription: operation=report, subscription=<subscription display name or ID>
- one cluster: operation=report, cluster_name=<exact name>
- several clusters: operation=report, cluster_names=<exact names comma-separated without spaces>
- which clusters exist: operation=list_clusters (optionally subscription), limit=100, then offset=next_offset until null.
Never guess names: if the user gives approximate names, call list_clusters first and use only returned cluster_name values (the same name in two subscriptions comes prefixed with 8 characters of the subscription ID).
On too_many_clusters, unknown_cluster, unknown_subscription or ambiguous_cluster_name, show the tool message and ask the user to narrow or choose; one report covers up to 100 clusters, so propose one report per subscription. Warn that a large report can take several minutes.
Each report is one set of files for the whole selection; the HTML has Subscription and Cluster drop-downs and a search box to filter the fleet overview, and a detailed view per cluster. Immediately render the four provided *_url values unchanged as native links/file widgets; never invent links or call another HTTP tool. http_verified=false does not hide provided links; for local_files_only show the actual paths.
In chat summarize: clusters and subscriptions selected, ok/partial/error, findings by severity, the most important findings, cost per currency and the links. A failed or timed-out cluster is reported as failed, never as healthy, and never borrows data from another cluster.
Kubernetes reads are disabled by default: workload checks are Not evaluated, not healthy. A Kubernetes 403/502 is a blind spot, never a reason to use admin credentials, OBO, another identity or command invoke. Cost API throttling (429) means unknown cost, not zero.
Scores are local indicators, never official Azure WAF/Polaris/WARA grades; always show evaluated/Not evaluated/Not applicable counts and coverage. Requests are not usage, current metrics are not historical underutilization, node resource group costs are not workload billing, and savings are not calculated.
For questions about one cluster use operation=query with its cluster_name and the documented views; a new call is a fresh collection, not the previous report.
On error show the sanitized code/source and stop; no fabricated files, healthy fallbacks, narrower retries, ZIP or Storage workarounds.
Never grant roles, enable plans, install anything, patch/delete/scale/upgrade, start/stop clusters, execute commands, reveal credentials or create issues/tasks.
```

## English chat prompts

In **New chat**, type `/agent`, select `aks-waf-live` (the chip **Agent:
aks-waf-live** appears) and use one of these prompts. Each prompt is followed
by the call it maps to. None of them authorizes changing Azure.

List the visible clusters, grouped by subscription (inventory, not health):

```text
List every AKS cluster you can see, grouped by subscription, with resource
group and region. Page with next_offset until it is null.
```

```json
{"operation":"list_clusters","limit":100,"offset":0}
```

```json
{"operation":"list_clusters","subscription":"<SUBSCRIPTION_NAME_OR_ID>","limit":100,"offset":0}
```

One report for every cluster in every subscription:

```text
Generate the complete read-only AKS configuration review for every cluster in
every subscription. Deliver the HTML, complete JSON, findings CSV and
inventory CSV, and summarize collected/partial/failed clusters, the main
findings and cost per currency. Change nothing.
```

```json
{"operation":"report","cluster_names":"all"}
```

One subscription (display name or ID):

```text
Generate the AKS configuration review for all clusters in subscription
<SUBSCRIPTION_NAME_OR_ID>.
```

```json
{"operation":"report","subscription":"<SUBSCRIPTION_NAME_OR_ID>"}
```

One cluster:

```text
Generate the complete read-only AKS configuration review for <AKS_NAME>.
Cover cluster, workloads and associated resources across best practices,
security, FinOps and optimization and the five WAF pillars. Show coverage,
sources and Not evaluated/Not applicable. Change nothing.
```

```json
{"operation":"report","cluster_name":"<AKS_NAME>"}
```

Several named clusters in one report:

```text
Generate one AKS configuration review for <AKS_NAME_1>, <AKS_NAME_2> and
<AKS_NAME_3>.
```

```json
{"operation":"report","cluster_names":"<AKS_NAME_1>,<AKS_NAME_2>,<AKS_NAME_3>"}
```

Follow-up questions about one cluster:

```text
Use query/coverage for <AKS_NAME>. Which sources failed or were partial, with
which HTTP/error code, and which checks cannot be evaluated? A 502/429 is not
permission denied, and a 403 does not mean zero objects.
```

```json
{"operation":"query","view":"coverage","cluster_name":"<AKS_NAME>","status":"denied","limit":10}
```

```text
Use query/findings for <AKS_NAME> with area=security and status=failed.
Prioritize only observed risks with resource, configuration, source, UTC time,
qualified impact and Microsoft recommendation. Do not invent critical findings.
```

```json
{"operation":"query","view":"findings","cluster_name":"<AKS_NAME>","area":"security","status":"failed","limit":10}
```

```text
Use query/workloads for <AKS_NAME> and namespace <NAMESPACE>. Distinguish
desired and ready replicas, probes and requests, and data that is Not
evaluated. Do not infer Kubernetes configuration from ARM Running.
```

```json
{"operation":"query","view":"workloads","cluster_name":"<AKS_NAME>","namespace":"<NAMESPACE>","limit":10}
```

```text
Use query/finops for <AKS_NAME>. Which measurements have timestamp, window,
unit and sample count, and which costs have an actual ResourceId and currency?
Keep candidates separate from calculated savings. Do not buy plans, change
SKUs or delete assets.
```

```json
{"operation":"query","view":"finops","cluster_name":"<AKS_NAME>","limit":5}
```

```text
Use query/summary for <AKS_NAME> and explain score and coverage together: how
many checks were evaluated, Not evaluated and Not applicable, and why this
local index is not an official Azure assessment.
```

```json
{"operation":"query","view":"summary","cluster_name":"<AKS_NAME>"}
```

In the report, the **Subscription** and **Cluster** drop-downs and the search
box at the top filter the fleet table, the KPI cards and the findings;
choosing a cluster opens its complete detailed review.
