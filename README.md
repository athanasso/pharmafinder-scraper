# pharmafinder-scraper

Automated scraper, registry builder, and GitHub Release CDN packager for Greek pharmacies and on-duty rotas, modeled after [`athanasso/fuelGR-scraper`](https://github.com/athanasso/fuelGR-scraper).

Directly crawls official Greek pharmaceutical syndicate portals (ΦΣΑ Attica + ITeQ Regional Network) — 100% independent, zero third-party proxy dependencies.

Powers the **[PharmaFinder Greece](../pharmafinder)** Expo / React Native mobile application.

---

## Architecture Overview

```
              +-------------------------------+    +--------------------------------+
              |      ΦΣΑ Attica Syndicate     |    |     ITeQ Regional Network      |
              |       (fsa-efimeries.gr)      |    |  (*.efhmeries.gr - 30 regions) |
              +---------------+---------------+    +---------------+----------------+
                              \                                   /
                               \                                 /
                         Direct HTTP/REST                  HTML Crawl & Parse
                                \                               /
                                 v                             v
                        +-----------------------------------------------+
                        |            multi_source_scraper.py            |
                        +-----------------------+-----------------------+
                                                |
                 +------------------------------+------------------------------+
                 | (Matches via 10-digit phone & Haversine distance <= 75m)    |
                 | (Auto-upserts newly discovered stores into catalog)          |
                 v                                                             v
+-----------------------------------+                         +---------------------------------+
| data/pharmacies_master.json       |                         | data/duties_raw.json            |
| (9,103 nationwide stores baseline)|                         | (Active shifts 1-to-1 schema)   |
+-----------------+-----------------+                         +----------------+----------------+
                  \                                                            /
                   \----------------------------+-----------------------------/
                                                |
                                                v
                               +---------------------------------+
                               |       package_dataset.py        |
                               +----------------+----------------+
                                                |
                                                v
                               +---------------------------------+
                               | pharmacies_latest.min.json      |
                               | pharmacies_latest.min.json.zst  |
                               +----------------+----------------+
                                                |
                                       GitHub Release CDN
                                                |
                                                v
                               +---------------------------------+
                               | PharmaFinder Expo Mobile App    |
                               | (Offline AsyncStorage + Geo)    |
                               +---------------------------------+
```

---

## Data Files & Purpose

| File | Status | Size | Purpose |
|---|---|---|---|
| `data/pharmacies_master.json` | **Committed (Core)** | ~4.9 MB | **Permanent national registry** of 9,103 pharmacies across all 505 Greek municipalities. Live syndicate feeds only publish stores *on duty right now* (~400 stores). This master catalog preserves all Greek pharmacies for regular daytime lookup, search, and navigation. Automatically enriched and self-healed by the scraper when new stores appear. |
| `data/duties_raw.json` | **Generated (Gitignored)** | ~70 KB | Ephemeral crawl artifact containing today's and tomorrow's duty shifts normalized to the mobile app schema. Consumed by `package_dataset.py`. |
| `data/cities.json` | **Legacy** | ~56 KB | 505 Greek municipal slugs used during initial registry bootstrapping. Kept for reference. |

---

## Primary Data Sources

1. **ΦΣΑ Attica (`fsa-efimeries.gr`)**:
   - Official Pharmaceutical Syndicate of Attica (Athens, Piraeus, East/West Attica).
   - Serves high-precision coordinates, phone numbers, and full duty intervals (morning, afternoon, overnight) in a single structured query.
2. **ITeQ Regional Network (`*.efhmeries.gr`)**:
   - Covers 30+ regional pharmaceutical syndicates across Greece:
     - Crete (`chania`, `heraklion`, `rethymno`, `lasithi`)
     - Northern Greece (`thess`, `serres`, `kavala`, `drama`, `rodopi`, `xanthi`, `evros`, `pieria`, `kozani`, `kastoria`, `florin`)
     - Central & Western Greece (`patras`, `larissa`, `magnisia`, `trikala`, `karditsa`, `ioannina`, `artas`, `preveza`, `aitoloakarnania`, `evia`, `fthiotida`)
     - Aegean & Ionian Islands (`rodos`, `dodekanisa`, `lesvos`, `chios`, `samos`, `corfu`)

---

## Release Artifacts

Every scheduled GitHub Actions run (or manual `workflow_dispatch`) builds and publishes:

| Asset | Description | Compression | Size |
|---|---|---|---|
| `pharmacies_latest.min.json` | Complete nationwide pharmacy registry with today/tomorrow duty shifts | Uncompressed JSON | ~3.7 MB |
| `pharmacies_latest.min.json.zst` | High-efficiency mobile payload | Zstandard (level 19) | ~449 KB |

### Direct CDN URL
```
https://github.com/<owner>/pharmafinder-scraper/releases/latest/download/pharmacies_latest.min.json
```

---

## GitHub Actions Automation

Workflow: [`.github/workflows/update-pharmacies.yml`](.github/workflows/update-pharmacies.yml)

- **Schedules (UTC):**
  - `17 4 * * *` (07:17 Athens — morning opening rota switch)
  - `47 10 * * *` (13:47 Athens — afternoon handover / evening rota)
  - `23 16 * * *` (19:23 Athens — overnight emergency rota switch)
  - `17 21 * * *` (00:17 Athens — date rollover / pre-warm tomorrow)
- **Permissions:** `contents: write` (for committing updated master catalog and publishing releases).
- **Automated Pipeline:**
  1. Sets up Python 3.12 with dependency caching.
  2. Runs `python multi_source_scraper.py` to scrape official syndicates, update duty rotas, and self-heal the master catalog.
  3. Runs `python package_dataset.py` to merge shifts, minify payload, and compress via `zstandard`.
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

### 2. Crawl Syndicates
```bash
python multi_source_scraper.py
```
Scrapes ΦΣΑ Attica and regional syndicate feeds, matches duty shifts to `data/pharmacies_master.json`, upserts new stores, and dumps `data/duties_raw.json`.

### 3. Package & Compress
```bash
python package_dataset.py
```
Merges fresh duty shifts with `data/pharmacies_master.json`, produces `pharmacies_latest.min.json`, compresses with `zstandard`, and generates release tags (`tag.txt`, `release_notes.md`).

---

## Mobile Client Integration

In the Expo mobile app ([`pharmafinder`](../pharmafinder)):

1. Configure CDN URL in `.env`:
   ```bash
   EXPO_PUBLIC_PHARMACIES_CDN_URL=https://github.com/<owner>/pharmafinder-scraper/releases/latest/download/pharmacies_latest.min.json
   ```
2. The client fetches and caches the dataset in `AsyncStorage` on startup (`src/entities/pharmacy/api/pharmacyApi.ts`).
3. Haversine distance, radius filtering, search, and duty mode checks (`now` / `today` / `tomorrow`) execute client-side instantly with zero network delay or API rate limits.

---

## Schema

```json
{
  "updated_at": "2026-10-09T00:20:00Z",
  "count": 9103,
  "on_duty_today": 321,
  "on_duty_tomorrow": 298,
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

---

## License

This project is licensed under the [GNU Affero General Public License v3.0 (AGPL-3.0)](LICENSE).
