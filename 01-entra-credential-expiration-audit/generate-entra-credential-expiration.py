# generate-entra-credential-expiration
# Python tool for Azure SRE Agent: Microsoft Entra credential expiration audit.
# Read-only. Before you paste it into the Code tab, replace <YOUR_AGENT_CLIENT_ID>
# with the Client ID of your agent's managed identity (Step 0 of the guide).
# Version 1.1 · October 2026

def main() -> dict:
    """Audit Microsoft Entra credential expiration for applications and service principals."""
    import html
    import json
    import os
    from collections import Counter
    from datetime import datetime, timezone
    from typing import Any, Dict, List, Optional
    import requests
    # ------------------------------------------------------------------
    # REQUIRED CONFIGURATION
    # Replace the value with the Client ID of the user-assigned managed
    # identity of YOUR Azure SRE Agent (Step 0 of the guide).
    # A Client ID is not a secret.
    # ------------------------------------------------------------------
    MANAGED_IDENTITY_CLIENT_ID = "<YOUR_AGENT_CLIENT_ID>"

    def fail(message: str) -> dict:
        return {"error": message, "coverage": "partial"}

    if not MANAGED_IDENTITY_CLIENT_ID or MANAGED_IDENTITY_CLIENT_ID.startswith("<"):
        return fail(
            "Configuration required: set MANAGED_IDENTITY_CLIENT_ID to the "
            "Client ID of your Azure SRE Agent user-assigned managed identity."
        )

    try:
        from azure.identity import ManagedIdentityCredential
        credential = ManagedIdentityCredential(
            client_id=MANAGED_IDENTITY_CLIENT_ID
        )
        graph_token = credential.get_token(
            "https://graph.microsoft.com/.default"
        ).token
    except Exception as exc:
        return fail(f"Failed to acquire Microsoft Graph token: {exc}")
    now_utc = datetime.now(timezone.utc)
    reference_date = now_utc.date()
    reference_iso = now_utc.strftime("%Y-%m-%dT%H:%M:%SZ")
    session = requests.Session()
    session.headers.update({
        "Authorization": f"Bearer {graph_token}",
        "Accept": "application/json",
    })
    def parse_datetime(value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    def classify(days_remaining: Optional[int]) -> str:
        if days_remaining is None:
            return "UNKNOWN"
        if days_remaining <= 0:
            return "EXPIRED"
        if days_remaining <= 7:
            return "CRITICAL"
        if days_remaining <= 30:
            return "EXPIRING SOON"
        if days_remaining <= 90:
            return "EXPIRING"
        return "Valid"
    def fetch_all(url: str) -> List[Dict[str, Any]]:
        items: List[Dict[str, Any]] = []
        next_url = url
        while next_url:
            response = session.get(next_url, timeout=60)
            if response.status_code in (401, 403):
                raise RuntimeError(
                    f"Microsoft Graph authorization failed: HTTP {response.status_code}."
                )
            if not response.ok:
                raise RuntimeError(
                    f"Microsoft Graph request failed: HTTP {response.status_code}."
                )
            payload = response.json()
            if not isinstance(payload, dict) or "value" not in payload:
                raise RuntimeError(
                    "Unexpected response format returned by Microsoft Graph."
                )
            items.extend(payload.get("value") or [])
            next_url = payload.get("@odata.nextLink")
        return items
    applications_url = (
        "https://graph.microsoft.com/v1.0/applications"
        "?$select=displayName,appId,id,passwordCredentials,keyCredentials"
        "&$top=999"
    )
    service_principals_url = (
        "https://graph.microsoft.com/v1.0/servicePrincipals"
        "?$select=displayName,appId,id,servicePrincipalType,"
        "passwordCredentials,keyCredentials"
        "&$top=999"
    )
    try:
        applications = fetch_all(applications_url)
        all_service_principals = fetch_all(service_principals_url)
    except Exception as exc:

        return fail(str(exc))
    service_principals = []
    managed_identity_excluded_count = 0
    for service_principal in all_service_principals:
        if service_principal.get("servicePrincipalType") == "ManagedIdentity":
            managed_identity_excluded_count += 1
            continue
        service_principals.append(service_principal)
    rows: List[Dict[str, Any]] = []
    status_counter = Counter()
    def add_credential_rows(source_object: Dict[str, Any], object_type: str) -> None:
        object_name = source_object.get("displayName") or ""
        app_id = source_object.get("appId") or ""
        object_id = source_object.get("id") or ""
        credential_sets = [
            ("passwordCredential", source_object.get("passwordCredentials") or []),
            ("keyCredential", source_object.get("keyCredentials") or []),
        ]
        for credential_type, credentials in credential_sets:
            for credential_item in credentials:
                expiration = parse_datetime(credential_item.get("endDateTime"))
                days_remaining = (
                    None if expiration is None
                    else (expiration.date() - reference_date).days
                )
                status = classify(days_remaining)
                status_counter[status] += 1
                rows.append({
                    "credentialName": credential_item.get("displayName") or "",
                    "type": credential_type,
                    "objectType": object_type,
                    "objectName": object_name,
                    "appId": app_id,
                    "objectId": object_id,
                    "expirationUtc": (
                        expiration.strftime("%Y-%m-%dT%H:%M:%SZ")
                        if expiration else ""
                    ),
                    "daysRemaining": (
                        days_remaining if days_remaining is not None else ""
                    ),
                    "status": status,
                    "actionUrl": (
                        "https://entra.microsoft.com/"
                        "#view/Microsoft_AAD_RegisteredApps/"
                        f"ApplicationMenuBlade/~/Overview/appId/{app_id}"
                        if app_id else ""
                    ),
                })
    for application in applications:
        add_credential_rows(application, "Application")
    for service_principal in service_principals:
        add_credential_rows(service_principal, "Service Principal")
    application_count = len(applications)
    service_principal_count = len(service_principals)
    counts_by_status = {
        key: int(value) for key, value in status_counter.items()
    }
    coverage = {
        "status": "complete",
        "reference_utc": reference_iso,
        "pagination_completed": True,
        "applications_scanned": application_count,
        "service_principals_scanned": service_principal_count,
        "managed_identities_excluded": managed_identity_excluded_count,
        "credential_rows": len(rows),
        "scope": (
            "Applications and Service Principals, excluding "
            "ManagedIdentity Service Principals"
        ),
    }
    report_date = now_utc.strftime("%Y-%m-%d")
    report_path = f"/mnt/data/entra-credential-expiration-audit-{report_date}.html"
    def escape(value):
        return html.escape("" if value is None else str(value), quote=True)
    def status_css(status):
        return "".join(ch.lower() if ch.isalnum() else "-" for ch in status).strip("-") or "unknown"
    status_order = ["EXPIRED", "CRITICAL", "EXPIRING SOON", "EXPIRING", "Valid"]
    status_notes = {
        "EXPIRED": "Requires immediate rotation review",
        "CRITICAL": "Expires within 7 days",
        "EXPIRING SOON": "Expires within 30 days",
        "EXPIRING": "Plan the next maintenance window",
        "Valid": "No immediate action",
    }
    status_cards = []
    for status in status_order:
        status_cards.append(
            "<article class=\"risk-card risk-card--%s\">"
            "<div class=\"risk-card__label\">%s</div>"
            "<div class=\"risk-card__count\">%s</div>"
            "<div class=\"risk-card__note\">%s</div>"
            "</article>"
            % (

                status_css(status),
                escape(status),
                counts_by_status.get(status, 0),
                escape(status_notes[status]),
            )
        )
    expired_or_critical = counts_by_status.get("EXPIRED", 0) + counts_by_status.get("CRITICAL", 0)
    if expired_or_critical:
        action_title = "Action required"
        action_detail = f"{expired_or_critical} credential(s) need owner review now."
        action_class = "signal--urgent"
    else:
        action_title = "No immediate action"
        action_detail = "No expired or critical credentials were found."
        action_class = "signal--clear"
    table_rows = []
    for row in rows:
        status_class = status_css(row["status"])
        action_link = (
            f'<a class="action-link" rel="noopener noreferrer" target="_blank" href="{escape(row["actionUrl"])}">Review in Entra <span aria-hidden="true">↗</span></a>'
            if row["actionUrl"]
            else ""
        )
        table_rows.append(
            f'<tr class="row--{status_class}">'
            f'<td><div class="credential-name">{escape(row["credentialName"])}</div><div class="credential-type">{escape(row["type"])}</div></td>'
            f'<td><span class="object-tag">{escape(row["objectType"])}</span></td>'
            f'<td><div class="object-name">{escape(row["objectName"])}</div><div class="id-line">App ID {escape(row["appId"])}</div></td>'
            f'<td class="date-cell">{escape(row["expirationUtc"])}</td>'
            f'<td class="days-cell">{escape(row["daysRemaining"])}</td>'
            f'<td><span class="status-badge status-badge--{status_class}">{escape(row["status"])}</span></td>'
            f'<td class="action-cell">{action_link}</td>'
            "</tr>"
        )
    html_document = f"""<!doctype html>
    <html lang="en">
    <head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
    <title>Entra Credential Expiration Audit</title>
    <style>
    :root {{
      --ink: #10233f;
      --muted: #5f6f82;
      --line: #d9e2ec;
      --paper: #f4f7fb;
      --panel: #ffffff;
      --cyan: #0c8ba7;
      --cyan-soft: #e5f6f9;
      --red: #b42318;
      --red-soft: #fff0ef;
      --amber: #a15c00;
      --amber-soft: #fff5e5;
      --blue: #2d6cdf;
      --blue-soft: #edf3ff;
      --green: #18794e;
      --green-soft: #e8f7ef;
      --shadow: 0 18px 40px rgba(16, 35, 63, .08);
    }}
    * {{ box-sizing: border-box; }}
    body {{
      margin: 0;
      background: var(--paper);
      color: var(--ink);
      font-family: "Aptos", "Segoe UI", sans-serif;
    }}
    button, input, select {{ font: inherit; }}
    .shell {{ max-width: 1600px; margin: 0 auto; padding: 28px; }}
    .hero {{
      position: relative;
      overflow: hidden;
      padding: 32px;
      border-radius: 22px;
      color: #f7fbff;
      background: linear-gradient(122deg, #10233f 0%, #173f67 58%, #0c8ba7 150%);
      box-shadow: var(--shadow);
    }}
    .hero::after {{
      content: "";
      position: absolute;
      width: 420px;
      height: 420px;
      right: -120px;
      top: -250px;
      border: 1px solid rgba(255,255,255,.24);
      border-radius: 50%;
      box-shadow: 0 0 0 55px rgba(255,255,255,.04), 0 0 0 110px rgba(255,255,255,.025);
    }}
    .hero__grid {{ position: relative; z-index: 1; display: grid; grid-template-columns: 1fr auto; gap: 28px; align-items: end; }}
    .eyebrow {{ color: #8fe5f0; font: 700 11px/1.2 "Cascadia Mono", Consolas, monospace; letter-spacing:
 .13em; text-transform: uppercase; }}
    h1 {{ margin: 10px 0 8px; font-family: "Palatino Linotype", Georgia, serif; font-size: clamp(34px, 5vw, 58px); letter-spacing: -.045em; line-height: .98; }}
    .hero__subtitle {{ max-width: 700px; margin: 0; color: #d5e5f2; font-size: 15px; line-height: 1.55; }}
    .signal {{ min-width: 245px; padding: 18px 20px; border-radius: 16px; border: 1px solid rgba(255,255,255,.18); background: rgba(5, 20, 37, .28); backdrop-filter: blur(10px); }}

    .signal--urgent {{ border-color: rgba(255, 178, 170, .58); }}
    .signal--clear {{ border-color: rgba(145, 239, 191, .54); }}
    .signal__label {{ margin-bottom: 7px; color: #b9d0e3; font: 700 10px/1.2 "Cascadia Mono", Consolas, monospace; letter-spacing: .12em; text-transform: uppercase; }}
    .signal__title {{ font-family: "Palatino Linotype", Georgia, serif; font-size: 25px; line-height: 1.05; }}
    .signal__detail {{ margin-top: 8px; color: #d5e5f2; font-size: 13px; line-height: 1.45; }}
    .context {{ display: flex; gap: 14px; flex-wrap: wrap; margin-top: 22px; color: #b9d0e3; font-size: 12px; }}
    .context span {{ padding-right: 14px; border-right: 1px solid rgba(255,255,255,.22); }}
    .context span:last-child {{ padding-right: 0; border-right: 0; }}
    .metric-grid {{ display: grid; grid-template-columns: repeat(4, 1fr); gap: 14px; margin: 18px 0; }}
    .metric {{ min-height: 112px; padding: 18px; border: 1px solid var(--line); border-radius: 16px; background: var(--panel); box-shadow: 0 8px 22px rgba(16, 35, 63, .04); }}
    .metric__label {{ color: var(--muted); font: 700 10px/1.2 "Cascadia Mono", Consolas, monospace; letter-spacing: .1em; text-transform: uppercase; }}
    .metric__value {{ margin-top: 12px; font-family: "Palatino Linotype", Georgia, serif; font-size: 38px; letter-spacing: -.04em; line-height: 1; }}
    .metric__note {{ margin-top: 8px; color: var(--muted); font-size: 12px; }}
    .section-heading {{ display: flex; justify-content: space-between; align-items: baseline; gap: 20px;
 margin: 30px 0 12px; }}
    .section-heading h2 {{ margin: 0; font-family: "Palatino Linotype", Georgia, serif; font-size: 25px;
 letter-spacing: -.025em; }}
    .section-heading p {{ margin: 0; color: var(--muted); font-size: 13px; }}
    .risk-grid {{ display: grid; grid-template-columns: repeat(5, 1fr); gap: 10px; }}
    .risk-card {{ min-height: 135px; padding: 17px; border: 1px solid var(--line); border-radius: 15px; background: var(--panel); }}
    .risk-card__label {{ color: var(--muted); font: 700 10px/1.2 "Cascadia Mono", Consolas, monospace; letter-spacing: .09em; text-transform: uppercase; }}
    .risk-card__count {{ margin: 15px 0 8px; font-family: "Palatino Linotype", Georgia, serif; font-size: 38px; line-height: .9; letter-spacing: -.04em; }}
    .risk-card__note {{ color: var(--muted); font-size: 12px; line-height: 1.35; }}
    .risk-card--expired {{ border-top: 4px solid var(--red); background: var(--red-soft); }}
    .risk-card--critical {{ border-top: 4px solid #d45d00; background: #fff1e5; }}
    .risk-card--expiring-soon {{ border-top: 4px solid var(--amber); background: var(--amber-soft); }}
    .risk-card--expiring {{ border-top: 4px solid var(--blue); background: var(--blue-soft); }}
    .risk-card--valid {{ border-top: 4px solid var(--green); background: var(--green-soft); }}
    .workspace {{ margin-top: 22px; overflow: hidden; border: 1px solid var(--line); border-radius: 18px; background: var(--panel); box-shadow: var(--shadow); }}
    .filters {{ display: grid; grid-template-columns: 1.4fr repeat(2, .72fr) .9fr .9fr; gap: 12px; padding: 18px; border-bottom: 1px solid var(--line); background: #fbfdff; }}
    .field label {{ display: block; margin-bottom: 7px; color: var(--muted); font: 700 10px/1.2 "Cascadia Mono", Consolas, monospace; letter-spacing: .08em; text-transform: uppercase; }}
    .field input, .field select {{ width: 100%; min-height: 42px; padding: 0 11px; border: 1px solid #cbd7e4; border-radius: 9px; outline: none; background: #fff; color: var(--ink); }}
    .field input:focus, .field select:focus {{ border-color: var(--cyan); box-shadow: 0 0 0 3px rgba(12,
 139, 167, .14); }}
    .table-toolbar {{ display: flex; justify-content: space-between; align-items: center; gap: 14px; padding: 14px 18px; }}
    .table-count {{ color: var(--muted); font-size: 13px; }}
    .export-button {{ padding: 10px 14px; border: 0; border-radius: 9px; background: var(--ink); color: #fff; font-weight: 700; cursor: pointer; transition: transform .16s ease, background .16s ease; }}
    .export-button:hover {{ background: #173f67; transform: translateY(-1px); }}
    .table-wrap {{ overflow: auto; border-top: 1px solid var(--line); }}
    table {{ width: 100%; min-width: 1120px; border-collapse: collapse; }}
    th {{ padding: 13px 16px; border-bottom: 1px solid var(--line); background: #f7faff; color: var(--muted); font: 700 10px/1.2 "Cascadia Mono", Consolas, monospace; letter-spacing: .08em; text-align: left; text-transform: uppercase; white-space: nowrap; cursor: pointer; }}
    th:first-child {{ cursor: default; }}
    td {{ padding: 15px 16px; border-bottom: 1px solid #e8eef4; font-size: 13px; vertical-align: top; }}
    tbody tr {{ transition: background .14s ease; }}
    tbody tr:hover {{ background: #f7fbff; }}
    tbody tr:last-child td {{ border-bottom: 0; }}
    .credential-name, .object-name {{ max-width: 310px; overflow-wrap: anywhere; font-weight: 700; line-height: 1.35; }}
    .credential-type, .id-line {{ margin-top: 5px; color: var(--muted); font: 11px/1.35 "Cascadia Mono",
 Consolas, monospace; overflow-wrap: anywhere; }}
    .object-tag {{ display: inline-block; padding: 5px 8px; border-radius: 999px; background: #eff4f9; color: #3d5167; font-size: 11px; font-weight: 700; white-space: nowrap; }}
    .date-cell, .days-cell {{ font-family: "Cascadia Mono", Consolas, monospace; font-size: 12px; white-space: nowrap; }}
    .days-cell {{ font-weight: 700; }}
    .status-badge {{ display: inline-flex; align-items: center; padding: 5px 8px; border-radius: 999px; font: 700 10px/1.2 "Cascadia Mono", Consolas, monospace; letter-spacing: .04em; white-space: nowrap; }}
    .status-badge--expired {{ background: var(--red-soft); color: var(--red); }}
    .status-badge--critical {{ background: #fff1e5; color: #c24f00; }}
    .status-badge--expiring-soon {{ background: var(--amber-soft); color: var(--amber); }}
    .status-badge--expiring {{ background: var(--blue-soft); color: var(--blue); }}
    .status-badge--valid {{ background: var(--green-soft); color: var(--green); }}
    .status-badge--unknown {{ background: #eef1f5; color: #576579; }}
    .action-cell {{ white-space: nowrap; }}
    .action-link {{ color: var(--cyan); font-size: 12px; font-weight: 700; text-decoration: none; }}
    .action-link:hover {{ text-decoration: underline; }}
    @media (max-width: 1000px) {{ .metric-grid, .risk-grid {{ grid-template-columns: repeat(2, 1fr); }} .filters {{ grid-template-columns: repeat(2, 1fr); }} }}
    @media (max-width: 680px) {{ .shell {{ padding: 14px; }} .hero {{ padding: 23px; border-radius: 16px; }} .hero__grid {{ grid-template-columns: 1fr; }} .signal {{ min-width: 0; }} .metric-grid, .risk-grid, .filters {{ grid-template-columns: 1fr; }} .context {{ display: block; }} .context span {{ display: block; padding: 4px 0; border: 0; }} .table-toolbar {{ align-items: stretch; flex-direction: column; }} .export-button {{ width: 100%; }} }}
    @media (prefers-reduced-motion: reduce) {{ * {{ scroll-behavior: auto !important; transition: none !important; }} }}
    </style>
    </head>
    <body>
    <main class="shell">
      <header class="hero">
        <div class="hero__grid">
          <div>
            <div class="eyebrow">Identity operations / credential watch</div>
            <h1>Expiration watch</h1>
            <p class="hero__subtitle">A read-only inventory of application and service principal credentials. Review the red path first, then schedule the remaining rotation work.</p>
          </div>
          <aside class="signal {action_class}">

            <div class="signal__label">Risk signal</div>
            <div class="signal__title">{escape(action_title)}</div>
            <div class="signal__detail">{escape(action_detail)}</div>
          </aside>
        </div>
        <div class="context">
          <span>Reference UTC: {escape(reference_iso)}</span>
          <span>Pagination: complete</span>
          <span>Managed Identities excluded: {managed_identity_excluded_count}</span>
        </div>
      </header>
      <section class="metric-grid" aria-label="Audit scope">
        <article class="metric"><div class="metric__label">Applications</div><div class="metric__value">{application_count}</div><div class="metric__note">Application registrations scanned</div></article>
        <article class="metric"><div class="metric__label">Service principals</div><div class="metric__value">{service_principal_count}</div><div class="metric__note">Non-managed identities included</div></article>
        <article class="metric"><div class="metric__label">Credentials</div><div class="metric__value">{len(rows)}</div><div class="metric__note">Secrets and certificates in scope</div></article>
        <article class="metric"><div class="metric__label">Coverage</div><div class="metric__value">100%</div><div class="metric__note">Microsoft Graph pagination completed</div></article>
      </section>
      <div class="section-heading"><h2>Risk posture</h2><p>Counts are based on one UTC reference time.</p></div>
      <section class="risk-grid" aria-label="Credential risk status">{''.join(status_cards)}</section>
      <section class="workspace" aria-label="Credential inventory">
        <div class="filters">
          <div class="field"><label for="f_name">Credential name</label><input id="f_name" type="search" placeholder="Search by credential name"></div>
          <div class="field"><label for="f_min">Minimum days</label><input id="f_min" type="number" placeholder="e.g. 0"></div>
          <div class="field"><label for="f_max">Maximum days</label><input id="f_max" type="number" placeholder="e.g. 30"></div>
          <div class="field"><label for="f_status">Risk status</label><select id="f_status"><option value="">All statuses</option><option>EXPIRED</option><option>CRITICAL</option><option>EXPIRING SOON</option><option>EXPIRING</option><option>Valid</option><option>UNKNOWN</option></select></div>
          <div class="field"><label for="f_object">Object type</label><select id="f_object"><option value="">All objects</option><option>Application</option><option>Service Principal</option></select></div>
        </div>
        <div class="table-toolbar"><div class="table-count" id="countLabel"></div><button class="export-button" type="button" onclick="exportCsv()">Export visible rows as CSV</button></div>
        <div class="table-wrap">
          <table id="auditTable">
            <thead><tr><th>Credential</th><th onclick="sortTable(1)">Object type</th><th onclick="sortTable(2)">Object</th><th onclick="sortTable(3)">Expiration UTC</th><th onclick="sortTable(4)">Days left</th><th onclick="sortTable(5)">Status</th><th>Action</th></tr></thead>
            <tbody>{''.join(table_rows)}</tbody>
          </table>
        </div>
      </section>
    </main>
    <script>
    const allRows = Array.from(document.querySelectorAll("#auditTable tbody tr"));
    let sortDirection = 1;
    let lastSortColumn = -1;
    function textAt(row, index) {{
      return (row.children[index]?.innerText || "").trim();
    }}
    function matchesFilters(row) {{
      const name = document.getElementById("f_name").value.trim().toLowerCase();
      const min = document.getElementById("f_min").value;
      const max = document.getElementById("f_max").value;
      const status = document.getElementById("f_status").value;
      const objectType = document.getElementById("f_object").value;
      const days = Number.parseInt(textAt(row, 4), 10);
      if (name && !textAt(row, 0).toLowerCase().includes(name)) return false;
      if (status && textAt(row, 5) !== status) return false;
      if (objectType && textAt(row, 1) !== objectType) return false;
      if (min !== "" && (Number.isNaN(days) || days < Number.parseInt(min, 10))) return false;
      if (max !== "" && (Number.isNaN(days) || days > Number.parseInt(max, 10))) return false;
      return true;
    }}
    function applyFilters() {{
      let visible = 0;
      allRows.forEach(row => {{
        const show = matchesFilters(row);
        row.hidden = !show;
        if (show) visible += 1;
      }});
      document.getElementById("countLabel").textContent = `${{visible}} of ${{allRows.length}} credentials visible`;
    }}
    function sortTable(index) {{
      const tbody = document.querySelector("#auditTable tbody");
      if (lastSortColumn === index) sortDirection *= -1;
      else {{ lastSortColumn = index; sortDirection = 1; }}
      const rows = Array.from(tbody.querySelectorAll("tr"));
      rows.sort((left, right) => textAt(left, index).localeCompare(textAt(right, index), undefined, {{ numeric: true, sensitivity: "base" }}) * sortDirection);
      rows.forEach(row => tbody.appendChild(row));
    }}
    function csvValue(value) {{

      return `"${{String(value ?? "").replaceAll('"', '""')}}"`;
    }}
    function exportCsv() {{
      const headers = ["credentialName", "type", "objectType", "objectName", "appId", "expirationUtc", "daysRemaining", "status", "actionUrl"];
      const lines = [headers.map(csvValue).join(",")];
      allRows.filter(row => !row.hidden).forEach(row => {{
        const credential = textAt(row, 0).split("\\n");
        const object = textAt(row, 2).split("\\n");
        const actionUrl = row.querySelector("a")?.href || "";
        lines.push([
          credential[0] || "", credential[1] || "", textAt(row, 1), object[0] || "",
          (object[1] || "").replace(/^App ID\\s*/, ""), textAt(row, 3), textAt(row, 4), textAt(row, 5), actionUrl
        ].map(csvValue).join(","));
      }});
      const blob = new Blob(["\\ufeff" + lines.join("\\r\\n")], {{ type: "text/csv;charset=utf-8;" }});
      const link = document.createElement("a");
      link.href = URL.createObjectURL(blob);
      link.download = "entra-credential-expiration-audit-filtered.csv";
      link.click();
      URL.revokeObjectURL(link.href);
    }}
    ["f_name", "f_min", "f_max", "f_status", "f_object"].forEach(id => {{
      document.getElementById(id).addEventListener("input", applyFilters);
      document.getElementById(id).addEventListener("change", applyFilters);
    }});
    applyFilters();
    </script>
    </body>
    </html>"""
    try:
        os.makedirs("/mnt/data", exist_ok=True)
        with open(report_path, "w", encoding="utf-8") as report_file:
            report_file.write(html_document)
    except Exception as exc:
        return fail(f"Failed to write report: {exc}")
    return {
        "report_path": report_path,
        "coverage": coverage,
        "application_count": application_count,
        "service_principal_count": service_principal_count,
        "managed_identity_excluded_count": managed_identity_excluded_count,
        "counts_by_status": counts_by_status,
    }
