# Azure Update Manager patching & failure investigation surface

**Target:** `report_template.html`
**Mode:** Operate — read-only offline operations ledger with a verdict-first summary, a prioritised action plan, interactive root-cause filters, expandable per-machine diagnostics, and lossless CSV/JSON exports.

## Structure and Flow

1. **Top bar (`header.bar`)**:
   - Sticky anthracite bar (`#141B24`) with a 3px orange rule: product mark, client name (`#client-name-label`) or validated logo plaque (`#brand-plaque`), a `Solo lectura` chip, `Modo oscuro` (`#theme-toggle`), an `Exportar` menu (`#export-menu-btn`) holding `Exportar JSON` (`#export-json-btn`), `Exportar Diagnóstico Máquinas CSV` (`#export-machines-csv-btn`) and `Exportar Ciclos y Parches CSV` (`#export-patches-csv-btn`), and the primary `Imprimir / PDF` (`#print-btn`).
2. **Verdict hero and KPI ledger (`#sec-cover`)**:
   - Title (`#cover-title`), one sentence with the key numbers (`#cover-subtitle`), provenance chips (`#cover-tags`: generated UTC, window, LIVE/SIMULATED and environment, subscription, 7/7 ARG sources, monthly cron), verdict card (`#verdict-card`) with the first action to take, and the machines-by-severity bar (`#severity-track`, `#severity-legend`).
   - Six-cell KPI ledger (`#kpi-strip`) overlapping the hero: machines evaluated (Azure VM + Azure Arc), machines with blockers, maintenance window executions (`UpdateSuccessfullyApplied` vs `ShutdownOrUnresponsive`), installation runs, pending security/critical patches, failed guest extensions. A `SIMULATED` note (`#sim-note`) appears for demo data.
3. **Section index (`nav.toc`)**: sticky left index with live counts per section; collapses to a horizontal strip on narrow screens.
4. **Executive summary (`#sec-executive`)**: machines per automated `failure_category` as clickable labelled bars (`#category-breakdown`, a click filters the register) and the verified executive takeaways (`#executive-messages`).
5. **Prioritised action plan (`#sec-actions`)**: one numbered item per blocker category (`#actions-table`), ordered by severity and affected machines, with the recommended human action, the synthesised diagnosis, machine chips that jump to the register, and the technical reference rendered as name + resource group + Portal link.
6. **Per-machine root-cause register (`#sec-investigation`)**:
   - Filters (`#filter-category`, `#filter-hosting`, `#filter-severity`, `#filter-search`), `Restablecer filtros` (`#filter-reset-btn`), `CSV de la vista` (`#machines-view-csv-btn`) and `Contraer/Expandir todos los detalles` (`#toggle-all-drawers-btn`), with the visible count (`#machines-count-label`).
   - Sortable table (`#machines-table`: severity, machine, pending, cycles) showing severity pill, machine and resource group, diagnosis headline, host/assessment state, pending patches and window cycles; each row has an evidence drawer (`#drawer-machine-N`) with `root_cause_evidence`, every detected blocker, `recommended_human_action`, the ARG reference or guest log path, pending Security/RollUp KBs and a Portal link.
7. **Maintenance cycles and installation runs (`#sec-cycles`)**: newest-first table (`#cycles-table`) of `maintenanceresources` and `patchinstallationresources` with status filter and search.
8. **Pending and installed patches (`#sec-patches`)**: filterable table (`#patches-table`) with KB IDs, classifications, versions and reboot behaviour.
9. **Guest extensions and Hotpatch (`#sec-extensions`)**: table (`#extensions-table`) of VM and Arc extensions (`settings` and `protectedSettings` are never read).
10. **Sources and method (`#sec-sources`)**: 7-source Azure Resource Graph receipts (`#sources-table`), methodological limits (`#methodology-list`) and queried tables with cadence (`#method-tables`).