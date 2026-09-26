# -*- coding: utf-8 -*-
# ================= FILMYFLY =================

import re
import requests
from bs4 import BeautifulSoup

from bot import load_config, clean_title

_session = requests.Session()
_session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})

_BLOCKED = re.compile(r'\bUNRATED\b|\b18\+\b', re.I)


def _cf_get(url, timeout=30):
    """CF Worker se fetch karo agar set hai, warna direct"""
    cfg = load_config()
    worker = cfg.get("cf_worker_url", "").strip().rstrip("/")
    if worker:
        proxy_url = f"{worker}?url={requests.utils.quote(url, safe='')}"
        try:
            r = _session.get(proxy_url, timeout=timeout)
            r.raise_for_status()
            return r
        except Exception as e:
            print(f"[FF] CF Worker failed ({e}), direct try...")
    r = _session.get(url, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r


def parse_size(size_str):
    size_str = size_str.upper()
    m = re.search(r'([\d.]+)\s*(MB|GB)', size_str)
    if not m: return 0
    val, unit = float(m.group(1)), m.group(2)
    return val * 1024 if unit == 'GB' else val


FF_LINK_PATTERNS = {
    "gofile":      r'gofile\.io',
    "gdflix":      r'gdflix\.|gdlink\.',
    "hubcloud":    r'hubcloud\.',
    "drivehub":    r'drivehub\.',
    "buzzheavier": r'buzzheavier\.com',
    "r2":          r'r2\.dev',
    "telegram":    r't\.me',
    "filesdl":     r'filesdl',
    "iwebp":       r'iwebp\.store',
}


def get_ff_posts():
    cfg  = load_config()
    base = cfg.get("ff_url", "https://filmyfly.army/")
    try:
        r    = _cf_get(base)
        soup = BeautifulSoup(r.text, "html.parser")
        posts = []
        links = soup.select('.A10 a[href*="/page-download/"]')
        if not links:
            links = soup.select('a[href*="/page-download/"]')
        for a in links:
            href  = a.get("href", "")
            title = a.get_text(strip=True) or "Unknown"
            if not href: continue
            if not href.startswith("http"):
                href = base.rstrip("/") + "/" + href.lstrip("/")
            if _BLOCKED.search(href) or _BLOCKED.search(title):
                print(f"[FF] Skipping UNRATED: {href}")
                continue
            posts.append({"title": title, "url": href})
        seen = set(); unique = []
        for p in posts:
            if p["url"] not in seen:
                seen.add(p["url"]); unique.append(p)
        return unique
    except Exception as e:
        print("FF POSTS ERROR:", e)
        return []


def get_ff_links(movie_url):
    if _BLOCKED.search(movie_url):
        print(f"[FF] Skipping UNRATED: {movie_url}")
        return []

    cfg        = load_config()
    size_limit = cfg.get("ff_size_limit_mb", 4096)
    extractor  = cfg.get("ff_extractor", "all").lower()
    results    = []

    try:
        r    = _cf_get(movie_url)
        soup = BeautifulSoup(r.text, "html.parser")

        # linkmake.in link
        linkmake = soup.find("a", href=re.compile(r'linkmake\.in'))
        if not linkmake:
            direct_sdl = soup.find_all("a", href=re.compile(r'filesdl', re.I))
            if direct_sdl:
                quality_links = direct_sdl
                soup2 = soup
            else:
                print(f"[FF] No linkmake or filesdl: {movie_url}")
                return results
        else:
            r2   = _cf_get(linkmake["href"])
            soup2 = BeautifulSoup(r2.text, "html.parser")
            quality_links = soup2.find_all("a", href=re.compile(r'filesdl', re.I))

        if not quality_links:
            print(f"[FF] No quality links: {movie_url}")
            return results

        for q_link in quality_links:
            try:
                r3   = _cf_get(q_link["href"])
                soup3 = BeautifulSoup(r3.text, "html.parser")

                title_div = soup3.find("div", class_="title")
                title_raw = title_div.text.strip() if title_div else "Movie"

                if _BLOCKED.search(title_raw):
                    print(f"[FF] Skipping UNRATED file: {title_raw}")
                    continue

                size_div = soup3.find(string=re.compile(r'Size:', re.I))
                if size_div:
                    size_text = re.sub(r'Size:\s*', '', size_div, flags=re.I).strip()
                    if parse_size(size_text) > size_limit:
                        print(f"[FF] Skip large: {title_raw} ({size_text})")
                        continue

                dl_btns = soup3.find_all("a", class_=re.compile(r'^button[124]?$', re.I))
                if not dl_btns:
                    dl_btns = soup3.find_all("a", href=True)

                for btn in dl_btns:
                    href = btn.get("href", "")
                    if not href or href.startswith("data:"): continue
                    if not any(re.search(pat, href, re.I) for pat in FF_LINK_PATTERNS.values()):
                        continue
                    if extractor != "all":
                        pat = FF_LINK_PATTERNS.get(extractor, "")
                        if pat and not re.search(pat, href, re.I): continue
                    results.append({
                        "title": clean_title(title_raw, "ff"),
                        "link":  href
                    })
            except Exception as e:
                print("FF QUALITY ERROR:", e)

    except Exception as e:
        print("FF LINKS ERROR:", e)

    return results
