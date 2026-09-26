# -*- coding: utf-8 -*-
# ================= HDMOVIE2 =================

import re
import requests
import feedparser
from bs4 import BeautifulSoup

from bot import load_config, clean_title, fetch_title_via_jina, HEADERS


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
            href = a["href"]
            if "gdflix" not in href.lower(): continue
            try:
                jina_title = fetch_title_via_jina(href)
                if jina_title:
                    raw_title = jina_title
                    final_url = href
                else:
                    r2 = requests.get(href, headers=HEADERS, allow_redirects=True, timeout=20)
                    tm = re.search(r"<title>(.*?)</title>", r2.text, re.I)
                    raw_title = tm.group(1) if tm else "Unknown"
                    final_url = r2.url
                final.append({"title": clean_title(raw_title, "hdm"), "link": final_url})
            except Exception as e:
                print("GD ERROR:", e)
        return final
    except Exception as e:
        print("HDM FINAL ERROR:", e); return []
