"""Shared feature builders for the Waymo demonstration questions (public data only)."""
import geopandas as gpd, pandas as pd, numpy as np
from sqlalchemy import create_engine

ENG = create_engine("postgresql+psycopg:///geometis")
STREET_CLASSES = ("trunk", "primary", "secondary", "tertiary", "residential", "unclassified", "living_street")
GROUPS = {
    "food_drink": ["Restaurant", "FastFoodRestaurant", "Bar", "Cafe", "CoffeeShop", "Bakery", "FoodEstablishment"],
    "retail": ["RetailEstablishment", "SpecialtyStore", "ClothingStore", "ElectronicsStore", "FurnitureStore",
               "GroceryStore", "ConvenienceStore"],
    "services": ["ServiceEstablishment", "HairSalon", "Spa", "Bank", "AutoRepair"],
    "health": ["Clinic", "HealthcareFacility", "Hospital", "DentalClinic"],
    "education": ["School", "ElementarySchool", "Preschool", "EducationalFacility"],
    "office": ["OfficeBuilding", "GovernmentBuilding"],
    "leisure": ["EntertainmentVenue", "Park", "SportsFacility", "Museum", "ArtGallery", "Hotel"],
}
SHORT_TRIP = GROUPS["food_drink"] + GROUPS["retail"] + GROUPS["leisure"] + ["Clinic", "Hospital"]

def _g(df):
    return df.rename_geometry("geometry")

def core(name):
    return _g(gpd.read_postgis("select name, core as geom from gkg.geofence where name = %(n)s", ENG,
                            params={"n": name}, geom_col="geom")).to_crs(3310)

def streets(gid):
    q = f"""select urn, name, road_classification, length_m, speed_limit_mph, speed_limit_source,
                   max_abs_grade, grade, from_node, to_node, geom
            from gkg.road_segment where geofence_id = %(g)s and road_classification in {STREET_CLASSES}
              and coalesce(subclass,'') <> 'link'"""
    return _g(gpd.read_postgis(q, ENG, params={"g": gid}, geom_col="geom")).to_crs(3310)

def nodes(gid):
    return _g(gpd.read_postgis("select urn, degree, node_kind, geom from gkg.intersection_node where geofence_id = %(g)s",
                            ENG, params={"g": gid}, geom_col="geom")).to_crs(3310)

def places(gid):
    return _g(gpd.read_postgis("""select urn, name, uko_class, geom from gkg.place where geofence_id = %(g)s
                               and coalesce(operating_status,'') <> 'permanently_closed'""",
                            ENG, params={"g": gid}, geom_col="geom")).to_crs(3310)

def stops(gid):
    return _g(gpd.read_postgis("""select urn, name, uko_class, departures_on_service_day as dep, geom from gkg.transit_stop
                               where geofence_id = %(g)s and location_type = 0""",
                            ENG, params={"g": gid}, geom_col="geom")).to_crs(3310)

def tracts(gid):
    return _g(gpd.read_postgis("""select geoid, population, households, zero_vehicle_share, median_household_income,
                               share_in_core, geom from gkg.census_tract where geofence_id = %(g)s""",
                            ENG, params={"g": gid}, geom_col="geom")).to_crs(3310)

def street_node_degree(st):
    """Degree counted on the street network only (service roads and driveways excluded)."""
    ends = pd.concat([st["from_node"], st["to_node"]])
    return ends.value_counts()

def complex_intersections(st, radius=30.0):
    """Intersection clusters (street-network nodes with 3+ legs merged within `radius` m) where 3 or more
    distinct named streets meet. Merging removes the split nodes that divided roadways create."""
    import shapely
    ends = pd.concat([st[["from_node", "name"]].rename(columns={"from_node": "node"}),
                      st[["to_node", "name"]].rename(columns={"to_node": "node"})])
    legs = ends.groupby("node").size()
    names = ends.dropna().groupby("node")["name"].apply(set)
    pts = {}
    for _, r in st.iterrows():
        cs = list(r.geometry.coords)
        pts.setdefault(r.from_node, cs[0]); pts.setdefault(r.to_node, cs[-1])
    nodes3 = [n for n, k in legs.items() if k >= 3 and n in pts]
    g = gpd.GeoDataFrame({"node": nodes3}, geometry=gpd.points_from_xy([pts[n][0] for n in nodes3],
                          [pts[n][1] for n in nodes3]), crs=st.crs)
    blobs = gpd.GeoDataFrame(geometry=list(g.buffer(radius / 2).union_all().geoms) if len(g) else [], crs=st.crs)
    blobs["cluster"] = range(len(blobs))
    j = gpd.sjoin(g, blobs, predicate="within")
    j["names"] = j.node.map(names)
    agg = j.groupby("cluster").agg(nodes=("node", "size"),
            street_names=("names", lambda s: len(set().union(*[x for x in s if isinstance(x, set)]))))
    blobs = blobs.join(agg, on="cluster")
    blobs["geometry"] = blobs.geometry.centroid
    return blobs[blobs.street_names >= 3]

def land_mask(st, buffer_m=150.0):
    """Land proxy: the street network buffered by 150 m (removes open water and offshore islands)."""
    return st.buffer(buffer_m).union_all()
