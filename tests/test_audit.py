import os, sys, unittest
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "src"))
import crawl, audit

ROOT = os.path.join(os.path.dirname(__file__), "..")
def go():
    pages = crawl.load(os.path.join(ROOT, "fixtures", "site"))
    smap = crawl.load_sitemap(os.path.join(ROOT, "fixtures", "sitemap.xml"))
    return pages, smap, audit.run(pages, smap)

def checks(fs, name):
    return [f for f in fs if f.check == name]

class ItFindsWhatWasPlanted(unittest.TestCase):
    """Each defect was put in the fixture on purpose. If one stops being found,
    the fixture and the test disagree and one of them is wrong."""

    def test_empty_description_is_not_treated_as_missing(self):
        _, _, fs = go()
        self.assertEqual(len(checks(fs, "description.empty")), 1)
        self.assertEqual(checks(fs, "description.empty")[0].where, "/")

    def test_duplicate_title_names_both_pages(self):
        _, _, fs = go()
        f = checks(fs, "title.duplicate")[0]
        self.assertIn("/about", f.where)
        self.assertIn("/services", f.where)

    def test_multiple_h1(self):
        _, _, fs = go()
        self.assertEqual(checks(fs, "h1.multiple")[0].where, "/services")

    def test_skipped_heading_level(self):
        _, _, fs = go()
        self.assertIn("h1 to h3", checks(fs, "headings.skipped_level")[0].what)

    def test_orphan_page(self):
        _, _, fs = go()
        self.assertEqual(checks(fs, "page.orphan")[0].where, "/orphan")

    def test_dead_sitemap_entry(self):
        _, _, fs = go()
        self.assertEqual(checks(fs, "sitemap.dead_entry")[0].where, "/gone")

    def test_noindex_page_listed_in_sitemap(self):
        _, _, fs = go()
        self.assertEqual(checks(fs, "sitemap.noindex_conflict")[0].where, "/noindex")

class ItDoesNotOverreach(unittest.TestCase):

    def test_page_with_a_good_alt_is_not_flagged(self):
        _, _, fs = go()
        self.assertFalse([f for f in checks(fs, "img.no_alt") if f.where == "/about"])

    def test_a_written_description_is_not_flagged(self):
        _, _, fs = go()
        flagged = {f.where for f in fs if f.check.startswith("description.")}
        self.assertNotIn("/about", flagged)
        self.assertNotIn("/orphan", flagged)

    def test_self_canonical_is_not_flagged(self):
        _, _, fs = go()
        self.assertNotIn("/about", {f.where for f in checks(fs, "canonical.points_elsewhere")})

class ItRefusesToClaimWhatItCannotSee(unittest.TestCase):
    """The reason this repo exists. An audit that cannot see the index should not
    print sentences about rankings as if it could."""

    def test_ranking_effect_is_declared_unverifiable(self):
        _, _, fs = go()
        f = checks(fs, "ranking.effect")[0]
        self.assertEqual(f.grade, audit.UNVERIFIABLE)

    def test_index_status_is_declared_unverifiable(self):
        _, _, fs = go()
        self.assertEqual(checks(fs, "index.status")[0].grade, audit.UNVERIFIABLE)

    def test_no_finding_promises_a_position(self):
        _, _, fs = go()
        for f in fs:
            blob = (f.what + " " + f.fix).lower()
            for word in ("guarantee", "will rank", "first page", "position 1", "#1"):
                self.assertNotIn(word, blob, f"{f.check} promises an outcome")

    def test_every_confirmed_finding_carries_evidence(self):
        _, _, fs = go()
        for f in fs:
            if f.grade == audit.CONFIRMED:
                self.assertTrue(f.evidence.strip(), f"{f.check} has no evidence")

if __name__ == "__main__":
    unittest.main()
