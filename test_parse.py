#!/usr/bin/env python3
"""
Offline parser test — feed it a saved JustDial HTML page to verify extraction.

Usage:
    # 1. In your browser: open JustDial, save page as HTML (Ctrl+S)
    # 2. Run:  python3 test_parse.py saved_page.html
"""
import sys
from pathlib import Path

from justdial_scraper import parse_listings, save_csv, save_json

if len(sys.argv) < 2:
    print("Usage: python3 test_parse.py <saved_justdial_page.html>")
    sys.exit(1)

html = Path(sys.argv[1]).read_text(encoding="utf-8", errors="ignore")
results = parse_listings(html)

print(f"Extracted {len(results)} listings:\n")
for i, r in enumerate(results, 1):
    print(f"  {i:>3}. {r['name']:<50}  {r['phone']}")

if results:
    save_csv(results, "parsed_results.csv")
    save_json(results, "parsed_results.json")
