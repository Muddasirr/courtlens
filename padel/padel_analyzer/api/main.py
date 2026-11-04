"""PadelLens API.

  uvicorn padel_analyzer.api.main:app --port 8010
"""
from __future__ import annotations

import csv
import hmac
import io
import json
import re
import secrets
import shutil
from pathlib import Path

import cv2
from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from starlette.concurrency import run_in_threadpool

from ..engine import advanced as ADV
from ..engine import court as C
from ..engine.shots import CLASSES
from . import db, platform_auth, worker
from .settings import API_TOKEN, AUTH_URL, CORS, MATCH_DIR, WEB_DIST

app = FastAPI(title="PadelLens", version="1.0")
app.add_middleware(CORSMiddleware, allow_origins=CORS, allow_methods=["*"], allow_headers=["*"])


@app.middleware("http")
async def require_token(request: Request, call_next):
    """PADEL_API_TOKEN = unrestricted service token; with PADEL_AUTH_URL the platform JWT (header) or a media
    token (?token=, GET only) is accepted and scoped to the caller's facilities."""
    path = request.url.path
    # /api/public/*: share links, read-only and scoped by their own unguessable token
    if (not (API_TOKEN or AUTH_URL) or not path.startswith("/api/") or path == "/api/health"
            or path.startswith("/api/public/")):
        return await call_next(request)
    auth = request.headers.get("authorization", "")
    given = auth[7:] if auth.lower().startswith("bearer ") else request.query_params.get("token", "")
    unauthorized = JSONResponse({"detail": "unauthorized"}, status_code=401)
    if not given:
        return unauthorized
    if API_TOKEN and hmac.compare_digest(given.encode(), API_TOKEN.encode()):
        scope = None
    elif AUTH_URL and given.startswith(platform_auth.MEDIA_PREFIX):
        ok, scope = platform_auth.verify_media(given)
        # read-only, and it cannot mint its successor (that needs a real sign-in)
        if not ok or request.method not in ("GET", "HEAD") or path == "/api/media-token":
            return unauthorized
    elif AUTH_URL:
        scope = await run_in_threadpool(platform_auth.facilities, given)
        if scope is None:
            return unauthorized
    else:
        return unauthorized
    reset = platform_auth.ALLOWED.set(scope)
    try:
        return await call_next(request)
    finally:
        platform_auth.ALLOWED.reset(reset)
db.init()
worker.recover_interrupted()


def _match(s, match_id: str) -> db.Match:
    m = s.get(db.Match, match_id)
    if not m or not platform_auth.can_see(m.facility_id):  # other tenants' matches look absent
        raise HTTPException(404, "match not found")
    return m


def _video(m: db.Match) -> Path:
    return MATCH_DIR / m.id / m.filename


@app.get("/api/health")
def health() -> dict:
    return {"ok": True}


@app.get("/api/media-token")
def media_token() -> dict:
    """Short-lived read-only token for <video>/<img>/download URLs (they cannot send an Authorization header)."""
    return platform_auth.media_token(platform_auth.allowed())


@app.get("/api/court")
def court_model() -> dict:
    """Court geometry for the UI (landmarks, lines, zones)."""
    return {"width": C.WIDTH, "length": C.LENGTH, "net_y": C.NET_Y, "service_y": list(C.SERVICE_Y),
            "net_zone_m": C.NET_ZONE_M, "landmarks": C.LANDMARKS, "lines": C.LINES, "stroke_types": CLASSES}


@app.post("/api/matches")
def create_match(file: UploadFile = File(...), title: str = Form(""), facility_id: str = Form("")) -> dict:
    name = re.sub(r"[^A-Za-z0-9._-]+", "_", Path(file.filename or "match.mp4").name) or "match.mp4"
    facility = _facility(facility_id)
    with db.Session() as s:
        m = db.Match(title=title or Path(name).stem, filename=name, facility_id=facility)
        s.add(m)
        s.commit()
        folder = MATCH_DIR / m.id
        folder.mkdir(parents=True, exist_ok=True)
        with open(folder / name, "wb") as out:
            shutil.copyfileobj(file.file, out, length=8 * 1024 * 1024)
        cap = cv2.VideoCapture(str(folder / name))
        if not cap.isOpened():
            s.delete(m)
            s.commit()
            shutil.rmtree(folder, ignore_errors=True)
            raise HTTPException(400, "not a readable video")
        m.fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
        m.n_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT))
        m.width, m.height = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)), int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
        cap.release()
        s.commit()
        return m.to_dict()


def _facility(requested: str) -> str | None:
    try:
        return platform_auth.pick_facility(requested)
    except PermissionError as exc:
        raise HTTPException(403, f"not a member of facility {exc}") from exc


def _scoped(q, model, facility_id: str | None):
    scope = platform_auth.allowed()
    if scope is not None:
        q = q.filter(model.facility_id.in_(scope))
    if facility_id:
        q = q.filter(model.facility_id == facility_id)
    return q


@app.get("/api/matches")
def list_matches(facility_id: str | None = None) -> list[dict]:
    with db.Session() as s:
        q = _scoped(s.query(db.Match), db.Match, facility_id)
        return [m.to_dict() for m in q.order_by(db.Match.created_at.desc()).all()]


@app.get("/api/matches/{match_id}")
def get_match(match_id: str) -> dict:
    with db.Session() as s:
        return _match(s, match_id).to_dict()


@app.delete("/api/matches/{match_id}")
def delete_match(match_id: str) -> dict:
    with db.Session() as s:
        m = _match(s, match_id)
        if m.status in ("queued", "processing"):
            raise HTTPException(409, "match is being analysed")
        s.query(db.Share).filter(db.Share.match_id == match_id).delete()
        s.delete(m)
        s.commit()
    shutil.rmtree(MATCH_DIR / match_id, ignore_errors=True)
    return {"deleted": match_id}


@app.get("/api/matches/{match_id}/video")
def video(match_id: str) -> FileResponse:
    with db.Session() as s:
        m = _match(s, match_id)
        return FileResponse(_video(m), media_type="video/mp4")


@app.get("/api/matches/{match_id}/frame")
def frame(match_id: str, t: float = 0.0, overlay: bool = False) -> Response:
    with db.Session() as s:
        m = _match(s, match_id)
        path, calib = _video(m), m.calibration
    cap = cv2.VideoCapture(str(path))
    cap.set(cv2.CAP_PROP_POS_MSEC, max(0.0, t) * 1000)
    ok, img = cap.read()
    cap.release()
    if not ok:
        raise HTTPException(400, "cannot read frame")
    if overlay and calib:
        img = C.draw(img, C.Calibration.from_dict(calib))
    ok, buf = cv2.imencode(".jpg", img, [cv2.IMWRITE_JPEG_QUALITY, 88])
    return Response(buf.tobytes(), media_type="image/jpeg")


class CalibrationIn(BaseModel):
    points: dict[str, tuple[float, float]]  # landmark name -> image px
    t: float = 0.0
    snap: bool = False  # refine onto painted lines
    save_camera: str | None = None  # name -> store as a reusable camera


@app.put("/api/matches/{match_id}/calibration")
def set_calibration(match_id: str, body: CalibrationIn) -> dict:
    with db.Session() as s:
        m = _match(s, match_id)
        try:
            cal = C.fit(body.points, (m.width, m.height))
        except ValueError as exc:
            raise HTTPException(422, str(exc)) from exc
        info: dict = {}
        if body.snap:
            cap = cv2.VideoCapture(str(_video(m)))
            cap.set(cv2.CAP_PROP_POS_MSEC, body.t * 1000)
            ok, img = cap.read()
            cap.release()
            if ok:
                cal, info = C.refine(img, cal)
        m.calibration = cal.to_dict()
        if m.status in ("uploaded", "calibrated", "failed", "done"):
            m.status = "calibrated" if m.status != "done" else "done"
        if body.save_camera:
            cam = db.Camera(name=body.save_camera, calibration=m.calibration, facility_id=m.facility_id)
            s.add(cam)
            s.flush()
            m.camera_id = cam.id
        s.commit()
        projected = cal.to_px(list(C.LANDMARKS.values())).round(1).tolist()
        return {"match": m.to_dict(), "refine": info,
                "projected_landmarks": dict(zip(C.LANDMARKS, projected))}


@app.get("/api/cameras")
def cameras(facility_id: str | None = None) -> list[dict]:
    with db.Session() as s:
        return [{"id": c.id, "name": c.name, "calibration": c.calibration}
                for c in _scoped(s.query(db.Camera), db.Camera, facility_id).all()]


@app.post("/api/matches/{match_id}/camera/{camera_id}")
def use_camera(match_id: str, camera_id: str) -> dict:
    with db.Session() as s:
        m = _match(s, match_id)
        cam = s.get(db.Camera, camera_id)
        if not cam or not platform_auth.can_see(cam.facility_id):
            raise HTTPException(404, "camera not found")
        if tuple(cam.calibration["image_size"]) != (m.width, m.height):
            raise HTTPException(422, "camera calibration was made at a different resolution")
        m.calibration, m.camera_id = cam.calibration, cam.id
        if m.status == "uploaded":
            m.status = "calibrated"
        s.commit()
        return m.to_dict()


@app.post("/api/matches/{match_id}/analyze")
def analyze(match_id: str) -> dict:
    with db.Session() as s:
        m = _match(s, match_id)
        if not m.calibration:
            raise HTTPException(409, "calibrate the court first")
        if m.status in ("queued", "processing"):
            raise HTTPException(409, "already running")
    worker.submit(match_id)
    return get_match(match_id)


def _report(match_id: str) -> dict:
    with db.Session() as s:
        review = _match(s, match_id).review or {}
    path = MATCH_DIR / match_id / "report.json"
    if not path.exists():
        raise HTTPException(404, "no report yet")
    return merge_review(json.loads(path.read_text()), review)


def _flat(d: dict, prefix: str = "") -> dict:
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out.update(_flat(v, f"{prefix}{k}."))
        elif isinstance(v, list):
            out[prefix + k] = json.dumps(v)
        else:
            out[prefix + k] = v
    return out


@app.get("/api/matches/{match_id}/export/{table}.csv")
def export_csv(match_id: str, table: str) -> Response:
    """Spreadsheet exports: shots, players, pairs, rallies."""
    rep = _report(match_id)
    names = [p["name"] for p in rep["players"]]
    if table == "shots":
        rows = [{"time_s": s["t"], "rally": s["rally"] + 1, "player": names[s["player"]],
                 "team": rep["teams"][s["team"]]["name"], **{k: v for k, v in _flat(s).items()
                 if k not in ("t", "rally", "player", "team", "frame", "type_probs", "ball_px")}}
                for s in rep["shots"] if not s.get("deleted")]
    elif table == "players":
        rows = [{"player": p["name"], "team": rep["teams"][p["team"]]["name"], **_flat(p["stats"])} for p in rep["players"]]
    elif table == "pairs":
        rows = [{"team": t["name"], "players": " & ".join(names[i] for i in t["players"]), **_flat(t["stats"])}
                for t in rep["teams"]]
    elif table == "rallies":
        rows = [{**{k: v for k, v in r.items() if k != "shots"},
                 "last_player": names[r["last_player"]] if r.get("last_player") is not None else None}
                for r in rep["rallies"]]
    else:
        raise HTTPException(404, "unknown table (shots, players, pairs, rallies)")
    buf = io.StringIO()
    cols = list(dict.fromkeys(k for r in rows for k in r))
    w = csv.DictWriter(buf, fieldnames=cols)
    w.writeheader()
    w.writerows(rows)
    return Response(buf.getvalue(), media_type="text/csv",
                    headers={"Content-Disposition": f'attachment; filename="padel_{match_id}_{table}.csv"'})


@app.get("/api/matches/{match_id}/report")
def report(match_id: str) -> dict:
    with db.Session() as s:
        m = _match(s, match_id)
        review = m.review or {}
    path = MATCH_DIR / match_id / "report.json"
    if not path.exists():
        raise HTTPException(404, "no report yet")
    return merge_review(json.loads(path.read_text()), review)


@app.get("/api/matches/{match_id}/summary")
def summary(match_id: str) -> dict:
    """Report without the heavy parts (replay track, shots, heatmaps): for dashboards and cross-match tables."""
    rep = _report(match_id)
    return {"match": rep["match"], "quality": rep.get("quality", {}),
            "players": [{k: v for k, v in p.items() if k != "heatmap"} for p in rep["players"]],
            "teams": rep["teams"], "rallies": len(rep["rallies"])}


class ReviewIn(BaseModel):
    players: dict[str, dict] | None = None  # {"0": {"name": "Ari"}}
    teams: dict[str, dict] | None = None  # {"0": {"name": "Ari / Paula"}}
    shots: dict[str, dict] | None = None  # {"12": {"type": "smash"}} or {"12": {"deleted": true}}
    rallies: dict[str, dict] | None = None  # {"3": {"winner_team": 1}}


@app.patch("/api/matches/{match_id}/review")
def patch_review(match_id: str, body: ReviewIn) -> dict:
    with db.Session() as s:
        m = _match(s, match_id)
        review = json.loads(json.dumps(m.review or {}))
        for key in ("players", "teams", "shots", "rallies"):
            for k, v in (getattr(body, key) or {}).items():
                review.setdefault(key, {}).setdefault(k, {}).update(v)
        if body.shots:
            for k, v in body.shots.items():
                if v.get("type") and v["type"] not in CLASSES:
                    raise HTTPException(422, f"unknown stroke type {v['type']}")
        m.review = review
        s.commit()
        return m.to_dict()


def merge_review(rep: dict, review: dict) -> dict:
    """Apply confirmed edits and recompute the counts that depend on them."""
    for k, v in (review.get("players") or {}).items():
        if int(k) < len(rep["players"]) and v.get("name"):
            rep["players"][int(k)]["name"] = v["name"]
    for k, v in (review.get("teams") or {}).items():
        if int(k) < len(rep["teams"]) and v.get("name"):
            rep["teams"][int(k)]["name"] = v["name"]
    deleted = set()
    for k, v in (review.get("shots") or {}).items():
        i = int(k)
        if i >= len(rep["shots"]):
            continue
        if v.get("deleted"):
            deleted.add(i)
        if v.get("type"):
            rep["shots"][i]["type"] = v["type"]
            rep["shots"][i]["label"] = "confirmed"
    for i in deleted:
        rep["shots"][i]["deleted"] = True
    for k, v in (review.get("rallies") or {}).items():
        i = int(k)
        if i < len(rep["rallies"]) and "winner_team" in v:
            rep["rallies"][i]["winner_team"] = v["winner_team"]
            rep["rallies"][i]["winner_source"] = "confirmed"
    live = [s for s in rep["shots"] if not s.get("deleted")]
    for p in rep["players"]:
        mine = [s for s in live if s["player"] == p["id"]]
        p["stats"]["shots"] = len(mine)
        p["stats"]["by_type"] = {c: sum(1 for s in mine if s["type"] == c) for c in CLASSES}
    for t in rep["teams"]:
        t["stats"]["shots"] = sum(1 for s in live if s["team"] == t["id"])
        t["stats"]["rallies_won"] = sum(1 for r in rep["rallies"] if r.get("winner_team") == t["id"])
    rep["match"]["hits"] = len(live)
    rep["match"]["type_mix"] = {c: sum(1 for s in live if s["type"] == c) for c in CLASSES}
    rep["match"]["rallies_confirmed"] = sum(1 for r in rep["rallies"] if r.get("winner_source") == "confirmed")
    ADV.outcome_stats(rep)
    return rep



# --- public share links ---------------------------------------------------------------------------------
# A share token is a capability for one match's report and video: no sign-in, GET only, revocable.
# 32 random bytes (urlsafe); one active link per match (making a new one revokes the old).

def _active_share(s, match_id: str) -> db.Share | None:
    return (s.query(db.Share).filter(db.Share.match_id == match_id, db.Share.revoked_at.is_(None))
            .order_by(db.Share.created_at.desc()).first())


@app.get("/api/matches/{match_id}/share")
def get_share(match_id: str) -> dict:
    with db.Session() as s:
        _match(s, match_id)
        sh = _active_share(s, match_id)
        return {"share": sh.to_dict() if sh else None}


@app.post("/api/matches/{match_id}/share")
def create_share(match_id: str) -> dict:
    with db.Session() as s:
        m = _match(s, match_id)
        if not (MATCH_DIR / m.id / "report.json").exists():
            raise HTTPException(409, "the match has no report yet: share it once analysis is done")
        now = db._now()
        for old in s.query(db.Share).filter(db.Share.match_id == match_id, db.Share.revoked_at.is_(None)):
            old.revoked_at = now
        sh = db.Share(token=secrets.token_urlsafe(32), match_id=match_id)
        s.add(sh)
        s.commit()
        return {"share": sh.to_dict()}


@app.delete("/api/matches/{match_id}/share")
def revoke_share(match_id: str) -> dict:
    with db.Session() as s:
        _match(s, match_id)
        now = db._now()
        n = 0
        for sh in s.query(db.Share).filter(db.Share.match_id == match_id, db.Share.revoked_at.is_(None)):
            sh.revoked_at = now
            n += 1
        s.commit()
        return {"revoked": n}


def _shared_match(s, token: str) -> db.Match:
    sh = s.get(db.Share, token) if token and len(token) <= 64 else None
    m = s.get(db.Match, sh.match_id) if sh and sh.revoked_at is None else None
    if m is None or not (MATCH_DIR / m.id / "report.json").exists():
        raise HTTPException(404, "this link is not valid any more")  # revoked, deleted and unknown look the same
    return m


@app.get("/api/public/share/{token}")
def public_report(token: str) -> JSONResponse:
    with db.Session() as s:
        m = _shared_match(s, token)
        review = m.review or {}
        meta = {"id": m.id, "title": m.title, "created_at": m.created_at.isoformat() if m.created_at else None,
                "fps": m.fps, "n_frames": m.n_frames, "width": m.width, "height": m.height, "status": m.status}
    rep = merge_review(json.loads((MATCH_DIR / m.id / "report.json").read_text()), review)
    return JSONResponse({"match": meta, "report": rep},
                        headers={"Cache-Control": "private, no-store", "X-Robots-Tag": "noindex"})


@app.get("/api/public/share/{token}/video")
def public_video(token: str) -> FileResponse:
    with db.Session() as s:
        m = _shared_match(s, token)
    return FileResponse(_video(m), media_type="video/mp4", headers={"X-Robots-Tag": "noindex"})


if WEB_DIST.exists():
    app.mount("/", StaticFiles(directory=WEB_DIST, html=True), name="web")

