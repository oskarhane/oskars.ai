#!/usr/bin/env python3
"""gbuild graph utility: validate, topo-order, and query a graph.json feature graph.

graph.json is a CypherLite GraphData file. It lives at
`.gbuild/<feature>/db/graph.json` so CypherLite can open the `db/` folder as a
JSON-store database (CypherLite opens a *directory*, not a bare `.json` file)
and query it with Cypher. This module is the query layer (topo waves, frontier,
status report) over that file. Format validation lives in validate_format.py
(the single source of truth for the contract); this module imports and re-exports
its validate() and enum sets.

Stdlib only, no pip install required. Schema: ../reference/graph-format.md

CLI:
  python3 graph.py <feature>/db/graph.json --waves     print the topological wave decomposition
  python3 graph.py <feature>/db/graph.json --frontier  print node ids ready to run right now
  python3 graph.py <feature>/db/graph.json --status    print the full status report (default)

Checkpoints are read from <feature>/nodes/<slug>.json by default, or --state-dir.
"""
import argparse
import json
import sys
from pathlib import Path

# Format contract + enum sets live in validate_format (single definition site).
from validate_format import (
    GraphError,
    SATISFIED_STATUSES,
    VALID_FAILURE_POLICIES,
    VALID_MODEL_TIERS,
    VALID_NODE_TYPES,
    VALID_TYPE_LABELS,
    validate,
)


# --- helpers over the GraphData shape ---------------------------------------

def _labels(node):
    return set(node.get("labels", []))


def _props(node):
    return node.get("properties", {}) if isinstance(node.get("properties"), dict) else {}


def gbuild_nodes(graph):
    """GbuildNode-labelled nodes, as a list."""
    return [n for n in graph.get("nodes", []) if "GbuildNode" in _labels(n)]


def node_by_id(graph, nid):
    for n in graph.get("nodes", []):
        if n.get("id") == nid:
            return n
    return None


def node_by_slug(graph, slug):
    for n in gbuild_nodes(graph):
        if _props(n).get("slug") == slug:
            return n
    return None


def slug_of(graph, nid):
    n = node_by_id(graph, nid)
    return _props(n).get("slug") if n else None


def id_of_slug(graph, slug):
    n = node_by_slug(graph, slug)
    return n.get("id") if n else None


def deps(graph, node_id):
    """node_ids this node depends on (DEPENDS_ON end_nodes)."""
    return [
        r["end_node"]
        for r in graph.get("relationships", [])
        if r.get("type") == "DEPENDS_ON" and r.get("start_node") == node_id
    ]


def satisfies(graph, node_id):
    """acceptance node_ids this node covers (SATISFIES end_nodes)."""
    return [
        r["end_node"]
        for r in graph.get("relationships", [])
        if r.get("type") == "SATISFIES" and r.get("start_node") == node_id
    ]


def feature(graph):
    """the single Feature node, or None."""
    for n in graph.get("nodes", []):
        if "Feature" in _labels(n):
            return n
    return None


def acceptance_nodes(graph):
    return [n for n in graph.get("nodes", []) if "Acceptance" in _labels(n)]


# --- core query layer --------------------------------------------------------

def load_graph(path):
    with open(path) as f:
        return json.load(f)


def topo_waves(graph):
    """Layer GbuildNodes into parallel-safe waves by slug.

    wave N contains every node whose DEPENDS_ON targets all resolved in <N.
    Returns a list of lists of slugs.
    """
    gn = gbuild_nodes(graph)
    # map node id -> slug, and slug -> dep slugs
    id_to_slug = {n["id"]: _props(n).get("slug") for n in gn}
    remaining = {id_to_slug[n["id"]]: n for n in gn}
    resolved = set()
    waves = []

    while remaining:
        wave = []
        for slug, node in remaining.items():
            dep_ids = deps(graph, node["id"])
            dep_slugs = {id_to_slug.get(d) for d in dep_ids}
            if dep_slugs.issubset(resolved):
                wave.append(slug)
        if not wave:
            raise GraphError(f"cycle detected among: {', '.join(sorted(remaining))}")
        wave.sort()
        waves.append(wave)
        for slug in wave:
            resolved.add(slug)
            del remaining[slug]

    return waves


def read_checkpoint(state_dir, slug):
    path = Path(state_dir) / f"{slug}.json"
    if not path.exists():
        return {"status": "pending"}
    with open(path) as f:
        return json.load(f)


def node_statuses(graph, state_dir):
    """slug -> status, for every GbuildNode."""
    return {
        _props(n).get("slug"): read_checkpoint(state_dir, _props(n).get("slug")).get("status", "pending")
        for n in gbuild_nodes(graph)
    }


def compute_report(graph, state_dir):
    statuses = node_statuses(graph, state_dir)
    id_slug = {n["id"]: _props(n).get("slug") for n in gbuild_nodes(graph)}
    frontier, blocked, in_flight, completed, cancelled, failed = [], [], [], [], [], []

    for node in gbuild_nodes(graph):
        slug = _props(node).get("slug")
        status = statuses.get(slug, "pending")
        dep_ids = deps(graph, node["id"])
        dep_statuses = [statuses.get(id_slug.get(d), "pending") for d in dep_ids]
        if status == "completed":
            completed.append(slug)
        elif status == "cancelled":
            cancelled.append(slug)
        elif status == "in_progress":
            in_flight.append(slug)
        elif status == "failed":
            failed.append(slug)
        elif all(ds in SATISFIED_STATUSES for ds in dep_statuses):
            frontier.append(slug)
        else:
            blocked.append(slug)

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
    """Checkpoints live in the sibling `nodes/` dir, next to the `db/` graph folder.

    The plan is `<feature>/db/graph.json` and state is `<feature>/nodes/`; the
    two are siblings so CypherLite's `nodes/` Parquet-shard detection never sees
    the checkpoint dir inside the folder it opens.
    """
    return Path(graph_path).resolve().parent.parent / "nodes"


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("graph_path")
    parser.add_argument("--state-dir", default=None, help="checkpoint dir, default: <feature>/nodes")
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
