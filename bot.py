# -*- coding: utf-8 -*-

import re
import json
import time
import os
import threading
import requests
import telebot
from datetime import date

BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID  = int(os.getenv("ADMIN_ID", "0"))

CONFIG_FILE = "config.json"
DB_FILE     = "seen_posts.json"
STATS_FILE  = "stats.json"

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)
HEADERS = {"User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile)"}

# ================= CONFIG =================
def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except:
        return default_config()

def default_config():
    return {
        "sky_domain": "https://skymovieshd.free/",
        "hdm_rss": "https://hdmovie2.org.uk/movies/feed/",
        "ef_url": "https://e4.extraflix.mobi/",
        "ff_url": "https://filmyfly.builders/",
        "interval": 900,
        "tag_username": "@username",
        "tag_id": 123456789,
        # channels per-source + common
        "channels": [],
        "sky_channels": [],
        "hdm_channels": [],
        "ef_channels": [],
        "ff_channels": [],
        # per-chat overrides: {"chat_id": {"cmd": "/l2", "extractor": "gofile", ...}}
        "chat_overrides": {},
        "sky_enabled": True, "hdm_enabled": True,
        "ef_enabled": True, "ff_enabled": True,
        "sky_extractor": "gofile",
        "ef_extractor": "hubcloud",
        "ff_extractor": "all",
        "ff_size_limit_mb": 4096,
        "complete_word": "Complete",  # change via /setcompleteword
        "sky_cmd": "/l3", "hdm_cmd": "/l3", "ef_cmd": "/l3", "ff_cmd": "/l3",
        # captions
        "sky_movie_caption":  "{title} ({year}) {quality} {language} {source} {codec} {esub}.mkv",
        "sky_series_caption": "{title} ({year}) {season} {episode} {complete} {quality} {language} {source} {codec} {esub}.mkv",
        "hdm_movie_caption":  "{title} ({year}) {quality} {language} {source} {codec} {esub}.mkv",
        "hdm_series_caption": "{title} ({year}) {season} {episode} {complete} {quality} {language} {source} {codec} {esub}.mkv",
        "ef_movie_caption":   "{title} ({year}) {quality} {language} {source} {codec} {esub}.mkv",
        "ef_series_caption":  "{title} ({year}) {season} {episode} {complete} {quality} {language} {source} {codec} {esub}.mkv",
        "ff_movie_caption":   "{title} ({year}) {quality} {language} {source} {codec} {esub}.mkv",
        "ff_series_caption":  "{title} ({year}) {season} {episode} {complete} {quality} {language} {source} {codec} {esub}.mkv",
    }

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

def get_chat_override(cfg, chat_id, key, default):
    """Per-chat override agar set hai to woh, warna global"""
    overrides = cfg.get("chat_overrides", {})
    return overrides.get(str(chat_id), {}).get(key, default)

def set_chat_override(cfg, chat_id, key, value):
    if "chat_overrides" not in cfg:
        cfg["chat_overrides"] = {}
    cid = str(chat_id)
    if cid not in cfg["chat_overrides"]:
        cfg["chat_overrides"][cid] = {}
    cfg["chat_overrides"][cid][key] = value

# ================= DB =================
def load_seen():
    try:
        with open(DB_FILE, "r") as f:
            return set(json.load(f))
    except:
        return set()

def save_seen(seen):
    with open(DB_FILE, "w") as f:
        json.dump(list(seen), f)

# ================= STATS =================
def load_stats():
    try:
        with open(STATS_FILE, "r") as f:
            return json.load(f)
    except:
        return {"date": str(date.today()), "sky": 0, "hdm": 0, "ef": 0, "ff": 0}

def save_stats(s):
    with open(STATS_FILE, "w") as f:
        json.dump(s, f)

def increment_stat(source):
    s = load_stats()
    today = str(date.today())
    if s.get("date") != today:
        s = {"date": today, "sky": 0, "hdm": 0, "ef": 0, "ff": 0}
    s[source] = s.get(source, 0) + 1
    save_stats(s)

last_check = {"sky": None, "hdm": None, "ef": None, "ff": None}
next_check = {"sky": None, "hdm": None, "ef": None, "ff": None}

def is_admin(msg):
    return msg.from_user.id == ADMIN_ID

# ================= TITLE PARSER =================
def parse_title(raw):
    raw = re.sub(r'^GDFlix\s*\|\s*', '', raw, flags=re.I).strip()
    raw = re.sub(r'\s*\[www\.[^\]]+\]\s*', ' ', raw, flags=re.I).strip()
    raw = re.sub(r'^Download\s+', '', raw, flags=re.I).strip()
    raw = re.sub(r'\s*\[[^\]]*(?:MB|GB)[^\]]*\]', '', raw, flags=re.I).strip()
    raw = re.sub(r'\.(mkv|mp4|avi)$', '', raw, flags=re.I).strip()
    raw = re.sub(r'\s+-\s+-\s+', ' ', raw).strip()
    raw = re.sub(r'\[Dual Audio\]|\[.*?Audio.*?\]', '', raw, flags=re.I).strip()
    raw = re.sub(r'[-_. ]*ExtraFlix\.Pw', '', raw, flags=re.I).strip()
    raw = re.sub(r'[-_. ]*FilmyFly\.[A-Za-z]+', '', raw, flags=re.I).strip()
    raw = re.sub(r'\s+', ' ', raw).strip()

    p = {}
    y = re.search(r'\b(19|20)\d{2}\b', raw)
    p['year'] = y.group() if y else ''
    q = re.search(r'\b(4K|2160p|1080p|720p|480p|360p)\b', raw, re.I)
    p['quality'] = q.group().lower() if q else ''
    src = re.search(r'\b(WEB-DL|WEBRip|BluRay|BDRip|HDTC|HDRip|DVDRip|AMZN|NF|ZEE5|HOTSTAR|JIO)\b', raw, re.I)
    p['source'] = src.group().upper() if src else ''
    codec = re.search(r'\b(x264|x265|HEVC|AVC|AV1)\b', raw, re.I)
    p['codec'] = codec.group().lower() if codec else ''
    lang = re.search(r'\b(Hindi|English|Tamil|Telugu|Malayalam|Kannada|Bengali|Multi)\b', raw, re.I)
    p['language'] = lang.group().capitalize() if lang else ''
    season = re.search(r'\bS(?:eason\s*)?(\d{1,2})\b', raw, re.I)
    p['season'] = f"Season {int(season.group(1))}" if season else ''
    ep = re.search(r'\bEP?\s*(\d{1,2})(?:\s*[-\u2013]\s*(\d{1,2}))?\b', raw, re.I)
    if ep:
        p['episode'] = f"EP{ep.group(1).zfill(2)}-{ep.group(2).zfill(2)}" if ep.group(2) else f"EP{ep.group(1).zfill(2)}"
    else:
        p['episode'] = ''
    _cw = load_config().get("complete_word", "Complete")
    p['complete'] = _cw if re.search(r'\bcomplete\b', raw, re.I) else ''
    p['combine'] = _cw  # alias: {combine} works same as {complete}
    p['esub'] = 'Esub'
    if y:
        title_part = raw[:y.start()].strip().rstrip('.-\u2013 ')
    elif q:
        title_part = raw[:q.start()].strip().rstrip('.-\u2013 ')
    else:
        title_part = raw
    p['title'] = title_part.strip().rstrip('.(- ')
    return p

DEFAULT_SKY_MOVIE  = "{title} ({year}) {quality} {language} {source} {codec} {esub}.mkv"
DEFAULT_SKY_SERIES = "{title} ({year}) {season} {episode} {complete} {quality} {language} {source} {codec} {esub}.mkv"
DEFAULT_HDM_MOVIE  = "{title} ({year}) {quality} {language} {source} {codec} {esub}.mkv"
DEFAULT_HDM_SERIES = "{title} ({year}) {season} {episode} {complete} {quality} {language} {source} {codec} {esub}.mkv"
DEFAULT_EF_MOVIE   = "{title} ({year}) {quality} {language} {source} {codec} {esub}.mkv"
DEFAULT_EF_SERIES  = "{title} ({year}) {season} {episode} {complete} {quality} {language} {source} {codec} {esub}.mkv"
DEFAULT_FF_MOVIE   = "{title} ({year}) {quality} {language} {source} {codec} {esub}.mkv"
DEFAULT_FF_SERIES  = "{title} ({year}) {season} {episode} {complete} {quality} {language} {source} {codec} {esub}.mkv"

def apply_caption(parts, fmt):
    result = fmt
    for k, v in parts.items():
        result = result.replace('{' + k + '}', v)
    result = re.sub(r'\(\s*\)', '', result)       # empty ()
    result = re.sub(r'\(\s+', '(', result)          # "( 2025" → "(2025"
    result = re.sub(r'\s+\)', ')', result)           # "2025 )" → "2025)"
    result = re.sub(r'\s{2,}', ' ', result).strip()
    result = re.sub(r'\s+\.mkv$', '.mkv', result)
    return result

def get_fmt(source, parts, chat_id=None):
    cfg = load_config()
    is_series = bool(parts.get('season') or parts.get('episode') or parts.get('complete'))
    defaults = {
        "sky": (DEFAULT_SKY_MOVIE, DEFAULT_SKY_SERIES),
        "hdm": (DEFAULT_HDM_MOVIE, DEFAULT_HDM_SERIES),
        "ef":  (DEFAULT_EF_MOVIE,  DEFAULT_EF_SERIES),
        "ff":  (DEFAULT_FF_MOVIE,  DEFAULT_FF_SERIES),
    }
    dm, ds = defaults.get(source, (DEFAULT_SKY_MOVIE, DEFAULT_SKY_SERIES))
    cap_key = f"{source}_series_caption" if is_series else f"{source}_movie_caption"
    global_val = cfg.get(cap_key, ds if is_series else dm)
    if chat_id:
        return get_chat_override(cfg, chat_id, cap_key, global_val)
    return global_val

def clean_title(raw, source="sky"):
    p = parse_title(raw)
    return apply_caption(p, get_fmt(source, p))

# ================= JINA TITLE =================
def fetch_title_via_jina(gdflix_url, retries=2, timeout=30):
    for attempt in range(retries + 1):
        try:
            r = requests.get(f"https://r.jina.ai/{gdflix_url}",
                             headers={"User-Agent": "Mozilla/5.0"}, timeout=timeout)
            m = re.search(r'Title:\s*GDFlix\s*\|\s*(.+?)(?:\n|URL Source)', r.text, re.I)
            if m: return m.group(1).strip()
            m2 = re.search(r'Name\s*:\s*([^\n]+\.mkv)', r.text, re.I)
            if m2: return m2.group(1).strip()
            return None
        except requests.exceptions.Timeout:
            if attempt < retries:
                print(f"Jina timeout, retry {attempt+1}/{retries}...")
                time.sleep(3)
            else:
                print("Jina: max retries reached, skipping.")
        except Exception as e:
            print(f"Jina error: {e}")
            break
    return None

# ================= SITES (Sky / HDM / EF / FF) =================
# Har site ka pura code ab sites/ folder mein hai (sky.py, hdm.py, ef.py, ff.py).
# Yahan se import niche hai (functions define hone ke baad) taaki sites/*.py
# files 'from bot import ...' kar sakein bina circular-import error ke.

# ================= SEND (per-chat aware) =================
def send_to_telegram(data, source="sky"):
    cfg = load_config()

    source_channels = cfg.get(f"{source}_channels", [])
    common_channels = cfg.get("channels", [])
    targets = source_channels or common_channels or [int(os.getenv("POST_CHAT_ID", "0"))]

    for chat_id in targets:
        # Per-chat overrides (fallback to global)
        cmd      = get_chat_override(cfg, chat_id, f"{source}_cmd",      cfg.get(f"{source}_cmd", "/l3"))
        tag_user = get_chat_override(cfg, chat_id, "tag_username",        cfg.get("tag_username", "@username"))
        tag_id   = get_chat_override(cfg, chat_id, "tag_id",              cfg.get("tag_id", 0))
        tag_line = f"Tag: {tag_user} {tag_id}"
        message  = f"{cmd} {data['link']} -n {data['title']}\n{tag_line}"
        try:
            bot.send_message(chat_id, message)
        except Exception as e:
            print(f"Send error to {chat_id}: {e}")

    increment_stat(source)

# ================= SITE IMPORTS =================
# Sky/HDM/EF/FF ka pura code sites/ folder mein hai. Import yahan, end mein,
# kyunki sites/*.py modules upar wale 'from bot import ...' karte hain — by
# is point tak load_config, clean_title, fetch_title_via_jina, HEADERS,
# send_to_telegram sab define ho chuke hain (no circular import issue).
from sites.sky import (
    get_sky_posts, extract_sky_link,
    extract_gofile_link, extract_gdflix_sky_link, extract_hubcloud_sky_link,
)
from sites.hdm import get_hdm_posts, get_hdm_links, extract_gdflix_data
from sites.ef import get_ef_posts, get_ef_linkshub_links, get_ef_hubcloud, get_ef_final_links
from sites.ff import get_ff_posts, get_ff_links, parse_size, FF_LINK_PATTERNS

# ================= HELP PAGES =================
HELP_PAGES = [
    (
        "RSS Bot (1/4) — Sources\n\n"
        "MANUAL CHECK:\n"
        "/sky -l  /hdm -l  /ef -l  /ff -l\n\n"
        "ENABLE/DISABLE:\n"
        "/sky on|off\n"
        "/hdm on|off\n"
        "/ef on|off\n"
        "/ff on|off\n\n"
        "DOMAIN:\n"
        "/setsky URL\n"
        "/sethdm RSS_URL\n"
        "/setef URL\n"
        "/setff URL\n\n"
        "INTERVAL:\n"
        "/settime 900"
    ),
    (
        "RSS Bot (2/4) — Channels & Tags\n\n"
        "Common (fallback):\n"
        "/setchat ID | /addchat ID\n\n"
        "Per-source:\n"
        "/setskychat | /addskychat | /removeskychat\n"
        "/sethdmchat | /addhdmchat | /removehdmchat\n"
        "/setefchat  | /addefchat  | /removeefchat\n"
        "/setffchat  | /addffchat  | /removeffchat\n\n"
        "/channels — list dekho\n\n"
        "TAG (global):\n"
        "/settag @username\n"
        "/settagid 123456789\n\n"
        "TAG (per-channel):\n"
        "/settag @xyz -chatid -100xxx\n"
        "/settagid 99999 -chatid -100xxx"
    ),
    (
        "RSS Bot (3/4) — CMD & Extractor\n\n"
        "CMD PREFIX (global):\n"
        "/setskycmd /l3\n"
        "/sethdmcmd /l3\n"
        "/setefcmd /l3\n"
        "/setffcmd /l3\n\n"
        "CMD PREFIX (per-chat):\n"
        "/setskycmd /l2 -chatid -100xxx\n"
        "/sethdmcmd /l2 -chatid -100xxx\n"
        "(same for ef, ff)\n\n"
        "EXTRACTOR (global or per-chat):\n"
        "/setextractor gofile|gdflix|hubcloud\n"
        "/setextractor hubcloud -chatid -100xxx\n"
        "/setefextractor hubcloud|all\n"
        "/setffextractor gofile|hubcloud|...\n\n"
        "FF SIZE:\n"
        "/setfflimit 4096"
    ),
    (
        "RSS Bot (4/4) — Captions\n\n"
        "SET FORMAT (global):\n"
        "/setskymovie FORMAT\n"
        "/setskyseries FORMAT\n"
        "/sethdmmovie FORMAT  /sethdmseries FORMAT\n"
        "/setefmovie  FORMAT  /setefseries  FORMAT\n"
        "/setffmovie  FORMAT  /setffseries  FORMAT\n\n"
        "SET FORMAT (per-channel):\n"
        "/setskymovie FORMAT -chatid -100xxx\n"
        "(same for all others)\n\n"
        "Placeholders:\n"
        "{title} {year} {quality} {language}\n"
        "{source} {codec} {season} {episode}\n"
        "{complete}/{combine} {esub}\n\n"
        "/setcompleteword Combine\n"
        "(change 'Complete' to any word)\n\n"
        "/replace -skyseries {complete} {combine}\n"
        "(placeholder rename in saved format)\n\n"
        "/showcaption | /resetcaption\n"
        "/testcaption <title>\n\n"
        "INFO:\n"
        "/settings | /status | /stats\n"
        "/latestsky|hdm|ef|ff"
    ),
]

# ================= COMMANDS =================

@bot.message_handler(commands=["start", "help"])
def cmd_help(message):
    if not is_admin(message): return
    markup = telebot.types.InlineKeyboardMarkup()
    markup.add(telebot.types.InlineKeyboardButton("Next >>", callback_data="help_1"))
    bot.send_message(message.chat.id, HELP_PAGES[0], reply_markup=markup)

@bot.callback_query_handler(func=lambda c: c.data.startswith("help_"))
def cb_help(call):
    page = int(call.data.split("_")[1])
    markup = telebot.types.InlineKeyboardMarkup(row_width=2)
    btns = []
    if page > 0:
        btns.append(telebot.types.InlineKeyboardButton("<< Back", callback_data=f"help_{page-1}"))
    if page < len(HELP_PAGES) - 1:
        btns.append(telebot.types.InlineKeyboardButton("Next >>", callback_data=f"help_{page+1}"))
    if btns: markup.add(*btns)
    bot.edit_message_text(HELP_PAGES[page], call.message.chat.id,
                          call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

def _toggle(message, key, name):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2: return
    cfg = load_config()
    if p[1].lower() == "on":  cfg[key] = True;  save_config(cfg); bot.reply_to(message, f"{name} ON")
    elif p[1].lower() == "off": cfg[key] = False; save_config(cfg); bot.reply_to(message, f"{name} OFF")

@bot.message_handler(commands=["sky"])
def cmd_sky(message):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2: return
    if p[1] == "-l":
        bot.reply_to(message, "Sky check shuru...")
        threading.Thread(target=run_sky_check, args=(message.chat.id,), daemon=True).start()
    else: _toggle(message, "sky_enabled", "SkyMovies")

@bot.message_handler(commands=["hdm"])
def cmd_hdm(message):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2: return
    if p[1] == "-l":
        bot.reply_to(message, "HDM check shuru...")
        threading.Thread(target=run_hdm_check, args=(message.chat.id,), daemon=True).start()
    else: _toggle(message, "hdm_enabled", "HDMovie2")

@bot.message_handler(commands=["ef"])
def cmd_ef(message):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2: return
    if p[1] == "-l":
        bot.reply_to(message, "EF check shuru...")
        threading.Thread(target=run_ef_check, args=(message.chat.id,), daemon=True).start()
    else: _toggle(message, "ef_enabled", "ExtraFlix")

@bot.message_handler(commands=["ff"])
def cmd_ff(message):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2: return
    if p[1] == "-l":
        bot.reply_to(message, "FF check shuru...")
        threading.Thread(target=run_ff_check, args=(message.chat.id,), daemon=True).start()
    else: _toggle(message, "ff_enabled", "FilmyFly")

@bot.message_handler(commands=["setsky"])
def cmd_setsky(m):
    if not is_admin(m): return
    p = m.text.strip().split(maxsplit=1)
    if len(p) < 2: return
    cfg = load_config(); cfg["sky_domain"] = p[1].strip(); save_config(cfg)
    bot.reply_to(m, f"Sky: {p[1].strip()}")

@bot.message_handler(commands=["sethdm"])
def cmd_sethdm(m):
    if not is_admin(m): return
    p = m.text.strip().split(maxsplit=1)
    if len(p) < 2: return
    cfg = load_config(); cfg["hdm_rss"] = p[1].strip(); save_config(cfg)
    bot.reply_to(m, f"HDM RSS: {p[1].strip()}")

@bot.message_handler(commands=["setef"])
def cmd_setef(m):
    if not is_admin(m): return
    p = m.text.strip().split(maxsplit=1)
    if len(p) < 2: return
    cfg = load_config(); cfg["ef_url"] = p[1].strip(); save_config(cfg)
    bot.reply_to(m, f"EF URL: {p[1].strip()}")

@bot.message_handler(commands=["setff"])
def cmd_setff(m):
    if not is_admin(m): return
    p = m.text.strip().split(maxsplit=1)
    if len(p) < 2: return
    cfg = load_config(); cfg["ff_url"] = p[1].strip(); save_config(cfg)
    bot.reply_to(m, f"FF URL: {p[1].strip()}")

@bot.message_handler(commands=["settime"])
def cmd_settime(m):
    if not is_admin(m): return
    p = m.text.strip().split()
    if len(p) < 2 or not p[1].isdigit(): return
    cfg = load_config(); cfg["interval"] = int(p[1]); save_config(cfg)
    bot.reply_to(m, f"Interval: {p[1]}s")

# --- Channel helpers ---
def _parse_chatid_flag(parts):
    """Return (main_args, chat_id_or_None)"""
    if "-chatid" in parts:
        idx = parts.index("-chatid")
        if idx + 1 < len(parts):
            return parts[:idx], int(parts[idx+1])
    return parts, None

def _add_channel(m, key, name):
    if not is_admin(m): return
    p = m.text.strip().split()
    if len(p) < 2: bot.reply_to(m, f"Usage: {p[0]} -100xxx"); return
    cfg = load_config(); cid = int(p[1])
    if cid not in cfg[key]: cfg[key].append(cid); save_config(cfg); bot.reply_to(m, f"{name} added: {p[1]}")
    else: bot.reply_to(m, "Already hai.")

def _set_channel(m, key, name):
    if not is_admin(m): return
    p = m.text.strip().split()
    if len(p) < 2: bot.reply_to(m, f"Usage: {p[0]} -100xxx"); return
    cfg = load_config(); cfg[key] = [int(p[1])]; save_config(cfg)
    bot.reply_to(m, f"{name} set: {p[1]}")

def _remove_channel(m, key, name):
    if not is_admin(m): return
    p = m.text.strip().split()
    if len(p) < 2: bot.reply_to(m, f"Usage: {p[0]} -100xxx"); return
    cfg = load_config(); cid = int(p[1])
    if cid in cfg[key]: cfg[key].remove(cid); save_config(cfg); bot.reply_to(m, f"{name} removed: {p[1]}")
    else: bot.reply_to(m, "Nahi mila.")

@bot.message_handler(commands=["setchat"])
def h1(m): _set_channel(m, "channels", "Common")
@bot.message_handler(commands=["addchat"])
def h2(m): _add_channel(m, "channels", "Common")
@bot.message_handler(commands=["setskychat"])
def h3(m): _set_channel(m, "sky_channels", "Sky")
@bot.message_handler(commands=["addskychat"])
def h4(m): _add_channel(m, "sky_channels", "Sky")
@bot.message_handler(commands=["removeskychat"])
def h5(m): _remove_channel(m, "sky_channels", "Sky")
@bot.message_handler(commands=["sethdmchat"])
def h6(m): _set_channel(m, "hdm_channels", "HDM")
@bot.message_handler(commands=["addhdmchat"])
def h7(m): _add_channel(m, "hdm_channels", "HDM")
@bot.message_handler(commands=["removehdmchat"])
def h8(m): _remove_channel(m, "hdm_channels", "HDM")
@bot.message_handler(commands=["setefchat"])
def h9(m): _set_channel(m, "ef_channels", "EF")
@bot.message_handler(commands=["addefchat"])
def h10(m): _add_channel(m, "ef_channels", "EF")
@bot.message_handler(commands=["removeefchat"])
def h11(m): _remove_channel(m, "ef_channels", "EF")
@bot.message_handler(commands=["setffchat"])
def h12(m): _set_channel(m, "ff_channels", "FF")
@bot.message_handler(commands=["addffchat"])
def h13(m): _add_channel(m, "ff_channels", "FF")
@bot.message_handler(commands=["removeffchat"])
def h14(m): _remove_channel(m, "ff_channels", "FF")

@bot.message_handler(commands=["channels"])
def cmd_channels(m):
    if not is_admin(m): return
    cfg = load_config()
    def fmt(lst): return ", ".join(str(c) for c in lst) if lst else "None"
    bot.reply_to(m, (
        f"Channels:\n"
        f"Sky:    {fmt(cfg.get('sky_channels',[]))}\n"
        f"HDM:    {fmt(cfg.get('hdm_channels',[]))}\n"
        f"EF:     {fmt(cfg.get('ef_channels',[]))}\n"
        f"FF:     {fmt(cfg.get('ff_channels',[]))}\n"
        f"Common: {fmt(cfg.get('channels',[]))}"
    ))

@bot.message_handler(commands=["settag"])
def cmd_settag(m):
    if not is_admin(m): return
    p = m.text.strip().split()
    if len(p) < 2: bot.reply_to(m, "Usage: /settag @xyz [-chatid -100xxx]"); return
    p, chat_id = _parse_chatid_flag(p)
    cfg = load_config()
    if chat_id:
        set_chat_override(cfg, chat_id, "tag_username", p[1]); save_config(cfg)
        bot.reply_to(m, f"Tag for {chat_id}: {p[1]}")
    else:
        cfg["tag_username"] = p[1]; save_config(cfg)
        bot.reply_to(m, f"Tag (global): {p[1]}")

@bot.message_handler(commands=["settagid"])
def cmd_settagid(m):
    if not is_admin(m): return
    p = m.text.strip().split()
    if len(p) < 2: bot.reply_to(m, "Usage: /settagid 123456 [-chatid -100xxx]"); return
    p, chat_id = _parse_chatid_flag(p)
    cfg = load_config()
    if chat_id:
        set_chat_override(cfg, chat_id, "tag_id", int(p[1])); save_config(cfg)
        bot.reply_to(m, f"Tag ID for {chat_id}: {p[1]}")
    else:
        cfg["tag_id"] = int(p[1]); save_config(cfg)
        bot.reply_to(m, f"Tag ID (global): {p[1]}")

# --- CMD per-chat support ---
def _set_cmd(m, source):
    if not is_admin(m): return
    p = m.text.strip().split()
    if len(p) < 2: bot.reply_to(m, f"Usage: /set{source}cmd /l3 [-chatid -100xxx]"); return
    p, chat_id = _parse_chatid_flag(p)
    cmd_val = p[1]
    cfg = load_config()
    if chat_id:
        set_chat_override(cfg, chat_id, f"{source}_cmd", cmd_val)
        save_config(cfg)
        bot.reply_to(m, f"{source.upper()} cmd for {chat_id}: {cmd_val}")
    else:
        cfg[f"{source}_cmd"] = cmd_val; save_config(cfg)
        bot.reply_to(m, f"{source.upper()} cmd (global): {cmd_val}")

@bot.message_handler(commands=["setskycmd"])
def cmd_setskycmd(m): _set_cmd(m, "sky")
@bot.message_handler(commands=["sethdmcmd"])
def cmd_sethdmcmd(m): _set_cmd(m, "hdm")
@bot.message_handler(commands=["setefcmd"])
def cmd_setefcmd(m): _set_cmd(m, "ef")
@bot.message_handler(commands=["setffcmd"])
def cmd_setffcmd(m): _set_cmd(m, "ff")

# --- Extractors ---
def _set_extractor(m, cfg_key, valid, name):
    if not is_admin(m): return
    p = m.text.strip().split()
    if len(p) < 2 or p[1].lower() not in valid:
        bot.reply_to(m, f"Usage: {p[0]} {'|'.join(valid)} [-chatid -100xxx]"); return
    p, chat_id = _parse_chatid_flag(p)
    val = p[1].lower()
    cfg = load_config()
    if chat_id:
        set_chat_override(cfg, chat_id, cfg_key, val); save_config(cfg)
        bot.reply_to(m, f"{name} extractor for {chat_id}: {val}")
    else:
        cfg[cfg_key] = val; save_config(cfg)
        bot.reply_to(m, f"{name} extractor (global): {val}")

@bot.message_handler(commands=["setextractor"])
def cmd_setextractor(m): _set_extractor(m, "sky_extractor", ["gofile","gdflix","hubcloud"], "Sky")

@bot.message_handler(commands=["setefextractor"])
def cmd_setefextractor(m): _set_extractor(m, "ef_extractor", ["hubcloud","all"], "EF")

@bot.message_handler(commands=["setffextractor"])
def cmd_setffextractor(m): _set_extractor(m, "ff_extractor", list(FF_LINK_PATTERNS.keys()) + ["all"], "FF")

@bot.message_handler(commands=["setfflimit"])
def cmd_setfflimit(m):
    if not is_admin(m): return
    p = m.text.strip().split()
    if len(p) < 2 or not p[1].isdigit(): bot.reply_to(m, "Usage: /setfflimit 4096"); return
    cfg = load_config(); cfg["ff_size_limit_mb"] = int(p[1]); save_config(cfg)
    bot.reply_to(m, f"FF limit: {p[1]} MB")

# --- Captions ---
SAMPLE_MOVIE  = {"title":"Movie","year":"2026","quality":"1080p","language":"Hindi",
                 "source":"WEB-DL","codec":"x265","season":"","episode":"","complete":"","esub":"Esub"}
SAMPLE_SERIES = {"title":"Show","year":"2026","quality":"1080p","language":"Hindi",
                 "source":"WEB-DL","codec":"x265","season":"Season 1","episode":"EP01-02","complete":"Complete","esub":"Esub"}

def _set_cap(m, key, sample):
    if not is_admin(m): return
    text = m.text.strip()
    # -chatid flag support: /setskymovie FORMAT -chatid -100xxx
    chat_id = None
    ci_match = re.search(r'-chatid\s+(-?\d+)', text)
    if ci_match:
        chat_id = int(ci_match.group(1))
        text = text[:ci_match.start()].strip()
    p = text.split(maxsplit=1)
    if len(p) < 2: bot.reply_to(m, "Format daalna zaroori hai.\nOptional: -chatid -100xxx"); return
    fmt_val = p[1].strip()
    cfg = load_config()
    if chat_id:
        set_chat_override(cfg, chat_id, key, fmt_val); save_config(cfg)
        bot.reply_to(m, f"Saved for {chat_id}!\nPreview: {apply_caption(sample, fmt_val)}")
    else:
        cfg[key] = fmt_val; save_config(cfg)
        bot.reply_to(m, f"Saved (global)!\nPreview: {apply_caption(sample, fmt_val)}")

@bot.message_handler(commands=["setskymovie"])
def c1(m): _set_cap(m, "sky_movie_caption", SAMPLE_MOVIE)
@bot.message_handler(commands=["setskyseries"])
def c2(m): _set_cap(m, "sky_series_caption", SAMPLE_SERIES)
@bot.message_handler(commands=["sethdmmovie"])
def c3(m): _set_cap(m, "hdm_movie_caption", SAMPLE_MOVIE)
@bot.message_handler(commands=["sethdmseries"])
def c4(m): _set_cap(m, "hdm_series_caption", SAMPLE_SERIES)
@bot.message_handler(commands=["setefmovie"])
def c5(m): _set_cap(m, "ef_movie_caption", SAMPLE_MOVIE)
@bot.message_handler(commands=["setefseries"])
def c6(m): _set_cap(m, "ef_series_caption", SAMPLE_SERIES)
@bot.message_handler(commands=["setffmovie"])
def c7(m): _set_cap(m, "ff_movie_caption", SAMPLE_MOVIE)
@bot.message_handler(commands=["setffseries"])
def c8(m): _set_cap(m, "ff_series_caption", SAMPLE_SERIES)

@bot.message_handler(commands=["showcaption"])
def cmd_showcaption(m):
    if not is_admin(m): return
    cfg = load_config()
    bot.reply_to(m, (
        f"Captions:\n\n"
        f"Sky Movie:\n{cfg.get('sky_movie_caption', DEFAULT_SKY_MOVIE)}\n\n"
        f"Sky Series:\n{cfg.get('sky_series_caption', DEFAULT_SKY_SERIES)}\n\n"
        f"HDM Movie:\n{cfg.get('hdm_movie_caption', DEFAULT_HDM_MOVIE)}\n\n"
        f"HDM Series:\n{cfg.get('hdm_series_caption', DEFAULT_HDM_SERIES)}\n\n"
        f"EF Movie:\n{cfg.get('ef_movie_caption', DEFAULT_EF_MOVIE)}\n\n"
        f"EF Series:\n{cfg.get('ef_series_caption', DEFAULT_EF_SERIES)}\n\n"
        f"FF Movie:\n{cfg.get('ff_movie_caption', DEFAULT_FF_MOVIE)}\n\n"
        f"FF Series:\n{cfg.get('ff_series_caption', DEFAULT_FF_SERIES)}"
    ))

@bot.message_handler(commands=["resetcaption"])
def cmd_resetcaption(m):
    if not is_admin(m): return
    cfg = load_config()
    cfg.update({
        "sky_movie_caption": DEFAULT_SKY_MOVIE, "sky_series_caption": DEFAULT_SKY_SERIES,
        "hdm_movie_caption": DEFAULT_HDM_MOVIE, "hdm_series_caption": DEFAULT_HDM_SERIES,
        "ef_movie_caption":  DEFAULT_EF_MOVIE,  "ef_series_caption":  DEFAULT_EF_SERIES,
        "ff_movie_caption":  DEFAULT_FF_MOVIE,  "ff_series_caption":  DEFAULT_FF_SERIES,
    })
    save_config(cfg); bot.reply_to(m, "All captions reset!")

@bot.message_handler(commands=["testcaption"])
def cmd_testcaption(m):
    if not is_admin(m): return
    p = m.text.strip().split(maxsplit=1)
    if len(p) < 2: bot.reply_to(m, "Usage: /testcaption Movie (2026) 1080p BluRay Hindi"); return
    parts = parse_title(p[1].strip())
    detail = "\n".join([f"{k}: {v}" for k, v in parts.items() if v])
    bot.reply_to(m, (
        f"Parsed:\n{detail}\n\n"
        f"Sky:  {apply_caption(parts, get_fmt('sky', parts))}\n"
        f"HDM:  {apply_caption(parts, get_fmt('hdm', parts))}\n"
        f"EF:   {apply_caption(parts, get_fmt('ef', parts))}\n"
        f"FF:   {apply_caption(parts, get_fmt('ff', parts))}"
    ))


# ================= /replace command =================
_REPLACE_KEY_MAP = {
    "-skymovie":  "sky_movie_caption",
    "-skyseries": "sky_series_caption",
    "-hdmmovie":  "hdm_movie_caption",
    "-hdmseries": "hdm_series_caption",
    "-efmovie":   "ef_movie_caption",
    "-efseries":  "ef_series_caption",
    "-ffmovie":   "ff_movie_caption",
    "-ffseries":  "ff_series_caption",
}

@bot.message_handler(commands=["replace"])
def cmd_replace(m):
    if not is_admin(m): return
    # Usage: /replace -skyseries {complete} {combine}
    # or:   /replace -skyseries {complete} {combine} -chatid -100xxx
    p = m.text.strip().split()
    usage = (
        "Usage: /replace -<target> {old} {new}\n"
        "Targets: -skymovie -skyseries -hdmmovie -hdmseries\n"
        "         -efmovie -efseries -ffmovie -ffseries\n\n"
        "Example:\n"
        "/replace -skyseries {complete} {combine}\n"
        "/replace -efmovie {source} {codec}\n\n"
        "Optional per-channel: add -chatid -100xxx at end"
    )
    if len(p) < 4:
        bot.reply_to(m, usage); return

    target = p[1].lower()
    if target not in _REPLACE_KEY_MAP:
        bot.reply_to(m, f"Unknown target: {target}\n\n" + usage); return

    old_word = p[2]
    new_word = p[3]

    # -chatid support
    chat_id = None
    if "-chatid" in p:
        idx = p.index("-chatid")
        if idx + 1 < len(p):
            try: chat_id = int(p[idx + 1])
            except: bot.reply_to(m, "Invalid chatid"); return

    cfg_key = _REPLACE_KEY_MAP[target]
    cfg = load_config()

    if chat_id:
        # per-channel: get current override or global
        current = get_chat_override(cfg, chat_id, cfg_key, cfg.get(cfg_key, ""))
        updated = current.replace(old_word, new_word)
        if updated == current:
            bot.reply_to(m, f"'{old_word}' nahi mila caption mein:\n{current}"); return
        set_chat_override(cfg, chat_id, cfg_key, updated)
        save_config(cfg)
        bot.reply_to(m, f"Done (channel {chat_id})!\n\nBefore:\n{current}\n\nAfter:\n{updated}")
    else:
        current = cfg.get(cfg_key, "")
        updated = current.replace(old_word, new_word)
        if updated == current:
            bot.reply_to(m, f"'{old_word}' nahi mila caption mein:\n{current}"); return
        cfg[cfg_key] = updated
        save_config(cfg)
        bot.reply_to(m, f"Done (global)!\n\nBefore:\n{current}\n\nAfter:\n{updated}")

@bot.message_handler(commands=["setcompleteword"])
def cmd_setcompleteword(m):
    if not is_admin(m): return
    p = m.text.strip().split(maxsplit=1)
    if len(p) < 2: bot.reply_to(m, "Usage: /setcompleteword Combine\nDefault: Complete\nAlias {combine} bhi kaam karta hai"); return
    cfg = load_config(); cfg["complete_word"] = p[1].strip(); save_config(cfg)
    bot.reply_to(m, f"Complete word set: {p[1].strip()}\n(Use {{complete}} or {{combine}} in caption format)")

@bot.message_handler(commands=["settings"])
def cmd_settings(m):
    if not is_admin(m): return
    cfg = load_config()
    bot.reply_to(m, (
        f"Settings\n\n"
        f"Sky: {cfg['sky_domain']} ({'ON' if cfg['sky_enabled'] else 'OFF'})\n"
        f"HDM: {cfg['hdm_rss']} ({'ON' if cfg['hdm_enabled'] else 'OFF'})\n"
        f"EF:  {cfg.get('ef_url')} ({'ON' if cfg.get('ef_enabled') else 'OFF'})\n"
        f"FF:  {cfg.get('ff_url')} ({'ON' if cfg.get('ff_enabled') else 'OFF'})\n\n"
        f"Interval: {cfg['interval']}s\n"
        f"Tag: {cfg['tag_username']} {cfg['tag_id']}\n"
        f"Sky ext: {cfg.get('sky_extractor','gofile')}\n"
        f"EF ext:  {cfg.get('ef_extractor','hubcloud')}\n"
        f"FF ext:  {cfg.get('ff_extractor','all')}\n"
        f"FF limit:{cfg.get('ff_size_limit_mb',4096)}MB\n"
        f"CMDs: sky={cfg.get('sky_cmd','/l3')} hdm={cfg.get('hdm_cmd','/l3')} "
        f"ef={cfg.get('ef_cmd','/l3')} ff={cfg.get('ff_cmd','/l3')}"
    ))

@bot.message_handler(commands=["status"])
def cmd_status(m):
    if not is_admin(m): return
    cfg = load_config()
    def ft(t):
        if not t: return "Never"
        d = int(time.time()-t); return f"{d}s ago" if d<60 else f"{d//60}m ago"
    def fn(t):
        if not t: return "?"
        d = int(t-time.time())
        if d<=0: return "Now"
        return f"{d}s" if d<60 else f"{d//60}m"
    bot.reply_to(m, (
        f"Status\n\n"
        f"Sky  last:{ft(last_check['sky'])}  next:{fn(next_check['sky'])}\n"
        f"HDM  last:{ft(last_check['hdm'])}  next:{fn(next_check['hdm'])}\n"
        f"EF   last:{ft(last_check['ef'])}   next:{fn(next_check['ef'])}\n"
        f"FF   last:{ft(last_check['ff'])}   next:{fn(next_check['ff'])}\n"
        f"Interval: {cfg['interval']}s"
    ))

@bot.message_handler(commands=["stats"])
def cmd_stats(m):
    if not is_admin(m): return
    s = load_stats()
    bot.reply_to(m, (
        f"Stats ({s.get('date','?')})\n\n"
        f"Sky:      {s.get('sky',0)}\n"
        f"HDMovie2: {s.get('hdm',0)}\n"
        f"ExtraFlix:{s.get('ef',0)}\n"
        f"FilmyFly: {s.get('ff',0)}\n"
        f"Total: {sum(s.get(k,0) for k in ['sky','hdm','ef','ff'])}"
    ))

@bot.message_handler(commands=["latestsky"])
def cmd_latestsky(m):
    if not is_admin(m): return
    try:
        posts = get_sky_posts()[:5]
        bot.reply_to(m, "Latest Sky:\n\n" + "\n".join(f"- {p['title']}\n{p['url']}" for p in posts) if posts else "Koi post nahi.")
    except Exception as e: bot.reply_to(m, f"Error: {e}")

@bot.message_handler(commands=["latesthdm"])
def cmd_latesthdm(m):
    if not is_admin(m): return
    try:
        posts = get_hdm_posts()[:5]
        bot.reply_to(m, "Latest HDM:\n\n" + "\n".join(f"- {p['title']}\n{p['url']}" for p in posts) if posts else "Koi post nahi.")
    except Exception as e: bot.reply_to(m, f"Error: {e}")

@bot.message_handler(commands=["latestef"])
def cmd_latestef(m):
    if not is_admin(m): return
    try:
        posts = get_ef_posts()[:5]
        bot.reply_to(m, "Latest EF:\n\n" + "\n".join(f"- {p['title']}\n{p['url']}" for p in posts) if posts else "Koi post nahi.")
    except Exception as e: bot.reply_to(m, f"Error: {e}")

@bot.message_handler(commands=["latestff"])
def cmd_latestff(m):
    if not is_admin(m): return
    try:
        posts = get_ff_posts()[:5]
        bot.reply_to(m, "Latest FF:\n\n" + "\n".join(f"- {p['title']}\n{p['url']}" for p in posts) if posts else "Koi post nahi.")
    except Exception as e: bot.reply_to(m, f"Error: {e}")

# ================= RUNNERS =================
def run_sky_check(notify=None):
    seen = load_seen(); count = 0
    try:
        for post in reversed(get_sky_posts()):
            if post["url"] in seen: continue
            data = extract_sky_link(post["url"])
            if data: send_to_telegram(data, "sky"); count += 1
            seen.add(post["url"]); save_seen(seen); time.sleep(2)
        if notify: bot.send_message(notify, f"Sky done. {count} sent.")
    except Exception as e:
        if notify: bot.send_message(notify, f"Sky error: {e}")

def run_hdm_check(notify=None):
    seen = load_seen(); count = 0
    try:
        for post in reversed(get_hdm_posts()):
            if post["url"] in seen: continue
            links = get_hdm_links(post["url"])
            files = []
            for item in links: files.extend(extract_gdflix_data(item["url"]))
            unique = list({x["link"]: x for x in files}.values())
            for f in unique: send_to_telegram(f, "hdm"); count += 1; time.sleep(2)
            seen.add(post["url"]); save_seen(seen)
        if notify: bot.send_message(notify, f"HDM done. {count} sent.")
    except Exception as e:
        if notify: bot.send_message(notify, f"HDM error: {e}")

def run_ef_check(notify=None):
    seen = load_seen(); count = 0
    cfg = load_config()
    extractor = cfg.get("ef_extractor", "hubcloud")
    try:
        for post in reversed(get_ef_posts()):
            if post["url"] in seen: continue
            files = get_ef_final_links(post["url"], post["title"], extractor)
            for f in files: send_to_telegram(f, "ef"); count += 1; time.sleep(2)
            seen.add(post["url"]); save_seen(seen)
        if notify: bot.send_message(notify, f"EF done. {count} sent.")
    except Exception as e:
        if notify: bot.send_message(notify, f"EF error: {e}")

def run_ff_check(notify=None):
    seen = load_seen(); count = 0
    try:
        for post in reversed(get_ff_posts()):
            if post["url"] in seen: continue
            files = get_ff_links(post["url"])
            for f in files: send_to_telegram(f, "ff"); count += 1; time.sleep(2)
            seen.add(post["url"]); save_seen(seen)
        if notify: bot.send_message(notify, f"FF done. {count} sent.")
    except Exception as e:
        if notify: bot.send_message(notify, f"FF error: {e}")

# ================= MAIN =================
def main():
    print("Bot Started...")
    threading.Thread(target=bot.infinity_polling, daemon=True).start()
    seen = load_seen()

    while True:
        cfg = load_config()
        interval = cfg.get("interval", 900)
        try:
            if cfg.get("sky_enabled", True):
                last_check["sky"] = time.time()
                for post in reversed(get_sky_posts()):
                    if post["url"] in seen: continue
                    data = extract_sky_link(post["url"])
                    if data: send_to_telegram(data, "sky"); print("[SKY]", data["title"])
                    seen.add(post["url"]); save_seen(seen); time.sleep(3)

            if cfg.get("hdm_enabled", True):
                last_check["hdm"] = time.time()
                for post in reversed(get_hdm_posts()):
                    if post["url"] in seen: continue
                    links = get_hdm_links(post["url"])
                    files = []
                    for item in links: files.extend(extract_gdflix_data(item["url"]))
                    unique = list({x["link"]: x for x in files}.values())
                    for f in unique: send_to_telegram(f, "hdm"); print("[HDM]", f["title"]); time.sleep(2)
                    seen.add(post["url"]); save_seen(seen)

            if cfg.get("ef_enabled", True):
                last_check["ef"] = time.time()
                extractor = cfg.get("ef_extractor", "hubcloud")
                for post in reversed(get_ef_posts()):
                    if post["url"] in seen: continue
                    files = get_ef_final_links(post["url"], post["title"], extractor)
                    for f in files: send_to_telegram(f, "ef"); print("[EF]", f["title"]); time.sleep(2)
                    seen.add(post["url"]); save_seen(seen)

            if cfg.get("ff_enabled", True):
                last_check["ff"] = time.time()
                for post in reversed(get_ff_posts()):
                    if post["url"] in seen: continue
                    files = get_ff_links(post["url"])
                    for f in files: send_to_telegram(f, "ff"); print("[FF]", f["title"]); time.sleep(2)
                    seen.add(post["url"]); save_seen(seen)

        except Exception as e:
            print("MAIN ERROR:", e)

        next_check["sky"] = next_check["hdm"] = next_check["ef"] = next_check["ff"] = time.time() + interval
        print(f"Sleeping {interval}s...")
        time.sleep(interval)

if __name__ == "__main__":
    main()
