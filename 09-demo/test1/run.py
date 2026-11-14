"""Run Test 1 arms in parallel and record cost.

python run.py QUESTIONS.jsonl OUTDIR --arms A1,A2,A3,A4 --runs 1 --workers 8 [--limit N]
Each (arm, question, run) is skipped if its result file exists, so a stopped run resumes.
Prices are read from env GEOMETIS_PRICE_IN, _OUT, _CACHE_READ, _CACHE_WRITE (dollars per million tokens);
without them the summary reports tokens only.
"""
import argparse, json, os, sys, time
from concurrent.futures import ThreadPoolExecutor, as_completed
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import loop

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("questions"); ap.add_argument("outdir")
    ap.add_argument("--arms", default="A1,A2,A3,A4"); ap.add_argument("--runs", type=int, default=1)
    ap.add_argument("--workers", type=int, default=8); ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()
    qs = [json.loads(l) for l in open(a.questions)]
    if a.limit: qs = qs[:a.limit]
    jobs = []
    for arm in a.arms.split(","):
        d = os.path.join(a.outdir, arm)
        for r in range(1, a.runs + 1):
            for q in qs:
                if not os.path.exists(os.path.join(d, f"{q['qid']}_r{r}.json")):
                    jobs.append((arm, q, r, d))
    print(f"{len(jobs)} runs to do", flush=True)
    t0, done, fails = time.time(), 0, 0
    with ThreadPoolExecutor(a.workers) as ex:
        futs = {ex.submit(loop.answer, arm, q["qid"], q["question"], r, d): (arm, q["qid"], r) for arm, q, r, d in jobs}
        for f in as_completed(futs):
            arm, qid, r = futs[f]
            try:
                o = f.result(); done += 1
                print(f"{arm} {qid} r{r}: {o['tool_calls']} calls, {o['seconds']} s, ANSWER={o['answer_line']}", flush=True)
            except Exception as e:
                fails += 1; print(f"{arm} {qid} r{r} FAILED: {type(e).__name__}: {str(e)[:200]}", flush=True)
    print(f"done {done}, failed {fails}, {time.time()-t0:.0f} s", flush=True)
    summarize(a.outdir)

def summarize(outdir):
    price = {k: float(os.environ[f"GEOMETIS_PRICE_{k.upper()}"]) for k in ("in", "out", "cache_read", "cache_write")
             if os.environ.get(f"GEOMETIS_PRICE_{k.upper()}")}
    for arm in sorted(os.listdir(outdir)):
        d = os.path.join(outdir, arm)
        if not os.path.isdir(d): continue
        tot = {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}; n = lim = 0
        for f in os.listdir(d):
            o = json.load(open(os.path.join(d, f))); n += 1; lim += o.get("hit_step_limit", False)
            for k in tot: tot[k] += o["usage"].get(k, 0)
        cost = ""
        if len(price) == 4:
            c = (tot["input"] * price["in"] + tot["output"] * price["out"] + tot["cache_read"] * price["cache_read"]
                 + tot["cache_write"] * price["cache_write"]) / 1e6
            cost = f", ${c:.2f} total, ${c/max(n,1):.3f} per run"
        print(f"{arm}: {n} runs, {lim} hit the step limit, tokens {tot}{cost}")
        steps(d, price)

def steps(d, price, top=5):
    """Slowest and most expensive steps of one arm, from the per-call records loop.py writes (model_calls and
    the seconds of each tool call). Runs written before those records existed are skipped."""
    mc, tc = [], []
    for f in os.listdir(d):
        o = json.load(open(os.path.join(d, f)))
        for c in o.get("model_calls", []):
            usd = ((c["input"] * price["in"] + c["output"] * price["out"] + c["cache_read"] * price["cache_read"]
                    + c["cache_write"] * price["cache_write"]) / 1e6) if len(price) == 4 else None
            mc.append({**c, "qid": o["qid"], "run": o["run"], "usd": usd})
        for c in o.get("ledger", []):
            if "seconds" in c: tc.append({"qid": o["qid"], "run": o["run"], "step": c["step"], "tool": c["tool"], "seconds": c["seconds"]})
    if not mc: return
    ms = sum(c["seconds"] for c in mc); ts = sum(c["seconds"] for c in tc)
    print(f"  {len(mc)} model calls, {ms:.0f} s (mean {ms/len(mc):.1f} s); {len(tc)} tool calls, {ts:.0f} s (mean {ts/max(len(tc),1):.1f} s)")
    fmt = lambda c: f"{c['qid']} r{c['run']} step {c['step']}"
    print("  slowest model calls: " + "; ".join(f"{fmt(c)} {c['seconds']:.1f} s, {c['output']} output tokens" for c in sorted(mc, key=lambda c: -c["seconds"])[:top]))
    if mc[0]["usd"] is not None:
        print("  most expensive model calls: " + "; ".join(f"{fmt(c)} ${c['usd']:.3f} ({c['input']} in, {c['cache_read']} cache read, {c['cache_write']} cache write, {c['output']} out)"
                                                         for c in sorted(mc, key=lambda c: -c["usd"])[:top]))
    if tc:
        print("  slowest tool calls: " + "; ".join(f"{fmt(c)} {c['tool']} {c['seconds']:.1f} s" for c in sorted(tc, key=lambda c: -c["seconds"])[:top]))

if __name__ == "__main__":
    main()
