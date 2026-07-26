import subprocess
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class LiffFastRouteBehaviorRunnerTests(unittest.TestCase):
    def test_node_behavior_suite(self):
        result = subprocess.run(
            ["node", "--test", "tests/liff_fast_route.behavior.test.mjs"],
            cwd=ROOT,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=30,
            check=False,
        )
        self.assertEqual(
            result.returncode,
            0,
            msg=f"{result.stdout}\n{result.stderr}",
        )


if __name__ == "__main__":
    unittest.main()
