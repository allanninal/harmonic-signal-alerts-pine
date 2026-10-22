# SPDX-License-Identifier: LicenseRef-PolyForm-Noncommercial-1.0.0 (see LICENSE)
"""Check pine/HarmonicSignalAlerts.pine against tests/reference.py, bar by bar, with PineTS (a local Pine v6 runtime).

    cd tests/runner && npm install && cd ../..
    python3 tests/check_pine.py <bars dir>
<bars dir> holds <SYMBOL>_<TF>.csv files with the columns time (unix ms), open, high, low, close[, volume], oldest first.

Parity: on every bar, the patterns the script completes equal the reference's: bullish and bearish pattern masks, the
bars of X, A, B, C and D (sum and sum of squares over the bar's patterns), D's price and the zone edges, for each
configuration below. A test-only block is appended to a copy of the script to plot these check values; the script
itself is not changed. Repaint: the script is re-run on the series cut at three points; every bar before a cut must
read the same as in the full run (a closed bar never changes when later bars arrive)."""
import argparse
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
from reference import Params, run  # noqa: E402

PINE = HERE.parent / "pine" / "HarmonicSignalAlerts.pine"
RUNNER = HERE / "runner" / "run_pine.mjs"
# tag: (PineTS input overrides keyed by input title, reference Params)
CONFIGS = {
    "default": ({}, Params()),
    "tight": ({"Swing: bars on the left": 5, "Swing: bars on the right": 3, "Ratio tolerance, %": 3,
               "Reversal zone half-width, % of XA": 5}, Params(left=5, right=3, tol=0.03, prz=0.05)),
}
PLOTS = ["T bull", "T bear", "T points", "T points sq", "T d price", "T zone"]
FLOAT_PLOTS = {"T d price", "T zone"}
TEST_BLOCK = """
// ---- test-only block (appended by tests/check_pine.py) ----
float _tb = 0.0
float _ts = 0.0
float _tp = 0.0
float _tq = 0.0
float _td = 0.0
float _tz = 0.0
for _e in evs
    if _e.dir > 0
        _tb += math.pow(2, _e.pat)
    else
        _ts += math.pow(2, _e.pat)
    _tp += _e.xb + _e.ab + _e.bb + _e.cb + _e.db
    _tq += _e.xb * _e.xb + _e.ab * _e.ab + _e.bb * _e.bb + _e.cb * _e.cb + _e.db * _e.db
    _td += _e.dp
    _tz += _e.nearZ + _e.farZ
plot(_tb, "T bull")
plot(_ts, "T bear")
plot(_tp, "T points")
plot(_tq, "T points sq")
plot(_td, "T d price")
plot(_tz, "T zone")
"""


def testable():
    t = tempfile.NamedTemporaryFile(suffix=".pine", delete=False, mode="w", encoding="utf-8")
    t.write(PINE.read_text(encoding="utf-8") + TEST_BLOCK)
    t.close()
    return Path(t.name)


def pine_run(pine, bars_csv, inputs):
    with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as t:
        out = t.name
    cmd = ["node", str(RUNNER), str(pine), str(bars_csv), out]
    for k, v in inputs.items():
        cmd += ["--input", f"{k}={str(v).lower() if isinstance(v, bool) else v}"]
    r = subprocess.run(cmd + PLOTS, capture_output=True, text=True)
    if r.returncode:
        sys.exit(f"PineTS failed on {bars_csv}:\n{r.stderr[-3000:]}")
    d = pd.read_csv(out)
    os.unlink(out)
    return {p: np.nan_to_num(d[p].to_numpy(float), nan=0.0) for p in PLOTS}


def expected(b, pr):
    events = run(*(b[k].to_numpy(float) for k in ("high", "low", "close")), pr)
    e = {p: np.zeros(len(b)) for p in PLOTS}
    for ev in events:
        t = ev["bar"]
        e["T bull" if ev["dir"] > 0 else "T bear"][t] += 2 ** ev["pat"]
        pts = [ev["x"][0] if ev["x"][0] is not None else -1, ev["a"][0], ev["b"][0], ev["c"][0], ev["d"][0]]
        e["T points"][t] += sum(pts)
        e["T points sq"][t] += sum(x * x for x in pts)
        e["T d price"][t] += ev["d"][1]
        e["T zone"][t] += ev["near"] + ev["far"]
    return e, len(events)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("bars")
    a = ap.parse_args()
    series = sorted(Path(a.bars).glob("*.csv"))
    pine = testable()
    ok = True
    for tag, (inputs, pr) in CONFIGS.items():
        n_ev = bad = 0
        for f in series:
            b = pd.read_csv(f)
            got = pine_run(pine, f, inputs)
            exp, k = expected(b, pr)
            n_ev += k
            for p in PLOTS:
                tol = 1e-9 * np.maximum(1.0, np.abs(exp[p])) if p in FLOAT_PLOTS else 0.0
                miss = np.where(np.abs(got[p] - exp[p]) > tol)[0]
                bad += len(miss)
                for i in miss[:3]:
                    print(f"  {tag} {f.stem} {p} bar {i}: pine {got[p][i]} reference {exp[p][i]}")
        print(f"parity {tag}: {len(series)} series, {n_ev} patterns, {bad} mismatches")
        ok &= bad == 0
    changed = checked = 0
    for f in series:
        b = pd.read_csv(f)
        full = pine_run(pine, f, {})
        n = len(b)
        for cut in (n // 2, n - 300, n - 1):
            with tempfile.NamedTemporaryFile(suffix=".csv", delete=False, mode="w") as t:
                b.iloc[:cut].to_csv(t, index=False)
            part = pine_run(pine, t.name, {})
            os.unlink(t.name)
            for p in PLOTS:
                checked += cut
                changed += int((part[p][:cut] != full[p][:cut]).sum())
    print(f"repaint: {checked} bar values re-read after cuts, {changed} changed")
    ok &= changed == 0
    os.unlink(pine)
    print("ALL PASS" if ok else "FAIL")
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
