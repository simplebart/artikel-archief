"""
app.py — Streamlit UI Laag

Gebruik:
    streamlit run app.py

Vereiste secrets (st.secrets of .streamlit/secrets.toml):
    [github]
    token  = "ghp_..."
    repo   = "gebruikersnaam/repo-naam"
    folder = "artikelen"   # optioneel, standaard "artikelen"
"""

from __future__ import annotations

import logging
import re

import streamlit as st

from scraper import scrape
from github_client import commit_article

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s — %(message)s",
)

# ---------------------------------------------------------------------------
# Paginaconfiguratie
# ---------------------------------------------------------------------------
st.set_page_config(
    page_title="Artikel Archiver",
    page_icon="📰",
    layout="centered",
    initial_sidebar_state="collapsed",
)

# ---------------------------------------------------------------------------
# Stijl
# ---------------------------------------------------------------------------
st.markdown("""
<style>
    @import url('https://fonts.googleapis.com/css2?family=Playfair+Display:wght@700&family=Source+Sans+3:wght@400;600&display=swap');

    html, body, [class*="css"] {
        font-family: 'Source Sans 3', sans-serif;
    }

    h1, h2, h3 {
        font-family: 'Playfair Display', serif !important;
    }

    .stApp {
        background-color: #f7f4ef;
    }

    /* Kop-banner */
    .header-block {
        background: #1a1a2e;
        color: #f0e6d3;
        border-radius: 12px;
        padding: 2rem 2.5rem 1.5rem;
        margin-bottom: 2rem;
        border-left: 6px solid #c9a84c;
    }
    .header-block h1 {
        font-size: 2rem;
        margin-bottom: 0.25rem;
        color: #f0e6d3 !important;
    }
    .header-block p {
        color: #a89880;
        margin: 0;
        font-size: 0.95rem;
    }

    /* Resultaat-card */
    .result-card {
        background: #ffffff;
        border-radius: 10px;
        padding: 1.5rem;
        border: 1px solid #e0d9ce;
        margin-top: 1.5rem;
        box-shadow: 0 2px 8px rgba(0,0,0,0.06);
    }
    .result-card h3 {
        color: #1a1a2e;
        font-size: 1.15rem;
        margin-bottom: 0.5rem;
    }
    .meta-line {
        color: #7a6e5f;
        font-size: 0.85rem;
        margin-bottom: 1rem;
    }

    /* Preview tekst-box */
    .text-preview {
        background: #f7f4ef;
        border-radius: 8px;
        padding: 1rem;
        font-size: 0.875rem;
        line-height: 1.7;
        color: #3d3325;
        max-height: 320px;
        overflow-y: auto;
        white-space: pre-wrap;
        border: 1px solid #e0d9ce;
    }

    /* Waarschuwing-badge */
    .badge {
        display: inline-block;
        padding: 2px 10px;
        border-radius: 20px;
        font-size: 0.78rem;
        font-weight: 600;
        margin-bottom: 0.5rem;
    }
    .badge-phase2 {
        background: #fff3cd;
        color: #856404;
        border: 1px solid #ffc107;
    }

    /* Button override */
    div.stButton > button {
        background: #1a1a2e;
        color: #f0e6d3;
        border: none;
        border-radius: 8px;
        font-family: 'Source Sans 3', sans-serif;
        font-size: 1rem;
        font-weight: 600;
        padding: 0.6rem 1.8rem;
        transition: background 0.2s;
    }
    div.stButton > button:hover {
        background: #c9a84c;
        color: #1a1a2e;
    }
</style>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Header
# ---------------------------------------------------------------------------
st.markdown("""
<div class="header-block">
    <h1>📰 Artikel Archiver</h1>
    <p>Scrape een nieuwsartikel en archiveer het direct naar je private GitHub-repository.</p>
</div>
""", unsafe_allow_html=True)

# ---------------------------------------------------------------------------
# Secrets validatie
# ---------------------------------------------------------------------------
def _load_secrets() -> tuple[str, str, str] | tuple[None, None, None]:
    """Laad GitHub-credentials uit st.secrets. Retourneert (token, repo, folder)."""
    try:
        token = st.secrets["github"]["token"]
        repo = st.secrets["github"]["repo"]
        folder = st.secrets["github"].get("folder", "artikelen")
        return token, repo, folder
    except (KeyError, FileNotFoundError):
        return None, None, None


token, repo, folder = _load_secrets()

if not token or not repo:
    st.warning(
        "⚙️ **GitHub-credentials niet gevonden.**  \n"
        "Maak `.streamlit/secrets.toml` aan met:\n"
        "```toml\n[github]\ntoken = \"ghp_...\"\nrepo = \"gebruikersnaam/repo\"\nfolder = \"artikelen\"\n```"
    )

# ---------------------------------------------------------------------------
# Sidebar — instellingen
# ---------------------------------------------------------------------------
with st.sidebar:
    st.markdown("### ⚙️ Instellingen")

    override_folder = st.text_input(
        "Submap in repo",
        value=folder or "artikelen",
        help="Map binnen de GitHub-repo waar bestanden worden opgeslagen.",
    )

    st.markdown("---")
    st.markdown("**Fase 2 — Playwright**")
    st.caption(
        "Sommige sites vereisen JavaScript-rendering. "
        "Schakel in `scraper.py` over naar `_fetch_with_playwright` "
        "voor volledige browser-emulatie."
    )

    st.markdown("---")
    st.markdown("**Repo**")
    st.caption(f"`{repo}`" if repo else "_Niet geconfigureerd_")

# ---------------------------------------------------------------------------
# Hoofd-UI
# ---------------------------------------------------------------------------
url_input = st.text_input(
    "Artikel-URL",
    placeholder="https://www.nrc.nl/nieuws/...",
    help="Plak hier de volledige URL van het artikel.",
)

archive_btn = st.button("🗄️  Scrape & Archiveer", use_container_width=True, disabled=not token)

# ---------------------------------------------------------------------------
# Logica
# ---------------------------------------------------------------------------
if archive_btn:
    url = url_input.strip()

    # Basis URL-validatie
    if not re.match(r"^https?://", url):
        st.error("Voer een geldige URL in die begint met `http://` of `https://`.")
        st.stop()

    # Stap 1: Scrapen
    with st.spinner("🔍 Artikel ophalen en parsen…"):
        result = scrape(url)

    if not result.success:
        needs_playwright = result.error and "Playwright" in result.error

        if needs_playwright:
            st.markdown(
                '<span class="badge badge-phase2">⚡ Fase 2 vereist</span>',
                unsafe_allow_html=True,
            )

        st.error(f"**Scraping mislukt:** {result.error}")

        if result.text:
            with st.expander("Gedeeltelijk gescrapete tekst bekijken"):
                st.markdown(f'<div class="text-preview">{result.text[:2000]}</div>',
                            unsafe_allow_html=True)
        st.stop()

    # Stap 2: Toon preview
    st.markdown(f"""
    <div class="result-card">
        <h3>{result.title}</h3>
        <div class="meta-line">
            🔗 {url} &nbsp;|&nbsp;
            📄 {len(result.text):,} tekens &nbsp;|&nbsp;
            HTTP {result.status_code}
        </div>
        <div class="text-preview">{result.text[:1500]}{"…" if len(result.text) > 1500 else ""}</div>
    </div>
    """, unsafe_allow_html=True)

    # Stap 3: GitHub commit
    with st.spinner("☁️ Archiveren naar GitHub…"):
        commit = commit_article(
            token=token,
            repo=repo,
            title=result.title,
            url=url,
            text=result.text,
            subfolder=override_folder,
        )

    if commit.success:
        st.success(
            f"✅ **Gearchiveerd!**  \n"
            f"📁 `{commit.file_path}`  \n"
            f"🔗 [Bekijk op GitHub]({commit.file_url})  \n"
            f"🔏 Commit: `{commit.commit_sha[:7]}`"
        )
    else:
        st.error(f"**GitHub-commit mislukt:** {commit.error}")

# ---------------------------------------------------------------------------
# Footer
# ---------------------------------------------------------------------------
st.markdown("---")
st.caption(
    "📰 Artikel Archiver · Fase 1 (requests + BeautifulSoup) · "
    "Fase 2-ready voor Playwright · Persoonlijk gebruik"
)
