"""
scraper.py — Request & Evasion + Parsing & DOM-Extractie Laag

Waterval-strategie:
  1. Directe fetch (roterende browser UA's)
  2. 12ft.io proxy fallback
  3. archive.ph fallback

Fase 2-ready: vervang _fetch_direct door _fetch_with_playwright
              zonder de publieke scrape(url) interface te wijzigen.
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
# User-Agent pool
# ---------------------------------------------------------------------------

_USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:125.0) "
    "Gecko/20100101 Firefox/125.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4_1) AppleWebKit/605.1.15 "
    "(KHTML, like Gecko) Version/17.4.1 Safari/605.1.15",
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
# Dataclass
# ---------------------------------------------------------------------------

@dataclass
class ScrapeResult:
    success: bool
    title: str
    text: str
    url: str
    source: str = "direct"
    error: Optional[str] = None
    status_code: Optional[int] = None
    tried: list[str] = field(default_factory=list)


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
    session = _make_session()
    resp = session.get(url, timeout=TIMEOUT, allow_redirects=True)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.status_code, resp.text


def _fetch_12ft(url: str) -> tuple[int, str]:
    proxy_url = f"https://12ft.io/proxy?q={url}"
    session = _make_session()
    resp = session.get(proxy_url, timeout=TIMEOUT, allow_redirects=True)
    resp.raise_for_status()
    resp.encoding = resp.apparent_encoding or "utf-8"
    return resp.status_code, resp.text


def _fetch_archive(url: str) -> tuple[int, str]:
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

def _get_tag_attrs(tag: Tag) -> tuple[list, str]:
    """
    Lees class en id veilig uit een Tag, ongeacht BS4/Python versie.
    Retourneert (classes_list, id_string).
    """
    try:
        attrs = tag.attrs if hasattr(tag, "attrs") and tag.attrs else {}
    except Exception:
        return [], ""

    classes = attrs.get("class") or []
    if isinstance(classes, str):
        classes = [classes]

    tag_id = attrs.get("id") or ""
    if isinstance(tag_id, list):
        tag_id = " ".join(tag_id)

    return classes, str(tag_id)


def _strip_noise(soup: BeautifulSoup) -> None:
    # Verwijder bekende ruis-tags
    for tag in list(soup.find_all(_STRIP_TAGS)):
        tag.decompose()

    # Verwijder paywall/ad-elementen op class of id
    # Werkt veilig op alle BS4/Python versies via _get_tag_attrs
    for tag in list(soup.find_all(True)):
        if not isinstance(tag, Tag):
            continue
        classes, tag_id = _get_tag_attrs(tag)
        attr_str = " ".join(str(v) for v in classes) + " " + tag_id
        if _PAYWALL_PATTERNS.search(attr_str):
            tag.decompose()


def _find_article_container(soup: BeautifulSoup) -> Optional[Tag]:
    for tag_name in _ARTICLE_TAGS:
        tag = soup.find(tag_name)
        if tag and isinstance(tag, Tag):
            return tag
    for cls in _ARTICLE_CLASSES:
        tag = soup.find(class_=re.compile(rf"\b{cls}\b", re.IGNORECASE))
        if tag and isinstance(tag, Tag):
            return tag
    body = soup.find("body")
    return body if isinstance(body, Tag) else None


def _extract_title(soup: BeautifulSoup) -> str:
    og = soup.find("meta", property="og:title")
    if og and isinstance(og, Tag):
        content = og.get("content")
        if content:
            return str(content).strip()
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
        if not isinstance(elem, Tag):
            continue
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
    soup = BeautifulSoup(html, "html.parser")
    title = _extract_title(soup)
    _strip_noise(soup)
    container = _find_article_container(soup)
    if not container:
        return title, ""
    return title, _to_markdown(container)


# ---------------------------------------------------------------------------
# Hulpfunctie: één fetch-poging uitvoeren
# ---------------------------------------------------------------------------

def _try_fetch(
    fetch_fn,
    label: str,
    url: str,
    tried: list[str],
) -> tuple[Optional[tuple[int, str]], Optional[str]]:
    tried.append(label)
    try:
        result = fetch_fn(url)
        return result, None
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else "?"
        return None, f"{label} geblokkeerd (HTTP {code})"
    except requests.exceptions.Timeout:
        return None, f"{label} time-out na {TIMEOUT}s"
    except requests.exceptions.ConnectionError as e:
        return None, f"{label} verbindingsfout: {e}"
    except Exception as e:
        return None, f"{label} onverwachte fout: {e}"


# ---------------------------------------------------------------------------
# Publieke interface
# ---------------------------------------------------------------------------

def scrape(url: str) -> ScrapeResult:
    """
    Waterval-scraper: direct → 12ft.io → archive.ph
    Retourneert altijd een ScrapeResult, gooit nooit een exception.
    """
    tried: list[str] = []
    errors: list[str] = []

    waterfall = [
        (_fetch_direct,  "direct",     "direct"),
        (_fetch_12ft,    "12ft.io",    "12ft.io"),
        (_fetch_archive, "archive.ph", "archive.ph"),
    ]

    for fetch_fn, label, source_name in waterfall:
        fetch_result, err = _try_fetch(fetch_fn, label, url, tried)

        if err:
            errors.append(err)
            logger.warning("%s mislukt voor %s: %s", label, url, err)
            time.sleep(0.8)
            continue

        status_code, html = fetch_result
        title, text = _parse_html(html)

        if len(text) >= 100:
            return ScrapeResult(
                success=True, title=title, text=text,
                url=url, source=source_name,
                status_code=status_code, tried=tried,
            )

        errors.append(f"{label}: pagina geladen maar te weinig tekst ({len(text)} tekens)")
        logger.info("Te weinig tekst via %s, volgende methode proberen…", label)

    error_summary = "\n".join(f"• {e}" for e in errors)
    return ScrapeResult(
        success=False, title="", text="", url=url,
        source="—", tried=tried,
        error=(
            f"Alle {len(tried)} methodes mislukt:\n{error_summary}\n\n"
            "💡 Tips:\n"
            "• Controleer of de URL correct is\n"
            "• Archiveer het artikel eerst via https://archive.ph\n"
            "• Fase 2 (Playwright) kan JavaScript-paywalls omzeilen"
        ),
    )
