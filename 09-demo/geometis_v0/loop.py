"""GeoMetis v0 answer loop and SQL-only baseline.

Usage (Mac mini, after `source ~/.geometis-env`):
  python loop.py geometis q01 [q02 ...]   # knowledge catalog + SQL + network tool
  python loop.py baseline q01 [...]       # plain schema listing + SQL only
Writes runs/<mode>/<qid>.json with the answer and every tool call (the evidence ledger).
Public data only: queries that name a trip table are refused.
"""
import json, os, re, sys, time
import anthropic, psycopg

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("GEOMETIS_MODEL", "claude-sonnet-5-5")
MAX_STEPS = 14
TRIP_TABLES = re.compile(r"\b(base_trips|base_trip_links|base_trips_carry|base_trips_file_log)\b", re.I)
QUESTIONS = json.load(open(os.path.join(HERE, "questions.json")))

def db():
    c = psycopg.connect("dbname=geometis", autocommit=False)
    with c.cursor() as cur:
        cur.execute("set search_path = gkg, public; set statement_timeout = '180s'; set transaction read only")
    return c

def run_sql(conn, query):
    q = query.strip().rstrip(";")
    if TRIP_TABLES.search(q):
        return {"error": "refused: trip tables are not available in this run"}
    if not re.match(r"(?is)^\s*(with|select)\b", q):
        return {"error": "refused: read-only SELECT or WITH queries only"}
    try:
        with conn.cursor() as cur:
            cur.execute(q)
            cols = [d.name for d in cur.description]
            rows = cur.fetchmany(201)
        conn.rollback(); conn.cursor().execute("set transaction read only")
        out = {"columns": cols, "rows": [[None if v is None else (v if isinstance(v,(int,float,str,bool)) else str(v)) for v in r] for r in rows[:200]]}
        if len(rows) > 200: out["note"] = "truncated at 200 rows"
        return out
    except Exception as e:
        conn.rollback(); conn.cursor().execute("set transaction read only")
        return {"error": f"{type(e).__name__}: {str(e)[:500]}"}

_graphs = {}
def shortest_path(conn, geofence_id, from_node, to_node, avoid_classes=None):
    """Shortest path by length over road segments (both directions; one-way rules not applied)."""
    import networkx as nx
    key = geofence_id
    if key not in _graphs:
        g = nx.Graph()
        with conn.cursor() as cur:
            cur.execute("select urn, from_node, to_node, length_m, road_classification, coalesce(subclass,''), coalesce(name,'') "
                        "from gkg.road_segment where geofence_id = %s", (geofence_id,))
            for urn, a, b, L, cls, sub, name in cur.fetchall():
                if a and b:
                    g.add_edge(a, b, urn=urn, w=L, cls=cls, sub=sub, name=name)
        conn.rollback(); conn.cursor().execute("set transaction read only")
        _graphs[key] = g
    g = _graphs[key]
    avoid = set(avoid_classes or [])
    view = nx.subgraph_view(g, filter_edge=lambda u, v: g[u][v]["cls"] not in avoid) if avoid else g
    try:
        path = nx.shortest_path(view, from_node, to_node, weight="w")
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    segs = [view[u][v] for u, v in zip(path, path[1:])]
    return {"length_m": round(sum(s["w"] for s in segs)), "segments": [
        {"urn": s["urn"], "name": s["name"], "class": s["cls"], "subclass": s["sub"], "length_m": round(s["w"])} for s in segs]}

SQL_TOOL = {"name": "sql", "description": "Run one read-only SQL query (PostgreSQL 17 + PostGIS) against the database. Returns up to 200 rows.",
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}
PATH_TOOL = {"name": "shortest_path", "description": "Shortest road-network path by length between two intersection node URNs in one graph geofence. Optionally avoid road classes (e.g. ['residential']). One-way rules and truck restrictions are not applied.",
             "input_schema": {"type": "object", "properties": {"geofence_id": {"type": "string"}, "from_node": {"type": "string"},
                 "to_node": {"type": "string"}, "avoid_classes": {"type": "array", "items": {"type": "string"}}},
                 "required": ["geofence_id", "from_node", "to_node"]}}

def plain_schema(conn):
    with conn.cursor() as cur:
        cur.execute("select table_name, string_agg(column_name||' '||data_type, ', ' order by ordinal_position) "
                    "from information_schema.columns where table_schema='gkg' group by 1 order by 1")
        rows = cur.fetchall()
    conn.rollback(); conn.cursor().execute("set transaction read only")
    return "\n".join(f"gkg.{t}({c})" for t, c in rows)

def system_prompt(mode, conn):
    if mode == "geometis":
        return open(os.path.join(HERE, "catalog.md")).read()
    return ("You answer questions about cities using a PostgreSQL/PostGIS database (schema gkg). "
            "Geometries are EPSG:4326. Tables and columns:\n" + plain_schema(conn) +
            "\nAnswer the question and show the numbers you used.")

def answer(mode, qid):
    q = QUESTIONS[qid]
    conn = db()
    client = anthropic.Anthropic()
    tools = [SQL_TOOL, PATH_TOOL] if mode == "geometis" else [SQL_TOOL]
    msgs = [{"role": "user", "content": q}]
    ledger, t0, usage = [], time.time(), {"input": 0, "output": 0}
    final = None
    sysp = system_prompt(mode, conn)
    for step in range(MAX_STEPS):
        last = step == MAX_STEPS - 1
        kw = {} if last else {"tools": tools}
        if last:
            msgs[-1]["content"].append({"type": "text", "text": "Step limit reached: give your final answer now from what you have, and say what you could not check."})
        r = client.messages.create(model=MODEL, max_tokens=4000, system=[{"type": "text", "text": sysp, "cache_control": {"type": "ephemeral"}}], messages=msgs, **kw)
        usage["input"] += r.usage.input_tokens + (getattr(r.usage, "cache_read_input_tokens", 0) or 0); usage["output"] += r.usage.output_tokens
        msgs.append({"role": "assistant", "content": [b.model_dump() for b in r.content]})
        calls = [b for b in r.content if b.type == "tool_use"]
        if not calls:
            final = "\n".join(b.text for b in r.content if b.type == "text"); break
        results = []
        for c in calls:
            res = run_sql(conn, c.input["query"]) if c.name == "sql" else shortest_path(conn, **c.input)
            ledger.append({"step": step, "tool": c.name, "input": c.input, "result": res})
            results.append({"type": "tool_result", "tool_use_id": c.id, "content": json.dumps(res)[:12000]})
        msgs.append({"role": "user", "content": results})
    out = {"qid": qid, "mode": mode, "model": MODEL, "question": q, "answer": final, "steps": len(ledger),
           "seconds": round(time.time() - t0, 1), "usage": usage, "ledger": ledger}
    d = os.path.join(HERE, "runs", mode); os.makedirs(d, exist_ok=True)
    json.dump(out, open(os.path.join(d, f"{qid}.json"), "w"), indent=1, default=str)
    print(f"== {mode} {qid}: {len(ledger)} tool calls, {out['seconds']} s, tokens {usage}")
    print(final or "(no final answer)")

if __name__ == "__main__":
    mode, qids = sys.argv[1], sys.argv[2:] or [k for k in QUESTIONS]
    for qid in qids:
        try: answer(mode, qid)
        except Exception as e: print(f"== {mode} {qid} FAILED: {type(e).__name__}: {e}")
