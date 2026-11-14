"""Primary (automatic) score for Test 1.

python score.py POOL.jsonl RUNSDIR > scores.csv
Parses each run's ANSWER line and compares it with the reference within the tolerance of its kind
(docs/test-plan-2026-11.md): meters and number within 5 percent (absolute 0.5 when the reference is 0);
buffer_count within max(5 percent, 1); count exact; name exact ignoring case, punctuation and spacing;
names F1 >= 0.8; yesno exact. A run with no parsable ANSWER line scores 0.
"""
import csv, json, os, re, sys

def num(s):
    if s is None: return None
    m = re.search(r"-?\d[\d,]*\.?\d*", s.replace(" ", ""))
    if not m: return None
    try: return float(m.group(0).replace(",", ""))
    except ValueError: return None

def norm(s): return re.sub(r"[^a-z0-9]", "", (s or "").lower())

def correct(kind, ref, ans):
    if ans is None or norm(ans) in ("", "unknown"): return 0
    if kind in ("meters", "number"):
        v = num(ans); r = float(ref)
        return int(v is not None and (abs(v - r) <= 0.05 * abs(r) if r else abs(v) <= 0.5))
    if kind == "buffer_count":
        v = num(ans); r = float(ref)
        return int(v is not None and abs(v - r) <= max(0.05 * abs(r), 1))
    if kind == "count":
        v = num(ans); return int(v is not None and v == float(ref))
    if kind == "name":
        return int(norm(ans) == norm(str(ref)))
    if kind == "yesno":
        a = norm(ans); return int(a.startswith(norm(str(ref))))
    if kind == "names":
        A = {norm(x) for x in ans.split("|") if norm(x)}; Rf = {norm(x) for x in ref}
        if not A or not Rf: return 0
        tp = len(A & Rf); p, r = tp / len(A), tp / len(Rf)
        return int(p + r > 0 and 2 * p * r / (p + r) >= 0.8)
    raise ValueError(kind)

def main():
    pool = {p["qid"]: p for p in (json.loads(l) for l in open(sys.argv[1]))}
    w = csv.writer(sys.stdout)
    w.writerow(["arm", "qid", "run", "template", "category", "author", "stated_definition", "geofence", "kind",
                "correct", "parsed", "hit_step_limit", "tool_calls"])
    for arm in sorted(os.listdir(sys.argv[2])):
        d = os.path.join(sys.argv[2], arm)
        if not os.path.isdir(d): continue
        for f in sorted(os.listdir(d)):
            o = json.load(open(os.path.join(d, f))); p = pool.get(o["qid"])
            if not p: continue
            w.writerow([arm, o["qid"], o["run"], p["template"], p["category"], p["author"], p["stated_definition"],
                        p["geofence"], p["kind"], correct(p["kind"], p["answer"], o["answer_line"]),
                        int(o["answer_line"] is not None), int(o.get("hit_step_limit", False)), o["tool_calls"]])

if __name__ == "__main__":
    main()
