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

### Rerun with the rail layer (job 085, 10 November 2026)

After Stage 1 gained a rail layer (`gkg/stage1_rail.py`, job 084), BART links resolve: 99.5 per cent of BART links and
100 per cent of their way-bearing distance map to rail segment URNs. Trips that combine bus and BART now resolve
99.8 per cent of their distance on average (was 54 per cent), and BART-only trips 100 per cent (was 12 per cent).
Way-bearing distance that does not resolve fell from 106,641 km to 10,257 km. The 656 `transit_rail` links (Amtrak)
still do not resolve; they are too few to matter for now and are left as an open item.

## Step 2: entry and exit positions on the graph (job 090, 10 November 2026)

`entry_exit_sample.sql` takes a 1 per cent sample of April 2024 trips (479,195 links with a way id), merges the graph
pieces that carry each OSM way into one line (99.4 per cent of the 13,323 sampled ways merge cleanly), projects each
link's start and end coordinates onto that line, and compares the span between the two projections with the vendor's
link distance. Aggregates only.

| Vendor mode | Links | Median distance of link ends from the graph | Both ends within 15 m | Median span / vendor distance | Span within 10% or 10 m |
|---|---|---|---|---|---|
| driving | 224,451 | 0.0 m | 93.2% | 1.000 | 92.7% |
| transit_bus | 165,932 | 0.0 m | 91.3% | 0.999 | 90.9% |
| transit_walking | 47,256 | 0.0 m | 94.1% | 0.999 | 93.0% |
| walking | 15,657 | 0.0 m | 97.1% | 0.999 | 96.4% |
| cycling | 9,152 | 0.0 m | 92.1% | 0.998 | 92.3% |
| transit_subway | 7,690 | 0.0 m | 89.9% | 0.973 | 80.4% |
| driving_walking | 3,113 | 0.0 m | 96.5% | 1.187 | 25.2% |

Findings:
1. **Vendor link ends lie exactly on OSM way geometry.** The median distance from a link end to the graph is 0.0 m in
   every mode. Raw device positions would scatter by several metres, so the vendor placed these points on the map,
   either by routing or by map-matching observed positions. This finding alone does not tell the two apart; the Phase 0
   evidence (identical route interiors for repeated trips, timing at fixed speeds) is what points to routing. It does
   mean entry and exit fractions can be read straight off the graph for about 91 to 97 per cent of links.
2. **The remaining 3 to 9 per cent** have an end more than 15 m from the 2026 graph line. The likely cause is way
   geometry edited between the vendor's 2024 OSM and the October 2026 Overture release (half of the resolved ways
   changed version). These links need a geometric fallback: match the link to the graph by shape, not by way id.
3. **BART spans run 3 per cent short** of the vendor distance at the median, and only 80 per cent fall within 10 per
   cent. Rail ways are long and the vendor's distances may follow the track differently; not a concern for
   conflation, but rail segment lengths should not be used to re-derive vendor distances.
4. **driving_walking links are 19 per cent longer on the graph** than the vendor says, and only a quarter agree. These
   are short links between parking and the street; the vendor may measure them to a point inside a parking lot or
   building. Open item.

Next: write the conflated links (trip, link, URN, entry and exit fractions) for all April trips into a Tier 3 table on
the Mac mini, with the fallback for the links in finding 2.
