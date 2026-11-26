#!/usr/bin/env python3
"""IdealDeal auto-poster — standard library only (no pip install needed).

Every run it:
  1. reads deal RSS/Atom feeds listed in bot/feeds.json
  2. finds merchant links (Amazon, Flipkart, ...) and turns them into YOUR affiliate links
  3. posts new deals to your Telegram channel
  4. updates site/deals.json so the website shows them too
"""
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FEEDS_FILE = Path(os.environ.get("FEEDS_FILE") or ROOT / "bot" / "feeds.json")
STATE_FILE = ROOT / "bot" / "state.json"
DEALS_FILE = ROOT / "site" / "deals.json"

TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()
CHAT = os.environ.get("TELEGRAM_CHAT_ID", "").strip()
AMAZON_TAG = os.environ.get("AMAZON_TAG", "").strip()
FLIPKART_AFFID = os.environ.get("FLIPKART_AFFID", "").strip()
# Generic wrapper for other stores, e.g. Cuelinks / EarnKaro style:
#   https://linksredirect.com/?cid=12345&source=linkkit&url={url}
AFFILIATE_TEMPLATE = os.environ.get("AFFILIATE_TEMPLATE", "").strip()
MAX_POSTS = int(os.environ.get("MAX_POSTS_PER_RUN", "5"))
USE_IMAGES = os.environ.get("USE_IMAGES", "1") == "1"
REQUIRE_AFFILIATE = os.environ.get("REQUIRE_AFFILIATE", "1") == "1"
DRY_RUN = os.environ.get("DRY_RUN") == "1" or not (TOKEN and CHAT)
SITE_NAME = "IdealDeal"
SITE_URL = "https://idealdeal.shop"
UA = "Mozilla/5.0 (compatible; IdealDealBot/1.0; +https://idealdeal.shop)"

MERCHANTS = {
    "amazon.in": "Amazon", "flipkart.com": "Flipkart", "myntra.com": "Myntra",
    "ajio.com": "Ajio", "nykaa.com": "Nykaa", "croma.com": "Croma",
    "tatacliq.com": "Tata CLiQ", "meesho.com": "Meesho", "reliancedigital.in": "Reliance Digital",
    "boat-lifestyle.com": "boAt", "lenskart.com": "Lenskart", "firstcry.com": "FirstCry",
}
SHORT_HOSTS = ("amzn.to", "amzn.in", "a.co", "fkrt.it", "fkrt.cc", "bit.ly", "cutt.ly",
               "tinyurl.com", "t.co", "ln.run", "dl.flipkart.com", "myntr.it")
CATEGORIES = {
    "electronics": ["phone", "mobile", "laptop", "headphone", "earbud", "tws", "watch", "tv", "camera",
                    "speaker", "charger", "power bank", "ssd", "monitor", "tablet", "router", "iphone",
                    "samsung", "oneplus", "redmi", "realme", "boat", "airpod"],
    "fashion": ["shirt", "t-shirt", "tshirt", "jeans", "shoe", "sneaker", "kurta", "dress", "saree",
                "jacket", "sandal", "bag", "wallet", "sunglass", "hoodie"],
    "home": ["kitchen", "cooker", "mixer", "grinder", "bedsheet", "mattress", "fan", "cooler",
             "vacuum", "furniture", "bottle", "cookware", "iron", "heater", "geyser", "purifier"],
    "beauty": ["serum", "cream", "lipstick", "perfume", "shampoo", "makeup", "skincare", "trimmer",
               "moisturi", "sunscreen", "face wash"],
    "grocery": ["snack", "coffee", "tea", "oil", "protein", "chocolate", "rice", "dry fruit", "almond"],
    "gaming": ["ps5", "xbox", "controller", "gaming", "playstation", "nintendo", "steam"],
}


def log(*a):
    print(*a, flush=True)


def http_get(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "*/*"})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def local(tag):
    return tag.rsplit("}", 1)[-1].lower() if isinstance(tag, str) else ""


def parse_feed(data):
    root = ET.fromstring(data)
    items = []
    for el in root.iter():
        if local(el.tag) not in ("item", "entry"):
            continue
        it = {"images": []}
        for ch in el:
            name = local(ch.tag)
            text = (ch.text or "").strip()
            if name == "title" and "title" not in it:
                it["title"] = text
            elif name == "link" and "link" not in it:
                it["link"] = ch.attrib.get("href") or text
            elif name in ("guid", "id") and "id" not in it:
                it["id"] = text
            elif name in ("description", "summary", "content", "encoded") and len(text) > len(it.get("desc", "")):
                it["desc"] = text
            elif name in ("pubdate", "published", "updated") and "date" not in it:
                it["date"] = text
            elif name in ("content", "thumbnail", "enclosure") and ch.attrib.get("url"):
                typ = ch.attrib.get("type", "")
                if not typ or typ.startswith("image"):
                    it["images"].append(ch.attrib["url"])
        if it.get("title") and (it.get("link") or it.get("desc")):
            it.setdefault("id", it.get("link", it["title"]))
            it.setdefault("desc", "")
            items.append(it)
    return items


def resolve(url):
    host = urllib.parse.urlparse(url).netloc.lower()
    if not any(host == h or host.endswith("." + h) for h in SHORT_HOSTS):
        return url
    try:
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=15) as r:
            return r.geturl()
    except Exception as e:  # noqa: BLE001
        log("  resolve failed:", url, e)
        return url


def merchant_of(url):
    host = urllib.parse.urlparse(url).netloc.lower()
    for dom, name in MERCHANTS.items():
        if host == dom or host.endswith("." + dom):
            return name
    return None


def find_merchant_url(item):
    cands = [item.get("link", "")]
    cands += [html.unescape(h) for h in re.findall(r'href=["\']([^"\']+)', item.get("desc", ""))]
    for c in cands:
        if not c.startswith("http"):
            continue
        final = resolve(c)
        m = merchant_of(final)
        if m:
            return final, m
    return None, None


def canonical(url):
    p = urllib.parse.urlparse(url)
    m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", p.path)
    if m and "amazon." in p.netloc:
        return "amazon:" + m.group(1)
    return p.netloc.lower() + p.path.rstrip("/")


def monetize(url, merchant):
    """Return (affiliate_url, is_monetized)."""
    p = urllib.parse.urlparse(url)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(p.query)
         if not k.lower().startswith(("utm_", "tag", "affid", "affextparam", "ref", "linkcode"))]
    if merchant == "Amazon" and AMAZON_TAG:
        m = re.search(r"/(?:dp|gp/product)/([A-Z0-9]{10})", p.path)
        if m:
            return f"https://www.amazon.in/dp/{m.group(1)}?tag={urllib.parse.quote(AMAZON_TAG)}", True
        q.append(("tag", AMAZON_TAG))
        return urllib.parse.urlunparse(p._replace(query=urllib.parse.urlencode(q))), True
    if merchant == "Flipkart" and FLIPKART_AFFID:
        q.append(("affid", FLIPKART_AFFID))
        return urllib.parse.urlunparse(p._replace(query=urllib.parse.urlencode(q))), True
    clean = urllib.parse.urlunparse(p._replace(query=urllib.parse.urlencode(q)))
    if AFFILIATE_TEMPLATE:
        return AFFILIATE_TEMPLATE.replace("{url}", urllib.parse.quote(clean, safe="")), True
    return clean, False


def clean_title(t):
    t = html.unescape(re.sub(r"<[^>]+>", "", t)).strip()
    return re.sub(r"\s+", " ", t)[:180]


def find_price(text):
    m = re.search(r"(?:₹|Rs\.?|INR)\s?([\d,]{2,9}(?:\.\d{1,2})?)", html.unescape(text))
    if not m:
        return ""
    try:
        return "₹{:,}".format(int(float(m.group(1).replace(",", ""))))
    except ValueError:
        return ""


def find_image(item):
    for u in item["images"]:
        if u.startswith("http"):
            return u
    m = re.search(r'<img[^>]+src=["\']([^"\']+)', item.get("desc", ""))
    return html.unescape(m.group(1)) if m and m.group(1).startswith("http") else ""


def categorize(text):
    t = text.lower()
    for cat, words in CATEGORIES.items():
        if any(w in t for w in words):
            return cat
    return "general"


def tg(method, payload):
    req = urllib.request.Request(
        f"https://api.telegram.org/bot{TOKEN}/{method}",
        data=json.dumps(payload).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        body = e.read().decode(errors="ignore")
        if e.code == 429:
            wait = 5
            try:
                wait = json.loads(body)["parameters"]["retry_after"] + 1
            except Exception:  # noqa: BLE001
                pass
            log(f"  rate limited, sleeping {wait}s")
            time.sleep(wait)
            return tg(method, payload)
        raise RuntimeError(f"Telegram {method} failed: {e.code} {body[:200]}")


def post_to_telegram(deal):
    lines = [f"🔥 <b>{html.escape(deal['title'])}</b>", ""]
    if deal["price"]:
        lines.append(f"💰 <b>{html.escape(deal['price'])}</b>")
    lines.append(f"🛒 {html.escape(deal['source'])}")
    lines += ["", f"<i>#ad · {SITE_NAME} · {SITE_URL.replace('https://', '')}</i>"]
    text = "\n".join(lines)
    markup = {"inline_keyboard": [[{"text": "🛍 Grab this deal", "url": deal["link"]}]]}
    base = {"chat_id": CHAT, "parse_mode": "HTML", "reply_markup": markup}
    if deal["image"] and USE_IMAGES:
        try:
            tg("sendPhoto", {**base, "photo": deal["image"], "caption": text[:1000]})
            return
        except RuntimeError as e:
            log("  photo failed, sending text only:", e)
    tg("sendMessage", {**base, "text": text, "disable_web_page_preview": True})


def load_json(path, default):
    try:
        return json.loads(path.read_text())
    except Exception:  # noqa: BLE001
        return default


def main():
    feeds = load_json(FEEDS_FILE, [])
    state = load_json(STATE_FILE, {"seen": []})
    doc = load_json(DEALS_FILE, {"total_tracked": 0, "deals": []})
    seen = set(state["seen"])
    first_run = not seen
    log(f"Mode: {'DRY RUN (not posting)' if DRY_RUN else 'LIVE'} | feeds: {len(feeds)} | first_run: {first_run}")

    candidates = []
    for f in feeds:
        try:
            items = parse_feed(http_get(f["url"]))
        except Exception as e:  # noqa: BLE001
            log(f"[{f.get('name')}] feed error: {e}")
            continue
        log(f"[{f.get('name')}] {len(items)} items")
        for it in items[:40]:
            key = hashlib.sha1(it["id"].encode()).hexdigest()[:16]
            if key not in seen:
                candidates.append((key, it))

    if first_run:  # don't flood the channel on day one
        for key, _ in candidates[3:]:
            seen.add(key)
        candidates = candidates[:3]

    posted = []
    for key, it in candidates:
        seen.add(key)
        if len(posted) >= MAX_POSTS:
            continue
        title = clean_title(it["title"])
        if re.search(r"\b(expired|sold out|out of stock)\b", title, re.I):
            continue
        url, merchant = find_merchant_url(it)
        if not url:
            continue
        canon = canonical(url)
        if canon in seen:
            continue
        link, monetized = monetize(url, merchant)
        if REQUIRE_AFFILIATE and not monetized:
            log(f"  skip (no affiliate setup for {merchant}): {title[:60]}")
            continue
        seen.add(canon)
        blob = title + " " + it["desc"]
        posted.append({
            "title": title, "link": link, "image": find_image(it) if USE_IMAGES else "",
            "price": find_price(blob), "source": merchant, "category": categorize(title),
            "posted_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        })

    sent = []
    for deal in reversed(posted):  # oldest first, so the channel reads chronologically
        log("->", deal["title"][:70], "|", deal["price"], "|", deal["source"])
        if not DRY_RUN:
            try:
                post_to_telegram(deal)
                time.sleep(3)
            except Exception as e:  # noqa: BLE001
                log("  post failed:", e)
                continue
        sent.append(deal)

    if sent:
        doc["deals"] = (sent[::-1] + doc.get("deals", []))[:200]
        doc["total_tracked"] = doc.get("total_tracked", 0) + len(sent)
        DEALS_FILE.parent.mkdir(parents=True, exist_ok=True)
        DEALS_FILE.write_text(json.dumps(doc, ensure_ascii=False, indent=1))
    state["seen"] = list(seen)[-4000:]
    STATE_FILE.write_text(json.dumps(state))
    log(f"Done. {len(sent)} deal(s) {'previewed' if DRY_RUN else 'posted'}.")


if __name__ == "__main__":
    sys.exit(main())
