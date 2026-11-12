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
   either by routing or by map-matching observed positions. This finding alone does not tell the two apart. The Phase 0
   evidence (identical route interiors for repeated trips, timing at fixed speeds) was first read as pointing to
   routing; the sub-path test below (job 109) shows that driving-only routes are not pure origin-to-destination
   routing, so "snapped to OSM; router versus map-matcher unresolved" is the accurate statement. It does
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

## Endpoint attribution: where the April trip ends lie (job 095, 11 November 2026)

Before building attribution (candidate claim 2), job 095 measured where April trip destinations lie, on a 5 per cent
sample of trips (21,637), against the graph's road and path network, building footprints and places. Aggregates only.

| Trip mode | Trips | Inside a building footprint | Median distance to the network | Within 1 m of the network | Median distance to the nearest place |
|---|---|---|---|---|---|
| multimodal (mostly driving + walking, and transit) | 13,223 | 0.2% | 0.0 m | 98.4% | 56 m |
| walking | 4,329 | 24.2% | 12.9 m | 6.4% | 68 m |
| transit_walking | 1,748 | 0.2% | 0.0 m | 98.7% | 81 m |
| driving | 1,431 | 14.0% | 16.7 m | 5.0% | 83 m |
| cycling | 906 | 18.2% | 9.8 m | 7.9% | 70 m |

Findings:
1. **Multimodal and transit trips end on the network, not at the place.** Their destinations sit on a road or path line
   (98 per cent within 1 m) and almost never inside a footprint. Their end point is where the vendor's route stops, so
   footprint containment cannot score them, and attribution has to work from distance, dwell and time alone.
2. **Single-mode trips end off the network.** Walking, driving and cycling destinations lie a median 10 to 17 m from the
   network and 14 to 24 per cent fall inside a footprint, which looks like a device position, possibly with privacy
   jitter. These are the trips where containment can help.
3. **Two of the planned reference sets need rethinking.** (a) Transit-access ends: the vendor builds transit legs from
   GTFS, so walk ends at a boarded stop coincide with the GTFS stop position, and nearest-stop attribution would be right
   by construction; the test would be circular, as the Phase 0 transit-access reference set was. (b) Single-place
   footprints: the plan selects these "by footprint geometry alone, so the test does not reuse the features the
   attribution method scores", but v19 section 10.3.2 scores footprint containment, so the method and the reference set
   share that feature. Either containment is removed from the method for this test, or the reference set needs another
   source of truth. Decisions needed from Evangelos before attribution v0 is built.

## Checks from the second outside review (jobs 109 and 110, 12 November 2026)

The second Fable review (Chat 2) proposed four checks of whether the vendor's trips are routed or observed.
`chat2_tests.sql` runs them on April and June 2024; `chat2_t2_drive_walk.sql` repeats the sub-path test on the driving
legs of "driving+driving_walking" trips. Aggregates only.

**T4, what "multimodal" covers.** Trips by mode set: driving + driving_walking 38.3%; transit (bus, BART or rail, with
walking and waits) 22.6%; walking 19.7%; transit_walking only 7.6%; driving only 7.1%; cycling 4.6%. A 5 per cent sample
puts trips with at least one transit leg at 22.5%. The "about 70 per cent of trips on the network" in the endpoint
table above is therefore mostly drive-and-walk trips, not transit trips. A 22.5 per cent transit share is still far
above any plausible share for Contra Costa, so the panel probably over-represents transit riders.

**T1, driving link speed.** On 5,257,096 driving links of driving-only trips (at least 50 m, positive duration), the
speed computed from link timestamps and distance equals the vendor's speed field on 100 per cent of links, so the two
are one calculation. On 1,841 OSM ways with at least 10 traversals at 07-09h and at 01-04h, the ratio of peak to night
speed has a median of 1.000 (10th to 90th percentile 0.981 to 1.013): no congestion appears at peak. On 3,841 ways
with at least 30 traversals, the coefficient of variation of speed has a median of 0.028 and is below 1 per cent on 26
per cent of ways. Driving link timing is modeled end to end, which rules out the alternative that real trip durations
were spread across links by a speed table.

**T3, repeat of single-mode trip ends.** Of 692,514 single-mode trip ends, 36.6 per cent recur for the same device at
exactly the same coordinates, and 44.6 per cent recur within about 11 m. About four in five repeats are exact, which
fits a stored place per device (for example, a cluster centre) rather than a fresh position fix each time.

**T2, sub-path consistency.** Anchor links (way id plus direction) appear in at least 20 trips from at least 5 devices.
For each anchor and each target distance (1.5, 3.5 and 8 km along the trip), the first later anchor at least that far
forms a pair; pairs are kept when at least 5 trips from at least 3 devices traverse them. The table gives the share of
pairs whose trips all follow one interior link sequence.

| Leg type | Group | 1.5-2.3 km | 3.5-5.3 km | 8-12 km |
|---|---|---|---|---|
| Driving (driving-only trips) | all | 0.828 | 0.809 | 0.802 |
| | April | 0.871 | 0.839 | 0.813 |
| | June | 0.877 | 0.857 | 0.840 |
| | peak | 0.894 | 0.874 | 0.856 |
| | off-peak | 0.863 | 0.842 | 0.824 |
| Walking legs of transit trips (positive control) | all | 0.999 | 0.999 | 1.000 |

Reading, by the review's rules: the positive control (legs built by the vendor's trip planner from GTFS) gives one
sequence almost always, so the test detects planner output. Driving-only routes give one sequence for 80 to 89 per cent
of pairs, falling slowly with distance. That is neither least-cost routing between origin and destination (which would
give about 99 per cent everywhere) nor dense observation (which would give low shares). It fits least-cost filling
between intermediate observed positions, or observed driving with strong habits; this test does not separate those two.
Pooling April and June lowers the share, so some second sequences probably come from map differences between the
months, not from different behaviour.

Limits: the review's condition that the graph offers a second path no more than 1.3 times longer was not applied
(no routing engine on the database); pairs with no alternative path raise the one-sequence share, so the driving shares
are upper bounds for pairs that have a real choice. The link key uses coordinates rounded to about 11 m, so small
snapping differences can create a spurious second sequence. The data contain no negative control.

Wording for reports: "Link-level times and speeds are produced by a speed model; this is established for every mode.
Transit legs are built by a trip planner from GTFS. Driving routes are snapped to a 2024 OpenStreetMap snapshot; they
are not pure origin-to-destination routes, and the data do not yet show whether the path between observed positions is
reconstructed by least-cost filling or observed."
