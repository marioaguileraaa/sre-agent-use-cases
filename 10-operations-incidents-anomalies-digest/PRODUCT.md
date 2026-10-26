# Periodic Azure Operations, Incidents, Anomalies, and Recommended Actions Digest

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Operations directors, SRE leads, hybrid infrastructure engineers, and cloud governance teams reviewing periodic operational health across Azure and Azure Arc estates.

## Product Purpose

Consolidate five read-only Azure evidence streams — native Azure Monitor alerts (`alertsmanagementresources`), Azure Service Health communications (`Microsoft.ResourceHealth/events`), cross-estate control-plane and guest extension posture (`Azure Resource Graph`), guest/platform telemetry anomalies (`Log Analytics InsightsMetrics, Perf, Heartbeat`), and correlated Azure Advisor recommendations (`Microsoft.Advisor/recommendations`) — into a single executive and technical dossier with a prioritized Recommended Actions (`acciones recomendadas`) ledger.

## Operating Context

An offline, single-file HTML operational ledger with zero external dependencies, strict CSP (`default-src 'none'`), interactive filtering, dark mode, print/PDF support, and four native downloadable artifacts in Azure SRE Agent. Scheduled monthly (`30 8 1 * *`, default `period="previous_month"`) while supporting `last_30d`, `last_7d`, and `last_24h` on demand.

## Capabilities and Constraints

- Read-only collection across Azure Resource Graph, Azure Resource Health, Log Analytics, and Azure Advisor using an explicit user-assigned managed identity (`MANAGED_IDENTITY_CLIENT_ID`).
- Strictly separates native fired/resolved alerts, official Azure Service Health platform events, control-plane/extension failures, and statistical/threshold telemetry anomalies.
- Prioritizes recommended actions across three operational horizons (`Inmediato <24h`, `Corto plazo 1-7 días`, `Ciclo mensual`) linked to exact incident, anomaly, and Advisor IDs.
- Public repository files use generic `CLIENTE` branding and empty `CLIENT_LOGO_DATA_URI`; private customer deployments validate embedded PNG/JPEG rasters with Pillow.
