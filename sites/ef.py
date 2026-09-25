# -*- coding: utf-8 -*-
# ================= EXTRAFLIX =================

import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote

from bot import load_config, clean_title

_session = requests.Session()
_session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"})

_BLOCKED = re.compile(r'\bUNRATED\b|\b18\+\b', re.I)

def _get_proxied_url(url):
    cfg = load_config()
    cf_worker = cfg.get("cf_worker_url", "")
    if cf_worker:
        return f"{cf_worker}?url={quote(url, safe='')}"
    return url

def _clean_ef_filename(name):
    name = re.sub(r"[-_. ]*ExtraFlix\.Pw", "", name, flags=re.I)
    name = re.sub(r"\s*-\s*[\d.]+\s*(MB|GB)\s*$", "", name, flags=re.I)
    if not re.search(r"\.(mkv|mp4|avi)$", name, re.I):
        name += ".mkv"
    name = re.sub(r"\.mkv$", ".Esub.mkv", name, flags=re.I)
    return name.strip()

def get_ef_posts(url=None):
    cfg = load_config()
    if not url:
        url = cfg.get("ef_url", "https://e3.extraflix.mobi/")

    try:
        fetch_url = _get_proxied_url(url)
        r = _session.get(fetch_url, timeout=30)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        movies = []

        for article in soup.select("article.category-movies"):
            a = article.select_one("h2.entry-title a")
            if not a or not a.get("href"): continue
            post_url = a["href"]
            post_title = a.get_text(strip=True)

            if _BLOCKED.search(post_url) or _BLOCKED.search(post_title):
                print(f"[EF] Skipping UNRATED: {post_url}")
                continue

            movies.append({"title": post_title, "url": post_url})

        seen = set()
        unique = []
        for m in movies:
            if m["url"] not in seen:
                seen.add(m["url"])
                unique.append(m)
        return unique

    except Exception as e:
        print("EF POSTS ERROR:", e)
        return []

def get_ef_linkshub_links(movie_url):
    try:
        fetch_url = _get_proxied_url(movie_url)
        r = _session.get(fetch_url, timeout=30)
        r.raise_for_status()
        links = re.findall(r'https://links\.linkshub\.fun/view/[A-Za-z0-9]+', r.text, re.I)
        return list(dict.fromkeys(links))
    except Exception as e:
        print("EF LINKSHUB FETCH ERROR:", e)
        return []

def get_ef_hubcloud(linkshub_url):
    try:
        fetch_url = _get_proxied_url(linkshub_url)
        r = _session.get(fetch_url, timeout=30, allow_redirects=True)
        r.raise_for_status()
        soup = BeautifulSoup(r.text, "html.parser")
        html = r.text

        h2 = soup.find("h2")
        if h2:
            filename = h2.get_text(" ", strip=True)
        else:
            filename = soup.title.get_text(strip=True) if soup.title else "Movie.mkv"

        filename = _clean_ef_filename(filename)

        all_file_links = re.findall(r'https?://[^"\'<>\s]+/file/\d+', html, re.I)
        all_file_links = list(dict.fromkeys(all_file_links))

        drivehub_links = [link for link in all_file_links if re.search(r'drivehub\.', link, re.I)]
        hubdrive_links = [link for link in all_file_links if re.search(r'hubdrive\.', link, re.I)]

        drivehub_url = drivehub_links[0] if drivehub_links else None
        hubdrive_url = hubdrive_links[0] if hubdrive_links else None
        hubcloud_url = None

        if hubdrive_url:
            try:
                fetch_hubdrive_url = _get_proxied_url(hubdrive_url)
                r2 = _session.get(fetch_hubdrive_url, timeout=30, allow_redirects=True)
                r2.raise_for_status()
                soup2 = BeautifulSoup(r2.text, "html.parser")
                
                hubcloud_links = []
                for a in soup2.find_all("a", href=True):
                    href = a.get("href", "").strip()
                    if re.search(r'hubcloud\.', href, re.I):
                        hubcloud_links.append(href)

                if not hubcloud_links:
                    hubcloud_links = re.findall(r'https?://hubcloud\.[^"\'<>\s]+', r2.text, re.I)

                hubcloud_links = list(dict.fromkeys(hubcloud_links))
                if hubcloud_links:
                    hubcloud_url = hubcloud_links[0]

            except Exception as e:
                print("EF HUBDRIVE ERROR:", e)

        if not (drivehub_url or hubdrive_url or hubcloud_url):
            return None

        return {
            "title": clean_title(filename, "ef"),
            "link": hubcloud_url,
            "drivehub": drivehub_url,
            "hubdrive": hubdrive_url,
            "hubcloud": hubcloud_url
        }

    except Exception as e:
        print("EF HUBCLOUD ERROR:", e)
        return None

def get_ef_final_links(movie_url, post_title, extractor="hubcloud"):
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
