"""Regression coverage for the curated profile showcase."""

from __future__ import annotations

import importlib.util
import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "generate_readme", ROOT / "scripts" / "generate_readme.py"
)
assert SPEC is not None and SPEC.loader is not None
generate_readme = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(generate_readme)


def repo(name: str) -> dict[str, str]:
    return {
        "name": name,
        "html_url": f"https://github.com/RMANOV/{name}",
        "language": "Python",
        "description": f"Description for {name}",
    }


class FeaturedRepoSelectionTests(unittest.TestCase):
    def test_curated_repo_is_appended_after_dynamic_top_repos(self) -> None:
        scored = [
            (100.0 - index, repo(f"dynamic-{index}"))
            for index in range(generate_readme.TOP_N + 1)
        ]
        scored.append((1.0, repo("algorithmic-arts")))

        selected = generate_readme.select_featured_repos(scored)

        self.assertEqual(
            [entry[1]["name"] for entry in selected],
            [
                *(f"dynamic-{index}" for index in range(generate_readme.TOP_N)),
                "algorithmic-arts",
            ],
        )

    def test_curated_repo_is_not_duplicated_when_already_in_dynamic_top(self) -> None:
        scored = [(100.0, repo("algorithmic-arts"))]
        scored.extend(
            (90.0 - index, repo(f"dynamic-{index}"))
            for index in range(generate_readme.TOP_N)
        )

        selected = generate_readme.select_featured_repos(scored)
        names = [entry[1]["name"] for entry in selected]

        self.assertEqual(names.count("algorithmic-arts"), 1)
        self.assertEqual(len(names), generate_readme.TOP_N)

    def test_missing_curated_repo_fails_closed(self) -> None:
        scored = [
            (100.0 - index, repo(f"dynamic-{index}"))
            for index in range(generate_readme.TOP_N + 1)
        ]

        with self.assertRaisesRegex(
            SystemExit,
            "Pinned featured repository is missing.*algorithmic-arts",
        ):
            generate_readme.select_featured_repos(scored)


class CuratedShowcaseTests(unittest.TestCase):
    def test_template_keeps_exact_two_by_two_gallery(self) -> None:
        template = (ROOT / "templates" / "README.template.md").read_text(
            encoding="utf-8"
        )
        showcase = template.split("<!-- Curated showcase:", 1)[1].split(
            "</table>", 1
        )[0]
        rows = re.findall(r"<tr>(.*?)</tr>", showcase, flags=re.DOTALL)

        self.assertEqual(len(rows), 2)
        self.assertEqual([row.count("<td>") for row in rows], [2, 2])
        for asset in generate_readme.CURATED_SHOWCASE_ASSETS:
            self.assertEqual(showcase.count(f"/assets/{asset}"), 1)

    def test_asset_guard_accepts_complete_gallery_and_rejects_loss(self) -> None:
        complete = "\n".join(
            f"/assets/{asset}"
            for asset in generate_readme.CURATED_SHOWCASE_ASSETS
        )
        generate_readme.validate_curated_showcase(complete)

        incomplete = complete.replace(
            "/assets/hyperbolic-flow.gif", "/assets/missing.gif"
        )
        with self.assertRaisesRegex(
            SystemExit,
            "gallery is incomplete: hyperbolic-flow.gif",
        ):
            generate_readme.validate_curated_showcase(incomplete)


if __name__ == "__main__":
    unittest.main()
