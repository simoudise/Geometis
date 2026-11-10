# TLP Phase 2 on the April 2024 trips

## Step 1: crosswalk coverage (job 080, 10 November 2026)

`crosswalk_coverage.sql` joins every April 2024 vendor link (48.8 million) to the OSM-way-to-URN crosswalk of
graph `us-ca-contra-costa-5` (Overture 2026-10-21.0) by OSM way id. It returns aggregates only.

| Vendor mode | Links | km | Links with a way id | Distance resolved (of links with a way id) |
|---|---|---|---|---|
| driving | 23.2 M | 1,817,964 | 99.8% | 99.8% |
| transit_bus | 16.9 M | 916,494 | 100% | 99.3% |
| transit_walking | 4.8 M | 251,400 | 99.2% | 99.7% |
| walking | 1.7 M | 63,868 | 89.9% | 99.7% |
| cycling | 0.9 M | 44,943 | 96.0% | 99.7% |
| transit_subway (BART) | 0.8 M | 109,656 | 99.5% | 0% |
| driving_walking | 0.3 M | 12,490 | 100% | 100% |
| transit_rail | 656 | 63 | 100% | 0% |

Findings:
1. **Road and path modes resolve almost completely.** The crosswalk covers 99.3 to 99.8 per cent of the distance
   on links that carry a way id, so geometric fallback is needed for well under 1 per cent of road distance.
2. **BART does not resolve at all.** The graph has no rail layer: Stage 1 loads Overture road and pedestrian
   segments only, and BART runs on railway ways. BART links account for most of the 106,641 km of way-bearing distance that does not
   resolve; road modes leave about 0.2 to 0.7 per cent unresolved. Every
   trip with a BART leg is therefore only partly conflated (mean 54 per cent of distance for bus-plus-BART trips,
   12 per cent for BART-only trips). Gap against v19: Stage 1 should add Overture's rail segments, or Stage 3 should
   represent rail lines from GTFS shapes, before transit trips can be conflated end to end.
3. **Way versions.** Where a way resolves, the vendor's 2024 way version equals the crosswalk's 2026 version on
   49 per cent of links and is older on 51 per cent; it is never newer. A changed version means the way was edited,
   not necessarily moved, so entry and exit fractions must come from geometry, not from the way alone.
4. **Walking links without a way id.** About 10 per cent of walking links carry no way id. These need the
   geometric fallback.

Next: entry and exit fractions on each URN from the link end coordinates (on the Mac mini only), and the rail layer.
