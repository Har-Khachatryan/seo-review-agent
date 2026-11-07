"""What the agent watches, and the thresholds it judges by."""
import os

SITE = "https://www.searchbloom.com"
SITE_NAME = "searchbloom.com"
SITEMAP_INDEX = f"{SITE}/sitemap_index.xml"
ROBOTS = f"{SITE}/robots.txt"

# Measured with PageSpeed Insights every day: the same pages, so days compare fairly.
KEY_PAGES = [
    f"{SITE}/",
    f"{SITE}/generative-engine-optimization/",
    f"{SITE}/answer-engine-optimization/",
    f"{SITE}/strategy/best-ai-seo-agency-companies-services-usa/",
    f"{SITE}/ecommerce-seo/",
]

# AI and search crawlers whose access through robots.txt is checked.
CRAWLERS = ["Googlebot", "Bingbot", "Google-Extended", "GPTBot", "OAI-SearchBot",
            "ChatGPT-User", "ClaudeBot", "Claude-SearchBot", "PerplexityBot", "CCBot"]

USER_AGENT = "Mozilla/5.0 (compatible; DailySEOReview/1.0; candidate-task-agent)"
CRAWL_WORKERS = 4          # polite: four requests at a time
TIMEOUT = 25               # seconds per request
MAX_EXTRA_LINKS = 600     # internal links outside the sitemap checked per day

# Thresholds
SLOW_RESPONSE_MS = 1500
THIN_WORDS = 300
TITLE_MAX = 65
META_MAX = 165
PSI_SCORE_POOR = 50
PSI_DROP = 10              # points lower than yesterday
LCP_GOOD_MS, LCP_POOR_MS = 2500, 4000
CLS_GOOD, CLS_POOR = 0.1, 0.25
INP_GOOD_MS, INP_POOR_MS = 200, 500

MODEL = "claude-haiku-5-5"  # well under a cent a day; set "claude-opus-5-5" for the most thorough review

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")
REPORTS_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "reports")
