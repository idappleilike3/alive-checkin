import unittest
from urllib.parse import parse_qs, urlparse

from guardian_group_flex import guardian_invite_bind_url


class GuardianInviteAllEntriesStoryFirstTests(unittest.TestCase):
    def test_backend_text_invite_opens_public_story_before_liff_form(self):
        url = guardian_invite_bind_url("Uabc_123")
        parsed = urlparse(url)

        self.assertEqual(parsed.scheme, "https")
        self.assertEqual(parsed.netloc, "alive-checkin.onrender.com")
        self.assertEqual(parsed.path, "/invite")
        self.assertEqual(parse_qs(parsed.query).get("invite_from"), ["Uabc_123"])


if __name__ == "__main__":
    unittest.main()
