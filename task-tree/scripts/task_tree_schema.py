"""Schema recognition and validation for persisted task-tree data."""

from typing import Dict, Optional


CURRENT_SCHEMA_VERSION = 2
VALID_STATUSES = (
    "not_started",
    "in_progress",
    "completed",
    "aborted",
    "impossible",
)
ACTIONABLE_STATUSES = frozenset({"not_started", "in_progress"})


class TaskTreeSchemaError(ValueError):
    """Raised when persisted task-tree data violates the current contract."""


def _require_int(value: object, label: str, *, positive: bool = False) -> int:
    if not isinstance(value, int) or isinstance(value, bool):
        raise TaskTreeSchemaError(f"{label} must be an integer")
    if positive and value <= 0:
        raise TaskTreeSchemaError(f"{label} must be a positive integer")
    return value


def _require_current_version(data: Dict) -> None:
    if "schema_version" not in data:
        raise TaskTreeSchemaError(
            "task tree is missing required schema_version 2"
        )
    version = data["schema_version"]
    if version != CURRENT_SCHEMA_VERSION:
        raise TaskTreeSchemaError(
            f"unsupported schema_version {version!r}; expected 2"
        )


def initialize_missing_schema_version(data: object) -> bool:
    """Initialize version 2 only for an unambiguous populated current tree.

    The relationship representation supplies enough evidence for this narrow
    metadata repair: roots have one top-level owner, every populated node has a
    parent-owned ``children`` list, and no unsupported child-owned fields remain.
    Empty or mixed input is deliberately left untouched because its format cannot
    be inferred from actual relationships.
    """

    if not isinstance(data, dict) or "schema_version" in data:
        return False
    nodes = data.get("nodes")
    root_ids = data.get("root_ids")
    if not isinstance(nodes, list) or not nodes or not isinstance(root_ids, list):
        return False
    if any(not isinstance(node, dict) for node in nodes):
        return False
    if not all("children" in node for node in nodes):
        return False
    if any("parent_id" in node or "sibling_order" in node for node in nodes):
        return False
    data["schema_version"] = CURRENT_SCHEMA_VERSION
    return True


def _recognize_current_format(data: object) -> Dict:
    """Return current-format input or raise a precise format diagnostic.

    Relationship fields are inspected without adding defaults so an unsupported
    structure cannot be rewritten by an ordinary runtime command.
    """

    if not isinstance(data, dict):
        raise TaskTreeSchemaError("task tree must be a JSON object")

    nodes = data.get("nodes")
    if not isinstance(nodes, list):
        raise TaskTreeSchemaError("nodes must be a list")
    if any(not isinstance(node, dict) for node in nodes):
        raise TaskTreeSchemaError("every node must be an object")

    _require_current_version(data)

    has_root_ids = "root_ids" in data
    if not has_root_ids:
        raise TaskTreeSchemaError("task tree is missing required root_ids")
    if not isinstance(data["root_ids"], list):
        raise TaskTreeSchemaError("root_ids must be a list")

    if not nodes:
        return data

    current_nodes = ["children" in node for node in nodes]
    unsupported_order_nodes = ["sibling_order" in node for node in nodes]
    unsupported_parent_nodes = ["parent_id" in node for node in nodes]
    has_unsupported_field = any(unsupported_order_nodes) or any(unsupported_parent_nodes)

    if all(current_nodes) and not has_unsupported_field:
        return data

    # Partial, mixed, and child-owned relationship fields have no accepted owner
    # of order. Refusing them is safer than guessing from node IDs or whichever
    # field happens to be present first.
    raise TaskTreeSchemaError(
        "unsupported or incomplete relationship structure: every node requires "
        "children owned by the parent; parent_id and sibling_order are not accepted"
    )


def _index_nodes(nodes: list) -> Dict[int, Dict]:
    indexed: Dict[int, Dict] = {}
    for node in nodes:
        node_id = _require_int(node.get("id"), "node id", positive=True)
        if node_id in indexed:
            raise TaskTreeSchemaError(f"duplicate node id: {node_id}")
        indexed[node_id] = node
    return indexed


def _validate_node_payload(node_id: int, node: Dict) -> None:
    required_types = {
        "summary": str,
        "body": str,
        "closeout_reviewed": bool,
        "events": dict,
    }
    for field, expected_type in required_types.items():
        if field not in node:
            raise TaskTreeSchemaError(f"node {node_id} is missing required field {field}")
        if not isinstance(node[field], expected_type):
            raise TaskTreeSchemaError(
                f"{field} for node {node_id} must be a {expected_type.__name__}"
            )

    if "files_dir" not in node:
        raise TaskTreeSchemaError(f"node {node_id} is missing required field files_dir")
    if node["files_dir"] is not None and not isinstance(node["files_dir"], str):
        raise TaskTreeSchemaError(f"files_dir for node {node_id} must be a string or null")

    status = node.get("status")
    if status not in VALID_STATUSES:
        raise TaskTreeSchemaError(f"invalid status for node {node_id}: {status!r}")

    if "return_to_id" in node:
        _require_int(
            node["return_to_id"],
            f"return_to_id for node {node_id}",
            positive=True,
        )


def validate_tree(data: object, *, validate_active: bool = True) -> None:
    """Validate the current task-tree schema and its graph invariants.

    ``validate_active=False`` exists only for the runtime's ``clear-active``
    recovery command. Graph and payload validation always remain enabled so that
    recovery cannot turn a structurally broken tree into writable data.
    """

    current = _recognize_current_format(data)
    nodes = current["nodes"]
    indexed = _index_nodes(nodes)

    next_id = _require_int(current.get("next_id"), "next_id", positive=True)
    if indexed and next_id <= max(indexed):
        raise TaskTreeSchemaError("next_id must be greater than every existing node id")

    owner: Dict[int, Optional[int]] = {}

    def register(child_id: object, parent_id: Optional[int], label: str) -> int:
        resolved = _require_int(child_id, label, positive=True)
        if resolved not in indexed:
            raise TaskTreeSchemaError(f"{label} references missing node {resolved}")
        if resolved in owner:
            raise TaskTreeSchemaError(f"node {resolved} has multiple owning positions")
        owner[resolved] = parent_id
        return resolved

    ordered_roots = [register(node_id, None, "root_ids") for node_id in current["root_ids"]]
    children_by_parent: Dict[int, list[int]] = {}
    for node_id, node in indexed.items():
        _validate_node_payload(node_id, node)
        children = node["children"]
        if not isinstance(children, list):
            raise TaskTreeSchemaError(f"children for node {node_id} must be a list")
        children_by_parent[node_id] = [
            register(child_id, node_id, f"children for node {node_id}")
            for child_id in children
        ]

    missing_owners = sorted(set(indexed) - set(owner))
    if missing_owners:
        rendered = ", ".join(str(node_id) for node_id in missing_owners)
        raise TaskTreeSchemaError(f"nodes have no owning position: {rendered}")

    visited: set[int] = set()
    visiting: set[int] = set()

    def visit(node_id: int) -> None:
        if node_id in visiting:
            raise TaskTreeSchemaError(f"cycle detected at node {node_id}")
        if node_id in visited:
            return
        visiting.add(node_id)
        for child_id in children_by_parent[node_id]:
            visit(child_id)
        visiting.remove(node_id)
        visited.add(node_id)

    # A disconnected cycle can still give every node one owner, so inspect every
    # component for cycles before separately enforcing reachability from roots.
    for node_id in indexed:
        visit(node_id)

    reachable: set[int] = set()

    def mark_reachable(node_id: int) -> None:
        if node_id in reachable:
            return
        reachable.add(node_id)
        for child_id in children_by_parent[node_id]:
            mark_reachable(child_id)

    for root_id in ordered_roots:
        mark_reachable(root_id)
    if reachable != set(indexed):
        unreachable = ", ".join(str(node_id) for node_id in sorted(set(indexed) - reachable))
        raise TaskTreeSchemaError(f"nodes are unreachable from root_ids: {unreachable}")

    def descendants_of(node_id: int) -> set[int]:
        descendants: set[int] = set()
        pending = list(children_by_parent[node_id])
        while pending:
            descendant_id = pending.pop()
            if descendant_id in descendants:
                continue
            descendants.add(descendant_id)
            pending.extend(children_by_parent[descendant_id])
        return descendants

    for node_id, node in indexed.items():
        return_to_id = node.get("return_to_id")
        if return_to_id is None:
            continue
        if return_to_id not in indexed:
            raise TaskTreeSchemaError(
                f"return_to_id for node {node_id} references missing node {return_to_id}"
            )
        # A continuation may point to an ancestor or an unrelated branch, but
        # never back into the subtree that must already be terminal before it
        # fires. Such an edge could only refocus finished descendant work.
        if return_to_id == node_id:
            raise TaskTreeSchemaError(f"node {node_id} cannot return to itself")
        if return_to_id in descendants_of(node_id):
            raise TaskTreeSchemaError(
                f"node {node_id} cannot return to its own descendant {return_to_id}"
            )

    if not validate_active:
        return
    active_id = current.get("active_id")
    if active_id is None:
        return
    active_id = _require_int(active_id, "active_id", positive=True)
    if active_id not in indexed:
        raise TaskTreeSchemaError(f"active_id references missing node {active_id}")
