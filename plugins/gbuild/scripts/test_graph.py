import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph import (  # noqa: E402
    GraphError,
    acceptance_nodes,
    compute_frontier,
    compute_report,
    gbuild_nodes,
    load_graph,
    satisfies,
    topo_waves,
    validate,
)
from validate_format import TYPE_TO_LABEL  # noqa: E402

PLUGIN_ROOT = Path(__file__).resolve().parent.parent
TEMPLATE = PLUGIN_ROOT / "templates" / "graph.json"
CYPHERLITE_BIN = shutil.which("cypherlite")


# --- canonical factories emitting GraphData ---------------------------------

def _gbuild_node(nid, slug, ntype="code", deps=None, satisfies_acc=None, **overrides):
    """Build a GbuildNode dict. deps/satisfies_acc are slug/acceptance-id lists
    resolved to ids by graph_of; here we only stash the raw properties."""
    base = {
        "id": nid,
        "labels": ["GbuildNode", TYPE_TO_LABEL[ntype]],
        "properties": {
            "slug": slug,
            "title": slug,
            "type": ntype,
            "contract": {"input": {}, "output": {}},
            "acceptance": [f"{slug} produces its declared output"],
            "verify": None,
            "failure_policy": "retry",
            "model_tier": "cheap",
        },
    }
    base["properties"].update(overrides.pop("props", {}))
    base.update(overrides)
    base["_deps"] = deps or []
    base["_satisfies"] = satisfies_acc or []
    return base


def graph_of(*nodes, acceptance=None, feature="test", destination="test",
             context="test", out_of_scope=None):
    """Assemble a full GraphData document.

    ids: Feature=1, then one Acceptance node per acceptance bullet, then
    GbuildNodes in the order given. Edges: HAS_ACCEPTANCE (feature->acceptance),
    SATISFIES (node->acceptance), DEPENDS_ON (node->node), all sequential.
    """
    out_nodes = []
    out_rels = []
    nid = 1
    rid = 1

    out_nodes.append({
        "id": nid,
        "labels": ["Feature"],
        "properties": {
            "feature": feature,
            "destination": destination,
            "context": context,
            "out_of_scope": out_of_scope or [],
        },
    })
    feature_id = nid
    nid += 1

    # acceptance nodes
    acc_id_by_key = {}  # "a-1" -> node id
    for acc in (acceptance or []):
        out_nodes.append({
            "id": nid,
            "labels": ["Acceptance"],
            "properties": {"id": acc["id"], "text": acc["text"]},
        })
        out_rels.append({
            "id": rid, "type": "HAS_ACCEPTANCE",
            "start_node": feature_id, "end_node": nid, "properties": {},
        })
        acc_id_by_key[acc["id"]] = nid
        nid += 1
        rid += 1

    # gbuild nodes — assign ids, remember slug->id for edge wiring
    slug_to_id = {}
    staged = []
    for n in nodes:
        n = dict(n)
        n["id"] = nid
        slug_to_id[n["properties"]["slug"]] = nid
        staged.append(n)
        nid += 1
    # If no node declares any explicit satisfies, auto-wire every acceptance
    # to every gbuild node so coverage holds for structural-only test graphs.
    explicit_satisfies = any(n.get("_satisfies") for n in staged)
    # strip the _deps/_satisfies stashed props and wire edges
    for n in staged:
        raw_deps = n.pop("_deps", [])
        raw_satisfies = n.pop("_satisfies", [])
        for dep_slug in raw_deps:
            # allow dangling deps (end_node that doesn't exist) so validate can
            # reject them; unknown slugs get a sentinel id.
            out_rels.append({
                "id": rid, "type": "DEPENDS_ON",
                "start_node": n["id"], "end_node": slug_to_id.get(dep_slug, -1),
                "properties": {},
            })
            rid += 1
        if explicit_satisfies:
            for acc_key in raw_satisfies:
                out_rels.append({
                    "id": rid, "type": "SATISFIES",
                    "start_node": n["id"], "end_node": acc_id_by_key[acc_key],
                    "properties": {},
                })
                rid += 1
        else:
            for acc_nid in acc_id_by_key.values():
                out_rels.append({
                    "id": rid, "type": "SATISFIES",
                    "start_node": n["id"], "end_node": acc_nid, "properties": {},
                })
                rid += 1
    out_nodes.extend(staged)

    return {
        "nodes": out_nodes,
        "relationships": out_rels,
        "indexes": [],
        "constraints": [],
        "next_node_id": nid,
        "next_rel_id": rid,
    }


def node(slug, deps=None, satisfies=None, ntype="code", **overrides):
    return _gbuild_node(None, slug, ntype=ntype, deps=deps, satisfies_acc=satisfies, **overrides)


def write_checkpoint(state_dir, slug, status, **fields):
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    payload = {"status": status, **fields}
    (Path(state_dir) / f"{slug}.json").write_text(json.dumps(payload))


ACC = [{"id": "a-1", "text": "feature bar"}]


class ChainTests(unittest.TestCase):
    def test_waves_are_one_node_each(self):
        g = graph_of(node("a"), node("b", ["a"]), node("c", ["b"]), acceptance=ACC)
        validate(g)
        self.assertEqual(topo_waves(g), [["a"], ["b"], ["c"]])

    def test_frontier_is_only_the_root(self):
        g = graph_of(node("a"), node("b", ["a"]), node("c", ["b"]), acceptance=ACC)
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(compute_frontier(g, d), ["a"])


class DiamondTests(unittest.TestCase):
    def setUp(self):
        self.g = graph_of(
            node("a"),
            node("b", ["a"]),
            node("c", ["a"]),
            node("d", ["b", "c"]),
            acceptance=ACC,
        )
        validate(self.g)

    def test_waves_group_b_and_c_together(self):
        self.assertEqual(topo_waves(self.g), [["a"], ["b", "c"], ["d"]])

    def test_b_and_c_both_blocked_until_a_completes(self):
        with tempfile.TemporaryDirectory() as d:
            report = compute_report(self.g, d)
            self.assertEqual(report["frontier"], ["a"])
            self.assertEqual(report["blocked"], ["b", "c", "d"])

    def test_b_and_c_become_frontier_together_once_a_completes(self):
        with tempfile.TemporaryDirectory() as d:
            write_checkpoint(d, "a", "completed")
            report = compute_report(self.g, d)
            self.assertEqual(report["frontier"], ["b", "c"])
            self.assertEqual(report["blocked"], ["d"])

    def test_d_waits_for_both_b_and_c(self):
        with tempfile.TemporaryDirectory() as d:
            write_checkpoint(d, "a", "completed")
            write_checkpoint(d, "b", "completed")
            report = compute_report(self.g, d)
            self.assertEqual(report["frontier"], ["c"])
            self.assertEqual(report["blocked"], ["d"])

            write_checkpoint(d, "c", "completed")
            report = compute_report(self.g, d)
            self.assertEqual(report["frontier"], ["d"])
            self.assertEqual(report["blocked"], [])

    def test_resume_skips_completed_nodes(self):
        with tempfile.TemporaryDirectory() as d:
            write_checkpoint(d, "a", "completed")
            write_checkpoint(d, "b", "completed")
            write_checkpoint(d, "c", "completed")
            report = compute_report(self.g, d)
            self.assertEqual(report["completed"], ["a", "b", "c"])
            self.assertEqual(report["frontier"], ["d"])

    def test_cancelled_dependency_counts_as_satisfied(self):
        with tempfile.TemporaryDirectory() as d:
            write_checkpoint(d, "a", "completed")
            write_checkpoint(d, "b", "cancelled")
            write_checkpoint(d, "c", "completed")
            report = compute_report(self.g, d)
            self.assertEqual(report["frontier"], ["d"])


class ValidationTests(unittest.TestCase):
    def test_cycle_is_rejected(self):
        g = graph_of(node("a", ["b"]), node("b", ["a"]), acceptance=ACC)
        with self.assertRaises(GraphError):
            validate(g)

    def test_missing_dependency_is_rejected(self):
        g = graph_of(node("a", ["ghost"]), acceptance=ACC)
        with self.assertRaises(GraphError):
            validate(g)

    def test_empty_acceptance_is_rejected(self):
        n = node("a")
        n["properties"]["acceptance"] = []
        g = graph_of(n, acceptance=ACC)
        with self.assertRaises(GraphError):
            validate(g)

    def test_blank_acceptance_bullet_is_rejected(self):
        n = node("a")
        n["properties"]["acceptance"] = ["   "]
        g = graph_of(n, acceptance=ACC)
        with self.assertRaises(GraphError):
            validate(g)

    def test_uncovered_acceptance_is_rejected(self):
        # acceptance a-2 has no SATISFIES edge
        g = graph_of(node("a", satisfies=["a-1"]),
                     acceptance=ACC + [{"id": "a-2", "text": "uncovered"}])
        with self.assertRaises(GraphError):
            validate(g)

    def test_counter_invariant_is_checked(self):
        g = graph_of(node("a"), acceptance=ACC)
        g["next_node_id"] = 999
        with self.assertRaises(GraphError):
            validate(g)

    def test_satisfies_property_is_rejected(self):
        n = node("a")
        n["properties"]["satisfies"] = ["a-1"]
        g = graph_of(n, acceptance=ACC)
        with self.assertRaises(GraphError):
            validate(g)


class TemplateTests(unittest.TestCase):
    def test_template_validates(self):
        g = load_graph(str(TEMPLATE))
        validate(g)  # raises if invalid

    def test_template_waves(self):
        g = load_graph(str(TEMPLATE))
        self.assertEqual(topo_waves(g), [
            ["a-produce-shared-value"],
            ["b-consume-doubled", "c-consume-squared"],
            ["d-join-and-sum"],
        ])

    def test_template_frontier_is_root(self):
        g = load_graph(str(TEMPLATE))
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(compute_frontier(g, d), ["a-produce-shared-value"])

    def test_template_acceptance_coverage(self):
        g = load_graph(str(TEMPLATE))
        # every acceptance node is targeted by >=1 SATISFIES and 1 HAS_ACCEPTANCE
        acc_ids = {n["id"] for n in acceptance_nodes(g)}
        sat_targets = set()
        has_targets = set()
        for r in g["relationships"]:
            if r["type"] == "SATISFIES":
                sat_targets.add(r["end_node"])
            if r["type"] == "HAS_ACCEPTANCE":
                has_targets.add(r["end_node"])
        self.assertEqual(acc_ids, sat_targets)
        self.assertEqual(acc_ids, has_targets)

    def test_template_counters(self):
        g = load_graph(str(TEMPLATE))
        max_nid = max(n["id"] for n in g["nodes"])
        max_rid = max(r["id"] for r in g["relationships"])
        self.assertEqual(g["next_node_id"], max_nid + 1)
        self.assertEqual(g["next_rel_id"], max_rid + 1)


@unittest.skipUnless(CYPHERLITE_BIN, "cypherlite binary not on PATH")
class CypherLiteLoadTests(unittest.TestCase):
    def test_validator_cross_check_passes_on_template(self):
        # main() should exit 0 — stdlib checks pass AND cypherlite loads it.
        res = subprocess.run(
            ["python3", str(PLUGIN_ROOT / "scripts" / "validate_format.py"), str(TEMPLATE)],
            capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("valid:", res.stdout)

    def test_validator_cross_check_can_be_disabled(self):
        res = subprocess.run(
            ["python3", str(PLUGIN_ROOT / "scripts" / "validate_format.py"),
             "--no-cypherlite", str(TEMPLATE)],
            capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        self.assertIn("valid:", res.stdout)

    def test_template_loads_and_queries(self):
        g = load_graph(str(TEMPLATE))
        q = "MATCH (n:GbuildNode) RETURN n.slug AS slug ORDER BY slug"
        res = subprocess.run(
            [CYPHERLITE_BIN, str(TEMPLATE), "-json", q],
            capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        rows = json.loads(res.stdout)
        slugs = [r["slug"] for r in rows]
        self.assertEqual(slugs, [
            "a-produce-shared-value", "b-consume-doubled",
            "c-consume-squared", "d-join-and-sum",
        ])

    def test_template_transitive_deps(self):
        q = ("MATCH (n {slug:'d-join-and-sum'})-[:DEPENDS_ON*]->(d) "
             "RETURN DISTINCT d.slug AS slug ORDER BY slug")
        res = subprocess.run(
            [CYPHERLITE_BIN, str(TEMPLATE), "-json", q],
            capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        rows = json.loads(res.stdout)
        self.assertEqual([r["slug"] for r in rows], [
            "a-produce-shared-value", "b-consume-doubled", "c-consume-squared",
        ])

    def test_template_acceptance_query(self):
        q = ("MATCH (f:Feature)-[:HAS_ACCEPTANCE]->(a:Acceptance) "
             "RETURN a.id AS id ORDER BY id")
        res = subprocess.run(
            [CYPHERLITE_BIN, str(TEMPLATE), "-json", q],
            capture_output=True, text=True,
        )
        self.assertEqual(res.returncode, 0, res.stderr)
        rows = json.loads(res.stdout)
        self.assertEqual([r["id"] for r in rows], ["a-1", "a-2"])


if __name__ == "__main__":
    unittest.main()
