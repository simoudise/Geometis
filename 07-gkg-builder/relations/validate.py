"""Validation of the GKG full build (Step 3): counts, invariants and spot checks.

python -m relations.validate OUT.json      (on the Mac mini, after relations.build)

Reads only gkg.* tables built from public data. Writes aggregate counts and a few public-data examples
(Overture names, DataSF neighborhood names) to OUT.json, which stays on the Mac mini share and goes to
Drive, never to the repository.
"""
import json, sys, time

import psycopg

from relations.build import DSN

conn = psycopg.connect(DSN, autocommit=True)
Q = lambda sql, a=None: conn.execute(sql, a).fetchall() if a else conn.execute(sql).fetchall()
out = {"checked": time.strftime("%Y-%m-%d %H:%M:%S")}

out["entities_by_class"] = [dict(geofence=g, uko_class=c, n=n) for g, c, n in Q(
    "select geofence_id, uko_class, count(*) from gkg.entity group by 1,2 order by 1,2")]
out["extra_types"] = [dict(uko_class=c, rule=r, n=n) for c, r, n in Q(
    "select uko_class, rule, count(*) from gkg.entity_type group by 1,2 order by 1")]

out["relations"] = [dict(rid=r, curie=c, crash_derived=cd, symmetric=s, geofence=g, edges=n, subjects=ns, objects=no,
                         provenance_rows=np_) for r, c, cd, s, g, n, ns, no, np_ in Q("""
    select t.rid, t.curie, t.crash_derived, t.is_symmetric, e.geofence_id, count(*), count(distinct x.subj), count(distinct x.obj),
           count(distinct x.pid)
    from gkg.edge x join gkg.relation_type t using (rid) join gkg.entity e on e.eid=x.subj
    group by 1,2,3,4,5 order by 1,5""")]
out["relations_without_edges"] = [c for (c,) in Q(
    "select curie from gkg.relation_type t where not exists (select 1 from gkg.edge x where x.rid=t.rid) "
    "and curie<>'uko:hasDistanceMeasurement' order by rid")]
out["rejected"] = [dict(curie=c, reason=w, n=n, example_subject_class=a, example_object_class=b) for c, w, n, a, b in Q(
    "select t.curie, r.reason, r.n, r.example_subj_class, r.example_obj_class from gkg.edge_rejected r join gkg.relation_type t using (rid) order by r.n desc")]
out["provenance"] = [dict(pid=p, curie=c, source=s, method=m, code_version=v, ontology_version=o, crash_derived=cd)
                     for p, c, s, m, v, o, cd in Q("""select p.pid, t.curie, p.source, p.method, p.code_version, p.ontology_version,
                     p.crash_derived from gkg.provenance p join gkg.relation_type t using (rid) order by p.pid""")]

# Invariants (each count should be zero).
inv = {}
inv["edges_without_provenance"] = Q("select count(*) from gkg.edge x where not exists (select 1 from gkg.provenance p where p.pid=x.pid)")[0][0]
inv["provenance_relation_mismatch"] = Q("select count(*) from gkg.edge x join gkg.provenance p using (pid) where p.rid<>x.rid")[0][0]
inv["edges_to_missing_entities"] = Q("""select count(*) from gkg.edge x where not exists (select 1 from gkg.entity e where e.eid=x.subj)
                                        or not exists (select 1 from gkg.entity e where e.eid=x.obj)""")[0][0]
inv["symmetric_not_ordered"] = Q("select count(*) from gkg.edge x join gkg.relation_type t using (rid) where t.is_symmetric and x.subj>=x.obj")[0][0]
inv["self_loops"] = Q("select count(*) from gkg.edge where subj=obj")[0][0]
inv["cross_geofence_edges"] = Q("""select count(*) from gkg.edge x join gkg.entity a on a.eid=x.subj join gkg.entity b on b.eid=x.obj
                                   where a.geofence_id<>b.geofence_id""")[0][0]
inv["duplicate_edges"] = Q("select coalesce(sum(n-1),0) from (select count(*) n from gkg.edge group by rid, subj, obj having count(*)>1) d")[0][0]
inv["crash_flag_mismatch"] = Q("""select count(*) from gkg.provenance p join gkg.relation_type t using (rid) where p.crash_derived<>t.crash_derived""")[0][0]
inv["near_over_200m"] = Q("select count(*) from gkg.edge x join gkg.relation_type t using (rid) where t.curie='uko:near' and x.value_m>200")[0][0]
inv["dm_walk_shorter_than_straight"] = Q("select count(*) from gkg.distance_measurement where walk_m < 0.98*straight_m")[0][0]
inv["dm_over_2km"] = Q("select count(*) from gkg.distance_measurement where straight_m > 2000")[0][0]
# Domain and range re-check on a sample of every relation after enforcement.
inv["domain_range_violations_in_sample"] = Q("""
    with s as (select x.* from gkg.edge x tablesample system (1) repeatable (7))
    select count(*) from s join gkg.relation_type t using (rid)
    where (cardinality(t.domain_classes)>0 and not 'owl:Thing' = any(t.domain_classes) and not exists (
             select 1 from gkg.entity e join gkg.class_closure c on c.uko_class=e.uko_class where e.eid=s.subj and c.ancestor = any(t.domain_classes)
             union all select 1 from gkg.entity_type e join gkg.class_closure c on c.uko_class=e.uko_class where e.eid=s.subj and c.ancestor = any(t.domain_classes)))
       or (cardinality(t.range_classes)>0 and not 'owl:Thing' = any(t.range_classes) and not exists (
             select 1 from gkg.entity e join gkg.class_closure c on c.uko_class=e.uko_class where e.eid=s.obj and c.ancestor = any(t.range_classes)
             union all select 1 from gkg.entity_type e join gkg.class_closure c on c.uko_class=e.uko_class where e.eid=s.obj and c.ancestor = any(t.range_classes)))""")[0][0]
inv["edges_in_domain_range_sample"] = Q("select count(*) from gkg.edge tablesample system (1) repeatable (7)")[0][0]
out["invariants"] = inv

# Geometric spot checks: re-derive a random sample of edges from the source tables.
spot = {}
spot["near_distance_recheck"] = Q("""
    with s as (select x.subj, x.obj, x.value_m from gkg.edge x join gkg.relation_type t using (rid) where t.curie='uko:near'
               order by random() limit 500),
    g as (select eid, geom from gkg_work.pts)
    select count(*), count(*) filter (where abs(ST_Distance(a.geom, b.geom) - s.value_m) > 0.5) from s join g a on a.eid=s.subj join g b on b.eid=s.obj""")[0] \
    if Q("select to_regclass('gkg_work.pts') is not null")[0][0] else "gkg_work dropped"
spot["within_tract_recheck"] = Q("""
    with s as (select x.subj, x.obj from gkg.edge x join gkg.relation_type t using (rid) join gkg.entity e on e.eid=x.subj
               where t.curie='uko:withinCensusTract' and e.src='building' order by random() limit 500)
    select count(*), count(*) filter (where not ST_Contains(ct.geom, ST_PointOnSurface(b.geom))) from s
    join gkg.entity eb on eb.eid=s.subj join gkg.building b on b.geofence_id=eb.geofence_id and b.urn=eb.urn
    join gkg.entity et on et.eid=s.obj join gkg.census_tract ct on ct.geofence_id=et.geofence_id and ct.urn=et.urn""")[0]
spot["examples"] = {}
for curie in ["uko:inNeighborhood", "uko:insideMall", "uko:partOfChain", "uko:continuesAs", "uko:feedsInto", "uko:branchesFrom",
              "uko:hasTransferTo", "uko:anchorStation", "uko:providesRecreationFor", "uko:onNorthSideOf", "uko:hasParking",
              "reo:hasCollisionCausationFactor", "uko:inHighInjuryNetwork"]:
    spot["examples"][curie] = [dict(subject_class=a, subject_name=an, object_class=b, object_name=bn, value_m=v) for a, an, b, bn, v in Q("""
        select es.uko_class, coalesce(p.name, r.name, x1.name), eo.uko_class, coalesce(p2.name, r2.name, x2.name), x.value_m
        from (select * from gkg.edge where rid=(select rid from gkg.relation_type where curie=%(c)s) order by random() limit 5) x
        join gkg.entity es on es.eid=x.subj join gkg.entity eo on eo.eid=x.obj
        left join gkg.place p on p.geofence_id=es.geofence_id and p.urn=es.urn
        left join gkg.road_segment r on r.geofence_id=es.geofence_id and r.urn=es.urn
        left join gkg.aux_entity x1 on x1.geofence_id=es.geofence_id and x1.urn=es.urn
        left join gkg.place p2 on p2.geofence_id=eo.geofence_id and p2.urn=eo.urn
        left join gkg.road_segment r2 on r2.geofence_id=eo.geofence_id and r2.urn=eo.urn
        left join gkg.aux_entity x2 on x2.geofence_id=eo.geofence_id and x2.urn=eo.urn""", {"c": curie})]
out["spot_checks"] = spot

out["distance_measurements"] = [dict(geofence=g, measured_to=m, target_class=c, rows=n, with_walk=w, median_straight_m=ms,
                                     median_walk_m=mw) for g, m, c, n, w, ms, mw in Q("""
    select e.geofence_id, d.measured_to, t.uko_class, count(*), count(d.walk_m),
           round(percentile_cont(0.5) within group (order by d.straight_m)::numeric), round(percentile_cont(0.5) within group (order by d.walk_m)::numeric)
    from gkg.distance_measurement d join gkg.entity e on e.eid=d.subj join gkg.entity t on t.eid=d.target group by 1,2,3 order by 1,2,3""")]
out["very_near"] = Q("""select count(*) from gkg.edge x join gkg.relation_type t using (rid) where t.curie='uko:near' and x.value_m<=50""")[0][0]
out["storage_gb"] = {t: float(Q(f"select round(pg_total_relation_size('gkg.{t}')/1e9,2)")[0][0]) for t in
                     ["edge", "entity", "entity_type", "aux_entity", "distance_measurement", "provenance", "relation_type"]}
json.dump(out, open(sys.argv[1], "w"), indent=1, default=str)
print(json.dumps(out["invariants"], default=str), json.dumps(out["relations_without_edges"]))
