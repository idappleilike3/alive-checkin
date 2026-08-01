from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[1]


class PlanNameTests(unittest.TestCase):
    def test_legacy_199_plan_name_is_not_used_in_product_files(self):
        excluded = {".git", "__pycache__"}
        legacy_terms = ("199 活" + "著版", "199 活" + "著價")
        allowed_suffixes = {".html", ".js", ".py", ".md"}

        remaining = []
        for path in ROOT.rglob("*"):
            if not path.is_file() or path.suffix not in allowed_suffixes:
                continue
            if any(part in excluded for part in path.parts):
                continue
            text = path.read_text(encoding="utf-8")
            for term in legacy_terms:
                if term in text:
                    remaining.append(f"{path.relative_to(ROOT)}: {term}")

        self.assertFalse(remaining, "\n".join(remaining))


if __name__ == "__main__":
    unittest.main()
