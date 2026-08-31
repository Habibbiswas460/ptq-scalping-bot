# MFE / MAE FORENSICS

Date: 2026-08-16

## Findings:
- MFE and MAE are successfully committing to the SQLite database (2026-08-12: MFE 934.05 / MAE -2871.7; 2026-08-14: MFE 151.45 / 1889.55).
- However, for hold times of 4 seconds and 42 seconds respectively (65 qty options), the captured negative and positive absolute numbers (exceeding thousands of INR) are mathematically impossible.
- Inference: The underlying payload passed from `state_machine.py` to `compute_excursion` likely passes the *entire recent tick buffer* (including pre-trade ticks), triggering massive baseline distortions relative to the instantaneous entry price.

## Evidence Strength: WEAK
The forensic insight suggests a structural bug in how excursions capture their tick array. Direct exit-timing behavior cannot currently be optimized against these metrics.
