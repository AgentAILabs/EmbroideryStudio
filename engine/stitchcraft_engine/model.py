"""Common stitch data model. Internal unit: millimetres. Y axis points DOWN (canvas convention).
The DST layer converts to 0.1 mm units with Y pointing UP."""
from __future__ import annotations
from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional, Tuple
from . import CONTRACT_VERSION

Point = Tuple[float, float]


class Cmd(str, Enum):
    STITCH = "stitch"
    JUMP = "jump"
    TRIM = "trim"
    COLOR_CHANGE = "color_change"
    END = "end"


@dataclass
class Stitch:
    x: float
    y: float
    cmd: Cmd = Cmd.STITCH
    thread: int = 0
    object_id: Optional[str] = None


@dataclass
class ThreadColor:
    name: str
    hex: str  # "#rrggbb"


@dataclass
class Pattern:
    name: str = "design"
    stitches: List[Stitch] = field(default_factory=list)
    threads: List[ThreadColor] = field(default_factory=list)

    def counts(self) -> dict:
        c = {k.value: 0 for k in Cmd}
        for s in self.stitches:
            c[s.cmd.value] += 1
        return c

    def bbox(self) -> Optional[Tuple[float, float, float, float]]:
        pts = [(s.x, s.y) for s in self.stitches if s.cmd in (Cmd.STITCH, Cmd.JUMP)]
        if not pts:
            return None
        xs, ys = [p[0] for p in pts], [p[1] for p in pts]
        return min(xs), min(ys), max(xs), max(ys)

    def to_dict(self) -> dict:
        """Versioned JSON contract between the .NET host and the engine."""
        return {
            "schema_version": CONTRACT_VERSION,
            "name": self.name,
            "units": "mm",
            "y_axis": "down",
            "threads": [{"name": t.name, "hex": t.hex} for t in self.threads],
            "stitches": [[round(s.x, 4), round(s.y, 4), s.cmd.value, s.thread, s.object_id]
                         for s in self.stitches],
        }

    @staticmethod
    def from_dict(d: dict) -> "Pattern":
        if d.get("schema_version", "").split(".")[0] != CONTRACT_VERSION.split(".")[0]:
            raise ValueError(f"Unsupported schema_version {d.get('schema_version')!r}")
        return Pattern(
            name=d["name"],
            threads=[ThreadColor(t["name"], t["hex"]) for t in d["threads"]],
            stitches=[Stitch(x, y, Cmd(c), th, oid) for x, y, c, th, oid in d["stitches"]],
        )
