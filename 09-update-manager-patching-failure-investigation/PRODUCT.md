# Azure Update Manager patching cycle & per-machine failure investigation dossier

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Infrastructure operations engineers, systems administrators, security operations leads, and service delivery managers responsible for monthly post-patching verification across Azure Virtual Machines (`Microsoft.Compute/virtualMachines`) and Azure Arc-enabled servers (`Microsoft.HybridCompute/machines`).

## Product Purpose

Deliver a dated, read-only post-patching cycle report and **automated per-machine root-cause failure investigation** using Azure Update Manager (`patchassessmentresources`, `patchinstallationresources`, `maintenanceresources`) and guest extension state, so operators immediately know which machines patched, which missed their maintenance window, and the exact technical blocker on every machine without logging into hosts one by one.

## Operating Context

An offline, single-file HTML industrial operations workpaper suitable for monthly scheduled execution (`0 8 1 * *`), interactive failure triage, master-detail root-cause inspection, mobile reading, dark mode, and print/PDF archival.

## Capabilities and Constraints

- One self-contained HTML file with inline CSS and JavaScript, strict Content Security Policy (`default-src 'none'`), and zero external runtime network requests.
- Correlates 7 read-only Azure Resource Graph (`Microsoft.ResourceGraph/resources?api-version=2022-10-01`) datasets across `resources`, `patchassessmentresources`, `patchinstallationresources`, and `maintenanceresources`.
- Classifies every compute machine into an explicit diagnostic category (`maintenance_window_unresponsive`, `arc_agent_expired_or_disconnected`, `assessment_stuck_or_readiness_undetermined`, `hotpatch_or_patch_extension_error`, `pending_security_patches_unscheduled`, `unassessed_no_update_manager_telemetry`, `healthy`) with structured root-cause evidence, guest log path or source reference, and concrete remediation steps.
- Never executes guest commands (`runCommand`), never starts/deallocates VMs, never triggers `installPatches` or `assessPatches`, and never reads extension `settings` or `protectedSettings`.

## Brand Commitments

- **Swiss Architectural Industrial Operations Ledger**: combines deep anthracite slate (`#141B24`), warm architectural stone (`#F6F5F2`), crisp 1px-bordered workpaper surfaces (`#FFFFFF`, `#D8DCE3`), vivid industrial orange structural accents (`#FF4E00`), and accessible burnt orange interactive text tokens (`#C23800`, >=4.5:1 on white).
- Generic repository source files never contain a customer name, customer logo, or private identifiers (`CLIENT_NAME = "CLIENTE"`, `CLIENT_LOGO_DATA_URI = ""`). Authorized operators privately configure a Pillow-validated PNG/JPEG data URI outside Git.
- Spanish business and technical operations language (`es-ES`) in the generated HTML report; English implementation and onboarding documentation in `README.md`.
