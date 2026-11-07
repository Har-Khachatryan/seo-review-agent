# Daily SEO Review Agent: searchbloom.com

Every morning at 09:00 (Yerevan) the agent checks searchbloom.com, compares it with the day before, and sends the team a short review on Telegram: what needs attention, why it matters, and what to do next. A full report is attached and saved to this repository.

## How it works

```text
GitHub Actions, 09:00 daily
        │
        ▼
1 collect   robots.txt · 9 sitemaps · all 283 pages · internal links · PageSpeed for 5 key pages
        │
        ▼
2 analyze   state checks: what is wrong today            (errors, noindex, broken links, slow LCP …)
            change checks: what moved since yesterday    (robots.txt edits, pages dropped, titles rewritten …)
            each finding marked new / ongoing / resolved
        │
        ▼
3 review    Claude (Claude Haiku 5.5) ranks the findings, writes why each matters and the next step,
            as structured JSON; falls back to a rule-based review if the API is unavailable
        │
        ▼
4 deliver   Telegram message + full markdown report as an attachment
        │
        ▼
5 save      snapshot, findings and report committed to the repository: tomorrow's baseline
```

| Module | Job |
|---|---|
| `agent/config.py` | The site, the key pages, the crawlers to check, every threshold |
| `agent/collect.py` | Fetches and parses everything (see [DATA.md](DATA.md)) |
| `agent/analyze.py` | 25+ checks; findings carry a stable id so the same problem is not reported as new every day |
| `agent/review.py` | The Claude call and the fallback review |
| `agent/deliver.py` | Telegram text and the markdown report |
| `agent/run.py` | One run, start to finish |
| `.github/workflows/daily-seo-review.yml` | The schedule, and a button to run it on demand |

## Why these choices

- **Public data, any site.** Crawling the sitemap, robots.txt and PageSpeed needs no access to the site, so the agent runs for searchbloom.com today and for a client's site tomorrow.
- **Rules find, the model explains.** Deterministic checks decide what is a problem, so nothing is hallucinated or missed by chance; Claude does what rules do badly: rank, explain, and write the next step for a person. It gets only the findings and is told to use only facts in them.
- **New vs ongoing.** A daily report that repeats the same 40 long titles every morning gets ignored. New problems lead; ongoing ones are listed once and noted as such; fixes show up as resolved.
- **Telegram.** Read on a phone before work, in a team chat where people can reply and assign. The full report is attached for whoever does the fix.
- **GitHub Actions.** Free, runs without anyone's laptop, keeps a history of every day in git, and has a "Run workflow" button for on-demand reviews.
- **AI crawler access** is checked every day because the site sells AI SEO: a robots.txt change that blocks GPTBot or PerplexityBot would cost it AI citations quietly.

## Run it

```bash
pip install -r requirements.txt
cp .env.example .env            # fill in the keys
python -m agent.check_setup     # checks each key without printing it, and finds the Telegram chat id
python -m agent.run --dry-run   # everything except sending
python -m agent.run             # and send to Telegram
python -m agent.run --replay    # re-review the last snapshot without crawling again (for testing)
```

On GitHub: add the four values as repository secrets (`GOOGLE_API_KEY`, `ANTHROPIC_API_KEY`, `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID`). Run time is about 3–4 minutes. The review runs on Claude Haiku 5.5 and costs well under a cent a day (the exact token count of each run is saved in `data/findings/`); setting `MODEL = "claude-opus-5-5"` in `agent/config.py` gives a more thorough review at roughly $0.10 a day.

## What it cannot do yet, and what I would add

- **Search Console.** Clicks, impressions, CTR and positions by page and query are the real performance data. For a site we own, a service account with read access would let the agent say "clicks to /ecommerce-seo/ fell 30% this week, mostly on query X".
- **AI visibility.** Track a fixed set of buyer questions in ChatGPT, Perplexity and Google AI Overviews and report whether the site is cited (the measurement the Task 1 article recommends), or pull it from a tool such as Peec AI.
- **Rankings and backlinks** from an SEO tool API (Ahrefs, Semrush): lost links and ranking drops on target keywords.
- **Trends, not just yesterday.** Compare against a 7-day baseline so slow declines show up, and a weekly summary.
- **Rendering.** Pages are read as HTML; content that only appears after JavaScript runs is not seen.
- **Ownership.** Route each finding type to an owner (developer, content, SEO) and mention them in the chat.
