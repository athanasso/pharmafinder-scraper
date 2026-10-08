# pharmafinder-scraper

Automated scraper, registry builder, and GitHub Release CDN packager for Greek pharmacies and on-duty rotas, modeled after [`athanasso/fuelGR-scraper`](https://github.com/athanasso/fuelGR-scraper).

Powers the **[PharmaFinder Greece](../pharmafinder)** Expo / React Native mobile application.

---

## Architecture Overview

```
                      +-----------------------------+
                      |   PharmaFinder Web Proxy    |
                      |   (Next.js BFF / AES-CBC)   |
                      +--------------+--------------+
                                     |
                       Scrapling + PBKDF2 Decrypt
                                     |
                                     v
+------------------------+    +--------------+    +-----------------------------+
| data/cities.json       |--->|  scraper.py  |--->| data/duties_raw.json        |
| (505 Greek cities)     |    +--------------+    +--------------+--------------+
+------------------------+                                       |
                                                                 v
+------------------------+                        +-----------------------------+
| data/                  |----------------------->|     package_dataset.py      |
| pharmacies_master.json |                        +--------------+--------------+
| (9,049 pharmacies)     |                                       |
+------------------------+                                       v
                                                  +-----------------------------+
                                                  | pharmacies_latest.min.json  |
                                                  | pharmacies_latest.min.json  |
                                                  |              .zst           |
                                                  +--------------+--------------+
                                                                 |
                                                          GitHub Release CDN
                                                                 |
                                                                 v
                                                  +-----------------------------+
                                                  | PharmaFinder Expo Mobile App|
                                                  | (AsyncStorage + Haversine)  |
                                                  +-----------------------------+
```

---

## Release Artifacts

Every scheduled GitHub Actions run (or manual `workflow_dispatch`) updates and publishes:

| Asset | Description | Compression | Size |
|---|---|---|---|
| `pharmacies_latest.min.json` | Complete nationwide pharmacy registry with today/tomorrow duty shifts | Uncompressed JSON | ~3.8 MB |
| `pharmacies_latest.min.json.zst` | High-efficiency mobile payload | Zstandard (level 19) | ~440 KB |

### Direct CDN URL
```
https://github.com/<owner>/pharmafinder-scraper/releases/latest/download/pharmacies_latest.min.json
```

---

## GitHub Actions Automation

Workflow: [`.github/workflows/update-pharmacies.yml`](.github/workflows/update-pharmacies.yml)

- **Schedules (UTC):**
  - `17 4 * * *` (07:17 Athens — morning rota update)
  - `47 10 * * *` (13:47 Athens — afternoon shift check)
  - `23 16 * * *` (19:23 Athens — overnight emergency rota)
- **Permissions:** `contents: write` (for committing updated registry and creating releases).
- **Automated Steps:**
  1. Sets up Python 3.12 with pip cache.
  2. Runs `python scraper.py` to crawl duty rosters.
  3. Runs `python package_dataset.py` to merge and build `.min.json` and `.min.json.zst`.
  4. Commits enriched `data/pharmacies_master.json` back to repository.
  5. Publishes latest release via `gh release create`.

---

## Local Development

### 1. Requirements
- Python 3.10+
- Virtual environment (recommended)

```bash
pip install -r requirements.txt
```

### 2. Crawl Rosters
```bash
python scraper.py
```
Crawls Greek municipalities using Scrapling, decodes encrypted duty tokens, and dumps `data/duties_raw.json`.

### 3. Package & Compress
```bash
python package_dataset.py
```
Merges fresh duty shifts with `data/pharmacies_master.json`, generates `pharmacies_latest.min.json`, compresses with `zstandard`, and writes release tags (`tag.txt`, `release_notes.md`).

---

## Mobile Client Integration

In the Expo mobile app ([`pharmafinder`](../pharmafinder)):

1. Set the CDN URL in `.env`:
   ```bash
   EXPO_PUBLIC_PHARMACIES_CDN_URL=https://github.com/<owner>/pharmafinder-scraper/releases/latest/download/pharmacies_latest.min.json
   ```
2. The client fetches and caches the dataset in `AsyncStorage` on startup (`src/entities/pharmacy/api/pharmacyApi.ts`).
3. Haversine distance, radius filtering, search, and duty mode checks (`now` / `today` / `tomorrow`) run instantly on the device without network latency or rate-limiting.

---

## Schema

```json
{
  "updated_at": "2026-10-08T17:00:00Z",
  "count": 9049,
  "on_duty_today": 2867,
  "on_duty_tomorrow": 2490,
  "pharmacies": [
    {
      "id": "qJyDEqRJTlCsbi4223Hnzw",
      "handle": "1866-sq-pharmacy-verganelaki-maro-chania",
      "name": "1866 SQ. PHARMACY - ΒΕΡΓΑΝΕΛΑΚΗ ΜΑΡΩ",
      "address": "Πλ. 1866 37, Χανιά, 73135, ΧΑΝΙΩΝ",
      "city": "Χανιά",
      "municipality": "Χανιά",
      "postalCode": "73135",
      "phone": "2821093717",
      "latitude": 35.51262362,
      "longitude": 24.01800638,
      "operatingHours": "08:00 – 14:00 · 17:30 – 21:00",
      "status": "open",
      "isFrequentDuty": false,
      "closesAt": "21:00:00",
      "duties": {
        "today": {
          "is_on_duty": true,
          "closes_at": "21:00:00",
          "periods": [
            { "opens_at": "08:00:00", "closes_at": "14:00:00" },
            { "opens_at": "17:30:00", "closes_at": "21:00:00" }
          ]
        },
        "tomorrow": {
          "is_on_duty": false,
          "closes_at": null,
          "periods": []
        }
      }
    }
  ]
}
```
