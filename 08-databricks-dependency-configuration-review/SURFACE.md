# Azure Databricks dependency and configuration report surface

**Target:** `report_template.html`.
**Mode:** Read-only offline dossier with local operating filters and lossless exports.

## Structure and Flow

1. **Cover & Provenance**: Client plaque (`CLIENTE` default, white plaque for optional private raster logo), workspace identity, SKU, cross-tenant authentication mode disclosure, UTC reference timestamp, and `LIVE` vs `SIMULATED` / `LAB` vs `PRODUCTION` badges.
2. **Executive Assessment & Coverage**: Local rule pass fraction alongside coverage percentage, count-based SVG donut chart (`Cumple`, `No cumple`, `No evaluado`, `No aplica`), 4-area breakdown (`Buenas prácticas`, `Seguridad`, `FinOps`, `Optimización`), 5-pillar WAF breakdown, and observed critical findings shortlist.
3. **Deep Dependency Map (`Mapa de dependencias` & `Propuesta de referencia - NO desplegada`)**:
   - **Tab 1 (`Mapa de dependencias observado e inferido`)**: Filter by dependency layer (`control_plane`, `compute`, `orchestration`, `governance`, `associated_resource`), relationship classification (`OBSERVED`, `INFERRED`, `UNKNOWN`), node kind, or job/workload name. Includes a bounded 13-node SVG neighborhood graph plus complete node, edge and unknown blind-spot tables with exact join-field receipts.
   - **Tab 2 (`Propuesta de referencia - NO desplegada`)**: Static, clearly labeled undeployed Azure Databricks Well-Architected Lakehouse reference diagram (VNet Injection, Secure Cluster Connectivity, Private Link, Unity Catalog with Access Connector UAMI, Cluster Policies, Serverless/Job Compute, Key Vault Secret Scopes).
4. **Workspace, Compute, Orchestration & Unity Catalog Inventory**: Interactive drilldown across Clusters, Instance Pools, Cluster Policies, Jobs & Task DAGs, Lakeflow Declarative Pipelines (DLT), SQL Warehouses, Unity Catalog (Metastore, Catalogs, Schemas, Storage Credentials, External Locations, Connections), Secret Scopes and Associated Azure Resources.
5. **Findings (`Hallazgos y comprobaciones`)**: Full filterable rule evaluations by area, level, pillar, severity, status and workload/job name, with exact evidence receipts and Microsoft Learn links.
6. **FinOps & Capacity Context**: Observed ARM `ActualCost` rows and currency separated from uncalculated savings (`Por estimar / No calculado`), plus computeFinOps anti-pattern candidates (such as jobs pinned to interactive all-purpose clusters or missing autotermination).
7. **Prioritized Action Plan & Source Ledger**: Human review roadmap (`Quick-win`, `Corto plazo`, `Medio plazo`) and per-source HTTP/pagination/coverage receipts.
