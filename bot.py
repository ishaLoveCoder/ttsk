# -*- coding: utf-8 -*-

import re
import json
import time
import os
import threading
import requests
import telebot
import feedparser
from datetime import date
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
ADMIN_ID  = int(os.getenv("ADMIN_ID", "0"))

CONFIG_FILE = "config.json"
DB_FILE     = "seen_posts.json"
STATS_FILE  = "stats.json"

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)  # parse_mode=None — plain text, no HTML errors

HEADERS = {"User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile)"}

# ================= CONFIG =================
def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except:
        return {
            "sky_domain": "https://skymovieshd.free/",
            "hdm_rss": "https://hdmovie2.org.uk/movies/feed/",
            "ef_url": "https://e3.extraflix.mobi/",
            "interval": 900,
            "tag_username": "@username",
            "tag_id": 123456789,
            "channels": [],
            "sky_enabled": True,
            "hdm_enabled": True,
            "ef_enabled": True,
            "sky_extractor": "gofile",
            "sky_cmd": "/l3",
            "hdm_cmd": "/l3",
            "ef_cmd": "/l3",
            "sky_movie_caption": "{title} ({year}) {quality} {language} {source} {codec} {esub}.mkv",
            "sky_series_caption": "{title} ({year}) {season} {episode} {complete} {quality} {language} {source} {codec} {esub}.mkv",
            "hdm_movie_caption": "{title} ({year}) {quality} {language} {source} {codec} {esub}.mkv",
            "hdm_series_caption": "{title} ({year}) {season} {episode} {complete} {quality} {language} {source} {codec} {esub}.mkv",
            "ef_movie_caption": "{title} {esub}.mkv",
        }

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

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
        return {"date": str(date.today()), "sky": 0, "hdm": 0, "ef": 0}

def save_stats(s):
    with open(STATS_FILE, "w") as f:
        json.dump(s, f)

def increment_stat(source):
    s = load_stats()
    today = str(date.today())
    if s.get("date") != today:
        s = {"date": today, "sky": 0, "hdm": 0, "ef": 0}
    s[source] = s.get(source, 0) + 1
    save_stats(s)

# ================= TRACKER =================
last_check = {"sky": None, "hdm": None, "ef": None}
next_check = {"sky": None, "hdm": None, "ef": None}

# ================= ADMIN =================
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
    raw = re.sub(r'\[.*?\]|\(.*?Audio.*?\)', '', raw, flags=re.I).strip()
    raw = re.sub(r'[-_. ]*ExtraFlix\.Pw', '', raw, flags=re.I).strip()
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

    p['complete'] = 'Complete' if re.search(r'\bcomplete\b', raw, re.I) else ''
    p['esub'] = 'Esub'

    if y:
        title_part = raw[:y.start()].strip().rstrip('.-\u2013 ')
    elif q:
        title_part = raw[:q.start()].strip().rstrip('.-\u2013 ')
    else:
        title_part = raw
    p['title'] = title_part.strip()

    return p


DEFAULT_SKY_MOVIE   = "{title} ({year}) {quality} {language} {source} {codec} {esub}.mkv"
DEFAULT_SKY_SERIES  = "{title} ({year}) {season} {episode} {complete} {quality} {language} {source} {codec} {esub}.mkv"
DEFAULT_HDM_MOVIE   = "{title} ({year}) {quality} {language} {source} {codec} {esub}.mkv"
DEFAULT_HDM_SERIES  = "{title} ({year}) {season} {episode} {complete} {quality} {language} {source} {codec} {esub}.mkv"
DEFAULT_EF_MOVIE    = "{title} {esub}.mkv"


def apply_caption(parts, fmt):
    result = fmt
    for k, v in parts.items():
        result = result.replace('{' + k + '}', v)
    # Empty brackets/spaces fix
    result = re.sub(r'\(\s*\)', '', result)
    result = re.sub(r'\s{2,}', ' ', result).strip()
    result = re.sub(r'\s+\.mkv$', '.mkv', result)
    return result


def get_fmt(source, parts):
    cfg = load_config()
    is_series = bool(parts.get('season') or parts.get('episode') or parts.get('complete'))
    if source == "sky":
        return cfg.get("sky_series_caption" if is_series else "sky_movie_caption",
                       DEFAULT_SKY_SERIES if is_series else DEFAULT_SKY_MOVIE)
    elif source == "hdm":
        return cfg.get("hdm_series_caption" if is_series else "hdm_movie_caption",
                       DEFAULT_HDM_SERIES if is_series else DEFAULT_HDM_MOVIE)
    else:  # ef
        return cfg.get("ef_movie_caption", DEFAULT_EF_MOVIE)


def clean_title(raw, source="sky"):
    p = parse_title(raw)
    return apply_caption(p, get_fmt(source, p))


# ================= SKYMOVIES =================
def get_sky_posts():
    cfg = load_config()
    HEADERS["Referer"] = cfg["sky_domain"]
    r = requests.get(cfg["sky_domain"], headers=HEADERS, timeout=20)
    soup = BeautifulSoup(r.text, "lxml")
    posts = []
    seen_urls = set()
    for a in soup.select("div.Fmvideo a[href*='movie/']"):
        href = a.get("href", "").strip()
        title = a.get_text(" ", strip=True)
        if not href or not title:
            continue
        full_url = urljoin(cfg["sky_domain"], href)
        if full_url not in seen_urls:
            seen_urls.add(full_url)
            posts.append({"title": title, "url": full_url})
    return posts


def _sky_title_from_html(html):
    m = re.search(r"<div class='Robiul'>\s*Download\s*(.*?)</div>", html, re.S | re.I)
    if m:
        return BeautifulSoup(m.group(1), "lxml").get_text(" ", strip=True)
    m2 = re.search(r"<title>\s*(.*?)\s*(?:Full Movie Download|Download)", html, re.I)
    return m2.group(1).strip() if m2 else "Unknown Movie"


def _sky_protected_html(html, movie_url):
    gd = re.search(r'<a href=[\'"]([^\'"]+)[\'"]>\s*Google Drive Direct Links\s*</a>', html, re.I)
    if not gd:
        gd = re.search(r'<a href=[\'"]([^\'"]+)[\'"][^>]*>(?:Download Now|V-Cloud|HubCloud|Direct Links?)</a>', html, re.I)
    if not gd:
        return None, None
    r2 = requests.get(gd.group(1).strip(),
                      headers={"User-Agent": HEADERS["User-Agent"], "Referer": movie_url},
                      timeout=20, allow_redirects=True)
    return r2.text, r2.url


def extract_gofile_link(movie_url):
    cfg = load_config(); HEADERS["Referer"] = cfg["sky_domain"]
    r = requests.get(movie_url, headers=HEADERS, timeout=20)
    raw_title = _sky_title_from_html(r.text)
    ph, _ = _sky_protected_html(r.text, movie_url)
    if not ph: return None
    m = re.findall(r'https?://(?:www\.)?gofile\.io/d/[A-Za-z0-9]+', ph, re.I)
    return {"title": clean_title(raw_title, "sky"), "link": m[0].strip()} if m else None


def extract_gdflix_link(movie_url):
    cfg = load_config(); HEADERS["Referer"] = cfg["sky_domain"]
    r = requests.get(movie_url, headers=HEADERS, timeout=20)
    raw_title = _sky_title_from_html(r.text)
    ph, _ = _sky_protected_html(r.text, movie_url)
    if not ph: return None
    for pat in [r'https?://gdflix\.[^\s"\'<>]+', r'https?://gdlink\.[^\s"\'<>]+']:
        m = re.findall(pat, ph, re.I)
        if m: return {"title": clean_title(raw_title, "sky"), "link": m[0].strip()}
    return None


def extract_hubcloud_link(movie_url):
    cfg = load_config(); HEADERS["Referer"] = cfg["sky_domain"]
    r = requests.get(movie_url, headers=HEADERS, timeout=20)
    raw_title = _sky_title_from_html(r.text)
    ph, rurl = _sky_protected_html(r.text, movie_url)
    if not ph: return None
    for pat in [r'https?://hubcloud\.[^\s"\']+/drive/[A-Za-z0-9]+',
                r'https?://(?:www\.)?hubcloud\.[^\s"\']+/drive/[A-Za-z0-9]+']:
        m = re.findall(pat, ph, re.I)
        if m: return {"title": clean_title(raw_title, "sky"), "link": max(m, key=len).strip()}
    if rurl and "hubcloud" in rurl.lower():
        return {"title": clean_title(raw_title, "sky"), "link": rurl.strip()}
    return None


def extract_sky_link(movie_url):
    ext = load_config().get("sky_extractor", "gofile").lower()
    if ext == "gdflix": return extract_gdflix_link(movie_url)
    if ext == "hubcloud": return extract_hubcloud_link(movie_url)
    return extract_gofile_link(movie_url)


# ================= HDMOVIE2 =================
def get_hdm_posts():
    cfg = load_config()
    feed = feedparser.parse(cfg["hdm_rss"])
    return [{"title": item.title, "url": item.link} for item in feed.entries]


def get_hdm_links(movie_url):
    try:
        r = requests.get(movie_url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        return [{"label": a.get_text(" ", strip=True), "url": a["href"]}
                for a in soup.find_all("a", href=True) if "hdm.im" in a["href"]]
    except Exception as e:
        print("HDM ERROR:", e); return []


def extract_gdflix_data(hdm_url):
    try:
        r = requests.get(hdm_url, headers=HEADERS, allow_redirects=True, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        final = []
        for a in soup.find_all("a", href=True):
            if "gdflix" not in a["href"].lower(): continue
            try:
                r2 = requests.get(a["href"], headers=HEADERS, allow_redirects=True, timeout=20)
                tm = re.search(r"<title>(.*?)</title>", r2.text, re.I)
                if not tm: continue
                final.append({"title": clean_title(tm.group(1), "hdm"), "link": r2.url})
            except Exception as e:
                print("GD ERROR:", e)
        return final
    except Exception as e:
        print("FINAL ERROR:", e); return []


# ================= EXTRAFLIX =================
def get_ef_posts():
    cfg = load_config()
    r = requests.get(cfg.get("ef_url", "https://e3.extraflix.mobi/"),
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")
    movies = []
    for article in soup.select("article"):
        if "category-movies" not in article.get("class", []): continue
        a = article.select_one("h2.entry-title a")
        if a: movies.append({"title": a.get_text(strip=True), "url": a["href"]})
    return movies


def get_ef_linkshub(movie_url):
    r = requests.get(movie_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    return re.findall(r'https://links\.linkshub\.fun/view/[A-Za-z0-9]+', r.text)


def get_ef_hubcloud(ls_url):
    r = requests.get(ls_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    html = r.text
    hub = re.search(r'https://hubcloud\.foo/drive/[A-Za-z0-9]+', html)
    title = re.search(r'<title>(.*?)</title>', html, re.I | re.S)
    if not hub: return None
    raw = title.group(1).strip() if title else "Movie.mkv"
    return hub.group(0), clean_title(raw, "ef")


# ================= SEND =================
def send_to_telegram(data, source="sky"):
    cfg = load_config()
    channels = cfg.get("channels", [])
    tag_line = f"Tag: {cfg['tag_username']} {cfg['tag_id']}"
    cmd = cfg.get(f"{source}_cmd", "/l2")
    message = f"{cmd} {data['link']} -n {data['title']}\n{tag_line}"
    targets = channels if channels else [int(os.getenv("POST_CHAT_ID", "0"))]
    for chat_id in targets:
        try:
            bot.send_message(chat_id, message)
        except Exception as e:
            print(f"Send error: {e}")
    increment_stat(source)


# ================= HELP PAGES =================
HELP_PAGES = [
    # Page 1
    (
        "RSS Bot Commands (1/3)\n\n"
        "MANUAL CHECK:\n"
        "/sky -l  — SkyMovies instant check\n"
        "/hdm -l  — HDMovie2 instant check\n"
        "/ef -l   — ExtraFlix instant check\n\n"
        "ENABLE/DISABLE:\n"
        "/sky on|off\n"
        "/hdm on|off\n"
        "/ef on|off\n\n"
        "DOMAIN CHANGE:\n"
        "/setsky https://newdomain.com/\n"
        "/sethdm https://newrss.com/feed/\n"
        "/setef https://newdomain.com/\n\n"
        "INTERVAL:\n"
        "/settime 300   (5 min)\n"
        "/settime 1800  (30 min)"
    ),
    # Page 2
    (
        "RSS Bot Commands (2/3)\n\n"
        "CHANNEL:\n"
        "/setchat -100xxxxxxxx\n"
        "/addchat -100xxxxxxxx\n\n"
        "TAG:\n"
        "/settag @username\n"
        "/settagid 123456789\n\n"
        "CMD PREFIX:\n"
        "/setskycmd /l2\n"
        "/sethdmcmd /l2\n"
        "/setefcmd /l4\n\n"
        "EXTRACTOR (Sky):\n"
        "/setextractor gofile\n"
        "/setextractor gdflix\n"
        "/setextractor hubcloud\n\n"
        "INFO:\n"
        "/settings\n"
        "/status\n"
        "/stats"
    ),
    # Page 3
    (
        "RSS Bot Commands (3/3)\n\n"
        "CAPTION FORMAT:\n"
        "/setskymovie {title} ({year}) ...\n"
        "/setskyseries {title} ({year}) ...\n"
        "/sethdmmovie {title} ({year}) ...\n"
        "/sethdmseries {title} ({year}) ...\n"
        "/setefcaption {title} {esub}.mkv\n\n"
        "/showcaption  — all formats\n"
        "/resetcaption — reset to default\n\n"
        "Placeholders:\n"
        "{title} {year} {quality} {language}\n"
        "{source} {codec} {season} {episode}\n"
        "{complete} {esub}\n\n"
        "TEST:\n"
        "/testcaption Krampus (2015) 720p BluRay\n\n"
        "PREVIEW:\n"
        "/latestsky\n"
        "/latesthdm\n"
        "/latestef"
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
    markup.add(*btns)
    bot.edit_message_text(HELP_PAGES[page], call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)


@bot.message_handler(commands=["sky"])
def cmd_sky(message):
    if not is_admin(message): return
    parts = message.text.strip().split(); cfg = load_config()
    if len(parts) < 2: return
    arg = parts[1].lower()
    if arg == "on":   cfg["sky_enabled"] = True;  save_config(cfg); bot.reply_to(message, "SkyMovies ON")
    elif arg == "off": cfg["sky_enabled"] = False; save_config(cfg); bot.reply_to(message, "SkyMovies OFF")
    elif arg == "-l":
        bot.reply_to(message, "SkyMovies instant check shuru...")
        threading.Thread(target=run_sky_check, args=(message.chat.id,), daemon=True).start()


@bot.message_handler(commands=["hdm"])
def cmd_hdm(message):
    if not is_admin(message): return
    parts = message.text.strip().split(); cfg = load_config()
    if len(parts) < 2: return
    arg = parts[1].lower()
    if arg == "on":   cfg["hdm_enabled"] = True;  save_config(cfg); bot.reply_to(message, "HDMovie2 ON")
    elif arg == "off": cfg["hdm_enabled"] = False; save_config(cfg); bot.reply_to(message, "HDMovie2 OFF")
    elif arg == "-l":
        bot.reply_to(message, "HDMovie2 instant check shuru...")
        threading.Thread(target=run_hdm_check, args=(message.chat.id,), daemon=True).start()


@bot.message_handler(commands=["ef"])
def cmd_ef(message):
    if not is_admin(message): return
    parts = message.text.strip().split(); cfg = load_config()
    if len(parts) < 2: return
    arg = parts[1].lower()
    if arg == "on":   cfg["ef_enabled"] = True;  save_config(cfg); bot.reply_to(message, "ExtraFlix ON")
    elif arg == "off": cfg["ef_enabled"] = False; save_config(cfg); bot.reply_to(message, "ExtraFlix OFF")
    elif arg == "-l":
        bot.reply_to(message, "ExtraFlix instant check shuru...")
        threading.Thread(target=run_ef_check, args=(message.chat.id,), daemon=True).start()


@bot.message_handler(commands=["setsky"])
def cmd_setsky(message):
    if not is_admin(message): return
    p = message.text.strip().split(maxsplit=1)
    if len(p) < 2: bot.reply_to(message, "Usage: /setsky https://domain.com/"); return
    cfg = load_config(); cfg["sky_domain"] = p[1].strip(); save_config(cfg)
    bot.reply_to(message, f"Sky domain: {cfg['sky_domain']}")


@bot.message_handler(commands=["sethdm"])
def cmd_sethdm(message):
    if not is_admin(message): return
    p = message.text.strip().split(maxsplit=1)
    if len(p) < 2: bot.reply_to(message, "Usage: /sethdm https://rss.com/feed/"); return
    cfg = load_config(); cfg["hdm_rss"] = p[1].strip(); save_config(cfg)
    bot.reply_to(message, f"HDM RSS: {cfg['hdm_rss']}")


@bot.message_handler(commands=["setef"])
def cmd_setef(message):
    if not is_admin(message): return
    p = message.text.strip().split(maxsplit=1)
    if len(p) < 2: bot.reply_to(message, "Usage: /setef https://domain.com/"); return
    cfg = load_config(); cfg["ef_url"] = p[1].strip(); save_config(cfg)
    bot.reply_to(message, f"ExtraFlix URL: {cfg['ef_url']}")


@bot.message_handler(commands=["settime"])
def cmd_settime(message):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2 or not p[1].isdigit(): bot.reply_to(message, "Usage: /settime 900"); return
    cfg = load_config(); cfg["interval"] = int(p[1]); save_config(cfg)
    bot.reply_to(message, f"Interval: {cfg['interval']}s")


@bot.message_handler(commands=["setchat"])
def cmd_setchat(message):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2: bot.reply_to(message, "Usage: /setchat -100xxxxxxxx"); return
    cfg = load_config(); cfg["channels"] = [int(p[1])]; save_config(cfg)
    bot.reply_to(message, f"Channel set: {p[1]}")


@bot.message_handler(commands=["addchat"])
def cmd_addchat(message):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2: bot.reply_to(message, "Usage: /addchat -100xxxxxxxx"); return
    cfg = load_config(); cid = int(p[1])
    if cid not in cfg["channels"]:
        cfg["channels"].append(cid); save_config(cfg)
        bot.reply_to(message, f"Channel added: {p[1]}")
    else:
        bot.reply_to(message, "Already list mein hai.")


@bot.message_handler(commands=["settag"])
def cmd_settag(message):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2: bot.reply_to(message, "Usage: /settag @username"); return
    cfg = load_config(); cfg["tag_username"] = p[1]; save_config(cfg)
    bot.reply_to(message, f"Tag: {p[1]}")


@bot.message_handler(commands=["settagid"])
def cmd_settagid(message):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2: bot.reply_to(message, "Usage: /settagid 123456789"); return
    cfg = load_config(); cfg["tag_id"] = int(p[1]); save_config(cfg)
    bot.reply_to(message, f"Tag ID: {p[1]}")


@bot.message_handler(commands=["setskycmd"])
def cmd_setskycmd(message):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2: bot.reply_to(message, "Usage: /setskycmd /l2"); return
    cfg = load_config(); cfg["sky_cmd"] = p[1]; save_config(cfg)
    bot.reply_to(message, f"Sky cmd: {p[1]}")


@bot.message_handler(commands=["sethdmcmd"])
def cmd_sethdmcmd(message):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2: bot.reply_to(message, "Usage: /sethdmcmd /l2"); return
    cfg = load_config(); cfg["hdm_cmd"] = p[1]; save_config(cfg)
    bot.reply_to(message, f"HDM cmd: {p[1]}")


@bot.message_handler(commands=["setefcmd"])
def cmd_setefcmd(message):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2: bot.reply_to(message, "Usage: /setefcmd /l4"); return
    cfg = load_config(); cfg["ef_cmd"] = p[1]; save_config(cfg)
    bot.reply_to(message, f"EF cmd: {p[1]}")


@bot.message_handler(commands=["setextractor"])
def cmd_setextractor(message):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2 or p[1].lower() not in ["gofile","gdflix","hubcloud"]:
        bot.reply_to(message, "Usage: /setextractor gofile|gdflix|hubcloud"); return
    cfg = load_config(); cfg["sky_extractor"] = p[1].lower(); save_config(cfg)
    bot.reply_to(message, f"Extractor: {p[1].lower()}")


# ---- Caption commands ----
def _set_caption(message, key, default, sample):
    if not is_admin(message): return
    p = message.text.strip().split(maxsplit=1)
    if len(p) < 2: bot.reply_to(message, f"Usage: /{message.text.split()[0][1:]} FORMAT"); return
    cfg = load_config(); cfg[key] = p[1].strip(); save_config(cfg)
    preview = apply_caption(sample, p[1].strip())
    bot.reply_to(message, f"Saved!\nPreview: {preview}")

SAMPLE_MOVIE  = {"title":"Movie","year":"2026","quality":"1080p","language":"Hindi","source":"WEB-DL","codec":"x265","season":"","episode":"","complete":"","esub":"Esub"}
SAMPLE_SERIES = {"title":"Show","year":"2026","quality":"1080p","language":"Hindi","source":"WEB-DL","codec":"x265","season":"Season 1","episode":"EP01-02","complete":"Complete","esub":"Esub"}
SAMPLE_EF     = {"title":"Movie Name","year":"","quality":"","language":"","source":"","codec":"","season":"","episode":"","complete":"","esub":"Esub"}

@bot.message_handler(commands=["setskymovie"])
def cmd_setskymovie(m):
    _set_caption(m, "sky_movie_caption", DEFAULT_SKY_MOVIE, SAMPLE_MOVIE)

@bot.message_handler(commands=["setskyseries"])
def cmd_setskyseries(m):
    _set_caption(m, "sky_series_caption", DEFAULT_SKY_SERIES, SAMPLE_SERIES)

@bot.message_handler(commands=["sethdmmovie"])
def cmd_sethdmmovie(m):
    _set_caption(m, "hdm_movie_caption", DEFAULT_HDM_MOVIE, SAMPLE_MOVIE)

@bot.message_handler(commands=["sethdmseries"])
def cmd_sethdmseries(m):
    _set_caption(m, "hdm_series_caption", DEFAULT_HDM_SERIES, SAMPLE_SERIES)

@bot.message_handler(commands=["setefcaption"])
def cmd_setefcaption(m):
    _set_caption(m, "ef_movie_caption", DEFAULT_EF_MOVIE, SAMPLE_EF)


@bot.message_handler(commands=["showcaption"])
def cmd_showcaption(message):
    if not is_admin(message): return
    cfg = load_config()
    text = (
        "Caption Formats:\n\n"
        f"Sky Movie:\n{cfg.get('sky_movie_caption', DEFAULT_SKY_MOVIE)}\n\n"
        f"Sky Series:\n{cfg.get('sky_series_caption', DEFAULT_SKY_SERIES)}\n\n"
        f"HDM Movie:\n{cfg.get('hdm_movie_caption', DEFAULT_HDM_MOVIE)}\n\n"
        f"HDM Series:\n{cfg.get('hdm_series_caption', DEFAULT_HDM_SERIES)}\n\n"
        f"ExtraFlix:\n{cfg.get('ef_movie_caption', DEFAULT_EF_MOVIE)}"
    )
    bot.reply_to(message, text)


@bot.message_handler(commands=["resetcaption"])
def cmd_resetcaption(message):
    if not is_admin(message): return
    cfg = load_config()
    cfg.update({
        "sky_movie_caption": DEFAULT_SKY_MOVIE, "sky_series_caption": DEFAULT_SKY_SERIES,
        "hdm_movie_caption": DEFAULT_HDM_MOVIE, "hdm_series_caption": DEFAULT_HDM_SERIES,
        "ef_movie_caption": DEFAULT_EF_MOVIE,
    })
    save_config(cfg)
    bot.reply_to(message, "All captions reset!")


@bot.message_handler(commands=["testcaption"])
def cmd_testcaption(message):
    if not is_admin(message): return
    p = message.text.strip().split(maxsplit=1)
    if len(p) < 2:
        bot.reply_to(message, "Usage: /testcaption Krampus (2015) 720p BluRay Hindi x265"); return
    parts = parse_title(p[1].strip())
    sky_out = apply_caption(parts, get_fmt("sky", parts))
    hdm_out = apply_caption(parts, get_fmt("hdm", parts))
    ef_out  = apply_caption(parts, get_fmt("ef", parts))
    detail = "\n".join([f"{k}: {v}" for k, v in parts.items() if v])
    bot.reply_to(message, f"Parsed:\n{detail}\n\nSky: {sky_out}\nHDM: {hdm_out}\nEF:  {ef_out}")


@bot.message_handler(commands=["settings"])
def cmd_settings(message):
    if not is_admin(message): return
    cfg = load_config()
    ch = ", ".join(str(c) for c in cfg["channels"]) or "Default"
    bot.reply_to(message, (
        f"Settings\n\n"
        f"Sky: {cfg['sky_domain']} ({'ON' if cfg['sky_enabled'] else 'OFF'})\n"
        f"HDM: {cfg['hdm_rss']} ({'ON' if cfg['hdm_enabled'] else 'OFF'})\n"
        f"EF:  {cfg.get('ef_url','?')} ({'ON' if cfg.get('ef_enabled') else 'OFF'})\n"
        f"Interval: {cfg['interval']}s\n"
        f"Tag: {cfg['tag_username']} {cfg['tag_id']}\n"
        f"Channels: {ch}\n"
        f"Extractor: {cfg.get('sky_extractor','gofile')}\n"
        f"Sky cmd: {cfg.get('sky_cmd','/l2')} | HDM: {cfg.get('hdm_cmd','/l2')} | EF: {cfg.get('ef_cmd','/l4')}"
    ))


@bot.message_handler(commands=["status"])
def cmd_status(message):
    if not is_admin(message): return
    cfg = load_config()
    def ft(t):
        if not t: return "Never"
        d = int(time.time()-t); return f"{d}s ago" if d<60 else f"{d//60}m ago"
    def fn(t):
        if not t: return "?"
        d = int(t-time.time())
        if d<=0: return "Now"
        return f"{d}s" if d<60 else f"{d//60}m"
    bot.reply_to(message, (
        f"Status\n\n"
        f"Sky last: {ft(last_check['sky'])} | next: {fn(next_check['sky'])}\n"
        f"HDM last: {ft(last_check['hdm'])} | next: {fn(next_check['hdm'])}\n"
        f"EF last:  {ft(last_check['ef'])}  | next: {fn(next_check['ef'])}\n"
        f"Interval: {cfg['interval']}s"
    ))


@bot.message_handler(commands=["stats"])
def cmd_stats(message):
    if not is_admin(message): return
    s = load_stats()
    bot.reply_to(message, (
        f"Today Stats ({s.get('date','?')})\n\n"
        f"Sky:      {s.get('sky',0)}\n"
        f"HDMovie2: {s.get('hdm',0)}\n"
        f"ExtraFlix:{s.get('ef',0)}\n\n"
        f"Total: {s.get('sky',0)+s.get('hdm',0)+s.get('ef',0)}"
    ))


@bot.message_handler(commands=["latestsky"])
def cmd_latestsky(message):
    if not is_admin(message): return
    try:
        posts = get_sky_posts()[:5]
        if not posts: bot.reply_to(message, "Koi post nahi."); return
        text = "Latest Sky (preview):\n\n" + "\n".join(f"- {p['title']}\n{p['url']}" for p in posts)
        bot.reply_to(message, text)
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")


@bot.message_handler(commands=["latesthdm"])
def cmd_latesthdm(message):
    if not is_admin(message): return
    try:
        posts = get_hdm_posts()[:5]
        if not posts: bot.reply_to(message, "Koi post nahi."); return
        text = "Latest HDM (preview):\n\n" + "\n".join(f"- {p['title']}\n{p['url']}" for p in posts)
        bot.reply_to(message, text)
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")


@bot.message_handler(commands=["latestef"])
def cmd_latestef(message):
    if not is_admin(message): return
    try:
        posts = get_ef_posts()[:5]
        if not posts: bot.reply_to(message, "Koi post nahi."); return
        text = "Latest ExtraFlix (preview):\n\n" + "\n".join(f"- {p['title']}\n{p['url']}" for p in posts)
        bot.reply_to(message, text)
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")


# ================= CHECK RUNNERS =================
def run_sky_check(notify_chat=None):
    seen = load_seen()
    try:
        count = 0
        for post in reversed(get_sky_posts()):
            if post["url"] in seen: continue
            data = extract_sky_link(post["url"])
            if data: send_to_telegram(data, "sky"); count += 1
            seen.add(post["url"]); save_seen(seen); time.sleep(2)
        if notify_chat: bot.send_message(notify_chat, f"Sky done. {count} sent.")
    except Exception as e:
        if notify_chat: bot.send_message(notify_chat, f"Sky error: {e}")


def run_hdm_check(notify_chat=None):
    seen = load_seen()
    try:
        count = 0
        for post in reversed(get_hdm_posts()):
            if post["url"] in seen: continue
            links = get_hdm_links(post["url"])
            files = []
            for item in links: files.extend(extract_gdflix_data(item["url"]))
            unique = list({x["link"]: x for x in files}.values())
            for f in unique: send_to_telegram(f, "hdm"); count += 1; time.sleep(2)
            seen.add(post["url"]); save_seen(seen)
        if notify_chat: bot.send_message(notify_chat, f"HDM done. {count} sent.")
    except Exception as e:
        if notify_chat: bot.send_message(notify_chat, f"HDM error: {e}")


def run_ef_check(notify_chat=None):
    seen = load_seen()
    try:
        count = 0
        for post in reversed(get_ef_posts()):
            if post["url"] in seen: continue
            for ls in get_ef_linkshub(post["url"]):
                data = get_ef_hubcloud(ls)
                if not data: continue
                hub_link, filename = data
                send_to_telegram({"link": hub_link, "title": filename}, "ef")
                count += 1; time.sleep(2)
            seen.add(post["url"]); save_seen(seen)
        if notify_chat: bot.send_message(notify_chat, f"EF done. {count} sent.")
    except Exception as e:
        if notify_chat: bot.send_message(notify_chat, f"EF error: {e}")


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
                    print("[SKY]", post["title"])
                    data = extract_sky_link(post["url"])
                    if data: send_to_telegram(data, "sky"); print("[SKY] Sent:", data["title"])
                    seen.add(post["url"]); save_seen(seen); time.sleep(3)

            if cfg.get("hdm_enabled", True):
                last_check["hdm"] = time.time()
                for post in reversed(get_hdm_posts()):
                    if post["url"] in seen: continue
                    print("[HDM]", post["title"])
                    links = get_hdm_links(post["url"])
                    files = []
                    for item in links: files.extend(extract_gdflix_data(item["url"]))
                    unique = list({x["link"]: x for x in files}.values())
                    for f in unique: send_to_telegram(f, "hdm"); print("[HDM] Sent:", f["title"]); time.sleep(2)
                    seen.add(post["url"]); save_seen(seen)

            if cfg.get("ef_enabled", True):
                last_check["ef"] = time.time()
                for post in reversed(get_ef_posts()):
                    if post["url"] in seen: continue
                    print("[EF]", post["title"])
                    for ls in get_ef_linkshub(post["url"]):
                        data = get_ef_hubcloud(ls)
                        if not data: continue
                        hub_link, filename = data
                        send_to_telegram({"link": hub_link, "title": filename}, "ef")
                        print("[EF] Sent:", filename); time.sleep(2)
                    seen.add(post["url"]); save_seen(seen)

        except Exception as e:
            print("MAIN ERROR:", e)

        next_check["sky"] = next_check["hdm"] = next_check["ef"] = time.time() + interval
        print(f"Sleeping {interval}s...")
        time.sleep(interval)


if __name__ == "__main__":
    main()
