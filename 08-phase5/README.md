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
