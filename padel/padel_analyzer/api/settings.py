from __future__ import annotations

import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.environ.get("PADEL_DATA_DIR", ROOT / "data" / "app"))
MATCH_DIR = DATA_DIR / "matches"
DB_URL = os.environ.get("PADEL_DB_URL", f"sqlite:///{DATA_DIR / 'padel.db'}")
DEVICE = os.environ.get("PADEL_DEVICE") or None  # None = cuda if available else cpu
POSE_STRIDE = int(os.environ.get("PADEL_POSE_STRIDE", "2"))
MAX_FRAMES = int(os.environ.get("PADEL_MAX_FRAMES", "0"))  # 0 = whole video
# kaggle = run detection + analysis on the Kaggle GPU (account in ../.env), local = this machine
BACKEND = os.environ.get("PADEL_BACKEND", "kaggle")
CORS = os.environ.get("PADEL_CORS", "http://localhost:5175,http://127.0.0.1:5175").split(",")
WEB_DIST = ROOT / "web" / "dist"
# optional shared secret: when set, every /api request needs "Authorization: Bearer <token>" (or ?token= for
# <video>/<img> URLs, which cannot send headers); /api/health stays open for load balancers
API_TOKEN = os.environ.get("PADEL_API_TOKEN", "")
# SportLens platform sign-in: core API base URL (e.g. http://core-api:8000). When set, the core JWT is accepted
# (Bearer or ?token=) and matches are scoped to the caller's facilities; PADEL_API_TOKEN stays a service token
AUTH_URL = os.environ.get("PADEL_AUTH_URL", "").rstrip("/")
AUTH_CACHE_S = int(os.environ.get("PADEL_AUTH_CACHE_S", "60"))
# <video>/<img>/download URLs cannot send headers: they carry a short-lived, read-only media token signed with
# this secret instead of the sign-in JWT. Set it when running more than one replica (random per process otherwise)
MEDIA_SECRET = os.environ.get("PADEL_MEDIA_SECRET", "")
MEDIA_TOKEN_TTL_S = int(os.environ.get("PADEL_MEDIA_TOKEN_TTL_S", str(6 * 3600)))
# matches created before platform sign-in have no facility; set this to file them under one facility at startup,
# otherwise they stay visible only through PADEL_API_TOKEN
LEGACY_FACILITY = os.environ.get("PADEL_LEGACY_FACILITY", "")
KAGGLE_JOB_TIMEOUT_S = int(os.environ.get("PADEL_KAGGLE_TIMEOUT_S", str(9 * 3600)))  # Kaggle kernels stop at 12 h

MATCH_DIR.mkdir(parents=True, exist_ok=True)
