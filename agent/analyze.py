"""Turn today's snapshot (and yesterday's) into findings.

Two kinds of check:
- state checks: what is wrong today (an error page, noindex in the sitemap, slow LCP...);
- change checks: what moved since yesterday (robots.txt edited, pages dropped, titles rewritten...).
Each finding has a stable id, so it can be marked new, ongoing or resolved across days.
"""
from collections import defaultdict
from statistics import median

from . import config as C

SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def F(fid, severity, kind, title, detail, urls=(), data=None):
    urls = list(urls)
    return {"id": fid, "severity": severity, "kind": kind, "title": title, "detail": detail,
            "count": len(urls), "urls": urls[:10], "data": data or {}}


def state_checks(s):
    out = []
    pages = s["pages"]

    if s["robots"]["status"] != 200:
        out.append(F("robots_unreachable", "critical", "crawlability", "robots.txt is not reachable",
                     f"robots.txt returned HTTP {s['robots']['status']}."))
    blocked = [b for b, ok in s["robots"]["crawler_access"].items() if not ok]
    if blocked:
        sev = "critical" if {"Googlebot", "Bingbot"} & set(blocked) else "high"
        out.append(F("crawlers_blocked", sev, "crawlability", "robots.txt blocks search or AI crawlers",
                     f"Blocked at the site root: {', '.join(blocked)}. Blocked AI crawlers cannot read pages to cite them.",
                     data={"blocked": blocked}))

    bad_sitemaps = [n for n, c in s["sitemaps"]["children"].items() if c["status"] != 200]
    if bad_sitemaps:
        out.append(F("sitemap_unreachable", "high", "indexing", "A sitemap file is not reachable",
                     f"Failing sitemap files: {', '.join(bad_sitemaps)}."))

    def group(fid, sev, kind, title, detail, pred):
        urls = [u for u, p in pages.items() if pred(p)]
        if urls:
            out.append(F(fid, sev, kind, title, detail.format(n=len(urls)), urls))

    group("status_5xx", "critical", "availability", "Sitemap pages return a server error",
          "{n} page(s) in the sitemap return HTTP 5xx or do not answer.", lambda p: (p.get("status") or 0) >= 500 or p.get("status") == 0)
    group("status_4xx", "critical", "availability", "Sitemap pages return a client error",
          "{n} page(s) in the sitemap return HTTP 4xx (likely 404).", lambda p: 400 <= (p.get("status") or 0) < 500)
    group("sitemap_redirects", "medium", "indexing", "Sitemap lists URLs that redirect",
          "{n} sitemap URL(s) redirect; a sitemap should list final URLs.", lambda p: p.get("redirects"))
    group("noindex_in_sitemap", "critical", "indexing", "Pages in the sitemap are set to noindex",
          "{n} page(s) are in the sitemap but tell search engines not to index them.",
          lambda p: "noindex" in (p.get("robots_meta") or "") or "noindex" in (p.get("x_robots") or "").lower())
    canon =[u for u, p in pages.items() if p.get("canonical") and p["canonical"].rstrip("/") != u.rstrip("/")]
    if canon:
        out.append(F("canonical_elsewhere", "medium", "indexing", "Sitemap pages canonicalize to another URL",
                     f"{len(canon)} sitemap page(s) name a different URL as canonical, so they will not rank themselves.",
                     canon, {"examples": {u: pages[u]["canonical"] for u in canon[:5]}}))
    group("missing_canonical", "low", "indexing", "Pages without a canonical tag",
          "{n} page(s) have no canonical tag.", lambda p: p.get("status") == 200 and p.get("title") is not None and not p.get("canonical"))

    group("missing_title", "high", "on-page", "Pages without a title",
          "{n} page(s) have no <title>.", lambda p: "h1_count" in p and not p.get("title"))  # HTML pages only
    group("long_title", "low", "on-page", "Titles likely cut off in results",
          f"{{n}} title(s) are longer than {C.TITLE_MAX} characters.", lambda p: len(p.get("title") or "") > C.TITLE_MAX)
    group("missing_meta", "medium", "on-page", "Pages without a meta description",
          "{n} page(s) have no meta description.", lambda p: p.get("status") == 200 and p.get("title") and not p.get("meta_description"))
    group("long_meta", "low", "on-page", "Meta descriptions likely cut off",
          f"{{n}} meta description(s) are longer than {C.META_MAX} characters.", lambda p: len(p.get("meta_description") or "") > C.META_MAX)
    group("h1_missing", "medium", "on-page", "Pages without an H1",
          "{n} page(s) have no H1 heading.", lambda p: p.get("status") == 200 and p.get("title") and p.get("h1_count") == 0)
    group("h1_multiple", "low", "on-page", "Pages with more than one H1",
          "{n} page(s) have several H1 headings.", lambda p: (p.get("h1_count") or 0) > 1)
    group("thin_content", "low", "content", "Thin pages",
          f"{{n}} page(s) have fewer than {C.THIN_WORDS} words of text.",
          lambda p: p.get("status") == 200 and p.get("title") and (p.get("words") or 0) < C.THIN_WORDS)
    group("no_schema", "low", "on-page", "Pages without structured data",
          "{n} page(s) carry no JSON-LD structured data.", lambda p: p.get("status") == 200 and p.get("title") and not p.get("schema_types"))
    group("slow_response", "medium", "performance", "Pages slow even on a repeat request",
          f"{{n}} page(s) took longer than {C.SLOW_RESPONSE_MS} ms to return their HTML twice in a row, so it is not just a cold cache.",
          lambda p: bool(p.get("ms_retry")) and min(p["ms"], p["ms_retry"]) > C.SLOW_RESPONSE_MS)

    for kind, key in (("title", "duplicate_title"), ("meta_description", "duplicate_meta")):
        seen = defaultdict(list)
        for u, p in pages.items():
            if p.get(kind):
                seen[p[kind].strip().lower()].append(u)
        dups = [u for us in seen.values() if len(us) > 1 for u in us]
        if dups:
            label = "titles" if kind == "title" else "meta descriptions"
            out.append(F(key, "medium", "on-page", f"Duplicate {label}",
                         f"{len(dups)} pages share a {kind.replace('_', ' ')} with another page.", dups))

    broken = {u: l for u, l in s["links"]["checked_outside_sitemap"].items() if l["status"] >= 400 or l["status"] == 0}
    if broken:
        out.append(F("broken_internal_links", "high", "links", "Broken internal links",
                     f"{len(broken)} internal link(s) point to URLs that return an error, so visitors and crawlers hit "
                     "dead ends. Each sits on a live page (linked_from): fix the link there, or redirect the dead URL.",
                     list(broken), {"broken_links": [{"dead_url": u, "status": l["status"], "linked_from": l["found_on"]}
                                                     for u, l in list(broken.items())[:10]]}))

    psi_down = {u: p["error"] for u, p in s["psi"].items() if "error" in p}
    if psi_down:
        reasons = ", ".join(sorted(set(psi_down.values())))
        if all(s["psi"][u].get("setup_problem") for u in psi_down):
            out.append(F("psi_unavailable", "info", "agent", "PageSpeed data missing today (agent setup)",
                         f"The PageSpeed Insights API refused the agent's own requests ({reasons}). This is the "
                         "monitoring setup (API key or quota), not the website; speed checks were skipped today.", list(psi_down)))
        else:
            out.append(F("psi_failed", "medium", "performance", "PageSpeed could not test some pages",
                         f"PageSpeed Insights could not test {len(psi_down)} page(s) ({reasons}); Google may be unable to load them.",
                         list(psi_down)))
    # Real users across the whole site (Chrome UX Report, via PageSpeed): judged once, not per page.
    site = next((p["origin_field"] for p in s["psi"].values() if p.get("origin_field")), None)
    if site:
        problems, sev = rate_field(site)
        if problems:
            out.append(F("cwv_site", sev, "performance", "Site-wide Core Web Vitals need work",
                         "Real users across the whole site: " + "; ".join(problems) + ".", data=site))
    for url, p in s["psi"].items():
        if "error" in p:
            continue
        problems, sev = [], None
        if p["score"] < C.PSI_SCORE_POOR:
            problems.append(f"lab performance score {p['score']}/100")
            sev = "medium"
        own = p.get("field")
        if own and site and all(own.get(k) == site.get(k) for k in ("lcp_ms", "inp_ms", "cls")):
            own = None  # the site's numbers standing in for the page's (older snapshots lack the flag)
        if own:  # this page has its own real-user data
            more, fsev = rate_field(own)
            problems += more
            sev = min([x for x in (sev, fsev) if x], key=SEVERITY.get, default=None)
        elif p["lcp_ms"] > C.LCP_POOR_MS:
            problems.append(f"lab LCP {p['lcp_ms']} ms (no real-user data for this page)")
            sev = sev or "medium"
        if problems:
            out.append(F(f"cwv|{url}", sev, "performance", "Page speed needs work",
                         "; ".join(problems) + ".", [url], p))
    return out


def rating(value, good, poor):
    if value is None:
        return None
    return "good" if value <= good else "poor" if value > poor else "needs improvement"


def rate_field(fld):
    """Google's Core Web Vitals thresholds, applied to 75th-percentile real-user values."""
    problems, sev = [], None
    for name, key, good, poor, unit in (("LCP", "lcp_ms", C.LCP_GOOD_MS, C.LCP_POOR_MS, " ms"),
                                        ("INP", "inp_ms", C.INP_GOOD_MS, C.INP_POOR_MS, " ms"),
                                        ("CLS", "cls", C.CLS_GOOD, C.CLS_POOR, "")):
        r = rating(fld.get(key), good, poor)
        if r in ("needs improvement", "poor"):
            verdict = "is poor" if r == "poor" else "needs improvement"
            problems.append(f"{name} {fld[key]}{unit} {verdict} (good is {good}{unit} or less)")
            level = "high" if r == "poor" else "medium"
            sev = level if sev is None or SEVERITY[level] < SEVERITY[sev] else sev
    return problems, sev


def change_checks(s, prev):
    if not prev:
        return []
    out = []
    if s["robots"]["sha"] != prev["robots"]["sha"]:
        out.append(F(f"robots_changed|{s['date']}", "high", "crawlability", "robots.txt changed",
                     "robots.txt is different from yesterday. Check that no important section or crawler is blocked.",
                     data={"before": prev["robots"]["text"], "after": s["robots"]["text"]}))
    newly_blocked = [b for b, ok in s["robots"]["crawler_access"].items()
                     if not ok and prev["robots"]["crawler_access"].get(b, True)]
    if newly_blocked:
        out.append(F(f"newly_blocked|{s['date']}", "critical", "crawlability", "A crawler was newly blocked",
                     f"Since yesterday robots.txt blocks: {', '.join(newly_blocked)}."))

    now, before = s["pages"], prev["pages"]
    removed = [u for u in before if u not in now]
    added = [u for u in now if u not in before]
    if removed:
        out.append(F(f"pages_removed|{s['date']}", "medium", "indexing", "Pages dropped from the sitemap",
                     f"{len(removed)} URL(s) left the sitemap since yesterday. Check they were retired on purpose and redirect.", removed))
    if added:
        out.append(F(f"pages_added|{s['date']}", "info", "indexing", "New pages in the sitemap",
                     f"{len(added)} new URL(s) appeared in the sitemap.", added))

    def changed(field, fid, sev, title, verb):
        urls = [u for u in now if u in before and now[u].get(field) != before[u].get(field)
                and before[u].get("status") == 200 and now[u].get("status") == 200]
        if urls:
            out.append(F(f"{fid}|{s['date']}", sev, "changes", title, f"{len(urls)} page(s) {verb} since yesterday.", urls,
                         {"examples": {u: {"before": before[u].get(field), "after": now[u].get(field)} for u in urls[:5]}}))

    broke = [u for u in now if u in before and before[u].get("status") == 200 and now[u].get("status") != 200]
    if broke:
        out.append(F(f"newly_broken|{s['date']}", "critical", "availability", "Pages broke since yesterday",
                     f"{len(broke)} page(s) worked yesterday and fail today.", broke,
                     {"statuses": {u: now[u].get("status") for u in broke[:10]}}))
    newly_noindex = [u for u in now if u in before and "noindex" in (now[u].get("robots_meta") or "")
                     and "noindex" not in (before[u].get("robots_meta") or "")]
    if newly_noindex:
        out.append(F(f"newly_noindex|{s['date']}", "critical", "indexing", "Pages newly set to noindex",
                     f"{len(newly_noindex)} page(s) became noindex since yesterday.", newly_noindex))
    changed("title", "titles_changed", "low", "Titles rewritten", "have a new title")
    changed("meta_description", "meta_changed", "info", "Meta descriptions rewritten", "have a new meta description")
    changed("canonical", "canonical_changed", "medium", "Canonical tags changed", "point their canonical somewhere new")
    updated = [u for u in now if u in before and now[u].get("lastmod") and now[u].get("lastmod") != before[u].get("lastmod")]
    if updated:
        out.append(F(f"content_updated|{s['date']}", "info", "changes", "Pages updated",
                     f"{len(updated)} page(s) have a new last-modified date in the sitemap.", updated))

    for url, p in s["psi"].items():
        q = prev.get("psi", {}).get(url, {})
        if "score" in p and "score" in q and q["score"] - p["score"] >= C.PSI_DROP:
            out.append(F(f"psi_drop|{url}|{s['date']}", "medium", "performance", "Performance score dropped",
                         f"Mobile performance score fell from {q['score']} to {p['score']}; lab LCP {q['lcp_ms']} → {p['lcp_ms']} ms. "
                         "Lab scores vary by a few points between runs, so a drop this size is worth a look.", [url]))

    return out


def trend_checks(s, history):
    """Response time against the last days' medians, never a single day: one sample is too noisy
    (the site caches pages for 10 minutes, so a recent visit makes the next one look fast)."""
    past = [m for m in history if m]
    ms_now = median([p["ms"] for p in s["pages"].values() if p.get("ms")] or [0])
    if len(past) >= 3:
        base = median(past)
        if ms_now > 2 * base and ms_now - base > 300:
            return [F(f"server_slower|{s['date']}", "medium", "performance", "The server is slower than usual",
                      f"Median HTML response today is {ms_now} ms, against a median of {base} ms over the previous {len(past)} days.")]
    return []


def summarize(s):
    pages = s["pages"]
    ms = [p["ms"] for p in pages.values() if p.get("ms")]
    return {
        "pages_in_sitemap": len(pages),
        "pages_ok": sum(1 for p in pages.values() if p.get("status") == 200),
        "sitemaps": {n: c["count"] for n, c in s["sitemaps"]["children"].items()},
        "median_response_ms": median(ms) if ms else None,
        "internal_links_found": s["links"]["internal_links_found"],
        "crawler_access": s["robots"]["crawler_access"],
        "psi": {u: {k: v for k, v in p.items() if k != "origin_field"} for u, p in s["psi"].items()},
        "site_core_web_vitals": rated(next((p["origin_field"] for p in s["psi"].values() if p.get("origin_field")), None)),
    }


def rated(fld):
    """The field values with Google's label next to each, so nobody has to guess what is good."""
    if not fld:
        return None
    return dict(fld, lcp_rating=rating(fld.get("lcp_ms"), C.LCP_GOOD_MS, C.LCP_POOR_MS),
                inp_rating=rating(fld.get("inp_ms"), C.INP_GOOD_MS, C.INP_POOR_MS),
                cls_rating=rating(fld.get("cls"), C.CLS_GOOD, C.CLS_POOR))


def analyze(s, prev, prev_findings, history=()):
    findings = state_checks(s) + change_checks(s, prev) + trend_checks(s, history)
    known = {f["id"] for f in (prev_findings or [])}
    for f in findings:
        f["status"] = "ongoing" if f["id"] in known else "new"
    current = {f["id"] for f in findings}
    resolved = [dict(f, status="resolved") for f in (prev_findings or [])
                if f["id"] not in current and "|20" not in f["id"]]  # dated change findings expire on their own
    findings.sort(key=lambda f: (SEVERITY[f["severity"]], f["status"] != "new", -f["count"]))
    return {"date": s["date"], "summary": summarize(s), "findings": findings, "resolved": resolved,
            "first_run": prev is None}
