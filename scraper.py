"""
scraper.py — Request & Evasion + Parsing & DOM-Extractie Laag

Strategie (waterval):
  1. Directe fetch met roterende User-Agent strings
  2. Bij 403/429 → archive.ph fallback
  3. Bij archive.ph mislukking → duidelijke foutmelding

Fase 2-ready: vervang `_fetch_with_requests` door `_fetch_with_playwright`
              zonder de publieke `scrape(url)` interface te wijzigen.
"""

from __future__ import annotations

import re
import time
import random
import logging
from dataclasses import dataclass, field
from typing import Optional

import requests
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# User-Agent pool — roteert bij elke aanroep
# ---------------------------------------------------------------------------

_USER_AGENTS = [
    # Chrome op Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Chrome op Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    # Firefox op Windows
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
    # Safari op Mac
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
    # Googlebot (SEO-bypass)
    "Mozilla/5.0 (compatible; Googlebot/2.1; +http://www.google.com/bot.html)",
]

_BASE_HEADERS = {
    "Accept": (
        "text/html,application/xhtml+xml,application/xml;"
        "q=0.9,image/avif,image/webp,*/*;q=0.8"
    ),
    "Accept-Language": "nl-NL,nl;q=0.9,en-US;q=0.8,en;q=0.7",
    "Accept-Encoding": "gzip, deflate, br",
    "Referer": "https://www.google.com/",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "DNT": "1",
    "Upgrade-Insecure-Requests": "1",
}

TIMEOUT = 20

# ---------------------------------------------------------------------------
# Semantische selectors
# ---------------------------------------------------------------------------

_ARTICLE_TAGS = ["article", "main", "section"]

_ARTICLE_CLASSES = [
    "article", "article-body", "article__body", "article-content",
    "article__content", "post-content", "entry-content", "story-body",
    "story__body", "content-body", "main-content", "body-text",
    "paragraph", "field-body",
]

_STRIP_TAGS = [
    "script", "style", "noscript", "iframe", "nav", "header", "footer",
    "aside", "figure", "figcaption", "form", "button", "svg", "img",
    "picture", "video", "audio",
]

_PAYWALL_PATTERNS = re.compile(
    r"paywall|pay-wall|premium|subscriber|subscription|"
    r"metered|locked|gate|overlay|modal|popup|banner|"
    r"cookie|consent|gdpr|ad[-_]|advertisement",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# Dataclass voor resultaat
# ---------------------------------------------------------------------------

@dataclass
class ScrapeResult:
    success: bool
    title: str
    text: str
    url: str
    source: str = "direct"          # "direct" | "archive.ph"
    error: Optional[str] = None
    status_code: Optional[int] = None
    tried: list[str] = field(default_factory=list)  # log van geprobeerde methodes


# ---------------------------------------------------------------------------
# Fetch-laag
# ---------------------------------------------------------------------------

def _make_session(ua: Optional[str] = None) -> requests.Session:
    session = requests.Session()
    headers = dict(_BASE_HEADERS)
    headers["User-Agent"] = ua or random.choice(_USER_AGENTS)
    session.headers.update(headers)
    return session


def _fetch_direct(url: str) -> tuple[int, str]:
    """Directe fetch met willekeurige UA. Raises HTTPError bij 4xx/5xx."""
    session = _make_session()
    resp = session.get(url, timeout=TIMEOUT, allow_redirects=True)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.status_code, resp.text


def _fetch_archive(url: str) -> tuple[int, str]:
    """
    Haal de nieuwste gearchiveerde versie op via archive.ph.
    archive.ph/newest/<url> redirectt naar de meest recente snapshot.
    """
    archive_url = f"https://archive.ph/newest/{url}"
    session = _make_session()
    resp = session.get(archive_url, timeout=TIMEOUT, allow_redirects=True)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.status_code, resp.text


# ---------------------------------------------------------------------------
# Fase 2 stub — Playwright
# ---------------------------------------------------------------------------
# async def _fetch_with_playwright(url: str) -> tuple[int, str]:
#     from playwright.async_api import async_playwright
#     async with async_playwright() as pw:
#         browser = await pw.chromium.launch(headless=True)
#         context = await browser.new_context(
#             user_agent=random.choice(_USER_AGENTS),
#             extra_http_headers={k: v for k, v in _BASE_HEADERS.items()},
#         )
#         page = await context.new_page()
#         response = await page.goto(url, wait_until="networkidle", timeout=30_000)
#         html = await page.content()
#         await browser.close()
#         return response.status if response else 200, html


# ---------------------------------------------------------------------------
# Parsing & DOM-Extractie
# ---------------------------------------------------------------------------

def _strip_noise(soup: BeautifulSoup) -> None:
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()
    for tag in soup.find_all(True):
        attrs = " ".join(
            str(v) for v in (tag.get("class", []) + [tag.get("id", "")])
        )
        if _PAYWALL_PATTERNS.search(attrs):
            tag.decompose()


def _find_article_container(soup: BeautifulSoup) -> Optional[Tag]:
    for tag_name in _ARTICLE_TAGS:
        tag = soup.find(tag_name)
        if tag:
            return tag
    for cls in _ARTICLE_CLASSES:
        tag = soup.find(class_=re.compile(rf"\b{cls}\b", re.IGNORECASE))
        if tag:
            return tag
    return soup.find("body")


def _extract_title(soup: BeautifulSoup) -> str:
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    title = soup.find("title")
    return title.get_text(strip=True) if title else "Zonder titel"


def _to_markdown(container: Tag) -> str:
    lines: list[str] = []
    for elem in container.find_all(
        ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote"],
        recursive=True,
    ):
        text = elem.get_text(separator=" ", strip=True)
        if not text:
            continue
        tag = elem.name
        if tag == "h1":
            lines.append(f"# {text}")
        elif tag == "h2":
            lines.append(f"## {text}")
        elif tag in ("h3", "h4"):
            lines.append(f"### {text}")
        elif tag in ("h5", "h6"):
            lines.append(f"#### {text}")
        elif tag == "blockquote":
            lines.append(f"> {text}")
        elif tag == "li":
            lines.append(f"- {text}")
        else:
            lines.append(text)
        lines.append("")
    return re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()


def _parse_html(html: str) -> tuple[str, str]:
    """Parse HTML → (title, markdown_text). Retourneert ("", "") bij mislukking."""
    soup = BeautifulSoup(html, "html.parser")
    title = _extract_title(soup)
    _strip_noise(soup)
    container = _find_article_container(soup)
    if not container:
        return title, ""
    return title, _to_markdown(container)


# ---------------------------------------------------------------------------
# Publieke interface
# ---------------------------------------------------------------------------

def scrape(url: str) -> ScrapeResult:
    """
    Waterval-scraper:
      1. Directe fetch (roterende UA)
      2. archive.ph fallback bij 403/429/verbindingsfout

    Retourneert altijd een ScrapeResult — gooit nooit een exception.
    """
    tried: list[str] = []

    # ── Poging 1: directe fetch ──────────────────────────────────────────
    tried.append("direct")
    direct_error: Optional[str] = None
    direct_code: Optional[int] = None

    try:
        status_code, html = _fetch_direct(url)
        title, text = _parse_html(html)

        if len(text) >= 100:
            return ScrapeResult(
                success=True, title=title, text=text,
                url=url, source="direct", status_code=status_code, tried=tried,
            )
        # Gelukt qua HTTP maar te weinig tekst → toch archive proberen
        direct_error = "Te weinig tekst via directe fetch, archive.ph wordt geprobeerd…"
        direct_code = status_code

    except requests.exceptions.HTTPError as e:
        direct_code = e.response.status_code if e.response is not None else None
        if direct_code in (403, 429, 401):
            direct_error = (
                f"Directe fetch geblokkeerd ({direct_code}). "
                "Archive.ph wordt geprobeerd…"
            )
        else:
            direct_error = f"HTTP-fout {direct_code} bij directe fetch."
        logger.warning("Directe fetch mislukt voor %s: %s", url, direct_error)

    except (requests.exceptions.ConnectionError, requests.exceptions.Timeout) as e:
        direct_error = f"Verbindingsfout bij directe fetch: {e}"
        logger.warning(direct_error)

    except Exception as e:
        direct_error = f"Onverwachte fout bij directe fetch: {e}"
        logger.exception(direct_error)

    # ── Poging 2: archive.ph fallback ────────────────────────────────────
    tried.append("archive.ph")
    time.sleep(1)  # kleine pauze voor beleefdheid

    try:
        status_code, html = _fetch_archive(url)
        title, text = _parse_html(html)

        if len(text) >= 100:
            return ScrapeResult(
                success=True, title=title, text=text,
                url=url, source="archive.ph", status_code=status_code, tried=tried,
            )

        # archive.ph gaf ook te weinig tekst
        return ScrapeResult(
            success=False, title=title, text=text, url=url,
            source="archive.ph", status_code=status_code, tried=tried,
            error=(
                "Archive.ph gevonden maar te weinig tekst geëxtraheerd. "
                "Mogelijk is dit artikel nog niet gearchiveerd, of vereist het "
                "JavaScript-rendering (overweeg Fase 2 met Playwright)."
            ),
        )

    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else None
        if code == 404:
            archive_error = (
                "Artikel niet gevonden in archive.ph (404). "
                "Het is mogelijk nog nooit gearchiveerd."
            )
        else:
            archive_error = f"Archive.ph gaf HTTP {code}."
        logger.warning("Archive.ph mislukt voor %s: %s", url, archive_error)
        return ScrapeResult(
            success=False, title="", text="", url=url,
            source="archive.ph", tried=tried,
            error=f"{direct_error}\n\nArchive.ph fallback: {archive_error}",
        )

    except Exception as e:
        logger.exception("Archive.ph fallback mislukt voor %s", url)
        return ScrapeResult(
            success=False, title="", text="", url=url,
            source="archive.ph", tried=tried,
            error=(
                f"{direct_error}\n\n"
                f"Archive.ph fallback ook mislukt: {e}\n\n"
                "💡 Tip: probeer het artikel eerst handmatig op archive.ph te archiveren "
                "via https://archive.ph"
            ),
        )
