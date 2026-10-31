"""User accounts: sign-up, sign-in, remember-me + 4-digit passcode unlock, admin.

Security choices:
- Passwords and passcodes are stored only as scrypt hashes. Nobody, including admin, can read them; admin can reset them.
- Angel One details (API key, PIN, TOTP secret) are encrypted with a secret key (SECRET_KEY in .env, created automatically).
  The admin dashboard shows them masked; they are only decrypted inside the server to log in to Angel One.
- Sessions are signed cookies. "Remember me" keeps a device token for 60 days; on that device you unlock with your passcode.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import os
import re
import secrets
import time
import uuid

from cryptography.fernet import Fernet, InvalidToken

from . import config as C
from .storage import store

SESSION_HOURS = 12
DEVICE_DAYS = 60
MAX_PASSCODE_FAILS = 5
_login_fails: dict[str, list[float]] = {}


# ------------------------------------------------------------------ secret key
def _secret() -> bytes:
    key = os.getenv("SECRET_KEY", "")
    if not key:
        key = secrets.token_urlsafe(48)
        os.environ["SECRET_KEY"] = key
        env = C.ROOT / ".env"
        try:
            with open(env, "a") as f:
                f.write(f"\n# created automatically: keeps logins and encrypted Angel details valid. Never share or change it.\nSECRET_KEY={key}\n")
        except OSError:
            print("WARNING: could not save SECRET_KEY to .env; logins will reset when the server restarts")
    return key.encode()


SECRET = _secret()
FERNET = Fernet(base64.urlsafe_b64encode(hashlib.sha256(b"tradelens-enc:" + SECRET).digest()))


def enc(s: str) -> str:
    return FERNET.encrypt(s.encode()).decode() if s else ""


def dec(s: str) -> str:
    try:
        return FERNET.decrypt(s.encode()).decode() if s else ""
    except InvalidToken:
        return ""


# ------------------------------------------------------------------ hashing
def hash_secret(pw: str) -> str:
    salt = secrets.token_bytes(16)
    h = hashlib.scrypt(pw.encode(), salt=salt, n=2 ** 14, r=8, p=1, dklen=32)
    return f"scrypt${salt.hex()}${h.hex()}"


def check_secret(pw: str, stored: str) -> bool:
    try:
        _, salt, h = stored.split("$")
        got = hashlib.scrypt(pw.encode(), salt=bytes.fromhex(salt), n=2 ** 14, r=8, p=1, dklen=32)
        return hmac.compare_digest(got.hex(), h)
    except Exception:
        return False


# ------------------------------------------------------------------ validation
PW_RULE = "at least 8 characters with one uppercase letter, one lowercase letter, one number and one symbol"


def password_ok(pw: str) -> bool:
    return (len(pw) >= 8 and re.search(r"[A-Z]", pw) and re.search(r"[a-z]", pw)
            and re.search(r"\d", pw) and re.search(r"[^A-Za-z0-9]", pw)) is not None


def validate_signup(b: dict) -> dict:
    """Returns {field: error} for every problem (empty dict = valid)."""
    e = {}
    for k, label in (("first_name", "First name"), ("last_name", "Last name")):
        if not (b.get(k) or "").strip():
            e[k] = f"{label} is required"
    un = (b.get("username") or "").strip()
    if not re.fullmatch(r"[A-Za-z0-9_.]{4,20}", un):
        e["username"] = "4–20 letters, numbers, _ or ."
    elif find_by_username(un):
        e["username"] = "This username is taken"
    if not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", (b.get("email") or "").strip()):
        e["email"] = "Enter a valid email"
    elif any((u.get("email") or "").lower() == b["email"].strip().lower() for u in store().users.values()):
        e["email"] = "An account with this email exists"
    ph = re.sub(r"[\s-]", "", b.get("phone") or "")
    if not re.fullmatch(r"(\+?91)?[6-9]\d{9}", ph):
        e["phone"] = "Enter a valid 10-digit mobile number"
    pw = b.get("password") or ""
    if not password_ok(pw):
        e["password"] = "Password needs " + PW_RULE
    if pw != (b.get("confirm_password") or ""):
        e["confirm_password"] = "Passwords don't match"
    pc = b.get("passcode") or ""
    if not re.fullmatch(r"\d{4}", pc):
        e["passcode"] = "Passcode must be 4 digits"
    elif pc != (b.get("confirm_passcode") or ""):
        e["confirm_passcode"] = "Passcodes don't match"
    a = [b.get(k, "").strip() for k in ("api_key", "client_code", "pin", "totp_secret")]
    if any(a) and not all(a):
        e["angel"] = "Fill all four Angel One fields, or leave all empty to add later"
    return e


# ------------------------------------------------------------------ users
def find_by_username(username: str) -> dict | None:
    un = (username or "").strip().lower()
    return next((u for u in store().users.values() if u["username"].lower() == un), None)


def get(uid: str) -> dict | None:
    return store().users.get(uid)


def set_angel(u: dict, api_key, client_code, pin, totp_secret, status="saved", error=""):
    u["angel"] = {"api_key": enc(api_key.strip()), "client_code": client_code.strip().upper(), "pin": enc(pin.strip()),
                  "totp": enc(totp_secret.strip().replace(" ", "")), "status": status, "error": error, "checked": int(time.time())}


def angel_creds(uid: str) -> dict | None:
    u = get(uid)
    a = (u or {}).get("angel")
    if not a:
        return None
    c = {"api_key": dec(a["api_key"]), "client_code": a["client_code"], "pin": dec(a["pin"]), "totp_secret": dec(a["totp"])}
    return c if all(c.values()) else None


def create(b: dict) -> dict:
    u = {"id": uuid.uuid4().hex[:12], "role": "user", "first_name": b["first_name"].strip(), "last_name": b["last_name"].strip(),
         "username": b["username"].strip(), "email": b["email"].strip().lower(), "phone": re.sub(r"[\s-]", "", b["phone"]),
         "pw": hash_secret(b["password"]), "pc": hash_secret(b["passcode"]), "pc_fails": 0, "gen": 1,
         "created": int(time.time()), "last_login": None, "disabled": False}
    if b.get("api_key"):
        set_angel(u, b["api_key"], b["client_code"], b["pin"], b["totp_secret"])
    store().save_user(u)
    return u


def ensure_admin():
    """Create / update the admin account from ADMIN_USERNAME and ADMIN_PASSWORD in .env."""
    un, pw = os.getenv("ADMIN_USERNAME", ""), os.getenv("ADMIN_PASSWORD", "")
    if not un or not pw:
        print("No ADMIN_USERNAME / ADMIN_PASSWORD in .env: admin dashboard disabled")
        return
    u = store().users.get("admin")
    if u is None:
        u = {"id": "admin", "role": "admin", "first_name": "Admin", "last_name": "", "username": un, "email": "", "phone": "",
             "pw": hash_secret(pw), "pc": "", "pc_fails": 0, "gen": 1, "created": int(time.time()), "last_login": None, "disabled": False}
        store().save_user(u)
    elif u["username"] != un or not check_secret(pw, u["pw"]):
        u["username"], u["pw"] = un, hash_secret(pw)
        store().save_user(u)


DEMO_USERNAME, DEMO_PASSWORD, DEMO_PASSCODE = "Demo", "demo@123", "1234"


def ensure_demo_user():
    """Demo copy: a ready-made login (Demo / demo@123, passcode 1234), reset on every start."""
    u = store().users.get("demo")
    if u is None:
        u = {"id": "demo", "role": "user", "first_name": "Demo", "last_name": "User", "username": DEMO_USERNAME,
             "email": "demo@example.com", "phone": "0000000000", "pw": hash_secret(DEMO_PASSWORD), "pc": hash_secret(DEMO_PASSCODE),
             "pc_fails": 0, "gen": 1, "created": int(time.time()), "last_login": None, "disabled": False}
    else:
        u.update({"username": DEMO_USERNAME, "pw": hash_secret(DEMO_PASSWORD), "pc": hash_secret(DEMO_PASSCODE),
                  "pc_fails": 0, "disabled": False})
        u.pop("angel", None)
    store().save_user(u)


def mask(s: str, keep=4) -> str:
    return "" if not s else ("•" * max(4, len(s) - keep)) + s[-keep:]


def public(u: dict, admin_view=False) -> dict:
    a = u.get("angel") or {}
    out = {"id": u["id"], "role": u["role"], "first_name": u["first_name"], "last_name": u["last_name"], "username": u["username"],
           "email": u["email"], "phone": u["phone"], "created": u["created"], "last_login": u.get("last_login"),
           "has_passcode": bool(u.get("pc")), "disabled": u.get("disabled", False),
           "angel": {"connected": bool(a), "client_code": a.get("client_code", ""), "status": a.get("status", "not added"),
                     "error": a.get("error", ""), "checked": a.get("checked")},
           "data_source": store().kv.get("data_user") == u["id"]}
    if a:
        out["angel"]["api_key_masked"] = mask(dec(a.get("api_key", "")))
        out["angel"]["pin_masked"] = "••••"
        out["angel"]["totp_masked"] = "•••• (encrypted)"
    return out


# ------------------------------------------------------------------ login throttling
def throttled(username: str) -> int:
    now = time.time()
    fails = [t for t in _login_fails.get(username.lower(), []) if now - t < 600]
    _login_fails[username.lower()] = fails
    if len(fails) >= 5:
        return int(600 - (now - fails[0]))
    return 0


def note_fail(username: str):
    _login_fails.setdefault(username.lower(), []).append(time.time())


# ------------------------------------------------------------------ tokens
def _sign(payload: str) -> str:
    return hmac.new(SECRET, payload.encode(), hashlib.sha256).hexdigest()[:40]


def make_token(kind: str, u: dict, hours: float) -> str:
    payload = f"{kind}.{u['id']}.{int(time.time() + hours * 3600)}.{u.get('gen', 1)}"
    return f"{payload}.{_sign(payload)}"


def read_token(tok: str | None, kind: str) -> dict | None:
    try:
        k, uid, exp, gen, sig = (tok or "").split(".")
        payload = f"{k}.{uid}.{exp}.{gen}"
        if k != kind or not hmac.compare_digest(sig, _sign(payload)) or int(exp) < time.time():
            return None
        u = get(uid)
        if not u or u.get("disabled") or str(u.get("gen", 1)) != gen:
            return None
        return u
    except Exception:
        return None


def logged_in(u: dict):
    u["last_login"] = int(time.time())
    u["pc_fails"] = 0
    store().save_user(u)


def reset_password(u: dict) -> str:
    """Admin reset: returns a one-time temporary password meeting the rules; signs the user out everywhere."""
    temp = "Tl" + secrets.token_hex(3) + "@" + str(secrets.randbelow(90) + 10)
    u["pw"] = hash_secret(temp)
    u["gen"] = u.get("gen", 1) + 1
    u["pc_fails"] = 0
    store().save_user(u)
    return temp


def verify_angel(creds: dict) -> tuple[bool, str]:
    """Try to log in to Angel One with these details (read-only check)."""
    try:
        import pyotp
        from SmartApi import SmartConnect
    except ImportError:
        return False, "saved (not checked: Angel One libraries not installed; run in live mode to verify)"
    try:
        api = SmartConnect(api_key=creds["api_key"])
        r = api.generateSession(creds["client_code"], creds["pin"], pyotp.TOTP(creds["totp_secret"]).now())
        if r and r.get("status"):
            try:
                api.terminateSession(creds["client_code"])
            except Exception:
                pass
            return True, ""
        return False, (r or {}).get("message") or "login failed"
    except Exception as e:
        return False, str(e)


def mark_angel(uid: str, status: str, error: str):
    """Record the latest Angel One connection result (shown in Profile and admin)."""
    u = get(uid)
    a = (u or {}).get("angel")
    if not a or (a.get("status") == status and a.get("error") == error):
        return
    a["status"], a["error"], a["checked"] = status, error[:200], int(time.time())
    store().save_user(u)
