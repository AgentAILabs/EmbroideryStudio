from __future__ import annotations
from .model import Cmd, Pattern


def preview_svg(p: Pattern, hoop_w: float = 0, hoop_h: float = 0, show_jumps: bool = True) -> str:
    bb = p.bbox()
    pad = 5
    x0, y0, x1, y1 = bb
    if hoop_w and hoop_h:
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        x0, x1, y0, y1 = cx - hoop_w / 2, cx + hoop_w / 2, cy - hoop_h / 2, cy + hoop_h / 2
    body, prev, thread = [], None, p.stitches[0].thread
    for s in p.stitches:
        if s.cmd == Cmd.COLOR_CHANGE:
            thread = s.thread
        elif s.cmd == Cmd.JUMP:
            if show_jumps and prev:
                body.append(f'<line x1="{prev[0]:.2f}" y1="{prev[1]:.2f}" x2="{s.x:.2f}" y2="{s.y:.2f}" stroke="#999" stroke-width="0.1" stroke-dasharray="0.6 0.6"/>')
            prev = (s.x, s.y)
        elif s.cmd == Cmd.STITCH:
            if prev:
                col = p.threads[thread].hex if p.threads else "#000"
                body.append(f'<line x1="{prev[0]:.2f}" y1="{prev[1]:.2f}" x2="{s.x:.2f}" y2="{s.y:.2f}" stroke="{col}" stroke-width="0.25" stroke-linecap="round"/>')
            prev = (s.x, s.y)
    hoop = f'<rect x="{x0:.2f}" y="{y0:.2f}" width="{x1 - x0:.2f}" height="{y1 - y0:.2f}" fill="none" stroke="#2563eb" stroke-width="0.4" stroke-dasharray="2 1"/>' if hoop_w else ""
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{x0 - pad:.2f} {y0 - pad:.2f} {x1 - x0 + 2 * pad:.2f} {y1 - y0 + 2 * pad:.2f}" '
            f'width="800"><rect x="{x0 - pad}" y="{y0 - pad}" width="{x1 - x0 + 2 * pad}" height="{y1 - y0 + 2 * pad}" fill="#f8fafc"/>{hoop}{"".join(body)}</svg>')


def thumbnail_svg(p: Pattern, px: int = 240, bg: str = "#f8fafc", pad_mm: float = 3.0, stroke_mm: float = 0.55) -> str:
    """Compact square thumbnail: one <path> per colour run (in stitching order, so later colours overlay earlier ones),
    a path breaks at every jump / trim. Coordinates are rounded to 0.1 mm. Much smaller than preview_svg."""
    bb = p.bbox()
    if bb is None:
        raise ValueError("pattern has no stitches")
    x0, y0, x1, y1 = bb
    side = max(x1 - x0, y1 - y0) + 2 * pad_mm
    cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
    vx, vy = cx - side / 2, cy - side / 2
    paths, cur_d, cur_col, pen_down = [], [], None, False

    def flush():
        nonlocal cur_d
        if cur_d and cur_col is not None:
            paths.append(f'<path d="{"".join(cur_d)}" stroke="{cur_col}"/>')
        cur_d = []

    thread = p.stitches[0].thread if p.stitches else 0
    last = None
    for s in p.stitches:
        if s.cmd == Cmd.COLOR_CHANGE:
            flush(); thread = s.thread; pen_down = False
        elif s.cmd in (Cmd.JUMP, Cmd.TRIM):
            pen_down = False
            if s.cmd == Cmd.JUMP:
                last = (s.x, s.y)
        elif s.cmd == Cmd.STITCH:
            col = p.threads[thread].hex if p.threads else "#000000"
            if col != cur_col:
                flush(); cur_col = col; pen_down = False
            x, y = f"{s.x:.1f}", f"{s.y:.1f}"
            if not pen_down:
                if last is not None and (abs(last[0] - s.x) > 1e-6 or abs(last[1] - s.y) > 1e-6):
                    cur_d.append(f"M{last[0]:.1f} {last[1]:.1f}L{x} {y}")
                else:
                    cur_d.append(f"M{x} {y}")
                pen_down = True
            else:
                cur_d.append(f"L{x} {y}")
            last = (s.x, s.y)
    flush()
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="{vx:.2f} {vy:.2f} {side:.2f} {side:.2f}" width="{px}" height="{px}">'
            f'<rect x="{vx:.2f}" y="{vy:.2f}" width="{side:.2f}" height="{side:.2f}" fill="{bg}"/>'
            f'<g fill="none" stroke-width="{stroke_mm}" stroke-linecap="round" stroke-linejoin="round">{"".join(paths)}</g></svg>')
