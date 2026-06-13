#!/usr/bin/env python3
"""
Polls Apple's Certified Refurbished store iPhone 15 Pro (128G/256G) & 15 Pro Max (256G) at $860 or less.
On a new hit, posts to Slack via webhook. Dedupes via state.json.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from pathlib import Path

PRICE_CAP = int(os.environ.get("PRICE_CAP", "860"))
STATE_PATH = Path("state.json")
WECOM_WEBHOOK_URL = "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=8179298e-2dd2-4d1a-96bb-cfb7753fe011"
MENTION_ALL = os.environ.get("MENTION_ALL", "0") == "0"

UA = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Safari/605.1.15"
)
HEADERS = {
    "User-Agent": UA,
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}


def fetch(url: str) -> str:
    req = urllib.request.Request(url, headers=HEADERS)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
            print(f"[fetch] {url} -> {resp.status} ({len(body)} bytes)", file=sys.stderr)
            return body
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        print(f"[fetch] {url} -> {e}", file=sys.stderr)
        return ""


def check_apple_refurb() -> list[dict]:
    url = "https://www.apple.com/shop/refurbished/iphone/iphone-15-pro-iphone-15-pro-max"
    html = fetch(url)
    if not html:
        return []
    
    pro_count = len(re.findall(r"iPhone 15 Pro", html, re.IGNORECASE))
    prices = sorted({p for p in re.findall(r"\$\s*([0-9][0-9,]{2,4}\.\d{2})", html)})
    print(
        f"[apple] 'iPhone 15 Pro/Max' x{pro_count}, "
        f"distinct prices: {prices[:15]}{'...' if len(prices) > 15 else ''}",
        file=sys.stderr,
    )
    
    hits = []
    pattern = re.compile(
        r"(Refurbished\s+iPhone\s+15\s+Pro(?:\s+Max)?\s+[^<]{0,100}?(?:128GB|256GB)[^<]{0,100}?)"
        r"[\s\S]{0,3000}?\$\s*([0-9][0-9,]{2,4})\.\d{2}",
        re.IGNORECASE,
    )
    
    seen = set()
    for m in pattern.finditer(html):
        title = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()
        price = int(m.group(2).replace(",", ""))
        
        if "512GB" in title or "1TB" in title:
            continue
            
        key = (title, price)
        if key in seen:
            continue
        seen.add(key)
        
        if price <= PRICE_CAP:
            hits.append(
                {
                    "retailer": "Apple Refurb",
                    "variant": title[:140],
                    "price": price,
                    "url": url,
                }
            )
    return hits


def signature(hit: dict) -> str:
    return f"{hit['retailer']}|{hit['variant']}|{hit['price']}"


def post_wecom(hit: dict) -> None:
    if not WECOM_WEBHOOK_URL or "http" not in WECOM_WEBHOOK_URL:
        print(f"[wecom] (dry-run) would post: {hit}", file=sys.stderr)
        return
    content = (
        f"⚠️ 发现目标 iPhone 翻新机！\n"
        f"型号: {hit['variant']}\n"
        f"价格: ${hit['price']} (预算上限: ${PRICE_CAP})\n"
        f"链接: {hit['url']}"
    )
    payload_dict = {
        "msgtype": "text",
        "text": {
            "content": content
        }
    }
    if MENTION_ALL:
        payload_dict["text"]["mentioned_list"] = ["@all"]

    payload = json.dumps(payload_dict).encode("utf-8")
    req = urllib.request.Request(
        WECOM_WEBHOOK_URL,
        data=payload,
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            resp.read()
            print("[wecom] alert sent successfully", file=sys.stderr)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError) as e:
        print(f"[wecom] post failed: {e}", file=sys.stderr)


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {}
    try:
        return json.loads(STATE_PATH.read_text())
    except json.JSONDecodeError:
        return {}


def save_state(state: dict) -> None:
    STATE_PATH.write_text(json.dumps(state, indent=2, sort_keys=True) + "\n")


def main() -> int:
    if os.environ.get("TEST_PING") == "1":
        print("[test] sending WeCom test ping")
        post_wecom(
            {
                "retailer": "TEST",
                "variant": "企业微信机器人连通性测试 (iPhone 15 Pro)",
                "price": 0,
                "url": "https://www.apple.com/shop/refurbished/iphone/iphone-15-pro-iphone-15-pro-max",
            }
        )
        return 0

    all_hits: list[dict] = []
    try:
        all_hits.extend(check_apple_refurb())
    except Exception as e:
        print(f"[check_apple_refurb] error: {e}", file=sys.stderr)

    print(f"hits this run: {len(all_hits)}")
    for h in all_hits:
        print(f"  - {signature(h)} -> {h['url']}")

    previous = load_state()
    current = {signature(h): h for h in all_hits}
    new_keys = set(current) - set(previous)

    for key in new_keys:
        print(f"[alert] new hit: {key}")
        post_wecom(current[key])

    save_state(current)
    return 0


if __name__ == "__main__":
    sys.exit(main())
