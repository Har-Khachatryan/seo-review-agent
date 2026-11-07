"""Collect today's snapshot of the site: robots.txt, sitemaps, every sitemap page,
internal links, and PageSpeed Insights (lab + real-user Core Web Vitals) for key pages."""
import hashlib
import json
import os
import re
import time
import urllib.robotparser
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse, urldefrag

import requests

from . import config as C

session = requests.Session()
session.headers["User-Agent"] = C.USER_AGENT


def get(url, **kw):
    t0 = time.time()
    r = session.get(url, timeout=C.TIMEOUT, **kw)
    return r, int((time.time() - t0) * 1000)


# ---------------------------------------------------------------- robots + sitemaps

def collect_robots():
    r, _ = get(C.ROBOTS)
    text = r.text if r.ok else ""
    rp = urllib.robotparser.RobotFileParser()
    rp.parse(text.splitlines())
    access = {bot: rp.can_fetch(bot, C.SITE + "/") for bot in C.CRAWLERS}
    return {
        "status": r.status_code,
        "sha": hashlib.sha256(text.encode()).hexdigest()[:16],
        "text": text,
        "crawler_access": access,
        "sitemaps": re.findall(r"(?im)^sitemap:\s*(\S+)", text),
    }


def _locs(xml):
    items = []
    for block in re.findall(r"<(?:url|sitemap)>(.*?)</(?:url|sitemap)>", xml, re.S):
        loc = re.search(r"<loc>\s*(.*?)\s*</loc>", block, re.S)
        mod = re.search(r"<lastmod>\s*(.*?)\s*</lastmod>", block, re.S)
        if loc:
            items.append((loc.group(1).strip(), mod.group(1).strip() if mod else None))
    return items


def collect_sitemaps():
    r, _ = get(C.SITEMAP_INDEX)
    children, urls = {}, {}
    for child, lastmod in _locs(r.text):
        cr, _ = get(child)
        entries = _locs(cr.text) if cr.ok else []
        name = child.rsplit("/", 1)[-1]
        children[name] = {"url": child, "status": cr.status_code, "lastmod": lastmod, "count": len(entries)}
        for loc, mod in entries:
            urls[loc] = {"sitemap": name, "lastmod": mod}
    return {"index_status": r.status_code, "children": children}, urls


# ---------------------------------------------------------------- pages

class PageParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.title, self.meta, self.canonical, self.robots = None, None, None, None
        self.h1, self.links, self.schema, self.hreflang = [], set(), [], 0
        self._in = None
        self._text, self._skip = [], 0
        self._jsonld = False
        self._buf = []

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag in ("script", "style", "noscript"):
            self._skip += 1
            self._jsonld = tag == "script" and (a.get("type") or "").lower() == "application/ld+json"
        if tag == "title" and self.title is None:
            self._in, self._buf = "title", []
        elif tag == "h1":
            self._in, self._buf = "h1", []
        elif tag == "meta":
            name = (a.get("name") or "").lower()
            if name == "description" and self.meta is None:
                self.meta = (a.get("content") or "").strip()
            elif name == "robots":
                self.robots = (a.get("content") or "").lower()
        elif tag == "link":
            rel = (a.get("rel") or "").lower()
            if rel == "canonical" and self.canonical is None:
                self.canonical = a.get("href")
            elif rel == "alternate" and a.get("hreflang"):
                self.hreflang += 1
        elif tag == "a" and a.get("href"):
            self.links.add(a["href"])

    def handle_endtag(self, tag):
        if tag in ("script", "style", "noscript"):
            self._skip = max(0, self._skip - 1)
            self._jsonld = False
        if tag == self._in:
            text = " ".join("".join(self._buf).split())
            if tag == "title":
                self.title = text
            else:
                self.h1.append(text)
            self._in = None

    def handle_data(self, data):
        if self._jsonld:
            self.schema += re.findall(r'"@type"\s*:\s*"([^"]+)"', data)
            return
        if self._in:
            self._buf.append(data)
        if not self._skip:
            self._text.append(data)

    def words(self):
        return len(re.findall(r"\w+", " ".join(self._text)))


def _internal(href, base):
    url = urldefrag(urljoin(base, href))[0]
    p = urlparse(url)
    if p.scheme in ("http", "https") and p.netloc.endswith(urlparse(C.SITE).netloc.replace("www.", "")):
        return url
    return None


def _get_page(url):
    """GET a page. A server error or no answer is asked once more after a pause, so a passing
    hiccup at the server or CDN (a 504 in under 200 ms, say) is not reported as a broken page.
    Returns (response or None, ms, error name, first_try); first_try is the failed first answer,
    a status code or an error name, when a second try was needed."""
    first_try = None
    for attempt in range(2):
        try:
            r, ms = get(url, allow_redirects=True)
            error = None
        except requests.RequestException as e:
            r, ms, error = None, None, type(e).__name__
        if r is not None and r.status_code < 500:
            break
        if attempt == 0:
            first_try = r.status_code if r is not None else error
            time.sleep(C.RETRY_PAUSE_S)
    return r, ms, error, first_try


def fetch_page(url):
    r, ms, error, first_try = _get_page(url)
    retried = {"first_try": first_try} if first_try is not None else {}
    if r is None:
        return {"status": 0, "error": error, **retried}
    out = {
        "status": r.status_code,
        "final_url": r.url if r.url != url else None,
        "redirects": len(r.history),
        "ms": ms,
        "bytes": len(r.content),
        "x_robots": r.headers.get("X-Robots-Tag"),
        **retried,
    }
    if r.ok and "html" in r.headers.get("Content-Type", ""):
        p = PageParser()
        p.feed(r.text)
        out.update({
            "title": p.title,
            "meta_description": p.meta,
            "canonical": p.canonical,
            "robots_meta": p.robots,
            "h1": p.h1[:3],
            "h1_count": len(p.h1),
            "words": p.words(),
            "schema_types": sorted(set(p.schema)),
            "hreflang": p.hreflang,
            "_links": sorted({u for h in p.links if (u := _internal(h, r.url))}),
        })
    out["cache"] = r.headers.get("X-Cache") or r.headers.get("CF-Cache-Status")
    if ms > C.SLOW_RESPONSE_MS:  # slow: ask again, to tell a cold cache from a slow page
        try:
            out["ms_retry"] = get(url)[1]
        except requests.RequestException:
            pass
    return out


def link_status(u):
    """HTTP status of a linked URL (0 = no answer); like pages, a server error or no answer is
    asked once more after a pause before the link counts as broken."""
    status = 0
    for attempt in range(2):
        try:
            r = session.head(u, timeout=C.TIMEOUT, allow_redirects=True)
            if r.status_code in (405, 403):
                r = session.get(u, timeout=C.TIMEOUT)
            status = r.status_code
        except requests.RequestException:
            status = 0
        if 0 < status < 500:
            break
        if attempt == 0:
            time.sleep(C.RETRY_PAUSE_S)
    return status


def collect_pages(urls):
    with ThreadPoolExecutor(C.CRAWL_WORKERS) as pool:
        results = dict(zip(urls, pool.map(fetch_page, urls)))
    # internal links that are not in the sitemap: check they resolve
    linked = {}
    for page, data in results.items():
        for link in data.pop("_links", []):
            linked.setdefault(link, page)
    extra = [u for u in linked if u not in results and u.rstrip("/") + "/" not in results][: C.MAX_EXTRA_LINKS]
    with ThreadPoolExecutor(C.CRAWL_WORKERS) as pool:
        statuses = dict(zip(extra, pool.map(link_status, extra)))
    links = {u: {"status": s, "found_on": linked[u]} for u, s in statuses.items()}
    return results, links, len(linked)


# ---------------------------------------------------------------- PageSpeed Insights

PSI = "https://www.googleapis.com/pagespeedonline/v5/runPagespeed"


def _field(exp):
    if not exp or "metrics" not in exp:
        return None
    m = exp["metrics"]

    def p75(key):
        return (m.get(key) or {}).get("percentile")
    cls = p75("CUMULATIVE_LAYOUT_SHIFT_SCORE")
    return {
        "overall": exp.get("overall_category"),
        "lcp_ms": p75("LARGEST_CONTENTFUL_PAINT_MS"),
        "inp_ms": p75("INTERACTION_TO_NEXT_PAINT"),
        "cls": cls / 100 if cls is not None else None,
    }


def psi(url):
    key = os.environ.get("GOOGLE_API_KEY")
    params = {"url": url, "strategy": "mobile", "category": "performance"}
    if key:
        params["key"] = key
    for attempt in range(3):
        try:
            r = requests.get(PSI, params=params, timeout=180)
        except requests.RequestException as e:
            err = type(e).__name__
            continue
        if r.status_code == 200:
            d = r.json()
            a = d["lighthouseResult"]["audits"]
            page_exp = d.get("loadingExperience") or {}
            return {
                "score": round(d["lighthouseResult"]["categories"]["performance"]["score"] * 100),
                "lcp_ms": round(a["largest-contentful-paint"]["numericValue"]),
                "cls": round(a["cumulative-layout-shift"]["numericValue"], 3),
                "tbt_ms": round(a["total-blocking-time"]["numericValue"]),
                # without enough visits of its own, PageSpeed fills the page's field data with the whole site's
                "field": None if page_exp.get("origin_fallback") else _field(page_exp),
                "origin_field": _field(d.get("originLoadingExperience")),
            }
        try:
            e = r.json().get("error", {})
            reason = next((d["reason"] for d in e.get("details", []) if d.get("reason")), None) or e.get("status")
        except ValueError:
            reason = None
        err = f"HTTP {r.status_code}" + (f" {reason}" if reason else "")
        if r.status_code in (400, 401, 403):  # the key itself is refused: retrying will not help
            return {"error": err, "setup_problem": True}
        time.sleep(5 * (attempt + 1))
    return {"error": err, "setup_problem": err.startswith("HTTP 429")}


def collect():
    started = time.time()
    snap = {"site": C.SITE, "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "collected_at": datetime.now(timezone.utc).isoformat(timespec="seconds")}
    snap["robots"] = collect_robots()
    snap["sitemaps"], urls = collect_sitemaps()
    pages, links, linked_count = collect_pages(list(urls))
    for u, meta in urls.items():
        pages[u].update(meta)
    snap["pages"] = pages
    snap["links"] = {"internal_links_found": linked_count, "checked_outside_sitemap": links}
    snap["psi"] = {u: psi(u) for u in C.KEY_PAGES}
    snap["duration_s"] = round(time.time() - started)
    return snap


if __name__ == "__main__":
    s = collect()
    print(json.dumps({k: v for k, v in s.items() if k != "pages"}, indent=1)[:3000])
    print(len(s["pages"]), "pages")
