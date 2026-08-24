import sys, os
sys.path.insert(0, os.path.dirname(__file__))
import crawl, audit

def main():
    site = os.environ.get("SITE", "fixtures/site")
    smap = os.environ.get("SITEMAP", "fixtures/sitemap.xml")
    out = os.environ.get("OUT", "out")
    os.makedirs(out, exist_ok=True)
    pages = crawl.load(site)
    sitemap = crawl.load_sitemap(smap)
    findings = audit.run(pages, sitemap)

    by = {}
    for f in findings:
        by.setdefault(f.grade, []).append(f)
    print(f"crawled {len(pages)} pages, sitemap lists {len(sitemap)}\n")
    for g in (audit.CONFIRMED, audit.INFERRED, audit.UNVERIFIABLE):
        print(f"{g:<14} {len(by.get(g, []))}")
    print()
    lines = ["# Technical SEO audit", "",
             f"{len(pages)} pages crawled. {len(findings)} findings.", "",
             "Every finding carries a grade. **CONFIRMED** was read off the page. "
             "**INFERRED** follows from a rule over the crawl. **UNVERIFIABLE** is named "
             "because a crawl cannot establish it and it should not be printed as if it could.", ""]
    for g in (audit.CONFIRMED, audit.INFERRED, audit.UNVERIFIABLE):
        fs = by.get(g, [])
        lines += [f"## {g} ({len(fs)})", ""]
        for f in fs:
            print(f"  {g[:4]:<5} {f.check:<28} {f.where:<22} {f.what[:58]}")
            lines += [f"### `{f.check}` — {f.where}",
                      f"- **What:** {f.what}",
                      f"- **Evidence:** `{f.evidence}`",
                      f"- **Fix:** {f.fix}", ""]
    with open(f"{out}/audit.md", "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines))
    print(f"\nwrote {out}/audit.md")

if __name__ == "__main__":
    main()
