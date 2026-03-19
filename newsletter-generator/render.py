"""
Renders a newsletter draft in Markdown.

Items are sorted by AI relevance score. Low-relevance items (score < 6) are
wrapped in HTML comments so you can see them but they're hidden if you paste
into a Markdown renderer. Delete anything you don't want before publishing.
"""

from datetime import datetime
from typing import Dict, List


def render_newsletter(data: Dict, config: Dict) -> str:
    now = datetime.now()
    month_year = now.strftime("%b %Y")
    issue_number = config["newsletter"].get("issue_number", "?")
    newsletter_name = config["newsletter"].get("name", "Newsletter")
    out = config.get("output", {})

    parts: List[str] = []

    # ── Header ──────────────────────────────────────────────────────────────
    parts.append(f"# Issue #{issue_number} · {month_year}\n")
    parts.append(
        f"Welcome to the {_ordinal(issue_number)} issue of {newsletter_name} Monthly!\n\n"
        "---\n\n"
        "> **Draft instructions:** Items are sorted by AI relevance score (shown in `<!-- comments -->`).\n"
        "> Delete what you don't want, add your commentary, and fill in the Events section manually.\n\n"
        "---\n"
    )

    # ── My Latest Content ────────────────────────────────────────────────────
    parts.append("## 🧱 My Latest Content\n")
    blog_posts = data.get("blog_posts", [])

    parts.append("### Long-form\n")
    parts.append("<!-- Add your YouTube long-form videos here -->\n")
    for p in blog_posts:
        parts.append(f"**[{p['title']}]({p['url']})**  \n{p.get('summary', '').strip()}\n")

    parts.append("\n### Shorts\n")
    parts.append("<!-- Add your YouTube Shorts here -->\n")

    # ── AWS Feature Highlights ───────────────────────────────────────────────
    parts.append("\n## ☁️ AWS Feature Highlights\n")
    parts.append("_AWS updates which caught my eye._\n")
    aws_news = data.get("aws_news", [])[: out.get("max_aws_news", 12)]

    if aws_news:
        for item in aws_news:
            parts.append(_render_item(item, show_url=True))
    else:
        parts.append("_No AWS news found matching your keywords._\n")

    # ── Community Highlights ─────────────────────────────────────────────────
    parts.append("\n## 🌐 Community Highlights\n")
    devto = data.get("devto_articles", [])[: out.get("max_community", 10)]

    if devto:
        for item in devto:
            author = item.get("author", "")
            title_line = f"{item['title']} — {author}" if author else item["title"]
            parts.append(_render_item(item, title_override=title_line, show_url=False))
    else:
        parts.append("_No community articles found._\n")

    # ── Reddit Radar ─────────────────────────────────────────────────────────
    parts.append("\n## 🧵 Reddit Radar\n")
    reddit = data.get("reddit_posts", [])[: out.get("max_reddit", 10)]

    if reddit:
        for item in reddit:
            sub = item.get("subreddit", "aws")
            meta = f"↑{item.get('score', 0)} · {item.get('num_comments', 0)} comments · r/{sub}"
            parts.append(_render_item(item, meta=meta, show_url=False))
    else:
        parts.append("_No Reddit posts found._\n")

    # ── Tool / Repo of the Month ─────────────────────────────────────────────
    parts.append("\n## 🧰 Tool / Repo of the Month\n")
    repos = data.get("github_repos", [])[: out.get("max_repos", 8)]

    if repos:
        for item in repos:
            stars = item.get("stars", 0)
            lang = item.get("language", "")
            meta = f"⭐ {stars}" + (f" · {lang}" if lang else "")
            parts.append(_render_item(item, meta=meta, show_url=True))
    else:
        parts.append("_No repos found._\n")

    # ── Upcoming Events ──────────────────────────────────────────────────────
    parts.append(
        "\n## 📅 Upcoming Events\n"
        "<!-- Add events manually from:\n"
        "     - https://community.aws/events\n"
        "     - https://aws.amazon.com/events/community-day/\n"
        "     - Local AWS user group pages\n"
        "-->\n\n"
        "_Add upcoming AWS community events here._\n"
    )

    # ── Footer ───────────────────────────────────────────────────────────────
    parts.append(
        "\n---\n\n"
        "## 🤝 Let's Connect!\n\n"
        "→ Follow me for more AWS insights and videos:\n\n"
        "- **Instagram:** @awsproductbuilder\n"
        "- **YouTube:** Learn with Avinash Dalvi\n"
        "- **Blog:** Internetkatta.com\n\n"
        "---\n\n"
        "Build Smart. Scale Fast. Spend Less.\n"
    )

    return "\n".join(parts)


def _render_item(
    item: Dict,
    title_override: str = "",
    meta: str = "",
    show_url: bool = True,
) -> str:
    score = item.get("relevance_score")
    keep = item.get("keep", True)
    why = item.get("why_it_matters", "").strip()
    summary = (item.get("summary") or item.get("description") or "").strip()
    body = why or summary[:200]
    title = title_override or item["title"]
    url = item["url"]

    score_tag = f" <!-- score: {score}/10 -->" if score is not None else ""
    low_tag = "\n<!-- ⚠️ LOW RELEVANCE — consider removing -->" if not keep else ""

    lines = [f"{low_tag}"]

    if show_url:
        lines.append(f"**{title}**{score_tag}  \n{body}  \n{url}")
    else:
        lines.append(f"**[{title}]({url})**{score_tag}  \n{body}")

    if meta:
        lines.append(f"_{meta}_")

    lines.append("")  # blank line between items
    return "\n".join(lines)


def _ordinal(n) -> str:
    try:
        n = int(n)
        if 11 <= (n % 100) <= 13:
            suffix = "th"
        else:
            suffix = {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")
        return f"{n}{suffix}"
    except (ValueError, TypeError):
        return str(n)
