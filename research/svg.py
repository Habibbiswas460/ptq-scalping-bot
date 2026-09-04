"""Minimal SVG chart primitives — stdlib only, no plotting dependency.

Every mark, tick and label is placed by one scale per axis, and all colour comes from CSS
custom properties so a chart reads correctly in either theme. Charts are emitted as inline
SVG strings and assembled by report.py.
"""
from __future__ import annotations

import datetime as _dt
import html
from typing import Callable, Dict, List, Optional, Sequence, Tuple


def esc(s) -> str:
    return html.escape(str(s), quote=True)


class Scale:
    def __init__(self, d0: float, d1: float, r0: float, r1: float):
        self.d0, self.d1 = float(d0), float(d1)
        if self.d1 == self.d0:
            self.d1 = self.d0 + 1.0
        self.r0, self.r1 = float(r0), float(r1)

    def __call__(self, v: float) -> float:
        return self.r0 + (float(v) - self.d0) / (self.d1 - self.d0) * (self.r1 - self.r0)

    def ticks(self, n: int = 5) -> List[float]:
        step = (self.d1 - self.d0) / max(1, n)
        return [self.d0 + i * step for i in range(n + 1)]


def _t2s(t: _dt.datetime) -> float:
    return t.hour * 3600 + t.minute * 60 + t.second


class Chart:
    """A single plot area with margins, axes and a title."""

    def __init__(self, w: int = 940, h: int = 260, ml: int = 58, mr: int = 18,
                 mt: int = 26, mb: int = 30, title: str = "", subtitle: str = ""):
        self.w, self.h = w, h
        self.ml, self.mr, self.mt, self.mb = ml, mr, mt, mb
        self.title, self.subtitle = title, subtitle
        self.parts: List[str] = []
        self.x: Optional[Scale] = None
        self.y: Optional[Scale] = None

    # -- geometry ----------------------------------------------------
    @property
    def px0(self): return self.ml
    @property
    def px1(self): return self.w - self.mr
    @property
    def py0(self): return self.mt
    @property
    def py1(self): return self.h - self.mb

    def set_time_x(self, t0: _dt.datetime, t1: _dt.datetime):
        self.x = Scale(_t2s(t0), _t2s(t1), self.px0, self.px1)
        self._x_is_time = True

    def set_x(self, d0, d1):
        self.x = Scale(d0, d1, self.px0, self.px1)
        self._x_is_time = False

    def set_y(self, d0, d1, pad: float = 0.06):
        span = (d1 - d0) or 1.0
        self.y = Scale(d0 - span * pad, d1 + span * pad, self.py1, self.py0)

    def X(self, v):
        return self.x(_t2s(v) if isinstance(v, _dt.datetime) else v)

    # -- furniture ---------------------------------------------------
    def grid(self, n: int = 4, y_fmt: Callable = lambda v: f"{v:,.0f}"):
        for v in self.y.ticks(n):
            yy = self.y(v)
            self.parts.append(
                f'<line x1="{self.px0}" y1="{yy:.1f}" x2="{self.px1}" y2="{yy:.1f}" '
                f'stroke="var(--grid)" stroke-width="1"/>')
            self.parts.append(
                f'<text x="{self.px0 - 6}" y="{yy + 3.5:.1f}" text-anchor="end" '
                f'class="ax">{esc(y_fmt(v))}</text>')

    def time_axis(self, t0: _dt.datetime, t1: _dt.datetime, every_min: int = 30):
        cur = t0.replace(second=0, microsecond=0)
        cur += _dt.timedelta(minutes=(-cur.minute) % every_min)
        while cur <= t1:
            xx = self.X(cur)
            self.parts.append(
                f'<line x1="{xx:.1f}" y1="{self.py1}" x2="{xx:.1f}" y2="{self.py1 + 4}" '
                f'stroke="var(--grid-strong)"/>')
            self.parts.append(
                f'<text x="{xx:.1f}" y="{self.py1 + 16}" text-anchor="middle" '
                f'class="ax">{cur.strftime("%H:%M")}</text>')
            cur += _dt.timedelta(minutes=every_min)

    def x_axis_labels(self, pairs: Sequence[Tuple[float, str]]):
        for v, lab in pairs:
            xx = self.x(v)
            self.parts.append(f'<text x="{xx:.1f}" y="{self.py1 + 16}" text-anchor="middle" '
                              f'class="ax">{esc(lab)}</text>')

    # -- marks -------------------------------------------------------
    def line(self, pts: Sequence[Tuple], color: str = "var(--accent)", width: float = 1.3,
             opacity: float = 1.0):
        if len(pts) < 2:
            return
        d = " ".join(("M" if i == 0 else "L") + f"{self.X(t):.1f},{self.y(v):.1f}"
                     for i, (t, v) in enumerate(pts))
        self.parts.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="{width}" '
                          f'opacity="{opacity}" stroke-linejoin="round"/>')

    def area(self, pts: Sequence[Tuple], color: str, opacity: float = 0.12):
        if len(pts) < 2:
            return
        d = " ".join(("M" if i == 0 else "L") + f"{self.X(t):.1f},{self.y(v):.1f}"
                     for i, (t, v) in enumerate(pts))
        d += f" L{self.X(pts[-1][0]):.1f},{self.py1} L{self.X(pts[0][0]):.1f},{self.py1} Z"
        self.parts.append(f'<path d="{d}" fill="{color}" opacity="{opacity}" stroke="none"/>')

    def candles(self, bars: Sequence[Dict], width_px: float = 3.0):
        for b in bars:
            xx = self.X(b["t"])
            up = b["c"] >= b["o"]
            col = "var(--up)" if up else "var(--dn)"
            self.parts.append(
                f'<line x1="{xx:.1f}" y1="{self.y(b["h"]):.1f}" x2="{xx:.1f}" '
                f'y2="{self.y(b["l"]):.1f}" stroke="{col}" stroke-width="1"/>')
            y0, y1 = self.y(b["o"]), self.y(b["c"])
            top, hgt = min(y0, y1), max(0.8, abs(y1 - y0))
            dash = ' stroke-dasharray="1.6 1.4" fill-opacity="0.25"' if b.get("partial") else ''
            self.parts.append(
                f'<rect x="{xx - width_px/2:.1f}" y="{top:.1f}" width="{width_px}" '
                f'height="{hgt:.1f}" fill="{col}" stroke="{col}"{dash}/>')

    def vspan(self, a, b, color: str, opacity: float = 0.13, label: str = ""):
        x0, x1 = self.X(a), self.X(b)
        self.parts.append(f'<rect x="{x0:.1f}" y="{self.py0}" width="{max(1.0, x1-x0):.1f}" '
                          f'height="{self.py1-self.py0}" fill="{color}" opacity="{opacity}"/>')
        if label:
            self.parts.append(f'<text x="{(x0+x1)/2:.1f}" y="{self.py0+11}" text-anchor="middle" '
                              f'class="ax-em">{esc(label)}</text>')

    def vline(self, t, color: str = "var(--ink3)", dash: str = "3 3", width: float = 1.0):
        xx = self.X(t)
        self.parts.append(f'<line x1="{xx:.1f}" y1="{self.py0}" x2="{xx:.1f}" y2="{self.py1}" '
                          f'stroke="{color}" stroke-width="{width}" stroke-dasharray="{dash}"/>')

    def hline(self, v, color: str = "var(--ink3)", dash: str = "3 3"):
        yy = self.y(v)
        self.parts.append(f'<line x1="{self.px0}" y1="{yy:.1f}" x2="{self.px1}" y2="{yy:.1f}" '
                          f'stroke="{color}" stroke-dasharray="{dash}" stroke-width="1"/>')

    def marker(self, t, v, kind: str = "entry", color: str = "var(--accent)", size: float = 5.0,
               title: str = ""):
        xx, yy = self.X(t), self.y(v)
        tip = f'<title>{esc(title)}</title>' if title else ''
        if kind == "entry":
            self.parts.append(f'<path d="M{xx:.1f},{yy-size:.1f} L{xx+size:.1f},{yy+size*0.8:.1f} '
                              f'L{xx-size:.1f},{yy+size*0.8:.1f} Z" fill="{color}" '
                              f'stroke="var(--surface)" stroke-width="0.8">{tip}</path>')
        elif kind == "exit":
            self.parts.append(f'<rect x="{xx-size*0.8:.1f}" y="{yy-size*0.8:.1f}" '
                              f'width="{size*1.6}" height="{size*1.6}" fill="{color}" '
                              f'stroke="var(--surface)" stroke-width="0.8">{tip}</rect>')
        else:
            self.parts.append(f'<circle cx="{xx:.1f}" cy="{yy:.1f}" r="{size}" fill="{color}" '
                              f'stroke="var(--surface)" stroke-width="0.6">{tip}</circle>')

    def dot(self, x, y, r=2.0, color="var(--accent)", opacity=0.7, title=""):
        tip = f'<title>{esc(title)}</title>' if title else ''
        self.parts.append(f'<circle cx="{self.x(x):.1f}" cy="{self.y(y):.1f}" r="{r}" '
                          f'fill="{color}" opacity="{opacity}">{tip}</circle>')

    def bar(self, x, y0, y1, w, color, opacity=1.0, title=""):
        xx = self.x(x)
        a, b = self.y(y0), self.y(y1)
        tip = f'<title>{esc(title)}</title>' if title else ''
        self.parts.append(f'<rect x="{xx-w/2:.1f}" y="{min(a,b):.1f}" width="{w}" '
                          f'height="{max(0.8, abs(b-a)):.1f}" fill="{color}" '
                          f'opacity="{opacity}">{tip}</rect>')

    def text(self, x, y, s, anchor="start", cls="ax", raw_xy=False):
        xx = x if raw_xy else self.X(x)
        yy = y if raw_xy else self.y(y)
        self.parts.append(f'<text x="{xx:.1f}" y="{yy:.1f}" text-anchor="{anchor}" '
                          f'class="{cls}">{esc(s)}</text>')

    # -- output ------------------------------------------------------
    def render(self) -> str:
        head = ""
        if self.title:
            head += (f'<text x="{self.px0}" y="14" class="ct">{esc(self.title)}</text>')
        if self.subtitle:
            head += (f'<text x="{self.px1}" y="14" text-anchor="end" class="cs">'
                     f'{esc(self.subtitle)}</text>')
        frame = (f'<line x1="{self.px0}" y1="{self.py1}" x2="{self.px1}" y2="{self.py1}" '
                 f'stroke="var(--grid-strong)"/>')
        return (f'<svg viewBox="0 0 {self.w} {self.h}" class="chart" '
                f'preserveAspectRatio="xMidYMid meet">{head}{"".join(self.parts)}{frame}</svg>')


def heatmap(rows: Sequence[str], cols: Sequence[str], values: Dict[Tuple[str, str], Optional[float]],
            fmt: Callable = lambda v: f"{v:.0f}", w: int = 940, cell_h: int = 26,
            label_w: int = 118, title: str = "", legend: str = "") -> str:
    """Row/column grid shaded by value. None renders as an explicit 'no data' cell rather
    than as zero, so a gap never reads as a measurement."""
    nums = [v for v in values.values() if v is not None]
    lo, hi = (min(nums), max(nums)) if nums else (0.0, 1.0)
    if hi == lo:
        hi = lo + 1.0
    cw = (w - label_w - 8) / max(1, len(cols))
    h = 34 + cell_h * len(rows) + 20
    p = [f'<text x="0" y="12" class="ct">{esc(title)}</text>']
    if legend:
        p.append(f'<text x="{w}" y="12" text-anchor="end" class="cs">{esc(legend)}</text>')
    for j, c in enumerate(cols):
        p.append(f'<text x="{label_w + cw*(j+0.5):.1f}" y="30" text-anchor="middle" '
                 f'class="ax">{esc(c)}</text>')
    for i, r in enumerate(rows):
        y = 34 + i * cell_h
        p.append(f'<text x="{label_w-8}" y="{y+cell_h*0.66:.1f}" text-anchor="end" '
                 f'class="ax-em">{esc(r)}</text>')
        for j, c in enumerate(cols):
            v = values.get((r, c))
            x = label_w + cw * j
            if v is None:
                p.append(f'<rect x="{x:.1f}" y="{y}" width="{cw-1.5:.1f}" height="{cell_h-2}" '
                         f'fill="var(--nodata)" stroke="var(--surface)"/>')
                p.append(f'<text x="{x+cw/2:.1f}" y="{y+cell_h*0.66:.1f}" text-anchor="middle" '
                         f'class="hm-none">no data</text>')
                continue
            k = (v - lo) / (hi - lo)
            p.append(f'<rect x="{x:.1f}" y="{y}" width="{cw-1.5:.1f}" height="{cell_h-2}" '
                     f'fill="var(--heat)" fill-opacity="{0.10 + 0.80*k:.3f}" '
                     f'stroke="var(--surface)"><title>{esc(r)} · {esc(c)} · {esc(fmt(v))}</title></rect>')
            p.append(f'<text x="{x+cw/2:.1f}" y="{y+cell_h*0.66:.1f}" text-anchor="middle" '
                     f'class="hm {"hm-hi" if k > 0.55 else ""}">{esc(fmt(v))}</text>')
    return (f'<svg viewBox="0 0 {w} {h}" class="chart" preserveAspectRatio="xMidYMid meet">'
            f'{"".join(p)}</svg>')
