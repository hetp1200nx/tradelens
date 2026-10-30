"""Storage for users, trades and settings.
Uses Supabase if SUPABASE_URL and SUPABASE_KEY are set, otherwise local JSON files in data/.
Every trade carries the id of the user who owns it; per-user settings live under keys "u:<user id>:<name>"."""
from __future__ import annotations

import json
import threading
import time
import uuid

import requests

from . import config as C

_lock = threading.Lock()
TABLES = {"trades": "trades.json", "users": "users.json"}


class Store:
    def __init__(self):
        self.supa = bool(C.SUPABASE_URL and C.SUPABASE_KEY)
        self.trades: dict[str, dict] = {}
        self.users: dict[str, dict] = {}
        self.kv: dict[str, object] = {}
        self.error = ""
        self._load()

    # ---------------- backend helpers
    def _h(self, extra=None):
        h = {"apikey": C.SUPABASE_KEY, "Content-Type": "application/json"}
        if C.SUPABASE_KEY.startswith("eyJ"):  # legacy service_role key (a JWT) also goes in Authorization
            h["Authorization"] = f"Bearer {C.SUPABASE_KEY}"
        # new secret keys (sb_secret_...) are sent only in the apikey header, as Supabase requires
        h.update(extra or {})
        return h

    def _load(self):
        if self.supa:
            try:
                for table in TABLES:
                    r = requests.get(f"{C.SUPABASE_URL}/rest/v1/{table}?select=id,data", headers=self._h(), timeout=15)
                    r.raise_for_status()
                    setattr(self, table, {row["id"]: row["data"] for row in r.json()})
                r = requests.get(f"{C.SUPABASE_URL}/rest/v1/app_kv?select=key,value", headers=self._h(), timeout=15)
                r.raise_for_status()
                self.kv = {row["key"]: row["value"] for row in r.json()}
                return
            except Exception as e:
                self.error = f"Supabase not reachable ({e}); using local files"
                self.supa = False
        for table, fname in TABLES.items():
            f = C.DATA_DIR / fname
            if f.exists():
                setattr(self, table, json.loads(f.read_text()))
        k = C.DATA_DIR / "kv.json"
        if k.exists():
            self.kv = json.loads(k.read_text())

    def _save_row(self, table: str, row: dict | None, delete_id: str | None = None):
        if self.supa:
            def go():
                try:
                    if delete_id:
                        requests.delete(f"{C.SUPABASE_URL}/rest/v1/{table}?id=eq.{delete_id}", headers=self._h(), timeout=15)
                    else:
                        requests.post(f"{C.SUPABASE_URL}/rest/v1/{table}", headers=self._h({"Prefer": "resolution=merge-duplicates"}),
                                      data=json.dumps({"id": row["id"], "data": row}), timeout=15).raise_for_status()
                except Exception as e:
                    self.error = f"Supabase save failed: {e}"
                    print(f"[TradeLens] {self.error}", flush=True)
            threading.Thread(target=go, daemon=True).start()
        else:
            with _lock:
                (C.DATA_DIR / TABLES[table]).write_text(json.dumps(getattr(self, table), indent=1))

    def _kv_push(self, key, value, delete=False):
        if self.supa:
            def go():
                try:
                    if delete:
                        requests.delete(f"{C.SUPABASE_URL}/rest/v1/app_kv?key=eq.{requests.utils.quote(key)}", headers=self._h(), timeout=15)
                    else:
                        requests.post(f"{C.SUPABASE_URL}/rest/v1/app_kv", headers=self._h({"Prefer": "resolution=merge-duplicates"}),
                                      data=json.dumps({"key": key, "value": value}), timeout=15).raise_for_status()
                except Exception as e:
                    self.error = f"Supabase save failed: {e}"
                    print(f"[TradeLens] {self.error}", flush=True)
            threading.Thread(target=go, daemon=True).start()
        else:
            with _lock:
                (C.DATA_DIR / "kv.json").write_text(json.dumps(self.kv))

    # ---------------- key/value settings (global and per user)
    def set_kv(self, key, value):
        self.kv[key] = value
        self._kv_push(key, value)

    def ukv(self, uid: str, key: str, default=None):
        v = self.kv.get(f"u:{uid}:{key}")
        return default if v is None else v

    def set_ukv(self, uid: str, key: str, value):
        self.set_kv(f"u:{uid}:{key}", value)

    # ---------------- users
    def save_user(self, u: dict):
        self.users[u["id"]] = u
        self._save_row("users", u)

    def delete_user(self, uid: str):
        """Remove a user and everything they own."""
        self.users.pop(uid, None)
        self._save_row("users", None, delete_id=uid)
        for tid in [t["id"] for t in self.trades.values() if t.get("user") == uid]:
            self.delete(tid)
        for k in [k for k in self.kv if k.startswith(f"u:{uid}:")]:
            self.kv.pop(k, None)
            self._kv_push(k, None, delete=True)

    # ---------------- trades
    def list(self, user: str | None = None):
        rows = [t for t in self.trades.values() if user is None or t.get("user") == user]
        return sorted(rows, key=lambda t: t.get("created_at", 0), reverse=True)

    def add(self, t: dict, user: str) -> dict:
        t = dict(t)
        t["id"] = uuid.uuid4().hex[:12]
        t["user"] = user
        t["created_at"] = int(time.time())
        t.setdefault("status", "open")
        t["alerts_sent"] = []
        self.trades[t["id"]] = t
        self._save_row("trades", t)
        return t

    def get(self, tid: str, user: str | None = None) -> dict | None:
        t = self.trades.get(tid)
        if t and user is not None and t.get("user") != user:
            return None
        return t

    def update(self, tid: str, fields: dict, user: str | None = None) -> dict | None:
        t = self.get(tid, user)
        if not t:
            return None
        fields.pop("user", None)
        fields.pop("id", None)
        t.update(fields)
        self._save_row("trades", t)
        return t

    def delete(self, tid: str, user: str | None = None):
        if self.get(tid, user) and self.trades.pop(tid, None) is not None:
            self._save_row("trades", None, delete_id=tid)


STORE = None


def store() -> Store:
    global STORE
    if STORE is None:
        STORE = Store()
    return STORE
