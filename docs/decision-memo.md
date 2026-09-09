# Decision Memo: Evening Rebalancing for the Monument Corridor

**Recommendation:** Establish a dedicated evening rebalancing route
(6:00-9:00 PM daily) serving the National Mall monument corridor —
Lincoln Memorial, Jefferson Memorial, the Smithsonian/National Mall
cluster, and Gravelly Point — to return bikes that accumulate there
from one-way evening leisure trips back into general circulation.

**Estimated impact:** across just the five worst-imbalanced station
pairs in this corridor, **7,500 net excess one-way trips** ended at
these locations without a matching departure over the observed period
— bikes that are, in effect, stranded there every evening unless
manually moved.

## The three numbers behind this

1. **7,616 evening arrivals vs. only 116 morning departures** across
   the top 5 imbalanced pairs — a system that is almost entirely
   one-directional in the evening at these specific locations, not a
   normal two-way flow.
2. **197-to-1 imbalance at the single worst pair** (Jefferson Memorial
   ↔ Lincoln Memorial): 1,577 evening arrivals against just 8 morning
   departures.
3. **All five of the worst-imbalanced pairs are monument/tourism
   destinations**, not office districts — this is not the classic
   AM/PM office commute pattern the "commute corridor" analysis was
   originally designed to catch. It's evening leisure and tourist
   riding concentrated around the Mall, and it produces a more
   extreme, more predictable imbalance than a typical commute corridor
   would.

## Why this is the right recommendation, not the empty-hours fix

The dashboard also surfaces a second real issue — station-level
empty-hours (worst case: Briggs Chaney & Castle Dr, 57 empty-hours;
several transit-hub stations like Franconia-Springfield Metro North
and Shady Grove Metro West flagged `investigate_demand` rather than
`low_capacity`, meaning the emptying looks demand-driven, not just a
too-small dock). That's real and worth a follow-up study — but it's
observed over a much shorter, more recent window (days to weeks of
live polling) than the corridor finding, which is grounded in the full
2024-2025 trip history (12.8M trips). The corridor imbalance is the
better-supported, more actionable finding to act on first.

## Appendix: assumptions and caveats

- **Corridor definition:** morning = 06:00-09:00 departures, evening =
  16:00-19:00 returns in the reverse direction. A station pair needs
  ≥20 combined trips to be considered ("has_meaningful_volume") — all
  five pairs above clear this by a wide margin.
- **This corridor finding is NOT a literal daily commute pattern.**
  The station names make clear this is monument-district leisure/
  tourism riding, not office commuting. The metric was built to catch
  commute asymmetry generally; it caught a different, equally real
  operational problem instead. Framing it accurately as "evening
  leisure riding" rather than "commuting" avoids a wrong operational
  story reaching whoever reads this memo next.
- **Station-status data (empty-hours, capacity exceedance) currently
  covers a much shorter window** than the trip-history-based findings
  — continuous live polling only began during this project, while
  trip history goes back across all of 2024-2025. The empty-hours
  numbers should be treated as an early signal, not yet a fully
  representative annual pattern.
- **Capacity exceedance join coverage is 97.7%**, not 100% — a small
  slice of demand-hours couldn't be matched to a live capacity value
  because no reliable ID crosswalk exists between historical trip
  station codes and the live GBFS feed (see `docs/DECISIONS.md`); the
  join used here is name-based and could silently miss a renamed
  station.
- **Total trip volume in the analyzed period: 12,776,970 trips**
  (2024-01 through 2025-12).
