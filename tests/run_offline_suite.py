"""Run every Python test with outbound networking disabled."""

import sys
import unittest
from pathlib import Path

from tests.offline_guard import offline_network_guard


def main() -> int:
    project_root = Path(__file__).resolve().parents[1]
    suite = unittest.defaultTestLoader.discover(
        str(project_root / "tests"),
        pattern="test_*.py",
    )
    with offline_network_guard():
        result = unittest.TextTestRunner(verbosity=1).run(suite)
    return 0 if result.wasSuccessful() else 1


if __name__ == "__main__":
    sys.exit(main())
