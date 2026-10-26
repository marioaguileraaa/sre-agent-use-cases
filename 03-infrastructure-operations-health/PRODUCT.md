# Infrastructure operations evidence

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Infrastructure operators reviewing a hybrid estate, and customers watching an
Azure SRE Agent demonstration. They need to distinguish an observed operational
problem from a monitoring blind spot, locate its evidence, and decide who should
review it.

## Product Purpose

Scenario 03 makes real CPU, memory, utilization, health, capacity and anomaly
evidence understandable across Azure Arc machines and Azure-native services.
The deliverable pairs source-grounded chat questions with a monthly interactive
HTML snapshot and machine-readable exports.
The same collector includes Arc agent/OS and native extension metadata, plus
optional dated owner-approved review baselines. Administration policy Unknowns
are separate from existing measurement assessments; review targets are not
support certification, latest-version claims or automatic maintenance.

## Positioning

One restricted read-only SRE subagent explains comparable operational signals
without pretending that Arc guest telemetry, Azure platform metrics and managed
service metrics have identical semantics. The absence of evidence remains
visible rather than becoming zero or a healthy status.

## Operating Context

The report is reviewed monthly and can be generated on demand. It is a dated,
self-contained offline artifact, not a live-polling portal. Fresh chat queries
collect scoped evidence for real-time demonstrations. A separately approved,
bounded operator load exercise demonstrates an actual Azure Monitor alert
invoking the subagent; the report, skill and scheduled task never apply load.

## Capabilities and Constraints

- Use real lab observations only for deployed demonstrations.
- Keep source, resource identity, unit, aggregation, grain, observation time,
  coverage and uncertainty attached to measurements.
- Support resource filters, time series, comparisons, chronological events,
  resource drilldowns and complete filtered exports.
- Collect only from one configured subscription and explicitly allowed log
  workspaces using the agent's managed identity.
- Return compact, complete structured chat responses. Full normalized evidence
  belongs in guarded runtime-owned files.
- Missing guest monitoring is Unknown / Not collected. Arc connection and ARM
  provisioning are not guest health. Anomaly flags are not root-cause proof.
- No automatic remediation, resource changes, workload stops, secrets, OOM
  exercises, disk filling or unbounded stress.
- No external frontend libraries, fonts, CDN calls, tokens or analytics.
- Preserve scenarios 01 and 02. Keep this scenario's product and design records
  inside this folder.

## Brand Commitments

Customer-neutral and reusable. The user explicitly requested a report with
personality that differs materially from the earlier scenarios and avoids a
generic AI dashboard. The confidential customer document was conceptual
inspiration only: no customer data, branding, copied assets or simulation belongs
in this scenario.

## Evidence on Hand

The repository contains earlier standalone SRE tools and their documentation;
their transport, export and managed-identity contracts are reusable prior art,
not performance measurements for this scenario. Current real telemetry,
permissions, alert-trigger proof and masked runtime screenshots are supplied
and verified by the parent session. Until supplied, availability and deployment
claims remain unconfirmed. Offline tests may use explicitly synthetic,
source-shaped fixtures that are never deployed as lab observations.

## Product Principles

1. Evidence before confidence: preserve unknowns and disclose source errors.
2. Comparable only when semantics match: never hide units or aggregation.
3. Read-only by construction: operator actions are separate and explicit.
4. Useful decisions over decorative scores: prioritize explainable owner reviews.
5. Snapshot honesty: recorded time and coverage travel with every export.

## Recorded Decisions and Runtime Evidence

The assigned operations-ledger direction was implemented after the subsequent
instruction to continue autonomously, as an explicitly stated assumption.
The built world is recorded in this folder's DESIGN.md, not inferred from
the older scenarios.

The parent supplied verified real Arc/native telemetry, deployed restricted
components, final monthly/current native downloads, actual automatic incident
invocations, bounded operator CPU measurements, worker cleanup and original
power-state restoration receipts. The README records their dated scope and
limitations; no private raw telemetry dataset is published. The Arc exercise
honors its observed command CPU quota rather than claiming host-wide saturation.
Offline tests and replay checks remain distinct from these runtime facts.
