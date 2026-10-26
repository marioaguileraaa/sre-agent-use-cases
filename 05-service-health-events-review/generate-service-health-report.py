"""Bounded read-only Service Health adapter; build_tool.py embeds the report UI."""

import base64
import binascii
import copy
import csv
import hashlib
import html
import io
import json
import os
import re
import tempfile
import time
from datetime import datetime, timedelta, timezone
from http.client import HTTPException
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, unquote, urlencode, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, Request, build_opener
from uuid import UUID, uuid4


SUBSCRIPTION_ID = "<APPROVED_SUBSCRIPTION_ID>"
TENANT_ID = "<APPROVED_TENANT_ID>"
MANAGED_IDENTITY_CLIENT_ID = "<APPROVED_UAMI_CLIENT_ID>"
CLIENT_NAME = "CLIENTE"
# Here goes the customer's logo, privately configured as a validated PNG/JPEG
# data URI. Keep generic Git source empty. Use adjacent strings <10K per line.
COMPANY_LOGO_DATA_URI = ""
COMPANY_LOGO_ALT_TEXT = "Customer logo"

API_VERSION = "2025-05-01"
ORIGIN = "https://management.azure.com"
OUTPUT_DIRECTORY = "service-health-reports"
ARTIFACT_BYTES = 4_800_000
TRANSPORT_BYTES = 3_500
MAX_LOGO_BYTES = 100_000
MAX_LOGO_DIMENSION = 2048
RETAINED_LOOKBACK_DAYS = 365
MAX_REQUESTED_DAYS = 93
MAX_PAGES = 25
MAX_SOURCE_RECORDS = 5_000
MAX_EVENT_RECORDS = 500
MAX_RESPONSE_BYTES = 20_000_000
MAX_HTTP_ATTEMPTS = 250
MAX_COLLECTION_SECONDS = 180
MAX_JSON_DEPTH = 50
EVENT_TYPES = ("ServiceIssue", "PlannedMaintenance")
TEMPORAL_SCOPES = ("all", "requested_updates", "active_now", "future_maintenance")
COMPLETE_SOURCE_STATUSES = ("complete", "successful_empty", "successful_empty_in_scope")

# BEGIN BUILD-TIME ASSETS
HTML_TEMPLATE = (
    '<!doctype html>\n<!--\nTHESIS: A temporal review register keeps published communications separate from'
    ' observed workload health; it refuses the health-score dashboard.\nOWN-WORLD: CLIENTE yellow #FBC807 '
    'and charcoal #1E1C18 frame neutral sheets; red, brown, blue and slate name evidence states independe'
    'ntly.\nSTORY: Choose a temporal lane, read a communication, inspect potential resource associations a'
    'nd source receipts, then export the evidence.\nFIRST VIEWPORT: Customer frame and title lead into UTC'
    ' context, coverage, temporal navigation and a register beside its detail sheet. Export actions remai'
    'n visible.\nFORM: Grounded structure 7, temporal register with adjacent evidence dossier; surface see'
    'd 5605736e. The supplied brand overrides challenger identities. Narrow screens stack without removin'
    'g evidence.\n-->\n<html lang="en">\n<head>\n<meta charset="utf-8">\n<meta name="viewport" content="width='
    'device-width, initial-scale=1">\n<meta http-equiv="Content-Security-Policy" content="default-src \'non'
    "e'; script-src 'unsafe-inline'; style-src 'unsafe-inline'; img-src data:; connect-src 'none'; base-u"
    'ri \'none\'; form-action \'none\'">\n<title>Service Health review</title>\n<style>\n:root {\n  color-scheme:'
    ' light;\n  --yellow: #fbc807; --charcoal: #1e1c18; --paper: #f1f2f3; --sheet: #ffffff;\n  --ink: #2527'
    '22; --muted: #555b61; --line: #c8ccd0; --quiet: #e8ebed;\n  --incident: #9b2f27; --incident-wash: #fc'
    'eeea; --maintenance: #854a09; --maintenance-wash: #fff1da;\n  --info: #1e5b75; --info-wash: #eaf3f8; '
    '--unknown: #535b67; --unknown-wash: #eceef1; --focus: #155da4;\n  --space-1: 6px; --space-2: 12px; --'
    'space-3: 18px; --space-4: 24px; --space-5: 36px;\n}\n* { box-sizing: border-box; }\nhtml { scroll-behav'
    'ior: smooth; scroll-padding-top: 20px; }\nbody { margin: 0; background: var(--paper); color: var(--in'
    'k); font: 15px/1.5 "Segoe UI", system-ui, sans-serif; }\nbutton, input, select { font: inherit; }\nbut'
    'ton, select, input, a.download { min-height: 42px; border: 1px solid #858d94; border-radius: 3px; }\n'
    'button, select, input { color: var(--ink); background: var(--sheet); }\nbutton, a.download { padding:'
    ' 8px 12px; cursor: pointer; }\nbutton:hover, a.download:hover { background: var(--quiet); }\nbutton:di'
    'sabled { color: var(--muted); border-color: var(--line); cursor: default; background: var(--paper); '
    '}\n:focus-visible { outline: 3px solid var(--focus); outline-offset: 3px; }\na { color: var(--info); t'
    'ext-underline-offset: 3px; }\nh1, h2, h3, p { margin: 0; }\nh1, h2, h3 { line-height: 1.2; text-wrap: '
    'balance; }\nh1 { font-size: clamp(27px, 3vw, 36px); font-weight: 650; letter-spacing: -0.02em; }\nh2 {'
    ' font-size: 22px; font-weight: 650; }\nh3 { font-size: 19px; font-weight: 650; }\np { max-width: 74ch;'
    ' }\nsmall, .small { font-size: 13px; }\n.muted { color: var(--muted); }\n.mono { font: 12px/1.6 ui-mono'
    'space, Consolas, monospace; overflow-wrap: anywhere; }\n.skip { position: absolute; top: -80px; left:'
    ' 12px; z-index: 4; padding: 12px; color: var(--charcoal); background: var(--yellow); }\n.skip:focus {'
    ' top: 12px; }\n.mast { display: grid; grid-template-columns: 218px minmax(0, 1fr); background: var(--'
    'charcoal); color: white; }\n.brand { display: flex; align-items: center; justify-content: center; fle'
    'x-direction: column; gap: 8px; padding: 22px 18px; background: var(--yellow); color: var(--charcoal)'
    '; }\n.brand strong { font-size: 23px; font-weight: 750; letter-spacing: -0.02em; overflow-wrap: anywh'
    'ere; max-width: 100%; }\n.logo-frame { min-height: 48px; width: 100%; max-width: 176px; display: grid'
    '; place-items: center; border: 1px solid var(--charcoal); padding: 8px; }\n.logo-frame img { max-heig'
    'ht: 58px; max-width: 100%; height: auto; width: auto; object-fit: contain; }\n.logo-placeholder { fon'
    't-size: 13px; }\n.mast-copy { padding: 27px 32px 25px; display: flex; flex-direction: column; justify'
    '-content: center; gap: 9px; }\n.mast-copy p { color: #e0dfdc; }\n.provenance { display: flex; align-it'
    'ems: center; flex-wrap: wrap; gap: 8px; font-size: 13px; }\n.provenance strong { padding: 2px 8px; co'
    'lor: var(--charcoal); background: var(--yellow); border-radius: 2px; }\n.toolbar { display: flex; fle'
    'x-wrap: wrap; gap: 8px; padding: 14px 26px; background: var(--sheet); border-bottom: 1px solid var(-'
    '-line); align-items: center; }\n.toolbar a.download { display: inline-flex; align-items: center; text'
    '-decoration: none; color: var(--ink); font-size: 13px; }\n.toolbar button { font-size: 13px; }\n.toolb'
    'ar .ledger-link { margin-left: auto; padding: 8px 2px; min-height: 42px; display: inline-flex; align'
    '-items: center; font-weight: 600; }\nmain { max-width: 1640px; margin: auto; padding: 24px 26px 40px;'
    ' }\n.sheet { background: var(--sheet); border: 1px solid var(--line); border-radius: 3px; }\n.window {'
    ' padding: 20px 22px; }\n.context-grid { display: grid; grid-template-columns: 1.25fr 1fr 1fr; gap: 24'
    'px; margin-top: 14px; }\ndl { margin: 0; }\ndt { font-size: 13px; font-weight: 600; color: var(--muted'
    '); }\ndd { margin: 3px 0 0; overflow-wrap: anywhere; }\n.window-label { display: block; margin-top: 6p'
    'x; font-size: 13px; color: var(--muted); }\n.coverage-line { display: flex; gap: 10px; align-items: b'
    'aseline; flex-wrap: wrap; margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--line); }\n'
    '.tag { display: inline-flex; align-items: center; font-size: 12px; font-weight: 650; padding: 3px 7p'
    'x; border-radius: 2px; line-height: 1.5; }\n.tag.incident { background: var(--incident-wash); color: '
    'var(--incident); }\n.tag.maintenance, .tag.partial { background: var(--maintenance-wash); color: var('
    '--maintenance); }\n.tag.info { background: var(--info-wash); color: var(--info); }\n.tag.unknown { bac'
    'kground: var(--unknown-wash); color: var(--unknown); }\n.limits { margin-top: 9px; font-size: 13px; c'
    'olor: var(--muted); }\n.review { margin-top: 30px; }\n.section-head { display: flex; justify-content: '
    'space-between; align-items: baseline; gap: 16px; margin-bottom: 15px; }\n.lanes { display: flex; flex'
    '-wrap: wrap; gap: 0; border-bottom: 1px solid var(--charcoal); }\n.lane { border-radius: 3px 3px 0 0;'
    ' border: 1px solid var(--line); border-bottom: 0; margin-right: 5px; background: var(--sheet); paddi'
    'ng: 11px 15px; }\n.lane[aria-pressed="true"] { background: var(--yellow); color: var(--charcoal); bor'
    'der-color: var(--charcoal); font-weight: 650; }\n.lane:hover { background: #e8e9e8; }\n.lane[aria-pres'
    'sed="true"]:hover { background: #efbe06; }\n.lane span { margin-left: 7px; font-variant-numeric: tabu'
    'lar-nums; }\n.lane-note { margin-top: 11px; color: var(--muted); font-size: 13px; }\n.filters { displa'
    'y: grid; grid-template-columns: minmax(180px, 1.5fr) repeat(3, minmax(125px, 1fr)) auto; gap: 12px; '
    'padding: 18px 0; align-items: end; }\nlabel { display: flex; flex-direction: column; gap: 5px; font-s'
    'ize: 13px; font-weight: 600; min-width: 0; }\ninput, select { padding: 8px 10px; width: 100%; min-wid'
    'th: 0; font-weight: 400; }\ninput::placeholder { color: var(--muted); opacity: 1; }\n.workbench { disp'
    'lay: grid; grid-template-columns: minmax(0, 1.22fr) minmax(330px, 1fr); gap: 18px; align-items: star'
    't; }\n.register { overflow: hidden; }\n.register-caption { padding: 14px 17px; border-bottom: 1px soli'
    'd var(--line); font-size: 13px; }\n.table-scroll { overflow-x: auto; }\ntable { width: 100%; border-co'
    'llapse: collapse; text-align: left; font-size: 13px; }\nth { background: #f2f4f5; color: #454b50; fon'
    't-size: 12px; font-weight: 650; }\nth, td { padding: 12px; border-bottom: 1px solid #e0e3e5; vertical'
    '-align: top; }\nth:first-child, td:first-child { padding-left: 17px; }\n.events-table { min-width: 510'
    'px; }\n.events-table td:first-child { width: 49%; min-width: 195px; }\n.events-table td:last-child { m'
    'in-width: 90px; }\ntr.selected td { background: #fff8dc; }\ntr:hover td { background: #f5f7f8; }\ntr.se'
    'lected:hover td { background: #fff4ca; }\n.event-open { border: 0; min-height: 0; padding: 0; backgro'
    'und: none; text-align: left; font-weight: 650; color: var(--ink); overflow-wrap: anywhere; line-heig'
    'ht: 1.45; }\n.event-open:hover { background: none; text-decoration: underline; text-underline-offset:'
    ' 3px; }\n.event-labels { margin-top: 8px; display: flex; flex-wrap: wrap; gap: 5px; }\n.cell-time { di'
    'splay: block; margin-top: 6px; color: var(--muted); font-variant-numeric: tabular-nums; }\n.empty { p'
    'adding: 28px 18px; color: var(--muted); }\n.pager { display: flex; justify-content: space-between; fl'
    'ex-wrap: wrap; align-items: center; gap: 10px; padding: 14px 17px; }\n.detail { padding: 21px; min-wi'
    'dth: 0; }\n.detail h3 { margin: 13px 0 8px; overflow-wrap: anywhere; }\n.detail p { overflow-wrap: any'
    'where; }\n.detail-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 15px 2'
    '0px; margin-top: 20px; }\n.detail h4 { font-size: 15px; margin: 24px 0 8px; }\n.source-copy { white-sp'
    'ace: pre-wrap; overflow-wrap: anywhere; max-height: 240px; overflow: auto; font-size: 14px; }\n.uncer'
    'tainties { margin: 8px 0 0; padding-left: 20px; font-size: 13px; color: var(--unknown); }\n.uncertain'
    'ties li { margin: 4px 0; }\ndetails { margin-top: 12px; border-top: 1px solid var(--line); padding-to'
    'p: 11px; }\nsummary { cursor: pointer; font-weight: 600; font-size: 13px; overflow-wrap: anywhere; }\n'
    'pre { white-space: pre-wrap; overflow-wrap: anywhere; font: 12px/1.6 ui-monospace, Consolas, monospa'
    'ce; margin: 12px 0 0; max-height: 420px; overflow: auto; padding: 12px; background: #f4f5f7; color: '
    '#30363b; }\n.resource-records { margin-top: 8px; }\n.resource-records details { margin: 9px 0 0; paddi'
    'ng: 12px 0 3px; }\n.resource-records summary { font-weight: 400; }\n.resource-records .mono { margin-t'
    'op: 8px; }\n.detail-note { margin-top: 12px; padding: 10px 12px; background: var(--info-wash); color:'
    ' var(--info); font-size: 13px; }\n.ledger { margin-top: 34px; }\n.ledger > p { margin-top: 8px; color:'
    ' var(--muted); font-size: 14px; }\n.ledger-list { margin-top: 16px; }\n.source-entry { margin: 0; padd'
    'ing: 16px 20px; border-top: 1px solid var(--line); }\n.source-entry:first-child { border-top: 0; }\n.s'
    'ource-entry summary { display: list-item; }\n.source-entry summary .tag { margin-left: 8px; }\n.source'
    '-stats { font-size: 13px; font-weight: 400; margin-top: 4px; display: block; color: var(--muted); }\n'
    '.source-entry p { margin-top: 10px; font-size: 13px; }\n.ledger-context { padding: 17px 20px; border-'
    'top: 1px solid var(--line); font-size: 13px; }\nfooter { padding-top: 26px; font-size: 13px; color: v'
    'ar(--muted); }\n.error { background: var(--incident-wash); color: var(--incident); padding: 20px; mar'
    'gin-bottom: 20px; }\n[hidden] { display: none !important; }\n@media (max-width: 1100px) {\n  .workbench'
    ' { grid-template-columns: minmax(0, 1fr); }\n  .context-grid { grid-template-columns: 1.3fr 1fr; }\n  '
    '.context-grid > :last-child { grid-column: 1 / -1; }\n  .filters { grid-template-columns: minmax(180p'
    'x, 1.5fr) 1fr 1fr; }\n  .filters label:last-of-type { grid-column: 1 / 3; }\n}\n@media (max-width: 620p'
    'x) {\n  .mast { grid-template-columns: 1fr; }\n  .brand { flex-direction: row; justify-content: space-'
    'between; padding: 14px 18px; gap: 16px; }\n  .brand strong { font-size: 21px; }\n  .logo-frame { min-h'
    'eight: 40px; max-width: 145px; width: 145px; flex-shrink: 0; padding: 6px; }\n  .logo-frame img { max'
    '-height: 44px; }\n  .mast-copy { padding: 22px 18px; }\n  .toolbar { padding: 12px 14px; gap: 8px; }\n '
    ' .toolbar .ledger-link { margin-left: 0; }\n  .toolbar a.download, .toolbar button { min-height: 44px'
    '; }\n  main { padding: 20px 14px 30px; }\n  .window, .detail { padding: 18px; }\n  .context-grid { grid'
    '-template-columns: 1fr; gap: 16px; }\n  .context-grid > :last-child { grid-column: auto; }\n  .section'
    '-head { flex-direction: column; gap: 7px; }\n  .lanes { display: grid; grid-template-columns: repeat('
    '2, minmax(0, 1fr)); gap: 7px; border: 0; }\n  .lane { margin: 0; border: 1px solid var(--line); borde'
    'r-radius: 3px; font-size: 13px; min-height: 48px; padding: 10px 8px; }\n  .filters { grid-template-co'
    'lumns: 1fr 1fr; gap: 12px 10px; }\n  .filters label:first-child { grid-column: 1 / -1; }\n  .filters l'
    'abel:last-of-type { grid-column: auto; }\n  .filters button { min-height: 44px; }\n  .workbench { gap:'
    ' 16px; }\n  .events-table { min-width: 480px; }\n  .detail-grid { grid-template-columns: 1fr; gap: 14p'
    'x; }\n  .source-entry { padding: 15px 17px; }\n}\n@media (prefers-reduced-motion: reduce) { html { scro'
    'll-behavior: auto; } }\n@media print {\n  body { background: white; font-size: 11px; }\n  .mast { grid-'
    'template-columns: 150px 1fr; print-color-adjust: exact; -webkit-print-color-adjust: exact; }\n  .mast'
    '-copy { padding: 15px 20px; }\n  .brand { padding: 14px; }\n  h1 { font-size: 25px; }\n  main { padding'
    ': 15px 0; max-width: none; }\n  .toolbar, .filters, .pager, .skip { display: none; }\n  .workbench { g'
    'rid-template-columns: 1fr; }\n  .window, .detail { padding: 14px; }\n  .context-grid { grid-template-c'
    'olumns: 1fr 1fr; }\n  .context-grid > :last-child { grid-column: 1 / -1; }\n  .lanes { display: flex; '
    '}\n  .lane { font-size: 11px; border: 1px solid var(--line); padding: 6px 9px; min-height: 0; print-c'
    'olor-adjust: exact; }\n  .table-scroll { overflow: visible; }\n  .events-table { min-width: 0; }\n  tr '
    '{ break-inside: avoid; }\n  .source-copy, pre { max-height: none; overflow: visible; }\n  .sheet { bor'
    'der-color: #aaa; }\n  .ledger { break-before: page; }\n  .source-entry { break-inside: avoid; }\n  foot'
    'er { border-top: 1px solid #aaa; margin-top: 16px; }\n}\n</style>\n</head>\n<body>\n<a class="skip" href='
    '"#review">Skip to event review</a>\n<header class="mast">\n  <div class="brand"><strong>__CLIENT_NAME_'
    '_</strong><div class="logo-frame">__COMPANY_LOGO__</div></div>\n  <div class="mast-copy">\n    <h1>Ser'
    'vice Health review</h1>\n    <p>Published incidents and planned maintenance. Evidence for review, not'
    ' a workload-health verdict.</p>\n    <div class="provenance"><strong id="provenance">Opening snapshot'
    '</strong><span id="reference-line">Reading the recorded UTC context.</span></div>\n  </div>\n</header>'
    '\n<nav class="toolbar" aria-label="Report exports and actions">\n  <a class="download" id="full-json" '
    'download="service-health-complete.json">Full source JSON</a>\n  <a class="download" id="filtered-json'
    '" download="service-health-filtered.json">Filtered JSON</a>\n  <a class="download" id="events-csv" do'
    'wnload="service-health-events-filtered.csv">Filtered events CSV</a>\n  <a class="download" id="resour'
    'ces-csv" download="service-health-resources-filtered.csv">Filtered resources CSV</a>\n  <button type='
    '"button" id="print-report">Print filtered review</button>\n  <a class="ledger-link" href="#source-led'
    'ger">Source ledger</a>\n</nav>\n<main>\n  <div id="render-error" class="error" role="alert" hidden></di'
    'v>\n  <noscript><div class="error">JavaScript is required for offline filters and exports. Use the se'
    'parately delivered complete JSON and CSV files; this is not an empty-success report.</div></noscript'
    '>\n  <section class="sheet window" aria-labelledby="window-heading">\n    <h2 id="window-heading">The '
    'window matters</h2>\n    <div class="context-grid">\n      <dl><dt>Requested update window · UTC, end '
    'exclusive</dt><dd id="requested-window"></dd><dd class="window-label">Selection uses lastUpdateTime,'
    ' not impact start or first publication.</dd></dl>\n      <dl><dt>Observed source reads · UTC</dt><dd '
    'id="observed-window"></dd><dd class="window-label">Native status is observed at collection, not a hi'
    'storical as-of state.</dd></dl>\n      <dl><dt>Retained-source queryStartTime · UTC</dt><dd id="query'
    '-start"></dd><dd class="window-label">Older Active events are not removed because their impact began'
    ' before the requested month.</dd></dl>\n    </div>\n    <div class="coverage-line"><span id="coverage-'
    'tag" class="tag unknown"></span><span id="coverage-summary" class="small"></span></div>\n    <p class'
    '="limits">Historical completeness is not proven. New/changed since last run is not established. A Tr'
    'acking ID is not a support-case number.</p>\n  </section>\n  <section class="review" id="review" aria-'
    'labelledby="review-heading">\n    <div class="section-head"><h2 id="review-heading">Communications to'
    ' review</h2><span id="record-counts" class="small muted"></span></div>\n    <div class="lanes" role="'
    'group" aria-label="Temporal scope">\n      <button class="lane" type="button" data-scope="all" aria-p'
    'ressed="true">All returned<span id="count-all"></span></button>\n      <button class="lane" type="but'
    'ton" data-scope="requested_updates" aria-pressed="false">Requested updates<span id="count-requested"'
    '></span></button>\n      <button class="lane" type="button" data-scope="active_now" aria-pressed="fal'
    'se">Active observed<span id="count-active"></span></button>\n      <button class="lane" type="button"'
    ' data-scope="future_maintenance" aria-pressed="false">Future maintenance<span id="count-future"></sp'
    'an></button>\n    </div>\n    <p class="lane-note" id="lane-note">All accepted event records in the re'
    'tained response, including records outside the requested update window. Temporal lanes can overlap.<'
    '/p>\n    <div class="filters" role="search" aria-label="Filter recorded event evidence">\n      <label'
    '>Search communications<input id="search" type="search" maxlength="160" placeholder="Tracking ID, ser'
    'vice, region or text"></label>\n      <label>Event type<select id="event-type"><option value="all">Bo'
    'th event types</option><option value="ServiceIssue">Service incidents</option><option value="Planned'
    'Maintenance">Planned maintenance</option></select></label>\n      <label>Native current state<select '
    'id="state"><option value="all">All states</option><option>Active</option><option>Resolved</option><o'
    'ption>Unknown</option></select></label>\n      <label>Published region<select id="region"><option val'
    'ue="all">All regions</option><option value="__unknown__">Unknown region</option></select></label>\n  '
    '    <button type="button" id="reset">Reset filters</button>\n    </div>\n    <div class="workbench">\n '
    '     <div class="sheet register">\n        <p class="register-caption" id="results" aria-live="polite'
    '"></p>\n        <div class="table-scroll" tabindex="0" role="region" aria-label="Event register, scro'
    'll horizontally if needed">\n          <table class="events-table"><caption hidden>Recorded event com'
    'munications</caption>\n            <thead><tr><th scope="col">Communication</th><th scope="col">Sourc'
    'e state</th><th scope="col">Source times · UTC</th><th scope="col">Resource records</th></tr></thead'
    '>\n            <tbody id="event-rows"></tbody>\n          </table>\n        </div>\n        <div class="'
    'pager"><span id="visible-count" class="small muted"></span><button type="button" id="show-more">Show'
    ' 25 more</button></div>\n      </div>\n      <section class="sheet detail" id="event-detail" tabindex='
    '"-1" aria-label="Selected communication and resource evidence">\n        <p class="muted">Select a co'
    'mmunication to inspect its source record and potential resource associations.</p>\n      </section>\n '
    '   </div>\n  </section>\n  <section class="ledger" id="source-ledger" aria-labelledby="ledger-heading"'
    '>\n    <h2 id="ledger-heading">Source &amp; coverage ledger</h2>\n    <p>Every list and attempted page'
    ' has its own receipt. A first page or HTTP 200 alone is not completeness. Empty, denied and partial '
    'are different outcomes.</p>\n    <div class="sheet ledger-list"><div id="source-entries"></div><div c'
    'lass="ledger-context" id="retention-note"></div></div>\n  </section>\n  <footer><p>Read-only snapshot.'
    ' Published potential impact is not a measured workload outage. Support cases, owners, root-cause ver'
    'ification and prior-run baselines are not collected. Full JSON retains complete accepted response fi'
    'elds and pagination evidence; filtered exports contain every selected event/resource record, not onl'
    'y the visible page.</p></footer>\n</main>\n<script id="complete-json-bytes" type="application/octet-st'
    'ream">__FULL_JSON_BASE64__</script>\n<script id="report-model" type="application/json">__UI_MODEL_JSO'
    'N__</script>\n<script>\n(() => {\n  "use strict";\n  const errorBox = document.getElementById("render-er'
    'ror");\n  try {\n    const data = JSON.parse(document.getElementById("report-model").textContent);\n   '
    ' const fullJSONBase64 = document.getElementById("complete-json-bytes").textContent.trim();\n    if (!'
    'Number.isSafeInteger(data.source_json_bytes) || data.source_json_bytes < 1 || data.source_json_bytes'
    ' > 4800000 ||\n        fullJSONBase64.length !== 4 * Math.ceil(data.source_json_bytes / 3)) throw new'
    ' Error("Invalid complete JSON byte bound.");\n    const binaryJSON = atob(fullJSONBase64);\n    const '
    'sourceJSONBytes = Uint8Array.from(binaryJSON, character => character.charCodeAt(0));\n    if (sourceJ'
    'SONBytes.length !== data.source_json_bytes) throw new Error("Complete JSON byte length differs from '
    'its references.");\n    const decoder = new TextDecoder("utf-8", {fatal: true});\n    const rangeText '
    '= range => {\n      if (!Array.isArray(range) || range.length !== 2 || !range.every(Number.isSafeInte'
    'ger) ||\n          range[0] < 0 || range[1] <= range[0] || range[1] > sourceJSONBytes.length) throw n'
    'ew Error("Invalid source JSON byte reference.");\n      return decoder.decode(sourceJSONBytes.subarra'
    'y(range[0], range[1]));\n    };\n    const completeJSON = record => {\n      const normalized = rangeTe'
    'xt(record.record_range);\n      const original = rangeText(record.source_record_range);\n      if (nor'
    'malized[0] !== "{" || !normalized.endsWith("}") || original[0] !== "{" || !original.endsWith("}")) t'
    'hrow new Error("Referenced records must be JSON objects.");\n      return normalized.slice(0, -1) + \''
    ',"source_record":\' + original + "}";\n    };\n    const prettyJSON = value => {\n      const pieces = ['
    '];\n      let quoted = false, escaped = false, depth = 0;\n      const line = () => "\\n" + "  ".repeat'
    '(depth);\n      for (const character of value) {\n        if (quoted) {\n          pieces.push(characte'
    'r);\n          if (escaped) escaped = false;\n          else if (character === "\\\\") escaped = true;\n '
    '         else if (character === \'"\') quoted = false;\n        } else if (character === \'"\') {\n       '
    '   quoted = true;\n          pieces.push(character);\n        } else if (character === "{" || characte'
    'r === "[") {\n          if (++depth > 100) throw new Error("Source JSON display exceeds the nesting b'
    'ound.");\n          pieces.push(character, line());\n        } else if (character === "}" || character'
    ' === "]") {\n          if (--depth < 0) throw new Error("Unbalanced source JSON display.");\n         '
    ' pieces.push(line(), character);\n        } else if (character === ",") pieces.push(character, line()'
    ');\n        else if (character === ":") pieces.push(": ");\n        else pieces.push(character);\n     '
    ' }\n      if (quoted || escaped || depth) throw new Error("Incomplete source JSON display.");\n      r'
    'eturn pieces.join("");\n    };\n    data.events.concat(data.resources).forEach(record => {\n      range'
    'Text(record.record_range);\n      rangeText(record.source_record_range);\n    });\n    const context = '
    'data.context;\n    const byId = id => document.getElementById(id);\n    const el = (tag, text, classNa'
    'me) => {\n      const node = document.createElement(tag);\n      if (text !== undefined && text !== nu'
    'll) node.textContent = String(text);\n      if (className) node.className = className;\n      return n'
    'ode;\n    };\n    const text = value => value === null || value === undefined || value === "" ? "Unkno'
    'wn / not supplied" : String(value);\n    const utc = value => value || "Unknown (original retained)";'
    '\n    const tag = (label, kind) => el("span", label, "tag " + kind);\n    const typeName = event => ev'
    'ent.event_type === "ServiceIssue" ? "Service incident" : "Planned maintenance";\n    const typeClass '
    '= event => event.event_type === "ServiceIssue" ? "incident" : "maintenance";\n    const statusClass ='
    ' status => status === "Active" ? "info" : "unknown";\n    const goodSource = source => ["complete", "'
    'successful_empty", "successful_empty_in_scope"].includes(source.status);\n    const sourceById = id ='
    '> data.sources.find(source => source.source_id === id);\n    const fields = (items, parent) => {\n    '
    '  const grid = el("div", null, "detail-grid");\n      items.forEach(([label, value, mono]) => {\n     '
    '   const group = el("dl");\n        group.append(el("dt", label), el("dd", text(value), mono ? "mono"'
    ' : ""));\n        grid.append(group);\n      });\n      parent.append(grid);\n    };\n    const rawDetail'
    's = (label, value) => {\n      const details = el("details");\n      details.append(el("summary", labe'
    'l), el("pre", value));\n      return details;\n    };\n    const encoded = string => {\n      const byte'
    's = new TextEncoder().encode(string);\n      let binary = "";\n      for (let index = 0; index < bytes'
    '.length; index += 8192) binary += String.fromCharCode(...bytes.subarray(index, index + 8192));\n     '
    ' return btoa(binary);\n    };\n    const download = (id, content, mime, base64 = false) => {\n      byI'
    'd(id).href = "data:" + mime + ";base64," + (base64 ? content : encoded(content));\n    };\n    const c'
    'sv = (columns, rows) => {\n      const cell = value => \'"\' + String(value).replace(/"/g, \'""\') + \'"\';'
    '\n      return "\\ufeff" + [columns, ...rows].map(row => row.map(cell).join(",")).join("\\r\\n") + "\\r\\n'
    '";\n    };\n    let scope = "all";\n    let selectedKey = null;\n    let shown = 25;\n    let filtered = '
    '[];\n    let printing = false;\n    const laneNotes = {\n      all: "All accepted event records in the '
    'retained response, including records outside the requested update window. Temporal lanes can overlap'
    '.",\n      requested_updates: "lastUpdateTime falls inside the requested UTC interval. This is not im'
    'pact-start history, first publication or newness since last run.",\n      active_now: "The native sou'
    'rce reported Active when read. Old impact-start dates remain visible. This is not reconstructed hist'
    'orical status or workload-outage proof.",\n      future_maintenance: "PlannedMaintenance with a futur'
    'e impactStartTime and not reported Resolved. Future communication is not guaranteed execution, first'
    ' publication or measured impact."\n    };\n    byId("provenance").textContent = context.provenance;\n  '
    '  byId("reference-line").textContent = (context.provenance === "SIMULATED" ? "Offline test evidence,'
    ' not live. " : context.provenance === "PRIVATE_REPLAY" ? "Replayed source evidence, not a fresh run.'
    ' " : "Dated source snapshot. ") + "Reference " + context.reference_utc;\n    byId("requested-window")'
    '.textContent = context.requested_window.start_utc + " to " + context.requested_window.end_utc_exclus'
    'ive;\n    byId("observed-window").textContent = text(context.collection_observed_utc.first) + " to " '
    '+ text(context.collection_observed_utc.last);\n    byId("query-start").textContent = context.source_q'
    'uery.query_start_utc;\n    const partial = context.coverage.status === "partial";\n    byId("coverage-'
    'tag").className = "tag " + (partial ? "partial" : "unknown");\n    byId("coverage-tag").textContent ='
    ' partial ? "Partial source coverage" : "Returned pages complete";\n    byId("coverage-summary").textC'
    'ontent = data.summary.incomplete_sources + " incomplete source(s); historical completeness is not pr'
    'oven."\n      + (context.coverage.event_source_successful_empty ? " No in-scope event records returne'
    'd: source validation only, not resilience." : "");\n    byId("record-counts").textContent = data.summ'
    'ary.native_event_records_received + " received · " + data.summary.event_records + " in scope · " + d'
    'ata.summary.excluded_category_records + " other-category records excluded";\n    const regions = [...'
    'new Set(data.events.flatMap(event => event.regions))].sort((a, b) => a.localeCompare(b));\n    region'
    's.forEach(region => { const option = el("option", region); option.value = region; byId("region").app'
    'end(option); });\n    byId("count-all").textContent = data.summary.event_records;\n    byId("count-req'
    'uested").textContent = data.summary.requested_update_records;\n    byId("count-active").textContent ='
    ' data.summary.active_observed_records;\n    byId("count-future").textContent = data.summary.future_ma'
    'intenance_records;\n    download("full-json", fullJSONBase64, "application/json;charset=utf-8", true)'
    ';\n    byId("retention-note").textContent = context.source_query.retention + " The explicit " + conte'
    'xt.source_query.lookback_days + "-day lookback is a request, not a guarantee. Accepted record lastUp'
    'dateTime extent: " + text(context.observed_last_update_extent.first_original) + " to " + text(contex'
    't.observed_last_update_extent.last_original) + "; " + context.observed_last_update_extent.missing_or'
    '_invalid + " missing/invalid. This extent is not complete history. No historical daily as-of status,'
    ' workload outage measurement or previous-run baseline is available.";\n    data.sources.forEach((sour'
    'ce, index) => {\n      const entry = el("details", null, "source-entry");\n      entry.id = "source-" '
    '+ index;\n      const heading = el("summary", source.source_id);\n      heading.append(tag(source.stat'
    'us.replace(/_/g, " "), goodSource(source) ? "unknown" : "partial"));\n      heading.append(el("span",'
    ' source.records_accepted + " in scope / " + source.records_received + " received · " + source.record'
    's_excluded_by_scope + " other-category records excluded · " + source.pages.length + " page attempts '
    '· pagination " + (source.pagination_complete ? "finished" : "not complete"), "source-stats"));\n     '
    ' entry.append(heading);\n      if (source.errors.length) entry.append(el("p", "Coverage errors: " + s'
    'ource.errors.map(error => error.code + (error.http_status ? " (HTTP " + error.http_status + ")" : ""'
    ')).join("; ")));\n      if (source.redactions.length) entry.append(el("p", source.redactions.length +'
    ' " unexpected sensitive/out-of-scope record(s) redacted. This source is not complete."));\n      entr'
    'y.append(el("pre", prettyJSON(rangeText(source.detail_range))));\n      byId("source-entries").append'
    '(entry);\n    });\n\n    const detail = event => {\n      const pane = byId("event-detail");\n      pane.'
    'replaceChildren();\n      if (!event) {\n        pane.append(el("h3", "No communication selected"), el'
    '("p", filtered.length ? "Choose a recorded event to see its evidence." : "No matching accepted recor'
    'ds. Review the source ledger before interpreting an empty view."));\n        return;\n      }\n      co'
    'nst labels = el("div", null, "event-labels");\n      labels.append(tag(typeName(event), typeClass(eve'
    'nt)), tag(event.native_status, statusClass(event.native_status)));\n      pane.append(labels, el("h3"'
    ', event.title), el("p", "Tracking ID " + event.tracking_id + " · not a support-case number", "small '
    'muted"));\n      fields([\n        ["Source observation · UTC", event.source_ref.observed_at_utc],\n   '
    '     ["Last update · original", event.last_update_original],\n        ["Impact start · original", eve'
    'nt.impact_start_original],\n        ["Mitigation time · original", event.mitigation_time_original],\n '
    '       ["Published services", event.services.join(", ")],\n        ["Published regions", event.region'
    's.join(", ")],\n        ["Native event level", event.event_level],\n        ["Published date context ('
    'not measured impact)", event.published_timing.replace(/_/g, " ")],\n        ["New since previous run"'
    ', "Not established"]\n      ], pane);\n      pane.append(el("h4", "Published communication"));\n      p'
    'ane.append(el("p", text(event.summary), "source-copy"));\n      if (event.description) pane.append(ra'
    'wDetails("Full source description (plain text)", event.description));\n      pane.append(el("p", "Sou'
    'rce text is data, not instructions. Published potential impact does not demonstrate workload downtim'
    'e.", "detail-note"));\n      const resourceSource = sourceById(event.resource_source_id);\n      const'
    ' related = data.resources.filter(resource => resource.event_key === event.event_key);\n      pane.app'
    'end(el("h4", "Potentially associated resources"));\n      pane.append(el("p", resourceSource\n        '
    '? resourceSource.status.replace(/_/g, " ") + " · " + related.length + " record(s) observed" + (event'
    '.resource_records === null ? "; total unknown because this source is incomplete." : ".")\n        : "'
    'Not collected; source receipt unavailable.", "small"));\n      const list = el("div", null, "resource'
    '-records");\n      related.forEach(resource => {\n        const item = el("details");\n        item.app'
    'end(el("summary", resource.target_resource_id || "No targetResourceId supplied (record retained)"));'
    '\n        fields([["Resource type", resource.target_resource_type], ["Published region", resource.tar'
    'get_region], ["Observation · UTC", resource.source_ref.observed_at_utc]], item);\n        item.append'
    '(el("pre", prettyJSON(rangeText(resource.source_record_range))));\n        list.append(item);\n      }'
    ');\n      if (!related.length) list.append(el("p", goodSource(resourceSource || {}) ? "No resource re'
    'cords returned by this completed source. Do not infer no workload impact." : "No accepted rows avail'
    'able; this is not evidence of no affected resources.", "small muted"));\n      pane.append(list, el("'
    'h4", "Unknowns & boundaries"));\n      const unknowns = el("ul", null, "uncertainties");\n      [...ev'
    'ent.uncertainties, "Support cases and workload owners not collected.", "No baseline or reliable firs'
    't-publication time; no automatic new/changed claim."].forEach(note => unknowns.append(el("li", note)'
    '));\n      pane.append(unknowns, rawDetails("Original event record · every returned field", prettyJSO'
    'N(rangeText(event.source_record_range))));\n      fields([["Native event ID", event.id, true], ["Even'
    't source receipt", event.source_ref.source_id, true], ["Resource source receipt", event.resource_sou'
    'rce_id, true]], pane);\n    };\n    const exports = () => {\n      const keys = new Set(filtered.map(ev'
    'ent => event.event_key));\n      const resources = data.resources.filter(resource => keys.has(resourc'
    'e.event_key));\n      const sourceIds = new Set(filtered.flatMap(event => [event.source_ref.source_id'
    ', event.resource_source_id]));\n      const receipts = data.sources.filter(source => sourceIds.has(so'
    'urce.source_id));\n      const content = \'{"context":\' + JSON.stringify(context)\n        + \',"export_'
    'scope":"All selected complete records; unfiltered original page envelopes remain in Full source JSON'
    '."\'\n        + \',"events":[\' + filtered.map(completeJSON).join(",") + \']\'\n        + \',"impacted_resou'
    'rces":[\' + resources.map(completeJSON).join(",") + \']\'\n        + \',"source_receipts":[\' + receipts.m'
    'ap(source => source.receipt_json).join(",") + "]}\\n";\n      download("filtered-json", content, "appl'
    'ication/json;charset=utf-8");\n      download("events-csv", csv(data.event_csv_fields, filtered.map(e'
    'vent => [...event.csv_cells, completeJSON(event)])), "text/csv;charset=utf-8");\n      download("reso'
    'urces-csv", csv(data.resource_csv_fields, resources.map(resource => [...resource.csv_cells, complete'
    'JSON(resource)])), "text/csv;charset=utf-8");\n    };\n    const render = () => {\n      const search ='
    ' byId("search").value.toLocaleLowerCase();\n      const kind = byId("event-type").value;\n      const '
    'state = byId("state").value;\n      const region = byId("region").value;\n      filtered = data.events'
    '.filter(event =>\n        (scope === "all" || event.temporal[scope]) &&\n        (kind === "all" || ev'
    'ent.event_type === kind) &&\n        (state === "all" || event.native_status === state) &&\n        (r'
    'egion === "all" || (region === "__unknown__" ? !event.regions.length : event.regions.includes(region'
    '))) &&\n        [event.title, event.summary || "", event.description || "", event.tracking_id, event.'
    'id, ...event.services, ...event.regions].join(" ").toLocaleLowerCase().includes(search)\n      );\n   '
    '   filtered.sort((a, b) => (new Date(b.last_update_original).getTime() || 0) - (new Date(a.last_upda'
    'te_original).getTime() || 0));\n      const body = byId("event-rows");\n      body.replaceChildren();\n'
    '      if (!filtered.some(event => event.event_key === selectedKey)) selectedKey = filtered[0]?.event'
    '_key || null;\n      const visible = printing ? filtered : filtered.slice(0, shown);\n      visible.fo'
    'rEach(event => {\n        const row = el("tr", null, event.event_key === selectedKey ? "selected" : "'
    '");\n        const communication = el("td");\n        const open = el("button", event.title, "event-op'
    'en");\n        open.type = "button";\n        open.setAttribute("aria-controls", "event-detail");\n    '
    '    open.setAttribute("aria-pressed", String(event.event_key === selectedKey));\n        open.addEven'
    'tListener("click", () => {\n          selectedKey = event.event_key;\n          render();\n          co'
    'nst dossier = byId("event-detail");\n          dossier.focus({preventScroll: true});\n          dossie'
    'r.scrollIntoView({block: "start"});\n        });\n        communication.append(open, el("span", event.'
    'tracking_id, "cell-time mono"));\n        const labels = el("div", null, "event-labels");\n        lab'
    'els.append(tag(typeName(event), typeClass(event)));\n        communication.append(labels);\n        co'
    'nst stateCell = el("td");\n        stateCell.append(tag(event.native_status, statusClass(event.native'
    '_status)));\n        const times = el("td");\n        times.append(el("span", "Start " + utc(event.imp'
    'act_start_utc)), el("span", "Updated " + utc(event.last_update_utc), "cell-time"));\n        const re'
    'sourceCell = el("td", event.resource_records === null ? event.resource_records_observed + " observed'
    '; total unknown" : String(event.resource_records));\n        row.append(communication, stateCell, tim'
    'es, resourceCell);\n        body.append(row);\n      });\n      if (!filtered.length) {\n        const r'
    'ow = el("tr");\n        const cell = el("td", data.events.length\n          ? "No records match these '
    'filters. Reset filters to review all returned evidence."\n          : partial ? "No event records acc'
    'epted. Collection is partial; inspect the source ledger."\n          : "Successful-empty event reads.'
    ' This validates the source, not workload health or resilience.", "empty");\n        cell.colSpan = 4;'
    '\n        row.append(cell);\n        body.append(row);\n      }\n      byId("results").textContent = fil'
    'tered.length + " matching / " + data.events.length + " accepted event records. Exports include all m'
    'atches and related resource rows.";\n      byId("visible-count").textContent = "Showing " + visible.l'
    'ength + " of " + filtered.length + " matches";\n      byId("show-more").disabled = visible.length >= '
    'filtered.length;\n      byId("show-more").hidden = filtered.length <= 25;\n      byId("lane-note").tex'
    'tContent = laneNotes[scope];\n      document.querySelectorAll(".lane").forEach(button => button.setAt'
    'tribute("aria-pressed", String(button.dataset.scope === scope)));\n      detail(filtered.find(event ='
    '> event.event_key === selectedKey));\n      exports();\n    };\n    document.querySelectorAll(".lane").'
    'forEach(button => button.addEventListener("click", () => { scope = button.dataset.scope; shown = 25;'
    ' render(); }));\n    ["event-type", "state", "region"].forEach(id => byId(id).addEventListener("chang'
    'e", () => { shown = 25; render(); }));\n    byId("search").addEventListener("input", () => { shown = '
    '25; render(); });\n    byId("reset").addEventListener("click", () => {\n      byId("search").value = "'
    '";\n      ["event-type", "state", "region"].forEach(id => byId(id).value = "all");\n      scope = "all'
    '"; shown = 25; render();\n    });\n    byId("show-more").addEventListener("click", () => { shown += 25'
    '; render(); });\n    byId("print-report").addEventListener("click", () => window.print());\n    window'
    '.addEventListener("beforeprint", () => { printing = true; render(); });\n    window.addEventListener('
    '"afterprint", () => { printing = false; render(); });\n    render();\n  } catch (error) {\n    errorBox'
    '.hidden = false;\n    errorBox.textContent = "The offline report could not initialize. Do not interpr'
    'et this as an empty source. Open the separately delivered complete JSON/CSV files and report the ren'
    'der error to the operator.";\n    console.error("Offline report initialization failed", error);\n  }\n}'
    ')();\n</script>\n</body>\n</html>\n'
)
# END BUILD-TIME ASSETS


class EvidenceError(RuntimeError):
    def __init__(self, code, message, source="validation", http_status=None, receipt=None):
        super().__init__(message)
        self.code = code
        self.source = source
        self.http_status = http_status
        self.receipt = receipt

    def document(self):
        result = {"code": self.code, "source": self.source, "message": str(self)}
        if self.http_status is not None:
            result["http_status"] = self.http_status
        return result


def utc_now():
    return datetime.now(timezone.utc)


def iso(value):
    value = value.astimezone(timezone.utc)
    return value.isoformat(timespec="microseconds" if value.microsecond else "seconds").replace("+00:00", "Z")


def json_text(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), allow_nan=False)


def decode_json(data):
    def unique_object(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("Duplicate JSON object key.")
            result[key] = value
        return result

    def reject_constant(value):
        raise ValueError("Nonfinite JSON constant.")

    result = json.loads(data, object_pairs_hook=unique_object, parse_constant=reject_constant)
    pending = [(result, 0)]
    while pending:
        item, depth = pending.pop()
        if depth > MAX_JSON_DEPTH:
            raise ValueError("JSON nesting exceeds its explicit bound.")
        if isinstance(item, dict):
            for key in item:
                key.encode("utf-8")
            pending.extend((value, depth + 1) for value in item.values())
        elif isinstance(item, list):
            pending.extend((value, depth + 1) for value in item)
        elif isinstance(item, str):
            item.encode("utf-8")
        elif isinstance(item, float) and not (-float("inf") < item < float("inf")):
            raise ValueError("Nonfinite JSON number.")
    return result


def response_bytes(value):
    return len(json.dumps(value).encode("utf-8"))


def budget_response(value):
    if response_bytes(value) > TRANSPORT_BYTES:
        raise EvidenceError("response_size_exceeded", "Default-serialized tool result exceeds 3500 bytes; no truncated result is returned.", "transport")
    return value


def configured_guid(value, name):
    try:
        valid = isinstance(value, str) and str(UUID(value)) == value.lower() and UUID(value).int != 0
    except (ValueError, AttributeError):
        valid = False
    if not valid:
        raise EvidenceError("configuration_required", "Set a real fixed " + name + " in the administrator-owned code before authentication.", "configuration")
    return value.lower()


def plain_text(value, field, maximum, empty=False):
    if not isinstance(value, str) or len(value) > maximum or (not empty and not value.strip()) or re.search(r"[\x00-\x1f\x7f\ud800-\udfff]", value):
        raise EvidenceError("invalid_parameter", field + " must be bounded plain text.", "parameters")
    return value.strip()


def configuration():
    config = {
        "subscription_id": configured_guid(SUBSCRIPTION_ID, "SUBSCRIPTION_ID"),
        "tenant_id": configured_guid(TENANT_ID, "TENANT_ID"),
        "client_id": configured_guid(MANAGED_IDENTITY_CLIENT_ID, "MANAGED_IDENTITY_CLIENT_ID"),
    }
    try:
        config["client_name"] = plain_text(CLIENT_NAME, "CLIENT_NAME", 120)
    except EvidenceError as exc:
        raise EvidenceError("invalid_branding", "CLIENT_NAME must contain 1 to 120 plain characters.", "branding") from exc
    return config


def logo_markup():
    try:
        alt = plain_text(COMPANY_LOGO_ALT_TEXT, "COMPANY_LOGO_ALT_TEXT", 120)
    except EvidenceError as exc:
        raise EvidenceError("invalid_company_logo", "Provide descriptive customer-logo alt text of 1 to 120 plain characters.", "branding") from exc
    if COMPANY_LOGO_DATA_URI == "":
        return '<span class="logo-placeholder">Customer logo</span>'
    if not isinstance(COMPANY_LOGO_DATA_URI, str):
        raise EvidenceError("invalid_company_logo", "The optional logo must be a PNG/JPEG base64 data URI.", "branding")
    if len(COMPANY_LOGO_DATA_URI) > ((MAX_LOGO_BYTES + 2) // 3) * 4 + 32:
        raise EvidenceError("invalid_company_logo", "Logo exceeds the 100000-byte raster bound.", "branding")
    match = re.fullmatch(r"data:image/(png|jpeg);base64,([A-Za-z0-9+/]+={0,2})", COMPANY_LOGO_DATA_URI)
    if match is None:
        raise EvidenceError("invalid_company_logo", "Only an embedded PNG/JPEG is allowed; no remote URL or SVG.", "branding")
    try:
        data = base64.b64decode(match[2], validate=True)
    except (ValueError, binascii.Error) as exc:
        raise EvidenceError("invalid_company_logo", "Logo base64 is invalid.", "branding") from exc
    if not 1 <= len(data) <= MAX_LOGO_BYTES:
        raise EvidenceError("invalid_company_logo", "Logo must contain 1 to 100000 raster bytes.", "branding")
    try:
        from PIL import Image, UnidentifiedImageError
    except ImportError as exc:
        raise EvidenceError("dependency_missing", "Configured branding requires Pillow raster validation.", "branding") from exc
    try:
        with Image.open(io.BytesIO(data), formats=["PNG", "JPEG"]) as image:
            width, height = image.size
            if (
                image.format != ("PNG" if match[1] == "png" else "JPEG")
                or not 1 <= width <= MAX_LOGO_DIMENSION
                or not 1 <= height <= MAX_LOGO_DIMENSION
                or getattr(image, "n_frames", 1) != 1
            ):
                raise EvidenceError("invalid_company_logo", "Use one frame, matching PNG/JPEG MIME, at most 2048 by 2048 pixels.", "branding")
            image.verify()
        with Image.open(io.BytesIO(data), formats=["PNG", "JPEG"]) as image:
            image.load()
    except (OSError, ValueError, SyntaxError, UnidentifiedImageError, Image.DecompressionBombError) as exc:
        raise EvidenceError("invalid_company_logo", "The logo is not a complete valid raster.", "branding") from exc
    return (
        '<img src="' + html.escape(COMPANY_LOGO_DATA_URI, quote=True) + '" alt="'
        + html.escape(alt, quote=True) + '" width="' + str(width) + '" height="' + str(height) + '">'
    )


def parse_utc(value, field):
    if not isinstance(value, str) or len(value) > 40:
        raise EvidenceError("invalid_time", field + " must be an ISO 8601 UTC timestamp.", "parameters")
    fraction = re.search(r"\.(\d+)", value)
    if fraction is not None and any(char != "0" for char in fraction[1][6:]):
        raise EvidenceError("invalid_time", field + " supports at most microsecond precision; no sub-microsecond input is rounded silently.", "parameters")
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise EvidenceError("invalid_time", field + " must be an ISO 8601 UTC timestamp.", "parameters") from exc
    if result.tzinfo is None or result.utcoffset() != timedelta(0):
        raise EvidenceError("invalid_time", field + " requires Z or an explicit zero UTC offset.", "parameters")
    return result.astimezone(timezone.utc)


def parameters(operation, period, start_utc, end_utc, view, event_type, state, time_scope, search, limit, offset, reference):
    enums = {
        "operation": (operation, ("report", "query")),
        "period": (period, ("auto", "previous_month", "last_24h", "last_7d", "custom")),
        "view": (view, ("summary", "events", "resources", "coverage")),
        "event_type": (event_type, ("all", *EVENT_TYPES)),
        "state": (state, ("all", "Active", "Resolved", "Unknown")),
        "time_scope": (time_scope, TEMPORAL_SCOPES),
    }
    for field, (value, allowed) in enums.items():
        if not isinstance(value, str) or value not in allowed:
            raise EvidenceError("invalid_parameter", field + " must be one of its documented values.", "parameters")
    if type(limit) is not int or not 1 <= limit <= 50 or type(offset) is not int or not 0 <= offset <= 10_000:
        raise EvidenceError("invalid_parameter", "limit requires int 1-50 and offset int 0-10000; booleans/floats are rejected.", "parameters")
    search = plain_text(search, "search", 160, empty=True)
    if operation == "report" and (view != "summary" or event_type != "all" or state != "all" or time_scope != "all" or search or limit != 10 or offset != 0):
        raise EvidenceError("invalid_combination", "Report mode retains all collected evidence; use default query-only filters and paging.", "parameters")
    if view in ("summary", "coverage") and (event_type != "all" or state != "all" or time_scope != "all" or search):
        raise EvidenceError("invalid_combination", "Event filters apply only to events/resources, not summary/coverage.", "parameters")
    selected = ("previous_month" if operation == "report" else "last_24h") if period == "auto" else period
    if selected == "custom":
        start, end = parse_utc(start_utc, "start_utc"), parse_utc(end_utc, "end_utc")
    else:
        if start_utc != "" or end_utc != "":
            raise EvidenceError("invalid_combination", "start_utc/end_utc are accepted only with period=custom.", "parameters")
        if selected == "previous_month":
            end = reference.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            start = (end - timedelta(days=1)).replace(day=1)
        else:
            end = reference
            start = end - timedelta(days=1 if selected == "last_24h" else 7)
    if not start < end <= reference or end - start > timedelta(days=MAX_REQUESTED_DAYS) or start < reference - timedelta(days=RETAINED_LOOKBACK_DAYS):
        raise EvidenceError("invalid_window", "Request a past UTC window of at most 93 days within the 365-day retained-source lookback.", "parameters")
    return {
        "operation": operation, "view": view, "event_type": event_type, "state": state,
        "time_scope": time_scope, "search": search, "limit": limit, "offset": offset,
        "window": {"period": selected, "start_utc": iso(start), "end_utc_exclusive": iso(end), "basis": "lastUpdateTime"},
        "source_query_start_utc": iso(reference - timedelta(days=RETAINED_LOOKBACK_DAYS)),
    }


def events_url(config, query_start):
    query = urlencode({"api-version": API_VERSION, "queryStartTime": query_start})
    return ORIGIN + "/subscriptions/" + config["subscription_id"] + "/providers/Microsoft.ResourceHealth/events?" + query


def resources_url(config, tracking_id):
    if not isinstance(tracking_id, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", tracking_id) is None:
        raise EvidenceError("invalid_event_identity", "Event name cannot be used as a bounded native event path.", "source_scope")
    return (
        ORIGIN + "/subscriptions/" + config["subscription_id"]
        + "/providers/Microsoft.ResourceHealth/events/" + quote(tracking_id, safe="")
        + "/impactedResources?api-version=" + API_VERSION
    )


def query_pairs(url, source):
    try:
        pairs = parse_qsl(urlsplit(url).query, keep_blank_values=True, strict_parsing=True)
    except ValueError as exc:
        raise EvidenceError("unsafe_source_url", "Source URL has malformed query parameters.", source) from exc
    result = {}
    for key, value in pairs:
        key = key.casefold()
        if key in result:
            raise EvidenceError("unsafe_source_url", "Source URL repeats a query parameter.", source)
        result[key] = value
    return result


def validate_request(url, config):
    if not isinstance(url, str) or len(url) > 16_000 or re.search(r"[\x00-\x20\x7f\\]|%(?![0-9A-Fa-f]{2})", url):
        raise EvidenceError("unsafe_source_url", "Source URL is not a bounded HTTPS native request.", "source_scope")
    try:
        parsed = urlsplit(url)
    except ValueError as exc:
        raise EvidenceError("unsafe_source_url", "Source URL has an invalid authority.", "source_scope") from exc
    prefix = "/subscriptions/" + config["subscription_id"] + "/providers/Microsoft.ResourceHealth/events"
    if parsed.scheme != "https" or parsed.netloc.casefold() != "management.azure.com" or parsed.fragment:
        raise EvidenceError("unsafe_source_url", "Only the fixed ARM origin is allowed; no redirects or credentials in URLs.", "source_scope")
    decoded = unquote(parsed.path)
    if decoded != parsed.path or "\\" in decoded or any(part in (".", "..") for part in decoded.split("/")):
        raise EvidenceError("unsafe_source_url", "Encoded paths, traversal and alternate separators are forbidden.", "source_scope")
    query = query_pairs(url, "source_scope")
    continuation = {"$skiptoken", "skiptoken"}
    if query.get("api-version") != API_VERSION or any(not query[key] for key in continuation & query.keys()):
        raise EvidenceError("unsafe_source_url", "Native API version and nonempty continuation are required.", "source_scope")
    if parsed.path == prefix:
        if set(query) - continuation != {"api-version", "querystarttime"}:
            raise EvidenceError("unsafe_source_url", "Only the native subscription feed with explicit queryStartTime is allowed; categories are selected locally.", "source_scope")
        parse_utc(query["querystarttime"], "queryStartTime")
    elif re.fullmatch(re.escape(prefix) + r"/[A-Za-z0-9][A-Za-z0-9_-]{0,127}/impactedResources", parsed.path):
        if set(query) - continuation != {"api-version"}:
            raise EvidenceError("unsafe_source_url", "Impacted-resource requests accept only the fixed API version and continuation.", "source_scope")
    else:
        raise EvidenceError("unsafe_source_url", "Only configured subscription events and their impactedResources may be read.", "source_scope")


def next_link(link, initial, config):
    if not isinstance(link, str) or len(link) > 16_000:
        raise EvidenceError("invalid_pagination", "Continuation must be a bounded native URL.", "pagination")
    query, required = query_pairs(link, "pagination"), query_pairs(initial, "pagination")
    if query.get("api-version") != required["api-version"]:
        raise EvidenceError("invalid_pagination", "Continuation changed/omitted the fixed API version.", "pagination")
    if "querystarttime" in required and "querystarttime" not in query:
        try:
            parts = urlsplit(link)
        except ValueError as exc:
            raise EvidenceError("invalid_pagination", "Continuation has an invalid authority.", "pagination") from exc
        pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
        pairs.append(("queryStartTime", required["querystarttime"]))
        link = urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(pairs), parts.fragment))
        query["querystarttime"] = required["querystarttime"]
    validate_request(link, config)
    current, original = urlsplit(link), urlsplit(initial)
    if current.path != original.path:
        raise EvidenceError("invalid_pagination", "Continuation changed the source resource path.", "pagination")
    if any(query.get(key) != value for key, value in required.items()) or set(query) - set(required) - {"$skiptoken", "skiptoken"}:
        raise EvidenceError("invalid_pagination", "Continuation changed/omitted query scope or added an unsupported parameter.", "pagination")
    if "$skiptoken" in query and "skiptoken" in query:
        raise EvidenceError("invalid_pagination", "Continuation supplied ambiguous skip tokens.", "pagination")
    return link


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


class NativeReader:
    def __init__(self, config):
        try:
            from azure.identity import ManagedIdentityCredential, CredentialUnavailableError
            from azure.core.exceptions import ClientAuthenticationError, ServiceRequestError
        except ImportError as exc:
            raise EvidenceError("dependency_missing", "Install azure-identity; no human/CLI credential fallback is available.", "identity") from exc
        self.config = config
        self.credential = ManagedIdentityCredential(
            client_id=config["client_id"], connection_timeout=5, read_timeout=10, retry_total=0,
        )
        self.auth_errors = (CredentialUnavailableError, ClientAuthenticationError, ServiceRequestError)
        self.opener = build_opener(NoRedirect())
        self.deadline = time.monotonic() + MAX_COLLECTION_SECONDS
        self.attempt_count = 0
        self.cached_token = None

    def close(self):
        self.credential.close()

    def token(self):
        if self.cached_token is not None and self.cached_token.expires_on > time.time() + 60:
            return self.cached_token.token
        try:
            token = self.credential.get_token(ORIGIN + "/.default")
        except self.auth_errors as exc:
            raise EvidenceError("authentication_failed", "The fixed managed identity could not acquire an ARM token.", "identity") from exc
        try:
            body = token.token.split(".")[1]
            claims = decode_json(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
        except (AttributeError, IndexError, ValueError, RecursionError, binascii.Error) as exc:
            raise EvidenceError("identity_mismatch", "Managed-identity token claims could not be verified; token data is excluded.", "identity") from exc
        if not isinstance(claims, dict) or (
            str(claims.get("tid", "")).lower() != self.config["tenant_id"]
            or str(claims.get("appid", claims.get("azp", ""))).lower() != self.config["client_id"]
            or str(claims.get("aud", "")).rstrip("/") != ORIGIN
        ):
            raise EvidenceError("identity_mismatch", "Token tenant/client/audience differs from fixed configuration.", "identity")
        self.cached_token = token
        return token.token

    def get(self, url, source):
        validate_request(url, self.config)
        attempts = []
        for attempt in range(2):
            if self.attempt_count >= MAX_HTTP_ATTEMPTS or time.monotonic() >= self.deadline:
                raise EvidenceError("collection_bound", "The shared request/deadline bound was reached; remaining evidence is unavailable.", source, receipt={"attempts": attempts})
            self.attempt_count += 1
            token = self.token()
            remaining = self.deadline - time.monotonic()
            if remaining <= 0:
                raise EvidenceError("collection_bound", "The collection deadline expired during managed-identity acquisition; no ARM request was sent.", source, receipt={"attempts": attempts})
            request = Request(url, headers={"Authorization": "Bearer " + token, "Accept": "application/json"}, method="GET")
            started = iso(utc_now())
            try:
                try:
                    response = self.opener.open(request, timeout=max(0.1, min(20, remaining)))
                except HTTPError as exc:
                    response = exc
                with response:
                    status = response.code
                    request_id = response.headers.get("x-ms-request-id", "")
                    retry_after = response.headers.get("Retry-After", "")
                    chunks, length, complete = [], 0, False
                    while length <= MAX_RESPONSE_BYTES:
                        if time.monotonic() >= self.deadline:
                            attempts.append({
                                "started_at_utc": started, "finished_at_utc": iso(utc_now()),
                                "http_status": status, "body_incomplete": True, "response_bytes_observed": length,
                            })
                            raise EvidenceError("collection_bound", "The collection deadline expired while reading the native response; an incomplete body was not accepted.", source, status, {"attempts": attempts})
                        # read1 permits a deadline check between buffered network reads.
                        chunk = response.read1(min(65_536, MAX_RESPONSE_BYTES + 1 - length))
                        if not chunk:
                            complete = True
                            break
                        chunks.append(chunk)
                        length += len(chunk)
                    data = b"".join(chunks)
            except (URLError, TimeoutError, OSError, HTTPException) as exc:
                attempts.append({"started_at_utc": started, "finished_at_utc": iso(utc_now()), "http_status": None, "code": "transport_failed"})
                raise EvidenceError("transport_failed", "Native HTTPS read failed; no empty response was substituted.", source, receipt={"attempts": attempts}) from exc
            receipt = {
                "started_at_utc": started, "finished_at_utc": iso(utc_now()),
                "http_status": status, "response_bytes": len(data),
                "response_complete": complete,
                "request_id": request_id, "response_sha256": hashlib.sha256(data).hexdigest(),
            }
            attempts.append(receipt)
            if len(data) > MAX_RESPONSE_BYTES:
                raise EvidenceError("source_response_too_large", "Native response exceeds 20000000 bytes; an incomplete body was not accepted.", source, status, {"attempts": attempts})
            try:
                payload = decode_json(data)
            except (ValueError, UnicodeDecodeError, RecursionError) as exc:
                raise EvidenceError("invalid_response_json", "Native response is not valid bounded JSON; raw non-JSON bodies are excluded.", source, status, {"attempts": attempts}) from exc
            if status in (429, 500, 502, 503, 504) and attempt == 0:
                receipt["error_response"] = payload
                delay = min(int(retry_after), 2) if re.fullmatch(r"[0-9]{1,4}", retry_after) else 1
                time.sleep(min(delay, max(0, self.deadline - time.monotonic())))
                continue
            return {"http_status": status, "payload": payload, "attempts": attempts, "observed_at_utc": receipt["finished_at_utc"]}
        raise EvidenceError("source_retry_exhausted", "Native retry bound was exhausted.", source)


def source_error(code, message, source, http_status=None):
    return EvidenceError(code, message, source, http_status).document()


def record_in_scope(raw, kind, config, tracking_id=None):
    if not isinstance(raw, dict):
        return "Record is not an object."
    identity = raw.get("id")
    prefix = "/subscriptions/" + config["subscription_id"] + "/providers/Microsoft.ResourceHealth/events/"
    if not isinstance(identity, str) or "\\" in identity or "%" in identity or "?" in identity or "#" in identity or any(part in (".", "..") for part in identity.split("/")):
        return "Record has no safe native subscription identity."
    if kind == "events":
        name = raw.get("name")
        if not isinstance(name, str) or re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_-]{0,127}", name) is None:
            return "Event identity is outside the fixed subscription or cannot be verified."
        accepted_ids = (
            prefix + name, "/providers/Microsoft.ResourceHealth/events/" + name,
            "Microsoft.ResourceHealth/events/" + name,
        )
        if identity.casefold() not in [candidate.casefold() for candidate in accepted_ids]:
            return "Event identity is outside the fixed subscription or cannot be verified."
        props = raw.get("properties")
        if not isinstance(props, dict) or props.get("eventType") not in EVENT_TYPES or (props.get("isEventSensitive") is not None and props.get("isEventSensitive") is not False):
            return "Event category/sensitivity is outside the fixed nonsensitive category read."
    else:
        prefixes = (
            prefix + tracking_id + "/impactedResources/",
            "/providers/Microsoft.ResourceHealth/events/" + tracking_id + "/impactedResources/",
            "Microsoft.ResourceHealth/events/" + tracking_id + "/impactedResources/",
        )
        expected = next((item for item in prefixes if identity.casefold().startswith(item.casefold())), None)
        if expected is None or not identity[len(expected):] or "/" in identity[len(expected):]:
            return "Impacted-resource record identity is outside its subscription event."
        props = raw.get("properties")
        target = props.get("targetResourceId") if isinstance(props, dict) else None
        if isinstance(target, str) and target.casefold().startswith("/subscriptions/") and not target.casefold().startswith(("/subscriptions/" + config["subscription_id"] + "/").casefold()):
            return "Published target resource belongs to a different subscription."
    return None


def charge_evidence(page, evidence_budget, source_id):
    evidence_budget["bytes"] += len(json_text(page).encode("utf-8"))
    if evidence_budget["bytes"] > ARTIFACT_BYTES:
        raise EvidenceError("collected_evidence_too_large", "Accepted source evidence alone exceeds the complete JSON artifact bound; no fields were dropped and no report files were written.", source_id)


def read_pages(reader, initial, source_id, kind, config, tracking_id=None, evidence_budget=None):
    evidence_budget = evidence_budget if evidence_budget is not None else {"bytes": 0}
    receipt = {
        "source_id": source_id, "kind": kind,
        "included_event_types": list(EVENT_TYPES) if kind == "events" else None,
        "tracking_id": tracking_id, "subscription_id": config["subscription_id"],
        "api_version": API_VERSION, "status": "not_collected",
        "initial_request_url": initial, "records_received": 0, "records_accepted": 0,
        "records_excluded_by_scope": 0, "excluded_event_types": {},
        "pages": [], "errors": [], "redactions": [],
        "pagination_complete": False, "duplicate_native_ids": 0,
    }
    rows, visited, identities = [], set(), set()
    current = initial
    limit = MAX_EVENT_RECORDS if kind == "events" else MAX_SOURCE_RECORDS
    while len(receipt["pages"]) < MAX_PAGES:
        if current in visited:
            receipt["errors"].append(source_error("pagination_loop", "A continuation repeated an already-read page.", source_id))
            break
        visited.add(current)
        page = {"page": len(receipt["pages"]) + 1, "request_method": "GET", "request_url": current}
        receipt["pages"].append(page)
        try:
            result = reader.get(current, source_id)
        except EvidenceError as exc:
            page.update(exc.receipt or {})
            page["http_status"] = exc.http_status
            receipt["errors"].append(exc.document())
            charge_evidence(page, evidence_budget, source_id)
            break
        page.update({
            "http_status": result["http_status"], "observed_at_utc": result["observed_at_utc"],
            "attempts": result["attempts"],
        })
        if result["http_status"] != 200:
            page["response"] = copy.deepcopy(result["payload"])
            receipt["errors"].append(source_error("native_http_error", "Native source returned HTTP " + str(result["http_status"]) + "; this is not an empty inventory.", source_id, result["http_status"]))
            charge_evidence(page, evidence_budget, source_id)
            break
        payload = result["payload"]
        if not isinstance(payload, dict) or not isinstance(payload.get("value"), list):
            page["response"] = copy.deepcopy(payload)
            receipt["errors"].append(source_error("invalid_list_shape", "Native list response is missing its value array.", source_id, 200))
            charge_evidence(page, evidence_budget, source_id)
            break
        page["response"] = {key: copy.deepcopy(value) for key, value in payload.items() if key != "value"}
        accepted = []
        excluded = 0
        for index, raw in enumerate(payload["value"]):
            receipt["records_received"] += 1
            props = raw.get("properties") if isinstance(raw, dict) else None
            category = props.get("eventType") if isinstance(props, dict) else None
            if kind == "events" and isinstance(category, str) and category and category not in EVENT_TYPES:
                receipt["records_excluded_by_scope"] += 1
                receipt["excluded_event_types"][category] = receipt["excluded_event_types"].get(category, 0) + 1
                excluded += 1
                continue
            reason = record_in_scope(raw, kind, config, tracking_id)
            if reason:
                receipt["redactions"].append({"page": page["page"], "record_index": index, "reason": reason})
                continue
            accepted_index = len(accepted)
            accepted.append(copy.deepcopy(raw))
            native_id = raw["id"].casefold()
            if native_id in identities:
                receipt["duplicate_native_ids"] += 1
            identities.add(native_id)
            rows.append((copy.deepcopy(raw), {
                "source_id": source_id, "page": page["page"], "record_index": accepted_index,
                "original_record_index": index, "observed_at_utc": result["observed_at_utc"],
            }))
        page["response"]["value"] = accepted
        page["records_received"] = len(payload["value"])
        page["records_accepted"] = len(accepted)
        page["records_excluded_by_scope"] = excluded
        receipt["records_accepted"] = len(rows)
        charge_evidence(page, evidence_budget, source_id)
        if len(rows) > limit:
            receipt["errors"].append(source_error("source_record_bound", "The source record bound was exceeded; accepted returned records remain in the export but coverage is partial.", source_id))
            break
        if payload.get("error") is not None:
            receipt["errors"].append(source_error("partial_response", "Native response contains an error alongside its list; returned records are retained.", source_id))
            break
        continuation = payload.get("nextLink")
        if continuation in (None, ""):
            receipt["pagination_complete"] = True
            break
        page["continuation_received"] = True
        try:
            current = next_link(continuation, initial, config)
            page["continuation_query_start_restored"] = current != continuation
        except EvidenceError as exc:
            receipt["errors"].append(exc.document())
            break
    else:
        receipt["errors"].append(source_error("source_page_bound", "The per-list 25-page bound was reached with an outstanding continuation.", source_id))
    if receipt["redactions"]:
        receipt["errors"].append(source_error("source_scope_violation", "Unexpected records were redacted from this nonsensitive subscription-only export; inspect the redaction ledger.", source_id))
    if receipt["duplicate_native_ids"]:
        receipt["errors"].append(source_error("duplicate_native_ids", "Repeated native IDs were retained as separate observations; unique-event completeness is uncertain.", source_id))
    if receipt["errors"]:
        first_status = receipt["errors"][0].get("http_status")
        not_collected = receipt["errors"][0]["code"] == "not_collected_in_replay"
        receipt["status"] = "partial" if rows else "not_collected" if not_collected else "denied" if first_status in (401, 403) else "unavailable"
    else:
        receipt["status"] = "complete" if rows else "successful_empty_in_scope" if receipt["records_excluded_by_scope"] else "successful_empty"
    return rows, receipt


def source_time(value):
    if not isinstance(value, str) or not value:
        return None
    try:
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return result.astimezone(timezone.utc) if result.tzinfo is not None else None


def clock_key(value):
    parsed = source_time(value)
    if parsed is None:
        return None
    match = re.fullmatch(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.(\d{1,9}))?(?:Z|[+-]\d{2}:\d{2})", value)
    if match is None:
        return None
    elapsed = parsed - datetime(1970, 1, 1, tzinfo=timezone.utc)
    fraction = int(((match[1] or "") + "000000000")[:9])
    return (elapsed.days * 86_400 + elapsed.seconds) * 1_000_000_000 + fraction


def source_utc_display(value):
    if clock_key(value) is None:
        return None
    parsed = source_time(value).replace(microsecond=0)
    fraction = re.search(r"\.(\d+)", value)
    return iso(parsed).removesuffix("Z") + ("." + fraction[1] if fraction else "") + "Z"


def scalar(value):
    if isinstance(value, (str, int, float, bool)):
        return str(value)
    return None


def normalize_event(raw, ref, params, reference, key):
    props = raw["properties"]
    uncertain = []
    times = {}
    for field in ("impactStartTime", "impactMitigationTime", "lastUpdateTime"):
        original = props.get(field)
        times[field] = clock_key(original)
        if times[field] is None:
            uncertain.append(field + " missing/invalid; original value retained.")
    status = props.get("status") if props.get("status") in ("Active", "Resolved") else "Unknown"
    if status == "Unknown":
        uncertain.append("Native current status missing/unrecognized.")
    start, end = clock_key(params["window"]["start_utc"]), clock_key(params["window"]["end_utc_exclusive"])
    reference_key = clock_key(iso(reference))
    updated = times["lastUpdateTime"]
    impact_start = times["impactStartTime"]
    mitigation = times["impactMitigationTime"]
    if impact_start is None:
        timing = "unknown"
    elif mitigation is not None and mitigation < impact_start:
        timing = "inconsistent_source_dates"
        uncertain.append("Source mitigation precedes impact start; no ongoing/future interval is established.")
    elif impact_start > reference_key:
        timing = "future_published_start"
    elif mitigation is not None and mitigation <= reference_key:
        timing = "source_mitigation_at_or_before_reference"
    elif mitigation is not None:
        timing = "between_source_start_and_mitigation"
    else:
        timing = "published_start_without_mitigation"
    if status == "Active" and timing == "source_mitigation_at_or_before_reference":
        uncertain.append("Native status is Active but source mitigation is at/before the reference; ongoing impact is not established.")
    services, regions = [], []
    impact = props.get("impact")
    if isinstance(impact, list):
        for item in impact:
            if not isinstance(item, dict):
                continue
            service = scalar(item.get("impactedService"))
            if service and service not in services:
                services.append(service)
            region_items = item.get("impactedRegions")
            if isinstance(region_items, list):
                for region_item in region_items:
                    region = scalar(region_item.get("impactedRegion")) if isinstance(region_item, dict) else None
                    if region and region not in regions:
                        regions.append(region)
    if not services:
        uncertain.append("No structured impacted service supplied.")
    if not regions:
        uncertain.append("No structured impacted region supplied.")
    if updated is not None and updated > reference_key:
        uncertain.append("lastUpdateTime is later than the run reference; the read is not an atomic as-of snapshot.")
    return {
        "event_key": key, "id": raw["id"], "tracking_id": raw["name"],
        "event_type": props["eventType"], "native_status": status,
        "title": scalar(props.get("title")) or "Untitled source event",
        "summary": scalar(props.get("summary")), "description": scalar(props.get("description")),
        "event_level": scalar(props.get("eventLevel")), "event_source": scalar(props.get("eventSource")),
        "impact_start_original": props.get("impactStartTime"), "mitigation_time_original": props.get("impactMitigationTime"),
        "last_update_original": props.get("lastUpdateTime"),
        "impact_start_utc": source_utc_display(props.get("impactStartTime")),
        "mitigation_time_utc": source_utc_display(props.get("impactMitigationTime")),
        "last_update_utc": source_utc_display(props.get("lastUpdateTime")),
        "services": services, "regions": regions, "source_ref": ref,
        "published_timing": timing,
        "temporal": {
            "requested_updates": updated is not None and start <= updated < end,
            "active_now": status == "Active",
            "future_maintenance": props["eventType"] == "PlannedMaintenance" and status != "Resolved" and timing == "future_published_start",
        },
        "newness": "not_established", "support_case_reference": "not_collected",
        "uncertainties": uncertain, "resource_source_id": None, "resource_source_status": "not_collected", "resource_records": None,
    }


def normalize_resource(raw, ref, event, key):
    props = raw.get("properties") if isinstance(raw.get("properties"), dict) else {}
    target = scalar(props.get("targetResourceId"))
    return {
        "resource_key": key, "event_key": event["event_key"], "event_id": event["id"],
        "tracking_id": event["tracking_id"], "id": raw["id"],
        "target_resource_id": target, "target_resource_type": scalar(props.get("targetResourceType")),
        "target_region": scalar(props.get("targetRegion")), "source_ref": ref,
        "association": "published_potential_impact", "workload_outage": "not_measured",
        "uncertainties": [] if target else ["Source supplied no targetResourceId; record retained, not a resolved resource identity."],
    }


def collect(reader, config, params, reference, provenance="LIVE"):
    sources, events, resources = [], [], []
    evidence_budget = {"bytes": 0}
    initial = events_url(config, params["source_query_start_utc"])
    rows, receipt = read_pages(reader, initial, "events:subscription", "events", config, evidence_budget=evidence_budget)
    receipt["query_start_utc"] = params["source_query_start_utc"]
    receipt["time_basis"] = "lastUpdateTime lower bound; no source upper-bound/as-of guarantee"
    sources.append(receipt)
    for raw, ref in rows:
        events.append(normalize_event(raw, ref, params, reference, "event-" + str(len(events) + 1)))
    resource_receipts = {}
    for event in events:
        identity = event["tracking_id"].casefold()
        if identity not in resource_receipts:
            source_id = "resources:" + event["tracking_id"]
            rows, receipt = read_pages(reader, resources_url(config, event["tracking_id"]), source_id, "impactedResources", config, event["tracking_id"], evidence_budget)
            sources.append(receipt)
            resource_receipts[identity] = (rows, receipt)
        rows, receipt = resource_receipts[identity]
        event["resource_source_id"] = receipt["source_id"]
        event["resource_source_status"] = receipt["status"]
        event["resource_records"] = len(rows) if receipt["status"] in COMPLETE_SOURCE_STATUSES else None
        event["resource_records_observed"] = len(rows)
        if event["resource_records"] is None:
            event["uncertainties"].append("Impacted-resource source is incomplete; observed rows are a lower bound, not zero/full scope.")
        for raw, ref in rows:
            resources.append(normalize_resource(raw, ref, event, "resource-" + str(len(resources) + 1)))
    event_sources = [source for source in sources if source["kind"] == "events"]
    all_complete = all(source["status"] in COMPLETE_SOURCE_STATUSES for source in sources)
    observed_times = [page["observed_at_utc"] for source in sources for page in source["pages"] if "observed_at_utc" in page]
    updates = [(clock_key(event["last_update_original"]), event["last_update_original"]) for event in events if clock_key(event["last_update_original"]) is not None]
    return {
        "schema_version": "service-health-events-v1", "provenance": provenance,
        "client_name": config["client_name"], "subscription_id": config["subscription_id"],
        "reference_utc": iso(reference), "requested_window": params["window"],
        "collection_observed_utc": {"first": min(observed_times) if observed_times else None, "last": max(observed_times) if observed_times else None},
        "observed_last_update_extent": {
            "first_original": min(updates, key=lambda item: item[0])[1] if updates else None,
            "last_original": max(updates, key=lambda item: item[0])[1] if updates else None,
            "records_with_valid_time": len(updates), "missing_or_invalid": len(events) - len(updates),
            "meaning": "Extent of accepted observed records, not complete historical coverage.",
        },
        "source_query": {
            "query_start_utc": params["source_query_start_utc"], "basis": "lastUpdateTime",
            "lookback_days": (reference - source_time(params["source_query_start_utc"])).total_seconds() / 86_400,
            "upper_bound": "not_supported", "category_selection": "Fixed client-side ServiceIssue / PlannedMaintenance; no unsupported eventType OData filter.",
            "retention": "Portal history 90 days; backend up to one year, not a completeness guarantee.",
            "active_scope": "Source-observed current Active records within returned retained data, regardless of impact-start month.",
        },
        "coverage": {
            "status": "complete_returned_pages" if all_complete else "partial",
            "historical_completeness": "not_proven", "current_state_as_of_history": "not_reconstructed",
            "newness": "not_established_without_baseline_or_reliable_publication_time",
            "event_source_successful_empty": all(source["status"] in ("successful_empty", "successful_empty_in_scope") for source in event_sources),
            "empty_meaning": "Successful-empty source validation only; no resilience or workload-health claim.",
            "support_cases": "not_collected", "workload_outages": "not_measured",
            "redacted_records": sum(len(source["redactions"]) for source in sources),
            "excluded_category_records": sum(source["records_excluded_by_scope"] for source in event_sources),
        },
        "events": events, "impacted_resources": resources, "sources": sources,
    }


def summary(snapshot):
    events = snapshot["events"]
    return {
        "event_records": len(events), "distinct_event_ids": len({event["id"].casefold() for event in events}),
        "native_event_records_received": sum(source["records_received"] for source in snapshot["sources"] if source["kind"] == "events"),
        "excluded_category_records": snapshot["coverage"]["excluded_category_records"],
        "service_issue_records": sum(event["event_type"] == "ServiceIssue" for event in events),
        "planned_maintenance_records": sum(event["event_type"] == "PlannedMaintenance" for event in events),
        "requested_update_records": sum(event["temporal"]["requested_updates"] for event in events),
        "active_observed_records": sum(event["temporal"]["active_now"] for event in events),
        "future_maintenance_records": sum(event["temporal"]["future_maintenance"] for event in events),
        "impacted_resource_records": len(snapshot["impacted_resources"]),
        "incomplete_sources": sum(source["status"] not in COMPLETE_SOURCE_STATUSES for source in snapshot["sources"]),
    }


def matches(event, params):
    if params["event_type"] != "all" and event["event_type"] != params["event_type"]:
        return False
    if params["state"] != "all" and event["native_status"] != params["state"]:
        return False
    if params["time_scope"] != "all" and not event["temporal"][params["time_scope"]]:
        return False
    haystack = " ".join([event["id"], event["tracking_id"], event["title"], event["summary"] or "", *event["services"], *event["regions"]])
    return params["search"].casefold() in haystack.casefold()


def event_projection(event):
    return {key: event[key] for key in (
        "event_key", "tracking_id", "event_type", "native_status", "title", "last_update_original",
        "impact_start_original", "temporal", "resource_records", "resource_records_observed", "newness", "source_ref",
        "published_timing", "resource_source_id", "resource_source_status",
    )}


def query_snapshot(snapshot, params):
    selected = [event for event in snapshot["events"] if matches(event, params)]
    if params["view"] == "summary":
        rows = [summary(snapshot)]
    elif params["view"] == "events":
        rows = [event_projection(event) for event in selected]
    elif params["view"] == "resources":
        keys = {event["event_key"] for event in selected}
        rows = [row for row in snapshot["impacted_resources"] if row["event_key"] in keys]
    else:
        rows = [{
            "source_id": source["source_id"], "status": source["status"], "records_received": source["records_received"],
            "records_accepted": source["records_accepted"], "pages_attempted": len(source["pages"]),
            "pagination_complete": source["pagination_complete"], "errors": source["errors"],
            "redacted_records": len(source["redactions"]),
            "records_excluded_by_scope": source["records_excluded_by_scope"], "excluded_event_types": source["excluded_event_types"],
        } for source in snapshot["sources"]]
    result = {
        "status": "partial" if snapshot["coverage"]["status"] == "partial" else "ok",
        "operation": "query", "view": params["view"], "provenance": snapshot["provenance"],
        "reference_utc": snapshot["reference_utc"], "requested_window": snapshot["requested_window"],
        "source_query_start_utc": snapshot["source_query"]["query_start_utc"],
        "collection_observed_utc": snapshot["collection_observed_utc"],
        "historical_completeness": "not_proven", "fresh_collection": True,
        "total_matched": len(rows), "requested_limit": params["limit"], "offset": params["offset"],
        "returned": 0, "has_more": False, "next_offset": None, "transport_capped": False, "rows": [],
    }
    desired = rows[params["offset"]:params["offset"] + params["limit"]]
    for row in desired:
        proposed = copy.deepcopy(result)
        proposed["rows"].append(row)
        proposed["returned"] += 1
        consumed = params["offset"] + proposed["returned"]
        proposed["has_more"] = consumed < len(rows)
        proposed["next_offset"] = consumed if proposed["has_more"] else None
        proposed["transport_capped"] = proposed["returned"] < len(desired)
        if response_bytes(proposed) > TRANSPORT_BYTES:
            if not result["rows"]:
                raise EvidenceError("query_row_too_large", "One complete projected row exceeds the chat budget. Request a report and inspect its complete JSON; no zero-row cursor is returned.", "transport")
            result["transport_capped"] = True
            break
        result = proposed
    return budget_response(result)


def source_record(snapshot, ref):
    source = next(item for item in snapshot["sources"] if item["source_id"] == ref["source_id"])
    page = source["pages"][ref["page"] - 1]
    return page["response"]["value"][ref["record_index"]]


def complete_event(snapshot, event):
    return {**event, "source_record": source_record(snapshot, event["source_ref"])}


def complete_resource(snapshot, resource):
    return {**resource, "source_record": source_record(snapshot, resource["source_ref"])}


EVENT_CSV_FIELDS = (
    "provenance", "subscription_id", "api_version", "reference_utc", "event_feed_query_start_utc", "requested_start_utc", "requested_end_utc_exclusive",
    "event_key", "id", "tracking_id", "event_type", "native_status", "published_timing", "title", "event_level",
    "services", "regions", "impact_start_original", "mitigation_time_original", "last_update_original",
    "requested_updates", "active_observed", "future_maintenance", "newness", "resource_records",
    "resource_records_observed", "resource_source_id", "resource_source_status", "source_id", "observed_at_utc", "details_json",
)
RESOURCE_CSV_FIELDS = (
    "provenance", "subscription_id", "api_version", "reference_utc", "event_feed_query_start_utc", "requested_start_utc", "requested_end_utc_exclusive",
    "resource_key", "id", "event_key", "tracking_id", "target_resource_id", "target_resource_type", "target_region",
    "association", "workload_outage", "source_id", "observed_at_utc", "details_json",
)


def csv_cell(value):
    if value is None:
        return ""
    text = json_text(value) if isinstance(value, (dict, list, bool)) else str(value)
    if text.startswith(("\t", "\r", "\n")) or text.lstrip().startswith(("=", "+", "-", "@")):
        return "'" + text
    return text


def csv_document(rows, fields):
    stream = io.StringIO(newline="")
    writer = csv.DictWriter(stream, fieldnames=fields, lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({field: csv_cell(row.get(field)) for field in fields})
    return stream.getvalue()


def csv_rows(snapshot):
    context = {
        "provenance": snapshot["provenance"], "subscription_id": snapshot["subscription_id"], "api_version": API_VERSION,
        "reference_utc": snapshot["reference_utc"], "event_feed_query_start_utc": snapshot["source_query"]["query_start_utc"],
        "requested_start_utc": snapshot["requested_window"]["start_utc"],
        "requested_end_utc_exclusive": snapshot["requested_window"]["end_utc_exclusive"],
    }
    events = [{
        **context, **event, "services": event["services"], "regions": event["regions"],
        "requested_updates": event["temporal"]["requested_updates"], "active_observed": event["temporal"]["active_now"],
        "future_maintenance": event["temporal"]["future_maintenance"],
        "source_id": event["source_ref"]["source_id"], "observed_at_utc": event["source_ref"]["observed_at_utc"],
        "details_json": complete_event(snapshot, event),
    } for event in snapshot["events"]]
    resources = [{
        **context, **resource, "source_id": resource["source_ref"]["source_id"],
        "observed_at_utc": resource["source_ref"]["observed_at_utc"], "details_json": complete_resource(snapshot, resource),
    } for resource in snapshot["impacted_resources"]]
    return events, resources


def safe_script_json(value):
    return json_text(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026").replace("\u2028", "\\u2028").replace("\u2029", "\\u2029")


def json_byte_ranges(snapshot, document, requested_paths):
    paths = set(requested_paths)
    prefixes = {path[:length] for path in paths for length in range(len(path) + 1)}
    chunks, ranges, position = [], {}, 0

    def emit(value):
        nonlocal position
        chunks.append(value)
        position += len(value)

    def walk(value, path=()):
        if len(path) > 100:
            raise EvidenceError("json_reference_depth", "Source JSON references exceed the bounded nesting depth.", "artifact_encoding")
        start = position
        if path not in prefixes:
            emit(json_text(value).encode("utf-8"))
        elif isinstance(value, dict):
            emit(b"{")
            for index, (key, child) in enumerate(value.items()):
                if index:
                    emit(b",")
                emit(json_text(key).encode("utf-8") + b":")
                walk(child, (*path, key))
            emit(b"}")
        elif isinstance(value, list):
            emit(b"[")
            for index, child in enumerate(value):
                if index:
                    emit(b",")
                walk(child, (*path, index))
            emit(b"]")
        else:
            emit(json_text(value).encode("utf-8"))
        if path in paths:
            ranges[path] = [start, position]

    walk(snapshot)
    if paths != ranges.keys() or b"".join(chunks) + b"\n" != document:
        raise EvidenceError("json_reference_mismatch", "Render references do not match the exact complete JSON bytes; no alternate snapshot was accepted.", "artifact_encoding")
    return ranges


def render_html(snapshot, document, branding):
    if EVENT_CSV_FIELDS[-1] != "details_json" or RESOURCE_CSV_FIELDS[-1] != "details_json":
        raise EvidenceError("invalid_csv_render_contract", "Complete CSV details must remain the final column in the render contract.", "artifact_encoding")
    event_rows, resource_rows = csv_rows(snapshot)
    source_indices = {source["source_id"]: index for index, source in enumerate(snapshot["sources"])}
    if len(source_indices) != len(snapshot["sources"]):
        raise EvidenceError("ambiguous_source_reference", "Source IDs must be unique for exact report references.", "artifact_encoding")

    def raw_path(row):
        ref = row["source_ref"]
        return ("sources", source_indices[ref["source_id"]], "pages", ref["page"] - 1, "response", "value", ref["record_index"])

    requested_paths = [("sources", index) for index in range(len(snapshot["sources"]))]
    for collection in ("events", "impacted_resources"):
        for index, row in enumerate(snapshot[collection]):
            requested_paths.extend(((collection, index), raw_path(row)))
    ranges = json_byte_ranges(snapshot, document, requested_paths)
    model = {
        "context": {key: snapshot[key] for key in ("schema_version", "provenance", "client_name", "subscription_id", "reference_utc", "requested_window", "collection_observed_utc", "observed_last_update_extent", "source_query", "coverage")},
        "summary": summary(snapshot), "events": [], "resources": [], "sources": [],
        "event_csv_fields": EVENT_CSV_FIELDS, "resource_csv_fields": RESOURCE_CSV_FIELDS,
        "source_json_bytes": len(document),
    }
    # Store source JSON once; UTF-8 byte references preserve every numeric lexeme.
    for index, (event, row) in enumerate(zip(snapshot["events"], event_rows)):
        model["events"].append({
            **event, "record_range": ranges[("events", index)], "source_record_range": ranges[raw_path(event)],
            "csv_cells": [csv_cell(row.get(field)) for field in EVENT_CSV_FIELDS if field != "details_json"],
        })
    for index, (resource, row) in enumerate(zip(snapshot["impacted_resources"], resource_rows)):
        model["resources"].append({
            **resource, "record_range": ranges[("impacted_resources", index)], "source_record_range": ranges[raw_path(resource)],
            "csv_cells": [csv_cell(row.get(field)) for field in RESOURCE_CSV_FIELDS if field != "details_json"],
        })
    for index, source in enumerate(snapshot["sources"]):
        receipt = {
            key: value for key, value in source.items() if key != "pages"
        } | {
            "pages": [{
                **{key: value for key, value in page.items() if key != "response"},
                "response_metadata": {key: value for key, value in page["response"].items() if key != "value"}
                if isinstance(page.get("response"), dict) else page.get("response"),
            } for page in source["pages"]],
        }
        model["sources"].append({
            **receipt, "receipt_json": json_text(receipt),
            "detail_range": ranges[("sources", index)],
        })
    return (
        HTML_TEMPLATE.replace("__CLIENT_NAME__", html.escape(snapshot["client_name"], quote=True))
        .replace("__COMPANY_LOGO__", branding)
        .replace("__FULL_JSON_BASE64__", base64.b64encode(document).decode("ascii"))
        .replace("__UI_MODEL_JSON__", safe_script_json(model))
    )


def artifact_directory():
    try:
        cwd = Path.cwd()
        root = cwd.resolve(strict=True)
        linked = any(part.is_symlink() or getattr(part, "is_junction", lambda: False)() for part in (cwd, *cwd.parents))
    except (OSError, RuntimeError) as exc:
        raise EvidenceError("unsafe_artifact_root", "Runtime cwd must resolve to an existing directory.", "artifact_storage") from exc
    if root == Path(root.anchor) or not root.is_dir() or linked:
        raise EvidenceError("unsafe_artifact_root", "Root directories and symlink/junction cwd ancestors are forbidden.", "artifact_storage")
    if OUTPUT_DIRECTORY != "service-health-reports":
        raise EvidenceError("unsafe_artifact_directory", "Only the fixed service-health-reports child is allowed.", "artifact_storage")
    directory = root / OUTPUT_DIRECTORY
    if directory.is_symlink() or getattr(directory, "is_junction", lambda: False)() or directory.resolve() != directory:
        raise EvidenceError("unsafe_artifact_directory", "Output folder is a link/junction or escapes the actual cwd.", "artifact_storage")
    return root, directory


SUFFIXES = {
    "report_path": ".html", "snapshot_path": "-snapshot.json",
    "events_csv_path": "-events.csv", "resources_csv_path": "-impacted-resources.csv",
}


def sharing_fields(root, paths):
    result = {"sharing_mode": "local_files_only", "http_verified": False}
    match = re.fullmatch(r"/(?:root/sreagent|usr)/terminalRoot/tmp/ThreadFiles/([0-9a-fA-F-]{36})", root.as_posix())
    if match is None:
        return result
    try:
        if str(UUID(match[1])) != match[1].lower():
            return result
    except ValueError:
        return result
    if set(paths) != set(SUFFIXES):
        raise EvidenceError("unsafe_sharing_path", "Exactly the four generated artifacts are required.", "artifact_storage")
    stem = paths["report_path"].name.removesuffix(".html")
    if re.fullmatch(r"(?:service-health|simulated-service-health)-[0-9]{8}T[0-9]{6}Z-[0-9a-f]{12}", stem) is None:
        raise EvidenceError("unsafe_sharing_path", "Native aliases require this tool's generated filenames.", "artifact_storage")
    for key, suffix in SUFFIXES.items():
        path = paths[key]
        if path.parent != root / OUTPUT_DIRECTORY or path.name != stem + suffix:
            raise EvidenceError("unsafe_sharing_path", "Native aliases must point to one guarded run under the actual runtime cwd.", "artifact_storage")
        result[key.removesuffix("_path") + "_url"] = "/api/files/tmp/ThreadFiles/" + match[1] + "/" + OUTPUT_DIRECTORY + "/" + quote(path.name, safe="")
    result["sharing_mode"] = "native_ui"
    return result


def report_envelope(snapshot, root, paths):
    return budget_response({
        "status": "partial" if snapshot["coverage"]["status"] == "partial" else "ok",
        "operation": "report", "artifact_status": "written", "provenance": snapshot["provenance"],
        "reference_utc": snapshot["reference_utc"], "requested_window": snapshot["requested_window"],
        "source_query_start_utc": snapshot["source_query"]["query_start_utc"],
        "historical_completeness": "not_proven", "newness": "not_established",
        "empty_source_validation_only": snapshot["coverage"]["event_source_successful_empty"],
        "summary": summary(snapshot), **{key: str(path) for key, path in paths.items()},
        **sharing_fields(root, paths),
    })


def prepare_artifacts(snapshot, branding):
    text = json_text(snapshot) + "\n"
    if json.loads(text) != snapshot:
        raise EvidenceError("json_round_trip_failed", "Complete source-qualified JSON failed its round-trip check.", "artifact_encoding")
    document = text.encode("utf-8")
    event_rows, resource_rows = csv_rows(snapshot)
    files = {
        "snapshot_path": document,
        "report_path": render_html(snapshot, document, branding).encode("utf-8"),
        "events_csv_path": csv_document(event_rows, EVENT_CSV_FIELDS).encode("utf-8-sig"),
        "resources_csv_path": csv_document(resource_rows, RESOURCE_CSV_FIELDS).encode("utf-8-sig"),
    }
    if any(len(data) > ARTIFACT_BYTES for data in files.values()):
        raise EvidenceError("artifact_size_exceeded", "A complete plain artifact exceeds 4800000 bytes. No file was written, no records/window were dropped and no ZIP/Blob substitute was created.", "artifact_storage")
    return files


def write_report(snapshot, branding):
    root, directory = artifact_directory()
    prefix = "simulated-service-health" if snapshot["provenance"] == "SIMULATED" else "service-health"
    stem = prefix + "-" + snapshot["reference_utc"].replace("-", "").replace(":", "") + "-" + uuid4().hex[:12]
    paths = {key: directory / (stem + suffix) for key, suffix in SUFFIXES.items()}
    result = report_envelope(snapshot, root, paths)
    files = prepare_artifacts(snapshot, branding)
    temporary, written = [], []
    try:
        directory.mkdir(exist_ok=True)
        if artifact_directory()[1] != directory or not directory.is_dir() or directory.resolve(strict=True) != directory:
            raise EvidenceError("unsafe_artifact_directory", "Output folder changed during creation.", "artifact_storage")
        for key, data in files.items():
            if paths[key].exists() or paths[key].is_symlink():
                raise EvidenceError("artifact_collision", "A generated path already exists; no overwrite is allowed.", "artifact_storage")
            fd, filename = tempfile.mkstemp(prefix=stem + "-", suffix=".tmp", dir=directory)
            pending = Path(filename)
            temporary.append(pending)
            with os.fdopen(fd, "wb") as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(pending, paths[key])
            temporary.remove(pending)
            written.append(paths[key])
        if any(path.read_bytes() != files[key] for key, path in paths.items()):
            raise EvidenceError("artifact_readback_failed", "Written artifact bytes differ from the complete prepared documents.", "artifact_storage")
    except (OSError, EvidenceError) as exc:
        failed = []
        for path in temporary + written:
            try:
                path.unlink(missing_ok=True)
            except OSError:
                failed.append(path.name)
        if failed:
            raise EvidenceError("artifact_cleanup_failed", "Artifact write failed and generated-file cleanup also failed; inspect: " + ", ".join(failed), "artifact_storage") from exc
        if isinstance(exc, EvidenceError):
            raise
        raise EvidenceError("artifact_write_failed", "Atomic artifact write/readback failed; this run's partial files were removed.", "artifact_storage") from exc
    return result


def main(operation: str = "report", period: str = "auto", start_utc: str = "", end_utc: str = "",
         view: str = "summary", event_type: str = "all", state: str = "all", time_scope: str = "all",
         search: str = "", limit: int = 10, offset: int = 0):
    """Runtime entry point. No live fixture, environment override or arbitrary path input."""
    try:
        reference = utc_now().replace(microsecond=0)
        params = parameters(operation, period, start_utc, end_utc, view, event_type, state, time_scope, search, limit, offset, reference)
        config = configuration()
        branding = logo_markup()
        if operation == "report":
            artifact_directory()
        reader = NativeReader(config)
        try:
            snapshot = collect(reader, config, params, reference)
        finally:
            reader.close()
        if operation == "report":
            return write_report(snapshot, branding)
        return query_snapshot(snapshot, params)
    except EvidenceError as exc:
        return budget_response({"status": "error", "operation": operation if operation in ("report", "query") else "invalid", "error": exc.document()})
