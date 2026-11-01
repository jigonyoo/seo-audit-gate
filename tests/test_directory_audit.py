import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
import directory_audit as directory

ROOT = Path(__file__).resolve().parents[1]
FIXTURES = ROOT / 'tests' / 'fixtures'
PLANTED = {
    'robots.txt.missing': 'site',
    'sitemap.xml.missing': 'site',
    'canonical.missing': '/index.html',
    'description.missing': '/index.html',
    'og:image.missing': '/index.html',
    'jsonld.missing': '/index.html',
    'links.broken': '/index.html',
    'h1.multiple': '/index.html',
}


def measured_table():
    report = directory.run(FIXTURES / 'site_defects')
    actual = {(f['check'], f['where']) for f in report['findings']}
    rows = ['| Planted issue | Planted | Detected | Rate |', '|---|---:|---:|---:|']
    detected = 0
    for check, where in PLANTED.items():
        found = int((check, where) in actual)
        detected += found
        rows.append(f'| `{check}` | 1 | {found} | {found:.0%} |')
    rows.append(f'| Total | {len(PLANTED)} | {detected} | {detected / len(PLANTED):.0%} |')
    return '\n'.join(rows)


class DirectoryAuditTests(unittest.TestCase):
    def test_all_planted_defects(self):
        report = directory.run(FIXTURES / 'site_defects')
        actual = {(f['check'], f['where']) for f in report['findings']}
        self.assertTrue(set(PLANTED.items()) <= actual)
        self.assertEqual(report['page_count'], 3)
        self.assertEqual(report['finding_count'], sum(report['counts_by_type'].values()))

    def test_readme_table_is_computed_from_fixture(self):
        self.assertIn(measured_table(), (ROOT / 'README.md').read_text())
        print('\nMeasured fixture detection:\n' + measured_table())

    def test_clean_site_has_only_unverifiable_findings(self):
        report = directory.run(FIXTURES / 'site_clean')
        self.assertEqual(report['page_count'], 3)
        self.assertEqual({f['check'] for f in report['findings']}, {'ranking.effect', 'index.status'})
        self.assertEqual(report['pages'][2]['path'], '/index.html')
        self.assertTrue(all(p['jsonld_types'] == ['WebPage'] for p in report['pages']))

    def test_no_promises_and_every_finding_is_graded(self):
        for name in ('site_clean', 'site_defects'):
            for f in directory.run(FIXTURES / name)['findings']:
                self.assertIn(f['grade'], ('CONFIRMED', 'INFERRED', 'UNVERIFIABLE'))
                self.assertTrue(f['evidence'].strip())
                for phrase in ('guarantee', 'will rank', 'first page', 'position 1', '#1'):
                    self.assertNotIn(phrase, (f['what'] + ' ' + f['fix']).lower())

    def audit_html(self, raw, extra=None):
        # Keep temporary writes inside the worktree, including on locked-down hosts.
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            root = Path(temp)
            (root / 'index.html').write_text(raw, encoding='utf-8')
            for name, content in (extra or {}).items():
                target = root / name
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(content, encoding='utf-8')
            return directory.run(root)

    def test_missing_metadata_h1_and_language(self):
        report = self.audit_html('<html><head></head><body></body></html>')
        types = report['counts_by_type']
        for check in ('title.missing', 'description.missing', 'canonical.missing',
                      'og:title.missing', 'og:description.missing', 'og:image.missing',
                      'og:url.missing', 'twitter:card.missing', 'jsonld.missing',
                      'h1.missing', 'html.lang.missing', '404.html.missing'):
            self.assertEqual(types.get(check), 1, check)

    def test_parser_attribute_order_case_entities_and_nested_title(self):
        report = self.audit_html('''<HTML LANG=en><TITLE>Fish &amp; Chips</TITLE>
            <META CONTENT="Description" NAME="DESCRIPTION">
            <LINK HREF="/" REL="alternate canonical" hreflang=en>
            <h1>Hello <em>world</em></h1>
            <script type="application/ld+json">{"@graph":[{"@type":["WebPage","Article"]}]}</script>''')
        page = report['pages'][0]
        self.assertEqual(page['title'], 'Fish & Chips')
        self.assertEqual(page['meta']['description'], 'Description')
        self.assertEqual(page['canonical'], '/')
        self.assertEqual(page['lang'], 'en')
        self.assertEqual(page['h1_count'], 1)
        self.assertEqual(page['jsonld_types'], ['Article', 'WebPage'])

    def test_invalid_json_missing_type_and_invalid_hreflang(self):
        report = self.audit_html('''<script type="application/ld+json">{bad}</script>
            <script type="application/ld+json">{}</script>
            <link rel=alternate hreflang="" href="">''')
        for check in ('jsonld.invalid', 'jsonld.type.missing', 'hreflang.invalid'):
            self.assertEqual(report['counts_by_type'].get(check), 1)

    def test_links_resolve_files_directories_queries_fragments_and_base(self):
        report = self.audit_html('''<link rel=canonical href="https://example.test/">
            <base href="/nested/">
            <a href="file%20name.html?q=1#x">file</a><a href="../">home</a>
            <a href="https://example.test/nested/">same origin</a>
            <a href="//other.test/missing">external</a><a href="mailto:a@example.test">mail</a>
            <a href="missing.html">broken</a><a href="/%2e%2e/outside.html">escape</a>
            <link rel=alternate hreflang=fr href="/missing-fr.html">''',
            {'nested/file name.html': '<h1>File</h1>', 'nested/index.html': '<h1>Directory</h1>'})
        broken = [f['evidence'] for f in report['findings'] if f['check'] == 'links.broken']
        self.assertEqual(len(broken), 3, broken)

    def test_symlinks_cannot_escape_site(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            parent = Path(temp)
            site = parent / 'site'
            site.mkdir()
            (parent / 'outside.html').write_text('secret')
            (site / 'escape.html').symlink_to(parent / 'outside.html')
            (site / 'index.html').write_text('<a href="escape.html">link</a>')
            report = directory.run(site)
            self.assertEqual(report['page_count'], 1)
            self.assertEqual(report['counts_by_type']['links.broken'], 1)

    def test_sitemap_coverage_and_invalid_xml(self):
        report = self.audit_html('<h1>Home</h1>', {'sitemap.xml':
            '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
            '<url><loc>https://example.test/?a=1&amp;b=2</loc></url></urlset>',
            'nested/index.html': '<h1>Nested</h1>'})
        missing = [f['where'] for f in report['findings'] if f['check'] == 'sitemap.page_missing']
        self.assertEqual(missing, ['/nested/index.html'])
        invalid = self.audit_html('', {'sitemap.xml': '<broken'})
        self.assertEqual(invalid['counts_by_type']['sitemap.invalid'], 1)

    def test_cli_writes_json_and_markdown_offline(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as output:
            result = subprocess.run([sys.executable, str(ROOT / 'src/cli.py'), 'audit-dir',
                                     str(FIXTURES / 'site_clean'), '--out', output],
                                    capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            report = json.loads((Path(output) / 'audit.json').read_text())
            markdown = (Path(output) / 'audit.md').read_text()
            self.assertEqual(report['page_count'], 3)
            self.assertIn('Pages: 3.', markdown)
            for check, count in report['counts_by_type'].items():
                self.assertIn(f'| {check} | {count} |', markdown)
            self.assertIn('UNVERIFIABLE', markdown)

    def test_audit_never_uses_network(self):
        with patch('socket.socket', side_effect=AssertionError('network forbidden')):
            directory.run(FIXTURES / 'site_clean')


if __name__ == '__main__':
    unittest.main()
