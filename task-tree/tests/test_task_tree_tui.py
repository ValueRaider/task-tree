"""Focused tests for the optional read-only Textual task-tree browser."""

from __future__ import annotations

import asyncio
from collections import Counter
import importlib.util
from pathlib import Path

import pytest


TEXTUAL = pytest.importorskip("textual")

TEST_DIR = Path(__file__).resolve().parent
SKILL_DIR = TEST_DIR.parent
SCRIPTS_DIR = SKILL_DIR / "scripts"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


task_tree = _load_module("task_tree_for_tui_tests", SCRIPTS_DIR / "task_tree.py")
task_tree_tui = _load_module("task_tree_tui_for_tests", SCRIPTS_DIR / "task_tree_tui.py")


def _node(node_id: int, summary: str, *, children=(), status="not_started"):
    return {
        "id": node_id,
        "children": list(children),
        "summary": summary,
        "body": f"Details for {summary}",
        "status": status,
        "closeout_reviewed": False,
        "files_dir": None,
        "events": {},
    }


def _fixture_store(tmp_path: Path):
    """Create a valid tree with an active branch and an unrelated branch."""

    store = task_tree.TaskTreeStore(str(tmp_path / "tree.json"))
    with store.locked_data(write=True) as data:
        data.update(
            {
                "schema_version": 2,
                "next_id": 7,
                "active_id": 3,
                "root_ids": [1, 5],
                "nodes": [
                    _node(1, "Active root", children=[2], status="in_progress"),
                    _node(2, "Active parent", children=[3], status="in_progress"),
                    _node(3, "Active task", children=[4], status="in_progress"),
                    _node(4, "Active task child"),
                    _node(5, "Unrelated root", children=[6]),
                    _node(6, "Unrelated child"),
                ],
            }
        )
    return store


def _nodes_by_id(tree):
    nodes = {}

    def visit(node):
        if isinstance(node.data, int):
            nodes[node.data] = node
        for child in node.children:
            visit(child)

    visit(tree.root)
    return nodes


def _details_text(app):
    # ``render`` is the stable Widget API; avoid relying on Static internals.
    return str(app.query_one("#details").render())


def test_completed_task_label_uses_tick_marker():
    completed = _node(7, "Finished task", status="completed")

    assert task_tree_tui._node_label(completed, active_id=None) == "[✓] #7 Finished task"


def test_active_branch_is_expanded_and_active_task_selected(tmp_path):
    store = _fixture_store(tmp_path)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one("Tree")
            nodes = _nodes_by_id(tree)

            assert tree.cursor_node is not None
            assert tree.cursor_node.data == 3
            assert nodes[1].is_expanded
            assert nodes[2].is_expanded
            assert nodes[3].is_expanded
            assert nodes[5].is_collapsed

    asyncio.run(exercise())


def test_left_collapses_or_moves_to_parent_and_right_expands(tmp_path):
    store = _fixture_store(tmp_path)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one("Tree")
            nodes = _nodes_by_id(tree)

            assert tree.cursor_node is nodes[3]
            assert nodes[3].is_expanded

            await pilot.press("left")
            await pilot.pause()
            assert tree.cursor_node is nodes[3]
            assert nodes[3].is_collapsed
            assert 3 not in app._expanded_ids

            # Once collapsed, Left follows the conventional tree-navigation
            # behavior and moves the cursor to the durable parent.
            await pilot.press("left")
            await pilot.pause()
            assert tree.cursor_node is nodes[2]

            # A leaf also moves directly to its parent on Left.
            nodes[3].expand()
            tree.move_cursor(nodes[4])
            await pilot.pause()
            await pilot.press("left")
            await pilot.pause()
            assert tree.cursor_node is nodes[3]

            await pilot.press("left")
            await pilot.pause()
            assert tree.cursor_node is nodes[3]
            assert nodes[3].is_collapsed

            await pilot.press("right")
            await pilot.pause()
            assert tree.cursor_node is nodes[3]
            assert nodes[3].is_expanded
            assert 3 in app._expanded_ids

    asyncio.run(exercise())


def test_each_durable_task_is_rendered_exactly_once(tmp_path):
    store = _fixture_store(tmp_path)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one("Tree")
            rendered_ids = []

            def visit(node):
                if isinstance(node.data, int):
                    rendered_ids.append(node.data)
                for child in node.children:
                    visit(child)

            visit(tree.root)

            with store.locked_data() as data:
                expected_ids = {node["id"] for node in data["nodes"]}
            assert set(rendered_ids) == expected_ids
            assert Counter(rendered_ids) == Counter({node_id: 1 for node_id in expected_ids})

    asyncio.run(exercise())


def test_selecting_a_task_updates_details(tmp_path):
    store = _fixture_store(tmp_path)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one("Tree")
            nodes = _nodes_by_id(tree)

            tree.select_node(nodes[4])
            await pilot.pause()

            assert tree.cursor_node is not None
            assert tree.cursor_node.data == 4
            details = _details_text(app)
            assert "#4  Active task child" in details
            assert "Status: not_started" in details

    asyncio.run(exercise())


def test_long_details_pane_scrolls_with_keyboard_and_resets_on_selection(tmp_path):
    store = _fixture_store(tmp_path)
    with store.locked_data(write=True) as data:
        active_task = next(node for node in data["nodes"] if node["id"] == 3)
        active_task["body"] = "\n".join(f"Long body line {index}" for index in range(80))

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store)
        async with app.run_test(size=(80, 12)) as pilot:
            await pilot.pause()
            pane = app.query_one("#details-pane", task_tree_tui.VerticalScroll)
            tree = app.query_one("Tree")

            assert pane.max_scroll_y > 0
            assert pane.allow_vertical_scroll
            assert app.focused is tree

            # The pane is the next keyboard focus target after the tree.
            await pilot.press("tab")
            await pilot.pause()
            assert app.focused is pane

            await pilot.press("end")
            await pilot.pause()
            assert pane.scroll_y > 0
            await pilot.press("home")
            await pilot.pause()
            assert pane.scroll_y == 0

            await pilot.press("pagedown")
            await pilot.pause()
            assert pane.scroll_y > 0
            await pilot.press("home")
            await pilot.pause()
            assert pane.scroll_y == 0

            # Selecting a different task replaces the text and returns the
            # scroll container to its top, even after it was scrolled down.
            await pilot.press("end")
            await pilot.pause()
            assert pane.scroll_y > 0
            nodes = _nodes_by_id(tree)
            tree.select_node(nodes[5])
            await pilot.pause()
            assert pane.scroll_y == 0
            details = _details_text(app)
            assert "#5  Unrelated root" in details

    asyncio.run(exercise())
