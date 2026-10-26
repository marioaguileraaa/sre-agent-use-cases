# Azure Databricks dependency and configuration consulting report

<!-- impeccable:product-schema 1 -->

## Platform

web

## Users

Platform architects, data engineering leads, security reviewers and FinOps owners inspecting an Azure Databricks workspace, its compute/orchestration workloads, Unity Catalog objects and associated Azure infrastructure.

## Product Purpose

Deliver a dated, read-only assessment of an Azure Databricks workspace across **dependency mapping, best practices, security, FinOps and general optimization**, aligned with the five Azure Well-Architected Framework pillars and the Databricks Well-Architected Lakehouse principles.

## Operating Context

An offline, single-file HTML consulting dossier suitable for executive review, technical dependency tracing, mobile reading, dark mode and print/PDF archival.

## Capabilities and Constraints

- One self-contained HTML file with inline CSS and JavaScript, system fonts, strict CSP (`default-src 'none'`), and zero network calls.
- Deep dependency map distinguishing **OBSERVED** native joins (ARM IDs, cluster IDs, job task DAG `depends_on`, `run_job_task`, `pipeline_id`, `warehouse_id`, `instance_pool_id`, `policy_id`, Unity Catalog `credential_name`, `access_connector_id`, Key Vault `resource_id`), explicit **INFERRED** configuration references (`abfss://` storage account hosts or Key Vault DNS names not in ARM inventory), and **UNKNOWN** blind spots (runtime table/column lineage in `system.access.table_lineage` requiring billable SQL warehouse execution, notebook code reads, and untested data-plane reachability).
- Never starts stopped clusters or SQL warehouses, and never executes SQL queries to fabricate lineage or FinOps workload attribution.
- Multi-workspace and single-workspace support, preserving failed workspace runs without substituting healthy-zero inventories.
- Local pass index displayed beside evaluated/unevaluated coverage counts; never presented as an official Microsoft WAF or Databricks certification.

## Brand Commitments

- Combines the corporate industrial navy/steel palette (`#003865`, `#0066a1`) and Databricks lakehouse lava/teal accents (`#ff3621`, `#00875a`) in chrome, cover framing and the four-color brand ribbon.
- Committed repository files, templates and documentation never include a customer name, customer logo or private customer identifiers; the cover plaque displays `CLIENTE` until an authorized operator privately configures a bounded PNG/JPEG raster outside Git.
- Spanish business language (`es-ES`) in the generated HTML report; English implementation and cross-tenant onboarding guide in `README.md`.
