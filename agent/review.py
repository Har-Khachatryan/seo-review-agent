"""Write the morning review from the findings: Claude ranks what needs attention and
says why and what to do. If the API is unavailable, a plain rule-based review is used."""
import json
import os

import anthropic

from . import config as C

SYSTEM = """You are the SEO lead reviewing a website's daily health check for the marketing team.
You get today's findings from an automated crawl of every sitemap page, robots.txt, internal links,
and PageSpeed Insights (lab scores plus real-user Core Web Vitals from the Chrome UX Report).
There is no Search Console traffic data, so never claim anything about clicks, rankings or traffic.

Write for busy people who read this on a phone before work:
- Lead with what needs attention today. New problems first, then anything critical that is ongoing.
- For each priority: what is wrong, why it matters for search or AI visibility, and the concrete next step.
- Use only facts present in the findings. Quote real URLs and numbers from them; invent nothing.
- Lab results (score, lab LCP) are the median of several runs, yet still move from day to day; report
  what was measured, never claim a lab change is beyond normal variation, and lead with real-user data.
- An intermittent server error means the page failed and then loaded on a recheck: the page is up,
  so never say it is down or needs restoring.
- "monitoring_notes" are about this agent's own setup (an API key, a quota), not the website.
  Never present them as a site problem or a priority.
- If nothing important changed, say so plainly. A quiet day is a good result.
- Keep it short: at most 5 priorities; each "why" and each "action" is one sentence of at most 30 words."""

SCHEMA = {
    "type": "object",
    "properties": {
        "status": {"type": "string", "enum": ["green", "amber", "red"],
                   "description": "red: something breaks indexing or availability; amber: real issues to fix; green: healthy"},
        "headline": {"type": "string", "description": "One sentence: the state of the site today"},
        "priorities": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "title": {"type": "string"},
                    "severity": {"type": "string", "enum": ["critical", "high", "medium", "low"]},
                    "is_new": {"type": "boolean"},
                    "why": {"type": "string", "description": "Why it matters: one sentence, at most 30 words"},
                    "action": {"type": "string", "description": "The concrete next step and its usual owner: one sentence, at most 30 words"},
                    "urls": {"type": "array", "items": {"type": "string"}},
                },
                "required": ["title", "severity", "is_new", "why", "action", "urls"],
                "additionalProperties": False,
            },
        },
        "changes": {"type": "string", "description": "What changed on the site since yesterday, in one short paragraph, or 'No changes.'"},
        "healthy": {"type": "array", "items": {"type": "string"}, "description": "2-4 short things that are fine today"},
    },
    "required": ["status", "headline", "priorities", "changes", "healthy"],
    "additionalProperties": False,
}


def notes(result):
    """Problems with the agent's own setup, kept apart from the site's findings."""
    return [f["detail"] for f in result["findings"] if f["kind"] == "agent"]


def _payload(result):
    trimmed = []
    for f in result["findings"]:
        if f["kind"] == "agent":
            continue
        g = dict(f)
        g["data"] = json.dumps(f["data"])[:1500]
        trimmed.append(g)
    return {"site": C.SITE_NAME, "date": result["date"], "first_run": result["first_run"],
            "summary": result["summary"], "findings": trimmed, "monitoring_notes": notes(result),
            "resolved_since_yesterday": [{"title": f["title"], "count": f["count"]} for f in result["resolved"]]}


def claude_review(result):
    client = anthropic.Anthropic()
    response = client.messages.create(
        model=C.MODEL,
        max_tokens=16000,
        system=SYSTEM,
        messages=[{"role": "user", "content": "Today's findings as JSON:\n\n" + json.dumps(_payload(result), indent=1)}],
        output_config={"effort": "medium", "format": {"type": "json_schema", "schema": SCHEMA}},
    )
    if response.stop_reason == "refusal":
        raise RuntimeError("the model declined the request")
    text = next(b.text for b in response.content if b.type == "text")
    review = json.loads(text)
    review["_written_by"] = response.model
    review["_tokens"] = {"in": response.usage.input_tokens, "out": response.usage.output_tokens}
    return review


def rule_review(result):
    order = [f for f in result["findings"] if f["severity"] != "info" and f["kind"] != "agent"]
    worst = order[0]["severity"] if order else None
    status = "red" if worst == "critical" else "amber" if worst in ("high", "medium") else "green"
    pri = [{"title": f["title"], "severity": f["severity"], "is_new": f["status"] == "new",
            "why": f["detail"], "action": "Review the listed URLs.", "urls": f["urls"][:3]} for f in order[:5]]
    changes = [f["title"] for f in result["findings"] if f["kind"] == "changes" or "|20" in f["id"]]
    return {"status": status,
            "headline": f"{len(order)} issue type(s) found across {result['summary']['pages_in_sitemap']} pages.",
            "priorities": pri, "changes": "; ".join(changes) or "No changes.",
            "healthy": [f"{result['summary']['pages_ok']} of {result['summary']['pages_in_sitemap']} sitemap pages answer 200"],
            "_written_by": "rules (Claude API unavailable)"}


def write_review(result):
    review = None
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            review = claude_review(result)
        except (anthropic.APIError, RuntimeError, StopIteration, json.JSONDecodeError) as e:
            print(f"Claude review failed ({type(e).__name__}: {e}); using the rule-based review.")
    review = review or rule_review(result)
    review["notes"] = notes(result)
    return review
