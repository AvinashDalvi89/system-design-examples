import os
import requests
from datetime import datetime, timedelta, timezone
from typing import List, Dict

GITHUB_API_BASE = "https://api.github.com"


def fetch_github_repos(
    queries: List[str],
    min_stars: int = 30,
    days_back: int = 60,
    max_repos: int = 25,
) -> List[Dict]:
    token = os.getenv("GITHUB_TOKEN")
    headers = {
        "Accept": "application/vnd.github+json",
        "User-Agent": "AWS Product Builder Newsletter/1.0",
    }
    if token:
        headers["Authorization"] = f"Bearer {token}"

    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days_back)).strftime("%Y-%m-%d")
    seen_ids: set = set()
    results: List[Dict] = []

    for query in queries:
        full_query = f"{query} stars:>={min_stars} created:>{cutoff_date}"
        try:
            resp = requests.get(
                f"{GITHUB_API_BASE}/search/repositories",
                headers=headers,
                params={"q": full_query, "sort": "stars", "order": "desc", "per_page": 15},
                timeout=10,
            )
            resp.raise_for_status()
            for repo in resp.json().get("items", []):
                if repo["id"] in seen_ids:
                    continue
                seen_ids.add(repo["id"])
                results.append({
                    "title": repo["full_name"],
                    "url": repo["html_url"],
                    "description": repo.get("description") or "",
                    "stars": repo["stargazers_count"],
                    "language": repo.get("language") or "",
                    "created": repo["created_at"][:10],
                    "topics": repo.get("topics", []),
                    "source": "github",
                })
        except Exception as e:
            print(f"  Warning: GitHub search failed for '{query}': {e}")

    results.sort(key=lambda x: x["stars"], reverse=True)
    return results[:max_repos]
