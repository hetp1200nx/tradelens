# TradeLens Demo

A complete copy of TradeLens that runs on a **simulated market**, for showing people how the app works.

- Every price, candle, volume and order-book number here is **simulated**. Nothing is real market data.
- Angel One and Supabase are switched off, so no broker account or database is needed (and none can be connected).
- The wallet starts at a virtual **₹1,00,000**.
- The simulated clock is held at 10:30 AM, so the market always looks "open".

**Demo login**

| | |
|---|---|
| Username | `Demo` |
| Password | `demo@123` |
| Passcode (if you tick *Remember me*) | `1234` |

Visitors can also create their own demo accounts. The shared Demo login's password and passcode can't be changed, and it resets every time the demo starts.

---

## Run the demo

You need **Python 3.10 or newer** from https://www.python.org/downloads/ (on Windows, tick **Add python.exe to PATH** while installing).

Download this repository (green **Code** button → **Download ZIP**) and extract it. Then open the **`demo`** folder inside it.

**Windows:** double-click **`start.bat`**. The first run installs everything (1–3 minutes), then your browser opens http://localhost:8000.

**Mac:** open Terminal, type `cd ` (with a space), drag the `demo` folder into the window, press Enter, then run:
```
bash start.sh
```
and open http://localhost:8000.

Sign in with **Demo / demo@123**.

To run the demo and the real app at the same time, give the demo another port: create a file called `.env` in the `demo` folder containing `PORT=8001`, then open http://localhost:8001.

**Show it on other devices:** on the same Wi-Fi, open `http://<this-computer's-IP>:8000` on a phone (find the IP with `ipconfig` on Windows, or *System Settings → Wi-Fi → Details* on Mac).

---

## What to try

1. **Boards:** Sensex, Nifty 50 and the Volatile Watchlist, in List or Grid view.
2. **Wide Flow / Market Flow:** sectors, every share's move flowing into the bullish/bearish split, and the tiered tile wall.
3. **Tap any share:** live chart with order blocks and liquidity, Buy / Sell / Wait / Avoid suggestion with entry, stop-loss and targets, P&L after charges, and a backtest.
4. **Trade Planner:** trade ideas sized to the ₹1,00,000 virtual wallet, with expected P&L.
5. **My Trades:** add a trade and watch the live P&L and exit alerts.
6. **Angel Account:** a sample portfolio, positions and orders.

The real app (one folder up) connects to Angel One for live prices. See the main README.
