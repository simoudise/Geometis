"""Generate Test 1 questions and reference answers from the templates. No model calls.

python gen.py SEED OUTDIR [template ids...]
Writes OUTDIR/pool.jsonl (one question per line, with its reference answer) and OUTDIR/questions.jsonl (qid and
question only, for the arms). Runs on the Mac mini; the output stays there (query outputs are not committed).
"""
import json, os, sys, time, traceback, zlib
import numpy as np
import psycopg
import templates_claude as TC

def main():
    seed, outdir = int(sys.argv[1]), sys.argv[2]
    only = set(sys.argv[3:])
    os.makedirs(outdir, exist_ok=True)
    conn = psycopg.connect("dbname=geometis", options="-c statement_timeout=600000 -c default_transaction_read_only=on")
    pool = []
    for tid, cat, stated, kind, text, sampler in TC.T:
        if only and tid not in only: continue
        for gi, gf in enumerate([TC.CC, TC.SF]):
            rng = np.random.default_rng([seed, zlib.crc32(tid.encode()), gi])
            t = time.time()
            try:
                items = sampler(conn, gf, rng, 3)
            except Exception:
                print(f"{tid} {gf} FAILED"); traceback.print_exc(); continue
            for j, it in enumerate(items):
                qid = f"{tid}-{'cc' if gf == TC.CC else 'sf'}{j+1}"
                question = text.format(**it["slots"]) + " " + TC.FORM[kind]
                pool.append({"qid": qid, "template": tid, "category": cat, "author": "claude", "stated_definition": stated,
                             "geofence": gf, "kind": kind, "question": question, "answer": it["answer"]})
            print(f"{tid} {gf}: {len(items)} questions in {time.time()-t:.1f} s", flush=True)
    with open(os.path.join(outdir, "pool.jsonl"), "w") as f:
        for p in pool: f.write(json.dumps(p, default=str) + "\n")
    with open(os.path.join(outdir, "questions.jsonl"), "w") as f:
        for p in pool: f.write(json.dumps({"qid": p["qid"], "question": p["question"]}) + "\n")
    print("total", len(pool))

if __name__ == "__main__":
    main()
