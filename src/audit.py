"""Findings carry a verdict grade, because 'this will improve your rankings' is not
something a crawl can establish and should not be printed as if it were."""
from dataclasses import dataclass

CONFIRMED = "CONFIRMED"        # read directly off the page
INFERRED = "INFERRED"          # follows from a rule over what was read
UNVERIFIABLE = "UNVERIFIABLE"  # a crawl cannot know this

@dataclass
class Finding:
    check: str
    where: str
    grade: str
    what: str
    evidence: str
    fix: str

TITLE_MAX = 60

def run(pages, sitemap):
    F = []
    add = lambda *a: F.append(Finding(*a))
    paths = set(pages)

    # --- CONFIRMED: things visible on the page itself -----------------------
    titles = {}
    for p in sorted(pages):
        pg = pages[p]
        if pg.description is not None and not pg.description.strip():
            add("description.empty", p, CONFIRMED,
                "description meta tag is present but empty",
                '<meta name="description" content="">',
                "write one, or remove the tag so the absence is honest")
        if pg.description is None:
            add("description.missing", p, CONFIRMED,
                "no description meta tag", "tag absent",
                "add one; Google may still write its own, which is fine")
        if len(pg.title) > TITLE_MAX:
            add("title.too_long", p, CONFIRMED,
                f"title is {len(pg.title)} characters, over the {TITLE_MAX} that usually survive truncation",
                pg.title, "front-load the two words a searcher would type")
        titles.setdefault(pg.title, []).append(p)
        if len(pg.h1) > 1:
            add("h1.multiple", p, CONFIRMED,
                f"{len(pg.h1)} h1 elements", " | ".join(pg.h1),
                "one h1 that names the page; demote the rest")
        levels = [l for l, _ in pg.heads]
        for a, b in zip(levels, levels[1:]):
            if b - a > 1:
                add("headings.skipped_level", p, CONFIRMED,
                    f"heading level jumps h{a} to h{b}",
                    " > ".join(f"h{l}:{t[:24]}" for l, t in pg.heads),
                    "do not skip a level; it is the page outline, not styling")
                break
        if pg.imgs_without_alt:
            add("img.no_alt", p, CONFIRMED,
                f"{pg.imgs_without_alt} of {pg.imgs} images have no alt attribute",
                "img tag without alt", "describe the image, or alt=\"\" if decorative")
        if pg.canonical and pg.canonical.rstrip("/").split("/")[-1] not in (p.strip("/"), "") \
           and p != "/":
            add("canonical.points_elsewhere", p, CONFIRMED,
                "canonical points at a different page",
                f"{p} -> {pg.canonical}",
                "intentional only if this page is a duplicate; otherwise it removes the page from search")

    for t, ps in sorted(titles.items()):
        if len(ps) > 1 and t:
            add("title.duplicate", ", ".join(ps), CONFIRMED,
                f"{len(ps)} pages share one title", t,
                "titles are how a result is chosen; two identical ones compete with each other")

    # --- INFERRED: follows from the crawl, stated as inference ---------------
    linked = set()
    for p in pages:
        for href in pages[p].links:
            if href.startswith("http"):
                continue
            linked.add("/" + href.strip("/") if href.strip("/") else "/")
    for p in sorted(paths):
        if p == "/":
            continue
        if p not in linked and p not in sitemap:
            add("page.orphan", p, INFERRED,
                "no internal link and not in the sitemap",
                f"linked-from: none; sitemap: absent",
                "link it from somewhere real, or delete it")
    for u in sitemap:
        if u not in paths:
            add("sitemap.dead_entry", u, INFERRED,
                "sitemap lists a URL that does not exist in the crawl",
                f"sitemap entry {u}",
                "remove it; a sitemap full of 404s is a crawl-budget leak")
    for p in sorted(paths):
        if "noindex" in pages[p].robots and p in sitemap:
            add("sitemap.noindex_conflict", p, INFERRED,
                "page is noindex but is listed in the sitemap",
                f'robots="{pages[p].robots}" and present in sitemap',
                "the sitemap asks for indexing and the tag refuses; pick one")
    slashy = set()
    for p in pages:
        for href in pages[p].links:
            if href.startswith("http"):
                continue
            bare = href.rstrip("/")
            if bare and href != bare and bare in {"/" + x.strip("/") for x in linked}:
                slashy.add(bare)
    for b in sorted(slashy):
        add("links.trailing_slash_mixed", b, INFERRED,
            "the same target is linked both with and without a trailing slash",
            f"{b} and {b}/",
            "pick one form and redirect the other")

    # --- UNVERIFIABLE: named on purpose -------------------------------------
    add("ranking.effect", "site", UNVERIFIABLE,
        "whether any of this moves a ranking",
        "a crawl observes the page, not the index or the competition",
        "measure impressions and click-through before and after; do not promise a position")
    add("index.status", "site", UNVERIFIABLE,
        "whether these pages are actually indexed",
        "requires Search Console, which a crawl cannot read",
        "check Coverage in Search Console; the tags here only express an intent")
    return F
