"""Check the four keys in .env without printing them, and find the Telegram chat id.

    python -m agent.check_setup
"""
import os
import re
import sys

import anthropic
import requests

from . import config as C
from .run import load_env

ENV_PATH = os.path.join(os.path.dirname(C.DATA_DIR), ".env")


def fmt(name, value, prefix=None):
    if not value:
        return f"{name}: EMPTY"
    notes = [f"{len(value)} characters"]
    if prefix and not value.startswith(prefix):
        notes.append(f"does not start with {prefix!r}")
    if re.search(r"\.\.\.|\*|•|…|\s", value):
        notes.append("looks masked or has spaces: copy the whole key again")
    return f"{name}: " + ", ".join(notes)


def check_google():
    key = os.environ.get("GOOGLE_API_KEY")
    print(fmt("GOOGLE_API_KEY", key, "AIza"))
    if not key:
        return
    r = requests.get("https://www.googleapis.com/pagespeedonline/v5/runPagespeed",
                     params={"url": C.SITE + "/", "strategy": "mobile", "category": "performance", "key": key},
                     timeout=180)
    if r.status_code == 200:
        score = r.json()["lighthouseResult"]["categories"]["performance"]["score"]
        print(f"  OK: PageSpeed works (home page mobile score {round(score * 100)})")
    else:
        msg = r.json().get("error", {}).get("message", r.text)[:200]
        print(f"  FAILED: HTTP {r.status_code}: {msg}")


def check_anthropic():
    key = os.environ.get("ANTHROPIC_API_KEY")
    print(fmt("ANTHROPIC_API_KEY", key, "sk-ant-"))
    if not key:
        return
    client = anthropic.Anthropic()
    try:
        client.models.retrieve(C.MODEL)
        print(f"  OK: the key is valid and {C.MODEL} is available")
    except anthropic.AuthenticationError:
        print("  FAILED: the key is not valid (copy it again, or create a new one)")
        return
    except anthropic.APIStatusError as e:
        print(f"  FAILED: HTTP {e.status_code}: {str(e)[:200]}")
        return
    except anthropic.APIConnectionError:
        print("  FAILED: could not reach the API")
        return
    try:  # a tiny request: is there credit to run the review?
        client.messages.create(model=C.MODEL, max_tokens=64, output_config={"effort": "low"},
                               messages=[{"role": "user", "content": "Reply with OK."}])
        print("  OK: the account has credit; the Claude review will run")
    except anthropic.BadRequestError as e:
        if "credit" in str(e).lower() or "balance" in str(e).lower():
            print("  NO CREDIT: the key works but the balance is empty (Billing in the console)")
        else:
            print(f"  FAILED: {str(e)[:200]}")
    except anthropic.APIStatusError as e:
        print(f"  FAILED: HTTP {e.status_code}: {str(e)[:200]}")


def check_telegram():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    print(fmt("TELEGRAM_BOT_TOKEN", token))
    if not token:
        return
    api = f"https://api.telegram.org/bot{token}"
    me = requests.get(f"{api}/getMe", timeout=30).json()
    if not me.get("ok"):
        print("  FAILED: Telegram does not accept this token (copy it again from @BotFather)")
        return
    print(f"  OK: bot @{me['result']['username']}")
    chats = {}
    for u in requests.get(f"{api}/getUpdates", timeout=30).json().get("result", []):
        msg = u.get("message") or u.get("my_chat_member") or u.get("channel_post") or {}
        chat = msg.get("chat")
        if chat:
            name = chat.get("title") or chat.get("first_name")
            if chat.get("username"):
                name = f"{name} (@{chat['username']})"
            chats[chat["id"]] = (chat.get("type"), name)
    for cid, (kind, title) in chats.items():
        print(f"  chat seen: {title} ({kind}) id {cid}")
    groups = {cid: t for cid, t in chats.items() if t[0] in ("group", "supergroup")}
    people = {cid: t for cid, t in chats.items() if t[0] == "private"}
    pick = groups if groups else people  # a team group wins; otherwise one person's chat
    current = os.environ.get("TELEGRAM_CHAT_ID")
    if current:
        print(f"TELEGRAM_CHAT_ID: set ({current})")
    elif len(pick) == 1:
        cid = next(iter(pick))
        text = open(ENV_PATH, encoding="utf-8").read()
        text = re.sub(r"(?m)^TELEGRAM_CHAT_ID=.*$", f"TELEGRAM_CHAT_ID={cid}", text)
        open(ENV_PATH, "w", encoding="utf-8").write(text)
        print(f"TELEGRAM_CHAT_ID: written to .env ({cid}, {pick[cid][1]})")
    elif not pick:
        print("TELEGRAM_CHAT_ID: no chat yet. Open the bot in Telegram, press Start (or add it to a group and "
              "send /start@<bot> there), then run this again.")
    else:
        print("TELEGRAM_CHAT_ID: several chats found; put the right id from the list above in .env")


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    load_env()
    for check in (check_google, check_anthropic, check_telegram):
        try:
            check()
        except requests.RequestException as e:
            print(f"  FAILED: network error ({type(e).__name__})")
        print()
