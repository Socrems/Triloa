"""Screen image OCR with reading-order reconstruction."""

from __future__ import annotations

from pathlib import Path
from threading import Lock

_engine = None
_lock = Lock()


def _join_fragments(parts: list[tuple[float, float, str]]) -> str:
    text = ""
    previous_right = -1.0
    for left, right, fragment in sorted(parts, key=lambda part: part[0]):
        if text and left < previous_right:
            for size in range(min(len(text), len(fragment), 12), 0, -1):
                if text.endswith(fragment[:size]):
                    fragment = fragment[size:]
                    break
        if fragment:
            separator = " " if text and text[-1].isascii() and text[-1].isalnum() and fragment[0].isascii() and fragment[0].isalnum() else ""
            text += separator + fragment
        previous_right = max(previous_right, right)
    return text


def _column_groups(items: list[tuple]) -> list[list[tuple]]:
    """Read separate page columns top to bottom instead of mixing their rows."""
    if len(items) < 6:
        return [items]
    heights = sorted(item[1] for item in items)
    minimum_gap = max(24.0, heights[len(heights) // 2] * 1.5)
    # Measure gutters between body boxes, ignoring boxes that span a candidate.
    # A spanning heading may be narrower than the page, so width alone is unsafe.
    edges = sorted({edge for item in items for edge in item[2:4]})
    gaps = []
    for first, last in zip(edges, edges[1:]):
        boundary = (first + last) / 2
        left_items = [item for item in items if item[3] < boundary]
        right_items = [item for item in items if item[2] > boundary]
        if len(left_items) >= 3 and len(right_items) >= 3:
            gap = min(i[2] for i in right_items) - max(i[3] for i in left_items)
            gaps.append((gap, boundary))
    for gap, boundary in sorted(gaps, reverse=True):
        if gap < minimum_gap:
            break
        left_items = [item for item in items if item[3] < boundary]
        right_items = [item for item in items if item[2] > boundary]
        if len(left_items) >= 3 and len(right_items) >= 3:
            overlap = min(max(i[0] + i[1] / 2 for i in left_items),
                          max(i[0] + i[1] / 2 for i in right_items)) - max(
                              min(i[0] - i[1] / 2 for i in left_items),
                              min(i[0] - i[1] / 2 for i in right_items))
            if overlap < heights[len(heights) // 2]:
                continue
            spanning = sorted((i for i in items if i[2] <= boundary <= i[3]),
                              key=lambda i: (i[0], i[2]))
            pending = left_items + right_items
            groups = []
            span_block = []

            def append_columns(band):
                for side in ([i for i in band if i[3] < boundary],
                             [i for i in band if i[2] > boundary]):
                    if side:
                        groups.extend(_column_groups(side))

            for span in spanning:
                above = [i for i in pending if i[0] < span[0]]
                if above:
                    if span_block:
                        groups.append(span_block)
                        span_block = []
                    append_columns(above)
                    pending = [i for i in pending if i[0] >= span[0]]
                span_block.append(span)
            if span_block:
                groups.append(span_block)
            append_columns(pending)
            return groups
    return [items]


def _reading_order(output) -> str:
    boxes = getattr(output, "boxes", None)
    texts = getattr(output, "txts", None)
    scores = getattr(output, "scores", None)
    if boxes is None or not texts:
        return ""
    items = []
    for index, (box, text) in enumerate(zip(boxes, texts)):
        if not text or not text.strip():
            continue
        if scores is not None and index < len(scores) and float(scores[index]) < 0.45:
            continue
        xs = [float(point[0]) for point in box]
        ys = [float(point[1]) for point in box]
        top, bottom = min(ys), max(ys)
        items.append((top + (bottom - top) / 2, max(1.0, bottom - top), min(xs), max(xs), text))
    if not items:
        return ""

    columns = []
    for column_items in _column_groups(items):
        column_items.sort(key=lambda item: (item[0], item[2]))
        rows: list[dict] = []
        for center, height, left, right, fragment in column_items:
            row = next(
                (candidate for candidate in rows
                 if abs(center - candidate["center"]) <= min(height, candidate["height"]) * 0.5),
                None,
            )
            if row is None:
                rows.append({"center": center, "height": height, "parts": [(left, right, fragment)]})
            else:
                row["parts"].append((left, right, fragment))
                count = len(row["parts"])
                row["center"] += (center - row["center"]) / count
                row["height"] = max(row["height"], height)
        ordered = sorted(rows, key=lambda row: row["center"])
        median_height = sorted(row["height"] for row in ordered)[len(ordered) // 2]
        result = []
        previous = None
        for row in ordered:
            if previous is not None:
                gap = (row["center"] - row["height"] / 2) - (
                    previous["center"] + previous["height"] / 2
                )
                result.append("\n\n" if gap > median_height * 0.75 else "\n")
            result.append(_join_fragments(row["parts"]))
            previous = row
        columns.append("".join(result))
    return "\n\n".join(columns)


def recognize(image: Path) -> str:
    global _engine
    try:
        from rapidocr import RapidOCR
    except ImportError as exc:
        raise RuntimeError("尚未安装 OCR 引擎。请先运行安装脚本。") from exc
    with _lock:
        if _engine is None:
            from .resources import ocr_model_paths
            _engine = RapidOCR(params=ocr_model_paths())
        output = _engine(str(image))
    return _reading_order(output)
