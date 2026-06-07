"""
github_client.py — GitHub API Integratie Laag

Pusht gescrapete tekst als een nieuw bestand naar een private GitHub-repo
via de GitHub Contents REST API (geen externe library nodig).
"""

from __future__ import annotations

import base64
import logging
import re
import time
from dataclasses import dataclass
from typing import Optional
from urllib.parse import urlparse

import requests

logger = logging.getLogger(__name__)

GITHUB_API = "https://api.github.com"


# ---------------------------------------------------------------------------
# Dataclass voor resultaat
# ---------------------------------------------------------------------------

@dataclass
class CommitResult:
    success: bool
    file_path: str
    file_url: str
    commit_sha: str
    error: Optional[str] = None


# ---------------------------------------------------------------------------
# Hulpfuncties
# ---------------------------------------------------------------------------

def _slugify(text: str, max_len: int = 60) -> str:
    """Maak een URL/bestandsnaam-veilige slug van willekeurige tekst."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_-]+", "-", text)
    text = text.strip("-")
    return text[:max_len]


def _build_filename(title: str, url: str) -> str:
    """
    Genereer een unieke bestandsnaam op basis van timestamp + gesaneerde slug.
    Formaat: YYYY-MM-DD_HH-MM-SS_<slug>.md
    """
    timestamp = time.strftime("%Y-%m-%d_%H-%M-%S")

    # Probeer eerst de titel, dan de URL-path als fallback
    slug = _slugify(title) if title and title != "Zonder titel" else ""
    if not slug:
        path = urlparse(url).path
        slug = _slugify(path.replace("/", "-").strip("-")) or "artikel"

    return f"{timestamp}_{slug}.md"


def _encode_content(text: str) -> str:
    """Encodeer tekst naar base64 (vereist door GitHub Contents API)."""
    return base64.b64encode(text.encode("utf-8")).decode("utf-8")


def _build_markdown(title: str, url: str, text: str) -> str:
    """Voeg metadata-header toe aan de gescrapete tekst."""
    scraped_at = time.strftime("%Y-%m-%d %H:%M:%S UTC", time.gmtime())
    return (
        f"# {title}\n\n"
        f"> **Bron:** {url}  \n"
        f"> **Gearchiveerd op:** {scraped_at}\n\n"
        f"---\n\n"
        f"{text}\n"
    )


# ---------------------------------------------------------------------------
# Publieke interface
# ---------------------------------------------------------------------------

def commit_article(
    *,
    token: str,
    repo: str,          # formaat: "gebruikersnaam/repo-naam"
    title: str,
    url: str,
    text: str,
    subfolder: str = "artikelen",
) -> CommitResult:
    """
    Commit de gescrapete tekst naar GitHub.

    Parameters
    ----------
    token      : GitHub Personal Access Token (PAT) met 'repo'-scope
    repo       : "<owner>/<repo>" bijv. "janssen/mijn-archief"
    title      : Artikeltitel (voor bestandsnaam + Markdown-header)
    url        : Originele artikel-URL
    text       : Gescrapete Markdown-tekst
    subfolder  : Map in de repo waar bestanden worden opgeslagen

    Returns
    -------
    CommitResult met file_url = directe GitHub-link naar het bestand
    """
    filename = _build_filename(title, url)
    file_path = f"{subfolder}/{filename}" if subfolder else filename
    content = _build_markdown(title, url, text)
    encoded = _encode_content(content)

    api_url = f"{GITHUB_API}/repos/{repo}/contents/{file_path}"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    payload = {
        "message": f"📰 Archief: {title[:72]}",
        "content": encoded,
        "branch": "main",
    }

    try:
        resp = requests.put(api_url, json=payload, headers=headers, timeout=15)

        if resp.status_code == 201:
            data = resp.json()
            raw_url = data["content"]["html_url"]
            sha = data["commit"]["sha"]
            logger.info("Committed: %s (sha: %s)", file_path, sha)
            return CommitResult(
                success=True,
                file_path=file_path,
                file_url=raw_url,
                commit_sha=sha,
            )

        if resp.status_code == 422:
            return CommitResult(
                success=False, file_path=file_path, file_url="", commit_sha="",
                error="Bestand bestaat al in de repository (422 Unprocessable Entity).",
            )
        if resp.status_code == 401:
            return CommitResult(
                success=False, file_path=file_path, file_url="", commit_sha="",
                error="Ongeldige GitHub-token (401). Controleer je PAT in st.secrets.",
            )
        if resp.status_code == 404:
            return CommitResult(
                success=False, file_path=file_path, file_url="", commit_sha="",
                error=f"Repository '{repo}' niet gevonden (404). Controleer de naam en toegangsrechten.",
            )

        # Generieke fout
        return CommitResult(
            success=False, file_path=file_path, file_url="", commit_sha="",
            error=f"GitHub API-fout {resp.status_code}: {resp.text[:200]}",
        )

    except requests.exceptions.Timeout:
        return CommitResult(
            success=False, file_path=file_path, file_url="", commit_sha="",
            error="GitHub API-verzoek verlopen (timeout na 15s).",
        )
    except Exception as e:
        logger.exception("Onverwachte fout bij GitHub-commit")
        return CommitResult(
            success=False, file_path=file_path, file_url="", commit_sha="",
            error=f"Onverwachte fout: {e}",
        )
