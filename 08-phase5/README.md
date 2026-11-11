# Phase 5: retrospective intervention test

Phase 5 compares the System's predicted crash change at built safety projects with the observed change (empirical
Bayes before-after) and with the Highway Safety Manual method. Crash data: TIMS injury crashes 2015 to 2025 for Contra
Costa County and San Francisco (Stage 4). With three years before and three after, a project qualifies if construction
finished between 2018 and 2022. Project tables are query outputs and stay on the Mac mini (work/phase5); this folder
holds code and notes only.

## Source 1: Caltrans HSIP delivery status (11 November 2026)

Caltrans Local Assistance publishes every Highway Safety Improvement Program project with its agency, location,
description of work, construction authorization date and close-out date ("List of All Projects", status as of
1 October 2026; saved as work/phase5/sources/hsip_allprojects_2026q4.xlsx). The list holds 2,380 projects statewide.

Contra Costa County agencies and San Francisco hold 109 of them. Twenty had construction authorized between 2016 and
2021, the authorizations most likely to finish construction between 2018 and 2022 (work/phase5/hsip_candidates_2016_2021.csv):
Contra Costa County (unincorporated roads) 12, Pittsburg 3, and one each for Lafayette, Pleasant Hill, Richmond, San
Pablo and SFMTA. Inside the two graph extents (the five cities plus 3 km, and San Francisco) only about six remain.

Findings:
1. **HSIP alone is too small.** The plan expected this risk ("the five cities alone may yield too few built projects").
   Close-out dates trail construction by one to three years, so each project's construction-completion date still has
   to come from the agency.
2. **Most Contra Costa HSIP projects lie outside the graph.** They are on unincorporated rural roads (Marsh Creek Road,
   Byron Highway, San Pablo Dam Road). The Knowledge Builder takes any geofence, so a Contra Costa County geofence would
   bring them inside a graph; that is a build, not a design change.
3. **The largest source is likely SFMTA.** San Francisco's Vision Zero and quick-build programs completed many
   corridor projects between 2018 and 2022 inside the San Francisco graph. Next step: compile SFMTA's project records with
   completion dates and treatments.

## Source 2: SFMTA quick-build corridors (11 November 2026)

SFMTA's "Vision Zero Quick-Build Project Updates, December 2022" (saved in work/phase5/sources) lists 28 completed
corridor projects with their completion month, plus Geneva Avenue (Mission to Prague) on a combined line. Completions
by year: 2019, 7; 2020, 12; 2021, 6; 2022, 3. All lie inside the San Francisco graph. Treatments come from each
project's scope (lane reductions, protected bikeways, painted safety zones, daylighting, signal timing); the December
2022 table gives scope only for projects still in design, so completed scopes must come from the earlier updates
(December 2021 and October 2020 are saved) or each project page. The table is in work/phase5/sfmta_quickbuild_completed.csv.

## Source 3: SFMTA traffic calming devices (11 November 2026)

SFMTA publishes its traffic calming devices as an ArcGIS layer (DataSF master FeatureServer layer 51, 1,686 features,
saved as work/phase5/sources/sfmta_traffic_calming.geojson) with install month and year, street, limits and measure.
Devices installed 2018 to 2022: 501, mostly speed humps (261) and speed cushions (212), plus 15 raised crosswalks and
13 speed tables. 603 features carry no install year.

Findings:
1. **San Francisco supplies enough projects.** About 29 corridor projects and 501 calming devices completed between
   2018 and 2022, against about six HSIP projects inside the Contra Costa graph. Speed humps and cushions sit mostly on
   residential streets with few injury crashes each, so they would be tested as a group by treatment, not one by one.
2. **The pandemic falls inside most before-after windows.** Crashes in San Francisco fell from 3,909 in 2019 to 2,706 in
   2020. An empirical Bayes design with a comparison group of untreated sites absorbs a citywide drop; a simple
   before-after count would credit the pandemic to the projects.
3. **SFMTA has published its own before-after results** for these programs (2022 Safe Streets Evaluation). They are a
   second check on our observed effects, not a replacement for them.

## Corridors on the graph and a first crude count (job 098, 11 November 2026)

`locate_projects.py` places each completed quick-build corridor on the San Francisco graph (street-name segments on the
shortest path between the intersections with the two limit streets) and counts TIMS injury crashes attached to those
segments and nodes in the 36 months before and after the completion month. The Embarcadero (Bay to North Point, Mission
to Harrison) is split into its two pieces, giving 30 rows; scopes come from the December 2021 and December 2022
updates.

23 of 30 corridors were placed. The seven not placed are 3rd Street (Berry to Terry Francois), Howard Street
(Embarcadero to 3rd), Indiana Street, Alemany Boulevard, Beale Street, Brannan Street and the Evans/Hunters Point/Innes
corridor. In each case a limit street's name did not match a graph name (for example "Embarcadero" against "The
Embarcadero") or the corridor runs along more than one street; these need name aliases or manual end points.

On the 23 placed corridors: 998 injury crashes before and 829 after. Citywide injury crashes in the same windows predict
862 after, so the corridors ran 3.8 per cent below the citywide trend. Killed-or-severely-injured crashes went from 76
to 74. Crashes involving a pedestrian or cyclist went from 528 to 326.

This is a crude comparison, not the Phase 5 result. It ignores regression to the mean (SFMTA chose these corridors
because they had many crashes), it uses all of San Francisco as the comparison group rather than similar untreated
streets, and the pedestrian and cyclist counts have no citywide comparison yet. The empirical Bayes estimate with safety
performance functions replaces it. Two placements also need checking: the Embarcadero pieces show 0 to 7 crashes, which
is low for that street, so crashes there may be attaching to a parallel segment.

## Traffic volumes: what is available (11 November 2026)

Highway Safety Manual safety performance functions predict crashes from traffic volume (AADT), so both the HSM baseline
and a standard empirical Bayes estimate need a volume for every treated and comparison segment. The public sources found:

- **SFMTA traffic counts, 1993-2015** (PDF of counts at selected locations): old and sparse; no counts after 2015.
- **Caltrans traffic census:** state highways only.
- **SFCTA SF-CHAMP model volumes:** modeled volumes on every link, available on request from SFCTA's Model Data Service
  Bureau (data@sfcta.org). The page states no fee and no terms for private firms; a request must say what the data is
  for.
- **Community Telraam sensors:** a few streets only.
- **Commercial:** INRIX Volume Profiles (already in the INRIX request), StreetLight, and Replica (a competitor).

There is no trip panel for San Francisco, so the City Data exposure used in Contra Costa does not exist there.

Design that needs no volumes. Empirical Bayes needs an expected crash frequency for a site, not volume as such. A
negative binomial model fitted to crash counts on untreated segments, with graph attributes as predictors (road class,
lanes, speed limit, grade, intersection density, transit stops, land use near the segment), gives that expected
frequency. The HSM baseline then becomes "EB expected crashes times the Clearinghouse CMF". Volume would make both
better but is not required to run the test, and a volume-free SPF built from graph context is closer to candidate claim
6 than an AADT SPF would be. Decision needed: run the volume-free design now, request SF-CHAMP volumes from SFCTA in
parallel, or wait for purchased volumes.

## Corridor placement, second pass (job 099, 11 November 2026)

Three fixes to `locate_projects.py`: a leading "The" is dropped before name matching ("Embarcadero" now matches "The
Embarcadero"); when a limit street shares no node with the corridor street, the corridor street's nodes within 60 m of
the limit street are used; and segments of the corridor street that run alongside the path (both ends within 30 m of
it) are added, so that both carriageways of a divided street count. A corridor along several streets lists them
separated by "/" (Evans Avenue/Hunters Point Boulevard/Innes Avenue).

27 of 30 corridors are now placed. Still not placed: 3rd Street (Berry to Terry Francois), Indiana Street (24th to
Cesar Chavez) and Beale Street (Market to Natoma); these need manual end points. The divided-street fix explains the
low Embarcadero counts: The Embarcadero (Mission to Broadway) went from 7 to 27 crashes before, and Market Street from
188 to 279.

Crude count on the 27 placed corridors: 1,346 injury crashes before, 1,061 after; the citywide trend predicts 1,157
after, so the corridors ran 8.3 per cent below it. Killed or severely injured: 110 to 96. Pedestrian or cyclist
involved: 694 to 414. The same caveats as before apply: no correction for regression to the mean, the whole city as
the comparison group, and no citywide comparison for the pedestrian and cyclist counts.

## Traffic calming devices (job 100, 11 November 2026)

`traffic_calming.sql` loads SFMTA's traffic calming layer, keeps devices installed 2018 to 2022 and marked Complete
(490; 477 with an install month), places each on the nearest San Francisco segment of the named street within 50 m
(449 devices on 441 segments), and counts injury crashes attached to those segments (not to intersections) in the 36
months before and after the earliest installation on each segment.

| Measure | Segments | Crashes before | Crashes after | After expected from the citywide trend |
|---|---|---|---|---|
| Speed hump | 220 | 17 | 7 | 15 |
| Speed cushion | 198 | 27 | 24 | 26 |
| Raised crosswalk or speed table | 23 | 3 | 4 | 2 |
| All | 441 | 47 | 35 | 43 |

Finding: these streets carry very few injury crashes (47 in three years across 441 segments), so the devices cannot
support a test on their own, even grouped by measure; the confidence intervals would span any plausible effect. The
quick-build corridors (1,346 crashes before) carry the Phase 5 test. The devices can join a pooled estimate for
residential streets, or be dropped.
