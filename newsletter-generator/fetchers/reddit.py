import requests
from typing import List, Dict

# Reddit's public JSON API — no credentials needed, just a descriptive User-Agent
_HEADERS = {"User-Agent": "AWS Product Builder Newsletter/1.0 (newsletter curation bot)"}


def fetch_reddit_posts(subreddits: List[str], time_filter: str = "month", limit: int = 40) -> List[Dict]:
    results = []

    for subreddit_name in subreddits:
        url = f"https://www.reddit.com/r/{subreddit_name}/top.json"
        try:
            resp = requests.get(
                url,
                headers=_HEADERS,
                params={"t": time_filter, "limit": limit},
                timeout=10,
            )
            resp.raise_for_status()
            posts = resp.json()["data"]["children"]

            for post in posts:
                d = post["data"]
                results.append({
                    "title": d["title"],
                    "url": f"https://www.reddit.com{d['permalink']}",
                    "score": d["score"],
                    "num_comments": d["num_comments"],
                    "subreddit": subreddit_name,
                    "summary": (d.get("selftext") or "")[:300],
                    "source": "reddit",
                })

        except Exception as e:
            print(f"  Warning: Could not fetch r/{subreddit_name}: {e}")

    return sorted(results, key=lambda x: x["score"], reverse=True)
