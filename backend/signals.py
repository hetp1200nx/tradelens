"""Rule-based trade suggestions for intraday, long-term and options.
Every suggestion lists its reasons and warnings so you can see WHY. Rules, not predictions."""
from __future__ import annotations

import math

from . import analytics as A


def _r(x, nd=2):
    return None if x is None else round(x, nd)


def _warn(lst, level, text):
    lst.append({"level": level, "text": text})


def _targets(entry, risk, levels, direction):
    """Pick T1/T2 from real levels (liquidity, prior highs/lows); fall back to 1.5R / 2.5R.
    Returns (t1, t2, obstacle) where obstacle is a level that sits closer than T1."""
    if direction > 0:
        cands = sorted(x for x in levels if x > entry)
    else:
        cands = sorted((x for x in levels if x < entry), reverse=True)
    obstacle = next((x for x in cands if abs(x - entry) < 1.2 * risk), None)
    far = [x for x in cands if abs(x - entry) >= 1.2 * risk]
    t1 = far[0] if far and abs(far[0] - entry) <= 4 * risk else entry + direction * 1.5 * risk
    rest = [x for x in far if abs(x - entry) >= abs(t1 - entry) + 0.5 * risk]
    t2 = rest[0] if rest and abs(rest[0] - entry) <= 6 * risk else entry + direction * max(2.5 * risk, abs(t1 - entry) + risk)
    return t1, t2, obstacle


def _finish(sig, direction, entry, sl, t1, t2, in_zone, hard_ok_text):
    risk = abs(entry - sl) or 1e-9
    rr1 = abs(t1 - entry) / risk
    rr2 = abs(t2 - entry) / risk
    sig.update({"entry": _r(entry), "sl": _r(sl), "t1": _r(t1), "t2": _r(t2),
                "rr1": _r(rr1, 2), "rr2": _r(rr2, 2), "risk_per_share": _r(risk)})
    if rr1 < 1.2:
        _warn(sig["warnings"], "hard", f"Reward too small: target 1 is only {rr1:.1f}x the risk")
    hard = [w for w in sig["warnings"] if w["level"] == "hard"]
    side = "BUY" if direction > 0 else "SELL"
    if hard:
        sig["action"] = "AVOID"
        sig["summary"] = f"{side} setup exists but not now: {hard[0]['text'].lower()}."
    elif in_zone:
        sig["action"] = side
        sig["summary"] = hard_ok_text
    else:
        sig["action"] = "WAIT"
        lo, hi = sig["zone"]
        sig["summary"] = (f"{'Bullish' if direction > 0 else 'Bearish'} bias. Wait for price to come to "
                          f"{lo:.2f} – {hi:.2f} before {'buying' if direction > 0 else 'selling'}. Don't chase.")
    soft = len([w for w in sig["warnings"] if w["level"] == "soft"])
    sig["confidence"] = int(max(5, min(95, sig.get("confidence", 50) - 12 * len(hard) - 6 * soft)))
    return sig


# ---------------------------------------------------------------- INTRADAY
def intraday(st, now: int) -> dict:
    sig = {"style": "intraday", "action": "WAIT", "reasons": [], "warnings": [], "zone": None,
           "timeframe": "5m"}
    c5 = A.resample(st.m1, 5)
    if len(c5) < 30 or st.ltp <= 0:
        sig["summary"] = "Collecting data: need about 30 five-minute candles before giving a signal."
        _warn(sig["warnings"], "hard", "Not enough intraday data yet")
        sig["action"] = "AVOID"
        return sig
    price = st.ltp
    m = st.metrics or {}
    a5 = A.atr(c5[-60:], 14) or price * 0.003
    closes = [c["c"] for c in c5]
    e20, e50 = A.ema(closes, 20)[-1], A.ema(closes, 50)[-1]
    today = st.today_candles(now)
    vw = A.vwap(today) or st.avg_price or e20  # indices have no volume: use EMA 20 instead of VWAP
    sod = A.ist_seconds_of_day(now)
    recent = c5[-225:]
    obs = A.order_blocks(recent)
    liq = A.liquidity_levels(recent)
    pdh = st.daily[-1]["h"] if st.daily else None
    pdl = st.daily[-1]["l"] if st.daily else None

    bull = bear = 0.0
    if price > vw:
        bull += 1
    else:
        bear += 1
    if e20 > e50:
        bull += 1
    else:
        bear += 1
    if m.get("direction", 0) > 0: bull += 1
    elif m.get("direction", 0) < 0: bear += 1
    p = m.get("pressure", 0)
    if p > 0.1: bull += 0.5
    elif p < -0.1: bear += 0.5
    oi = m.get("oi_signal", "")
    if oi in ("Long build-up", "Short covering"): bull += 0.5
    elif oi in ("Short build-up", "Long unwinding"): bear += 0.5
    sig["reasons"] = []
    sig["levels"] = {"vwap": _r(vw), "ema20": _r(e20), "ema50": _r(e50), "pdh": _r(pdh), "pdl": _r(pdl),
                     "day_high": st.high, "day_low": st.low,
                     "order_blocks": [{"type": o["type"], "top": _r(o["top"]), "bottom": _r(o["bottom"]), "t": o["t"]} for o in obs],
                     "buy_side_liquidity": [_r(x["price"]) for x in liq["buy_side"] if x["price"] > price][:4],
                     "sell_side_liquidity": [_r(x["price"]) for x in sorted(liq["sell_side"], key=lambda x: -x["price"]) if x["price"] < price][:4]}

    # ---- timing & market-condition warnings
    W = sig["warnings"]
    if sod < A.SESSION_OPEN + 15 * 60:
        _warn(W, "hard", "First 15 minutes of the session: price discovery, avoid fresh entries")
    if sod >= 15 * 3600:
        _warn(W, "hard", "After 3:00 PM: too late for a new intraday trade")
    elif sod >= 14 * 3600 + 30 * 60:
        _warn(W, "soft", "After 2:30 PM: limited time left for targets")
    if sod > A.SESSION_CLOSE or sod < A.SESSION_OPEN:
        _warn(W, "hard", "Market is closed")
    if m.get("choppy"):
        _warn(W, "hard", "Choppy price action: no clean trend today")
    if m.get("vol_ratio", 1) < 0.7:
        _warn(W, "soft", f"Low volume ({m.get('vol_ratio', 0):.1f}x normal): moves may not follow through")

    direction = 0
    if bull >= 2.5 and bull > bear + 0.5:
        direction = 1
    elif bear >= 2.5 and bear > bull + 0.5:
        direction = -1
    if direction == 0:
        sig["action"] = "AVOID" if m.get("choppy") else "WAIT"
        sig["summary"] = "No clear direction: buyers and sellers are balanced. Stay out until a side takes control."
        sig["confidence"] = 20
        return sig

    R = sig["reasons"]
    if direction > 0:
        if price > vw: R.append(f"Price above VWAP ({vw:.2f})")
        if e20 > e50: R.append("5-min trend up (EMA 20 above EMA 50)")
        if p > 0.1: R.append(f"Buyers dominate order book ({p * 100:.0f}% more buy quantity)")
        if oi in ("Long build-up", "Short covering"): R.append(f"OI: {oi}")
        if m.get("vol_ratio", 0) >= 1.5: R.append(f"Volume {m['vol_ratio']:.1f}x normal")
    else:
        if price < vw: R.append(f"Price below VWAP ({vw:.2f})")
        if e20 < e50: R.append("5-min trend down (EMA 20 below EMA 50)")
        if p < -0.1: R.append(f"Sellers dominate order book ({-p * 100:.0f}% more sell quantity)")
        if oi in ("Short build-up", "Long unwinding"): R.append(f"OI: {oi}")
        if m.get("vol_ratio", 0) >= 1.5: R.append(f"Volume {m['vol_ratio']:.1f}x normal")

    # ---- entry zone: nearest fresh order block on our side, else VWAP
    if direction > 0:
        cands = [o for o in obs if o["type"] == "bull" and o["top"] <= price + 0.3 * a5 and o["bottom"] >= price - 3.5 * a5]
        ob = max(cands, key=lambda o: o["top"]) if cands else None
    else:
        cands = [o for o in obs if o["type"] == "bear" and o["bottom"] >= price - 0.3 * a5 and o["top"] <= price + 3.5 * a5]
        ob = min(cands, key=lambda o: o["bottom"]) if cands else None
    if ob:
        lo, hi = ob["bottom"], ob["top"]
        R.append(f"{'Bullish' if direction > 0 else 'Bearish'} order block at {lo:.2f} – {hi:.2f}")
    else:
        lo, hi = vw - 0.2 * a5, vw + 0.2 * a5
        R.append("No fresh order block nearby: using VWAP as the entry zone")
    sig["zone"] = [_r(lo), _r(hi)]
    if direction > 0:
        in_zone = lo - 0.1 * a5 <= price <= hi + 0.25 * a5
        entry = min(price, hi) if in_zone else hi
        sl = lo - 0.25 * a5
        if price - vw > 2.2 * a5:
            _warn(W, "soft", "Price stretched far above VWAP: chasing risk, wait for pullback")
        if p < -0.25:
            _warn(W, "soft", "Sellers currently heavier in the order book")
        if st.uc and (st.uc - price) / price < 0.01:
            _warn(W, "hard", "Near upper circuit")
        levels = [x["price"] for x in liq["buy_side"]] + [o["bottom"] for o in obs if o["type"] == "bear"]
        if pdh: levels.append(pdh)
        if st.high > price: levels.append(st.high)
    else:
        in_zone = lo - 0.25 * a5 <= price <= hi + 0.1 * a5
        entry = max(price, lo) if in_zone else lo
        sl = hi + 0.25 * a5
        if vw - price > 2.2 * a5:
            _warn(W, "soft", "Price stretched far below VWAP: chasing risk, wait for pullback")
        if p > 0.25:
            _warn(W, "soft", "Buyers currently heavier in the order book")
        if st.lc and (price - st.lc) / price < 0.01:
            _warn(W, "hard", "Near lower circuit")
        levels = [x["price"] for x in liq["sell_side"]] + [o["top"] for o in obs if o["type"] == "bull"]
        if pdl: levels.append(pdl)
        if 0 < st.low < price: levels.append(st.low)
    risk = max(abs(entry - sl), price * 0.0015)
    sl = entry - direction * risk
    t1, t2, obst = _targets(entry, risk, levels, direction)
    if obst is not None:
        _warn(W, "soft", f"{'Resistance' if direction > 0 else 'Support'} at {obst:.2f} is close: the move may stall there")
    if abs(m.get("chg", 0)) / (m.get("atr_pct") or 1.5) > 2.5:
        _warn(W, "soft", "Stock already moved more than 2.5x its normal daily range")
    sig["confidence"] = 45 + max(bull, bear) * 8 + (m.get("strength", 0) / 6)
    ok = (f"{'BUY' if direction > 0 else 'SELL'} now: price is in the entry zone with "
          f"{'buyers' if direction > 0 else 'sellers'} in control.")
    return _finish(sig, direction, entry, sl, t1, t2, in_zone, ok)


# ---------------------------------------------------------------- LONG TERM
def long_term(st, now: int) -> dict:
    sig = {"style": "long", "action": "WAIT", "reasons": [], "warnings": [], "zone": None, "timeframe": "1D"}
    d = list(st.daily)
    if st.ltp > 0:
        d.append({"t": now, "o": st.open or st.ltp, "h": st.high or st.ltp, "l": st.low or st.ltp, "c": st.ltp, "v": st.volume})
    if len(d) < 60:
        sig["action"] = "AVOID"
        sig["summary"] = "Not enough daily history (need 60+ days)."
        return sig
    price = st.ltp
    closes = [c["c"] for c in d]
    e50 = A.ema(closes, 50)[-1]
    e200 = A.ema(closes, 200)[-1] if len(closes) >= 200 else A.ema(closes, len(closes))[-1]
    r = A.rsi(closes[-120:], 14) or 50
    ad = A.atr(d[-60:], 14) or price * 0.02
    obs = A.order_blocks(d[-250:], 4)
    liq = A.liquidity_levels(d[-250:])
    hi52 = max(c["h"] for c in d[-250:])
    lo52 = min(c["l"] for c in d[-250:])
    sig["levels"] = {"ema50": _r(e50), "ema200": _r(e200), "rsi": _r(r, 1), "high_52w": _r(hi52), "low_52w": _r(lo52),
                     "order_blocks": [{"type": o["type"], "top": _r(o["top"]), "bottom": _r(o["bottom"]), "t": o["t"]} for o in obs]}
    W, R = sig["warnings"], sig["reasons"]
    up = price > e50 > e200 or (price > e200 and e50 > e200)
    down = price < e50 < e200 or (price < e200 and e50 < e200)
    if up:
        direction = 1
        R.append("Uptrend: price above 50-DMA and 200-DMA")
    elif down:
        direction = -1
        R.append("Downtrend: price below 50-DMA and 200-DMA")
    else:
        sig["summary"] = "Mixed trend (price between the 50 and 200-day averages). Wait for a clear trend."
        sig["confidence"] = 25
        return sig
    if direction > 0:
        cands = [o for o in obs if o["type"] == "bull" and o["top"] <= price * 1.01 and o["bottom"] >= price - 4 * ad]
        ob = max(cands, key=lambda o: o["top"]) if cands else None
        if ob:
            lo, hi = ob["bottom"], ob["top"]
            R.append(f"Daily bullish order block at {lo:.2f} – {hi:.2f}")
        else:
            lo, hi = e50 - 0.3 * ad, e50 + 0.3 * ad
            R.append(f"Using the 50-day average ({e50:.2f}) as the buy zone")
        in_zone = lo - 0.2 * ad <= price <= hi + 0.4 * ad
        entry = min(price, hi) if in_zone else hi
        sl = min(lo - 0.5 * ad, entry - 1.5 * ad)
        if r > 75: _warn(W, "soft", f"RSI {r:.0f}: overbought, better entries usually come on dips")
        if (price - e50) / e50 > 0.15: _warn(W, "soft", "Price is more than 15% above the 50-day average: stretched")
        levels = [x["price"] for x in liq["buy_side"]] + [hi52]
        ok = "BUY for long term: price is at a strong support zone in an uptrend."
    else:
        _warn(W, "soft", "For long term, SELL means exit or avoid holding (not short-selling)")
        cands = [o for o in obs if o["type"] == "bear" and o["bottom"] >= price * 0.99 and o["top"] <= price + 4 * ad]
        ob = min(cands, key=lambda o: o["bottom"]) if cands else None
        if ob:
            lo, hi = ob["bottom"], ob["top"]
            R.append(f"Daily bearish order block at {lo:.2f} – {hi:.2f}")
        else:
            lo, hi = e50 - 0.3 * ad, e50 + 0.3 * ad
            R.append(f"Using the 50-day average ({e50:.2f}) as resistance")
        in_zone = lo - 0.4 * ad <= price <= hi + 0.2 * ad
        entry = max(price, lo) if in_zone else lo
        sl = max(hi + 0.5 * ad, entry + 1.5 * ad)
        if r < 25: _warn(W, "soft", f"RSI {r:.0f}: oversold, bounces are likely")
        levels = [x["price"] for x in liq["sell_side"]] + [lo52]
        ok = "SELL / EXIT holdings: price is at resistance in a downtrend."
    sig["zone"] = [_r(lo), _r(hi)]
    risk = abs(entry - sl)
    t1, t2, obst = _targets(entry, risk, levels, direction)
    if obst is not None:
        _warn(W, "soft", f"{'Resistance' if direction > 0 else 'Support'} at {obst:.2f} is close")
    sig["confidence"] = 55 + (10 if ob else 0)
    return _finish(sig, direction, entry, sl, t1, t2, in_zone, ok)


# ---------------------------------------------------------------- OPTIONS
def _guess_step(price):
    for lim, step in ((100, 1), (250, 2.5), (500, 5), (1000, 10), (2500, 20), (5000, 50), (15000, 100)):
        if price < lim:
            return step
    return 250


def option(st, now: int, base: dict, quote_fn=None) -> dict:
    sig = {"style": "option", "action": base["action"], "reasons": list(base.get("reasons", [])),
           "warnings": list(base.get("warnings", [])), "zone": base.get("zone"), "timeframe": "5m",
           "underlying": {k: base.get(k) for k in ("entry", "sl", "t1", "t2", "rr1", "rr2")},
           "levels": base.get("levels")}
    if not st.is_fno and not st.is_index:
        sig["action"] = "AVOID"
        sig["summary"] = "This stock has no options (not in F&O)."
        return sig
    if base["action"] not in ("BUY", "SELL", "WAIT") or base.get("entry") is None:
        sig["action"] = "AVOID" if base["action"] == "AVOID" else "WAIT"
        sig["summary"] = "No option trade: the stock itself has no clean setup. " + base.get("summary", "")
        return sig
    direction = 1 if (base["t1"] or 0) > (base["entry"] or 0) else -1
    typ = "CE" if direction > 0 else "PE"
    price = st.ltp
    step = st.strike_step or _guess_step(price)
    atm = round(price / step) * step
    itm = atm - step if typ == "CE" else atm + step
    delta = 0.6
    W = sig["warnings"]
    sod = A.ist_seconds_of_day(now)
    q = quote_fn(st, itm, typ) if quote_fn else None
    estimated = False
    if q and q.get("ltp"):
        prem = q["ltp"]
        lot = q.get("lot") or st.lot
        name = q.get("symbol")
        expiry = q.get("expiry")
        days = q.get("days_to_expiry")
    else:
        # rough estimate when the live option price isn't available (demo mode / lookup failed)
        sigma_d = (st.atr_pct or 1.5) / 100 * 0.8
        days = 4 if st.is_index else 10  # index options expire weekly
        intrinsic = max(0.0, price - itm) if typ == "CE" else max(0.0, itm - price)
        prem = intrinsic + 0.4 * price * sigma_d * math.sqrt(days)
        lot = st.lot or 1
        name = f"{st.sym} {itm:g} {typ}"
        expiry = None
        estimated = True
        _warn(W, "soft", "Option price is an ESTIMATE (live option quote not available)")
    u_entry, u_sl, u_t1, u_t2 = base["entry"], base["sl"], base["t1"], base["t2"]
    p_entry = prem + delta * (u_entry - price) * direction
    p_sl = max(0.05, p_entry - delta * abs(u_entry - u_sl))
    p_t1 = p_entry + delta * abs(u_t1 - u_entry)
    p_t2 = p_entry + delta * abs(u_t2 - u_entry)
    if sod >= 14 * 3600:
        _warn(W, "soft", "After 2 PM option buyers lose more to time decay")
    if days is not None and days <= 0 and sod >= 13 * 3600 + 30 * 60:
        _warn(W, "hard", "Expiry day afternoon: premiums decay very fast")
    elif days is not None and days <= 2:
        _warn(W, "soft", f"Only {days} day(s) to expiry: fast time decay")
    sig["reasons"].append(f"Buy {typ} because the stock signal is {'bullish' if direction > 0 else 'bearish'}")
    sig["reasons"].append(f"1 strike in-the-money ({itm:g}) for better delta and less decay than out-of-the-money")
    hard = [w for w in W if w["level"] == "hard"]
    if hard:
        sig["action"] = "AVOID"
    elif base["action"] in ("BUY", "SELL"):
        sig["action"] = f"BUY {typ}"
    else:
        sig["action"] = "WAIT"
    sig["option"] = {"symbol": name, "type": typ, "strike": itm, "atm": atm, "step": step, "lot": lot,
                     "expiry": expiry, "estimated": estimated, "premium_now": _r(prem),
                     "entry": _r(p_entry), "sl": _r(p_sl), "t1": _r(p_t1), "t2": _r(p_t2),
                     "per_lot": {"risk": _r((p_entry - p_sl) * lot), "reward_t1": _r((p_t1 - p_entry) * lot),
                                 "reward_t2": _r((p_t2 - p_entry) * lot)}}
    if sig["action"].startswith("BUY"):
        sig["summary"] = (f"Buy {name} near {p_entry:.2f} when the stock is at {u_entry:.2f}. "
                          f"Exit if the stock breaks {u_sl:.2f}.")
    elif sig["action"] == "WAIT":
        sig["summary"] = f"Wait: buy {typ} only when the stock reaches the zone {base['zone'][0]} – {base['zone'][1]}."
    else:
        sig["summary"] = "Avoid options right now: " + (hard[0]["text"].lower() if hard else "no clean setup") + "."
    sig["confidence"] = base.get("confidence", 40)
    return sig


def all_signals(st, now, quote_fn=None) -> dict:
    i = intraday(st, now)
    return {"intraday": i, "long": long_term(st, now), "option": option(st, now, i, quote_fn)}
