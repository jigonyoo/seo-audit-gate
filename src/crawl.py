"""Read a local static site. No network - the fixture is the site."""
import os, re
from dataclasses import dataclass, field

TAG = lambda n: re.compile(rf"<{n}\b[^>]*>(.*?)</{n}>", re.S | re.I)
TITLE, H1, H2, H3 = TAG("title"), TAG("h1"), TAG("h2"), TAG("h3")
META = re.compile(r"<meta\s+name=[\"'](\w+)[\"']\s+content=[\"'](.*?)[\"']", re.S | re.I)
CANON = re.compile(r"<link\s+rel=[\"']canonical[\"']\s+href=[\"'](.*?)[\"']", re.I)
HREF = re.compile(r"<a\b[^>]*href=[\"'](.*?)[\"']", re.I)
IMG = re.compile(r"<img\b([^>]*)>", re.I)
ALT = re.compile(r"\balt=[\"'](.*?)[\"']", re.I)

@dataclass
class Page:
    path: str            # site path, e.g. "/services"
    title: str = ""
    description: str | None = None
    robots: str = ""
    canonical: str = ""
    h1: list = field(default_factory=list)
    heads: list = field(default_factory=list)   # (level, text) in document order
    links: list = field(default_factory=list)
    imgs_without_alt: int = 0
    imgs: int = 0

def _one(rx, s):
    m = rx.search(s)
    return m.group(1).strip() if m else ""

def load(site_dir: str):
    pages = {}
    for name in sorted(os.listdir(site_dir)):
        if not name.endswith(".html"):
            continue
        with open(os.path.join(site_dir, name), encoding="utf-8") as fh:
            raw = fh.read()
        path = "/" if name == "index.html" else "/" + name[:-5]
        metas = {k.lower(): v.strip() for k, v in META.findall(raw)}
        heads = []
        for lvl, rx in ((1, H1), (2, H2), (3, H3)):
            for t in rx.findall(raw):
                heads.append((lvl, raw.find(t), re.sub(r"\s+", " ", t).strip()))
        heads.sort(key=lambda x: x[1])
        imgs = IMG.findall(raw)
        pages[path] = Page(
            path=path,
            title=re.sub(r"\s+", " ", _one(TITLE, raw)),
            description=metas.get("description"),
            robots=metas.get("robots", ""),
            canonical=_one(CANON, raw),
            h1=[re.sub(r"\s+", " ", t).strip() for t in H1.findall(raw)],
            heads=[(l, t) for l, _, t in heads],
            links=[h for h in HREF.findall(raw)],
            imgs=len(imgs),
            imgs_without_alt=sum(1 for a in imgs if not ALT.search(a)),
        )
    return pages

def load_sitemap(path: str):
    if not os.path.exists(path):
        return []
    with open(path, encoding="utf-8") as fh:
        raw = fh.read()
    locs = re.findall(r"<loc>(.*?)</loc>", raw)
    out = []
    for u in locs:
        p = re.sub(r"^https?://[^/]+", "", u.strip())
        out.append(p if p else "/")
    return out
