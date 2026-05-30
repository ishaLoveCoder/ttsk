# -*- coding: utf-8 -*-

import re
import json
import time
import os
import threading
import requests
import telebot
import feedparser
from datetime import datetime, date
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# ================= CONFIG =================
BOT_TOKEN  = os.getenv("BOT_TOKEN")
ADMIN_ID   = int(os.getenv("ADMIN_ID", "0"))

CONFIG_FILE = "config.json"
DB_FILE     = "seen_posts.json"
STATS_FILE  = "stats.json"

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile)",
}

# ================= CONFIG HELPERS =================
def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except:
        return {
            "sky_domain": "https://skymovieshd.free/",
            "hdm_rss": "https://hdmovie2.org.uk/movies/feed/",
            "interval": 900,
            "tag_username": "@username",
            "tag_id": 123456789,
            "channels": [],
            "sky_enabled": True,
            "hdm_enabled": True,
            "sky_extractor": "gofile",
            "sky_movie_caption": "{title} ({year}) {quality} {language} {source} {codec} {esub}.mkv",
            "sky_series_caption": "{title} ({year}) {season} {episode} {complete} {quality} {language} {source} {codec} {esub}.mkv",
            "hdm_movie_caption": "{title} ({year}) {quality} {language} {source} {codec} {esub}.mkv",
            "hdm_series_caption": "{title} ({year}) {season} {episode} {complete} {quality} {language} {source} {codec} {esub}.mkv",
        }

def save_config(cfg):
    with open(CONFIG_FILE, "w") as f:
        json.dump(cfg, f, indent=2)

# ================= DATABASE =================
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
        return {"date": str(date.today()), "sky": 0, "hdm": 0}

def save_stats(stats):
    with open(STATS_FILE, "w") as f:
        json.dump(stats, f)

def increment_stat(source):
    stats = load_stats()
    today = str(date.today())
    if stats.get("date") != today:
        stats = {"date": today, "sky": 0, "hdm": 0}
    stats[source] = stats.get(source, 0) + 1
    save_stats(stats)

# ================= LAST CHECK TRACKER =================
last_check = {"sky": None, "hdm": None}
next_check = {"sky": None, "hdm": None}

# ================= ADMIN CHECK =================
def is_admin(message):
    return message.from_user.id == ADMIN_ID

# ================= TITLE PARSER =================
def parse_title(raw):
    raw = re.sub(r'^GDFlix\s*\|\s*', '', raw, flags=re.I).strip()
    raw = re.sub(r'\s*\[www\.[^\]]+\]\s*', ' ', raw, flags=re.I).strip()
    raw = re.sub(r'^Download\s+', '', raw, flags=re.I).strip()
    raw = re.sub(r'\s*\[[^\]]*(?:MB|GB)[^\]]*\]', '', raw, flags=re.I).strip()
    raw = re.sub(r'\.(mkv|mp4|avi)$', '', raw, flags=re.I).strip()
    raw = re.sub(r'\s+-\s+-\s+', ' ', raw).strip()
    raw = re.sub(r'\[Dual Audio\]', '', raw, flags=re.I).strip()
    raw = re.sub(r'\[.*?\]', '', raw).strip()
    raw = re.sub(r'\(.*?Audio.*?\)', '', raw, flags=re.I).strip()
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


DEFAULT_SKY_MOVIE_CAPTION   = "{title} ({year}) {quality} {language} {source} {codec} {esub}.mkv"
DEFAULT_SKY_SERIES_CAPTION  = "{title} ({year}) {season} {episode} {complete} {quality} {language} {source} {codec} {esub}.mkv"
DEFAULT_HDM_MOVIE_CAPTION   = "{title} ({year}) {quality} {language} {source} {codec} {esub}.mkv"
DEFAULT_HDM_SERIES_CAPTION  = "{title} ({year}) {season} {episode} {complete} {quality} {language} {source} {codec} {esub}.mkv"


def apply_caption_format(parts, fmt):
    result = fmt
    for key, val in parts.items():
        result = result.replace('{' + key + '}', val)
    # Empty fields ki wajah se aane wale extra spaces/brackets clean karo
    result = re.sub(r'\(\s*\)', '', result)          # () hata do
    result = re.sub(r'\s{2,}', ' ', result).strip()  # double spaces
    result = re.sub(r'\s+\.mkv$', '.mkv', result)    # space before .mkv
    result = re.sub(r'\s+,', ',', result)
    return result


def get_caption_fmt(source, parts):
    """source=sky/hdm, parts dict se movie/series decide karke format lo"""
    cfg = load_config()
    is_series = bool(parts.get('season') or parts.get('episode') or parts.get('complete'))
    if source == "sky":
        if is_series:
            return cfg.get("sky_series_caption", DEFAULT_SKY_SERIES_CAPTION)
        return cfg.get("sky_movie_caption", DEFAULT_SKY_MOVIE_CAPTION)
    else:
        if is_series:
            return cfg.get("hdm_series_caption", DEFAULT_HDM_SERIES_CAPTION)
        return cfg.get("hdm_movie_caption", DEFAULT_HDM_MOVIE_CAPTION)


def clean_title(raw, source="sky"):
    parts = parse_title(raw)
    fmt = get_caption_fmt(source, parts)
    return apply_caption_format(parts, fmt)


# ================= SKYMOVIES =================
def get_sky_posts():
    cfg = load_config()
    HEADERS["Referer"] = cfg["sky_domain"]
    r = requests.get(cfg["sky_domain"], headers=HEADERS, timeout=20)
    soup = BeautifulSoup(r.text, "lxml")
    posts = []
    for a in soup.select("div.Fmvideo a[href*='movie/']"):
        href = a.get("href", "").strip()
        title = a.get_text(" ", strip=True)
        if not href or not title:
            continue
        full_url = urljoin(cfg["sky_domain"], href)
        if full_url not in [x["url"] for x in posts]:
            posts.append({"title": title, "url": full_url, "source": "sky"})
    return posts


def _extract_sky_title(html):
    m = re.search(r"<div class='Robiul'>\s*Download\s*(.*?)</div>", html, re.S | re.I)
    if m:
        return BeautifulSoup(m.group(1), "lxml").get_text(" ", strip=True)
    m2 = re.search(r"<title>\s*(.*?)\s*(?:Full Movie Download|Download)", html, re.I)
    return m2.group(1).strip() if m2 else "Unknown Movie"


def _get_protected_html(html, movie_url):
    gd = re.search(r'<a href=[\'"]([^\'"]+)[\'"]>\s*Google Drive Direct Links\s*</a>', html, re.I)
    if not gd:
        gd = re.search(r'<a href=[\'"]([^\'"]+)[\'"][^>]*>(?:Download Now|V-Cloud|HubCloud|Direct Links?)</a>', html, re.I)
    if not gd:
        return None, None
    protected_url = gd.group(1).strip()
    r2 = requests.get(protected_url, headers={"User-Agent": HEADERS["User-Agent"], "Referer": movie_url},
                      timeout=20, allow_redirects=True)
    return r2.text, r2.url


def extract_gofile_link(movie_url):
    cfg = load_config()
    HEADERS["Referer"] = cfg["sky_domain"]
    r = requests.get(movie_url, headers=HEADERS, timeout=20)
    html = r.text
    raw_title = _extract_sky_title(html)
    protected_html, _ = _get_protected_html(html, movie_url)
    if not protected_html:
        return None
    matches = re.findall(r'https?://(?:www\.)?gofile\.io/d/[A-Za-z0-9]+', protected_html, re.I)
    if not matches:
        return None
    return {"title": clean_title(raw_title, "sky"), "link": matches[0].strip()}


def extract_gdflix_link(movie_url):
    cfg = load_config()
    HEADERS["Referer"] = cfg["sky_domain"]
    r = requests.get(movie_url, headers=HEADERS, timeout=20)
    html = r.text
    raw_title = _extract_sky_title(html)
    protected_html, _ = _get_protected_html(html, movie_url)
    if not protected_html:
        return None
    for pattern in [r'https?://gdflix\.[^\s"\'<>]+', r'https?://gdlink\.[^\s"\'<>]+']:
        matches = re.findall(pattern, protected_html, re.I)
        if matches:
            return {"title": clean_title(raw_title, "sky"), "link": matches[0].strip()}
    return None


def extract_hubcloud_link(movie_url):
    cfg = load_config()
    HEADERS["Referer"] = cfg["sky_domain"]
    r = requests.get(movie_url, headers=HEADERS, timeout=20)
    html = r.text
    raw_title = _extract_sky_title(html)
    protected_html, redirect_url = _get_protected_html(html, movie_url)
    if not protected_html:
        return None
    for pattern in [
        r'https?://hubcloud\.[^\s"\']+/drive/[A-Za-z0-9]+',
        r'https?://(?:www\.)?hubcloud\.[^\s"\']+/drive/[A-Za-z0-9]+'
    ]:
        matches = re.findall(pattern, protected_html, re.I)
        if matches:
            return {"title": clean_title(raw_title, "sky"), "link": max(matches, key=len).strip()}
    if redirect_url and "hubcloud" in redirect_url.lower():
        return {"title": clean_title(raw_title, "sky"), "link": redirect_url.strip()}
    return None


def extract_sky_link(movie_url):
    """Config ke hisaab se sahi extractor use karo"""
    cfg = load_config()
    extractor = cfg.get("sky_extractor", "gofile").lower()
    if extractor == "gdflix":
        return extract_gdflix_link(movie_url)
    elif extractor == "hubcloud":
        return extract_hubcloud_link(movie_url)
    else:
        return extract_gofile_link(movie_url)


# ================= HDMOVIE2 =================
def get_hdm_posts():
    cfg = load_config()
    feed = feedparser.parse(cfg["hdm_rss"])
    return [{"title": item.title, "url": item.link, "source": "hdmovie2"} for item in feed.entries]

def get_hdm_links(movie_url):
    try:
        r = requests.get(movie_url, headers=HEADERS, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            if "hdm.im" in a["href"]:
                links.append({"label": a.get_text(" ", strip=True), "url": a["href"]})
        return links
    except Exception as e:
        print("HDM ERROR:", e)
        return []

def extract_gdflix_data(hdm_url):
    try:
        r = requests.get(hdm_url, headers=HEADERS, allow_redirects=True, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        final = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "gdflix" not in href.lower():
                continue
            try:
                r2 = requests.get(href, headers=HEADERS, allow_redirects=True, timeout=20)
                final_url = r2.url
                title_match = re.search(r"<title>(.*?)</title>", r2.text, re.I)
                if not title_match:
                    continue
                raw_title = title_match.group(1)
                final.append({"title": clean_title(raw_title, "hdm"), "link": final_url})
            except Exception as e:
                print("GD ERROR:", e)
        return final
    except Exception as e:
        print("FINAL ERROR:", e)
        return []

# ================= TELEGRAM SEND =================
def send_to_telegram(data, source="sky"):
    cfg = load_config()
    channels = cfg.get("channels", [])
    tag_line = f"Tag: {cfg['tag_username']} {cfg['tag_id']}"
    message = f"/l2 {data['link']} -n {data['title']}\n{tag_line}"
    targets = channels if channels else [int(os.getenv("POST_CHAT_ID", "0"))]
    for chat_id in targets:
        try:
            bot.send_message(chat_id, message)
        except Exception as e:
            print(f"Send error to {chat_id}:", e)
    increment_stat(source)

# ================= COMMANDS =================

@bot.message_handler(commands=["start", "help"])
def cmd_help(message):
    if not is_admin(message): return
    # NOTE: parse_mode=HTML mein <title> jaisi tags error deti hain
    # isliye yahan plain text bhej rahe hain
    text = (
        "RSS Bot Commands\n\n"
        "Manual Check:\n"
        "/sky -l — SkyMovies instant check\n"
        "/hdm -l — HDMovie2 instant check\n\n"
        "Domain Change:\n"
        "/setsky https://newdomain.com/\n"
        "/sethdm https://newrss.com/feed/\n\n"
        "Interval:\n"
        "/settime 300 — 5 min\n"
        "/settime 1800 — 30 min\n\n"
        "Enable/Disable:\n"
        "/sky on | /sky off\n"
        "/hdm on | /hdm off\n\n"
        "Channel:\n"
        "/setchat -100xxxxxxxx\n"
        "/addchat -100xxxxxxxx\n\n"
        "Tag:\n"
        "/settag @username\n"
        "/settagid 123456789\n\n"
        "Extractor (Sky):\n"
        "/setextractor gofile\n"
        "/setextractor gdflix\n"
        "/setextractor hubcloud\n\n"
        "Caption (Sky):\n"
        "/setskymovie {title} ({year}) ...\n"
        "/setskyseries {title} ({year}) ...\n\n"
        "Caption (HDM):\n"
        "/sethdmmovie {title} ({year}) ...\n"
        "/sethdmseries {title} ({year}) ...\n\n"
        "Info:\n"
        "/settings\n"
        "/status\n"
        "/stats\n"
        "/latestsky\n"
        "/latesthdm\n"
        "/showcaption\n"
        "/resetcaption\n"
        "/testcaption <raw title>"
    )
    bot.send_message(message.chat.id, text)


@bot.message_handler(commands=["sky"])
def cmd_sky(message):
    if not is_admin(message): return
    parts = message.text.strip().split()
    cfg = load_config()
    if len(parts) >= 2:
        arg = parts[1].lower()
        if arg == "on":
            cfg["sky_enabled"] = True; save_config(cfg)
            bot.reply_to(message, "SkyMovies RSS ON")
        elif arg == "off":
            cfg["sky_enabled"] = False; save_config(cfg)
            bot.reply_to(message, "SkyMovies RSS OFF")
        elif arg == "-l":
            bot.reply_to(message, "SkyMovies instant check shuru...")
            threading.Thread(target=run_sky_check, args=(message.chat.id,), daemon=True).start()

@bot.message_handler(commands=["hdm"])
def cmd_hdm(message):
    if not is_admin(message): return
    parts = message.text.strip().split()
    cfg = load_config()
    if len(parts) >= 2:
        arg = parts[1].lower()
        if arg == "on":
            cfg["hdm_enabled"] = True; save_config(cfg)
            bot.reply_to(message, "HDMovie2 RSS ON")
        elif arg == "off":
            cfg["hdm_enabled"] = False; save_config(cfg)
            bot.reply_to(message, "HDMovie2 RSS OFF")
        elif arg == "-l":
            bot.reply_to(message, "HDMovie2 instant check shuru...")
            threading.Thread(target=run_hdm_check, args=(message.chat.id,), daemon=True).start()

@bot.message_handler(commands=["setsky"])
def cmd_setsky(message):
    if not is_admin(message): return
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2: bot.reply_to(message, "Usage: /setsky https://newdomain.com/"); return
    cfg = load_config(); cfg["sky_domain"] = parts[1].strip(); save_config(cfg)
    bot.reply_to(message, f"Sky domain set: {cfg['sky_domain']}")

@bot.message_handler(commands=["sethdm"])
def cmd_sethdm(message):
    if not is_admin(message): return
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2: bot.reply_to(message, "Usage: /sethdm https://newrss.com/feed/"); return
    cfg = load_config(); cfg["hdm_rss"] = parts[1].strip(); save_config(cfg)
    bot.reply_to(message, f"HDM RSS set: {cfg['hdm_rss']}")

@bot.message_handler(commands=["settime"])
def cmd_settime(message):
    if not is_admin(message): return
    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit(): bot.reply_to(message, "Usage: /settime 300"); return
    cfg = load_config(); cfg["interval"] = int(parts[1]); save_config(cfg)
    bot.reply_to(message, f"Interval set: {cfg['interval']} seconds")

@bot.message_handler(commands=["setchat"])
def cmd_setchat(message):
    if not is_admin(message): return
    parts = message.text.strip().split()
    if len(parts) < 2: bot.reply_to(message, "Usage: /setchat -100xxxxxxxx"); return
    cfg = load_config(); cfg["channels"] = [int(parts[1])]; save_config(cfg)
    bot.reply_to(message, f"Channel set: {parts[1]}")

@bot.message_handler(commands=["addchat"])
def cmd_addchat(message):
    if not is_admin(message): return
    parts = message.text.strip().split()
    if len(parts) < 2: bot.reply_to(message, "Usage: /addchat -100xxxxxxxx"); return
    cfg = load_config()
    chat_id = int(parts[1])
    if chat_id not in cfg["channels"]:
        cfg["channels"].append(chat_id); save_config(cfg)
        bot.reply_to(message, f"Channel added: {parts[1]}")
    else:
        bot.reply_to(message, "Channel already hai list mein.")

@bot.message_handler(commands=["settag"])
def cmd_settag(message):
    if not is_admin(message): return
    parts = message.text.strip().split()
    if len(parts) < 2: bot.reply_to(message, "Usage: /settag @username"); return
    cfg = load_config(); cfg["tag_username"] = parts[1]; save_config(cfg)
    bot.reply_to(message, f"Tag username set: {parts[1]}")

@bot.message_handler(commands=["settagid"])
def cmd_settagid(message):
    if not is_admin(message): return
    parts = message.text.strip().split()
    if len(parts) < 2: bot.reply_to(message, "Usage: /settagid 123456789"); return
    cfg = load_config(); cfg["tag_id"] = int(parts[1]); save_config(cfg)
    bot.reply_to(message, f"Tag ID set: {parts[1]}")

@bot.message_handler(commands=["setextractor"])
def cmd_setextractor(message):
    if not is_admin(message): return
    parts = message.text.strip().split()
    if len(parts) < 2 or parts[1].lower() not in ["gofile","gdflix","hubcloud"]:
        bot.reply_to(message, "Usage: /setextractor gofile\nOptions: gofile, gdflix, hubcloud"); return
    cfg = load_config(); cfg["sky_extractor"] = parts[1].lower(); save_config(cfg)
    bot.reply_to(message, f"Sky extractor set: {parts[1].lower()}")

# ---- Caption Commands ----
@bot.message_handler(commands=["setskymovie"])
def cmd_setskymovie(message):
    if not is_admin(message): return
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2: bot.reply_to(message, "Usage: /setskymovie {title} ({year}) {quality} {esub}.mkv"); return
    cfg = load_config(); cfg["sky_movie_caption"] = parts[1].strip(); save_config(cfg)
    sample = {"title":"Movie","year":"2026","quality":"1080p","language":"Hindi","source":"WEB-DL","codec":"x265","season":"","episode":"","complete":"","esub":"Esub"}
    bot.reply_to(message, f"Sky Movie caption set!\nPreview: {apply_caption_format(sample, parts[1].strip())}")

@bot.message_handler(commands=["setskyseries"])
def cmd_setskyseries(message):
    if not is_admin(message): return
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2: bot.reply_to(message, "Usage: /setskyseries {title} ({year}) {season} {episode} {esub}.mkv"); return
    cfg = load_config(); cfg["sky_series_caption"] = parts[1].strip(); save_config(cfg)
    sample = {"title":"Show","year":"2026","quality":"1080p","language":"Hindi","source":"WEB-DL","codec":"x265","season":"Season 1","episode":"EP01-02","complete":"Complete","esub":"Esub"}
    bot.reply_to(message, f"Sky Series caption set!\nPreview: {apply_caption_format(sample, parts[1].strip())}")

@bot.message_handler(commands=["sethdmmovie"])
def cmd_sethdmmovie(message):
    if not is_admin(message): return
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2: bot.reply_to(message, "Usage: /sethdmmovie {title} ({year}) {quality} {esub}.mkv"); return
    cfg = load_config(); cfg["hdm_movie_caption"] = parts[1].strip(); save_config(cfg)
    sample = {"title":"Movie","year":"2026","quality":"1080p","language":"Hindi","source":"WEB-DL","codec":"x265","season":"","episode":"","complete":"","esub":"Esub"}
    bot.reply_to(message, f"HDM Movie caption set!\nPreview: {apply_caption_format(sample, parts[1].strip())}")

@bot.message_handler(commands=["sethdmseries"])
def cmd_sethdmseries(message):
    if not is_admin(message): return
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2: bot.reply_to(message, "Usage: /sethdmseries {title} ({year}) {season} {episode} {esub}.mkv"); return
    cfg = load_config(); cfg["hdm_series_caption"] = parts[1].strip(); save_config(cfg)
    sample = {"title":"Show","year":"2026","quality":"1080p","language":"Hindi","source":"WEB-DL","codec":"x265","season":"Season 1","episode":"EP01-02","complete":"Complete","esub":"Esub"}
    bot.reply_to(message, f"HDM Series caption set!\nPreview: {apply_caption_format(sample, parts[1].strip())}")

@bot.message_handler(commands=["showcaption"])
def cmd_showcaption(message):
    if not is_admin(message): return
    cfg = load_config()
    text = (
        "Current Caption Formats:\n\n"
        f"Sky Movie:\n{cfg.get('sky_movie_caption', DEFAULT_SKY_MOVIE_CAPTION)}\n\n"
        f"Sky Series:\n{cfg.get('sky_series_caption', DEFAULT_SKY_SERIES_CAPTION)}\n\n"
        f"HDM Movie:\n{cfg.get('hdm_movie_caption', DEFAULT_HDM_MOVIE_CAPTION)}\n\n"
        f"HDM Series:\n{cfg.get('hdm_series_caption', DEFAULT_HDM_SERIES_CAPTION)}"
    )
    bot.reply_to(message, text)

@bot.message_handler(commands=["resetcaption"])
def cmd_resetcaption(message):
    if not is_admin(message): return
    cfg = load_config()
    cfg["sky_movie_caption"]  = DEFAULT_SKY_MOVIE_CAPTION
    cfg["sky_series_caption"] = DEFAULT_SKY_SERIES_CAPTION
    cfg["hdm_movie_caption"]  = DEFAULT_HDM_MOVIE_CAPTION
    cfg["hdm_series_caption"] = DEFAULT_HDM_SERIES_CAPTION
    save_config(cfg)
    bot.reply_to(message, "All captions reset to default!")

@bot.message_handler(commands=["testcaption"])
def cmd_testcaption(message):
    if not is_admin(message): return
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /testcaption <raw title>\nExample: /testcaption Krampus (2015) 720p BluRay Hindi x265")
        return
    raw = parts[1].strip()
    p = parse_title(raw)

    # Sky format
    sky_fmt = get_caption_fmt("sky", p)
    sky_out = apply_caption_format(p, sky_fmt)

    # HDM format
    hdm_fmt = get_caption_fmt("hdm", p)
    hdm_out = apply_caption_format(p, hdm_fmt)

    detail = "\n".join([f"{k}: {v}" for k, v in p.items() if v])
    text = (
        f"Parsed:\n{detail}\n\n"
        f"Sky Output:\n{sky_out}\n\n"
        f"HDM Output:\n{hdm_out}"
    )
    bot.reply_to(message, text)

@bot.message_handler(commands=["settings"])
def cmd_settings(message):
    if not is_admin(message): return
    cfg = load_config()
    channels_str = ", ".join(str(c) for c in cfg["channels"]) or "Default (POST_CHAT_ID)"
    text = (
        f"Current Settings\n\n"
        f"Sky Domain: {cfg['sky_domain']}\n"
        f"HDM RSS: {cfg['hdm_rss']}\n"
        f"Interval: {cfg['interval']}s\n"
        f"Tag: {cfg['tag_username']} {cfg['tag_id']}\n"
        f"Channels: {channels_str}\n"
        f"Sky: {'ON' if cfg['sky_enabled'] else 'OFF'}\n"
        f"HDM: {'ON' if cfg['hdm_enabled'] else 'OFF'}\n"
        f"Extractor: {cfg.get('sky_extractor','gofile')}"
    )
    bot.reply_to(message, text)

@bot.message_handler(commands=["status"])
def cmd_status(message):
    if not is_admin(message): return
    cfg = load_config()
    def fmt_time(t):
        if not t: return "Abhi tak nahi"
        diff = int(time.time() - t)
        return f"{diff} sec ago" if diff < 60 else f"{diff // 60} min ago"
    def fmt_next(t):
        if not t: return "Unknown"
        diff = int(t - time.time())
        if diff <= 0: return "Abhi"
        return f"{diff} sec" if diff < 60 else f"{diff // 60} min"
    text = (
        f"Bot Status\n\n"
        f"Sky Last Check: {fmt_time(last_check['sky'])}\n"
        f"HDM Last Check: {fmt_time(last_check['hdm'])}\n\n"
        f"Next Sky Check: {fmt_next(next_check['sky'])}\n"
        f"Next HDM Check: {fmt_next(next_check['hdm'])}\n\n"
        f"Interval: {cfg['interval']}s"
    )
    bot.reply_to(message, text)

@bot.message_handler(commands=["stats"])
def cmd_stats(message):
    if not is_admin(message): return
    stats = load_stats()
    total = stats.get("sky", 0) + stats.get("hdm", 0)
    bot.reply_to(message, (
        f"Today Stats ({stats.get('date', 'N/A')})\n\n"
        f"SkyMovies: {stats.get('sky', 0)}\n"
        f"HDMovie2: {stats.get('hdm', 0)}\n\n"
        f"Total: {total}"
    ))

@bot.message_handler(commands=["latestsky"])
def cmd_latestsky(message):
    if not is_admin(message): return
    bot.reply_to(message, "Latest Sky posts fetch ho rahe hain...")
    try:
        posts = get_sky_posts()[:5]
        if not posts: bot.reply_to(message, "Koi post nahi mila."); return
        text = "Latest SkyMovies Posts (preview):\n\n"
        for p in posts:
            text += f"- {p['title']}\n{p['url']}\n\n"
        bot.send_message(message.chat.id, text)
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=["latesthdm"])
def cmd_latesthdm(message):
    if not is_admin(message): return
    bot.reply_to(message, "Latest HDM posts fetch ho rahe hain...")
    try:
        posts = get_hdm_posts()[:5]
        if not posts: bot.reply_to(message, "Koi post nahi mila."); return
        text = "Latest HDMovie2 Posts (preview):\n\n"
        for p in posts:
            text += f"- {p['title']}\n{p['url']}\n\n"
        bot.send_message(message.chat.id, text)
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

# ================= INSTANT CHECK FUNCTIONS =================
def run_sky_check(notify_chat=None):
    seen = load_seen()
    try:
        posts = get_sky_posts()
        count = 0
        for post in reversed(posts):
            if post["url"] in seen:
                continue
            data = extract_sky_link(post["url"])
            if data:
                send_to_telegram(data, "sky")
                count += 1
            seen.add(post["url"])
            save_seen(seen)
            time.sleep(2)
        if notify_chat:
            bot.send_message(notify_chat, f"Sky check done. {count} new posts sent.")
    except Exception as e:
        if notify_chat:
            bot.send_message(notify_chat, f"Sky check error: {e}")

def run_hdm_check(notify_chat=None):
    seen = load_seen()
    try:
        posts = get_hdm_posts()
        count = 0
        for post in reversed(posts):
            if post["url"] in seen:
                continue
            hdm_links = get_hdm_links(post["url"])
            all_files = []
            for item in hdm_links:
                all_files.extend(extract_gdflix_data(item["url"]))
            unique = []
            used = set()
            for x in all_files:
                if x["link"] not in used:
                    used.add(x["link"]); unique.append(x)
            for file in unique:
                send_to_telegram(file, "hdm")
                count += 1
                time.sleep(2)
            seen.add(post["url"])
            save_seen(seen)
        if notify_chat:
            bot.send_message(notify_chat, f"HDM check done. {count} new posts sent.")
    except Exception as e:
        if notify_chat:
            bot.send_message(notify_chat, f"HDM check error: {e}")

# ================= MAIN LOOP =================
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
                sky_posts = get_sky_posts()
                for post in reversed(sky_posts):
                    if post["url"] in seen: continue
                    print("[SKY] New:", post["title"])
                    data = extract_sky_link(post["url"])
                    if data:
                        send_to_telegram(data, "sky")
                        print("[SKY] Sent:", data["title"])
                    seen.add(post["url"]); save_seen(seen)
                    time.sleep(3)

            if cfg.get("hdm_enabled", True):
                last_check["hdm"] = time.time()
                hd_posts = get_hdm_posts()
                for post in reversed(hd_posts):
                    if post["url"] in seen: continue
                    print("[HDMOVIE2] New:", post["title"])
                    hdm_links = get_hdm_links(post["url"])
                    all_files = []
                    for item in hdm_links:
                        all_files.extend(extract_gdflix_data(item["url"]))
                    unique = []
                    used = set()
                    for x in all_files:
                        if x["link"] not in used:
                            used.add(x["link"]); unique.append(x)
                    for file in unique:
                        send_to_telegram(file, "hdm")
                        print("[HDMOVIE2] Sent:", file["title"])
                        time.sleep(2)
                    seen.add(post["url"]); save_seen(seen)

        except Exception as e:
            print("MAIN ERROR:", e)

        next_check["sky"] = time.time() + interval
        next_check["hdm"] = time.time() + interval
        print(f"Sleeping {interval}s...")
        time.sleep(interval)


if __name__ == "__main__":
    main()
