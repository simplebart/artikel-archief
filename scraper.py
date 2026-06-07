"""
scraper.py — Request & Evasion + Parsing & DOM-Extractie Laag

Fase 1: requests + BeautifulSoup
Fase 2-ready: vervang `_fetch_with_requests` door `_fetch_with_playwright`
                zonder de publieke `scrape(url)` interface te wijzigen.
"""

from __future__ import annotations

import re
import logging
from dataclasses import dataclass
from typing import Optional

import requests
from bs4 import BeautifulSoup, Tag

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuratie
# ---------------------------------------------------------------------------

# Semantische container-tags (hoog vertrouwen → laag vertrouwen)
_ARTICLE_TAGS = ["article", "main", "section"]

# CSS-classes die typisch de bulk-tekst bevatten
_ARTICLE_CLASSES = [
    "article", "article-body", "article__body", "article-content",
    "article__content", "post-content", "entry-content", "story-body",
    "story__body", "content-body", "main-content", "body-text",
    "paragraph", "field-body",
]

# DOM-elementen die we altijd verwijderen
_STRIP_TAGS = [
    "script", "style", "noscript", "iframe", "nav", "header", "footer",
    "aside", "figure", "figcaption", "form", "button", "svg", "img",
    "picture", "video", "audio", "ads", "ad",
]

# CSS-classes/-id's die op paywall/ad-overlays wijzen
_PAYWALL_PATTERNS = re.compile(
    r"paywall|pay-wall|premium|subscriber|subscription|"
    r"metered|locked|gate|overlay|modal|popup|banner|"
    r"cookie|consent|gdpr|ad[-_]|advertisement",
    re.IGNORECASE,
)

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (compatible; Googlebot/2.1; "
        "+http://www.google.com/bot.html)"
    ),
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

TIMEOUT = 15  # seconden


# ---------------------------------------------------------------------------
# Dataclass voor resultaat
# ---------------------------------------------------------------------------

@dataclass
class ScrapeResult:
    success: bool
    title: str
    text: str
    url: str
    error: Optional[str] = None
    status_code: Optional[int] = None


# ---------------------------------------------------------------------------
# Fase 1 — requests
# ---------------------------------------------------------------------------

def _fetch_with_requests(url: str) -> tuple[int, str]:
    """
    Haal de raw HTML op via requests.
    Raises requests.HTTPError bij 4xx/5xx.
    Retourneert (status_code, html_text).
    """
    session = requests.Session()
    session.headers.update(HEADERS)

    response = session.get(url, timeout=TIMEOUT, allow_redirects=True)
    response.raise_for_status()
    response.encoding = response.apparent_encoding or "utf-8"
    return response.status_code, response.text


# ---------------------------------------------------------------------------
# Fase 2 stub — Playwright (async)
# ---------------------------------------------------------------------------
# Uncomment en implementeer dit blok wanneer je overschakelt naar Fase 2.
#
# async def _fetch_with_playwright(url: str) -> tuple[int, str]:
#     from playwright.async_api import async_playwright
#     async with async_playwright() as pw:
#         browser = await pw.chromium.launch(headless=True)
#         context = await browser.new_context(
#             user_agent=HEADERS["User-Agent"],
#             extra_http_headers={k: v for k, v in HEADERS.items()
#                                  if k != "User-Agent"},
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
    """Verwijder scripts, stijlen, navs, ads, paywall-overlays, etc."""
    # Verwijder bekende ruis-tags
    for tag in soup.find_all(_STRIP_TAGS):
        tag.decompose()

    # Verwijder elementen met paywall/ad-gerelateerde class of id
    for tag in soup.find_all(True):
        attrs = " ".join(
            str(v) for v in (
                tag.get("class", []) + [tag.get("id", "")]
            )
        )
        if _PAYWALL_PATTERNS.search(attrs):
            tag.decompose()


def _find_article_container(soup: BeautifulSoup) -> Optional[Tag]:
    """
    Zoek de meest waarschijnlijke tekst-container via:
    1. Semantische tags (<article>, <main>, <section>)
    2. CSS-classes die op artikel-body wijzen
    3. Fallback: <body>
    """
    # 1. Directe semantische tags
    for tag_name in _ARTICLE_TAGS:
        tag = soup.find(tag_name)
        if tag:
            return tag

    # 2. CSS-classes
    for cls in _ARTICLE_CLASSES:
        tag = soup.find(class_=re.compile(rf"\b{cls}\b", re.IGNORECASE))
        if tag:
            return tag

    # 3. Fallback
    return soup.find("body")


def _extract_title(soup: BeautifulSoup) -> str:
    """Haal de paginatitel op (og:title → <h1> → <title>)."""
    og = soup.find("meta", property="og:title")
    if og and og.get("content"):
        return og["content"].strip()
    h1 = soup.find("h1")
    if h1:
        return h1.get_text(strip=True)
    title = soup.find("title")
    return title.get_text(strip=True) if title else "Zonder titel"


def _to_markdown(container: Tag) -> str:
    """
    Converteer de container naar leesbare platte tekst met Markdown-opmaak
    voor koppen en alinea's.
    """
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

        lines.append("")  # lege regel na elk element

    # Verwijder opeenvolgende lege regels
    result = re.sub(r"\n{3,}", "\n\n", "\n".join(lines))
    return result.strip()


# ---------------------------------------------------------------------------
# Publieke interface
# ---------------------------------------------------------------------------

def scrape(url: str) -> ScrapeResult:
    """
    Hoofd-scraper. Retourneert altijd een ScrapeResult (nooit een exception
    naar de caller).

    Om over te schakelen naar Playwright (Fase 2):
      - Vervang de aanroep van `_fetch_with_requests` door
        `asyncio.run(_fetch_with_playwright(url))`
      - De rest van deze functie blijft ongewijzigd.
    """
    try:
        status_code, html = _fetch_with_requests(url)
    except requests.exceptions.HTTPError as e:
        code = e.response.status_code if e.response is not None else None
        msg = {
            403: "Toegang geweigerd (403 Forbidden). De server blokkeert de crawler.",
            429: "Te veel verzoeken (429 Too Many Requests). Probeer het later opnieuw.",
            401: "Authenticatie vereist (401). Dit artikel zit achter een harde paywall.",
            404: "Pagina niet gevonden (404).",
        }.get(code, f"HTTP-fout {code}: {e}")
        logger.warning("HTTP-fout voor %s: %s", url, msg)
        return ScrapeResult(success=False, title="", text="", url=url,
                            error=msg, status_code=code)

    except requests.exceptions.ConnectionError:
        return ScrapeResult(success=False, title="", text="", url=url,
                            error="Kan geen verbinding maken met de server. Controleer de URL.")
    except requests.exceptions.Timeout:
        return ScrapeResult(success=False, title="", text="", url=url,
                            error=f"Verzoek verlopen (timeout na {TIMEOUT}s).")
    except Exception as e:
        logger.exception("Onverwachte scraper-fout voor %s", url)
        return ScrapeResult(success=False, title="", text="", url=url,
                            error=f"Onverwachte fout: {e}")

    soup = BeautifulSoup(html, "html.parser")
    title = _extract_title(soup)
    _strip_noise(soup)
    container = _find_article_container(soup)

    if not container:
        return ScrapeResult(success=False, title=title, text="", url=url,
                            error="Geen artikel-container gevonden in de DOM.",
                            status_code=status_code)

    text = _to_markdown(container)

    if len(text) < 100:
        return ScrapeResult(
            success=False, title=title, text=text, url=url,
            error=(
                "Te weinig tekst geëxtraheerd (mogelijk server-side paywall "
                "of JavaScript-rendering vereist — overweeg Fase 2 met Playwright)."
            ),
            status_code=status_code,
        )

    return ScrapeResult(success=True, title=title, text=text, url=url,
                        status_code=status_code)
