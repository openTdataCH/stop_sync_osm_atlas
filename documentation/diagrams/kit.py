"""Shared visual language for the documentation diagrams.

Every hand-designed documentation diagram is a small Python function that
composes the helpers below. The helpers are the diagram "macros": one place
defines the palette, typography, shapes, arrows, step numbers and legends, so
all diagrams read as one system. ``build.py`` renders the catalog in
``catalog.py`` to self-contained SVG files.

The output deliberately uses only presentation attributes and plain shapes
(no CSS, markers, filters, fonts or scripts). The same file therefore renders
identically in the documentation portal, on GitHub and in the WeasyPrint PDF.

The visual rules themselves are documented in ``documentation/Documentation
style guide.md``. Keep that page and this module in step.
"""
from __future__ import annotations

import math
import re
from dataclasses import dataclass
from html import unescape
from typing import Iterable, List, Optional, Sequence, Tuple, Union
from xml.sax.saxutils import escape

KIT_VERSION = 2

FONT = "'Segoe UI', system-ui, -apple-system, 'Helvetica Neue', Arial, sans-serif"
MONO = "'SFMono-Regular', Consolas, 'Liberation Mono', Menlo, monospace"

# Ink and surfaces, from static/css/src/01-settings/tokens.css.
INK = '#343a40'        # --color-dark: body text, numbered steps
MUTED = '#6c757d'      # --color-fg-muted: secondary text, plain arrows
FAINT = '#adb5bd'      # --color-fg-subtle: rails, dividers
SURFACE = '#ffffff'    # --color-bg: canvas
BORDER = '#e5e7eb'     # --color-border


@dataclass(frozen=True)
class Tone:
    """Colours of one meaning: outline, filled shape, text and zone tint."""

    stroke: str
    fill: str
    text: str
    tint: str


# System diagrams: who owns a part. These match the documentation portal's
# ownership badges (engine = success palette, app = primary palette).
ENGINE = Tone('#4caf50', '#eaf4ec', '#1f5e22', '#f6fbf6')
APP = Tone('#174092', '#eef3fb', '#174092', '#f7f9fd')
CONTRACT = Tone('#6b21a8', '#faf5ff', '#6b21a8', '#fdfaff')  # the shared result bundle
EXTERNAL = Tone('#6c757d', '#f8f9fa', '#343a40', '#fbfbfc')  # services outside both projects

# Domain diagrams: what a map marker means. These match the map palette.
ATLAS = Tone('#174092', '#eef3fb', '#174092', '#f7f9fd')
OSM = Tone('#4caf50', '#ecf8ed', '#1f5e22', '#f6fbf6')
GTFS = Tone('#f0ad4e', '#fdf8ef', '#653a00', '#fefbf5')
UNMATCHED = Tone('#dc3545', '#fbe9eb', '#721c24', '#fef6f7')

# Status colours shared by both vocabularies.
WARNING = Tone('#f0ad4e', '#fdf8ef', '#653a00', '#fefbf5')
NEUTRAL = EXTERNAL

HEADING_SIZE = 15
BODY_SIZE = 13
SMALL_SIZE = 12

# Text is measured with Helvetica metrics (thousandths of an em), then
# widened: PDF builds on Linux can fall back to the wider DejaVu Sans.
_FONT_SAFETY = 1.12
_REGULAR = dict(zip(
    ' !"#$%&\'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~',
    [278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278]
    + [556] * 10
    + [278, 278, 584, 584, 584, 556, 1015, 667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556,
       833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 278, 278, 278, 469, 556,
       333, 556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333,
       500, 278, 556, 500, 722, 500, 500, 500, 334, 260, 334, 584],
))
_BOLD = dict(zip(
    ' !"#$%&\'()*+,-./0123456789:;<=>?@ABCDEFGHIJKLMNOPQRSTUVWXYZ[\\]^_`abcdefghijklmnopqrstuvwxyz{|}~',
    [278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278]
    + [556] * 10
    + [333, 333, 584, 584, 584, 611, 975, 722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611,
       833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611, 333, 278, 333, 584, 556,
       333, 556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389,
       556, 333, 611, 556, 778, 556, 556, 500, 389, 280, 389, 584],
))
_WIDE = {'→': 1000, '←': 1000, '↔': 1000, '—': 1000, '…': 1000, '✓': 800, '✕': 800, '×': 584}


class LayoutError(ValueError):
    """A label does not fit the space a diagram gives it."""


def _num(value: float) -> str:
    """Format a coordinate deterministically, without float noise."""
    text = f'{round(value, 2):.2f}'.rstrip('0').rstrip('.')
    return '0' if text in ('-0', '') else text


def text_width(text: str, size: float, *, bold: bool = False, mono: bool = False) -> float:
    """Estimate the rendered width of ``text`` in user units."""
    if mono:
        return len(text) * 0.6 * size * _FONT_SAFETY
    table = _BOLD if bold else _REGULAR
    units = sum(_WIDE.get(char, table.get(char, 556)) for char in text)
    return units / 1000 * size * _FONT_SAFETY


@dataclass(frozen=True)
class Line:
    """One line of text inside a shape. ``mono`` marks code identifiers."""

    text: str
    size: float = BODY_SIZE
    bold: bool = False
    mono: bool = False
    color: Optional[str] = None

    def width(self) -> float:
        return text_width(self.text, self.size, bold=self.bold, mono=self.mono)


TextLike = Union[str, Line]


def _line(value: TextLike, *, size: float = BODY_SIZE, bold: bool = False,
          color: Optional[str] = None) -> Line:
    if isinstance(value, Line):
        return value
    # Backticks mark code: `name` renders in the monospace font.
    if value.startswith('`') and value.endswith('`') and len(value) > 1:
        return Line(value[1:-1], size=size, bold=bold, mono=True, color=color)
    return Line(value, size=size, bold=bold, color=color)


def code(text: str, size: float = BODY_SIZE, color: Optional[str] = None) -> Line:
    return Line(text, size=size, mono=True, color=color)


def text(x: float, y: float, value: TextLike, *, size: float = BODY_SIZE, bold: bool = False,
         color: str = INK, anchor: str = 'start', mono: bool = False, italic: bool = False,
         letter_spacing: Optional[float] = None, max_width: Optional[float] = None) -> str:
    """A single line of text. ``y`` is the baseline.

    ``max_width`` makes the build fail when the text would not fit.
    """
    line = _line(value, size=size, bold=bold, color=color)
    if mono:
        line = Line(line.text, line.size, line.bold, True, line.color)
    if max_width is not None and line.width() > max_width + 0.5:
        raise LayoutError(f'text {line.text!r} needs {line.width():.0f} units, only {max_width:.0f} are available')
    attributes = [
        f'x="{_num(x)}"', f'y="{_num(y)}"',
        f'font-family="{MONO if line.mono else FONT}"',
        f'font-size="{_num(line.size)}"',
        f'fill="{line.color or color}"',
    ]
    if line.bold:
        attributes.append('font-weight="600"')
    if italic:
        attributes.append('font-style="italic"')
    if anchor != 'start':
        attributes.append(f'text-anchor="{anchor}"')
    if letter_spacing:
        attributes.append(f'letter-spacing="{_num(letter_spacing)}"')
    # SVG collapses leading spaces; non-breaking spaces keep an indent.
    content = line.text.lstrip(' ')
    content = ' ' * (len(line.text) - len(content)) + content
    return f'<text {" ".join(attributes)}>{escape(content)}</text>'


def _block_height(lines: Sequence[Line], gap: float) -> float:
    if not lines:
        return 0.0
    return sum(line.size for line in lines) + gap * (len(lines) - 1)


def text_block(x: float, top: float, lines: Sequence[TextLike], *, anchor: str = 'start',
               color: str = INK, gap: float = 5.0, max_width: Optional[float] = None,
               context: str = '') -> Tuple[str, float]:
    """Stack lines downwards from ``top``. Returns the SVG and its height."""
    parsed = [_line(value, color=color) for value in lines]
    parts = []
    y = top
    for line in parsed:
        if max_width is not None and line.width() > max_width + 0.5:
            raise LayoutError(
                f'{context or "Text"}: {line.text!r} needs {line.width():.0f} units, '
                f'only {max_width:.0f} are available'
            )
        y += line.size
        parts.append(text(x, y - line.size * 0.2, line, anchor=anchor, color=line.color or color))
        y += gap
    return '\n'.join(parts), _block_height(parsed, gap)


def _rect(x: float, y: float, w: float, h: float, *, fill: str, stroke: Optional[str],
          radius: float = 10, width: float = 1.5, dash: Optional[str] = None,
          opacity: Optional[float] = None) -> str:
    attributes = [f'x="{_num(x)}"', f'y="{_num(y)}"', f'width="{_num(w)}"', f'height="{_num(h)}"']
    if radius:
        attributes.append(f'rx="{_num(radius)}"')
    attributes.append(f'fill="{fill}"')
    if opacity is not None:
        attributes.append(f'fill-opacity="{_num(opacity)}"')
    if stroke:
        attributes += [f'stroke="{stroke}"', f'stroke-width="{_num(width)}"']
        if dash:
            attributes.append(f'stroke-dasharray="{dash}"')
    return f'<rect {" ".join(attributes)}/>'


def _content(x: float, y: float, w: float, h: float, tone: Tone, title: Optional[TextLike],
             lines: Sequence[TextLike], *, align: str, pad: float, title_size: float,
             line_size: float, gap: float, context: str, top_inset: float = 0.0,
             valign: str = 'middle') -> str:
    parsed: List[Line] = []
    if title is not None:
        heading = _line(title, size=title_size, bold=True, color=tone.text)
        # A code() title keeps its font but takes the tone's colour and weight.
        parsed.append(Line(heading.text, heading.size, True, heading.mono, heading.color or tone.text))
    parsed += [_line(value, size=line_size, color=INK) for value in lines]
    if not parsed:
        return ''
    inner_w = w - 2 * pad
    block_h = _block_height(parsed, gap)
    available_h = h - 2 * pad - top_inset
    if block_h > available_h + 0.5:
        raise LayoutError(f'{context}: text needs {block_h:.0f} units of height, only {available_h:.0f} fit')
    top = y + top_inset + pad
    if valign == 'middle':
        top += (available_h - block_h) / 2
    tx = x + w / 2 if align == 'center' else x + pad
    anchor = 'middle' if align == 'center' else 'start'
    svg, _ = text_block(tx, top, parsed, anchor=anchor, gap=gap, max_width=inner_w, context=context)
    return svg


def box(x: float, y: float, w: float, h: float, tone: Tone, title: Optional[TextLike] = None,
        lines: Sequence[TextLike] = (), *, align: str = 'center', pad: float = 10,
        title_size: float = HEADING_SIZE, line_size: float = BODY_SIZE, gap: float = 5,
        radius: float = 10, dashed: bool = False, filled: bool = True, stroke_width: float = 1.5,
        valign: str = 'middle') -> str:
    """A component: a rounded rectangle with a bold title and detail lines.

    ``valign='top'`` turns it into a card whose header leaves room for
    nested shapes below it.
    """
    shape = _rect(x, y, w, h, fill=tone.fill if filled else SURFACE, stroke=tone.stroke,
                  radius=radius, width=stroke_width, dash='6 4' if dashed else None)
    label = _content(x, y, w, h, tone, title, lines, align=align, pad=pad, title_size=title_size,
                     line_size=line_size, gap=gap, context=f'box {title!r}', valign=valign)
    return f'<g>{shape}\n{label}</g>'


def zone(x: float, y: float, w: float, h: float, tone: Tone, label: str,
         sublabel: Optional[str] = None, *, dashed: bool = False, tab_x: Optional[float] = None) -> str:
    """An ownership area. The label sits on the top border, like a tab.

    ``tab_x`` moves the tab (default: near the left corner) out of the way
    of arrows that cross the top border.
    """
    shape = _rect(x, y, w, h, fill=tone.tint, stroke=tone.stroke, radius=16, width=1.5,
                  dash='8 5' if dashed else None)
    caption = label.upper()
    caption_w = text_width(caption, SMALL_SIZE, bold=True) + 1.2 * len(caption)
    parts = [shape]
    sub_w = 0.0
    if sublabel:
        sub_w = text_width(sublabel, SMALL_SIZE) + 10
    tab_w = caption_w + sub_w + 22
    left = x + 16 if tab_x is None else tab_x
    if left + tab_w > x + w - 8 or left < x + 8:
        raise LayoutError(f'zone {label!r}: its label does not fit on the top border')
    parts.append(_rect(left, y - 11, tab_w, 22, fill=SURFACE, stroke=tone.stroke, radius=11, width=1.2))
    parts.append(text(left + 11, y + 4.2, caption, size=SMALL_SIZE, bold=True, color=tone.text, letter_spacing=1.2))
    if sublabel:
        parts.append(text(left + 11 + caption_w + 8, y + 4.2, sublabel, size=SMALL_SIZE, color=MUTED))
    return '<g>' + '\n'.join(parts) + '</g>'


def store(x: float, y: float, w: float, h: float, tone: Tone, title: Optional[TextLike],
          lines: Sequence[TextLike] = (), *, line_size: float = BODY_SIZE,
          title_size: float = HEADING_SIZE, valign: str = 'middle') -> str:
    """A database or durable store, drawn as a cylinder."""
    ry = min(10.0, h / 6)
    body = (
        f'<path d="M{_num(x)} {_num(y + ry)} '
        f'A{_num(w / 2)} {_num(ry)} 0 0 1 {_num(x + w)} {_num(y + ry)} '
        f'L{_num(x + w)} {_num(y + h - ry)} '
        f'A{_num(w / 2)} {_num(ry)} 0 0 1 {_num(x)} {_num(y + h - ry)} Z" '
        f'fill="{tone.fill}" stroke="{tone.stroke}" stroke-width="1.5"/>'
    )
    rim = (
        f'<path d="M{_num(x)} {_num(y + ry)} '
        f'A{_num(w / 2)} {_num(ry)} 0 0 0 {_num(x + w)} {_num(y + ry)}" '
        f'fill="none" stroke="{tone.stroke}" stroke-width="1.5"/>'
    )
    label = ''
    if title or lines:
        label = _content(x, y, w, h, tone, title or None, lines, align='center', pad=8,
                         title_size=title_size, line_size=line_size, gap=4,
                         context=f'store {title!r}', top_inset=ry * 1.2, valign=valign)
    return f'<g>{body}\n{rim}\n{label}</g>'


def document(x: float, y: float, w: float, h: float, tone: Tone, title: Optional[TextLike] = None,
             lines: Sequence[TextLike] = (), *, align: str = 'start', title_size: float = BODY_SIZE + 1,
             line_size: float = SMALL_SIZE, gap: float = 4, fold: float = 12) -> str:
    """A file or record set: a sheet with a folded corner."""
    outline = (
        f'<path d="M{_num(x)} {_num(y)} L{_num(x + w - fold)} {_num(y)} L{_num(x + w)} {_num(y + fold)} '
        f'L{_num(x + w)} {_num(y + h)} L{_num(x)} {_num(y + h)} Z" fill="{tone.fill}" '
        f'stroke="{tone.stroke}" stroke-width="1.3" stroke-linejoin="round"/>'
    )
    corner = (
        f'<path d="M{_num(x + w - fold)} {_num(y)} L{_num(x + w - fold)} {_num(y + fold)} '
        f'L{_num(x + w)} {_num(y + fold)}" fill="{SURFACE}" stroke="{tone.stroke}" '
        f'stroke-width="1.3" stroke-linejoin="round"/>'
    )
    label = _content(x, y, w, h, tone, title, lines, align=align, pad=9, title_size=title_size,
                     line_size=line_size, gap=gap, context=f'document {title!r}')
    return f'<g>{outline}\n{corner}\n{label}</g>'


def browser(x: float, y: float, w: float, h: float, tone: Tone, title: TextLike,
            lines: Sequence[TextLike] = ()) -> str:
    """A web page or user interface, drawn as a browser window."""
    bar = 18
    parts = [
        _rect(x, y, w, h, fill=SURFACE, stroke=tone.stroke, radius=8),
        f'<path d="M{_num(x + 0.75)} {_num(y + bar)} L{_num(x + w - 0.75)} {_num(y + bar)}" '
        f'stroke="{tone.stroke}" stroke-width="1.2"/>',
    ]
    for index in range(3):
        parts.append(f'<circle cx="{_num(x + 12 + index * 10)}" cy="{_num(y + bar / 2)}" r="3" fill="{tone.stroke}" '
                     f'fill-opacity="0.45"/>')
    parts.append(_content(x, y, w, h, tone, title, lines, align='center', pad=8, title_size=HEADING_SIZE,
                          line_size=BODY_SIZE, gap=4, context=f'browser {title!r}', top_inset=bar))
    return '<g>' + '\n'.join(parts) + '</g>'


def chevron(x: float, y: float, w: float, h: float, tone: Tone, lines: Sequence[TextLike], *,
            tip: float = 14, first: bool = False, size: float = SMALL_SIZE, filled: bool = True) -> str:
    """One stage of a left-to-right sequence. Chain chevrons with ``x += w - tip / 2``."""
    notch = 0 if first else tip
    points = [(x, y), (x + w - tip, y), (x + w, y + h / 2), (x + w - tip, y + h), (x, y + h), (x + notch, y + h / 2)]
    shape = (f'<path d="M{" L".join(f"{_num(px)} {_num(py)}" for px, py in points)} Z" '
             f'fill="{tone.fill if filled else SURFACE}" stroke="{tone.stroke}" stroke-width="1.5" '
             f'stroke-linejoin="round"/>')
    inner = w - tip - notch / 2 - 8
    parsed = [_line(value, size=size, bold=True, color=tone.text) for value in lines]
    block_h = _block_height(parsed, 3)
    center = x + (w - tip + notch) / 2 + 2
    svg, _ = text_block(center, y + (h - block_h) / 2, parsed, anchor='middle', gap=3, max_width=inner,
                        context=f'chevron {lines!r}')
    return f'<g>{shape}\n{svg}</g>'


def pill(x: float, y: float, label: TextLike, tone: Tone, *, size: float = SMALL_SIZE,
         anchor: str = 'start', filled: bool = True) -> Tuple[str, float]:
    """A short tag. ``y`` is the vertical centre. Returns the SVG and width."""
    line = _line(label, size=size, color=tone.text)
    width = line.width() + 16
    height = size + 9
    left = x - width / 2 if anchor == 'middle' else (x - width if anchor == 'end' else x)
    shape = _rect(left, y - height / 2, width, height, fill=tone.fill if filled else SURFACE,
                  stroke=tone.stroke, radius=height / 2, width=1.1)
    label_svg = text(left + width / 2, y + size * 0.35, line, anchor='middle', color=tone.text)
    return f'<g>{shape}\n{label_svg}</g>', width


def step(cx: float, cy: float, number: Union[int, str], *, radius: float = 11) -> str:
    """A numbered reading-order marker; the page text explains each number."""
    return (
        f'<g><circle cx="{_num(cx)}" cy="{_num(cy)}" r="{_num(radius)}" fill="{INK}" '
        f'stroke="{SURFACE}" stroke-width="2"/>\n'
        + text(cx, cy + 4.3, str(number), size=12.5, bold=True, color=SURFACE, anchor='middle')
        + '</g>'
    )


Point = Tuple[float, float]

_STYLES = {
    'flow': None,          # data moves along the arrow
    'invoke': '7 5',       # one part starts or controls another
    'optional': '2.5 4',   # optional input or cache reuse
}


def _arrow_head(tip: Point, before: Point, color: str, size: float = 9) -> str:
    angle = math.atan2(tip[1] - before[1], tip[0] - before[0])
    spread = math.radians(26)
    left = (tip[0] - size * math.cos(angle - spread), tip[1] - size * math.sin(angle - spread))
    right = (tip[0] - size * math.cos(angle + spread), tip[1] - size * math.sin(angle + spread))
    return (f'<path d="M{_num(left[0])} {_num(left[1])} L{_num(tip[0])} {_num(tip[1])} '
            f'L{_num(right[0])} {_num(right[1])} Z" fill="{color}" stroke="{color}" '
            f'stroke-width="1" stroke-linejoin="round"/>')


def _rounded_path(points: Sequence[Point], radius: float) -> str:
    """An orthogonal or diagonal polyline with softened corners."""
    commands = [f'M{_num(points[0][0])} {_num(points[0][1])}']
    for index in range(1, len(points) - 1):
        previous, corner, following = points[index - 1], points[index], points[index + 1]
        in_len = math.dist(previous, corner)
        out_len = math.dist(corner, following)
        r = min(radius, in_len / 2, out_len / 2)
        if r <= 0.5:
            commands.append(f'L{_num(corner[0])} {_num(corner[1])}')
            continue
        start = (corner[0] + (previous[0] - corner[0]) * r / in_len, corner[1] + (previous[1] - corner[1]) * r / in_len)
        end = (corner[0] + (following[0] - corner[0]) * r / out_len, corner[1] + (following[1] - corner[1]) * r / out_len)
        commands.append(f'L{_num(start[0])} {_num(start[1])}')
        commands.append(f'Q{_num(corner[0])} {_num(corner[1])} {_num(end[0])} {_num(end[1])}')
    commands.append(f'L{_num(points[-1][0])} {_num(points[-1][1])}')
    return ' '.join(commands)


def arrow(points: Sequence[Point], *, kind: str = 'flow', color: str = MUTED, width: float = 1.8,
          start_head: bool = False, end_head: bool = True, label: Optional[TextLike] = None,
          label_at: Optional[Point] = None, label_tone: Optional[Tone] = None, corner: float = 10) -> str:
    """Connect points. ``kind`` is ``flow``, ``invoke`` or ``optional``."""
    if kind not in _STYLES:
        raise ValueError(f'Unknown arrow kind {kind!r}')
    if len(points) < 2:
        raise ValueError('An arrow needs at least two points')
    parts = []
    dash = _STYLES[kind]
    path = _rounded_path(points, corner)
    attributes = f'd="{path}" fill="none" stroke="{color}" stroke-width="{_num(width)}" stroke-linecap="round" stroke-linejoin="round"'
    if dash:
        attributes += f' stroke-dasharray="{dash}"'
    parts.append(f'<path {attributes}/>')
    if end_head:
        parts.append(_arrow_head(points[-1], points[-2], color))
    if start_head:
        parts.append(_arrow_head(points[0], points[1], color))
    if label is not None:
        if label_at is None:
            first, second = points[len(points) // 2 - 1], points[len(points) // 2]
            label_at = ((first[0] + second[0]) / 2, (first[1] + second[1]) / 2)
        tone = label_tone or Tone(color, SURFACE, color, SURFACE)
        tag, _ = pill(label_at[0], label_at[1], label, tone, anchor='middle', filled=False)
        parts.append(tag)
    return '<g>' + '\n'.join(parts) + '</g>'


def note(x: float, y: float, lines: Sequence[TextLike], *, color: str = MUTED, anchor: str = 'start',
         size: float = SMALL_SIZE, gap: float = 4) -> str:
    """Free annotation text, top-aligned at ``y``."""
    svg, _ = text_block(x, y, [_line(value, size=size, color=color) for value in lines],
                        anchor=anchor, color=color, gap=gap)
    return svg


def divider(x1: float, y1: float, x2: float, y2: float, *, color: str = FAINT, dash: Optional[str] = '4 4',
            width: float = 1.2) -> str:
    attributes = f'd="M{_num(x1)} {_num(y1)} L{_num(x2)} {_num(y2)}" stroke="{color}" stroke-width="{_num(width)}"'
    if dash:
        attributes += f' stroke-dasharray="{dash}"'
    return f'<path {attributes}/>'


def node(cx: float, cy: float, tone: Tone, *, radius: float = 9, letter: Optional[str] = None,
         hollow: bool = False) -> str:
    """A map marker: a filled circle, optionally lettered like the map's P/S/D icons."""
    parts = [f'<circle cx="{_num(cx)}" cy="{_num(cy)}" r="{_num(radius)}" '
             f'fill="{SURFACE if hollow else tone.stroke}" stroke="{tone.stroke if hollow else SURFACE}" '
             f'stroke-width="{2.5 if hollow else 2}"/>']
    if letter:
        parts.append(text(cx, cy + radius * 0.42, letter, size=radius * 1.15, bold=True,
                          color=tone.stroke if hollow else SURFACE, anchor='middle'))
    return '<g>' + '\n'.join(parts) + '</g>'


LegendItem = Tuple[str, Union[Tone, str], str]


def legend(x: float, y: float, items: Iterable[LegendItem], *, columns: int = 0, spacing: float = 26,
           column_gap: float = 28) -> Tuple[str, float]:
    """A one-row (or wrapped) legend. Items are ``(kind, tone_or_color, label)``.

    ``kind`` is ``box``, ``zone``, ``store``, ``node`` (optionally lettered,
    ``node:P``; ``hollow:S`` for an outlined marker), an arrow kind (``flow``,
    ``invoke``, ``optional``) or a plain association without arrowhead
    (``link``, ``link-dashed``). Returns the SVG and the total width.
    """
    parts = []
    cursor = x
    row = 0
    entries = list(items)
    for index, (kind, tone, label) in enumerate(entries):
        if columns and index and index % columns == 0:
            row += 1
            cursor = x
        cy = y + row * spacing
        color = tone.stroke if isinstance(tone, Tone) else tone
        if kind in ('box', 'zone'):
            fill = tone.tint if kind == 'zone' and isinstance(tone, Tone) else (
                tone.fill if isinstance(tone, Tone) else SURFACE)
            parts.append(_rect(cursor, cy - 8, 22, 16, fill=fill, stroke=color, radius=4, width=1.4))
            swatch = 22
        elif kind == 'store':
            parts.append(store(cursor, cy - 10, 18, 20, tone if isinstance(tone, Tone) else EXTERNAL, None))
            swatch = 18
        elif kind.split(':')[0] in ('node', 'hollow'):
            letter = kind.split(':', 1)[1] if ':' in kind else None
            parts.append(node(cursor + 9, cy, tone if isinstance(tone, Tone) else EXTERNAL, radius=9,
                              letter=letter, hollow=kind.startswith('hollow')))
            swatch = 18
        elif kind in ('link', 'link-dashed'):
            parts.append(arrow([(cursor, cy), (cursor + 34, cy)], kind='invoke' if kind == 'link-dashed' else 'flow',
                               color=color, width=2.2, end_head=False))
            swatch = 34
        else:
            parts.append(arrow([(cursor, cy), (cursor + 34, cy)], kind=kind, color=color, width=1.8))
            swatch = 34
        parts.append(text(cursor + swatch + 8, cy + 4.3, label, size=SMALL_SIZE, color=INK))
        cursor += swatch + 8 + text_width(label, SMALL_SIZE) + column_gap
    return '<g>' + '\n'.join(parts) + '</g>', cursor - x - column_gap


# White space kept around the drawing, and the closest any shape may come to
# the left or right edge of the canvas.
CANVAS_PAD = 22.0
CANVAS_EDGE = 12.0

_ELEMENT = re.compile(r'<(rect|circle|path)\b([^>]*)/?>|<text\b([^>]*)>(.*?)</text>', re.DOTALL)
_ATTRIBUTE = re.compile(r'([\w:-]+)="([^"]*)"')
_PATH_TOKEN = re.compile(r'[MLQAZ]|-?\d+(?:\.\d+)?')


def _path_points(data: str) -> List[Tuple[float, float]]:
    """Points that bound a path of the kit's absolute M, L, Q and A commands."""
    tokens = _PATH_TOKEN.findall(data)
    points: List[Tuple[float, float]] = []
    index, command = 0, 'M'
    while index < len(tokens):
        if tokens[index] in 'MLQAZ':
            command = tokens[index]
            index += 1
            continue
        if command == 'A':
            # The kit's arcs join two points at the same height (a cylinder
            # rim), so they bulge by at most ``ry`` vertically.
            ry, x, y = (float(tokens[index + offset]) for offset in (1, 5, 6))
            points += [(x, y - ry), (x, y + ry)]
            index += 7
        else:
            # M, L and the control and end points of Q: x, y pairs.
            points.append((float(tokens[index]), float(tokens[index + 1])))
            index += 2
    return points


def _extent(body: str) -> Tuple[float, float, float, float]:
    """The bounding box ``(left, top, right, bottom)`` of everything drawn."""
    boxes = []
    for match in _ELEMENT.finditer(body):
        kind = match.group(1) or 'text'
        values = dict(_ATTRIBUTE.findall(match.group(2) or match.group(3)))
        number = lambda name: float(values.get(name, 0))  # noqa: E731
        if kind == 'rect':
            boxes.append((number('x'), number('y'), number('x') + number('width'), number('y') + number('height')))
        elif kind == 'circle':
            r = number('r')
            boxes.append((number('cx') - r, number('cy') - r, number('cx') + r, number('cy') + r))
        elif kind == 'path':
            points = _path_points(values.get('d', ''))
            if points:
                xs, ys = [x for x, _ in points], [y for _, y in points]
                boxes.append((min(xs), min(ys), max(xs), max(ys)))
        else:
            size = number('font-size')
            label = unescape(match.group(4))
            width = text_width(label, size, bold=values.get('font-weight') == '600',
                               mono=values.get('font-family') == MONO)
            width += number('letter-spacing') * len(label)
            x = number('x')
            left = {'middle': x - width / 2, 'end': x - width}.get(values.get('text-anchor'), x)
            boxes.append((left, number('y') - size * 0.8, left + width, number('y') + size * 0.25))
    if not boxes:
        return 0.0, 0.0, 0.0, 0.0
    return (min(b[0] for b in boxes), min(b[1] for b in boxes),
            max(b[2] for b in boxes), max(b[3] for b in boxes))


class Diagram:
    """A canvas. Add SVG fragments with ``add`` and serialize with ``render``.

    A diagram has no title of its own: the page heading above it names it,
    and the sentence below it says what to look at. ``height`` bounds the
    layout; the rendered file is cropped to the drawing plus a margin.
    """

    def __init__(self, width: float, height: float, title: str, description: str):
        self.width = width
        self.height = height
        self.title = title
        self.description = description
        self._parts: List[str] = []

    def add(self, *fragments: str) -> 'Diagram':
        self._parts.extend(fragment for fragment in fragments if fragment)
        return self

    def render(self) -> str:
        body = '\n'.join(self._parts)
        left, top, right, bottom = _extent(body)
        if left < CANVAS_EDGE or right > self.width - CANVAS_EDGE:
            raise LayoutError(
                f'{self.title!r}: the drawing spans x {left:.0f} to {right:.0f}; keep it within '
                f'{CANVAS_EDGE:.0f} and {self.width - CANVAS_EDGE:.0f}'
            )
        if top < 0 or bottom > self.height:
            raise LayoutError(f'{self.title!r}: the drawing spans y {top:.0f} to {bottom:.0f}, '
                              f'outside the canvas height {self.height:.0f}')
        origin = math.floor(top - CANVAS_PAD)
        height = math.ceil(bottom + CANVAS_PAD) - origin
        width = _num(self.width)
        return (
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 {origin} {width} {height}" '
            f'width="{width}" height="{height}" role="img" aria-labelledby="diagram-title diagram-desc">\n'
            f'<title id="diagram-title">{escape(self.title)}</title>\n'
            f'<desc id="diagram-desc">{escape(self.description)}</desc>\n'
            f'<!-- Generated by documentation/diagrams/build.py (kit v{KIT_VERSION}). '
            f'Edit the diagram source in documentation/diagrams/, not this file. -->\n'
            f'<rect x="0" y="{origin}" width="{width}" height="{height}" fill="{SURFACE}"/>\n'
            f'{body}\n'
            f'</svg>\n'
        )
