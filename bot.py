# -*- coding: utf-8 -*-

import re
import json
import time
import os
import requests
import telebot
import feedparser

from bs4 import BeautifulSoup
from urllib.parse import urljoin

# ================= CONFIG =================
BOT_TOKEN = os.getenv("BOT_TOKEN")
POST_CHAT_ID = int(os.getenv("POST_CHAT_ID"))
TAG_USER_ID = int(os.getenv("TAG_USER_ID"))
TAG_USERNAME = os.getenv("TAG_USERNAME", "@username")

SITE_URL = os.getenv("SITE_URL", "https://skymovieshd.fast/")
HDMOVIE_RSS = os.getenv("HDMOVIE_RSS", "https://hdmovie2.com.se/movies/feed/")

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

    if "esub" not in title.lower():
        title += " Esub"

    return title + ".mkv"


# =========================================================
# SKYMOVIES POSTS
# =========================================================
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
                "url": full_url,
                "source": "sky"
            })

    return posts


# =========================================================
# HDMOVIE2 RSS POSTS
# =========================================================
def get_hdmovie2_posts():

    feed = feedparser.parse(HDMOVIE_RSS)

    posts = []

    for item in feed.entries:

        posts.append({
            "title": item.title,
            "url": item.link,
            "source": "hdmovie2"
        })

    return posts


# =========================================================
# SKYMOVIES GOFILE EXTRACTOR
# =========================================================
def extract_gofile_link(movie_url):
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
        timeout=20,
        allow_redirects=True
    )

    protected_html = r2.text

    gofile_patterns = [
        r'https?://gofile\.io/d/[A-Za-z0-9]+'
    ]

    final_link = None

    for pattern in gofile_patterns:
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


# =========================================================
# HDMOVIE2 EXTRACTOR
# =========================================================
def get_hdm_links(movie_url):

    try:

        r = requests.get(
            movie_url,
            headers=HEADERS,
            timeout=20
        )

        soup = BeautifulSoup(r.text, "html.parser")

        links = []

        for a in soup.find_all("a", href=True):

            href = a["href"]

            if "hdm.im" in href:

                text = a.get_text(" ", strip=True)

                links.append({
                    "label": text,
                    "url": href
                })

        return links

    except Exception as e:
        print("HDM ERROR:", e)
        return []


# =========================================================
# HDMOVIE2 FINAL GDFLIX LINK
# =========================================================
def extract_gdflix_data(hdm_url):

    try:

        r = requests.get(
            hdm_url,
            headers=HEADERS,
            allow_redirects=True,
            timeout=20
        )

        soup = BeautifulSoup(r.text, "html.parser")

        final = []

        for a in soup.find_all("a", href=True):

            href = a["href"]

            if "gdflix" not in href.lower():
                continue

            try:

                r2 = requests.get(
                    href,
                    headers=HEADERS,
                    allow_redirects=True,
                    timeout=20
                )

                final_url = r2.url

                title_match = re.search(
                    r"<title>(.*?)</title>",
                    r2.text,
                    re.I
                )

                if not title_match:
                    continue

                raw_title = title_match.group(1)

                clean = clean_movie_title(raw_title)

                final.append({
                    "title": clean,
                    "link": final_url
                })

            except Exception as e:
                print("GD ERROR:", e)

        return final

    except Exception as e:
        print("FINAL ERROR:", e)
        return []


# =========================================================
# TELEGRAM SEND
# =========================================================
def send_to_telegram(data):

    message = (
        f"/l2 {data['link']} -n {data['title']}\n\n"
        f"Tag: {TAG_USERNAME} [{TAG_USER_ID}]"
    )

    bot.send_message(POST_CHAT_ID, message)


# =========================================================
# MAIN LOOP
# =========================================================
def main():
    print("Bot Started...")

    seen = load_seen()

    while True:

        try:

            # ---------------- SKYMOVIES ----------------
            sky_posts = get_latest_posts()

            for post in reversed(sky_posts):

                if post["url"] in seen:
                    continue

                print("[SKY] New:", post["title"])

                data = extract_gofile_link(post["url"])

                if data:
                    send_to_telegram(data)
                    print("[SKY] Sent:", data["title"])

                seen.add(post["url"])
                save_seen(seen)

                time.sleep(3)


            # ---------------- HDMOVIE2 ----------------
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

                    if x["link"] in used:
                        continue

                    used.add(x["link"])
                    unique.append(x)

                for file in unique:

                    send_to_telegram(file)

                    print("[HDMOVIE2] Sent:", file["title"])

                    time.sleep(2)

                seen.add(post["url"])
                save_seen(seen)


        except Exception as e:
            print("MAIN ERROR:", e)

        print("Sleeping...")
        time.sleep(CHECK_INTERVAL)


if __name__ == "__main__":
    main()
