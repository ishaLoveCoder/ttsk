# -*- coding: utf-8 -*-
# ================= SKYMOVIES =================

import re
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin

from bot import load_config, clean_title, HEADERS


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
    if m: return BeautifulSoup(m.group(1), "lxml").get_text(" ", strip=True)
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

def extract_gdflix_sky_link(movie_url):
    cfg = load_config(); HEADERS["Referer"] = cfg["sky_domain"]
    r = requests.get(movie_url, headers=HEADERS, timeout=20)
    raw_title = _sky_title_from_html(r.text)
    ph, _ = _sky_protected_html(r.text, movie_url)
    if not ph: return None
    for pat in [r'https?://gdflix\.[^\s"\'<>]+', r'https?://gdlink\.[^\s"\'<>]+']:
        m = re.findall(pat, ph, re.I)
        if m: return {"title": clean_title(raw_title, "sky"), "link": m[0].strip()}
    return None

def extract_hubcloud_sky_link(movie_url):
    cfg = load_config(); HEADERS["Referer"] = cfg["sky_domain"]
    r = requests.get(movie_url, headers=HEADERS, timeout=20)
    raw_title = _sky_title_from_html(r.text)
    ph, rurl = _sky_protected_html(r.text, movie_url)
    if not ph: return None
    for pat in [r'https?://hubcloud\.[^\s"\']+/drive/[A-Za-z0-9]+']:
        m = re.findall(pat, ph, re.I)
        if m: return {"title": clean_title(raw_title, "sky"), "link": max(m, key=len).strip()}
    if rurl and "hubcloud" in rurl.lower():
        return {"title": clean_title(raw_title, "sky"), "link": rurl.strip()}
    return None

def extract_sky_link(movie_url):
    ext = load_config().get("sky_extractor", "gofile").lower()
    if ext == "gdflix": return extract_gdflix_sky_link(movie_url)
    if ext == "hubcloud": return extract_hubcloud_sky_link(movie_url)
    return extract_gofile_link(movie_url)
