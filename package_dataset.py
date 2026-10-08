#!/usr/bin/env python3
"""
package_dataset.py

Packages PharmaFinder dataset artifacts for GitHub Release and static CDN hosting.
Modeled after fuelGR-scraper/package_dataset.py:
1. Loads master registry (data/pharmacies_master.json).
2. Merges latest duty rosters from data/duties_raw.json (updating operatingHours, closesAt, is_on_duty, coords).
3. Writes updated master dataset back to data/pharmacies_master.json.
4. Generates compact mobile distribution artifact: pharmacies_latest.min.json.
5. Compresses artifact using zstandard (.zst).
6. Generates tag.txt and release_notes.md for automated GitHub Release publishing.
"""

from __future__ import annotations

import gzip
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
MASTER_FILE = DATA_DIR / "pharmacies_master.json"
DUTIES_FILE = DATA_DIR / "duties_raw.json"
OUTPUT_JSON = SCRIPT_DIR / "pharmacies_latest.min.json"
OUTPUT_ZST = SCRIPT_DIR / "pharmacies_latest.min.json.zst"
TAG_FILE = SCRIPT_DIR / "tag.txt"
RELEASE_NOTES = SCRIPT_DIR / "release_notes.md"


def compress_zstd(source_path: Path, dest_path: Path):
    """Compresses file using python zstandard library, zstd CLI, or fallback gzip."""
    try:
        import zstandard as zstd

        cctx = zstd.ZstdCompressor(level=19)
        with open(source_path, "rb") as f_in, open(dest_path, "wb") as f_out:
            cctx.copy_stream(f_in, f_out)
        print(f"  [zstd-lib] Compressed {source_path.name} -> {dest_path.name} ({dest_path.stat().st_size:,} bytes)")
        return
    except ImportError:
        pass

    zstd_bin = shutil.which("zstd")
    if zstd_bin:
        res = subprocess.run(
            [zstd_bin, "-19", "-f", str(source_path), "-o", str(dest_path)],
            capture_output=True,
        )
        if res.returncode == 0:
            print(f"  [zstd-cli] Compressed {source_path.name} -> {dest_path.name} ({dest_path.stat().st_size:,} bytes)")
            return

    # Fallback to gzip
    gz_path = dest_path.with_suffix(".gz")
    with open(source_path, "rb") as f_in, gzip.open(gz_path, "wb", compresslevel=9) as f_out:
        shutil.copyfileobj(f_in, f_out)
    print(f"  [gzip-fallback] Compressed {source_path.name} -> {gz_path.name} ({gz_path.stat().st_size:,} bytes)")


def format_periods(periods: list) -> str:
    if not periods:
        return "—"
    parts = []
    for p in periods:
        o = str(p.get("opens_at", ""))[:5]
        c = str(p.get("closes_at", ""))[:5]
        if o and c:
            parts.append(f"{o} – {c}")
    return " · ".join(parts) if parts else "—"


def package():
    print("=" * 60)
    print(" PharmaFinder Greece — Release Packager")
    print(" Modeled after fuelGR-scraper (Zstandard + Release Tagging)")
    print("=" * 60)

    if not MASTER_FILE.exists():
        print(f"[-] Master registry not found at {MASTER_FILE}. Run seed script first.")
        sys.exit(1)

    with open(MASTER_FILE, "r", encoding="utf-8") as f:
        master_list: list[dict] = json.load(f)

    master_map: dict[str, dict] = {p["id"]: p for p in master_list}
    print(f"[*] Loaded {len(master_map):,} baseline pharmacies from {MASTER_FILE.name}.")

    now_utc = datetime.now(timezone.utc)
    now_str = now_utc.isoformat()

    # Merge fresh duties if available
    duties_merged = 0
    today_on_duty_count = 0
    tomorrow_on_duty_count = 0

    if DUTIES_FILE.exists():
        with open(DUTIES_FILE, "r", encoding="utf-8") as f:
            duties_payload = json.load(f)
        
        raw_pharmacies = duties_payload.get("pharmacies", {})
        print(f"[*] Merging live duties for {len(raw_pharmacies):,} pharmacies...")

        for pid, d_obj in raw_pharmacies.items():
            today_duty = d_obj.get("duties", {}).get("today", {})
            tomorrow_duty = d_obj.get("duties", {}).get("tomorrow", {})

            is_open_today = bool(today_duty.get("is_on_duty"))
            if is_open_today:
                today_on_duty_count += 1
            if tomorrow_duty.get("is_on_duty"):
                tomorrow_on_duty_count += 1

            periods_today = today_duty.get("periods", [])
            hours_str = format_periods(periods_today)

            if pid in master_map:
                target = master_map[pid]
                if d_obj.get("name"):
                    target["name"] = d_obj["name"]
                if d_obj.get("address"):
                    target["address"] = d_obj["address"]
                if d_obj.get("city"):
                    target["city"] = d_obj["city"]
                if d_obj.get("phone"):
                    target["phone"] = d_obj["phone"]
                if d_obj.get("latitude") is not None and d_obj.get("longitude") is not None:
                    target["latitude"] = d_obj["latitude"]
                    target["longitude"] = d_obj["longitude"]
                
                target["operatingHours"] = hours_str
                target["status"] = "open" if is_open_today else "scheduled"
                target["closesAt"] = today_duty.get("closes_at")
                target["duties"] = {
                    "today": today_duty,
                    "tomorrow": tomorrow_duty,
                }
                duties_merged += 1
            else:
                # Add discovered pharmacy
                master_map[pid] = {
                    "id": pid,
                    "handle": d_obj.get("handle", pid),
                    "name": d_obj.get("name", "ΦΑΡΜΑΚΕΙΟ"),
                    "address": d_obj.get("address", ""),
                    "city": d_obj.get("city", ""),
                    "municipality": d_obj.get("city", ""),
                    "postalCode": "",
                    "prefecture": "",
                    "phone": d_obj.get("phone"),
                    "latitude": d_obj.get("latitude", 38.0),
                    "longitude": d_obj.get("longitude", 23.7),
                    "isFrequentDuty": d_obj.get("is_frequent_duty", False),
                    "operatingHours": hours_str,
                    "status": "open" if is_open_today else "scheduled",
                    "closesAt": today_duty.get("closes_at"),
                    "duties": {
                        "today": today_duty,
                        "tomorrow": tomorrow_duty,
                    },
                }
                duties_merged += 1

        print(f"[+] Successfully merged {duties_merged:,} duty shifts.")
    else:
        print("[!] No duties_raw.json found; compiling existing master state.")
        for p in master_map.values():
            if p.get("status") == "open":
                today_on_duty_count += 1

    # Save updated master registry
    updated_master = list(master_map.values())
    with open(MASTER_FILE, "w", encoding="utf-8") as f:
        json.dump(updated_master, f, ensure_ascii=False, indent=2)
    print(f"[+] Updated master registry: {MASTER_FILE} ({len(updated_master):,} stores).")

    # Build mobile distribution payload
    mobile_payload = {
        "updated_at": now_str,
        "count": len(updated_master),
        "on_duty_today": today_on_duty_count,
        "on_duty_tomorrow": tomorrow_on_duty_count,
        "pharmacies": updated_master,
    }

    # Write minified JSON
    with open(OUTPUT_JSON, "w", encoding="utf-8") as f:
        json.dump(mobile_payload, f, ensure_ascii=False, separators=(",", ":"))

    json_kb = OUTPUT_JSON.stat().st_size / 1024
    print(f"[+] Generated minified mobile JSON: {OUTPUT_JSON.name} ({json_kb:.1f} KB).")

    # Compress with zstandard
    compress_zstd(OUTPUT_JSON, OUTPUT_ZST)

    # Generate tag and release notes for GitHub Release
    tag = f"v{now_utc.strftime('%Y.%m.%d-%H%M')}"
    TAG_FILE.write_text(tag, encoding="utf-8")

    release_notes_content = f"""# PharmaFinder Greece — Automated Registry & Duty Release ({tag})

- **Release Timestamp:** `{now_str}`
- **Total Registered Greek Pharmacies:** `{len(updated_master):,}`
- **Active On-Duty Pharmacies (Today):** `{today_on_duty_count:,}`
- **Active On-Duty Pharmacies (Tomorrow):** `{tomorrow_on_duty_count:,}`

### Artifacts
- `pharmacies_latest.min.json` ({json_kb:.1f} KB uncompressed)
- `pharmacies_latest.min.json.zst` (Zstandard level 19 mobile stream)

Automated update generated via Scrapling crawler modeled after fuelGR-scraper.
"""
    RELEASE_NOTES.write_text(release_notes_content, encoding="utf-8")
    print(f"[+] Generated {TAG_FILE.name} ({tag}) and {RELEASE_NOTES.name}.")
    print("\n Packaging complete!")


if __name__ == "__main__":
    package()
