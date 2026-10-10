"""Literal task search, modal key routing, and session-local preferences."""

from __future__ import annotations

import asyncio
import copy
import importlib.util
from pathlib import Path

import pytest


pytest.importorskip("textual")

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"


def _load_module(name, filename):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS_DIR / filename)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


task_tree = _load_module("task_tree_for_search_tests", "task_tree.py")
tui = _load_module("task_tree_tui_for_search_tests", "task_tree_tui.py")


def _node(node_id, summary, *, children=(), status="not_started", body=""):
    return {
        "id": node_id,
        "summary": summary,
        "children": list(children),
        "status": status,
        "body": body,
        "closeout_reviewed": False,
        "files_dir": None,
        "events": {},
    }


def _fixture_store(tmp_path):
    store = task_tree.TaskTreeStore(str(tmp_path / "tree.json"))
    with store.locked_data(write=True) as data:
        data.update({
            "schema_version": 2,
            "next_id": 9,
            "active_id": 1,
            "root_ids": [1, 4, 7],
            # Deliberately not in traversal order.
            "nodes": [
                _node(8, "Notes", body="Body-only Deploy text"),
                _node(7, "deploy lower", children=[8]),
                _node(5, "Deploy nested"),
                _node(4, "Deploy completed", children=[5], status="completed"),
                _node(2, "Deploy service"),
                _node(1, "Start", children=[2], status="in_progress"),
            ],
        })
    return store


def _read(store):
    with store.locked_data() as data:
        return copy.deepcopy(data)


def _tree_node(app, task_id):
    return app.query_one(tui.DragTree)._task_node(task_id)


async def _search(app, pilot, query):
    await pilot.press("/")
    await pilot.pause()
    assert isinstance(app.screen, tui.SearchInputScreen)
    app.screen.query_one(tui.Input).value = query
    await pilot.press("enter")
    await pilot.pause()


async def _pause_for_preview(pilot):
    await pilot.pause(tui.SearchInputScreen.PREVIEW_DELAY + 0.1)


class _FakeTimer:
    def __init__(self, delay, callback):
        self.delay = delay
        self.callback = callback
        self.stopped = False

    def stop(self):
        self.stopped = True


def test_search_debounce_resets_on_edits_and_ignores_stale_callbacks(monkeypatch):
    previews = []
    timers = []
    screen = tui.SearchInputScreen("", previews.append)
    input_widget = tui.Input()

    def set_timer(delay, callback):
        timer = _FakeTimer(delay, callback)
        timers.append(timer)
        return timer

    monkeypatch.setattr(screen, "set_timer", set_timer)
    screen.on_input_changed(tui.Input.Changed(input_widget, ""))
    assert timers == []  # Initial value is not an edit.
    for value in ["D", "Deploy", "Deplo", ""]:
        screen.on_input_changed(tui.Input.Changed(input_widget, value))
        assert timers[-1].delay == 0.5
        assert previews == []
    assert all(timer.stopped for timer in timers[:-1])
    assert not timers[-1].stopped
    # Model callbacks that were already queued before their timer was stopped.
    for timer in timers[:-1]:
        timer.callback()
    assert previews == []
    timers[-1].callback()
    assert previews == [""]
    assert screen._preview_timer is None


@pytest.mark.parametrize("finish", ["submit", "cancel", "unmount"])
def test_search_debounce_is_cancelled_when_leaving_input(monkeypatch, finish):
    previews = []
    dismissed = []
    screen = tui.SearchInputScreen("", previews.append)
    input_widget = tui.Input()
    timer = _FakeTimer(0.5, None)

    def set_timer(delay, callback):
        timer.callback = callback
        return timer

    monkeypatch.setattr(screen, "set_timer", set_timer)
    monkeypatch.setattr(screen, "dismiss", dismissed.append)
    screen.on_input_changed(tui.Input.Changed(input_widget, "Deploy"))
    if finish == "submit":
        screen.on_input_submitted(tui.Input.Submitted(input_widget, "Deploy"))
        assert dismissed == ["Deploy"]
    elif finish == "cancel":
        screen.action_cancel()
        assert dismissed == [None]
    else:
        screen.on_unmount()
    assert timer.stopped
    assert screen._preview_timer is None
    timer.callback()
    screen.on_input_changed(tui.Input.Changed(input_widget, "late edit"))
    assert previews == []
    assert screen._preview_timer is None


def test_debounced_search_waits_for_idle_but_enter_applies_immediately(tmp_path):
    store = _fixture_store(tmp_path)
    before = _read(store)

    async def exercise():
        app = tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("/")
            await pilot.pause()
            screen = app.screen
            input_widget = screen.query_one(tui.Input)
            previews = []
            preview = screen._preview

            def record_preview(query):
                previews.append(query)
                preview(query)

            screen._preview = record_preview
            input_widget.value = "Deploy service"
            await pilot.pause(0.1)
            assert previews == []
            assert app._selected_id == 1
            input_widget.value = "Deploy nested"
            await pilot.pause(0.1)
            assert previews == []
            await _pause_for_preview(pilot)
            assert previews == ["Deploy nested"]
            assert app._selected_id == 5
            assert app.focused is input_widget
            input_widget.value = "deploy lower"
            await pilot.pause(0.1)
            assert app._search_query == "Deploy nested"
            await pilot.press("enter")
            await pilot.pause()
            assert app._search_query == "deploy lower"
            assert app._selected_id == 7
            assert app.focused is app.query_one(tui.DragTree)
            await _pause_for_preview(pilot)
            assert previews == ["Deploy nested"]
            assert app._selected_id == 7
            # Cancel a pending edit, then start a different search before its
            # deadline; the old callback must not affect the new session.
            await pilot.press("/")
            await pilot.pause()
            app.screen.query_one(tui.Input).value = "Deploy nested"
            await pilot.pause(0.1)
            await pilot.press("escape", "/")
            await pilot.pause()
            assert app._search_query == "deploy lower"
            assert app._selected_id == 7
            await _pause_for_preview(pilot)
            assert app._search_query == "deploy lower"
            assert app._selected_id == 7
            await pilot.press("escape")
    asyncio.run(exercise())
    assert _read(store) == before


def test_literal_matching_case_body_states_and_durable_order(tmp_path):
    data = _read(_fixture_store(tmp_path))
    settings = tui.SearchSettings()
    assert tui._task_ids_in_order(data) == [1, 2, 4, 5, 7, 8]
    assert tui._search_task_ids(data, "Deploy", settings) == [2, 4, 5]
    assert tui._search_task_ids(data, "deploy", settings) == [7]
    settings.case_sensitive = False
    assert tui._search_task_ids(data, "deploy", settings) == [2, 4, 5, 7]
    settings.include_body = True
    assert tui._search_task_ids(data, "deploy", settings) == [2, 4, 5, 7, 8]
    settings.ignored_statuses.add("completed")
    assert tui._search_task_ids(data, "deploy", settings) == [2, 5, 7, 8]
    assert tui._search_task_ids(data, "", settings) == []
    assert tui._search_task_ids(data, ".*", settings) == []
    data["nodes"][0]["summary"] = "Literal [x].* Straße"
    assert tui._search_task_ids(data, "[x].*", settings) == [8]
    assert tui._search_task_ids(data, "STRASSE", settings) == [8]


def test_search_reveals_collapsed_matches_wraps_and_preserves_store(tmp_path):
    store = _fixture_store(tmp_path)
    before = _read(store)

    async def exercise():
        app = tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            assert not _tree_node(app, 4).is_expanded
            await _search(app, pilot, "Deploy")
            assert app._search_matches == [2, 4, 5]
            assert app._selected_id == 2
            assert app._status == "Search 'Deploy': 1/3"
            assert _tree_node(app, 2).label.spans
            assert not _tree_node(app, 7).label.spans
            await pilot.press("n")
            await pilot.pause()
            assert app._selected_id == 4
            await pilot.press("n")
            await pilot.pause()
            assert app._selected_id == 5
            assert _tree_node(app, 4).is_expanded
            assert 4 in app._expanded_ids
            assert app.query_one(tui.DragTree).cursor_node.data == 5
            assert "#5" in str(app.query_one("#details").render())
            assert app._status == "Search 'Deploy': 3/3"
            await pilot.press("n")
            await pilot.pause()
            assert app._selected_id == 2
            await pilot.press("N")
            await pilot.pause()
            assert app._selected_id == 5
            # A nonmatching cursor also searches from its durable position.
            app.query_one(tui.DragTree).move_cursor(_tree_node(app, 7))
            await pilot.pause()
            await pilot.press("N")
            await pilot.pause()
            assert app._selected_id == 5
            await _search(app, pilot, "missing")
            assert app._selected_id == 5
            assert app._status == "No matches for 'missing'"
            await pilot.press("n", "N")
            await pilot.pause()
            assert app._selected_id == 5
            await _search(app, pilot, "")
            assert app._search_matches == []
            assert app._status == "Search cleared"
            assert not _tree_node(app, 2).label.spans
    asyncio.run(exercise())
    assert _read(store) == before


def test_configuration_has_own_command_bar_and_blocks_normal_keys(tmp_path):
    store = _fixture_store(tmp_path)
    before = _read(store)

    async def exercise():
        app = tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _search(app, pilot, "Deploy")
            selected = app._selected_id
            expanded = set(app._expanded_ids)
            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, tui.SearchConfigScreen)
            assert "Case: sensitive" in str(app.screen.query_one(tui.Static).render())
            await pilot.press("c", "b", "1")
            await pilot.pause()
            hints = str(app.screen.query_one(tui.Static).render())
            assert "Case: insensitive" in hints
            assert "Bodies: on" in hints
            assert "completed: on" in hints
            # No tree navigation, reload, quit, undo, move, or nested modes.
            await pilot.press("down", "right", "left", "space", "q", "r", "u", "m", "n", "/")
            await pilot.pause()
            tree = app.query_one(tui.DragTree)
            await pilot.click(offset=(tree.region.x + 10, tree.content_region.y))
            await pilot.pause()
            assert isinstance(app.screen, tui.SearchConfigScreen)
            assert app._selected_id == selected
            assert app._expanded_ids == expanded
            assert not app.query_one(tui.DragTree).dragging
            await pilot.press("escape")
            await pilot.pause()
            assert app._selected_id == selected
            assert app._search_matches == [2, 5, 7, 8]
            assert app.search_settings.ignored_statuses == {"completed"}
            assert app._status == "Search 'Deploy': 1/4"
            await pilot.press("n")
            await pilot.pause()
            assert app._selected_id == 5
            assert _tree_node(app, 4).is_expanded
            await pilot.press("n", "n")
            await pilot.pause()
            assert app._selected_id == 8
            assert _tree_node(app, 7).is_expanded
            assert "Body-only Deploy text" in str(app.query_one("#details").render())
            # Settings survive reload, but not a new app instance.
            await pilot.press("r")
            await pilot.pause()
            assert not app.search_settings.case_sensitive
            assert app._search_matches == [2, 5, 7, 8]
    asyncio.run(exercise())
    assert _read(store) == before
    assert tui.TaskTreeApp(store).search_settings == tui.SearchSettings()


@pytest.mark.parametrize("exit_key", ["escape", "enter", "s"])
def test_every_state_can_be_toggled_and_config_exited(tmp_path, exit_key):
    store = _fixture_store(tmp_path)

    async def exercise():
        app = tui.TaskTreeApp(store)
        async with app.run_test(size=(60, 20)) as pilot:
            await pilot.pause()
            await pilot.press("s")
            await pilot.pause()
            for key, status in tui.SearchConfigScreen.STATUS_KEYS.items():
                await pilot.press(key)
                await pilot.pause()
                assert status in app.search_settings.ignored_statuses
                assert f"{status}: on" in str(app.screen.query_one(tui.Static).render())
                await pilot.press(key)
                await pilot.pause()
                assert status not in app.search_settings.ignored_statuses
            bar = app.screen.query_one("#search-config")
            assert bar.region.bottom == app.screen.region.bottom
            assert bar.region.height >= 4
            await pilot.press("c", "c", "b", "b", exit_key)
            await pilot.pause()
            assert not isinstance(app.screen, tui.SearchConfigScreen)
            assert app.search_settings == tui.SearchSettings()
    asyncio.run(exercise())


def test_matching_order_is_updated_after_relocation_and_undo(tmp_path):
    store = _fixture_store(tmp_path)

    async def exercise():
        app = tui.TaskTreeApp(store, relocate_node=task_tree.relocate_node)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _search(app, pilot, "Deploy")
            app.handle_drag_drop(tui.DropIntent(2, None, after_id=7))
            await pilot.pause()
            assert app._search_matches == [4, 5, 2]
            assert app._status.startswith("Moved #2")
            await pilot.press("n")
            await pilot.pause()
            assert app._selected_id == 4
            assert app._status == "Search 'Deploy': 1/3"
            await pilot.press("u")
            await pilot.pause()
            assert app._search_matches == [2, 4, 5]
            assert app._selected_id == 2
            await pilot.press("n")
            await pilot.pause()
            assert app._selected_id == 4
    asyncio.run(exercise())


def test_search_input_is_plain_text_and_escape_preserves_previous_search(tmp_path):
    store = _fixture_store(tmp_path)

    async def exercise():
        app = tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _search(app, pilot, "Deploy")
            selected = app._selected_id
            await pilot.press("/")
            await pilot.pause()
            input_widget = app.screen.query_one(tui.Input)
            assert input_widget.value == "Deploy"
            assert input_widget.selection.start == 0
            assert input_widget.selection.end == len("Deploy")
            input_widget.value = ""
            await pilot.press(*list("sqmrunnN/[x].*"))
            await pilot.pause()
            assert input_widget.value == "sqmrunnN/[x].*"
            assert isinstance(app.screen, tui.SearchInputScreen)
            assert app._selected_id == selected
            assert not app.query_one(tui.DragTree).dragging
            await pilot.press("escape")
            await pilot.pause()
            assert app._search_query == "Deploy"
            assert app._search_matches == [2, 4, 5]
            assert app._selected_id == selected
            assert app.focused is app.query_one(tui.DragTree)
            await _search(app, pilot, "[x].*")
            assert app._status == "No matches for '[x].*'"
            assert str(app.query_one("#status").render()) == app._status
    asyncio.run(exercise())


def test_incremental_typing_and_deleting_updates_matches_without_enter(tmp_path):
    store = _fixture_store(tmp_path)
    before = _read(store)

    async def exercise():
        app = tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            tree = app.query_one(tui.DragTree)
            original_nodes = dict(tree._tree_nodes)
            await pilot.press("/")
            await pilot.pause()
            input_widget = app.screen.query_one(tui.Input)
            for index, letter in enumerate("Deploy"):
                await pilot.press(letter)
                await _pause_for_preview(pilot)
                assert app._search_query == "Deploy"[:index + 1]
                assert app._search_matches == [2, 4, 5]
                assert app._selected_id == 2
                assert app._status.endswith("1/3")
                assert app.focused is input_widget
            await pilot.press("space", "n")
            await _pause_for_preview(pilot)
            assert app._search_matches == [5]
            assert app._selected_id == 5
            assert tree.cursor_node.data == 5
            assert _tree_node(app, 4).is_expanded
            assert "#5" in str(app.query_one("#details").render())
            assert app.focused is input_widget
            # Deleting broadens the search from its original anchor, not task 5.
            await pilot.press("backspace")
            await _pause_for_preview(pilot)
            assert app._search_query == "Deploy "
            assert app._search_matches == [2, 4, 5]
            assert app._selected_id == 2
            await pilot.press("n", "x")
            await _pause_for_preview(pilot)
            assert app._search_matches == []
            assert app._selected_id == 1
            assert app._status == "No matches for 'Deploy nx'"
            await pilot.press("backspace")
            await _pause_for_preview(pilot)
            assert app._selected_id == 5
            assert app._status == "Search 'Deploy n': 1/1"
            # Live edits do not rebuild the tree or steal input focus.
            assert dict(tree._tree_nodes) == original_nodes
            assert app.focused is input_widget
            await pilot.press("enter")
            await pilot.pause()
            assert not isinstance(app.screen, tui.SearchInputScreen)
            assert app._selected_id == 5
            assert app._search_query == "Deploy n"
            assert app.focused is tree
    asyncio.run(exercise())
    assert _read(store) == before


def test_incremental_escape_restores_search_selection_and_expansion(tmp_path):
    store = _fixture_store(tmp_path)
    before = _read(store)

    async def exercise():
        app = tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _search(app, pilot, "Deploy")
            original_status = app._status
            original_expansion = set(app._expanded_ids)
            await pilot.press("/")
            await pilot.pause()
            input_widget = app.screen.query_one(tui.Input)
            input_widget.value = "deploy lower"
            await _pause_for_preview(pilot)
            assert app._selected_id == 7
            input_widget.value = "Deploy nested"
            await _pause_for_preview(pilot)
            assert app._selected_id == 5
            assert _tree_node(app, 4).is_expanded
            assert app._search_matches == [5]
            await pilot.press("escape")
            await pilot.pause()
            assert app._selected_id == 2
            assert app.query_one(tui.DragTree).cursor_node.data == 2
            assert app._search_query == "Deploy"
            assert app._search_matches == [2, 4, 5]
            assert app._expanded_ids == original_expansion
            assert not _tree_node(app, 4).is_expanded
            assert app._status == original_status
            assert _tree_node(app, 2).label.spans
            assert not _tree_node(app, 7).label.spans
    asyncio.run(exercise())
    assert _read(store) == before


def test_incremental_search_uses_case_body_and_ignored_state_settings(tmp_path):
    store = _fixture_store(tmp_path)
    before = _read(store)

    async def exercise():
        app = tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("s", "c", "b", "1", "escape", "/")
            await pilot.pause()
            input_widget = app.screen.query_one(tui.Input)
            await pilot.press(*list("deploy"))
            await _pause_for_preview(pilot)
            assert app._search_matches == [2, 5, 7, 8]
            input_widget.value = "body-only"
            await _pause_for_preview(pilot)
            assert app._search_matches == [8]
            assert app._selected_id == 8
            assert _tree_node(app, 7).is_expanded
            assert app.query_one(tui.DragTree).cursor_node.data == 8
            assert "Body-only Deploy text" in str(app.query_one("#details").render())
            assert app.focused is input_widget
            await pilot.press("escape")
            await pilot.pause()
            assert app._search_query == ""
            assert app._selected_id == 1
            assert not _tree_node(app, 7).is_expanded
            assert app.search_settings.ignored_statuses == {"completed"}
    asyncio.run(exercise())
    assert _read(store) == before


@pytest.mark.parametrize("finish_key", ["enter", "escape"])
def test_incremental_delete_to_empty_clears_preview_and_rapid_edits_settle(
    tmp_path, finish_key
):
    store = _fixture_store(tmp_path)

    async def exercise():
        app = tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            await pilot.press("/")
            await pilot.pause()
            input_widget = app.screen.query_one(tui.Input)
            # Pasted/programmatic edits are Changed events too; no Enter needed.
            for query in ["Deploy nested", "deploy lower", "missing", "Deploy service"]:
                input_widget.value = query
            await _pause_for_preview(pilot)
            assert app._search_query == "Deploy service"
            assert app._selected_id == 2
            assert app._search_matches == [2]
            await pilot.press("end", *(["backspace"] * len(input_widget.value)))
            await _pause_for_preview(pilot)
            assert app._search_query == ""
            assert app._search_matches == []
            assert app._selected_id == 1
            assert app._status == "Search cleared"
            assert not _tree_node(app, 2).label.spans
            assert app.focused is input_widget
            await pilot.press(finish_key)
            await pilot.pause()
            assert app._search_query == ""
            assert app._selected_id == 1
            assert not isinstance(app.screen, tui.SearchInputScreen)
            assert app._search_snapshot is None
    asyncio.run(exercise())


def test_search_and_configuration_do_not_interrupt_a_move(tmp_path):
    store = _fixture_store(tmp_path)
    before = _read(store)

    async def exercise():
        app = tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _search(app, pilot, "Deploy")
            await pilot.press("m")
            await pilot.pause()
            tree = app.query_one(tui.DragTree)
            assert tree.keyboard_move_mode
            selected = app._selected_id
            await pilot.press("/", "s", "n", "N")
            await pilot.pause()
            assert not isinstance(app.screen, (tui.SearchInputScreen, tui.SearchConfigScreen))
            assert tree.keyboard_move_mode
            assert app._selected_id == selected
            await pilot.press("escape")
            await pilot.pause()
            assert not tree.keyboard_move_mode
            assert app._status == "Search 'Deploy': 1/3"
            await pilot.press("s")
            await pilot.pause()
            assert isinstance(app.screen, tui.SearchConfigScreen)
    asyncio.run(exercise())
    assert _read(store) == before


def test_reload_recomputes_matches_and_empty_tree_can_search(tmp_path):
    store = _fixture_store(tmp_path)

    async def exercise():
        app = tui.TaskTreeApp(store)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _search(app, pilot, "Deploy")
            with store.locked_data(write=True) as data:
                for node in data["nodes"]:
                    node["summary"] = "Changed"
            await pilot.press("r")
            await pilot.pause()
            assert app._search_matches == []
            assert app._status == "No matches for 'Deploy'"
        empty = task_tree.TaskTreeStore(str(tmp_path / "empty.json"))
        app = tui.TaskTreeApp(empty)
        async with app.run_test() as pilot:
            await pilot.pause()
            await _search(app, pilot, "anything")
            assert app._selected_id is None
            assert app._status == "No matches for 'anything'"
            await pilot.press("s", "c", "escape")
            await pilot.pause()
            assert not app.search_settings.case_sensitive
    asyncio.run(exercise())
