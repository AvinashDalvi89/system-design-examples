"""
Uses Claude to score each item's relevance for the newsletter and generate
a "why it matters for product builders" blurb per item.

One API call per section keeps costs low (Haiku model).
Items scored < 6 are flagged with a comment in the rendered draft.
"""

import json
import os
from typing import Dict, List

_SECTION_LABELS = {
    "aws_news": "AWS What's New updates",
    "devto_articles": "dev.to community articles from AWS builders",
    "reddit_posts": "Reddit discussions from r/aws and related subs",
    "github_repos": "GitHub repositories related to AWS",
}


def score_and_enrich(sections: Dict[str, List], config: Dict) -> Dict[str, List]:
    api_key = os.getenv("ANTHROPIC_API_KEY")
    if not api_key:
        print("  Warning: ANTHROPIC_API_KEY not set — skipping AI scoring (items will appear unscored)")
        return sections

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=api_key)
    except ImportError:
        print("  Warning: anthropic package not installed. Run: pip install anthropic")
        return sections

    audience = config["audience"]["description"]

    for section_key, items in sections.items():
        if not items:
            continue

        label = _SECTION_LABELS.get(section_key, section_key)
        print(f"  Scoring {len(items)} items: {label} ...")

        items_text = "\n\n".join(
            f"{i + 1}. Title: {item['title']}\n"
            f"   URL: {item['url']}\n"
            f"   Summary: {_summary(item)[:300]}"
            for i, item in enumerate(items)
        )

        prompt = f"""You are curating a monthly newsletter called "AWS for Product Builder".

Audience: {audience}

Below are {len(items)} items from: {label}

For each item return:
- index: the item number (1-based)
- relevance_score: 1-10 (10 = essential for product builders on AWS)
- why_it_matters: one concrete sentence from a product builder perspective — be specific, not generic
- keep: true if relevance_score >= 6

Items:
{items_text}

Return ONLY a valid JSON array. No markdown fences, no explanation. Example:
[{{"index": 1, "relevance_score": 8, "why_it_matters": "...", "keep": true}}]"""

        try:
            response = client.messages.create(
                model="claude-haiku-4-5-20251001",
                max_tokens=4000,
                messages=[{"role": "user", "content": prompt}],
            )
            raw = response.content[0].text.strip()
            # Strip markdown code fences if present
            if raw.startswith("```"):
                raw = raw.split("```")[1]
                if raw.startswith("json"):
                    raw = raw[4:]
            scored = json.loads(raw.strip())

            for s in scored:
                idx = s["index"] - 1
                if 0 <= idx < len(items):
                    items[idx]["relevance_score"] = s.get("relevance_score", 5)
                    items[idx]["why_it_matters"] = s.get("why_it_matters", "")
                    items[idx]["keep"] = s.get("keep", True)

            sections[section_key] = sorted(
                items, key=lambda x: x.get("relevance_score", 0), reverse=True
            )
            print(f"    Done — top score: {sections[section_key][0].get('relevance_score', '?')}/10")

        except Exception as e:
            print(f"  Warning: AI scoring failed for {section_key}: {e}")

    return sections


def _summary(item: Dict) -> str:
    return item.get("summary") or item.get("description") or item.get("why_it_matters") or ""
