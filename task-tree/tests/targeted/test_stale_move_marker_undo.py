"""TUI regression for stale receipts after serialized same-second moves."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
from pathlib import Path

import pytest


pytest.importorskip("textual")

SKILL_DIR = Path(__file__).resolve().parents[2]
SCRIPTS_DIR = SKILL_DIR / "scripts"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


task_tree = _load_module("task_tree_for_move_marker_incident", SCRIPTS_DIR / "task_tree.py")
task_tree_tui = _load_module("task_tree_tui_for_move_marker_incident", SCRIPTS_DIR / "task_tree_tui.py")


def _node(node_id, children=()):
    return {
        "id": node_id,
        "children": list(children),
        "summary": f"Task {node_id}",
        "body": "",
        "status": "not_started",
        "closeout_reviewed": False,
        "files_dir": None,
        "events": {},
    }


def _make_store(tmp_path):
    store = task_tree.TaskTreeStore(str(tmp_path / "tree.json"))
    with store.locked_data(write=True) as data:
        data.update(
            {
                "schema_version": 2,
                "next_id": 8,
                "active_id": 1,
                "root_ids": [1, 4],
                "nodes": [
                    _node(1, [2, 3]),
                    _node(2, [7]),
                    _node(3),
                    _node(4, [5, 6]),
                    _node(5),
                    _node(6),
                    _node(7),
                ],
            }
        )
    return store


def _read(store):
    with store.locked_data() as data:
        return copy.deepcopy(data)


def test_stale_first_receipt_rejected_after_three_same_second_moves(tmp_path, monkeypatch):
    fixed_time = "2026-02-03T04:05:06Z"
    monkeypatch.setattr(task_tree, "utc_now", lambda: fixed_time)
    store = _make_store(tmp_path)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store, relocate_node=task_tree.relocate_node)
        async with app.run_test() as pilot:
            await pilot.pause()

            # First move is the UI drop and its receipt is retained for undo.
            app.handle_drag_drop(task_tree_tui.DropIntent(2, 4, before_id=6))
            await pilot.pause()
            first_receipt = app._undo_receipt
            assert first_receipt is not None
            first_marker = first_receipt.move_marker

            # Two later moves return the same task to exactly the first
            # destination, under separate serialized store locks.
            with store.locked_data(write=True) as data:
                second_receipt = task_tree.relocate_node(data, 2, 1, after_id=3)
            with store.locked_data(write=True) as data:
                third_receipt = task_tree.relocate_node(data, 2, 4, before_id=6)

            markers = [first_marker, second_receipt.move_marker, third_receipt.move_marker]
            assert len(set(markers)) == 3
            assert [first_receipt.moved_at, second_receipt.moved_at, third_receipt.moved_at] == [fixed_time] * 3
            assert _read(store)["nodes"][1]["events"]["move_marker"] == third_receipt.move_marker

            before_undo = _read(store)
            app.action_undo()
            await pilot.pause()
            assert _read(store) == before_undo
            assert app._undo_receipt is None
            assert "changed after the drop" in app._status

    asyncio.run(exercise())
