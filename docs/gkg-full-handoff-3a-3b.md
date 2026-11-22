# Starting point for Chats 3a and 3b: the GKG full build

Read `docs/HANDOFF.md` and `docs/test-plan-2026-11.md` first. This file tells a new chat how to use the full
geospatial knowledge graph (GKG) that the GeoMetis-GKG chat built on November 20, 2026. The relation definitions are
in `docs/gkg-full-data-dictionary.md`. The build report with counts and checks is in Drive, SPECTRA > GKG FULL.

## What exists

- Geofences: `us-ca-san-francisco` and `us-ca-contra-costa-5` (Antioch, Concord, Pittsburg, Pleasant Hill,
  Walnut Creek). The two extents overlap, so the same Overture feature can appear in both with two entity keys.
- Database `geometis`, schema `gkg`, on the Mac mini. The earlier builder stages (1 to 6) are unchanged. The full
  build added `gkg.entity`, `gkg.entity_type`, `gkg.aux_entity`, `gkg.relation_type`, `gkg.provenance`, `gkg.edge`,
  `gkg.distance_measurement`, `gkg.edge_rejected` and `gkg.class_closure`, and the views `gkg.edge_named`,
  `gkg.rel_very_near` and `gkg.edge_for_crash_prediction`.
- Ontologies: coordinated release 2026-11-22 in `01-ontologies` (UKO 15.7.0, TKO 8.5.1, MLO 1.7.2, REO 1.7.0,
  FKO 1.2.3). Tests 1 and 2 stay frozen on UKO 15.5.
- Method: `docs/gkg-full-methodology.md` is the complete method (inputs, entities, every relation rule, checks,
  how to rebuild).
- Code: `07-gkg-builder/relations/build.py` (numbered steps; `python -m relations.build STEP ...` reruns one step),
  `relations/validate.py` (checks), `relations/make_dictionary.py` (data dictionary). The relation catalogue in
  `relations/catalogue/*.tsv` comes from the ontology files: rerun `python -m relations.build --catalogue` in the
  cloud workspace whenever RELATIONS or the ontology changes, then copy the TSV files to the Mac mini.

## Rules that bind any use of the graph

1. A crash-prediction model reads edges only through `gkg.edge_for_crash_prediction`. That view drops every
   crash-derived relation and every edge that touches a crash record, a risk profile or a High Injury Network
   entity (Evangelos's decision, Nov 20). Crash records may serve as labels only.
2. Every input is public data (Tier P). The graph holds no trip data, and client trip tables stay out of this work.
3. Query outputs and coordinates stay off the repository. Aggregates go to the Mac mini share and to Drive.
4. The GKG chat used main-queue jobs 200-221 and status jobs s200-s221. Ask Evangelos which job numbers each of Chats 3a and 3b may use, so the two chats do not collide on the Mac mini.

## How to read the graph

- Join `gkg.edge` to `gkg.entity` on `eid` to get URNs and classes; `gkg.edge_named` does this for you, but it is
  slow on whole relations. Filter on `rid` (see `gkg.relation_type`) before joining.
- Symmetric relations are stored once with subject key < object key. Read both directions.
- For an inverse pair only one property is stored (for example uko:within, not uko:contains).
- `value_m` holds meters for distance-bearing relations (near, nearTransitStop, hasParking and others).
- A walking distance in `gkg.distance_measurement` is null when the walk exceeds 2 km.
- Test class membership with `gkg.class_closure` (built from UKO 15.7 and REO 1.7.0). `gkg.entity_type` is empty
  under UKO 15.7; if a later build adds rows, use them too.

## Decisions already taken on the build (November 22)

1. uko:crosses links a crosswalk to the road segment nearest its midpoint within 7 m and 30 degrees of perpendicular.
2. Government buildings stay landmark targets for distance measurements.
3. UKO 15.7 is in force; the build was re-checked against it.

## Known limits

- uko:derivedFrom is empty: only one Overture release has been loaded.
- Overture place classes are noisy (some ShoppingMall places are shops).
- Transit relations cover the stored reference service day only.
- uko:continuesAs follows the digitized direction of segments only.
