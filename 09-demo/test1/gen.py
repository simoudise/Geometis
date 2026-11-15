"""Generate Test 1 questions and reference answers from the templates. No model calls.

python gen.py SEED OUTDIR [--exclude POOL.jsonl ...] [--only tid,tid]
Writes OUTDIR/pool.jsonl (one question per line, with its reference answer), OUTDIR/questions.jsonl (qid and
question only, for the arms) and OUTDIR/dropped.jsonl (questions removed by drop.py, with the reason). Runs on the
Mac mini; the output stays there (query outputs are not committed).

Fillings per template: at most 6 (docs/test-plan-2026-11.md): 3 per geofence for templates set in both geofences,
6 for templates set in one, except where templates_evangelos.PER sets the split (city questions:
5 Contra Costa cities and San Francisco). Questions whose text appears in an --exclude pool (the pilot) are skipped; the sampler
draws 3 extra fillings per geofence so that exclusions and drops can be replaced.
"""
import argparse, json, os, time, traceback, zlib
from collections import Counter
import numpy as np
import psycopg
import templates_claude as TC
import templates_evangelos as TE
from drop import drop

FORM = {**TC.FORM, "names": "List the answers separated by a vertical bar (|), for example: A | B | C."}

def templates():
    for tid, cat, stated, kind, text, sampler in TC.T:
        yield tid, cat, stated, kind, text, sampler, [TC.CC, TC.SF], False, "claude"
    for tid, cat, stated, kind, text, sampler, gfs, sidewalk in TE.T:
        yield tid, cat, stated, kind, text, sampler, gfs, sidewalk, "evangelos"

def main():
    ap = argparse.ArgumentParser(); ap.add_argument("seed", type=int); ap.add_argument("outdir")
    ap.add_argument("--exclude", nargs="*", default=[]); ap.add_argument("--only", default="")
    a = ap.parse_args()
    only = set(x for x in a.only.split(",") if x)
    excluded = set()
    for p in a.exclude:
        excluded |= {json.loads(l)["question"] for l in open(p)}
    os.makedirs(a.outdir, exist_ok=True)
    conn = psycopg.connect("dbname=geometis", options="-c statement_timeout=600000 -c default_transaction_read_only=on")
    pool, dropped = [], []
    for tid, cat, stated, kind, text, sampler, gfs, sidewalk, author in templates():
        if only and tid not in only: continue
        for gf in gfs:
            per = getattr(TE, "PER", {}).get(tid, {}).get(gf, 6 // len(gfs))
            gi = [TC.CC, TC.SF].index(gf)
            rng = np.random.default_rng([a.seed, zlib.crc32(tid.encode()), gi])
            t = time.time()
            try:
                items = sampler(conn, gf, rng, per + 3)
            except Exception:
                print(f"{tid} {gf} FAILED"); traceback.print_exc(); conn.rollback(); continue
            kept, seen = [], set()
            for it in items:
                question = text.format(**it["slots"]) + " " + FORM[kind]
                if question in seen: continue
                seen.add(question)
                if question in excluded:
                    dropped.append({"template": tid, "geofence": gf, "question": question, "reason": "pilot question"}); continue
                why = drop(sidewalk, gf, it["answer"])
                if why:
                    dropped.append({"template": tid, "geofence": gf, "question": question, "reason": why}); continue
                kept.append((question, it["answer"]))
                if len(kept) >= per: break
            for j, (question, answer) in enumerate(kept):
                qid = f"{tid}-{'cc' if gf == TC.CC else 'sf'}{j+1}"
                pool.append({"qid": qid, "template": tid, "category": cat, "author": author, "stated_definition": stated,
                             "geofence": gf, "kind": kind, "question": question, "answer": answer})
            print(f"{tid} {gf}: {len(kept)} questions ({len(items)} sampled) in {time.time()-t:.1f} s", flush=True)
    with open(os.path.join(a.outdir, "pool.jsonl"), "w") as f:
        for p in pool: f.write(json.dumps(p, default=str) + "\n")
    with open(os.path.join(a.outdir, "questions.jsonl"), "w") as f:
        for p in pool: f.write(json.dumps({"qid": p["qid"], "question": p["question"]}) + "\n")
    with open(os.path.join(a.outdir, "dropped.jsonl"), "w") as f:
        for p in dropped: f.write(json.dumps(p, default=str) + "\n")
    print("total", len(pool), "dropped", len(dropped), dict(Counter(d["reason"] for d in dropped)))
    print("category by geofence (published before the run):")
    c = Counter((p["category"], p["geofence"]) for p in pool)
    for k in sorted(c): print(f"  {k[0]:12s} {k[1]:22s} {c[k]}")
    print("by author:", dict(Counter(p["author"] for p in pool)))

if __name__ == "__main__":
    main()
