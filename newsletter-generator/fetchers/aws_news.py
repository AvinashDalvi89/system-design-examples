import feedparser
from datetime import datetime, timedelta, timezone
from typing import List, Dict

AWS_FEED_URL = "https://aws.amazon.com/new/feed/"


def fetch_aws_news(keywords: List[str], days_back: int = 35) -> List[Dict]:
    try:
        feed = feedparser.parse(AWS_FEED_URL)
    except Exception as e:
        print(f"  Warning: Could not fetch AWS news feed: {e}")
        return []

    cutoff = datetime.now(timezone.utc) - timedelta(days=days_back)
    results = []

    for entry in feed.entries:
        try:
            published = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc)
        except (AttributeError, TypeError):
            continue

        if published < cutoff:
            continue

        title = entry.title
        summary = entry.get("summary", "")
        text = f"{title} {summary}".lower()

        if any(kw.lower() in text for kw in keywords):
            results.append({
                "title": title,
                "url": entry.link,
                "summary": summary,
                "published": published.strftime("%Y-%m-%d"),
                "source": "aws_news",
            })

    return results
