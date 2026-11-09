"""Venue self-training set for the ball detector, from a finished analysis (no hand labels).

    python scripts/build_ball_selftrain.py OUT_DIR  MATCH_DIR:VIDEO[:HOLDOUT_FROM_FRAME] ...

Pseudo-labels = MOVING points of the ball trajectory tracked at min_conf 0.2 (engine/ball.track: tracklets
with a constant-velocity gate). On Legends Arena 24/24 audited points were the ball. Only the ball in play is
labelled: round 1 also labelled other confident candidates and taught the model to fire on spare balls by the
net, logos and signs (~70 % precision on its new detections).
Each sampled frame is scaled like the detector sees it (imgsz 1536 on 1920 px) and cut into a tile around the
ball. Negatives: random empty tiles, plus HARD negatives centred on "hotspots" (image cells where candidates
sit for a long time: logos, signs, spectators, dead balls), at moments the ball in play is elsewhere. Frames from HOLDOUT_FROM_FRAME on are never used:
that part of the video is cut to OUT_DIR/holdout/*.mp4 for the before/after check.
"""
from __future__ import annotations

import json
import random
import subprocess
import sys
from pathlib import Path

import cv2
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from padel_analyzer.engine import ball as B  # noqa: E402
from padel_analyzer.engine.audio import ffmpeg_exe  # noqa: E402
from padel_analyzer.engine.detect import Detections  # noqa: E402

TILE = 320  # the ball is ~5-12 px at the detector's scale: small tiles keep the upload light (train imgsz 320)
SCALE = 1536 / 1920
EVERY = 3  # consecutive frames are near duplicates
MAX_POS = 1200
NEG_FRAC = 0.15
HARD_FRAC = 0.4  # hard negatives per positive
HOT_CELL = 24  # px (full resolution) grid for static hotspots
HOT_CONF = 0.03  # weak candidates count: the base model only whispers at logos / spare balls
HOT_FRAC = 0.005  # a cell holding a candidate in >= 0.5 % of frames is a hotspot
TOP_FRAC = 0.15  # extra negatives from the top band (signs, logos, spectators behind the far glass)
MIN_SPEED_PX = 2.0  # px/frame: slower track points are not labelled (dead / held balls)
HOLDOUT_S = 150  # seconds of the held-out tail cut for the detector comparison


def tiles_for(det: Detections, video: str, upto: int, out: Path, tag: str, rng: random.Random) -> dict:
    tr = B.track(det.ball, min_conf=0.2)
    speed = np.linalg.norm(B.velocity(tr.xy), axis=1)
    moving = tr.observed & (np.nan_to_num(speed) > MIN_SPEED_PX)
    frames = [f for f in np.where(moving[:upto])[0][::EVERY]]
    rng.shuffle(frames)
    frames = sorted(frames[:MAX_POS])
    neg = sorted(rng.sample(range(upto), min(upto, int(len(frames) * NEG_FRAC))))
    # hotspots: grid cells holding a candidate in many frames (static look-alikes and dead balls)
    c = det.ball[:upto]
    ok = c[:, :, 4] >= HOT_CONF
    cx = ((c[:, :, 0] + c[:, :, 2]) / 2)[ok]
    cy = ((c[:, :, 1] + c[:, :, 3]) / 2)[ok]
    cells = np.stack([(cx // HOT_CELL).astype(int), (cy // HOT_CELL).astype(int)], 1)
    uniq, cnt = np.unique(cells, axis=0, return_counts=True)
    hot = uniq[cnt >= max(150, HOT_FRAC * upto)]
    hard = {}
    if len(hot):
        for f in rng.sample(range(upto), min(upto, int(len(frames) * HARD_FRAC))):
            hard[f] = hot[rng.randrange(len(hot))]
    for f in rng.sample(range(upto), min(upto, int(len(frames) * TOP_FRAC))):
        hard.setdefault(f, np.array([rng.randrange(0, 1920 // HOT_CELL), rng.randrange(0, 260 // HOT_CELL)]))
    cap = cv2.VideoCapture(video)
    W, H = int(1920 * SCALE), int(1080 * SCALE)
    n_pos = n_neg = 0
    n_hard = 0
    for f in sorted(set(frames) | set(neg) | set(hard)):
        cap.set(cv2.CAP_PROP_POS_FRAMES, int(f) * det.step)
        ok, img = cap.read()
        if not ok:
            continue
        img = cv2.resize(img, (W, H), interpolation=cv2.INTER_AREA)
        c = det.ball[f]
        boxes = c[c[:, 4] > 0][:, :5].copy()
        boxes[:, :4] *= SCALE
        if f in frames:
            cx, cy = tr.xy[f] * SCALE
            x0 = int(np.clip(cx - rng.uniform(40, TILE - 40), 0, W - TILE))
            y0 = int(np.clip(cy - rng.uniform(40, TILE - 40), 0, H - TILE))
            # only the ball in play: the candidate on the moving track (spare balls in the tile = background)
            d = np.hypot((boxes[:, 0] + boxes[:, 2]) / 2 - cx, (boxes[:, 1] + boxes[:, 3]) / 2 - cy)
            lab = boxes[d < 6][:1]
            kind = "pos"
        elif f in hard:
            hx, hy = (hard[f] + 0.5) * HOT_CELL * SCALE
            x0 = int(np.clip(hx - rng.uniform(40, TILE - 40), 0, W - TILE))
            y0 = int(np.clip(hy - rng.uniform(40, TILE - 40), 0, H - TILE))
            if tr.observed[f]:  # the ball in play must not be in a negative tile
                bx, by = tr.xy[f] * SCALE
                if x0 - 8 <= bx <= x0 + TILE + 8 and y0 - 8 <= by <= y0 + TILE + 8:
                    continue
            lab = boxes[:0]
            kind = "hard"
        else:
            # negative: a tile with no candidate at all, even weak ones
            for _ in range(10):
                x0, y0 = rng.randint(0, W - TILE), rng.randint(0, H - TILE)
                inside = ((boxes[:, 0] < x0 + TILE) & (boxes[:, 2] > x0) & (boxes[:, 1] < y0 + TILE) & (boxes[:, 3] > y0))
                if not (inside & (boxes[:, 4] >= 0.1)).any():
                    break
            else:
                continue
            lab = boxes[:0]
            kind = "neg"
        tile = img[y0:y0 + TILE, x0:x0 + TILE]
        rows = []
        for b in lab:
            bx0, by0 = max(b[0] - x0, 0), max(b[1] - y0, 0)
            bx1, by1 = min(b[2] - x0, TILE), min(b[3] - y0, TILE)
            if bx1 - bx0 < 2 or by1 - by0 < 2:
                continue
            rows.append(f"0 {(bx0 + bx1) / 2 / TILE:.6f} {(by0 + by1) / 2 / TILE:.6f} "
                        f"{(bx1 - bx0) / TILE:.6f} {(by1 - by0) / TILE:.6f}")
        if kind == "pos" and not rows:
            continue
        split = "val" if rng.random() < 0.08 else "train"
        name = f"{tag}_{f:06d}_{kind}"
        cv2.imwrite(str(out / split / "images" / f"{name}.jpg"), tile, [cv2.IMWRITE_JPEG_QUALITY, 88])
        (out / split / "labels" / f"{name}.txt").write_text("\n".join(rows))
        n_pos += kind == "pos"
        n_neg += kind == "neg"
        n_hard += kind == "hard"
    cap.release()
    return {"positives": n_pos, "negatives": n_neg, "hard_negatives": n_hard, "hotspot_cells": int(len(hot)),
            "frames_used_upto": int(upto)}


def main() -> None:
    out = Path(sys.argv[1])
    for s in ("train", "val"):
        for k in ("images", "labels"):
            (out / s / k).mkdir(parents=True, exist_ok=True)
    (out / "holdout").mkdir(exist_ok=True)
    rng = random.Random(0)
    summary = {}
    for spec in sys.argv[2:]:
        parts = spec.split(":")
        folder, video = Path(parts[0]), parts[1]
        det = Detections.load(folder / "detections.npz")
        upto = int(parts[2]) if len(parts) > 2 else det.n
        tag = folder.name[-12:]
        summary[tag] = tiles_for(det, video, upto, out, tag, rng)
        if upto < det.n:  # held-out tail: cut it for the before/after detector check
            t0 = upto * det.step / det.fps
            subprocess.run([ffmpeg_exe(), "-v", "error", "-y", "-ss", f"{t0:.3f}", "-t", str(HOLDOUT_S), "-i", video, "-an",
                            "-c", "copy",
                            str(out / "holdout" / f"{tag}.mp4")], check=True)
            summary[tag]["holdout_start_s"] = round(t0, 3)
        print(tag, summary[tag], flush=True)
    (out / "data.yaml").write_text("path: .\ntrain: train/images\nval: val/images\nnames:\n  0: ball\n")
    (out / "summary.json").write_text(json.dumps(summary, indent=1))


if __name__ == "__main__":
    main()
