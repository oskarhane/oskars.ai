#!/usr/bin/env python3
"""gbuild graph utility: validate, topo-order, and query a graph.json feature graph.

Stdlib only, no pip install required. Schema: ../reference/graph-format.md

CLI:
  python3 graph.py <graph.json> --waves     print the topological wave decomposition
  python3 graph.py <graph.json> --frontier  print node ids ready to run right now
  python3 graph.py <graph.json> --status    print the full status report

Checkpoints are read from <graph dir>/nodes/<id>.json by default, or --state-dir.
"""
import argparse
import json
import sys
from pathlib import Path

VALID_NODE_TYPES = {"research", "decision", "code", "test", "verify", "chore"}
VALID_FAILURE_POLICIES = {"retry", "fallback", "skip", "repair", "escalate", "stop"}
VALID_MODEL_TIERS = {"cheap", "strong"}
SATISFIED_STATUSES = {"completed", "cancelled"}


class GraphError(Exception):
    pass


def load_graph(path):
    with open(path) as f:
        return json.load(f)


def validate(graph):
    """Raise GraphError with every problem found, joined, rather than the first one."""
    errors = []
    nodes = graph.get("nodes", [])
    if not nodes:
        errors.append("graph has no nodes")

    seen = set()
    for node in nodes:
        node_id = node.get("id")
        if not node_id:
            errors.append("node missing id")
            continue
        if node_id in seen:
            errors.append(f"duplicate node id: {node_id}")
        seen.add(node_id)

    by_id = {n["id"]: n for n in nodes if n.get("id")}

    for node in nodes:
        node_id = node.get("id", "<unknown>")

        if node.get("type") not in VALID_NODE_TYPES:
            errors.append(f"{node_id}: invalid type {node.get('type')!r}")

        for dep in node.get("dependencies", []):
            if dep not in by_id:
                errors.append(f"{node_id}: dependency {dep!r} does not exist")

        acceptance = node.get("acceptance") or []
        if not isinstance(acceptance, list) or len(acceptance) == 0:
            errors.append(f"{node_id}: acceptance criteria must be a non-empty list")
        elif any(not str(c).strip() for c in acceptance):
            errors.append(f"{node_id}: acceptance criteria must not be blank")

        if node.get("failure_policy") not in VALID_FAILURE_POLICIES:
            errors.append(f"{node_id}: invalid failure_policy {node.get('failure_policy')!r}")

        if node.get("model_tier") not in VALID_MODEL_TIERS:
            errors.append(f"{node_id}: invalid model_tier {node.get('model_tier')!r}")

    if not errors:
        try:
            topo_waves(graph)
        except GraphError as e:
            errors.append(str(e))

    if errors:
        raise GraphError("; ".join(errors))


def topo_waves(graph):
    """Layer nodes into parallel-safe waves: wave N contains every node whose deps all resolved in <N."""
    nodes = graph.get("nodes", [])
    remaining = {n["id"]: n for n in nodes}
    resolved = set()
    waves = []

    while remaining:
        wave = [
            node_id
            for node_id, node in remaining.items()
            if all(dep in resolved for dep in node.get("dependencies", []))
        ]
        if not wave:
            raise GraphError(f"cycle detected among: {', '.join(sorted(remaining))}")
        wave.sort()
        waves.append(wave)
        for node_id in wave:
            resolved.add(node_id)
            del remaining[node_id]

    return waves


def read_checkpoint(state_dir, node_id):
    path = Path(state_dir) / f"{node_id}.json"
    if not path.exists():
        return {"status": "pending"}
    with open(path) as f:
        return json.load(f)


def node_statuses(graph, state_dir):
    return {
        node["id"]: read_checkpoint(state_dir, node["id"]).get("status", "pending")
        for node in graph.get("nodes", [])
    }


def compute_report(graph, state_dir):
    statuses = node_statuses(graph, state_dir)
    frontier, blocked, in_flight, completed, cancelled, failed = [], [], [], [], [], []

    for node in graph.get("nodes", []):
        node_id = node["id"]
        status = statuses[node_id]
        if status == "completed":
            completed.append(node_id)
        elif status == "cancelled":
            cancelled.append(node_id)
        elif status == "in_progress":
            in_flight.append(node_id)
        elif status == "failed":
            failed.append(node_id)
        elif all(statuses[dep] in SATISFIED_STATUSES for dep in node.get("dependencies", [])):
            frontier.append(node_id)
        else:
            blocked.append(node_id)

    return {
        "frontier": sorted(frontier),
        "blocked": sorted(blocked),
        "in_flight": sorted(in_flight),
        "completed": sorted(completed),
        "cancelled": sorted(cancelled),
        "failed": sorted(failed),
        "waves": topo_waves(graph),
    }


def compute_frontier(graph, state_dir):
    return compute_report(graph, state_dir)["frontier"]


def default_state_dir(graph_path):
    return Path(graph_path).resolve().parent / "nodes"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("graph_path")
    parser.add_argument("--state-dir", default=None, help="checkpoint dir, default: <graph dir>/nodes")
    group = parser.add_mutually_exclusive_group()
    group.add_argument("--waves", action="store_true")
    group.add_argument("--frontier", action="store_true")
    group.add_argument("--status", action="store_true")
    args = parser.parse_args(argv)

    graph = load_graph(args.graph_path)
    try:
        validate(graph)
    except GraphError as e:
        print(f"invalid graph: {e}", file=sys.stderr)
        return 1

    state_dir = args.state_dir or default_state_dir(args.graph_path)

    if args.waves:
        print(json.dumps(topo_waves(graph)))
    elif args.frontier:
        print(json.dumps(compute_frontier(graph, state_dir)))
    else:
        print(json.dumps(compute_report(graph, state_dir), indent=2))

    return 0


if __name__ == "__main__":
    sys.exit(main())
