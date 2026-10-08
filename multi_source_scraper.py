#!/usr/bin/env python3
"""
multi_source_scraper.py

Official Greek primary-source on-duty pharmacy crawler.
Completely replaces the third-party pharmafinder.app proxy by extracting real-time
duty shifts directly from official Greek pharmaceutical syndicates:
  1. ΦΣΑ (fsa-efimeries.gr) for Attica (~4,130 pharmacies)
  2. ITeQ Network (*.efhmeries.gr) for regional prefectures

Generates 1-to-1 drop-in replacement artifacts:
  - data/duties_raw.json (consumed by package_dataset.py)
  - data/duties_multi_source.json (detailed primary metadata)
  - Updates data/pharmacies_master.json (self-healing master catalog)
"""

from __future__ import annotations

import base64
import html as html_lib
import json
import math
import os
import re
import ssl
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
import urllib.request
import urllib.error

sys.stdout.reconfigure(encoding="utf-8")

SCRIPT_DIR = Path(r"d:\Projects\RN\github-published\pharmafinder-scraper")
DATA_DIR = SCRIPT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

MASTER_FILE = DATA_DIR / "pharmacies_master.json"
DUTIES_RAW_FILE = DATA_DIR / "duties_raw.json"
OUTPUT_MULTI_FILE = DATA_DIR / "duties_multi_source.json"

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "el-GR,el;q=0.9,en;q=0.8",
}

# Regional syndicates ordered by population / pharmacy density
REGIONAL_PREFECTURES = [
    "herakleion", "korinthia", "larisa", "messinia", "chania", 
    "argolida", "lakonia", "pieria", "fthiotida", "evia", 
    "imathia", "pella", "lasithi", "trikala", "magnesia",
    "kozani", "kavala", "drama", "xanthi", "evros", 
    "ioannina", "arta", "preveza", "thesprotia", "karditsa", 
    "karpenisi", "zakynthos", "samos", "ileia", "arkadia"
]


def haversine_m(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Computes great-circle distance between two GPS points in meters."""
    R = 6371000
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlambda = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlambda / 2) ** 2
    return 2 * R * math.atan2(math.sqrt(a), math.sqrt(1 - a))


def normalize_greek(text: str) -> str:
    """Strips Greek diacritics and non-alphanumeric chars for token matching."""
    text = text.upper()
    accents = {
        'Ά': 'Α', 'Έ': 'Ε', 'Ή': 'Η', 'Ί': 'Ι', 'Ϊ': 'Ι', 
        'Ό': 'Ο', 'Ύ': 'Υ', 'Ϋ': 'Υ', 'Ώ': 'Ω'
    }
    for a, b in accents.items():
        text = text.replace(a, b)
    return re.sub(r'[^Α-Ω0-9\s]', ' ', text)


def clean_phone(phone_raw: str) -> str:
    """Extracts 10-digit Greek landline (2xxx) or mobile (69xxx)."""
    digits = re.sub(r'\D', '', phone_raw)
    if len(digits) == 10 and digits.startswith(('2', '69')):
        return digits
    return ""


# ─────────────────────────────────────────────────────────────
# SOURCE 1: ΦΣΑ ATTICA (fsa-efimeries.gr)
# ─────────────────────────────────────────────────────────────

def scrape_fsa_attica() -> list[dict]:
    """Scrapes on-duty pharmacies across Attica from official fsa-efimeries.gr."""
    url = "https://fsa-efimeries.gr/Home/FilteredHomeResults"
    print("[*] [1/2] Querying official ΦΣΑ Attica (fsa-efimeries.gr)...")
    
    req = urllib.request.Request(
        url,
        headers={**HEADERS, "HX-Request": "true"}
    )
    
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=20) as resp:
            html_text = resp.read().decode("utf-8", errors="ignore")
    except Exception as e:
        print(f"[-] FSA Attica fetch error: {e}")
        return []

    marker_pattern = r'L\.marker\(\[([0-9.]+),\s*([0-9.]+)\][^)]*\)\s*\.bindPopup\(`<a href="#(\d+)">.*?<p>(.*?)</p></a>`\)'
    markers = re.findall(marker_pattern, html_text, re.DOTALL)
    
    card_pattern = r'<div[^>]*id="(\d+)"[^>]*class="card[^"]*"[^>]*>(.*?)</div>\s*</div>\s*</div>'
    cards = dict(re.findall(card_pattern, html_text, re.DOTALL))
    
    duties = []
    for lat_s, lng_s, duty_id, popup_text in markers:
        clean_popup = html_lib.unescape(popup_text).replace("<br>", "\n")
        lines = [l.strip() for l in clean_popup.split("\n") if l.strip()]
        
        name = lines[0] if lines else "Φαρμακείο"
        address = lines[1] if len(lines) > 1 else ""
        district = lines[2] if len(lines) > 2 else "Αθήνα"
        
        phone = ""
        for line in lines:
            p = clean_phone(line)
            if p:
                phone = p
                break
                
        # Parse duty hours badge
        card_html = cards.get(duty_id, "")
        hours_match = re.search(r'badge[^>]*>\s*([0-9:.]+)\s*-\s*([0-9:.]+)\s*<', card_html)
        if hours_match:
            start_h = hours_match.group(1).replace(".", ":").zfill(5)
            end_h = hours_match.group(2).replace(".", ":").zfill(5)
            periods = [{
                "opens_at": f"{start_h}:00" if len(start_h) == 5 else start_h,
                "closes_at": f"{end_h}:00" if len(end_h) == 5 else end_h,
                "date": None
            }]
            closes_at = f"{end_h}:00" if len(end_h) == 5 else end_h
            raw_hours = f"{start_h} – {end_h}"
        else:
            periods = [{"opens_at": "08:00:00", "closes_at": "08:00:00", "date": None}]
            closes_at = "08:00:00"
            raw_hours = "Διανυκτερεύον (08:00 – 08:00)"

        duties.append({
            "source": "fsa-efimeries.gr",
            "region": "Αττική",
            "name": name,
            "address": address,
            "city": district,
            "phone": phone,
            "latitude": float(lat_s),
            "longitude": float(lng_s),
            "closes_at": closes_at,
            "periods": periods,
            "raw_hours": raw_hours
        })

    print(f"[+] ΦΣΑ Attica: Extracted {len(duties)} official on-duty pharmacies.")
    return duties


# ─────────────────────────────────────────────────────────────
# SOURCE 2: ITeQ REGIONAL NETWORK (*.efhmeries.gr)
# ─────────────────────────────────────────────────────────────

def scrape_regional_subdomain(sub: str) -> list[dict]:
    """Scrapes on-duty pharmacies for a specific prefecture with retry backoff."""
    url = f"https://{sub}.efhmeries.gr/"
    req = urllib.request.Request(url, headers=HEADERS)
    
    html_text = ""
    for attempt in range(2):
        try:
            with urllib.request.urlopen(req, context=SSL_CTX, timeout=12) as resp:
                html_text = resp.read().decode("utf-8", errors="ignore")
                break
        except Exception:
            time.sleep(1.0)
            
    if not html_text:
        return []

    # Look for cards with /Home/Details/(\d+)
    cards = re.findall(r'<div[^>]*class="[^"]*card[^"]*"[^>]*>(.*?)</div>\s*</div>', html_text, re.DOTALL)
    duties = []
    
    for c in cards:
        det_match = re.search(r'/Home/Details/(\d+)', c)
        if not det_match:
            continue

        # Extract phone from tel: link
        phone_match = re.search(r'href="tel:([0-9\s]+)"', c)
        phone = clean_phone(phone_match.group(1)) if phone_match else ""

        # Title
        title_match = re.search(r'<h[4-6][^>]*>(.*?)</h[4-6]>', c, re.DOTALL)
        name = html_lib.unescape(re.sub(r'<[^>]+>', '', title_match.group(1))).strip() if title_match else ""

        # Coordinates from Google Maps link
        lat, lng = None, None
        map_match = re.search(r'query=([0-9.]+)%2C([0-9.]+)', c)
        if map_match:
            lat = float(map_match.group(1))
            lng = float(map_match.group(2))

        # Shift hours
        shift_match = re.search(r'(ΔΙΑΝΥΚΤΕΡΕΥΕΙ[^<]+|ΕΦΗΜΕΡΕΥΕΙ[^<]+)', c, re.IGNORECASE)
        shift_text = html_lib.unescape(shift_match.group(1)).strip() if shift_match else "Εφημερεύον"

        # Address
        clean_text = re.sub(r'<[^>]+>', '\n', c)
        lines = [re.sub(r'\s+', ' ', l).strip() for l in clean_text.split('\n') if l.strip()]
        address = ""
        for line in lines:
            if any(k in line.lower() for k in ['οδός', 'οδος', 'τ.κ.', 'αρ.', 'πλατεία', '8ης']) or (re.search(r'\d+', line) and not clean_phone(line)):
                if not address and len(line) > 5 and not clean_phone(line):
                    address = line
                    break

        if name:
            duties.append({
                "source": f"{sub}.efhmeries.gr",
                "region": sub.capitalize(),
                "name": name,
                "address": address or sub.capitalize(),
                "city": sub.capitalize(),
                "phone": phone,
                "latitude": lat,
                "longitude": lng,
                "closes_at": "08:00:00",
                "periods": [{"opens_at": "08:00:00", "closes_at": "08:00:00", "date": None}],
                "raw_hours": shift_text
            })

    return duties


def scrape_all_regions() -> list[dict]:
    """Scrapes verified regional prefectures with safe polite backoff."""
    print(f"[*] [2/2] Querying regional syndicates across {len(REGIONAL_PREFECTURES)} prefectures...")
    all_regional = []
    
    for i, sub in enumerate(REGIONAL_PREFECTURES, 1):
        duties = scrape_regional_subdomain(sub)
        if duties:
            print(f"  [+] ({i:2d}/{len(REGIONAL_PREFECTURES)}) {sub:14s}: {len(duties)} on-duty pharmacies")
            all_regional.extend(duties)
        # 1.2s delay to prevent firewall connection drops
        time.sleep(1.2)

    print(f"[+] Regional syndicates: Extracted {len(all_regional)} on-duty pharmacies.")
    return all_regional


# ─────────────────────────────────────────────────────────────
# 1-TO-1 SCHEMA BUILDER & RAW DUTIES GENERATOR
# ─────────────────────────────────────────────────────────────

def build_1to1_duties_payload(raw_duties: list[dict]) -> tuple[dict, list[dict]]:
    """
    Integrates scraped duties into the exact 1-to-1 schema expected by package_dataset.py:
    {
      "updated_at": "<ISO>",
      "pharmacies": {
        "<id>": {
          "id": "<id>",
          "handle": "<handle>",
          "name": "<name>",
          "address": "<address>",
          "city": "<city>",
          "phone": "<phone>",
          "latitude": <lat>,
          "longitude": <lng>,
          "duties": {
            "today": {
              "is_on_duty": true,
              "closes_at": "<time>",
              "periods": [...],
              "observed_at": null,
              "data_status": "fresh"
            },
            "tomorrow": {
              "is_on_duty": false,
              "closes_at": null,
              "periods": [],
              "observed_at": null,
              "data_status": "fresh"
            }
          }
        }
      }
    }
    """
    if not MASTER_FILE.exists():
        raise FileNotFoundError(f"Master file not found at {MASTER_FILE}")

    with open(MASTER_FILE, "r", encoding="utf-8") as f:
        master_list: list[dict] = json.load(f)

    # Lookup indices
    master_by_phone: dict[str, dict] = {}
    for p in master_list:
        phone = clean_phone(p.get("phone") or "")
        if phone:
            master_by_phone[phone] = p

    raw_pharmacies_dict: dict[str, dict] = {}
    matched_count = 0
    upserted_count = 0

    now_iso = datetime.now(timezone.utc).isoformat()

    for d in raw_duties:
        matched = None
        phone = d.get("phone") or ""
        plat = d.get("latitude")
        plng = d.get("longitude")
        d_name = d.get("name") or ""

        # Strategy A: Phone Match
        if phone and phone in master_by_phone:
            matched = master_by_phone[phone]

        # Strategy B: Haversine Geo Match (<= 75m)
        if not matched and plat and plng:
            min_dist = 999999
            closest = None
            for p in master_list:
                mlat = p.get("latitude")
                mlng = p.get("longitude")
                if mlat and mlng and abs(mlat - plat) < 0.005 and abs(mlng - plng) < 0.005:
                    dist = haversine_m(plat, plng, mlat, mlng)
                    if dist < min_dist:
                        min_dist = dist
                        closest = p
            if closest and min_dist <= 75.0:
                matched = closest

        # Strategy C: Token Overlap within 300m
        if not matched and plat and plng:
            t1 = set(normalize_greek(d_name).split()) - {'ΚΑΙ', 'ΣΙΑ', 'ΟΕ', 'ΕΕ', 'ΦΑΡΜΑΚΕΙΟ'}
            for p in master_list:
                mlat = p.get("latitude")
                mlng = p.get("longitude")
                if mlat and mlng and abs(mlat - plat) < 0.005 and abs(mlng - plng) < 0.005:
                    if haversine_m(plat, plng, mlat, mlng) <= 300.0:
                        t2 = set(normalize_greek(p.get("name") or "").split()) - {'ΚΑΙ', 'ΣΙΑ', 'ΟΕ', 'ΕΕ', 'ΦΑΡΜΑΚΕΙΟ'}
                        if t1 & t2:
                            matched = p
                            break

        if matched:
            matched_count += 1
            pid = matched["id"]
            matched["status"] = "open"
            if phone and not matched.get("phone"):
                matched["phone"] = phone
        else:
            # Self-healing upsert
            upserted_count += 1
            pid = f"duty_{abs(hash(d_name + (d.get('address') or ''))) & 0xFFFFFFFF:08x}"
            new_entry = {
                "id": pid,
                "handle": f"pf-{pid}",
                "name": d_name,
                "address": d.get("address") or "",
                "city": d.get("city") or d.get("region") or "",
                "municipality": d.get("city") or "",
                "postalCode": "",
                "prefecture": d.get("region") or "",
                "phone": phone or None,
                "latitude": plat or 38.0,
                "longitude": plng or 23.7,
                "isFrequentDuty": True,
                "operatingHours": d.get("raw_hours") or "08:00 – 08:00",
                "status": "open",
                "closesAt": d.get("closes_at"),
            }
            master_list.append(new_entry)
            matched = new_entry

        # Build 1-to-1 duty record
        raw_pharmacies_dict[pid] = {
            "id": pid,
            "handle": matched.get("handle", pid),
            "name": matched.get("name", d_name),
            "address": matched.get("address", d.get("address")),
            "city": matched.get("city", d.get("city")),
            "phone": matched.get("phone", phone),
            "latitude": matched.get("latitude", plat),
            "longitude": matched.get("longitude", plng),
            "duties": {
                "today": {
                    "is_on_duty": True,
                    "closes_at": d.get("closes_at", "08:00:00"),
                    "periods": d.get("periods", []),
                    "observed_at": None,
                    "data_status": "fresh"
                },
                "tomorrow": {
                    "is_on_duty": False,
                    "closes_at": None,
                    "periods": [],
                    "observed_at": None,
                    "data_status": "fresh"
                }
            }
        }

    duties_raw_payload = {
        "updated_at": now_iso,
        "source": "Official Greek Pharmaceutical Associations (FSA & ITeQ Network)",
        "pharmacies": raw_pharmacies_dict
    }

    print(f"\n[*] 1-to-1 Duties Integration Summary:")
    print(f"  - Total Scraped Primary Shifts:       {len(raw_duties)}")
    print(f"  - Matched Existing Master Stores:     {matched_count}")
    print(f"  - Discovered & Upserted New Stores:   {upserted_count}")
    print(f"  - Master Registry Total Count:        {len(master_list)}")

    return duties_raw_payload, master_list


def main():
    start_time = time.time()
    print("=" * 65)
    print("PHARMAFINDER 1-TO-1 MULTI-SOURCE PRIMARY SCRAPER")
    print("100% REPLACEMENT FOR THIRD-PARTY PHARMAFINDER.APP PROXY")
    print("=" * 65)

    # 1. Scrape FSA Attica
    fsa_duties = scrape_fsa_attica()

    # 2. Scrape Regional Prefectures
    regional_duties = scrape_all_regions()

    all_duties = fsa_duties + regional_duties

    # 3. Build 1-to-1 duties_raw.json and update master
    duties_raw_payload, updated_master = build_1to1_duties_payload(all_duties)

    # 4. Save data/duties_raw.json (ready for package_dataset.py)
    with open(DUTIES_RAW_FILE, "w", encoding="utf-8") as f:
        json.dump(duties_raw_payload, f, ensure_ascii=False, indent=2)
    print(f"[+] Wrote {len(duties_raw_payload['pharmacies'])} duty shifts to {DUTIES_RAW_FILE}")

    # 5. Save data/pharmacies_master.json
    with open(MASTER_FILE, "w", encoding="utf-8") as f:
        json.dump(updated_master, f, ensure_ascii=False, indent=2)
    print(f"[+] Saved updated master catalog to {MASTER_FILE}")

    elapsed = time.time() - start_time
    print(f"\n[+] Multi-source crawl finished cleanly in {elapsed:.2f} seconds.")


if __name__ == "__main__":
    main()
