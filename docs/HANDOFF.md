# Handoff for a new GeoMetis chat

Read this file, then `docs/test-plan-2026-11.md`, before doing anything. The test plan is the scope. Propose nothing outside it without asking Evangelos first.

## Standing rules

- CLAUDE.md in this repository applies: code and ontologies only; no trip data, coordinates, geohashes, device identifiers, query outputs or credentials in the repository; trip tables are read only on the Mac mini through the job runner, which writes aggregates only.
- Keep working on delegated tasks without being prompted. Stop only when a machine runs out of resources, needed data is unavailable, or a decision belongs to Evangelos.
- Before ending a turn with open work, schedule a check-in with send_later, and do the promised work before the check-in fires.
- Write in plain English: every sentence has a subject doing something; no consultant lingo; US spelling; explain acronyms.
- Never handle Evangelos's logins or keys. He enters keys himself.
- Outside language-model APIs see only material that is not client data. Tests 1 and 2 use public data only.
- Any output derived from CITYDATA trips carries "Powered by CITYDATA.ai". CITYDATA trips are for demonstration only.
- At each natural break, update the GeoMetis project files `docs/HANDOFF.md` and `docs/test-plan-2026-11.md` (Projects tool) from the repository. Whenever these files change, also upload them to the Drive folder SPECTRA (id 1sVqDDaxsgCCcM_BD-cT4yya6CJ7DQew6) with the date and time in the title, add "SUPERSEDED - " to the titles of the older copies there, and give Evangelos the Drive links.

## Where things are

- Repository: github.com/simoudise/Geometis, cloned at /home/claude/geometis.
- Mac mini (Media-Server.local, M2, 24 GB): database `geometis`, schema `gkg`, PostgreSQL 17 with PostGIS; Python at ~/geometis-venv/bin/python.
- The Mac mini's work folder appears in the linked MacBook shell as $HOME/mnt/Geometis-mini (on the MacBook: /Volumes/Geometis-mini).
- Job runner: main queue `jobs/inbox/NNN-name.sh` (one at a time, logs in `jobs/logs`); status lane `jobs/status-inbox/sNNN-name.sh` (killed after 120 s, logs in `jobs/status-logs`). The last numbers used are in the State section below.
- Anthropic API key: ~/.geometis-env on the Mac mini. Runner jobs must `source ~/.geometis-env`.
- Answer loop: `09-demo/geometis_v0/loop.py` (modes `geometis` and `baseline`), catalog `catalog.md`, old questions `questions.json`.
- Waymo analyses: `09-demo/waymo/` (H7 service area, H6 urban form).
- Architecture: Google Doc "GeoMetis Architecture v19"; SPECTRA decisions in the Drive file "v19 patch - SPECTRA review decisions of 11-11-26 and 11-12-26 (draft).md" (id 1IdJA87PJB2ZwhIkR5eg-R6kJoXdn_gm2), edits M1 to M18.

## Known traps

- device_commit_files can write stale content when a staged file name is reused. Stage each version under a new name and verify with md5.
- Pass statement_timeout and read-only settings as connection options, not as SET statements, because a rollback undoes a SET.
- The catalog's street definition includes trunk roads; leaving them out broke an earlier answer.
- Long jobs run in the main queue in the foreground; launchd kills processes a job leaves behind.
- `symmetric` is a reserved word in PostgreSQL; the relation table uses `is_symmetric`.
- A job script must end with `|| exit 1` after the Python call, or the runner logs exit 0 for a failed step.

## State on November 22, 2026, 10:00 Pacific (update this section at every handoff)

CURRENT WORK: GeoMetis-GKG, the full geospatial knowledge graph build for San Francisco and the five Contra Costa
cities (brief from Evangelos, Nov 20). Three steps, each stopping for his approval: (1) relation inventory, (2) feasibility
and timing, (3) build. Branch `gkg-full`, made from `a2-stage1-loader` at 9f9ee50. GeoMetis 1 has stopped; this work
has the Mac mini. Job numbers for this work: main queue 200-299, status lane s200-s299. Used so far: main 200-225; status s200-s223. Reserved for the 15.7 work: main 224-239, status s224-s239. Nothing is running or queued.

Step 1 (done, awaiting Evangelos's approval): inventory of all 285 object properties in UKO 15.5, TKO 8.4, MLO 1.7,
REO 1.6.1 and FKO 1.2.1. Code: `07-gkg-builder/relations/dump_object_properties.py` and `classify_inventory.py`
(the classification is a hand-written table in the second file). Deliverable in Drive SPECTRA > GKG FULL. Result:
99 properties can be built from data we can access (17 stored in full or part, 46 computable, 36 need a rule from
Evangelos); 8 need public downloads; 18 carry a crash flag and must never be inputs to a crash-prediction test.
Naming fixes on the branch (not yet applied to the database): `seg_adjacent` relabeled uko:touches; `seg_intersects`
documented as uko:adjacentSegment with new view `rel_adjacent_segment` (node -> segment); `segment_within_tract`
relabeled uko:withinCensusTract; new view `rel_connects_to_transit` (segment -> stop, UKO direction; v19 9.4 differs).

RESOURCE FLAG: the Mac mini data volume is 99 percent full (15 GiB free; database 55 GB). Step 2 must size every
relation family against this; freeing space is Evangelos's decision.

Step 1 approved by Evangelos (Nov 20, 13:25 Pacific); his rule decisions are in docs/gkg-full-decisions.md, with
his addition: record distances to important buildings and districts. Public downloads done (jobs 202-204, folder
~/geometis-data/gkg/public/2026-11-20 with MANIFEST.tsv). Disk: Evangelos freed space; 126 GiB free at 11:39 Pacific.
Ontologies (Nov 20 afternoon, at Evangelos's request): coordinated release 2026-11-20 in 01-ontologies:
uko_ontology_v15_6.ttl, tko_ontology_v8_5.ttl, mlo_ontology_v1_7_1.ttl, reo_ontology_v1_6_2.ttl, fko_ontology_v1_2_2.ttl,
generated by tools/make_uko_15_6.py and tools/make_companions_2026_11_20.py; tools/check_stack.py reports zero problems;
HermiT (-k) finds the set consistent. The old 2026-09-19 set is inconsistent (language-tagged literals under xsd:string
ranges in MLO and REO). 15.5 and the old companions stay for the frozen Tests 1 and 2. The builder now reads UKO 15.6
(gkg/config.py ONTOLOGY_RELEASE). Relation inventory scripts default to the new set (RELEASE env var; 295 properties).

Step 2 (done, awaiting Evangelos's approval): docs/gkg-full-step2-feasibility.md. Jobs 205 (failed on a SQL cast,
fixed), 206 (relations/feasibility.py, 2 percent samples, 104 s) and 207 (relations/feasibility2.sh, OSM load,
parks, shared buildings, TIMS-CCRS check); status s212-s215. Result: about 125 million rows, about 25 GB with text
URNs or about 9 GB with integer entity keys; about 2 to 2.5 hours on the Mac mini; Google Cloud not needed.
Scratch schemas gkg_feas and gkg_feas2 were dropped. Files on the Mac mini: work/gkg-full (feasibility code copies,
feas-2pct/feasibility.json). Disk: 71 GiB free at 14:28 (local Time Machine snapshots reappear hourly).
Decisions needed before Step 3: section 5 of the Step 2 document.

Step 3 (done, Nov 20, 17:30 Pacific; awaiting Evangelos's review). Evangelos approved the six Step 3 decisions
("1. yes 2. ok 3. ok 4. ok 5. ok 6. ok"). Code: 07-gkg-builder/relations/build.py (steps schema to cleanup),
validate.py, make_dictionary.py, catalogue/*.tsv; commit 211eb22 is the code version in gkg.provenance. Jobs 208-221
(208-211 and 213 failed on SQL errors that were fixed; each step was rerun alone). Result: 1,532,717 entities,
58,655,659 edges in 78 relations with 100 provenance rows, 28,053,993 distance measurements; edges 5.2 GB; database
63 GB; 54 GiB free. All invariants are zero except district walking distances that the 20 m node rule makes shorter
than the boundary distance (documented). Enforcement removed 352,082 edges that failed UKO 15.6 domains or ranges
(gkg.edge_rejected). Validation file: work/gkg-full/validation-2026-11-20.json on the Mac mini. Data dictionary:
docs/gkg-full-data-dictionary.md. Handoff for Chats 3a and 3b: docs/gkg-full-handoff-3a-3b.md. Build report with
counts, gaps and three open decisions: Drive SPECTRA > GKG FULL. The scratch schemas gkg_work and gkg_load were dropped.
Nov 22 (Evangelos, 08:59 Pacific): (1) tighter crosswalk rule approved, now nearest road within 7 m and 30 degrees
of perpendicular; (2) government buildings stay landmarks; (3) UKO 15.7 generated. Coordinated release 2026-11-22:
uko_ontology_v15_7.ttl, tko_ontology_v8_5_1.ttl, mlo_ontology_v1_7_2.ttl, reo_ontology_v1_7_0.ttl,
fko_ontology_v1_2_3.ttl (tools/make_uko_15_7.py, tools/make_companions_2026_11_22.py); check_stack zero problems,
HermiT consistent with witness individuals. The builder reads 15.7 (gkg/config.py). Job 222 rebuilt the affected
relations: 59,444,055 edges, 1,334 removed by enforcement, gkg.entity_type empty; validation file
work/gkg-full/validation-2026-11-22.json. The complete method is docs/gkg-full-methodology.md (generated by
relations/make_methodology.py from relations/methodology_head.md and the catalogue). Decisions log: section H of
docs/gkg-full-decisions.md. Nov 22, 09:34: at Evangelos's request 15.7 also carries audit items O2, O3 and O12, and
REO became 1.7.0 with item O1 (crash to segment, KABCO with per-state mapping); file reo_ontology_v1_7_0.ttl replaces
the short-lived reo_ontology_v1_6_3.ttl. Jobs 224-225 built reo:onRoadSegment and reo:hasKABCOSeverity (both
crash-derived): 59,570,786 edges in 80 relations, 102 provenance rows; validation-2026-11-22b.json. Job 223 ran
VACUUM FULL on gkg.edge (4.9 GB). Disk: 39 GiB free. Open for Evangelos: audit question T3-9 (non-collision incidents).
The stage-3 place mapping in gkg/stage3_places.py does not yet carry the landmark class overrides (Theater,
ConcertHall, OperaHouse, CityHall); relations/build.py applies them in gkg.entity only.

Earlier state (Tests 1 and 2, closed):

Done:
- Test plan revision 2 approved; Fable's 18 defects accepted (docs/test-plan-2026-11.md, change log).
- Test 1: five arms in 09-demo/test1/loop.py; catalog.md and dictionary.md frozen; 25 Claude templates with
  independent references; gen.py, run.py, score.py. Dry-run pool (seed 20261114) is for smoke tests only.
- Test 1 pilot (job 131, seed 58231907, `pilot_select.py`, `pilot_report.py`): 50 questions on A1 to A4, 10 on A0,
  210 runs, none failed, $12.30 total ($0.053 to $0.069 per run on A1 to A4). Step-limit hits A1 14%, A2 6%,
  A3 4%, A4 4%. With 30 non-lookup templates and 6 questions each the standard errors are 3.3 to 3.6 points
  (target 4); bootstrap medians of the needed count range 19 to 39. Recommendation sent: keep 30 templates.
  Pilot questions (runs-pilot, pool-pilot on the Mac mini) must be excluded from the full set.
- loop.py per-call timing (model_calls; tool seconds) and run.py step summary, after the pilot; new loop.py
  SHA-256 29778409... in the freeze record; checked with status job s152.
- Test 2 on the Mac mini, under ~/Geometis-mini/work: test2-export (job 130), test2-folds (job 132, folds.py),
  test2-netmetrics (job 133, network_metrics.py: reach and betweenness), test2-features (job 134, features.py;
  feature_list.json SHA-256 742bbc8e... frozen in the plan). SPECTRA v0 code (spectra.py, train_spectra.py) and
  evaluate.py (heads, tuning, append-only held-out log) are written and tested on synthetic data only.
- No held-out label has been read by any evaluation. Rule kept: no held-out evaluation until every method's
  configuration is fixed.

- SPECTRA timing (jobs 135, 136, 139; profiling 137, 138): CPU is faster than MPS on this graph; S-full 74 s per
  epoch on CPU for fold 1. Estimate about 2 days for all Test 2 training on the Mac mini (change log, Nov 14).
  Tile cache added. B4 baselines written (baselines_gnn.py: rgcn, rgcn-eq, sage), tested on synthetic data.

Decided by Evangelos (Nov 14, 13:36): 30 non-lookup templates; Test 2 stays on the Mac mini.

Test 1 templates (Nov 14, 16:30): Evangelos's 15 templates are in templates_evangelos.py (author "evangelos"),
with his corrections and the implementation decisions in the plan's change log. All Test 1 files are frozen by
hash (freeze record). Development pools for checks are in work/demo/test1/dev-ev (seed 1; not used in any run).

Test 1 full pool (job 141a, done): 216 questions from 40 templates (Claude 126, Evangelos 90), 48 pilot repeats
removed; table and hashes in the plan's change log (published before the run).

Fold f1 tuning is complete (validation deviance on source CV group 0; lower is better):
- S-pub: trial 6, tau 0.1, lr 0.0005, 2 layers, mask 0.2, relation drop 0.2, 10 epochs: 0.4647.
- S-full: trial 7, tau 0.1, lr 0.0005, 2 layers, mask 0.3, relation drop 0.2, 20 epochs: 0.4427.
- R-GCN: trial 1, lr 0.0005, 2 layers, 10 epochs: 0.4349. Equal-supervision R-GCN: same config: 0.4355.
- GraphSAGE: trial 2, lr 0.0005, 2 layers, 10 epochs: 0.5017.
The R-GCN jobs 142 and 143 crashed (a tile with no labeled entity) and were rerun as 144-u-* after the fix.

Fold f2 tuning is complete (validation deviance on source CV group 0):
- S-pub: trial 6, tau 0.1, lr 0.0005, 2 layers, mask 0.2, relation drop 0.2, 10 epochs: 0.4509.
- S-full: trial 5, tau 0.2, lr 0.0005, 2 layers, mask 0.3, relation drop 0.1, 20 epochs: 0.4300.
- R-GCN: trial 6, lr 0.001, 3 layers, 10 epochs: 0.4214. Equal-supervision R-GCN: trial 0, lr 0.002, 3 layers,
  20 epochs: 0.4218.
- GraphSAGE: trial 2, lr 0.0005, 2 layers, 10 epochs: 0.4683.

Test 1 is complete (job 146-x, Nov 15 20:11 UTC). Every arm has all its answers (A0 90; A1 to A4 648 each).
Cost $272.58 for the full run, plus $12.30 for the pilot. Step-limit hits: A1 25%, A2 19%, A3 18%, A4 18%.
Verdicts under the plan's rules (non-lookup, 168 questions, 30 templates):
- A-tool (A2 - A1): +11.7 [+6.4, +17.0], inconclusive.
- A-knowledge (A4 - A2), primary: +7.1 [-1.0, +15.5], inconclusive.
- A-ontology (A4 - A3): +2.8 [-2.2, +7.7], fail.
- Lookup guardrail: +9.0 [-4.1, +22.2], holds.
Descriptive: A-knowledge is -3.0 on Claude's templates and +15.9 on Evangelos's; A4 - A2 is about +30 on
constrained, -10 on network and +1 on what-if. Full output: end of jobs/logs/146-x-test1-full-finish.log.

Blind grading is complete (first batch 678 items, resubmitted 216 with a 4,000-token cap; merged in
work/demo/test1/grading-full/grades-merged.csv; about $13.49). Correct explanations: A0 0%, A1 63%, A2 68%,
A3 72%, A4 73%. Applicable limits stated: A0 17%, A1 32%, A2 38%, A3 78%, A4 81%. A3 and A4 were told the limits,
so the limit share partly measures repetition. Evangelos's 10 percent sample: grading-full/check-sample-10pct.csv
(89 items, seed 20261116).

Test 2: fold f1 and f2 final runs and fold f3 tuning are complete; every trained network passes the M13 leakage
rule on f1 and f2. Fold f3 winners are in the plan's change log (Nov 16).

Test 2 is complete (job 155 ended 01:59 UTC Nov 20, no failures; job 156 ran the frozen analysis on
work/test2-eval/all). Bet B: FAIL. S-pub is worse than B2 in every fold and stratum (pooled gain -0.062, interval
-0.074 to -0.051). No graph network beats B2 alone; the combined EMB+B2 sets are slightly worse than B2. The
in-geofence reference is worse than B2 on the two Contra Costa folds (recorded in the change log, Nov 20).
Full output: jobs/logs/156-test2-analyze.log. S-pub-untyped is not run (Evangelos's rule: only if S-pub passes or
is inconclusive). Per the plan, SPECTRA training stops until a different design or more data gives a reason.

Spending rule (Evangelos, Nov 15): every step that spends money must be needed to answer Bet A or Bet B;
otherwise stop. Test 2 spends no API money (Mac mini only).

Decisions on Nov 17 (Evangelos): the Test 1 A-ontology fail stops treating the ontology as something the model
reads. The step-limit reruns and the A-tool and A-knowledge checks are exploratory; the frozen verdicts stand.

FLAG AGAINST THE ARCHITECTURE (v19), recorded Nov 19 at Evangelos's request: the v19 components for the ontology
as model input and for SPECTRA have no supporting evidence after Tests 1 and 2 (Test 1 A-ontology fail; Test 2 Bet B
fail). Make no architecture revisions until the Test 3 pilot.

Decisions Nov 19 (Evangelos): verdict accepted; SPECTRA training and S-pub-untyped stop; no rescue designs.

Done Nov 20: job 157, the reference diagnostic (outside the verdict). B2 still beats the tuned reference on both
Contra Costa folds (+0.020 and +0.029, intervals exclude zero); San Francisco unchanged. Change log, Nov 20.
Internal report on Tests 1 and 2: Drive folder SPECTRA, "GeoMetis Tests 1 and 2 report 2026-11-20.md".

Work stopped by Evangelos on Nov 20: "finish your reports and then stop." The city2graph comparison ended at the
road-graph probe (change log, Nov 20). The final internal report on Tests 1 and 2 is in the Drive folder SPECTRA.
Nothing is running or queued on the Mac mini, and no check-in is scheduled. Start new work only on Evangelos's
instruction; the Test 3 pilot is the next decision point named in the architecture flag above.

Open question for after Thursday (no work now): (a) does the ontology improve transfer to cities with different data
sources compared with standard schemas; (b) could city2graph build Test 3 graphs in place of our builder.

Later (not for Tests 1 or 2):
- Builder fallback for cities with no GTFS feed: city2graph (github.com/c2g-dev/city2graph) added load_osm_transport,
  which builds a synthetic GTFS feed from OSM routes and stops with adjustable assumptions and can add planned routes
  for what-if questions. city2graph is already in the architecture's builder plan (Section 11). If adopted, mark every
  synthetic stop, route and departure as synthetic in the graph and add it to the catalog's source limits. Not for
  Tests 1 or 2.

GCP: project "geometis", GPUS_ALL_REGIONS = 1 approved on Nov 14; us-central1 L4 limit already 1. Nothing created.

*Synapse Partners, LLC — Confidential and Proprietary*
