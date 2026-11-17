"""Test 2 add-on: do separate parameters per relation help message passing? (change log, Nov 17)

python analyze_untyped.py EVALDIR UNTYPEDDIR [B] [SEED] [WIDEDIR]
EVALDIR holds the main evaluations.jsonl and reference.jsonl (analyze_test2.py). UNTYPEDDIR holds evaluations.jsonl
for S-pub-untyped (evaluate.py with --emb .../S-pub-untyped/seedN). Written and frozen before any S-pub-untyped run.

Claim tested: separate parameters per relation help message passing. S-pub-untyped uses the same graph, inputs,
losses and procedure as S-pub, but one message function and one update and normalization layer shared by every
relation and node type. Per-type input encoders remain, so some type information still enters through the inputs;
the untyped encoder also has fewer parameters. Both limits are reported with the result.
Decision rule (approved by Evangelos, Nov 17), on S-pub embeddings alone (EMB) against S-pub-untyped alone:
- relation parameters help: the pooled gain of S-pub over S-pub-untyped reaches the minimum effect (10 percent of
  the B2-to-reference gap and more than two seed standard deviations) and the block interval excludes zero;
- they hurt (added Nov 17): S-pub-untyped beats S-pub by the minimum effect and the block interval excludes zero;
- they add nothing: the 95 percent block interval lies inside plus or minus the minimum effect;
- inconclusive: every other outcome.
"""
import json, os, sys
import numpy as np
import analyze_test2 as A

def main():
    evaldir, udir = sys.argv[1], sys.argv[2]
    B = int(sys.argv[3]) if len(sys.argv) > 3 else 9999
    rng = np.random.default_rng(int(sys.argv[4]) if len(sys.argv) > 4 else 20261118)
    mean, per_seed = A.load(evaldir)
    A.NETS.append("S-pub-untyped")
    um, ups = A.load(udir)
    mean.update(um); per_seed.update(ups)
    S, U = "S-pub EMB", "S-pub-untyped EMB"
    if any((x, f) not in mean for x in (S, U, "B2", "REF") for f in A.FOLDS):
        raise SystemExit("missing S-pub, S-pub-untyped, B2 or the reference on some fold")
    gap = A.gain(mean, "REF", "B2"); min_eff = max(0.10 * gap, 0.0)
    g = A.gain(mean, S, U); ci = A.bootstrap(mean, S, U, B, rng)
    sd, seeds = A.seed_sd(per_seed, mean, S, U)
    thresh = max(min_eff, 2 * sd)
    print(f"Minimum effect: {min_eff:.4f} (10 percent of the B2-to-reference gap {gap:.4f}); 2 seed SD {2 * sd:.4f}")
    print(f"S-pub gain over S-pub-untyped: {g:+.4f}, 95% block interval [{ci[0]:+.4f}, {ci[1]:+.4f}]")
    print("Per fold:", {f: round(float(A.gain(mean, S, U, [f])), 4) for f in A.FOLDS})
    print("Per stratum:", {s: round(float(A.gain(mean, S, U, A.FOLDS, {s})), 4) for s in A.STRATA + ["local"]})
    if g >= thresh and ci[0] > 0:
        v = "SEPARATE RELATION PARAMETERS HELP"
    elif -g >= thresh and ci[1] < 0:
        v = "SEPARATE RELATION PARAMETERS HURT"   # third outcome added by Evangelos, Nov 17
    elif ci[0] > -min_eff and ci[1] < min_eff:
        v = "SEPARATE RELATION PARAMETERS ADD NOTHING"
    else:
        v = "INCONCLUSIVE"
    print("Verdict:", v)
    print("Limits: per-type input encoders remain in S-pub-untyped, and it has fewer parameters than S-pub.")
    # Secondary, width-matched check (added Nov 17): run only when the primary verdict is "help"; it tests whether
    # model size explains the result and does not change the primary verdict.
    wdir = sys.argv[5] if len(sys.argv) > 5 else ""
    if wdir:
        A.NETS.append("S-pub-untyped-wide")
        wm, wps = A.load(wdir); mean.update(wm); per_seed.update(wps)
        W = "S-pub-untyped-wide EMB"
        if all((W, f) in mean for f in A.FOLDS):
            gw = A.gain(mean, S, W); cw = A.bootstrap(mean, S, W, B, rng)
            print(f"Secondary (width-matched): S-pub gain over S-pub-untyped-wide: {gw:+.4f} [{cw[0]:+.4f}, {cw[1]:+.4f}]")
    if all(("S-pub-untyped EMB+B2", f) in mean for f in A.FOLDS):
        print(f"Secondary: S-pub-untyped EMB+B2 gain over B2: {A.gain(mean, 'S-pub-untyped EMB+B2', 'B2'):+.4f}")

if __name__ == "__main__":
    main()
