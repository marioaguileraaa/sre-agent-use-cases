# Azure Operations, Incidents, Anomalies, and Recommended Actions Digest Surface

**Target:** `report_template.html`
**Mode:** Operate / Read-only engineering operations dossier with live client-side filtering and lossless exports.

## Structure and Flow

1. **Top bar (`#topbar`)**: client plaque (`#client-plaque`), Azure SRE Agent mark, section navigation with live counts (`#section-nav`), `Solo lectura` chip, `Modo oscuro` (`#theme-toggle`) and `Imprimir / PDF` (`#btn-print`). Sticky on screen; on narrow screens the navigation hides and the buttons become icons.
2. **Verdict-first header (`#top`)**: H1, window scope, one-sentence summary with the key counts (`#hero-lead`), meta chips (generated UTC, window, subscription, LIVE/SIMULATED, coverage), verdict card (`#verdict-card`) and severity distribution (`#evidence-distribution-bar`).
3. **KPI cards (`#ledger-summary-grid`)** overlapping the header (alerts, Service Health, control-plane and Arc anomalies, telemetry anomalies, recommended actions, resources), then data notices (`#status-notes`: simulated data, partial coverage).
4. **Period summary (`#sec-executive`)**: `Qué hacer ahora` (horizon tiles that filter the plan and the top five actions), executive synthesis (`#executive-messages-list`) with provenance (`#provenance-strip`), signals by evidence stream and resources with most signals (bars that apply the matching filter and jump to the register).
5. **Filters (`#sec-filters`)**: search (`#filter-search`), `category`, `severity`, `horizon`, reset (`#filter-reset`), a live status line and the local downloads (`#btn-export-json`, `#btn-export-incidents-csv`, `#btn-export-actions-csv`, always the full data).
6. **Registers**: incidents and platform communications (`#sec-incidents`), technical anomalies (`#sec-anomalies`), prioritized recommended actions (`#sec-actions`, evidence IDs jump to the cited row), resource status and Azure Advisor (`#sec-resources`). Sortable headers, `X de Y` counts, resources as name + resource group + type + Portal link, 50 rows per page on screen with `Mostrar más` (print shows every row).
7. **Source coverage and method (`#sec-coverage`)**: per-source receipts (`#sources-table`: status, records, pages, read signature, errors), limitations (`#methodology-list`) and run parameters, then the footer.