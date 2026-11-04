"""Re-score overheads and smash calls of a finished report from its saved detections (no GPU, no video).

    python scripts/rescore_overheads.py <match folder with report.json + detections.npz> [--dry-run]

For reports produced before the windowed overhead measure (engine/shots.py: arm_up, gate_smash). The hitter's
pose is followed from the detection nearest to the shot position over +-0.24 s around contact. Writes
report.json in place and keeps the original as report.pre_rescore.json.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from padel_analyzer.engine import court as C  # noqa: E402
from padel_analyzer.engine import shots as SH  # noqa: E402
from padel_analyzer.engine.detect import Detections  # noqa: E402


def hitter_sequence(det: Detections, f: int, foot_px: np.ndarray, w: int) -> tuple[np.ndarray, np.ndarray] | None:
    b = det.pose_box[f]
    ok = b[:, 4] > 0.2
    if not ok.any():
        return None
    bottom = np.c_[(b[:, 0] + b[:, 2]) / 2, b[:, 3]]
    d = np.where(ok, np.linalg.norm(bottom - foot_px, axis=1), np.inf)
    j = int(np.argmin(d))
    if d[j] > 0.6 * max(60.0, b[j, 3] - b[j, 1]):
        return None
    centre = (b[j, :2] + b[j, 2:4]) / 2
    boxes, kpts = [], []
    for g in range(max(0, f - w), min(det.n, f + w + 1)):
        bb = det.pose_box[g]
        okg = bb[:, 4] > 0.2
        if not okg.any():
            continue
        cc = (bb[:, :2] + bb[:, 2:4]) / 2
        k = int(np.argmin(np.where(okg, np.linalg.norm(cc - centre, axis=1), np.inf)))
        boxes.append(bb[k, :4])
        kpts.append(det.pose_kpt[g, k])
    return np.array(boxes), np.array(kpts)


def rescore(folder: Path, dry_run: bool = False) -> dict:
    rep = json.loads((folder / "report.json").read_text())
    det = Detections.load(folder / "detections.npz")
    cal = C.Calibration.from_dict(rep["calibration"])
    fps = float(rep["match"]["fps"])
    w = max(1, int(round(SH.OVERHEAD_WINDOW_S * fps)))
    changed = {"smash_demoted": 0, "overhead_on": 0, "overhead_off": 0, "unscored": 0}
    for s in rep["shots"]:
        seq = hitter_sequence(det, s["frame"], cal.to_px(np.array([s["pos_m"]]))[0], w) if s.get("pos_m") else None
        if seq is None:  # hitter not detected at contact (e.g. below the frame): no stroke evidence
            changed["unscored"] += 1
            over, seen = False, False
        else:
            over, seen = SH.arm_up(*seq) >= SH.OVERHEAD_ARM_UP, True
        if over != bool(s.get("overhead")):
            changed["overhead_on" if over else "overhead_off"] += 1
        s["overhead"] = bool(over)
        if s.get("label") != "confirmed":
            kind, conf = SH.gate_smash(s["type"], float(s["type_conf"]), s.get("type_probs") or {}, over, seen)
            if kind != s["type"]:
                changed["smash_demoted"] += 1
                s["type"], s["type_conf"] = kind, conf
                s["volley"] = bool(s.get("volley")) and kind != "serve"
    for p in rep["players"]:
        mine = [s for s in rep["shots"] if s["player"] == p["id"]]
        p["stats"]["overheads"] = sum(1 for s in mine if s["overhead"])
        p["stats"]["by_type"] = {c: sum(1 for s in mine if s["type"] == c) for c in SH.CLASSES}
    for r in rep["rallies"]:
        idx = [s for s in rep["shots"] if s["rally"] == r["id"]]
        if idx:
            r["first_type"] = idx[0]["type"]
    rep["match"]["type_mix"] = {c: sum(1 for s in rep["shots"] if s["type"] == c) for c in SH.CLASSES}
    rep.setdefault("quality", {})["overheads_rescored"] = True
    if rep["quality"].get("view_limit_y") is None:
        v = C.view_limit_y(cal)
        rep["quality"]["view_limit_y"] = round(v, 2) if v is not None else None
    if not dry_run:
        backup = folder / "report.pre_rescore.json"
        if not backup.exists():
            shutil.copy(folder / "report.json", backup)
        (folder / "report.json").write_text(json.dumps(rep))
    return changed


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("folder", type=Path)
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()
    print(json.dumps(rescore(a.folder, a.dry_run)))
