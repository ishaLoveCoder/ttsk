# -*- coding: utf-8 -*-

import re
import json
import time
import os
import requests
import telebot
from bs4 import BeautifulSoup
from urllib.parse import urljoin

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
POST_CHAT_ID = int(os.getenv("POST_CHAT_ID"))
TAG_USER_ID = int(os.getenv("TAG_USER_ID"))
TAG_USERNAME = os.getenv("TAG_USERNAME", "@username")
SITE_URL = os.getenv("SITE_URL", "https://skymovieshd.fast/")
CHECK_INTERVAL = int(os.getenv("CHECK_INTERVAL", "900"))
DB_FILE = "seen_posts.json"
# ==========================================

bot = telebot.TeleBot(BOT_TOKEN, parse_mode="HTML")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Linux; Android 10; Mobile)",
    "Referer": SITE_URL
}


# ---------- DATABASE ----------
def load_seen():
    try:
        with open(DB_FILE, "r", encoding="utf-8") as f:
            return set(json.load(f))
    except:
        return set()


def save_seen(seen):
    with open(DB_FILE, "w", encoding="utf-8") as f:
        json.dump(list(seen), f)


# ---------- TITLE CLEANER ----------
def clean_movie_title(title):
    title = title.replace("Download ", "").strip()

    title = re.sub(r'\s*\[[^\]]*(?:MB|GB)[^\]]*\]', '', title, flags=re.I)

    title = re.sub(r'\s+', ' ', title).strip()

    title = re.sub(r'(\.mkv|\.mp4|\.avi)$', '', title, flags=re.I)

    return title + ".mkv"


# ---------- STEP 1 ----------
def get_latest_posts():
    r = requests.get(SITE_URL, headers=HEADERS, timeout=20)
    soup = BeautifulSoup(r.text, "lxml")

    posts = []

    for a in soup.select("div.Fmvideo a[href*='movie/']"):
        href = a.get("href", "").strip()
        title = a.get_text(" ", strip=True)

        if not href or not title:
            continue

        full_url = urljoin(SITE_URL, href)

        if full_url not in [x["url"] for x in posts]:
            posts.append({
                "title": title,
                "url": full_url
            })

    return posts


# ---------- STEP 2 ----------
def extract_gdflix_link(movie_url):
    r = requests.get(movie_url, headers=HEADERS, timeout=20)
    html = r.text

    title_match = re.search(
        r"<div class='Robiul'>\s*Download\s*(.*?)</div>",
        html,
        re.S | re.I
    )

    if title_match:
        raw_title = BeautifulSoup(
            title_match.group(1),
            "lxml"
        ).get_text(" ", strip=True)

    else:
        title_match = re.search(
            r"<title>\s*(.*?)\s*Full Movie Download",
            html,
            re.I
        )

        raw_title = title_match.group(1).strip() if title_match else "Unknown Movie"

    gdrive_match = re.search(
        r'<a href=[\'"]([^\'"]+)[\'"]>\s*Google Drive Direct Links\s*</a>',
        html,
        re.I
    )

    if not gdrive_match:
        return None

    protected_url = gdrive_match.group(1).strip()

    r2 = requests.get(
        protected_url,
        headers={
            "User-Agent": HEADERS["User-Agent"],
            "Referer": movie_url
        },
        timeout=20
    )

    protected_html = r2.text

    gdflix_patterns = [
        r'https?://gdflix\.[^\s"\'<>]+',
        r'https?://gdlink\.[^\s"\'<>]+'
    ]

    final_link = None

    for pattern in gdflix_patterns:
        matches = re.findall(pattern, protected_html, re.I)

        if matches:
            final_link = matches[0].strip()
            break

    if not final_link:
        return None

    return {
        "title": clean_movie_title(raw_title),
        "link": final_link
    }


# ---------- TELEGRAM ----------
def send_to_telegram(data):
    message = (
        f"/l2 {data['link']} -n {data['title']}\n"
        f"Tag: {TAG_USERNAME} {TAG_USER_ID}"
    )

    bot.send_message(POST_CHAT_ID, message)


# ---------- MAIN ----------
def main():
    print("Bot Started...")
    seen = load_seen()

    while True:
        try:
            posts = get_latest_posts()

            for post in reversed(posts):
                if post["url"] in seen:
                    continue

                print("New Post Found:", post["title"])

                data = extract_gdflix_link(post["url"])

                if data:
                    send_to_telegram(data)
                    print("Sent:", data["title"])

                seen.add(post["url"])
                save_seen(seen)

                time.sleep(3)

        except Exception as e:
            print("Error:", e)

        time.sleep(CHECK_INTERVAL)
