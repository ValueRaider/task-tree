"""Focused tests for the Textual drag marker and drop seams."""

from __future__ import annotations

import asyncio
import importlib.util
import math
from pathlib import Path

import pytest
from rich.style import Style
from textual.events import MouseDown, MouseMove, MouseUp


pytest.importorskip("textual")

TEST_DIR = Path(__file__).resolve().parent
SCRIPTS_DIR = TEST_DIR.parent / "scripts"


def _load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


task_tree = _load_module("task_tree_for_tui_drag_tests", SCRIPTS_DIR / "task_tree.py")
task_tree_tui = _load_module(
    "task_tree_tui_for_drag_tests", SCRIPTS_DIR / "task_tree_tui.py"
)


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
    store = task_tree.TaskTreeStore(str(tmp_path / "tree.json"))
    with store.locked_data(write=True) as data:
        data.update(
            {
                "schema_version": 2,
                "next_id": 7,
                "active_id": 1,
                "root_ids": [1, 4, 5],
                "nodes": [
                    _node(1, "Root", children=[2]),
                    _node(2, "Source", children=[3]),
                    _node(3, "Source child"),
                    _node(4, "Other root"),
                    _node(5, "Target", children=[6]),
                    _node(6, "Target child"),
                ],
            }
        )
    return store


def _collapsed_drop_store(tmp_path: Path):
    """Create collapsed source/target branches for durable drop tests."""

    store = task_tree.TaskTreeStore(str(tmp_path / "collapsed-drop-tree.json"))
    with store.locked_data(write=True) as data:
        data.update(
            {
                "schema_version": 2,
                "next_id": 8,
                "active_id": 1,
                "root_ids": [1, 4, 5],
                "nodes": [
                    _node(1, "Unrelated root"),
                    _node(4, "Source", children=[7]),
                    _node(7, "Source child"),
                    _node(5, "Target", children=[6]),
                    _node(6, "Target child"),
                ],
            }
        )
    return store


def _leaf_destination_drop_store(tmp_path: Path):
    """Create a collapsed source branch and a true leaf destination."""

    store = task_tree.TaskTreeStore(str(tmp_path / "leaf-destination-drop-tree.json"))
    with store.locked_data(write=True) as data:
        data.update(
            {
                "schema_version": 2,
                "next_id": 8,
                "active_id": 1,
                "root_ids": [1, 4, 5],
                "nodes": [
                    _node(1, "Unrelated root"),
                    _node(4, "Source", children=[7]),
                    _node(7, "Source child"),
                    _node(5, "Leaf target"),
                ],
            }
        )
    return store


def _alignment_store(tmp_path: Path):
    store = task_tree.TaskTreeStore(str(tmp_path / "alignment-tree.json"))
    with store.locked_data(write=True) as data:
        data.update(
            {
                "schema_version": 2,
                "next_id": 6,
                "active_id": 2,
                "root_ids": [1, 5],
                "nodes": [
                    _node(1, "Expandable root", children=[2, 3]),
                    _node(2, "Nested leaf"),
                    _node(3, "Expandable sibling", children=[4]),
                    _node(4, "Expandable child"),
                    _node(5, "Root leaf"),
                ],
            }
        )
    return store


def _node_for(tree, task_id: int):
    return next(node for node in tree._tree_nodes.values() if node.data == task_id)


def _line_strip(tree, task_id: int):
    node = _node_for(tree, task_id)
    assert node._line >= 0
    return tree._render_line(node._line, 0, tree.size.width, tree.rich_style)


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


def _rendered_task_text_start(tree, task_id: int) -> int:
    node = _node_for(tree, task_id)
    strip = tree._render_line(
        node._line,
        0,
        max(tree.size.width, tree.virtual_size.width),
        tree.rich_style,
    )
    start = 0
    for segment in strip._segments:
        if segment.style.meta.get("node") == node._id:
            return start + 2
        start += segment.cell_length
    raise AssertionError(f"task node {task_id} has no rendered label")


def _label_styles(tree, task_id: int):
    node = _node_for(tree, task_id)
    return [
        segment.style
        for segment in _line_strip(tree, task_id)._segments
        if segment.style.meta.get("node") == node._id
    ]


def test_click_does_not_start_drag(tmp_path):
    store = _fixture_store(tmp_path)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one(task_tree_tui.DragTree)
            await pilot.click(tree, offset=(6, 0))
            assert not tree.dragging
            assert not tree.pending_drag
            assert tree.cursor_node is not None

    asyncio.run(exercise())


def test_leaf_slots_align_with_expandable_icons_and_keep_rows_stable(tmp_path):
    store = _alignment_store(tmp_path)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one(task_tree_tui.DragTree)
            assert _rendered_task_text_start(tree, 5) == _rendered_task_text_start(
                tree, 1
            )
            assert _rendered_task_text_start(tree, 2) == _rendered_task_text_start(
                tree, 3
            )

            leaf = _node_for(tree, 2)
            expandable = _node_for(tree, 3)
            nested_strip = _line_strip(tree, 2)
            assert any(
                segment.text == "─ "
                and segment.style.meta.get("node") == leaf._id
                for segment in nested_strip._segments
            )
            assert not leaf._allow_expand
            assert expandable._allow_expand
            sibling_strip = _line_strip(tree, 3)
            assert any(
                segment.style.meta.get("toggle")
                for segment in sibling_strip._segments
                if segment.style.meta.get("node") == expandable._id
            )

            identities = {
                node.data: node
                for node in tree._tree_nodes.values()
                if isinstance(node.data, int)
            }
            total_rows = len(tree._tree_lines)
            row_height = tree.size.height
            tree.start_drag(5)
            tree.set_drag_target(3, tree.DROP_CHILD)
            await pilot.pause()
            assert {
                node.data: node
                for node in tree._tree_nodes.values()
                if isinstance(node.data, int)
            } == identities
            assert len(tree._tree_lines) == total_rows
            assert tree.size.height == row_height

    asyncio.run(exercise())


def test_markers_preserve_metadata_and_support_all_intents(tmp_path):
    store = _fixture_store(tmp_path)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one(task_tree_tui.DragTree)
            tree.start_drag(4)

            tree.set_drag_target(5, tree.DROP_AFTER)
            await pilot.pause()
            assert tree.drag_intent == task_tree_tui.DropIntent(4, None, after_id=5)
            assert tree.candidate_mode == tree.DROP_AFTER
            assert any(style.underline for style in _label_styles(tree, 5))
            assert any(style.dim for style in _label_styles(tree, 4))

            strip = _line_strip(tree, 5)
            rendered_text = "".join(segment.text for segment in strip._segments)
            assert "drop preview" not in rendered_text
            assert "↑" not in rendered_text and "↓" not in rendered_text
            assert not any("drag_ghost" in segment.style.meta for segment in strip._segments)
            assert any(segment.style.meta.get("node") is not None for segment in strip._segments)

            tree.set_drag_target(5, tree.DROP_CHILD)
            await pilot.pause()
            assert tree.drag_intent == task_tree_tui.DropIntent(4, 5)
            assert tree.candidate_mode == tree.DROP_CHILD
            child_styles = _label_styles(tree, 5)
            assert any(style.reverse and style.bold for style in child_styles)
            assert not _node_for(tree, 5).is_expanded

            # BEFORE remains available through the programmatic seam, although
            # the direct horizontal gesture intentionally maps to AFTER.
            tree.set_drag_target(5, tree.DROP_BEFORE)
            assert tree.drag_intent == task_tree_tui.DropIntent(4, None, before_id=5)
            assert tree.candidate_mode == tree.DROP_BEFORE

    asyncio.run(exercise())


def test_candidate_changes_only_refresh_markers_and_keep_layout_stable(tmp_path):
    store = _fixture_store(tmp_path)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one(task_tree_tui.DragTree)
            tree.start_drag(4)
            await pilot.pause()

            identities = {
                node.data: node
                for node in tree._tree_nodes.values()
                if isinstance(node.data, int)
            }
            lines = {task_id: node._line for task_id, node in identities.items()}
            expanded = {task_id: node.is_expanded for task_id, node in identities.items()}
            total_lines = len(tree._tree_lines)
            scroll_y = tree.scroll_offset.y

            tree.set_drag_target(1, tree.DROP_AFTER)
            await pilot.pause()
            assert tree.drag_intent == task_tree_tui.DropIntent(4, None, after_id=1)
            assert {node.data: node for node in tree._tree_nodes.values() if isinstance(node.data, int)} == identities
            assert {task_id: node._line for task_id, node in identities.items()} == lines
            assert {task_id: node.is_expanded for task_id, node in identities.items()} == expanded
            assert len(tree._tree_lines) == total_lines
            assert tree.scroll_offset.y == scroll_y

            # Target 5 is collapsed but has a real child. CHILD must not
            # expand it or manufacture a row.
            tree.set_drag_target(5, tree.DROP_CHILD)
            await pilot.pause()
            assert tree.drag_intent == task_tree_tui.DropIntent(4, 5)
            assert not _node_for(tree, 5).is_expanded
            assert {node.data: node for node in tree._tree_nodes.values() if isinstance(node.data, int)} == identities
            assert {task_id: node._line for task_id, node in identities.items()} == lines
            assert {task_id: node.is_expanded for task_id, node in identities.items()} == expanded
            assert len(tree._tree_lines) == total_lines
            assert tree.scroll_offset.y == scroll_y
            assert any(style.reverse and style.bold for style in _label_styles(tree, 5))

    asyncio.run(exercise())


def test_durable_child_drop_expands_target_only_after_commit(tmp_path):
    store = _collapsed_drop_store(tmp_path)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store, relocate_node=task_tree.relocate_node)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one(task_tree_tui.DragTree)
            target = _node_for(tree, 5)
            source = _node_for(tree, 4)
            source_child = _node_for(tree, 7)

            assert target.is_collapsed
            assert source.is_collapsed
            assert source_child._line == -1

            tree.start_drag(4)
            tree.set_drag_target(5, tree.DROP_CHILD)
            await pilot.pause()
            # Preview is styling-only and does not expand the candidate.
            assert _node_for(tree, 5).is_collapsed
            assert _node_for(tree, 6)._line == -1

            tree.drop_drag()
            await pilot.pause()

            assert tree.drag_intent is None
            assert _node_for(tree, 5).is_expanded
            assert _node_for(tree, 6)._line >= 0
            assert _node_for(tree, 4).is_collapsed
            assert _node_for(tree, 4)._line >= 0
            assert _node_for(tree, 7)._line == -1
            assert tree.cursor_node is not None
            assert tree.cursor_node.data == 4

    asyncio.run(exercise())


def test_pilot_held_drag_child_drop_expands_leaf_destination_after_commit(tmp_path):
    store = _leaf_destination_drop_store(tmp_path)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store, relocate_node=task_tree.relocate_node)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one(task_tree_tui.DragTree)
            source = _node_for(tree, 4)
            target = _node_for(tree, 5)

            assert not target._allow_expand
            assert len(target.children) == 0
            assert source.is_collapsed
            assert _node_for(tree, 7)._line == -1

            source_offset = (10, source._line + 1)
            midpoint = _task_text_midpoint(tree, target.data)
            target_offset = (math.ceil(midpoint), target._line + 1)
            await pilot.mouse_down(tree, offset=source_offset)
            await pilot.hover(tree, offset=target_offset)
            await pilot.pause()
            assert tree.drag_intent == task_tree_tui.DropIntent(4, 5)

            await pilot.mouse_up(tree, offset=target_offset)
            await pilot.pause()

            destination = _node_for(tree, 5)
            moved_source = _node_for(tree, 4)
            assert destination._allow_expand
            assert destination.is_expanded
            assert 5 in app._expanded_ids
            assert moved_source._line >= 0
            assert _node_for(tree, 7)._line == -1
            with store.locked_data() as data:
                by_id = {node["id"]: node for node in data["nodes"]}
                assert by_id[5]["children"] == [4]

    asyncio.run(exercise())


@pytest.mark.parametrize("destination", ["leaf", "collapsed", "expanded"])
def test_click_dispatch_suppresses_drop_click_and_toggles_ordinary_click_once(
    tmp_path, destination
):
    """Exercise Textual dispatch, including MouseUp's trailing Click."""

    factory = (
        _leaf_destination_drop_store
        if destination == "leaf"
        else _collapsed_drop_store
    )
    store = factory(tmp_path)
    with store.locked_data(write=True) as data:
        # Keep the target row stable when the moved source is attached to it.
        data["root_ids"] = [1, 5, 4]

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store, relocate_node=task_tree.relocate_node)
        async with app.run_test(size=(100, 30)) as pilot:
            await pilot.pause()
            tree = app.query_one(task_tree_tui.DragTree)
            if destination == "expanded":
                _node_for(tree, 5).expand()
                await pilot.pause()

            toggles = []
            toggle = tree._toggle_node

            def track_toggle(node):
                toggles.append(node.data)
                return toggle(node)

            tree._toggle_node = track_toggle

            def post(event_type, point):
                x, y = point
                app.post_message(
                    event_type(
                        None, x, y, 0, 0, 1, False, False, False,
                        screen_x=x, screen_y=y,
                    )
                )

            source = _node_for(tree, 4)
            target = _node_for(tree, 5)
            source_point = (tree.region.x + 10, tree.region.y + source._line + 1)
            target_point = (
                tree.region.x + math.ceil(_task_text_midpoint(tree, 5)),
                tree.region.y + target._line + 1,
            )

            # Raw events enter App dispatch; terminal dispatch synthesizes Click
            # after MouseUp, unlike Pilot.mouse_up.
            post(MouseDown, source_point)
            await pilot.pause()
            post(MouseMove, target_point)
            await pilot.pause()
            assert tree.drag_intent == task_tree_tui.DropIntent(4, 5)
            post(MouseUp, target_point)
            await pilot.pause()
            await pilot.pause()

            target = _node_for(tree, 5)
            moved_source = _node_for(tree, 4)
            assert toggles == []
            assert target.is_expanded
            assert moved_source.parent is target
            with store.locked_data() as data:
                by_id = {node["id"]: node for node in data["nodes"]}
                assert 4 in by_id[5]["children"]
            assert tree.cursor_node is not None
            assert tree.cursor_node.data == 4

            # A normal click is dispatched once by Textual to Tree._on_click.
            toggles.clear()
            target_point = (
                tree.region.x + math.ceil(_task_text_midpoint(tree, 5)),
                tree.region.y + target._line + 1,
            )
            post(MouseDown, target_point)
            await pilot.pause()
            post(MouseUp, target_point)
            await pilot.pause()
            assert toggles == [5]
            assert not _node_for(tree, 5).is_expanded

            post(MouseDown, target_point)
            await pilot.pause()
            post(MouseUp, target_point)
            await pilot.pause()
            assert toggles == [5, 5]
            assert _node_for(tree, 5).is_expanded

    asyncio.run(exercise())


def test_durable_sibling_after_drop_preserves_expansion_state(tmp_path):
    store = _collapsed_drop_store(tmp_path)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store, relocate_node=task_tree.relocate_node)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one(task_tree_tui.DragTree)
            before = {
                task_id: _node_for(tree, task_id).is_expanded
                for task_id in (1, 4, 5)
            }

            tree.start_drag(4)
            tree.set_drag_target(5, tree.DROP_AFTER)
            await pilot.pause()
            assert {
                task_id: _node_for(tree, task_id).is_expanded
                for task_id in (1, 4, 5)
            } == before

            tree.drop_drag()
            await pilot.pause()
            assert {
                task_id: _node_for(tree, task_id).is_expanded
                for task_id in (1, 4, 5)
            } == before
            assert _node_for(tree, 7)._line == -1

    asyncio.run(exercise())


def test_pilot_held_drag_level_maps_to_after_and_persists_then_undoes(tmp_path):
    store = _fixture_store(tmp_path)
    calls = []

    def relocate(*args, **kwargs):
        calls.append((args, kwargs))
        return task_tree.relocate_node(*args, **kwargs)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store, relocate_node=relocate)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one(task_tree_tui.DragTree)
            source = _node_for(tree, 4)
            target = _node_for(tree, 5)
            source_offset = (10, source._line + 1)
            midpoint = _task_text_midpoint(tree, target.data)
            target_offset = (math.ceil(midpoint) - 1, target._line + 1)
            await pilot.mouse_down(tree, offset=source_offset)
            await pilot.hover(tree, offset=target_offset)
            await pilot.pause()
            assert tree.drag_intent == task_tree_tui.DropIntent(4, None, after_id=5)
            rendered_intent = tree.drag_intent
            await pilot.mouse_up(tree, offset=target_offset)
            await pilot.pause()

            assert app._last_dropped_intent == rendered_intent
            assert len(calls) == 1
            with store.locked_data() as data:
                by_id = {node["id"]: node for node in data["nodes"]}
                assert data["root_ids"] == [1, 5, 4]
                assert by_id[5]["children"] == [6]

            await pilot.press("u")
            await pilot.pause()
            with store.locked_data() as data:
                assert data["root_ids"] == [1, 4, 5]

    asyncio.run(exercise())


def test_pilot_held_drag_right_two_cells_maps_to_child(tmp_path):
    store = _fixture_store(tmp_path)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one(task_tree_tui.DragTree)
            source = _node_for(tree, 4)
            target = _node_for(tree, 5)
            await pilot.mouse_down(tree, offset=(10, source._line + 1))
            midpoint = _task_text_midpoint(tree, target.data)
            await pilot.hover(tree, offset=(math.ceil(midpoint), target._line + 1))
            await pilot.pause()
            assert tree.drag_intent == task_tree_tui.DropIntent(4, 5)
            tree.cancel_drag()

    asyncio.run(exercise())


def test_invalid_targets_escape_and_outside_release_clear_without_store_write(tmp_path):
    store = _fixture_store(tmp_path)
    with store.locked_data() as data:
        before = repr(data)

    async def exercise():
        app = task_tree_tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one(task_tree_tui.DragTree)
            tree.start_drag(2)
            tree.set_drag_target(2, tree.DROP_CHILD)
            assert tree.drag_intent is None
            assert tree.candidate_task_id is None
            assert tree.candidate_mode is None
            tree.set_drag_target(3, tree.DROP_CHILD)
            assert tree.drag_intent is None
            tree.set_drag_target(5, tree.DROP_CHILD)
            assert tree.drag_intent is not None
            await pilot.press("escape")
            await pilot.pause()
            assert not tree.dragging
            assert tree.drag_intent is None
            assert tree.candidate_mode is None

            tree.start_drag(3)
            tree.set_drag_target(5, tree.DROP_CHILD)
            outside = MouseUp(tree, 0, 0, 0, 0, 1, False, False, False, style=Style())
            tree._press_position = (0, 0)
            tree.on_mouse_up(outside)
            await pilot.pause()
            assert not tree.dragging
            assert app._last_dropped_intent is None

    asyncio.run(exercise())
    with store.locked_data() as data:
        assert repr(data) == before
