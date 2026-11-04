"""Padel court geometry and floor-plane calibration.

Court frame (metres): x in [0, 10] across (camera left -> right), y in [0, 20] along,
y = 0 at the far back wall, net at y = 10. Same frame as PadelTracker100.
"""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

WIDTH = 10.0
LENGTH = 20.0
NET_Y = 10.0
SERVICE_FROM_NET = 6.95
SERVICE_Y = (NET_Y - SERVICE_FROM_NET, NET_Y + SERVICE_FROM_NET)  # 3.05, 16.95
NET_ZONE_M = 4.0

LANDMARKS: dict[str, tuple[float, float]] = {
    "far_left": (0.0, 0.0),
    "far_right": (WIDTH, 0.0),
    "far_service_left": (0.0, SERVICE_Y[0]),
    "far_service_t": (WIDTH / 2, SERVICE_Y[0]),
    "far_service_right": (WIDTH, SERVICE_Y[0]),
    "net_left": (0.0, NET_Y),
    "net_centre": (WIDTH / 2, NET_Y),
    "net_right": (WIDTH, NET_Y),
    "near_service_left": (0.0, SERVICE_Y[1]),
    "near_service_t": (WIDTH / 2, SERVICE_Y[1]),
    "near_service_right": (WIDTH, SERVICE_Y[1]),
    "near_left": (0.0, LENGTH),
    "near_right": (WIDTH, LENGTH),
}

# Painted floor lines (the net line is the net's foot; it is drawn but not painted).
LINES: list[tuple[tuple[float, float], tuple[float, float]]] = [
    ((0, 0), (WIDTH, 0)),
    ((0, LENGTH), (WIDTH, LENGTH)),
    ((0, 0), (0, LENGTH)),
    ((WIDTH, 0), (WIDTH, LENGTH)),
    ((0, SERVICE_Y[0]), (WIDTH, SERVICE_Y[0])),
    ((0, SERVICE_Y[1]), (WIDTH, SERVICE_Y[1])),
    ((WIDTH / 2, SERVICE_Y[0]), (WIDTH / 2, SERVICE_Y[1])),
]
NET_LINE = ((0.0, NET_Y), (WIDTH, NET_Y))
# Lines that are actually painted white on the floor (used by auto-refinement).
PAINTED = [LINES[4], LINES[5], LINES[6]]


def zone(y: float | np.ndarray) -> np.ndarray:
    """0 = net zone, 1 = transition, 2 = back (behind the service line)."""
    d = np.abs(np.asarray(y, dtype=float) - NET_Y)
    return np.where(d <= NET_ZONE_M, 0, np.where(d <= SERVICE_FROM_NET, 1, 2))


def side(y: float | np.ndarray) -> np.ndarray:
    """0 = far side (y < 10), 1 = near side."""
    return (np.asarray(y, dtype=float) >= NET_Y).astype(int)


def project(H: np.ndarray, pts: np.ndarray) -> np.ndarray:
    """Apply a 3x3 homography to (N, 2) points."""
    pts = np.asarray(pts, dtype=np.float64).reshape(-1, 2)
    ph = np.c_[pts, np.ones(len(pts))] @ np.asarray(H, dtype=np.float64).T
    w = ph[:, 2:3]
    w = np.where(np.abs(w) < 1e-12, 1e-12, w)
    return ph[:, :2] / w


@dataclass
class Calibration:
    """Image px <-> court metres for one fixed camera."""

    H: np.ndarray  # undistorted image px -> court metres
    image_size: tuple[int, int]  # (w, h)
    points_px: dict[str, tuple[float, float]] | None = None
    reproj_m: float | None = None  # mean landmark error in metres (fit residual)
    k1: float = 0.0  # radial lens distortion (division model, radius normalised by the half-diagonal)

    @property
    def H_inv(self) -> np.ndarray:
        return np.linalg.inv(self.H)

    def undistort(self, px: np.ndarray) -> np.ndarray:
        return undistort(px, self.k1, self.image_size)

    def distort(self, px: np.ndarray) -> np.ndarray:
        return distort(px, self.k1, self.image_size)

    def to_m(self, px: np.ndarray) -> np.ndarray:
        return project(self.H, self.undistort(px))

    def to_px(self, m: np.ndarray) -> np.ndarray:
        return self.distort(project(self.H_inv, m))

    def to_dict(self) -> dict:
        return {
            "H": np.asarray(self.H).tolist(),
            "image_size": list(self.image_size),
            "points_px": self.points_px,
            "reproj_m": self.reproj_m,
            "k1": self.k1,
        }

    @classmethod
    def from_dict(cls, d: dict) -> "Calibration":
        return cls(
            H=np.asarray(d["H"], dtype=np.float64),
            image_size=tuple(d["image_size"]),
            points_px={k: tuple(v) for k, v in (d.get("points_px") or {}).items()} or None,
            reproj_m=d.get("reproj_m"),
            k1=float(d.get("k1") or 0.0),
        )


def _norm(image_size: tuple[int, int]) -> tuple[np.ndarray, float]:
    w, h = image_size
    return np.array([w / 2.0, h / 2.0]), float(np.hypot(w, h) / 2.0)


def undistort(px: np.ndarray, k1: float, image_size: tuple[int, int]) -> np.ndarray:
    """Division model: p_u = c + (p_d - c) / (1 + k1 r_d^2). k1 < 0 corrects barrel (wide-angle) lenses."""
    px = np.asarray(px, dtype=np.float64).reshape(-1, 2)
    if not k1:
        return px
    c, s = _norm(image_size)
    q = (px - c) / s
    r2 = (q ** 2).sum(1, keepdims=True)
    return c + q / (1 + k1 * r2) * s


def distort(px: np.ndarray, k1: float, image_size: tuple[int, int]) -> np.ndarray:
    """Inverse of `undistort` (radial, solved per point: r_u = r_d / (1 + k1 r_d^2))."""
    px = np.asarray(px, dtype=np.float64).reshape(-1, 2)
    if not k1:
        return px
    c, s = _norm(image_size)
    q = (px - c) / s
    ru = np.linalg.norm(q, axis=1)
    # k1 ru rd^2 - rd + ru = 0  ->  rd = (1 - sqrt(1 - 4 k1 ru^2)) / (2 k1 ru)
    disc = np.clip(1 - 4 * k1 * ru ** 2, 0, None)
    with np.errstate(divide="ignore", invalid="ignore"):
        rd = np.where(ru > 1e-9, (1 - np.sqrt(disc)) / (2 * k1 * ru), 0.0)
        scale = np.where(ru > 1e-9, rd / ru, 1.0)
    return c + q * scale[:, None] * s


def fit(points_px: dict[str, tuple[float, float]], image_size: tuple[int, int]) -> Calibration:
    """Homography from >= 4 clicked landmarks (RANSAC when >= 5 so one bad click is tolerated)."""
    names = [n for n in points_px if n in LANDMARKS]
    if len(names) < 4:
        raise ValueError(f"need at least 4 known landmarks, got {len(names)}")
    src = np.array([points_px[n] for n in names], dtype=np.float64)
    dst = np.array([LANDMARKS[n] for n in names], dtype=np.float64)
    if _degenerate(dst):
        raise ValueError("landmarks are (nearly) collinear — pick points on at least two different lines")
    method = cv2.RANSAC if len(names) >= 5 else 0
    H, _ = cv2.findHomography(src, dst, method, ransacReprojThreshold=0.35)
    if H is None:
        raise ValueError("homography fit failed")
    err = float(np.linalg.norm(project(H, src) - dst, axis=1).mean())
    best = Calibration(H=H, image_size=tuple(image_size), points_px=dict(points_px), reproj_m=err)
    if len(names) >= 6 and err > 0.08:
        # wide-angle club cameras: fit one radial distortion term with the homography (least squares,
        # all points — distortion, not a bad click, is the usual reason the plain fit is off)
        for k1 in np.linspace(-0.6, 0.3, 91):
            und = undistort(src, k1, image_size)
            Hk, _ = cv2.findHomography(und, dst, 0)
            if Hk is None:
                continue
            e = float(np.linalg.norm(project(Hk, und) - dst, axis=1).mean())
            if e < best.reproj_m - 1e-4:
                best = Calibration(H=Hk, image_size=tuple(image_size), points_px=dict(points_px), reproj_m=e,
                                   k1=round(float(k1), 3))
    return best


def _degenerate(m: np.ndarray) -> bool:
    c = m - m.mean(0)
    s = np.linalg.svd(c, compute_uv=False)
    return s[-1] < 0.5


def floor_error_m(H_est: np.ndarray, H_ref: np.ndarray, step: float = 0.5) -> float:
    """Mean metres between where two calibrations put the same image points, over the floor."""
    xs, ys = np.meshgrid(np.arange(0, WIDTH + 1e-6, step), np.arange(0, LENGTH + 1e-6, step))
    grid_m = np.c_[xs.ravel(), ys.ravel()]
    px = project(np.linalg.inv(H_ref), grid_m)
    return float(np.linalg.norm(project(H_est, px) - grid_m, axis=1).mean())


def line_points_m(step: float = 0.1, lines=None) -> np.ndarray:
    out = []
    for (x0, y0), (x1, y1) in lines or LINES:
        n = max(2, int(np.hypot(x1 - x0, y1 - y0) / step))
        t = np.linspace(0, 1, n)
        out.append(np.c_[x0 + t * (x1 - x0), y0 + t * (y1 - y0)])
    return np.vstack(out)


def white_line_mask(frame_bgr: np.ndarray) -> np.ndarray:
    """Thin bright structures (court paint) via a white top-hat on lightness."""
    lab = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2LAB)
    L = lab[:, :, 0]
    k = cv2.getStructuringElement(cv2.MORPH_RECT, (15, 15))
    th = cv2.morphologyEx(L, cv2.MORPH_TOPHAT, k)
    sat = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)[:, :, 1]
    mask = ((th > 25) & (sat < 90)).astype(np.uint8)
    return cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((2, 2), np.uint8))


def refine(frame_bgr: np.ndarray, calib: Calibration, sigma_px: float = 12.0) -> tuple[Calibration, dict]:
    """Snap a clicked calibration onto the painted lines (service lines + centre line).

    Only three lines are painted on a padel floor (the outline is glass), so lines alone do not
    pin all 8 dof; the clicks act as a prior: cost = truncated line distance + ((anchor shift)/sigma)^2.
    Corrects a few pixels of click error; it is not a from-scratch detector.
    """
    from scipy.optimize import minimize

    if calib.k1:
        return calib, {"skipped": "lens distortion fitted; snap assumes an undistorted image"}
    mask = white_line_mask(frame_bgr)
    dist = cv2.distanceTransform((1 - mask).astype(np.uint8), cv2.DIST_L2, 3)
    h, w = dist.shape
    trunc = 8.0
    samples_m = line_points_m(0.05, PAINTED)
    anchors_m = np.array([[0, SERVICE_Y[0]], [WIDTH, SERVICE_Y[0]], [WIDTH, SERVICE_Y[1]], [0, SERVICE_Y[1]]])
    a0 = calib.to_px(anchors_m).ravel()

    def H_from(a: np.ndarray) -> np.ndarray:
        return cv2.getPerspectiveTransform(a.reshape(4, 2).astype(np.float32), anchors_m.astype(np.float32))

    def line_cost(v: np.ndarray) -> float:
        px = project(np.linalg.inv(H_from(v)), samples_m)
        x, y = px[:, 0], px[:, 1]
        inside = (x >= 0) & (x < w - 1) & (y >= 0) & (y < h - 1)
        if inside.sum() < 0.5 * len(px):
            return trunc
        d = cv2.remap(dist, x[inside].astype(np.float32).reshape(1, -1), y[inside].astype(np.float32).reshape(1, -1),
                      cv2.INTER_LINEAR).ravel()
        return float(np.minimum(d, trunc).mean())

    def cost(v: np.ndarray) -> float:
        shift = np.linalg.norm((v - a0).reshape(4, 2), axis=1)
        return line_cost(v) + float(np.mean((shift / sigma_px) ** 2))

    before = line_cost(a0)
    res = minimize(cost, a0, method="Powell", options={"maxiter": 4000, "xtol": 0.05, "ftol": 1e-5})
    after = line_cost(res.x)
    best = res.x if after < before else a0
    out = Calibration(H=H_from(best), image_size=calib.image_size, points_px=calib.points_px, reproj_m=calib.reproj_m)
    return out, {"line_cost_before_px": round(before, 2), "line_cost_after_px": round(min(after, before), 2)}


def draw(frame: np.ndarray, calib: Calibration, color=(0, 255, 255), thickness: int = 2) -> np.ndarray:
    out = frame.copy()
    for (a, b) in LINES + [NET_LINE]:
        p = calib.to_px(line_points_m(0.25, [(a, b)]))
        cv2.polylines(out, [p.astype(np.int32).reshape(-1, 1, 2)], False, color, thickness, cv2.LINE_AA)
    return out


# --- 3D camera from the floor homography -------------------------------------------------------------
# Club cameras sit high behind one end, so the near pair's feet often leave the frame while their upper
# body is still visible. The floor homography + a square-pixel pinhole (centred principal point) pins the
# camera, which lets a body point at a known height (shoulders) be placed on the floor.

SHOULDER_HEIGHT_M = 1.45  # median for adult club players; fitted on Legends Arena full-body samples (bias 0.02 m)
_CAM_CACHE: dict[bytes, dict] = {}


def camera_model(calib: Calibration) -> dict | None:
    """{K, R, t, C, up, rms_px} or None when the homography does not give a usable camera."""
    key = np.asarray(calib.H, np.float64).tobytes() + repr(calib.image_size).encode()
    if key in _CAM_CACHE:
        return _CAM_CACHE[key]
    cam = None
    try:
        cam = _fit_camera(np.asarray(calib.H, np.float64), calib.image_size)
        # a camera below the floor, absurd focal length or a poor fit means the pinhole model does not hold
        if not (1.0 < abs(cam["C"][2]) < 40.0 and 100 < cam["K"][0, 0] < 20000 and cam["rms_px"] < 25):
            cam = None
    except Exception:  # noqa: BLE001 - degenerate geometry: fall back to floor-only placement
        cam = None
    _CAM_CACHE[key] = cam
    return cam


def _fit_camera(H: np.ndarray, size: tuple[int, int]) -> dict:
    from scipy.optimize import least_squares

    w, h = size
    cx, cy = w / 2, h / 2
    G = np.linalg.inv(H)
    G = G / G[2, 2]
    A = np.linalg.inv(np.array([[1, 0, cx], [0, 1, cy], [0, 0, 1.0]])) @ G
    a1, a2 = A[:, 0], A[:, 1]
    # |r1| = |r2| and r1.r2 = 0 each give f^2; one of them is ill-conditioned when the camera sits on an axis
    f2 = [c for c in (-((a1[0] ** 2 + a1[1] ** 2) - (a2[0] ** 2 + a2[1] ** 2)) / (a1[2] ** 2 - a2[2] ** 2 + 1e-18),
                      -(a1[0] * a2[0] + a1[1] * a2[1]) / (a1[2] * a2[2] + 1e-18)) if np.isfinite(c) and c > 0]
    f = float(np.sqrt(max(f2))) if f2 else float(w)
    K = np.array([[f, 0, cx], [0, f, cy], [0, 0, 1]])
    M = np.linalg.inv(K) @ G
    lam = 2 / (np.linalg.norm(M[:, 0]) + np.linalg.norm(M[:, 1]))
    r1, r2, t = M[:, 0] * lam, M[:, 1] * lam, M[:, 2] * lam
    if t[2] < 0:
        r1, r2, t = -r1, -r2, -t
    U, _, Vt = np.linalg.svd(np.c_[r1, r2, np.cross(r1, r2)])
    rv, _ = cv2.Rodrigues(U @ Vt)
    g = np.array([[x, y] for x in np.linspace(0, WIDTH, 11) for y in np.linspace(0, LENGTH, 21)])
    px = project(G, g)
    keep = (px[:, 0] > -w) & (px[:, 0] < 2 * w) & (px[:, 1] > -h) & (px[:, 1] < 2 * h)
    g, px = g[keep], px[keep]

    def res(p: np.ndarray) -> np.ndarray:
        Rm, _ = cv2.Rodrigues(p[1:4])
        Kp = np.array([[p[0], 0, cx], [0, p[0], cy], [0, 0, 1]])
        q = (Kp @ (Rm @ np.c_[g, np.zeros(len(g))].T + p[4:7, None])).T
        return (q[:, :2] / q[:, 2:] - px).ravel()

    r = least_squares(res, np.r_[f, rv.ravel(), t], x_scale="jac")
    R, _ = cv2.Rodrigues(r.x[1:4])
    K = np.array([[r.x[0], 0, cx], [0, r.x[0], cy], [0, 0, 1]])
    C = -R.T @ r.x[4:7]
    return {"K": K, "R": R, "t": r.x[4:7], "C": C, "up": float(np.sign(C[2])),
            "rms_px": float(np.sqrt(np.mean(r.fun ** 2)))}


def floor_under(calib: Calibration, px: np.ndarray, height_m: float) -> np.ndarray | None:
    """Floor metres under image points that are `height_m` above the floor (None without a camera model)."""
    cam = camera_model(calib)
    if cam is None:
        return None
    p = calib.undistort(np.asarray(px, np.float64).reshape(-1, 2))
    d = (cam["R"].T @ (np.linalg.inv(cam["K"]) @ np.c_[p, np.ones(len(p))].T)).T
    s = (cam["up"] * height_m - cam["C"][2]) / d[:, 2]
    return cam["C"][None, :2] + s[:, None] * d[:, :2]


def view_limit_y(calib: Calibration) -> float | None:
    """Court y beyond which a standing player's shoulders leave the bottom of the frame (None if all in view)."""
    w, h = calib.image_size
    m = floor_under(calib, np.array([[w / 2, h - 1]]), SHOULDER_HEIGHT_M)
    if m is None:
        return None
    y = float(m[0, 1])
    return y if NET_Y < y < LENGTH else None
