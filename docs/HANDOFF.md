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

## Where things are

- Repository: github.com/simoudise/Geometis, cloned at /home/claude/geometis.
- Mac mini (Media-Server.local, M2, 24 GB): database `geometis`, schema `gkg`, PostgreSQL 17 with PostGIS; Python at ~/geometis-venv/bin/python.
- The Mac mini's work folder appears in the linked MacBook shell as $HOME/mnt/Geometis-mini (on the MacBook: /Volumes/Geometis-mini).
- Job runner: main queue `jobs/inbox/NNN-name.sh` (one at a time, logs in `jobs/logs`); status lane `jobs/status-inbox/sNNN-name.sh` (killed after 120 s, logs in `jobs/status-logs`). Last numbers used: main queue 130, status lane s147.
- Anthropic API key: ~/.geometis-env on the Mac mini. Runner jobs must `source ~/.geometis-env`.
- Answer loop: `09-demo/geometis_v0/loop.py` (modes `geometis` and `baseline`), catalog `catalog.md`, old questions `questions.json`.
- Waymo analyses: `09-demo/waymo/` (H7 service area, H6 urban form).
- Architecture: Google Doc "GeoMetis Architecture v19"; SPECTRA decisions in the Drive file "v19 patch - SPECTRA review decisions of 11-11-26 and 11-12-26 (draft).md" (id 1IdJA87PJB2ZwhIkR5eg-R6kJoXdn_gm2), edits M1 to M18.

## Known traps

- device_commit_files can write stale content when a staged file name is reused. Stage each version under a new name and verify with md5.
- Pass statement_timeout and read-only settings as connection options, not as SET statements, because a rollback undoes a SET.
- The catalog's street definition includes trunk roads; leaving them out broke an earlier answer.
- Long jobs run in the main queue in the foreground; launchd kills processes a job leaves behind.

## State on November 14, 2026, 13:30 Pacific (update this section at every handoff)

All work is on branch `a2-stage1-loader` (main still stops at November 3). Last numbers used: main queue 144,
status lane s157.

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

Waiting on Evangelos:
- His 15 templates in the Sheet "Test 1 question templates (Evangelos)"
  (https://claude.ai/artifact/XSwwaWghxUitpkHonAxcJQ), to become templates_evangelos.py with author "evangelos".
  He is working on them now.

Running:
- Fold f1 tuning, jobs 140 to 144 (S-pub, S-full, rgcn, rgcn-eq, sage; tune.py; about 8 to 9 hours in total).
  Output ~/Geometis-mini/work/test2-tune/f1-wc-ph-concord/<network>/tuning.json. tune.py resumes: rerunning a
  job skips finished trials. Tuning rules and the M13 leakage rule are in the plan's change log.

Next steps, in order:
1. When f1 tuning ends: queue f2 tuning (same five jobs), then f3 (San Francisco last).
2. After each fold's tuning: 5 seeds per network with the winning config (train_spectra.py with --overrides and
   --epochs from tuning.json; baselines_gnn.py likewise). Check each run's leakage against its control.
3. Done: evaluate.py method B2-eq (B2 trained on both crash windows, window column), tested on synthetic data.
4. Only when every method's configuration is fixed on every fold: evaluate.py on held-out folds for all methods,
   then the block bootstrap and the pass rules.
5. When Evangelos's templates arrive: implement them, generate the full pool with a new seed excluding pilot
   fillings, freeze templates, reference code, drop rule and parser by hash, then run the full Test 1.

GCP: project "geometis", GPUS_ALL_REGIONS = 1 approved on Nov 14; us-central1 L4 limit already 1. Nothing created.

*Synapse Partners, LLC — Confidential and Proprietary*
