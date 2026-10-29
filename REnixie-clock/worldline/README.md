# worldline-estimator

A **news-based worldline reading**. Every 30 minutes it reads world-news RSS feeds,
scores the stories, and publishes a single 8-character value (baseline `1.048596`) that a clock or
any other device can poll.

* `divergence.txt` - just the value, e.g. `1.048596` (what the ESP32 reads)
* `badge.json` - for the live badge on the repo front page
* `divergence.json` - value, field (alpha/beta), z-score, calibration flag, top stories of the day
* `history.json` and `state.json` - the time series and the model state

All of these live on the `worldline-data` branch.

No servers to keep alive: a scheduled GitHub Action runs the script and commits the files.

## Running it

Inside the REnixie;clock repo the setup steps live in [`../docs/setup.md`](../docs/setup.md).
A scheduled GitHub Action runs `scripts/update_worldline.sh`, which runs this script and commits the
output to the `worldline-data` branch.

Local test: `python worldline.py run --data /tmp/wd` (needs internet) -
`python worldline.py score "headline"` - `python -m unittest discover -s tests`.

## Method

1. **Fetch** feeds listed in `FEEDS` (dead feeds are skipped; if all fail the meter is left untouched).
2. **De-duplicate**: an item is counted once. Paraphrases of one story from different outlets are merged
   into one story; the number of outlets boosts its impact (`I = severity * (1 + 0.5*(outlets-1))`, max 1).
3. **Score** each story: valence `v` in [-1, 1] (escalation vs resolution) and severity in [0, 1].
   Default scorer is a keyword lexicon (free, deterministic). Optional: an LLM scorer, or a 50/50 blend.
4. **Accumulate** into two leaky sums with weight `w = I^2` (big stories dominate): a fast one
   (12 h half-life) and a slow one (3 d half-life). The *news climate* is
   `C = mean of (sum(w v) + K*mu) / (sum(w) + K)` for both. With no evidence, C falls back to "normal".
5. **Normalise**: `z = (C - mu) / sigma`, where `mu` and `sigma` are the climate's own long-run mean and
   spread (30-day half-life). The constant background of bad news is therefore "normal"; only
   **surprise** moves the meter. This is the main modelling choice.
6. **Map** z to a worldline:
   * `z >= -2`: `1.048596 + 0.0243*z` (saturating below 2.0 on the way up)
   * `z < -2`: crosses into the alpha field and decays toward 0 as `exp(-(|z|-2)/2.5)`
   * `z = 0` is exactly `1.048596`.

The first reading defines "normal", so a fresh install starts on the baseline. For the first 7 days the
JSON says `"calibrating": true` and the spread is inflated to damp early false alarms.

## Known limitations

* The lexicon is keyword-based: sarcasm, context ("war of words") and non-English news are weak spots.
  The LLM scorer helps but is untested here without an API key.
* Because "normal" adapts (30-day half-life), a *permanent* crisis slowly becomes the new baseline.
* Feed coverage is Western-English-centric by default. Change `FEEDS` to taste.
* RSS URLs change. Verify them; the script reports failures in the Action log.
* GitHub cron is best-effort (delays of several minutes are common) and may pause on inactive repos.
* Constants (`HL_*`, `SD_PRIOR`, `FIELD_CROSS_Z`) are reasoned guesses, not fitted. After a few weeks of
  `history.json`, tune them so the meter crosses the field edge about as often as you want it to.
