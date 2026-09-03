# City selection — Week 0 verification

Checked live, 2026-09-03.

## Candidates checked

| Check | Divvy (Chicago) | Capital Bikeshare (DC metro) |
|---|---|---|
| `gbfs.json` resolves, no auth | Yes | Yes — `https://gbfs.capitalbikeshare.com/gbfs/gbfs.json` |
| `station_status` freshness | `last_reported` seconds old at fetch | Live, well under 5-min bar |
| Historical trip files | Multi-year, S3-hosted | **2010–present**, S3-hosted (`capitalbikeshare-data`) |
| Station count | ~1,000–1,900 | ~700–900, multi-jurisdiction (DC, Arlington, Alexandria, Montgomery Co., Prince George's Co., Fairfax, Falls Church) |
| Known schema quirks | None flagged | Documented ID/schema changes across years — a bonus, well-understood "schema drift" lesson |

## Decision: Capital Bikeshare

- Deepest available public trip history (2010+) of any GBFS system checked
- Lighter station count than Divvy — friendlier for a laptop
- Multi-jurisdiction structure gives the Week 5 "neighboring station state"
  spatial feature real texture — station density and demand patterns differ
  meaningfully between, say, downtown DC and Reston, VA
- Well-trodden dataset (`bikerentaldata` R package, multiple public
  case studies) — low risk of undocumented format surprises

## Sources checked directly

- `https://gbfs.capitalbikeshare.com/gbfs/gbfs.json` — discovery doc, live
- `https://gbfs.lyft.com/gbfs/1.1/dca-cabi/en/station_information.json` — real station data
- `https://capitalbikeshare.com/system-data` — official trip data page, License Agreement
- `https://s3.amazonaws.com/capitalbikeshare-data/` — trip history bucket
