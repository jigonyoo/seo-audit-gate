"""All Actor integration tests are offline, including platform adapter tests."""
import asyncio
import io
import json
from pathlib import Path
import socket
import tempfile
import unittest
from unittest.mock import AsyncMock, patch

from actor import run, validate, snapshot_path
from storage import LocalStorage, PlatformStorage
from transport import FakeTransport, Fetcher, Response, UrllibTransport, MAX_BYTES

ROOT = Path(__file__).resolve().parents[1]
ORIGIN = 'https://example.test'


def html(raw):
    return Response(200, raw.encode(), {'Content-Type': 'text/html; charset=utf-8'})


class OfflineTests(unittest.TestCase):
    def setUp(self):
        # asyncio uses an AF_UNIX socketpair internally; block outbound connects.
        self.network = patch.object(socket.socket, 'connect', side_effect=AssertionError('network forbidden'))
        self.network.start()
        self.addCleanup(self.network.stop)

    def fetcher(self, routes, **options):
        transport = FakeTransport(routes)
        return Fetcher(transport, interval_ms=0, sleep=lambda _: None, **options), transport

    def test_snapshot_storage_grades_charging_and_no_promises(self):
        fixture = (ROOT / 'tests/fixtures/site_clean/index.html').read_text()
        fetcher, transport = self.fetcher({
            ORIGIN + '/robots.txt': Response(200, b'User-agent: *\nDisallow: /private'),
            ORIGIN + '/': html(fixture + '<a href="/next">next</a><a href="/private">no</a>'
                                  '<a href="https://other.test/">external</a>'
                                  '<a href="/failed">fail</a><a href="/?q=1">query</a>'),
            ORIGIN + '/next': html('<title>Next</title><a href="/">home</a>'),
            ORIGIN + '/failed': Response(503, b''),
            ORIGIN + '/sitemap.xml': Response(200, b'<urlset/>'),
        })
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            storage = LocalStorage(temp)
            report = asyncio.run(run({'startUrl': ORIGIN}, storage, fetcher=fetcher))
            self.assertEqual(report['page_count'], 2)
            self.assertNotIn('robots.txt.missing', report['counts_by_type'])
            self.assertNotIn('sitemap.xml.missing', report['counts_by_type'])
            self.assertEqual(storage.charges, ['page-audited'] * 2)
            records = list((Path(temp) / 'datasets/default').glob('*.json'))
            self.assertEqual(len(records), 2)
            kv = Path(temp) / 'key_value_stores/default'
            self.assertEqual(json.loads((kv / 'AUDIT.json').read_text()), report)
            markdown = (kv / 'AUDIT-MARKDOWN.md').read_text()
            self.assertIn('Partial static snapshot', markdown)
            self.assertIn('UNVERIFIABLE', markdown)
            outputs = [report, markdown] + [json.loads(p.read_text()) for p in records]
            for output in outputs:
                for phrase in ('guarantee', 'will rank', 'first page', 'position 1', '#1'):
                    self.assertNotIn(phrase, json.dumps(output).lower())
            for finding in report['findings']:
                self.assertIn(finding['grade'], ('CONFIRMED', 'INFERRED', 'UNVERIFIABLE'))
                self.assertTrue(finding['evidence'])
        requested = [c[0] for c in transport.calls]
        self.assertNotIn(ORIGIN + '/private', requested)
        self.assertFalse(any('other.test' in url or '?q=' in url for url in requested))

    def test_page_limit_and_duplicate_redirects(self):
        fetcher, transport = self.fetcher({
            ORIGIN + '/robots.txt': Response(200, b'User-agent: *\nAllow: /'),
            ORIGIN + '/': html('<a href="/a.html">a</a><a href="/b.html">b</a>'),
            ORIGIN + '/a.html': Response(302, b'', {'Location': '/'}),
            ORIGIN + '/b.html': html('<title>B</title>'),
        })
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            storage = LocalStorage(temp)
            report = asyncio.run(run({'startUrl': ORIGIN, 'maxPages': 1}, storage, fetcher=fetcher))
            self.assertEqual(report['page_count'], 1)
            self.assertNotIn(ORIGIN + '/a.html', [c[0] for c in transport.calls])
            self.assertEqual(len(storage.charges), 1)
        fetcher, _ = self.fetcher({
            ORIGIN + '/robots.txt': Response(200, b'User-agent: *\nAllow: /'),
            ORIGIN + '/': html('<a href="/a.html">a</a><a href="/b.html">b</a>'),
            ORIGIN + '/a.html': Response(302, b'', {'Location': '/'}),
            ORIGIN + '/b.html': html('<title>B</title>'),
        })
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            storage = LocalStorage(temp)
            report = asyncio.run(run({'startUrl': ORIGIN, 'maxPages': 2}, storage, fetcher=fetcher))
            self.assertEqual(report['page_count'], 2)
            self.assertEqual(len(storage.charges), 2)

    def test_robots_fail_closed_and_unreceived_pages_not_charged(self):
        for robots in (Response(404, b''), Response(503, b''), TimeoutError(),
                       Response(302, b'', {'Location': '/other'}),
                       Response(200, b'User-agent: *\nDisallow: /'), Response(200, b'\xff')):
            fetcher, transport = self.fetcher({ORIGIN + '/robots.txt': robots})
            with tempfile.TemporaryDirectory(dir=ROOT) as temp:
                storage = LocalStorage(temp)
                report = asyncio.run(run({'startUrl': ORIGIN}, storage, fetcher=fetcher))
                self.assertEqual(report['page_count'], 0)
                self.assertEqual(storage.charges, [])
                self.assertTrue(all(c[0].endswith('/robots.txt') for c in transport.calls))

    def test_non_html_oversize_and_timeout_are_not_charged(self):
        for response in (Response(200, b'{}', {'Content-Type': 'application/json'}),
                         Response(200, b'x' * (MAX_BYTES + 1), {'Content-Type': 'text/html'}),
                         TimeoutError()):
            fetcher, _ = self.fetcher({
                ORIGIN + '/robots.txt': Response(200, b'User-agent: *\nAllow: /'),
                ORIGIN + '/': response,
            })
            with tempfile.TemporaryDirectory(dir=ROOT) as temp:
                storage = LocalStorage(temp)
                report = asyncio.run(run({'startUrl': ORIGIN}, storage, fetcher=fetcher))
                self.assertEqual(report['page_count'], 0)
                self.assertEqual(storage.charges, [])

    def test_robots_crawl_delay_and_cached_rules(self):
        elapsed = [0]

        def sleep(delay):
            elapsed[0] += delay

        transport = FakeTransport({
            ORIGIN + '/robots.txt': Response(200, b'User-agent: *\nAllow: /\nCrawl-delay: 5'),
            ORIGIN + '/': html('<h1>Home</h1>'),
        })
        fetcher = Fetcher(transport, interval_ms=1000, clock=lambda: elapsed[0], sleep=sleep)
        self.assertIsNotNone(fetcher.fetch(ORIGIN + '/'))
        self.assertIsNotNone(fetcher.fetch(ORIGIN + '/'))
        self.assertEqual(elapsed[0], 10)
        self.assertEqual(sum(url.endswith('/robots.txt') for url, _, _ in transport.calls), 1)

    def test_actor_configuration_matches_runtime_defaults(self):
        config = json.loads((ROOT / '.actor/actor.json').read_text())
        schema = json.loads((ROOT / '.actor/input_schema.json').read_text())
        self.assertEqual(config['input'], './input_schema.json')
        self.assertEqual(schema['required'], ['startUrl'])
        self.assertEqual(schema['properties']['maxPages']['default'], 20)
        self.assertEqual(schema['properties']['maxPages']['maximum'], 200)
        self.assertEqual(schema['properties']['requestIntervalMillis']['default'], 1000)

    def test_redirect_host_and_robots_checked_before_request(self):
        for target in ('https://other.test/', '/private'):
            fetcher, transport = self.fetcher({
                ORIGIN + '/robots.txt': Response(200, b'User-agent: *\nDisallow: /private'),
                ORIGIN + '/': Response(302, b'', {'Location': target}),
            })
            self.assertIsNone(fetcher.fetch(ORIGIN + '/'))
            self.assertEqual(len(transport.calls), 2)

    def test_retry_after_backoff_timeout_and_domain_interval(self):
        now = [0.0]
        sleeps = []

        def sleep(delay):
            sleeps.append(delay)
            now[0] += delay

        transport = FakeTransport({
            ORIGIN + '/robots.txt': Response(200, b'User-agent: *\nAllow: /'),
            ORIGIN + '/': [Response(429, b'', {'Retry-After': '5'}),
                           Response(503, b'', {'Retry-After': 'Thu, 01 Jan 1970 00:00:10 GMT'}),
                           TimeoutError(), html('<title>OK</title>')],
        })
        fetcher = Fetcher(transport, user_agent='TestBot', interval_ms=1000,
                          timeout=7, clock=lambda: now[0], wall_clock=lambda: now[0], sleep=sleep)
        self.assertIsNotNone(fetcher.fetch(ORIGIN + '/'))
        self.assertIn(5, sleeps)
        self.assertIn(4, sleeps)
        self.assertTrue(all(agent == 'TestBot' and timeout == 7 for _, agent, timeout in transport.calls))
        self.assertGreaterEqual(now[0], 14)

    def test_urllib_size_bound_without_network(self):
        class FakeResponse(io.BytesIO):
            code = 200
            headers = {'Content-Type': 'text/html'}

        for size in (MAX_BYTES, MAX_BYTES + 1):
            opener = unittest.mock.Mock()
            opener.open.return_value = FakeResponse(b'x' * size)
            with patch('transport.build_opener', return_value=opener):
                if size > MAX_BYTES:
                    with self.assertRaises(ValueError):
                        UrllibTransport().request(ORIGIN, 'Bot', 3)
                else:
                    self.assertEqual(len(UrllibTransport().request(ORIGIN, 'Bot', 3).body), size)
                self.assertEqual(opener.open.call_args.kwargs['timeout'], 3)

    def test_input_and_paths(self):
        self.assertEqual(validate({'startUrl': ORIGIN})[1:], (20, 1000, 'SeoAuditGate'))
        self.assertEqual(validate({'startUrl': ORIGIN + '/?x=1'})[0], ORIGIN + '/?x=1')
        for value in ({}, {'startUrl': 'file:///tmp/a'},
                      {'startUrl': 'https://user:pass@example.test/'},
                      {'startUrl': ORIGIN, 'maxPages': 201},
                      {'startUrl': ORIGIN, 'maxPages': True},
                      {'startUrl': ORIGIN, 'requestIntervalMillis': -1},
                      {'startUrl': ORIGIN, 'userAgent': 'bad\nagent'}):
            with self.assertRaises(ValueError):
                validate(value)
        for path in ('/%2e%2e/escape', '/a/../b', '/a%5cb', '/%00'):
            with self.assertRaises(ValueError):
                snapshot_path(ORIGIN + path)

    def test_local_input_and_platform_adapter(self):
        with tempfile.TemporaryDirectory(dir=ROOT) as temp:
            path = Path(temp) / 'key_value_stores/default'
            path.mkdir(parents=True)
            (path / 'INPUT.json').write_text(json.dumps({'startUrl': ORIGIN}))
            self.assertEqual(asyncio.run(LocalStorage(temp).get_input()), {'startUrl': ORIGIN})
        actor = unittest.mock.Mock()
        actor.get_input = AsyncMock(return_value={'startUrl': ORIGIN})
        actor.push_data = AsyncMock()
        actor.set_value = AsyncMock()
        actor.charge = AsyncMock(return_value=None)
        storage = PlatformStorage(actor)
        asyncio.run(storage.get_input())
        asyncio.run(storage.push_data({'path': '/index.html'}))
        asyncio.run(storage.set_value('AUDIT', {}, 'application/json'))
        asyncio.run(storage.charge('page-audited'))
        actor.charge.assert_awaited_once_with(event_name='page-audited', count=1)
        actor.set_value.assert_awaited_once_with('AUDIT', '{}', content_type='application/json')


if __name__ == '__main__':
    unittest.main()
