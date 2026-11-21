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
- Ontologies: UKO 15.6.0 and REO 1.6.2 (coordinated release 2026-11-20 in `01-ontologies`). Tests 1 and 2 stay
  frozen on UKO 15.5.
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
- An entity can have extra asserted types in `gkg.entity_type`. Use them, with `gkg.class_closure`, when you test
  class membership.

## Open items from the build (Evangelos to decide)

1. The crosswalk rule for uko:crosses (nearest road segment within 12 m of the crosswalk's midpoint).
2. Whether GovernmentBuilding stays a landmark class for distance measurements.
3. Whether the UKO 15.7 candidates (wider domains for sharesBuildingWith, partOfChain, operatedByOrg, insideMall,
   hasDataSource; four missing subclass axioms) go into an ontology update now.

## Known limits

- uko:derivedFrom is empty: only one Overture release has been loaded.
- Overture place classes are noisy (some ShoppingMall places are shops).
- Transit relations cover the stored reference service day only.
- uko:continuesAs follows the digitized direction of segments only.
