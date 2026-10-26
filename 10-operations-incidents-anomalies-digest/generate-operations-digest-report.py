"""Read-only Azure Operations, Incidents, Anomalies, and Recommended Actions Digest engine. Build standalone tool with build_tool.py."""

import base64
import binascii
import copy
import csv
import hashlib
import io
import json
import math
import os
import re
import ssl
import statistics
import tempfile
import time
import warnings
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit
from urllib.request import HTTPRedirectHandler, HTTPSHandler, Request, build_opener
from uuid import UUID, uuid4


SUBSCRIPTION_ID = "<YOUR_SUBSCRIPTION_ID>"
MANAGED_IDENTITY_CLIENT_ID = "<YOUR_MANAGED_IDENTITY_CLIENT_ID>"
APPROVED_LOG_WORKSPACES = [
    {
        "name": "<WORKSPACE_NAME>",
        "customer_id": "<WORKSPACE_GUID>",
        "resource_group": "<RESOURCE_GROUP>",
    }
]
CLIENT_NAME = "CLIENTE"
# Here goes the customer's logo, privately configured as a validated PNG/JPEG
# data URI. Keep generic Git source empty. Use adjacent strings <10K per line.
CLIENT_LOGO_DATA_URI = ""
CLIENT_LOGO_ALT = "Logotipo autorizado del cliente"
OUTPUT_DIRECTORY = "operations-digest-reports"

ARM_ORIGIN = "https://management.azure.com"
LOGS_ORIGIN = "https://api.loganalytics.io"
ARM_TOKEN_AUDIENCES = (
    "https://management.azure.com",
    "https://management.core.windows.net",
)
LOGS_TOKEN_AUDIENCES = (
    "https://api.loganalytics.io",
    "https://api.loganalytics.azure.com",
)
ARG_API_VERSION = "2022-10-01"
RESOURCE_HEALTH_API_VERSION = "2022-10-01"
ADVISOR_API_VERSION = "2023-01-01"

TRANSPORT_BYTES = 3500
ARTIFACT_BYTES = 4_800_000
HTTP_BYTES = 12_000_000
MAX_PAGES = 25
MAX_ROWS = 10_000
MAX_WORKSPACES = 10
MAX_COLLECTION_SECONDS = 180
MAX_HTTP_ATTEMPTS = 200
MAX_LOGO_BYTES = 100_000
MAX_LOGO_DIMENSION = 2048

OPERATIONS = ("report", "query")
PERIODS = ("previous_month", "last_30d", "last_7d", "last_24h")
VIEWS = ("summary", "incidents", "anomalies", "actions", "resources", "advisor", "coverage")
CATEGORIES = (
    "all",
    "native_alert",
    "service_health",
    "extension_failure",
    "connectivity_posture",
    "telemetry_anomaly",
    "advisor_recommendation",
)
SEVERITIES = ("all", "critical", "high", "medium", "low")
HORIZONS = ("immediate_24h", "short_term_7d", "monthly_cycle")
SOURCE_STATUSES = ("complete", "partial", "denied", "error", "not_configured")

ESTATE_RESOURCE_TYPES = (
    "microsoft.compute/virtualmachines",
    "microsoft.compute/virtualmachinescalesets",
    "microsoft.hybridcompute/machines",
    "microsoft.kubernetes/connectedclusters",
    "microsoft.containerservice/managedclusters",
    "microsoft.app/containerapps",
    "microsoft.web/sites",
    "microsoft.web/serverfarms",
    "microsoft.storage/storageaccounts",
    "microsoft.keyvault/vaults",
    "microsoft.sql/servers/databases",
    "microsoft.dbforpostgresql/flexibleservers",
    "microsoft.cache/redis",
)
EXTENSION_RESOURCE_TYPES = (
    "microsoft.hybridcompute/machines/extensions",
    "microsoft.compute/virtualmachines/extensions",
)
CRITICAL_EXTENSION_TOKENS = (
    "mde",
    "defender",
    "aadlogin",
    "aadsshlogin",
    "azuremonitor",
    "ama",
    "omsagent",
    "dependencyagent",
    "keyvault",
    "policy",
)

SEVERITY_RANK = {"critical": 0, "high": 1, "medium": 2, "low": 3}
SEVERITY_LABELS = {
    "critical": "Crítica",
    "high": "Alta",
    "medium": "Media",
    "low": "Baja",
}
CATEGORY_LABELS = {
    "native_alert": "Alerta nativa Azure Monitor",
    "service_health": "Comunicación Azure Service Health",
    "extension_failure": "Fallo de extensión VM / Azure Arc",
    "connectivity_posture": "Anomalía de plano de control / conectividad",
    "telemetry_anomaly": "Anomalía estadística / umbral de telemetría",
    "advisor_recommendation": "Recomendación correlacionada Azure Advisor",
}
HORIZON_LABELS = {
    "immediate_24h": "Inmediato <24h",
    "short_term_7d": "Corto plazo 1-7 días",
    "monthly_cycle": "Ciclo mensual",
}
EFFORT_LABELS = {
    "low": "Bajo",
    "medium": "Medio",
    "high": "Alto",
}

# BEGIN BUILD-TIME ASSETS
HTML_TEMPLATE = (
    '<!DOCTYPE html>\n<html lang="es" data-theme="light">\n<head>\n<meta charset="utf-8">\n<meta name="viewpo'
    'rt" content="width=device-width, initial-scale=1">\n<meta http-equiv="Content-Security-Policy" conten'
    't="default-src \'none\'; img-src data:; style-src \'unsafe-inline\'; script-src \'unsafe-inline\'; base-ur'
    'i \'none\'; form-action \'none\'; connect-src \'none\'">\n<title>Informe de Operaciones, Incidencias, Anoma'
    'lías y Acciones Recomendadas</title>\n<style>\n:root {\n  --brand-orange: #FF4E00;\n  --brand-orange-alt'
    ': #FC4C00;\n  --brand-orange-text: #C23800;\n  --brand-orange-wash: #FFF2EC;\n  --slate-topbar: #141B24'
    ';\n  --slate-header: #1C2532;\n  --bg-page: #F6F5F2;\n  --bg-panel: #FFFFFF;\n  --bg-subtle: #EFECE6;\n  '
    '--bg-row-hover: #F9F7F3;\n  --ink-primary: #141B24;\n  --ink-secondary: #3E4C5E;\n  --ink-muted: #5A687'
    'A;\n  --border-hairline: #D8DCE3;\n  --border-strong: #9AA5B5;\n  --sev-critical-text: #A41E22;\n  --sev'
    '-critical-bg: #FDF2F2;\n  --sev-critical-border: #E8B4B6;\n  --sev-high-text: #B83300;\n  --sev-high-bg'
    ': #FFF4EE;\n  --sev-high-border: #F0C0A8;\n  --sev-medium-text: #7A5200;\n  --sev-medium-bg: #FFFAEB;\n '
    ' --sev-medium-border: #E5D090;\n  --sev-low-text: #2E4057;\n  --sev-low-bg: #F2F5F8;\n  --sev-low-borde'
    'r: #C8D2DF;\n  --status-ok-text: #145A32;\n  --status-ok-bg: #EEF8F2;\n  --status-ok-border: #A9DFBF;\n '
    " --font-sans: 'Outfit', 'Segoe UI', system-ui, -apple-system, sans-serif;\n  --font-mono: 'Consolas',"
    " ui-monospace, 'Cascadia Mono', monospace;\n  --shadow-panel: 0 2px 6px rgba(20, 27, 36, 0.05);\n}\n\nht"
    'ml[data-theme="dark"] {\n  --brand-orange: #FF5C14;\n  --brand-orange-alt: #FF6B2B;\n  --brand-orange-t'
    'ext: #FF8854;\n  --brand-orange-wash: #2B1A12;\n  --slate-topbar: #0B0F15;\n  --slate-header: #121923;\n'
    '  --bg-page: #0F141B;\n  --bg-panel: #161E29;\n  --bg-subtle: #1D2736;\n  --bg-row-hover: #1F2A3A;\n  --'
    'ink-primary: #F3F5F8;\n  --ink-secondary: #CBD5E1;\n  --ink-muted: #94A3B8;\n  --border-hairline: #2A36'
    '47;\n  --border-strong: #475569;\n  --sev-critical-text: #GTA0A4;\n  --sev-critical-text: #FCA5A5;\n  --'
    'sev-critical-bg: #35181B;\n  --sev-critical-border: #6E2B30;\n  --sev-high-text: #FDBA8C;\n  --sev-high'
    '-bg: #362015;\n  --sev-high-border: #783F21;\n  --sev-medium-text: #FDE047;\n  --sev-medium-bg: #332B14'
    ';\n  --sev-medium-border: #6B571E;\n  --sev-low-text: #CBD5E1;\n  --sev-low-bg: #1E293B;\n  --sev-low-bo'
    'rder: #3B4C66;\n  --status-ok-text: #86EFAC;\n  --status-ok-bg: #132A1F;\n  --status-ok-border: #23533B'
    ';\n  --shadow-panel: 0 4px 10px rgba(0, 0, 0, 0.28);\n}\n\n*, *::before, *::after {\n  box-sizing: border'
    '-box;\n}\n\nbody {\n  margin: 0;\n  padding: 0;\n  background-color: var(--bg-page);\n  color: var(--ink-pr'
    'imary);\n  font-family: var(--font-sans);\n  font-size: 15px;\n  line-height: 1.5;\n  font-variant-numer'
    'ic: tabular-nums;\n  -webkit-font-smoothing: antialiased;\n}\n\na {\n  color: var(--brand-orange-text);\n '
    ' text-decoration: underline;\n  text-underline-offset: 2px;\n}\n\na:hover {\n  color: var(--brand-orange)'
    ';\n}\n\na:focus-visible, button:focus-visible, select:focus-visible, input:focus-visible {\n  outline: 2'
    'px solid var(--brand-orange);\n  outline-offset: 2px;\n}\n\n/* Top Architectural Bar */\n.topbar {\n  back'
    'ground-color: var(--slate-topbar);\n  color: #FFFFFF;\n  border-bottom: 2px solid var(--brand-orange);'
    '\n}\n\n.topbar-inner {\n  max-width: 1440px;\n  margin: 0 auto;\n  padding: 14px 24px;\n  display: flex;\n  '
    'flex-wrap: wrap;\n  align-items: center;\n  justify-content: space-between;\n  gap: 16px;\n}\n\n.brand-ide'
    'ntity {\n  display: flex;\n  align-items: center;\n  gap: 16px;\n  min-width: 0;\n}\n\n.client-plaque {\n  b'
    'ackground-color: #FFFFFF;\n  color: #141B24;\n  border: 1px solid #D8DCE3;\n  border-radius: 3px;\n  pad'
    'ding: 6px 12px;\n  display: inline-flex;\n  align-items: center;\n  gap: 10px;\n  flex-shrink: 0;\n}\n\n.cl'
    'ient-plaque img {\n  max-height: 28px;\n  width: auto;\n  display: block;\n}\n\n.client-name-label {\n  fon'
    't-weight: 700;\n  font-size: 14px;\n  letter-spacing: -0.01em;\n  color: #141B24;\n}\n\n.topbar-title-grou'
    'p {\n  min-width: 0;\n}\n\n.topbar-title {\n  margin: 0;\n  font-size: 18px;\n  font-weight: 600;\n  letter-'
    'spacing: -0.02em;\n  color: #FFFFFF;\n}\n\n.topbar-subtitle {\n  margin: 2px 0 0 0;\n  font-size: 13px;\n  '
    'color: #CBD5E1;\n}\n\n.toolbar-actions {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: center;\n  g'
    'ap: 8px;\n}\n\n.btn-action {\n  background-color: #1F2937;\n  color: #F8FAFC;\n  border: 1px solid #3B495E'
    ';\n  border-radius: 3px;\n  padding: 7px 12px;\n  font-family: var(--font-sans);\n  font-size: 13px;\n  f'
    'ont-weight: 500;\n  cursor: pointer;\n  transition: background-color 160ms ease, border-color 160ms ea'
    'se;\n}\n\n.btn-action:hover {\n  background-color: #2D3B4E;\n  border-color: var(--brand-orange);\n}\n\n.btn'
    '-action-primary {\n  background-color: var(--brand-orange);\n  color: #141B24;\n  border-color: var(--b'
    'rand-orange);\n  font-weight: 600;\n}\n\n.btn-action-primary:hover {\n  background-color: #FF6929;\n  bord'
    'er-color: #FF6929;\n}\n\n/* Section Navigation Bar */\n.section-nav {\n  background-color: var(--bg-panel'
    ');\n  border-bottom: 1px solid var(--border-hairline);\n}\n\n.section-nav-inner {\n  max-width: 1440px;\n '
    ' margin: 0 auto;\n  padding: 8px 24px;\n  display: flex;\n  flex-wrap: wrap;\n  gap: 16px;\n}\n\n.section-n'
    'av a {\n  color: var(--ink-secondary);\n  text-decoration: none;\n  font-size: 13px;\n  font-weight: 600'
    ';\n  padding: 4px 0;\n  border-bottom: 2px solid transparent;\n  transition: color 150ms ease, border-c'
    'olor 150ms ease;\n}\n\n.section-nav a:hover {\n  color: var(--brand-orange-text);\n  border-bottom-color:'
    ' var(--brand-orange);\n}\n\n/* Main Workspace Container */\n.workspace-container {\n  max-width: 1440px;\n'
    '  margin: 0 auto;\n  padding: 24px;\n  display: flex;\n  flex-direction: column;\n  gap: 28px;\n}\n\n/* Wor'
    'kpaper Panel */\n.workpaper {\n  background-color: var(--bg-panel);\n  border: 1px solid var(--border-h'
    'airline);\n  border-radius: 2px;\n  box-shadow: var(--shadow-panel);\n  padding: 24px;\n}\n\n.workpaper-he'
    'ader {\n  display: flex;\n  flex-wrap: wrap;\n  align-items: baseline;\n  justify-content: space-between'
    ';\n  gap: 12px;\n  padding-bottom: 14px;\n  margin-bottom: 18px;\n  border-bottom: 1px solid var(--borde'
    'r-hairline);\n}\n\n.workpaper-header h1,\n.workpaper-header h2 {\n  margin: 0;\n  font-size: 22px;\n  font-'
    'weight: 600;\n  letter-spacing: -0.02em;\n  color: var(--ink-primary);\n}\n\n.workpaper-header h1 {\n  fon'
    't-size: 26px;\n}\n\n.workpaper-meta {\n  font-size: 13px;\n  color: var(--ink-muted);\n}\n\n/* Provenance St'
    'rip */\n.provenance-grid {\n  display: grid;\n  grid-template-columns: repeat(auto-fit, minmax(210px, 1'
    'fr));\n  border: 1px solid var(--border-hairline);\n  background-color: var(--bg-subtle);\n  margin-bot'
    'tom: 20px;\n}\n\n.provenance-cell {\n  padding: 12px 14px;\n  border-right: 1px solid var(--border-hairli'
    'ne);\n  border-bottom: 1px solid var(--border-hairline);\n}\n\n.provenance-cell-title {\n  font-size: 12p'
    'x;\n  font-weight: 600;\n  color: var(--ink-muted);\n  margin-bottom: 4px;\n}\n\n.provenance-cell-value {\n'
    '  font-size: 14px;\n  font-weight: 600;\n  color: var(--ink-primary);\n  word-break: break-word;\n}\n\n/* '
    'Swiss Ledger Summary Strip */\n.ledger-summary-grid {\n  display: grid;\n  grid-template-columns: repea'
    't(auto-fit, minmax(200px, 1fr));\n  border: 1px solid var(--border-hairline);\n  margin-bottom: 20px;\n'
    '}\n\n.ledger-summary-cell {\n  padding: 14px 16px;\n  background-color: var(--bg-panel);\n  border-right:'
    ' 1px solid var(--border-hairline);\n  border-bottom: 1px solid var(--border-hairline);\n  display: fle'
    'x;\n  flex-direction: column;\n  justify-content: space-between;\n  gap: 6px;\n}\n\n.ledger-summary-title '
    '{\n  font-size: 13px;\n  font-weight: 600;\n  color: var(--ink-secondary);\n}\n\n.ledger-summary-figure {\n'
    '  font-size: 28px;\n  font-weight: 700;\n  line-height: 1.15;\n  color: var(--ink-primary);\n}\n\n.ledger-'
    'summary-detail {\n  font-size: 12px;\n  color: var(--ink-muted);\n}\n\n/* Proportional Evidence Distribut'
    'ion Bar */\n.distribution-wrap {\n  margin-bottom: 20px;\n  padding: 14px 16px;\n  background-color: var'
    '(--bg-subtle);\n  border: 1px solid var(--border-hairline);\n}\n\n.distribution-header {\n  display: flex'
    ';\n  justify-content: space-between;\n  align-items: center;\n  font-size: 13px;\n  font-weight: 600;\n  '
    'color: var(--ink-secondary);\n  margin-bottom: 8px;\n}\n\n.distribution-track {\n  height: 10px;\n  width:'
    ' 100%;\n  background-color: var(--border-hairline);\n  display: flex;\n  overflow: hidden;\n  border-rad'
    'ius: 1px;\n}\n\n.dist-seg-critical { background-color: #C92A2A; }\n.dist-seg-high { background-color: #F'
    'F4E00; }\n.dist-seg-medium { background-color: #D97706; }\n.dist-seg-low { background-color: #475569; '
    '}\n\n.distribution-legend {\n  display: flex;\n  flex-wrap: wrap;\n  gap: 16px;\n  margin-top: 8px;\n  font'
    '-size: 12px;\n  color: var(--ink-secondary);\n}\n\n.legend-item {\n  display: inline-flex;\n  align-items:'
    ' center;\n  gap: 6px;\n}\n\n.legend-swatch {\n  width: 8px;\n  height: 8px;\n  display: inline-block;\n}\n\n/*'
    ' Executive Messages List */\n.executive-list {\n  margin: 0;\n  padding-left: 20px;\n  max-width: 74ch;\n'
    '  color: var(--ink-primary);\n}\n\n.executive-list li {\n  margin-bottom: 8px;\n}\n\n/* Interactive Filter '
    'Bar */\n.filter-bar {\n  display: grid;\n  grid-template-columns: repeat(auto-fit, minmax(190px, 1fr));'
    '\n  gap: 12px;\n  align-items: end;\n}\n\n.filter-field {\n  display: flex;\n  flex-direction: column;\n  ga'
    'p: 4px;\n}\n\n.filter-field label {\n  font-size: 12px;\n  font-weight: 600;\n  color: var(--ink-secondary'
    ');\n}\n\n.filter-control {\n  width: 100%;\n  padding: 8px 10px;\n  font-family: var(--font-sans);\n  font-'
    'size: 14px;\n  background-color: var(--bg-panel);\n  color: var(--ink-primary);\n  border: 1px solid va'
    'r(--border-strong);\n  border-radius: 2px;\n}\n\n.filter-footer {\n  margin-top: 12px;\n  padding-top: 12p'
    'x;\n  border-top: 1px solid var(--border-hairline);\n  display: flex;\n  flex-wrap: wrap;\n  justify-con'
    'tent: space-between;\n  align-items: center;\n  gap: 12px;\n  font-size: 13px;\n  color: var(--ink-secon'
    'dary);\n}\n\n/* Architectural Data Tables */\n.table-scroll {\n  width: 100%;\n  overflow-x: auto;\n  borde'
    'r: 1px solid var(--border-hairline);\n}\n\n.ledger-table {\n  width: 100%;\n  border-collapse: collapse;\n'
    '  text-align: left;\n  font-size: 13.5px;\n}\n\n.ledger-table th {\n  background-color: var(--bg-subtle);'
    '\n  color: var(--ink-primary);\n  font-weight: 600;\n  font-size: 12.5px;\n  padding: 10px 12px;\n  borde'
    'r-bottom: 1px solid var(--border-strong);\n  border-right: 1px solid var(--border-hairline);\n  white-'
    'space: nowrap;\n}\n\n.ledger-table td {\n  padding: 10px 12px;\n  border-bottom: 1px solid var(--border-h'
    'airline);\n  border-right: 1px solid var(--border-hairline);\n  vertical-align: top;\n  color: var(--in'
    'k-primary);\n}\n\n.ledger-table tr:hover td {\n  background-color: var(--bg-row-hover);\n}\n\n.mono {\n  fon'
    't-family: var(--font-mono);\n  font-size: 12px;\n  word-break: break-all;\n}\n\n/* Status & Severity Mark'
    'ers (1px hairline, no slop pills) */\n.sev-tag {\n  display: inline-flex;\n  align-items: center;\n  gap'
    ': 5px;\n  padding: 2px 7px;\n  font-size: 12px;\n  font-weight: 600;\n  border-radius: 2px;\n  border: 1p'
    'x solid var(--border-hairline);\n  white-space: nowrap;\n}\n\n.sev-critical {\n  color: var(--sev-critica'
    'l-text);\n  background-color: var(--sev-critical-bg);\n  border-color: var(--sev-critical-border);\n}\n\n'
    '.sev-high {\n  color: var(--sev-high-text);\n  background-color: var(--sev-high-bg);\n  border-color: v'
    'ar(--sev-high-border);\n}\n\n.sev-medium {\n  color: var(--sev-medium-text);\n  background-color: var(--s'
    'ev-medium-bg);\n  border-color: var(--sev-medium-border);\n}\n\n.sev-low {\n  color: var(--sev-low-text);'
    '\n  background-color: var(--sev-low-bg);\n  border-color: var(--sev-low-border);\n}\n\n.sev-ok {\n  color:'
    ' var(--status-ok-text);\n  background-color: var(--status-ok-bg);\n  border-color: var(--status-ok-bor'
    'der);\n}\n\n.horizon-tag {\n  display: inline-block;\n  padding: 2px 7px;\n  font-size: 12px;\n  font-weigh'
    't: 600;\n  border: 1px solid var(--border-strong);\n  background-color: var(--bg-subtle);\n  color: var'
    '(--ink-primary);\n  border-radius: 2px;\n  white-space: nowrap;\n}\n\n.horizon-immediate_24h {\n  border-c'
    'olor: var(--brand-orange);\n  background-color: var(--brand-orange-wash);\n  color: var(--brand-orange'
    '-text);\n}\n\n.empty-ledger-row td {\n  text-align: center;\n  padding: 20px;\n  color: var(--ink-muted);\n'
    '  font-style: italic;\n}\n\n.sub-heading {\n  margin: 24px 0 12px 0;\n  font-size: 17px;\n  font-weight: 6'
    '00;\n  color: var(--ink-primary);\n}\n\n@media (max-width: 768px) {\n  .topbar-inner,\n  .section-nav-inne'
    'r,\n  .workspace-container {\n    padding-left: 14px;\n    padding-right: 14px;\n  }\n  .workpaper {\n    '
    'padding: 16px;\n  }\n  .workpaper-header h1 {\n    font-size: 21px;\n  }\n  .workpaper-header h2 {\n    fo'
    'nt-size: 18px;\n  }\n}\n\n@media print {\n  .toolbar-actions,\n  .section-nav,\n  #sec-filters {\n    displa'
    'y: none !important;\n  }\n  body {\n    background-color: #FFFFFF;\n    color: #000000;\n  }\n  .workpaper'
    ' {\n    box-shadow: none;\n    page-break-inside: avoid;\n  }\n}\n</style>\n</head>\n<body>\n<header class="'
    'topbar" id="topbar">\n  <div class="topbar-inner">\n    <div class="brand-identity">\n      <div class='
    '"client-plaque" id="client-plaque">\n        <span id="client-logo-slot"></span>\n        <span class='
    '"client-name-label" id="client-name-label">CLIENTE</span>\n      </div>\n      <div class="topbar-titl'
    'e-group">\n        <p class="topbar-title">Dossier de Operaciones, Incidencias, Anomalías y Acciones '
    'Recomendadas</p>\n        <p class="topbar-subtitle" id="topbar-subtitle">Consolidación multifuente e'
    'n modo solo lectura · Azure SRE Agent</p>\n      </div>\n    </div>\n    <div class="toolbar-actions">\n'
    '      <button type="button" class="btn-action" id="theme-toggle">Modo oscuro</button>\n      <button '
    'type="button" class="btn-action" id="btn-export-json">Exportar JSON</button>\n      <button type="but'
    'ton" class="btn-action" id="btn-export-incidents-csv">Exportar Incidencias y Anomalías CSV</button>\n'
    '      <button type="button" class="btn-action btn-action-primary" id="btn-export-actions-csv">Export'
    'ar Acciones Recomendadas CSV</button>\n      <button type="button" class="btn-action" id="btn-print">'
    'Imprimir / PDF</button>\n    </div>\n  </div>\n</header>\n\n<nav class="section-nav" aria-label="Seccione'
    's del informe">\n  <div class="section-nav-inner">\n    <a href="#sec-executive">Síntesis ejecutiva</a'
    '>\n    <a href="#sec-filters">Filtros operativos</a>\n    <a href="#sec-incidents">Incidencias y alert'
    'as (<span id="nav-incidents-count">0</span>)</a>\n    <a href="#sec-anomalies">Anomalías técnicas (<s'
    'pan id="nav-anomalies-count">0</span>)</a>\n    <a href="#sec-actions">Acciones recomendadas (<span i'
    'd="nav-actions-count">0</span>)</a>\n    <a href="#sec-resources">Recursos y Advisor (<span id="nav-r'
    'esources-count">0</span>)</a>\n    <a href="#sec-coverage">Cobertura de fuentes (<span id="nav-source'
    's-count">0</span>)</a>\n  </div>\n</nav>\n\n<main class="workspace-container" id="report-body">\n  <!-- 1'
    '. Executive Synthesis & Window Provenance Header -->\n  <section class="workpaper" id="sec-executive"'
    '>\n    <div class="workpaper-header">\n      <h1 id="cover-title">Informe de Operaciones con Incidenci'
    'as, Anomalías y Acciones Recomendadas</h1>\n      <span class="workpaper-meta" id="reference-utc-labe'
    'l">Referencia UTC: —</span>\n    </div>\n\n    <div class="provenance-grid" id="provenance-strip">\n    '
    '  <div class="provenance-cell">\n        <div class="provenance-cell-title">Suscripción Azure</div>\n '
    '       <div class="provenance-cell-value mono" id="prov-subscription">—</div>\n      </div>\n      <di'
    'v class="provenance-cell">\n        <div class="provenance-cell-title">Ventana evaluada</div>\n       '
    ' <div class="provenance-cell-value" id="prov-window-label">—</div>\n      </div>\n      <div class="pr'
    'ovenance-cell">\n        <div class="provenance-cell-title">Intervalo UTC exacto</div>\n        <div c'
    'lass="provenance-cell-value mono" id="prov-window-range">—</div>\n      </div>\n      <div class="prov'
    'enance-cell">\n        <div class="provenance-cell-title">Cadencia y programación</div>\n        <div '
    'class="provenance-cell-value" id="prov-cadence">—</div>\n      </div>\n      <div class="provenance-ce'
    'll">\n        <div class="provenance-cell-title">Origen de evidencia</div>\n        <div class="proven'
    'ance-cell-value" id="prov-provenance">—</div>\n      </div>\n    </div>\n\n    <div class="ledger-summar'
    'y-grid" id="ledger-summary-grid">\n      <div class="ledger-summary-cell">\n        <span class="ledge'
    'r-summary-title">Alertas nativas Azure Monitor</span>\n        <span class="ledger-summary-figure" id'
    '="kpi-native-alerts">0</span>\n        <span class="ledger-summary-detail" id="kpi-native-alerts-sub"'
    '>alertsmanagementresources</span>\n      </div>\n      <div class="ledger-summary-cell">\n        <span'
    ' class="ledger-summary-title">Eventos Azure Service Health</span>\n        <span class="ledger-summar'
    'y-figure" id="kpi-service-health">0</span>\n        <span class="ledger-summary-detail" id="kpi-servi'
    'ce-health-sub">ServiceIssue &amp; PlannedMaintenance</span>\n      </div>\n      <div class="ledger-su'
    'mmary-cell">\n        <span class="ledger-summary-title">Anomalías plano control y Arc</span>\n       '
    ' <span class="ledger-summary-figure" id="kpi-posture-anomalies">0</span>\n        <span class="ledger'
    '-summary-detail" id="kpi-posture-anomalies-sub">Extensiones fallidas y conectividad</span>\n      </d'
    'iv>\n      <div class="ledger-summary-cell">\n        <span class="ledger-summary-title">Anomalías de '
    'telemetría</span>\n        <span class="ledger-summary-figure" id="kpi-telemetry-anomalies">0</span>\n'
    '        <span class="ledger-summary-detail" id="kpi-telemetry-anomalies-sub">InsightsMetrics, Perf y'
    ' Heartbeat</span>\n      </div>\n      <div class="ledger-summary-cell">\n        <span class="ledger-s'
    'ummary-title">Acciones recomendadas</span>\n        <span class="ledger-summary-figure" id="kpi-actio'
    'ns-total">0</span>\n        <span class="ledger-summary-detail" id="kpi-actions-sub">Priorizadas por '
    'horizonte</span>\n      </div>\n      <div class="ledger-summary-cell">\n        <span class="ledger-su'
    'mmary-title">Recursos en alcance</span>\n        <span class="ledger-summary-figure" id="kpi-resource'
    's-total">0</span>\n        <span class="ledger-summary-detail" id="kpi-resources-sub">0 requieren ate'
    'nción</span>\n      </div>\n    </div>\n\n    <div class="distribution-wrap" id="evidence-distribution-b'
    'ar">\n      <div class="distribution-header">\n        <span>Distribución de severidad sobre hallazgos'
    ' operativos (incidencias + anomalías)</span>\n        <span id="dist-total-label">0 señales</span>\n  '
    '    </div>\n      <div class="distribution-track" id="dist-track"></div>\n      <div class="distributi'
    'on-legend" id="dist-legend"></div>\n    </div>\n\n    <ul class="executive-list" id="executive-messages'
    '-list"></ul>\n  </section>\n\n  <!-- 2. Interactive Filter Bar -->\n  <section class="workpaper" id="sec'
    '-filters">\n    <div class="workpaper-header">\n      <h2>Filtros Operativos de Inspección</h2>\n      '
    '<span class="workpaper-meta" id="filter-status-summary">Mostrando la totalidad de registros recolect'
    'ados</span>\n    </div>\n    <div class="filter-bar">\n      <div class="filter-field">\n        <label '
    'for="filter-category">Flujo de evidencia (`category`)</label>\n        <select class="filter-control"'
    ' id="filter-category">\n          <option value="all">Todas las categorías</option>\n          <option'
    ' value="native_alert">Alertas nativas Azure Monitor</option>\n          <option value="service_health'
    '">Comunicaciones Azure Service Health</option>\n          <option value="extension_failure">Fallos de'
    ' extensión VM / Azure Arc</option>\n          <option value="connectivity_posture">Anomalías de conec'
    'tividad / plano de control</option>\n          <option value="telemetry_anomaly">Anomalías de telemet'
    'ría (CPU / Memoria / Disco / Heartbeat)</option>\n          <option value="advisor_recommendation">Re'
    'comendaciones Azure Advisor</option>\n        </select>\n      </div>\n      <div class="filter-field">'
    '\n        <label for="filter-severity">Severidad (`severity`)</label>\n        <select class="filter-c'
    'ontrol" id="filter-severity">\n          <option value="all">Todas las severidades</option>\n         '
    ' <option value="critical">Crítica</option>\n          <option value="high">Alta</option>\n          <o'
    'ption value="medium">Media</option>\n          <option value="low">Baja</option>\n        </select>\n  '
    '    </div>\n      <div class="filter-field">\n        <label for="filter-horizon">Horizonte de acción '
    '(`horizon`)</label>\n        <select class="filter-control" id="filter-horizon">\n          <option va'
    'lue="all">Todos los horizontes</option>\n          <option value="immediate_24h">Inmediato &lt;24h</o'
    'ption>\n          <option value="short_term_7d">Corto plazo 1-7 días</option>\n          <option value'
    '="monthly_cycle">Ciclo mensual</option>\n        </select>\n      </div>\n      <div class="filter-fiel'
    'd">\n        <label for="filter-search">Búsqueda por recurso, ID, extensión o métrica</label>\n       '
    ' <input type="search" class="filter-control" id="filter-search" placeholder="Ej. arcbox-win2k25, MDE'
    '.Windows, aks...">\n      </div>\n    </div>\n    <div class="filter-footer">\n      <span id="filter-ac'
    'tive-note">Los filtros actualizan en vivo las tablas de incidencias, anomalías y acciones recomendad'
    'as.</span>\n      <button type="button" class="btn-action" id="filter-reset">Restablecer filtros</but'
    'ton>\n    </div>\n  </section>\n\n  <!-- 3. Unified Incidents Ledger -->\n  <section class="workpaper" id'
    '="sec-incidents">\n    <div class="workpaper-header">\n      <h2>Registro Unificado de Incidencias y C'
    'omunicaciones de Plataforma</h2>\n      <span class="workpaper-meta">Visibles: <strong id="incidents-'
    'count">0</strong> registros (`native_alert` + `service_health`)</span>\n    </div>\n    <div class="ta'
    'ble-scroll">\n      <table class="ledger-table" id="incidents-table">\n        <thead>\n          <tr>\n'
    '            <th>ID</th>\n            <th>Categoría</th>\n            <th>Severidad</th>\n            <t'
    'h>Estado / Condición</th>\n            <th>Recurso / Servicio</th>\n            <th>Señal / Tipo</th>\n'
    '            <th>Inicio / Última actualización UTC</th>\n            <th>Descripción y referencia</th>'
    '\n          </tr>\n        </thead>\n        <tbody id="incidents-tbody"></tbody>\n      </table>\n    </'
    'div>\n  </section>\n\n  <!-- 4. Technical Anomalies Ledger -->\n  <section class="workpaper" id="sec-ano'
    'malies">\n    <div class="workpaper-header">\n      <h2>Registro de Anomalías Técnicas (Plano de Contr'
    'ol, Extensiones y Telemetría)</h2>\n      <span class="workpaper-meta">Visibles: <strong id="anomalie'
    's-count">0</strong> anomalías (`extension_failure`, `connectivity_posture`, `telemetry_anomaly`)</sp'
    'an>\n    </div>\n    <div class="table-scroll">\n      <table class="ledger-table" id="anomalies-table"'
    '>\n        <thead>\n          <tr>\n            <th>ID</th>\n            <th>Categoría</th>\n            '
    '<th>Severidad</th>\n            <th>Recurso / Grupo</th>\n            <th>Métrica o Propiedad</th>\n   '
    '         <th>Valor observado vs. Referencia</th>\n            <th>Muestras / Ventana</th>\n           '
    ' <th>Evidencia técnica y guía</th>\n          </tr>\n        </thead>\n        <tbody id="anomalies-tbo'
    'dy"></tbody>\n      </table>\n    </div>\n  </section>\n\n  <!-- 5. Prioritized Recommended Actions Matri'
    'x -->\n  <section class="workpaper" id="sec-actions">\n    <div class="workpaper-header">\n      <h2>Ma'
    'triz Priorizada de Acciones Recomendadas (`Acciones Recomendadas`)</h2>\n      <span class="workpaper'
    '-meta">Visibles: <strong id="actions-count">0</strong> acciones vinculadas a evidencias</span>\n    <'
    '/div>\n    <div class="table-scroll">\n      <table class="ledger-table" id="actions-table">\n        <'
    'thead>\n          <tr>\n            <th>Prioridad</th>\n            <th>Horizonte</th>\n            <th>'
    'Severidad</th>\n            <th>Acción recomendada y recurso</th>\n            <th>Ámbito responsable '
    '/ Esfuerzo</th>\n            <th>Evidencias vinculadas</th>\n            <th>Guía técnica para revisió'
    'n humana</th>\n          </tr>\n        </thead>\n        <tbody id="actions-tbody"></tbody>\n      </ta'
    'ble>\n    </div>\n  </section>\n\n  <!-- 6. Resource Health & Correlated Advisor Context -->\n  <section '
    'class="workpaper" id="sec-resources">\n    <div class="workpaper-header">\n      <h2>Estado Operativo '
    'por Recurso y Recomendaciones de Azure Advisor</h2>\n      <span class="workpaper-meta">Recursos: <st'
    'rong id="resources-count">0</strong> · Advisor: <strong id="advisor-count">0</strong></span>\n    </d'
    'iv>\n    <div class="table-scroll">\n      <table class="ledger-table" id="resources-table">\n        <'
    'thead>\n          <tr>\n            <th>Recurso</th>\n            <th>Tipo / Hosting</th>\n            <'
    'th>Grupo / Región</th>\n            <th>Estado operativo</th>\n            <th>Incidencias</th>\n      '
    '      <th>Anomalías</th>\n            <th>Ext. fallidas</th>\n            <th>Acciones</th>\n          '
    '  <th>Resumen de telemetría</th>\n          </tr>\n        </thead>\n        <tbody id="resources-tbody'
    '"></tbody>\n      </table>\n    </div>\n\n    <h3 class="sub-heading">Recomendaciones en Caché de Azure '
    'Advisor (`arm_advisor_recommendations`)</h3>\n    <div class="table-scroll">\n      <table class="ledg'
    'er-table" id="advisor-table">\n        <thead>\n          <tr>\n            <th>ID</th>\n            <th'
    '>Categoría Advisor</th>\n            <th>Impacto</th>\n            <th>Recurso</th>\n            <th>Pr'
    'oblema detectado</th>\n            <th>Solución recomendada</th>\n            <th>Actualizado UTC</th>'
    '\n          </tr>\n        </thead>\n        <tbody id="advisor-tbody"></tbody>\n      </table>\n    </di'
    'v>\n  </section>\n\n  <!-- 7. Source Coverage Receipts & Methodology -->\n  <section class="workpaper" i'
    'd="sec-coverage">\n    <div class="workpaper-header">\n      <h2>Recibos de Cobertura de Fuentes y Met'
    'odología de Solo Lectura</h2>\n      <span class="workpaper-meta">Fuentes verificadas: <strong id="so'
    'urces-count">0</strong></span>\n    </div>\n    <div class="table-scroll">\n      <table class="ledger-'
    'table" id="sources-table">\n        <thead>\n          <tr>\n            <th>Fuente (`source_id`)</th>\n'
    '            <th>Estado</th>\n            <th>Registros</th>\n            <th>Páginas</th>\n            '
    '<th>Paginación completa</th>\n            <th>Firma de lectura / Detalle</th>\n            <th>Notas y'
    ' alcance</th>\n          </tr>\n        </thead>\n        <tbody id="sources-tbody"></tbody>\n      </ta'
    'ble>\n    </div>\n\n    <h3 class="sub-heading">Garantías Operativas y Limitaciones Metodológicas</h3>\n'
    '    <ul class="executive-list" id="methodology-list"></ul>\n  </section>\n</main>\n\n<script type="appli'
    'cation/json" id="report-data">__REPORT_DATA_JSON__</script>\n<script>\n(function () {\n  "use strict";\n'
    '\n  var rawText = document.getElementById("report-data").textContent;\n  var DATA = JSON.parse(rawText'
    ');\n\n  function el(tag, attrs, children) {\n    var node = document.createElement(tag);\n    if (attrs)'
    ' {\n      Object.keys(attrs).forEach(function (k) {\n        if (k === "className") {\n          node.c'
    'lassName = attrs[k];\n        } else if (k === "textContent") {\n          node.textContent = attrs[k]'
    ';\n        } else if (attrs[k] !== null && attrs[k] !== undefined) {\n          node.setAttribute(k, S'
    'tring(attrs[k]));\n        }\n      });\n    }\n    if (Array.isArray(children)) {\n      children.forEac'
    'h(function (ch) {\n        if (typeof ch === "string") {\n          node.appendChild(document.createTe'
    'xtNode(ch));\n        } else if (ch) {\n          node.appendChild(ch);\n        }\n      });\n    }\n    '
    'return node;\n  }\n\n  function clear(node) {\n    while (node.firstChild) {\n      node.removeChild(node'
    '.firstChild);\n    }\n  }\n\n  function sevBadge(sev, label) {\n    var s = (sev || "low").toLowerCase();'
    '\n    var cls = "sev-tag sev-" + (["critical", "high", "medium", "low", "ok"].indexOf(s) >= 0 ? s : "'
    'low");\n    return el("span", { className: cls, textContent: label || sev || "Baja" });\n  }\n\n  functi'
    'on renderBranding() {\n    var client = DATA.client || {};\n    var nameLabel = document.getElementByI'
    'd("client-name-label");\n    var logoSlot = document.getElementById("client-logo-slot");\n    clear(lo'
    'goSlot);\n    nameLabel.textContent = client.name || "CLIENTE";\n    if (client.logo_data_uri && /^dat'
    'a:image\\/(png|jpeg);base64,/.test(client.logo_data_uri)) {\n      logoSlot.appendChild(\n        el("i'
    'mg", {\n          id: "client-logo-img",\n          src: client.logo_data_uri,\n          alt: client.l'
    'ogo_alt || "Logotipo autorizado del cliente"\n        })\n      );\n    }\n  }\n\n  function renderExecuti'
    've() {\n    var win = DATA.window || {};\n    var counts = DATA.counts || {};\n    document.getElementB'
    'yId("reference-utc-label").textContent = "Referencia UTC: " + (DATA.reference_utc || "—");\n    docum'
    'ent.getElementById("prov-subscription").textContent = DATA.subscription_id || "—";\n    document.getE'
    'lementById("prov-window-label").textContent = win.label || win.period || "—";\n    document.getElemen'
    'tById("prov-window-range").textContent = (win.start_utc || "—") + " → " + (win.end_utc || "—");\n    '
    'document.getElementById("prov-cadence").textContent = win.cadence || "Mensual programado (30 8 1 * *'
    ' UTC)";\n    document.getElementById("prov-provenance").textContent = (DATA.provenance || "LIVE") + "'
    ' · Solo lectura";\n\n    document.getElementById("kpi-native-alerts").textContent = String(counts.nati'
    've_alerts_total || 0);\n    document.getElementById("kpi-service-health").textContent = String(counts'
    '.service_health_total || 0);\n    var postureTotal = (counts.extension_failures_total || 0) + (counts'
    '.connectivity_posture_total || 0);\n    document.getElementById("kpi-posture-anomalies").textContent '
    '= String(postureTotal);\n    document.getElementById("kpi-posture-anomalies-sub").textContent =\n     '
    ' String(counts.extension_failures_total || 0) + " ext. fallidas · " +\n      String(counts.connectivi'
    'ty_posture_total || 0) + " conectividad/postura";\n    document.getElementById("kpi-telemetry-anomali'
    'es").textContent = String(counts.telemetry_anomalies_total || 0);\n    document.getElementById("kpi-a'
    'ctions-total").textContent = String(counts.actions_total || 0);\n    document.getElementById("kpi-act'
    'ions-sub").textContent =\n      String(counts.actions_immediate_24h || 0) + " <24h · " +\n      String'
    '(counts.actions_short_term_7d || 0) + " 1-7d · " +\n      String(counts.actions_monthly_cycle || 0) +'
    ' " mensual";\n    document.getElementById("kpi-resources-total").textContent = String(counts.resource'
    's_total || 0);\n    document.getElementById("kpi-resources-sub").textContent =\n      String(counts.re'
    'sources_attention || 0) + " con hallazgos activos";\n\n    var sevBreak = counts.severity_breakdown ||'
    ' {};\n    var cCrit = sevBreak.critical || 0;\n    var cHigh = sevBreak.high || 0;\n    var cMed = sevB'
    'reak.medium || 0;\n    var cLow = sevBreak.low || 0;\n    var totalSig = cCrit + cHigh + cMed + cLow;\n'
    '    document.getElementById("dist-total-label").textContent = String(totalSig) + " señales consolida'
    'das";\n\n    var track = document.getElementById("dist-track");\n    var legend = document.getElementBy'
    'Id("dist-legend");\n    clear(track);\n    clear(legend);\n    var items = [\n      { key: "critical", l'
    'abel: "Crítica", count: cCrit, cls: "dist-seg-critical" },\n      { key: "high", label: "Alta", count'
    ': cHigh, cls: "dist-seg-high" },\n      { key: "medium", label: "Media", count: cMed, cls: "dist-seg-'
    'medium" },\n      { key: "low", label: "Baja", count: cLow, cls: "dist-seg-low" }\n    ];\n    items.fo'
    'rEach(function (it) {\n      if (totalSig > 0 && it.count > 0) {\n        var seg = el("div", { classN'
    'ame: it.cls });\n        seg.style.width = ((it.count * 100) / totalSig).toFixed(2) + "%";\n        tr'
    'ack.appendChild(seg);\n      }\n      legend.appendChild(\n        el("span", { className: "legend-item'
    '" }, [\n          el("span", { className: "legend-swatch " + it.cls }),\n          it.label + ": " + S'
    'tring(it.count)\n        ])\n      );\n    });\n\n    var msgList = document.getElementById("executive-me'
    'ssages-list");\n    clear(msgList);\n    (DATA.executive_messages || []).forEach(function (msg) {\n    '
    '  msgList.appendChild(el("li", { textContent: msg }));\n    });\n  }\n\n  function matchesCommonFilter(r'
    'ow, cat, sev, query) {\n    if (cat !== "all" && row.category !== cat) {\n      return false;\n    }\n  '
    '  if (sev !== "all" && row.severity !== sev) {\n      return false;\n    }\n    if (query) {\n      var '
    'hay = [\n        row.id,\n        row.title,\n        row.resource_name,\n        row.resource_id,\n     '
    '   row.resource_group,\n        row.summary,\n        row.metric_or_field,\n        row.signal_type,\n  '
    '      row.owner_scope,\n        row.recommendation\n      ].join(" ").toLowerCase();\n      if (hay.ind'
    'exOf(query) < 0) {\n        return false;\n      }\n    }\n    return true;\n  }\n\n  function renderTables'
    '() {\n    var cat = document.getElementById("filter-category").value;\n    var sev = document.getEleme'
    'ntById("filter-severity").value;\n    var hor = document.getElementById("filter-horizon").value;\n    '
    'var query = (document.getElementById("filter-search").value || "").trim().toLowerCase();\n\n    var in'
    'cidents = (DATA.incidents || []).filter(function (row) {\n      return matchesCommonFilter(row, cat, '
    'sev, query);\n    });\n    var anomalies = (DATA.anomalies || []).filter(function (row) {\n      return'
    ' matchesCommonFilter(row, cat, sev, query);\n    });\n    var actions = (DATA.actions || []).filter(fu'
    'nction (row) {\n      if (hor !== "all" && row.horizon !== hor) {\n        return false;\n      }\n     '
    ' return matchesCommonFilter(row, cat, sev, query);\n    });\n    var resources = (DATA.resources || []'
    ').filter(function (row) {\n      if (sev !== "all" && row.severity !== sev) {\n        return false;\n '
    '     }\n      if (query) {\n        var hay = [row.resource_name, row.resource_id, row.resource_group,'
    ' row.resource_type, row.operational_state].join(" ").toLowerCase();\n        if (hay.indexOf(query) <'
    ' 0) {\n          return false;\n        }\n      }\n      return true;\n    });\n    var advisor = (DATA.a'
    'dvisor || []).filter(function (row) {\n      return matchesCommonFilter(row, cat, sev, query);\n    })'
    ';\n\n    document.getElementById("incidents-count").textContent = String(incidents.length);\n    docume'
    'nt.getElementById("anomalies-count").textContent = String(anomalies.length);\n    document.getElement'
    'ById("actions-count").textContent = String(actions.length);\n    document.getElementById("resources-c'
    'ount").textContent = String(resources.length);\n    document.getElementById("advisor-count").textCont'
    'ent = String(advisor.length);\n\n    document.getElementById("nav-incidents-count").textContent = Stri'
    'ng(incidents.length);\n    document.getElementById("nav-anomalies-count").textContent = String(anomal'
    'ies.length);\n    document.getElementById("nav-actions-count").textContent = String(actions.length);\n'
    '    document.getElementById("nav-resources-count").textContent = String(resources.length);\n\n    docu'
    'ment.getElementById("filter-status-summary").textContent =\n      "Incidencias: " + incidents.length '
    '+ " · Anomalías: " + anomalies.length + " · Acciones: " + actions.length;\n\n    // Incidents table\n  '
    '  var incBody = document.getElementById("incidents-tbody");\n    clear(incBody);\n    if (!incidents.l'
    'ength) {\n      incBody.appendChild(\n        el("tr", { className: "empty-ledger-row" }, [\n          '
    'el("td", { colspan: "8", textContent: "Sin incidencias o alertas que coincidan con los criterios act'
    'uales." })\n        ])\n      );\n    } else {\n      incidents.forEach(function (inc) {\n        incBody'
    '.appendChild(\n          el("tr", null, [\n            el("td", { className: "mono", textContent: inc.'
    'id }),\n            el("td", { textContent: inc.category_label || inc.category }),\n            el("td'
    '", null, [sevBadge(inc.severity, inc.severity_label + " (" + (inc.native_severity || "") + ")")]),\n '
    '           el("td", { textContent: (inc.monitor_condition || "") + " / " + (inc.state || "") }),\n   '
    '         el("td", null, [\n              el("div", { textContent: inc.resource_name }),\n             '
    ' el("div", { className: "mono", textContent: inc.resource_group + " · " + inc.resource_type })\n     '
    '       ]),\n            el("td", { textContent: (inc.signal_type || "") + " · " + (inc.monitor_servic'
    'e || "") }),\n            el("td", { className: "mono" }, [\n              el("div", { textContent: "I'
    'nicio: " + (inc.start_time_utc || "—") }),\n              el("div", { textContent: "Act.: " + (inc.la'
    'st_updated_utc || "—") })\n            ]),\n            el("td", null, [\n              el("div", { tex'
    'tContent: inc.summary }),\n              el("a", { href: inc.learn_url, target: "_blank", rel: "noope'
    'ner noreferrer", textContent: "Documentación Microsoft Learn" })\n            ])\n          ])\n       '
    ' );\n      });\n    }\n\n    // Anomalies table\n    var anomBody = document.getElementById("anomalies-tb'
    'ody");\n    clear(anomBody);\n    if (!anomalies.length) {\n      anomBody.appendChild(\n        el("tr"'
    ', { className: "empty-ledger-row" }, [\n          el("td", { colspan: "8", textContent: "Sin anomalía'
    's técnicas que coincidan con los criterios actuales." })\n        ])\n      );\n    } else {\n      anom'
    'alies.forEach(function (anom) {\n        anomBody.appendChild(\n          el("tr", null, [\n           '
    ' el("td", { className: "mono", textContent: anom.id }),\n            el("td", { textContent: anom.cat'
    'egory_label || anom.category }),\n            el("td", null, [sevBadge(anom.severity, anom.severity_l'
    'abel)]),\n            el("td", null, [\n              el("div", { textContent: anom.resource_name }),\n'
    '              el("div", { className: "mono", textContent: anom.resource_group + " · " + anom.hosting'
    '.toUpperCase() })\n            ]),\n            el("td", { className: "mono", textContent: anom.metric'
    '_or_field }),\n            el("td", { className: "mono" }, [\n              el("div", { textContent: "'
    'Obs.: " + String(anom.observed_value) + " " + (anom.unit || "") }),\n              el("div", { textCo'
    'ntent: "Ref.: " + String(anom.baseline_or_expected) + " " + (anom.unit || "") })\n            ]),\n   '
    '         el("td", { className: "mono" }, [\n              el("div", { textContent: String(anom.sample'
    '_count || 1) + " muestras" }),\n              el("div", { textContent: (anom.window_grain || "PointIn'
    'Time") + (anom.workspace_name ? " · " + anom.workspace_name : "") })\n            ]),\n            el('
    '"td", null, [\n              el("div", { textContent: anom.summary }),\n              el("a", { href: '
    'anom.learn_url, target: "_blank", rel: "noopener noreferrer", textContent: "Guía oficial Microsoft L'
    'earn" })\n            ])\n          ])\n        );\n      });\n    }\n\n    // Actions table\n    var actBod'
    'y = document.getElementById("actions-tbody");\n    clear(actBody);\n    if (!actions.length) {\n      a'
    'ctBody.appendChild(\n        el("tr", { className: "empty-ledger-row" }, [\n          el("td", { colsp'
    'an: "7", textContent: "Sin acciones recomendadas que coincidan con los filtros seleccionados." })\n  '
    '      ])\n      );\n    } else {\n      actions.forEach(function (act) {\n        var horCls = "horizon-'
    'tag horizon-" + (act.horizon || "short_term_7d");\n        actBody.appendChild(\n          el("tr", nu'
    'll, [\n            el("td", { className: "mono", textContent: "#" + String(act.priority_rank) + " (" '
    '+ act.id + ")" }),\n            el("td", null, [el("span", { className: horCls, textContent: act.hori'
    'zon_label })]),\n            el("td", null, [sevBadge(act.severity, act.severity_label)]),\n          '
    '  el("td", null, [\n              el("div", { textContent: act.title }),\n              el("div", { cl'
    'assName: "mono", textContent: act.resource_name + " (" + act.resource_group + ")" })\n            ]),'
    '\n            el("td", null, [\n              el("div", { textContent: act.owner_scope }),\n           '
    '   el("div", { textContent: "Esfuerzo estimado: " + act.effort_label })\n            ]),\n            '
    'el("td", { className: "mono", textContent: (act.linked_evidence_ids || []).join(", ") }),\n          '
    '  el("td", null, [\n              el("div", { textContent: act.recommendation }),\n              el("d'
    'iv", { className: "workpaper-meta", textContent: "Evidencia: " + act.evidence_summary }),\n          '
    '    el("a", { href: act.learn_url, target: "_blank", rel: "noopener noreferrer", textContent: "Refer'
    'encia Microsoft Learn" })\n            ])\n          ])\n        );\n      });\n    }\n\n    // Resources t'
    'able\n    var resBody = document.getElementById("resources-tbody");\n    clear(resBody);\n    if (!reso'
    'urces.length) {\n      resBody.appendChild(\n        el("tr", { className: "empty-ledger-row" }, [\n   '
    '       el("td", { colspan: "9", textContent: "Sin recursos inventariados para el filtro actual." })\n'
    '        ])\n      );\n    } else {\n      resources.forEach(function (res) {\n        var tm = res.telem'
    'etry_metrics || {};\n        var tmParts = [];\n        if (tm.cpu_percent) {\n          tmParts.push("'
    'CPU máx " + tm.cpu_percent.max + "% (med " + tm.cpu_percent.median + "%)");\n        }\n        if (tm'
    '.memory_available_mb) {\n          tmParts.push("Mem mín " + tm.memory_available_mb.min + " MB");\n   '
    '     }\n        if (tm.disk_free_percent) {\n          tmParts.push("Disco libre mín " + tm.disk_free_'
    'percent.min + "%");\n        }\n        if (tm.heartbeat_silence_minutes) {\n          tmParts.push("Si'
    'lencio HB " + tm.heartbeat_silence_minutes.max + " min");\n        }\n        var statusBadge = res.st'
    'atus === "healthy"\n          ? sevBadge("ok", "Normal (" + (res.operational_state || "Succeeded") + '
    '")")\n          : sevBadge(res.severity, res.severity_label + " (" + (res.operational_state || "Atenc'
    'ión") + ")");\n        resBody.appendChild(\n          el("tr", null, [\n            el("td", null, [\n '
    '             el("div", { textContent: res.resource_name }),\n              el("div", { className: "mo'
    'no", textContent: res.resource_id })\n            ]),\n            el("td", { className: "mono", textC'
    'ontent: res.resource_type + " [" + res.hosting.toUpperCase() + "]" }),\n            el("td", { textCo'
    'ntent: res.resource_group + " · " + res.location }),\n            el("td", null, [statusBadge]),\n    '
    '        el("td", { className: "mono", textContent: String(res.incident_count || 0) }),\n            e'
    'l("td", { className: "mono", textContent: String(res.anomaly_count || 0) }),\n            el("td", { '
    'className: "mono", textContent: String(res.failed_extension_count || 0) + "/" + String(res.extension'
    's_total || 0) }),\n            el("td", { className: "mono", textContent: String(res.action_count || '
    '0) }),\n            el("td", { className: "mono", textContent: tmParts.length ? tmParts.join(" · ") :'
    ' "Sin telemetría de huésped en ventana" })\n          ])\n        );\n      });\n    }\n\n    // Advisor t'
    'able\n    var advBody = document.getElementById("advisor-tbody");\n    clear(advBody);\n    if (!adviso'
    'r.length) {\n      advBody.appendChild(\n        el("tr", { className: "empty-ledger-row" }, [\n       '
    '   el("td", { colspan: "7", textContent: "No hay recomendaciones de Azure Advisor en caché para el f'
    'iltro actual." })\n        ])\n      );\n    } else {\n      advisor.forEach(function (adv) {\n        ad'
    'vBody.appendChild(\n          el("tr", null, [\n            el("td", { className: "mono", textContent:'
    ' adv.id }),\n            el("td", { textContent: adv.advisor_category }),\n            el("td", null, '
    '[sevBadge(adv.severity, adv.impact)]),\n            el("td", { textContent: adv.resource_name + " (" '
    '+ adv.resource_group + ")" }),\n            el("td", { textContent: adv.problem }),\n            el("t'
    'd", { textContent: adv.solution }),\n            el("td", { className: "mono", textContent: adv.last_'
    'updated_utc })\n          ])\n        );\n      });\n    }\n  }\n\n  function renderCoverage() {\n    var so'
    'urces = DATA.sources || [];\n    document.getElementById("sources-count").textContent = String(source'
    's.length);\n    document.getElementById("nav-sources-count").textContent = String(sources.length);\n  '
    '  var tbody = document.getElementById("sources-tbody");\n    clear(tbody);\n    sources.forEach(functi'
    'on (src) {\n      var stBadge = src.status === "complete"\n        ? sevBadge("ok", "complete")\n      '
    '  : src.status === "partial"\n        ? sevBadge("medium", "partial")\n        : sevBadge("critical", '
    'src.status);\n      var wsExtra = "";\n      if (Array.isArray(src.workspaces_queried) && src.workspac'
    'es_queried.length) {\n        wsExtra = " [" + src.workspaces_queried.map(function (w) {\n          re'
    'turn w.workspace_name + ": " + w.status + " (" + w.records + " filas)";\n        }).join(", ") + "]";'
    '\n      }\n      tbody.appendChild(\n        el("tr", null, [\n          el("td", { className: "mono", t'
    'extContent: src.id }),\n          el("td", null, [stBadge]),\n          el("td", { className: "mono", '
    'textContent: String(src.records || 0) }),\n          el("td", { className: "mono", textContent: Strin'
    'g(src.pages || 0) }),\n          el("td", { className: "mono", textContent: src.pagination_complete ?'
    ' "true" : "false" }),\n          el("td", { className: "mono", textContent: (src.read_signature || "—'
    '") + wsExtra }),\n          el("td", { textContent: src.note || "—" })\n        ])\n      );\n    });\n\n '
    '   var methList = document.getElementById("methodology-list");\n    clear(methList);\n    var meth = D'
    'ATA.methodology || {};\n    (meth.limitations || []).forEach(function (lim) {\n      methList.appendCh'
    'ild(el("li", { textContent: lim }));\n    });\n  }\n\n  function downloadBlob(filename, content, mime) {'
    '\n    var blob = new Blob([content], { type: mime });\n    var url = URL.createObjectURL(blob);\n    va'
    'r link = document.createElement("a");\n    link.href = url;\n    link.download = filename;\n    documen'
    't.body.appendChild(link);\n    link.click();\n    document.body.removeChild(link);\n    setTimeout(func'
    'tion () { URL.revokeObjectURL(url); }, 500);\n  }\n\n  function csvEscape(val) {\n    if (val === null |'
    '| val === undefined) {\n      return \'""\';\n    }\n    var str = typeof val === "object" ? JSON.stringi'
    'fy(val) : String(val);\n    if (/^[=+\\-@\\t\\r\\n]/.test(str.trimLeft())) {\n      str = "\'" + str;\n    }'
    '\n    return \'"\' + str.replace(/"/g, \'""\') + \'"\';\n  }\n\n  function exportIncidentsCsv() {\n    var head'
    'ers = ["record_kind", "id", "category", "severity", "title", "resource_name", "resource_group", "met'
    'ric_or_signal", "observed_value", "observed_at_utc", "summary"];\n    var lines = [headers.join(",")]'
    ';\n    (DATA.incidents || []).forEach(function (inc) {\n      lines.push([\n        "incident", inc.id,'
    ' inc.category, inc.severity, inc.title, inc.resource_name,\n        inc.resource_group, inc.signal_ty'
    'pe, inc.native_severity, inc.last_updated_utc, inc.summary\n      ].map(csvEscape).join(","));\n    })'
    ';\n    (DATA.anomalies || []).forEach(function (anom) {\n      lines.push([\n        "anomaly", anom.id'
    ', anom.category, anom.severity, anom.title, anom.resource_name,\n        anom.resource_group, anom.me'
    'tric_or_field, anom.observed_value, anom.observed_at_utc, anom.summary\n      ].map(csvEscape).join("'
    ',"));\n    });\n    downloadBlob("ops-digest-incidents-anomalies.csv", "\\uFEFF" + lines.join("\\r\\n"), '
    '"text/csv;charset=utf-8");\n  }\n\n  function exportActionsCsv() {\n    var headers = ["priority_rank", '
    '"id", "horizon_label", "severity", "category", "title", "resource_name", "resource_group", "owner_sc'
    'ope", "effort_label", "linked_evidence_ids", "recommendation"];\n    var lines = [headers.join(",")];'
    '\n    (DATA.actions || []).forEach(function (act) {\n      lines.push([\n        act.priority_rank, act'
    '.id, act.horizon_label, act.severity, act.category, act.title,\n        act.resource_name, act.resour'
    'ce_group, act.owner_scope, act.effort_label,\n        (act.linked_evidence_ids || []).join(";"), act.'
    'recommendation\n      ].map(csvEscape).join(","));\n    });\n    downloadBlob("ops-digest-recommended-a'
    'ctions.csv", "\\uFEFF" + lines.join("\\r\\n"), "text/csv;charset=utf-8");\n  }\n\n  // Event bindings\n  ["'
    'filter-category", "filter-severity", "filter-horizon"].forEach(function (id) {\n    document.getEleme'
    'ntById(id).addEventListener("change", renderTables);\n  });\n  document.getElementById("filter-search"'
    ').addEventListener("input", renderTables);\n  document.getElementById("filter-reset").addEventListene'
    'r("click", function () {\n    document.getElementById("filter-category").value = "all";\n    document.'
    'getElementById("filter-severity").value = "all";\n    document.getElementById("filter-horizon").value'
    ' = "all";\n    document.getElementById("filter-search").value = "";\n    renderTables();\n  });\n\n  docu'
    'ment.getElementById("theme-toggle").addEventListener("click", function () {\n    var htmlNode = docum'
    'ent.documentElement;\n    var next = htmlNode.getAttribute("data-theme") === "dark" ? "light" : "dark'
    '";\n    htmlNode.setAttribute("data-theme", next);\n    document.getElementById("theme-toggle").textCo'
    'ntent = next === "dark" ? "Modo claro" : "Modo oscuro";\n  });\n\n  document.getElementById("btn-export'
    '-json").addEventListener("click", function () {\n    downloadBlob("ops-digest-snapshot.json", JSON.st'
    'ringify(DATA, null, 2), "application/json;charset=utf-8");\n  });\n  document.getElementById("btn-expo'
    'rt-incidents-csv").addEventListener("click", exportIncidentsCsv);\n  document.getElementById("btn-exp'
    'ort-actions-csv").addEventListener("click", exportActionsCsv);\n  document.getElementById("btn-print"'
    ').addEventListener("click", function () {\n    window.print();\n  });\n\n  renderBranding();\n  renderExe'
    'cutive();\n  renderTables();\n  renderCoverage();\n})();\n</script>\n</body>\n</html>\n'
)
# END BUILD-TIME ASSETS


class EvidenceError(RuntimeError):
    def __init__(self, code, message, source="digest", http_status=None):
        super().__init__(message)
        self.code = code
        self.source = source
        self.http_status = http_status

    def public(self):
        result = {
            "code": self.code,
            "message": str(self),
            "source_id": self.source,
            "http_status": self.http_status,
        }
        return result


def utc_now():
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def parse_utc(value, source="normalization"):
    if not isinstance(value, str) or not value or len(value) > 48:
        raise EvidenceError("invalid_timestamp", "Expected an ISO 8601 UTC timestamp.", source)
    cleaned = value.strip()
    if cleaned.endswith("Z"):
        cleaned = cleaned[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(cleaned)
    except ValueError as exc:
        raise EvidenceError("invalid_timestamp", "Could not parse ISO 8601 timestamp.", source) from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EvidenceError("invalid_timestamp", "Timestamp must include an explicit timezone offset.", source)
    return parsed.astimezone(timezone.utc)


def iso_utc(dt):
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def obj(value, source="normalization"):
    if not isinstance(value, dict):
        raise EvidenceError("invalid_shape", "Expected a JSON object from source.", source)
    return value


def array(value, source="normalization"):
    if not isinstance(value, list) or any(not isinstance(row, dict) for row in value):
        raise EvidenceError("invalid_shape", "Expected a JSON array of objects from source.", source)
    return value


def pick(value, *keys):
    current = value
    for key in keys:
        if not isinstance(current, dict) or key not in current:
            return None
        current = current[key]
    return current


def text(value, source="normalization", maximum=8192):
    if value is None:
        return None
    if not isinstance(value, str) or len(value) > maximum or any(ord(ch) < 32 and ch not in ("\t", "\n", "\r") for ch in value):
        raise EvidenceError("invalid_field", "Source text field has an invalid type, control char, or length.", source)
    return value.strip()


def number(value, source="normalization"):
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        raise EvidenceError("invalid_field", "Source numeric value must be a finite number.", source)
    return float(value)


def boolean(value, source="normalization"):
    if value is not None and not isinstance(value, bool):
        raise EvidenceError("invalid_field", "Source boolean field has an invalid type.", source)
    return value


def tags_map(value, source="normalization"):
    if value is None:
        return {}
    raw_tags = obj(value, source)
    sanitized = {}
    for key, item in raw_tags.items():
        k = text(str(key), source, 256)
        if not k:
            continue
        if any(word in k.lower() for word in ("secret", "password", "token", "key", "sas", "credential", "connectionstring")):
            continue
        if isinstance(item, (str, int, float, bool)) or item is None:
            sanitized[k] = text(str(item), source, 512) if item is not None else None
    return sanitized


def validate_guid(value, field_name):
    try:
        if not isinstance(value, str) or str(UUID(value)) != value.lower() or UUID(value).int == 0:
            raise ValueError
    except (ValueError, AttributeError) as exc:
        raise EvidenceError(
            "configuration_required",
            "Configure the explicit GUID constant " + field_name + " before running live collection.",
            "configuration",
        ) from exc
    return value.lower()


def validate_logo(uri, alt=CLIENT_LOGO_ALT):
    if uri == "":
        return
    if not isinstance(uri, str) or len(uri) > 140_000:
        raise EvidenceError("invalid_logo", "Optional logo must be a bounded inline PNG/JPEG data URI.", "branding")
    match = re.fullmatch(r"data:image/(png|jpeg);base64,([A-Za-z0-9+/=]+)", uri)
    if not match:
        raise EvidenceError("invalid_logo", "Only inline PNG/JPEG MIME with canonical base64 is allowed.", "branding")
    try:
        data = base64.b64decode(match[2], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise EvidenceError("invalid_logo", "Invalid logo base64 payload.", "branding") from exc
    if not 1 <= len(data) <= MAX_LOGO_BYTES:
        raise EvidenceError("invalid_logo", "Optional raster logo must contain 1..100000 bytes.", "branding")
    if not isinstance(alt, str) or not alt.strip() or len(alt) > 120 or re.search(r"[\x00-\x1f\x7f]", alt):
        raise EvidenceError("invalid_logo", "Provide 1..120 plain characters of descriptive logo alt text.", "branding")
    try:
        from PIL import Image, ImageFile, UnidentifiedImageError
    except ImportError as exc:
        raise EvidenceError("dependency_missing", "A configured logo requires Pillow for raster validation.", "branding") from exc
    if ImageFile.LOAD_TRUNCATED_IMAGES:
        raise EvidenceError("unsafe_decoder_settings", "Truncated-image decoding must not be enabled.", "branding")
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("error", Image.DecompressionBombWarning)
            with Image.open(io.BytesIO(data), formats=["PNG", "JPEG"]) as image:
                width, height = image.size
                if (
                    image.format != ("PNG" if match[1] == "png" else "JPEG")
                    or not 1 <= width <= MAX_LOGO_DIMENSION
                    or not 1 <= height <= MAX_LOGO_DIMENSION
                    or getattr(image, "n_frames", 1) != 1
                ):
                    raise EvidenceError("invalid_logo", "Use one PNG/JPEG frame, matching MIME, at most 2048x2048 pixels.", "branding")
                image.verify()
            with Image.open(io.BytesIO(data), formats=["PNG", "JPEG"]) as image:
                image.load()
    except (OSError, ValueError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError, Image.DecompressionBombWarning) as exc:
        raise EvidenceError("invalid_logo", "The optional logo is not a complete, valid single-frame PNG/JPEG raster.", "branding") from exc


def validate_config():
    validate_logo(CLIENT_LOGO_DATA_URI, CLIENT_LOGO_ALT)
    if not isinstance(CLIENT_NAME, str) or not 1 <= len(CLIENT_NAME.strip()) <= 120 or re.search(r"[\x00-\x1f\x7f]", CLIENT_NAME):
        raise EvidenceError("configuration_required", "CLIENT_NAME must be 1..120 plain characters.", "configuration")
    if not isinstance(CLIENT_LOGO_ALT, str) or not 1 <= len(CLIENT_LOGO_ALT.strip()) <= 120 or re.search(r"[\x00-\x1f\x7f]", CLIENT_LOGO_ALT):
        raise EvidenceError("configuration_required", "CLIENT_LOGO_ALT must be 1..120 plain characters.", "configuration")
    sub_id = validate_guid(SUBSCRIPTION_ID, "SUBSCRIPTION_ID")
    client_id = validate_guid(MANAGED_IDENTITY_CLIENT_ID, "MANAGED_IDENTITY_CLIENT_ID")
    if not isinstance(APPROVED_LOG_WORKSPACES, list) or len(APPROVED_LOG_WORKSPACES) > MAX_WORKSPACES:
        raise EvidenceError("configuration_required", "Configure 0..10 entries in APPROVED_LOG_WORKSPACES.", "configuration")
    workspaces = []
    seen_names = set()
    seen_ids = set()
    for item in APPROVED_LOG_WORKSPACES:
        if not isinstance(item, dict):
            raise EvidenceError("configuration_required", "Each APPROVED_LOG_WORKSPACES entry must be a dict.", "configuration")
        w_name = item.get("name")
        w_rg = item.get("resource_group")
        if not isinstance(w_name, str) or not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", w_name):
            raise EvidenceError("configuration_required", "Configure a valid workspace name in APPROVED_LOG_WORKSPACES.", "configuration")
        if not isinstance(w_rg, str) or not re.fullmatch(r"[A-Za-z0-9_.()-]{1,90}", w_rg):
            raise EvidenceError("configuration_required", "Configure a valid resource_group in APPROVED_LOG_WORKSPACES.", "configuration")
        w_guid = validate_guid(item.get("customer_id"), "APPROVED_LOG_WORKSPACES.customer_id")
        if w_name.lower() in seen_names or w_guid in seen_ids:
            raise EvidenceError("configuration_required", "Duplicate workspace name or customer_id in APPROVED_LOG_WORKSPACES.", "configuration")
        seen_names.add(w_name.lower())
        seen_ids.add(w_guid)
        workspaces.append({
            "name": w_name,
            "customer_id": w_guid,
            "resource_group": w_rg,
        })
    return {
        "subscription_id": sub_id,
        "client_id": client_id,
        "workspaces": workspaces,
        "client_name": CLIENT_NAME.strip(),
    }


def compute_window(period, reference_str):
    ref_dt = parse_utc(reference_str, "parameters")
    if period == "previous_month":
        end_dt = ref_dt.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        start_dt = (end_dt - timedelta(days=1)).replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        label = "Mes natural anterior (" + start_dt.strftime("%Y-%m") + ")"
        cadence = "Ejecución mensual programada (30 8 1 * * UTC) / mes cerrado"
        grain = "PT1H"
    elif period == "last_30d":
        end_dt = ref_dt.replace(microsecond=0)
        start_dt = end_dt - timedelta(days=30)
        label = "Últimos 30 días móviles"
        cadence = "Bajo demanda (ventana móvil de 30 días)"
        grain = "PT1H"
    elif period == "last_7d":
        end_dt = ref_dt.replace(microsecond=0)
        start_dt = end_dt - timedelta(days=7)
        label = "Últimos 7 días móviles"
        cadence = "Bajo demanda (ventana semanal móvil de 7 días)"
        grain = "PT1H"
    elif period == "last_24h":
        end_dt = ref_dt.replace(microsecond=0)
        start_dt = end_dt - timedelta(hours=24)
        label = "Últimas 24 horas"
        cadence = "Bajo demanda (guardia operativa 24h)"
        grain = "PT5M"
    else:
        raise EvidenceError("invalid_parameter", "period must use its declared enum.", "parameters")
    start_iso = iso_utc(start_dt)
    end_iso = iso_utc(end_dt)
    duration_hours = max(1, int(round((end_dt - start_dt).total_seconds() / 3600.0)))
    return {
        "period": period,
        "label": label,
        "cadence": cadence,
        "start_utc": start_iso,
        "end_utc": end_iso,
        "timespan_iso": start_iso + "/" + end_iso,
        "grain": grain,
        "duration_hours": duration_hours,
    }


def validate_parameters(
    operation="report",
    period="previous_month",
    view="summary",
    category="all",
    severity="all",
    resource_name="",
    limit=25,
    offset=0,
    reference_utc=None,
):
    for key, value, choices in (
        ("operation", operation, OPERATIONS),
        ("period", period, PERIODS),
        ("view", view, VIEWS),
        ("category", category, CATEGORIES),
        ("severity", severity, SEVERITIES),
    ):
        if not isinstance(value, str) or value not in choices:
            raise EvidenceError("invalid_parameter", key + " must use its declared enum.", "parameters")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 100:
        raise EvidenceError("invalid_parameter", "limit must be an integer from 1 to 100.", "parameters")
    if isinstance(offset, bool) or not isinstance(offset, int) or not 0 <= offset <= 500_000:
        raise EvidenceError("invalid_parameter", "offset must be an integer from 0 to 500000.", "parameters")
    if not isinstance(resource_name, str) or len(resource_name) > 128 or (
        resource_name and not re.fullmatch(r"[A-Za-z0-9_.-]{1,128}", resource_name)
    ):
        raise EvidenceError(
            "invalid_parameter",
            "resource_name must be a bounded resource name (^[A-Za-z0-9_.-]{0,128}$), never a path, URL, or query.",
            "parameters",
        )
    has_filters = any((view != "summary", category != "all", severity != "all", bool(resource_name), limit != 25, offset != 0))
    if operation == "report" and has_filters:
        raise EvidenceError(
            "invalid_combination",
            "operation=report writes complete unfiltered evidence for the requested period; use defaults for view/category/severity/resource_name/limit/offset.",
            "parameters",
        )
    if operation == "query":
        if view in ("summary", "coverage") and any((category != "all", severity != "all", bool(resource_name))):
            raise EvidenceError(
                "invalid_combination",
                "summary and coverage views do not accept category, severity, or resource_name filters.",
                "parameters",
            )
        if view == "resources" and category != "all":
            raise EvidenceError(
                "invalid_combination",
                "view=resources aggregates across categories; use category=all.",
                "parameters",
            )
        if view == "incidents" and category not in ("all", "native_alert", "service_health"):
            raise EvidenceError(
                "invalid_combination",
                "view=incidents supports category in ('all', 'native_alert', 'service_health').",
                "parameters",
            )
        if view == "anomalies" and category not in ("all", "extension_failure", "connectivity_posture", "telemetry_anomaly"):
            raise EvidenceError(
                "invalid_combination",
                "view=anomalies supports category in ('all', 'extension_failure', 'connectivity_posture', 'telemetry_anomaly').",
                "parameters",
            )
        if view == "advisor" and category not in ("all", "advisor_recommendation"):
            raise EvidenceError(
                "invalid_combination",
                "view=advisor supports category in ('all', 'advisor_recommendation').",
                "parameters",
            )
    ref = reference_utc or utc_now()
    window = compute_window(period, ref)
    return {
        "operation": operation,
        "period": period,
        "view": view,
        "category": category,
        "severity": severity,
        "resource_name": resource_name,
        "limit": limit,
        "offset": offset,
        "window": window,
    }


def response_bytes(value):
    return len(json.dumps(value, allow_nan=False).encode("utf-8"))


def ensure_response(value):
    if response_bytes(value) > TRANSPORT_BYTES:
        raise EvidenceError(
            "transport_size_exceeded",
            "Default-serialized response exceeds 3500 bytes; no malformed or truncated JSON is returned.",
            "transport",
        )
    return value


def arm_resource_id(value, subscription_id=None, source="scope"):
    raw = text(value, source, 2048)
    if not raw:
        raise EvidenceError("invalid_resource_id", "A scoped ARM resource ID is required.", source)
    if re.search(r"[\x00-\x1f\x7f?#\\%]", raw):
        raise EvidenceError("invalid_resource_id", "Resource ID contains unsafe characters.", source)
    cleaned = raw.rstrip("/")
    parts = cleaned.split("/")
    if (
        len(parts) < 5
        or parts[0] != ""
        or parts[1].lower() != "subscriptions"
        or any(part in ("", ".", "..") for part in parts[1:])
    ):
        raise EvidenceError("invalid_resource_id", "Resource ID has invalid ARM path structure.", source)
    try:
        sub_guid = str(UUID(parts[2])).lower()
    except ValueError as exc:
        raise EvidenceError("invalid_resource_id", "Resource ID subscription is not a valid GUID.", source) from exc
    if subscription_id and sub_guid != subscription_id.lower():
        raise EvidenceError("invalid_resource_id", "Resource ID belongs to a different subscription.", source)
    return cleaned


def extract_rg_and_type(resource_id):
    if not isinstance(resource_id, str) or not resource_id.startswith("/"):
        return "subscription-scope", "microsoft.resources/subscriptions", resource_id or "subscription"
    parts = resource_id.rstrip("/").split("/")
    rg = "subscription-scope"
    if len(parts) >= 5 and parts[3].lower() == "resourcegroups":
        rg = parts[4]
    if "providers" in [p.lower() for p in parts]:
        idx = [p.lower() for p in parts].index("providers")
        if idx + 2 < len(parts):
            provider = parts[idx + 1]
            type_segments = parts[idx + 2::2]
            rtype = (provider + "/" + "/".join(type_segments)).lower()
            rname = parts[-1]
            return rg, rtype, rname
    return rg, "microsoft.resources/resource", parts[-1]


def source_receipt(source_id, reference, status="complete", note="", window=None, **extra):
    return {
        "id": source_id,
        "status": status,
        "time": reference,
        "records": 0,
        "pages": 0,
        "pagination_complete": status == "complete",
        "errors": [],
        "note": note,
        "window": window,
        **extra,
    }


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def verify_jwt_claims(token_str, expected_client, expected_aud):
    try:
        encoded = token_str.split(".")[1]
        claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    except (AttributeError, IndexError, ValueError, binascii.Error) as exc:
        raise EvidenceError("authentication_failed", "Identity provider returned an unreadable JWT.", "identity") from exc
    tenant = pick(claims, "tid")
    client = pick(claims, "appid") or pick(claims, "azp")
    aud = pick(claims, "aud")
    try:
        valid_tid = isinstance(tenant, str) and str(UUID(tenant)) == tenant.lower() and UUID(tenant).int != 0
    except ValueError:
        valid_tid = False
    expected_norm = expected_aud.rstrip("/").lower()
    aud_norm = aud.rstrip("/").lower() if isinstance(aud, str) else ""
    if expected_norm == ARM_ORIGIN.lower():
        aud_valid = aud_norm in ARM_TOKEN_AUDIENCES
    elif expected_norm == LOGS_ORIGIN.lower():
        aud_valid = aud_norm in LOGS_TOKEN_AUDIENCES
    else:
        aud_valid = aud_norm == expected_norm
    if not (valid_tid and isinstance(client, str) and client.lower() == expected_client.lower() and aud_valid):
        raise EvidenceError("identity_mismatch", "Token client identity or audience differs from the fixed configuration.", "identity")
    return claims


class Identity:
    def __init__(self, config):
        try:
            from azure.identity import ManagedIdentityCredential
        except ImportError as exc:
            raise EvidenceError("dependency_missing", "Live reads require azure-identity; no fallback credential is permitted.", "identity") from exc
        self.config = config
        self.credential = ManagedIdentityCredential(client_id=config["client_id"])
        self.deadline = time.monotonic() + MAX_COLLECTION_SECONDS
        self.request_count = 0
        self.cached_tokens = {}

    def guard_budget(self):
        if time.monotonic() >= self.deadline:
            raise EvidenceError("collection_deadline", "Collection time bound reached; remaining reads are marked incomplete.", "collection")
        if self.request_count >= MAX_HTTP_ATTEMPTS:
            raise EvidenceError("request_cap", "Collection HTTP request bound reached.", "collection")
        self.request_count += 1

    def token(self, origin):
        from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError
        from azure.identity import CredentialUnavailableError

        cached = self.cached_tokens.get(origin)
        if cached is not None and cached[1] > time.time() + 60:
            return cached[0]
        self.guard_budget()
        scope = origin.rstrip("/") + "/.default"
        try:
            tok = self.credential.get_token(scope)
        except (ClientAuthenticationError, CredentialUnavailableError, ServiceRequestError) as exc:
            raise EvidenceError("authentication_failed", "The configured managed identity could not acquire a token.", "identity") from exc
        verify_jwt_claims(tok.token, self.config["client_id"], origin)
        self.cached_tokens[origin] = (tok.token, getattr(tok, "expires_on", time.time() + 300))
        return tok.token

    def arm_token(self):
        return self.token(ARM_ORIGIN)

    def logs_token(self):
        return self.token(LOGS_ORIGIN)

    def close(self):
        self.credential.close()


class HttpReader:
    def __init__(self, identity, origin=ARM_ORIGIN, token_kind="arm"):
        self.identity = identity
        self.origin = origin
        self.token_kind = token_kind
        self.context = ssl.create_default_context()
        if self.context.verify_mode != ssl.CERT_REQUIRED or not self.context.check_hostname:
            raise EvidenceError("unsafe_tls", "TLS certificate and hostname verification are mandatory.", "tls")
        self.opener = build_opener(NoRedirect(), HTTPSHandler(context=self.context))
        self.allowed = set()

    def allow(self, url, method="GET"):
        parsed = urlsplit(url)
        if (
            parsed.scheme != "https"
            or (parsed.scheme + "://" + parsed.netloc.lower()) != self.origin.lower()
            or parsed.fragment
            or parsed.username
            or parsed.password
            or "\\" in parsed.path
            or any(part in (".", "..") for part in unquote(parsed.path).split("/"))
        ):
            raise EvidenceError("unsafe_endpoint", "Read URL changed the fixed HTTPS origin or path safety rules.", "scope")
        if method not in ("GET", "POST"):
            raise EvidenceError("unsafe_method", "Only read-only GET and POST queries (ARG / Log Analytics) are permitted.", "scope")
        lowered = parsed.path.lower()
        if any(forbidden in lowered for forbidden in ("/write", "/delete", "/action", "/runcommand", "/listkeys", "/secrets")):
            raise EvidenceError("unsafe_endpoint", "Write actions, command execution, and secret reads are forbidden.", "scope")
        if method == "POST" and not (
            lowered == "/providers/microsoft.resourcegraph/resources"
            or re.fullmatch(r"/v1/workspaces/[0-9a-f-]{36}/query", lowered)
        ):
            raise EvidenceError("unsafe_method", "POST is restricted to Azure Resource Graph and Log Analytics query endpoints.", "scope")
        self.allowed.add((method, parsed.path))
        return url

    def _bearer(self):
        return self.identity.arm_token() if self.token_kind == "arm" else self.identity.logs_token()

    def request(self, method, url, source, body=None):
        parsed = urlsplit(url)
        if (
            (parsed.scheme + "://" + parsed.netloc.lower()) != self.origin.lower()
            or parsed.fragment
            or parsed.username
            or parsed.password
            or len(url) > 16384
            or (method, parsed.path) not in self.allowed
        ):
            raise EvidenceError("unsafe_endpoint", "Request was not registered in the scoped read allowlist.", source)
        payload = None if body is None else json.dumps(body, allow_nan=False).encode("utf-8")
        for attempt in range(3):
            bearer = self._bearer()
            self.identity.guard_budget()
            headers = {
                "Authorization": "Bearer " + bearer,
                "Accept": "application/json",
                "Content-Type": "application/json",
            }
            if self.token_kind == "logs":
                headers["Prefer"] = "wait=90"
            req = Request(url, data=payload, method=method, headers=headers)
            try:
                with self.opener.open(req, timeout=30) as response:
                    if response.status != 200:
                        raise EvidenceError("http_error", "Read returned HTTP " + str(response.status) + ".", source, response.status)
                    raw = response.read(HTTP_BYTES + 1)
                    if len(raw) > HTTP_BYTES:
                        raise EvidenceError("response_cap", "Response exceeded the byte safety cap.", source)
            except HTTPError as exc:
                if exc.code in (429, 500, 502, 503, 504) and attempt < 2:
                    retry = exc.headers.get("Retry-After", "") if exc.headers else ""
                    time.sleep(min(int(retry), 4) if re.fullmatch(r"[0-9]{1,4}", retry) else attempt + 1)
                    continue
                raise EvidenceError(
                    "access_denied" if exc.code in (401, 403) else "http_error",
                    "Read returned HTTP " + str(exc.code) + "; raw error bodies are excluded.",
                    source,
                    exc.code,
                ) from exc
            except (URLError, TimeoutError, ssl.SSLError, OSError) as exc:
                reason = getattr(exc, "reason", exc)
                code = "tls_failed" if isinstance(reason, ssl.SSLError) else "transport_failed"
                raise EvidenceError(code, "Transport or TLS error during read-only request.", source) from exc
            try:
                decoded = json.loads(raw)
                return obj(decoded, source)
            except (ValueError, UnicodeDecodeError) as exc:
                raise EvidenceError("invalid_json", "Source returned malformed JSON.", source) from exc
        raise EvidenceError("http_error", "Bounded HTTP retries exhausted.", source)


def next_arm_link(link, initial):
    if not isinstance(link, str) or not link or len(link) > 16384:
        raise EvidenceError("invalid_pagination", "Invalid ARM continuation link.", "pagination")
    current, first = urlsplit(link), urlsplit(initial)
    if (
        current.scheme != "https"
        or current.netloc.lower() != first.netloc.lower()
        or unquote(current.path) != unquote(first.path)
        or current.fragment
        or current.username
        or current.password
        or "\\" in current.path
    ):
        raise EvidenceError("invalid_pagination", "ARM continuation changed origin or path.", "pagination")
    try:
        pairs = parse_qsl(current.query, keep_blank_values=True, strict_parsing=True)
        original = dict(parse_qsl(first.query, keep_blank_values=True, strict_parsing=True))
    except ValueError as exc:
        raise EvidenceError("invalid_pagination", "Malformed continuation query parameters.", "pagination") from exc
    values = dict(pairs)
    paging = {"$skiptoken", "skiptoken", "$skipToken", "skipToken", "$skip", "$top"}
    if len(values) != len(pairs) or any(key not in original and key not in paging for key in values):
        raise EvidenceError("invalid_pagination", "ARM continuation added an unapproved query parameter.", "pagination")
    if any(values.get(key) != value for key, value in original.items() if key not in paging):
        raise EvidenceError("invalid_pagination", "ARM continuation modified api-version or scope filter.", "pagination")
    return link


def arg_alerts_query():
    return (
        "alertsmanagementresources "
        "| where type =~ 'microsoft.alertsmanagement/alerts' "
        "| extend ess = properties.essentials "
        "| project id, name, "
        "severity=tostring(ess.severity), "
        "alertState=tostring(ess.alertState), "
        "monitorCondition=tostring(ess.monitorCondition), "
        "signalType=tostring(ess.signalType), "
        "monitorService=tostring(ess.monitorService), "
        "targetResource=tostring(ess.targetResource), "
        "targetResourceName=tostring(ess.targetResourceName), "
        "targetResourceGroup=tostring(ess.targetResourceGroup), "
        "targetResourceType=tostring(ess.targetResourceType), "
        "startDateTime=tostring(ess.startDateTime), "
        "lastModifiedDateTime=tostring(ess.lastModifiedDateTime), "
        "resolvedDateTime=tostring(ess.monitorConditionResolvedDateTime), "
        "description=tostring(ess.description) "
        "| order by startDateTime desc, id asc"
    )


def arg_inventory_query():
    types_literal = ", ".join("'" + t + "'" for t in ESTATE_RESOURCE_TYPES)
    return (
        "resources "
        "| where type in~ (" + types_literal + ") "
        "| project id, name, type, resourceGroup, location, skuName=tostring(sku.name), tags, "
        "provisioningState=tostring(properties.provisioningState), "
        "arcStatus=tostring(properties.status), "
        "arcAgentVersion=tostring(properties.agentVersion), "
        "arcLastStatusChange=tostring(properties.lastStatusChange), "
        "osName=tostring(coalesce(properties.osName, properties.storageProfile.osDisk.osType)), "
        "osSku=tostring(properties.osSku), "
        "osVersion=tostring(properties.osVersion), "
        "vmSize=tostring(properties.hardwareProfile.vmSize), "
        "powerState=tostring(coalesce(properties.extended.instanceView.powerState.code, properties.powerState.code)), "
        "kubernetesVersion=tostring(properties.kubernetesVersion), "
        "runningState=tostring(coalesce(properties.runningStatus, properties.state)) "
        "| order by id asc"
    )


def arg_extensions_query():
    types_literal = ", ".join("'" + t + "'" for t in EXTENSION_RESOURCE_TYPES)
    return (
        "resources "
        "| where type in~ (" + types_literal + ") "
        "| project id, name, type, resourceGroup, location, "
        "publisher=tostring(properties.publisher), "
        "extType=tostring(properties.type), "
        "version=tostring(coalesce(properties.typeHandlerVersion, properties.instanceView.typeHandlerVersion)), "
        "provisioningState=tostring(properties.provisioningState), "
        "enableAutomaticUpgrade=properties.enableAutomaticUpgrade, "
        "autoUpgradeMinorVersion=properties.autoUpgradeMinorVersion "
        "| order by id asc"
    )


def read_arg_query(reader, subscription_id, query, source_id, reference, window, normalize_fn):
    url = ARM_ORIGIN + "/providers/Microsoft.ResourceGraph/resources?api-version=" + ARG_API_VERSION
    reader.allow(url, "POST")
    receipt = source_receipt(
        source_id,
        reference,
        window=window,
        page_cap=MAX_PAGES,
        row_cap=MAX_ROWS,
        pagination_complete=False,
        read_signature="POST " + url,
    )
    rows = []
    seen_ids = set()
    seen_tokens = set()
    skip_token = None
    try:
        for page_num in range(1, MAX_PAGES + 1):
            options = {"$top": 1000, "resultFormat": "objectArray"}
            if skip_token is not None:
                options["$skipToken"] = skip_token
            body = {
                "subscriptions": [subscription_id],
                "query": query,
                "options": options,
            }
            payload = reader.request("POST", url, source_id, body=body)
            receipt["pages"] = page_num
            data = array(payload.get("data", []), source_id)
            if len(rows) + len(data) > MAX_ROWS:
                raise EvidenceError("row_cap", "Resource Graph row safety cap reached.", source_id)
            for raw in data:
                normalized = normalize_fn(raw)
                if normalized is None:
                    continue
                row_id = str(normalized.get("id") or normalized.get("resource_id") or "").lower()
                if not row_id or row_id in seen_ids:
                    raise EvidenceError("invalid_pagination", "Resource Graph row ID is missing or duplicated.", source_id)
                seen_ids.add(row_id)
                rows.append(normalized)
            receipt["records"] = len(rows)
            next_token = payload.get("$skipToken")
            if not next_token:
                receipt["pagination_complete"] = True
                return rows, receipt
            next_token = text(next_token, source_id, 8192)
            if not next_token or next_token in seen_tokens:
                raise EvidenceError("pagination_loop", "Resource Graph repeated or emptied $skipToken.", source_id)
            seen_tokens.add(next_token)
            skip_token = next_token
        raise EvidenceError("page_cap", "Resource Graph page cap reached.", source_id)
    except EvidenceError as exc:
        receipt["status"] = "partial" if rows else "denied" if exc.http_status in (401, 403) else "error"
        receipt["records"] = len(rows)
        receipt["errors"].append(exc.public())
        return rows, receipt


def read_arm_pages(reader, url, source_id, reference, window, normalize_fn):
    reader.allow(url, "GET")
    receipt = source_receipt(
        source_id,
        reference,
        window=window,
        page_cap=MAX_PAGES,
        row_cap=MAX_ROWS,
        pagination_complete=False,
        read_signature="GET " + url,
    )
    rows = []
    seen_ids = set()
    seen_pages = set()
    current = url
    try:
        for page_num in range(1, MAX_PAGES + 1):
            if current in seen_pages:
                raise EvidenceError("pagination_loop", "ARM pagination repeated a page URL.", source_id)
            seen_pages.add(current)
            payload = reader.request("GET", current, source_id)
            receipt["pages"] = page_num
            page = array(payload.get("value", []), source_id)
            if len(rows) + len(page) > MAX_ROWS:
                raise EvidenceError("row_cap", "ARM list row safety cap reached.", source_id)
            for raw in page:
                normalized = normalize_fn(raw)
                if normalized is None:
                    continue
                row_id = str(normalized.get("id") or "").lower()
                if not row_id or row_id in seen_ids:
                    raise EvidenceError("invalid_pagination", "ARM row identity is missing or repeated.", source_id)
                seen_ids.add(row_id)
                rows.append(normalized)
            receipt["records"] = len(rows)
            continuation = payload.get("nextLink")
            if not continuation:
                receipt["pagination_complete"] = True
                return rows, receipt
            current = next_arm_link(continuation, url)
        raise EvidenceError("page_cap", "ARM list page cap reached.", source_id)
    except EvidenceError as exc:
        receipt["status"] = "partial" if rows else "denied" if exc.http_status in (401, 403) else "error"
        receipt["records"] = len(rows)
        receipt["errors"].append(exc.public())
        return rows, receipt


def map_alert_severity(sev_str):
    mapping = {
        "sev0": "critical",
        "sev1": "high",
        "sev2": "medium",
        "sev3": "low",
        "sev4": "low",
    }
    return mapping.get((sev_str or "").strip().lower(), "medium")


def normalize_alert_row(raw, subscription_id, window, reference):
    source_id = "arg_alerts_incidents"
    alert_id = text(raw.get("id"), source_id, 2048)
    name = text(raw.get("name"), source_id, 256) or (alert_id.split("/")[-1] if alert_id else None)
    if not alert_id or not name:
        raise EvidenceError("invalid_alert", "Alert row is missing id or name.", source_id)
    native_sev = text(raw.get("severity"), source_id, 32) or "Sev2"
    sev = map_alert_severity(native_sev)
    alert_state = text(raw.get("alertState"), source_id, 64) or "New"
    monitor_cond = text(raw.get("monitorCondition"), source_id, 64) or "Fired"
    signal_type = text(raw.get("signalType"), source_id, 64) or "Metric"
    monitor_service = text(raw.get("monitorService"), source_id, 128) or "Platform"
    target_res = text(raw.get("targetResource"), source_id, 2048)
    if target_res and target_res.lower().startswith("/subscriptions/"):
        target_res = arm_resource_id(target_res, subscription_id, source_id)
    rg, rtype, inferred_name = extract_rg_and_type(target_res or "")
    target_name = text(raw.get("targetResourceName"), source_id, 256) or inferred_name
    target_rg = text(raw.get("targetResourceGroup"), source_id, 128) or rg
    target_type = (text(raw.get("targetResourceType"), source_id, 180) or rtype).lower()
    start_str = text(raw.get("startDateTime"), source_id, 64)
    mod_str = text(raw.get("lastModifiedDateTime"), source_id, 64) or start_str or reference
    res_str = text(raw.get("resolvedDateTime"), source_id, 64)
    start_dt = parse_utc(start_str, source_id) if start_str else parse_utc(mod_str, source_id)
    mod_dt = parse_utc(mod_str, source_id)
    w_start = parse_utc(window["start_utc"], source_id)
    w_end = parse_utc(window["end_utc"], source_id)
    is_active = monitor_cond.lower() == "fired" or alert_state.lower() in ("new", "acknowledged")
    in_window = (w_start <= start_dt <= w_end) or (w_start <= mod_dt <= w_end) or is_active
    if not in_window:
        return None
    desc = text(raw.get("description"), source_id, 2048) or (
        "Alerta nativa " + native_sev + " (" + monitor_cond + " / " + alert_state + ") en " + target_name + "."
    )
    short_hash = hashlib.sha256(alert_id.lower().encode("utf-8")).hexdigest()[:10]
    return {
        "id": "INC-ALR-" + short_hash,
        "native_id": alert_id,
        "record_kind": "incident",
        "category": "native_alert",
        "category_label": CATEGORY_LABELS["native_alert"],
        "severity": sev,
        "severity_label": SEVERITY_LABELS[sev],
        "native_severity": native_sev,
        "state": alert_state,
        "monitor_condition": monitor_cond,
        "title": "Alerta " + native_sev + " (" + monitor_service + "): " + target_name,
        "signal_type": signal_type,
        "monitor_service": monitor_service,
        "resource_id": target_res or ("/subscriptions/" + subscription_id),
        "resource_name": target_name,
        "resource_group": target_rg,
        "resource_type": target_type,
        "start_time_utc": iso_utc(start_dt),
        "last_updated_utc": iso_utc(mod_dt),
        "resolved_time_utc": iso_utc(parse_utc(res_str, source_id)) if res_str else None,
        "observed_at_utc": reference,
        "source_id": source_id,
        "summary": desc,
        "learn_url": "https://learn.microsoft.com/azure/azure-monitor/alerts/alerts-overview",
    }


def normalize_service_health_row(raw, subscription_id, window, reference):
    source_id = "arm_service_health"
    event_id = text(raw.get("id"), source_id, 2048)
    tracking_id = text(raw.get("name"), source_id, 128)
    if not event_id or not tracking_id or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", tracking_id):
        raise EvidenceError("invalid_service_health", "Service Health event is missing a valid tracking ID.", source_id)
    props = obj(raw.get("properties", {}), source_id)
    event_type = text(props.get("eventType"), source_id, 64)
    if event_type not in ("ServiceIssue", "PlannedMaintenance"):
        return None
    status = text(props.get("status"), source_id, 64) or "Active"
    title = text(props.get("title"), source_id, 512) or ("Evento " + event_type + " (" + tracking_id + ")")
    level = (text(props.get("level"), source_id, 64) or "").lower()
    if event_type == "ServiceIssue":
        sev = "critical" if level == "critical" else "high"
    else:
        sev = "medium"
    start_str = text(props.get("impactStartTime"), source_id, 64) or text(props.get("lastUpdateTime"), source_id, 64) or reference
    update_str = text(props.get("lastUpdateTime"), source_id, 64) or start_str
    mitigation_str = text(props.get("impactMitigationTime"), source_id, 64)
    start_dt = parse_utc(start_str, source_id)
    update_dt = parse_utc(update_str, source_id)
    w_start = parse_utc(window["start_utc"], source_id)
    w_end = parse_utc(window["end_utc"], source_id)
    in_window = (w_start <= start_dt <= w_end) or (w_start <= update_dt <= w_end) or status.lower() == "active"
    if not in_window:
        return None
    impacts = props.get("impact") if isinstance(props.get("impact"), list) else []
    services = []
    regions = []
    for imp in impacts:
        if isinstance(imp, dict):
            svc = text(imp.get("impactedService"), source_id, 128)
            if svc and svc not in services:
                services.append(svc)
            reg_list = imp.get("impactedRegions") if isinstance(imp.get("impactedRegions"), list) else []
            for reg in reg_list:
                if isinstance(reg, dict):
                    rname = text(reg.get("impactedRegion"), source_id, 64)
                    if rname and rname not in regions:
                        regions.append(rname)
    service_label = ", ".join(services) if services else "Azure Platform"
    region_label = ", ".join(regions) if regions else "Global"
    summary_text = text(props.get("summary"), source_id, 2048) or (
        event_type + " " + tracking_id + " (" + status + ") en " + service_label + " [" + region_label + "]."
    )
    return {
        "id": "INC-SH-" + tracking_id,
        "native_id": event_id,
        "tracking_id": tracking_id,
        "record_kind": "incident",
        "category": "service_health",
        "category_label": CATEGORY_LABELS["service_health"],
        "severity": sev,
        "severity_label": SEVERITY_LABELS[sev],
        "native_severity": event_type,
        "state": status,
        "monitor_condition": status,
        "title": title,
        "signal_type": event_type,
        "monitor_service": service_label,
        "regions": regions,
        "resource_id": "/subscriptions/" + subscription_id,
        "resource_name": service_label,
        "resource_group": "subscription-scope",
        "resource_type": "microsoft.resourcehealth/events",
        "start_time_utc": iso_utc(start_dt),
        "last_updated_utc": iso_utc(update_dt),
        "resolved_time_utc": iso_utc(parse_utc(mitigation_str, source_id)) if mitigation_str else None,
        "observed_at_utc": reference,
        "source_id": source_id,
        "summary": summary_text,
        "learn_url": "https://learn.microsoft.com/azure/service-health/service-health-overview",
    }


def normalize_estate_resource(raw, subscription_id, reference):
    source_id = "arg_posture_anomalies"
    res_id = arm_resource_id(raw.get("id"), subscription_id, source_id)
    name = text(raw.get("name"), source_id, 256)
    rtype = (text(raw.get("type"), source_id, 180) or "").lower()
    rg = text(raw.get("resourceGroup"), source_id, 128)
    location = text(raw.get("location"), source_id, 64)
    if not name or not rtype or not rg or not location or rtype not in ESTATE_RESOURCE_TYPES:
        raise EvidenceError("invalid_inventory", "Inventory row is missing required identity fields.", source_id)
    hosting = "arc" if rtype in ("microsoft.hybridcompute/machines", "microsoft.kubernetes/connectedclusters") else "azure"
    prov_state = text(raw.get("provisioningState"), source_id, 64) or "Succeeded"
    arc_status = text(raw.get("arcStatus"), source_id, 64)
    arc_version = text(raw.get("arcAgentVersion"), source_id, 64)
    arc_last_change = text(raw.get("arcLastStatusChange"), source_id, 64)
    if arc_last_change:
        arc_last_change = iso_utc(parse_utc(arc_last_change, source_id))
    power_state = text(raw.get("powerState"), source_id, 64)
    running_state = text(raw.get("runningState"), source_id, 64)
    op_state = arc_status or power_state or running_state or prov_state
    return {
        "id": res_id,
        "resource_id": res_id,
        "name": name,
        "resource_name": name,
        "resource_group": rg,
        "resource_type": rtype,
        "location": location,
        "hosting": hosting,
        "sku": text(raw.get("skuName"), source_id, 64),
        "provisioning_state": prov_state,
        "operational_state": op_state,
        "arc_status": arc_status,
        "arc_agent_version": arc_version,
        "arc_last_status_change_utc": arc_last_change,
        "os_name": text(raw.get("osName"), source_id, 128),
        "os_sku": text(raw.get("osSku"), source_id, 128),
        "os_version": text(raw.get("osVersion"), source_id, 64),
        "vm_size": text(raw.get("vmSize"), source_id, 64),
        "power_state": power_state,
        "kubernetes_version": text(raw.get("kubernetesVersion"), source_id, 64),
        "tags": tags_map(raw.get("tags"), source_id),
        "observed_at_utc": reference,
        "source_id": source_id,
    }


def normalize_extension_row(raw, subscription_id, reference):
    source_id = "arg_guest_extensions"
    ext_id = arm_resource_id(raw.get("id"), subscription_id, source_id)
    parts = ext_id.split("/")
    if len(parts) < 11 or parts[9].lower() != "extensions":
        raise EvidenceError("invalid_extension", "Extension ID is not a valid child resource ID.", source_id)
    parent_id = "/".join(parts[:9])
    parent_name = parts[8]
    parent_type = (parts[6] + "/" + parts[7]).lower()
    ext_name = text(raw.get("name"), source_id, 256) or parts[-1]
    rg = text(raw.get("resourceGroup"), source_id, 128) or parts[4]
    location = text(raw.get("location"), source_id, 64) or ""
    publisher = text(raw.get("publisher"), source_id, 256) or "UnknownPublisher"
    ext_type = text(raw.get("extType"), source_id, 256) or ext_name
    version = text(raw.get("version"), source_id, 64) or "unknown"
    prov_state = text(raw.get("provisioningState"), source_id, 64) or "Unknown"
    return {
        "id": ext_id,
        "extension_id": ext_id,
        "name": ext_name,
        "extension_name": ext_name,
        "resource_id": parent_id,
        "resource_name": parent_name,
        "resource_group": rg,
        "resource_type": parent_type,
        "hosting": "arc" if "hybridcompute" in parent_type else "azure",
        "location": location,
        "publisher": publisher,
        "extension_type": ext_type,
        "version": version,
        "provisioning_state": prov_state,
        "enable_automatic_upgrade": boolean(raw.get("enableAutomaticUpgrade"), source_id),
        "auto_upgrade_minor_version": boolean(raw.get("autoUpgradeMinorVersion"), source_id),
        "observed_at_utc": reference,
        "source_id": source_id,
    }


def detect_posture_and_extension_anomalies(resources, extensions, reference):
    anomalies = []
    for ext in extensions:
        state = (ext.get("provisioning_state") or "").strip()
        if state.lower() in ("succeeded", "creating", "updating"):
            continue
        token_haystack = (ext["extension_name"] + " " + ext["extension_type"] + " " + ext["publisher"]).lower()
        is_crit_ext = any(tok in token_haystack for tok in CRITICAL_EXTENSION_TOKENS)
        sev = "high" if state.lower() == "failed" and is_crit_ext else "medium"
        short_hash = hashlib.sha256(ext["extension_id"].lower().encode("utf-8")).hexdigest()[:10]
        anomalies.append({
            "id": "ANM-EXT-" + short_hash,
            "record_kind": "anomaly",
            "category": "extension_failure",
            "category_label": CATEGORY_LABELS["extension_failure"],
            "anomaly_kind": "guest_extension_provisioning_failed",
            "severity": sev,
            "severity_label": SEVERITY_LABELS[sev],
            "title": "Extensión " + ext["extension_name"] + " en estado " + state + " (" + ext["resource_name"] + ")",
            "resource_id": ext["resource_id"],
            "resource_name": ext["resource_name"],
            "resource_group": ext["resource_group"],
            "resource_type": ext["resource_type"],
            "hosting": ext["hosting"],
            "metric_or_field": "properties.provisioningState (" + ext["publisher"] + "/" + ext["extension_type"] + ")",
            "observed_value": state,
            "baseline_or_expected": "Succeeded",
            "unit": "State",
            "sample_count": 1,
            "window_grain": "PointInTime",
            "observed_at_utc": reference,
            "source_id": "arg_posture_anomalies",
            "workspace_name": "",
            "extension_name": ext["extension_name"],
            "extension_version": ext["version"],
            "summary": (
                "La extensión " + ext["extension_name"] + " (" + ext["publisher"] + "/" + ext["extension_type"]
                + ", versión " + ext["version"] + ") en " + ext["resource_name"]
                + " presenta provisioningState=" + state + "."
            ),
            "learn_url": "https://learn.microsoft.com/azure/azure-arc/servers/manage-vm-extensions",
        })

    for res in resources:
        rtype = res["resource_type"]
        rname = res["resource_name"]
        short_hash = hashlib.sha256(res["resource_id"].lower().encode("utf-8")).hexdigest()[:10]
        if rtype in ("microsoft.hybridcompute/machines", "microsoft.kubernetes/connectedclusters"):
            arc_st = (res.get("arc_status") or "").strip()
            if arc_st.lower() in ("expired", "disconnected", "error"):
                sev = "high" if arc_st.lower() in ("expired", "error") else "medium"
                changed = res.get("arc_last_status_change_utc") or "no_timestamp"
                ver = res.get("arc_agent_version") or "unknown"
                anomalies.append({
                    "id": "ANM-ARC-" + short_hash,
                    "record_kind": "anomaly",
                    "category": "connectivity_posture",
                    "category_label": CATEGORY_LABELS["connectivity_posture"],
                    "anomaly_kind": "arc_agent_" + arc_st.lower(),
                    "severity": sev,
                    "severity_label": SEVERITY_LABELS[sev],
                    "title": "Agente Azure Arc en estado " + arc_st + " (" + rname + ")",
                    "resource_id": res["resource_id"],
                    "resource_name": rname,
                    "resource_group": res["resource_group"],
                    "resource_type": rtype,
                    "hosting": "arc",
                    "metric_or_field": "properties.status (agentVersion=" + ver + ")",
                    "observed_value": arc_st,
                    "baseline_or_expected": "Connected",
                    "unit": "State",
                    "sample_count": 1,
                    "window_grain": "PointInTime",
                    "observed_at_utc": reference,
                    "source_id": "arg_posture_anomalies",
                    "workspace_name": "",
                    "summary": (
                        "El recurso híbrido " + rname + " (" + (res.get("os_sku") or res.get("os_name") or rtype)
                        + ") reporta status=" + arc_st + " (último cambio: " + changed + ", agente " + ver + ")."
                    ),
                    "learn_url": "https://learn.microsoft.com/azure/azure-arc/servers/troubleshoot-agent-onboard",
                })
        if rtype == "microsoft.containerservice/managedclusters":
            pstate = (res.get("power_state") or "").strip()
            prov = (res.get("provisioning_state") or "").strip()
            if prov.lower() == "failed" or (pstate and pstate.lower() not in ("running", "succeeded")):
                sev = "high" if prov.lower() == "failed" else "medium"
                observed_st = prov if prov.lower() == "failed" else pstate
                anomalies.append({
                    "id": "ANM-AKS-" + short_hash,
                    "record_kind": "anomaly",
                    "category": "connectivity_posture",
                    "category_label": CATEGORY_LABELS["connectivity_posture"],
                    "anomaly_kind": "aks_cluster_non_running",
                    "severity": sev,
                    "severity_label": SEVERITY_LABELS[sev],
                    "title": "Clúster AKS " + rname + " en estado " + observed_st,
                    "resource_id": res["resource_id"],
                    "resource_name": rname,
                    "resource_group": res["resource_group"],
                    "resource_type": rtype,
                    "hosting": "azure",
                    "metric_or_field": "properties.powerState.code / provisioningState",
                    "observed_value": observed_st,
                    "baseline_or_expected": "Running / Succeeded",
                    "unit": "State",
                    "sample_count": 1,
                    "window_grain": "PointInTime",
                    "observed_at_utc": reference,
                    "source_id": "arg_posture_anomalies",
                    "workspace_name": "",
                    "summary": (
                        "El clúster AKS " + rname + " (k8s " + (res.get("kubernetes_version") or "n/a")
                        + ") se encuentra en estado " + observed_st + " (provisioningState=" + prov + ")."
                    ),
                    "learn_url": "https://learn.microsoft.com/azure/aks/start-stop-cluster",
                })
        elif (res.get("provisioning_state") or "").lower() == "failed":
            anomalies.append({
                "id": "ANM-PRV-" + short_hash,
                "record_kind": "anomaly",
                "category": "connectivity_posture",
                "category_label": CATEGORY_LABELS["connectivity_posture"],
                "anomaly_kind": "resource_provisioning_failed",
                "severity": "high",
                "severity_label": SEVERITY_LABELS["high"],
                "title": "Recurso " + rname + " con provisioningState=Failed",
                "resource_id": res["resource_id"],
                "resource_name": rname,
                "resource_group": res["resource_group"],
                "resource_type": rtype,
                "hosting": res["hosting"],
                "metric_or_field": "properties.provisioningState",
                "observed_value": "Failed",
                "baseline_or_expected": "Succeeded",
                "unit": "State",
                "sample_count": 1,
                "window_grain": "PointInTime",
                "observed_at_utc": reference,
                "source_id": "arg_posture_anomalies",
                "workspace_name": "",
                "summary": "El recurso " + rname + " (" + rtype + ") presenta provisioningState=Failed en Azure Resource Manager.",
                "learn_url": "https://learn.microsoft.com/azure/azure-resource-manager/troubleshooting/troubleshooting-deployment-errors",
            })
        elif rtype == "microsoft.compute/virtualmachines":
            pstate = (res.get("power_state") or "").strip().lower()
            if pstate in ("powerstate/deallocated", "powerstate/stopped", "deallocated", "stopped"):
                anomalies.append({
                    "id": "ANM-VM-" + short_hash,
                    "record_kind": "anomaly",
                    "category": "connectivity_posture",
                    "category_label": CATEGORY_LABELS["connectivity_posture"],
                    "anomaly_kind": "vm_stopped_or_deallocated",
                    "severity": "low",
                    "severity_label": SEVERITY_LABELS["low"],
                    "title": "Máquina virtual " + rname + " en estado " + (res.get("power_state") or "Stopped"),
                    "resource_id": res["resource_id"],
                    "resource_name": rname,
                    "resource_group": res["resource_group"],
                    "resource_type": rtype,
                    "hosting": "azure",
                    "metric_or_field": "instanceView.powerState.code",
                    "observed_value": res.get("power_state") or "Stopped",
                    "baseline_or_expected": "PowerState/running",
                    "unit": "State",
                    "sample_count": 1,
                    "window_grain": "PointInTime",
                    "observed_at_utc": reference,
                    "source_id": "arg_posture_anomalies",
                    "workspace_name": "",
                    "summary": (
                        "La máquina virtual " + rname + " (" + (res.get("vm_size") or "VM")
                        + ") está detenida o desasignada (" + (res.get("power_state") or "Stopped") + ")."
                    ),
                    "learn_url": "https://learn.microsoft.com/azure/virtual-machines/states-billing",
                })
    return anomalies


def telemetry_kql_query(grain="1h"):
    return (
        "let cpu_im = InsightsMetrics "
        "| where Origin in ('vm.azm.ms', 'azuremonitor') and Namespace == 'Processor' and Name == 'UtilizationPercentage' "
        "| summarize bin_val=avg(Val), samples=count() by _ResourceId=tolower(_ResourceId), bin(TimeGenerated, " + grain + ") "
        "| extend metric_key='cpu_percent', unit='Percent'; "
        "let mem_im = InsightsMetrics "
        "| where Origin in ('vm.azm.ms', 'azuremonitor') and Namespace == 'Memory' and Name == 'AvailableMB' "
        "| summarize bin_val=min(Val), samples=count() by _ResourceId=tolower(_ResourceId), bin(TimeGenerated, " + grain + ") "
        "| extend metric_key='memory_available_mb', unit='MB'; "
        "let disk_im = InsightsMetrics "
        "| where Origin in ('vm.azm.ms', 'azuremonitor') and Namespace == 'LogicalDisk' and Name == 'FreeSpacePercentage' "
        "| where tostring(parse_json(Tags)['vm.azm.ms/mountId']) !startswith '/snap/' "
        "| summarize bin_val=min(Val), samples=count() by _ResourceId=tolower(_ResourceId), bin(TimeGenerated, " + grain + ") "
        "| extend metric_key='disk_free_percent', unit='Percent'; "
        "let perf_cpu = Perf "
        "| where ObjectName in ('Processor', 'Processor Information') and CounterName == '% Processor Time' and InstanceName in ('_Total', 'Total') "
        "| summarize bin_val=avg(CounterValue), samples=count() by _ResourceId=tolower(_ResourceId), bin(TimeGenerated, " + grain + ") "
        "| extend metric_key='cpu_percent', unit='Percent'; "
        "let combined = union isfuzzy=true cpu_im, mem_im, disk_im, perf_cpu "
        "| where isnotempty(_ResourceId) "
        "| summarize avg_val=round(avg(bin_val), 2), max_val=round(max(bin_val), 2), min_val=round(min(bin_val), 2), "
        "median_val=round(percentile(bin_val, 50), 2), p95_val=round(percentile(bin_val, 95), 2), "
        "high_bins=countif(metric_key == 'cpu_percent' and bin_val >= 85.0), "
        "low_mem_bins=countif(metric_key == 'memory_available_mb' and bin_val <= 512.0), "
        "low_disk_bins=countif(metric_key == 'disk_free_percent' and bin_val <= 15.0), "
        "bins_total=count(), sample_count=sum(samples), last_seen_utc=max(TimeGenerated) "
        "by _ResourceId, metric_key, unit; "
        "let hb = Heartbeat "
        "| where isnotempty(_ResourceId) "
        "| summarize avg_val=round(todouble(count()), 2), max_val=round(todouble(datetime_diff('minute', now(), max(TimeGenerated))), 2), "
        "min_val=0.0, median_val=0.0, p95_val=0.0, high_bins=0, low_mem_bins=0, low_disk_bins=0, "
        "bins_total=count(), sample_count=count(), last_seen_utc=max(TimeGenerated) "
        "by _ResourceId=tolower(_ResourceId) "
        "| extend metric_key='heartbeat_silence_minutes', unit='Minutes'; "
        "union isfuzzy=true combined, hb"
    )


def parse_log_table(payload, source_id):
    if payload.get("error") is not None:
        raise EvidenceError("partial_log_query", "Log Analytics returned a partial/error payload.", source_id)
    tables = payload.get("tables")
    if not isinstance(tables, list) or not tables or not isinstance(tables[0], dict):
        raise EvidenceError("invalid_log_result", "Log Analytics response is missing its primary table.", source_id)
    table = tables[0]
    columns = table.get("columns")
    rows = table.get("rows")
    if not isinstance(columns, list) or not isinstance(rows, list) or len(rows) > MAX_ROWS:
        raise EvidenceError("invalid_log_result", "Log Analytics table columns or rows are invalid.", source_id)
    col_names = [text(col.get("name"), source_id, 128) for col in columns if isinstance(col, dict)]
    if len(col_names) != len(columns) or len(set(col_names)) != len(col_names):
        raise EvidenceError("invalid_log_result", "Log Analytics table column names are invalid or duplicated.", source_id)
    parsed = []
    for row in rows:
        if not isinstance(row, list) or len(row) != len(col_names):
            raise EvidenceError("invalid_log_result", "Log Analytics row length does not match columns.", source_id)
        parsed.append(dict(zip(col_names, row)))
    return parsed


def evaluate_telemetry_row(raw, workspace_name, subscription_id, window, reference):
    source_id = "logs_telemetry_anomalies"
    raw_res_id = text(raw.get("_ResourceId"), source_id, 2048)
    if not raw_res_id or not raw_res_id.lower().startswith("/subscriptions/" + subscription_id.lower() + "/"):
        return None
    res_id = arm_resource_id(raw_res_id, subscription_id, source_id)
    rg, rtype, rname = extract_rg_and_type(res_id)
    hosting = "arc" if "hybridcompute" in rtype or "connectedclusters" in rtype else "azure"
    metric_key = text(raw.get("metric_key"), source_id, 64) or ""
    unit = text(raw.get("unit"), source_id, 32) or "Percent"
    avg_val = number(raw.get("avg_val"), source_id)
    max_val = number(raw.get("max_val"), source_id)
    min_val = number(raw.get("min_val"), source_id)
    median_val = number(raw.get("median_val"), source_id)
    p95_val = number(raw.get("p95_val"), source_id)
    high_bins = int(number(raw.get("high_bins"), source_id) or 0)
    low_mem_bins = int(number(raw.get("low_mem_bins"), source_id) or 0)
    low_disk_bins = int(number(raw.get("low_disk_bins"), source_id) or 0)
    bins_total = int(number(raw.get("bins_total"), source_id) or 0)
    sample_count = int(number(raw.get("sample_count"), source_id) or 0)
    last_seen = text(raw.get("last_seen_utc"), source_id, 64) or reference
    last_seen_iso = iso_utc(parse_utc(last_seen, source_id))
    short_hash = hashlib.sha256((res_id.lower() + "|" + metric_key + "|" + workspace_name).encode("utf-8")).hexdigest()[:10]

    if metric_key == "cpu_percent" and max_val is not None and median_val is not None:
        delta = round(max_val - median_val, 2)
        sustained = high_bins >= 3 or (avg_val is not None and avg_val >= 85.0)
        spike = max_val >= 95.0 or (max_val >= 85.0 and delta >= 25.0)
        if sustained or spike:
            sev = "critical" if (sustained and max_val >= 95.0) else "high" if sustained or max_val >= 95.0 else "medium"
            kind = "sustained_high_cpu" if sustained else "cpu_statistical_spike"
            return {
                "id": "ANM-TEL-" + short_hash,
                "record_kind": "anomaly",
                "category": "telemetry_anomaly",
                "category_label": CATEGORY_LABELS["telemetry_anomaly"],
                "anomaly_kind": kind,
                "severity": sev,
                "severity_label": SEVERITY_LABELS[sev],
                "title": "Anomalía de CPU en " + rname + " (pico " + str(max_val) + "%, mediana " + str(median_val) + "%)",
                "resource_id": res_id,
                "resource_name": rname,
                "resource_group": rg,
                "resource_type": rtype,
                "hosting": hosting,
                "metric_or_field": "Processor/UtilizationPercentage (" + window["grain"] + ")",
                "observed_value": max_val,
                "baseline_or_expected": median_val,
                "average_value": avg_val,
                "p95_value": p95_val,
                "high_bins": high_bins,
                "bins_total": bins_total,
                "unit": unit,
                "sample_count": sample_count,
                "window_grain": window["grain"],
                "observed_at_utc": last_seen_iso,
                "source_id": source_id,
                "workspace_name": workspace_name,
                "summary": (
                    "Telemetría en " + workspace_name + " para " + rname + ": pico CPU=" + str(max_val)
                    + "%, promedio=" + str(avg_val) + "%, mediana=" + str(median_val) + "% (Δ+" + str(delta)
                    + " pp, " + str(high_bins) + "/" + str(bins_total) + " intervalos >=85%, "
                    + str(sample_count) + " muestras)."
                ),
                "learn_url": "https://learn.microsoft.com/azure/azure-monitor/vm/vminsights-performance",
            }

    if metric_key == "memory_available_mb" and min_val is not None:
        if min_val <= 512.0 or low_mem_bins >= 2:
            sev = "high" if min_val <= 256.0 else "medium"
            return {
                "id": "ANM-TEL-" + short_hash,
                "record_kind": "anomaly",
                "category": "telemetry_anomaly",
                "category_label": CATEGORY_LABELS["telemetry_anomaly"],
                "anomaly_kind": "low_available_memory",
                "severity": sev,
                "severity_label": SEVERITY_LABELS[sev],
                "title": "Presión de memoria física en " + rname + " (mínimo " + str(min_val) + " MB disponibles)",
                "resource_id": res_id,
                "resource_name": rname,
                "resource_group": rg,
                "resource_type": rtype,
                "hosting": hosting,
                "metric_or_field": "Memory/AvailableMB (" + window["grain"] + ")",
                "observed_value": min_val,
                "baseline_or_expected": median_val if median_val is not None else 1024.0,
                "average_value": avg_val,
                "p95_value": p95_val,
                "high_bins": low_mem_bins,
                "bins_total": bins_total,
                "unit": "MB",
                "sample_count": sample_count,
                "window_grain": window["grain"],
                "observed_at_utc": last_seen_iso,
                "source_id": source_id,
                "workspace_name": workspace_name,
                "summary": (
                    "Memoria disponible en " + rname + " cayó hasta " + str(min_val) + " MB (mediana "
                    + str(median_val) + " MB, " + str(low_mem_bins) + "/" + str(bins_total)
                    + " intervalos <=512 MB en " + workspace_name + ")."
                ),
                "learn_url": "https://learn.microsoft.com/azure/azure-monitor/vm/vminsights-performance",
            }

    if metric_key == "disk_free_percent" and min_val is not None:
        if min_val <= 15.0 or low_disk_bins >= 1:
            sev = "critical" if min_val <= 5.0 else "high" if min_val <= 10.0 else "medium"
            return {
                "id": "ANM-TEL-" + short_hash,
                "record_kind": "anomaly",
                "category": "telemetry_anomaly",
                "category_label": CATEGORY_LABELS["telemetry_anomaly"],
                "anomaly_kind": "low_disk_free_space",
                "severity": sev,
                "severity_label": SEVERITY_LABELS[sev],
                "title": "Espacio libre en disco bajo en " + rname + " (" + str(min_val) + "% libre)",
                "resource_id": res_id,
                "resource_name": rname,
                "resource_group": rg,
                "resource_type": rtype,
                "hosting": hosting,
                "metric_or_field": "LogicalDisk/FreeSpacePercentage (" + window["grain"] + ")",
                "observed_value": min_val,
                "baseline_or_expected": 15.0,
                "average_value": avg_val,
                "p95_value": p95_val,
                "high_bins": low_disk_bins,
                "bins_total": bins_total,
                "unit": "Percent",
                "sample_count": sample_count,
                "window_grain": window["grain"],
                "observed_at_utc": last_seen_iso,
                "source_id": source_id,
                "workspace_name": workspace_name,
                "summary": (
                    "Volumen lógico en " + rname + " registró " + str(min_val)
                    + "% de espacio libre (umbral mínimo 15%, " + str(sample_count)
                    + " muestras en " + workspace_name + ")."
                ),
                "learn_url": "https://learn.microsoft.com/azure/azure-monitor/vm/vminsights-performance",
            }

    if metric_key == "heartbeat_silence_minutes" and max_val is not None:
        if max_val >= 15.0:
            sev = "high" if max_val >= 60.0 else "medium"
            return {
                "id": "ANM-HB-" + short_hash,
                "record_kind": "anomaly",
                "category": "telemetry_anomaly",
                "category_label": CATEGORY_LABELS["telemetry_anomaly"],
                "anomaly_kind": "heartbeat_silence_gap",
                "severity": sev,
                "severity_label": SEVERITY_LABELS[sev],
                "title": "Silencio de Heartbeat (" + str(int(round(max_val))) + " min sin latido) en " + rname,
                "resource_id": res_id,
                "resource_name": rname,
                "resource_group": rg,
                "resource_type": rtype,
                "hosting": hosting,
                "metric_or_field": "Heartbeat/SilenceMinutes",
                "observed_value": round(max_val, 1),
                "baseline_or_expected": 5.0,
                "average_value": avg_val,
                "p95_value": None,
                "high_bins": 1,
                "bins_total": bins_total,
                "unit": "Minutes",
                "sample_count": sample_count,
                "window_grain": window["grain"],
                "observed_at_utc": last_seen_iso,
                "source_id": source_id,
                "workspace_name": workspace_name,
                "summary": (
                    "El recurso " + rname + " lleva " + str(round(max_val, 1))
                    + " minutos sin emitir latidos en la tabla Heartbeat de " + workspace_name
                    + " (último latido: " + last_seen_iso + ")."
                ),
                "learn_url": "https://learn.microsoft.com/azure/azure-monitor/agents/azure-monitor-agent-troubleshoot",
            }
    return None


def collect_logs_telemetry(logs_reader, config, window, reference):
    workspaces = config["workspaces"]
    if not workspaces:
        receipt = source_receipt(
            "logs_telemetry_anomalies",
            reference,
            status="not_configured",
            window=window,
            note="No Log Analytics workspaces configured in APPROVED_LOG_WORKSPACES.",
            workspaces_queried=[],
        )
        return [], [], receipt

    grain_kql = "5m" if window["grain"] == "PT5M" else "1h"
    query = telemetry_kql_query(grain_kql)
    anomalies_by_key = {}
    telemetry_summaries = []
    ws_receipts = []
    total_records = 0
    errors = []

    for ws in workspaces:
        url = LOGS_ORIGIN + "/v1/workspaces/" + ws["customer_id"] + "/query"
        logs_reader.allow(url, "POST")
        body = {"query": query, "timespan": window["timespan_iso"]}
        try:
            payload = logs_reader.request("POST", url, "logs_telemetry_anomalies", body=body)
            rows = parse_log_table(payload, "logs_telemetry_anomalies")
            total_records += len(rows)
            ws_receipts.append({
                "workspace_name": ws["name"],
                "customer_id": ws["customer_id"],
                "status": "complete",
                "records": len(rows),
            })
            for row in rows:
                telemetry_summaries.append({
                    "workspace_name": ws["name"],
                    "resource_id": text(row.get("_ResourceId"), "logs_telemetry_anomalies", 2048),
                    "metric_key": text(row.get("metric_key"), "logs_telemetry_anomalies", 64),
                    "avg_val": number(row.get("avg_val"), "logs_telemetry_anomalies"),
                    "max_val": number(row.get("max_val"), "logs_telemetry_anomalies"),
                    "min_val": number(row.get("min_val"), "logs_telemetry_anomalies"),
                    "median_val": number(row.get("median_val"), "logs_telemetry_anomalies"),
                    "sample_count": int(number(row.get("sample_count"), "logs_telemetry_anomalies") or 0),
                })
                anom = evaluate_telemetry_row(row, ws["name"], config["subscription_id"], window, reference)
                if anom is not None:
                    dedup_key = (anom["resource_id"].lower(), anom["anomaly_kind"])
                    existing = anomalies_by_key.get(dedup_key)
                    if existing is None or SEVERITY_RANK[anom["severity"]] < SEVERITY_RANK[existing["severity"]]:
                        anomalies_by_key[dedup_key] = anom
        except EvidenceError as exc:
            err_doc = exc.public()
            err_doc["workspace_name"] = ws["name"]
            errors.append(err_doc)
            ws_receipts.append({
                "workspace_name": ws["name"],
                "customer_id": ws["customer_id"],
                "status": "denied" if exc.http_status in (401, 403) else "error",
                "records": 0,
                "error": err_doc,
            })

    ok_count = sum(w["status"] == "complete" for w in ws_receipts)
    if ok_count == len(ws_receipts):
        status = "complete"
    elif ok_count > 0:
        status = "partial"
    elif any(w["status"] == "denied" for w in ws_receipts):
        status = "denied"
    else:
        status = "error"

    receipt = source_receipt(
        "logs_telemetry_anomalies",
        reference,
        status=status,
        records=total_records,
        pages=len(ws_receipts),
        pagination_complete=status == "complete",
        errors=errors,
        window=window,
        workspaces_queried=ws_receipts,
        read_signature="POST https://api.loganalytics.io/v1/workspaces/{workspace_id}/query",
        note="Consultas KQL acotadas sobre InsightsMetrics, Perf y Heartbeat en los espacios Log Analytics aprobados.",
    )
    sorted_anomalies = sorted(
        anomalies_by_key.values(),
        key=lambda a: (SEVERITY_RANK[a["severity"]], a["resource_name"].lower(), a["id"]),
    )
    return sorted_anomalies, telemetry_summaries, receipt


def normalize_advisor_row(raw, subscription_id, reference):
    source_id = "arm_advisor_recommendations"
    rec_id = text(raw.get("id"), source_id, 2048)
    name = text(raw.get("name"), source_id, 256)
    if not rec_id or not name:
        raise EvidenceError("invalid_advisor", "Advisor recommendation is missing id or name.", source_id)
    props = obj(raw.get("properties", {}), source_id)
    adv_cat = text(props.get("category"), source_id, 64) or "HighAvailability"
    impact = text(props.get("impact"), source_id, 32) or "Medium"
    sev_map = {"high": "high", "medium": "medium", "low": "low"}
    sev = sev_map.get(impact.lower(), "medium")
    short_desc = obj(props.get("shortDescription", {}), source_id) if props.get("shortDescription") else {}
    problem = text(short_desc.get("problem"), source_id, 1024) or ("Recomendación de Azure Advisor (" + adv_cat + ")")
    solution = text(short_desc.get("solution"), source_id, 1024) or problem
    res_meta = obj(props.get("resourceMetadata", {}), source_id) if props.get("resourceMetadata") else {}
    target_id = text(res_meta.get("resourceId"), source_id, 2048) or rec_id.split("/providers/Microsoft.Advisor/")[0]
    if target_id and target_id.lower().startswith("/subscriptions/"):
        target_id = arm_resource_id(target_id, subscription_id, source_id)
    rg, rtype, rname = extract_rg_and_type(target_id)
    impacted_val = text(props.get("impactedValue"), source_id, 256) or rname
    updated = text(props.get("lastUpdated"), source_id, 64) or reference
    updated_iso = iso_utc(parse_utc(updated, source_id))
    short_hash = hashlib.sha256(rec_id.lower().encode("utf-8")).hexdigest()[:10]
    return {
        "id": "ADV-" + short_hash,
        "recommendation_id": name,
        "native_id": rec_id,
        "record_kind": "advisor",
        "category": "advisor_recommendation",
        "category_label": CATEGORY_LABELS["advisor_recommendation"],
        "advisor_category": adv_cat,
        "impact": impact,
        "severity": sev,
        "severity_label": SEVERITY_LABELS[sev],
        "problem": problem,
        "solution": solution,
        "title": problem,
        "resource_id": target_id,
        "resource_name": impacted_val,
        "resource_group": rg,
        "resource_type": rtype,
        "last_updated_utc": updated_iso,
        "observed_at_utc": reference,
        "source_id": source_id,
        "summary": "[" + adv_cat + " / Impacto " + impact + "] " + problem + " — " + solution,
        "learn_url": "https://learn.microsoft.com/azure/advisor/advisor-overview",
    }


def synthesize_actions(incidents, anomalies, advisor_rows):
    actions = []

    for inc in incidents:
        is_active = (inc.get("monitor_condition") or "").lower() in ("fired", "active") or (inc.get("state") or "").lower() in ("new", "acknowledged", "active")
        if inc["category"] == "native_alert":
            horizon = "immediate_24h" if (is_active and inc["severity"] in ("critical", "high")) else "short_term_7d"
            effort = "low" if inc["severity"] in ("medium", "low") else "medium"
            owner = "Ingeniería de Fiabilidad / Operaciones Monitorización"
            rec_text = (
                "Verificar la condición de disparo (" + inc["monitor_condition"] + " / " + inc["state"]
                + ") en Azure Monitor para " + inc["resource_name"] + ", validar correlación con cambios recientes y documentar el cierre operativo."
            )
        else:
            horizon = "immediate_24h" if (is_active and inc["signal_type"] == "ServiceIssue") else "short_term_7d"
            effort = "low"
            owner = "Gobierno Cloud / Gestión de Incidentes Plataforma"
            rec_text = (
                "Revisar el trackingId oficial " + (inc.get("tracking_id") or inc["id"])
                + " en Azure Service Health (" + inc["monitor_service"]
                + "), evaluar ventana de mantenimiento o mitigación y confirmar impacto real sobre cargas dependientes."
            )
        actions.append({
            "_sort_key": (
                0 if horizon == "immediate_24h" else 1,
                SEVERITY_RANK[inc["severity"]],
                inc["resource_name"].lower(),
                inc["id"],
            ),
            "category": inc["category"],
            "category_label": inc["category_label"],
            "severity": inc["severity"],
            "severity_label": inc["severity_label"],
            "horizon": horizon,
            "horizon_label": HORIZON_LABELS[horizon],
            "effort": effort,
            "effort_label": EFFORT_LABELS[effort],
            "title": "Atender " + ("alerta activa " if is_active else "incidencia registrada ") + "en " + inc["resource_name"],
            "resource_id": inc["resource_id"],
            "resource_name": inc["resource_name"],
            "resource_group": inc["resource_group"],
            "resource_type": inc["resource_type"],
            "owner_scope": owner,
            "linked_evidence_ids": [inc["id"]],
            "source_ids": [inc["source_id"]],
            "evidence_summary": inc["summary"],
            "recommendation": rec_text,
            "learn_url": inc["learn_url"],
        })

    ext_by_resource = {}
    for anom in anomalies:
        if anom["category"] == "extension_failure":
            ext_by_resource.setdefault(anom["resource_id"], []).append(anom)
        elif anom["category"] == "connectivity_posture":
            is_arc = anom["hosting"] == "arc"
            is_aks = "managedclusters" in anom["resource_type"]
            horizon = "short_term_7d" if anom["severity"] in ("critical", "high", "medium") else "monthly_cycle"
            owner = (
                "Operaciones Híbridas / Administración Azure Arc"
                if is_arc
                else "Plataforma de Contenedores / Operaciones AKS"
                if is_aks
                else "Operaciones de Infraestructura Cloud"
            )
            if is_arc:
                rec_text = (
                    "Inspeccionar el servicio himds y la conectividad saliente TLS del agente Azure Connected Machine en "
                    + anom["resource_name"] + " (estado actual: " + str(anom["observed_value"])
                    + "); renovar credenciales o reconectar el nodo si el certificado de identidad ha expirado."
                )
            elif is_aks:
                rec_text = (
                    "Confirmar si la parada/estado (" + str(anom["observed_value"]) + ") del clúster AKS "
                    + anom["resource_name"] + " responde a planificación de ahorro o a un fallo de plano de control; "
                    + "evitar mantener clústeres detenidos más de 12 meses para preservar compatibilidad de versión."
                )
            else:
                rec_text = (
                    "Revisar el estado operativo (" + str(anom["observed_value"]) + ") de "
                    + anom["resource_name"] + " y confirmar su alineación con el catálogo de servicios activos."
                )
            actions.append({
                "_sort_key": (
                    1 if horizon == "short_term_7d" else 2,
                    SEVERITY_RANK[anom["severity"]],
                    anom["resource_name"].lower(),
                    anom["id"],
                ),
                "category": anom["category"],
                "category_label": anom["category_label"],
                "severity": anom["severity"],
                "severity_label": anom["severity_label"],
                "horizon": horizon,
                "horizon_label": HORIZON_LABELS[horizon],
                "effort": "medium" if is_arc or is_aks else "low",
                "effort_label": EFFORT_LABELS["medium" if is_arc or is_aks else "low"],
                "title": "Normalizar estado operativo de " + anom["resource_name"] + " (" + str(anom["observed_value"]) + ")",
                "resource_id": anom["resource_id"],
                "resource_name": anom["resource_name"],
                "resource_group": anom["resource_group"],
                "resource_type": anom["resource_type"],
                "owner_scope": owner,
                "linked_evidence_ids": [anom["id"]],
                "source_ids": [anom["source_id"]],
                "evidence_summary": anom["summary"],
                "recommendation": rec_text,
                "learn_url": anom["learn_url"],
            })
        elif anom["category"] == "telemetry_anomaly":
            horizon = "immediate_24h" if anom["severity"] == "critical" else "short_term_7d"
            actions.append({
                "_sort_key": (
                    0 if horizon == "immediate_24h" else 1,
                    SEVERITY_RANK[anom["severity"]],
                    anom["resource_name"].lower(),
                    anom["id"],
                ),
                "category": "telemetry_anomaly",
                "category_label": CATEGORY_LABELS["telemetry_anomaly"],
                "severity": anom["severity"],
                "severity_label": SEVERITY_LABELS[anom["severity"]],
                "horizon": horizon,
                "horizon_label": HORIZON_LABELS[horizon],
                "effort": "medium",
                "effort_label": EFFORT_LABELS["medium"],
                "title": "Investigar anomalía de telemetría en " + anom["resource_name"] + " (" + anom["metric_or_field"] + ")",
                "resource_id": anom["resource_id"],
                "resource_name": anom["resource_name"],
                "resource_group": anom["resource_group"],
                "resource_type": anom["resource_type"],
                "owner_scope": "Ingeniería de Capacidad & Observabilidad",
                "linked_evidence_ids": [anom["id"]],
                "source_ids": [anom["source_id"]],
                "evidence_summary": anom["summary"],
                "recommendation": (
                    "Analizar los procesos e intervalos de presión en " + anom["resource_name"]
                    + " reportados en Log Analytics (" + (anom.get("workspace_name") or "workspace")
                    + "), verificar dimensionamiento de SKU o fugas de recursos y ajustar umbrales de alerta preventiva."
                ),
                "learn_url": anom["learn_url"],
            })

    for res_id, ext_anoms in sorted(ext_by_resource.items()):
        highest = min(ext_anoms, key=lambda x: SEVERITY_RANK[x["severity"]])
        ext_names = ", ".join(sorted({x.get("extension_name") or x["title"] for x in ext_anoms}))
        ev_ids = [x["id"] for x in ext_anoms]
        horizon = "short_term_7d"
        actions.append({
            "_sort_key": (
                1,
                SEVERITY_RANK[highest["severity"]],
                highest["resource_name"].lower(),
                ev_ids[0],
            ),
            "category": "extension_failure",
            "category_label": CATEGORY_LABELS["extension_failure"],
            "severity": highest["severity"],
            "severity_label": SEVERITY_LABELS[highest["severity"]],
            "horizon": horizon,
            "horizon_label": HORIZON_LABELS[horizon],
            "effort": "medium",
            "effort_label": EFFORT_LABELS["medium"],
            "title": "Remediar extensiones fallidas (" + ext_names + ") en " + highest["resource_name"],
            "resource_id": res_id,
            "resource_name": highest["resource_name"],
            "resource_group": highest["resource_group"],
            "resource_type": highest["resource_type"],
            "owner_scope": "Seguridad de Endpoint & Operaciones Híbridas (MDE / Entra ID / AMA)",
            "linked_evidence_ids": ev_ids,
            "source_ids": ["arg_posture_anomalies"],
            "evidence_summary": "; ".join(x["summary"] for x in ext_anoms),
            "recommendation": (
                "Verificar primero la conectividad del agente base en " + highest["resource_name"]
                + ", revisar registros locales de instalación de " + ext_names
                + " y reprovisionar las extensiones en ventana de cambio controlada."
            ),
            "learn_url": "https://learn.microsoft.com/azure/azure-arc/servers/troubleshoot-vm-extensions",
        })

    for adv in advisor_rows:
        horizon = "short_term_7d" if adv["severity"] == "high" else "monthly_cycle"
        actions.append({
            "_sort_key": (
                1 if horizon == "short_term_7d" else 2,
                SEVERITY_RANK[adv["severity"]],
                adv["resource_name"].lower(),
                adv["id"],
            ),
            "category": "advisor_recommendation",
            "category_label": CATEGORY_LABELS["advisor_recommendation"],
            "severity": adv["severity"],
            "severity_label": SEVERITY_LABELS[adv["severity"]],
            "horizon": horizon,
            "horizon_label": HORIZON_LABELS[horizon],
            "effort": "medium" if adv["severity"] == "high" else "low",
            "effort_label": EFFORT_LABELS["medium" if adv["severity"] == "high" else "low"],
            "title": "Evaluar recomendación Azure Advisor (" + adv["advisor_category"] + ") en " + adv["resource_name"],
            "resource_id": adv["resource_id"],
            "resource_name": adv["resource_name"],
            "resource_group": adv["resource_group"],
            "resource_type": adv["resource_type"],
            "owner_scope": "Arquitectura Cloud & Mejora Continua WAF",
            "linked_evidence_ids": [adv["id"]],
            "source_ids": ["arm_advisor_recommendations"],
            "evidence_summary": adv["summary"],
            "recommendation": adv["solution"],
            "learn_url": adv["learn_url"],
        })

    actions.sort(key=lambda item: item["_sort_key"])
    finalized = []
    for idx, item in enumerate(actions, start=1):
        clean = {k: v for k, v in item.items() if k != "_sort_key"}
        short_hash = hashlib.sha256((clean["resource_id"].lower() + "|" + clean["title"] + "|" + str(idx)).encode("utf-8")).hexdigest()[:8]
        clean["id"] = f"ACT-{idx:03d}-{short_hash}"
        clean["priority_rank"] = idx
        finalized.append(clean)
    return finalized


def rollup_resources(estate_resources, extensions, incidents, anomalies, actions, telemetry_summaries):
    by_id = {}
    for res in estate_resources:
        rid = res["resource_id"].lower()
        by_id[rid] = {
            **res,
            "incident_count": 0,
            "anomaly_count": 0,
            "failed_extension_count": 0,
            "extensions_total": 0,
            "action_count": 0,
            "highest_severity": "low",
            "status": "healthy",
            "telemetry_metrics": {},
        }

    for ext in extensions:
        rid = ext["resource_id"].lower()
        if rid in by_id:
            by_id[rid]["extensions_total"] += 1
            if (ext.get("provisioning_state") or "").lower() not in ("succeeded", "creating", "updating"):
                by_id[rid]["failed_extension_count"] += 1

    for t_row in telemetry_summaries:
        rid = (t_row.get("resource_id") or "").lower()
        if rid in by_id and t_row.get("metric_key"):
            by_id[rid]["telemetry_metrics"][t_row["metric_key"]] = {
                "avg": t_row.get("avg_val"),
                "max": t_row.get("max_val"),
                "min": t_row.get("min_val"),
                "median": t_row.get("median_val"),
                "samples": t_row.get("sample_count"),
            }

    def bump_sev(entry, sev):
        if entry["status"] == "healthy" or SEVERITY_RANK[sev] < SEVERITY_RANK[entry["highest_severity"]]:
            entry["highest_severity"] = sev

    for inc in incidents:
        rid = inc["resource_id"].lower()
        if rid in by_id:
            by_id[rid]["incident_count"] += 1
            bump_sev(by_id[rid], inc["severity"])
            by_id[rid]["status"] = "attention"

    for anom in anomalies:
        rid = anom["resource_id"].lower()
        if rid in by_id:
            by_id[rid]["anomaly_count"] += 1
            bump_sev(by_id[rid], anom["severity"])
            if anom["severity"] in ("critical", "high", "medium"):
                by_id[rid]["status"] = "attention"
            elif by_id[rid]["status"] == "healthy":
                by_id[rid]["status"] = "review"

    for act in actions:
        rid = act["resource_id"].lower()
        if rid in by_id:
            by_id[rid]["action_count"] += 1

    rolled = []
    for entry in by_id.values():
        sev = entry["highest_severity"] if entry["status"] != "healthy" else "low"
        entry["severity"] = sev
        entry["severity_label"] = SEVERITY_LABELS[sev] if entry["status"] != "healthy" else "Normal"
        rolled.append(entry)

    rolled.sort(
        key=lambda r: (
            0 if r["status"] == "attention" else 1 if r["status"] == "review" else 2,
            SEVERITY_RANK[r["severity"]],
            r["resource_name"].lower(),
        )
    )
    return rolled


def collect_live(config, window, reference):
    identity = Identity(config)
    try:
        arm_reader = HttpReader(identity, ARM_ORIGIN, "arm")
        logs_reader = HttpReader(identity, LOGS_ORIGIN, "logs")
        sub_id = config["subscription_id"]

        alerts, alerts_receipt = read_arg_query(
            arm_reader,
            sub_id,
            arg_alerts_query(),
            "arg_alerts_incidents",
            reference,
            window,
            lambda raw: normalize_alert_row(raw, sub_id, window, reference),
        )
        alerts_receipt["note"] = "Alertas nativas Azure Monitor (alertsmanagementresources) activas o actualizadas en la ventana."

        sh_query = urlencode({
            "api-version": RESOURCE_HEALTH_API_VERSION,
            "queryStartTime": window["start_utc"],
        })
        sh_url = ARM_ORIGIN + "/subscriptions/" + sub_id + "/providers/Microsoft.ResourceHealth/events?" + sh_query
        sh_events, sh_receipt = read_arm_pages(
            arm_reader,
            sh_url,
            "arm_service_health",
            reference,
            window,
            lambda raw: normalize_service_health_row(raw, sub_id, window, reference),
        )
        sh_receipt["note"] = "Comunicaciones oficiales Microsoft.ResourceHealth/events (ServiceIssue y PlannedMaintenance)."

        estate_resources, posture_receipt = read_arg_query(
            arm_reader,
            sub_id,
            arg_inventory_query(),
            "arg_posture_anomalies",
            reference,
            window,
            lambda raw: normalize_estate_resource(raw, sub_id, reference),
        )
        posture_receipt["note"] = "Inventario operativo Azure Resource Graph (VMs, Azure Arc, AKS, Container Apps, Web Apps, Storage, Key Vault, DBs)."

        extensions, ext_receipt = read_arg_query(
            arm_reader,
            sub_id,
            arg_extensions_query(),
            "arg_guest_extensions",
            reference,
            window,
            lambda raw: normalize_extension_row(raw, sub_id, reference),
        )
        ext_receipt["note"] = "Metadatos de extensiones de VM y servidores Azure Arc (sin leer settings ni protectedSettings)."

        telemetry_anomalies, telemetry_summaries, logs_receipt = collect_logs_telemetry(
            logs_reader, config, window, reference
        )

        adv_url = (
            ARM_ORIGIN + "/subscriptions/" + sub_id
            + "/providers/Microsoft.Advisor/recommendations?api-version=" + ADVISOR_API_VERSION
        )
        advisor_rows, advisor_receipt = read_arm_pages(
            arm_reader,
            adv_url,
            "arm_advisor_recommendations",
            reference,
            window,
            lambda raw: normalize_advisor_row(raw, sub_id, reference),
        )
        advisor_receipt["note"] = "Recomendaciones en caché de Microsoft.Advisor/recommendations en la suscripción."

        sources = [
            alerts_receipt,
            sh_receipt,
            posture_receipt,
            ext_receipt,
            logs_receipt,
            advisor_receipt,
        ]
        if all(s["status"] in ("denied", "error") for s in (alerts_receipt, posture_receipt)):
            first_err = (alerts_receipt["errors"] or posture_receipt["errors"] or [{}])[0]
            raise EvidenceError(
                first_err.get("code", "all_sources_failed"),
                "Primary Azure Resource Graph sources failed; no synthetic or empty report is generated.",
                first_err.get("source_id", "arg_posture_anomalies"),
                first_err.get("http_status"),
            )

        return {
            "subscription_id": sub_id,
            "alerts": alerts,
            "service_health": sh_events,
            "estate_resources": estate_resources,
            "extensions": extensions,
            "telemetry_anomalies": telemetry_anomalies,
            "telemetry_summaries": telemetry_summaries,
            "advisor": advisor_rows,
            "sources": sources,
        }
    finally:
        identity.close()


def finish_snapshot(raw, window, reference, provenance="LIVE"):
    if provenance not in ("LIVE", "SIMULATED"):
        raise EvidenceError("invalid_provenance", "provenance must be LIVE or SIMULATED.", "digest")
    validate_logo(CLIENT_LOGO_DATA_URI, CLIENT_LOGO_ALT)

    incidents = sorted(
        list(raw.get("alerts", [])) + list(raw.get("service_health", [])),
        key=lambda item: (SEVERITY_RANK[item["severity"]], item["start_time_utc"], item["id"]),
    )
    posture_anomalies = detect_posture_and_extension_anomalies(
        raw.get("estate_resources", []),
        raw.get("extensions", []),
        reference,
    )
    anomalies = sorted(
        posture_anomalies + list(raw.get("telemetry_anomalies", [])),
        key=lambda item: (SEVERITY_RANK[item["severity"]], item["category"], item["resource_name"].lower(), item["id"]),
    )
    advisor_rows = sorted(
        list(raw.get("advisor", [])),
        key=lambda item: (SEVERITY_RANK[item["severity"]], item["advisor_category"], item["id"]),
    )
    actions = synthesize_actions(incidents, anomalies, advisor_rows)
    resources = rollup_resources(
        raw.get("estate_resources", []),
        raw.get("extensions", []),
        incidents,
        anomalies,
        actions,
        raw.get("telemetry_summaries", []),
    )
    sources = list(raw.get("sources", []))

    native_alert_count = sum(i["category"] == "native_alert" for i in incidents)
    sh_count = sum(i["category"] == "service_health" for i in incidents)
    ext_fail_count = sum(a["category"] == "extension_failure" for a in anomalies)
    posture_count = sum(a["category"] == "connectivity_posture" for a in anomalies)
    tel_anom_count = sum(a["category"] == "telemetry_anomaly" for a in anomalies)
    imm_actions = sum(act["horizon"] == "immediate_24h" for act in actions)
    short_actions = sum(act["horizon"] == "short_term_7d" for act in actions)
    month_actions = sum(act["horizon"] == "monthly_cycle" for act in actions)
    attention_res = sum(r["status"] == "attention" for r in resources)
    degraded_sources = [s["id"] for s in sources if s["status"] not in ("complete", "not_configured")]

    counts = {
        "incidents_total": len(incidents),
        "native_alerts_total": native_alert_count,
        "service_health_total": sh_count,
        "anomalies_total": len(anomalies),
        "extension_failures_total": ext_fail_count,
        "connectivity_posture_total": posture_count,
        "telemetry_anomalies_total": tel_anom_count,
        "advisor_recommendations_total": len(advisor_rows),
        "actions_total": len(actions),
        "actions_immediate_24h": imm_actions,
        "actions_short_term_7d": short_actions,
        "actions_monthly_cycle": month_actions,
        "resources_total": len(resources),
        "resources_attention": attention_res,
        "extensions_evaluated": len(raw.get("extensions", [])),
        "severity_breakdown": {
            sev: sum(item["severity"] == sev for item in (incidents + anomalies))
            for sev in ("critical", "high", "medium", "low")
        },
    }

    executive_messages = [
        (
            "Ventana evaluada: " + window["label"] + " (" + window["start_utc"] + " → " + window["end_utc"]
            + ") sobre " + str(counts["resources_total"]) + " recursos inventariados ("
            + str(counts["resources_attention"]) + " requieren atención operativa)."
        ),
        (
            "Incidencias consolidadas: " + str(counts["incidents_total"]) + " registradas ("
            + str(native_alert_count) + " alertas nativas Azure Monitor y "
            + str(sh_count) + " comunicaciones oficiales Azure Service Health)."
        ),
        (
            "Anomalías técnicas detectadas: " + str(counts["anomalies_total"]) + " en total ("
            + str(ext_fail_count) + " fallos de extensión VM/Arc, "
            + str(posture_count) + " anomalías de conectividad/plano de control y "
            + str(tel_anom_count) + " anomalías estadísticas/umbrales de telemetría)."
        ),
        (
            "Plan de acciones recomendadas: " + str(counts["actions_total"]) + " acciones priorizadas ("
            + str(imm_actions) + " en horizonte Inmediato <24h, "
            + str(short_actions) + " a Corto plazo 1-7 días y "
            + str(month_actions) + " en Ciclo mensual), correlacionadas con "
            + str(counts["advisor_recommendations_total"]) + " recomendaciones de Azure Advisor."
        ),
        (
            "Cobertura de fuentes: " + str(len(sources) - len(degraded_sources)) + " de " + str(len(sources))
            + " flujos de evidencia completados en modo solo lectura sin alterar recursos ni agentes."
        ),
    ]

    return {
        "schema_version": "operations-digest-v1",
        "provenance": provenance,
        "reference_utc": reference,
        "subscription_id": raw["subscription_id"],
        "client": {
            "name": CLIENT_NAME.strip(),
            "logo_data_uri": CLIENT_LOGO_DATA_URI,
            "logo_alt": CLIENT_LOGO_ALT.strip(),
        },
        "window": window,
        "counts": counts,
        "executive_messages": executive_messages,
        "incidents": incidents,
        "anomalies": anomalies,
        "actions": actions,
        "resources": resources,
        "extensions": raw.get("extensions", []),
        "advisor": advisor_rows,
        "sources": sources,
        "methodology": {
            "read_only": True,
            "official_sla_calculation": False,
            "scheduled_cadence_cron": "30 8 1 * *",
            "scheduled_default_period": "previous_month",
            "supported_periods": list(PERIODS),
            "evidence_streams": [
                "arg_alerts_incidents (microsoft.alertsmanagement/alerts)",
                "arm_service_health (Microsoft.ResourceHealth/events)",
                "arg_posture_anomalies & arg_guest_extensions (Azure Resource Graph)",
                "logs_telemetry_anomalies (Log Analytics InsightsMetrics, Perf, Heartbeat)",
                "arm_advisor_recommendations (Microsoft.Advisor/recommendations)",
            ],
            "limitations": [
                "Las alertas nativas y eventos de Service Health reflejan el estado y marcas temporales registradas por Azure Monitor y Resource Health en el momento de la consulta.",
                "El estado de extensiones y agentes Azure Arc en Azure Resource Graph es una observación de plano de control; no lee settings protegidos ni ejecuta comandos dentro del sistema operativo huésped.",
                "Las anomalías de telemetría se calculan sobre los espacios Log Analytics aprobados para los recursos que emiten InsightsMetrics, Perf o Heartbeat en la ventana.",
                "Las acciones recomendadas constituyen una guía operativa priorizada para revisión humana; el agente opera estrictamente en modo solo lectura.",
            ],
        },
    }


def collection_disclosure(snapshot):
    return {
        "reference_utc": snapshot["reference_utc"],
        "fresh_collection": True,
        "provenance": snapshot["provenance"],
        "subscription_id": snapshot["subscription_id"],
        "window": snapshot["window"],
        "source_status_counts": dict(Counter(s["status"] for s in snapshot["sources"])),
        "source_total": len(snapshot["sources"]),
        "source_details_view": "coverage",
        "paging_basis": "Local offset in this fresh collection; not a persistent cross-call cursor.",
    }


def summary_row(snapshot):
    return {
        "subscription_id": snapshot["subscription_id"],
        "reference_utc": snapshot["reference_utc"],
        "window": snapshot["window"],
        "counts": snapshot["counts"],
        "executive_messages": snapshot["executive_messages"],
        "official_sla_calculation": False,
    }


def snapshot_rows(snapshot, view):
    return {
        "summary": [summary_row(snapshot)],
        "incidents": snapshot["incidents"],
        "anomalies": snapshot["anomalies"],
        "actions": snapshot["actions"],
        "resources": snapshot["resources"],
        "advisor": snapshot["advisor"],
        "coverage": snapshot["sources"],
    }[view]


def query_snapshot(snapshot, params):
    view = params["view"]
    rows = snapshot_rows(snapshot, view)

    def matches(row):
        if params["category"] != "all" and row.get("category") != params["category"]:
            return False
        if params["severity"] != "all" and row.get("severity") != params["severity"]:
            return False
        if params["resource_name"]:
            target = params["resource_name"].lower()
            rname = str(row.get("resource_name") or row.get("name") or "").lower()
            if target != rname and target not in rname:
                return False
        return True

    matched = [row for row in rows if matches(row)]
    selected = matched[params["offset"]:params["offset"] + params["limit"]]
    partial = any(s["status"] not in ("complete", "not_configured") for s in snapshot["sources"])
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
                "message": "A single row exceeds the 3500-byte JSON transport budget; inspect the full snapshot JSON.",
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
    escaped = (
        document.replace("&", "\\u0026")
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("\u2028", "\\u2028")
        .replace("\u2029", "\\u2029")
    )
    if json.loads(escaped) != snapshot:
        raise EvidenceError("round_trip_failed", "Embedded JSON failed lossless round-trip verification.", "renderer")
    return escaped


def render_html(snapshot):
    if HTML_TEMPLATE.count("__REPORT_DATA_JSON__") != 1:
        raise EvidenceError("template_missing", "Build the HTML template into the standalone tool with build_tool.py.", "renderer")
    validate_logo(snapshot["client"]["logo_data_uri"], snapshot["client"].get("logo_alt", CLIENT_LOGO_ALT))
    return HTML_TEMPLATE.replace("__REPORT_DATA_JSON__", safe_json(snapshot))


def csv_cell(value):
    if value is None:
        return ""
    text_val = json.dumps(value, ensure_ascii=False, allow_nan=False, separators=(",", ":")) if isinstance(value, (dict, list)) else str(value)
    return "'" + text_val if text_val.lstrip().startswith(("=", "+", "-", "@", "\t", "\r", "\n")) else text_val


def csv_document(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.writer(stream)
    writer.writerow(fields)
    for row in rows:
        writer.writerow([csv_cell(row.get(field)) for field in fields])
    return stream.getvalue()


def incidents_and_anomalies_csv_rows(snapshot):
    rows = []
    for inc in snapshot["incidents"]:
        rows.append({
            "record_kind": "incident",
            "id": inc["id"],
            "category": inc["category"],
            "severity": inc["severity"],
            "state_or_kind": inc["monitor_condition"] + " / " + inc["state"],
            "title": inc["title"],
            "resource_name": inc["resource_name"],
            "resource_group": inc["resource_group"],
            "resource_type": inc["resource_type"],
            "resource_id": inc["resource_id"],
            "metric_or_signal": inc["signal_type"],
            "observed_value": inc["native_severity"],
            "baseline_or_expected": "NoAlert",
            "unit": "Signal",
            "observed_at_utc": inc["last_updated_utc"],
            "source_id": inc["source_id"],
            "summary": inc["summary"],
            "learn_url": inc["learn_url"],
            "details_json": inc,
        })
    for anom in snapshot["anomalies"]:
        rows.append({
            "record_kind": "anomaly",
            "id": anom["id"],
            "category": anom["category"],
            "severity": anom["severity"],
            "state_or_kind": anom["anomaly_kind"],
            "title": anom["title"],
            "resource_name": anom["resource_name"],
            "resource_group": anom["resource_group"],
            "resource_type": anom["resource_type"],
            "resource_id": anom["resource_id"],
            "metric_or_signal": anom["metric_or_field"],
            "observed_value": anom["observed_value"],
            "baseline_or_expected": anom["baseline_or_expected"],
            "unit": anom["unit"],
            "observed_at_utc": anom["observed_at_utc"],
            "source_id": anom["source_id"],
            "summary": anom["summary"],
            "learn_url": anom["learn_url"],
            "details_json": anom,
        })
    return rows


def actions_csv_rows(snapshot):
    return [
        {
            **act,
            "details_json": act,
        }
        for act in snapshot["actions"]
    ]


def artifact_directory():
    try:
        cwd = Path.cwd()
        root = cwd.resolve(strict=True)
        linked = any(part.is_symlink() or getattr(part, "is_junction", lambda: False)() for part in (cwd, *cwd.parents))
    except (OSError, RuntimeError) as exc:
        raise EvidenceError("unsafe_artifact_root", "Runtime cwd must resolve to an existing directory.", "artifact_storage") from exc
    if root == Path(root.anchor) or not root.is_dir() or linked:
        raise EvidenceError("unsafe_artifact_root", "Filesystem roots, symlink/junction cwd ancestors, and non-directories are forbidden.", "artifact_storage")
    if OUTPUT_DIRECTORY != "operations-digest-reports":
        raise EvidenceError("unsafe_artifact_directory", "Only the fixed operations-digest-reports child directory is allowed.", "artifact_storage")
    directory = root / OUTPUT_DIRECTORY
    if directory.is_symlink() or getattr(directory, "is_junction", lambda: False)() or directory.resolve() != directory:
        raise EvidenceError("unsafe_artifact_directory", "Output directory is a symlink/junction or escapes cwd.", "artifact_storage")
    return root, directory


def sharing_fields(root, paths):
    result = {"sharing_mode": "local_files_only", "http_verified": False}
    match = re.fullmatch(
        r"/(?:root/sreagent|usr)/terminalRoot/tmp/ThreadFiles/([0-9a-fA-F-]{36})",
        root.as_posix(),
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
        "incidents_csv_path": "-incidents.csv",
        "actions_csv_path": "-actions.csv",
    }
    if set(paths) != set(suffixes):
        raise EvidenceError("unsafe_sharing_path", "Native delivery requires all four guarded report artifacts.", "artifact_storage")
    stem = paths["report_path"].name.removesuffix(".html")
    if not re.fullmatch(r"ops-digest-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}", stem):
        raise EvidenceError("unsafe_sharing_path", "Native aliases require this tool's generated ops-digest run filenames.", "artifact_storage")
    expected = root / "operations-digest-reports"
    aliases = {}
    for key, path in paths.items():
        if path.parent != expected or path.name != stem + suffixes[key]:
            raise EvidenceError("unsafe_sharing_path", "Native aliases must reference the same run in operations-digest-reports.", "artifact_storage")
        aliases[key.removesuffix("_path") + "_url"] = (
            "/api/files/tmp/ThreadFiles/" + match[1] + "/operations-digest-reports/" + quote(path.name, safe="")
        )
    return {**result, "sharing_mode": "native_ui", **aliases}


def report_envelope(snapshot, paths, root):
    partial = any(s["status"] not in ("complete", "not_configured") for s in snapshot["sources"])
    result = {
        "status": "partial" if partial else "ok",
        "operation": "report",
        "artifact_status": "written",
        **sharing_fields(root, paths),
        "collection": collection_disclosure(snapshot),
        "counts": snapshot["counts"],
        **{key: str(path) for key, path in paths.items()},
    }
    return ensure_response(result)


def write_report(snapshot):
    root, directory = artifact_directory()
    ref_compact = snapshot["reference_utc"].replace(":", "").replace("-", "")
    prefix = "ops-digest-" + ref_compact + "-" + uuid4().hex[:12]
    paths = {
        key: directory / (prefix + suffix)
        for key, suffix in (
            ("report_path", ".html"),
            ("snapshot_path", "-snapshot.json"),
            ("incidents_csv_path", "-incidents.csv"),
            ("actions_csv_path", "-actions.csv"),
        )
    }
    response = report_envelope(snapshot, paths, root)
    snapshot_document = json.dumps(snapshot, ensure_ascii=False, separators=(",", ":"), allow_nan=False)
    if json.loads(snapshot_document) != snapshot:
        raise EvidenceError("round_trip_failed", "Full normalized snapshot JSON did not round-trip.", "artifact_storage")
    documents = {
        "report_path": render_html(snapshot),
        "snapshot_path": snapshot_document,
        "incidents_csv_path": csv_document(
            incidents_and_anomalies_csv_rows(snapshot),
            (
                "record_kind", "id", "category", "severity", "state_or_kind", "title",
                "resource_name", "resource_group", "resource_type", "resource_id",
                "metric_or_signal", "observed_value", "baseline_or_expected", "unit",
                "observed_at_utc", "source_id", "summary", "learn_url", "details_json",
            ),
        ),
        "actions_csv_path": csv_document(
            actions_csv_rows(snapshot),
            (
                "priority_rank", "id", "horizon_label", "severity", "category", "title",
                "resource_name", "resource_group", "resource_type", "resource_id",
                "owner_scope", "effort_label", "linked_evidence_ids", "source_ids",
                "evidence_summary", "recommendation", "learn_url", "details_json",
            ),
        ),
    }
    encoded = {key: value.encode("utf-8-sig" if key.endswith("csv_path") else "utf-8") for key, value in documents.items()}
    if any(len(value) > ARTIFACT_BYTES for value in encoded.values()):
        raise EvidenceError("artifact_size_exceeded", "Complete artifacts exceed 4800000 bytes; no files were written.", "artifact_storage")
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
            raise EvidenceError("artifact_readback_failed", "Written artifact bytes differ from prepared content.", "artifact_storage")
        if json.loads(paths["snapshot_path"].read_text(encoding="utf-8")) != snapshot:
            raise EvidenceError("artifact_readback_failed", "Written snapshot JSON differs from normalized data.", "artifact_storage")
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
                "Artifact write failed and cleanup failed for: " + ", ".join(failures),
                "artifact_storage",
            ) from exc
        if isinstance(exc, EvidenceError):
            raise
        raise EvidenceError("artifact_write_failed", "Could not atomically write all four artifacts.", "artifact_storage") from exc
    return response


def main(
    operation: str = "report",
    period: str = "previous_month",
    view: str = "summary",
    category: str = "all",
    severity: str = "all",
    resource_name: str = "",
    limit: int = 25,
    offset: int = 0,
) -> dict:
    """Generate the periodic Azure Operations Digest (incidents, anomalies, and prioritized actions) or query views."""
    try:
        reference = utc_now()
        params = validate_parameters(
            operation=operation,
            period=period,
            view=view,
            category=category,
            severity=severity,
            resource_name=resource_name,
            limit=limit,
            offset=offset,
            reference_utc=reference,
        )
        config = validate_config()
        if operation == "report" and HTML_TEMPLATE.count("__REPORT_DATA_JSON__") != 1:
            raise EvidenceError("template_missing", "Use the built standalone tool with embedded HTML_TEMPLATE.", "renderer")
        raw = collect_live(config, params["window"], reference)
        snapshot = finish_snapshot(raw, params["window"], reference, provenance="LIVE")
        return query_snapshot(snapshot, params) if operation == "query" else write_report(snapshot)
    except EvidenceError as exc:
        return ensure_response({
            "status": "error",
            "error": exc.public(),
            "artifact_status": "cleanup_failed" if exc.code == "artifact_cleanup_failed" else "not_written",
            "provenance": "LIVE",
        })
