import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from graph import (
    GraphError,
    compute_frontier,
    compute_report,
    topo_waves,
    validate,
)


def node(id_, deps=None, **overrides):
    base = {
        "id": id_,
        "title": id_,
        "type": "code",
        "dependencies": deps or [],
        "contract": {"input": {}, "output": {}},
        "satisfies": [],
        "acceptance": [f"{id_} produces its declared output"],
        "verify": None,
        "failure_policy": "retry",
        "model_tier": "cheap",
    }
    base.update(overrides)
    return base


def graph_of(*nodes):
    return {
        "feature": "test",
        "destination": "test",
        "context": "test",
        "out_of_scope": [],
        "acceptance": [],
        "nodes": list(nodes),
    }


def write_checkpoint(state_dir, node_id, status, **fields):
    Path(state_dir).mkdir(parents=True, exist_ok=True)
    payload = {"status": status, **fields}
    (Path(state_dir) / f"{node_id}.json").write_text(json.dumps(payload))


class ChainTests(unittest.TestCase):
    def test_waves_are_one_node_each(self):
        g = graph_of(node("a"), node("b", ["a"]), node("c", ["b"]))
        validate(g)
        self.assertEqual(topo_waves(g), [["a"], ["b"], ["c"]])

    def test_frontier_is_only_the_root(self):
        g = graph_of(node("a"), node("b", ["a"]), node("c", ["b"]))
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(compute_frontier(g, d), ["a"])


class DiamondTests(unittest.TestCase):
    def setUp(self):
        self.g = graph_of(
            node("a"),
            node("b", ["a"]),
            node("c", ["a"]),
            node("d", ["b", "c"]),
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
        g = graph_of(node("a", ["b"]), node("b", ["a"]))
        with self.assertRaises(GraphError):
            validate(g)

    def test_missing_dependency_is_rejected(self):
        g = graph_of(node("a", ["ghost"]))
        with self.assertRaises(GraphError):
            validate(g)

    def test_empty_acceptance_is_rejected(self):
        g = graph_of(node("a", acceptance=[]))
        with self.assertRaises(GraphError):
            validate(g)

    def test_blank_acceptance_bullet_is_rejected(self):
        g = graph_of(node("a", acceptance=["   "]))
        with self.assertRaises(GraphError):
            validate(g)


if __name__ == "__main__":
    unittest.main()
