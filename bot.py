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

bot = telebot.TeleBot(BOT_TOKEN, parse_mode=None)

HEADERS = {"User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile)"}

# ================= CONFIG HELPERS =================
def load_config():
    try:
        with open(CONFIG_FILE, "r") as f:
            return json.load(f)
    except:
        return {
            "sky_domain": "https://skymovieshd.free/",
            "hdm_rss": "https://hdmovie2.org.uk/movies/feed/",
            "ef_url": "https://e4.extraflix.mobi/",
            "ff_url": "https://filmyfly.builders/",
            "interval": 900,
            "tag_username": "@username",
            "tag_id": 123456789,
            "channels": [], "sky_channels": [], "hdm_channels": [],
            "ef_channels": [], "ff_channels": [],
            "sky_enabled": True, "hdm_enabled": True,
            "ef_enabled": True, "ff_enabled": True,
            "sky_extractor": "gofile",
            "ef_extractor": "hubcloud",
            "ff_extractor": "all",
            "ff_size_limit_mb": 4096,
            "sky_cmd": "/l3", "hdm_cmd": "/l3", "ef_cmd": "/l3", "ff_cmd": "/l3",
            "sky_movie_caption": "{title} ({year}) {quality} {language} {source} {codec} {esub}.mkv",
            "sky_series_caption": "{title} ({year}) {season} {episode} {complete} {quality} {language} {source} {codec} {esub}.mkv",
            "hdm_movie_caption": "{title} ({year}) {quality} {language} {source} {codec} {esub}.mkv",
            "hdm_series_caption": "{title} ({year}) {season} {episode} {complete} {quality} {language} {source} {codec} {esub}.mkv",
            "ef_movie_caption": "{title} ({year}) {quality} {language} {esub}.mkv",
            "ff_movie_caption": "{title} ({year}) {quality} {language} {esub}.mkv",
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

# ================= TRACKER =================
last_check = {"sky": None, "hdm": None, "ef": None, "ff": None}
next_check = {"sky": None, "hdm": None, "ef": None, "ff": None}

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

DEFAULT_SKY_MOVIE  = "{title} ({year}) {quality} {language} {source} {codec} {esub}.mkv"
DEFAULT_SKY_SERIES = "{title} ({year}) {season} {episode} {complete} {quality} {language} {source} {codec} {esub}.mkv"
DEFAULT_HDM_MOVIE  = "{title} ({year}) {quality} {language} {source} {codec} {esub}.mkv"
DEFAULT_HDM_SERIES = "{title} ({year}) {season} {episode} {complete} {quality} {language} {source} {codec} {esub}.mkv"
DEFAULT_EF_MOVIE   = "{title} ({year}) {quality} {language} {esub}.mkv"
DEFAULT_FF_MOVIE   = "{title} ({year}) {quality} {language} {esub}.mkv"

def apply_caption(parts, fmt):
    result = fmt
    for k, v in parts.items():
        result = result.replace('{' + k + '}', v)
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
    elif source == "ef":
        return cfg.get("ef_movie_caption", DEFAULT_EF_MOVIE)
    else:
        return cfg.get("ff_movie_caption", DEFAULT_FF_MOVIE)

def clean_title(raw, source="sky"):
    p = parse_title(raw)
    return apply_caption(p, get_fmt(source, p))

# ================= JINA TITLE FETCH =================
def fetch_title_via_jina(gdflix_url):
    """GDFlix page title jina.ai ke through fetch karo"""
    try:
        jina_url = f"https://r.jina.ai/{gdflix_url}"
        r = requests.get(jina_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        # Title: line dhundho
        m = re.search(r'Title:\s*GDFlix\s*\|\s*(.+?)(?:\n|URL Source)', r.text, re.I)
        if m:
            return m.group(1).strip()
        # Fallback: Name : line
        m2 = re.search(r'Name\s*:\s*([^\n]+\.mkv)', r.text, re.I)
        if m2:
            return m2.group(1).strip()
    except Exception as e:
        print(f"Jina fetch error: {e}")
    return None

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
        if not href or not title: continue
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
    if not gd: return None, None
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
    """HDM ke gdflix links fetch karo — jina.ai se title lo"""
    try:
        r = requests.get(hdm_url, headers=HEADERS, allow_redirects=True, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        final = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "gdflix" not in href.lower(): continue
            try:
                # Jina se title fetch karo
                jina_title = fetch_title_via_jina(href)
                if jina_title:
                    raw_title = jina_title
                else:
                    # Fallback: direct page se
                    r2 = requests.get(href, headers=HEADERS, allow_redirects=True, timeout=20)
                    tm = re.search(r"<title>(.*?)</title>", r2.text, re.I)
                    raw_title = tm.group(1) if tm else "Unknown"
                    href = r2.url  # final redirect URL

                final.append({"title": clean_title(raw_title, "hdm"), "link": href})
            except Exception as e:
                print("GD ERROR:", e)
        return final
    except Exception as e:
        print("FINAL ERROR:", e); return []

# ================= EXTRAFLIX =================
def get_ef_posts():
    cfg = load_config()
    r = requests.get(cfg.get("ef_url", "https://e4.extraflix.mobi/"),
                     headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    soup = BeautifulSoup(r.text, "html.parser")
    movies = []
    for article in soup.select("article"):
        if "category-movies" not in article.get("class", []): continue
        a = article.select_one("h2.entry-title a")
        if a: movies.append({"title": a.get_text(strip=True), "url": a["href"]})
    return movies

def get_ef_links(movie_url):
    """ExtraFlix se drivehub + hubcloud dono links nikalo"""
    try:
        r = requests.get(movie_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        soup = BeautifulSoup(r.text, "html.parser")

        linkshub_url = None
        for a in soup.find_all("a", href=True):
            if "linkshub.fun" in a["href"].lower():
                linkshub_url = a["href"]; break

        if not linkshub_url:
            return {"drivehub": [], "hubcloud": []}

        r2 = requests.get(linkshub_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        soup2 = BeautifulSoup(r2.text, "html.parser")

        drivehub, hubcloud = [], []
        for a in soup2.find_all("a", href=True):
            href = a["href"]
            if "drivehub" in href.lower() and href not in drivehub:
                drivehub.append(href)
            elif "hubcloud" in href.lower() and href not in hubcloud:
                hubcloud.append(href)

        return {"drivehub": drivehub, "hubcloud": hubcloud}
    except Exception as e:
        print("EF ERROR:", e)
        return {"drivehub": [], "hubcloud": []}

def get_ef_final_links(movie_url, post_title, extractor="hubcloud"):
    """EF ke final links + titles nikalo"""
    links = get_ef_links(movie_url)
    results = []

    target_links = []
    if extractor == "drivehub":
        target_links = links["drivehub"]
    elif extractor == "hubcloud":
        target_links = links["hubcloud"]
    else:  # all
        target_links = links["drivehub"] + links["hubcloud"]

    for link in target_links:
        try:
            r = requests.get(link, headers={"User-Agent": "Mozilla/5.0"}, timeout=30, allow_redirects=True)
            tm = re.search(r"<title>(.*?)</title>", r.text, re.I | re.S)
            raw = tm.group(1).strip() if tm else post_title
            results.append({"title": clean_title(raw, "ef"), "link": r.url})
        except Exception as e:
            print("EF LINK ERROR:", e)

    return results

# ================= FILMYFLY =================
def parse_size(size_str):
    size_str = size_str.upper()
    m = re.search(r'([\d.]+)\s*(MB|GB)', size_str)
    if not m: return 0
    val, unit = float(m.group(1)), m.group(2)
    return val * 1024 if unit == 'GB' else val

# FilmyFly ke known cloud providers
FF_LINK_PATTERNS = {
    "gofile":      r'gofile\.io',
    "gdflix":      r'gdflix\.|gdlink\.',
    "hubcloud":    r'hubcloud\.',
    "drivehub":    r'drivehub\.',
    "buzzheavier": r'buzzheavier\.com',
    "r2":          r'r2\.dev',
    "telegram":    r't\.me',
    "filesdl":     r'filesdl\.in',
    "iwebp":       r'iwebp\.store',
}

def get_ff_posts():
    cfg = load_config()
    try:
        r = requests.get(cfg.get("ff_url", "https://filmyfly.builders/"),
                         headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        soup = BeautifulSoup(r.text, "html.parser")
        posts = []
        for a in soup.select('.A10 a[href*="/page-download/"]'):
            href = a["href"]
            if not href.startswith("http"):
                href = cfg.get("ff_url", "https://filmyfly.builders/").rstrip("/") + "/" + href.lstrip("/")
            posts.append({"title": a.get_text(strip=True), "url": href})
        return posts
    except Exception as e:
        print("FF POSTS ERROR:", e); return []

def get_ff_links(movie_url):
    """FilmyFly movie page se saare download links nikalo"""
    cfg = load_config()
    size_limit = cfg.get("ff_size_limit_mb", 4096)
    extractor = cfg.get("ff_extractor", "all").lower()
    results = []

    try:
        r = requests.get(movie_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        soup = BeautifulSoup(r.text, "html.parser")

        linkmake = soup.find("a", href=re.compile(r'linkmake\.in'))
        if not linkmake: return results

        r2 = requests.get(linkmake["href"], headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        soup2 = BeautifulSoup(r2.text, "html.parser")
        quality_links = soup2.find_all("a", href=re.compile(r'filesdl\.in'))

        for q_link in quality_links:
            try:
                r3 = requests.get(q_link["href"], headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
                soup3 = BeautifulSoup(r3.text, "html.parser")

                # Title
                title_div = soup3.find("div", class_="title")
                title_raw = title_div.text.strip() if title_div else "Movie"

                # Size check
                size_div = soup3.find("div", string=re.compile(r'Size:'))
                size_text = size_div.text.replace("Size:", "").strip() if size_div else "0 MB"
                if parse_size(size_text) > size_limit:
                    print(f"[FF] Skipping (size > {size_limit}MB): {title_raw}")
                    continue

                # Download buttons
                dl_btns = soup3.find_all("a", class_=re.compile(r'button[124]?|download-link'))
                for btn in dl_btns:
                    href = btn.get("href", "")
                    if not href or href.startswith("data:"): continue

                    # Extractor filter
                    if extractor != "all":
                        pat = FF_LINK_PATTERNS.get(extractor, "")
                        if pat and not re.search(pat, href, re.I): continue

                    results.append({
                        "title": clean_title(title_raw, "ff"),
                        "link": href
                    })
            except Exception as e:
                print("FF QUALITY ERROR:", e)

    except Exception as e:
        print("FF LINKS ERROR:", e)

    return results

# ================= SEND =================
def send_to_telegram(data, source="sky"):
    cfg = load_config()
    tag_line = f"Tag: {cfg['tag_username']} {cfg['tag_id']}"
    cmd = cfg.get(f"{source}_cmd", "/l3")
    message = f"{cmd} {data['link']} -n {data['title']}\n{tag_line}"

    source_channels = cfg.get(f"{source}_channels", [])
    common_channels = cfg.get("channels", [])
    targets = source_channels or common_channels or [int(os.getenv("POST_CHAT_ID", "0"))]

    for chat_id in targets:
        try:
            bot.send_message(chat_id, message)
        except Exception as e:
            print(f"Send error to {chat_id}: {e}")
    increment_stat(source)

# ================= HELP PAGES =================
HELP_PAGES = [
    (
        "RSS Bot Commands (1/4)\n\n"
        "MANUAL CHECK:\n"
        "/sky -l  — SkyMovies\n"
        "/hdm -l  — HDMovie2\n"
        "/ef -l   — ExtraFlix\n"
        "/ff -l   — FilmyFly\n\n"
        "ENABLE/DISABLE:\n"
        "/sky on|off\n"
        "/hdm on|off\n"
        "/ef on|off\n"
        "/ff on|off\n\n"
        "DOMAIN CHANGE:\n"
        "/setsky https://domain.com/\n"
        "/sethdm https://rss.com/feed/\n"
        "/setef https://domain.com/\n"
        "/setff https://domain.com/"
    ),
    (
        "RSS Bot Commands (2/4)\n\n"
        "INTERVAL:\n"
        "/settime 300   (5 min)\n"
        "/settime 1800  (30 min)\n\n"
        "CHANNEL (Common):\n"
        "/setchat -100xxx\n"
        "/addchat -100xxx\n\n"
        "SKY Channels:\n"
        "/setskychat | /addskychat | /removeskychat\n\n"
        "HDM Channels:\n"
        "/sethdmchat | /addhdmchat | /removehdmchat\n\n"
        "EF Channels:\n"
        "/setefchat | /artefchat | /removefefchat\n\n"
        "FF Channels:\n"
        "/setffchat | /addffchat | /removfffchat\n\n"
        "/channels — all channel list"
    ),
    (
        "RSS Bot Commands (3/4)\n\n"
        "TAG:\n"
        "/settag @username\n"
        "/settagid 123456789\n\n"
        "CMD PREFIX:\n"
        "/setskycmd /l3\n"
        "/sethdmcmd /l3\n"
        "/setefcmd /l3\n"
        "/setffcmd /l3\n\n"
        "EXTRACTOR:\n"
        "/setextractor gofile|gdflix|hubcloud  (Sky)\n"
        "/setefextractor drivehub|hubcloud|all (EF)\n"
        "/setffextractor gofile|gdflix|hubcloud|drivehub|buzzheavier|r2|filesdl|all (FF)\n\n"
        "FF SIZE LIMIT:\n"
        "/setfflimit 4096  (MB, default 4GB)"
    ),
    (
        "RSS Bot Commands (4/4)\n\n"
        "CAPTION:\n"
        "/setskymovie FORMAT\n"
        "/setskyseries FORMAT\n"
        "/sethdmmovie FORMAT\n"
        "/sethdmseries FORMAT\n"
        "/setefcaption FORMAT\n"
        "/setffcaption FORMAT\n\n"
        "/showcaption\n"
        "/resetcaption\n"
        "/testcaption <title>\n\n"
        "Placeholders:\n"
        "{title} {year} {quality} {language}\n"
        "{source} {codec} {season} {episode}\n"
        "{complete} {esub}\n\n"
        "INFO:\n"
        "/settings | /status | /stats\n"
        "/latestsky | /latesthdm\n"
        "/latestef | /latestff"
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
    bot.edit_message_text(HELP_PAGES[page], call.message.chat.id, call.message.message_id, reply_markup=markup)
    bot.answer_callback_query(call.id)

# --- Source toggles ---
def _toggle_source(message, key, name):
    if not is_admin(message): return
    parts = message.text.strip().split()
    if len(parts) < 2: return
    cfg = load_config()
    if parts[1].lower() == "on":
        cfg[key] = True; save_config(cfg); bot.reply_to(message, f"{name} ON")
    elif parts[1].lower() == "off":
        cfg[key] = False; save_config(cfg); bot.reply_to(message, f"{name} OFF")

@bot.message_handler(commands=["sky"])
def cmd_sky(message):
    if not is_admin(message): return
    parts = message.text.strip().split()
    if len(parts) < 2: return
    if parts[1] == "-l":
        bot.reply_to(message, "Sky instant check shuru...")
        threading.Thread(target=run_sky_check, args=(message.chat.id,), daemon=True).start()
    else: _toggle_source(message, "sky_enabled", "SkyMovies")

@bot.message_handler(commands=["hdm"])
def cmd_hdm(message):
    if not is_admin(message): return
    parts = message.text.strip().split()
    if len(parts) < 2: return
    if parts[1] == "-l":
        bot.reply_to(message, "HDM instant check shuru...")
        threading.Thread(target=run_hdm_check, args=(message.chat.id,), daemon=True).start()
    else: _toggle_source(message, "hdm_enabled", "HDMovie2")

@bot.message_handler(commands=["ef"])
def cmd_ef(message):
    if not is_admin(message): return
    parts = message.text.strip().split()
    if len(parts) < 2: return
    if parts[1] == "-l":
        bot.reply_to(message, "ExtraFlix instant check shuru...")
        threading.Thread(target=run_ef_check, args=(message.chat.id,), daemon=True).start()
    else: _toggle_source(message, "ef_enabled", "ExtraFlix")

@bot.message_handler(commands=["ff"])
def cmd_ff(message):
    if not is_admin(message): return
    parts = message.text.strip().split()
    if len(parts) < 2: return
    if parts[1] == "-l":
        bot.reply_to(message, "FilmyFly instant check shuru...")
        threading.Thread(target=run_ff_check, args=(message.chat.id,), daemon=True).start()
    else: _toggle_source(message, "ff_enabled", "FilmyFly")

# --- Domain commands ---
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
    bot.reply_to(message, f"EF URL: {cfg['ef_url']}")

@bot.message_handler(commands=["setff"])
def cmd_setff(message):
    if not is_admin(message): return
    p = message.text.strip().split(maxsplit=1)
    if len(p) < 2: bot.reply_to(message, "Usage: /setff https://domain.com/"); return
    cfg = load_config(); cfg["ff_url"] = p[1].strip(); save_config(cfg)
    bot.reply_to(message, f"FF URL: {cfg['ff_url']}")

@bot.message_handler(commands=["settime"])
def cmd_settime(message):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2 or not p[1].isdigit(): bot.reply_to(message, "Usage: /settime 900"); return
    cfg = load_config(); cfg["interval"] = int(p[1]); save_config(cfg)
    bot.reply_to(message, f"Interval: {cfg['interval']}s")

# --- Channel commands ---
def _add_channel(message, key, name):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2: bot.reply_to(message, f"Usage: {message.text.split()[0]} -100xxxxxxxx"); return
    cfg = load_config(); cid = int(p[1])
    if cid not in cfg[key]: cfg[key].append(cid); save_config(cfg); bot.reply_to(message, f"{name} added: {p[1]}")
    else: bot.reply_to(message, "Already hai list mein.")

def _set_channel(message, key, name):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2: bot.reply_to(message, f"Usage: {message.text.split()[0]} -100xxxxxxxx"); return
    cfg = load_config(); cfg[key] = [int(p[1])]; save_config(cfg)
    bot.reply_to(message, f"{name} set: {p[1]}")

def _remove_channel(message, key, name):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2: bot.reply_to(message, f"Usage: {message.text.split()[0]} -100xxxxxxxx"); return
    cfg = load_config(); cid = int(p[1])
    if cid in cfg[key]: cfg[key].remove(cid); save_config(cfg); bot.reply_to(message, f"{name} removed: {p[1]}")
    else: bot.reply_to(message, "Channel nahi mila list mein.")

@bot.message_handler(commands=["setchat"])
def h(m): _set_channel(m, "channels", "Common channel")
@bot.message_handler(commands=["addchat"])
def h2(m): _add_channel(m, "channels", "Common channel")

@bot.message_handler(commands=["setskychat"])
def h3(m): _set_channel(m, "sky_channels", "Sky channel")
@bot.message_handler(commands=["addskychat"])
def h4(m): _add_channel(m, "sky_channels", "Sky channel")
@bot.message_handler(commands=["removeskychat"])
def h5(m): _remove_channel(m, "sky_channels", "Sky channel")

@bot.message_handler(commands=["sethdmchat"])
def h6(m): _set_channel(m, "hdm_channels", "HDM channel")
@bot.message_handler(commands=["addhdmchat"])
def h7(m): _add_channel(m, "hdm_channels", "HDM channel")
@bot.message_handler(commands=["removehdmchat"])
def h8(m): _remove_channel(m, "hdm_channels", "HDM channel")

@bot.message_handler(commands=["setefchat"])
def h9(m): _set_channel(m, "ef_channels", "EF channel")
@bot.message_handler(commands=["artefchat"])
def h10(m): _add_channel(m, "ef_channels", "EF channel")
@bot.message_handler(commands=["removefefchat"])
def h11(m): _remove_channel(m, "ef_channels", "EF channel")

@bot.message_handler(commands=["setffchat"])
def h12(m): _set_channel(m, "ff_channels", "FF channel")
@bot.message_handler(commands=["addffchat"])
def h13(m): _add_channel(m, "ff_channels", "FF channel")
@bot.message_handler(commands=["removfffchat"])
def h14(m): _remove_channel(m, "ff_channels", "FF channel")

@bot.message_handler(commands=["channels"])
def cmd_channels(message):
    if not is_admin(message): return
    cfg = load_config()
    def fmt(lst): return ", ".join(str(c) for c in lst) if lst else "None"
    bot.reply_to(message, (
        f"Channel List\n\n"
        f"Sky:    {fmt(cfg.get('sky_channels',[]))}\n"
        f"HDM:    {fmt(cfg.get('hdm_channels',[]))}\n"
        f"EF:     {fmt(cfg.get('ef_channels',[]))}\n"
        f"FF:     {fmt(cfg.get('ff_channels',[]))}\n"
        f"Common: {fmt(cfg.get('channels',[]))}\n\n"
        f"(Common = fallback agar source channel empty ho)"
    ))

# --- Tag & CMD commands ---
@bot.message_handler(commands=["settag"])
def cmd_settag(message):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2: return
    cfg = load_config(); cfg["tag_username"] = p[1]; save_config(cfg)
    bot.reply_to(message, f"Tag: {p[1]}")

@bot.message_handler(commands=["settagid"])
def cmd_settagid(message):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2: return
    cfg = load_config(); cfg["tag_id"] = int(p[1]); save_config(cfg)
    bot.reply_to(message, f"Tag ID: {p[1]}")

@bot.message_handler(commands=["setskycmd"])
def cmd_setskycmd(m):
    if not is_admin(m): return
    p = m.text.strip().split()
    if len(p) < 2: return
    cfg = load_config(); cfg["sky_cmd"] = p[1]; save_config(cfg); bot.reply_to(m, f"Sky cmd: {p[1]}")

@bot.message_handler(commands=["sethdmcmd"])
def cmd_sethdmcmd(m):
    if not is_admin(m): return
    p = m.text.strip().split()
    if len(p) < 2: return
    cfg = load_config(); cfg["hdm_cmd"] = p[1]; save_config(cfg); bot.reply_to(m, f"HDM cmd: {p[1]}")

@bot.message_handler(commands=["setefcmd"])
def cmd_setefcmd(m):
    if not is_admin(m): return
    p = m.text.strip().split()
    if len(p) < 2: return
    cfg = load_config(); cfg["ef_cmd"] = p[1]; save_config(cfg); bot.reply_to(m, f"EF cmd: {p[1]}")

@bot.message_handler(commands=["setffcmd"])
def cmd_setffcmd(m):
    if not is_admin(m): return
    p = m.text.strip().split()
    if len(p) < 2: return
    cfg = load_config(); cfg["ff_cmd"] = p[1]; save_config(cfg); bot.reply_to(m, f"FF cmd: {p[1]}")

# --- Extractor commands ---
@bot.message_handler(commands=["setextractor"])
def cmd_setextractor(message):
    if not is_admin(message): return
    p = message.text.strip().split()
    valid = ["gofile", "gdflix", "hubcloud"]
    if len(p) < 2 or p[1].lower() not in valid:
        bot.reply_to(message, f"Usage: /setextractor {'|'.join(valid)}"); return
    cfg = load_config(); cfg["sky_extractor"] = p[1].lower(); save_config(cfg)
    bot.reply_to(message, f"Sky extractor: {p[1].lower()}")

@bot.message_handler(commands=["setefextractor"])
def cmd_setefextractor(message):
    if not is_admin(message): return
    p = message.text.strip().split()
    valid = ["drivehub", "hubcloud", "all"]
    if len(p) < 2 or p[1].lower() not in valid:
        bot.reply_to(message, f"Usage: /setefextractor {'|'.join(valid)}"); return
    cfg = load_config(); cfg["ef_extractor"] = p[1].lower(); save_config(cfg)
    bot.reply_to(message, f"EF extractor: {p[1].lower()}")

@bot.message_handler(commands=["setffextractor"])
def cmd_setffextractor(message):
    if not is_admin(message): return
    p = message.text.strip().split()
    valid = list(FF_LINK_PATTERNS.keys()) + ["all"]
    if len(p) < 2 or p[1].lower() not in valid:
        bot.reply_to(message, f"Usage: /setffextractor {'|'.join(valid)}"); return
    cfg = load_config(); cfg["ff_extractor"] = p[1].lower(); save_config(cfg)
    bot.reply_to(message, f"FF extractor: {p[1].lower()}")

@bot.message_handler(commands=["setfflimit"])
def cmd_setfflimit(message):
    if not is_admin(message): return
    p = message.text.strip().split()
    if len(p) < 2 or not p[1].isdigit():
        bot.reply_to(message, "Usage: /setfflimit 4096 (MB)"); return
    cfg = load_config(); cfg["ff_size_limit_mb"] = int(p[1]); save_config(cfg)
    bot.reply_to(message, f"FF size limit: {p[1]} MB")

# --- Caption commands ---
SAMPLE_MOVIE  = {"title":"Movie","year":"2026","quality":"1080p","language":"Hindi","source":"WEB-DL","codec":"x265","season":"","episode":"","complete":"","esub":"Esub"}
SAMPLE_SERIES = {"title":"Show","year":"2026","quality":"1080p","language":"Hindi","source":"WEB-DL","codec":"x265","season":"Season 1","episode":"EP01-02","complete":"Complete","esub":"Esub"}

def _set_caption(message, key, sample):
    if not is_admin(message): return
    p = message.text.strip().split(maxsplit=1)
    if len(p) < 2: bot.reply_to(message, "Format daalna zaroori hai."); return
    cfg = load_config(); cfg[key] = p[1].strip(); save_config(cfg)
    bot.reply_to(message, f"Saved!\nPreview: {apply_caption(sample, p[1].strip())}")

@bot.message_handler(commands=["setskymovie"])
def c1(m): _set_caption(m, "sky_movie_caption", SAMPLE_MOVIE)
@bot.message_handler(commands=["setskyseries"])
def c2(m): _set_caption(m, "sky_series_caption", SAMPLE_SERIES)
@bot.message_handler(commands=["sethdmmovie"])
def c3(m): _set_caption(m, "hdm_movie_caption", SAMPLE_MOVIE)
@bot.message_handler(commands=["sethdmseries"])
def c4(m): _set_caption(m, "hdm_series_caption", SAMPLE_SERIES)
@bot.message_handler(commands=["setefcaption"])
def c5(m): _set_caption(m, "ef_movie_caption", SAMPLE_MOVIE)
@bot.message_handler(commands=["setffcaption"])
def c6(m): _set_caption(m, "ff_movie_caption", SAMPLE_MOVIE)

@bot.message_handler(commands=["showcaption"])
def cmd_showcaption(message):
    if not is_admin(message): return
    cfg = load_config()
    bot.reply_to(message, (
        f"Caption Formats:\n\n"
        f"Sky Movie:\n{cfg.get('sky_movie_caption', DEFAULT_SKY_MOVIE)}\n\n"
        f"Sky Series:\n{cfg.get('sky_series_caption', DEFAULT_SKY_SERIES)}\n\n"
        f"HDM Movie:\n{cfg.get('hdm_movie_caption', DEFAULT_HDM_MOVIE)}\n\n"
        f"HDM Series:\n{cfg.get('hdm_series_caption', DEFAULT_HDM_SERIES)}\n\n"
        f"EF:\n{cfg.get('ef_movie_caption', DEFAULT_EF_MOVIE)}\n\n"
        f"FF:\n{cfg.get('ff_movie_caption', DEFAULT_FF_MOVIE)}"
    ))

@bot.message_handler(commands=["resetcaption"])
def cmd_resetcaption(message):
    if not is_admin(message): return
    cfg = load_config()
    cfg.update({
        "sky_movie_caption": DEFAULT_SKY_MOVIE, "sky_series_caption": DEFAULT_SKY_SERIES,
        "hdm_movie_caption": DEFAULT_HDM_MOVIE, "hdm_series_caption": DEFAULT_HDM_SERIES,
        "ef_movie_caption": DEFAULT_EF_MOVIE, "ff_movie_caption": DEFAULT_FF_MOVIE,
    })
    save_config(cfg); bot.reply_to(message, "All captions reset!")

@bot.message_handler(commands=["testcaption"])
def cmd_testcaption(message):
    if not is_admin(message): return
    p = message.text.strip().split(maxsplit=1)
    if len(p) < 2: bot.reply_to(message, "Usage: /testcaption Movie Name (2026) 1080p BluRay"); return
    parts = parse_title(p[1].strip())
    detail = "\n".join([f"{k}: {v}" for k, v in parts.items() if v])
    bot.reply_to(message, (
        f"Parsed:\n{detail}\n\n"
        f"Sky:  {apply_caption(parts, get_fmt('sky', parts))}\n"
        f"HDM:  {apply_caption(parts, get_fmt('hdm', parts))}\n"
        f"EF:   {apply_caption(parts, get_fmt('ef', parts))}\n"
        f"FF:   {apply_caption(parts, get_fmt('ff', parts))}"
    ))

# --- Info commands ---
@bot.message_handler(commands=["settings"])
def cmd_settings(message):
    if not is_admin(message): return
    cfg = load_config()
    bot.reply_to(message, (
        f"Settings\n\n"
        f"Sky: {cfg['sky_domain']} ({'ON' if cfg['sky_enabled'] else 'OFF'})\n"
        f"HDM: {cfg['hdm_rss']} ({'ON' if cfg['hdm_enabled'] else 'OFF'})\n"
        f"EF:  {cfg.get('ef_url')} ({'ON' if cfg.get('ef_enabled') else 'OFF'})\n"
        f"FF:  {cfg.get('ff_url')} ({'ON' if cfg.get('ff_enabled') else 'OFF'})\n\n"
        f"Interval: {cfg['interval']}s\n"
        f"Tag: {cfg['tag_username']} {cfg['tag_id']}\n"
        f"Sky extractor: {cfg.get('sky_extractor','gofile')}\n"
        f"EF extractor: {cfg.get('ef_extractor','hubcloud')}\n"
        f"FF extractor: {cfg.get('ff_extractor','all')}\n"
        f"FF size limit: {cfg.get('ff_size_limit_mb',4096)} MB\n"
        f"CMDs: sky={cfg.get('sky_cmd','/l3')} hdm={cfg.get('hdm_cmd','/l3')} ef={cfg.get('ef_cmd','/l3')} ff={cfg.get('ff_cmd','/l3')}"
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
        if d <= 0: return "Now"
        return f"{d}s" if d<60 else f"{d//60}m"
    bot.reply_to(message, (
        f"Status\n\n"
        f"Sky  last:{ft(last_check['sky'])}  next:{fn(next_check['sky'])}\n"
        f"HDM  last:{ft(last_check['hdm'])}  next:{fn(next_check['hdm'])}\n"
        f"EF   last:{ft(last_check['ef'])}   next:{fn(next_check['ef'])}\n"
        f"FF   last:{ft(last_check['ff'])}   next:{fn(next_check['ff'])}\n\n"
        f"Interval: {cfg['interval']}s"
    ))

@bot.message_handler(commands=["stats"])
def cmd_stats(message):
    if not is_admin(message): return
    s = load_stats()
    total = sum(s.get(k, 0) for k in ["sky","hdm","ef","ff"])
    bot.reply_to(message, (
        f"Today Stats ({s.get('date','?')})\n\n"
        f"Sky:      {s.get('sky',0)}\n"
        f"HDMovie2: {s.get('hdm',0)}\n"
        f"ExtraFlix:{s.get('ef',0)}\n"
        f"FilmyFly: {s.get('ff',0)}\n\n"
        f"Total: {total}"
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

# ================= CHECK RUNNERS =================
def run_sky_check(notify_chat=None):
    seen = load_seen(); count = 0
    try:
        for post in reversed(get_sky_posts()):
            if post["url"] in seen: continue
            data = extract_sky_link(post["url"])
            if data: send_to_telegram(data, "sky"); count += 1
            seen.add(post["url"]); save_seen(seen); time.sleep(2)
        if notify_chat: bot.send_message(notify_chat, f"Sky done. {count} sent.")
    except Exception as e:
        if notify_chat: bot.send_message(notify_chat, f"Sky error: {e}")

def run_hdm_check(notify_chat=None):
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
        if notify_chat: bot.send_message(notify_chat, f"HDM done. {count} sent.")
    except Exception as e:
        if notify_chat: bot.send_message(notify_chat, f"HDM error: {e}")

def run_ef_check(notify_chat=None):
    seen = load_seen(); count = 0
    cfg = load_config()
    extractor = cfg.get("ef_extractor", "hubcloud")
    try:
        for post in reversed(get_ef_posts()):
            if post["url"] in seen: continue
            files = get_ef_final_links(post["url"], post["title"], extractor)
            for f in files: send_to_telegram(f, "ef"); count += 1; time.sleep(2)
            seen.add(post["url"]); save_seen(seen)
        if notify_chat: bot.send_message(notify_chat, f"EF done. {count} sent.")
    except Exception as e:
        if notify_chat: bot.send_message(notify_chat, f"EF error: {e}")

def run_ff_check(notify_chat=None):
    seen = load_seen(); count = 0
    try:
        for post in reversed(get_ff_posts()):
            if post["url"] in seen: continue
            files = get_ff_links(post["url"])
            for f in files: send_to_telegram(f, "ff"); count += 1; time.sleep(2)
            seen.add(post["url"]); save_seen(seen)
        if notify_chat: bot.send_message(notify_chat, f"FF done. {count} sent.")
    except Exception as e:
        if notify_chat: bot.send_message(notify_chat, f"FF error: {e}")

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
