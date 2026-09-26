# -*- coding: utf-8 -*-
# ================= EXTRAFLIX =================

import re
import requests
from bs4 import BeautifulSoup

from bot import load_config, clean_title

_session = requests.Session()
_session.headers.update({"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"})


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
            print(f"[EF] CF Worker failed ({e}), direct try...")
    r = _session.get(url, timeout=timeout, allow_redirects=True)
    r.raise_for_status()
    return r

_BLOCKED = re.compile(r'\bUNRATED\b|\b18\+\b', re.I)


def _clean_ef_filename(name):
    name = re.sub(r"[-_. ]*ExtraFlix\.Pw", "", name, flags=re.I)
    name = re.sub(r"\s*-\s*[\d.]+\s*(MB|GB)\s*$", "", name, flags=re.I)

    if not re.search(r"\.(mkv|mp4|avi)$", name, re.I):
        name += ".mkv"

    name = re.sub(
        r"\.mkv$",
        ".Esub.mkv",
        name,
        flags=re.I
    )

    return name.strip()


def get_ef_posts():
    cfg = load_config()
    url = cfg.get("ef_url", "https://e3.extraflix.mobi/")

    try:
        r = _cf_get(url)

        soup = BeautifulSoup(
            r.text,
            "html.parser"
        )

        movies = []

        for article in soup.select(
            "article.category-movies"
        ):
            a = article.select_one(
                "h2.entry-title a"
            )

            if not a or not a.get("href"):
                continue

            post_url = a["href"]
            post_title = a.get_text(
                strip=True
            )

            # UNRATED filter
            if (
                _BLOCKED.search(post_url)
                or _BLOCKED.search(post_title)
            ):
                print(
                    f"[EF] Skipping UNRATED: {post_url}"
                )
                continue

            movies.append({
                "title": post_title,
                "url": post_url
            })

        # deduplicate
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
        r = _cf_get(movie_url)

        links = re.findall(
            r'https://links\.linkshub\.fun/view/[A-Za-z0-9]+',
            r.text,
            re.I
        )

        return list(
            dict.fromkeys(links)
        )

    except Exception as e:
        print(
            "EF LINKSHUB FETCH ERROR:",
            e
        )
        return []


def get_ef_hubcloud(linkshub_url):
    """
    Linkshub flow:

        Linkshub
            |
            +--> DriveHub
            |
            +--> HubDrive --> HubCloud

    IMPORTANT:
    DriveHub ke andar HubCloud search nahi kiya jata.
    HubCloud sirf HubDrive page se nikala jata hai.
    """

    try:
        r = _session.get(
            linkshub_url,
            timeout=30,
            allow_redirects=True
        )

        r.raise_for_status()

        soup = BeautifulSoup(
            r.text,
            "html.parser"
        )

        html = r.text

        # =================================================
        # TITLE
        # =================================================

        h2 = soup.find("h2")

        if h2:
            filename = h2.get_text(
                " ",
                strip=True
            )
        else:
            filename = (
                soup.title.get_text(
                    strip=True
                )
                if soup.title
                else "Movie.mkv"
            )

        filename = _clean_ef_filename(
            filename
        )

        # =================================================
        # FIND ALL /file/ID LINKS
        # =================================================

        all_file_links = re.findall(
            r'https?://[^"\'<>\s]+/file/\d+',
            html,
            re.I
        )

        all_file_links = list(
            dict.fromkeys(
                all_file_links
            )
        )

        # =================================================
        # DRIVEHUB
        # =================================================

        drivehub_links = [
            link
            for link in all_file_links
            if re.search(
                r'drivehub\.',
                link,
                re.I
            )
        ]

        # =================================================
        # HUBDRIVE
        # Supports:
        #   hubdrive.pics
        #   hubdrive.tips
        #   other hubdrive.* domains
        # =================================================

        hubdrive_links = [
            link
            for link in all_file_links
            if re.search(
                r'hubdrive\.',
                link,
                re.I
            )
        ]

        drivehub_url = (
            drivehub_links[0]
            if drivehub_links
            else None
        )

        hubdrive_url = (
            hubdrive_links[0]
            if hubdrive_links
            else None
        )

        hubcloud_url = None

        # =================================================
        # HUBDRIVE → HUBCLOUD
        #
        # IMPORTANT:
        # Sirf HubDrive open hoga.
        # DriveHub ko open karke HubCloud search nahi hoga.
        # =================================================

        if hubdrive_url:

            try:
                r2 = _cf_get(hubdrive_url)

                soup2 = BeautifulSoup(
                    r2.text,
                    "html.parser"
                )

                # -----------------------------------------
                # First: <a href="">
                # -----------------------------------------

                hubcloud_links = []

                for a in soup2.find_all(
                    "a",
                    href=True
                ):
                    href = a.get(
                        "href",
                        ""
                    ).strip()

                    if re.search(
                        r'hubcloud\.',
                        href,
                        re.I
                    ):
                        hubcloud_links.append(
                            href
                        )

                # -----------------------------------------
                # Fallback: raw HTML
                # -----------------------------------------

                if not hubcloud_links:

                    hubcloud_links = re.findall(
                        r'https?://hubcloud\.[^"\'<>\s]+',
                        r2.text,
                        re.I
                    )

                hubcloud_links = list(
                    dict.fromkeys(
                        hubcloud_links
                    )
                )

                if hubcloud_links:
                    hubcloud_url = (
                        hubcloud_links[0]
                    )

            except Exception as e:
                print(
                    "EF HUBDRIVE ERROR:",
                    e
                )

        # =================================================
        # RETURN
        # =================================================

        # Existing repo compatibility:
        # "link" = final HubCloud when available.
        #
        # Additional fields:
        # drivehub / hubdrive / hubcloud
        #

        if not (
            drivehub_url
            or hubdrive_url
            or hubcloud_url
        ):
            return None

        # Priority: hubcloud → drivehub → hubdrive
        final_link = hubcloud_url or drivehub_url or hubdrive_url

        return {
            "title": clean_title(
                filename,
                "ef"
            ),

            # final_link = jo bhi pehle mile
            "link": final_link,

            # Individual fields
            "drivehub": drivehub_url,
            "hubdrive": hubdrive_url,
            "hubcloud": hubcloud_url
        }

    except Exception as e:
        print(
            "EF HUBCLOUD ERROR:",
            e
        )
        return None


def get_ef_final_links(
    movie_url,
    post_title,
    extractor="hubcloud"
):
    # UNRATED check on movie URL too

    if (
        _BLOCKED.search(movie_url)
        or _BLOCKED.search(post_title)
    ):
        print(
            f"[EF] Skipping UNRATED: {movie_url}"
        )
        return []

    results = []

    linkshubs = get_ef_linkshub_links(
        movie_url
    )

    if not linkshubs:
        print(
            f"[EF] No linkshub links found: "
            f"{movie_url}"
        )
        return []

    for ls_url in linkshubs:

        data = get_ef_hubcloud(
            ls_url
        )

        if data:
            results.append(data)

    return results
