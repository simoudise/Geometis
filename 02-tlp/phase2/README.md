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

## Step 3: conflation of all April 2024 links (job 091, 10 November 2026)

`conflate_april.sql` writes `tlp.link_conflation` on the Mac mini (Tier 3: it holds trip ids and stays there). Each row
is one piece of a vendor link on one URN, with entry and exit fractions in the direction of travel and the method used.
The "way" method splits a link across the URN pieces of its OSM way when both link ends lie within 15 m of the merged way
line; the "fallback" method takes the nearest piece of a layer that suits the mode when both ends lie within 30 m of it.
The job took 26 minutes and wrote 69.2 million rows (64.2 million by way, 5.1 million by fallback); free disk on the Mac
mini fell from 184 GB to 144 GB. Every entry and exit fraction lies in [0, 1].

| Vendor mode | Links | Matched | Of matched: by way | Of matched: by fallback | URN pieces per matched link |
|---|---|---|---|---|---|
| driving | 23,157,804 | 99.0% | 91.1% | 8.9% | 1.37 |
| transit_bus | 16,873,772 | 99.1% | 88.6% | 11.4% | 1.51 |
| transit_walking | 4,805,261 | 99.0% | 92.0% | 8.0% | 1.56 |
| walking | 1,711,900 | 97.5% | 86.6% | 13.4% | 1.43 |
| cycling | 945,386 | 98.5% | 89.6% | 10.4% | 1.51 |
| transit_subway (BART) | 824,682 | 99.7% | 50.8% | 49.2% | 1.03 |
| driving_walking | 327,530 | 100% | 94.0% | 6.0% | 1.34 |
| transitwait | 161,207 | not conflated (no extent) | | | |
| transit_rail | 656 | 0% | | | |

Gaps:
1. **Fallback gives one URN per link, which suits most fallback links (jobs 092-093).** On a 10 per cent sample of trips,
   fallback links are short (median 14 to 78 m by mode; 90th percentile 50 to 302 m), their ends lie on the chosen URN
   (median offset 0.0 to 4.8 m), and for driving, bus and BART the span on the URN averages 94 to 98 per cent of the
   vendor's distance. The exception is the long tail: links over 200 m are 5 to 11 per cent of driving, bus and BART
   fallback links but carry 20 to 45 per cent of their fallback distance, and a single URN cannot hold them. These need
   a routed fallback (shortest path on the layer graph between the two projected ends). pgRouting is not installed on
   the Mac mini; the routed fallback would use pgRouting (a Homebrew install) or a SciPy shortest-path step. Overall it
   affects about 0.5 per cent of links and 2 to 4 per cent of link distance, so it is deferred behind endpoint
   attribution.
2. **Why half the BART links fall back (job 092).** The cause is the referenced way, not the rail layer: 99.5 per cent of
   BART fallback links have an end more than 15 m from their own way's line (half between 250 and 500 m), yet their ends
   lie on some rail piece (median offset 0.0 m). The likeliest explanation is that BART ways were split between 2024 and
   2026: the old way id stays with one part of the track, and links on the split-off part now point at a way that no
   longer covers them. The nearest-piece fallback handles these correctly because the links are short (median 78 m).
3. **transit_rail (Amtrak, 656 links) and transitwait** are not conflated. transitwait has no extent; Amtrak is too small to
   matter now.
4. **Disk.** The table and its index use about 40 GB. June will need as much again; check free space before running it.
