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
ADMIN_ID   = int(os.getenv("ADMIN_ID", "0"))   # Sirf yahi ID commands use kar sakti hai

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
            "sky_domain": "https://skymovieshd.fast/",
            "hdm_rss": "https://hdmovie2.com.se/movies/feed/",
            "interval": 900,
            "tag_username": "@username",
            "tag_id": 123456789,
            "channels": [],
            "sky_enabled": True,
            "hdm_enabled": True
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

def admin_only(func):
    def wrapper(message):
        if not is_admin(message):
            bot.reply_to(message, "❌ Sirf admin yeh command use kar sakta hai.")
            return
        func(message)
    return wrapper

# ================= TITLE CLEANER =================
def clean_title(title):
    # GDFlix | prefix hata do
    title = re.sub(r'^GDFlix\s*\|\s*', '', title, flags=re.I).strip()

    # [www.anything.com] hata do
    title = re.sub(r'\s*\[www\.[^\]]+\]\s*', ' ', title, flags=re.I).strip()

    # Download prefix hata do
    title = re.sub(r'^Download\s+', '', title, flags=re.I).strip()

    # Size brackets [500MB] etc hata do
    title = re.sub(r'\s*\[[^\]]*(?:MB|GB)[^\]]*\]', '', title, flags=re.I).strip()

    # Extension hata do
    title = re.sub(r'\.(mkv|mp4|avi)$', '', title, flags=re.I).strip()

    # Multiple spaces
    title = re.sub(r'\s+', ' ', title).strip()

    # Esub add karo agar nahi hai
    if "esub" not in title.lower():
        title += " Esub"

    return title + ".mkv"

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

def extract_gofile_link(movie_url):
    cfg = load_config()
    HEADERS["Referer"] = cfg["sky_domain"]
    r = requests.get(movie_url, headers=HEADERS, timeout=20)
    html = r.text

    title_match = re.search(r"<div class='Robiul'>\s*Download\s*(.*?)</div>", html, re.S | re.I)
    if title_match:
        raw_title = BeautifulSoup(title_match.group(1), "lxml").get_text(" ", strip=True)
    else:
        title_match = re.search(r"<title>\s*(.*?)\s*Full Movie Download", html, re.I)
        raw_title = title_match.group(1).strip() if title_match else "Unknown Movie"

    gdrive_match = re.search(
        r'<a href=[\'"]([^\'"]+)[\'"]>\s*Google Drive Direct Links\s*</a>', html, re.I
    )
    if not gdrive_match:
        return None

    protected_url = gdrive_match.group(1).strip()
    r2 = requests.get(protected_url, headers={"User-Agent": HEADERS["User-Agent"], "Referer": movie_url},
                      timeout=20, allow_redirects=True)

    gofile_matches = re.findall(r'https?://gofile\.io/d/[A-Za-z0-9]+', r2.text, re.I)
    if not gofile_matches:
        return None

    return {"title": clean_title(raw_title), "link": gofile_matches[0].strip()}

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
                final.append({"title": clean_title(raw_title), "link": final_url})
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

    # Tag line — brackets ke bina
    tag_line = f"Tag: {cfg['tag_username']} {cfg['tag_id']}"

    message = f"/l2 {data['link']} -n {data['title']}\n\n{tag_line}"

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
    if not is_admin(message):
        return
    text = (
        "🤖 <b>RSS Bot Commands</b>\n\n"
        "<b>Manual Check:</b>\n"
        "/sky -l — SkyMovies instant check\n"
        "/hdm -l — HDMovie2 instant check\n\n"
        "<b>Domain Change:</b>\n"
        "/setsky https://newdomain.com/\n"
        "/sethdm https://newrss.com/feed/\n\n"
        "<b>Interval:</b>\n"
        "/settime 300 — 5 min\n"
        "/settime 1800 — 30 min\n\n"
        "<b>Enable/Disable:</b>\n"
        "/sky on | /sky off\n"
        "/hdm on | /hdm off\n\n"
        "<b>Channel:</b>\n"
        "/setchat -100xxxxxxxx\n"
        "/addchat -100xxxxxxxx\n\n"
        "<b>Tag:</b>\n"
        "/settag @username\n"
        "/settagid 123456789\n\n"
        "<b>Info:</b>\n"
        "/settings — current config\n"
        "/status — last/next check time\n"
        "/stats — today's post count\n"
        "/latestsky — preview sky posts\n"
        "/latesthdm — preview hdm posts"
    )
    bot.reply_to(message, text)

@bot.message_handler(commands=["sky"])
def cmd_sky(message):
    if not is_admin(message): return
    parts = message.text.strip().split()
    cfg = load_config()

    if len(parts) >= 2:
        arg = parts[1].lower()
        if arg == "on":
            cfg["sky_enabled"] = True
            save_config(cfg)
            bot.reply_to(message, "✅ SkyMovies RSS <b>ON</b>")
        elif arg == "off":
            cfg["sky_enabled"] = False
            save_config(cfg)
            bot.reply_to(message, "🔴 SkyMovies RSS <b>OFF</b>")
        elif arg == "-l":
            bot.reply_to(message, "⚡ SkyMovies instant check shuru...")
            threading.Thread(target=run_sky_check, args=(message.chat.id,), daemon=True).start()

@bot.message_handler(commands=["hdm"])
def cmd_hdm(message):
    if not is_admin(message): return
    parts = message.text.strip().split()
    cfg = load_config()

    if len(parts) >= 2:
        arg = parts[1].lower()
        if arg == "on":
            cfg["hdm_enabled"] = True
            save_config(cfg)
            bot.reply_to(message, "✅ HDMovie2 RSS <b>ON</b>")
        elif arg == "off":
            cfg["hdm_enabled"] = False
            save_config(cfg)
            bot.reply_to(message, "🔴 HDMovie2 RSS <b>OFF</b>")
        elif arg == "-l":
            bot.reply_to(message, "⚡ HDMovie2 instant check shuru...")
            threading.Thread(target=run_hdm_check, args=(message.chat.id,), daemon=True).start()

@bot.message_handler(commands=["setsky"])
def cmd_setsky(message):
    if not is_admin(message): return
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /setsky https://newdomain.com/")
        return
    cfg = load_config()
    cfg["sky_domain"] = parts[1].strip()
    save_config(cfg)
    bot.reply_to(message, f"✅ Sky domain set:\n<code>{cfg['sky_domain']}</code>")

@bot.message_handler(commands=["sethdm"])
def cmd_sethdm(message):
    if not is_admin(message): return
    parts = message.text.strip().split(maxsplit=1)
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /sethdm https://newrss.com/feed/")
        return
    cfg = load_config()
    cfg["hdm_rss"] = parts[1].strip()
    save_config(cfg)
    bot.reply_to(message, f"✅ HDM RSS set:\n<code>{cfg['hdm_rss']}</code>")

@bot.message_handler(commands=["settime"])
def cmd_settime(message):
    if not is_admin(message): return
    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].isdigit():
        bot.reply_to(message, "Usage: /settime 300")
        return
    cfg = load_config()
    cfg["interval"] = int(parts[1])
    save_config(cfg)
    bot.reply_to(message, f"✅ Interval set: <b>{cfg['interval']} seconds</b>")

@bot.message_handler(commands=["setchat"])
def cmd_setchat(message):
    if not is_admin(message): return
    parts = message.text.strip().split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /setchat -100xxxxxxxx")
        return
    cfg = load_config()
    cfg["channels"] = [int(parts[1])]
    save_config(cfg)
    bot.reply_to(message, f"✅ Channel set: <code>{parts[1]}</code>")

@bot.message_handler(commands=["addchat"])
def cmd_addchat(message):
    if not is_admin(message): return
    parts = message.text.strip().split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /addchat -100xxxxxxxx")
        return
    cfg = load_config()
    chat_id = int(parts[1])
    if chat_id not in cfg["channels"]:
        cfg["channels"].append(chat_id)
        save_config(cfg)
        bot.reply_to(message, f"✅ Channel added: <code>{parts[1]}</code>")
    else:
        bot.reply_to(message, "⚠️ Channel already hai list mein.")

@bot.message_handler(commands=["settag"])
def cmd_settag(message):
    if not is_admin(message): return
    parts = message.text.strip().split()
    if len(parts) < 2:
        bot.reply_to(message, "Usage: /settag @username")
        return
    cfg = load_config()
    cfg["tag_username"] = parts[1]
    save_config(cfg)
    bot.reply_to(message, f"✅ Tag username set: <b>{parts[1]}</b>")

@bot.message_handler(commands=["settagid"])
def cmd_settagid(message):
    if not is_admin(message): return
    parts = message.text.strip().split()
    if len(parts) < 2 or not parts[1].lstrip("-").isdigit():
        bot.reply_to(message, "Usage: /settagid 123456789")
        return
    cfg = load_config()
    cfg["tag_id"] = int(parts[1])
    save_config(cfg)
    bot.reply_to(message, f"✅ Tag ID set: <b>{parts[1]}</b>")

@bot.message_handler(commands=["settings"])
def cmd_settings(message):
    if not is_admin(message): return
    cfg = load_config()
    channels_str = ", ".join(str(c) for c in cfg["channels"]) or "Default (POST_CHAT_ID)"
    text = (
        f"⚙️ <b>Current Settings</b>\n\n"
        f"🌐 Sky Domain: <code>{cfg['sky_domain']}</code>\n"
        f"📡 HDM RSS: <code>{cfg['hdm_rss']}</code>\n"
        f"⏱ Interval: <b>{cfg['interval']}s</b>\n"
        f"🏷 Tag: <b>{cfg['tag_username']}</b> {cfg['tag_id']}\n"
        f"📢 Channels: <code>{channels_str}</code>\n"
        f"🟢 Sky: {'ON' if cfg['sky_enabled'] else 'OFF'}\n"
        f"🟢 HDM: {'ON' if cfg['hdm_enabled'] else 'OFF'}"
    )
    bot.reply_to(message, text)

@bot.message_handler(commands=["status"])
def cmd_status(message):
    if not is_admin(message): return
    cfg = load_config()

    def fmt_time(t):
        if not t: return "Abhi tak nahi"
        diff = int(time.time() - t)
        if diff < 60: return f"{diff} sec ago"
        return f"{diff // 60} min ago"

    def fmt_next(t):
        if not t: return "Unknown"
        diff = int(t - time.time())
        if diff <= 0: return "Abhi"
        if diff < 60: return f"{diff} sec"
        return f"{diff // 60} min"

    text = (
        f"📊 <b>Bot Status</b>\n\n"
        f"🔵 Sky Last Check: {fmt_time(last_check['sky'])}\n"
        f"🔵 HDM Last Check: {fmt_time(last_check['hdm'])}\n\n"
        f"⏭ Next Sky Check: {fmt_next(next_check['sky'])}\n"
        f"⏭ Next HDM Check: {fmt_next(next_check['hdm'])}\n\n"
        f"⏱ Interval: {cfg['interval']}s"
    )
    bot.reply_to(message, text)

@bot.message_handler(commands=["stats"])
def cmd_stats(message):
    if not is_admin(message): return
    stats = load_stats()
    total = stats.get("sky", 0) + stats.get("hdm", 0)
    text = (
        f"📈 <b>Today's Stats ({stats.get('date', 'N/A')})</b>\n\n"
        f"🎬 SkyMovies: <b>{stats.get('sky', 0)}</b>\n"
        f"🎬 HDMovie2: <b>{stats.get('hdm', 0)}</b>\n\n"
        f"📦 Total: <b>{total}</b>"
    )
    bot.reply_to(message, text)

@bot.message_handler(commands=["latestsky"])
def cmd_latestsky(message):
    if not is_admin(message): return
    bot.reply_to(message, "🔍 Latest Sky posts fetch ho rahe hain...")
    try:
        posts = get_sky_posts()[:5]
        if not posts:
            bot.reply_to(message, "Koi post nahi mila.")
            return
        text = "🎬 <b>Latest SkyMovies Posts (preview):</b>\n\n"
        for p in posts:
            text += f"• {p['title']}\n<code>{p['url']}</code>\n\n"
        bot.send_message(message.chat.id, text)
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

@bot.message_handler(commands=["latesthdm"])
def cmd_latesthdm(message):
    if not is_admin(message): return
    bot.reply_to(message, "🔍 Latest HDM posts fetch ho rahe hain...")
    try:
        posts = get_hdm_posts()[:5]
        if not posts:
            bot.reply_to(message, "Koi post nahi mila.")
            return
        text = "🎬 <b>Latest HDMovie2 Posts (preview):</b>\n\n"
        for p in posts:
            text += f"• {p['title']}\n<code>{p['url']}</code>\n\n"
        bot.send_message(message.chat.id, text)
    except Exception as e:
        bot.reply_to(message, f"Error: {e}")

# ================= INSTANT CHECK FUNCTIONS =================
def run_sky_check(notify_chat=None):
    seen = load_seen()
    cfg = load_config()
    try:
        posts = get_sky_posts()
        count = 0
        for post in reversed(posts):
            if post["url"] in seen:
                continue
            data = extract_gofile_link(post["url"])
            if data:
                send_to_telegram(data, "sky")
                count += 1
            seen.add(post["url"])
            save_seen(seen)
            time.sleep(2)
        if notify_chat:
            bot.send_message(notify_chat, f"✅ Sky check done. {count} new posts sent.")
    except Exception as e:
        if notify_chat:
            bot.send_message(notify_chat, f"❌ Sky check error: {e}")

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
                    used.add(x["link"])
                    unique.append(x)
            for file in unique:
                send_to_telegram(file, "hdm")
                count += 1
                time.sleep(2)
            seen.add(post["url"])
            save_seen(seen)
        if notify_chat:
            bot.send_message(notify_chat, f"✅ HDM check done. {count} new posts sent.")
    except Exception as e:
        if notify_chat:
            bot.send_message(notify_chat, f"❌ HDM check error: {e}")

# ================= MAIN LOOP =================
def main():
    print("Bot Started...")

    # Bot polling thread
    threading.Thread(target=bot.infinity_polling, daemon=True).start()

    seen = load_seen()

    while True:
        cfg = load_config()
        interval = cfg.get("interval", 900)

        try:
            # --- SKYMOVIES ---
            if cfg.get("sky_enabled", True):
                last_check["sky"] = time.time()
                sky_posts = get_sky_posts()
                for post in reversed(sky_posts):
                    if post["url"] in seen:
                        continue
                    print("[SKY] New:", post["title"])
                    data = extract_gofile_link(post["url"])
                    if data:
                        send_to_telegram(data, "sky")
                        print("[SKY] Sent:", data["title"])
                    seen.add(post["url"])
                    save_seen(seen)
                    time.sleep(3)

            # --- HDMOVIE2 ---
            if cfg.get("hdm_enabled", True):
                last_check["hdm"] = time.time()
                hd_posts = get_hdm_posts()
                for post in reversed(hd_posts):
                    if post["url"] in seen:
                        continue
                    print("[HDMOVIE2] New:", post["title"])
                    hdm_links = get_hdm_links(post["url"])
                    all_files = []
                    for item in hdm_links:
                        all_files.extend(extract_gdflix_data(item["url"]))
                    unique = []
                    used = set()
                    for x in all_files:
                        if x["link"] not in used:
                            used.add(x["link"])
                            unique.append(x)
                    for file in unique:
                        send_to_telegram(file, "hdm")
                        print("[HDMOVIE2] Sent:", file["title"])
                        time.sleep(2)
                    seen.add(post["url"])
                    save_seen(seen)

        except Exception as e:
            print("MAIN ERROR:", e)

        # Next check time update
        next_check["sky"] = time.time() + interval
        next_check["hdm"] = time.time() + interval

        print(f"Sleeping {interval}s...")
        time.sleep(interval)


if __name__ == "__main__":
    main()
