# SPDX-License-Identifier: LicenseRef-PolyForm-Noncommercial-1.0.0 (see LICENSE)
"""Python twin of Harm.mqh: the same swings, pattern ratios and PRZ completion rule, step for step, so the indicators'
output can be compared bar by bar (tests/check_parity.py). The rules are described in the README.

    from reference import Params, run
    events = run(high, low, close, Params())
"""
from dataclasses import dataclass

ABCD, GARTLEY, BAT = range(3)
NAMES = ["ABCD", "Gartley", "Bat"]
# b_lo, b_hi (AB/XA), c_lo, c_hi (BC/AB), d (key ratio), p_lo, p_hi (CD/BC at the key level, 0 = no check)
RATIOS = [
    (0, 0, 0.382, 0.886, 1.0, 0, 0),
    (0.618, 0.618, 0.382, 0.886, 0.786, 1.13, 1.618),
    (0.382, 0.50, 0.382, 0.886, 0.886, 1.618, 2.618),
]


@dataclass
class Params:
    left: int = 10
    right: int = 5
    tol: float = 0.05
    prz: float = 0.03
    use: tuple = (True, True, True)


def inside(v, lo, hi, tol):
    return lo * (1 - tol) <= v <= hi * (1 + tol)


def match(sw, pr):
    """Patterns completed by the last swing (C) of `sw` [(type, price, bar)]: list of candidate dicts."""
    out = []
    if len(sw) < 3:
        return out
    ct, cp, cb = sw[-1]
    bt, bp, bb = sw[-2]
    at, ap, ab = sw[-3]
    bull = ct == 1                       # C is a high: D below it
    s = 1.0 if bull else -1.0
    AB = abs(ap - bp)
    BC = abs(cp - bp)
    if AB <= 0 or BC <= 0:
        return out
    for pat in range(len(NAMES)):
        if not pr.use[pat]:
            continue
        b_lo, b_hi, c_lo, c_hi, d, p_lo, p_hi = RATIOS[pat]
        if pat == ABCD:
            if not inside(BC / AB, c_lo, c_hi, pr.tol):
                continue
            key = cp - s * AB
            scale = AB
            xp, xb = None, None
        else:
            if len(sw) < 4:
                continue
            xt, xp, xb = sw[-4]
            XA = abs(ap - xp)
            if XA <= 0 or not inside(AB / XA, b_lo, b_hi, pr.tol):
                continue
            if not inside(BC / AB, c_lo, c_hi, pr.tol):
                continue
            key = ap - s * d * XA
            if p_lo > 0 and not inside(abs(cp - key) / BC, p_lo, p_hi, pr.tol):
                continue
            scale = XA
        if s * (cp - key) <= 0:
            continue
        out.append(dict(pat=pat, dir=1 if bull else -1,
                        near=key + s * pr.prz * scale, far=key - s * pr.prz * scale,
                        x=(xb, xp), a=(ab, ap), b=(bb, bp), c=(cb, cp), ext=None, ext_bar=-1, worst=None))
    return out


def run(high, low, close, pr: Params = Params()):
    """events: list of dicts in firing order; each has the bar it fired on, the points and the PRZ."""
    n = len(high)
    sw = []                               # (type 1 high / -1 low, price, bar)
    cands = []
    events = []
    for t in range(n):
        h, l, c = high[t], low[t], close[t]
        # 1) live candidates take this bar
        alive = []
        for cd in cands:
            if step(cd, t, h, l, c, events):
                alive.append(cd)
        cands = alive
        # 2) pivot confirmed at p = t - right
        p = t - pr.right
        if p - pr.left < 0:
            continue
        is_h = all(high[p] > high[p - j] for j in range(1, pr.left + 1)) and \
            all(high[p] >= high[p + j] for j in range(1, pr.right + 1))
        is_l = all(low[p] < low[p - j] for j in range(1, pr.left + 1)) and \
            all(low[p] <= low[p + j] for j in range(1, pr.right + 1))
        if is_h and is_l:
            if not sw:
                continue
            is_h, is_l = sw[-1][0] == -1, sw[-1][0] == 1
        changed = False
        for typ, ok, px in ((1, is_h, high[p]), (-1, is_l, low[p])):
            if not ok:
                continue
            if sw and sw[-1][0] == typ:
                if (px > sw[-1][1]) if typ == 1 else (px < sw[-1][1]):
                    sw[-1] = (typ, px, p)
                    changed = True
            elif sw and ((typ == -1 and px >= sw[-1][1]) or (typ == 1 and px <= sw[-1][1])):
                pass                                     # on the wrong side of the last swing
            else:
                sw.append((typ, px, p))
                if len(sw) > 8:
                    sw.pop(0)
                changed = True
        if not changed:
            continue
        cands = match(sw, pr)
        # 3) new candidates catch up on the bars after C (C's pivot guarantees none of them is beyond C)
        alive = []
        for cd in cands:
            ok = True
            for j in range(cd["c"][0] + 1, t + 1):
                if not step(cd, j, high[j], low[j], close[j], events, fire_at=t):
                    ok = False
                    break
            if ok:
                alive.append(cd)
        cands = alive
    return events


def step(cd, j, h, l, c, events, fire_at=None):
    """Feed bar j to a candidate. False when it is finished (dead, void or fired). `fire_at` = the bar an event is
    dated on during the catch-up (the confirmation bar, never earlier)."""
    s = cd["dir"]
    if (h > cd["c"][1]) if s > 0 else (l < cd["c"][1]):
        return False                                     # beyond C: C moves, the candidate dies
    ext = l if s > 0 else h
    if cd["ext"] is None or ((ext < cd["ext"]) if s > 0 else (ext > cd["ext"])):
        cd["ext"], cd["ext_bar"] = ext, j
    if cd["worst"] is None or ((c < cd["worst"]) if s > 0 else (c > cd["worst"])):
        cd["worst"] = c
    if (cd["ext"] <= cd["near"]) if s > 0 else (cd["ext"] >= cd["near"]):
        if (cd["worst"] < cd["far"]) if s > 0 else (cd["worst"] > cd["far"]):
            return False                                 # closed beyond the zone: void
        bar = j if fire_at is None else fire_at
        events.append(dict(bar=bar, dir=s, pat=cd["pat"], name=NAMES[cd["pat"]], x=cd["x"], a=cd["a"], b=cd["b"],
                           c=cd["c"], d=(cd["ext_bar"], cd["ext"]), near=cd["near"], far=cd["far"]))
        return False
    return True
