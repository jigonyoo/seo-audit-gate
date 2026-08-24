# Technical SEO audit

5 pages crawled. 15 findings.

Every finding carries a grade. **CONFIRMED** was read off the page. **INFERRED** follows from a rule over the crawl. **UNVERIFIABLE** is named because a crawl cannot establish it and it should not be printed as if it could.

## CONFIRMED (9)

### `description.empty` — /
- **What:** description meta tag is present but empty
- **Evidence:** `<meta name="description" content="">`
- **Fix:** write one, or remove the tag so the absence is honest

### `title.too_long` — /about
- **What:** title is 80 characters, over the 60 that usually survive truncation
- **Evidence:** `Services | Acme Plumbing | Emergency Plumber Dublin | 24/7 Callout | Best Prices`
- **Fix:** front-load the two words a searcher would type

### `description.missing` — /noindex
- **What:** no description meta tag
- **Evidence:** `tag absent`
- **Fix:** add one; Google may still write its own, which is fine

### `canonical.points_elsewhere` — /noindex
- **What:** canonical points at a different page
- **Evidence:** `/noindex -> https://example.com/services`
- **Fix:** intentional only if this page is a duplicate; otherwise it removes the page from search

### `title.too_long` — /services
- **What:** title is 80 characters, over the 60 that usually survive truncation
- **Evidence:** `Services | Acme Plumbing | Emergency Plumber Dublin | 24/7 Callout | Best Prices`
- **Fix:** front-load the two words a searcher would type

### `h1.multiple` — /services
- **What:** 2 h1 elements
- **Evidence:** `Services | Emergency callout`
- **Fix:** one h1 that names the page; demote the rest

### `headings.skipped_level` — /services
- **What:** heading level jumps h1 to h3
- **Evidence:** `h1:Services > h1:Emergency callout > h3:Drains`
- **Fix:** do not skip a level; it is the page outline, not styling

### `img.no_alt` — /services
- **What:** 1 of 1 images have no alt attribute
- **Evidence:** `img tag without alt`
- **Fix:** describe the image, or alt="" if decorative

### `title.duplicate` — /about, /services
- **What:** 2 pages share one title
- **Evidence:** `Services | Acme Plumbing | Emergency Plumber Dublin | 24/7 Callout | Best Prices`
- **Fix:** titles are how a result is chosen; two identical ones compete with each other

## INFERRED (4)

### `page.orphan` — /orphan
- **What:** no internal link and not in the sitemap
- **Evidence:** `linked-from: none; sitemap: absent`
- **Fix:** link it from somewhere real, or delete it

### `sitemap.dead_entry` — /gone
- **What:** sitemap lists a URL that does not exist in the crawl
- **Evidence:** `sitemap entry /gone`
- **Fix:** remove it; a sitemap full of 404s is a crawl-budget leak

### `sitemap.noindex_conflict` — /noindex
- **What:** page is noindex but is listed in the sitemap
- **Evidence:** `robots="noindex, nofollow" and present in sitemap`
- **Fix:** the sitemap asks for indexing and the tag refuses; pick one

### `links.trailing_slash_mixed` — /services
- **What:** the same target is linked both with and without a trailing slash
- **Evidence:** `/services and /services/`
- **Fix:** pick one form and redirect the other

## UNVERIFIABLE (2)

### `ranking.effect` — site
- **What:** whether any of this moves a ranking
- **Evidence:** `a crawl observes the page, not the index or the competition`
- **Fix:** measure impressions and click-through before and after; do not promise a position

### `index.status` — site
- **What:** whether these pages are actually indexed
- **Evidence:** `requires Search Console, which a crawl cannot read`
- **Fix:** check Coverage in Search Console; the tags here only express an intent
