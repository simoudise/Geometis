"""Pilot report for Test 1: accuracy by arm, step-limit hits, variance between templates, template count.

python pilot_report.py SCORES.csv [QUESTIONS_PER_TEMPLATE=6] [TARGET_SE_POINTS=4]
SCORES.csv comes from score.py. Pilot results do not count toward any pass rule
(docs/test-plan-2026-11.md, "Cost and order"); this report sizes the full run.

Template count. For a comparison (for example A4 minus A2), d is the paired difference on one question. A
one-way analysis of variance by template splits the variance of d into a part between templates (vt) and a
part within templates (vw). With T templates and m questions per template, the standard error of the mean
difference is sqrt(vt / T + vw / (T * m)). The pilot runs each question once, so vw contains the run-to-run
noise of a single run; the full run averages three runs per question, which can only lower vw. The template
count printed here therefore errs on the high side. A bootstrap over templates shows how uncertain the count is.
"""
import csv, sys
import numpy as np

NONLOOKUP = ("network", "what-if", "constrained")
COMPARISONS = [("A-knowledge", "A4", "A2"), ("A-tool", "A2", "A1"), ("A-ontology", "A4", "A3")]

def components(groups):
    """groups: list of arrays of paired differences, one array per template. Returns (vt, vw, mean)."""
    groups = [np.asarray(g, float) for g in groups if len(g)]
    n = np.array([len(g) for g in groups]); N, k = n.sum(), len(groups)
    grand = np.concatenate(groups).mean()
    ssw = sum(((g - g.mean()) ** 2).sum() for g in groups)
    ssb = sum(len(g) * (g.mean() - grand) ** 2 for g in groups)
    vw = ssw / (N - k) if N > k else 0.0
    n0 = (N - (n ** 2).sum() / N) / (k - 1) if k > 1 else 1.0
    vt = max((ssb / (k - 1) - vw) / n0, 0.0) if k > 1 else 0.0
    return vt, vw, grand

def needed(vt, vw, m, se):
    return int(np.ceil((vt + vw / m) / se ** 2))

def main():
    rows = list(csv.DictReader(open(sys.argv[1])))
    m = int(sys.argv[2]) if len(sys.argv) > 2 else 6
    se = (float(sys.argv[3]) if len(sys.argv) > 3 else 4.0) / 100
    arms = sorted({r["arm"] for r in rows})
    print("Accuracy (percent correct; n = runs)")
    cats = ["network", "what-if", "constrained", "lookup"]
    print(f"{'arm':4}" + "".join(f"{c:>16}" for c in cats) + f"{'non-lookup':>16}{'no ANSWER':>11}{'step limit':>12}")
    for a in arms:
        ra = [r for r in rows if r["arm"] == a]; line = f"{a:4}"
        for c in cats + ["non-lookup"]:
            rc = [r for r in ra if (r["category"] in NONLOOKUP if c == "non-lookup" else r["category"] == c)]
            line += f"{(100 * np.mean([int(r['correct']) for r in rc]) if rc else float('nan')):10.0f} ({len(rc):2d})"
        line += f"{sum(1 - int(r['parsed']) for r in ra):11d}{100 * np.mean([int(r['hit_step_limit']) for r in ra]):11.0f}%"
        print(line)
    print("\nStated definition versus not, constrained questions (percent correct)")
    for a in arms:
        rc = [r for r in rows if r["arm"] == a and r["category"] == "constrained"]
        s = [int(r["correct"]) for r in rc if r["stated_definition"] in ("True", "true", "1")]
        u = [int(r["correct"]) for r in rc if r["stated_definition"] not in ("True", "true", "1")]
        print(f"  {a}: stated {100*np.mean(s) if s else float('nan'):.0f} ({len(s)}), not stated {100*np.mean(u) if u else float('nan'):.0f} ({len(u)})")
    score = {}
    for r in rows:
        score.setdefault((r["arm"], r["qid"]), []).append(int(r["correct"]))
    score = {k: float(np.mean(v)) for k, v in score.items()}
    meta = {r["qid"]: r for r in rows}
    rng = np.random.default_rng(1)
    for name, hi, lo in COMPARISONS:
        byt = {}
        for qid, r in meta.items():
            if r["category"] in NONLOOKUP and (hi, qid) in score and (lo, qid) in score:
                byt.setdefault(r["template"], []).append(score[(hi, qid)] - score[(lo, qid)])
        if len(byt) < 2:
            print(f"\n{name}: too few templates"); continue
        groups = [byt[t] for t in sorted(byt)]
        vt, vw, mean = components(groups)
        boot = []
        for _ in range(2000):
            ix = rng.integers(0, len(groups), len(groups))
            b = components([groups[i] for i in ix]); boot.append(needed(b[0], b[1], m, se))
        q = np.percentile(boot, [10, 50, 90]).astype(int)
        nq = sum(len(g) for g in groups)
        print(f"\n{name} ({hi} minus {lo}), non-lookup: mean difference {100*mean:+.0f} points on {nq} questions, {len(groups)} templates")
        print(f"  standard deviation between templates {100*np.sqrt(vt):.0f} points, within templates {100*np.sqrt(vw):.0f} points")
        print(f"  templates needed for a standard error of {100*se:.0f} points with {m} questions each: {needed(vt, vw, m, se)}"
              f" (bootstrap 10th, 50th, 90th percentile: {q[0]}, {q[1]}, {q[2]})")
        print(f"  standard error with 30 templates and {m} questions each: {100*np.sqrt(vt/30 + vw/(30*m)):.1f} points")
        print("  template means (points): " + ", ".join(f"{t} {100*np.mean(byt[t]):+.0f}" for t in sorted(byt)))

if __name__ == "__main__":
    main()
