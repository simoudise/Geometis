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

## State on November 15, 2026, 06:50 Pacific (update this section at every handoff)

All work is on branch `a2-stage1-loader` (main still stops at November 3). Last numbers used: main queue 149 (plus 141a, 144-u-*, 144a, 149a1 to 149a5, 146-x),
status lane s188. Job scripts now start with `set -o pipefail` so that a failure is not hidden by grep.

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

Running and queued (main queue, in order):
- Job 144a (full Test 1 run) ended at 12:02 UTC Nov 15 with 711 runs failed (A3 68, A4 643): loop.py leaks an API
  client and a database connection per answer, and the runner allows 256 open files. Finished runs are clean
  (scan_infra_errors.py). Cost so far $199.31. Details in the plan's change log (Nov 15).
- 146 fold f2 S-full tuning (running).
- 146-x finishes Test 1: open-file limit 4,096, missing A3 and A4 runs in processes of 24 questions, then
  score.py and analyze_full.py. Expected about 4 hours and about $70.
- 147 to 149 fold f2 tuning; 149a1 to 149a5 fold f1 final runs.

Next steps, in order:
1. When job 146-x ends: report cost, step-limit hits and primary scores by arm, category and author group; run the
   wild cluster bootstrap and the pass rules; prepare the blind grading packet for Fable (limits.json).
2. When f2 tuning ends: queue f3 tuning (San Francisco last; same five networks).
3. After f2 tuning: queue the f2 final runs the same way (copy 149a* with the fold changed). After each fold's tuning: 5 seeds per network with the winning config (train_spectra.py with --overrides and
   --epochs from tuning.json; baselines_gnn.py likewise). Check each run's leakage against its control.
4. Only when every method's configuration is fixed on every fold: evaluate.py on held-out folds for all methods
   (B0, B1, B2, B2-eq, EMB and EMB+B2 for each network), then the block bootstrap and the pass rules.
5. Blind secondary grading of Test 1 by Fable with limits.json; Evangelos checks 10 percent.

GCP: project "geometis", GPUS_ALL_REGIONS = 1 approved on Nov 14; us-central1 L4 limit already 1. Nothing created.

*Synapse Partners, LLC — Confidential and Proprietary*
