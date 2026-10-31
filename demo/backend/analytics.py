"""Pure calculation functions: indicators, order blocks, liquidity, support/resistance.
Candles are dicts: {"t": epoch seconds, "o", "h", "l", "c", "v"}.
"""
from __future__ import annotations

IST = 19800  # +05:30 in seconds
SESSION_OPEN = 9 * 3600 + 15 * 60
SESSION_CLOSE = 15 * 3600 + 30 * 60


def ist_day_start(t: int) -> int:
    return (t + IST) // 86400 * 86400 - IST


def ist_seconds_of_day(t: int) -> int:
    return (t + IST) % 86400


# ---------- basic indicators ----------
def ema(values: list[float], n: int) -> list[float]:
    if not values:
        return []
    k = 2 / (n + 1)
    out, e = [], values[0]
    for v in values:
        e = v * k + e * (1 - k)
        out.append(e)
    return out


def sma(values: list[float], n: int) -> float | None:
    if len(values) < n:
        return None
    return sum(values[-n:]) / n


def atr(candles: list[dict], n: int = 14) -> float:
    if len(candles) < 2:
        return (candles[0]["h"] - candles[0]["l"]) if candles else 0.0
    trs = []
    for i in range(1, len(candles)):
        c, p = candles[i], candles[i - 1]
        trs.append(max(c["h"] - c["l"], abs(c["h"] - p["c"]), abs(c["l"] - p["c"])))
    trs = trs[-n * 3:]
    # Wilder smoothing
    a = sum(trs[:n]) / min(n, len(trs))
    for tr in trs[n:]:
        a = (a * (n - 1) + tr) / n
    return a


def rsi(closes: list[float], n: int = 14) -> float | None:
    if len(closes) < n + 1:
        return None
    gains = losses = 0.0
    for i in range(1, n + 1):
        d = closes[i] - closes[i - 1]
        gains += max(d, 0)
        losses += max(-d, 0)
    ag, al = gains / n, losses / n
    for i in range(n + 1, len(closes)):
        d = closes[i] - closes[i - 1]
        ag = (ag * (n - 1) + max(d, 0)) / n
        al = (al * (n - 1) + max(-d, 0)) / n
    if al == 0:
        return 100.0
    return 100 - 100 / (1 + ag / al)


def vwap(candles_today: list[dict]) -> float | None:
    pv = vol = 0.0
    for c in candles_today:
        tp = (c["h"] + c["l"] + c["c"]) / 3
        pv += tp * c["v"]
        vol += c["v"]
    return pv / vol if vol else None


def resample(candles_1m: list[dict], minutes: int) -> list[dict]:
    """Group 1-minute candles into N-minute candles aligned to the 09:15 session open."""
    if minutes <= 1:
        return list(candles_1m)
    size = minutes * 60
    out: list[dict] = []
    cur_key = None
    for c in candles_1m:
        day = ist_day_start(c["t"])
        open_t = day + SESSION_OPEN
        key = open_t + max(0, (c["t"] - open_t)) // size * size
        if key != cur_key:
            out.append({"t": key, "o": c["o"], "h": c["h"], "l": c["l"], "c": c["c"], "v": c["v"]})
            cur_key = key
        else:
            b = out[-1]
            b["h"] = max(b["h"], c["h"])
            b["l"] = min(b["l"], c["l"])
            b["c"] = c["c"]
            b["v"] += c["v"]
    return out


def resample_weekly(daily: list[dict]) -> list[dict]:
    out: list[dict] = []
    cur = None
    for c in daily:
        d = (c["t"] + IST) // 86400
        week = (d + 3) // 7  # epoch day 0 was a Thursday; this groups Monday..Sunday
        if week != cur:
            out.append(dict(c))
            cur = week
        else:
            b = out[-1]
            b["h"] = max(b["h"], c["h"])
            b["l"] = min(b["l"], c["l"])
            b["c"] = c["c"]
            b["v"] += c["v"]
    return out


# ---------- structure ----------
def swings(candles: list[dict], left: int = 3, right: int = 3) -> list[dict]:
    out = []
    for i in range(left, len(candles) - right):
        h, l = candles[i]["h"], candles[i]["l"]
        win = candles[i - left:i + right + 1]
        if h == max(c["h"] for c in win):
            out.append({"i": i, "t": candles[i]["t"], "price": h, "kind": "high"})
        if l == min(c["l"] for c in win):
            out.append({"i": i, "t": candles[i]["t"], "price": l, "kind": "low"})
    return out


def order_blocks(candles: list[dict], max_each: int = 3) -> list[dict]:
    """Bullish OB = last down candle before a strong up move that leaves an imbalance (FVG)
    or closes well beyond it. Bearish OB is the mirror. Blocks broken by a close beyond them are dropped."""
    n = len(candles)
    if n < 10:
        return []
    ranges = [c["h"] - c["l"] for c in candles]
    found = []
    for i in range(1, n - 3):
        c = candles[i]
        lookback = ranges[max(0, i - 20):i] or [ranges[i]]
        avg_r = sum(lookback) / len(lookback) or 1e-9
        nxt = candles[i + 1:i + 4]
        if c["c"] < c["o"]:  # down candle -> possible bullish OB
            disp = max(x["c"] for x in nxt) - c["h"]
            fvg = any(candles[j + 1]["l"] > candles[j - 1]["h"] for j in range(i + 1, min(i + 3, n - 1)))
            if disp >= 0.8 * avg_r and (fvg or disp >= 1.5 * avg_r) and nxt[0]["c"] > nxt[0]["o"]:
                found.append({"type": "bull", "i": i, "t": c["t"], "top": c["h"], "bottom": c["l"]})
        elif c["c"] > c["o"]:  # up candle -> possible bearish OB
            disp = c["l"] - min(x["c"] for x in nxt)
            fvg = any(candles[j + 1]["h"] < candles[j - 1]["l"] for j in range(i + 1, min(i + 3, n - 1)))
            if disp >= 0.8 * avg_r and (fvg or disp >= 1.5 * avg_r) and nxt[0]["c"] < nxt[0]["o"]:
                found.append({"type": "bear", "i": i, "t": c["t"], "top": c["h"], "bottom": c["l"]})
    valid = []
    for ob in found:
        after = candles[ob["i"] + 2:]
        if ob["type"] == "bull":
            if any(x["c"] < ob["bottom"] for x in after):
                continue
            ob["tested"] = sum(1 for x in after if x["l"] <= ob["top"])
        else:
            if any(x["c"] > ob["top"] for x in after):
                continue
            ob["tested"] = sum(1 for x in after if x["h"] >= ob["bottom"])
        valid.append(ob)
    # fresher / less-tested first; drop heavily tested blocks (liquidity already used)
    valid = [v for v in valid if v["tested"] <= 3]
    bulls = sorted([v for v in valid if v["type"] == "bull"], key=lambda v: -v["i"])[:max_each]
    bears = sorted([v for v in valid if v["type"] == "bear"], key=lambda v: -v["i"])[:max_each]
    return bulls + bears


def liquidity_levels(candles: list[dict], tol_pct: float = 0.0012) -> dict:
    """Untaken swing highs (buy-side liquidity, stops of short sellers above)
    and untaken swing lows (sell-side liquidity below). Equal highs/lows are marked stronger."""
    sw = swings(candles, 3, 3)
    highs, lows = [], []
    for s in sw:
        after = candles[s["i"] + 1:]
        if s["kind"] == "high" and not any(x["h"] > s["price"] for x in after):
            highs.append(s["price"])
        if s["kind"] == "low" and not any(x["l"] < s["price"] for x in after):
            lows.append(s["price"])

    def cluster(levels):
        levels = sorted(levels)
        out = []
        for p in levels:
            if out and abs(p - out[-1]["price"]) / p <= tol_pct:
                out[-1]["count"] += 1
                out[-1]["price"] = max(out[-1]["price"], p)
            else:
                out.append({"price": p, "count": 1})
        return out

    return {"buy_side": cluster(highs), "sell_side": cluster(lows)}


def nearest_above(levels: list[float], price: float) -> float | None:
    above = [x for x in levels if x > price]
    return min(above) if above else None


def nearest_below(levels: list[float], price: float) -> float | None:
    below = [x for x in levels if x < price]
    return max(below) if below else None


def range_efficiency(candles: list[dict]) -> float:
    """Net move / total path. Near 1 = clean trend, near 0 = choppy."""
    if len(candles) < 3:
        return 0.0
    net = abs(candles[-1]["c"] - candles[0]["o"])
    path = sum(abs(c["c"] - c["o"]) + (c["h"] - c["l"]) * 0.5 for c in candles) or 1e-9
    return min(1.0, net / path * 2)
