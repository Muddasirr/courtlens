# Padel analysis — how accurate is it?

What each number in a padel report is worth, how we know, and what would make it better.
Written for the Legends Arena footage (PlaySight camera, Court 1, three sessions, Nov 2026), with the
lab benchmarks beside it for comparison. Detailed experiment log: [EVAL.md](EVAL.md).

## 1. Two kinds of evidence

| | **Benchmark (labelled)** | **Legends Arena (no labels)** |
| --- | --- | --- |
| Footage | Professional broadcasts: PadelTracker100 finals (WPT 2022), 99 rallies from 11 WPT 2023 tournaments (Decorte et al.), FIP Kuwait 2025 | One fixed club camera, 1080p 25 fps, audio band-limited to 8 kHz, ~78 min of play in 3 sessions |
| Ground truth | Every ball position, player box, hit time, stroke type and hitter labelled by the dataset authors; point winners read off the scoreboard | None. Nobody has labelled this video |
| How we score | Models never see the match / tournament they are tested on (cross-match or leave-tournament-out) | Geometry checks against the known court size, and **random spot checks by eye** (20 shots at a time from a seeded random sample, `scripts/audit_sheet.py`) |
| Confidence | High: hundreds to thousands of labelled events | Moderate: small samples. 14/20 means "somewhere between ~50 % and ~85 %" (95 % interval) |

The benchmark tells us what the method can do on good footage. The Legends checks tell us how much of that
survives on this camera. Where the two differ, trust the Legends number for Legends reports.

## 2. Accuracy per report item

Rating: 🟢 measured and good · 🟡 usable, read as an estimate · 🔴 do not present as fact.

### Court and players

| Item | Legends Arena | Basis | Benchmark | Rating |
| --- | --- | --- | --- | --- |
| Court mapping (image → metres) | **3.5–4 cm** mean error on the court lines | ~1,100 points on the painted lines and floor edges vs the regulation court (10 × 20 m) | 3–7 cm | 🟢 |
| Player position on court | Feet visible: same as benchmark. Near player cut off by the frame: ~0.25 m (placed from the shoulders) | Simulated cut-offs on full-body frames (0.73 m before the fix) | 5 cm median, 15 cm p90 | 🟢 |
| Distance covered, spacing, net/back time, heatmaps | Follows from positions | — | within ±2 % of labelled distance | 🟢 |
| Which pair is which (team A / B) | **Fixed 2026-11-09.** Sessions 1 and 3 swapped the teams mid-session (at 9.9 min and 14.9–15.9 min) although nobody changed ends | Checked frame by frame around each split; see §4 | 52/52 and 61/61 segments | 🟢 |
| Which partner is which inside a pair | Not measurable (no labels anywhere) | — | — | 🟡 |
| Players far beyond the far glass | Not visible to the camera past 18.1 m | `quality.view_limit_y` | — | — |

### Ball

| Item | Legends Arena | Basis | Benchmark | Rating |
| --- | --- | --- | --- | --- |
| Ball found | **48 % / 45 % / 35 %** of frames (sessions 1/2/3) | Coverage of the tracked ball; was 10–13 % with the stock model | 87–90 % recall in rallies | 🟡 |
| Ball detections that are really the ball | **24/24** spot-checked (≈ 86–100 %) | Random tracked points checked by eye; 0/24 look-alikes on the held-out tail after the venue model | 91 % precision | 🟢 |
| Shot speed (racket → first bounce, average) | Given for **71 / 60 / 39** shots; median 54–55 km/h | Only shots where the ball is seen at contact and bounce. No radar exists for padel video, so checked physically (serves land in the service box 30/30, 35/36 on broadcast) | median diff. detected vs labelled ball 0.2–0.3 km/h | 🟡 |

The ball is the camera's weak point: it is 5–12 px wide, blurs, and disappears behind the glass and the near
players. Everything that needs the ball (speed, bounce, direction) exists for only part of the shots.

### Shots and rallies

| Item | Legends Arena | Basis | Benchmark | Rating |
| --- | --- | --- | --- | --- |
| Shots detected | 407 / 329 / 248 | Audio (8 kHz-trained) + video hit model | F1 0.94 (11 unseen tournaments, also at 8 kHz) | 🟡 |
| **Shot is real AND credited to the right player** | **~70 %** (14/20 latest; 13/20, 15/20 earlier) | Random 20-shot audits by eye | 93 % player, 97 % pair | 🟡 |
| Stroke type (forehand / backhand / volley / serve …) | **~2/3–3/4** of correctly credited shots | Same audits | 78–79 % | 🟡 |
| Smash | **~7/8** calls correct | Smash audit; a smash now requires the arm above the head | — | 🟢 |
| Rallies | 87 / 83 / 59 | Hits grouped by gaps; not counted against real points here | 23/24 points matched (Kuwait) | 🟡 |
| Points won, winners / errors | Estimate | Model guess of who won each rally | 69 % per point (coin flip ≈ 56 %) | 🔴 |
| Games / set score | Not produced unless points are confirmed in review | — | — | — |

The report itself says this in its footer: positions, distances and speeds are measured; shots, stroke types
and point winners are model estimates.

## 3. Why Legends is below the benchmark

1. **The audio is 8 kHz.** The hit sound's crisp part is above 4 kHz and is gone. Fixed by retraining on
   band-limited audio (0 → 534 audio hit candidates), but the sound cannot tell which court a hit came from.
2. **The near players are cut off by the bottom of the frame.** Their feet and often their racket arm are
   out of view, so the system sometimes credits a hit to a visible player instead.
3. **The ball is small and often hidden.** When it is not visible at the contact, the hitter is chosen from
   body pose and the alternation rule only. Most remaining wrong credits are players standing in the ready
   position while the ball was not visible.
4. **No labels from this venue.** Every model was trained on broadcast footage; the venue ball model was
   self-trained from its own confident tracks.

## 4. What has already been done on this footage

| Fix | Effect |
| --- | --- |
| Audio and hit models retrained for 8 kHz | Session 1: 39 → 45 rallies, 149 → 207 shots at that stage |
| Calibration refit from the court lines | 0.53 m → 3.5 cm error |
| Cut-off players placed from the shoulders | 0.73 m → 0.25 m |
| Smash requires an overhead arm | 93 smash calls (mostly wrong) → 20, ~7/8 correct |
| Broadcast "court view" rule off for fixed cameras | Stopped dropping 57 % of session 1's hits |
| Lower ball threshold on low-coverage cameras | Ball seen 10–13 % → 22–30 % |
| Ball model self-trained on this venue | Ball seen → 35–48 %; shots with speed 37/41/24 → 71/60/39 |
| Hits with the ball out of every player's reach removed | 18 / 14 / 7 false hits removed |
| A short empty court (2–9 s: ball fetched outside the glass, near pair below the frame) no longer counts as a possible change of ends; needs ≥ 30 s. Two-segment matching no longer always answers "swapped" | Team A/B stays on its own end; no more "hitting from both halves" |

## 5. What would improve it, in order of value

| # | Step | Expected gain | Effort | Needs |
| --- | --- | --- | --- | --- |
| 1 | **Hand-label one session** (who hit, when, stroke type) — ~400 shots | Turns every 🟡 above into a measured number, and trains the hitter and stroke models on this camera. Typical gain from in-venue labels: hitter ~70 % → 85 %+ | ~4–6 h of labelling in the review screen | Someone who knows padel |
| 2 | **Mirror positions after a real change of ends** in charts | Each team always drawn on its own half (only matters for matches where ends do change) | Small code change | Nothing |
| 3 | **Detect a real change of ends on a fixed camera** (players walking past the net post during a long break) | Correct teams in matches that do change ends | Medium | Nothing |
| 4 | **Clean audio from this court** (camera mic set to ≥ 16 kHz, or a court-side mic) | Hit timing and which-court separation; hit F1 on the benchmark is 0.94 with full audio | Venue setting | Club cooperation |
| 5 | **A second camera or a lower-tilted camera** showing the near players' feet | Fixes the cut-off-player problem at the source; hitter credit and stroke type would approach benchmark levels | Hardware | Club cooperation |
| 6 | **Racket detector** | Tells the hitting hand directly → forehand/backhand and hitter when the ball is hidden | Needs a labelled racket set (~1–2k boxes) | Labelling |
| 7 | **Point winners confirmed in review** | Unlocks real games and set scores | 2–3 min per session in the UI | A person watching |
| 8 | **More Legends sessions** | More self-training data for the ball model; better estimates of all rates | Upload | More footage from the club |

Steps 2 and 3 can be done now. Step 1 is the single biggest lever; steps 4–5 depend on the club.

## 6. How to present it

- Safe to state as measured: court positions, distance covered, heatmaps, team formations, net time, smash count.
- State as estimates: shots per player, stroke mix, ball speed (only on shots where it is shown).
- Do not present as fact: points won, winners/errors, anything that adds up per-point outcomes.
