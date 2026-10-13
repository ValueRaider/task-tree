"""Interactive Textual interface for a task-tree store.

This module is deliberately imported only by the ``tui`` command.  Textual is
an optional dependency, so ordinary task-tree CLI commands remain usable in
minimal installations. Relocations are committed through the store's normal
locked mutation path rather than by editing the backing JSON directly.
"""

from dataclasses import dataclass, field
import copy
from typing import Any, Callable, Dict, Optional, Set

from textual.app import App, ComposeResult
from textual.containers import Horizontal, Vertical, VerticalScroll
from textual.events import Click, MouseDown, MouseMove, MouseUp, Resize
from textual.screen import ModalScreen
from textual.timer import Timer
from textual.widgets import Footer, Header, Input, Static, Tree
from textual.widgets.tree import UnknownNodeID
from rich.style import Style
from rich.text import Text

import task_tree_notepad as notepad_storage


NARROW_LAYOUT_BASE_COLUMNS = 90
NARROW_LAYOUT_COLUMNS_PER_LEVEL = 8


STATUS_MARKERS = {
    "not_started": "[ ]",
    "in_progress": "[~]",
    "completed": "[✓]",
    "aborted": "[-]",
    "impossible": "[!]",
}


@dataclass
class SearchSettings:
    """Session-local search preferences; never written to the task store."""

    case_sensitive: bool = True
    include_body: bool = False
    ignored_statuses: Set[str] = field(default_factory=set)


@dataclass
class SearchSnapshot:
    """The view to restore if an incremental search is cancelled."""

    query: str
    selected_id: Optional[int]
    expanded_ids: Set[int]
    status: str


def _task_ids_in_order(data: Dict[str, Any]) -> list[int]:
    """Depth-first durable order, independent of the visible expansion state."""

    by_id = _node_index(data)
    ordered = []
    pending = list(reversed(data.get("root_ids", [])))
    while pending:
        node_id = pending.pop()
        ordered.append(node_id)
        pending.extend(reversed(by_id[node_id]["children"]))
    return ordered


def _search_task_ids(
    data: Dict[str, Any], query: str, settings: SearchSettings
) -> list[int]:
    """Match literal text in tree order, including collapsed descendants."""

    if not query:
        return []
    needle = query if settings.case_sensitive else query.casefold()
    by_id = _node_index(data)
    matches = []
    for node_id in _task_ids_in_order(data):
        node = by_id[node_id]
        # Ignoring a parent must not exclude otherwise eligible children.
        if node["status"] in settings.ignored_statuses:
            continue
        fields = [node["summary"]]
        if settings.include_body:
            fields.append(node.get("body") or "")
        if any(
            needle in (value if settings.case_sensitive else value.casefold())
            for value in fields
        ):
            matches.append(node_id)
    return matches


class SearchInputScreen(ModalScreen[Optional[str]]):
    """A bottom command bar whose typed keys cannot reach normal bindings."""

    DEFAULT_CSS = """
    SearchInputScreen { align: left bottom; background: transparent; }
    #search-command { height: auto; background: $surface; }
    #search-input { height: 3; }
    #search-input-hints { height: auto; padding: 0 1; }
    """
    BINDINGS = [("escape", "cancel", "Cancel")]
    PREVIEW_DELAY = 0.5

    def __init__(self, query: str, preview: Callable[[str], None]) -> None:
        super().__init__()
        self._initial_query = query
        self._last_input_value = query
        self._preview = preview
        self._preview_timer: Optional[Timer] = None
        self._preview_generation = 0
        self._finished = False

    def compose(self) -> ComposeResult:
        with Vertical(id="search-command"):
            yield Input(
                self._initial_query,
                placeholder="/ Search (literal text)",
                id="search-input",
            )
            yield Static(
                "Search after 500 ms idle · Enter Apply now · Esc Cancel",
                id="search-input-hints",
            )

    def on_mount(self) -> None:
        self.query_one(Input).focus()

    def on_input_changed(self, event: Input.Changed) -> None:
        event.stop()
        # Input also emits Changed for its initial value, before any editing.
        if not self._finished and event.value != self._last_input_value:
            self._last_input_value = event.value
            self._stop_pending_preview()
            generation = self._preview_generation
            self._preview_timer = self.set_timer(
                self.PREVIEW_DELAY,
                lambda: self._preview_if_current(generation, event.value),
            )

    def _stop_pending_preview(self) -> None:
        self._preview_generation += 1
        if self._preview_timer is not None:
            self._preview_timer.stop()
            self._preview_timer = None

    def _preview_if_current(self, generation: int, query: str) -> None:
        # A stopped timer may already have queued its callback. Ignore stale
        # edits and callbacks from a screen that has been dismissed.
        if not self._finished and generation == self._preview_generation:
            self._preview_timer = None
            self._preview(query)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        self._finished = True
        self._stop_pending_preview()
        # The app applies the submitted value synchronously on dismissal.
        self.dismiss(event.value)

    def action_cancel(self) -> None:
        self._finished = True
        self._stop_pending_preview()
        self.dismiss(None)

    def on_unmount(self) -> None:
        self._finished = True
        self._stop_pending_preview()


class SearchConfigScreen(ModalScreen[None]):
    """Immediate toggles in a modal command bar, not commands in the query."""

    DEFAULT_CSS = """
    SearchConfigScreen { align: left bottom; background: transparent; }
    #search-config { height: auto; padding: 0 1; background: $surface; }
    """
    STATUS_KEYS = {
        "1": "completed",
        "2": "aborted",
        "3": "impossible",
        "4": "not_started",
        "5": "in_progress",
    }
    BINDINGS = [
        ("c", "toggle_case", "Case"),
        ("b", "toggle_body", "Bodies"),
        *[
            (key, f"toggle_status('{status}')", status)
            for key, status in STATUS_KEYS.items()
        ],
        ("escape,enter,s", "done", "Back"),
    ]

    def __init__(self, settings: SearchSettings) -> None:
        super().__init__()
        self.settings = settings

    def compose(self) -> ComposeResult:
        yield Static(self._hints(), id="search-config")

    def _hints(self) -> Text:
        case = "sensitive" if self.settings.case_sensitive else "insensitive"
        body = "on" if self.settings.include_body else "off"
        ignores = [
            f"{key} {status}: {'on' if status in self.settings.ignored_statuses else 'off'}"
            for key, status in self.STATUS_KEYS.items()
        ]
        return Text(
            f"Search settings · c Case: {case} · b Bodies: {body}\n"
            f"Ignore: {' · '.join(ignores[:3])}\n"
            f"        {' · '.join(ignores[3:])}\n"
            "Esc / Enter / s Back (settings retained)"
        )

    def _refresh_hints(self) -> None:
        self.query_one("#search-config", Static).update(self._hints())

    def action_toggle_case(self) -> None:
        self.settings.case_sensitive = not self.settings.case_sensitive
        self._refresh_hints()

    def action_toggle_body(self) -> None:
        self.settings.include_body = not self.settings.include_body
        self._refresh_hints()

    def action_toggle_status(self, status: str) -> None:
        if status in self.settings.ignored_statuses:
            self.settings.ignored_statuses.remove(status)
        else:
            self.settings.ignored_statuses.add(status)
        self._refresh_hints()

    def action_done(self) -> None:
        self.dismiss()


def _node_index(data: Dict[str, Any]) -> Dict[int, Dict[str, Any]]:
    return {node["id"]: node for node in data["nodes"]}


def _node_label(node: Dict[str, Any], active_id: Optional[int]) -> str:
    marker = "  ← active" if node["id"] == active_id else ""
    return f"{STATUS_MARKERS[node['status']]} #{node['id']} {node['summary']}{marker}"


def _styled_node_label(
    node: Dict[str, Any], active_id: Optional[int], *, matched: bool
) -> Text:
    label = Text(_node_label(node, active_id))
    if matched:
        label.stylize("bold yellow")
    return label


def _detail_text(data: Dict[str, Any], node: Dict[str, Any]) -> str:
    """Render task fields without changing the data held under a read lock."""

    by_id = _node_index(data)
    parent_by_child = {
        child_id: candidate["id"]
        for candidate in data["nodes"]
        for child_id in candidate["children"]
    }
    parent_id = parent_by_child.get(node["id"])
    parent = by_id.get(parent_id) if parent_id is not None else None
    return_target = by_id.get(node.get("return_to_id"))

    lines = [
        f"#{node['id']}  {node['summary']}",
        "",
        f"Status: {node['status']}",
        "Parent: " + (f"#{parent['id']} {parent['summary']}" if parent else "None"),
        "Return to: "
        + (
            f"#{return_target['id']} {return_target['summary']}"
            if return_target
            else "None"
        ),
        f"Closeout reviewed: {str(node.get('closeout_reviewed', False)).lower()}",
        f"Children: {len(node['children'])}",
    ]
    if node.get("body"):
        lines.extend(("", "Body", node["body"]))
    events = node.get("events", {})
    if events:
        lines.extend(("", "Events"))
        lines.extend(f"{name}: {value}" for name, value in sorted(events.items()))
    if node.get("files_dir"):
        lines.extend(("", f"Files: {node['files_dir']}"))
    return "\n".join(lines)


@dataclass(frozen=True)
class DropIntent:
    """The in-memory result of hit-testing a drag destination.

    ``destination_parent_id`` is ``None`` for a root-level sibling insertion.
    Exactly one of ``before_id`` and ``after_id`` is set for sibling moves;
    both are unset when the source is to become a child of the hovered task.
    """

    source_id: int
    destination_parent_id: Optional[int]
    before_id: Optional[int] = None
    after_id: Optional[int] = None

    def __post_init__(self) -> None:
        if self.before_id is not None and self.after_id is not None:
            raise ValueError("a drop cannot have both before_id and after_id")


class DragTree(Tree[Any]):
    """A Tree with stable, midpoint-based drag/drop previews.

    A destination is the durable task under the pointer.  The left half of
    its rendered task text inserts the source after that task; the right half
    makes the source a child. The tree is never rebuilt while an intent is
    being previewed; only the source and candidate labels are restyled.
    """

    DROP_BEFORE = "before"
    DROP_AFTER = "after"
    DROP_CHILD = "child"

    BINDINGS = [
        *Tree.BINDINGS,
        ("left", "collapse_cursor", "Collapse"),
        ("right", "expand_cursor", "Expand"),
        ("escape", "cancel_drag", "Cancel drag"),
    ]

    def __init__(
        self,
        label: Any,
        data: Any = None,
        *,
        name: Optional[str] = None,
        id: Optional[str] = None,
        classes: Optional[str] = None,
        disabled: bool = False,
    ) -> None:
        super().__init__(label, data, name=name, id=id, classes=classes, disabled=disabled)
        self.drag_source_id: Optional[int] = None
        self.drag_intent: Optional[DropIntent] = None
        # ``candidate_task_id`` names the valid durable destination under the
        # pointer; it is cleared when the source, a descendant, or no task is
        # under the pointer.
        self.candidate_task_id: Optional[int] = None
        # The rendered placement decision for the candidate.  This is kept
        # separately from the durable intent so marker styling does not have
        # to infer a mouse gesture from the intent fields.
        self.candidate_mode: Optional[str] = None
        self._press_position: Optional[tuple[int, int]] = None
        self._processed_pointer_position: Optional[tuple[float, float]] = None
        self._pending_source_id: Optional[int] = None
        self._dragging = False
        # Keyboard-initiated movement is deliberately separate from the
        # held-button state, but both modes share the same intent preview.
        self._keyboard_move_mode = False
        self._keyboard_click_pending = False
        # Textual emits a Click after the MouseUp that completes a drag. If
        # allowed through, Tree's auto-expand handler toggles the freshly
        # expanded drop destination closed again.
        self._suppress_next_click = False
        self._drop_handler: Optional[Callable[[DropIntent], None]] = None
        self._drag_changed: Optional[Callable[[], None]] = None
        self._drag_cancelled: Optional[Callable[[], None]] = None
        self._intent_for_target: Optional[Callable[[int, str], Optional[DropIntent]]] = None

    def configure_drag_callbacks(
        self,
        *,
        drop_handler: Callable[[DropIntent], None],
        drag_changed: Callable[[], None],
        drag_cancelled: Callable[[], None],
        intent_for_target: Callable[[int, str], Optional[DropIntent]],
    ) -> None:
        self._drop_handler = drop_handler
        self._drag_changed = drag_changed
        self._drag_cancelled = drag_cancelled
        self._intent_for_target = intent_for_target

    def clear(self) -> "DragTree":
        """Clear rows and discard orphaned internal nodes from a reload."""

        super().clear()
        # Textual reuses the root's internal ID but retains old entries in
        # ``_tree_nodes``. Prune them so hit testing only sees current rows.
        self._tree_nodes = {self.root._id: self.root}
        return self

    @property
    def dragging(self) -> bool:
        return self._dragging

    @property
    def keyboard_move_mode(self) -> bool:
        """Whether movement was started with ``m`` rather than a mouse drag."""

        return self._keyboard_move_mode

    @property
    def pending_drag(self) -> bool:
        """Whether a mouse-down is pending the one-cell drag threshold."""

        return self._press_position is not None and not self._dragging

    def _real_node_id(self, node_id: Any) -> Optional[int]:
        return node_id if isinstance(node_id, int) else None

    def _event_node_id(self, event: MouseDown | MouseMove | MouseUp) -> Optional[int]:
        line_no = event.style.meta.get("line")
        if isinstance(line_no, int):
            line_node = self.get_node_at_line(line_no)
            if line_node is not None:
                return self._real_node_id(line_node.data)
        tree_node_id = event.style.meta.get("node")
        try:
            tree_node = self.get_node_by_id(tree_node_id)
        except (KeyError, TypeError, ValueError, UnknownNodeID):
            tree_node = None
        if tree_node is not None:
            return self._real_node_id(tree_node.data)
        # This fallback keeps direct event-seam tests convenient when they
        # supply an application task ID rather than Textual's internal node
        # ID. Real rendered events always take the branch above.
        return self._real_node_id(tree_node_id)

    def _task_node(self, task_id: int) -> Optional[Any]:
        """Return the rendered TreeNode for a durable task ID."""

        for node in self._tree_nodes.values():
            if node.data == task_id:
                return node
        return None

    def _task_text_midpoint(self, node: Any) -> Optional[float]:
        """Return the widget-local midpoint of a rendered task label.

        ``MouseEvent.x`` is relative to the Tree's outer box, while tree rows
        are rendered from the content origin and then cropped by horizontal
        scroll.  Find the label's rendered start to account for Textual's
        guides and the fixed two-cell expander slot, then use ``_label``'s
        actual cell width so no marker or guide contributes to the midpoint.
        """

        if not isinstance(node._line, int) or node._line < 0:
            return None

        # Render without cropping to get the exact guide/slot width used by
        # Textual and by ``render_label`` above.  The outer ``node`` metadata
        # is applied to every label segment in Tree._render_line.
        rendered = self._render_line(
            node._line,
            0,
            max(self.size.width, self.virtual_size.width),
            self.rich_style,
        )
        label_start: Optional[int] = None
        x = 0
        for segment in rendered._segments:
            if segment.style.meta.get("node") == node._id:
                label_start = x
                break
            x += segment.cell_length
        if label_start is None:
            return None

        content_origin = self.content_region.x - self.region.x
        scroll_x = self.scroll_offset.x
        text_width = node._label.cell_len
        # The metadata begins at the two-cell expander/leaf slot.  The
        # midpoint is deliberately inside ``node._label`` rather than in
        # that slot, so add the slot before applying the label width.
        return content_origin + label_start - scroll_x + 2 + (text_width / 2)

    def _zone_from_pointer(self, event: MouseMove, target_id: int) -> Optional[str]:
        """Map the pointer to the left/right half of the rendered task text."""

        node = self._task_node(target_id)
        midpoint = self._task_text_midpoint(node) if node is not None else None
        if midpoint is None:
            return None
        return self.DROP_AFTER if event.x < midpoint else self.DROP_CHILD

    def _set_intent(
        self,
        intent: Optional[DropIntent],
        candidate_id: Optional[int],
        candidate_mode: Optional[str] = None,
    ) -> None:
        """Set the durable candidate and refresh marker styling only."""

        if intent is None:
            candidate_id = None
            candidate_mode = None
        changed = (
            intent != self.drag_intent
            or candidate_id != self.candidate_task_id
            or candidate_mode != self.candidate_mode
        )
        self.drag_intent = intent
        self.candidate_task_id = candidate_id
        self.candidate_mode = candidate_mode
        if changed:
            self._refresh_drag()

    def _refresh_drag(self) -> None:
        if self._drag_changed is not None:
            self._drag_changed()
        else:
            self.refresh(layout=False)

    def _set_dragging(self, source_id: int, event: MouseMove) -> None:
        self.start_drag(source_id)
        self._update_intent(event)

    def start_drag(self, source_id: int) -> None:
        """Start a drag through a deterministic seam (also used by mouse input)."""

        if self._dragging or not isinstance(source_id, int):
            return
        self._dragging = True
        self._keyboard_move_mode = False
        self._keyboard_click_pending = False
        self.drag_source_id = source_id
        self.drag_intent = None
        self.candidate_task_id = None
        self._processed_pointer_position = None
        self.candidate_mode = None
        self.capture_mouse()
        self._refresh_drag()

    def start_keyboard_move(self, source_id: int) -> None:
        """Enter move mode without requiring a held mouse button."""

        if self._dragging or self.pending_drag or not isinstance(source_id, int):
            return
        self._keyboard_move_mode = True
        self._keyboard_click_pending = False
        self._press_position = None
        self._pending_source_id = None
        self._processed_pointer_position = None
        self._dragging = True
        self.drag_source_id = source_id
        self.drag_intent = None
        self.candidate_task_id = None
        self.candidate_mode = None
        # Capture keeps movement and the eventual click observable even when
        # the pointer crosses the Tree border.  It does not imply a button is
        # held; ``on_mouse_move`` has a distinct keyboard-mode path below.
        self.capture_mouse()
        self._refresh_drag()

    def set_drag_target(self, target_id: int, zone: str) -> None:
        """Update the preview target without manufacturing mouse metadata."""

        if not self._dragging or self._intent_for_target is None:
            return
        if zone not in {self.DROP_BEFORE, self.DROP_AFTER, self.DROP_CHILD}:
            intent = None
        else:
            intent = self._intent_for_target(target_id, zone)
        self._set_intent(
            intent,
            target_id if intent is not None else None,
            zone if intent is not None else None,
        )

    def drop_drag(self) -> Optional[DropIntent]:
        """Release a drag through a deterministic seam and return its intent."""

        if not self._dragging:
            return None
        intent = self.drag_intent
        self.release_mouse()
        self._press_position = None
        self._pending_source_id = None
        self._processed_pointer_position = None
        self._dragging = False
        self._keyboard_move_mode = False
        self._keyboard_click_pending = False
        self.drag_source_id = None
        self.drag_intent = None
        self.candidate_task_id = None
        self.candidate_mode = None
        if intent is not None and self._drop_handler is not None:
            self._drop_handler(intent)
        if self._drag_cancelled is not None:
            self._drag_cancelled()
        return intent

    def _update_intent(self, event: MouseMove | MouseUp) -> None:
        if not self._dragging or self.drag_source_id is None:
            return
        node_id = self._event_node_id(event)
        zone = self._zone_from_pointer(event, node_id) if node_id is not None else None
        intent = (
            self._intent_for_target(node_id, zone)
            if node_id is not None and zone is not None and self._intent_for_target is not None
            else None
        )
        self._set_intent(
            intent,
            node_id if intent is not None else None,
            zone if intent is not None else None,
        )

    @staticmethod
    def _has_rendered_drop_metadata(event: MouseUp) -> bool:
        """Return whether release landed on a rendered tree row.

        The intent rendered by the preceding mouse move is authoritative;
        release only checks that the pointer is still over the tree.
        """

        metadata = event.style.meta
        line = metadata.get("line")
        return isinstance(line, int) and line >= 0

    def on_mouse_down(self, event: MouseDown) -> None:
        if event.button != 1:
            return
        # If a test/backend did not emit Click after the previous MouseUp, do
        # not suppress this new, independent click.
        self._suppress_next_click = False
        if self._keyboard_move_mode:
            # A keyboard move is completed by the corresponding mouse-up.
            # Do not let this click move the cursor, toggle a branch, or start
            # the ordinary held-button drag path.
            self._keyboard_click_pending = True
            event.stop()
            return
        source_id = self._event_node_id(event)
        if source_id is None or self._dragging:
            return
        self._press_position = (event.x, event.y)
        self._pending_source_id = source_id
        # Capturing immediately means a release outside the widget can cancel
        # the pending click without losing the normal click behavior.
        self.capture_mouse()

    def on_mouse_move(self, event: MouseMove) -> None:
        position = (event.x, event.y)
        duplicate = self._processed_pointer_position == position
        if self._keyboard_move_mode:
            if not duplicate:
                self._update_intent(event)
                self._processed_pointer_position = position
            event.stop()
            return
        if self._press_position is None:
            return
        if not self._dragging:
            press_x, press_y = self._press_position
            if abs(event.x - press_x) < 1 and abs(event.y - press_y) < 1:
                return
            source_id = self._pending_source_id
            if source_id is None:
                # The source is encoded on the original mouse-down, but a
                # synthetic event may only provide the move metadata.
                source_id = self._event_node_id(event)
            if source_id is None:
                self.cancel_drag()
                return
            self._set_dragging(source_id, event)
            self._processed_pointer_position = position
        elif self._processed_pointer_position != position:
            self._update_intent(event)
            self._processed_pointer_position = position
        event.stop()

    def on_mouse_up(self, event: MouseUp) -> None:
        if self._keyboard_move_mode:
            if event.button != 1:
                # Do not carry a stale click marker across an unrelated
                # button release while the keyboard move remains active.
                self._keyboard_click_pending = False
                return
            if not self._keyboard_click_pending:
                return
            self._keyboard_click_pending = False
            if not self._has_rendered_drop_metadata(event):
                self.cancel_drag()
                event.stop()
                return
            self._suppress_next_click = True
            # The rendered intent is authoritative. Do not re-hit-test after
            # the click.
            if self.drag_intent is not None:
                self.drop_drag()
            event.stop()
            return
        if self._press_position is None and not self._dragging:
            return
        if not self._dragging:
            self.release_mouse()
            self._press_position = None
            self._pending_source_id = None
            self._processed_pointer_position = None
            return
        if not self._has_rendered_drop_metadata(event):
            self.cancel_drag()
            event.stop()
            return
        self._suppress_next_click = True
        self.drop_drag()
        event.stop()

    async def _on_click(self, event: Click) -> None:
        """Discard the synthetic Click following a completed drag.

        Textual dispatches base handlers automatically, so do not call super().
        """

        if self._suppress_next_click:
            self._suppress_next_click = False
            # Stopping bubbling alone does not suppress Tree's default action.
            event.prevent_default()
            event.stop()
            return

    def cancel_drag(self) -> None:
        if self._press_position is None and not self._dragging:
            return
        self.release_mouse()
        self._press_position = None
        self._pending_source_id = None
        self._processed_pointer_position = None
        self._dragging = False
        self._keyboard_move_mode = False
        self._keyboard_click_pending = False
        self.drag_source_id = None
        self.drag_intent = None
        self.candidate_task_id = None
        self.candidate_mode = None
        if self._drag_cancelled is not None:
            self._drag_cancelled()

    def action_cancel_drag(self) -> None:
        self.cancel_drag()

    def action_collapse_cursor(self) -> None:
        """Collapse the cursor task, or move to its parent if already closed."""

        node = self.cursor_node
        if node is None:
            return
        if node.allow_expand and node.is_expanded:
            node.collapse()
            return
        parent = node.parent
        if parent is not None and isinstance(parent.data, int):
            self.move_cursor(parent)

    def action_expand_cursor(self) -> None:
        """Expand the task at the keyboard cursor, if it has children."""

        node = self.cursor_node
        if node is not None and node.allow_expand:
            node.expand()

    def render_label(self, node: Any, base_style: Style, style: Style) -> Text:
        # Delegate expandable nodes to Textual so its ordinary icon, toggle
        # metadata, and node behavior remain intact. Leaves receive the same
        # two-cell slot visually: a hidden-root leaf uses spaces, while a
        # nested leaf uses a horizontal continuation matching the guide.
        if node._allow_expand:
            rendered = super().render_label(node, base_style, style)
        else:
            node_label = node._label.copy()
            node_label.stylize(style)
            slot = "  " if node.parent is self.root and not self.show_root else "─ "
            rendered = Text.assemble((slot, base_style), node_label)
        if not self._dragging:
            return rendered
        if node.data == self.drag_source_id:
            rendered.stylize(Style(dim=True))
        if node.data == self.candidate_task_id:
            if self.candidate_mode == self.DROP_AFTER:
                rendered.stylize(Style(underline=True))
            elif self.candidate_mode == self.DROP_CHILD:
                rendered.stylize(Style(reverse=True, bold=True))
        return rendered

class TaskTreeApp(App[None]):
    """An interactive task-tree viewer backed by the normal locked store.

    Drag/drop relocations are persisted atomically. ``U`` or ``Ctrl+Z`` undoes
    the latest relocation for this session when its receipt is still safe;
    reloading clears that undo state.
    """

    TITLE = "task-tree"
    CSS = """
    #layout { height: 1fr; }
    #tree-pane { width: 55%; border: round $primary; }
    #details-pane {
        width: 45%;
        border: round $primary;
        padding: 1 2;
    }
    Screen.narrow #layout { layout: vertical; }
    Screen.narrow #tree-pane { width: 100%; height: 45%; }
    Screen.narrow #details-pane { width: 100%; height: 55%; }
    #details { width: 100%; height: auto; }
    #notepad-spacer { height: 1fr; min-height: 0; }
    #notepad { width: 100%; height: auto; margin-top: 1; border-top: solid $primary; padding-top: 1; }
    #status { height: 1; padding: 0 1; color: $text-muted; }
    Tree { height: 1fr; }
    """
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("r", "reload", "Reload"),
        ("/", "search", "Search"),
        ("s", "configure_search", "Search settings"),
        ("n", "next_match", "Next match"),
        ("N,shift+n", "previous_match", "Previous match"),
        ("m", "move_selected", "Move selected"),
        ("u", "undo", "Undo"),
        ("ctrl+z", "undo", "Undo"),
        ("escape", "cancel_drag", "Cancel drag"),
    ]

    def __init__(
        self,
        store: Any,
        relocate_node: Optional[Callable[..., Any]] = None,
    ) -> None:
        super().__init__()
        self.store = store
        # The CLI injects the callable from its already-loaded task_tree
        # module.  Keeping this optional lets the UI and drag-preview tests run
        # without importing task_tree.py a second time.
        self._relocate_node = relocate_node
        self._data: Dict[str, Any] = {}
        self._expanded_ids: Set[int] = set()
        self._selected_id: Optional[int] = None
        self._first_load = True
        self._last_dropped_intent: Optional[DropIntent] = None
        self._undo_receipt: Optional[Any] = None
        self._status = ""
        
        self._notepad = None
        
        self.search_settings = SearchSettings()
        self._search_query = ""
        self._search_matches: list[int] = []
        self._search_snapshot: Optional[SearchSnapshot] = None

    def compose(self) -> ComposeResult:
        yield Header(show_clock=False)
        with Horizontal(id="layout"):
            yield DragTree("Tasks", id="tree-pane")
            with VerticalScroll(id="details-pane"):
                yield Static("Loading task tree…", id="details")
                yield Static("", id="notepad-spacer")
                yield Static("", id="notepad", markup=False)
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        self._update_responsive_layout(self.size.width)
        tree = self.query_one(DragTree)
        tree.show_root = False
        tree.show_guides = True
        tree.configure_drag_callbacks(
            drop_handler=self.handle_drag_drop,
            drag_changed=self._refresh_drag_markers,
            drag_cancelled=self._drag_visuals_changed,
            intent_for_target=self._intent_for_target,
        )
        self._reload_tree()

    def on_resize(self, event: Resize) -> None:
        self._update_responsive_layout(event.size.width)

    def _update_responsive_layout(self, width: int) -> None:
        """Use durable active ancestry, never selection or expansion state."""
        depth = max(0, len(self._active_branch_ids()) - 1)
        threshold = NARROW_LAYOUT_BASE_COLUMNS + NARROW_LAYOUT_COLUMNS_PER_LEVEL * depth
        self.screen.set_class(width < threshold, "narrow")

    def _read_data(self) -> Dict[str, Any]:
        # The store owns schema validation and lock behavior.
        with self.store.locked_data() as data:
            self._notepad = notepad_storage.snapshot(self.store.path)
            return copy.deepcopy(data)

    def _set_status(self, status: str) -> None:
        self._status = status
        try:
            self.query_one("#status", Static).update(Text(status))
        except Exception:
            # This is useful for direct, pre-mount seams and keeps status
            # reporting from changing the underlying mutation behavior.
            pass

    @staticmethod
    def _parent_id_in_data(data: Dict[str, Any], node_id: int) -> Optional[int]:
        if node_id in data.get("root_ids", []):
            return None
        for candidate in data.get("nodes", []):
            if node_id in candidate.get("children", []):
                return candidate["id"]
        raise ValueError(f"Node {node_id} has no owning position")

    @staticmethod
    def _require_data_node(data: Dict[str, Any], node_id: int) -> Dict[str, Any]:
        for node in data.get("nodes", []):
            if node.get("id") == node_id:
                return node
        raise ValueError(f"Node {node_id} does not exist")

    def _destination_description(
        self, data: Dict[str, Any], intent: DropIntent
    ) -> str:
        by_id = _node_index(data)
        if intent.before_id is None and intent.after_id is None:
            parent = by_id.get(intent.destination_parent_id)
            return (
                f"under #{parent['id']} {parent['summary']}"
                if parent is not None
                else "at the root"
            )
        anchor_id = intent.before_id or intent.after_id
        anchor = by_id.get(anchor_id)
        relation = "before" if intent.before_id is not None else "after"
        if anchor is None:
            return "at the selected position"
        return f"{relation} #{anchor['id']} {anchor['summary']}"

    def _drop_failed(self, message: str) -> None:
        # No mutation is retried here.  A fresh read makes the display reflect
        # whatever durable state actually survived a validation/I/O failure.
        self._reload_tree()
        self._set_status(f"Drop failed: {message}")
        self.notify("Drop failed; task tree reloaded", severity="error")

    def _undo_failed(self, message: str) -> None:
        self._undo_receipt = None
        self._reload_tree()
        self._set_status(f"Undo unavailable: {message}")
        self.notify("Undo unavailable; task tree reloaded", severity="error")

    def _update_details(self, text: str) -> None:
        """Update the details text and return its scroll container to the top."""

        pane = self.query_one("#details-pane", VerticalScroll)
        self.query_one("#details", Static).update(text)
        # Stop any pending scroll animation and reset the current position
        # immediately. The content update can change the layout on the next
        # refresh, so repeat the non-animated reset after that refresh too.
        pane.scroll_home(animate=False, immediate=True)
        self.call_after_refresh(pane.scroll_home, animate=False, immediate=True)

    def _reload_tree(self) -> None:
        try:
            self._data = self._read_data()
        except (OSError, ValueError) as exc:
            self._update_details(f"Could not read task tree:\n{exc}")
            self.query_one("#notepad", Static).update("Tree-wide notepad\nUnavailable: task tree could not reload")
            self.notify("Could not reload task tree", severity="error")
            return

        self.query_one("#notepad", Static).update(notepad_storage.render(self._notepad))

        # On entry, reveal the active task's context without expanding an
        # entire large workstream. Subsequent reloads retain the user's own
        # expansion/collapse choices.
        if self._first_load:
            self._expanded_ids.update(self._active_branch_ids())
            self._first_load = False

        self._render_tree()

    def _render_tree(self, *, expand_node_id: Optional[int] = None) -> None:
        """Rebuild rows from durable data after a reload or successful drop.

        ``expand_node_id`` is used for a child drop whose destination became
        a parent during persistence.  The destination is deliberately built
        using the ordinary expansion state first, then expanded as the exact
        rebuilt ``TreeNode`` after its newly persisted child has been
        attached.  This matters when the destination was a leaf before the
        drop: adding its ID to ``_expanded_ids`` before construction is not
        sufficient for every Textual lifecycle.
        """

        self._update_responsive_layout(self.size.width)
        tree = self.query_one(DragTree)
        tree.clear()
        by_id = _node_index(self._data)
        active_id = self._data.get("active_id")
        visible_nodes: Dict[int, Any] = {}
        self._search_matches = _search_task_ids(
            self._data, self._search_query, self.search_settings
        )
        match_ids = set(self._search_matches)

        def add_node(parent: Any, node_id: int) -> None:
            node = by_id[node_id]
            child_ids = node["children"]
            label = _styled_node_label(node, active_id, matched=node_id in match_ids)
            if child_ids:
                tree_node = parent.add(
                    label,
                    data=node_id,
                    expand=node_id in self._expanded_ids,
                )
            else:
                tree_node = parent.add_leaf(label, data=node_id)
            visible_nodes[node_id] = tree_node
            for child_id in child_ids:
                add_node(tree_node, child_id)

        for root_id in self._data["root_ids"]:
            add_node(tree.root, root_id)

        if expand_node_id is not None:
            destination_node = visible_nodes.get(expand_node_id)
            if destination_node is not None and destination_node._allow_expand:
                destination_node.expand()
                self._expanded_ids.add(expand_node_id)

        selected_id = self._selected_id
        if selected_id not in visible_nodes:
            selected_id = active_id if active_id in visible_nodes else next(iter(visible_nodes), None)
        self._selected_id = selected_id
        if selected_id is None:
            self._update_details("No tasks in this tree.")
        else:
            # ``Tree.select_node`` posts ``NodeSelected``. Textual's default
            # handler for that message toggles the node when ``auto_expand``
            # is enabled, which would collapse an initially expanded active
            # node. Move the cursor after the rebuilt tree has been laid out;
            # before that refresh, nested nodes do not yet have usable line
            # numbers and Textual clamps the cursor back to the first row.
            self.call_after_refresh(tree.move_cursor, visible_nodes[selected_id])
            self._show_details(selected_id)
        if self._search_query and self._search_status_visible():
            self._show_search_status()

    def _refresh_drag_markers(self) -> None:
        """Repaint marker styles without changing tree layout or node objects."""

        tree = self.query_one(DragTree)
        tree._clear_line_cache()
        tree.refresh(layout=False)

    def _drag_visuals_changed(self) -> None:
        """Clear drag marker styling without rebuilding the durable tree."""

        tree = self.query_one(DragTree)
        if not tree.dragging and self._status.startswith("Moving #"):
            self._set_status("")
            if self._search_query:
                self._show_search_status()
        self._refresh_drag_markers()

    def _parent_by_child(self) -> Dict[int, int]:
        return {
            child_id: node["id"]
            for node in self._data["nodes"]
            for child_id in node["children"]
        }

    def _descendant_ids(self, node_id: int) -> Set[int]:
        by_id = _node_index(self._data)
        descendants: Set[int] = set()
        pending = list(by_id.get(node_id, {}).get("children", []))
        while pending:
            current = pending.pop()
            if current in descendants:
                continue
            descendants.add(current)
            pending.extend(by_id.get(current, {}).get("children", []))
        return descendants

    def _intent_for_target(self, target_id: int, zone: str) -> Optional[DropIntent]:
        tree = self.query_one(DragTree)
        source_id = tree.drag_source_id
        by_id = _node_index(self._data)
        if (
            source_id is None
            or source_id not in by_id
            or target_id == source_id
            or target_id not in by_id
        ):
            return None
        descendants = self._descendant_ids(source_id)
        if target_id in descendants:
            return None
        parent_by_child = self._parent_by_child()
        if zone == DragTree.DROP_CHILD:
            return DropIntent(source_id, target_id)
        if zone == DragTree.DROP_BEFORE:
            anchor_id, after_id = target_id, None
        elif zone == DragTree.DROP_AFTER:
            anchor_id, after_id = None, target_id
        else:
            return None
        if anchor_id is not None and anchor_id in descendants:
            return None
        if after_id is not None and after_id in descendants:
            return None
        return DropIntent(source_id, parent_by_child.get(target_id), anchor_id, after_id)

    def handle_drag_drop(self, intent: DropIntent) -> None:
        self._last_dropped_intent = intent
        if self._relocate_node is None:
            # Direct UI-only tests intentionally omit the data-layer callable.
            # Preserve their seam without presenting a non-existent durable
            # success.
            self.notify(f"Drop intent: move #{intent.source_id}", severity="information")
            return

        try:
            with self.store.locked_data(write=True) as data:
                receipt = self._relocate_node(
                    data,
                    intent.source_id,
                    intent.destination_parent_id,
                    before_id=intent.before_id,
                    after_id=intent.after_id,
                )
                # TaskTreeStore writes the yielded object when this context
                # exits.  Copying here ensures Textual never retains a dict
                # owned by the lock's mutation scope.
                persisted_data = copy.deepcopy(data)
        except Exception as exc:
            self._drop_failed(str(exc))
            return

        self._data = persisted_data
        self._undo_receipt = receipt
        self._selected_id = intent.source_id
        # A child drop into a collapsed branch must reveal the moved task,
        # but must not expand the moved source (or any of its descendants).
        # Sibling drops preserve the user's existing expansion state.  The
        # destination is explicitly expanded after rebuilding so a leaf-to-
        # parent transition does not depend on constructor ``expand=True``.
        child_drop = (
            intent.destination_parent_id is not None
            and intent.before_id is None
            and intent.after_id is None
        )
        destination = self._destination_description(persisted_data, intent)
        self._set_status(
            f"Moved #{intent.source_id} {destination} — press U/Ctrl+Z to undo"
        )
        self._render_tree(
            expand_node_id=intent.destination_parent_id if child_drop else None
        )
        self.notify(
            f"Moved #{intent.source_id} {destination}; press U/Ctrl+Z to undo",
            severity="information",
        )

    def _undo_mutation(self, receipt: Any) -> Dict[str, Any]:
        """Validate and inverse one relocation under one fresh write lock."""

        with self.store.locked_data(write=True) as data:
            source = self._require_data_node(data, receipt.source_id)
            current_parent_id = self._parent_id_in_data(data, receipt.source_id)
            if current_parent_id != receipt.destination_parent_id:
                raise ValueError("the moved task is no longer at its drop destination")
            move_marker = source.get("events", {}).get("move_marker")
            if move_marker != receipt.move_marker:
                raise ValueError("the moved task changed after the drop")

            if receipt.original_parent_id is not None:
                self._require_data_node(data, receipt.original_parent_id)

            destination_owner = (
                data["root_ids"]
                if receipt.original_parent_id is None
                else self._require_data_node(data, receipt.original_parent_id)["children"]
            )
            before_id = None
            after_id = None
            if (
                receipt.original_next_id is not None
                and receipt.original_next_id in destination_owner
            ):
                before_id = receipt.original_next_id
            elif (
                receipt.original_previous_id is not None
                and receipt.original_previous_id in destination_owner
            ):
                after_id = receipt.original_previous_id
            elif (
                receipt.original_next_id is None
                and receipt.original_previous_id is None
            ):
                # The source was the sole original child (or root), so
                # appending is the exact original placement.
                pass
            else:
                raise ValueError("the original sibling anchors no longer exist")

            self._relocate_node(
                data,
                receipt.source_id,
                receipt.original_parent_id,
                before_id=before_id,
                after_id=after_id,
            )
            return copy.deepcopy(data)

    def action_undo(self) -> None:
        receipt = self._undo_receipt
        if receipt is None:
            self.notify("Nothing to undo", severity="information")
            return
        try:
            persisted_data = self._undo_mutation(receipt)
        except Exception as exc:
            self._undo_failed(str(exc))
            return

        self._data = persisted_data
        self._selected_id = receipt.source_id
        self._expanded_ids.update(self._branch_ids_for(receipt.source_id))
        self._undo_receipt = None
        self._set_status("")
        self._render_tree()
        self.notify(f"Undid move of #{receipt.source_id}", severity="information")

    def _active_branch_ids(self) -> Set[int]:
        """Return active task and its ancestors, which must be expanded to reveal it."""

        active_id = self._data.get("active_id")
        if active_id is None:
            return set()
        return self._branch_ids_for(active_id)

    def _branch_ids_for(self, node_id: Optional[int]) -> Set[int]:
        if node_id is None:
            return set()
        parent_by_child = {
            child_id: node["id"]
            for node in self._data["nodes"]
            for child_id in node["children"]
        }
        branch: Set[int] = set()
        current_id: Optional[int] = node_id
        while current_id is not None:
            branch.add(current_id)
            current_id = parent_by_child.get(current_id)
        return branch

    def _show_details(self, node_id: int) -> None:
        node = _node_index(self._data)[node_id]
        self._update_details(_detail_text(self._data, node))

    def on_tree_node_highlighted(self, event: Tree.NodeHighlighted) -> None:
        node_id = event.node.data
        if isinstance(node_id, int):
            self._selected_id = node_id
            self._show_details(node_id)
            if (
                self._search_query
                and self._search_status_visible()
                and not self.query_one(DragTree).dragging
            ):
                self._show_search_status()

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        if isinstance(event.node.data, int):
            self._expanded_ids.add(event.node.data)

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed) -> None:
        if isinstance(event.node.data, int):
            self._expanded_ids.discard(event.node.data)

    def check_action(self, action: str, parameters: tuple[object, ...]) -> bool:
        if action in {"next_match", "previous_match"}:
            return bool(self._search_query)
        return True

    def _can_start_search(self) -> bool:
        tree = self.query_one(DragTree)
        if tree.dragging or tree.pending_drag:
            self.notify("Finish or cancel the move before entering search")
            return False
        return True

    def action_search(self) -> None:
        if self._can_start_search():
            self._search_snapshot = SearchSnapshot(
                self._search_query,
                self._selected_id,
                set(self._expanded_ids),
                self._status,
            )
            self.push_screen(
                SearchInputScreen(self._search_query, self._preview_search),
                self._submit_search,
            )

    def action_configure_search(self) -> None:
        if self._can_start_search():
            self.push_screen(
                SearchConfigScreen(self.search_settings), self._search_configured
            )

    def _submit_search(self, query: Optional[str]) -> None:
        snapshot = self._search_snapshot
        if snapshot is None:
            return
        if query is None:
            self._search_query = snapshot.query
            self._selected_id = snapshot.selected_id
            self._expanded_ids = set(snapshot.expanded_ids)
            self._render_tree()
            self._set_status(snapshot.status)
        else:
            # Apply the final value even if its Changed message is still queued.
            self._preview_search(query)
        self._search_snapshot = None
        self.query_one(DragTree).focus()
        self.refresh_bindings()

    def _preview_search(self, query: str) -> None:
        snapshot = self._search_snapshot
        if snapshot is None:
            return
        self._search_query = query
        previous_matches = set(self._search_matches)
        self._search_matches = _search_task_ids(
            self._data, query, self.search_settings
        )
        tree = self.query_one(DragTree)
        match_ids = set(self._search_matches)
        changed_ids = previous_matches ^ match_ids
        by_id = _node_index(self._data)
        # Keep node objects and geometry stable, repainting only changed matches.
        for tree_node in tree._tree_nodes.values():
            if tree_node.data in changed_ids:
                tree_node.set_label(
                    _styled_node_label(
                        by_id[tree_node.data],
                        self._data.get("active_id"),
                        matched=tree_node.data in match_ids,
                    )
                )
        # Every edit searches from the original cursor, not the last preview.
        self._selected_id = snapshot.selected_id
        if self._search_matches:
            self._navigate_search(1, include_current=True, focus_tree=False)
        else:
            if self._selected_id is not None:
                self._show_details(self._selected_id)
                self.call_after_refresh(self._move_search_cursor, self._selected_id)
            if query:
                self._show_search_status()
            else:
                self._set_status("Search cleared")

    def _search_configured(self, result: None) -> None:
        # Recompute existing results without unexpectedly moving the cursor.
        self._render_tree()
        self.query_one(DragTree).focus()
        if self._search_query:
            self._show_search_status()

    def _search_status_visible(self) -> bool:
        # Do not replace move confirmations or errors with a match count.
        return not self._status or self._status.startswith(("Search ", "No matches for "))

    def _show_search_status(self) -> None:
        if not self._search_matches:
            self._set_status(f"No matches for {self._search_query!r}")
        elif self._selected_id in self._search_matches:
            index = self._search_matches.index(self._selected_id) + 1
            self._set_status(
                f"Search {self._search_query!r}: {index}/{len(self._search_matches)}"
            )
        else:
            self._set_status(
                f"Search {self._search_query!r}: {len(self._search_matches)} matches"
            )

    def _move_search_cursor(self, task_id: int) -> None:
        # A later edit or cancellation may supersede a queued cursor movement.
        if task_id == self._selected_id:
            tree = self.query_one(DragTree)
            node = tree._task_node(task_id)
            if node is not None:
                tree.move_cursor(node)

    def _navigate_search(
        self, direction: int, *, include_current: bool = False, focus_tree: bool = True
    ) -> None:
        tree = self.query_one(DragTree)
        if tree.dragging or tree.pending_drag:
            self.notify("Finish or cancel the move before navigating matches")
            return
        matches = self._search_matches
        if not matches:
            self._show_search_status()
            return
        # Include every task in traversal order, not just currently visible rows.
        ordered = _task_ids_in_order(self._data)
        positions = {task_id: index for index, task_id in enumerate(ordered)}
        cursor = positions.get(self._selected_id, -1 if direction > 0 else len(ordered))
        candidates = matches if direction > 0 else list(reversed(matches))
        target = next(
            (
                task_id
                for task_id in candidates
                if (positions[task_id] - cursor) * direction > 0
                or (include_current and task_id == self._selected_id)
            ),
            candidates[0],
        )
        self._selected_id = target
        for task_id in self._branch_ids_for(target) - {target}:
            ancestor = tree._task_node(task_id)
            if ancestor is not None:
                ancestor.expand()
                self._expanded_ids.add(task_id)
        self.call_after_refresh(self._move_search_cursor, target)
        if focus_tree:
            tree.focus()
        self._show_details(target)
        self._show_search_status()

    def action_next_match(self) -> None:
        self._navigate_search(1)

    def action_previous_match(self) -> None:
        self._navigate_search(-1)

    def action_reload(self) -> None:
        self._undo_receipt = None
        self._set_status("")
        self._reload_tree()
        self.notify("Reloaded task tree")

    def action_cancel_drag(self) -> None:
        self.query_one(DragTree).cancel_drag()

    def action_move_selected(self) -> None:
        """Enter or cancel the no-button keyboard move interaction."""

        tree = self.query_one(DragTree)
        if tree.keyboard_move_mode:
            tree.cancel_drag()
            return
        if tree.dragging or tree.pending_drag:
            self.notify("Finish the active drag before starting move mode")
            return

        node = tree.cursor_node
        source_id = node.data if node is not None else None
        if not isinstance(source_id, int) or source_id not in _node_index(self._data):
            self.notify("Select a durable task before moving it")
            return

        tree.start_keyboard_move(source_id)
        self._set_status(
            f"Moving #{source_id} — left half inserts after, right half makes child; "
            "click places; Escape cancels"
        )

    def action_quit(self) -> None:
        self.exit()


def run_tui(
    store: Any,
    relocate_node: Optional[Callable[..., Any]] = None,
) -> int:
    """Run the UI and return a normal CLI exit status."""

    TaskTreeApp(store, relocate_node=relocate_node).run()
    return 0
