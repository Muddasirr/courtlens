"""Who hit the ball: per-hit evidence + the rule that the two sides alternate.

Evidence for each of the 4 slots at a hit: normalised wrist-to-ball distance around the contact. A side may
touch the ball only once, so consecutive hits belong to opposite ends unless a hit was missed; a Viterbi pass
over each rally trades the evidence against that rule. Decorte hit_assignments: EVAL §12.
"""
from __future__ import annotations

import numpy as np

MISSING = 3.0  # cost of a slot with no player / ball around the hit
SAME_END = 1.0  # penalty for two consecutive hits from the same end (middle of the stable 0.3-2 range)
MISSED_HIT_GAP_S = 2.5  # beyond this a hit in between may have been missed: no alternation penalty
GROUP_GAP_S = 4.0


def contact_costs(tracks, ball_xy: np.ndarray, f: int, window: int = 3) -> np.ndarray:
    """(4,) best wrist-to-ball distance (in player heights) within ±window frames of f."""
    cost = np.full(4, MISSING)
    n = len(ball_xy)
    for k in range(max(0, f - window), min(n, f + window + 1)):
        b = ball_xy[k]
        if np.isnan(b).any():
            continue
        for s in range(4):
            box = tracks.box[k, s]
            if np.isnan(box).any():
                continue
            h = max(box[3] - box[1], 1.0)
            w = [tracks.kpt[k, s, j, :2] for j in (9, 10) if tracks.kpt[k, s, j, 2] > 0.3]
            d = min(float(np.linalg.norm(x - b)) for x in w) / h if w else \
                float(np.hypot(max(box[0] - b[0], 0, b[0] - box[2]), max(box[1] - b[1], 0, b[1] - box[3]))) / h + 1
            cost[s] = min(cost[s], d)
    return cost


def assign(frames: list[int], tracks, ball_xy: np.ndarray, fps: float, same_end: float = SAME_END) -> list[int]:
    """Slot of the hitter for each hit (frames sorted); Viterbi within each group of hits."""
    out = [0] * len(frames)
    i = 0
    while i < len(frames):
        j = i
        while j + 1 < len(frames) and (frames[j + 1] - frames[j]) / fps <= GROUP_GAP_S:
            j += 1
        fs = frames[i:j + 1]
        unary = np.array([contact_costs(tracks, ball_xy, f) for f in fs])
        cost, back = unary[0].copy(), []
        for k in range(1, len(fs)):
            pen = same_end if (fs[k] - fs[k - 1]) / fps <= MISSED_HIT_GAP_S else 0.0
            step = np.array([[pen if (a < 2) == (b < 2) else 0.0 for a in range(4)] for b in range(4)])
            total = cost[None, :] + step  # (to, from)
            back.append(total.argmin(1))
            cost = total.min(1) + unary[k]
        s = int(cost.argmin())
        path = [s]
        for b in reversed(back):
            s = int(b[s])
            path.append(s)
        out[i:j + 1] = path[::-1]
        i = j + 1
    return out


# A hit needs the ball within reach of somebody. On a club camera with a 3-court venue (audio from the next
# courts) the hit model fires while players stand, walk or sit on the bench; Legends Arena audit: of 20 hits whose
# ball was > 3 body heights from the credited player, 17 were no hit at all (docs/EVAL.md §13).
REACH_BODY_HEIGHTS = 3.0  # box grown by a racket's reach (0.5 body height), then this many body heights


def out_of_reach(hits, ball_xy: np.ndarray, boxes: np.ndarray, image_h: int, window: int = 3) -> list[bool]:
    """Per hit: True when the ball is visible near contact and out of reach of every visible player.
    boxes: (n, 4, 4) xyxy per slot (nan = not detected). Kept (False) whenever it cannot be decided: no ball near
    the contact, or a player is cut off by / missing below the bottom of the frame while the ball is low."""
    n = len(ball_xy)
    out = []
    for h in hits:
        f = h.frame
        bp = next((ball_xy[f + k] for k in (0, -1, 1, -2, 2, -window, window)
                   if 0 <= f + k < n and np.isfinite(ball_xy[f + k, 0])), None)
        if bp is None:
            out.append(False)
            continue
        b = boxes[f]
        seen = ~np.isnan(b[:, 0])
        near_hidden = (~seen[2:]).any() or (b[2:, 3][seen[2:]] >= image_h - 4).any()
        if bp[1] > 0.6 * image_h and near_hidden:
            out.append(False)
            continue
        best = np.inf
        for x0, y0, x1, y1 in b[seen]:
            hgt = max(y1 - y0, 30.0)
            dx = max(x0 - 0.5 * hgt - bp[0], 0.0, bp[0] - (x1 + 0.5 * hgt))
            dy = max(y0 - 0.5 * hgt - bp[1], 0.0, bp[1] - y1)
            best = min(best, float(np.hypot(dx, dy)) / hgt)
        out.append(bool(seen.any()) and best > REACH_BODY_HEIGHTS)
    return out
