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
EMAIL = "r.manov@gmail.com"
LINKEDIN_URL = "https://linkedin.com/in/ruslan-m-a7a40266"
CODE_BYTES_CAP = 6.0
FRESHNESS_WINDOW_DAYS = 180.0
STAR_IMPACT_WEIGHT = 6.0
FORK_IMPACT_WEIGHT = 4.0
CODE_FILE_SUFFIXES = {
    ".py",
    ".rs",
    ".java",
    ".js",
    ".ts",
    ".tsx",
    ".jsx",
    ".go",
    ".c",
    ".cc",
    ".cpp",
    ".h",
    ".hpp",
    ".cs",
    ".sql",
    ".vb",
    ".cls",
    ".pq",
    ".sh",
}
TEST_HINTS = {"tests", "test", "spec", "pytest.ini", "tox.ini"}
DOC_HINTS = {
    "docs",
    "doc",
    "Project_Docs",
    "mkdocs.yml",
    "mkdocs.yaml",
    "docs.md",
    "DEMO.md",
    "INSTALL.md",
    "WIKI.md",
    "CONTRIBUTING.md",
}
MANIFEST_HINTS = {
    "Cargo.toml",
    "pyproject.toml",
    "package.json",
    "go.mod",
    "pom.xml",
    "build.gradle",
    "build.gradle.kts",
    "requirements.txt",
    "setup.py",
    "setup.cfg",
}
META_DIR_HINTS = {
    ".git",
    ".github",
    ".cargo",
    "docs",
    "doc",
    "tests",
    "test",
    "spec",
    "scripts",
    "config",
    "paper",
    "demo",
    "examples",
    "assets",
    "templates",
}

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


def gh_api(endpoint: str, warn: bool = True):
    """Call GitHub API via gh CLI. Returns parsed JSON."""
    result = subprocess.run(
        [GH, "api", endpoint],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        if warn:
            print(
                f"  WARN: gh api {endpoint}: {result.stderr.strip()}", file=sys.stderr
            )
        return None
    return json.loads(result.stdout)


def fetch_profile() -> dict:
    """Fetch public profile metadata for the README header."""
    profile = gh_api(f"users/{OWNER}")
    if not profile or not isinstance(profile, dict):
        return {}
    return profile


def fetch_public_repos() -> list[dict]:
    """Fetch all public repos owned by the profile."""
    repos = gh_api(f"users/{OWNER}/repos?per_page=100&type=owner&sort=pushed")
    if not repos:
        sys.exit("ERROR: Could not fetch repos. Check gh auth status.")
    return [r for r in repos if not r.get("private")]


def filter_primary_repos(repos: list[dict]) -> list[dict]:
    """Exclude forks for ranking and language stats.

    GitHub's public repo count includes forks, so stats should use the full
    public set. Featured projects and language bars should stay focused on
    first-party work.
    """
    return [r for r in repos if not r.get("fork")]


def fetch_repo_quality_signals(repos: list[dict]) -> dict[str, dict]:
    """Fetch universal quality signals used for featured repo ranking."""
    signals: dict[str, dict] = {}
    for i, repo in enumerate(repos):
        name = repo["name"]
        print(f"  [{i + 1}/{len(repos)}] {name}")

        root_items = gh_api(f"repos/{OWNER}/{name}/contents/", warn=False)
        if not isinstance(root_items, list):
            root_items = []

        item_names = {
            item.get("name", "") for item in root_items if isinstance(item, dict)
        }
        root_dirs = [
            item.get("name", "")
            for item in root_items
            if isinstance(item, dict) and item.get("type") == "dir"
        ]
        code_file_count = 0
        for item in root_items:
            if not isinstance(item, dict) or item.get("type") != "file":
                continue
            suffix = Path(item.get("name", "")).suffix.lower()
            if suffix in CODE_FILE_SUFFIXES:
                code_file_count += 1

        crates_children = gh_api(f"repos/{OWNER}/{name}/contents/crates", warn=False)
        crates_dir_count = 0
        if isinstance(crates_children, list):
            crates_dir_count = sum(
                1
                for item in crates_children
                if isinstance(item, dict) and item.get("type") == "dir"
            )

        workflows = gh_api(
            f"repos/{OWNER}/{name}/contents/.github/workflows",
            warn=False,
        )
        releases = gh_api(f"repos/{OWNER}/{name}/releases?per_page=1", warn=False)

        has_ci = isinstance(workflows, list) and len(workflows) > 0
        has_tests = any(hint in item_names for hint in TEST_HINTS)
        has_docs = any(hint in item_names for hint in DOC_HINTS)
        has_license = bool(repo.get("license")) or any(
            name.upper().startswith("LICENSE") for name in item_names
        )
        has_releases = isinstance(releases, list) and len(releases) > 0
        has_homepage = bool((repo.get("homepage") or "").strip())
        has_manifest = any(hint in item_names for hint in MANIFEST_HINTS)
        has_src = "src" in item_names or "crates" in item_names
        has_quality_gate = has_ci or has_tests or has_docs
        multiple_crates = crates_dir_count >= 2 and has_quality_gate
        code_root_dirs = [
            dir_name
            for dir_name in root_dirs
            if dir_name not in META_DIR_HINTS and not dir_name.startswith(".")
        ]
        multi_binary_workspace = (
            "Cargo.toml" in item_names
            and len(code_root_dirs) >= 3
            and has_quality_gate
            and (multiple_crates or "src" not in item_names)
        )
        toy_single_file = (
            code_file_count <= 2
            and not has_tests
            and not has_ci
            and not has_docs
            and not has_manifest
            and not has_src
        )

        signals[name] = {
            "has_ci": has_ci,
            "has_tests": has_tests,
            "has_docs": has_docs,
            "has_license": has_license,
            "has_releases": has_releases,
            "has_homepage": has_homepage,
            "multiple_crates": multiple_crates,
            "multi_binary_workspace": multi_binary_workspace,
            "toy_single_file": toy_single_file,
        }
    return signals


def score_repo(repo: dict, lang_bytes: dict[str, int], signals: dict) -> float:
    """Rank repos by external impact, technical substance, and proof signals."""
    total_bytes = sum(lang_bytes.values()) if lang_bytes else 0
    stars = repo.get("stargazers_count", 0)
    forks = repo.get("forks_count", 0)

    impact = (
        math.log1p(stars) * STAR_IMPACT_WEIGHT + math.log1p(forks) * FORK_IMPACT_WEIGHT
    )

    substance = 0.0
    if total_bytes > 0:
        substance = min(math.log10(total_bytes), CODE_BYTES_CAP) * 3

    freshness = 0.0
    pushed = repo.get("pushed_at", "")
    if pushed:
        pushed_dt = datetime.fromisoformat(pushed.replace("Z", "+00:00"))
        days = max(0, (datetime.now(timezone.utc) - pushed_dt).days)
        freshness = 6 / (1 + days / FRESHNESS_WINDOW_DAYS)

    proof = 0.0
    proof += 4 if signals.get("has_ci") else 0
    proof += 4 if signals.get("has_tests") else 0
    proof += 3 if signals.get("has_license") else 0
    proof += 3 if signals.get("has_releases") else 0
    proof += 2 if signals.get("has_homepage") else 0
    proof += 2 if signals.get("has_docs") else 0
    proof += 3 if signals.get("multiple_crates") else 0
    proof += 2 if signals.get("multi_binary_workspace") else 0

    penalty = 0.0
    name_desc = (repo["name"] + " " + (repo.get("description") or "")).lower()
    if any(ind in name_desc for ind in COURSEWORK_INDICATORS):
        penalty += 12
    if repo.get("archived"):
        penalty += 8
    if signals.get("toy_single_file"):
        penalty += 5

    return impact + substance + freshness + proof - penalty


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
    """Render a text progress bar: ████████     (space-padded, no ghost blocks)."""
    filled = round(pct / 100 * width)
    return "\u2588" * filled + " " * (width - filled)


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


def build_contact_line(profile: dict) -> str:
    """Build contact links from live profile metadata plus stable external links."""
    parts: list[str] = []

    blog = (profile.get("blog") or "").strip()
    if blog:
        parts.append(f"[Resume / CV]({blog})")

    parts.append(f"[LinkedIn]({LINKEDIN_URL})")
    parts.append(f"[{EMAIL}](mailto:{EMAIL})")

    location = (profile.get("location") or "").strip()
    if location:
        parts.append(location)

    return " \u00b7 ".join(parts)


def generate():
    """Main entry point."""
    script_dir = Path(__file__).resolve().parent
    repo_root = script_dir.parent
    template_path = repo_root / "templates" / "README.template.md"
    output_path = repo_root / "README.md"

    if not template_path.exists():
        sys.exit(f"ERROR: Template not found at {template_path}")

    print(f"Using gh: {GH}")
    print("Fetching profile...")
    profile = fetch_profile()

    print("Fetching repos...")
    all_repos = fetch_public_repos()
    repos = filter_primary_repos(all_repos)
    print(f"  Found {len(all_repos)} public repos total")
    print(f"  Using {len(repos)} primary repos for ranking")

    print("Fetching language data (for scoring + language bars)...")
    per_repo_langs, lang_stats = fetch_all_language_data(repos)
    print(f"  {len(lang_stats)} languages detected")

    print("Fetching repo quality signals...")
    repo_signals = fetch_repo_quality_signals(repos)

    print("Scoring repos...")
    scored = [
        (
            score_repo(
                r,
                per_repo_langs.get(r["name"], {}),
                repo_signals.get(r["name"], {}),
            ),
            r,
        )
        for r in repos
    ]
    scored.sort(key=lambda x: x[0], reverse=True)

    print(f"Top {TOP_N}:")
    for score, repo in scored[:TOP_N]:
        print(f"  {score:6.1f}  {repo['name']}")

    print("Rendering README...")
    template_text = template_path.read_text(encoding="utf-8")
    readme = Template(template_text).safe_substitute(
        display_name=(profile.get("name") or OWNER),
        featured_table=build_featured_table(scored),
        language_bars=build_language_bars(lang_stats),
        stats_line=build_stats_line(all_repos),
        contact_line=build_contact_line(profile),
        updated_at=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
    )

    output_path.write_text(readme, encoding="utf-8")
    print(f"Done. README written to {output_path}")


if __name__ == "__main__":
    generate()
