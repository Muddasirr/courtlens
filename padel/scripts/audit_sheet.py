"""Visual audit sheet: crop the hitter of sampled shots at -0.2 s / contact / +0.2 s, for labelling by eye.

    python scripts/audit_sheet.py <match folder: report.json + detections.npz> <video> <out.jpg>
           [--kind all|smash|...] [--n 20] [--seed 0]

Writes out.jpg and out.jpg.json (the sampled shots, in sheet order). Same seed + same report = same sample.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from padel_analyzer.engine import court as C  # noqa: E402
from padel_analyzer.engine.detect import Detections  # noqa: E402

TILE = 200


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("video")
    ap.add_argument("out")
    ap.add_argument("--kind", default="all")
    ap.add_argument("--n", type=int, default=20)
    ap.add_argument("--seed", type=int, default=0)
    a = ap.parse_args()
    r = json.loads((a.folder / "report.json").read_text())
    d = Detections.load(a.folder / "detections.npz")
    cal = C.Calibration.from_dict(r["calibration"])
    shots = [s for s in r["shots"] if (a.kind == "all" or s["type"] == a.kind) and s.get("pos_m")]
    random.Random(a.seed).shuffle(shots)
    shots = sorted(shots[: a.n], key=lambda s: s["t"])
    cap = cv2.VideoCapture(a.video)
    fps = cap.get(cv2.CAP_PROP_FPS)
    W, H = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    rows = []
    for i, s in enumerate(shots):
        f = s["frame"]
        foot = cal.to_px(np.array([s["pos_m"]]))[0]
        b = d.pose_box[f]
        ok = b[:, 4] > 0.2
        if ok.any():
            bot = np.c_[(b[:, 0] + b[:, 2]) / 2, b[:, 3]]
            j = np.where(ok)[0][np.argmin(np.linalg.norm(bot[ok] - foot, axis=1))]
            x0, y0, x1, y1 = b[j, :4]
        else:
            x0, y0, x1, y1 = foot[0] - 40, foot[1] - 120, foot[0] + 40, foot[1]
        side = max(y1 - y0, 60) * 1.6
        cx, cy = (x0 + x1) / 2, (y0 + y1) / 2
        tiles = []
        for dt in (-0.2, 0.0, 0.2):
            cap.set(cv2.CAP_PROP_POS_FRAMES, int(f + dt * fps))
            _, fr = cap.read()
            X0, Y0 = int(max(0, cx - side / 2)), int(max(0, cy - side / 2))
            X1, Y1 = int(min(W, cx + side / 2)), int(min(H, cy + side / 2))
            tiles.append(cv2.resize(fr[Y0:Y1, X0:X1], (TILE, TILE)))
        row = np.hstack(tiles)
        lab = f"#{i} t={s['t']:.1f} p{s['player']} {s['type']} {s['type_conf']:.2f} oh={int(s['overhead'])}"
        cv2.rectangle(row, (0, 0), (3 * TILE, 18), (0, 0, 0), -1)
        cv2.putText(row, lab, (3, 13), 0, 0.42, (0, 255, 255), 1)
        rows.append(row)
    while len(rows) % 2:
        rows.append(np.zeros_like(rows[0]))
    sheet = np.vstack([np.hstack(rows[k:k + 2]) for k in range(0, len(rows), 2)])
    cv2.imwrite(a.out, sheet, [cv2.IMWRITE_JPEG_QUALITY, 85])
    Path(a.out + ".json").write_text(json.dumps([{k: s.get(k) for k in ("id", "t", "frame", "type", "player", "team")}
                                                 for s in shots]))


if __name__ == "__main__":
    main()
