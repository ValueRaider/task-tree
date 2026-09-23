"""Focused persistence and one-level undo tests for the Textual TUI."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
from pathlib import Path

import pytest


pytest.importorskip("textual")

TEST_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TEST_DIR.parent / "scripts"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


task_tree = _load_module("task_tree_for_tui_undo_tests", SCRIPTS_DIR / "task_tree.py")
task_tree_tui = _load_module(
    "task_tree_tui_for_undo_tests", SCRIPTS_DIR / "task_tree_tui.py"
)


def _node(node_id: int, summary: str, *, children=()):
    return {
        "id": node_id,
        "children": list(children),
        "summary": summary,
        "body": f"Details for {summary}",
        "status": "not_started",
        "closeout_reviewed": False,
        "files_dir": None,
        "events": {},
    }


def _fixture_store(tmp_path: Path):
    store = task_tree.TaskTreeStore(str(tmp_path / "tree.json"))
    with store.locked_data(write=True) as data:
        data.update(
            {
                "schema_version": 2,
                "next_id": 8,
                "active_id": 1,
                "root_ids": [1, 4],
                "nodes": [
                    _node(1, "Original parent", children=[2, 3]),
                    _node(2, "Source", children=[7]),
                    _node(3, "Original next"),
                    _node(4, "Destination", children=[5, 6]),
                    _node(5, "Destination previous"),
                    _node(6, "Destination next"),
                    _node(7, "Source child"),
                ],
            }
        )
    return store


def _read(store):
    with store.locked_data() as data:
        return copy.deepcopy(data)


def test_drop_persists_subtree_and_undo_restores_anchors(tmp_path):
    store = _fixture_store(tmp_path)
    calls = []

    def relocate(*args, **kwargs):
        calls.append((args, kwargs))
        return task_tree.relocate_node(*args, **kwargs)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store, relocate_node=relocate)
        async with app.run_test() as pilot:
            await pilot.pause()
            intent = task_tree_tui.DropIntent(2, 4, before_id=6)
            app.handle_drag_drop(intent)
            await pilot.pause()
            moved = _read(store)
            assert [node["children"] for node in moved["nodes"] if node["id"] in (1, 2, 4)] == [
                [3],
                [7],
                [5, 2, 6],
            ]
            assert len(calls) == 1
            receipt = app._undo_receipt
            assert receipt is not None
            moved_at = receipt.moved_at

            app.action_undo()
            await pilot.pause()
            restored = _read(store)
            assert next(node for node in restored["nodes"] if node["id"] == 1)["children"] == [2, 3]
            assert next(node for node in restored["nodes"] if node["id"] == 4)["children"] == [5, 6]
            source = next(node for node in restored["nodes"] if node["id"] == 2)
            assert source["children"] == [7]
            assert source["events"]["moved_at"] != moved_at
            assert len(calls) == 2
            assert app._undo_receipt is None

    asyncio.run(exercise())


def test_second_drop_replaces_undo_and_reload_clears_it(tmp_path):
    store = _fixture_store(tmp_path)
    calls = []

    def relocate(*args, **kwargs):
        calls.append(1)
        return task_tree.relocate_node(*args, **kwargs)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store, relocate_node=relocate)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.handle_drag_drop(task_tree_tui.DropIntent(2, 4, before_id=6))
            await pilot.pause()
            first = app._undo_receipt
            app.handle_drag_drop(task_tree_tui.DropIntent(2, None, after_id=1))
            await pilot.pause()
            assert app._undo_receipt is not None
            assert app._undo_receipt is not first
            assert len(calls) == 2
            app.action_reload()
            await pilot.pause()
            assert app._undo_receipt is None
            assert app._status == ""

    asyncio.run(exercise())


def test_external_change_and_missing_anchor_refuse_without_mutation(tmp_path):
    store = _fixture_store(tmp_path)
    calls = []

    def relocate(*args, **kwargs):
        calls.append(1)
        return task_tree.relocate_node(*args, **kwargs)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store, relocate_node=relocate)
        async with app.run_test() as pilot:
            await pilot.pause()
            app.handle_drag_drop(task_tree_tui.DropIntent(2, 4, before_id=6))
            await pilot.pause()
            # Move the source externally: its moved_at and current owner no
            # longer satisfy the retained receipt.
            with store.locked_data(write=True) as data:
                task_tree.relocate_node(data, 2, None)
            before = _read(store)
            app.action_undo()
            await pilot.pause()
            assert _read(store) == before
            assert len(calls) == 1
            assert app._undo_receipt is None

            # Create a fresh drop, then remove the original next anchor by an
            # external relocation. The inverse must refuse rather than guess.
            with store.locked_data(write=True) as data:
                task_tree.relocate_node(data, 2, 1, before_id=3)
            app.handle_drag_drop(task_tree_tui.DropIntent(2, 4, before_id=6))
            await pilot.pause()
            with store.locked_data(write=True) as data:
                task_tree.relocate_node(data, 3, None)
            before = _read(store)
            app.action_undo()
            await pilot.pause()
            assert _read(store) == before
            assert len(calls) == 2
            assert app._undo_receipt is None

    asyncio.run(exercise())
