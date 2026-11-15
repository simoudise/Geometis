"""Test 1 secondary score: blind grading by Claude Fable 5.2 through the Message Batches API.

python grade.py prepare POOL.jsonl RUNSDIR OUTDIR [SEED]   build the blind packet (no API call)
python grade.py submit OUTDIR [CAP=30]                        send the batch (spends money; refuses above CAP dollars)
python grade.py collect OUTDIR                                fetch results when the batch has ended

Scope (Evangelos, November 15): one randomly chosen run of each question for arms A1 to A4, plus one run of each
of A0's 30 questions, about 890 answers. Fuller grading is decided after these results.

Blinding (docs/test-plan-2026-11.md, Scoring; Fable defect 5): the grader sees the question, the final answer text
with every URN replaced by [ID], the reference answer, and the numbered list of data limits with the numbers that
apply to the question's template (limits.json). It never sees the arm, the tool calls, the step count or the
ledger. Items are shuffled and carry random codes; the mapping from code to arm and run stays in OUTDIR/key.json
and is not sent. Limitation: an answer's own wording can still hint at its arm (for example ontology class names
in A4 answers); the report states this.
The limit wording is the data dictionary's (plain prose, no ontology names), so the grader's text favors no arm.
"""
import json, os, random, re, sys, time

MODEL = "claude-fable-5-2"
HERE = os.path.dirname(os.path.abspath(__file__))
URN = re.compile(r"urn:urban-kg:[^\s,;)\]\"'|]+")

def limits_text():
    t = open(os.path.join(HERE, "dictionary.md")).read()
    i = t.index("## Limits of the data"); j = t.find("\n## ", i + 5)
    return t[t.index("\n", i) + 1: j if j > 0 else None].strip()

SYSTEM = """You grade answers to geospatial questions about two Bay Area areas. You do not know which system wrote
an answer. Judge each answer only on its text.

The data behind every answer has these limits:
{limits}

For the answer you receive:
1. For each limit number listed as applying to this question, decide whether the answer states that limit, or
   clearly accounts for it, in a way that bears on this question. Paraphrase counts; a generic list of every limit
   with no link to the question counts as stated only if the applicable limit is among them.
2. Judge the explanation: "correct" if the method and the reasoning would produce the right kind of answer and
   contain no material error; "partly" if the approach is reasonable but has a material error or omission;
   "incorrect" if the method is wrong or the answer rests on a misreading of the question or the data. The
   reference answer is given for context: a wrong final number with a sound method can be "partly"; a right
   number reached by an unsound method is not "correct".
3. Note any limit the answer wrongly claims applies, or any claim the data cannot support.
Reply with JSON only: {{"limits": {{"<number>": true|false, ...}}, "explanation": "correct"|"partly"|"incorrect",
"unsupported_claims": true|false, "note": "<one sentence>"}}"""

def prepare(pool_path, runsdir, outdir, seed=20261115):
    os.makedirs(outdir, exist_ok=True)
    pool = {json.loads(l)["qid"]: json.loads(l) for l in open(pool_path)}
    lim = json.load(open(os.path.join(HERE, "limits.json")))
    rng = random.Random(seed)
    items = []
    for arm in ("A0", "A1", "A2", "A3", "A4"):
        for qid in sorted(pool):
            runs = [r for r in (1, 2, 3) if os.path.exists(os.path.join(runsdir, arm, f"{qid}_r{r}.json"))]
            if not runs: continue
            r = rng.choice(runs)
            o = json.load(open(os.path.join(runsdir, arm, f"{qid}_r{r}.json")))
            items.append({"arm": arm, "qid": qid, "run": r, "template": pool[qid]["template"],
                          "question": URN.sub("[ID]", pool[qid]["question"]),
                          "answer": URN.sub("[ID]", o.get("answer") or "(no answer text)"),
                          "reference": URN.sub("[ID]", json.dumps(pool[qid]["answer"], default=str)),
                          "limits": lim.get(pool[qid]["template"], [])})
    rng.shuffle(items)
    key, reqs = {}, []
    for k, it in enumerate(items):
        code = f"g{k:04d}"
        key[code] = {f: it[f] for f in ("arm", "qid", "run", "template", "limits")}
        applies = ", ".join(str(n) for n in it["limits"]) or "none"
        user = (f"Question:\n{it['question']}\n\nAnswer to grade:\n{it['answer']}\n\nReference answer: {it['reference']}\n\n"
                f"Limits that apply to this question: {applies}.")
        reqs.append({"custom_id": code, "params": {"model": MODEL, "max_tokens": 600,
                     "system": [{"type": "text", "text": SYSTEM.format(limits=limits_text()), "cache_control": {"type": "ephemeral"}}],
                     "messages": [{"role": "user", "content": user}]}})
    json.dump(key, open(os.path.join(outdir, "key.json"), "w"))
    with open(os.path.join(outdir, "requests.jsonl"), "w") as f:
        for r in reqs: f.write(json.dumps(r) + "\n")
    print(f"{len(reqs)} items; by arm:", {a: sum(1 for v in key.values() if v["arm"] == a) for a in ("A0", "A1", "A2", "A3", "A4")})
    print(f"estimated cost at batch prices ($4 input, $20 output per million tokens): ${estimate(reqs):.2f}")

def estimate(reqs):
    chars = sum(len(r["params"]["messages"][0]["content"]) for r in reqs)
    return chars / 3.5 / 1e6 * 4 + len(reqs) * 250 / 1e6 * 20 + 3000 * 10 / 1e6 * 4   # input, output, one cache write

def submit(outdir, cap=30.0):
    import anthropic
    reqs = [json.loads(l) for l in open(os.path.join(outdir, "requests.jsonl"))]
    est = estimate(reqs)
    if est > cap: raise SystemExit(f"estimated ${est:.2f} exceeds the cap of ${cap:.2f}; not submitted")
    b = anthropic.Anthropic().messages.batches.create(requests=reqs)
    json.dump({"batch_id": b.id, "submitted": time.time(), "n": len(reqs)}, open(os.path.join(outdir, "batch.json"), "w"))
    print("submitted", b.id, len(reqs), "requests")

def collect(outdir):
    import anthropic, csv
    c = anthropic.Anthropic(); info = json.load(open(os.path.join(outdir, "batch.json")))
    b = c.messages.batches.retrieve(info["batch_id"])
    print("status", b.processing_status, dict(b.request_counts))
    if b.processing_status != "ended": return
    key = json.load(open(os.path.join(outdir, "key.json")))
    rows, usage = [], {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0}
    for res in c.messages.batches.results(info["batch_id"]):
        k = key[res.custom_id]; row = {"code": res.custom_id, **{f: k[f] for f in ("arm", "qid", "run", "template")}}
        if res.result.type != "succeeded":
            row["error"] = res.result.type; rows.append(row); continue
        m = res.result.message; u = m.usage
        usage["input"] += u.input_tokens; usage["output"] += u.output_tokens
        usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
        usage["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0
        text = "".join(b.text for b in m.content if b.type == "text")
        try:
            g = json.loads(text[text.index("{"): text.rindex("}") + 1])
            lims = {str(n): bool(g.get("limits", {}).get(str(n))) for n in k["limits"]}
            row.update({"limits_applicable": len(lims), "limits_stated": sum(lims.values()),
                        "explanation": g.get("explanation"), "unsupported_claims": g.get("unsupported_claims"),
                        "note": g.get("note", "")[:300]})
        except Exception as e:
            row["error"] = f"parse: {e}"
        rows.append(row)
    cols = ["code", "arm", "qid", "run", "template", "limits_applicable", "limits_stated", "explanation", "unsupported_claims", "note", "error"]
    with open(os.path.join(outdir, "grades.csv"), "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols); w.writeheader()
        for r in rows: w.writerow({c2: r.get(c2, "") for c2 in cols})
    usd = (usage["input"] * 4 + usage["output"] * 20 + usage["cache_read"] * 0.10 + usage["cache_write"] * 5) / 1e6
    print("results", len(rows), "errors", sum(1 for r in rows if r.get("error")), "tokens", usage,
          f"cost at batch prices about ${usd:.2f}")

if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "prepare": prepare(sys.argv[2], sys.argv[3], sys.argv[4], *(int(x) for x in sys.argv[5:6]))
    elif cmd == "submit": submit(sys.argv[2], *(float(x) for x in sys.argv[3:4]))
    elif cmd == "collect": collect(sys.argv[2])
