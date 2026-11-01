"""Collect a bounded same-host snapshot, then reuse the directory audit."""
from collections import deque
import asyncio
from pathlib import Path
import tempfile
from urllib.parse import unquote, urljoin, urlsplit, urlunsplit

import directory_audit
from transport import Fetcher, UrllibTransport


def normalized(url):
    if not isinstance(url, str):
        raise ValueError('URL must be a string')
    parts = urlsplit(url)
    if (parts.scheme not in ('http', 'https') or not parts.hostname
            or parts.username is not None or parts.password is not None):
        raise ValueError('startUrl and links must be HTTP(S) URLs without credentials')
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path or '/', parts.query, ''))


def snapshot_path(url):
    path = unquote(urlsplit(url).path)
    if '\\' in path or '\x00' in path or any(p in ('.', '..') for p in path.split('/')):
        raise ValueError('unsafe snapshot path')
    if path.rstrip('/') in ('/robots.txt', '/sitemap.xml'):
        raise ValueError('reserved auxiliary resource path')
    relative = path.lstrip('/')
    if not relative or path.endswith('/') or Path(relative).suffix.lower() not in ('.html', '.htm'):
        relative = relative.rstrip('/') + '/index.html' if relative else 'index.html'
    return relative


def validate(value):
    if not isinstance(value, dict):
        raise ValueError('INPUT must be an object')
    start = normalized(value.get('startUrl', ''))
    maximum = value.get('maxPages', 20)
    interval = value.get('requestIntervalMillis', 1000)
    agent = value.get('userAgent', 'SeoAuditGate')
    if type(maximum) is not int or not 1 <= maximum <= 200:
        raise ValueError('maxPages must be an integer from 1 to 200')
    if type(interval) is not int or not 0 <= interval <= 60000:
        raise ValueError('requestIntervalMillis must be an integer from 0 to 60000')
    if not isinstance(agent, str) or not agent.strip() or any(ord(c) < 32 or ord(c) > 126 for c in agent):
        raise ValueError('userAgent must be nonempty printable ASCII')
    snapshot_path(start)
    return start, maximum, interval, agent


async def run(value, storage, transport=None, fetcher=None):
    start, maximum, interval, agent = validate(value)
    fetcher = fetcher or Fetcher(transport or UrllibTransport(), agent, interval)
    origin = urlunsplit((*urlsplit(start)[:2], '', '', ''))
    host = urlsplit(start).netloc
    queue, seen, saved = deque([start]), set(), {}
    skipped = []
    # Keep temporary snapshots within the caller's working directory.
    with tempfile.TemporaryDirectory(prefix='actor-snapshot-', dir=Path.cwd()) as temp:
        root = Path(temp)
        while queue and len(saved) < maximum and len(seen) < maximum * 5:
            url = queue.popleft()
            if url in seen:
                continue
            seen.add(url)
            try:
                relative = snapshot_path(url)
                if relative in saved:
                    continue
                fetched = await asyncio.to_thread(fetcher.fetch, url)
                if fetched is None:
                    skipped.append({'url': url, 'reason': 'not fetched (robots, HTTP, size, or transport)'})
                    continue
                final_url, response = fetched
                final_url = normalized(final_url)
                relative = snapshot_path(final_url)
                if relative in saved:
                    continue
                if response.header('Content-Type').split(';')[0].strip().lower() not in ('text/html', 'application/xhtml+xml'):
                    skipped.append({'url': url, 'reason': 'not HTML'})
                    continue
                target = root / relative
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(response.text(), encoding='utf-8')
                saved[relative] = {'url': final_url, 'requested_url': url, 'status': response.status}
                parser = directory_audit.PageParser()
                parser.feed(response.text())
                parser.close()
                base = urljoin(final_url, parser.base) if parser.base else final_url
                for href in parser.links:
                    try:
                        link = normalized(urljoin(base, href))
                        snapshot_path(link)
                    except ValueError:
                        continue
                    if urlsplit(link).netloc == host and link not in seen and len(queue) < maximum * 5:
                        queue.append(link)
            except (ValueError, OSError) as exc:
                skipped.append({'url': url, 'reason': str(exc)})

        # Auxiliary resources do not count as pages and never incur page events.
        if saved:
            sitemap = await asyncio.to_thread(fetcher.fetch, origin + '/sitemap.xml')
            if sitemap:
                (root / 'sitemap.xml').write_text(sitemap[1].text(), encoding='utf-8')
        if origin in fetcher.robots_bodies:
            (root / 'robots.txt').write_bytes(fetcher.robots_bodies[origin])
        report = directory_audit.run(root)
        report['crawl'] = {
            'start_url': start, 'max_pages': maximum, 'attempted_pages': len(seen),
            'skipped': skipped,
            'scope': 'Partial static snapshot; missing local targets are not proof of deployed errors. '
                     'Query variants share one path (first saved wins); extensionless pages use path/index.html. '
                     'No JavaScript rendering.',
        }
        for page in report['pages']:
            source = saved[page['path'].lstrip('/')]
            item = {**source, **page, 'findings': [f for f in report['findings']
                                                if f['where'] == page['path']]}
            await storage.push_data(item)
            await storage.charge('page-audited')
        await storage.set_value('AUDIT', report, 'application/json')
        markdown = directory_audit.markdown(report)
        markdown += '\n\n## Crawl scope\n\n' + report['crawl']['scope'] + '\n'
        await storage.set_value('AUDIT-MARKDOWN', markdown, 'text/markdown')
        return report
