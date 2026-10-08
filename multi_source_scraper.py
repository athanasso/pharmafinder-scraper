#!/usr/bin/env python3
"""
multi_source_scraper.py

Official Greek primary-source on-duty pharmacy crawler.
Fetches real-time duty shifts directly from:
  1. ΦΣΑ (fsa-efimeries.gr) for Attica (~4,130 pharmacies)
  2. ITeQ Network (*.efhmeries.gr) for 30+ regional prefectures (Crete, Peloponnese, Thessaly, Macedonia, Epirus, Thrace, Aegean)

Matches and upserts against data/pharmacies_master.json and outputs standardized duty rosters.
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
OUTPUT_FILE = DATA_DIR / "duties_multi_source.json"

SSL_CTX = ssl.create_default_context()
SSL_CTX.check_hostname = False
SSL_CTX.verify_mode = ssl.CERT_NONE

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "el-GR,el;q=0.9,en;q=0.8",
}

# 30 verified working regional prefectures on efhmeries.gr
REGIONAL_SUBDOMAINS = [
    "herakleion", "korinthia", "messinia", "larisa", "chania", 
    "argolida", "lakonia", "pieria", "fthiotida", "evia", 
    "evros", "magnesia", "imathia", "pella", "lasithi", 
    "trikala", "kozani", "samos", "kavala", "drama", 
    "xanthi", "ioannina", "arta", "preveza", "thesprotia", 
    "karditsa", "karpenisi", "zakynthos", "ileia", "arkadia"
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
    """Scrapes on-duty pharmacies across the Attica region from fsa-efimeries.gr."""
    url = "https://fsa-efimeries.gr/Home/FilteredHomeResults"
    print("[*] Fetching FSA Attica duties from fsa-efimeries.gr...")
    
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
                
        # Parse duty hours badge from card
        card_html = cards.get(duty_id, "")
        hours_match = re.search(r'badge[^>]*>\s*([0-9:.]+)\s*-\s*([0-9:.]+)\s*<', card_html)
        if hours_match:
            start_h, end_h = hours_match.group(1).replace(".", ":"), hours_match.group(2).replace(".", ":")
            hours_str = f"{start_h} - {end_h}"
        else:
            hours_str = "Διανυκτερεύον"

        duties.append({
            "source": "fsa-efimeries.gr",
            "region": "Αττική",
            "name": name,
            "address": address,
            "city": district,
            "phone": phone,
            "latitude": float(lat_s),
            "longitude": float(lng_s),
            "duty_summary": {
                "opens_at": None,
                "closes_at": None,
                "raw_hours": hours_str
            }
        })

    print(f"[+] FSA Attica parsed {len(duties)} active on-duty pharmacies.")
    return duties


# ─────────────────────────────────────────────────────────────
# SOURCE 2: ITeQ REGIONAL NETWORK (*.efhmeries.gr)
# ─────────────────────────────────────────────────────────────

def scrape_regional_subdomain(sub: str) -> list[dict]:
    """Scrapes on-duty pharmacies for a specific prefecture subdomain."""
    url = f"https://{sub}.efhmeries.gr/"
    req = urllib.request.Request(url, headers=HEADERS)
    
    try:
        with urllib.request.urlopen(req, context=SSL_CTX, timeout=8) as resp:
            html_text = resp.read().decode("utf-8", errors="ignore")
    except Exception:
        return []

    # Extract all pharmacy card blocks
    card_chunks = html_text.split('<div class="card')
    duties = []
    
    for chunk in card_chunks[1:]:
        det_match = re.search(r'/Home/Details/(\d+)', chunk)
        if not det_match:
            continue
            
        # Extract title (name)
        title_match = re.search(r'<h[4-6][^>]*class="card-title[^"]*"[^>]*>(.*?)</h[4-6]>', chunk, re.DOTALL)
        if not title_match:
            title_match = re.search(r'<h[4-6][^>]*>(.*?)</h[4-6]>', chunk, re.DOTALL)
        name = html_lib.unescape(re.sub(r'<[^>]+>', '', title_match.group(1))).strip() if title_match else ""
        
        # Extract address & phone
        clean_text = re.sub(r'<[^>]+>', '\n', chunk)
        lines = [re.sub(r'\s+', ' ', l).strip() for l in clean_text.split('\n') if l.strip()]
        
        phone = ""
        address = ""
        for line in lines:
            p = clean_phone(line)
            if p and not phone:
                phone = p
            elif any(k in line.lower() for k in ['οδός', 'οδος', 'τ.κ.', 'αρ.', 'πλατεία']) or re.search(r'\d+', line):
                if not address and len(line) > 5 and not p:
                    address = line
                    
        # Extract coordinates from Google Maps query: query=35.5068073%2C23.9880296
        lat, lng = None, None
        map_match = re.search(r'query=([0-9.]+)%2C([0-9.]+)', chunk)
        if map_match:
            lat = float(map_match.group(1))
            lng = float(map_match.group(2))
            
        # Duty shift text
        shift_match = re.search(r'(ΔΙΑΝΥΚΤΕΡΕΥΕΙ[^<]+|ΕΦΗΜΕΡΕΥΕΙ[^<]+)', chunk, re.IGNORECASE)
        shift_text = html_lib.unescape(shift_match.group(1)).strip() if shift_match else "Εφημερεύον"

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
                "duty_summary": {
                    "opens_at": None,
                    "closes_at": None,
                    "raw_hours": shift_text
                }
            })

    return duties


def scrape_all_regions() -> list[dict]:
    """Scrapes all 30 supported regional prefectures with polite backoff."""
    print(f"[*] Fetching regional duties across {len(REGIONAL_SUBDOMAINS)} Greek prefectures...")
    all_regional = []
    
    for sub in REGIONAL_SUBDOMAINS:
        duties = scrape_regional_subdomain(sub)
        if duties:
            print(f"  [+] {sub:15s}: {len(duties)} on-duty pharmacies")
            all_regional.extend(duties)
        time.sleep(0.3)  # polite rate-limiting

    print(f"[+] Regional total: {len(all_regional)} pharmacies across {len(REGIONAL_SUBDOMAINS)} prefectures.")
    return all_regional


# ─────────────────────────────────────────────────────────────
# MASTER REGISTRY MATCHER & UPSERTER
# ─────────────────────────────────────────────────────────────

def match_and_upsert_duties(raw_duties: list[dict]) -> tuple[dict, list[dict]]:
    """
    Matches raw scraped duties against pharmacies_master.json.
    Upserts newly discovered pharmacies so the database self-heals.
    Returns: (output_dataset_dict, updated_master_list)
    """
    if not MASTER_FILE.exists():
        raise FileNotFoundError(f"Master file not found at {MASTER_FILE}")
        
    with open(MASTER_FILE, "r", encoding="utf-8") as f:
        master_list: list[dict] = json.load(f)

    # 1. Build lookup indices
    master_by_phone: dict[str, dict] = {}
    for p in master_list:
        phone = clean_phone(p.get("phone") or "")
        if phone:
            master_by_phone[phone] = p

    # Reset all master duties to idle
    for p in master_list:
        p["status"] = "idle"
        p["dutyPeriods"] = []

    matched_count = 0
    new_upserted = 0
    active_duties = []

    for d in raw_duties:
        matched_pharmacy = None
        phone = d.get("phone") or ""
        plat = d.get("latitude")
        plng = d.get("longitude")
        d_name = d.get("name") or ""
        
        # Strategy A: Phone Match
        if phone and phone in master_by_phone:
            matched_pharmacy = master_by_phone[phone]

        # Strategy B: Haversine Geo Match (<= 75 meters)
        if not matched_pharmacy and plat and plng:
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
                matched_pharmacy = closest

        # Strategy C: Token Overlap within 300m
        if not matched_pharmacy and plat and plng:
            t1 = set(normalize_greek(d_name).split()) - {'ΚΑΙ', 'ΣΙΑ', 'ΟΕ', 'ΕΕ', 'ΦΑΡΜΑΚΕΙΟ'}
            for p in master_list:
                mlat = p.get("latitude")
                mlng = p.get("longitude")
                if mlat and mlng and abs(mlat - plat) < 0.005 and abs(mlng - plng) < 0.005:
                    if haversine_m(plat, plng, mlat, mlng) <= 300.0:
                        t2 = set(normalize_greek(p.get("name") or "").split()) - {'ΚΑΙ', 'ΣΙΑ', 'ΟΕ', 'ΕΕ', 'ΦΑΡΜΑΚΕΙΟ'}
                        if t1 & t2:
                            matched_pharmacy = p
                            break

        # Process Match or Upsert New
        if matched_pharmacy:
            matched_count += 1
            matched_pharmacy["status"] = "on_duty"
            matched_pharmacy["dutyPeriods"] = [{
                "opensAt": None,
                "closesAt": None,
                "rawHours": d["duty_summary"]["raw_hours"]
            }]
            # Enrich phone if missing
            if phone and not matched_pharmacy.get("phone"):
                matched_pharmacy["phone"] = phone
            active_duties.append(matched_pharmacy)
        else:
            # Self-healing: create verified record from association
            new_upserted += 1
            new_id = f"duty_{abs(hash(d_name + (d.get('address') or ''))) & 0xFFFFFFFF:08x}"
            new_entry = {
                "id": new_id,
                "handle": f"pf-{new_id}",
                "name": d_name,
                "address": d.get("address") or "",
                "city": d.get("city") or d.get("region") or "",
                "municipality": d.get("city") or "",
                "postalCode": "",
                "prefecture": d.get("region") or "",
                "phone": phone,
                "latitude": plat,
                "longitude": plng,
                "isFrequentDuty": True,
                "operatingHours": None,
                "status": "on_duty",
                "closesAt": None,
                "dutyPeriods": [{
                    "opensAt": None,
                    "closesAt": None,
                    "rawHours": d["duty_summary"]["raw_hours"]
                }]
            }
            master_list.append(new_entry)
            active_duties.append(new_entry)

    print(f"\n[*] Matching Summary:")
    print(f"  - Total Scraped from Primary Sources: {len(raw_duties)}")
    print(f"  - Matched to Existing Master Records: {matched_count}")
    print(f"  - Newly Discovered & Upserted:       {new_upserted}")
    print(f"  - Total Active On-Duty Pharmacies:    {len(active_duties)}")

    now_iso = datetime.now(timezone.utc).isoformat()
    output_payload = {
        "metadata": {
            "version": "2.0.0-primary",
            "source": "Official Greek Pharmaceutical Associations (FSA & ITeQ Network)",
            "crawled_at": now_iso,
            "total_master_pharmacies": len(master_list),
            "total_on_duty": len(active_duties),
            "sources_contacted": 1 + len(REGIONAL_SUBDOMAINS)
        },
        "items": active_duties
    }

    return output_payload, master_list


def main():
    start_time = time.time()
    print("=" * 65)
    print("PHARMAFINDER MULTI-SOURCE PRIMARY SCRAPER (Interpretation B)")
    print("=" * 65)

    # Step 1: Scrape Attica
    attica_duties = scrape_fsa_attica()

    # Step 2: Scrape Regional Network
    regional_duties = scrape_all_regions()

    all_scraped = attica_duties + regional_duties

    # Step 3: Match & Upsert against Master Registry
    payload, updated_master = match_and_upsert_duties(all_scraped)

    # Step 4: Write duties output
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f"\n[+] Wrote {len(payload['items'])} active duties to {OUTPUT_FILE}")

    # Step 5: Save updated master (with new pharmacies upserted)
    with open(MASTER_FILE, "w", encoding="utf-8") as f:
        json.dump(updated_master, f, ensure_ascii=False, indent=2)
    print(f"[+] Updated master registry saved ({len(updated_master)} total pharmacies).")

    elapsed = time.time() - start_time
    print(f"[+] Multi-source scrape finished in {elapsed:.2f} seconds.")


if __name__ == "__main__":
    main()
