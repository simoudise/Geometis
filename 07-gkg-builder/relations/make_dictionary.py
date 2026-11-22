"""Write the data dictionary for the GKG full relations.

python3 -m relations.make_dictionary OUT.md [VALIDATION.json]

Without VALIDATION.json the dictionary carries no counts (the repository copy). With it, each relation gets its
edge counts per geofence (the Drive copy).
"""
import json, sys
from pathlib import Path

from relations.build import RELATIONS, CATALOGUE

FAMILY = [
    ("Road network topology", ["uko:adjacentSegment", "uko:connectsTo", "uko:touches", "uko:intersectsRoad", "uko:crosses",
                               "uko:crossesOver", "uko:continuesAs", "uko:branchesFrom", "uko:mergesInto", "uko:feedsInto",
                               "uko:parallelTo", "uko:hasAccessPoint"]),
    ("Containment and administrative areas", ["uko:within", "uko:withinCensusTract", "uko:hasJurisdiction", "uko:inNeighborhood",
                                              "uko:inSupervisorDistrict", "uko:overlaps", "uko:adjacentTo", "uko:adjacentNeighborhood"]),
    ("Proximity and distance", ["uko:near", "uko:hasDistanceMeasurement", "uko:hasVulnerablePopulationNearby",
                                "uko:nearVulnerablePopulation"]),
    ("Buildings, places and access", ["uko:sharesWallWith", "uko:sharesBuildingWith", "uko:insideMall", "uko:accessibleBy",
                                      "uko:frontageOn", "uko:providesAccessTo", "uko:servesAsMainAccess", "uko:accessibleByBikeLane",
                                      "uko:accessibleBySidewalk", "uko:hasParking", "uko:partOfChain", "uko:operatedByOrg"]),
    ("Sidewalks", ["uko:alongsideOf", "uko:onNorthSideOf", "uko:onSouthSideOf", "uko:onEastSideOf", "uko:onWestSideOf"]),
    ("Transit and shared mobility", ["uko:servesStop", "uko:parentStation", "uko:hasTrip", "uko:hasStopTime", "uko:atStop",
                                     "uko:hasServiceCalendar", "uko:hasServiceException", "uko:gtfsOperatedBy", "uko:hasTransferTo",
                                     "uko:fareProductOfAgency", "uko:hasServiceArea", "uko:anchorStation", "uko:connectsToTransit",
                                     "uko:nearTransitStop", "uko:nearestTransitStop", "uko:hasTransitAccess", "uko:walkshedOrigin",
                                     "uko:operatedBySystem"]),
    ("Common spaces", ["uko:adjacentToCommonSpace", "uko:bordersCommonSpace", "uko:bordersNaturalArea",
                       "uko:crossesThroughCommonSpace", "uko:hasTrailConnection", "uko:pathThroughCommonSpace",
                       "uko:providesRecreationFor"]),
    ("Freight", ["uko:hasTruckRoutingConstraint", "uko:constrainsSegment", "uko:hasTruckParkingFacility"]),
    ("Safety (crash-derived: never an input to crash prediction)", ["uko:inHighInjuryNetwork", "uko:hinSegmentOf",
        "uko:hasIntersectionRiskProfile", "reo:atIntersectionNode", "reo:hasCollisionCausationFactor", "reo:incidentCollisionType",
        "reo:incidentLighting", "reo:incidentRoadSurface", "reo:incidentWeatherCondition"]),
    ("Lineage and sources", ["uko:derivedFrom", "uko:hasDataSource"]),
]
listed = sum((f[1] for f in FAMILY), [])
assert sorted(listed) == sorted(c for c, *_ in RELATIONS), set(listed) ^ {c for c, *_ in RELATIONS}


def main():
    out, val = Path(sys.argv[1]), (json.load(open(sys.argv[2])) if len(sys.argv) > 2 else None)
    rel = {l.split("\t")[1]: l.rstrip("\n").split("\t") for l in open(CATALOGUE / "relation_type.tsv")}
    counts, rejected, methods = {}, {}, {}
    if val:
        for r in val["relations"]:
            counts.setdefault(r["curie"], {})[r["geofence"]] = r["edges"]
        for r in val["rejected"]:
            rejected[r["curie"]] = rejected.get(r["curie"], 0) + r["n"]
        for p in val["provenance"]:
            methods.setdefault(p["curie"], []).append(f'{p["method"]} (source: {p["source"]})')
    L = ["# GKG full build: data dictionary for the new relations", "",
         "Release: GKG full, built November 20, 2026 and revised November 22 on the Mac mini (database `geometis`, schema `gkg`), checked against UKO 15.7.0 and REO 1.6.3. "
     "The method is in `docs/gkg-full-methodology.md`. "
         "Code: `07-gkg-builder/relations/build.py`; checks: `relations/validate.py`.", "",
         "## Tables", "",
         "| Table | One row is | Key columns |", "|---|---|---|",
         "| `gkg.entity` | one entity in one geofence | `eid` (integer key), `urn`, `geofence_id`, `uko_class`, `src` (source table or `aux:<kind>`) |",
         "| `gkg.entity_type` | an extra asserted type of an entity | `eid`, `uko_class`, `rule` |",
         "| `gkg.aux_entity` | an entity that the earlier stages did not store (districts, blocks, parks, organizations, trips and others) | `geofence_id`, `urn`, `uko_class`, `kind`, `name`, `props`, `geom` |",
         "| `gkg.relation_type` | one ontology property | `rid`, `curie`, `domain_classes`, `range_classes`, `crash_derived`, `is_symmetric`, `inverse_curie`, `method` |",
         "| `gkg.provenance` | one way of producing edges of one relation | `pid`, `rid`, `source`, `method`, `code_version`, `ontology_version`, `crash_derived` |",
         "| `gkg.edge` | one edge | `rid`, `subj`, `obj` (entity keys), `pid`, `value_m` (meters, where the relation has a distance) |",
         "| `gkg.distance_measurement` | one uko:DistanceMeasurement | `subj`, `target`, `straight_m`, `walk_m`, `measured_to` (`point` or `boundary`), `inside_target`, `pid` |",
         "| `gkg.edge_rejected` | edges removed because the subject or object failed the property's domain or range | `rid`, `reason`, `n`, example classes |",
         "| `gkg.class_closure` | a class and one of its named ancestors (UKO 15.7 + REO 1.6.3) | `uko_class`, `ancestor` |", "",
         "## Views", "",
         "- `gkg.edge_named`: every edge with relation name, URNs, classes, geofence and provenance.",
         "- `gkg.rel_very_near`: uko:veryNear, which is uko:near with `value_m` <= 50. The build stores no separate veryNear rows.",
         "- `gkg.edge_for_crash_prediction`: the only edge source a crash-prediction export may use. It drops every relation marked "
         "`crash_derived` and every edge that touches a crash record, a risk profile or a High Injury Network entity.", "",
         "## Conventions", "",
         "- A symmetric relation is stored once, with subject key < object key. Read it in both directions.",
         "- For a pair of inverse properties the build stores only the property listed below; the inverse (`inverse_curie`) follows from it.",
         "- Metric work uses California Albers (EPSG:3310). Walking distances use the stored walking network: road segments except motorways, "
         "pedestrian edges and access points.",
         "- An edge never joins entities of two geofences. The Contra Costa and San Francisco extents overlap, so the same Overture feature "
         "can appear in both geofences with two entity keys.",
         "- New URNs use the `gkgfull` source tag (for example `urn:urban-kg:CityBlock:gkgfull:<hash>`). Public-data URNs keep the "
         "publisher's identifier where one exists (DataSF, MTC, TIGER, OpenStreetMap, GBFS).",
         "- The enforce step removes edges whose subject or object is not an instance of the property's `rdfs:domain` or `rdfs:range` "
         "under the UKO 15.7 class hierarchy plus `gkg.entity_type`. Removed counts are in `gkg.edge_rejected`.", "",
         "## Asserted extra types", "",
     "None under UKO 15.7. The November 20 build asserted types per entity that UKO 15.6 lacked (schools and hospitals as "
     "vulnerable-population facilities, pedestrian network edges as pedestrian infrastructure, truck restrictions as "
     "operational constraints); UKO 15.7 states the first as axioms and widens the domains that needed the others.", ""]
    for fam, cs in FAMILY:
        L += [f"## {fam}", ""]
        for c in cs:
            i, curie, dom, rng, cd, sym, inv, note = rel[c]
            L.append(f"### {c}")
            L.append("")
            L.append(f"- Domain: {dom.replace(',', ' or ') or '(none)'}; range: {rng.replace(',', ' or ') or '(none)'}."
                     + (" Symmetric." if sym == "True" else "") + (f" Inverse: {inv}." if inv else "")
                     + (" **Crash-derived.**" if cd == "True" else ""))
            L.append(f"- Rule: {note}.")
            if c in methods:
                for m in sorted(set(methods[c])):
                    L.append(f"- Provenance row: {m}.")
            if val:
                if c == "uko:hasDistanceMeasurement":
                    for d in val["distance_measurements"]:
                        L.append(f"- {d['geofence']}, to {d['target_class']} ({d['measured_to']}): {d['rows']:,} rows, "
                                 f"{d['with_walk']:,} with a walking distance; median straight {d['median_straight_m']} m, median walk {d['median_walk_m']} m.")
                else:
                    cs_ = counts.get(c, {})
                    L.append("- Edges: " + ("; ".join(f"{g} {n:,}" for g, n in sorted(cs_.items())) or "none") +
                             (f"; removed by domain/range enforcement: {rejected[c]:,}" if c in rejected else "") + ".")
            L.append("")
    L += ["## Not built, and why", "",
          "- uko:veryNear: stored as uko:near with `value_m` <= 50 (decision 3); read `gkg.rel_very_near`.",
          "- uko:onSameBlock: computed at query time from uko:within building -> uko:CityBlock (decision 4).",
          "- uko:hasStreetAddress and address-based uko:servesAsMainAccess: the place files the builder loaded carry no address fields. "
          "servesAsMainAccess uses the nearest street instead.",
          "- uko:hasAccessToCommonSpace: no distance rule was approved.",
          "- uko:servesNeighborhood: needs a rule (which stops or routes serve which neighborhood).",
          "- uko:servesVehicleType: the static Bay Wheels GBFS files list vehicle types per system, not per station.",
          "- North, south, east and west relations between features (decision B2); acrossFrom, nearbyLandmark, segmentBetween, "
          "from/toCrossStreet and the commercial competition relations (skipped by decision).",
          "- uko:derivedFrom: the relation is wired to `gkg.urn_lineage`, which is empty because the build has used one Overture release.", ""]
    out.write_text("\n".join(L))
    print(out, len(L), "lines")


if __name__ == "__main__":
    main()
