# Design note: place statistics (O4), the fingerprint (O5) and police-reported non-collision incidents (draft, November 22, 2026)

Status: DRAFT for Evangelos's approval. After approval, the GKG chat implements these changes in the next coordinated release (UKO 15.8, REO 1.8.0, MLO 1.8.0) and loads San Francisco data. This note proposes terms; the GKG chat may adjust names to fit its generators, but it should keep the structure and the acceptance tests.

Scope: San Francisco only, as Evangelos decided on November 22. Nothing here needs another city's data.

## 1. One pattern for every measured value

UKO 15.7 already holds one measured value with its own context: uko:TrafficVolumeObservation records a value, a statistic, a period, a method and a source. O4, O5 and the incident counts need the same structure. I propose that all of them follow one pattern, and that the pattern align with the W3C and OGC Sensor, Observation, Sample, and Actuator ontology (SOSA), the lightweight core of the Semantic Sensor Network ontology (W3C Recommendation, October 19, 2017, https://www.w3.org/TR/vocab-ssn/). A 2023 edition of that standard is still a W3C Working Draft (September 2026), so the 2017 Recommendation is the version to cite.

**Why an observation and not a plain number.** A census figure has a period (the ACS 2020-2024 five-year estimate), a margin of error, a source table and a method. Several vintages of the same figure will coexist, and hypothesis H10 compares a place before and after an intervention. A plain datatype property such as "population = 812,000" can hold none of that context.

**The proposed alignment.**
- A new abstract class uko:MeasuredValue is declared a subclass of sosa:Observation. UKO imports only the SOSA module, not the full SSN ontology. uko:TrafficVolumeObservation becomes a subclass of uko:MeasuredValue, so that existing volume data keeps its meaning.
- Each measured value states what it describes (sosa:hasFeatureOfInterest: a tract, a city, a road segment), which variable it measures (sosa:observedProperty: an individual from a controlled list), the number (sosa:hasSimpleResult, or a UKO value property), the period it covers (sosa:phenomenonTime), and the method (sosa:usedProcedure).
- UKO adds the properties SOSA lacks: uko:valueUnit, uko:marginOfError, uko:marginConfidenceLevel (0.90 for ACS; the Census Bureau publishes ACS margins at the 90 percent level), uko:valueSource (a uko:DataSource), uko:sourceTable (for example "B19013"), and uko:valueCrashDerived (true when the value depends on crash records, so that crash-prediction exports can drop it).

**Decision 1 for Evangelos:** align with SOSA by subclassing and importing the SOSA module, or keep a stand-alone UKO pattern with the same fields. I recommend the alignment: reviewers in academic venues will recognize the pattern, and the import adds few terms.

## 2. O4: place statistics

**Classes and properties.**
- uko:PlaceStatistic, a subclass of uko:MeasuredValue, for any figure that describes an area as a whole.
- uko:hasPlaceStatistic, from uko:SpatialEntity to uko:PlaceStatistic.
- uko:PlaceVariable, a class whose individuals name the variables: Population, LandAreaKm2, Households, MedianHouseholdIncome, HouseholdsIncomeBelow35k, HouseholdsIncome100kPlus, ZeroVehicleHouseholdShare, JobCount, CommuteModeShare, JobsReachable. A new variable then needs a new individual, not a new property.
- For variables that depend on a mode or a time limit, the statistic carries uko:travelMode (car, transit, walk, bicycle) and uko:travelTimeThresholdMinutes. JobsReachable by car within 30 minutes and by transit within 45 minutes then share one definition. uko:jobAccessibility stays in UKO for existing data; its definition gains a sentence that points to the general pattern.
- uko:GridCell, a subclass of uko:ConceptualArea, with uko:gridSystem ("H3") and uko:gridIndex, because factor 4 measures job density on H3 cells at resolution 8. UKO 15.7 has no grid-cell class.
- uko:zeroVehicleHouseholdDensity stays; the loader writes the same figure as a ZeroVehicleHouseholdShare statistic as well.

**San Francisco data.** The table gkg.census_tract already holds population (all 261 tracts), median household income (94.3 percent of tracts), households and the two income bands, from ACS 2020-2024. The loader turns those columns into statistics without a new download. Land area comes from the tract polygons. Three public downloads are needed: LODES workplace area characteristics for San Francisco blocks (job counts), ACS table B08301 (means of transportation to work, for commute mode shares), and the ACS margins of error for the tables already loaded.

**Acceptance tests (competency questions from the audit catalog).** After the build, a query must answer each of these for San Francisco: F7 (population and land area per tract and for the city), F8 (median income, zero-vehicle share, income segregation index), F4 (job centers from job counts on H3 cells), F5 (residents within 400 m of frequent service), F3 (jobs reachable on foot within 30 minutes; car and transit wait for a router), and P3 and H7 (commute mode share per tract).

## 3. O5: the fingerprint

The fingerprint describes a place, so its values belong in UKO. The results of transfer experiments describe models, so they belong in MLO.

**UKO classes.**
- uko:Fingerprint: one fingerprint of one area (a city or a tract) at one version. Properties: uko:fingerprintOf (the area), uko:fingerprintVersion, uko:computedOn (a date), uko:usesReferenceSet.
- uko:FingerprintFactor: individuals for factors 1 to 17 of the factor specification and for the six graded questions. Each individual states its layer (structural, operating, governance and market, behavior, graded) and its smallest area, so that a query can select the factors a test allows. Factor 12 carries uko:valueCrashDerived true, which matches the Test 3 rule that excludes it from every distance.
- uko:FactorValue, a subclass of uko:MeasuredValue: one factor's value for one fingerprint, with uko:formulaVersion, the source versions (through uko:valueSource), and uko:scalingResidual (true when the value is stored as its residual from the population scaling fit of factor 7).
- uko:ReferenceSet: the set of areas whose statistics standardize the factors, with its version.
- uko:FingerprintDistance: the distance between two fingerprints, with uko:distanceFrom, uko:distanceTo, uko:distanceValue, uko:distanceMetric (for example "Euclidean on point-level marks, equal question weights"), uko:factorSetUsed (the factors included) and uko:weightsVersion.

**Graded factors.** A graded question's score enters as a uko:FactorValue with uko:grader (a text name; UKO has no person class, and the GKG should not hold one) and uko:scoreKind ("suggested" or "highest possible"). Evangelos decided that the pack evidence itself stays in the scoring spreadsheets for now, so the factor value links to its spreadsheet through uko:valueSource and nothing more.

**MLO classes.**
- mlo:TransferEvaluation: one evaluation of a model trained on a source area and applied to a target area. Properties: mlo:sourceArea, mlo:targetArea, mlo:evaluatesModel (an mlo:AnalyticsModel), mlo:featureSet (for example "B2"), mlo:outcomeDefinition (for example "KSI crashes, KABCO K and A, five complete years"), mlo:errorMeasure (for example "Poisson deviance, intercept-adjusted"), mlo:errorValue, mlo:evaluatedOn and mlo:evaluationLogRef (the line in the append-only log).

**San Francisco data.** With one city, a fingerprint can be computed and stored, but no distance or transfer evaluation exists until a second area does. Two options give the classes real San Francisco instances now: tract-level fingerprints (factors 1, 3, 5 and 8 are defined at tract level), and neighborhood-level fingerprints for the 158 San Francisco neighborhoods already in the graph. Both give pairwise distances inside the city, which hypothesis H9 needs.

**Acceptance tests.** F1 (the street-pattern signature of each tract, stored with its formula version), H9 (tract fingerprints and the distances between them), and H10 (two versions of one fingerprint, distinguished by version and date). H0 needs a second city and waits for a Waymo-approved project.

**Decision 2 for Evangelos:** compute tract-level fingerprints for San Francisco now, so that O5 has instances and H9 can be examined, or define the classes and wait for a second city.

## 4. Police-reported incidents other than collisions (REO)

**Classes.**
- reo:ReportedTrafficIncident, a new parent class. reo:HistoricalIncidentRecord (collisions) becomes its subclass, so that existing crash data keeps every property and relation.
- reo:NonCollisionIncident, a second subclass of reo:ReportedTrafficIncident.
- reo:NonCollisionCategory, with individuals in three groups, as Evangelos approved on November 22:
  - curb and right-of-way violations: double parking, blocking a bike lane, blocking a bus zone, stopping in a red zone, misuse of a loading zone;
  - dangerous driving: speeding, running a red light, failing to yield to a pedestrian, driving under the influence, reckless driving, sideshows and street takeovers;
  - incidents involving automated vehicles: obstructing an emergency vehicle, obstructing traffic, vandalism of the vehicle, a notice of noncompliance to the operator.
- reo:recordOrigin, with the values "citation or arrest", "dispatched call for service" and "incident report", because each origin measures something different: a citation measures enforcement, a call measures a complaint.
- reo:issuingAgency (a uko:Organization, for example the San Francisco Police Department or the San Francisco Municipal Transportation Agency), reo:involvesAutomatedVehicle (boolean) and reo:avOperator (a uko:Organization).
- reo:relatedCollision, from a non-collision incident to the reo:HistoricalIncidentRecord it followed. Any incident with this relation, and any record of a hit-and-run or of an arrest after a collision, carries uko:valueCrashDerived true.
- The domains of reo:onRoadSegment and reo:atIntersectionNode widen to reo:ReportedTrafficIncident, so that incidents attach to the network as crashes do. reo:locationPrecision records how far the source rounds locations (for example "nearest intersection" or "block midpoint").

**What the graph stores.** Incident records describe individuals' encounters with the police. I propose that the graph store only counts: reo:IncidentCount, a subclass of uko:MeasuredValue, holding the number of incidents of one category and one origin on one segment, intersection or block for one month. The individual records stay in the loader's working tables on the Mac mini and are never exported.

**The rule for prediction.** Every non-collision count is excluded from crash-prediction inputs by the same view rule that drops crash-derived edges. Curb-violation counts may serve as inputs to the curb study (research question 3), which predicts no crashes. Dangerous-driving counts serve only as a secondary outcome.

**San Francisco sources (to verify before loading).** DataSF publishes police incident reports from 2018 on, law enforcement dispatched calls for service, and SFMTA parking citations; the California Department of Justice publishes stop data under the Racial and Identity Profiling Act. I have not yet confirmed each dataset's identifier, fields, location rounding and licence; the loader's first job is that check, and I will report it before any download.

**Acceptance tests.** T3-9 (incidents of each category per segment per month), and research question 3's first step (curb-violation counts within 100 m of each place class that generates pickups).

**Decision 3 for Evangelos:** store only monthly counts by segment, intersection or block (my recommendation), or store individual incident records.

## 5. Order of work after approval

1. The GKG chat implements the approved terms in UKO 15.8, REO 1.8.0 and MLO 1.8.0, checks the set with HermiT, and tells this chat the release commit.
2. The GKG chat loads San Francisco data: statistics from gkg.census_tract, then LODES and ACS B08301; tract fingerprints if Evangelos chooses option one in Decision 2; incident counts after the source check in section 4.
3. This chat writes a query for each acceptance test, runs it on the Mac mini (jobs 300-349, read-only), checks a sample of answers by hand, and updates the audit catalog.

*Synapse Partners, LLC — Confidential and Proprietary*
