# GeoMetis test plan: two bets, two tests (draft for review, November 14, 2026)

Status: DRAFT. Evangelos approved the pass thresholds on November 14, 2026, as a starting point that we may tighten later. Fable reviews the design before any run. After the review, this document is frozen. Any later change is listed in the change log at the end, with its date and reason, before the run it affects.

## Why this plan exists

We have produced 19 versions of the architecture without learning whether the System works. This plan replaces argument with two tests. Each test has a pass rule and a fail rule written before it runs. A failed test stops the line of work it tests.

Everything larger (Chora, a Waymo or Google project, more geofences) rests on two bets:

- **Bet A.** The symbolic layer (the ontology, the knowledge catalog and the network tools) makes a language model answer geospatial questions better than the same model with SQL alone, or with no tools.
- **Bet B.** SPECTRA embeddings learned from the knowledge graph predict outcomes in a place the model did not train on better than features built by hand.

Test 1 tests Bet A. Test 2 tests Bet B. Neither test uses trip data, so every input and output is public (Tier P inputs, Tier R crash labels), and the trained weights carry no Tier 3 restriction.

## Data both tests use

Two geofences are already built in the database `geometis` on the Mac mini:

| Geofence | Road segments | Intersections | Places | Pedestrian edges | Transit stops | Census tracts |
|---|---|---|---|---|---|---|
| us-ca-contra-costa-5 (Antioch, Concord, Pittsburg, Pleasant Hill, Walnut Creek) | 89,695 | 71,947 | 28,604 | 24,310 | 1,639 | 116 |
| us-ca-san-francisco | 61,175 | 49,521 | 78,789 | 72,482 | 3,849 | 261 |

Injury crashes (TIMS, attached to segments and intersections): Contra Costa has about 2,200 a year (9,639 in 2021 to 2025); San Francisco has about 3,300 a year (16,375 in 2021 to 2025). 2026 is partial and is not used.

---

## Test 1: does the symbolic layer help? (Bet A)

### Arms

All three arms use the same model (claude-sonnet-5-5) with the same settings, and each answers every question three times.

1. **LLM only.** The model receives the question and a one-paragraph description of the two geofences. It has no tools.
2. **SQL only.** The model receives a plain listing of the schema and a read-only SQL tool. This is the current baseline in `09-demo/geometis_v0/loop.py`.
3. **GeoMetis v0.** The model receives the knowledge catalog (`catalog.md`), the same SQL tool and the `shortest_path` network tool.

All arms keep the existing limits: at most 14 steps, a forced final answer at the step limit, tool output capped at 12,000 characters, and trip tables refused.

### Questions

The current 23 questions are too few to detect anything but a very large difference. Test 1 replaces them with templates. Each template is a question with blanks (a station, a school, a city or a place category). Code fills the blanks from the graph and computes the reference answer for each filled-in question. The target is 150 to 250 questions in four categories:

| Category | What the question needs | Example template | How code computes the answer |
|---|---|---|---|
| Lookup | Filter and count | "How many grocery stores lie inside the Concord city core?" | SQL count |
| Network | Distances or reach over the street or walking network | "What is the walking distance along the pedestrian network from {BART station} to the nearest grocery store?" | Shortest path over pedestrian edges |
| What-if | The network after a change | "If {bridge segment} closed, how much longer would the shortest drive be from {A} to {B}?" | Shortest path before and after removing the segment |
| Constrained | Definitions and source limits from the catalog | "Which street segments within 500 m of {school} carry a posted limit above 25 mph?" | SQL with the catalog's street definition and the posted-limit rule |

Lookups test whether the symbolic layer costs anything on easy questions. The HERE and Zephr prototype (a language model on top of HERE's maps, for example "an Irish bar within walking distance") answered lookups correctly and drew only moderate interest. Lookups therefore count as a guardrail, not as evidence for the System.

Rules for the questions:

- I write the templates and the reference code, then freeze both (file hashes recorded here) before any arm runs.
- The filled-in questions are drawn at random with a recorded seed, balanced across the two geofences.
- A question is dropped before the run if its reference answer depends on data the catalog lists as unreliable (for example, the absence of a sidewalk in Contra Costa). The drop list is recorded before the run.

### Scoring

- **Primary score (automatic).** Code compares each final answer with the reference answer: counts must match exactly; distances and lengths must fall within 5 percent; lists score as correct when the F1 overlap with the reference list reaches 0.8. A per-template extraction rule pulls the number or list from the answer text. Answers the rule cannot parse go to the grader below.
- **Secondary score (blind).** Fable grades two things without knowing which arm wrote the answer: whether the answer states the source limits that affect it, and whether its explanation is correct. Arm names, tool calls and step counts are removed before grading. Evangelos checks a random 10 percent of Fable's grades.
- The unit of analysis is the filled-in question. Each arm's score on a question is the mean of its three runs.

### Pass and fail rules

- **Pass:** on network, what-if and constrained questions combined, GeoMetis v0 scores at least 15 percentage points higher than SQL only, and the 95 percent confidence interval of the difference excludes zero. On lookups, GeoMetis v0 scores no more than 5 points below SQL only.
- **Fail:** GeoMetis v0 scores within 5 points of SQL only on network, what-if and constrained questions. The symbolic layer then adds nothing worth its cost, and we stop building on it in its current form.
- **Between pass and fail:** the result is inconclusive. We report it as inconclusive and decide with Evangelos whether a larger question set is worth running.
- **LLM only:** if LLM only scores within 5 points of GeoMetis v0, the graph itself adds nothing. We expect LLM only to score lowest by a wide margin. Test 1 measures that margin; it is not a pass condition.
- **Confidence interval:** a bootstrap that resamples templates first and questions within templates second, so that 40 questions from one template do not count as 40 independent observations.

### Cost and order

- A pilot of 50 questions across all three arms runs first. The pilot measures cost per question and finds setup errors. Pilot results do not count toward the test, and the frozen files do not change after the pilot except to fix bugs, which go in the change log.
- Before spending more than the current $20 of API credit, I report the measured cost to Evangelos. The full test needs roughly 2,000 to 4,000 model calls.
- Calls run 8 to 10 at a time from the Mac mini.

---

## Test 2: do SPECTRA embeddings predict in a new place? (Bet B)

Test 2 is a reduced version of the transfer evaluation in the v19 patch (M18). The reductions are listed under "Gaps against the v19 patch" below.

### What gets built

SPECTRA v0 as the v19 patch specifies, trained on the Mac mini:

- Node types: road segments, intersections, places, pedestrian edges, transit stops and census tracts, with their graph relations.
- Inputs: Tier P only (M7d). No crash-derived and no trip-derived input enters the encoder. The location block never enters the encoder; the shape block does (M3).
- Positives: 50 percent two-view pairs and 50 percent form-versus-function pairs (M1j).
- Negatives: distance-matched negatives of the same node type plus debiased in-batch negatives (M2).
- InfoNCE loss with temperature 0.15 (M2b).
- Fixed, unit-based feature transforms; no city indicator (M8, M9).

Two variants:

- **S-pub:** the default losses only.
- **S-full (crash only):** S-pub plus the auxiliary head L_aux (M17), which predicts 2015 to 2019 injury-crash counts in the source geofences only. The patch's trip-end head and flow pairs are left out, so S-full here uses no trip data.

### Task and target

Task T1 from M18: injury-crash frequency per street segment and per intersection, counted over 2021 to 2025. Training never sees 2021 to 2025 crash counts in the held-out geofence. L_aux uses only 2015 to 2019.

### Feature sets compared

Every feature set feeds the same prediction head: gradient-boosted trees with a Poisson objective and segment length as the exposure term. The head trains on source entities only.

- **B0:** source mean by road class and area type.
- **B1:** each entity's own Tier P attributes.
- **B2:** B1 plus hand-built neighborhood aggregates over 1 to 3 hops and rings of 250 m, 500 m and 1 km.
- **B3:** AlphaEarth satellite embeddings, if I can get access through Google Earth Engine. If access fails, B3 is dropped and the drop is recorded.
- **B4:** GraphSAGE trained on the same graph with the same compute budget.
- **S-pub** and **S-full**, each alone and each combined with B2.
- **In-geofence reference:** a model trained on the held-out geofence's own labels, with spatial block cross-validation. This model sets the ceiling.

### Splits

Three folds, following M18's cluster folds:

1. Hold out Walnut Creek, Pleasant Hill and Concord; train on Antioch, Pittsburg and San Francisco.
2. Hold out Antioch and Pittsburg; train on the other three Contra Costa cities and San Francisco.
3. Hold out San Francisco; train on the five Contra Costa cities.

Source entities within 1 km of the held-out boundary are removed from training. Every configuration choice (epochs, temperature within 0.1 to 0.2, head settings) is fixed on folds 1 and 2. Fold 3, San Francisco, then runs once with the frozen configuration.

### Measures

- **Primary (named before the run):** Poisson deviance of the held-out predictions, computed within road-class strata (arterial, collector and local, intersections) and pooled.
- **Secondary:** the share of 2021 to 2025 injury crashes that fall on the top 5 percent of network length as ranked by the prediction.

### Pass and fail rules

SPECTRA passes only if all of these hold for the better of S-pub and S-full:

1. It beats B2 and B4 on the pooled primary measure.
2. The paired difference against B2 is in SPECTRA's favor in all three folds.
3. A bootstrap over spatial blocks gives a 95 percent interval for the pooled difference that excludes zero.
4. The advantage holds inside each road-class stratum.
5. It closes at least half of the gap between B1 and the in-geofence reference.
6. The San Francisco fold is not negative.

Fail rules:

- If SPECTRA does not beat B2, the learned encoder adds nothing to hand-built features at this scale. We stop investing in SPECTRA training until a different design or more data gives a reason to try again.
- If S-full matches S-pub, the auxiliary crash supervision contributes nothing.

### Known weaknesses

- The graph has no traffic volumes, so every feature set partly learns that busy roads have more crashes. The test compares feature sets under the same handicap, and the report states the handicap.
- Three folds from one metropolitan region support statements about the Bay Area only. A pass justifies building public-data graphs for target-only cities (for example Pittsburgh and Portland) and running the same frozen models there. It does not establish transfer in general.

### Gaps against the v19 patch (M18), flagged rather than hidden

- Two geofences and three folds instead of six geofence folds plus target-only cities. The Wilcoxon test across target-only cities (M18 condition 2, second half) cannot run yet.
- Task T2 (commute flows against LODES), T3 (trip-end shares) and T6 (High Injury Network) are not run. T3 needs trip data; T2 and T6 can be added later without changing the frozen T1 result.
- No S-in variant, because S-in reads Tier R and T inputs.
- B3 covers AlphaEarth only (if accessible). CityFM, the Population Dynamics Foundation Model and the sentence-encoder baseline are not run. B6 (merged node types) and B7 (a language model given each entity's description) are not run.
- The canary and trip-leakage controls of M18 do not apply, because no trip data enters.
- The current geofences come from the full builder, not from a separate Tier P-only rebuild. The encoder reads only Tier P properties, so the inputs match; the separate rebuild matters once trip data or Tier S data exists.

---

## Order and timeline

| When | Work |
|---|---|
| Nov 14 | This draft; Fable reviews the design |
| Nov 15 | Revise per review; freeze; new chat starts from this document |
| Nov 15 to 17 | Test 1 templates and reference code, frozen; Test 2 data export from the database |
| Nov 17 to 18 | Test 1 pilot (50 questions); cost report |
| Nov 18 to 20 | Test 1 full run; Fable grades blind (Fable's allowance renews Mondays at noon) |
| Nov 17 to 26 | SPECTRA v0 build and training on folds 1 and 2; configuration frozen |
| about Nov 27 | Test 2: San Francisco fold runs once; report |

Work outside this plan (H8, Pittsburgh, the effect library, patch rev 3) waits until both tests report, unless Evangelos decides otherwise.

## Change log

(empty)

*Synapse Partners, LLC — Confidential and Proprietary*
