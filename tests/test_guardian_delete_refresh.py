import unittest
from pathlib import Path


class GuardianDeleteRefreshTests(unittest.TestCase):
    def test_member_center_refreshes_server_status_after_guardian_delete(self):
        page = Path("index.html").read_text(encoding="utf-8")
        start = page.index("async function executeDeleteGuardian()")
        end = page.index("async function generateInvite()", start)
        source = page[start:end]

        self.assertIn("currentStatusData.contacts = updatedContacts", source)
        self.assertIn("await refreshStatus()", source)


if __name__ == "__main__":
    unittest.main()
