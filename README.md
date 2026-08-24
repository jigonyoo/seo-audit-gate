# seo-audit-gate

A technical SEO audit where **every finding says how it was established** — and the things a crawl
cannot establish are printed as exactly that, instead of being dressed up as advice.

Runs offline against a local site. Python standard library only, no network, no API key.

```
make demo    # audits the fixture site
make test    # 14 tests
```

## The measured run

5 pages crawled, 5 sitemap entries, **15 findings**:

| grade | count | means |
|---|---:|---|
| `CONFIRMED` | 9 | read directly off the page |
| `INFERRED` | 4 | follows from a rule over the whole crawl |
| `UNVERIFIABLE` | 2 | a crawl cannot know this, and says so |

**CONFIRMED** — empty description on `/`; 80-character titles on `/services` and `/about`; the same
title on two pages; two `h1` on one page; a heading outline that jumps h1 → h3; an image with no
alt; a canonical on `/noindex` pointing at a different page.

**INFERRED** — `/orphan` has no internal link and is not in the sitemap; the sitemap lists `/gone`,
which does not exist; `/noindex` is `noindex` **and** listed in the sitemap, so the sitemap asks for
indexing while the tag refuses; `/services` is linked both with and without a trailing slash.

**UNVERIFIABLE** — whether any of this moves a ranking, and whether these pages are indexed at all.

## Why the third grade is the point

Most audit output is a list of defects followed by an implied promise. The promise is the part that
cannot be supported: a crawler observes your page, not Google's index and not your competitors. So
this tool names that boundary as a finding rather than leaving it as an impression:

```
UNVERIFIABLE  ranking.effect   whether any of this moves a ranking
              evidence: a crawl observes the page, not the index or the competition
              fix: measure impressions and click-through before and after;
                   do not promise a position
```

A test asserts that **no finding anywhere in the output contains "guarantee", "will rank",
"first page", "position 1" or "#1"**. That is a machine check on our own sales language, not a
policy in a document.

## What it does not do

- No network. It reads a local directory; a real run needs a fetch layer with rate limits,
  `robots.txt` handling, and redirect following. None of that is here.
- No JavaScript rendering. A client-rendered site would look empty to it.
- No Search Console, no log files, no rank data — which is exactly why two findings are
  `UNVERIFIABLE` rather than absent.
- Heading and title rules are conventions, not laws. 60 characters is where truncation usually
  starts; it is not a penalty threshold, and the tool does not pretend otherwise.
- The fixture is synthetic and small. Numbers above describe this fixture, not your site.

## Layout

```
fixtures/site/    five pages, seven planted defects
fixtures/sitemap.xml
src/crawl.py      parse pages and the sitemap
src/audit.py      the checks, each returning a graded finding
src/cli.py        table to stdout, full audit to out/audit.md
tests/            14 tests: 7 assert each planted defect is found,
                  3 assert clean pages are left alone,
                  4 assert the tool refuses to claim what it cannot see
```
