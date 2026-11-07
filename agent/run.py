"""The daily run: collect → compare with yesterday → review → deliver → save.

    python -m agent.run            # full run, sends to Telegram
    python -m agent.run --dry-run  # everything except sending
"""
import argparse
import glob
import gzip
import json
import os
import sys

from . import config as C
from .analyze import analyze
from .collect import collect
from .deliver import markdown_report, send_telegram, telegram_text
from .review import write_review


def load_env():
    """Local runs read ../.env; on GitHub Actions the values come from repository secrets."""
    path = os.path.join(os.path.dirname(C.DATA_DIR), ".env")
    if os.path.exists(path):
        for line in open(path, encoding="utf-8"):
            if "=" in line and not line.lstrip().startswith("#"):
                k, v = line.strip().split("=", 1)
                os.environ.setdefault(k.strip(), v.strip().strip('"'))


def latest(pattern, before):
    files = sorted(f for f in glob.glob(pattern) if os.path.basename(f).split(".")[0] < before)
    return files[-1] if files else None


def main():
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true", help="do everything except sending")
    ap.add_argument("--replay", action="store_true", help="reuse data/latest_snapshot.json instead of crawling")
    args = ap.parse_args()
    load_env()
    snaps, finds = os.path.join(C.DATA_DIR, "snapshots"), os.path.join(C.DATA_DIR, "findings")
    for d in (snaps, finds, C.REPORTS_DIR):
        os.makedirs(d, exist_ok=True)

    if args.replay:
        snap = json.load(open(os.path.join(C.DATA_DIR, "latest_snapshot.json"), encoding="utf-8"))
        print(f"Replaying the snapshot of {snap['date']} (no crawl)")
    else:
        print(f"Collecting {C.SITE} ...")
        snap = collect()
    today = snap["date"]
    prev_file = latest(os.path.join(snaps, "*.json.gz"), today)
    prev = json.load(gzip.open(prev_file, "rt", encoding="utf-8")) if prev_file else None
    prev_find_file = latest(os.path.join(finds, "*.json"), today)
    prev_findings = json.load(open(prev_find_file, encoding="utf-8"))["findings"] if prev_find_file else None
    print(f"Collected {len(snap['pages'])} pages in {snap['duration_s']} s; "
          f"comparing with {os.path.basename(prev_file) if prev_file else 'nothing (first run)'}")

    history = []  # median response time of up to 7 previous days
    for f in sorted(glob.glob(os.path.join(finds, "*.json"))):
        if os.path.basename(f).split(".")[0] < today:
            history.append(json.load(open(f, encoding="utf-8"))["summary"].get("median_response_ms"))
    result = analyze(snap, prev, prev_findings, history[-7:])
    review = write_review(result)
    report = markdown_report(review, result)
    parts = telegram_text(review, result)

    with gzip.open(os.path.join(snaps, f"{today}.json.gz"), "wt", encoding="utf-8") as fh:
        json.dump(snap, fh)
    with open(os.path.join(C.DATA_DIR, "latest_snapshot.json"), "w", encoding="utf-8") as fh:
        json.dump(snap, fh, indent=1, ensure_ascii=False)
    with open(os.path.join(finds, f"{today}.json"), "w", encoding="utf-8") as fh:
        json.dump(dict(result, review=review), fh, indent=1, ensure_ascii=False)
    report_path = os.path.join(C.REPORTS_DIR, f"{today}.md")
    with open(report_path, "w", encoding="utf-8") as fh:
        fh.write(report)

    print("\n" + "\n\n[next message]\n".join(parts) + "\n")
    if not args.dry_run:
        print(f"Sent to Telegram ({len(parts)} message(s) + report)." if send_telegram(parts, report_path) else "")
    print(f"Saved: data/snapshots/{today}.json.gz, data/findings/{today}.json, reports/{today}.md")


if __name__ == "__main__":
    main()
