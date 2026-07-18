# Phase 2 Task 6 Report

- Added baseline comparisons for prior equal-duration day, prior-week, and calendar-month windows.
- Change rates preserve direction; unavailable inputs and zero baselines are not calculated.
- Added IQR and sample-3-sigma series anomaly evidence with an eight-sample minimum.
- Verification: `tests/test_anomaly_tool.py` (11 passed); full `pytest -q` (181 passed); `git diff --check` clean.
