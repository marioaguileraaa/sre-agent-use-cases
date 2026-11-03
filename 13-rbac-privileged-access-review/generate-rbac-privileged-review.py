# generate-rbac-privileged-review
# Python tool for Azure SRE Agent: Azure RBAC privileged access review
# (Owner, User Access Administrator, Contributor and administrative roles).
# READ ONLY. The SRE Agent managed identity needs:
#   - Azure RBAC: Reader on every reviewed subscription.
#   - Microsoft Graph (application permissions): User.Read.All, Application.Read.All,
#     GroupMember.Read.All and AuditLog.Read.All (the last one for sign-in activity).
# It never creates, modifies or deletes any role assignment.
# BEFORE PASTING IT into the Code tab, replace <YOUR_AGENT_CLIENT_ID> and <YOUR_SUBSCRIPTION_ID>
# (Step 4 of the guide). A Client ID or a Subscription ID is not a secret.
# Version 1.0 - November 2026
def main() -> dict:
    """Read-only privileged Azure RBAC access review: orphaned, redundant and individual-review assignments."""
    import base64
    import csv
    import fnmatch
    import html
    import io
    import json
    import os
    import re
    import time
    from collections import Counter, defaultdict
    from datetime import datetime, timezone
    from pathlib import Path
    from urllib.parse import quote
    import requests

    # ------------------------------------------------------------------
    # REQUIRED CONFIGURATION
    # Client ID of YOUR SRE Agent's (user-assigned) managed identity
    # and the list of subscriptions to review.
    # ------------------------------------------------------------------
    MANAGED_IDENTITY_CLIENT_ID = "<YOUR_AGENT_CLIENT_ID>"
    SUBSCRIPTION_IDS = ["<YOUR_SUBSCRIPTION_ID>"]
    # ------------------------------------------------------------------
    # OPTIONAL CONFIGURATION
    # ------------------------------------------------------------------
    STALE_SIGNIN_DAYS = 90       # no sign-in in N days = "unused"
    LARGE_GROUP_MEMBERS = 25     # groups with more members = "large group"
    ORGANIZATION_NAME = ""       # optional: shown in the report title, footer and JSON when set
    LOGO_DATA_URI = ""  # optional: data:image/png;base64,... of your organization logo

    ARM = "https://management.azure.com"
    GRAPH = "https://graph.microsoft.com"
    MICROSOFT_TENANTS = {
        "f8cdef31-a31e-4b4a-93e4-5f571e91255a",
        "72f988bf-86f1-41af-91ab-2d7cd011db47",
    }

    def fail(message: str) -> dict:
        return {"status": "error", "error": message}

    if not MANAGED_IDENTITY_CLIENT_ID or MANAGED_IDENTITY_CLIENT_ID.startswith("<"):
        return fail("Configuration required: MANAGED_IDENTITY_CLIENT_ID must be the Client ID "
                    "of your Azure SRE Agent managed identity.")
    subscriptions = [s.strip() for s in SUBSCRIPTION_IDS if s and not s.strip().startswith("<")]
    if not subscriptions:
        return fail("Configuration required: SUBSCRIPTION_IDS must contain at least one subscription.")

    try:
        from azure.identity import ManagedIdentityCredential
        credential = ManagedIdentityCredential(client_id=MANAGED_IDENTITY_CLIENT_ID)
        arm_token = credential.get_token(ARM + "/.default").token
    except Exception as exc:
        return fail(f"Could not get an Azure Resource Manager token: {type(exc).__name__}")
    graph_token, graph_token_error = None, None
    try:
        graph_token = credential.get_token(GRAPH + "/.default").token
    except Exception as exc:
        graph_token_error = type(exc).__name__

    def claim(token: str, key: str):
        try:
            part = token.split(".")[1]
            part += "=" * (-len(part) % 4)
            return json.loads(base64.urlsafe_b64decode(part)).get(key)
        except Exception:
            return None

    tenant_id = (claim(arm_token, "tid") or "").lower()
    now = datetime.now(timezone.utc)
    reference_iso = now.strftime("%Y-%m-%dT%H:%M:%SZ")
    report_date = now.strftime("%Y-%m-%d")
    org_name = (ORGANIZATION_NAME or "").strip()

    arm = requests.Session()
    arm.headers.update({"Authorization": "Bearer " + arm_token, "Accept": "application/json"})

    def arm_list(url: str):
        items, next_url = [], url
        while next_url:
            for attempt in range(3):
                r = arm.get(next_url, timeout=90)
                if r.status_code == 429 and attempt < 2:
                    time.sleep(min(int(r.headers.get("Retry-After", "5") or 5), 20))
                    continue
                break
            if r.status_code in (401, 403):
                return items, "denied", r.status_code
            if not r.ok:
                return items, "error", r.status_code
            body = r.json()
            items.extend(body.get("value", []))
            next_url = body.get("nextLink")
        return items, "ok", 200

    def parse_dt(value):
        if not value:
            return None
        text = str(value).strip().replace("Z", "+00:00")
        m = re.match(r"^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(\.\d+)?(.*)$", text)
        if m:
            text = m.group(1) + (m.group(2)[:7] if m.group(2) else "") + m.group(3)
        try:
            dt = datetime.fromisoformat(text)
        except ValueError:
            try:
                dt = datetime.fromisoformat(text[:19])
            except ValueError:
                return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    # ------------------------------------------------------------------
    # 1) Azure Resource Manager: assignments, definitions and PIM
    # ------------------------------------------------------------------
    assignments = {}
    role_defs = {}
    pim_active = {}
    pim_eligible = []
    sub_coverage = []
    mg_ancestors = defaultdict(set)
    sub_names = {}
    for sub in subscriptions:
        cov = {"subscription_id": sub, "name": sub}
        r = arm.get(f"{ARM}/subscriptions/{sub}?api-version=2022-12-01", timeout=60)
        if r.ok:
            sub_names[sub.lower()] = r.json().get("displayName") or sub
            cov["name"] = sub_names[sub.lower()]
            cov["state"] = r.json().get("state")
        else:
            cov["state"] = f"HTTP {r.status_code}"
        ra, st, code = arm_list(f"{ARM}/subscriptions/{sub}/providers/Microsoft.Authorization/roleAssignments?api-version=2022-04-01")
        cov["role_assignments"] = {"status": st, "http": code, "count": len(ra)}
        for a in ra:
            assignments.setdefault(a["id"].lower(), a)
            scope = (a.get("properties", {}).get("scope") or "").lower()
            if scope.startswith("/providers/microsoft.management/managementgroups/"):
                mg_ancestors[sub.lower()].add(scope)
        rd, st, code = arm_list(f"{ARM}/subscriptions/{sub}/providers/Microsoft.Authorization/roleDefinitions?api-version=2022-04-01")
        cov["role_definitions"] = {"status": st, "http": code, "count": len(rd)}
        for d in rd:
            role_defs.setdefault(d["name"].lower(), d)
        pa, st, code = arm_list(f"{ARM}/subscriptions/{sub}/providers/Microsoft.Authorization/roleAssignmentScheduleInstances?api-version=2020-10-01")
        cov["pim_active"] = {"status": st, "http": code, "count": len(pa)}
        for p in pa:
            pp = p.get("properties", {})
            origin = (pp.get("originRoleAssignmentId") or "").lower()
            if origin:
                pim_active[origin] = pp
        pe, st, code = arm_list(f"{ARM}/subscriptions/{sub}/providers/Microsoft.Authorization/roleEligibilityScheduleInstances?api-version=2020-10-01")
        cov["pim_eligible"] = {"status": st, "http": code, "count": len(pe)}
        pim_eligible.extend(pe)
        sub_coverage.append(cov)

    readable = [c for c in sub_coverage if c["role_assignments"]["status"] == "ok"]
    if not readable:
        return fail("No subscription is readable (role assignments denied or failed). "
                    "Assign Reader to the agent identity on the configured subscriptions.")

    # ------------------------------------------------------------------
    # 2) Role classification by privilege tier
    # ------------------------------------------------------------------
    def perm_blocks(defn):
        return (defn or {}).get("properties", {}).get("permissions", []) or []

    def op_allowed(defn, op, data=False):
        op = op.lower()
        for block in perm_blocks(defn):
            acts = [x.lower() for x in (block.get("dataActions" if data else "actions") or [])]
            nots = [x.lower() for x in (block.get("notDataActions" if data else "notActions") or [])]
            if any(fnmatch.fnmatchcase(op, p) for p in acts) and not any(
                    fnmatch.fnmatchcase(op, n) or fnmatch.fnmatchcase(n, op) for n in nots):
                return True
        return False

    def actions_of(defn, data=False):
        out = []
        for block in perm_blocks(defn):
            out.extend(block.get("dataActions" if data else "actions") or [])
        return out

    tier_cache = {}

    def tier_of(defn):
        key = (defn or {}).get("name", "").lower()
        if key in tier_cache:
            return tier_cache[key]
        name = (defn or {}).get("properties", {}).get("roleName", "")
        if op_allowed(defn, "Microsoft.Authorization/roleAssignments/write"):
            tier = 0
        elif "*" in actions_of(defn):
            tier = 1
        elif re.search(r"admin|owner", name, re.I):
            tier = 2
        else:
            tier = None
        tier_cache[key] = tier
        return tier

    def covers(parent, child):
        if parent is None or child is None:
            return False
        if parent.get("name", "").lower() == child.get("name", "").lower():
            return True
        for a in actions_of(child):
            if not op_allowed(parent, a):
                return False
        for a in actions_of(child, data=True):
            if not op_allowed(parent, a, data=True):
                return False
        return True

    TIER_LABEL = {0: "Tier 0 · Access control", 1: "Tier 1 · Full control", 2: "Tier 2 · Service admin"}

    # ------------------------------------------------------------------
    # 3) Assignment normalization
    # ------------------------------------------------------------------
    def scope_info(scope):
        s = (scope or "").rstrip("/")
        low = s.lower()
        if low in ("", "/"):
            return "Root (/)", "Tenant root", None
        m = re.match(r"^/providers/microsoft\.management/managementgroups/([^/]+)$", low)
        if m:
            mg = s.split("/")[-1]
            label = "Root management group" if mg.lower() == tenant_id else f"Management Group {mg}"
            return "Management Group", label, None
        m = re.match(r"^/subscriptions/([^/]+)(/resourcegroups/([^/]+))?(/providers/.+)?$", low)
        if not m:
            return "Other", s, None
        sub = m.group(1)
        sub_label = sub_names.get(sub, sub)
        if m.group(4):
            parts = s.split("/")
            return "Resource", f"{parts[-2]}/{parts[-1]} · {s.split('/')[4] if m.group(2) else sub_label}", sub
        if m.group(2):
            return "Resource group", s.split("/")[4], sub
        return "Subscription", sub_label, sub

    def is_ancestor(parent_scope, child_scope, child_sub):
        p, c = parent_scope.rstrip("/").lower(), child_scope.rstrip("/").lower()
        if p == c:
            return False
        if p in ("", "/"):
            return True
        if p.startswith("/providers/microsoft.management/managementgroups/"):
            if c.startswith("/subscriptions/") and child_sub:
                return p in mg_ancestors.get(child_sub, set())
            return False
        return c.startswith(p + "/")

    raw_rows = []
    for aid, a in assignments.items():
        p = a.get("properties", {})
        role_guid = (p.get("roleDefinitionId") or "").split("/")[-1].lower()
        defn = role_defs.get(role_guid)
        level, scope_label, sub = scope_info(p.get("scope"))
        pim = pim_active.get(aid)
        end = parse_dt((pim or {}).get("endDateTime"))
        if pim and (pim.get("assignmentType") == "Activated"):
            access = "PIM activation"
        elif end:
            access = "Time-bound"
        else:
            access = "Permanent"
        raw_rows.append({
            "id": a["id"],
            "assignment_name": a.get("name"),
            "scope": p.get("scope"),
            "scope_level": level,
            "scope_label": scope_label,
            "subscription_id": sub,
            "role_id": role_guid,
            "role": (defn or {}).get("properties", {}).get("roleName") or f"Role {role_guid[:8]}",
            "role_type": (defn or {}).get("properties", {}).get("type") or "Unknown",
            "tier": tier_of(defn) if defn else None,
            "principal_id": p.get("principalId"),
            "principal_arm_type": p.get("principalType") or "Unknown",
            "condition": bool(p.get("condition")),
            "created_on": p.get("createdOn"),
            "access": access,
            "end_date": end.strftime("%Y-%m-%d") if end else None,
            "pim_name": (((pim or {}).get("expandedProperties") or {}).get("principal") or {}).get("displayName"),
            "_defn": defn,
        })

    privileged = [r for r in raw_rows if r["tier"] is not None]

    # ------------------------------------------------------------------
    # 4) Microsoft Graph: identity resolution (batches of 20)
    # ------------------------------------------------------------------
    graph = requests.Session()
    if graph_token:
        graph.headers.update({"Authorization": "Bearer " + graph_token, "Content-Type": "application/json"})

    def graph_batch(reqs, version="v1.0"):
        results = {}
        for i in range(0, len(reqs), 20):
            chunk = reqs[i:i + 20]
            pending = chunk
            for attempt in range(3):
                r = graph.post(f"{GRAPH}/{version}/$batch", json={"requests": pending}, timeout=90)
                if not r.ok:
                    for q in pending:
                        results[q["id"]] = (r.status_code, None)
                    break
                retry, wait = [], 0
                for resp in r.json().get("responses", []):
                    if resp.get("status") == 429 and attempt < 2:
                        retry.append(next(q for q in pending if q["id"] == resp["id"]))
                        wait = max(wait, int((resp.get("headers") or {}).get("Retry-After", "3") or 3))
                    else:
                        results[resp["id"]] = (resp.get("status"), resp.get("body"))
                if not retry:
                    break
                pending = retry
                time.sleep(min(wait, 15))
        return results

    principal_types = {}
    for r in privileged:
        principal_types[r["principal_id"]] = r["principal_arm_type"]
    principals = {}
    graph_stats = defaultdict(Counter)
    signin_user_status = "not evaluated"
    signin_sp_status = "not evaluated"
    membership_status = "not evaluated"

    if graph_token:
        user_sel = "id,displayName,userPrincipalName,userType,accountEnabled,createdDateTime,signInActivity"
        reqs = []
        for pid, ptype in principal_types.items():
            if ptype == "User":
                url = f"/users/{pid}?$select={user_sel}"
            elif ptype == "ServicePrincipal":
                url = f"/servicePrincipals/{pid}?$select=id,displayName,appId,servicePrincipalType,appOwnerOrganizationId,accountEnabled"
            elif ptype == "Group":
                url = f"/groups/{pid}?$select=id,displayName,securityEnabled,isAssignableToRole"
            else:
                url = f"/directoryObjects/{pid}"
            reqs.append({"id": pid, "method": "GET", "url": url})
        res = graph_batch(reqs)
        users_retry = [pid for pid, (st, _) in res.items() if st == 403 and principal_types.get(pid) == "User"]
        if users_retry:
            signin_user_status = "denied (AuditLog.Read.All)"
            res.update(graph_batch([{"id": pid, "method": "GET",
                                     "url": f"/users/{pid}?$select=id,displayName,userPrincipalName,userType,accountEnabled,createdDateTime"}
                                    for pid in users_retry]))
        elif any(t == "User" for t in principal_types.values()):
            signin_user_status = "ok"
        for pid, ptype in principal_types.items():
            st, body = res.get(pid, (None, None))
            kind = {"User": "Users", "ServicePrincipal": "Apps and identities", "Group": "Groups"}.get(ptype, "Other")
            if st == 200 and isinstance(body, dict):
                principals[pid] = {"status": "ok", **body}
                graph_stats[kind]["resolved"] += 1
            elif st == 404:
                principals[pid] = {"status": "orphan"}
                graph_stats[kind]["orphaned"] += 1
            elif st in (401, 403):
                principals[pid] = {"status": "denied"}
                graph_stats[kind]["denied"] += 1
            else:
                principals[pid] = {"status": "error", "http": st}
                graph_stats[kind]["error"] += 1

        groups_ok = [pid for pid, ptype in principal_types.items() if ptype == "Group" and principals.get(pid, {}).get("status") == "ok"]
        if groups_ok:
            cres = graph_batch([{"id": pid, "method": "GET", "url": f"/groups/{pid}/transitiveMembers/$count",
                                 "headers": {"ConsistencyLevel": "eventual"}} for pid in groups_ok])
            for pid in groups_ok:
                st, body = cres.get(pid, (None, None))
                if st == 200:
                    try:
                        principals[pid]["member_count"] = int(body if not isinstance(body, str) else body.strip())
                    except Exception:
                        try:
                            principals[pid]["member_count"] = int(base64.b64decode(body).decode().strip())
                        except Exception:
                            pass
        if any(principals.get(pid, {}).get("status") == "denied" for pid, t in principal_types.items() if t == "Group"):
            membership_status = "denied (GroupMember.Read.All)"

        sp_apps = {}
        for r in privileged:
            pr = principals.get(r["principal_id"], {})
            if r["principal_arm_type"] == "ServicePrincipal" and pr.get("status") == "ok" and pr.get("appId") and r["tier"] in (0, 1):
                sp_apps[r["principal_id"]] = pr["appId"]
        if sp_apps:
            sres = graph_batch([{"id": pid, "method": "GET",
                                 "url": "/reports/servicePrincipalSignInActivities?$filter=" + quote(f"appId eq '{app}'", safe="'=")}
                                for pid, app in sp_apps.items()], version="beta")
            codes = Counter(st for st, _ in sres.values())
            if codes.get(200):
                signin_sp_status = "ok" if len(codes) == 1 else "partial"
            elif codes:
                signin_sp_status = f"unavailable (HTTP {max(codes, key=codes.get)})"
            for pid, (st, body) in sres.items():
                if st == 200 and isinstance(body, dict):
                    vals = body.get("value") or []
                    last = None
                    if vals:
                        last = ((vals[0].get("lastSignInActivity") or {}).get("lastSignInDateTime"))
                    principals[pid]["sp_last_sign_in"] = last
                    principals[pid]["sp_signin_known"] = True

        group_priv = defaultdict(list)
        for r in privileged:
            if r["principal_arm_type"] == "Group":
                group_priv[r["principal_id"]].append(r)
        user_groups = {}
        priv_users = {r["principal_id"] for r in privileged if r["principal_arm_type"] == "User"
                      and principals.get(r["principal_id"], {}).get("status") == "ok"}
        if group_priv and priv_users:
            mres = graph_batch([{"id": pid, "method": "GET",
                                 "url": f"/users/{pid}/transitiveMemberOf/microsoft.graph.group?$select=id&$top=999"}
                                for pid in priv_users])
            codes = Counter(st for st, _ in mres.values())
            membership_status = "ok" if codes.get(200) and len(codes) == 1 else (
                "partial" if codes.get(200) else f"denied (HTTP {max(codes, key=codes.get) if codes else '-'})")
            for pid, (st, body) in mres.items():
                if st == 200 and isinstance(body, dict):
                    user_groups[pid] = {g.get("id") for g in body.get("value", [])}
        elif not group_priv:
            membership_status = "no privileged groups"
    else:
        user_groups, group_priv = {}, {}

    # ------------------------------------------------------------------
    # 5) Decision per assignment
    # ------------------------------------------------------------------
    TYPE_LABEL = {"User": "User", "Group": "Group", "ServicePrincipal": "Application",
                  "ForeignGroup": "External group", "Device": "Device", "Unknown": "Unknown"}
    FLAG_LABEL = {
        "human_standing": "User with standing privilege (no PIM)",
        "nonhuman_tier0": "Non-human identity that can grant access",
        "owner_equivalent": "Contributor + access delegation = Owner equivalent",
        "unconditioned_delegation": "Access delegation without condition",
        "stale": f"No sign-in for more than {STALE_SIGNIN_DAYS} days",
        "disabled": "Disabled account",
        "guest": "Guest user (B2B)",
        "external_sp": "Application from another tenant",
        "large_group": f"Group with more than {LARGE_GROUP_MEMBERS} members",
        "broad_scope": "Management Group or subscription scope",
        "unresolved": "Unresolved identity (Graph permissions)",
    }
    FLAG_ACTION = {
        "disabled": "Remove: the account is disabled.",
        "human_standing": "Convert to a PIM eligible assignment (JIT activation with MFA and approval).",
        "nonhuman_tier0": "Replace with a purpose-built least-privilege role (Role Designer) or constrain with a condition.",
        "owner_equivalent": "Separate duties: remove the access delegation or restrict it with a condition.",
        "unconditioned_delegation": "Add a delegation condition (allowed roles) or move to PIM.",
        "stale": "Confirm with the owner and remove if unused.",
        "guest": "Validate the guest's sponsor, need and expiration date.",
        "external_sp": "Validate the vendor and the contract that justifies the access.",
        "large_group": "Review the group membership or split it by function.",
        "broad_scope": "Reduce the scope to the required resource group.",
        "unresolved": "Grant Graph read permissions and re-run before deciding.",
    }
    FLAG_ORDER = list(FLAG_ACTION.keys())

    by_principal = defaultdict(list)
    for r in privileged:
        by_principal[r["principal_id"]].append(r)
    all_by_principal = defaultdict(list)
    for r in raw_rows:
        all_by_principal[r["principal_id"]].append(r)

    def days_since(value):
        dt = parse_dt(value)
        return (now - dt).days if dt else None

    rows = []
    for r in privileged:
        pr = principals.get(r["principal_id"], {"status": "not evaluated"})
        ptype = r["principal_arm_type"]
        type_label = TYPE_LABEL.get(ptype, ptype)
        if ptype == "ServicePrincipal" and pr.get("servicePrincipalType") == "ManagedIdentity":
            type_label = "Managed identity"
        name = pr.get("displayName") or r["pim_name"]
        detail = pr.get("userPrincipalName") or pr.get("appId") or ""
        if pr.get("status") == "orphan":
            name = name or "Deleted identity"
            detail = detail or ("objectId " + r["principal_id"])
        name = name or "Unresolved"

        last_sign_in, signin_known = None, False
        if ptype == "User" and pr.get("status") == "ok":
            sia = pr.get("signInActivity") or {}
            dates = [parse_dt(sia.get(k)) for k in ("lastSignInDateTime", "lastNonInteractiveSignInDateTime", "lastSuccessfulSignInDateTime")]
            dates = [d for d in dates if d]
            if "signInActivity" in pr:
                signin_known = True
            if dates:
                last_sign_in = max(dates).strftime("%Y-%m-%d")
        if ptype == "ServicePrincipal" and pr.get("sp_signin_known"):
            signin_known = True
            if pr.get("sp_last_sign_in"):
                last_sign_in = parse_dt(pr["sp_last_sign_in"]).strftime("%Y-%m-%d")

        decision, reason = None, ""
        if pr.get("status") == "orphan":
            decision = "orphan"
            reason = "The identity no longer exists in Microsoft Entra ID; the assignment grants access to no one."
        if decision is None:
            for parent in all_by_principal[r["principal_id"]]:
                if parent is r or parent["condition"] or parent["access"] != "Permanent":
                    continue
                if is_ancestor(parent["scope"], r["scope"], r["subscription_id"]) and covers(parent["_defn"], r["_defn"]):
                    decision = "redundant"
                    reason = f"Redundant (inherited): already receives {parent['role']} without condition from {parent['scope_label']}."
                    break
        if decision is None:
            for parent in all_by_principal[r["principal_id"]]:
                if parent is r or parent["condition"] or parent["access"] != "Permanent":
                    continue
                if parent["scope"].rstrip("/").lower() == r["scope"].rstrip("/").lower() and covers(parent["_defn"], r["_defn"]):
                    mutual = covers(r["_defn"], parent["_defn"])
                    if not mutual or r["id"].lower() > parent["id"].lower():
                        decision = "redundant"
                        reason = f"Redundant (same scope): {parent['role']} at the same scope already includes this role."
                        break
        if decision is None and ptype == "User" and r["principal_id"] in user_groups:
            for gid in user_groups[r["principal_id"]]:
                for parent in group_priv.get(gid, []):
                    if parent["condition"] or parent["access"] != "Permanent":
                        continue
                    same_or_up = parent["scope"].rstrip("/").lower() == r["scope"].rstrip("/").lower() or is_ancestor(parent["scope"], r["scope"], r["subscription_id"])
                    if same_or_up and covers(parent["_defn"], r["_defn"]):
                        gname = principals.get(gid, {}).get("displayName") or parent["pim_name"] or "a group"
                        decision = "redundant"
                        reason = f"Redundant (via group): already receives it as a member of {gname} ({parent['role']} on {parent['scope_label']})."
                        break
                if decision:
                    break

        flags = []
        tier = r["tier"]
        if pr.get("status") in ("denied", "error"):
            flags.append("unresolved")
        if ptype == "User" and tier in (0, 1) and r["access"] == "Permanent":
            flags.append("human_standing")
        if ptype == "User" and (pr.get("userType") == "Guest"):
            flags.append("guest")
        if pr.get("accountEnabled") is False:
            flags.append("disabled")
        if ptype in ("User", "ServicePrincipal") and signin_known and tier in (0, 1):
            ds = days_since(last_sign_in) if last_sign_in else None
            created_days = days_since(pr.get("createdDateTime")) if ptype == "User" else None
            if (ds is not None and ds > STALE_SIGNIN_DAYS) or (ds is None and (created_days is None or created_days > STALE_SIGNIN_DAYS)):
                flags.append("stale")
        if ptype == "ServicePrincipal" and tier == 0:
            flags.append("nonhuman_tier0")
        if tier == 0 and r["role"] != "Owner" and not r["condition"]:
            flags.append("unconditioned_delegation")
        if tier == 0 and r["role"] != "Owner":
            if any(o is not r and o["tier"] == 1 and o["scope"].rstrip("/").lower() == r["scope"].rstrip("/").lower() for o in by_principal[r["principal_id"]]):
                flags.append("owner_equivalent")
        if tier == 1:
            if any(o is not r and o["tier"] == 0 and o["role"] != "Owner" and o["scope"].rstrip("/").lower() == r["scope"].rstrip("/").lower() for o in by_principal[r["principal_id"]]):
                flags.append("owner_equivalent")
        owner_org = (pr.get("appOwnerOrganizationId") or "").lower()
        if ptype == "ServicePrincipal" and pr.get("servicePrincipalType") == "Application" and owner_org and owner_org != tenant_id and owner_org not in MICROSOFT_TENANTS:
            flags.append("external_sp")
        if ptype == "Group" and (pr.get("member_count") or 0) > LARGE_GROUP_MEMBERS:
            flags.append("large_group")
        if r["scope_level"] in ("Management Group", "Subscription", "Root (/)") and tier in (0, 1):
            flags.append("broad_scope")
        flags = [f for f in FLAG_ORDER if f in flags]

        if decision is None:
            decision = "review" if flags else "ok"
            if decision == "review":
                reason = "; ".join(FLAG_LABEL[f] for f in flags) + "."
            else:
                reason = "Scoped role, resolved identity and no risk signals."
        if decision == "orphan":
            action = "Remove the assignment (identity no longer exists). No access impact."
        elif decision == "redundant":
            action = "Remove the duplicate assignment after approval. Effective access does not change."
        elif decision == "review":
            action = " ".join(FLAG_ACTION[f] for f in flags[:2])
        else:
            action = "Keep and review in the next cycle."

        portal = f"https://portal.azure.com/#@{tenant_id}/resource{r['scope']}/users" if r["scope"] and r["scope"] != "/" else ""
        rows.append({
            "decision": decision,
            "decision_label": {"orphan": "Remove · orphaned", "redundant": "Remove · redundant",
                               "review": "Individual review", "ok": "Compliant"}[decision],
            "reason": reason,
            "action": action,
            "flags": flags,
            "flag_labels": [FLAG_LABEL[f] for f in flags],
            "role": r["role"],
            "role_type": "Custom" if r["role_type"] == "CustomRole" else "Built-in",
            "tier": tier,
            "tier_label": TIER_LABEL[tier],
            "principal_name": name,
            "principal_type": type_label,
            "principal_detail": detail,
            "principal_id": r["principal_id"],
            "principal_status": pr.get("status"),
            "scope_level": r["scope_level"],
            "scope_label": r["scope_label"],
            "scope": r["scope"],
            "subscription": sub_names.get(r["subscription_id"] or "", r["subscription_id"] or ""),
            "access": r["access"],
            "end_date": r["end_date"],
            "condition": r["condition"],
            "last_sign_in": last_sign_in,
            "created_on": (r["created_on"] or "")[:10],
            "assignment_id": r["id"],
            "portal_url": portal,
        })

    decision_rank = {"orphan": 0, "redundant": 1, "review": 2, "ok": 3}
    rows.sort(key=lambda x: (decision_rank[x["decision"]], x["tier"], x["role"], x["scope_level"], x["principal_name"].lower()))

    # ------------------------------------------------------------------
    # 6) Metrics
    # ------------------------------------------------------------------
    dec_counts = Counter(r["decision"] for r in rows)
    owner_rows = [r for r in rows if r["role"] == "Owner"]
    owner_dec = Counter(r["decision"] for r in owner_rows)
    tier_counts = Counter(r["tier"] for r in rows)
    flag_counts = Counter(f for r in rows if r["decision"] == "review" for f in r["flags"])
    levels = ["Management Group", "Subscription", "Resource group", "Resource"]
    level_matrix = {lv: Counter(r["decision"] for r in rows if r["scope_level"] == lv) for lv in levels}
    standing = sum(1 for r in rows if r["access"] == "Permanent" and r["tier"] in (0, 1))
    tier01 = sum(1 for r in rows if r["tier"] in (0, 1))
    eligible_priv = 0
    for e in pim_eligible:
        guid = ((e.get("properties") or {}).get("roleDefinitionId") or "").split("/")[-1].lower()
        if tier_of(role_defs.get(guid)) in (0, 1):
            eligible_priv += 1
    princ_counter = Counter()
    princ_meta = {}
    for r in rows:
        if r["decision"] in ("review", "ok"):
            princ_counter[r["principal_id"]] += 1
            princ_meta[r["principal_id"]] = r
    top_principals = []
    for pid, n in princ_counter.most_common(8):
        m = princ_meta[pid]
        top_principals.append({"name": m["principal_name"], "type": m["principal_type"], "count": n,
                               "tier0": sum(1 for r in rows if r["principal_id"] == pid and r["tier"] == 0 and r["decision"] in ("review", "ok"))})

    graph_denied = sum(c.get("denied", 0) + c.get("error", 0) for c in graph_stats.values())
    arm_issues = [c for c in sub_coverage if c["role_assignments"]["status"] != "ok" or c["role_definitions"]["status"] != "ok"]
    status = "complete"
    if arm_issues or graph_denied or not graph_token:
        status = "partial"
    removable = dec_counts.get("orphan", 0) + dec_counts.get("redundant", 0)

    summary = {
        "reference_utc": reference_iso,
        "subscriptions": [{"id": c["subscription_id"], "name": c["name"]} for c in sub_coverage],
        "total_role_assignments": len(raw_rows),
        "privileged_assignments": len(rows),
        "by_tier": {TIER_LABEL[k]: v for k, v in sorted(tier_counts.items())},
        "decisions": {"remove_orphaned": dec_counts.get("orphan", 0), "remove_redundant": dec_counts.get("redundant", 0),
                      "individual_review": dec_counts.get("review", 0), "compliant": dec_counts.get("ok", 0)},
        "owner": {"total": len(owner_rows), "remove_orphaned": owner_dec.get("orphan", 0),
                  "remove_redundant": owner_dec.get("redundant", 0), "individual_review": owner_dec.get("review", 0),
                  "compliant": owner_dec.get("ok", 0)},
        "removable_without_access_change": removable,
        "standing_tier01_percent": round(100 * standing / tier01) if tier01 else 0,
        "pim_eligible_privileged": eligible_priv,
        "review_signals": {FLAG_LABEL[k]: v for k, v in flag_counts.most_common()},
        "distinct_principals": len({r["principal_id"] for r in rows}),
    }
    coverage = {
        "status": status,
        "subscriptions": sub_coverage,
        "graph_token": "ok" if graph_token else f"unavailable ({graph_token_error})",
        "graph_identities": {k: dict(v) for k, v in graph_stats.items()},
        "user_sign_in_activity": signin_user_status,
        "service_principal_sign_in_activity": signin_sp_status,
        "group_membership": membership_status,
    }

    # ------------------------------------------------------------------
    # 7) Files: HTML, CSV and JSON
    # ------------------------------------------------------------------
    base = f"rbac-privileged-access-review-{report_date}"
    csv_buf = io.StringIO()
    writer = csv.writer(csv_buf)
    headers = ["decision", "reason", "recommended_action", "signals", "role", "role_type", "privilege_tier",
               "identity", "identity_type", "upn_or_appid", "principal_id", "identity_status",
               "scope_level", "scope", "subscription", "access", "end", "condition", "last_sign_in",
               "created", "assignment_id", "portal_iam"]
    writer.writerow(headers)
    for r in rows:
        writer.writerow([r["decision_label"], r["reason"], r["action"], " | ".join(r["flag_labels"]), r["role"], r["role_type"],
                         r["tier_label"], r["principal_name"], r["principal_type"], r["principal_detail"], r["principal_id"],
                         r["principal_status"], r["scope_level"], r["scope"], r["subscription"], r["access"], r["end_date"] or "",
                         "yes" if r["condition"] else "no", r["last_sign_in"] or "", r["created_on"], r["assignment_id"], r["portal_url"]])
    csv_text = "\ufeff" + csv_buf.getvalue()
    json_doc = {"report": "Azure RBAC privileged access review", "read_only": True}
    if org_name:
        json_doc["organization"] = org_name
    json_doc.update({"summary": summary, "coverage": coverage, "assignments": rows})
    json_text = json.dumps(json_doc, ensure_ascii=False, indent=2)

    def esc(v):
        return html.escape(str(v if v is not None else ""))

    def pct(n, d):
        return f"{(100 * n / d):.0f}%" if d else "0%"

    total = len(rows)
    seg = ""
    for key, label in (("orphan", "Orphaned"), ("redundant", "Redundant"), ("review", "Individual review"), ("ok", "Compliant")):
        n = dec_counts.get(key, 0)
        if n:
            seg += f'<span class="seg d-{key}" style="flex:{n}" title="{esc(label)}: {n}"><b>{n}</b></span>'
    legend = "".join(
        f'<span class="lg"><i class="dot d-{k}"></i>{esc(l)} <b>{dec_counts.get(k, 0)}</b></span>'
        for k, l in (("orphan", "Remove · orphaned"), ("redundant", "Remove · redundant"), ("review", "Individual review"), ("ok", "Compliant")))

    level_rows = ""
    for lv in levels:
        c = level_matrix[lv]
        tot = sum(c.values())
        if not tot:
            continue
        level_rows += (f"<tr><th>{esc(lv)}</th><td class='n'>{tot}</td><td class='n c-orphan'>{c.get('orphan', 0) or '·'}</td>"
                       f"<td class='n c-redundant'>{c.get('redundant', 0) or '·'}</td><td class='n c-review'>{c.get('review', 0) or '·'}</td>"
                       f"<td class='n c-ok'>{c.get('ok', 0) or '·'}</td></tr>")

    maxflag = max(flag_counts.values()) if flag_counts else 1
    flag_bars = "".join(
        f"<div class='bar'><span class='bl'>{esc(FLAG_LABEL[k])}</span><span class='bt'><i style='width:{max(4, 100 * v / maxflag):.0f}%'></i></span><b>{v}</b></div>"
        for k, v in flag_counts.most_common()) or "<p class='muted'>No risk signals in the current assignments.</p>"

    top_html = "".join(
        f"<li><span class='who'>{esc(t['name'])}<small>{esc(t['type'])}</small></span><span class='cnt'>{t['count']}<small>{t['tier0']} tier 0</small></span></li>"
        for t in top_principals) or "<li class='muted'>No identities with current privileged access.</li>"

    def chip(status_text):
        s = str(status_text).lower()
        cls = "ok" if s in ("ok", "no privileged groups") else ("warn" if s.startswith(("partial", "not evaluated")) else "bad")
        return f"<span class='st st-{cls}'>{esc(status_text)}</span>"

    cov_rows = ""
    for c in sub_coverage:
        cov_rows += (f"<tr><th>{esc(c['name'])}</th><td>{chip(c['role_assignments']['status'])} {c['role_assignments']['count']}</td>"
                     f"<td>{chip(c['role_definitions']['status'])} {c['role_definitions']['count']}</td>"
                     f"<td>{chip(c['pim_active']['status'])} {c['pim_active']['count']}</td>"
                     f"<td>{chip(c['pim_eligible']['status'])} {c['pim_eligible']['count']}</td></tr>")
    graph_rows = ""
    for kind in ("Users", "Groups", "Apps and identities", "Other"):
        c = graph_stats.get(kind)
        if not c:
            continue
        graph_rows += (f"<tr><th>{esc(kind)}</th><td class='n'>{c.get('resolved', 0)}</td><td class='n{' c-orphan' if c.get('orphaned') else ''}'>{c.get('orphaned', 0)}</td>"
                       f"<td class='n'>{c.get('denied', 0) + c.get('error', 0)}</td></tr>")

    owner_total = len(owner_rows)
    owner_removable = owner_dec.get("orphan", 0) + owner_dec.get("redundant", 0)
    status_label = "Full coverage" if status == "complete" else "Partial coverage"
    sub_list = ", ".join(c["name"] for c in sub_coverage)
    data_json = json.dumps(rows, ensure_ascii=False).replace("</", "<\\/")

    logo_uri = (LOGO_DATA_URI or "").strip()
    if logo_uri.startswith("data:image/"):
        logo_html = f'<img class="logo" src="{esc(logo_uri)}" alt="{esc(org_name or "Organization logo")}">'
    else:
        logo_html = ('<span class="wm" role="img" aria-label="Azure SRE Agent"><svg viewBox="0 0 24 24" aria-hidden="true">'
                     '<path d="M9.2 3h5.6l6.2 18h-4.5l-1.5-4.6H8.4L9.9 12h3.8L12 6.6 6.4 21H2z" fill="currentColor"/></svg>'
                     '<span>Azure SRE Agent</span></span>')
    title_prefix = esc(org_name) + " · " if org_name else ""
    footer_org = " · Internal use · " + esc(org_name) if org_name else ""

    html_doc = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>__TITLE_PREFIX__Azure RBAC privileged access review · __DATE__</title>
<style>
:root{--ink:#1B1F24;--navy:#243A5E;--navy2:#1B2C48;--accent:#0F6CBD;--accent2:#0C5A9E;--sky:#7CC3FF;--bg:#F3F5F8;--card:#fff;--text:#1B1F24;--muted:#57606A;--line:#DCE1E7;
--orphan:#C4314B;--redundant:#C25200;--review:#0F6CBD;--ok:#107C10}
*{box-sizing:border-box}html,body{margin:0}body{font-family:"Segoe UI",system-ui,-apple-system,Roboto,Arial,sans-serif;background:var(--bg);color:var(--text);font-size:14px;line-height:1.45}
.top{background:var(--ink);display:flex;align-items:center;justify-content:space-between;gap:12px;padding:14px 40px;position:sticky;top:0;z-index:5}
.top img.logo{height:34px;display:block}.top .tag{color:#C9D1D9;font-size:12px;letter-spacing:.04em;display:flex;gap:10px;align-items:center}
.wm{display:inline-flex;align-items:center;gap:10px;color:#fff;font-weight:600;font-size:18px;letter-spacing:.01em;white-space:nowrap}
.wm svg{width:30px;height:30px;padding:5px;border-radius:8px;background:linear-gradient(135deg,#0F6CBD,#2899F5);color:#fff;flex:none}
.pill{white-space:nowrap;border:1px solid #3D4651;border-radius:999px;padding:5px 12px;color:#E6EAEF}.pill.accent{background:var(--accent);border-color:var(--accent);color:#fff;font-weight:600}
.hero{background:linear-gradient(180deg,var(--navy) 0%,var(--navy2) 100%);color:#fff;padding:42px 40px 34px}
.eyebrow{color:var(--sky);font-weight:700;letter-spacing:.14em;font-size:12px;text-transform:uppercase}
h1{font-size:40px;line-height:1.08;margin:10px 0 10px;font-weight:700;letter-spacing:-.01em}
.lead{max-width:880px;color:#D5DEEA;font-size:16px;margin:0}
.lead b{color:#fff}
.meta{display:flex;flex-wrap:wrap;gap:8px;margin:18px 0 26px}.meta span{background:rgba(255,255,255,.07);border:1px solid rgba(255,255,255,.14);border-radius:8px;padding:6px 10px;font-size:12px;color:#DDE5EF}
.big{display:grid;grid-template-columns:repeat(3,1fr);gap:16px;max-width:1100px}
.big div{background:rgba(255,255,255,.06);border:1px solid rgba(255,255,255,.12);border-left:5px solid var(--sky);border-radius:12px;padding:16px 18px}
.big div:nth-child(2){border-left-color:#FF8C42}.big div:nth-child(3){border-left-color:#4FA3F7}
.big b{display:block;font-size:46px;font-weight:700;line-height:1}.big span{color:#C9D4E2;font-size:13px}
.decbar{display:flex;height:34px;border-radius:9px;overflow:hidden;margin:26px 0 10px;max-width:1100px;background:#152238}
.seg{display:flex;align-items:center;justify-content:center;color:#fff;font-size:13px;min-width:34px}.seg b{font-weight:700}
.d-orphan{background:var(--orphan)}.d-redundant{background:var(--redundant)}.d-review{background:var(--review)}.d-ok{background:var(--ok)}
.legend{display:flex;flex-wrap:wrap;gap:18px;color:#D5DEEA;font-size:13px}.lg{display:flex;align-items:center;gap:7px}.lg b{color:#fff}
.dot{width:11px;height:11px;border-radius:3px;display:inline-block}
main{padding:28px 40px 40px;max-width:1440px}
.kpis{display:grid;grid-template-columns:repeat(6,1fr);gap:14px;margin-bottom:22px}
.kpi{background:var(--card);border:1px solid var(--line);border-radius:12px;padding:14px 16px}
.kpi b{display:block;font-size:28px;font-weight:700;color:var(--ink)}.kpi span{color:var(--muted);font-size:12.5px}
.kpi.hl{border-top:4px solid var(--accent)}
.grid2{display:grid;grid-template-columns:1.15fr 1fr;gap:18px;margin-bottom:18px}
.grid2>*{min-width:0}.card{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:20px 22px}
h2{font-size:18px;margin:0 0 4px;color:var(--ink);font-weight:700}.sub{color:var(--muted);margin:0 0 14px;font-size:13px}
table{border-collapse:collapse;width:100%}th,td{padding:8px 10px;border-bottom:1px solid var(--line);text-align:left;vertical-align:top}
thead th{font-size:11.5px;text-transform:uppercase;letter-spacing:.06em;color:var(--muted);font-weight:700;background:#F6F8FA}
td.n,th.n{text-align:right;font-variant-numeric:tabular-nums}.c-orphan{color:var(--orphan);font-weight:700}.c-redundant{color:var(--redundant);font-weight:700}.c-review{color:var(--accent);font-weight:700}.c-ok{color:var(--ok);font-weight:700}
.bar{display:grid;grid-template-columns:minmax(180px,1.4fr) 1fr 34px;gap:10px;align-items:center;margin:9px 0;font-size:13px}
.bt{background:#E8EDF3;border-radius:6px;height:12px;overflow:hidden}.bt i{display:block;height:100%;background:var(--accent);border-radius:6px}.bar b{text-align:right}
.top8{list-style:none;margin:0;padding:0}.top8 li{display:flex;justify-content:space-between;align-items:center;gap:12px;padding:9px 0;border-bottom:1px solid var(--line)}
.who{min-width:0;overflow-wrap:anywhere}.cnt{flex:none}.who small,.cnt small{display:block;color:var(--muted);font-size:11.5px}.cnt{text-align:right;font-weight:700;font-size:18px}
.filters{display:flex;flex-wrap:wrap;gap:10px;margin:6px 0 14px;align-items:center}
.filters input,.filters select{border:1px solid #C3CCD6;border-radius:8px;padding:8px 10px;font:inherit;background:#fff;min-width:150px}
.filters input{min-width:260px}.btn{background:var(--accent);color:#fff;border:0;border-radius:999px;padding:9px 16px;font-weight:600;cursor:pointer;font:inherit;font-weight:600}
.btn:hover{background:var(--accent2)}.btn.ghost{background:#fff;color:var(--ink);border:1px solid #C3CCD6}.btn.ghost:hover{background:#F3F5F8}.count{color:var(--muted);margin-left:auto;font-size:13px}
.regwrap{overflow-x:auto}.reg{table-layout:fixed;min-width:1040px}
.reg th{cursor:pointer;white-space:nowrap}.reg th.sorted:after{content:" ▾"}.reg th.sorted.asc:after{content:" ▴"}
.reg td{font-size:13px;line-height:1.4;padding:11px 10px}.reg td .small,.reg td .tier{display:block}.reg td .tier{width:max-content;max-width:100%}
.reg tr.r-orphan td:first-child{box-shadow:inset 3px 0 0 var(--orphan)}.reg tr.r-redundant td:first-child{box-shadow:inset 3px 0 0 var(--redundant)}.reg tr.r-review td:first-child{box-shadow:inset 3px 0 0 var(--review)}.reg tr.r-ok td:first-child{box-shadow:inset 3px 0 0 var(--ok)}
.reg tbody tr:hover{background:#FAFBFC}.brk{overflow-wrap:anywhere}.nm{overflow-wrap:anywhere}.why{color:#3B4450}.flags{margin-top:-2px}
.more{text-align:center;margin-top:14px}
.badge{display:inline-block;border-radius:999px;padding:3px 10px;font-size:12px;font-weight:700;color:#fff;white-space:nowrap}
.b-orphan{background:var(--orphan)}.b-redundant{background:var(--redundant)}.b-review{background:var(--review)}.b-ok{background:var(--ok)}
.tier{display:inline-block;font-size:11px;border-radius:6px;padding:1px 7px;margin-top:3px;font-weight:700}.t0{background:#FDE7EA;color:#A4262C}.t1{background:#FFF0E0;color:#8A3B00}.t2{background:#E5F1FB;color:#0B4F8A}
.flag{display:inline-block;background:#F1F4F7;border:1px solid #DFE4EA;border-radius:6px;padding:2px 7px;font-size:11.5px;margin:2px 3px 2px 0}
.muted{color:var(--muted)}.small{font-size:12px;color:var(--muted)}a{color:var(--accent)}a.iam{white-space:nowrap;font-weight:700;text-decoration:none}
.st{display:inline-block;border-radius:6px;padding:1px 8px;font-size:12px;font-weight:700}.st-ok{background:#DFF6DD;color:#0E5C0E}.st-warn{background:#FFF0E0;color:#8A3B00}.st-bad{background:#FDE7EA;color:#A4262C}
.steps{counter-reset:s;list-style:none;padding:0;margin:0}.steps li{counter-increment:s;position:relative;padding:0 0 12px 40px}
.steps li:before{content:counter(s);position:absolute;left:0;top:0;width:26px;height:26px;border-radius:50%;background:var(--accent);color:#fff;font-weight:700;display:flex;align-items:center;justify-content:center}
.note{background:#F3F7FB;border-left:4px solid var(--accent);padding:10px 14px;border-radius:6px;font-size:13px;margin-top:10px}
footer{background:var(--ink);color:#AEB8C3;padding:22px 40px;font-size:12px;display:flex;justify-content:space-between;align-items:center;gap:20px;flex-wrap:wrap}
footer img.logo{height:22px;display:block}footer .wm{font-size:14px;gap:8px}footer .wm svg{width:22px;height:22px;padding:4px;border-radius:6px}
@media (max-width:1100px){.kpis{grid-template-columns:repeat(3,1fr)}.grid2{grid-template-columns:1fr}}
@media (max-width:640px){.top,.hero,main,footer{padding-left:16px;padding-right:16px}.top img.logo{height:30px}.top .wm{font-size:16px}.top .wm svg{width:26px;height:26px}.pill{font-size:11px;padding:5px 9px}.tag .pill:first-child{display:none}h1{font-size:28px}.big{grid-template-columns:1fr}.kpis{grid-template-columns:repeat(2,1fr)}
.card>table{display:block;overflow-x:auto}.card th,.card td{padding:7px 6px}.reg{min-width:0}.reg colgroup{display:none}.reg thead{display:none}.reg tr{display:block;border:1px solid var(--line);border-radius:10px;margin-bottom:10px;padding:8px 6px;background:#fff}.reg td{display:block;border:0;padding:4px 8px}.reg td:empty{display:none}.reg tr td:first-child{box-shadow:none!important}
.filters input,.filters select{min-width:0;width:100%}.filters .btn{flex:1}.count{margin-left:0;width:100%}.meta span{white-space:normal}.bar{grid-template-columns:1fr 70px 26px}}
@media print{.top{position:static}.filters,.btn{display:none}}
</style></head><body>
<header class="top">__LOGO__<div class="tag"><span class="pill">Azure RBAC · Microsoft Entra ID</span><span class="pill accent">Read only</span></div></header>
<section class="hero">
<div class="eyebrow">Access governance · Azure RBAC</div>
<h1>Privileged access review</h1>
<p class="lead">Of <b>__TOTAL__ privileged assignments</b>, <b>__REMOVABLE__ can be removed without changing effective access</b> (deleted identities or duplicated permissions) and <b>__REVIEW__ need an individual review</b> with their owner.</p>
<div class="meta"><span>Reference date: __REF__</span><span>Subscriptions: __SUBS__</span><span>__STATUS__</span><span>Managed identity · Reader + Graph read</span></div>
<div class="big">
<div><b>__OWNER__</b><span>Owner assignments analyzed</span></div>
<div><b>__OWNER_RM__</b><span>Owner assignments removable without access loss (orphaned + redundant)</span></div>
<div><b>__OWNER_RV__</b><span>Owner assignments for individual review</span></div>
</div>
<div class="decbar">__SEG__</div>
<div class="legend">__LEGEND__</div>
</section>
<main>
<div class="kpis">
<div class="kpi hl"><b>__ALL__</b><span>role assignments inventoried</span></div>
<div class="kpi"><b>__TOTAL__</b><span>privileged (tier 0, 1 and 2)</span></div>
<div class="kpi"><b>__T0__</b><span>tier 0 · can grant access</span></div>
<div class="kpi"><b>__PRINC__</b><span>identities with privileges</span></div>
<div class="kpi"><b>__STANDING__</b><span>of tier 0/1 is standing access</span></div>
<div class="kpi"><b>__ELIG__</b><span>privileged PIM eligibilities</span></div>
</div>
<div class="grid2">
<div class="card"><h2>Decision by scope level</h2><p class="sub">Where privileged access is concentrated and what to do with it.</p>
<table><thead><tr><th>Level</th><th class="n">Total</th><th class="n">Orphaned</th><th class="n">Redundant</th><th class="n">Review</th><th class="n">Compliant</th></tr></thead><tbody>__LEVELS__</tbody></table>
<div class="note">A <b>redundant</b> assignment repeats a permission the identity already receives without condition from a higher scope, at the same scope or through a group. Removing it does not change effective access.</div></div>
<div class="card"><h2>Individual review signals</h2><p class="sub">Why a current assignment needs validation by its owner.</p>__FLAGS__</div>
</div>
<div class="grid2">
<div class="card"><h2>Identities with the most current privileges</h2><p class="sub">Assignments under review or compliant per identity, excluding those that can be removed.</p><ul class="top8">__TOP__</ul></div>
<div class="card"><h2>Next steps · 30-day pilot</h2><p class="sub">The agent proposes; people approve. No change is executed automatically.</p>
<ol class="steps">
<li><b>Risk-free cleanup.</b> Remove the __REMOVABLE__ orphaned or redundant assignments through an approved change. Effective access does not change.</li>
<li><b>Human access to PIM.</b> Convert users' standing privilege into eligibility with JIT activation, MFA and approval.</li>
<li><b>Non-human identities.</b> Replace Owner/UAA on applications and managed identities with least-privilege roles (Role Designer).</li>
<li><b>Groups by function and scope.</b> Assign through groups separated by environment and subscription, never to individual users at Management Group level.</li>
<li><b>Periodic review.</b> Schedule this monthly review in the SRE Agent and track how the indicators evolve.</li>
</ol></div>
</div>
<div class="card regcard" style="margin-bottom:18px">
<h2>Privileged assignment register</h2><p class="sub">Filter, sort and export. Each row links to the scope's access control (IAM) blade in the Azure portal.</p>
<div class="filters">
<input id="q" type="search" placeholder="Search identity, role or scope…" aria-label="Search">
<select id="fd" aria-label="Decision"><option value="">All decisions</option><option value="orphan">Remove · orphaned</option><option value="redundant">Remove · redundant</option><option value="review">Individual review</option><option value="ok">Compliant</option></select>
<select id="ft" aria-label="Privilege tier"><option value="">All tiers</option><option value="0">Tier 0 · Access control</option><option value="1">Tier 1 · Full control</option><option value="2">Tier 2 · Service admin</option></select>
<select id="fp" aria-label="Identity type"><option value="">All identities</option><option>User</option><option>Group</option><option>Application</option><option>Managed identity</option><option>Unknown</option></select>
<select id="fl" aria-label="Scope"><option value="">All scopes</option><option>Management Group</option><option>Subscription</option><option>Resource group</option><option>Resource</option></select>
<button class="btn" id="csv">Export filtered CSV</button><button class="btn ghost" id="rst">Clear</button><span class="count" id="cnt"></span>
</div>
<div class="regwrap"><table class="reg" id="reg"><colgroup><col style="width:150px"><col style="width:150px"><col style="width:22%"><col style="width:15%"><col><col style="width:19%"><col style="width:64px"></colgroup><thead><tr>
<th data-k="decision">Decision</th><th data-k="role">Role and access</th><th data-k="principal_name">Identity</th><th data-k="scope_label">Scope</th><th data-k="flags">Reason and signals</th><th data-k="action">Recommended action</th><th>IAM</th>
</tr></thead><tbody id="body"></tbody></table></div>
<div class="more"><button class="btn ghost" id="more">Show more</button></div>
</div>
<div class="grid2">
<div class="card"><h2>Review coverage</h2><p class="sub">Anything that could not be read is a blind spot, never a clean result.</p>
<table><thead><tr><th>Subscription</th><th>Assignments</th><th>Definitions</th><th>PIM active</th><th>PIM eligible</th></tr></thead><tbody>__COV__</tbody></table></div>
<div class="card"><h2>Identity resolution</h2><p class="sub">Microsoft Entra ID through Microsoft Graph (read only).</p>
<table><thead><tr><th>Identities (Graph)</th><th class="n">Resolved</th><th class="n">Orphaned</th><th class="n">No permission</th></tr></thead><tbody>__GRAPH__</tbody></table>
<p class="small" style="margin-top:10px">User sign-in: __SIU__ · Application sign-in: __SIS__ · Group membership: __MEM__</p></div>
</div>
<p class="small">Method: inventory of Azure RBAC assignments per subscription (including those inherited from Management Groups), role classification by its permissions (tier 0 = can write role assignments; tier 1 = full control-plane control; tier 2 = service administration roles), identity resolution in Microsoft Entra ID, PIM state and sign-in activity. An assignment is only marked as redundant when another permanent, unconditioned assignment of the same identity (or of a group it belongs to) already covers all its permissions at the same or a higher scope.</p>
</main>
<footer>__LOGO__<span>Report generated by Azure SRE Agent · read only · __REF____FOOTER_ORG__</span></footer>
<script>
const DATA=__DATA__;
const L={orphan:"Remove · orphaned",redundant:"Remove · redundant",review:"Individual review",ok:"Compliant"};
const R={orphan:0,redundant:1,review:2,ok:3};
let sortK="decision",asc=true,limit=20;
const PAGE=20;
const $=id=>document.getElementById(id);
const e=s=>String(s??"").replace(/[&<>"]/g,c=>({"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;"}[c]));
function rows(){const q=$("q").value.toLowerCase(),d=$("fd").value,t=$("ft").value,p=$("fp").value,l=$("fl").value;
return DATA.filter(r=>(!d||r.decision===d)&&(!t||String(r.tier)===t)&&(!p||r.principal_type===p)&&(!l||r.scope_level===l)&&
(!q||[r.principal_name,r.principal_detail,r.role,r.scope_label,r.scope,r.reason].join(" ").toLowerCase().includes(q)))
.sort((a,b)=>{let x=a[sortK],y=b[sortK];if(sortK==="decision"){x=R[x];y=R[y]}if(sortK==="flags"){x=a.flags.length;y=b.flags.length}
if(x<y)return asc?-1:1;if(x>y)return asc?1:-1;return 0})}
function render(){const all=rows(),rs=all.slice(0,limit);$("cnt").textContent=(all.length>rs.length?rs.length+" shown · ":"")+all.length+" of "+DATA.length+" assignments";
$("more").parentNode.style.display=all.length>rs.length?"":"none";$("more").textContent="Show "+Math.min(PAGE,all.length-rs.length)+" more";
$("body").innerHTML=rs.map(r=>`<tr class="r-${r.decision}"><td data-h="Decision"><span class="badge b-${r.decision}">${L[r.decision]}</span></td>
<td data-h="Role"><b>${e(r.role)}</b><span class="tier t${r.tier}">${e(r.tier_label)}</span><span class="small">${e(r.access)}${r.end_date?' until '+e(r.end_date):''}${r.condition?' · with condition':''}</span></td>
<td data-h="Identity"><b class="nm">${e(r.principal_name)}</b><span class="small brk">${e(r.principal_type)}${r.principal_detail?" · "+e(r.principal_detail):""}</span>${r.last_sign_in?'<span class="small">Last sign-in: '+e(r.last_sign_in)+'</span>':''}</td>
<td data-h="Scope"><span class="brk">${e(r.scope_label)}</span><span class="small">${e(r.scope_level)}</span></td>
<td data-h="Reason">${r.decision==="review"&&r.flag_labels.length?'<div class="flags">'+r.flag_labels.map(f=>'<span class="flag">'+e(f)+'</span>').join("")+'</div>':'<div class="why">'+e(r.reason)+'</div>'}</td>
<td data-h="Action">${e(r.action)}</td><td data-h="IAM">${r.portal_url?'<a class="iam" target="_blank" rel="noopener" href="'+e(r.portal_url)+'" title="Open the scope access control (IAM)">Open ↗</a>':''}</td></tr>`).join("")||'<tr><td colspan="7" class="muted">No results for the current filter.</td></tr>';
document.querySelectorAll(".reg th[data-k]").forEach(th=>{th.classList.toggle("sorted",th.dataset.k===sortK);th.classList.toggle("asc",th.dataset.k===sortK&&asc)})}
document.querySelectorAll(".reg th[data-k]").forEach(th=>th.addEventListener("click",()=>{if(sortK===th.dataset.k)asc=!asc;else{sortK=th.dataset.k;asc=true}render()}));
["q","fd","ft","fp","fl"].forEach(id=>{const f=()=>{limit=PAGE;render()};$(id).addEventListener("input",f);$(id).addEventListener("change",f)});
$("more").onclick=()=>{limit+=PAGE;render()};
$("rst").onclick=()=>{["q","fd","ft","fp","fl"].forEach(id=>$(id).value="");limit=PAGE;render()};
$("csv").onclick=()=>{const h=["decision","role","tier","identity","type","upn_or_appid","scope","scope_level","access","signals","reason","action","assignment_id","portal_iam"];
const c=v=>'"'+String(v??"").replace(/"/g,'""')+'"';
const lines=[h.join(",")].concat(rows().map(r=>[L[r.decision],r.role,r.tier_label,r.principal_name,r.principal_type,r.principal_detail,r.scope,r.scope_level,r.access,r.flag_labels.join(" | "),r.reason,r.action,r.assignment_id,r.portal_url].map(c).join(",")));
const a=document.createElement("a");a.href=URL.createObjectURL(new Blob(["\\ufeff"+lines.join("\\r\\n")],{type:"text/csv;charset=utf-8"}));a.download="rbac-privileged-access-filtered.csv";a.click();URL.revokeObjectURL(a.href)};
render();
</script></body></html>"""
    repl = {
        "__TITLE_PREFIX__": title_prefix, "__FOOTER_ORG__": footer_org,
        "__DATE__": esc(report_date), "__LOGO__": logo_html, "__TOTAL__": str(total), "__REMOVABLE__": str(removable),
        "__REVIEW__": str(dec_counts.get("review", 0)), "__REF__": esc(reference_iso.replace("T", " ").replace("Z", " UTC")),
        "__SUBS__": esc(sub_list), "__STATUS__": esc(status_label), "__OWNER__": str(owner_total), "__OWNER_RM__": str(owner_removable),
        "__OWNER_RV__": str(owner_dec.get("review", 0)), "__SEG__": seg, "__LEGEND__": legend, "__ALL__": str(len(raw_rows)),
        "__T0__": str(tier_counts.get(0, 0)), "__PRINC__": str(summary["distinct_principals"]),
        "__STANDING__": f"{summary['standing_tier01_percent']}%", "__ELIG__": str(eligible_priv), "__LEVELS__": level_rows,
        "__FLAGS__": flag_bars, "__TOP__": top_html, "__COV__": cov_rows, "__GRAPH__": graph_rows,
        "__SIU__": chip(signin_user_status), "__SIS__": chip(signin_sp_status), "__MEM__": chip(membership_status),
    }
    for k, v in repl.items():
        html_doc = html_doc.replace(k, v)
    html_doc = html_doc.replace("__DATA__", data_json)

    files = {"report": (base + ".html", html_doc), "csv": (base + ".csv", csv_text), "json": (base + ".json", json_text)}
    out = {}
    try:
        os.makedirs("/mnt/data", exist_ok=True)
        cwd = Path.cwd()
        match = re.fullmatch(r"/(?:root/sreagent|usr)/terminalRoot/tmp/ThreadFiles/([0-9a-fA-F-]{36})", cwd.as_posix())
        for key, (fname, content) in files.items():
            with open(os.path.join("/mnt/data", fname), "w", encoding="utf-8") as fh:
                fh.write(content)
            (cwd / fname).write_text(content, encoding="utf-8")
            out[key + "_path"] = str(cwd / fname) if match else os.path.join("/mnt/data", fname)
            if match:
                out[key + "_url"] = f"/api/files/tmp/ThreadFiles/{match.group(1)}/{quote(fname, safe='')}"
    except Exception as exc:
        return fail(f"Could not write the report files: {type(exc).__name__}")

    # Compact response: the full detail goes into the files, not into the tool output.
    compact_summary = {k: v for k, v in summary.items() if k not in ("subscriptions", "reference_utc")}
    compact_summary["review_signals"] = dict(list(summary["review_signals"].items())[:6])
    compact_coverage = {
        "status": status,
        "subscriptions": [{"name": c.get("name"), "role_assignments": c["role_assignments"]["status"]} for c in sub_coverage],
        "graph_token": coverage["graph_token"],
        "graph_identities": coverage["graph_identities"],
        "user_sign_in_activity": signin_user_status,
        "service_principal_sign_in_activity": signin_sp_status,
        "group_membership": membership_status,
    }
    return {
        "status": status,
        **out,
        "summary": compact_summary,
        "coverage": compact_coverage,
        "top_review_items": [
            {k: r[k] for k in ("decision_label", "role", "principal_name", "scope_label")}
            for r in rows if r["decision"] in ("orphan", "redundant", "review")][:5],
    }
