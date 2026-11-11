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
