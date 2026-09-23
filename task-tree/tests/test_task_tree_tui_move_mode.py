"""Focused tests for keyboard-initiated, no-button TUI movement."""

from __future__ import annotations

import asyncio
import importlib.util
import math
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


task_tree = _load_module("task_tree_for_tui_move_mode_tests", SCRIPTS_DIR / "task_tree.py")
task_tree_tui = _load_module(
    "task_tree_tui_for_move_mode_tests", SCRIPTS_DIR / "task_tree_tui.py"
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
                "next_id": 7,
                "active_id": 1,
                "root_ids": [1, 4, 5],
                "nodes": [
                    _node(1, "Root"),
                    _node(4, "Source"),
                    _node(5, "Target", children=[6]),
                    _node(6, "Target child"),
                ],
            }
        )
    return store


def _node_for(tree, task_id: int):
    return next(node for node in tree._tree_nodes.values() if node.data == task_id)


def _task_text_midpoint(tree, task_id: int) -> float:
    """Derive the rendered task-text midpoint from the actual row geometry."""

    node = _node_for(tree, task_id)
    strip = tree._render_line(
        node._line,
        0,
        max(tree.size.width, tree.virtual_size.width),
        tree.rich_style,
    )
    label_start = 0
    for segment in strip._segments:
        if segment.style.meta.get("node") == node._id:
            break
        label_start += segment.cell_length
    content_origin = tree.content_region.x - tree.region.x
    return (
        content_origin
        + label_start
        + 2
        - tree.scroll_offset.x
        + node._label.cell_len / 2
    )


def test_m_move_mode_maps_level_to_after_then_right_to_child_and_undoes(
    tmp_path: Path,
):
    store = _fixture_store(tmp_path)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store, relocate_node=task_tree.relocate_node)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one(task_tree_tui.DragTree)
            tree.select_node(_node_for(tree, 4))
            await pilot.pause()

            source = _node_for(tree, 4)
            source_midpoint = _task_text_midpoint(tree, source.data)
            # Deliberately select from a right-side X; the eventual placement
            # must depend on the hovered candidate text, not this click.
            await pilot.click(
                tree,
                offset=(math.ceil(source_midpoint) + 2, source._line + 1),
            )
            await pilot.pause()
            await pilot.press("m")
            await pilot.pause()
            assert tree.keyboard_move_mode and tree.dragging

            target = _node_for(tree, 5)
            midpoint = _task_text_midpoint(tree, target.data)
            await pilot.hover(
                tree,
                offset=(math.ceil(midpoint) - 1, target._line + 1),
            )
            await pilot.pause()
            assert tree.drag_intent == task_tree_tui.DropIntent(4, None, after_id=5)
            assert tree.candidate_mode == tree.DROP_AFTER

            target = _node_for(tree, 5)
            midpoint = _task_text_midpoint(tree, target.data)
            child_x = math.ceil(midpoint)
            await pilot.hover(tree, offset=(child_x, target._line + 1))
            await pilot.pause()
            assert tree.drag_intent == task_tree_tui.DropIntent(4, 5)
            assert tree.candidate_mode == tree.DROP_CHILD

            await pilot.click(tree, offset=(child_x, target._line + 1))
            await pilot.pause()
            assert not tree.keyboard_move_mode and not tree.dragging
            with store.locked_data() as data:
                by_id = {node["id"]: node for node in data["nodes"]}
                assert data["root_ids"] == [1, 5]
                assert by_id[5]["children"] == [6, 4]

            await pilot.press("u")
            await pilot.pause()
            with store.locked_data() as data:
                assert data["root_ids"] == [1, 4, 5]

    asyncio.run(exercise())


@pytest.mark.parametrize("cancel_key", ["m", "escape"])
def test_m_move_mode_cancels_without_writing(tmp_path: Path, cancel_key: str):
    store = _fixture_store(tmp_path)
    with store.locked_data() as data:
        before = repr(data)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one(task_tree_tui.DragTree)
            tree.select_node(_node_for(tree, 4))
            await pilot.pause()
            await pilot.press("m")
            await pilot.pause()
            assert tree.keyboard_move_mode
            await pilot.press(cancel_key)
            await pilot.pause()
            assert not tree.keyboard_move_mode and not tree.dragging

    asyncio.run(exercise())
    with store.locked_data() as data:
        assert repr(data) == before


def test_move_mode_click_without_intent_stays_active_without_writing(tmp_path: Path):
    store = _fixture_store(tmp_path)
    with store.locked_data() as data:
        before = repr(data)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one(task_tree_tui.DragTree)
            tree.select_node(_node_for(tree, 4))
            await pilot.pause()
            await pilot.press("m")
            await pilot.pause()
            source = _node_for(tree, 4)
            await pilot.click(tree, offset=(3, source._line + 1))
            await pilot.pause()
            assert tree.keyboard_move_mode and tree.dragging
            assert tree.drag_intent is None

    asyncio.run(exercise())
    with store.locked_data() as data:
        assert repr(data) == before
