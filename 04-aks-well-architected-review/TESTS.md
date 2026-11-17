# Tests — AKS fleet build (case 04)

Tool `generate-aks-waf-report.py` built from the sources (sha256
`a5671e25c0e36011e8dd9ac889a594684617e9f246d31f8afc41f8b86a8c4910`). 17 November 2026. All tests are read-only.

## 1. Package test suite — all green

`SRE_REPORT_BROWSER_TESTS=1 python -m pytest tests` (Edge, headless): **182 passed, 2 skipped, 0 failed**.
The 2 skips are the opt-in private-snapshot tests (never distributed), skipped in the original package too.
Re-run after the documentation update: still 182 passed, 2 skipped (the package contract test now checks the
English-only fleet docs, every Markdown link/anchor and that every manifest image, including the new fleet image, is referenced).
Original package for comparison: 169 passed, 1 failed (`test_operator` float formatting), 2 skipped.

New `tests/test_fleet.py` (SIMULATED, no network):

- only `TENANT_ID` + `MANAGED_IDENTITY_CLIENT_ID`: `list_clusters` over 105 clusters in 20 subscriptions, ≤ 3500
  bytes per page, `next_offset` walks every cluster once, rows with subscription name and region;
- `subscription` filter by ID or display name (case-insensitive), unknown subscription with close matches;
- selection: no selection / `all` above 100 → `too_many_clusters`; `all` + subscription; subscription only; names
  (case-insensitive, order kept); 100 names; unknown, ambiguous duplicate, repeated, 101 names, unsafe text;
  duplicate resolved with `subscription` or the prefixed key; `query` without selection → `selection_required`;
- operator override merges discovery metadata and needs a subscription when `SUBSCRIPTION_ID` is not set;
- fixed Resource Graph query (POST to the ARG endpoint, joins subscription names, no subscription filter by default);
- parallel collection of 24 clusters in 20 subscriptions: each worker sees its own subscription, bounded workers,
  order kept, 403 / exception / timeout become `error` runs, incomplete source → `partial`, scope restored;
- Cost Management 429 waits the `x-ms-ratelimit-microsoft.costmanagement-qpu-retry-after` hint; a wait beyond the
  deadline stops as `throttled` without sleeping; at most 2 cost queries in flight; throttling only marks that cost
  source;
- fleet report of 10 clusters in 3 subscriptions (one denied): envelope ≤ 3500 bytes, error listed, per-run client
  not duplicated, compressed embedded JSON equals the JSON file, CSV rows carry subscription ID and name.

New browser tests in `tests/test_report_ui.py`: fleet overview filters (subscription → KPIs, table, cluster
drop-down; cluster → detailed view; back to All; search); failed cluster stays an error and gzip-embedded JSON opens
offline with the full JSON export unchanged.

## 2. Sample run (Playwright, Edge headless)

`sample-run/simulated-20261010T120000Z-4596adfa1b2c.html` (7 clusters, 3 subscriptions, 2.6 MB): opens with no
console errors; defaults All/All with 7 clusters and 3 subscriptions; fleet overview shown and detailed sections
hidden; subscription filter updates KPIs (2 clusters in "Contoso Shared Services"), table and cluster drop-down;
search filters and restores; choosing a cluster shows its detailed review; back to All returns to the fleet.
Envelope: 4 collected, 2 partial, 1 error; 17 findings (6 high, 9 medium, 2 low); EUR 1,035.20 on 5 clusters.
Screenshots and output: `..\sample-validation\`.

## 3. Scale — 100 clusters in 20 subscriptions (mocked collection, this build)

59/59 checks; HTML 4,309,780 bytes (gzip+base64 JSON), JSON 39,556,032 bytes, findings/inventory CSV
401,678 / 6,348,918 bytes, chat response 2,656 bytes, generation 5.5 s, peak memory ~413 MB; the HTML passes the same
browser checks (100 clusters, 20 subscriptions). Output: `..\scale-validation\`.

## 4. Lab — SRE Agent Test playground (nothing deployed)

This build with the lab tenant and client ID only (`SUBSCRIPTION_ID` left as placeholder), 2 AKS clusters:
`list_clusters` 2.4 s (2 clusters, subscription name and region), `list_clusters` by subscription display name 2.1 s,
`report cluster_names="all"` 28.4 s (2 partial: Kubernetes not configured; cost USD 408.92 on 2 clusters),
`report for one lab cluster` 13.5 s. Downloaded HTML files pass the browser checks with no console errors.
Earlier runs of the same engine code also covered `list_clusters` by ID, unknown subscription, two named clusters and
`query`. Output: `..\lab-validation\`.
