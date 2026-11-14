"""GeoMetis v0 answer loop and SQL-only baseline.

Test 1 arms (docs/test-plan-2026-11.md, revision 2): A0 LLM only; A1 schema + SQL; A2 schema + SQL + network
tool; A3 data dictionary + SQL + network tool; A4 knowledge catalog + SQL + network tool. Every arm gets the
same answer rules and must end with one `ANSWER:` line.

Usage (Mac mini, after `source ~/.geometis-env`):
  python loop.py A4 questions.jsonl [run]
Writes runs/<arm>/<qid>_r<run>.json with the answer and every tool call (the evidence ledger).
Public data only: queries that name a trip table are refused.
"""
import json, os, re, sys, time
import anthropic, psycopg

HERE = os.path.dirname(os.path.abspath(__file__))
MODEL = os.environ.get("GEOMETIS_MODEL", "claude-sonnet-5-5")
MAX_STEPS = 14
TRIP_TABLES = re.compile(r"\b(base_trips|base_trip_links|base_trips_carry|base_trips_file_log)\b", re.I)

def db():
    # Session settings go in the connection options: a SET inside a transaction is undone by rollback.
    return psycopg.connect("dbname=geometis", autocommit=False,
        options="-c statement_timeout=180000 -c search_path=gkg,public -c default_transaction_read_only=on")

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
        conn.rollback()
        out = {"columns": cols, "rows": [[None if v is None else (v if isinstance(v,(int,float,str,bool)) else str(v)) for v in r] for r in rows[:200]]}
        if len(rows) > 200: out["note"] = "truncated at 200 rows"
        return out
    except Exception as e:
        conn.rollback()
        return {"error": f"{type(e).__name__}: {str(e)[:500]}"}

_graphs = {}
def _graph(conn, geofence_id, network):
    """Undirected graph of one network. 'road': every road segment. 'walk': the walkable network the
    walksheds use (stage3_transit.walk_graph): road segments other than motorways, pedestrian edges, and
    access points joining intersections to pedestrian nodes at length 0. Parallel edges keep the shortest."""
    import networkx as nx
    key = (geofence_id, network)
    if key in _graphs:
        return _graphs[key]
    q = ("select urn, from_node, to_node, length_m, road_classification, coalesce(subclass,''), coalesce(name,'') "
         "from gkg.road_segment where geofence_id = %(g)s")
    if network == "walk":
        q += (" and coalesce(road_classification,'') <> 'motorway'"
              " union all select urn, from_node, to_node, length_m, 'pedestrian:' || coalesce(edge_class,''), coalesce(subclass,''), ''"
              " from gkg.pedestrian_edge where geofence_id = %(g)s"
              " union all select urn, intersection_node, pedestrian_node, 0, 'access', '', ''"
              " from gkg.access_point where geofence_id = %(g)s")
    g = nx.Graph()
    with conn.cursor() as cur:
        cur.execute(q, {"g": geofence_id})
        for urn, a, b, L, cls, sub, name in cur.fetchall():
            if not (a and b) or a == b:
                continue
            w = max(float(L), 0.01)
            if g.has_edge(a, b) and g[a][b]["w"] <= w:
                continue
            g.add_edge(a, b, urn=urn, w=w, cls=cls, sub=sub, name=name)
    conn.rollback()
    _graphs[key] = g
    return g

def network_path(conn, geofence_id, from_node, to_node, network="road", avoid_classes=None, remove_segments=None):
    """Shortest path by length (both directions; one-way rules not applied), optionally without some
    road classes or without named segments (for what-if questions)."""
    import networkx as nx
    if network not in ("road", "walk"):
        return {"error": "network must be 'road' or 'walk'"}
    g = _graph(conn, geofence_id, network)
    avoid, removed = set(avoid_classes or []), set(remove_segments or [])
    if avoid or removed:
        view = nx.subgraph_view(g, filter_edge=lambda u, v: g[u][v]["cls"] not in avoid and g[u][v]["urn"] not in removed)
    else:
        view = g
    for n in (from_node, to_node):
        if n not in g:
            return {"error": f"node {n} is not on the {network} network of {geofence_id}"}
    try:
        path = nx.shortest_path(view, from_node, to_node, weight="w")
    except nx.NetworkXNoPath:
        return {"error": "no path: the two nodes are not connected on this network after the removals"}
    except Exception as e:
        return {"error": f"{type(e).__name__}: {e}"}
    segs = [view[u][v] for u, v in zip(path, path[1:])]
    out = {"length_m": round(sum(s["w"] for s in segs)), "edge_count": len(segs), "segments": [
        {"urn": s["urn"], "name": s["name"], "class": s["cls"], "subclass": s["sub"], "length_m": round(s["w"])} for s in segs[:150]]}
    if len(segs) > 150:
        out["note"] = f"segment list truncated to the first 150 of {len(segs)}"
    return out

SQL_TOOL = {"name": "sql", "description": "Run one read-only SQL query (PostgreSQL 17 + PostGIS) against the database. Returns up to 200 rows.",
            "input_schema": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]}}
PATH_TOOL = {"name": "network_path",
             "description": ("Shortest path by length between two node URNs in one graph geofence. network 'road' uses every road "
                             "segment; network 'walk' uses road segments other than motorways plus mapped pedestrian ways. "
                             "Optionally avoid road classes (e.g. ['primary']) or remove named segments by URN. "
                             "One-way rules and turn restrictions are not applied. Returns the length in meters and the segments used."),
             "input_schema": {"type": "object", "properties": {
                 "geofence_id": {"type": "string"}, "from_node": {"type": "string"}, "to_node": {"type": "string"},
                 "network": {"type": "string", "enum": ["road", "walk"]},
                 "avoid_classes": {"type": "array", "items": {"type": "string"}},
                 "remove_segments": {"type": "array", "items": {"type": "string"}}},
                 "required": ["geofence_id", "from_node", "to_node", "network"]}}

# Arms of Test 1 (docs/test-plan-2026-11.md, revision 2).
ARMS = {
    "A0": {"desc": "llm_only", "tools": []},
    "A1": {"desc": "schema", "tools": [SQL_TOOL]},
    "A2": {"desc": "schema", "tools": [SQL_TOOL, PATH_TOOL]},
    "A3": {"desc": "dictionary", "tools": [SQL_TOOL, PATH_TOOL]},
    "A4": {"desc": "catalog", "tools": [SQL_TOOL, PATH_TOOL]},
}

ANSWER_RULES = """
## How to answer
- Answer the question asked. State your method in one or two sentences.
- Name the entities and the numbers you used.
- State any limit of the data that affects the answer.
- If the data cannot answer part of the question, say so plainly.
- End with exactly one line of the form `ANSWER: <value>`, in the form the question asks for:
  a number with no units or commas, a single name, names separated by " | ", or yes or no.
  If you cannot answer, write `ANSWER: unknown`.
"""

LLM_ONLY = ("You answer questions about two areas in California: five cities in Contra Costa County (Antioch, Concord, "
            "Pittsburg, Pleasant Hill and Walnut Creek) and the City and County of San Francisco. You have no tools and "
            "no database; answer from what you know and give your best estimate.")

def plain_schema(conn):
    with conn.cursor() as cur:
        cur.execute("select table_name, string_agg(column_name||' '||data_type, ', ' order by ordinal_position) "
                    "from information_schema.columns where table_schema='gkg' group by 1 order by 1")
        rows = cur.fetchall()
    conn.rollback()
    return "\n".join(f"gkg.{t}({c})" for t, c in rows)

def system_prompt(arm, conn):
    d = ARMS[arm]["desc"]
    if d == "llm_only":
        base = LLM_ONLY
    elif d == "catalog":
        base = open(os.path.join(HERE, "catalog.md")).read()
    elif d == "dictionary":
        base = open(os.path.join(HERE, "dictionary.md")).read()
    else:
        base = ("You answer questions about cities using a PostgreSQL/PostGIS database (schema gkg). "
                "Geometries are EPSG:4326. Tables and columns:\n" + plain_schema(conn))
    return base + "\n" + ANSWER_RULES

def answer(arm, qid, question, run=1, outdir=None):
    conn = db() if ARMS[arm]["tools"] else None
    client = anthropic.Anthropic()
    tools = ARMS[arm]["tools"]
    msgs = [{"role": "user", "content": [{"type": "text", "text": question}]}]
    ledger, t0, usage = [], time.time(), {"input": 0, "cache_read": 0, "cache_write": 0, "output": 0}
    final, hit_limit = None, False
    sysp = system_prompt(arm, conn)
    for step in range(MAX_STEPS):
        last = step == MAX_STEPS - 1
        kw = {"tools": tools} if (tools and not last) else {}
        if last:
            hit_limit = True
            msgs[-1]["content"].append({"type": "text", "text": "Step limit reached: give your final answer now from what you have, say what you could not check, and end with the ANSWER line."})
        # Cost only, no change to content: a rolling cache breakpoint on the newest message, so each step
        # reads the earlier conversation from the cache instead of paying full input price again.
        send = msgs[:-1] + [{"role": msgs[-1]["role"], "content": [dict(b) for b in msgs[-1]["content"]]}]
        send[-1]["content"][-1]["cache_control"] = {"type": "ephemeral"}
        r = client.messages.create(model=MODEL, max_tokens=4000, system=[{"type": "text", "text": sysp, "cache_control": {"type": "ephemeral"}}], messages=send, **kw)
        u = r.usage
        usage["input"] += u.input_tokens; usage["output"] += u.output_tokens
        usage["cache_read"] += getattr(u, "cache_read_input_tokens", 0) or 0
        usage["cache_write"] += getattr(u, "cache_creation_input_tokens", 0) or 0
        msgs.append({"role": "assistant", "content": [b.model_dump() for b in r.content]})
        calls = [b for b in r.content if b.type == "tool_use"]
        if not calls:
            final = "\n".join(b.text for b in r.content if b.type == "text"); break
        results = []
        for c in calls:
            if c.name == "sql":
                res = run_sql(conn, c.input.get("query", ""))
            else:
                try:
                    res = network_path(conn, **c.input)
                except TypeError as e:
                    res = {"error": f"bad arguments: {e}"}
            ledger.append({"step": step, "tool": c.name, "input": c.input, "result": res})
            results.append({"type": "tool_result", "tool_use_id": c.id, "content": json.dumps(res, default=str)[:12000]})
        msgs.append({"role": "user", "content": results})
    if conn is not None:
        conn.close()
    m = re.findall(r"^\s*ANSWER:\s*(.+?)\s*$", final or "", re.M)
    out = {"qid": qid, "arm": arm, "run": run, "model": MODEL, "question": question, "answer": final,
           "answer_line": m[-1] if m else None, "tool_calls": len(ledger), "hit_step_limit": hit_limit,
           "seconds": round(time.time() - t0, 1), "usage": usage, "ledger": ledger}
    d = outdir or os.path.join(HERE, "runs", arm); os.makedirs(d, exist_ok=True)
    json.dump(out, open(os.path.join(d, f"{qid}_r{run}.json"), "w"), indent=1, default=str)
    return out

if __name__ == "__main__":
    # python loop.py ARM questions.jsonl [run]   (one JSON object per line: {"qid": ..., "question": ...})
    arm, qfile = sys.argv[1], sys.argv[2]
    run = int(sys.argv[3]) if len(sys.argv) > 3 else 1
    for line in open(qfile):
        q = json.loads(line)
        try:
            o = answer(arm, q["qid"], q["question"], run)
            print(f"== {arm} {q['qid']} r{run}: {o['tool_calls']} calls, {o['seconds']} s, ANSWER={o['answer_line']}")
        except Exception as e:
            print(f"== {arm} {q['qid']} FAILED: {type(e).__name__}: {e}")
