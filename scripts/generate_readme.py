#!/usr/bin/env python3
"""Auto-generate RMANOV GitHub profile README from live API data.

Zero external dependencies — uses only stdlib + gh CLI.
Runs on GitHub Actions (daily cron) and locally.
"""

import json
import math
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from string import Template

OWNER = "RMANOV"
TOP_N = 6
BAR_WIDTH = 24
MAX_LANGUAGES = 5

# Coursework/hobby indicators — repos matching these get a scoring penalty.
# Penalty, not exclusion: a coursework repo with many stars can still rank.
# These are stable patterns (educational platforms don't rename).
COURSEWORK_INDICATORS = [
    "softuni",
    "hackerrank",
    "course",
    "educational",
    "exercises",
    "tutorial",
    "father-son",
]

# Find gh CLI: PATH first, then portable Windows location
GH = shutil.which("gh") or os.path.expanduser("~/Apps/gh/bin/gh.exe")


def gh_api(endpoint: str):
    """Call GitHub API via gh CLI. Returns parsed JSON."""
    result = subprocess.run(
        [GH, "api", endpoint],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        print(f"  WARN: gh api {endpoint}: {result.stderr.strip()}", file=sys.stderr)
        return None
    return json.loads(result.stdout)


def fetch_repos() -> list[dict]:
    """Fetch all public, non-fork, owned repos."""
    repos = gh_api(f"users/{OWNER}/repos?per_page=100&type=owner&sort=pushed")
    if not repos:
        sys.exit("ERROR: Could not fetch repos. Check gh auth status.")
    return [r for r in repos if not r.get("fork") and not r.get("private")]


def score_repo(repo: dict, lang_bytes: dict[str, int]) -> float:
    """Weighted importance score for ranking.

    Primary signal: code volume (log10 bytes) — objective complexity proxy.
    Secondary: stars, forks, recency, description quality.
    """
    s = 0.0
    s += repo.get("stargazers_count", 0) * 5
    s += repo.get("forks_count", 0) * 3

    # Code volume: primary complexity signal (log10 scale)
    # 1KB→9, 10KB→12, 100KB→15, 1MB→18, 10MB→21
    total_bytes = sum(lang_bytes.values()) if lang_bytes else 0
    if total_bytes > 0:
        s += math.log10(total_bytes) * 3

    # Recency: light boost, max 10 (code volume and stars should dominate)
    pushed = repo.get("pushed_at", "")
    if pushed:
        pushed_dt = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
        days = (datetime.now(timezone.utc) - pushed_dt).days
        s += max(0, 10 - days / 3)

    desc = repo.get("description") or ""
    s += min(len(desc) / 20, 5)

    if repo.get("language"):
        s += 2

    # Coursework penalty: check name + description for educational patterns
    name_desc = (repo["name"] + " " + desc).lower()
    if any(ind in name_desc for ind in COURSEWORK_INDICATORS):
        s *= 0.3

    return s


def fetch_all_language_data(
    repos: list[dict],
) -> tuple[dict[str, dict], dict[str, int]]:
    """Fetch language bytes for each repo.

    Returns (per_repo, aggregated_totals).
    per_repo: {repo_name: {lang: bytes}}
    aggregated_totals: {lang: total_bytes} across all repos
    """
    per_repo: dict[str, dict] = {}
    totals: dict[str, int] = {}
    for i, repo in enumerate(repos):
        name = repo["name"]
        print(f"  [{i + 1}/{len(repos)}] {name}")
        langs = gh_api(f"repos/{OWNER}/{name}/languages")
        if not langs or not isinstance(langs, dict):
            per_repo[name] = {}
            continue
        per_repo[name] = langs
        for lang, bytes_ in langs.items():
            totals[lang] = totals.get(lang, 0) + bytes_
    return per_repo, totals


def render_bar(pct: float, width: int = BAR_WIDTH) -> str:
    """Render a text progress bar: ████████░░░░."""
    filled = round(pct / 100 * width)
    return "\u2588" * filled + "\u2591" * (width - filled)


def build_featured_table(scored: list[tuple[float, dict]]) -> str:
    """Build markdown table of top repos."""
    lines = [
        "| Project | Stack | Description |",
        "|---------|-------|-------------|",
    ]
    for _, repo in scored[:TOP_N]:
        name = repo["name"]
        url = repo["html_url"]
        lang = repo.get("language") or "\u2014"
        desc = repo.get("description") or "No description"
        if len(desc) > 120:
            desc = desc[:120].rsplit(" ", 1)[0] + "..."
        lines.append(f"| [**{name}**]({url}) | {lang} | {desc} |")
    return "\n".join(lines)


def build_language_bars(lang_stats: dict[str, int]) -> str:
    """Build text-based language bar chart."""
    total = sum(lang_stats.values())
    if total == 0:
        return "_No language data available_"

    sorted_langs = sorted(lang_stats.items(), key=lambda x: x[1], reverse=True)
    top = sorted_langs[:MAX_LANGUAGES]
    other_bytes = sum(b for _, b in sorted_langs[MAX_LANGUAGES:])

    lines = ["```"]
    for lang, bytes_ in top:
        pct = bytes_ / total * 100
        lines.append(f"{lang:<12} {render_bar(pct)} {pct:5.1f}%")

    if other_bytes > 0:
        pct = other_bytes / total * 100
        lines.append(f"{'Other':<12} {render_bar(pct)} {pct:5.1f}%")

    lines.append("```")
    return "\n".join(lines)


def build_stats_line(repos: list[dict]) -> str:
    """Build summary stats line."""
    total_stars = sum(r.get("stargazers_count", 0) for r in repos)
    total_forks = sum(r.get("forks_count", 0) for r in repos)
    return (
        f"**{len(repos)}** public repos \u00b7 "
        f"**{total_stars}** stars \u00b7 "
        f"**{total_forks}** forks"
    )


def generate():
    """Main entry point."""
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    template_path = repo_root / "templates" / "README.template.md"
    output_path = repo_root / "README.md"

    if not template_path.exists():
        sys.exit(f"ERROR: Template not found at {template_path}")

    print(f"Using gh: {GH}")
    print("Fetching repos...")
    repos = fetch_repos()
    print(f"  Found {len(repos)} public repos")

    print("Fetching language data (for scoring + language bars)...")
    per_repo_langs, lang_stats = fetch_all_language_data(repos)
    print(f"  {len(lang_stats)} languages detected")

    print("Scoring repos...")
    scored = [(score_repo(r, per_repo_langs.get(r["name"], {})), r) for r in repos]
    scored.sort(key=lambda x: x[0], reverse=True)

    print(f"Top {TOP_N}:")
    for score, repo in scored[:TOP_N]:
        print(f"  {score:6.1f}  {repo['name']}")

    print("Rendering README...")
    contact_line = (
        "[r.manov@gmail.com](mailto:r.manov@gmail.com) \u00b7 "
        "[LinkedIn](https://linkedin.com/in/ruslan-m-a7a40266) \u00b7 "
        "[CV / Portfolio](https://puzzle-espadrille-5cc.notion.site/"
        "Ruslan-Manov-Professional-Autobiography-CV-"
        "303219533f3981459003e2cd80624336)"
    )

    template_text = template_path.read_text(encoding="utf-8")
    readme = Template(template_text).safe_substitute(
        featured_table=build_featured_table(scored),
        language_bars=build_language_bars(lang_stats),
        stats_line=build_stats_line(repos),
        contact_line=contact_line,
        updated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )

    output_path.write_text(readme, encoding="utf-8")
    print(f"Done. README written to {output_path}")


if __name__ == "__main__":
    generate()
