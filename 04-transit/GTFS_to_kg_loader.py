"""
GTFS Data Loader for Urban Knowledge Graph
Imports GTFS feeds from Bay Area transit agencies into the UKO-based KG
"""

import os
import csv
import zipfile
from datetime import datetime
from typing import Dict, List, Optional
from rdflib import Graph, Literal, Namespace, URIRef
from rdflib.namespace import RDF, RDFS, XSD
import requests
from pathlib import Path

# Namespaces
UKO = Namespace("urn:urban-kg:")
UKO_ENTITY = Namespace("urn:urban-kg:entity/gtfs/")
GEO = Namespace("http://www.opengis.net/ont/geosparql#")


class GTFSLoader:
    """
    Loads GTFS data from Bay Area transit agencies and populates knowledge graph
    """
    
    # Direct GTFS feed URLs (from transitfeeds.com and agency sites)
    # These are more reliable than the 511 API
    GTFS_FEEDS = {
        'AC_Transit': 'http://gtfs.actransit.org/gtfs_latest.zip',
        'BART': 'https://www.bart.gov/dev/schedules/google_transit.zip',
        'County_Connection': 'https://cccta.org/GTFS/google_transit.zip',
        'Tri_Delta': 'http://www.trideltatransit.com/google/google_transit.zip',
        'WestCAT': 'http://www.westcat.org/sites/default/files/google_transit.zip',
    }
    
    # Alternative: 511.org API endpoints (requires API key)
    GTFS_511_FEEDS = {
        'AC_Transit': 'http://api.511.org/transit/datafeeds?operator_id=AC&api_key={API_KEY}',
        'BART': 'http://api.511.org/transit/datafeeds?operator_id=BA&api_key={API_KEY}',
        'County_Connection': 'http://api.511.org/transit/datafeeds?operator_id=CC&api_key={API_KEY}',
        'Tri_Delta': 'http://api.511.org/transit/datafeeds?operator_id=TD&api_key={API_KEY}',
    }
    
    # Route type mapping (GTFS standard)
    ROUTE_TYPE_MAPPING = {
        0: UKO.LightRailRoute,  # Tram/Light rail
        1: UKO.SubwayRoute,      # Subway/Metro
        2: UKO.RailRoute,        # Rail
        3: UKO.BusRoute,         # Bus
        4: UKO.FerryRoute,       # Ferry
        5: UKO.CableCarRoute,    # Cable tram
        6: UKO.GondolaRoute,     # Aerial lift
        7: UKO.FunicularRoute,   # Funicular
        11: UKO.BusRoute,        # Trolleybus
        12: UKO.RailRoute        # Monorail
    }
    
    def __init__(self, graph: Graph, api_key: str = None, bounding_box: List[float] = None):
        """
        Args:
            graph: RDF graph to populate
            api_key: 511.org API key (optional, for alternative feeds)
            bounding_box: [lat_min, lat_max, lon_min, lon_max] to filter stops
        """
        self.graph = graph
        self.api_key = api_key
        self.bbox = bounding_box
        
        # Statistics
        self.stats = {
            'agencies': 0,
            'routes': 0,
            'stops': 0,
            'trips': 0,
            'stop_times': 0,
            'stops_filtered': 0,
            'calendars': 0,
            'transfers': 0
        }
        
        # Use direct feeds by default
        self.feeds = self.GTFS_FEEDS
        
        # If API key provided, use 511 feeds
        if api_key:
            self.feeds = self.GTFS_511_FEEDS
    
    def load_all_agencies(self, data_dir: str = "gtfs_data", agencies: List[str] = None):
        """Download and load GTFS data from Bay Area agencies
        
        Args:
            data_dir: Directory to store downloaded feeds
            agencies: List of agency names to load (None = all)
        """
        
        os.makedirs(data_dir, exist_ok=True)
        
        agencies_to_load = agencies if agencies else list(self.feeds.keys())
        
        for agency_name in agencies_to_load:
            if agency_name not in self.feeds:
                print(f"Warning: Unknown agency '{agency_name}', skipping...")
                continue
                
            print(f"\n{'='*60}")
            print(f"Processing {agency_name}")
            print('='*60)
            
            feed_url = self.feeds[agency_name]
            
            # Download GTFS feed
            gtfs_zip = os.path.join(data_dir, f"{agency_name}.zip")
            if not os.path.exists(gtfs_zip):
                success = self._download_gtfs(feed_url, gtfs_zip)
                if not success:
                    print(f"Failed to download {agency_name}, skipping...")
                    continue
            else:
                print(f"Using cached file: {gtfs_zip}")
            
            # Verify it's a valid zip
            if not self._verify_zip(gtfs_zip):
                print(f"Invalid zip file for {agency_name}, skipping...")
                os.remove(gtfs_zip)  # Remove corrupt file
                continue
            
            # Extract and load
            extract_dir = os.path.join(data_dir, agency_name)
            self._extract_gtfs(gtfs_zip, extract_dir)
            self.load_gtfs_feed(extract_dir, agency_name)
    
    def load_gtfs_feed(self, gtfs_dir: str, agency_name: str):
        """Load a single GTFS feed into the knowledge graph"""
        
        print(f"\nLoading GTFS data from {gtfs_dir}...")
        
        # Check if required files exist
        required_files = ['agency.txt', 'routes.txt', 'stops.txt', 'trips.txt', 'stop_times.txt']
        missing_files = [f for f in required_files if not os.path.exists(os.path.join(gtfs_dir, f))]
        
        if missing_files:
            print(f"Error: Missing required files: {missing_files}")
            return
        
        # Load in order (respecting dependencies)
        try:
            agency_uri = self._load_agency(gtfs_dir, agency_name)
            routes = self._load_routes(gtfs_dir, agency_uri)
            stops = self._load_stops(gtfs_dir)
            calendars = self._load_calendars(gtfs_dir)
            trips = self._load_trips(gtfs_dir, routes, calendars)
            self._load_stop_times(gtfs_dir, trips, stops)
            
            # Optional files
            if os.path.exists(os.path.join(gtfs_dir, 'transfers.txt')):
                self._load_transfers(gtfs_dir, stops)
            
            print(f"\n✓ Successfully loaded {agency_name}:")
            print(f"  - Routes: {len(routes)}")
            print(f"  - Stops: {len(stops)}")
            print(f"  - Trips: {len(trips)}")
            print(f"  - Calendars: {len(calendars)}")
            
        except Exception as e:
            print(f"Error loading {agency_name}: {e}")
            import traceback
            traceback.print_exc()
    
    def _verify_zip(self, zip_path: str) -> bool:
        """Verify that a file is a valid zip"""
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                # Try to read the file list
                zf.namelist()
                return True
        except zipfile.BadZipFile:
            return False
        except Exception:
            return False
    
    def _download_gtfs(self, url: str, output_path: str) -> bool:
        """Download GTFS feed with proper error handling"""
        
        try:
            # Replace API key if using 511 API
            if '{API_KEY}' in url:
                if not self.api_key:
                    print(f"Error: API key required for this feed")
                    print(f"Get a free key at: https://511.org/open-data/token")
                    return False
                url = url.replace('{API_KEY}', self.api_key)
            
            print(f"Downloading from: {url[:50]}...")
            
            # Download with proper headers
            headers = {
                'User-Agent': 'Mozilla/5.0 (compatible; GTFSLoader/1.0)'
            }
            
            response = requests.get(url, headers=headers, timeout=60, stream=True)
            response.raise_for_status()
            
            # Check content type
            content_type = response.headers.get('content-type', '')
            
            # Some APIs return HTML error pages
            if 'text/html' in content_type:
                print(f"Error: Received HTML instead of ZIP file")
                print(f"URL may be incorrect or require authentication")
                return False
            
            # Save file
            with open(output_path, 'wb') as f:
                for chunk in response.iter_content(chunk_size=8192):
                    f.write(chunk)
            
            print(f"✓ Downloaded successfully ({os.path.getsize(output_path) / 1024 / 1024:.2f} MB)")
            return True
            
        except requests.exceptions.RequestException as e:
            print(f"Download error: {e}")
            return False
        except Exception as e:
            print(f"Unexpected error: {e}")
            return False
    
    def _extract_gtfs(self, zip_path: str, extract_dir: str):
        """Extract GTFS zip file"""
        os.makedirs(extract_dir, exist_ok=True)
        
        print(f"Extracting to {extract_dir}...")
        
        with zipfile.ZipFile(zip_path, 'r') as zip_ref:
            zip_ref.extractall(extract_dir)
        
        # List extracted files
        files = os.listdir(extract_dir)
        print(f"✓ Extracted {len(files)} files")
    
    def _load_agency(self, gtfs_dir: str, agency_name: str) -> URIRef:
        """Load agency.txt"""
        agency_file = os.path.join(gtfs_dir, 'agency.txt')
        
        with open(agency_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                agency_id = row.get('agency_id', agency_name)
                agency_uri = UKO_ENTITY[f"agency/{agency_id}"]
                
                self.graph.add((agency_uri, RDF.type, UKO.TransitAgency))
                self.graph.add((agency_uri, RDFS.label, Literal(row['agency_name'])))
                self.graph.add((agency_uri, UKO.gtfsAgencyId, Literal(agency_id)))
                self.graph.add((agency_uri, UKO.agencyName, Literal(row['agency_name'])))
                
                if 'agency_url' in row and row['agency_url']:
                    self.graph.add((agency_uri, UKO.agencyUrl, URIRef(row['agency_url'])))
                
                if 'agency_timezone' in row and row['agency_timezone']:
                    self.graph.add((agency_uri, UKO.agencyTimezone, Literal(row['agency_timezone'])))
                
                if 'agency_phone' in row and row['agency_phone']:
                    self.graph.add((agency_uri, UKO.agencyPhone, Literal(row['agency_phone'])))
                
                self.stats['agencies'] += 1
                return agency_uri
        
        # Fallback if no agency row
        agency_uri = UKO_ENTITY[f"agency/{agency_name}"]
        self.graph.add((agency_uri, RDF.type, UKO.TransitAgency))
        self.graph.add((agency_uri, RDFS.label, Literal(agency_name)))
        self.stats['agencies'] += 1
        return agency_uri
    
    def _load_routes(self, gtfs_dir: str, agency_uri: URIRef) -> Dict[str, URIRef]:
        """Load routes.txt"""
        routes_file = os.path.join(gtfs_dir, 'routes.txt')
        routes = {}
        
        with open(routes_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                route_id = row['route_id']
                route_uri = UKO_ENTITY[f"route/{route_id}"]
                
                # Determine route class based on type
                route_type = int(row.get('route_type', 3))  # Default to bus
                route_class = self.ROUTE_TYPE_MAPPING.get(route_type, UKO.BusRoute)
                
                self.graph.add((route_uri, RDF.type, route_class))
                self.graph.add((route_uri, UKO.gtfsRouteId, Literal(route_id)))
                
                # Route name
                if 'route_short_name' in row and row['route_short_name']:
                    short_name = row['route_short_name']
                    self.graph.add((route_uri, UKO.routeShortName, Literal(short_name)))
                    self.graph.add((route_uri, RDFS.label, Literal(short_name)))
                elif 'route_long_name' in row and row['route_long_name']:
                    self.graph.add((route_uri, RDFS.label, Literal(row['route_long_name'])))
                
                if 'route_long_name' in row and row['route_long_name']:
                    self.graph.add((route_uri, UKO.routeLongName, Literal(row['route_long_name'])))
                
                if 'route_desc' in row and row['route_desc']:
                    self.graph.add((route_uri, UKO.routeDescription, Literal(row['route_desc'])))
                
                self.graph.add((route_uri, UKO.routeType, Literal(route_type, datatype=XSD.integer)))
                self.graph.add((route_uri, UKO.operatedBy, agency_uri))
                
                # Colors
                if 'route_color' in row and row['route_color']:
                    color = row['route_color']
                    if not color.startswith('#'):
                        color = '#' + color
                    self.graph.add((route_uri, UKO.routeColor, Literal(color)))
                
                if 'route_text_color' in row and row['route_text_color']:
                    text_color = row['route_text_color']
                    if not text_color.startswith('#'):
                        text_color = '#' + text_color
                    self.graph.add((route_uri, UKO.routeTextColor, Literal(text_color)))
                
                routes[route_id] = route_uri
                self.stats['routes'] += 1
        
        return routes
    
    def _load_stops(self, gtfs_dir: str) -> Dict[str, URIRef]:
        """Load stops.txt with bounding box filtering"""
        stops_file = os.path.join(gtfs_dir, 'stops.txt')
        stops = {}
        
        with open(stops_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                try:
                    stop_lat = float(row['stop_lat'])
                    stop_lon = float(row['stop_lon'])
                except (ValueError, KeyError):
                    continue
                
                # Filter by bounding box if provided
                if self.bbox:
                    lat_min, lat_max, lon_min, lon_max = self.bbox
                    if not (lat_min <= stop_lat <= lat_max and lon_min <= stop_lon <= lon_max):
                        self.stats['stops_filtered'] += 1
                        continue
                
                stop_id = row['stop_id']
                stop_uri = UKO_ENTITY[f"stop/{stop_id}"]
                
                # Determine stop type
                location_type = int(row.get('location_type', 0))
                if location_type == 1:
                    stop_class = UKO.TransitStation
                elif location_type == 2:
                    stop_class = UKO.StationEntrance
                elif location_type == 3:
                    stop_class = UKO.GenericNode
                elif location_type == 4:
                    stop_class = UKO.BoardingArea
                else:
                    stop_class = UKO.StopLocation
                
                self.graph.add((stop_uri, RDF.type, stop_class))
                self.graph.add((stop_uri, UKO.gtfsStopId, Literal(stop_id)))
                self.graph.add((stop_uri, RDFS.label, Literal(row['stop_name'])))
                self.graph.add((stop_uri, UKO.stopName, Literal(row['stop_name'])))
                
                if 'stop_code' in row and row['stop_code']:
                    self.graph.add((stop_uri, UKO.stopCode, Literal(row['stop_code'])))
                
                if 'stop_desc' in row and row['stop_desc']:
                    self.graph.add((stop_uri, UKO.stopDescription, Literal(row['stop_desc'])))
                
                # Coordinates
                self.graph.add((stop_uri, UKO.latitude, Literal(stop_lat, datatype=XSD.decimal)))
                self.graph.add((stop_uri, UKO.longitude, Literal(stop_lon, datatype=XSD.decimal)))
                
                # Parent station
                if 'parent_station' in row and row['parent_station']:
                    parent_uri = UKO_ENTITY[f"stop/{row['parent_station']}"]
                    self.graph.add((stop_uri, UKO.parentStation, parent_uri))
                
                # Accessibility
                if 'wheelchair_boarding' in row and row['wheelchair_boarding']:
                    try:
                        wheelchair = int(row['wheelchair_boarding'])
                        self.graph.add((stop_uri, UKO.wheelchairBoardingType, 
                                      Literal(wheelchair, datatype=XSD.integer)))
                    except ValueError:
                        pass
                
                # Platform code
                if 'platform_code' in row and row['platform_code']:
                    self.graph.add((stop_uri, UKO.platformCode, Literal(row['platform_code'])))
                
                # Zone
                if 'zone_id' in row and row['zone_id']:
                    self.graph.add((stop_uri, UKO.zoneId, Literal(row['zone_id'])))
                
                stops[stop_id] = stop_uri
                self.stats['stops'] += 1
        
        return stops
    
    def _load_calendars(self, gtfs_dir: str) -> Dict[str, URIRef]:
        """Load calendar.txt"""
        calendar_file = os.path.join(gtfs_dir, 'calendar.txt')
        calendars = {}
        
        if not os.path.exists(calendar_file):
            print("Note: No calendar.txt file found (may use calendar_dates.txt instead)")
            return calendars
        
        with open(calendar_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                service_id = row['service_id']
                calendar_uri = UKO_ENTITY[f"calendar/{service_id}"]
                
                self.graph.add((calendar_uri, RDF.type, UKO.ServiceCalendar))
                self.graph.add((calendar_uri, UKO.gtfsServiceId, Literal(service_id)))
                
                # Days of week
                for day in ['monday', 'tuesday', 'wednesday', 'thursday', 'friday', 'saturday', 'sunday']:
                    if day in row:
                        value = bool(int(row[day]))
                        day_prop = f"service{day.capitalize()}"
                        prop = getattr(UKO, day_prop)
                        self.graph.add((calendar_uri, prop, Literal(value, datatype=XSD.boolean)))
                
                # Dates
                if 'start_date' in row:
                    start_date = row['start_date']
                    if len(start_date) == 8:  # YYYYMMDD format
                        start_date = f"{start_date[:4]}-{start_date[4:6]}-{start_date[6:]}"
                    self.graph.add((calendar_uri, UKO.startDate, Literal(start_date, datatype=XSD.date)))
                
                if 'end_date' in row:
                    end_date = row['end_date']
                    if len(end_date) == 8:
                        end_date = f"{end_date[:4]}-{end_date[4:6]}-{end_date[6:]}"
                    self.graph.add((calendar_uri, UKO.endDate, Literal(end_date, datatype=XSD.date)))
                
                calendars[service_id] = calendar_uri
                self.stats['calendars'] += 1
        
        return calendars
    
    def _load_trips(self, gtfs_dir: str, routes: Dict, calendars: Dict) -> Dict[str, URIRef]:
        """Load trips.txt (with optional limit for testing)"""
        trips_file = os.path.join(gtfs_dir, 'trips.txt')
        trips = {}
        
        # Optional: limit trips for testing
        max_trips = None  # Set to integer to limit, None for all
        
        with open(trips_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                if max_trips and len(trips) >= max_trips:
                    print(f"Note: Limited to {max_trips} trips for testing")
                    break
                
                trip_id = row['trip_id']
                trip_uri = UKO_ENTITY[f"trip/{trip_id}"]
                
                self.graph.add((trip_uri, RDF.type, UKO.TransitTrip))
                self.graph.add((trip_uri, UKO.gtfsTripId, Literal(trip_id)))
                
                # Link to route
                route_id = row['route_id']
                if route_id in routes:
                    self.graph.add((trip_uri, UKO.belongsToRoute, routes[route_id]))
                
                # Link to calendar
                service_id = row['service_id']
                if service_id in calendars:
                    self.graph.add((trip_uri, UKO.hasServiceCalendar, calendars[service_id]))
                
                if 'trip_headsign' in row and row['trip_headsign']:
                    self.graph.add((trip_uri, UKO.tripHeadsign, Literal(row['trip_headsign'])))
                
                if 'trip_short_name' in row and row['trip_short_name']:
                    self.graph.add((trip_uri, UKO.tripShortName, Literal(row['trip_short_name'])))
                
                if 'direction_id' in row and row['direction_id']:
                    try:
                        direction = int(row['direction_id'])
                        self.graph.add((trip_uri, UKO.directionId, Literal(direction == 1, datatype=XSD.boolean)))
                    except ValueError:
                        pass
                
                if 'block_id' in row and row['block_id']:
                    self.graph.add((trip_uri, UKO.blockId, Literal(row['block_id'])))
                
                if 'shape_id' in row and row['shape_id']:
                    self.graph.add((trip_uri, UKO.gtfsShapeId, Literal(row['shape_id'])))
                
                if 'wheelchair_accessible' in row and row['wheelchair_accessible']:
                    try:
                        wheelchair = int(row['wheelchair_accessible'])
                        self.graph.add((trip_uri, UKO.wheelchairAccessible, 
                                      Literal(wheelchair == 1, datatype=XSD.boolean)))
                    except ValueError:
                        pass
                
                if 'bikes_allowed' in row and row['bikes_allowed']:
                    try:
                        bikes = int(row['bikes_allowed'])
                        self.graph.add((trip_uri, UKO.bikesAllowed, 
                                      Literal(bikes == 1, datatype=XSD.boolean)))
                    except ValueError:
                        pass
                
                trips[trip_id] = trip_uri
                self.stats['trips'] += 1
        
        return trips
    
    def _load_stop_times(self, gtfs_dir: str, trips: Dict, stops: Dict):
        """Load stop_times.txt and create stop sequences"""
        stop_times_file = os.path.join(gtfs_dir, 'stop_times.txt')
        
        print(f"Loading stop times (this may take a while)...")
        
        # Process stop times in batches
        trip_stops = {}
        processed = 0
        
        with open(stop_times_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                trip_id = row['trip_id']
                if trip_id not in trips:
                    continue
                
                stop_id = row['stop_id']
                if stop_id not in stops:
                    continue
                
                if trip_id not in trip_stops:
                    trip_stops[trip_id] = []
                
                trip_stops[trip_id].append({
                    'stop_uri': stops[stop_id],
                    'sequence': int(row['stop_sequence']),
                    'arrival_time': row.get('arrival_time', ''),
                    'departure_time': row.get('departure_time', ''),
                    'pickup_type': int(row.get('pickup_type', 0)),
                    'drop_off_type': int(row.get('drop_off_type', 0))
                })
                
                processed += 1
                if processed % 10000 == 0:
                    print(f"  Processed {processed:,} stop times...")
        
        print(f"Creating stop time entities for {len(trip_stops):,} trips...")
        
        # Create stop sequences
        for i, (trip_id, stops_list) in enumerate(trip_stops.items()):
            if i % 1000 == 0 and i > 0:
                print(f"  Created entities for {i:,} / {len(trip_stops):,} trips...")
            
            trip_uri = trips[trip_id]
            stops_sorted = sorted(stops_list, key=lambda x: x['sequence'])
            
            for stop_info in stops_sorted:
                stop_uri = stop_info['stop_uri']
                
                # Create stop time entity
                stop_time_uri = UKO_ENTITY[f"stoptime/{trip_id}_{stop_info['sequence']}"]
                self.graph.add((stop_time_uri, RDF.type, UKO.StopTime))
                self.graph.add((stop_time_uri, UKO.atStop, stop_uri))
                self.graph.add((trip_uri, UKO.hasStopTime, stop_time_uri))
                self.graph.add((stop_time_uri, UKO.stopSequence, 
                              Literal(stop_info['sequence'], datatype=XSD.integer)))
                
                # Times (may be empty for non-timepoint stops)
                if stop_info['arrival_time']:
                    self.graph.add((stop_time_uri, UKO.arrivalTime, Literal(stop_info['arrival_time'])))
                
                if stop_info['departure_time']:
                    self.graph.add((stop_time_uri, UKO.departureTime, Literal(stop_info['departure_time'])))
                
                # Pickup/drop-off types
                self.graph.add((stop_time_uri, UKO.pickupType, 
                              Literal(stop_info['pickup_type'], datatype=XSD.integer)))
                self.graph.add((stop_time_uri, UKO.dropOffType, 
                              Literal(stop_info['drop_off_type'], datatype=XSD.integer)))
                
                self.stats['stop_times'] += 1
        
        print(f"✓ Created {self.stats['stop_times']:,} stop time entities")
    
    def _load_transfers(self, gtfs_dir: str, stops: Dict):
        """Load transfers.txt"""
        transfers_file = os.path.join(gtfs_dir, 'transfers.txt')
        
        with open(transfers_file, 'r', encoding='utf-8-sig') as f:
            reader = csv.DictReader(f)
            for row in reader:
                from_stop_id = row['from_stop_id']
                to_stop_id = row['to_stop_id']
                
                if from_stop_id in stops and to_stop_id in stops:
                    from_stop = stops[from_stop_id]
                    to_stop = stops[to_stop_id]
                    
                    transfer_type = int(row.get('transfer_type', 0))
                    
                    # Create transfer relationship
                    self.graph.add((from_stop, UKO.hasTransfer, to_stop))
                    
                    # Could create Transfer entity with more metadata if needed
                    if 'min_transfer_time' in row and row['min_transfer_time']:
                        # For now, just note the relationship exists
                        # Could be enhanced with reified statements
                        pass
                    
                    self.stats['transfers'] += 1
    
    def print_statistics(self):
        """Print loading statistics"""
        print("\n" + "="*60)
        print("GTFS LOADING STATISTICS")
        print("="*60)
        for key, value in self.stats.items():
            print(f"{key:20s}: {value:,}")
        print("="*60)


# Usage example
if __name__ == "__main__":
    from rdflib import Graph
    import sys
    
    print("="*60)
    print("GTFS to Knowledge Graph Loader")
    print("="*60)
    
    # Load existing knowledge graph (or create new one)
    kg_file = "contracosta_kg_enhanced.ttl"
    
    g = Graph()
    if os.path.exists(kg_file):
        print(f"\nLoading existing knowledge graph: {kg_file}")
        g.parse(kg_file, format="turtle")
        print(f"✓ Loaded {len(g):,} existing triples")
    else:
        print(f"\nCreating new knowledge graph")
        # Bind namespaces
        g.bind("uko", UKO)
        g.bind("uko_entity", UKO_ENTITY)
        g.bind("geo", GEO)
    
    # Define bounding box for Contra Costa County cities
    # Antioch, Pittsburg, Walnut Creek, Pleasant Hill, Richmond
    # [lat_min, lat_max, lon_min, lon_max]
    contra_costa_bbox = [37.88, 38.10, -122.35, -121.70]
    
    print(f"\nBounding box: {contra_costa_bbox}")
    print(f"  Latitude:  {contra_costa_bbox[0]} to {contra_costa_bbox[1]}")
    print(f"  Longitude: {contra_costa_bbox[2]} to {contra_costa_bbox[3]}")
    
    # Initialize loader
    # Note: 511.org API key is optional - direct feeds will be used by default
    api_key = os.environ.get('TRANSIT_511_API_KEY')  # Set environment variable if available
    
    loader = GTFSLoader(
        graph=g,
        api_key=api_key,
        bounding_box=contra_costa_bbox
    )
    
    # Select which agencies to load
    # Start with just County Connection (serves Contra Costa directly)
    agencies_to_load = ['County_Connection']
    
    # To load all available agencies, uncomment:
    # agencies_to_load = None
    
    # Or specify multiple agencies:
    # agencies_to_load = ['County_Connection', 'Tri_Delta', 'WestCAT']
    
    print(f"\nAgencies to load: {agencies_to_load if agencies_to_load else 'ALL'}")
    
    # Load Bay Area transit data
    try:
        loader.load_all_agencies(
            data_dir="gtfs_data",
            agencies=agencies_to_load
        )
    except KeyboardInterrupt:
        print("\n\nInterrupted by user")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nError during loading: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    
    # Print statistics
    loader.print_statistics()
    
    # Save enhanced graph
    output_file = "contracosta_kg_with_transit.ttl"
    print(f"\nSaving enhanced knowledge graph to: {output_file}")
    print("This may take a few minutes...")
    
    try:
        g.serialize(destination=output_file, format="turtle")
        file_size_mb = os.path.getsize(output_file) / 1024 / 1024
        print(f"✓ Saved successfully ({file_size_mb:.2f} MB)")
        print(f"  Total triples in graph: {len(g):,}")
    except Exception as e:
        print(f"Error saving graph: {e}")
        sys.exit(1)
    
    print("\n" + "="*60)
    print("GTFS LOADING COMPLETE")
    print("="*60)
    print(f"\nNext steps:")
    print(f"1. Review the knowledge graph: {output_file}")
    print(f"2. Load additional agencies if needed")
    print(f"3. Integrate with trip enhancement pipeline")
    print(f"4. Query transit connectivity for POIs")
    print("\nExample SPARQL query to find transit stops:")
    print("""
    PREFIX uko: <urn:urban-kg:>
    PREFIX rdfs: <http://www.w3.org/2000/01/rdf-schema#>
    
    SELECT ?stop ?name ?lat ?lon
    WHERE {
        ?stop a uko:StopLocation ;
              rdfs:label ?name ;
              uko:latitude ?lat ;
              uko:longitude ?lon .
    }
    LIMIT 10
    """)