#!/usr/bin/env python3
"""gbuild graph format validator — the authoritative contract for graph.json.

graph.json is a CypherLite GraphData file (openable with `cypherlite <path>`).
This module checks it is both CypherLite-loadable and gbuild-correct: the
GraphData envelope, node shapes (Feature / Acceptance / GbuildNode), the three
relationship types (DEPENDS_ON / HAS_ACCEPTANCE / SATISFIES), id/counter
invariants, acyclicity, and coverage. Stdlib only — same no-install rule as
graph.py.

Single source of truth for the format: graph.py imports VALID_* and
SATISFIED_STATUSES from here, and its validate() calls validate() below.

CLI:
  python3 validate_format.py <graph.json>
    exit 0 + "valid: <feature>"          on success
    exit 1 + "invalid: <errors joined>"  on failure
"""
import argparse
import json
import re
import sys

# --- enum sets (single definition site; graph.py imports these) -------------

VALID_NODE_TYPES = {"research", "decision", "code", "test", "verify", "chore"}
VALID_FAILURE_POLICIES = {"retry", "fallback", "skip", "repair", "escalate", "stop"}
VALID_MODEL_TIERS = {"cheap", "strong"}
SATISFIED_STATUSES = {"completed", "cancelled"}

# PascalCase type label <-> lowercase type property. Order matches VALID_NODE_TYPES.
TYPE_TO_LABEL = {
    "research": "Research",
    "decision": "Decision",
    "code": "Code",
    "test": "Test",
    "verify": "Verify",
    "chore": "Chore",
}
VALID_TYPE_LABELS = set(TYPE_TO_LABEL.values())

VALID_REL_TYPES = {"DEPENDS_ON", "HAS_ACCEPTANCE", "SATISFIES"}

SLUG_RE = re.compile(r"^[a-z0-9]+(-[a-z0-9]+)*$")
ACCEPTANCE_ID_RE = re.compile(r"^a-\d+$")


class GraphError(Exception):
    pass


def _is_int(v):
    return isinstance(v, int) and not isinstance(v, bool)


def _is_str_list(v):
    return isinstance(v, list) and all(isinstance(x, str) for x in v)


def validate(graph):
    """Raise GraphError with every problem found, joined, rather than the first.

    Collects all structural, shape, relationship, counter, acyclicity, and
    coverage errors into one message so a single validate pass tells the author
    everything to fix.
    """
    errors = []

    if not isinstance(graph, dict):
        raise GraphError("graph root is not an object")

    # --- GraphData envelope ---------------------------------------------------
    for key in ("nodes", "relationships", "indexes", "constraints"):
        if not isinstance(graph.get(key), list):
            errors.append(f"top-level {key!r} must be a list")
    for key in ("next_node_id", "next_rel_id"):
        if not _is_int(graph.get(key)):
            errors.append(f"top-level {key!r} must be an integer")

    nodes = graph.get("nodes") if isinstance(graph.get("nodes"), list) else []
    rels = graph.get("relationships") if isinstance(graph.get("relationships"), list) else []

    if not nodes:
        errors.append("graph has no nodes")

    # --- node shape + id uniqueness ------------------------------------------
    node_ids = set()
    for n in nodes:
        if not isinstance(n, dict):
            errors.append("a node is not an object")
            continue
        nid = n.get("id")
        if not _is_int(nid):
            errors.append("a node has a missing or non-integer id")
            continue
        if nid in node_ids:
            errors.append(f"duplicate node id: {nid}")
        node_ids.add(nid)
        if not isinstance(n.get("labels"), list) or not all(isinstance(l, str) for l in n.get("labels", [])):
            errors.append(f"node {nid}: labels must be a list of strings")
        if not isinstance(n.get("properties"), dict):
            errors.append(f"node {nid}: properties must be an object")

    by_id = {n["id"]: n for n in nodes if isinstance(n, dict) and _is_int(n.get("id"))}
    labels_by_id = {nid: set(n.get("labels", [])) for nid, n in by_id.items()}
    props_by_id = {nid: n.get("properties", {}) for nid, n in by_id.items() if isinstance(n.get("properties"), dict)}

    # --- Feature node --------------------------------------------------------
    feature_nodes = [nid for nid, ls in labels_by_id.items() if "Feature" in ls]
    if len(feature_nodes) != 1:
        errors.append(f"expected exactly one Feature node, found {len(feature_nodes)}")
    feature_id = feature_nodes[0] if feature_nodes else None
    if feature_id is not None:
        p = props_by_id.get(feature_id, {})
        for key in ("feature", "destination", "context"):
            if not isinstance(p.get(key), str):
                errors.append(f"Feature node: {key!r} must be a string")
        if not _is_str_list(p.get("out_of_scope")):
            errors.append("Feature node: 'out_of_scope' must be a list of strings")
        if "acceptance" in p:
            errors.append("Feature node must not carry an 'acceptance' property (use Acceptance nodes)")

    # --- Acceptance nodes ----------------------------------------------------
    acceptance_nodes = {}  # id property -> node id
    for nid, ls in labels_by_id.items():
        if "Acceptance" not in ls:
            continue
        p = props_by_id.get(nid, {})
        aid = p.get("id")
        if not isinstance(aid, str) or not ACCEPTANCE_ID_RE.match(aid):
            errors.append(f"node {nid} (Acceptance): 'id' must be a string like 'a-1'")
        elif aid in acceptance_nodes:
            errors.append(f"duplicate Acceptance id: {aid}")
        else:
            acceptance_nodes[aid] = nid
        if not isinstance(p.get("text"), str) or not p.get("text", "").strip():
            errors.append(f"node {nid} (Acceptance): 'text' must be a non-blank string")

    # --- GbuildNode shape ----------------------------------------------------
    gbuild_nodes = {}  # slug -> node id
    for nid, ls in labels_by_id.items():
        if "GbuildNode" not in ls:
            continue
        p = props_by_id.get(nid, {})
        slug = p.get("slug")
        if not isinstance(slug, str) or not SLUG_RE.match(slug):
            errors.append(f"node {nid} (GbuildNode): 'slug' must be a kebab-case string")
        elif slug in gbuild_nodes:
            errors.append(f"duplicate GbuildNode slug: {slug}")
        else:
            gbuild_nodes[slug] = nid
        if not isinstance(p.get("title"), str):
            errors.append(f"node {nid} (GbuildNode): 'title' must be a string")
        ntype = p.get("type")
        if ntype not in VALID_NODE_TYPES:
            errors.append(f"node {nid} (GbuildNode): invalid type {ntype!r}")
        contract = p.get("contract")
        if not isinstance(contract, dict) or not isinstance(contract.get("input"), dict) or not isinstance(contract.get("output"), dict):
            errors.append(f"node {nid} (GbuildNode): 'contract' must be {{input:{{}},output:{{}}}}")
        acc = p.get("acceptance")
        if not isinstance(acc, list) or len(acc) == 0:
            errors.append(f"node {nid} (GbuildNode): 'acceptance' must be a non-empty list")
        elif any(not str(c).strip() for c in acc):
            errors.append(f"node {nid} (GbuildNode): 'acceptance' must not contain blank entries")
        if p.get("verify") is not None and not isinstance(p.get("verify"), str):
            errors.append(f"node {nid} (GbuildNode): 'verify' must be a string or null")
        if p.get("failure_policy") not in VALID_FAILURE_POLICIES:
            errors.append(f"node {nid} (GbuildNode): invalid failure_policy {p.get('failure_policy')!r}")
        if p.get("model_tier") not in VALID_MODEL_TIERS:
            errors.append(f"node {nid} (GbuildNode): invalid model_tier {p.get('model_tier')!r}")
        if "satisfies" in p:
            errors.append(f"node {nid} (GbuildNode): must not carry a 'satisfies' property (use SATISFIES edges)")
        # type-label consistency
        if ntype in TYPE_TO_LABEL:
            expected_label = TYPE_TO_LABEL[ntype]
            if expected_label not in ls:
                errors.append(f"node {nid} (GbuildNode): type {ntype!r} requires label {expected_label!r}")
            extra_type_labels = (ls & VALID_TYPE_LABELS) - {expected_label}
            if extra_type_labels:
                errors.append(f"node {nid} (GbuildNode): type labels {extra_type_labels} do not match type {ntype!r}")

    gbuild_ids = {nid for nid, ls in labels_by_id.items() if "GbuildNode" in ls}

    # --- relationship shape --------------------------------------------------
    rel_ids = set()
    depends_edges = []  # (start, end) for acyclicity
    has_acc_ends = set()  # acceptance node ids targeted by HAS_ACCEPTANCE
    satisfies_ends = set()  # acceptance node ids targeted by SATISFIES
    depends_targets = set()  # gbuild node ids that are depended upon (chore coverage)
    for r in rels:
        if not isinstance(r, dict):
            errors.append("a relationship is not an object")
            continue
        rid = r.get("id")
        if not _is_int(rid):
            errors.append("a relationship has a missing or non-integer id")
            continue
        if rid in rel_ids:
            errors.append(f"duplicate relationship id: {rid}")
        rel_ids.add(rid)
        rtype = r.get("type")
        if rtype not in VALID_REL_TYPES:
            errors.append(f"relationship {rid}: invalid type {rtype!r}")
            continue
        s, e = r.get("start_node"), r.get("end_node")
        if s not in by_id:
            errors.append(f"relationship {rid}: start_node {s!r} does not exist")
        if e not in by_id:
            errors.append(f"relationship {rid}: end_node {e!r} does not exist")
            continue
        if not isinstance(r.get("properties"), dict):
            errors.append(f"relationship {rid}: properties must be an object")
        # type-specific endpoint constraints
        if rtype == "DEPENDS_ON":
            if s not in gbuild_ids:
                errors.append(f"relationship {rid} (DEPENDS_ON): start_node {s} must be a GbuildNode")
            if e not in gbuild_ids:
                errors.append(f"relationship {rid} (DEPENDS_ON): end_node {e} must be a GbuildNode")
            else:
                depends_edges.append((s, e))
                depends_targets.add(e)
        elif rtype == "HAS_ACCEPTANCE":
            if feature_id is not None and s != feature_id:
                errors.append(f"relationship {rid} (HAS_ACCEPTANCE): start_node {s} must be the Feature node")
            if "Acceptance" not in labels_by_id.get(e, set()):
                errors.append(f"relationship {rid} (HAS_ACCEPTANCE): end_node {e} must be an Acceptance node")
            else:
                has_acc_ends.add(e)
        elif rtype == "SATISFIES":
            if s not in gbuild_ids:
                errors.append(f"relationship {rid} (SATISFIES): start_node {s} must be a GbuildNode")
            if "Acceptance" not in labels_by_id.get(e, set()):
                errors.append(f"relationship {rid} (SATISFIES): end_node {e} must be an Acceptance node")
            else:
                satisfies_ends.add(e)

    # --- counter invariant ---------------------------------------------------
    if nodes and _is_int(graph.get("next_node_id")):
        expected_n = max(n["id"] for n in nodes if isinstance(n, dict) and _is_int(n.get("id"))) + 1
        if graph["next_node_id"] != expected_n:
            errors.append(f"next_node_id must be {expected_n} (max node id + 1), got {graph['next_node_id']}")
    if rels and _is_int(graph.get("next_rel_id")):
        expected_r = max(r["id"] for r in rels if isinstance(r, dict) and _is_int(r.get("id"))) + 1
        if graph["next_rel_id"] != expected_r:
            errors.append(f"next_rel_id must be {expected_r} (max rel id + 1), got {graph['next_rel_id']}")

    # --- acyclicity ---------------------------------------------------------
    if depends_edges and not any("DEPENDS_ON" in e for e in errors):
        cycle = _detect_cycle(gbuild_ids, depends_edges)
        if cycle:
            errors.append(f"cycle detected among: {', '.join(sorted(str(c) for c in cycle))}")

    # --- coverage -----------------------------------------------------------
    for aid, anid in acceptance_nodes.items():
        if anid not in satisfies_ends:
            errors.append(f"Acceptance {aid!r} (node {anid}) is not covered by any SATISFIES edge")
        if anid not in has_acc_ends:
            errors.append(f"Acceptance {aid!r} (node {anid}) is not linked by any HAS_ACCEPTANCE edge")
    # every chore must be depended on
    for nid in gbuild_ids:
        p = props_by_id.get(nid, {})
        if p.get("type") == "chore" and nid not in depends_targets:
            errors.append(f"chore node {nid} (slug {p.get('slug')!r}) is not depended on by any node")

    if errors:
        raise GraphError("; ".join(errors))


def _detect_cycle(node_ids, edges):
    """Return a set of node ids involved in a cycle, or empty set if acyclic."""
    adj = {nid: [] for nid in node_ids}
    for s, e in edges:
        adj.setdefault(s, []).append(e)
    WHITE, GRAY, BLACK = 0, 1, 2
    color = {nid: WHITE for nid in node_ids}
    in_cycle = set()

    def dfs(u, stack):
        color[u] = GRAY
        stack.append(u)
        for v in adj.get(u, []):
            if v not in color:
                continue
            if color[v] == GRAY:
                # cycle: from v back to u along the stack
                idx = stack.index(v)
                in_cycle.update(stack[idx:])
            elif color[v] == WHITE:
                dfs(v, stack)
        stack.pop()
        color[u] = BLACK

    for nid in node_ids:
        if color.get(nid) == WHITE:
            dfs(nid, [])
    return in_cycle


def _cypherlite_cross_check(graph_path):
    """If cypherlite is on PATH, confirm CypherLite itself loads the file and
    can run a trivial query. Catches serde/encoding issues the stdlib walk can't
    (e.g. a top-level shape CypherLite's GraphData loader rejects). Returns an
    error string on failure, None on success or when cypherlite is absent.

    Absence is silent — cypherlite is an optional consumer, not a dependency.
    """
    import shutil
    import subprocess
    bin_path = shutil.which("cypherlite")
    if bin_path is None:
        return None  # not installed — skip, not a failure
    res = subprocess.run(
        [bin_path, str(graph_path), "-json",
         "MATCH (n) RETURN count(n) AS c"],
        capture_output=True, text=True, timeout=30,
    )
    # cypherlite returns exit 0 even on some load failures (it prints the error
    # to stderr), so check both the exit code AND the output for failure markers.
    out = (res.stderr + res.stdout).strip()
    if res.returncode != 0:
        return f"cypherlite refused to load the file: {out or 'unknown error'}"
    if "Failed to open database" in out or "failed to parse JSON" in out:
        return f"cypherlite refused to load the file: {out}"
    return None


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("graph_path")
    parser.add_argument("--no-cypherlite", action="store_true",
                        help="skip the optional cypherlite load cross-check even if the binary is present")
    args = parser.parse_args(argv)

    try:
        with open(args.graph_path) as f:
            graph = json.load(f)
    except (OSError, json.JSONDecodeError) as e:
        print(f"invalid: cannot read {args.graph_path}: {e}", file=sys.stderr)
        return 1

    try:
        validate(graph)
    except GraphError as e:
        print(f"invalid: {e}", file=sys.stderr)
        return 1

    # Optional cross-check: confirm CypherLite itself loads the file (catches
    # serde/encoding issues the stdlib checks above can't). Skipped silently if
    # cypherlite isn't installed — it's an optional consumer, not a dependency.
    if not args.no_cypherlite:
        cl_err = _cypherlite_cross_check(args.graph_path)
        if cl_err is not None:
            print(f"invalid: {cl_err}", file=sys.stderr)
            return 1

    # best-effort feature slug for the success line
    feature = "?"
    for n in graph.get("nodes", []):
        if isinstance(n, dict) and "Feature" in n.get("labels", []):
            p = n.get("properties", {})
            if isinstance(p.get("feature"), str):
                feature = p["feature"]
            break
    print(f"valid: {feature}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
