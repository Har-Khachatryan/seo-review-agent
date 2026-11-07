"""Render the review as a Telegram message and a full markdown report, and send them."""
import html
import os

import requests

from . import config as C

DOT = {"red": "🔴", "amber": "🟠", "green": "🟢"}
SEV = {"critical": "🔴", "high": "🟠", "medium": "🟡", "low": "⚪"}


def short(url):
    return url.replace(C.SITE, "") or "/"


def telegram_text(review, result):
    """The message as a list of parts, each within Telegram's 4096-character limit."""
    def e(text):
        return html.escape(str(text), quote=False)
    s = result["summary"]
    lines = [f"{DOT[review['status']]} <b>SEO review · {C.SITE_NAME} · {result['date']}</b>",
             e(review["headline"]), ""]
    if review["priorities"]:
        lines.append("<b>Needs attention</b>")
        for i, p in enumerate(review["priorities"], 1):
            tag = " · NEW" if p["is_new"] else ""
            lines.append(f"{i}. {SEV[p['severity']]} <b>{e(p['title'])}</b>{tag}")
            lines.append(f"   {e(p['why'])}")
            lines.append(f"   👉 {e(p['action'])}")
            for u in p["urls"][:2]:
                lines.append(f"   <a href=\"{html.escape(u)}\">{e(short(u))}</a>")
        lines.append("")
    lines.append(f"<b>Since yesterday:</b> {e(review['changes'])}")
    if review.get("healthy"):
        lines.append("<b>Fine today</b>")
        lines += [f"✓ {e(h.rstrip('.'))}" for h in review["healthy"]]
    for n in review.get("notes", []):
        lines.append(f"⚙️ <i>Monitoring note: {e(n)}</i>")
    cwv = s.get("site_core_web_vitals")
    lines.append("")
    lines.append(f"📊 {s['pages_ok']}/{s['pages_in_sitemap']} pages OK · median response {s['median_response_ms']} ms"
                 + (f" · real-user LCP {cwv['lcp_ms']} ms, INP {cwv['inp_ms']} ms, CLS {cwv['cls']}" if cwv else ""))
    parts, cur = [], ""
    for line in lines:  # split between lines, never inside a tag
        if len(cur) + len(line) + 1 > 3900:
            parts.append(cur.rstrip())
            cur = ""
        cur += line + "\n"
    parts.append(cur.rstrip())
    return parts


def markdown_report(review, result):
    s = result["summary"]
    out = [f"# SEO review: {C.SITE_NAME}, {result['date']}", "",
           f"**Status:** {review['status'].upper()} · {review['headline']}", "",
           "## Needs attention", ""]
    for i, p in enumerate(review["priorities"], 1):
        out += [f"{i}. **{p['title']}** ({p['severity']}{', new' if p['is_new'] else ''})",
                f"   - Why: {p['why']}", f"   - Next step: {p['action']}"]
        out += [f"   - {u}" for u in p["urls"]]
    if not review["priorities"]:
        out.append("Nothing needs attention today.")
    out += ["", "## Since yesterday", "", review["changes"], "", "## Fine today", ""]
    out += [f"- {h}" for h in review.get("healthy", [])]
    if review.get("notes"):
        out += ["", "## Monitoring notes (the agent's own setup)", ""] + [f"- {n}" for n in review["notes"]]

    out += ["", "## All findings", "", "| Severity | Status | Finding | Pages | Detail |", "|---|---|---|---|---|"]
    for f in result["findings"]:
        out.append(f"| {f['severity']} | {f['status']} | {f['title']} | {f['count']} | {f['detail']} |")
    for f in result["resolved"]:
        out.append(f"| {f['severity']} | resolved | {f['title']} | {f['count']} | fixed since yesterday |")

    out += ["", "## Page speed (mobile, key pages)", "",
            "| Page | Score | Lab LCP | Lab CLS | TBT | Real-user LCP | Real-user INP | Real-user CLS |",
            "|---|---|---|---|---|---|---|---|"]
    for url, p in s["psi"].items():
        if "error" in p:
            out.append(f"| {short(url)} | error: {p['error']} | | | | | | |")
            continue
        fl = p.get("field") or {}
        out.append(f"| {short(url)} | {p['score']} | {p['lcp_ms']} ms | {p['cls']} | {p['tbt_ms']} ms | "
                   f"{fl.get('lcp_ms', '–')} | {fl.get('inp_ms', '–')} | {fl.get('cls', '–')} |")
    out += ["", "## Coverage", "",
            f"- Sitemap pages crawled: {s['pages_in_sitemap']} ({s['pages_ok']} answered 200); "
            + ", ".join(f"{k} {v}" for k, v in s["sitemaps"].items()),
            f"- Internal links found: {s['internal_links_found']}",
            f"- Median HTML response: {s['median_response_ms']} ms",
            "- Crawler access (robots.txt): " + ", ".join(f"{b} {'allowed' if ok else 'BLOCKED'}" for b, ok in s["crawler_access"].items()),
            f"- Review written by: {review.get('_written_by')}", ""]
    return "\n".join(out)


def send_telegram(parts, report_path):
    token, chat = os.environ.get("TELEGRAM_BOT_TOKEN"), os.environ.get("TELEGRAM_CHAT_ID")
    if not (token and chat):
        print("Telegram not configured (TELEGRAM_BOT_TOKEN / TELEGRAM_CHAT_ID); message printed only.")
        return False
    api = f"https://api.telegram.org/bot{token}"
    for text in parts:
        r = requests.post(f"{api}/sendMessage", timeout=30, data={
            "chat_id": chat, "text": text, "parse_mode": "HTML", "disable_web_page_preview": "true"})
        if not r.ok:
            raise RuntimeError(f"Telegram refused the message: {r.text[:300]}")
    with open(report_path, "rb") as fh:
        requests.post(f"{api}/sendDocument", timeout=60, data={"chat_id": chat, "caption": "Full report"},
                      files={"document": (os.path.basename(report_path), fh, "text/markdown")}).raise_for_status()
    return True
