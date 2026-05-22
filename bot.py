# -*- coding: utf-8 -*-
import re
import json
import time
import os
import requests
import telebot
import feedparser
import threading
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin
from config_manager import load_config, save_config, update_config

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
# Initial Admin ID from env, but can be updated or locked
ADMIN_ID = int(os.getenv("ADMIN_ID", "0")) 

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")
DB_FILE = "seen_posts.json"

# Global state for tracking last checks
last_check_times = {"sky": 0, "hdm": 0}
force_check = {"sky": False, "hdm": False}

# ==========================================
# HELPERS
# ==========================================

def get_headers(site_url):
    return {
        "User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile)",
        "Referer": site_url
    }

def load_seen():
    try:
        if os.path.exists(DB_FILE):
            with open(DB_FILE, "r", encoding="utf-8") as f:
                return set(json.load(f))
    except:
        pass
    return set()

def save_seen(seen):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f)

def clean_movie_title(title):
    # Remove site names and common prefixes
    title = re.sub(r'GDFlix\s*\|\s*', '', title, flags=re.I)
    title = title.replace("Download ", "").strip()
    
    # Remove URLs like [www.hdmovie4.com] or (www.hdmovie4.com)
    title = re.sub(r'\[.*?www\..*?\]', '', title, flags=re.I)
    title = re.sub(r'\(.*?www\..*?\)', '', title, flags=re.I)
    
    # Remove file extensions if they exist in the middle
    title = re.sub(r'\.mkv|\.mp4|\.avi', '', title, flags=re.I)
    
    # Clean up brackets with MB/GB
    title = re.sub(r'\s*\[[^\]]*(?:MB|GB)[^\]]*\]', '', title, flags=re.I)
    
    # Clean up multiple spaces
    title = re.sub(r'\s+', ' ', title).strip()
    
    # Ensure Esub is present (but not duplicated)
    if "esub" not in title.lower():
        title += " Esub"
    
    # Return with .mkv extension
    return title + ".mkv"

def is_admin(message):
    config = load_config()
    if config["admin_id"] == 0:
        # First user becomes admin if not set
        update_config("admin_id", message.from_user.id)
        return True
    return message.from_user.id == config["admin_id"]

# ==========================================
# SCRAPERS
# ==========================================

def get_latest_posts():
    config = load_config()
    try:
        r = requests.get(config["sky_domain"], headers=get_headers(config["sky_domain"]), timeout=20)
        soup = BeautifulSoup(r.text, "lxml")
        posts = []
        for a in soup.select("div.Fmvideo a[href*='movie/']"):
            href = a.get("href", "").strip()
            title = a.get_text(" ", strip=True)
            if not href or not title: continue
            full_url = urljoin(config["sky_domain"], href)
            if full_url not in [x["url"] for x in posts]:
                posts.append({"title": title, "url": full_url})
        return posts
    except Exception as e:
        print("SKY SCRAPE ERROR:", e)
        return []

def get_hdmovie2_posts():
    config = load_config()
    try:
        feed = feedparser.parse(config["hdm_rss"])
        posts = []
        for entry in feed.entries:
            posts.append({"title": entry.title, "url": entry.link})
        return posts
    except Exception as e:
        print("HDM RSS ERROR:", e)
        return []

def extract_gofile_link(movie_url):
    config = load_config()
    try:
        r = requests.get(movie_url, headers=get_headers(config["sky_domain"]), timeout=20)
        html = r.text
        title_match = re.search(r"<div class='Robiul'>\s*Download\s*(.*?)</div>", html, re.S | re.I)
        if title_match:
            raw_title = BeautifulSoup(title_match.group(1), "lxml").get_text(" ", strip=True)
        else:
            title_match = re.search(r"<title>\s*(.*?)\s*Full Movie Download", html, re.I)
            raw_title = title_match.group(1).strip() if title_match else "Unknown Movie"
        
        gdrive_match = re.search(r'<a href=[\'"]([^\'"]+)[\'"]>\s*Google Drive Direct Links\s*</a>', html, re.I)
        if not gdrive_match: return None
        
        protected_url = gdrive_match.group(1).strip()
        r2 = requests.get(protected_url, headers={"User-Agent": "Mozilla/5.0", "Referer": movie_url}, timeout=20, allow_redirects=True)
        
        gofile_patterns = [r'https?://gofile\.io/d/[A-Za-z0-9]+']
        final_link = None
        for pattern in gofile_patterns:
            matches = re.findall(pattern, r2.text, re.I)
            if matches:
                final_link = matches[0].strip()
                break
        if not final_link: return None
        return {"title": clean_movie_title(raw_title), "link": final_link}
    except Exception as e:
        print("GOFILE EXTRACT ERROR:", e)
        return None

def get_hdm_links(movie_url):
    try:
        r = requests.get(movie_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        links = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "hdm.im" in href:
                text = a.get_text(" ", strip=True)
                links.append({"label": text, "url": href})
        return links
    except Exception as e:
        print("HDM LINKS ERROR:", e)
        return []

def extract_gdflix_data(hdm_url):
    try:
        r = requests.get(hdm_url, headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True, timeout=20)
        soup = BeautifulSoup(r.text, "html.parser")
        final = []
        for a in soup.find_all("a", href=True):
            href = a["href"]
            if "gdflix" not in href.lower(): continue
            try:
                r2 = requests.get(href, headers={"User-Agent": "Mozilla/5.0"}, allow_redirects=True, timeout=20)
                final_url = r2.url
                title_match = re.search(r"<title>(.*?)</title>", r2.text, re.I)
                raw_title = title_match.group(1) if title_match else "Unknown"
                final.append({"title": clean_movie_title(raw_title), "link": final_url})
            except: continue
        return final
    except Exception as e:
        print("GD DATA ERROR:", e)
        return []

# ==========================================
# TELEGRAM SEND
# ==========================================

def send_to_telegram(data, source="sky"):
    config = load_config()
    # Removed brackets from tag_id as requested
    message = (
        f"/l2 {data['link']} -n {data['title']}\n\n"
        f"Tag: {config['tag_username']} {config['tag_id']}"
    )
    
    # Send to all channels
    for chat_id in config["channels"]:
        try:
            bot.send_message(chat_id, message)
        except Exception as e:
            print(f"Error sending to {chat_id}: {e}")
            
    # Update stats
    today = datetime.now().strftime("%Y-%m-%d")
    if config["stats"].get("last_reset") != today:
        config["stats"] = {"today_sky": 0, "today_hdm": 0, "last_reset": today}
    
    if source == "sky":
        config["stats"]["today_sky"] += 1
    else:
        config["stats"]["today_hdm"] += 1
    
    save_config(config)

# ==========================================
# COMMAND HANDLERS
# ==========================================

@bot.message_handler(commands=['start'])
def cmd_start(message):
    bot.reply_to(message, "Bot is running. Use /settings to see config.")

@bot.message_handler(commands=['settings'])
def cmd_settings(message):
    if not is_admin(message): return
    config = load_config()
    text = (
        f"<b>Current Settings:</b>\n"
        f"Sky Domain: {config['sky_domain']}\n"
        f"HDM RSS: {config['hdm_rss']}\n"
        f"RSS Time: {config['interval']}s\n"
        f"Tag Username: {config['tag_username']}\n"
        f"Tag ID: {config['tag_id']}\n"
        f"Channels: {', '.join(map(str, config['channels']))}\n"
        f"Sky Status: {'ON' if config['sky_enabled'] else 'OFF'}\n"
        f"HDM Status: {'ON' if config['hdm_enabled'] else 'OFF'}"
    )
    bot.reply_to(message, text)

@bot.message_handler(commands=['status'])
def cmd_status(message):
    if not is_admin(message): return
    config = load_config()
    now = time.time()
    
    def format_time(last):
        if last == 0: return "Never"
        diff = int(now - last)
        if diff < 60: return f"{diff}s ago"
        return f"{diff // 60}m ago"

    next_sky = max(0, int(config['interval'] - (now - last_check_times['sky'])))
    next_hdm = max(0, int(config['interval'] - (now - last_check_times['hdm'])))

    text = (
        f"<b>RSS Status:</b>\n"
        f"Sky Last Check: {format_time(last_check_times['sky'])}\n"
        f"HDM Last Check: {format_time(last_check_times['hdm'])}\n\n"
        f"Next Sky Check: {next_sky // 60}m {next_sky % 60}s\n"
        f"Next HDM Check: {next_hdm // 60}m {next_hdm % 60}s"
    )
    bot.reply_to(message, text)

@bot.message_handler(commands=['stats'])
def cmd_stats(message):
    if not is_admin(message): return
    config = load_config()
    stats = config["stats"]
    text = (
        f"<b>Daily Stats ({stats.get('last_reset', 'N/A')}):</b>\n\n"
        f"SkyMovies: {stats.get('today_sky', 0)}\n"
        f"HDMovie2: {stats.get('today_hdm', 0)}\n\n"
        f"Total: {stats.get('today_sky', 0) + stats.get('today_hdm', 0)}"
    )
    bot.reply_to(message, text)

@bot.message_handler(commands=['sky'])
def cmd_sky(message):
    if not is_admin(message): return
    args = message.text.split()
    if len(args) < 2: return
    
    cmd = args[1].lower()
    if cmd == "-l":
        global force_check
        force_check["sky"] = True
        bot.reply_to(message, "SkyMovies force check triggered!")
    elif cmd == "on":
        update_config("sky_enabled", True)
        bot.reply_to(message, "SkyMovies RSS Enabled.")
    elif cmd == "off":
        update_config("sky_enabled", False)
        bot.reply_to(message, "SkyMovies RSS Disabled.")

@bot.message_handler(commands=['hdm'])
def cmd_hdm(message):
    if not is_admin(message): return
    args = message.text.split()
    if len(args) < 2: return
    
    cmd = args[1].lower()
    if cmd == "-l":
        global force_check
        force_check["hdm"] = True
        bot.reply_to(message, "HDMovie2 force check triggered!")
    elif cmd == "on":
        update_config("hdm_enabled", True)
        bot.reply_to(message, "HDMovie2 RSS Enabled.")
    elif cmd == "off":
        update_config("hdm_enabled", False)
        bot.reply_to(message, "HDMovie2 RSS Disabled.")

@bot.message_handler(commands=['setsky'])
def cmd_setsky(message):
    if not is_admin(message): return
    args = message.text.split()
    if len(args) < 2: return
    update_config("sky_domain", args[1])
    bot.reply_to(message, f"Sky Domain updated to: {args[1]}")

@bot.message_handler(commands=['sethdm'])
def cmd_sethdm(message):
    if not is_admin(message): return
    args = message.text.split()
    if len(args) < 2: return
    update_config("hdm_rss", args[1])
    bot.reply_to(message, f"HDM RSS updated to: {args[1]}")

@bot.message_handler(commands=['settime'])
def cmd_settime(message):
    if not is_admin(message): return
    args = message.text.split()
    if len(args) < 2: return
    try:
        t = int(args[1])
        update_config("interval", t)
        bot.reply_to(message, f"RSS Interval updated to {t}s")
    except:
        bot.reply_to(message, "Invalid number.")

@bot.message_handler(commands=['setchat'])
def cmd_setchat(message):
    if not is_admin(message): return
    args = message.text.split()
    if len(args) < 2: return
    try:
        chat_id = int(args[1])
        update_config("channels", [chat_id])
        bot.reply_to(message, f"Primary channel set to: {chat_id}")
    except:
        bot.reply_to(message, "Invalid Chat ID.")

@bot.message_handler(commands=['addchat'])
def cmd_addchat(message):
    if not is_admin(message): return
    args = message.text.split()
    if len(args) < 2: return
    try:
        chat_id = int(args[1])
        config = load_config()
        if chat_id not in config["channels"]:
            config["channels"].append(chat_id)
            save_config(config)
            bot.reply_to(message, f"Added channel: {chat_id}")
        else:
            bot.reply_to(message, "Channel already exists.")
    except:
        bot.reply_to(message, "Invalid Chat ID.")

@bot.message_handler(commands=['settag'])
def cmd_settag(message):
    if not is_admin(message): return
    args = message.text.split()
    if len(args) < 2: return
    update_config("tag_username", args[1])
    bot.reply_to(message, f"Tag Username set to: {args[1]}")

@bot.message_handler(commands=['settagid'])
def cmd_settagid(message):
    if not is_admin(message): return
    args = message.text.split()
    if len(args) < 2: return
    try:
        tag_id = int(args[1])
        update_config("tag_id", tag_id)
        bot.reply_to(message, f"Tag ID set to: {tag_id}")
    except:
        bot.reply_to(message, "Invalid ID.")

@bot.message_handler(commands=['latestsky'])
def cmd_latestsky(message):
    if not is_admin(message): return
    bot.reply_to(message, "Fetching latest SkyMovies posts (Preview)...")
    posts = get_latest_posts()
    if not posts:
        bot.send_message(message.chat.id, "No posts found.")
        return
    text = "<b>Latest SkyMovies:</b>\n\n"
    for p in posts[:5]:
        text += f"• {p['title']}\n"
    bot.send_message(message.chat.id, text)

@bot.message_handler(commands=['latesthdm'])
def cmd_latesthdm(message):
    if not is_admin(message): return
    bot.reply_to(message, "Fetching latest HDMovie2 posts (Preview)...")
    posts = get_hdmovie2_posts()
    if not posts:
        bot.send_message(message.chat.id, "No posts found.")
        return
    text = "<b>Latest HDMovie2:</b>\n\n"
    for p in posts[:5]:
        text += f"• {p['title']}\n"
    bot.send_message(message.chat.id, text)

# ==========================================
# BACKGROUND LOOP
# ==========================================

def rss_loop():
    print("RSS Loop Started...")
    seen = load_seen()
    while True:
        try:
            config = load_config()
            now = time.time()
            
            # ---------------- SKYMOVIES ----------------
            if config["sky_enabled"] and (now - last_check_times["sky"] >= config["interval"] or force_check["sky"]):
                print("[SKY] Checking...")
                last_check_times["sky"] = now
                force_check["sky"] = False
                
                sky_posts = get_latest_posts()
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

            # ---------------- HDMOVIE2 ----------------
            if config["hdm_enabled"] and (now - last_check_times["hdm"] >= config["interval"] or force_check["hdm"]):
                print("[HDM] Checking...")
                last_check_times["hdm"] = now
                force_check["hdm"] = False
                
                hd_posts = get_hdmovie2_posts()
                for post in reversed(hd_posts):
                    if post["url"] in seen:
                        continue
                    print("[HDMOVIE2] New:", post["title"])
                    hdm_links = get_hdm_links(post["url"])
                    all_files = []
                    for item in hdm_links:
                        files = extract_gdflix_data(item["url"])
                        all_files.extend(files)
                    
                    unique = []
                    used = set()
                    for x in all_files:
                        if x["link"] in used: continue
                        used.add(x["link"])
                        unique.append(x)
                        
                    for file in unique:
                        send_to_telegram(file, "hdm")
                        print("[HDMOVIE2] Sent:", file["title"])
                        time.sleep(2)
                    seen.add(post["url"])
                    save_seen(seen)

        except Exception as e:
            print("LOOP ERROR:", e)
        
        time.sleep(10) # Short sleep to check for force_check or config updates

def main():
    # Initialize Admin ID if not set in config but exists in env
    config = load_config()
    if config["admin_id"] == 0 and ADMIN_ID != 0:
        update_config("admin_id", ADMIN_ID)
    
    # Start RSS Loop in thread
    threading.Thread(target=rss_loop, daemon=True).start()
    
    # Start Bot Polling
    print("Bot Polling Started...")
    bot.infinity_polling()

if __name__ == "__main__":
    main()
