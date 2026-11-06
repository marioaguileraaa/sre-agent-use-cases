"""Identity, read-only HTTP allowlist and Resource Graph paging guards (offline)."""

import sys
import types
import unittest

from support import CLIENT_ID, TENANT, FakeReader, load_tool, make_jwt, params, row


def sidecar(scope, tenant=TENANT, client=CLIENT_ID):
    return {"iss": "adc-msi-sidecar", "tid": tenant, "cid": "", "clientId": client, "scp": scope, "kind": "workspace-mi",
            "exp": 4102444800, "iat": 1700000000}


class SidecarTokenTests(unittest.TestCase):
    def setUp(self):
        self.t = load_tool()

    def test_arm_scope_maps_to_arm_audience_and_client(self):
        claims = self.t.normalize_sidecar_claims(sidecar("https://management.core.windows.net/.default"))
        self.assertEqual((claims["aud"], claims["appid"], claims["tid"]), ("https://management.azure.com", CLIENT_ID, TENANT))

    def test_graph_scope_keeps_its_resource_and_real_tokens_are_unchanged(self):
        self.assertEqual(self.t.normalize_sidecar_claims(sidecar("https://graph.microsoft.com/.default"))["aud"], "https://graph.microsoft.com")
        real = {"iss": "https://sts.windows.net/" + TENANT + "/", "tid": TENANT, "appid": CLIENT_ID, "aud": "https://management.azure.com/"}
        self.assertIs(self.t.normalize_sidecar_claims(real), real)
        self.assertEqual(self.t.normalize_sidecar_claims("not-a-dict"), "not-a-dict")

    def test_claim_check_is_lenient_and_never_raises(self):
        ok = self.t.claim_check(make_jwt(sidecar("https://management.core.windows.net/.default")), CLIENT_ID, self.t.ARM)
        self.assertEqual(ok, "verified sidecar placeholder token")
        other = self.t.claim_check(make_jwt(sidecar("https://management.core.windows.net/.default", client="55555555-5555-4555-8555-555555555555")),
                                   CLIENT_ID, self.t.ARM)
        self.assertIn("continuing", other)
        self.assertIn("continuing", self.t.claim_check("garbage", CLIENT_ID, self.t.ARM))

    def test_identity_uses_managed_identity_credential_with_configured_client_and_caches_tokens(self):
        calls = []

        class Token:
            def __init__(self, token):
                self.token, self.expires_on = token, 4102444800

        class ManagedIdentityCredential:
            def __init__(self, client_id=None):
                calls.append(("init", client_id))

            def get_token(self, scope):
                calls.append(("token", scope))
                return Token(make_jwt(sidecar("https://management.core.windows.net/.default")))

            def close(self):
                pass

        fake = types.ModuleType("azure.identity")
        fake.ManagedIdentityCredential = ManagedIdentityCredential
        saved = {k: sys.modules.get(k) for k in ("azure", "azure.identity")}
        sys.modules["azure"] = types.ModuleType("azure")
        sys.modules["azure.identity"] = fake
        try:
            identity = self.t.Identity(CLIENT_ID)
            identity.token(self.t.ARM)
            identity.token(self.t.ARM)
        finally:
            for key, value in saved.items():
                if value is None:
                    sys.modules.pop(key, None)
                else:
                    sys.modules[key] = value
        self.assertEqual(calls, [("init", CLIENT_ID), ("token", "https://management.azure.com/.default")])
        self.assertEqual(identity.checks[self.t.ARM], "verified sidecar placeholder token")


class AllowlistTests(unittest.TestCase):
    def setUp(self):
        self.t = load_tool()
        self.reader = self.t.Reader(identity=None, deadline=10 ** 9)

    def test_allowed_read_endpoints(self):
        sub = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        self.assertEqual(self.reader.origin_for("POST", self.t.ARM + "/providers/Microsoft.ResourceGraph/resources?api-version=2024-04-01"), self.t.ARM)
        for url in (f"{self.t.ARM}/subscriptions/{sub}/providers/Microsoft.Insights/eventtypes/management/values?api-version=2015-04-01",
                    f"{self.t.ARM}/subscriptions/{sub}/providers/Microsoft.Authorization/roleDefinitions/acdd72a7-3385-48ef-bd42-f606fba81ae7?api-version=2022-04-01",
                    f"{self.t.ARM}/subscriptions/{sub}?api-version=2022-12-01"):
            self.assertEqual(self.reader.origin_for("GET", url), self.t.ARM)

    def test_everything_else_is_refused(self):
        sub = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee"
        for method, url in (("POST", f"{self.t.ARM}/subscriptions/{sub}/resourceGroups/rg/providers/Microsoft.Storage/storageAccounts/st/listKeys"),
                            ("PUT", self.t.ARM + "/providers/Microsoft.ResourceGraph/resources"),
                            ("DELETE", f"{self.t.ARM}/subscriptions/{sub}"),
                            ("GET", f"{self.t.ARM}/subscriptions/{sub}/resourceGroups/rg"),
                            ("GET", "http://management.azure.com/providers/Microsoft.ResourceGraph/resources"),
                            ("POST", "https://evil.example.com/providers/Microsoft.ResourceGraph/resources"),
                            ("GET", f"{self.t.GRAPH}/v1.0/servicePrincipals"),
                            ("GET", f"{self.t.ARM}/subscriptions/{sub}/../providers/Microsoft.Insights/eventtypes/management/values")):
            with self.subTest(method=method, url=url), self.assertRaises(self.t.DigestError) as raised:
                self.reader.origin_for(method, url)
            self.assertEqual(raised.exception.code, "unsafe_endpoint")

    def test_graph_is_allowed_only_when_enabled(self):
        reader = self.t.Reader(identity=None, deadline=10 ** 9, graph_enabled=True)
        self.assertEqual(reader.origin_for("GET", self.t.GRAPH + "/v1.0/servicePrincipals?$filter=appId%20eq%20'x'"), self.t.GRAPH)

    def test_budget_guard_stops_requests_after_the_deadline(self):
        reader = self.t.Reader(identity=None, deadline=0)
        with self.assertRaises(self.t.DigestError) as raised:
            reader.guard()
        self.assertEqual(raised.exception.code, "collection_deadline")


class ResourceGraphPagingTests(unittest.TestCase):
    def setUp(self):
        self.t = load_tool()
        self.config = self.t.validate_config()

    def page(self, ids, token=None):
        payload = {"data": [{"id": i, "v": 1} for i in ids]}
        if token:
            payload["$skipToken"] = token
        return payload

    def test_follows_skip_token_and_merges_pages(self):
        reader = FakeReader([self.page(["a", "b"], "t1"), self.page(["c"])])
        rows, rec = self.t.arg_query(reader, self.config, "resourcechanges | project id", "arg_test", "test")
        self.assertEqual([r["id"] for r in rows], ["a", "b", "c"])
        self.assertEqual((rec["status"], rec["pages"], rec["records"]), ("complete", 2, 3))
        self.assertEqual(reader.calls[1][2]["options"]["$skipToken"], "t1")
        self.assertNotIn("$skipToken", reader.calls[0][2]["options"])
        self.assertEqual(reader.calls[0][2]["subscriptions"], [self.config["subscriptions"][0]])

    def test_repeated_skip_token_is_a_loop_and_marks_partial(self):
        reader = FakeReader([self.page(["a"], "t1"), self.page(["b"], "t1")])
        rows, rec = self.t.arg_query(reader, self.config, "q", "arg_test", "test")
        self.assertEqual(rec["status"], "partial")
        self.assertEqual(rec["errors"][0]["code"], "pagination_loop")
        self.assertEqual(len(rows), 2)

    def test_duplicate_row_id_and_row_cap_are_guarded(self):
        dup = FakeReader([self.page(["a"], "t1"), self.page(["A"])])
        self.assertEqual(self.t.arg_query(dup, self.config, "q", "x", "x")[1]["errors"][0]["code"], "invalid_pagination")
        cap = FakeReader([self.page(["a", "b", "c"])])
        rows, rec = self.t.arg_query(cap, self.config, "q", "x", "x", row_cap=2)
        self.assertEqual((rec["status"], rec["errors"][0]["code"], rows), ("error", "row_cap", []))

    def test_page_cap_marks_partial(self):
        self.t.MAX_PAGES = 2
        reader = FakeReader([self.page(["a"], "t1"), self.page(["b"], "t2")])
        rows, rec = self.t.arg_query(reader, self.config, "q", "x", "x")
        self.assertEqual((rec["status"], rec["errors"][0]["code"], len(rows)), ("partial", "page_cap", 2))

    def test_access_denied_is_reported_as_denied(self):
        reader = FakeReader([self.t.DigestError("access_denied", "HTTP 403", "arg_test", 403)])
        rows, rec = self.t.arg_query(reader, self.config, "q", "arg_test", "test")
        self.assertEqual((rows, rec["status"]), ([], "denied"))

    def test_more_than_300_subscriptions_are_batched(self):
        self.t.SUBSCRIPTION_IDS = [f"aaaaaaaa-bbbb-4ccc-8ddd-{i:012d}" for i in range(301)]
        config = self.t.validate_config()
        reader = FakeReader([self.page(["a"]), self.page(["b"])])
        rows, rec = self.t.arg_query(reader, config, "q", "x", "x")
        self.assertEqual([len(c[2]["subscriptions"]) for c in reader.calls], [300, 1])
        self.assertEqual(len(rows), 2)

    def test_queries_embed_only_validated_values(self):
        p = params(self.t, resource_group="rg-app")
        query = self.t.q_candidates(self.config, p)
        self.assertIn("resourceGroup contains 'rg-app'", query)
        self.assertIn("mv-expand path = keys to typeof(string) limit 400", query)
        self.assertNotIn("| limit", query)
        with self.assertRaises(self.t.DigestError):
            self.t.kql_text("x' or 1==1")

    def test_delete_attribution_uses_activity_log_caller(self):
        deleted = row("microsoft.network/publicipaddresses", "PIP-TEMP", "Delete", by="System", by_type="System", client="Unspecified")
        raw = {"sources": [], "containers": [], "candidates": [deleted]}
        reader = FakeReader([{"value": [{"operationName": {"value": "Microsoft.Network/publicIPAddresses/delete"}, "status": {"value": "Started"},
                                         "category": {"value": "Administrative"}, "caller": "bob@contoso.com"}]}])
        self.t.repair_delete_attribution(reader, self.config, params(self.t), raw)
        self.assertEqual((deleted["changedBy"], deleted["changedByType"], deleted["attributedBy"]), ("bob@contoso.com", "User", "activity_log"))
        self.assertIn("resourceUri%20eq%20'", reader.calls[0][1])
        self.assertEqual(raw["sources"][0]["records"], 1)


if __name__ == "__main__":
    unittest.main()
