# generate-fabric-chargeback-report
# Microsoft Fabric FinOps: real cost, who consumes what, idle capacity and savings, from the customer's own tenant.
# Two auth modes, zero secrets in both:
#   A) Same tenant (default): the SRE Agent managed identity reads Fabric/Azure directly.
#   B) Cross-tenant: managed identity -> Federated Identity Credential -> multi-tenant app in the Fabric tenant.
# Sources (all live, read-only): Power BI/Fabric admin APIs (activity log, workspaces, items, refreshables, tenant settings),
#   Fabric Spark (Livy sessions), OneLake (DFS), Azure Cost Management (daily cost per meter), Azure Activity Log
#   (capacity suspend/resume) and the public Azure Retail Prices API. Nothing is simulated or estimated without a source.
# Read-only · Version 5.0 · October 2026


def main(operation: str = "report", period: str = "last_30d", identities: str = "masked") -> dict:
    """Generate a read-only Microsoft Fabric FinOps and chargeback report (HTML + JSON + 2 CSV) from real tenant data."""
    import csv
    import hashlib
    import html
    import io
    import json
    import math
    import os
    import re
    import time
    from collections import Counter, defaultdict
    from concurrent.futures import ThreadPoolExecutor
    from datetime import datetime, timedelta, timezone
    from pathlib import Path
    from urllib.parse import quote

    # ---- CONFIGURE (see README, step "Configure the tool") ---------------------------------------
    # Client ID of the SRE Agent user-assigned managed identity. Required in both modes.
    MANAGED_IDENTITY_CLIENT_ID = "<SRE_AGENT_UAMI_CLIENT_ID>"
    # Option A - same tenant: leave the two values below untouched (or set them to "").
    # Option B - cross-tenant: client ID of the multi-tenant app and tenant ID where Fabric lives.
    FEDERATED_APP_CLIENT_ID = "<FEDERATED_APP_CLIENT_ID>"
    TARGET_FABRIC_TENANT_ID = "<TARGET_FABRIC_TENANT_ID>"
    # ------------------------------------------------------------------------------------------------

    def _configured(v):
        return bool((v or "").strip()) and not v.strip().startswith("<")

    CROSS_TENANT = _configured(FEDERATED_APP_CLIENT_ID) and _configured(TARGET_FABRIC_TENANT_ID)
    AUTH_MODE = "cross_tenant" if CROSS_TENANT else "same_tenant"
    OWN_IDENTITY_ID = (FEDERATED_APP_CLIENT_ID if CROSS_TENANT else MANAGED_IDENTITY_CLIENT_ID).strip().lower()
    FABRIC_API = "https://api.fabric.microsoft.com/v1"
    PBI_API = "https://api.powerbi.com/v1.0/myorg"
    ARM_API = "https://management.azure.com"
    BUDGET_SECONDS = 105

    operation = (operation or "report").strip().lower()
    show_ids = (identities or "masked").strip().lower() in ("full", "show", "visible", "yes", "true")
    period_map = {"last_30d": ("Últimos 30 días", 30), "last_14d": ("Últimos 14 días", 14), "last_7d": ("Últimos 7 días", 7)}
    period_key = (period or "last_30d").strip().lower()
    if period_key not in period_map:
        period_key = "last_30d"
    period_label, period_days = period_map[period_key]
    now_utc = datetime.now(timezone.utc)
    ref_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    stamp = now_utc.strftime("%Y%m%dT%H%M%SZ")
    window_start = (now_utc - timedelta(days=period_days)).replace(hour=0, minute=0, second=0, microsecond=0)
    replay = os.environ.get("FABRIC_FINOPS_REPLAY")
    cwd = Path.cwd()
    m_tid = re.fullmatch(r"/(?:root/sreagent|usr)/terminalRoot/tmp/ThreadFiles/([0-9a-fA-F-]{36})", cwd.as_posix())

    def file_url(name):
        return f"/api/files/tmp/ThreadFiles/{m_tid.group(1)}/{quote(name, safe='')}" if m_tid else str(cwd / name)

    if replay:
        raw = json.loads(Path(replay).read_text(encoding='utf-8'))
        sources = raw.get('sources', {})
    else:
        # ================================================================== 1. COLLECT (real tenant data only)
        T0 = time.monotonic()
        sources = {}

        def src(name, status, http=None, count=None, note=None, started=None):
            sources[name] = {"status": status, "http": http, "count": count, "note": note,
                             "seconds": round(time.monotonic() - (started or T0), 1)}

        def left():
            return BUDGET_SECONDS - (time.monotonic() - T0)

        def req(method, url, tok, params=None, body=None, headers=None, timeout=25, retries=2):
            err = None
            for attempt in range(retries + 1):
                if left() < 3:
                    return None, "budget", {}
                h = {"Authorization": "Bearer " + tok, "Accept": "application/json"}
                h.update(headers or {})
                try:
                    r = requests.request(method, url, params=params, json=body, headers=h, timeout=max(3, min(timeout, left())))
                except Exception as exc:
                    err = type(exc).__name__
                    continue
                if r.status_code == 429 and attempt < retries:
                    waits = []
                    for k, v in r.headers.items():
                        if k.lower().endswith("retry-after"):
                            try:
                                waits.append(float(v))
                            except ValueError:
                                pass
                    wait = max(waits) if waits else 4.0 * (attempt + 1)
                    if wait > left() - 20:
                        return 429, "retry-after %ds" % int(wait), r.headers
                    time.sleep(min(max(wait, 1.0), 30.0))
                    continue
                try:
                    data = r.json()
                except ValueError:
                    data = r.text[:300]
                return r.status_code, data, r.headers
            return None, err or "error", {}

        import requests
        from azure.identity import ClientAssertionCredential, ManagedIdentityCredential

        uami = (ManagedIdentityCredential(client_id=MANAGED_IDENTITY_CLIENT_ID) if _configured(MANAGED_IDENTITY_CLIENT_ID)
                else ManagedIdentityCredential())
        if CROSS_TENANT:
            cred = ClientAssertionCredential(tenant_id=TARGET_FABRIC_TENANT_ID, client_id=FEDERATED_APP_CLIENT_ID,
                                             func=lambda: uami.get_token("api://AzureADTokenExchange/.default").token)
        else:
            cred = uami
        tokens = {}
        for key, scope in (("fab", "https://api.fabric.microsoft.com/.default"),
                           ("pbi", "https://analysis.windows.net/powerbi/api/.default"),
                           ("arm", "https://management.azure.com/.default"),
                           ("sto", "https://storage.azure.com/.default")):
            try:
                tokens[key] = cred.get_token(scope).token
            except Exception as exc:
                tokens[key] = None
                src("token_" + key, "error", note=type(exc).__name__)

        def _token_tid(tok):
            try:
                import base64
                p = tok.split(".")[1]
                return json.loads(base64.urlsafe_b64decode(p + "=" * (-len(p) % 4))).get("tid")
            except Exception:
                return None

        tenant_id = TARGET_FABRIC_TENANT_ID if CROSS_TENANT else next(
            (_token_tid(v) for v in tokens.values() if v and _token_tid(v)), None)
        raw = {"generated_utc": ref_iso, "period_days": period_days, "tenant_id": tenant_id, "auth_mode": AUTH_MODE}

        def c_capacities():
            t = time.monotonic()
            st, d, _ = req("GET", f"{PBI_API}/admin/capacities", tokens["pbi"])
            caps = d.get("value", []) if isinstance(d, dict) else []
            raw["pbi_capacities"] = [{"id": (c.get("id") or "").lower(), "name": c.get("displayName"), "sku": c.get("sku"),
                                      "state": c.get("state"), "region": c.get("region"), "admins": len(c.get("admins") or [])}
                                     for c in caps]
            src("capacities", "ok" if st == 200 else "error", st, len(caps), started=t)

        def c_workspaces():
            t = time.monotonic()
            out, url, st = [], f"{FABRIC_API}/admin/workspaces", None
            for _ in range(10):
                st, d, _ = req("GET", url, tokens["fab"])
                if st != 200 or not isinstance(d, dict):
                    break
                for w in d.get("workspaces", []) or []:
                    out.append({"id": (w.get("id") or "").lower(), "name": w.get("name"), "type": w.get("type"),
                                "state": w.get("state"), "capacity_id": (w.get("capacityId") or "").lower()})
                url = d.get("continuationUri")
                if not url:
                    break
            raw["workspaces"] = out
            src("workspaces", "ok" if out else "error", st, len(out), started=t)
            return out

        def c_items():
            t = time.monotonic()
            out, url, st = [], f"{FABRIC_API}/admin/items", None
            for _ in range(20):
                st, d, _ = req("GET", url, tokens["fab"])
                if st != 200 or not isinstance(d, dict):
                    break
                for i in d.get("itemEntities", []) or []:
                    cp = i.get("creatorPrincipal") or {}
                    out.append({"id": (i.get("id") or "").lower(), "type": i.get("type"), "name": i.get("name"),
                                "state": i.get("state"), "updated": i.get("lastUpdatedDate"),
                                "ws": (i.get("workspaceId") or "").lower(), "cap": (i.get("capacityId") or "").lower(),
                                "creator_id": (cp.get("id") or "").lower(), "creator_name": cp.get("displayName"),
                                "creator_upn": (cp.get("userDetails") or {}).get("userPrincipalName"),
                                "creator_type": cp.get("type")})
                url = d.get("continuationUri")
                if not url and d.get("continuationToken"):
                    url = f"{FABRIC_API}/admin/items?continuationToken={quote(d['continuationToken'])}"
                if not url:
                    break
            raw["items"] = out
            src("items", "ok" if out else "error", st, len(out), started=t)
            return out

        def c_activity():
            t = time.monotonic()
            days = min(period_days, 27)
            res = {}

            def one_day(dd):
                day = (now_utc - timedelta(days=dd)).strftime("%Y-%m-%d")
                end = now_utc.strftime("%H:%M:%S") + ".000Z" if dd == 0 else "23:59:59.999Z"
                url = (f"{PBI_API}/admin/activityevents?startDateTime='{day}T00:00:00.000Z'&endDateTime='{day}T{end}'")
                evs, st = [], None
                for _ in range(40):
                    st, d, _ = req("GET", url, tokens["pbi"], timeout=30)
                    if st != 200 or not isinstance(d, dict):
                        break
                    for e in d.get("activityEventEntities") or []:
                        evs.append({
                            "t": e.get("CreationTime"), "u": e.get("UserId") or e.get("UserKey") or "",
                            "a": e.get("Activity") or e.get("Operation") or "", "wl": e.get("Workload") or "",
                            "ws": e.get("WorkSpaceName") or e.get("WorkspaceName") or "",
                            "wsid": (e.get("WorkspaceId") or "").lower(),
                            "it": (e.get("ItemName") or e.get("ArtifactName") or e.get("ObjectDisplayName") or e.get("DatasetName")
                                   or e.get("ReportName") or e.get("DashboardName") or ""),
                            "itt": e.get("ArtifactKind") or e.get("ItemType") or e.get("ObjectType") or "",
                            "cap": e.get("CapacityName") or "", "ok": e.get("IsSuccess"),
                            "ua": (e.get("UserAgent") or "")[:80], "ut": e.get("UserType"),
                        })
                    if d.get("lastResultSet") or not d.get("continuationUri"):
                        break
                    url = d["continuationUri"]
                return day, st, evs

            with ThreadPoolExecutor(max_workers=9) as ex:
                for day, st, evs in ex.map(one_day, range(days)):
                    res[day] = (st, evs)
            events, ok_days, last_st = [], 0, None
            for day in sorted(res):
                st, evs = res[day]
                last_st = st if st != 200 else last_st
                if st == 200:
                    ok_days += 1
                events.extend(evs)
            raw["events"] = events
            raw["activity_days_ok"] = ok_days
            raw["activity_days_requested"] = days
            src("activity", "ok" if ok_days == days else ("partial" if ok_days else "error"), last_st or 200, len(events),
                note=f"{ok_days}/{days} días", started=t)

        def c_refreshables():
            t = time.monotonic()
            st, d, _ = req("GET", f"{PBI_API}/admin/capacities/refreshables", tokens["pbi"],
                           params={"$top": "500", "$expand": "capacity,group"}, timeout=30)
            rows = d.get("value", []) if isinstance(d, dict) else []
            out = []
            for r in rows:
                lr = r.get("lastRefresh") or {}
                sc = r.get("refreshSchedule") or {}
                out.append({"id": r.get("id"), "name": r.get("name"), "kind": r.get("kind"),
                            "ws": (r.get("group") or {}).get("name"), "wsid": ((r.get("group") or {}).get("id") or "").lower(),
                            "cap": (r.get("capacity") or {}).get("displayName"), "sku": (r.get("capacity") or {}).get("sku"),
                            "last_type": lr.get("refreshType"), "last_start": lr.get("startTime"), "last_end": lr.get("endTime"),
                            "last_status": lr.get("status"), "last_error": (str(lr.get("serviceExceptionJson") or "")[:200] or None),
                            "sched_enabled": bool(sc.get("enabled")), "sched_days": sc.get("days") or [], "sched_times": sc.get("times") or [],
                            "count": r.get("refreshCount"), "failures": r.get("refreshFailures"),
                            "avg_s": r.get("averageDuration"), "median_s": r.get("medianDuration"),
                            "per_day": r.get("refreshesPerDay"), "configured_by": r.get("configuredBy") or []})
            raw["refreshables"] = out
            src("refreshables", "ok" if st == 200 else "error", st, len(out), started=t)

        def c_livy(workspaces):
            t = time.monotonic()
            win = [w for w in workspaces if w.get("capacity_id")]

            def one(w):
                url, out, st = f"{FABRIC_API}/workspaces/{w['id']}/spark/livySessions", [], None
                for _ in range(6):
                    st, d, _ = req("GET", url, tokens["fab"], timeout=20, retries=1)
                    if st != 200 or not isinstance(d, dict):
                        break
                    for s in d.get("value", []) or []:
                        out.append({"ws": w["id"], "item": s.get("itemName"), "item_id": ((s.get("item") or {}).get("itemId") or "").lower(),
                                    "item_type": s.get("itemType"), "job": s.get("jobType"), "op": s.get("operationName"),
                                    "user_id": ((s.get("submitter") or {}).get("id") or "").lower(),
                                    "user_type": (s.get("submitter") or {}).get("type"), "state": s.get("state"),
                                    "submitted": s.get("submittedDateTime"), "start": s.get("startDateTime"), "end": s.get("endDateTime"),
                                    "queued_s": (s.get("queuedDuration") or {}).get("value"),
                                    "running_s": (s.get("runningDuration") or {}).get("value"),
                                    "total_s": (s.get("totalDuration") or {}).get("value"),
                                    "cap": (s.get("capacityId") or "").lower(), "hc": s.get("isHighConcurrency"),
                                    "origin": s.get("origin"), "runtime": s.get("runtimeVersion")})
                    url = d.get("continuationUri")
                    if not url:
                        break
                return st, out

            sessions, codes = [], Counter()
            with ThreadPoolExecutor(max_workers=8) as ex:
                for st, out in ex.map(one, win):
                    codes[str(st)] += 1
                    sessions.extend(out)
            raw["livy"] = sessions
            raw["livy_http"] = dict(codes)
            src("spark", "ok" if codes.get("200") else "error", "200" if codes.get("200") else None, len(sessions),
                note=f"{codes.get('200', 0)}/{len(win)} workspaces", started=t)

        def c_onelake(items):
            t = time.monotonic()
            targets = [i for i in items if i.get("type") in ("Lakehouse", "Warehouse") and i.get("ws")][:60]

            def one(it):
                tot, files, cont, st, pages = 0, 0, None, None, 0
                for _ in range(10):
                    if left() < 12:
                        break
                    params = {"resource": "filesystem", "recursive": "true", "directory": it["id"]}
                    if cont:
                        params["continuation"] = cont
                    try:
                        r = requests.get(f"https://onelake.dfs.fabric.microsoft.com/{it['ws']}", params=params, timeout=max(3, min(20, left())),
                                         headers={"Authorization": "Bearer " + tokens["sto"], "x-ms-version": "2023-08-03"})
                    except Exception:
                        break
                    st = r.status_code
                    if st != 200:
                        break
                    pages += 1
                    for p in (r.json() or {}).get("paths", []) or []:
                        if str(p.get("isDirectory")).lower() != "true":
                            tot += int(p.get("contentLength") or 0)
                            files += 1
                    cont = r.headers.get("x-ms-continuation")
                    if not cont:
                        break
                return {"ws": it["ws"], "item": it["name"], "item_id": it["id"], "type": it["type"], "bytes": tot,
                        "files": files, "http": st, "truncated": bool(cont)}

            with ThreadPoolExecutor(max_workers=8) as ex:
                out = list(ex.map(one, targets))
            raw["onelake"] = out
            okn = sum(1 for o in out if o["http"] == 200)
            src("onelake", "ok" if okn == len(out) and out else ("partial" if okn else "error"), 200 if okn else None, len(out),
                note=f"{okn}/{len(out)} lakehouses/warehouses leídos", started=t)

        def c_arm():
            t = time.monotonic()
            st, d, _ = req("GET", f"{ARM_API}/subscriptions", tokens["arm"], params={"api-version": "2022-12-01"})
            subs = [s for s in (d.get("value", []) if isinstance(d, dict) else []) if (s.get("state") or "Enabled") == "Enabled"][:5]
            raw["subscriptions"] = [{"id": s.get("subscriptionId"), "name": s.get("displayName")} for s in subs]
            src("arm", "ok" if subs else "error", st, len(subs), started=t)
            caps, rows, logs = [], [], []
            cost_st = log_st = None
            notes = {}
            extra_st, extra_rows = {}, {"cost_monthly": [], "sub_costs": []}
            for s in subs:
                sid = s.get("subscriptionId")
                st, d, _ = req("GET", f"{ARM_API}/subscriptions/{sid}/providers/Microsoft.Fabric/capacities", tokens["arm"],
                               params={"api-version": "2023-11-01"})
                for c in (d.get("value", []) if isinstance(d, dict) else []):
                    p = c.get("properties") or {}
                    rg = re.search(r"/resourceGroups/([^/]+)/", c.get("id") or "", re.I)
                    caps.append({"name": c.get("name"), "id": (c.get("id") or "").lower(), "sub": sid, "sub_name": s.get("displayName"),
                                 "rg": rg.group(1) if rg else "", "sku": (c.get("sku") or {}).get("name"), "location": c.get("location"),
                                 "state": p.get("state"), "admins": len((p.get("administration") or {}).get("members") or []),
                                 "tags": c.get("tags") or {}})
                body = {"type": "ActualCost", "timeframe": "Custom",
                        "timePeriod": {"from": window_start.strftime("%Y-%m-%dT00:00:00Z"), "to": now_utc.strftime("%Y-%m-%dT23:59:59Z")},
                        "dataset": {"granularity": "Daily",
                                    "aggregation": {"cost": {"name": "Cost", "function": "Sum"}, "qty": {"name": "UsageQuantity", "function": "Sum"}},
                                    "grouping": [{"type": "Dimension", "name": "ResourceId"}, {"type": "Dimension", "name": "Meter"}],
                                    "filter": {"dimensions": {"name": "ResourceType", "operator": "In", "values": ["microsoft.fabric/capacities"]}}}}
                url = f"{ARM_API}/subscriptions/{sid}/providers/Microsoft.CostManagement/query?api-version=2023-11-01"
                for _ in range(5):
                    cost_st, d, _ = req("POST", url, tokens["arm"], body=body, timeout=40, retries=3)
                    if cost_st != 200 or not isinstance(d, dict):
                        if cost_st == 429:
                            notes["cost"] = "Cost Management limitó las peticiones (HTTP 429, %s); volver a pedir el informe más tarde" % d
                        break
                    pr = d.get("properties") or {}
                    cols = [c.get("name") for c in pr.get("columns") or []]
                    for row in pr.get("rows") or []:
                        r = dict(zip(cols, row))
                        rows.append({"date": str(r.get("UsageDate")), "rid": (r.get("ResourceId") or "").lower(), "meter": r.get("Meter") or "",
                                     "cost": float(r.get("Cost") or 0), "qty": float(r.get("UsageQuantity") or 0),
                                     "currency": r.get("Currency")})
                    url = pr.get("nextLink")
                    if not url:
                        break
                m0 = now_utc.replace(day=1)
                for _ in range(11):
                    m0 = (m0 - timedelta(days=1)).replace(day=1)
                extra = (("cost_monthly", {"type": "ActualCost", "timeframe": "Custom",
                                           "timePeriod": {"from": m0.strftime("%Y-%m-%dT00:00:00Z"), "to": now_utc.strftime("%Y-%m-%dT23:59:59Z")},
                                           "dataset": {"granularity": "Monthly", "aggregation": {"cost": {"name": "Cost", "function": "Sum"}},
                                                       "grouping": [{"type": "Dimension", "name": "ResourceId"}],
                                                       "filter": {"dimensions": {"name": "ResourceType", "operator": "In", "values": ["microsoft.fabric/capacities"]}}}}),
                         ("sub_costs", {"type": "ActualCost", "timeframe": "Custom",
                                        "timePeriod": {"from": window_start.strftime("%Y-%m-%dT00:00:00Z"), "to": now_utc.strftime("%Y-%m-%dT23:59:59Z")},
                                        "dataset": {"granularity": "None", "aggregation": {"cost": {"name": "Cost", "function": "Sum"}},
                                                    "grouping": [{"type": "Dimension", "name": "ServiceName"}, {"type": "Dimension", "name": "ResourceId"}]}}))
                for key, bdy in extra:
                    time.sleep(1.5)
                    st_x, d, _ = req("POST", f"{ARM_API}/subscriptions/{sid}/providers/Microsoft.CostManagement/query?api-version=2023-11-01",
                                     tokens["arm"], body=bdy, timeout=40, retries=4)
                    extra_st[key] = st_x
                    if st_x == 429:
                        notes[key] = "Cost Management limitó las peticiones (HTTP 429, %s)" % d
                    if st_x == 200 and isinstance(d, dict):
                        pr = d.get("properties") or {}
                        cols = [c.get("name") for c in pr.get("columns") or []]
                        for row in pr.get("rows") or []:
                            r = dict(zip(cols, row))
                            extra_rows[key].append({"month": str(r.get("BillingMonth") or "")[:7], "service": r.get("ServiceName") or "",
                                                    "rid": (r.get("ResourceId") or "").lower(), "cost": float(r.get("Cost") or 0),
                                                    "currency": r.get("Currency"), "sub": sid})
                flt = (f"eventTimestamp ge '{(window_start - timedelta(days=1)).strftime('%Y-%m-%dT%H:%M:%SZ')}' and "
                       f"eventTimestamp le '{now_utc.strftime('%Y-%m-%dT%H:%M:%SZ')}' and resourceProvider eq 'Microsoft.Fabric'")
                url, params = f"{ARM_API}/subscriptions/{sid}/providers/Microsoft.Insights/eventtypes/management/values", \
                    {"api-version": "2015-04-01", "$filter": flt}
                for _ in range(10):
                    log_st, d, _ = req("GET", url, tokens["arm"], params=params, timeout=30)
                    if log_st != 200 or not isinstance(d, dict):
                        break
                    for e in d.get("value", []) or []:
                        logs.append({"t": e.get("eventTimestamp"), "op": (e.get("operationName") or {}).get("value") or "",
                                     "status": (e.get("status") or {}).get("value") or "", "rid": (e.get("resourceId") or "").lower(),
                                     "caller": e.get("caller") or "", "corr": e.get("correlationId") or "",
                                     "claims_app": ((e.get("claims") or {}).get("appid") or "")})
                    url, params = d.get("nextLink"), None
                    if not url:
                        break
            raw["arm_capacities"] = caps
            raw["cost_rows"] = rows
            raw["activity_log"] = logs
            src("cost", "ok" if cost_st == 200 else "error", cost_st, len(rows), note=notes.get("cost"), started=t)
            src("activity_log", "ok" if log_st == 200 else "error", log_st, len(logs), started=t)
            raw["cost_monthly"] = extra_rows["cost_monthly"]
            raw["sub_costs"] = extra_rows["sub_costs"]
            for key in ("cost_monthly", "sub_costs"):
                src(key, "ok" if extra_st.get(key) == 200 else "error", extra_st.get(key), len(extra_rows[key]), note=notes.get(key), started=t)
            # public Azure Retail Prices for the capacity regions (no auth)
            t2 = time.monotonic()
            prices = []
            for region in sorted({c["location"].replace(" ", "").lower() for c in caps if c.get("location")})[:3]:
                url = "https://prices.azure.com/api/retail/prices"
                params = {"$filter": f"serviceName eq 'Microsoft Fabric' and armRegionName eq '{region}'", "currencyCode": "USD"}
                for _ in range(5):
                    try:
                        r = requests.get(url, params=params, timeout=max(3, min(20, left())))
                        d = r.json() if r.ok else {}
                    except Exception:
                        break
                    for p in d.get("Items", []) or []:
                        prices.append({"region": region, "meter": p.get("meterName"), "product": p.get("productName"), "type": p.get("type"),
                                       "term": p.get("reservationTerm"), "price": p.get("unitPrice"), "unit": p.get("unitOfMeasure"),
                                       "currency": p.get("currencyCode")})
                    url, params = d.get("NextPageLink"), None
                    if not url:
                        break
            raw["prices"] = prices
            src("prices", "ok" if prices else "error", 200 if prices else None, len(prices), started=t2)

        def c_tenant_settings():
            t = time.monotonic()
            st, d, _ = req("GET", f"{FABRIC_API}/admin/tenantsettings", tokens["fab"])
            ts = d.get("tenantSettings", []) if isinstance(d, dict) else []
            raw["tenant_settings"] = [{"name": s.get("settingName"), "title": s.get("title"), "enabled": bool(s.get("enabled")),
                                       "group": s.get("tenantSettingGroup"), "groups": [g.get("name") for g in s.get("enabledSecurityGroups") or []],
                                       "excluded": len(s.get("excludedSecurityGroups") or [])} for s in ts]
            src("tenant_settings", "ok" if st == 200 else "error", st, len(ts), started=t)

        def chain_workspace_livy():
            ws = c_workspaces()
            c_livy(ws)

        def chain_items_onelake():
            its = c_items()
            c_onelake(its)

        if tokens.get("fab") and tokens.get("pbi"):
            with ThreadPoolExecutor(max_workers=7) as ex:
                futs = [ex.submit(f) for f in (c_activity, chain_workspace_livy, chain_items_onelake, c_arm,
                                               c_capacities, c_refreshables, c_tenant_settings)]
                for f in futs:
                    try:
                        f.result()
                    except Exception as exc:
                        sources.setdefault("internal_" + str(len(sources)), {"status": "error", "note": f"{type(exc).__name__}: {str(exc)[:160]}"})
        raw["sources"] = sources
        raw["collect_seconds"] = round(time.monotonic() - T0, 1)

    # ================================================================== v5 ANALYSIS · only real tenant data
    t_an = time.monotonic()
    E = html.escape
    GUID = re.compile(r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$")
    WD = ["lun", "mar", "mié", "jue", "vie", "sáb", "dom"]

    def P(s):
        if not s:
            return None
        try:
            return datetime.fromisoformat(str(s).replace("Z", "")[:19]).replace(tzinfo=timezone.utc)
        except Exception:
            return None

    def fn(v, d=0):
        s = f"{(v or 0):,.{d}f}"
        return s.replace(",", "§").replace(".", ",").replace("§", ".")

    def pc(v, d=1):
        return f"{fn((v or 0) * 100, d)} %"

    def hhmm(t):
        return t.strftime("%H:%M") if t else "—"

    def floor_day(t):
        return t.replace(hour=0, minute=0, second=0, microsecond=0)

    gen = P(raw.get("generated_utc")) or now_utc
    days_n = int(raw.get("period_days") or period_days)
    win0 = floor_day(gen - timedelta(days=days_n))
    win_hours = max((gen - win0).total_seconds() / 3600, 1)
    act_days = int(raw.get("activity_days_requested") or 0)
    act_ok = int(raw.get("activity_days_ok") or 0)
    act0 = floor_day(gen - timedelta(days=act_days - 1)) if act_days else None
    own_sp = OWN_IDENTITY_ID
    sources = raw.get("sources") or {}

    workspaces = raw.get("workspaces") or []
    ws_name = {(w.get("id") or "").lower(): (w.get("name") or "") for w in workspaces}
    if not show_ids:
        # personal workspaces are named after their owner
        for _w in workspaces:
            _k, _v = (_w.get("id") or "").lower(), _w.get("name") or ""
            if (_w.get("type") or "").lower() == "personal" or "@" in _v:
                _l, _, _d = _v.partition("@")
                ws_name[_k] = f"Personal · {_l[:1]}•••@{_d[:1]}•••" if _d else f"Personal · {_l[:1]}•••"
    ws_cap = {(w.get("id") or "").lower(): (w.get("capacity_id") or "").lower() for w in workspaces}
    ws_type = {(w.get("id") or "").lower(): (w.get("type") or "") for w in workspaces}
    _wn = Counter((w.get("name") or "").lower() for w in workspaces)
    ws_by_name = {(w.get("name") or "").lower(): (w.get("id") or "").lower() for w in workspaces if _wn[(w.get("name") or "").lower()] == 1}
    items = raw.get("items") or []
    _inm = Counter((i.get("name") or "").lower() for i in items)
    item_ws = {(i.get("name") or "").lower(): (i.get("ws") or "").lower() for i in items if _inm[(i.get("name") or "").lower()] == 1}
    item_type_by_name = {(i.get("name") or "").lower(): i.get("type") or "" for i in items if _inm[(i.get("name") or "").lower()] == 1}
    creators = {}
    for i in items:
        cid = (i.get("creator_id") or "").lower()
        if cid and i.get("creator_upn"):
            creators[cid] = (i.get("creator_name") or "", (i.get("creator_upn") or "").lower())
    upn_name = {upn: nm for nm, upn in creators.values() if upn}
    pbi_caps = raw.get("pbi_capacities") or []
    pcap = {(c.get("id") or "").lower(): c for c in pbi_caps}

    orig_label = {}

    def pkey(u):
        u = (u or "").strip()
        lu = u.lower()
        if lu in creators:
            return creators[lu][1]
        orig_label.setdefault(lu, u)
        return lu

    def pkind(k):
        if k == own_sp:
            return "sre"
        if "@" in k:
            return "user"
        if GUID.match(k):
            return "app"
        if k in ("", "unknown", "none", "null"):
            return "unknown"
        return "system"

    def mask_upn(u):
        loc, _, dom = u.partition("@")
        return f"{loc[:1]}•••@{dom[:1]}•••" if dom else f"{loc[:1]}•••"

    def plabel(k):
        kind = pkind(k)
        if kind == "sre":
            return "SRE Agent (esta lectura)"
        if kind == "user":
            if show_ids:
                nm = upn_name.get(k)
                return f"{nm} · {k}" if nm else k
            return mask_upn(k)
        if kind == "app":
            return f"App {k}" if show_ids else f"App {k[:8]}…"
        if kind == "unknown":
            return "Sin identidad en el evento"
        return f"{orig_label.get(k, k)} (sistema)"

    def ev_cat(a, itt):
        al, t = (a or "").lower(), (itt or "").lower()
        if t == "llmplugin" or any(k in al for k in ("aiskill", "dataagent", "copilot", "openai", "aichat", "llm")):
            return "ai"
        if t in ("functionset", "appbackend", "graphqlapi", "userdatafunction") or any(k in al for k in ("functionset", "graphql", "userdatafunction")):
            return "api"
        if t.startswith(("ontology", "graph", "digitaltwin")) or any(k in al for k in ("ontology", "digitaloperations", "graph")):
            return "iq"
        if t in ("synapsenotebook", "notebook", "lakehouse", "environment", "sparkjobdefinition", "mlmodel", "mlexperiment") \
                or any(k in al for k in ("notebook", "spark", "lakehouse", "livy")):
            return "spark"
        if t.startswith(("kusto", "eventstream", "eventhouse", "reflex", "kql")) or any(k in al for k in ("kusto", "eventstream", "eventhouse", "kql")):
            return "rti"
        if t in ("datawarehouse", "warehouse", "sqlanalyticsendpoint", "sqldbnative", "sqldatabase", "mirroreddatabase") \
                or any(k in al for k in ("warehouse", "sqldatabase", "sqlendpoint")):
            return "db"
        if any(k in al for k in ("pipeline", "dataflow", "copyjob")):
            return "df"
        if t in ("report", "dataset", "model", "dashboard", "app", "semanticmodel") or any(k in al for k in ("report", "dataset", "dashboard", "refresh", "analyzedby")):
            return "pbi"
        return "other"

    def is_admin_act(a):
        return a.endswith(("AsAdmin", "ViaAdminApi")) or a in ("ExportActivityEvents", "GetDatasourceDetailsWithCredentialsAsync")

    # ---------------------------------------------------------------- activity events
    evs = []
    for e in raw.get("events") or []:
        t = P(e.get("t"))
        if not t or t < win0:
            continue
        k = pkey(e.get("u"))
        kind = "sre" if "AzureSREAgent" in (e.get("ua") or "") else pkind(k)
        a = e.get("a") or ""
        wsid = (e.get("wsid") or "").lower()
        it = e.get("it") or ""
        if not wsid and e.get("ws"):
            wsid = ws_by_name.get(e["ws"].lower(), "")
        if not wsid and it:
            wsid = item_ws.get(it.lower(), "")
        itt = e.get("itt") or item_type_by_name.get(it.lower(), "")
        if it.strip().lower() in ("unknown", "none", "null"):
            it = "(sin nombre en el registro)"
        work = kind in ("user", "app") and not is_admin_act(a)
        evs.append({"t": t, "k": k, "kind": kind, "a": a, "ws": wsid, "it": it, "itt": itt, "cat": ev_cat(a, itt), "work": work})
    work_ev = [e for e in evs if e["work"]]

    # ---------------------------------------------------------------- Spark / Livy sessions
    livy = []
    for s in raw.get("livy") or []:
        st, en, sub = P(s.get("start")), P(s.get("end")), P(s.get("submitted"))
        ref = st or sub
        if not ref or ref < win0:
            continue
        op = s.get("op") or ""
        livy.append({"ws": (s.get("ws") or "").lower(), "item": (s.get("item") if (s.get("item") or "").strip().lower() not in ("", "unknown", "none", "null") else "(sin nombre en el registro)"), "op": op, "user": pkey(s.get("user_id")),
                     "state": s.get("state") or "", "start": st, "end": en, "run": float(s.get("running_s") or 0),
                     "queued": float(s.get("queued_s") or 0), "sched": "schedul" in op.lower(), "pipe": "pipeline" in op.lower(),
                     "cap": (s.get("cap") or "").lower()})
    livy_total_s = sum(x["run"] for x in livy)

    # ---------------------------------------------------------------- cost (Azure Cost Management, real invoice meters)
    CATS = {
        "idle": ("Capacidad encendida sin consumo (Compute Pool)", "#d99a2b"),
        "ai": ("IA · Copilot y Data Agents", "#7b3fa0"),
        "spark": ("Spark y notebooks", "#117865"),
        "iq": ("Fabric IQ · Ontology y Graph", "#2f6fb3"),
        "rti": ("Real-Time Intelligence", "#c4532b"),
        "db": ("Warehouse y SQL", "#0f7c8c"),
        "pbi": ("Power BI", "#b8860b"),
        "df": ("Data Factory", "#5a7d1a"),
        "api": ("APIs y funciones", "#a23b72"),
        "onelake": ("Transacciones OneLake", "#7d8fa3"),
        "storage": ("Almacenamiento (GB-mes)", "#4f6378"),
        "overage": ("Exceso de capacidad (overage)", "#b42318"),
        "other": ("Otros medidores", "#9aa5b1"),
    }

    def meter_cat(m):
        ml = (m or "").lower()
        if "compute pool" in ml:
            return "idle"
        if "overage" in ml:
            return "overage"
        if "data stored" in ml or "storage" in ml:
            return "storage"
        if ml.startswith("onelake"):
            return "onelake"
        if any(k in ml for k in ("copilot", "ontology ai", "operations agents", "ml model")):
            return "ai"
        if "spark" in ml:
            return "spark"
        if ml.startswith(("ontology", "graph", "digital twin", "fabric planning")):
            return "iq"
        if any(k in ml for k in ("eventhouse", "eventstream", "activator", "rti ", "map ", "anomaly")):
            return "rti"
        if any(k in ml for k in ("data warehouse", "sql database", "sql db", "cosmos")):
            return "db"
        if "power bi" in ml:
            return "pbi"
        if any(k in ml for k in ("data movement", "data orchestration", "dataflow", "airflow", "dbt", "ssis", "vnet")):
            return "df"
        if "graphql" in ml or "user data functions" in ml:
            return "api"
        return "other"

    def short_meter(m):
        for suf in (" Capacity Usage CU", " OD On-Demand Usage CU", " Usage CU"):
            if m.endswith(suf):
                return m[: -len(suf)]
        return m

    d0 = win0.strftime("%Y%m%d")
    crow = [c for c in raw.get("cost_rows") or [] if str(c.get("date") or "") >= d0]
    CUR = next((c.get("currency") for c in crow if c.get("currency")), "USD")

    def money(v, d=2):
        return f"{fn(v, d)} {CUR}"

    arm_caps = raw.get("arm_capacities") or []
    cap_by_rid = {(c.get("id") or "").lower(): c for c in arm_caps}
    total_cost = sum(c["cost"] for c in crow)
    meters, cat_cost = {}, Counter()
    day_cat = defaultdict(Counter)
    cap_cost = Counter()
    for c in crow:
        cat = meter_cat(c["meter"])
        m = meters.setdefault(c["meter"], {"name": short_meter(c["meter"]), "cat": cat, "cost": 0.0, "qty": 0.0, "days": set()})
        m["cost"] += c["cost"]
        m["qty"] += c["qty"]
        if c["cost"] > 0.005:
            m["days"].add(c["date"])
        cat_cost[cat] += c["cost"]
        day_cat[c["date"]][cat] += c["cost"]
        cap_cost[c["rid"]] += c["cost"]
    focus_rid = cap_cost.most_common(1)[0][0] if cap_cost else (next((r for r, c in cap_by_rid.items() if (c.get("state") or "").lower() == "active"), "") if cap_by_rid else "")
    focus = cap_by_rid.get(focus_rid, {})
    focus_name = focus.get("name") or (focus_rid.rsplit("/", 1)[-1] if focus_rid else "—")
    focus_sku = focus.get("sku") or next((c.get("sku") for c in pbi_caps if (c.get("name") or "").lower() == focus_name.lower()), "") or ""
    m_cu = re.search(r"(\d+)", focus_sku or "")
    focus_cu = int(m_cu.group(1)) if m_cu and focus_sku.upper().startswith("F") else 0
    focus_region = (focus.get("location") or "").replace(" ", "").lower()
    focus_pbi = next((c for c in pbi_caps if (c.get("name") or "").lower() == focus_name.lower()), {})
    focus_pbi_id = (focus_pbi.get("id") or "").lower()

    prices = raw.get("prices") or []
    price_cu = next((p.get("price") for p in prices if p.get("region") == focus_region and p.get("type") == "Consumption"
                     and p.get("meter") == "Compute Pool Capacity Usage CU"), None)
    price_src = "Azure Retail Prices API (precio público pago por uso, " + (focus_region or "región") + ")"
    pool_rows = [c for c in crow if c["rid"] == focus_rid and meter_cat(c["meter"]) == "idle" and c["qty"] > 0]
    eff_price = (sum(c["cost"] for c in pool_rows) / sum(c["qty"] for c in pool_rows)) if pool_rows else None
    if price_cu is None and eff_price:
        price_cu, price_src = eff_price, "precio efectivo de la factura (coste ÷ CU-h del medidor Compute Pool)"
    price_cu = float(price_cu or 0)
    hourly = focus_cu * price_cu
    res = {}
    for p in prices:
        if p.get("region") == focus_region and p.get("type") == "Reservation" and "capacity" in (p.get("meter") or "").lower():
            yrs = 3 if "3" in (p.get("term") or "") else 1
            res[yrs] = float(p.get("price") or 0) / yrs

    # ---------------------------------------------------------------- uptime from Azure Activity Log (suspend/resume)
    def intervals_for(rid, state):
        evl = []
        for e in raw.get("activity_log") or []:
            t = P(e.get("t"))
            if t and (e.get("rid") or "").lower() == rid and (e.get("status") or "").lower() == "succeeded":
                evl.append((t, (e.get("op") or "").lower(), e.get("caller") or ""))
        evl.sort()
        out, cur, seen, ops = [], None, False, []
        for t, op, caller in evl:
            if op.endswith("/resume/action"):
                ops.append(("resume", t, caller))
                if cur is None:
                    cur = t
                seen = True
            elif op.endswith("/suspend/action"):
                ops.append(("suspend", t, caller))
                if cur is None and not seen:
                    cur = win0
                if cur is not None:
                    out.append((cur, t))
                cur = None
                seen = True
            elif op.endswith("/write"):
                ops.append(("write", t, caller))
        if cur is not None:
            out.append((cur, gen))
        basis = "Activity Log"
        if not evl:
            out = [(win0, gen)] if (state or "").lower() == "active" else []
            basis = "sin eventos de pausa/reanudación en el periodo"
        clipped = [(max(a, win0), min(b, gen)) for a, b in out if b > win0 and a < gen]
        return clipped, ops, basis

    focus_iv, focus_ops, uptime_basis = intervals_for(focus_rid, focus.get("state"))
    on_hours = sum((b - a).total_seconds() for a, b in focus_iv) / 3600
    uptime = on_hours / win_hours
    on_day = Counter()
    for a, b in focus_iv:
        d = a
        while d < b:
            nx = min(b, floor_day(d) + timedelta(days=1))
            on_day[d.strftime("%Y%m%d")] += (nx - d).total_seconds() / 3600
            d = nx
    callers_resume = Counter(pkey(c) for o, t, c in focus_ops if o == "resume")
    callers_suspend = Counter(pkey(c) for o, t, c in focus_ops if o == "suspend")
    susp_times = [t for o, t, c in focus_ops if o == "suspend" and t >= win0]
    auto_suspend = bool(callers_suspend) and all(pkind(k) == "app" for k in callers_suspend)

    # ---------------------------------------------------------------- daily reconciliation: provisioned vs billed vs consumed
    day_cu = defaultdict(lambda: {"billed": 0.0, "pool": 0.0, "cost": 0.0})
    for c in crow:
        if c["rid"] != focus_rid:
            continue
        dc = day_cu[c["date"]]
        dc["cost"] += c["cost"]
        cat = meter_cat(c["meter"])
        if cat != "storage":
            dc["billed"] += c["qty"]
            if cat == "idle":
                dc["pool"] += c["qty"]
    all_days = []
    d = win0
    while d <= gen:
        all_days.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    last_cost_day = max((k for k, v in day_cu.items() if v["cost"] > 0.05), default=None)
    daily = []
    for k in all_days:
        dc = day_cu.get(k, {"billed": 0.0, "pool": 0.0, "cost": 0.0})
        oh = on_day.get(k, 0.0)
        prov = focus_cu * oh
        consumed = max(dc["billed"] - dc["pool"], 0)
        daily.append({"date": k, "on_h": oh, "prov": prov, "billed": dc["billed"], "pool": dc["pool"], "consumed": consumed,
                      "util": (consumed / dc["billed"]) if dc["billed"] > 0.5 else None, "cost": dc["cost"],
                      "ratio": (dc["billed"] / prov) if prov > 0.5 else None, "lag": bool(last_cost_day and k > last_cost_day)})
    cu_billed = sum(x["billed"] for x in daily)
    cu_pool = sum(x["pool"] for x in daily)
    cu_consumed = max(cu_billed - cu_pool, 0)
    util_all = cu_consumed / cu_billed if cu_billed else 0
    cu_cost_focus = sum(c["cost"] for c in crow if c["rid"] == focus_rid and meter_cat(c["meter"]) != "storage")
    idle_cost = cat_cost.get("idle", 0.0)
    consumption_cost = total_cost - idle_cost - cat_cost.get("storage", 0.0)
    billed_days = [x for x in daily if x["cost"] > 0.05 and x["on_h"] > 0.5 and not x["lag"]]
    match_days = [x for x in billed_days if x["consumed"] < 0.02 * max(x["prov"], 1)]
    match_err = max((abs(x["ratio"] - 1) for x in match_days if x["ratio"]), default=None)
    smoothed_extra = sum(max(x["billed"] - x["prov"], 0) for x in billed_days)
    lowuse_days = [x for x in billed_days if x["consumed"] < 0.02 * max(x["prov"], 1)]
    lowuse_cost = sum(x["cost"] for x in lowuse_days)
    on_billed_hours = sum(x["on_h"] for x in billed_days)

    # ---------------------------------------------------------------- on vs used: idle tail per on-interval (activity log + Livy)
    work_times = sorted(e["t"] for e in work_ev if not focus_pbi_id or not e["ws"] or ws_cap.get(e["ws"], focus_pbi_id) in (focus_pbi_id, ""))
    livy_focus = [x for x in livy if x["start"] and (not focus_pbi_id or x["cap"] in (focus_pbi_id, ""))]
    import bisect
    runs = []
    for a, b in focus_iv:
        covered = bool(act0) and a >= act0
        ongoing = b >= gen - timedelta(minutes=1) and (focus.get("state") or "").lower() == "active"
        i0, i1 = bisect.bisect_left(work_times, a), bisect.bisect_right(work_times, b)
        acts = work_times[i0:i1]
        spans = [(max(x["start"], a), min(x["end"] or b, b)) for x in livy_focus if x["start"] < b and (x["end"] or b) > a]
        last_cands = ([acts[-1]] if acts else []) + [s[1] for s in spans]
        first_cands = ([acts[0]] if acts else []) + [s[0] for s in spans]
        last = max(last_cands) if last_cands else None
        first = min(first_cands) if first_cands else None
        hours, h, busy = [], a, 0.0
        while h < b:
            nx = min(h + timedelta(hours=1), b)
            n = bisect.bisect_left(work_times, nx) - bisect.bisect_left(work_times, h)
            sp = any(s0 < nx and s1 > h for s0, s1 in spans)
            hours.append((h, nx, n, sp))
            if n or sp:
                busy += (nx - h).total_seconds() / 3600
            h = nx
        dur = (b - a).total_seconds() / 3600
        tail = ((b - last).total_seconds() / 3600 if last else dur) if covered and not ongoing else None
        runs.append({"a": a, "b": b, "dur": dur, "covered": covered, "ongoing": ongoing, "first": first, "last": last,
                     "n": len(acts), "spark_h": sum((s1 - s0).total_seconds() for s0, s1 in spans) / 3600, "spans": spans,
                     "hours": hours, "idle_h": (dur - busy) if covered else None, "tail": tail})
    BUFFER_H = 1.0
    cov_runs = [r for r in runs if r["covered"] and not r["ongoing"]]
    tail_h = sum(r["tail"] or 0 for r in cov_runs)
    tail_save_h = sum(max((r["tail"] or 0) - BUFFER_H, 0) for r in cov_runs)
    tail_save = tail_save_h * hourly
    idle_cov_h = sum(r["idle_h"] or 0 for r in cov_runs)
    cov_on_h = sum(r["dur"] for r in cov_runs)
    cov_days = max(act_days, 1)
    per_month = 30.0 / cov_days
    whatif = []
    for H in range(17, 24):
        saved, conflicts, days_hit = 0.0, 0, 0
        for r in cov_runs:
            cut = floor_day(r["b"]) + timedelta(hours=H)
            if r["b"] <= cut:
                continue
            st = max(r["a"], cut)
            saved += (r["b"] - st).total_seconds() / 3600
            days_hit += 1
            if (r["last"] and r["last"] > cut):
                conflicts += 1
        whatif.append({"hour": H, "saved_h": saved, "save": saved * hourly, "days": days_hit, "conflicts": conflicts})
    safe = [w for w in whatif if w["conflicts"] == 0 and w["saved_h"] > 0]
    best_safe = max(safe, key=lambda w: w["saved_h"]) if safe else None
    suspend_hour_med = sorted(t.hour + t.minute / 60 for t in susp_times)[len(susp_times) // 2] if susp_times else None

    # ---------------------------------------------------------------- commitments & size (real public prices + real hours)
    payg_year_cu = price_cu * 8760
    breakeven = {y: (v / payg_year_cu) for y, v in res.items()} if payg_year_cu else {}
    cost_src = sources.get("cost") or {}
    cost_ok = cost_src.get("status") == "ok"
    cost_http = cost_src.get("http")
    cost_why = ("Azure Cost Management limitó las peticiones (HTTP 429). Es temporal: vuelve a pedir el informe en unos minutos." if cost_http == 429 else
                "La app no tiene permiso de lectura de costes (HTTP 403): asigna Cost Management Reader en la suscripción." if cost_http in (401, 403) else
                f"Azure Cost Management no respondió (HTTP {cost_http or 'sin respuesta'}). Vuelve a pedir el informe en unos minutos.")
    annual_payg_cu = cu_cost_focus * 365.0 / max(days_n, 1) if cost_ok else hourly * on_hours * 365.0 / max(days_n, 1)
    annual_res = {y: focus_cu * v for y, v in res.items()}
    avg_cu_on = (cu_consumed / on_billed_hours) if on_billed_hours else 0
    peak_day = max(billed_days, key=lambda x: x["consumed"] / max(x["on_h"], 0.1), default=None)
    peak_day_avg = (peak_day["consumed"] / max(peak_day["on_h"], 0.1)) if peak_day else 0
    sizes = []
    s = focus_cu // 2
    while cost_ok and s >= 2 and len(sizes) < 3:
        sizes.append({"sku": f"F{s}", "cu": s, "save_month": on_billed_hours * (focus_cu - s) * price_cu * 30.0 / max(days_n, 1),
                      "peak_load": peak_day_avg / s, "avg_load": avg_cu_on / s})
        s //= 2

    # ---------------------------------------------------------------- Spark notebooks
    nb = {}
    for x in livy:
        key = (x["ws"], x["item"])
        n = nb.setdefault(key, {"ws": x["ws"], "item": x["item"], "sessions": 0, "sched": 0, "pipe": 0, "failed": 0, "run": 0.0,
                                "queued": 0.0, "users": Counter(), "first": None, "last": None})
        n["sessions"] += 1
        n["sched"] += x["sched"]
        n["pipe"] += x["pipe"]
        n["failed"] += x["state"].lower() == "failed"
        n["run"] += x["run"]
        n["queued"] += x["queued"]
        n["users"][x["user"]] += 1
        if x["start"]:
            n["first"] = min(n["first"] or x["start"], x["start"])
            n["last"] = max(n["last"] or x["start"], x["start"])
    spark_cost = cat_cost.get("spark", 0.0)
    nb_list = sorted(nb.values(), key=lambda n: -n["run"])
    for n in nb_list:
        n["share"] = n["run"] / livy_total_s if livy_total_s else 0
        n["cost"] = spark_cost * n["share"]
    livy_failed = [x for x in livy if x["state"].lower() == "failed"]

    # ---------------------------------------------------------------- chargeback by workspace (real meter cost x real usage driver)
    DRIVER = {"spark": "segundos de ejecución Spark (Livy)", "ai": "consultas IA/Copilot/Data Agent del log de actividad",
              "iq": "operaciones Ontology/Graph del log de actividad", "rti": "operaciones Eventhouse/Eventstream/KQL",
              "db": "operaciones Warehouse/SQL", "pbi": "operaciones Power BI", "df": "operaciones de pipelines/dataflows",
              "api": "invocaciones de funciones/APIs"}
    drv = defaultdict(Counter)
    for x in livy:
        drv["spark"][x["ws"] or "?"] += x["run"]
    for e in work_ev:
        if e["cat"] in DRIVER and e["cat"] != "spark":
            drv[e["cat"]][e["ws"] or "?"] += 1
    alloc = defaultdict(Counter)
    unassigned = Counter()
    for cat, cost in cat_cost.items():
        if cat == "idle":
            continue
        w = drv.get(cat)
        tot = sum(w.values()) if w else 0
        if cat in DRIVER and tot > 0:
            for ws, v in w.items():
                alloc[ws][cat] += cost * v / tot
        else:
            unassigned[cat] += cost
    direct_ws = {ws: sum(c.values()) for ws, c in alloc.items()}
    direct_total = sum(v for ws, v in direct_ws.items() if ws != "?")
    ws_ev = Counter(e["ws"] for e in work_ev if e["ws"])
    ws_ai = Counter(e["ws"] for e in work_ev if e["ws"] and e["cat"] == "ai")
    ws_spark = Counter()
    for x in livy:
        ws_spark[x["ws"]] += x["run"] / 3600
    ws_items = Counter((i.get("ws") or "").lower() for i in items)
    ws_types = defaultdict(Counter)
    ws_upd = {}
    for i in items:
        w = (i.get("ws") or "").lower()
        ws_types[w][i.get("type") or "?"] += 1
        u = P(i.get("updated"))
        if u and u.year > 2000:
            ws_upd[w] = max(ws_upd.get(w, u), u)
    cb = []
    for w in workspaces:
        wid = (w.get("id") or "").lower()
        cid = ws_cap.get(wid, "")
        d_ = direct_ws.get(wid, 0.0)
        idle_share = idle_cost * (d_ / direct_total) if direct_total else 0.0
        cb.append({"id": wid, "name": ws_name.get(wid) or w.get("name") or wid, "type": w.get("type") or "", "cap": (pcap.get(cid) or {}).get("name") or cid[:8],
                   "sku": (pcap.get(cid) or {}).get("sku") or "", "items": ws_items.get(wid, 0), "events": ws_ev.get(wid, 0),
                   "ai": ws_ai.get(wid, 0), "spark_h": ws_spark.get(wid, 0.0), "direct": d_, "idle": idle_share,
                   "total": d_ + idle_share, "by_cat": alloc.get(wid, Counter()), "updated": ws_upd.get(wid),
                   "types": ws_types.get(wid, Counter())})
    cb.sort(key=lambda r: (-r["total"], -r["events"], r["name"].lower()))
    no_ws_cost = sum(alloc.get("?", Counter()).values())
    unassigned_total = sum(unassigned.values())
    paid_caps = {(c.get("id") or "").lower() for c in pbi_caps if (c.get("sku") or "").upper().startswith("F") and (c.get("state") or "").lower() == "active"}
    idle_ws = [r for r in cb if r["events"] == 0 and r["spark_h"] == 0 and ws_cap.get(r["id"]) in paid_caps and r["type"] != "Personal"]

    # ---------------------------------------------------------------- who: principals, items, heatmap
    princ = {}
    for e in evs:
        p = princ.setdefault(e["k"], {"k": e["k"], "kind": e["kind"], "events": 0, "work": 0, "days": set(), "cats": Counter(),
                                      "acts": Counter(), "items": Counter(), "ws": Counter(), "first": e["t"], "last": e["t"]})
        p["events"] += 1
        p["work"] += e["work"]
        p["days"].add(e["t"].date())
        p["cats"][e["cat"]] += 1
        p["acts"][e["a"]] += 1
        if e["it"]:
            p["items"][e["it"]] += 1
        if e["ws"]:
            p["ws"][e["ws"]] += 1
        p["first"], p["last"] = min(p["first"], e["t"]), max(p["last"], e["t"])
    for x in livy:
        p = princ.setdefault(x["user"], {"k": x["user"], "kind": pkind(x["user"]), "events": 0, "work": 0, "days": set(), "cats": Counter(),
                                         "acts": Counter(), "items": Counter(), "ws": Counter(), "first": x["start"] or gen, "last": x["start"] or gen})
        p.setdefault("spark_h", 0.0)
        p["spark_h"] = p.get("spark_h", 0.0) + x["run"] / 3600
        p["nb"] = p.get("nb", 0) + 1
    humans = sorted([p for p in princ.values() if p["kind"] in ("user", "app")], key=lambda p: -(p["work"] + p.get("nb", 0)))
    nonhuman = sorted([p for p in princ.values() if p["kind"] not in ("user", "app")], key=lambda p: -p["events"])
    item_use = {}
    for e in work_ev:
        if not e["it"]:
            continue
        key = (e["ws"], e["it"])
        r = item_use.setdefault(key, {"ws": e["ws"], "it": e["it"], "itt": e["itt"], "n": 0, "cats": Counter(), "users": set(), "last": e["t"]})
        r["n"] += 1
        r["cats"][e["cat"]] += 1
        r["users"].add(e["k"])
        r["last"] = max(r["last"], e["t"])
    top_items = sorted(item_use.values(), key=lambda r: -r["n"])[:15]
    heat = [[0] * 24 for _ in range(7)]
    for e in work_ev:
        heat[e["t"].weekday()][e["t"].hour] += 1
    heat_max = max((max(r) for r in heat), default=0)
    cat_events = Counter(e["cat"] for e in work_ev)

    # ---------------------------------------------------------------- inventory & governance
    item_types = Counter(i.get("type") or "?" for i in items)
    stale_cut = gen - timedelta(days=90)
    stale_items = [i for i in items if (P(i.get("updated")) or gen) < stale_cut]
    stale_types = Counter(i.get("type") or "?" for i in stale_items)
    refs = []
    for r in raw.get("refreshables") or []:
        ls = P(r.get("last_start"))
        age = (gen - ls).days if ls else None
        status = (r.get("last_status") or "").lower()
        level = "crit" if status == "failed" else ("warn" if (age is not None and age > 60) else "ok")
        err = ""
        if r.get("last_error"):
            m = re.search(r'"code"\s*:\s*"([^"]+)"', str(r["last_error"]))
            err = m.group(1) if m else str(r["last_error"])[:60]
        _rws = r.get("ws") or ""
        _rid = ws_by_name.get(_rws.lower(), "")
        if _rid and not show_ids:
            _rws = ws_name.get(_rid) or _rws
        if "@" in _rws and not show_ids:
            _l, _, _d = _rws.partition("@")
            _rws = f"Personal · {_l[:1]}•••@{_d[:1]}•••"
        refs.append({"name": r.get("name") or "", "ws": _rws, "kind": r.get("kind") or "", "type": r.get("last_type") or "",
                     "last": ls, "age": age, "status": {"completed": "Correcto", "failed": "Fallido", "disabled": "Deshabilitado", "unknown": "En curso"}.get(status, r.get("last_status") or "—"),
                     "sched": bool(r.get("sched_enabled")), "level": level, "err": err})
    refs.sort(key=lambda r: ({"crit": 0, "warn": 1, "ok": 2}[r["level"]], -(r["age"] or 0)))
    ref_failed = [r for r in refs if r["level"] == "crit"]
    ref_stale = [r for r in refs if r["level"] == "warn"]
    ts = raw.get("tenant_settings") or []
    TS_RULES = [
        ("copilot, ai agents and other ai experiences powered by azure openai", "Habilita Copilot y Data Agents: es el origen del medidor «Copilot and AI»."),
        ("designated as fabric copilot capacities", "Permite separar el consumo de IA en una capacidad dedicada y repercutirlo con exactitud."),
        ("users can create fabric items", "Quién puede crear items que consumen CU en capacidades de pago."),
        ("service principals can access read-only admin apis", "Necesario para este informe (lectura de auditoría e inventario)."),
        ("show user data in the fabric capacity metrics", "Permite ver usuarios en Capacity Metrics para chargeback por persona."),
        ("standalone, cross-item power bi copilot", "Experiencia Copilot transversal: más consumo de IA posible."),
        ("operations agents", "Agentes de operaciones: nuevos medidores de IA."),
        ("publish to web", "Riesgo de exposición pública de informes."),
        ("guest users can access microsoft fabric", "Invitados consumiendo capacidad del tenant."),
        ("users can access data stored in onelake with apps external", "Lecturas externas de OneLake generan transacciones facturables."),
    ]
    ts_rows = []
    for key, why in TS_RULES:
        for s_ in ts:
            if key in (s_.get("title") or "").lower():
                scope = ("Grupos: " + ", ".join(s_.get("groups") or [])) if s_.get("groups") else ("Toda la organización" if s_.get("enabled") else "—")
                ts_rows.append({"title": s_.get("title"), "group": s_.get("group"), "enabled": s_.get("enabled"), "scope": scope, "why": why})
                break
    ts_enabled = sum(1 for s_ in ts if s_.get("enabled"))
    ol = raw.get("onelake") or []
    ol_ok = [o for o in ol if o.get("http") == 200]
    ol_bytes = sum(o.get("bytes") or 0 for o in ol_ok)
    ws_on_cap = Counter(ws_cap.values())
    caps_tbl = []
    for c in pbi_caps:
        cid = (c.get("id") or "").lower()
        arm = next((a for a in arm_caps if (a.get("name") or "").lower() == (c.get("name") or "").lower()), None)
        cost = cap_cost.get((arm or {}).get("id", "").lower(), 0.0) if arm else 0.0
        sku = c.get("sku") or ""
        st = c.get("state") or ""
        nws = ws_on_cap.get(cid, 0)
        if arm and not (arm.get("tags") or {}):
            tagnote = "sin etiquetas"
        elif arm:
            tagnote = ", ".join(f"{k}={v}" for k, v in (arm.get("tags") or {}).items())[:60]
        else:
            tagnote = "no es recurso Azure"
        if sku.upper().startswith("FT"):
            find, lvl = "Capacidad de prueba (trial)", "info"
        elif sku.upper().startswith("PP"):
            find, lvl = "Premium por usuario (licencia, no CU)", "neutral"
        elif st.lower() in ("suspended", "paused") and nws == 0:
            find, lvl = "Pausada y sin workspaces: candidata a eliminar", "warn"
        elif st.lower() in ("suspended", "paused"):
            find, lvl = "Pausada (sin coste de cómputo)", "ok"
        elif cid == focus_pbi_id:
            find, lvl = f"Encendida {pc(uptime, 0)} del periodo · uso {pc(util_all, 0)}", "warn" if util_all < 0.3 else "ok"
        else:
            find, lvl = "Activa", "ok"
        mcu = re.search(r"(\d+)", sku)
        caps_tbl.append({"name": c.get("name") or "", "sku": sku, "state": st, "region": c.get("region") or "", "admins": c.get("admins"),
                         "ws": nws, "items": sum(1 for i in items if (i.get("cap") or "").lower() == cid), "cost": cost, "tags": tagnote,
                         "finding": find, "lvl": lvl, "arm": bool(arm), "rg": (arm or {}).get("rg") or "",
                         "hourly_if_on": (int(mcu.group(1)) * price_cu) if (mcu and sku.upper().startswith("F") and not sku.upper().startswith("FT")) else None})
    paused_empty = [c for c in caps_tbl if c["lvl"] == "warn" and c["state"].lower() in ("suspended", "paused")]
    trials = [c for c in caps_tbl if c["sku"].upper().startswith("FT")]
    untagged = [c for c in caps_tbl if c["arm"] and c["tags"] == "sin etiquetas"]
    cm_ws = next((w for w in workspaces if "capacity metrics" in (w.get("name") or "").lower()), None)
    cm_items = [i for i in items if cm_ws and (i.get("ws") or "").lower() == (cm_ws.get("id") or "").lower()]
    cm_installed = bool(cm_ws) and any((i.get("type") or "") in ("SemanticModel", "App") for i in cm_items)

    # ================================================================== v5 STYLE (same visual world as v4)
    CSS = """
:root{--ink:#0f1f2e;--muted:#4b5e71;--line:#d5e2ec;--paper:#f3f7fa;--panel:#fff;--teal:#117865;--teal-deep:#0b5345;
--teal-soft:#e6f4f1;--on:#cfe9e3;--idle:#d99a2b;--idle-soft:#fdf1dc;--spark:#6a3d9a;--amber:#a14306;--amber-soft:#fef0c7;
--crit:#b42318;--crit-soft:#fee4e2;--ok:#18794e;--ok-soft:#e8f7ef;--info:#1d5c8f;--info-soft:#e6f0f9;--r:10px;
--serif:"Palatino Linotype",Palatino,Georgia,serif;--sans:"Aptos","Segoe UI",-apple-system,sans-serif;--mono:"Cascadia Mono",Consolas,monospace}
*{box-sizing:border-box}
html{-webkit-text-size-adjust:100%;scroll-behavior:smooth;scroll-padding-top:64px}
body{margin:0;background:var(--paper);color:var(--ink);font:15px/1.5 var(--sans);font-variant-numeric:tabular-nums}
.wrap{max-width:1240px;margin:0 auto;padding-left:28px;padding-right:28px}
header.top{background:var(--teal-deep);color:#fff;padding:34px 0 28px}
header.top h1{font-family:var(--serif);font-weight:700;font-size:clamp(28px,3.4vw,40px);line-height:1.12;margin:0 0 10px;letter-spacing:-.01em;text-wrap:balance}
header.top p.lede{margin:0 0 18px;max-width:78ch;color:#d5ece6;font-size:16px}
.chips{display:flex;flex-wrap:wrap;gap:8px;margin:0;padding:0;list-style:none}
.chips li{background:rgba(255,255,255,.1);border:1px solid rgba(255,255,255,.2);border-radius:999px;padding:4px 12px;font-size:13px;color:#eef8f5}
.chips li b{font-weight:600;color:#fff}
nav.toc{position:sticky;top:0;z-index:5;background:rgba(243,247,250,.96);backdrop-filter:blur(6px);border-bottom:1px solid var(--line)}
nav.toc ol{display:flex;gap:4px;margin:0 auto;padding:8px 28px;list-style:none;overflow-x:auto;max-width:1240px;scrollbar-width:thin}
nav.toc a{display:block;white-space:nowrap;padding:6px 8px;border-radius:6px;color:var(--muted);text-decoration:none;font-size:13px;font-weight:600}
nav.toc a:hover{background:#e3edf2;color:var(--ink)}
main{padding:28px 0 56px}
section{margin:0 0 40px}
h2{font-family:var(--serif);font-size:26px;line-height:1.2;margin:0 0 6px;text-wrap:balance}
h3{font-size:15px;margin:0 0 10px}
p.sub{margin:0 0 16px;color:var(--muted);max-width:84ch}
.panel{background:var(--panel);border:1px solid var(--line);border-radius:var(--r);padding:22px}
.panel+.panel,.panel+.tbl-wrap,.tbl-wrap+.panel,.tbl-wrap+.tbl-wrap,.split+.panel,.panel+.split,.split+.tbl-wrap{margin-top:18px}
.hero{display:grid;grid-template-columns:minmax(240px,330px) 1fr;gap:32px;align-items:start}
.total-label{font-size:13px;color:var(--muted);margin:0}
.total-figure{font-family:var(--serif);font-size:clamp(40px,5vw,56px);font-weight:700;line-height:1.05;margin:4px 0 6px;color:var(--teal-deep);white-space:nowrap}
.total-figure small{font-size:.42em;font-weight:600;margin-left:6px;color:var(--muted);letter-spacing:.02em}
.total-meta{margin:0;color:var(--muted);font-size:14px}
.verdict{font-family:var(--serif);font-size:clamp(19px,2vw,23px);line-height:1.35;margin:0 0 16px;max-width:60ch}
.verdict b{color:var(--amber)}
.stack{display:flex;height:24px;border-radius:6px;overflow:hidden;background:#e9eff3;margin:0 0 14px}
.stack span{display:block;height:100%;transform-origin:left;animation:grow .8s cubic-bezier(.2,.7,.2,1) both}
@keyframes grow{from{transform:scaleX(0)}to{transform:scaleX(1)}}
.legend{display:grid;grid-template-columns:repeat(3,minmax(0,1fr));gap:14px;margin:0;padding:0;list-style:none}
.legend li{font-size:13px;color:var(--muted)}
.sw{display:inline-block;width:10px;height:10px;border-radius:2px;margin-right:6px;vertical-align:0}
.legend strong{display:block;font-size:19px;color:var(--ink);margin-top:2px}
.facts{display:flex;flex-wrap:wrap;gap:10px 30px;margin:20px 0 0;padding:16px 0 0;border-top:1px solid var(--line);list-style:none}
.facts li{font-size:13px;color:var(--muted)}.facts b{display:block;color:var(--ink);font-size:17px}
.save-strip{display:flex;flex-wrap:wrap;gap:12px 36px;align-items:baseline;background:var(--teal-deep);color:#e6f4f1;border-radius:var(--r);padding:18px 22px;margin:0 0 16px}
.save-strip .big{font-family:var(--serif);font-size:32px;font-weight:700;color:#fff;line-height:1}
.save-strip p{margin:0;font-size:14px;max-width:70ch}
.actions{list-style:none;margin:0;padding:0;display:grid;gap:10px;counter-reset:a}
.actions li{display:grid;grid-template-columns:36px minmax(0,1fr) 170px;gap:6px 16px;align-items:start;background:#fff;border:1px solid var(--line);border-radius:var(--r);padding:16px 18px}
.actions li::before{counter-increment:a;content:counter(a);display:grid;place-items:center;width:28px;height:28px;border-radius:50%;background:var(--teal-soft);color:var(--teal-deep);font-weight:700;font-size:13px;grid-row:1/3}
.actions h3{margin:0 0 4px;font-size:16px}
.actions p{margin:0;font-size:14px;color:var(--muted)}
.actions .ev{grid-column:2/3;font-size:13px;color:#33495c;margin-top:6px}
.actions .ev code{font-family:var(--mono);font-size:12px;background:#f1f5f8;border-radius:4px;padding:1px 5px}
.actions .val{grid-column:3;grid-row:1/3;text-align:right}
.actions .val b{display:block;font-family:var(--serif);font-size:21px;color:var(--teal-deep);white-space:nowrap}
.actions .val span{font-size:12px;color:var(--muted)}
.notice{display:flex;gap:14px;align-items:flex-start;background:var(--info-soft);border:1px solid #c7dbee;border-radius:var(--r);padding:14px 18px;margin:0 0 18px;font-size:14px}
.notice.warn{background:var(--amber-soft);border-color:#f3d48a}
.notice b{display:block;margin-bottom:2px}.notice p{margin:0}
.chart{overflow-x:auto;-webkit-overflow-scrolling:touch}
.chart svg{display:block;min-width:720px;width:100%;height:auto}
.chart text{font-family:var(--sans);fill:#4b5e71;font-size:11px}
.chart .lbl{font-size:11px;fill:#33495c}
.keys{display:flex;flex-wrap:wrap;gap:8px 18px;margin:12px 0 0;padding:0;list-style:none;font-size:13px;color:var(--muted)}
.tbl-wrap{overflow-x:auto;border:1px solid var(--line);border-radius:var(--r);background:var(--panel)}
table{width:100%;border-collapse:collapse;font-size:14px}
th,td{padding:10px 12px;text-align:left;border-bottom:1px solid var(--line);vertical-align:top}
thead th{background:#f6faf9;font-size:12px;font-weight:600;color:var(--muted);white-space:nowrap;position:sticky;top:0}
tbody tr:hover{background:#f4fbf9}
tfoot td{font-weight:700;background:#f6faf9;border-bottom:0}
td.num,th.num{text-align:right;white-space:nowrap}
table.dense{font-size:13px}table.dense th,table.dense td{padding:8px 9px}
.sortbtn{all:unset;cursor:pointer;display:inline-flex;gap:4px;align-items:center;border-radius:4px}
.sortbtn::after{content:"↕";opacity:.35;font-size:11px}
th[aria-sort=ascending] .sortbtn::after{content:"↑";opacity:1}
th[aria-sort=descending] .sortbtn::after{content:"↓";opacity:1}
.id{font-family:var(--mono);font-size:12px;color:#2b4458}
.cell-strong{font-weight:600}.cell-sub{display:block;font-size:12px;color:var(--muted)}
.nw{white-space:nowrap}.muted{color:var(--muted)}
.mini{display:flex;width:120px;height:8px;border-radius:4px;overflow:hidden;background:#e9eff3;margin-top:6px}
.mini span{display:block;height:100%}
.pill{display:inline-block;border-radius:999px;padding:2px 10px;font-size:12px;font-weight:600;white-space:nowrap}
.pill.ok{background:var(--ok-soft);color:var(--ok)}.pill.warn{background:var(--amber-soft);color:var(--amber)}
.pill.crit{background:var(--crit-soft);color:var(--crit)}.pill.info{background:var(--info-soft);color:var(--info)}
.pill.neutral{background:#eef2f5;color:#3d5163}
.split{display:grid;grid-template-columns:minmax(0,1fr) minmax(0,1fr);gap:18px;align-items:start}
.split>*{margin-top:0!important;min-width:0}
.split.wide{grid-template-columns:minmax(0,3fr) minmax(0,2fr)}
.bars{list-style:none;margin:0;padding:0;display:grid;gap:12px}
.bars li{display:grid;grid-template-columns:minmax(0,1fr) auto;gap:4px 12px;font-size:14px}
.bars .track{grid-column:1/-1;height:8px;border-radius:4px;background:#e9eff3;overflow:hidden}
.bars .fill{height:100%;border-radius:4px}
.kv{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:14px;margin:0;padding:0;list-style:none}
.kv.types{grid-template-columns:repeat(6,minmax(0,1fr))}
.kv li{background:#fff;border:1px solid var(--line);border-radius:var(--r);padding:14px 16px;font-size:13px;color:var(--muted)}
.kv b{display:block;font-family:var(--serif);font-size:24px;color:var(--ink);line-height:1.15;margin-top:2px}
.heat td{padding:0;border:0;width:3.4%;height:22px}
.heat th{font-size:11px;font-weight:600;color:var(--muted);padding:2px 6px;border:0;background:none;position:static}
.heat td span{display:block;height:20px;margin:1px;border-radius:3px}
.toolbar{display:flex;flex-wrap:wrap;gap:10px;align-items:center;margin:0 0 12px}
.btn{font:inherit;font-size:13px;font-weight:600;border:1px solid var(--teal);color:var(--teal-deep);background:#fff;border-radius:8px;padding:7px 13px;cursor:pointer;text-decoration:none;display:inline-block}
.btn:hover{background:var(--teal-soft)}
.qs{display:grid;grid-template-columns:1fr 1fr;gap:12px}
.qs article{background:#fff;border:1px solid var(--line);border-radius:var(--r);padding:16px 18px}
.qs h3{font-size:14px;color:var(--teal-deep);margin:0 0 10px}
.qs ul{list-style:none;margin:0;padding:0;display:grid;gap:8px}
.qs li{display:grid;grid-template-columns:1fr auto;gap:10px;align-items:start;font-size:14px}
.qs li button{font:inherit;font-size:12px;border:1px solid var(--line);background:#f6faf9;border-radius:6px;padding:3px 9px;cursor:pointer;color:var(--muted)}
.method{display:grid;grid-template-columns:1fr 1fr;gap:20px;font-size:14px}
.method ul{margin:0;padding-left:18px}.method li{margin:0 0 6px}
footer{color:var(--muted);font-size:12px;padding:20px 0 40px;border-top:1px solid var(--line)}
:focus-visible{outline:3px solid #f5c46b;outline-offset:2px}
@media (max-width:900px){.wrap{padding-left:16px;padding-right:16px}nav.toc ol{padding:8px 16px}
.hero,.split,.split.wide,.method,.qs{grid-template-columns:minmax(0,1fr)}.legend{grid-template-columns:repeat(2,minmax(0,1fr))}
.kv,.kv.types{grid-template-columns:repeat(2,minmax(0,1fr))}
.actions li{grid-template-columns:32px minmax(0,1fr)}.actions .val{grid-column:2;grid-row:auto;text-align:left}
.actions .ev{grid-column:2}}
@media (prefers-reduced-motion:reduce){.stack span{animation:none}html{scroll-behavior:auto}}
@media print{body{background:#fff}nav.toc,.toolbar,.qs button{display:none}header.top{background:#fff;color:var(--ink);border-bottom:2px solid var(--teal-deep)}
header.top p.lede,.chips li{color:var(--ink)}.save-strip{background:#fff;color:var(--ink);border:2px solid var(--teal-deep)}.save-strip .big{color:var(--teal-deep)}
.panel,.tbl-wrap,.actions li{break-inside:avoid}thead th{position:static}.chart svg{min-width:0}}
"""

    JS = """
(function(){
  document.querySelectorAll('table[data-sortable]').forEach(function(table){
    var ths=table.querySelectorAll('thead th[data-sort]');
    ths.forEach(function(th){
      var btn=th.querySelector('.sortbtn'); if(!btn) return;
      btn.addEventListener('click',function(){
        var dir=th.getAttribute('aria-sort')==='descending'?'ascending':'descending';
        ths.forEach(function(o){o.removeAttribute('aria-sort');}); th.setAttribute('aria-sort',dir);
        var col=+th.dataset.col, num=th.dataset.sort==='num', tb=table.tBodies[0], rows=[].slice.call(tb.rows);
        rows.sort(function(a,b){
          var x=a.cells[col].dataset.v||a.cells[col].textContent, y=b.cells[col].dataset.v||b.cells[col].textContent;
          if(num){x=parseFloat(x)||0;y=parseFloat(y)||0;return dir==='ascending'?x-y:y-x;}
          return dir==='ascending'?x.localeCompare(y,'es'):y.localeCompare(x,'es');
        });
        rows.forEach(function(r){tb.appendChild(r);});
      });
    });
  });
  function dl(name,text){
    var blob=new Blob(['\\ufeff'+text],{type:'text/csv;charset=utf-8'});
    var a=document.createElement('a'); a.href=URL.createObjectURL(blob); a.download=name;
    document.body.appendChild(a); a.click(); setTimeout(function(){URL.revokeObjectURL(a.href); a.remove();},500);
  }
  document.querySelectorAll('[data-csv]').forEach(function(b){
    b.addEventListener('click',function(){ var s=document.getElementById(b.dataset.csv); if(s) dl(b.dataset.name, s.textContent); });
  });
  document.querySelectorAll('[data-copy]').forEach(function(b){
    b.addEventListener('click',function(){
      var t=b.dataset.copy, o=b.textContent, done=function(){b.textContent='Copiada';setTimeout(function(){b.textContent=o;},1500);};
      if(navigator.clipboard) navigator.clipboard.writeText(t).then(done,done); else done();
    });
  });
})();
"""

    def th(label, col=None, kind=None, cls=""):
        c = f' class="{cls}"' if cls else ""
        if col is None:
            return f"<th{c}>{label}</th>"
        return f'<th{c} data-col="{col}" data-sort="{kind or "txt"}"><button type="button" class="sortbtn">{label}</button></th>'

    def pill(lvl, text):
        return f'<span class="pill {lvl}">{E(text)}</span>'

    def cat_sw(cat):
        return f'<span class="sw" style="background:{CATS.get(cat, CATS["other"])[1]}"></span>'

    def ws_label(wid):
        if not wid or wid == "?":
            return "Sin workspace en el evento"
        return ws_name.get(wid) or wid[:8]

    def dlabel(k):
        dt = datetime.strptime(k, "%Y%m%d")
        return f"{WD[dt.weekday()]} {dt.day}/{dt.month}"

    # ================================================================== v5 ACTIONS (every figure comes from the analysis above)
    try:
        from zoneinfo import ZoneInfo
        mad_off = int(gen.astimezone(ZoneInfo("Europe/Madrid")).utcoffset().total_seconds() // 3600)
    except Exception:
        mad_off = 2 if 3 < gen.month < 11 else 1
    mad_lbl = f"UTC+{mad_off}"

    def hmad(H):
        return f"{H:02d}:00 UTC ({(H + mad_off) % 24:02d}:00 Madrid)"

    actions = []
    headline_save = 0.0
    if cov_runs and hourly and tail_save_h > 0:
        m_tail = tail_save * per_month
        headline_save += m_tail
        worst = sorted(cov_runs, key=lambda r: -(r["tail"] or 0))[:3]
        ev = "; ".join(f"{dlabel(r['b'].strftime('%Y%m%d'))}: última actividad {hhmm(r['last'])}, pausa {hhmm(r['b'])} → {fn(r['tail'], 1)} h" for r in worst)
        actions.append({"kind": "save", "title": "Pausar la capacidad cuando deja de usarse",
                        "why": (f"La pausa actual es {'automática' if auto_suspend else 'manual'} hacia las {hhmm(susp_times[-1]) if susp_times else '—'} UTC, "
                                f"pero el trabajo real termina antes. En {len(cov_runs)} encendidos con actividad registrada hubo "
                                f"{fn(tail_h, 1)} h encendida tras la última actividad. Pausando 1 h después de la última actividad se ahorran "
                                f"{fn(tail_save_h, 1)} h × {money(hourly)}/h."),
                        "evidence": ev, "value": m_tail, "unit": "/mes estimado", "src": "Activity Log + registro de actividad + Spark + precio público"})
    if best_safe and best_safe["save"] > 0:
        actions.append({"kind": "save", "title": f"Alternativa simple: adelantar la pausa automática a las {hmad(best_safe['hour'])}",
                        "why": (f"Con esa hora fija no se habría cortado ningún trabajo en el periodo observado y se habrían evitado "
                                f"{fn(best_safe['saved_h'], 1)} h encendida. No se suma al total porque se solapa con la acción anterior."),
                        "evidence": " · ".join(f"{hmad(w['hour']).split(' (')[0]}: {fn(w['saved_h'], 1)} h, {w['conflicts']} día(s) con trabajo cortado" for w in whatif if w["saved_h"] > 0),
                        "value": best_safe["save"] * per_month, "unit": "/mes (alternativa)", "src": "Activity Log + registro de actividad"})
    if lowuse_days:
        actions.append({"kind": "save", "title": f"Evitar encender la capacidad en días sin carga ({len(lowuse_days)} días)",
                        "why": ("En estos días la factura muestra prácticamente solo el medidor «Compute Pool» (capacidad encendida, nada consumido). "
                                "Validar con el equipo si fueron encendidos para pruebas o demos que podían agruparse."),
                        "evidence": ", ".join(f"{dlabel(x['date'])}: {fn(x['on_h'], 1)} h, {money(x['cost'])}" for x in lowuse_days),
                        "value": lowuse_cost, "unit": "en el periodo (validar)", "src": "Azure Cost Management + Activity Log"})
    if res.get(1) and breakeven.get(1):
        be = breakeven[1]
        if uptime < be:
            extra = annual_res[1] - annual_payg_cu
            actions.append({"kind": "avoid", "title": "No comprar reserva de capacidad con el patrón de uso actual",
                            "why": (f"La reserva a 1 año sale a {money(res[1], 0)} por CU/año ({money(annual_res[1], 0)} para {focus_sku}). "
                                    f"Solo compensa si la capacidad está encendida más del {pc(be, 0)} del tiempo; ahora lo está el {pc(uptime, 0)}. "
                                    f"Al ritmo actual el pago por uso cuesta {money(annual_payg_cu, 0)}/año"
                                    f"{'' if cost_ok else ' (horas encendida × precio público, sin factura en esta ejecución)'}."),
                            "evidence": f"Precio pago por uso {money(price_cu, 4)}/CU-h · {price_src}",
                            "value": max(extra, 0), "unit": "/año de sobrecoste evitado",
                            "src": "Azure Retail Prices + Cost Management" if cost_ok else "Azure Retail Prices + Activity Log"})
        else:
            sav = annual_payg_cu - annual_res[1]
            actions.append({"kind": "save", "title": "Valorar reserva de capacidad a 1 año",
                            "why": f"La capacidad está encendida el {pc(uptime, 0)} del tiempo, por encima del umbral del {pc(be, 0)}.",
                            "evidence": f"Pago por uso anualizado {money(annual_payg_cu, 0)} vs reserva {money(annual_res[1], 0)}",
                            "value": sav, "unit": "/año", "src": "Azure Retail Prices + Cost Management"})
    if sizes and peak_day_avg and sizes[0]["peak_load"] < 0.8:
        s0 = sizes[0]
        actions.append({"kind": "scenario", "title": f"Escenario: bajar de {focus_sku} a {s0['sku']} (validar picos)",
                        "why": (f"De media se consumieron {fn(avg_cu_on, 1)} CU por hora encendida; el día de más carga "
                                f"({dlabel(peak_day['date'])}) {fn(peak_day_avg, 1)} CU de media, un {pc(s0['peak_load'], 0)} de un {s0['sku']}. "
                                "Son medias por hora: antes de cambiar, revisar picos y throttling en la app Capacity Metrics"
                                + (", que ya está instalada." if cm_installed else " (conviene instalarla).")),
                        "evidence": f"CU-h facturadas − CU-h de «Compute Pool» por día · {fn(on_billed_hours, 1)} h encendida con coste",
                        "value": s0["save_month"], "unit": "/mes si se confirma", "src": "Cost Management (cantidades CU-h)"})
    sched_nb = [n for n in nb_list if n["sched"] >= 3]
    for n in sched_nb[:2]:
        actions.append({"kind": "review", "title": f"Revisar la frecuencia del notebook programado «{n['item']}»",
                        "why": (f"{n['sched']} ejecuciones programadas y {fn(n['run'] / 3600, 1)} h de Spark en el periodo "
                                f"({pc(n['share'], 0)} del tiempo Spark). Mientras se ejecuta, la capacidad no puede pausarse."),
                        "evidence": f"Workspace {ws_label(n['ws'])} · primera {n['first'].strftime('%d/%m %H:%M') if n['first'] else '—'}, última {n['last'].strftime('%d/%m %H:%M') if n['last'] else '—'} UTC",
                        "value": n["cost"], "unit": "Spark atribuido en el periodo", "src": "Spark/Livy API + medidor Spark"})
    for c in paused_empty:
        if c["hourly_if_on"]:
            actions.append({"kind": "risk", "title": f"Eliminar o etiquetar la capacidad pausada «{c['name']}» ({c['sku']})",
                            "why": (f"Está pausada y sin ningún workspace asignado. Si alguien la reanuda por error costaría "
                                    f"{money(c['hourly_if_on'])}/h ({money(c['hourly_if_on'] * 24 * 30, 0)}/mes encendida)."),
                            "evidence": f"Grupo de recursos {c['rg'] or '—'} · {c['tags']}",
                            "value": c["hourly_if_on"] * 24 * 30, "unit": "/mes de riesgo evitado", "src": "ARM + Fabric Admin API"})
    if livy_failed:
        wasted = sum(x["run"] for x in livy_failed) / 3600
        actions.append({"kind": "review", "title": f"Corregir {len(livy_failed)} sesiones Spark fallidas",
                        "why": f"Consumieron {fn(wasted, 1)} h de Spark sin resultado útil.",
                        "evidence": ", ".join(sorted({x['item'] for x in livy_failed}))[:240],
                        "value": spark_cost * (sum(x["run"] for x in livy_failed) / livy_total_s) if livy_total_s else None,
                        "unit": "Spark atribuido", "src": "Spark/Livy API"})
    ai_cost = cat_cost.get("ai", 0.0)
    cop_set = next((r for r in ts_rows if "copilot capacities" in (r["title"] or "").lower()), None)
    if ai_cost > 0:
        actions.append({"kind": "gov", "title": "Separar el consumo de IA en una capacidad Copilot designada",
                        "why": (f"La IA (Copilot, Data Agents, Ontology AI) ya cuesta {money(ai_cost)} ({pc(ai_cost / total_cost if total_cost else 0, 1)}). "
                                "Designar una capacidad para Copilot permite repercutir ese coste con exactitud por equipo."),
                        "evidence": f"Ajuste del tenant «{cop_set['title']}»: {'activado' if cop_set['enabled'] else 'desactivado'}" if cop_set else "Medidores de IA en Cost Management",
                        "value": None, "unit": "", "src": "Cost Management + Tenant settings"})
    if untagged:
        actions.append({"kind": "gov", "title": "Etiquetar las capacidades con centro de coste",
                        "why": "Sin etiquetas (costCenter, owner, environment) Cost Management no puede repartir ni crear presupuestos por área.",
                        "evidence": ", ".join(f"{c['name']} ({c['sku']})" for c in untagged), "value": None, "unit": "", "src": "ARM"})
    if ref_failed:
        actions.append({"kind": "gov", "title": f"Arreglar {len(ref_failed)} refresco(s) fallido(s)",
                        "why": "Modelos con el último refresco fallido: datos desactualizados para los usuarios.",
                        "evidence": "; ".join(f"{r['name']} ({r['ws']}) {r['err']}" for r in ref_failed), "value": None, "unit": "", "src": "Admin API refreshables"})
    if idle_ws:
        actions.append({"kind": "gov", "title": f"Revisar {len(idle_ws)} workspaces en capacidad de pago sin uso en el periodo",
                        "why": "Sin actividad ni Spark en el periodo. Candidatos a archivar, moverse a capacidad de prueba o limpiar.",
                        "evidence": ", ".join(r["name"] for r in idle_ws[:12]) + (" …" if len(idle_ws) > 12 else ""), "value": None, "unit": "", "src": "Admin API + registro de actividad"})
    if trials:
        actions.append({"kind": "gov", "title": "Planificar el fin de la capacidad de prueba",
                        "why": "Lo que esté en la capacidad trial dejará de funcionar o tendrá que moverse a una de pago al terminar la prueba.",
                        "evidence": ", ".join(f"{c['name']} ({c['ws']} workspaces, {c['items']} items)" for c in trials), "value": None, "unit": "", "src": "Fabric Admin API"})
    if stale_items:
        actions.append({"kind": "gov", "title": f"Limpiar {len(stale_items)} items sin cambios en más de 90 días",
                        "why": "Reduce ruido, riesgo y almacenamiento. Verificar antes que no se consultan (tabla de items más usados).",
                        "evidence": ", ".join(f"{t}: {n}" for t, n in stale_types.most_common(6)), "value": None, "unit": "", "src": "Admin API items"})

    # ================================================================== v5 CHARTS (inline SVG, no external libraries)
    def nice_max(v):
        if v <= 0:
            return 1
        e = 10 ** math.floor(math.log10(v))
        for m in (1, 1.5, 2, 2.5, 3, 4, 5, 6, 8, 10):
            if v <= m * e:
                return m * e
        return 10 * e

    cat_order = [c for c, _ in sorted(cat_cost.items(), key=lambda kv: (kv[0] != "idle", kv[0] == "storage", -kv[1])) if cat_cost[c] > 0.005]

    def svg_daily_cost():
        W, H, L, R, T, B = 1100, 300, 58, 14, 14, 64
        n = len(all_days)
        if not n:
            return ""
        vals = [sum(day_cat[k].values()) for k in all_days]
        ym = nice_max(max(vals) if vals else 1)
        bw = (W - L - R) / n
        g = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="dct"><title id="dct">Coste diario por pieza de Fabric</title>']
        for i in range(5):
            y = T + (H - T - B) * i / 4
            g.append(f'<line x1="{L}" x2="{W - R}" y1="{y:.1f}" y2="{y:.1f}" stroke="#e3ebf1"/>'
                     f'<text x="{L - 8}" y="{y + 4:.1f}" text-anchor="end">{fn(ym * (1 - i / 4), 0)}</text>')
        for i, k in enumerate(all_days):
            x = L + i * bw + bw * 0.14
            w = bw * 0.72
            y = H - B
            tot = vals[i]
            tip = [f"{dlabel(k)} · {money(tot)}"]
            for c in cat_order:
                v = day_cat[k].get(c, 0)
                if v <= 0:
                    continue
                h = (H - T - B) * v / ym
                y -= h
                g.append(f'<rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{max(h, .5):.1f}" fill="{CATS[c][1]}"/>')
                tip.append(f"{CATS[c][0]}: {money(v)}")
            on = on_day.get(k, 0)
            g.append(f'<rect x="{L + i * bw:.1f}" y="{T}" width="{bw:.1f}" height="{H - T - B}" fill="transparent"><title>{E(chr(10).join(tip))}{E(chr(10) + "Encendida " + fn(on, 1) + " h") if on else ""}</title></rect>')
            dt = datetime.strptime(k, "%Y%m%d")
            if i % 2 == 0 or n <= 16:
                g.append(f'<text x="{L + i * bw + bw / 2:.1f}" y="{H - B + 15}" text-anchor="middle">{dt.day}/{dt.month}</text>')
            if dt.weekday() == 0:
                g.append(f'<text x="{L + i * bw + bw / 2:.1f}" y="{H - B + 30}" text-anchor="middle" class="lbl">lun</text>')
            if on > 0.05:
                g.append(f'<rect x="{L + i * bw + bw * .14:.1f}" y="{H - B + 36}" width="{bw * .72:.1f}" height="4" rx="2" fill="#117865" opacity="{min(.25 + on / 24, 1):.2f}"/>')
        g.append(f'<text x="{L}" y="{H - 4}" class="lbl">Barra fina inferior: horas encendida ese día (más oscura = más horas)</text>')
        g.append(f'<text x="{L - 50}" y="{T + 2}" class="lbl">{E(CUR)}</text></svg>')
        return "".join(g)

    act_hour = Counter((t.strftime("%Y%m%d"), t.hour) for t in work_times)
    ah_max = max(act_hour.values()) if act_hour else 1
    tl_days = [k for k in all_days if on_day.get(k, 0) > 0.01 or any(dk == k for dk, _ in act_hour)]
    tail_by_day = {}
    for r in cov_runs:
        if r["last"] and r["tail"] and r["tail"] > 0.05:
            tail_by_day.setdefault(r["b"].strftime("%Y%m%d"), []).append((r["last"], r["b"]))
        elif not r["last"]:
            tail_by_day.setdefault(r["b"].strftime("%Y%m%d"), []).append((r["a"], r["b"]))

    def svg_timeline():
        if not tl_days:
            return ""
        L, R, T, RH, G = 92, 92, 26, 22, 6
        W = 1100
        PX = (W - L - R) / 24
        H = T + len(tl_days) * (RH + G) + 14
        g = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="tlt"><title id="tlt">Horas encendida frente a horas con trabajo, por día</title>',
             '<defs><pattern id="hatch" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">'
             '<rect width="6" height="6" fill="#eef2f5"/><line x1="0" y1="0" x2="0" y2="6" stroke="#c9d4dd" stroke-width="2"/></pattern></defs>']
        for hh in range(0, 25, 3):
            x = L + hh * PX
            g.append(f'<line x1="{x:.1f}" x2="{x:.1f}" y1="{T - 6}" y2="{H - 10}" stroke="#e3ebf1"/>'
                     f'<text x="{x:.1f}" y="{T - 10}" text-anchor="middle">{hh:02d}h</text>')
        g.append(f'<text x="{W - 4}" y="{T - 10}" text-anchor="end" class="lbl">h encendida</text>')
        for i, k in enumerate(tl_days):
            y = T + i * (RH + G)
            d0_ = datetime.strptime(k, "%Y%m%d").replace(tzinfo=timezone.utc)
            pre = bool(act0) and d0_ < act0
            g.append(f'<text x="{L - 10}" y="{y + 15}" text-anchor="end" class="lbl">{dlabel(k)}</text>')
            g.append(f'<rect x="{L}" y="{y}" width="{24 * PX:.1f}" height="{RH}" fill="#f6f9fb"/>')
            for a, b in focus_iv:
                s_, e_ = max(a, d0_), min(b, d0_ + timedelta(days=1))
                if e_ <= s_:
                    continue
                x0 = L + (s_ - d0_).total_seconds() / 3600 * PX
                x1 = L + (e_ - d0_).total_seconds() / 3600 * PX
                g.append(f'<rect x="{x0:.1f}" y="{y}" width="{max(x1 - x0, 1):.1f}" height="{RH}" fill="{"url(#hatch)" if pre else "#cfe9e3"}">'
                         f'<title>Encendida {hhmm(s_)}–{hhmm(e_)} UTC{" · antes del inicio del registro de actividad" if pre else ""}</title></rect>')
            for a, b in tail_by_day.get(k, []):
                s_, e_ = max(a, d0_), min(b, d0_ + timedelta(days=1))
                if e_ > s_:
                    x0 = L + (s_ - d0_).total_seconds() / 3600 * PX
                    x1 = L + (e_ - d0_).total_seconds() / 3600 * PX
                    g.append(f'<rect x="{x0:.1f}" y="{y}" width="{max(x1 - x0, 1):.1f}" height="{RH}" fill="#d99a2b" opacity=".38">'
                             f'<title>Encendida sin trabajo: {hhmm(s_)}–{hhmm(e_)} UTC ({fn((e_ - s_).total_seconds() / 3600, 1)} h)</title></rect>')
            for hh in range(24):
                n_ = act_hour.get((k, hh), 0)
                if n_:
                    hgt = 3 + (RH - 7) * math.sqrt(n_ / ah_max)
                    g.append(f'<rect x="{L + hh * PX + PX * .2:.1f}" y="{y + RH - 4 - hgt:.1f}" width="{PX * .6:.1f}" height="{hgt:.1f}" rx="1.5" fill="#0b5345">'
                             f'<title>{dlabel(k)} {hh:02d}h UTC · {n_} operaciones de usuarios/apps</title></rect>')
            for x in livy_focus:
                s_, e_ = max(x["start"], d0_), min(x["end"] or gen, d0_ + timedelta(days=1))
                if e_ > s_:
                    x0 = L + (s_ - d0_).total_seconds() / 3600 * PX
                    x1 = L + (e_ - d0_).total_seconds() / 3600 * PX
                    g.append(f'<rect x="{x0:.1f}" y="{y + RH - 3}" width="{max(x1 - x0, 1.5):.1f}" height="3" fill="#6a3d9a">'
                             f'<title>Spark · {E(x["item"])} · {hhmm(x["start"])}–{hhmm(x["end"])} UTC</title></rect>')
            oh = on_day.get(k, 0)
            g.append(f'<text x="{W - R + 8}" y="{y + 15}" class="lbl">{fn(oh, 1)} h</text>')
        g.append("</svg>")
        return "".join(g)

    def heat_html():
        rows_ = []
        for d_ in range(7):
            cells = []
            for hh in range(24):
                v = heat[d_][hh]
                op = 0 if not v else .15 + .85 * math.sqrt(v / max(heat_max, 1))
                cells.append(f'<td title="{WD[d_]} {hh:02d}h UTC · {v} operaciones"><span style="background:rgba(11,83,69,{op:.2f});{"outline:1px solid #e3ebf1" if not v else ""}"></span></td>')
            rows_.append(f"<tr><th scope=row>{WD[d_]}</th>{''.join(cells)}</tr>")
        head = "".join(f"<th>{hh:02d}</th>" if hh % 3 == 0 else "<th></th>" for hh in range(24))
        return f'<div class="chart"><table class="heat" style="min-width:720px"><thead><tr><th></th>{head}</tr></thead><tbody>{"".join(rows_)}</tbody></table></div>'

    # ================================================================== v5 HTML · part 1 (summary, actions, pieces)
    MEXPL = [
        ("compute pool", "Parte de la capacidad encendida que no consumió ninguna carga. Fabric factura la capacidad completa por hora mientras está encendida; lo no usado aparece aquí."),
        ("capacity overage", "Consumo por encima del tamaño de la capacidad (sobreconsumo) facturado a precio de overage."),
        ("copilot and ai", "Copilot, Data Agents y experiencias de IA (consultas en lenguaje natural sobre los datos)."),
        ("ontology ai", "Funciones de IA de Fabric IQ sobre la ontología."),
        ("operations agents", "Agentes de operaciones de Real-Time Intelligence."),
        ("spark memory optimized", "Cómputo Spark: notebooks, jobs de Spark y cargas en lakehouses."),
        ("spark", "Cómputo Spark."),
        ("ontology logic", "Fabric IQ: lógica y operaciones de la ontología (modelado semántico de negocio)."),
        ("ontology", "Fabric IQ: ontología."),
        ("graph", "Fabric IQ: Graph."),
        ("onelake cache", "Caché de OneLake (datos en caché para consultas rápidas, p. ej. KQL)."),
        ("onelake storage", "Almacenamiento de datos en OneLake."),
        ("onelake", "Transacciones de lectura/escritura en OneLake."),
        ("eventhouse", "Eventhouse/KQL: base de datos en tiempo real encendida o consultada."),
        ("eventstream", "Eventstream: ingesta y procesamiento de eventos en streaming."),
        ("activator", "Activator: reglas y alertas en tiempo real."),
        ("data warehouse", "Warehouse y endpoint SQL de lakehouses."),
        ("sql database", "SQL database en Fabric."),
        ("power bi", "Power BI: refrescos, consultas e informes en la capacidad."),
        ("data movement", "Copy activities de pipelines (movimiento de datos)."),
        ("data orchestration", "Orquestación de pipelines."),
        ("dataflow", "Dataflows Gen2."),
        ("user data functions", "User data functions."),
        ("graphql", "API for GraphQL."),
        ("mirroring", "Mirroring de bases de datos."),
    ]

    def mexpl(name):
        nl = name.lower()
        for k, v in MEXPL:
            if k in nl:
                return v
        return "Medidor de Fabric facturado en la capacidad."

    MES = ["ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic"]
    mon = defaultdict(Counter)
    for r in raw.get("cost_monthly") or []:
        if r.get("month"):
            nm = (r.get("rid") or "").rsplit("/", 1)[-1] or "capacidades Fabric"
            mon[r["month"]][nm] += r.get("cost") or 0
    mon_keys = sorted(mon)
    cur_month = gen.strftime("%Y-%m")
    mon_tot = {k: sum(v.values()) for k, v in mon.items()}
    full_months = [k for k in mon_keys if k != cur_month and mon_tot[k] > 0]
    mon_avg = sum(mon_tot[k] for k in full_months) / len(full_months) if full_months else 0
    mon_caps = sorted({c for v in mon.values() for c in v}, key=lambda c: -sum(mon[k][c] for k in mon_keys))
    MON_COL = ["#117865", "#1d5c8f", "#6a3d9a", "#a14306", "#4f6378"]

    def mlabel(k):
        return f"{MES[int(k[5:7]) - 1]} {k[2:4]}"

    def svg_monthly():
        if not mon_keys:
            return ""
        W, H, L, R, T, B = 1100, 250, 64, 16, 22, 40
        mx = nice_max(max(mon_tot.values()))
        bw = (W - L - R) / len(mon_keys)
        g = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-labelledby="mtt"><title id="mtt">Coste mensual de Fabric en Cost Management</title>']
        for i in range(5):
            v = mx * i / 4
            y = H - B - (H - B - T) * i / 4
            g.append(f'<line x1="{L}" x2="{W - R}" y1="{y:.1f}" y2="{y:.1f}" stroke="#e3ebf1"/><text x="{L - 8}" y="{y + 4:.1f}" text-anchor="end">{fn(v, 0)}</text>')
        if mon_avg:
            ya = H - B - (H - B - T) * mon_avg / mx
            g.append(f'<line x1="{L}" x2="{W - R}" y1="{ya:.1f}" y2="{ya:.1f}" stroke="#a14306" stroke-dasharray="4 4"><title>Media meses cerrados {money(mon_avg, 0)}</title></line>')
        for i, k in enumerate(mon_keys):
            x = L + i * bw + bw * .18
            y0 = H - B
            for j, c in enumerate(mon_caps):
                v = mon[k].get(c, 0)
                if v <= 0:
                    continue
                h = (H - B - T) * v / mx
                y0 -= h
                op = ' opacity=".55"' if k == cur_month else ""
                g.append(f'<rect x="{x:.1f}" y="{y0:.1f}" width="{bw * .64:.1f}" height="{h:.1f}" fill="{MON_COL[j % len(MON_COL)]}"{op}>'
                         f'<title>{mlabel(k)} · {E(c)}: {money(v)}{" (mes en curso)" if k == cur_month else ""}</title></rect>')
            g.append(f'<text x="{x + bw * .32:.1f}" y="{y0 - 6:.1f}" text-anchor="middle" class="lbl">{fn(mon_tot[k], 0)}</text>'
                     f'<text x="{x + bw * .32:.1f}" y="{H - B + 16}" text-anchor="middle">{mlabel(k)}</text>')
            if k == cur_month:
                g.append(f'<text x="{x + bw * .32:.1f}" y="{H - B + 30}" text-anchor="middle" class="lbl">en curso</text>')
        g.append(f'<text x="{L - 50}" y="{T - 6}" class="lbl">{E(CUR)}</text></svg>')
        return "".join(g)

    subc = raw.get("sub_costs") or []
    sub_total = sum(r["cost"] for r in subc)
    sub_svc = Counter()
    for r in subc:
        sub_svc[r["service"] or "?"] += r["cost"]
    fabric_sub = sub_svc.get("Microsoft Fabric", 0.0)
    fab_adj = sorted([r for r in subc if r["cost"] >= 0.01 and r["service"] != "Microsoft Fabric" and "fabric" in r["rid"]], key=lambda r: -r["cost"])
    fab_adj_total = sum(r["cost"] for r in fab_adj)

    def rshort(rid):
        p = rid.split("/")
        rg = p[p.index("resourcegroups") + 1] if "resourcegroups" in p else ""
        return (p[-1] if p else rid), rg

    DRV_TOP = {}
    for cat in DRIVER:
        w = drv.get(cat) or Counter()
        tot = sum(w.values())
        if tot:
            DRV_TOP[cat] = [(ws_label(k), v / tot) for k, v in w.most_common(3)]
    item_by_cat = defaultdict(Counter)
    for e in work_ev:
        if e["it"]:
            item_by_cat[e["cat"]][e["it"]] += 1
    for x in livy:
        item_by_cat["spark"][x["item"]] += x["run"]

    nav = [("resumen", "Resumen"), ("acciones", "Acciones FinOps"), ("piezas", "Dónde va el dinero"), ("uso", "Encendida vs usada"),
           ("quien", "Quién consume"), ("reparto", "Reparto por workspace"), ("compromisos", "Reserva y tamaño"),
           ("gobierno", "Gobierno"), ("preguntas", "Preguntas"), ("fuentes", "Fuentes")]
    ok_src = sum(1 for v in sources.values() if v.get("status") == "ok")
    parts = []
    parts.append(f"""<!doctype html><html lang="es"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>FinOps de Microsoft Fabric · {E(period_label)} · datos reales</title><style>{CSS}</style></head><body>
<header class="top"><div class="wrap"><h1>FinOps de Microsoft Fabric: qué se paga, qué se usa y qué se puede ahorrar</h1>
<p class="lede">Informe generado por Azure SRE Agent leyendo en directo el tenant: factura de Azure Cost Management, horas de encendido del
Activity Log, actividad de usuarios, ejecuciones Spark, inventario y configuración de Fabric. Ningún dato es de ejemplo.</p>
<ul class="chips"><li><b>{E(period_label)}</b> · {win0.strftime('%d/%m')} → {gen.strftime('%d/%m/%Y %H:%M')} UTC</li>
<li>Capacidad principal <b>{E(focus_name)}</b> ({E(focus_sku)} · {E(focus.get('location') or '')})</li>
<li><b>{ok_src}/{len(sources)}</b> fuentes leídas</li><li>Identidades {'visibles' if show_ids else 'enmascaradas'}</li></ul></div></header>
<nav class="toc" aria-label="Secciones"><ol>{''.join(f'<li><a href="#{a}">{b}</a></li>' for a, b in nav)}</ol></nav><main><div class="wrap">""")

    def no_cost(sec_id, title, what):
        return (f'<section id="{sec_id}"><h2>{title}</h2><div class="notice warn"><div><b>Necesita la factura de Cost Management</b>'
                f'<p>{what} {E(cost_why)}</p></div></div></section>')

    if not cost_ok:
        parts.append(f'<div class="notice warn"><div><b>Coste facturado no disponible en esta ejecución</b><p>{E(cost_why)} '
                     'Las horas encendida, la actividad, Spark, el gobierno y los ahorros por pausa sí son reales y están completos; '
                     'los importes de ahorro usan el precio público de Azure.</p></div></div>')
    elif not crow:
        parts.append('<div class="notice warn"><div><b>Sin coste en el periodo</b><p>Cost Management no devolvió importes para capacidades de Fabric. '
                     'Revisa el rol Cost Management Reader en la suscripción o si las capacidades se facturan en otra suscripción.</p></div></div>')
    idle_pct = idle_cost / total_cost if total_cost else 0
    stor = cat_cost.get("storage", 0.0)
    seg = [("Consumido por cargas", consumption_cost, "#117865"), ("Encendida sin consumo", idle_cost, "#d99a2b"), ("Almacenamiento", stor, "#4f6378")]
    stack = "".join(f'<span style="width:{(v / total_cost * 100) if total_cost else 0:.2f}%;background:{c}" title="{E(lbl)}: {money(v)}"></span>' for lbl, v, c in seg if v > 0)
    legend = "".join(f'<li><span class="sw" style="background:{c}"></span>{E(lbl)}<strong>{money(v)}</strong>{pc(v / total_cost if total_cost else 0)}</li>' for lbl, v, c in seg)
    verdict = (f"La capacidad {E(focus_sku)} estuvo encendida <b>{fn(on_hours, 0)} h</b> ({pc(uptime, 0)} del periodo) y en ese tiempo "
               f"solo se usó el <b>{pc(util_all, 0)}</b> de lo que se pagó. El <b>{pc(idle_pct, 0)}</b> de la factura es capacidad encendida sin carga.") \
        if focus_cu and cu_billed else "Resumen del coste facturado en el periodo."
    est_on = hourly * on_hours
    if cost_ok:
        hero_l = (f'<p class="total-label">Coste real en {E(period_label.lower())}</p><p class="total-figure">{fn(total_cost, 2)}<small>{E(CUR)}</small></p>'
                  f'<p class="total-meta">Azure Cost Management · ActualCost · {len(meters)} medidores · {len({c["rid"] for c in crow})} capacidad(es) con cargo</p>')
        hero_r = f'<p class="verdict">{verdict}</p><div class="stack">{stack}</div><ul class="legend">{legend}</ul>'
        kv_cu = f'<li>CU-h pagadas vs usadas<b>{fn(cu_billed, 0)} / {fn(cu_consumed, 0)}</b>uso medio {fn(avg_cu_on, 1)} CU por hora encendida</li>'
    else:
        hero_l = (f'<p class="total-label">Coste facturado en {E(period_label.lower())}</p><p class="total-figure">—</p>'
                  f'<p class="total-meta">No disponible en esta ejecución</p>')
        hero_r = (f'<p class="verdict">Con el precio público, las <b>{fn(on_hours, 0)} h</b> encendida de {E(focus_sku)} equivalen a unos <b>{money(est_on, 0)}</b> '
                  f'({money(hourly)}/h). Es una referencia, no la factura: no incluye almacenamiento ni las operaciones que Fabric factura al pausar.</p>')
        kv_cu = '<li>CU-h pagadas vs usadas<b>—</b>requiere la factura de Cost Management</li>'
    parts.append(f"""<section id="resumen"><h2>Resumen</h2><p class="sub">Importe real facturado por Azure para las capacidades de Fabric y cómo se reparte entre uso real y capacidad ociosa.</p>
<div class="panel hero"><div>{hero_l}</div>
<div>{hero_r}</div></div>
<ul class="kv" style="margin-top:18px">
<li>Horas encendida<b>{fn(on_hours, 1)} h</b>de {fn(win_hours, 0)} h del periodo</li>
<li>Coste por hora encendida<b>{money(hourly)}</b>{focus_cu} CU × {money(price_cu, 4)}/CU-h</li>
{kv_cu}
<li>Ahorro identificado<b>{money(headline_save, 0)}/mes</b>sin cambiar de SKU ni tocar cargas</li></ul></section>""")

    # actions
    kind_lbl = {"save": ("Ahorro", "ok"), "avoid": ("Evitar gasto", "info"), "scenario": ("Escenario", "info"), "review": ("Revisar", "warn"),
                "risk": ("Riesgo", "crit"), "gov": ("Gobierno", "neutral")}
    ali = []
    for a in actions:
        kl, kc = kind_lbl.get(a["kind"], ("", "neutral"))
        val = f'<b>{money(a["value"], 0)}</b><span>{E(a["unit"])}</span>' if a.get("value") else f'<span>{pill(kc, kl)}</span>'
        ali.append(f'<li><div><h3>{E(a["title"])} {pill(kc, kl) if a.get("value") else ""}</h3><p>{E(a["why"])}</p></div>'
                   f'<div class="val">{val}</div><div class="ev"><b>Evidencia:</b> {E(a["evidence"] or "—")} · <i>{E(a["src"])}</i></div></li>')
    parts.append(f"""<section id="acciones"><h2>Acciones FinOps priorizadas</h2>
<p class="sub">Cada acción se calcula con los datos de este tenant y muestra la evidencia. Las cifras mensuales proyectan el periodo observado a 30 días.</p>
<div class="save-strip"><span class="big">{money(headline_save, 0)}/mes</span><p>Ahorro directo estimado ajustando la pausa de la capacidad, con 1 h de margen tras la última actividad.
Las demás acciones evitan gasto o riesgo y no se suman.</p></div>
<ol class="actions">{''.join(ali) or '<li><div><h3>Sin acciones</h3><p>No se detectan oportunidades con los datos disponibles.</p></div></li>'}</ol></section>""")

    # pieces
    cat_rows = []
    for c in cat_order:
        v = cat_cost[c]
        tops = DRV_TOP.get(c)
        who = ", ".join(f"{E(n)} {pc(s, 0)}" for n, s in tops) if tops else ("No asignable a un workspace" if c in ("idle", "storage", "onelake", "overage", "other") else "Sin actividad registrada")
        cat_rows.append(f'<li><span>{cat_sw(c)}{E(CATS[c][0])}</span><b>{money(v)} · {pc(v / total_cost if total_cost else 0)}</b>'
                        f'<span class="track"><span class="fill" style="display:block;width:{(v / max(cat_cost.values()) * 100):.1f}%;background:{CATS[c][1]}"></span></span>'
                        f'<span class="cell-sub" style="grid-column:1/-1">Generado en: {who}</span></li>')
    mrows = []
    for m in sorted(meters.values(), key=lambda m: -m["cost"]):
        if m["cost"] < 0.005:
            continue
        tops = item_by_cat.get(m["cat"])
        top_it = ", ".join(E(k) for k, _ in tops.most_common(3)) if tops and m["cat"] in DRIVER else "—"
        unit = "GB-mes" if m["cat"] == "storage" else "CU-h"
        mrows.append(f'<tr><td><span class="cell-strong">{cat_sw(m["cat"])}{E(m["name"])}</span><span class="cell-sub">{E(mexpl(m["name"]))}</span></td>'
                     f'<td>{E(CATS[m["cat"]][0])}</td><td class="num" data-v="{m["qty"]:.3f}">{fn(m["qty"], 1)} {unit}</td>'
                     f'<td class="num" data-v="{len(m["days"])}">{len(m["days"])}</td><td class="num" data-v="{m["cost"]:.4f}">{money(m["cost"])}</td>'
                     f'<td class="num" data-v="{m["cost"] / total_cost if total_cost else 0:.5f}">{pc(m["cost"] / total_cost if total_cost else 0)}</td><td>{top_it}</td></tr>')
    lag_note = f" Los días posteriores al {dlabel(last_cost_day)} aún no tienen coste: Cost Management publica con 24–48 h de retraso." if last_cost_day and last_cost_day < gen.strftime("%Y%m%d") else ""
    svc_rows = "".join(f'<li><span>{E(s)}</span><b>{money(v)} · {pc(v / sub_total if sub_total else 0, 0)}</b>'
                       f'<span class="track"><span class="fill" style="display:block;width:{(v / max(sub_svc.values()) * 100) if sub_svc else 0:.1f}%;background:{"#117865" if s == "Microsoft Fabric" else "#8aa1b4"}"></span></span></li>'
                       for s, v in sub_svc.most_common(6) if v >= 0.5)
    adj_rows = "".join(f'<li><span>{E(rshort(r["rid"])[0])}<span class="cell-sub">{E(r["service"])} · {E(rshort(r["rid"])[1])}</span></span><b>{money(r["cost"])}</b></li>' for r in fab_adj[:6])
    trend_html = ""
    if mon_keys or subc:
        prev = full_months[-1] if full_months else None
        trend_html = f"""<div class="panel" style="margin-top:18px"><h3>Tendencia mensual de Fabric</h3>
<p class="muted" style="margin:0 0 8px">Factura mensual de las capacidades de Fabric (incluye capacidades ya eliminadas).{f' Último mes cerrado ({mlabel(prev)}): <b>{money(mon_tot[prev])}</b>.' if prev else ''}
{f' Mes en curso hasta hoy: <b>{money(mon_tot.get(cur_month, 0))}</b>.' if cur_month in mon_tot else ''}</p>
<div class="chart">{svg_monthly()}</div><ul class="keys">{''.join(f'<li><span class="sw" style="background:{MON_COL[j % len(MON_COL)]}"></span>{E(c)}</li>' for j, c in enumerate(mon_caps)) if len(mon_caps) > 1 else ''}{f'<li><span class="sw" style="background:none;border-top:2px dashed #a14306;height:0;width:16px"></span>Media de los meses cerrados: <b>{money(mon_avg, 0)}</b></li>' if mon_avg else ''}</ul></div>
<div class="split" style="margin-top:18px"><div class="panel"><h3>Fabric dentro de la suscripción</h3>
<p class="muted" style="margin:0 0 12px">Mismo periodo, toda la suscripción: Fabric es el <b>{pc(fabric_sub / sub_total if sub_total else 0, 0)}</b> de {money(sub_total)}.</p>
<ul class="bars">{svc_rows}</ul></div>
{f'<div class="panel"><h3>Otros recursos Azure con «fabric» en el nombre o en su grupo de recursos ({money(fab_adj_total)})</h3><p class="muted" style="margin:0 0 8px">No se facturan en la capacidad. Revisar si forman parte de la solución (p. ej. apps de Data Agent o mirroring) o si son recursos ajenos en el mismo grupo.</p><ul class="bars">{adj_rows}</ul></div>' if fab_adj else ''}</div>"""
    if not cost_ok:
        parts.append(no_cost("piezas", "Dónde va el dinero, pieza a pieza",
                             "El desglose por medidor, la tendencia mensual y el peso de Fabric en la suscripción salen de la factura."))
    else:
        parts.append(f"""<section id="piezas"><h2>Dónde va el dinero, pieza a pieza</h2>
<p class="sub">Cada medidor de la factura de Fabric con su cantidad, importe y qué lo generó. La suma de todos los medidores es el coste total.{lag_note}</p>
<div class="panel"><div class="chart">{svg_daily_cost()}</div>
<ul class="keys">{''.join(f'<li>{cat_sw(c)}{E(CATS[c][0])}</li>' for c in cat_order)}</ul></div>
<div class="split"><div class="panel"><h3>Por tipo de carga</h3><ul class="bars">{''.join(cat_rows)}</ul></div>
<div class="panel"><h3>Cómo leer la factura de Fabric</h3><p class="muted" style="margin:0 0 10px">Una capacidad {E(focus_sku or 'F')} se paga por hora encendida
({money(hourly)}/h). Microsoft desglosa ese importe en medidores: cada carga (Spark, IA, Real-Time…) factura las CU que usó y el resto aparece como
«Compute Pool». Por eso el Compute Pool alto significa capacidad encendida sin uso, no una carga concreta.</p>
<p class="muted" style="margin:0">Al pausar, Fabric factura de golpe las operaciones suavizadas pendientes; por eso algunos días el total supera {focus_cu or 'las'} CU × horas encendida.
En los días sin carga la factura coincide con las horas encendida{f' con un error máximo del {pc(match_err, 1)}' if match_err is not None else ''}, lo que valida el cálculo de horas.</p></div></div>
{trend_html}
<div class="toolbar" style="margin-top:18px"><button class="btn" type="button" data-csv="csv-meters" data-name="fabric-coste-diario-medidores.csv">Descargar CSV diario por medidor</button></div>
<div class="tbl-wrap"><table data-sortable class="dense"><thead><tr>{th('Medidor', 0)}{th('Tipo', 1)}{th('Cantidad', 2, 'num', 'num')}{th('Días con cargo', 3, 'num', 'num')}{th('Coste', 4, 'num', 'num')}{th('%', 5, 'num', 'num')}<th>Items que más lo usan</th></tr></thead>
<tbody>{''.join(mrows)}</tbody><tfoot><tr><td colspan="4">Total</td><td class="num">{money(total_cost)}</td><td class="num">100 %</td><td></td></tr></tfoot></table></div></section>""")

    # ================================================================== v5 HTML · part 2 (on vs used, who, chargeback, commitments)
    wrows = "".join(f'<tr><td class="nw">{hmad(w["hour"])}</td><td class="num">{fn(w["saved_h"], 1)} h</td><td class="num">{money(w["save"])}</td>'
                    f'<td class="num">{money(w["save"] * per_month, 0)}</td><td class="num">{w["days"]}</td>'
                    f'<td>{pill("ok", "Sin cortar trabajo") if w["conflicts"] == 0 else pill("crit", str(w["conflicts"]) + " día(s) con trabajo cortado")}</td></tr>'
                    for w in whatif)
    drows = []
    for x in daily:
        if x["on_h"] < 0.01 and x["cost"] < 0.01:
            continue
        drows.append(f'<tr><td class="nw" data-v="{x["date"]}">{dlabel(x["date"])}</td><td class="num" data-v="{x["on_h"]:.2f}">{fn(x["on_h"], 1)} h</td>'
                     f'<td class="num" data-v="{x["billed"]:.1f}">{fn(x["billed"], 0)}</td><td class="num" data-v="{x["consumed"]:.1f}">{fn(x["consumed"], 0)}</td>'
                     f'<td class="num" data-v="{x["util"] or 0:.4f}">{pc(x["util"], 0) if x["util"] is not None else "—"}</td>'
                     f'<td class="num" data-v="{x["cost"]:.2f}">{money(x["cost"]) if not x["lag"] else "pendiente"}</td>'
                     f'<td class="num">{fn(x["ratio"], 2) if x["ratio"] is not None else "—"}</td></tr>')
    pre_note = (f"Las franjas rayadas son anteriores al {act0.strftime('%d/%m')}: el registro de actividad de Fabric solo guarda {act_days} días, "
                "así que ahí se ve el encendido pero no el trabajo.") if act0 and act0 > win0 else ""
    if cost_ok:
        bill_col = f"""<div><h3>Factura frente a horas encendida, día a día</h3><p class="muted" style="margin:0 0 10px">CU-h facturadas, CU-h usadas por cargas y ratio factura ÷ (horas × {focus_cu or '—'} CU).
Ratio 1,00 = la factura cuadra con las horas encendida.</p>
<div class="tbl-wrap"><table data-sortable class="dense"><thead><tr>{th('Día', 0)}{th('Encendida', 1, 'num', 'num')}{th('CU-h pagadas', 2, 'num', 'num')}{th('CU-h usadas', 3, 'num', 'num')}{th('Uso', 4, 'num', 'num')}{th('Coste', 5, 'num', 'num')}<th class="num">Ratio</th></tr></thead>
<tbody>{''.join(drows)}</tbody></table></div></div>"""
    else:
        bill_col = (f'<div><h3>Factura frente a horas encendida, día a día</h3><div class="notice warn"><div><b>Necesita la factura de Cost Management</b>'
                    f'<p>Las CU-h pagadas y usadas por día salen de la factura. {E(cost_why)}</p></div></div></div>')
    parts.append(f"""<section id="uso"><h2>Encendida frente a usada</h2>
<p class="sub">Cada fila es un día (UTC). La franja verde es la capacidad encendida (Activity Log), las barras oscuras son operaciones de usuarios y apps,
la línea morada son sesiones Spark y el ámbar marca la cola encendida después del último trabajo. {pre_note}</p>
<ul class="kv"><li>Encendida<b>{fn(on_hours, 1)} h</b>{len(focus_iv)} encendidos en el periodo</li>
<li>Tras el último trabajo<b>{fn(tail_h, 1)} h</b>{len(cov_runs)} encendidos con actividad registrada</li>
<li>Pausa {'automática' if auto_suspend else 'manual'}<b>{hhmm(susp_times[-1]) if susp_times else '—'} UTC</b>{f'mediana {int(suspend_hour_med):02d}:{int((suspend_hour_med % 1) * 60):02d} UTC' if suspend_hour_med is not None else 'sin pausas en el periodo'}</li>
<li>Quién la enciende<b>{len(callers_resume)}</b>{E(', '.join(plabel(pkey(c)) for c, _ in callers_resume.most_common(2))) or '—'}</li></ul>
<div class="panel" style="margin-top:18px"><div class="chart">{svg_timeline()}</div>
<ul class="keys"><li><span class="sw" style="background:#cfe9e3"></span>Encendida</li><li><span class="sw" style="background:#d99a2b;opacity:.6"></span>Encendida tras el último trabajo</li>
<li><span class="sw" style="background:#0b5345"></span>Operaciones por hora</li><li><span class="sw" style="background:#6a3d9a"></span>Spark</li>
{'<li><span class="sw" style="background:#c9d4dd"></span>Sin registro de actividad</li>' if pre_note else ''}</ul></div>
<div class="split" style="margin-top:18px"><div><h3>¿Y si la pausa automática fuera antes?</h3>
<p class="muted" style="margin:0 0 10px">Horas que se habrían evitado en los {len(cov_runs)} encendidos con actividad registrada, y si se habría cortado algún trabajo real.</p>
<div class="tbl-wrap"><table class="dense"><thead><tr><th>Pausa a las</th><th class="num">Horas evitadas</th><th class="num">Ahorro observado</th><th class="num">Al mes</th><th class="num">Días</th><th>Impacto</th></tr></thead>
<tbody>{wrows}</tbody></table></div></div>
{bill_col}</div></section>""")

    # who
    def topcat(p):
        c = [k for k, _ in p["cats"].most_common(3) if k in CATS]
        return " ".join(cat_sw(k) + E(CATS[k][0].split(" ·")[0].split(" (")[0]) for k in c[:2]) or "—"

    prow = []
    for p in humans[:25]:
        top_ws = ", ".join(E(ws_label(w)) for w, _ in p["ws"].most_common(2)) or "—"
        prow.append(f'<tr><td><span class="cell-strong">{E(plabel(p["k"]))}</span><span class="cell-sub">{"Persona" if p["kind"] == "user" else "Aplicación / service principal"}</span></td>'
                    f'<td class="num" data-v="{p["work"]}">{fn(p["work"])}</td><td class="num" data-v="{len(p["days"])}">{len(p["days"])}</td>'
                    f'<td>{topcat(p)}</td><td>{top_ws}</td><td class="num" data-v="{p.get("spark_h", 0):.2f}">{fn(p.get("spark_h", 0), 1)} h</td>'
                    f'<td class="nw" data-v="{p["last"].isoformat()}">{p["last"].strftime("%d/%m %H:%M")}</td></tr>')
    nh = "".join(f'<tr><td>{E(plabel(p["k"]))}</td><td class="num">{fn(p["events"])}</td><td>{E(", ".join(a for a, _ in p["acts"].most_common(3)))}</td></tr>' for p in nonhuman[:8])
    irows = "".join(f'<tr><td><span class="cell-strong">{E(r["it"])}</span><span class="cell-sub">{E(r["itt"] or "")}</span></td><td>{E(ws_label(r["ws"]))}</td>'
                    f'<td class="num" data-v="{r["n"]}">{fn(r["n"])}</td><td class="num" data-v="{len(r["users"])}">{len(r["users"])}</td><td>{topcat(r)}</td>'
                    f'<td class="nw" data-v="{r["last"].isoformat()}">{r["last"].strftime("%d/%m %H:%M")}</td></tr>' for r in top_items)
    n_users = sum(1 for p in humans if p["kind"] == "user")
    parts.append(f"""<section id="quien"><h2>Quién consume</h2>
<p class="sub">Operaciones de trabajo (consultas, ejecuciones, IA, refrescos, lecturas) del registro de actividad de Fabric{f' de los últimos {act_ok} días' if act_ok else ''} y sesiones Spark.
Las operaciones de administración y lecturas de este propio informe no cuentan. Identidades {'visibles' if show_ids else 'enmascaradas; pide el informe con identidades visibles si el destinatario está autorizado'}.</p>
<ul class="kv"><li>Personas activas<b>{n_users}</b>con operaciones de trabajo</li><li>Apps y service principals<b>{len(humans) - n_users}</b>con operaciones</li>
<li>Operaciones de trabajo<b>{fn(len(work_ev))}</b>de {fn(len(evs))} eventos auditados</li><li>Sesiones Spark<b>{len(livy)}</b>{fn(livy_total_s / 3600, 1)} h de ejecución</li></ul>
<div class="tbl-wrap" style="margin-top:18px"><table data-sortable class="dense"><thead><tr>{th('Identidad', 0)}{th('Operaciones', 1, 'num', 'num')}{th('Días activos', 2, 'num', 'num')}<th>Tipo de carga</th><th>Workspaces</th>{th('Spark', 5, 'num', 'num')}{th('Última', 6)}</tr></thead>
<tbody>{''.join(prow) or '<tr><td colspan="7">Sin operaciones de trabajo en el periodo.</td></tr>'}</tbody></table></div>
<div class="panel" style="margin-top:18px"><h3>Cuándo se trabaja (día × hora UTC)</h3>{heat_html()}</div>
<div class="panel" style="margin-top:18px"><h3>Identidades de sistema</h3><p class="muted" style="margin:0 0 10px">Procesos de Fabric y Power BI sin persona detrás.</p>
<div class="tbl-wrap"><table class="dense"><thead><tr><th>Identidad</th><th class="num">Eventos</th><th>Operaciones</th></tr></thead><tbody>{nh or '<tr><td colspan="3">—</td></tr>'}</tbody></table></div></div>
<h3 style="margin-top:22px">Items más usados</h3>
<div class="tbl-wrap"><table data-sortable class="dense"><thead><tr>{th('Item', 0)}{th('Workspace', 1)}{th('Operaciones', 2, 'num', 'num')}{th('Identidades', 3, 'num', 'num')}<th>Carga</th>{th('Última', 5)}</tr></thead>
<tbody>{irows or '<tr><td colspan="6">—</td></tr>'}</tbody></table></div></section>""")

    # chargeback
    cb_sum = sum(r["total"] for r in cb)
    residual = total_cost - cb_sum - no_ws_cost - unassigned_total
    cbrows = []
    cb_zero = []
    for r in cb:
        if r["total"] < 0.005:
            cb_zero.append(r["name"])
            continue
        mini = "".join(f'<span style="width:{v / r["direct"] * 100:.1f}%;background:{CATS[c][1]}" title="{E(CATS[c][0])}: {money(v)}"></span>'
                       for c, v in r["by_cat"].most_common() if r["direct"] > 0 and v > 0)
        cbrows.append(f'<tr><td><span class="cell-strong">{E(r["name"])}</span><span class="cell-sub">{E(r["cap"])} {E(r["sku"])} · {r["items"]} items</span>'
                      f'{f"<span class=mini>{mini}</span>" if mini else ""}</td>'
                      f'<td class="num" data-v="{r["events"]}">{fn(r["events"])}</td><td class="num" data-v="{r["ai"]}">{fn(r["ai"])}</td>'
                      f'<td class="num" data-v="{r["spark_h"]:.2f}">{fn(r["spark_h"], 1)} h</td><td class="num" data-v="{r["direct"]:.4f}">{money(r["direct"])}</td>'
                      f'<td class="num" data-v="{r["idle"]:.4f}">{money(r["idle"])}</td><td class="num cell-strong" data-v="{r["total"]:.4f}">{money(r["total"])}</td>'
                      f'<td class="num" data-v="{r["total"] / total_cost if total_cost else 0:.5f}">{pc(r["total"] / total_cost if total_cost else 0)}</td></tr>')
    extra_rows = []
    if no_ws_cost > 0.005:
        extra_rows.append(("Operaciones sin workspace en el evento", no_ws_cost))
    if abs(residual) > 0.005:
        extra_rows.append(("Workspaces que ya no existen o no inventariados", residual))
    for c, v in unassigned.most_common():
        if v > 0.005:
            extra_rows.append((f"Plataforma no asignable · {CATS[c][0]}", v))
    ex_html = "".join(f'<tr><td colspan="4"><span class="muted">{E(n)}</span></td><td class="num">{money(v)}</td><td></td><td class="num">{money(v)}</td>'
                      f'<td class="num">{pc(v / total_cost if total_cost else 0)}</td></tr>' for n, v in extra_rows)
    drv_list = "".join(f'<li>{cat_sw(c)}<b>{E(CATS[c][0])}</b> ({money(cat_cost[c])}) → por {E(d)}</li>' for c, d in DRIVER.items() if cat_cost.get(c, 0) > 0.005)
    nbrows = "".join(f'<tr><td><span class="cell-strong">{E(n["item"])}</span><span class="cell-sub">{E(ws_label(n["ws"]))}</span></td>'
                     f'<td class="num" data-v="{n["sessions"]}">{n["sessions"]}</td><td class="num" data-v="{n["sched"]}">{n["sched"]}</td>'
                     f'<td class="num" data-v="{n["failed"]}">{pill("crit", str(n["failed"])) if n["failed"] else "0"}</td>'
                     f'<td class="num" data-v="{n["run"]:.0f}">{fn(n["run"] / 3600, 2)} h</td><td class="num" data-v="{n["share"]:.4f}">{pc(n["share"], 0)}</td>'
                     f'<td class="num" data-v="{n["cost"]:.4f}">{money(n["cost"]) if cost_ok else "—"}</td>'
                     f'<td class="nw">{n["last"].strftime("%d/%m %H:%M") if n["last"] else "—"}</td></tr>' for n in nb_list[:15])
    if cost_ok:
        cb_block = f"""<p class="sub">Cada medidor de la factura se reparte con su propio uso real. El tiempo encendido sin consumo se reparte en proporción al consumo directo de cada workspace.
La suma cuadra exactamente con el total facturado.</p>
<div class="split"><div class="panel"><h3>Cómo se reparte cada medidor</h3><ul class="method" style="display:block;padding-left:0;list-style:none">{drv_list}
<li>{cat_sw('idle')}<b>{E(CATS['idle'][0])}</b> ({money(idle_cost)}) → en proporción al coste directo</li>
<li>{cat_sw('storage')}<b>Almacenamiento, transacciones OneLake y otros</b> → plataforma, no asignable con los datos disponibles</li></ul></div>
<div class="panel"><h3>Cuadre con la factura</h3><ul class="facts" style="border:0;margin:0;padding:0">
<li>Workspaces<b>{money(cb_sum)}</b></li><li>No asignable<b>{money(total_cost - cb_sum)}</b></li><li>Total facturado<b>{money(total_cost)}</b></li></ul>
<p class="muted" style="margin:14px 0 0">Para facturar internamente con precisión por persona, la referencia es la app Capacity Metrics{' (instalada en el tenant)' if cm_installed else ''} con el ajuste «Show user data» activado.</p></div></div>
<div class="toolbar" style="margin-top:18px"><button class="btn" type="button" data-csv="csv-chargeback" data-name="fabric-chargeback-workspaces.csv">Descargar CSV de reparto</button></div>
<div class="tbl-wrap"><table data-sortable class="dense"><thead><tr>{th('Workspace', 0)}{th('Operaciones', 1, 'num', 'num')}{th('Consultas IA', 2, 'num', 'num')}{th('Spark', 3, 'num', 'num')}{th('Coste directo', 4, 'num', 'num')}{th('Encendida sin uso', 5, 'num', 'num')}{th('Total', 6, 'num', 'num')}{th('%', 7, 'num', 'num')}</tr></thead>
<tbody>{''.join(cbrows)}</tbody><tfoot>{ex_html}<tr><td colspan="6">Total</td><td class="num">{money(total_cost)}</td><td class="num">100 %</td></tr></tfoot></table></div>
{f'<p class="muted" style="margin:10px 0 0"><b>{len(cb_zero)} workspaces sin consumo facturable en el periodo:</b> {E(", ".join(sorted(cb_zero, key=str.lower)))}.</p>' if cb_zero else ''}
"""
    else:
        cb_block = ('<div class="notice warn"><div><b>Necesita la factura de Cost Management</b><p>El reparto por workspace distribuye el importe facturado de cada medidor. '
                    f'{E(cost_why)} Mientras tanto, «Quién consume» muestra el uso real por workspace, identidad e item.</p></div></div>\n')
    parts.append(f"""<section id="reparto"><h2>Reparto del coste por workspace (chargeback)</h2>
{cb_block}<h3 style="margin-top:22px">Notebooks y jobs Spark</h3><p class="muted" style="margin:0 0 10px">{f"Coste Spark ({money(spark_cost)}) repartido por segundos de ejecución reales de cada sesión." if cost_ok else "Horas de ejecución reales de cada sesión; el coste aparece cuando hay factura."}</p>
<div class="tbl-wrap"><table data-sortable class="dense"><thead><tr>{th('Notebook', 0)}{th('Sesiones', 1, 'num', 'num')}{th('Programadas', 2, 'num', 'num')}{th('Fallidas', 3, 'num', 'num')}{th('Ejecución', 4, 'num', 'num')}{th('% Spark', 5, 'num', 'num')}{th('Coste', 6, 'num', 'num')}<th>Última (UTC)</th></tr></thead>
<tbody>{nbrows or '<tr><td colspan="8">Sin sesiones Spark en el periodo.</td></tr>'}</tbody></table></div></section>""")

    # ================================================================== v5 HTML · part 3 (commitments, governance, questions, sources)
    cmp_items = []
    same_res = bool(annual_res.get(1) and annual_res.get(3) and abs(annual_res[3] - annual_res[1]) / annual_res[1] < 0.01)
    if annual_payg_cu:
        cmp_items.append(("Pago por uso al ritmo actual" + ("" if cost_ok else " (horas encendida × precio público)"), annual_payg_cu, "#117865"))
    if same_res:
        cmp_items.append((f"Reserva 1 o 3 años ({focus_sku}) · mismo precio anual en la lista pública", annual_res[1], "#8aa1b4"))
    else:
        for y in (1, 3):
            if annual_res.get(y):
                cmp_items.append((f"Reserva {y} año{'s' if y > 1 else ''} ({focus_sku})", annual_res[y], "#8aa1b4"))
    if hourly:
        cmp_items.append((f"Pago por uso 24×7 ({focus_sku})", hourly * 8760, "#d99a2b"))
    cmp_max = max((v for _, v, _ in cmp_items), default=1)
    cmp_html = "".join(f'<li><span>{E(n)}</span><b>{money(v, 0)}/año</b><span class="track"><span class="fill" style="display:block;width:{v / cmp_max * 100:.1f}%;background:{c}"></span></span></li>'
                       for n, v, c in cmp_items)
    if same_res and 1 in breakeven:
        be_html = f'<li>Reserva 1 o 3 años<b>{pc(breakeven[1], 0)}</b>del tiempo encendida para compensar</li>'
    else:
        be_html = "".join(f'<li>Reserva {y} año{"s" if y > 1 else ""}<b>{pc(b, 0)}</b>del tiempo encendida para compensar</li>' for y, b in sorted(breakeven.items()))
    srows = "".join(f'<tr><td class="cell-strong">{E(s_["sku"])}</td><td class="num">{s_["cu"]}</td><td class="num">{pc(s_["avg_load"], 0)}</td>'
                    f'<td class="num">{pc(s_["peak_load"], 0)}</td><td class="num">{money(s_["save_month"], 0)}</td>'
                    f'<td>{pill("ok", "Viable en media") if s_["peak_load"] < 0.6 else (pill("warn", "Ajustado") if s_["peak_load"] < 0.9 else pill("crit", "Insuficiente"))}</td></tr>'
                    for s_ in sizes)
    if cost_ok:
        size_html = f"""<h3 style="margin-top:22px">Escenarios de tamaño</h3>
<p class="muted" style="margin:0 0 10px">Carga = CU usadas por hora encendida ÷ CU del SKU. «Pico» es el día de más carga en media horaria{f" ({dlabel(peak_day['date'])})" if peak_day else ''}.
No incluye ráfagas de minutos: confirmar en Capacity Metrics antes de cambiar de tamaño.</p>
<div class="tbl-wrap"><table class="dense"><thead><tr><th>SKU</th><th class="num">CU</th><th class="num">Carga media</th><th class="num">Carga día pico</th><th class="num">Ahorro/mes</th><th>Lectura</th></tr></thead>
<tbody><tr><td class="cell-strong">{E(focus_sku)} (actual)</td><td class="num">{focus_cu}</td><td class="num">{pc(avg_cu_on / focus_cu if focus_cu else 0, 0)}</td><td class="num">{pc(peak_day_avg / focus_cu if focus_cu else 0, 0)}</td><td class="num">—</td><td>{pill("neutral", "Actual")}</td></tr>{srows}</tbody></table></div>"""
    else:
        size_html = ('<h3 style="margin-top:22px">Escenarios de tamaño</h3><div class="notice warn"><div><b>Necesita la factura de Cost Management</b>'
                     f'<p>La carga por hora se calcula con las CU-h facturadas y consumidas. {E(cost_why)}</p></div></div>')
    parts.append(f"""<section id="compromisos"><h2>Reserva y tamaño de la capacidad</h2>
<p class="sub">Precios públicos de Azure para {E(focus_region or 'la región')} y horas reales encendida. Una reserva se paga las 24 h del día; solo compensa si la capacidad está encendida casi siempre.</p>
<div class="split"><div class="panel"><h3>Coste anual comparado</h3><ul class="bars">{cmp_html or '<li>Sin precios disponibles.</li>'}</ul>
<p class="muted" style="margin:14px 0 0">Precio pago por uso: {money(price_cu, 4)}/CU-h · {E(price_src)}.</p></div>
<div class="panel"><h3>Umbral de rentabilidad</h3><ul class="kv" style="grid-template-columns:1fr 1fr">
<li>Encendida ahora<b>{pc(uptime, 0)}</b>{fn(on_hours, 0)} h de {fn(win_hours, 0)} h</li>{be_html}</ul>
<p class="muted" style="margin:14px 0 0">{'Con el uso actual, pagar por uso y pausar es más barato que cualquier reserva.' if breakeven and uptime < min(breakeven.values()) else 'El uso actual supera el umbral de al menos una reserva.'}</p></div></div>
{size_html}</section>""")

    # governance
    crows = "".join(f'<tr><td><span class="cell-strong">{E(c["name"])}</span><span class="cell-sub">{E(c["region"])}{" · " + E(c["rg"]) if c["rg"] else ""}</span></td>'
                    f'<td>{E(c["sku"])}</td><td>{E(c["state"])}</td><td class="num">{c["ws"]}</td><td class="num">{c["items"]}</td>'
                    f'<td class="num">{money(c["cost"]) if c["arm"] else "—"}</td><td>{E(c["tags"])}</td><td>{pill(c["lvl"], c["finding"])}</td></tr>' for c in caps_tbl)
    rrows = "".join(f'<tr><td><span class="cell-strong">{E(r["name"])}</span><span class="cell-sub">{E(r["ws"])}</span></td><td>{E(r["kind"])}</td>'
                    f'<td class="nw">{r["last"].strftime("%d/%m/%Y") if r["last"] else "—"}</td><td class="num">{r["age"] if r["age"] is not None else "—"}</td>'
                    f'<td>{(pill("warn", "Sin refrescar &gt;60 días") + "<span class=cell-sub>Último: " + E(r["status"]) + "</span>") if r["level"] == "warn" else pill(r["level"], r["status"])}{("<span class=cell-sub>" + E(r["err"]) + "</span>") if r["err"] else ""}</td>'
                    f'<td>{"Sí" if r["sched"] else "No"}</td></tr>' for r in refs[:20])
    tsrows = "".join(f'<tr><td><span class="cell-strong">{E(r["title"])}</span><span class="cell-sub">{E(r["why"])}</span></td>'
                     f'<td>{pill("ok" if r["enabled"] else "neutral", "Activado" if r["enabled"] else "Desactivado")}</td><td>{E(r["scope"])}</td></tr>' for r in ts_rows)
    itypes = "".join(f'<li>{E(t)}<b>{n}</b></li>' for t, n in item_types.most_common(12))
    ol_line = (f"{len(ol_ok)} de {len(ol)} lakehouses leídos · {fn(ol_bytes / 1024 ** 3, 2)} GB en tablas y ficheros" if ol else "Sin lakehouses en el inventario")
    parts.append(f"""<section id="gobierno"><h2>Inventario y gobierno</h2>
<p class="sub">Lo que hay en el tenant y lo que conviene ordenar para que el coste sea controlable.</p>
<ul class="kv"><li>Capacidades<b>{len(caps_tbl)}</b>{sum(1 for c in caps_tbl if c['state'].lower() == 'active')} activas</li>
<li>Workspaces<b>{len(workspaces)}</b>{sum(1 for w in workspaces if (w.get('capacity_id') or '').lower() in paid_caps)} en capacidad de pago</li>
<li>Items<b>{fn(len(items))}</b>{len(stale_items)} sin cambios en 90 días</li><li>OneLake leído<b>{fn(ol_bytes / 1024 ** 3, 2)} GB</b>{E(ol_line)}</li></ul>
<h3 style="margin-top:22px">Capacidades</h3>
<div class="tbl-wrap"><table class="dense"><thead><tr><th>Capacidad</th><th>SKU</th><th>Estado</th><th class="num">Workspaces</th><th class="num">Items</th><th class="num">Coste periodo</th><th>Etiquetas</th><th>Hallazgo</th></tr></thead>
<tbody>{crows}</tbody></table></div>
<div class="panel" style="margin-top:18px"><h3>Items por tipo</h3><ul class="kv types">{itypes}</ul></div>
<div class="panel" style="margin-top:18px"><h3>Ajustes del tenant que afectan al coste</h3><div class="tbl-wrap"><table class="dense"><thead><tr><th>Ajuste</th><th>Estado</th><th>Ámbito</th></tr></thead>
<tbody>{tsrows or '<tr><td colspan="3">—</td></tr>'}</tbody></table></div></div>
<h3 style="margin-top:22px">Refrescos de modelos y dataflows</h3>
<div class="tbl-wrap"><table class="dense"><thead><tr><th>Item</th><th>Tipo</th><th>Último</th><th class="num">Días</th><th>Estado</th><th>Programado</th></tr></thead>
<tbody>{rrows or '<tr><td colspan="6">Sin elementos refrescables.</td></tr>'}</tbody></table></div></section>""")

    # questions
    QS = [
        ("Coste y factura", [
            "¿Cuánto me ha costado Fabric en los últimos 30 días y en qué medidores?",
            "Compara el coste de este mes con el mes anterior y explica la diferencia.",
            "¿Qué parte de la factura es capacidad encendida sin uso?",
            "¿Qué días se pagó la capacidad sin que nadie la usara?"]),
        ("Ahorro y capacidad", [
            "¿A qué hora debería pausarse la capacidad para no cortar trabajo?",
            "¿Me compensa una reserva de capacidad con mi uso actual?",
            "¿Podría bajar de SKU? Dame la carga media y del día pico.",
            "¿Qué capacidades están pausadas o vacías y cuánto costarían encendidas?"]),
        ("Quién y qué consume", [
            "Reparte el coste del periodo por workspace y explícame el método.",
            "¿Qué usuarios y apps generan más carga y en qué workspaces?",
            "¿Qué notebooks Spark consumen más y cuáles se ejecutan programados?",
            "¿Cuánto cuesta la IA (Copilot, Data Agents) y quién la usa?"]),
        ("Gobierno", [
            "¿Qué refrescos han fallado y desde cuándo?",
            "¿Qué workspaces de capacidad de pago no se han usado este mes?",
            "¿Qué ajustes del tenant afectan al coste y cómo están configurados?",
            "Genera el informe con identidades visibles para el equipo de FinOps."]),
    ]
    qhtml = "".join(f'<article><h3>{E(g)}</h3><ul>' + "".join(f'<li><span>{E(q)}</span><button type="button" data-copy="{E(q)}">Copiar</button></li>' for q in qs) + "</ul></article>" for g, qs in QS)
    parts.append(f"""<section id="preguntas"><h2>Pregúntale al agente</h2>
<p class="sub">Copia cualquiera de estas preguntas en el chat de Azure SRE Agent (agente <b>fabric-chargeback-live</b>). El agente vuelve a leer el tenant en directo y responde con cifras de este mismo modelo.</p>
<div class="qs">{qhtml}</div></section>""")

    # sources
    SRC_LBL = {"capacities": ("Capacidades de Fabric", "Fabric Admin API"), "workspaces": ("Workspaces", "Fabric Admin API"),
               "items": ("Items", "Fabric Admin API"), "activity": ("Registro de actividad", "Power BI Admin API · activityevents"),
               "refreshables": ("Refrescos", "Power BI Admin API · refreshables"), "spark": ("Sesiones Spark", "Fabric Spark Livy API"),
               "onelake": ("Tamaño OneLake", "OneLake DFS API"), "arm": ("Suscripciones", "Azure Resource Manager"),
               "cost": ("Coste diario por medidor", "Azure Cost Management · ActualCost"), "activity_log": ("Encendido y pausa", "Azure Activity Log"),
               "cost_monthly": ("Coste mensual (12 meses)", "Azure Cost Management"), "sub_costs": ("Coste de la suscripción por servicio", "Azure Cost Management"),
               "prices": ("Precios públicos", "Azure Retail Prices API"), "tenant_settings": ("Ajustes del tenant", "Fabric Admin API · tenantsettings")}
    st_pill = {"ok": ("ok", "Leído"), "partial": ("warn", "Parcial"), "error": ("crit", "Error")}
    srcrows = []
    for k, v in sources.items():
        if k.startswith("token_"):
            k_lbl = (f"Token {k[6:]}", "Entra ID · federación sin secretos")
        else:
            k_lbl = SRC_LBL.get(k, (k, ""))
        lv, tx = st_pill.get(v.get("status"), ("neutral", v.get("status") or "—"))
        srcrows.append(f'<tr><td><span class="cell-strong">{E(k_lbl[0])}</span><span class="cell-sub">{E(k_lbl[1])}</span></td><td>{pill(lv, tx)}</td>'
                       f'<td class="num">{E(str(v.get("http") or "—"))}</td><td class="num">{fn(v.get("count") or 0)}</td><td class="num">{fn(v.get("seconds") or 0, 1)} s</td>'
                       f'<td>{E(v.get("note") or "")}</td></tr>')
    srcrows.append(f'<tr><td><span class="cell-strong">App Capacity Metrics</span><span class="cell-sub">Power BI · modelo semántico</span></td>'
                   f'<td>{pill("info", "Instalada · no consultable") if cm_installed else pill("neutral", "No detectada")}</td><td class="num">—</td>'
                   f'<td class="num">{len(cm_items) if cm_installed else 0}</td><td class="num">—</td>'
                   f'<td>{"Microsoft no permite consultar con service principal los modelos con RLS/SSO como este. Úsala para validar picos y throttling." if cm_installed else "Instálala para ver picos por minuto y throttling."}</td></tr>')
    parts.append(f"""<section id="fuentes"><h2>Fuentes y método</h2>
<p class="sub">Todo se lee en el momento de generar el informe, en modo solo lectura, {'con una identidad federada entre tenants, sin secretos' if raw.get('auth_mode', 'cross_tenant') == 'cross_tenant' else 'con la identidad gestionada del SRE Agent, sin secretos'}. Esta es la situación real de cada fuente en esta ejecución.</p>
<div class="tbl-wrap"><table class="dense"><thead><tr><th>Fuente</th><th>Estado</th><th class="num">HTTP</th><th class="num">Registros</th><th class="num">Tiempo</th><th>Nota</th></tr></thead>
<tbody>{''.join(srcrows)}</tbody></table></div>
<div class="method panel" style="margin-top:18px"><div><h3>Cómo se calcula</h3><ul>
<li>El coste es el importe real de Cost Management (ActualCost) de los recursos <code>microsoft.fabric/capacities</code>, por día y medidor, en {E(CUR)}.</li>
<li>Las horas encendida salen de los eventos resume/suspend del Activity Log y se validan contra la factura (ratio factura ÷ horas × CU).</li>
<li>El trabajo real son operaciones del registro de actividad de Fabric y sesiones Spark; se excluyen operaciones administrativas y las de este informe.</li>
<li>Las proyecciones mensuales escalan el periodo observado a 30 días.</li></ul></div>
<div><h3>Límites conocidos</h3><ul>
<li>El registro de actividad de Fabric guarda {act_days or 28} días: el trabajo anterior no es visible.</li>
<li>Cost Management publica el coste con 24–48 h de retraso; los últimos días pueden faltar.</li>
<li>Los medios horarios no muestran ráfagas de minutos: para tamaño y throttling, Capacity Metrics.</li>
<li>Al pausar, Fabric factura de golpe las operaciones suavizadas pendientes.</li></ul></div></div></section>""")

    # ================================================================== v5 OUTPUT (files + agent answer)
    def dec(v, d=4):
        return f"{(v or 0):.{d}f}".replace(".", ",")

    def csv_text(header_row, rows_):
        buf = io.StringIO()
        w = csv.writer(buf, delimiter=";", lineterminator="\n")
        w.writerow(header_row)
        w.writerows(rows_)
        return buf.getvalue()

    cats_cb = [c for c in cat_order if c in DRIVER]
    cb_csv_rows = []
    for r in cb:
        cb_csv_rows.append([r["name"], r["id"], r["cap"], r["sku"], r["items"], r["events"], r["ai"], dec(r["spark_h"], 2)]
                           + [dec(r["by_cat"].get(c, 0)) for c in cats_cb] + [dec(r["direct"]), dec(r["idle"]), dec(r["total"]),
                                                                            dec(r["total"] / total_cost * 100 if total_cost else 0, 2)])
    for n, v in extra_rows:
        cb_csv_rows.append([n, "", "", "", "", "", "", ""] + ["" for _ in cats_cb] + [dec(v), "", dec(v), dec(v / total_cost * 100 if total_cost else 0, 2)])
    cb_csv = csv_text(["workspace", "workspace_id", "capacidad", "sku", "items", "operaciones", "consultas_ia", "spark_horas"]
                      + [f"coste_{c}" for c in cats_cb] + ["coste_directo", "encendida_sin_uso", "total", "porcentaje"], cb_csv_rows)
    cap_nm = {rid: (c.get("name") or rid.rsplit("/", 1)[-1]) for rid, c in cap_by_rid.items()}
    mt_csv = csv_text(["fecha", "capacidad", "medidor", "categoria", "cantidad", "coste", "moneda"],
                      [[f"{c['date'][:4]}-{c['date'][4:6]}-{c['date'][6:8]}", cap_nm.get(c["rid"], c["rid"].rsplit("/", 1)[-1]), c["meter"],
                        CATS[meter_cat(c["meter"])][0], dec(c["qty"]), dec(c["cost"]), c.get("currency") or CUR]
                       for c in sorted(crow, key=lambda c: (c["date"], -c["cost"]))])

    def script_block(i, txt):
        return f'<script type="text/plain" id="{i}">{txt.replace("</", "<\\/")}</script>'

    parts.append(f"""</div></main><footer><div class="wrap">Generado por Azure SRE Agent · herramienta generate-fabric-chargeback-report v5.0 ·
{gen.strftime('%d/%m/%Y %H:%M')} UTC · lectura en {fn(raw.get('collect_seconds') or 0, 1)} s · solo lectura, sin datos de ejemplo.</div></footer>
{script_block('csv-meters', mt_csv)}{script_block('csv-chargeback', cb_csv)}<script>{JS}</script></body></html>""")
    html_doc = "".join(parts)

    def r2(v):
        return round(float(v or 0), 2)

    answer = {
        "status": "ok", "version": "5.0", "auth_mode": raw.get("auth_mode", AUTH_MODE), "generated_utc": gen.strftime("%Y-%m-%dT%H:%M:%SZ"), "period": period_label,
        "window_utc": [win0.strftime("%Y-%m-%d"), gen.strftime("%Y-%m-%d")], "currency": CUR, "identities": "visible" if show_ids else "masked",
        "cost_available": cost_ok, "cost_unavailable_reason": None if cost_ok else cost_why,
        "headline": {"total_cost": r2(total_cost) if cost_ok else None, "consumed_by_workloads": r2(consumption_cost) if cost_ok else None,
                     "on_without_use": r2(idle_cost) if cost_ok else None,
                     "storage": r2(cat_cost.get("storage", 0)) if cost_ok else None, "on_hours": round(on_hours, 1), "uptime_pct": round(uptime * 100, 1),
                     "utilization_pct_while_on": round(util_all * 100, 1) if cost_ok else None, "hourly_cost_when_on": r2(hourly),
                     "on_hours_x_public_price": r2(hourly * on_hours),
                     "idle_after_last_work_hours": round(tail_h, 1), "monthly_saving_identified": r2(headline_save)},
        "focus_capacity": {"name": focus_name, "sku": focus_sku, "region": focus_region, "state": focus.get("state"),
                           "price_per_cu_hour": round(price_cu, 4), "price_source": price_src,
                           "auto_suspend_utc": hhmm(susp_times[-1]) if susp_times else None},
        "cost_by_category": {CATS[c][0]: r2(cat_cost[c]) for c in cat_order},
        "meters": [{"meter": m["name"], "category": CATS[m["cat"]][0], "quantity": round(m["qty"], 2), "cost": r2(m["cost"]), "explanation": mexpl(m["name"])}
                   for m in sorted(meters.values(), key=lambda m: -m["cost"]) if m["cost"] >= 0.01],
        "cost_daily": [{"date": x["date"], "on_hours": round(x["on_h"], 2), "cost": r2(x["cost"]), "cu_h_billed": round(x["billed"], 1),
                        "cu_h_used": round(x["consumed"], 1), "utilization_pct": round((x["util"] or 0) * 100, 1), "cost_pending": x["lag"]} for x in daily],
        "cost_monthly": [{"month": k, "cost": r2(mon_tot[k]), "in_progress": k == cur_month, "by_capacity": {c: r2(v) for c, v in mon[k].items()}} for k in mon_keys],
        "subscription_context": {"total": r2(sub_total), "fabric_share_pct": round(fabric_sub / sub_total * 100, 1) if sub_total else None,
                                 "by_service": {s: r2(v) for s, v in sub_svc.most_common(10)},
                                 "fabric_named_resources": [{"resource": rshort(r["rid"])[0], "service": r["service"], "cost": r2(r["cost"])} for r in fab_adj[:10]]},
        "actions": [{"kind": a["kind"], "title": a["title"], "why": a["why"], "evidence": a["evidence"], "value": r2(a["value"]) if a.get("value") else None,
                     "unit": a["unit"], "source": a["src"]} for a in actions],
        "pause_whatif": [{"pause_hour_utc": w["hour"], "hours_saved": round(w["saved_h"], 1), "saving_per_month": r2(w["save"] * per_month),
                          "days_with_work_cut": w["conflicts"]} for w in whatif],
        "reservation": {"breakeven_uptime_pct": {f"{y}y": round(b * 100, 1) for y, b in breakeven.items()}, "annual_payg_current": r2(annual_payg_cu),
                        "annual_reservation": {f"{y}y": r2(v) for y, v in annual_res.items()}},
        "size_scenarios": [{"sku": s_["sku"], "avg_load_pct": round(s_["avg_load"] * 100), "peak_day_load_pct": round(s_["peak_load"] * 100),
                            "saving_per_month": r2(s_["save_month"])} for s_ in sizes],
        "chargeback_by_workspace": [{"workspace": r["name"], "capacity": r["cap"], "operations": r["events"], "ai_queries": r["ai"],
                                     "spark_hours": round(r["spark_h"], 2), "direct": r2(r["direct"]), "idle_share": r2(r["idle"]), "total": r2(r["total"])}
                                    for r in cb if r["total"] >= 0.01][:25],
        "chargeback_not_assignable": {n: r2(v) for n, v in extra_rows},
        "top_identities": [{"identity": plabel(p["k"]), "kind": p["kind"], "operations": p["work"], "active_days": len(p["days"]),
                            "spark_hours": round(p.get("spark_h", 0), 2), "workspaces": [ws_label(w) for w, _ in p["ws"].most_common(3)]} for p in humans[:10]],
        "top_items": [{"item": r["it"], "type": r["itt"], "workspace": ws_label(r["ws"]), "operations": r["n"], "identities": len(r["users"])} for r in top_items[:10]],
        "spark_notebooks": [{"notebook": n["item"], "workspace": ws_label(n["ws"]), "sessions": n["sessions"], "scheduled": n["sched"], "failed": n["failed"],
                             "hours": round(n["run"] / 3600, 2), "cost": r2(n["cost"])} for n in nb_list[:10]],
        "capacities": [{"name": c["name"], "sku": c["sku"], "state": c["state"], "workspaces": c["ws"], "cost": r2(c["cost"]), "finding": c["finding"], "tags": c["tags"]} for c in caps_tbl],
        "failed_refreshes": [{"item": r["name"], "workspace": r["ws"], "last": r["last"].strftime("%Y-%m-%d") if r["last"] else None, "error": r["err"]} for r in ref_failed],
        "idle_workspaces_on_paid_capacity": [r["name"] for r in idle_ws],
        "tenant_settings": [{"setting": r["title"], "enabled": r["enabled"], "scope": r["scope"]} for r in ts_rows],
        "capacity_metrics_app": "installed; not queryable by service principal (RLS/SSO model)" if cm_installed else "not detected",
        "sources": {k: {"status": v.get("status"), "http": v.get("http"), "count": v.get("count")} for k, v in sources.items()},
        "analysis_seconds": round(time.monotonic() - t_an, 1),
    }
    if operation == "summary":
        return answer

    base = f"fabric-finops-{stamp}"
    names = {"report": f"{base}.html", "snapshot": f"{base}-snapshot.json", "chargeback_csv": f"{base}-reparto-workspaces.csv",
             "meters_csv": f"{base}-coste-diario-medidores.csv"}
    snap = dict(answer)
    snap["raw_counts"] = {k: (len(v) if isinstance(v, list) else None) for k, v in raw.items() if isinstance(v, list)}
    blobs = {names["report"]: html_doc.encode("utf-8"),
             names["snapshot"]: json.dumps(snap, ensure_ascii=False, indent=2, default=str).encode("utf-8"),
             names["chargeback_csv"]: ("\ufeff" + cb_csv).encode("utf-8"),
             names["meters_csv"]: ("\ufeff" + mt_csv).encode("utf-8")}
    for fname, data in blobs.items():
        (cwd / fname).write_bytes(data)
    answer.update({"report_url": file_url(names["report"]), "snapshot_url": file_url(names["snapshot"]),
                   "chargeback_csv_url": file_url(names["chargeback_csv"]), "meters_csv_url": file_url(names["meters_csv"])})
    for k in ("cost_daily", "meters"):
        answer[k] = answer[k][:12] if k == "meters" else answer[k]
    return answer
