# Activity log

## 2026-10-28
- Diagnosed the hosted API: front page loads, `/api/*` returns Cloudflare 502; upstream issue #4
  (Sep 26, 2026) reports the same. The backend was never published (repo has only Website/ and src/client/).
- Decision (owner): build our own real-news estimator instead of depending on the dead service.
- Built `worldline.py` (zero dependencies): RSS/Atom ingest, de-dup, story clustering, lexicon scorer,
  optional LLM scorer, two-timescale climate, z-score normalisation, worldline mapping, JSON/TXT output.
- Tests: 16 unit tests pass (scoring direction, negation, mapping continuity/bounds, dynamics, de-dup,
  clustering, parsing, output format).
- Found and fixed two bugs via simulation: (1) cold-start drift - re-running with no new news moved the
  value away from 1.048596; (2) over-reaction in week one - added calibration damping and a running-average
  "normal" for the first runs.
- Simulation (21 synthetic days): quiet noise stays around 1.03-1.06; a half-day war burst drops to ~0.49
  and recovers over ~2-3 days; a ceasefire burst lifts to ~1.13 and decays over ~5 days.
- NOT done / NOT verified: live RSS fetching (sandbox blocks those hosts), LLM scorer (no API key),
  ESP32 sketch (not compiled), GitHub Action (not run).

## Next
- [ ] Push to GitHub, run the workflow once, confirm `data/divergence.txt` exists.
- [ ] Verify every feed URL in the first Action log; drop dead ones.
- [ ] Paste v2 multi-mode sketch so Online mode can be wired in properly.
- [ ] After ~2 weeks of history, review the z distribution and tune constants.

## 2026-10-28 (later)
- Restructured into one repo, REnixie;clock (GitHub repo name `REnixie-clock`, since `;` is not allowed):
  `worldline/`, `firmware/`, `hardware/`, `docs/`, `scripts/`.
- Moved the 48 daily data commits to a separate `worldline-data` branch. The update script was tested
  locally against a bare git remote (first run creates the branch, later runs commit, unchanged data
  commits nothing, main untouched). The GitHub Action itself has not run yet.
- Added `badge.json` so the README can show the live value.
