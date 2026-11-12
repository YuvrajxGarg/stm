import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from stm import updater  # noqa: E402
from stm.settings import Settings  # noqa: E402


class UpdaterTests(unittest.TestCase):
    def make(self, zip_url, sha_url):
        s = Settings(os.path.join(tempfile.mkdtemp(), "settings.json"))
        s.set("auto_install", False)
        u = updater.Updater(s, lambda st: None)
        u.fetch_latest = lambda: {"version": "99.0.0", "notes": "", "page": "https://github.com/x",
                                  "zip": zip_url, "sha": sha_url, "published": None}
        return u

    def test_release_without_this_platforms_build_is_not_offered(self):
        self.assertEqual(self.make(None, None).check(manual=True)["phase"], "uptodate")
        self.assertEqual(self.make("https://x/z.zip", None).check(manual=True)["phase"], "uptodate")

    def test_complete_release_is_offered(self):
        self.assertEqual(self.make("https://x/z.zip", "https://x/z.zip.sha256").check(manual=True)["phase"], "available")

    def test_versions(self):
        self.assertTrue(updater.is_newer("1.0.10", "1.0.9"))
        self.assertFalse(updater.is_newer("1.0.0", "1.0.0"))


if __name__ == "__main__":
    unittest.main()
