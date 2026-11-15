"""Test 1 full-run analysis: primary scores, comparisons, intervals and the pass rules.

python analyze_full.py SCORES.csv RUNSDIR [B=9999] [SEED=20261115]
SCORES.csv comes from score.py on the full pool; RUNSDIR holds the answer files (for cost and step-limit hits).
Follows docs/test-plan-2026-11.md, Test 1:
- Each arm's score on a question is the mean of its three runs (0 to 1; reported in points, 0 to 100).
- Comparisons use paired differences per question: A-tool = A2 - A1, A-knowledge = A4 - A2, A-ontology = A4 - A3,
  on network, what-if and constrained questions combined; the lookup guardrail uses A4 - A2 on lookups.
- Intervals: wild cluster bootstrap with Rademacher weights, clustered by template and stratified by category
  (Cameron, Gelbach and Miller 2008). Each bootstrap draw keeps each category's mean difference and flips the sign
  of every template's residuals (difference minus its category mean) with probability one half; the estimate is
  the mean over questions; the 95 percent interval is the 2.5th to 97.5th percentile of the draws.
- Pass: estimate >= 15 points and lower bound > 5. Fail: estimate <= 5 and upper bound < 15. Otherwise
  inconclusive. Lookup guardrail holds when the lower bound of A4 - A2 on lookups exceeds -5 points.
The report also splits results by author group and, for constrained questions, by whether the question states
its definition. These splits are descriptive; the pass rules apply to the combined set only.
"""
import csv, glob, json, os, sys
import numpy as np

NONLOOKUP = ("network", "what-if", "constrained")
COMPARISONS = [("A-tool", "A2", "A1"), ("A-knowledge", "A4", "A2"), ("A-ontology", "A4", "A3")]

def wild_cluster(d, cat, tpl, B, rng):
    d = np.asarray(d, float); cats = np.unique(cat)
    cm = {c: d[cat == c].mean() for c in cats}
    base = np.array([cm[c] for c in cat]); resid = d - base
    tpls, inv = np.unique(tpl, return_inverse=True)
    W = rng.choice([-1.0, 1.0], size=(B, len(tpls)))
    draws = (base[None, :] + W[:, inv] * resid[None, :]).mean(1)
    return float(d.mean()), float(np.percentile(draws, 2.5)), float(np.percentile(draws, 97.5))

def verdict(est, lo, hi):
    if est >= 15 and lo > 5: return "PASS"
    if est <= 5 and hi < 15: return "FAIL"
    return "INCONCLUSIVE"

def main():
    rows = list(csv.DictReader(open(sys.argv[1])))
    runsdir = sys.argv[2]
    B = int(sys.argv[3]) if len(sys.argv) > 3 else 9999
    rng = np.random.default_rng(int(sys.argv[4]) if len(sys.argv) > 4 else 20261115)
    meta, sc = {}, {}
    for r in rows:
        meta[r["qid"]] = r
        sc.setdefault((r["arm"], r["qid"]), []).append(int(r["correct"]))
    score = {k: 100.0 * np.mean(v) for k, v in sc.items()}
    arms = sorted({a for a, _ in sc})
    nruns = {a: sum(len(v) for (aa, _), v in sc.items() if aa == a) for a in arms}

    # Cost and step-limit hits from the answer files.
    print("Runs, cost and step-limit hits by arm")
    for a in arms:
        files = glob.glob(os.path.join(runsdir, a, "*.json"))
        usd = lim = 0.0
        for f in files:
            o = json.load(open(f)); u = o["usage"]
            usd += (u["input"] * 2 + u["output"] * 10 + u["cache_read"] * 0.10 + u["cache_write"] * 2.50) / 1e6
            lim += bool(o.get("hit_step_limit") or o.get("hit_limit"))
        print(f"  {a}: {nruns[a]} scored runs, {len(files)} answer files, ${usd:.2f} (${usd/max(len(files),1):.3f} per run), "
              f"step limit {100*lim/max(len(files),1):.0f}%")

    def mean_by(arm, pred):
        v = [score[(arm, q)] for q, r in meta.items() if (arm, q) in score and pred(r)]
        return (np.mean(v) if v else float("nan")), len(v)

    print("\nPrimary score (points) by arm and category")
    cats = ["network", "what-if", "constrained", "lookup"]
    print("arm " + "".join(f"{c:>18}" for c in cats + ["non-lookup"]))
    for a in arms:
        line = f"{a:4}"
        for c in cats + ["non-lookup"]:
            m, n = mean_by(a, (lambda r, c=c: r["category"] in NONLOOKUP) if c == "non-lookup" else (lambda r, c=c: r["category"] == c))
            line += f"{m:12.1f} ({n:3d})"
        print(line)
    for author in ("claude", "evangelos"):
        print(f"\nAuthor group {author}: non-lookup score by arm: " + ", ".join(
            f"{a} {mean_by(a, lambda r: r['category'] in NONLOOKUP and r['author'] == author)[0]:.1f}" for a in arms))
    print("\nConstrained questions, definition stated versus not")
    for a in arms:
        s = mean_by(a, lambda r: r["category"] == "constrained" and r["stated_definition"] in ("True", "true", "1"))
        u = mean_by(a, lambda r: r["category"] == "constrained" and r["stated_definition"] not in ("True", "true", "1"))
        print(f"  {a}: stated {s[0]:.1f} ({s[1]}), not stated {u[0]:.1f} ({u[1]})")

    def compare(hi, lo, pred):
        qs = [q for q, r in meta.items() if pred(r) and (hi, q) in score and (lo, q) in score]
        d = np.array([score[(hi, q)] - score[(lo, q)] for q in qs])
        cat = np.array([meta[q]["category"] for q in qs]); tpl = np.array([meta[q]["template"] for q in qs])
        return (*wild_cluster(d, cat, tpl, B, rng), len(qs), len(set(tpl)))

    print(f"\nComparisons on network, what-if and constrained questions combined (wild cluster bootstrap, B = {B})")
    for name, hi, lo in COMPARISONS:
        est, l, h, n, k = compare(hi, lo, lambda r: r["category"] in NONLOOKUP)
        print(f"  {name} ({hi} - {lo}): {est:+.1f} points, 95% interval [{l:+.1f}, {h:+.1f}], {n} questions, {k} templates: {verdict(est, l, h)}")
        for author in ("claude", "evangelos"):
            e2, l2, h2, n2, k2 = compare(hi, lo, lambda r: r["category"] in NONLOOKUP and r["author"] == author)
            print(f"      {author}: {e2:+.1f} [{l2:+.1f}, {h2:+.1f}], {n2} questions, {k2} templates (descriptive)")
    est, l, h, n, k = compare("A4", "A2", lambda r: r["category"] == "lookup")
    print(f"  Lookup guardrail (A4 - A2 on lookups): {est:+.1f} [{l:+.1f}, {h:+.1f}], {n} questions: "
          f"{'HOLDS' if l > -5 else 'DOES NOT HOLD'}")

if __name__ == "__main__":
    main()
