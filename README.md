# TradeLens: your personal order-block & liquidity terminal

Live boards for **Sensex, Nifty 50 and a Volatile Watchlist** (starts with the 200 most volatile F&O stocks; add any NSE share),
live candle charts with order blocks and liquidity levels, buy / sell / wait / avoid suggestions for **intraday, long term and options**,
a profit/loss calculator with full charges, your own trade journal with live P&L and exit alerts, a backtest, a Trade Planner sized
to your balance, and a scorecard that tracks how the signals really perform.

TradeLens only **reads** market data and your account. It never places, changes or cancels orders. You trade in your own broker app as usual.

> **Disclaimer:** educational tool, not investment advice. The suggestions are rules, not predictions, and no rule wins every trade.
> Do your own research before trading. Sharing or selling signals to others needs SEBI registration.

> **Just want to see it?** The [`demo`](demo/) folder is a full copy that runs on a simulated market with a ready-made login
> (**Demo / demo@123**) and a virtual ₹1,00,000 wallet. No Angel One account needed. See [demo/README.md](demo/README.md).

---

## Contents
1. [What you need](#1-what-you-need)
2. [Run it on Windows](#2-run-it-on-windows)
3. [Run it on Mac](#3-run-it-on-mac)
4. [First sign-in and the admin account](#4-first-sign-in-and-the-admin-account)
5. [Switch to live Angel One prices (free)](#5-switch-to-live-angel-one-prices-free)
6. [Save data in Supabase (optional)](#6-save-data-in-supabase-optional)
7. [Use it on your phone / host it from your own computer](#7-use-it-on-your-phone--host-it-from-your-own-computer)
8. [What each screen does](#8-what-each-screen-does)
9. [Troubleshooting](#9-troubleshooting)
10. [Files](#10-files)

---

## 1. What you need

- A Windows 10/11 PC or a Mac (Apple Silicon or Intel)
- **Python 3.10 or newer** (3.12 recommended), free from https://www.python.org/downloads/
- Internet connection
- Optional: a free **Angel One SmartAPI** key for real live prices (section 5). Without it, TradeLens runs in **demo mode** with a simulated market so you can explore every screen.

**Get the code:** on this GitHub page click the green **Code** button → **Download ZIP**, then extract the ZIP (right-click → *Extract All* on Windows; double-click on Mac).
Or, if you use Git: `git clone https://github.com/hetp1200nx/tradelens.git`

---

## 2. Run it on Windows

**One-time setup**
1. Install Python from https://www.python.org/downloads/ .
   On the first installer screen, **tick "Add python.exe to PATH"**, then click *Install Now*.
2. Check it: press `Win + R`, type `cmd`, press Enter, and run:
   ```
   python --version
   ```
   It should print `Python 3.10` or higher.

**Start TradeLens**
1. Open the extracted `tradelens` folder.
2. Double-click **`start.bat`**.
   - If Windows shows *"Windows protected your PC"*, click **More info → Run anyway**.
   - The first run creates a private Python environment and installs everything (1–3 minutes).
3. Your browser opens **http://localhost:8000**. Keep the black window open while you use the app; closing it stops TradeLens.

Next time, just double-click `start.bat` again (it starts in a few seconds).

**Manual way (if you prefer the command line)**
```
cd path\to\tradelens
python -m venv .venv
.venv\Scripts\pip install -r requirements.txt
copy .env.example .env
.venv\Scripts\python run.py
```
Then open http://localhost:8000.

---

## 3. Run it on Mac

**One-time setup**
1. Install Python from https://www.python.org/downloads/ (download the macOS installer and run it).
2. Open **Terminal** (`Cmd + Space`, type *Terminal*, press Enter) and check:
   ```
   python3 --version
   ```
   It should print `Python 3.10` or higher. (If macOS offers to install "command line developer tools", accept it.)

**Start TradeLens**
1. In Terminal, type `cd ` (with a space), drag the extracted `tradelens` folder into the Terminal window, and press Enter.
2. Run:
   ```
   bash start.sh
   ```
   The first run installs everything (1–3 minutes).
3. Open **http://localhost:8000** in Safari or Chrome. Keep Terminal open while you use the app; press `Ctrl + C` to stop it.

Next time: open Terminal, `cd` into the folder again and run `bash start.sh`.

**Manual way**
```
cd /path/to/tradelens
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
cp .env.example .env
.venv/bin/python run.py
```

---

## 4. First sign-in and the admin account

The first start creates a file called **`.env`** in the folder (a copy of `.env.example`). Open it with Notepad (Windows) or TextEdit (Mac) and set your admin login:
```
ADMIN_USERNAME=your-admin-name
ADMIN_PASSWORD=a-strong-password
```
Save, stop the app (close the window / `Ctrl + C`) and start it again.

- **Admin:** sign in with those details to open the **Admin** dashboard (all users, their Angel API status, trades, CSV export, password resets).
- **Everyone else:** tap **Create account** and fill in name, username, email, mobile, password (8+ characters with an uppercase letter, a lowercase letter, a number and a symbol) and a 4-digit passcode. Angel One API details are optional at sign-up and can be added later in **Profile**.
- **Remember me** lets you unlock the app on that device with just your 4-digit passcode (60 days).

> Keep `.env` private. It holds your admin login and the secret key that encrypts users' Angel details. Never upload it anywhere.
> Back it up: if `SECRET_KEY` (added automatically) is lost, users must re-enter their Angel details.

---

## 5. Switch to live Angel One prices (free)

1. **Create the API key.** Log in at https://smartapi.angelbroking.com → **Create an App** → type **Trading APIs** (needed to read your balance, holdings and positions; TradeLens still never places orders) → any app name, redirect URL `http://127.0.0.1`, and your current public IP if it asks (search "what is my IP"). Copy the **API Key**.
2. **Get the TOTP secret.** Open https://smartapi.angelbroking.com/enable-totp and log in with client ID + PIN + OTP. It shows a QR code **and a text key**. Copy the text key.
3. In TradeLens, open **Profile** (your name, top right) → **Angel One API** and enter: API key, client ID, login PIN and the TOTP text key → **Save**.
4. When it shows **connected**, TradeLens restarts itself into **live mode** within a few seconds. The first live start of the day takes **2–4 minutes** while it loads price history; later starts that day are quick.

Login happens automatically every day with the TOTP secret, with no daily manual step. Live prices for everyone come from one API (the first one that connects, or the one the admin picks in **Admin → user → Use for live prices**); each user's own API shows their own balance, holdings, positions and orders.

*Alternative:* put the four values in `.env` as `ANGEL_API_KEY`, `ANGEL_CLIENT_CODE`, `ANGEL_PIN`, `ANGEL_TOTP_SECRET` and restart.

When the market is closed, the status pill shows **market closed (last prices)**, and prices update again from 9:15 AM.

---

## 6. Save data in Supabase (optional)

By default, users, trades and watchlists are saved in the `data` folder on your computer. That's fine for one computer.
To keep data safe in the cloud (and survive reinstalling), use Supabase's free plan:

1. https://supabase.com → **New project** (region: Mumbai).
2. **SQL Editor → New query** → paste everything from `supabase.sql` → **Run**.
3. **Project Settings → API Keys** → copy the **Project URL** and a **secret** key (`sb_secret_…`) into `.env`:
   ```
   SUPABASE_URL=https://xxxx.supabase.co
   SUPABASE_KEY=sb_secret_xxxxxxxx
   ```
4. Restart TradeLens. Run `python supabase_check.py` (Windows: `.venv\Scripts\python supabase_check.py`, Mac: `.venv/bin/python supabase_check.py`) to confirm the connection.

The secret key stays on your computer only; the web page never sees it.

---

## 7. Use it on your phone / host it from your own computer

**Same Wi-Fi (simplest)**
Find your computer's local IP: Windows `ipconfig` (IPv4 Address), Mac *System Settings → Wi-Fi → Details*. Then open `http://<that-ip>:8000` on your phone, e.g. `http://192.168.1.5:8000`.
Allow Python through the firewall if asked.

**From anywhere, free (your computer acts as the server)**
- **Windows:** double-click **`start_online.bat`**
- **Mac:** `bash start_online.sh` (use `caffeinate -i bash start_online.sh` to stop the Mac sleeping)

This starts TradeLens and a free **Cloudflare Tunnel** (downloaded automatically the first time) and prints a public `https://….trycloudflare.com` link that works on any phone or computer. Everyone must sign in. The computer must stay on and awake.

*Optional extras for the online mode (in `.env`):*
- **One fixed link:** the tunnel link changes on every restart. Set `GITHUB_TOKEN` (a fine-grained token with *Contents: Read and write* on **your own** repo) and `GITHUB_REPO=your-username/your-repo`. TradeLens then updates a small forwarding page on that repo's GitHub Pages (`gh-pages` branch), so one address always points to the current link. Turn on GitHub Pages for the `gh-pages` branch in the repo settings.
- **Telegram:** set `TELEGRAM_BOT_TOKEN` and `TELEGRAM_CHAT_ID` to receive the new link (and trade alerts) on Telegram. Create a bot with @BotFather, send it any message, then open `https://api.telegram.org/bot<TOKEN>/getUpdates` and copy `"chat":{"id": …}`.
- **Start with Windows:** run **`install_autostart.bat`** once, and TradeLens goes online every time you sign in to Windows. To undo, press `Win + R`, type `shell:startup`, and delete *TradeLens online.bat*.

**Install as an app:** open TradeLens in Chrome/Safari on your phone → **Add to Home screen**. Tap **🔔 Alerts** to turn on notifications.

---

## 8. What each screen does

**Boards:** Sensex / Nifty 50 / Volatile Watchlist, in **List** or **Grid** view, updated every second.
- **Strength (0–100):** today's move vs the stock's normal daily range (ATR), volume vs a normal day at this time, buyer/seller quantity in the order book, and position in the day's range. Choppy stocks score 0.
- **Vol ×:** today's volume compared with a normal day at the same time.
- **Buy / Sell bar:** total pending buy vs sell quantity.
- **OI view (F&O):** Long build-up, Short build-up, Short covering, Long unwinding.
- **Grid view:** a live card per share with sparkline, rank, conviction, VWAP, order-block zone, support/resistance (S1–S4, R1–R4), risk-reward, signal and a mini intraday chart. Filter and sort.
- **+ Add share:** live search across every NSE share, or **Import Excel / CSV** (symbols in the first column or a column named Symbol/Stock/Share/Scrip/Name; **Template** downloads a sample).

**Market Flow (tree view):** sectors ranked on the left, every share's move since the open drawn as a live line, bullish vs bearish split on the right, and the strongest buying and selling shares with their recent volume.

**Stock page (tap any share):**
- Live chart (1 min to weekly) with EMA 20/50, VWAP, order-block zones, liquidity levels and your own trade lines.
- **Suggestion** per style: BUY / SELL / WAIT / AVOID with entry zone, stop-loss, 2 targets, risk-reward, reasons and warnings.
  - *Intraday (5-min):* trend from VWAP + EMA 20/50 + order-book pressure + OI; entry at the nearest fresh order block; targets at untaken liquidity / previous-day high-low. Warns in the first 15 min, late in the day, in choppy or low-volume stocks, near circuits, or when reward is under 1.2× risk.
  - *Long term (daily):* 50/200-day trend, daily order blocks, RSI. "SELL" here means exit or avoid holding.
  - *Option:* follows the intraday signal; suggests a 1-strike in-the-money CE/PE with premium entry/SL/targets and risk per lot, plus time-decay and expiry warnings.
- **Live quote:** OHLC, volume, VWAP, circuits, 52-week range, OI, 5-level market depth.
- **P&L calculator:** net profit/loss at SL, T1 and T2 **after brokerage, STT, exchange fees, SEBI fee, stamp duty, GST and DP charges**.
- **Backtest:** replays the intraday order-block rule on ~60 days of 5-minute history (win rate, average R after costs, profit factor, worst losing streak).

**Trade Planner:** uses your Angel available balance (or any amount you type) and suggests sized trades for intraday, options and long term, keeping loss at stop-loss within 1% of balance by default, with **expected P&L** for each idea. Below ₹2,000 it shows **Recharge wallet**.

**Angel Account (read-only):** available balance, margin used, positions and holdings with live P&L, today's orders, and an optional daily loss limit warning.

**My Trades:** log trades you took in your broker app. Each open trade shows live net P&L after charges and plain advice (*Hold / Book part at T1 / Exit at T2 / Stop-loss hit / Signal turned against you / Market closes soon*), with a pop-up, sound, notification and optional Telegram alert. Export to Excel (CSV).

**Radar:** volume spikes, new day highs/lows with volume, strength crossing 70, trends starting after choppy trading, and your own price alerts.

**Scorecard:** records BUY/SELL signals from the strongest stocks and later marks each a win or loss. Use it (with backtests) to judge how much to trust the signals.

**Light / dark mode:** ☾ / ☀ in the top bar.

---

## 9. Troubleshooting

| Problem | Fix |
|---|---|
| `python` is not recognized (Windows) | Reinstall Python and tick **Add python.exe to PATH**, then open a new window. |
| `python3: command not found` (Mac) | Install Python from python.org, then open a new Terminal window. |
| Page doesn't open | Make sure the start window is still open, then go to http://localhost:8000 . If port 8000 is busy, set `PORT=8001` in `.env`. |
| Yellow **DEMO** badge | No working Angel API yet; see section 5. |
| Angel "Invalid TOTP" / login failed | Check client ID, 4-digit PIN and the TOTP **text key** (not the 6-digit code), and that your computer's clock is correct. |
| Angel Account says the service isn't answering | Angel's account service is down temporarily (common at night and on weekends); it retries automatically. |
| Forgot admin password | Change `ADMIN_PASSWORD` in `.env` and restart. |
| Start over with fresh data | Stop the app and delete the `data` folder (local storage only). |

---

## 10. Files
```
start.bat / start.sh                 start on this computer (Windows / Mac)
start_online.bat / start_online.sh   start + public link via Cloudflare Tunnel
install_autostart.bat                go online automatically at Windows sign-in
run.py                               the server
online.py                            tunnel, fixed link and keep-awake helper
.env.example                         settings template (copied to .env on first start)
supabase.sql                         database setup for Supabase (optional)
backend/feeds/angel.py               Angel One login, history and live feed (read-only)
backend/feeds/demo.py                simulated market for demo mode
backend/analytics.py                 indicators, order blocks, liquidity, VWAP
backend/signals.py                   intraday / long-term / option suggestion rules
backend/market.py                    live quotes, candles, board strength scores
backend/engine.py                    trade tracking, alerts, scorecard, backtest
backend/charges.py                   brokerage and tax calculation (edit if your rates differ)
backend/planner.py                   Trade Planner
backend/universe.py                  Nifty 50 / Sensex lists (update when indices rebalance)
frontend/                            the web app (phone and desktop)
```
