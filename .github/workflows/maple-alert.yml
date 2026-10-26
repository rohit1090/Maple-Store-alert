#!/usr/bin/env python3
"""Maple Store new-listing alert -> Telegram.

Checks Maple Store's iPhone collections, compares them with the listings
seen on earlier runs (seen_ids.json), and sends a Telegram message for new,
in-stock phones that match your filters (model, price, storage, colour,
battery health).

Environment variables (set as GitHub secrets):
  TELEGRAM_BOT_TOKEN  the token BotFather gave you
  TELEGRAM_CHAT_ID    your chat ID (a number)

Optional:
  SEND_TEST=true      send one test message and exit (no state is changed)
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

# Models to track, with the highest price (in rupees) you would pay for each.
# A phone at exactly this price still qualifies. Titles on the site look like
# "iPhone 15 Plus - 128GB - Black - Pre-owned".
# "iPhone 15" does NOT match "iPhone 15 Pro", and "iPhone 16" does NOT match
# "iPhone 16 Pro" or "iPhone 16 Plus".
MODEL_MAX_PRICE = {
    "iPhone 15": 60000,
    "iPhone 15 Plus": 60000,
    "iPhone 16": 60000,
}

STORAGES = ["128GB", "256GB"]  # use [] for any storage
COLOURS = ["Black", "Blue", "Green"]  # use [] for any colour

MIN_BATTERY = 90  # alert only if battery health is at least this %. 0 = ignore

ITEMS_PER_MESSAGE = 10
PAGE_SIZE = 250
STATE_FILE = Path(__file__).with_name("seen_ids.json")
USER_AGENT = "Mozilla/5.0 (personal price alert; contact: github.com)"
# ----------------------------------------------------------------------------

TITLE_RE = re.compile(
    r"^(?:" + "|".join(re.escape(m) for m in MODEL_MAX_PRICE) + r")\s+-\s+",
    re.IGNORECASE,
)
MODEL_LIMITS = {m.casefold(): limit for m, limit in MODEL_MAX_PRICE.items()}
STORAGE_SET = {re.sub(r"\s+", "", s).upper() for s in STORAGES}
COLOUR_SET = {c.casefold() for c in COLOURS}


def http_get(url, retries=2, accept="application/json"):
    last_error = None
    for attempt in range(retries + 1):
        try:
            req = urllib.request.Request(
                url, headers={"User-Agent": USER_AGENT, "Accept": accept}
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


# "Battery: <b>81%</b>" sits inside the product's own block (id="Sku-template--...__main").
# Other products shown further down the page have the same text, so the main
# block is looked at first.
BATTERY_RE = re.compile(r"Battery\s*:?\s*(?:<[^>]*>\s*)*(\d{1,3})\s*%", re.IGNORECASE)
MAIN_BLOCK_RE = re.compile(r'id="Sku-template--[^"]*__main"', re.IGNORECASE)


def parse_battery(html):
    """Battery % of the main product on a Maple product page, or None."""
    block = MAIN_BLOCK_RE.search(html)
    if block:
        m = BATTERY_RE.search(html, block.end(), block.end() + 600)
        if m:
            return int(m.group(1))
    m = BATTERY_RE.search(html)  # fallback: first battery figure on the page
    return int(m.group(1)) if m else None


def battery_of(product):
    """Fetch the product page and read its battery %. None if it cannot be read."""
    url = f"{BASE}/products/{product['handle']}"
    try:
        value = parse_battery(http_get(url, accept="text/html"))
    except Exception as exc:
        print(f"Battery lookup failed for {product['title']}: {exc}")
        return None
    print(f"Battery for {product['title']}: {value if value is not None else 'not found'}")
    return value


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


def split_title(title):
    return [p.strip() for p in title.split(" - ")]


def best_variant(product):
    """The cheapest in-stock variant (or the cheapest variant if none in stock)."""
    variants = product.get("variants") or [{}]
    pool = [v for v in variants if v.get("available")] or variants

    def price_key(v):
        try:
            return float(v.get("price"))
        except (TypeError, ValueError):
            return float("inf")

    return min(pool, key=price_key)


def price_of(product):
    try:
        return float(best_variant(product).get("price"))
    except (TypeError, ValueError):
        return None


def filter_reason(product):
    """Return None if the phone matches your filters, else why it does not.

    If storage or colour cannot be read from the title, that check is skipped,
    so an oddly named phone is never silently dropped.
    """
    parts = split_title(product["title"])
    model = parts[0]
    storage = parts[1] if len(parts) > 1 else ""
    colour = parts[2] if len(parts) > 2 else ""

    limit = MODEL_LIMITS.get(model.casefold())
    price = price_of(product)
    if limit is not None and price is not None and price > limit:
        return f"price {inr(price)} is over your limit of {inr(limit)}"

    looks_like_storage = re.fullmatch(r"\d+\s*(GB|TB)", storage, re.IGNORECASE)
    if STORAGE_SET and looks_like_storage:
        if re.sub(r"\s+", "", storage).upper() not in STORAGE_SET:
            return f"storage {storage} is not in your list"

    looks_like_colour = colour and not re.fullmatch(r"pre-?owned", colour, re.IGNORECASE)
    if COLOUR_SET and looks_like_colour and colour.casefold() not in COLOUR_SET:
        return f"colour {colour} is not in your list"
    return None


def describe(product, battery=None):
    parts = split_title(product["title"])
    if parts and re.fullmatch(r"pre-?owned", parts[-1], re.IGNORECASE):
        parts = parts[:-1]
    variant = best_variant(product)
    price = variant.get("price")
    compare = variant.get("compare_at_price")
    line = f"• {' · '.join(parts)} — {inr(price)}"
    try:
        if compare and float(compare) > float(price):
            line += f" (was {inr(compare)})"
    except (TypeError, ValueError):
        pass
    if MIN_BATTERY:
        line += f" · Battery {battery}%" if battery is not None else " · Battery ? (check page)"
    line += f"\n{BASE}/products/{product['handle']}"
    return line


def battery_reason(battery):
    """None if the battery is fine (or unknown, so a phone is never missed)."""
    if MIN_BATTERY and battery is not None and battery < MIN_BATTERY:
        return f"battery {battery}% is below {MIN_BATTERY}%"
    return None


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


def notify_new(products, batteries):
    """products must already be sorted cheapest first."""
    chunks = [
        products[i : i + ITEMS_PER_MESSAGE]
        for i in range(0, len(products), ITEMS_PER_MESSAGE)
    ]
    count = len(products)
    for index, chunk in enumerate(chunks):
        header = ""
        if index == 0:
            header = (
                f"New on Maple Store: {count} phone{'s' if count != 1 else ''}"
                f" (cheapest first)\n\n"
            )
        body = "\n\n".join(describe(p, batteries.get(p["id"])) for p in chunk)
        send_message(header + body)
        if index < len(chunks) - 1:
            time.sleep(2)  # stay well inside Telegram's rate limits


def load_seen():
    if not STATE_FILE.exists():
        return None
    return set(json.loads(STATE_FILE.read_text()))


def save_seen(ids):
    STATE_FILE.write_text(json.dumps(sorted(ids)) + "\n")


def run_test(found):
    """Send one real, currently available matching phone (or a plain OK)."""
    candidates = [
        p for p in found.values() if is_available(p) and filter_reason(p) is None
    ]
    candidates.sort(key=lambda p: price_of(p) or float("inf"))
    chosen, chosen_battery = None, None
    for p in candidates[:10]:  # look at the 10 cheapest at most
        battery = battery_of(p) if MIN_BATTERY else None
        time.sleep(1)
        if battery_reason(battery) is None:
            chosen, chosen_battery = p, battery
            break
    if chosen:
        send_message(
            "TEST message (this phone is not new, nothing was changed):\n\n"
            + describe(chosen, chosen_battery)
        )
    else:
        send_message(
            "TEST message: Telegram works, but none of the cheapest in-stock "
            "phones match your filters right now."
        )
    print(f"Test message sent. {len(candidates)} in-stock phones match the basic filters.")


def main():
    found = {}
    for handle in COLLECTIONS:
        for product in fetch_collection(handle):
            if TITLE_RE.match(product.get("title", "")):
                found[product["id"]] = product
        time.sleep(1)

    if os.environ.get("SEND_TEST", "").strip().lower() == "true":
        run_test(found)
        return 0

    seen = load_seen()
    all_ids = set(found)

    if seen is None:
        # First run: remember what is already listed so we do not send an
        # alert for every existing phone.
        save_seen(all_ids)
        send_message(
            f"Maple alert is on. Tracking {len(all_ids)} current listings "
            f"({', '.join(MODEL_MAX_PRICE)}). You will be messaged when new "
            f"phones that match your filters appear."
        )
        print(f"Baseline saved: {len(all_ids)} listings.")
        return 0

    new_in_stock = [
        p for pid, p in found.items() if pid not in seen and is_available(p)
    ]
    matching = []
    for p in new_in_stock:
        reason = filter_reason(p)
        if reason is None:
            matching.append(p)
        else:
            print(f"New but skipped: {p['title']} ({reason})")

    # Battery is only on each phone's own page, so look it up for the few
    # new phones that already passed every other filter.
    batteries = {}
    if MIN_BATTERY and matching:
        kept = []
        for p in matching:
            batteries[p["id"]] = battery_of(p)
            time.sleep(1)
            reason = battery_reason(batteries[p["id"]])
            if reason is None:
                kept.append(p)
            else:
                print(f"New but skipped: {p['title']} ({reason})")
        matching = kept
    matching.sort(key=lambda p: price_of(p) or float("inf"))

    print(
        f"{len(found)} tracked listings, {len(new_in_stock)} new in stock, "
        f"{len(matching)} match your filters."
    )

    if matching:
        notify_new(matching, batteries)  # raises on failure, so state is not saved
        print(f"Sent alert for {len(matching)} new phones.")

    if not all_ids <= seen:
        save_seen(seen | all_ids)
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        sys.exit(1)
