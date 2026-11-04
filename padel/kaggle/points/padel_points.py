"""Kernel: point labels from broadcast scoreboards -> point-winner model.

Inputs: PT100 videos + held-out detection caches (both finals), padel-scoreboard states, the Kuwait 2025 clip's
detections / report / hand-read points (padel-kuwait-small), production models.
One row per scoreboard point change -> engine.points features, label = last hitter's pair won.
Leave-one-match-out over F / M / Kuwait; production model trained on all three.
Output: /kaggle/working/out/points.json, models/point_lgbm.{txt,json}
"""
from __future__ import annotations

import glob
import json
import re
import shutil
import subprocess
import sys
import time
import traceback
from pathlib import Path

import numpy as np

OUT = Path("/kaggle/working/out")
REPO = Path("/kaggle/working/padel")


def first(p: str) -> Path | None:
    h = sorted(glob.glob(p, recursive=True))
    return Path(h[0]) if h else None


def log(*a):
    print(time.strftime("%H:%M:%S"), *a, flush=True)


def setup():
    subprocess.run([sys.executable, "-m", "pip", "install", "-q", "ultralytics==8.4.189", "lightgbm"], check=False)
    code = first("/kaggle/input/**/padel_analyzer/__init__.py").parents[1]
    if REPO.exists():
        shutil.rmtree(REPO)
    shutil.copytree(code, REPO)
    models = REPO / "models"
    models.mkdir(exist_ok=True)
    wanted = {
        "pose.pt": "/kaggle/input/**/models/pose_all/best.pt",
        "hit_lgbm_video.txt": "/kaggle/input/**/padel-eval/out/models/hit_lgbm.txt",
        "hit_lgbm_video.json": "/kaggle/input/**/padel-eval/out/models/hit_lgbm.json",
        "hit_lgbm.txt": "/kaggle/input/**/padel-fusion/out/models/hit_lgbm.txt",
        "hit_lgbm.json": "/kaggle/input/**/padel-fusion/out/models/hit_lgbm.json",
        "shot_lgbm.txt": "/kaggle/input/**/out/models/shot_lgbm.txt",
        "stroke_rgb.pt": "/kaggle/input/**/stroke_rgb.pt",
    }
    for name, pat in wanted.items():
        src = first(pat)
        if src:
            shutil.copy(src, models / name)
    labels = first("/kaggle/input/**/pt100/labels/2022_BCN_FinalF_1_pose.json").parent
    (REPO / "data" / "pt100").mkdir(parents=True, exist_ok=True)
    if not (REPO / "data" / "pt100" / "labels").exists():
        shutil.copytree(labels, REPO / "data" / "pt100" / "labels")
    sys.path.insert(0, str(REPO))
    log("models", sorted(p.name for p in models.iterdir()))


def main() -> None:
    setup()
    import lightgbm as lgb

    from padel_analyzer.eval.scoreboard import transitions

    from padel_analyzer.engine import ball as B
    from padel_analyzer.engine import court as C
    from padel_analyzer.engine import hitter as HT
    from padel_analyzer.engine import pipeline
    from padel_analyzer.engine import players as P
    from padel_analyzer.engine import points as PT
    from padel_analyzer.engine.detect import Detections
    from padel_analyzer.eval import pt100

    OUT.mkdir(parents=True, exist_ok=True)
    res: dict = {"identity": {}, "points": {}}
    rows: dict[str, tuple[np.ndarray, np.ndarray, list]] = {}

    for key in ("F", "M"):
        try:
            name = pt100.MATCHES[key]
            g = pt100.load(key)
            z = np.load(first(f"/kaggle/input/**/cache/{name}_heldout.npz"), allow_pickle=True)
            n = len(z["ball"])
            det = Detections(30.0, (1920, 1080), z["ball"].astype(np.float32), z["pose_box"].astype(np.float32),
                             z["pose_kpt"].astype(np.float32), np.ones(n, bool), np.zeros(n, bool))
            calib = C.Calibration(g.H, (1920, 1080))
            video = first(f"/kaggle/input/**/videos/{name}.mp4")
            log(key, "frames", n, video)
            feats = pipeline.sample_embeddings(video, det)
            log(key, "embeddings", len(feats))
            new = P.track(det, calib, feats)
            pipeline.sample_embeddings = lambda *a, **k: feats  # analyze() reuses them
            rep = pipeline.analyze(det, calib, video)
            log(key, "report", rep["match"]["rallies"], "rallies", rep["match"]["hits"], "hits")
            states = json.loads(first(f"/kaggle/input/**/{name}/states.json").read_text())
            tr = transitions(states)
            log(key, "scoreboard transitions", len(tr), "of", len(states), "states")
            shots, rallies = rep["shots"], rep["rallies"]
            gt_serves = [s.frame for s in g.shots if s.kind == "serve"]
            seg = new.segments
            seg_of = lambda f: next((i for i, (a, b) in enumerate(seg) if a <= f < b), len(seg) - 1)  # noqa: E731
            truth_far_row = {}  # segment -> scoreboard row of the pair at the far end
            X, y, meta = [], [], []
            pos = new.person_view().pos_m
            bt = B.track(det.ball)
            for t in tr:
                rs = [r for r in rallies if r["shots"] and t["from"] - 30 <= shots[r["shots"][-1]]["frame"] < t["to"]]
                if len(rs) != 1 or t["server_row"] is None:
                    continue
                r = rs[0]
                first_f = shots[r["shots"][0]]["frame"]
                # where the serve was hit: labelled serve near the rally start, else a detected serve
                sf = next((f for f in gt_serves if first_f - 45 <= f <= first_f + 45), None)
                sp = None
                if sf is not None:
                    pm = g.pos_m[sf]
                    ok = ~np.isnan(pm[:, 0])
                    if ok.any():
                        bx = g.ball[sf]
                        # the server: the labelled player nearest the ball in the image -> his side
                        bb = g.pbox[sf]
                        c = (bb[:, :2] + bb[:, 2:]) / 2
                        dd = np.linalg.norm(c - bx, axis=1) if not np.isnan(bx).any() else np.abs(pm[:, 1] - 10)
                        dd = np.where(ok, dd, np.inf)
                        sp = float(pm[int(np.argmin(dd)), 1])
                if sp is None and shots[r["shots"][0]]["type"] == "serve" and shots[r["shots"][0]].get("pos_m"):
                    sp = shots[r["shots"][0]]["pos_m"][1]
                if sp is None:
                    continue
                server_far = sp < C.NET_Y
                far_row = t["server_row"] if server_far else 1 - t["server_row"]
                truth_far_row[seg_of(first_f)] = far_row
                last = shots[r["shots"][-1]]
                if not last.get("pos_m"):
                    continue
                last_far = last["pos_m"][1] < C.NET_Y
                winner_far = (t["winner_row"] == far_row)
                k = rallies.index(r)
                X.append(PT.rally_features(r, shots, bt.xy, pos, calib, 30.0,
                                           next((b for a, b in seg if b > last["frame"]), n),
                                           shots[rallies[k + 1]["shots"][0]]["frame"] if k + 1 < len(rallies) and rallies[k + 1]["shots"] else None))
                y.append(int(winner_far == last_far))
                meta.append({"frame": last["frame"], "winner_row": t["winner_row"], "far_row": far_row})
            rows[key] = (np.array(X), np.array(y), meta)
            log(key, "point rows", len(y), "pos rate", float(np.mean(y)) if y else None)
        except Exception:  # noqa: BLE001
            log("FAILED", key, traceback.format_exc()[-2500:])

    # Kuwait 2025 (unseen, hand-read scoreboard)
    try:
        kd = first("/kaggle/input/**/kuwait_points.json").parent
        rep = json.loads((kd / "report.json").read_text())
        lab = json.loads((kd / "kuwait_points.json").read_text())["points"]
        det = Detections.load(kd / "detections.npz")
        calib = C.Calibration.from_dict(rep["calibration"])
        tk = P.track(det, calib)  # no shirts: slots 0,1 = far pair, so features use sides
        pos, bt, fps, n = tk.person_view().pos_m, B.track(det.ball), det.fps, det.n
        shots, rallies = rep["shots"], rep["rallies"]
        # stored report predates the alternation step: redo the hitters; team = end here (shirt-free tracks)
        slots = HT.assign([s["frame"] for s in shots], tk, B.track_for_events(det.ball).xy, fps)
        for s, sl in zip(shots, slots):
            s["player"], s["team"] = sl, 0 if sl < 2 else 1
            p = pos[min(s["frame"], n - 1), sl]
            if not np.isnan(p).any():
                s["pos_m"] = [float(p[0]), float(p[1])]
        a_far = lambda t: 75 <= t < 299  # Coello/Tapia's end, from serve positions + changes of ends  # noqa: E731
        X, y, meta, prev = [], [], [], 0
        for p in lab:
            rs = [r for r in rallies if r["shots"] and prev < shots[r["shots"][-1]]["t"] <= p["by_s"]]
            prev = p["by_s"]
            if not rs:
                continue
            r = rs[-1]
            last = shots[r["shots"][-1]]
            if not last.get("pos_m"):
                continue
            winner_far = a_far(last["t"]) if p["winner_team"] == 0 else not a_far(last["t"])
            k = rallies.index(r)
            X.append(PT.rally_features(r, shots, bt.xy, pos, calib, fps, n,
                                       shots[rallies[k + 1]["shots"][0]]["frame"] if k + 1 < len(rallies) and rallies[k + 1]["shots"] else None))
            y.append(int(winner_far == (last["pos_m"][1] < C.NET_Y)))
            meta.append({"t": last["t"]})
        rows["K"] = (np.array(X), np.array(y), meta)
        log("K point rows", len(y), "pos rate", float(np.mean(y)))
    except Exception:  # noqa: BLE001
        log("FAILED kuwait", traceback.format_exc()[-2500:])

    params = dict(objective="binary", learning_rate=0.05, num_leaves=7, min_data_in_leaf=8, feature_fraction=0.8,
                  bagging_fraction=0.8, bagging_freq=1, lambda_l2=1.0, verbose=-1)
    keys = [k for k in rows if len(rows[k][1])]
    res["points"]["rows"] = {k: int(len(rows[k][1])) for k in keys}
    res["points"]["last_hitter_won_rate"] = {k: round(float(np.mean(rows[k][1])), 3) for k in keys}
    for te in keys:
        tr = [k for k in keys if k != te]
        if not tr:
            continue
        Xtr = np.vstack([rows[k][0] for k in tr])
        ytr = np.concatenate([rows[k][1] for k in tr])
        bst = lgb.train(params, lgb.Dataset(Xtr, ytr), num_boost_round=150)
        p = bst.predict(rows[te][0])
        yt = rows[te][1]
        acc = float(((p >= 0.5) == yt).mean())
        maj = float(max(yt.mean(), 1 - yt.mean()))
        base = float(max(ytr.mean(), 1 - ytr.mean()))
        res["points"][f"test_{te}"] = {"n": int(len(yt)), "accuracy": round(acc, 3),
                                        "always_majority_of_train": round(float(((ytr.mean() >= 0.5) == yt).mean()), 3),
                                        "test_majority_rate": round(maj, 3)}
        log("points LOMO", te, json.dumps(res["points"][f"test_{te}"]))
    if keys:
        Xa = np.vstack([rows[k][0] for k in keys])
        ya = np.concatenate([rows[k][1] for k in keys])
        bst = lgb.train(params, lgb.Dataset(Xa, ya, feature_name=PT.FEATURES), num_boost_round=150)
        (OUT / "models").mkdir(exist_ok=True)
        bst.save_model(str(OUT / "models" / "point_lgbm.txt"))
        (OUT / "models" / "point_lgbm.json").write_text(json.dumps({"rows": res["points"]["rows"]}))
        imp = dict(zip(PT.FEATURES, bst.feature_importance("gain").round(1).tolist()))
        res["points"]["importance"] = dict(sorted(imp.items(), key=lambda kv: -kv[1])[:12])
        np.savez(OUT / "point_rows.npz", **{f"X_{k}": rows[k][0] for k in keys}, **{f"y_{k}": rows[k][1] for k in keys})
    (OUT / "points.json").write_text(json.dumps(res, indent=1, default=str))
    log("final", json.dumps(res, default=str)[:3000])


if __name__ == "__main__":
    main()
