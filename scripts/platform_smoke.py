"""SportLens end-to-end smoke test through the gateway (no GPU jobs are started).

  padel/.venv/bin/python scripts/platform_smoke.py --base http://localhost:8080   (needs httpx, opencv, numpy)

Checks: health of every service, SPA routing, sign-up / sign-in, facility creation, futsal match creation,
padel upload filed under the facility, tenant isolation for both sports, read-only padel media token,
security headers, and that query strings stay out of the access log format (manual: docker logs).
"""
from __future__ import annotations

import argparse
import secrets
import sys
import tempfile
from pathlib import Path

import httpx

ok_count = 0


def check(cond: bool, what: str) -> None:
    global ok_count
    if not cond:
        print(f"FAIL  {what}")
        sys.exit(1)
    ok_count += 1
    print(f"ok    {what}")


def tiny_video() -> bytes:
    """2 s black 320x240 clip, so padel can probe fps / size."""
    import cv2
    import numpy as np

    out = Path(tempfile.mkdtemp()) / "clip.mp4"
    w = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), 25, (320, 240))
    for _ in range(50):
        w.write(np.zeros((240, 320, 3), np.uint8))
    w.release()
    return out.read_bytes()


def user(c: httpx.Client, tag: str) -> dict[str, str]:
    email = f"smoke-{tag}-{secrets.token_hex(4)}@example.com"
    pw = secrets.token_urlsafe(12)
    r = c.post("/api/v1/auth/register", json={"email": email, "full_name": f"Smoke {tag}", "password": pw})
    check(r.status_code == 201, f"register {tag}")
    r = c.post("/api/v1/auth/login", json={"email": email, "password": pw})
    check(r.status_code == 200, f"login {tag}")
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--base", default="http://localhost:8080")
    base = ap.parse_args().base.rstrip("/")
    c = httpx.Client(base_url=base, timeout=60)

    check(c.get("/healthz").status_code == 200, "gateway /healthz")
    check(c.get("/health").json().get("status") == "ok", "core /health")
    check(c.get("/api/v1/health").json().get("status") == "ok", "core /api/v1/health alias")
    check(c.get("/padel/api/health").json().get("ok") is True, "padel /padel/api/health")

    home = c.get("/")
    check(home.status_code == 200 and '<div id="root">' in home.text, "SPA index")
    check(c.get("/facilities/x/padel").text == home.text, "SPA deep link falls back to index.html")
    for h in ("content-security-policy", "x-content-type-options", "x-frame-options", "referrer-policy"):
        check(h in home.headers, f"security header {h}")
    check(home.headers.get("cache-control") == "no-cache", "index.html not cached")
    check("x-request-id" in c.get("/api/v1/health").headers, "request id on API responses")

    check(c.get("/padel/api/matches").status_code == 401, "padel rejects anonymous")
    check(c.get("/api/v1/facilities").status_code == 401, "core rejects anonymous")

    a, b = user(c, "a"), user(c, "b")
    fa = c.post("/api/v1/facilities", json={"name": "Smoke Arena A"}, headers=a).json()["id"]
    fb = c.post("/api/v1/facilities", json={"name": "Smoke Arena B"}, headers=b).json()["id"]
    check(bool(fa and fb), "facilities created")

    # futsal
    r = c.post(f"/api/v1/facilities/{fa}/matches", json={"title": "Smoke futsal"}, headers=a)
    check(r.status_code == 201, "futsal match created")
    check(c.get(f"/api/v1/facilities/{fa}/matches", headers=b).status_code == 403, "futsal: other tenant blocked")

    # padel
    clip = tiny_video()
    r = c.post("/padel/api/matches", headers=a, data={"title": "Smoke padel", "facility_id": fa},
               files={"file": ("clip.mp4", clip, "video/mp4")})
    check(r.status_code == 200, f"padel upload ({r.status_code} {r.text[:120]})")
    pm = r.json()
    check(pm["facility_id"] == fa and pm["n_frames"] > 0, "padel match filed under facility A")
    r = c.post("/padel/api/matches", headers=a, data={"title": "x", "facility_id": fb},
               files={"file": ("clip.mp4", clip, "video/mp4")})
    check(r.status_code == 403, "padel: cannot upload into another facility")
    check([m["id"] for m in c.get("/padel/api/matches", headers=a).json()] == [pm["id"]], "padel: A lists own match")
    check(c.get("/padel/api/matches", headers=b).json() == [], "padel: B sees nothing")
    check(c.get(f"/padel/api/matches/{pm['id']}", headers=b).status_code == 404, "padel: B gets 404 on A's match")

    mt = c.get("/padel/api/media-token", headers=a).json()["token"]
    v = c.get(f"/padel/api/matches/{pm['id']}/video", params={"token": mt}, headers={"Range": "bytes=0-99"})
    check(v.status_code == 206 and len(v.content) == 100, "padel video: ranged playback with media token")
    f = c.get(f"/padel/api/matches/{pm['id']}/frame", params={"t": 0.5, "token": mt})
    check(f.headers.get("content-type") == "image/jpeg", "padel frame with media token")
    check(c.delete(f"/padel/api/matches/{pm['id']}", params={"token": mt}).status_code == 401, "media token is read-only")
    mb = c.get("/padel/api/media-token", headers=b).json()["token"]
    check(c.get(f"/padel/api/matches/{pm['id']}/video", params={"token": mb}).status_code == 404, "media token is tenant-scoped")

    check(c.delete(f"/padel/api/matches/{pm['id']}", headers=a).status_code == 200, "padel match deleted by owner")
    print(f"\nALL {ok_count} CHECKS PASSED against {base}")


if __name__ == "__main__":
    main()
