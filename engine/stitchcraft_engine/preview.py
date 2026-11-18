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
