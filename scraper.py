#!/usr/bin/env python3
"""
scraper.py

Automated Greek on-duty pharmacy crawler modeled after fuelGR-scraper.
Crawls duty shifts for all Greek municipalities from pharmafinder.app via Scrapling,
decrypting payload tokens with PBKDF2/AES-128-CBC and saving raw rosters to data/duties_raw.json.
"""

from __future__ import annotations

import base64
import json
import os
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from cryptography.hazmat.primitives import hashes, hmac
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from scrapling.fetchers import Fetcher

sys.stdout.reconfigure(encoding="utf-8")

BASE_URL = "https://www.pharmafinder.app"
CLIENT_SECRET = b"zs6QYeF72lEmAfXPDk4BSnc0LHIZ3bot"
CLIENT_SALT = b"zWUlwh5GsrBpM9vt"

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)

CITIES_FILE = DATA_DIR / "cities.json"
DUTIES_OUT = DATA_DIR / "duties_raw.json"


def derive_keys() -> tuple[bytes, bytes]:
    """Derives 16-byte HMAC signing key and 16-byte AES encryption key via PBKDF2."""
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=CLIENT_SALT,
        iterations=100_000,
    )
    derived = kdf.derive(CLIENT_SECRET)
    return derived[:16], derived[16:32]


_SIGNING_KEY, _ENCRYPTION_KEY = derive_keys()


def unpad(data: bytes) -> bytes:
    """Strips one or more layers of PKCS7 padding."""
    while len(data) > 0:
        pad_len = data[-1]
        if 1 <= pad_len <= 16 and all(b == pad_len for b in data[-pad_len:]):
            data = data[:-pad_len]
        else:
            break
    return data


def decrypt_token(token_str: str) -> dict:
    """Decrypts a PharmaFinder Fernet-format payload."""
    token_bytes = base64.urlsafe_b64decode(token_str + "=" * (-len(token_str) % 4))
    data_to_verify = token_bytes[:-32]
    signature = token_bytes[-32:]

    h = hmac.HMAC(_SIGNING_KEY, hashes.SHA256())
    h.update(data_to_verify)
    h.verify(signature)

    iv = token_bytes[9:25]
    ciphertext = token_bytes[25:-32]

    cipher = Cipher(algorithms.AES(_ENCRYPTION_KEY), modes.CBC(iv))
    decryptor = cipher.decryptor()
    padded_plaintext = decryptor.update(ciphertext) + decryptor.finalize()

    plain = unpad(padded_plaintext)
    return json.loads(plain.decode("utf-8"))


def get_session(retries: int = 3) -> str:
    """Acquires anonymous session cookie from the BFF proxy."""
    for attempt in range(1, retries + 1):
        try:
            res = Fetcher.post(
                f"{BASE_URL}/api/session",
                headers={
                    "Origin": BASE_URL,
                    "Referer": f"{BASE_URL}/",
                    "Accept": "application/json",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PharmaFinder-Scraper/1.0",
                },
            )
            cookie_val = res.cookies.get("pf_session")
            if cookie_val:
                return cookie_val
        except Exception as e:
            if attempt == retries:
                raise RuntimeError(f"Failed to acquire pf_session after {retries} attempts: {e}")
            time.sleep(1.0)
    raise RuntimeError("Failed to obtain pf_session cookie")


def fetch_city_duty(
    city_slug: str,
    duty_time: str,
    session_cookie: str,
    cursor: str | None = None,
    max_retries: int = 3,
) -> dict | None:
    """Fetches on-duty pharmacies for a given city and time mode with retry backoff."""
    url = f"{BASE_URL}/api/proxy/v1/duty/cities/{city_slug}?time={duty_time}"
    if cursor:
        url += f"&cursor={cursor}"

    for attempt in range(1, max_retries + 1):
        try:
            res = Fetcher.get(
                url,
                headers={
                    "Cookie": f"pf_session={session_cookie}",
                    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) PharmaFinder-Scraper/1.0",
                    "Accept": "application/json",
                },
            )
            if res.status == 404:
                return None
            if res.status in (500, 502, 503, 504):
                if attempt < max_retries:
                    time.sleep(1.5 * attempt)
                    continue
                return None
            raw = res.json()
            if "encrypted" in raw:
                return decrypt_token(raw["encrypted"])
            return raw
        except Exception as e:
            if attempt < max_retries:
                time.sleep(1.0 * attempt)
                continue
            print(f"  [!] City {city_slug} ({duty_time}) failed: {e}")
            return None
    return None


def run_scraper():
    print("=" * 60)
    print(" PharmaFinder Greece — Duty Pharmacy Scraper")
    print(" Modeled after fuelGR-scraper (Scrapling + Automated Cron)")
    print("=" * 60)

    if not CITIES_FILE.exists():
        print(f"[-] Missing {CITIES_FILE}. Run seed script first.")
        sys.exit(1)

    with open(CITIES_FILE, "r", encoding="utf-8") as f:
        cities = json.load(f)
    print(f"[*] Loaded {len(cities)} cities from registry.")

    print("[*] Minting anonymous session...")
    cookie = get_session()
    print("[+] Session active.")

    raw_duties: dict[str, dict] = {}
    total_shifts_scraped = 0
    start_time = time.time()

    # Prioritize populated cities first, then scrape remaining
    priority_slugs = {
        "athina", "thessaloniki", "peiraias", "patra", "irakleio", "larisa",
        "volos", "ioannina", "chania", "chalkida", "kallithea", "peristeri",
        "maroysi", "glyfada", "neasmirni", "chalandri", "kifisia", "ilioypoli",
        "agios-dimitrios", "aigaleo", "dafni", "peyki", "agia-paraskevi",
        "vyronas", "zografoy", "galatsi", "thiva", "kalamata", "rodo", "kerkyra",
    }
    
    sorted_cities = sorted(
        cities,
        key=lambda c: 0 if c["slug"] in priority_slugs else 1
    )

    # Scrape duty schedules for today and tomorrow
    for idx, c in enumerate(sorted_cities, 1):
        c_slug = c["slug"]
        c_name = c["city"]
        
        for mode in ("today", "tomorrow"):
            cursor = None
            page_num = 0
            while True:
                page_num += 1
                data = fetch_city_duty(c_slug, mode, cookie, cursor=cursor)
                if not data:
                    break
                
                items = data.get("items", [])
                for item in items:
                    pid = item.get("public_id") or item.get("handle")
                    if not pid:
                        continue
                    
                    if pid not in raw_duties:
                        raw_duties[pid] = {
                            "id": pid,
                            "handle": item.get("handle", pid),
                            "name": item.get("name"),
                            "address": item.get("address_short"),
                            "city": item.get("city") or c_name,
                            "phone": item.get("phone"),
                            "latitude": item.get("latitude"),
                            "longitude": item.get("longitude"),
                            "is_frequent_duty": item.get("is_frequent_duty", False),
                            "duties": {},
                        }
                    
                    # Update coords/phone if missing
                    if item.get("latitude") and not raw_duties[pid].get("latitude"):
                        raw_duties[pid]["latitude"] = item["latitude"]
                        raw_duties[pid]["longitude"] = item["longitude"]
                    if item.get("phone") and not raw_duties[pid].get("phone"):
                        raw_duties[pid]["phone"] = item["phone"]

                    duty_summary = item.get("duty_summary", {})
                    raw_duties[pid]["duties"][mode] = {
                        "is_on_duty": duty_summary.get("is_on_duty"),
                        "closes_at": duty_summary.get("closes_at"),
                        "periods": duty_summary.get("periods", []),
                        "observed_at": duty_summary.get("observed_at"),
                    }
                    total_shifts_scraped += 1

                if data.get("has_more") and data.get("next_cursor"):
                    cursor = data["next_cursor"]
                    if page_num >= 8:  # Safety ceiling
                        break
                else:
                    break

        if idx % 25 == 0 or idx == len(sorted_cities):
            elapsed = time.time() - start_time
            print(f"[{idx}/{len(sorted_cities)}] Scraped {c_name} — {len(raw_duties)} unique pharmacies ({elapsed:.1f}s)")

    output_payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "total_pharmacies": len(raw_duties),
        "total_shifts": total_shifts_scraped,
        "pharmacies": raw_duties,
    }

    with open(DUTIES_OUT, "w", encoding="utf-8") as f:
        json.dump(output_payload, f, ensure_ascii=False, indent=2)

    elapsed_total = time.time() - start_time
    print(f"\n[+] Scrape finished in {elapsed_total:.1f}s.")
    print(f"[+] Captured {len(raw_duties)} on-duty pharmacies ({total_shifts_scraped} shifts).")
    print(f"[+] Saved to {DUTIES_OUT}.")


if __name__ == "__main__":
    run_scraper()
