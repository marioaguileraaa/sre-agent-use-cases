#!/usr/bin/env python3
"""Automated deployment (Option B) of case 14 - Daily relevant Azure changes digest - to an Azure SRE Agent.

Creates or updates, idempotently, the Python tool (with its 6 optional parameters), the skill, the subagent
and (optionally) the daily scheduled task, using the files published in this folder. It is equivalent to the
manual portal steps of the guide (Option A).

Requirements: Python 3.9+ (standard library only), Azure CLI signed in with `az login`, and the SRE Agent
Administrator role on the SRE Agent resource. Azure Owner/Contributor do NOT replace it.

Examples:
  python deploy/deploy-sre-agent-components.py --endpoint https://<your-agent>.azuresre.ai \
      --agent-client-id <client-id> --subscription-id <sub-1> --subscription-id <sub-2> --schedule

  # Management group scope (Reader on the management group) and optional report branding
  python deploy/deploy-sre-agent-components.py --endpoint https://<your-agent>.azuresre.ai \
      --agent-client-id <client-id> --management-group-id <mg-id> --client-name "Contoso"

  Add --dry-run to validate the configuration without calling the API.
"""
import argparse
import json
import re
import shutil
import subprocess
import sys
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent  # the case folder
SPEC = json.loads((ROOT / "deploy" / "sre-agent-components.json").read_text(encoding="utf-8"))
GUID = re.compile(r"^[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}$")
MARKERS = {
    "client": 'MANAGED_IDENTITY_CLIENT_ID = "<YOUR_MANAGED_IDENTITY_CLIENT_ID>"',
    "subs": 'SUBSCRIPTION_IDS = ["<YOUR_SUBSCRIPTION_ID>"]',
    "mg": 'MANAGEMENT_GROUP_ID = ""',
    "name": 'CLIENT_NAME = ""',
}


def fail(message):
    print(f"ERROR: {message}", file=sys.stderr)
    sys.exit(1)


def guids(name, values):
    out = []
    for v in values:
        for part in (p.strip() for p in v.split(",") if p.strip()):
            if not GUID.match(part):
                fail(f"{name} must be a valid GUID (got: {part!r}).")
            out.append(part.lower())
    return out


def configure_code(code, args):
    for marker in MARKERS.values():
        if code.count(marker) != 1:
            fail(f"Expected marker not found in the tool code: {marker}")
    client = guids("--agent-client-id", [args.agent_client_id])
    if len(client) != 1:
        fail("Pass exactly one --agent-client-id (Client ID of the SRE Agent managed identity).")
    subs = guids("--subscription-id", args.subscription_id)
    mg = (args.management_group_id or "").strip()
    if mg and not re.fullmatch(r"[A-Za-z0-9_().\-]{1,90}", mg):
        fail("--management-group-id must be a management group ID.")
    if not subs and not mg:
        fail("Pass at least one --subscription-id or a --management-group-id.")
    code = code.replace(MARKERS["client"], f'MANAGED_IDENTITY_CLIENT_ID = "{client[0]}"')
    if subs:
        code = code.replace(MARKERS["subs"], "SUBSCRIPTION_IDS = [" + ", ".join(f'"{s}"' for s in subs) + "]")
    else:
        code = code.replace(MARKERS["subs"], "SUBSCRIPTION_IDS = []")
    if mg:
        code = code.replace(MARKERS["mg"], f'MANAGEMENT_GROUP_ID = "{mg}"')
    if args.client_name:
        if len(args.client_name) > 80 or re.search(r"[\x00-\x1f\x7f<>]", args.client_name):
            fail("--client-name must be plain text of up to 80 characters.")
        code = code.replace(MARKERS["name"], "CLIENT_NAME = " + json.dumps(args.client_name))
    compile(code, "tool", "exec")
    return code


def token():
    az = shutil.which("az") or shutil.which("az.cmd")
    if not az:
        fail("Azure CLI (az) not found. Install Azure CLI and run 'az login'.")
    result = subprocess.run([az, "account", "get-access-token", "--resource", "https://azuresre.ai",
                             "--query", "accessToken", "-o", "tsv"], capture_output=True, text=True)
    if result.returncode != 0 or not result.stdout.strip():
        fail("Could not get a token for https://azuresre.ai. Run 'az login'.\n" + result.stderr)
    return result.stdout.strip()


class Api:
    def __init__(self, endpoint, dry_run):
        self.endpoint = endpoint.rstrip("/")
        self.dry_run = dry_run
        self.bearer = None if dry_run else token()

    def call(self, method, path, body=None):
        if self.dry_run:
            return {}
        data = json.dumps(body).encode("utf-8") if body is not None else None
        request = urllib.request.Request(self.endpoint + path, data=data, method=method, headers={
            "Authorization": "Bearer " + self.bearer, "Accept": "application/json",
            **({"Content-Type": "application/json"} if data else {}),
        })
        try:
            with urllib.request.urlopen(request, timeout=120) as response:
                raw = response.read().decode("utf-8")
                return json.loads(raw) if raw.strip() else {}
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8", "replace")[:600]
            hint = " Check that your user has the SRE Agent Administrator role on the agent." if exc.code in (401, 403) else ""
            fail(f"{method} {path} -> HTTP {exc.code}. {detail}{hint}")


def deploy(api, args):
    spec = SPEC["digest"]
    folder = (ROOT / spec["folder"]).resolve()
    tool_name, skill_name, agent_name = spec["tool"]["name"], spec["skill"]["name"], spec["agent"]["name"]
    code = configure_code((folder / spec["tool"]["code"]).read_text(encoding="utf-8"), args)
    skill = (folder / spec["skill"]["file"]).read_text(encoding="utf-8")
    instructions = (folder / spec["agent"]["file"]).read_text(encoding="utf-8")

    print(f"1/4 Python tool  -> {tool_name}")
    api.call("PUT", f"/api/v2/extendedAgent/tools/{tool_name}", {
        "name": tool_name, "type": "ExtendedAgentTool", "tags": None,
        "properties": {
            "type": "PythonFunctionTool", "functionCode": code,
            "timeoutSeconds": spec["tool"]["timeoutSeconds"], "dependencies": [],
            "authEnabled": False, "authScopes": None, "connector": None,
            "description": spec["tool"]["description"],
            "parameters": [dict(p, value=None) for p in spec["tool"]["parameters"]],
            "attributes": [], "toolMode": "Auto",
        },
    })
    print(f"2/4 Skill        -> {skill_name}")
    api.call("PUT", f"/api/v2/extendedAgent/skills/{skill_name}", {
        "name": skill_name, "type": "Skill", "tags": None,
        "properties": {"description": spec["skill"]["description"], "tools": [tool_name],
                       "skillContent": skill, "additionalFiles": []},
    })
    print(f"3/4 Subagent     -> {agent_name}")
    api.call("PUT", f"/api/v2/extendedAgent/agents/{agent_name}", {
        "name": agent_name, "type": "ExtendedAgent", "tags": None,
        "properties": {
            "instructions": instructions, "handoffDescription": spec["agent"]["handoffDescription"],
            "handoffs": [], "tools": [tool_name], "mcpTools": [], "connectors": [],
            "allowParallelToolCalls": spec["agent"]["allowParallelToolCalls"], "agentsAsTools": [],
            "maxReflectionCount": 0, "criticPromptPath": "", "criticOnHandOff": False,
            "customReflectionNote": "", "commonPrompts": [],
            "disableDocumentRetrieval": spec["agent"]["disableDocumentRetrieval"],
            "enableHandoffPromptOverride": False, "userPromptOverride": None,
            "handoffPromptOverride": None, "instructionsOverride": None, "commonTools": [],
            "temperature": None, "llmModelName": None, "enableVanillaMode": False,
            "enableSkills": True, "addSystemSkills": False, "allowedSkills": [skill_name],
            "outputType": None, "hooks": None, "permissions": None,
        },
    })
    for kind, name in (("tools", tool_name), ("skills", skill_name), ("agents", agent_name)):
        if not api.dry_run and api.call("GET", f"/api/v2/extendedAgent/{kind}/{name}").get("name") != name:
            fail(f"Could not verify {kind}/{name} after deployment.")
    if not args.schedule:
        print("4/4 Scheduled task -> skipped (use --schedule to create it)")
        return agent_name
    task = spec["schedule"]
    print(f"4/4 Scheduled task -> {task['name']} [{task['cronExpression']} UTC]")
    existing = api.call("GET", "/api/v1/scheduledtasks")
    existing = existing.get("value", []) if isinstance(existing, dict) else existing
    if any(t.get("name") == task["name"] for t in existing or []):
        print("    already exists; not duplicated.")
    else:
        api.call("POST", "/api/v1/scheduledtasks", {
            "name": task["name"], "agent": agent_name, "cronExpression": task["cronExpression"],
            "agentPrompt": task["agentPrompt"], "description": task["description"], "agentMode": "autonomous",
        })
    return agent_name


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--endpoint", required=True, help="SRE Agent URL (https://<name>...azuresre.ai)")
    parser.add_argument("--agent-client-id", required=True, help="Client ID of the SRE Agent managed identity")
    parser.add_argument("--subscription-id", action="append", default=[], help="Subscription to review. Repeatable or comma-separated")
    parser.add_argument("--management-group-id", default="", help="Optional management group scope instead of subscriptions")
    parser.add_argument("--client-name", default="", help="Optional organization name shown in the report header")
    parser.add_argument("--schedule", action="store_true", help="Also create the daily scheduled task (0 18 * * * UTC)")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()
    if not re.match(r"^https://[\w.-]+\.azuresre\.ai/?$", args.endpoint):
        fail("--endpoint must be the agent URL, e.g. https://sre-agent-xxxx--yyyy.zzzz.region.azuresre.ai")
    api = Api(args.endpoint, args.dry_run)
    agent = deploy(api, args)
    print("\nDone." + (" (dry-run: the API was not called)" if args.dry_run else ""))
    print(f"  Try it in the SRE Agent chat:  /agent {agent}  and send a prompt from scheduled-task.md.")


if __name__ == "__main__":
    main()
