"""Ball-to-hitter reach check for a finished report: how far the ball is from the credited hitter at contact.

    python scripts/hit_reach.py <match folder: report.json + detections.npz>

Prints per-shot distance (in body heights, from the hitter's box grown by a racket's reach) for analysis.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from padel_analyzer.engine import ball as B  # noqa: E402
from padel_analyzer.engine import court as C  # noqa: E402
from padel_analyzer.engine.detect import Detections  # noqa: E402


def reach(folder: Path) -> list[dict]:
    r = json.loads((folder / "report.json").read_text())
    d = Detections.load(folder / "detections.npz")
    cal = C.Calibration.from_dict(r["calibration"])
    ev = B.track_for_events(d.ball)
    out = []
    for s in r["shots"]:
        f = s["frame"]
        bp = next((ev.xy[f + k] for k in (0, -1, 1, -2, 2, -3, 3) if 0 <= f + k < d.n and np.isfinite(ev.xy[f + k, 0])),
                  None)
        b = d.pose_box[f]
        ok = np.where(b[:, 4] > 0.2)[0]
        dist = None
        if bp is not None and s.get("pos_m") and len(ok):
            foot = cal.to_px(np.array([s["pos_m"]]))[0]
            bot = np.c_[(b[ok, 0] + b[ok, 2]) / 2, b[ok, 3]]
            j = ok[np.argmin(np.linalg.norm(bot - foot, axis=1))]
            x0, y0, x1, y1 = b[j, :4]
            h = max(y1 - y0, 30.0)
            dx = max(x0 - 0.5 * h - bp[0], 0, bp[0] - (x1 + 0.5 * h))
            dy = max(y0 - 0.5 * h - bp[1], 0, bp[1] - y1)
            dist = float(np.hypot(dx, dy) / h)
        out.append({"id": s["id"], "t": s["t"], "frame": f, "reach": dist})
    return out


if __name__ == "__main__":
    res = reach(Path(sys.argv[1]))
    v = [x["reach"] for x in res if x["reach"] is not None]
    print(json.dumps({"shots": len(res), "with_ball": len(v), "over_3": sum(x > 3 for x in v),
                      "over_2": sum(x > 2 for x in v)}))
