# GeoMetis test plan: two bets, two tests (revision 2, November 14, 2026)

Status: revision 2, approved by Evangelos on November 14, 2026 (decisions below). Arm descriptions and tools frozen (Freeze record); templates not yet frozen. Revision 1 went to Fable for a design review (Chat 5, November 14). Fable found 18 defects, three of them fatal. This revision accepts all 18; the change log at the end maps each defect to its fix. The plan is frozen once Evangelos approves the open decisions listed at the end. Any later change goes in the change log, with its date and reason, before the run it affects.

## Why this plan exists

We have produced 19 versions of the architecture without learning whether the System works. This plan replaces argument with two tests. Each test has pass, fail and inconclusive rules written before it runs. A failed test stops the line of work it tests.

- **Bet A.** The symbolic layer makes a language model answer geospatial questions better than the same model with SQL alone. Revision 2 splits Bet A into three parts, because revision 1 changed several things at once (Fable defects 1 and 2):
  - **A-tool:** a network tool helps.
  - **A-knowledge:** a written description of the data (definitions, source limits, how to use the tables) helps.
  - **A-ontology:** stating that description in the ontology's classes and relations helps beyond a plain data dictionary with the same facts.
- **Bet B.** SPECTRA embeddings learned from the knowledge graph predict outcomes in a place the model did not train on better than features built by hand.

Neither test uses trip data. Every input is Tier P; crash records (Tier R) serve only as labels. The trained weights carry no Tier 3 restriction.

## Data both tests use

| Geofence | Road segments | Intersections | Places | Pedestrian edges | Transit stops | Census tracts |
|---|---|---|---|---|---|---|
| us-ca-contra-costa-5 (Antioch, Concord, Pittsburg, Pleasant Hill, Walnut Creek) | 89,695 | 71,947 | 28,604 | 24,310 | 1,639 | 116 |
| us-ca-san-francisco | 61,175 | 49,521 | 78,789 | 72,482 | 3,849 | 261 |

Injury crashes: Contra Costa 9,639 in 2021 to 2025; San Francisco 16,375. 2026 is partial and is not used. The database has PostGIS 3.6.4 and no pgRouting.

---

## Test 1: what does each part of the symbolic layer add? (Bet A)

### Arms

All arms use claude-sonnet-5-5 at the API's default temperature (1.0). Each answers every question three times. Every arm receives the same answer rules (state the method, name the entities and numbers used, state any limit of the data that affects the answer, say plainly what the data cannot answer) and must end with one machine-readable line, `ANSWER: …`, in a format each question specifies.

| Arm | Description of the data | Tools |
|---|---|---|
| A0 LLM only | One paragraph naming the two geofences | None |
| A1 SQL | Plain schema listing (table and column names and types, from information_schema) | Read-only SQL |
| A2 SQL + network | Plain schema listing | Read-only SQL, network tool |
| A3 Dictionary + network | Data dictionary: the catalog's facts (column meanings, definitions such as "street" and "arterial", the nine source limits, how tables join) written as plain prose without ontology class names or relations | Read-only SQL, network tool |
| A4 GeoMetis v0 | Knowledge catalog (ontology classes mapped to tables, relations, source limits) | Read-only SQL, network tool |

Comparisons:
- **A-tool:** A2 minus A1.
- **A-knowledge:** A4 minus A2. This comparison is the primary test of Bet A.
- **A-ontology:** A4 minus A3.
- A0 answers 30 questions only and is reported descriptively, with no pass rule (Fable defect 8).

The plan uses a chain of arms rather than Fable's full two-by-two design: it drops "catalog with SQL, no network tool". The chain still isolates each effect; it cannot measure whether the catalog helps more when the tool is absent. This omission saves one arm of API calls.

All arms keep the step limit of 14 with a forced final answer, tool output capped at 12,000 characters, and refusal of trip tables. The report gives, for each arm, the share of runs that hit the step limit (Fable defect 9).

### Network tool

The current `shortest_path` tool routes only over road segments and can avoid only whole road classes. Revision 2 replaces it, before anything is frozen, with `network_path`, which adds (a) the walking network the walksheds use (road segments other than motorways, pedestrian edges and access points) and (b) removal of named segments, so that network and what-if questions do not depend on SQL tricks. One-way rules are not applied, and every question says so.

### Reference answers

- Reference paths come from an independent implementation: separately written code that exports the edge tables and runs Dijkstra with SciPy's sparse-graph routines. The reference code never calls the arms' tool (Fable defect 3).
- Each question states the metric (length in meters), the network (road or pedestrian), that one-way rules are ignored, and how straight-line distance is measured (California Albers, EPSG:3310).
- Tolerances: distances and lengths within 5 percent; counts that depend on a distance buffer within 5 percent or 1, whichever is larger; other counts exact; lists correct when F1 overlap reaches 0.8.
- Half of the constrained questions state the needed definition inside the question (for example, "count residential, tertiary, secondary, primary and trunk roads as streets"). The other half rely on the arm's description of the data. The report shows the two halves separately (Fable defect 2).

### Questions

- **Categories:** lookup, network, what-if and constrained, as in revision 1. Lookups remain a guardrail, not evidence for the System; the HERE and Zephr prototype shows that a language model on a map answers lookups correctly and that buyers find this only moderately interesting.
- **Size:** at least 30 non-lookup templates with at most 6 filled-in questions each, plus 10 lookup templates. The pilot estimates the variance between templates; the final template count is then set so that the standard error of the A4-minus-A2 difference is at most 4 points (Fable defect 6).
- **Authorship:** at least half of the non-lookup templates come from an author who has not seen the catalog or the data dictionary. The report shows results for the two author groups separately (Fable defect 4). (Open decision 1.)
- **Freeze order:** first the catalog, the data dictionary, every system prompt, `loop.py` and the network tool are frozen and their SHA-256 hashes recorded here. Then the templates are written. Then the templates, the reference code, the drop rule and the answer parser are frozen and hashed (Fable defect 4).
- **Drop rule:** frozen code drops a question before the run when its reference depends on data the catalog marks unreliable. In the first version of this rule, Contra Costa questions whose answer depends on whether a sidewalk or crosswalk is mapped are dropped, because sidewalk mapping there covers 20 to 35 percent of streets. Walking-route questions stay in both geofences: the walking network (the same one the walksheds use) is every road segment except motorways plus mapped pedestrian ways, so sparse sidewalk data does not cut it apart. The plan publishes the category-by-geofence count table before the run (Fable defect 9).
- **Sampling:** the filled-in questions are drawn with a recorded seed. Pilot questions are excluded from the full set.

### Scoring

- **Primary score (automatic):** code parses the `ANSWER:` line and compares it with the reference within the tolerances above. A run without a parsable `ANSWER:` line scores zero.
- **Secondary score (blind):** for each question, a checklist of the source limits that apply is written and frozen with the templates. Fable checks each answer against that checklist and judges whether the explanation is correct. Arm names, tool calls, step counts and URNs are removed before grading (Fable defect 5). Evangelos checks a random 10 percent.
- Each arm's score on a question is the mean of its three runs.

### Statistics

The analysis uses paired differences per question. Confidence intervals come from a wild cluster bootstrap with Rademacher weights, clustered by template and stratified by category, following Cameron, Gelbach and Miller (2008, Review of Economics and Statistics 90(3)), who show that resampling whole clusters over-rejects when clusters number between about 5 and 30 (Fable defect 6).

### Pass, fail and inconclusive rules

The same rules apply to each comparison (A-tool, A-knowledge, A-ontology), computed on network, what-if and constrained questions combined (Fable defect 7):

- **Pass:** the estimated difference is at least 15 points and the lower bound of its 95 percent interval exceeds 5 points.
- **Fail:** the estimate is at most 5 points (any negative value included) and the upper bound is below 15 points.
- **Inconclusive:** every other outcome.
- **Lookup guardrail:** holds when the lower bound of the lookup difference (A4 minus A2) exceeds minus 5 points.

What each outcome means:
- A-knowledge fails: describing the data adds nothing that a schema listing and SQL do not supply. We stop building the symbolic layer in its current form.
- A-knowledge passes and A-ontology fails: the benefit comes from documentation, not from the ontology. The System's claim then rests on curated data knowledge, and the ontology needs a reason other than question answering.
- A-ontology passes: the ontology itself helps a language model reason over the graph.

### Cost and order

- A pilot of 50 questions across A1 to A4 (and 10 for A0) measures cost per question and the variance between templates, and finds setup errors. Pilot results do not count.
- I report the measured cost before spending past the current $20 of API credit. Five arms raise the call count above revision 1's estimate; the pilot gives the real figure.
- Calls run 8 to 10 at a time from the Mac mini.

---

## Test 2: do SPECTRA embeddings predict in a new place? (Bet B)

Test 2 is a reduced version of the transfer evaluation in the v19 patch (M18). Departures are listed under "Gaps against the v19 patch".

### What gets built

SPECTRA v0 as the patch specifies:
- Node types: road segments, intersections, places, pedestrian edges, transit stops and census tracts, with their graph relations.
- Inputs: Tier P only (M7d). The location block never enters the encoder; the shape block does (M3). Fixed, unit-based transforms; no city indicator (M8, M9).
- Positives: 50 percent two-view pairs and 50 percent form-versus-function pairs (M1j). Negatives: distance-matched negatives of the same node type plus debiased in-batch negatives (M2). InfoNCE with temperature starting at 0.15 (M2b).
- The prediction head reads only the transferable part of the embedding (M4); the location block never reaches the head (Fable defect 18d).

Two variants:
- **S-pub:** the default losses only.
- **S-full (crash only):** S-pub plus L_aux (M17), predicting 2015 to 2019 injury-crash counts in source geofences. No trip-end head and no flow pairs.

### Task, target and measures

- Task T1 from M18: injury-crash frequency, counted over 2021 to 2025, with **separate heads for street segments and for intersections** (Fable defect 13). Segment heads use length as the exposure term; intersection heads have no exposure term.
- **Primary measure (named now):** Poisson deviance on the held-out fold after fitting one intercept per held-out geofence, so that the measure compares ranking and relative risk rather than the overall crash level of each place. Raw deviance is reported beside it (Fable defect 13).
- **Secondary measures:** the share of 2021 to 2025 injury crashes on the top 5 percent of network length as ranked by the prediction; and, on arterials only, the result when public HPMS traffic volumes are added to B2 and to SPECTRA + B2. (M7d holds HPMS out of encoder inputs; here HPMS enters only the head in a secondary analysis that tests whether SPECTRA's advantage is a stand-in for traffic volume.)

### Feature sets compared

Every feature set feeds the same head class (gradient-boosted trees, Poisson objective) trained on source entities only.

- **B0:** source mean by road class and area type.
- **B1:** every raw Tier P input the encoder reads for the entity itself, including reach and betweenness (Fable defect 12).
- **B2:** B1 plus hand-built neighborhood aggregates over 1 to 3 hops and rings of 250 m, 500 m and 1 km. The B2 feature list is frozen by hash before SPECTRA trains (Fable defect 12).
- **B3:** AlphaEarth satellite embeddings if Google Earth Engine access works; otherwise dropped and recorded.
- **B4:** a supervised heterogeneous graph network (R-GCN) trained end to end with a Poisson loss on source crash counts. An unsupervised GraphSAGE is reported as well (Fable defect 12).
- **S-pub, S-full**, each alone and combined with B2.
- **References:** an in-geofence model trained on the held-out geofence's own labels under spatial-block cross-validation; and S-pub + B2 heads given 1, 5 and 10 percent of target labels (Fable defect 18c).
- **Equal supervision:** for the S-full comparison, B2 and B4 also train with the 2015 to 2019 source counts as additional targets (Fable defect 11).

### Splits

Three folds (M18's cluster folds): hold out Walnut Creek + Pleasant Hill + Concord; hold out Antioch + Pittsburg; hold out San Francisco. The held-out area is the union of the held-out city cores (`gkg.geofence.core`).

- Source entities within 1 km of the held-out boundary are removed, and every graph edge that crosses the buffer is cut (Fable defect 16).
- In each fold, the encoder trains on source entities only, and every fitted quantity (feature transforms, imputed values such as class-median speed limits and feature means, negative mining, heads) is computed on source entities only (Fable defect 16).
- A spatial block is a 1 km by 1 km square in EPSG:3310.

### Tuning (Fable defect 10)

Each fold chooses its configuration by cross-validation over spatial blocks inside its own source cities. No method sees a held-out label until its configuration is fixed. Each held-out fold's labels are read once per method. B2, B4, S-pub and S-full each get the same number of logged tuning trials (8 per fold). San Francisco runs after the two Contra Costa folds, with the procedure unchanged.

### Leakage controls (Fable defect 17)

- The export writes the M7d lineage manifest and fails if any encoder or baseline input traces to Tier R, T, S or D.
- L_aux counts are built from `gkg.tims_crash` with `accident_year` at most 2019. `segment_crash_stats` is never read.
- No feature set uses road names, place names or URNs.
- A position-leakage measurement (M13) is reported for S-pub and S-full.
- Every evaluation on a held-out fold is written to an append-only log.

### Seeds and minimum effect (Fable defect 14)

S-pub, S-full, B4 and GraphSAGE each train with 5 seeds per fold. A gain counts only if it is at least 10 percent of the gap between B2 and the in-geofence reference and also larger than two standard deviations across seeds.

### Pass, fail and inconclusive rules

The **encoder claim rests on S-pub** (named now, before any run; Fable defect 11). S-pub passes only if all hold:

1. It beats B2 and B4 on the pooled primary measure by at least the minimum effect.
2. The paired difference against B2 favors S-pub in all three folds. (With no true difference this happens about one time in eight by chance, which is why conditions 1 and 3 also apply.)
3. A bootstrap over spatial blocks gives a 95 percent interval for the pooled difference that excludes zero. This interval measures noise within the three places, not variation between places; the report says so.
4. The advantage holds in the arterial, collector and intersection strata, pooled across folds. Local streets are reported but not required, because nearly all local segments have zero crashes (Fable defect 15).
5. It closes at least half of the gap between B1 and the in-geofence reference.
6. The San Francisco fold is not negative.

- **Fail:** S-pub does not beat B2 by the minimum effect, and the 95 percent interval of the pooled difference excludes the minimum effect. The learned encoder then adds nothing to hand-built features at this scale, and we stop investing in SPECTRA training until a different design or more data gives a reason to try again.
- **Inconclusive:** every other outcome.
- **S-full against S-pub:** S-full "matches" S-pub when the 95 percent interval of their difference lies inside plus or minus the minimum effect. Then the auxiliary crash supervision adds nothing.

### Known weaknesses

- The graph has no traffic volumes; the HPMS secondary analysis tests how much this matters on arterials.
- Three folds from one region support statements about the Bay Area only. A pass justifies building public-data graphs for target-only cities (for example Pittsburgh and Portland) and running the frozen models there.

### Compute

Five seeds of four networks on three folds, plus tuning trials, come to roughly 150 training runs. I have not yet timed one SPECTRA run on the Mac mini. The first run gets timed; if the total exceeds about four days of machine time, the training moves to one GPU on GCP. (Open decision 4.)

### Gaps against the v19 patch (M18), flagged rather than hidden

- Two geofences and three folds instead of six geofence folds plus target-only cities; the Wilcoxon test across target-only cities cannot run.
- Tasks T2, T3 and T6 are not run.
- No S-in variant.
- M18 condition 1 requires S-full to beat B2, the best B3 and S-pub; this plan rests the encoder claim on S-pub against B2 and B4, and tests S-full separately with equal supervision (Fable defect 18a).
- B3 covers AlphaEarth only, if accessible. CityFM, the Population Dynamics Foundation Model, the sentence-encoder baseline, B6 and B7 are not run.
- Missing-source augmentation (M11) is not applied in the first run.
- The buffer is a fixed 1 km; M18's later replacement by the range at which crash counts stop correlating is not done.
- The current geofences come from the full builder rather than a separate Tier P-only rebuild; the lineage manifest enforces Tier P inputs instead.

---

## Order and timeline (revised)

| When | Work |
|---|---|
| Nov 14 to 15 | Evangelos decides the open questions below; network tool extended; data dictionary written; prompts, catalog, dictionary, loop and tool frozen |
| Nov 15 to 17 | Templates written (half by an author who has not seen the catalog); reference code, drop rule and parser frozen; Test 2 export with lineage manifest |
| Nov 17 to 18 | Test 1 pilot; cost and variance report; final template count set |
| Nov 18 to 22 | Test 1 full run; Fable grades blind |
| Nov 17 to 20 | SPECTRA v0 built; one run timed; compute decision |
| Nov 20 to Dec 4 | Test 2 training and evaluation (earlier if training moves to GCP) |

Work outside this plan (H8, Pittsburgh, the effect library, patch rev 3) waits until both tests report, unless Evangelos decides otherwise.

## Freeze record

| Date | File (in `09-demo/test1/`) | SHA-256 |
|---|---|---|
| Nov 14 | catalog.md (arm A4 description) | d447946179162c4b6dc3188ac70cf631ada736eaa3adda0f163fe5ddd9ef62d8 |
| Nov 14 | dictionary.md (arm A3 description) | dfb4b7e63e4d093a8e537013b8ef9e4b6e9e520710a8beb1b03250a57a56c129 |
| Nov 14 | loop.py (all system prompts, answer rules, SQL tool, network tool) | 223a27e80f02c1bf9848c490ba6634dd4c1547533f7dec5b1bbbb41598d60454 |

These three files were frozen before any template was written. The network tool passed a smoke test on both geofences and both networks (job 124, no model calls).

## Decisions (Evangelos, November 14)

1. **Independent template author:** Evangelos writes 15 non-lookup templates (5 network, 5 what-if, 5 constrained) in the Sheet "Test 1 question templates (Evangelos)". I write the other 15 non-lookup templates and the 10 lookup templates.
2. **Interval-based rules:** approved.
3. **API budget:** the pilot measures the cost; I report it before spending past the current $20.
4. **Compute for Test 2:** time the first SPECTRA run on the Mac mini, then decide between the Mac mini and GCP.

## Change log

| Date | Fable defect | Change |
|---|---|---|
| Nov 14 | 1 (fatal) | Arms split so the network tool and the catalog are tested separately (A1 to A4) |
| Nov 14 | 2 (fatal) | Data-dictionary arm A3 added; half of constrained questions state their definition |
| Nov 14 | 3 | Independent reference implementation; questions state metric, network, one-way rule and projection; buffer-count tolerance |
| Nov 14 | 4 | Freeze of catalog, prompts, loop and tool before templates; independent author for half the templates; pilot questions excluded |
| Nov 14 | 5 | Same answer rules and `ANSWER:` line for every arm; frozen limit checklists; URNs removed before grading |
| Nov 14 | 6 | Template count set from pilot variance (standard error at most 4 points); wild cluster bootstrap |
| Nov 14 | 7 | Interval-based pass, fail and inconclusive rules; interval-based lookup guardrail |
| Nov 14 | 8 | LLM-only arm cut to 30 questions, descriptive only |
| Nov 14 | 9 | Drop rule in frozen code; category-by-geofence table published before the run; step-limit hits reported |
| Nov 14 | 10 (fatal) | Tuning inside source cities by spatial-block cross-validation; equal tuning trials |
| Nov 14 | 11 | Encoder claim rests on S-pub; S-full compared with baselines given equal supervision |
| Nov 14 | 12 | B1 and B2 include every encoder input; B2 frozen by hash first; supervised R-GCN baseline |
| Nov 14 | 13 | Separate segment and intersection heads; primary measure fits one intercept per held-out geofence; HPMS secondary analysis |
| Nov 14 | 14 | Five seeds; minimum effect tied to the B2-to-reference gap and to seed spread |
| Nov 14 | 15 | Strata pooled across folds, local streets not required; "matches" defined; inconclusive outcome |
| Nov 14 | 16 | Encoder and all fitted quantities on source entities only; edges crossing the buffer cut |
| Nov 14 | 17 | Lineage manifest enforced; L_aux from tims_crash up to 2019; no names or URNs |
| Nov 14 | 18 | Gaps section extended; head reads the transferable vector (M4); position-leakage measurement (M13); low-label references; evaluation log |
| Nov 14 | (none) | Drop rule corrected: the walking network includes all non-motorway roads, so walking-route questions stay in Contra Costa; only questions that depend on mapped sidewalks are dropped there. The catalog's own answer rules are removed so that every arm receives the same rules |

*Synapse Partners, LLC — Confidential and Proprietary*
