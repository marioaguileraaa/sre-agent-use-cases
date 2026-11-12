"""Read-only Azure Databricks dependency and configuration assessment. Build assets with build_tool.py before SRE paste."""

import base64
import binascii
import csv
import hashlib
import io
import json
import math
import os
import re
import ssl
import tempfile
import time
import warnings
from collections import Counter
from datetime import datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from uuid import UUID, uuid4


SUBSCRIPTION_ID = "<YOUR_TARGET_SUBSCRIPTION_ID>"
SRE_TENANT_ID = "<YOUR_SRE_AGENT_TENANT_ID>"
TARGET_TENANT_ID = "<YOUR_TARGET_DATABRICKS_TENANT_ID>"
MANAGED_IDENTITY_CLIENT_ID = "<YOUR_SRE_UAMI_CLIENT_ID>"
FEDERATED_APP_CLIENT_ID = ""
KEYVAULT_OAUTH_SECRET_URI = ""
# Optional cross-tenant certificate for auth_mode "cross_tenant_multitenant_fic". The Azure SRE Agent sandbox hands
# Python tools sidecar-issued managed identity tokens that the platform proxy swaps at egress, so they cannot be sent
# as a federated client assertion (Entra rejects them with AADSTS5002723). Store a certificate of the multi-tenant
# app in a Key Vault the agent identity can read (Key Vault Secrets User) and set both values; leave them empty to
# use the federated identity credential.
CROSS_TENANT_CERT_KEYVAULT_URL = ""
CROSS_TENANT_CERT_NAME = ""
CLIENT_NAME = "CLIENTE"
# Here goes the customer's logo, privately configured as a validated PNG/JPEG
# data URI. Keep generic Git source empty. Use adjacent strings <10K per line.
CLIENT_LOGO_DATA_URI = ""
CLIENT_LOGO_ALT = "Logotipo autorizado del cliente"
APPROVED_WORKSPACES = {
    "<APPROVED_DATABRICKS_WORKSPACE_NAME>": {
        "resource_group": "<APPROVED_DATABRICKS_RESOURCE_GROUP>",
        "workspace_host": "<APPROVED_WORKSPACE_HOST_ADB_NET>",
        "environment": "UNSPECIFIED",
        "auth_mode": "same_tenant_uami",
        "workspace_api_enabled": True,
        "unity_catalog_enabled": True,
        "include_managed_resource_group": True,
        "advisor_enabled": True,
        "approved_related_resource_ids": [],
        "approved_cost_resource_ids": [],
        "cost_scope": "disabled",
        "cost_timeframe": "month_to_date",
        # Databricks costs (report section 6): Cost Management grouped by Databricks tags for the workspace resource,
        # its managed resource group and approved_cost_resource_ids. Needs Reader or Cost Management Reader on the
        # subscription; free reads that never start compute.
        "cost_analysis_enabled": True,
        # OFF by default because it costs DBUs: the ID of an EXISTING SQL warehouse enables per-run and per-user detail
        # from system.billing.usage + system.billing.list_prices (Statement Execution API, one fixed read-only SELECT).
        "system_tables_warehouse_id": "",
        "requirements": {},
    }
}
# Databricks cost analysis settings (shared by all approved workspaces).
COST_METRIC = "AmortizedCost"  # AmortizedCost spreads Databricks commit units and reservations; ActualCost is the invoice view
COST_ALLOCATION_TAGS = ["team", "project", "cost_center"]  # your own cluster, job, pool and warehouse tags (up to 3 keys)
COST_AUTOTERMINATION_MAX_MINUTES = 60  # interactive clusters with a longer auto-termination are flagged
COST_WAREHOUSE_AUTOSTOP_MAX_MINUTES = 30  # SQL warehouses with a longer auto-stop are flagged
COST_JOBS_TO_ALL_PURPOSE_DBU_RATIO = 0.55  # Jobs compute DBU list price / All-purpose DBU list price (Premium 0.30 / 0.55)
COST_SPOT_DISCOUNT = 0.6  # conservative Azure Spot discount used for worker VMs (Azure quotes up to 90 %)
REPORT_FOCUS = "configuration"  # "costs" opens the report with the Databricks cost section (title, verdict and KPIs)
# Optional private branding (keep empty in Git): CSS colour overrides from BRAND_THEME_KEYS, a WOFF2 heading font as a
# data URI (<= 80 KB) and where the client logo goes ("hero" plaque or "bar" = white top bar, no plaque).
BRAND_THEME = {}
BRAND_DISPLAY_FONT_DATA_URI = ""
BRAND_LOGO_PLACEMENT = "hero"

ARM_ORIGIN = "https://management.azure.com"
ARM_TOKEN_AUDIENCES = (
    "https://management.azure.com",
    "https://management.core.windows.net",
)
KEYVAULT_AUDIENCE = "https://vault.azure.net"
DATABRICKS_ENTRA_RESOURCE = "2ff814a6-3304-4ab8-85cb-cd0e6f879c1d"
ENTRA_TOKEN_EXCHANGE_AUDIENCE = "api://AzureADTokenExchange"
ENTRA_TOKEN_EXCHANGE_AUDIENCES = (
    "api://azureadtokenexchange",
    "fb60f99c-7a34-4190-8149-302f77469936",
)
DATABRICKS_ARM_API = "2024-05-01"
TRANSPORT_BYTES = 3500
ARTIFACT_BYTES = 4_800_000
HTTP_BYTES = 8_000_000
MAX_PAGES = 50
MAX_ROWS = 15000
MAX_RELATED_RESOURCES = 200
MAX_DETAIL_GETS = 100
MAX_COLLECTION_SECONDS = 420
MAX_HTTP_ATTEMPTS = 360
OUTPUT_DIRECTORY = "databricks-dependency-reports"
COST_API_VERSION = "2025-03-01"
COST_QUERY_RESERVE_SECONDS = 20
MAX_COST_ROWS = 20000
MAX_COST_DAILY_KEYS = 100
COST_MAX_RETRY_WAIT = 30
COST_DIMENSIONS = (
    ("cluster", "ClusterName"),
    ("job", "JobId"),
    ("warehouse", "SqlEndpointId"),
    ("pool", "DatabricksInstancePoolId"),
)
BRAND_THEME_KEYS = (
    "--paper", "--surface", "--soft", "--hover", "--ink", "--title", "--muted", "--line", "--line2", "--link", "--focus",
    "--sel", "--chart", "--chart-2", "--edge", "--bar-bg", "--bar-hover", "--btn", "--btn-hover", "--btn-ink", "--hero-a",
    "--hero-b", "--hero-muted", "--hero-line", "--brand-rule", "--brand-logo", "--foot-bg", "--foot-ink",
)
OPERATIONS = ("report", "query", "list_workspaces", "self_test")
AUTH_MODES = (
    "same_tenant_uami",
    "cross_tenant_multitenant_fic",
    "cross_tenant_lighthouse_plus_databricks_oidc",
    "cross_tenant_lighthouse_plus_keyvault_oauth_m2m",
)
AREAS = ("best_practices", "security", "finops", "optimization")
PILLARS = ("reliability", "security", "cost", "operations", "performance")
LEVELS = ("workspace", "workload", "resource")
SEVERITIES = ("critical", "high", "medium", "low")
CLASSIFICATIONS = ("OBSERVED", "INFERRED", "UNKNOWN")
CHECK_STATUSES = ("passed", "failed", "not_evaluated", "not_applicable")
SOURCE_STATUSES = ("complete", "partial", "denied", "error", "not_configured", "not_applicable")
VIEWS = (
    "summary",
    "workspace",
    "compute",
    "jobs",
    "pipelines",
    "warehouses",
    "unity_catalog",
    "resources",
    "findings",
    "finops",
    "coverage",
    "actions",
    "dependencies",
    "costs",
)
SYSTEM_CATALOGS = ("system", "hive_metastore", "samples", "__databricks_internal")
RESOURCE_APIS = {
    "microsoft.databricks/accessconnectors": "2024-05-01",
    "microsoft.storage/storageaccounts": "2023-05-01",
    "microsoft.keyvault/vaults": "2023-07-01",
    "microsoft.network/virtualnetworks": "2024-05-01",
    "microsoft.network/virtualnetworks/subnets": "2024-05-01",
    "microsoft.network/networksecuritygroups": "2024-05-01",
    "microsoft.network/routetables": "2024-05-01",
    "microsoft.network/natgateways": "2024-05-01",
    "microsoft.network/publicipaddresses": "2024-05-01",
    "microsoft.network/loadbalancers": "2024-05-01",
    "microsoft.network/privateendpoints": "2024-05-01",
    "microsoft.network/privatednszones": "2020-06-01",
    "microsoft.eventhub/namespaces": "2024-01-01",
    "microsoft.managedidentity/userassignedidentities": "2023-01-31",
}
WORKSPACE_CONF_KEYS = (
    "enableTokensConfig",
    "maxTokenLifetimeDays",
    "enableIpAccessLists",
    "enableDbfsFileBrowser",
    "enableExportNotebook",
)

# BEGIN BUILD-TIME ASSETS
CATALOG = json.loads((
    '{"catalogSnapshot": {"name": "Azure Databricks Well-Architected & Lakehouse Dependency Review", "ser'
    'vice_guide_url": "https://learn.microsoft.com/en-us/azure/well-architected/service-guides/azure-data'
    'bricks", "lakehouse_waf_url": "https://learn.microsoft.com/en-us/azure/databricks/lakehouse-architec'
    'ture/well-architected", "arm_template_url": "https://learn.microsoft.com/en-us/azure/templates/micro'
    'soft.databricks/2024-05-01/workspaces", "retrieved_at": "2026-10-16", "item_count": 36}, "assessment'
    '_url": "https://learn.microsoft.com/en-us/assessments/azure-architecture-review/", "interpretation":'
    ' ["Local rule-resource indicators, not an official Microsoft Well-Architected assessment, certificat'
    'ion or Databricks audit grade.", "Dependency edges distinguish OBSERVED native ID/key joins from exp'
    'licit INFERRED URI/host references and UNKNOWN runtime lineage.", "Control-plane REST API reads neve'
    'r start clusters or SQL warehouses and never execute billable SQL queries against system.access.tabl'
    'e_lineage; system.billing.usage is queried only when the operator sets system_tables_warehouse_id (o'
    'ff by default; that one fixed statement consumes DBUs and can start the chosen warehouse).", "Cross-'
    'tenant collection requires explicit administrator-configured federation or Azure Lighthouse delegati'
    'on; a single-tenant SRE UAMI never acquires foreign-tenant tokens implicitly.", "Configuration prese'
    'nce does not prove effective firewall enforcement, data-plane network reachability, least-privilege '
    'Unity Catalog grants or workload SLA compliance."], "rules": [{"rule_id": "C01", "reference_id": "DB'
    'X-WAF-SEC-01", "test": "sku_premium", "level": "workspace", "area": "security", "pillar": "security"'
    ', "severity": "high", "effort": "medium", "title": "SKU Premium para gobernanza y controles de segur'
    'idad", "recommendation": "Validar el uso del tier Premium para cargas de producci\\u00f3n que requier'
    'en Unity Catalog, control de acceso basado en roles y auditor\\u00eda avanzada.", "business_impact": '
    '"Un tier inferior a Premium puede limitar controles de identidad, Unity Catalog y aislamiento de acc'
    'eso.", "learn_url": "https://learn.microsoft.com/en-us/azure/well-architected/service-guides/azure-d'
    'atabricks#cost-optimization"}, {"rule_id": "C02", "reference_id": "DBX-WAF-SEC-02", "test": "secure_'
    'cluster_connectivity", "level": "workspace", "area": "security", "pillar": "security", "severity": "'
    'high", "effort": "medium", "title": "Secure Cluster Connectivity (No Public IP)", "recommendation": '
    '"Habilitar enableNoPublicIp en el workspace para que los nodos de c\\u00f3mputo no tengan direcciones'
    ' IP p\\u00fablicas y conecten al plano de control por rel\\u00e9 saliente.", "business_impact": "Nodos'
    ' de cl\\u00faster con IP p\\u00fablica incrementan la superficie de exposici\\u00f3n de red del plano d'
    'e datos.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/security/network/classic'
    '/secure-cluster-connectivity"}, {"rule_id": "C03", "reference_id": "DBX-WAF-NET-01", "test": "vnet_i'
    'njection", "level": "workspace", "area": "best_practices", "pillar": "security", "severity": "medium'
    '", "effort": "high", "title": "Despliegue con VNet Injection en red gestionada por el cliente", "rec'
    'ommendation": "Cuando la arquitectura de red corporativa lo requiera, desplegar el workspace con cus'
    'tomVirtualNetworkId y subredes host/container dedicadas.", "business_impact": "La VNet administrada '
    'por defecto impide aplicar rutas personalizadas, inspecci\\u00f3n de egress o emparejamientos granula'
    'res.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/security/network/classic/vne'
    't-inject"}, {"rule_id": "C04", "reference_id": "DBX-WAF-NET-02", "test": "private_link_and_public_ac'
    'cess", "level": "workspace", "area": "security", "pillar": "security", "severity": "high", "effort":'
    ' "high", "title": "Restricci\\u00f3n de red p\\u00fablica y Private Link del workspace", "recommendati'
    'on": "Revisar publicNetworkAccess, requiredNsgRules y conexiones Private Endpoint aprobadas seg\\u00f'
    'an los requisitos de aislamiento privado.", "business_impact": "El acceso p\\u00fablico abierto sin c'
    'ontroles compensatorios ampl\\u00eda la superficie de entrada al workspace.", "learn_url": "https://l'
    'earn.microsoft.com/en-us/azure/databricks/security/network/classic/private-link"}, {"rule_id": "C05"'
    ', "reference_id": "DBX-WAF-SEC-03", "test": "access_connector_and_storage_firewall", "level": "works'
    'pace", "area": "security", "pillar": "security", "severity": "medium", "effort": "medium", "title": '
    '"Access Connector con identidad administrada y firewall de almacenamiento", "recommendation": "Vincu'
    'lar un Azure Databricks Access Connector con identidad administrada (SystemAssigned o UserAssigned) '
    'y revisar defaultStorageFirewall.", "business_impact": "La ausencia de Access Connector impide auten'
    'ticar con identidad administrada hacia almacenamiento gobernado.", "learn_url": "https://learn.micro'
    'soft.com/en-us/azure/databricks/connect/unity-catalog/cloud-storage/azure-managed-identities"}, {"ru'
    'le_id": "C06", "reference_id": "DBX-WAF-SEC-04", "test": "customer_managed_keys", "level": "workspac'
    'e", "area": "security", "pillar": "security", "severity": "medium", "effort": "medium", "title": "Ci'
    'frado con claves gestionadas por el cliente (CMK) e infraestructura", "recommendation": "Si la pol\\u'
    '00edtica de cumplimiento exige CMK, configurar claves de Key Vault para managedServices y managedDis'
    'k con rotaci\\u00f3n autom\\u00e1tica.", "business_impact": "Sin CMK cuando es requerido por normativa'
    ', el cliente no controla directamente la revocaci\\u00f3n criptogr\\u00e1fica.", "learn_url": "https:/'
    '/learn.microsoft.com/en-us/azure/databricks/security/keys/"}, {"rule_id": "C07", "reference_id": "DB'
    'X-WAF-SEC-05", "test": "enhanced_security_compliance", "level": "workspace", "area": "security", "pi'
    'llar": "operations", "severity": "low", "effort": "medium", "title": "Perfil de seguridad mejorada y'
    ' actualizaci\\u00f3n autom\\u00e1tica de cl\\u00fasteres", "recommendation": "Evaluar enhancedSecurityM'
    'onitoring, automaticClusterUpdate y complianceSecurityProfile cuando apliquen normativas espec\\u00ed'
    'ficas.", "business_impact": "Sin actualizaciones autom\\u00e1ticas o monitorizaci\\u00f3n mejorada req'
    'uerida, el mantenimiento de agentes depende de procesos manuales.", "learn_url": "https://learn.micr'
    'osoft.com/en-us/azure/databricks/security/privacy/security-profile"}, {"rule_id": "C08", "reference_'
    'id": "DBX-WAF-OPS-01", "test": "diagnostics", "level": "workspace", "area": "best_practices", "pilla'
    'r": "operations", "severity": "medium", "effort": "low", "title": "Configuraci\\u00f3n de Diagnostic '
    'Settings en el plano de control ARM", "recommendation": "Configurar categor\\u00edas de auditor\\u00ed'
    'a en Microsoft.Insights/diagnosticSettings hacia Log Analytics, Storage o Event Hub y verificar la i'
    'ngesta.", "business_impact": "Sin registros diagn\\u00f3sticos habilitados se reduce la trazabilidad '
    'de eventos de control plane, jobs y accesos.", "learn_url": "https://learn.microsoft.com/en-us/azure'
    '/databricks/admin/account-settings/audit-logs"}, {"rule_id": "C09", "reference_id": "DBX-WAF-SEC-06"'
    ', "test": "pat_token_governance", "level": "workspace", "area": "security", "pillar": "security", "s'
    'everity": "medium", "effort": "low", "title": "Gobernanza de Personal Access Tokens (PAT) en workspa'
    'ce-conf", "recommendation": "Revisar enableTokensConfig y priorizar autenticaci\\u00f3n OAuth M2M o i'
    'dentidades administradas de Microsoft Entra frente a PATs duraderos.", "business_impact": "Tokens pe'
    'rsonales sin control de emisi\\u00f3n o expiraci\\u00f3n incrementan el riesgo de credenciales persist'
    'entes.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/security/auth/api-access-p'
    'ermissions"}, {"rule_id": "C10", "reference_id": "DBX-WAF-GOV-01", "test": "default_catalog_unity", '
    '"level": "workspace", "area": "best_practices", "pillar": "operations", "severity": "medium", "effor'
    't": "medium", "title": "Cat\\u00e1logo predeterminado en Unity Catalog frente a Hive heredado", "reco'
    'mmendation": "Configurar UnityCatalog como cat\\u00e1logo predeterminado y evitar almacenar datos de '
    'negocio en el DBFS root o hive_metastore.", "business_impact": "El uso de hive_metastore y DBFS root'
    ' dificulta el control de acceso unificado y el linaje de datos.", "learn_url": "https://learn.micros'
    'oft.com/en-us/azure/databricks/data-governance/unity-catalog/best-practices"}, {"rule_id": "C11", "r'
    'eference_id": "DBX-WAF-SEC-07", "test": "global_init_scripts", "level": "workspace", "area": "securi'
    'ty", "pillar": "security", "severity": "low", "effort": "low", "title": "Higiene y revisi\\u00f3n de '
    'Global Init Scripts", "recommendation": "Minimizar o auditar los global init scripts habilitados y p'
    'referir pol\\u00edticas de cl\\u00faster o scripts con alcance de unidad en Unity Catalog.", "business'
    '_impact": "Los global init scripts se ejecutan en todos los cl\\u00fasteres del workspace y pueden in'
    'troducir dependencias ocultas o superficie de fallo.", "learn_url": "https://learn.microsoft.com/en-'
    'us/azure/databricks/init-scripts/global"}, {"rule_id": "C12", "reference_id": "DBX-WAF-OPS-02", "tes'
    't": "advisor", "level": "workspace", "area": "optimization", "pillar": "operations", "severity": "lo'
    'w", "effort": "low", "title": "Revisi\\u00f3n de recomendaciones cacheadas de Azure Advisor", "recomm'
    'endation": "Consultar las recomendaciones cacheadas de Azure Advisor para el workspace y recursos as'
    'ociados como insumo complementario.", "business_impact": "Ignorar alertas de plataforma puede retras'
    'ar la detecci\\u00f3n de mejoras de fiabilidad o coste.", "learn_url": "https://learn.microsoft.com/e'
    'n-us/azure/well-architected/service-guides/azure-databricks"}, {"rule_id": "W01", "reference_id": "D'
    'BX-WAF-COST-01", "test": "cluster_autotermination", "level": "workload", "area": "finops", "pillar":'
    ' "cost", "severity": "high", "effort": "low", "title": "Autoterminaci\\u00f3n configurada en cl\\u00fa'
    'steres interactivos All-Purpose", "recommendation": "Definir autotermination_minutes (por ejemplo <='
    ' 60 minutos) en todos los cl\\u00fasteres All-Purpose para evitar consumo DBU y VM en inactividad.", '
    '"business_impact": "Un cl\\u00faster interactivo sin autoterminaci\\u00f3n o con umbral excesivo manti'
    'ene nodos facturando sin carga activa.", "learn_url": "https://learn.microsoft.com/en-us/azure/datab'
    'ricks/compute/cluster-config-best-practices"}, {"rule_id": "W02", "reference_id": "DBX-WAF-GOV-02", '
    '"test": "cluster_policy_bound", "level": "workload", "area": "best_practices", "pillar": "cost", "se'
    'verity": "medium", "effort": "medium", "title": "Cl\\u00fasteres gobernados mediante Cluster Policy",'
    ' "recommendation": "Asociar policy_id a los cl\\u00fasteres para aplicar l\\u00edmites de tipo de inst'
    'ancia, autoterminaci\\u00f3n, versi\\u00f3n de runtime y etiquetas FinOps.", "business_impact": "Crear'
    ' cl\\u00fasteres sin pol\\u00edtica permite configuraciones no estandarizadas y sobrecostes accidental'
    'es.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/admin/clusters/policies"}, {"'
    'rule_id": "W03", "reference_id": "DBX-WAF-SEC-08", "test": "cluster_access_mode", "level": "workload'
    '", "area": "security", "pillar": "security", "severity": "high", "effort": "medium", "title": "Modo '
    'de acceso de c\\u00f3mputo compatible con aislamiento y Unity Catalog", "recommendation": "Configurar'
    ' data_security_mode en USER_ISOLATION (Standard/Shared) o SINGLE_USER (Dedicated) y evitar modos sin'
    ' aislamiento (NONE).", "business_impact": "Modos de acceso heredados o sin aislamiento impiden aplic'
    'ar controles de Unity Catalog o permiten acceso directo no gobernado.", "learn_url": "https://learn.'
    'microsoft.com/en-us/azure/databricks/compute/configure#access-mode"}, {"rule_id": "W04", "reference_'
    'id": "DBX-WAF-OPS-03", "test": "cluster_runtime_lts", "level": "workload", "area": "best_practices",'
    ' "pillar": "reliability", "severity": "medium", "effort": "medium", "title": "Versi\\u00f3n de Databr'
    'icks Runtime soportada (LTS / actual)", "recommendation": "Mantener spark_version en una versi\\u00f3'
    'n Long Term Support (LTS) vigente (por ejemplo 13.3 LTS, 14.3 LTS, 15.4 LTS o superior).", "business'
    '_impact": "Versiones antiguas de Databricks Runtime pierden soporte, parches de seguridad y optimiza'
    'ciones de Photon/Delta.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/release-n'
    'otes/runtime/"}, {"rule_id": "W05", "reference_id": "DBX-WAF-PERF-01", "test": "cluster_autoscaling_'
    'or_pool", "level": "workload", "area": "optimization", "pillar": "performance", "severity": "low", "'
    'effort": "low", "title": "Escalado din\\u00e1mico (Autoscale) o uso de Instance Pool en cl\\u00fastere'
    's", "recommendation": "Evaluar autoscale (min_workers/max_workers) o vinculaci\\u00f3n a instance_poo'
    'l_id para adaptar capacidad a variaciones de carga.", "business_impact": "Un n\\u00famero fijo de wor'
    'kers sin pool puede infrautilizar recursos en valles o limitar concurrencia en picos.", "learn_url":'
    ' "https://learn.microsoft.com/en-us/azure/databricks/compute/cluster-config-best-practices#autoscali'
    'ng"}, {"rule_id": "W06", "reference_id": "DBX-WAF-COST-02", "test": "job_uses_job_compute", "level":'
    ' "workload", "area": "finops", "pillar": "cost", "severity": "high", "effort": "medium", "title": "J'
    'obs programados ejecutando en Job Compute o Serverless en lugar de All-Purpose", "recommendation": "'
    'Migrar las tareas de Jobs que apuntan a existing_cluster_id hacia job_cluster_key o c\\u00f3mputo Ser'
    'verless de Jobs.", "business_impact": "Ejecutar jobs automatizados sobre cl\\u00fasteres All-Purpose '
    'consume tarifas DBU m\\u00e1s altas y acopla fallos entre cargas.", "learn_url": "https://learn.micro'
    'soft.com/en-us/azure/well-architected/service-guides/azure-databricks#cost-optimization"}, {"rule_id'
    '": "W07", "reference_id": "DBX-WAF-REL-01", "test": "job_resilience_settings", "level": "workload", '
    '"area": "best_practices", "pillar": "reliability", "severity": "medium", "effort": "low", "title": "'
    'Timeouts, reintentos o notificaciones en Jobs de orquestaci\\u00f3n", "recommendation": "Configurar t'
    'imeout_seconds, pol\\u00edticas de reintento y notificaciones o alertas en los Jobs cr\\u00edticos par'
    'a detectar ejecuciones colgadas o fallidas.", "business_impact": "Un job sin timeout ni alertas pued'
    'e quedar bloqueado consumiendo recursos o incumplir ventanas de datos sin aviso.", "learn_url": "htt'
    'ps://learn.microsoft.com/en-us/azure/databricks/jobs/configure-job"}, {"rule_id": "W08", "reference_'
    'id": "DBX-WAF-SEC-09", "test": "job_service_principal_run_as", "level": "workload", "area": "securit'
    'y", "pillar": "operations", "severity": "medium", "effort": "medium", "title": "Ejecuci\\u00f3n de Jo'
    'bs mediante Service Principal (run_as)", "recommendation": "Configurar run_as con un Service Princip'
    'al dedicado en lugar de una cuenta de usuario individual para evitar fallos ante bajas o cambios de '
    'rol.", "business_impact": "Los jobs ejecutados bajo identidad de usuario fallan si el usuario deja l'
    'a organizaci\\u00f3n o pierde permisos.", "learn_url": "https://learn.microsoft.com/en-us/azure/datab'
    'ricks/admin/users-groups/service-principals"}, {"rule_id": "W09", "reference_id": "DBX-WAF-COST-03",'
    ' "test": "sql_warehouse_autostop", "level": "workload", "area": "finops", "pillar": "cost", "severit'
    'y": "medium", "effort": "low", "title": "Auto-stop y arquitectura Serverless/Pro en SQL Warehouses",'
    ' "recommendation": "Configurar auto_stop_mins (<= 30 minutos) o usar SQL Warehouses Serverless para '
    'cargas BI e interactivas con demanda variable.", "business_impact": "Un SQL Warehouse sin auto-stop '
    'mantiene capacidad facturable activa fuera de las ventanas de consulta.", "learn_url": "https://lear'
    'n.microsoft.com/en-us/azure/databricks/compute/sql-warehouse/create"}, {"rule_id": "W10", "reference'
    '_id": "DBX-WAF-GOV-03", "test": "pipeline_unity_catalog", "level": "workload", "area": "best_practic'
    'es", "pillar": "operations", "severity": "medium", "effort": "medium", "title": "Pipelines declarati'
    'vos (Lakeflow / DLT) publicados en Unity Catalog", "recommendation": "Definir un cat\\u00e1logo de Un'
    'ity Catalog en los pipelines declarativos para asegurar linaje nativo y gobernanza de tablas.", "bus'
    'iness_impact": "Los pipelines publicados en hive_metastore quedan fuera del modelo centralizado de p'
    'ermisos y linaje.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/ldp/unity-catal'
    'og"}, {"rule_id": "G01", "reference_id": "DBX-WAF-GOV-04", "test": "uc_metastore_attached", "level":'
    ' "workspace", "area": "best_practices", "pillar": "security", "severity": "high", "effort": "high", '
    '"title": "Asignaci\\u00f3n de Metastore de Unity Catalog al workspace", "recommendation": "Vincular e'
    'l workspace a un Metastore regional de Unity Catalog para centralizar identidades, control de acceso'
    ', auditor\\u00eda y linaje.", "business_impact": "Sin Metastore adjunto no est\\u00e1n disponibles las'
    ' capacidades de gobierno unificado, ubicaciones externas ni tablas de sistema.", "learn_url": "https'
    '://learn.microsoft.com/en-us/azure/databricks/data-governance/unity-catalog/get-started"}, {"rule_id'
    '": "G02", "reference_id": "DBX-WAF-SEC-10", "test": "uc_storage_credential_mi", "level": "workspace"'
    ', "area": "security", "pillar": "security", "severity": "high", "effort": "medium", "title": "Storag'
    'e Credentials de Unity Catalog basadas en Managed Identity", "recommendation": "Usar Azure Managed I'
    'dentity (v\\u00eda Access Connector) en las Storage Credentials de Unity Catalog en lugar de secretos'
    ' de Service Principal.", "business_impact": "Las credenciales basadas en secretos requieren rotaci\\u'
    '00f3n manual y aumentan el riesgo ante filtraciones.", "learn_url": "https://learn.microsoft.com/en-'
    'us/azure/databricks/connect/unity-catalog/cloud-storage/storage-credentials"}, {"rule_id": "G03", "r'
    'eference_id": "DBX-WAF-GOV-05", "test": "uc_external_locations_governed", "level": "workspace", "are'
    'a": "security", "pillar": "security", "severity": "medium", "effort": "medium", "title": "External L'
    'ocations con Storage Credential v\\u00e1lida y rutas ADLS Gen2 expl\\u00edcitas", "recommendation": "V'
    'erificar que cada External Location enlace con una Storage Credential existente, utilice abfss:// y '
    'aplique vinculaci\\u00f3n por workspace cuando proceda.", "business_impact": "Ubicaciones externas hu'
    '\\u00e9rfanas o sin aislamiento pueden exponer contenedores compartidos entre entornos.", "learn_url"'
    ': "https://learn.microsoft.com/en-us/azure/databricks/data-governance/unity-catalog/best-practices#e'
    'xternal-locations"}, {"rule_id": "G04", "reference_id": "DBX-WAF-SEC-11", "test": "secret_scopes_key'
    'vault", "level": "workspace", "area": "security", "pillar": "security", "severity": "medium", "effor'
    't": "medium", "title": "Secret Scopes respaldados por Azure Key Vault", "recommendation": "Preferir '
    'Secret Scopes con backend AZURE_KEYVAULT frente a scopes locales DATABRICKS cuando se requiera gesti'
    '\\u00f3n centralizada de secretos.", "business_impact": "Los scopes locales de Databricks no se integ'
    'ran directamente con las pol\\u00edticas de rotaci\\u00f3n y auditor\\u00eda de Azure Key Vault.", "lea'
    'rn_url": "https://learn.microsoft.com/en-us/azure/databricks/security/secrets/secret-scopes"}, {"rul'
    'e_id": "G05", "reference_id": "DBX-WAF-REL-02", "test": "dependency_integrity", "level": "workspace"'
    ', "area": "best_practices", "pillar": "reliability", "severity": "high", "effort": "medium", "title"'
    ': "Integridad referencial del mapa de dependencias de Jobs, C\\u00f3mputo y Gobernanza", "recommendat'
    'ion": "Corregir referencias rotas en tareas de Jobs (cl\\u00fasteres eliminados, SQL Warehouses inexi'
    'stentes, pipelines o jobs hijos ausentes y credenciales no resueltas).", "business_impact": "Una dep'
    'endencia rota observada en la definici\\u00f3n de un Job provocar\\u00e1 fallos inmediatos de ejecuci\\'
    'u00f3n en producci\\u00f3n.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/jobs/c'
    'onfigure-job"}, {"rule_id": "G06", "reference_id": "DBX-WAF-GOV-06", "test": "runtime_table_lineage"'
    ', "level": "workspace", "area": "optimization", "pillar": "operations", "severity": "low", "effort":'
    ' "medium", "title": "Linaje din\\u00e1mico de tablas y columnas (system.access.table_lineage)", "reco'
    'mmendation": "Si se requiere linaje en tiempo de ejecuci\\u00f3n a nivel de tabla/columna, habilitar '
    'y consultar system.access.table_lineage en una sesi\\u00f3n autorizada sin arrancar c\\u00f3mputo auto'
    'm\\u00e1ticamente desde este colector.", "business_impact": "El an\\u00e1lisis de plano de control map'
    'ea dependencias declaradas, pero no las lecturas/escrituras SQL din\\u00e1micas dentro de notebooks."'
    ', "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/admin/system-tables/lineage"}, {"'
    'rule_id": "G07", "reference_id": "DBX-WAF-GOV-07", "test": "lakehouse_federation_connections", "leve'
    'l": "workspace", "area": "best_practices", "pillar": "operations", "severity": "low", "effort": "low'
    '", "title": "Gobernanza de conexiones externas en Unity Catalog (Lakehouse Federation)", "recommenda'
    'tion": "Inventariar las conexiones de Lakehouse Federation en Unity Catalog y verificar sus dependen'
    'cias de red y credenciales.", "business_impact": "Las conexiones federadas externas representan depe'
    'ndencias cr\\u00edticas hacia motores SQL o plataformas de terceros.", "learn_url": "https://learn.mi'
    'crosoft.com/en-us/azure/databricks/query-federation/"}, {"rule_id": "G08", "reference_id": "DBX-WAF-'
    'NET-03", "test": "outbound_control_plane_endpoints", "level": "workspace", "area": "best_practices",'
    ' "pillar": "reliability", "severity": "medium", "effort": "low", "title": "Visibilidad de dependenci'
    'as de red saliente (outboundNetworkDependenciesEndpoints)", "recommendation": "Contrastar las reglas'
    ' de firewall/UDR/NSG con la lista oficial de endpoints salientes requeridos por el workspace hacia e'
    'l plano de control.", "business_impact": "Bloquear dependencias salientes requeridas (Webapp, Contro'
    'l Plane NAT, Storage, Metastore, EventHub/ServiceBus) impide el arranque de cl\\u00fasteres.", "learn'
    '_url": "https://learn.microsoft.com/en-us/azure/databricks/administration-guide/cloud-configurations'
    '/azure/udr"}, {"rule_id": "R01", "reference_id": "DBX-WAF-RES-01", "test": "storage_tls_and_public_b'
    'lob", "level": "resource", "area": "security", "pillar": "security", "severity": "high", "effort": "'
    'low", "title": "Cuentas de almacenamiento asociadas con HTTPS, TLS 1.2+ y sin acceso p\\u00fablico a '
    'blobs", "recommendation": "Exigir supportsHttpsTrafficOnly=true, minimumTlsVersion=TLS1_2 y allowBlo'
    'bPublicAccess=false en las cuentas ADLS Gen2 asociadas.", "business_impact": "Permitir tr\\u00e1fico '
    'no cifrado o acceso an\\u00f3nimo a contenedores expone activos del lakehouse.", "learn_url": "https:'
    '//learn.microsoft.com/en-us/azure/storage/blobs/security-recommendations"}, {"rule_id": "R02", "refe'
    'rence_id": "DBX-WAF-RES-02", "test": "storage_shared_key_and_network", "level": "resource", "area": '
    '"security", "pillar": "security", "severity": "medium", "effort": "medium", "title": "Restricci\\u00f'
    '3n de Shared Key y acceso de red en cuentas de almacenamiento asociadas", "recommendation": "Evaluar'
    ' la deshabilitaci\\u00f3n de allowSharedKeyAccess y restringir publicNetworkAccess en cuentas ADLS Ge'
    'n2 gobernadas por Entra ID / Unity Catalog.", "business_impact": "Las claves compartidas de cuenta e'
    'luden los controles granulares de identidad de Microsoft Entra y Unity Catalog.", "learn_url": "http'
    's://learn.microsoft.com/en-us/azure/storage/common/shared-key-authorization-prevent"}, {"rule_id": "'
    'R03", "reference_id": "DBX-WAF-RES-03", "test": "keyvault_rbac_and_purge", "level": "resource", "are'
    'a": "security", "pillar": "security", "severity": "medium", "effort": "medium", "title": "Autorizaci'
    '\\u00f3n RBAC y protecci\\u00f3n contra purga en Key Vaults asociados", "recommendation": "Habilitar e'
    'nableRbacAuthorization y enablePurgeProtection en los Key Vaults vinculados a Secret Scopes o claves'
    ' CMK del workspace.", "business_impact": "Sin protecci\\u00f3n contra purga, la eliminaci\\u00f3n acci'
    'dental o maliciosa de una clave CMK o secreto puede ser irreversible.", "learn_url": "https://learn.'
    'microsoft.com/en-us/azure/key-vault/general/security-features"}, {"rule_id": "R04", "reference_id": '
    '"DBX-WAF-RES-04", "test": "nsg_exposure", "level": "resource", "area": "security", "pillar": "securi'
    'ty", "severity": "high", "effort": "medium", "title": "Exposici\\u00f3n de puertos administrativos de'
    'sde Internet en NSG asociados", "recommendation": "Eliminar o restringir reglas Inbound Allow desde '
    'Internet (0.0.0.0/0, *, Internet) hacia SSH (22), RDP (3389) o todos los puertos en subredes del wor'
    'kspace.", "business_impact": "Reglas de entrada abiertas desde Internet hacia las subredes de cl\\u00'
    'faster violan el aislamiento del plano de datos.", "learn_url": "https://learn.microsoft.com/en-us/a'
    'zure/databricks/security/network/classic/vnet-inject"}, {"rule_id": "R05", "reference_id": "DBX-WAF-'
    'RES-05", "test": "private_endpoint_approved", "level": "resource", "area": "best_practices", "pillar'
    '": "reliability", "severity": "medium", "effort": "low", "title": "Estado aprobado en conexiones Pri'
    'vate Endpoint asociadas", "recommendation": "Confirmar que todas las conexiones Private Endpoint aso'
    'ciadas al workspace o recursos vinculados est\\u00e9n en estado Approved.", "business_impact": "Un Pr'
    'ivate Endpoint en estado Pending, Rejected o Disconnected interrumpe la conectividad privada previst'
    'a.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/security/network/classic/priva'
    'te-link"}, {"rule_id": "R06", "reference_id": "DBX-WAF-COST-04", "test": "cost_attribution", "level"'
    ': "workspace", "area": "finops", "pillar": "cost", "severity": "low", "effort": "medium", "title": "'
    'Atribuci\\u00f3n de costes reales (ActualCost) y granularidad DBU por carga", "recommendation": "Comb'
    'inar los costes reales ARM observados con el etiquetado de cl\\u00fasteres/jobs y la tabla system.bil'
    'ling.usage para atribuir consumo DBU por equipo o pipeline.", "business_impact": "ActualCost a nivel'
    ' de ResourceId de Azure no desglosa por s\\u00ed solo el consumo interno de cada Job, SQL Warehouse o'
    ' usuario.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/admin/system-tables/bil'
    'ling"}]}'
))
HTML_TEMPLATE = (
    '<!doctype html>\n<!--\nTHESIS: An offline Lakehouse consulting dossier connects dated Azure Databricks'
    ' dependency and configuration evidence to human engineering decisions without fabricating lineage or'
    ' savings.\nOWN-WORLD: Azure SRE Agent report family (slim bar, verdict-first navy hero, overlapping K'
    'PI cards, white cards on a light ground) framed by corporate navy/steel (#003865, #0066a1) and the D'
    'atabricks lava/teal ribbon (#ff3621, #00875a); colour never substitutes for evidence.\nSTORY: Read th'
    'e verdict and coverage first, confirm workspace identity and provenance, inspect OBSERVED vs INFERRE'
    'D vs UNKNOWN dependencies, drill into workloads/Unity Catalog, then act on the prioritised plan and '
    'check the source ledger.\n-->\n<html lang="es-ES">\n<head>\n<meta charset="utf-8">\n<meta name="viewport"'
    ' content="width=device-width,initial-scale=1">\n<meta http-equiv="Content-Security-Policy" content="d'
    "efault-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; font-src da"
    'ta:; connect-src \'none\'; base-uri \'none\'; form-action \'none\'; object-src \'none\'">\n<meta name="color-'
    'scheme" content="light dark">\n<title>Revisión Azure Databricks | Mapa de dependencias y configuració'
    'n</title>\n<style>\n:root{\ncolor-scheme:light;\n--brand-navy: #003865; --brand-lava: #ff3621; --brand-s'
    'teel: #0066a1; --brand-teal: #00875a;\n--paper:#f2f5f8;--surface:#ffffff;--soft:#eef2f6;--hover:#f6f9'
    'fc;\n--ink:#16212c;--title:#002b4e;--muted:#4f5d6b;--line:#dde3ea;--line2:#c2ccd6;\n--link:#0058a3;--f'
    'ocus:#0b6bcb;--sel:#cfe3f7;--chart:#0066a1;--chart-2:#8fb3d3;--edge:#4d7aa3;\n--bar-bg:#ffffff;--bar-'
    'hover:#eef2f6;--btn:#003865;--btn-hover:#002848;--btn-ink:#ffffff;\n--hero-a:#003865;--hero-b:#00223c'
    ';--hero-muted:#c3d5e8;--hero-line:rgba(255,255,255,.24);\n--up-ink:#b42318;--down-ink:#067647;\n--shad'
    'ow:0 1px 2px rgba(16,24,40,.05),0 10px 28px rgba(16,24,40,.07);\n--crit-ink:#b42318;--crit-bg:#fee4e2'
    ';--crit-bar:#d92d20;\n--high-ink:#b93815;--high-bg:#ffead5;--high-bar:#ef6820;\n--med-ink:#93370d;--me'
    'd-bg:#fef0c7;--med-bar:#f79009;\n--low-ink:#175cd3;--low-bg:#d1e9ff;--low-bar:#2e90fa;\n--info-ink:#34'
    '4054;--info-bg:#eaecf0;--info-bar:#98a2b3;\n--ok-ink:#067647;--ok-bg:#dcfae6;--ok-bar:#17b26a;\n--obs-'
    'ink:#00603f;--obs-bg:#ddf4ea;--obs-line:#00875a;\n--inf-ink:#8a4b00;--inf-bg:#fff1d6;--inf-line:#c777'
    '00;\n--unk-ink:#475467;--unk-bg:#eaecf0;--unk-line:#98a2b3;\n}\n:root[data-theme="dark"]{\ncolor-scheme:'
    'dark;\n--paper:#0d141b;--surface:#15202a;--soft:#1c2834;--hover:#19242f;\n--ink:#e6edf3;--title:#f1f6f'
    'b;--muted:#a9b7c5;--line:#26333f;--line2:#3a4a5a;\n--link:#8cc8ff;--focus:#8cc8ff;--sel:#24476b;--cha'
    'rt:#6fb6f0;--chart-2:#3f6d94;--edge:#7aa7cf;\n--up-ink:#ffb4ab;--down-ink:#a6f4c5;\n--bar-bg:#101920;-'
    '-bar-hover:#1c2834;--btn:#8cc8ff;--btn-hover:#a9d6ff;--btn-ink:#0b1620;\n--hero-a:#0a2742;--hero-b:#0'
    '61626;--hero-muted:#bdd0e3;\n--shadow:0 1px 2px rgba(0,0,0,.35),0 10px 28px rgba(0,0,0,.35);\n--crit-i'
    'nk:#ffb4ab;--crit-bg:#4a1c1a;--high-ink:#ffc29e;--high-bg:#4a2614;\n--med-ink:#fedf89;--med-bg:#45330'
    'f;--low-ink:#a8d4ff;--low-bg:#13304f;\n--info-ink:#d0d5dd;--info-bg:#2a3441;--ok-ink:#a6f4c5;--ok-bg:'
    '#133a28;\n--obs-ink:#8ce9bf;--obs-bg:#12382a;--inf-ink:#f5d875;--inf-bg:#3d3216;--unk-ink:#cbd5e1;--u'
    'nk-bg:#2a3441;\n}\n*{box-sizing:border-box}\nhtml{scroll-padding-top:78px;-webkit-text-size-adjust:100%'
    ';scrollbar-color:var(--line2) var(--paper)}\nbody{margin:0;background:var(--paper);color:var(--ink);f'
    'ont:15px/1.55 "Segoe UI",system-ui,-apple-system,sans-serif;font-variant-numeric:tabular-nums;overfl'
    'ow-wrap:break-word}\n::selection{background:var(--sel);color:var(--ink)}\n[hidden]{display:none !impor'
    'tant}\na{color:var(--link);text-underline-offset:3px}\nbutton,input,select{font:inherit;color:inherit}'
    '\n:focus-visible{outline:3px solid var(--focus);outline-offset:2px}\n.sr{position:absolute;width:1px;h'
    'eight:1px;margin:-1px;padding:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}\n.ski'
    'p{position:absolute;left:16px;top:-100px;z-index:60;padding:10px 14px;background:var(--surface);colo'
    'r:var(--ink);border:2px solid var(--focus);border-radius:8px}\n.skip:focus{top:10px}\nsvg.i{width:16px'
    ';height:16px;flex:none;fill:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-li'
    'nejoin:round}\n.bar{position:sticky;top:0;z-index:30;display:flex;align-items:center;gap:14px;min-hei'
    'ght:60px;padding:8px clamp(14px,3vw,40px);background:var(--bar-bg);box-shadow:0 1px 0 var(--line)}\n.'
    'brand{display:flex;flex:none;align-items:center;gap:10px;color:var(--ink);text-decoration:none}\n.bra'
    'nd .mark{width:30px;height:30px;flex:none}\n.wordmark{font-weight:700;font-size:16.5px;letter-spacing'
    ':-.01em;white-space:nowrap;color:var(--title)}\n.product{font-size:13.5px;color:var(--muted);white-sp'
    'ace:nowrap;padding-left:10px;border-left:1px solid var(--line2)}\n.bar-nav{display:flex;gap:2px;margi'
    'n-left:6px;min-width:0;overflow:hidden}\n.bar-nav a{color:var(--muted);text-decoration:none;font-size'
    ':14px;font-weight:600;padding:8px 9px;border-radius:8px;white-space:nowrap}\n.bar-nav a:hover,.bar-na'
    'v a[aria-current="true"]{background:var(--bar-hover);color:var(--title)}\n.acts{margin-left:auto;disp'
    'lay:flex;align-items:center;gap:8px}\n.tag{font-size:12.5px;font-weight:600;color:var(--muted);border'
    ':1px solid var(--line2);border-radius:999px;padding:5px 11px;white-space:nowrap}\n.btn{display:inline'
    '-flex;align-items:center;justify-content:center;gap:8px;min-height:40px;padding:0 15px;border:1px so'
    'lid transparent;border-radius:10px;background:var(--btn);color:var(--btn-ink);font-weight:600;font-s'
    'ize:14px;cursor:pointer;white-space:nowrap;text-decoration:none;list-style:none}\n.btn:hover{backgrou'
    'nd:var(--btn-hover)}\n.btn.ghost{background:var(--surface);color:var(--ink);border-color:var(--line2)'
    '}\n.btn.ghost:hover{background:var(--bar-hover)}\n.btn.icon{width:40px;padding:0}\n.btn.sm{min-height:3'
    '4px;padding:0 12px;font-size:13px}\nsummary.btn::-webkit-details-marker{display:none}\n#theme-toggle .'
    'sun,#theme-toggle[aria-pressed="true"] .moon{display:none}\n#theme-toggle[aria-pressed="true"] .sun{d'
    'isplay:block}\n.menu{position:relative}\n.menu-pop{position:absolute;right:0;top:calc(100% + 6px);z-in'
    'dex:40;min-width:260px;display:grid;gap:2px;padding:6px;background:var(--surface);border:1px solid v'
    'ar(--line);border-radius:12px;box-shadow:var(--shadow)}\n.menu-pop button,.menu-pop a{display:block;w'
    'idth:100%;padding:9px 12px;border:0;border-radius:8px;background:transparent;color:var(--ink);text-a'
    'lign:left;text-decoration:none;font-size:14px;font-weight:600;cursor:pointer}\n.menu-pop button:hover'
    ',.menu-pop a:hover{background:var(--soft)}\n.menu-pop small{display:block;font-weight:400;color:var(-'
    '-muted);font-size:12.5px}\n.toc{display:none}\n.brand-ribbon{display:flex;height:5px}\n.brand-ribbon sp'
    'an{flex:1}\n.brand-ribbon .navy{background:var(--brand-navy)}\n.brand-ribbon .lava{background:var(--br'
    'and-lava)}\n.brand-ribbon .steel{background:var(--brand-steel)}\n.brand-ribbon .teal{background:var(--'
    'brand-teal)}\nselect,input[type="search"]{min-height:40px;max-width:100%;padding:0 12px;border:1px so'
    'lid var(--line2);border-radius:10px;background:var(--surface);color:var(--ink)}\ninput[type="search"]'
    '::placeholder{color:var(--muted);opacity:1}\nselect:focus-visible,input:focus-visible{outline:3px sol'
    'id var(--focus);outline-offset:1px}\n.multi-band{background:var(--surface);border-bottom:1px solid va'
    'r(--line)}\n.band-in{max-width:1400px;margin:0 auto;padding:12px clamp(14px,3vw,40px);display:flex;fl'
    'ex-wrap:wrap;gap:10px 24px;align-items:center;justify-content:space-between;font-size:14px}\n.band-in'
    ' p{margin:0;color:var(--muted)}\n.band-in b{color:var(--ink)}\n.ws-select{display:flex;align-items:cen'
    'ter;gap:10px;font-weight:600}\n.hero{position:relative;background:linear-gradient(150deg,var(--hero-a'
    ') 0%,var(--hero-b) 100%);color:#ffffff;padding:clamp(28px,4.2vw,52px) clamp(14px,3vw,40px) 104px}\n.h'
    'ero-in{max-width:1320px;margin:0 auto;display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:24p'
    'x 52px;align-items:start}\n.hero h1{margin:0 0 14px;font-size:clamp(28px,3vw,44px);line-height:1.12;f'
    'ont-weight:700;letter-spacing:-.02em;text-wrap:balance;color:#ffffff}\n.lead{margin:0;max-width:72ch;'
    'font-size:17px;line-height:1.55;color:var(--hero-muted)}\n.lead b{color:#ffffff;font-weight:700}\n.met'
    'a{display:flex;flex-wrap:wrap;gap:8px;margin-top:20px}\n.meta span{font-size:12.5px;padding:5px 11px;'
    'border-radius:999px;border:1px solid var(--hero-line);color:var(--hero-muted);white-space:nowrap}\n.m'
    'eta b{color:#ffffff;font-weight:600}\n.meta span.on{background:rgba(255,255,255,.12);border-color:rgb'
    'a(255,255,255,.45);color:#ffffff;font-weight:700;letter-spacing:.02em}\n.hero-side{display:grid;gap:1'
    '4px}\n.plaque-k{margin:0 0 6px;font-size:12.5px;color:var(--hero-muted)}\n.brand-plaque{color-scheme:o'
    'nly light;display:flex;align-items:center;justify-content:center;min-height:64px;padding:10px 16px;b'
    'order-radius:12px;background:#ffffff;color:#334155}\n.brand-plaque img{display:block;max-width:100%;m'
    'ax-height:44px;object-fit:contain}\n.brand-placeholder{font-size:14px;font-weight:700;letter-spacing:'
    '.16em;color:#334155}\n.client-name{margin:6px 0 0;font-size:14px;font-weight:600;color:#ffffff}\n.sign'
    'al{padding:18px 20px;border-radius:16px;background:rgba(255,255,255,.07);border:1px solid var(--sig-'
    'line)}\n.signal .k{font-size:13px;font-weight:600;color:var(--hero-muted)}\n.signal b{display:block;ma'
    'rgin-top:4px;font-size:26px;line-height:1.15;font-weight:700;color:var(--sig-ink)}\n.signal p{margin:'
    '8px 0 0;font-size:14px;color:var(--hero-muted)}\n.signal.crit{--sig-ink:#ffb4ab;--sig-line:rgba(255,1'
    '80,171,.55)}\n.signal.warn{--sig-ink:#fedf89;--sig-line:rgba(254,223,137,.5)}\n.signal.act{--sig-ink:#'
    'fdb022;--sig-line:rgba(253,176,34,.5)}\n.signal.ok{--sig-ink:#a6f4c5;--sig-line:rgba(166,244,197,.45)'
    '}\n.signal.info{--sig-ink:#e4e7ec;--sig-line:rgba(255,255,255,.35)}\n.dist{grid-column:1 / -1}\n.dist-h'
    'ead{display:flex;flex-wrap:wrap;justify-content:space-between;gap:4px 16px;margin-bottom:8px;font-si'
    'ze:13.5px;color:var(--hero-muted)}\n.dist-head b,.legend b{color:#ffffff}\n.track{display:flex;height:'
    '14px;border-radius:999px;overflow:hidden;background:rgba(255,255,255,.16)}\n.track i{display:block;he'
    'ight:100%}\n.legend{display:flex;flex-wrap:wrap;gap:6px 20px;margin-top:10px;font-size:13.5px;color:v'
    'ar(--hero-muted)}\n.legend span{display:inline-flex;align-items:center;gap:7px}\n.legend i{display:inl'
    'ine-block;width:10px;height:10px;border-radius:3px}\n.page{max-width:1400px;margin:0 auto;padding:0 c'
    'lamp(14px,3vw,40px) 56px}\n.kpis{position:relative;z-index:2;display:grid;grid-template-columns:repea'
    't(auto-fit,minmax(min(100%,178px),1fr));gap:14px;margin-top:-62px}\n.kpi{min-width:0;padding:18px 20p'
    'x;background:var(--surface);border:1px solid var(--line);border-radius:16px;box-shadow:var(--shadow)'
    '}\n.kpi .v{display:flex;flex-wrap:wrap;align-items:baseline;gap:0 5px;font-size:33px;line-height:1.05'
    ';font-weight:700;letter-spacing:-.02em;color:var(--title)}\n.kpi .v small{font-size:15px;font-weight:'
    '600;letter-spacing:0;color:var(--muted)}\n.kpi .l{margin-top:9px;font-size:14px;font-weight:600}\n.kpi'
    ' .s{margin-top:3px;font-size:13px;color:var(--muted)}\n.sim,.note{display:flex;gap:10px;align-items:f'
    'lex-start;margin-top:16px;padding:11px 16px;border-radius:12px;font-size:14px}\n.sim{background:repea'
    'ting-linear-gradient(135deg,#fffaeb 0 12px,#fef0c7 12px 24px);border:1px solid #fedf89;color:#7a2e0e'
    ';font-weight:600}\n.note{background:var(--surface);border:1px solid var(--line);color:var(--ink)}\n.si'
    'm svg.i,.note svg.i{width:18px;height:18px;margin-top:1px}\n.note svg.i{color:var(--med-bar)}\n.chapte'
    'r{margin-top:48px;scroll-margin-top:78px}\n.sh{margin-bottom:16px}\n.sh h2{margin:0;font-size:23px;lin'
    'e-height:1.3;font-weight:700;letter-spacing:-.01em;color:var(--title);text-wrap:balance}\n.sh p{margi'
    'n:6px 0 0;max-width:75ch;font-size:14.5px;color:var(--muted)}\n.grid2{display:grid;grid-template-colu'
    'mns:repeat(auto-fit,minmax(min(100%,440px),1fr));gap:16px}\n.stack-gap>* + *{margin-top:16px}\n.card{m'
    'in-width:0;padding:20px 22px;background:var(--surface);border:1px solid var(--line);border-radius:16'
    'px;box-shadow:var(--shadow)}\n.card h3{margin:0 0 4px;font-size:17px;line-height:1.3;font-weight:700;'
    'color:var(--title)}\n.card .sub{margin:0 0 14px;font-size:13.5px;color:var(--muted)}\n.card.flat{paddi'
    'ng:0;overflow:hidden}\n.card-head{display:flex;flex-wrap:wrap;align-items:baseline;justify-content:sp'
    'ace-between;gap:4px 16px;padding:18px 22px 12px}\n.card-head h3{margin:0}\n.card-head p{margin:0;font-'
    'size:13.5px;color:var(--muted)}\n.facts{display:grid;grid-template-columns:repeat(auto-fit,minmax(min'
    '(100%,250px),1fr));gap:16px 28px;margin:0}\n.facts dt{margin-bottom:3px;font-size:12.5px;color:var(--'
    'muted)}\n.facts dd{margin:0;font-size:14.5px;font-weight:600;min-width:0}\n.facts dd small{display:blo'
    'ck;font-weight:400;color:var(--muted);font-size:12.5px}\n.plist,.msgs{list-style:none;margin:0;paddin'
    'g:0}\n.msgs li{position:relative;padding:9px 0 9px 18px;border-top:1px solid var(--line);font-size:14'
    '.5px}\n.msgs li:first-child{border-top:0;padding-top:2px}\n.msgs li::before{content:"";position:absolu'
    'te;left:2px;top:17px;width:6px;height:6px;border-radius:50%;background:var(--chart)}\n.msgs li:first-'
    'child::before{top:10px}\n.plist li{display:grid;grid-template-columns:auto minmax(0,1fr);gap:4px 12px'
    ';padding:12px 0;border-top:1px solid var(--line)}\n.plist li:first-child{border-top:0;padding-top:0}\n'
    '.plist .pt{font-weight:600}\n.plist .pm{grid-column:2;font-size:13.5px;color:var(--muted)}\n.bars{disp'
    'lay:grid;gap:12px}\n.brow{display:grid;grid-template-columns:minmax(120px,36%) minmax(0,1fr) auto;gap'
    ':12px;align-items:center;font-size:14px}\n.brow .bl{min-width:0}\n.brow .bl small,.brow .bv small{disp'
    'lay:block;font-size:12.5px;font-weight:400;color:var(--muted)}\n.bt{height:10px;border-radius:999px;o'
    'verflow:hidden;background:var(--soft)}\n.bt i{display:block;height:100%;min-width:2px;border-radius:9'
    '99px;background:var(--chart)}\n.brow .bv{text-align:right;font-weight:700;white-space:nowrap}\n.brow.n'
    'a .bv{font-weight:600;color:var(--muted)}\n#check-status .brow{grid-template-columns:minmax(150px,46%'
    ') minmax(0,1fr) auto}\n.wrap,.graph{overflow-x:auto;border-top:1px solid var(--line);background:linea'
    'r-gradient(90deg,var(--surface) 30%,rgba(255,255,255,0)) left / 36px 100% no-repeat local,linear-gra'
    'dient(270deg,var(--surface) 30%,rgba(255,255,255,0)) right / 36px 100% no-repeat local,radial-gradie'
    'nt(farthest-side at 0 50%,rgba(16,24,40,.18),rgba(16,24,40,0)) left / 14px 100% no-repeat scroll,rad'
    'ial-gradient(farthest-side at 100% 50%,rgba(16,24,40,.18),rgba(16,24,40,0)) right / 14px 100% no-rep'
    'eat scroll}\ntable{width:100%;border-collapse:collapse;font-size:14px;text-align:left}\nth{padding:10p'
    'x 14px;background:var(--soft);color:var(--title);font-size:12px;font-weight:700;letter-spacing:.04em'
    ';text-transform:uppercase;white-space:nowrap;border-bottom:1px solid var(--line);vertical-align:bott'
    'om}\ntd{padding:11px 14px;border-bottom:1px solid var(--line);vertical-align:top}\ntbody tr:last-child'
    ' td{border-bottom:0}\ntbody tr:hover{background:var(--hover)}\ntable.dense{font-size:13.5px}\n.dense td'
    ',.dense th{padding-left:11px;padding-right:11px}\ntd.n,th.n{text-align:right;white-space:nowrap}\ntd.n'
    'w{white-space:nowrap}\ntd.w{min-width:240px}\ntd.empty-cell{color:var(--muted)}\ntr.pg{display:none}\n.t'
    'h-sort{all:unset;display:inline-flex;align-items:center;gap:4px;cursor:pointer}\n.th-sort:focus-visib'
    'le{outline:3px solid var(--focus);outline-offset:2px;border-radius:4px}\n.th-sort::after{content:"";w'
    'idth:0;height:0;border:4px solid transparent;border-top-color:currentColor;opacity:.35;margin-top:4p'
    'x}\nth[aria-sort="ascending"] .th-sort::after{border-top-color:transparent;border-bottom-color:curren'
    'tColor;margin-top:-4px;opacity:1}\nth[aria-sort="descending"] .th-sort::after{opacity:1}\n.more-row{di'
    'splay:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:8px 12px;padding:12px;border'
    '-top:1px solid var(--line)}\n.more-note{font-size:13px;color:var(--muted)}\n.stack b{display:block;fon'
    't-weight:600}\n.stack small{display:block;font-size:12.5px;color:var(--muted)}\n.mono{font-family:ui-m'
    'onospace,"Cascadia Mono",Consolas,monospace;font-size:12.5px}\n.nw{white-space:nowrap}\n.muted{color:v'
    'ar(--muted)}\n.fd p,.fr p{margin:3px 0 0}\n.fd p{font-size:13.5px;color:var(--muted)}\n.res b{display:b'
    'lock;font-weight:600}\n.res small{display:block;font-size:12.5px;color:var(--muted)}\n.ext{display:inl'
    'ine-flex;align-items:center;gap:4px;margin-top:3px;font-size:13px;font-weight:600;white-space:nowrap'
    '}\n.ext svg.i{width:13px;height:13px}\n.chips{display:flex;flex-wrap:wrap;gap:5px;margin-top:6px}\n.chi'
    'ps span{padding:1px 8px;border-radius:7px;background:var(--soft);color:var(--muted);font-size:12px}\n'
    '.chips b{color:var(--ink);font-weight:600}\ndetails.json{margin-top:6px;font-size:12.5px}\ndetails.jso'
    'n summary{cursor:pointer;color:var(--link);font-weight:600}\ndetails.json pre{max-width:620px;max-hei'
    'ght:260px;overflow:auto;margin:6px 0 0;padding:10px;border-radius:8px;background:var(--soft);font:12'
    'px/1.45 ui-monospace,"Cascadia Mono",Consolas,monospace;white-space:pre}\n.pill{display:inline-flex;a'
    'lign-items:center;gap:6px;padding:2px 10px;border-radius:999px;font-size:12.5px;font-weight:700;line'
    '-height:1.6;white-space:nowrap}\n.pill::before{content:"";width:7px;height:7px;border-radius:50%;back'
    'ground:var(--d,currentColor)}\n.sev-critical{color:var(--crit-ink);background:var(--crit-bg);--d:var('
    '--crit-bar)}\n.sev-high{color:var(--high-ink);background:var(--high-bg);--d:var(--high-bar)}\n.sev-med'
    'ium{color:var(--med-ink);background:var(--med-bg);--d:var(--med-bar)}\n.sev-low{color:var(--low-ink);'
    'background:var(--low-bg);--d:var(--low-bar)}\n.sev-info,.tone-info{color:var(--info-ink);background:v'
    'ar(--info-bg);--d:var(--info-bar)}\n.tone-ok{color:var(--ok-ink);background:var(--ok-bg);--d:var(--ok'
    '-bar)}\n.tone-warn{color:var(--med-ink);background:var(--med-bg);--d:var(--med-bar)}\n.tone-crit{color'
    ':var(--crit-ink);background:var(--crit-bg);--d:var(--crit-bar)}\n.cls-OBSERVED{color:var(--obs-ink);b'
    'ackground:var(--obs-bg);--d:var(--obs-line)}\n.cls-INFERRED{color:var(--inf-ink);background:var(--inf'
    '-bg);--d:var(--inf-line);outline:1px dashed var(--inf-line);outline-offset:-1px}\n.cls-UNKNOWN{color:'
    'var(--unk-ink);background:var(--unk-bg);--d:transparent}\n.cls-UNKNOWN::before{box-shadow:inset 0 0 0'
    ' 1.5px var(--unk-line)}\n.st{display:inline-flex;align-items:center;gap:7px;font-size:13.5px;font-wei'
    'ght:600;white-space:nowrap}\n.st::before{content:"";width:9px;height:9px;border-radius:50%;background'
    ':var(--d)}\n.st-failed{--d:var(--crit-bar)}\n.st-passed{--d:var(--ok-bar)}\n.st-not_evaluated{--d:var(-'
    '-info-bar)}\n.st-not_applicable{--d:transparent;color:var(--muted)}\n.st-not_applicable::before{box-sh'
    'adow:inset 0 0 0 2px var(--info-bar)}\n.tools{display:flex;flex-wrap:wrap;gap:10px 12px;align-items:f'
    'lex-end;padding:0 22px 16px}\n.field{display:grid;gap:4px;min-width:0;font-size:12.5px;font-weight:60'
    '0;color:var(--muted)}\n.field select,.field input{color:var(--ink);font-size:14px;font-weight:400}\n.f'
    'ield.grow{flex:1 1 220px}\n.field.grow input{width:100%}\n.cls-sum{display:flex;flex-wrap:wrap;gap:8px'
    ';margin:-4px 0 16px}\n.tabs{display:inline-flex;flex-wrap:wrap;gap:4px;margin:0 0 16px;padding:4px;ba'
    'ckground:var(--soft);border:1px solid var(--line);border-radius:12px}\n.tabs button{min-height:40px;p'
    'adding:0 16px;border:0;border-radius:9px;background:transparent;color:var(--muted);font-size:14px;fo'
    'nt-weight:600;cursor:pointer}\n.tabs button:hover{color:var(--title)}\n.tabs button[aria-selected="tru'
    'e"]{background:var(--surface);color:var(--title);box-shadow:0 1px 2px rgba(16,24,40,.1),0 0 0 1px va'
    'r(--line)}\n.graph{padding:4px 22px 6px}\n.graph svg{display:block;width:100%;min-width:760px;height:a'
    'uto}\n.g-col{fill:var(--muted);font-size:11px;font-weight:700;letter-spacing:.06em;text-transform:upp'
    'ercase}\n.g-node rect{fill:var(--surface);stroke:var(--line2);stroke-width:1.2}\n.g-node.ws rect{strok'
    'e:var(--brand-steel);stroke-width:2}\n.g-node.inf rect{fill:var(--inf-bg);stroke:var(--inf-line);stro'
    'ke-dasharray:5 4}\n.g-l1{fill:var(--ink);font-size:12.5px;font-weight:600}\n.g-l2{fill:var(--muted);fo'
    'nt-size:11px}\n.edge{fill:none;stroke:var(--edge);stroke-width:1.3;opacity:.75}\n.edge.inf{stroke:var('
    '--inf-line);stroke-dasharray:6 5;opacity:1}\n.arr.obs{fill:var(--edge)}\n.arr.inf{fill:var(--inf-line)'
    '}\n.g-legend{display:flex;flex-wrap:wrap;gap:6px 20px;align-items:center;padding:10px 22px 16px;font-'
    'size:13px;color:var(--muted)}\n.g-legend span{display:inline-flex;align-items:center;gap:8px}\n.g-lege'
    'nd svg{width:34px;height:10px}\n.ref-box rect{fill:var(--soft);stroke:var(--brand-steel);stroke-width'
    ':1.5;stroke-dasharray:6 4}\n.ref-t{fill:var(--title);font-size:13px;font-weight:700}\n.ref-s{fill:var('
    '--muted);font-size:11.5px}\n.ref-link{stroke:var(--brand-lava);stroke-width:2}\n.ref-flag rect{fill:va'
    'r(--high-bg)}\n.ref-flag text{fill:var(--high-ink);font-size:11px;font-weight:700;letter-spacing:.05e'
    'm}\n.ref-note{fill:var(--high-ink);font-size:12.5px;font-weight:600}\n.stat{font-size:34px;line-height'
    ':1.1;font-weight:700;letter-spacing:-.02em;color:var(--title);margin:6px 0 4px}\n.stat small{font-siz'
    'e:15px;font-weight:600;color:var(--muted);letter-spacing:0}\n.stat.na{font-size:24px}\n.notes{margin:1'
    '2px 0 0;padding-left:18px;font-size:13px;color:var(--muted)}\n.notes li + li{margin-top:4px}\n.plan{di'
    'splay:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr));gap:16px;align-items:s'
    'tart}\n.steps{list-style:none;margin:12px 0 0;padding:0}\n.steps li{display:grid;grid-template-columns'
    ':28px minmax(0,1fr);gap:4px 12px;padding:12px 0;border-top:1px solid var(--line)}\n.steps .no{display'
    ':grid;place-items:center;width:28px;height:28px;border-radius:50%;background:var(--btn);color:var(--'
    'btn-ink);font-size:13px;font-weight:700}\n.steps .sx{min-width:0}\n.steps .sx p{margin:4px 0 0;font-si'
    'ze:14px}\n.steps .sm{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center;margin-top:6px;font-'
    'size:12.5px;color:var(--muted)}\n.steps .sm .ext{margin-top:0}\n.empty{display:flex;gap:12px;align-ite'
    'ms:center;color:var(--muted);font-size:14px}\n.empty svg.i{width:22px;height:22px;color:var(--ok-bar)'
    '}\n.dl2{display:grid;grid-template-columns:minmax(150px,220px) minmax(0,1fr);gap:10px 20px;margin:0;f'
    'ont-size:14px}\n.dl2 dt{color:var(--muted)}\n.dl2 dd{margin:0}\n.dl2 ul{margin:0;padding-left:18px}\n.st'
    'ate-card{max-width:1320px;margin:28px auto;padding:20px 22px;border:1px solid var(--crit-bar);border'
    '-radius:16px;background:var(--crit-bg);color:var(--crit-ink)}\n.state-card h2{margin:0 0 6px;font-siz'
    'e:20px}\n.state-card p{margin:0;color:var(--ink)}\n.state-card dl{margin:12px 0 0;color:var(--ink)}\n.h'
    'ero h1,.sh h2,.signal b{font-family:var(--display,inherit)}\nhtml.brand-font .hero h1{font-weight:600'
    ';letter-spacing:0;font-size:clamp(32px,3.6vw,48px);line-height:1.08}\nhtml.brand-font .sh h2{font-wei'
    'ght:600;letter-spacing:0;font-size:27px}\nhtml.brand-font .signal b{font-weight:600;letter-spacing:0;'
    'font-size:28px}\n.client-logo{display:none}\nhtml.brand-bar .brand .mark,html.brand-bar .wordmark{disp'
    'lay:none}\nhtml.brand-bar .client-logo{display:block;height:30px;width:auto;max-width:200px}\nhtml.bra'
    'nd-bar .product{padding-left:16px;border-left-color:var(--line)}\nhtml.brand-bar .brand-ribbon,html.b'
    'rand-bar #plaque-block{display:none}\nhtml.brand-bar .bar{box-shadow:none;border-bottom:3px solid var'
    '(--brand-rule,var(--btn))}\nhtml.branded .foot{max-width:none;margin:0;padding:18px clamp(14px,3vw,40'
    'px) 28px;border-top:0;background:var(--foot-bg,transparent);color:var(--foot-ink,var(--muted))}\n.cos'
    't-head{display:grid;grid-template-columns:minmax(0,1.3fr) minmax(0,1fr);gap:22px 40px;align-items:st'
    'art}\n.cstats{display:grid;grid-template-columns:repeat(2,minmax(0,1fr));gap:20px 28px}\n.cstat .k{fon'
    't-size:13px;font-weight:600;color:var(--muted)}\n.cstat .n{margin-top:4px;font-size:30px;line-height:'
    '1.08;font-weight:700;letter-spacing:-.02em;color:var(--title);white-space:nowrap}\n.cstat .n small{ma'
    'rgin-left:5px;font-size:14px;font-weight:600;letter-spacing:0;color:var(--muted)}\n.cstat .d{margin-t'
    'op:5px;font-size:13px;color:var(--muted)}\n.up{color:var(--up-ink);font-weight:600}\n.down{color:var(-'
    '-down-ink);font-weight:600}\n.cost-trend h4{margin:0 0 10px;font-size:13px;font-weight:600;color:var('
    '--muted)}\n.mrow{display:grid;grid-template-columns:minmax(92px,auto) minmax(0,1fr) auto;gap:12px;ali'
    'gn-items:center;padding:6px 0;font-size:13.5px}\n.mrow .ml{font-weight:600;white-space:nowrap}\n.mrow '
    '.ml small{display:block;font-size:12px;font-weight:400;color:var(--muted)}\n.mrow .mv{text-align:righ'
    't;font-weight:700;white-space:nowrap}\n.strack{display:flex;height:14px;border-radius:999px;overflow:'
    'hidden;background:var(--soft)}\n.strack i{display:block;height:100%}\n.seg-dbu{background:var(--chart)'
    '}\n.seg-infra{background:var(--chart-2)}\n.mrow.partial .strack i{background-image:repeating-linear-gr'
    'adient(135deg,rgba(255,255,255,.5) 0 4px,rgba(255,255,255,0) 4px 8px)}\n.keys{display:flex;flex-wrap:'
    'wrap;gap:4px 16px;margin-top:8px;font-size:12.5px;color:var(--muted)}\n.keys span{display:inline-flex'
    ';align-items:center;gap:6px}\n.keys i{display:inline-block;width:10px;height:10px;border-radius:3px}\n'
    '.vm-sizes{margin-top:16px;padding-top:12px;border-top:1px solid var(--line);font-size:13px;color:var'
    '(--muted)}\n.vm-sizes .chips{margin-top:6px}\n.cost-tabs{margin:0 22px 14px}\n.movers{display:grid;grid'
    '-template-columns:repeat(auto-fit,minmax(min(100%,320px),1fr));gap:0 36px}\n.movers h4{margin:4px 0 2'
    'px;font-size:13px;font-weight:600;color:var(--muted)}\n.mover{display:grid;grid-template-columns:minm'
    'ax(0,1fr) auto;gap:2px 14px;padding:10px 0;border-top:1px solid var(--line);font-size:14px}\n.mover b'
    '{font-weight:600;overflow-wrap:anywhere}\n.mover .dv{text-align:right;font-weight:700;white-space:now'
    'rap}\n.mover small{font-size:12.5px;color:var(--muted)}\n.gapn{display:flex;flex-wrap:wrap;align-items'
    ':baseline;gap:4px 12px;margin:2px 0 14px}\n.gapn b{font-size:30px;line-height:1.1;font-weight:700;let'
    'ter-spacing:-.02em;color:var(--title)}\n.gapn span{font-size:14px;color:var(--muted)}\n.sav{font-weigh'
    't:700;white-space:nowrap}\n.sav small{display:block;font-size:12px;font-weight:400;color:var(--muted)'
    ';white-space:normal}\n.sav.nc{font-weight:600;color:var(--muted)}\n.legacy-sum{display:flex;flex-wrap:'
    'wrap;gap:6px 28px;align-items:baseline;padding:0 22px 14px}\n.legacy-sum .stat{margin:0}\n.legacy-sum '
    '.notes{margin:0;max-width:80ch}\n.sys-grid{display:grid;grid-template-columns:repeat(2,minmax(0,1fr))'
    ';gap:16px 40px;margin-top:20px}\n.sys-grid h4,.sys-h{margin:0 0 8px;font-size:13px;font-weight:600;co'
    'lor:var(--muted)}\n.sys-h{margin-top:14px}\n.sys-wrap{margin:0 -22px;border-bottom:1px solid var(--lin'
    'e)}\n#sec-finops .bars{grid-template-columns:minmax(120px,36%) minmax(0,1fr) auto;column-gap:12px}\n#s'
    'ec-finops .bars>*{grid-column:1 / -1}\n#sec-finops .bars>.brow{grid-template-columns:subgrid}\n.h3row{'
    'display:flex;flex-wrap:wrap;align-items:center;gap:6px 12px;margin-bottom:4px}\n.h3row h3{margin:0}\n@'
    'media (max-width:1400px){#workspace-error-view,#opening-state{margin:28px clamp(14px,3vw,40px)}}\n.fo'
    'ot{max-width:1320px;margin:0 auto;padding:20px 0 40px;border-top:1px solid var(--line);color:var(--m'
    'uted);font-size:13px}\n@media (max-width:1400px){.foot{margin:0 clamp(14px,3vw,40px)}}\n@media (max-wi'
    'dth:1360px){.bar-nav,.tag{display:none} .toc{display:block}}\n@media (max-width:1040px){.hero-in{grid'
    '-template-columns:1fr} .hero-side{grid-template-columns:repeat(auto-fit,minmax(min(100%,280px),1fr))'
    '} .product{display:none} .cost-head,.sys-grid{grid-template-columns:minmax(0,1fr)}}\n@media (max-widt'
    'h:720px){\n.btn .lbl{display:none}\n.btn{padding:0 11px}\n.acts{gap:6px}\n.hero{padding-bottom:92px}\n.le'
    'ad{font-size:16px}\n.brand-plaque{min-height:52px}\n.kpis{grid-template-columns:repeat(2,minmax(0,1fr)'
    ');gap:10px}\n.kpi{padding:14px 16px}\n.kpi .v{font-size:27px}\n.brow,#check-status .brow{grid-template-'
    'columns:minmax(0,1fr) auto}\n.brow .bt{grid-column:1 / -1;grid-row:2}\n.tools,.card-head,.g-legend{pad'
    'ding-left:16px;padding-right:16px}\n.graph{padding-left:16px;padding-right:16px}\n.card{padding:16px}\n'
    '.card.flat{padding:0}\n.dl2{grid-template-columns:1fr;gap:2px 0}\n.dl2 dd + dt{margin-top:10px}\n.cost-'
    'tabs{margin-left:16px;margin-right:16px}\n.sys-wrap{margin:0 -16px}\n#sec-finops .bars{grid-template-c'
    'olumns:minmax(0,1fr) auto}\n.legacy-sum{padding-left:16px;padding-right:16px}\n.cstats{gap:16px 18px}\n'
    '.cstat .n{font-size:25px}\nhtml.brand-font .hero h1{font-size:30px}\nhtml.brand-font .sh h2{font-size:'
    '24px}\n}\n@media (max-width:420px){.wordmark{font-size:15px} .brand .mark{width:26px;height:26px} .btn'
    '.icon,.acts .btn{width:38px;min-height:38px;padding:0}}\n@media (max-width:360px){.bar{gap:8px} .acts'
    '{gap:4px} .brand{flex:0 1 auto;min-width:0} .wordmark{overflow:hidden;text-overflow:ellipsis}}\n@medi'
    'a (prefers-reduced-motion:reduce){*{transition:none !important;scroll-behavior:auto !important}}\n@pa'
    'ge{size:A4;margin:14mm 12mm 16mm}\n@media print{\n*{-webkit-print-color-adjust:exact;print-color-adjus'
    't:exact}\nhtml,body{background:#ffffff;font-size:12px}\n.bar,.skip,.tools,.more-row,.tabs,.ws-select,d'
    'etails.json{display:none !important}\n.multi-band{border:0}\n.hero{padding:22px 24px 74px;border-radiu'
    's:14px}\n.hero-in{grid-template-columns:minmax(0,1fr) 210px;gap:14px 26px}\n.hero-side{grid-template-c'
    'olumns:1fr}\n.hero h1{font-size:25px}\n.lead{font-size:12.5px}\n.signal b{font-size:19px}\n.page{padding'
    ':0}\n.kpis{grid-template-columns:repeat(3,minmax(0,1fr));gap:10px;margin-top:-54px}\n.kpi{padding:12px'
    ' 14px;box-shadow:none}\n.kpi .v{font-size:24px}\n.card{box-shadow:none;break-inside:avoid}\n.card.flat{'
    'break-inside:auto}\n.grid2{grid-template-columns:1fr 1fr}\n.plan{grid-template-columns:1fr}\n.plan .car'
    'd{break-inside:auto}\n.steps .sx b,.plist .pt{font-size:12px}\n.steps .sx p,.msgs li,.brow{font-size:1'
    '1.5px}\n.plist .pm,.steps .sm,.brow small,.facts dt,.facts dd small{font-size:10.5px}\n.facts dd{font-'
    'size:12px}\n.chapter{margin-top:24px}\n.sh{break-after:avoid;break-inside:avoid}\n.card-head{display:bl'
    'ock;break-after:avoid;break-inside:avoid}\n.card-head p{margin-top:2px}\n.sh::after,.card-head::after{'
    'content:"";display:block;height:150px;margin-bottom:-150px}\n.sh p{font-size:12px}\ntr,.kpi,.signal,.b'
    'row,.steps li,.plist li{break-inside:avoid}\nthead{display:table-header-group}\ntr.pg{display:table-ro'
    'w !important}\n.wrap,.graph{overflow:visible;background:none}\ntable,table.dense{font-size:10.5px}\ntd,'
    'th,.dense td,.dense th{padding:5px 7px}\ntd{overflow-wrap:break-word}\ntd .mono,td.w,.chips span{overf'
    'low-wrap:anywhere}\ntd small,td p,td .ext,td .st,td .pill,.chips span,.card td small,.card td p{font-'
    'size:9.5px}\nth[data-label] .th-sort{display:none}\nth[data-label]::before{content:attr(data-label)}\nt'
    'd .pill{padding:1px 7px;gap:4px}\ntd .pill::before{width:5px;height:5px}\n.sh h2{font-size:18px}\n.card'
    ' h3{font-size:13.5px}\n.card .sub,.card-head p,.notes,.dl2{font-size:10.5px}\nth{font-size:9px;white-s'
    'pace:normal}\ntd.nw,td .nw{white-space:normal}\ntd.w{min-width:0}\n.mono{font-size:9.5px}\n.graph svg{mi'
    'n-width:0}\n[hidden].print-show{display:block !important}\na{color:inherit;text-decoration:none}\n.foot'
    '{padding:14px 0 0}\n.cost-head{grid-template-columns:1.25fr 1fr;gap:12px 24px}\n.cstat .n{font-size:20'
    'px}\n.cstat .d,.mrow,.mover,.keys,.vm-sizes{font-size:10.5px}\n.gapn b{font-size:20px}\n.sys-grid{grid-'
    'template-columns:1fr 1fr}\n.brow .bl small,.brow .bv small{font-size:10.5px}\n.mrow,.mover,.cstat{brea'
    'k-inside:avoid}\nhtml.brand-font .hero h1{font-size:28px}\nhtml.brand-font .sh h2{font-size:20px}\nhtml'
    '.branded .foot{background:none;color:#475467}\n}\n</style>\n</head>\n<body>\n<a class="skip" href="#main-'
    'document">Saltar al contenido principal</a>\n<header class="bar">\n  <a class="brand" href="#sec-cover'
    '">\n    <svg class="mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false"><rect width="32" h'
    'eight="32" rx="8" fill="#003865"/><path d="M16 7.5l9 4.6-9 4.6-9-4.6z" fill="#ff3621"/><path d="M7 1'
    '6.4l9 4.6 9-4.6M7 20.8l9 4.6 9-4.6" fill="none" stroke="#ffffff" stroke-width="1.9" stroke-linejoin='
    '"round"/></svg>\n    <span class="wordmark">Azure SRE Agent</span>\n    <span class="product" id="bar-'
    'product">Dependencias Azure Databricks</span>\n  </a>\n  <nav class="bar-nav" aria-label="Contenido de'
    'l informe" id="bar-nav">\n    <a href="#sec-dependencies">Dependencias</a>\n    <a href="#sec-inventor'
    'y">Inventario</a>\n    <a href="#sec-findings">Hallazgos</a>\n    <a href="#sec-finops">Costes</a>\n   '
    ' <a href="#sec-actions">Plan</a>\n    <a href="#sec-sources">Fuentes</a>\n  </nav>\n  <div class="acts"'
    '>\n    <details class="menu toc">\n      <summary class="btn ghost" aria-label="Contenido"><svg class='
    '"i" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M4 6h16M4 12h16M4 18h10"/></sv'
    'g><span class="lbl">Contenido</span></summary>\n      <nav class="menu-pop" aria-label="Contenido" id'
    '="toc-menu">\n        <a href="#sec-cover">1. Portada y procedencia</a>\n        <a href="#sec-executi'
    've">2. Resumen ejecutivo y WAF</a>\n        <a href="#sec-dependencies">3. Mapa de dependencias</a>\n '
    '       <a href="#sec-inventory">4. Inventario Lakehouse y ARM</a>\n        <a href="#sec-findings">5.'
    ' Hallazgos y reglas</a>\n        <a href="#sec-finops">6. Costes de Databricks</a>\n        <a href="#'
    'sec-actions">7. Plan de acción</a>\n        <a href="#sec-sources">8. Fuentes y metodología</a>\n     '
    ' </nav>\n    </details>\n    <span class="tag">Solo lectura</span>\n    <button type="button" class="bt'
    'n ghost icon" id="theme-toggle" aria-pressed="false" title="Modo oscuro"><svg class="i moon" viewBox'
    '="0 0 24 24" aria-hidden="true" focusable="false"><path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.'
    '5z"/></svg><svg class="i sun" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="1'
    '2" cy="12" r="4"/><path d="M12 2v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1'
    'l1.4-1.4M17.7 6.3l1.4-1.4"/></svg><span class="sr">Modo oscuro</span></button>\n    <details class="m'
    'enu" id="export-menu">\n      <summary class="btn ghost" aria-label="Exportar"><svg class="i" viewBox'
    '="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg><sp'
    'an class="lbl">Exportar</span></summary>\n      <div class="menu-pop">\n        <button type="button" '
    'id="export-json-btn">Instantánea completa (JSON)<small>Modelo normalizado embebido en este informe</'
    'small></button>\n        <button type="button" id="export-deps-csv-btn">Dependencias (CSV)<small>Nodo'
    's, relaciones y puntos ciegos del workspace</small></button>\n        <button type="button" id="expor'
    't-findings-csv-btn">Comprobaciones (CSV)<small>Todas las reglas evaluadas con su evidencia</small></'
    'button>\n        <button type="button" id="export-costs-csv-btn">Coste por carga (CSV)<small>Clústere'
    's, jobs, warehouses, pools y etiquetas del mes</small></button>\n        <button type="button" id="ex'
    'port-signals-csv-btn">Señales de optimización (CSV)<small>Cada señal con su coste y su ahorro estima'
    'do</small></button>\n      </div>\n    </details>\n    <button type="button" class="btn" id="print-btn"'
    '><svg class="i" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M7 9V3h10v6M7 18H5'
    'a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h14a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2M7 14h10v7H7z"/></svg><span class'
    '="lbl">Imprimir / PDF</span></button>\n  </div>\n</header>\n<div class="brand-ribbon" aria-hidden="true'
    '"><span class="navy"></span><span class="lava"></span><span class="steel"></span><span class="teal">'
    '</span></div>\n<div class="multi-band" id="multi-overview" hidden>\n  <div class="band-in">\n    <p id='
    '"multi-summary"></p>\n    <label class="ws-select" id="workspace-selector-wrap" hidden>Workspace\n    '
    '  <select id="workspace-selector" aria-label="Seleccionar workspace"></select>\n    </label>\n  </div>'
    '\n</div>\n<main id="main-document" tabindex="-1">\n  <div id="opening-state" class="state-card" role="a'
    'lert" hidden></div>\n  <div id="workspace-error-view" class="state-card" role="alert" hidden></div>\n '
    ' <div id="report-body" hidden>\n    <section class="hero" id="sec-cover" aria-labelledby="cover-title'
    '">\n      <div class="hero-in">\n        <div>\n          <h1 id="cover-title">Revisión de arquitectura'
    ', dependencias y configuración de Azure Databricks</h1>\n          <p class="lead" id="cover-lead"></'
    'p>\n          <div class="meta" id="cover-badges"></div>\n        </div>\n        <aside class="hero-si'
    'de" aria-label="Cliente y veredicto">\n          <div id="plaque-block">\n            <p class="plaque'
    '-k">Preparado para</p>\n            <div class="brand-plaque" id="brand-plaque"></div>\n            <p'
    ' class="client-name" id="client-name-label"></p>\n          </div>\n          <div class="signal" id="'
    'verdict"></div>\n        </aside>\n        <div class="dist" id="severity-dist"></div>\n      </div>\n  '
    '  </section>\n    <div class="page">\n      <div class="kpis" id="kpis"></div>\n      <div id="notices"'
    '></div>\n\n      <section class="chapter" id="sec-identity" aria-labelledby="h-identity">\n        <div'
    ' class="sh"><h2 id="h-identity">1. Workspace, identidad y procedencia</h2><p>Qué workspace se revisó'
    ', con qué identidad y desde qué tenant: el contexto que da validez a cada cifra de este informe.</p>'
    '</div>\n        <div class="card"><dl class="facts" id="cover-facts"></dl></div>\n      </section>\n\n  '
    '    <section class="chapter" id="sec-executive" aria-labelledby="h-exec">\n        <div class="sh"><h'
    '2 id="h-exec">2. Lectura ejecutiva, cobertura e indicadores locales</h2><p>El índice local mide únic'
    'amente las reglas evaluadas sobre evidencia observada. Nunca sustituye una evaluación oficial de Mic'
    'rosoft Well-Architected ni oculta fuentes no evaluadas.</p></div>\n        <div class="grid2">\n      '
    '    <div class="card"><h3>Lectura ejecutiva</h3><p class="sub">Lo esencial de esta revisión, empezan'
    'do por el coste.</p><ul class="msgs" id="executive-messages"></ul></div>\n          <div class="card"'
    '><h3>Distribución de comprobaciones</h3><p class="sub">Estado de cada regla local frente a la eviden'
    'cia observada.</p><div class="bars" id="check-status"></div></div>\n          <div class="card"><h3>D'
    'esglose por área</h3><p class="sub">Índice local por área de revisión, junto a su cobertura evaluada'
    '.</p><div class="bars" id="area-scores"></div></div>\n          <div class="card"><h3>Desglose por pi'
    'lar Well-Architected</h3><p class="sub">Mismo cálculo agrupado por pilar; no es una puntuación ofici'
    'al WAF.</p><div class="bars" id="pillar-scores"></div></div>\n        </div>\n        <div class="card'
    '" style="margin-top:16px"><h3>Prioridades críticas y de alta severidad observadas</h3><p class="sub"'
    '>Comprobaciones que no cumplen con severidad crítica o alta, con el objeto afectado y su evidencia.<'
    '/p><ul class="plist" id="priority-findings"></ul></div>\n      </section>\n\n      <section class="chap'
    'ter" id="sec-dependencies" aria-labelledby="h-deps">\n        <div class="sh"><h2 id="h-deps">3. Mapa'
    ' de dependencias y arquitectura Lakehouse</h2><p>Cada relación se clasifica explícitamente como <str'
    'ong>OBSERVED</strong> (join exacto de ID/clave nativa confirmado en las APIs), <strong>INFERRED</str'
    'ong> (referencia explícita de URI/host hacia un recurso no recolectado en ARM) o <strong>UNKNOWN</st'
    'rong> (linaje dinámico en tiempo de ejecución o alcance no consultado sin arrancar cómputo).</p></di'
    'v>\n        <div class="cls-sum" id="dep-class-summary"></div>\n        <div class="tabs" role="tablis'
    't" aria-label="Vistas de arquitectura y dependencias">\n          <button type="button" role="tab" id'
    '="tab-dep-observed" aria-selected="true" aria-controls="panel-dep-observed">Mapa de dependencias obs'
    'ervado e inferido</button>\n          <button type="button" role="tab" id="tab-dep-reference" aria-se'
    'lected="false" aria-controls="panel-dep-reference" tabindex="-1">Propuesta de referencia - NO desple'
    'gada</button>\n        </div>\n        <div id="panel-dep-observed" class="print-show" role="tabpanel"'
    ' aria-labelledby="tab-dep-observed">\n          <div class="card flat">\n            <div class="card-'
    'head"><h3>Grafo de vecindario</h3><p id="dep-graph-note"></p></div>\n            <div class="tools">\n'
    '              <label class="field">Capa\n                <select id="dep-layer-filter">\n             '
    '     <option value="all">Todas las capas</option>\n                  <option value="control_plane">Pl'
    'ano de control (ARM)</option>\n                  <option value="compute">Cómputo (Clústeres / Pools /'
    ' Warehouses)</option>\n                  <option value="orchestration">Orquestación (Jobs / Tareas / '
    'Pipelines)</option>\n                  <option value="governance">Gobernanza (Unity Catalog / Secret '
    'Scopes)</option>\n                  <option value="associated_resource">Recursos Azure asociados</opt'
    'ion>\n                </select>\n              </label>\n              <label class="field">Clasificaci'
    'ón\n                <select id="dep-class-filter">\n                  <option value="all">Todas (OBSER'
    'VED / INFERRED / UNKNOWN)</option>\n                  <option value="OBSERVED">OBSERVED (Join nativo '
    'exacto)</option>\n                  <option value="INFERRED">INFERRED (Referencia URI/host)</option>\n'
    '                  <option value="UNKNOWN">UNKNOWN (Punto ciego explícito)</option>\n                <'
    '/select>\n              </label>\n              <label class="field grow">Buscar nodo / carga\n        '
    '        <input type="search" id="dep-search-filter" placeholder="Job, clúster, catálogo, cuenta ADLS'
    '…">\n              </label>\n              <button type="button" class="btn ghost" id="dep-clear">Limp'
    'iar filtros</button>\n            </div>\n            <div class="graph" id="dep-graph-box"></div>\n   '
    '         <div class="g-legend" aria-hidden="true">\n              <span><svg viewBox="0 0 34 10"><lin'
    'e x1="1" y1="5" x2="33" y2="5" class="edge"/></svg>OBSERVED · join nativo</span>\n              <span'
    '><svg viewBox="0 0 34 10"><line x1="1" y1="5" x2="33" y2="5" class="edge inf"/></svg>INFERRED · URI/'
    'host sin inventario ARM</span>\n              <span id="dep-graph-caption"></span>\n            </div>'
    '\n          </div>\n          <div class="stack-gap" style="margin-top:16px">\n            <div class="'
    'card flat"><div class="card-head"><h3>Relaciones de dependencia (<span id="dep-edges-count">0</span>'
    ')</h3><p>Origen, relación y destino con los campos de join exactos.</p></div><div class="wrap"><tabl'
    'e class="dense" id="dep-edges-table"></table></div></div>\n            <div class="card flat"><div cl'
    'ass="card-head"><h3>Nodos del grafo (<span id="dep-nodes-count">0</span>)</h3><p>Cada objeto con su '
    'fuente y un resumen de la evidencia.</p></div><div class="wrap"><table class="dense" id="dep-nodes-t'
    'able"></table></div></div>\n            <div class="card flat"><div class="card-head"><h3>Puntos cieg'
    'os y alcances UNKNOWN (<span id="dep-unknowns-count">0</span>)</h3><p>Lo que esta revisión no puede '
    'ver sin ejecutar cómputo o leer código.</p></div><div class="wrap"><table class="dense" id="dep-unkn'
    'owns-table"></table></div></div>\n            <div class="card flat"><div class="card-head"><h3>Refer'
    'encias rotas detectadas (<span id="dep-broken-count">0</span>)</h3><p>Identificadores referenciados '
    'que no existen en el inventario observado.</p></div><div class="wrap"><table class="dense" id="dep-b'
    'roken-table"></table></div></div>\n          </div>\n        </div>\n        <div id="panel-dep-referen'
    'ce" class="print-show" role="tabpanel" aria-labelledby="tab-dep-reference" hidden>\n          <div cl'
    'ass="card flat">\n            <div class="card-head"><h3>Arquitectura de referencia Azure Databricks '
    'Lakehouse — Propuesta NO desplegada</h3><p>Línea base recomendada por Microsoft y Databricks Well-Ar'
    'chitected Lakehouse. <strong>No representa recursos desplegados en el entorno del cliente.</strong><'
    '/p></div>\n            <div class="graph" id="ref-arch-box"></div>\n            <div class="wrap"><tab'
    'le id="ref-arch-table"></table></div>\n          </div>\n        </div>\n      </section>\n\n      <secti'
    'on class="chapter" id="sec-inventory" aria-labelledby="h-inv">\n        <div class="sh"><h2 id="h-inv'
    '">4. Inventario de Workspace, Cómputo, Orquestación, Unity Catalog y Recursos Asociados</h2><p>Los o'
    'bjetos sobre los que se evalúan las reglas. Cada fila procede de una lectura de API registrada en la'
    ' sección 8.</p></div>\n        <div class="stack-gap">\n          <div class="card flat"><div class="c'
    'ard-head"><h3>Clústeres All-Purpose, Job Clusters, Instance Pools y Cluster Policies</h3><p id="inv-'
    'compute-count"></p></div><div class="wrap"><table class="dense" id="inv-compute-table"></table></div'
    '></div>\n          <div class="card flat"><div class="card-head"><h3>Jobs, DAG de tareas, Pipelines d'
    'eclarativos (Lakeflow / DLT) y SQL Warehouses</h3><p id="inv-orchestration-count"></p></div><div cla'
    'ss="wrap"><table class="dense" id="inv-orchestration-table"></table></div></div>\n          <div clas'
    's="card flat"><div class="card-head"><h3>Unity Catalog (Metastore, Catálogos, Esquemas, Storage Cred'
    'entials, External Locations, Conexiones) y Secret Scopes</h3><p id="inv-uc-count"></p></div><div cla'
    'ss="wrap"><table class="dense" id="inv-uc-table"></table></div></div>\n          <div class="card fla'
    't"><div class="card-head"><h3>Recursos Azure asociados y Endpoints de dependencia saliente del plano'
    ' de control</h3><p id="inv-resources-count"></p></div><div class="wrap"><table class="dense" id="inv'
    '-resources-table"></table></div></div>\n        </div>\n      </section>\n\n      <section class="chapte'
    'r" id="sec-findings" aria-labelledby="h-find">\n        <div class="sh"><h2 id="h-find">5. Hallazgos '
    'y evaluación detallada de reglas</h2><p>Cada comprobación local con su estado, la evidencia observad'
    'a y la recomendación. Las que no cumplen aparecen primero; filtre, ordene por columna y exporte.</p>'
    '</div>\n        <div class="card flat">\n          <div class="card-head"><h3>Registro de comprobacion'
    'es</h3><p id="findings-count-label"></p></div>\n          <div class="tools">\n            <label clas'
    's="field">Área\n              <select id="find-area-filter">\n                <option value="all">Toda'
    's</option>\n                <option value="best_practices">Buenas prácticas</option>\n                '
    '<option value="security">Seguridad</option>\n                <option value="finops">FinOps</option>\n '
    '               <option value="optimization">Optimización</option>\n              </select>\n          '
    '  </label>\n            <label class="field">Nivel\n              <select id="find-level-filter">\n    '
    '            <option value="all">Todos</option>\n                <option value="workspace">Workspace /'
    ' Gobernanza</option>\n                <option value="workload">Workload (Cómputo / Jobs / SQL)</optio'
    'n>\n                <option value="resource">Recurso Azure asociado</option>\n              </select>\n'
    '            </label>\n            <label class="field">Severidad\n              <select id="find-sev-f'
    'ilter">\n                <option value="all">Todas</option>\n                <option value="critical">'
    'Crítica</option>\n                <option value="high">Alta</option>\n                <option value="m'
    'edium">Media</option>\n                <option value="low">Baja</option>\n              </select>\n    '
    '        </label>\n            <label class="field">Estado\n              <select id="find-status-filte'
    'r">\n                <option value="all">Todos</option>\n                <option value="failed">No cum'
    'ple (failed)</option>\n                <option value="passed">Cumple (passed)</option>\n              '
    '  <option value="not_evaluated">No evaluado</option>\n                <option value="not_applicable">'
    'No aplica</option>\n              </select>\n            </label>\n            <label class="field grow'
    '">Buscar recurso / carga\n              <input type="search" id="find-search-filter" placeholder="Fil'
    'trar por regla, job, clúster…">\n            </label>\n            <button type="button" class="btn gh'
    'ost" id="find-clear">Limpiar</button>\n            <button type="button" class="btn ghost" id="find-e'
    'xport-btn"><svg class="i" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 4v11'
    'M7 10l5 5 5-5M5 20h14"/></svg>CSV filtrado</button>\n          </div>\n          <div class="wrap"><ta'
    'ble class="dense" id="findings-table"></table></div>\n        </div>\n      </section>\n\n      <section'
    ' class="chapter" id="sec-finops" aria-labelledby="h-finops">\n        <div class="sh"><h2 id="h-finop'
    's">6. Costes de Databricks: de dónde vienen y cómo optimizarlos</h2><p id="cost-intro">El coste del '
    'mes en Cost Management, repartido por las etiquetas que Databricks pone a cada clúster, job, SQL war'
    'ehouse y pool, y los cambios de configuración que lo reducirían.</p></div>\n        <div id="cost-emp'
    'ty" hidden></div>\n        <div id="cost-body">\n          <div id="cost-data">\n          <div class="'
    'card cost-head">\n            <div class="cstats" id="cost-stats"></div>\n            <div class="cost'
    '-trend" id="cost-trend"></div>\n          </div>\n          <div class="grid2" style="margin-top:16px"'
    '>\n            <div class="card"><h3>DBU por tipo de cómputo</h3><p class="sub" id="cost-dbu-sub">Lo '
    'que Databricks factura por unidad de procesamiento, según el tipo de carga.</p><div class="bars" id='
    '"cost-dbu-bars"></div></div>\n            <div class="card"><h3>Infraestructura por servicio</h3><p c'
    'lass="sub" id="cost-infra-sub">Máquinas virtuales, discos y red que el área de trabajo usa en vuestr'
    'a suscripción.</p><div class="bars" id="cost-infra-bars"></div><div class="vm-sizes" id="cost-vm-siz'
    'es"></div></div>\n          </div>\n          <div class="card flat" style="margin-top:16px">\n        '
    '    <div class="card-head"><h3>Quién lo consume</h3><p id="cost-attr-note"></p></div>\n            <d'
    'iv class="tabs cost-tabs" role="tablist" aria-label="Reparto del coste" id="cost-tabs"></div>\n      '
    '      <div class="tools">\n              <label class="field grow">Buscar\n                <input type'
    '="search" id="cost-attr-search" placeholder="Clúster, job, warehouse, pool o valor de etiqueta…">\n  '
    '            </label>\n              <button type="button" class="btn ghost" id="cost-attr-export"><sv'
    'g class="i" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 4v11M7 10l5 5 5-5M'
    '5 20h14"/></svg>CSV del reparto</button>\n            </div>\n            <div class="wrap" role="tabp'
    'anel" id="cost-attr-panel" aria-labelledby="cost-tab-cluster"><table class="dense" id="cost-attr-tab'
    'le"></table></div>\n          </div>\n          <div class="grid2" style="margin-top:16px">\n          '
    '  <div class="card"><h3>Lo que no explica ninguna etiqueta</h3><p class="sub">Coste sin la etiqueta '
    '<span class="mono">Vendor</span> que Databricks pone a todo el cómputo clásico: servicios compartido'
    's del área de trabajo y cómputo serverless.</p><div id="cost-gap"></div></div>\n            <div clas'
    's="card"><h3>Cobertura de vuestras etiquetas</h3><p class="sub" id="cost-tags-sub">Parte del coste d'
    'el mes que lleva cada etiqueta de imputación configurada.</p><div class="bars" id="cost-tag-bars"></'
    'div><ul class="notes" id="cost-tag-notes"></ul></div>\n          </div>\n          <div class="card" s'
    'tyle="margin-top:16px"><h3>Qué ha cambiado frente al mes anterior</h3><p class="sub" id="cost-movers'
    '-sub">Clústeres, jobs, SQL warehouses y pools con mayor variación.</p><div class="movers" id="cost-m'
    'overs"></div></div>\n          </div>\n          <div class="card flat" style="margin-top:16px">\n     '
    '       <div class="card-head"><h3>Cómo optimizarlo</h3><p id="cost-signals-count"></p></div>\n       '
    '     <div class="tools">\n              <label class="field">Severidad\n                <select id="co'
    'st-sig-sev">\n                  <option value="all">Todas</option>\n                  <option value="h'
    'igh">Alta</option>\n                  <option value="medium">Media</option>\n                  <option'
    ' value="low">Baja</option>\n                </select>\n              </label>\n              <label cla'
    'ss="field">Ahorro\n                <select id="cost-sig-saving">\n                  <option value="all'
    '">Todas las señales</option>\n                  <option value="with">Con ahorro estimado</option>\n   '
    '             </select>\n              </label>\n              <label class="field grow">Buscar\n       '
    '         <input type="search" id="cost-sig-search" placeholder="Señal, clúster, job, warehouse…">\n  '
    '            </label>\n              <button type="button" class="btn ghost" id="cost-sig-export"><svg'
    ' class="i" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M12 4v11M7 10l5 5 5-5M5'
    ' 20h14"/></svg>CSV filtrado</button>\n            </div>\n            <div class="wrap"><table class="'
    'dense" id="cost-signals-table"></table></div>\n          </div>\n          <div class="card" style="ma'
    'rgin-top:16px" id="cost-system"></div>\n          <div class="card" style="margin-top:16px">\n        '
    '    <h3>Método, supuestos y fuentes de coste</h3>\n            <p class="sub">Cómo se calcula cada ci'
    'fra de esta sección. Ninguna consulta arranca cómputo ni cambia nada.</p>\n            <dl class="dl2'
    '" id="cost-method"></dl>\n          </div>\n        </div>\n        <div class="card flat legacy-cost" '
    'style="margin-top:16px" id="finops-legacy">\n          <div class="card-head"><h3>Coste ARM del alcan'
    'ce aprobado (<span class="mono">cost_scope</span>)</h3><p id="finops-cost-window"></p></div>\n       '
    '   <div class="legacy-sum"><div class="stat" id="finops-actual-cost"></div><ul class="notes" id="fin'
    'ops-cost-note"></ul></div>\n          <div class="wrap"><table class="dense" id="finops-cost-table"><'
    '/table></div>\n        </div>\n      </section>\n\n      <section class="chapter" id="sec-actions" aria-'
    'labelledby="h-actions">\n        <div class="sh"><h2 id="h-actions">7. Plan de acción priorizado para'
    ' revisión humana</h2><p>Los horizontes Quick-win (&lt;1 semana), Corto plazo (1-3 meses) y Medio pla'
    'zo son categorías orientativas de planificación, no promesas de entrega ni cambios automáticos.</p><'
    '/div>\n        <div class="plan" id="actions-plan"></div>\n      </section>\n\n      <section class="cha'
    'pter" id="sec-sources" aria-labelledby="h-sources">\n        <div class="sh"><h2 id="h-sources">8. Re'
    'gistro de fuentes, recibos HTTP y límites metodológicos</h2><p>Qué fuentes se leyeron, con qué resul'
    'tado y qué queda fuera del alcance. El índice local solo se interpreta junto a esta cobertura.</p></'
    'div>\n        <div class="card flat">\n          <div class="card-head"><h3>Cobertura de fuentes</h3><'
    'p id="sources-summary"></p></div>\n          <div class="bars" id="sources-bars" style="padding:0 22p'
    'x 16px"></div>\n          <div class="wrap"><table class="dense" id="sources-table"></table></div>\n  '
    '      </div>\n        <div class="card" style="margin-top:16px">\n          <h3>Método e interpretació'
    'n</h3>\n          <p class="sub">Cómo se calcula cada indicador y qué no puede afirmar esta revisión.'
    '</p>\n          <dl class="dl2" id="method-notes"></dl>\n          <h3 style="margin-top:18px">Limitac'
    'iones y reglas de interpretación</h3>\n          <ul class="notes" id="methodology-limitations"></ul>'
    '\n        </div>\n      </section>\n    </div>\n  </div>\n</main>\n<footer class="foot" id="report-footer"'
    '></footer>\n<script type="application/json" id="report-data">__REPORT_DATA_JSON__</script>\n<script>\n('
    'function () {\n  "use strict";\n  var SVGNS = "http://www.w3.org/2000/svg";\n  var LAYERS = ["control_p'
    'lane", "compute", "orchestration", "governance", "associated_resource"];\n  var SEVS = ["critical", "'
    'high", "medium", "low"];\n  var STATUS_ORDER = { failed: 0, not_evaluated: 1, passed: 2, not_applicab'
    'le: 3 };\n  var L = {\n    status: { passed: "Cumple", failed: "No cumple", not_evaluated: "No evaluad'
    'o", not_applicable: "No aplica" },\n    sev: { critical: "Crítica", high: "Alta", medium: "Media", lo'
    'w: "Baja" },\n    area: { best_practices: "Buenas prácticas", security: "Seguridad", finops: "FinOps"'
    ', optimization: "Optimización" },\n    pillar: { reliability: "Fiabilidad", security: "Seguridad", co'
    'st: "Optimización de costes", operations: "Excelencia operativa", performance: "Eficiencia del rendi'
    'miento" },\n    level: { workspace: "Workspace", workload: "Carga de trabajo", resource: "Recurso Azu'
    're" },\n    layer: { control_plane: "Plano de control", compute: "Cómputo", orchestration: "Orquestac'
    'ión", governance: "Gobernanza", associated_resource: "Recursos asociados" },\n    src: { complete: "C'
    'ompleta", partial: "Parcial", denied: "Denegada", error: "Error", not_configured: "No configurada", '
    'not_applicable: "No aplica" },\n    effort: { L: "esfuerzo bajo", M: "esfuerzo medio", H: "esfuerzo a'
    'lto" },\n    kind: {\n      databricks_workspace: "Workspace", managed_resource_group: "Grupo administ'
    'rado", outbound_dependency_category: "Endpoint saliente",\n      all_purpose_cluster: "Clúster all-pu'
    'rpose", job_cluster_spec: "Job cluster", instance_pool: "Instance pool", cluster_policy: "Cluster po'
    'licy",\n      sql_warehouse: "SQL Warehouse", job: "Job", job_task: "Tarea de job", dlt_pipeline: "Pi'
    'peline DLT", secret_scope: "Secret scope",\n      uc_metastore: "Metastore UC", uc_catalog: "Catálogo'
    ' UC", uc_schema: "Esquema UC", uc_storage_credential: "Storage credential",\n      uc_external_locati'
    'on: "External location", uc_connection: "Conexión UC", external_storage_target: "Almacenamiento exte'
    'rno",\n      external_key_vault_target: "Key Vault externo", "microsoft.network/virtualnetworks": "Re'
    'd virtual", "microsoft.network/virtualnetworks/subnets": "Subred",\n      "microsoft.network/networks'
    'ecuritygroups": "NSG", "microsoft.network/privateendpoints": "Private Endpoint", "microsoft.databric'
    'ks/accessconnectors": "Access Connector",\n      "microsoft.managedidentity/userassignedidentities": '
    '"Identidad administrada", "microsoft.storage/storageaccounts": "Cuenta de almacenamiento",\n      "mi'
    'crosoft.keyvault/vaults": "Key Vault", AllPurposeCluster: "Clúster all-purpose", InstancePool: "Inst'
    'ance pool", ClusterPolicy: "Cluster policy",\n      "microsoft.network/routetables": "Tabla de rutas"'
    ', "microsoft.network/natgateways": "NAT Gateway", "microsoft.network/publicipaddresses": "IP pública'
    '",\n      "microsoft.network/loadbalancers": "Load Balancer", "microsoft.network/privatednszones": "Z'
    'ona DNS privada", "microsoft.eventhub/namespaces": "Event Hubs",\n      external_access_connector_tar'
    'get: "Access Connector externo", external_arm_target: "Recurso ARM externo",\n      inferred_adls_sto'
    'rage_uri_target: "URI ADLS inferida", inferred_catalog_storage_uri_target: "Almacenamiento de catálo'
    'go inferido",\n      inferred_pipeline_storage_uri_target: "Almacenamiento de pipeline inferido", per'
    'mission_filtered_absence_or_deleted_target: "Destino no visible o eliminado",\n      GlobalInitScript'
    ': "Init script global", OutboundDependency: "Endpoint saliente"\n    }\n  };\n  var SEV_WORD = { critic'
    'al: ["crítica", "críticas"], high: ["alta", "altas"], medium: ["media", "medias"], low: ["baja", "ba'
    'jas"] };\n  var SEV_BAR = { critical: "var(--crit-bar)", high: "var(--high-bar)", medium: "var(--med-'
    'bar)", low: "var(--low-bar)" };\n  var NF = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 2'
    ' });\n  var NF2 = new Intl.NumberFormat("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2'
    ' });\n  var ICON = {\n    ext: ["M14 4h6v6", "M20 4l-9 9", "M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1'
    ' 1 0 0 1 1-1h5"],\n    check: ["M20 6L9 17l-5-5"],\n    alert: ["M12 3.5l9 16H3z", "M12 10v4", "M12 17'
    '.2v.3"],\n    info: ["M12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 11v5", "M12 7.8v.3"]\n  };\n\n  funct'
    'ion el(tag, attrs, children) {\n    var node = document.createElement(tag);\n    if (attrs) {\n      Ob'
    'ject.keys(attrs).forEach(function (k) {\n        if (k === "text") { node.textContent = String(attrs['
    'k]); }\n        else if (k === "className") { if (attrs[k]) { node.className = attrs[k]; } }\n        '
    'else if (attrs[k] !== null && attrs[k] !== undefined) { node.setAttribute(k, String(attrs[k])); }\n  '
    '    });\n    }\n    if (children) {\n      children.forEach(function (c) {\n        if (typeof c === "st'
    'ring" || typeof c === "number") { node.appendChild(document.createTextNode(String(c))); }\n        el'
    'se if (c) { node.appendChild(c); }\n      });\n    }\n    return node;\n  }\n  function svg(tag, attrs, t'
    'ext) {\n    var node = document.createElementNS(SVGNS, tag);\n    Object.keys(attrs || {}).forEach(fun'
    'ction (k) { node.setAttribute(k, String(attrs[k])); });\n    if (text !== undefined) { node.textConte'
    'nt = String(text); }\n    return node;\n  }\n  function clear(node) { while (node.firstChild) { node.re'
    'moveChild(node.firstChild); } }\n  function icon(name) {\n    var s = svg("svg", { "class": "i", viewB'
    'ox: "0 0 24 24", "aria-hidden": "true", focusable: "false" });\n    ICON[name].forEach(function (d) {'
    ' s.appendChild(svg("path", { d: d })); });\n    return s;\n  }\n  function lab(map, key) {\n    if (key '
    '=== null || key === undefined || key === "") { return "—"; }\n    return Object.prototype.hasOwnPrope'
    'rty.call(map, key) ? map[key] : String(key);\n  }\n  function isNum(v) { return typeof v === "number" '
    '&& isFinite(v); }\n  function num(v) { return isNum(v) ? NF.format(v) : (v === null || v === undefine'
    'd || v === "" ? "—" : String(v)); }\n  function pct(v) { return isNum(v) ? NF.format(v) + "\\u00a0%" :'
    ' "No evaluado"; }\n  function utc(s) {\n    if (!s) { return "—"; }\n    var m = /^(\\d{4}-\\d{2}-\\d{2})T'
    '(\\d{2}:\\d{2})/.exec(String(s));\n    return m ? m[1] + " " + m[2] + " UTC" : String(s);\n  }\n  functio'
    'n day(s) { var m = /^(\\d{4}-\\d{2}-\\d{2})/.exec(String(s || "")); return m ? m[1] : "—"; }\n  function'
    ' plural(n, one, many) { return n === 1 ? one : many; }\n  function yesNo(v) { return v === true ? "Sí'
    '" : v === false ? "No" : "No observado"; }\n  function access(v) { return v === "Disabled" ? "Deshabi'
    'litado" : v === "Enabled" ? "Habilitado" : (v || "No observado"); }\n  function rich(node, parts) {\n '
    '   clear(node);\n    parts.forEach(function (p) { if (p !== "" && p !== null) { node.appendChild(Arra'
    'y.isArray(p) ? el("b", { text: p[0] }) : document.createTextNode(String(p))); } });\n    return node;'
    '\n  }\n  function brk(text, cls) {\n    var span = el("span", { className: cls === undefined ? "mono" :'
    ' cls });\n    var s = String(text === null || text === undefined || text === "" ? "—" : text), buf = '
    '"";\n    if (s.length <= 24) { span.textContent = s; span.className += " nw"; return span; }\n    for '
    '(var i = 0; i < s.length; i++) {\n      buf += s.charAt(i);\n      if ("/_.-:,".indexOf(s.charAt(i)) >'
    '= 0 && i < s.length - 1) {\n        span.appendChild(document.createTextNode(buf));\n        span.appe'
    'ndChild(document.createElement("wbr"));\n        buf = "";\n      }\n    }\n    if (buf) { span.appendCh'
    'ild(document.createTextNode(buf)); }\n    return span;\n  }\n  function mono(text) { return el("span", '
    '{ className: "mono nw", text: text === null || text === undefined || text === "" ? "—" : text }); }\n'
    '  function stack(main, sub) {\n    var d = el("div", { className: "stack" });\n    var b = el("b");\n  '
    '  if (main instanceof Node) { b.appendChild(main); } else { b.textContent = main === null || main =='
    '= undefined || main === "" ? "—" : String(main); }\n    d.appendChild(b);\n    if (sub instanceof Node'
    ') { var w = el("small"); w.appendChild(sub); d.appendChild(w); }\n    else if (sub) { d.appendChild(e'
    'l("small", { text: sub })); }\n    return d;\n  }\n  function pill(cls, text, title) { return el("span"'
    ', { className: "pill " + cls, text: text, title: title || null }); }\n  function sevPill(sev, label) '
    '{ return pill(SEVS.indexOf(sev) >= 0 ? "sev-" + sev : "sev-info", label || lab(L.sev, sev)); }\n  fun'
    'ction clsPill(c) { return pill("cls-" + (c === "OBSERVED" || c === "INFERRED" ? c : "UNKNOWN"), c ||'
    ' "UNKNOWN"); }\n  function statusTag(st) { return el("span", { className: "st st-" + (STATUS_ORDER[st'
    '] !== undefined ? st : "not_evaluated"), title: st, text: lab(L.status, st) }); }\n  function srcTone'
    '(st) { return st === "complete" ? "tone-ok" : st === "partial" ? "tone-warn" : (st === "denied" || s'
    't === "error") ? "tone-crit" : "tone-info"; }\n  function srcPill(st) { return pill(srcTone(st), lab('
    'L.src, st), st); }\n  function kindLabel(kind) { var t = lab(L.kind, kind); return el("span", { text:'
    ' t, title: kind && t !== kind ? kind : null }); }\n  function emptyState(text) { return el("div", { c'
    'lassName: "empty" }, [icon("check"), el("span", { text: text })]); }\n  function safeLearnUrl(u) {\n  '
    '  if (typeof u !== "string") { return null; }\n    try {\n      var parsed = new URL(u);\n      return '
    '(parsed.protocol === "https:" && (parsed.hostname === "learn.microsoft.com" || parsed.hostname === "'
    'docs.databricks.com")) ? u : null;\n    } catch (e) { return null; }\n  }\n  function extLink(href, tex'
    't) { return el("a", { className: "ext", href: href, target: "_blank", rel: "noopener noreferrer" }, '
    '[text, icon("ext")]); }\n  var ARM_RE = /^\\/subscriptions\\/[0-9a-f-]{36}\\/resourcegroups\\/([^\\/]+)\\/p'
    'roviders\\/(microsoft\\.[a-z0-9]+\\/[a-z0-9]+)\\/([^\\/]+)(?:\\/([a-z0-9]+)\\/([^\\/]+))?$/i;\n  function arm'
    'Cell(id, name) {\n    var m = ARM_RE.exec(String(id || ""));\n    if (!m) { return brk(id); }\n    var '
    'box = el("div", { className: "res" });\n    box.appendChild(el("b", { text: name || m[5] || m[3] }));'
    '\n    box.appendChild(el("small", null, [brk(m[1] + " · " + m[2] + (m[4] ? "/" + m[4] : ""), "")]));\n'
    '    var a = extLink("https://portal.azure.com/#@/resource" + id, "Portal");\n    a.setAttribute("titl'
    'e", id);\n    box.appendChild(a);\n    return box;\n  }\n  function kvChips(obj, max) {\n    var wrap = e'
    'l("div", { className: "chips" }), shown = 0;\n    Object.keys(obj || {}).forEach(function (k) {\n     '
    ' var v = obj[k];\n      if (v === null || v === undefined || v === "" || typeof v === "object" || sho'
    'wn >= max) { return; }\n      var s = String(v);\n      if (s.indexOf("/subscriptions/") === 0 || s.le'
    'ngth > 70) { return; }\n      wrap.appendChild(el("span", null, [k + ": ", el("b", { text: s })]));\n '
    '     shown++;\n    });\n    return shown ? wrap : null;\n  }\n  function evidenceCell(obj) {\n    var box'
    ' = el("div"), chips = kvChips(obj, 4), json = JSON.stringify(obj || {}, null, 1);\n    if (chips) { b'
    'ox.appendChild(chips); }\n    if (json && json.length > 2) {\n      var d = el("details", { className:'
    ' "json" });\n      d.appendChild(el("summary", { text: "JSON completo" }));\n      d.appendChild(el("p'
    're", { text: json }));\n      box.appendChild(d);\n    }\n    if (!box.firstChild) { box.textContent = '
    '"—"; }\n    return box;\n  }\n\n  var TSTATE = {};\n  function spec(c) { return (c !== null && typeof c ='
    '== "object" && !(c instanceof Node) && Object.prototype.hasOwnProperty.call(c, "v")) ? c : { v: c };'
    ' }\n  function sortValue(c) {\n    if (c.s !== undefined) { return c.s; }\n    return c.v instanceof No'
    'de ? c.v.textContent : (c.v === null || c.v === undefined ? "" : c.v);\n  }\n  function renderTable(ta'
    'bleNode, headers, rows, opts) {\n    var st = TSTATE[tableNode.id] || (TSTATE[tableNode.id] = { sort:'
    ' -1, dir: 1 });\n    st.headers = headers.map(function (h) { return typeof h === "string" ? { t: h } '
    ': h; });\n    st.rows = rows.map(function (r) { return r.map(spec); });\n    st.opts = opts || {};\n   '
    ' st.limit = st.opts.page || 0;\n    drawTable(tableNode, st, null);\n  }\n  function drawTable(tableNod'
    'e, st, focus) {\n    var headers = st.headers, opts = st.opts, rows = st.rows;\n    if (st.sort >= 0) '
    '{\n      var i = st.sort, dir = st.dir;\n      rows = rows.map(function (r, idx) { return { r: r, idx:'
    ' idx }; }).sort(function (a, b) {\n        var x = sortValue(a.r[i]), y = sortValue(b.r[i]);\n        '
    'var d = (isNum(x) && isNum(y)) ? x - y : String(x).localeCompare(String(y), "es", { numeric: true, s'
    'ensitivity: "base" });\n        return d * dir || a.idx - b.idx;\n      }).map(function (o) { return o'
    '.r; });\n    }\n    clear(tableNode);\n    var thead = el("thead"), trh = el("tr");\n    headers.forEach'
    '(function (h, hi) {\n      var th = el("th", { className: h.c || null, scope: "col" });\n      if (opt'
    's.sortable && h.s !== false) {\n        var b = el("button", { type: "button", className: "th-sort", '
    'text: h.t });\n        th.setAttribute("data-label", h.t);\n        if (st.sort === hi) { th.setAttrib'
    'ute("aria-sort", st.dir === 1 ? "ascending" : "descending"); }\n        b.addEventListener("click", f'
    'unction () {\n          if (st.sort === hi) { st.dir = -st.dir; } else { st.sort = hi; st.dir = 1; }\n'
    '          drawTable(tableNode, st, "th" + hi);\n        });\n        th.appendChild(b);\n      } else {'
    ' th.textContent = h.t; }\n      trh.appendChild(th);\n    });\n    thead.appendChild(trh);\n    tableNod'
    'e.appendChild(thead);\n    var tbody = el("tbody");\n    if (!rows.length) {\n      var tr0 = el("tr");'
    '\n      tr0.appendChild(el("td", { colspan: headers.length, className: "empty-cell", text: opts.empty'
    ' || "Sin registros en este alcance o filtro." }));\n      tbody.appendChild(tr0);\n    }\n    rows.forE'
    'ach(function (cells, ri) {\n      var tr = el("tr", { className: st.limit && ri >= st.limit ? "pg" : '
    'null });\n      cells.forEach(function (c, ci) {\n        var td = el("td", { className: [headers[ci] '
    '&& headers[ci].c, c.c].filter(Boolean).join(" ") || null });\n        if (c.v instanceof Node) { td.a'
    'ppendChild(c.v); }\n        else { td.textContent = c.v === null || c.v === undefined || c.v === "" ?'
    ' "—" : String(c.v); }\n        tr.appendChild(td);\n      });\n      tbody.appendChild(tr);\n    });\n   '
    ' tableNode.appendChild(tbody);\n    var wrap = tableNode.parentNode, more = wrap.nextElementSibling;\n'
    '    if (!more || !more.classList.contains("more-row")) {\n      more = el("div", { className: "more-r'
    'ow" });\n      wrap.parentNode.insertBefore(more, wrap.nextSibling);\n    }\n    clear(more);\n    var h'
    'iddenRows = st.limit ? Math.max(0, rows.length - st.limit) : 0;\n    more.hidden = hiddenRows === 0;\n'
    '    if (hiddenRows) {\n      var step = opts.page;\n      var b1 = el("button", { type: "button", clas'
    'sName: "btn ghost sm", "data-k": "more", text: "Mostrar " + Math.min(step, hiddenRows) + " más" });\n'
    '      b1.addEventListener("click", function () { st.limit += step; drawTable(tableNode, st, "more");'
    ' });\n      var b2 = el("button", { type: "button", className: "btn ghost sm", "data-k": "all", text:'
    ' "Mostrar todas (" + rows.length + ")" });\n      b2.addEventListener("click", function () { st.limit'
    ' = 0; drawTable(tableNode, st, "table"); });\n      more.appendChild(el("span", { className: "more-no'
    'te", text: "Mostrando " + st.limit + " de " + rows.length + " filas" }));\n      more.appendChild(b1)'
    ';\n      more.appendChild(b2);\n    }\n    if (focus) {\n      var target = focus.indexOf("th") === 0 ? '
    'tableNode.querySelectorAll(".th-sort")[Number(focus.slice(2))] : focus === "more" ? more.querySelect'
    'or("[data-k=more]") : null;\n      if (target) { target.focus(); }\n      else if (focus === "more" ||'
    ' focus === "table") { tableNode.setAttribute("tabindex", "-1"); tableNode.focus(); }\n    }\n  }\n\n  va'
    'r rawText = document.getElementById("report-data").textContent;\n  var rootData;\n  try {\n    rootData'
    ' = JSON.parse(rawText);\n  } catch (e) {\n    var openErr = document.getElementById("opening-state");\n'
    '    openErr.hidden = false;\n    openErr.textContent = "Error al cargar el modelo JSON embebido del i'
    'nforme.";\n    return;\n  }\n\n  var isMulti = rootData && rootData.schema_version === "databricks-dep-m'
    'ulti-workspace-v1";\n  var currentSnap = null;\n\n  var themeBtn = document.getElementById("theme-toggl'
    'e");\n  themeBtn.addEventListener("click", function () {\n    var dark = document.documentElement.getA'
    'ttribute("data-theme") === "dark";\n    if (dark) { document.documentElement.removeAttribute("data-th'
    'eme"); }\n    else { document.documentElement.setAttribute("data-theme", "dark"); }\n    themeBtn.setA'
    'ttribute("aria-pressed", dark ? "false" : "true");\n  });\n  document.getElementById("print-btn").addE'
    'ventListener("click", function () { window.print(); });\n  var themeBeforePrint = null;\n  window.addE'
    'ventListener("beforeprint", function () {\n    themeBeforePrint = document.documentElement.getAttribu'
    'te("data-theme");\n    document.documentElement.removeAttribute("data-theme");\n  });\n  window.addEven'
    'tListener("afterprint", function () {\n    if (themeBeforePrint) { document.documentElement.setAttrib'
    'ute("data-theme", themeBeforePrint); }\n    themeBeforePrint = null;\n  });\n\n  function closeMenus(exc'
    'ept) {\n    [].forEach.call(document.querySelectorAll("details.menu[open]"), function (d) { if (d !=='
    ' except) { d.removeAttribute("open"); } });\n  }\n  document.addEventListener("click", function (ev) {'
    '\n    var inside = ev.target.closest ? ev.target.closest("details.menu") : null;\n    closeMenus(insid'
    'e);\n    if (inside && ev.target.closest("a, button") && !ev.target.closest("summary")) { inside.remo'
    'veAttribute("open"); }\n  });\n  document.addEventListener("keydown", function (ev) {\n    if (ev.key !'
    '== "Escape") { return; }\n    var open = document.querySelector("details.menu[open]");\n    if (open) '
    '{ open.removeAttribute("open"); open.querySelector("summary").focus(); }\n  });\n\n  function downloadB'
    'lob(filename, content, mime) {\n    var blob = new Blob([content], { type: mime });\n    var url = URL'
    '.createObjectURL(blob);\n    var a = el("a", { href: url, download: filename });\n    document.body.ap'
    'pendChild(a);\n    a.click();\n    document.body.removeChild(a);\n    URL.revokeObjectURL(url);\n  }\n  f'
    'unction csvEscape(v) {\n    if (v === null || v === undefined) { return ""; }\n    var s = typeof v =='
    '= "object" ? JSON.stringify(v) : String(v);\n    if (/^[=+\\-@\\t\\r\\n]/.test(s.trimLeft())) { s = "\'" +'
    ' s; }\n    return \'"\' + s.replace(/"/g, \'""\') + \'"\';\n  }\n  var CHECK_COLS = ["check_id", "rule_id", "'
    'title", "status", "level", "area", "pillar", "severity", "workload_name", "reason", "recommendation"'
    ', "learn_url"];\n  function checksCsv(list) {\n    var lines = [CHECK_COLS.join(",")];\n    list.forEac'
    'h(function (r) { lines.push(CHECK_COLS.map(function (c) { return csvEscape(r[c]); }).join(",")); });'
    '\n    return "\\uFEFF" + lines.join("\\r\\n");\n  }\n  document.getElementById("export-json-btn").addEvent'
    'Listener("click", function () {\n    downloadBlob("databricks-dependency-snapshot.json", JSON.stringi'
    'fy(rootData, null, 2), "application/json;charset=utf-8");\n  });\n  document.getElementById("export-de'
    'ps-csv-btn").addEventListener("click", function () {\n    if (!currentSnap) { return; }\n    var cols '
    '= ["record_type", "classification", "layer", "id", "kind", "label", "from", "to", "relation", "join_'
    'fields", "source_ids"];\n    var lines = [cols.join(",")];\n    var dep = currentSnap.dependencies;\n  '
    '  [].concat(dep.nodes || [], dep.edges || [], dep.unknowns || []).forEach(function (r) {\n      lines'
    '.push(cols.map(function (c) { return csvEscape(r[c]); }).join(","));\n    });\n    downloadBlob("datab'
    'ricks-dependencies.csv", "\\uFEFF" + lines.join("\\r\\n"), "text/csv;charset=utf-8");\n  });\n  document.'
    'getElementById("export-findings-csv-btn").addEventListener("click", function () {\n    if (!currentSn'
    'ap) { return; }\n    downloadBlob("databricks-findings.csv", checksCsv(currentSnap.checks || []), "te'
    'xt/csv;charset=utf-8");\n  });\n\n  var tabObs = document.getElementById("tab-dep-observed");\n  var tab'
    'Ref = document.getElementById("tab-dep-reference");\n  var panelObs = document.getElementById("panel-'
    'dep-observed");\n  var panelRef = document.getElementById("panel-dep-reference");\n  function selectTa'
    'b(ref) {\n    tabObs.setAttribute("aria-selected", ref ? "false" : "true");\n    tabRef.setAttribute("'
    'aria-selected", ref ? "true" : "false");\n    tabObs.setAttribute("tabindex", ref ? "-1" : "0");\n    '
    'tabRef.setAttribute("tabindex", ref ? "0" : "-1");\n    panelObs.hidden = ref;\n    panelRef.hidden = '
    '!ref;\n  }\n  tabObs.addEventListener("click", function () { selectTab(false); });\n  tabRef.addEventLi'
    'stener("click", function () { selectTab(true); });\n  [tabObs, tabRef].forEach(function (t) {\n    t.a'
    'ddEventListener("keydown", function (ev) {\n      if (ev.key === "ArrowRight" || ev.key === "ArrowLef'
    't") {\n        var ref = t === tabObs;\n        selectTab(ref);\n        (ref ? tabRef : tabObs).focus('
    ');\n        ev.preventDefault();\n      }\n    });\n  });\n\n  function fitText(s, max) { s = String(s || '
    '""); return s.length > max ? s.slice(0, Math.max(1, max - 1)) + "…" : s; }\n  function nodeLines(n) {'
    '\n    var label = String(n.label || n.name || n.id), kind = lab(L.kind, n.kind), cut = label.indexOf('
    '" :: ");\n    if (cut < 0) { cut = label.indexOf(" / "); }\n    if (cut > 0) { return [label.slice(lab'
    'el.indexOf(" ", cut + 1) + 1), kind + " · " + label.slice(0, cut)]; }\n    return [label, kind + (n.c'
    'lassification === "INFERRED" ? " · INFERRED" : "")];\n  }\n  function renderNeighborhoodSvg(nodes, edg'
    'es) {\n    var box = document.getElementById("dep-graph-box");\n    var caption = document.getElementB'
    'yId("dep-graph-caption");\n    clear(box);\n    if (!nodes.length) { box.appendChild(emptyState("Ningú'
    'n nodo coincide con este filtro.")); caption.textContent = ""; return; }\n    var deg = {};\n    edges'
    '.forEach(function (e) { deg[e.from] = (deg[e.from] || 0) + 1; deg[e.to] = (deg[e.to] || 0) + 1; });\n'
    '    var subset = nodes.map(function (n, i) {\n      return { n: n, i: i, r: (n.kind === "databricks_w'
    'orkspace" ? 1000 : 0) + (n.classification === "INFERRED" ? 500 : 0) + (deg[n.id] || 0) };\n    }).sor'
    't(function (a, b) { return b.r - a.r || a.i - b.i; }).slice(0, 13).map(function (x) { return x.n; })'
    ';\n    var order = LAYERS.slice();\n    subset.forEach(function (n) { if (order.indexOf(n.layer) < 0) '
    '{ order.push(n.layer); } });\n    var cols = [];\n    order.forEach(function (layer) {\n      var ns = '
    'subset.filter(function (n) { return n.layer === layer; });\n      for (var i = 0; i < ns.length; i +='
    ' 5) { cols.push({ layer: layer, nodes: ns.slice(i, i + 5), head: i === 0 }); }\n    });\n    var W = 1'
    '200, colW = W / cols.length, bw = Math.min(214, colW - 30), bh = 50, gy = 20, top = 34;\n    var rows'
    ' = Math.max.apply(null, cols.map(function (c) { return c.nodes.length; }));\n    var H = top + rows *'
    ' (bh + gy);\n    var pos = {};\n    cols.forEach(function (c, ci) {\n      var off = (rows - c.nodes.le'
    'ngth) * (bh + gy) / 2;\n      c.nodes.forEach(function (n, ri) { pos[n.id] = { x: colW * ci + colW / '
    '2, y: top + off + ri * (bh + gy) + bh / 2, c: ci }; });\n    });\n    var s = svg("svg", { viewBox: "0'
    ' 0 " + W + " " + H, role: "img", "aria-label": "Grafo de dependencias: " + subset.length + " de " + '
    'nodes.length + " nodos filtrados, agrupados por capa." });\n    var defs = svg("defs");\n    ["obs", "'
    'inf"].forEach(function (k) {\n      var m = svg("marker", { id: "dep-arrow-" + k, viewBox: "0 0 10 10'
    '", refX: 9, refY: 5, markerWidth: 6, markerHeight: 6, orient: "auto" });\n      m.appendChild(svg("pa'
    'th", { d: "M0 0L10 5L0 10z", "class": "arr " + k }));\n      defs.appendChild(m);\n    });\n    s.appen'
    'dChild(defs);\n    cols.forEach(function (c, ci) {\n      if (c.head) { s.appendChild(svg("text", { x:'
    ' colW * ci + colW / 2 - bw / 2, y: 16, "class": "g-col" }, fitText(lab(L.layer, c.layer), Math.floor'
    '(bw / 7.5)))); }\n    });\n    var drawn = 0;\n    edges.forEach(function (e) {\n      var a = pos[e.fro'
    'm], b = pos[e.to];\n      if (!a || !b || e.from === e.to) { return; }\n      var sx, ex, c1, c2;\n    '
    '  if (a.c < b.c) { sx = a.x + bw / 2; ex = b.x - bw / 2 - 2; c1 = sx + (ex - sx) / 2; c2 = ex - (ex '
    '- sx) / 2; }\n      else if (a.c > b.c) { sx = a.x - bw / 2; ex = b.x + bw / 2 + 2; c1 = sx - (sx - e'
    'x) / 2; c2 = ex + (sx - ex) / 2; }\n      else { sx = a.x + bw / 2; ex = b.x + bw / 2 + 2; c1 = sx + '
    '26; c2 = ex + 26; }\n      var k = e.classification === "INFERRED" ? "inf" : "obs";\n      s.appendChi'
    'ld(svg("path", { d: "M" + sx + " " + a.y + " C" + c1 + " " + a.y + " " + c2 + " " + b.y + " " + ex +'
    ' " " + b.y, "class": "edge " + k, "marker-end": "url(#dep-arrow-" + k + ")" }));\n      drawn++;\n    '
    '});\n    var maxChars = Math.floor((bw - 22) / 6.9);\n    subset.forEach(function (n) {\n      var p = '
    'pos[n.id], lines = nodeLines(n);\n      var g = svg("g", { "class": "g-node" + (n.classification === '
    '"INFERRED" ? " inf" : "") + (n.kind === "databricks_workspace" ? " ws" : "") });\n      g.appendChild'
    '(svg("title", {}, (n.label || n.id) + " · " + (n.kind || "") + " · " + (n.classification || "")));\n '
    '     g.appendChild(svg("rect", { x: p.x - bw / 2, y: p.y - bh / 2, width: bw, height: bh, rx: 8 }));'
    '\n      g.appendChild(svg("text", { x: p.x - bw / 2 + 11, y: p.y - 3, "class": "g-l1" }, fitText(line'
    's[0], maxChars)));\n      g.appendChild(svg("text", { x: p.x - bw / 2 + 11, y: p.y + 14, "class": "g-'
    'l2" }, fitText(lines[1], Math.floor((bw - 22) / 6))));\n      s.appendChild(g);\n    });\n    box.appen'
    'dChild(s);\n    caption.textContent = "Mostrando " + subset.length + " de " + nodes.length + " nodos '
    'filtrados y " + drawn + " relaciones entre ellos (vista acotada a 13 nodos: workspace, referencias I'
    'NFERRED y nodos más conectados). Las tablas contienen el 100 % de los nodos, aristas y puntos ciegos'
    '.";\n  }\n\n  function renderReferenceArchitecture() {\n    var box = document.getElementById("ref-arch-'
    'box");\n    clear(box);\n    var s = svg("svg", { viewBox: "0 0 1200 236", role: "img", "aria-label": '
    '"Arquitectura de referencia Azure Databricks Lakehouse - Propuesta NO desplegada" });\n    var flag ='
    ' svg("g", { "class": "ref-flag" });\n    flag.appendChild(svg("rect", { x: 0, y: 4, width: 300, heigh'
    't: 24, rx: 12 }));\n    flag.appendChild(svg("text", { x: 14, y: 20 }, "PROPUESTA DE REFERENCIA · NO '
    'DESPLEGADA"));\n    s.appendChild(flag);\n    var boxes = [\n      ["Red y Perímetro (ARM)", "VNet Inje'
    'ction + SCC + Private Link"],\n      ["Identidad y Secretos", "Entra SP/UAMI + Key Vault Scopes"],\n  '
    '    ["Cómputo y Orquestación", "Cluster Policies + Job/Serverless"],\n      ["Unity Catalog & ADLS", '
    '"Access Connector UAMI + Linaje"]\n    ];\n    var bw = 262, gap = (1200 - 4 * bw) / 3;\n    boxes.forE'
    'ach(function (b, i) {\n      var x = i * (bw + gap);\n      if (i < boxes.length - 1) { s.appendChild('
    'svg("line", { x1: x + bw, y1: 92, x2: x + bw + gap, y2: 92, "class": "ref-link" })); }\n      var g ='
    ' svg("g", { "class": "ref-box" });\n      g.appendChild(svg("rect", { x: x + 1, y: 52, width: bw - 2,'
    ' height: 80, rx: 10 }));\n      g.appendChild(svg("text", { x: x + 18, y: 86, "class": "ref-t" }, b[0'
    ']));\n      g.appendChild(svg("text", { x: x + 18, y: 108, "class": "ref-s" }, b[1]));\n      s.append'
    'Child(g);\n    });\n    s.appendChild(svg("text", { x: 0, y: 176, "class": "ref-note" }, "PROPUESTA DE'
    ' REFERENCIA (NO DESPLEGADA): Integración entre tenants mediante Entra Multi-tenant FIC o Lighthouse '
    '+ Databricks OIDC."));\n    s.appendChild(svg("text", { x: 0, y: 204, "class": "ref-s" }, "Componente'
    's recomendados para comparar con el mapa observado; ninguno se ha detectado ni creado en el workspac'
    'e revisado."));\n    box.appendChild(s);\n    renderTable(document.getElementById("ref-arch-table"),\n '
    '     ["Componente de referencia", "Práctica recomendada Microsoft / Databricks", "Compromiso / Trade'
    '-off"],\n      [\n        ["VNet Injection + Secure Cluster Connectivity", "Desplegar en VNet propia c'
    'on enableNoPublicIp=true y subredes delegadas host/container con NSG.", "Exige planificación IPAM y '
    'rutas salientes hacia endpoints de plano de control."],\n        ["Private Link (Front-end / Back-end'
    ' / WebAuth)", "Aislar tráfico de usuarios y plano de datos mediante Private Endpoints aprobados y zo'
    'nas DNS privadas.", "Requiere SKU Premium y gestión de DNS privado entre redes hub-spoke."],\n       '
    ' ["Unity Catalog + Access Connector (UAMI)", "Gobernar catálogos y External Locations con Storage Cr'
    'edentials basadas en Managed Identity.", "Sustituye claves compartidas y montajes DBFS heredados."],'
    '\n        ["Jobs sobre Job Compute / Serverless + Service Principal", "Ejecutar jobs productivos con '
    'run_as Service Principal sobre cómputo efímero de Job o Serverless.", "Reduce coste DBU frente a All'
    '-Purpose y evita fallos por baja de usuarios."],\n        ["Integración Cross-Tenant sin secretos", "'
    'Usar App multitenant con Federated Identity Credential (UAMI) o Azure Lighthouse (ARM) + Databricks '
    'OIDC Federation.", "Requiere consentimiento/asignación por administradores de ambos tenants."]\n     '
    ' ].map(function (r) { return [{ v: el("b", { text: r[0] }) }, r[1], r[2]]; })\n    );\n  }\n\n  function'
    ' applyDependencyFilters() {\n    if (!currentSnap) { return; }\n    var layer = document.getElementByI'
    'd("dep-layer-filter").value;\n    var cls = document.getElementById("dep-class-filter").value;\n    va'
    'r q = (document.getElementById("dep-search-filter").value || "").toLowerCase().trim();\n    var dep ='
    ' currentSnap.dependencies || { nodes: [], edges: [], unknowns: [], broken_references: [] };\n    func'
    'tion keep(r) {\n      if (layer !== "all" && r.layer !== layer) { return false; }\n      if (cls !== "'
    'all" && r.classification !== cls) { return false; }\n      if (q && JSON.stringify(r).toLowerCase().i'
    'ndexOf(q) === -1) { return false; }\n      return true;\n    }\n    var nodes = (dep.nodes || []).filte'
    'r(keep);\n    var edges = (dep.edges || []).filter(keep);\n    var unknowns = (dep.unknowns || []).fil'
    'ter(keep);\n    var byId = {};\n    (dep.nodes || []).forEach(function (n) { byId[n.id] = n; });\n    f'
    'unction nodeCell(id) {\n      var n = byId[id];\n      return n ? { v: stack(brk(n.label || n.id, ""),'
    ' lab(L.kind, n.kind)), s: n.label || n.id } : { v: brk(id) };\n    }\n    renderNeighborhoodSvg(nodes,'
    ' edges);\n    document.getElementById("dep-edges-count").textContent = String(edges.length);\n    rend'
    'erTable(document.getElementById("dep-edges-table"),\n      ["Clasificación", "Capa", "Origen", "Relac'
    'ión", "Destino", "Campos join", "Fuentes"],\n      edges.map(function (e) {\n        return [\n        '
    '  { v: clsPill(e.classification), s: e.classification },\n          lab(L.layer, e.layer),\n          '
    'nodeCell(e.from),\n          { v: brk(e.relation), s: e.relation },\n          nodeCell(e.to),\n       '
    '   { v: brk((e.join_fields || []).join(", ")) },\n          { v: brk((e.source_ids || []).join(", "))'
    ' }\n        ];\n      }), { page: 12, sortable: true }\n    );\n    document.getElementById("dep-nodes-c'
    'ount").textContent = String(nodes.length);\n    renderTable(document.getElementById("dep-nodes-table"'
    '),\n      ["Clasificación", "Capa", "Tipo", "Nombre / etiqueta", "Fuente", { t: "Evidencia", s: false'
    ', c: "w" }],\n      nodes.map(function (n) {\n        return [\n          { v: clsPill(n.classification'
    '), s: n.classification },\n          lab(L.layer, n.layer),\n          { v: kindLabel(n.kind) },\n     '
    '     { v: brk(n.label || n.id, ""), s: n.label },\n          { v: mono(n.source_id) },\n          { v:'
    ' evidenceCell(n.evidence) }\n        ];\n      }), { page: 12, sortable: true }\n    );\n    var broken '
    '= dep.broken_references || [];\n    document.getElementById("dep-broken-count").textContent = String('
    'broken.length);\n    renderTable(document.getElementById("dep-broken-table"),\n      ["Objeto origen",'
    ' "Tipo de referencia rota", "ID destino no encontrado"],\n      broken.map(function (b) { return [b.s'
    'ource_object, b.kind, { v: brk(b.target_id) }]; }),\n      { empty: "Sin referencias rotas entre tare'
    'as, clústeres, pools, políticas, pipelines, warehouses y credenciales." }\n    );\n    document.getEle'
    'mentById("dep-unknowns-count").textContent = String(unknowns.length);\n    renderTable(document.getEl'
    'ementById("dep-unknowns-table"),\n      ["Capa", "Código", "Descripción del punto ciego", "Fuentes"],'
    '\n      unknowns.map(function (u) {\n        return [lab(L.layer, u.layer), { v: brk(u.code) }, u.mess'
    'age, { v: brk((u.source_ids || []).join(", ")) }];\n      })\n    );\n  }\n\n  function observedValues(ev'
    'idence) {\n    var merged = {};\n    (Array.isArray(evidence) ? evidence : []).forEach(function (ev) {'
    '\n      if (ev && ev.value && typeof ev.value === "object" && !Array.isArray(ev.value)) {\n        Obj'
    'ect.keys(ev.value).forEach(function (k) { merged[k] = ev.value[k]; });\n      }\n    });\n    return kv'
    'Chips(merged, 3);\n  }\n  function filteredChecks() {\n    var area = document.getElementById("find-are'
    'a-filter").value;\n    var level = document.getElementById("find-level-filter").value;\n    var sev = '
    'document.getElementById("find-sev-filter").value;\n    var st = document.getElementById("find-status-'
    'filter").value;\n    var q = (document.getElementById("find-search-filter").value || "").toLowerCase('
    ').trim();\n    return (currentSnap.checks || []).filter(function (c) {\n      if (area !== "all" && c.'
    'area !== area) { return false; }\n      if (level !== "all" && c.level !== level) { return false; }\n '
    '     if (sev !== "all" && c.severity !== sev) { return false; }\n      if (st !== "all" && c.status !'
    '== st) { return false; }\n      if (q && JSON.stringify(c).toLowerCase().indexOf(q) === -1) { return '
    'false; }\n      return true;\n    });\n  }\n  function applyFindingFilters() {\n    if (!currentSnap) { r'
    'eturn; }\n    var all = currentSnap.checks || [];\n    var filtered = filteredChecks().slice().sort(fu'
    'nction (a, b) {\n      return (STATUS_ORDER[a.status] - STATUS_ORDER[b.status]) || (SEVS.indexOf(a.se'
    'verity) - SEVS.indexOf(b.severity)) || String(a.rule_id).localeCompare(String(b.rule_id), "es", { nu'
    'meric: true });\n    });\n    var failed = filtered.filter(function (c) { return c.status === "failed"'
    '; }).length;\n    document.getElementById("findings-count-label").textContent = "Mostrando " + filter'
    'ed.length + " de " + all.length + " comprobaciones · " + failed + plural(failed, " no cumple", " no '
    'cumplen") + ".";\n    renderTable(document.getElementById("findings-table"),\n      [{ t: "Estado" }, '
    '{ t: "Severidad" }, { t: "Regla" }, { t: "Área / pilar" }, { t: "Objeto" }, { t: "Hallazgo y evidenc'
    'ia", c: "w" }, { t: "Recomendación", c: "w" }],\n      filtered.map(function (c) {\n        var link ='
    ' safeLearnUrl(c.learn_url);\n        var detail = el("div", { className: "fd" });\n        detail.appe'
    'ndChild(el("b", { text: c.title }));\n        detail.appendChild(el("p", { text: c.reason }));\n      '
    '  var chips = observedValues(c.evidence);\n        if (chips) { detail.appendChild(chips); }\n        '
    'var rec = el("div", { className: "fr" });\n        rec.appendChild(el("p", { text: c.recommendation }'
    '));\n        if (link) { rec.appendChild(extLink(link, "Documentación oficial")); }\n        return [\n'
    '          { v: statusTag(c.status), s: STATUS_ORDER[c.status] },\n          { v: sevPill(c.severity, '
    'c.severity_label), s: SEVS.indexOf(c.severity) },\n          { v: stack(c.rule_id, mono(c.reference_i'
    'd)), s: c.rule_id },\n          { v: stack(lab(L.area, c.area), lab(L.pillar, c.pillar)), s: lab(L.ar'
    'ea, c.area) },\n          { v: stack(brk(c.workload_name || c.resource_name || c.workspace_name, ""),'
    ' lab(L.level, c.level)), s: c.workload_name || c.resource_name || "" },\n          { v: detail, s: c.'
    'title },\n          { v: rec, s: c.recommendation }\n        ];\n      }), { page: 15, sortable: true }'
    '\n    );\n  }\n\n  ["dep-layer-filter", "dep-class-filter", "dep-search-filter"].forEach(function (id) {'
    '\n    document.getElementById(id).addEventListener("input", applyDependencyFilters);\n    document.get'
    'ElementById(id).addEventListener("change", applyDependencyFilters);\n  });\n  ["find-area-filter", "fi'
    'nd-level-filter", "find-sev-filter", "find-status-filter", "find-search-filter"].forEach(function (i'
    'd) {\n    document.getElementById(id).addEventListener("input", applyFindingFilters);\n    document.ge'
    'tElementById(id).addEventListener("change", applyFindingFilters);\n  });\n  document.getElementById("d'
    'ep-clear").addEventListener("click", function () {\n    document.getElementById("dep-layer-filter").v'
    'alue = "all";\n    document.getElementById("dep-class-filter").value = "all";\n    document.getElement'
    'ById("dep-search-filter").value = "";\n    applyDependencyFilters();\n  });\n  document.getElementById('
    '"find-clear").addEventListener("click", function () {\n    ["find-area-filter", "find-level-filter", '
    '"find-sev-filter", "find-status-filter"].forEach(function (id) { document.getElementById(id).value ='
    ' "all"; });\n    document.getElementById("find-search-filter").value = "";\n    applyFindingFilters();'
    '\n  });\n  document.getElementById("find-export-btn").addEventListener("click", function () {\n    if ('
    '!currentSnap) { return; }\n    downloadBlob("databricks-findings-filtered.csv", checksCsv(filteredChe'
    'cks()), "text/csv;charset=utf-8");\n  });\n\n  function barRow(label, sub, width, value, valueSub, colo'
    'r, na) {\n    var row = el("div", { className: "brow" + (na ? " na" : "") });\n    var bl = el("div", '
    '{ className: "bl" }, [label]);\n    if (sub) { bl.appendChild(el("small", { text: sub })); }\n    row.'
    'appendChild(bl);\n    var bar = el("i");\n    bar.style.width = Math.max(0, Math.min(100, width)) + "%'
    '";\n    if (color) { bar.style.background = color; }\n    if (na || !width) { bar.style.minWidth = "0"'
    '; }\n    row.appendChild(el("div", { className: "bt" }, [bar]));\n    var bv = el("div", { className: '
    '"bv", text: value });\n    if (valueSub) { bv.appendChild(el("small", { text: valueSub })); }\n    row'
    '.appendChild(bv);\n    return row;\n  }\n  function scoreBars(id, map, labels) {\n    var holder = docum'
    'ent.getElementById(id);\n    clear(holder);\n    Object.keys(map || {}).forEach(function (k) {\n      v'
    'ar it = map[k] || {}, na = !isNum(it.score);\n      holder.appendChild(barRow(lab(labels, k), null, n'
    'a ? 0 : it.score, na ? "No evaluado" : pct(it.score),\n        "cobertura " + (isNum(it.coverage_perc'
    'ent) ? pct(it.coverage_percent) : "0\\u00a0%"), null, na));\n    });\n  }\n  function kpi(value, unit, l'
    'abel, sub) {\n    var v = el("div", { className: "v" }, [String(value)]);\n    if (unit) { v.appendChi'
    'ld(el("small", { text: unit })); }\n    return el("div", { className: "kpi" }, [v, el("div", { classN'
    'ame: "l", text: label }), sub ? el("div", { className: "s", text: sub }) : null]);\n  }\n  function pc'
    'tParts(v) { return isNum(v) ? [NF.format(v), "%"] : ["—", ""]; }\n  function sourcePlane(id) {\n    id'
    ' = String(id || "");\n    if (id.indexOf("arm_") === 0 || id === "azure_cost") { return "Plano 1 · AR'
    'M"; }\n    if (id.indexOf("dbx_") === 0) { return "Plano 2 · Databricks REST"; }\n    if (id.indexOf("'
    'uc_") === 0) { return "Plano 2 · Unity Catalog"; }\n    return "Interno";\n  }\n  var SRC_COLOR = { com'
    'plete: "var(--ok-bar)", partial: "var(--med-bar)", denied: "var(--crit-bar)", error: "var(--crit-bar'
    ')", not_configured: "var(--info-bar)", not_applicable: "var(--line2)" };\n\n  function renderHero(snap'
    ', g, counts) {\n    var ws = snap.workspace || {}, sc = (snap.dependencies && snap.dependencies.summa'
    'ry_counts) || {};\n    var fails = (snap.findings || []).length, ev = g.evaluated || 0;\n    var sevTe'
    'xt = SEVS.filter(function (s) { return counts[s]; }).map(function (s) { return counts[s] + " " + plu'
    'ral(counts[s], SEV_WORD[s][0], SEV_WORD[s][1]); }).join(" · ");\n    var depParts = [" El mapa de dep'
    'endencias reúne ", [num(sc.nodes_total || 0)], " nodos y ", [num(sc.edges_total || 0)], " relaciones'
    ', con ", [num(sc.edges_inferred || 0)], " referencias INFERRED y ", [num(sc.unknowns_total || 0)], "'
    ' puntos ciegos UNKNOWN."];\n    var ch = (snap.databricks_costs && snap.databricks_costs.headline) ||'
    ' {};\n    if (isNum(ch.review_total)) {\n      costCurrency = snap.databricks_costs.currency || "";\n  '
    '    depParts = depParts.concat([" Databricks costó ", [money(ch.review_total)], " en " + monthName(c'
    'h.review_month)].concat(\n        isNum(ch.estimated_monthly_savings) ? ["; ahorro estimado ", ["≈ " '
    '+ money(ch.estimated_monthly_savings)], " al mes (sección de costes)."] : ["."]));\n    }\n    rich(do'
    'cument.getElementById("cover-lead"), ev ? [[num(fails)], plural(fails, " comprobación no cumple", " '
    'comprobaciones no cumplen"), sevText ? " (" + sevText + ")" : "", " de ", [num(ev)], " evaluadas; ín'
    'dice local ", [pct(g.score)], " con una cobertura del ", [pct(g.coverage_percent)], "."].concat(depP'
    'arts)\n      : ["Ninguna comprobación pudo evaluarse con las fuentes disponibles; revise la cobertura'
    ' en la sección 8."].concat(depParts));\n    var meta = document.getElementById("cover-badges");\n    c'
    'lear(meta);\n    function chip(parts, on, title) { meta.appendChild(rich(el("span", { className: on ?'
    ' "on" : null, title: title || null }), parts)); }\n    chip(["Generado ", [utc(snap.reference_utc)]])'
    ';\n    chip(["Workspace ", [ws.name || "—"]]);\n    chip([[ws.cross_tenant ? "Entre tenants" : "Mismo '
    'tenant"], " · " + (ws.auth_mode || "—")], false, ws.cross_tenant ? (ws.sre_tenant_id || "—") + " → "'
    ' + (ws.target_tenant_id || "—") : ws.target_tenant_id);\n    chip(["Entorno ", [snap.environment || "'
    '—"]]);\n    chip([snap.provenance === "SIMULATED" ? "DATOS SIMULADOS" : "DATOS " + (snap.provenance |'
    '| "LIVE")], true);\n\n    var tone = "ok", title = counts.low ? "Sin desviaciones relevantes" : "Sin d'
    'esviaciones observadas";\n    if (!ev) { tone = "info"; title = "Sin evaluar"; }\n    else if (counts.'
    'critical) { tone = "crit"; title = "Acción requerida"; }\n    else if (counts.high || counts.medium) '
    '{ tone = "warn"; title = "Requiere atención"; }\n    var lowCov = isNum(g.coverage_percent) && g.cove'
    'rage_percent < 50;\n    if (lowCov && tone === "ok") { tone = "warn"; title = "Cobertura insuficiente'
    '"; }\n    var verdict = document.getElementById("verdict");\n    verdict.className = "signal " + tone;'
    '\n    clear(verdict);\n    verdict.appendChild(el("div", { className: "k", text: "Veredicto" }));\n    '
    'verdict.appendChild(el("b", { text: title }));\n    verdict.appendChild(el("p", { text: (ev ? (sevTex'
    't || "Ningún hallazgo") + " · cobertura " + pct(g.coverage_percent) : "Ninguna comprobación evaluada'
    '") + (lowCov ? " · solo " + ev + " de " + (ev + (g.not_evaluated || 0)) + " evaluadas" : "") }));\n\n '
    '   var dist = document.getElementById("severity-dist");\n    clear(dist);\n    dist.hidden = !fails;\n '
    '   if (fails) {\n      dist.appendChild(rich(el("div", { className: "dist-head" }), ["Hallazgos por s'
    'everidad", ""]));\n      dist.firstChild.appendChild(rich(el("span"), [[num(fails)], " de " + num(g.t'
    'otal || 0) + " comprobaciones no cumplen"]));\n      var track = el("div", { className: "track", role'
    ': "img", "aria-label": sevText });\n      var legend = el("div", { className: "legend" });\n      SEVS'
    '.forEach(function (s) {\n        if (!counts[s]) { return; }\n        var seg = el("i", { title: L.sev'
    '[s] + ": " + counts[s] });\n        seg.style.width = (100 * counts[s] / fails) + "%";\n        seg.st'
    'yle.background = SEV_BAR[s];\n        track.appendChild(seg);\n        var key = el("i");\n        key.'
    'style.background = SEV_BAR[s];\n        legend.appendChild(el("span", null, [key, L.sev[s] + " ", el('
    '"b", { text: String(counts[s]) })]));\n      });\n      dist.appendChild(track);\n      dist.appendChil'
    'd(legend);\n    }\n\n    var client = snap.client || { name: "CLIENTE", logo_data_uri: "", logo_alt: "L'
    'ogotipo autorizado del cliente" };\n    var plaque = document.getElementById("brand-plaque");\n    cle'
    'ar(plaque);\n    var hasLogo = client.logo_data_uri && /^data:image\\/(png|jpeg);base64,[A-Za-z0-9+/=]'
    '+$/.test(client.logo_data_uri);\n    if (hasLogo) { plaque.appendChild(el("img", { src: client.logo_d'
    'ata_uri, alt: client.logo_alt || client.name || "CLIENTE" })); }\n    else { plaque.appendChild(el("s'
    'pan", { className: "brand-placeholder", text: client.name || "CLIENTE" })); }\n    var nameLabel = do'
    'cument.getElementById("client-name-label");\n    nameLabel.textContent = client.name || "CLIENTE";\n  '
    '  nameLabel.hidden = !hasLogo;\n  }\n\n  function renderKpis(snap, g, counts) {\n    var sc = (snap.depe'
    'ndencies && snap.dependencies.summary_counts) || {}, fin = snap.finops || {};\n    var fails = (snap.'
    'findings || []).length, ev = g.evaluated || 0;\n    var holder = document.getElementById("kpis");\n   '
    ' clear(holder);\n    var sevText = SEVS.filter(function (s) { return counts[s]; }).map(function (s) {'
    ' return counts[s] + " " + plural(counts[s], SEV_WORD[s][0], SEV_WORD[s][1]); }).join(" · ");\n    var'
    ' sp = pctParts(g.score), cp = pctParts(g.coverage_percent);\n    var hasCost = isNum(fin.actual_cost)'
    ';\n    var win = fin.window ? day(fin.window.start).slice(5) + " → " + day(fin.window.end).slice(5) :'
    ' null;\n    var cm = snap.databricks_costs || {}, ch = cm.headline || {};\n    costCurrency = cm.curre'
    'ncy || "";\n    var costKpi = isNum(ch.review_total)\n      ? kpi(NF0.format(ch.review_total), cm.curr'
    'ency || "", "Coste Databricks", monthName(ch.review_month).split(" de ")[0] + (isNum(ch.dbu_share) ?'
    ' " · " + NF0.format(ch.dbu_share) + " % DBU" : "") + (isNum(ch.estimated_monthly_savings) ? " · ahor'
    'ro ≈ " + money(ch.estimated_monthly_savings) + "/mes" : " · " + signedPct(ch.change_pct) + " vs mes '
    'anterior"))\n      : kpi(hasCost ? NF2.format(fin.actual_cost) : "—", hasCost ? (fin.currency || "") '
    ': "", "Coste observado", hasCost ? "ActualCost · " + (win || "periodo acumulado") : "No evaluado");\n'
    '    var list = FOCUS === "costs" && isNum(ch.review_total) ? [\n      kpi(NF0.format(ch.review_total)'
    ', cm.currency || "", "Coste de " + monthName(ch.review_month).split(" de ")[0], signedPct(ch.change_'
    'pct) + " frente a " + monthName(ch.previous_month).split(" de ")[0]),\n      kpi(NF0.format(ch.mtd_to'
    'tal), cm.currency || "", "Mes en curso", "hasta el día " + ch.mtd_days + " de " + monthName(ch.curre'
    'nt_month).split(" de ")[0]),\n      kpi(NF0.format(ch.dbu_share || 0), "%", "DBU", NF0.format(100 - ('
    'ch.dbu_share || 0)) + " % infraestructura (" + money(ch.infra_total) + ")"),\n      kpi(isNum(ch.unat'
    'tributed_share) ? NF1.format(ch.unattributed_share) : "—", isNum(ch.unattributed_share) ? "%" : "", '
    '"Sin etiqueta de cómputo", isNum(ch.unattributed_total) ? money(ch.unattributed_total) + " sin atrib'
    'uir" : "No evaluado"),\n      kpi(isNum(ch.estimated_monthly_savings) ? NF0.format(ch.estimated_month'
    'ly_savings) : "—", isNum(ch.estimated_monthly_savings) ? cm.currency || "" : "", "Ahorro estimado al'
    ' mes", ch.savings_signals + " de " + ch.signals + " señales, sin contar dos veces"),\n      kpi(num(f'
    'ails), "", "Hallazgos de configuración", sevText || "Sin desviaciones observadas")\n    ] : [\n      k'
    'pi(num(fails), "", "Hallazgos", sevText || "Sin desviaciones observadas"),\n      kpi(sp[0], sp[1], "'
    'Índice local", ev ? "Sobre " + ev + " evaluadas" : "Sin comprobaciones evaluadas"),\n      kpi(cp[0],'
    ' cp[1], "Cobertura evaluada", ev + " de " + (ev + (g.not_evaluated || 0)) + " aplicables"),\n      kp'
    'i(num(sc.edges_total || 0), "", "Relaciones", num(sc.edges_observed || 0) + " OBSERVED · " + num(sc.'
    'edges_inferred || 0) + " INFERRED"),\n      kpi(num(sc.unknowns_total || 0), "", "Puntos ciegos UNKNO'
    'WN", num(sc.broken_references_total || 0) + plural(sc.broken_references_total || 0, " referencia rot'
    'a", " referencias rotas")),\n      costKpi\n    ];\n    list.forEach(function (k) { holder.appendChild('
    'k); });\n\n    var notices = document.getElementById("notices");\n    clear(notices);\n    if (snap.prov'
    'enance === "SIMULATED") {\n      notices.appendChild(el("div", { className: "sim", role: "note" }, [i'
    'con("alert"), el("span", { text: "Datos simulados: este informe procede de un conjunto sintético de '
    'pruebas; las cifras no describen un workspace real." })]));\n    }\n    var gaps = (snap.sources || []'
    ').filter(function (s) { return s.status !== "complete" && s.status !== "not_applicable"; });\n    if '
    '(gaps.length) {\n      var listed = gaps.slice(0, 6).map(function (s) { return s.id + " (" + lab(L.sr'
    'c, s.status).toLowerCase() + ")"; }).join(", ") + (gaps.length > 6 ? " y " + (gaps.length - 6) + " m'
    'ás" : "");\n      notices.appendChild(el("div", { className: "note", role: "note" }, [icon("info"), e'
    'l("span", { text: gaps.length + plural(gaps.length, " fuente sin datos completos: ", " fuentes sin d'
    'atos completos: ") + listed + ". Las comprobaciones que dependen de ellas figuran como No evaluado ('
    'sección 8)." })]));\n    }\n  }\n\n  function renderFacts(snap) {\n    var ws = snap.workspace || {};\n   '
    ' var facts = document.getElementById("cover-facts");\n    clear(facts);\n    function fact(label, main'
    ', sub) {\n      var dd = el("dd");\n      if (main instanceof Node) { dd.appendChild(main); } else { d'
    'd.textContent = main === null || main === undefined || main === "" ? "—" : String(main); }\n      if '
    '(sub instanceof Node) { var w = el("small"); w.appendChild(sub); dd.appendChild(w); } else if (sub) '
    '{ dd.appendChild(el("small", { text: sub })); }\n      facts.appendChild(el("div", null, [el("dt", { '
    'text: label }), dd]));\n    }\n    fact("Workspace", ws.name, brk(ws.workspace_url || "—"));\n    fact('
    '"Recurso ARM", armCell(ws.id, ws.name));\n    fact("Grupo administrado", brk(ws.managed_resource_grou'
    'p || "—", ""));\n    fact("Región · SKU", (ws.region || "—") + " · " + (ws.sku_name || "—"), ws.sku_t'
    'ier ? "Nivel " + ws.sku_tier : null);\n    fact("Red", "Acceso público: " + access(ws.public_network_'
    'access), "Sin IP pública (NPIP): " + yesNo(ws.enable_no_public_ip) + (ws.custom_virtual_network_id ?'
    ' " · VNet inyectada" : ""));\n    fact("Autenticación", ws.auth_mode || "—", ws.cross_tenant ? "Entre'
    ' tenants" : "Mismo tenant");\n    var tenants = el("span");\n    if (ws.cross_tenant) { tenants.append'
    'Child(mono(ws.sre_tenant_id)); tenants.appendChild(el("br")); tenants.appendChild(mono("→ " + (ws.ta'
    'rget_tenant_id || "—"))); }\n    else { tenants.appendChild(mono(ws.target_tenant_id)); }\n    fact(ws'
    '.cross_tenant ? "Tenant SRE → tenant destino" : "Tenant", tenants);\n    fact("Unity Catalog por defe'
    'cto", ws.default_catalog_name || "—", ws.default_catalog_type || null);\n  }\n\n  function renderExecut'
    'ive(snap, g) {\n    var msgList = document.getElementById("executive-messages");\n    clear(msgList);\n'
    '    (snap.executive_messages || []).forEach(function (m) { msgList.appendChild(el("li", { text: m })'
    '); });\n    var total = Math.max(1, g.total || 0);\n    var status = document.getElementById("check-st'
    'atus");\n    clear(status);\n    [\n      ["passed", "Configuración observada conforme con la regla loc'
    'al.", "var(--ok-bar)"],\n      ["failed", "Desviación o referencia rota observada.", "var(--crit-bar)'
    '"],\n      ["not_evaluated", "Fuente no disponible, requisito no confirmado o alcance sin cómputo.", '
    '"var(--info-bar)"],\n      ["not_applicable", "Excluido del denominador por tipo de objeto o requisit'
    'o falso.", "var(--line2)"]\n    ].forEach(function (r) {\n      var n = g[r[0]] || 0;\n      status.app'
    'endChild(barRow(el("span", { className: "st st-" + r[0], text: L.status[r[0]] }), r[1], 100 * n / to'
    'tal, num(n), NF.format(100 * n / total) + "\\u00a0%", r[2], !n));\n    });\n    scoreBars("area-scores"'
    ', snap.scores && snap.scores.areas, L.area);\n    scoreBars("pillar-scores", snap.scores && snap.scor'
    'es.pillars, L.pillar);\n    var list = document.getElementById("priority-findings");\n    clear(list);'
    '\n    var priorities = (snap.findings || []).filter(function (f) { return f.severity === "critical" |'
    '| f.severity === "high"; })\n      .sort(function (a, b) { return SEVS.indexOf(a.severity) - SEVS.ind'
    'exOf(b.severity); });\n    if (!priorities.length) { list.appendChild(el("li", null, [emptyState("Sin'
    ' hallazgos críticos ni de severidad alta en las comprobaciones evaluadas.")])); }\n    priorities.for'
    'Each(function (f) {\n      list.appendChild(el("li", null, [\n        sevPill(f.severity, f.severity_l'
    'abel),\n        el("div", { className: "pt", text: f.title }),\n        el("div", { className: "pm", t'
    'ext: f.rule_id + " · " + lab(L.level, f.level) + (f.workload_name ? ": " + f.workload_name : "") + "'
    ' — " + (f.business_impact || f.reason || "") })\n      ]));\n    });\n  }\n\n  function renderInventory(s'
    'nap) {\n    var inv = snap.inventory || {};\n    function count(id, n, word) { document.getElementById'
    '(id).textContent = n + " " + word; }\n    var computeRows = [].concat(inv.clusters || [], inv.instanc'
    'e_pools || [], inv.cluster_policies || [], inv.global_init_scripts || []);\n    count("inv-compute-co'
    'unt", computeRows.length, plural(computeRows.length, "objeto", "objetos"));\n    renderTable(document'
    '.getElementById("inv-compute-table"),\n      ["Tipo", "Nombre / ID", "Estado / runtime", "Acceso / au'
    'toterminación", "Política / pool"],\n      computeRows.map(function (r) {\n        return [\n          '
    '{ v: kindLabel(r.kind) },\n          { v: stack(r.name || "—", mono(r.id)), s: r.name },\n          { '
    'v: stack(r.state || "—", r.spark_version ? mono(r.spark_version) : null), s: r.state },\n          (r'
    '.data_security_mode || "—") + (r.autotermination_minutes !== undefined && r.autotermination_minutes '
    '!== null ? " · " + r.autotermination_minutes + " min" : ""),\n          { v: stack(r.policy_id ? mono'
    '(r.policy_id) : "—", r.instance_pool_id ? mono("Pool: " + r.instance_pool_id) : null) }\n        ];\n '
    '     }), { sortable: true }\n    );\n    var orchRows = [];\n    (inv.jobs || []).forEach(function (j) '
    '{\n      var tasks = el("div", { className: "chips" });\n      (j.tasks || []).forEach(function (t) { '
    'tasks.appendChild(el("span", { text: t.task_key })); });\n      orchRows.push([{ v: kindLabel("Job") '
    '}, { v: stack(j.name, mono(j.id)), s: j.name }, j.scheduled ? "Programado" : "Sin programación",\n   '
    '     { v: stack(j.run_as_service_principal ? "Service principal" : "Usuario (sin SP)", j.run_as_serv'
    'ice_principal ? mono(j.run_as_service_principal) : null) },\n        { v: (j.tasks || []).length ? ta'
    'sks : "—" }]);\n    });\n    (inv.pipelines || []).forEach(function (p) {\n      orchRows.push([{ v: ki'
    'ndLabel("dlt_pipeline") }, { v: stack(p.name, mono(p.id)), s: p.name }, p.state || "—", "Serverless:'
    ' " + yesNo(p.serverless),\n        "Catálogo " + (p.catalog || "hive_metastore") + " · destino " + (p'
    '.target || "—")]);\n    });\n    (inv.sql_warehouses || []).forEach(function (w) {\n      orchRows.push'
    '([{ v: kindLabel("sql_warehouse") }, { v: stack(w.name, mono(w.id)), s: w.name }, (w.state || "—") +'
    ' " · " + (w.cluster_size || "—"),\n        "Serverless: " + yesNo(w.enable_serverless_compute) + " · '
    'auto-stop " + (isNum(w.auto_stop_mins) ? w.auto_stop_mins + " min" : "—"), w.warehouse_type || "—"])'
    ';\n    });\n    count("inv-orchestration-count", orchRows.length, plural(orchRows.length, "objeto", "o'
    'bjetos"));\n    renderTable(document.getElementById("inv-orchestration-table"),\n      ["Tipo", "Nombr'
    'e / ID", "Estado / programación", "Identidad / modo", "Tareas / destino"], orchRows, { sortable: tru'
    'e });\n    var ucRows = [];\n    if (inv.uc_metastore) {\n      ucRows.push([L.kind.uc_metastore, { v: '
    'brk(inv.uc_metastore.name, "") }, { v: mono(inv.uc_metastore.id) }, { v: brk(inv.uc_metastore.storag'
    'e_root || "—") }, "Región " + (inv.uc_metastore.region || "—")]);\n    }\n    (inv.uc_catalogs || []).'
    'forEach(function (c) { ucRows.push([L.kind.uc_catalog, { v: brk(c.name, "") }, c.catalog_type || "—"'
    ', { v: brk(c.storage_root || "—") }, "Aislamiento " + (c.isolation_mode || "—")]); });\n    (inv.uc_s'
    'chemas || []).forEach(function (s) { ucRows.push([L.kind.uc_schema, { v: brk(s.full_name, "") }, s.c'
    'atalog_name, { v: brk(s.storage_root || "—") }, "—"]); });\n    (inv.uc_storage_credentials || []).fo'
    'rEach(function (cr) { ucRows.push([L.kind.uc_storage_credential, { v: brk(cr.name, "") }, cr.uses_ma'
    'naged_identity ? "Managed Identity" : "Service Principal", { v: cr.access_connector_id ? armCell(cr.'
    'access_connector_id) : "—" }, "Solo lectura: " + yesNo(cr.read_only)]); });\n    (inv.uc_external_loc'
    'ations || []).forEach(function (loc) { ucRows.push([L.kind.uc_external_location, { v: brk(loc.name, '
    '"") }, "Credencial " + (loc.credential_name || "—"), { v: brk(loc.url || "—") }, "Solo lectura: " + '
    'yesNo(loc.read_only)]); });\n    (inv.uc_connections || []).forEach(function (cn) { ucRows.push([L.ki'
    'nd.uc_connection, { v: brk(cn.name, "") }, cn.connection_type || "—", { v: brk(cn.host || "—") }, "C'
    'redencial " + (cn.credential_type || "—")]); });\n    (inv.secret_scopes || []).forEach(function (sc)'
    ' { ucRows.push([L.kind.secret_scope, { v: brk(sc.name, "") }, sc.backend_type || "—", { v: sc.keyvau'
    'lt_resource_id ? armCell(sc.keyvault_resource_id) : brk(sc.keyvault_dns_name || "—") }, "Valores nun'
    'ca leídos"]); });\n    count("inv-uc-count", ucRows.length, plural(ucRows.length, "objeto", "objetos"'
    '));\n    renderTable(document.getElementById("inv-uc-table"), ["Objeto", "Nombre", "Tipo / credencial'
    '", { t: "URI / recurso", c: "w" }, "Detalle"], ucRows, { sortable: true });\n    var resRows = [];\n  '
    '  (inv.related_resources || []).forEach(function (r) {\n      var a = r.association || {};\n      resR'
    'ows.push([{ v: kindLabel(r.resource_kind) }, { v: armCell(r.id, r.name), s: r.name },\n        { v: s'
    'tack(a.type || "—", brk([a.source_id, a.field].filter(Boolean).join(" · "))) }, { v: evidenceCell(r.'
    'configuration) }]);\n    });\n    (inv.outbound_endpoints || []).forEach(function (o) {\n      var chip'
    's = el("div", { className: "chips" });\n      (o.endpoints || []).forEach(function (ep) {\n        var'
    ' ports = (ep.details || []).map(function (d) { return d.port; }).filter(Boolean).join(", ");\n       '
    ' chips.appendChild(el("span", { text: (ep.domain_name || ep.domainName || "—") + (ports ? ":" + port'
    's : "") }));\n      });\n      resRows.push([{ v: kindLabel("OutboundDependency") }, { v: stack(o.cate'
    'gory || "—", null), s: o.category }, { v: stack("outboundNetworkDependenciesEndpoints", null) }, { v'
    ': chips.firstChild ? chips : "—" }]);\n    });\n    count("inv-resources-count", resRows.length, plura'
    'l(resRows.length, "recurso o endpoint", "recursos y endpoints"));\n    renderTable(document.getElemen'
    'tById("inv-resources-table"), ["Tipo", "Recurso", "Asociación", { t: "Configuración observada", c: "'
    'w", s: false }], resRows, { sortable: true });\n  }\n\n  function renderFinops(snap) {\n    var fin = sn'
    'ap.finops || {};\n    var legacy = document.getElementById("finops-legacy");\n    var configured = (fi'
    'n.cost_rows || []).length > 0 || fin.cost_source_complete;\n    var amount = document.getElementById('
    '"finops-actual-cost");\n    clear(amount);\n    amount.hidden = !configured;\n    if (isNum(fin.actual_'
    'cost)) { amount.className = "stat"; amount.appendChild(document.createTextNode(NF2.format(fin.actual'
    '_cost) + " ")); amount.appendChild(el("small", { text: fin.currency || "" })); }\n    else { amount.c'
    'lassName = "stat na"; amount.textContent = "No evaluado"; }\n    document.getElementById("finops-cost'
    '-window").textContent = fin.window && configured ? "Ventana " + day(fin.window.start) + " → " + day('
    'fin.window.end) + " · fuente azure_cost " + (fin.cost_source_complete ? "completa" : "incompleta") :'
    ' "Desactivado (cost_scope = disabled). Opcional: importes por ResourceId aprobado, sin reparto por c'
    'arga.";\n    var notes = document.getElementById("finops-cost-note");\n    clear(notes);\n    (configur'
    'ed ? fin.notes || [] : []).forEach(function (n) { notes.appendChild(el("li", { text: n })); });\n    '
    'var table = document.getElementById("finops-cost-table");\n    table.parentNode.hidden = !configured;'
    '\n    renderTable(table,\n      ["Recurso", "Fecha", { t: "Importe", c: "n" }, "Moneda", "Base"],\n    '
    '  (fin.cost_rows || []).map(function (r) {\n        return [{ v: armCell(r.resource_id) }, r.usage_da'
    'te ? day(r.usage_date) : "Periodo acumulado", { v: isNum(r.amount) ? NF2.format(r.amount) : num(r.am'
    'ount), s: r.amount }, r.currency, r.basis];\n      }), { empty: "Sin filas de facturación observadas '
    'en el alcance aprobado." }\n    );\n    legacy.hidden = false;\n  }\n\n  var NF0 = new Intl.NumberFormat('
    '"es-ES", { maximumFractionDigits: 0, useGrouping: "always" });\n  var NF1 = new Intl.NumberFormat("es'
    '-ES", { minimumFractionDigits: 1, maximumFractionDigits: 1 });\n  var MONTHS = ["enero", "febrero", "'
    'marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembr'
    'e"];\n  var C = {\n    family: { all_purpose: "All-purpose (interactivo)", jobs: "Jobs", jobs_light: "'
    'Jobs Light", sql: "SQL warehouses pro y clásicos", sql_serverless: "SQL warehouses serverless",\n    '
    '  pipelines: "Pipelines (DLT)", serverless: "Serverless (notebooks y jobs)", ai: "IA y model serving'
    '", other: "Otros DBU" },\n    category: { "virtual machines": "Máquinas virtuales", storage: "Almacen'
    'amiento y discos", bandwidth: "Transferencia de datos", "virtual network": "Red virtual (NAT, IP púb'
    'licas)",\n      "load balancer": "Load Balancer", "azure databricks": "DBU", "nat gateway": "NAT Gate'
    'way" },\n    gapWhy: { storage: "Almacenamiento raíz del área de trabajo (DBFS) y discos sin clúster"'
    ', "azure databricks": "No llevan etiquetas de Azure: se reparten con políticas de uso serverless o c'
    'on las tablas de sistema",\n      bandwidth: "Transferencia de datos de salida", "virtual network": "'
    'NAT Gateway e IP públicas del área de trabajo", "load balancer": "Load Balancer del área de trabajo"'
    ',\n      "virtual machines": "Máquinas virtuales sin etiquetas de Databricks" },\n    dim: { cluster: '
    '"Clústeres", job: "Jobs", warehouse: "SQL warehouses", pool: "Pools", creators: "Creadores" },\n    k'
    'ind: { all_purpose: "Clúster interactivo", job_run: "Clúster de job", job_runs: "Clústeres efímeros '
    'de jobs", pipeline: "Clúster de pipeline", pipeline_runs: "Clústeres de pipelines (DLT)",\n      not_'
    'in_inventory: "No está en el inventario (eliminado o de otro tipo)", job: "Job", warehouse: "SQL war'
    'ehouse", pool: "Pool" },\n    objKind: { AllPurposeCluster: "Clúster interactivo", Job: "Job", Instan'
    'cePool: "Pool", SqlWarehouse: "SQL warehouse", ClusterPolicy: "Política de cómputo", Runtime: "Runti'
    'me", NodeType: "Tipo de VM" },\n    saving: { lower_bound: "al menos", upper_bound: "hasta", estimate'
    ': "≈" },\n    basis: { weekend_cost: "coste de sábados y domingos del mes", jobs_dbu_ratio: "DBU del '
    'clúster × (1 − ratio jobs/all-purpose)", spot_discount: "VM de workers × descuento spot",\n      dail'
    'y_floor: "coste mínimo diario × días del mes", always_on_weekends: "coste × fines de semana / días d'
    'el mes" },\n    ev: { autotermination_minutes: "autoterminación (min)", state: "estado", uptime_hours'
    ': "encendido (h)", active_days: "días con coste", weekend_cost: "coste en fin de semana",\n      jobs'
    ': "jobs", jobs_count: "nº de jobs", dbu_cost: "coste DBU", availability: "disponibilidad", workers: '
    '"workers", vm_cost: "coste VM", continuous: "continuo",\n      max_workers: "máx. workers", min_idle_'
    'instances: "inactivas mínimas", idle_now: "inactivas ahora", idle_autotermination_minutes: "liberaci'
    'ón de inactivas (min)",\n      daily_floor: "suelo diario", auto_stop_mins: "auto-stop (min)", server'
    'less: "serverless", warehouse_type: "tipo", cluster_size: "tamaño", objects: "objetos",\n      alloca'
    'tion_tags: "etiquetas", supported_list_checked: "lista oficial consultada", deprecated: "retirada" }'
    ',\n    status: { complete: "Completa", partial: "Parcial", denied: "Denegada", error: "Error", skippe'
    'd: "Omitida por tiempo", not_configured: "No configurada", not_collected: "No recogida" }\n  };\n  var'
    ' costCurrency = "";\n  function monthName(label, short) {\n    var m = /^(\\d{4})-(\\d{2})$/.exec(String'
    '(label || ""));\n    if (!m) { return String(label || "—"); }\n    var name = MONTHS[Number(m[2]) - 1]'
    ' || m[2];\n    return short ? name.slice(0, 3) + " " + m[1] : name + " de " + m[1];\n  }\n  function mo'
    'ney(v, cur) {\n    if (!isNum(v)) { return "—"; }\n    return (v === 0 ? "0" : Math.abs(v) < 10 ? NF2.'
    'format(v) : NF0.format(v)) + (cur === "" ? "" : "\\u00a0" + (cur || costCurrency));\n  }\n  function si'
    'gnedPct(v) { return isNum(v) ? (v > 0 ? "+" : v < 0 ? "−" : "") + NF1.format(Math.abs(v)) + "\\u00a0%'
    '" : "—"; }\n  function deltaNode(pct, abs, cur) {\n    if (!isNum(pct) && !isNum(abs)) { return el("sp'
    'an", { className: "muted", text: "sin mes anterior" }); }\n    var up = (isNum(abs) ? abs : pct) > 0;'
    '\n    var text = isNum(pct) ? signedPct(pct) : (abs > 0 ? "+" : "−") + money(Math.abs(abs), cur);\n   '
    ' return el("span", { className: up ? "up" : "down", text: text });\n  }\n  function sh(v) { return isN'
    'um(v) ? NF1.format(v) + "\\u00a0%" : "—"; }\n  function lowerKey(s) { return String(s || "").toLowerCa'
    'se(); }\n  function costRows(m) { return (m && m.attribution && m.attribution.rows) || []; }\n  functi'
    'on rowName(r) {\n    if (r.kind === "job_runs") { return "Clústeres efímeros de jobs (" + r.count + p'
    'lural(r.count, " ejecución", " ejecuciones") + ")"; }\n    if (r.kind === "pipeline_runs") { return "'
    'Clústeres de pipelines (DLT)"; }\n    return r.name;\n  }\n  function tagChips(tags) {\n    var keys = O'
    'bject.keys(tags || {});\n    if (!keys.length) { return el("span", { className: "muted", text: "Sin e'
    'tiquetas" }); }\n    var wrap = el("div", { className: "chips" });\n    keys.forEach(function (k) { wr'
    'ap.appendChild(el("span", null, [k + ": ", el("b", { text: String(tags[k]) })])); });\n    return wra'
    'p;\n  }\n  function evText(v) {\n    if (Array.isArray(v)) { return v.join(", "); }\n    if (v === true)'
    ' { return "Sí"; }\n    if (v === false) { return "No"; }\n    return isNum(v) ? NF.format(v) : String('
    'v);\n  }\n  function sigChips(ev) {\n    var wrap = el("div", { className: "chips" }), n = 0;\n    Objec'
    't.keys(ev || {}).forEach(function (k) {\n      var v = ev[k];\n      if (v === null || v === undefined'
    ' || v === "" || (Array.isArray(v) && !v.length) || n >= 4) { return; }\n      var shown = /cost|floor'
    '/.test(k) && isNum(v) ? money(v) : evText(v);\n      wrap.appendChild(el("span", null, [(C.ev[k] || k'
    ') + ": ", el("b", { text: shown })]));\n      n++;\n    });\n    return n ? wrap : null;\n  }\n  function'
    ' savingCell(s) {\n    if (!isNum(s.estimated_monthly_saving)) { return { v: el("span", { className: "'
    'muted", text: s.monthly_cost === null ? "—" : "No estimable" }), s: -1 }; }\n    var box = el("div", '
    '{ className: "sav" + (s.counted ? "" : " nc") }, [(C.saving[s.saving_kind] || "≈") + " " + money(s.e'
    'stimated_monthly_saving)]);\n    box.appendChild(el("small", { text: s.counted ? C.basis[s.saving_bas'
    'is] || "" : "No suma: mismo objeto que un ahorro mayor" }));\n    return { v: box, s: s.counted ? s.e'
    'stimated_monthly_saving : s.estimated_monthly_saving / 1000 };\n  }\n  var COST_TAB = "cluster";\n  fun'
    'ction costTabs(m) {\n    var tabs = [];\n    ((m.attribution && m.attribution.dimensions) || []).forEa'
    'ch(function (d) { tabs.push({ id: d.key, label: C.dim[d.key] || d.key }); });\n    if (m.attribution '
    '&& (m.attribution.creators || []).length) { tabs.push({ id: "creators", label: C.dim.creators }); }\n'
    '    ((m.attribution && m.attribution.custom_tags) || []).forEach(function (t) { tabs.push({ id: "tag'
    ':" + t.tag, label: "Etiqueta " + t.tag }); });\n    return tabs;\n  }\n  function drawCostTabs(m) {\n   '
    ' var holder = document.getElementById("cost-tabs");\n    clear(holder);\n    var tabs = costTabs(m);\n '
    '   if (!tabs.some(function (t) { return t.id === COST_TAB; })) { COST_TAB = tabs.length ? tabs[0].id'
    ' : "cluster"; }\n    tabs.forEach(function (t, i) {\n      var b = el("button", { type: "button", role'
    ': "tab", id: "cost-tab-" + i, "aria-selected": t.id === COST_TAB ? "true" : "false", "aria-controls"'
    ': "cost-attr-panel", tabindex: t.id === COST_TAB ? "0" : "-1", text: t.label });\n      b.addEventLis'
    'tener("click", function () { COST_TAB = t.id; drawCostTabs(m); renderAttribution(m); });\n      b.add'
    'EventListener("keydown", function (ev) {\n        if (ev.key !== "ArrowRight" && ev.key !== "ArrowLef'
    't") { return; }\n        var next = tabs[(i + (ev.key === "ArrowRight" ? 1 : tabs.length - 1)) % tabs'
    '.length];\n        COST_TAB = next.id;\n        drawCostTabs(m);\n        renderAttribution(m);\n       '
    ' var focusBtn = document.querySelector(\'#cost-tabs [aria-selected="true"]\');\n        if (focusBtn) {'
    ' focusBtn.focus(); }\n        ev.preventDefault();\n      });\n      if (t.id === COST_TAB) { document.'
    'getElementById("cost-attr-panel").setAttribute("aria-labelledby", "cost-tab-" + i); }\n      holder.a'
    'ppendChild(b);\n    });\n  }\n  function attributionView(m) {\n    var head = m.headline || {}, q = (doc'
    'ument.getElementById("cost-attr-search").value || "").toLowerCase().trim();\n    var prev = monthName'
    '(head.previous_month, true), view = { headers: [], rows: [], note: "" };\n    function keep(text) { r'
    'eturn !q || String(text).toLowerCase().indexOf(q) >= 0; }\n    var deltaHead = { t: "Frente a " + pre'
    'v, c: "n" };\n    if (COST_TAB === "creators") {\n      view.headers = ["Creador", { t: "Coste del mes'
    '", c: "n" }, { t: "% del mes", c: "n" }];\n      view.rows = (m.attribution.creators || []).filter(fu'
    'nction (r) { return keep(r.creator); }).map(function (r) {\n        return [{ v: brk(r.creator === "—'
    '" ? "Sin creador conocido" : r.creator, ""), s: r.creator }, { v: money(r.total), s: r.total, c: "n"'
    ' }, { v: sh(r.share), s: r.share, c: "n" }];\n      });\n      view.note = "Según quién creó cada clús'
    'ter, job y SQL warehouse del inventario actual; lo eliminado no tiene creador.";\n      return view;\n'
    '    }\n    if (COST_TAB.indexOf("tag:") === 0) {\n      var t = (m.attribution.custom_tags || []).filt'
    'er(function (x) { return "tag:" + x.tag === COST_TAB; })[0] || { values: [] };\n      view.headers = '
    '["Valor de " + t.tag, { t: "DBU", c: "n" }, { t: "Infraestructura", c: "n" }, { t: "Total", c: "n" }'
    ', { t: "% del mes", c: "n" }, deltaHead];\n      view.rows = (t.values || []).filter(function (r) { r'
    'eturn keep(r.value); }).map(function (r) {\n        return [{ v: el("b", { text: r.value }), s: r.val'
    'ue }, { v: money(r.dbu), s: r.dbu, c: "n" }, { v: money(r.infra), s: r.infra, c: "n" }, { v: money(r'
    '.total), s: r.total, c: "n" },\n          { v: sh(r.share), s: r.share, c: "n" }, { v: deltaNode(r.pr'
    'evious_total ? 100 * (r.total - r.previous_total) / r.previous_total : null, r.total - r.previous_to'
    'tal), s: r.total - r.previous_total, c: "n" }];\n      });\n      if (isNum(t.untagged_total) && keep('
    '"sin etiqueta")) {\n        var why = (t.untagged_categories || []).slice(0, 3).map(function (c) { re'
    'turn lab(C.category, lowerKey(c.category)) + " " + money(c.review); }).join(" · ");\n        view.row'
    's.push([{ v: stack("Sin etiqueta " + t.tag, why || null), s: "~" }, { v: "—", c: "n", s: -1 }, { v: '
    '"—", c: "n", s: -1 }, { v: money(t.untagged_total), s: t.untagged_total, c: "n" },\n          { v: sh'
    '(isNum(head.review_total) && head.review_total ? 100 * t.untagged_total / head.review_total : null),'
    ' s: t.untagged_total, c: "n" }, { v: "—", c: "n", s: 0 }]);\n      }\n      view.note = isNum(t.tagged'
    '_share) ? "La etiqueta " + t.tag + " está en el " + sh(t.tagged_share) + " del coste del mes; sin el'
    'la quedan " + money(t.untagged_total) + "." : "Consulta de la etiqueta " + t.tag + ": " + lab(C.stat'
    'us, t.status) + ".";\n      return view;\n    }\n    var d = ((m.attribution && m.attribution.dimension'
    's) || []).filter(function (x) { return x.key === COST_TAB; })[0] || {};\n    view.headers = ["Nombre"'
    ', { t: "DBU", c: "n" }, { t: "Infraestructura", c: "n" }, { t: "Total", c: "n" }, { t: "% del mes", '
    'c: "n" }, deltaHead, "Etiquetas de imputación"];\n    view.rows = costRows(m).filter(function (r) { r'
    'eturn r.dimension === COST_TAB && keep(rowName(r) + " " + JSON.stringify(r.tags) + " " + (r.creator '
    '|| "")); }).map(function (r) {\n      var grouped = r.kind === "job_runs" || r.kind === "pipeline_run'
    's";\n      var sub = grouped ? (r.kind === "job_runs" ? "Detalle por job en la pestaña Jobs" : "Etiqu'
    'etas en la definición de cada pipeline") : lab(C.kind, r.kind) + (r.creator ? " · " + r.creator : ""'
    ');\n      return [{ v: stack(brk(rowName(r), ""), sub), s: rowName(r) }, { v: money(r.dbu), s: r.dbu,'
    ' c: "n" }, { v: money(r.infra), s: r.infra, c: "n" }, { v: el("b", { text: money(r.total) }), s: r.t'
    'otal, c: "n" },\n        { v: sh(r.share), s: r.share, c: "n" }, { v: deltaNode(r.change_pct, r.chang'
    'e), s: r.change, c: "n" }, { v: grouped ? el("span", { className: "muted", text: "—" }) : tagChips(r'
    '.tags) }];\n    });\n    if (isNum(d.untagged_total) && keep("sin etiqueta")) {\n      view.rows.push(['
    '{ v: stack("Sin etiqueta " + d.tag, "Coste que esta etiqueta no explica"), s: "~" }, { v: "—", c: "n'
    '", s: -1 }, { v: "—", c: "n", s: -1 }, { v: money(d.untagged_total), s: d.untagged_total, c: "n" },\n'
    '        { v: sh(isNum(d.tagged_share) ? 100 - d.tagged_share : null), s: d.untagged_total, c: "n" },'
    ' { v: "—", c: "n", s: 0 }, { v: "—" }]);\n    }\n    var why = { cluster: "Los jobs aparecen agrupados'
    '; su detalle está en la pestaña Jobs.", job: "Solo el cómputo de jobs lleva JobId: un job que corre '
    'en un clúster interactivo cuenta en ese clúster.",\n      warehouse: "Cada SQL warehouse con su DBU y'
    ', si no es serverless, sus VM.", pool: "Las VM de un pool solo llevan las etiquetas del pool, nunca '
    'las del clúster que las usa." }[COST_TAB] || "";\n    view.note = isNum(d.tagged_share) ? "La etiquet'
    'a " + d.tag + " explica el " + sh(d.tagged_share) + " del coste del mes. " + why : "Consulta " + (d.'
    'tag || "") + ": " + lab(C.status, d.status) + ".";\n    return view;\n  }\n  function renderAttribution'
    '(m) {\n    var view = attributionView(m);\n    document.getElementById("cost-attr-note").textContent ='
    ' view.note;\n    renderTable(document.getElementById("cost-attr-table"), view.headers, view.rows, { s'
    'ortable: true, page: 12, empty: "Sin coste en esta vista." });\n  }\n  function filteredSignals(m) {\n '
    '   var sev = document.getElementById("cost-sig-sev").value, sav = document.getElementById("cost-sig-'
    'saving").value;\n    var q = (document.getElementById("cost-sig-search").value || "").toLowerCase().t'
    'rim();\n    return (m.signals || []).filter(function (s) {\n      if (sev !== "all" && s.severity !== '
    'sev) { return false; }\n      if (sav === "with" && !isNum(s.estimated_monthly_saving)) { return fals'
    'e; }\n      return !q || JSON.stringify(s).toLowerCase().indexOf(q) >= 0;\n    });\n  }\n  function rend'
    'erSignals(m) {\n    var all = m.signals || [], list = filteredSignals(m), head = m.headline || {};\n  '
    '  var counted = all.filter(function (s) { return s.counted; });\n    document.getElementById("cost-si'
    'gnals-count").textContent = "Mostrando " + list.length + " de " + all.length + plural(all.length, " '
    'señal", " señales") +\n      (counted.length ? " · " + counted.length + " con ahorro estimado que sum'
    'an " + money(head.estimated_monthly_savings) + " al mes (por objeto solo cuenta el mayor)." : ".");\n'
    '    renderTable(document.getElementById("cost-signals-table"),\n      [{ t: "Severidad" }, { t: "Seña'
    'l y evidencia", c: "w" }, { t: "Objeto" }, { t: "Coste del mes", c: "n" }, { t: "Ahorro estimado / m'
    'es", c: "n" }, { t: "Qué hacer", c: "w" }],\n      list.map(function (s) {\n        var d = el("div", '
    '{ className: "fd" }, [el("b", { text: s.title })]);\n        var chips = sigChips(s.evidence);\n      '
    '  if (chips) { d.appendChild(chips); }\n        var rec = el("div", { className: "fr" }, [el("p", { t'
    'ext: s.recommendation })]);\n        var link = safeLearnUrl(s.learn_url);\n        if (link) { rec.ap'
    'pendChild(extLink(link, "Microsoft Learn")); }\n        return [\n          { v: sevPill(s.severity), '
    's: ["high", "medium", "low"].indexOf(s.severity) },\n          { v: d, s: s.title },\n          { v: s'
    'tack(brk(s.object_name, ""), lab(C.objKind, s.object_kind)), s: s.object_name },\n          { v: mone'
    'y(s.monthly_cost), s: isNum(s.monthly_cost) ? s.monthly_cost : -1, c: "n" },\n          savingCell(s)'
    ',\n          { v: rec, s: s.recommendation }\n        ];\n      }), { sortable: true, page: 12, empty: '
    '"Ninguna señal coincide con el filtro." }\n    );\n  }\n  function costBars(holder, items, total, color'
    ', cur) {\n    clear(holder);\n    var max = Math.max.apply(null, [1].concat(items.map(function (i) { r'
    'eturn i.value; })));\n    items.forEach(function (i) { holder.appendChild(barRow(i.label, i.sub, 100 '
    '* i.value / max, money(i.value, cur), i.valueSub, color, false)); });\n    if (!items.length) { holde'
    'r.appendChild(emptyState("Sin coste en el mes revisado.")); }\n  }\n  function renderCostStats(m) {\n  '
    '  var head = m.headline || {}, stats = document.getElementById("cost-stats");\n    clear(stats);\n    '
    'function stat(k, n, unit, d) {\n      var nv = el("div", { className: "n" }, [String(n)]);\n      if ('
    'unit) { nv.appendChild(el("small", { text: unit })); }\n      stats.appendChild(el("div", { className'
    ': "cstat" }, [el("div", { className: "k", text: k }), nv, d ? (d instanceof Node ? el("div", { class'
    'Name: "d" }, [d]) : el("div", { className: "d", text: d })) : null]));\n    }\n    var delta = el("spa'
    'n", null, [deltaNode(head.change_pct, head.change), " frente a " + monthName(head.previous_month) + '
    '" (" + money(head.previous_total) + ")"]);\n    stat("Coste de " + monthName(head.review_month), mone'
    'y(head.review_total, ""), costCurrency, delta);\n    stat("DBU · infraestructura", isNum(head.dbu_sha'
    're) ? NF0.format(head.dbu_share) + " · " + NF0.format(100 - head.dbu_share) : "—", "%", money(head.d'
    'bu_total) + " DBU · " + money(head.infra_total) + " infraestructura");\n    stat("Sin etiqueta de cóm'
    'puto", isNum(head.unattributed_share) ? NF1.format(head.unattributed_share) : "—", isNum(head.unattr'
    'ibuted_share) ? "%" : "",\n      isNum(head.unattributed_total) ? money(head.unattributed_total) + " '
    'en servicios compartidos y serverless" : "No evaluado");\n    stat("Ahorro estimado al mes", isNum(he'
    'ad.estimated_monthly_savings) ? "≈ " + money(head.estimated_monthly_savings, "") : "—", isNum(head.e'
    'stimated_monthly_savings) ? costCurrency : "",\n      isNum(head.estimated_monthly_savings) ? head.sa'
    'vings_signals + " de " + head.signals + " señales, sin contar dos veces" : "Sin datos de coste para '
    'estimarlo");\n    var trend = document.getElementById("cost-trend");\n    clear(trend);\n    trend.appe'
    'ndChild(el("h4", { text: "Evolución mensual" }));\n    var maxTotal = Math.max.apply(null, [1].concat'
    '((m.monthly || []).map(function (r) { return r.total; })));\n    (m.monthly || []).forEach(function ('
    'r) {\n      var row = el("div", { className: "mrow" + (r.partial ? " partial" : "") });\n      row.app'
    'endChild(el("div", { className: "ml" }, [monthName(r.month, true), r.partial ? el("small", { text: "'
    'hasta el día " + (head.mtd_days || "—") }) : r.month === head.review_month ? el("small", { text: "me'
    's revisado" }) : null]));\n      var track = el("div", { className: "strack", role: "img", "aria-labe'
    'l": monthName(r.month) + ": " + money(r.dbu) + " DBU y " + money(r.infra) + " de infraestructura" })'
    ';\n      [["seg-dbu", r.dbu], ["seg-infra", r.infra]].forEach(function (p) { var seg = el("i", { clas'
    'sName: p[0] }); seg.style.width = (100 * p[1] / maxTotal) + "%"; track.appendChild(seg); });\n      r'
    'ow.appendChild(track);\n      row.appendChild(el("div", { className: "mv", text: money(r.total) }));\n'
    '      trend.appendChild(row);\n    });\n    trend.appendChild(el("div", { className: "keys" }, [el("sp'
    'an", null, [el("i", { className: "seg-dbu" }), "DBU"]), el("span", null, [el("i", { className: "seg-'
    'infra" }), "Infraestructura"])]));\n  }\n  function renderCostSplit(m) {\n    var split = m.split || {}'
    ', head = m.headline || {};\n    costBars(document.getElementById("cost-dbu-bars"), (split.dbu_familie'
    's || []).map(function (f) {\n      return { label: lab(C.family, f.key), sub: (f.meters || []).slice('
    '0, 2).map(function (x) { return x.meter; }).join(" · "), value: f.review,\n        valueSub: sh(f.sha'
    're) + (isNum(f.previous) && f.previous ? " · " + signedPct(100 * (f.review - f.previous) / f.previou'
    's) : "") };\n    }), head.dbu_total, "var(--chart)");\n    var ap = (split.dbu_families || []).filter('
    'function (f) { return f.key === "all_purpose"; })[0];\n    document.getElementById("cost-dbu-sub").te'
    'xtContent = ap && isNum(ap.share) && ap.share >= 25\n      ? "El cómputo interactivo es el " + sh(ap.'
    'share) + " de la DBU, y su DBU cuesta casi el doble que la de jobs."\n      : "Lo que Databricks fact'
    'ura por unidad de procesamiento, según el tipo de carga.";\n    costBars(document.getElementById("cos'
    't-infra-bars"), (split.infra_categories || []).map(function (c) {\n      return { label: lab(C.catego'
    'ry, lowerKey(c.category)), sub: null, value: c.review, valueSub: sh(c.share) };\n    }), head.infra_t'
    'otal, "var(--chart-2)");\n    var sizes = document.getElementById("cost-vm-sizes");\n    clear(sizes);'
    '\n    if ((split.vm_sizes || []).length) {\n      sizes.appendChild(document.createTextNode("Tamaños d'
    'e VM con más coste"));\n      var chips = el("div", { className: "chips" });\n      split.vm_sizes.sli'
    'ce(0, 6).forEach(function (v) { chips.appendChild(el("span", null, [v.meter + " · ", el("b", { text:'
    ' money(v.review) })])); });\n      sizes.appendChild(chips);\n    }\n  }\n  function renderGapAndTags(m)'
    ' {\n    var gapBox = document.getElementById("cost-gap"), gap = m.attribution && m.attribution.gap;\n '
    '   clear(gapBox);\n    if (!gap) { gapBox.appendChild(el("p", { className: "muted", text: "No evaluad'
    'o: la consulta por la etiqueta Vendor no está disponible." })); }\n    else {\n      gapBox.appendChil'
    'd(el("div", { className: "gapn" }, [el("b", { text: NF1.format(gap.share || 0) + "\\u00a0%" }), el("s'
    'pan", { text: money(gap.total) + " del mes" })]));\n      var bars = el("div", { className: "bars" })'
    ';\n      gapBox.appendChild(bars);\n      costBars(bars, (gap.categories || []).map(function (c) {\n   '
    '     var key = lowerKey(c.category);\n        return { label: key === "azure databricks" ? "DBU serve'
    'rless" : lab(C.category, key), sub: C.gapWhy[key] || null, value: c.review, valueSub: sh(c.share) };'
    '\n      }), gap.total, "var(--info-bar)");\n    }\n    var tags = (m.attribution && m.attribution.custo'
    'm_tags) || [], holder = document.getElementById("cost-tag-bars");\n    clear(holder);\n    tags.forEac'
    'h(function (t) {\n      holder.appendChild(barRow(el("span", { className: "mono", text: t.tag }), isN'
    'um(t.untagged_total) ? "Sin ella: " + money(t.untagged_total) : lab(C.status, t.status),\n        isN'
    'um(t.tagged_share) ? t.tagged_share : 0, isNum(t.tagged_share) ? sh(t.tagged_share) : "—", null, "va'
    'r(--chart)", !isNum(t.tagged_share)));\n    });\n    if (!tags.length) { holder.appendChild(el("p", { '
    'className: "muted", text: "Sin etiquetas de imputación configuradas (COST_ALLOCATION_TAGS)." })); }\n'
    '    var notes = document.getElementById("cost-tag-notes");\n    clear(notes);\n    (m.signals || []).f'
    'ilter(function (s) { return s.code === "MISSING_ALLOCATION_TAGS" || s.code === "POLICY_TAGS"; }).sli'
    'ce(0, 5).forEach(function (s) {\n      notes.appendChild(el("li", { text: s.title + ": " + ((s.eviden'
    'ce && s.evidence.objects) || []).slice(0, 4).join("; ") }));\n    });\n  }\n  function renderMovers(m) '
    '{\n    var holder = document.getElementById("cost-movers"), mv = m.movers || {}, head = m.headline ||'
    ' {};\n    clear(holder);\n    document.getElementById("cost-movers-sub").textContent = "Clústeres, job'
    's, SQL warehouses y pools con mayor variación de " + monthName(head.previous_month) + " a " + monthN'
    'ame(head.review_month) + ".";\n    [["Suben", mv.up || []], ["Bajan", mv.down || []]].forEach(functio'
    'n (g) {\n      var col = el("div", null, [el("h4", { text: g[0] })]);\n      if (!g[1].length) { col.a'
    'ppendChild(el("p", { className: "muted", text: "Sin variaciones relevantes." })); }\n      g[1].forEa'
    'ch(function (r) {\n        col.appendChild(el("div", { className: "mover" }, [\n          el("b", { te'
    'xt: rowName(r) }),\n          el("span", { className: "dv " + (r.change > 0 ? "up" : "down"), text: ('
    'r.change > 0 ? "+" : "−") + money(Math.abs(r.change)) }),\n          el("small", { text: lab(C.kind, '
    'r.kind) + " · " + money(r.total) + " en " + monthName(head.review_month, true) }),\n          el("sma'
    'll", { className: "dv", text: r.previous_total ? signedPct(r.change_pct) : "nuevo" })\n        ]));\n '
    '     });\n      holder.appendChild(col);\n    });\n  }\n  function renderSystemTables(m) {\n    var box ='
    ' document.getElementById("cost-system"), st = m.system_tables || { status: "not_configured" };\n    c'
    'lear(box);\n    var on = st.status === "complete";\n    box.appendChild(el("div", { className: "h3row"'
    ' }, [el("h3", { text: "Detalle por ejecución y usuario (tablas de sistema)" }),\n      pill(on ? "ton'
    'e-warn" : st.status === "not_configured" ? "tone-info" : "tone-crit", on ? "Activado · consume DBU" '
    ': st.status === "not_configured" ? "Desactivado" : lab(C.status, st.status))]));\n    if (!on) {\n    '
    '  box.appendChild(el("p", { className: "sub", text: st.status === "not_configured"\n        ? "Opcion'
    'al y desactivado por defecto porque consume DBU (y arranca el SQL warehouse si está parado). Con sys'
    'tem_tables_warehouse_id (un SQL warehouse existente) la tool lanza una única consulta de solo lectur'
    'a a system.billing.usage y system.billing.list_prices y muestra aquí el coste por ejecución de job y'
    ' por usuario."\n        : "La consulta a las tablas de sistema no terminó: revise en la sección 8 la '
    'fuente dbx_system_billing." }));\n      return;\n    }\n    var cur = st.currency || "USD";\n    var ws '
    '= String(st.window && st.window.start || ""), we = String(st.window && st.window.end || "");\n    var'
    ' wy = +ws.slice(0, 4), wm = +ws.slice(5, 7), nextMonth = wm === 12 ? (wy + 1) + "-01" : wy + "-" + S'
    'tring(wm + 1).padStart(2, "0");\n    var wholeMonth = /^\\d{4}-\\d{2}-01/.test(ws) && we.slice(0, 10) ='
    '== nextMonth + "-01";\n    box.appendChild(el("p", { className: "sub", text: "Coste a precio de lista'
    ' (" + cur + ", sin descuentos) " + (wholeMonth ? "de " + monthName(ws.slice(0, 7)) : "de " + day(ws)'
    ' + " a " + day(we)) + ", según system.billing.usage." }));\n    box.appendChild(el("h4", { className:'
    ' "sys-h", text: "Ejecuciones y cargas con más coste" }));\n    var wrap = el("div", { className: "wra'
    'p sys-wrap" }), table = el("table", { className: "dense", id: "cost-system-table" });\n    wrap.appen'
    'dChild(table);\n    box.appendChild(wrap);\n    var grid = el("div", { className: "sys-grid" }), left '
    '= el("div"), right = el("div");\n    left.appendChild(el("h4", { text: "Por usuario o service princip'
    'al" }));\n    var ub = el("div", { className: "bars" });\n    left.appendChild(ub);\n    right.appendCh'
    'ild(el("h4", { text: "Por producto" }));\n    var pb = el("div", { className: "bars" });\n    right.ap'
    'pendChild(pb);\n    grid.appendChild(left);\n    grid.appendChild(right);\n    box.appendChild(grid);\n '
    '   function sku(s) { return s ? String(s).replace(/_/g, " ").toLowerCase() : null; }\n    function pr'
    'oduct(p) {\n      var known = { ALL_PURPOSE: "All-purpose (interactivo)", JOBS: "Jobs", SQL: "SQL war'
    'ehouses", DLT: "Pipelines (DLT)", INTERACTIVE: "Notebooks serverless",\n        MODEL_SERVING: "Model'
    ' serving", VECTOR_SEARCH: "Vector Search", LAKEHOUSE_MONITORING: "Lakehouse Monitoring", PREDICTIVE_'
    'OPTIMIZATION: "Predictive optimization" };\n      return p ? known[String(p).toUpperCase()] || String'
    '(p).charAt(0) + String(p).slice(1).replace(/_/g, " ").toLowerCase() : "—";\n    }\n    renderTable(tab'
    'le, ["Producto", "Job · ejecución / recurso", "Ejecutado por", { t: "DBU", c: "n" }, { t: "Coste de '
    'lista", c: "n" }],\n      (st.runs || []).map(function (r) {\n        var what = r.job_id ? "Job " + r'
    '.job_id + (r.job_run_id ? " · ejecución " + r.job_run_id : "") : r.warehouse_id ? "Warehouse " + r.w'
    'arehouse_id : r.cluster_id ? "Clúster " + r.cluster_id : r.pipeline_id ? "Pipeline " + r.pipeline_id'
    ' : "—";\n        return [{ v: stack(product(r.product), sku(r.sku)), s: r.product }, { v: brk(what, "'
    '") }, { v: brk(r.run_as || "—", "") }, { v: NF0.format(r.dbus || 0), s: r.dbus, c: "n" }, { v: money'
    '(r.list_cost, cur), s: r.list_cost, c: "n" }];\n      }), { sortable: true, page: 8 });\n    costBars('
    'ub, (st.users || []).slice(0, 8).map(function (u) { return { label: brk(u.run_as || "—", ""), value:'
    ' u.list_cost || 0 }; }), null, "var(--chart)", cur);\n    costBars(pb, (st.products || []).slice(0, 8'
    ').map(function (p) { return { label: product(p.product), sub: sku(p.sku), value: p.list_cost || 0 };'
    ' }), null, "var(--chart-2)", cur);\n  }\n  function renderCostMethod(m) {\n    var dl = document.getEle'
    'mentById("cost-method"), a = m.assumptions || {}, scope = m.scope || {}, p = m.periods || {};\n    cl'
    'ear(dl);\n    function row(term, node) { dl.appendChild(el("dt", { text: term })); var dd = el("dd");'
    ' dd.appendChild(node instanceof Node ? node : document.createTextNode(node)); dl.appendChild(dd); }\n'
    '    row("Alcance", "Recurso del área de trabajo (DBU)" + (scope.managed_resource_group ? " y su grup'
    'o de recursos administrado " + scope.managed_resource_group + " (VM, discos y red)" : "") +\n      (('
    'scope.resource_ids || []).length > 1 ? ", más " + (scope.resource_ids.length - 1) + " recursos aprob'
    'ados" : "") + "; coste " + (m.metric === "ActualCost" ? "real (vista de factura)" : "amortizado") + '
    '" en " + (m.currency || "la moneda de facturación") + ".");\n    row("Meses", "Mes revisado " + month'
    'Name(p.review) + " (cerrado), comparado con " + monthName(p.previous) + "; " + monthName(p.current) '
    '+ " hasta el día " + (p.mtd_days || "—") + ". El coste de los dos últimos días puede cambiar.");\n   '
    ' row("Reparto", "Cost Management agrupado por las etiquetas que Databricks pone al cómputo (ClusterN'
    'ame, JobId, SqlEndpointId, DatabricksInstancePoolId, Vendor) y por " +\n      ((a.allocation_tags || '
    '[]).length ? (a.allocation_tags || []).join(", ") : "ninguna etiqueta propia") + ", cada una con su '
    'servicio (DBU frente a infraestructura).");\n    var rules = el("ul");\n    [\n      "Autoterminación d'
    'esactivada: lo que costó el clúster en sábados y domingos (al menos, si nadie lo usa el fin de seman'
    'a).",\n      "Jobs en un clúster interactivo: DBU del clúster × (1 − " + NF.format(a.jobs_to_all_purp'
    'ose_dbu_ratio) + ") (hasta, si todo su uso son esos jobs).",\n      "Workers sin spot: coste de VM × '
    'workers / (workers + 1) × " + NF0.format(100 * (a.spot_discount || 0)) + " % de descuento prudente."'
    ',\n      "Pool con instancias inactivas mínimas: coste mínimo diario del pool × días del mes.",\n     '
    ' "SQL warehouse sin auto-stop: coste × " + NF1.format(100 * (a.weekend_share || 0)) + " % (fines de '
    'semana del mes).",\n      "Por objeto solo suma el mayor ahorro; los demás figuran como «no suma». La'
    's demás señales no tienen un dato de coste que permita estimar sin inventar."\n    ].forEach(function'
    ' (t) { rules.appendChild(el("li", { text: t })); });\n    row("Ahorro estimado", rules);\n    var chip'
    's = el("div", { className: "chips" });\n    Object.keys(m.query_status || {}).forEach(function (k) { '
    'chips.appendChild(el("span", null, [k + ": ", el("b", { text: lab(C.status, m.query_status[k]) })]))'
    '; });\n    row("Consultas", chips.firstChild ? chips : "Sin consultas de coste (" + lab(C.status, m.s'
    'tatus) + ").");\n    var sys = m.system_tables || {};\n    var gaps = (sys.status === "complete" ? "" '
    ': "Uso por ejecución y por usuario (tablas de sistema, desactivadas por defecto); ") +\n      "almace'
    'namiento y red fuera del grupo administrado salvo los recursos de approved_cost_resource_ids" +\n    '
    '  (sys.status === "complete" ? "; el detalle de las tablas de sistema va a precio de lista, sin vues'
    'tros descuentos." : ".");\n    row("No cubre", gaps.charAt(0).toUpperCase() + gaps.slice(1));\n  }\n  f'
    'unction renderCosts(snap) {\n    var m = snap.databricks_costs, emptyBox = document.getElementById("c'
    'ost-empty");\n    var body = document.getElementById("cost-body"), data = document.getElementById("co'
    'st-data");\n    clear(emptyBox);\n    if (!m) {\n      body.hidden = true;\n      emptyBox.hidden = fals'
    'e;\n      emptyBox.appendChild(el("div", { className: "note", role: "note" }, [icon("info"), el("span'
    '", { text: "Esta instantánea no incluye el análisis de costes de Databricks." })]));\n      return;\n '
    '   }\n    body.hidden = false;\n    costCurrency = m.currency || "";\n    var head = m.headline || {}, '
    'hasData = isNum(head.review_total);\n    data.hidden = !hasData;\n    if (!hasData) {\n      emptyBox.h'
    'idden = false;\n      var why = { not_configured: "El análisis de costes está desactivado en la confi'
    'guración (cost_analysis_enabled = False).",\n        denied: "La identidad no puede leer costes: conc'
    'eda Cost Management Reader (o Reader) en la suscripción y repita la revisión.",\n        not_collecte'
    'd: "Esta ejecución no recogió costes de Cost Management." }[m.status] || "Cost Management no devolvi'
    'ó datos utilizables (" + lab(C.status, m.status) + "); vea la fuente azure_cost_databricks en la sec'
    'ción 8.";\n      emptyBox.appendChild(el("div", { className: "note", role: "note" }, [icon("info"), e'
    'l("span", { text: why + " Las señales de configuración siguen abajo, sin ahorro estimado." })]));\n  '
    '  } else {\n      emptyBox.hidden = true;\n      renderCostStats(m);\n      renderCostSplit(m);\n      d'
    'rawCostTabs(m);\n      renderAttribution(m);\n      renderGapAndTags(m);\n      renderMovers(m);\n    }\n'
    '    renderSignals(m);\n    renderSystemTables(m);\n    renderCostMethod(m);\n  }\n  ["cost-sig-sev", "co'
    'st-sig-saving", "cost-sig-search"].forEach(function (id) {\n    var node = document.getElementById(id'
    ');\n    ["input", "change"].forEach(function (evName) { node.addEventListener(evName, function () { i'
    'f (currentSnap && currentSnap.databricks_costs) { renderSignals(currentSnap.databricks_costs); } });'
    ' });\n  });\n  document.getElementById("cost-attr-search").addEventListener("input", function () { if '
    '(currentSnap && currentSnap.databricks_costs) { renderAttribution(currentSnap.databricks_costs); } }'
    ');\n  function csvLines(cols, rows) { return "\\uFEFF" + [cols.join(",")].concat(rows.map(function (r)'
    ' { return cols.map(function (c) { return csvEscape(r[c]); }).join(","); })).join("\\r\\n"); }\n  functi'
    'on costCsv() {\n    var m = currentSnap && currentSnap.databricks_costs;\n    if (!m) { return csvLine'
    's(["dimension"], []); }\n    var rows = costRows(m).map(function (r) { return { dimension: r.dimensio'
    'n, name: rowName(r), kind: r.kind, creator: r.creator, dbu: r.dbu, infra: r.infra, total: r.total, p'
    'revious_total: r.previous_total, share: r.share, tags: r.tags, currency: m.currency, month: m.period'
    's && m.periods.review }; });\n    ((m.attribution && m.attribution.custom_tags) || []).forEach(functi'
    'on (t) {\n      (t.values || []).forEach(function (v) { rows.push({ dimension: "tag:" + t.tag, name: '
    'v.value, kind: "tag_value", dbu: v.dbu, infra: v.infra, total: v.total, previous_total: v.previous_t'
    'otal, share: v.share, currency: m.currency, month: m.periods && m.periods.review }); });\n      if (i'
    'sNum(t.untagged_total)) { rows.push({ dimension: "tag:" + t.tag, name: "(sin etiqueta)", kind: "unta'
    'gged", total: t.untagged_total, currency: m.currency, month: m.periods && m.periods.review }); }\n   '
    ' });\n    return csvLines(["month", "dimension", "name", "kind", "creator", "dbu", "infra", "total", '
    '"previous_total", "share", "tags", "currency"], rows);\n  }\n  function signalsCsv(list) {\n    var cur'
    ' = currentSnap && currentSnap.databricks_costs ? currentSnap.databricks_costs.currency : "";\n    ret'
    'urn csvLines(["id", "code", "severity", "title", "object_kind", "object_name", "monthly_cost", "esti'
    'mated_monthly_saving", "saving_kind", "saving_basis", "counted", "currency", "recommendation", "lear'
    'n_url", "evidence"],\n      list.map(function (s) { return Object.assign({ currency: cur }, s); }));\n'
    '  }\n  document.getElementById("cost-attr-export").addEventListener("click", function () { downloadBl'
    'ob("databricks-costes-por-carga.csv", costCsv(), "text/csv;charset=utf-8"); });\n  document.getElemen'
    'tById("export-costs-csv-btn").addEventListener("click", function () { downloadBlob("databricks-coste'
    's-por-carga.csv", costCsv(), "text/csv;charset=utf-8"); });\n  document.getElementById("cost-sig-expo'
    'rt").addEventListener("click", function () { if (currentSnap && currentSnap.databricks_costs) { down'
    'loadBlob("databricks-senales-filtradas.csv", signalsCsv(filteredSignals(currentSnap.databricks_costs'
    ')), "text/csv;charset=utf-8"); } });\n  document.getElementById("export-signals-csv-btn").addEventLis'
    'tener("click", function () { if (currentSnap && currentSnap.databricks_costs) { downloadBlob("databr'
    'icks-senales-optimizacion.csv", signalsCsv(currentSnap.databricks_costs.signals || []), "text/csv;ch'
    'arset=utf-8"); } });\n\n  var PRESENTATION = (rootData && rootData.presentation) || {};\n  var FOCUS = '
    'PRESENTATION.focus === "costs" ? "costs" : "configuration";\n  function renumberSections() {\n    var '
    'short = { "sec-finops": "Costes de Databricks", "sec-identity": "Workspace e identidad", "sec-execut'
    'ive": "Resumen ejecutivo y WAF", "sec-dependencies": "Mapa de dependencias",\n      "sec-inventory": '
    '"Inventario Lakehouse y ARM", "sec-findings": "Hallazgos y reglas", "sec-actions": "Plan de acción",'
    ' "sec-sources": "Fuentes y metodología" };\n    var toc = document.getElementById("toc-menu");\n    cl'
    'ear(toc);\n    toc.appendChild(el("a", { href: "#sec-cover", text: "Portada y veredicto" }));\n    [].'
    'slice.call(document.querySelectorAll(".page > .chapter")).forEach(function (c, i) {\n      var h = c.'
    'querySelector(".sh h2");\n      if (h) { h.textContent = h.textContent.replace(/^\\d+\\.\\s*/, (i + 1) +'
    ' ". "); }\n      toc.appendChild(el("a", { href: "#" + c.id, text: (i + 1) + ". " + (short[c.id] || c'
    '.id) }));\n    });\n  }\n  function applyPresentation() {\n    var p = PRESENTATION, root = document.doc'
    'umentElement, css = "";\n    var theme = p.theme && typeof p.theme === "object" ? p.theme : {};\n    v'
    'ar rules = Object.keys(theme).filter(function (k) {\n      return /^--[a-z0-9-]{1,32}$/.test(k) && /^'
    '(#[0-9a-fA-F]{6}|rgba\\([0-9.,\\s]{7,40}\\))$/.test(String(theme[k]));\n    }).map(function (k) { return'
    ' k + ":" + theme[k]; });\n    if (rules.length) { css += ":root{" + rules.join(";") + "}"; root.class'
    'List.add("branded"); themeBtn.hidden = true; }\n    if (typeof p.display_font === "string" && /^data:'
    'font\\/woff2;base64,[A-Za-z0-9+\\/=]+$/.test(p.display_font)) {\n      css += "@font-face{font-family:\\'
    '"Brand Display\\";src:url(" + p.display_font + ") format(\\"woff2\\");font-weight:600;font-style:normal'
    ';font-display:swap}" +\n        ":root{--display:\\"Brand Display\\",Didot,\\"Bodoni 72\\",\\"Bodoni MT\\",'
    'Georgia,serif}";\n      root.classList.add("brand-font");\n    }\n    if (css) { var style = el("style"'
    ', { id: "brand-style" }); style.textContent = css; document.head.appendChild(style); }\n    var clien'
    't = rootData.client || {};\n    var barLogo = p.logo_placement === "bar" && client.logo_data_uri && /'
    '^data:image\\/(png|jpeg);base64,[A-Za-z0-9+/=]+$/.test(client.logo_data_uri);\n    if (barLogo) {\n    '
    '  root.classList.add("brand-bar");\n      var brand = document.querySelector(".bar .brand");\n      br'
    'and.insertBefore(el("img", { className: "client-logo", src: client.logo_data_uri, alt: client.logo_a'
    'lt || client.name || "" }), brand.firstChild);\n    }\n    document.getElementById("bar-product").text'
    'Content = (FOCUS === "costs" ? "Costes y configuración de Azure Databricks" : "Dependencias Azure Da'
    'tabricks") +\n      (barLogo && client.name ? " · " + client.name : "");\n    if (FOCUS === "costs") {'
    '\n      document.querySelector(".page").insertBefore(document.getElementById("sec-finops"), document.'
    'getElementById("sec-identity"));\n      var nav = document.getElementById("bar-nav");\n      nav.inser'
    'tBefore(nav.querySelector(\'a[href="#sec-finops"]\'), nav.firstChild);\n      renumberSections();\n    }'
    '\n  }\n  function renderCostHero(snap) {\n    var m = snap.databricks_costs || {}, h = m.headline || {}'
    ', ws = snap.workspace || {};\n    if (FOCUS !== "costs" || !isNum(h.review_total)) { return; }\n    co'
    'stCurrency = m.currency || "";\n    var month = monthName(h.review_month).split(" de ")[0], prev = mo'
    'nthName(h.previous_month).split(" de ")[0];\n    document.getElementById("cover-title").textContent ='
    ' "Costes de Azure Databricks: " + monthName(h.review_month);\n    var parts = ["Databricks costó ", ['
    'money(h.review_total)], " en " + month + ", ", [signedPct(h.change_pct)], " frente a " + prev + ": e'
    'l ", [NF0.format(h.dbu_share || 0) + "\\u00a0%"],\n      " son DBU y el ", [NF0.format(100 - (h.dbu_sh'
    'are || 0)) + "\\u00a0%"], " infraestructura."];\n    if (isNum(h.unattributed_share)) { parts = parts.'
    'concat([" El ", [sh(h.unattributed_share)], " no lo explica ninguna etiqueta de cómputo"]).concat(h.'
    'first_tag && isNum(h.first_tag.tagged_share) ? ["; vuestra etiqueta ", [h.first_tag.tag], " cubre el'
    ' ", [sh(h.first_tag.tagged_share)], "."] : ["."]); }\n    if (isNum(h.estimated_monthly_savings)) { p'
    'arts = parts.concat([" ", [String(h.savings_signals)], plural(h.savings_signals, " cambio ahorraría"'
    ', " cambios ahorrarían"), " unos ", [money(h.estimated_monthly_savings)], " al mes."]); }\n    rich(d'
    'ocument.getElementById("cover-lead"), parts);\n    var meta = document.getElementById("cover-badges")'
    ';\n    clear(meta);\n    function chip(p, on) { meta.appendChild(rich(el("span", { className: on ? "on'
    '" : null }), p)); }\n    chip(["Generado ", [utc(snap.reference_utc)]]);\n    chip(["Workspace ", [ws.'
    'name || "—"]]);\n    chip([m.metric === "ActualCost" ? "Coste real · " : "Coste amortizado · ", [m.cu'
    'rrency || "—"]]);\n    chip(["Entorno ", [snap.environment || "—"]]);\n    chip([snap.provenance === "'
    'SIMULATED" ? "DATOS SIMULADOS" : "DATOS " + (snap.provenance || "LIVE")], true);\n    var sev = h.sig'
    'nals_by_severity || {}, tone = "ok", title = "En línea";\n    if (sev.high) { tone = "act"; title = "'
    'Acción necesaria"; } else if (sev.medium) { tone = "warn"; title = "Revisión recomendada"; }\n    var'
    ' verdict = document.getElementById("verdict");\n    verdict.className = "signal " + tone;\n    clear(v'
    'erdict);\n    verdict.appendChild(el("div", { className: "k", text: "Veredicto" }));\n    verdict.appe'
    'ndChild(el("b", { text: title }));\n    verdict.appendChild(el("p", { text: [isNum(h.estimated_monthl'
    'y_savings) ? "Ahorro estimado ≈ " + money(h.estimated_monthly_savings) + "/mes" : null,\n      isNum('
    'h.unattributed_share) ? sh(h.unattributed_share) + " sin atribuir" : null, h.signals + plural(h.sign'
    'als, " señal", " señales")].filter(Boolean).join(" · ") }));\n    var dist = document.getElementById('
    '"severity-dist");\n    clear(dist);\n    dist.hidden = !h.signals;\n    if (!h.signals) { return; }\n   '
    ' var head = el("div", { className: "dist-head" }, [el("span", { text: "Señales de optimización por s'
    'everidad" })]);\n    head.appendChild(rich(el("span"), [[num(h.signals)], plural(h.signals, " señal",'
    ' " señales") + " en " + month]));\n    dist.appendChild(head);\n    var track = el("div", { className:'
    ' "track", role: "img", "aria-label": ["high", "medium", "low"].map(function (s) { return (sev[s] || '
    '0) + " " + L.sev[s].toLowerCase(); }).join(", ") });\n    var legend = el("div", { className: "legend'
    '" });\n    ["high", "medium", "low"].forEach(function (s) {\n      if (!sev[s]) { return; }\n      var '
    'seg = el("i", { title: L.sev[s] + ": " + sev[s] });\n      seg.style.width = (100 * sev[s] / h.signal'
    's) + "%";\n      seg.style.background = SEV_BAR[s];\n      track.appendChild(seg);\n      var key = el('
    '"i");\n      key.style.background = SEV_BAR[s];\n      legend.appendChild(el("span", null, [key, L.sev'
    '[s] + " ", el("b", { text: String(sev[s]) })]));\n    });\n    dist.appendChild(track);\n    dist.appen'
    'dChild(legend);\n  }\n\n  function renderActions(snap) {\n    var holder = document.getElementById("acti'
    'ons-plan");\n    clear(holder);\n    var actions = snap.actions || [];\n    if (!actions.length) { hold'
    'er.appendChild(el("div", { className: "card" }, [emptyState("Sin acciones: ninguna comprobación eval'
    'uada requiere cambios.")])); return; }\n    [["quick_win", "Quick-win", "Menos de 1 semana"], ["short'
    '_term", "Corto plazo", "1-3 meses"], ["medium_term", "Medio plazo", "Planificación posterior"]].forE'
    'ach(function (h) {\n      var items = actions.filter(function (a) { return a.horizon === h[0]; });\n  '
    '    var card = el("div", { className: "card" }, [el("h3", { text: h[1] }), el("p", { className: "sub'
    '", text: h[2] + " · " + items.length + plural(items.length, " acción", " acciones") })]);\n      if ('
    '!items.length) { card.appendChild(el("p", { className: "muted", text: "Sin acciones en este horizont'
    'e." })); }\n      else {\n        var ol = el("ol", { className: "steps" });\n        items.forEach(fun'
    'ction (a, i) {\n          var link = safeLearnUrl(a.learn_url);\n          var meta = el("div", { clas'
    'sName: "sm" }, [sevPill(a.severity, a.severity_label), el("span", { text: a.rule_id + " · " + lab(L.'
    'effort, a.effort_label) })]);\n          if (link) { meta.appendChild(extLink(link, "Documentación"))'
    '; }\n          ol.appendChild(el("li", null, [\n            el("span", { className: "no", text: String'
    '(i + 1) }),\n            el("div", { className: "sx" }, [el("b", { text: a.title }), el("div", { clas'
    'sName: "muted", text: lab(L.level, a.level) + ": " + (a.workload_name || a.resource_id || "—") }), e'
    'l("p", { text: a.recommendation }), meta])\n          ]));\n        });\n        card.appendChild(ol);\n'
    '      }\n      holder.appendChild(card);\n    });\n  }\n\n  function renderSources(snap) {\n    var source'
    's = snap.sources || [];\n    var byStatus = {};\n    sources.forEach(function (s) { byStatus[s.status]'
    ' = (byStatus[s.status] || 0) + 1; });\n    var complete = byStatus.complete || 0;\n    document.getEle'
    'mentById("sources-summary").textContent = complete + " de " + sources.length + plural(sources.length'
    ', " fuente completa", " fuentes completas");\n    var bars = document.getElementById("sources-bars");'
    '\n    clear(bars);\n    Object.keys(L.src).forEach(function (k) {\n      if (!byStatus[k]) { return; }\n'
    '      bars.appendChild(barRow(srcPill(k), null, 100 * byStatus[k] / Math.max(1, sources.length), num'
    '(byStatus[k]), null, SRC_COLOR[k], false));\n    });\n    renderTable(document.getElementById("sources'
    '-table"),\n      ["Fuente", "Plano", "Estado", { t: "Páginas", c: "n" }, { t: "Registros", c: "n" }, '
    '"Hora UTC", { t: "Nota / errores", c: "w" }],\n      sources.map(function (s) {\n        var note = el'
    '("div");\n        if (s.note) { note.appendChild(el("span", { text: s.note })); }\n        (s.errors |'
    '| []).forEach(function (e) {\n          note.appendChild(el("div", { className: "muted", text: [e.htt'
    'p_status ? "HTTP " + e.http_status : null, e.code, e.message].filter(Boolean).join(" · ") }));\n     '
    '   });\n        if (!note.firstChild) { note.textContent = "—"; }\n        return [{ v: mono(s.id), s:'
    ' s.id }, { v: sourcePlane(s.id), c: "nw" }, { v: srcPill(s.status), s: s.status }, { v: num(s.pages)'
    ', s: s.pages }, { v: num(s.records), s: s.records }, { v: utc(s.time), c: "nw" }, { v: note }];\n    '
    '  }), { sortable: true, page: 12 }\n    );\n    var m = snap.methodology || {}, cat = m.catalogSnapsho'
    't || {}, cov = m.catalog_coverage || {};\n    var dl = document.getElementById("method-notes");\n    c'
    'lear(dl);\n    function row(term, node) { dl.appendChild(el("dt", { text: term })); var dd = el("dd")'
    '; dd.appendChild(node instanceof Node ? node : document.createTextNode(node)); dl.appendChild(dd); }'
    '\n    row("Índice local", m.score_formula || "—");\n    row("Cobertura", m.coverage_formula || "—");\n '
    '   var catNode = el("span", { text: (cat.name || "Catálogo local") + " · " + (cov.local_rules || 0) '
    '+ " reglas locales · recuperado " + (cat.retrieved_at || "—") + " " });\n    [[cat.service_guide_url,'
    ' "Guía de servicio"], [cat.lakehouse_waf_url, "Lakehouse WAF"], [m.assessment_url, "Assessment ofici'
    'al"]].forEach(function (l) {\n      var u = safeLearnUrl(l[0]);\n      if (u) { catNode.appendChild(do'
    'cument.createTextNode(" ")); catNode.appendChild(extLink(u, l[1])); }\n    });\n    row("Catálogo de r'
    'eglas", catNode);\n    var interp = el("ul");\n    (m.interpretation || []).forEach(function (t) { int'
    'erp.appendChild(el("li", { text: t })); });\n    row("Interpretación", interp.firstChild ? interp : "'
    '—");\n    var limList = document.getElementById("methodology-limitations");\n    clear(limList);\n    ('
    'm.limitations || []).forEach(function (l) { limList.appendChild(el("li", { text: l })); });\n  }\n\n  f'
    'unction cssString(s) { return String(s).replace(/\\\\/g, "\\\\\\\\").replace(/"/g, \'\\\\"\').replace(/[\\r\\n]+'
    '/g, " ").replace(/</g, "\\\\3c "); }\n  function renderFooter(snap) {\n    var ws = snap.workspace || {}'
    ', client = (snap.client && snap.client.name) || "CLIENTE";\n    var when = utc(snap.reference_utc), c'
    'osts = FOCUS === "costs";\n    document.getElementById("report-footer").textContent = "Generado por A'
    'zure SRE Agent · Solo lectura · generate-databricks-dependency-report · " + when + " · " + client;\n '
    '   document.title = (ws.name ? ws.name + " · " : "") + (costs ? "Costes de Azure Databricks | Origen'
    ' del coste y optimización" : "Revisión Azure Databricks | Mapa de dependencias y configuración");\n  '
    '  var style = document.getElementById("print-page-style");\n    if (!style) { style = el("style", { i'
    'd: "print-page-style" }); document.head.appendChild(style); }\n    var foot = (costs ? "Costes de Azu'
    're Databricks · " : "Revisión Azure Databricks · ") + (ws.name || "—") + " · " + when + (snap.proven'
    'ance === "SIMULATED" ? " · DATOS SIMULADOS" : "");\n    style.textContent = \'@page { @bottom-left { c'
    'ontent: "\' + cssString(foot) + \'"; font: 8pt "Segoe UI", sans-serif; color: #667085; } @bottom-right'
    ' { content: "Página " counter(page) " de " counter(pages); font: 8pt "Segoe UI", sans-serif; color: '
    "#667085; } }';\n  }\n\n  function renderSnapshot(snap) {\n    currentSnap = snap;\n    document.getElemen"
    'tById("workspace-error-view").hidden = true;\n    document.getElementById("report-body").hidden = fal'
    'se;\n    var g = (snap.scores && snap.scores.global) || {};\n    var counts = { critical: 0, high: 0, '
    'medium: 0, low: 0 };\n    (snap.findings || []).forEach(function (f) { if (counts[f.severity] !== und'
    'efined) { counts[f.severity]++; } });\n    var sc = (snap.dependencies && snap.dependencies.summary_c'
    'ounts) || {};\n    renderHero(snap, g, counts);\n    renderCostHero(snap);\n    renderKpis(snap, g, cou'
    'nts);\n    renderFacts(snap);\n    renderExecutive(snap, g);\n    var sum = document.getElementById("de'
    'p-class-summary");\n    clear(sum);\n    [["OBSERVED", sc.edges_observed, " relaciones"], ["INFERRED",'
    ' sc.edges_inferred, " relaciones"], ["UNKNOWN", sc.unknowns_total, " puntos ciegos"]].forEach(functi'
    'on (c) {\n      sum.appendChild(pill("cls-" + c[0], c[0] + " · " + num(c[1] || 0) + c[2]));\n    });\n '
    '   sum.appendChild(pill("sev-info", num(sc.broken_references_total || 0) + plural(sc.broken_referenc'
    'es_total || 0, " referencia rota", " referencias rotas")));\n    document.getElementById("dep-graph-n'
    'ote").textContent = num(sc.nodes_total || 0) + " nodos · " + num(sc.edges_total || 0) + " relaciones'
    ' en total";\n    renderInventory(snap);\n    renderFinops(snap);\n    renderCosts(snap);\n    renderActi'
    'ons(snap);\n    renderSources(snap);\n    renderFooter(snap);\n    applyDependencyFilters();\n    applyF'
    'indingFilters();\n    renderReferenceArchitecture();\n  }\n\n  applyPresentation();\n  if (isMulti) {\n   '
    ' var selWrap = document.getElementById("workspace-selector-wrap");\n    var sel = document.getElement'
    'ById("workspace-selector");\n    var runs = rootData.workspace_runs || [];\n    var agg = rootData.agg'
    'regate || {};\n    document.getElementById("multi-overview").hidden = false;\n    selWrap.hidden = fal'
    'se;\n    rich(document.getElementById("multi-summary"), ["Vista multi-workspace · ", [num(runs.length'
    ')], plural(runs.length, " workspace seleccionado", " workspaces seleccionados") + " · ", [num(agg.fi'
    'ndings_total || 0)], " hallazgos · ",\n      [num((agg.dependency_counts && agg.dependency_counts.nod'
    'es_total) || 0)], " nodos de dependencia · ", [num(agg.failed_workspace_count || 0)], plural(agg.fai'
    'led_workspace_count || 0, " workspace con error", " workspaces con error")]);\n    runs.forEach(funct'
    'ion (r, idx) {\n      sel.appendChild(el("option", { value: String(idx), text: r.workspace_name + " ('
    '" + r.status + ")" }));\n    });\n    var selectRun = function (idx) {\n      var run = runs[idx];\n    '
    '  if (!run) { return; }\n      if (run.snapshot) {\n        renderSnapshot(run.snapshot);\n      } else'
    ' {\n        currentSnap = null;\n        document.getElementById("report-body").hidden = true;\n       '
    ' var errView = document.getElementById("workspace-error-view");\n        errView.hidden = false;\n    '
    '    clear(errView);\n        var err = run.error || {};\n        errView.appendChild(el("h2", { text: '
    '"Recolección fallida para el workspace " + run.workspace_name }));\n        errView.appendChild(el("p'
    '", { text: "No se sustituyen datos vacíos ni puntuaciones de otro workspace. Seleccione otro workspa'
    'ce o corrija el acceso y repita la revisión." }));\n        var dl = el("dl", { className: "dl2" });\n'
    '        [["Código", err.code], ["Fuente", err.source_id], ["HTTP", err.http_status], ["Mensaje", err'
    '.message], ["Hora UTC", utc(run.reference_utc)]].forEach(function (p) {\n          dl.appendChild(el('
    '"dt", { text: p[0] }));\n          dl.appendChild(el("dd", { text: p[1] === null || p[1] === undefine'
    'd || p[1] === "" ? "—" : String(p[1]) }));\n        });\n        errView.appendChild(dl);\n      }\n    '
    '};\n    sel.addEventListener("change", function () { selectRun(Number(sel.value)); });\n    selectRun('
    '0);\n  } else {\n    renderSnapshot(rootData);\n  }\n\n  var navLinks = [].slice.call(document.querySelec'
    'torAll(".bar-nav a"));\n  if ("IntersectionObserver" in window && navLinks.length) {\n    var spy = ne'
    'w IntersectionObserver(function (entries) {\n      entries.forEach(function (en) {\n        if (!en.is'
    'Intersecting) { return; }\n        var id = en.target.id;\n        navLinks.forEach(function (a) { if '
    '(a.getAttribute("href") === "#" + id) { a.setAttribute("aria-current", "true"); } else { a.removeAtt'
    'ribute("aria-current"); } });\n      });\n    }, { rootMargin: "-80px 0px -65% 0px" });\n    ["sec-cove'
    'r", "sec-identity", "sec-executive", "sec-dependencies", "sec-inventory", "sec-findings", "sec-finop'
    's", "sec-actions", "sec-sources"].forEach(function (id) {\n      var node = document.getElementById(i'
    'd);\n      if (node) { spy.observe(node); }\n    });\n  }\n})();\n</script>\n</body>\n</html>\n'
)
# END BUILD-TIME ASSETS


SIDECAR_TOKEN_ISSUER = "adc-msi-sidecar"


def normalize_sidecar_claims(claims):
    """Map Azure SRE Agent sandbox token claims onto the standard Entra names.

    Python tools in the SRE Agent sandbox receive placeholder tokens issued by the identity sidecar
    (iss "adc-msi-sidecar") that the platform proxy replaces with the real managed identity token at egress.
    They carry tid, clientId and scp instead of aud/appid, so tenant, client and audience stay verifiable.
    """
    if not isinstance(claims, dict) or claims.get("iss") != SIDECAR_TOKEN_ISSUER:
        return claims
    scope = claims.get("scp") if isinstance(claims.get("scp"), str) else ""
    audience = scope[:-len("/.default")] if scope.endswith("/.default") else scope
    if audience.rstrip("/").lower() == "https://management.core.windows.net":
        audience = "https://management.azure.com"
    return dict(claims, appid=claims.get("clientId") or claims.get("cid") or None, aud=audience or None)


class EvidenceError(RuntimeError):
    def __init__(self, code, message, source="assessment", http_status=None):
        super().__init__(message)
        self.code, self.source, self.http_status = code, source, http_status

    def public(self):
        return {"code": self.code, "message": str(self), "source_id": self.source, "http_status": self.http_status}


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def obj(value, source="normalization"):
    if not isinstance(value, dict):
        raise EvidenceError("invalid_shape", "Expected a source object; no empty-success substitution.", source)
    return value


def array(value, source="normalization"):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise EvidenceError("invalid_shape", "Expected an array of source objects.", source)
    return value


def pick(value, *keys):
    result = value
    for key in keys:
        if not isinstance(result, dict) or key not in result:
            return None
        result = result[key]
    return result


def text(value, source="normalization", maximum=8192):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > maximum or any(ord(c) < 32 for c in value):
        raise EvidenceError("invalid_field", "Source text has an invalid type, control character or safety-bound length.", source)
    return value


def number(value, source="normalization"):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise EvidenceError("invalid_field", "Source numeric value must be finite.", source)
    return value


def boolean(value, source="normalization"):
    if value is not None and not isinstance(value, bool):
        raise EvidenceError("invalid_field", "Source boolean field has an invalid type.", source)
    return value


def strings(value, source="normalization"):
    if value is None:
        return None
    if not isinstance(value, list):
        raise EvidenceError("invalid_field", "Source string-list field has an invalid type.", source)
    return [text(item, source) for item in value]


def tags_map(value, source):
    if value is None:
        return {}
    result = {}
    for key, item in obj(value, source).items():
        k = text(str(key), source, 256)
        if any(secret_word in k.lower() for secret_word in ("secret", "password", "token", "key", "sas", "credential")):
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            result[k] = text(str(item), source, 512) if item is not None else None
    return result


def validate_logo(uri, alt=CLIENT_LOGO_ALT):
    if uri == "":
        return
    if not isinstance(uri, str) or len(uri) > 140000:
        raise EvidenceError("invalid_logo", "Optional logo must be a bounded inline PNG/JPEG, not a path or URL.", "branding")
    match = re.fullmatch(r"data:image/(png|jpeg);base64,([A-Za-z0-9+/=]+)", uri)
    if not match:
        raise EvidenceError("invalid_logo", "Only inline PNG/JPEG MIME with canonical base64 is allowed.", "branding")
    try:
        data = base64.b64decode(match[2], validate=True)
    except binascii.Error as exc:
        raise EvidenceError("invalid_logo", "Invalid logo base64.", "branding") from exc
    if not 1 <= len(data) <= 100000:
        raise EvidenceError("invalid_logo", "Optional raster logo must contain 1..100000 bytes.", "branding")
    if not isinstance(alt, str) or not alt.strip() or len(alt) > 120 or re.search(r"[\x00-\x1f\x7f]", alt):
        raise EvidenceError("invalid_logo", "Provide 1..120 plain characters of descriptive logo alt text.", "branding")
    try:
        from PIL import Image, ImageFile, UnidentifiedImageError
    except ImportError as exc:
        raise EvidenceError("dependency_missing", "A configured logo requires Pillow for genuine bounded raster validation.", "branding") from exc
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise EvidenceError("unsafe_decoder_settings", "Truncated-image decoding must not be enabled; no signature-only fallback.", "branding")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=["PNG", "JPEG"]) as image:
                width, height = image.size
                if (
                    image.format != ("PNG" if match[1] == "png" else "JPEG")
                    or not 1 <= width <= 2048 or not 1 <= height <= 2048
                    or getattr(image, "n_frames", 1) != 1
                ):
                    raise EvidenceError("invalid_logo", "Use one PNG/JPEG frame, matching MIME, at most 2048 by 2048 pixels.", "branding")
                image.verify()
            with Image.open(io.BytesIO(data), formats=["PNG", "JPEG"]) as image:
                image.load()
    except (OSError, ValueError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise EvidenceError("invalid_logo", "The optional logo is not a complete, valid single-frame PNG/JPEG raster.", "branding") from exc


def validate_cost_settings():
    if COST_METRIC not in ("AmortizedCost", "ActualCost"):
        raise EvidenceError("configuration_required", "COST_METRIC must be AmortizedCost or ActualCost.", "configuration")
    tags = COST_ALLOCATION_TAGS
    if (
        not isinstance(tags, list) or len(tags) > 3
        or any(not isinstance(t, str) or not re.fullmatch(r"[A-Za-z0-9_.:/=+@-][A-Za-z0-9 _.:/=+@-]{0,127}", t) for t in tags)
        or len({t.lower() for t in tags}) != len(tags)
    ):
        raise EvidenceError("configuration_required", "COST_ALLOCATION_TAGS holds up to 3 distinct tag keys.", "configuration")
    for name, value, low, high in (
        ("COST_AUTOTERMINATION_MAX_MINUTES", COST_AUTOTERMINATION_MAX_MINUTES, 10, 1440),
        ("COST_WAREHOUSE_AUTOSTOP_MAX_MINUTES", COST_WAREHOUSE_AUTOSTOP_MAX_MINUTES, 1, 1440),
        ("COST_JOBS_TO_ALL_PURPOSE_DBU_RATIO", COST_JOBS_TO_ALL_PURPOSE_DBU_RATIO, 0.05, 1),
        ("COST_SPOT_DISCOUNT", COST_SPOT_DISCOUNT, 0, 0.95),
    ):
        if isinstance(value, bool) or not isinstance(value, (int, float)) or not low <= value <= high:
            raise EvidenceError("configuration_required", name + " is outside its documented range.", "configuration")


def presentation_settings():
    """Validated presentation hooks embedded in the report: focus, colour overrides, heading font and logo placement."""
    if REPORT_FOCUS not in ("configuration", "costs"):
        raise EvidenceError("configuration_required", "REPORT_FOCUS must be configuration or costs.", "branding")
    if BRAND_LOGO_PLACEMENT not in ("hero", "bar"):
        raise EvidenceError("configuration_required", "BRAND_LOGO_PLACEMENT must be hero or bar.", "branding")
    if not isinstance(BRAND_THEME, dict) or len(BRAND_THEME) > len(BRAND_THEME_KEYS):
        raise EvidenceError("configuration_required", "BRAND_THEME maps documented CSS variables to colours.", "branding")
    colour = r"#[0-9A-Fa-f]{6}|rgba\((?:\s*\d{1,3}\s*,){3}\s*(?:0|1|0?\.\d{1,3})\s*\)"
    for key, value in BRAND_THEME.items():
        if key not in BRAND_THEME_KEYS or not isinstance(value, str) or not re.fullmatch(colour, value):
            raise EvidenceError("configuration_required", "BRAND_THEME accepts only " + ", ".join(BRAND_THEME_KEYS) + " with #RRGGBB or rgba() colours.", "branding")
    font = BRAND_DISPLAY_FONT_DATA_URI
    if font:
        match = re.fullmatch(r"data:font/woff2;base64,([A-Za-z0-9+/=]+)", font) if isinstance(font, str) and len(font) <= 110000 else None
        try:
            data = base64.b64decode(match[1], validate=True) if match else b""
        except binascii.Error:
            data = b""
        if not 1000 <= len(data) <= 80000 or not data.startswith(b"wOF2"):
            raise EvidenceError("configuration_required", "BRAND_DISPLAY_FONT_DATA_URI must be an inline WOFF2 font of at most 80 KB.", "branding")
    return {"focus": REPORT_FOCUS, "logo_placement": BRAND_LOGO_PLACEMENT, "theme": dict(BRAND_THEME), "display_font": font}


def response_bytes(value):
    return len(json.dumps(value, allow_nan=False).encode("utf-8"))


def ensure_response(value):
    if response_bytes(value) > TRANSPORT_BYTES:
        raise EvidenceError("transport_size_exceeded", "Default-serialized response exceeds 3500 bytes; no malformed/truncated JSON is returned.", "transport")
    return value


def arm_id(value, subscription=None):
    value = text(value, "scope", 2048)
    if value is None:
        raise EvidenceError("invalid_resource_id", "A scoped ARM resource ID is required.", "scope")
    parts = value.split("/")
    if (
        len(parts) < 9 or parts[0] != "" or parts[1].lower() != "subscriptions"
        or parts[3].lower() != "resourcegroups" or parts[5].lower() != "providers"
        or any(not re.fullmatch(r"[A-Za-z0-9_.()-]+", part) or part in (".", "..") for part in parts[2:])
        or (subscription and parts[2].lower() != subscription.lower())
    ):
        raise EvidenceError("invalid_resource_id", "Resource ID changed the fixed subscription or has unsafe syntax.", "scope")
    try:
        UUID(parts[2])
    except ValueError as exc:
        raise EvidenceError("invalid_resource_id", "Resource ID subscription is not a GUID.", "scope") from exc
    return value


def resource_type(resource_id):
    parts = arm_id(resource_id).split("/")
    return (parts[6] + "/" + "/".join(parts[7::2])).lower()


def validate_guid(value, field_name):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value.lower() or UUID(value).int == 0:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise EvidenceError("configuration_required", "Configure the explicit " + field_name + " before authentication.", "configuration") from exc
    return value.lower()


def validate_workspace_host(host, required=True):
    if not required and not host:
        return ""
    if not isinstance(host, str) or not re.fullmatch(r"adb-[0-9]{10,24}\.[0-9]{1,4}\.azuredatabricks\.net", host):
        raise EvidenceError(
            "configuration_required",
            "Configure workspace_host as an exact per-workspace hostname (adb-<id>.<shard>.azuredatabricks.net) without scheme or path.",
            "configuration",
        )
    return host.lower()


def validate_config(workspace_name):
    validate_guid(SUBSCRIPTION_ID, "SUBSCRIPTION_ID")
    sre_tid = validate_guid(SRE_TENANT_ID, "SRE_TENANT_ID")
    target_tid = validate_guid(TARGET_TENANT_ID, "TARGET_TENANT_ID")
    validate_guid(MANAGED_IDENTITY_CLIENT_ID, "MANAGED_IDENTITY_CLIENT_ID")
    if not isinstance(APPROVED_WORKSPACES, dict) or not 1 <= len(APPROVED_WORKSPACES) <= 5:
        raise EvidenceError("configuration_required", "Configure one to five fixed approved Databricks workspaces.", "configuration")
    name = workspace_name or next(iter(APPROVED_WORKSPACES))
    if name not in APPROVED_WORKSPACES:
        raise EvidenceError("invalid_parameter", "workspace_name must exactly match the fixed operator allowlist.", "parameters")
    config = obj(APPROVED_WORKSPACES[name], "configuration")
    for field, value, maximum in (("name", name, 64), ("resource_group", config.get("resource_group"), 90)):
        if not isinstance(value, str) or not 1 <= len(value) <= maximum or not re.fullmatch(r"[A-Za-z0-9_.()-]+", value):
            raise EvidenceError("configuration_required", "Configure a bounded approved " + field + ".", "configuration")
    if config.get("environment") not in ("LAB", "PRODUCTION", "UNSPECIFIED"):
        raise EvidenceError("configuration_required", "Set explicit LAB/PRODUCTION/UNSPECIFIED environment.", "configuration")
    auth_mode = config.get("auth_mode")
    if auth_mode not in AUTH_MODES:
        raise EvidenceError("configuration_required", "Set auth_mode to one of: " + ", ".join(AUTH_MODES) + ".", "configuration")
    if auth_mode == "same_tenant_uami" and sre_tid != target_tid:
        raise EvidenceError(
            "cross_tenant_configuration_required",
            "SRE_TENANT_ID and TARGET_TENANT_ID differ: a single-tenant UAMI cannot directly authenticate across tenants. Configure cross_tenant_multitenant_fic or cross_tenant_lighthouse_plus_databricks_oidc after completing the colleague tenant setup.",
            "configuration",
        )
    for field in ("workspace_api_enabled", "unity_catalog_enabled", "include_managed_resource_group", "advisor_enabled"):
        if not isinstance(config.get(field), bool):
            raise EvidenceError("configuration_required", "Configure the boolean " + field + ".", "configuration")
    dbx_plane_enabled = config["workspace_api_enabled"] or config["unity_catalog_enabled"]
    if auth_mode == "cross_tenant_multitenant_fic" or (
        dbx_plane_enabled and auth_mode in ("cross_tenant_lighthouse_plus_databricks_oidc", "cross_tenant_lighthouse_plus_keyvault_oauth_m2m")
    ):
        validate_guid(FEDERATED_APP_CLIENT_ID, "FEDERATED_APP_CLIENT_ID")
    if auth_mode == "cross_tenant_multitenant_fic" and (CROSS_TENANT_CERT_KEYVAULT_URL or CROSS_TENANT_CERT_NAME):
        if not (
            isinstance(CROSS_TENANT_CERT_KEYVAULT_URL, str)
            and re.fullmatch(r"https://[a-z0-9-]{3,24}\.vault\.azure\.net/?", CROSS_TENANT_CERT_KEYVAULT_URL)
            and isinstance(CROSS_TENANT_CERT_NAME, str)
            and re.fullmatch(r"[A-Za-z0-9-]{1,127}", CROSS_TENANT_CERT_NAME)
        ):
            raise EvidenceError(
                "configuration_required",
                "Configure CROSS_TENANT_CERT_KEYVAULT_URL as https://<vault>.vault.azure.net and CROSS_TENANT_CERT_NAME as the certificate name, or leave both empty.",
                "configuration",
            )
    if dbx_plane_enabled and auth_mode == "cross_tenant_lighthouse_plus_keyvault_oauth_m2m":
        if not isinstance(KEYVAULT_OAUTH_SECRET_URI, str) or not re.fullmatch(
            r"https://[a-z0-9-]{3,24}\.vault\.azure\.net/secrets/[A-Za-z0-9-]{1,127}(?:/[0-9a-f]{32})?",
            KEYVAULT_OAUTH_SECRET_URI,
        ):
            raise EvidenceError(
                "configuration_required",
                "Configure KEYVAULT_OAUTH_SECRET_URI as https://<vault>.vault.azure.net/secrets/<secret-name> in the SRE tenant.",
                "configuration",
            )
    host = validate_workspace_host(config.get("workspace_host", ""), required=dbx_plane_enabled)
    if config.get("cost_scope") not in ("disabled", "resource_ids", "managed_resource_group"):
        raise EvidenceError("configuration_required", "Configure disabled/resource_ids/managed_resource_group cost scope.", "configuration")
    if config.get("cost_timeframe") not in ("month_to_date", "last_30_days"):
        raise EvidenceError("configuration_required", "Configure month_to_date/last_30_days billing timeframe.", "configuration")
    cost_analysis = config.get("cost_analysis_enabled", True)
    if not isinstance(cost_analysis, bool):
        raise EvidenceError("configuration_required", "Configure the boolean cost_analysis_enabled.", "configuration")
    warehouse = config.get("system_tables_warehouse_id", "")
    if not isinstance(warehouse, str) or (warehouse and not re.fullmatch(r"[A-Za-z0-9]{8,64}", warehouse)):
        raise EvidenceError("configuration_required", "system_tables_warehouse_id is empty (off) or the ID of an existing SQL warehouse.", "configuration")
    validate_cost_settings()
    presentation_settings()
    for field in ("approved_related_resource_ids", "approved_cost_resource_ids"):
        ids = config.get(field)
        if not isinstance(ids, list) or len(ids) > MAX_RELATED_RESOURCES or len({str(i).lower() for i in ids}) != len(ids):
            raise EvidenceError("configuration_required", "Configure distinct bounded fixed resource IDs.", "configuration")
        for value in ids:
            arm_id(value, SUBSCRIPTION_ID)
    requirements = obj(config.get("requirements"), "configuration")
    allowed = {
        "premium_required",
        "no_public_ip_required",
        "vnet_injection_required",
        "private_link_required",
        "access_connector_required",
        "cmk_required",
        "enhanced_security_required",
        "diagnostics_required",
        "pat_restriction_required",
        "unity_catalog_required",
        "cluster_policy_required",
        "autoscaling_required",
        "service_principal_jobs_required",
        "keyvault_secret_scopes_required",
        "shared_key_disabled_required",
    }
    if set(requirements) - allowed:
        raise EvidenceError("configuration_required", "Unknown requirement key; requirements are operator-authored, not query inputs.", "configuration")
    for key, value in requirements.items():
        if value is not None and not isinstance(value, bool):
            raise EvidenceError("configuration_required", "Requirement values must be boolean or unknown.", "configuration")
    validate_logo(CLIENT_LOGO_DATA_URI, CLIENT_LOGO_ALT)
    if not isinstance(CLIENT_NAME, str) or not 1 <= len(CLIENT_NAME) <= 120 or any(ord(c) < 32 for c in CLIENT_NAME):
        raise EvidenceError("configuration_required", "Client label must be bounded plain text.", "configuration")
    return {
        **config,
        "name": name,
        "workspace_host": host,
        "cost_analysis_enabled": cost_analysis,
        "system_tables_warehouse_id": warehouse,
        "sre_tenant_id": sre_tid,
        "target_tenant_id": target_tid,
        "cross_tenant": sre_tid != target_tid,
        "id": "/subscriptions/" + SUBSCRIPTION_ID + "/resourceGroups/" + config["resource_group"]
        + "/providers/Microsoft.Databricks/workspaces/" + name,
    }


def selection_configs(workspace_name, workspace_names):
    first = validate_config(workspace_name)
    configured = [validate_config(name) for name in APPROVED_WORKSPACES]
    names = workspace_names.split(",") if workspace_names else [first["name"]]
    if len(set(names)) != len(names) or any(name not in APPROVED_WORKSPACES for name in names):
        raise EvidenceError("invalid_parameter", "Select distinct exact fixed allowlisted workspace names only.", "parameters")
    by_name = {config["name"]: config for config in configured}
    roster = [
        {
            "workspace_id": config["id"],
            "workspace_name": config["name"],
            "resource_group": config["resource_group"],
            "workspace_host": config["workspace_host"],
            "environment": config["environment"],
            "auth_mode": config["auth_mode"],
            "cross_tenant": config["cross_tenant"],
        }
        for config in configured
    ]
    return [by_name[name] for name in names], roster


def validate_parameters(
    operation, view, workspace_name, workspace_names, workload_name,
    classification, area, level, severity, status, limit, offset,
):
    for key, value, choices in (
        ("operation", operation, OPERATIONS),
        ("view", view, VIEWS),
        ("classification", classification, ("all",) + CLASSIFICATIONS),
        ("area", area, ("all",) + AREAS),
        ("level", level, ("all",) + LEVELS),
        ("severity", severity, ("all",) + SEVERITIES),
        ("status", status, ("all",) + CHECK_STATUSES + SOURCE_STATUSES),
    ):
        if value not in choices:
            raise EvidenceError("invalid_parameter", key + " must use its declared enum.", "parameters")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise EvidenceError("invalid_parameter", "limit must be an integer from 1 to 100.", "parameters")
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 500000:
        raise EvidenceError("invalid_parameter", "offset must be an integer from 0 to 500000.", "parameters")
    for key, value, maximum in (("workspace_name", workspace_name, 64), ("workload_name", workload_name, 253)):
        if not isinstance(value, str) or len(value) > maximum or (value and not re.fullmatch(r"[A-Za-z0-9_.:()-]+", value)):
            raise EvidenceError("invalid_parameter", key + " is a bounded exact local name, not a path, URL or command.", "parameters")
    if not isinstance(workspace_names, str) or len(workspace_names) > 324 or (
        workspace_names and not re.fullmatch(r"[A-Za-z0-9_.()-]{1,64}(?:,[A-Za-z0-9_.()-]{1,64}){0,4}", workspace_names)
    ):
        raise EvidenceError("invalid_parameter", "workspace_names is an exact comma-separated allowlist selection of one to five names, without spaces.", "parameters")
    if workspace_name and workspace_names:
        raise EvidenceError("invalid_combination", "Use workspace_name or workspace_names, not both.", "parameters")
    filters = any((workload_name, classification != "all", area != "all", level != "all", severity != "all", status != "all"))
    if operation in ("report", "list_workspaces", "self_test") and (view != "summary" or filters or limit != 25 or offset != 0):
        raise EvidenceError("invalid_combination", "report/list_workspaces/self_test cannot be narrowed by query filters or paging.", "parameters")
    if operation in ("list_workspaces", "self_test") and (workspace_name or workspace_names):
        raise EvidenceError("invalid_combination", "list_workspaces and self_test do not select a workspace.", "parameters")
    if operation == "query":
        if classification != "all" and view != "dependencies":
            raise EvidenceError("invalid_combination", "classification filter applies only to view=dependencies.", "parameters")
        if view in ("summary", "workspace", "coverage") and workload_name:
            raise EvidenceError("invalid_combination", "workload_name filter does not apply to summary, workspace or coverage views.", "parameters")
        if view not in ("findings", "actions") and any((area != "all", level != "all", severity != "all")):
            raise EvidenceError("invalid_combination", "Area/level/severity filters apply only to findings or actions.", "parameters")
        if status != "all" and (
            (view == "coverage" and status not in SOURCE_STATUSES)
            or (view in ("findings", "actions") and status not in CHECK_STATUSES)
            or view not in ("coverage", "findings", "actions")
        ):
            raise EvidenceError("invalid_combination", "Status does not belong to the selected view.", "parameters")
    return dict(
        operation=operation, view=view, workspace_name=workspace_name, workspace_names=workspace_names,
        workload_name=workload_name, classification=classification, area=area, level=level,
        severity=severity, status=status, limit=limit, offset=offset,
    )


def source_receipt(source_id, reference, status="complete", note="", **extra):
    return {
        "id": source_id, "status": status, "time": reference, "records": 0, "pages": 0,
        "errors": [], "note": note, "window": None, **extra,
    }


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def verify_jwt_claims(token_str, expected_tid, expected_client, expected_aud):
    try:
        encoded = token_str.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
        claims = normalize_sidecar_claims(claims)
    except (AttributeError, IndexError, ValueError, binascii.Error) as exc:
        raise EvidenceError("authentication_failed", "Identity provider returned an unreadable JWT; token contents are excluded.", "identity") from exc
    tenant = pick(claims, "tid")
    client = pick(claims, "appid") or pick(claims, "azp")
    aud = pick(claims, "aud")
    expected_norm = expected_aud.rstrip("/").lower()
    aud_norm = aud.rstrip("/").lower() if isinstance(aud, str) else ""
    aud_valid = (
        aud_norm in ARM_TOKEN_AUDIENCES
        if expected_norm == ARM_ORIGIN.lower()
        else aud_norm in ENTRA_TOKEN_EXCHANGE_AUDIENCES
        if expected_norm == ENTRA_TOKEN_EXCHANGE_AUDIENCE.lower()
        else aud_norm == expected_norm
    )
    if not (
        isinstance(tenant, str) and tenant.lower() == expected_tid.lower()
        and isinstance(client, str) and client.lower() == expected_client.lower()
        and aud_valid
    ):
        raise EvidenceError("identity_mismatch", "Token tenant, client identity or audience differs from the fixed configuration.", "identity")
    return claims


class Identity:
    def __init__(self, config):
        try:
            from azure.identity import ManagedIdentityCredential
        except ImportError as exc:
            raise EvidenceError("dependency_missing", "Live reads require azure-identity; no cached-login fallback.", "identity") from exc
        self.config = config
        self.credential = ManagedIdentityCredential(client_id=MANAGED_IDENTITY_CLIENT_ID)
        self.deadline = time.monotonic() + MAX_COLLECTION_SECONDS
        self.request_count = 0
        self.context = ssl.create_default_context()
        if self.context.verify_mode != ssl.CERT_REQUIRED or not self.context.check_hostname:
            raise EvidenceError("unsafe_tls", "TLS peer and hostname validation are mandatory.", "tls")
        self.opener = build_opener(NoRedirect(), HTTPSHandler(context=self.context))

    def _guard_budget(self):
        if time.monotonic() >= self.deadline:
            raise EvidenceError("collection_deadline", "Collection elapsed-time bound reached; remaining reads are unavailable, not healthy.", "collection")
        if self.request_count >= MAX_HTTP_ATTEMPTS:
            raise EvidenceError("request_cap", "Collection HTTP-attempt bound reached; no narrower success is substituted.", "collection")
        self.request_count += 1

    def uami_token(self, audience):
        from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError
        from azure.identity import CredentialUnavailableError
        self._guard_budget()
        try:
            token = self.credential.get_token(audience.rstrip("/") + "/.default").token
        except (ClientAuthenticationError, CredentialUnavailableError, ServiceRequestError) as exc:
            raise EvidenceError("authentication_failed", "The explicitly selected SRE managed identity could not acquire a token.", "identity") from exc
        verify_jwt_claims(token, SRE_TENANT_ID, MANAGED_IDENTITY_CLIENT_ID, audience)
        return token

    def exchange_entra_certificate(self, target_resource):
        kv_token = self.uami_token(KEYVAULT_AUDIENCE)
        self._guard_budget()
        kv_req = Request(CROSS_TENANT_CERT_KEYVAULT_URL.rstrip("/") + "/secrets/" + CROSS_TENANT_CERT_NAME + "?api-version=7.4",
                         method="GET", headers={"Authorization": "Bearer " + kv_token, "Accept": "application/json"})
        try:
            with self.opener.open(kv_req, timeout=15) as response:
                kv_payload = obj(json.loads(response.read(65536)), "identity")
        except HTTPError as exc:
            raise EvidenceError("keyvault_secret_read_failed", "Key Vault cross-tenant certificate read failed with HTTP " + str(exc.code) + ".", "identity", exc.code) from exc
        except (URLError, TimeoutError, ssl.SSLError, OSError, ValueError) as exc:
            raise EvidenceError("keyvault_secret_read_failed", "Key Vault cross-tenant certificate transport failed.", "identity") from exc
        pem = kv_payload.get("value")
        if not isinstance(pem, str) or len(pem) > 32768 or "-----BEGIN" not in pem:
            raise EvidenceError("keyvault_secret_read_failed", "Key Vault returned no PEM certificate for the cross-tenant app.", "identity")
        self._guard_budget()
        try:
            from azure.identity import CertificateCredential
            access_token = CertificateCredential(TARGET_TENANT_ID.lower(), FEDERATED_APP_CLIENT_ID.lower(),
                                                 certificate_data=pem.encode("utf-8")).get_token(target_resource.rstrip("/") + "/.default").token
        except Exception as exc:
            raise EvidenceError("cross_tenant_auth_failed", "Cross-tenant certificate sign-in failed: " + " ".join(str(exc).split())[:220], "identity") from exc
        verify_jwt_claims(access_token, TARGET_TENANT_ID, FEDERATED_APP_CLIENT_ID, target_resource)
        return access_token

    def exchange_entra_fic(self, target_resource):
        if CROSS_TENANT_CERT_KEYVAULT_URL and CROSS_TENANT_CERT_NAME:
            return self.exchange_entra_certificate(target_resource)
        assertion = self.uami_token(ENTRA_TOKEN_EXCHANGE_AUDIENCE)
        self._guard_budget()
        token_url = "https://login.microsoftonline.com/" + TARGET_TENANT_ID.lower() + "/oauth2/v2.0/token"
        form = urlencode({
            "client_id": FEDERATED_APP_CLIENT_ID.lower(),
            "grant_type": "client_credentials",
            "scope": target_resource.rstrip("/") + "/.default",
            "client_assertion_type": "urn:ietf:params:oauth:client-assertion-type:jwt-bearer",
            "client_assertion": assertion,
        }).encode("utf-8")
        request = Request(token_url, data=form, method="POST", headers={
            "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json",
        })
        try:
            with self.opener.open(request, timeout=20) as response:
                if response.status != 200:
                    raise EvidenceError("cross_tenant_auth_failed", "Cross-tenant Entra FIC exchange returned HTTP " + str(response.status) + ".", "identity", response.status)
                payload = obj(json.loads(response.read(65536)), "identity")
        except HTTPError as exc:
            raise EvidenceError("cross_tenant_auth_failed", "Cross-tenant Entra FIC token exchange failed with HTTP " + str(exc.code) + ".", "identity", exc.code) from exc
        except (URLError, TimeoutError, ssl.SSLError, OSError, ValueError) as exc:
            raise EvidenceError("cross_tenant_auth_failed", "Cross-tenant Entra FIC token transport failed.", "identity") from exc
        access_token = text(payload.get("access_token"), "identity", 32768)
        if not access_token:
            raise EvidenceError("cross_tenant_auth_failed", "Cross-tenant Entra FIC response contained no access_token.", "identity")
        verify_jwt_claims(access_token, TARGET_TENANT_ID, FEDERATED_APP_CLIENT_ID, target_resource)
        return access_token

    def exchange_databricks_oidc(self, workspace_host):
        assertion = self.uami_token(ENTRA_TOKEN_EXCHANGE_AUDIENCE)
        self._guard_budget()
        token_url = "https://" + workspace_host + "/oidc/v1/token"
        form = urlencode({
            "client_id": FEDERATED_APP_CLIENT_ID.lower(),
            "subject_token": assertion,
            "subject_token_type": "urn:ietf:params:oauth:token-type:jwt",
            "grant_type": "urn:ietf:params:oauth:grant-type:token-exchange",
            "scope": "all-apis",
        }).encode("utf-8")
        request = Request(token_url, data=form, method="POST", headers={
            "Content-Type": "application/x-www-form-urlencoded", "Accept": "application/json",
        })
        try:
            with self.opener.open(request, timeout=20) as response:
                if response.status != 200:
                    raise EvidenceError("databricks_oidc_failed", "Databricks OIDC federation exchange returned HTTP " + str(response.status) + ".", "workspace_auth", response.status)
                payload = obj(json.loads(response.read(65536)), "workspace_auth")
        except HTTPError as exc:
            raise EvidenceError("databricks_oidc_failed", "Databricks OIDC federation exchange failed with HTTP " + str(exc.code) + ".", "workspace_auth", exc.code) from exc
        except (URLError, TimeoutError, ssl.SSLError, OSError, ValueError) as exc:
            raise EvidenceError("databricks_oidc_failed", "Databricks OIDC federation transport failed.", "workspace_auth") from exc
        access_token = text(payload.get("access_token"), "workspace_auth", 32768)
        if not access_token:
            raise EvidenceError("databricks_oidc_failed", "Databricks OIDC federation returned no access_token.", "workspace_auth")
        return access_token

    def exchange_keyvault_oauth_m2m(self, workspace_host):
        kv_token = self.uami_token(KEYVAULT_AUDIENCE)
        self._guard_budget()
        kv_url = KEYVAULT_OAUTH_SECRET_URI + "?api-version=7.4"
        kv_req = Request(kv_url, method="GET", headers={
            "Authorization": "Bearer " + kv_token, "Accept": "application/json",
        })
        try:
            with self.opener.open(kv_req, timeout=15) as response:
                if response.status != 200:
                    raise EvidenceError("keyvault_secret_read_failed", "Key Vault OAuth secret read returned HTTP " + str(response.status) + ".", "workspace_auth", response.status)
                kv_payload = obj(json.loads(response.read(65536)), "workspace_auth")
        except HTTPError as exc:
            raise EvidenceError("keyvault_secret_read_failed", "Key Vault OAuth secret read failed with HTTP " + str(exc.code) + ".", "workspace_auth", exc.code) from exc
        except (URLError, TimeoutError, ssl.SSLError, OSError, ValueError) as exc:
            raise EvidenceError("keyvault_secret_read_failed", "Key Vault OAuth secret transport failed.", "workspace_auth") from exc
        secret_value = text(kv_payload.get("value"), "workspace_auth", 4096)
        if not secret_value:
            raise EvidenceError("keyvault_secret_read_failed", "Key Vault returned an empty OAuth secret value.", "workspace_auth")
        self._guard_budget()
        token_url = "https://" + workspace_host + "/oidc/v1/token"
        basic = base64.b64encode((FEDERATED_APP_CLIENT_ID.lower() + ":" + secret_value).encode("utf-8")).decode("ascii")
        form = urlencode({"grant_type": "client_credentials", "scope": "all-apis"}).encode("utf-8")
        request = Request(token_url, data=form, method="POST", headers={
            "Authorization": "Basic " + basic,
            "Content-Type": "application/x-www-form-urlencoded",
            "Accept": "application/json",
        })
        try:
            with self.opener.open(request, timeout=20) as response:
                if response.status != 200:
                    raise EvidenceError("databricks_oauth_m2m_failed", "Databricks OAuth M2M exchange returned HTTP " + str(response.status) + ".", "workspace_auth", response.status)
                payload = obj(json.loads(response.read(65536)), "workspace_auth")
        except HTTPError as exc:
            raise EvidenceError("databricks_oauth_m2m_failed", "Databricks OAuth M2M exchange failed with HTTP " + str(exc.code) + ".", "workspace_auth", exc.code) from exc
        except (URLError, TimeoutError, ssl.SSLError, OSError, ValueError) as exc:
            raise EvidenceError("databricks_oauth_m2m_failed", "Databricks OAuth M2M transport failed.", "workspace_auth") from exc
        access_token = text(payload.get("access_token"), "workspace_auth", 32768)
        if not access_token:
            raise EvidenceError("databricks_oauth_m2m_failed", "Databricks OAuth M2M returned no access_token.", "workspace_auth")
        return access_token

    def arm_token(self):
        if self.config["auth_mode"] == "cross_tenant_multitenant_fic":
            return self.exchange_entra_fic(ARM_ORIGIN)
        return self.uami_token(ARM_ORIGIN)

    def databricks_token(self):
        mode = self.config["auth_mode"]
        if mode == "same_tenant_uami":
            return self.uami_token(DATABRICKS_ENTRA_RESOURCE)
        if mode == "cross_tenant_multitenant_fic":
            return self.exchange_entra_fic(DATABRICKS_ENTRA_RESOURCE)
        if mode == "cross_tenant_lighthouse_plus_databricks_oidc":
            return self.exchange_databricks_oidc(self.config["workspace_host"])
        if mode == "cross_tenant_lighthouse_plus_keyvault_oauth_m2m":
            return self.exchange_keyvault_oauth_m2m(self.config["workspace_host"])
        raise EvidenceError("configuration_required", "Unsupported authentication mode.", "configuration")

    def close(self):
        self.credential.close()


class HttpReader:
    def __init__(self, identity, origin=ARM_ORIGIN, token_kind="arm", patient=False):
        self.identity, self.origin, self.token_kind = identity, origin, token_kind
        # patient readers (Cost Management) honour the *retry-after headers for longer; others keep the 3-attempt policy
        self.patient = patient
        self.statement_path = None
        self.context = ssl.create_default_context()
        if self.context.verify_mode != ssl.CERT_REQUIRED or not self.context.check_hostname:
            raise EvidenceError("unsafe_tls", "TLS peer and hostname validation are mandatory.", "tls")
        self.opener = build_opener(NoRedirect(), HTTPSHandler(context=self.context))
        self.allowed = set()

    def allow(self, url, method="GET"):
        parsed = urlsplit(url)
        if parsed.scheme != "https" or (parsed.scheme + "://" + parsed.netloc) != self.origin or parsed.fragment or parsed.username:
            raise EvidenceError("unsafe_endpoint", "Read URL changed the fixed HTTPS origin.", "scope")
        if method not in ("GET", "POST"):
            raise EvidenceError("unsafe_method", "Only enumerated GET reads and one Cost Management read-only POST are permitted.", "scope")
        if any(forbidden in parsed.path.lower() for forbidden in ("/secrets/get", "/secrets/put", "/secrets/delete", "/commands/", "/clusters/start", "/clusters/create", "/jobs/run-now", "/sql/statements")):
            raise EvidenceError("unsafe_endpoint", "Secret-value reads, compute starts, SQL statement execution and writes are forbidden.", "scope")
        self.allowed.add((method, parsed.path))
        return url

    def _bearer(self):
        return self.identity.arm_token() if self.token_kind == "arm" else self.identity.databricks_token()

    def request(self, method, url, source, body=None, allow_empty=False):
        parsed = urlsplit(url)
        if (
            parsed.scheme + "://" + parsed.netloc != self.origin or parsed.fragment or parsed.username or parsed.password
            or len(url) > 16384 or (method, parsed.path) not in self.allowed
        ):
            raise EvidenceError("unsafe_endpoint", "Request was not one of the scoped allowlisted reads.", source)
        if method == "POST" and not (
            parsed.path.lower().endswith("/providers/microsoft.costmanagement/query")
            or (self.statement_path is not None and parsed.path == self.statement_path)
        ):
            raise EvidenceError("unsafe_method", "This POST is not an enumerated read-only operation.", source)
        payload = None if body is None else json.dumps(body, allow_nan=False).encode("utf-8")
        attempts = 5 if self.patient else 3
        for attempt in range(attempts):
            bearer = self._bearer()
            self.identity._guard_budget()
            request = Request(url, data=payload, method=method, headers={
                "Authorization": "Bearer " + bearer,
                "Accept": "application/json",
                "Content-Type": "application/json",
            })
            try:
                with self.opener.open(request, timeout=60 if self.patient else 30) as response:
                    if response.status == 204 and allow_empty:
                        return {}
                    if response.status != 200:
                        raise EvidenceError("http_error", "Read returned HTTP " + str(response.status) + ".", source, response.status)
                    raw = response.read(HTTP_BYTES + 1)
                    if len(raw) > HTTP_BYTES:
                        raise EvidenceError("response_cap", "Source response exceeded the disclosed byte safety bound.", source)
            except HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt < attempts - 1:
                    headers = exc.headers.items() if exc.headers else []
                    waits = [int(v) for k, v in headers if k.lower().endswith("retry-after") and re.fullmatch(r"\s*[0-9]{1,4}\s*", str(v))]
                    if self.patient:
                        wait = min(COST_MAX_RETRY_WAIT, max(waits) + 1 if waits else 5 * (attempt + 1))
                        if self.identity.deadline - time.monotonic() > wait + COST_QUERY_RESERVE_SECONDS / 2:
                            time.sleep(wait)
                            continue
                    else:
                        time.sleep(min(max(waits), 5) if waits else attempt + 1)
                        continue
                raise EvidenceError(
                    "access_denied" if exc.code in (401, 403) else "throttled" if exc.code == 429 and self.patient else "http_error",
                    "Read returned HTTP " + str(exc.code) + "; response bodies are excluded.",
                    source, exc.code,
                ) from exc
            except (URLError, TimeoutError, ssl.SSLError, OSError) as exc:
                reason = getattr(exc, "reason", exc)
                code = "tls_failed" if isinstance(reason, ssl.SSLError) else "transport_failed"
                raise EvidenceError(code, "Read transport/TLS failed; no insecure retry or alternate identity.", source) from exc
            try:
                decoded = json.loads(raw)
                return decoded if isinstance(decoded, (dict, list)) else obj(decoded, source)
            except (ValueError, UnicodeDecodeError) as exc:
                raise EvidenceError("invalid_json", "Source returned invalid JSON; no raw body is exported.", source) from exc
        raise EvidenceError("http_error", "Bounded retries exhausted.", source)


class StatementReader(HttpReader):
    """The only SQL path, OFF by default: POST /api/2.0/sql/statements with the fixed read-only billing SELECT."""

    PATH = "/api/2.0/sql/statements"

    def __init__(self, identity, origin):
        super().__init__(identity, origin, "databricks")
        self.statement_path = self.PATH

    def allow(self, url, method="GET"):
        parsed = urlsplit(url)
        if (
            method != "POST" or parsed.scheme != "https" or parsed.scheme + "://" + parsed.netloc != self.origin
            or parsed.path != self.PATH or parsed.query or parsed.fragment or parsed.username
        ):
            raise EvidenceError("unsafe_endpoint", "Only the fixed system-table billing statement may be posted.", "dbx_system_billing")
        self.allowed.add((method, parsed.path))
        return url

    def request(self, method, url, source, body=None, allow_empty=False):
        if not isinstance(body, dict) or body.get("statement") != SYSTEM_BILLING_STATEMENT:
            raise EvidenceError("unsafe_statement", "Only the fixed read-only billing statement is allowed.", source)
        return super().request(method, url, source, body=body, allow_empty=allow_empty)


def next_arm_link(link, initial):
    if not isinstance(link, str) or not link or len(link) > 16384:
        raise EvidenceError("invalid_pagination", "Invalid ARM continuation.", "pagination")
    current, first = urlsplit(link), urlsplit(initial)
    if (
        current.scheme != "https" or current.netloc != first.netloc or current.path != first.path
        or current.fragment or current.username or current.password
        or unquote(current.path) != current.path or "\\" in current.path
    ):
        raise EvidenceError("invalid_pagination", "ARM continuation changed origin or exact resource scope.", "pagination")
    try:
        pairs = parse_qsl(current.query, keep_blank_values=True, strict_parsing=True)
        original = dict(parse_qsl(first.query, keep_blank_values=True, strict_parsing=True))
    except ValueError as exc:
        raise EvidenceError("invalid_pagination", "Malformed continuation query.", "pagination") from exc
    values = dict(pairs)
    paging = {"$skiptoken", "skiptoken", "$skipToken", "skipToken", "$skip", "$top"}
    if len(values) != len(pairs) or any(key not in original and key not in paging for key in values):
        raise EvidenceError("invalid_pagination", "ARM continuation added an unapproved query.", "pagination")
    if any(values.get(key) != value for key, value in original.items() if key not in paging):
        raise EvidenceError("invalid_pagination", "ARM continuation changed version or filter.", "pagination")
    aliases = [value for key, value in pairs if key.lower() in ("$skiptoken", "skiptoken")]
    if aliases and (not all(aliases) or len(set(aliases)) != 1):
        raise EvidenceError("invalid_pagination", "ARM continuation token aliases are empty or conflicting.", "pagination")
    return link


def read_arm_pages(reader, url, source_id, reference, normalize, value_key="value", top_level_list=False):
    receipt = source_receipt(
        source_id, reference, page_cap=MAX_PAGES, row_cap=MAX_ROWS,
        pagination_complete=False, read_signature="GET " + url,
    )
    rows, seen_ids, seen_pages = [], set(), set()
    current = url
    reader.allow(url, "GET")
    try:
        for page_number in range(MAX_PAGES):
            if current in seen_pages:
                raise EvidenceError("pagination_loop", "Source repeated a continuation.", source_id)
            seen_pages.add(current)
            payload = reader.request("GET", current, source_id)
            receipt["pages"] = page_number + 1
            if top_level_list and isinstance(payload, list):
                page = array(payload, source_id)
                continuation = None
            else:
                payload = obj(payload, source_id)
                page = array(payload.get(value_key, []), source_id)
                continuation = payload.get("nextLink")
            if len(rows) + len(page) > MAX_ROWS:
                raise EvidenceError("row_cap", "Source row safety cap reached; scope was not silently narrowed.", source_id)
            for raw in page:
                row = normalize(raw)
                identity = str(row.get("id") or row.get("resource_id") or "").lower()
                if not identity or identity in seen_ids:
                    raise EvidenceError("invalid_pagination", "Source row identity is absent or repeated.", source_id)
                seen_ids.add(identity)
                rows.append(row)
            receipt["records"] = len(rows)
            if not continuation:
                receipt["pagination_complete"] = True
                return rows, receipt
            current = next_arm_link(continuation, url)
        raise EvidenceError("page_cap", "Source page safety cap reached; collection remains explicitly partial.", source_id)
    except EvidenceError as exc:
        receipt["status"] = "partial" if rows else "denied" if exc.http_status in (401, 403) else "error"
        receipt["records"] = len(rows)
        receipt["errors"].append(exc.public())
        return rows, receipt


def read_dbx_pages(reader, base_url, source_id, reference, list_key, normalize, base_params=None, token_param="page_token"):
    params = dict(base_params or {})
    first_url = base_url + ("?" + urlencode(params) if params else "")
    receipt = source_receipt(
        source_id, reference, page_cap=MAX_PAGES, row_cap=MAX_ROWS,
        pagination_complete=False, read_signature="GET " + first_url,
    )
    rows, seen_ids, seen_tokens = [], set(), set()
    reader.allow(first_url, "GET")
    current_token = None
    try:
        for page_number in range(MAX_PAGES):
            page_params = dict(params)
            if current_token is not None:
                page_params[token_param] = current_token
            current_url = base_url + ("?" + urlencode(page_params) if page_params else "")
            payload = obj(reader.request("GET", current_url, source_id), source_id)
            receipt["pages"] = page_number + 1
            raw_list = payload.get(list_key)
            page = [] if raw_list is None else array(raw_list, source_id)
            if len(rows) + len(page) > MAX_ROWS:
                raise EvidenceError("row_cap", "Databricks API row safety cap reached; scope was not silently narrowed.", source_id)
            for raw in page:
                row = normalize(raw)
                identity = str(row.get("id") or row.get("name") or "")
                if not identity or identity in seen_ids:
                    raise EvidenceError("invalid_pagination", "Databricks object identity is absent or repeated.", source_id)
                seen_ids.add(identity)
                rows.append(row)
            receipt["records"] = len(rows)
            next_token = payload.get("next_page_token")
            has_more = payload.get("has_more")
            if not next_token:
                if has_more is True:
                    raise EvidenceError("missing_continuation", "Databricks list reported has_more=true without next_page_token.", source_id)
                receipt["pagination_complete"] = True
                return rows, receipt
            next_token = text(next_token, source_id, 4096)
            if not next_token or next_token in seen_tokens:
                raise EvidenceError("pagination_loop", "Databricks pagination token is empty or repeated.", source_id)
            seen_tokens.add(next_token)
            current_token = next_token
        raise EvidenceError("page_cap", "Databricks page safety cap reached; collection remains explicitly partial.", source_id)
    except EvidenceError as exc:
        receipt["status"] = "partial" if rows else "denied" if exc.http_status in (401, 403) else "error"
        receipt["records"] = len(rows)
        receipt["errors"].append(exc.public())
        return rows, receipt


def read_one(reader, url, source_id, reference, normalize):
    receipt = source_receipt(source_id, reference, pages=1, read_signature="GET " + url)
    try:
        reader.allow(url)
        result = normalize(obj(reader.request("GET", url, source_id), source_id))
        receipt["records"] = 1
        return result, receipt
    except EvidenceError as exc:
        receipt.update(status="denied" if exc.http_status in (401, 403) else "error", records=0, errors=[exc.public()])
        return None, receipt


def param_val(params_obj, key, kind="str", source_id="arm_workspace"):
    entry = pick(params_obj, key)
    if entry is None:
        return None
    val = pick(entry, "value") if isinstance(entry, dict) else entry
    if kind == "bool":
        return boolean(val, source_id)
    return text(val, source_id, 2048)


def normalize_workspace(raw, source_id, reference, config):
    sub = config.get("subscription_id") or SUBSCRIPTION_ID
    resource_id = arm_id(raw.get("id"), sub)
    if resource_id.lower() != config["id"].lower():
        raise EvidenceError("scope_mismatch", "ARM returned a different Databricks workspace ID.", source_id)
    props = obj(raw.get("properties", {}), source_id)
    params = obj(props.get("parameters", {}), source_id)
    workspace_url = text(props.get("workspaceUrl"), source_id, 256)
    if workspace_url and config["workspace_host"] and workspace_url.lower() != config["workspace_host"].lower():
        raise EvidenceError("scope_mismatch", "ARM workspaceUrl differs from the configured workspace_host.", source_id)
    managed_rg_id = text(props.get("managedResourceGroupId"), source_id, 2048)
    managed_rg_name = None
    if managed_rg_id:
        arm_id_parts = managed_rg_id.split("/")
        if len(arm_id_parts) >= 5 and arm_id_parts[1].lower() == "subscriptions" and arm_id_parts[3].lower() == "resourcegroups":
            managed_rg_name = text(arm_id_parts[4], source_id, 90)
    access_connector = obj(props.get("accessConnector", {}), source_id) if props.get("accessConnector") else {}
    ac_id = arm_id(access_connector.get("id"), sub) if access_connector.get("id") else None
    ac_uami = arm_id(access_connector.get("userAssignedIdentityId"), sub) if access_connector.get("userAssignedIdentityId") else None
    custom_vnet_id = param_val(params, "customVirtualNetworkId", "str", source_id)
    if custom_vnet_id:
        custom_vnet_id = arm_id(custom_vnet_id, sub)
    enc_entities = obj(pick(props, "encryption", "entities") or {}, source_id)
    managed_services_cmk = obj(enc_entities.get("managedServices", {}), source_id) if enc_entities.get("managedServices") else {}
    managed_disk_cmk = obj(enc_entities.get("managedDisk", {}), source_id) if enc_entities.get("managedDisk") else {}
    esc = obj(props.get("enhancedSecurityCompliance", {}), source_id) if props.get("enhancedSecurityCompliance") else {}
    default_cat = obj(props.get("defaultCatalog", {}), source_id) if props.get("defaultCatalog") else {}
    pe_connections = []
    for pe in array(props.get("privateEndpointConnections", []), source_id):
        pe_props = obj(pe.get("properties", {}), source_id)
        pe_connections.append({
            "id": text(pe.get("id"), source_id, 2048),
            "name": text(pe.get("name"), source_id, 256),
            "private_endpoint_id": text(pick(pe_props, "privateEndpoint", "id"), source_id, 2048),
            "status": text(pick(pe_props, "privateLinkServiceConnectionState", "status"), source_id, 64),
            "group_ids": strings(pe_props.get("groupIds", []), source_id),
        })
    return {
        "id": resource_id,
        "resource_id": resource_id,
        "name": text(raw.get("name"), source_id, 64),
        "workspace_name": config["name"],
        "workspace_id": resource_id,
        "workspace_guid": text(props.get("workspaceId"), source_id, 128),
        "workspace_url": workspace_url or config["workspace_host"],
        "subscription_id": sub,
        "sre_tenant_id": config["sre_tenant_id"],
        "target_tenant_id": config["target_tenant_id"],
        "auth_mode": config["auth_mode"],
        "cross_tenant": config["cross_tenant"],
        "resource_group": config["resource_group"],
        "region": text(raw.get("location"), source_id, 64),
        "sku_name": text(pick(raw, "sku", "name"), source_id, 64),
        "sku_tier": text(pick(raw, "sku", "tier"), source_id, 64),
        "provisioning_state": text(props.get("provisioningState"), source_id, 64),
        "managed_resource_group_id": managed_rg_id,
        "managed_resource_group": managed_rg_name,
        "public_network_access": text(props.get("publicNetworkAccess"), source_id, 64),
        "required_nsg_rules": text(props.get("requiredNsgRules"), source_id, 64),
        "default_storage_firewall": text(props.get("defaultStorageFirewall"), source_id, 64),
        "default_catalog_type": text(default_cat.get("initialType"), source_id, 64),
        "default_catalog_name": text(default_cat.get("initialName"), source_id, 256),
        "enable_no_public_ip": param_val(params, "enableNoPublicIp", "bool", source_id),
        "custom_virtual_network_id": custom_vnet_id,
        "custom_public_subnet_name": param_val(params, "customPublicSubnetName", "str", source_id),
        "custom_private_subnet_name": param_val(params, "customPrivateSubnetName", "str", source_id),
        "nat_gateway_name": param_val(params, "natGatewayName", "str", source_id),
        "public_ip_name": param_val(params, "publicIpName", "str", source_id),
        "dbfs_storage_account_name": param_val(params, "storageAccountName", "str", source_id),
        "dbfs_storage_sku": param_val(params, "storageAccountSkuName", "str", source_id),
        "prepare_encryption": param_val(params, "prepareEncryption", "bool", source_id),
        "require_infrastructure_encryption": param_val(params, "requireInfrastructureEncryption", "bool", source_id),
        "aml_workspace_id": param_val(params, "amlWorkspaceId", "str", source_id),
        "access_connector": {
            "id": ac_id,
            "identity_type": text(access_connector.get("identityType"), source_id, 64),
            "user_assigned_identity_id": ac_uami,
        },
        "cmk": {
            "managed_services_key_source": text(managed_services_cmk.get("keySource"), source_id, 64),
            "managed_services_vault_uri": text(pick(managed_services_cmk, "keyVaultProperties", "keyVaultUri"), source_id, 512),
            "managed_disk_key_source": text(managed_disk_cmk.get("keySource"), source_id, 64),
            "managed_disk_vault_uri": text(pick(managed_disk_cmk, "keyVaultProperties", "keyVaultUri"), source_id, 512),
            "managed_disk_auto_rotation": boolean(managed_disk_cmk.get("rotationToLatestKeyVersionEnabled"), source_id),
        },
        "enhanced_security_compliance": {
            "automatic_cluster_update": text(pick(esc, "automaticClusterUpdate", "value"), source_id, 64),
            "enhanced_security_monitoring": text(pick(esc, "enhancedSecurityMonitoring", "value"), source_id, 64),
            "compliance_security_profile": text(pick(esc, "complianceSecurityProfile", "value"), source_id, 64),
            "compliance_standards": strings(pick(esc, "complianceSecurityProfile", "complianceStandards"), source_id),
        },
        "private_endpoint_connections": pe_connections,
        "tags": tags_map(raw.get("tags"), source_id),
        "source_id": source_id,
        "observed_at": reference,
    }


def normalize_outbound_endpoint(raw, source_id, reference, config):
    category = text(raw.get("category"), source_id, 128)
    if not category:
        raise EvidenceError("invalid_record", "Outbound dependency endpoint category is required.", source_id)
    endpoints = []
    for ep in array(raw.get("endpoints", []), source_id):
        domain = text(ep.get("domainName"), source_id, 512)
        ports = [
            {"port": number(d.get("port"), source_id), "region": text(d.get("region"), source_id, 64)}
            for d in array(ep.get("endpointDetails", []), source_id)
        ]
        endpoints.append({"domain_name": domain, "details": ports})
    return {
        "id": config["id"] + "/outboundEndpoints/" + re.sub(r"[^A-Za-z0-9_.-]+", "-", category),
        "resource_id": config["id"],
        "workspace_name": config["name"],
        "workspace_id": config["id"],
        "name": category,
        "category": category,
        "kind": "OutboundNetworkDependency",
        "endpoints": endpoints,
        "source_id": source_id,
        "observed_at": reference,
    }


def normalize_resource(raw, source_id, reference, config, association):
    sub = config.get("subscription_id") or SUBSCRIPTION_ID
    resource_id = arm_id(raw.get("id"), sub)
    kind = resource_type(resource_id)
    if kind not in RESOURCE_APIS:
        raise EvidenceError("unsupported_resource_type", "Resource detail type is not in the fixed whitelist.", source_id)
    props = obj(raw.get("properties", {}), source_id)
    row = {
        "id": resource_id,
        "resource_id": resource_id,
        "name": text(raw.get("name"), source_id, 256),
        "kind": kind,
        "resource_kind": kind,
        "region": text(raw.get("location"), source_id, 64),
        "sku_name": text(pick(raw, "sku", "name"), source_id, 64),
        "sku_tier": text(pick(raw, "sku", "tier"), source_id, 64),
        "provisioning_state": text(props.get("provisioningState"), source_id, 64),
        "association": association,
        "configuration": {},
        "workspace_name": config["name"],
        "workspace_id": config["id"],
        "source_id": source_id,
        "observed_at": reference,
    }
    if kind == "microsoft.databricks/accessconnectors":
        identity_block = obj(raw.get("identity", {}), source_id) if raw.get("identity") else {}
        row["identity_type"] = text(identity_block.get("type"), source_id, 64)
        row["principal_id"] = text(identity_block.get("principalId"), source_id, 64)
        row["user_assigned_identities"] = [
            arm_id(k, sub) for k in obj(identity_block.get("userAssignedIdentities") or {}, source_id)
        ]
    elif kind == "microsoft.storage/storageaccounts":
        for field in ("supportsHttpsTrafficOnly", "minimumTlsVersion", "allowBlobPublicAccess", "allowSharedKeyAccess", "publicNetworkAccess", "isHnsEnabled"):
            val = props.get(field)
            row["configuration"][field] = boolean(val, source_id) if isinstance(val, bool) or val is None else text(str(val), source_id, 64)
        row["dfs_endpoint"] = text(pick(props, "primaryEndpoints", "dfs"), source_id, 512)
        row["blob_endpoint"] = text(pick(props, "primaryEndpoints", "blob"), source_id, 512)
    elif kind == "microsoft.keyvault/vaults":
        for field in ("enableRbacAuthorization", "enablePurgeProtection", "enableSoftDelete", "softDeleteRetentionInDays", "publicNetworkAccess", "vaultUri"):
            val = props.get(field)
            if isinstance(val, bool) or val is None:
                row["configuration"][field] = val
            elif isinstance(val, (int, float)):
                row["configuration"][field] = number(val, source_id)
            else:
                row["configuration"][field] = text(str(val), source_id, 512)
        row["vault_uri"] = text(props.get("vaultUri"), source_id, 512)
    elif kind == "microsoft.network/virtualnetworks":
        row["address_space"] = strings(pick(props, "addressSpace", "addressPrefixes"), source_id)
        row["subnet_ids"] = [arm_id(s.get("id"), sub) for s in array(props.get("subnets", []), source_id) if s.get("id")]
    elif kind == "microsoft.network/virtualnetworks/subnets":
        row["address_prefix"] = text(props.get("addressPrefix"), source_id, 128)
        row["nsg_id"] = arm_id(pick(props, "networkSecurityGroup", "id"), sub) if pick(props, "networkSecurityGroup", "id") else None
        row["route_table_id"] = arm_id(pick(props, "routeTable", "id"), sub) if pick(props, "routeTable", "id") else None
        row["nat_gateway_id"] = arm_id(pick(props, "natGateway", "id"), sub) if pick(props, "natGateway", "id") else None
        row["delegations"] = [text(pick(d, "properties", "serviceName") or d.get("name"), source_id, 256) for d in array(props.get("delegations", []), source_id)]
    elif kind == "microsoft.network/routetables":
        row["disable_bgp_route_propagation"] = boolean(props.get("disableBgpRoutePropagation"), source_id)
        row["routes"] = [
            {
                "name": text(r.get("name"), source_id, 256),
                "address_prefix": text(pick(r, "properties", "addressPrefix"), source_id, 128),
                "next_hop_type": text(pick(r, "properties", "nextHopType"), source_id, 64),
                "next_hop_ip_address": text(pick(r, "properties", "nextHopIpAddress"), source_id, 128),
            }
            for r in array(props.get("routes", []), source_id)
        ]
    elif kind == "microsoft.network/networksecuritygroups":
        row["security_rules"] = [
            {
                key: number(pick(item, "properties", key), source_id) if key == "priority"
                else strings(pick(item, "properties", key), source_id) if key.endswith(("Prefixes", "Ranges"))
                else text(pick(item, "properties", key), source_id, 256)
                for key in ("priority", "direction", "access", "protocol", "sourceAddressPrefix", "sourceAddressPrefixes", "destinationPortRange", "destinationPortRanges", "destinationAddressPrefix")
            }
            for item in array(props.get("securityRules", []), source_id)
        ]
    elif kind == "microsoft.network/natgateways":
        row["public_ip_ids"] = [arm_id(ip.get("id"), sub) for ip in array(props.get("publicIpAddresses", []), source_id) if ip.get("id")]
    elif kind == "microsoft.network/publicipaddresses":
        row["configuration"]["ipAddress"] = text(props.get("ipAddress"), source_id, 128)
        row["configuration"]["publicIPAllocationMethod"] = text(props.get("publicIPAllocationMethod"), source_id, 64)
    elif kind == "microsoft.network/privateendpoints":
        row["subnet_id"] = arm_id(pick(props, "subnet", "id"), sub) if pick(props, "subnet", "id") else None
        connections = array(props.get("privateLinkServiceConnections", []) or props.get("manualPrivateLinkServiceConnections", []), source_id)
        row["connections"] = [
            {
                "target_id": text(pick(c, "properties", "privateLinkServiceId"), source_id, 2048),
                "group_ids": strings(pick(c, "properties", "groupIds"), source_id),
                "status": text(pick(c, "properties", "privateLinkServiceConnectionState", "status"), source_id, 64),
            }
            for c in connections
        ]
    elif kind == "microsoft.managedidentity/userassignedidentities":
        row["principal_id"] = text(props.get("principalId"), source_id, 64)
        row["client_id"] = text(props.get("clientId"), source_id, 64)
    return row


def referenced_resource_ids(row, subscription=None):
    refs = []
    for field in ("subnet_ids", "public_ip_ids", "user_assigned_identities"):
        refs.extend((val, field) for val in row.get(field, []) if val)
    for field in ("nsg_id", "route_table_id", "nat_gateway_id", "subnet_id"):
        if row.get(field):
            refs.append((row[field], field))
    if row.get("resource_kind") == "microsoft.network/virtualnetworks/subnets":
        refs.append((re.split(r"/subnets/", row["id"], flags=re.IGNORECASE)[0], "parent_virtual_network_id"))
    for val, field in refs:
        val = arm_id(val, subscription or SUBSCRIPTION_ID)
        if resource_type(val) in RESOURCE_APIS:
            yield val, field


def normalize_cluster(raw, source_id, reference, config):
    cid = text(raw.get("cluster_id"), source_id, 128)
    name = text(raw.get("cluster_name"), source_id, 256) or cid
    if not cid:
        raise EvidenceError("invalid_record", "Databricks cluster requires cluster_id.", source_id)
    autoscale = obj(raw.get("autoscale", {}), source_id) if raw.get("autoscale") else None
    return {
        "id": cid,
        "cluster_id": cid,
        "name": name,
        "workload_name": name,
        "kind": "JobCluster" if raw.get("cluster_source") == "JOB" else "AllPurposeCluster",
        "cluster_source": text(raw.get("cluster_source"), source_id, 64),
        "state": text(raw.get("state"), source_id, 64),
        "spark_version": text(raw.get("spark_version"), source_id, 128),
        "node_type_id": text(raw.get("node_type_id"), source_id, 128),
        "driver_node_type_id": text(raw.get("driver_node_type_id"), source_id, 128),
        "num_workers": number(raw.get("num_workers"), source_id),
        "autoscale": {
            "min_workers": number(autoscale.get("min_workers"), source_id),
            "max_workers": number(autoscale.get("max_workers"), source_id),
        } if autoscale else None,
        "autotermination_minutes": number(raw.get("autotermination_minutes"), source_id),
        "data_security_mode": text(raw.get("data_security_mode"), source_id, 64),
        "single_user_name": text(raw.get("single_user_name"), source_id, 256),
        "policy_id": text(raw.get("policy_id"), source_id, 128),
        "instance_pool_id": text(raw.get("instance_pool_id"), source_id, 128),
        "driver_instance_pool_id": text(raw.get("driver_instance_pool_id"), source_id, 128),
        "runtime_engine": text(raw.get("runtime_engine"), source_id, 64),
        "custom_tags": tags_map(raw.get("custom_tags"), source_id),
        "creator_user_name": text(raw.get("creator_user_name"), source_id, 256),
        "azure_availability": text(pick(raw, "azure_attributes", "availability"), source_id, 64),
        "first_on_demand": number(pick(raw, "azure_attributes", "first_on_demand"), source_id),
        "start_time": number(raw.get("start_time"), source_id),
        "last_restarted_time": number(raw.get("last_restarted_time"), source_id),
        "terminated_time": number(raw.get("terminated_time"), source_id),
        "resource_id": config["id"],
        "workspace_name": config["name"],
        "workspace_id": config["id"],
        "source_id": source_id,
        "observed_at": reference,
    }


def normalize_pool(raw, source_id, reference, config):
    pid = text(raw.get("instance_pool_id"), source_id, 128)
    name = text(raw.get("instance_pool_name"), source_id, 256) or pid
    if not pid:
        raise EvidenceError("invalid_record", "Instance pool requires instance_pool_id.", source_id)
    return {
        "id": pid,
        "instance_pool_id": pid,
        "name": name,
        "workload_name": name,
        "kind": "InstancePool",
        "node_type_id": text(raw.get("node_type_id"), source_id, 128),
        "min_idle_instances": number(raw.get("min_idle_instances"), source_id),
        "max_capacity": number(raw.get("max_capacity"), source_id),
        "idle_instance_autotermination_minutes": number(raw.get("idle_instance_autotermination_minutes"), source_id),
        "azure_availability": text(pick(raw, "azure_attributes", "availability"), source_id, 64),
        "custom_tags": tags_map(raw.get("custom_tags"), source_id),
        "state": text(raw.get("state"), source_id, 64),
        "stats": {
            key: number(pick(raw, "stats", key), source_id)
            for key in ("used_count", "idle_count", "pending_used_count", "pending_idle_count")
        },
        "resource_id": config["id"],
        "workspace_name": config["name"],
        "workspace_id": config["id"],
        "source_id": source_id,
        "observed_at": reference,
    }


def normalize_policy(raw, source_id, reference, config):
    pol_id = text(raw.get("policy_id"), source_id, 128)
    name = text(raw.get("name"), source_id, 256) or pol_id
    if not pol_id:
        raise EvidenceError("invalid_record", "Cluster policy requires policy_id.", source_id)
    enforced_tags, autotermination = None, None
    definition = raw.get("definition")
    if isinstance(definition, str) and len(definition) <= 200000:
        try:
            rules = json.loads(definition)
        except ValueError:
            rules = None
        if isinstance(rules, dict):
            # only tag names and the auto-termination bound are kept; values such as Spark settings are never exported
            enforced_tags = sorted({k[len("custom_tags."):][:128] for k in rules if isinstance(k, str) and k.startswith("custom_tags.")})
            rule = rules.get("autotermination_minutes")
            if isinstance(rule, dict):
                autotermination = {
                    key: rule.get(key) for key in ("type", "value", "maxValue", "defaultValue")
                    if isinstance(rule.get(key), (int, float, str)) and not isinstance(rule.get(key), bool) and len(str(rule.get(key))) <= 32
                }
    return {
        "id": pol_id,
        "policy_id": pol_id,
        "name": name,
        "workload_name": name,
        "kind": "ClusterPolicy",
        "policy_family_id": text(raw.get("policy_family_id"), source_id, 128),
        "is_default": boolean(raw.get("is_default"), source_id),
        "enforced_tag_keys": enforced_tags,
        "autotermination_rule": autotermination,
        "resource_id": config["id"],
        "workspace_name": config["name"],
        "workspace_id": config["id"],
        "source_id": source_id,
        "observed_at": reference,
    }


def normalize_job(raw, source_id, reference, config, from_detail=False):
    raw_job_id = raw.get("job_id")
    if raw_job_id is None or isinstance(raw_job_id, bool):
        raise EvidenceError("invalid_record", "Databricks job requires job_id.", source_id)
    jid = str(raw_job_id)
    settings = obj(raw.get("settings", {}), source_id)
    name = text(settings.get("name"), source_id, 512) or ("job-" + jid)
    run_as = obj(settings.get("run_as") or raw.get("run_as") or {}, source_id)
    job_clusters = []
    for jc in array(settings.get("job_clusters", []), source_id):
        key = text(jc.get("job_cluster_key"), source_id, 128)
        new_cluster = obj(jc.get("new_cluster", {}), source_id)
        if key:
            autoscale = new_cluster.get("autoscale") if isinstance(new_cluster.get("autoscale"), dict) else {}
            job_clusters.append({
                "job_cluster_key": key,
                "spark_version": text(new_cluster.get("spark_version"), source_id, 128),
                "node_type_id": text(new_cluster.get("node_type_id"), source_id, 128),
                "driver_node_type_id": text(new_cluster.get("driver_node_type_id"), source_id, 128),
                "policy_id": text(new_cluster.get("policy_id"), source_id, 128),
                "instance_pool_id": text(new_cluster.get("instance_pool_id"), source_id, 128),
                "data_security_mode": text(new_cluster.get("data_security_mode"), source_id, 64),
                "num_workers": number(new_cluster.get("num_workers"), source_id),
                "autoscale_max_workers": number(autoscale.get("max_workers"), source_id),
                "azure_availability": text(pick(new_cluster, "azure_attributes", "availability"), source_id, 64),
                "runtime_engine": text(new_cluster.get("runtime_engine"), source_id, 64),
                "custom_tags": tags_map(new_cluster.get("custom_tags"), source_id),
            })
    tasks = []
    for t in array(settings.get("tasks", []), source_id):
        tkey = text(t.get("task_key"), source_id, 256)
        if not tkey:
            raise EvidenceError("invalid_record", "Job task requires task_key.", source_id)
        deps = [text(d.get("task_key"), source_id, 256) for d in array(t.get("depends_on", []), source_id) if d.get("task_key")]
        run_job_target = pick(t, "run_job_task", "job_id")
        tasks.append({
            "task_key": tkey,
            "depends_on": deps,
            "existing_cluster_id": text(t.get("existing_cluster_id"), source_id, 128),
            "job_cluster_key": text(t.get("job_cluster_key"), source_id, 128),
            "environment_key": text(t.get("environment_key"), source_id, 128),
            "pipeline_id": text(pick(t, "pipeline_task", "pipeline_id"), source_id, 128),
            "warehouse_id": text(pick(t, "sql_task", "warehouse_id"), source_id, 128),
            "run_job_id": str(run_job_target) if run_job_target is not None and not isinstance(run_job_target, bool) else None,
            "notebook_path": text(pick(t, "notebook_task", "notebook_path"), source_id, 1024),
            "timeout_seconds": number(t.get("timeout_seconds"), source_id),
            "max_retries": number(t.get("max_retries"), source_id),
        })
    notifs = obj(settings.get("email_notifications", {}), source_id)
    webhooks = obj(settings.get("webhook_notifications", {}), source_id)
    has_notifications = bool(
        notifs.get("on_failure") or notifs.get("on_duration_warning_threshold_exceeded")
        or webhooks.get("on_failure") or settings.get("notification_settings")
    )
    schedule = settings.get("schedule") or settings.get("trigger") or settings.get("continuous")
    pause_status = pick(schedule, "pause_status") if isinstance(schedule, dict) else None
    has_more_flag = boolean(raw.get("has_more"), source_id) is True
    next_token_present = bool(text(raw.get("next_page_token"), source_id, 4096))
    tasks_incomplete = has_more_flag or next_token_present or len(tasks) >= 100 or len(job_clusters) >= 100
    return {
        "id": jid,
        "job_id": jid,
        "name": name,
        "workload_name": name,
        "kind": "Job",
        "scheduled": bool(schedule),
        "schedule_paused": pause_status == "PAUSED",
        "continuous": bool(settings.get("continuous")),
        "creator_user_name": text(raw.get("creator_user_name"), source_id, 256),
        "timeout_seconds": number(settings.get("timeout_seconds"), source_id),
        "max_concurrent_runs": number(settings.get("max_concurrent_runs"), source_id),
        "has_notifications": has_notifications,
        "run_as_service_principal": text(run_as.get("service_principal_name"), source_id, 256),
        "run_as_user_name": text(run_as.get("user_name"), source_id, 256),
        "job_clusters": job_clusters,
        "tasks": tasks,
        "tasks_incomplete": tasks_incomplete,
        "tags": tags_map(settings.get("tags"), source_id),
        "resource_id": config["id"],
        "workspace_name": config["name"],
        "workspace_id": config["id"],
        "source_id": source_id,
        "observed_at": reference,
    }


def normalize_pipeline(raw, source_id, reference, config, detail=None, detail_source_id=None):
    pid = text(raw.get("pipeline_id") or (detail.get("pipeline_id") if isinstance(detail, dict) else None), source_id, 128)
    spec_source = detail_source_id or source_id
    spec = obj(
        (detail.get("spec") if isinstance(detail, dict) and detail.get("spec") is not None else raw.get("spec")) or {},
        spec_source,
    )
    name = text((detail.get("name") if isinstance(detail, dict) else None) or spec.get("name") or raw.get("name"), source_id, 256) or pid
    if not pid:
        raise EvidenceError("invalid_record", "Pipeline requires pipeline_id.", source_id)
    has_spec = bool(spec) or any(raw.get(k) is not None for k in ("catalog", "schema", "target", "storage", "serverless", "continuous"))
    catalog_val = text(spec.get("catalog") if "catalog" in spec else raw.get("catalog"), spec_source, 256)
    schema_raw = (
        spec.get("schema")
        if "schema" in spec
        else spec.get("target")
        if "target" in spec
        else raw.get("schema")
        if "schema" in raw
        else raw.get("target")
    )
    target_val = text(schema_raw, spec_source, 256)
    storage_val = text(spec.get("storage") if "storage" in spec else raw.get("storage"), spec_source, 1024)
    serverless_val = boolean(spec.get("serverless") if "serverless" in spec else raw.get("serverless"), spec_source)
    continuous_val = boolean(spec.get("continuous") if "continuous" in spec else raw.get("continuous"), spec_source)
    clusters_spec = []
    for cl in array(spec.get("clusters", []), spec_source):
        clusters_spec.append({
            "label": text(cl.get("label"), spec_source, 128),
            "policy_id": text(cl.get("policy_id"), spec_source, 128),
            "instance_pool_id": text(cl.get("instance_pool_id"), spec_source, 128),
            "driver_instance_pool_id": text(cl.get("driver_instance_pool_id"), spec_source, 128),
            "node_type_id": text(cl.get("node_type_id"), spec_source, 128),
        })
    return {
        "id": pid,
        "pipeline_id": pid,
        "name": name,
        "workload_name": name,
        "kind": "LakeflowPipeline",
        "state": text((detail.get("state") if isinstance(detail, dict) and detail.get("state") else None) or raw.get("state"), source_id, 64),
        "catalog": catalog_val,
        "schema": target_val,
        "target": target_val,
        "storage": storage_val,
        "serverless": serverless_val,
        "continuous": continuous_val,
        "clusters": clusters_spec,
        "detail_collected": has_spec,
        "detail_source_id": spec_source if has_spec else None,
        "resource_id": config["id"],
        "workspace_name": config["name"],
        "workspace_id": config["id"],
        "source_id": source_id,
        "observed_at": reference,
    }


def normalize_warehouse(raw, source_id, reference, config):
    wid = text(raw.get("id"), source_id, 128)
    name = text(raw.get("name"), source_id, 256) or wid
    if not wid:
        raise EvidenceError("invalid_record", "SQL warehouse requires id.", source_id)
    return {
        "id": wid,
        "warehouse_id": wid,
        "name": name,
        "workload_name": name,
        "kind": "SqlWarehouse",
        "state": text(raw.get("state"), source_id, 64),
        "cluster_size": text(raw.get("cluster_size"), source_id, 64),
        "warehouse_type": text(raw.get("warehouse_type"), source_id, 64),
        "enable_serverless_compute": boolean(raw.get("enable_serverless_compute"), source_id),
        "auto_stop_mins": number(raw.get("auto_stop_mins"), source_id),
        "min_num_clusters": number(raw.get("min_num_clusters"), source_id),
        "max_num_clusters": number(raw.get("max_num_clusters"), source_id),
        "enable_photon": boolean(raw.get("enable_photon"), source_id),
        "spot_instance_policy": text(raw.get("spot_instance_policy"), source_id, 64),
        "num_clusters": number(raw.get("num_clusters"), source_id),
        "num_active_sessions": number(raw.get("num_active_sessions"), source_id),
        "creator_name": text(raw.get("creator_name"), source_id, 256),
        "custom_tags": tags_map({
            str(item.get("key")): item.get("value")
            for item in (pick(raw, "tags", "custom_tags") or []) if isinstance(item, dict) and item.get("key")
        } if isinstance(pick(raw, "tags", "custom_tags"), list) else None, source_id),
        "resource_id": config["id"],
        "workspace_name": config["name"],
        "workspace_id": config["id"],
        "source_id": source_id,
        "observed_at": reference,
    }


def normalize_secret_scope(raw, source_id, reference, config):
    name = text(raw.get("name"), source_id, 256)
    if not name:
        raise EvidenceError("invalid_record", "Secret scope requires name.", source_id)
    kv = obj(raw.get("keyvault_metadata", {}), source_id) if raw.get("keyvault_metadata") else {}
    kv_resource_id = text(kv.get("resource_id"), source_id, 2048)
    if kv_resource_id and kv_resource_id.lower().startswith("/subscriptions/" + SUBSCRIPTION_ID.lower() + "/"):
        kv_resource_id = arm_id(kv_resource_id, SUBSCRIPTION_ID)
    return {
        "id": "scope:" + name,
        "name": name,
        "workload_name": name,
        "kind": "SecretScope",
        "backend_type": text(raw.get("backend_type"), source_id, 64),
        "keyvault_resource_id": kv_resource_id,
        "keyvault_dns_name": text(kv.get("dns_name"), source_id, 512),
        "resource_id": config["id"],
        "workspace_name": config["name"],
        "workspace_id": config["id"],
        "source_id": source_id,
        "observed_at": reference,
    }


def normalize_init_script(raw, source_id, reference, config):
    sid = text(raw.get("script_id"), source_id, 128)
    name = text(raw.get("name"), source_id, 256) or sid
    if not sid:
        raise EvidenceError("invalid_record", "Global init script requires script_id.", source_id)
    return {
        "id": sid,
        "script_id": sid,
        "name": name,
        "workload_name": name,
        "kind": "GlobalInitScript",
        "enabled": boolean(raw.get("enabled"), source_id),
        "position": number(raw.get("position"), source_id),
        "resource_id": config["id"],
        "workspace_name": config["name"],
        "workspace_id": config["id"],
        "source_id": source_id,
        "observed_at": reference,
    }


def normalize_metastore(raw, source_id, reference, config):
    mid = text(raw.get("metastore_id"), source_id, 128)
    name = text(raw.get("name"), source_id, 256) or mid
    if not mid:
        raise EvidenceError("invalid_record", "Unity Catalog metastore requires metastore_id.", source_id)
    return {
        "id": mid,
        "metastore_id": mid,
        "name": name,
        "workload_name": name,
        "kind": "UnityCatalogMetastore",
        "region": text(raw.get("region"), source_id, 64),
        "storage_root": text(raw.get("storage_root"), source_id, 1024),
        "storage_root_credential_id": text(raw.get("storage_root_credential_id"), source_id, 256),
        "storage_root_credential_name": text(raw.get("storage_root_credential_name"), source_id, 256),
        "privilege_model_version": text(raw.get("privilege_model_version"), source_id, 64),
        "global_metastore_id": text(raw.get("global_metastore_id"), source_id, 256),
        "resource_id": config["id"],
        "workspace_name": config["name"],
        "workspace_id": config["id"],
        "source_id": source_id,
        "observed_at": reference,
    }


def normalize_catalog(raw, source_id, reference, config):
    name = text(raw.get("name"), source_id, 256)
    if not name:
        raise EvidenceError("invalid_record", "Unity Catalog catalog requires name.", source_id)
    return {
        "id": "catalog:" + name,
        "name": name,
        "workload_name": name,
        "kind": "UnityCatalog",
        "catalog_type": text(raw.get("catalog_type"), source_id, 64),
        "storage_root": text(raw.get("storage_root"), source_id, 1024),
        "storage_location": text(raw.get("storage_location"), source_id, 1024),
        "isolation_mode": text(raw.get("isolation_mode"), source_id, 64),
        "connection_name": text(raw.get("connection_name"), source_id, 256),
        "metastore_id": text(raw.get("metastore_id"), source_id, 128),
        "resource_id": config["id"],
        "workspace_name": config["name"],
        "workspace_id": config["id"],
        "source_id": source_id,
        "observed_at": reference,
    }


def normalize_schema(raw, source_id, reference, config):
    full_name = text(raw.get("full_name"), source_id, 512)
    name = text(raw.get("name"), source_id, 256)
    catalog_name = text(raw.get("catalog_name"), source_id, 256)
    if not full_name or not name or not catalog_name:
        raise EvidenceError("invalid_record", "Unity Catalog schema requires full_name, catalog_name and name.", source_id)
    return {
        "id": "schema:" + full_name,
        "full_name": full_name,
        "name": name,
        "workload_name": full_name,
        "catalog_name": catalog_name,
        "kind": "UnitySchema",
        "storage_root": text(raw.get("storage_root"), source_id, 1024),
        "storage_location": text(raw.get("storage_location"), source_id, 1024),
        "metastore_id": text(raw.get("metastore_id"), source_id, 128),
        "resource_id": config["id"],
        "workspace_name": config["name"],
        "workspace_id": config["id"],
        "source_id": source_id,
        "observed_at": reference,
    }


def normalize_storage_credential(raw, source_id, reference, config):
    name = text(raw.get("name"), source_id, 256)
    if not name:
        raise EvidenceError("invalid_record", "Storage credential requires name.", source_id)
    mi = obj(raw.get("azure_managed_identity", {}), source_id) if raw.get("azure_managed_identity") else {}
    sp = obj(raw.get("azure_service_principal", {}), source_id) if raw.get("azure_service_principal") else {}
    ac_id = text(mi.get("access_connector_id"), source_id, 2048)
    mi_id = text(mi.get("managed_identity_id"), source_id, 2048)
    return {
        "id": "storage_credential:" + name,
        "credential_id": text(raw.get("id"), source_id, 128),
        "name": name,
        "workload_name": name,
        "kind": "StorageCredential",
        "read_only": boolean(raw.get("read_only"), source_id),
        "isolation_mode": text(raw.get("isolation_mode"), source_id, 64),
        "uses_managed_identity": bool(ac_id),
        "uses_service_principal": bool(sp.get("application_id") or sp.get("directory_id")),
        "access_connector_id": ac_id,
        "managed_identity_id": mi_id,
        "service_principal_application_id": text(sp.get("application_id"), source_id, 128),
        "resource_id": config["id"],
        "workspace_name": config["name"],
        "workspace_id": config["id"],
        "source_id": source_id,
        "observed_at": reference,
    }


def normalize_external_location(raw, source_id, reference, config):
    name = text(raw.get("name"), source_id, 256)
    if not name:
        raise EvidenceError("invalid_record", "External location requires name.", source_id)
    url = text(raw.get("url"), source_id, 2048)
    return {
        "id": "external_location:" + name,
        "name": name,
        "workload_name": name,
        "kind": "ExternalLocation",
        "url": url,
        "credential_name": text(raw.get("credential_name"), source_id, 256),
        "credential_id": text(raw.get("credential_id"), source_id, 128),
        "read_only": boolean(raw.get("read_only"), source_id),
        "isolation_mode": text(raw.get("isolation_mode"), source_id, 64),
        "metastore_id": text(raw.get("metastore_id"), source_id, 128),
        "resource_id": config["id"],
        "workspace_name": config["name"],
        "workspace_id": config["id"],
        "source_id": source_id,
        "observed_at": reference,
    }


def normalize_connection(raw, source_id, reference, config):
    name = text(raw.get("name"), source_id, 256)
    if not name:
        raise EvidenceError("invalid_record", "Unity Catalog connection requires name.", source_id)
    return {
        "id": "connection:" + name,
        "connection_id": text(raw.get("connection_id"), source_id, 128),
        "name": name,
        "workload_name": name,
        "kind": "LakehouseFederationConnection",
        "connection_type": text(raw.get("connection_type"), source_id, 64),
        "credential_type": text(raw.get("credential_type"), source_id, 64),
        "host": text(pick(raw, "options", "host") or raw.get("url"), source_id, 512),
        "read_only": boolean(raw.get("read_only"), source_id),
        "resource_id": config["id"],
        "workspace_name": config["name"],
        "workspace_id": config["id"],
        "source_id": source_id,
        "observed_at": reference,
    }


def extract_storage_account_from_uri(uri_str):
    if not isinstance(uri_str, str):
        return None
    match = re.match(r"^(?:abfss?|wasbs?)://(?:[^@/?#]+@)?([a-z0-9]{3,24})\.(?:dfs|blob)\.core\.windows\.net(?:/|$)", uri_str.strip(), re.IGNORECASE)
    return match.group(1).lower() if match else None


def extract_vault_host(uri_str):
    if not isinstance(uri_str, str):
        return None
    try:
        parsed = urlsplit(uri_str.strip())
    except ValueError:
        return None
    if parsed.scheme == "https" and parsed.hostname and parsed.hostname.lower().endswith(".vault.azure.net"):
        return parsed.hostname.lower()
    return None


def read_runtime_catalog(reader, reference, inventory):
    """Supported runtime keys and metadata of the node types in use: end-of-support runtimes and deprecated VM families."""
    used = {c.get(k) for c in inventory.get("clusters", []) for k in ("node_type_id", "driver_node_type_id")}
    used |= {p.get("node_type_id") for p in inventory.get("instance_pools", [])}
    used |= {jc.get(k) for j in inventory.get("jobs", []) for jc in j.get("job_clusters", []) for k in ("node_type_id", "driver_node_type_id")}
    used.discard(None)

    def versions(item):
        rows = item.get("versions") if isinstance(item.get("versions"), list) else []
        return sorted({v["key"] for v in rows if isinstance(v, dict) and isinstance(v.get("key"), str) and len(v["key"]) <= 128})

    def node_types(item):
        rows = item.get("node_types") if isinstance(item.get("node_types"), list) else []
        out = {}
        for row in rows:
            node = row.get("node_type_id") if isinstance(row, dict) else None
            if node in used:
                cores = row.get("num_cores")
                out[node] = {
                    "is_deprecated": row.get("is_deprecated") is True,
                    "num_cores": cores if isinstance(cores, (int, float)) and not isinstance(cores, bool) and math.isfinite(cores) else None,
                    "photon_worker_capable": row.get("photon_worker_capable") is True,
                }
        return out

    spark, spark_receipt = read_one(reader, reader.origin + "/api/2.0/clusters/spark-versions", "dbx_spark_versions", reference, versions)
    nodes, node_receipt = read_one(reader, reader.origin + "/api/2.0/clusters/list-node-types", "dbx_node_types", reference, node_types)
    spark_receipt["records"] = len(spark or [])
    node_receipt["records"] = len(nodes or {})
    return {"spark_versions": spark, "node_types": nodes}, [spark_receipt, node_receipt]


def collect_live(config, reference, deadline=None):
    identity = Identity(config)
    try:
        if deadline is not None:
            identity.deadline = min(identity.deadline, deadline)
        arm = HttpReader(identity, ARM_ORIGIN, "arm")
        raw = {
            "sources": [],
            "inventory": {
                "clusters": [],
                "instance_pools": [],
                "cluster_policies": [],
                "jobs": [],
                "pipelines": [],
                "sql_warehouses": [],
                "secret_scopes": [],
                "global_init_scripts": [],
                "uc_metastore": None,
                "uc_catalogs": [],
                "uc_schemas": [],
                "uc_storage_credentials": [],
                "uc_external_locations": [],
                "uc_connections": [],
                "outbound_endpoints": [],
                "related_resources": [],
            },
            "requirements": config["requirements"],
            "workspace_conf": None,
            "arm_diagnostics": [],
            "advisor": [],
            "cost_rows": [],
        }
        ws_url = ARM_ORIGIN + config["id"] + "?api-version=" + DATABRICKS_ARM_API
        workspace, receipt = read_one(arm, ws_url, "arm_workspace", reference, lambda item: normalize_workspace(item, "arm_workspace", reference, config))
        raw["sources"].append(receipt)
        workspace_arm_error = None
        if workspace is None:
            workspace_arm_error = receipt["errors"][0]
            if not config["workspace_api_enabled"]:
                raise EvidenceError(workspace_arm_error["code"], "The approved primary Databricks workspace could not be read; no synthetic/empty live report.", "arm_workspace", workspace_arm_error["http_status"])
            receipt["note"] = "Primary ARM workspace GET returned non-complete status; ARM control-plane checks remain Not evaluated while Plane 2 Workspace/Unity Catalog REST is evaluated."
            workspace = {
                "id": config["id"],
                "resource_id": config["id"],
                "name": config["name"],
                "workspace_name": config["name"],
                "workspace_id": config["id"],
                "workspace_guid": None,
                "workspace_url": config["workspace_host"],
                "subscription_id": SUBSCRIPTION_ID,
                "sre_tenant_id": config["sre_tenant_id"],
                "target_tenant_id": config["target_tenant_id"],
                "auth_mode": config["auth_mode"],
                "cross_tenant": config["cross_tenant"],
                "resource_group": config["resource_group"],
                "region": None,
                "sku_name": None,
                "sku_tier": None,
                "provisioning_state": None,
                "managed_resource_group_id": None,
                "managed_resource_group": None,
                "public_network_access": None,
                "required_nsg_rules": None,
                "default_storage_firewall": None,
                "default_catalog_type": None,
                "default_catalog_name": None,
                "enable_no_public_ip": None,
                "custom_virtual_network_id": None,
                "custom_public_subnet_name": None,
                "custom_private_subnet_name": None,
                "nat_gateway_name": None,
                "public_ip_name": None,
                "dbfs_storage_account_name": None,
                "dbfs_storage_sku": None,
                "prepare_encryption": None,
                "require_infrastructure_encryption": None,
                "aml_workspace_id": None,
                "access_connector": {"id": None, "identity_type": None, "user_assigned_identity_id": None},
                "cmk": {
                    "managed_services_key_source": None,
                    "managed_services_vault_uri": None,
                    "managed_disk_key_source": None,
                    "managed_disk_vault_uri": None,
                    "managed_disk_auto_rotation": None,
                },
                "enhanced_security_compliance": {
                    "automatic_cluster_update": None,
                    "enhanced_security_monitoring": None,
                    "compliance_security_profile": None,
                    "compliance_standards": None,
                },
                "private_endpoint_connections": [],
                "tags": {},
                "source_id": "arm_workspace",
                "observed_at": reference,
            }
        raw["workspace"] = workspace

        outbound, out_receipt = read_arm_pages(
            arm,
            ARM_ORIGIN + config["id"] + "/outboundNetworkDependenciesEndpoints?api-version=" + DATABRICKS_ARM_API,
            "arm_outbound_endpoints",
            reference,
            lambda item: normalize_outbound_endpoint(item, "arm_outbound_endpoints", reference, config),
            top_level_list=True,
        )
        raw["inventory"]["outbound_endpoints"] = outbound
        raw["sources"].append(out_receipt)

        def normalize_diag(item):
            diag_id = text(item.get("id"), "arm_diagnostics", 2048)
            props = obj(item.get("properties", {}), "arm_diagnostics")
            return {
                "id": diag_id,
                "name": text(item.get("name"), "arm_diagnostics", 256),
                "workspace_id": text(props.get("workspaceId"), "arm_diagnostics", 2048),
                "storage_account_id": text(props.get("storageAccountId"), "arm_diagnostics", 2048),
                "event_hub_authorization_rule_id": text(props.get("eventHubAuthorizationRuleId"), "arm_diagnostics", 2048),
                "logs": [
                    {"category": text(l.get("category") or l.get("categoryGroup"), "arm_diagnostics", 128), "enabled": boolean(l.get("enabled"), "arm_diagnostics")}
                    for l in array(props.get("logs", []), "arm_diagnostics")
                ],
            }

        diags, diag_receipt = read_arm_pages(
            arm,
            ARM_ORIGIN + config["id"] + "/providers/Microsoft.Insights/diagnosticSettings?api-version=2021-05-01-preview",
            "arm_diagnostics",
            reference,
            normalize_diag,
        )
        raw["arm_diagnostics"] = diags
        raw["sources"].append(diag_receipt)

        related, queued, seen_related = [], [], set()
        related_attempt = 0
        related_cap_omitted = []

        def queue_related(rid, assoc):
            if not rid or not isinstance(rid, str) or not rid.lower().startswith("/subscriptions/" + SUBSCRIPTION_ID.lower() + "/"):
                return
            rid_clean = arm_id(rid, SUBSCRIPTION_ID)
            if resource_type(rid_clean) not in RESOURCE_APIS or rid_clean.lower() in seen_related:
                return
            if len(seen_related) >= MAX_RELATED_RESOURCES:
                if all(item["resource_id"].lower() != rid_clean.lower() for item in related_cap_omitted):
                    related_cap_omitted.append({"resource_id": rid_clean, "association": assoc})
                return
            seen_related.add(rid_clean.lower())
            queued.append((rid_clean, assoc))

        for rid in config["approved_related_resource_ids"]:
            queue_related(rid, {"type": "approved_configuration", "source_id": "configuration", "field": "approved_related_resource_ids"})
        if workspace["custom_virtual_network_id"]:
            queue_related(workspace["custom_virtual_network_id"], {"type": "direct_reference", "source_id": "arm_workspace", "resource_id": workspace["id"], "field": "parameters.customVirtualNetworkId"})
            for sub_field in ("custom_public_subnet_name", "custom_private_subnet_name"):
                if workspace.get(sub_field):
                    queue_related(
                        workspace["custom_virtual_network_id"] + "/subnets/" + workspace[sub_field],
                        {"type": "direct_reference", "source_id": "arm_workspace", "resource_id": workspace["id"], "field": "parameters." + sub_field},
                    )
        if pick(workspace, "access_connector", "id"):
            queue_related(workspace["access_connector"]["id"], {"type": "direct_reference", "source_id": "arm_workspace", "resource_id": workspace["id"], "field": "accessConnector.id"})
        if pick(workspace, "access_connector", "user_assigned_identity_id"):
            queue_related(workspace["access_connector"]["user_assigned_identity_id"], {"type": "direct_reference", "source_id": "arm_workspace", "resource_id": workspace["id"], "field": "accessConnector.userAssignedIdentityId"})
        for pe in workspace.get("private_endpoint_connections", []):
            if pe.get("private_endpoint_id"):
                queue_related(pe["private_endpoint_id"], {"type": "direct_reference", "source_id": "arm_workspace", "resource_id": workspace["id"], "field": "privateEndpointConnections"})

        if config["include_managed_resource_group"] and workspace.get("managed_resource_group"):
            mrg_url = ARM_ORIGIN + "/subscriptions/" + SUBSCRIPTION_ID + "/resourceGroups/" + workspace["managed_resource_group"] + "/resources?api-version=2021-04-01"
            def mrg_item(item):
                rid = arm_id(item.get("id"), SUBSCRIPTION_ID)
                return {"id": rid, "resource_id": rid, "type": text(item.get("type"), "arm_managed_rg_inventory", 256)}
            mrg_rows, mrg_receipt = read_arm_pages(arm, mrg_url, "arm_managed_rg_inventory", reference, mrg_item)
            raw["sources"].append(mrg_receipt)
            for item in mrg_rows:
                queue_related(item["id"], {"type": "managed_resource_group", "source_id": "arm_managed_rg_inventory", "resource_id": workspace["id"], "field": "managedResourceGroupId"})
        else:
            raw["sources"].append(source_receipt("arm_managed_rg_inventory", reference, "not_configured", "Managed resource group inventory disabled or absent."))

        def read_queued_related():
            nonlocal related_attempt
            while queued:
                rid, assoc = queued.pop(0)
                related_attempt += 1
                rtype = resource_type(rid)
                api_ver = RESOURCE_APIS[rtype]
                sid = "arm_resource_" + str(related_attempt) + "_" + hashlib.sha256(rid.lower().encode("utf-8")).hexdigest()[:8]
                row, r_receipt = read_one(
                    arm, ARM_ORIGIN + rid + "?api-version=" + api_ver, sid, reference,
                    lambda item, s=sid, a=assoc: normalize_resource(item, s, reference, config, a),
                )
                r_receipt["resource_id"] = rid
                raw["sources"].append(r_receipt)
                if row is not None:
                    related.append(row)
                    for child_id, field in referenced_resource_ids(row):
                        queue_related(child_id, {"type": "direct_reference", "source_id": sid, "resource_id": rid, "field": field})

        read_queued_related()

        if config["workspace_api_enabled"]:
            dbx = HttpReader(identity, "https://" + config["workspace_host"], "databricks")
            conf_url = dbx.origin + "/api/2.0/workspace-conf?" + urlencode({"keys": ",".join(WORKSPACE_CONF_KEYS)})
            def norm_conf(item):
                return {k: text(str(item.get(k)), "dbx_workspace_conf", 256) if item.get(k) is not None else None for k in WORKSPACE_CONF_KEYS}
            conf_obj, conf_receipt = read_one(dbx, conf_url, "dbx_workspace_conf", reference, norm_conf)
            raw["workspace_conf"] = conf_obj
            raw["sources"].append(conf_receipt)

            clusters, cl_receipt = read_dbx_pages(
                dbx, dbx.origin + "/api/2.0/clusters/list", "dbx_clusters", reference, "clusters",
                lambda item: normalize_cluster(item, "dbx_clusters", reference, config),
            )
            raw["inventory"]["clusters"] = clusters
            raw["sources"].append(cl_receipt)

            pools, pool_receipt = read_dbx_pages(
                dbx, dbx.origin + "/api/2.0/instance-pools/list", "dbx_instance_pools", reference, "instance_pools",
                lambda item: normalize_pool(item, "dbx_instance_pools", reference, config),
            )
            raw["inventory"]["instance_pools"] = pools
            raw["sources"].append(pool_receipt)

            policies, pol_receipt = read_dbx_pages(
                dbx, dbx.origin + "/api/2.0/policies/clusters/list", "dbx_cluster_policies", reference, "policies",
                lambda item: normalize_policy(item, "dbx_cluster_policies", reference, config),
            )
            raw["inventory"]["cluster_policies"] = policies
            raw["sources"].append(pol_receipt)

            jobs, job_receipt = read_dbx_pages(
                dbx, dbx.origin + "/api/2.1/jobs/list", "dbx_jobs", reference, "jobs",
                lambda item: normalize_job(item, "dbx_jobs", reference, config),
                base_params={"expand_tasks": "true", "limit": "25"},
            )
            job_detail_count = 0
            for idx, job_row in enumerate(jobs):
                if not job_row.get("tasks_incomplete"):
                    continue
                if job_detail_count >= MAX_DETAIL_GETS:
                    raw["sources"].append(source_receipt(
                        "dbx_job_details_cap", reference, "partial",
                        "Job detail GET bound reached; remaining truncated jobs keep tasks_incomplete=True.",
                        records=job_detail_count,
                    ))
                    break
                job_detail_count += 1
                jsid = "dbx_job_detail_" + str(job_detail_count) + "_" + hashlib.sha256(job_row["id"].encode("utf-8")).hexdigest()[:8]
                jurl = dbx.origin + "/api/2.1/jobs/get?" + urlencode({"job_id": job_row["id"]})
                full_job, j_rec = read_one(
                    dbx, jurl, jsid, reference,
                    lambda item, s=jsid: normalize_job(item, s, reference, config, from_detail=True),
                )
                raw["sources"].append(j_rec)
                if full_job is not None:
                    jobs[idx] = full_job
            raw["inventory"]["jobs"] = jobs
            raw["sources"].append(job_receipt)

            pipelines, pipe_receipt = read_dbx_pages(
                dbx, dbx.origin + "/api/2.0/pipelines", "dbx_pipelines", reference, "statuses",
                lambda item: normalize_pipeline(item, "dbx_pipelines", reference, config),
                base_params={"max_results": "50"},
            )
            pipe_detail_count = 0
            for idx, pipe_row in enumerate(pipelines):
                if pipe_row.get("detail_collected"):
                    continue
                if not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", pipe_row["id"]):
                    raise EvidenceError("invalid_record", "Pipeline ID has unsafe syntax for detail path.", "dbx_pipelines")
                if pipe_detail_count >= MAX_DETAIL_GETS:
                    raw["sources"].append(source_receipt(
                        "dbx_pipeline_details_cap", reference, "partial",
                        "Pipeline detail GET bound reached; remaining pipelines keep detail_collected=False.",
                        records=pipe_detail_count,
                    ))
                    break
                pipe_detail_count += 1
                psid = "dbx_pipeline_detail_" + str(pipe_detail_count) + "_" + hashlib.sha256(pipe_row["id"].encode("utf-8")).hexdigest()[:8]
                purl = dbx.origin + "/api/2.0/pipelines/" + quote(pipe_row["id"], safe="")
                full_pipe, p_rec = read_one(
                    dbx, purl, psid, reference,
                    lambda item, p=pipe_row, s=psid: normalize_pipeline(p, p["source_id"], reference, config, detail=item, detail_source_id=s),
                )
                raw["sources"].append(p_rec)
                if full_pipe is not None:
                    pipelines[idx] = full_pipe
            raw["inventory"]["pipelines"] = pipelines
            raw["sources"].append(pipe_receipt)

            warehouses, wh_receipt = read_dbx_pages(
                dbx, dbx.origin + "/api/2.0/sql/warehouses", "dbx_sql_warehouses", reference, "warehouses",
                lambda item: normalize_warehouse(item, "dbx_sql_warehouses", reference, config),
            )
            raw["inventory"]["sql_warehouses"] = warehouses
            raw["sources"].append(wh_receipt)

            raw["dbx_runtime_catalog"], runtime_receipts = read_runtime_catalog(dbx, reference, raw["inventory"])
            raw["sources"].extend(runtime_receipts)

            scopes, scope_receipt = read_dbx_pages(
                dbx, dbx.origin + "/api/2.0/secrets/scopes/list", "dbx_secret_scopes", reference, "scopes",
                lambda item: normalize_secret_scope(item, "dbx_secret_scopes", reference, config),
            )
            raw["inventory"]["secret_scopes"] = scopes
            raw["sources"].append(scope_receipt)
            for sc in scopes:
                if sc.get("keyvault_resource_id"):
                    queue_related(sc["keyvault_resource_id"], {"type": "direct_reference", "source_id": "dbx_secret_scopes", "resource_id": workspace["id"], "field": "keyvault_metadata.resource_id"})

            scripts, script_receipt = read_dbx_pages(
                dbx, dbx.origin + "/api/2.0/global-init-scripts", "dbx_init_scripts", reference, "scripts",
                lambda item: normalize_init_script(item, "dbx_init_scripts", reference, config),
            )
            raw["inventory"]["global_init_scripts"] = scripts
            raw["sources"].append(script_receipt)
        else:
            for sid in ("dbx_workspace_conf", "dbx_clusters", "dbx_instance_pools", "dbx_cluster_policies", "dbx_jobs", "dbx_pipelines", "dbx_sql_warehouses", "dbx_spark_versions", "dbx_node_types", "dbx_secret_scopes", "dbx_init_scripts"):
                raw["sources"].append(source_receipt(sid, reference, "not_configured", "Workspace REST API collection is disabled in configuration; no empty-workload inference."))

        if config["unity_catalog_enabled"] and config["workspace_api_enabled"]:
            dbx_uc = HttpReader(identity, "https://" + config["workspace_host"], "databricks")
            metastore, ms_receipt = read_one(
                dbx_uc, dbx_uc.origin + "/api/2.1/unity-catalog/metastore_summary", "uc_metastore_summary", reference,
                lambda item: normalize_metastore(item, "uc_metastore_summary", reference, config),
            )
            raw["inventory"]["uc_metastore"] = metastore
            raw["sources"].append(ms_receipt)

            catalogs, cat_receipt = read_dbx_pages(
                dbx_uc, dbx_uc.origin + "/api/2.1/unity-catalog/catalogs", "uc_catalogs", reference, "catalogs",
                lambda item: normalize_catalog(item, "uc_catalogs", reference, config),
                base_params={"include_browse": "true"},
            )
            raw["inventory"]["uc_catalogs"] = catalogs
            raw["sources"].append(cat_receipt)

            all_schemas = []
            schema_receipt = source_receipt("uc_schemas", reference, status="complete" if cat_receipt["status"] == "complete" else cat_receipt["status"], note="Unity Catalog schemas per non-system catalog.")
            if cat_receipt["status"] == "complete":
                for cat in catalogs:
                    if cat["name"].lower() in SYSTEM_CATALOGS:
                        continue
                    rows, s_rec = read_dbx_pages(
                        dbx_uc, dbx_uc.origin + "/api/2.1/unity-catalog/schemas", "uc_schemas", reference, "schemas",
                        lambda item: normalize_schema(item, "uc_schemas", reference, config),
                        base_params={"catalog_name": cat["name"], "include_browse": "true"},
                    )
                    all_schemas.extend(rows)
                    schema_receipt["pages"] += s_rec["pages"]
                    schema_receipt["records"] = len(all_schemas)
                    if s_rec["status"] != "complete":
                        schema_receipt["status"] = "partial" if all_schemas else s_rec["status"]
                        schema_receipt["errors"].extend(s_rec["errors"])
            raw["inventory"]["uc_schemas"] = all_schemas
            raw["sources"].append(schema_receipt)

            creds, cred_receipt = read_dbx_pages(
                dbx_uc, dbx_uc.origin + "/api/2.1/unity-catalog/storage-credentials", "uc_storage_credentials", reference, "storage_credentials",
                lambda item: normalize_storage_credential(item, "uc_storage_credentials", reference, config),
            )
            raw["inventory"]["uc_storage_credentials"] = creds
            raw["sources"].append(cred_receipt)
            for cr in creds:
                if cr.get("access_connector_id"):
                    queue_related(cr["access_connector_id"], {"type": "direct_reference", "source_id": "uc_storage_credentials", "resource_id": workspace["id"], "field": "azure_managed_identity.access_connector_id"})
                if cr.get("managed_identity_id"):
                    queue_related(cr["managed_identity_id"], {"type": "direct_reference", "source_id": "uc_storage_credentials", "resource_id": workspace["id"], "field": "azure_managed_identity.managed_identity_id"})

            ext_locs, ext_receipt = read_dbx_pages(
                dbx_uc, dbx_uc.origin + "/api/2.1/unity-catalog/external-locations", "uc_external_locations", reference, "external_locations",
                lambda item: normalize_external_location(item, "uc_external_locations", reference, config),
                base_params={"include_browse": "true"},
            )
            raw["inventory"]["uc_external_locations"] = ext_locs
            raw["sources"].append(ext_receipt)

            conns, conn_receipt = read_dbx_pages(
                dbx_uc, dbx_uc.origin + "/api/2.1/unity-catalog/connections", "uc_connections", reference, "connections",
                lambda item: normalize_connection(item, "uc_connections", reference, config),
            )
            raw["inventory"]["uc_connections"] = conns
            raw["sources"].append(conn_receipt)
        else:
            for sid in ("uc_metastore_summary", "uc_catalogs", "uc_schemas", "uc_storage_credentials", "uc_external_locations", "uc_connections"):
                raw["sources"].append(source_receipt(sid, reference, "not_configured", "Unity Catalog REST collection is disabled in configuration; no governance state is inferred."))

        raw["sources"].append(source_receipt(
            "uc_system_lineage",
            reference,
            "not_configured",
            "Runtime table/column lineage (system.access.table_lineage, system.access.column_lineage) requires SQL Warehouse query execution and is never queried by this control-plane collector; DBU billing detail (system.billing.usage) is the separate opt-in source dbx_system_billing.",
        ))

        read_queued_related()
        if related_cap_omitted:
            raw["sources"].append(source_receipt(
                "arm_related_cap",
                reference,
                "partial",
                "Related ARM resource queue reached MAX_RELATED_RESOURCES=" + str(MAX_RELATED_RESOURCES) + "; additional referenced resources were omitted and remain UNKNOWN.",
                records=len(seen_related),
                omitted_count=len(related_cap_omitted),
                omitted_resource_ids=[item["resource_id"] for item in related_cap_omitted[:50]],
                errors=[{
                    "code": "related_resource_cap_reached",
                    "message": "MAX_RELATED_RESOURCES cap reached; omitted resources are not assumed healthy.",
                    "source_id": "arm_related_cap",
                    "http_status": None,
                }],
            ))
        raw["inventory"]["related_resources"] = related

        advisor_source = source_receipt("arm_advisor", reference, "not_configured", "Cached recommendations only; no generateRecommendations action.")
        if config["advisor_enabled"]:
            adv_url = ARM_ORIGIN + "/subscriptions/" + SUBSCRIPTION_ID + "/providers/Microsoft.Advisor/recommendations?" + urlencode({
                "api-version": "2025-01-01", "$filter": "ResourceId eq '" + config["id"] + "'", "$top": "100",
            })
            def advisor_row(item):
                advisory_id = text(item.get("id"), "arm_advisor", 2048)
                if not advisory_id or not advisory_id.lower().startswith("/subscriptions/" + SUBSCRIPTION_ID.lower() + "/"):
                    raise EvidenceError("scope_mismatch", "Advisor ID changed subscription scope.", "arm_advisor")
                target = pick(item, "properties", "resourceMetadata", "resourceId")
                if not isinstance(target, str) or target.lower() != config["id"].lower():
                    raise EvidenceError("scope_mismatch", "Advisor returned a resource outside the exact workspace filter.", "arm_advisor")
                return {
                    "id": advisory_id,
                    "resource_id": config["id"],
                    "name": text(item.get("name"), "arm_advisor", 256),
                    "target_resource_id": target,
                    "category": text(pick(item, "properties", "category"), "arm_advisor", 64),
                    "impact": text(pick(item, "properties", "impact"), "arm_advisor", 64),
                    "last_updated": text(pick(item, "properties", "lastUpdated"), "arm_advisor", 64),
                    "problem": text(pick(item, "properties", "shortDescription", "problem"), "arm_advisor", 1024),
                    "solution": text(pick(item, "properties", "shortDescription", "solution"), "arm_advisor", 1024),
                    "workspace_name": config["name"],
                    "workspace_id": config["id"],
                    "source_id": "arm_advisor",
                    "observed_at": reference,
                }
            raw["advisor"], advisor_source = read_arm_pages(arm, adv_url, "arm_advisor", reference, advisor_row)
        raw["sources"].append(advisor_source)

        raw["cost_rows"], cost_source = collect_cost(arm, config, reference, related, workspace)
        raw["sources"].append(cost_source)
        raw["dbx_cost_data"], dbx_cost_source = collect_databricks_costs(identity, config, reference, workspace, raw["inventory"])
        raw["sources"].append(dbx_cost_source)
        raw["system_billing"], billing_source = collect_system_billing(identity, config, reference, workspace)
        raw["sources"].append(billing_source)
        if workspace_arm_error is not None:
            plane2_ok = any(
                s["id"].startswith(("dbx_", "uc_")) and s["id"] != "uc_system_lineage" and s["status"] == "complete"
                for s in raw["sources"]
            )
            if not plane2_ok:
                raise EvidenceError(workspace_arm_error["code"], "The approved primary Databricks workspace could not be read; no synthetic/empty live report.", "arm_workspace", workspace_arm_error["http_status"])
        return raw
    finally:
        identity.close()


def collect_cost(reader, config, reference, related, workspace=None):
    ids = config["approved_cost_resource_ids"]
    declared = datetime.fromisoformat(reference.replace("Z", "+00:00"))
    monthly = config["cost_timeframe"] == "month_to_date"
    start_time = declared.replace(day=1, hour=0, minute=0, second=0, microsecond=0) if monthly else declared - timedelta(days=30)
    start = start_time.isoformat().replace("+00:00", "Z")
    mode = config["cost_scope"]
    receipt = source_receipt(
        "azure_cost", reference, "not_configured",
        "No approved billing scope; no job/cluster DBU billing inference without system.billing.usage.",
        window={"start": start, "end": reference},
        timeframe="MonthToDate" if monthly else "Custom",
        granularity="None" if monthly else "Daily",
        cost_type="ActualCost",
        unit="billing_currency",
        pagination_complete=False,
    )
    if mode == "disabled":
        return [], receipt
    scope = "/subscriptions/" + SUBSCRIPTION_ID
    managed_rg = pick(workspace, "managed_resource_group")
    if mode == "managed_resource_group":
        if not isinstance(managed_rg, str) or not re.fullmatch(r"[A-Za-z0-9_.()-]{1,90}", managed_rg):
            receipt.update(status="error", errors=[EvidenceError("unverified_cost_scope", "Billing managedResourceGroup must come from the exact observed ARM workspace.", "azure_cost").public()])
            return [], receipt
        scope += "/resourceGroups/" + managed_rg
        receipt["association"] = {"type": "managed_resource_group_billing_context", "source_id": "arm_workspace", "managed_resource_group": managed_rg}
    else:
        observed_ids = {row["resource_id"].lower() for row in related} | {config["id"].lower()}
        if not ids or any(value.lower() not in observed_ids for value in ids):
            receipt.update(status="error", errors=[EvidenceError("unverified_cost_scope", "Fixed cost IDs must also be observed in the collected fixed inventory.", "azure_cost").public()])
            return [], receipt
        receipt["association"] = {"type": "approved_observed_resource_ids", "source_id": "configuration"}
    url = ARM_ORIGIN + scope + "/providers/Microsoft.CostManagement/query?api-version=2023-11-01"
    receipt.update(scope=scope, read_signature="POST " + url)
    reader.allow(url, "POST")
    body = {
        "type": "ActualCost",
        "timeframe": "MonthToDate" if monthly else "Custom",
        "dataset": {
            "granularity": "None" if monthly else "Daily",
            "aggregation": {"totalCost": {"name": "PreTaxCost", "function": "Sum"}},
            "grouping": [{"type": "Dimension", "name": "ResourceId"}],
        },
    }
    if not monthly:
        body["timePeriod"] = {"from": start, "to": reference}
    if mode == "resource_ids":
        body["dataset"]["filter"] = {"dimensions": {"name": "ResourceId", "operator": "In", "values": ids}}
    rows, seen = [], set()
    current = url
    try:
        for page_number in range(MAX_PAGES):
            if current in seen:
                raise EvidenceError("pagination_loop", "Cost query repeated a continuation.", "azure_cost")
            seen.add(current)
            payload = reader.request("POST", current, "azure_cost", body=body, allow_empty=True)
            receipt["pages"] = page_number + 1
            if not payload:
                receipt.update(status="complete", pagination_complete=True, records=len(rows), empty_http_204=True)
                return rows, receipt
            props = obj(payload.get("properties"), "azure_cost")
            columns = array(props.get("columns"), "azure_cost")
            names = [text(item.get("name"), "azure_cost", 128) for item in columns]
            required = {"ResourceId", "Currency"} | (set() if monthly else {"UsageDate"})
            if len(names) != len(set(names)) or not required <= set(names) or not ("PreTaxCost" in names or "Cost" in names):
                raise EvidenceError("invalid_cost_shape", "Required cost columns are absent or repeated.", "azure_cost")
            values = props.get("rows")
            if not isinstance(values, list) or len(rows) + len(values) > MAX_ROWS:
                raise EvidenceError("row_cap", "Cost rows are invalid or exceeded the safety bound.", "azure_cost")
            for value in values:
                if not isinstance(value, list) or len(value) != len(names):
                    raise EvidenceError("invalid_cost_shape", "Cost row/column lengths differ.", "azure_cost")
                record = dict(zip(names, value))
                resource_id = arm_id(record["ResourceId"], SUBSCRIPTION_ID)
                currency = text(record["Currency"], "azure_cost", 8)
                if not currency or not re.fullmatch(r"[A-Z]{3}", currency):
                    raise EvidenceError("invalid_currency", "Cost currency is not an observed ISO currency code.", "azure_cost")
                date = str(record["UsageDate"]) if record.get("UsageDate") is not None else None
                amount = number(record.get("PreTaxCost", record.get("Cost")), "azure_cost")
                if amount is None:
                    raise EvidenceError("invalid_cost_amount", "Cost amount is absent; it is not zero.", "azure_cost")
                rows.append({
                    "resource_id": resource_id, "usage_date": date, "amount": amount,
                    "currency": currency, "source_id": "azure_cost", "observed_at": reference,
                    "workspace_name": config["name"], "workspace_id": config["id"],
                    "window": receipt["window"], "association": receipt["association"],
                    "basis": "ActualCost/PreTaxCost in exact approved ARM scope; not per-job or per-cluster DBU attribution.",
                })
            receipt["records"] = len(rows)
            link = props.get("nextLink")
            if not link:
                receipt.update(status="complete", pagination_complete=True)
                return rows, receipt
            current = next_arm_link(link, url)
        raise EvidenceError("page_cap", "Cost query page safety cap reached.", "azure_cost")
    except (EvidenceError, ValueError) as exc:
        error = exc if isinstance(exc, EvidenceError) else EvidenceError("invalid_cost_date", "Cost date is not valid.", "azure_cost")
        receipt.update(status="partial" if rows else "denied" if error.http_status in (401, 403) else "error", records=len(rows), errors=[error.public()])
        return rows, receipt


def dependencies_for(raw, reference, provenance):
    ws, inv = raw["workspace"], raw["inventory"]
    scope = {
        "workspace_id": ws["id"],
        "workspace_name": ws["workspace_name"],
        "provenance": provenance,
        "observed_at": reference,
    }
    nodes, edges, unknowns, broken_refs, unverified_refs = {}, {}, [], [], []
    arm_map, cluster_map, pool_map, policy_map, job_map, pipe_map, wh_map = {}, {}, {}, {}, {}, {}, {}
    cred_map, cat_map, schema_map, storage_by_name, kv_by_host = {}, {}, {}, {}, {}
    source_status_by_id = {s["id"]: s["status"] for s in raw["sources"]}

    def add_unknown(code, layer, kind, message, source_ids, resource_id=None, workload_name=""):
        uid = "unknown-" + hashlib.sha256((ws["id"].lower() + "|" + code + "|" + str(resource_id or "") + "|" + workload_name).encode("utf-8")).hexdigest()[:24]
        unknowns.append({
            **scope, "id": uid, "record_type": "unknown", "classification": "UNKNOWN",
            "layer": layer, "kind": kind, "code": code, "message": message,
            "source_ids": source_ids, "resource_id": resource_id or ws["id"],
            "workload_name": workload_name, "status": "not_evaluated",
        })

    def record_unresolved_ref(source_object, kind, target_id, target_source_id, layer, intra_object=False):
        if intra_object:
            broken_refs.append({
                "source_object": source_object,
                "kind": kind,
                "target_id": target_id,
                "target_source_id": target_source_id,
                "qualification": "confirmed_intra_object_missing",
            })
            return
        t_status = source_status_by_id.get(target_source_id, "not_configured")
        if t_status != "complete":
            add_unknown(
                "unresolved_target_source_incomplete_" + kind,
                layer,
                kind,
                source_object + " references " + str(target_id) + ", but target source " + target_source_id + " is " + t_status + "; reference remains UNKNOWN.",
                [target_source_id],
                workload_name=source_object,
            )
            unverified_refs.append({
                "source_object": source_object,
                "kind": kind,
                "target_id": target_id,
                "target_source_id": target_source_id,
                "qualification": "target_source_" + t_status,
            })
            return
        add_unknown(
            "unresolved_cross_object_reference_" + kind,
            layer,
            kind,
            source_object + " references " + str(target_id) + ", which was not returned in " + target_source_id + ". Because Databricks list APIs are permission-filtered by object ACLs, absence may reflect ACL visibility or a deleted object and remains UNKNOWN.",
            [target_source_id],
            workload_name=source_object,
        )
        unverified_refs.append({
            "source_object": source_object,
            "kind": kind,
            "target_id": target_id,
            "target_source_id": target_source_id,
            "qualification": "permission_filtered_absence_or_deleted_target",
        })

    def add_node(native_key, kind, layer, label, source_id, evidence, resource_id=None, classification="OBSERVED", workload_name=""):
        nid = "node-" + hashlib.sha256((ws["id"].lower() + "|" + kind + "|" + str(native_key)).encode("utf-8")).hexdigest()[:24]
        node = {
            **scope, "id": nid, "record_type": "node", "classification": classification,
            "layer": layer, "kind": kind, "label": label, "name": label,
            "workload_name": workload_name or label, "resource_id": resource_id or ws["id"],
            "source_id": source_id, "evidence": evidence,
        }
        nodes[nid] = node
        return nid

    def add_edge(start, end, relation, layer, classification, source_ids, join_fields, evidence, workload_name=""):
        if not start or not end:
            return
        eid = "edge-" + hashlib.sha256((start + "|" + relation + "|" + end + "|" + classification).encode("utf-8")).hexdigest()[:24]
        edges.setdefault(eid, {
            **scope, "id": eid, "record_type": "edge", "classification": classification,
            "layer": layer, "from": start, "to": end, "relation": relation,
            "source_ids": list(dict.fromkeys(source_ids)), "join_fields": join_fields,
            "evidence": evidence, "workload_name": workload_name,
        })

    root = add_node(ws["id"].lower(), "databricks_workspace", "control_plane", ws["name"], "arm_workspace", {
        "arm_id": ws["id"], "workspace_url": ws["workspace_url"], "sku": ws["sku_name"],
        "auth_mode": ws["auth_mode"], "cross_tenant": ws["cross_tenant"],
        "enable_no_public_ip": ws["enable_no_public_ip"], "public_network_access": ws["public_network_access"],
    }, ws["id"])
    arm_map[ws["id"].lower()] = root

    if ws.get("managed_resource_group_id"):
        mrg_node = add_node(
            ws["managed_resource_group_id"].lower(), "managed_resource_group", "control_plane",
            ws.get("managed_resource_group") or ws["managed_resource_group_id"], "arm_workspace",
            {"managed_resource_group_id": ws["managed_resource_group_id"]}, ws["managed_resource_group_id"],
        )
        add_edge(root, mrg_node, "manages_resource_group", "control_plane", "OBSERVED", ["arm_workspace"], ["properties.managedResourceGroupId"], {"managed_resource_group_id": ws["managed_resource_group_id"]})

    for out_ep in inv.get("outbound_endpoints", []):
        ep_node = add_node(
            out_ep["id"], "outbound_dependency_category", "control_plane", out_ep["category"],
            out_ep["source_id"], {"category": out_ep["category"], "endpoints": out_ep["endpoints"]}, ws["id"],
        )
        add_edge(root, ep_node, "requires_outbound_control_plane_dependency", "control_plane", "OBSERVED", ["arm_workspace", out_ep["source_id"]], ["outboundNetworkDependenciesEndpoints.category"], {"category": out_ep["category"]})

    for res in inv.get("related_resources", []):
        r_node = add_node(
            res["id"].lower(), res["resource_kind"], "associated_resource", res["name"] or res["id"],
            res["source_id"], {"arm_id": res["id"], "association": res["association"], "configuration": res.get("configuration", {})},
            res["id"],
        )
        arm_map[res["id"].lower()] = r_node
        if res["resource_kind"] == "microsoft.storage/storageaccounts" and res.get("name"):
            storage_by_name[res["name"].lower()] = r_node
        if res["resource_kind"] == "microsoft.keyvault/vaults" and res.get("vault_uri"):
            host = extract_vault_host(res["vault_uri"])
            if host:
                kv_by_host[host] = r_node

    if ws.get("custom_virtual_network_id"):
        vnet_key = arm_map.get(ws["custom_virtual_network_id"].lower())
        if vnet_key:
            add_edge(root, vnet_key, "injected_into_vnet", "associated_resource", "OBSERVED", ["arm_workspace"], ["parameters.customVirtualNetworkId"], {"vnet_id": ws["custom_virtual_network_id"]})
        for sub_field, rel in (("custom_public_subnet_name", "uses_host_public_subnet"), ("custom_private_subnet_name", "uses_container_private_subnet")):
            if ws.get(sub_field):
                sub_id = (ws["custom_virtual_network_id"] + "/subnets/" + ws[sub_field]).lower()
                if sub_id in arm_map:
                    add_edge(root, arm_map[sub_id], rel, "associated_resource", "OBSERVED", ["arm_workspace"], ["parameters." + sub_field], {"subnet_id": sub_id})

    ac_id = pick(ws, "access_connector", "id")
    if ac_id and ac_id.lower() in arm_map:
        add_edge(root, arm_map[ac_id.lower()], "uses_access_connector", "associated_resource", "OBSERVED", ["arm_workspace"], ["properties.accessConnector.id"], {"access_connector_id": ac_id})

    if ws.get("dbfs_storage_account_name"):
        dbfs_name = ws["dbfs_storage_account_name"].lower()
        if dbfs_name in storage_by_name:
            add_edge(root, storage_by_name[dbfs_name], "uses_dbfs_root_storage", "associated_resource", "OBSERVED", ["arm_workspace"], ["parameters.storageAccountName"], {"storage_account": ws["dbfs_storage_account_name"]})
        else:
            inferred_dbfs = add_node(
                "dbfs_storage:" + dbfs_name, "external_storage_target", "associated_resource",
                ws["dbfs_storage_account_name"], "arm_workspace",
                {"storage_account_name": ws["dbfs_storage_account_name"], "arm_detail_collected": False},
                ws["id"], classification="INFERRED",
            )
            add_edge(root, inferred_dbfs, "inferred_dbfs_root_storage_name", "associated_resource", "INFERRED", ["arm_workspace"], ["parameters.storageAccountName"], {"storage_account_name": ws["dbfs_storage_account_name"]})

    for cmk_field in ("managed_services_vault_uri", "managed_disk_vault_uri"):
        v_uri = pick(ws, "cmk", cmk_field)
        host = extract_vault_host(v_uri) if v_uri else None
        if host:
            if host in kv_by_host:
                add_edge(root, kv_by_host[host], "uses_cmk_key_vault", "associated_resource", "OBSERVED", ["arm_workspace"], ["encryption." + cmk_field], {"vault_uri": v_uri})
            else:
                inf_kv = add_node("cmk_vault:" + host, "external_key_vault_target", "associated_resource", host, "arm_workspace", {"vault_uri": v_uri, "arm_detail_collected": False}, ws["id"], classification="INFERRED")
                add_edge(root, inf_kv, "inferred_cmk_key_vault_uri", "associated_resource", "INFERRED", ["arm_workspace"], ["encryption." + cmk_field], {"vault_uri": v_uri})

    for res in inv.get("related_resources", []):
        r_key = arm_map[res["id"].lower()]
        for child_id, field in referenced_resource_ids(res, res["id"].split("/")[2]):
            relation_name = "associated_route_table" if field == "route_table_id" else "associated_nsg" if field == "nsg_id" else "references_arm_resource"
            if child_id.lower() in arm_map:
                add_edge(r_key, arm_map[child_id.lower()], relation_name, "associated_resource", "OBSERVED", [res["source_id"]], [field], {"target_id": child_id})
            else:
                inf_arm = add_node("arm_ref:" + child_id.lower(), "external_arm_target", "associated_resource", child_id.split("/")[-1], res["source_id"], {"target_id": child_id, "field": field, "arm_detail_collected": False}, child_id, classification="INFERRED")
                add_edge(r_key, inf_arm, "inferred_" + relation_name, "associated_resource", "INFERRED", [res["source_id"]], [field], {"target_id": child_id})

    for pool in inv.get("instance_pools", []):
        p_node = add_node(pool["id"], "instance_pool", "compute", pool["name"], pool["source_id"], pool, ws["id"], workload_name=pool["name"])
        pool_map[pool["id"]] = p_node
        add_edge(root, p_node, "contains_instance_pool", "compute", "OBSERVED", [pool["source_id"]], ["instance_pool_id"], {"instance_pool_id": pool["id"]}, workload_name=pool["name"])

    for pol in inv.get("cluster_policies", []):
        pol_node = add_node(pol["id"], "cluster_policy", "compute", pol["name"], pol["source_id"], pol, ws["id"], workload_name=pol["name"])
        policy_map[pol["id"]] = pol_node
        add_edge(root, pol_node, "contains_cluster_policy", "compute", "OBSERVED", [pol["source_id"]], ["policy_id"], {"policy_id": pol["id"]}, workload_name=pol["name"])

    for cl in inv.get("clusters", []):
        c_kind = "job_cluster" if cl["cluster_source"] == "JOB" else "all_purpose_cluster"
        c_node = add_node(cl["id"], c_kind, "compute", cl["name"], cl["source_id"], cl, ws["id"], workload_name=cl["name"])
        cluster_map[cl["id"]] = c_node
        add_edge(root, c_node, "contains_cluster", "compute", "OBSERVED", [cl["source_id"]], ["cluster_id"], {"cluster_id": cl["id"]}, workload_name=cl["name"])
        if cl.get("policy_id"):
            if cl["policy_id"] in policy_map:
                add_edge(c_node, policy_map[cl["policy_id"]], "governed_by_policy", "compute", "OBSERVED", [cl["source_id"], "dbx_cluster_policies"], ["policy_id"], {"policy_id": cl["policy_id"]}, workload_name=cl["name"])
            else:
                record_unresolved_ref(cl["name"], "cluster_policy_missing", cl["policy_id"], "dbx_cluster_policies", "compute")
        for pool_field in ("instance_pool_id", "driver_instance_pool_id"):
            if cl.get(pool_field):
                if cl[pool_field] in pool_map:
                    add_edge(c_node, pool_map[cl[pool_field]], "backed_by_instance_pool", "compute", "OBSERVED", [cl["source_id"], "dbx_instance_pools"], [pool_field], {pool_field: cl[pool_field]}, workload_name=cl["name"])
                else:
                    record_unresolved_ref(cl["name"], "instance_pool_missing", cl[pool_field], "dbx_instance_pools", "compute")

    for wh in inv.get("sql_warehouses", []):
        w_node = add_node(wh["id"], "sql_warehouse", "compute", wh["name"], wh["source_id"], wh, ws["id"], workload_name=wh["name"])
        wh_map[wh["id"]] = w_node
        add_edge(root, w_node, "contains_sql_warehouse", "compute", "OBSERVED", [wh["source_id"]], ["warehouse_id"], {"warehouse_id": wh["id"]}, workload_name=wh["name"])

    for sc in inv.get("secret_scopes", []):
        sc_node = add_node(sc["name"], "secret_scope", "governance", sc["name"], sc["source_id"], sc, ws["id"], workload_name=sc["name"])
        add_edge(root, sc_node, "contains_secret_scope", "governance", "OBSERVED", [sc["source_id"]], ["name"], {"scope": sc["name"]}, workload_name=sc["name"])
        kv_rid = sc.get("keyvault_resource_id")
        kv_dns = extract_vault_host(sc.get("keyvault_dns_name")) if sc.get("keyvault_dns_name") else None
        if kv_rid and kv_rid.lower() in arm_map:
            add_edge(sc_node, arm_map[kv_rid.lower()], "backed_by_key_vault", "governance", "OBSERVED", [sc["source_id"], "arm_workspace"], ["keyvault_metadata.resource_id"], {"keyvault_resource_id": kv_rid}, workload_name=sc["name"])
        elif kv_dns and kv_dns in kv_by_host:
            add_edge(sc_node, kv_by_host[kv_dns], "backed_by_key_vault", "governance", "OBSERVED", [sc["source_id"]], ["keyvault_metadata.dns_name"], {"dns_name": sc["keyvault_dns_name"]}, workload_name=sc["name"])
        elif kv_rid or kv_dns:
            inf_kv = add_node("scope_kv:" + (kv_dns or kv_rid), "external_key_vault_target", "associated_resource", kv_dns or kv_rid, sc["source_id"], {"keyvault_resource_id": kv_rid, "dns_name": sc.get("keyvault_dns_name")}, ws["id"], classification="INFERRED", workload_name=sc["name"])
            add_edge(sc_node, inf_kv, "inferred_key_vault_reference", "governance", "INFERRED", [sc["source_id"]], ["keyvault_metadata"], {"keyvault_resource_id": kv_rid, "dns_name": sc.get("keyvault_dns_name")}, workload_name=sc["name"])

    ms = inv.get("uc_metastore")
    ms_node = None
    if ms:
        ms_node = add_node(ms["id"], "uc_metastore", "governance", ms["name"], ms["source_id"], ms, ws["id"], workload_name=ms["name"])
        add_edge(root, ms_node, "attached_to_uc_metastore", "governance", "OBSERVED", [ms["source_id"]], ["metastore_id"], {"metastore_id": ms["id"]}, workload_name=ms["name"])

    for cred in inv.get("uc_storage_credentials", []):
        cr_node = add_node(cred["name"], "uc_storage_credential", "governance", cred["name"], cred["source_id"], cred, ws["id"], workload_name=cred["name"])
        cred_map[cred["name"]] = cr_node
        add_edge(ms_node or root, cr_node, "defines_storage_credential", "governance", "OBSERVED", [cred["source_id"]], ["name"], {"credential_name": cred["name"]}, workload_name=cred["name"])
        if cred.get("access_connector_id"):
            ac_low = cred["access_connector_id"].lower()
            if ac_low in arm_map:
                add_edge(cr_node, arm_map[ac_low], "authenticates_via_access_connector", "governance", "OBSERVED", [cred["source_id"]], ["azure_managed_identity.access_connector_id"], {"access_connector_id": cred["access_connector_id"]}, workload_name=cred["name"])
            else:
                inf_ac = add_node("ac:" + ac_low, "external_access_connector_target", "associated_resource", cred["access_connector_id"].split("/")[-1], cred["source_id"], {"access_connector_id": cred["access_connector_id"]}, ws["id"], classification="INFERRED", workload_name=cred["name"])
                add_edge(cr_node, inf_ac, "inferred_access_connector_reference", "governance", "INFERRED", [cred["source_id"]], ["azure_managed_identity.access_connector_id"], {"access_connector_id": cred["access_connector_id"]}, workload_name=cred["name"])

    for loc in inv.get("uc_external_locations", []):
        loc_node = add_node(loc["name"], "uc_external_location", "governance", loc["name"], loc["source_id"], loc, ws["id"], workload_name=loc["name"])
        add_edge(ms_node or root, loc_node, "defines_external_location", "governance", "OBSERVED", [loc["source_id"]], ["name"], {"external_location": loc["name"]}, workload_name=loc["name"])
        if loc.get("credential_name"):
            if loc["credential_name"] in cred_map:
                add_edge(loc_node, cred_map[loc["credential_name"]], "uses_storage_credential", "governance", "OBSERVED", [loc["source_id"], "uc_storage_credentials"], ["credential_name"], {"credential_name": loc["credential_name"]}, workload_name=loc["name"])
            else:
                record_unresolved_ref(loc["name"], "storage_credential_missing", loc["credential_name"], "uc_storage_credentials", "governance")
        acct = extract_storage_account_from_uri(loc.get("url"))
        if acct:
            if acct in storage_by_name:
                add_edge(loc_node, storage_by_name[acct], "points_to_adls_storage_account", "governance", "OBSERVED", [loc["source_id"]], ["url"], {"url": loc["url"], "storage_account": acct}, workload_name=loc["name"])
            else:
                inf_st = add_node("adls:" + acct, "external_storage_target", "associated_resource", acct, loc["source_id"], {"url": loc["url"], "storage_account": acct, "arm_detail_collected": False}, ws["id"], classification="INFERRED", workload_name=loc["name"])
                add_edge(loc_node, inf_st, "inferred_adls_storage_uri_target", "governance", "INFERRED", [loc["source_id"]], ["url"], {"url": loc["url"], "storage_account": acct}, workload_name=loc["name"])

    for conn in inv.get("uc_connections", []):
        conn_node = add_node(conn["name"], "uc_connection", "governance", conn["name"], conn["source_id"], conn, ws["id"], workload_name=conn["name"])
        add_edge(ms_node or root, conn_node, "federates_external_connection", "governance", "OBSERVED", [conn["source_id"]], ["name", "connection_type"], {"connection_type": conn.get("connection_type"), "host": conn.get("host")}, workload_name=conn["name"])

    for cat in inv.get("uc_catalogs", []):
        cat_node = add_node(cat["name"], "uc_catalog", "governance", cat["name"], cat["source_id"], cat, ws["id"], workload_name=cat["name"])
        cat_map[cat["name"]] = cat_node
        add_edge(ms_node or root, cat_node, "contains_catalog", "governance", "OBSERVED", [cat["source_id"]], ["name"], {"catalog_name": cat["name"]}, workload_name=cat["name"])
        c_acct = extract_storage_account_from_uri(cat.get("storage_root") or cat.get("storage_location"))
        if c_acct:
            if c_acct in storage_by_name:
                add_edge(cat_node, storage_by_name[c_acct], "uses_catalog_managed_storage", "governance", "OBSERVED", [cat["source_id"]], ["storage_root"], {"storage_root": cat.get("storage_root") or cat.get("storage_location"), "storage_account": c_acct}, workload_name=cat["name"])
            else:
                inf_cst = add_node("adls:" + c_acct, "external_storage_target", "associated_resource", c_acct, cat["source_id"], {"url": cat.get("storage_root") or cat.get("storage_location"), "storage_account": c_acct, "arm_detail_collected": False}, ws["id"], classification="INFERRED", workload_name=cat["name"])
                add_edge(cat_node, inf_cst, "inferred_catalog_storage_uri_target", "governance", "INFERRED", [cat["source_id"]], ["storage_root"], {"storage_root": cat.get("storage_root") or cat.get("storage_location"), "storage_account": c_acct}, workload_name=cat["name"])
        if cat.get("connection_name"):
            conn_target = next((nodes[k] for k in nodes if nodes[k]["kind"] == "uc_connection" and nodes[k]["name"] == cat["connection_name"]), None)
            if conn_target:
                add_edge(cat_node, conn_target["id"], "uses_federated_connection", "governance", "OBSERVED", [cat["source_id"], "uc_connections"], ["connection_name"], {"connection_name": cat["connection_name"]}, workload_name=cat["name"])

    for sch in inv.get("uc_schemas", []):
        sch_node = add_node(sch["full_name"], "uc_schema", "governance", sch["full_name"], sch["source_id"], sch, ws["id"], workload_name=sch["full_name"])
        schema_map[sch["full_name"]] = sch_node
        if sch["catalog_name"] in cat_map:
            add_edge(cat_map[sch["catalog_name"]], sch_node, "contains_schema", "governance", "OBSERVED", [sch["source_id"], "uc_catalogs"], ["catalog_name"], {"full_name": sch["full_name"]}, workload_name=sch["full_name"])

    for pipe in inv.get("pipelines", []):
        p_node = add_node(pipe["id"], "dlt_pipeline", "orchestration", pipe["name"], pipe["source_id"], pipe, ws["id"], workload_name=pipe["name"])
        pipe_map[pipe["id"]] = p_node
        add_edge(root, p_node, "contains_pipeline", "orchestration", "OBSERVED", [pipe["source_id"]], ["pipeline_id"], {"pipeline_id": pipe["id"]}, workload_name=pipe["name"])
        if pipe.get("detail_collected") is False:
            add_unknown(
                "pipeline_spec_detail_unavailable_" + pipe["id"],
                "orchestration",
                "dlt_pipeline",
                "Pipeline " + pipe["name"] + " (" + pipe["id"] + ") list entry has no full spec (/api/2.0/pipelines/{id} unavailable or not collected); catalog, target schema, storage and cluster bindings remain UNKNOWN.",
                [pipe.get("detail_source_id") or pipe["source_id"]],
                workload_name=pipe["name"],
            )
            continue
        p_sources = list(dict.fromkeys([pipe["source_id"]] + ([pipe["detail_source_id"]] if pipe.get("detail_source_id") else [])))
        if pipe.get("catalog"):
            if pipe["catalog"] in cat_map:
                add_edge(p_node, cat_map[pipe["catalog"]], "publishes_to_catalog", "orchestration", "OBSERVED", p_sources + ["uc_catalogs"], ["catalog"], {"catalog": pipe["catalog"]}, workload_name=pipe["name"])
            if pipe.get("target"):
                full_target = pipe["catalog"] + "." + pipe["target"]
                if full_target in schema_map:
                    add_edge(p_node, schema_map[full_target], "publishes_to_schema", "orchestration", "OBSERVED", p_sources + ["uc_schemas"], ["catalog", "target"], {"schema": full_target}, workload_name=pipe["name"])
        p_acct = extract_storage_account_from_uri(pipe.get("storage"))
        if p_acct:
            if p_acct in storage_by_name:
                add_edge(p_node, storage_by_name[p_acct], "uses_pipeline_storage_account", "orchestration", "OBSERVED", p_sources, ["spec.storage"], {"storage": pipe["storage"], "storage_account": p_acct}, workload_name=pipe["name"])
            else:
                inf_pst = add_node("adls:" + p_acct, "external_storage_target", "associated_resource", p_acct, pipe["source_id"], {"url": pipe["storage"], "storage_account": p_acct, "arm_detail_collected": False}, ws["id"], classification="INFERRED", workload_name=pipe["name"])
                add_edge(p_node, inf_pst, "inferred_pipeline_storage_uri_target", "orchestration", "INFERRED", p_sources, ["spec.storage"], {"storage": pipe["storage"], "storage_account": p_acct}, workload_name=pipe["name"])
        for pcl in pipe.get("clusters", []):
            if pcl.get("policy_id"):
                if pcl["policy_id"] in policy_map:
                    add_edge(p_node, policy_map[pcl["policy_id"]], "governed_by_policy", "compute", "OBSERVED", p_sources + ["dbx_cluster_policies"], ["spec.clusters.policy_id"], {"policy_id": pcl["policy_id"]}, workload_name=pipe["name"])
                else:
                    record_unresolved_ref(pipe["name"], "pipeline_cluster_policy_missing", pcl["policy_id"], "dbx_cluster_policies", "compute")
            for pool_f in ("instance_pool_id", "driver_instance_pool_id"):
                if pcl.get(pool_f):
                    if pcl[pool_f] in pool_map:
                        add_edge(p_node, pool_map[pcl[pool_f]], "backed_by_instance_pool", "compute", "OBSERVED", p_sources + ["dbx_instance_pools"], ["spec.clusters." + pool_f], {pool_f: pcl[pool_f]}, workload_name=pipe["name"])
                    else:
                        record_unresolved_ref(pipe["name"], "pipeline_instance_pool_missing", pcl[pool_f], "dbx_instance_pools", "compute")

    for job in inv.get("jobs", []):
        j_node = add_node(job["id"], "job", "orchestration", job["name"], job["source_id"], job, ws["id"], workload_name=job["name"])
        job_map[job["id"]] = j_node
        add_edge(root, j_node, "contains_job", "orchestration", "OBSERVED", [job["source_id"]], ["job_id"], {"job_id": job["id"]}, workload_name=job["name"])

    for job in inv.get("jobs", []):
        j_node = job_map[job["id"]]
        job_incomplete = job.get("tasks_incomplete") is True
        if job_incomplete:
            add_unknown(
                "job_tasks_truncated_or_incomplete_" + job["id"],
                "orchestration",
                "job_dag",
                "Job " + job["name"] + " (" + job["id"] + ") task or job_cluster list was truncated or incomplete in jobs/list and full detail could not be resolved; intra-job DAG completeness remains UNKNOWN.",
                [job["source_id"]],
                workload_name=job["name"],
            )
        jc_nodes = {}
        for jc in job.get("job_clusters", []):
            jc_key = job["id"] + ":" + jc["job_cluster_key"]
            jc_node = add_node(jc_key, "job_cluster_spec", "compute", job["name"] + " / " + jc["job_cluster_key"], job["source_id"], jc, ws["id"], workload_name=job["name"])
            jc_nodes[jc["job_cluster_key"]] = jc_node
            add_edge(j_node, jc_node, "defines_job_cluster_spec", "orchestration", "OBSERVED", [job["source_id"]], ["job_clusters.job_cluster_key"], {"job_cluster_key": jc["job_cluster_key"]}, workload_name=job["name"])
            if jc.get("policy_id"):
                if jc["policy_id"] in policy_map:
                    add_edge(jc_node, policy_map[jc["policy_id"]], "governed_by_policy", "compute", "OBSERVED", [job["source_id"], "dbx_cluster_policies"], ["policy_id"], {"policy_id": jc["policy_id"]}, workload_name=job["name"])
                else:
                    record_unresolved_ref(job["name"], "job_cluster_policy_missing", jc["policy_id"], "dbx_cluster_policies", "compute")
            if jc.get("instance_pool_id"):
                if jc["instance_pool_id"] in pool_map:
                    add_edge(jc_node, pool_map[jc["instance_pool_id"]], "backed_by_instance_pool", "compute", "OBSERVED", [job["source_id"], "dbx_instance_pools"], ["instance_pool_id"], {"instance_pool_id": jc["instance_pool_id"]}, workload_name=job["name"])
                else:
                    record_unresolved_ref(job["name"], "job_cluster_pool_missing", jc["instance_pool_id"], "dbx_instance_pools", "compute")

        task_nodes = {}
        for task in job.get("tasks", []):
            t_id = job["id"] + ":" + task["task_key"]
            t_node = add_node(t_id, "job_task", "orchestration", job["name"] + " :: " + task["task_key"], job["source_id"], task, ws["id"], workload_name=job["name"])
            task_nodes[task["task_key"]] = t_node
            add_edge(j_node, t_node, "has_task", "orchestration", "OBSERVED", [job["source_id"]], ["tasks.task_key"], {"task_key": task["task_key"]}, workload_name=job["name"])
            if task.get("existing_cluster_id"):
                if task["existing_cluster_id"] in cluster_map:
                    add_edge(t_node, cluster_map[task["existing_cluster_id"]], "runs_on_all_purpose_cluster", "orchestration", "OBSERVED", [job["source_id"], "dbx_clusters"], ["existing_cluster_id"], {"existing_cluster_id": task["existing_cluster_id"]}, workload_name=job["name"])
                else:
                    record_unresolved_ref(job["name"] + "::" + task["task_key"], "existing_cluster_missing", task["existing_cluster_id"], "dbx_clusters", "orchestration")
            if task.get("job_cluster_key"):
                if task["job_cluster_key"] in jc_nodes:
                    add_edge(t_node, jc_nodes[task["job_cluster_key"]], "runs_on_job_cluster_spec", "orchestration", "OBSERVED", [job["source_id"]], ["job_cluster_key"], {"job_cluster_key": task["job_cluster_key"]}, workload_name=job["name"])
                elif not job_incomplete:
                    record_unresolved_ref(job["name"] + "::" + task["task_key"], "job_cluster_key_missing", task["job_cluster_key"], job["source_id"], "orchestration", intra_object=True)
            if task.get("pipeline_id"):
                if task["pipeline_id"] in pipe_map:
                    add_edge(t_node, pipe_map[task["pipeline_id"]], "triggers_dlt_pipeline", "orchestration", "OBSERVED", [job["source_id"], "dbx_pipelines"], ["pipeline_task.pipeline_id"], {"pipeline_id": task["pipeline_id"]}, workload_name=job["name"])
                else:
                    record_unresolved_ref(job["name"] + "::" + task["task_key"], "pipeline_missing", task["pipeline_id"], "dbx_pipelines", "orchestration")
            if task.get("warehouse_id"):
                if task["warehouse_id"] in wh_map:
                    add_edge(t_node, wh_map[task["warehouse_id"]], "executes_on_sql_warehouse", "orchestration", "OBSERVED", [job["source_id"], "dbx_sql_warehouses"], ["sql_task.warehouse_id"], {"warehouse_id": task["warehouse_id"]}, workload_name=job["name"])
                else:
                    record_unresolved_ref(job["name"] + "::" + task["task_key"], "sql_warehouse_missing", task["warehouse_id"], "dbx_sql_warehouses", "orchestration")
            if task.get("run_job_id"):
                if task["run_job_id"] in job_map:
                    add_edge(t_node, job_map[task["run_job_id"]], "triggers_downstream_job", "orchestration", "OBSERVED", [job["source_id"]], ["run_job_task.job_id"], {"run_job_id": task["run_job_id"]}, workload_name=job["name"])
                else:
                    record_unresolved_ref(job["name"] + "::" + task["task_key"], "downstream_job_missing", task["run_job_id"], "dbx_jobs", "orchestration")

        for task in job.get("tasks", []):
            t_node = task_nodes[task["task_key"]]
            for upstream_key in task.get("depends_on", []):
                if upstream_key in task_nodes:
                    add_edge(t_node, task_nodes[upstream_key], "depends_on_task", "orchestration", "OBSERVED", [job["source_id"]], ["tasks.depends_on"], {"task_key": task["task_key"], "depends_on": upstream_key}, workload_name=job["name"])
                elif not job_incomplete:
                    record_unresolved_ref(job["name"] + "::" + task["task_key"], "task_dependency_missing", upstream_key, job["source_id"], "orchestration", intra_object=True)

    add_unknown(
        "runtime_table_column_lineage_not_queried",
        "governance",
        "table_lineage",
        "Runtime table/column lineage (system.access.table_lineage, system.access.column_lineage) requires executing SQL queries on a running SQL Warehouse (billable DBU compute). Control-plane collection never starts compute or fabricates table lineage from notebook names.",
        ["uc_system_lineage"],
    )
    add_unknown(
        "notebook_code_internal_dependencies_not_executed",
        "orchestration",
        "notebook_code",
        "Dynamic paths, JDBC strings and library calls inside notebook/Python/JAR source code are not statically parsed or executed.",
        ["dbx_jobs"],
    )
    add_unknown(
        "effective_network_and_storage_acl_reachability_untested",
        "associated_resource",
        "network_reachability",
        "Observed VNet injection, NSG rules, Private Endpoints, Storage Credentials and External Locations confirm configuration references, not live data-plane packet flow or effective ACL evaluation.",
        ["arm_workspace", "uc_external_locations"],
    )
    for source in raw["sources"]:
        if source["status"] not in ("complete", "not_applicable") and source["id"] != "uc_system_lineage":
            add_unknown(
                "source_incomplete_" + source["id"],
                "control_plane",
                "source_blind_spot",
                source["id"] + " status=" + source["status"] + ": " + source["note"],
                [source["id"]],
                source.get("resource_id"),
            )

    edge_list = list(edges.values())
    node_list = list(nodes.values())
    return {
        "nodes": node_list,
        "edges": edge_list,
        "unknowns": unknowns,
        "broken_references": broken_refs,
        "unverified_references": unverified_refs,
        "summary_counts": {
            "nodes_total": len(node_list),
            "edges_total": len(edge_list),
            "edges_observed": sum(e["classification"] == "OBSERVED" for e in edge_list),
            "edges_inferred": sum(e["classification"] == "INFERRED" for e in edge_list),
            "unknowns_total": len(unknowns),
            "broken_references_total": len(broken_refs),
            "unverified_references_total": len(unverified_refs),
        },
    }


def outcome(status, reason, value=None, source_ids=None):
    return {"status": status, "reason": reason, "value": value or {}, "source_ids": source_ids or []}


def decision(value, reason, observed, sources=None):
    return outcome("not_evaluated" if value is None else "passed" if value else "failed", reason, observed, sources)


def source_complete(raw, *ids):
    sources = {source["id"]: source for source in raw["sources"]}
    return all(pick(sources.get(source_id), "status") == "complete" for source_id in ids)


def expected(raw, key):
    return raw.get("requirements", {}).get(key)


def conditional(value, requirement, reason, observed, sources=None):
    if requirement is False:
        return outcome("not_applicable", "El requisito confirmado no aplica. " + reason, observed, sources)
    if value is True:
        return decision(True, reason + " Configuración observada; no prueba eficacia en tiempo de ejecución.", observed, sources)
    if requirement is not True:
        return outcome("not_evaluated", "Falta requisito confirmado del propietario o control compensatorio. " + reason, observed, sources)
    return decision(value, reason + " Requisito confirmado por el propietario.", observed, sources)


def evaluate_workspace_rule(rule, raw, dep_graph):
    test, ws, inv = rule["test"], raw["workspace"], raw["inventory"]
    if test == "sku_premium":
        sku = (ws.get("sku_name") or ws.get("sku_tier") or "").lower()
        val = True if sku == "premium" else False if sku in ("standard", "trial") else None
        return conditional(val, expected(raw, "premium_required") if expected(raw, "premium_required") is not None else True,
                           "SKU ARM observada del workspace.", {"sku_name": ws.get("sku_name"), "sku_tier": ws.get("sku_tier")}, ["arm_workspace"])
    if test == "secure_cluster_connectivity":
        return decision(ws.get("enable_no_public_ip"), "Parámetro enableNoPublicIp observado en ARM.", {"enable_no_public_ip": ws.get("enable_no_public_ip")}, ["arm_workspace"])
    if test == "vnet_injection":
        vnet = ws.get("custom_virtual_network_id")
        vnet_val = True if vnet else (False if source_complete(raw, "arm_workspace") else None)
        return conditional(vnet_val, expected(raw, "vnet_injection_required") if expected(raw, "vnet_injection_required") is not None else True,
                           "Parámetro customVirtualNetworkId e inyección de subredes host/container.", {
                               "custom_virtual_network_id": vnet,
                               "custom_public_subnet_name": ws.get("custom_public_subnet_name"),
                               "custom_private_subnet_name": ws.get("custom_private_subnet_name"),
                           }, ["arm_workspace"])
    if test == "private_link_and_public_access":
        pna = ws.get("public_network_access")
        pes = ws.get("private_endpoint_connections", [])
        approved_pe = any(p.get("status") == "Approved" for p in pes)
        val = True if pna == "Disabled" or approved_pe else (False if pna == "Enabled" and not pes else None)
        return conditional(val, expected(raw, "private_link_required"), "Configuración publicNetworkAccess, requiredNsgRules y Private Endpoints.", {
            "public_network_access": pna, "required_nsg_rules": ws.get("required_nsg_rules"), "private_endpoint_connections": pes,
        }, ["arm_workspace"])
    if test == "access_connector_and_storage_firewall":
        ac = ws.get("access_connector", {})
        has_ac = bool(ac.get("id")) and ac.get("identity_type") in ("SystemAssigned", "UserAssigned", "SystemAssigned,UserAssigned")
        return decision(True if has_ac else False if source_complete(raw, "arm_workspace") else None,
                        "Access Connector vinculado al workspace para identidad administrada.", {
                            "access_connector": ac, "default_storage_firewall": ws.get("default_storage_firewall"),
                        }, ["arm_workspace"])
    if test == "customer_managed_keys":
        cmk = ws.get("cmk", {})
        has_cmk = cmk.get("managed_services_key_source") == "Microsoft.Keyvault" and cmk.get("managed_disk_key_source") == "Microsoft.Keyvault"
        return conditional(has_cmk, expected(raw, "cmk_required"), "Cifrado CMK de managedServices y managedDisk.", cmk, ["arm_workspace"])
    if test == "enhanced_security_compliance":
        esc = ws.get("enhanced_security_compliance", {})
        enabled = esc.get("enhanced_security_monitoring") == "Enabled" or esc.get("compliance_security_profile") == "Enabled"
        return conditional(enabled, expected(raw, "enhanced_security_required"), "Perfil enhancedSecurityCompliance observado.", esc, ["arm_workspace"])
    if test == "diagnostics":
        rows = raw.get("arm_diagnostics", [])
        enabled = any(log.get("enabled") is True for r in rows for log in r.get("logs", []))
        val = True if enabled else False if source_complete(raw, "arm_diagnostics") else None
        return decision(val, "Diagnostic settings habilitados en ARM; la ingesta efectiva requiere verificación separada.", {"diagnostic_settings": rows}, ["arm_diagnostics"])
    if test == "pat_token_governance":
        if not source_complete(raw, "dbx_workspace_conf") or not isinstance(raw.get("workspace_conf"), dict):
            return outcome("not_evaluated", "workspace-conf no disponible para revisar políticas de tokens PAT.", source_ids=["dbx_workspace_conf"])
        conf = raw["workspace_conf"]
        max_days = conf.get("maxTokenLifetimeDays")
        tokens_enabled = conf.get("enableTokensConfig")
        bounded = tokens_enabled == "false" or (max_days is not None and str(max_days).isdigit() and 0 < int(max_days) <= 90)
        return decision(bounded, "Gobernanza de tokens PAT (enableTokensConfig y maxTokenLifetimeDays <= 90 días).", conf, ["dbx_workspace_conf"])
    if test == "default_catalog_unity":
        dtype = ws.get("default_catalog_type")
        has_uc = bool(inv.get("uc_metastore"))
        val = True if dtype == "UnityCatalog" or has_uc else (False if dtype == "HiveMetastore" else None)
        return decision(val, "Catálogo predeterminado UnityCatalog o metastore adjunto observado.", {
            "default_catalog_type": dtype, "default_catalog_name": ws.get("default_catalog_name"),
            "uc_metastore_id": pick(inv.get("uc_metastore"), "id"),
        }, ["arm_workspace", "uc_metastore_summary"])
    if test == "global_init_scripts":
        if not source_complete(raw, "dbx_init_scripts"):
            return outcome("not_evaluated", "Lista de global init scripts no disponible.", source_ids=["dbx_init_scripts"])
        enabled = [s for s in inv.get("global_init_scripts", []) if s.get("enabled") is True]
        return decision(len(enabled) == 0, "Los global init scripts activos deben minimizarse y migrarse a políticas o volúmenes gobernados.", {
            "total_scripts": len(inv.get("global_init_scripts", [])), "enabled_scripts": [s["name"] for s in enabled],
        }, ["dbx_init_scripts"])
    if test == "advisor":
        return decision(True if source_complete(raw, "arm_advisor") else None,
                        "Recomendaciones cacheadas de Azure Advisor leídas para el workspace.", {"recommendations_count": len(raw.get("advisor", []))}, ["arm_advisor"])
    if test == "uc_metastore_attached":
        if not source_complete(raw, "uc_metastore_summary"):
            return outcome("not_evaluated", "Metastore summary de Unity Catalog no disponible.", source_ids=["uc_metastore_summary"])
        ms = inv.get("uc_metastore")
        return decision(bool(ms and ms.get("metastore_id")), "Asignación de Metastore de Unity Catalog confirmada.", {"metastore": ms}, ["uc_metastore_summary"])
    if test == "uc_storage_credential_mi":
        if not source_complete(raw, "uc_storage_credentials"):
            return outcome("not_evaluated", "Storage credentials de Unity Catalog no disponibles.", source_ids=["uc_storage_credentials"])
        creds = inv.get("uc_storage_credentials", [])
        if not creds:
            return outcome("not_evaluated", "No se observaron storage credentials registradas en Unity Catalog.", source_ids=["uc_storage_credentials"])
        sp_creds = [c["name"] for c in creds if c.get("uses_service_principal") or not c.get("uses_managed_identity")]
        return decision(len(sp_creds) == 0, "Todas las storage credentials usan Azure Managed Identity vía Access Connector.", {
            "total_credentials": len(creds), "non_managed_identity_credentials": sp_creds,
        }, ["uc_storage_credentials"])
    if test == "uc_external_locations_governed":
        if not source_complete(raw, "uc_external_locations", "uc_storage_credentials"):
            return outcome("not_evaluated", "External locations o storage credentials incompletas.", source_ids=["uc_external_locations", "uc_storage_credentials"])
        locs = inv.get("uc_external_locations", [])
        if not locs:
            return outcome("not_evaluated", "No se observaron external locations registradas.", source_ids=["uc_external_locations"])
        known_creds = {c["name"] for c in inv.get("uc_storage_credentials", [])}
        if all(str(l.get("url") or "").lower().startswith("abfss://") for l in locs) and any(not l.get("credential_name") for l in locs) and not known_creds:
            return outcome(
                "not_evaluated",
                "External locations observadas vía permiso mínimo BROWSE con URI abfss://, pero credential_name y uc_storage_credentials están filtrados por ACL de Unity Catalog.",
                {"total_external_locations": len(locs), "browse_only_projection": True},
                ["uc_external_locations", "uc_storage_credentials"],
            )
        ungoverned = [
            l["name"] for l in locs
            if not l.get("credential_name") or l["credential_name"] not in known_creds
            or not str(l.get("url") or "").lower().startswith("abfss://")
        ]
        return decision(len(ungoverned) == 0, "External locations vinculadas a Storage Credential existente y URI abfss://.", {
            "total_external_locations": len(locs), "non_compliant_locations": ungoverned,
        }, ["uc_external_locations", "uc_storage_credentials"])
    if test == "secret_scopes_keyvault":
        if not source_complete(raw, "dbx_secret_scopes"):
            return outcome("not_evaluated", "Secret scopes no disponibles.", source_ids=["dbx_secret_scopes"])
        scopes = inv.get("secret_scopes", [])
        if not scopes:
            return outcome("not_evaluated", "No se observaron secret scopes en el workspace.", source_ids=["dbx_secret_scopes"])
        dbx_backed = [s["name"] for s in scopes if s.get("backend_type") != "AZURE_KEYVAULT"]
        return decision(len(dbx_backed) == 0, "Secret scopes respaldados por Azure Key Vault (AZURE_KEYVAULT).", {
            "total_scopes": len(scopes), "databricks_backed_scopes": dbx_backed,
        }, ["dbx_secret_scopes"])
    if test == "dependency_integrity":
        dep_sources = (
            "dbx_jobs",
            "dbx_clusters",
            "dbx_instance_pools",
            "dbx_cluster_policies",
            "dbx_pipelines",
            "dbx_sql_warehouses",
            "uc_storage_credentials",
            "uc_external_locations",
        )
        broken = dep_graph.get("broken_references", [])
        unverified = dep_graph.get("unverified_references", [])
        incomplete_jobs = [j["name"] for j in inv.get("jobs", []) if j.get("tasks_incomplete") is True]
        incomplete_pipes = [p["name"] for p in inv.get("pipelines", []) if p.get("detail_collected") is False]
        if broken:
            return decision(
                False,
                "Se detectaron referencias internas rotas confirmadas dentro de definiciones completas de Jobs (job_cluster_key o depends_on inexistentes).",
                {
                    "broken_references_count": len(broken),
                    "broken_references": broken,
                    "unverified_references_count": len(unverified),
                },
                list(dep_sources),
            )
        if not source_complete(raw, *dep_sources) or incomplete_jobs or incomplete_pipes or unverified:
            return outcome(
                "not_evaluated",
                "Existen fuentes de dependencias incompletas, detalles de jobs/pipelines truncados o referencias entre objetos no verificadas (las APIs list de Databricks filtran por ACL, por lo que la ausencia de un ID externo se mantiene UNKNOWN en lugar de declararse rota).",
                {
                    "broken_references_count": 0,
                    "unverified_references_count": len(unverified),
                    "unverified_references": unverified,
                    "incomplete_jobs": incomplete_jobs,
                    "incomplete_pipelines": incomplete_pipes,
                },
                list(dep_sources),
            )
        return decision(
            True,
            "Todas las fuentes de dependencia están completas y todas las referencias entre tareas de Jobs, clústeres, pools, políticas, pipelines, warehouses y credenciales resuelven en el mapa de dependencias.",
            {
                "broken_references_count": 0,
                "unverified_references_count": 0,
            },
            list(dep_sources),
        )
    if test == "runtime_table_lineage":
        return outcome(
            "not_evaluated",
            "El linaje dinámico de tablas y columnas (system.access.table_lineage / column_lineage) requiere ejecutar consultas en un SQL Warehouse activo y no se ejecuta ni simula desde este colector de plano de control.",
            {"system_tables_queried": False},
            ["uc_system_lineage"],
        )
    if test == "lakehouse_federation_connections":
        if not source_complete(raw, "uc_connections"):
            return outcome("not_evaluated", "Conexiones de Lakehouse Federation no disponibles.", source_ids=["uc_connections"])
        conns = inv.get("uc_connections", [])
        if not conns:
            return outcome("not_applicable", "No existen conexiones externas de Lakehouse Federation registradas en el metastore.", {"connections_count": 0}, ["uc_connections"])
        return decision(True, "Conexiones externas de Lakehouse Federation inventariadas en el mapa de dependencias.", {
            "connections": [{"name": c["name"], "type": c.get("connection_type"), "host": c.get("host")} for c in conns],
        }, ["uc_connections"])
    if test == "outbound_control_plane_endpoints":
        if not source_complete(raw, "arm_outbound_endpoints"):
            return outcome("not_evaluated", "Lista oficial outboundNetworkDependenciesEndpoints no disponible.", source_ids=["arm_outbound_endpoints"])
        eps = inv.get("outbound_endpoints", [])
        return decision(bool(eps), "Dependencias de red saliente hacia el plano de control inventariadas desde ARM.", {
            "categories": [e["category"] for e in eps], "count": len(eps),
        }, ["arm_outbound_endpoints"])
    if test == "cost_attribution":
        head = (raw.get("databricks_cost_model") or {}).get("headline") or {}
        gap, first = head.get("unattributed_share"), head.get("first_tag")
        if gap is not None and first and first.get("tagged_share") is not None:
            return decision(
                gap <= 10 and first["tagged_share"] >= 80,
                "Atribución del coste de Databricks por etiquetas en Cost Management: como mucho un 10 % sin etiqueta de cómputo y al menos un 80 % con la etiqueta de imputación principal.",
                {"month": head.get("review_month"), "unattributed_share": gap, "allocation_tag": first["tag"], "tagged_share": first["tagged_share"]},
                ["azure_cost_databricks"],
            )
        return outcome(
            "not_evaluated",
            "Sin datos de Cost Management para Databricks (análisis de costes desactivado, lectura denegada o sin consumo): no se puede medir qué parte del coste explican las etiquetas.",
            {"cost_status": (raw.get("databricks_cost_model") or {}).get("status")},
            ["azure_cost_databricks"],
        )
    raise EvidenceError("unknown_rule", "Workspace rule has no implemented evaluator: " + str(test), "rule_catalog")


def evaluate_workload_rule(rule, row, raw):
    test = rule["test"]
    kind = row.get("kind")
    if test in ("cluster_autotermination", "cluster_policy_bound", "cluster_access_mode", "cluster_runtime_lts", "cluster_autoscaling_or_pool"):
        if kind not in ("AllPurposeCluster", "JobCluster"):
            return None
        if test == "cluster_autotermination":
            if kind == "JobCluster":
                return outcome("not_applicable", "Clúster efímero de Job: finaliza automáticamente al terminar la tarea.", {"cluster_source": row.get("cluster_source")}, [row["source_id"]])
            mins = row.get("autotermination_minutes")
            val = True if isinstance(mins, (int, float)) and 0 < mins <= 60 else False
            return decision(val, "Autoterminación configurada <= 60 minutos en clúster All-Purpose.", {"autotermination_minutes": mins}, [row["source_id"]])
        if test == "cluster_policy_bound":
            return decision(bool(row.get("policy_id")), "Asociación de policy_id observada en el clúster.", {"policy_id": row.get("policy_id")}, [row["source_id"]])
        if test == "cluster_access_mode":
            mode = (row.get("data_security_mode") or "").upper()
            val = True if mode in ("USER_ISOLATION", "SINGLE_USER", "SHARED") else False if mode in ("NONE", "LEGACY_PASSTHROUGH", "LEGACY_TABLE_ACL", "LEGACY_SINGLE_USER", "") else None
            return decision(val, "Modo de acceso data_security_mode compatible con Unity Catalog y aislamiento.", {"data_security_mode": row.get("data_security_mode")}, [row["source_id"]])
        if test == "cluster_runtime_lts":
            sv = row.get("spark_version") or ""
            match = re.match(r"^(\d+)\.(\d+)", sv)
            major = int(match.group(1)) if match else None
            is_lts = "lts" in sv.lower()
            val = True if major is not None and major >= 13 and is_lts else False if major is not None else None
            return decision(val, "Versión de Databricks Runtime LTS >= 13.x observada.", {"spark_version": sv}, [row["source_id"]])
        if test == "cluster_autoscaling_or_pool":
            has_auto = bool(row.get("autoscale")) or bool(row.get("instance_pool_id"))
            return decision(has_auto, "Autoscale o vinculación a Instance Pool observada en el clúster.", {
                "autoscale": row.get("autoscale"), "instance_pool_id": row.get("instance_pool_id"), "num_workers": row.get("num_workers"),
            }, [row["source_id"]])

    if test in ("job_uses_job_compute", "job_resilience_settings", "job_service_principal_run_as"):
        if kind != "Job":
            return None
        tasks = row.get("tasks", [])
        if test == "job_uses_job_compute":
            all_purpose_tasks = [t["task_key"] for t in tasks if t.get("existing_cluster_id")]
            return decision(len(all_purpose_tasks) == 0, "Las tareas del Job usan Job Compute, Serverless, SQL Warehouse o Pipeline en lugar de existing_cluster_id All-Purpose.", {
                "tasks_total": len(tasks), "tasks_on_all_purpose_cluster": all_purpose_tasks,
            }, [row["source_id"]])
        if test == "job_resilience_settings":
            has_timeout = bool(row.get("timeout_seconds")) or (bool(tasks) and all(bool(t.get("timeout_seconds")) for t in tasks))
            has_notif = row.get("has_notifications") is True
            return decision(has_timeout and has_notif, "Job configurado con timeout_seconds y notificaciones de fallo/alerta.", {
                "job_timeout_seconds": row.get("timeout_seconds"), "has_notifications": has_notif,
            }, [row["source_id"]])
        if test == "job_service_principal_run_as":
            sp = row.get("run_as_service_principal")
            user = row.get("run_as_user_name")
            val = True if sp else False if user else None
            return decision(val, "Identidad de ejecución run_as del Job asignada a un Service Principal.", {
                "run_as_service_principal": sp, "run_as_user_name": user,
            }, [row["source_id"]])

    if test == "sql_warehouse_autostop":
        if kind != "SqlWarehouse":
            return None
        mins = row.get("auto_stop_mins")
        serverless = row.get("enable_serverless_compute") is True or (row.get("warehouse_type") or "").upper() == "PRO"
        val = True if isinstance(mins, (int, float)) and 0 < mins <= 30 and serverless else False
        return decision(val, "SQL Warehouse con auto_stop_mins <= 30 minutos y modo Serverless/Pro.", {
            "auto_stop_mins": mins, "enable_serverless_compute": row.get("enable_serverless_compute"), "warehouse_type": row.get("warehouse_type"),
        }, [row["source_id"]])

    if test == "pipeline_unity_catalog":
        if kind != "LakeflowPipeline":
            return None
        if row.get("detail_collected") is False:
            return outcome(
                "not_evaluated",
                "El detalle spec del pipeline (/api/2.0/pipelines/{id}) no estuvo disponible; el listado resumen no incluye catalog/schema.",
                {"pipeline_id": row.get("id"), "detail_collected": False},
                [row.get("detail_source_id") or row["source_id"]],
            )
        cat = row.get("catalog")
        val = True if cat and cat.lower() not in ("hive_metastore", "") else False
        return decision(val, "Pipeline declarativo configurado con catálogo destino en Unity Catalog.", {
            "catalog": cat, "schema": row.get("schema") or row.get("target"), "target": row.get("target"), "serverless": row.get("serverless"),
        }, [row.get("detail_source_id") or row["source_id"]])
    return None


def evaluate_resource_rule(rule, row, raw):
    test = rule["test"]
    rkind = row.get("resource_kind")
    cfg = row.get("configuration", {})
    if test == "storage_tls_and_public_blob":
        if rkind != "microsoft.storage/storageaccounts":
            return None
        https = cfg.get("supportsHttpsTrafficOnly")
        tls = cfg.get("minimumTlsVersion")
        pub_blob = cfg.get("allowBlobPublicAccess")
        val = False if (https is False or tls in ("TLS1_0", "TLS1_1") or pub_blob is True) else (
            True if https is True and tls in ("TLS1_2", "TLS1_3") and pub_blob is False else None
        )
        return decision(val, "HTTPS obligatorio, TLS >= 1.2 y allowBlobPublicAccess=false en cuenta de almacenamiento asociada.", cfg, [row["source_id"]])
    if test == "storage_shared_key_and_network":
        if rkind != "microsoft.storage/storageaccounts":
            return None
        shared = cfg.get("allowSharedKeyAccess")
        pna = cfg.get("publicNetworkAccess")
        if row.get("name", "").lower() == (raw["workspace"].get("dbfs_storage_account_name") or "").lower():
            return outcome("not_applicable", "Cuenta DBFS root administrada por la plataforma Azure Databricks.", cfg, [row["source_id"]])
        val = True if shared is False and pna == "Disabled" else False if shared is True or pna == "Enabled" else None
        return conditional(val, expected(raw, "shared_key_disabled_required") if expected(raw, "shared_key_disabled_required") is not None else True,
                           "Shared Key y acceso público en cuenta ADLS Gen2 asociada.", cfg, [row["source_id"]])
    if test == "keyvault_rbac_and_purge":
        if rkind != "microsoft.keyvault/vaults":
            return None
        rbac = cfg.get("enableRbacAuthorization")
        purge = cfg.get("enablePurgeProtection")
        val = True if rbac is True and purge is True else False if rbac is False or purge is False else None
        return decision(val, "Key Vault asociado con Azure RBAC y Purge Protection habilitados.", cfg, [row["source_id"]])
    if test == "nsg_exposure":
        if rkind != "microsoft.network/networksecuritygroups":
            return None
        rules = row.get("security_rules", [])
        exposed = []
        for srule in rules:
            if srule.get("direction") != "Inbound" or srule.get("access") != "Allow":
                continue
            srcs = ([srule.get("sourceAddressPrefix")] if srule.get("sourceAddressPrefix") else []) + (srule.get("sourceAddressPrefixes") or [])
            ports = ([srule.get("destinationPortRange")] if srule.get("destinationPortRange") else []) + (srule.get("destinationPortRanges") or [])
            if any(s in ("*", "0.0.0.0/0", "::/0", "Internet") for s in srcs) and any(p in ("*", "22", "3389", "0-65535") for p in ports):
                exposed.append(srule)
        return decision(len(exposed) == 0, "Reglas Inbound Allow desde Internet hacia puertos administrativos en NSG asociado.", {
            "exposed_rules": exposed, "total_rules": len(rules),
        }, [row["source_id"]])
    if test == "private_endpoint_approved":
        if rkind != "microsoft.network/privateendpoints":
            return None
        conns = row.get("connections", [])
        val = True if conns and all(c.get("status") == "Approved" for c in conns) else False if conns else None
        return decision(val, "Estado de aprobación de las conexiones Private Endpoint asociadas.", {"connections": conns}, [row["source_id"]])
    return None


def make_check(rule, target_id, target_name, workload_name, evaluation, reference, ws):
    status = evaluation["status"]
    cid = rule["rule_id"] + "-" + hashlib.sha256((ws["id"].lower() + "|" + rule["rule_id"] + "|" + str(target_id)).encode("utf-8")).hexdigest()[:10]
    sev_labels = {"critical": "Crítica", "high": "Alta", "medium": "Media", "low": "Baja"}
    eff_labels = {"low": "L", "medium": "M", "high": "H"}
    return {
        "check_id": cid,
        "rule_id": rule["rule_id"],
        "reference_id": rule["reference_id"],
        "title": rule["title"],
        "status": status,
        "level": rule["level"],
        "area": rule["area"],
        "pillar": rule["pillar"],
        "severity": rule["severity"],
        "severity_label": sev_labels[rule["severity"]],
        "effort": rule["effort"],
        "effort_label": eff_labels[rule["effort"]],
        "resource_id": target_id,
        "resource_name": target_name,
        "workload_name": workload_name,
        "workspace_id": ws["id"],
        "workspace_name": ws["workspace_name"],
        "reason": evaluation["reason"],
        "business_impact": rule["business_impact"],
        "recommendation": rule["recommendation"],
        "learn_url": rule["learn_url"],
        "evidence": [] if status in ("not_evaluated", "not_applicable") and not evaluation["value"] else [
            {
                "source_id": (evaluation["source_ids"] or ["arm_workspace"])[0],
                "source_ids": evaluation["source_ids"] or ["arm_workspace"],
                "resource_id": target_id,
                "observed_at": reference,
                "value": evaluation["value"],
            }
        ],
    }


def evaluate(raw, reference, dep_graph):
    ws, inv = raw["workspace"], raw["inventory"]
    checks = []
    workloads = (
        inv.get("clusters", [])
        + inv.get("jobs", [])
        + inv.get("pipelines", [])
        + inv.get("sql_warehouses", [])
    )
    resources = inv.get("related_resources", [])
    for rule in CATALOG.get("rules", []):
        if rule["level"] == "workspace":
            ev = evaluate_workspace_rule(rule, raw, dep_graph)
            checks.append(make_check(rule, ws["id"], ws["name"], "", ev, reference, ws))
        elif rule["level"] == "workload":
            matched_any = False
            for wl in workloads:
                ev = evaluate_workload_rule(rule, wl, raw)
                if ev is not None:
                    matched_any = True
                    checks.append(make_check(rule, ws["id"] + "/workloads/" + str(wl["id"]), wl["name"], wl["name"], ev, reference, ws))
            if not matched_any:
                checks.append(make_check(rule, ws["id"], ws["name"], "", outcome(
                    "not_evaluated",
                    "No se observaron objetos de carga aplicables o la fuente REST del workspace no estuvo disponible; ausencia no equivale a cumplimiento.",
                    {}, ["dbx_clusters", "dbx_jobs", "dbx_pipelines", "dbx_sql_warehouses"],
                ), reference, ws))
        elif rule["level"] == "resource":
            matched_res = False
            for res in resources:
                ev = evaluate_resource_rule(rule, res, raw)
                if ev is not None:
                    matched_res = True
                    checks.append(make_check(rule, res["id"], res["name"], res["name"] or "", ev, reference, ws))
            if not matched_res:
                checks.append(make_check(rule, ws["id"], ws["name"], "", outcome(
                    "not_evaluated",
                    "No se recolectaron recursos ARM asociados de este tipo en el alcance aprobado; no se asume ausencia de riesgo.",
                    {}, ["arm_workspace"],
                ), reference, ws))
    return checks


def score(checks):
    counts = {s: sum(c["status"] == s for c in checks) for s in CHECK_STATUSES}
    evaluated = counts["passed"] + counts["failed"]
    eligible = evaluated + counts["not_evaluated"]
    return {
        "score": round(100 * counts["passed"] / evaluated, 2) if evaluated else None,
        "passed": counts["passed"],
        "failed": counts["failed"],
        "evaluated": evaluated,
        "not_evaluated": counts["not_evaluated"],
        "not_applicable": counts["not_applicable"],
        "total": len(checks),
        "coverage_percent": round(100 * evaluated / eligible, 2) if eligible else None,
    }


def actions_for(findings):
    order = {"critical": 0, "high": 1, "medium": 2, "low": 3}
    horizon = {"low": "quick_win", "medium": "short_term", "high": "medium_term"}
    sorted_findings = sorted(findings, key=lambda f: (order.get(f["severity"], 9), f["rule_id"], f["check_id"]))
    actions = []
    for item in sorted_findings:
        actions.append({
            "id": "ACT-" + item["check_id"],
            "check_id": item["check_id"],
            "rule_id": item["rule_id"],
            "title": item["title"],
            "area": item["area"],
            "pillar": item["pillar"],
            "level": item["level"],
            "severity": item["severity"],
            "severity_label": item["severity_label"],
            "effort": item["effort"],
            "effort_label": item["effort_label"],
            "horizon": horizon.get(item["effort"], "short_term"),
            "status": item["status"],
            "resource_id": item["resource_id"],
            "workload_name": item.get("workload_name", ""),
            "workspace_id": item["workspace_id"],
            "workspace_name": item["workspace_name"],
            "recommendation": item["recommendation"],
            "reason": item["reason"],
            "learn_url": item["learn_url"],
            "estimated_savings": None,
        })
    return actions


def finops_for(raw):
    inv, ws = raw["inventory"], raw["workspace"]
    candidates = []
    for cl in inv.get("clusters", []):
        if cl.get("cluster_source") != "JOB":
            mins = cl.get("autotermination_minutes")
            if not isinstance(mins, (int, float)) or mins <= 0 or mins > 60:
                candidates.append({
                    "id": "FINOPS-CL-" + hashlib.sha256(cl["id"].encode("utf-8")).hexdigest()[:10],
                    "title": "Revisar autoterminación en clúster interactivo All-Purpose",
                    "resource_id": ws["id"] + "/clusters/" + cl["id"],
                    "workload_name": cl["name"],
                    "source_id": cl["source_id"],
                    "basis": "Configuración observada de autotermination_minutes en /api/2.0/clusters/list; sin estimar ahorro DBU.",
                    "value": mins if mins is not None else "disabled",
                    "unit": "minutes",
                    "sample_count": 1,
                    "window": None,
                    "recommendation": "Ajustar autotermination_minutes (<= 60 min) y aplicar Cluster Policy para contener consumo en inactividad.",
                    "estimated_savings": None,
                })
    for job in inv.get("jobs", []):
        ap_tasks = [t["task_key"] for t in job.get("tasks", []) if t.get("existing_cluster_id")]
        if ap_tasks:
            candidates.append({
                "id": "FINOPS-JOB-" + hashlib.sha256(job["id"].encode("utf-8")).hexdigest()[:10],
                "title": "Revisar tareas de Job ejecutando sobre clúster All-Purpose",
                "resource_id": ws["id"] + "/jobs/" + job["id"],
                "workload_name": job["name"],
                "source_id": job["source_id"],
                "basis": "Tareas con existing_cluster_id observadas en /api/2.1/jobs/list; la tarifa DBU de Jobs Compute/Serverless es inferior a All-Purpose.",
                "value": len(ap_tasks),
                "unit": "tasks_on_all_purpose",
                "sample_count": 1,
                "window": None,
                "recommendation": "Evaluar migración de tareas a job_cluster_key o Jobs Serverless tras validar dependencias de librerías e init scripts.",
                "estimated_savings": None,
            })
    for wh in inv.get("sql_warehouses", []):
        mins = wh.get("auto_stop_mins")
        if not isinstance(mins, (int, float)) or mins <= 0 or mins > 30:
            candidates.append({
                "id": "FINOPS-WH-" + hashlib.sha256(wh["id"].encode("utf-8")).hexdigest()[:10],
                "title": "Revisar auto_stop_mins en SQL Warehouse",
                "resource_id": ws["id"] + "/warehouses/" + wh["id"],
                "workload_name": wh["name"],
                "source_id": wh["source_id"],
                "basis": "Configuración auto_stop_mins observada en /api/2.0/sql/warehouses; sin proyectar ahorro monetario.",
                "value": mins if mins is not None else "disabled",
                "unit": "minutes",
                "sample_count": 1,
                "window": None,
                "recommendation": "Redefinir auto_stop_mins <= 30 min o evaluar Serverless SQL Warehouse.",
                "estimated_savings": None,
            })
    cost_rows = raw.get("cost_rows", [])
    currencies = {row["currency"] for row in cost_rows}
    cost_source = next((source for source in raw["sources"] if source["id"] == "azure_cost"), None)
    currency = next(iter(currencies)) if len(currencies) == 1 else None
    total = float(sum((Decimal(str(row["amount"])) for row in cost_rows), Decimal(0))) if currency and pick(cost_source, "status") == "complete" else None
    by_currency = {
        code: float(sum((Decimal(str(row["amount"])) for row in cost_rows if row["currency"] == code), Decimal(0)))
        for code in sorted(currencies)
    }
    return {
        "sources": ["azure_cost", "arm_advisor", "dbx_clusters", "dbx_jobs", "dbx_sql_warehouses"],
        "window": pick(cost_source, "window"),
        "currency": currency,
        "actual_cost": total,
        "cost_rows": cost_rows,
        "candidates": candidates,
        "estimated_savings": None,
        "observed_cost_totals_by_currency": by_currency,
        "cost_source_complete": pick(cost_source, "status") == "complete",
        "notes": [
            "Cluster, warehouse and job configurations are point-in-time control-plane observations, not historical DBU consumption.",
            "These ActualCost rows come only from cost_scope (approved ARM ResourceIds) and are not split by job, notebook or user; the Databricks cost section attributes DBU and infrastructure by Databricks tags.",
            "System table system.billing.usage is queried only when system_tables_warehouse_id is configured (off by default, it consumes DBUs).",
            "Savings on these legacy rows are not computed; the Databricks cost section estimates savings only from observed cost with documented rules.",
        ],
    }


# ---------------------------------------------------------------------------------------------------------------
# Databricks costs: where they come from (Cost Management grouped by Databricks tags) and how to optimise them
# (Databricks REST configuration joined to the observed cost). Optional, off by default: system tables.
# ---------------------------------------------------------------------------------------------------------------

SYSTEM_BILLING_STATEMENT = (
    "WITH u AS (SELECT u.billing_origin_product AS product, u.sku_name AS sku, u.usage_metadata.cluster_id AS cluster_id, "
    "u.usage_metadata.job_id AS job_id, u.usage_metadata.job_run_id AS job_run_id, u.usage_metadata.warehouse_id AS warehouse_id, "
    "u.usage_metadata.dlt_pipeline_id AS pipeline_id, u.identity_metadata.run_as AS run_as, CAST(u.usage_quantity AS DOUBLE) AS dbus, "
    "CAST(u.usage_quantity * lp.pricing.effective_list.default AS DOUBLE) AS list_cost, lp.currency_code AS currency "
    "FROM system.billing.usage u LEFT JOIN system.billing.list_prices lp ON lp.sku_name = u.sku_name AND lp.cloud = u.cloud "
    "AND lp.usage_unit = u.usage_unit AND u.usage_end_time >= lp.price_start_time "
    "AND (lp.price_end_time IS NULL OR u.usage_end_time < lp.price_end_time) "
    "WHERE u.workspace_id = :workspace_id AND u.usage_date >= :start_date AND u.usage_date < :end_date AND u.usage_unit = 'DBU'), "
    "runs AS (SELECT 'run' AS row_type, product, sku, cluster_id, job_id, job_run_id, warehouse_id, pipeline_id, run_as, "
    "SUM(dbus) AS dbus, SUM(list_cost) AS list_cost, MAX(currency) AS currency FROM u "
    "GROUP BY product, sku, cluster_id, job_id, job_run_id, warehouse_id, pipeline_id, run_as ORDER BY list_cost DESC NULLS LAST LIMIT 300), "
    "users AS (SELECT 'user' AS row_type, CAST(NULL AS STRING) AS product, CAST(NULL AS STRING) AS sku, CAST(NULL AS STRING) AS cluster_id, "
    "CAST(NULL AS STRING) AS job_id, CAST(NULL AS STRING) AS job_run_id, CAST(NULL AS STRING) AS warehouse_id, CAST(NULL AS STRING) AS pipeline_id, "
    "run_as, SUM(dbus) AS dbus, SUM(list_cost) AS list_cost, MAX(currency) AS currency FROM u GROUP BY run_as "
    "ORDER BY list_cost DESC NULLS LAST LIMIT 100), "
    "products AS (SELECT 'product' AS row_type, product, sku, CAST(NULL AS STRING) AS cluster_id, CAST(NULL AS STRING) AS job_id, "
    "CAST(NULL AS STRING) AS job_run_id, CAST(NULL AS STRING) AS warehouse_id, CAST(NULL AS STRING) AS pipeline_id, CAST(NULL AS STRING) AS run_as, "
    "SUM(dbus) AS dbus, SUM(list_cost) AS list_cost, MAX(currency) AS currency FROM u GROUP BY product, sku) "
    "SELECT * FROM runs UNION ALL SELECT * FROM users UNION ALL SELECT * FROM products"
)
COST_LEARN = {
    "autotermination": "https://learn.microsoft.com/azure/databricks/compute/clusters-manage#automatic-termination",
    "jobs_compute": "https://learn.microsoft.com/azure/databricks/jobs/compute",
    "spot": "https://learn.microsoft.com/azure/databricks/compute/configure#spot-instances",
    "policies": "https://learn.microsoft.com/azure/databricks/admin/clusters/policies",
    "tags": "https://learn.microsoft.com/azure/databricks/admin/account-settings/usage-detail-tags",
    "runtime": "https://learn.microsoft.com/azure/databricks/release-notes/runtime/",
    "node_types": "https://learn.microsoft.com/azure/databricks/compute/cluster-config-best-practices",
    "pools": "https://learn.microsoft.com/azure/databricks/compute/pool-best-practices",
    "warehouse": "https://learn.microsoft.com/azure/databricks/compute/sql-warehouse/create",
    "photon": "https://learn.microsoft.com/azure/databricks/compute/photon",
    "streaming": "https://learn.microsoft.com/azure/databricks/jobs/continuous",
    "billing": "https://learn.microsoft.com/azure/databricks/admin/system-tables/billing",
    "cost_best_practices": "https://learn.microsoft.com/azure/databricks/lakehouse-architecture/cost-optimization/best-practices",
}
AP_SOURCES_EXCLUDED = ("JOB", "PIPELINE", "PIPELINE_MAINTENANCE", "SQL", "MODELS")
OLD_NODE_RE = re.compile(r"^Standard_(?:DS?\d+[a-z]*_v[23]|DS?\d+|F\d+s?|L\d+s|E\d+[a-z]*_v3|NC\d+[a-z]*(?:_v2)?|NV\d+[a-z]*)$", re.IGNORECASE)


def _month_start(day):
    return day.replace(day=1)


def cost_periods(reference):
    today = datetime.fromisoformat(reference.replace("Z", "+00:00")).date()
    current = _month_start(today)
    review_end = current - timedelta(days=1)
    review = _month_start(review_end)
    previous = _month_start(review - timedelta(days=1))
    weekend = sum((review + timedelta(days=i)).weekday() >= 5 for i in range(review_end.day))
    return {
        "today": today, "current_start": current, "review_start": review, "review_end": review_end, "previous_start": previous,
        "labels": {
            "current": current.strftime("%Y-%m"), "review": review.strftime("%Y-%m"), "previous": previous.strftime("%Y-%m"),
            "review_days": review_end.day, "review_weekend_days": weekend, "mtd_days": today.day,
            "current_month_days": ((current + timedelta(days=32)).replace(day=1) - timedelta(days=1)).day,
        },
    }


def cost_query_body(start, end, granularity, grouping, scope_filter, extra=None):
    return {
        "type": COST_METRIC,
        "timeframe": "Custom",
        "timePeriod": {"from": start.isoformat() + "T00:00:00Z", "to": end.isoformat() + "T23:59:59Z"},
        "dataset": {
            "granularity": granularity,
            "aggregation": {"totalCost": {"name": "Cost", "function": "Sum"}},
            "grouping": grouping,
            "filter": scope_filter if extra is None else {"and": [scope_filter, extra]},
        },
    }


def parse_cost_payload(payload, source):
    props = obj(obj(payload, source).get("properties"), source)
    columns = [text(column.get("name"), source, 128) for column in array(props.get("columns"), source)]
    index = {name: i for i, name in enumerate(columns)}
    amount_column = next((name for name in ("Cost", "PreTaxCost", "CostUSD") if name in index), None)
    rows = props.get("rows")
    if amount_column is None or "Currency" not in index or not isinstance(rows, list):
        raise EvidenceError("invalid_cost_shape", "Cost Management returned no amount/currency columns.", source)
    parsed = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(columns):
            raise EvidenceError("invalid_cost_shape", "Cost row/column lengths differ.", source)
        amount = row[index[amount_column]]
        if isinstance(amount, bool) or not isinstance(amount, (int, float)) or not math.isfinite(amount):
            raise EvidenceError("invalid_cost_amount", "Cost amount is absent or not finite; it is not zero.", source)
        if "BillingMonth" in index:
            period = str(row[index["BillingMonth"]])[:7]
        elif "UsageDate" in index:
            raw_day = str(row[index["UsageDate"]])
            period = raw_day[:4] + "-" + raw_day[4:6] + "-" + raw_day[6:8] if re.fullmatch(r"[0-9]{8}", raw_day) else raw_day[:10]
        else:
            period = None
        key = row[index["TagValue"]] if "TagValue" in index else None
        key = text(str(key), source, 512) if key not in (None, "") else None
        category = text(str(row[index["MeterCategory"]]), source, 256) if "MeterCategory" in index and row[index["MeterCategory"]] is not None else None
        meter = text(str(row[index["Meter"]]), source, 256) if "Meter" in index and row[index["Meter"]] is not None else None
        currency = text(str(row[index["Currency"]]), source, 8)
        parsed.append([period, key, category, meter, round(float(amount), 6), currency])
    return parsed, props.get("nextLink")


def ap_clusters(inventory):
    return [
        c for c in inventory.get("clusters", [])
        if c.get("kind") == "AllPurposeCluster" and (c.get("cluster_source") or "UI").upper() not in AP_SOURCES_EXCLUDED
    ]


def cost_query_plan(periods, scope_filter, inventory):
    review, review_end, previous = periods["review_start"], periods["review_end"], periods["previous_start"]
    by_meter = [{"type": "Dimension", "name": "MeterCategory"}]
    plan = [
        ("meter", cost_query_body(previous, periods["today"], "Monthly", by_meter + [{"type": "Dimension", "name": "Meter"}], scope_filter)),
        ("vendor", cost_query_body(previous, review_end, "Monthly", [{"type": "TagKey", "name": "Vendor"}] + by_meter, scope_filter)),
    ]
    for dimension, tag in COST_DIMENSIONS:
        plan.append((dimension, cost_query_body(previous, review_end, "Monthly", [{"type": "TagKey", "name": tag}] + by_meter, scope_filter)))
    for tag in COST_ALLOCATION_TAGS:
        plan.append(("tag:" + tag, cost_query_body(previous, review_end, "Monthly", [{"type": "TagKey", "name": tag}] + by_meter, scope_filter)))
    names = sorted({c["name"] for c in ap_clusters(inventory) if c.get("name")})[:MAX_COST_DAILY_KEYS]
    if names:
        plan.append(("daily_cluster", cost_query_body(review, review_end, "Daily", [{"type": "TagKey", "name": "ClusterName"}], scope_filter,
                                                      {"tags": {"name": "ClusterName", "operator": "In", "values": names}})))
    pools = sorted({p["id"] for p in inventory.get("instance_pools", []) if (p.get("min_idle_instances") or 0) > 0})[:MAX_COST_DAILY_KEYS]
    if pools:
        plan.append(("daily_pool", cost_query_body(review, review_end, "Daily", [{"type": "TagKey", "name": "DatabricksInstancePoolId"}], scope_filter,
                                                   {"tags": {"name": "DatabricksInstancePoolId", "operator": "In", "values": pools}})))
    return plan


def collect_databricks_costs(identity, config, reference, workspace, inventory):
    periods = cost_periods(reference)
    labels = periods["labels"]
    receipt = source_receipt(
        "azure_cost_databricks", reference, "not_configured",
        "Databricks cost analysis is disabled in configuration (cost_analysis_enabled=False).",
        window={"start": periods["previous_start"].isoformat() + "T00:00:00Z", "end": reference},
        metric=COST_METRIC, queries=[], pagination_complete=False,
    )
    if not config.get("cost_analysis_enabled", True):
        return None, receipt
    url = ARM_ORIGIN + "/subscriptions/" + SUBSCRIPTION_ID + "/providers/Microsoft.CostManagement/query?api-version=" + COST_API_VERSION
    reader = HttpReader(identity, ARM_ORIGIN, "arm", patient=True)
    reader.allow(url, "POST")
    resource_ids = [config["id"].lower()] + [rid.lower() for rid in config.get("approved_cost_resource_ids", []) if rid.lower() != config["id"].lower()]
    managed_rg = workspace.get("managed_resource_group") if isinstance(workspace, dict) else None
    parts = [{"dimensions": {"name": "ResourceId", "operator": "In", "values": resource_ids}}]
    if managed_rg:
        parts.append({"dimensions": {"name": "ResourceGroupName", "operator": "In", "values": [managed_rg.lower()]}})
    scope_filter = parts[0] if len(parts) == 1 else {"or": parts}
    data = {
        "metric": COST_METRIC, "periods": labels, "queries": {},
        "scope": {"subscription_id": SUBSCRIPTION_ID, "resource_ids": resource_ids, "managed_resource_group": managed_rg},
    }
    for qid, body in cost_query_plan(periods, scope_filter, inventory):
        started, rows, pages, error, status = time.monotonic(), [], 0, None, "complete"
        if identity.deadline - started < COST_QUERY_RESERVE_SECONDS:
            error = EvidenceError("collection_deadline", "Collection time bound reached before this cost query; it is missing, not zero.", "azure_cost_databricks").public()
            data["queries"][qid] = {"status": "skipped", "rows": [], "pages": 0, "seconds": 0.0, "error": error}
            continue
        current, seen = url, set()
        try:
            while True:
                if current in seen:
                    raise EvidenceError("pagination_loop", "Cost query repeated a continuation.", "azure_cost_databricks")
                seen.add(current)
                payload = reader.request("POST", current, "azure_cost_databricks", body=body)
                pages += 1
                parsed, link = parse_cost_payload(payload, "azure_cost_databricks")
                rows.extend(parsed)
                if len(rows) > MAX_COST_ROWS:
                    raise EvidenceError("row_cap", "Cost rows exceeded the safety bound; the query is partial.", "azure_cost_databricks")
                if not link:
                    break
                if pages >= MAX_PAGES:
                    raise EvidenceError("page_cap", "Cost query page safety cap reached.", "azure_cost_databricks")
                current = next_arm_link(link, url)
        except (EvidenceError, ValueError) as exc:
            failure = exc if isinstance(exc, EvidenceError) else EvidenceError("invalid_cost_shape", "Cost data could not be parsed.", "azure_cost_databricks")
            error = failure.public()
            status = "partial" if rows else "denied" if failure.http_status in (401, 403) else "error"
        data["queries"][qid] = {"status": status, "rows": rows, "pages": pages, "seconds": round(time.monotonic() - started, 1), "error": error}
    statuses = [q["status"] for q in data["queries"].values()]
    overall = (
        "complete" if all(s == "complete" for s in statuses)
        else "partial" if any(s in ("complete", "partial") for s in statuses)
        else "denied" if statuses and statuses[0] == "denied"
        else "error"
    )
    receipt.update(
        status=overall,
        records=sum(len(q["rows"]) for q in data["queries"].values()),
        pages=sum(q["pages"] for q in data["queries"].values()),
        pagination_complete=overall == "complete",
        scope="/subscriptions/" + SUBSCRIPTION_ID,
        read_signature="POST " + url,
        queries=[{"id": qid, "status": q["status"], "records": len(q["rows"]), "seconds": q["seconds"]} for qid, q in data["queries"].items()],
        errors=[q["error"] for q in data["queries"].values() if q["error"]][:3],
        note=(
            "Cost Management grouped by Databricks tags (ClusterName, JobId, SqlEndpointId, DatabricksInstancePoolId, Vendor and "
            + (", ".join(COST_ALLOCATION_TAGS) or "no allocation tags") + ") for the workspace resource and its managed resource group."
            if overall != "denied" else
            "The identity cannot read cost: grant Cost Management Reader (or Reader) on the subscription."
        ),
    )
    return data, receipt


def collect_system_billing(identity, config, reference, workspace):
    periods = cost_periods(reference)
    receipt = source_receipt(
        "dbx_system_billing", reference, "not_configured",
        "Off by default: system.billing.usage + list_prices through the Statement Execution API on an existing SQL warehouse "
        "(it consumes DBUs). Set system_tables_warehouse_id to enable per-run and per-user detail.",
    )
    warehouse = config.get("system_tables_warehouse_id") or ""
    if not warehouse or not config["workspace_api_enabled"]:
        return None, receipt
    workspace_number = (workspace or {}).get("workspace_guid") or ""
    if not re.fullmatch(r"[0-9]{6,24}", str(workspace_number)):
        match = re.match(r"adb-([0-9]{6,24})\.", config["workspace_host"])
        workspace_number = match.group(1) if match else ""
    if not workspace_number:
        receipt.update(status="error", errors=[EvidenceError("workspace_id_unknown", "The numeric workspace ID is unknown; system tables were not queried.", "dbx_system_billing").public()])
        return None, receipt
    reader = StatementReader(identity, "https://" + config["workspace_host"])
    url = reader.allow(reader.origin + StatementReader.PATH, "POST")
    body = {
        "warehouse_id": warehouse, "statement": SYSTEM_BILLING_STATEMENT, "wait_timeout": "50s", "on_wait_timeout": "CANCEL",
        "disposition": "INLINE", "format": "JSON_ARRAY",
        "parameters": [
            {"name": "workspace_id", "value": str(workspace_number), "type": "STRING"},
            {"name": "start_date", "value": periods["review_start"].isoformat(), "type": "DATE"},
            {"name": "end_date", "value": periods["current_start"].isoformat(), "type": "DATE"},
        ],
    }
    receipt.update(read_signature="POST " + url, warehouse_id=warehouse, window={"start": periods["review_start"].isoformat(), "end": periods["current_start"].isoformat()})
    try:
        payload = obj(reader.request("POST", url, "dbx_system_billing", body=body), "dbx_system_billing")
        state = pick(payload, "status", "state")
        if state != "SUCCEEDED":
            message = text(pick(payload, "status", "error", "message"), "dbx_system_billing", 400) or ""
            raise EvidenceError("statement_" + str(state or "unknown").lower(), ("Statement state " + str(state) + ". " + message).strip(), "dbx_system_billing")
        columns = [text(c.get("name"), "dbx_system_billing", 64) for c in array(pick(payload, "manifest", "schema", "columns") or [], "dbx_system_billing")]
        data_rows = pick(payload, "result", "data_array") or []
        if not isinstance(data_rows, list):
            raise EvidenceError("invalid_shape", "Statement result is not an array.", "dbx_system_billing")
        rows = []
        for item in data_rows[:600]:
            if not isinstance(item, list) or len(item) != len(columns):
                raise EvidenceError("invalid_shape", "Statement row/column lengths differ.", "dbx_system_billing")
            record = {}
            for name, value in zip(columns, item):
                if name in ("dbus", "list_cost"):
                    try:
                        record[name] = round(float(value), 4) if value not in (None, "") else None
                    except (TypeError, ValueError):
                        record[name] = None
                else:
                    record[name] = text(str(value), "dbx_system_billing", 256) if value is not None else None
            rows.append(record)
        receipt.update(status="complete", records=len(rows), pages=1, truncated=bool(pick(payload, "manifest", "truncated")))
        return {"warehouse_id": warehouse, "window": receipt["window"], "rows": rows, "truncated": receipt["truncated"]}, receipt
    except EvidenceError as exc:
        receipt.update(status="denied" if exc.http_status in (401, 403) else "error", errors=[exc.public()])
        return None, receipt


def dbu_family(meter):
    m = (meter or "").lower()
    for family, words in (
        ("sql_serverless", ("serverless sql",)), ("sql", ("sql",)), ("pipelines", ("dlt", "delta live", "pipeline")),
        ("jobs_light", ("jobs light",)), ("serverless", ("serverless",)), ("jobs", ("jobs", "automated")),
        ("all_purpose", ("all-purpose", "all purpose", "interactive")), ("ai", ("serving", "inference", "vector", "model", "foundation")),
    ):
        if any(word in m for word in words):
            return family
    return "other"


def _money(value):
    return round(value, 2) if isinstance(value, (int, float)) else None


def es_amount(value, decimals=0):
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        return "—"
    formatted = format(round(value, decimals), "," + "." + str(decimals) + "f")
    return formatted.replace(",", "\x00").replace(".", ",").replace("\x00", ".")


def es_month(label):
    names = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre")
    match = re.fullmatch(r"(\d{4})-(\d{2})", str(label or ""))
    return names[int(match.group(2)) - 1] + " de " + match.group(1) if match and 1 <= int(match.group(2)) <= 12 else str(label)


def _pct(part, whole):
    return round(100.0 * part / whole, 1) if isinstance(part, (int, float)) and isinstance(whole, (int, float)) and whole > 0 else None


def _vm_meter(node_type):
    return (node_type or "").replace("Standard_", "").replace("_", " ").lower()


def cost_tables(data, labels):
    """Aggregate every Cost Management query result in the dominant billing currency."""
    queries = data.get("queries", {})
    totals = {}
    for q in queries.values():
        for period, key, category, meter, amount, currency in q["rows"]:
            totals[currency] = totals.get(currency, 0.0) + abs(amount)
    currency = max(totals, key=totals.get) if totals else None
    review, previous, current = labels["review"], labels["previous"], labels["current"]
    rows = {qid: [r for r in q["rows"] if r[5] == currency] for qid, q in queries.items()}
    is_dbu = lambda category: (category or "").lower() == "azure databricks"

    def by_key(qid):
        out = {}
        for period, key, category, meter, amount, _ in rows.get(qid, []):
            slot = out.setdefault(key, {"dbu": 0.0, "infra": 0.0, "vm": 0.0, "review": 0.0, "previous": 0.0, "categories": {}})
            if period == review:
                slot["review"] += amount
                slot["dbu" if is_dbu(category) else "infra"] += amount
                if (category or "").lower() == "virtual machines":
                    slot["vm"] += amount
                slot["categories"][category or "—"] = slot["categories"].get(category or "—", 0.0) + amount
            elif period == previous:
                slot["previous"] += amount
        return out

    months = {label: {"dbu": 0.0, "infra": 0.0} for label in (previous, review, current)}
    families, categories, vm_sizes = {}, {}, {}
    for period, _, category, meter, amount, _ in rows.get("meter", []):
        if period not in months:
            continue
        months[period]["dbu" if is_dbu(category) else "infra"] += amount
        if is_dbu(category):
            slot = families.setdefault(dbu_family(meter), {"review": 0.0, "previous": 0.0, "meters": {}})
            if period in (review, previous):
                slot[period == review and "review" or "previous"] += amount
            if period == review:
                slot["meters"][meter or "—"] = slot["meters"].get(meter or "—", 0.0) + amount
        else:
            slot = categories.setdefault(category or "—", {"review": 0.0, "previous": 0.0})
            if period in (review, previous):
                slot[period == review and "review" or "previous"] += amount
            if period == review and (category or "").lower() == "virtual machines":
                vm_sizes[meter or "—"] = vm_sizes.get(meter or "—", 0.0) + amount
    daily = {}
    for qid in ("daily_cluster", "daily_pool"):
        per_key = {}
        for period, key, _, _, amount, _ in rows.get(qid, []):
            if key is None or not period or len(period) != 10:
                continue
            day = per_key.setdefault(key, {})
            day[period] = day.get(period, 0.0) + amount
        daily[qid] = per_key
    return {
        "currency": currency,
        "other_currencies": sorted(c for c in totals if c != currency),
        "months": months, "families": families, "categories": categories, "vm_sizes": vm_sizes, "daily": daily,
        "dimensions": {qid: by_key(qid) for qid in queries if qid not in ("meter", "daily_cluster", "daily_pool")},
        "query_status": {qid: q["status"] for qid, q in queries.items()},
    }


def daily_profile(days, labels, start):
    if not days:
        return None
    weekend = sum(v for d, v in days.items() if datetime.strptime(d, "%Y-%m-%d").weekday() >= 5)
    active = [v for v in days.values() if v > 0.01]
    floor = min(days.get((start + timedelta(days=i)).isoformat(), 0.0) for i in range(labels["review_days"]))
    return {"active_days": len(active), "weekend_cost": round(weekend, 2), "floor": round(max(floor, 0.0), 2), "total": round(sum(days.values()), 2)}


def cost_signals(inventory, catalog, tables, labels, periods, reference):
    """Optimisation signals from observed configuration, each with the observed cost of its object and, where the
    cost data allows it, an estimated monthly saving with a documented rule."""
    dims = tables["dimensions"] if tables else {}
    clusters_cost, jobs_cost = dims.get("cluster", {}), dims.get("job", {})
    pools_cost, warehouses_cost = dims.get("pool", {}), dims.get("warehouse", {})
    daily = tables["daily"] if tables else {}
    ref_ms = datetime.fromisoformat(reference.replace("Z", "+00:00")).timestamp() * 1000
    tags_wanted = [t.lower() for t in COST_ALLOCATION_TAGS]
    weekend_share = labels["review_weekend_days"] / max(1, labels["review_days"])
    signals = []

    def add(code, severity, title, kind, oid, name, evidence, cost, saving, saving_kind, basis, recommendation, learn, effort="L"):
        signals.append({
            "id": "COST-" + code + "-" + hashlib.sha256((kind + "|" + str(oid)).encode("utf-8")).hexdigest()[:10],
            "code": code, "severity": severity, "title": title, "object_kind": kind, "object_id": str(oid), "object_name": name,
            "evidence": evidence, "monthly_cost": _money(cost), "estimated_monthly_saving": _money(saving) if saving and saving > 0.5 else None,
            "saving_kind": saving_kind if saving and saving > 0.5 else None, "saving_basis": basis if saving and saving > 0.5 else None,
            "recommendation": recommendation, "learn_url": COST_LEARN[learn], "effort": effort, "counted": False,
        })

    def total(slot):
        return slot["review"] if slot else None

    def workers(spec):
        if isinstance(spec.get("autoscale"), dict) and spec["autoscale"].get("max_workers"):
            return ((spec["autoscale"].get("min_workers") or 0) + spec["autoscale"]["max_workers"]) / 2.0
        return spec.get("num_workers") or spec.get("autoscale_max_workers") or 0

    def workers_label(spec):
        auto = spec.get("autoscale") if isinstance(spec.get("autoscale"), dict) else None
        if auto and auto.get("max_workers"):
            return str(auto.get("min_workers") or 0) + "–" + str(auto["max_workers"]) + " (autoescalado)"
        if spec.get("autoscale_max_workers") and not spec.get("num_workers"):
            return "hasta " + str(spec["autoscale_max_workers"]) + " (autoescalado)"
        return spec.get("num_workers")

    def missing_tags(tags):
        present = {k.lower() for k in (tags or {})}
        return [t for t in COST_ALLOCATION_TAGS if t.lower() not in present]

    ap = ap_clusters(inventory)
    for c in ap:
        slot = clusters_cost.get(c["name"])
        mins = c.get("autotermination_minutes")
        off = not isinstance(mins, (int, float)) or mins <= 0
        if off or mins > COST_AUTOTERMINATION_MAX_MINUTES:
            since = c.get("last_restarted_time") or c.get("start_time")
            uptime = round((ref_ms - since) / 3.6e6) if c.get("state") == "RUNNING" and isinstance(since, (int, float)) and since < ref_ms else None
            profile = daily_profile(daily.get("daily_cluster", {}).get(c["name"]), labels, periods["review_start"])
            saving = profile["weekend_cost"] if off and profile and profile["weekend_cost"] > 0 else None
            add("AUTOTERM_OFF" if off else "AUTOTERM_LONG", "high" if off else "medium",
                "Clúster interactivo sin autoterminación" if off else "Autoterminación larga en clúster interactivo",
                "AllPurposeCluster", c["id"], c["name"],
                {"autotermination_minutes": 0 if off else mins, "state": c.get("state"), "uptime_hours": uptime,
                 "active_days": profile and profile["active_days"], "weekend_cost": profile and profile["weekend_cost"]},
                total(slot), saving, "lower_bound", "weekend_cost",
                "Configurar autotermination_minutes en " + str(min(30, COST_AUTOTERMINATION_MAX_MINUTES)) + " minutos o menos y fijarlo con una política de cómputo.",
                "autotermination")
        w = workers(c)
        if w and not c.get("instance_pool_id") and not str(c.get("azure_availability") or "ON_DEMAND_AZURE").upper().startswith("SPOT"):
            saving = slot["vm"] * w / (w + 1.0) * COST_SPOT_DISCOUNT if slot and slot["vm"] else None
            add("NO_SPOT", "low", "Workers sin instancias spot en clúster interactivo", "AllPurposeCluster", c["id"], c["name"],
                {"availability": c.get("azure_availability") or "ON_DEMAND_AZURE", "workers": workers_label(c), "vm_cost": slot and _money(slot["vm"])},
                total(slot), saving, "estimate", "spot_discount",
                "Usar SPOT_WITH_FALLBACK_AZURE en los workers (first_on_demand=1 mantiene el driver bajo demanda) si la carga tolera reintentos.",
                "spot")
    by_cluster = {}
    for job in inventory.get("jobs", []):
        if not job.get("scheduled") or job.get("schedule_paused"):
            continue
        for task in job.get("tasks", []):
            if task.get("existing_cluster_id"):
                by_cluster.setdefault(task["existing_cluster_id"], set()).add(job["name"])
    for cid, names in sorted(by_cluster.items()):
        cluster = next((c for c in inventory.get("clusters", []) if c["id"] == cid), None)
        name = cluster["name"] if cluster else cid
        slot = clusters_cost.get(name)
        saving = slot["dbu"] * (1 - COST_JOBS_TO_ALL_PURPOSE_DBU_RATIO) if slot and slot["dbu"] else None
        add("JOBS_ON_ALL_PURPOSE", "high", "Jobs programados en cómputo interactivo (all-purpose)", "AllPurposeCluster", cid, name,
            {"jobs": sorted(names)[:6], "jobs_count": len(names), "dbu_cost": slot and _money(slot["dbu"])},
            total(slot), saving, "upper_bound", "jobs_dbu_ratio",
            "Mover las tareas a cómputo de jobs (job_cluster_key) o serverless: la DBU de jobs cuesta en torno a un "
            + str(round(100 * (1 - COST_JOBS_TO_ALL_PURPOSE_DBU_RATIO))) + " % menos que la all-purpose.",
            "jobs_compute", "M")
    for job in inventory.get("jobs", []):
        slot = jobs_cost.get(job["id"])
        on_demand = [jc for jc in job.get("job_clusters", []) if workers(jc) and not jc.get("instance_pool_id")
                     and not str(jc.get("azure_availability") or "ON_DEMAND_AZURE").upper().startswith("SPOT")]
        if on_demand:
            top = max(on_demand, key=workers)
            w = workers(top)
            saving = slot["vm"] * w / (w + 1.0) * COST_SPOT_DISCOUNT if slot and slot["vm"] else None
            add("NO_SPOT", "medium", "Clúster de job sin instancias spot", "Job", job["id"], job["name"],
                {"availability": "ON_DEMAND_AZURE", "workers": workers_label(top), "vm_cost": slot and _money(slot["vm"]), "continuous": job.get("continuous")},
                total(slot), saving, "estimate", "spot_discount",
                "Usar SPOT_WITH_FALLBACK_AZURE en los workers del job cluster; mantener el driver bajo demanda.", "spot")
        if job.get("continuous"):
            add("CONTINUOUS_JOB", "medium", "Job continuo: cómputo encendido todo el mes", "Job", job["id"], job["name"],
                {"continuous": True}, total(slot), None, None, None,
                "Confirmar que necesita latencia continua; si no, usar disparadores programados o por llegada de ficheros.", "streaming", "M")
        big = [jc for jc in job.get("job_clusters", []) if (jc.get("autoscale_max_workers") or jc.get("num_workers") or 0) >= 8
               and str(jc.get("runtime_engine") or "").upper() != "PHOTON"]
        if big:
            add("PHOTON_CANDIDATE", "low", "Job grande sin Photon: evaluar", "Job", job["id"], job["name"],
                {"max_workers": max(jc.get("autoscale_max_workers") or jc.get("num_workers") or 0 for jc in big)},
                total(slot), None, None, None,
                "Probar Photon en una ejecución: cuesta más DBU por hora pero suele terminar antes en SQL y ETL.", "photon", "M")
    for pool in inventory.get("instance_pools", []):
        slot = pools_cost.get(pool["id"])
        idle_min = pool.get("min_idle_instances") or 0
        if idle_min > 0:
            profile = daily_profile(daily.get("daily_pool", {}).get(pool["id"]), labels, periods["review_start"])
            saving = profile["floor"] * labels["review_days"] if profile and profile["floor"] > 0 else None
            add("POOL_IDLE", "medium", "Pool con instancias inactivas siempre encendidas", "InstancePool", pool["id"], pool["name"],
                {"min_idle_instances": idle_min, "idle_now": (pool.get("stats") or {}).get("idle_count"),
                 "idle_autotermination_minutes": pool.get("idle_instance_autotermination_minutes"), "daily_floor": profile and profile["floor"]},
                total(slot), saving, "estimate", "daily_floor",
                "Bajar min_idle_instances a 0 (o al mínimo justificado) y la autoterminación de inactivas a 10-15 minutos.", "pools")
    for wh in inventory.get("sql_warehouses", []):
        slot = warehouses_cost.get(wh["id"])
        mins = wh.get("auto_stop_mins")
        if not isinstance(mins, (int, float)) or mins <= 0 or mins > COST_WAREHOUSE_AUTOSTOP_MAX_MINUTES:
            never = not isinstance(mins, (int, float)) or mins <= 0
            saving = slot["review"] * weekend_share if never and slot and slot["review"] else None
            add("WAREHOUSE_AUTOSTOP", "high" if never else "medium",
                "SQL warehouse sin auto-stop" if never else "Auto-stop largo en SQL warehouse", "SqlWarehouse", wh["id"], wh["name"],
                {"auto_stop_mins": mins or 0, "state": wh.get("state"), "serverless": wh.get("enable_serverless_compute")},
                total(slot), saving, "estimate", "always_on_weekends",
                "Configurar auto-stop en 10-" + str(COST_WAREHOUSE_AUTOSTOP_MAX_MINUTES) + " minutos (serverless arranca en segundos).", "warehouse")
        if wh.get("enable_serverless_compute") is not True:
            add("WAREHOUSE_SERVERLESS", "low", "SQL warehouse clásico o pro: evaluar serverless", "SqlWarehouse", wh["id"], wh["name"],
                {"warehouse_type": wh.get("warehouse_type"), "cluster_size": wh.get("cluster_size")}, total(slot), None, None, None,
                "Evaluar serverless: arranque en segundos, auto-stop corto y sin VM en vuestra suscripción.", "warehouse")
    no_policy = [c for c in ap if not c.get("policy_id")]
    if no_policy:
        cost = sum(clusters_cost[c["name"]]["review"] for c in no_policy if c["name"] in clusters_cost)
        add("NO_POLICY", "low", "Clústeres interactivos sin política de cómputo", "AllPurposeCluster", "no-policy",
            str(len(no_policy)) + (" clúster" if len(no_policy) == 1 else " clústeres"),
            {"objects": [c["name"] for c in no_policy][:8]}, cost, None, None, None,
            "Asignar una política que fije autoterminación, tamaños, spot y etiquetas de imputación.", "policies")
    if tags_wanted:
        weak = [p for p in inventory.get("cluster_policies", []) if p.get("enforced_tag_keys") is not None
                and [t for t in tags_wanted if t not in {k.lower() for k in p["enforced_tag_keys"]}]]
        if weak:
            add("POLICY_TAGS", "medium", "Políticas que no obligan las etiquetas de imputación", "ClusterPolicy", "policy-tags",
                str(len(weak)) + (" política" if len(weak) == 1 else " políticas"),
                {"objects": [p["name"] for p in weak][:8], "allocation_tags": COST_ALLOCATION_TAGS}, None, None, None, None,
                "Añadir custom_tags." + COST_ALLOCATION_TAGS[0] + " (y las demás) como etiquetas fijas u obligatorias en cada política.", "policies")
        groups = (
            ("AllPurposeCluster", ("clúster interactivo", "clústeres interactivos"), [(c["name"], c.get("custom_tags"), total(clusters_cost.get(c["name"]))) for c in ap]),
            ("Job", ("job", "jobs"), [(j["name"], job_effective_tags(j), total(jobs_cost.get(j["id"])))
                                       for j in inventory.get("jobs", []) if j.get("job_clusters")]),
            ("InstancePool", ("pool", "pools"), [(p["name"], p.get("custom_tags"), total(pools_cost.get(p["id"]))) for p in inventory.get("instance_pools", [])]),
            ("SqlWarehouse", ("SQL warehouse", "SQL warehouses"), [(w["name"], w.get("custom_tags"), total(warehouses_cost.get(w["id"]))) for w in inventory.get("sql_warehouses", [])]),
        )
        for kind, labels, items in groups:
            missing = [(name, cost, missing_tags(tags)) for name, tags, cost in items if missing_tags(tags)]
            if missing:
                cost = sum(c for _, c, _ in missing if c)
                untagged = sum(1 for _, _, m in missing if len(m) == len(COST_ALLOCATION_TAGS))
                add("MISSING_ALLOCATION_TAGS", "medium" if cost else "low",
                    ("Sin etiquetas de imputación en " if untagged == len(missing) else "Etiquetas de imputación incompletas en ") + labels[1],
                    kind, "tags-" + kind, str(len(missing)) + " " + labels[len(missing) != 1],
                    {"objects": [n + " (falta " + ", ".join(m) + ")" for n, _, m in missing][:8], "allocation_tags": COST_ALLOCATION_TAGS},
                    cost or None, None, None, None,
                    {
                        "AllPurposeCluster": "Añadir las etiquetas que faltan en custom_tags de cada clúster y hacerlas obligatorias con una política de cómputo.",
                        "Job": "Añadir las etiquetas que faltan como etiquetas del job (se propagan a sus job clusters) o en custom_tags del job cluster.",
                        "InstancePool": "Añadir las etiquetas que faltan en custom_tags del pool: sus VM solo heredan las etiquetas del pool, no las del clúster.",
                        "SqlWarehouse": "Añadir las etiquetas que faltan en las etiquetas del SQL warehouse.",
                    }[kind] + " Etiquetas: " + ", ".join(COST_ALLOCATION_TAGS) + ".",
                    "tags")
    versions = set((catalog or {}).get("spark_versions") or [])
    by_version, by_node = {}, {}
    specs = [(c["name"], c.get("spark_version"), c.get("node_type_id"), clusters_cost.get(c["name"])) for c in ap]
    specs += [(j["name"], jc.get("spark_version"), jc.get("node_type_id"), None) for j in inventory.get("jobs", []) for jc in j.get("job_clusters", [])]
    specs += [(p["name"], None, p.get("node_type_id"), None) for p in inventory.get("instance_pools", [])]
    for name, version, node, _ in specs:
        major = re.match(r"^(\d+)\.", version or "")
        if version and ((versions and version not in versions) or (not versions and major and int(major.group(1)) < 13)):
            by_version.setdefault(version, set()).add(name)
        info = ((catalog or {}).get("node_types") or {}).get(node) or {}
        if node and (info.get("is_deprecated") or OLD_NODE_RE.match(node)):
            by_node.setdefault(node, set()).add(name)
    for version, names in sorted(by_version.items()):
        add("RUNTIME_EOS", "medium", "Runtime fuera de soporte" if versions else "Runtime antiguo", "Runtime", version, version,
            {"objects": sorted(names)[:8], "supported_list_checked": bool(versions)}, None, None, None, None,
            "Actualizar a una versión LTS soportada (más rendimiento por DBU y parches de seguridad).", "runtime", "M")
    vm_sizes = tables["vm_sizes"] if tables else {}
    for node, names in sorted(by_node.items()):
        size = _vm_meter(node)
        cost = sum(v for meter, v in vm_sizes.items() if (meter or "").lower().startswith(size)) if vm_sizes else None
        add("OLD_NODE_FAMILY", "low", "Familia de VM antigua o retirada", "NodeType", node, node,
            {"objects": sorted(names)[:8], "deprecated": bool(((catalog or {}).get("node_types") or {}).get(node, {}).get("is_deprecated"))},
            cost or None, None, None, None,
            "Comparar con la generación actual (por ejemplo Dds_v5 o Eds_v5): suele dar más rendimiento por euro.", "node_types", "M")
    best = {}
    for s in signals:
        if s["estimated_monthly_saving"]:
            key = s["object_kind"] + "|" + s["object_id"] if s["object_kind"] != "Job" else "Job|" + s["object_id"]
            if key not in best or s["estimated_monthly_saving"] > best[key]["estimated_monthly_saving"]:
                best[key] = s
    for s in best.values():
        s["counted"] = True
    rank = {"high": 0, "medium": 1, "low": 2}
    signals.sort(key=lambda s: (-(s["estimated_monthly_saving"] or 0) if s["counted"] else 0, rank[s["severity"]], -(s["monthly_cost"] or 0), s["code"]))
    return signals


def job_effective_tags(job):
    """Job tags propagate to the job clusters a run creates; job-cluster custom_tags add to (and override) them."""
    tags = dict(job.get("tags") or {})
    for jc in job.get("job_clusters", []):
        tags.update(jc.get("custom_tags") or {})
    return tags


def attribution_rows(dimension, slots, inventory, review_total):
    """One row per tag value of a Cost Management dimension, joined to the observed inventory by name or ID."""
    clusters = {c["name"]: c for c in inventory.get("clusters", [])}
    jobs = {j["id"]: j for j in inventory.get("jobs", [])}
    warehouses = {w["id"]: w for w in inventory.get("sql_warehouses", [])}
    pools = {p["id"]: p for p in inventory.get("instance_pools", [])}
    grouped = {}
    for key, slot in slots.items():
        if key is None:
            continue
        name, kind, found, creator, tags = key, dimension, False, None, {}
        group_key = key
        if dimension == "cluster":
            job_run = re.match(r"^job-(\d+)-run-\d+", key)
            if job_run:
                group_key, kind, name = "job-runs", "job_runs", "job_runs"
            elif key.startswith("dlt-execution-") or key.startswith("dlt-maintenance-"):
                group_key, kind, name = "pipelines", "pipeline_runs", "pipeline_runs"
            elif key in clusters:
                c = clusters[key]
                kind = "pipeline" if (c.get("cluster_source") or "").upper().startswith("PIPELINE") else "all_purpose" if c.get("kind") == "AllPurposeCluster" else "job_run"
                found, creator, tags = True, c.get("creator_user_name"), c.get("custom_tags") or {}
            else:
                kind = "not_in_inventory"
        elif dimension == "job" and key in jobs:
            j = jobs[key]
            found, name, creator = True, j["name"], j.get("creator_user_name")
            tags = job_effective_tags(j)
        elif dimension == "warehouse" and key in warehouses:
            w = warehouses[key]
            found, name, creator, tags = True, w["name"], w.get("creator_name"), w.get("custom_tags") or {}
        elif dimension == "pool" and key in pools:
            p = pools[key]
            found, name, tags = True, p["name"], p.get("custom_tags") or {}
        row = grouped.setdefault(group_key, {
            "dimension": dimension, "key": group_key, "name": name, "kind": kind, "in_inventory": found, "creator": creator,
            "tags": {k: v for k, v in tags.items() if k.lower() in {t.lower() for t in COST_ALLOCATION_TAGS}},
            "dbu": 0.0, "infra": 0.0, "vm": 0.0, "total": 0.0, "previous_total": 0.0, "count": 0,
        })
        row["dbu"] += slot["dbu"]
        row["infra"] += slot["infra"]
        row["vm"] += slot["vm"]
        row["total"] += slot["review"]
        row["previous_total"] += slot["previous"]
        row["count"] += 1
    rows = []
    for row in grouped.values():
        if row["kind"] == "job_runs":
            row["name"] = "Clústeres efímeros de jobs (" + str(row["count"]) + (" ejecución)" if row["count"] == 1 else " ejecuciones)")
        elif row["kind"] == "pipeline_runs":
            row["name"] = "Clústeres de pipelines (DLT)"
        row["change"] = round(row["total"] - row["previous_total"], 2)
        row["change_pct"] = _pct(row["total"] - row["previous_total"], row["previous_total"])
        row["share"] = _pct(row["total"], review_total)
        for field in ("dbu", "infra", "vm", "total", "previous_total"):
            row[field] = round(row[field], 2)
        rows.append(row)
    rows.sort(key=lambda r: (-r["total"], str(r["name"])))
    return rows[:150]


def databricks_costs_for(raw, reference):
    """Section 6 model: where Databricks cost comes from and how to optimise it. Never invents data: a missing query
    stays missing (None) and its status is reported."""
    inventory = raw.get("inventory", {})
    data = raw.get("dbx_cost_data")
    receipt = next((s for s in raw.get("sources", []) if s["id"] == "azure_cost_databricks"), None)
    periods = cost_periods(reference)
    labels = periods["labels"]
    tables = cost_tables(data, labels) if data else None
    status = pick(receipt, "status") or ("not_collected" if data is None else "complete")
    signals = cost_signals(inventory, raw.get("dbx_runtime_catalog"), tables, labels, periods, reference)
    model = {
        "status": status,
        "metric": COST_METRIC,
        "periods": labels,
        "currency": tables["currency"] if tables else None,
        "other_currencies": tables["other_currencies"] if tables else [],
        "scope": data.get("scope") if data else None,
        "query_status": tables["query_status"] if tables else {},
        "assumptions": {
            "allocation_tags": list(COST_ALLOCATION_TAGS),
            "autotermination_max_minutes": COST_AUTOTERMINATION_MAX_MINUTES,
            "warehouse_autostop_max_minutes": COST_WAREHOUSE_AUTOSTOP_MAX_MINUTES,
            "jobs_to_all_purpose_dbu_ratio": COST_JOBS_TO_ALL_PURPOSE_DBU_RATIO,
            "spot_discount": COST_SPOT_DISCOUNT,
            "weekend_share": round(labels["review_weekend_days"] / max(1, labels["review_days"]), 4),
        },
        "signals": signals,
        "headline": None, "monthly": [], "split": None, "attribution": None, "movers": None,
    }
    saving_total = round(sum(s["estimated_monthly_saving"] for s in signals if s["counted"]), 2)
    severity_counts = {sev: sum(s["severity"] == sev for s in signals) for sev in ("high", "medium", "low")}
    if tables and tables["query_status"].get("meter") in ("complete", "partial"):
        months = tables["months"]
        review = months[labels["review"]]
        previous = months[labels["previous"]]
        current = months[labels["current"]]
        review_total = review["dbu"] + review["infra"]
        previous_total = previous["dbu"] + previous["infra"]
        vendor = tables["dimensions"].get("vendor")
        gap = vendor.get(None) if vendor is not None and tables["query_status"].get("vendor") in ("complete", "partial") else None
        model["monthly"] = [
            {"month": label, "dbu": round(months[label]["dbu"], 2), "infra": round(months[label]["infra"], 2),
             "total": round(months[label]["dbu"] + months[label]["infra"], 2), "partial": label == labels["current"]}
            for label in (labels["previous"], labels["review"], labels["current"])
        ]
        family_rows = [
            {"key": key, "review": round(v["review"], 2), "previous": round(v["previous"], 2), "share": _pct(v["review"], review["dbu"]),
             "meters": [{"meter": m, "review": round(a, 2)} for m, a in sorted(v["meters"].items(), key=lambda kv: -kv[1])[:6]]}
            for key, v in sorted(tables["families"].items(), key=lambda kv: -kv[1]["review"])
        ]
        category_rows = [
            {"category": key, "review": round(v["review"], 2), "previous": round(v["previous"], 2), "share": _pct(v["review"], review["infra"])}
            for key, v in sorted(tables["categories"].items(), key=lambda kv: -kv[1]["review"])
        ]
        model["split"] = {
            "dbu_families": family_rows,
            "infra_categories": category_rows,
            "vm_sizes": [{"meter": m, "review": round(a, 2)} for m, a in sorted(tables["vm_sizes"].items(), key=lambda kv: -kv[1])[:8]],
        }
        dimensions = []
        all_rows = []
        for dimension, tag in COST_DIMENSIONS:
            slots = tables["dimensions"].get(dimension)
            state = tables["query_status"].get(dimension)
            if slots is None or state not in ("complete", "partial"):
                dimensions.append({"key": dimension, "tag": tag, "status": state or "not_collected", "tagged_share": None, "untagged_total": None})
                continue
            untagged = slots.get(None, {"review": 0.0})["review"]
            rows = attribution_rows(dimension, slots, inventory, review_total)
            all_rows.extend(rows)
            dimensions.append({"key": dimension, "tag": tag, "status": state, "tagged_share": _pct(review_total - untagged, review_total),
                               "untagged_total": round(untagged, 2), "rows": len(rows)})
        creators = {}
        for row in all_rows:
            if row["dimension"] in ("cluster", "job", "warehouse") and row["in_inventory"]:
                who = row["creator"] or "—"
                creators[who] = creators.get(who, 0.0) + row["total"]
        custom = []
        for tag in COST_ALLOCATION_TAGS:
            slots = tables["dimensions"].get("tag:" + tag)
            state = tables["query_status"].get("tag:" + tag)
            if slots is None or state not in ("complete", "partial"):
                custom.append({"tag": tag, "status": state or "not_collected", "tagged_share": None, "values": []})
                continue
            untagged = slots.get(None, {"review": 0.0})
            custom.append({
                "tag": tag, "status": state, "tagged_share": _pct(review_total - untagged["review"], review_total),
                "untagged_total": round(untagged["review"], 2),
                "untagged_categories": [{"category": k, "review": round(v, 2)} for k, v in sorted(untagged.get("categories", {}).items(), key=lambda kv: -kv[1])[:6]],
                "values": [
                    {"value": k, "total": round(v["review"], 2), "dbu": round(v["dbu"], 2), "infra": round(v["infra"], 2),
                     "previous_total": round(v["previous"], 2), "share": _pct(v["review"], review_total)}
                    for k, v in sorted(((k, v) for k, v in slots.items() if k is not None), key=lambda kv: -kv[1]["review"])[:40]
                ],
            })
        model["attribution"] = {
            "dimensions": dimensions,
            "rows": all_rows,
            "creators": [{"creator": k, "total": round(v, 2), "share": _pct(v, review_total)} for k, v in sorted(creators.items(), key=lambda kv: -kv[1])[:25]],
            "custom_tags": custom,
            "gap": None if gap is None else {
                "total": round(gap["review"], 2), "share": _pct(gap["review"], review_total), "previous_total": round(gap["previous"], 2),
                "categories": [{"category": k, "review": round(v, 2), "share": _pct(v, gap["review"])}
                               for k, v in sorted(gap["categories"].items(), key=lambda kv: -kv[1])],
            },
        }
        movable = [r for r in all_rows if r["dimension"] in ("cluster", "job", "warehouse", "pool") and r["kind"] not in ("job_runs", "pipeline_runs")]
        model["movers"] = {
            "up": [r for r in sorted(movable, key=lambda r: -r["change"]) if r["change"] > 0][:5],
            "down": [r for r in sorted(movable, key=lambda r: r["change"]) if r["change"] < 0][:3],
        }
        top = max((r for r in all_rows if r["dimension"] in ("cluster", "job", "warehouse")), key=lambda r: r["total"], default=None)
        first_tag = next((c for c in custom if c["tagged_share"] is not None), None)
        model["headline"] = {
            "review_month": labels["review"], "previous_month": labels["previous"], "current_month": labels["current"],
            "review_total": round(review_total, 2), "previous_total": round(previous_total, 2),
            "change": round(review_total - previous_total, 2), "change_pct": _pct(review_total - previous_total, previous_total),
            "dbu_total": round(review["dbu"], 2), "infra_total": round(review["infra"], 2), "dbu_share": _pct(review["dbu"], review_total),
            "mtd_total": round(current["dbu"] + current["infra"], 2), "mtd_days": labels["mtd_days"],
            "unattributed_total": None if gap is None else round(gap["review"], 2),
            "unattributed_share": None if gap is None else _pct(gap["review"], review_total),
            "first_tag": first_tag and {"tag": first_tag["tag"], "tagged_share": first_tag["tagged_share"]},
            "top_object": top and {"name": top["name"], "dimension": top["dimension"], "total": top["total"], "share": top["share"]},
            "estimated_monthly_savings": saving_total or None,
            "savings_signals": sum(1 for s in signals if s["counted"]),
            "signals": len(signals), "signals_by_severity": severity_counts,
        }
    else:
        model["headline"] = {
            "review_month": labels["review"], "estimated_monthly_savings": None, "savings_signals": 0,
            "signals": len(signals), "signals_by_severity": severity_counts,
        }
    billing = raw.get("system_billing")
    billing_receipt = next((s for s in raw.get("sources", []) if s["id"] == "dbx_system_billing"), None)
    model["system_tables"] = {"status": pick(billing_receipt, "status") or "not_configured", "warehouse_id": pick(billing_receipt, "warehouse_id")}
    if billing:
        rows = sorted(billing.get("rows", []), key=lambda r: -(r.get("list_cost") or 0))
        model["system_tables"].update(
            window=billing.get("window"), truncated=billing.get("truncated"),
            runs=[r for r in rows if r.get("row_type") == "run"][:40],
            users=[r for r in rows if r.get("row_type") == "user"][:20],
            products=[r for r in rows if r.get("row_type") == "product"][:20],
            currency=next((r.get("currency") for r in rows if r.get("currency")), None),
        )
    return model


def cost_summary(model):
    """Compact cost headline for chat responses (fits the 3,500-byte tool-result budget)."""
    if not model:
        return None
    head = model.get("headline") or {}
    return {
        "status": model.get("status"),
        "month": head.get("review_month"),
        "currency": model.get("currency"),
        "total": head.get("review_total"),
        "change_pct": head.get("change_pct"),
        "dbu_share": head.get("dbu_share"),
        "unattributed_share": head.get("unattributed_share"),
        "estimated_monthly_savings": head.get("estimated_monthly_savings"),
        "signals": head.get("signals"),
    }


DEMO_SUBSCRIPTION = "00000000-0000-4000-8000-0000000000a1"
DEMO_TENANT = "00000000-0000-4000-8000-0000000000b2"


def _demo_weights(pattern, key, days, start):
    weights = []
    for i in range(days):
        day = start + timedelta(days=i)
        noise = 0.9 + 0.2 * int(hashlib.sha256((key + day.isoformat()).encode("utf-8")).hexdigest()[:4], 16) / 65535
        weekday = day.weekday() < 5
        coin = int(hashlib.sha256((key + "c" + day.isoformat()).encode("utf-8")).hexdigest()[:2], 16) / 255
        weight = {
            "always": 1.0, "nightly": 1.0, "weekdays": 1.0 if weekday else 0.0,
            "light": 1.0 if weekday and coin < 0.55 else 0.0, "sparse": 1.0 if weekday and coin < 0.22 else 0.0,
            "month_end": 1.0 if i >= days - 6 else 0.0, "pool": 0.62 + (0.38 if weekday else 0.0),
        }[pattern]
        weights.append(weight * (noise if pattern != "pool" else 1.0))
    scale = sum(weights) or 1.0
    return [w / scale for w in weights]


def demo_cost_data(reference, inventory):
    """SIMULATED Cost Management results built item by item, so every query reconciles exactly as live data would."""
    periods = cost_periods(reference)
    labels = periods["labels"]
    tag = {role: (COST_ALLOCATION_TAGS[i] if len(COST_ALLOCATION_TAGS) > i else None) for i, role in enumerate(("team", "project", "cc"))}
    vm, db, st = "Virtual Machines", "Azure Databricks", "Storage"
    ap = lambda name: {"Vendor": "Databricks", "ClusterName": name}
    job = lambda jid, run: {"Vendor": "Databricks", "ClusterName": "job-" + jid + "-run-" + run, "JobId": jid}
    wh = lambda wid: {"Vendor": "Databricks", "SqlEndpointId": wid}
    pool = lambda pid: {"Vendor": "Databricks", "DatabricksInstancePoolId": pid}
    items = [
        (ap("bi-ventas-compartido"), {"team": "ventas", "project": "cuadros-mando"}, db, "Premium All-purpose Compute DBU", 3360, 2640, "always"),
        (ap("bi-ventas-compartido"), {"team": "ventas", "project": "cuadros-mando"}, vm, "DS4 v2", 2050, 1610, "always"),
        (ap("bi-ventas-compartido"), {"team": "ventas", "project": "cuadros-mando"}, st, "P10 LRS Disk", 140, 130, "always"),
        (ap("ds-prevision-demanda"), {"team": "data-science", "project": "prevision-demanda", "cc": "CC-410"}, db, "Premium All-purpose Photon DBU", 820, 760, "weekdays"),
        (ap("ds-prevision-demanda"), {"team": "data-science", "project": "prevision-demanda", "cc": "CC-410"}, vm, "E8ds v5 Spot", 310, 290, "weekdays"),
        (ap("ds-prevision-demanda"), {"team": "data-science", "project": "prevision-demanda", "cc": "CC-410"}, st, "P10 LRS Disk", 45, 40, "weekdays"),
        (ap("ingenieria-adhoc"), {"team": "ingenieria"}, db, "Premium All-purpose Compute DBU", 410, 450, "light"),
        (ap("ingenieria-adhoc"), {"team": "ingenieria"}, vm, "D8ds v5", 260, 280, "light"),
        (ap("ingenieria-adhoc"), {"team": "ingenieria"}, st, "P10 LRS Disk", 25, 25, "light"),
        (ap("legado-informes"), {}, db, "Premium All-purpose Compute DBU", 190, 260, "sparse"),
        (ap("legado-informes"), {}, vm, "DS3 v2", 120, 150, "sparse"),
        (ap("legado-informes"), {}, st, "P10 LRS Disk", 15, 15, "sparse"),
        (ap("finanzas-cierre"), {"team": "finanzas", "project": "cierre-mensual", "cc": "CC-200"}, db, "Premium All-purpose Compute DBU", 260, 180, "month_end"),
        (pool("1015-090000-pool-general"), {}, vm, "D4ds v5", 1180, 1120, "pool"),
        (pool("1015-090000-pool-general"), {}, st, "P10 LRS Disk", 60, 58, "pool"),
        (pool("1015-091500-pool-etlnoche"), {"team": "ingenieria"}, vm, "E8ds v5 Spot", 220, 240, "nightly"),
        (job("1001", "318842"), {"team": "ventas", "project": "etl-ventas", "cc": "CC-100"}, db, "Premium Jobs Compute DBU", 1640, 1480, "nightly"),
        (job("1001", "318842"), {"team": "ventas", "project": "etl-ventas", "cc": "CC-100"}, vm, "D8ds v5", 1020, 930, "nightly"),
        (job("1001", "318842"), {"team": "ventas", "project": "etl-ventas", "cc": "CC-100"}, st, "P10 LRS Disk", 70, 65, "nightly"),
        (job("1004", "551220"), {"team": "data-science", "project": "prevision-demanda"}, db, "Premium Jobs Compute DBU", 690, 640, "nightly"),
        (job("1004", "551220"), {"team": "data-science", "project": "prevision-demanda"}, vm, "E8ds v5 Spot", 160, 150, "nightly"),
        (job("1005", "77310"), {}, db, "Premium Jobs Compute DBU", 380, 300, "nightly"),
        (job("1005", "77310"), {}, vm, "DS3 v2", 240, 190, "nightly"),
        (job("1006", "1"), {"team": "ingenieria", "project": "ingesta-erp", "cc": "CC-300"}, db, "Premium Jobs Compute DBU", 520, 505, "always"),
        (job("1006", "1"), {"team": "ingenieria", "project": "ingesta-erp", "cc": "CC-300"}, vm, "D4ds v5", 300, 290, "always"),
        ({"Vendor": "Databricks", "ClusterName": "dlt-execution-0c1d2e3f-pedidos"}, {"team": "ingenieria", "project": "ingesta-erp"}, db, "Premium DLT Core Compute DBU", 430, 380, "nightly"),
        ({"Vendor": "Databricks", "ClusterName": "dlt-execution-0c1d2e3f-pedidos"}, {"team": "ingenieria", "project": "ingesta-erp"}, vm, "D4ds v5", 140, 120, "nightly"),
        (wh("a1b2c3d4e5f60718"), {"team": "ventas"}, db, "Premium SQL Compute Pro DBU", 1920, 1700, "always"),
        (wh("a1b2c3d4e5f60718"), {"team": "ventas"}, vm, "E8ds v5", 640, 560, "always"),
        (wh("b2c3d4e5f6071829"), {"team": "finanzas", "project": "cierre-mensual", "cc": "CC-200"}, db, "Premium Serverless SQL DBU", 640, 590, "weekdays"),
        ({}, {}, db, "Premium Serverless Compute DBU", 520, 260, "weekdays"),
        ({}, {}, st, "Hot LRS Data Stored", 420, 400, "always"),
        ({}, {}, "Bandwidth", "Standard Data Transfer Out", 180, 170, "always"),
        ({}, {}, "Virtual Network", "NAT Gateway Hours", 140, 140, "always"),
        ({}, {}, "Load Balancer", "Standard Load Balancer Data Processed", 60, 60, "always"),
    ]
    review_days = labels["review_days"]
    mtd_factor = max(0, labels["mtd_days"] - 1) / review_days * 1.04
    queries = {}

    def tags_of(item):
        default, alloc = item[0], item[1]
        return {**default, **{tag[role]: value for role, value in alloc.items() if tag.get(role)}}

    def emit(qid, key_of, with_meter=False, current=False):
        out = {}
        for item in items:
            key = key_of(tags_of(item))
            for period, amount in ((labels["previous"], item[5]), (labels["review"], item[4])) + (((labels["current"], round(item[4] * mtd_factor, 2)),) if current else ()):
                slot = (period, key, item[2], item[3] if with_meter else None)
                out[slot] = out.get(slot, 0.0) + amount
        queries[qid] = {"status": "complete", "rows": [[p, k, c, m, round(v, 6), "EUR"] for (p, k, c, m), v in sorted(out.items(), key=str)],
                        "pages": 1, "seconds": 2.1, "error": None}

    emit("meter", lambda t: None, with_meter=True, current=True)
    emit("vendor", lambda t: t.get("Vendor"))
    for dimension, tag_name in COST_DIMENSIONS:
        emit(dimension, lambda t, n=tag_name: t.get(n))
    for tag_name in COST_ALLOCATION_TAGS:
        emit("tag:" + tag_name, lambda t, n=tag_name: t.get(n))
    names = {c["name"] for c in ap_clusters(inventory)}
    pools_idle = {p["id"] for p in inventory.get("instance_pools", []) if (p.get("min_idle_instances") or 0) > 0}
    for qid, tag_name, wanted in (("daily_cluster", "ClusterName", names), ("daily_pool", "DatabricksInstancePoolId", pools_idle)):
        out = {}
        for item in items:
            key = item[0].get(tag_name)
            if key not in wanted:
                continue
            for i, weight in enumerate(_demo_weights(item[6], key + item[3], review_days, periods["review_start"])):
                day = (periods["review_start"] + timedelta(days=i)).isoformat()
                if weight:
                    out[(day, key)] = out.get((day, key), 0.0) + item[4] * weight
        queries[qid] = {"status": "complete", "rows": [[d, k, None, None, round(v, 6), "EUR"] for (d, k), v in sorted(out.items())],
                        "pages": 1, "seconds": 1.4, "error": None}
    return {
        "metric": COST_METRIC, "periods": labels, "queries": queries,
        "scope": {"subscription_id": DEMO_SUBSCRIPTION, "resource_ids": [], "managed_resource_group": "databricks-rg-dbx-analitica-prod"},
    }


def demo_system_billing(reference):
    periods = cost_periods(reference)
    rows = []
    for job_id, name, runs, cost, sku, user in (
        ("1001", "etl-ventas-diario", 31, 52.9, "PREMIUM_JOBS_COMPUTE", "sp-etl-produccion"),
        ("1004", "prevision-demanda-semanal", 4, 172.5, "PREMIUM_JOBS_COMPUTE", "luis.martin@example.com"),
        ("1005", "calidad-datos-silver", 31, 12.3, "PREMIUM_JOBS_COMPUTE", "jorge.lopez@example.com"),
    ):
        for n in range(min(runs, 6)):
            rows.append({"row_type": "run", "product": "JOBS", "sku": sku, "cluster_id": None, "job_id": job_id, "job_run_id": str(700000 + int(job_id) * 10 + n),
                         "warehouse_id": None, "pipeline_id": None, "run_as": user, "dbus": round(cost / 0.30 * (1.18 - 0.07 * n), 1),
                         "list_cost": round(cost * (1.18 - 0.07 * n), 2), "currency": "USD"})
    rows.append({"row_type": "run", "product": "ALL_PURPOSE", "sku": "PREMIUM_ALL_PURPOSE_COMPUTE", "cluster_id": "0915-081203-bivts01", "job_id": None,
                 "job_run_id": None, "warehouse_id": None, "pipeline_id": None, "run_as": "ana.garcia@example.com", "dbus": 6545.5, "list_cost": 3600.0, "currency": "USD"})
    rows.append({"row_type": "run", "product": "SQL", "sku": "PREMIUM_SQL_PRO_COMPUTE", "cluster_id": None, "job_id": None, "job_run_id": None,
                 "warehouse_id": "a1b2c3d4e5f60718", "pipeline_id": None, "run_as": None, "dbus": 3740.0, "list_cost": 2057.0, "currency": "USD"})
    rows.sort(key=lambda r: -r["list_cost"])
    for user, dbus, cost in (("ana.garcia@example.com", 6545.5, 3600.0), ("sp-etl-produccion", 5880.0, 1764.0), ("luis.martin@example.com", 3790.0, 1595.0),
                             ("marta.ruiz@example.com", 800.0, 440.0), ("jorge.lopez@example.com", 1615.0, 650.0)):
        rows.append({"row_type": "user", "product": None, "sku": None, "cluster_id": None, "job_id": None, "job_run_id": None, "warehouse_id": None,
                     "pipeline_id": None, "run_as": user, "dbus": dbus, "list_cost": cost, "currency": "USD"})
    for product, sku, dbus, cost in (("ALL_PURPOSE", "PREMIUM_ALL_PURPOSE_COMPUTE", 9255.0, 5090.0), ("JOBS", "PREMIUM_JOBS_COMPUTE", 11000.0, 3300.0),
                                     ("SQL", "PREMIUM_SQL_PRO_COMPUTE", 3740.0, 2057.0), ("SQL", "PREMIUM_SERVERLESS_SQL_COMPUTE", 980.0, 686.0),
                                     ("DLT", "PREMIUM_DLT_CORE_COMPUTE", 1530.0, 459.0), ("INTERACTIVE", "PREMIUM_SERVERLESS_COMPUTE", 400.0, 300.0)):
        rows.append({"row_type": "product", "product": product, "sku": sku, "cluster_id": None, "job_id": None, "job_run_id": None, "warehouse_id": None,
                     "pipeline_id": None, "run_as": None, "dbus": dbus, "list_cost": cost, "currency": "USD"})
    return {"warehouse_id": "b2c3d4e5f6071829", "window": {"start": periods["review_start"].isoformat(), "end": periods["current_start"].isoformat()},
            "rows": rows, "truncated": False}


def demo_raw(reference):
    """Complete SIMULATED workspace (operation=self_test): no network, no configuration, clearly labelled everywhere."""
    sub, rg, name, host = DEMO_SUBSCRIPTION, "rg-datos-prod", "dbx-analitica-prod", "adb-1234567890123456.7.azuredatabricks.net"
    base = "/subscriptions/" + sub + "/resourceGroups/" + rg + "/providers/"
    config = {
        "name": name, "resource_group": rg, "workspace_host": host, "environment": "PRODUCTION", "auth_mode": "same_tenant_uami",
        "workspace_api_enabled": True, "unity_catalog_enabled": True, "include_managed_resource_group": True, "advisor_enabled": True,
        "approved_related_resource_ids": [], "approved_cost_resource_ids": [], "cost_scope": "disabled", "cost_timeframe": "month_to_date",
        "cost_analysis_enabled": True, "system_tables_warehouse_id": "b2c3d4e5f6071829",
        "requirements": {"premium_required": True, "no_public_ip_required": True, "vnet_injection_required": True, "cluster_policy_required": True},
        "sre_tenant_id": DEMO_TENANT, "target_tenant_id": DEMO_TENANT, "cross_tenant": False, "subscription_id": sub,
        "id": base + "Microsoft.Databricks/workspaces/" + name,
    }
    vnet, ac = base + "Microsoft.Network/virtualNetworks/vnet-datos-prod", base + "Microsoft.Databricks/accessConnectors/ac-datos-prod"
    nsg, st, kv = base + "Microsoft.Network/networkSecurityGroups/nsg-dbx-prod", base + "Microsoft.Storage/storageAccounts/stlagodatosprod", base + "Microsoft.KeyVault/vaults/kv-datos-prod"
    ws = normalize_workspace({
        "id": config["id"], "name": name, "location": "westeurope", "sku": {"name": "premium"},
        "properties": {
            "workspaceId": "1234567890123456", "workspaceUrl": host, "provisioningState": "Succeeded",
            "managedResourceGroupId": "/subscriptions/" + sub + "/resourceGroups/databricks-rg-" + name, "publicNetworkAccess": "Enabled",
            "requiredNsgRules": "AllRules", "defaultCatalog": {"initialType": "UnityCatalog", "initialName": "main"},
            "accessConnector": {"id": ac, "identityType": "SystemAssigned"},
            "parameters": {"enableNoPublicIp": {"value": True}, "customVirtualNetworkId": {"value": vnet},
                           "customPublicSubnetName": {"value": "snet-dbx-host"}, "customPrivateSubnetName": {"value": "snet-dbx-container"},
                           "storageAccountName": {"value": "dbstoragedemo01"}},
        },
    }, "arm_workspace", reference, config)
    related = [normalize_resource(item, "arm_resource_" + str(i + 1), reference, config, {"type": "direct_reference", "source_id": "arm_workspace", "field": field})
               for i, (item, field) in enumerate((
                   ({"id": vnet, "name": "vnet-datos-prod", "location": "westeurope", "properties": {"addressSpace": {"addressPrefixes": ["10.20.0.0/16"]},
                     "subnets": [{"id": vnet + "/subnets/snet-dbx-host"}, {"id": vnet + "/subnets/snet-dbx-container"}]}}, "parameters.customVirtualNetworkId"),
                   ({"id": vnet + "/subnets/snet-dbx-host", "name": "snet-dbx-host", "properties": {"addressPrefix": "10.20.1.0/24", "networkSecurityGroup": {"id": nsg},
                     "delegations": [{"name": "dbx", "properties": {"serviceName": "Microsoft.Databricks/workspaces"}}]}}, "parameters.customPublicSubnetName"),
                   ({"id": vnet + "/subnets/snet-dbx-container", "name": "snet-dbx-container", "properties": {"addressPrefix": "10.20.2.0/24", "networkSecurityGroup": {"id": nsg},
                     "delegations": [{"name": "dbx", "properties": {"serviceName": "Microsoft.Databricks/workspaces"}}]}}, "parameters.customPrivateSubnetName"),
                   ({"id": nsg, "name": "nsg-dbx-prod", "properties": {"securityRules": []}}, "nsg_id"),
                   ({"id": ac, "name": "ac-datos-prod", "identity": {"type": "SystemAssigned"}, "properties": {"provisioningState": "Succeeded"}}, "accessConnector.id"),
                   ({"id": st, "name": "stlagodatosprod", "sku": {"name": "Standard_ZRS"}, "properties": {"supportsHttpsTrafficOnly": True, "minimumTlsVersion": "TLS1_2",
                     "allowBlobPublicAccess": False, "allowSharedKeyAccess": True, "publicNetworkAccess": "Enabled", "isHnsEnabled": True,
                     "primaryEndpoints": {"dfs": "https://stlagodatosprod.dfs.core.windows.net/"}}}, "approved_related_resource_ids"),
                   ({"id": kv, "name": "kv-datos-prod", "properties": {"enableRbacAuthorization": True, "enablePurgeProtection": True, "enableSoftDelete": True,
                     "publicNetworkAccess": "Disabled", "vaultUri": "https://kv-datos-prod.vault.azure.net/"}}, "keyvault_metadata.resource_id"),
               ))]
    day_ms = 86400000
    now_ms = int(datetime.fromisoformat(reference.replace("Z", "+00:00")).timestamp() * 1000)
    tags = lambda **kw: {COST_ALLOCATION_TAGS[i]: kw[r] for i, r in enumerate(("team", "project", "cc")) if len(COST_ALLOCATION_TAGS) > i and r in kw}
    cluster_specs = [
        {"cluster_id": "0915-081203-bivts01", "cluster_name": "bi-ventas-compartido", "cluster_source": "UI", "state": "RUNNING", "spark_version": "13.3.x-scala2.12",
         "node_type_id": "Standard_DS4_v2", "autoscale": {"min_workers": 2, "max_workers": 8}, "autotermination_minutes": 0, "data_security_mode": "USER_ISOLATION",
         "azure_attributes": {"availability": "ON_DEMAND_AZURE"}, "custom_tags": tags(team="ventas", project="cuadros-mando"),
         "creator_user_name": "ana.garcia@example.com", "start_time": now_ms - 40 * day_ms, "last_restarted_time": now_ms - 9 * day_ms},
        {"cluster_id": "0915-091530-dsprv02", "cluster_name": "ds-prevision-demanda", "cluster_source": "UI", "state": "TERMINATED", "spark_version": "15.4.x-cpu-ml-scala2.12",
         "node_type_id": "Standard_E8ds_v5", "num_workers": 4, "autotermination_minutes": 120, "data_security_mode": "SINGLE_USER", "policy_id": "POL-CIENCIA-DATOS",
         "runtime_engine": "PHOTON", "azure_attributes": {"availability": "SPOT_WITH_FALLBACK_AZURE", "first_on_demand": 1},
         "custom_tags": tags(team="data-science", project="prevision-demanda", cc="CC-410"), "creator_user_name": "luis.martin@example.com"},
        {"cluster_id": "0915-102244-ingad03", "cluster_name": "ingenieria-adhoc", "cluster_source": "UI", "state": "TERMINATED", "spark_version": "14.3.x-scala2.12",
         "node_type_id": "Standard_D8ds_v5", "autoscale": {"min_workers": 1, "max_workers": 4}, "autotermination_minutes": 30, "data_security_mode": "USER_ISOLATION",
         "policy_id": "POL-USO-PERSONAL", "azure_attributes": {"availability": "ON_DEMAND_AZURE"}, "custom_tags": tags(team="ingenieria"),
         "creator_user_name": "marta.ruiz@example.com"},
        {"cluster_id": "0915-110001-legin04", "cluster_name": "legado-informes", "cluster_source": "UI", "state": "TERMINATED", "spark_version": "10.4.x-scala2.12",
         "node_type_id": "Standard_DS3_v2", "num_workers": 2, "autotermination_minutes": 60, "data_security_mode": "NONE",
         "azure_attributes": {"availability": "ON_DEMAND_AZURE"}, "creator_user_name": "jorge.lopez@example.com"},
        {"cluster_id": "0915-120000-fincr05", "cluster_name": "finanzas-cierre", "cluster_source": "API", "state": "TERMINATED", "spark_version": "15.4.x-scala2.12",
         "node_type_id": "Standard_D4ds_v5", "num_workers": 2, "autotermination_minutes": 20, "data_security_mode": "USER_ISOLATION", "policy_id": "POL-USO-PERSONAL",
         "instance_pool_id": "1015-090000-pool-general", "custom_tags": tags(team="finanzas", project="cierre-mensual", cc="CC-200"),
         "creator_user_name": "elena.sanz@example.com"},
        {"cluster_id": "1103-020000-job1004", "cluster_name": "job-1004-run-551220", "cluster_source": "JOB", "state": "TERMINATED", "spark_version": "15.4.x-cpu-ml-scala2.12",
         "node_type_id": "Standard_E8ds_v5", "num_workers": 6, "data_security_mode": "SINGLE_USER"},
    ]
    clusters = [normalize_cluster(c, "dbx_clusters", reference, config) for c in cluster_specs]
    pools = [normalize_pool(p, "dbx_instance_pools", reference, config) for p in (
        {"instance_pool_id": "1015-090000-pool-general", "instance_pool_name": "pool-general", "node_type_id": "Standard_D4ds_v5", "min_idle_instances": 4,
         "max_capacity": 20, "idle_instance_autotermination_minutes": 60, "azure_attributes": {"availability": "ON_DEMAND_AZURE"}, "state": "ACTIVE",
         "stats": {"used_count": 1, "idle_count": 4}},
        {"instance_pool_id": "1015-091500-pool-etlnoche", "instance_pool_name": "pool-etl-noche", "node_type_id": "Standard_E8ds_v5", "min_idle_instances": 0,
         "max_capacity": 30, "idle_instance_autotermination_minutes": 15, "azure_attributes": {"availability": "SPOT_WITH_FALLBACK_AZURE"}, "state": "ACTIVE",
         "custom_tags": tags(team="ingenieria"), "stats": {"used_count": 0, "idle_count": 0}},
    )]
    tag_rules = lambda *keys: {"custom_tags." + COST_ALLOCATION_TAGS[i]: {"type": "unlimited", "isOptional": False} for i in keys if len(COST_ALLOCATION_TAGS) > i}
    policies = [normalize_policy(p, "dbx_cluster_policies", reference, config) for p in (
        {"policy_id": "POL-USO-PERSONAL", "name": "pol-uso-personal", "policy_family_id": "personal-vm",
         "definition": json.dumps({**tag_rules(0), "autotermination_minutes": {"type": "fixed", "value": 30}})},
        {"policy_id": "POL-CIENCIA-DATOS", "name": "pol-ciencia-datos", "definition": json.dumps({**tag_rules(0, 1), "autotermination_minutes": {"type": "range", "maxValue": 120}})},
        {"policy_id": "POL-JOBS-PRODUCCION", "name": "pol-jobs-produccion", "definition": json.dumps(tag_rules(0, 1, 2))},
    )]
    job_cluster = lambda key, node, pol, avail, extra, **kw: {"job_cluster_key": key, "new_cluster": {
        "spark_version": kw.pop("version", "15.4.x-scala2.12"), "node_type_id": node, "policy_id": pol, "azure_attributes": {"availability": avail},
        "custom_tags": tags(**kw), "data_security_mode": "SINGLE_USER", **extra}}
    job_specs = [
        (1001, "etl-ventas-diario", {"quartz_cron_expression": "0 0 2 * * ?"}, [job_cluster("jc-etl", "Standard_D8ds_v5", "POL-JOBS-PRODUCCION", "ON_DEMAND_AZURE",
          {"autoscale": {"min_workers": 2, "max_workers": 10}}, team="ventas", project="etl-ventas", cc="CC-100")], [("bronce", "jc-etl", None), ("plata", "jc-etl", None)]),
        (1002, "refresco-cuadros-mando", {"quartz_cron_expression": "0 30 6 * * ?"}, [], [("refresco", None, "0915-081203-bivts01")]),
        (1003, "export-pedidos-distribuidores", {"quartz_cron_expression": "0 0 7 * * ?"}, [], [("export", None, "0915-081203-bivts01")]),
        (1004, "prevision-demanda-semanal", {"quartz_cron_expression": "0 0 4 ? * MON"}, [job_cluster("jc-ml", "Standard_E8ds_v5", "POL-CIENCIA-DATOS",
          "SPOT_WITH_FALLBACK_AZURE", {"num_workers": 6}, version="15.4.x-cpu-ml-scala2.12", team="data-science", project="prevision-demanda")], [("entrenar", "jc-ml", None)]),
        (1005, "calidad-datos-silver", {"quartz_cron_expression": "0 0 3 * * ?"}, [job_cluster("jc-calidad", "Standard_DS3_v2", None, "ON_DEMAND_AZURE",
          {"num_workers": 4}, version="12.2.x-scala2.12")], [("validar", "jc-calidad", None)]),
        (1006, "ingesta-erp-continua", None, [job_cluster("jc-stream", "Standard_D4ds_v5", "POL-JOBS-PRODUCCION", "ON_DEMAND_AZURE", {"num_workers": 2},
          team="ingenieria", project="ingesta-erp", cc="CC-300")], [("stream", "jc-stream", None)]),
    ]
    jobs = []
    for jid, jname, schedule, clusters_spec, tasks in job_specs:
        settings = {"name": jname, "job_clusters": clusters_spec, "timeout_seconds": 7200, "email_notifications": {"on_failure": ["datos@example.com"]},
                    "run_as": {"service_principal_name": "00000000-0000-4000-8000-0000000000c3"} if jid in (1001, 1006) else {"user_name": "ana.garcia@example.com"},
                    "tasks": [{"task_key": key, "job_cluster_key": jck, "existing_cluster_id": ecid, "notebook_task": {"notebook_path": "/Repos/datos/" + jname + "/" + key}}
                              for key, jck, ecid in tasks]}
        settings.update({"schedule": schedule} if schedule else {"continuous": {"pause_status": "UNPAUSED"}})
        jobs.append(normalize_job({"job_id": jid, "creator_user_name": "ana.garcia@example.com", "settings": settings}, "dbx_jobs", reference, config))
    pipelines = [normalize_pipeline({"pipeline_id": "0c1d2e3f-pedidos", "name": "dlt-pedidos", "state": "IDLE", "catalog": "main", "target": "plata_pedidos",
                                     "serverless": False, "continuous": False}, "dbx_pipelines", reference, config)]
    warehouses = [normalize_warehouse(w, "dbx_sql_warehouses", reference, config) for w in (
        {"id": "a1b2c3d4e5f60718", "name": "wh-bi-ventas", "state": "RUNNING", "cluster_size": "Medium", "warehouse_type": "PRO", "enable_serverless_compute": False,
         "auto_stop_mins": 0, "min_num_clusters": 1, "max_num_clusters": 2, "num_clusters": 1, "num_active_sessions": 0, "creator_name": "ana.garcia@example.com",
         "tags": {"custom_tags": [{"key": k, "value": v} for k, v in tags(team="ventas").items()]}},
        {"id": "b2c3d4e5f6071829", "name": "wh-finanzas-serverless", "state": "STOPPED", "cluster_size": "Small", "warehouse_type": "PRO",
         "enable_serverless_compute": True, "auto_stop_mins": 10, "min_num_clusters": 1, "max_num_clusters": 1, "creator_name": "elena.sanz@example.com",
         "tags": {"custom_tags": [{"key": k, "value": v} for k, v in tags(team="finanzas", project="cierre-mensual", cc="CC-200").items()]}},
    )]
    scopes = [normalize_secret_scope({"name": "kv-datos-prod", "backend_type": "AZURE_KEYVAULT",
                                      "keyvault_metadata": {"resource_id": kv, "dns_name": "https://kv-datos-prod.vault.azure.net/"}}, "dbx_secret_scopes", reference, config)]
    metastore = normalize_metastore({"metastore_id": "ms-weu-demo", "name": "metastore-westeurope", "region": "westeurope",
                                     "storage_root": "abfss://metastore@stlagodatosprod.dfs.core.windows.net/root"}, "uc_metastore_summary", reference, config)
    catalogs = [normalize_catalog({"name": n, "catalog_type": "MANAGED_CATALOG", "storage_root": "abfss://" + n + "@stlagodatosprod.dfs.core.windows.net/" + n,
                                   "isolation_mode": "ISOLATED", "metastore_id": "ms-weu-demo"}, "uc_catalogs", reference, config) for n in ("main", "ventas", "ciencia_datos")]
    schemas = [normalize_schema({"full_name": "main." + n, "name": n, "catalog_name": "main", "metastore_id": "ms-weu-demo"}, "uc_schemas", reference, config)
               for n in ("bronce_pedidos", "plata_pedidos")]
    creds = [normalize_storage_credential({"id": "sc-demo-01", "name": "cred-lago-datos", "read_only": False,
                                           "azure_managed_identity": {"access_connector_id": ac}}, "uc_storage_credentials", reference, config)]
    locations = [normalize_external_location({"name": "ext-lago-curado", "url": "abfss://curado@stlagodatosprod.dfs.core.windows.net/", "credential_name": "cred-lago-datos",
                                               "read_only": False, "metastore_id": "ms-weu-demo"}, "uc_external_locations", reference, config)]
    outbound = [normalize_outbound_endpoint({"category": "Webapp", "endpoints": [{"domainName": "westeurope.azuredatabricks.net", "endpointDetails": [{"port": 443}]}]},
                                            "arm_outbound_endpoints", reference, config)]
    inventory = {
        "clusters": clusters, "instance_pools": pools, "cluster_policies": policies, "jobs": jobs, "pipelines": pipelines, "sql_warehouses": warehouses,
        "secret_scopes": scopes, "global_init_scripts": [], "uc_metastore": metastore, "uc_catalogs": catalogs, "uc_schemas": schemas,
        "uc_storage_credentials": creds, "uc_external_locations": locations, "uc_connections": [], "outbound_endpoints": outbound, "related_resources": related,
    }
    counts = {"dbx_clusters": clusters, "dbx_instance_pools": pools, "dbx_cluster_policies": policies, "dbx_jobs": jobs, "dbx_pipelines": pipelines,
              "dbx_sql_warehouses": warehouses, "dbx_secret_scopes": scopes, "uc_catalogs": catalogs, "uc_schemas": schemas, "uc_storage_credentials": creds,
              "uc_external_locations": locations, "uc_connections": [], "arm_outbound_endpoints": outbound}
    sources = [source_receipt("arm_workspace", reference, records=1, pages=1)]
    sources += [source_receipt(sid, reference, records=len(rows), pages=1) for sid, rows in counts.items()]
    sources += [source_receipt(sid, reference, records=1, pages=1) for sid in ("arm_diagnostics", "dbx_workspace_conf", "uc_metastore_summary", "dbx_spark_versions", "dbx_node_types")]
    sources += [source_receipt("arm_managed_rg_inventory", reference, records=9, pages=1), source_receipt("dbx_init_scripts", reference, pages=1)]
    sources += [source_receipt("arm_resource_" + str(i + 1), reference, records=1, pages=1) for i in range(len(related))]
    sources += [
        source_receipt("uc_system_lineage", reference, "not_configured", "Runtime table/column lineage is never queried by this collector."),
        source_receipt("arm_advisor", reference, pages=1),
        source_receipt("azure_cost", reference, "not_configured", "Legacy cost_scope disabled in the simulated configuration."),
    ]
    cost_data = demo_cost_data(reference, inventory)
    sources.append(source_receipt("azure_cost_databricks", reference, records=sum(len(q["rows"]) for q in cost_data["queries"].values()),
                                  pages=len(cost_data["queries"]), metric=COST_METRIC,
                                  queries=[{"id": k, "status": "complete", "records": len(q["rows"]), "seconds": q["seconds"]} for k, q in cost_data["queries"].items()],
                                  note="SIMULATED Cost Management results (operation=self_test)."))
    billing = demo_system_billing(reference)
    sources.append(source_receipt("dbx_system_billing", reference, records=len(billing["rows"]), pages=1, warehouse_id=billing["warehouse_id"],
                                  note="SIMULATED system.billing.usage result: in production this source is OFF unless system_tables_warehouse_id is set."))
    return {
        "workspace": ws, "sources": sources, "inventory": inventory, "requirements": config["requirements"],
        "workspace_conf": {"enableTokensConfig": "true", "maxTokenLifetimeDays": "90", "enableIpAccessLists": "false",
                           "enableDbfsFileBrowser": "false", "enableExportNotebook": "true"},
        "arm_diagnostics": [{"id": config["id"] + "/providers/Microsoft.Insights/diagnosticSettings/diag-dbx", "name": "diag-dbx",
                             "logs": [{"category": "jobs", "enabled": True}, {"category": "clusters", "enabled": True}]}],
        "advisor": [], "cost_rows": [],
        "dbx_runtime_catalog": {
            "spark_versions": ["13.3.x-scala2.12", "14.3.x-scala2.12", "15.4.x-scala2.12", "15.4.x-cpu-ml-scala2.12", "16.4.x-scala2.12"],
            "node_types": {"Standard_DS3_v2": {"is_deprecated": False}, "Standard_DS4_v2": {"is_deprecated": False}},
        },
        "dbx_cost_data": cost_data,
        "system_billing": billing,
        "demo_roster": [{"workspace_id": config["id"], "workspace_name": name, "resource_group": rg, "workspace_host": host,
                         "environment": "PRODUCTION", "auth_mode": "same_tenant_uami", "cross_tenant": False}],
    }


def finish_snapshot(raw, reference, provenance="LIVE", environment="UNSPECIFIED"):
    if provenance not in ("LIVE", "SIMULATED") or environment not in ("LAB", "PRODUCTION", "UNSPECIFIED"):
        raise EvidenceError("invalid_provenance", "Explicit source provenance and environment are required.")
    raw = {
        **raw,
        "sources": list(raw["sources"]) + [
            source_receipt(
                "reference_catalog", reference,
                records=CATALOG.get("catalogSnapshot", {}).get("item_count", 0),
                note="Build-time pinned Azure Databricks Well-Architected & Lakehouse rule catalog.",
            ),
            source_receipt(
                "configuration_requirements", reference,
                "complete" if raw.get("requirements") else "not_configured",
                records=len(raw.get("requirements", {})),
                note="Explicit operator intent only; unknown requirements are not inferred.",
            ),
        ],
    }
    raw["databricks_cost_model"] = cost_model = databricks_costs_for(raw, reference)
    dep_graph = dependencies_for(raw, reference, provenance)
    checks = evaluate(raw, reference, dep_graph)
    findings = [check for check in checks if check["status"] == "failed"]
    global_score = score(checks)
    scores = {
        "global": global_score,
        "coverage": dict(global_score),
        "areas": {area: score([check for check in checks if check["area"] == area]) for area in AREAS},
        "pillars": {pillar: score([check for check in checks if check["pillar"] == pillar]) for pillar in PILLARS},
    }
    blind_spots = [source["id"] for source in raw["sources"] if source["status"] not in ("complete", "not_applicable")]
    critical = sum(check["severity"] == "critical" for check in findings)
    catalog_count = CATALOG.get("catalogSnapshot", {}).get("item_count", len(CATALOG.get("rules", [])))
    dep_counts = dep_graph["summary_counts"]
    head = cost_model.get("headline") or {}
    cost_message = (
        "Databricks costó " + es_amount(head["review_total"]) + " " + (cost_model.get("currency") or "") + " en " + es_month(head["review_month"])
        + " (" + es_amount(head.get("dbu_share"), 1) + " % DBU, " + es_amount(100 - (head.get("dbu_share") or 0), 1) + " % infraestructura)"
        + ("; " + es_amount(head["unattributed_share"], 1) + " % sin etiqueta de cómputo" if head.get("unattributed_share") is not None else "")
        + ("; ahorro estimado " + es_amount(head["estimated_monthly_savings"]) + " " + (cost_model.get("currency") or "") + "/mes con reglas documentadas."
           if head.get("estimated_monthly_savings") else ".")
    ) if head.get("review_total") is not None else (
        str(head.get("signals") or 0) + " señales de optimización de costes observadas en la configuración; sin datos de coste ("
        + str(cost_model.get("status")) + "), así que no se estima ahorro."
    )
    return {
        "schema_version": "1.0",
        "provenance": provenance,
        "environment": environment,
        "reference_utc": reference,
        "client": {"name": CLIENT_NAME, "logo_data_uri": CLIENT_LOGO_DATA_URI, "logo_alt": CLIENT_LOGO_ALT},
        "presentation": presentation_settings(),
        "workspace": raw["workspace"],
        "sources": raw["sources"],
        "inventory": raw["inventory"],
        "dependencies": dep_graph,
        "source_data": {
            "workspace_conf": raw.get("workspace_conf"),
            "arm_diagnostics": raw.get("arm_diagnostics", []),
            "advisor": raw.get("advisor", []),
            "cost_rows": raw.get("cost_rows", []),
        },
        "checks": checks,
        "findings": findings,
        "scores": scores,
        "finops": finops_for(raw),
        "databricks_costs": cost_model,
        "actions": actions_for(findings),
        "executive_messages": [
            cost_message,
            str(dep_counts["nodes_total"]) + " nodos en el mapa de dependencias (" + str(dep_counts["edges_observed"]) + " relaciones OBSERVED, " + str(dep_counts["edges_inferred"]) + " INFERRED explícitas y " + str(dep_counts["unknowns_total"]) + " puntos ciegos UNKNOWN).",
            str(len(findings)) + " hallazgos de configuración y dependencias observados (" + str(critical) + " críticos reales, sin rellenar un Top 5 ficticio).",
            str(global_score["evaluated"]) + " de " + str(global_score["evaluated"] + global_score["not_evaluated"]) + " comprobaciones aplicables evaluadas; la cobertura se muestra junto al índice local.",
            str(dep_counts["broken_references_total"]) + " referencias rotas detectadas entre tareas de Jobs, clústeres, pools, políticas, pipelines, warehouses y credenciales.",
            str(len(blind_spots)) + " fuentes con estado parcial, denegado o no configurado; ningún clúster se inició para esta revisión.",
        ],
        "methodology": {
            "score_kind": "local_assessment_indicator",
            "official_waf_score": False,
            "read_only": True,
            "score_formula": "100 * passed / (passed + failed), unique workspace/rule/workload/resource check_id. No evaluated checks => null.",
            "coverage_formula": "100 * evaluated / (evaluated + not_evaluated). N/A excluded.",
            "catalogSnapshot": CATALOG.get("catalogSnapshot", {}),
            "catalog_coverage": {
                "total_items": catalog_count,
                "mapped_items": len(CATALOG.get("rules", [])),
                "unmapped_items": max(0, catalog_count - len(CATALOG.get("rules", []))),
                "local_rules": len(CATALOG.get("rules", [])),
            },
            "assessment_url": CATALOG.get("assessment_url", ""),
            "interpretation": CATALOG.get("interpretation", []),
            "scope": {
                "workspace_id": raw["workspace"]["id"],
                "workspace_name": raw["workspace"]["workspace_name"],
                "workspace_host": raw["workspace"]["workspace_url"],
                "auth_mode": raw["workspace"]["auth_mode"],
                "cross_tenant": raw["workspace"]["cross_tenant"],
                "environment": environment,
                "requirements": raw.get("requirements", {}),
            },
            "limitations": [
                "Point-in-time ARM control-plane and Databricks Workspace/Unity Catalog REST metadata assessment; no cluster or SQL Warehouse is started.",
                "Dependency edges are classified strictly as OBSERVED (exact native ID/key join), INFERRED (unverified URI/hostname target) or UNKNOWN (uncollected runtime lineage or code internals).",
                "Cross-tenant execution requires prior administrator setup (multi-tenant app with Federated Identity Credential or Azure Lighthouse + Databricks OIDC federation).",
                "This local indicator is not an official Microsoft Well-Architected Review or Databricks certification.",
            ],
        },
    }


def multi_snapshot(runs, reference, roster):
    if not 1 <= len(runs) <= 5 or len({run["workspace_id"].lower() for run in runs}) != len(runs):
        raise EvidenceError("invalid_workspace_runs", "Multi-workspace runs require distinct fixed workspace IDs.", "assessment")
    if any(
        run["status"] not in ("ok", "partial", "error")
        or ((run["snapshot"] is None) != (run["status"] == "error"))
        or (run["snapshot"] is None and not isinstance(run["error"], dict))
        or (run["snapshot"] is not None and run["error"] is not None)
        for run in runs
    ):
        raise EvidenceError("invalid_workspace_runs", "Each run is an explicit snapshot success/partial or a structured error, never both.", "assessment")
    snapshots = [run["snapshot"] for run in runs if run["snapshot"] is not None]
    provenances = {snapshot["provenance"] for snapshot in snapshots}
    if len(provenances) > 1:
        raise EvidenceError("mixed_provenance", "LIVE and SIMULATED snapshots cannot be combined.", "assessment")
    checks = [check for snapshot in snapshots for check in snapshot["checks"]]
    scores = {
        "global": score(checks),
        "areas": {area: score([row for row in checks if row["area"] == area]) for area in AREAS},
        "pillars": {pillar: score([row for row in checks if row["pillar"] == pillar]) for pillar in PILLARS},
    }
    scores["coverage"] = dict(scores["global"])
    inv_keys = ("clusters", "jobs", "pipelines", "sql_warehouses", "uc_catalogs", "uc_external_locations", "related_resources")
    heads = [((s.get("databricks_costs") or {}).get("headline") or {}, (s.get("databricks_costs") or {}).get("currency")) for s in snapshots]
    currencies = {cur for head, cur in heads if head.get("review_total") is not None}
    comparable = bool(heads) and len(currencies) == 1 and all(head.get("review_total") is not None for head, _ in heads)
    return {
        "schema_version": "databricks-dep-multi-workspace-v1",
        "reference_utc": reference,
        "provenance": next(iter(provenances)) if provenances else "LIVE",
        "client": {"name": CLIENT_NAME, "logo_data_uri": CLIENT_LOGO_DATA_URI, "logo_alt": CLIENT_LOGO_ALT},
        "presentation": presentation_settings(),
        "available_workspaces": roster,
        "selected_workspace_names": [run["workspace_name"] for run in runs],
        "workspace_runs": runs,
        "aggregate": {
            "scores": scores,
            "inventory_counts": {
                key: sum(len(snapshot["inventory"].get(key) or []) for snapshot in snapshots)
                for key in inv_keys
            },
            "dependency_counts": {
                key: sum(snapshot["dependencies"]["summary_counts"].get(key, 0) for snapshot in snapshots)
                for key in ("nodes_total", "edges_total", "edges_observed", "edges_inferred", "unknowns_total", "broken_references_total")
            },
            "findings_total": sum(len(snapshot["findings"]) for snapshot in snapshots),
            "critical_total": sum(check["status"] == "failed" and check["severity"] == "critical" for check in checks),
            "workspace_status_counts": dict(Counter(run["status"] for run in runs)),
            "failed_workspace_count": sum(run["snapshot"] is None for run in runs),
            "official_waf_score": False,
            "estimated_savings": None,
            "actual_cost": None,
            "databricks_costs": {
                "currency": next(iter(currencies)) if comparable else None,
                "review_total": round(sum(head["review_total"] for head, _ in heads), 2) if comparable else None,
                "estimated_monthly_savings": round(sum(head.get("estimated_monthly_savings") or 0 for head, _ in heads), 2) if comparable else None,
            },
        },
    }


def run_sources(run):
    if run["snapshot"] is not None:
        return run["snapshot"]["sources"]
    return [source_receipt(
        "arm_workspace", run["reference_utc"],
        "denied" if run["error"].get("http_status") in (401, 403) else "error",
        "Primary collection failed; this workspace has no snapshot or inferred healthy-zero inventory.",
        errors=[run["error"]],
    )]


def successful_snapshots(document):
    return (
        [run["snapshot"] for run in document["workspace_runs"] if run["snapshot"] is not None]
        if document.get("schema_version") == "databricks-dep-multi-workspace-v1"
        else [document]
    )


def collection_disclosure(snapshot):
    if snapshot.get("schema_version") == "databricks-dep-multi-workspace-v1":
        sources = [source for run in snapshot["workspace_runs"] for source in run_sources(run)]
        return {
            "reference_utc": snapshot["reference_utc"],
            "fresh_collection": True,
            "provenance": snapshot["provenance"],
            "selected_workspace_names": snapshot["selected_workspace_names"],
            "workspace_run_status_counts": snapshot["aggregate"]["workspace_status_counts"],
            "source_status_counts": dict(Counter(source["status"] for source in sources)),
            "source_total": len(sources),
            "source_details_view": "coverage",
            "paging_basis": "Local offset in this collection; later calls recollect, not a stable cross-call cursor.",
        }
    return {
        "reference_utc": snapshot["reference_utc"],
        "fresh_collection": True,
        "provenance": snapshot["provenance"],
        "environment": snapshot["environment"],
        "auth_mode": snapshot["workspace"]["auth_mode"],
        "cross_tenant": snapshot["workspace"]["cross_tenant"],
        "source_status_counts": dict(Counter(s["status"] for s in snapshot["sources"])),
        "source_total": len(snapshot["sources"]),
        "source_details_view": "coverage",
        "paging_basis": "Local offset in this collection; later calls recollect, not a stable cross-call cursor.",
    }


def summary(snapshot):
    inv = snapshot["inventory"]
    compact_scores = lambda group: {
        k: {
            "score": v["score"],
            "coverage_percent": v["coverage_percent"],
            "evaluated": v["evaluated"],
            "not_evaluated": v["not_evaluated"],
        }
        for k, v in group.items()
    }
    return {
        "workspace_id": snapshot["workspace"]["id"],
        "workspace_name": snapshot["workspace"]["workspace_name"],
        "workspace_url": snapshot["workspace"]["workspace_url"],
        "auth_mode": snapshot["workspace"]["auth_mode"],
        "cross_tenant": snapshot["workspace"]["cross_tenant"],
        "global": snapshot["scores"]["global"],
        "areas": compact_scores(snapshot["scores"]["areas"]),
        "pillars": compact_scores(snapshot["scores"]["pillars"]),
        "inventory_counts": {
            key: len(inv.get(key) or [])
            for key in ("clusters", "jobs", "pipelines", "sql_warehouses", "uc_catalogs", "uc_external_locations", "related_resources")
        },
        "dependency_counts": snapshot["dependencies"]["summary_counts"],
        "findings": len(snapshot["findings"]),
        "critical": sum(f["severity"] == "critical" for f in snapshot["findings"]),
        "catalog_coverage": snapshot["methodology"]["catalog_coverage"],
        "official_waf_score": False,
        "actual_cost": snapshot["finops"]["actual_cost"],
        "currency": snapshot["finops"]["currency"],
        "estimated_savings": None,
        "databricks_costs": cost_summary(snapshot.get("databricks_costs")),
    }


def cost_rows_for_query(snapshot):
    model = snapshot.get("databricks_costs") or {}
    currency = model.get("currency")
    head = model.get("headline") or {}
    rows = [{"record_type": "headline", "name": "databricks_costs", **(cost_summary(model) or {}),
             "mtd_total": head.get("mtd_total"), "previous_total": head.get("previous_total")}]
    for s in model.get("signals", []):
        rows.append({
            "record_type": "signal", "id": s["id"], "code": s["code"], "severity": s["severity"], "title": s["title"],
            "name": s["object_name"], "workload_name": s["object_name"], "kind": s["object_kind"], "monthly_cost": s["monthly_cost"],
            "estimated_monthly_saving": s["estimated_monthly_saving"], "saving_kind": s["saving_kind"], "counted": s["counted"],
            "currency": currency, "recommendation": s["recommendation"],
        })
    for r in ((model.get("attribution") or {}).get("rows") or [])[:60]:
        rows.append({
            "record_type": "attribution", "dimension": r["dimension"], "name": r["name"], "workload_name": r["name"], "kind": r["kind"],
            "total": r["total"], "dbu": r["dbu"], "infra": r["infra"], "previous_total": r["previous_total"], "share": r["share"],
            "creator": r["creator"], "tags": r["tags"], "currency": currency,
        })
    return rows


def snapshot_rows(snapshot, view):
    inv = snapshot["inventory"]
    uc_rows = (
        ([inv["uc_metastore"]] if inv.get("uc_metastore") else [])
        + inv.get("uc_catalogs", [])
        + inv.get("uc_schemas", [])
        + inv.get("uc_storage_credentials", [])
        + inv.get("uc_external_locations", [])
        + inv.get("uc_connections", [])
    )
    return {
        "summary": [summary(snapshot)],
        "workspace": [snapshot["workspace"]],
        "compute": inv.get("clusters", []) + inv.get("instance_pools", []) + inv.get("cluster_policies", []) + inv.get("global_init_scripts", []),
        "jobs": inv.get("jobs", []),
        "pipelines": inv.get("pipelines", []),
        "warehouses": inv.get("sql_warehouses", []),
        "unity_catalog": uc_rows + inv.get("secret_scopes", []),
        "resources": inv.get("related_resources", []) + inv.get("outbound_endpoints", []),
        "findings": snapshot["checks"],
        "coverage": snapshot["sources"],
        "actions": snapshot["actions"],
        "finops": (
            [{**row, "record_type": "candidate"} for row in snapshot["finops"]["candidates"]]
            + [{**row, "record_type": "cost"} for row in snapshot["finops"]["cost_rows"]]
        ),
        "dependencies": (
            snapshot["dependencies"]["nodes"]
            + snapshot["dependencies"]["edges"]
            + snapshot["dependencies"]["unknowns"]
        ),
        "costs": cost_rows_for_query(snapshot),
    }[view]


def query_snapshot(snapshot, params):
    view = params["view"]
    if snapshot.get("schema_version") == "databricks-dep-multi-workspace-v1":
        rows = []
        for run in snapshot["workspace_runs"]:
            scope = {"workspace_id": run["workspace_id"], "workspace_name": run["workspace_name"]}
            if run["snapshot"] is not None:
                rows.extend({**row, **scope} for row in snapshot_rows(run["snapshot"], view))
            elif view == "coverage":
                rows.extend({**row, **scope} for row in run_sources(run))
            elif view == "summary":
                rows.append({
                    **scope, "status": "error", "global": None, "inventory_counts": None,
                    "error": run["error"], "reference_utc": run["reference_utc"],
                })
    else:
        rows = snapshot_rows(snapshot, view)

    def matches(row):
        if params["workload_name"] and row.get("workload_name") != params["workload_name"] and row.get("name") != params["workload_name"]:
            return False
        if params["classification"] != "all" and row.get("classification") != params["classification"]:
            return False
        for field in ("area", "level", "severity", "status"):
            if params[field] != "all" and row.get(field) != params[field]:
                return False
        return True

    matched = [row for row in rows if matches(row)]
    selected = matched[params["offset"]:params["offset"] + params["limit"]]
    partial = snapshot.get("schema_version") == "databricks-dep-multi-workspace-v1" and any(
        run["status"] != "ok" for run in snapshot["workspace_runs"]
    )
    result = {
        "status": "partial" if partial else "ok",
        "operation": "query",
        "view": view,
        "collection": collection_disclosure(snapshot),
        "total_matched": len(matched),
        "offset": params["offset"],
        "requested_limit": params["limit"],
        "returned": len(selected),
        "has_more": params["offset"] + len(selected) < len(matched),
        "next_offset": params["offset"] + len(selected) if params["offset"] + len(selected) < len(matched) else None,
        "transport_capped": False,
        "rows": selected,
    }
    while selected and response_bytes(result) > TRANSPORT_BYTES:
        selected = selected[:-1]
        result.update(
            rows=selected,
            returned=len(selected),
            transport_capped=True,
            has_more=params["offset"] + len(selected) < len(matched),
            next_offset=params["offset"] + len(selected) if selected and params["offset"] + len(selected) < len(matched) else None,
        )
    if not selected and params["offset"] < len(matched):
        return ensure_response({
            "status": "error",
            "operation": "query",
            "view": view,
            "error": {
                "code": "query_row_too_large",
                "message": "One complete row cannot fit 3500 default-serialized bytes. Use the full report JSON; no zero-row continuation.",
            },
            "total_matched": len(matched),
            "offset": params["offset"],
            "requested_limit": params["limit"],
            "returned": 0,
            "has_more": True,
            "next_offset": None,
            "transport_capped": True,
            "collection": collection_disclosure(snapshot),
        })
    return ensure_response(result)


def safe_json(snapshot):
    document = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    escaped = document.replace("&", "\\u0026").replace("<", "\\u003c").replace(">", "\\u003e").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")
    if json.loads(escaped) != snapshot:
        raise EvidenceError("round_trip_failed", "Complete embedded normalized JSON did not round-trip.", "renderer")
    return escaped


def render_html(snapshot):
    if HTML_TEMPLATE.count("__REPORT_DATA_JSON__") != 1:
        raise EvidenceError("template_missing", "Build the approved template into the canonical standalone tool.", "renderer")
    validate_logo(snapshot["client"]["logo_data_uri"], snapshot["client"].get("logo_alt", CLIENT_LOGO_ALT))
    return HTML_TEMPLATE.replace("__REPORT_DATA_JSON__", safe_json(snapshot))


def csv_cell(value):
    if value is None:
        return ""
    value = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) if isinstance(value, (dict, list)) else str(value)
    return "'" + value if value.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else value


def csv_document(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(fields)
    for row in rows:
        writer.writerow([csv_cell(row.get(field)) for field in fields])
    return stream.getvalue()


def dependencies_csv_rows(snapshot):
    if snapshot.get("schema_version") == "databricks-dep-multi-workspace-v1":
        rows = [row for item in successful_snapshots(snapshot) for row in dependencies_csv_rows(item)]
        rows.extend(
            {
                "record_type": "workspace_collection_error",
                "classification": "UNKNOWN",
                "layer": "control_plane",
                "workspace_id": run["workspace_id"],
                "workspace_name": run["workspace_name"],
                "id": run["workspace_id"],
                "kind": "workspace_error",
                "label": run["workspace_name"],
                "source_ids": [run["error"]["source_id"]],
                "observed_at": run["reference_utc"],
                "details_json": run,
            }
            for run in snapshot["workspace_runs"] if run["snapshot"] is None
        )
        return rows
    dep = snapshot["dependencies"]
    rows = []
    for node in dep["nodes"]:
        rows.append({
            "record_type": "node",
            "classification": node["classification"],
            "layer": node["layer"],
            "workspace_id": node["workspace_id"],
            "workspace_name": node["workspace_name"],
            "id": node["id"],
            "kind": node["kind"],
            "label": node["label"],
            "from": "",
            "to": "",
            "relation": "",
            "join_fields": [],
            "source_ids": [node["source_id"]],
            "observed_at": node["observed_at"],
            "details_json": node,
        })
    for edge in dep["edges"]:
        rows.append({
            "record_type": "edge",
            "classification": edge["classification"],
            "layer": edge["layer"],
            "workspace_id": edge["workspace_id"],
            "workspace_name": edge["workspace_name"],
            "id": edge["id"],
            "kind": "dependency_edge",
            "label": edge["relation"],
            "from": edge["from"],
            "to": edge["to"],
            "relation": edge["relation"],
            "join_fields": edge["join_fields"],
            "source_ids": edge["source_ids"],
            "observed_at": edge["observed_at"],
            "details_json": edge,
        })
    for unk in dep["unknowns"]:
        rows.append({
            "record_type": "unknown",
            "classification": "UNKNOWN",
            "layer": unk["layer"],
            "workspace_id": unk["workspace_id"],
            "workspace_name": unk["workspace_name"],
            "id": unk["id"],
            "kind": unk["kind"],
            "label": unk["code"],
            "from": "",
            "to": "",
            "relation": "",
            "join_fields": [],
            "source_ids": unk["source_ids"],
            "observed_at": unk["observed_at"],
            "details_json": unk,
        })
    return rows


def artifact_directory():
    try:
        cwd = Path.cwd()
        root = cwd.resolve(strict=True)
        linked = any(part.is_symlink() or getattr(part, "is_junction", lambda: False)() for part in (cwd, *cwd.parents))
    except (OSError, RuntimeError) as exc:
        raise EvidenceError("unsafe_artifact_root", "Runtime cwd must resolve to an existing directory.", "artifact_storage") from exc
    if root == Path(root.anchor) or not root.is_dir() or linked:
        raise EvidenceError("unsafe_artifact_root", "Filesystem roots, symlink/junction cwd ancestors and non-directories are forbidden.", "artifact_storage")
    if OUTPUT_DIRECTORY != "databricks-dependency-reports":
        raise EvidenceError("unsafe_artifact_directory", "Only the fixed databricks-dependency-reports child is allowed.", "artifact_storage")
    directory = root / OUTPUT_DIRECTORY
    if directory.is_symlink() or getattr(directory, "is_junction", lambda: False)() or directory.resolve() != directory:
        raise EvidenceError("unsafe_artifact_directory", "Output directory is a symlink/junction or escapes cwd.", "artifact_storage")
    return root, directory


def sharing_fields(root, paths):
    result = {"sharing_mode": "local_files_only", "http_verified": False}
    match = re.fullmatch(
        r"/(?:root/sreagent|usr)/terminalRoot/tmp/ThreadFiles/([0-9a-fA-F-]{36})", root.as_posix()
    )
    if match is None:
        return result
    try:
        if str(UUID(match[1])) != match[1].lower():
            return result
    except ValueError:
        return result
    suffixes = {
        "report_path": ".html",
        "snapshot_path": "-snapshot.json",
        "findings_csv_path": "-findings.csv",
        "dependencies_csv_path": "-dependencies.csv",
    }
    if set(paths) != set(suffixes):
        raise EvidenceError("unsafe_sharing_path", "Native delivery requires exactly the four guarded report artifacts.", "artifact_storage")
    stem = paths["report_path"].name.removesuffix(".html")
    if not re.fullmatch(r"(?:dbx|simulated)-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}", stem):
        raise EvidenceError("unsafe_sharing_path", "Native aliases require this tool's generated run filenames.", "artifact_storage")
    expected = root / "databricks-dependency-reports"
    aliases = {}
    for key, path in paths.items():
        if path.parent != expected or path.name != stem + suffixes[key]:
            raise EvidenceError("unsafe_sharing_path", "Native aliases must reference the same run in the fixed report directory.", "artifact_storage")
        aliases[key.removesuffix("_path") + "_url"] = (
            "/api/files/tmp/ThreadFiles/" + match[1] + "/databricks-dependency-reports/" + quote(path.name, safe="")
        )
    return {**result, "sharing_mode": "native_ui", **aliases}


def report_envelope(snapshot, paths, root):
    items = successful_snapshots(snapshot)
    findings = [row for item in items for row in item["findings"]]
    multi = snapshot.get("schema_version") == "databricks-dep-multi-workspace-v1"
    aggregate = snapshot["aggregate"] if multi else None
    partial = any(s["status"] not in ("complete", "not_applicable") for item in items for s in item["sources"])
    inv_keys = ("clusters", "jobs", "pipelines", "sql_warehouses", "uc_catalogs", "uc_external_locations", "related_resources")
    result = {
        "status": "partial" if partial or (multi and aggregate["workspace_status_counts"].get("error")) else "ok",
        "operation": "self_test" if snapshot.get("provenance") == "SIMULATED" else "report",
        "artifact_status": "written",
        **sharing_fields(root, paths),
        "collection": collection_disclosure(snapshot),
        "global": aggregate["scores"]["global"] if multi else snapshot["scores"]["global"],
        "findings_total": len(findings),
        "inventory_counts": aggregate["inventory_counts"] if multi else {
            key: len(snapshot["inventory"].get(key) or []) for key in inv_keys
        },
        "dependency_counts": aggregate["dependency_counts"] if multi else snapshot["dependencies"]["summary_counts"],
        "critical_total": sum(row["severity"] == "critical" for row in findings),
        "estimated_savings": None,
        "databricks_costs": aggregate["databricks_costs"] if multi else cost_summary(snapshot.get("databricks_costs")),
        **{key: str(path) for key, path in paths.items()},
    }
    return ensure_response(result)


def write_report(snapshot):
    root, directory = artifact_directory()
    reference = snapshot["reference_utc"].replace(":", "").replace("-", "")
    prefix = ("simulated-" if snapshot["provenance"] == "SIMULATED" else "dbx-") + reference + "-" + uuid4().hex[:12]
    paths = {
        key: directory / (prefix + suffix)
        for key, suffix in (
            ("report_path", ".html"),
            ("snapshot_path", "-snapshot.json"),
            ("findings_csv_path", "-findings.csv"),
            ("dependencies_csv_path", "-dependencies.csv"),
        )
    }
    response = report_envelope(snapshot, paths, root)
    snapshot_document = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if json.loads(snapshot_document) != snapshot:
        raise EvidenceError("round_trip_failed", "Full normalized export does not round-trip.", "artifact_storage")
    documents = {
        "report_path": render_html(snapshot),
        "snapshot_path": snapshot_document,
        "findings_csv_path": csv_document(
            [{**row, "details_json": row} for item in successful_snapshots(snapshot) for row in item["findings"]],
            ("check_id", "rule_id", "reference_id", "title", "status", "level", "area", "pillar", "severity", "resource_id",
             "workspace_id", "workspace_name", "workload_name", "effort", "reason", "recommendation", "learn_url", "details_json"),
        ),
        "dependencies_csv_path": csv_document(
            dependencies_csv_rows(snapshot),
            ("record_type", "classification", "layer", "workspace_id", "workspace_name", "id", "kind", "label",
             "from", "to", "relation", "join_fields", "source_ids", "observed_at", "details_json"),
        ),
    }
    encoded = {key: value.encode("utf-8-sig" if key.endswith("csv_path") else "utf-8") for key, value in documents.items()}
    if any(len(value) > ARTIFACT_BYTES for value in encoded.values()):
        raise EvidenceError("artifact_size_exceeded", "Complete artifacts exceed 4800000 bytes; no records, sources or time windows were dropped and no files were written.", "artifact_storage")
    temporary, written = [], []
    try:
        directory.mkdir(exist_ok=True)
        if artifact_directory()[1] != directory or directory.resolve(strict=True) != directory or not directory.is_dir():
            raise EvidenceError("unsafe_artifact_directory", "Output directory changed after creation.", "artifact_storage")
        for key, data in encoded.items():
            if paths[key].exists() or paths[key].is_symlink():
                raise EvidenceError("artifact_collision", "A unique output path already exists; no overwrite.", "artifact_storage")
            fd, filename = tempfile.mkstemp(prefix=prefix + "-", suffix=".tmp", dir=directory)
            temp_path = Path(filename)
            temporary.append(temp_path)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, paths[key])
            temporary.remove(temp_path)
            written.append(paths[key])
        if any(path.read_bytes() != encoded[key] for key, path in paths.items()):
            raise EvidenceError("artifact_readback_failed", "Written artifact bytes differ from complete prepared content.", "artifact_storage")
        if json.loads(paths["snapshot_path"].read_text(encoding="utf-8")) != snapshot:
            raise EvidenceError("artifact_readback_failed", "Written full normalized evidence differs from source-normalized data.", "artifact_storage")
    except (OSError, EvidenceError) as exc:
        failures = []
        for path in temporary + written:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                failures.append(path.name)
        if failures:
            raise EvidenceError(
                "artifact_cleanup_failed",
                "Artifact failure and cleanup failure; inspect these generated files in the fixed output directory: " + ", ".join(failures),
                "artifact_storage",
            ) from exc
        if isinstance(exc, EvidenceError):
            raise
        raise EvidenceError("artifact_write_failed", "Could not atomically write/read back all four files; this run's partial files were removed.", "artifact_storage") from exc
    return response


def main(
    operation: str = "report",
    view: str = "summary",
    workspace_name: str = "",
    workspace_names: str = "",
    workload_name: str = "",
    classification: str = "all",
    area: str = "all",
    level: str = "all",
    severity: str = "all",
    status: str = "all",
    limit: int = 25,
    offset: int = 0,
) -> dict:
    """Collect one or several fixed approved Azure Databricks workspaces; never change source scope or identity."""
    try:
        params = validate_parameters(
            operation, view, workspace_name, workspace_names, workload_name,
            classification, area, level, severity, status, limit, offset,
        )
        if operation == "self_test":
            validate_cost_settings()
            presentation_settings()
            validate_logo(CLIENT_LOGO_DATA_URI, CLIENT_LOGO_ALT)
            if not CATALOG.get("rules"):
                raise EvidenceError("catalog_missing", "Use the build-generated whole-file tool, not unbuilt engine.py.", "rule_catalog")
            reference = utc_now()
            raw = demo_raw(reference)
            snapshot = finish_snapshot(raw, reference, provenance="SIMULATED", environment="PRODUCTION")
            snapshot.update(available_workspaces=raw["demo_roster"], selected_workspace_names=[raw["demo_roster"][0]["workspace_name"]])
            return write_report(snapshot)
        configs, roster = selection_configs(workspace_name, workspace_names)
        if operation == "list_workspaces":
            return ensure_response({
                "status": "ok",
                "operation": operation,
                "fresh_collection": False,
                "roster_basis": "fixed_operator_configuration_not_observed_inventory",
                "available_workspaces": roster,
                "total": len(roster),
            })
        if not CATALOG.get("rules"):
            raise EvidenceError("catalog_missing", "Use the build-generated whole-file tool, not unbuilt engine.py.", "rule_catalog")
        reference = utc_now()
        if len(configs) == 1:
            config = configs[0]
            raw = collect_live(config, reference)
            snapshot = finish_snapshot(raw, reference, environment=config["environment"])
            snapshot.update(available_workspaces=roster, selected_workspace_names=[config["name"]])
        else:
            runs = []
            deadline = time.monotonic() + MAX_COLLECTION_SECONDS
            for config in configs:
                run_reference = utc_now()
                run = {
                    "workspace_id": config["id"],
                    "workspace_name": config["name"],
                    "reference_utc": run_reference,
                    "snapshot": None,
                    "error": None,
                    "status": "error",
                }
                try:
                    if time.monotonic() >= deadline:
                        raise EvidenceError("collection_deadline", "Shared multi-workspace time bound reached; this workspace was not collected, not empty/healthy.", "collection")
                    raw = collect_live(config, run_reference, deadline=deadline)
                    run["snapshot"] = finish_snapshot(raw, run_reference, environment=config["environment"])
                    run["status"] = "partial" if any(
                        source["status"] not in ("complete", "not_applicable") for source in run["snapshot"]["sources"]
                    ) else "ok"
                except EvidenceError as exc:
                    run["error"] = exc.public()
                runs.append(run)
            snapshot = multi_snapshot(runs, reference, roster)
            if not successful_snapshots(snapshot):
                return ensure_response({
                    "status": "error",
                    "error": {
                        "code": "all_workspaces_failed",
                        "source": "arm_workspace",
                        "message": "No selected workspace produced a snapshot; no empty/healthy report or files.",
                    },
                    "artifact_status": "not_written",
                    "workspace_errors": [
                        {
                            "workspace_name": run["workspace_name"],
                            "error": {key: run["error"].get(key) for key in ("code", "source_id", "http_status")},
                        }
                        for run in runs
                    ],
                    "provenance": "LIVE",
                })
        return query_snapshot(snapshot, params) if operation == "query" else write_report(snapshot)
    except EvidenceError as exc:
        return ensure_response({
            "status": "error",
            "error": exc.public(),
            "artifact_status": "cleanup_failed" if exc.code == "artifact_cleanup_failed" else "not_written",
            "provenance": "LIVE",
        })
