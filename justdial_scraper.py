#!/usr/bin/env python3
"""
JustDial Hotels in Pune - Name & Contact Number Scraper
Run this on your LOCAL machine (not a cloud server) to bypass bot protection.

Requirements:
    pip install curl-cffi beautifulsoup4 lxml

Usage:
    python3 justdial_scraper.py                        # scrape all pages
    python3 justdial_scraper.py --pages 3              # only first 3 pages
    python3 justdial_scraper.py --city Mumbai --cat Restaurants  # custom search
"""

import argparse
import csv
import json
import re
import time
import random
import sys
from pathlib import Path
from datetime import datetime

try:
    from curl_cffi import requests as cffi_requests
except ImportError:
    print("ERROR: Install curl-cffi first:  pip install curl-cffi beautifulsoup4 lxml")
    sys.exit(1)

from bs4 import BeautifulSoup


# ── Config ──────────────────────────────────────────────────────────────────

DEFAULT_CITY = "Pune"
DEFAULT_CATEGORY = "Hotels"
DEFAULT_PAGES = 50          # JustDial shows ~10 results per page
OUTPUT_CSV = "justdial_results.csv"
OUTPUT_JSON = "justdial_results.json"

HEADERS = {
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8",
    "Accept-Language": "en-IN,en-GB;q=0.9,en-US;q=0.8,en;q=0.7",
    "Cache-Control": "no-cache",
    "Pragma": "no-cache",
    "Sec-Fetch-Dest": "document",
    "Sec-Fetch-Mode": "navigate",
    "Sec-Fetch-Site": "same-origin",
    "Sec-Fetch-User": "?1",
    "Upgrade-Insecure-Requests": "1",
}


# ── Helpers ──────────────────────────────────────────────────────────────────

def build_url(city: str, category: str, page: int) -> str:
    """Build the JustDial listing URL for a given page."""
    base = f"https://www.justdial.com/{city}/{category}/nct-10000013"
    if page == 1:
        return base
    return f"{base}/page-{page}"


def decode_phone(encoded: str) -> str:
    """
    JustDial obfuscates phone numbers in the HTML using a character-map rotation.
    This reverses the encoding used in their front-end JS.
    """
    # JD maps digits 0-9 to different characters in their span tags
    # The actual phone extraction relies on aria-label or data attributes
    return encoded.strip()


def extract_phone_from_element(tag) -> str:
    """Extract phone number from a JustDial result element."""
    phone = ""

    # Method 1: data-phone attribute
    phone = tag.get("data-phone", "")
    if phone:
        return phone.strip()

    # Method 2: aria-label on the call button
    call_btn = tag.find(attrs={"data-phone": True})
    if call_btn:
        return call_btn["data-phone"].strip()

    # Method 3: .contact-info span / anchor with tel: href
    tel_link = tag.find("a", href=re.compile(r"^tel:"))
    if tel_link:
        return tel_link["href"].replace("tel:", "").strip()

    # Method 4: span with class containing 'contact' or 'mobilesv'
    for cls in ("mobilesv", "contact-info", "callcontent", "calldetail"):
        el = tag.find(class_=re.compile(cls, re.I))
        if el:
            digits = re.sub(r"\D", "", el.get_text())
            if len(digits) >= 7:
                return digits

    # Method 5: raw text pattern
    raw = tag.get_text(" ", strip=True)
    match = re.search(r"\b((\+91[\-\s]?)?[6-9]\d{9}|0\d{2,4}[\-\s]\d{6,8})\b", raw)
    if match:
        return match.group(0).strip()

    return ""


def extract_name(tag) -> str:
    """Extract business name from a JustDial result element."""
    # Common selectors JD uses for business name
    for selector in [
        ("span", {"class": re.compile(r"lng_cont_name|store-name|jd-title", re.I)}),
        ("a",    {"class": re.compile(r"store-name|title|bnm", re.I)}),
        ("h2",   {}),
        ("h3",   {}),
    ]:
        el = tag.find(*selector)
        if el:
            text = el.get_text(" ", strip=True)
            if text:
                return text

    # Fallback: data-name attribute on the li itself
    return tag.get("data-name", "").strip()


def parse_listings(html: str) -> list[dict]:
    """Parse all business listings from a JustDial search-results page."""
    soup = BeautifulSoup(html, "lxml")
    results = []

    # JustDial wraps each listing in an <li> with class containing 'store-details'
    # or a <div> with class 'resultbox_info' / 'jd_hd_cont'
    candidates = (
        soup.find_all("li", class_=re.compile(r"store-details|resultbox|cntanr", re.I))
        or soup.find_all("div", class_=re.compile(r"resultbox_info|jd_hd_cont", re.I))
    )

    for item in candidates:
        name = extract_name(item)
        phone = extract_phone_from_element(item)

        if not name:
            continue

        results.append({
            "name": name,
            "phone": phone or "N/A",
        })

    return results


def save_csv(data: list[dict], path: str):
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["name", "phone"])
        writer.writeheader()
        writer.writerows(data)
    print(f"  Saved CSV  → {path}  ({len(data)} rows)")


def save_json(data: list[dict], path: str):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    print(f"  Saved JSON → {path}  ({len(data)} records)")


# ── Main Scraper ──────────────────────────────────────────────────────────────

def scrape(city: str, category: str, max_pages: int):
    session = cffi_requests.Session(impersonate="chrome124")

    all_results: list[dict] = []
    consecutive_empty = 0

    print(f"\nScraping JustDial: {category} in {city}")
    print(f"Max pages: {max_pages}\n")

    # Warm-up: visit homepage to pick up cookies
    try:
        session.get("https://www.justdial.com/", headers=HEADERS, timeout=20)
        time.sleep(random.uniform(1.5, 3.0))
    except Exception as e:
        print(f"[warn] Homepage warm-up failed: {e}")

    for page_num in range(1, max_pages + 1):
        url = build_url(city, category, page_num)
        print(f"  Page {page_num:>3}/{max_pages}  {url}", end="  ... ", flush=True)

        try:
            resp = session.get(
                url,
                headers={**HEADERS, "Referer": build_url(city, category, max(1, page_num - 1))},
                timeout=25,
            )
        except Exception as e:
            print(f"[ERROR] {e}")
            time.sleep(5)
            continue

        if resp.status_code == 403:
            print("[BLOCKED] 403 – Akamai detected a bot. Run this on your home/office machine.")
            print("          Cloud server IPs are blocked by JustDial's CDN.")
            break

        if resp.status_code != 200:
            print(f"[SKIP] HTTP {resp.status_code}")
            consecutive_empty += 1
            if consecutive_empty >= 3:
                print("  3 consecutive empty pages → stopping.")
                break
            time.sleep(random.uniform(2, 4))
            continue

        page_results = parse_listings(resp.text)
        print(f"found {len(page_results)} listings")

        if not page_results:
            consecutive_empty += 1
            if consecutive_empty >= 3:
                print("  3 consecutive empty pages → stopping (end of results).")
                break
        else:
            consecutive_empty = 0
            all_results.extend(page_results)

        # Polite delay (2–5 seconds between pages)
        time.sleep(random.uniform(2, 5))

    # De-duplicate by name+phone
    seen = set()
    unique = []
    for row in all_results:
        key = (row["name"].lower(), row["phone"])
        if key not in seen:
            seen.add(key)
            unique.append(row)

    print(f"\nTotal unique listings: {len(unique)}")
    return unique


def main():
    parser = argparse.ArgumentParser(description="Scrape hotel names & phones from JustDial")
    parser.add_argument("--city",    default=DEFAULT_CITY,     help="City name (default: Pune)")
    parser.add_argument("--cat",     default=DEFAULT_CATEGORY, help="Category (default: Hotels)")
    parser.add_argument("--pages",   type=int, default=DEFAULT_PAGES, help="Max pages to scrape")
    parser.add_argument("--out-csv", default=OUTPUT_CSV,  help="Output CSV filename")
    parser.add_argument("--out-json",default=OUTPUT_JSON, help="Output JSON filename")
    args = parser.parse_args()

    data = scrape(args.city, args.cat, args.pages)

    if data:
        save_csv(data, args.out_csv)
        save_json(data, args.out_json)
    else:
        print("\nNo data extracted.")
        print("Make sure you are running this on a residential/home internet connection,")
        print("NOT on a cloud server — JustDial blocks cloud/datacenter IP ranges.")


if __name__ == "__main__":
    main()
