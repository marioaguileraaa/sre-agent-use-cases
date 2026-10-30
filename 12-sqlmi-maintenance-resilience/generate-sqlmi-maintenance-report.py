# generate-sqlmi-maintenance-report
# Azure SQL Managed Instance: resilience to maintenance windows.
# Answers with data "why do users see errors when SQL MI maintenance happens?":
#   1) SQL MI inventory: maintenance window, tier, connection type (Proxy/Redirect), failover groups.
#   2) Real reconfigurations (Resource Health + Activity Log) and upcoming maintenance (Service Health).
#   3) Correlation with Application Insights: which applications surface errors to users (no retries)
#      and which absorb them (with retries).
#   4) Recommended window per instance from real load, plus an action plan with commands.
# Modes: data_source="demo" (deterministic simulated data, no configuration needed) | "live" | "auto".
# The report itself is written in Spanish (same convention as case 11).
# Read-only · Version 1.0 · October 2026


def main(operation: str = "report", period: str = "last_30d", data_source: str = "auto") -> dict:
    """Read-only SQL Managed Instance maintenance resilience report (HTML + JSON + 2 CSV)."""
    import base64
    import csv
    import html
    import io
    import json
    import os
    import random
    import re
    import time
    from collections import defaultdict
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    from urllib.parse import quote

    # ---- CONFIGURE (see README, step 4) ---------------------------------------------------------------
    # Client ID of the SRE Agent user-assigned managed identity. Only needed in live mode.
    MANAGED_IDENTITY_CLIENT_ID = "<SRE_AGENT_UAMI_CLIENT_ID>"
    # Subscriptions to analyze, comma separated. Empty or placeholder = every subscription the identity can read.
    SUBSCRIPTION_IDS = "<SUBSCRIPTION_IDS_COMMA_SEPARATED>"
    # Log Analytics Workspace IDs (the "Workspace ID" GUID) where the Application Insights of the apps
    # that use SQL MI write. Empty or placeholder = no per-application correlation.
    LOG_ANALYTICS_WORKSPACE_IDS = "<LOG_ANALYTICS_WORKSPACE_IDS_COMMA_SEPARATED>"
    # Business time zone used to read peak hours and windows (Azure windows use the region's local time).
    LOCAL_TIMEZONE = "Europe/Madrid"
    # ----------------------------------------------------------------------------------------------------

    def _configured(v):
        return bool((v or "").strip()) and not v.strip().startswith("<")

    def _csv_list(v):
        return [x.strip() for x in (v or "").split(",") if x.strip()] if _configured(v) else []

    ARM = "https://management.azure.com"
    BUDGET_SECONDS = 105
    operation = (operation or "report").strip().lower()
    if operation not in ("report", "summary", "upcoming"):
        operation = "report"
    period_map = {"last_30d": ("Últimos 30 días", 30), "last_14d": ("Últimos 14 días", 14), "last_7d": ("Últimos 7 días", 7)}
    period_key = (period or "last_30d").strip().lower()
    if period_key not in period_map:
        period_key = "last_30d"
    period_label, period_days = period_map[period_key]
    mode_req = (data_source or "auto").strip().lower()
    if mode_req not in ("auto", "live", "demo"):
        mode_req = "auto"
    now_utc = datetime.now(timezone.utc).replace(microsecond=0)
    stamp = now_utc.strftime("%Y%m%dT%H%M%SZ")
    start_utc = now_utc - timedelta(days=period_days)
    cwd = Path.cwd()
    m_tid = re.fullmatch(r"/(?:root/sreagent|usr)/terminalRoot/tmp/ThreadFiles/([0-9a-fA-F-]{36})", cwd.as_posix())

    def file_url(name):
        return f"/api/files/tmp/ThreadFiles/{m_tid.group(1)}/{quote(name, safe='')}" if m_tid else str(cwd / name)

    # ---- Hora local (zoneinfo si existe; si no, regla CET/CEST de la UE) -------------------------------
    try:
        from zoneinfo import ZoneInfo
        _TZ = ZoneInfo(LOCAL_TIMEZONE)
        _TZ.utcoffset(datetime(2026, 1, 1))

        def to_local(dt):
            return dt.astimezone(_TZ)

        def from_local(naive):
            return naive.replace(tzinfo=_TZ).astimezone(timezone.utc)
    except Exception:
        def _eu_off(dt_utc):
            y = dt_utc.year

            def last_sun(m):
                d = datetime(y, m, 31, 1, tzinfo=timezone.utc)
                return d - timedelta(days=(d.weekday() + 1) % 7)
            return 2 if last_sun(3) <= dt_utc < last_sun(10) else 1

        def to_local(dt):
            dt = dt.astimezone(timezone.utc)
            return (dt + timedelta(hours=_eu_off(dt))).replace(tzinfo=None)

        def from_local(naive):
            guess = naive.replace(tzinfo=timezone.utc)
            return guess - timedelta(hours=_eu_off(guess))

    def parse_dt(v):
        if v in (None, ""):
            return None
        if isinstance(v, (int, float)):
            return datetime.fromtimestamp(v / (1000 if v > 1e11 else 1), tz=timezone.utc)
        s = str(v).strip()
        if s.isdigit():
            return parse_dt(int(s))
        s = s.replace("Z", "+00:00")
        m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(.*)$", s)
        if m:
            s = m.group(1) + (m.group(2) or "")[:7] + m.group(3)
        try:
            d = datetime.fromisoformat(s)
        except ValueError:
            return None
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)

    DIAS = ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"]

    def fmt_local(dt, with_day=True):
        if not dt:
            return "—"
        lo = to_local(dt)
        return (DIAS[lo.weekday()] + " " if with_day else "") + lo.strftime("%d/%m %H:%M")

    # ---- Ventanas de mantenimiento de SQL MI (Microsoft Learn: maintenance-window) ---------------------
    WINDOWS = {
        "Default": "Por defecto · 17:00–08:00 todos los días",
        "Weekday": "Entre semana · Lun–Jue 22:00–06:00",
        "Weekend": "Fin de semana · Vie–Dom 22:00–06:00",
        "Custom": "Configuración no estándar",
    }
    WINDOW_SUFFIX = {"Weekday": "MI_1", "Weekend": "MI_2"}

    def window_of(cfg_id):
        c = (cfg_id or "").strip().lower()
        if not c or c.endswith("sql_default"):
            return "Default"
        if c.endswith("_mi_1"):
            return "Weekday"
        if c.endswith("_mi_2"):
            return "Weekend"
        return "Custom"

    def in_window(win, lo):
        wd, h = lo.weekday(), lo.hour
        if win in ("Default", "Custom"):
            return h >= 17 or h < 8
        if win == "Weekday":
            return (h >= 22 and wd in (0, 1, 2, 3)) or (h < 6 and wd in (1, 2, 3, 4))
        if win == "Weekend":
            return (h >= 22 and wd in (4, 5, 6)) or (h < 6 and wd in (5, 6, 0))
        return False

    WINDOW_CELLS = {w: {(d, h) for d in range(7) for h in range(24)
                        if in_window(w, datetime(2026, 1, 5 + d, h, 30))} for w in ("Default", "Weekday", "Weekend")}

    REGION_PASCAL = {
        "westeurope": "WestEurope", "northeurope": "NorthEurope", "spaincentral": "SpainCentral",
        "francecentral": "FranceCentral", "germanywestcentral": "GermanyWestCentral", "swedencentral": "SwedenCentral",
        "italynorth": "ItalyNorth", "uksouth": "UKSouth", "ukwest": "UKWest", "switzerlandnorth": "SwitzerlandNorth",
        "polandcentral": "PolandCentral", "eastus": "EastUS", "eastus2": "EastUS2", "westus": "WestUS",
        "centralus": "CentralUS", "northcentralus": "NorthCentralUS", "southcentralus": "SouthCentralUS",
    }
    REGION_LABEL = {
        "westeurope": "West Europe", "northeurope": "North Europe", "spaincentral": "Spain Central",
        "francecentral": "France Central", "germanywestcentral": "Germany West Central", "swedencentral": "Sweden Central",
        "italynorth": "Italy North", "uksouth": "UK South", "ukwest": "UK West",
    }
    REGION_PAIRS = {
        "westeurope": "northeurope", "northeurope": "westeurope", "francecentral": "francesouth",
        "francesouth": "francecentral", "germanywestcentral": "germanynorth", "germanynorth": "germanywestcentral",
        "uksouth": "ukwest", "ukwest": "uksouth", "swedencentral": "swedensouth", "swedensouth": "swedencentral",
        "switzerlandnorth": "switzerlandwest", "switzerlandwest": "switzerlandnorth", "eastus": "westus",
        "westus": "eastus", "eastus2": "centralus", "centralus": "eastus2",
    }

    def region_label(loc):
        return REGION_LABEL.get((loc or "").lower(), loc or "—")

    def config_id(sub, loc, win):
        if win == "Default":
            return f"/subscriptions/{sub}/providers/Microsoft.Maintenance/publicMaintenanceConfigurations/SQL_Default"
        rp = REGION_PASCAL.get((loc or "").lower(), (loc or "region")[:1].upper() + (loc or "region")[1:])
        return (f"/subscriptions/{sub}/providers/Microsoft.Maintenance/publicMaintenanceConfigurations/"
                f"SQL_{rp}_{WINDOW_SUFFIX[win]}")

    def env_of(name, tags):
        for k, v in (tags or {}).items():
            if k.lower() in ("env", "entorno", "environment", "ambiente") and v:
                v = str(v).lower()
                return "prd" if v.startswith(("prd", "prod", "pro")) else "no-prd"
        n = (name or "").lower()
        if re.search(r"[-_](prd|prod|pro)([-_]|$)", n):
            return "prd"
        if re.search(r"[-_](pre|dev|test|tst|uat|qa|int|des)([-_]|$)", n):
            return "no-prd"
        return "prd"

    def batch_cells(tags):
        for k, v in (tags or {}).items():
            if k.lower() in ("batch-hours", "batch_hours", "etl-hours", "ventana-batch"):
                m = re.match(r"^\s*(\d{1,2})\s*-\s*(\d{1,2})\s*$", str(v))
                if m:
                    a, b = int(m.group(1)) % 24, int(m.group(2)) % 24
                    hours = [(a + i) % 24 for i in range(((b - a) % 24) or 24)]
                    return {(d, h) for d in range(7) for h in hours}, f"{a:02d}:00–{b:02d}:00"
        return set(), None

    TRANSIENT = {"233", "997", "10060", "10053", "10054", "4060", "4221", "1204", "1205", "1222", "10928", "10929",
                 "40501", "49918", "49919", "49920", "40143", "40197", "40540", "40613", "-2"}

    # ==== Colectores LIVE (solo lectura) ================================================================
    t0 = time.monotonic()
    sources = []

    def src(name, status, detail=""):
        sources.append({"source": name, "status": status, "detail": str(detail)[:300]})

    def left():
        return BUDGET_SECONDS - (time.monotonic() - t0)

    def collect_live():
        import requests
        from azure.identity import ManagedIdentityCredential
        cred = ManagedIdentityCredential(client_id=MANAGED_IDENTITY_CLIENT_ID)
        tokens = {}

        def tok(scope):
            if scope not in tokens or tokens[scope][1] - time.time() < 120:
                t = cred.get_token(scope)
                tokens[scope] = (t.token, t.expires_on)
            return tokens[scope][0]

        def req(method, url, body=None, scope=ARM + "/.default", tries=3):
            for i in range(tries):
                if left() < 4:
                    raise TimeoutError("presupuesto de tiempo agotado")
                r = requests.request(method, url, json=body, timeout=min(30, max(5, left() - 2)),
                                     headers={"Authorization": "Bearer " + tok(scope), "Content-Type": "application/json"})
                if r.status_code in (429, 500, 502, 503, 504) and i < tries - 1:
                    time.sleep(min(int(r.headers.get("Retry-After", "3") or 3), 10))
                    continue
                if r.status_code >= 400:
                    raise RuntimeError(f"HTTP {r.status_code}: {r.text[:200]}")
                return r.json() if r.text else {}
            return {}

        subs = _csv_list(SUBSCRIPTION_IDS)

        def arg(query):
            rows, skip = [], None
            while True:
                body = {"query": query, "options": {"resultFormat": "objectArray", "$top": 1000}}
                if subs:
                    body["subscriptions"] = subs
                if skip:
                    body["options"]["$skipToken"] = skip
                j = req("POST", ARM + "/providers/Microsoft.ResourceGraph/resources?api-version=2022-10-01", body)
                rows += j.get("data") or []
                skip = j.get("$skipToken")
                if not skip or len(rows) > 20000:
                    return rows

        d = {"mode": "live", "instances": [], "events": [], "upcoming": [], "alerts": [],
             "dep_hourly": [], "dep_fail": [], "req_fail": [], "cpu": {}, "telemetry": False}

        # 1) Inventario SQL MI
        try:
            rows = arg("resources | where type =~ 'microsoft.sql/managedinstances' | project id, name, location, "
                       "resourceGroup, subscriptionId, tags, skuName=tostring(sku.name), tier=tostring(sku.tier), "
                       "vCores=toint(properties.vCores), cfg=tostring(properties.maintenanceConfigurationId), "
                       "proxy=tostring(properties.proxyOverride), zr=tobool(properties.zoneRedundant), "
                       "pool=tostring(properties.instancePoolId), fqdn=tostring(properties.fullyQualifiedDomainName), "
                       "state=tostring(properties.state)")
            for r in rows:
                tier = (r.get("tier") or r.get("skuName") or "")
                tier = "BusinessCritical" if "business" in tier.lower() or (r.get("skuName") or "").upper().startswith("BC") else "GeneralPurpose"
                px = (r.get("proxy") or "").strip()
                d["instances"].append({
                    "id": r["id"], "name": r["name"], "sub": r.get("subscriptionId"), "rg": r.get("resourceGroup"),
                    "location": (r.get("location") or "").lower(), "tier": tier, "vcores": r.get("vCores"),
                    "cfg_id": r.get("cfg") or "", "proxy": "Redirect" if px.lower() in ("redirect", "default") else ("Proxy" if px.lower() == "proxy" else "—"),
                    "zone_redundant": bool(r.get("zr")), "pool": bool(r.get("pool")), "fqdn": r.get("fqdn") or "",
                    "tags": r.get("tags") or {}, "fog": None, "fog_role": None, "fog_partner": None})
            src("Resource Graph · inventario SQL MI", "ok", f"{len(rows)} instancias")
        except Exception as e:
            src("Resource Graph · inventario SQL MI", "error", e)
        by_id = {i["id"].lower(): i for i in d["instances"]}

        # 2) Failover groups (REST por grupo de recursos y región)
        fog_err = 0
        for key in sorted({(i["sub"], i["rg"], i["location"]) for i in d["instances"]}):
            try:
                j = req("GET", f"{ARM}/subscriptions/{key[0]}/resourceGroups/{key[1]}/providers/Microsoft.Sql/locations/"
                               f"{key[2]}/instanceFailoverGroups?api-version=2023-08-01")
                for fg in j.get("value") or []:
                    p = fg.get("properties") or {}
                    for pair in p.get("managedInstancePairs") or []:
                        a = by_id.get((pair.get("primaryManagedInstanceId") or "").lower())
                        b = by_id.get((pair.get("partnerManagedInstanceId") or "").lower())
                        for x, role, other in ((a, "Primary", b), (b, "Secondary", a)):
                            if x:
                                x["fog"], x["fog_role"] = fg.get("name"), role
                                x["fog_partner"] = other["name"] if other else None
            except Exception:
                fog_err += 1
        src("ARM · failover groups", "ok" if not fog_err else "partial", f"{fog_err} errores" if fog_err else "")

        # 3) Próximos mantenimientos (Service Health) y updates por recurso (Maintenance)
        try:
            rows = arg("servicehealthresources | where type =~ 'Microsoft.ResourceHealth/events' | extend p=properties "
                       "| where tostring(p.EventType) == 'PlannedMaintenance' | mv-expand imp=p.Impact "
                       "| where tostring(imp.ImpactedService) =~ 'SQL Managed Instance' | project trackingId=name, "
                       "title=tostring(p.Title), status=tostring(p.Status), start=tostring(p.ImpactStartTime), "
                       "end=tostring(p.ImpactMitigationTime), regions=imp.ImpactedRegions")
            seen = set()
            for r in rows:
                st, en = parse_dt(r.get("start")), parse_dt(r.get("end"))
                if not st or (en or st) < now_utc - timedelta(hours=12) or r.get("trackingId") in seen:
                    continue
                seen.add(r.get("trackingId"))
                regs = [re.sub(r"\s+", "", (x.get("ImpactedRegion") or "")).lower() for x in (r.get("regions") or []) if isinstance(x, dict)]
                d["upcoming"].append({"tracking_id": r.get("trackingId"), "title": r.get("title") or "Mantenimiento planificado",
                                      "start": st.isoformat(), "end": (en or st + timedelta(hours=8)).isoformat(),
                                      "regions": regs, "impacted": [i["name"] for i in d["instances"] if i["location"] in regs],
                                      "source": "Service Health"})
            src("Service Health · mantenimiento planificado", "ok", f"{len(d['upcoming'])} eventos")
        except Exception as e:
            src("Service Health · mantenimiento planificado", "error", e)
        try:
            rows = arg("maintenanceresources | where type =~ 'microsoft.maintenance/updates' "
                       "| where tolower(id) contains '/microsoft.sql/managedinstances/' or tolower(tostring(properties.resourceId)) "
                       "contains '/microsoft.sql/managedinstances/' | project id, rid=tostring(properties.resourceId), "
                       "status=tostring(properties.status), start=tostring(properties.startTimeUtc), "
                       "end=tostring(properties.endTimeUtc), impact=tostring(properties.impactType)")
            n = 0
            for r in rows:
                rid = (r.get("rid") or r.get("id") or "").lower().split("/providers/microsoft.maintenance")[0]
                mi = by_id.get(rid)
                st = parse_dt(r.get("start"))
                if not mi or (r.get("status") or "").lower() not in ("pending", "inprogress", "in progress", "scheduled") or not st:
                    continue
                en = parse_dt(r.get("end")) or st + timedelta(hours=8)
                hit = next((u for u in d["upcoming"] if abs((parse_dt(u["start"]) - st).total_seconds()) < 86400), None)
                if hit:
                    if mi["name"] not in hit["impacted"]:
                        hit["impacted"].append(mi["name"])
                else:
                    d["upcoming"].append({"tracking_id": "—", "title": f"Update {r.get('impact') or ''}".strip(),
                                          "start": st.isoformat(), "end": en.isoformat(), "regions": [mi["location"]],
                                          "impacted": [mi["name"]], "source": "Maintenance"})
                n += 1
            src("Resource Graph · maintenanceresources", "ok", f"{n} updates pendientes")
        except Exception as e:
            src("Resource Graph · maintenanceresources", "partial", e)

        # 4) Alertas de Service Health
        try:
            rows = arg("resources | where type =~ 'microsoft.insights/activitylogalerts' | project name, "
                       "enabled=tobool(properties.enabled), cond=properties.condition")

            def flat(c, out):
                if isinstance(c, dict):
                    if c.get("field"):
                        vals = c.get("containsAny") or ([c.get("equals")] if c.get("equals") is not None else [])
                        out.append((c["field"].lower(), [str(v).lower() for v in vals]))
                    for k in ("allOf", "anyOf"):
                        for x in c.get(k) or []:
                            flat(x, out)
                elif isinstance(c, list):
                    for x in c:
                        flat(x, out)
                return out
            for r in rows:
                f = flat(r.get("cond") or {}, [])
                if not any(k == "category" and "servicehealth" in v for k, v in f):
                    continue
                inc = [v for k, v in f if k.endswith("incidenttype")]
                svc = [v for k, v in f if "impactedservices" in k]
                d["alerts"].append({"name": r.get("name"), "enabled": r.get("enabled") is not False,
                                    "covers_maintenance": not inc or any("maintenance" in x for v in inc for x in v),
                                    "covers_sqlmi": not svc or any("managed instance" in x for v in svc for x in v),
                                    "types": sorted({x for v in inc for x in v}) or ["todas"]})
            src("Resource Graph · alertas Service Health", "ok", f"{len(d['alerts'])} alertas")
        except Exception as e:
            src("Resource Graph · alertas Service Health", "error", e)

        # 5) Resource Health (reconfiguraciones) + CPU por instancia, en paralelo
        def rh(mi):
            out = []
            j = req("GET", f"{ARM}{mi['id']}/providers/Microsoft.ResourceHealth/availabilityStatuses?api-version=2022-10-01&$top=200")
            st = []
            for x in j.get("value") or []:
                p = x.get("properties") or {}
                t = parse_dt(p.get("occuredTime") or p.get("occurredTime") or p.get("reportedTime"))
                if t:
                    st.append((t, (p.get("availabilityState") or "").lower(), p.get("reasonType") or "", p.get("summary") or ""))
            st.sort()
            for k, (t, state, reason, summ) in enumerate(st):
                if state in ("unavailable", "degraded") and t >= start_utc:
                    nxt = next((s[0] for s in st[k + 1:] if s[1] == "available"), None)
                    dur = max(1, min(3600, int((nxt - t).total_seconds()))) if nxt else 30
                    rs = reason.lower()
                    out.append({"mi": mi["name"], "start": t.isoformat(), "duration_s": dur, "source": "Resource Health",
                                "reason": "Planned" if "planned" in rs and "un" not in rs else ("UserInitiated" if "user" in rs else "Unplanned")})
            return out

        def cpu(mi):
            j = req("GET", f"{ARM}{mi['id']}/providers/Microsoft.Insights/metrics?api-version=2023-10-01&metricnames=avg_cpu_percent"
                           f"&interval=PT1H&aggregation=Average&timespan={start_utc:%Y-%m-%dT%H:%M:%SZ}/{now_utc:%Y-%m-%dT%H:%M:%SZ}")
            pts = []
            for ts in ((j.get("value") or [{}])[0].get("timeseries") or []):
                for p in ts.get("data") or []:
                    if p.get("average") is not None:
                        pts.append((p["timeStamp"], p["average"]))
            return pts
        rh_err = cpu_err = 0
        with ThreadPoolExecutor(max_workers=8) as ex:
            fut_rh = {i["name"]: ex.submit(rh, i) for i in d["instances"]}
            fut_cpu = {i["name"]: ex.submit(cpu, i) for i in d["instances"]}
            for n, f in fut_rh.items():
                try:
                    d["events"] += f.result()
                except Exception:
                    rh_err += 1
            for n, f in fut_cpu.items():
                try:
                    d["cpu"][n] = f.result()
                except Exception:
                    cpu_err += 1
        src("Resource Health · historial", "ok" if not rh_err else "partial", f"{len(d['events'])} eventos; {rh_err} errores")
        src("Azure Monitor · avg_cpu_percent", "ok" if not cpu_err else "partial", f"{cpu_err} errores" if cpu_err else "")

        # 6) Failovers manuales (Activity Log)
        try:
            names = {i["id"].lower(): i["name"] for i in d["instances"]}
            for sub in sorted({i["sub"] for i in d["instances"]}):
                flt = quote(f"eventTimestamp ge '{start_utc:%Y-%m-%dT%H:%M:%SZ}' and resourceProvider eq 'Microsoft.Sql'")
                j = req("GET", f"{ARM}/subscriptions/{sub}/providers/Microsoft.Insights/eventtypes/management/values"
                               f"?api-version=2015-04-01&$filter={flt}&$select=operationName,resourceId,eventTimestamp,status")
                for e in j.get("value") or []:
                    op = ((e.get("operationName") or {}).get("value") or "").lower()
                    rid = (e.get("resourceId") or "").lower()
                    st = ((e.get("status") or {}).get("value") or "").lower()
                    t = parse_dt(e.get("eventTimestamp"))
                    if op.endswith("managedinstances/failover/action") and st == "succeeded" and rid in names and t:
                        dup = any(x["mi"] == names[rid] and abs((parse_dt(x["start"]) - t).total_seconds()) < 900 for x in d["events"])
                        if dup:
                            for x in d["events"]:
                                if x["mi"] == names[rid] and abs((parse_dt(x["start"]) - t).total_seconds()) < 900:
                                    x["reason"] = "UserInitiated"
                        else:
                            d["events"].append({"mi": names[rid], "start": t.isoformat(), "duration_s": 10,
                                                "reason": "UserInitiated", "source": "Activity Log"})
            src("Activity Log · failovers manuales", "ok")
        except Exception as e:
            src("Activity Log · failovers manuales", "partial", e)

        # 7) Application Insights (workspace-based) vía Log Analytics
        wss = _csv_list(LOG_ANALYTICS_WORKSPACE_IDS)
        if not wss:
            src("Application Insights · dependencias SQL", "skipped", "LOG_ANALYTICS_WORKSPACE_IDS sin configurar")
        days = period_days

        def la(ws, q):
            j = req("POST", f"https://api.loganalytics.io/v1/workspaces/{ws}/query", {"query": q, "timespan": f"P{days}D"},
                    scope="https://api.loganalytics.io/.default")
            t = (j.get("tables") or [{}])[0]
            cols = [c["name"] for c in t.get("columns") or []]
            return [dict(zip(cols, r)) for r in t.get("rows") or []]
        for ws in wss:
            try:
                d["dep_hourly"] += la(ws, "AppDependencies | where Type has 'SQL' | summarize n=count() by app=AppRoleName, "
                                          "target=Target, ts=bin(TimeGenerated, 1h)")
                d["dep_fail"] += la(ws, "AppDependencies | where Type has 'SQL' and Success == false | summarize n=count() by "
                                        "app=AppRoleName, target=Target, ts=bin(TimeGenerated, 1m), code=tostring(ResultCode)")
                d["req_fail"] += la(ws, "AppRequests | where Success == false and toint(ResultCode) >= 500 | summarize n=count() "
                                        "by app=AppRoleName, ts=bin(TimeGenerated, 1m)")
                d["telemetry"] = True
                src(f"Application Insights · workspace …{ws[-6:]}", "ok")
            except Exception as e:
                src(f"Application Insights · workspace …{ws[-6:]}", "error", e)
        return d

    # ==== Dataset DEMO (simulado, determinista; sin datos reales de cliente) ==============================
    def collect_demo():
        rnd = random.Random(20261022)
        SUB = "00000000-0000-0000-0000-000000000000"
        DNS = "a1b2c3d4e5f6.database.windows.net"

        def mi(name, loc, tier, vc, win, proxy, tags=None, fog=None, role=None, partner=None, rg="rg-data-prd"):
            return {"id": f"/subscriptions/{SUB}/resourceGroups/{rg}/providers/Microsoft.Sql/managedInstances/{name}",
                    "name": name, "sub": SUB, "rg": rg, "location": loc, "tier": tier, "vcores": vc,
                    "cfg_id": "" if win == "Default" else config_id(SUB, loc, win), "proxy": proxy, "zone_redundant": tier == "BusinessCritical",
                    "pool": False, "fqdn": f"{name}.{DNS}", "tags": tags or {"entorno": "prd"},
                    "fog": fog, "fog_role": role, "fog_partner": partner}
        inst = [
            mi("sqlmi-core-prd", "spaincentral", "BusinessCritical", 16, "Default", "Proxy",
               {"entorno": "prd", "app": "core"}, "fog-core", "Primary", "sqlmi-core-dr"),
            mi("sqlmi-core-dr", "westeurope", "BusinessCritical", 16, "Default", "Proxy",
               {"entorno": "prd", "app": "core", "rol": "dr"}, "fog-core", "Secondary", "sqlmi-core-prd", "rg-data-dr"),
            mi("sqlmi-orders-prd", "spaincentral", "GeneralPurpose", 8, "Weekday", "Redirect", {"entorno": "prd", "app": "orders"}),
            mi("sqlmi-bookings-prd", "spaincentral", "GeneralPurpose", 8, "Default", "Redirect", {"entorno": "prd", "app": "bookings"}),
            mi("sqlmi-dwh-prd", "spaincentral", "GeneralPurpose", 16, "Weekend", "Redirect",
               {"entorno": "prd", "app": "dwh", "batch-hours": "23-04"}),
            mi("sqlmi-pre", "spaincentral", "GeneralPurpose", 4, "Default", "Redirect", {"entorno": "pre"}, rg="rg-data-pre"),
        ]
        fog_host = f"fog-core.{DNS}"
        # app: (rpm base, [(target host, db)], perfil de reintentos, horario)
        APPS = {
            "customer-portal-web": (420, [(fog_host, "CoreDB")], "none", "web"),
            "pricing-api": (260, [(f"sqlmi-core-prd.{DNS}", "PricingDB")], "none", "web"),
            "crm-contactcenter": (180, [(fog_host, "CoreDB"), (f"sqlmi-bookings-prd.{DNS}", "BookingsDB")], "none", "office"),
            "orders-backoffice": (120, [(f"sqlmi-orders-prd.{DNS}", "OrdersDB")], "resilient", "office"),
            "mobile-app-api": (380, [(fog_host, "CoreDB")], "resilient", "web"),
            "payments-api": (90, [(fog_host, "PaymentsDB")], "resilient", "web"),
            "bookings-api": (140, [(f"sqlmi-bookings-prd.{DNS}", "BookingsDB")], "partial", "web"),
            "nightly-etl": (25, [(f"sqlmi-dwh-prd.{DNS}", "DWH")], "resilient", "batch"),
        }
        WEB = [0.08, 0.05, 0.04, 0.04, 0.05, 0.08, 0.15, 0.35, 0.7, 1.0, 1.0, 1.0, 1.0, 1.0, 0.95, 0.75, 0.75,
               0.9, 0.95, 0.95, 0.9, 0.8, 0.45, 0.2]

        def rpm(app, lo):
            base, _, _, kind = APPS[app]
            wd, h = lo.weekday(), lo.hour
            if kind == "office":
                f = (1.0 if 9 <= h < 14 else 0.7 if 8 <= h < 22 else 0.0) * (0.35 if wd >= 5 else 1.0)
            elif kind == "batch":
                f = 8.0 if (h >= 23 or h < 4) else 0.3
            else:
                f = WEB[h] * (0.55 if wd >= 5 else 1.0)
            return base * f

        def at_local(days_back, wd, hh, mm, ss=0):
            today = to_local(now_utc).replace(tzinfo=None)
            day = (today - timedelta(days=days_back)).date()
            day = day - timedelta(days=(day.weekday() - wd) % 7)
            return from_local(datetime(day.year, day.month, day.day, hh, mm, ss))
        EVENTS = [("sqlmi-core-prd", 22, 1, 18, 42, 9, "Planned"), ("sqlmi-core-prd", 22, 1, 18, 44, 6, "Planned"),
                  ("sqlmi-dwh-prd", 20, 6, 23, 15, 14, "Planned"), ("sqlmi-core-dr", 18, 3, 3, 10, 7, "Planned"),
                  ("sqlmi-orders-prd", 15, 2, 23, 5, 11, "Planned"), ("sqlmi-bookings-prd", 11, 0, 19, 20, 8, "Planned"),
                  ("sqlmi-bookings-prd", 11, 0, 19, 23, 5, "Planned"), ("sqlmi-core-prd", 8, 4, 11, 37, 21, "Unplanned"),
                  ("sqlmi-pre", 6, 1, 10, 2, 5, "UserInitiated"), ("sqlmi-bookings-prd", 3, 3, 20, 51, 28, "Unplanned")]
        events = []
        for name, db, wd, hh, mm, dur, reason in EVENTS:
            if db > period_days:
                continue
            t = at_local(db, wd, hh, mm, rnd.randint(0, 50))
            events.append({"mi": name, "start": t.isoformat(), "duration_s": dur, "reason": reason,
                           "source": "Activity Log" if reason == "UserInitiated" else "Resource Health"})

        def host_mi(h):
            lab = h.split(".")[0]
            return "sqlmi-core-prd" if lab == "fog-core" else lab
        dep_hourly, dep_fail, req_fail = [], [], []
        h0 = start_utc.replace(minute=0, second=0)
        hours = int((now_utc - h0).total_seconds() // 3600)
        for app, (base, targets, retry, kind) in APPS.items():
            for k in range(hours):
                t = h0 + timedelta(hours=k)
                v = rpm(app, to_local(t)) * 3 * 60
                for host, dbn in targets:
                    share = 1.0 / len(targets)
                    dep_hourly.append({"app": app, "target": f"{host} | {dbn}", "ts": t.isoformat(),
                                       "n": int(v * share * rnd.uniform(0.9, 1.1))})
        CODES = [("40613", 0.5), ("40197", 0.2), ("4060", 0.15), ("233", 0.15)]
        for ev in events:
            t = parse_dt(ev["start"])
            for app, (base, targets, retry, kind) in APPS.items():
                for host, dbn in targets:
                    if host_mi(host) != ev["mi"]:
                        continue
                    n = rpm(app, to_local(t)) * 3 * (ev["duration_s"] + 10) / 60 / len(targets) * rnd.uniform(0.85, 1.15)
                    if n < 1:
                        continue
                    minute = t.replace(second=0)
                    for code, p in CODES:
                        c = int(round(n * p))
                        if c:
                            dep_fail.append({"app": app, "target": f"{host} | {dbn}", "ts": minute.isoformat(), "code": code, "n": c})
                    ratio = {"none": 0.8, "partial": 0.25}.get(retry, 0.0) * rnd.uniform(0.9, 1.1)
                    if int(n * ratio):
                        req_fail.append({"app": app, "ts": minute.isoformat(), "n": int(n * ratio)})
        for _ in range(60):
            app = rnd.choice(list(APPS))
            host, dbn = APPS[app][1][0]
            t = (start_utc + timedelta(minutes=rnd.randint(0, period_days * 1440 - 1))).replace(second=0)
            dep_fail.append({"app": app, "target": f"{host} | {dbn}", "ts": t.isoformat(), "code": rnd.choice(["1205", "1222", "-2"]), "n": rnd.randint(1, 3)})
            if rnd.random() < 0.5:
                req_fail.append({"app": app, "ts": t.isoformat(), "n": 1})
        up_start = at_local(-3, (to_local(now_utc).weekday() + 3) % 7, 17, 0)
        upcoming = [{"tracking_id": "QK4X-9TZ", "title": "Mantenimiento planificado de Azure SQL Managed Instance · Spain Central",
                     "start": up_start.isoformat(), "end": (up_start + timedelta(hours=15)).isoformat(), "regions": ["spaincentral"],
                     "impacted": ["sqlmi-core-prd", "sqlmi-bookings-prd", "sqlmi-pre"], "source": "Service Health"}]
        alerts = [{"name": "alr-servicehealth-incidencias", "enabled": True, "covers_maintenance": False, "covers_sqlmi": True,
                   "types": ["incident"]}]
        for name, st, det in [("Resource Graph · inventario SQL MI", "ok", "6 instancias"), ("ARM · failover groups", "ok", "1 grupo"),
                              ("Service Health · mantenimiento planificado", "ok", "1 evento"),
                              ("Resource Graph · maintenanceresources", "ok", "3 updates pendientes"),
                              ("Resource Graph · alertas Service Health", "ok", "1 alerta"),
                              ("Resource Health · historial", "ok", f"{len(events)} eventos"),
                              ("Activity Log · failovers manuales", "ok", "1 drill"),
                              ("Application Insights · dependencias SQL", "ok", f"{len(APPS)} aplicaciones")]:
            src(name + " (simulado)", st, det)
        return {"mode": "demo", "instances": inst, "events": events, "upcoming": upcoming, "alerts": alerts,
                "dep_hourly": dep_hourly, "dep_fail": dep_fail, "req_fail": req_fail, "cpu": {}, "telemetry": True}

    # ==== Obtener datos ================================================================================
    replay = os.environ.get("SQLMI_REPLAY", "").strip()
    if replay and Path(replay).is_file():
        raw = json.loads(Path(replay).read_text(encoding="utf-8"))["raw"]
        src("Replay JSON", "ok", Path(replay).name)
    elif mode_req == "demo" or (mode_req == "auto" and not _configured(MANAGED_IDENTITY_CLIENT_ID)):
        raw = collect_demo()
    else:
        if not _configured(MANAGED_IDENTITY_CLIENT_ID):
            return {"status": "error", "mode": "live", "message": "Configura MANAGED_IDENTITY_CLIENT_ID en el código de la tool "
                    "(README paso 4) o ejecuta con data_source='demo'."}
        try:
            raw = collect_live()
        except Exception as e:
            return {"status": "error", "mode": "live", "message": f"Error recogiendo datos: {e}", "sources": sources}
        if not raw["instances"]:
            return {"status": "no_data", "mode": "live", "sources": sources,
                    "message": "La identidad no ve ninguna SQL Managed Instance. Revisa el rol Reader (README paso 3) "
                               "o ejecuta con data_source='demo' para ver el informe de ejemplo."}
    MODE = raw["mode"]
    insts = raw["instances"]
    by_name = {i["name"]: i for i in insts}
    for i in insts:
        i["window"] = window_of(i["cfg_id"])
        i["env"] = env_of(i["name"], i["tags"])
        i["batch"], i["batch_label"] = batch_cells(i["tags"])
    fog_primary = {}
    for i in insts:
        if i.get("fog") and i.get("fog_role") == "Primary":
            fog_primary[i["fog"].lower()] = i["name"]

    def mi_of_target(t):
        host = (t or "").split("|")[0].strip().split(",")[0].lower()
        lab = host.split(".")[0]
        return lab if lab in by_name else fog_primary.get(lab)

    # ---- Mapa de carga 7x24 por instancia (media de llamadas SQL por hora local) ----------------------
    occ = defaultdict(int)
    h = start_utc.replace(minute=0, second=0)
    while h < now_utc:
        lo = to_local(h)
        occ[(lo.weekday(), lo.hour)] += 1
        h += timedelta(hours=1)
    heat = defaultdict(lambda: [[0.0] * 24 for _ in range(7)])
    app_mi = defaultdict(int)
    for r in raw["dep_hourly"]:
        mi = mi_of_target(r.get("target"))
        t = parse_dt(r.get("ts"))
        if not mi or not t:
            continue
        lo = to_local(t)
        heat[mi][lo.weekday()][lo.hour] += float(r.get("n") or 0)
        app_mi[(r.get("app") or "?", mi)] += int(r.get("n") or 0)
    heat_src = {}
    for mi in list(heat):
        for d_ in range(7):
            for hh in range(24):
                heat[mi][d_][hh] /= max(1, occ[(d_, hh)])
        heat_src[mi] = "Application Insights"
    for name, pts in (raw.get("cpu") or {}).items():
        if name in heat_src or not pts:
            continue
        acc, cnt = [[0.0] * 24 for _ in range(7)], [[0] * 24 for _ in range(7)]
        for ts, v in pts:
            t = parse_dt(ts)
            if t:
                lo = to_local(t)
                acc[lo.weekday()][lo.hour] += v
                cnt[lo.weekday()][lo.hour] += 1
        heat[name] = [[acc[a][b] / cnt[a][b] if cnt[a][b] else 0 for b in range(24)] for a in range(7)]
        heat_src[name] = "CPU (avg_cpu_percent)"
    for i in insts:
        if i["name"] not in heat_src and i.get("fog_partner") in heat_src:
            heat[i["name"]] = heat[i["fog_partner"]]
            heat_src[i["name"]] = f"carga del primario ({i['fog_partner']})"

    # ---- Eventos: ventana, hora local, eventos detectados por telemetría ------------------------------
    fails_by_mi = defaultdict(list)
    for r in raw["dep_fail"]:
        mi, t = mi_of_target(r.get("target")), parse_dt(r.get("ts"))
        if mi and t:
            fails_by_mi[mi].append((t, r.get("app") or "?", str(r.get("code") or ""), int(r.get("n") or 0)))
    req_by_app = defaultdict(list)
    for r in raw["req_fail"]:
        t = parse_dt(r.get("ts"))
        if t:
            req_by_app[r.get("app") or "?"].append((t, int(r.get("n") or 0)))
    events = [dict(e) for e in raw["events"] if e["mi"] in by_name]
    if MODE == "live":
        for mi, rows in fails_by_mi.items():
            per_min = defaultdict(int)
            for t, app, code, n in rows:
                if code in TRANSIENT:
                    per_min[t.replace(second=0)] += n
            for t, n in sorted(per_min.items()):
                if n >= 25 and not any(e["mi"] == mi and abs((parse_dt(e["start"]) - t).total_seconds()) < 900 for e in events):
                    events.append({"mi": mi, "start": t.isoformat(), "duration_s": 60, "reason": "Detected", "source": "Telemetría"})
    REASON = {"Planned": "Planificado", "Unplanned": "No planificado", "UserInitiated": "Manual (drill)", "Detected": "Detectado (telemetría)"}
    for e in events:
        t = parse_dt(e["start"])
        e["_t"], e["local"] = t, fmt_local(t)
        e["in_window"] = in_window(by_name[e["mi"]]["window"], to_local(t))
        e["reason_es"] = REASON.get(e["reason"], e["reason"])
    events.sort(key=lambda x: x["_t"])

    # ---- Correlación evento -> dependencias fallidas -> errores de usuario -------------------------------
    impact = []
    app_stats = defaultdict(lambda: {"dep": 0, "user": 0, "events": 0, "codes": defaultdict(int)})

    def ev_span(e):
        return e["_t"] - timedelta(minutes=2), e["_t"] + timedelta(seconds=e["duration_s"]) + timedelta(minutes=5)

    def nearest(cands, t):
        # Cada fallo se asigna a un único evento (el más cercano) para no contar dos veces reconfiguraciones seguidas.
        hits = [k for k in cands if ev_span(events[k])[0] <= t <= ev_span(events[k])[1]]
        return min(hits, key=lambda k: abs((t - events[k]["_t"]).total_seconds())) if hits else None
    ev_by_mi = defaultdict(list)
    for k, e in enumerate(events):
        ev_by_mi[e["mi"]].append(k)
        e["dep_failures"], e["user_errors"], e["apps"], e["_per_app"] = 0, 0, [], defaultdict(int)
    for mi, rows in fails_by_mi.items():
        for t, app, code, n in rows:
            k = nearest(ev_by_mi.get(mi, []), t) if code in TRANSIENT else None
            if k is not None:
                events[k]["_per_app"][app] += n
                app_stats[app]["codes"][code] += n
    app_events = defaultdict(list)
    for k, e in enumerate(events):
        for app in e["_per_app"]:
            app_events[app].append(k)
    user_by = defaultdict(int)
    for app, rows in req_by_app.items():
        for t, n in rows:
            k = nearest(app_events.get(app, []), t)
            if k is not None:
                user_by[(k, app)] += n
    for k, e in enumerate(events):
        for app, n in sorted(e["_per_app"].items(), key=lambda x: -x[1]):
            u = user_by[(k, app)]
            app_stats[app]["dep"] += n
            app_stats[app]["user"] += u
            app_stats[app]["events"] += 1
            e["dep_failures"] += n
            e["user_errors"] += u
            e["apps"].append(app)
            impact.append({"event_local": e["local"], "event_utc": e["start"], "managed_instance": e["mi"], "reason": e["reason_es"],
                           "duration_s": e["duration_s"], "app": app, "sql_dependency_failures": n, "user_errors": u})
        del e["_per_app"]

    def verdict(dep, user):
        if not raw.get("telemetry"):
            return "Sin telemetría"
        if dep == 0:
            return "Sin impacto observado"
        r = user / dep
        return "Sin reintentos" if r >= 0.5 else ("Parcial" if r >= 0.05 else "Resiliente")
    apps = []
    for (app, mi), n in app_mi.items():
        if not any(x["app"] == app for x in apps):
            s = app_stats[app]
            apps.append({"app": app, "mis": sorted({m for (a_, m) in app_mi if a_ == app}),
                         "sql_calls": sum(v for (a_, m), v in app_mi.items() if a_ == app), "events": s["events"],
                         "dep_failures": s["dep"], "user_errors": s["user"],
                         "ratio": round(s["user"] / s["dep"], 2) if s["dep"] else None, "verdict": verdict(s["dep"], s["user"]),
                         "codes": ", ".join(f"{c}×{v}" for c, v in sorted(s["codes"].items(), key=lambda x: -x[1])[:4])})
    ORDER = {"Sin reintentos": 0, "Parcial": 1, "Resiliente": 2, "Sin impacto observado": 3, "Sin telemetría": 4}
    apps.sort(key=lambda x: (ORDER.get(x["verdict"], 9), -x["user_errors"]))
    risky = {a["app"] for a in apps if a["verdict"] in ("Sin reintentos", "Parcial")}
    apps_by_mi = defaultdict(list)
    for a in apps:
        for m in a["mis"]:
            apps_by_mi[m].append(a)

    # ---- Recomendación de ventana por instancia ----------------------------------------------------------
    def win_score(mi, w):
        hm = heat.get(mi)
        if not hm:
            return None
        peak = max(max(r) for r in hm) or 1
        cells = WINDOW_CELLS[w]
        base = sum(hm[d_][hh] for d_, hh in cells) / len(cells) / peak
        pen = 0.5 * len(cells & by_name[mi]["batch"]) / len(cells) if by_name[mi]["batch"] else 0
        return round(base + pen, 3)
    for i in insts:
        i["scores"] = {w: win_score(i["name"], w) for w in ("Default", "Weekday", "Weekend")}
        i["recommended"] = None
        cand = {w: s for w, s in i["scores"].items() if w != "Default" and s is not None}
        if cand and not i["pool"]:
            best = min(cand, key=cand.get)
            # Solo se recomienda cambiar si mejora >10 %: cambiar la ventana cambia la IP de la instancia.
            cur = cand.get(i["window"])
            i["recommended"] = i["window"] if cur is not None and cand[best] >= cur * 0.9 else best
    for i in insts:
        if i.get("fog_role") == "Secondary" and i.get("fog_partner") in by_name:
            p = by_name[i["fog_partner"]]
            if p["recommended"]:
                i["recommended"] = "Weekend" if p["recommended"] == "Weekday" else "Weekday"
        i["paired"] = bool(i.get("fog_partner")) and REGION_PAIRS.get(i["location"]) == by_name.get(i["fog_partner"], {}).get("location")
        i["recommended_id"] = config_id(i["sub"], i["location"], i["recommended"]) if i["recommended"] else None
        actual = sum(e["user_errors"] for e in events if e["mi"] == i["name"] and e["reason"] == "Planned")
        est = 0.0
        hm = heat.get(i["name"])
        if hm and i["recommended"] and actual:
            cells = WINDOW_CELLS[i["recommended"]]
            mean_w = sum(hm[d_][hh] for d_, hh in cells) / len(cells)
            for e in events:
                if e["mi"] == i["name"] and e["reason"] == "Planned" and e["user_errors"]:
                    lo = to_local(e["_t"])
                    est += e["user_errors"] * min(1.0, mean_w / max(hm[lo.weekday()][lo.hour], 1e-9))
        i["user_errors_planned"], i["user_errors_est"] = actual, int(round(est))

    # ---- Hallazgos priorizados ------------------------------------------------------------------------------
    findings = []

    def add(sev, title, scope, detail, action, cmd=""):
        findings.append({"severity": sev, "title": title, "scope": scope, "detail": detail, "action": action, "command": cmd})
    prd = [i for i in insts if i["env"] == "prd"]
    up7 = [u for u in raw["upcoming"] if parse_dt(u["start"]) <= now_utc + timedelta(days=7)]
    for u in up7:
        at = sorted({a["app"] for m in u["impacted"] for a in apps_by_mi.get(m, []) if a["app"] in risky})
        if at:
            add("Alta", f"Mantenimiento en {max(0, (parse_dt(u['start']) - now_utc).days)} días con aplicaciones sin reintentos",
                ", ".join(u["impacted"]), f"{u['title']} ({u['tracking_id']}) empieza {fmt_local(parse_dt(u['start']))}. "
                f"Aplicaciones en riesgo: {', '.join(at)}.",
                "Avisar a los equipos de esas aplicaciones, tener el runbook de comunicación listo y, si es posible, "
                "aplicar antes la ventana recomendada o validar los reintentos.")
    for a in apps:
        if a["verdict"] == "Sin reintentos":
            add("Alta", "Aplicación sin lógica de reintentos", a["app"], f"{a['user_errors']} errores de usuario por "
                f"{a['dep_failures']} fallos SQL transitorios en {a['events']} reconfiguraciones (ratio {a['ratio']}).",
                "Implementar reintentos con backoff exponencial para errores transitorios (ver retry-samples/). "
                "Es la única medida que elimina el impacto, también en eventos no planificados.")
        elif a["verdict"] == "Parcial":
            add("Media", "Aplicación con reintentos parciales", a["app"], f"{a['user_errors']} errores de usuario de "
                f"{a['dep_failures']} fallos SQL (ratio {a['ratio']}): reintenta en algunos caminos pero no en todos.",
                "Revisar que el reintento cubra apertura de conexión y comandos, y que el timeout total sea ≥ 60 s.")
    if not any(x["enabled"] and x["covers_maintenance"] and x["covers_sqlmi"] for x in raw["alerts"]):
        partial = [x["name"] for x in raw["alerts"] if x["enabled"]]
        add("Alta", "Sin aviso anticipado de mantenimiento de SQL MI", "Suscripción",
            "Ninguna alerta de Service Health cubre 'Mantenimiento planificado' para SQL Managed Instance"
            + (f" (existe {', '.join(partial)}, pero no incluye Maintenance)." if partial else "."),
            "Crear la alerta (aviso 24 h antes, al inicio y al final) con create-sqlmi-maintenance-alert.ps1.",
            "./create-sqlmi-maintenance-alert.ps1 -SubscriptionId <SUB_ID> -ResourceGroup <RG> -ActionGroupId <ACTION_GROUP_ID>")
    for i in prd:
        if i["window"] == "Default" and not i["pool"] and i.get("fog_role") != "Secondary":
            hit = [a["app"] for a in apps_by_mi.get(i["name"], []) if a["app"] in risky]
            rec = i["recommended"] or "Weekday"
            red = (f" Estimación: {i['user_errors_planned']} → ~{i['user_errors_est']} errores de usuario en mantenimientos planificados."
                   if i["user_errors_planned"] else "")
            add("Alta" if hit else "Media", "Instancia de producción en la ventana por defecto (17:00–08:00)", i["name"],
                "La ventana por defecto incluye la franja de tarde con tráfico alto." + (f" Apps afectadas: {', '.join(hit)}." if hit else "") + red,
                f"Cambiar a {WINDOWS[rec]} (mejor puntuación según la carga real). Cambia la IP de la instancia: actualizar NSG/firewalls.",
                f"az sql mi update -g {i['rg']} -n {i['name']} --maint-config-id \"{config_id(i['sub'], i['location'], rec)}\"")
    for i in insts:
        if i.get("fog_role") == "Primary" and i.get("fog_partner") in by_name:
            s = by_name[i["fog_partner"]]
            if not i["paired"] and i["window"] == s["window"]:
                add("Alta", "Failover group con la misma ventana en regiones no emparejadas", f"{i['fog']} ({i['name']} / {s['name']})",
                    f"{region_label(i['location'])} y {region_label(s['location'])} no son pareja de región: Azure puede mantener ambas "
                    "réplicas en la misma franja.",
                    f"Primario en {WINDOWS[i['recommended'] or 'Weekday']}, secundario en {WINDOWS[s['recommended'] or 'Weekend']}. "
                    "Cambiar primero el secundario.",
                    f"az sql mi update -g {s['rg']} -n {s['name']} --maint-config-id \"{config_id(s['sub'], s['location'], s['recommended'] or 'Weekend')}\"")
    for i in insts:
        if i["proxy"] == "Proxy":
            add("Media", "Tipo de conexión Proxy", i["name"], "Proxy es el modo heredado: añade latencia y genera más desconexiones "
                "por el mantenimiento del gateway. Redirect es el valor por defecto desde octubre de 2025.",
                "Cambiar a Redirect (abrir puertos 11000–11999 desde las subredes cliente; validar en preproducción).",
                f"az sql mi update -g {i['rg']} -n {i['name']} --proxy-override Redirect")
    for i in insts:
        if i["batch"] and i["batch"] & WINDOW_CELLS.get(i["window"], set()):
            n = sum(1 for e in events if e["mi"] == i["name"] and (lambda lo: (lo.weekday(), lo.hour))(to_local(e["_t"])) in i["batch"])
            add("Media", "La ventana se solapa con los procesos batch", i["name"], f"Batch {i['batch_label']} dentro de "
                f"{WINDOWS[i['window']]}; {n} reconfiguración(es) cayeron en horario batch.",
                "Asegurar que los jobs son reanudables/idempotentes, o mover el batch fuera de la ventana.")
    unpl = [e for e in events if e["reason"] in ("Unplanned", "Detected")]
    if unpl:
        add("Media", "Eventos no planificados: la ventana no protege", ", ".join(sorted({e["mi"] for e in unpl})),
            f"{len(unpl)} eventos fuera de control de la ventana, con {sum(e['user_errors'] for e in unpl)} errores de usuario.",
            "Solo los reintentos en la aplicación evitan este impacto. Ninguna ventana lo resuelve.")
    for i in prd:
        if i["tier"] == "GeneralPurpose" and any(a["app"] in risky for a in apps_by_mi.get(i["name"], [])):
            add("Info", "General Purpose con aplicaciones críticas", i["name"], "En GP la reconfiguración mueve el motor a otro nodo; "
                "en Business Critical conmuta a una réplica ya caliente.", "Valorar Business Critical solo si tras los reintentos sigue habiendo impacto.")
    outside = [e for e in events if e["reason"] == "Planned" and not e["in_window"]]
    if outside:
        add("Info", "Eventos planificados fuera de la ventana configurada", ", ".join(sorted({e["mi"] for e in outside})),
            f"{len(outside)} eventos. Azure puede aplicar actualizaciones críticas fuera de ventana.", "Revisar en Service Health el motivo.")
    for i in insts:
        if i["pool"]:
            add("Info", "Instancia en instance pool", i["name"], "La ventana de mantenimiento no se puede configurar en instance pools.", "—")
    if raw.get("telemetry"):
        for i in prd:
            if not apps_by_mi.get(i["name"]) and i.get("fog_role") != "Secondary":
                add("Info", "Instancia sin telemetría de aplicaciones", i["name"], "Ninguna dependencia SQL de Application Insights apunta a esta instancia.",
                    "Habilitar Application Insights en las aplicaciones que la usan para medir el impacto real.")
    if any(f["command"].startswith("az sql mi update") and "maint-config-id" in f["command"] for f in findings):
        add("Info", "Cambiar la ventana cambia la IP de la instancia", "Todas", "La operación mueve la instancia a otro cluster "
            "virtual: cambia la IP y requiere IPs libres en la subred.", "Planificar el cambio en horario valle, actualizar NSG/firewalls y "
            "comprobar el tamaño de subred.")
    SEV = {"Alta": 0, "Media": 1, "Info": 2}
    findings.sort(key=lambda f: SEV[f["severity"]])

    # ---- KPIs ------------------------------------------------------------------------------------------
    durs = [e["duration_s"] for e in events]
    nxt = min(raw["upcoming"], key=lambda u: u["start"]) if raw["upcoming"] else None
    user_total = sum(e["user_errors"] for e in events)
    user_norety = sum(a["user_errors"] for a in apps if a["verdict"] == "Sin reintentos")
    kpis = {
        "managed_instances_prd": len(prd),
        "prd_on_default_window": sum(1 for i in prd if i["window"] == "Default"),
        "reconfigurations": len(events),
        "planned": sum(1 for e in events if e["reason"] == "Planned"),
        "unplanned": len(unpl),
        "avg_duration_s": round(sum(durs) / len(durs), 1) if durs else 0,
        "max_duration_s": max(durs) if durs else 0,
        "user_errors": user_total,
        "user_errors_no_retry_pct": round(100 * user_norety / user_total) if user_total else 0,
        "apps_no_retry": sum(1 for a in apps if a["verdict"] == "Sin reintentos"),
        "apps_partial": sum(1 for a in apps if a["verdict"] == "Parcial"),
        "apps_total": len(apps),
        "next_maintenance": fmt_local(parse_dt(nxt["start"])) if nxt else "—",
        "maintenance_alert": any(x["enabled"] and x["covers_maintenance"] and x["covers_sqlmi"] for x in raw["alerts"]),
    }
    answer = (f"{period_label}: {kpis['reconfigurations']} reconfiguraciones de SQL MI (media {kpis['avg_duration_s']} s, máx "
              f"{kpis['max_duration_s']} s). {user_total} errores llegaron a usuarios; el {kpis['user_errors_no_retry_pct']} % viene de "
              f"{kpis['apps_no_retry']} aplicaciones sin reintentos. La ventana decide CUÁNDO ocurre la reconfiguración; los reintentos "
              f"deciden SI el usuario lo nota. {kpis['unplanned']} eventos no planificados no los habría evitado ninguna ventana.")
    if operation == "summary":
        return {"status": "ok", "mode": MODE, "period": period_label, "kpis": kpis, "answer": answer,
                "findings": [{k: f[k] for k in ("severity", "title", "scope", "action", "command")} for f in findings],
                "apps": [{k: a[k] for k in ("app", "verdict", "user_errors", "dep_failures")} for a in apps],
                "sources": sources}
    if operation == "upcoming":
        return {"status": "ok", "mode": MODE, "upcoming": [dict(u, start_local=fmt_local(parse_dt(u["start"])), end_local=fmt_local(parse_dt(u["end"])),
                at_risk_apps=sorted({a["app"] for m in u["impacted"] for a in apps_by_mi.get(m, []) if a["app"] in risky})) for u in raw["upcoming"]],
                "maintenance_alert": kpis["maintenance_alert"], "sources": sources}

    # ==== Informe HTML ==================================================================================
    E = lambda v: html.escape("" if v is None else str(v))
    CSS = """
*{box-sizing:border-box}body{margin:0;font-family:'Segoe UI',Arial,Helvetica,sans-serif;background:#F4F7FB;color:#1B2A3A;font-size:14px;line-height:1.45}
.wrap{max-width:1180px;margin:0 auto;padding:0 18px 40px}
header{background:#243A5E;color:#fff;padding:18px 0 22px;border-bottom:5px solid #0078D4}
header .wrap{display:flex;gap:18px;align-items:center;padding-bottom:0}
header svg{flex:0 0 auto}
header h1{margin:0;font-size:22px;font-weight:600}header p{margin:4px 0 0;opacity:.9;font-size:13px}
.demo{background:#FFF4E5;color:#7A4A00;border:1px solid #F0C27B;border-radius:8px;padding:8px 12px;margin:16px 0 0;font-weight:600}
h2{color:#243A5E;font-size:18px;margin:30px 0 10px;padding-bottom:6px;border-bottom:2px solid #D6E4F2}
.answer{background:#fff;border-left:6px solid #0078D4;border-radius:8px;padding:14px 18px;margin-top:18px;box-shadow:0 1px 3px rgba(0,40,90,.08);font-size:15px}
.kpis{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;margin-top:16px}
@media(max-width:760px){.kpis{grid-template-columns:repeat(2,1fr)}}
.kpi{background:#fff;border-radius:10px;padding:12px 14px;box-shadow:0 1px 3px rgba(0,40,90,.08);border-top:4px solid #243A5E}
.kpi b{display:block;font-size:24px;color:#243A5E}.kpi span{font-size:12px;color:#5A6B7D}
.kpi.bad{border-top-color:#C62828}.kpi.bad b{color:#C62828}.kpi.warn{border-top-color:#B26A00}.kpi.warn b{color:#B26A00}
.card{background:#fff;border-radius:10px;padding:14px 16px;box-shadow:0 1px 3px rgba(0,40,90,.08);margin-bottom:12px}
.card.up{border-left:6px solid #C62828}
.tw{overflow-x:auto;background:#fff;border-radius:10px;box-shadow:0 1px 3px rgba(0,40,90,.08)}
table{border-collapse:collapse;width:100%;min-width:720px}th{background:#243A5E;color:#fff;text-align:left;font-weight:600;font-size:12.5px}
th,td{padding:8px 10px;vertical-align:top;border-bottom:1px solid #E3EAF2}tr:nth-child(even) td{background:#F9FBFD}
code{background:#EEF3F9;border-radius:4px;padding:2px 5px;font-size:12px;word-break:break-all;font-family:Consolas,monospace}
.sev{display:inline-block;border-radius:12px;padding:2px 9px;font-size:12px;font-weight:700;color:#fff}
.Alta{background:#C62828}.Media{background:#B26A00}.Info{background:#6B7C93}
.v{display:inline-block;border-radius:12px;padding:2px 9px;font-size:12px;font-weight:600}
.v0{background:#FDE7E7;color:#C62828}.v1{background:#FFF1DC;color:#8A5200}.v2{background:#E3F4EA;color:#1E7B45}.v3,.v4{background:#EEF1F5;color:#5A6B7D}
.ok{color:#1E7B45;font-weight:600}.ko{color:#C62828;font-weight:600}
.hm{display:grid;grid-template-columns:38px repeat(24,1fr);gap:2px;font-size:10px;min-width:640px}
.hm div{height:18px;border-radius:2px;display:flex;align-items:center;justify-content:center}
.hm .lab{background:none;color:#5A6B7D;justify-content:flex-start}
.hm .w{background-image:repeating-linear-gradient(45deg,rgba(255,255,255,.55) 0 2px,transparent 2px 5px)}
.hm .r{box-shadow:inset 0 0 0 2px #0078D4}
.legend{font-size:12px;color:#5A6B7D;margin:6px 0 2px}.legend i{display:inline-block;width:14px;height:12px;vertical-align:middle;margin:0 4px 0 10px;border-radius:2px}
.cols{display:grid;grid-template-columns:repeat(auto-fit,minmax(260px,1fr));gap:12px}
.cols .card h3{margin:0 0 8px;font-size:15px;color:#243A5E}.cols ul{margin:0;padding-left:18px}.cols li{margin:4px 0}
.small{font-size:12px;color:#5A6B7D}footer{margin-top:30px;font-size:12px;color:#5A6B7D}
svg text{font-family:'Segoe UI',Arial,sans-serif}
@media(max-width:640px){header h1{font-size:18px}header svg{width:42px;height:42px}.kpi b{font-size:20px}body{font-size:13px}}
"""

    def kpi(v, lab, cls=""):
        return f'<div class="kpi {cls}"><b>{E(v)}</b><span>{E(lab)}</span></div>'
    VCLS = {k: f"v{n}" for k, n in ORDER.items()}
    out = [f'<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">'
           f'<title>SQL MI · Resiliencia ante mantenimiento</title><style>{CSS}</style></head><body>',
           f'<header><div class="wrap"><svg width="52" height="52" viewBox="0 0 48 48" aria-hidden="true"><rect width="48" height="48" rx="10" fill="#fff"/><g fill="none" stroke="#0078D4" stroke-width="3"><ellipse cx="24" cy="13" rx="12" ry="5"/><path d="M12 13v22c0 2.8 5.4 5 12 5s12-2.2 12-5V13M12 24c0 2.8 5.4 5 12 5s12-2.2 12-5"/></g></svg><div>'
           f'<h1>Resiliencia de Azure SQL Managed Instance ante mantenimiento</h1>'
           f'<p>{E(period_label)} · generado {E(fmt_local(now_utc))} ({E(LOCAL_TIMEZONE)}) · Azure SRE Agent</p></div></div></header><div class="wrap">']
    if MODE == "demo":
        out.append('<div class="demo">MODO DEMO — datos simulados para mostrar el informe. Configura la tool (README paso 4) para analizar tu entorno.</div>')
    out.append(f'<div class="answer"><b>Respuesta corta.</b> {E(answer)}</div><div class="kpis">')
    out += [kpi(kpis["managed_instances_prd"], "SQL MI de producción"),
            kpi(f"{kpis['prd_on_default_window']}/{kpis['managed_instances_prd']}", "en ventana por defecto", "warn" if kpis["prd_on_default_window"] else ""),
            kpi(kpis["reconfigurations"], f"reconfiguraciones ({kpis['planned']} planif. · {kpis['unplanned']} no planif.)"),
            kpi(f"{kpis['avg_duration_s']} s", f"duración media (máx {kpis['max_duration_s']} s)"),
            kpi(kpis["user_errors"], "errores vistos por usuarios", "bad" if kpis["user_errors"] else ""),
            kpi(f"{kpis['apps_no_retry']}/{kpis['apps_total']}", f"apps sin reintentos (+{kpis['apps_partial']} parciales)", "bad" if kpis["apps_no_retry"] else ""),
            kpi(kpis["next_maintenance"], "próximo mantenimiento"),
            kpi("Sí" if kpis["maintenance_alert"] else "No", "alerta de mantenimiento", "" if kpis["maintenance_alert"] else "bad")]
    out.append("</div>")

    out.append("<h2>Próximo mantenimiento</h2>")
    if not raw["upcoming"]:
        out.append('<div class="card">No hay mantenimientos planificados publicados en Service Health para tus SQL MI.</div>')
    for u in sorted(raw["upcoming"], key=lambda x: x["start"]):
        at = sorted({a["app"] for m in u["impacted"] for a in apps_by_mi.get(m, []) if a["app"] in risky})
        out.append(f'<div class="card {"up" if at else ""}"><b>{E(u["title"])}</b> <span class="small">· {E(u["tracking_id"])} · {E(u["source"])}</span><br>'
                   f'{E(fmt_local(parse_dt(u["start"])))} → {E(fmt_local(parse_dt(u["end"])))} · Instancias: {E(", ".join(u["impacted"]) or "—")}<br>'
                   + (f'<span class="ko">Aplicaciones en riesgo (sin reintentos o parciales): {E(", ".join(at))}</span>' if at
                      else '<span class="ok">Sin aplicaciones en riesgo detectadas.</span>') + "</div>")

    out.append('<h2>Acciones priorizadas</h2><div class="tw"><table><tr><th>Prioridad</th><th>Hallazgo</th><th>Ámbito</th><th>Detalle</th>'
               '<th>Qué hacer</th></tr>')
    for f in findings:
        out.append(f'<tr><td><span class="sev {f["severity"]}">{E(f["severity"])}</span></td><td><b>{E(f["title"])}</b></td><td>{E(f["scope"])}</td>'
                   f'<td>{E(f["detail"])}</td><td>{E(f["action"])}' + (f'<br><code>{E(f["command"])}</code>' if f["command"] else "") + "</td></tr>")
    out.append("</table></div>")

    out.append('<h2>Instancias y ventanas</h2><div class="tw"><table><tr><th>Instancia</th><th>Región</th><th>Tier</th><th>Entorno</th>'
               '<th>Ventana actual</th><th>Conexión</th><th>Failover group</th><th>Ventana recomendada</th><th>Errores usuario (planificados)</th></tr>')
    for i in sorted(insts, key=lambda x: (x["env"] != "prd", x["name"])):
        fg = f'{i["fog"]} · {"primario" if i["fog_role"] == "Primary" else "secundario"}' if i.get("fog") else "—"
        rec = WINDOWS[i["recommended"]] if i["recommended"] and i["recommended"] != i["window"] else ("Mantener" if i["recommended"] else "—")
        est = (f'{i["user_errors_planned"]} → ~{i["user_errors_est"]}' if i["user_errors_planned"] and i["recommended"] != i["window"]
               else str(i["user_errors_planned"]))
        out.append(f'<tr><td><b>{E(i["name"])}</b></td><td>{E(region_label(i["location"]))}</td><td>{E("BC" if i["tier"] == "BusinessCritical" else "GP")} · '
                   f'{E(i["vcores"])} vCores</td><td>{E(i["env"])}</td><td>{E(WINDOWS[i["window"]])}</td>'
                   f'<td class="{"ko" if i["proxy"] == "Proxy" else ""}">{E(i["proxy"])}</td><td>{E(fg)}</td><td>{E(rec)}</td><td>{E(est)}</td></tr>')
    out.append('</table></div><p class="small">La estimación de errores aplica la carga media de la ventana recomendada a los eventos planificados '
               'reales. Es orientativa: solo los reintentos eliminan el impacto.</p>')

    lanes = sorted({e["mi"] for e in events}, key=lambda m: list(by_name).index(m))
    if events:
        W, L, LH = 1000, 200, 34
        H = 40 + LH * len(lanes)
        RC = {"Planned": "#0078D4", "Unplanned": "#C62828", "UserInitiated": "#6B7C93", "Detected": "#B26A00"}
        sv = [f'<svg viewBox="0 0 {W} {H}" width="100%" role="img" aria-label="Línea de tiempo de reconfiguraciones">']
        span = (now_utc - start_utc).total_seconds()
        for k in range(0, period_days + 1, max(1, period_days // 6)):
            x = L + (W - L - 20) * k / period_days
            sv.append(f'<line x1="{x:.0f}" y1="10" x2="{x:.0f}" y2="{H - 22}" stroke="#E3EAF2"/>'
                      f'<text x="{x:.0f}" y="{H - 6}" font-size="11" fill="#5A6B7D" text-anchor="middle">{E((to_local(start_utc + timedelta(days=k))).strftime("%d/%m"))}</text>')
        for n, m in enumerate(lanes):
            y = 26 + n * LH
            sv.append(f'<text x="6" y="{y + 4}" font-size="12" fill="#1B2A3A">{E(m)}</text><line x1="{L}" y1="{y}" x2="{W - 20}" y2="{y}" stroke="#C9D6E4"/>')
            groups = []
            for e in sorted((x for x in events if x["mi"] == m), key=lambda x: x["_t"]):
                x = L + (W - L - 20) * (e["_t"] - start_utc).total_seconds() / span
                r = 4 + min(9, e["duration_s"] / 3)
                sv.append(f'<circle cx="{x:.1f}" cy="{y}" r="{r:.1f}" fill="{RC.get(e["reason"], "#999")}" fill-opacity=".85">'
                          f'<title>{E(e["local"])} · {E(e["reason_es"])} · {e["duration_s"]} s · {e["user_errors"]} errores usuario</title></circle>')
                # Reconfiguraciones muy próximas (p. ej. 2 en el mismo mantenimiento) comparten una sola etiqueta.
                if groups and x - groups[-1][0] < 14:
                    groups[-1][1] += e["user_errors"]
                    groups[-1][2] = max(groups[-1][2], r)
                    groups[-1][3] += 1
                else:
                    groups.append([x, e["user_errors"], r, 1])
            for x, u, r, c in groups:
                if u:
                    lbl = f'{u} ({c} reconf.)' if c > 1 else str(u)
                    sv.append(f'<text x="{x:.1f}" y="{y - r - 3:.1f}" font-size="10.5" fill="#C62828" text-anchor="middle" font-weight="700">{lbl}</text>')
        sv.append("</svg>")
        out.append('<h2>Reconfiguraciones y errores de usuario</h2><div class="card">' + "".join(sv) +
                   '<div class="legend"><i style="background:#0078D4"></i>Planificado<i style="background:#C62828"></i>No planificado'
                   '<i style="background:#6B7C93"></i>Manual (drill)<i style="background:#B26A00"></i>Detectado por telemetría · '
                   'número rojo = errores vistos por usuarios · tamaño = duración</div></div>')
        out.append('<div class="tw"><table><tr><th>Fecha (hora local)</th><th>Instancia</th><th>Tipo</th><th>Duración</th><th>¿En ventana?</th>'
                   '<th>Fallos SQL transitorios</th><th>Errores usuario</th><th>Aplicaciones</th></tr>')
        for e in reversed(events):
            out.append(f'<tr><td>{E(e["local"])}</td><td>{E(e["mi"])}</td><td>{E(e["reason_es"])}</td><td>{e["duration_s"]} s</td>'
                       f'<td>{("Sí" if e["in_window"] else "No") if e["reason"] == "Planned" else "n/a"}</td><td>{e["dep_failures"]}</td><td class="{"ko" if e["user_errors"] else ""}">{e["user_errors"]}</td>'
                       f'<td>{E(", ".join(e["apps"]) or "—")}</td></tr>')
        out.append("</table></div>")

    out.append('<h2>Aplicaciones: ¿absorben la reconfiguración?</h2><div class="tw"><table><tr><th>Aplicación</th><th>Instancias</th>'
               '<th>Llamadas SQL</th><th>Reconfig. afectadas</th><th>Fallos SQL transitorios</th><th>Errores usuario</th><th>Ratio</th>'
               '<th>Veredicto</th><th>Códigos</th></tr>')
    for a in apps:
        out.append(f'<tr><td><b>{E(a["app"])}</b></td><td>{E(", ".join(a["mis"]))}</td><td>{a["sql_calls"]:,}</td><td>{a["events"]}</td>'
                   f'<td>{a["dep_failures"]}</td><td>{a["user_errors"]}</td><td>{E(a["ratio"] if a["ratio"] is not None else "—")}</td>'
                   f'<td><span class="v {VCLS.get(a["verdict"], "v4")}">{E(a["verdict"])}</span></td><td>{E(a["codes"] or "—")}</td></tr>')
    out.append('</table></div><p class="small">Ratio = errores de usuario (peticiones HTTP 5xx) ÷ fallos SQL transitorios durante la '
               'reconfiguración. ≥ 0,5: el error llega al usuario (sin reintentos). &lt; 0,05: la aplicación lo absorbe.</p>')

    out.append("<h2>Carga real vs. ventanas de mantenimiento</h2>")
    for i in insts:
        hm = heat.get(i["name"])
        if not hm or i.get("fog_role") == "Secondary":
            continue
        peak = max(max(r) for r in hm) or 1
        cw = WINDOW_CELLS.get(i["window"], set())
        rw = WINDOW_CELLS.get(i["recommended"], set()) if i["recommended"] and i["recommended"] != i["window"] else set()
        cells = ['<div class="lab"></div>'] + [f'<div class="lab" style="justify-content:center">{hh}</div>' for hh in range(24)]
        for d_ in range(7):
            cells.append(f'<div class="lab">{DIAS[d_]}</div>')
            for hh in range(24):
                a_ = 0.06 + 0.94 * hm[d_][hh] / peak
                cls = ("w " if (d_, hh) in cw else "") + ("r" if (d_, hh) in rw else "")
                cells.append(f'<div class="{cls}" style="background-color:rgba(0,75,147,{a_:.2f})" title="{DIAS[d_]} {hh:02d}:00 · {hm[d_][hh]:,.0f}"></div>')
        sc = " · ".join(f"{w}: {i['scores'][w]}" for w in ("Default", "Weekday", "Weekend") if i["scores"].get(w) is not None)
        out.append(f'<div class="card"><b>{E(i["name"])}</b> <span class="small">· fuente: {E(heat_src.get(i["name"], "—"))} · '
                   f'actual: {E(WINDOWS[i["window"]])}' + (f' · recomendada: <b>{E(WINDOWS[i["recommended"]])}</b>' if rw else "") +
                   (f' · batch {E(i["batch_label"])}' if i["batch_label"] else "") +
                   f'</span><div style="overflow-x:auto;margin-top:8px"><div class="hm">{"".join(cells)}</div></div>'
                   f'<div class="legend">Azul más intenso = más carga · <i class="w" style="background:#7FA5CC;background-image:repeating-linear-gradient(45deg,'
                   f'rgba(255,255,255,.6) 0 2px,transparent 2px 5px)"></i>ventana actual<i style="box-shadow:inset 0 0 0 2px #0078D4"></i>ventana '
                   f'recomendada · puntuación (menor = mejor): {E(sc)}</div></div>')

    out.append('<h2>Qué permite Azure, qué no y qué hacer</h2><div class="cols">'
               '<div class="card"><h3>Lo que Azure permite</h3><ul><li>3 ventanas: por defecto (17:00–08:00), entre semana (Lun–Jue 22:00–06:00) y '
               'fin de semana (Vie–Dom 22:00–06:00), en hora local de la región.</li><li>Aviso 24 h antes, al inicio y al final mediante alertas de '
               'Service Health.</li><li>Ventanas distintas en primario y secundario de un failover group.</li><li>Conexión Redirect (menos '
               'desconexiones por mantenimiento del gateway).</li><li>Failover manual para ensayar (máx. 1 cada 15 min).</li></ul></div>'
               '<div class="card"><h3>Lo que Azure no permite</h3><ul><li>Elegir día y hora exactos ni ventanas a medida como en on-premises.</li>'
               '<li>Posponer o cancelar un mantenimiento concreto.</li><li>Evitar eventos no planificados (hardware, red) ni actualizaciones '
               'críticas que pueden aplicarse fuera de ventana.</li><li>Una reconfiguración sin desconexión: siempre corta conexiones unos segundos.</li></ul></div>'
               '<div class="card"><h3>Qué hacer (en este orden)</h3><ul><li><b>Reintentos</b> con backoff en todas las aplicaciones: elimina el '
               'impacto en planificados y no planificados.</li><li>Alerta de mantenimiento + comunicación a negocio.</li><li>Ventana entre semana o '
               'fin de semana según la carga real; ventanas distintas en el failover group.</li><li>Redirect en lugar de Proxy.</li>'
               '<li>Ensayo trimestral en preproducción con failover manual.</li></ul></div></div>')

    out.append('<h2>Fuentes y cobertura</h2><div class="tw"><table><tr><th>Fuente</th><th>Estado</th><th>Detalle</th></tr>')
    for s in sources:
        out.append(f'<tr><td>{E(s["source"])}</td><td class="{"ok" if s["status"] == "ok" else "ko" if s["status"] == "error" else ""}">{E(s["status"])}</td>'
                   f'<td>{E(s["detail"])}</td></tr>')
    out.append('</table></div><footer>Informe de solo lectura generado por Azure SRE Agent · tool generate-sqlmi-maintenance-report v1.0. '
               'Referencias: Microsoft Learn — Maintenance window (SQL MI), Advance notifications, Connection types, Configurable retry logic (SqlClient).</footer>'
               '</div></body></html>')
    html_doc = "".join(out)

    # ==== Salidas ======================================================================================
    base_name = f"sqlmi-mantenimiento-{stamp}"
    files = {}
    try:
        p = cwd / f"{base_name}.html"
        p.write_text(html_doc, encoding="utf-8")
        files["html"] = file_url(p.name)
        report = {"generated_utc": now_utc.isoformat(), "mode": MODE, "period": period_label, "kpis": kpis, "answer": answer,
                  "findings": findings, "apps": apps,
                  "instances": [{k: v for k, v in i.items() if k != "batch"} for i in insts],
                  "events": [{k: v for k, v in e.items() if k != "_t"} for e in events], "upcoming": raw["upcoming"],
                  "alerts": raw["alerts"], "sources": sources, "raw": raw}
        p = cwd / f"{base_name}.json"
        p.write_text(json.dumps(report, ensure_ascii=False, separators=(",", ":"), default=str), encoding="utf-8")
        files["json"] = file_url(p.name)
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        w.writerow(["instancia", "region", "tier", "vcores", "entorno", "ventana_actual", "maintenance_configuration_id", "conexion",
                    "failover_group", "rol", "ventana_recomendada", "maintenance_configuration_id_recomendado",
                    "errores_usuario_planificados", "errores_usuario_estimados"])
        for i in insts:
            w.writerow([i["name"], i["location"], i["tier"], i["vcores"], i["env"], i["window"], i["cfg_id"] or "SQL_Default", i["proxy"],
                        i.get("fog") or "", i.get("fog_role") or "", i["recommended"] or "", i["recommended_id"] or "",
                        i["user_errors_planned"], i["user_errors_est"]])
        p = cwd / f"{base_name}-instancias.csv"
        p.write_text("\ufeff" + buf.getvalue(), encoding="utf-8")
        files["csv_instances"] = file_url(p.name)
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";")
        cols = ["event_local", "event_utc", "managed_instance", "reason", "duration_s", "app", "sql_dependency_failures", "user_errors"]
        w.writerow(cols)
        for r in impact:
            w.writerow([r[c] for c in cols])
        p = cwd / f"{base_name}-impacto.csv"
        p.write_text("\ufeff" + buf.getvalue(), encoding="utf-8")
        files["csv_impact"] = file_url(p.name)
    except Exception as e:
        return {"status": "error", "mode": MODE, "message": f"No se pudieron escribir los ficheros: {e}", "kpis": kpis}

    return {
        "status": "ok",
        "mode": MODE,
        "period": period_label,
        "files": files,
        "kpis": kpis,
        "answer": answer,
        "top_actions": [{k: f[k] for k in ("severity", "title", "scope", "action", "command")} for f in findings[:6]],
        "next_maintenance": nxt and {"tracking_id": nxt["tracking_id"], "start_local": fmt_local(parse_dt(nxt["start"])),
                                     "impacted": nxt["impacted"]},
        "message": ("MODO DEMO (datos simulados). " if MODE == "demo" else "")
                   + f"Informe listo: [Abrir informe HTML]({files['html']}) · [JSON]({files['json']}) · "
                     f"[CSV instancias]({files['csv_instances']}) · [CSV impacto]({files['csv_impact']})",
    }
