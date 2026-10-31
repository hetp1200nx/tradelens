"""Trade charges for Indian markets (NSE). Rates change: check your broker's rate card and edit RATES.
STT on F&O reflects the Budget 2026 increase effective 1 April 2026 (futures 0.05%, options 0.15% of premium, on sell side).
"""

RATES = {
    "delivery": {"brokerage_pct": 0.001, "brokerage_cap": 20.0, "brokerage_min": 5.0,
                 "stt_buy": 0.001, "stt_sell": 0.001, "exch": 0.0000297, "stamp_buy": 0.00015,
                 "dp_sell": 20.0},
    "intraday": {"brokerage_pct": 0.0025, "brokerage_cap": 20.0, "brokerage_min": 0.0,
                 "stt_buy": 0.0, "stt_sell": 0.00025, "exch": 0.0000297, "stamp_buy": 0.00003,
                 "dp_sell": 0.0},
    "futures": {"brokerage_pct": 1.0, "brokerage_cap": 20.0, "brokerage_min": 0.0,
                "stt_buy": 0.0, "stt_sell": 0.0005, "exch": 0.0000173, "stamp_buy": 0.00002,
                "dp_sell": 0.0},
    "option": {"brokerage_pct": 1.0, "brokerage_cap": 20.0, "brokerage_min": 0.0,
               "stt_buy": 0.0, "stt_sell": 0.0015, "exch": 0.0003503, "stamp_buy": 0.00003,
               "dp_sell": 0.0},
}
SEBI_FEE = 0.000001   # Rs 10 per crore
GST = 0.18


def _brokerage(r, value):
    b = min(r["brokerage_cap"], value * r["brokerage_pct"])
    return max(b, r["brokerage_min"]) if value > 0 else 0.0


def charges(segment: str, buy_value: float, sell_value: float) -> dict:
    """buy_value/sell_value = price x quantity (for options: premium x quantity)."""
    r = RATES.get(segment, RATES["intraday"])
    brokerage = _brokerage(r, buy_value) + _brokerage(r, sell_value)
    stt = buy_value * r["stt_buy"] + sell_value * r["stt_sell"]
    turnover = buy_value + sell_value
    exch = turnover * r["exch"]
    sebi = turnover * SEBI_FEE
    stamp = buy_value * r["stamp_buy"]
    dp = r["dp_sell"] * (1 + GST) if sell_value > 0 else 0.0
    gst = (brokerage + exch + sebi) * GST
    total = brokerage + stt + exch + sebi + stamp + gst + dp
    return {k: round(v, 2) for k, v in {
        "brokerage": brokerage, "stt": stt, "exchange": exch, "sebi": sebi,
        "stamp": stamp, "gst": gst, "dp": dp, "total": total}.items()}


def trade_pnl(side: str, entry: float, exit_: float, qty: float, segment: str) -> dict:
    """side BUY = bought first then sell at exit. side SELL = sold first (short) then buy back at exit."""
    if side.upper() == "BUY":
        buy_v, sell_v = entry * qty, exit_ * qty
    else:
        buy_v, sell_v = exit_ * qty, entry * qty
    gross = sell_v - buy_v
    ch = charges(segment, buy_v, sell_v)
    net = gross - ch["total"]
    return {"gross": round(gross, 2), "charges": ch, "net": round(net, 2),
            "pct_on_capital": round(net / (entry * qty) * 100, 2) if entry * qty else 0.0}


def breakeven_move(side: str, entry: float, qty: float, segment: str) -> float:
    """Price move needed just to cover charges."""
    ch = charges(segment, entry * qty, entry * qty)["total"]
    return round(ch / qty, 2) if qty else 0.0
