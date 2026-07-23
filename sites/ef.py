# -*- coding: utf-8 -*-
# ================= EXTRAFLIX =================

import re
import requests
from bs4 import BeautifulSoup

from bot import load_config, clean_title

_session = requests.Session()
_session.headers.update({"User-Agent": "Mozilla/5.0"})

_BLOCKED = re.compile(r'\bUNRATED\b', re.I)


def _clean_ef_filename(name):
    name = re.sub(r"[-_. ]*ExtraFlix\.Pw", "", name, flags=re.I)
    name = re.sub(r"\s*-\s*[\d.]+\s*(MB|GB)\s*$", "", name, flags=re.I)
    if not re.search(r"\.(mkv|mp4|avi)$", name, re.I):
        name += ".mkv"
    name = re.sub(r"\.mkv$", ".Esub.mkv", name, flags=re.I)
    return name.strip()


def get_ef_posts():
    cfg = load_config()
    url = cfg.get("ef_url", "https://e3.extraflix.mobi/")
    try:
        r = _session.get(url, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        movies = []
        for article in soup.select("article.category-movies"):
            a = article.select_one("h2.entry-title a")
            if not a or not a.get("href"): continue
            post_url   = a["href"]
            post_title = a.get_text(strip=True)
            # UNRATED filter
            if _BLOCKED.search(post_url) or _BLOCKED.search(post_title):
                print(f"[EF] Skipping UNRATED: {post_url}")
                continue
            movies.append({"title": post_title, "url": post_url})
        # deduplicate
        seen = set(); unique = []
        for m in movies:
            if m["url"] not in seen:
                seen.add(m["url"]); unique.append(m)
        return unique
    except Exception as e:
        print("EF POSTS ERROR:", e)
        return []


def get_ef_linkshub_links(movie_url):
    try:
        r = _session.get(movie_url, timeout=30)
        r.raise_for_status()
        links = re.findall(r'https://links\.linkshub\.fun/view/[A-Za-z0-9]+', r.text)
        return list(dict.fromkeys(links))
    except Exception as e:
        print("EF LINKSHUB FETCH ERROR:", e)
        return []


def get_ef_hubcloud(linkshub_url):
    try:
        r = _session.get(linkshub_url, timeout=30, allow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        html = r.text

        # Title: h2 preferred, fallback to <title>
        h2 = soup.find("h2")
        if h2:
            filename = h2.get_text(" ", strip=True)
        else:
            filename = soup.title.get_text(strip=True) if soup.title else "Movie.mkv"

        filename = _clean_ef_filename(filename)

        # Chain: hubdrive.tips → hubcloud
        hubdrive = re.search(r'https://hubdrive\.tips/file/\d+', html)
        if hubdrive:
            try:
                r2 = _session.get(hubdrive.group(0), timeout=30, allow_redirects=True)
                r2.raise_for_status()
                hc = re.search(r'https://hubcloud\.[^"\'<\s]+/drive/[A-Za-z0-9]+', r2.text)
                if hc:
                    return {"title": clean_title(filename, "ef"), "link": hc.group(0)}
            except Exception as e:
                print("EF HUBDRIVE ERROR:", e)

        # Direct hubcloud fallback
        direct = re.search(r'https://hubcloud\.[^"\'<\s]+/drive/[A-Za-z0-9]+', html)
        if direct:
            return {"title": clean_title(filename, "ef"), "link": direct.group(0)}

        return None
    except Exception as e:
        print("EF HUBCLOUD ERROR:", e)
        return None


def get_ef_final_links(movie_url, post_title, extractor="hubcloud"):
    # UNRATED check on movie URL too
    if _BLOCKED.search(movie_url) or _BLOCKED.search(post_title):
        print(f"[EF] Skipping UNRATED: {movie_url}")
        return []
    results = []
    linkshubs = get_ef_linkshub_links(movie_url)
    if not linkshubs:
        print(f"[EF] No linkshub links found: {movie_url}")
        return []
    for ls_url in linkshubs:
        data = get_ef_hubcloud(ls_url)
        if data:
            results.append(data)
    return results
