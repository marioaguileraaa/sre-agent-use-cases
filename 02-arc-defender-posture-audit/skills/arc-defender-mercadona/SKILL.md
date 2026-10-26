# Arc Defender Mercadona Simulation

## Objective and provenance
Demonstrate the same evidence-led experience using a **SIMULATED**, deterministic
200-server fixture: 142 on-premises / 58 GCP. These allocations, environments,
operating systems and findings are synthetic assumptions, not verified Mercadona
customer facts. Say **SIMULATED** prominently in every answer and artifact.

## Mandatory tool
Use only `simulate-arc-defender-mercadona`. It uses the Python standard library,
never calls Azure or an external service, never acquires a token and needs no
identity scope or cloud role. Do not switch to the live tool for a simulation.

## Report and questions
For the complete branded HTML, server CSV, finding CSV and JSON snapshot, call
`operation="report"` with otherwise default parameters. Deliver all four links,
the synthetic provenance, UTC reference, counts and three explained actions.
Files use the validated fixed `arc-defender-reports` subdirectory of the runtime
working directory, not an arbitrary path or `/mnt/data`. Publish only actual
returned files through the normal sharing mechanism, and verify downloads.
Never invent `sandbox:` links or expand the tool allowlist to solve sharing.

For questions call `operation="query"` with `view="inventory"`, `"findings"` or
`"actions"` and the documented filters. Example: `provider="gcp"` for simulated
GCP gaps; `mde="failed-extension"` for installation failures; `view="actions"`,
`limit=3` for prioritization. For missing **or** failed MDE, use two filtered calls
and combine distinct IDs. Never send arbitrary KQL, URLs or executable input.

Disclose `total_matched`, `returned`, `has_more` and `next_offset`. The full-snapshot
summary is explicitly unfiltered; filtered counts are `matched_servers` and
`total_matched`. Do not imply a capped page is the entire result.
`requested_limit` is only a ceiling. `transport_capped=true` means the complete
JSON was limited to 3500 serialized bytes for the real sandbox stdout transport.
Use the advancing `next_offset` or full report snapshot, never a truncated JSON
string or a silent partial total.
Additional views include `resource_details`, `posture`, `attack_paths`,
`software`, `controls`, `compliance` and `vulnerabilities`. The latter presents
DEMO-VA occurrences, not real CVEs. `risk` means native-like illustrative risk,
not technical `severity`; `status` keeps healthy/unhealthy records separate.
`resource_type` is an exact local filter. Scope-specific unsupported filter
combinations are explicit errors, not silently ignored.

## Interpretation and boundaries
- Keep extension installation separate from the **simulated** independent sensor
  fixture. A synthetic `Healthy` row is not a real MDE health verification.
- Explain priority through concrete synthetic findings/coverage gaps, not a
  fabricated numerical risk score.
- Vulnerability identifiers use `DEMO-VA-*`; never invent real-looking CVEs or
  customer attack paths.
- Illustrative simulated nodes/edges are fictional teaching chains, not real
  Defender graph detections, customer topology or proof that Arc on-premises
  machines support every native attack-path feature.
- The synthetic baseline healthy/total ratio is an illustrative control
  indicator, not native Defender Secure Score or certification.
- Do not claim customer ROI, avoided incidents worth millions, "only solution in
  the market", automatic ENS/GDPR certification, general on-prem/GCP Arc JIT or
  standalone on-premises Arc agentless scanning.
- Defender CSPM and Defender for SQL have separate plans/licensing. Do not say
  Servers P2 includes every Defender cloud capability.
- On any tool error, report the error; do not invent download links or data.
- Never read, attach or reproduce the confidential source PDF. The published
  fixture contains only the explicitly labeled, requested synthetic assumptions.

## Safety
No cloud reads or writes, no credentials, no customer inventory and no live
remediation. The only writes are the four report artifacts beneath the validated
runtime-owned export root. Keep this subagent restricted to this simulation
skill and tool.
