# Ontology sufficiency audit: state (update at every break)

This file records the state of the ontology sufficiency audit. The GKG chat owns `docs/HANDOFF.md`, the ontology files and the builder; this audit does not edit them.

## Scope and rules (Evangelos, November 22, 2026)

- The audit checks whether the five ontologies and the GKG data can answer the competency questions drawn from the fingerprint documents, the city evidence packs and the Test 3 draft plan. Part 1 is in Drive SPECTRA: "GeoMetis ontology sufficiency audit part 1 (draft) 2026-11-22 10.15.md" with its CSV catalog.
- All work covers San Francisco only until Waymo approves a project. Step 4 (New York, Los Angeles, Chicago, Boston) is dropped until then.
- Mac mini job numbers for this audit: main queue 300-349, status lane s300-s349. Queries are read-only.
- The GKG chat is the only chat that edits ontology files. This audit sends it design notes after Evangelos approves them.
- Decisions recorded on November 22: O1 to O5 go into UKO and REO; pack evidence (O7) stays in the scoring spreadsheets until Test 3 part 3a shows that the graded factors carry signal. Police-reported incidents other than collisions enter as secondary layers: curb and right-of-way violations, dangerous-driving enforcement (a secondary outcome only, never a crash-prediction input), and incidents involving automated vehicles. Crash-linked records (hit-and-run reports, arrests after a collision) are crash-derived.

## State on November 22, 2026, 10:05 Pacific

- The GKG chat released UKO 15.7 and REO 1.7.0 (commit 0e5ebe3) with audit items O1, O2, O3 and O12.
- Recheck against the new release and the San Francisco data (status jobs s300, failed on a psql option; s301, done): 42 questions; 5 fully covered (T3-1, T3-2, T3-3, F6, F12), 14 partly covered, 23 not covered. Catalog: `docs/ontology-audit-catalog.md`.
- San Francisco facts from s301: 61,175 road segments, grade on 100 percent, posted speed limit on 21.8 percent; 261 tracts with population (100 percent) and median income (94.3 percent), ACS 2020-2024; 39,669 crash records, 39,614 linked to a segment, KABCO K 387, A 2,973, B 11,204, C 25,105; no control types and no volume observations loaded.
- Next: design note for O4 (place statistics, which the San Francisco tracts already hold without UKO properties), O5 (the fingerprint) and the REO class for non-collision police incidents. Then step 3: a query for each covered or partly covered question against the San Francisco graph.

## State on November 22, 2026, 11:45 Pacific

- Design note for O4, O5 and the non-collision incident class: `docs/ontology-design-note-o4-o5-incidents.md` (also in Drive SPECTRA). It awaits Evangelos's three decisions: SOSA alignment, tract-level fingerprints for San Francisco now, and counts-only storage of incidents.
- After approval the GKG chat implements the note; this chat then runs the acceptance-test queries (jobs 300-349).

## State on November 22, 2026, 11:50 Pacific

- Evangelos approved the design note (11:34): SOSA alignment; tract-level fingerprints for San Francisco now; incidents as monthly counts (with the time-of-day and weekday split and per-source place unit that Claude added). The note now records the San Francisco sources checked from catalog pages.
- Next: the GKG chat implements UKO 15.8, REO 1.8.0 and MLO 1.8.0 and loads San Francisco data; this chat then runs the acceptance-test queries.
