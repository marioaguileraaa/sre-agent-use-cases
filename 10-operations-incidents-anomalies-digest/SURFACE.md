# Azure Operations, Incidents, Anomalies, and Recommended Actions Digest Surface

**Target:** `report_template.html`
**Mode:** Operate / Read-only engineering operations dossier with live client-side filtering and lossless exports.

## Structure and Flow

1. **Top Architectural Chrome (`#topbar`)**: Client plaque (`#client-plaque`), dossier title, and five local utility actions (`Modo oscuro`, `Exportar JSON`, `Exportar Incidencias y Anomalías CSV`, `Exportar Acciones Recomendadas CSV`, `Imprimir / PDF`).
2. **Executive Synthesis & Window Provenance Header (`#sec-executive`)**: Subscription and UTC window provenance grid (`#provenance-strip`), 6-cell architectural ledger strip (`#ledger-summary-grid`), proportional severity distribution bar (`#evidence-distribution-bar`), and executive synthesis points (`#executive-messages-list`).
3. **Interactive Filter Bar (`#sec-filters`)**: Live filtering across `category`, `severity`, `horizon`, and free-text search (`#filter-search`) with instant counter updates and reset (`#filter-reset`).
4. **Unified Incidents Ledger (`#sec-incidents`)**: Consolidates native Azure Monitor alerts (`native_alert`) and Azure Service Health events (`service_health`) with exact signal types, monitor conditions, and UTC timestamps.
5. **Technical Anomalies Ledger (`#sec-anomalies`)**: Consolidates failed VM/Arc guest extensions (`extension_failure`), control-plane/connectivity anomalies (`connectivity_posture`), and statistical/threshold telemetry anomalies (`telemetry_anomaly`) with observed values, baselines, units, sample counts, and time grains.
6. **Prioritized Recommended Actions Matrix (`#sec-actions`)**: Action plan (`acciones recomendadas`) ordered by urgency horizon (`Inmediato <24h`, `Corto plazo 1-7 días`, `Ciclo mensual`) and severity, citing exact incident/anomaly/Advisor IDs, owner review scopes, and Microsoft Learn URLs.
7. **Resource Health & Advisor Context Ledger (`#sec-resources`)**: Per-resource operational roll-up (`#resources-table`) and correlated Azure Advisor recommendations (`#advisor-table`).
8. **Source Coverage Receipts & Methodology (`#sec-coverage`)**: Per-source collection receipts (`#sources-table`) and read-only methodology disclosures (`#methodology-list`).
