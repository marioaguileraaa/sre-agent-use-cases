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
        "requirements": {},
    }
}

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
MAX_COLLECTION_SECONDS = 240
MAX_HTTP_ATTEMPTS = 300
OUTPUT_DIRECTORY = "databricks-dependency-reports"
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
    'e_lineage or system.billing.usage.", "Cross-tenant collection requires explicit administrator-config'
    'ured federation or Azure Lighthouse delegation; a single-tenant SRE UAMI never acquires foreign-tena'
    'nt tokens implicitly.", "Configuration presence does not prove effective firewall enforcement, data-'
    'plane network reachability, least-privilege Unity Catalog grants or workload SLA compliance."], "rul'
    'es": [{"rule_id": "C01", "reference_id": "DBX-WAF-SEC-01", "test": "sku_premium", "level": "workspac'
    'e", "area": "security", "pillar": "security", "severity": "high", "effort": "medium", "title": "SKU '
    'Premium para gobernanza y controles de seguridad", "recommendation": "Validar el uso del tier Premiu'
    'm para cargas de producci\\u00f3n que requieren Unity Catalog, control de acceso basado en roles y au'
    'ditor\\u00eda avanzada.", "business_impact": "Un tier inferior a Premium puede limitar controles de i'
    'dentidad, Unity Catalog y aislamiento de acceso.", "learn_url": "https://learn.microsoft.com/en-us/a'
    'zure/well-architected/service-guides/azure-databricks#cost-optimization"}, {"rule_id": "C02", "refer'
    'ence_id": "DBX-WAF-SEC-02", "test": "secure_cluster_connectivity", "level": "workspace", "area": "se'
    'curity", "pillar": "security", "severity": "high", "effort": "medium", "title": "Secure Cluster Conn'
    'ectivity (No Public IP)", "recommendation": "Habilitar enableNoPublicIp en el workspace para que los'
    ' nodos de c\\u00f3mputo no tengan direcciones IP p\\u00fablicas y conecten al plano de control por rel'
    '\\u00e9 saliente.", "business_impact": "Nodos de cl\\u00faster con IP p\\u00fablica incrementan la supe'
    'rficie de exposici\\u00f3n de red del plano de datos.", "learn_url": "https://learn.microsoft.com/en-'
    'us/azure/databricks/security/network/classic/secure-cluster-connectivity"}, {"rule_id": "C03", "refe'
    'rence_id": "DBX-WAF-NET-01", "test": "vnet_injection", "level": "workspace", "area": "best_practices'
    '", "pillar": "security", "severity": "medium", "effort": "high", "title": "Despliegue con VNet Injec'
    'tion en red gestionada por el cliente", "recommendation": "Cuando la arquitectura de red corporativa'
    ' lo requiera, desplegar el workspace con customVirtualNetworkId y subredes host/container dedicadas.'
    '", "business_impact": "La VNet administrada por defecto impide aplicar rutas personalizadas, inspecc'
    'i\\u00f3n de egress o emparejamientos granulares.", "learn_url": "https://learn.microsoft.com/en-us/a'
    'zure/databricks/security/network/classic/vnet-inject"}, {"rule_id": "C04", "reference_id": "DBX-WAF-'
    'NET-02", "test": "private_link_and_public_access", "level": "workspace", "area": "security", "pillar'
    '": "security", "severity": "high", "effort": "high", "title": "Restricci\\u00f3n de red p\\u00fablica '
    'y Private Link del workspace", "recommendation": "Revisar publicNetworkAccess, requiredNsgRules y co'
    'nexiones Private Endpoint aprobadas seg\\u00fan los requisitos de aislamiento privado.", "business_im'
    'pact": "El acceso p\\u00fablico abierto sin controles compensatorios ampl\\u00eda la superficie de ent'
    'rada al workspace.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/security/netwo'
    'rk/classic/private-link"}, {"rule_id": "C05", "reference_id": "DBX-WAF-SEC-03", "test": "access_conn'
    'ector_and_storage_firewall", "level": "workspace", "area": "security", "pillar": "security", "severi'
    'ty": "medium", "effort": "medium", "title": "Access Connector con identidad administrada y firewall '
    'de almacenamiento", "recommendation": "Vincular un Azure Databricks Access Connector con identidad a'
    'dministrada (SystemAssigned o UserAssigned) y revisar defaultStorageFirewall.", "business_impact": "'
    'La ausencia de Access Connector impide autenticar con identidad administrada hacia almacenamiento go'
    'bernado.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/connect/unity-catalog/cl'
    'oud-storage/azure-managed-identities"}, {"rule_id": "C06", "reference_id": "DBX-WAF-SEC-04", "test":'
    ' "customer_managed_keys", "level": "workspace", "area": "security", "pillar": "security", "severity"'
    ': "medium", "effort": "medium", "title": "Cifrado con claves gestionadas por el cliente (CMK) e infr'
    'aestructura", "recommendation": "Si la pol\\u00edtica de cumplimiento exige CMK, configurar claves de'
    ' Key Vault para managedServices y managedDisk con rotaci\\u00f3n autom\\u00e1tica.", "business_impact"'
    ': "Sin CMK cuando es requerido por normativa, el cliente no controla directamente la revocaci\\u00f3n'
    ' criptogr\\u00e1fica.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/security/key'
    's/"}, {"rule_id": "C07", "reference_id": "DBX-WAF-SEC-05", "test": "enhanced_security_compliance", "'
    'level": "workspace", "area": "security", "pillar": "operations", "severity": "low", "effort": "mediu'
    'm", "title": "Perfil de seguridad mejorada y actualizaci\\u00f3n autom\\u00e1tica de cl\\u00fasteres", '
    '"recommendation": "Evaluar enhancedSecurityMonitoring, automaticClusterUpdate y complianceSecurityPr'
    'ofile cuando apliquen normativas espec\\u00edficas.", "business_impact": "Sin actualizaciones autom\\u'
    '00e1ticas o monitorizaci\\u00f3n mejorada requerida, el mantenimiento de agentes depende de procesos '
    'manuales.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/security/privacy/securi'
    'ty-profile"}, {"rule_id": "C08", "reference_id": "DBX-WAF-OPS-01", "test": "diagnostics", "level": "'
    'workspace", "area": "best_practices", "pillar": "operations", "severity": "medium", "effort": "low",'
    ' "title": "Configuraci\\u00f3n de Diagnostic Settings en el plano de control ARM", "recommendation": '
    '"Configurar categor\\u00edas de auditor\\u00eda en Microsoft.Insights/diagnosticSettings hacia Log Ana'
    'lytics, Storage o Event Hub y verificar la ingesta.", "business_impact": "Sin registros diagn\\u00f3s'
    'ticos habilitados se reduce la trazabilidad de eventos de control plane, jobs y accesos.", "learn_ur'
    'l": "https://learn.microsoft.com/en-us/azure/databricks/admin/account-settings/audit-logs"}, {"rule_'
    'id": "C09", "reference_id": "DBX-WAF-SEC-06", "test": "pat_token_governance", "level": "workspace", '
    '"area": "security", "pillar": "security", "severity": "medium", "effort": "low", "title": "Gobernanz'
    'a de Personal Access Tokens (PAT) en workspace-conf", "recommendation": "Revisar enableTokensConfig '
    'y priorizar autenticaci\\u00f3n OAuth M2M o identidades administradas de Microsoft Entra frente a PAT'
    's duraderos.", "business_impact": "Tokens personales sin control de emisi\\u00f3n o expiraci\\u00f3n i'
    'ncrementan el riesgo de credenciales persistentes.", "learn_url": "https://learn.microsoft.com/en-us'
    '/azure/databricks/security/auth/api-access-permissions"}, {"rule_id": "C10", "reference_id": "DBX-WA'
    'F-GOV-01", "test": "default_catalog_unity", "level": "workspace", "area": "best_practices", "pillar"'
    ': "operations", "severity": "medium", "effort": "medium", "title": "Cat\\u00e1logo predeterminado en '
    'Unity Catalog frente a Hive heredado", "recommendation": "Configurar UnityCatalog como cat\\u00e1logo'
    ' predeterminado y evitar almacenar datos de negocio en el DBFS root o hive_metastore.", "business_im'
    'pact": "El uso de hive_metastore y DBFS root dificulta el control de acceso unificado y el linaje de'
    ' datos.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/data-governance/unity-cat'
    'alog/best-practices"}, {"rule_id": "C11", "reference_id": "DBX-WAF-SEC-07", "test": "global_init_scr'
    'ipts", "level": "workspace", "area": "security", "pillar": "security", "severity": "low", "effort": '
    '"low", "title": "Higiene y revisi\\u00f3n de Global Init Scripts", "recommendation": "Minimizar o aud'
    'itar los global init scripts habilitados y preferir pol\\u00edticas de cl\\u00faster o scripts con alc'
    'ance de unidad en Unity Catalog.", "business_impact": "Los global init scripts se ejecutan en todos '
    'los cl\\u00fasteres del workspace y pueden introducir dependencias ocultas o superficie de fallo.", "'
    'learn_url": "https://learn.microsoft.com/en-us/azure/databricks/init-scripts/global"}, {"rule_id": "'
    'C12", "reference_id": "DBX-WAF-OPS-02", "test": "advisor", "level": "workspace", "area": "optimizati'
    'on", "pillar": "operations", "severity": "low", "effort": "low", "title": "Revisi\\u00f3n de recomend'
    'aciones cacheadas de Azure Advisor", "recommendation": "Consultar las recomendaciones cacheadas de A'
    'zure Advisor para el workspace y recursos asociados como insumo complementario.", "business_impact":'
    ' "Ignorar alertas de plataforma puede retrasar la detecci\\u00f3n de mejoras de fiabilidad o coste.",'
    ' "learn_url": "https://learn.microsoft.com/en-us/azure/well-architected/service-guides/azure-databri'
    'cks"}, {"rule_id": "W01", "reference_id": "DBX-WAF-COST-01", "test": "cluster_autotermination", "lev'
    'el": "workload", "area": "finops", "pillar": "cost", "severity": "high", "effort": "low", "title": "'
    'Autoterminaci\\u00f3n configurada en cl\\u00fasteres interactivos All-Purpose", "recommendation": "Def'
    'inir autotermination_minutes (por ejemplo <= 60 minutos) en todos los cl\\u00fasteres All-Purpose par'
    'a evitar consumo DBU y VM en inactividad.", "business_impact": "Un cl\\u00faster interactivo sin auto'
    'terminaci\\u00f3n o con umbral excesivo mantiene nodos facturando sin carga activa.", "learn_url": "h'
    'ttps://learn.microsoft.com/en-us/azure/databricks/compute/cluster-config-best-practices"}, {"rule_id'
    '": "W02", "reference_id": "DBX-WAF-GOV-02", "test": "cluster_policy_bound", "level": "workload", "ar'
    'ea": "best_practices", "pillar": "cost", "severity": "medium", "effort": "medium", "title": "Cl\\u00f'
    'asteres gobernados mediante Cluster Policy", "recommendation": "Asociar policy_id a los cl\\u00faster'
    'es para aplicar l\\u00edmites de tipo de instancia, autoterminaci\\u00f3n, versi\\u00f3n de runtime y e'
    'tiquetas FinOps.", "business_impact": "Crear cl\\u00fasteres sin pol\\u00edtica permite configuracione'
    's no estandarizadas y sobrecostes accidentales.", "learn_url": "https://learn.microsoft.com/en-us/az'
    'ure/databricks/admin/clusters/policies"}, {"rule_id": "W03", "reference_id": "DBX-WAF-SEC-08", "test'
    '": "cluster_access_mode", "level": "workload", "area": "security", "pillar": "security", "severity":'
    ' "high", "effort": "medium", "title": "Modo de acceso de c\\u00f3mputo compatible con aislamiento y U'
    'nity Catalog", "recommendation": "Configurar data_security_mode en USER_ISOLATION (Standard/Shared) '
    'o SINGLE_USER (Dedicated) y evitar modos sin aislamiento (NONE).", "business_impact": "Modos de acce'
    'so heredados o sin aislamiento impiden aplicar controles de Unity Catalog o permiten acceso directo '
    'no gobernado.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/compute/configure#a'
    'ccess-mode"}, {"rule_id": "W04", "reference_id": "DBX-WAF-OPS-03", "test": "cluster_runtime_lts", "l'
    'evel": "workload", "area": "best_practices", "pillar": "reliability", "severity": "medium", "effort"'
    ': "medium", "title": "Versi\\u00f3n de Databricks Runtime soportada (LTS / actual)", "recommendation"'
    ': "Mantener spark_version en una versi\\u00f3n Long Term Support (LTS) vigente (por ejemplo 13.3 LTS,'
    ' 14.3 LTS, 15.4 LTS o superior).", "business_impact": "Versiones antiguas de Databricks Runtime pier'
    'den soporte, parches de seguridad y optimizaciones de Photon/Delta.", "learn_url": "https://learn.mi'
    'crosoft.com/en-us/azure/databricks/release-notes/runtime/"}, {"rule_id": "W05", "reference_id": "DBX'
    '-WAF-PERF-01", "test": "cluster_autoscaling_or_pool", "level": "workload", "area": "optimization", "'
    'pillar": "performance", "severity": "low", "effort": "low", "title": "Escalado din\\u00e1mico (Autosc'
    'ale) o uso de Instance Pool en cl\\u00fasteres", "recommendation": "Evaluar autoscale (min_workers/ma'
    'x_workers) o vinculaci\\u00f3n a instance_pool_id para adaptar capacidad a variaciones de carga.", "b'
    'usiness_impact": "Un n\\u00famero fijo de workers sin pool puede infrautilizar recursos en valles o l'
    'imitar concurrencia en picos.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/com'
    'pute/cluster-config-best-practices#autoscaling"}, {"rule_id": "W06", "reference_id": "DBX-WAF-COST-0'
    '2", "test": "job_uses_job_compute", "level": "workload", "area": "finops", "pillar": "cost", "severi'
    'ty": "high", "effort": "medium", "title": "Jobs programados ejecutando en Job Compute o Serverless e'
    'n lugar de All-Purpose", "recommendation": "Migrar las tareas de Jobs que apuntan a existing_cluster'
    '_id hacia job_cluster_key o c\\u00f3mputo Serverless de Jobs.", "business_impact": "Ejecutar jobs aut'
    'omatizados sobre cl\\u00fasteres All-Purpose consume tarifas DBU m\\u00e1s altas y acopla fallos entre'
    ' cargas.", "learn_url": "https://learn.microsoft.com/en-us/azure/well-architected/service-guides/azu'
    're-databricks#cost-optimization"}, {"rule_id": "W07", "reference_id": "DBX-WAF-REL-01", "test": "job'
    '_resilience_settings", "level": "workload", "area": "best_practices", "pillar": "reliability", "seve'
    'rity": "medium", "effort": "low", "title": "Timeouts, reintentos o notificaciones en Jobs de orquest'
    'aci\\u00f3n", "recommendation": "Configurar timeout_seconds, pol\\u00edticas de reintento y notificaci'
    'ones o alertas en los Jobs cr\\u00edticos para detectar ejecuciones colgadas o fallidas.", "business_'
    'impact": "Un job sin timeout ni alertas puede quedar bloqueado consumiendo recursos o incumplir vent'
    'anas de datos sin aviso.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/jobs/con'
    'figure-job"}, {"rule_id": "W08", "reference_id": "DBX-WAF-SEC-09", "test": "job_service_principal_ru'
    'n_as", "level": "workload", "area": "security", "pillar": "operations", "severity": "medium", "effor'
    't": "medium", "title": "Ejecuci\\u00f3n de Jobs mediante Service Principal (run_as)", "recommendation'
    '": "Configurar run_as con un Service Principal dedicado en lugar de una cuenta de usuario individual'
    ' para evitar fallos ante bajas o cambios de rol.", "business_impact": "Los jobs ejecutados bajo iden'
    'tidad de usuario fallan si el usuario deja la organizaci\\u00f3n o pierde permisos.", "learn_url": "h'
    'ttps://learn.microsoft.com/en-us/azure/databricks/admin/users-groups/service-principals"}, {"rule_id'
    '": "W09", "reference_id": "DBX-WAF-COST-03", "test": "sql_warehouse_autostop", "level": "workload", '
    '"area": "finops", "pillar": "cost", "severity": "medium", "effort": "low", "title": "Auto-stop y arq'
    'uitectura Serverless/Pro en SQL Warehouses", "recommendation": "Configurar auto_stop_mins (<= 30 min'
    'utos) o usar SQL Warehouses Serverless para cargas BI e interactivas con demanda variable.", "busine'
    'ss_impact": "Un SQL Warehouse sin auto-stop mantiene capacidad facturable activa fuera de las ventan'
    'as de consulta.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/compute/sql-wareh'
    'ouse/create"}, {"rule_id": "W10", "reference_id": "DBX-WAF-GOV-03", "test": "pipeline_unity_catalog"'
    ', "level": "workload", "area": "best_practices", "pillar": "operations", "severity": "medium", "effo'
    'rt": "medium", "title": "Pipelines declarativos (Lakeflow / DLT) publicados en Unity Catalog", "reco'
    'mmendation": "Definir un cat\\u00e1logo de Unity Catalog en los pipelines declarativos para asegurar '
    'linaje nativo y gobernanza de tablas.", "business_impact": "Los pipelines publicados en hive_metasto'
    're quedan fuera del modelo centralizado de permisos y linaje.", "learn_url": "https://learn.microsof'
    't.com/en-us/azure/databricks/ldp/unity-catalog"}, {"rule_id": "G01", "reference_id": "DBX-WAF-GOV-04'
    '", "test": "uc_metastore_attached", "level": "workspace", "area": "best_practices", "pillar": "secur'
    'ity", "severity": "high", "effort": "high", "title": "Asignaci\\u00f3n de Metastore de Unity Catalog '
    'al workspace", "recommendation": "Vincular el workspace a un Metastore regional de Unity Catalog par'
    'a centralizar identidades, control de acceso, auditor\\u00eda y linaje.", "business_impact": "Sin Met'
    'astore adjunto no est\\u00e1n disponibles las capacidades de gobierno unificado, ubicaciones externas'
    ' ni tablas de sistema.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/data-gover'
    'nance/unity-catalog/get-started"}, {"rule_id": "G02", "reference_id": "DBX-WAF-SEC-10", "test": "uc_'
    'storage_credential_mi", "level": "workspace", "area": "security", "pillar": "security", "severity": '
    '"high", "effort": "medium", "title": "Storage Credentials de Unity Catalog basadas en Managed Identi'
    'ty", "recommendation": "Usar Azure Managed Identity (v\\u00eda Access Connector) en las Storage Crede'
    'ntials de Unity Catalog en lugar de secretos de Service Principal.", "business_impact": "Las credenc'
    'iales basadas en secretos requieren rotaci\\u00f3n manual y aumentan el riesgo ante filtraciones.", "'
    'learn_url": "https://learn.microsoft.com/en-us/azure/databricks/connect/unity-catalog/cloud-storage/'
    'storage-credentials"}, {"rule_id": "G03", "reference_id": "DBX-WAF-GOV-05", "test": "uc_external_loc'
    'ations_governed", "level": "workspace", "area": "security", "pillar": "security", "severity": "mediu'
    'm", "effort": "medium", "title": "External Locations con Storage Credential v\\u00e1lida y rutas ADLS'
    ' Gen2 expl\\u00edcitas", "recommendation": "Verificar que cada External Location enlace con una Stora'
    'ge Credential existente, utilice abfss:// y aplique vinculaci\\u00f3n por workspace cuando proceda.",'
    ' "business_impact": "Ubicaciones externas hu\\u00e9rfanas o sin aislamiento pueden exponer contenedor'
    'es compartidos entre entornos.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/da'
    'ta-governance/unity-catalog/best-practices#external-locations"}, {"rule_id": "G04", "reference_id": '
    '"DBX-WAF-SEC-11", "test": "secret_scopes_keyvault", "level": "workspace", "area": "security", "pilla'
    'r": "security", "severity": "medium", "effort": "medium", "title": "Secret Scopes respaldados por Az'
    'ure Key Vault", "recommendation": "Preferir Secret Scopes con backend AZURE_KEYVAULT frente a scopes'
    ' locales DATABRICKS cuando se requiera gesti\\u00f3n centralizada de secretos.", "business_impact": "'
    'Los scopes locales de Databricks no se integran directamente con las pol\\u00edticas de rotaci\\u00f3n'
    ' y auditor\\u00eda de Azure Key Vault.", "learn_url": "https://learn.microsoft.com/en-us/azure/databr'
    'icks/security/secrets/secret-scopes"}, {"rule_id": "G05", "reference_id": "DBX-WAF-REL-02", "test": '
    '"dependency_integrity", "level": "workspace", "area": "best_practices", "pillar": "reliability", "se'
    'verity": "high", "effort": "medium", "title": "Integridad referencial del mapa de dependencias de Jo'
    'bs, C\\u00f3mputo y Gobernanza", "recommendation": "Corregir referencias rotas en tareas de Jobs (cl\\'
    'u00fasteres eliminados, SQL Warehouses inexistentes, pipelines o jobs hijos ausentes y credenciales '
    'no resueltas).", "business_impact": "Una dependencia rota observada en la definici\\u00f3n de un Job '
    'provocar\\u00e1 fallos inmediatos de ejecuci\\u00f3n en producci\\u00f3n.", "learn_url": "https://learn'
    '.microsoft.com/en-us/azure/databricks/jobs/configure-job"}, {"rule_id": "G06", "reference_id": "DBX-'
    'WAF-GOV-06", "test": "runtime_table_lineage", "level": "workspace", "area": "optimization", "pillar"'
    ': "operations", "severity": "low", "effort": "medium", "title": "Linaje din\\u00e1mico de tablas y co'
    'lumnas (system.access.table_lineage)", "recommendation": "Si se requiere linaje en tiempo de ejecuci'
    '\\u00f3n a nivel de tabla/columna, habilitar y consultar system.access.table_lineage en una sesi\\u00f'
    '3n autorizada sin arrancar c\\u00f3mputo autom\\u00e1ticamente desde este colector.", "business_impact'
    '": "El an\\u00e1lisis de plano de control mapea dependencias declaradas, pero no las lecturas/escritu'
    'ras SQL din\\u00e1micas dentro de notebooks.", "learn_url": "https://learn.microsoft.com/en-us/azure/'
    'databricks/admin/system-tables/lineage"}, {"rule_id": "G07", "reference_id": "DBX-WAF-GOV-07", "test'
    '": "lakehouse_federation_connections", "level": "workspace", "area": "best_practices", "pillar": "op'
    'erations", "severity": "low", "effort": "low", "title": "Gobernanza de conexiones externas en Unity '
    'Catalog (Lakehouse Federation)", "recommendation": "Inventariar las conexiones de Lakehouse Federati'
    'on en Unity Catalog y verificar sus dependencias de red y credenciales.", "business_impact": "Las co'
    'nexiones federadas externas representan dependencias cr\\u00edticas hacia motores SQL o plataformas d'
    'e terceros.", "learn_url": "https://learn.microsoft.com/en-us/azure/databricks/query-federation/"}, '
    '{"rule_id": "G08", "reference_id": "DBX-WAF-NET-03", "test": "outbound_control_plane_endpoints", "le'
    'vel": "workspace", "area": "best_practices", "pillar": "reliability", "severity": "medium", "effort"'
    ': "low", "title": "Visibilidad de dependencias de red saliente (outboundNetworkDependenciesEndpoints'
    ')", "recommendation": "Contrastar las reglas de firewall/UDR/NSG con la lista oficial de endpoints s'
    'alientes requeridos por el workspace hacia el plano de control.", "business_impact": "Bloquear depen'
    'dencias salientes requeridas (Webapp, Control Plane NAT, Storage, Metastore, EventHub/ServiceBus) im'
    'pide el arranque de cl\\u00fasteres.", "learn_url": "https://learn.microsoft.com/en-us/azure/databric'
    'ks/administration-guide/cloud-configurations/azure/udr"}, {"rule_id": "R01", "reference_id": "DBX-WA'
    'F-RES-01", "test": "storage_tls_and_public_blob", "level": "resource", "area": "security", "pillar":'
    ' "security", "severity": "high", "effort": "low", "title": "Cuentas de almacenamiento asociadas con '
    'HTTPS, TLS 1.2+ y sin acceso p\\u00fablico a blobs", "recommendation": "Exigir supportsHttpsTrafficOn'
    'ly=true, minimumTlsVersion=TLS1_2 y allowBlobPublicAccess=false en las cuentas ADLS Gen2 asociadas."'
    ', "business_impact": "Permitir tr\\u00e1fico no cifrado o acceso an\\u00f3nimo a contenedores expone a'
    'ctivos del lakehouse.", "learn_url": "https://learn.microsoft.com/en-us/azure/storage/blobs/security'
    '-recommendations"}, {"rule_id": "R02", "reference_id": "DBX-WAF-RES-02", "test": "storage_shared_key'
    '_and_network", "level": "resource", "area": "security", "pillar": "security", "severity": "medium", '
    '"effort": "medium", "title": "Restricci\\u00f3n de Shared Key y acceso de red en cuentas de almacenam'
    'iento asociadas", "recommendation": "Evaluar la deshabilitaci\\u00f3n de allowSharedKeyAccess y restr'
    'ingir publicNetworkAccess en cuentas ADLS Gen2 gobernadas por Entra ID / Unity Catalog.", "business_'
    'impact": "Las claves compartidas de cuenta eluden los controles granulares de identidad de Microsoft'
    ' Entra y Unity Catalog.", "learn_url": "https://learn.microsoft.com/en-us/azure/storage/common/share'
    'd-key-authorization-prevent"}, {"rule_id": "R03", "reference_id": "DBX-WAF-RES-03", "test": "keyvaul'
    't_rbac_and_purge", "level": "resource", "area": "security", "pillar": "security", "severity": "mediu'
    'm", "effort": "medium", "title": "Autorizaci\\u00f3n RBAC y protecci\\u00f3n contra purga en Key Vault'
    's asociados", "recommendation": "Habilitar enableRbacAuthorization y enablePurgeProtection en los Ke'
    'y Vaults vinculados a Secret Scopes o claves CMK del workspace.", "business_impact": "Sin protecci\\u'
    '00f3n contra purga, la eliminaci\\u00f3n accidental o maliciosa de una clave CMK o secreto puede ser '
    'irreversible.", "learn_url": "https://learn.microsoft.com/en-us/azure/key-vault/general/security-fea'
    'tures"}, {"rule_id": "R04", "reference_id": "DBX-WAF-RES-04", "test": "nsg_exposure", "level": "reso'
    'urce", "area": "security", "pillar": "security", "severity": "high", "effort": "medium", "title": "E'
    'xposici\\u00f3n de puertos administrativos desde Internet en NSG asociados", "recommendation": "Elimi'
    'nar o restringir reglas Inbound Allow desde Internet (0.0.0.0/0, *, Internet) hacia SSH (22), RDP (3'
    '389) o todos los puertos en subredes del workspace.", "business_impact": "Reglas de entrada abiertas'
    ' desde Internet hacia las subredes de cl\\u00faster violan el aislamiento del plano de datos.", "lear'
    'n_url": "https://learn.microsoft.com/en-us/azure/databricks/security/network/classic/vnet-inject"}, '
    '{"rule_id": "R05", "reference_id": "DBX-WAF-RES-05", "test": "private_endpoint_approved", "level": "'
    'resource", "area": "best_practices", "pillar": "reliability", "severity": "medium", "effort": "low",'
    ' "title": "Estado aprobado en conexiones Private Endpoint asociadas", "recommendation": "Confirmar q'
    'ue todas las conexiones Private Endpoint asociadas al workspace o recursos vinculados est\\u00e9n en '
    'estado Approved.", "business_impact": "Un Private Endpoint en estado Pending, Rejected o Disconnecte'
    'd interrumpe la conectividad privada prevista.", "learn_url": "https://learn.microsoft.com/en-us/azu'
    're/databricks/security/network/classic/private-link"}, {"rule_id": "R06", "reference_id": "DBX-WAF-C'
    'OST-04", "test": "cost_attribution", "level": "workspace", "area": "finops", "pillar": "cost", "seve'
    'rity": "low", "effort": "medium", "title": "Atribuci\\u00f3n de costes reales (ActualCost) y granular'
    'idad DBU por carga", "recommendation": "Combinar los costes reales ARM observados con el etiquetado '
    'de cl\\u00fasteres/jobs y la tabla system.billing.usage para atribuir consumo DBU por equipo o pipeli'
    'ne.", "business_impact": "ActualCost a nivel de ResourceId de Azure no desglosa por s\\u00ed solo el '
    'consumo interno de cada Job, SQL Warehouse o usuario.", "learn_url": "https://learn.microsoft.com/en'
    '-us/azure/databricks/admin/system-tables/billing"}]}'
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
    "efault-src 'none'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src"
    ' \'none\'; base-uri \'none\'; form-action \'none\'; object-src \'none\'">\n<meta name="color-scheme" content='
    '"light dark">\n<title>Revisión Azure Databricks | Mapa de dependencias y configuración</title>\n<style'
    '>\n:root{\ncolor-scheme:light;\n--brand-navy: #003865; --brand-lava: #ff3621; --brand-steel: #0066a1; -'
    '-brand-teal: #00875a;\n--paper:#f2f5f8;--surface:#ffffff;--soft:#eef2f6;--hover:#f6f9fc;\n--ink:#16212'
    'c;--title:#002b4e;--muted:#4f5d6b;--line:#dde3ea;--line2:#c2ccd6;\n--link:#0058a3;--focus:#0b6bcb;--s'
    'el:#cfe3f7;--chart:#0066a1;--edge:#4d7aa3;\n--bar-bg:#ffffff;--bar-hover:#eef2f6;--btn:#003865;--btn-'
    'hover:#002848;--btn-ink:#ffffff;\n--hero-a:#003865;--hero-b:#00223c;--hero-muted:#c3d5e8;--hero-line:'
    'rgba(255,255,255,.24);\n--shadow:0 1px 2px rgba(16,24,40,.05),0 10px 28px rgba(16,24,40,.07);\n--crit-'
    'ink:#b42318;--crit-bg:#fee4e2;--crit-bar:#d92d20;\n--high-ink:#b93815;--high-bg:#ffead5;--high-bar:#e'
    'f6820;\n--med-ink:#93370d;--med-bg:#fef0c7;--med-bar:#f79009;\n--low-ink:#175cd3;--low-bg:#d1e9ff;--lo'
    'w-bar:#2e90fa;\n--info-ink:#344054;--info-bg:#eaecf0;--info-bar:#98a2b3;\n--ok-ink:#067647;--ok-bg:#dc'
    'fae6;--ok-bar:#17b26a;\n--obs-ink:#00603f;--obs-bg:#ddf4ea;--obs-line:#00875a;\n--inf-ink:#8a4b00;--in'
    'f-bg:#fff1d6;--inf-line:#c77700;\n--unk-ink:#475467;--unk-bg:#eaecf0;--unk-line:#98a2b3;\n}\n:root[data'
    '-theme="dark"]{\ncolor-scheme:dark;\n--paper:#0d141b;--surface:#15202a;--soft:#1c2834;--hover:#19242f;'
    '\n--ink:#e6edf3;--title:#f1f6fb;--muted:#a9b7c5;--line:#26333f;--line2:#3a4a5a;\n--link:#8cc8ff;--focu'
    's:#8cc8ff;--sel:#24476b;--chart:#6fb6f0;--edge:#7aa7cf;\n--bar-bg:#101920;--bar-hover:#1c2834;--btn:#'
    '8cc8ff;--btn-hover:#a9d6ff;--btn-ink:#0b1620;\n--hero-a:#0a2742;--hero-b:#061626;--hero-muted:#bdd0e3'
    ';\n--shadow:0 1px 2px rgba(0,0,0,.35),0 10px 28px rgba(0,0,0,.35);\n--crit-ink:#ffb4ab;--crit-bg:#4a1c'
    '1a;--high-ink:#ffc29e;--high-bg:#4a2614;\n--med-ink:#fedf89;--med-bg:#45330f;--low-ink:#a8d4ff;--low-'
    'bg:#13304f;\n--info-ink:#d0d5dd;--info-bg:#2a3441;--ok-ink:#a6f4c5;--ok-bg:#133a28;\n--obs-ink:#8ce9bf'
    ';--obs-bg:#12382a;--inf-ink:#f5d875;--inf-bg:#3d3216;--unk-ink:#cbd5e1;--unk-bg:#2a3441;\n}\n*{box-siz'
    'ing:border-box}\nhtml{scroll-padding-top:78px;-webkit-text-size-adjust:100%;scrollbar-color:var(--lin'
    'e2) var(--paper)}\nbody{margin:0;background:var(--paper);color:var(--ink);font:15px/1.55 "Segoe UI",s'
    'ystem-ui,-apple-system,sans-serif;font-variant-numeric:tabular-nums;overflow-wrap:break-word}\n::sele'
    'ction{background:var(--sel);color:var(--ink)}\n[hidden]{display:none !important}\na{color:var(--link);'
    'text-underline-offset:3px}\nbutton,input,select{font:inherit;color:inherit}\n:focus-visible{outline:3p'
    'x solid var(--focus);outline-offset:2px}\n.sr{position:absolute;width:1px;height:1px;margin:-1px;padd'
    'ing:0;overflow:hidden;clip:rect(0 0 0 0);white-space:nowrap;border:0}\n.skip{position:absolute;left:1'
    '6px;top:-100px;z-index:60;padding:10px 14px;background:var(--surface);color:var(--ink);border:2px so'
    'lid var(--focus);border-radius:8px}\n.skip:focus{top:10px}\nsvg.i{width:16px;height:16px;flex:none;fil'
    'l:none;stroke:currentColor;stroke-width:1.8;stroke-linecap:round;stroke-linejoin:round}\n.bar{positio'
    'n:sticky;top:0;z-index:30;display:flex;align-items:center;gap:14px;min-height:60px;padding:8px clamp'
    '(14px,3vw,40px);background:var(--bar-bg);box-shadow:0 1px 0 var(--line)}\n.brand{display:flex;flex:no'
    'ne;align-items:center;gap:10px;color:var(--ink);text-decoration:none}\n.brand .mark{width:30px;height'
    ':30px;flex:none}\n.wordmark{font-weight:700;font-size:16.5px;letter-spacing:-.01em;white-space:nowrap'
    ';color:var(--title)}\n.product{font-size:13.5px;color:var(--muted);white-space:nowrap;padding-left:10'
    'px;border-left:1px solid var(--line2)}\n.bar-nav{display:flex;gap:2px;margin-left:6px;min-width:0;ove'
    'rflow:hidden}\n.bar-nav a{color:var(--muted);text-decoration:none;font-size:14px;font-weight:600;padd'
    'ing:8px 9px;border-radius:8px;white-space:nowrap}\n.bar-nav a:hover,.bar-nav a[aria-current="true"]{b'
    'ackground:var(--bar-hover);color:var(--title)}\n.acts{margin-left:auto;display:flex;align-items:cente'
    'r;gap:8px}\n.tag{font-size:12.5px;font-weight:600;color:var(--muted);border:1px solid var(--line2);bo'
    'rder-radius:999px;padding:5px 11px;white-space:nowrap}\n.btn{display:inline-flex;align-items:center;j'
    'ustify-content:center;gap:8px;min-height:40px;padding:0 15px;border:1px solid transparent;border-rad'
    'ius:10px;background:var(--btn);color:var(--btn-ink);font-weight:600;font-size:14px;cursor:pointer;wh'
    'ite-space:nowrap;text-decoration:none;list-style:none}\n.btn:hover{background:var(--btn-hover)}\n.btn.'
    'ghost{background:var(--surface);color:var(--ink);border-color:var(--line2)}\n.btn.ghost:hover{backgro'
    'und:var(--bar-hover)}\n.btn.icon{width:40px;padding:0}\n.btn.sm{min-height:34px;padding:0 12px;font-si'
    'ze:13px}\nsummary.btn::-webkit-details-marker{display:none}\n#theme-toggle .sun,#theme-toggle[aria-pre'
    'ssed="true"] .moon{display:none}\n#theme-toggle[aria-pressed="true"] .sun{display:block}\n.menu{positi'
    'on:relative}\n.menu-pop{position:absolute;right:0;top:calc(100% + 6px);z-index:40;min-width:260px;dis'
    'play:grid;gap:2px;padding:6px;background:var(--surface);border:1px solid var(--line);border-radius:1'
    '2px;box-shadow:var(--shadow)}\n.menu-pop button,.menu-pop a{display:block;width:100%;padding:9px 12px'
    ';border:0;border-radius:8px;background:transparent;color:var(--ink);text-align:left;text-decoration:'
    'none;font-size:14px;font-weight:600;cursor:pointer}\n.menu-pop button:hover,.menu-pop a:hover{backgro'
    'und:var(--soft)}\n.menu-pop small{display:block;font-weight:400;color:var(--muted);font-size:12.5px}\n'
    '.toc{display:none}\n.brand-ribbon{display:flex;height:5px}\n.brand-ribbon span{flex:1}\n.brand-ribbon .'
    'navy{background:var(--brand-navy)}\n.brand-ribbon .lava{background:var(--brand-lava)}\n.brand-ribbon .'
    'steel{background:var(--brand-steel)}\n.brand-ribbon .teal{background:var(--brand-teal)}\nselect,input['
    'type="search"]{min-height:40px;max-width:100%;padding:0 12px;border:1px solid var(--line2);border-ra'
    'dius:10px;background:var(--surface);color:var(--ink)}\ninput[type="search"]::placeholder{color:var(--'
    'muted);opacity:1}\nselect:focus-visible,input:focus-visible{outline:3px solid var(--focus);outline-of'
    'fset:1px}\n.multi-band{background:var(--surface);border-bottom:1px solid var(--line)}\n.band-in{max-wi'
    'dth:1400px;margin:0 auto;padding:12px clamp(14px,3vw,40px);display:flex;flex-wrap:wrap;gap:10px 24px'
    ';align-items:center;justify-content:space-between;font-size:14px}\n.band-in p{margin:0;color:var(--mu'
    'ted)}\n.band-in b{color:var(--ink)}\n.ws-select{display:flex;align-items:center;gap:10px;font-weight:6'
    '00}\n.hero{position:relative;background:linear-gradient(150deg,var(--hero-a) 0%,var(--hero-b) 100%);c'
    'olor:#ffffff;padding:clamp(28px,4.2vw,52px) clamp(14px,3vw,40px) 104px}\n.hero-in{max-width:1320px;ma'
    'rgin:0 auto;display:grid;grid-template-columns:minmax(0,1fr) 330px;gap:24px 52px;align-items:start}\n'
    '.hero h1{margin:0 0 14px;font-size:clamp(28px,3vw,44px);line-height:1.12;font-weight:700;letter-spac'
    'ing:-.02em;text-wrap:balance;color:#ffffff}\n.lead{margin:0;max-width:72ch;font-size:17px;line-height'
    ':1.55;color:var(--hero-muted)}\n.lead b{color:#ffffff;font-weight:700}\n.meta{display:flex;flex-wrap:w'
    'rap;gap:8px;margin-top:20px}\n.meta span{font-size:12.5px;padding:5px 11px;border-radius:999px;border'
    ':1px solid var(--hero-line);color:var(--hero-muted);white-space:nowrap}\n.meta b{color:#ffffff;font-w'
    'eight:600}\n.meta span.on{background:rgba(255,255,255,.12);border-color:rgba(255,255,255,.45);color:#'
    'ffffff;font-weight:700;letter-spacing:.02em}\n.hero-side{display:grid;gap:14px}\n.plaque-k{margin:0 0 '
    '6px;font-size:12.5px;color:var(--hero-muted)}\n.brand-plaque{color-scheme:only light;display:flex;ali'
    'gn-items:center;justify-content:center;min-height:64px;padding:10px 16px;border-radius:12px;backgrou'
    'nd:#ffffff;color:#334155}\n.brand-plaque img{display:block;max-width:100%;max-height:44px;object-fit:'
    'contain}\n.brand-placeholder{font-size:14px;font-weight:700;letter-spacing:.16em;color:#334155}\n.clie'
    'nt-name{margin:6px 0 0;font-size:14px;font-weight:600;color:#ffffff}\n.signal{padding:18px 20px;borde'
    'r-radius:16px;background:rgba(255,255,255,.07);border:1px solid var(--sig-line)}\n.signal .k{font-siz'
    'e:13px;font-weight:600;color:var(--hero-muted)}\n.signal b{display:block;margin-top:4px;font-size:26p'
    'x;line-height:1.15;font-weight:700;color:var(--sig-ink)}\n.signal p{margin:8px 0 0;font-size:14px;col'
    'or:var(--hero-muted)}\n.signal.crit{--sig-ink:#ffb4ab;--sig-line:rgba(255,180,171,.55)}\n.signal.warn{'
    '--sig-ink:#fedf89;--sig-line:rgba(254,223,137,.5)}\n.signal.ok{--sig-ink:#a6f4c5;--sig-line:rgba(166,'
    '244,197,.45)}\n.signal.info{--sig-ink:#e4e7ec;--sig-line:rgba(255,255,255,.35)}\n.dist{grid-column:1 /'
    ' -1}\n.dist-head{display:flex;flex-wrap:wrap;justify-content:space-between;gap:4px 16px;margin-bottom'
    ':8px;font-size:13.5px;color:var(--hero-muted)}\n.dist-head b,.legend b{color:#ffffff}\n.track{display:'
    'flex;height:14px;border-radius:999px;overflow:hidden;background:rgba(255,255,255,.16)}\n.track i{disp'
    'lay:block;height:100%}\n.legend{display:flex;flex-wrap:wrap;gap:6px 20px;margin-top:10px;font-size:13'
    '.5px;color:var(--hero-muted)}\n.legend span{display:inline-flex;align-items:center;gap:7px}\n.legend i'
    '{display:inline-block;width:10px;height:10px;border-radius:3px}\n.page{max-width:1400px;margin:0 auto'
    ';padding:0 clamp(14px,3vw,40px) 56px}\n.kpis{position:relative;z-index:2;display:grid;grid-template-c'
    'olumns:repeat(auto-fit,minmax(min(100%,178px),1fr));gap:14px;margin-top:-62px}\n.kpi{min-width:0;padd'
    'ing:18px 20px;background:var(--surface);border:1px solid var(--line);border-radius:16px;box-shadow:v'
    'ar(--shadow)}\n.kpi .v{display:flex;flex-wrap:wrap;align-items:baseline;gap:0 5px;font-size:33px;line'
    '-height:1.05;font-weight:700;letter-spacing:-.02em;color:var(--title)}\n.kpi .v small{font-size:15px;'
    'font-weight:600;letter-spacing:0;color:var(--muted)}\n.kpi .l{margin-top:9px;font-size:14px;font-weig'
    'ht:600}\n.kpi .s{margin-top:3px;font-size:13px;color:var(--muted)}\n.sim,.note{display:flex;gap:10px;a'
    'lign-items:flex-start;margin-top:16px;padding:11px 16px;border-radius:12px;font-size:14px}\n.sim{back'
    'ground:repeating-linear-gradient(135deg,#fffaeb 0 12px,#fef0c7 12px 24px);border:1px solid #fedf89;c'
    'olor:#7a2e0e;font-weight:600}\n.note{background:var(--surface);border:1px solid var(--line);color:var'
    '(--ink)}\n.sim svg.i,.note svg.i{width:18px;height:18px;margin-top:1px}\n.note svg.i{color:var(--med-b'
    'ar)}\n.chapter{margin-top:48px;scroll-margin-top:78px}\n.sh{margin-bottom:16px}\n.sh h2{margin:0;font-s'
    'ize:23px;line-height:1.3;font-weight:700;letter-spacing:-.01em;color:var(--title);text-wrap:balance}'
    '\n.sh p{margin:6px 0 0;max-width:75ch;font-size:14.5px;color:var(--muted)}\n.grid2{display:grid;grid-t'
    'emplate-columns:repeat(auto-fit,minmax(min(100%,440px),1fr));gap:16px}\n.stack-gap>* + *{margin-top:1'
    '6px}\n.card{min-width:0;padding:20px 22px;background:var(--surface);border:1px solid var(--line);bord'
    'er-radius:16px;box-shadow:var(--shadow)}\n.card h3{margin:0 0 4px;font-size:17px;line-height:1.3;font'
    '-weight:700;color:var(--title)}\n.card .sub{margin:0 0 14px;font-size:13.5px;color:var(--muted)}\n.car'
    'd.flat{padding:0;overflow:hidden}\n.card-head{display:flex;flex-wrap:wrap;align-items:baseline;justif'
    'y-content:space-between;gap:4px 16px;padding:18px 22px 12px}\n.card-head h3{margin:0}\n.card-head p{ma'
    'rgin:0;font-size:13.5px;color:var(--muted)}\n.facts{display:grid;grid-template-columns:repeat(auto-fi'
    't,minmax(min(100%,250px),1fr));gap:16px 28px;margin:0}\n.facts dt{margin-bottom:3px;font-size:12.5px;'
    'color:var(--muted)}\n.facts dd{margin:0;font-size:14.5px;font-weight:600;min-width:0}\n.facts dd small'
    '{display:block;font-weight:400;color:var(--muted);font-size:12.5px}\n.plist,.msgs{list-style:none;mar'
    'gin:0;padding:0}\n.msgs li{position:relative;padding:9px 0 9px 18px;border-top:1px solid var(--line);'
    'font-size:14.5px}\n.msgs li:first-child{border-top:0;padding-top:2px}\n.msgs li::before{content:"";pos'
    'ition:absolute;left:2px;top:17px;width:6px;height:6px;border-radius:50%;background:var(--chart)}\n.ms'
    'gs li:first-child::before{top:10px}\n.plist li{display:grid;grid-template-columns:auto minmax(0,1fr);'
    'gap:4px 12px;padding:12px 0;border-top:1px solid var(--line)}\n.plist li:first-child{border-top:0;pad'
    'ding-top:0}\n.plist .pt{font-weight:600}\n.plist .pm{grid-column:2;font-size:13.5px;color:var(--muted)'
    '}\n.bars{display:grid;gap:12px}\n.brow{display:grid;grid-template-columns:minmax(120px,36%) minmax(0,1'
    'fr) auto;gap:12px;align-items:center;font-size:14px}\n.brow .bl{min-width:0}\n.brow .bl small,.brow .b'
    'v small{display:block;font-size:12.5px;font-weight:400;color:var(--muted)}\n.bt{height:10px;border-ra'
    'dius:999px;overflow:hidden;background:var(--soft)}\n.bt i{display:block;height:100%;min-width:2px;bor'
    'der-radius:999px;background:var(--chart)}\n.brow .bv{text-align:right;font-weight:700;white-space:now'
    'rap}\n.brow.na .bv{font-weight:600;color:var(--muted)}\n#check-status .brow{grid-template-columns:minm'
    'ax(150px,46%) minmax(0,1fr) auto}\n.wrap,.graph{overflow-x:auto;border-top:1px solid var(--line);back'
    'ground:linear-gradient(90deg,var(--surface) 30%,rgba(255,255,255,0)) left / 36px 100% no-repeat loca'
    'l,linear-gradient(270deg,var(--surface) 30%,rgba(255,255,255,0)) right / 36px 100% no-repeat local,r'
    'adial-gradient(farthest-side at 0 50%,rgba(16,24,40,.18),rgba(16,24,40,0)) left / 14px 100% no-repea'
    't scroll,radial-gradient(farthest-side at 100% 50%,rgba(16,24,40,.18),rgba(16,24,40,0)) right / 14px'
    ' 100% no-repeat scroll}\ntable{width:100%;border-collapse:collapse;font-size:14px;text-align:left}\nth'
    '{padding:10px 14px;background:var(--soft);color:var(--title);font-size:12px;font-weight:700;letter-s'
    'pacing:.04em;text-transform:uppercase;white-space:nowrap;border-bottom:1px solid var(--line);vertica'
    'l-align:bottom}\ntd{padding:11px 14px;border-bottom:1px solid var(--line);vertical-align:top}\ntbody t'
    'r:last-child td{border-bottom:0}\ntbody tr:hover{background:var(--hover)}\ntable.dense{font-size:13.5p'
    'x}\n.dense td,.dense th{padding-left:11px;padding-right:11px}\ntd.n,th.n{text-align:right;white-space:'
    'nowrap}\ntd.nw{white-space:nowrap}\ntd.w{min-width:240px}\ntd.empty-cell{color:var(--muted)}\ntr.pg{disp'
    'lay:none}\n.th-sort{all:unset;display:inline-flex;align-items:center;gap:4px;cursor:pointer}\n.th-sort'
    ':focus-visible{outline:3px solid var(--focus);outline-offset:2px;border-radius:4px}\n.th-sort::after{'
    'content:"";width:0;height:0;border:4px solid transparent;border-top-color:currentColor;opacity:.35;m'
    'argin-top:4px}\nth[aria-sort="ascending"] .th-sort::after{border-top-color:transparent;border-bottom-'
    'color:currentColor;margin-top:-4px;opacity:1}\nth[aria-sort="descending"] .th-sort::after{opacity:1}\n'
    '.more-row{display:flex;flex-wrap:wrap;align-items:center;justify-content:center;gap:8px 12px;padding'
    ':12px;border-top:1px solid var(--line)}\n.more-note{font-size:13px;color:var(--muted)}\n.stack b{displ'
    'ay:block;font-weight:600}\n.stack small{display:block;font-size:12.5px;color:var(--muted)}\n.mono{font'
    '-family:ui-monospace,"Cascadia Mono",Consolas,monospace;font-size:12.5px}\n.nw{white-space:nowrap}\n.m'
    'uted{color:var(--muted)}\n.fd p,.fr p{margin:3px 0 0}\n.fd p{font-size:13.5px;color:var(--muted)}\n.res'
    ' b{display:block;font-weight:600}\n.res small{display:block;font-size:12.5px;color:var(--muted)}\n.ext'
    '{display:inline-flex;align-items:center;gap:4px;margin-top:3px;font-size:13px;font-weight:600;white-'
    'space:nowrap}\n.ext svg.i{width:13px;height:13px}\n.chips{display:flex;flex-wrap:wrap;gap:5px;margin-t'
    'op:6px}\n.chips span{padding:1px 8px;border-radius:7px;background:var(--soft);color:var(--muted);font'
    '-size:12px}\n.chips b{color:var(--ink);font-weight:600}\ndetails.json{margin-top:6px;font-size:12.5px}'
    '\ndetails.json summary{cursor:pointer;color:var(--link);font-weight:600}\ndetails.json pre{max-width:6'
    '20px;max-height:260px;overflow:auto;margin:6px 0 0;padding:10px;border-radius:8px;background:var(--s'
    'oft);font:12px/1.45 ui-monospace,"Cascadia Mono",Consolas,monospace;white-space:pre}\n.pill{display:i'
    'nline-flex;align-items:center;gap:6px;padding:2px 10px;border-radius:999px;font-size:12.5px;font-wei'
    'ght:700;line-height:1.6;white-space:nowrap}\n.pill::before{content:"";width:7px;height:7px;border-rad'
    'ius:50%;background:var(--d,currentColor)}\n.sev-critical{color:var(--crit-ink);background:var(--crit-'
    'bg);--d:var(--crit-bar)}\n.sev-high{color:var(--high-ink);background:var(--high-bg);--d:var(--high-ba'
    'r)}\n.sev-medium{color:var(--med-ink);background:var(--med-bg);--d:var(--med-bar)}\n.sev-low{color:var'
    '(--low-ink);background:var(--low-bg);--d:var(--low-bar)}\n.sev-info,.tone-info{color:var(--info-ink);'
    'background:var(--info-bg);--d:var(--info-bar)}\n.tone-ok{color:var(--ok-ink);background:var(--ok-bg);'
    '--d:var(--ok-bar)}\n.tone-warn{color:var(--med-ink);background:var(--med-bg);--d:var(--med-bar)}\n.ton'
    'e-crit{color:var(--crit-ink);background:var(--crit-bg);--d:var(--crit-bar)}\n.cls-OBSERVED{color:var('
    '--obs-ink);background:var(--obs-bg);--d:var(--obs-line)}\n.cls-INFERRED{color:var(--inf-ink);backgrou'
    'nd:var(--inf-bg);--d:var(--inf-line);outline:1px dashed var(--inf-line);outline-offset:-1px}\n.cls-UN'
    'KNOWN{color:var(--unk-ink);background:var(--unk-bg);--d:transparent}\n.cls-UNKNOWN::before{box-shadow'
    ':inset 0 0 0 1.5px var(--unk-line)}\n.st{display:inline-flex;align-items:center;gap:7px;font-size:13.'
    '5px;font-weight:600;white-space:nowrap}\n.st::before{content:"";width:9px;height:9px;border-radius:50'
    '%;background:var(--d)}\n.st-failed{--d:var(--crit-bar)}\n.st-passed{--d:var(--ok-bar)}\n.st-not_evaluat'
    'ed{--d:var(--info-bar)}\n.st-not_applicable{--d:transparent;color:var(--muted)}\n.st-not_applicable::b'
    'efore{box-shadow:inset 0 0 0 2px var(--info-bar)}\n.tools{display:flex;flex-wrap:wrap;gap:10px 12px;a'
    'lign-items:flex-end;padding:0 22px 16px}\n.field{display:grid;gap:4px;min-width:0;font-size:12.5px;fo'
    'nt-weight:600;color:var(--muted)}\n.field select,.field input{color:var(--ink);font-size:14px;font-we'
    'ight:400}\n.field.grow{flex:1 1 220px}\n.field.grow input{width:100%}\n.cls-sum{display:flex;flex-wrap:'
    'wrap;gap:8px;margin:-4px 0 16px}\n.tabs{display:inline-flex;flex-wrap:wrap;gap:4px;margin:0 0 16px;pa'
    'dding:4px;background:var(--soft);border:1px solid var(--line);border-radius:12px}\n.tabs button{min-h'
    'eight:40px;padding:0 16px;border:0;border-radius:9px;background:transparent;color:var(--muted);font-'
    'size:14px;font-weight:600;cursor:pointer}\n.tabs button:hover{color:var(--title)}\n.tabs button[aria-s'
    'elected="true"]{background:var(--surface);color:var(--title);box-shadow:0 1px 2px rgba(16,24,40,.1),'
    '0 0 0 1px var(--line)}\n.graph{padding:4px 22px 6px}\n.graph svg{display:block;width:100%;min-width:76'
    '0px;height:auto}\n.g-col{fill:var(--muted);font-size:11px;font-weight:700;letter-spacing:.06em;text-t'
    'ransform:uppercase}\n.g-node rect{fill:var(--surface);stroke:var(--line2);stroke-width:1.2}\n.g-node.w'
    's rect{stroke:var(--brand-steel);stroke-width:2}\n.g-node.inf rect{fill:var(--inf-bg);stroke:var(--in'
    'f-line);stroke-dasharray:5 4}\n.g-l1{fill:var(--ink);font-size:12.5px;font-weight:600}\n.g-l2{fill:var'
    '(--muted);font-size:11px}\n.edge{fill:none;stroke:var(--edge);stroke-width:1.3;opacity:.75}\n.edge.inf'
    '{stroke:var(--inf-line);stroke-dasharray:6 5;opacity:1}\n.arr.obs{fill:var(--edge)}\n.arr.inf{fill:var'
    '(--inf-line)}\n.g-legend{display:flex;flex-wrap:wrap;gap:6px 20px;align-items:center;padding:10px 22p'
    'x 16px;font-size:13px;color:var(--muted)}\n.g-legend span{display:inline-flex;align-items:center;gap:'
    '8px}\n.g-legend svg{width:34px;height:10px}\n.ref-box rect{fill:var(--soft);stroke:var(--brand-steel);'
    'stroke-width:1.5;stroke-dasharray:6 4}\n.ref-t{fill:var(--title);font-size:13px;font-weight:700}\n.ref'
    '-s{fill:var(--muted);font-size:11.5px}\n.ref-link{stroke:var(--brand-lava);stroke-width:2}\n.ref-flag '
    'rect{fill:var(--high-bg)}\n.ref-flag text{fill:var(--high-ink);font-size:11px;font-weight:700;letter-'
    'spacing:.05em}\n.ref-note{fill:var(--high-ink);font-size:12.5px;font-weight:600}\n.stat{font-size:34px'
    ';line-height:1.1;font-weight:700;letter-spacing:-.02em;color:var(--title);margin:6px 0 4px}\n.stat sm'
    'all{font-size:15px;font-weight:600;color:var(--muted);letter-spacing:0}\n.stat.na{font-size:24px}\n.no'
    'tes{margin:12px 0 0;padding-left:18px;font-size:13px;color:var(--muted)}\n.notes li + li{margin-top:4'
    'px}\n.plan{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,360px),1fr));gap:16px;a'
    'lign-items:start}\n.steps{list-style:none;margin:12px 0 0;padding:0}\n.steps li{display:grid;grid-temp'
    'late-columns:28px minmax(0,1fr);gap:4px 12px;padding:12px 0;border-top:1px solid var(--line)}\n.steps'
    ' .no{display:grid;place-items:center;width:28px;height:28px;border-radius:50%;background:var(--btn);'
    'color:var(--btn-ink);font-size:13px;font-weight:700}\n.steps .sx{min-width:0}\n.steps .sx p{margin:4px'
    ' 0 0;font-size:14px}\n.steps .sm{display:flex;flex-wrap:wrap;gap:4px 12px;align-items:center;margin-t'
    'op:6px;font-size:12.5px;color:var(--muted)}\n.steps .sm .ext{margin-top:0}\n.empty{display:flex;gap:12'
    'px;align-items:center;color:var(--muted);font-size:14px}\n.empty svg.i{width:22px;height:22px;color:v'
    'ar(--ok-bar)}\n.dl2{display:grid;grid-template-columns:minmax(150px,220px) minmax(0,1fr);gap:10px 20p'
    'x;margin:0;font-size:14px}\n.dl2 dt{color:var(--muted)}\n.dl2 dd{margin:0}\n.dl2 ul{margin:0;padding-le'
    'ft:18px}\n.state-card{max-width:1320px;margin:28px auto;padding:20px 22px;border:1px solid var(--crit'
    '-bar);border-radius:16px;background:var(--crit-bg);color:var(--crit-ink)}\n.state-card h2{margin:0 0 '
    '6px;font-size:20px}\n.state-card p{margin:0;color:var(--ink)}\n.state-card dl{margin:12px 0 0;color:va'
    'r(--ink)}\n@media (max-width:1400px){#workspace-error-view,#opening-state{margin:28px clamp(14px,3vw,'
    '40px)}}\n.foot{max-width:1320px;margin:0 auto;padding:20px 0 40px;border-top:1px solid var(--line);co'
    'lor:var(--muted);font-size:13px}\n@media (max-width:1400px){.foot{margin:0 clamp(14px,3vw,40px)}}\n@me'
    'dia (max-width:1360px){.bar-nav,.tag{display:none} .toc{display:block}}\n@media (max-width:1040px){.h'
    'ero-in{grid-template-columns:1fr} .hero-side{grid-template-columns:repeat(auto-fit,minmax(min(100%,2'
    '80px),1fr))} .product{display:none}}\n@media (max-width:720px){\n.btn .lbl{display:none}\n.btn{padding:'
    '0 11px}\n.acts{gap:6px}\n.hero{padding-bottom:92px}\n.lead{font-size:16px}\n.brand-plaque{min-height:52p'
    'x}\n.kpis{grid-template-columns:repeat(2,minmax(0,1fr));gap:10px}\n.kpi{padding:14px 16px}\n.kpi .v{fon'
    't-size:27px}\n.brow,#check-status .brow{grid-template-columns:minmax(0,1fr) auto}\n.brow .bt{grid-colu'
    'mn:1 / -1;grid-row:2}\n.tools,.card-head,.g-legend{padding-left:16px;padding-right:16px}\n.graph{paddi'
    'ng-left:16px;padding-right:16px}\n.card{padding:16px}\n.card.flat{padding:0}\n.dl2{grid-template-column'
    's:1fr;gap:2px 0}\n.dl2 dd + dt{margin-top:10px}\n}\n@media (max-width:420px){.wordmark{font-size:15px} '
    '.brand .mark{width:26px;height:26px} .btn.icon,.acts .btn{width:38px;min-height:38px;padding:0}}\n@me'
    'dia (max-width:360px){.bar{gap:8px} .acts{gap:4px} .brand{flex:0 1 auto;min-width:0} .wordmark{overf'
    'low:hidden;text-overflow:ellipsis}}\n@media (prefers-reduced-motion:reduce){*{transition:none !import'
    'ant;scroll-behavior:auto !important}}\n@page{size:A4;margin:14mm 12mm 16mm}\n@media print{\n*{-webkit-p'
    'rint-color-adjust:exact;print-color-adjust:exact}\nhtml,body{background:#ffffff;font-size:12px}\n.bar,'
    '.skip,.tools,.more-row,.tabs,.ws-select,details.json{display:none !important}\n.multi-band{border:0}\n'
    '.hero{padding:22px 24px 74px;border-radius:14px}\n.hero-in{grid-template-columns:minmax(0,1fr) 210px;'
    'gap:14px 26px}\n.hero-side{grid-template-columns:1fr}\n.hero h1{font-size:25px}\n.lead{font-size:12.5px'
    '}\n.signal b{font-size:19px}\n.page{padding:0}\n.kpis{grid-template-columns:repeat(3,minmax(0,1fr));gap'
    ':10px;margin-top:-54px}\n.kpi{padding:12px 14px;box-shadow:none}\n.kpi .v{font-size:24px}\n.card{box-sh'
    'adow:none;break-inside:avoid}\n.card.flat{break-inside:auto}\n.grid2{grid-template-columns:1fr 1fr}\n.p'
    'lan{grid-template-columns:1fr}\n.plan .card{break-inside:auto}\n.steps .sx b,.plist .pt{font-size:12px'
    '}\n.steps .sx p,.msgs li,.brow{font-size:11.5px}\n.plist .pm,.steps .sm,.brow small,.facts dt,.facts d'
    'd small{font-size:10.5px}\n.facts dd{font-size:12px}\n.chapter{margin-top:24px}\n.sh{break-after:avoid;'
    'break-inside:avoid}\n.card-head{display:block;break-after:avoid;break-inside:avoid}\n.card-head p{marg'
    'in-top:2px}\n.sh::after,.card-head::after{content:"";display:block;height:150px;margin-bottom:-150px}'
    '\n.sh p{font-size:12px}\ntr,.kpi,.signal,.brow,.steps li,.plist li{break-inside:avoid}\nthead{display:t'
    'able-header-group}\ntr.pg{display:table-row !important}\n.wrap,.graph{overflow:visible;background:none'
    '}\ntable,table.dense{font-size:10.5px}\ntd,th,.dense td,.dense th{padding:5px 7px}\ntd{overflow-wrap:br'
    'eak-word}\ntd .mono,td.w,.chips span{overflow-wrap:anywhere}\ntd small,td p,td .ext,td .st,td .pill,.c'
    'hips span,.card td small,.card td p{font-size:9.5px}\nth[data-label] .th-sort{display:none}\nth[data-l'
    'abel]::before{content:attr(data-label)}\ntd .pill{padding:1px 7px;gap:4px}\ntd .pill::before{width:5px'
    ';height:5px}\n.sh h2{font-size:18px}\n.card h3{font-size:13.5px}\n.card .sub,.card-head p,.notes,.dl2{f'
    'ont-size:10.5px}\nth{font-size:9px;white-space:normal}\ntd.nw,td .nw{white-space:normal}\ntd.w{min-widt'
    'h:0}\n.mono{font-size:9.5px}\n.graph svg{min-width:0}\n[hidden].print-show{display:block !important}\na{'
    'color:inherit;text-decoration:none}\n.foot{padding:14px 0 0}\n}\n</style>\n</head>\n<body>\n<a class="skip'
    '" href="#main-document">Saltar al contenido principal</a>\n<header class="bar">\n  <a class="brand" hr'
    'ef="#sec-cover">\n    <svg class="mark" viewBox="0 0 32 32" aria-hidden="true" focusable="false"><rec'
    't width="32" height="32" rx="8" fill="#003865"/><path d="M16 7.5l9 4.6-9 4.6-9-4.6z" fill="#ff3621"/'
    '><path d="M7 16.4l9 4.6 9-4.6M7 20.8l9 4.6 9-4.6" fill="none" stroke="#ffffff" stroke-width="1.9" st'
    'roke-linejoin="round"/></svg>\n    <span class="wordmark">Azure SRE Agent</span>\n    <span class="pro'
    'duct">Dependencias Azure Databricks</span>\n  </a>\n  <nav class="bar-nav" aria-label="Contenido del i'
    'nforme">\n    <a href="#sec-dependencies">Dependencias</a>\n    <a href="#sec-inventory">Inventario</a'
    '>\n    <a href="#sec-findings">Hallazgos</a>\n    <a href="#sec-finops">FinOps</a>\n    <a href="#sec-a'
    'ctions">Plan</a>\n    <a href="#sec-sources">Fuentes</a>\n  </nav>\n  <div class="acts">\n    <details c'
    'lass="menu toc">\n      <summary class="btn ghost" aria-label="Contenido"><svg class="i" viewBox="0 0'
    ' 24 24" aria-hidden="true" focusable="false"><path d="M4 6h16M4 12h16M4 18h10"/></svg><span class="l'
    'bl">Contenido</span></summary>\n      <nav class="menu-pop" aria-label="Contenido">\n        <a href="'
    '#sec-cover">1. Portada y procedencia</a>\n        <a href="#sec-executive">2. Resumen ejecutivo y WAF'
    '</a>\n        <a href="#sec-dependencies">3. Mapa de dependencias</a>\n        <a href="#sec-inventory'
    '">4. Inventario Lakehouse y ARM</a>\n        <a href="#sec-findings">5. Hallazgos y reglas</a>\n      '
    '  <a href="#sec-finops">6. FinOps y capacidad</a>\n        <a href="#sec-actions">7. Plan de acción</'
    'a>\n        <a href="#sec-sources">8. Fuentes y metodología</a>\n      </nav>\n    </details>\n    <span'
    ' class="tag">Solo lectura</span>\n    <button type="button" class="btn ghost icon" id="theme-toggle" '
    'aria-pressed="false" title="Modo oscuro"><svg class="i moon" viewBox="0 0 24 24" aria-hidden="true" '
    'focusable="false"><path d="M20 14.5A8 8 0 0 1 9.5 4 8 8 0 1 0 20 14.5z"/></svg><svg class="i sun" vi'
    'ewBox="0 0 24 24" aria-hidden="true" focusable="false"><circle cx="12" cy="12" r="4"/><path d="M12 2'
    'v2M12 20v2M4.9 4.9l1.4 1.4M17.7 17.7l1.4 1.4M2 12h2M20 12h2M4.9 19.1l1.4-1.4M17.7 6.3l1.4-1.4"/></sv'
    'g><span class="sr">Modo oscuro</span></button>\n    <details class="menu" id="export-menu">\n      <su'
    'mmary class="btn ghost" aria-label="Exportar"><svg class="i" viewBox="0 0 24 24" aria-hidden="true" '
    'focusable="false"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg><span class="lbl">Exportar</span></'
    'summary>\n      <div class="menu-pop">\n        <button type="button" id="export-json-btn">Instantánea'
    ' completa (JSON)<small>Modelo normalizado embebido en este informe</small></button>\n        <button '
    'type="button" id="export-deps-csv-btn">Dependencias (CSV)<small>Nodos, relaciones y puntos ciegos de'
    'l workspace</small></button>\n        <button type="button" id="export-findings-csv-btn">Comprobacion'
    'es (CSV)<small>Todas las reglas evaluadas con su evidencia</small></button>\n      </div>\n    </detai'
    'ls>\n    <button type="button" class="btn" id="print-btn"><svg class="i" viewBox="0 0 24 24" aria-hid'
    'den="true" focusable="false"><path d="M7 9V3h10v6M7 18H5a2 2 0 0 1-2-2v-5a2 2 0 0 1 2-2h14a2 2 0 0 1'
    ' 2 2v5a2 2 0 0 1-2 2h-2M7 14h10v7H7z"/></svg><span class="lbl">Imprimir / PDF</span></button>\n  </di'
    'v>\n</header>\n<div class="brand-ribbon" aria-hidden="true"><span class="navy"></span><span class="lav'
    'a"></span><span class="steel"></span><span class="teal"></span></div>\n<div class="multi-band" id="mu'
    'lti-overview" hidden>\n  <div class="band-in">\n    <p id="multi-summary"></p>\n    <label class="ws-se'
    'lect" id="workspace-selector-wrap" hidden>Workspace\n      <select id="workspace-selector" aria-label'
    '="Seleccionar workspace"></select>\n    </label>\n  </div>\n</div>\n<main id="main-document" tabindex="-'
    '1">\n  <div id="opening-state" class="state-card" role="alert" hidden></div>\n  <div id="workspace-err'
    'or-view" class="state-card" role="alert" hidden></div>\n  <div id="report-body" hidden>\n    <section '
    'class="hero" id="sec-cover" aria-labelledby="cover-title">\n      <div class="hero-in">\n        <div>'
    '\n          <h1 id="cover-title">Revisión de arquitectura, dependencias y configuración de Azure Data'
    'bricks</h1>\n          <p class="lead" id="cover-lead"></p>\n          <div class="meta" id="cover-bad'
    'ges"></div>\n        </div>\n        <aside class="hero-side" aria-label="Cliente y veredicto">\n      '
    '    <div>\n            <p class="plaque-k">Preparado para</p>\n            <div class="brand-plaque" i'
    'd="brand-plaque"></div>\n            <p class="client-name" id="client-name-label"></p>\n          </d'
    'iv>\n          <div class="signal" id="verdict"></div>\n        </aside>\n        <div class="dist" id='
    '"severity-dist"></div>\n      </div>\n    </section>\n    <div class="page">\n      <div class="kpis" id'
    '="kpis"></div>\n      <div id="notices"></div>\n\n      <section class="chapter" id="sec-identity" aria'
    '-labelledby="h-identity">\n        <div class="sh"><h2 id="h-identity">1. Workspace, identidad y proc'
    'edencia</h2><p>Qué workspace se revisó, con qué identidad y desde qué tenant: el contexto que da val'
    'idez a cada cifra de este informe.</p></div>\n        <div class="card"><dl class="facts" id="cover-f'
    'acts"></dl></div>\n      </section>\n\n      <section class="chapter" id="sec-executive" aria-labelledb'
    'y="h-exec">\n        <div class="sh"><h2 id="h-exec">2. Lectura ejecutiva, cobertura e indicadores lo'
    'cales</h2><p>El índice local mide únicamente las reglas evaluadas sobre evidencia observada. Nunca s'
    'ustituye una evaluación oficial de Microsoft Well-Architected ni oculta fuentes no evaluadas.</p></d'
    'iv>\n        <div class="grid2">\n          <div class="card"><h3>Lectura ejecutiva</h3><p class="sub"'
    '>Lo esencial de esta revisión en cinco líneas.</p><ul class="msgs" id="executive-messages"></ul></di'
    'v>\n          <div class="card"><h3>Distribución de comprobaciones</h3><p class="sub">Estado de cada '
    'regla local frente a la evidencia observada.</p><div class="bars" id="check-status"></div></div>\n   '
    '       <div class="card"><h3>Desglose por área</h3><p class="sub">Índice local por área de revisión,'
    ' junto a su cobertura evaluada.</p><div class="bars" id="area-scores"></div></div>\n          <div cl'
    'ass="card"><h3>Desglose por pilar Well-Architected</h3><p class="sub">Mismo cálculo agrupado por pil'
    'ar; no es una puntuación oficial WAF.</p><div class="bars" id="pillar-scores"></div></div>\n        <'
    '/div>\n        <div class="card" style="margin-top:16px"><h3>Prioridades críticas y de alta severidad'
    ' observadas</h3><p class="sub">Comprobaciones que no cumplen con severidad crítica o alta, con el ob'
    'jeto afectado y su evidencia.</p><ul class="plist" id="priority-findings"></ul></div>\n      </sectio'
    'n>\n\n      <section class="chapter" id="sec-dependencies" aria-labelledby="h-deps">\n        <div clas'
    's="sh"><h2 id="h-deps">3. Mapa de dependencias y arquitectura Lakehouse</h2><p>Cada relación se clas'
    'ifica explícitamente como <strong>OBSERVED</strong> (join exacto de ID/clave nativa confirmado en la'
    's APIs), <strong>INFERRED</strong> (referencia explícita de URI/host hacia un recurso no recolectado'
    ' en ARM) o <strong>UNKNOWN</strong> (linaje dinámico en tiempo de ejecución o alcance no consultado '
    'sin arrancar cómputo).</p></div>\n        <div class="cls-sum" id="dep-class-summary"></div>\n        '
    '<div class="tabs" role="tablist" aria-label="Vistas de arquitectura y dependencias">\n          <butt'
    'on type="button" role="tab" id="tab-dep-observed" aria-selected="true" aria-controls="panel-dep-obse'
    'rved">Mapa de dependencias observado e inferido</button>\n          <button type="button" role="tab" '
    'id="tab-dep-reference" aria-selected="false" aria-controls="panel-dep-reference" tabindex="-1">Propu'
    'esta de referencia - NO desplegada</button>\n        </div>\n        <div id="panel-dep-observed" clas'
    's="print-show" role="tabpanel" aria-labelledby="tab-dep-observed">\n          <div class="card flat">'
    '\n            <div class="card-head"><h3>Grafo de vecindario</h3><p id="dep-graph-note"></p></div>\n  '
    '          <div class="tools">\n              <label class="field">Capa\n                <select id="de'
    'p-layer-filter">\n                  <option value="all">Todas las capas</option>\n                  <o'
    'ption value="control_plane">Plano de control (ARM)</option>\n                  <option value="compute'
    '">Cómputo (Clústeres / Pools / Warehouses)</option>\n                  <option value="orchestration">'
    'Orquestación (Jobs / Tareas / Pipelines)</option>\n                  <option value="governance">Gober'
    'nanza (Unity Catalog / Secret Scopes)</option>\n                  <option value="associated_resource"'
    '>Recursos Azure asociados</option>\n                </select>\n              </label>\n              <l'
    'abel class="field">Clasificación\n                <select id="dep-class-filter">\n                  <o'
    'ption value="all">Todas (OBSERVED / INFERRED / UNKNOWN)</option>\n                  <option value="OB'
    'SERVED">OBSERVED (Join nativo exacto)</option>\n                  <option value="INFERRED">INFERRED ('
    'Referencia URI/host)</option>\n                  <option value="UNKNOWN">UNKNOWN (Punto ciego explíci'
    'to)</option>\n                </select>\n              </label>\n              <label class="field grow'
    '">Buscar nodo / carga\n                <input type="search" id="dep-search-filter" placeholder="Job, '
    'clúster, catálogo, cuenta ADLS…">\n              </label>\n              <button type="button" class="'
    'btn ghost" id="dep-clear">Limpiar filtros</button>\n            </div>\n            <div class="graph"'
    ' id="dep-graph-box"></div>\n            <div class="g-legend" aria-hidden="true">\n              <span'
    '><svg viewBox="0 0 34 10"><line x1="1" y1="5" x2="33" y2="5" class="edge"/></svg>OBSERVED · join nat'
    'ivo</span>\n              <span><svg viewBox="0 0 34 10"><line x1="1" y1="5" x2="33" y2="5" class="ed'
    'ge inf"/></svg>INFERRED · URI/host sin inventario ARM</span>\n              <span id="dep-graph-capti'
    'on"></span>\n            </div>\n          </div>\n          <div class="stack-gap" style="margin-top:1'
    '6px">\n            <div class="card flat"><div class="card-head"><h3>Relaciones de dependencia (<span'
    ' id="dep-edges-count">0</span>)</h3><p>Origen, relación y destino con los campos de join exactos.</p'
    '></div><div class="wrap"><table class="dense" id="dep-edges-table"></table></div></div>\n            '
    '<div class="card flat"><div class="card-head"><h3>Nodos del grafo (<span id="dep-nodes-count">0</spa'
    'n>)</h3><p>Cada objeto con su fuente y un resumen de la evidencia.</p></div><div class="wrap"><table'
    ' class="dense" id="dep-nodes-table"></table></div></div>\n            <div class="card flat"><div cla'
    'ss="card-head"><h3>Puntos ciegos y alcances UNKNOWN (<span id="dep-unknowns-count">0</span>)</h3><p>'
    'Lo que esta revisión no puede ver sin ejecutar cómputo o leer código.</p></div><div class="wrap"><ta'
    'ble class="dense" id="dep-unknowns-table"></table></div></div>\n            <div class="card flat"><d'
    'iv class="card-head"><h3>Referencias rotas detectadas (<span id="dep-broken-count">0</span>)</h3><p>'
    'Identificadores referenciados que no existen en el inventario observado.</p></div><div class="wrap">'
    '<table class="dense" id="dep-broken-table"></table></div></div>\n          </div>\n        </div>\n    '
    '    <div id="panel-dep-reference" class="print-show" role="tabpanel" aria-labelledby="tab-dep-refere'
    'nce" hidden>\n          <div class="card flat">\n            <div class="card-head"><h3>Arquitectura d'
    'e referencia Azure Databricks Lakehouse — Propuesta NO desplegada</h3><p>Línea base recomendada por '
    'Microsoft y Databricks Well-Architected Lakehouse. <strong>No representa recursos desplegados en el '
    'entorno del cliente.</strong></p></div>\n            <div class="graph" id="ref-arch-box"></div>\n    '
    '        <div class="wrap"><table id="ref-arch-table"></table></div>\n          </div>\n        </div>\n'
    '      </section>\n\n      <section class="chapter" id="sec-inventory" aria-labelledby="h-inv">\n       '
    ' <div class="sh"><h2 id="h-inv">4. Inventario de Workspace, Cómputo, Orquestación, Unity Catalog y R'
    'ecursos Asociados</h2><p>Los objetos sobre los que se evalúan las reglas. Cada fila procede de una l'
    'ectura de API registrada en la sección 8.</p></div>\n        <div class="stack-gap">\n          <div c'
    'lass="card flat"><div class="card-head"><h3>Clústeres All-Purpose, Job Clusters, Instance Pools y Cl'
    'uster Policies</h3><p id="inv-compute-count"></p></div><div class="wrap"><table class="dense" id="in'
    'v-compute-table"></table></div></div>\n          <div class="card flat"><div class="card-head"><h3>Jo'
    'bs, DAG de tareas, Pipelines declarativos (Lakeflow / DLT) y SQL Warehouses</h3><p id="inv-orchestra'
    'tion-count"></p></div><div class="wrap"><table class="dense" id="inv-orchestration-table"></table></'
    'div></div>\n          <div class="card flat"><div class="card-head"><h3>Unity Catalog (Metastore, Cat'
    'álogos, Esquemas, Storage Credentials, External Locations, Conexiones) y Secret Scopes</h3><p id="in'
    'v-uc-count"></p></div><div class="wrap"><table class="dense" id="inv-uc-table"></table></div></div>\n'
    '          <div class="card flat"><div class="card-head"><h3>Recursos Azure asociados y Endpoints de '
    'dependencia saliente del plano de control</h3><p id="inv-resources-count"></p></div><div class="wrap'
    '"><table class="dense" id="inv-resources-table"></table></div></div>\n        </div>\n      </section>'
    '\n\n      <section class="chapter" id="sec-findings" aria-labelledby="h-find">\n        <div class="sh"'
    '><h2 id="h-find">5. Hallazgos y evaluación detallada de reglas</h2><p>Cada comprobación local con su'
    ' estado, la evidencia observada y la recomendación. Las que no cumplen aparecen primero; filtre, ord'
    'ene por columna y exporte.</p></div>\n        <div class="card flat">\n          <div class="card-head'
    '"><h3>Registro de comprobaciones</h3><p id="findings-count-label"></p></div>\n          <div class="t'
    'ools">\n            <label class="field">Área\n              <select id="find-area-filter">\n          '
    '      <option value="all">Todas</option>\n                <option value="best_practices">Buenas práct'
    'icas</option>\n                <option value="security">Seguridad</option>\n                <option va'
    'lue="finops">FinOps</option>\n                <option value="optimization">Optimización</option>\n    '
    '          </select>\n            </label>\n            <label class="field">Nivel\n              <selec'
    't id="find-level-filter">\n                <option value="all">Todos</option>\n                <option'
    ' value="workspace">Workspace / Gobernanza</option>\n                <option value="workload">Workload'
    ' (Cómputo / Jobs / SQL)</option>\n                <option value="resource">Recurso Azure asociado</op'
    'tion>\n              </select>\n            </label>\n            <label class="field">Severidad\n      '
    '        <select id="find-sev-filter">\n                <option value="all">Todas</option>\n           '
    '     <option value="critical">Crítica</option>\n                <option value="high">Alta</option>\n  '
    '              <option value="medium">Media</option>\n                <option value="low">Baja</option'
    '>\n              </select>\n            </label>\n            <label class="field">Estado\n             '
    ' <select id="find-status-filter">\n                <option value="all">Todos</option>\n               '
    ' <option value="failed">No cumple (failed)</option>\n                <option value="passed">Cumple (p'
    'assed)</option>\n                <option value="not_evaluated">No evaluado</option>\n                <'
    'option value="not_applicable">No aplica</option>\n              </select>\n            </label>\n      '
    '      <label class="field grow">Buscar recurso / carga\n              <input type="search" id="find-s'
    'earch-filter" placeholder="Filtrar por regla, job, clúster…">\n            </label>\n            <butt'
    'on type="button" class="btn ghost" id="find-clear">Limpiar</button>\n            <button type="button'
    '" class="btn ghost" id="find-export-btn"><svg class="i" viewBox="0 0 24 24" aria-hidden="true" focus'
    'able="false"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>CSV filtrado</button>\n          </div>\n '
    '         <div class="wrap"><table class="dense" id="findings-table"></table></div>\n        </div>\n  '
    '    </section>\n\n      <section class="chapter" id="sec-finops" aria-labelledby="h-finops">\n        <'
    'div class="sh"><h2 id="h-finops">6. FinOps, costes observados y candidatos de optimización</h2><p>Co'
    'ste real observado en ARM y configuraciones que suelen generar gasto en inactividad. No se inventan '
    'ahorros: lo que no se ha medido figura como no calculado.</p></div>\n        <div class="grid2">\n    '
    '      <div class="card"><h3>Coste real observado (ARM ActualCost)</h3><div class="stat" id="finops-a'
    'ctual-cost"></div><p class="sub" id="finops-cost-window"></p><ul class="notes" id="finops-cost-note"'
    '></ul></div>\n          <div class="card"><h3>Ahorro estimado</h3><div class="stat na">Por estimar / '
    'No calculado</div><p class="sub">No se inventan ahorros DBU ni descuentos sin medir el consumo histó'
    'rico en system.billing.usage y validar compromisos comerciales.</p></div>\n        </div>\n        <di'
    'v class="stack-gap" style="margin-top:16px">\n          <div class="card flat"><div class="card-head"'
    '><h3>Candidatos de eficiencia operativa y FinOps</h3><p>Configuraciones observadas que merecen revis'
    'ión; sin proyección de ahorro.</p></div><div class="wrap"><table class="dense" id="finops-candidates'
    '-table"></table></div></div>\n          <div class="card flat"><div class="card-head"><h3>Filas de fa'
    'cturación ARM observadas</h3><p>Importes por ResourceId aprobado, en la moneda real de facturación.<'
    '/p></div><div class="wrap"><table class="dense" id="finops-cost-table"></table></div></div>\n        '
    '</div>\n      </section>\n\n      <section class="chapter" id="sec-actions" aria-labelledby="h-actions"'
    '>\n        <div class="sh"><h2 id="h-actions">7. Plan de acción priorizado para revisión humana</h2><'
    'p>Los horizontes Quick-win (&lt;1 semana), Corto plazo (1-3 meses) y Medio plazo son categorías orie'
    'ntativas de planificación, no promesas de entrega ni cambios automáticos.</p></div>\n        <div cla'
    'ss="plan" id="actions-plan"></div>\n      </section>\n\n      <section class="chapter" id="sec-sources"'
    ' aria-labelledby="h-sources">\n        <div class="sh"><h2 id="h-sources">8. Registro de fuentes, rec'
    'ibos HTTP y límites metodológicos</h2><p>Qué fuentes se leyeron, con qué resultado y qué queda fuera'
    ' del alcance. El índice local solo se interpreta junto a esta cobertura.</p></div>\n        <div clas'
    's="card flat">\n          <div class="card-head"><h3>Cobertura de fuentes</h3><p id="sources-summary"'
    '></p></div>\n          <div class="bars" id="sources-bars" style="padding:0 22px 16px"></div>\n       '
    '   <div class="wrap"><table class="dense" id="sources-table"></table></div>\n        </div>\n        <'
    'div class="card" style="margin-top:16px">\n          <h3>Método e interpretación</h3>\n          <p cl'
    'ass="sub">Cómo se calcula cada indicador y qué no puede afirmar esta revisión.</p>\n          <dl cla'
    'ss="dl2" id="method-notes"></dl>\n          <h3 style="margin-top:18px">Limitaciones y reglas de inte'
    'rpretación</h3>\n          <ul class="notes" id="methodology-limitations"></ul>\n        </div>\n      '
    '</section>\n    </div>\n  </div>\n</main>\n<footer class="foot" id="report-footer"></footer>\n<script typ'
    'e="application/json" id="report-data">__REPORT_DATA_JSON__</script>\n<script>\n(function () {\n  "use s'
    'trict";\n  var SVGNS = "http://www.w3.org/2000/svg";\n  var LAYERS = ["control_plane", "compute", "orc'
    'hestration", "governance", "associated_resource"];\n  var SEVS = ["critical", "high", "medium", "low"'
    '];\n  var STATUS_ORDER = { failed: 0, not_evaluated: 1, passed: 2, not_applicable: 3 };\n  var L = {\n '
    '   status: { passed: "Cumple", failed: "No cumple", not_evaluated: "No evaluado", not_applicable: "N'
    'o aplica" },\n    sev: { critical: "Crítica", high: "Alta", medium: "Media", low: "Baja" },\n    area:'
    ' { best_practices: "Buenas prácticas", security: "Seguridad", finops: "FinOps", optimization: "Optim'
    'ización" },\n    pillar: { reliability: "Fiabilidad", security: "Seguridad", cost: "Optimización de c'
    'ostes", operations: "Excelencia operativa", performance: "Eficiencia del rendimiento" },\n    level: '
    '{ workspace: "Workspace", workload: "Carga de trabajo", resource: "Recurso Azure" },\n    layer: { co'
    'ntrol_plane: "Plano de control", compute: "Cómputo", orchestration: "Orquestación", governance: "Gob'
    'ernanza", associated_resource: "Recursos asociados" },\n    src: { complete: "Completa", partial: "Pa'
    'rcial", denied: "Denegada", error: "Error", not_configured: "No configurada", not_applicable: "No ap'
    'lica" },\n    effort: { L: "esfuerzo bajo", M: "esfuerzo medio", H: "esfuerzo alto" },\n    kind: {\n  '
    '    databricks_workspace: "Workspace", managed_resource_group: "Grupo administrado", outbound_depend'
    'ency_category: "Endpoint saliente",\n      all_purpose_cluster: "Clúster all-purpose", job_cluster_sp'
    'ec: "Job cluster", instance_pool: "Instance pool", cluster_policy: "Cluster policy",\n      sql_wareh'
    'ouse: "SQL Warehouse", job: "Job", job_task: "Tarea de job", dlt_pipeline: "Pipeline DLT", secret_sc'
    'ope: "Secret scope",\n      uc_metastore: "Metastore UC", uc_catalog: "Catálogo UC", uc_schema: "Esqu'
    'ema UC", uc_storage_credential: "Storage credential",\n      uc_external_location: "External location'
    '", uc_connection: "Conexión UC", external_storage_target: "Almacenamiento externo",\n      external_k'
    'ey_vault_target: "Key Vault externo", "microsoft.network/virtualnetworks": "Red virtual", "microsoft'
    '.network/virtualnetworks/subnets": "Subred",\n      "microsoft.network/networksecuritygroups": "NSG",'
    ' "microsoft.network/privateendpoints": "Private Endpoint", "microsoft.databricks/accessconnectors": '
    '"Access Connector",\n      "microsoft.managedidentity/userassignedidentities": "Identidad administrad'
    'a", "microsoft.storage/storageaccounts": "Cuenta de almacenamiento",\n      "microsoft.keyvault/vault'
    's": "Key Vault", AllPurposeCluster: "Clúster all-purpose", InstancePool: "Instance pool", ClusterPol'
    'icy: "Cluster policy",\n      "microsoft.network/routetables": "Tabla de rutas", "microsoft.network/n'
    'atgateways": "NAT Gateway", "microsoft.network/publicipaddresses": "IP pública",\n      "microsoft.ne'
    'twork/loadbalancers": "Load Balancer", "microsoft.network/privatednszones": "Zona DNS privada", "mic'
    'rosoft.eventhub/namespaces": "Event Hubs",\n      external_access_connector_target: "Access Connector'
    ' externo", external_arm_target: "Recurso ARM externo",\n      inferred_adls_storage_uri_target: "URI '
    'ADLS inferida", inferred_catalog_storage_uri_target: "Almacenamiento de catálogo inferido",\n      in'
    'ferred_pipeline_storage_uri_target: "Almacenamiento de pipeline inferido", permission_filtered_absen'
    'ce_or_deleted_target: "Destino no visible o eliminado",\n      GlobalInitScript: "Init script global"'
    ', OutboundDependency: "Endpoint saliente"\n    }\n  };\n  var SEV_WORD = { critical: ["crítica", "críti'
    'cas"], high: ["alta", "altas"], medium: ["media", "medias"], low: ["baja", "bajas"] };\n  var SEV_BAR'
    ' = { critical: "var(--crit-bar)", high: "var(--high-bar)", medium: "var(--med-bar)", low: "var(--low'
    '-bar)" };\n  var NF = new Intl.NumberFormat("es-ES", { maximumFractionDigits: 2 });\n  var NF2 = new I'
    'ntl.NumberFormat("es-ES", { minimumFractionDigits: 2, maximumFractionDigits: 2 });\n  var ICON = {\n  '
    '  ext: ["M14 4h6v6", "M20 4l-9 9", "M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"],\n    '
    'check: ["M20 6L9 17l-5-5"],\n    alert: ["M12 3.5l9 16H3z", "M12 10v4", "M12 17.2v.3"],\n    info: ["M'
    '12 21a9 9 0 1 0 0-18 9 9 0 0 0 0 18z", "M12 11v5", "M12 7.8v.3"]\n  };\n\n  function el(tag, attrs, chi'
    'ldren) {\n    var node = document.createElement(tag);\n    if (attrs) {\n      Object.keys(attrs).forEa'
    'ch(function (k) {\n        if (k === "text") { node.textContent = String(attrs[k]); }\n        else if'
    ' (k === "className") { if (attrs[k]) { node.className = attrs[k]; } }\n        else if (attrs[k] !== '
    'null && attrs[k] !== undefined) { node.setAttribute(k, String(attrs[k])); }\n      });\n    }\n    if ('
    'children) {\n      children.forEach(function (c) {\n        if (typeof c === "string" || typeof c === '
    '"number") { node.appendChild(document.createTextNode(String(c))); }\n        else if (c) { node.appen'
    'dChild(c); }\n      });\n    }\n    return node;\n  }\n  function svg(tag, attrs, text) {\n    var node = '
    'document.createElementNS(SVGNS, tag);\n    Object.keys(attrs || {}).forEach(function (k) { node.setAt'
    'tribute(k, String(attrs[k])); });\n    if (text !== undefined) { node.textContent = String(text); }\n '
    '   return node;\n  }\n  function clear(node) { while (node.firstChild) { node.removeChild(node.firstCh'
    'ild); } }\n  function icon(name) {\n    var s = svg("svg", { "class": "i", viewBox: "0 0 24 24", "aria'
    '-hidden": "true", focusable: "false" });\n    ICON[name].forEach(function (d) { s.appendChild(svg("pa'
    'th", { d: d })); });\n    return s;\n  }\n  function lab(map, key) {\n    if (key === null || key === un'
    'defined || key === "") { return "—"; }\n    return Object.prototype.hasOwnProperty.call(map, key) ? m'
    'ap[key] : String(key);\n  }\n  function isNum(v) { return typeof v === "number" && isFinite(v); }\n  fu'
    'nction num(v) { return isNum(v) ? NF.format(v) : (v === null || v === undefined || v === "" ? "—" : '
    'String(v)); }\n  function pct(v) { return isNum(v) ? NF.format(v) + "\\u00a0%" : "No evaluado"; }\n  fu'
    'nction utc(s) {\n    if (!s) { return "—"; }\n    var m = /^(\\d{4}-\\d{2}-\\d{2})T(\\d{2}:\\d{2})/.exec(St'
    'ring(s));\n    return m ? m[1] + " " + m[2] + " UTC" : String(s);\n  }\n  function day(s) { var m = /^('
    '\\d{4}-\\d{2}-\\d{2})/.exec(String(s || "")); return m ? m[1] : "—"; }\n  function plural(n, one, many) '
    '{ return n === 1 ? one : many; }\n  function yesNo(v) { return v === true ? "Sí" : v === false ? "No"'
    ' : "No observado"; }\n  function access(v) { return v === "Disabled" ? "Deshabilitado" : v === "Enabl'
    'ed" ? "Habilitado" : (v || "No observado"); }\n  function rich(node, parts) {\n    clear(node);\n    pa'
    'rts.forEach(function (p) { if (p !== "" && p !== null) { node.appendChild(Array.isArray(p) ? el("b",'
    ' { text: p[0] }) : document.createTextNode(String(p))); } });\n    return node;\n  }\n  function brk(te'
    'xt, cls) {\n    var span = el("span", { className: cls === undefined ? "mono" : cls });\n    var s = S'
    'tring(text === null || text === undefined || text === "" ? "—" : text), buf = "";\n    if (s.length <'
    '= 24) { span.textContent = s; span.className += " nw"; return span; }\n    for (var i = 0; i < s.leng'
    'th; i++) {\n      buf += s.charAt(i);\n      if ("/_.-:,".indexOf(s.charAt(i)) >= 0 && i < s.length - '
    '1) {\n        span.appendChild(document.createTextNode(buf));\n        span.appendChild(document.creat'
    'eElement("wbr"));\n        buf = "";\n      }\n    }\n    if (buf) { span.appendChild(document.createTex'
    'tNode(buf)); }\n    return span;\n  }\n  function mono(text) { return el("span", { className: "mono nw"'
    ', text: text === null || text === undefined || text === "" ? "—" : text }); }\n  function stack(main,'
    ' sub) {\n    var d = el("div", { className: "stack" });\n    var b = el("b");\n    if (main instanceof '
    'Node) { b.appendChild(main); } else { b.textContent = main === null || main === undefined || main =='
    '= "" ? "—" : String(main); }\n    d.appendChild(b);\n    if (sub instanceof Node) { var w = el("small"'
    '); w.appendChild(sub); d.appendChild(w); }\n    else if (sub) { d.appendChild(el("small", { text: sub'
    ' })); }\n    return d;\n  }\n  function pill(cls, text, title) { return el("span", { className: "pill "'
    ' + cls, text: text, title: title || null }); }\n  function sevPill(sev, label) { return pill(SEVS.ind'
    'exOf(sev) >= 0 ? "sev-" + sev : "sev-info", label || lab(L.sev, sev)); }\n  function clsPill(c) { ret'
    'urn pill("cls-" + (c === "OBSERVED" || c === "INFERRED" ? c : "UNKNOWN"), c || "UNKNOWN"); }\n  funct'
    'ion statusTag(st) { return el("span", { className: "st st-" + (STATUS_ORDER[st] !== undefined ? st :'
    ' "not_evaluated"), title: st, text: lab(L.status, st) }); }\n  function srcTone(st) { return st === "'
    'complete" ? "tone-ok" : st === "partial" ? "tone-warn" : (st === "denied" || st === "error") ? "tone'
    '-crit" : "tone-info"; }\n  function srcPill(st) { return pill(srcTone(st), lab(L.src, st), st); }\n  f'
    'unction kindLabel(kind) { var t = lab(L.kind, kind); return el("span", { text: t, title: kind && t !'
    '== kind ? kind : null }); }\n  function emptyState(text) { return el("div", { className: "empty" }, ['
    'icon("check"), el("span", { text: text })]); }\n  function safeLearnUrl(u) {\n    if (typeof u !== "st'
    'ring") { return null; }\n    try {\n      var parsed = new URL(u);\n      return (parsed.protocol === "'
    'https:" && (parsed.hostname === "learn.microsoft.com" || parsed.hostname === "docs.databricks.com"))'
    ' ? u : null;\n    } catch (e) { return null; }\n  }\n  function extLink(href, text) { return el("a", { '
    'className: "ext", href: href, target: "_blank", rel: "noopener noreferrer" }, [text, icon("ext")]); '
    '}\n  var ARM_RE = /^\\/subscriptions\\/[0-9a-f-]{36}\\/resourcegroups\\/([^\\/]+)\\/providers\\/(microsoft\\.'
    '[a-z0-9]+\\/[a-z0-9]+)\\/([^\\/]+)(?:\\/([a-z0-9]+)\\/([^\\/]+))?$/i;\n  function armCell(id, name) {\n    v'
    'ar m = ARM_RE.exec(String(id || ""));\n    if (!m) { return brk(id); }\n    var box = el("div", { clas'
    'sName: "res" });\n    box.appendChild(el("b", { text: name || m[5] || m[3] }));\n    box.appendChild(e'
    'l("small", null, [brk(m[1] + " · " + m[2] + (m[4] ? "/" + m[4] : ""), "")]));\n    var a = extLink("h'
    'ttps://portal.azure.com/#@/resource" + id, "Portal");\n    a.setAttribute("title", id);\n    box.appen'
    'dChild(a);\n    return box;\n  }\n  function kvChips(obj, max) {\n    var wrap = el("div", { className: '
    '"chips" }), shown = 0;\n    Object.keys(obj || {}).forEach(function (k) {\n      var v = obj[k];\n     '
    ' if (v === null || v === undefined || v === "" || typeof v === "object" || shown >= max) { return; }'
    '\n      var s = String(v);\n      if (s.indexOf("/subscriptions/") === 0 || s.length > 70) { return; }'
    '\n      wrap.appendChild(el("span", null, [k + ": ", el("b", { text: s })]));\n      shown++;\n    });\n'
    '    return shown ? wrap : null;\n  }\n  function evidenceCell(obj) {\n    var box = el("div"), chips = '
    'kvChips(obj, 4), json = JSON.stringify(obj || {}, null, 1);\n    if (chips) { box.appendChild(chips);'
    ' }\n    if (json && json.length > 2) {\n      var d = el("details", { className: "json" });\n      d.ap'
    'pendChild(el("summary", { text: "JSON completo" }));\n      d.appendChild(el("pre", { text: json }));'
    '\n      box.appendChild(d);\n    }\n    if (!box.firstChild) { box.textContent = "—"; }\n    return box;'
    '\n  }\n\n  var TSTATE = {};\n  function spec(c) { return (c !== null && typeof c === "object" && !(c ins'
    'tanceof Node) && Object.prototype.hasOwnProperty.call(c, "v")) ? c : { v: c }; }\n  function sortValu'
    'e(c) {\n    if (c.s !== undefined) { return c.s; }\n    return c.v instanceof Node ? c.v.textContent :'
    ' (c.v === null || c.v === undefined ? "" : c.v);\n  }\n  function renderTable(tableNode, headers, rows'
    ', opts) {\n    var st = TSTATE[tableNode.id] || (TSTATE[tableNode.id] = { sort: -1, dir: 1 });\n    st'
    '.headers = headers.map(function (h) { return typeof h === "string" ? { t: h } : h; });\n    st.rows ='
    ' rows.map(function (r) { return r.map(spec); });\n    st.opts = opts || {};\n    st.limit = st.opts.pa'
    'ge || 0;\n    drawTable(tableNode, st, null);\n  }\n  function drawTable(tableNode, st, focus) {\n    va'
    'r headers = st.headers, opts = st.opts, rows = st.rows;\n    if (st.sort >= 0) {\n      var i = st.sor'
    't, dir = st.dir;\n      rows = rows.map(function (r, idx) { return { r: r, idx: idx }; }).sort(functi'
    'on (a, b) {\n        var x = sortValue(a.r[i]), y = sortValue(b.r[i]);\n        var d = (isNum(x) && i'
    'sNum(y)) ? x - y : String(x).localeCompare(String(y), "es", { numeric: true, sensitivity: "base" });'
    '\n        return d * dir || a.idx - b.idx;\n      }).map(function (o) { return o.r; });\n    }\n    clea'
    'r(tableNode);\n    var thead = el("thead"), trh = el("tr");\n    headers.forEach(function (h, hi) {\n  '
    '    var th = el("th", { className: h.c || null, scope: "col" });\n      if (opts.sortable && h.s !== '
    'false) {\n        var b = el("button", { type: "button", className: "th-sort", text: h.t });\n        '
    'th.setAttribute("data-label", h.t);\n        if (st.sort === hi) { th.setAttribute("aria-sort", st.di'
    'r === 1 ? "ascending" : "descending"); }\n        b.addEventListener("click", function () {\n         '
    ' if (st.sort === hi) { st.dir = -st.dir; } else { st.sort = hi; st.dir = 1; }\n          drawTable(ta'
    'bleNode, st, "th" + hi);\n        });\n        th.appendChild(b);\n      } else { th.textContent = h.t;'
    ' }\n      trh.appendChild(th);\n    });\n    thead.appendChild(trh);\n    tableNode.appendChild(thead);\n'
    '    var tbody = el("tbody");\n    if (!rows.length) {\n      var tr0 = el("tr");\n      tr0.appendChild'
    '(el("td", { colspan: headers.length, className: "empty-cell", text: opts.empty || "Sin registros en '
    'este alcance o filtro." }));\n      tbody.appendChild(tr0);\n    }\n    rows.forEach(function (cells, r'
    'i) {\n      var tr = el("tr", { className: st.limit && ri >= st.limit ? "pg" : null });\n      cells.f'
    'orEach(function (c, ci) {\n        var td = el("td", { className: [headers[ci] && headers[ci].c, c.c]'
    '.filter(Boolean).join(" ") || null });\n        if (c.v instanceof Node) { td.appendChild(c.v); }\n   '
    '     else { td.textContent = c.v === null || c.v === undefined || c.v === "" ? "—" : String(c.v); }\n'
    '        tr.appendChild(td);\n      });\n      tbody.appendChild(tr);\n    });\n    tableNode.appendChild'
    '(tbody);\n    var wrap = tableNode.parentNode, more = wrap.nextElementSibling;\n    if (!more || !more'
    '.classList.contains("more-row")) {\n      more = el("div", { className: "more-row" });\n      wrap.par'
    'entNode.insertBefore(more, wrap.nextSibling);\n    }\n    clear(more);\n    var hiddenRows = st.limit ?'
    ' Math.max(0, rows.length - st.limit) : 0;\n    more.hidden = hiddenRows === 0;\n    if (hiddenRows) {\n'
    '      var step = opts.page;\n      var b1 = el("button", { type: "button", className: "btn ghost sm",'
    ' "data-k": "more", text: "Mostrar " + Math.min(step, hiddenRows) + " más" });\n      b1.addEventListe'
    'ner("click", function () { st.limit += step; drawTable(tableNode, st, "more"); });\n      var b2 = el'
    '("button", { type: "button", className: "btn ghost sm", "data-k": "all", text: "Mostrar todas (" + r'
    'ows.length + ")" });\n      b2.addEventListener("click", function () { st.limit = 0; drawTable(tableN'
    'ode, st, "table"); });\n      more.appendChild(el("span", { className: "more-note", text: "Mostrando '
    '" + st.limit + " de " + rows.length + " filas" }));\n      more.appendChild(b1);\n      more.appendChi'
    'ld(b2);\n    }\n    if (focus) {\n      var target = focus.indexOf("th") === 0 ? tableNode.querySelecto'
    'rAll(".th-sort")[Number(focus.slice(2))] : focus === "more" ? more.querySelector("[data-k=more]") : '
    'null;\n      if (target) { target.focus(); }\n      else if (focus === "more" || focus === "table") { '
    'tableNode.setAttribute("tabindex", "-1"); tableNode.focus(); }\n    }\n  }\n\n  var rawText = document.g'
    'etElementById("report-data").textContent;\n  var rootData;\n  try {\n    rootData = JSON.parse(rawText)'
    ';\n  } catch (e) {\n    var openErr = document.getElementById("opening-state");\n    openErr.hidden = f'
    'alse;\n    openErr.textContent = "Error al cargar el modelo JSON embebido del informe.";\n    return;\n'
    '  }\n\n  var isMulti = rootData && rootData.schema_version === "databricks-dep-multi-workspace-v1";\n  '
    'var currentSnap = null;\n\n  var themeBtn = document.getElementById("theme-toggle");\n  themeBtn.addEve'
    'ntListener("click", function () {\n    var dark = document.documentElement.getAttribute("data-theme")'
    ' === "dark";\n    if (dark) { document.documentElement.removeAttribute("data-theme"); }\n    else { do'
    'cument.documentElement.setAttribute("data-theme", "dark"); }\n    themeBtn.setAttribute("aria-pressed'
    '", dark ? "false" : "true");\n  });\n  document.getElementById("print-btn").addEventListener("click", '
    'function () { window.print(); });\n  var themeBeforePrint = null;\n  window.addEventListener("beforepr'
    'int", function () {\n    themeBeforePrint = document.documentElement.getAttribute("data-theme");\n    '
    'document.documentElement.removeAttribute("data-theme");\n  });\n  window.addEventListener("afterprint"'
    ', function () {\n    if (themeBeforePrint) { document.documentElement.setAttribute("data-theme", them'
    'eBeforePrint); }\n    themeBeforePrint = null;\n  });\n\n  function closeMenus(except) {\n    [].forEach.'
    'call(document.querySelectorAll("details.menu[open]"), function (d) { if (d !== except) { d.removeAtt'
    'ribute("open"); } });\n  }\n  document.addEventListener("click", function (ev) {\n    var inside = ev.t'
    'arget.closest ? ev.target.closest("details.menu") : null;\n    closeMenus(inside);\n    if (inside && '
    'ev.target.closest("a, button") && !ev.target.closest("summary")) { inside.removeAttribute("open"); }'
    '\n  });\n  document.addEventListener("keydown", function (ev) {\n    if (ev.key !== "Escape") { return;'
    ' }\n    var open = document.querySelector("details.menu[open]");\n    if (open) { open.removeAttribute'
    '("open"); open.querySelector("summary").focus(); }\n  });\n\n  function downloadBlob(filename, content,'
    ' mime) {\n    var blob = new Blob([content], { type: mime });\n    var url = URL.createObjectURL(blob)'
    ';\n    var a = el("a", { href: url, download: filename });\n    document.body.appendChild(a);\n    a.cl'
    'ick();\n    document.body.removeChild(a);\n    URL.revokeObjectURL(url);\n  }\n  function csvEscape(v) {'
    '\n    if (v === null || v === undefined) { return ""; }\n    var s = typeof v === "object" ? JSON.stri'
    'ngify(v) : String(v);\n    if (/^[=+\\-@\\t\\r\\n]/.test(s.trimLeft())) { s = "\'" + s; }\n    return \'"\' +'
    ' s.replace(/"/g, \'""\') + \'"\';\n  }\n  var CHECK_COLS = ["check_id", "rule_id", "title", "status", "lev'
    'el", "area", "pillar", "severity", "workload_name", "reason", "recommendation", "learn_url"];\n  func'
    'tion checksCsv(list) {\n    var lines = [CHECK_COLS.join(",")];\n    list.forEach(function (r) { lines'
    '.push(CHECK_COLS.map(function (c) { return csvEscape(r[c]); }).join(",")); });\n    return "\\uFEFF" +'
    ' lines.join("\\r\\n");\n  }\n  document.getElementById("export-json-btn").addEventListener("click", func'
    'tion () {\n    downloadBlob("databricks-dependency-snapshot.json", JSON.stringify(rootData, null, 2),'
    ' "application/json;charset=utf-8");\n  });\n  document.getElementById("export-deps-csv-btn").addEventL'
    'istener("click", function () {\n    if (!currentSnap) { return; }\n    var cols = ["record_type", "cla'
    'ssification", "layer", "id", "kind", "label", "from", "to", "relation", "join_fields", "source_ids"]'
    ';\n    var lines = [cols.join(",")];\n    var dep = currentSnap.dependencies;\n    [].concat(dep.nodes '
    '|| [], dep.edges || [], dep.unknowns || []).forEach(function (r) {\n      lines.push(cols.map(functio'
    'n (c) { return csvEscape(r[c]); }).join(","));\n    });\n    downloadBlob("databricks-dependencies.csv'
    '", "\\uFEFF" + lines.join("\\r\\n"), "text/csv;charset=utf-8");\n  });\n  document.getElementById("export'
    '-findings-csv-btn").addEventListener("click", function () {\n    if (!currentSnap) { return; }\n    do'
    'wnloadBlob("databricks-findings.csv", checksCsv(currentSnap.checks || []), "text/csv;charset=utf-8")'
    ';\n  });\n\n  var tabObs = document.getElementById("tab-dep-observed");\n  var tabRef = document.getElem'
    'entById("tab-dep-reference");\n  var panelObs = document.getElementById("panel-dep-observed");\n  var '
    'panelRef = document.getElementById("panel-dep-reference");\n  function selectTab(ref) {\n    tabObs.se'
    'tAttribute("aria-selected", ref ? "false" : "true");\n    tabRef.setAttribute("aria-selected", ref ? '
    '"true" : "false");\n    tabObs.setAttribute("tabindex", ref ? "-1" : "0");\n    tabRef.setAttribute("t'
    'abindex", ref ? "0" : "-1");\n    panelObs.hidden = ref;\n    panelRef.hidden = !ref;\n  }\n  tabObs.add'
    'EventListener("click", function () { selectTab(false); });\n  tabRef.addEventListener("click", functi'
    'on () { selectTab(true); });\n  [tabObs, tabRef].forEach(function (t) {\n    t.addEventListener("keydo'
    'wn", function (ev) {\n      if (ev.key === "ArrowRight" || ev.key === "ArrowLeft") {\n        var ref '
    '= t === tabObs;\n        selectTab(ref);\n        (ref ? tabRef : tabObs).focus();\n        ev.preventD'
    'efault();\n      }\n    });\n  });\n\n  function fitText(s, max) { s = String(s || ""); return s.length >'
    ' max ? s.slice(0, Math.max(1, max - 1)) + "…" : s; }\n  function nodeLines(n) {\n    var label = Strin'
    'g(n.label || n.name || n.id), kind = lab(L.kind, n.kind), cut = label.indexOf(" :: ");\n    if (cut <'
    ' 0) { cut = label.indexOf(" / "); }\n    if (cut > 0) { return [label.slice(label.indexOf(" ", cut + '
    '1) + 1), kind + " · " + label.slice(0, cut)]; }\n    return [label, kind + (n.classification === "INF'
    'ERRED" ? " · INFERRED" : "")];\n  }\n  function renderNeighborhoodSvg(nodes, edges) {\n    var box = do'
    'cument.getElementById("dep-graph-box");\n    var caption = document.getElementById("dep-graph-caption'
    '");\n    clear(box);\n    if (!nodes.length) { box.appendChild(emptyState("Ningún nodo coincide con es'
    'te filtro.")); caption.textContent = ""; return; }\n    var deg = {};\n    edges.forEach(function (e) '
    '{ deg[e.from] = (deg[e.from] || 0) + 1; deg[e.to] = (deg[e.to] || 0) + 1; });\n    var subset = nodes'
    '.map(function (n, i) {\n      return { n: n, i: i, r: (n.kind === "databricks_workspace" ? 1000 : 0) '
    '+ (n.classification === "INFERRED" ? 500 : 0) + (deg[n.id] || 0) };\n    }).sort(function (a, b) { re'
    'turn b.r - a.r || a.i - b.i; }).slice(0, 13).map(function (x) { return x.n; });\n    var order = LAYE'
    'RS.slice();\n    subset.forEach(function (n) { if (order.indexOf(n.layer) < 0) { order.push(n.layer);'
    ' } });\n    var cols = [];\n    order.forEach(function (layer) {\n      var ns = subset.filter(function'
    ' (n) { return n.layer === layer; });\n      for (var i = 0; i < ns.length; i += 5) { cols.push({ laye'
    'r: layer, nodes: ns.slice(i, i + 5), head: i === 0 }); }\n    });\n    var W = 1200, colW = W / cols.l'
    'ength, bw = Math.min(214, colW - 30), bh = 50, gy = 20, top = 34;\n    var rows = Math.max.apply(null'
    ', cols.map(function (c) { return c.nodes.length; }));\n    var H = top + rows * (bh + gy);\n    var po'
    's = {};\n    cols.forEach(function (c, ci) {\n      var off = (rows - c.nodes.length) * (bh + gy) / 2;'
    '\n      c.nodes.forEach(function (n, ri) { pos[n.id] = { x: colW * ci + colW / 2, y: top + off + ri *'
    ' (bh + gy) + bh / 2, c: ci }; });\n    });\n    var s = svg("svg", { viewBox: "0 0 " + W + " " + H, ro'
    'le: "img", "aria-label": "Grafo de dependencias: " + subset.length + " de " + nodes.length + " nodos'
    ' filtrados, agrupados por capa." });\n    var defs = svg("defs");\n    ["obs", "inf"].forEach(function'
    ' (k) {\n      var m = svg("marker", { id: "dep-arrow-" + k, viewBox: "0 0 10 10", refX: 9, refY: 5, m'
    'arkerWidth: 6, markerHeight: 6, orient: "auto" });\n      m.appendChild(svg("path", { d: "M0 0L10 5L0'
    ' 10z", "class": "arr " + k }));\n      defs.appendChild(m);\n    });\n    s.appendChild(defs);\n    cols'
    '.forEach(function (c, ci) {\n      if (c.head) { s.appendChild(svg("text", { x: colW * ci + colW / 2 '
    '- bw / 2, y: 16, "class": "g-col" }, fitText(lab(L.layer, c.layer), Math.floor(bw / 7.5)))); }\n    }'
    ');\n    var drawn = 0;\n    edges.forEach(function (e) {\n      var a = pos[e.from], b = pos[e.to];\n   '
    '   if (!a || !b || e.from === e.to) { return; }\n      var sx, ex, c1, c2;\n      if (a.c < b.c) { sx '
    '= a.x + bw / 2; ex = b.x - bw / 2 - 2; c1 = sx + (ex - sx) / 2; c2 = ex - (ex - sx) / 2; }\n      els'
    'e if (a.c > b.c) { sx = a.x - bw / 2; ex = b.x + bw / 2 + 2; c1 = sx - (sx - ex) / 2; c2 = ex + (sx '
    '- ex) / 2; }\n      else { sx = a.x + bw / 2; ex = b.x + bw / 2 + 2; c1 = sx + 26; c2 = ex + 26; }\n  '
    '    var k = e.classification === "INFERRED" ? "inf" : "obs";\n      s.appendChild(svg("path", { d: "M'
    '" + sx + " " + a.y + " C" + c1 + " " + a.y + " " + c2 + " " + b.y + " " + ex + " " + b.y, "class": "'
    'edge " + k, "marker-end": "url(#dep-arrow-" + k + ")" }));\n      drawn++;\n    });\n    var maxChars ='
    ' Math.floor((bw - 22) / 6.9);\n    subset.forEach(function (n) {\n      var p = pos[n.id], lines = nod'
    'eLines(n);\n      var g = svg("g", { "class": "g-node" + (n.classification === "INFERRED" ? " inf" : '
    '"") + (n.kind === "databricks_workspace" ? " ws" : "") });\n      g.appendChild(svg("title", {}, (n.l'
    'abel || n.id) + " · " + (n.kind || "") + " · " + (n.classification || "")));\n      g.appendChild(svg'
    '("rect", { x: p.x - bw / 2, y: p.y - bh / 2, width: bw, height: bh, rx: 8 }));\n      g.appendChild(s'
    'vg("text", { x: p.x - bw / 2 + 11, y: p.y - 3, "class": "g-l1" }, fitText(lines[0], maxChars)));\n   '
    '   g.appendChild(svg("text", { x: p.x - bw / 2 + 11, y: p.y + 14, "class": "g-l2" }, fitText(lines[1'
    '], Math.floor((bw - 22) / 6))));\n      s.appendChild(g);\n    });\n    box.appendChild(s);\n    caption'
    '.textContent = "Mostrando " + subset.length + " de " + nodes.length + " nodos filtrados y " + drawn '
    '+ " relaciones entre ellos (vista acotada a 13 nodos: workspace, referencias INFERRED y nodos más co'
    'nectados). Las tablas contienen el 100 % de los nodos, aristas y puntos ciegos.";\n  }\n\n  function re'
    'nderReferenceArchitecture() {\n    var box = document.getElementById("ref-arch-box");\n    clear(box);'
    '\n    var s = svg("svg", { viewBox: "0 0 1200 236", role: "img", "aria-label": "Arquitectura de refer'
    'encia Azure Databricks Lakehouse - Propuesta NO desplegada" });\n    var flag = svg("g", { "class": "'
    'ref-flag" });\n    flag.appendChild(svg("rect", { x: 0, y: 4, width: 300, height: 24, rx: 12 }));\n   '
    ' flag.appendChild(svg("text", { x: 14, y: 20 }, "PROPUESTA DE REFERENCIA · NO DESPLEGADA"));\n    s.a'
    'ppendChild(flag);\n    var boxes = [\n      ["Red y Perímetro (ARM)", "VNet Injection + SCC + Private '
    'Link"],\n      ["Identidad y Secretos", "Entra SP/UAMI + Key Vault Scopes"],\n      ["Cómputo y Orques'
    'tación", "Cluster Policies + Job/Serverless"],\n      ["Unity Catalog & ADLS", "Access Connector UAMI'
    ' + Linaje"]\n    ];\n    var bw = 262, gap = (1200 - 4 * bw) / 3;\n    boxes.forEach(function (b, i) {\n'
    '      var x = i * (bw + gap);\n      if (i < boxes.length - 1) { s.appendChild(svg("line", { x1: x + '
    'bw, y1: 92, x2: x + bw + gap, y2: 92, "class": "ref-link" })); }\n      var g = svg("g", { "class": "'
    'ref-box" });\n      g.appendChild(svg("rect", { x: x + 1, y: 52, width: bw - 2, height: 80, rx: 10 })'
    ');\n      g.appendChild(svg("text", { x: x + 18, y: 86, "class": "ref-t" }, b[0]));\n      g.appendChi'
    'ld(svg("text", { x: x + 18, y: 108, "class": "ref-s" }, b[1]));\n      s.appendChild(g);\n    });\n    '
    's.appendChild(svg("text", { x: 0, y: 176, "class": "ref-note" }, "PROPUESTA DE REFERENCIA (NO DESPLE'
    'GADA): Integración entre tenants mediante Entra Multi-tenant FIC o Lighthouse + Databricks OIDC."));'
    '\n    s.appendChild(svg("text", { x: 0, y: 204, "class": "ref-s" }, "Componentes recomendados para co'
    'mparar con el mapa observado; ninguno se ha detectado ni creado en el workspace revisado."));\n    bo'
    'x.appendChild(s);\n    renderTable(document.getElementById("ref-arch-table"),\n      ["Componente de r'
    'eferencia", "Práctica recomendada Microsoft / Databricks", "Compromiso / Trade-off"],\n      [\n      '
    '  ["VNet Injection + Secure Cluster Connectivity", "Desplegar en VNet propia con enableNoPublicIp=tr'
    'ue y subredes delegadas host/container con NSG.", "Exige planificación IPAM y rutas salientes hacia '
    'endpoints de plano de control."],\n        ["Private Link (Front-end / Back-end / WebAuth)", "Aislar '
    'tráfico de usuarios y plano de datos mediante Private Endpoints aprobados y zonas DNS privadas.", "R'
    'equiere SKU Premium y gestión de DNS privado entre redes hub-spoke."],\n        ["Unity Catalog + Acc'
    'ess Connector (UAMI)", "Gobernar catálogos y External Locations con Storage Credentials basadas en M'
    'anaged Identity.", "Sustituye claves compartidas y montajes DBFS heredados."],\n        ["Jobs sobre '
    'Job Compute / Serverless + Service Principal", "Ejecutar jobs productivos con run_as Service Princip'
    'al sobre cómputo efímero de Job o Serverless.", "Reduce coste DBU frente a All-Purpose y evita fallo'
    's por baja de usuarios."],\n        ["Integración Cross-Tenant sin secretos", "Usar App multitenant c'
    'on Federated Identity Credential (UAMI) o Azure Lighthouse (ARM) + Databricks OIDC Federation.", "Re'
    'quiere consentimiento/asignación por administradores de ambos tenants."]\n      ].map(function (r) { '
    'return [{ v: el("b", { text: r[0] }) }, r[1], r[2]]; })\n    );\n  }\n\n  function applyDependencyFilter'
    's() {\n    if (!currentSnap) { return; }\n    var layer = document.getElementById("dep-layer-filter").'
    'value;\n    var cls = document.getElementById("dep-class-filter").value;\n    var q = (document.getEle'
    'mentById("dep-search-filter").value || "").toLowerCase().trim();\n    var dep = currentSnap.dependenc'
    'ies || { nodes: [], edges: [], unknowns: [], broken_references: [] };\n    function keep(r) {\n      i'
    'f (layer !== "all" && r.layer !== layer) { return false; }\n      if (cls !== "all" && r.classificati'
    'on !== cls) { return false; }\n      if (q && JSON.stringify(r).toLowerCase().indexOf(q) === -1) { re'
    'turn false; }\n      return true;\n    }\n    var nodes = (dep.nodes || []).filter(keep);\n    var edges'
    ' = (dep.edges || []).filter(keep);\n    var unknowns = (dep.unknowns || []).filter(keep);\n    var byI'
    'd = {};\n    (dep.nodes || []).forEach(function (n) { byId[n.id] = n; });\n    function nodeCell(id) {'
    '\n      var n = byId[id];\n      return n ? { v: stack(brk(n.label || n.id, ""), lab(L.kind, n.kind)),'
    ' s: n.label || n.id } : { v: brk(id) };\n    }\n    renderNeighborhoodSvg(nodes, edges);\n    document.'
    'getElementById("dep-edges-count").textContent = String(edges.length);\n    renderTable(document.getEl'
    'ementById("dep-edges-table"),\n      ["Clasificación", "Capa", "Origen", "Relación", "Destino", "Camp'
    'os join", "Fuentes"],\n      edges.map(function (e) {\n        return [\n          { v: clsPill(e.class'
    'ification), s: e.classification },\n          lab(L.layer, e.layer),\n          nodeCell(e.from),\n    '
    '      { v: brk(e.relation), s: e.relation },\n          nodeCell(e.to),\n          { v: brk((e.join_fi'
    'elds || []).join(", ")) },\n          { v: brk((e.source_ids || []).join(", ")) }\n        ];\n      })'
    ', { page: 12, sortable: true }\n    );\n    document.getElementById("dep-nodes-count").textContent = S'
    'tring(nodes.length);\n    renderTable(document.getElementById("dep-nodes-table"),\n      ["Clasificaci'
    'ón", "Capa", "Tipo", "Nombre / etiqueta", "Fuente", { t: "Evidencia", s: false, c: "w" }],\n      nod'
    'es.map(function (n) {\n        return [\n          { v: clsPill(n.classification), s: n.classification'
    ' },\n          lab(L.layer, n.layer),\n          { v: kindLabel(n.kind) },\n          { v: brk(n.label '
    '|| n.id, ""), s: n.label },\n          { v: mono(n.source_id) },\n          { v: evidenceCell(n.eviden'
    'ce) }\n        ];\n      }), { page: 12, sortable: true }\n    );\n    var broken = dep.broken_reference'
    's || [];\n    document.getElementById("dep-broken-count").textContent = String(broken.length);\n    re'
    'nderTable(document.getElementById("dep-broken-table"),\n      ["Objeto origen", "Tipo de referencia r'
    'ota", "ID destino no encontrado"],\n      broken.map(function (b) { return [b.source_object, b.kind, '
    '{ v: brk(b.target_id) }]; }),\n      { empty: "Sin referencias rotas entre tareas, clústeres, pools, '
    'políticas, pipelines, warehouses y credenciales." }\n    );\n    document.getElementById("dep-unknowns'
    '-count").textContent = String(unknowns.length);\n    renderTable(document.getElementById("dep-unknown'
    's-table"),\n      ["Capa", "Código", "Descripción del punto ciego", "Fuentes"],\n      unknowns.map(fu'
    'nction (u) {\n        return [lab(L.layer, u.layer), { v: brk(u.code) }, u.message, { v: brk((u.sourc'
    'e_ids || []).join(", ")) }];\n      })\n    );\n  }\n\n  function observedValues(evidence) {\n    var merg'
    'ed = {};\n    (Array.isArray(evidence) ? evidence : []).forEach(function (ev) {\n      if (ev && ev.va'
    'lue && typeof ev.value === "object" && !Array.isArray(ev.value)) {\n        Object.keys(ev.value).for'
    'Each(function (k) { merged[k] = ev.value[k]; });\n      }\n    });\n    return kvChips(merged, 3);\n  }\n'
    '  function filteredChecks() {\n    var area = document.getElementById("find-area-filter").value;\n    '
    'var level = document.getElementById("find-level-filter").value;\n    var sev = document.getElementByI'
    'd("find-sev-filter").value;\n    var st = document.getElementById("find-status-filter").value;\n    va'
    'r q = (document.getElementById("find-search-filter").value || "").toLowerCase().trim();\n    return ('
    'currentSnap.checks || []).filter(function (c) {\n      if (area !== "all" && c.area !== area) { retur'
    'n false; }\n      if (level !== "all" && c.level !== level) { return false; }\n      if (sev !== "all"'
    ' && c.severity !== sev) { return false; }\n      if (st !== "all" && c.status !== st) { return false;'
    ' }\n      if (q && JSON.stringify(c).toLowerCase().indexOf(q) === -1) { return false; }\n      return '
    'true;\n    });\n  }\n  function applyFindingFilters() {\n    if (!currentSnap) { return; }\n    var all ='
    ' currentSnap.checks || [];\n    var filtered = filteredChecks().slice().sort(function (a, b) {\n      '
    'return (STATUS_ORDER[a.status] - STATUS_ORDER[b.status]) || (SEVS.indexOf(a.severity) - SEVS.indexOf'
    '(b.severity)) || String(a.rule_id).localeCompare(String(b.rule_id), "es", { numeric: true });\n    })'
    ';\n    var failed = filtered.filter(function (c) { return c.status === "failed"; }).length;\n    docum'
    'ent.getElementById("findings-count-label").textContent = "Mostrando " + filtered.length + " de " + a'
    'll.length + " comprobaciones · " + failed + plural(failed, " no cumple", " no cumplen") + ".";\n    r'
    'enderTable(document.getElementById("findings-table"),\n      [{ t: "Estado" }, { t: "Severidad" }, { '
    't: "Regla" }, { t: "Área / pilar" }, { t: "Objeto" }, { t: "Hallazgo y evidencia", c: "w" }, { t: "R'
    'ecomendación", c: "w" }],\n      filtered.map(function (c) {\n        var link = safeLearnUrl(c.learn_'
    'url);\n        var detail = el("div", { className: "fd" });\n        detail.appendChild(el("b", { text'
    ': c.title }));\n        detail.appendChild(el("p", { text: c.reason }));\n        var chips = observed'
    'Values(c.evidence);\n        if (chips) { detail.appendChild(chips); }\n        var rec = el("div", { '
    'className: "fr" });\n        rec.appendChild(el("p", { text: c.recommendation }));\n        if (link) '
    '{ rec.appendChild(extLink(link, "Documentación oficial")); }\n        return [\n          { v: statusT'
    'ag(c.status), s: STATUS_ORDER[c.status] },\n          { v: sevPill(c.severity, c.severity_label), s: '
    'SEVS.indexOf(c.severity) },\n          { v: stack(c.rule_id, mono(c.reference_id)), s: c.rule_id },\n '
    '         { v: stack(lab(L.area, c.area), lab(L.pillar, c.pillar)), s: lab(L.area, c.area) },\n       '
    '   { v: stack(brk(c.workload_name || c.resource_name || c.workspace_name, ""), lab(L.level, c.level)'
    '), s: c.workload_name || c.resource_name || "" },\n          { v: detail, s: c.title },\n          { v'
    ': rec, s: c.recommendation }\n        ];\n      }), { page: 15, sortable: true }\n    );\n  }\n\n  ["dep-l'
    'ayer-filter", "dep-class-filter", "dep-search-filter"].forEach(function (id) {\n    document.getEleme'
    'ntById(id).addEventListener("input", applyDependencyFilters);\n    document.getElementById(id).addEve'
    'ntListener("change", applyDependencyFilters);\n  });\n  ["find-area-filter", "find-level-filter", "fin'
    'd-sev-filter", "find-status-filter", "find-search-filter"].forEach(function (id) {\n    document.getE'
    'lementById(id).addEventListener("input", applyFindingFilters);\n    document.getElementById(id).addEv'
    'entListener("change", applyFindingFilters);\n  });\n  document.getElementById("dep-clear").addEventLis'
    'tener("click", function () {\n    document.getElementById("dep-layer-filter").value = "all";\n    docu'
    'ment.getElementById("dep-class-filter").value = "all";\n    document.getElementById("dep-search-filte'
    'r").value = "";\n    applyDependencyFilters();\n  });\n  document.getElementById("find-clear").addEvent'
    'Listener("click", function () {\n    ["find-area-filter", "find-level-filter", "find-sev-filter", "fi'
    'nd-status-filter"].forEach(function (id) { document.getElementById(id).value = "all"; });\n    docume'
    'nt.getElementById("find-search-filter").value = "";\n    applyFindingFilters();\n  });\n  document.getE'
    'lementById("find-export-btn").addEventListener("click", function () {\n    if (!currentSnap) { return'
    '; }\n    downloadBlob("databricks-findings-filtered.csv", checksCsv(filteredChecks()), "text/csv;char'
    'set=utf-8");\n  });\n\n  function barRow(label, sub, width, value, valueSub, color, na) {\n    var row ='
    ' el("div", { className: "brow" + (na ? " na" : "") });\n    var bl = el("div", { className: "bl" }, ['
    'label]);\n    if (sub) { bl.appendChild(el("small", { text: sub })); }\n    row.appendChild(bl);\n    v'
    'ar bar = el("i");\n    bar.style.width = Math.max(0, Math.min(100, width)) + "%";\n    if (color) { ba'
    'r.style.background = color; }\n    if (na || !width) { bar.style.minWidth = "0"; }\n    row.appendChil'
    'd(el("div", { className: "bt" }, [bar]));\n    var bv = el("div", { className: "bv", text: value });\n'
    '    if (valueSub) { bv.appendChild(el("small", { text: valueSub })); }\n    row.appendChild(bv);\n    '
    'return row;\n  }\n  function scoreBars(id, map, labels) {\n    var holder = document.getElementById(id)'
    ';\n    clear(holder);\n    Object.keys(map || {}).forEach(function (k) {\n      var it = map[k] || {}, '
    'na = !isNum(it.score);\n      holder.appendChild(barRow(lab(labels, k), null, na ? 0 : it.score, na ?'
    ' "No evaluado" : pct(it.score),\n        "cobertura " + (isNum(it.coverage_percent) ? pct(it.coverage'
    '_percent) : "0\\u00a0%"), null, na));\n    });\n  }\n  function kpi(value, unit, label, sub) {\n    var v'
    ' = el("div", { className: "v" }, [String(value)]);\n    if (unit) { v.appendChild(el("small", { text:'
    ' unit })); }\n    return el("div", { className: "kpi" }, [v, el("div", { className: "l", text: label '
    '}), sub ? el("div", { className: "s", text: sub }) : null]);\n  }\n  function pctParts(v) { return isN'
    'um(v) ? [NF.format(v), "%"] : ["—", ""]; }\n  function sourcePlane(id) {\n    id = String(id || "");\n '
    '   if (id.indexOf("arm_") === 0 || id === "azure_cost") { return "Plano 1 · ARM"; }\n    if (id.index'
    'Of("dbx_") === 0) { return "Plano 2 · Databricks REST"; }\n    if (id.indexOf("uc_") === 0) { return '
    '"Plano 2 · Unity Catalog"; }\n    return "Interno";\n  }\n  var SRC_COLOR = { complete: "var(--ok-bar)"'
    ', partial: "var(--med-bar)", denied: "var(--crit-bar)", error: "var(--crit-bar)", not_configured: "v'
    'ar(--info-bar)", not_applicable: "var(--line2)" };\n\n  function renderHero(snap, g, counts) {\n    var'
    ' ws = snap.workspace || {}, sc = (snap.dependencies && snap.dependencies.summary_counts) || {};\n    '
    'var fails = (snap.findings || []).length, ev = g.evaluated || 0;\n    var sevText = SEVS.filter(funct'
    'ion (s) { return counts[s]; }).map(function (s) { return counts[s] + " " + plural(counts[s], SEV_WOR'
    'D[s][0], SEV_WORD[s][1]); }).join(" · ");\n    var depParts = [" El mapa de dependencias reúne ", [nu'
    'm(sc.nodes_total || 0)], " nodos y ", [num(sc.edges_total || 0)], " relaciones, con ", [num(sc.edges'
    '_inferred || 0)], " referencias INFERRED y ", [num(sc.unknowns_total || 0)], " puntos ciegos UNKNOWN'
    '."];\n    rich(document.getElementById("cover-lead"), ev ? [[num(fails)], plural(fails, " comprobació'
    'n no cumple", " comprobaciones no cumplen"), sevText ? " (" + sevText + ")" : "", " de ", [num(ev)],'
    ' " evaluadas; índice local ", [pct(g.score)], " con una cobertura del ", [pct(g.coverage_percent)], '
    '"."].concat(depParts)\n      : ["Ninguna comprobación pudo evaluarse con las fuentes disponibles; rev'
    'ise la cobertura en la sección 8."].concat(depParts));\n    var meta = document.getElementById("cover'
    '-badges");\n    clear(meta);\n    function chip(parts, on, title) { meta.appendChild(rich(el("span", {'
    ' className: on ? "on" : null, title: title || null }), parts)); }\n    chip(["Generado ", [utc(snap.r'
    'eference_utc)]]);\n    chip(["Workspace ", [ws.name || "—"]]);\n    chip([[ws.cross_tenant ? "Entre te'
    'nants" : "Mismo tenant"], " · " + (ws.auth_mode || "—")], false, ws.cross_tenant ? (ws.sre_tenant_id'
    ' || "—") + " → " + (ws.target_tenant_id || "—") : ws.target_tenant_id);\n    chip(["Entorno ", [snap.'
    'environment || "—"]]);\n    chip([snap.provenance === "SIMULATED" ? "DATOS SIMULADOS" : "DATOS " + (s'
    'nap.provenance || "LIVE")], true);\n\n    var tone = "ok", title = counts.low ? "Sin desviaciones rele'
    'vantes" : "Sin desviaciones observadas";\n    if (!ev) { tone = "info"; title = "Sin evaluar"; }\n    '
    'else if (counts.critical) { tone = "crit"; title = "Acción requerida"; }\n    else if (counts.high ||'
    ' counts.medium) { tone = "warn"; title = "Requiere atención"; }\n    var lowCov = isNum(g.coverage_pe'
    'rcent) && g.coverage_percent < 50;\n    if (lowCov && tone === "ok") { tone = "warn"; title = "Cobert'
    'ura insuficiente"; }\n    var verdict = document.getElementById("verdict");\n    verdict.className = "'
    'signal " + tone;\n    clear(verdict);\n    verdict.appendChild(el("div", { className: "k", text: "Vere'
    'dicto" }));\n    verdict.appendChild(el("b", { text: title }));\n    verdict.appendChild(el("p", { tex'
    't: (ev ? (sevText || "Ningún hallazgo") + " · cobertura " + pct(g.coverage_percent) : "Ninguna compr'
    'obación evaluada") + (lowCov ? " · solo " + ev + " de " + (ev + (g.not_evaluated || 0)) + " evaluada'
    's" : "") }));\n\n    var dist = document.getElementById("severity-dist");\n    clear(dist);\n    dist.hi'
    'dden = !fails;\n    if (fails) {\n      dist.appendChild(rich(el("div", { className: "dist-head" }), ['
    '"Hallazgos por severidad", ""]));\n      dist.firstChild.appendChild(rich(el("span"), [[num(fails)], '
    '" de " + num(g.total || 0) + " comprobaciones no cumplen"]));\n      var track = el("div", { classNam'
    'e: "track", role: "img", "aria-label": sevText });\n      var legend = el("div", { className: "legend'
    '" });\n      SEVS.forEach(function (s) {\n        if (!counts[s]) { return; }\n        var seg = el("i"'
    ', { title: L.sev[s] + ": " + counts[s] });\n        seg.style.width = (100 * counts[s] / fails) + "%"'
    ';\n        seg.style.background = SEV_BAR[s];\n        track.appendChild(seg);\n        var key = el("i'
    '");\n        key.style.background = SEV_BAR[s];\n        legend.appendChild(el("span", null, [key, L.s'
    'ev[s] + " ", el("b", { text: String(counts[s]) })]));\n      });\n      dist.appendChild(track);\n     '
    ' dist.appendChild(legend);\n    }\n\n    var client = snap.client || { name: "CLIENTE", logo_data_uri: '
    '"", logo_alt: "Logotipo autorizado del cliente" };\n    var plaque = document.getElementById("brand-p'
    'laque");\n    clear(plaque);\n    var hasLogo = client.logo_data_uri && /^data:image\\/(png|jpeg);base6'
    '4,[A-Za-z0-9+/=]+$/.test(client.logo_data_uri);\n    if (hasLogo) { plaque.appendChild(el("img", { sr'
    'c: client.logo_data_uri, alt: client.logo_alt || client.name || "CLIENTE" })); }\n    else { plaque.a'
    'ppendChild(el("span", { className: "brand-placeholder", text: client.name || "CLIENTE" })); }\n    va'
    'r nameLabel = document.getElementById("client-name-label");\n    nameLabel.textContent = client.name '
    '|| "CLIENTE";\n    nameLabel.hidden = !hasLogo;\n  }\n\n  function renderKpis(snap, g, counts) {\n    var'
    ' sc = (snap.dependencies && snap.dependencies.summary_counts) || {}, fin = snap.finops || {};\n    va'
    'r fails = (snap.findings || []).length, ev = g.evaluated || 0;\n    var holder = document.getElementB'
    'yId("kpis");\n    clear(holder);\n    var sevText = SEVS.filter(function (s) { return counts[s]; }).ma'
    'p(function (s) { return counts[s] + " " + plural(counts[s], SEV_WORD[s][0], SEV_WORD[s][1]); }).join'
    '(" · ");\n    var sp = pctParts(g.score), cp = pctParts(g.coverage_percent);\n    var hasCost = isNum('
    'fin.actual_cost);\n    var win = fin.window ? day(fin.window.start).slice(5) + " → " + day(fin.window'
    '.end).slice(5) : null;\n    [\n      kpi(num(fails), "", "Hallazgos", sevText || "Sin desviaciones obs'
    'ervadas"),\n      kpi(sp[0], sp[1], "Índice local", ev ? "Sobre " + ev + " evaluadas" : "Sin comproba'
    'ciones evaluadas"),\n      kpi(cp[0], cp[1], "Cobertura evaluada", ev + " de " + (ev + (g.not_evaluat'
    'ed || 0)) + " aplicables"),\n      kpi(num(sc.edges_total || 0), "", "Relaciones", num(sc.edges_obser'
    'ved || 0) + " OBSERVED · " + num(sc.edges_inferred || 0) + " INFERRED"),\n      kpi(num(sc.unknowns_t'
    'otal || 0), "", "Puntos ciegos UNKNOWN", num(sc.broken_references_total || 0) + plural(sc.broken_ref'
    'erences_total || 0, " referencia rota", " referencias rotas")),\n      kpi(hasCost ? NF2.format(fin.a'
    'ctual_cost) : "—", hasCost ? (fin.currency || "") : "", "Coste observado", hasCost ? "ActualCost · "'
    ' + (win || "periodo acumulado") : "No evaluado")\n    ].forEach(function (k) { holder.appendChild(k);'
    ' });\n\n    var notices = document.getElementById("notices");\n    clear(notices);\n    if (snap.provena'
    'nce === "SIMULATED") {\n      notices.appendChild(el("div", { className: "sim", role: "note" }, [icon'
    '("alert"), el("span", { text: "Datos simulados: este informe procede de un conjunto sintético de pru'
    'ebas; las cifras no describen un workspace real." })]));\n    }\n    var gaps = (snap.sources || []).f'
    'ilter(function (s) { return s.status !== "complete" && s.status !== "not_applicable"; });\n    if (ga'
    'ps.length) {\n      var listed = gaps.slice(0, 6).map(function (s) { return s.id + " (" + lab(L.src, '
    's.status).toLowerCase() + ")"; }).join(", ") + (gaps.length > 6 ? " y " + (gaps.length - 6) + " más"'
    ' : "");\n      notices.appendChild(el("div", { className: "note", role: "note" }, [icon("info"), el("'
    'span", { text: gaps.length + plural(gaps.length, " fuente sin datos completos: ", " fuentes sin dato'
    's completos: ") + listed + ". Las comprobaciones que dependen de ellas figuran como No evaluado (sec'
    'ción 8)." })]));\n    }\n  }\n\n  function renderFacts(snap) {\n    var ws = snap.workspace || {};\n    va'
    'r facts = document.getElementById("cover-facts");\n    clear(facts);\n    function fact(label, main, s'
    'ub) {\n      var dd = el("dd");\n      if (main instanceof Node) { dd.appendChild(main); } else { dd.t'
    'extContent = main === null || main === undefined || main === "" ? "—" : String(main); }\n      if (su'
    'b instanceof Node) { var w = el("small"); w.appendChild(sub); dd.appendChild(w); } else if (sub) { d'
    'd.appendChild(el("small", { text: sub })); }\n      facts.appendChild(el("div", null, [el("dt", { tex'
    't: label }), dd]));\n    }\n    fact("Workspace", ws.name, brk(ws.workspace_url || "—"));\n    fact("Re'
    'curso ARM", armCell(ws.id, ws.name));\n    fact("Grupo administrado", brk(ws.managed_resource_group |'
    '| "—", ""));\n    fact("Región · SKU", (ws.region || "—") + " · " + (ws.sku_name || "—"), ws.sku_tier'
    ' ? "Nivel " + ws.sku_tier : null);\n    fact("Red", "Acceso público: " + access(ws.public_network_acc'
    'ess), "Sin IP pública (NPIP): " + yesNo(ws.enable_no_public_ip) + (ws.custom_virtual_network_id ? " '
    '· VNet inyectada" : ""));\n    fact("Autenticación", ws.auth_mode || "—", ws.cross_tenant ? "Entre te'
    'nants" : "Mismo tenant");\n    var tenants = el("span");\n    if (ws.cross_tenant) { tenants.appendChi'
    'ld(mono(ws.sre_tenant_id)); tenants.appendChild(el("br")); tenants.appendChild(mono("→ " + (ws.targe'
    't_tenant_id || "—"))); }\n    else { tenants.appendChild(mono(ws.target_tenant_id)); }\n    fact(ws.cr'
    'oss_tenant ? "Tenant SRE → tenant destino" : "Tenant", tenants);\n    fact("Unity Catalog por defecto'
    '", ws.default_catalog_name || "—", ws.default_catalog_type || null);\n  }\n\n  function renderExecutive'
    '(snap, g) {\n    var msgList = document.getElementById("executive-messages");\n    clear(msgList);\n   '
    ' (snap.executive_messages || []).forEach(function (m) { msgList.appendChild(el("li", { text: m })); '
    '});\n    var total = Math.max(1, g.total || 0);\n    var status = document.getElementById("check-statu'
    's");\n    clear(status);\n    [\n      ["passed", "Configuración observada conforme con la regla local.'
    '", "var(--ok-bar)"],\n      ["failed", "Desviación o referencia rota observada.", "var(--crit-bar)"],'
    '\n      ["not_evaluated", "Fuente no disponible, requisito no confirmado o alcance sin cómputo.", "va'
    'r(--info-bar)"],\n      ["not_applicable", "Excluido del denominador por tipo de objeto o requisito f'
    'also.", "var(--line2)"]\n    ].forEach(function (r) {\n      var n = g[r[0]] || 0;\n      status.append'
    'Child(barRow(el("span", { className: "st st-" + r[0], text: L.status[r[0]] }), r[1], 100 * n / total'
    ', num(n), NF.format(100 * n / total) + "\\u00a0%", r[2], !n));\n    });\n    scoreBars("area-scores", s'
    'nap.scores && snap.scores.areas, L.area);\n    scoreBars("pillar-scores", snap.scores && snap.scores.'
    'pillars, L.pillar);\n    var list = document.getElementById("priority-findings");\n    clear(list);\n  '
    '  var priorities = (snap.findings || []).filter(function (f) { return f.severity === "critical" || f'
    '.severity === "high"; })\n      .sort(function (a, b) { return SEVS.indexOf(a.severity) - SEVS.indexO'
    'f(b.severity); });\n    if (!priorities.length) { list.appendChild(el("li", null, [emptyState("Sin ha'
    'llazgos críticos ni de severidad alta en las comprobaciones evaluadas.")])); }\n    priorities.forEac'
    'h(function (f) {\n      list.appendChild(el("li", null, [\n        sevPill(f.severity, f.severity_labe'
    'l),\n        el("div", { className: "pt", text: f.title }),\n        el("div", { className: "pm", text'
    ': f.rule_id + " · " + lab(L.level, f.level) + (f.workload_name ? ": " + f.workload_name : "") + " — '
    '" + (f.business_impact || f.reason || "") })\n      ]));\n    });\n  }\n\n  function renderInventory(snap'
    ') {\n    var inv = snap.inventory || {};\n    function count(id, n, word) { document.getElementById(id'
    ').textContent = n + " " + word; }\n    var computeRows = [].concat(inv.clusters || [], inv.instance_p'
    'ools || [], inv.cluster_policies || [], inv.global_init_scripts || []);\n    count("inv-compute-count'
    '", computeRows.length, plural(computeRows.length, "objeto", "objetos"));\n    renderTable(document.ge'
    'tElementById("inv-compute-table"),\n      ["Tipo", "Nombre / ID", "Estado / runtime", "Acceso / autot'
    'erminación", "Política / pool"],\n      computeRows.map(function (r) {\n        return [\n          { v'
    ': kindLabel(r.kind) },\n          { v: stack(r.name || "—", mono(r.id)), s: r.name },\n          { v: '
    'stack(r.state || "—", r.spark_version ? mono(r.spark_version) : null), s: r.state },\n          (r.da'
    'ta_security_mode || "—") + (r.autotermination_minutes !== undefined && r.autotermination_minutes !=='
    ' null ? " · " + r.autotermination_minutes + " min" : ""),\n          { v: stack(r.policy_id ? mono(r.'
    'policy_id) : "—", r.instance_pool_id ? mono("Pool: " + r.instance_pool_id) : null) }\n        ];\n    '
    '  }), { sortable: true }\n    );\n    var orchRows = [];\n    (inv.jobs || []).forEach(function (j) {\n '
    '     var tasks = el("div", { className: "chips" });\n      (j.tasks || []).forEach(function (t) { tas'
    'ks.appendChild(el("span", { text: t.task_key })); });\n      orchRows.push([{ v: kindLabel("Job") }, '
    '{ v: stack(j.name, mono(j.id)), s: j.name }, j.scheduled ? "Programado" : "Sin programación",\n      '
    '  { v: stack(j.run_as_service_principal ? "Service principal" : "Usuario (sin SP)", j.run_as_service'
    '_principal ? mono(j.run_as_service_principal) : null) },\n        { v: (j.tasks || []).length ? tasks'
    ' : "—" }]);\n    });\n    (inv.pipelines || []).forEach(function (p) {\n      orchRows.push([{ v: kindL'
    'abel("dlt_pipeline") }, { v: stack(p.name, mono(p.id)), s: p.name }, p.state || "—", "Serverless: " '
    '+ yesNo(p.serverless),\n        "Catálogo " + (p.catalog || "hive_metastore") + " · destino " + (p.ta'
    'rget || "—")]);\n    });\n    (inv.sql_warehouses || []).forEach(function (w) {\n      orchRows.push([{'
    ' v: kindLabel("sql_warehouse") }, { v: stack(w.name, mono(w.id)), s: w.name }, (w.state || "—") + " '
    '· " + (w.cluster_size || "—"),\n        "Serverless: " + yesNo(w.enable_serverless_compute) + " · aut'
    'o-stop " + (isNum(w.auto_stop_mins) ? w.auto_stop_mins + " min" : "—"), w.warehouse_type || "—"]);\n '
    '   });\n    count("inv-orchestration-count", orchRows.length, plural(orchRows.length, "objeto", "obje'
    'tos"));\n    renderTable(document.getElementById("inv-orchestration-table"),\n      ["Tipo", "Nombre /'
    ' ID", "Estado / programación", "Identidad / modo", "Tareas / destino"], orchRows, { sortable: true }'
    ');\n    var ucRows = [];\n    if (inv.uc_metastore) {\n      ucRows.push([L.kind.uc_metastore, { v: brk'
    '(inv.uc_metastore.name, "") }, { v: mono(inv.uc_metastore.id) }, { v: brk(inv.uc_metastore.storage_r'
    'oot || "—") }, "Región " + (inv.uc_metastore.region || "—")]);\n    }\n    (inv.uc_catalogs || []).for'
    'Each(function (c) { ucRows.push([L.kind.uc_catalog, { v: brk(c.name, "") }, c.catalog_type || "—", {'
    ' v: brk(c.storage_root || "—") }, "Aislamiento " + (c.isolation_mode || "—")]); });\n    (inv.uc_sche'
    'mas || []).forEach(function (s) { ucRows.push([L.kind.uc_schema, { v: brk(s.full_name, "") }, s.cata'
    'log_name, { v: brk(s.storage_root || "—") }, "—"]); });\n    (inv.uc_storage_credentials || []).forEa'
    'ch(function (cr) { ucRows.push([L.kind.uc_storage_credential, { v: brk(cr.name, "") }, cr.uses_manag'
    'ed_identity ? "Managed Identity" : "Service Principal", { v: cr.access_connector_id ? armCell(cr.acc'
    'ess_connector_id) : "—" }, "Solo lectura: " + yesNo(cr.read_only)]); });\n    (inv.uc_external_locati'
    'ons || []).forEach(function (loc) { ucRows.push([L.kind.uc_external_location, { v: brk(loc.name, "")'
    ' }, "Credencial " + (loc.credential_name || "—"), { v: brk(loc.url || "—") }, "Solo lectura: " + yes'
    'No(loc.read_only)]); });\n    (inv.uc_connections || []).forEach(function (cn) { ucRows.push([L.kind.'
    'uc_connection, { v: brk(cn.name, "") }, cn.connection_type || "—", { v: brk(cn.host || "—") }, "Cred'
    'encial " + (cn.credential_type || "—")]); });\n    (inv.secret_scopes || []).forEach(function (sc) { '
    'ucRows.push([L.kind.secret_scope, { v: brk(sc.name, "") }, sc.backend_type || "—", { v: sc.keyvault_'
    'resource_id ? armCell(sc.keyvault_resource_id) : brk(sc.keyvault_dns_name || "—") }, "Valores nunca '
    'leídos"]); });\n    count("inv-uc-count", ucRows.length, plural(ucRows.length, "objeto", "objetos"));'
    '\n    renderTable(document.getElementById("inv-uc-table"), ["Objeto", "Nombre", "Tipo / credencial", '
    '{ t: "URI / recurso", c: "w" }, "Detalle"], ucRows, { sortable: true });\n    var resRows = [];\n    ('
    'inv.related_resources || []).forEach(function (r) {\n      var a = r.association || {};\n      resRows'
    '.push([{ v: kindLabel(r.resource_kind) }, { v: armCell(r.id, r.name), s: r.name },\n        { v: stac'
    'k(a.type || "—", brk([a.source_id, a.field].filter(Boolean).join(" · "))) }, { v: evidenceCell(r.con'
    'figuration) }]);\n    });\n    (inv.outbound_endpoints || []).forEach(function (o) {\n      var chips ='
    ' el("div", { className: "chips" });\n      (o.endpoints || []).forEach(function (ep) {\n        var po'
    'rts = (ep.details || []).map(function (d) { return d.port; }).filter(Boolean).join(", ");\n        ch'
    'ips.appendChild(el("span", { text: (ep.domain_name || ep.domainName || "—") + (ports ? ":" + ports :'
    ' "") }));\n      });\n      resRows.push([{ v: kindLabel("OutboundDependency") }, { v: stack(o.categor'
    'y || "—", null), s: o.category }, { v: stack("outboundNetworkDependenciesEndpoints", null) }, { v: c'
    'hips.firstChild ? chips : "—" }]);\n    });\n    count("inv-resources-count", resRows.length, plural(r'
    'esRows.length, "recurso o endpoint", "recursos y endpoints"));\n    renderTable(document.getElementBy'
    'Id("inv-resources-table"), ["Tipo", "Recurso", "Asociación", { t: "Configuración observada", c: "w",'
    ' s: false }], resRows, { sortable: true });\n  }\n\n  function renderFinops(snap) {\n    var fin = snap.'
    'finops || {};\n    var amount = document.getElementById("finops-actual-cost");\n    clear(amount);\n   '
    ' if (isNum(fin.actual_cost)) { amount.className = "stat"; amount.appendChild(document.createTextNode'
    '(NF2.format(fin.actual_cost) + " ")); amount.appendChild(el("small", { text: fin.currency || "" }));'
    ' }\n    else { amount.className = "stat na"; amount.textContent = "No evaluado / Sin alcance de factu'
    'ración"; }\n    document.getElementById("finops-cost-window").textContent = fin.window ? "Ventana " +'
    ' day(fin.window.start) + " → " + day(fin.window.end) + " · fuente azure_cost " + (fin.cost_source_co'
    'mplete ? "completa" : "incompleta") : "Sin ventana de coste observada.";\n    var notes = document.ge'
    'tElementById("finops-cost-note");\n    clear(notes);\n    (fin.notes || []).forEach(function (n) { not'
    'es.appendChild(el("li", { text: n })); });\n    function unitText(c) {\n      if (c.unit === "minutes"'
    ') { return "min"; }\n      if (c.unit === "tasks_on_all_purpose") { return c.value === 1 ? "tarea en '
    'All-Purpose" : "tareas en All-Purpose"; }\n      return c.unit || "";\n    }\n    renderTable(document.'
    'getElementById("finops-candidates-table"),\n      ["Carga / objeto", "Candidato", { t: "Valor observa'
    'do", c: "n" }, "Base", { t: "Recomendación", c: "w" }],\n      (fin.candidates || []).map(function (c'
    ') {\n        return [\n          { v: stack(c.workload_name || "—", mono(c.id)), s: c.workload_name },'
    '\n          c.title,\n          { v: (c.value === "disabled" ? "desactivado" : num(c.value)) + " " + u'
    'nitText(c), s: isNum(c.value) ? c.value : -1 },\n          c.basis, c.recommendation\n        ];\n     '
    ' }), { sortable: true, empty: "Sin candidatos de eficiencia en la configuración observada." }\n    );'
    '\n    renderTable(document.getElementById("finops-cost-table"),\n      ["Recurso", "Fecha", { t: "Impo'
    'rte", c: "n" }, "Moneda", "Base"],\n      (fin.cost_rows || []).map(function (r) {\n        return [{ '
    'v: armCell(r.resource_id) }, r.usage_date ? day(r.usage_date) : "Periodo acumulado", { v: isNum(r.am'
    'ount) ? NF2.format(r.amount) : num(r.amount), s: r.amount }, r.currency, r.basis];\n      }), { empty'
    ': "Sin filas de facturación observadas en el alcance aprobado." }\n    );\n  }\n\n  function renderActio'
    'ns(snap) {\n    var holder = document.getElementById("actions-plan");\n    clear(holder);\n    var acti'
    'ons = snap.actions || [];\n    if (!actions.length) { holder.appendChild(el("div", { className: "card'
    '" }, [emptyState("Sin acciones: ninguna comprobación evaluada requiere cambios.")])); return; }\n    '
    '[["quick_win", "Quick-win", "Menos de 1 semana"], ["short_term", "Corto plazo", "1-3 meses"], ["medi'
    'um_term", "Medio plazo", "Planificación posterior"]].forEach(function (h) {\n      var items = action'
    's.filter(function (a) { return a.horizon === h[0]; });\n      var card = el("div", { className: "card'
    '" }, [el("h3", { text: h[1] }), el("p", { className: "sub", text: h[2] + " · " + items.length + plur'
    'al(items.length, " acción", " acciones") })]);\n      if (!items.length) { card.appendChild(el("p", {'
    ' className: "muted", text: "Sin acciones en este horizonte." })); }\n      else {\n        var ol = el'
    '("ol", { className: "steps" });\n        items.forEach(function (a, i) {\n          var link = safeLea'
    'rnUrl(a.learn_url);\n          var meta = el("div", { className: "sm" }, [sevPill(a.severity, a.sever'
    'ity_label), el("span", { text: a.rule_id + " · " + lab(L.effort, a.effort_label) })]);\n          if '
    '(link) { meta.appendChild(extLink(link, "Documentación")); }\n          ol.appendChild(el("li", null,'
    ' [\n            el("span", { className: "no", text: String(i + 1) }),\n            el("div", { classNa'
    'me: "sx" }, [el("b", { text: a.title }), el("div", { className: "muted", text: lab(L.level, a.level)'
    ' + ": " + (a.workload_name || a.resource_id || "—") }), el("p", { text: a.recommendation }), meta])\n'
    '          ]));\n        });\n        card.appendChild(ol);\n      }\n      holder.appendChild(card);\n   '
    ' });\n  }\n\n  function renderSources(snap) {\n    var sources = snap.sources || [];\n    var byStatus = '
    '{};\n    sources.forEach(function (s) { byStatus[s.status] = (byStatus[s.status] || 0) + 1; });\n    v'
    'ar complete = byStatus.complete || 0;\n    document.getElementById("sources-summary").textContent = c'
    'omplete + " de " + sources.length + plural(sources.length, " fuente completa", " fuentes completas")'
    ';\n    var bars = document.getElementById("sources-bars");\n    clear(bars);\n    Object.keys(L.src).fo'
    'rEach(function (k) {\n      if (!byStatus[k]) { return; }\n      bars.appendChild(barRow(srcPill(k), n'
    'ull, 100 * byStatus[k] / Math.max(1, sources.length), num(byStatus[k]), null, SRC_COLOR[k], false));'
    '\n    });\n    renderTable(document.getElementById("sources-table"),\n      ["Fuente", "Plano", "Estado'
    '", { t: "Páginas", c: "n" }, { t: "Registros", c: "n" }, "Hora UTC", { t: "Nota / errores", c: "w" }'
    '],\n      sources.map(function (s) {\n        var note = el("div");\n        if (s.note) { note.appendC'
    'hild(el("span", { text: s.note })); }\n        (s.errors || []).forEach(function (e) {\n          note'
    '.appendChild(el("div", { className: "muted", text: [e.http_status ? "HTTP " + e.http_status : null, '
    'e.code, e.message].filter(Boolean).join(" · ") }));\n        });\n        if (!note.firstChild) { note'
    '.textContent = "—"; }\n        return [{ v: mono(s.id), s: s.id }, { v: sourcePlane(s.id), c: "nw" },'
    ' { v: srcPill(s.status), s: s.status }, { v: num(s.pages), s: s.pages }, { v: num(s.records), s: s.r'
    'ecords }, { v: utc(s.time), c: "nw" }, { v: note }];\n      }), { sortable: true, page: 12 }\n    );\n '
    '   var m = snap.methodology || {}, cat = m.catalogSnapshot || {}, cov = m.catalog_coverage || {};\n  '
    '  var dl = document.getElementById("method-notes");\n    clear(dl);\n    function row(term, node) { dl'
    '.appendChild(el("dt", { text: term })); var dd = el("dd"); dd.appendChild(node instanceof Node ? nod'
    'e : document.createTextNode(node)); dl.appendChild(dd); }\n    row("Índice local", m.score_formula ||'
    ' "—");\n    row("Cobertura", m.coverage_formula || "—");\n    var catNode = el("span", { text: (cat.na'
    'me || "Catálogo local") + " · " + (cov.local_rules || 0) + " reglas locales · recuperado " + (cat.re'
    'trieved_at || "—") + " " });\n    [[cat.service_guide_url, "Guía de servicio"], [cat.lakehouse_waf_ur'
    'l, "Lakehouse WAF"], [m.assessment_url, "Assessment oficial"]].forEach(function (l) {\n      var u = '
    'safeLearnUrl(l[0]);\n      if (u) { catNode.appendChild(document.createTextNode(" ")); catNode.append'
    'Child(extLink(u, l[1])); }\n    });\n    row("Catálogo de reglas", catNode);\n    var interp = el("ul")'
    ';\n    (m.interpretation || []).forEach(function (t) { interp.appendChild(el("li", { text: t })); });'
    '\n    row("Interpretación", interp.firstChild ? interp : "—");\n    var limList = document.getElementB'
    'yId("methodology-limitations");\n    clear(limList);\n    (m.limitations || []).forEach(function (l) {'
    ' limList.appendChild(el("li", { text: l })); });\n  }\n\n  function cssString(s) { return String(s).rep'
    'lace(/\\\\/g, "\\\\\\\\").replace(/"/g, \'\\\\"\').replace(/[\\r\\n]+/g, " ").replace(/</g, "\\\\3c "); }\n  functi'
    'on renderFooter(snap) {\n    var ws = snap.workspace || {}, client = (snap.client && snap.client.name'
    ') || "CLIENTE";\n    var when = utc(snap.reference_utc);\n    document.getElementById("report-footer")'
    '.textContent = "Generado por Azure SRE Agent · Solo lectura · generate-databricks-dependency-report '
    '· " + when + " · " + client;\n    document.title = (ws.name ? ws.name + " · " : "") + "Revisión Azure'
    ' Databricks | Mapa de dependencias y configuración";\n    var style = document.getElementById("print-'
    'page-style");\n    if (!style) { style = el("style", { id: "print-page-style" }); document.head.appen'
    'dChild(style); }\n    var foot = "Revisión Azure Databricks · " + (ws.name || "—") + " · " + when + ('
    'snap.provenance === "SIMULATED" ? " · DATOS SIMULADOS" : "");\n    style.textContent = \'@page { @bott'
    'om-left { content: "\' + cssString(foot) + \'"; font: 8pt "Segoe UI", sans-serif; color: #667085; } @b'
    'ottom-right { content: "Página " counter(page) " de " counter(pages); font: 8pt "Segoe UI", sans-ser'
    "if; color: #667085; } }';\n  }\n\n  function renderSnapshot(snap) {\n    currentSnap = snap;\n    documen"
    't.getElementById("workspace-error-view").hidden = true;\n    document.getElementById("report-body").h'
    'idden = false;\n    var g = (snap.scores && snap.scores.global) || {};\n    var counts = { critical: 0'
    ', high: 0, medium: 0, low: 0 };\n    (snap.findings || []).forEach(function (f) { if (counts[f.severi'
    'ty] !== undefined) { counts[f.severity]++; } });\n    var sc = (snap.dependencies && snap.dependencie'
    's.summary_counts) || {};\n    renderHero(snap, g, counts);\n    renderKpis(snap, g, counts);\n    rende'
    'rFacts(snap);\n    renderExecutive(snap, g);\n    var sum = document.getElementById("dep-class-summary'
    '");\n    clear(sum);\n    [["OBSERVED", sc.edges_observed, " relaciones"], ["INFERRED", sc.edges_infer'
    'red, " relaciones"], ["UNKNOWN", sc.unknowns_total, " puntos ciegos"]].forEach(function (c) {\n      '
    'sum.appendChild(pill("cls-" + c[0], c[0] + " · " + num(c[1] || 0) + c[2]));\n    });\n    sum.appendCh'
    'ild(pill("sev-info", num(sc.broken_references_total || 0) + plural(sc.broken_references_total || 0, '
    '" referencia rota", " referencias rotas")));\n    document.getElementById("dep-graph-note").textConte'
    'nt = num(sc.nodes_total || 0) + " nodos · " + num(sc.edges_total || 0) + " relaciones en total";\n   '
    ' renderInventory(snap);\n    renderFinops(snap);\n    renderActions(snap);\n    renderSources(snap);\n  '
    '  renderFooter(snap);\n    applyDependencyFilters();\n    applyFindingFilters();\n    renderReferenceAr'
    'chitecture();\n  }\n\n  if (isMulti) {\n    var selWrap = document.getElementById("workspace-selector-wr'
    'ap");\n    var sel = document.getElementById("workspace-selector");\n    var runs = rootData.workspace'
    '_runs || [];\n    var agg = rootData.aggregate || {};\n    document.getElementById("multi-overview").h'
    'idden = false;\n    selWrap.hidden = false;\n    rich(document.getElementById("multi-summary"), ["Vist'
    'a multi-workspace · ", [num(runs.length)], plural(runs.length, " workspace seleccionado", " workspac'
    'es seleccionados") + " · ", [num(agg.findings_total || 0)], " hallazgos · ",\n      [num((agg.depende'
    'ncy_counts && agg.dependency_counts.nodes_total) || 0)], " nodos de dependencia · ", [num(agg.failed'
    '_workspace_count || 0)], plural(agg.failed_workspace_count || 0, " workspace con error", " workspace'
    's con error")]);\n    runs.forEach(function (r, idx) {\n      sel.appendChild(el("option", { value: St'
    'ring(idx), text: r.workspace_name + " (" + r.status + ")" }));\n    });\n    var selectRun = function '
    '(idx) {\n      var run = runs[idx];\n      if (!run) { return; }\n      if (run.snapshot) {\n        ren'
    'derSnapshot(run.snapshot);\n      } else {\n        currentSnap = null;\n        document.getElementByI'
    'd("report-body").hidden = true;\n        var errView = document.getElementById("workspace-error-view"'
    ');\n        errView.hidden = false;\n        clear(errView);\n        var err = run.error || {};\n      '
    '  errView.appendChild(el("h2", { text: "Recolección fallida para el workspace " + run.workspace_name'
    ' }));\n        errView.appendChild(el("p", { text: "No se sustituyen datos vacíos ni puntuaciones de '
    'otro workspace. Seleccione otro workspace o corrija el acceso y repita la revisión." }));\n        va'
    'r dl = el("dl", { className: "dl2" });\n        [["Código", err.code], ["Fuente", err.source_id], ["H'
    'TTP", err.http_status], ["Mensaje", err.message], ["Hora UTC", utc(run.reference_utc)]].forEach(func'
    'tion (p) {\n          dl.appendChild(el("dt", { text: p[0] }));\n          dl.appendChild(el("dd", { t'
    'ext: p[1] === null || p[1] === undefined || p[1] === "" ? "—" : String(p[1]) }));\n        });\n      '
    '  errView.appendChild(dl);\n      }\n    };\n    sel.addEventListener("change", function () { selectRun'
    '(Number(sel.value)); });\n    selectRun(0);\n  } else {\n    renderSnapshot(rootData);\n  }\n\n  var navLi'
    'nks = [].slice.call(document.querySelectorAll(".bar-nav a"));\n  if ("IntersectionObserver" in window'
    ' && navLinks.length) {\n    var spy = new IntersectionObserver(function (entries) {\n      entries.for'
    'Each(function (en) {\n        if (!en.isIntersecting) { return; }\n        var id = en.target.id;\n    '
    '    navLinks.forEach(function (a) { if (a.getAttribute("href") === "#" + id) { a.setAttribute("aria-'
    'current", "true"); } else { a.removeAttribute("aria-current"); } });\n      });\n    }, { rootMargin: '
    '"-80px 0px -65% 0px" });\n    ["sec-cover", "sec-identity", "sec-executive", "sec-dependencies", "sec'
    '-inventory", "sec-findings", "sec-finops", "sec-actions", "sec-sources"].forEach(function (id) {\n   '
    '   var node = document.getElementById(id);\n      if (node) { spy.observe(node); }\n    });\n  }\n})();\n'
    '</script>\n</body>\n</html>\n'
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
        ("operation", operation, ("report", "query", "list_workspaces")),
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
    if operation in ("report", "list_workspaces") and (view != "summary" or filters or limit != 25 or offset != 0):
        raise EvidenceError("invalid_combination", "report/list_workspaces cannot be narrowed by query filters or paging.", "parameters")
    if operation == "list_workspaces" and (workspace_name or workspace_names):
        raise EvidenceError("invalid_combination", "list_workspaces lists the complete fixed roster; do not select a workspace.", "parameters")
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
    def __init__(self, identity, origin=ARM_ORIGIN, token_kind="arm"):
        self.identity, self.origin, self.token_kind = identity, origin, token_kind
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
        if method == "POST" and not parsed.path.lower().endswith("/providers/microsoft.costmanagement/query"):
            raise EvidenceError("unsafe_method", "This POST is not an enumerated read-only operation.", source)
        payload = None if body is None else json.dumps(body, allow_nan=False).encode("utf-8")
        for attempt in range(3):
            bearer = self._bearer()
            self.identity._guard_budget()
            request = Request(url, data=payload, method=method, headers={
                "Authorization": "Bearer " + bearer,
                "Accept": "application/json",
                "Content-Type": "application/json",
            })
            try:
                with self.opener.open(request, timeout=30) as response:
                    if response.status == 204 and allow_empty:
                        return {}
                    if response.status != 200:
                        raise EvidenceError("http_error", "Read returned HTTP " + str(response.status) + ".", source, response.status)
                    raw = response.read(HTTP_BYTES + 1)
                    if len(raw) > HTTP_BYTES:
                        raise EvidenceError("response_cap", "Source response exceeded the disclosed byte safety bound.", source)
            except HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                    retry = exc.headers.get("Retry-After", "") if exc.headers else ""
                    time.sleep(min(int(retry), 5) if re.fullmatch(r"[0-9]{1,4}", retry) else attempt + 1)
                    continue
                raise EvidenceError(
                    "access_denied" if exc.code in (401, 403) else "http_error",
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
    resource_id = arm_id(raw.get("id"), SUBSCRIPTION_ID)
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
    ac_id = arm_id(access_connector.get("id"), SUBSCRIPTION_ID) if access_connector.get("id") else None
    ac_uami = arm_id(access_connector.get("userAssignedIdentityId"), SUBSCRIPTION_ID) if access_connector.get("userAssignedIdentityId") else None
    custom_vnet_id = param_val(params, "customVirtualNetworkId", "str", source_id)
    if custom_vnet_id:
        custom_vnet_id = arm_id(custom_vnet_id, SUBSCRIPTION_ID)
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
        "subscription_id": SUBSCRIPTION_ID,
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
    resource_id = arm_id(raw.get("id"), SUBSCRIPTION_ID)
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
            arm_id(k, SUBSCRIPTION_ID) for k in obj(identity_block.get("userAssignedIdentities") or {}, source_id)
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
        row["subnet_ids"] = [arm_id(s.get("id"), SUBSCRIPTION_ID) for s in array(props.get("subnets", []), source_id) if s.get("id")]
    elif kind == "microsoft.network/virtualnetworks/subnets":
        row["address_prefix"] = text(props.get("addressPrefix"), source_id, 128)
        row["nsg_id"] = arm_id(pick(props, "networkSecurityGroup", "id"), SUBSCRIPTION_ID) if pick(props, "networkSecurityGroup", "id") else None
        row["route_table_id"] = arm_id(pick(props, "routeTable", "id"), SUBSCRIPTION_ID) if pick(props, "routeTable", "id") else None
        row["nat_gateway_id"] = arm_id(pick(props, "natGateway", "id"), SUBSCRIPTION_ID) if pick(props, "natGateway", "id") else None
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
        row["public_ip_ids"] = [arm_id(ip.get("id"), SUBSCRIPTION_ID) for ip in array(props.get("publicIpAddresses", []), source_id) if ip.get("id")]
    elif kind == "microsoft.network/publicipaddresses":
        row["configuration"]["ipAddress"] = text(props.get("ipAddress"), source_id, 128)
        row["configuration"]["publicIPAllocationMethod"] = text(props.get("publicIPAllocationMethod"), source_id, 64)
    elif kind == "microsoft.network/privateendpoints":
        row["subnet_id"] = arm_id(pick(props, "subnet", "id"), SUBSCRIPTION_ID) if pick(props, "subnet", "id") else None
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


def referenced_resource_ids(row):
    refs = []
    for field in ("subnet_ids", "public_ip_ids", "user_assigned_identities"):
        refs.extend((val, field) for val in row.get(field, []) if val)
    for field in ("nsg_id", "route_table_id", "nat_gateway_id", "subnet_id"):
        if row.get(field):
            refs.append((row[field], field))
    if row.get("resource_kind") == "microsoft.network/virtualnetworks/subnets":
        refs.append((re.split(r"/subnets/", row["id"], flags=re.IGNORECASE)[0], "parent_virtual_network_id"))
    for val, field in refs:
        val = arm_id(val, SUBSCRIPTION_ID)
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
    return {
        "id": pol_id,
        "policy_id": pol_id,
        "name": name,
        "workload_name": name,
        "kind": "ClusterPolicy",
        "policy_family_id": text(raw.get("policy_family_id"), source_id, 128),
        "is_default": boolean(raw.get("is_default"), source_id),
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
            job_clusters.append({
                "job_cluster_key": key,
                "spark_version": text(new_cluster.get("spark_version"), source_id, 128),
                "node_type_id": text(new_cluster.get("node_type_id"), source_id, 128),
                "policy_id": text(new_cluster.get("policy_id"), source_id, 128),
                "instance_pool_id": text(new_cluster.get("instance_pool_id"), source_id, 128),
                "data_security_mode": text(new_cluster.get("data_security_mode"), source_id, 64),
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
            for sid in ("dbx_workspace_conf", "dbx_clusters", "dbx_instance_pools", "dbx_cluster_policies", "dbx_jobs", "dbx_pipelines", "dbx_sql_warehouses", "dbx_secret_scopes", "dbx_init_scripts"):
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
            "Runtime table/column lineage (system.access.table_lineage, system.access.column_lineage) and DBU billing (system.billing.usage) require SQL Warehouse query execution and are never auto-started by this control-plane collector.",
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
        for child_id, field in referenced_resource_ids(res):
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
        return outcome(
            "not_evaluated",
            "ActualCost de ARM refleja facturación por ResourceId de Azure; la atribución interna de DBU por job/clúster/usuario requiere system.billing.usage y políticas de etiquetado.",
            {"cost_rows_collected": len(raw.get("cost_rows", []))},
            ["azure_cost"],
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
            "ActualCost uses observed approved ARM ResourceIds and actual billing currency; it does not split DBU spend by job, notebook or user.",
            "System table system.billing.usage is not queried automatically so no SQL Warehouse is started or billed by this review.",
            "No fabricated DBU savings, reservation discounts or rightsizing returns are computed.",
        ],
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
    return {
        "schema_version": "1.0",
        "provenance": provenance,
        "environment": environment,
        "reference_utc": reference,
        "client": {"name": CLIENT_NAME, "logo_data_uri": CLIENT_LOGO_DATA_URI, "logo_alt": CLIENT_LOGO_ALT},
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
        "actions": actions_for(findings),
        "executive_messages": [
            str(dep_counts["nodes_total"]) + " nodos en el mapa de dependencias (" + str(dep_counts["edges_observed"]) + " relaciones OBSERVED, " + str(dep_counts["edges_inferred"]) + " INFERRED explícitas y " + str(dep_counts["unknowns_total"]) + " puntos ciegos UNKNOWN).",
            str(len(findings)) + " hallazgos de configuración y dependencias observados (" + str(critical) + " críticos reales, sin rellenar un Top 5 ficticio).",
            str(global_score["evaluated"]) + " de " + str(global_score["evaluated"] + global_score["not_evaluated"]) + " comprobaciones aplicables evaluadas; la cobertura se muestra junto al índice local.",
            str(dep_counts["broken_references_total"]) + " referencias rotas detectadas entre tareas de Jobs, clústeres, pools, políticas, pipelines, warehouses y credenciales.",
            str(len(blind_spots)) + " fuentes con estado parcial, denegado o no configurado; ahorro estimado no calculado y ningún clúster o SQL Warehouse fue iniciado.",
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
    return {
        "schema_version": "databricks-dep-multi-workspace-v1",
        "reference_utc": reference,
        "provenance": next(iter(provenances)) if provenances else "LIVE",
        "client": {"name": CLIENT_NAME, "logo_data_uri": CLIENT_LOGO_DATA_URI, "logo_alt": CLIENT_LOGO_ALT},
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
    }


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
        "operation": "report",
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
