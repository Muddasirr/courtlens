"""Padel kernel (CPU): who-hit-the-ball attribution vs Decorte et al. hit_assignments (319 hits, 2 tournaments).

Labels: rally video, timestamp of the frame where the hit is visible, hitter as t1p1 top-left, t1p2 top-right,
t2p1 bottom-left, t2p2 bottom-right. Ours: tracks rebuilt from padel-audio's saved detections; at the
labelled frame (±3) the hitter is the player whose wrist is closest to the ball (box distance as fallback);
top/bottom = net side, left/right = image x relative to the partner. Paper: 83.7 % player, 86.8 % team.
"""
from __future__ import annotations

import csv
import glob
import json
import shutil
import subprocess
import sys
from pathlib import Path

import numpy as np

OUT = Path("/kaggle/working/out")


def first(p):
    h = sorted(glob.glob(p, recursive=True))
    return Path(h[0]) if h else None


def main():
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "openpyxl", "ultralytics==8.4.189"], check=False)
    import pandas as pd

    code = first("/kaggle/input/**/padel_analyzer/__init__.py").parents[1]
    repo = Path("/tmp/padel")
    shutil.copytree(code, repo)
    labels = first("/kaggle/input/**/pt100/labels/2022_BCN_FinalF_1_pose.json").parent
    (repo / "data" / "pt100").mkdir(parents=True)
    shutil.copytree(labels, repo / "data" / "pt100" / "labels")
    sys.path.insert(0, str(repo))
    from padel_analyzer.engine import ball as B
    from padel_analyzer.engine import court as C
    from padel_analyzer.engine import players as P
    from padel_analyzer.engine.detect import Detections
    from padel_analyzer.eval import pt100

    xl = first("/kaggle/input/**/CVSPORTS_Padel/metadata/hit_assignments.xlsx")
    det_dir = first("/kaggle/input/**/out/det/20230528_VIGO_00.mp4.npz").parent
    df = pd.read_excel(xl)
    print(df.head(), df.columns.tolist(), len(df), flush=True)
    calib = C.Calibration(pt100.load("F").H, (1920, 1080))
    cache: dict = {}
    rows = []
    for _, r in df.iterrows():
        vid = str(r["video"])
        vid = vid if vid.endswith(".mp4") else vid + ".mp4"
        p = det_dir / (vid + ".npz")
        if not p.exists():
            rows.append({"video": vid, "status": "no detections"})
            continue
        if vid not in cache:
            det = Detections.load(p)
            cache[vid] = (det, P.track(det, calib), B.track_for_events(det.ball))
        det, tr, bt = cache[vid]
        ts = r["timestamp"]
        t = float(ts) if not isinstance(ts, str) else sum(float(x) * 60 ** i for i, x in enumerate(reversed(ts.split(":"))))
        f0 = int(round(t * det.fps))
        best = (np.inf, None, None)
        for f in range(max(0, f0 - 3), min(det.n, f0 + 4)):
            b = bt.xy[f]
            if np.isnan(b).any():
                continue
            for s in range(4):
                box = tr.box[f, s]
                if np.isnan(box).any():
                    continue
                k = tr.kpt[f, s]
                w = [k[j, :2] for j in (9, 10) if k[j, 2] > 0.3]
                h = box[3] - box[1]
                d = min(np.linalg.norm(x - b) for x in w) / h if w else \
                    np.hypot(max(box[0] - b[0], 0, b[0] - box[2]), max(box[1] - b[1], 0, b[1] - box[3])) / h + 1
                if d < best[0]:
                    best = (d, f, s)
        gt = str(r["player"]).strip()
        if best[1] is None:
            rows.append({"video": vid, "gt": gt, "status": "no ball/players"})
            continue
        _, f, s = best
        partner = s ^ 1
        x_me = (tr.box[f, s, 0] + tr.box[f, s, 2]) / 2
        x_pa = (tr.box[f, partner, 0] + tr.box[f, partner, 2]) / 2 if not np.isnan(tr.box[f, partner, 0]) else None
        top = s < 2
        if x_pa is None:
            left = x_me < 960  # partner not seen: image centre
        else:
            left = x_me < x_pa
        pred = ("t1" if top else "t2") + ("p1" if left else "p2")
        rows.append({"video": vid, "gt": gt, "pred": pred, "status": "ok", "dist": round(float(best[0]), 3)})
    # sequence model: labelled frames + every annotated hit of the rally, Viterbi, scored on the same labels
    from padel_analyzer.engine import hitter as HT

    onsets: dict = {}
    with open(first("/kaggle/input/**/CVSPORTS_Padel/metadata/hits.csv")) as fh:
        for h in csv.DictReader(fh):
            onsets.setdefault(h["filename"], []).append(float(h["start"]))
    labelled = {}  # video -> [(frame, gt, row index)]
    for i, (_, r) in enumerate(df.iterrows()):
        vid = str(r["video"])
        vid = vid if vid.endswith(".mp4") else vid + ".mp4"
        if vid in cache and rows[i]["status"] == "ok":
            det = cache[vid][0]
            ts = r["timestamp"]
            t = float(ts) if not isinstance(ts, str) else sum(float(x) * 60 ** k for k, x in enumerate(reversed(ts.split(":"))))
            labelled.setdefault(vid, []).append((int(round(t * det.fps)), rows[i]["gt"], i))

    def label_of(tr, f, s):
        partner = s ^ 1
        x_me = (tr.box[f, s, 0] + tr.box[f, s, 2]) / 2
        x_pa = (tr.box[f, partner, 0] + tr.box[f, partner, 2]) / 2 if not np.isnan(tr.box[f, partner, 0]) else None
        if np.isnan(x_me):
            return None
        left = x_me < 960 if x_pa is None else x_me < x_pa
        return ("t1" if s < 2 else "t2") + ("p1" if left else "p2")

    grid = {}
    for same_end in (0.0, 0.3, 0.6, 1.0, 2.0):
        hit, team, tot = 0, 0, 0
        for vid, labs in labelled.items():
            det, tr, bt = cache[vid]
            on = sorted(int(round(t * det.fps)) for t in onsets.get(vid, []))
            frames = sorted(set(f for f, _, _ in labs) | {o for o in on if all(abs(o - f) > 8 for f, _, _ in labs)})
            slots = dict(zip(frames, HT.assign(frames, tr, bt.xy, det.fps, same_end)))
            for f, gt, _ in labs:
                pred = label_of(tr, min(max(f, 0), det.n - 1), slots[f]) or "t1p1"
                tot += 1
                hit += pred == gt
                team += pred[:2] == gt[:2]
        grid[f"same_end={same_end}"] = {"player": round(hit / tot, 4), "team": round(team / tot, 4), "n": tot}
        print(same_end, grid[f"same_end={same_end}"], flush=True)
    ok = [x for x in rows if x["status"] == "ok"]
    res = {
        "sequence_grid": grid,
        "labels": len(rows), "evaluated": len(ok),
        "player_acc": round(np.mean([x["pred"] == x["gt"] for x in ok]), 4) if ok else None,
        "team_acc": round(np.mean([x["pred"][:2] == x["gt"][:2] for x in ok]), 4) if ok else None,
        "player_acc_over_all_labels": round(sum(x["pred"] == x["gt"] for x in ok) / max(1, len(rows)), 4),
        "skipped": {s: sum(1 for x in rows if x["status"] == s) for s in {x["status"] for x in rows}},
        "paper": {"player": 0.837, "team": 0.8683},
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "hitter.json").write_text(json.dumps({"result": res, "rows": rows}, indent=1))
    print(json.dumps(res, indent=1), flush=True)


if __name__ == "__main__":
    main()
