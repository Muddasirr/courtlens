"""Platform sign-in: core JWT accepted, matches scoped per facility, read-only media tokens, service token kept."""
import importlib

import cv2
import numpy as np
import pytest

# token -> facilities the stub core API reports for it
USERS = {"jwt-alice": ["fac-a"], "jwt-bob": ["fac-b"], "jwt-both": ["fac-a", "fac-b"]}


class _Resp:
    def __init__(self, token):
        self.status_code = 200 if token in USERS else 401
        self._facs = USERS.get(token, [])

    def json(self):
        return [{"id": f, "name": f} for f in self._facs]


@pytest.fixture
def client(tmp_path, monkeypatch):
    monkeypatch.setenv("PADEL_DATA_DIR", str(tmp_path))
    monkeypatch.setenv("PADEL_DB_URL", f"sqlite:///{tmp_path / 't.db'}")
    monkeypatch.setenv("PADEL_BACKEND", "local")
    monkeypatch.setenv("PADEL_AUTH_URL", "http://core.test")
    monkeypatch.setenv("PADEL_API_TOKEN", "service-secret")
    calls = []

    def fake_get(url, headers, timeout):
        calls.append(url)
        assert url == "http://core.test/api/v1/facilities"
        return _Resp(headers["Authorization"][7:])

    import padel_analyzer.api.settings as settings

    importlib.reload(settings)
    import padel_analyzer.api.platform_auth as pa

    importlib.reload(pa)
    monkeypatch.setattr(pa.requests, "get", fake_get)
    import padel_analyzer.api.db as db

    importlib.reload(db)
    import padel_analyzer.api.worker as worker

    importlib.reload(worker)
    import padel_analyzer.api.main as main

    importlib.reload(main)
    from fastapi.testclient import TestClient

    yield TestClient(main.app), calls
    for var in ("PADEL_AUTH_URL", "PADEL_API_TOKEN"):
        monkeypatch.delenv(var)
    importlib.reload(settings)
    importlib.reload(pa)
    importlib.reload(main)


def _clip(tmp_path) -> bytes:
    path = tmp_path / "c.mp4"
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), 30, (640, 360))
    for _ in range(10):
        w.write(np.zeros((360, 640, 3), np.uint8))
    w.release()
    return path.read_bytes()


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def _upload(c, tmp_path, token, **data):
    return c.post("/api/matches", headers=_h(token), data={"title": "t", **data},
                  files={"file": ("c.mp4", _clip(tmp_path), "video/mp4")})


def test_tenant_isolation(client, tmp_path):
    c, calls = client
    assert c.get("/api/health").status_code == 200  # open for load balancers
    assert c.get("/api/matches").status_code == 401
    assert c.get("/api/matches", headers=_h("forged")).status_code == 401

    a = _upload(c, tmp_path, "jwt-alice").json()  # single facility: filed there automatically
    assert a["facility_id"] == "fac-a"
    assert _upload(c, tmp_path, "jwt-alice", facility_id="fac-b").status_code == 403
    assert _upload(c, tmp_path, "jwt-both").status_code == 403  # two facilities: must say which
    b = _upload(c, tmp_path, "jwt-both", facility_id="fac-b").json()

    assert [m["id"] for m in c.get("/api/matches", headers=_h("jwt-alice")).json()] == [a["id"]]
    assert [m["id"] for m in c.get("/api/matches", headers=_h("jwt-bob")).json()] == [b["id"]]
    assert len(c.get("/api/matches", headers=_h("jwt-both")).json()) == 2
    assert [m["id"] for m in c.get("/api/matches", params={"facility_id": "fac-b"},
                                   headers=_h("jwt-both")).json()] == [b["id"]]
    # another tenant's match is indistinguishable from a missing one, for every verb
    assert c.get(f"/api/matches/{a['id']}", headers=_h("jwt-bob")).status_code == 404
    assert c.get(f"/api/matches/{a['id']}/video", headers=_h("jwt-bob")).status_code == 404
    assert c.get(f"/api/matches/{a['id']}/summary", headers=_h("jwt-bob")).status_code == 404
    assert c.delete(f"/api/matches/{a['id']}", headers=_h("jwt-bob")).status_code == 404
    assert c.patch(f"/api/matches/{a['id']}/review", json={}, headers=_h("jwt-bob")).status_code == 404
    # service token keeps working and sees everything
    assert len(c.get("/api/matches", headers=_h("service-secret")).json()) == 2
    # core API answers are cached per token
    n = len(calls)
    c.get("/api/matches", headers=_h("jwt-alice"))
    assert len(calls) == n


def test_media_token(client, tmp_path):
    c, _ = client
    a = _upload(c, tmp_path, "jwt-alice").json()
    b = _upload(c, tmp_path, "jwt-bob").json()
    mt = c.get("/api/media-token", headers=_h("jwt-alice")).json()["token"]
    assert mt.startswith("m1.")
    assert c.get(f"/api/matches/{a['id']}/video", params={"token": mt}).status_code == 200
    assert c.get(f"/api/matches/{b['id']}/video", params={"token": mt}).status_code == 404  # scoped
    assert c.delete(f"/api/matches/{a['id']}", params={"token": mt}).status_code == 401  # read-only
    assert c.get("/api/media-token", params={"token": mt}).status_code == 401  # cannot renew itself
    assert c.get("/api/matches", params={"token": mt[:-2] + "00"}).status_code == 401  # tampered


def test_share_link(client, tmp_path):
    import json

    import padel_analyzer.api.main as main

    c, _ = client
    a = _upload(c, tmp_path, "jwt-alice").json()
    url = f"/api/matches/{a['id']}/share"
    assert c.post(url, headers=_h("jwt-alice")).status_code == 409  # nothing to share before analysis
    (main.MATCH_DIR / a["id"] / "report.json").write_text(json.dumps({"match": {"hits": 3}, "players": [], "teams": [], "shots": [], "rallies": []}))
    assert c.post(url, headers=_h("jwt-bob")).status_code == 404  # only the owning facility can share
    assert c.post(url, params={"token": c.get("/api/media-token", headers=_h("jwt-alice")).json()["token"]}).status_code == 401
    tok = c.post(url, headers=_h("jwt-alice")).json()["share"]["token"]
    assert len(tok) >= 40 and c.get(url, headers=_h("jwt-alice")).json()["share"]["token"] == tok

    pub = c.get(f"/api/public/share/{tok}")  # no sign-in
    assert pub.status_code == 200 and pub.json()["match"]["title"] == "t" and "players" in pub.json()["report"]
    assert "facility_id" not in pub.json()["match"] and pub.headers["x-robots-tag"] == "noindex"
    assert c.get(f"/api/public/share/{tok}/video").status_code == 200
    assert c.get("/api/public/share/not-a-token").status_code == 404
    # the share token is not a sign-in: it opens nothing else
    assert c.get(f"/api/matches/{a['id']}", headers=_h(tok)).status_code == 401
    assert c.get(f"/api/matches/{a['id']}/video", params={"token": tok}).status_code == 401

    new = c.post(url, headers=_h("jwt-alice")).json()["share"]["token"]  # a new link revokes the old one
    assert c.get(f"/api/public/share/{tok}").status_code == 404 and c.get(f"/api/public/share/{new}").status_code == 200
    assert c.delete(url, headers=_h("jwt-alice")).json()["revoked"] == 1
    assert c.get(f"/api/public/share/{new}").status_code == 404
    assert c.get(url, headers=_h("jwt-alice")).json()["share"] is None
    tok3 = c.post(url, headers=_h("jwt-alice")).json()["share"]["token"]
    c.delete(f"/api/matches/{a['id']}", headers=_h("jwt-alice"))  # deleting the match ends its links
    assert c.get(f"/api/public/share/{tok3}").status_code == 404
