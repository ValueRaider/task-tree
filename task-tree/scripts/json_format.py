"""Deterministic JSON formatting for experimental task-tree schema v2."""

import json
import re
from typing import Dict, List


# One hundred columns keeps ordinary task IDs dense without making tree files
# awkward to inspect in a split terminal or review in a side-by-side diff.
RELATIONSHIP_ARRAY_LINE_WIDTH = 100

RELATIONSHIP_ARRAY_START = re.compile(r'^(?P<indent> *)"(?P<key>children|root_ids)": \[$')
RELATIONSHIP_ARRAY_ITEM = re.compile(r"^\s*(?P<id>[1-9][0-9]*)(?:,)?$")


def _format_id_array(
    indent: str,
    key: str,
    ids: List[int],
    *,
    trailing_comma: bool,
    width: int,
) -> List[str]:
    prefix = f'{indent}"{key}": ['
    continuation = " " * len(prefix)
    closing = "]" + ("," if trailing_comma else "")
    lines: List[str] = []
    current = prefix

    for index, node_id in enumerate(ids):
        last = index == len(ids) - 1
        token = str(node_id) + ("" if last else ",")
        separator = "" if current.endswith("[") else " "
        candidate = current + separator + token + (closing if last else "")
        if len(candidate) <= width or current == prefix:
            current += separator + token
        else:
            lines.append(current)
            current = continuation + token

    current += closing
    lines.append(current)
    return lines


def _compact_relationship_arrays(serialized: str, *, width: int) -> str:
    source_lines = serialized.splitlines()
    output: List[str] = []
    index = 0
    while index < len(source_lines):
        start = RELATIONSHIP_ARRAY_START.match(source_lines[index])
        if start is None:
            output.append(source_lines[index])
            index += 1
            continue

        cursor = index + 1
        ids: List[int] = []
        while cursor < len(source_lines):
            item = RELATIONSHIP_ARRAY_ITEM.match(source_lines[cursor])
            if item is None:
                break
            ids.append(int(item.group("id")))
            cursor += 1

        closing = source_lines[cursor] if cursor < len(source_lines) else ""
        expected_prefix = f"{start.group('indent')}]"
        if not ids or not closing.startswith(expected_prefix):
            output.append(source_lines[index])
            index += 1
            continue

        output.extend(
            _format_id_array(
                start.group("indent"),
                start.group("key"),
                ids,
                trailing_comma=closing.endswith(","),
                width=width,
            )
        )
        index = cursor + 1
    return "\n".join(output)


def dumps_v2_json(data: Dict, *, width: int = RELATIONSHIP_ARRAY_LINE_WIDTH) -> str:
    """Serialize v2 data while using horizontal space for relationship IDs."""

    serialized = json.dumps(data, indent=2, sort_keys=True)
    return _compact_relationship_arrays(serialized, width=width) + "\n"
