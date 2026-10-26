# Azure Update Manager patching & failure investigation surface

**Target:** `report_template.html`
**Mode:** Operate — read-only offline operations ledger with interactive root-cause filters, expandable per-machine diagnostics, and lossless CSV/JSON exports.

## Structure and Flow

1. **Topbar & Provenance Header (`#sec-cover`)**:
   - Deep anthracite topbar (`#141B24`) with local operating controls: `Modo oscuro` (`#theme-toggle`), `Exportar JSON` (`#export-json-btn`), `Exportar Diagnóstico Máquinas CSV` (`#export-machines-csv-btn`), `Exportar Ciclos y Parches CSV` (`#export-patches-csv-btn`), and `Imprimir / PDF` (`#print-btn`).
   - Cover header with report title, subscription & window metadata, provenance badges, and white-backed client logo plaque (`#brand-plaque`, `#client-name-label`).
2. **Executive Ledger & Failure Distribution (`#sec-executive`)**:
   - Architectural 1px ledger strip summarizing total machines (`Azure VM` + `Azure Arc`), machines with root-cause blockers, maintenance window executions (`UpdateSuccessfullyApplied` vs `ShutdownOrUnresponsive`), installation runs, and pending security/rollup updates.
   - Visual breakdown of machines by automated `failure_category` and key executive takeaways (`#executive-messages`).
3. **Automated Per-Machine Root-Cause Investigation Ledger (`#sec-investigation`)**:
   - Interactive filter bar (`#filter-category`, `#filter-hosting`, `#filter-severity`, `#filter-search`, `#filter-reset-btn`) updating visible count (`#machines-count-label`).
   - Master-detail expandable diagnostic table (`#machines-table`): each machine displays its hosting (`azure` / `arc`), OS, power/Arc connection state, assessment & patch mode, pending security/critical/rollup/other counts, maintenance cycle ratio, `failure_category`, `severity`, `investigation_headline`, and an expandable root-cause evidence drawer containing `root_cause_evidence`, `log_or_source_reference` (in `Consolas`), guest extensions, and `recommended_human_action`.
4. **Maintenance Cycles & Installation Runs Ledger (`#sec-cycles`)**:
   - Complete chronological table (`#cycles-table`) of `maintenanceresources` (`microsoft.maintenance/applyupdates`, `microsoft.maintenance/configurationassignments`, `microsoft.maintenance/maintenanceconfigurations/applyupdates`) and `patchinstallationresources` executions in the selected window, highlighting `UpdateSuccessfullyApplied` vs `ShutdownOrUnresponsive`, correlation IDs, reboot status, and patch counts.
5. **Pending & Installed Software Patches (`#sec-patches`)**:
   - Interactive filterable table (`#patches-table`) of pending software updates (`arg_software_patches_pending`) and installed/not-selected patches (`arg_software_patches_installed`) with KB IDs, classifications (`Security`, `Critical`, `UpdateRollUp`, `Definition`, `Updates`, `Other`), versions, and reboot behavior.
6. **Guest Patching & Management Extensions (`#sec-extensions`)**:
   - Table (`#extensions-table`) of VM and Arc extensions (`publisher`, `type`, `typeHandlerVersion`, `provisioningState`, `autoUpgradeMinorVersion`, `enableAutomaticUpgrade`) correlated with `hotpatchStatus` and guest patch readiness.
7. **Prioritized Human Remediation Plan & Source Receipts (`#sec-actions`, `#sec-sources`)**:
   - Actionable engineering remediation table (`#actions-table`) and 7-source Azure Resource Graph coverage receipt ledger (`#sources-table`).
