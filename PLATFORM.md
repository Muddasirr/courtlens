# SportLens: one app for futsal and padel analytics

SportLens is the single product facilities use: one sign-in, one facility workspace, one URL. It hosts two sport
engines that were built and validated separately and stay independent:

| Sport | Engine (owner of the analysis) | Docs |
| --- | --- | --- |
| Futsal (and 11v11 football) | `backend/` (CourtLens): multi-camera tracking, identity, possession, events, review, publish | `PRD.md`, `ARCHITECTURE.md`, `EVAL.md`, `ROADMAP.md` |
| Padel | `padel/` (PadelLens): calibration, 4-player tracking, ball, audio+video hits, strokes, rallies, points | `padel/docs/*` |

This file covers the platform layer: how the pieces fit, how to run it, and what is still open.

## 1. Architecture

```
                         browser (SPA: web/)
                                 │  one origin
                     ┌───────────▼────────────┐
                     │  gateway (nginx)        │  TLS terminates in front of this
                     │  /            → SPA     │  security headers, CSP, rate limits,
                     │  /api/v1/*    → core    │  request ids, JSON access log without
                     │  /padel/api/* → padel   │  query strings, streamed uploads/video
                     └──────┬───────────┬──────┘
                            │           │
             ┌──────────────▼──┐     ┌──▼──────────────────┐
             │ core-api        │◄────│ padel               │  padel asks core "which facilities
             │ FastAPI         │ JWT │ FastAPI + SQLite    │  does this token belong to?"
             │ users, roles,   │check│ match files, report │  (cached 60 s), then scopes every
             │ facilities,     │     │ in-process worker   │  match/camera to them
             │ futsal product  │     └──────────┬──────────┘
             └──┬────────┬─────┘                │
       Postgres │        │ Redis queue          │ Kaggle GPU (hadivenix)
             ┌──▼──┐ ┌───▼────────┐             ▼
             │ db  │ │ core-worker│──► Kaggle GPU (muddasirr) / local YOLO
             └─────┘ └────────────┘
```

Design choices:

- **Modular monolith per sport, behind one edge.** Each sport keeps its own data model, pipeline, models and
  Kaggle account; the platform shares identity, tenancy and the UI. No shared database, no cross-imports
  between `backend/` and `padel/`. A sport can be deployed, scaled or rolled back on its own.
- **Core API is the identity provider.** Users, facilities and roles live in the core (Postgres). The padel
  service trusts the core JWT by asking the core API for the caller's facility memberships (no shared secret
  beyond the gateway network, no shared DB). Answers are cached per token for 60 s; the core API being down
  fails closed.
- **Tenant isolation on every request.** Futsal: facility-scoped routes + role checks (existing). Padel:
  `matches.facility_id` / `cameras.facility_id`; list endpoints filter by the caller's facilities, and every
  per-match route returns 404 for another tenant's match (no existence leak).
- **No sign-in token in URLs.** `<video>`, `<img>` and download links cannot send headers, so the padel UI uses
  a media token: HMAC-signed, GET-only, tenant-scoped, 6 h TTL, refreshed by the shell, and unable to mint its
  successor. The gateway never logs query strings.
- **One web app, sport UIs as modules.** `web/` is the shell (sign-in, facility switcher, cross-sport
  Overview, cross-match Players). The futsal and padel UIs are imported from their own source trees
  (`frontend/src`, `padel/web/src`), so work on either UI shows up in SportLens without copying. Each sport's global
  stylesheet is namespaced at build time (`.sl-futsal`, `.sl-padel`), so the two design systems cannot leak
  into each other. Sport UIs are separate lazy-loaded chunks (shell 22 kB, padel 35 kB, futsal 61 kB).
- **Standalone apps keep working.** `docker-compose.yml` (futsal dev, :8001/:5174) and
  `padel/docker-compose.yml` (:8010) are unchanged. With no `PADEL_AUTH_URL` / `PADEL_API_TOKEN`, padel behaves
  exactly as before.

### 1.1 Padel share links

The report's **Share** button creates a public link (`/share/padel/<token>`) that opens the match report read-only
without sign-in: video with player overlay, stats, pairs, rallies and shots. The token is 32 random bytes and is
the only credential; it opens nothing but `GET /api/public/share/<token>` and its video (no other padel or core
route accepts it). One active link per match: creating a new one or **Turn off link** revokes the old one, and
deleting the match ends it. Responses carry `X-Robots-Tag: noindex`.

### Request routing

| Path | Service | Notes |
| --- | --- | --- |
| `/`, `/facilities/...`, `/report/<token>` | SPA | `index.html` fallback, `no-cache`; `/assets/*` immutable for 1 year |
| `/api/v1/auth/*` | core | 10 req/min per IP (burst 10) |
| `/api/v1/storage/*` | core | signed video upload/download, streamed (no buffering), 1 h timeouts |
| `/api/v1/*`, `/api/health`, `/health` | core | 30 req/s per IP (burst 60) |
| `/padel/api/*` | padel `/api/*` | multipart uploads + ranged video streamed, 1 h timeouts |
| `/healthz` | gateway | liveness |

### Web routes

| Route | Page |
| --- | --- |
| `/` | sign-in / facility list (goes straight in when there is one facility) |
| `/facilities/:id` | Overview: pipeline counts (setup → processing → review → published / failed), sport cards, all matches across sports; polls while anything is processing |
| `/facilities/:id/futsal` | futsal squad & fixtures (CourtLens) |
| `/facilities/:id/matches/:mid[/label]` | futsal match centre / event labelling (CourtLens paths kept so its links work) |
| `/facilities/:id/padel#/…` | padel matches, calibration, report (PadelLens hash routes) |
| `/facilities/:id/players` | season totals per player, per sport, over the latest 30 analysed matches (4 requests in flight). Futsal players are roster entities; padel players are grouped by the name given in review (unnamed "Player N" stay per match) |
| `/report/:token` | public futsal share report (no sign-in; revoked → 404) |
| `/share/padel/:token` | public padel match report: video with player overlay, stats, rallies, shots; read-only, no sign-in |

### Adding a sport

1. Run its service behind the gateway (`location /<sport>/api/`), accepting the core JWT the way
   `padel/padel_analyzer/api/platform_auth.py` does.
2. Add a `SportDef` in `web/src/lib/sports.ts` (list matches, status → stage, player lines, columns).
3. Add a lazy module in `web/src/sports/` and a nav entry/route in `web/src/App.tsx`.

## 2. Run it

### Production-style stack

```bash
cp .env.platform.example .env.platform        # set POSTGRES_PASSWORD, JWT_SECRET, PADEL_MEDIA_SECRET (openssl rand -hex 32)
DOCKER_CONTEXT=default docker compose -p sportlens -f docker-compose.platform.yml --env-file .env.platform up -d --build
# -> http://localhost:8080
```

- Separate compose project, database, Redis and volumes from the futsal dev stack. Its worker never sees the
  dev queue (a worker re-queues or fails "running" jobs it finds at start-up, so two workers must not share one queue).
- Only the gateway publishes a port. Put TLS in front of it (load balancer or Caddy/Traefik) and set
  `PUBLIC_URL` to the public origin.
- GPU: futsal jobs use the Kaggle account in `~/.kaggle` (`muddasirr`), padel jobs use
  `KAGGLE_API_KEY_LSECOND` (`hadivenix`). Keep them separate.
- Scale futsal processing with `--scale core-worker=N`; API replicas with `CORE_API_WORKERS`.
- Padel matches created before platform sign-in have no facility: set `PADEL_LEGACY_FACILITY=<facility id>` once
  to file them under it. Until then only the padel service token (`PADEL_API_TOKEN`) can see them.
- With S3 storage, set `STORAGE_BACKEND=s3` + `S3_*`; the gateway adds `S3_PUBLIC_ENDPOINT` to the CSP.

### Development

```bash
# APIs: the futsal dev stack (docker-compose.yml, :8001) + padel (:8010)
cd padel && PADEL_AUTH_URL=http://localhost:8001 PADEL_BACKEND=local .venv/bin/uvicorn padel_analyzer.api.main:app --port 8010
cd web && npm install && npm run dev            # http://localhost:5180, proxies /api/v1 and /padel/api like the gateway
```

Note: the dev stack's `JWT_SECRET` is `dev-change-me`. Never use that value outside a laptop.

## 3. Tests

| Check | Command | Result (2026-11-02) |
| --- | --- | --- |
| Futsal/core backend | `cd backend && .venv/bin/python -m pytest -q tests` | 119 passed |
| Padel API + platform auth | `cd padel && .venv/bin/python -m pytest -q tests/test_api.py tests/test_platform_auth.py` | 4 passed |
| Padel full suite on Kaggle (lightgbm, DINOv2 end to end) | `python padel/kaggle/kaggle_cli.py code && python padel/kaggle/kaggle_cli.py push tests` | 23 passed |
| Web typecheck (strict, shell + both sport UIs) + build | `cd web && npm run build` | ok |
| API end to end through the gateway | `padel/.venv/bin/python scripts/platform_smoke.py --base http://localhost:8080` | 32/32: health, SPA fallback, security headers, sign-up/in, futsal + padel tenant isolation, padel upload, ranged video and frames with media token, media token read-only and tenant-scoped |
| Design quality (Impeccable detector, 0 findings in shell, futsal and padel sources and rendered pages) | `cd web && npm run lint:design` | 0 findings |
| UI in a real browser | `padel/.venv/bin/python scripts/platform_ui_smoke.py --shots /tmp/shots` | sign-up → facility → Overview → futsal match centre → padel → Players → 390 px mobile: no page errors, no 5xx, no horizontal scroll |

Also checked by hand on the stack: a real analysed padel match (Kuwait 2025, 10 min) plays with overlays and
mini-court through the gateway, and the Players table aggregates two padel matches. The access log
contains no tokens.

## 4. What is still open

Platform (this layer):

- **Padel jobs are in-process** (one at a time; a restart marks running jobs failed and they are re-run from the UI).
  Next step: move them onto a durable queue like futsal's Redis worker. Owned by the padel engine. Not changed here.
- **Padel storage is a local volume** (SQLite + files). For more than one padel replica, move to Postgres
  (`PADEL_DB_URL`) and object storage.
- **Roles in padel:** any facility member can edit and delete padel matches. Futsal enforces owner, staff and
  reviewer roles. Padel should read the role too (needs a role field on the core `/facilities` response).
- **Padel highlight clips** (share links are done: see 1.1).
- **Cross-match stats are aggregated in the browser** (latest 30 matches). When facilities exceed that, add a
  stats read model (per-player rows written when a report is finalised).
- Observability beyond logs: metrics (Prometheus), error tracking (Sentry), alerts on stuck jobs (PRD §6.4).
- SSO, invite emails, billing.

Model quality and missing stats (owned by the sport engines; from `ROADMAP.md`, `padel/docs/ROADMAP.md` and the engine sessions):

| Futsal / football | Padel |
| --- | --- |
| Labelled venue footage (W0) blocks every accuracy gate | No validation yet on the customer's own cameras |
| Shots/goals: futsal 3/7 shots; football ≈ 0 until the spotter checkpoint switch lands | Point winner 72 % → score/games only from confirmed winners |
| Identity fragments (27 "players" for 22 people); many events have no player | Forced vs unforced errors, smash outs (por 3/4), highlight clips |
| Jersey numbers ~0 → staff rename | Bandeja / víbora / lob need labelled match footage |
| Set pieces (corners, free kicks, penalties), fouls, cards, saves: staff-tagged only | Club-camera ball detection (venue retraining) |
| `possession_coverage_pct` reads 100 % when the ball was seen in 54 % of frames | |
| Metres / speeds only after calibration | |
