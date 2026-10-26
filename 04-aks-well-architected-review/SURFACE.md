# AKS report surface

**Target:** `report_template.html`.
**Mode:** Read, with operating filters and local exports.

The reader first identifies the client, cluster, lab/production context,
reference time and evidence provenance. The executive section separates the
engine's local index from its coverage, then presents only supplied priorities.
Inventory and findings support category, namespace and workload drilldown.
FinOps qualifies observed costs and candidates; a human action plan and
source/method receipts close the dossier.

The assessment chart visualizes the supplied counts of passed, failed,
not-evaluated and not-applicable checks. Its centre is the count of checks,
not an invented health grade. A labelled data table and the separate supplied
score/coverage stay alongside it. Unknowns are neutral, never green.

FinOps separates a prominent observed amount/currency from estimated savings.
Missing savings say **Por estimar / No calculado**, never zero. Scope,
association, dates and completeness come from the actual cost receipt, not
from namespace filters or a guessed allocation. Measurement windows retain
their original sample shape separately from billing periods.

Architecture has two keyboard-operable tabs: **Arquitectura observada** uses
only the engine's exact node/edge/source identities and full field receipts;
**Propuesta de referencia - NO desplegada** is a static, conditional Microsoft
baseline with cited assumptions and tradeoffs. Azure public Load Balancer
(ELB) and private frontend (ILB) are labelled explicitly, not inferred from
names. No database, ingress, connection or resource is fabricated.

The resource-type picker, object picker and grouped resource tree expose every
node. The visual neighbourhood is bounded to thirteen nodes, with its actual
visible/total counts; complete node/edge/unknown tables and JSON retain all
records. On mobile the graph scrolls locally rather than shrinking labels to
unreadable pixels. Namespace/workload topology context uses Kubernetes
namespace/kind/name/UID evidence, never a shared cluster ARM ID.

The multi-cluster wrapper keeps a supplied aggregate overview separate from
the selected cluster's detailed snapshot. Switching clusters resets local
filters. A failed primary read shows its actual error, with no score/workload/
cost/topology fallback. A fixed roster is configuration, not presence or
health. Full JSON keeps the original wrapper; scope JSON filters only the
selected snapshot and explicitly retains all other run snapshots/errors and
the original aggregate.

The pinned direction is a Fluent 2 consulting document, not a SaaS dashboard:
white or neutral-dark reading pages, left-aligned Segoe UI, deliberate whitespace
and ruled tables. The user's subsequent color direction adds Microsoft-blue
chrome, a blue-toned cover and contents rail, and a four-color brand ribbon.
The palette frames the document, not its health; severity color never stands in
for a missing observation.

The signature interaction is following a namespace or workload into the same
complete evidence set, with matching-record counts and lossless local exports
remaining independent of pagination. Global/area/pillar scores always retain
their explicitly labeled whole-snapshot scope.

The ARM parent resource ID is not a Kubernetes object identity. Workload
selection uses the supplied Kubernetes UID, or namespace/kind/name when no UID
is available; namespace-bearing records never cross namespace boundaries merely
because they share the same ARM parent. Raw identities remain unchanged in
receipts and exports.

The engine fills `__REPORT_DATA_JSON__` exactly once in an application/json
script. Startup validates schema 1.0 before exposing the report. All supplied
data enters the DOM as text or explicitly allowlisted URLs. Optional branding
is an inline raster image on a white plaque in both themes.

Observation windows retain their source shape: a `{start, end}` interval, one
`{timestamp, duration}` measurement window, a list of such measurement windows,
or `null`. Each sample's timestamp and duration is displayed separately;
repeated timestamps are retained and never collapsed into an invented interval.
Additional evidence fields remain available in receipts and complete exports.

Printed output retains the selected scope, materializes every matching row,
opens disclosures and removes operating controls. Unavailable information,
source failures and lab/synthetic labels remain visible in every scene.
Both architecture views print with the undeployed label intact. The graph
remains a bounded illustration; the full node/edge tables print every match.
The eleven original Azure V24 SVGs are audited static data URIs, with nearby
product names and retained usage/source/hash notices.

No unresolved aesthetic decisions. Missing runtime evidence belongs to the
engine and parent; the surface must disclose it rather than invent it.
