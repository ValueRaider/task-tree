#!/usr/bin/env python3

import argparse
import fcntl
import json
import os
import re
import shlex
import shutil
import sys
import tempfile
import textwrap
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Dict, Iterator, List, Optional

sys.path.insert(0, os.path.dirname(__file__))
from json_format import dumps_v2_json
from task_tree_schema import (
    ACTIONABLE_STATUSES,
    VALID_STATUSES,
    initialize_missing_schema_version,
    validate_tree,
)

STATUS_ICONS = {
    "not_started": "[ ]",
    "in_progress": "[~]",
    "completed": "[x]",
    "aborted": "[-]",
    "impossible": "[!]",
}

MAX_FULL_CHILDREN_JSON_LINES = 200


@dataclass
class TaskTreeStore:
    path: str

    @property
    def lock_path(self) -> str:
        return f"{self.path}.lock"

    def _empty_data(self) -> Dict:
        return {
            "schema_version": 2,
            "next_id": 1,
            "active_id": None,
            "root_ids": [],
            "nodes": [],
        }

    def _read_unlocked(self, validate_active: bool = True) -> tuple[Dict, bool]:
        if not os.path.exists(self.path):
            data = self._empty_data()
            initialized_version = False
        else:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
            initialized_version = initialize_missing_schema_version(data)
        validate_tree(data, validate_active=validate_active)
        return data, initialized_version

    def _write_unlocked(self, data: Dict) -> None:
        # Every write restores the full contract, even when clear-active used a
        # narrowly relaxed read to recover from a bad focus pointer.
        validate_tree(data)
        directory = os.path.dirname(self.path) or "."
        os.makedirs(directory, exist_ok=True)
        with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=directory, delete=False) as tmp:
            tmp.write(dumps_v2_json(data))
            tmp_path = tmp.name
        os.replace(tmp_path, self.path)

    def reset_unlocked(self) -> Dict:
        data = self._empty_data()
        self._write_unlocked(data)
        return data

    def remove_tree_file_unlocked(self) -> bool:
        if not os.path.exists(self.path):
            return False
        os.remove(self.path)
        return True

    @contextmanager
    def locked_data(self, write: bool = False, validate_active: bool = True) -> Iterator[Dict]:
        lock_mode = fcntl.LOCK_EX if write else fcntl.LOCK_SH
        lock_dir = os.path.dirname(self.lock_path) or "."
        os.makedirs(lock_dir, exist_ok=True)
        with open(self.lock_path, "a+", encoding="utf-8") as lock_file:
            fcntl.flock(lock_file.fileno(), lock_mode)
            data, initialized_version = self._read_unlocked(
                validate_active=validate_active
            )
            if initialized_version and not write:
                # Missing-version initialization is a real persisted repair. A
                # read command begins with a shared lock, then re-reads under an
                # exclusive lock so concurrent writers cannot be overwritten by
                # the metadata-only update.
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                data, initialized_version = self._read_unlocked(
                    validate_active=validate_active
                )
                if initialized_version:
                    self._write_unlocked(data)
            try:
                yield data
                if write:
                    self._write_unlocked(data)
            finally:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def store_path_selection(cli_tree_file: Optional[str] = None) -> tuple[str, Optional[str]]:
    """Return the selected path and the deprecated environment variable, if used."""
    if cli_tree_file:
        return cli_tree_file, None

    explicit = os.environ.get("TASK_TREE_FILE")
    if explicit:
        return explicit, "TASK_TREE_FILE"

    agent_name = os.environ.get("TASK_TREE_AGENT", "").strip()
    if agent_name:
        safe_name = slugify_agent_name(agent_name)
        return f"./task_tree/{safe_name}.json", "TASK_TREE_AGENT"

    return "./task_tree/tree.json", None


def default_store(cli_tree_file: Optional[str] = None) -> TaskTreeStore:
    path, _ = store_path_selection(cli_tree_file)
    return TaskTreeStore(path)


def legacy_store_environment_warning(cli_tree_file: Optional[str] = None) -> Optional[str]:
    path, environment_variable = store_path_selection(cli_tree_file)
    if environment_variable is None:
        return None
    return (
        f"warning: {environment_variable} is deprecated; replace it with "
        f"--tree-file {shlex.quote(path)}"
    )


def slugify_agent_name(agent_name: str) -> str:
    lowered = agent_name.strip().lower()
    slug = re.sub(r"[^a-z0-9._-]+", "-", lowered)
    slug = slug.strip(".-")
    return slug or "tree"


def base_dir_for_store(store: TaskTreeStore) -> str:
    return os.path.dirname(store.path) or "."


def shared_dir_for_store(store: TaskTreeStore) -> str:
    return os.path.join(base_dir_for_store(store), "shared")


def task_files_dir_for_store(store: TaskTreeStore, node_id: int) -> str:
    return os.path.join(base_dir_for_store(store), "files", str(node_id))


# Detailed task output is for orientation, not directory traversal. Ten paths
# expose the ordinary task artifacts while keeping an unusually large folder
# from overwhelming the task metadata that the caller requested.
DETAIL_FILE_DISPLAY_LIMIT = 10

# Direct children orient the caller within one task boundary. Three preserve
# the next few concrete branches without turning node details into a recursive
# or effectively full-tree print when a planning parent has many children.
DETAIL_CHILD_DISPLAY_LIMIT = 3


def task_artifact_files(files_dir: str) -> List[str]:
    """Return sorted task-owned file paths relative to the artifact directory."""

    if not os.path.isdir(files_dir):
        return []
    artifacts: List[str] = []
    for root, directory_names, file_names in os.walk(files_dir):
        directory_names.sort()
        for file_name in sorted(file_names):
            path = os.path.join(root, file_name)
            if os.path.isfile(path):
                artifacts.append(os.path.relpath(path, files_dir))
    artifacts.sort()
    return artifacts


def event_log_path_for_node(store: TaskTreeStore, node: Dict) -> str:
    files_dir = node.get("files_dir") or task_files_dir_for_store(store, node["id"])
    return os.path.join(files_dir, "events.jsonl")


def ensure_dir(path: str) -> str:
    os.makedirs(path, exist_ok=True)
    return path


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def remove_dir_if_exists(path: str) -> bool:
    if not path or not os.path.exists(path):
        return False
    shutil.rmtree(path)
    return True


def ensure_node_events(node: Dict) -> Dict:
    events = node.get("events")
    if not isinstance(events, dict):
        events = {}
        node["events"] = events
    return events


def stamp_event(node: Dict, event_name: str, timestamp: Optional[str] = None) -> str:
    ts = timestamp or utc_now()
    events = ensure_node_events(node)
    events[event_name] = ts
    events["last_mutated_at"] = ts
    return ts


def find_node(data: Dict, node_id: int) -> Optional[Dict]:
    for node in data["nodes"]:
        if node["id"] == node_id:
            return node
    return None


def require_node(data: Dict, node_id: int) -> Dict:
    node = find_node(data, node_id)
    if node is None:
        raise ValueError(f"Node {node_id} does not exist")
    return node


def child_nodes(data: Dict, node_id: int) -> List[Dict]:
    parent = require_node(data, node_id)
    return [require_node(data, child_id) for child_id in parent["children"]]


def parent_id_for(data: Dict, node_id: int) -> Optional[int]:
    require_node(data, node_id)
    if node_id in data["root_ids"]:
        return None
    for candidate in data["nodes"]:
        if node_id in candidate["children"]:
            return candidate["id"]
    raise ValueError(f"Node {node_id} has no owning position")


def parent_node(data: Dict, node_id: int) -> Optional[Dict]:
    parent_id = parent_id_for(data, node_id)
    return require_node(data, parent_id) if parent_id is not None else None


def sibling_nodes(data: Dict, node_id: int) -> List[Dict]:
    parent = parent_node(data, node_id)
    return child_nodes(data, parent["id"]) if parent is not None else root_nodes(data)


def owning_id_list(data: Dict, node_id: int) -> List[int]:
    """Return the authoritative ordered list that directly owns node_id."""

    parent = parent_node(data, node_id)
    return parent["children"] if parent is not None else data["root_ids"]


def destination_id_list(data: Dict, parent_id: Optional[int]) -> List[int]:
    return data["root_ids"] if parent_id is None else require_node(data, parent_id)["children"]


def closeout_review_due(data: Dict, node: Dict) -> bool:
    children = child_nodes(data, node["id"])
    return (
        bool(children)
        and is_pending(node)
        and not node.get("closeout_reviewed", False)
        and not any(is_pending(child) for child in children)
    )


def root_nodes(data: Dict) -> List[Dict]:
    return [require_node(data, node_id) for node_id in data["root_ids"]]


def subtree_ids(data: Dict, node_id: int) -> List[int]:
    found = [node_id]
    queue = [node_id]
    while queue:
        current = queue.pop(0)
        for child in child_nodes(data, current):
            found.append(child["id"])
            queue.append(child["id"])
    return found


def node_path(data: Dict, node_id: int) -> List[Dict]:
    path = []
    current = require_node(data, node_id)
    while current is not None:
        path.append(current)
        current = parent_node(data, current["id"])
    path.reverse()
    return path


def render_node_details(store: TaskTreeStore, node: Dict, data: Optional[Dict] = None) -> str:
    parent_id = parent_id_for(data, node["id"]) if data is not None else None
    parent_text = "None"
    if parent_id is not None:
        parent = find_node(data, parent_id) if data is not None else None
        parent_text = (
            render_node_brief(parent, data.get("active_id") if data is not None else None)
            if parent is not None
            else f"#{parent_id}"
        )
    lines = [
        f"id: {node['id']}",
        f"summary: {node['summary']}",
        f"status: {node['status']}",
        f"Parent: {parent_text}",
    ]
    lines.append(
        f"closeout_reviewed: {str(node.get('closeout_reviewed', False)).lower()}"
    )
    if node.get("return_to_id") is not None:
        target = find_node(data, node["return_to_id"]) if data is not None else None
        target_text = (
            render_node_brief(target, data.get("active_id"))
            if target
            else f"#{node['return_to_id']}"
        )
        lines.append(f"return_to_id: {target_text}")
    if data is not None and closeout_review_due(data, node):
        lines.append(
            "closeout_review: due - all direct children are terminal; review parent relevance/closeout before advancing"
        )
    if node.get("body"):
        lines.append(f"body: {node['body']}")
    if data is not None:
        direct_children = child_nodes(data, node["id"])
        lines.append("children:")
        if not direct_children:
            lines.append("  (none)")
        else:
            active_id = data.get("active_id")
            for child in direct_children[:DETAIL_CHILD_DISPLAY_LIMIT]:
                lines.append(f"  {render_node_brief(child, active_id)}")
            omitted = len(direct_children) - DETAIL_CHILD_DISPLAY_LIMIT
            if omitted > 0:
                noun = "child" if omitted == 1 else "children"
                lines.append(f"  ... {omitted} more {noun}")
    if node.get("files_dir"):
        lines.append(f"files_dir: {node['files_dir']}")
        artifacts = task_artifact_files(node["files_dir"])
        lines.append("files:")
        if not artifacts:
            lines.append("  (none)")
        else:
            for artifact in artifacts[:DETAIL_FILE_DISPLAY_LIMIT]:
                lines.append(f"  - {artifact}")
            omitted = len(artifacts) - DETAIL_FILE_DISPLAY_LIMIT
            if omitted > 0:
                noun = "file" if omitted == 1 else "files"
                lines.append(f"  ... {omitted} more {noun}")
    event_log_path = event_log_path_for_node(store, node)
    if os.path.exists(event_log_path):
        lines.append(f"event_log: {event_log_path}")
        latest_event = latest_event_record(event_log_path)
        if latest_event is not None:
            lines.append(f"latest_event: {summarize_event_record(latest_event)}")
    events = ensure_node_events(node)
    if events:
        lines.append("events:")
        for key in sorted(events):
            lines.append(f"  {key}: {events[key]}")
    lines.append(f"shared_dir: {shared_dir_for_store(store)}")
    return "\n".join(lines)


def render_subtree(data: Dict, node_id: int, active_id: Optional[int], depth: int = 0) -> List[str]:
    node = require_node(data, node_id)
    marker = " << ACTIVE" if node["id"] == active_id else ""
    icon = STATUS_ICONS[node["status"]]
    lines = [f"{'  ' * depth}{icon} #{node['id']} {node['summary']}{marker}"]
    for child in child_nodes(data, node_id):
        lines.extend(render_subtree(data, child["id"], active_id, depth + 1))
    return lines


def render_tree(data: Dict) -> str:
    roots = root_nodes(data)
    if not roots:
        return "(empty tree)"
    lines: List[str] = []
    for node in roots:
        lines.extend(render_subtree(data, node["id"], data["active_id"]))
    return "\n".join(lines)


def indent_text(text: str, prefix: str) -> str:
    return "\n".join(f"{prefix}{line}" for line in text.splitlines())


def render_node_brief(node: Optional[Dict], active_id: Optional[int]) -> str:
    if node is None:
        return "(none)"
    marker = " << ACTIVE" if node["id"] == active_id else ""
    return f"{STATUS_ICONS[node['status']]} #{node['id']} {node['summary']}{marker}"


def render_node_title(node: Optional[Dict]) -> str:
    """Render only the stable identifier and title for orientation context."""
    if node is None:
        return "(none)"
    return f"#{node['id']} {node['summary']}"


def sibling_window(data: Dict, node: Dict) -> tuple[Optional[Dict], Optional[Dict]]:
    siblings = sibling_nodes(data, node["id"])
    index = next(index for index, sibling in enumerate(siblings) if sibling["id"] == node["id"])
    previous_node = siblings[index - 1] if index > 0 else None
    next_node = siblings[index + 1] if index + 1 < len(siblings) else None
    return previous_node, next_node


def next_after_subtree(data: Dict, subtree_root: Optional[Dict]) -> Optional[Dict]:
    """Find the next branch after a subtree, climbing ancestors as needed."""
    current = subtree_root
    while current is not None:
        next_node = sibling_window(data, current)[1]
        if next_node is not None:
            return next_node
        current = parent_node(data, current["id"])
    return None


def render_status_snapshot(store: TaskTreeStore, data: Dict) -> str:
    active_id = data["active_id"]
    lines = ["task_tree_snapshot:"]
    if active_id is None:
        lines.append("active: (no active task)")
        lines.append(f"next_actionable: {render_node_brief(choose_next_task(data), active_id)}")
        lines.append(f"shared_dir: {shared_dir_for_store(store)}")
        return "\n".join(lines)

    active = require_node(data, active_id)
    previous_node, next_node = sibling_window(data, active)
    parent = parent_node(data, active["id"])
    # After the current branch is exhausted, tree traversal may resume at a
    # sibling of the parent or of any higher ancestor—not only the parent.
    following_branch = next_after_subtree(data, parent)
    if parent is not None:
        lines.append(f"parent: {render_node_title(parent)}")
    if previous_node is not None:
        lines.append(f"previous_sibling: {render_node_title(previous_node)}")
    lines.extend(["active:", indent_text(render_node_details(store, active, data), "  ")])
    if next_node is not None:
        lines.append(f"next_sibling: {render_node_title(next_node)}")
    if following_branch is not None:
        lines.append(f"next_after_subtree: {render_node_title(following_branch)}")
    return "\n".join(lines)


def snapshot_context_reference(node: Optional[Dict]) -> Optional[Dict]:
    if node is None:
        return None
    return {
        "id": node["id"],
        "summary": node["summary"],
        "status": node["status"],
    }


def status_snapshot_to_dict(store: TaskTreeStore, data: Dict) -> Dict:
    """Return the same structural contexts shown by the text snapshot."""
    active_id = data["active_id"]
    payload = {
        "active": None,
        "parent": None,
        "previous_sibling": None,
        "next_sibling": None,
        "next_after_subtree": None,
        "next_actionable": None,
        "shared_dir": shared_dir_for_store(store),
    }
    if active_id is None:
        payload["next_actionable"] = snapshot_context_reference(choose_next_task(data))
        return payload

    active = require_node(data, active_id)
    previous_node, next_node = sibling_window(data, active)
    parent = parent_node(data, active["id"])
    payload.update(
        {
            # Preserve the former active --json record inside the richer
            # snapshot payload so migration changes only its enclosing path.
            "active": node_to_dict(store, active, active_id, data),
            "parent": snapshot_context_reference(parent),
            "previous_sibling": snapshot_context_reference(previous_node),
            "next_sibling": snapshot_context_reference(next_node),
            "next_after_subtree": snapshot_context_reference(
                next_after_subtree(data, parent)
            ),
        }
    )
    return payload


def render_mutation_result(store: TaskTreeStore, data: Dict, *, full_tree: bool) -> str:
    # Mutation commands default to the same compact orientation view as a bare
    # invocation; callers must explicitly opt into the potentially huge tree.
    return render_tree(data) if full_tree else render_status_snapshot(store, data)


def node_to_dict(
    store: TaskTreeStore, node: Dict, active_id: Optional[int], data: Dict
) -> Dict:
    # The JSON view derives relationship metadata for callers; v2 never
    # persists these compatibility fields on the child record.
    siblings = sibling_nodes(data, node["id"])
    return {
        "id": node["id"],
        "sibling_order": next(
            index for index, sibling in enumerate(siblings, start=1) if sibling["id"] == node["id"]
        ),
        "summary": node["summary"],
        "body": node.get("body", ""),
        "status": node["status"],
        "parent_id": parent_id_for(data, node["id"]),
        "return_to_id": node.get("return_to_id"),
        "closeout_reviewed": node.get("closeout_reviewed", False),
        "files_dir": node.get("files_dir"),
        "shared_dir": shared_dir_for_store(store),
        "is_active": node["id"] == active_id,
        "events": ensure_node_events(node),
    }


def list_candidates(data: Dict, status: Optional[str] = None) -> List[Dict]:
    nodes = sorted(data["nodes"], key=lambda n: n["id"])
    if status is not None:
        nodes = [node for node in nodes if node["status"] == status]
    return nodes


PENDING_STATUSES = ACTIONABLE_STATUSES
ACTIVE_STATUSES = ACTIONABLE_STATUSES
EVENT_LIST_FIELDS = ("evidence", "changed_file", "delegate_report")
EVENT_SCALAR_FIELDS = ("phase", "next_action", "command", "exit_code", "blocker")


def is_pending(node: Dict) -> bool:
    return node["status"] in PENDING_STATUSES


def is_active_eligible(node: Dict) -> bool:
    return node["status"] in ACTIVE_STATUSES


def focus_node(data: Dict, node: Optional[Dict]) -> None:
    """Move focus without imposing the direct set-active status policy."""
    if node is None:
        data["active_id"] = None
        return
    data["active_id"] = node["id"]
    stamp_event(node, "activated_at")


def set_active_node(data: Dict, node: Optional[Dict]) -> None:
    if node is None:
        focus_node(data, None)
        return
    # Direct selection means "start/resume work" and therefore rejects a
    # terminal task. Only a return edge uses focus_node to restore terminal
    # context without asserting that the target is actionable.
    if not is_active_eligible(node):
        raise ValueError(f"Cannot set {node['status']} task active: {node['id']}")
    focus_node(data, node)


def tree_order_nodes(data: Dict, parent_id: Optional[int] = None) -> List[Dict]:
    ordered: List[Dict] = []
    siblings = root_nodes(data) if parent_id is None else child_nodes(data, parent_id)
    for node in siblings:
        ordered.append(node)
        ordered.extend(tree_order_nodes(data, node["id"]))
    return ordered


def terminal_return_source(data: Dict, completed_node: Dict) -> Optional[Dict]:
    """Return the nearest finished branch whose continuation can now fire."""
    for candidate in reversed(node_path(data, completed_node["id"])):
        if candidate.get("return_to_id") is None or is_pending(candidate):
            continue
        if all(
            not is_pending(descendant)
            for descendant in tree_order_nodes(data, candidate["id"])
        ):
            return candidate
    return None


def advance_active_after_terminal_transition(
    data: Dict, node: Dict, previous_status: str
) -> None:
    """Advance once when the focused task crosses into a terminal state."""
    # Return edges are transition hooks. Re-evaluating them merely because a
    # terminal task is focused would make old continuations fire repeatedly.
    if (
        data.get("active_id") != node["id"]
        or previous_status not in ACTIVE_STATUSES
        or is_active_eligible(node)
    ):
        return

    return_source = terminal_return_source(data, node)
    if return_source is not None:
        target = find_node(data, return_source["return_to_id"])
        if target is not None:
            # A return is a focus override, not a request for new actionable
            # work. The target therefore remains valid even when terminal.
            focus_node(data, target)
            return
        # Schema validation normally prevents a missing target. If in-memory
        # data is damaged, ordinary traversal is safer than guessing a target.

    set_active_node(data, choose_next_task(data))


def validate_return_to_assignment(data: Dict, source_id: int, target_id: int) -> None:
    """Validate a CLI return edge before mutation output is rendered."""
    require_node(data, target_id)
    if target_id == source_id:
        raise ValueError(f"Node {source_id} cannot return to itself")
    source = find_node(data, source_id)
    if source is not None and target_id in subtree_ids(data, source_id)[1:]:
        raise ValueError(f"Node {source_id} cannot return to its own descendant {target_id}")


def first_pending_descendant(data: Dict, node_id: int) -> Optional[Dict]:
    for node in tree_order_nodes(data, node_id):
        if is_pending(node):
            return node
    return None


def first_pending_after_subtree(data: Dict, ordered: List[Dict], node_id: int) -> Optional[Dict]:
    branch_ids = set(subtree_ids(data, node_id))
    branch_indexes = [index for index, node in enumerate(ordered) if node["id"] in branch_ids]
    start = max(branch_indexes) + 1 if branch_indexes else 0
    for node in ordered[start:]:
        if is_pending(node):
            return node
    return None


def first_actionable_in_branch(data: Dict, node: Dict) -> Optional[Dict]:
    if node["status"] == "in_progress":
        descendant = first_pending_descendant(data, node["id"])
        if descendant is not None:
            return descendant
    if is_pending(node):
        return node
    return first_pending_descendant(data, node["id"])


def first_actionable_among(data: Dict, nodes: List[Dict]) -> Optional[Dict]:
    for node in nodes:
        candidate = first_actionable_in_branch(data, node)
        if candidate is not None:
            return candidate
    return None


def choose_next_task_relative(data: Dict, node_id: int) -> Optional[Dict]:
    current = require_node(data, node_id)

    descendant = first_pending_descendant(data, current["id"])
    if descendant is not None:
        return descendant
    if is_pending(current):
        return current

    while parent_node(data, current["id"]) is not None:
        parent = parent_node(data, current["id"])
        siblings = child_nodes(data, parent["id"])
        current_index = next(
            index for index, node in enumerate(siblings) if node["id"] == current["id"]
        )

        candidate = first_actionable_among(data, siblings[current_index + 1 :])
        if candidate is not None:
            return candidate

        candidate = first_actionable_among(data, siblings[:current_index])
        if candidate is not None:
            return candidate

        if is_pending(parent):
            return parent

        current = parent

    root_siblings = root_nodes(data)
    root_index = next(
        index for index, node in enumerate(root_siblings) if node["id"] == current["id"]
    )

    candidate = first_actionable_among(data, root_siblings[root_index + 1 :])
    if candidate is not None:
        return candidate

    candidate = first_actionable_among(data, root_siblings[:root_index])
    if candidate is not None:
        return candidate

    return None


def choose_next_task(data: Dict, relative_to_id: Optional[int] = None) -> Optional[Dict]:
    if relative_to_id is not None:
        return choose_next_task_relative(data, relative_to_id)

    ordered = tree_order_nodes(data)
    active_id = data["active_id"]

    if active_id is not None:
        active = find_node(data, active_id)
        if active is not None:
            descendant = first_pending_descendant(data, active_id)
            if descendant is not None:
                return descendant
            if is_pending(active):
                return active

            current = active
            while parent_node(data, current["id"]) is not None:
                parent = parent_node(data, current["id"])
                after_current_branch = first_pending_after_subtree(
                    data,
                    tree_order_nodes(data, parent["id"]),
                    current["id"],
                )
                if after_current_branch is not None:
                    return after_current_branch
                if is_pending(parent):
                    return parent
                current = parent

            return first_pending_after_subtree(data, ordered, current["id"])

    for node in ordered:
        if is_pending(node):
            return node
    return None


def prune_empty_dirs(path: str) -> None:
    current = path
    while current and os.path.isdir(current):
        try:
            os.rmdir(current)
        except OSError:
            return
        parent = os.path.dirname(current)
        if parent == current:
            return
        current = parent


def parse_iso8601(ts: Optional[str]) -> Optional[datetime]:
    if not ts or not isinstance(ts, str):
        return None
    try:
        if ts.endswith("Z"):
            ts = ts[:-1] + "+00:00"
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def event_timestamp(node: Dict, event_name: str) -> Optional[datetime]:
    events = ensure_node_events(node)
    return parse_iso8601(events.get(event_name))


def query_candidates(
    data: Dict,
    status: Optional[str] = None,
    contains: Optional[str] = None,
    event_name: str = "last_mutated_at",
    since_days: Optional[float] = None,
) -> List[Dict]:
    nodes = sorted(data["nodes"], key=lambda n: n["id"])
    if status is not None:
        nodes = [node for node in nodes if node["status"] == status]
    if contains:
        needle = contains.lower()
        nodes = [
            node
            for node in nodes
            if needle in node.get("summary", "").lower() or needle in node.get("body", "").lower()
        ]
    if since_days is not None:
        cutoff = datetime.now(timezone.utc) - timedelta(days=since_days)
        filtered: List[Dict] = []
        for node in nodes:
            ts = event_timestamp(node, event_name)
            if ts is not None and ts >= cutoff:
                filtered.append(node)
        nodes = filtered
    return nodes


def parse_bool(value: str) -> bool:
    lowered = value.strip().lower()
    if lowered in {"1", "true", "yes", "y"}:
        return True
    if lowered in {"0", "false", "no", "n"}:
        return False
    raise argparse.ArgumentTypeError("expected true or false")


def parse_nonnegative_int(value: str) -> int:
    parsed = int(value)
    if parsed < 0:
        raise argparse.ArgumentTypeError("expected a nonnegative integer")
    return parsed


def ensure_task_files_dir(store: TaskTreeStore, node: Dict, timestamp: Optional[str] = None) -> str:
    files_dir = node.get("files_dir")
    if not files_dir:
        files_dir = task_files_dir_for_store(store, node["id"])
        node["files_dir"] = files_dir
        stamp_event(node, "files_created_at", timestamp)
    return ensure_dir(files_dir)


def build_event_record(args: argparse.Namespace, event_name: str) -> Dict:
    record = {
        "ts": utc_now(),
        "event": event_name,
        "summary": args.summary,
    }
    for field in EVENT_SCALAR_FIELDS:
        value = getattr(args, field, None)
        if value is not None:
            record[field] = value
    for field in EVENT_LIST_FIELDS:
        values = getattr(args, field, None)
        if values:
            record[field] = values
    return record


def append_event_record(path: str, record: Dict) -> None:
    ensure_dir(os.path.dirname(path))
    with open(path, "a+", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_EX)
        try:
            f.write(json.dumps(record, ensure_ascii=False, separators=(",", ":")))
            f.write("\n")
            f.flush()
            os.fsync(f.fileno())
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)


def load_event_records(path: str) -> List[Dict]:
    if not os.path.exists(path):
        return []
    with open(path, "r", encoding="utf-8") as f:
        fcntl.flock(f.fileno(), fcntl.LOCK_SH)
        try:
            lines = f.readlines()
        finally:
            fcntl.flock(f.fileno(), fcntl.LOCK_UN)
    records: List[Dict] = []
    for line_no, raw_line in enumerate(lines, start=1):
        line = raw_line.strip()
        if not line:
            continue
        try:
            record = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"invalid event log JSON in {path}:{line_no}: {exc}") from exc
        if not isinstance(record, dict):
            raise ValueError(f"invalid event log record in {path}:{line_no}: expected object")
        for required_key in ("ts", "event", "summary"):
            if required_key not in record:
                raise ValueError(f"invalid event log record in {path}:{line_no}: missing {required_key!r}")
        records.append(record)
    return records


def latest_event_record(path: str) -> Optional[Dict]:
    records = load_event_records(path)
    return records[-1] if records else None


def summarize_event_record(record: Dict) -> str:
    return f"{record['ts']} {record['event']}: {record['summary']}"


def render_event_record_text(record: Dict) -> List[str]:
    lines = [f"- {summarize_event_record(record)}"]
    for field in EVENT_SCALAR_FIELDS:
        if field in record:
            lines.append(f"  {field}: {record[field]}")
    for field in EVENT_LIST_FIELDS:
        for value in record.get(field, []):
            lines.append(f"  {field}: {value}")
    return lines


def render_event_log_text(path: str, records: List[Dict]) -> str:
    lines = [f"event_log: {path}"]
    if not records:
        lines.append("(no events logged)")
        return "\n".join(lines)
    for record in records:
        lines.extend(render_event_record_text(record))
    return "\n".join(lines)


def cmd_snapshot(args: argparse.Namespace) -> int:
    store = default_store(args.tree_file)
    with store.locked_data() as data:
        if getattr(args, "json", False):
            print(json.dumps(status_snapshot_to_dict(store, data), indent=2, ensure_ascii=False))
            return 0
        print(render_status_snapshot(store, data))
        return 0


def cmd_show(args: argparse.Namespace) -> int:
    if args.details and args.node_id is None:
        raise ValueError("show --details requires ID")
    store = default_store(args.tree_file)
    with store.locked_data() as data:
        if args.node_id is None:
            if args.json:
                roots = root_nodes(data)
                payload = {
                    "active_id": data["active_id"],
                    "nodes": [node_to_dict(store, n, data["active_id"], data) for n in roots],
                }
                print(json.dumps(payload, indent=2, ensure_ascii=False))
                return 0
            print(render_tree(data))
            return 0
        if args.json:
            print(json.dumps(node_to_dict(store, require_node(data, args.node_id), data["active_id"], data), indent=2, ensure_ascii=False))
            return 0
        if args.details:
            print(render_node_details(store, require_node(data, args.node_id), data))
            return 0
        print("\n".join(render_subtree(data, args.node_id, data["active_id"])))
        return 0


def cmd_add(args: argparse.Namespace) -> int:
    store = default_store(args.tree_file)
    with store.locked_data(write=True) as data:
        if args.parent is not None:
            require_node(data, args.parent)
        if args.return_to is not None:
            validate_return_to_assignment(data, data["next_id"], args.return_to)
        node = {
            "id": data["next_id"],
            "children": [],
            "summary": args.summary,
            "body": args.body or "",
            "status": args.status,
            "closeout_reviewed": False,
            "files_dir": None,
            "events": {},
        }
        if args.return_to is not None:
            node["return_to_id"] = args.return_to
        created_at = utc_now()
        stamp_event(node, "created_at", created_at)
        stamp_event(node, "status_changed_at", created_at)
        if args.body:
            stamp_event(node, "body_updated_at", created_at)
        data["next_id"] += 1
        data["nodes"].append(node)
        destination_id_list(data, args.parent).append(node["id"])
        if args.parent is not None:
            parent = require_node(data, args.parent)
            if parent.get("closeout_reviewed", False):
                parent["closeout_reviewed"] = False
                stamp_event(parent, "closeout_reviewed_updated_at", created_at)
        if args.with_files:
            node["files_dir"] = task_files_dir_for_store(store, node["id"])
            ensure_dir(node["files_dir"])
            stamp_event(node, "files_created_at")
        if args.set_active:
            set_active_node(data, node)
        if args.details:
            print(render_node_details(store, node, data))
        else:
            print(render_mutation_result(store, data, full_tree=args.full_tree))
        return 0


def cmd_update(args: argparse.Namespace) -> int:
    mutation_values = (
        args.summary,
        args.body,
        args.body_file,
        args.status,
        args.closeout_reviewed,
        args.return_to,
        args.clear_return_to or None,
    )
    if all(value is None for value in mutation_values):
        raise ValueError(
            "update requires at least one of --summary, --body, --body-file, "
            "--status, --closeout-reviewed, --return-to, or --clear-return-to"
        )

    body = None
    if args.body_file is not None:
        try:
            with open(args.body_file, "r", encoding="utf-8") as f:
                body = f.read()
        except OSError as exc:
            print(f"task_tree.py update: could not read --body-file {args.body_file!r}: {exc}", file=sys.stderr)
            return 1
    elif args.body is not None:
        body = args.body

    store = default_store(args.tree_file)
    with store.locked_data(write=True) as data:
        node = require_node(data, args.node_id)
        if args.summary is not None:
            node["summary"] = args.summary
            stamp_event(node, "summary_updated_at")
        if body is not None:
            node["body"] = body
            stamp_event(node, "body_updated_at")
        if args.closeout_reviewed is not None:
            node["closeout_reviewed"] = args.closeout_reviewed
            stamp_event(node, "closeout_reviewed_updated_at")
        if args.return_to is not None:
            validate_return_to_assignment(data, node["id"], args.return_to)
            node["return_to_id"] = args.return_to
            stamp_event(node, "return_to_updated_at")
        elif args.clear_return_to:
            node.pop("return_to_id", None)
            stamp_event(node, "return_to_updated_at")
        if args.status is not None:
            previous_status = node["status"]
            node["status"] = args.status
            stamp_event(node, "status_changed_at")
            parent = parent_node(data, node["id"])
            if parent is not None:
                if parent.get("closeout_reviewed", False):
                    parent["closeout_reviewed"] = False
                    stamp_event(parent, "closeout_reviewed_updated_at")
            advance_active_after_terminal_transition(data, node, previous_status)
        if args.details:
            print(render_node_details(store, node, data))
        else:
            print(render_mutation_result(store, data, full_tree=args.full_tree))
        return 0


def cmd_active(args: argparse.Namespace) -> int:
    store = default_store(args.tree_file)
    with store.locked_data() as data:
        active_id = data["active_id"]
        if active_id is None:
            print("(no active task)")
            return 0
        node = require_node(data, active_id)
        if args.json:
            print(json.dumps(node_to_dict(store, node, data["active_id"], data), indent=2, ensure_ascii=False))
            return 0
        print(render_node_details(store, node, data))
        return 0


def cmd_set_active(args: argparse.Namespace) -> int:
    store = default_store(args.tree_file)
    with store.locked_data(write=True) as data:
        node = require_node(data, args.node_id)
        set_active_node(data, node)
        print(render_mutation_result(store, data, full_tree=args.full_tree))
        return 0


def cmd_clear_active(args: argparse.Namespace) -> int:
    store = default_store(args.tree_file)
    with store.locked_data(write=True, validate_active=False) as data:
        data["active_id"] = None
        print(render_mutation_result(store, data, full_tree=args.full_tree))
        return 0


def cmd_path(args: argparse.Namespace) -> int:
    store = default_store(args.tree_file)
    with store.locked_data() as data:
        for node in node_path(data, args.node_id):
            print(f"#{node['id']} {node['summary']} [{node['status']}]")
        return 0


def cmd_move(args: argparse.Namespace) -> int:
    store = default_store(args.tree_file)
    with store.locked_data(write=True) as data:
        node = require_node(data, args.node_id)
        old_parent_id = parent_id_for(data, node["id"])
        if args.parent is not None:
            require_node(data, args.parent)
            if args.parent in subtree_ids(data, args.node_id):
                raise ValueError(f"Cannot move node {args.node_id} under its own subtree")
        owning_id_list(data, node["id"]).remove(node["id"])
        destination_id_list(data, args.parent).append(node["id"])
        stamp_event(node, "moved_at")
        for parent_id in {old_parent_id, args.parent}:
            if parent_id is not None:
                parent = require_node(data, parent_id)
                if parent.get("closeout_reviewed", False):
                    parent["closeout_reviewed"] = False
                    stamp_event(parent, "closeout_reviewed_updated_at")
        print(render_mutation_result(store, data, full_tree=args.full_tree))
        return 0


def cmd_reorder(args: argparse.Namespace) -> int:
    store = default_store(args.tree_file)
    with store.locked_data(write=True) as data:
        node = require_node(data, args.node_id)
        owner = owning_id_list(data, node["id"])
        node_parent_id = parent_id_for(data, node["id"])
        siblings = sibling_nodes(data, node["id"])
        siblings = [sibling for sibling in siblings if sibling["id"] != node["id"]]
        if args.first:
            siblings.insert(0, node)
        elif args.before is not None:
            target = require_node(data, args.before)
            if parent_id_for(data, target["id"]) != node_parent_id:
                raise ValueError(f"Node {args.before} is not a sibling of node {args.node_id}")
            insert_at = next(index for index, sibling in enumerate(siblings) if sibling["id"] == args.before)
            siblings.insert(insert_at, node)
        elif args.after is not None:
            target = require_node(data, args.after)
            if parent_id_for(data, target["id"]) != node_parent_id:
                raise ValueError(f"Node {args.after} is not a sibling of node {args.node_id}")
            insert_at = next(index for index, sibling in enumerate(siblings) if sibling["id"] == args.after) + 1
            siblings.insert(insert_at, node)
        elif args.before_first_pending:
            insert_at = next(
                (
                    index
                    for index, sibling in enumerate(siblings)
                    if sibling["status"] in ("in_progress", "not_started")
                ),
                len(siblings),
            )
            siblings.insert(insert_at, node)
        else:
            siblings.append(node)
        owner[:] = [sibling["id"] for sibling in siblings]
        stamp_event(node, "moved_at")
        print(render_mutation_result(store, data, full_tree=args.full_tree))
        return 0


def cmd_delete(args: argparse.Namespace) -> int:
    store = default_store(args.tree_file)
    with store.locked_data(write=True) as data:
        node = require_node(data, args.node_id)
        parent_id = parent_id_for(data, node["id"])
        doomed = set(subtree_ids(data, args.node_id))
        if node["children"] and not args.force:
            raise ValueError("Refusing to delete a task with children without --force")
        incoming_returns = [
            candidate["id"]
            for candidate in data["nodes"]
            if candidate["id"] not in doomed
            and candidate.get("return_to_id") in doomed
        ]
        if incoming_returns:
            rendered = ", ".join(str(node_id) for node_id in sorted(incoming_returns))
            raise ValueError(
                "Refusing to delete return target; clear or rewrite return_to_id "
                f"on task(s): {rendered}"
            )
        for node_id in doomed:
            node = require_node(data, node_id)
            if node.get("files_dir"):
                removed = remove_dir_if_exists(node["files_dir"])
                if removed:
                    stamp_event(node, "files_pruned_at")
                node["files_dir"] = None
        owning_id_list(data, args.node_id).remove(args.node_id)
        data["nodes"] = [node for node in data["nodes"] if node["id"] not in doomed]
        if parent_id is not None and parent_id not in doomed:
            parent = require_node(data, parent_id)
            if parent.get("closeout_reviewed", False):
                parent["closeout_reviewed"] = False
                stamp_event(parent, "closeout_reviewed_updated_at")
        if data["active_id"] in doomed:
            data["active_id"] = None
        files_root = os.path.join(base_dir_for_store(store), "files")
        prune_empty_dirs(files_root)
        print(render_mutation_result(store, data, full_tree=args.full_tree))
        return 0


def cmd_list(args: argparse.Namespace) -> int:
    store = default_store(args.tree_file)
    with store.locked_data() as data:
        nodes = list_candidates(data, args.status)
        if not nodes:
            print("(no matching tasks)")
            return 0
        if args.json:
            print(json.dumps({
                "active_id": data["active_id"],
                "nodes": [node_to_dict(store, node, data["active_id"], data) for node in nodes],
            }, indent=2, ensure_ascii=False))
            return 0
        for node in nodes:
            marker = " << ACTIVE" if node["id"] == data["active_id"] else ""
            print(f"{STATUS_ICONS[node['status']]} #{node['id']} {node['summary']}{marker}")
        return 0


def cmd_children(args: argparse.Namespace) -> int:
    store = default_store(args.tree_file)
    with store.locked_data() as data:
        require_node(data, args.node_id)
        nodes = child_nodes(data, args.node_id)
        if not nodes:
            print("(no child tasks)")
            return 0
        if args.json:
            payload = {
                "active_id": data["active_id"],
                "parent_id": args.node_id,
                "nodes": [node_to_dict(store, node, data["active_id"], data) for node in nodes],
            }
            output = json.dumps(payload, indent=2, ensure_ascii=False)
            if len(output.splitlines()) > MAX_FULL_CHILDREN_JSON_LINES:
                output = json.dumps({
                    "active_id": data["active_id"],
                    "parent_id": args.node_id,
                    "compact": True,
                    "line_limit": MAX_FULL_CHILDREN_JSON_LINES,
                    "full_output_line_count": len(output.splitlines()),
                    "nodes": [
                        {
                            "id": node["id"],
                            "sibling_order": position,
                            "summary": node["summary"],
                            "status": node["status"],
                            "parent_id": args.node_id,
                            "is_active": node["id"] == data["active_id"],
                        }
                        for position, node in enumerate(nodes, start=1)
                    ],
                }, indent=2, ensure_ascii=False)
            print(output)
            return 0
        if args.details:
            print("\n---\n".join(render_node_details(store, node, data) for node in nodes))
            return 0
        for node in nodes:
            marker = " << ACTIVE" if node["id"] == data["active_id"] else ""
            print(f"{STATUS_ICONS[node['status']]} #{node['id']} {node['summary']}{marker}")
        return 0


def cmd_query(args: argparse.Namespace) -> int:
    store = default_store(args.tree_file)
    with store.locked_data() as data:
        nodes = query_candidates(
            data,
            status=args.status,
            contains=args.contains,
            event_name=args.event,
            since_days=args.since_days,
        )
        if not nodes:
            print("(no matching tasks)")
            return 0
        if args.json:
            print(json.dumps({
                "active_id": data["active_id"],
                "query": {
                    "status": args.status,
                    "contains": args.contains,
                    "event": args.event,
                    "since_days": args.since_days,
                },
                "nodes": [node_to_dict(store, node, data["active_id"], data) for node in nodes],
            }, indent=2, ensure_ascii=False))
            return 0
        for node in nodes:
            marker = " << ACTIVE" if node["id"] == data["active_id"] else ""
            ts = ensure_node_events(node).get(args.event)
            base = f"{STATUS_ICONS[node['status']]} #{node['id']} {node['summary']}{marker}"
            if ts:
                base += f" [{args.event}={ts}]"
            print(base)
            if args.details:
                if node.get("body"):
                    print(f"  body: {node['body']}")
                if node.get("files_dir"):
                    print(f"  files_dir: {node['files_dir']}")
        return 0


def cmd_next(args: argparse.Namespace) -> int:
    """Print the next actionable task for direct human reading.

    Do not parse this prose output with broad shell regexes; read the `id:`
    field directly, or add a structured output mode before automating it.
    When a completed child leaves its parent with no pending direct children,
    next returns the parent for closeout before advancing outside that branch.
    """
    store = default_store(args.tree_file)
    with store.locked_data() as data:
        if args.node_id is not None:
            require_node(data, args.node_id)
        node = choose_next_task(data, relative_to_id=args.node_id)
        if node is None:
            print("(no next task)")
            return 0
        print(render_node_details(store, node, data))
        return 0


def cmd_ensure_files(args: argparse.Namespace) -> int:
    store = default_store(args.tree_file)
    with store.locked_data(write=True) as data:
        node = require_node(data, args.node_id)
        print(ensure_task_files_dir(store, node))
        return 0


def cmd_log_event(args: argparse.Namespace) -> int:
    store = default_store(args.tree_file)
    record = build_event_record(args, args.event)
    with store.locked_data(write=True) as data:
        node = require_node(data, args.node_id)
        log_path = os.path.join(ensure_task_files_dir(store, node, record["ts"]), "events.jsonl")
        append_event_record(log_path, record)
        print(render_event_log_text(log_path, [record]))
        return 0


def cmd_event_log(args: argparse.Namespace) -> int:
    store = default_store(args.tree_file)
    with store.locked_data() as data:
        node = require_node(data, args.node_id)
        log_path = event_log_path_for_node(store, node)
        records = load_event_records(log_path)
        if args.tail is not None:
            records = records[-args.tail :] if args.tail else []
        if args.json:
            print(json.dumps({
                "task_id": args.node_id,
                "event_log": log_path,
                "events": records,
            }, indent=2, ensure_ascii=False))
            return 0
        print(render_event_log_text(log_path, records))
        return 0


def cmd_checkpoint(args: argparse.Namespace) -> int:
    body = None
    if args.body_file is not None:
        try:
            with open(args.body_file, "r", encoding="utf-8") as f:
                body = f.read()
        except OSError as exc:
            print(f"task_tree.py checkpoint: could not read --body-file {args.body_file!r}: {exc}", file=sys.stderr)
            return 1

    store = default_store(args.tree_file)
    record = build_event_record(args, "checkpoint")
    with store.locked_data(write=True) as data:
        node = require_node(data, args.node_id)
        if body is not None:
            node["body"] = body
            stamp_event(node, "body_updated_at", record["ts"])
        log_path = os.path.join(ensure_task_files_dir(store, node, record["ts"]), "events.jsonl")
        append_event_record(log_path, record)
        print(render_event_log_text(log_path, [record]))
        return 0


def cmd_prune_files(args: argparse.Namespace) -> int:
    store = default_store(args.tree_file)
    with store.locked_data(write=True) as data:
        node = require_node(data, args.node_id)
        files_dir = node.get("files_dir")
        if not files_dir:
            print("(no files_dir set)")
            return 0
        removed = remove_dir_if_exists(files_dir)
        node["files_dir"] = None
        if removed:
            stamp_event(node, "files_pruned_at")
        print(f"removed: {removed}")
        files_root = os.path.join(base_dir_for_store(store), "files")
        prune_empty_dirs(files_root)
        return 0


def cmd_shared_dir(args: argparse.Namespace) -> int:
    store = default_store(args.tree_file)
    print(ensure_dir(shared_dir_for_store(store)))
    return 0


def cmd_clear(args: argparse.Namespace) -> int:
    store = default_store(args.tree_file)
    lock_dir = os.path.dirname(store.lock_path) or "."
    os.makedirs(lock_dir, exist_ok=True)
    with open(store.lock_path, "a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        if args.prune_files:
            remove_dir_if_exists(os.path.join(base_dir_for_store(store), "files"))
        if args.prune_shared:
            remove_dir_if_exists(shared_dir_for_store(store))
        if args.drop_file:
            store.remove_tree_file_unlocked()
        else:
            store.reset_unlocked()
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)
        print("(empty tree)")
        return 0


def cmd_reset(args: argparse.Namespace) -> int:
    args.prune_files = True
    return cmd_clear(args)


def option_label(action: argparse.Action) -> str:
    """Render one visible long option for the root option reference."""
    option = next((item for item in action.option_strings if item.startswith("--")), action.option_strings[0])
    if action.nargs == 0:
        return option
    metavar = action.metavar or action.dest.upper().replace("_", "-")
    return f"{option} {metavar}"


def append_option_reference_line(lines: List[str], label: str, description: str, *, indent: str = "    ") -> None:
    prefix = f"{indent}{label:<28}"
    lines.extend(
        textwrap.wrap(
            description,
            width=92,
            initial_indent=prefix,
            subsequent_indent=" " * len(prefix),
        )
    )


def render_subcommand_option_reference(subcommands: argparse._SubParsersAction) -> str:
    """Build a root-help appendix from the same action help used by each command."""
    # The root overview must expose option meanings, but maintaining a second
    # hand-written option table would drift from each command's own --help.
    lines = ["Subcommand-specific options:"]
    for name, command_parser in subcommands.choices.items():
        visible_actions = [
            action
            for action in command_parser._actions
            if action.option_strings
            and action.dest != "help"
            and action.help is not argparse.SUPPRESS
        ]
        if not visible_actions:
            continue
        choice = next(
            choice_action
            for choice_action in subcommands._choices_actions
            if choice_action.dest == name
        )
        lines.extend(("", f"  {choice.metavar}"))
        required_groups = {
            id(action): group
            for group in command_parser._mutually_exclusive_groups
            if group.required
            for action in group._group_actions
        }
        emitted_groups = set()
        for action in visible_actions:
            group = required_groups.get(id(action))
            if group is not None:
                if id(group) in emitted_groups:
                    continue
                emitted_groups.add(id(group))
                lines.append("    Choose one:")
                for grouped_action in group._group_actions:
                    append_option_reference_line(
                        lines,
                        option_label(grouped_action),
                        grouped_action.help,
                        indent="      ",
                    )
                continue
            requirement = " (required)" if action.required else ""
            append_option_reference_line(lines, option_label(action) + requirement, action.help)
    return "\n".join(lines)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Persistent task tree. If no command is specified, show the "
            "compact active-task snapshot."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--tree-file",
        metavar="PATH",
        help=(
            "Use PATH as the task-tree JSON file for this invocation. "
            "Default: ./task_tree/tree.json"
        ),
    )
    sub = parser.add_subparsers(dest="command")

    def add_command(name: str, synopsis: str, *, help: str, **kwargs) -> argparse.ArgumentParser:
        command_parser = sub.add_parser(name, help=help, **kwargs)
        # argparse exposes no public parameter for a subcommand's label in the
        # parent command list. Its pseudo-action controls display only, so this
        # leaves the accepted command token as `name` while aligning its compact
        # synopsis with the other command labels.
        sub._choices_actions[-1].metavar = synopsis
        return command_parser

    def add_event_record_arguments(command_parser: argparse.ArgumentParser, *, include_event: bool) -> None:
        if include_event:
            command_parser.add_argument("--event", required=True, metavar="EVENT", help="Name the event recorded in the task event log.")
        command_parser.add_argument("--summary", required=True, metavar="TEXT", help="Provide a concise factual summary for the event.")
        command_parser.add_argument("--phase", metavar="TEXT", help="Record the work phase associated with the event.")
        command_parser.add_argument("--next-action", dest="next_action", metavar="TEXT", help="Record the next intended action.")
        command_parser.add_argument("--command", metavar="TEXT", help="Record the command associated with the event.")
        command_parser.add_argument("--exit-code", dest="exit_code", type=int, metavar="CODE", help="Record the command exit code.")
        command_parser.add_argument("--blocker", metavar="TEXT", help="Record a blocker that prevents progress.")
        command_parser.add_argument("--evidence", action="append", metavar="PATH", help="Add an evidence path; repeat for multiple paths.")
        command_parser.add_argument("--changed-file", dest="changed_file", action="append", metavar="PATH", help="Add a changed-file path; repeat for multiple paths.")
        command_parser.add_argument("--delegate-report", dest="delegate_report", action="append", metavar="PATH", help="Add a delegate-report path; repeat for multiple paths.")

    def add_mutation_output_arguments(
        command_parser: argparse.ArgumentParser,
        *,
        include_details: bool = False,
    ) -> None:
        # Compact output is the safe default because real task trees can be
        # large enough for a routine mutation to flood the caller's context.
        output = command_parser.add_mutually_exclusive_group()
        if include_details:
            output.add_argument("--details", action="store_true", help="Print the affected task's full details instead of a compact snapshot.")
        output.add_argument("--full-tree", action="store_true", help="Print the full tree instead of a compact snapshot after the mutation.")

    snapshot = add_command(
        "snapshot",
        "snapshot [default]",
        help="Show active task with previous/next sibling context",
    )
    snapshot.add_argument("--json", action="store_true", help="Emit the complete snapshot context as JSON rather than text.")
    snapshot.set_defaults(func=cmd_snapshot)

    show = add_command("show", "show [id]", help="Show the whole tree or a subtree")
    show.add_argument("node_id", nargs="?", type=int, metavar="ID", help="Show this task and its subtree; omit to show all roots.")
    show_output = show.add_mutually_exclusive_group()
    show_output.add_argument("--details", action="store_true", help="Show full details for one task instead of its subtree.")
    show_output.add_argument("--json", action="store_true", help="Emit JSON rather than text.")
    show.set_defaults(func=cmd_show)

    add = add_command("add", "add <summary>", help="Add a task")
    add.add_argument("summary", metavar="SUMMARY", help="Set the task's short title.")
    add.add_argument("--body", default="", metavar="TEXT", help="Set the task body.")
    add.add_argument("--parent", type=int, metavar="ID", help="Create the task as a child of ID.")
    add.add_argument("--return-to", dest="return_to", type=int, metavar="ID", help="After this task's subtree finishes, return focus to ID.")
    add.add_argument("--status", default="not_started", choices=VALID_STATUSES, metavar="STATUS", help="Set the initial task status.")
    add.add_argument("--set-active", action="store_true", help="Make the new task active.")
    add.add_argument("--with-files", action="store_true", help="Create the new task's artifact directory.")
    add_mutation_output_arguments(add, include_details=True)
    add.set_defaults(func=cmd_add)

    update = add_command(
        "update",
        "update <id>",
        help="Update an existing task; requires a mutation option.",
        description=(
            "At least one mutation option is required."
        ),
    )
    update.add_argument("node_id", type=int, metavar="ID", help="Identify the task to update.")
    update.add_argument("--summary", metavar="TEXT", help="Replace the task summary.")
    update_body = update.add_mutually_exclusive_group()
    update_body.add_argument("--body", metavar="TEXT", help="Replace the task body with TEXT.")
    update_body.add_argument("--body-file", metavar="PATH", help="Read the replacement task body from a UTF-8 text file.")
    update.add_argument("--status", choices=VALID_STATUSES, metavar="STATUS", help="Set the task status.")
    update.add_argument("--closeout-reviewed", type=parse_bool, metavar="BOOL", help="Set whether child-work closeout was reviewed.")
    update_return = update.add_mutually_exclusive_group()
    update_return.add_argument("--return-to", dest="return_to", type=int, metavar="ID", help="After this task's subtree finishes, return focus to ID.")
    update_return.add_argument("--clear-return-to", action="store_true", help="Remove this task's return-focus override.")
    add_mutation_output_arguments(update, include_details=True)
    update.set_defaults(func=cmd_update)

    active = add_command(
        "active",
        "active",
        help="[deprecated] Use snapshot instead.",
        description="Deprecated: use snapshot or snapshot --json instead.",
    )
    active.add_argument("--json", action="store_true", help="Emit the active task as JSON rather than text.")
    active.set_defaults(func=cmd_active)

    set_active = add_command("set-active", "set-active <id>", help="Mark a task as active")
    set_active.add_argument("node_id", type=int, metavar="ID", help="Identify the task to make active.")
    add_mutation_output_arguments(set_active)
    set_active.set_defaults(func=cmd_set_active)

    clear_active = add_command("clear-active", "clear-active", help="Clear the active task")
    add_mutation_output_arguments(clear_active)
    clear_active.set_defaults(func=cmd_clear_active)

    path_cmd = add_command("path", "path <id>", help="Show path from root to a task")
    path_cmd.add_argument("node_id", type=int, metavar="ID", help="Identify the task whose ancestry to show.")
    path_cmd.set_defaults(func=cmd_path)

    move = add_command("move", "move <id>", help="Move a task under a new parent")
    move.add_argument("node_id", type=int, metavar="ID", help="Identify the task to move.")
    move.add_argument("--parent", type=int, metavar="ID", help="Move the task under ID; omit to make it a root task.")
    add_mutation_output_arguments(move)
    move.set_defaults(func=cmd_move)

    reorder = add_command(
        "reorder",
        "reorder <id>",
        help="Move a task among siblings; requires a placement option",
    )
    reorder.add_argument("node_id", type=int, metavar="ID", help="Identify the task to reorder.")
    reorder_pos = reorder.add_mutually_exclusive_group(required=True)
    reorder_pos.add_argument("--first", action="store_true", help="Move the task before all siblings.")
    reorder_pos.add_argument("--before", type=int, metavar="ID", help="Move the task before sibling ID.")
    reorder_pos.add_argument("--after", type=int, metavar="ID", help="Move the task after sibling ID.")
    reorder_pos.add_argument(
        "--before-first-pending",
        action="store_true",
        help="Move before the first actionable sibling; append if none exist.",
    )
    reorder_pos.add_argument("--last", action="store_true", help="Move the task after all siblings.")
    add_mutation_output_arguments(reorder)
    reorder.set_defaults(func=cmd_reorder)

    delete = add_command("delete", "delete <id>", help="Delete a task or subtree")
    delete.add_argument("node_id", type=int, metavar="ID", help="Identify the task or subtree to delete.")
    delete.add_argument(
        "--force",
        action="store_true",
        help=(
            "Allow deletion when the task has children; surviving return_to_id "
            "references still block deletion."
        ),
    )
    add_mutation_output_arguments(delete)
    delete.set_defaults(func=cmd_delete)

    list_cmd = add_command("list", "list", help="List tasks flat, optionally filtered by status")
    list_cmd.add_argument("--status", choices=VALID_STATUSES, metavar="STATUS", help="Include only tasks with this status.")
    list_cmd.add_argument("--json", action="store_true", help="Emit JSON rather than text.")
    list_cmd.set_defaults(func=cmd_list)

    children_cmd = add_command("children", "children <id>", help="List direct child tasks")
    children_cmd.add_argument("node_id", type=int, metavar="ID", help="Identify the parent task.")
    children_output = children_cmd.add_mutually_exclusive_group()
    children_output.add_argument("--details", action="store_true", help="Show full details for each direct child.")
    children_output.add_argument("--json", action="store_true", help="Emit JSON rather than text.")
    children_cmd.set_defaults(func=cmd_children)

    query_cmd = add_command("query", "query", help="Query tasks by status/text and event time")
    query_cmd.add_argument("--status", choices=VALID_STATUSES, metavar="STATUS", help="Include only tasks with this status.")
    query_cmd.add_argument("--contains", metavar="TEXT", help="Include tasks whose summary or body contains TEXT.")
    query_cmd.add_argument(
        "--event",
        default="last_mutated_at",
        metavar="TIMESTAMP",
        choices=[
            "created_at",
            "activated_at",
            "status_changed_at",
            "summary_updated_at",
            "body_updated_at",
            "closeout_reviewed_updated_at",
            "return_to_updated_at",
            "moved_at",
            "files_created_at",
            "files_pruned_at",
            "last_mutated_at",
        ],
        help="Choose the lifecycle timestamp used with --since-days.",
    )
    query_cmd.add_argument("--since-days", type=float, metavar="DAYS", help="Include tasks whose chosen timestamp is within DAYS.")
    query_output = query_cmd.add_mutually_exclusive_group()
    query_output.add_argument("--details", action="store_true", help="Include task body and artifact-directory fields in text output.")
    query_output.add_argument("--json", action="store_true", help="Emit JSON rather than text.")
    query_cmd.set_defaults(func=cmd_query)

    next_cmd = add_command(
        "next",
        "next [id]",
        help="Suggest the next actionable task",
        description=(
            "Print the next actionable task for direct human reading. If "
            "node_id is supplied, calculate relative to that task instead of "
            "the active task without changing active state. Do not parse this "
            "prose output with broad shell regexes; read the `id:` field "
            "directly, or add a structured output mode before automating it. "
            "If a completed child leaves its parent with no pending direct "
            "children, return that parent for closeout before advancing "
            "outside the branch."
        ),
    )
    next_cmd.add_argument("node_id", nargs="?", type=int, metavar="ID", help="Choose next work relative to ID instead of the active task.")
    next_cmd.set_defaults(func=cmd_next)

    ensure_files = add_command(
        "ensure-files",
        "ensure-files <id>",
        help="Create and print the task-specific artifact directory",
    )
    ensure_files.add_argument("node_id", type=int, metavar="ID", help="Identify the task whose artifact directory to create.")
    ensure_files.set_defaults(func=cmd_ensure_files)

    log_event = add_command(
        "log-event",
        "log-event <id>",
        help="Append a compact JSONL event record; requires --event and --summary",
    )
    log_event.add_argument("node_id", type=int, metavar="ID", help="Identify the task that owns the event.")
    add_event_record_arguments(log_event, include_event=True)
    log_event.set_defaults(func=cmd_log_event)

    event_log = add_command("event-log", "event-log <id>", help="Show a task's append-only event log")
    event_log.add_argument("node_id", type=int, metavar="ID", help="Identify the task whose event log to show.")
    event_log.add_argument("--tail", type=parse_nonnegative_int, metavar="COUNT", help="Show only the last COUNT events.")
    event_log.add_argument("--json", action="store_true", help="Emit JSON rather than text.")
    event_log.set_defaults(func=cmd_event_log)

    checkpoint = add_command(
        "checkpoint",
        "checkpoint <id>",
        help="Append a checkpoint event; requires --summary",
    )
    checkpoint.add_argument("node_id", type=int, metavar="ID", help="Identify the task that owns the checkpoint.")
    add_event_record_arguments(checkpoint, include_event=False)
    checkpoint.add_argument("--body-file", metavar="PATH", help="Read the replacement task body from a UTF-8 text file.")
    checkpoint.set_defaults(func=cmd_checkpoint)

    prune_files = add_command(
        "prune-files",
        "prune-files <id>",
        help="Delete a task's artifact directory",
    )
    prune_files.add_argument("node_id", type=int, metavar="ID", help="Identify the task whose artifact directory to delete.")
    prune_files.set_defaults(func=cmd_prune_files)

    shared_dir = add_command("shared-dir", "shared-dir", help="Show and create the shared artifact directory")
    shared_dir.set_defaults(func=cmd_shared_dir)

    clear_cmd = add_command("clear", "clear", help="Clear the whole task tree")
    clear_cmd.add_argument("--prune-files", action="store_true", help="Delete all task artifact directories.")
    clear_cmd.add_argument("--prune-shared", action="store_true", help="Delete the shared artifact directory.")
    clear_cmd.add_argument("--drop-file", action="store_true", help="Delete the backing tree JSON file instead of resetting it.")
    clear_cmd.set_defaults(func=cmd_clear)

    reset_cmd = add_command(
        "reset",
        "reset",
        help="Clear the tree and delete all task artifact directories",
    )
    reset_cmd.add_argument("--prune-shared", action="store_true", help="Delete the shared artifact directory.")
    reset_cmd.add_argument("--drop-file", action="store_true", help="Delete the backing tree JSON file instead of resetting it.")
    reset_cmd.set_defaults(func=cmd_reset)

    parser.epilog = render_subcommand_option_reference(sub)
    return parser


def main(argv: List[str]) -> int:
    parser = build_parser()
    parser.set_defaults(func=cmd_snapshot)
    args = parser.parse_args(argv)
    warning = legacy_store_environment_warning(args.tree_file)
    if warning:
        print(warning, file=sys.stderr)
    if args.command == "active":
        print("warning: active is deprecated; use snapshot or snapshot --json", file=sys.stderr)
    return args.func(args)


if __name__ == "__main__":
    try:
        raise SystemExit(main(sys.argv[1:]))
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        raise SystemExit(2)
