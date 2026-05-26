#!/usr/bin/env python3
"""
Deep phone extractor — visits hotel websites, decodes every encoding trick:
  - Schema.org JSON-LD  - JavaScript variables  - data-* attributes
  - tel: href links     - CSS content           - reversed/ROT strings
  - Unicode obfuscation - HTML entities         - Google SERP snippets
"""

import requests, re, json, csv, time, html, urllib.parse, random
from bs4 import BeautifulSoup

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                  "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-IN,en;q=0.9",
})

# ── Phone patterns ────────────────────────────────────────────────────────────
# Indian mobile: 10 digits starting 6-9
MOBILE_RE = re.compile(
    r'(?<!\d)(?:\+91[\s\-\.]*)?(?:0)?([6-9]\d{9})(?!\d)'
)
# Indian landline: 02x-xxxxxxxx or 0x-xxxxxxxx
LANDLINE_RE = re.compile(
    r'(?<!\d)(?:\+91[\s\-\.]*)?'
    r'(0(?:20|21|22|11|33|40|44|80|79|484|471|422|452|413|416|427|431|435|436|462|464|466)\d{6,8})'
    r'(?!\d)'
)
PHONE_ANY = re.compile(
    r'(?:\+91[\s\-\.]?)?(?:0)?[6-9]\d{9}|'
    r'(?:\+91[\s\-\.]?)?0\d{2,4}[\s\-\.]\d{6,8}'
)


def clean_phone(raw: str) -> str:
    d = re.sub(r'[^\d+]', '', raw)
    if d.startswith('+91') and len(d) > 3:
        d = d[3:]
    elif d.startswith('91') and len(d) == 12:
        d = d[2:]
    elif d.startswith('091') and len(d) == 13:
        d = d[3:]
    return d


def is_mobile(phone: str) -> bool:
    digits = clean_phone(phone)
    return bool(re.fullmatch(r'[6-9]\d{9}', digits))


def extract_all_phones(text: str) -> list[str]:
    found = set()
    for m in PHONE_ANY.finditer(text):
        raw = m.group(0)
        d = clean_phone(raw)
        if len(d) >= 7:
            found.add(d)
    return list(found)


# ── Decoding tricks ───────────────────────────────────────────────────────────

def decode_html_entities(text: str) -> str:
    return html.unescape(text)


def decode_reversed(text: str) -> str:
    """Some sites reverse phone strings in HTML."""
    phones = []
    for segment in re.findall(r'[\d\s\-\+\.]{7,20}', text[::-1]):
        cleaned = re.sub(r'\D', '', segment)
        if len(cleaned) >= 7:
            phones.append(cleaned)
    return ' '.join(phones)


def decode_unicode_numbers(text: str) -> str:
    """Convert Unicode fullwidth digits ０-９ and other Unicode digits to ASCII."""
    result = []
    for ch in text:
        cp = ord(ch)
        # Fullwidth digits: ０ (0xFF10) to ９ (0xFF19)
        if 0xFF10 <= cp <= 0xFF19:
            result.append(str(cp - 0xFF10))
        # Arabic-Indic digits: ٠ (0x0660) to ٩ (0x0669)
        elif 0x0660 <= cp <= 0x0669:
            result.append(str(cp - 0x0660))
        # Devanagari digits: ० (0x0966) to ९ (0x096F)
        elif 0x0966 <= cp <= 0x096F:
            result.append(str(cp - 0x0966))
        else:
            result.append(ch)
    return ''.join(result)


def extract_from_jsonld(soup) -> list[str]:
    """Extract phones from Schema.org JSON-LD blocks."""
    phones = []
    for tag in soup.find_all('script', type='application/ld+json'):
        try:
            data = json.loads(tag.string or '')
            text = json.dumps(data)
            phones += extract_all_phones(text)
            # Also look for telephone field directly
            for field in ['telephone', 'phone', 'faxNumber', 'contactPoint']:
                val = data.get(field, '')
                if isinstance(val, str):
                    phones += extract_all_phones(val)
                elif isinstance(val, list):
                    for v in val:
                        if isinstance(v, str):
                            phones += extract_all_phones(v)
                        elif isinstance(v, dict):
                            phones += extract_all_phones(json.dumps(v))
        except Exception:
            pass
    return phones


def extract_from_js(html_text: str) -> list[str]:
    """Extract phone numbers embedded in JavaScript variables/strings."""
    phones = []
    # Look for JS string assignments that contain phone-like content
    js_patterns = [
        r'(?:phone|mobile|contact|tel|number|whatsapp|call)["\'\s]*[:=]["\'\s]*([+\d\s\-\.]{7,20})',
        r'["\']([+\d\s\-\.]{10,18})["\']',
        r'data-(?:phone|mobile|tel|contact|number)\s*=\s*["\']([^"\']{7,20})["\']',
    ]
    for pat in js_patterns:
        for m in re.finditer(pat, html_text, re.IGNORECASE):
            candidate = m.group(1).strip()
            phones += extract_all_phones(candidate)
    return phones


def extract_from_data_attrs(soup) -> list[str]:
    """Extract from data-phone, data-mobile, data-contact etc."""
    phones = []
    attrs = ['data-phone', 'data-mobile', 'data-tel', 'data-contact',
             'data-number', 'data-whatsapp', 'data-call']
    for attr in attrs:
        for tag in soup.find_all(attrs={attr: True}):
            phones += extract_all_phones(tag[attr])
    return phones


def extract_from_tel_links(soup) -> list[str]:
    """Extract from <a href="tel:...">"""
    phones = []
    for tag in soup.find_all('a', href=re.compile(r'^tel:', re.I)):
        raw = tag['href'].replace('tel:', '').replace('Tel:', '')
        phones += extract_all_phones(raw)
    return phones


def extract_from_meta(soup) -> list[str]:
    """Extract from meta tags."""
    phones = []
    for tag in soup.find_all('meta'):
        content = tag.get('content', '')
        name = tag.get('name', '') + tag.get('property', '')
        if any(k in name.lower() for k in ['phone','mobile','contact','tel']):
            phones += extract_all_phones(content)
        elif content:
            phones += extract_all_phones(content)
    return phones


def decode_css_hidden(html_text: str) -> list[str]:
    """Some sites hide numbers using CSS direction:rtl or unicode-bidi."""
    phones = []
    # Look for RTL-reversed number strings
    rtl_segments = re.findall(
        r'direction\s*:\s*rtl[^>]*>([^<]{5,25})<',
        html_text, re.IGNORECASE
    )
    for seg in rtl_segments:
        phones += extract_all_phones(seg[::-1])
    return phones


def extract_phones_from_page(url: str, html_text: str) -> list[str]:
    """Master extractor — runs all decode strategies."""
    all_phones = []
    soup = BeautifulSoup(html_text, 'lxml')

    # Decode HTML entities first
    decoded_text = decode_html_entities(html_text)
    # Convert Unicode digits
    decoded_text = decode_unicode_numbers(decoded_text)

    all_phones += extract_from_tel_links(soup)
    all_phones += extract_from_jsonld(soup)
    all_phones += extract_from_data_attrs(soup)
    all_phones += extract_from_meta(soup)
    all_phones += extract_from_js(decoded_text)
    all_phones += decode_css_hidden(decoded_text)
    all_phones += extract_all_phones(decoded_text)

    # Reversed text trick
    for p in extract_all_phones(decode_reversed(decoded_text)):
        all_phones.append(p)

    # De-dup and normalize
    seen = set()
    result = []
    for p in all_phones:
        d = clean_phone(p)
        if len(d) >= 7 and d not in seen:
            seen.add(d)
            result.append(d)

    return result


# ── Website fetcher ───────────────────────────────────────────────────────────

def fetch(url: str, timeout=15) -> str | None:
    try:
        r = SESSION.get(url, timeout=timeout, allow_redirects=True)
        if r.status_code == 200:
            return r.text
    except Exception:
        pass
    return None


def find_contact_page(base_url: str, html_text: str) -> str | None:
    """Look for a Contact Us page link."""
    soup = BeautifulSoup(html_text, 'lxml')
    for a in soup.find_all('a', href=True):
        href = a['href'].lower()
        text = a.get_text().lower()
        if any(k in href or k in text for k in ['contact', 'reach', 'touch', 'enquiry']):
            full = urllib.parse.urljoin(base_url, a['href'])
            if full.startswith('http'):
                return full
    return None


# ── Google search for hotel website ──────────────────────────────────────────

def google_search_website(hotel_name: str) -> str | None:
    """Search Google for the hotel's official website."""
    query = f'{hotel_name} Pune official website contact'
    try:
        r = SESSION.get(
            'https://www.google.com/search',
            params={'q': query, 'num': 5},
            timeout=10
        )
        if r.status_code != 200:
            return None
        soup = BeautifulSoup(r.text, 'lxml')
        # First organic result URL
        for a in soup.find_all('a', href=True):
            href = a['href']
            if href.startswith('/url?q='):
                real = urllib.parse.unquote(href.split('/url?q=')[1].split('&')[0])
                if real.startswith('http') and 'google' not in real:
                    return real
    except Exception:
        pass
    return None


def google_search_phone(hotel_name: str) -> list[str]:
    """Get phone numbers from Google search snippet for this hotel."""
    query = f'{hotel_name} Pune contact phone number'
    phones = []
    try:
        r = SESSION.get('https://www.google.com/search',
                        params={'q': query, 'num': 3}, timeout=10)
        if r.status_code != 200:
            return phones
        text = decode_unicode_numbers(decode_html_entities(r.text))
        phones = extract_all_phones(text)
        # Filter noise: only plausible Indian numbers
        phones = [p for p in phones if len(clean_phone(p)) in (10, 11, 12)]
    except Exception:
        pass
    return phones


# ── Main ──────────────────────────────────────────────────────────────────────

def scrape_hotel(hotel: dict) -> dict:
    name = hotel['name']
    result = dict(hotel)
    found_mobiles = []
    found_all = []
    sources_tried = []

    website = hotel.get('website', '').strip()

    # 1. Visit the hotel's own website
    if website:
        sources_tried.append(f'website:{website}')
        html = fetch(website)
        if html:
            phones = extract_phones_from_page(website, html)
            found_all += phones

            # Also try the Contact Us page
            contact_url = find_contact_page(website, html)
            if contact_url and contact_url != website:
                time.sleep(0.8)
                sources_tried.append(f'contact_page:{contact_url}')
                contact_html = fetch(contact_url)
                if contact_html:
                    found_all += extract_phones_from_page(contact_url, contact_html)

    # 2. Google search for phone in SERP snippet
    time.sleep(random.uniform(1.5, 3.0))
    sources_tried.append('google_snippet')
    found_all += google_search_phone(name)

    # 3. If no website found yet, try Google to find one
    if not website:
        time.sleep(random.uniform(1.5, 2.5))
        found_site = google_search_website(name)
        if found_site:
            sources_tried.append(f'google_found_site:{found_site}')
            html = fetch(found_site)
            if html:
                found_all += extract_phones_from_page(found_site, html)
                result['website'] = found_site

    # Normalize, de-dup, classify
    seen = set()
    mobiles = []
    landlines = []
    for p in found_all:
        d = clean_phone(p)
        if d in seen or len(d) < 7:
            continue
        seen.add(d)
        if is_mobile(d):
            mobiles.append(d)
        else:
            landlines.append(d)

    found_mobiles = mobiles

    if found_mobiles:
        result['phone'] = found_mobiles[0]
        result['all_mobiles'] = ';'.join(found_mobiles)
        result['number_type'] = 'mobile'
    elif landlines:
        result['phone'] = landlines[0]
        result['all_mobiles'] = ''
        result['number_type'] = 'landline'

    result['all_mobiles'] = ';'.join(found_mobiles) if found_mobiles else ''
    result['sources'] = '|'.join(sources_tried)

    label = f"[{len(found_mobiles)} mobile, {len(landlines)} landline]"
    status = "MOBILE FOUND" if found_mobiles else ("landline" if landlines else "none")
    print(f"  {'OK' if found_mobiles else '--'}  {name:<50} {status}  {result.get('phone','')}")

    return result


def main():
    with open('/home/user/extract-data/hotels_pune.json') as f:
        hotels = json.load(f)

    print(f"Processing {len(hotels)} hotels...\n")
    results = []
    for i, hotel in enumerate(hotels, 1):
        print(f"[{i:>3}/{len(hotels)}]", end='  ')
        r = scrape_hotel(hotel)
        results.append(r)
        time.sleep(random.uniform(1.0, 2.5))

    # Summary
    mobiles = [r for r in results if r.get('number_type') == 'mobile']
    print(f"\n{'='*60}")
    print(f"Hotels with mobile numbers: {len(mobiles)}")
    print(f"{'='*60}")
    for r in mobiles:
        print(f"  {r['name']:<55} {r['all_mobiles']}")

    # Save
    fields = ['name','phone','all_mobiles','number_type','stars','area','website','sources']
    with open('/home/user/extract-data/hotels_pune_deep.csv', 'w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(results)

    with open('/home/user/extract-data/hotels_pune_deep.json', 'w', encoding='utf-8') as f:
        json.dump(results, f, indent=2, ensure_ascii=False)

    print(f"\nSaved hotels_pune_deep.csv and hotels_pune_deep.json")


if __name__ == '__main__':
    main()
