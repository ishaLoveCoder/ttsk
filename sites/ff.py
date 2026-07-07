# -*- coding: utf-8 -*-
# ================= FILMYFLY =================

import re
import requests
from bs4 import BeautifulSoup

from bot import load_config, clean_title


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
    "filesdl":     r'filesdl\.in',
    "iwebp":       r'iwebp\.store',
}


def get_ff_posts():
    cfg = load_config()
    base = cfg.get("ff_url", "https://filmyfly.builders/")
    try:
        r = requests.get(base, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        soup = BeautifulSoup(r.text, "html.parser")
        posts = []
        links = soup.select('.A10 a[href*="/page-download/"]')
        if not links:
            links = soup.select('a[href*="/page-download/"]')
        for a in links:
            href = a.get("href", "")
            if not href: continue
            if not href.startswith("http"):
                href = base.rstrip("/") + "/" + href.lstrip("/")
            title = a.get_text(strip=True) or "Unknown"
            posts.append({"title": title, "url": href})
        seen = set(); unique = []
        for p in posts:
            if p["url"] not in seen:
                seen.add(p["url"]); unique.append(p)
        return unique
    except Exception as e:
        print("FF POSTS ERROR:", e); return []


def get_ff_links(movie_url):
    cfg = load_config()
    size_limit = cfg.get("ff_size_limit_mb", 4096)
    extractor  = cfg.get("ff_extractor", "all").lower()
    results    = []

    try:
        r = requests.get(movie_url, headers={"User-Agent": "Mozilla/5.0"}, timeout=30)
        soup = BeautifulSoup(r.text, "html.parser")

        linkmake = soup.find("a", href=re.compile(r'linkmake\.in'))
        if not linkmake:
            print(f"[FF] No linkmake found at {movie_url}")
            return results

        r2 = requests.get(linkmake["href"], headers={"User-Agent": "Mozilla/5.0"},
                          timeout=30, allow_redirects=True)
        soup2 = BeautifulSoup(r2.text, "html.parser")

        quality_links = soup2.find_all("a", href=re.compile(r'filesdl\.in'))
        if not quality_links:
            print(f"[FF] No quality links at linkmake page")
            return results

        for q_link in quality_links:
            try:
                r3 = requests.get(q_link["href"], headers={"User-Agent": "Mozilla/5.0"},
                                  timeout=30, allow_redirects=True)
                soup3 = BeautifulSoup(r3.text, "html.parser")

                title_div = soup3.find("div", class_="title")
                title_raw = title_div.text.strip() if title_div else "Movie"

                size_div = soup3.find(string=re.compile(r'Size:', re.I))
                if size_div:
                    size_text = size_div.strip().replace("Size:", "").strip()
                    if parse_size(size_text) > size_limit:
                        print(f"[FF] Skip large: {title_raw} ({size_text})")
                        continue

                # All button classes: button, button1, button2, button4
                dl_btns = soup3.find_all(
                    "a",
                    class_=re.compile(r'^button[124]?$', re.I)
                )
                # Fallback: href-based filter
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
