import time
import unittest

from support import SUB_A, Response, ScriptedOpener, configure, http_error, load_tool, now

QUERY_URL = f"https://management.azure.com/subscriptions/{SUB_A}/providers/Microsoft.CostManagement/query?api-version=2025-03-01"
ARG_URL = "https://management.azure.com/providers/Microsoft.ResourceGraph/resources?api-version=2024-04-01"


class AllowlistTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def test_only_read_endpoints_are_allowed(self):
        check = self.tool.Reader.check_url
        check("POST", QUERY_URL)
        check("POST", ARG_URL)
        check("GET", f"https://management.azure.com/subscriptions/{SUB_A}/providers/Microsoft.Consumption/budgets?api-version=2023-05-01")
        for method, url in (("GET", QUERY_URL), ("DELETE", ARG_URL), ("PUT", ARG_URL),
                            ("POST", f"https://management.azure.com/subscriptions/{SUB_A}/providers/Microsoft.Compute/virtualMachines/vm1/deallocate"),
                            ("POST", QUERY_URL.replace("https://", "http://")), ("POST", QUERY_URL.replace("management.azure.com", "evil.example.com")),
                            ("GET", f"https://management.azure.com/subscriptions/{SUB_A}/providers/Microsoft.Consumption/budgets/../../x")):
            with self.subTest(method=method, url=url):
                with self.assertRaises(self.tool.FinOpsError) as ctx:
                    check(method, url)
                self.assertEqual(ctx.exception.code, "unsafe_endpoint")


class ThrottlingAndPagingTests(unittest.TestCase):
    def setUp(self):
        self.tool = load_tool()

    def reader(self, script, budget=600):
        opener = ScriptedOpener(script)
        return self.tool.Reader(lambda: "token", time.monotonic() + budget, opener), opener

    def test_cost_query_waits_for_any_retry_after_header_and_follows_next_link(self):
        page1 = {"properties": {"columns": [{"name": "Cost"}, {"name": "UsageDate"}, {"name": "ServiceName"}, {"name": "Currency"}],
                                "rows": [[10.0, 20261001, "Storage", "USD"]], "nextLink": QUERY_URL + "&$skiptoken=abc"}}
        page2 = {"properties": {"columns": [{"name": "Cost"}, {"name": "UsageDate"}, {"name": "ServiceName"}, {"name": "Currency"}],
                                "rows": [[5.0, 20261002, "Storage", "USD"]], "nextLink": None}}
        throttled = http_error(QUERY_URL, 429, {"x-ms-ratelimit-microsoft.costmanagement-clienttype-retry-after": "17",
                                                "x-ms-ratelimit-microsoft.costmanagement-entity-retry-after": "30"})
        reader, opener = self.reader([throttled, Response(page1), Response(page2)])
        rec = self.tool.receipt("cost_daily:x", "src_cost_daily", SUB_A)
        rows = self.tool.cost_query(reader, SUB_A, {"type": "AmortizedCost"}, rec)
        self.assertEqual([r["Cost"] for r in rows], [10.0, 5.0])
        self.assertEqual(rec["status"], "complete")
        self.assertEqual(rec["pages"], 2)
        self.assertEqual(reader.throttled, 1)
        self.assertEqual(reader.waited, 31)  # the longest retry-after wins (+1 s)
        self.assertIn("$skiptoken=abc", opener.calls[2][1])
        self.assertEqual(opener.calls[2][2], {"type": "AmortizedCost"})  # the body is re-posted with the next link

    def test_persistent_throttling_marks_the_source_as_error_not_as_zero_cost(self):
        hdr = {"x-ms-ratelimit-microsoft.costmanagement-entity-retry-after": "5"}
        reader, _ = self.reader([http_error(QUERY_URL, 429, hdr) for _ in range(6)])
        rec = self.tool.receipt("cost_monthly:x", "src_cost_monthly", SUB_A)
        self.assertIsNone(self.tool.cost_query(reader, SUB_A, {}, rec))
        self.assertEqual(rec["status"], "error")
        self.assertEqual(rec["errors"][0]["http_status"], 429)

    def test_denied_subscription_is_reported_as_denied(self):
        reader, _ = self.reader([http_error(QUERY_URL, 403)])
        rec = self.tool.receipt("cost_monthly:x", "src_cost_monthly", SUB_A)
        self.assertIsNone(self.tool.cost_query(reader, SUB_A, {}, rec))
        self.assertEqual(rec["status"], "denied")
        self.assertIn("Reader", rec["errors"][0]["message"])

    def test_wait_longer_than_the_remaining_budget_is_not_attempted(self):
        hdr = {"x-ms-ratelimit-microsoft.costmanagement-qpu-retry-after": "60"}
        reader, opener = self.reader([http_error(QUERY_URL, 429, hdr)], budget=30)
        rec = self.tool.receipt("cost_daily:x", "src_cost_daily", SUB_A)
        self.assertIsNone(self.tool.cost_query(reader, SUB_A, {}, rec))
        self.assertEqual(len(opener.calls), 1)
        self.assertEqual(reader.waited, 0)

    def test_transport_errors_are_retried_once(self):
        reader, opener = self.reader([TimeoutError("read timed out"), TimeoutError("read timed out")])
        rec = self.tool.receipt("cost_daily:x", "src_cost_daily", SUB_A)
        self.assertIsNone(self.tool.cost_query(reader, SUB_A, {}, rec))
        self.assertEqual(len(opener.calls), 2)
        self.assertEqual(rec["errors"][0]["code"], "transport_failed")

    def test_resource_graph_paging_with_skip_token(self):
        reader, opener = self.reader([Response({"data": [{"id": "/a"}], "$skipToken": "t1"}), Response({"data": [{"id": "/b"}, {"id": "/a"}]})])
        rec = self.tool.receipt("tags", "src_tags")
        rows = self.tool.arg_query(reader, {"subscriptions": [SUB_A]}, "resources | project id", rec)
        self.assertEqual([r["id"] for r in rows], ["/a", "/b"])
        self.assertEqual(opener.calls[1][2]["options"]["$skipToken"], "t1")

    def test_collection_continues_when_one_cost_query_fails(self):
        config = configure(self.tool)
        periods = self.tool.review_periods(now())
        containers = Response({"data": [{"id": f"/subscriptions/{SUB_A}", "type": "microsoft.resources/subscriptions", "name": "Prod", "subscriptionId": SUB_A}]})
        empty_arg = Response({"data": []})
        cost_ok = Response({"properties": {"columns": [{"name": "Cost"}, {"name": "UsageDate"}, {"name": "ServiceName"}, {"name": "PricingModel"},
                                                       {"name": "Currency"}], "rows": [[3.0, 20261101, "Storage", "OnDemand", "USD"]]}})
        script = [containers, empty_arg, empty_arg, empty_arg, Response({"value": []}), http_error(QUERY_URL, 403), cost_ok,
                  Response({"properties": {"columns": [], "rows": []}})]
        reader, _ = self.reader(script)
        raw = self.tool.collect(reader, config, periods)
        statuses = {r["id"]: r["status"] for r in raw["receipts"]}
        self.assertEqual(statuses["cost_monthly"], "denied")
        self.assertEqual(statuses["cost_daily"], "complete")
        snapshot = self.tool.build_snapshot(raw, config, periods, now(), {})
        self.assertEqual(snapshot["status"], "partial")
        self.assertTrue(any(f["category"] == "data" for f in snapshot["findings"]))


if __name__ == "__main__":
    unittest.main()
