import os
import requests
from datetime import datetime, timedelta, timezone
from typing import List, Dict

DEVTO_API_BASE = "https://dev.to/api"


def fetch_devto_articles(tags: List[str], days_back: int = 35, per_page: int = 50) -> List[Dict]:
    headers = {
        "User-Agent": "AWS Product Builder Newsletter/1.0",
        "Accept": "application/vnd.forem.api-v1+json",
    }
    api_key = os.getenv("DEVTO_API_KEY")
    if api_key:
        headers["api-key"] = api_key

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    seen_urls: set = set()
    results: List[Dict] = []

    # Primary source: aws-builders organization on dev.to
    _fetch_page(
        f"{DEVTO_API_BASE}/articles",
        {"username": "aws-builders", "per_page": per_page},
        headers, results, seen_urls, cutoff,
        label="aws-builders org",
    )

    # Secondary: articles by tag
    for tag in tags:
        _fetch_page(
            f"{DEVTO_API_BASE}/articles",
            {"tag": tag, "per_page": per_page, "top": "1"},
            headers, results, seen_urls, cutoff,
            label=f"tag:{tag}",
        )

    return sorted(results, key=lambda x: x.get("reactions", 0), reverse=True)


def _fetch_page(url, params, headers, results, seen_urls, cutoff, label):
    try:
        resp = requests.get(url, headers=headers, params=params, timeout=10)
        resp.raise_for_status()
        for article in resp.json():
            _add_article(article, results, seen_urls, cutoff)
    except Exception as e:
        print(f"  Warning: dev.to fetch failed ({label}): {e}")


def _add_article(article: Dict, results: List, seen_urls: set, cutoff: datetime):
    url = article.get("url", "")
    if not url or url in seen_urls:
        return

    published_str = article.get("published_at", "")
    if not published_str:
        return
    try:
        published = datetime.fromisoformat(published_str.replace("Z", "+00:00"))
        if published < cutoff:
            return
    except (ValueError, AttributeError):
        return

    seen_urls.add(url)
    results.append({
        "title": article.get("title", ""),
        "url": url,
        "author": article.get("user", {}).get("name", ""),
        "summary": article.get("description", ""),
        "published": published.strftime("%Y-%m-%d"),
        "reactions": article.get("public_reactions_count", 0),
        "tags": article.get("tag_list", []),
        "source": "devto",
    })
