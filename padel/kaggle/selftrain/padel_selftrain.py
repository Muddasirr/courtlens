"""Padel GPU kernel: venue self-training of the ball detector (no hand labels).

Input: padel-legends-balltiles dataset (scripts/build_ball_selftrain.py): 640 px tiles pseudo-labelled from the
venue's own tracked ball trajectories, plus held-out clips the tiles never came from.
  1. fine-tune the production ball model (padel-venues ball_v2) on the tiles (low LR: adapt, not relearn)
  2. run base and fine-tuned models over every held-out frame exactly as the detector does
     (imgsz 1536, conf 0.03, 5 candidates) and save both candidate arrays for the before/after comparison
Outputs /kaggle/working/out/{models/ball_venue/best.pt, holdout_<clip>_<model>.npz, selftrain.json}.
"""
from __future__ import annotations

import glob
import json
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

import numpy as np

OUT = Path("/kaggle/working/out")
K_BALL = 5


def first(p: str) -> Path | None:
    m = sorted(glob.glob(p, recursive=True))
    return Path(m[0]) if m else None


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def candidates(weights: str, video: Path) -> np.ndarray:
    import cv2
    from ultralytics import YOLO

    m = YOLO(weights)
    cap = cv2.VideoCapture(str(video))
    out = []
    while True:
        frames = []
        for _ in range(16):
            ok, fr = cap.read()
            if not ok:
                break
            frames.append(fr)
        if not frames:
            break
        for r in m.predict(frames, imgsz=1536, conf=0.03, max_det=K_BALL, verbose=False, device=0, half=True):
            c = np.zeros((K_BALL, 5), np.float32)
            k = len(r.boxes)
            if k:
                c[:k, :4] = r.boxes.xyxy.cpu().numpy()
                c[:k, 4] = r.boxes.conf.cpu().numpy()
            out.append(c)
    return np.stack(out)


def main() -> None:
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "ultralytics==8.4.189"], check=False)
    from ultralytics import YOLO

    OUT.mkdir(parents=True, exist_ok=True)
    res: dict = {}

    def save():
        (OUT / "selftrain.json").write_text(json.dumps(res, indent=1, default=str))

    src = first("/kaggle/input/**/data.yaml").parent
    ds = Path("/kaggle/working/ds")
    shutil.copytree(src, ds, dirs_exist_ok=True)
    (ds / "data.yaml").write_text(f"path: {ds}\ntrain: train/images\nval: val/images\nnames:\n  0: ball\n")
    base = str(first("/kaggle/input/**/models/ball_v2/best.pt"))
    res["base"] = base
    res["tiles"] = {s: len(list((ds / s / "images").glob("*.jpg"))) for s in ("train", "val")}
    log("tiles", res["tiles"], "base", base)
    try:
        res["base_val"] = YOLO(base).val(data=str(ds / "data.yaml"), imgsz=320, batch=32, device=0, verbose=False,
                                         plots=False).results_dict
        YOLO(base).train(data=str(ds / "data.yaml"), imgsz=320, epochs=60, time=1.25, patience=15, batch=64,
                         lr0=0.002, lrf=0.1, warmup_epochs=1, mosaic=0.3, close_mosaic=5, scale=0.3, degrees=0,
                         fliplr=0.5, hsv_h=0.01, hsv_s=0.4, hsv_v=0.3, device=0, workers=4, plots=False,
                         project="/kaggle/working/runs", name="ball_venue", exist_ok=True, verbose=False)
        best = Path("/kaggle/working/runs/ball_venue/weights/best.pt")
        (OUT / "models" / "ball_venue").mkdir(parents=True, exist_ok=True)
        shutil.copy(best, OUT / "models" / "ball_venue" / "best.pt")
        res["new_val"] = YOLO(str(best)).val(data=str(ds / "data.yaml"), imgsz=320, batch=32, device=0,
                                             verbose=False, plots=False).results_dict
        log("val base", res["base_val"], "new", res["new_val"])
    except Exception:  # noqa: BLE001
        res["train"] = "FAILED " + traceback.format_exc()[-2000:]
        save()
        raise
    save()
    for clip in sorted((ds / "holdout").glob("*.mp4")):
        for tag, w in (("base", base), ("new", str(OUT / "models" / "ball_venue" / "best.pt"))):
            t0 = time.time()
            c = candidates(w, clip)
            np.savez_compressed(OUT / f"holdout_{clip.stem}_{tag}.npz", ball=c)
            res[f"holdout_{clip.stem}_{tag}"] = {"frames": len(c), "s": round(time.time() - t0, 1),
                                                 "frames_conf35": float((c[:, :, 4] >= 0.35).any(1).mean()),
                                                 "frames_conf20": float((c[:, :, 4] >= 0.2).any(1).mean())}
            log(clip.stem, tag, res[f"holdout_{clip.stem}_{tag}"])
            save()


if __name__ == "__main__":
    main()
