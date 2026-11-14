"""Reference answers for the GeoMetis demonstration questions (public data only).

Runs on the Mac mini through the job runner. Reads the gkg schema, writes one CSV per
question and a summary to $OUT (default ~/Geometis-mini/work/demo/reference). It reads
no trip table. Outputs are not committed to the repository.
"""
import csv, os, sys, time
import psycopg

OUT = os.environ.get("OUT", os.path.expanduser("~/Geometis-mini/work/demo/reference"))
os.makedirs(OUT, exist_ok=True)
CC, SF = "us-ca-contra-costa-5", "us-ca-san-francisco"
CITY = "(select core from gkg.geofence where name = %(city)s)"
STREET = ("r.road_classification not in ('service','track','unknown','motorway','trunk') "
          "and coalesce(r.subclass,'') <> 'link'")

Q = {}

Q["q01"] = ("Concord: 10 intersections with most KSI crashes 2021-2025", {"city": "Concord"}, f"""
with top as (
  select s.urn, s.ksi, s.crashes, s.pedestrian, n.degree, n.geom, n.geofence_id
  from gkg.segment_crash_stats s
  join gkg.intersection_node n on n.urn = s.urn and n.geofence_id = s.geofence_id
  where s.entity = 'intersection' and s.year_from = 2021 and s.year_to = 2025
    and ST_Within(n.geom, {CITY})
  order by s.ksi desc, s.crashes desc limit 10)
select t.urn, t.ksi, t.crashes, t.pedestrian, t.degree as legs,
       string_agg(distinct r.name, ' / ') as streets,
       string_agg(distinct r.road_classification, '/') as classes,
       max(r.speed_limit_mph) as max_speed_mph,
       round(ST_Y(t.geom)::numeric,5) as lat, round(ST_X(t.geom)::numeric,5) as lon
from top t
left join gkg.road_segment r on r.geofence_id = t.geofence_id and (r.from_node = t.urn or r.to_node = t.urn)
group by t.urn, t.ksi, t.crashes, t.pedestrian, t.degree, t.geom
order by t.ksi desc, t.crashes desc""")

CITIES = ["Antioch", "Concord", "Pittsburg", "Pleasant Hill", "Walnut Creek", "San Francisco city"]

Q["q03"] = ("Pedestrian crashes 2021-2025 per km of street, by city", {}, f"""
with c as (select name, core from gkg.geofence
           where name in ('Antioch','Concord','Pittsburg','Pleasant Hill','Walnut Creek','San Francisco city')),
km as (select c.name, sum(r.length_m)/1000.0 as street_km
       from c join gkg.road_segment r on ST_Within(ST_Centroid(r.geom), c.core)
       where {STREET} group by c.name),
ped as (select c.name, count(*) filter (where t.pedestrian) as ped_crashes,
               count(*) filter (where t.pedestrian and t.severity in (1,2)) as ped_ksi
        from c join gkg.tims_crash t on ST_Within(t.geom, c.core)
        where t.accident_year between 2021 and 2025 group by c.name)
select km.name, round(km.street_km::numeric,1) as street_km, ped.ped_crashes, ped.ped_ksi,
       round((ped.ped_crashes/km.street_km)::numeric,3) as ped_crashes_per_km
from km join ped using (name) order by ped_crashes_per_km desc""")

Q["q03b"] = ("Street-pattern measures from Stage 6 build records", {}, """
select geofence_id, finished, stats::text from gkg.build where stage ilike '%%6%%' order by build_id desc limit 4""")

Q["q04"] = ("Pedestrian crashes by speed-limit class, 2015-2019 vs 2021-2025, by city", {}, """
with c as (select name, core from gkg.geofence
           where name in ('Antioch','Concord','Pittsburg','Pleasant Hill','Walnut Creek','San Francisco city')),
x as (select c.name, t.accident_year, r.speed_limit_mph
      from c join gkg.tims_crash t on ST_Within(t.geom, c.core)
      join gkg.crash_attachment a on a.case_id = t.case_id
      left join gkg.road_segment r on r.urn = a.segment_urn and r.geofence_id = a.geofence_id
      where t.pedestrian)
select name,
  case when speed_limit_mph is null then 'unknown' when speed_limit_mph <= 25 then '25 or less'
       when speed_limit_mph <= 35 then '30-35' when speed_limit_mph <= 45 then '40-45' else '50+' end as speed_class,
  count(*) filter (where accident_year between 2015 and 2019) as y2015_2019,
  count(*) filter (where accident_year between 2021 and 2025) as y2021_2025
from x group by 1,2 order by 1,2""")

Q["q06"] = ("Contra Costa tracts with highest zero-vehicle share: places in bus-stop walksheds", {}, f"""
with tr as (select urn, geoid, zero_vehicle_share, households, geom from gkg.census_tract
            where geofence_id = '{CC}' and share_in_core >= 0.5 and households > 200
            order by zero_vehicle_share desc limit 10),
ws as (select tr.geoid, ST_Union(w.geom) as g, count(distinct s.urn) as stops
       from tr join gkg.transit_stop s on s.geofence_id = '{CC}' and s.uko_class = 'BusStop' and ST_Within(s.geom, tr.geom)
       join gkg.walkshed_area w on w.origin_urn = s.urn and w.geofence_id = s.geofence_id
       group by tr.geoid)
select tr.geoid, round(tr.zero_vehicle_share::numeric,3) as zero_vehicle_share, round(tr.households) as households,
       coalesce(ws.stops,0) as bus_stops,
       count(distinct p.urn) filter (where p.uko_class = 'GroceryStore') as groceries,
       count(distinct p.urn) filter (where p.uko_class in ('Clinic','HealthcareFacility','Hospital')) as clinics,
       count(distinct p.urn) filter (where p.uko_class in ('School','ElementarySchool','Preschool')) as schools,
       string_agg(distinct p.name, '; ') filter (where p.uko_class = 'GroceryStore') as grocery_names
from tr left join ws on ws.geoid = tr.geoid
left join gkg.place p on p.geofence_id = '{CC}' and ws.g is not null and ST_Within(p.geom, ws.g)
group by tr.geoid, tr.zero_vehicle_share, tr.households, ws.stops order by tr.zero_vehicle_share desc""")

Q["q08"] = ("BART stations within 1 km of the five cities: share of walkshed street length posted above 35 mph", {}, f"""
with st as (select s.urn, s.name, s.geofence_id, s.in_core from gkg.transit_stop s
            join gkg.transit_agency ag on ag.feed_id = s.feed_id and ag.geofence_id = s.geofence_id
            where ag.name = 'Bay Area Rapid Transit' and s.location_type = 1 and s.geofence_id = '{CC}'
              and exists (select 1 from gkg.geofence g where g.name in ('Antioch','Concord','Pittsburg','Pleasant Hill','Walnut Creek')
                          and ST_DWithin(ST_Transform(g.core,3310), ST_Transform(s.geom,3310), 1000))),
w as (select st.name, st.in_core, st.geofence_id, (array_agg(w.geom order by w.area_m2 desc))[1] as g
      from st left join gkg.transit_stop c on c.geofence_id = st.geofence_id and (c.urn = st.urn or c.parent_urn = st.urn)
      left join gkg.walkshed_area w on w.origin_urn = c.urn and w.geofence_id = c.geofence_id
      group by st.name, st.in_core, st.geofence_id),
L as (select w.name, w.in_core, (w.g is not null) as has_walkshed,
        coalesce(sum(ST_Length(ST_Transform(ST_Intersection(r.geom, w.g),3310))),0) as street_m,
        coalesce(sum(ST_Length(ST_Transform(ST_Intersection(r.geom, w.g),3310))) filter (where r.speed_limit_mph > 35),0) as fast_m,
        coalesce(sum(ST_Length(ST_Transform(ST_Intersection(r.geom, w.g),3310))) filter (where r.speed_limit_source = 'posted'),0) as posted_m
      from w left join gkg.road_segment r on r.geofence_id = w.geofence_id and w.g is not null and ST_Intersects(r.geom, w.g) and {STREET}
      group by w.name, w.in_core, w.g)
select name, in_core, has_walkshed, round(street_m::numeric) as street_m,
       round((fast_m/nullif(street_m,0))::numeric,3) as share_above_35,
       round((posted_m/nullif(street_m,0))::numeric,3) as share_posted
from L order by share_above_35 desc nulls last""")

Q["q10"] = ("Bus stops with no sidewalk or crosswalk edge within 100 m, by city", {}, """
with c as (select name, core from gkg.geofence
           where name in ('Antioch','Concord','Pittsburg','Pleasant Hill','Walnut Creek','San Francisco city')),
s as (select c.name, st.urn, st.geofence_id, st.geom from c join gkg.transit_stop st
      on st.uko_class = 'BusStop' and ST_Within(st.geom, c.core))
select s.name, count(*) as bus_stops,
  count(*) filter (where not exists (
    select 1 from gkg.pedestrian_edge e where e.geofence_id = s.geofence_id
      and e.subclass in ('sidewalk','crosswalk')
      and ST_DWithin(ST_Transform(e.geom,3310), ST_Transform(s.geom,3310), 100))) as without_sidewalk_or_crosswalk
from s group by s.name order by s.name""")

Q["q20"] = ("Street segments missing a speed limit or a nearby sidewalk edge, by road class", {}, f"""
with r as (select r.* from gkg.road_segment r where r.in_core and {STREET})
select geofence_id, road_classification, count(*) as segments,
  round(avg((speed_limit_source = 'none')::int)::numeric,3) as share_no_speed,
  round(avg((speed_limit_source = 'posted')::int)::numeric,3) as share_posted_speed,
  round(avg((exists (select 1 from gkg.pedestrian_edge e where e.geofence_id = r.geofence_id and e.subclass = 'sidewalk'
          and ST_DWithin(ST_Transform(e.geom,3310), ST_Transform(r.geom,3310), 20)))::int)::numeric,3) as share_sidewalk_within_20m
from r group by 1,2 order by 1,2""")

def run(conn, key, title, params, sql):
    t0 = time.time()
    with conn.cursor() as cur:
        cur.execute(sql, params)
        cols = [d.name for d in cur.description]
        rows = cur.fetchall()
    with open(os.path.join(OUT, f"{key}.csv"), "w", newline="") as f:
        w = csv.writer(f); w.writerow(cols); w.writerows(rows)
    print(f"== {key}: {title} ({len(rows)} rows, {time.time()-t0:.1f}s)")
    print(" | ".join(cols))
    for r in rows[:40]:
        print(" | ".join("" if v is None else str(v)[:120] for v in r))

if __name__ == "__main__":
    keys = sys.argv[1:] or list(Q)
    with psycopg.connect("dbname=geometis") as conn:
        for k in keys:
            title, params, sql = Q[k]
            try:
                run(conn, k, title, params, sql)
            except Exception as e:
                conn.rollback(); print(f"== {k} FAILED: {e}")
