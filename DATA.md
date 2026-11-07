# The data the agent works from

Every morning the agent takes a fresh snapshot of **searchbloom.com** from public sources, compares it with the previous day's, and reviews the difference. Nothing needs a login to the site, so the agent works for any website. Search Console data (clicks, impressions, positions) would be the next source to add when the agent runs for a site we own (see the README).

## Sources

| Data | Where it comes from | What the agent uses it for |
|---|---|---|
| **robots.txt** | `https://www.searchbloom.com/robots.txt`, fetched daily | Whether Googlebot, Bingbot and AI crawlers (GPTBot, OAI-SearchBot, ChatGPT-User, ClaudeBot, Claude-SearchBot, PerplexityBot, Google-Extended, CCBot) may crawl the site; any change from yesterday |
| **XML sitemaps** | The sitemap index named in robots.txt (`sitemap_index.xml`, 9 child sitemaps from Rank Math) | The list of pages the site wants indexed (283 today) with their last-modified dates: pages added, removed or updated |
| **Every sitemap page** | Each URL fetched once a day, four at a time, with an identifying user agent | HTTP status, redirects, HTML response time, title, meta description, canonical, robots meta and X-Robots-Tag, H1s, word count, JSON-LD structured-data types |
| **Internal links** | Every link from those pages to the same site (535 today); those not in the sitemap are checked as well | Broken internal links and the page each one sits on |
| **PageSpeed Insights API** (Google) | 5 key pages, mobile: home, GEO service, AEO service, the "Best AI SEO Companies" guide, ecommerce SEO | Lab performance (score, LCP, CLS, TBT) and **real-user Core Web Vitals from the Chrome UX Report** (p75 LCP, INP, CLS for the page and for the whole site) |

## Files

| File | What it is |
|---|---|
| `data/latest_snapshot.json` | Today's full snapshot, readable: robots.txt, sitemaps, every page's fields, links, PageSpeed results |
| `data/snapshots/YYYY-MM-DD.json.gz` | One snapshot per day, compressed: the history the agent compares against |
| `data/findings/YYYY-MM-DD.json` | That day's findings (with new / ongoing / resolved status) and the written review |
| `reports/YYYY-MM-DD.md` | The full report sent to Telegram with the message |

## What it does not have

- **No traffic or ranking data.** Without Search Console access the agent cannot see clicks, impressions or positions, and its review is told never to claim any.
- **Lab speed scores move a few points between runs.** The agent flags only drops of 10 points or more, and leads with real-user data where Google has it.
- **One sample a day.** A short outage between morning runs would be missed.
