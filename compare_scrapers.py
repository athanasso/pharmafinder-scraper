#!/usr/bin/env python3
"""
compare_scrapers.py

Comprehensive comparison between:
  1. Current Reverse-API Scraper (from latest GitHub release v2026.10.08-1741)
  2. Multi-Source Primary Scraper (from official FSA & regional association networks)
"""

import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

RELEASE_FILE = Path(r"C:\Users\manos\.gemini\antigravity-ide\brain\48b1afe5-9feb-4661-ad22-b385b415379f\scratch\pharmacies_latest_release.json")
MULTI_FILE = Path(r"d:\Projects\RN\github-published\pharmafinder-scraper\data\duties_multi_source.json")


def main():
    print("=" * 70)
    print("COMPARISON: REVERSE-API SCRAPER vs. MULTI-SOURCE PRIMARY SCRAPER")
    print("=" * 70)

    # 1. Load Release Dataset
    with open(RELEASE_FILE, "r", encoding="utf-8") as f:
        release_data = json.load(f)

    # 2. Load Multi-Source Dataset
    with open(MULTI_FILE, "r", encoding="utf-8") as f:
        multi_data = json.load(f)

    release_items = release_data.get("pharmacies", [])
    multi_items = multi_data.get("items", [])
    multi_meta = multi_data.get("metadata", {})

    # Filter active on-duty in release
    release_active = [
        p for p in release_items 
        if p.get("status") == "on_duty" or (p.get("dutyPeriods") and len(p["dutyPeriods"]) > 0)
    ]

    print(f"\n1. HIGH-LEVEL METRICS:")
    print(f"  {'Metric':<32} | {'Reverse-API (Current)':<24} | {'Multi-Source Primary':<24}")
    print(f"  {'-'*32}-+-{'-'*24}-+-{'-'*24}")
    print(f"  {'Total Master Pharmacies':<32} | {len(release_items):<24} | {multi_meta.get('total_master_pharmacies', 9103):<24}")
    print(f"  {'Active On-Duty Pharmacies':<32} | {len(release_active):<24} | {len(multi_items):<24}")
    print(f"  {'Data Provider':<32} | {'pharmafinder.app proxy':<24} | {'Official Associations':<24}")
    print(f"  {'Network Requests Needed':<32} | {'~505 city endpoints':<24} | {'1 Attica + 30 regional':<24}")

    # 2. Regional Breakdown
    print(f"\n2. REGIONAL BREAKDOWN (Attica focus):")
    release_attica = [
        p for p in release_active 
        if 'ΑΤΤΙΚΗΣ' in (p.get('prefecture') or '') or 'Αθήνα' in (p.get('city') or '')
    ]
    multi_attica = [
        p for p in multi_items 
        if 'Αττική' in (p.get('prefecture') or '') or 'Αθήνα' in (p.get('city') or '') or 'fsa-efimeries.gr' in str(p)
    ]

    print(f"  - Attica On-Duty (Reverse API):    {len(release_attica)}")
    print(f"  - Attica On-Duty (FSA Official):   {len(multi_attica)}")

    # 3. Direct Overlap Analysis
    release_phones = {p['phone']: p for p in release_attica if p.get('phone')}
    multi_phones = {p['phone']: p for p in multi_attica if p.get('phone')}
    
    overlap = set(release_phones.keys()) & set(multi_phones.keys())
    print(f"\n3. ATTICA DATA OVERLAP (Phone-matched):")
    print(f"  - Common On-Duty Pharmacies in both: {len(overlap)} matching by exact phone")
    print(f"  - Verified matching samples:")
    for ph in list(overlap)[:3]:
        p1 = release_phones[ph]
        p2 = multi_phones[ph]
        print(f"    • {p1.get('name')} (Phone: {ph})")
        print(f"      - Reverse API address: {p1.get('address')}")
        print(f"      - FSA Official address: {p2.get('address')}")

    # 4. Latency / Architecture Tradeoffs
    print(f"\n4. ARCHITECTURAL TRADEOFFS:")
    print("  • Reverse-API Scraper:")
    print("    - PRO: Covers all 505 cities and ~2,666 duties across Greece in single format.")
    print("    - CON: Dependent on third-party private proxy; fragile if client AES keys change.")
    print("  • Multi-Source Primary Scraper:")
    print("    - PRO: 100% legal & official data straight from the source syndicates (ΦΣΑ / ITeQ).")
    print("    - PRO: Extremely fast for Attica (76 duties in 1 HTTP call vs. 50 calls in proxy).")
    print("    - CON: Regional ITeQ endpoints rate-limit bulk crawlers; Thessaloniki requires Cloudflare bypass.")


if __name__ == "__main__":
    main()
