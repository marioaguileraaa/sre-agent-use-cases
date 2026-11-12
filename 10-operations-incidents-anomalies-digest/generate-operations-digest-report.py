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
    ': #FC4C00;\n  --brand-orange-text: #C23800;\n  --brand-orange-wash: #FFF2EC;\n  --brand-orange-line: #F'
    'FC9AE;\n  --slate-topbar: #141B24;\n  --slate-header: #1C2532;\n  --bg-page: #F6F5F2;\n  --bg-panel: #FF'
    'FFFF;\n  --bg-subtle: #F1EEE8;\n  --bg-row-hover: #FAF8F4;\n  --ink-primary: #141B24;\n  --ink-secondary'
    ': #3E4C5E;\n  --ink-muted: #5A687A;\n  --border-hairline: #DEDCD6;\n  --border-strong: #9AA5B5;\n  --her'
    'o-bg: #1C2532;\n  --hero-deep: #141B24;\n  --hero-ink: #E6EBF1;\n  --hero-muted: #C3CCD8;\n  --hero-line'
    ': rgba(255, 255, 255, 0.18);\n  --sev-critical: #B42318;\n  --sev-critical-bg: #FEE4E2;\n  --sev-critic'
    'al-bar: #D92D20;\n  --sev-high: #B93815;\n  --sev-high-bg: #FFEAD5;\n  --sev-high-bar: #EF6820;\n  --sev'
    '-medium: #93370D;\n  --sev-medium-bg: #FEF0C7;\n  --sev-medium-bar: #F79009;\n  --sev-low: #175CD3;\n  -'
    '-sev-low-bg: #D1E9FF;\n  --sev-low-bar: #2E90FA;\n  --sev-info: #344054;\n  --sev-info-bg: #EAECF0;\n  -'
    '-sev-info-bar: #98A2B3;\n  --ok: #067647;\n  --ok-bg: #DCFAE6;\n  --note-bg: #FFFAEB;\n  --note-line: #F'
    'EDF89;\n  --note-ink: #7A2E0E;\n  --chart: #3E4C5E;\n  --edge: rgba(20, 27, 36, 0.18);\n  --shadow-card:'
    " 0 1px 2px rgba(20, 27, 36, 0.04), 0 6px 20px rgba(20, 27, 36, 0.06);\n  --font-sans: 'Outfit', 'Sego"
    "e UI', system-ui, -apple-system, sans-serif;\n  --font-mono: 'Consolas', ui-monospace, 'Cascadia Mono"
    '\', monospace;\n  color-scheme: light;\n}\n\nhtml[data-theme="dark"] {\n  --brand-orange: #FF5C14;\n  --bra'
    'nd-orange-alt: #FF6B2B;\n  --brand-orange-text: #FF8854;\n  --brand-orange-wash: #2B1A12;\n  --brand-or'
    'ange-line: #6E3417;\n  --slate-topbar: #0B0F15;\n  --slate-header: #121923;\n  --bg-page: #0F141B;\n  --'
    'bg-panel: #161E29;\n  --bg-subtle: #1D2736;\n  --bg-row-hover: #1B2431;\n  --ink-primary: #F3F5F8;\n  --'
    'ink-secondary: #CBD5E1;\n  --ink-muted: #9AA8BA;\n  --border-hairline: #2A3647;\n  --border-strong: #47'
    '5569;\n  --hero-bg: #121923;\n  --hero-deep: #0B0F15;\n  --hero-muted: #B8C3D1;\n  --hero-line: rgba(255'
    ', 255, 255, 0.14);\n  --sev-critical: #FDA29B;\n  --sev-critical-bg: rgba(217, 45, 32, 0.22);\n  --sev-'
    'high: #F9B87F;\n  --sev-high-bg: rgba(239, 104, 32, 0.22);\n  --sev-medium: #FEC84B;\n  --sev-medium-bg'
    ': rgba(247, 144, 9, 0.18);\n  --sev-low: #84CAFF;\n  --sev-low-bg: rgba(46, 144, 250, 0.2);\n  --sev-in'
    'fo: #D0D5DD;\n  --sev-info-bg: rgba(152, 162, 179, 0.2);\n  --ok: #75E0A7;\n  --ok-bg: rgba(23, 178, 10'
    '6, 0.18);\n  --note-bg: #2A2212;\n  --note-line: #6B571E;\n  --note-ink: #FDE68A;\n  --chart: #9AA8BA;\n '
    ' --edge: rgba(0, 0, 0, 0.55);\n  --shadow-card: 0 1px 2px rgba(0, 0, 0, 0.3), 0 8px 24px rgba(0, 0, 0'
    ', 0.25);\n  color-scheme: dark;\n}\n\n*, *::before, *::after { box-sizing: border-box; }\nhtml { scroll-b'
    'ehavior: smooth; scrollbar-color: var(--border-strong) var(--bg-page); -webkit-text-size-adjust: 100'
    '%; }\nbody { margin: 0; background: var(--bg-page); color: var(--ink-primary); font: 15px/1.55 var(--'
    'font-sans); font-variant-numeric: tabular-nums; -webkit-font-smoothing: antialiased; }\n::selection {'
    ' background: #FFD9C7; color: #141B24; }\na { color: var(--brand-orange-text); text-decoration-thickne'
    'ss: 1px; text-underline-offset: 3px; }\na:hover { text-decoration-thickness: 2px; }\n:focus-visible { '
    'outline: 2px solid var(--brand-orange); outline-offset: 2px; }\nbutton, input, select { font: inherit'
    '; color: inherit; }\ncode { font-family: var(--font-mono); font-size: 0.86em; }\np, li { text-wrap: pr'
    'etty; }\nh2, h3 { text-wrap: balance; }\nsvg { flex: none; }\n.sr-only { position: absolute; width: 1px'
    '; height: 1px; padding: 0; margin: -1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap;'
    ' border: 0; }\n.skip-link { position: absolute; left: 16px; top: -60px; z-index: 60; padding: 8px 14p'
    'x; border-radius: 8px; background: var(--bg-panel); color: var(--ink-primary); font-weight: 600; box'
    '-shadow: var(--shadow-card); }\n.skip-link:focus { top: 12px; }\n.print-only { display: none; }\n.print'
    '-only:empty { display: none !important; }\n\n/* Top bar */\n.topbar { position: sticky; top: 0; z-index'
    ': 40; background-color: var(--slate-topbar); color: #FFFFFF; border-bottom: 2px solid var(--brand-or'
    'ange); }\n.topbar-inner { max-width: 1400px; min-height: 58px; margin: 0 auto; padding: 8px 40px; dis'
    'play: flex; align-items: center; gap: 16px; }\n.brand { display: flex; align-items: center; gap: 12px'
    '; min-width: 0; color: #FFFFFF; text-decoration: none; }\n.client-plaque { flex-shrink: 0; display: i'
    'nline-flex; align-items: center; gap: 8px; min-height: 32px; padding: 4px 10px; border-radius: 6px; '
    'background: #FFFFFF; color: #141B24; }\n.client-plaque img { display: block; max-height: 24px; width:'
    ' auto; }\n.client-name-label { font-size: 13px; font-weight: 700; letter-spacing: 0.02em; }\n.brand-te'
    'xt { display: flex; flex-direction: column; min-width: 0; line-height: 1.2; }\n.brand-text b { font-s'
    'ize: 15px; font-weight: 700; white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }\n.bran'
    'd-text span { font-size: 12.5px; color: #C3CCD8; white-space: nowrap; overflow: hidden; text-overflo'
    'w: ellipsis; }\n.section-nav { display: flex; gap: 2px; margin-left: 12px; }\n.section-nav a { padding'
    ': 7px 10px; border-radius: 6px; color: #D5DCE5; font-size: 13.5px; font-weight: 600; text-decoration'
    ': none; white-space: nowrap; }\n.section-nav a:hover { background: rgba(255, 255, 255, 0.08); color: '
    '#FFFFFF; }\n.section-nav a[aria-current="true"] { color: #FFFFFF; box-shadow: inset 0 -2px 0 var(--br'
    'and-orange); border-radius: 6px 6px 0 0; }\n.section-nav .n { margin-left: 5px; color: #9FB0C3; font-'
    'weight: 500; }\n.toolbar-actions { margin-left: auto; display: flex; align-items: center; gap: 8px; f'
    'lex-shrink: 0; }\n.chip-ro { padding: 4px 11px; border: 1px solid rgba(255, 255, 255, 0.24); border-r'
    'adius: 999px; color: #D5DCE5; font-size: 12.5px; font-weight: 600; white-space: nowrap; }\n.btn { dis'
    'play: inline-flex; align-items: center; justify-content: center; gap: 8px; min-height: 38px; padding'
    ': 0 14px; border: 1px solid transparent; border-radius: 8px; font-size: 13.5px; font-weight: 600; li'
    'ne-height: 1.2; white-space: nowrap; cursor: pointer; text-decoration: none; transition: background-'
    'color 150ms ease, border-color 150ms ease, filter 150ms ease; }\n.btn svg { width: 16px; height: 16px'
    '; }\n.btn-bar { background: transparent; color: #F3F5F8; border-color: rgba(255, 255, 255, 0.26); }\n.'
    'btn-bar:hover { background: rgba(255, 255, 255, 0.08); border-color: rgba(255, 255, 255, 0.45); }\n.b'
    'tn-primary { background: var(--brand-orange); border-color: var(--brand-orange); color: #141B24; }\n.'
    'btn-primary:hover { filter: brightness(1.07); }\n.btn-ghost { background: var(--bg-panel); color: var'
    '(--ink-primary); border-color: var(--border-strong); }\n.btn-ghost:hover { background: var(--bg-subtl'
    'e); border-color: var(--ink-secondary); }\n.btn-bar:focus-visible, .btn-primary:focus-visible { outli'
    'ne-color: #FFFFFF; }\n\n/* Hero */\n.hero { background: linear-gradient(160deg, var(--hero-bg) 0%, var('
    '--hero-deep) 100%); color: var(--hero-ink); padding: 44px 40px 100px; }\n.hero-in { max-width: 1320px'
    '; margin: 0 auto; display: grid; grid-template-columns: minmax(0, 1fr) 340px; gap: 20px 48px; align-'
    'items: start; }\n.hero h1 { margin: 0; max-width: 24ch; color: #FFFFFF; font-size: 42px; line-height:'
    ' 1.1; font-weight: 700; letter-spacing: -0.02em; text-wrap: balance; }\n.hero-scope { margin: 10px 0 '
    '0; color: var(--hero-muted); font-size: 15px; }\n.hero-lead { margin: 16px 0 0; max-width: 68ch; font'
    '-size: 17px; line-height: 1.55; }\n.hero-lead b { color: #FFFFFF; font-weight: 700; }\n.meta { display'
    ': flex; flex-wrap: wrap; gap: 8px; margin: 20px 0 0; padding: 0; list-style: none; }\n.meta li { max-'
    'width: 100%; padding: 4px 11px; border: 1px solid var(--hero-line); border-radius: 999px; color: var'
    '(--hero-muted); font-size: 12.5px; overflow-wrap: anywhere; }\n.meta li.on { color: #FFFFFF; font-wei'
    'ght: 600; border-color: rgba(255, 255, 255, 0.42); }\n.meta li.warn { color: #FEDF89; font-weight: 60'
    '0; border-color: rgba(254, 223, 137, 0.5); }\n.verdict { padding: 20px 22px; border: 1px solid var(--'
    'verdict-line, var(--hero-line)); border-radius: 14px; background: rgba(255, 255, 255, 0.05); }\n.verd'
    'ict .k { color: var(--hero-muted); font-size: 13px; font-weight: 600; }\n.verdict b { display: block;'
    ' margin-top: 6px; color: var(--verdict-ink, #FFFFFF); font-size: 28px; line-height: 1.15; font-weigh'
    't: 700; }\n.verdict p { margin: 8px 0 0; color: var(--hero-muted); font-size: 14px; }\n.verdict p + p '
    '{ margin-top: 4px; }\n.verdict.crit { --verdict-ink: #FFB4AB; --verdict-line: rgba(255, 180, 171, 0.5'
    '); }\n.verdict.warn { --verdict-ink: #FEDF89; --verdict-line: rgba(254, 223, 137, 0.5); }\n.verdict.ok'
    ' { --verdict-ink: #A6F4C5; --verdict-line: rgba(166, 244, 197, 0.45); }\n.dist { grid-column: 1 / -1;'
    ' margin-top: 4px; }\n.dist-head { display: flex; justify-content: space-between; gap: 12px; margin-bo'
    'ttom: 8px; color: var(--hero-muted); font-size: 13px; }\n.track { display: flex; height: 12px; overfl'
    'ow: hidden; border-radius: 999px; background: rgba(255, 255, 255, 0.12); }\n.track i { display: block'
    '; height: 100%; }\n.legend { display: flex; flex-wrap: wrap; gap: 6px 18px; margin-top: 10px; color: '
    'var(--hero-muted); font-size: 13px; }\n.legend span { display: inline-flex; align-items: center; gap:'
    ' 7px; }\n.legend i { width: 10px; height: 10px; border-radius: 3px; }\n.legend b { color: #FFFFFF; }\n\n'
    '/* Page body */\n.page { max-width: 1320px; margin: 0 auto; padding: 0 40px 56px; }\n.kpis { position:'
    ' relative; z-index: 2; display: grid; grid-template-columns: repeat(6, minmax(0, 1fr)); gap: 12px; m'
    'argin-top: -60px; }\n.kpi { min-width: 0; padding: 16px 18px 18px; border: 1px solid var(--border-hai'
    'rline); border-radius: 12px; background: var(--bg-panel); box-shadow: var(--shadow-card); }\n.kpi .v '
    '{ font-size: 36px; line-height: 1; font-weight: 700; letter-spacing: -0.02em; }\n.kpi .l { margin-top'
    ': 10px; font-size: 14px; line-height: 1.35; font-weight: 600; }\n.kpi .d { margin-top: 4px; color: va'
    'r(--ink-muted); font-size: 12.5px; line-height: 1.4; }\n.notes { display: grid; gap: 10px; margin-top'
    ': 16px; }\n.notes:empty { display: none; }\n.note { display: flex; align-items: flex-start; gap: 10px;'
    ' padding: 11px 16px; border: 1px solid var(--note-line); border-radius: 10px; background: var(--note'
    '-bg); color: var(--note-ink); font-size: 14px; font-weight: 500; }\n.note svg { width: 18px; height: '
    '18px; margin-top: 1px; }\n.note a { color: inherit; font-weight: 700; }\n.note.sim { background: repea'
    'ting-linear-gradient(135deg, var(--note-bg) 0 12px, rgba(254, 223, 137, 0.07) 12px 24px), var(--note'
    '-bg); }\nhtml:not([data-theme="dark"]) .note.sim { background: repeating-linear-gradient(135deg, #FFF'
    'AEB 0 12px, #FEF0C7 12px 24px); }\n.sec { margin-top: 48px; scroll-margin-top: 80px; }\n.sh { display:'
    ' flex; flex-wrap: wrap; justify-content: space-between; align-items: flex-end; gap: 8px 24px; margin'
    '-bottom: 14px; }\n.sh h2 { margin: 0; font-size: 22px; line-height: 1.3; font-weight: 700; letter-spa'
    'cing: -0.01em; }\n.sh h3 { margin: 0; font-size: 18px; line-height: 1.3; font-weight: 700; }\n.sub-sh '
    '{ margin-top: 32px; }\n.why { margin: 4px 0 0; max-width: 75ch; color: var(--ink-muted); font-size: 1'
    '4px; }\n.count { margin: 0; color: var(--ink-secondary); font-size: 13.5px; white-space: nowrap; }\n.c'
    'ount strong { color: var(--ink-primary); }\n.card { min-width: 0; padding: 20px 22px; border: 1px sol'
    'id var(--border-hairline); border-radius: 12px; background: var(--bg-panel); box-shadow: var(--shado'
    'w-card); }\n.card h3 { margin: 0; font-size: 16.5px; line-height: 1.3; font-weight: 700; }\n.card .sub'
    ' { margin: 4px 0 14px; color: var(--ink-muted); font-size: 13.5px; }\n.grid2 { display: grid; grid-te'
    'mplate-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }\n.mt { margin-top: 16px; }\n\n/* Overview */\n.t'
    'iles { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; margin-bottom: 6p'
    'x; }\n.tile { display: flex; flex-direction: column; align-items: flex-start; gap: 4px; padding: 12px'
    ' 14px; border: 1px solid transparent; border-radius: 10px; background: var(--bg-subtle); text-align:'
    ' left; cursor: pointer; transition: border-color 150ms ease; }\n.tile:hover { border-color: var(--bor'
    'der-strong); }\n.tile b { font-size: 28px; line-height: 1; font-weight: 700; }\n.tile span { color: va'
    'r(--ink-secondary); font-size: 12.5px; line-height: 1.35; }\n.tile.imm { border-color: var(--brand-or'
    'ange-line); background: var(--brand-orange-wash); }\n.tile.imm b { color: var(--brand-orange-text); }'
    '\n.todo { margin: 0; padding: 0; list-style: none; }\n.todo li { display: grid; grid-template-columns:'
    ' 28px minmax(0, 1fr); gap: 10px; padding: 11px 0; border-top: 1px solid var(--border-hairline); }\n.t'
    'odo li > div { min-width: 0; overflow-wrap: anywhere; }\n.todo .rk { color: var(--ink-muted); font-si'
    'ze: 15px; font-weight: 700; }\n.todo .t { font-size: 14px; line-height: 1.4; font-weight: 600; }\n.tod'
    'o .m { display: flex; flex-wrap: wrap; align-items: center; gap: 6px 10px; margin-top: 5px; color: v'
    'ar(--ink-muted); font-size: 12.5px; }\n.todo .m > span:last-child { min-width: 0; }\n.more-link { disp'
    'lay: inline-block; margin-top: 4px; font-size: 14px; font-weight: 600; }\n.exec-list { margin: 0; pad'
    'ding-left: 18px; max-width: 75ch; }\n.exec-list li { margin: 0 0 8px; font-size: 14.5px; line-height:'
    ' 1.55; }\n.exec-list li::marker { color: var(--ink-muted); }\n.exec-list b { font-weight: 700; }\n.prov'
    ' { display: grid; grid-template-columns: max-content minmax(0, 1fr); gap: 6px 16px; margin: 16px 0 0'
    '; padding-top: 14px; border-top: 1px solid var(--border-hairline); font-size: 13.5px; }\n.prov dt { c'
    'olor: var(--ink-muted); }\n.prov dd { margin: 0; font-weight: 600; overflow-wrap: anywhere; }\n.bars {'
    ' display: grid; gap: 2px; }\n.brow { display: grid; grid-template-columns: minmax(110px, 42%) minmax('
    '0, 1fr) 40px; gap: 12px; align-items: center; width: calc(100% + 16px); margin: 0 -8px; padding: 7px'
    ' 8px; border: 0; border-radius: 8px; background: none; font-size: 14px; text-align: left; cursor: po'
    'inter; }\n.brow:hover { background: var(--bg-subtle); }\n.brow .bl { overflow: hidden; text-overflow: '
    'ellipsis; white-space: nowrap; }\n.brow .bl small { margin-left: 6px; color: var(--ink-muted); font-s'
    'ize: 12.5px; }\n.brow .bt { height: 10px; overflow: hidden; border-radius: 999px; background: var(--b'
    'g-subtle); }\n.brow:hover .bt { background: var(--bg-panel); }\n.brow .bt i { display: block; height: '
    '100%; min-width: 3px; border-radius: 999px; background: var(--chart); }\n.brow b { text-align: right;'
    ' font-weight: 700; }\n.dot { display: inline-block; width: 9px; height: 9px; margin-right: 8px; borde'
    'r-radius: 50%; vertical-align: 0; }\n.empty-note { margin: 0; color: var(--ink-muted); font-size: 14p'
    'x; }\n\n/* Filters */\n.filters { display: grid; grid-template-columns: minmax(220px, 1.5fr) repeat(3, '
    'minmax(170px, 1fr)) auto; gap: 12px; align-items: end; }\n.field { display: flex; flex-direction: col'
    'umn; gap: 6px; min-width: 0; }\n.field label { color: var(--ink-secondary); font-size: 13px; font-wei'
    'ght: 600; }\n.field label code { margin-left: 4px; color: var(--ink-muted); font-weight: 500; }\n.cont'
    'rol { width: 100%; min-height: 40px; padding: 0 12px; border: 1px solid var(--border-strong); border'
    '-radius: 8px; background: var(--bg-panel); color: var(--ink-primary); font-size: 14px; }\n.control::p'
    'laceholder { color: var(--ink-muted); opacity: 1; }\n.control:focus { outline: none; border-color: va'
    'r(--brand-orange-text); box-shadow: 0 0 0 3px rgba(255, 78, 0, 0.22); }\n.filter-foot { display: flex'
    '; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px 24px; margin-top: '
    '16px; padding-top: 14px; border-top: 1px solid var(--border-hairline); }\n.status-line { margin: 0; c'
    'olor: var(--ink-secondary); font-size: 13.5px; }\n.status-line b { color: var(--ink-primary); }\n.down'
    'loads { display: flex; flex-wrap: wrap; align-items: center; gap: 8px; }\n.downloads > span { margin-'
    'right: 2px; color: var(--ink-muted); font-size: 13px; }\n\n/* Tables */\n.table-card { padding: 0; over'
    'flow: hidden; }\n.table-scroll { overflow-x: auto; background: linear-gradient(90deg, var(--bg-panel)'
    ' 30%, transparent) left / 36px 100% no-repeat local, linear-gradient(270deg, var(--bg-panel) 30%, tr'
    'ansparent) right / 36px 100% no-repeat local, radial-gradient(farthest-side at 0 50%, var(--edge), t'
    'ransparent) left / 14px 100% no-repeat scroll, radial-gradient(farthest-side at 100% 50%, var(--edge'
    '), transparent) right / 14px 100% no-repeat scroll; }\n.ledger-table { width: 100%; border-collapse: '
    'collapse; font-size: 13.5px; }\n.ledger-table th { padding: 10px 12px; border-bottom: 1px solid var(-'
    '-border-hairline); background: var(--bg-subtle); color: var(--ink-secondary); font-size: 11.5px; fon'
    't-weight: 700; letter-spacing: 0.04em; line-height: 1.35; text-align: left; text-transform: uppercas'
    'e; vertical-align: bottom; }\n.ledger-table th .hg { white-space: nowrap; }\n.ledger-table td { paddin'
    'g: 12px; border-bottom: 1px solid var(--border-hairline); vertical-align: top; }\n.ledger-table tbody'
    ' tr:last-child td { border-bottom: 0; }\n.ledger-table tbody tr:hover td { background: var(--bg-row-h'
    'over); }\n.ledger-table .n { text-align: right; white-space: nowrap; }\n.ledger-table tr.flash td { ba'
    'ckground: var(--brand-orange-wash); }\n.ledger-table tr[id] { scroll-margin-top: 90px; }\n.ledger-tabl'
    'e tr.pg { display: none; }\n.more-row { display: flex; flex-wrap: wrap; justify-content: center; alig'
    'n-items: center; gap: 8px 16px; padding: 14px 16px; border-top: 1px solid var(--border-hairline); co'
    'lor: var(--ink-muted); font-size: 13px; }\n.more-row[hidden] { display: none; }\n.sort { position: rel'
    'ative; display: inline-block; margin: -4px -16px -4px -6px; padding: 4px 16px 4px 6px; border: 0; bo'
    'rder-radius: 4px; background: none; color: inherit; font: inherit; letter-spacing: inherit; line-hei'
    'ght: inherit; text-align: left; text-transform: inherit; cursor: pointer; }\n.th-print { display: non'
    'e; }\n.sort:hover { color: var(--ink-primary); }\n.sort::after { content: ""; position: absolute; righ'
    't: 4px; bottom: 10px; width: 0; height: 0; border-left: 4px solid transparent; border-right: 4px sol'
    'id transparent; border-top: 5px solid currentColor; opacity: 0; }\n.sort:hover::after { opacity: 0.35'
    '; }\nth[aria-sort="ascending"] .sort::after { opacity: 1; border-top: 0; border-bottom: 5px solid cur'
    'rentColor; }\nth[aria-sort="descending"] .sort::after { opacity: 1; }\nth[aria-sort] { color: var(--in'
    'k-primary); }\n.empty-row td { padding: 22px 16px; color: var(--ink-muted); }\n.pill { display: inline'
    '-flex; align-items: center; gap: 6px; padding: 3px 10px; border-radius: 999px; font-size: 12px; font'
    '-weight: 700; line-height: 1.3; white-space: nowrap; }\n.pill::before { content: ""; width: 7px; heig'
    'ht: 7px; border-radius: 50%; background: currentColor; }\n.pill.critical { color: var(--sev-critical)'
    '; background: var(--sev-critical-bg); }\n.pill.high { color: var(--sev-high); background: var(--sev-h'
    'igh-bg); }\n.pill.medium { color: var(--sev-medium); background: var(--sev-medium-bg); }\n.pill.low { '
    'color: var(--sev-low); background: var(--sev-low-bg); }\n.pill.info { color: var(--sev-info); backgro'
    'und: var(--sev-info-bg); }\n.pill.ok { color: var(--ok); background: var(--ok-bg); }\n.tag { display: '
    'inline-block; padding: 2px 9px; border: 1px solid var(--border-hairline); border-radius: 6px; backgr'
    'ound: var(--bg-subtle); color: var(--ink-secondary); font-size: 12px; font-weight: 600; white-space:'
    ' nowrap; }\n.tag.immediate_24h { border-color: var(--brand-orange-line); background: var(--brand-oran'
    'ge-wash); color: var(--brand-orange-text); }\n.id { color: var(--ink-secondary); font-family: var(--f'
    'ont-mono); font-size: 12.5px; white-space: nowrap; }\n.sm { display: block; margin-top: 3px; color: v'
    'ar(--ink-muted); font-size: 12.5px; line-height: 1.45; }\n.stack > * + * { margin-top: 6px; }\n.res b '
    '{ display: block; font-weight: 600; overflow-wrap: anywhere; }\n.code { color: var(--ink-secondary); '
    'font-family: var(--font-mono); font-size: 12px; }\n.ext { display: inline-flex; align-items: center; '
    'gap: 4px; margin-top: 4px; font-size: 12.5px; font-weight: 600; white-space: nowrap; }\n.ext svg { wi'
    'dth: 12px; height: 12px; }\n.ids { display: flex; flex-wrap: wrap; gap: 4px; }\n.chip-id { padding: 2p'
    'x 7px; border: 1px solid var(--border-hairline); border-radius: 6px; background: var(--bg-subtle); c'
    'olor: var(--ink-secondary); font-family: var(--font-mono); font-size: 12px; text-decoration: none; w'
    'hite-space: nowrap; }\na.chip-id:hover { border-color: var(--brand-orange-text); color: var(--brand-o'
    'range-text); }\n.state { display: inline-flex; align-items: center; gap: 6px; font-weight: 600; white'
    '-space: nowrap; }\n.state::before { content: ""; width: 7px; height: 7px; border-radius: 50%; backgro'
    'und: var(--sev-info-bar); }\n.state.on::before { background: var(--sev-high-bar); }\n.rank { font-size'
    ': 16px; font-weight: 700; }\n.wide { min-width: 280px; overflow-wrap: anywhere; }\n.w3 { min-width: 25'
    '0px; overflow-wrap: anywhere; }\n.w2 { min-width: 170px; overflow-wrap: anywhere; }\n.w1 { min-width: '
    '150px; }\n.nw { white-space: nowrap; }\n.errbox { margin-top: 8px; padding: 8px 10px; border-radius: 8'
    'px; background: var(--sev-critical-bg); color: var(--sev-critical); font-size: 12.5px; line-height: '
    '1.45; }\n.wslist { margin: 6px 0 0; padding: 0; list-style: none; color: var(--ink-muted); font-size:'
    ' 12.5px; }\n.plain-list { margin: 14px 0 0; padding-left: 18px; color: var(--ink-secondary); font-siz'
    'e: 14px; }\n.plain-list li { margin-bottom: 6px; }\n.report-error { margin-top: 24px; }\n\n/* Footer */\n'
    '.foot { max-width: 1320px; margin: 0 auto; padding: 20px 40px 40px; display: flex; flex-wrap: wrap; '
    'justify-content: space-between; gap: 8px 16px; color: var(--ink-muted); font-size: 13px; }\n.foot-in '
    '{ border-top: 1px solid var(--border-hairline); }\n\n.topbar:has(#client-logo-img) .brand-text span { '
    'display: none; }\n@media (max-width: 1300px) {\n  .topbar:has(#client-logo-img) .section-nav { display'
    ': none; }\n}\n@media (max-width: 760px) {\n  .topbar:has(#client-logo-img) .client-name-label { display'
    ': none; }\n}\n@media (max-width: 1360px) {\n  #theme-toggle { min-width: 40px; padding: 0 10px; }\n  #th'
    'eme-toggle .lbl { position: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0)'
    '; white-space: nowrap; }\n}\n@media (max-width: 1220px) {\n  .section-nav { display: none; }\n}\n@media ('
    'max-width: 1100px) {\n  .hero-in { grid-template-columns: minmax(0, 1fr); }\n  .kpis { grid-template-c'
    'olumns: repeat(3, minmax(0, 1fr)); }\n  .grid2 { grid-template-columns: minmax(0, 1fr); }\n  .filters '
    '{ grid-template-columns: repeat(2, minmax(0, 1fr)); }\n}\n@media (max-width: 760px) {\n  .topbar-inner '
    '{ gap: 10px; padding: 8px 16px; }\n  .chip-ro { display: none; }\n  .brand-text span, .btn .lbl { posi'
    'tion: absolute; width: 1px; height: 1px; overflow: hidden; clip: rect(0 0 0 0); white-space: nowrap;'
    ' }\n  .btn-bar, .btn-primary { min-width: 40px; padding: 0 10px; }\n  .hero { padding: 28px 16px 84px;'
    ' }\n  .hero h1 { font-size: 30px; }\n  .hero-lead { font-size: 15.5px; }\n  .verdict b { font-size: 24p'
    'x; }\n  .page { padding: 0 16px 40px; }\n  .kpis { grid-template-columns: repeat(2, minmax(0, 1fr)); g'
    'ap: 10px; margin-top: -56px; }\n  .kpi { padding: 14px; }\n  .kpi .v { font-size: 30px; }\n  .sec { mar'
    'gin-top: 36px; }\n  .sh h2 { font-size: 20px; }\n  .card { padding: 16px; }\n  .tiles { gap: 8px; }\n  .'
    'tile { padding: 10px; }\n  .tile b { font-size: 24px; }\n  .filters { grid-template-columns: minmax(0,'
    ' 1fr); }\n  .brow { grid-template-columns: minmax(0, 1fr) 36px; row-gap: 6px; }\n  .brow .bt { grid-co'
    'lumn: 1 / -1; grid-row: 2; }\n  .foot { padding: 16px 16px 32px; }\n}\n@media (max-width: 360px) {\n  .t'
    'opbar-inner { gap: 8px; padding: 8px 12px; }\n  .brand { gap: 8px; }\n  .client-plaque { padding: 4px '
    '7px; }\n  .client-name-label { font-size: 12px; }\n  .brand-text b { font-size: 13px; }\n}\n@media (max-'
    'width: 340px) {\n  .brand-text { display: none; }\n}\n@media (prefers-reduced-motion: reduce) {\n  html '
    '{ scroll-behavior: auto; }\n  *, *::before, *::after { transition: none !important; animation: none !'
    'important; }\n}\n\n@page { size: A4 landscape; margin: 10mm 10mm 14mm; @bottom-right { content: "Página'
    ' " counter(page) " de " counter(pages); font: 8.5pt \'Segoe UI\', sans-serif; color: #5A687A; } }\n@med'
    'ia print {\n  html, html[data-theme="dark"] {\n    --bg-page: #FFFFFF; --bg-panel: #FFFFFF; --bg-subtl'
    'e: #F1EEE8; --bg-row-hover: #FFFFFF;\n    --ink-primary: #141B24; --ink-secondary: #3E4C5E; --ink-mut'
    'ed: #5A687A;\n    --border-hairline: #DEDCD6; --border-strong: #9AA5B5;\n    --brand-orange-text: #C23'
    '800; --brand-orange-wash: #FFF2EC; --brand-orange-line: #FFC9AE;\n    --hero-bg: #1C2532; --hero-deep'
    ': #141B24; --hero-muted: #C3CCD8;\n    --sev-critical: #B42318; --sev-critical-bg: #FEE4E2; --sev-hig'
    'h: #B93815; --sev-high-bg: #FFEAD5;\n    --sev-medium: #93370D; --sev-medium-bg: #FEF0C7; --sev-low: '
    '#175CD3; --sev-low-bg: #D1E9FF;\n    --sev-info: #344054; --sev-info-bg: #EAECF0; --ok: #067647; --ok'
    '-bg: #DCFAE6;\n    --note-bg: #FFFAEB; --note-line: #FEDF89; --note-ink: #7A2E0E; --chart: #3E4C5E;\n '
    '   color-scheme: light;\n  }\n  * { -webkit-print-color-adjust: exact; print-color-adjust: exact; }\n  '
    'body { background: #FFFFFF; font-size: 11.5px; }\n  .topbar { position: static; background-color: #FF'
    'FFFF; color: #141B24; border-bottom: 0; }\n  .topbar-inner { min-height: 0; padding: 0 0 8px; }\n  .br'
    'and { color: #141B24; }\n  .client-plaque { border: 1px solid #DEDCD6; }\n  .brand-text span { color: '
    '#5A687A; }\n  .chip-ro { display: inline-block; color: #3E4C5E; border-color: #DEDCD6; }\n  .section-n'
    'av, #theme-toggle, #btn-print, .skip-link, #sec-filters, .downloads, .more-link, .more-row { display'
    ': none !important; }\n  .ledger-table tr.pg { display: table-row; }\n  .print-only { display: block; }'
    '\n  .hero { padding: 22px 24px 70px; border-radius: 12px; }\n  .hero h1 { font-size: 30px; max-width: '
    'none; }\n  .hero-lead { font-size: 13.5px; }\n  .hero-in { grid-template-columns: minmax(0, 1fr) 260px'
    '; gap: 14px 28px; }\n  .verdict b { font-size: 21px; }\n  .page { padding: 0; max-width: none; }\n  .kp'
    'is { grid-template-columns: repeat(6, minmax(0, 1fr)); margin-top: -50px; }\n  .kpi .v { font-size: 2'
    '6px; }\n  .kpi, .card, .note, .brow, .verdict, .todo li, .tile, .ledger-table tr { break-inside: avoi'
    'd; }\n  .card.table-card { break-inside: auto; }\n  .card, .kpi { box-shadow: none; }\n  .grid2 { grid-'
    'template-columns: repeat(2, minmax(0, 1fr)); }\n  .sec { margin-top: 20px; }\n  .sh { break-after: avo'
    'id; }\n  .table-card { overflow: visible; }\n  .table-scroll { overflow: visible; background: none; }\n'
    '  .ledger-table { font-size: 10.5px; }\n  .ledger-table th { font-size: 9.5px; padding: 6px 8px; }\n  '
    '.ledger-table td { padding: 6px 8px; overflow-wrap: break-word; }\n  .ledger-table td.wide, .ledger-t'
    'able td.w2, .ledger-table td.w3 { overflow-wrap: anywhere; }\n  .ledger-table thead { display: table-'
    'header-group; }\n  .ledger-table .sm, .ledger-table .ext, .ledger-table .pill, .ledger-table .tag, .l'
    'edger-table .state { font-size: 9.5px; }\n  .ledger-table .id, .ledger-table .code, .ledger-table .ch'
    'ip-id { font-size: 9.5px; }\n  .ledger-table .rank { font-size: 12px; }\n  .brow .bl { white-space: no'
    'rmal; }\n  .brow .bl small { display: block; margin: 1px 0 0 17px; }\n  .wide, .w1, .w2, .w3 { min-wid'
    'th: 0; }\n  .sort { display: none !important; }\n  .th-print { display: inline; }\n  .ext svg { display'
    ': none; }\n  a { text-decoration: none; }\n  .foot { padding: 12px 0 0; max-width: none; }\n}\n</style>\n'
    '</head>\n<body>\n<a class="skip-link" href="#report-body">Saltar al contenido</a>\n<header class="topba'
    'r" id="topbar">\n  <div class="topbar-inner">\n    <a class="brand" href="#top" aria-label="Inicio del'
    ' informe">\n      <span class="client-plaque" id="client-plaque">\n        <span id="client-logo-slot"'
    '></span>\n        <span class="client-name-label" id="client-name-label">CLIENTE</span>\n      </span>'
    '\n      <span class="brand-text"><b>Azure SRE Agent</b><span id="topbar-subtitle">Dossier de operacio'
    'nes</span></span>\n    </a>\n    <nav class="section-nav" id="section-nav" aria-label="Secciones del i'
    'nforme">\n      <a href="#sec-executive">Resumen</a>\n      <a href="#sec-incidents">Incidencias<span '
    'class="n" id="nav-incidents-count">0</span></a>\n      <a href="#sec-anomalies">Anomalías<span class='
    '"n" id="nav-anomalies-count">0</span></a>\n      <a href="#sec-actions">Acciones<span class="n" id="n'
    'av-actions-count">0</span></a>\n      <a href="#sec-resources">Recursos<span class="n" id="nav-resour'
    'ces-count">0</span></a>\n      <a href="#sec-coverage">Cobertura<span class="n" id="nav-sources-count'
    '">0</span></a>\n    </nav>\n    <div class="toolbar-actions">\n      <span class="chip-ro">Solo lectura'
    '</span>\n      <button type="button" class="btn btn-bar" id="theme-toggle" title="Modo oscuro"><svg v'
    'iewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-'
    'linejoin="round" aria-hidden="true"><path d="M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z"/></svg><s'
    'pan class="lbl">Modo oscuro</span></button>\n      <button type="button" class="btn btn-primary" id="'
    'btn-print"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-lineca'
    'p="round" stroke-linejoin="round" aria-hidden="true"><path d="M6 9V3h12v6M6 18H4a2 2 0 0 1-2-2v-5a2 '
    '2 0 0 1 2-2h16a2 2 0 0 1 2 2v5a2 2 0 0 1-2 2h-2M6 14h12v7H6z"/></svg><span class="lbl">Imprimir / PD'
    'F</span></button>\n    </div>\n  </div>\n</header>\n\n<main id="report-body">\n  <section class="hero" id='
    '"top" aria-labelledby="cover-title">\n    <div class="hero-in">\n      <div>\n        <h1 id="cover-tit'
    'le">Incidencias, anomalías y acciones recomendadas</h1>\n        <p class="hero-scope" id="hero-scope'
    '">Informe periódico de operaciones Azure</p>\n        <p class="hero-lead" id="hero-lead"></p>\n      '
    '  <ul class="meta" id="hero-meta" aria-label="Contexto del informe"></ul>\n      </div>\n      <aside '
    'class="verdict" id="verdict-card" aria-label="Veredicto">\n        <div class="k">Veredicto</div>\n   '
    '     <b id="verdict-title">—</b>\n        <p id="verdict-detail"></p>\n        <p id="verdict-sub"></p'
    '>\n      </aside>\n      <div class="dist" id="evidence-distribution-bar">\n        <div class="dist-he'
    'ad"><span>Severidad de incidencias y anomalías</span><span id="dist-total-label">0 señales</span></d'
    'iv>\n        <div class="track" id="dist-track" role="img" aria-label="Distribución por severidad"></'
    'div>\n        <div class="legend" id="dist-legend"></div>\n      </div>\n    </div>\n  </section>\n\n  <di'
    'v class="page">\n    <div class="kpis" id="ledger-summary-grid">\n      <div class="kpi"><div class="v'
    '" id="kpi-native-alerts">0</div><div class="l">Alertas de Azure Monitor</div><div class="d" id="kpi-'
    'native-alerts-sub">alertsmanagementresources</div></div>\n      <div class="kpi"><div class="v" id="k'
    'pi-service-health">0</div><div class="l">Comunicaciones de Service Health</div><div class="d" id="kp'
    'i-service-health-sub">ServiceIssue y PlannedMaintenance</div></div>\n      <div class="kpi"><div clas'
    's="v" id="kpi-posture-anomalies">0</div><div class="l">Anomalías de plano de control y Arc</div><div'
    ' class="d" id="kpi-posture-anomalies-sub">Extensiones fallidas y conectividad</div></div>\n      <div'
    ' class="kpi"><div class="v" id="kpi-telemetry-anomalies">0</div><div class="l">Anomalías de telemetr'
    'ía</div><div class="d" id="kpi-telemetry-anomalies-sub">InsightsMetrics, Perf y Heartbeat</div></div'
    '>\n      <div class="kpi"><div class="v" id="kpi-actions-total">0</div><div class="l">Acciones recome'
    'ndadas</div><div class="d" id="kpi-actions-sub">Priorizadas por horizonte</div></div>\n      <div cla'
    'ss="kpi"><div class="v" id="kpi-resources-total">0</div><div class="l">Recursos en alcance</div><div'
    ' class="d" id="kpi-resources-sub">0 con hallazgos activos</div></div>\n    </div>\n    <div class="not'
    'es" id="status-notes"></div>\n\n    <section class="sec" id="sec-executive" aria-labelledby="h-executi'
    've">\n      <div class="sh"><div><h2 id="h-executive">Resumen del periodo</h2><p class="why">Qué exig'
    'e atención primero y de dónde salen las señales de la ventana evaluada.</p></div></div>\n      <div c'
    'lass="grid2">\n        <div class="card">\n          <h3>Qué hacer ahora</h3>\n          <p class="sub"'
    '>Acciones priorizadas para revisión humana; cada una cita la evidencia que la justifica.</p>\n       '
    '   <div class="tiles" id="horizon-tiles"></div>\n          <ol class="todo" id="top-actions"></ol>\n  '
    '        <a class="more-link" href="#sec-actions" id="all-actions-link">Ver todas las acciones</a>\n  '
    '      </div>\n        <div class="card">\n          <h3>Síntesis ejecutiva</h3>\n          <p class="su'
    'b">Lo esencial del periodo, calculado sobre las fuentes leídas.</p>\n          <ul class="exec-list" '
    'id="executive-messages-list"></ul>\n          <dl class="prov" id="provenance-strip">\n            <dt'
    '>Suscripción Azure</dt><dd class="code" id="prov-subscription">—</dd>\n            <dt>Ventana evalua'
    'da</dt><dd id="prov-window-label">—</dd>\n            <dt>Intervalo UTC exacto</dt><dd id="prov-windo'
    'w-range">—</dd>\n            <dt>Cadencia</dt><dd id="prov-cadence">—</dd>\n            <dt>Origen de '
    'evidencia</dt><dd id="prov-provenance">—</dd>\n            <dt>Referencia UTC</dt><dd id="reference-u'
    'tc-label">—</dd>\n          </dl>\n        </div>\n        <div class="card">\n          <h3>Señales por'
    ' flujo de evidencia</h3>\n          <p class="sub">Cada barra filtra los registros por ese flujo.</p>'
    '\n          <div class="bars" id="stream-bars"></div>\n        </div>\n        <div class="card">\n     '
    '     <h3>Recursos con más señales</h3>\n          <p class="sub">Incidencias más anomalías por recurs'
    'o: el punto de partida de la revisión.</p>\n          <div class="bars" id="resource-bars"></div>\n   '
    '     </div>\n      </div>\n    </section>\n\n    <section class="sec" id="sec-filters" aria-labelledby="'
    'h-filters">\n      <div class="sh"><div><h2 id="h-filters">Filtrar registros</h2><p class="why">Los f'
    'iltros acotan a la vez incidencias, anomalías, acciones, recursos y Advisor. Las descargas incluyen '
    'siempre todos los registros.</p></div></div>\n      <div class="card">\n        <div class="filters">\n'
    '          <div class="field">\n            <label for="filter-search">Buscar</label>\n            <inp'
    'ut type="search" class="control" id="filter-search" placeholder="Recurso, ID, extensión o métrica" a'
    'utocomplete="off">\n          </div>\n          <div class="field">\n            <label for="filter-cat'
    'egory">Flujo de evidencia <code>category</code></label>\n            <select class="control" id="filt'
    'er-category">\n              <option value="all">Todas las categorías</option>\n              <option '
    'value="native_alert">Alertas nativas Azure Monitor</option>\n              <option value="service_hea'
    'lth">Comunicaciones Azure Service Health</option>\n              <option value="extension_failure">Fa'
    'llos de extensión VM / Azure Arc</option>\n              <option value="connectivity_posture">Anomalí'
    'as de conectividad / plano de control</option>\n              <option value="telemetry_anomaly">Anoma'
    'lías de telemetría (CPU / Memoria / Disco / Heartbeat)</option>\n              <option value="advisor'
    '_recommendation">Recomendaciones Azure Advisor</option>\n            </select>\n          </div>\n     '
    '     <div class="field">\n            <label for="filter-severity">Severidad <code>severity</code></l'
    'abel>\n            <select class="control" id="filter-severity">\n              <option value="all">To'
    'das las severidades</option>\n              <option value="critical">Crítica</option>\n              <'
    'option value="high">Alta</option>\n              <option value="medium">Media</option>\n              '
    '<option value="low">Baja</option>\n            </select>\n          </div>\n          <div class="field'
    '">\n            <label for="filter-horizon">Horizonte de acción <code>horizon</code></label>\n        '
    '    <select class="control" id="filter-horizon">\n              <option value="all">Todos los horizon'
    'tes</option>\n              <option value="immediate_24h">Inmediato &lt;24h</option>\n              <o'
    'ption value="short_term_7d">Corto plazo 1-7 días</option>\n              <option value="monthly_cycle'
    '">Ciclo mensual</option>\n            </select>\n          </div>\n          <button type="button" clas'
    's="btn btn-ghost" id="filter-reset">Restablecer</button>\n        </div>\n        <div class="filter-f'
    'oot">\n          <p class="status-line" id="filter-status-summary" aria-live="polite">Mostrando la to'
    'talidad de registros recolectados</p>\n          <div class="downloads">\n            <span>Descargas '
    'locales:</span>\n            <button type="button" class="btn btn-ghost" id="btn-export-json"><svg vi'
    'ewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-l'
    'inejoin="round" aria-hidden="true"><path d="M12 3v12m0 0 5-5m-5 5-5-5M4 21h16"/></svg>JSON completo<'
    '/button>\n            <button type="button" class="btn btn-ghost" id="btn-export-incidents-csv"><svg '
    'viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke'
    '-linejoin="round" aria-hidden="true"><path d="M12 3v12m0 0 5-5m-5 5-5-5M4 21h16"/></svg>CSV incidenc'
    'ias y anomalías</button>\n            <button type="button" class="btn btn-ghost" id="btn-export-acti'
    'ons-csv"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap='
    '"round" stroke-linejoin="round" aria-hidden="true"><path d="M12 3v12m0 0 5-5m-5 5-5-5M4 21h16"/></sv'
    'g>CSV acciones recomendadas</button>\n          </div>\n        </div>\n      </div>\n    </section>\n   '
    ' <p class="print-only status-line" id="print-filter-note"></p>\n\n    <section class="sec" id="sec-inc'
    'idents" aria-labelledby="h-incidents">\n      <div class="sh"><div><h2 id="h-incidents">Incidencias y'
    ' comunicaciones de plataforma</h2><p class="why">Alertas nativas de Azure Monitor y comunicaciones o'
    'ficiales de Service Health de la ventana: lo que ya ocurrió o sigue activo.</p></div><p class="count'
    '"><strong id="incidents-count">0</strong> de <span id="incidents-total">0</span> incidencias</p></di'
    'v>\n      <div class="card table-card"><div class="table-scroll" tabindex="0" role="region" aria-labe'
    'lledby="h-incidents">\n        <table class="ledger-table" id="incidents-table"><caption class="sr-on'
    'ly">Incidencias y comunicaciones de plataforma</caption><thead></thead><tbody id="incidents-tbody"><'
    '/tbody></table>\n      </div></div>\n    </section>\n\n    <section class="sec" id="sec-anomalies" aria-'
    'labelledby="h-anomalies">\n      <div class="sh"><div><h2 id="h-anomalies">Anomalías técnicas</h2><p '
    'class="why">Desviaciones detectadas por el agente: extensiones fallidas, postura de plano de control'
    ' y telemetría fuera de rango.</p></div><p class="count"><strong id="anomalies-count">0</strong> de <'
    'span id="anomalies-total">0</span> anomalías</p></div>\n      <div class="card table-card"><div class'
    '="table-scroll" tabindex="0" role="region" aria-labelledby="h-anomalies">\n        <table class="ledg'
    'er-table" id="anomalies-table"><caption class="sr-only">Anomalías técnicas</caption><thead></thead><'
    'tbody id="anomalies-tbody"></tbody></table>\n      </div></div>\n    </section>\n\n    <section class="s'
    'ec" id="sec-actions" aria-labelledby="h-actions">\n      <div class="sh"><div><h2 id="h-actions">Acci'
    'ones recomendadas priorizadas</h2><p class="why">Plan ordenado por urgencia para revisión humana. Ca'
    'da acción enlaza las evidencias que la justifican; el agente no ejecuta cambios.</p></div><p class="'
    'count"><strong id="actions-count">0</strong> de <span id="actions-total">0</span> acciones</p></div>'
    '\n      <div class="card table-card"><div class="table-scroll" tabindex="0" role="region" aria-labell'
    'edby="h-actions">\n        <table class="ledger-table" id="actions-table"><caption class="sr-only">Ac'
    'ciones recomendadas priorizadas</caption><thead></thead><tbody id="actions-tbody"></tbody></table>\n '
    '     </div></div>\n    </section>\n\n    <section class="sec" id="sec-resources" aria-labelledby="h-res'
    'ources">\n      <div class="sh"><div><h2 id="h-resources">Estado por recurso</h2><p class="why">Cada '
    'recurso inventariado con sus incidencias, anomalías, extensiones y acciones; primero los que tienen '
    'hallazgos activos.</p></div><p class="count"><strong id="resources-count">0</strong> de <span id="re'
    'sources-total">0</span> recursos</p></div>\n      <div class="card table-card"><div class="table-scro'
    'll" tabindex="0" role="region" aria-labelledby="h-resources">\n        <table class="ledger-table" id'
    '="resources-table"><caption class="sr-only">Estado operativo por recurso</caption><thead></thead><tb'
    'ody id="resources-tbody"></tbody></table>\n      </div></div>\n      <div class="sh sub-sh"><div><h3 i'
    'd="h-advisor">Recomendaciones de Azure Advisor</h3><p class="why">Recomendaciones en caché de <code>'
    'arm_advisor_recommendations</code> correlacionadas con el plan de acciones.</p></div><p class="count'
    '"><strong id="advisor-count">0</strong> de <span id="advisor-total">0</span> recomendaciones</p></di'
    'v>\n      <div class="card table-card"><div class="table-scroll" tabindex="0" role="region" aria-labe'
    'lledby="h-advisor">\n        <table class="ledger-table" id="advisor-table"><caption class="sr-only">'
    'Recomendaciones de Azure Advisor</caption><thead></thead><tbody id="advisor-tbody"></tbody></table>\n'
    '      </div></div>\n    </section>\n\n    <section class="sec" id="sec-coverage" aria-labelledby="h-cov'
    'erage">\n      <div class="sh"><div><h2 id="h-coverage">Cobertura de fuentes y método</h2><p class="w'
    'hy">Qué se leyó y con qué resultado. Una fuente parcial es un punto ciego, no un resultado limpio.</'
    'p></div><p class="count"><strong id="sources-count">0</strong> fuentes</p></div>\n      <div class="c'
    'ard table-card"><div class="table-scroll" tabindex="0" role="region" aria-labelledby="h-coverage">\n '
    '       <table class="ledger-table" id="sources-table"><caption class="sr-only">Recibos de cobertura '
    'por fuente</caption><thead></thead><tbody id="sources-tbody"></tbody></table>\n      </div></div>\n   '
    '   <div class="grid2 mt">\n        <div class="card">\n          <h3>Garantías operativas y limitacion'
    'es</h3>\n          <p class="sub">Lo que este informe no afirma.</p>\n          <ul class="exec-list" '
    'id="methodology-list"></ul>\n        </div>\n        <div class="card">\n          <h3>Método</h3>\n    '
    '      <p class="sub">Parámetros de ejecución y flujos de evidencia consultados en modo solo lectura.'
    '</p>\n          <dl class="prov" id="method-facts" style="margin-top:0;padding-top:0;border-top:0"></'
    'dl>\n          <ul class="plain-list mt" id="method-streams"></ul>\n        </div>\n      </div>\n    </'
    'section>\n  </div>\n</main>\n\n<footer class="foot-in"><div class="foot" id="report-footer"><span id="fo'
    'oter-left">Generado por Azure SRE Agent · Solo lectura</span><span id="footer-right"></span></div></'
    'footer>\n\n<script type="application/json" id="report-data">__REPORT_DATA_JSON__</script>\n<script>\n(fu'
    'nction () {\n  "use strict";\n\n  var SEV_RANK = { critical: 0, high: 1, medium: 2, low: 3 };\n  var SEV'
    '_LABEL = { critical: "Crítica", high: "Alta", medium: "Media", low: "Baja" };\n  var SEV_WORDS = { cr'
    'itical: ["crítica", "críticas"], high: ["alta", "altas"], medium: ["media", "medias"], low: ["baja",'
    ' "bajas"] };\n  var SEV_BAR = { critical: "--sev-critical-bar", high: "--sev-high-bar", medium: "--se'
    'v-medium-bar", low: "--sev-low-bar" };\n  var HORIZON_RANK = { immediate_24h: 0, short_term_7d: 1, mo'
    'nthly_cycle: 2 };\n  var STATUS = { complete: ["Completa", "ok"], partial: ["Parcial", "medium"], den'
    'ied: ["Denegada", "critical"], error: ["Error", "critical"], not_configured: ["No configurada", "inf'
    'o"] };\n  var SHORT_CAT = {\n    native_alert: "Alerta Azure Monitor",\n    service_health: "Service He'
    'alth",\n    extension_failure: "Extensión fallida",\n    connectivity_posture: "Plano de control",\n   '
    ' telemetry_anomaly: "Telemetría",\n    advisor_recommendation: "Azure Advisor"\n  };\n  var UNIT = { Pe'
    'rcent: "%", Minutes: "min", MB: "MB", State: "" };\n  var TYPE_LABEL = {\n    "microsoft.compute/virtu'
    'almachines": "Máquina virtual",\n    "microsoft.compute/virtualmachinescalesets": "Conjunto de escala'
    'do de VM",\n    "microsoft.hybridcompute/machines": "Servidor Azure Arc",\n    "microsoft.kubernetes/c'
    'onnectedclusters": "Kubernetes con Azure Arc",\n    "microsoft.containerservice/managedclusters": "Cl'
    'úster AKS",\n    "microsoft.app/containerapps": "Container App",\n    "microsoft.web/sites": "App Serv'
    'ice",\n    "microsoft.web/serverfarms": "Plan de App Service",\n    "microsoft.storage/storageaccounts'
    '": "Cuenta de almacenamiento",\n    "microsoft.keyvault/vaults": "Key Vault",\n    "microsoft.sql/serv'
    'ers/databases": "Base de datos SQL",\n    "microsoft.dbforpostgresql/flexibleservers": "PostgreSQL fl'
    'exible",\n    "microsoft.cache/redis": "Azure Cache for Redis",\n    "microsoft.operationalinsights/wo'
    'rkspaces": "Área de trabajo de Log Analytics",\n    "microsoft.resourcehealth/events": "Service Healt'
    'h"\n  };\n  var PATHS = {\n    ext: "M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 '
    '0 1 1-1h5",\n    alert: "M12 9v4m0 4h.01M10.3 3.9 1.8 18a2 2 0 0 0 1.7 3h17a2 2 0 0 0 1.7-3L13.7 3.9a'
    '2 2 0 0 0-3.4 0Z",\n    moon: "M21 12.8A9 9 0 1 1 11.2 3a7 7 0 0 0 9.8 9.8Z",\n    sun: "M12 3v2M12 19'
    'v2M4.2 4.2l1.4 1.4M18.4 18.4l1.4 1.4M3 12h2M19 12h2M4.2 19.8l1.4-1.4M18.4 5.6l1.4-1.4M12 8a4 4 0 1 0'
    ' 0 8 4 4 0 0 0 0-8Z"\n  };\n  var REDUCED = window.matchMedia && window.matchMedia("(prefers-reduced-m'
    'otion: reduce)").matches;\n\n  function el(tag, attrs, children) {\n    var node = document.createEleme'
    'nt(tag);\n    if (attrs) {\n      Object.keys(attrs).forEach(function (k) {\n        if (k === "classNa'
    'me") {\n          node.className = attrs[k];\n        } else if (k === "textContent") {\n          node'
    '.textContent = attrs[k];\n        } else if (attrs[k] !== null && attrs[k] !== undefined) {\n         '
    ' node.setAttribute(k, String(attrs[k]));\n        }\n      });\n    }\n    (children || []).forEach(func'
    'tion (ch) {\n      if (ch === null || ch === undefined || ch === false) {\n        return;\n      }\n   '
    '   node.appendChild(typeof ch === "string" || typeof ch === "number" ? document.createTextNode(Strin'
    'g(ch)) : ch);\n    });\n    return node;\n  }\n\n  function clear(node) {\n    while (node.firstChild) {\n '
    '     node.removeChild(node.firstChild);\n    }\n  }\n\n  function icon(name) {\n    var ns = "http://www.'
    'w3.org/2000/svg";\n    var svg = document.createElementNS(ns, "svg");\n    var attrs = { viewBox: "0 0'
    ' 24 24", fill: "none", stroke: "currentColor", "stroke-width": "2", "stroke-linecap": "round", "stro'
    'ke-linejoin": "round", "aria-hidden": "true" };\n    Object.keys(attrs).forEach(function (k) { svg.se'
    'tAttribute(k, attrs[k]); });\n    var path = document.createElementNS(ns, "path");\n    path.setAttrib'
    'ute("d", PATHS[name]);\n    svg.appendChild(path);\n    return svg;\n  }\n\n  var dataNode = document.get'
    'ElementById("report-data");\n  var DATA;\n  try {\n    DATA = JSON.parse(dataNode.textContent);\n  } cat'
    'ch (err) {\n    var holder = document.querySelector(".page");\n    clear(holder);\n    holder.appendChi'
    'ld(el("div", { className: "note report-error", role: "alert" }, [icon("alert"), el("span", null, ["N'
    'o se pudo leer el modelo de datos embebido. Genere el informe con la herramienta (operation=\\"report'
    '\\") en lugar de abrir la plantilla directamente."])]));\n    return;\n  }\n  var COUNTS = DATA.counts |'
    '| {};\n\n  function n(value) {\n    var v = Number(value) || 0;\n    return Math.round(v) === v ? String'
    '(v).replace(/\\B(?=(\\d{3})+(?!\\d))/g, "\\u202f") : String(v);\n  }\n\n  function plural(count, one, many)'
    ' {\n    return Number(count) === 1 ? one : many;\n  }\n\n  function b(value) {\n    return el("b", { text'
    'Content: n(value) });\n  }\n\n  function utc(value) {\n    if (!value) {\n      return "—";\n    }\n    ret'
    'urn String(value).replace("T", " ").replace(/:\\d{2}(\\.\\d+)?Z$/, "").replace(/Z$/, "");\n  }\n\n  functi'
    'on plain(value) {\n    if (value === null || value === undefined) {\n      return "";\n    }\n    var s '
    '= String(value);\n    if (!/[<&]/.test(s)) {\n      return s;\n    }\n    var doc = new DOMParser().pars'
    'eFromString(s.replace(/<\\/(p|div|li|h[1-6]|tr|ul|ol)>|<br\\s*\\/?>/gi, " $& "), "text/html");\n    retu'
    'rn (doc.body.textContent || "").replace(/\\s+/g, " ").trim();\n  }\n\n  function breakable(value, cls) {'
    '\n    var span = el("span", { className: cls === undefined ? "code" : cls || null });\n    var buf = "'
    '";\n    String(value === null || value === undefined ? "" : value).split("").forEach(function (ch) {\n'
    '      buf += ch;\n      if ("/.?&=_".indexOf(ch) >= 0) {\n        span.appendChild(document.createText'
    'Node(buf));\n        span.appendChild(document.createElement("wbr"));\n        buf = "";\n      }\n    }'
    ');\n    if (buf) {\n      span.appendChild(document.createTextNode(buf));\n    }\n    return span;\n  }\n\n'
    '  function prose(value) {\n    var text = plain(value);\n    var span = el("span");\n    var last = 0;\n'
    '    text.replace(/[A-Za-z)][\\/.](?=[A-Za-z(])/g, function (match, offset) {\n      var cut = offset +'
    ' match.length;\n      span.appendChild(document.createTextNode(text.slice(last, cut)));\n      span.ap'
    'pendChild(document.createElement("wbr"));\n      last = cut;\n      return match;\n    });\n    span.app'
    'endChild(document.createTextNode(text.slice(last)));\n    return span;\n  }\n\n  function withName(text,'
    ' name) {\n    var s = String(text || "");\n    var at = name && name.length <= 32 ? s.indexOf(name) : '
    '-1;\n    if (at < 0) {\n      return [s];\n    }\n    return [s.slice(0, at), el("span", { className: "n'
    'w", textContent: name }), s.slice(at + name.length)];\n  }\n\n  function sevKey(row) {\n    return SEV_R'
    'ANK.hasOwnProperty(row.severity) ? SEV_RANK[row.severity] : 9;\n  }\n\n  function pill(sev, label, titl'
    'e) {\n    var tone = SEV_RANK.hasOwnProperty(sev) || sev === "ok" || sev === "info" ? sev : "info";\n '
    '   return el("span", { className: "pill " + tone, textContent: label || SEV_LABEL[sev] || String(sev'
    ' || "—"), title: title || null });\n  }\n\n  function extLink(href, label) {\n    if (typeof href !== "s'
    'tring" || !/^https:\\/\\//.test(href)) {\n      return null;\n    }\n    return el("a", { className: "ext'
    '", href: href, target: "_blank", rel: "noopener noreferrer" }, [label, icon("ext")]);\n  }\n\n  functio'
    'n portalUrl(id) {\n    return typeof id === "string" && /^\\/subscriptions\\/[^/]+\\/(resourcegroups|pro'
    'viders)\\/[^?#]+$/i.test(id)\n      ? "https://portal.azure.com/#@/resource" + id\n      : null;\n  }\n\n '
    ' function typeLabel(type) {\n    var t = String(type || "").toLowerCase();\n    return TYPE_LABEL[t] |'
    '| t.split("/").pop() || "";\n  }\n\n  function rgLabel(rg) {\n    return rg === "subscription-scope" ? "'
    'Ámbito de suscripción" : (rg || "");\n  }\n\n  function resourceCell(name, rg, type, id, extra) {\n    v'
    'ar meta = [rgLabel(rg), type ? typeLabel(type) : "", extra || ""].filter(Boolean).join(" · ");\n    r'
    'eturn el("div", { className: "res", title: id || null }, [\n      el("b", { textContent: name || "—" '
    '}),\n      meta ? el("span", { className: "sm", textContent: meta, title: type || null }) : null,\n   '
    '   portalUrl(id) ? extLink(portalUrl(id), "Portal") : null\n    ]);\n  }\n\n  function idCell(row) {\n   '
    ' return [el("span", { className: "id", textContent: row.id }), el("span", { className: "sm", textCon'
    'tent: SHORT_CAT[row.category] || row.category_label || "", title: row.category_label || null })];\n  '
    '}\n\n  function withUnit(value, unit) {\n    var u = UNIT.hasOwnProperty(unit) ? UNIT[unit] : (unit || '
    '"");\n    var text = typeof value === "number" ? n(value) : String(value === null || value === undefi'
    'ned ? "—" : value);\n    return u ? text + "\\u00a0" + u : text;\n  }\n\n  /* ---------- Header, hero and'
    ' KPIs ---------- */\n\n  function renderBranding() {\n    var client = DATA.client || {};\n    var nameL'
    'abel = document.getElementById("client-name-label");\n    var logoSlot = document.getElementById("cli'
    'ent-logo-slot");\n    clear(logoSlot);\n    nameLabel.textContent = client.name || "CLIENTE";\n    if ('
    'client.logo_data_uri && /^data:image\\/(png|jpeg);base64,/.test(client.logo_data_uri)) {\n      logoSl'
    'ot.appendChild(el("img", { id: "client-logo-img", src: client.logo_data_uri, alt: client.logo_alt ||'
    ' "Logotipo autorizado del cliente" }));\n    }\n  }\n\n  function verdict() {\n    var sb = COUNTS.severi'
    'ty_breakdown || {};\n    var imm = COUNTS.actions_immediate_24h || 0;\n    var parts = ["critical", "h'
    'igh", "medium", "low"].filter(function (k) { return sb[k]; }).map(function (k) {\n      return n(sb[k'
    ']) + " " + SEV_WORDS[k][sb[k] === 1 ? 0 : 1];\n    });\n    var tone = imm > 0 || sb.critical ? "crit"'
    ' : (sb.high || sb.medium) ? "warn" : "ok";\n    var card = document.getElementById("verdict-card");\n '
    '   card.className = "verdict " + tone;\n    document.getElementById("verdict-title").textContent = to'
    'ne === "crit" ? "Acción requerida" : tone === "warn" ? "Requiere atención" : parts.length ? "Sin hal'
    'lazgos prioritarios" : "Sin hallazgos";\n    document.getElementById("verdict-detail").textContent = '
    'parts.length ? parts.join(" · ") : "Sin incidencias ni anomalías en la ventana";\n    document.getEle'
    'mentById("verdict-sub").textContent =\n      (imm ? n(imm) + " " + plural(imm, "acción inmediata", "a'
    'cciones inmediatas") + " (<24 h)" : "Ninguna acción en horizonte inmediato")\n      + " · " + n(COUNT'
    'S.resources_attention || 0) + " " + plural(COUNTS.resources_attention, "recurso", "recursos") + " co'
    'n hallazgos activos";\n  }\n\n  function renderHero() {\n    var win = DATA.window || {};\n    var source'
    's = DATA.sources || [];\n    var degraded = sources.filter(function (s) { return s.status !== "comple'
    'te" && s.status !== "not_configured"; });\n    document.getElementById("hero-scope").textContent = "I'
    'nforme periódico de operaciones Azure · " + (win.label || win.period || "ventana no indicada");\n    '
    'document.title = "Dossier de operaciones, incidencias, anomalías y acciones recomendadas · " + (win.'
    'label || "") + " · " + ((DATA.client || {}).name || "CLIENTE");\n\n    var lead = document.getElementB'
    'yId("hero-lead");\n    clear(lead);\n    [\n      "La ventana registra ", b(COUNTS.incidents_total), " '
    '" + plural(COUNTS.incidents_total, "incidencia", "incidencias") + " y ",\n      b(COUNTS.anomalies_to'
    'tal), " " + plural(COUNTS.anomalies_total, "anomalía técnica", "anomalías técnicas") + " sobre ",\n  '
    '    b(COUNTS.resources_total), " " + plural(COUNTS.resources_total, "recurso evaluado", "recursos ev'
    'aluados") + " (",\n      b(COUNTS.resources_attention), " con hallazgos activos); el plan propone ",\n'
    '      b(COUNTS.actions_total), " " + plural(COUNTS.actions_total, "acción priorizada", "acciones pri'
    'orizadas") + ": ",\n      b(COUNTS.actions_immediate_24h), " " + plural(COUNTS.actions_immediate_24h,'
    ' "inmediata", "inmediatas") + ", ",\n      b(COUNTS.actions_short_term_7d), " a corto plazo y ", b(CO'
    'UNTS.actions_monthly_cycle), " de ciclo mensual."\n    ].forEach(function (part) {\n      lead.appendC'
    'hild(typeof part === "string" ? document.createTextNode(part) : part);\n    });\n\n    var sub = DATA.s'
    'ubscription_id || "";\n    var meta = document.getElementById("hero-meta");\n    clear(meta);\n    var '
    'live = DATA.provenance === "LIVE";\n    [\n      ["Generado " + utc(DATA.reference_utc) + " UTC", ""],'
    '\n      ["Ventana " + utc(win.start_utc).slice(0, 10) + " → " + utc(win.end_utc).slice(0, 10) + " (UT'
    'C)", ""],\n      [sub ? "Suscripción " + (sub.length > 16 ? sub.slice(0, 8) + "…" + sub.slice(-4) : s'
    'ub) : "", ""],\n      [live ? "Lectura en vivo (LIVE)" : "Datos simulados (" + (DATA.provenance || "S'
    'IMULATED") + ")", "on"],\n      [degraded.length ? "Cobertura parcial · " + (sources.length - degrade'
    'd.length) + " de " + sources.length + " fuentes" : "Cobertura completa · " + sources.length + " fuen'
    'tes", degraded.length ? "warn" : ""]\n    ].forEach(function (item) {\n      if (item[0]) {\n        me'
    'ta.appendChild(el("li", { className: item[1] || null, textContent: item[0], title: item[0].indexOf("'
    'Suscripción") === 0 ? sub : null }));\n      }\n    });\n\n    verdict();\n\n    var sb = COUNTS.severity_'
    'breakdown || {};\n    var total = ["critical", "high", "medium", "low"].reduce(function (acc, k) { re'
    'turn acc + (sb[k] || 0); }, 0);\n    document.getElementById("dist-total-label").textContent = n(tota'
    'l) + " " + plural(total, "señal", "señales");\n    var track = document.getElementById("dist-track");'
    '\n    var legend = document.getElementById("dist-legend");\n    clear(track);\n    clear(legend);\n    v'
    'ar described = [];\n    ["critical", "high", "medium", "low"].forEach(function (k) {\n      var count '
    '= sb[k] || 0;\n      var color = "var(" + SEV_BAR[k] + ")";\n      if (total > 0 && count > 0) {\n     '
    '   var seg = el("i", { title: SEV_LABEL[k] + ": " + count });\n        seg.style.width = (count * 100'
    ' / total).toFixed(2) + "%";\n        seg.style.background = color;\n        track.appendChild(seg);\n  '
    '    }\n      var sw = el("i");\n      sw.style.background = color;\n      legend.appendChild(el("span",'
    ' null, [sw, SEV_LABEL[k] + " ", el("b", { textContent: n(count) })]));\n      described.push(SEV_LABE'
    'L[k] + " " + count);\n    });\n    track.setAttribute("aria-label", "Distribución por severidad: " + d'
    'escribed.join(", "));\n\n    var notes = document.getElementById("status-notes");\n    clear(notes);\n  '
    '  if (!live) {\n      notes.appendChild(el("div", { className: "note sim" }, [icon("alert"), el("span'
    '", null, ["Datos simulados (" + (DATA.provenance || "SIMULATED") + "): figuras de demostración gener'
    'adas sin leer Azure; no describen un entorno real."])]));\n    }\n    if (degraded.length) {\n      not'
    'es.appendChild(el("div", { className: "note" }, [icon("alert"), el("span", null, [\n        "Cobertur'
    'a parcial: " + degraded.map(function (s) { return s.id + " (" + (STATUS[s.status] || [s.status])[0].'
    'toLowerCase() + ")"; }).join(", ")\n        + ". Lo que no se leyó es un punto ciego, no un resultado'
    ' limpio. ",\n        el("a", { href: "#sec-coverage", textContent: "Ver cobertura de fuentes" })\n    '
    '  ])]));\n    }\n  }\n\n  function renderKpis() {\n    var incidents = DATA.incidents || [];\n    var nati'
    've = incidents.filter(function (r) { return r.category === "native_alert"; });\n    var fired = nativ'
    'e.filter(function (r) { return String(r.monitor_condition || "").toLowerCase() === "fired"; }).lengt'
    'h;\n    var sh = incidents.filter(function (r) { return r.category === "service_health"; });\n    var '
    'issues = sh.filter(function (r) { return r.signal_type === "ServiceIssue"; }).length;\n    var set = '
    'function (id, value) { document.getElementById(id).textContent = value; };\n    set("kpi-native-alert'
    's", n(COUNTS.native_alerts_total));\n    set("kpi-native-alerts-sub", n(fired) + " " + plural(fired, '
    '"activa", "activas") + " (Fired) · " + n(native.length - fired) + " " + plural(native.length - fired'
    ', "resuelta", "resueltas"));\n    set("kpi-service-health", n(COUNTS.service_health_total));\n    set('
    '"kpi-service-health-sub", n(issues) + " " + plural(issues, "incidencia de servicio", "incidencias de'
    ' servicio") + " · " + n(sh.length - issues) + " " + plural(sh.length - issues, "mantenimiento", "man'
    'tenimientos"));\n    set("kpi-posture-anomalies", n((COUNTS.extension_failures_total || 0) + (COUNTS.'
    'connectivity_posture_total || 0)));\n    set("kpi-posture-anomalies-sub", n(COUNTS.extension_failures'
    '_total) + " ext. fallidas · " + n(COUNTS.connectivity_posture_total) + " conectividad/postura");\n   '
    ' set("kpi-telemetry-anomalies", n(COUNTS.telemetry_anomalies_total));\n    var kinds = { cpu: 0, mem:'
    ' 0, disk: 0, hb: 0 };\n    (DATA.anomalies || []).forEach(function (a) {\n      if (a.category === "te'
    'lemetry_anomaly") {\n        var k = String(a.anomaly_kind || "");\n        kinds[/cpu/.test(k) ? "cpu'
    '" : /memory/.test(k) ? "mem" : /disk/.test(k) ? "disk" : "hb"] += 1;\n      }\n    });\n    var kindTex'
    't = [["cpu", "CPU"], ["mem", "memoria"], ["disk", "disco"], ["hb", "heartbeat"]].filter(function (k)'
    ' { return kinds[k[0]]; }).map(function (k) { return n(kinds[k[0]]) + " " + k[1]; }).join(" · ");\n   '
    ' set("kpi-telemetry-anomalies-sub", kindText || "InsightsMetrics, Perf y Heartbeat");\n    set("kpi-a'
    'ctions-total", n(COUNTS.actions_total));\n    set("kpi-actions-sub", n(COUNTS.actions_immediate_24h) '
    '+ " <24h · " + n(COUNTS.actions_short_term_7d) + " 1-7 días · " + n(COUNTS.actions_monthly_cycle) + '
    '" mensual");\n    set("kpi-resources-total", n(COUNTS.resources_total));\n    set("kpi-resources-sub",'
    ' n(COUNTS.resources_attention) + " con hallazgos activos");\n  }\n\n  /* ---------- Overview ----------'
    ' */\n\n  function jumpTo(id) {\n    var target = document.getElementById(id);\n    if (target) {\n      t'
    'arget.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", block: "start" });\n    }\n  }\n\n  functi'
    'on renderOverview() {\n    var win = DATA.window || {};\n    var messages = document.getElementById("e'
    'xecutive-messages-list");\n    clear(messages);\n    (DATA.executive_messages || []).forEach(function '
    '(msg) {\n      var li = el("li");\n      var text = String(msg);\n      text.split(/(\\d+)/).forEach(fun'
    'ction (part, i, all) {\n        if (!part) {\n          return;\n        }\n        var prev = i > 0 ? a'
    'll[i - 1].slice(-1) : "";\n        var next = i + 1 < all.length ? all[i + 1].charAt(0) : "";\n       '
    ' var standalone = i % 2 === 1 && !/[-:T<\\w]/.test(prev) && !/[-:\\w]/.test(next);\n        li.appendCh'
    'ild(standalone ? el("b", { textContent: part }) : document.createTextNode(part));\n      });\n      me'
    'ssages.appendChild(li);\n    });\n    document.getElementById("prov-subscription").textContent = DATA.'
    'subscription_id || "—";\n    document.getElementById("prov-window-label").textContent = win.label || '
    'win.period || "—";\n    document.getElementById("prov-window-range").textContent = (win.start_utc || '
    '"—") + " → " + (win.end_utc || "—");\n    document.getElementById("prov-cadence").textContent = win.c'
    'adence || "Mensual programado (30 8 1 * * UTC)";\n    document.getElementById("prov-provenance").text'
    'Content = (DATA.provenance || "LIVE") + " · solo lectura";\n    document.getElementById("reference-ut'
    'c-label").textContent = DATA.reference_utc || "—";\n\n    var tiles = document.getElementById("horizon'
    '-tiles");\n    clear(tiles);\n    [["immediate_24h", "Inmediato <24h", COUNTS.actions_immediate_24h], '
    '["short_term_7d", "Corto plazo 1-7 días", COUNTS.actions_short_term_7d], ["monthly_cycle", "Ciclo me'
    'nsual", COUNTS.actions_monthly_cycle]].forEach(function (t) {\n      var tile = el("button", { type: '
    '"button", className: "tile" + (t[0] === "immediate_24h" && t[2] ? " imm" : ""), "aria-label": t[1] +'
    ' ": " + (t[2] || 0) + " acciones. Filtrar el plan por este horizonte" }, [el("b", { textContent: n(t'
    '[2]) }), el("span", { textContent: t[1] })]);\n      tile.addEventListener("click", function () {\n   '
    '     resetFilters(true);\n        document.getElementById("filter-horizon").value = t[0];\n        ren'
    'derTables();\n        jumpTo("sec-actions");\n      });\n      tiles.appendChild(tile);\n    });\n\n    va'
    'r list = document.getElementById("top-actions");\n    clear(list);\n    var actions = (DATA.actions ||'
    ' []).slice(0, 5);\n    if (!actions.length) {\n      list.appendChild(el("li", null, [el("span", { cla'
    'ssName: "rk", textContent: "—" }), el("div", { className: "t", textContent: "Sin acciones recomendad'
    'as en esta ventana." })]));\n    }\n    actions.forEach(function (act) {\n      list.appendChild(el("li'
    '", null, [\n        el("span", { className: "rk", textContent: String(act.priority_rank) }),\n        '
    'el("div", null, [\n          el("div", { className: "t" }, withName(act.title, act.resource_name)),\n '
    '         el("div", { className: "m" }, [pill(act.severity, act.severity_label), el("span", { classNa'
    'me: "tag " + (act.horizon || ""), textContent: act.horizon_label }), el("span", { textContent: act.r'
    'esource_name + (act.resource_group ? " · " + rgLabel(act.resource_group) : "") })])\n        ])\n     '
    ' ]));\n    });\n    document.getElementById("all-actions-link").textContent = "Ver las " + n(COUNTS.ac'
    'tions_total) + " acciones del plan";\n\n    var streams = [\n      ["native_alert", "Alertas nativas Az'
    'ure Monitor", COUNTS.native_alerts_total, "sec-incidents"],\n      ["service_health", "Comunicaciones'
    ' Service Health", COUNTS.service_health_total, "sec-incidents"],\n      ["extension_failure", "Extens'
    'iones VM / Arc fallidas", COUNTS.extension_failures_total, "sec-anomalies"],\n      ["connectivity_po'
    'sture", "Plano de control y conectividad", COUNTS.connectivity_posture_total, "sec-anomalies"],\n    '
    '  ["telemetry_anomaly", "Telemetría fuera de rango", COUNTS.telemetry_anomalies_total, "sec-anomalie'
    's"],\n      ["advisor_recommendation", "Recomendaciones Azure Advisor", COUNTS.advisor_recommendation'
    's_total, "sec-resources"]\n    ];\n    var maxStream = Math.max.apply(null, streams.map(function (s) {'
    ' return s[2] || 0; }).concat([1]));\n    var streamBox = document.getElementById("stream-bars");\n    '
    'clear(streamBox);\n    streams.forEach(function (s) {\n      var bar = el("i");\n      bar.style.width '
    '= ((s[2] || 0) * 100 / maxStream).toFixed(1) + "%";\n      if (!s[2]) {\n        bar.style.minWidth = '
    '"0";\n      }\n      var row = el("button", { type: "button", className: "brow", "aria-label": s[1] + '
    '": " + (s[2] || 0) + ". Filtrar los registros por este flujo" }, [el("span", { className: "bl", text'
    'Content: s[1] }), el("span", { className: "bt" }, [bar]), el("b", { textContent: n(s[2]) })]);\n     '
    ' row.addEventListener("click", function () {\n        resetFilters(true);\n        document.getElement'
    'ById("filter-category").value = s[0];\n        renderTables();\n        jumpTo(s[3]);\n      });\n      '
    'streamBox.appendChild(row);\n    });\n\n    var hot = (DATA.resources || []).map(function (r) {\n      r'
    'eturn { r: r, v: (r.incident_count || 0) + (r.anomaly_count || 0) };\n    }).filter(function (x) { re'
    'turn x.v > 0; }).sort(function (x, y) {\n      return y.v - x.v || sevKey(x.r) - sevKey(y.r) || Strin'
    'g(x.r.resource_name).localeCompare(String(y.r.resource_name));\n    }).slice(0, 6);\n    var resBox = '
    'document.getElementById("resource-bars");\n    clear(resBox);\n    if (!hot.length) {\n      resBox.app'
    'endChild(el("p", { className: "empty-note", textContent: "Ningún recurso inventariado acumula incide'
    'ncias ni anomalías en la ventana." }));\n    }\n    var maxHot = hot.length ? hot[0].v : 1;\n    hot.fo'
    'rEach(function (x) {\n      var color = "var(" + (SEV_BAR[x.r.severity] || "--sev-info-bar") + ")";\n '
    '     var bar = el("i");\n      bar.style.width = (x.v * 100 / maxHot).toFixed(1) + "%";\n      bar.sty'
    'le.background = color;\n      var dot = el("span", { className: "dot" });\n      dot.style.background '
    '= color;\n      var row = el("button", { type: "button", className: "brow", title: x.r.resource_id, "'
    'aria-label": x.r.resource_name + ": " + x.v + " señales, severidad máxima " + (x.r.severity_label ||'
    ' "") + ". Buscar este recurso en los registros" }, [\n        el("span", { className: "bl" }, [dot, x'
    '.r.resource_name, el("small", { textContent: x.r.resource_group || "" })]),\n        el("span", { cla'
    'ssName: "bt" }, [bar]),\n        el("b", { textContent: n(x.v) })\n      ]);\n      row.addEventListene'
    'r("click", function () {\n        resetFilters(true);\n        document.getElementById("filter-search"'
    ').value = x.r.resource_name;\n        renderTables();\n        jumpTo(x.r.incident_count ? "sec-incide'
    'nts" : "sec-anomalies");\n      });\n      resBox.appendChild(row);\n    });\n  }\n\n  /* ---------- Regis'
    'ters ---------- */\n\n  var TABLES = {};\n  var PAGE = 50;\n  var lastFilterKey = "";\n\n  function headLa'
    'bel(text) {\n    var parts = String(text).split(" · ");\n    var out = [];\n    parts.forEach(function '
    '(part, i) {\n      if (i) {\n        out.push(" ");\n      }\n      out.push(el("span", { className: "hg'
    '", textContent: part + (i < parts.length - 1 ? " ·" : "") }));\n    });\n    return out;\n  }\n\n  functi'
    'on setupTable(tableId, cols, rowId) {\n    var table = document.getElementById(tableId);\n    var tr ='
    ' el("tr");\n    cols.forEach(function (c, i) {\n      var th = el("th", { scope: "col", className: c.n'
    'um ? "n" : null });\n      if (c.sort) {\n        var btn = el("button", { type: "button", className: '
    '"sort" }, headLabel(c.head));\n        btn.addEventListener("click", function () {\n          var st ='
    ' TABLES[tableId].sort;\n          TABLES[tableId].sort = { i: i, dir: st.i === i && st.dir === "ascen'
    'ding" ? "descending" : "ascending" };\n          renderTables();\n        });\n        th.appendChild(b'
    'tn);\n        th.appendChild(el("span", { className: "th-print", "aria-hidden": "true" }, headLabel(c'
    '.head)));\n      } else {\n        headLabel(c.head).forEach(function (part) { th.appendChild(typeof p'
    'art === "string" ? document.createTextNode(part) : part); });\n      }\n      tr.appendChild(th);\n    '
    '});\n    var thead = table.querySelector("thead");\n    clear(thead);\n    thead.appendChild(tr);\n    v'
    'ar more = el("div", { className: "more-row", id: tableId + "-more", hidden: "hidden" }, [el("span"),'
    ' el("button", { type: "button", className: "btn btn-ghost" })]);\n    more.querySelector("button").ad'
    'dEventListener("click", function () {\n      TABLES[tableId].limit += PAGE;\n      renderTables();\n   '
    ' });\n    table.closest(".table-card").appendChild(more);\n    TABLES[tableId] = { cols: cols, sort: {'
    ' i: -1, dir: "" }, rowId: rowId, limit: PAGE };\n  }\n\n  function fillTable(tableId, rows, emptyText) '
    '{\n    var t = TABLES[tableId];\n    var table = document.getElementById(tableId);\n    var tbody = tab'
    'le.querySelector("tbody");\n    var more = document.getElementById(tableId + "-more");\n    var st = t'
    '.sort;\n    var ths = table.querySelectorAll("thead th");\n    for (var k = 0; k < ths.length; k++) {\n'
    '      if (k === st.i) {\n        ths[k].setAttribute("aria-sort", st.dir);\n      } else {\n        ths'
    '[k].removeAttribute("aria-sort");\n      }\n    }\n    if (st.i >= 0) {\n      var acc = t.cols[st.i].so'
    'rt;\n      var dir = st.dir === "ascending" ? 1 : -1;\n      rows = rows.map(function (r, idx) { retur'
    'n [r, idx]; }).sort(function (x, y) {\n        var a = acc(x[0]);\n        var c = acc(y[0]);\n        '
    'var d = typeof a === "number" && typeof c === "number" ? a - c : String(a).localeCompare(String(c), '
    '"es", { numeric: true, sensitivity: "base" });\n        return d ? d * dir : x[1] - y[1];\n      }).ma'
    'p(function (p) { return p[0]; });\n    }\n    clear(tbody);\n    var hidden = Math.max(0, rows.length -'
    ' t.limit);\n    more.hidden = hidden === 0;\n    if (hidden) {\n      more.querySelector("span").textCo'
    'ntent = "Se muestran " + n(t.limit) + " de " + n(rows.length) + ". La impresión incluye todos.";\n   '
    '   more.querySelector("button").textContent = "Mostrar " + n(Math.min(PAGE, hidden)) + " más";\n    }'
    '\n    if (!rows.length) {\n      tbody.appendChild(el("tr", { className: "empty-row" }, [el("td", { co'
    'lspan: String(t.cols.length), textContent: emptyText })]));\n      return;\n    }\n    var frag = docum'
    'ent.createDocumentFragment();\n    rows.forEach(function (row, idx) {\n      var attrs = t.rowId ? { i'
    'd: t.rowId(row) } : {};\n      if (idx >= t.limit) {\n        attrs.className = "pg";\n      }\n      va'
    'r tr = el("tr", attrs);\n      t.cols.forEach(function (c) {\n        var value = c.cell(row);\n       '
    ' tr.appendChild(el("td", { className: c.cls || (c.num ? "n" : null) }, Array.isArray(value) ? value '
    ': [value]));\n      });\n      frag.appendChild(tr);\n    });\n    tbody.appendChild(frag);\n  }\n\n  funct'
    'ion stateCell(row) {\n    var cond = row.monitor_condition || "—";\n    var active = /^(fired|active)$'
    '/i.test(cond);\n    return [el("span", { className: "state" + (active ? " on" : ""), textContent: con'
    'd }), el("span", { className: "sm", textContent: row.state || "" })];\n  }\n\n  function evidenceLinks('
    'ids) {\n    return el("div", { className: "ids" }, (ids || []).map(function (id) {\n      var a = el("'
    'a", { className: "chip-id", href: "#ev-" + id, textContent: id, title: "Ir a la evidencia " + id });'
    '\n      a.addEventListener("click", function (ev) {\n        ev.preventDefault();\n        gotoEvidence'
    '(id);\n      });\n      return a;\n    }));\n  }\n\n  function gotoEvidence(id) {\n    var row = document.g'
    'etElementById("ev-" + id);\n    if (!row) {\n      resetFilters();\n      row = document.getElementById'
    '("ev-" + id);\n    }\n    if (row && row.classList.contains("pg")) {\n      TABLES[row.closest("table")'
    '.id].limit = Infinity;\n      renderTables();\n      row = document.getElementById("ev-" + id);\n    }\n'
    '    if (!row) {\n      return;\n    }\n    row.scrollIntoView({ behavior: REDUCED ? "auto" : "smooth", '
    'block: "center" });\n    row.classList.add("flash");\n    setTimeout(function () { row.classList.remov'
    'e("flash"); }, 1800);\n  }\n\n  function evId(row) {\n    return "ev-" + row.id;\n  }\n\n  function telemet'
    'ryText(metrics) {\n    var tm = metrics || {};\n    var parts = [];\n    if (tm.cpu_percent) {\n      pa'
    'rts.push("CPU máx " + tm.cpu_percent.max + " % (mediana " + tm.cpu_percent.median + " %)");\n    }\n  '
    '  if (tm.memory_available_mb) {\n      parts.push("Memoria mín " + n(tm.memory_available_mb.min) + " '
    'MB");\n    }\n    if (tm.disk_free_percent) {\n      parts.push("Disco libre mín " + tm.disk_free_perce'
    'nt.min + " %");\n    }\n    if (tm.heartbeat_silence_minutes) {\n      parts.push("Silencio de Heartbea'
    't " + n(tm.heartbeat_silence_minutes.max) + " min");\n    }\n    return parts.length ? parts.join(" · '
    '") : "Sin telemetría de huésped en la ventana";\n  }\n\n  function setupTables() {\n    var byName = fun'
    'ction (r) { return String(r.resource_name || "").toLowerCase(); };\n    setupTable("incidents-table",'
    ' [\n      { head: "Severidad", sort: sevKey, cls: "nw", cell: function (r) { return [pill(r.severity,'
    ' r.severity_label), el("span", { className: "sm", textContent: r.native_severity || "" })]; } },\n   '
    '   { head: "ID · flujo", sort: function (r) { return r.id; }, cls: "nw", cell: idCell },\n      { hea'
    'd: "Recurso / servicio", sort: byName, cls: "w2", cell: function (r) {\n        if (r.category === "s'
    'ervice_health") {\n          return resourceCell(r.resource_name, "subscription-scope", null, null, ('
    'r.regions || []).join(", "));\n        }\n        return resourceCell(r.resource_name, r.resource_grou'
    'p, r.resource_type, r.resource_id);\n      } },\n      { head: "Estado", sort: function (r) { return ('
    'r.monitor_condition || "") + " " + (r.state || ""); }, cls: "nw", cell: stateCell },\n      { head: "'
    'Señal", sort: function (r) { return r.signal_type || ""; }, cell: function (r) { return [el("div", {'
    ' textContent: r.signal_type || "—" }), el("span", { className: "sm", textContent: r.monitor_service '
    '|| "" })]; } },\n      { head: "Inicio · act. (UTC)", sort: function (r) { return r.start_time_utc ||'
    ' ""; }, cls: "nw", cell: function (r) {\n        return [el("div", { textContent: utc(r.start_time_ut'
    'c), title: r.start_time_utc }), el("span", { className: "sm", textContent: "act. " + utc(r.last_upda'
    'ted_utc), title: r.last_updated_utc })];\n      } },\n      { head: "Descripción", cls: "wide", cell: '
    'function (r) { return [el("div", null, [prose(r.summary)]), extLink(r.learn_url, "Microsoft Learn")]'
    '; } }\n    ], evId);\n\n    setupTable("anomalies-table", [\n      { head: "Severidad", sort: sevKey, cl'
    's: "nw", cell: function (r) { return pill(r.severity, r.severity_label); } },\n      { head: "ID · fl'
    'ujo", sort: function (r) { return r.id; }, cls: "nw", cell: idCell },\n      { head: "Recurso", sort:'
    ' byName, cls: "w2", cell: function (r) { return resourceCell(r.resource_name, r.resource_group, r.re'
    'source_type, r.resource_id); } },\n      { head: "Métrica o propiedad", sort: function (r) { return r'
    '.metric_or_field || ""; }, cell: function (r) { return breakable(r.metric_or_field, "code"); } },\n  '
    '    { head: "Observado · referencia", cell: function (r) {\n        return [el("div", null, [el("b", '
    '{ textContent: withUnit(r.observed_value, r.unit) })]), el("span", { className: "sm", textContent: "'
    'ref. " + withUnit(r.baseline_or_expected, r.unit) })];\n      } },\n      { head: "Muestras · ventana"'
    ', sort: function (r) { return Number(r.sample_count) || 0; }, cell: function (r) {\n        var count'
    ' = Number(r.sample_count) || 1;\n        return [el("div", { className: "nw", textContent: n(count) +'
    ' " " + plural(count, "muestra", "muestras") }), el("span", { className: "sm", textContent: (r.window'
    '_grain || "PointInTime") + (r.workspace_name ? " · " + r.workspace_name : "") })];\n      } },\n      '
    '{ head: "Evidencia técnica", cls: "wide", cell: function (r) { return [el("div", null, [prose(r.summ'
    'ary)]), extLink(r.learn_url, "Guía en Microsoft Learn")]; } }\n    ], evId);\n\n    setupTable("actions'
    '-table", [\n      { head: "Prioridad", sort: function (r) { return Number(r.priority_rank) || 0; }, c'
    'ls: "nw", cell: function (r) { return [el("span", { className: "rank", textContent: "#" + r.priority'
    '_rank }), el("span", { className: "sm id", textContent: r.id })]; } },\n      { head: "Horizonte · se'
    'veridad", sort: function (r) { return (HORIZON_RANK.hasOwnProperty(r.horizon) ? HORIZON_RANK[r.horiz'
    'on] : 9) * 10 + sevKey(r); }, cls: "nw stack", cell: function (r) {\n        return [el("div", null, '
    '[el("span", { className: "tag " + (r.horizon || ""), textContent: r.horizon_label })]), el("div", nu'
    'll, [pill(r.severity, r.severity_label)])];\n      } },\n      { head: "Acción recomendada", sort: fun'
    'ction (r) { return r.title || ""; }, cls: "w3", cell: function (r) {\n        return el("div", { clas'
    'sName: "res", title: r.resource_id || null }, [el("b", null, withName(r.title, r.resource_name)), el'
    '("span", { className: "sm", textContent: (r.resource_name || "") + (r.resource_group ? " · " + rgLab'
    'el(r.resource_group) : "") }), portalUrl(r.resource_id) ? extLink(portalUrl(r.resource_id), "Portal"'
    ') : null]);\n      } },\n      { head: "Responsable · esfuerzo", sort: function (r) { return r.owner_s'
    'cope || ""; }, cls: "w1", cell: function (r) { return [el("div", { textContent: r.owner_scope || "—"'
    ' }), el("span", { className: "sm", textContent: "Esfuerzo: " + (r.effort_label || "—") })]; } },\n   '
    '   { head: "Evidencias", cell: function (r) { return evidenceLinks(r.linked_evidence_ids); } },\n    '
    '  { head: "Guía para revisión humana", cls: "wide", cell: function (r) {\n        return [el("div", n'
    'ull, [prose(r.recommendation)]), el("span", { className: "sm" }, ["Evidencia: ", prose(r.evidence_su'
    'mmary)]), extLink(r.learn_url, "Referencia en Microsoft Learn")];\n      } }\n    ]);\n\n    setupTable('
    '"resources-table", [\n      { head: "Recurso", sort: byName, cls: "w2", cell: function (r) { return r'
    'esourceCell(r.resource_name, r.resource_group, null, r.resource_id, r.location); } },\n      { head: '
    '"Tipo · hosting", sort: function (r) { return typeLabel(r.resource_type); }, cell: function (r) { re'
    'turn [el("div", { textContent: typeLabel(r.resource_type) }), el("span", { className: "sm" }, [break'
    'able(r.resource_type, "code"), " · " + String(r.hosting || "").toUpperCase()])]; } },\n      { head: '
    '"Estado operativo", sort: function (r) { return (r.status === "attention" ? 0 : r.status === "review'
    '" ? 1 : 2) * 10 + sevKey(r); }, cls: "nw", cell: function (r) {\n        return [r.status === "health'
    'y" ? pill("ok", "Normal") : pill(r.severity, r.severity_label), el("span", { className: "sm", textCo'
    'ntent: r.operational_state || "" })];\n      } },\n      { head: "Incidencias", num: true, sort: funct'
    'ion (r) { return r.incident_count || 0; }, cell: function (r) { return n(r.incident_count); } },\n   '
    '   { head: "Anomalías", num: true, sort: function (r) { return r.anomaly_count || 0; }, cell: functi'
    'on (r) { return n(r.anomaly_count); } },\n      { head: "Ext. fallidas", num: true, sort: function (r'
    ') { return r.failed_extension_count || 0; }, cell: function (r) { return n(r.failed_extension_count)'
    ' + " / " + n(r.extensions_total); } },\n      { head: "Acciones", num: true, sort: function (r) { ret'
    'urn r.action_count || 0; }, cell: function (r) { return n(r.action_count); } },\n      { head: "Resum'
    'en de telemetría", cls: "w2", cell: function (r) { return telemetryText(r.telemetry_metrics); } }\n  '
    '  ]);\n\n    setupTable("advisor-table", [\n      { head: "Impacto", sort: sevKey, cls: "nw", cell: fun'
    'ction (r) { return [pill(r.severity, r.severity_label, "Impacto " + (r.impact || "")), el("span", { '
    'className: "sm", textContent: r.advisor_category || "" })]; } },\n      { head: "ID", sort: function '
    '(r) { return r.id; }, cls: "nw", cell: function (r) { return el("span", { className: "id", textConte'
    'nt: r.id }); } },\n      { head: "Recurso", sort: byName, cls: "w2", cell: function (r) { return reso'
    'urceCell(r.resource_name, r.resource_group, r.resource_type, r.resource_id); } },\n      { head: "Pro'
    'blema detectado", cls: "w2", cell: function (r) { return prose(r.problem); } },\n      { head: "Soluc'
    'ión recomendada", cls: "wide", cell: function (r) { return [el("div", null, [prose(r.solution)]), ex'
    'tLink(r.learn_url, "Azure Advisor en Microsoft Learn")]; } },\n      { head: "Actualizado (UTC)", sor'
    't: function (r) { return r.last_updated_utc || ""; }, cls: "nw", cell: function (r) { return el("spa'
    'n", { textContent: utc(r.last_updated_utc), title: r.last_updated_utc }); } }\n    ], evId);\n\n    set'
    'upTable("sources-table", [\n      { head: "Fuente", cls: "nw", cell: function (r) { return el("span",'
    ' { className: "id", textContent: r.id }); } },\n      { head: "Estado", cls: "nw", cell: function (r)'
    ' { var s = STATUS[r.status] || [r.status, "critical"]; return pill(s[1], s[0], r.status); } },\n     '
    ' { head: "Registros", num: true, cell: function (r) { return n(r.records); } },\n      { head: "Págin'
    'as", num: true, cell: function (r) { return n(r.pages); } },\n      { head: "Paginación completa", cl'
    's: "nw", cell: function (r) { return r.pagination_complete ? "Sí" : "No"; } },\n      { head: "Firma '
    'de lectura y detalle", cls: "wide", cell: function (r) {\n        var kids = [breakable(r.read_signat'
    'ure || "—", "code")];\n        if (Array.isArray(r.workspaces_queried) && r.workspaces_queried.length'
    ') {\n          kids.push(el("ul", { className: "wslist" }, r.workspaces_queried.map(function (w) {\n  '
    '          return el("li", { textContent: w.workspace_name + " · " + ((STATUS[w.status] || [w.status]'
    ')[0]) + " · " + n(w.records) + " " + plural(w.records, "fila", "filas") });\n          })));\n        '
    '}\n        (r.errors || []).forEach(function (e) {\n          kids.push(el("div", { className: "errbox'
    '" }, [el("b", { textContent: e.code || "error" }), " · " + (e.message || "") + (e.http_status ? " (H'
    'TTP " + e.http_status + ")" : "")]));\n        });\n        return kids;\n      } },\n      { head: "Not'
    'as y alcance", cls: "w2", cell: function (r) { return r.note || "—"; } }\n    ]);\n  }\n\n  function mat'
    'chesCommonFilter(row, cat, sev, query) {\n    if (cat !== "all" && row.category !== cat) {\n      retu'
    'rn false;\n    }\n    if (sev !== "all" && row.severity !== sev) {\n      return false;\n    }\n    if (q'
    'uery) {\n      var hay = [row.id, row.title, row.resource_name, row.resource_id, row.resource_group, '
    'row.summary, row.metric_or_field, row.signal_type, row.owner_scope, row.recommendation].join(" ").to'
    'LowerCase();\n      if (hay.indexOf(query) < 0) {\n        return false;\n      }\n    }\n    return true'
    ';\n  }\n\n  function renderTables() {\n    var cat = document.getElementById("filter-category").value;\n '
    '   var sev = document.getElementById("filter-severity").value;\n    var hor = document.getElementById'
    '("filter-horizon").value;\n    var rawQuery = (document.getElementById("filter-search").value || "").'
    'trim();\n    var query = rawQuery.toLowerCase();\n    var filterKey = [cat, sev, hor, query].join("\\u0'
    '001");\n    if (filterKey !== lastFilterKey) {\n      lastFilterKey = filterKey;\n      Object.keys(TAB'
    'LES).forEach(function (id) { TABLES[id].limit = PAGE; });\n    }\n\n    var incidents = (DATA.incidents'
    ' || []).filter(function (row) { return matchesCommonFilter(row, cat, sev, query); });\n    var anomal'
    'ies = (DATA.anomalies || []).filter(function (row) { return matchesCommonFilter(row, cat, sev, query'
    '); });\n    var actions = (DATA.actions || []).filter(function (row) {\n      return (hor === "all" ||'
    ' row.horizon === hor) && matchesCommonFilter(row, cat, sev, query);\n    });\n    var resources = (DAT'
    'A.resources || []).filter(function (row) {\n      if (sev !== "all" && row.severity !== sev) {\n      '
    '  return false;\n      }\n      if (query) {\n        var hay = [row.resource_name, row.resource_id, ro'
    'w.resource_group, row.resource_type, row.operational_state].join(" ").toLowerCase();\n        if (hay'
    '.indexOf(query) < 0) {\n          return false;\n        }\n      }\n      return true;\n    });\n    var '
    'advisor = (DATA.advisor || []).filter(function (row) { return matchesCommonFilter(row, cat, sev, que'
    'ry); });\n\n    var counts = { incidents: incidents.length, anomalies: anomalies.length, actions: acti'
    'ons.length, resources: resources.length, advisor: advisor.length };\n    Object.keys(counts).forEach('
    'function (key) {\n      document.getElementById(key + "-count").textContent = String(counts[key]);\n  '
    '    document.getElementById(key + "-total").textContent = String((DATA[key] || []).length);\n      va'
    'r nav = document.getElementById("nav-" + key + "-count");\n      if (nav) {\n        nav.textContent ='
    ' String(counts[key]);\n      }\n    });\n\n    var active = cat !== "all" || sev !== "all" || hor !== "a'
    'll" || query;\n    var status = document.getElementById("filter-status-summary");\n    clear(status);\n'
    '    [b(incidents.length), " " + plural(incidents.length, "incidencia", "incidencias") + " · ", b(ano'
    'malies.length), " " + plural(anomalies.length, "anomalía", "anomalías") + " · ", b(actions.length), '
    '" " + plural(actions.length, "acción", "acciones") + " · ", b(resources.length), " " + plural(resour'
    'ces.length, "recurso", "recursos"), active ? " (filtro activo)" : " (sin filtros)"].forEach(function'
    ' (part) {\n      status.appendChild(typeof part === "string" ? document.createTextNode(part) : part);'
    '\n    });\n    var labelOf = function (id) { var s = document.getElementById(id); return s.options[s.s'
    'electedIndex].text; };\n    document.getElementById("print-filter-note").textContent = active\n      ?'
    ' "Filtros aplicados al imprimir: " + [cat !== "all" ? labelOf("filter-category") : "", sev !== "all"'
    ' ? "severidad " + labelOf("filter-severity") : "", hor !== "all" ? "horizonte " + labelOf("filter-ho'
    'rizon") : "", query ? "búsqueda «" + rawQuery + "»" : ""].filter(Boolean).join(" · ")\n      : "";\n\n '
    '   var none = function (key, filtered, empty) { return (DATA[key] || []).length ? filtered : empty; '
    '};\n    fillTable("incidents-table", incidents, none("incidents", "Sin incidencias ni alertas que coi'
    'ncidan con los filtros actuales.", "Sin incidencias ni alertas en la ventana evaluada."));\n    fillT'
    'able("anomalies-table", anomalies, none("anomalies", "Sin anomalías técnicas que coincidan con los f'
    'iltros actuales.", "Sin anomalías técnicas en la ventana evaluada."));\n    fillTable("actions-table"'
    ', actions, none("actions", "Sin acciones recomendadas que coincidan con los filtros actuales.", "Sin'
    ' acciones recomendadas para esta ventana."));\n    fillTable("resources-table", resources, none("reso'
    'urces", "Sin recursos inventariados para el filtro actual.", "Sin recursos inventariados en el alcan'
    'ce."));\n    fillTable("advisor-table", advisor, none("advisor", "Sin recomendaciones de Azure Adviso'
    'r en caché para el filtro actual.", "Sin recomendaciones de Azure Advisor en caché para la suscripci'
    'ón."));\n  }\n\n  function resetFilters(silent) {\n    document.getElementById("filter-category").value '
    '= "all";\n    document.getElementById("filter-severity").value = "all";\n    document.getElementById("'
    'filter-horizon").value = "all";\n    document.getElementById("filter-search").value = "";\n    if (!si'
    'lent) {\n      renderTables();\n    }\n  }\n\n  function renderCoverage() {\n    var sources = DATA.source'
    's || [];\n    document.getElementById("sources-count").textContent = String(sources.length);\n    docu'
    'ment.getElementById("nav-sources-count").textContent = String(sources.length);\n    fillTable("source'
    's-table", sources, "No hay recibos de fuentes en el modelo.");\n\n    var meth = DATA.methodology || {'
    '};\n    var methList = document.getElementById("methodology-list");\n    clear(methList);\n    (meth.li'
    'mitations || []).forEach(function (lim) {\n      methList.appendChild(el("li", { textContent: lim }))'
    ';\n    });\n    var facts = document.getElementById("method-facts");\n    clear(facts);\n    [\n      ["M'
    'odo", meth.read_only === false ? "Escritura" : "Solo lectura"],\n      ["Cálculo SLA oficial", meth.o'
    'fficial_sla_calculation ? "Sí" : "No"],\n      ["Programación", (meth.scheduled_cadence_cron || "30 8'
    ' 1 * *") + " (UTC)"],\n      ["Periodo por defecto", meth.scheduled_default_period || "previous_month'
    '"],\n      ["Periodos admitidos", (meth.supported_periods || []).join(", ") || "—"]\n    ].forEach(fun'
    'ction (f) {\n      facts.appendChild(el("dt", { textContent: f[0] }));\n      facts.appendChild(el("dd'
    '", { textContent: f[1] }));\n    });\n    var streams = document.getElementById("method-streams");\n   '
    ' clear(streams);\n    (meth.evidence_streams || []).forEach(function (s) {\n      streams.appendChild('
    'el("li", { textContent: s }));\n    });\n\n    var client = (DATA.client || {}).name || "CLIENTE";\n    '
    'document.getElementById("footer-left").textContent = "Generado por Azure SRE Agent · Solo lectura · '
    'Referencia " + utc(DATA.reference_utc) + " UTC · " + (DATA.schema_version || "");\n    document.getEl'
    'ementById("footer-right").textContent = client;\n    var page = el("style", { textContent: "@page{@bo'
    'ttom-left{content:\\"" + ("Informe de operaciones · " + client + " · " + ((DATA.window || {}).label |'
    '| "") + " · " + utc(DATA.reference_utc) + " UTC").replace(/["\\\\\\r\\n]/g, " ") + "\\";font:8.5pt \'Segoe'
    ' UI\',sans-serif;color:#5A687A}}" });\n    document.head.appendChild(page);\n  }\n\n  function watchSecti'
    'ons() {\n    if (!("IntersectionObserver" in window)) {\n      return;\n    }\n    var links = {};\n    A'
    'rray.prototype.forEach.call(document.querySelectorAll("#section-nav a"), function (a) {\n      links['
    'a.getAttribute("href").slice(1)] = a;\n    });\n    var observer = new IntersectionObserver(function ('
    'entries) {\n      entries.forEach(function (entry) {\n        if (entry.isIntersecting) {\n          Ob'
    'ject.keys(links).forEach(function (k) { links[k].removeAttribute("aria-current"); });\n          if ('
    'links[entry.target.id]) {\n            links[entry.target.id].setAttribute("aria-current", "true");\n '
    '         }\n        }\n      });\n    }, { rootMargin: "-35% 0px -60% 0px" });\n    Array.prototype.forE'
    'ach.call(document.querySelectorAll("#top, .sec"), function (section) {\n      observer.observe(sectio'
    'n);\n    });\n  }\n\n  /* ---------- Exports ---------- */\n\n  function downloadBlob(filename, content, m'
    'ime) {\n    var blob = new Blob([content], { type: mime });\n    var url = URL.createObjectURL(blob);\n'
    '    var link = document.createElement("a");\n    link.href = url;\n    link.download = filename;\n    d'
    'ocument.body.appendChild(link);\n    link.click();\n    document.body.removeChild(link);\n    setTimeou'
    't(function () { URL.revokeObjectURL(url); }, 500);\n  }\n\n  function csvEscape(val) {\n    if (val === '
    'null || val === undefined) {\n      return \'""\';\n    }\n    var str = typeof val === "object" ? JSON.s'
    'tringify(val) : String(val);\n    if (/^[=+\\-@\\t\\r\\n]/.test(str.trimLeft())) {\n      str = "\'" + str;'
    '\n    }\n    return \'"\' + str.replace(/"/g, \'""\') + \'"\';\n  }\n\n  function exportIncidentsCsv() {\n    va'
    'r headers = ["record_kind", "id", "category", "severity", "title", "resource_name", "resource_group"'
    ', "metric_or_signal", "observed_value", "observed_at_utc", "summary"];\n    var lines = [headers.join'
    '(",")];\n    (DATA.incidents || []).forEach(function (inc) {\n      lines.push([\n        "incident", i'
    'nc.id, inc.category, inc.severity, inc.title, inc.resource_name,\n        inc.resource_group, inc.sig'
    'nal_type, inc.native_severity, inc.last_updated_utc, inc.summary\n      ].map(csvEscape).join(","));\n'
    '    });\n    (DATA.anomalies || []).forEach(function (anom) {\n      lines.push([\n        "anomaly", a'
    'nom.id, anom.category, anom.severity, anom.title, anom.resource_name,\n        anom.resource_group, a'
    'nom.metric_or_field, anom.observed_value, anom.observed_at_utc, anom.summary\n      ].map(csvEscape).'
    'join(","));\n    });\n    downloadBlob("ops-digest-incidents-anomalies.csv", "\\uFEFF" + lines.join("\\r'
    '\\n"), "text/csv;charset=utf-8");\n  }\n\n  function exportActionsCsv() {\n    var headers = ["priority_r'
    'ank", "id", "horizon_label", "severity", "category", "title", "resource_name", "resource_group", "ow'
    'ner_scope", "effort_label", "linked_evidence_ids", "recommendation"];\n    var lines = [headers.join('
    '",")];\n    (DATA.actions || []).forEach(function (act) {\n      lines.push([\n        act.priority_ran'
    'k, act.id, act.horizon_label, act.severity, act.category, act.title,\n        act.resource_name, act.'
    'resource_group, act.owner_scope, act.effort_label,\n        (act.linked_evidence_ids || []).join(";")'
    ', act.recommendation\n      ].map(csvEscape).join(","));\n    });\n    downloadBlob("ops-digest-recomme'
    'nded-actions.csv", "\\uFEFF" + lines.join("\\r\\n"), "text/csv;charset=utf-8");\n  }\n\n  /* ---------- Wi'
    'ring ---------- */\n\n  ["filter-category", "filter-severity", "filter-horizon"].forEach(function (id)'
    ' {\n    document.getElementById(id).addEventListener("change", renderTables);\n  });\n  document.getEle'
    'mentById("filter-search").addEventListener("input", renderTables);\n  document.getElementById("filter'
    '-reset").addEventListener("click", function () { resetFilters(); });\n\n  document.getElementById("the'
    'me-toggle").addEventListener("click", function () {\n    var root = document.documentElement;\n    var'
    ' next = root.getAttribute("data-theme") === "dark" ? "light" : "dark";\n    root.setAttribute("data-t'
    'heme", next);\n    this.querySelector(".lbl").textContent = next === "dark" ? "Modo claro" : "Modo os'
    'curo";\n    this.title = this.querySelector(".lbl").textContent;\n    this.querySelector("path").setAt'
    'tribute("d", next === "dark" ? PATHS.sun : PATHS.moon);\n  });\n\n  document.getElementById("btn-export'
    '-json").addEventListener("click", function () {\n    downloadBlob("ops-digest-snapshot.json", JSON.st'
    'ringify(DATA, null, 2), "application/json;charset=utf-8");\n  });\n  document.getElementById("btn-expo'
    'rt-incidents-csv").addEventListener("click", exportIncidentsCsv);\n  document.getElementById("btn-exp'
    'ort-actions-csv").addEventListener("click", exportActionsCsv);\n  document.getElementById("btn-print"'
    ').addEventListener("click", function () {\n    window.print();\n  });\n\n  renderBranding();\n  renderHer'
    'o();\n  renderKpis();\n  setupTables();\n  renderOverview();\n  renderTables();\n  renderCoverage();\n  wa'
    'tchSections();\n})();\n</script>\n</body>\n</html>\n'
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
        claims = normalize_sidecar_claims(claims)
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
