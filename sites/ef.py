# -*- coding: utf-8 -*-
# ================= EXTRAFLIX =================

import re
import requests
from bs4 import BeautifulSoup

from bot import load_config, clean_title


def get_ef_posts():
    cfg = load_config()
    url = cfg.get("ef_url", "https://e3.extraflix.mobi/")
    try:
        r = requests.get(url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
        soup = BeautifulSoup(r.text, "html.parser")
        movies = []
        for article in soup.select("article"):
            if "category-movies" not in article.get("class", []):
                continue
            a = article.select_one("h2.entry-title a")
            if a:
                movies.append({"title": a.get_text(strip=True), "url": a["href"]})
        return movies
    except Exception as e:
        print("EF POSTS ERROR:", e)
        return []


def get_ef_linkshub_links(movie_url):
    """Movie page se linkshub links nikalo"""
    r = requests.get(movie_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    return re.findall(r'https://links\.linkshub\.fun/view/[A-Za-z0-9]+', r.text)


def get_ef_hubcloud(linkshub_url):
    """Linkshub page se hubcloud link + title nikalo"""
    r = requests.get(linkshub_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=60)
    html = r.text
    hub   = re.search(r'https://hubcloud\.foo/drive/[A-Za-z0-9]+', html)
    title = re.search(r'<title>(.*?)</title>', html, re.I | re.S)
    if not hub:
        return None
    filename = title.group(1).strip() if title else "Movie.mkv"
    # Clean ExtraFlix watermark from filename
    filename = re.sub(r"[-_. ]*ExtraFlix\.Pw", "", filename, flags=re.I)
    filename = re.sub(r"\.mkv$", ".Esub.mkv", filename, flags=re.I)
    return {"title": clean_title(filename, "ef"), "link": hub.group(0)}


def get_ef_final_links(movie_url, post_title, extractor="hubcloud"):
    """Main function — movie URL se final download links lo"""
    results = []
    try:
        linkshubs = get_ef_linkshub_links(movie_url)
        for ls_url in linkshubs:
            try:
                data = get_ef_hubcloud(ls_url)
                if data:
                    results.append(data)
            except Exception as e:
                print("EF HUBCLOUD ERROR:", e)
    except Exception as e:
        print("EF FINAL ERROR:", e)
    return results
