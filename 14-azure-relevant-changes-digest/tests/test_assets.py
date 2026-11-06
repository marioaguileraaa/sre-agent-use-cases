"""Consistency of the deployable assets: main() signature, parameter schema, deploy spec and skill (offline)."""

import importlib.util
import inspect
import json
import types
import unittest

from support import ROOT, load_tool


class AssetTests(unittest.TestCase):
    def setUp(self):
        self.t = load_tool(configure=False)
        self.signature = inspect.signature(self.t.main)

    def test_schema_matches_main_signature_and_defaults(self):
        schema = json.loads((ROOT / "tool-parameters.schema.json").read_text(encoding="utf-8"))
        self.assertEqual(list(schema["properties"]), list(self.signature.parameters))
        for name, prop in schema["properties"].items():
            self.assertEqual(prop["default"], self.signature.parameters[name].default, name)
        self.assertEqual(schema["properties"]["view"]["enum"], list(self.t.VIEWS))
        self.assertEqual(schema["properties"]["period"]["enum"], list(self.t.PERIODS))

    def test_deploy_spec_matches_tool_and_restricts_the_agent(self):
        spec = json.loads((ROOT / "deploy" / "sre-agent-components.json").read_text(encoding="utf-8"))["digest"]
        self.assertEqual(spec["tool"]["timeoutSeconds"], 150)
        self.assertGreater(spec["tool"]["timeoutSeconds"], self.t.MAX_COLLECTION_SECONDS + 30)
        self.assertEqual([p["name"] for p in spec["tool"]["parameters"]], list(self.signature.parameters))
        self.assertEqual({p["name"]: p["type"] for p in spec["tool"]["parameters"]}["limit"], "int")
        self.assertFalse(any(p["required"] for p in spec["tool"]["parameters"]))
        self.assertFalse(spec["agent"]["allowParallelToolCalls"])
        self.assertEqual(spec["schedule"]["cronExpression"], "0 18 * * *")
        self.assertTrue(spec["schedule"]["agentPrompt"].startswith("@change-digest-reviewer "))
        skill = (ROOT / spec["skill"]["file"]).read_text(encoding="utf-8")
        self.assertTrue(skill.startswith("---\nname: azure-change-digest\n"))
        self.assertIn("  - generate-azure-change-digest\n", skill)

    def test_deploy_script_configures_the_generic_tool(self):
        spec = importlib.util.spec_from_file_location("deploy_case14", ROOT / "deploy" / "deploy-sre-agent-components.py")
        deploy = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(deploy)
        code = (ROOT / "generate-azure-change-digest.py").read_text(encoding="utf-8")
        args = types.SimpleNamespace(agent_client_id="12345678-1234-4abc-8def-123456789abc", subscription_id=["aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"],
                                     management_group_id="", client_name="Contoso")
        configured = deploy.configure_code(code, args)
        self.assertIn('MANAGED_IDENTITY_CLIENT_ID = "12345678-1234-4abc-8def-123456789abc"', configured)
        self.assertIn('SUBSCRIPTION_IDS = ["aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"]', configured)
        self.assertIn('CLIENT_NAME = "Contoso"', configured)

    def test_generic_file_keeps_placeholders(self):
        generic = (ROOT / "generate-azure-change-digest.py").read_text(encoding="utf-8").splitlines()
        self.assertIn('MANAGED_IDENTITY_CLIENT_ID = "<YOUR_MANAGED_IDENTITY_CLIENT_ID>"', generic)
        self.assertTrue(any(line.startswith('SUBSCRIPTION_IDS = ["<YOUR_SUBSCRIPTION_ID>"]') for line in generic))

    def test_tool_uses_only_standard_library_and_azure_identity(self):
        source = (ROOT / "generate-azure-change-digest.py").read_text(encoding="utf-8")
        imports = {line.split()[1].split(".")[0] for line in source.splitlines() if line.startswith(("import ", "from "))}
        self.assertFalse(imports - {"base64", "csv", "html", "io", "json", "os", "re", "ssl", "tempfile", "time", "collections",
                                    "datetime", "pathlib", "urllib", "uuid"})
        self.assertIn("from azure.identity import ManagedIdentityCredential", source)
        self.assertNotIn("requests", imports)


if __name__ == "__main__":
    unittest.main()
