"""Check your Supabase connection and copy any locally saved data into it.

Run once after filling SUPABASE_URL and SUPABASE_KEY in .env:
    python supabase_check.py            (Windows: .venv\\Scripts\\python supabase_check.py)
"""
import json
import sys

import requests

from backend import config as C


def headers(extra=None):
    h = {"apikey": C.SUPABASE_KEY, "Content-Type": "application/json"}
    if C.SUPABASE_KEY.startswith("eyJ"):
        h["Authorization"] = f"Bearer {C.SUPABASE_KEY}"
    h.update(extra or {})
    return h


def main():
    if not (C.SUPABASE_URL and C.SUPABASE_KEY):
        sys.exit("SUPABASE_URL and SUPABASE_KEY are empty in .env. Fill them in first.")
    if C.SUPABASE_KEY.startswith("sb_publishable") or ('"role":"anon"' in C.SUPABASE_KEY):
        sys.exit("That is the PUBLISHABLE / anon key. Use the SECRET key (sb_secret_...) or the legacy service_role key.")
    print("Supabase URL:", C.SUPABASE_URL)
    ok = True
    for table in ("users", "trades", "app_kv"):
        sel = "key" if table == "app_kv" else "id"
        try:
            r = requests.get(f"{C.SUPABASE_URL}/rest/v1/{table}?select={sel}&limit=1", headers=headers(), timeout=20)
        except Exception as e:
            sys.exit(f"Cannot reach Supabase: {e}\nCheck SUPABASE_URL (it looks like https://abcdxyz.supabase.co).")
        if r.status_code == 200:
            print(f"  table {table:7s} OK")
        else:
            ok = False
            msg = r.text[:200]
            hint = ("run supabase.sql in the SQL Editor" if r.status_code == 404 or "does not exist" in msg
                    else "check the key: it must be the SECRET / service_role key" if r.status_code in (401, 403) else "")
            print(f"  table {table:7s} ERROR {r.status_code}: {msg}\n    -> {hint}")
    if not ok:
        sys.exit("\nFix the errors above and run this again.")

    # copy local data (if any) into Supabase
    copied = 0
    for table, fname in (("users", "users.json"), ("trades", "trades.json")):
        f = C.DATA_DIR / fname
        if not f.exists():
            continue
        rows = [{"id": k, "data": v} for k, v in json.loads(f.read_text()).items()]
        if rows:
            r = requests.post(f"{C.SUPABASE_URL}/rest/v1/{table}", headers=headers({"Prefer": "resolution=merge-duplicates"}),
                              data=json.dumps(rows), timeout=60)
            r.raise_for_status()
            copied += len(rows)
            print(f"  copied {len(rows)} {table} from local file")
    f = C.DATA_DIR / "kv.json"
    if f.exists():
        rows = [{"key": k, "value": v} for k, v in json.loads(f.read_text()).items()]
        if rows:
            r = requests.post(f"{C.SUPABASE_URL}/rest/v1/app_kv", headers=headers({"Prefer": "resolution=merge-duplicates"}),
                              data=json.dumps(rows), timeout=60)
            r.raise_for_status()
            copied += len(rows)
            print(f"  copied {len(rows)} settings / watchlists from local file")
    print("\nAll good. Supabase is ready." + ("" if copied else " (No local data to copy.)"))
    print("Start TradeLens again; the Admin page footer and /api/status will show storage: supabase.")


if __name__ == "__main__":
    main()
