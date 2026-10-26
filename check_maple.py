#!/usr/bin/env python3
"""Maple Store new-listing alert -> Telegram.

Checks Maple Store's iPhone collections, compares them with the listings
seen on earlier runs (seen_ids.json), and sends one Telegram message for
anything new that is in stock.

Environment variables (set as GitHub secrets):
  TELEGRAM_BOT_TOKEN  the token BotFather gave you
  TELEGRAM_CHAT_ID    your chat ID (a number)
"""

import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

# ----------------------------------------------------------------------------
# Settings you may want to change
# ----------------------------------------------------------------------------
BASE = "https://maplestore.in"
COLLECTIONS = ["iphone-15-series", "iphone-16-series"]

# Models to alert on. Each entry must match the start of the product title,
# which looks like "iPhone 15 Plus - 128GB - Black - Pre-owned".
# "iPhone 15" does NOT match "iPhone 15 Pro", and "iPhone 16" does NOT match
# "iPhone 16 Pro" or "iPhone 16 Plus".
MODELS = ["iPhone 15", "iPhone 15 Plus", "iPhone 16"]

ITEMS_PER_MESSAGE = 5
PAGE_SIZE = 250
STATE_FILE = Path(__file__).with_name("seen_ids.json")
USER_AGENT = "Mozilla/5.0 (personal price alert; contact: github.com)"
# ----------------------------------------------------------------------------

TITLE_RE = re.compile(
    r"^(?:" + "|".join(re.escape(m) for m in MODELS) + r")\s+-\s+", re.IGNORECASE
)


def http_get(url, retries=2):
    last_error = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
            )
            with urllib.request.urlopen(req, timeout=30) as resp:
                return resp.read().decode("utf-8")
        except urllib.error.HTTPError as e:
            last_error = f"HTTP {e.code}"
            if e.code in (401, 403, 404):
                break  # retrying will not help
        except Exception as e:  # network problems
            last_error = type(e).__name__
        time.sleep(3 * (attempt + 1))
    raise RuntimeError(f"Could not fetch {url}: {last_error}")


def fetch_collection(handle):
    products = []
    page = 1
    while True:
        url = f"{BASE}/collections/{handle}/products.json?limit={PAGE_SIZE}&page={page}"
        batch = json.loads(http_get(url)).get("products", [])
        products.extend(batch)
        if len(batch) < PAGE_SIZE:
            break
        page += 1
        time.sleep(1)
    return products


def inr(value):
    """42999.00 -> ₹42,999 ; 134900.00 -> ₹1,34,900"""
    try:
        s = str(int(float(value)))
    except (TypeError, ValueError):
        return f"₹{value}"
    if len(s) > 3:
        head, tail = s[:-3], s[-3:]
        head = re.sub(r"(\d)(?=(\d\d)+$)", r"\1,", head)
        s = f"{head},{tail}"
    return "₹" + s


def is_available(product):
    return any(v.get("available") for v in product.get("variants", []))


def describe(product):
    variant = (product.get("variants") or [{}])[0]
    price = variant.get("price")
    compare = variant.get("compare_at_price")
    line = f"• {product['title']}\n  {inr(price)}"
    try:
        if compare and float(compare) > float(price):
            line += f" (was {inr(compare)})"
    except (TypeError, ValueError):
        pass
    line += f"\n  {BASE}/products/{product['handle']}"
    return line


def send_message(text):
    """Send a Telegram message. Raises RuntimeError on any failure.

    The error text never includes the bot token.
    """
    token = os.environ["TELEGRAM_BOT_TOKEN"].strip()
    chat_id = os.environ["TELEGRAM_CHAT_ID"].strip()
    data = urllib.parse.urlencode(
        {
            "chat_id": chat_id,
            "text": text,
            # Several links per message: skip the big link previews.
            "link_preview_options": json.dumps({"is_disabled": True}),
        }
    ).encode("utf-8")
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{token}/sendMessage",
        data=data,
        headers={"User-Agent": USER_AGENT},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        if not body.get("ok"):
            raise RuntimeError("Telegram did not accept the message")
    except urllib.error.HTTPError as e:
        raise RuntimeError(f"Telegram returned HTTP {e.code}") from None
    except urllib.error.URLError as e:
        raise RuntimeError(f"Telegram unreachable: {e.reason}") from None


def notify_new(products):
    chunks = [
        products[i : i + ITEMS_PER_MESSAGE]
        for i in range(0, len(products), ITEMS_PER_MESSAGE)
    ]
    for index, chunk in enumerate(chunks):
        header = f"New on Maple Store ({len(products)} new)\n\n" if index == 0 else ""
        send_message(header + "\n\n".join(describe(p) for p in chunk))
        if index < len(chunks) - 1:
            time.sleep(2)  # stay well inside Telegram's rate limits


def load_seen():
    if not STATE_FILE.exists():
        return None
    return set(json.loads(STATE_FILE.read_text()))


def save_seen(ids):
    STATE_FILE.write_text(json.dumps(sorted(ids)) + "\n")


def main():
    found = {}
    for handle in COLLECTIONS:
        for product in fetch_collection(handle):
            if TITLE_RE.match(product.get("title", "")):
                found[product["id"]] = product
        time.sleep(1)

    seen = load_seen()
    all_ids = set(found)

    if seen is None:
        # First run: remember what is already listed so we do not send an
        # alert for every existing phone.
        save_seen(all_ids)
        send_message(
            f"Maple alert is on. Tracking {len(all_ids)} current listings "
            f"({', '.join(MODELS)}). You will be messaged when new ones appear."
        )
        print(f"Baseline saved: {len(all_ids)} listings.")
        return 0

    new_products = [
        p for pid, p in found.items() if pid not in seen and is_available(p)
    ]
    new_products.sort(key=lambda p: p["title"])

    if new_products:
        notify_new(new_products)  # raises on failure, so state is not saved
        print(f"Sent alert for {len(new_products)} new listings.")

    if not all_ids <= seen:
        save_seen(seen | all_ids)

    if not new_products:
        print("No new listings.")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
