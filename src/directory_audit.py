"""Audit local static files with no network access."""
from collections import Counter
from dataclasses import asdict
from html.parser import HTMLParser
import json
from pathlib import Path
from urllib.parse import unquote, urljoin, urlsplit
import xml.etree.ElementTree as ET

from audit import Finding, CONFIRMED, INFERRED, UNVERIFIABLE, TITLE_MAX


class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title = []
        self.h1_count = 0
        self.lang = ''
        self.meta = {}
        self.canonical = ''
        self.hreflang = []
        self.links = []
        self.base = ''
        self.json_ld = []
        self._title = False
        self._script = None

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == 'html':
            self.lang = a.get('lang') or ''
        elif tag == 'title':
            self._title = True
        elif tag == 'h1':
            self.h1_count += 1
        elif tag == 'meta':
            key = (a.get('property') or a.get('name') or '').lower()
            self.meta[key] = a.get('content') or ''
        elif tag == 'link':
            rel = (a.get('rel') or '').lower().split()
            if 'canonical' in rel:
                self.canonical = a.get('href') or ''
            if 'alternate' in rel and 'hreflang' in a:
                self.hreflang.append({'lang': a['hreflang'] or '', 'href': a.get('href') or ''})
        elif tag in ('a', 'area') and 'href' in a:
            self.links.append(a['href'] or '')
        elif tag == 'base' and not self.base:
            self.base = a.get('href') or ''
        elif tag == 'script' and (a.get('type') or '').lower().strip() == 'application/ld+json':
            self._script = []

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        self.handle_endtag(tag)

    def handle_endtag(self, tag):
        if tag == 'title':
            self._title = False
        if tag == 'script' and self._script is not None:
            self.json_ld.append(''.join(self._script))
            self._script = None

    def handle_data(self, data):
        if self._title:
            self.title.append(data)
        if self._script is not None:
            self._script.append(data)


def local_file(root, path):
    """Contain traversal and symlinks before opening a target."""
    target = (root / unquote(path).lstrip('/')).resolve()
    if not target.is_relative_to(root):
        return None
    if target.is_dir():
        target = (target / 'index.html').resolve()
    if not target.is_relative_to(root):
        return None
    return target if target.is_file() else None


def schema_types(value):
    types = []
    if isinstance(value, dict):
        t = value.get('@type')
        if isinstance(t, str) and t.strip():
            types.append(t)
        elif isinstance(t, list):
            types.extend(x for x in t if isinstance(x, str) and x.strip())
        for child in value.values():
            types.extend(schema_types(child))
    elif isinstance(value, list):
        for child in value:
            types.extend(schema_types(child))
    return sorted(set(types))


def run(site_dir):
    root = Path(site_dir).resolve()
    if not root.is_dir():
        raise ValueError(f'not a directory: {site_dir}')
    findings, pages = [], []

    def add(check, where, grade, what, evidence, fix):
        findings.append(Finding(check, where, grade, what, evidence, fix))

    def missing(check, where, what):
        add(check, where, CONFIRMED, what, 'absent or empty in local file', 'add ' + what)

    files = sorted(p for p in root.rglob('*') if p.suffix.lower() in ('.html', '.htm')
                   and p.is_file() and p.resolve().is_relative_to(root))
    for file in files:
        where = '/' + file.relative_to(root).as_posix()
        parser = PageParser()
        parser.feed(file.read_text(encoding='utf-8'))
        parser.close()
        title = ' '.join(''.join(parser.title).split())
        if not title:
            missing('title.missing', where, 'title')
        elif len(title) > TITLE_MAX:
            add('title.too_long', where, CONFIRMED, 'title exceeds 60 characters', title, 'shorten the title')
        for key in ('description', 'og:title', 'og:description', 'og:image', 'og:url', 'twitter:card'):
            if not parser.meta.get(key, '').strip():
                missing(key + ('.empty' if key in parser.meta else '.missing'), where, key)
        if not parser.canonical.strip():
            missing('canonical.missing', where, 'canonical link')
        if parser.h1_count != 1:
            add('h1.multiple' if parser.h1_count > 1 else 'h1.missing', where, CONFIRMED,
                f'{parser.h1_count} H1 elements', str(parser.h1_count), 'use one H1 naming the page')
        if not parser.lang.strip():
            missing('html.lang.missing', where, 'html lang')
        for alternate in parser.hreflang:
            if not alternate['lang'].strip() or not alternate['href'].strip():
                add('hreflang.invalid', where, CONFIRMED, 'empty hreflang or href',
                    str(alternate), 'supply a language and alternate URL')
        types = []
        if not parser.json_ld:
            missing('jsonld.missing', where, 'JSON-LD script')
        for raw in parser.json_ld:
            try:
                value = json.loads(raw)
            except ValueError as exc:
                add('jsonld.invalid', where, CONFIRMED, 'invalid JSON-LD JSON', str(exc), 'correct the JSON')
                continue
            found = schema_types(value)
            types.extend(found)
            if not found:
                missing('jsonld.type.missing', where, 'JSON-LD @type')
        declared = urlsplit(parser.canonical)
        origin = (f'{declared.scheme}://{declared.netloc}'
                  if declared.scheme in ('http', 'https') and declared.netloc else 'https://local.invalid')
        base = urljoin(origin + where, parser.base) if parser.base else origin + where
        for href in parser.links + [a['href'] for a in parser.hreflang if a['href']]:
            url = urlsplit(urljoin(base, href))
            if url.scheme not in ('http', 'https') or url.netloc != urlsplit(origin).netloc:
                continue
            if local_file(root, url.path) is None:
                add('links.broken', where, CONFIRMED, 'internal link has no local file',
                    f'{href} -> {url.path}', 'point the link at a file inside the site folder')
        pages.append({'path': where, 'title': title, 'meta': parser.meta,
                      'canonical': parser.canonical, 'h1_count': parser.h1_count,
                      'lang': parser.lang, 'hreflang': parser.hreflang,
                      'jsonld_types': sorted(set(types))})

    for name in ('robots.txt', 'sitemap.xml', '404.html'):
        if local_file(root, '/' + name) is None:
            missing(name + '.missing', 'site', name)
    sitemap = local_file(root, '/sitemap.xml')
    if sitemap:
        try:
            tree = ET.fromstring(sitemap.read_text(encoding='utf-8'))
            locations = [e.text.strip() for e in tree.iter()
                         if e.tag.rsplit('}', 1)[-1] == 'loc' and e.text]
            covered = {local_file(root, urlsplit(u).path) for u in locations}
            for file in files:
                if file.resolve() not in covered:
                    add('sitemap.page_missing', '/' + file.relative_to(root).as_posix(), INFERRED,
                        'HTML page is not listed in sitemap', 'no sitemap URL resolves to this file',
                        'add the page URL to sitemap.xml')
        except ET.ParseError as exc:
            add('sitemap.invalid', 'site', CONFIRMED, 'invalid sitemap XML', str(exc), 'correct sitemap.xml')
    for check, what in [('ranking.effect', 'whether any of this moves a ranking'),
                        ('index.status', 'whether these pages are actually indexed')]:
        add(check, 'site', UNVERIFIABLE, what, 'local files cannot establish this',
            'measure using search performance data')
    return {'page_count': len(pages), 'finding_count': len(findings),
            'counts_by_type': dict(sorted(Counter(f.check for f in findings).items())),
            'counts_by_grade': dict(sorted(Counter(f.grade for f in findings).items())),
            'pages': pages, 'findings': [asdict(f) for f in findings]}


def markdown(report):
    def escape(value):
        return str(value).replace('&', '&amp;').replace('<', '&lt;').replace('>', '&gt;').replace('|', '&#124;').replace('\n', ' ')
    lines = ['# Static directory SEO audit', '',
             f"Pages: {report['page_count']}. Findings: {report['finding_count']}.", '',
             '| Issue type | Count |', '|---|---:|']
    lines += [f'| {escape(k)} | {v} |' for k, v in report['counts_by_type'].items()]
    lines += ['', '## Page inventory', '']
    for page in report['pages']:
        lines += [f"- {escape(page['path'])}: {escape(json.dumps(page, ensure_ascii=False))}"]
    lines += ['', '## Findings', '']
    for f in report['findings']:
        lines += [f"### {f['grade']} · {escape(f['check'])} · {escape(f['where'])}",
                  f"{escape(f['what'])}", '', f"Evidence: {escape(f['evidence'])}", '',
                  f"Fix: {escape(f['fix'])}", '']
    return '\n'.join(lines)
