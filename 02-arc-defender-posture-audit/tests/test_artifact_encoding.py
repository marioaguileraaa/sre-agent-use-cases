"""Lossless size-bounded artifacts; optional full lab fixture remains ignored."""

import copy
import csv
import hashlib
import io
import json
import math
import shutil
import subprocess
import tempfile
import unittest
from collections import Counter
from pathlib import Path
from unittest.mock import patch

from test_arc_defender_tools import REFERENCE, SCENARIO, parameters, sim, live

FIXTURES = SCENARIO.parent / "handoff-inputs" / "expanded-discovery"
CURRENT_FIXTURE = (
    SCENARIO.parent / "handoff-inputs" / "defender-size-20261013" / "actual-20261013-normalized-snapshot.json"
)


def legacy_pack(snapshot):
    """The previous v1 encoder, retained only to reproduce the full-size regression."""
    counts = Counter()

    def count(value):
        if isinstance(value, str):
            counts[value] += 1
        elif isinstance(value, dict):
            for child in value.values():
                count(child)
        elif isinstance(value, list):
            for child in value:
                count(child)

    count(snapshot)
    strings = sorted(s for s, occurrences in counts.items() if (
        len(s) >= 12 and occurrences > 1 or len(s) >= 7 and occurrences > 3
    ))
    lookup = {s: index for index, s in enumerate(strings)}

    def encode(value):
        if isinstance(value, str):
            return "~" + str(lookup[value]) if value in lookup else "~" + value if value.startswith("~") else value
        if isinstance(value, dict):
            if any(key in ("$s", "$table", "$missing") for key in value):
                raise ValueError("Reserved v1 codec key.")
            return {key: encode(child) for key, child in value.items()}
        if isinstance(value, list):
            if len(value) >= 4 and all(isinstance(row, dict) for row in value):
                fields = sorted({key for row in value for key in row})
                return {"$table": fields, "rows": [
                    [encode(row[key]) if key in row else {"$missing": True} for key in fields] for row in value
                ]}
            return [encode(child) for child in value]
        return value

    return {
        "schema_version": "2.1", "encoding": "dictionary-columns-v1",
        "provenance": snapshot["provenance"], "reference_utc": snapshot["reference_utc"],
        "summary": snapshot["summary"], "strings": strings, "data": encode(snapshot),
    }


def growing_snapshot():
    """Portable, explicitly fictional native-shaped recommendations and embedded CVEs."""
    original = sim._fixture(REFERENCE)
    inventory = copy.deepcopy(original["inventory"])
    findings = copy.deepcopy(original["findings"])
    template = next(finding for finding in findings if finding["cve_details"])
    for index in range(1800):
        resource = inventory[index % len(inventory)]
        finding = copy.deepcopy(template)
        finding.update({key: resource[key] for key in (
            "resource_id", "server_name", "resource_group", "provider", "environment",
        )})
        finding["finding_id"] = f"DEMO-REC-GROWTH-{index:05d}"
        finding["recommendation_id"] = f"DEMO-growth-definition-{index % 90:03d}"
        finding["title"] = f"SIMULATED growing package recommendation {index % 90:03d}"
        finding["status"] = ("Unhealthy", "Healthy", "NotApplicable")[index % 3]
        finding["cve_details"] = [{
            "cve_id": f"DEMO-VA-GROWTH-{index:05d}-{sequence:02d}",
            "technical_severity": ("Critical", "High", "Medium")[sequence % 3],
            "fix_status": "SIMULATED fix available", "fixed_version": "DEMO-fixed",
            "source_description": "SIMULATED nested source description retained without truncation.",
            "source_metadata": {
                "name": "DEMO package", "vendor": "SIMULATED vendor",
                "source_time_utc": REFERENCE, "optional": None, "versions": ["DEMO-old", "DEMO-fixed"],
            },
        } for sequence in range(12)]
        findings.append(finding)
    context = {key: copy.deepcopy(original[key]) for key in (
        "posture", "attack_paths", "software", "plans", "compliance", "subscription_recommendations",
    )}
    return sim._finish_snapshot(
        inventory, findings, copy.deepcopy(original["sources"]), "SIMULATED", REFERENCE,
        copy.deepcopy(original["scope"]), assumptions=copy.deepcopy(original["synthetic_assumptions"]),
        context=context,
    )


def javascript_decoder():
    document = sim._render_html(sim._fixture(REFERENCE))
    return document[document.index("function unpackSnapshot(doc) {"):
                    document.index("const snapshot = unpackSnapshot(documentData);")]


def malformed_documents():
    def doc(data, strings=None, version="dictionary-columns-v2"):
        return {"encoding": version, "strings": ["key"] if strings is None else strings, "data": data}

    values = [
        None, [], {"encoding": "unsupported"}, {"encoding": "dictionary-columns-v2", "strings": []},
        doc([1, []], "not a dictionary"), doc([1, []], [None]),
    ]
    values.extend(doc(data) for data in (
        [], [True, 0], [0, -1], [0, True], [0, 1.5], [0, 99], [0, 0, "extra"],
        [4], [5, "NaN"], [5, "Infinity"], [5, "1e1000"], [5, "01.0"], [5, 1], [5, "1.0", "extra"],
        [1, [0]], [1, [0, 1, 0, 2]], [1, [0, [4]]], [2, [[4]]],
        [3, -1, [], []], [3, True, [], []], [3, 1.5, [], []], [3, 10**20, [], []],
        [3, 4, [0], []], [3, 4, [0, 0], [[0, None], [0, None]]],
        [3, 4, [0], [[1, [1, 2, 3]]]], [3, 4, [0], [[0, None, "extra"]]],
        [3, 4, [0], [[2, [[0, 1]]]]], [3, 4, [0], [[2, [[True, 1]]]]],
        [3, 4, [0], [[2, [[5, 1]]]]], [3, 4, [0], [[2, [[3, 1]]]]],
        [3, 4, [0], [[3, None, [[4, 1]]]]], [3, 4, [0], [[3, None, [[True, 1]]]]],
        [3, 4, [0], [[3, None, [[1, 1], [1, 2]]]]], [3, 4, [0], [[99]]], {"$s": 0},
    ))
    values.append(doc([1, [0, 1, 1, 2]], ["key", "key"]))
    values.extend(doc(data, version="dictionary-columns-v1") for data in (
        {"$s": -1}, {"$s": True}, {"$s": 99}, {"$s": 0, "extra": 1},
        {"$missing": True}, {"$table": ["key"]},
        {"$table": ["key", "key"], "rows": [[1, 2]]},
        {"$table": [1], "rows": [[1]]}, {"$table": ["key"], "rows": [[1, 2]]},
        {"$table": ["key"], "rows": [[{"$missing": 1}]]}, "~invalid", "~999", "~" + "9" * 10000,
    ))
    nested = 1
    for _ in range(102):
        nested = [2, [nested]]
    values.append(doc([1, [0, nested]]))
    return values


def expansion_documents():
    def document(value, strings=None):
        return {
            "encoding": "dictionary-columns-v2", "strings": strings or ["rows", "value"],
            "data": [1, [0, value]],
        }

    inner = [3, 40000, [], []]
    return [
        document([3, 1_000_000_000, [], []], ["rows"]),
        document([3, 40000, [1], [[0, inner]]]),
        document([3, 40000, [1], [[2, [[40000, inner]]]]]),
        document([3, 40000, [1], [[3, inner, [[0, None]]]]]),
        document([2, [[3, 800000, [], []]] * 3]),
        document([3, 40000, list(range(1, 61)), [[0, [4]]] * 60],
                 ["rows"] + [f"field-{index}" for index in range(60)]),
        document([3, 3000, [1], [[0, [0, 2]]]], ["rows", "value", "x" * 24000]),
    ]


def sparse_unused_default_document():
    return {
        "encoding": "dictionary-columns-v2", "strings": ["rows", "value"],
        "data": [1, [0, [3, 100, [1], [[3, [3, 50000, [], []], [[index, None] for index in range(100)]]]]]],
    }


def native_snapshot():
    """Offline normalization of user-approved local fixtures, never Azure."""
    read = lambda filename: json.loads((FIXTURES / filename).read_text(encoding="utf-8"))
    resources = read("resource_inventory-actual.json")["data"]
    records = read("all_assessments-actual.json")["data"]
    subscription = resources[0]["id"].split("/")[2]
    known = {r["resource_id"]: r for value in resources for r in [live._resource_row(value, subscription)]}
    machines = read("arc-machines-actual.json")
    for machine in machines.get("data", machines.get("value", [])):
        row = live._inventory_row(machine, subscription, REFERENCE)
        known[row["resource_id"]] = row
    for record in records:
        resource_id = live._assessment_resource_id(record, subscription)
        if resource_id and resource_id not in known:
            details = record["properties"].get("resourceDetails", {})
            row = live._resource_row({
                "id": resource_id, "name": details.get("ResourceName", resource_id.rsplit("/", 1)[-1]),
                "type": details.get("ResourceType", "Defender/indexedAsset"),
            }, subscription, True)
            row["parent_resource_id"] = live._assessed_parent(record, resource_id, known, subscription)
            known[resource_id] = row
    inventory = list(known.values())
    findings, _ = live._normalize_findings(
        records, "defender_recommendations", inventory, subscription, REFERENCE, arc_only=False
    )
    discovery = {row["source"]: row.get("rows", []) for row in read("posture-source-discovery.json")}
    context = {
        "posture": {
            "scores": live._normalize_context(discovery["secure_scores"], "subscription_secure_score", subscription, REFERENCE),
            "controls": live._normalize_context(
                read("score_controls-actual.json")["data"], "secure_score_controls", subscription, REFERENCE
            ),
            "risk_score_observations": live._normalize_context(
                read("risk_scores-actual.json")["data"], "risk_secure_score", subscription, REFERENCE
            ),
        },
        "attack_paths": live._normalize_attack_paths(read("attackpaths-actual.json")["data"], inventory, subscription, REFERENCE),
        "software": live._normalize_software(read("software-actual.json")["data"], inventory, subscription, REFERENCE),
        "compliance": {
            "standards": live._normalize_context(
                discovery["regulatory_standards"], "compliance_standards", subscription, REFERENCE
            ),
            "controls": live._normalize_context(
                read("compliance_controls-actual.json")["data"], "compliance_controls", subscription, REFERENCE
            ),
            "assessments": live._normalize_context(
                read("compliance_assessments-actual.json")["data"], "compliance_assessments", subscription, REFERENCE
            ),
        },
        "subscription_recommendations": live._subscription_recommendations(records, subscription, REFERENCE),
        "plans": [{
            "name": row["name"], "pricing_tier": row["pricingTier"], "sub_plan": row["subPlan"],
            "coverage": row["coverage"], "scope": "Subscription context",
        } for row in discovery["plans"]],
    }
    sources = [{
        "name": name, "status": "complete", "records": len(records) if name == "defender_recommendations" else 0,
        "reference_utc": REFERENCE, "note": "Offline source fixture replay, not a live API call.", "errors": [],
    } for name in (
        "arc_inventory", "defender_recommendations", "defender_vulnerabilities", "defender_alerts",
        "attack_paths", "software_inventory", "subscription_secure_score", "secure_score_controls",
    )]
    return live._finish_snapshot(inventory, findings, sources, "LIVE", REFERENCE, {
        "subscription_id": subscription, "tenant_id": "fixture-only",
        "description": "Offline approved fixture; not a runtime observation.",
    }, context=context)


class LosslessEncodingTests(unittest.TestCase):
    def test_round_trip_preserves_all_fields_records_empty_missing_and_null(self):
        snapshot = sim._fixture(REFERENCE)
        snapshot["codec_test"] = [{"a": None, "b": "repeated-string-long-enough"}] * 4 + [
            {"a": []}, {}, {"literal_tilde": "~123", "literal_double_tilde": "~~123"},
            {"types": [True, False, 0, -7, 1.0, -0.0, 0.125, 1e30, None, {}, []],
             "unicode": "Espa\u00f1a \u03a9 \U0001f642 \u2028 \u2029"},
        ]
        packed = sim._pack_snapshot(snapshot)
        restored = sim._unpack_snapshot(json.loads(json.dumps(packed)))
        self.assertEqual(restored, snapshot)
        self.assertEqual([type(value) for value in restored["codec_test"][-1]["types"]],
                         [type(value) for value in snapshot["codec_test"][-1]["types"]])
        self.assertEqual(math.copysign(1, restored["codec_test"][-1]["types"][5]), -1)
        self.assertEqual(sim._unpack_snapshot(snapshot), snapshot)
        self.assertEqual(packed["encoding"], "dictionary-columns-v2")
        self.assertEqual(packed["schema_version"], "2.2")

    def test_literal_reserved_keys_values_and_arrays_are_not_codec_markers(self):
        snapshot = sim._fixture(REFERENCE)
        snapshot["codec_literals"] = [
            {"$s": 0}, {"$missing": True}, {"$table": ["literal"], "rows": [[None]]},
            {"__proto__": {"polluted": True}, "constructor": [0, 1], "prototype": "literal"},
            [4], [0, 0], [1, []], [3, 4, [], []], "~0", "~~0", "dictionary-columns-v2",
        ]
        self.assertEqual(sim._unpack_snapshot(sim._pack_snapshot(snapshot)), snapshot)

    def test_all_column_modes_preserve_types_missing_values_order_and_independent_objects(self):
        snapshot = sim._fixture(REFERENCE)
        rows = [{
            "constant": {"nested": [True, None]}, "dense": index, "runs": index // 100,
            "sparse": True if index == 555 else None,
            **({"optional": []} if index == 555 else {}),
        } for index in range(1000)]
        snapshot["codec_columns"] = rows
        packed = sim._pack_snapshot(snapshot)
        pairs = packed["data"][1]
        table = next(pairs[index + 1] for index in range(0, len(pairs), 2)
                     if packed["strings"][pairs[index]] == "codec_columns")
        modes = {packed["strings"][field]: column[0] for field, column in zip(table[2], table[3])}
        self.assertEqual({key: modes[key] for key in ("constant", "dense", "runs", "sparse")},
                         {"constant": 0, "dense": 1, "runs": 2, "sparse": 3})
        restored = sim._unpack_snapshot(packed)
        self.assertEqual(restored, snapshot)
        self.assertNotIn("optional", restored["codec_columns"][554])
        self.assertEqual(restored["codec_columns"][555]["optional"], [])
        restored["codec_columns"][0]["constant"]["nested"].append("changed")
        self.assertEqual(restored["codec_columns"][1]["constant"], {"nested": [True, None]})

    def test_historical_v1_and_ordinary_documents_still_decode_exactly(self):
        snapshot = sim._fixture(REFERENCE)
        self.assertEqual(sim._unpack_snapshot(legacy_pack(snapshot)), snapshot)
        legacy = {
            "encoding": "dictionary-columns-v1", "strings": ["shared"], "data": {
                "reference": {"$s": 0}, "tilde": "~~0",
                "records": {"$table": ["present", "absent", "null"], "rows": [
                    ["~0", {"$missing": True}, None],
                ]},
            },
        }
        self.assertEqual(sim._unpack_snapshot(legacy), {
            "reference": "shared", "tilde": "~0", "records": [{"present": "shared", "null": None}],
        })

    def test_invalid_references_and_tables_fail_explicitly(self):
        for value in malformed_documents():
            with self.subTest(document=value), self.assertRaises(sim.EvidenceError) as raised:
                sim._unpack_snapshot(value)
            self.assertEqual(raised.exception.code, "invalid_encoding")

    def test_encoder_rejects_non_json_values_and_excessive_nesting_explicitly(self):
        nested = None
        for _ in range(102):
            nested = [nested]
        for bad in (float("nan"), float("inf"), float("-inf"), {1: "not a string key"}, {1, 2}, nested):
            snapshot = sim._fixture(REFERENCE)
            snapshot["invalid_value"] = bad
            with self.subTest(value=type(bad)), self.assertRaises(sim.EvidenceError) as raised:
                sim._pack_snapshot(snapshot)
            self.assertEqual(raised.exception.code, "invalid_encoding")

    def test_size_guard_does_not_publish_truncated_success_or_partial_files(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(sim.Path, "cwd", return_value=Path(folder)):
            with patch.object(sim, "MAX_ARTIFACT_BYTES", 100):
                result = sim.main(operation="report")
            self.assertEqual(result["status"], "error")
            self.assertEqual(result["error"]["code"], "artifact_size_exceeded")
            self.assertNotIn("report_path", result)
            self.assertEqual(list(Path(folder).iterdir()), [])

    def test_html_uses_lossless_packed_data_and_pages_but_csv_keeps_all_matches(self):
        snapshot = sim._fixture(REFERENCE)
        html = sim._render_html(snapshot)
        embedded = html.split('<script type="application/json" id="report-data">', 1)[1].split("</script>", 1)[0]
        self.assertEqual(sim._unpack_snapshot(json.loads(embedded)), snapshot)
        self.assertIn("filteredFindings.slice(0,findingLimit)", html)
        self.assertIn("exportCsv(filteredFindings", html)
        self.assertIn("CSV exports ALL matches", html)
        self.assertNotIn("innerHTML", html)

    def test_exact_utf8_html_limit_accepts_boundary_and_rejects_one_extra_byte(self):
        snapshot = sim._fixture(REFERENCE)
        for extra in ("", "x"):
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as folder:
                with patch.object(sim.Path, "cwd", return_value=Path(folder)), \
                     patch.object(sim, "_render_html", return_value="\u00e9" * 2_400_000 + extra):
                    if extra:
                        with self.assertRaises(sim.EvidenceError) as raised:
                            sim._write_report(snapshot)
                        self.assertEqual(raised.exception.code, "artifact_size_exceeded")
                        self.assertEqual(list(Path(folder).iterdir()), [])
                    else:
                        result = sim._write_report(snapshot)
                        self.assertEqual(Path(result["report_path"]).stat().st_size, 4_800_000)

    def test_exact_json_limit_and_oversized_packed_json_never_publish_partial_files(self):
        snapshot = sim._fixture(REFERENCE)
        snapshot["limit_test"] = ""
        base = len(json.dumps(snapshot, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
        snapshot["limit_test"] = "x" * (4_800_000 - base)
        for extra in ("", "x"):
            snapshot["limit_test"] += extra
            with self.subTest(extra=extra), tempfile.TemporaryDirectory() as folder:
                with patch.object(sim.Path, "cwd", return_value=Path(folder)), \
                     patch.object(sim, "_render_html", return_value="<html>Guard-only fixture</html>"), \
                     patch.object(sim, "_pack_snapshot", return_value=snapshot) as encoder:
                    if extra:
                        with self.assertRaises(sim.EvidenceError) as raised:
                            sim._write_report(snapshot)
                        self.assertEqual(raised.exception.code, "artifact_size_exceeded")
                        self.assertEqual(list(Path(folder).iterdir()), [])
                        encoder.assert_called_once()
                    else:
                        result = sim._write_report(snapshot)
                        self.assertEqual(Path(result["snapshot_path"]).stat().st_size, 4_800_000)
                        encoder.assert_not_called()

    def test_failure_publishing_any_of_four_artifacts_cleans_all_run_files(self):
        replace = sim.os.replace
        snapshot = sim._fixture(REFERENCE)
        for failure_at in range(1, 5):
            calls = 0

            def fail_at(source, target):
                nonlocal calls
                calls += 1
                if calls == failure_at:
                    raise OSError("Injected publish failure")
                return replace(source, target)

            with self.subTest(failure_at=failure_at), tempfile.TemporaryDirectory() as folder:
                with patch.object(sim.Path, "cwd", return_value=Path(folder)), \
                     patch.object(sim.os, "replace", side_effect=fail_at):
                    with self.assertRaises(sim.EvidenceError) as raised:
                        sim._write_report(snapshot)
                self.assertEqual(raised.exception.code, "artifact_write_failed")
                self.assertEqual(list((Path(folder) / "arc-defender-reports").iterdir()), [])


class PortableGrowthRegressionTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = growing_snapshot()

    def test_full_native_shaped_growth_exceeds_original_guard_but_v2_has_headroom(self):
        snapshot = self.snapshot
        old = legacy_pack(snapshot)
        self.assertGreater(len(json.dumps(old, ensure_ascii=False, separators=(",", ":")).encode("utf-8")), 4_800_000)
        with patch.object(sim, "_pack_snapshot", side_effect=legacy_pack):
            old_html = sim._render_html(snapshot)
            self.assertGreater(len(old_html.encode("utf-8")), 4_800_000)
            with tempfile.TemporaryDirectory() as folder, patch.object(sim.Path, "cwd", return_value=Path(folder)):
                with self.assertRaises(sim.EvidenceError) as raised:
                    sim._write_report(snapshot)
                self.assertEqual(raised.exception.code, "artifact_size_exceeded")
                self.assertEqual(list(Path(folder).iterdir()), [])
        with tempfile.TemporaryDirectory() as folder, patch.object(sim.Path, "cwd", return_value=Path(folder)):
            result = sim._write_report(snapshot)
            for key in ("report_path", "snapshot_path"):
                self.assertLessEqual(Path(result[key]).stat().st_size, 4_300_000)
            restored = sim._unpack_snapshot(json.loads(Path(result["snapshot_path"]).read_text(encoding="utf-8")))
            self.assertEqual(restored, snapshot)
            self.assertLessEqual(len(json.dumps(result).encode("utf-8")), 3500)
            html = Path(result["report_path"]).read_text(encoding="utf-8")
            self.assertEqual(html.split('<script type="application/json"', 1)[0],
                             old_html.split('<script type="application/json"', 1)[0])
            for key, rows, fields in (
                ("csv_path", snapshot["inventory"], sim.INVENTORY_CSV_FIELDS),
                ("findings_csv_path", snapshot["findings"], sim.FINDING_CSV_FIELDS),
            ):
                with Path(result[key]).open(encoding="utf-8-sig", newline="") as stream:
                    document = stream.read()
                self.assertEqual(document, sim._csv_document(rows, fields))
                self.assertEqual(len(list(csv.DictReader(io.StringIO(document)))), len(rows))

    def test_queries_and_all_default_serializer_budgets_are_unchanged_after_decode(self):
        snapshot = self.snapshot
        restored = sim._unpack_snapshot(sim._pack_snapshot(snapshot))
        for view in sim.VIEWS:
            with self.subTest(view=view):
                params = parameters(view=view, limit=100)
                result = sim._query(snapshot, params)
                self.assertEqual(sim._query(restored, params), result)
                self.assertLessEqual(len(json.dumps(result).encode("utf-8")), 3500)


class ExpansionBudgetTests(unittest.TestCase):
    def test_billion_rows_and_nested_amplification_fail_before_any_row_allocation(self):
        builtin_range = range

        def no_rows(*args):
            if len(args) == 1 and args[0] > 0:
                raise AssertionError("Row/cell allocation reached before the expansion guard.")
            return builtin_range(*args)

        for module in (live, sim):
            for document in expansion_documents():
                with self.subTest(module=module.__name__, data=document["data"]):
                    with patch.object(module, "range", no_rows, create=True):
                        with self.assertRaises(module.EvidenceError) as raised:
                            module._unpack_snapshot(document)
                    self.assertEqual(raised.exception.code, "encoding_expansion_exceeded")
                    self.assertEqual(raised.exception.source, "artifact_encoding")

    def test_exact_node_and_unicode_string_budgets_match_encoder_and_decoder(self):
        snapshot = {
            "provenance": "SIMULATED", "reference_utc": REFERENCE, "summary": {},
            "rows": [{"text": "\u20ac\U0001f642", "optional": None}, {"text": "\u20ac\U0001f642"},
                     {"text": "\u20ac\U0001f642", "optional": False}, {}],
        }
        packed = sim._pack_snapshot(snapshot)
        nodes, units = sim._check_snapshot_expansion(packed["data"], packed["strings"])
        for node_limit, string_limit in ((nodes, units), (nodes - 1, units), (nodes, units - 1)):
            with self.subTest(nodes=node_limit, units=string_limit):
                with patch.object(sim, "MAX_DECODED_NODES", node_limit), \
                     patch.object(sim, "MAX_DECODED_STRING_UNITS", string_limit):
                    if node_limit == nodes and string_limit == units:
                        self.assertEqual(sim._unpack_snapshot(packed), snapshot)
                        self.assertEqual(sim._pack_snapshot(snapshot), packed)
                    else:
                        for operation in (lambda: sim._unpack_snapshot(packed), lambda: sim._pack_snapshot(snapshot)):
                            with self.assertRaises(sim.EvidenceError) as raised:
                                operation()
                            self.assertEqual(raised.exception.code, "encoding_expansion_exceeded")

    def test_plain_and_v1_compatibility_is_not_restricted_by_the_new_v2_budget(self):
        snapshot = sim._fixture(REFERENCE)
        old = legacy_pack(snapshot)
        with patch.object(sim, "MAX_DECODED_NODES", 0), patch.object(sim, "MAX_DECODED_STRING_UNITS", 0):
            self.assertEqual(sim._unpack_snapshot(snapshot), snapshot)
            self.assertEqual(sim._unpack_snapshot(old), snapshot)

    def test_sparse_overrides_do_not_allocate_unused_default_subtrees(self):
        builtin_range = range

        def safe_range(*args):
            if len(args) == 1 and args[0] > 1000:
                raise AssertionError("Unused sparse default was expanded.")
            return builtin_range(*args)

        for module in (live, sim):
            with self.subTest(module=module.__name__), patch.object(module, "range", safe_range, create=True):
                self.assertEqual(module._unpack_snapshot(sparse_unused_default_document()),
                                 {"rows": [{"value": None} for _ in range(100)]})

    def test_report_expansion_failure_returns_explicit_error_without_any_files(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(sim.Path, "cwd", return_value=Path(folder)), \
             patch.object(sim, "MAX_DECODED_NODES", 0):
            result = sim.main(operation="report")
            self.assertEqual(list(Path(folder).iterdir()), [])
        self.assertEqual(result["status"], "error")
        self.assertEqual(result["error"]["code"], "encoding_expansion_exceeded")
        self.assertNotIn("report_path", result)


@unittest.skipUnless(shutil.which("node"), "Node.js is optional for portable HTML decoder parity checks.")
class JavascriptDecoderTests(unittest.TestCase):
    def decode(self, documents):
        program = javascript_decoder() + """
const fs = require("node:fs");
const documents = JSON.parse(fs.readFileSync(0,"utf8"));
process.stdout.write(JSON.stringify(documents.map(doc => {
  try {return {ok:true,value:unpackSnapshot(doc)};}
  catch (error) {return {ok:false,error:error.message};}
})));
"""
        result = subprocess.run(
            [shutil.which("node"), "-e", program], input=json.dumps(documents), text=True,
            encoding="utf-8", capture_output=True, check=True, timeout=30,
        )
        return json.loads(result.stdout)

    def test_exact_python_javascript_parity_for_plain_v1_v2_and_reserved_literals(self):
        snapshot = sim._fixture(REFERENCE)
        snapshot["codec_test"] = [
            {"value": None}, {}, {"value": []}, {"value": {}},
            {"value": [True, False, 0, -1, 0.125, "~0", "~~0", "Espa\u00f1a \U0001f642"]},
        ]
        documents = [snapshot, legacy_pack(snapshot), sim._pack_snapshot(snapshot)]
        literal = copy.deepcopy(snapshot)
        literal["reserved"] = [{"$missing": True}, {"$s": 0}, {"$table": [], "rows": []},
                               {"__proto__": {"polluted": True}}, [4], [0, 0]]
        documents.append(sim._pack_snapshot(literal))
        for document, result in zip(documents, self.decode(documents)):
            self.assertTrue(result["ok"])
            self.assertEqual(result["value"], sim._unpack_snapshot(document))

    def test_malformed_and_truncated_documents_fail_in_both_decoders(self):
        for document, result in zip(malformed_documents(), self.decode(malformed_documents())):
            with self.subTest(document=document):
                self.assertFalse(result["ok"])
                self.assertTrue(result["error"])
                with self.assertRaises(sim.EvidenceError):
                    sim._unpack_snapshot(document)

    def test_expansion_guard_precedes_javascript_row_or_cell_allocation(self):
        program = javascript_decoder() + """
const fs = require("node:fs"), attempts = [], original = Array.from;
Array.from = function(value,...args) {
  if (value && !Array.isArray(value) && typeof value === "object"
      && Object.hasOwn(value,"length") && value.length > 0) {
    attempts.push(value.length); throw new Error("Unsafe allocation intercepted");
  }
  return original.call(this,value,...args);
};
const results = JSON.parse(fs.readFileSync(0,"utf8")).map(doc => {
  try {unpackSnapshot(doc); return "accepted";}
  catch (error) {return error.message;}
});
process.stdout.write(JSON.stringify({results,attempts}));
"""
        result = subprocess.run(
            [shutil.which("node"), "-e", program], input=json.dumps(expansion_documents()), text=True,
            encoding="utf-8", capture_output=True, check=True, timeout=30,
        )
        proof = json.loads(result.stdout)
        self.assertEqual(proof["attempts"], [])
        self.assertTrue(all("bounded decoded expansion budget" in message for message in proof["results"]))

    def test_exact_unicode_budgets_match_python_and_embedded_javascript(self):
        snapshot = {
            "provenance": "SIMULATED", "reference_utc": REFERENCE, "summary": {},
            "rows": [{"text": "\u20ac\U0001f642"}, {"text": "\u20ac\U0001f642"}, {}, {"text": None}],
        }
        document = sim._pack_snapshot(snapshot)
        nodes, units = sim._check_snapshot_expansion(document["data"], document["strings"])
        for node_limit, string_limit in ((nodes, units), (nodes - 1, units), (nodes, units - 1)):
            with self.subTest(nodes=node_limit, units=string_limit):
                with patch.object(sim, "MAX_DECODED_NODES", node_limit), \
                     patch.object(sim, "MAX_DECODED_STRING_UNITS", string_limit), \
                     patch.object(sim, "_pack_snapshot", side_effect=legacy_pack):
                    result = self.decode([document])[0]
                self.assertEqual(result["ok"], node_limit == nodes and string_limit == units)
                if result["ok"]:
                    self.assertEqual(result["value"], snapshot)
                else:
                    self.assertIn("bounded decoded expansion budget", result["error"])


@unittest.skipUnless((FIXTURES / "all_assessments-actual.json").is_file(),
                     "Private actual fixtures are deliberately not distributed in the repository.")
class HistoricalFixtureSizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.snapshot = native_snapshot()

    def test_exact_native_cohorts_survive_lossless_encoding(self):
        snapshot = self.snapshot
        self.assertEqual(len(snapshot["findings"]), 1693)
        self.assertEqual(snapshot["summary"]["recommendation_status_counts"], {
            "Healthy": 486, "Unhealthy": 1118, "NotApplicable": 89,
        })
        self.assertEqual(snapshot["summary"]["embedded_cve_records"], 7495)
        self.assertEqual(snapshot["summary"]["distinct_embedded_cves"], 2767)
        self.assertEqual(snapshot["summary"]["distinct_resource_cve_pairs"], 7148)
        self.assertEqual(live._unpack_snapshot(live._pack_snapshot(snapshot)), snapshot)
        for name, unhealthy in (("ArcBox-SQL", 103), ("ArcBox-Win2K25", 171)):
            row = next(r for r in snapshot["inventory"] if r["server_name"] == name)
            self.assertEqual(row["recommendation_status_counts"]["Unhealthy"], unhealthy)

    def test_plain_html_and_snapshot_are_below_exact_sharing_size_threshold(self):
        with tempfile.TemporaryDirectory() as folder, patch.object(live.Path, "cwd", return_value=Path(folder)):
            result = live._write_report(self.snapshot)
            for key in ("report_path", "snapshot_path"):
                self.assertLessEqual(Path(result[key]).stat().st_size, 4_800_000)
            document = json.loads(Path(result["snapshot_path"]).read_text(encoding="utf-8"))
            self.assertEqual(live._unpack_snapshot(document), self.snapshot)
            self.assertLessEqual(len(json.dumps(result).encode("utf-8")), 3500)


@unittest.skipUnless(CURRENT_FIXTURE.is_file(), "Private 13 October regression fixture is deliberately not distributed.")
class CurrentFixtureSizeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        raw = CURRENT_FIXTURE.read_bytes()
        if hashlib.sha256(raw).hexdigest() != "ad5f262727eaee3a5efc55df47326010083069b28b72e78166991d6b29bbe0ac":
            raise AssertionError("The private current normalized fixture differs from its verified receipt.")
        cls.snapshot = json.loads(raw)

    def test_exact_current_full_cohorts_and_all_fields_round_trip(self):
        snapshot = self.snapshot
        self.assertEqual({key: len(snapshot[key]) for key in (
            "inventory", "findings", "recommendation_groups", "vulnerabilities", "software",
            "subscription_recommendations", "attack_paths", "sources", "plans", "actions",
        )}, {
            "inventory": 553, "findings": 1983, "recommendation_groups": 989, "vulnerabilities": 8350,
            "software": 1134, "subscription_recommendations": 1983, "attack_paths": 3,
            "sources": 20, "plans": 18, "actions": 8,
        })
        self.assertEqual(snapshot["summary"]["recommendation_status_counts"],
                         {"Healthy": 486, "Unhealthy": 1408, "NotApplicable": 89})
        self.assertEqual(snapshot["summary"]["recommendation_risk_counts"], {"High": 51, "Medium": 687, "Low": 670})
        self.assertEqual(snapshot["summary"]["distinct_embedded_cves"], 3005)
        self.assertEqual(snapshot["summary"]["distinct_resource_cve_pairs"], 7411)
        restored = live._unpack_snapshot(json.loads(json.dumps(live._pack_snapshot(snapshot))))
        self.assertEqual(restored, snapshot)
        self.assertEqual(restored["status"], "partial")

    def test_current_repro_size_headroom_and_complete_ordinary_csvs(self):
        snapshot = self.snapshot
        previous = legacy_pack(snapshot)
        self.assertEqual(len(json.dumps(previous, ensure_ascii=False, separators=(",", ":")).encode("utf-8")), 5_487_756)
        with tempfile.TemporaryDirectory() as folder, patch.object(live.Path, "cwd", return_value=Path(folder)):
            result = live._write_report(snapshot)
            for key in ("report_path", "snapshot_path"):
                self.assertLessEqual(Path(result[key]).stat().st_size, 4_300_000)
            self.assertEqual(Path(result["csv_path"]).stat().st_size, 438_831)
            self.assertEqual(Path(result["findings_csv_path"]).stat().st_size, 5_270_731)
            self.assertEqual(live._unpack_snapshot(json.loads(Path(result["snapshot_path"]).read_text(encoding="utf-8"))),
                             snapshot)
            self.assertLessEqual(len(json.dumps(result).encode("utf-8")), 3500)
            for key, rows, fields in (
                ("csv_path", snapshot["inventory"], live.INVENTORY_CSV_FIELDS),
                ("findings_csv_path", snapshot["findings"], live.FINDING_CSV_FIELDS),
            ):
                self.assertEqual(Path(result[key]).read_bytes(), b"\xef\xbb\xbf" + live._csv_document(rows, fields).encode("utf-8"))
                self.assertTrue(Path(result[key]).is_absolute())
