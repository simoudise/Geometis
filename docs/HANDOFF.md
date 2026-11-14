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

## State on November 14, 2026, 11:45 Pacific (update this section at every handoff)

Done:
- Test plan revision 2 approved; Fable's 18 defects accepted (docs/test-plan-2026-11.md, change log).
- Test 1: five arms in 09-demo/test1/loop.py; catalog.md and dictionary.md frozen (hashes in the plan); network tool
  `network_path` (road and walk networks, segment removal); 25 Claude templates (templates_claude.py) with
  independent references (reference.py, SciPy and PostGIS); generator gen.py; parallel runner run.py; scorer score.py.
  Dry-run pool (seed 20261114) and a 2-question smoke test (job 129) exist on the Mac mini; neither may be used in
  the pilot or the full set. Measured cost: about $0.11 per run on arms A1 to A4.
- Test 2: export.py wrote Tier P features, edges, crash labels and cores to ~/Geometis-mini/work/test2-export
  (job 130), with the lineage check passing.

Waiting on Evangelos:
- $400 of API credit (decided; he adds it at platform.claude.com/settings/billing). The pilot needs it.
- His 15 templates in the Sheet "Test 1 question templates (Evangelos)"
  (https://claude.ai/artifact/XSwwaWghxUitpkHonAxcJQ). Translate each into a sampler and a reference function in
  templates_evangelos.py, with author "evangelos".

Next steps, in order:
1. When credit is in: generate the pilot pool with a new seed (not 20261114), 50 questions across Claude's
   templates; run A1 to A4 once and A0 on 10; report cost per run, step-limit hits and the variance between
   templates; set the final template count (standard error of A4 minus A2 at most 4 points).
2. Test 2: folds.py (city membership from cores.parquet, 1 km buffer, edges crossing the buffer cut, 1 km spatial
   blocks); B0/B1/B2 feature builder with the B2 list frozen by hash before SPECTRA trains.
3. SPECTRA v0 model code per v19 patch M1 to M4, M7, M8, M9, M13, M17; time one training run; then decide Mac mini
   or GCP (project "geometis", one L4 GPU in us-central1 approved; gcloud not yet installed on the Mac mini).
4. When Evangelos's templates arrive: implement them, freeze all templates, reference code, drop rule and parser by
   hash, then run the full Test 1.

GCP: project "geometis", GPUS_ALL_REGIONS = 1 approved on Nov 14; us-central1 L4 limit already 1. Nothing created.

*Synapse Partners, LLC — Confidential and Proprietary*
