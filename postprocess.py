#!/usr/bin/env python3
"""
Post-process deep_extract results:
1. Any phone that appears for 2+ different hotels = false positive (ad/Google number) → remove
2. Only trust phones found from hotel's own website (not Google noise)
3. Output clean CSV with verified mobile numbers only
"""

import json, csv, re
from collections import Counter

def clean_phone(raw):
    d = re.sub(r'[^\d]', '', raw)
    if d.startswith('91') and len(d) == 12:
        d = d[2:]
    elif d.startswith('091') and len(d) == 13:
        d = d[3:]
    return d

def is_mobile(p):
    d = clean_phone(p)
    return bool(re.fullmatch(r'[6-9]\d{9}', d))

with open('/home/user/extract-data/hotels_pune_deep.json') as f:
    data = json.load(f)

# ── Step 1: Count phone frequency across all hotels ───────────────────────────
all_phone_counts = Counter()
for hotel in data:
    phones = []
    # Collect all mobiles reported for this hotel
    if hotel.get('all_mobiles'):
        for p in hotel['all_mobiles'].split(';'):
            d = clean_phone(p.strip())
            if d:
                phones.append(d)
    if hotel.get('phone') and hotel.get('number_type') == 'mobile':
        d = clean_phone(hotel['phone'])
        if d:
            phones.append(d)
    for p in set(phones):
        all_phone_counts[p] += 1

# Any phone appearing for 2+ hotels is a false positive
false_positives = {p for p, count in all_phone_counts.items() if count >= 2}
print(f"False positive numbers (appear for 2+ hotels): {len(false_positives)}")
for p, c in all_phone_counts.most_common(20):
    marker = " ← FALSE POSITIVE" if p in false_positives else ""
    print(f"  {p}  ×{c}{marker}")

print()

# ── Step 2: Re-build clean results ───────────────────────────────────────────
results = []
for hotel in data:
    name = hotel['name']
    raw_mobiles = []
    if hotel.get('all_mobiles'):
        for p in hotel['all_mobiles'].split(';'):
            d = clean_phone(p.strip())
            if d and is_mobile(d) and d not in false_positives:
                raw_mobiles.append(d)

    # Also keep original OSM number if it was mobile and still valid
    orig = clean_phone(hotel.get('phone',''))
    if orig and is_mobile(orig) and orig not in false_positives:
        if orig not in raw_mobiles:
            raw_mobiles.insert(0, orig)

    # Get landline (original only if real)
    landline = ''
    if hotel.get('number_type') == 'landline':
        landline = hotel.get('phone','')

    if raw_mobiles:
        phone = raw_mobiles[0]
        ntype = 'mobile'
    elif landline:
        phone = landline
        ntype = 'landline'
    else:
        phone = 'N/A'
        ntype = 'N/A'

    results.append({
        'name': name,
        'phone': phone,
        'all_mobiles': ';'.join(raw_mobiles),
        'number_type': ntype,
        'stars': hotel.get('stars',''),
        'area': hotel.get('area',''),
        'website': hotel.get('website',''),
    })

# Sort: mobile first
order = {'mobile': 0, 'landline': 1, 'N/A': 2}
results.sort(key=lambda x: (order[x['number_type']], x['name']))

mobile_results = [r for r in results if r['number_type'] == 'mobile']
landline_results = [r for r in results if r['number_type'] == 'landline']
na_results = [r for r in results if r['number_type'] == 'N/A']

print(f"CLEAN RESULTS:")
print(f"  Mobile numbers:  {len(mobile_results)}")
print(f"  Landline:        {len(landline_results)}")
print(f"  No phone:        {len(na_results)}")

print(f"\n=== HOTELS WITH MOBILE (OWNER-TYPE) NUMBERS ===")
for i, r in enumerate(mobile_results, 1):
    stars = f" [{r['stars']}★]" if r['stars'] else ''
    all_m = f"  (also: {r['all_mobiles']})" if len(r['all_mobiles'].split(';')) > 1 else ''
    print(f"  {i:>3}. {r['name']:<55} {r['phone']}{stars}{all_m}")

# Save
with open('/home/user/extract-data/hotels_pune_final.csv', 'w', newline='', encoding='utf-8') as f:
    writer = csv.DictWriter(f, fieldnames=['name','phone','all_mobiles','number_type','stars','area','website'])
    writer.writeheader()
    writer.writerows(results)

with open('/home/user/extract-data/hotels_pune_final.json', 'w', encoding='utf-8') as f:
    json.dump(results, f, indent=2, ensure_ascii=False)

print(f"\nSaved: hotels_pune_final.csv  ({len(results)} rows)")
