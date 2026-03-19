#!/usr/bin/env python3
"""
AWS for Product Builder — Newsletter Draft Generator
=====================================================

Setup (one-time):
  1. cp .env.example .env
  2. Fill in .env with your API keys
  3. Update config.yaml (issue_number, channel_handle, etc.)
  4. pip install -r requirements.txt

Run:
  python run.py

Output:
  draft_YYYY_MM.md  — review, edit, delete low-relevance items, then publish
"""

import sys
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv

from fetchers.aws_news import fetch_aws_news
from fetchers.blog import fetch_blog_posts
from fetchers.devto import fetch_devto_articles
from fetchers.github_repos import fetch_github_repos
from fetchers.reddit import fetch_reddit_posts
from llm_scorer import score_and_enrich
from render import render_newsletter


def load_config(path: str = "config.yaml") -> dict:
    config_path = Path(__file__).parent / path
    if not config_path.exists():
        print(f"Error: config file not found at {config_path}")
        sys.exit(1)
    with open(config_path) as f:
        return yaml.safe_load(f)


def main():
    load_dotenv(Path(__file__).parent / ".env")
    config = load_config()

    print(f"\n📰 {config['newsletter']['name']} — Issue #{config['newsletter']['issue_number']}")
    print("=" * 60)

    # ── Fetch all sections ───────────────────────────────────────
    print("\n🔍 Fetching AWS What's New...")
    aws_news = fetch_aws_news(
        keywords=config["aws_news"]["keywords"],
        days_back=config["aws_news"]["days_back"],
    )
    print(f"   {len(aws_news)} items matched keywords")

    print("📝 Fetching blog posts...")
    blog_posts = fetch_blog_posts(
        rss_url=config["blog"]["rss_url"],
        days_back=config["blog"]["days_back"],
    )
    print(f"   {len(blog_posts)} posts")

    print("👥 Fetching dev.to community articles...")
    devto_articles = fetch_devto_articles(
        tags=config["devto"]["tags"],
        days_back=config["devto"]["days_back"],
        per_page=config["devto"]["per_page"],
    )
    print(f"   {len(devto_articles)} articles")

    print("🧵 Fetching Reddit top posts...")
    reddit_posts = fetch_reddit_posts(
        subreddits=config["reddit"]["subreddits"],
        time_filter=config["reddit"]["time_filter"],
        limit=config["reddit"]["limit"],
    )
    print(f"   {len(reddit_posts)} posts")

    print("🔧 Fetching GitHub repos...")
    github_repos = fetch_github_repos(
        queries=config["github"]["queries"],
        min_stars=config["github"]["min_stars"],
        days_back=config["github"]["days_back"],
        max_repos=config["github"]["max_repos"],
    )
    print(f"   {len(github_repos)} repos")

    # ── AI scoring ───────────────────────────────────────────────
    print("\n🤖 Running AI scoring + commentary (Claude Haiku)...")
    scored = score_and_enrich(
        {
            "aws_news": aws_news,
            "devto_articles": devto_articles,
            "reddit_posts": reddit_posts,
            "github_repos": github_repos,
        },
        config=config,
    )

    scored["blog_posts"] = blog_posts

    # ── Render draft ─────────────────────────────────────────────
    print("\n📄 Rendering newsletter draft...")
    draft = render_newsletter(scored, config)

    month_str = datetime.now().strftime("%Y_%m")
    output_dir = Path(__file__).parent / config["output"]["draft_dir"]
    output_path = output_dir / f"draft_{month_str}.md"
    output_path.write_text(draft, encoding="utf-8")

    # ── Summary ──────────────────────────────────────────────────
    print(f"\n✅ Done! Draft saved to: {output_path}")
    print("\nItem counts in draft:")
    print(f"  AWS Feature Highlights : {len(scored.get('aws_news', []))}")
    print(f"  Community Highlights   : {len(scored.get('devto_articles', []))}")
    print(f"  Reddit Radar           : {len(scored.get('reddit_posts', []))}")
    print(f"  Tool / Repo Spotlight  : {len(scored.get('github_repos', []))}")
    print(f"  Blog posts             : {len(blog_posts)}")
    print("\nNext steps:")
    print("  1. Open the draft and review each section")
    print("  2. Delete low-relevance items (marked ⚠️ or scored < 6)")
    print("  3. Edit the AI-generated 'why it matters' blurbs")
    print("  4. Add events to the 📅 Upcoming Events section manually")
    print("  5. Bump issue_number in config.yaml for next month\n")


if __name__ == "__main__":
    main()
