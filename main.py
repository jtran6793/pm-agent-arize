import os
import json
import pathlib
import requests
from datetime import datetime, timezone, timedelta
from anthropic import Anthropic
from dotenv import load_dotenv
from opentelemetry import trace
from openinference.semconv.trace import SpanAttributes
from instrumentation import setup_tracing

load_dotenv()

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY")
GITHUB_TOKEN = os.getenv("GITHUB_TOKEN")
ARIZE_SPACE_ID = os.getenv("ARIZE_SPACE_ID")
ARIZE_API_KEY = os.getenv("ARIZE_API_KEY")

REQUIRED_VARS = ["ANTHROPIC_API_KEY", "GITHUB_TOKEN", "ARIZE_SPACE_ID", "ARIZE_API_KEY"]
missing = [v for v in REQUIRED_VARS if not os.getenv(v)]
if missing:
    print(f"Error: Missing required environment variables: {', '.join(missing)}")
    raise SystemExit(1)

tracer_provider = setup_tracing()
tracer = trace.get_tracer(__name__)

client = Anthropic(api_key=ANTHROPIC_API_KEY)
MODEL = "claude-sonnet-4-6"


def parse_json(text: str) -> dict:
    """Strip markdown fences then parse JSON."""
    text = text.strip()
    if text.startswith("```"):
        lines = text.split("\n")
        # Drop opening fence (and optional language tag) and closing fence
        lines = lines[1:] if lines[0].startswith("```") else lines
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines).strip()
    return json.loads(text)


# ─────────────────────────────────────────────
# Step 1: Fetch GitHub Issues
# ─────────────────────────────────────────────
def fetch_github_issues() -> list[dict]:
    print("Step 1: Fetching GitHub issues from Arize-ai/phoenix...")

    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }

    issues = []
    page = 1

    while len(issues) < 100:
        response = requests.get(
            "https://api.github.com/repos/Arize-ai/phoenix/issues",
            headers=headers,
            params={"state": "open", "per_page": 100, "page": page, "sort": "created", "direction": "desc"},
        )

        if response.status_code != 200:
            print(f"Error fetching issues: {response.status_code} — {response.text}")
            raise SystemExit(1)

        page_data = response.json()
        if not page_data:
            break

        for issue in page_data:
            if "pull_request" in issue:
                continue

            issues.append({
                "number": issue["number"],
                "title": issue["title"],
                "body": (issue.get("body") or "").strip(),
                "labels": [label["name"] for label in issue.get("labels", [])],
                "reactions": issue.get("reactions", {}).get("+1", 0),
                "comments": issue.get("comments", 0),
                "created_at": issue["created_at"],
            })

            if len(issues) >= 100:
                break

        page += 1

    print(f"  Fetched {len(issues)} issues.\n")
    return issues[:100]


# ─────────────────────────────────────────────
# Step 2a: Identify Emergent Themes
# ─────────────────────────────────────────────
def identify_themes(issues: list[dict]) -> list[dict]:
    print("Step 2a: Identifying emergent themes with Claude...")

    issues_text = "\n\n".join(
        f"Issue #{i['number']}: {i['title']}\n{i['body'][:600]}"
        for i in issues
    )

    prompt = f"""You are analyzing GitHub issues for Phoenix, an open-source LLM observability platform.

Here are {len(issues)} open issues:

{issues_text}

Read through all issues and identify 6 to 8 natural themes that emerge from the data. \
Group related issues into meaningful categories useful for a product manager.

Return a JSON object with this exact structure — no other text:
{{
  "themes": [
    {{
      "name": "Theme Name",
      "description": "One-sentence description of what this theme covers"
    }}
  ]
}}"""

    response = client.messages.create(
        model=MODEL,
        max_tokens=1024,
        messages=[{"role": "user", "content": prompt}],
    )

    data = parse_json(response.content[0].text)
    themes = data["themes"]

    print(f"  Identified {len(themes)} themes:")
    for t in themes:
        print(f"  • {t['name']}: {t['description']}")
    print()

    return themes


# ─────────────────────────────────────────────
# Step 2b: Classify Each Issue
# ─────────────────────────────────────────────
def classify_issues(issues: list[dict], themes: list[dict]) -> list[dict]:
    print(f"Step 2b: Classifying {len(issues)} issues (one Claude call per issue)...")

    theme_names = [t["name"] for t in themes]
    themes_text = "\n".join(f"- {t['name']}: {t['description']}" for t in themes)

    classified = []

    for idx, issue in enumerate(issues, 1):
        print(f"  [{idx:>3}/{len(issues)}] #{issue['number']} — {issue['title'][:60]}", end="\r")

        prompt = f"""Classify the following GitHub issue into exactly one of these themes:

{themes_text}

Issue title: {issue['title']}
Issue body: {issue['body'][:1000]}

Return a JSON object with this exact structure — no other text:
{{
  "theme": "<exact theme name from the list above>",
  "reason": "One-sentence explanation of why this issue belongs to that theme"
}}"""

        try:
            response = client.messages.create(
                model=MODEL,
                max_tokens=256,
                messages=[{"role": "user", "content": prompt}],
            )
            result = parse_json(response.content[0].text)

            # Fallback if Claude returns an unrecognised theme name
            if result.get("theme") not in theme_names:
                result["theme"] = theme_names[0]
                result["reason"] = "Fallback classification — theme name not recognised."

        except Exception as exc:
            print(f"\n  Warning: classification failed for #{issue['number']}: {exc}")
            result = {"theme": theme_names[0], "reason": "Classification error — assigned to first theme."}

        classified.append({**issue, "theme": result["theme"], "reason": result["reason"]})

    print(f"\n  Classified {len(classified)} issues.\n")
    return classified


# ─────────────────────────────────────────────
# Step 3: Score Each Theme
# ─────────────────────────────────────────────
def score_themes(classified_issues: list[dict], themes: list[dict]) -> list[dict]:
    print("Step 3: Scoring themes...")

    thirty_days_ago = datetime.now(timezone.utc) - timedelta(days=30)

    # Bucket issues by theme
    buckets: dict[str, list[dict]] = {t["name"]: [] for t in themes}
    for issue in classified_issues:
        theme = issue.get("theme")
        if theme in buckets:
            buckets[theme].append(issue)

    scored = []
    for theme in themes:
        name = theme["name"]
        theme_issues = buckets[name]

        issue_count = len(theme_issues)
        total_reactions = sum(i["reactions"] for i in theme_issues)
        total_comments = sum(i["comments"] for i in theme_issues)
        recency_bonus = sum(
            2
            for i in theme_issues
            if datetime.fromisoformat(i["created_at"].replace("Z", "+00:00")) > thirty_days_ago
        )

        score = (issue_count * 3) + (total_reactions * 2) + (total_comments * 1) + recency_bonus

        scored.append({
            "name": name,
            "description": theme["description"],
            "issues": theme_issues,
            "issue_count": issue_count,
            "total_reactions": total_reactions,
            "total_comments": total_comments,
            "recency_bonus": recency_bonus,
            "score": score,
        })

    scored.sort(key=lambda x: x["score"], reverse=True)

    print("  Scores (highest first):")
    for s in scored:
        print(
            f"  • {s['name']}: {s['score']} pts "
            f"({s['issue_count']} issues × 3  +  {s['total_reactions']} reactions × 2  +  "
            f"{s['total_comments']} comments  +  {s['recency_bonus']} recency)"
        )
    print()

    return scored


# ─────────────────────────────────────────────
# Step 4: Generate PM Brief
# ─────────────────────────────────────────────
def generate_pm_brief(scored_themes: list[dict]) -> tuple[str, list[dict]]:
    print("Step 4: Generating PM brief with Claude...")

    top_3 = scored_themes[:3]

    sections = []
    for theme in top_3:
        issue_lines = "\n".join(
            f"  - \"{i['title']}\" (#{i['number']}, {i['reactions']} 👍, {i['comments']} comments)"
            for i in theme["issues"][:20]
        )
        sections.append(
            f"Theme: {theme['name']} (Score: {theme['score']})\n"
            f"Description: {theme['description']}\n"
            f"Issues ({theme['issue_count']} total, showing up to 20):\n{issue_lines}"
        )

    context = "\n\n".join(sections)

    prompt = f"""You are a senior product manager analyzing user feedback for Phoenix, \
an open-source LLM observability and evaluation platform.

Here are the top 3 themes from GitHub issues, ranked by a weighted score \
(issue count × 3 + reactions × 2 + comments × 1 + recency bonus):

{context}

Write a PM brief with exactly these three sections:

## Top 3 Pain Points
Describe each theme as a concrete pain point users are experiencing. \
Cite specific issue titles from the data above as evidence — do not invent claims.

## Recommended Feature to Build
Recommend one specific feature that would address the most critical pain point. \
Be concrete: describe what it does, which user problem it solves, and a high-level \
implementation approach. Name it.

## Rationale
Explain why this feature was chosen over alternatives. \
Reference specific issue titles, reaction counts, and comment counts to justify the decision."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=2048,
        messages=[{"role": "user", "content": prompt}],
    )

    brief = response.content[0].text.strip()
    print("  PM brief generated.\n")
    return brief, top_3


# ─────────────────────────────────────────────
# Step 5: Generate Eval Spec
# ─────────────────────────────────────────────
def generate_eval_spec(pm_brief: str) -> str:
    print("Step 5: Generating eval spec with Claude...")

    prompt = f"""You are a senior ML engineer designing an evaluation framework for a new product feature.

The following PM brief describes a feature that has been approved for development:

{pm_brief}

Write a detailed eval spec for the recommended feature. \
It must be specific enough that an engineer can implement it without asking follow-up questions.

Include exactly these three sections:

## Eval Dimensions
List 3–5 dimensions along which the feature will be evaluated. \
For each dimension provide: a name, what it measures, and why it matters for correctness or quality.

## Example Test Cases
Provide 3 specific test cases. Each must include:
- **Input**: The exact input or scenario (be specific, not generic)
- **Expected Output**: What correct behavior looks like
- **Why It Matters**: What a failure here would indicate about the feature

## Pass/Fail Criteria
Define quantitative pass/fail thresholds for each eval dimension. \
Use concrete numbers (percentages, latency in ms, score ranges) — not vague language like "good" or "acceptable"."""

    response = client.messages.create(
        model=MODEL,
        max_tokens=4096,
        messages=[{"role": "user", "content": prompt}],
    )

    spec = response.content[0].text.strip()
    print("  Eval spec generated.\n")
    return spec


# ─────────────────────────────────────────────
# Save Output
# ─────────────────────────────────────────────
def save_output(
    themes: list[dict],
    scored_themes: list[dict],
    pm_brief: str,
    eval_spec: str,
) -> None:
    pathlib.Path("output").mkdir(exist_ok=True)

    lines = [
        "# Feedback Synthesizer Report",
        f"\n_Generated {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}_\n",
        "---\n",
        "## Identified Themes\n",
    ]

    for t in themes:
        lines.append(f"- **{t['name']}**: {t['description']}")

    lines += [
        "\n---\n",
        "## Theme Scores\n",
        "| Rank | Theme | Issues | Reactions | Comments | Recency Bonus | Score |",
        "|------|-------|--------|-----------|----------|---------------|-------|",
    ]
    for rank, s in enumerate(scored_themes, 1):
        lines.append(
            f"| {rank} | {s['name']} | {s['issue_count']} | {s['total_reactions']} | "
            f"{s['total_comments']} | +{s['recency_bonus']} | **{s['score']}** |"
        )

    lines += [
        "\n---\n",
        "## PM Brief\n",
        pm_brief,
        "\n---\n",
        "## Eval Spec\n",
        eval_spec,
    ]

    output_path = pathlib.Path("output/pm-brief.md")
    output_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"  Saved to {output_path}")


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────
def main() -> None:
    print("=== Feedback Synthesizer ===\n")

    with tracer.start_as_current_span(
        "feedback-synthesizer",
        attributes={SpanAttributes.OPENINFERENCE_SPAN_KIND: "CHAIN"},
    ):
        issues = fetch_github_issues()
        themes = identify_themes(issues)
        classified = classify_issues(issues, themes)
        scored = score_themes(classified, themes)
        pm_brief, _ = generate_pm_brief(scored)
        eval_spec = generate_eval_spec(pm_brief)

        print("Saving output...")
        save_output(themes, scored, pm_brief, eval_spec)

    print("\n=== Done! Output saved to output/pm-brief.md ===")


if __name__ == "__main__":
    main()
    tracer_provider.force_flush()
    tracer_provider.shutdown()
