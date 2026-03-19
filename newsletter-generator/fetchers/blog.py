import feedparser
from datetime import datetime, timedelta, timezone
from typing import List, Dict

# Common RSS URL patterns to try if the configured one fails
_RSS_FALLBACKS = ["/feed", "/rss", "/atom.xml", "/feed.xml"]


def fetch_blog_posts(rss_url: str, days_back: int = 35) -> List[Dict]:
    feed = _try_parse(rss_url)
    if feed is None:
        # Try common variants
        base = rss_url.rstrip("/").removesuffix("/feed").removesuffix("/rss")
        for suffix in _RSS_FALLBACKS:
            candidate = base + suffix
            if candidate != rss_url:
                feed = _try_parse(candidate)
                if feed is not None:
                    break

    if feed is None:
        print(f"  Warning: Could not fetch blog RSS from {rss_url} — skipping blog")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    results = []

    for entry in feed.entries:
        published = _parse_date(entry)
        if published is None or published < cutoff:
            continue

        results.append({
            "title": entry.title,
            "url": entry.link,
            "summary": entry.get("summary", "")[:300],
            "published": published.strftime("%Y-%m-%d"),
            "source": "blog",
        })

    return results


def _try_parse(url: str):
    try:
        feed = feedparser.parse(url)
        if feed.bozo and not feed.entries:
            return None
        return feed
    except Exception:
        return None


def _parse_date(entry) -> datetime | None:
    for attr in ("published_parsed", "updated_parsed"):
        parsed = getattr(entry, attr, None)
        if parsed:
            try:
                return datetime(*parsed[:6], tzinfo=timezone.utc)
            except (TypeError, ValueError):
                continue
    return None
