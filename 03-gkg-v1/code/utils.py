import os
import requests
from tqdm import tqdm
from geopy.geocoders import Nominatim
import ssl
import certifi

def get_city_bounding_box(city: str, state: str) -> list | None:
    """
    Gets the bounding box for a given city and state using Nominatim.
    Returns [lat_min, lat_max, lon_min, lon_max] format expected by OSM handler.
    """
    print(f"Fetching bounding box for {city}, {state}...")
    
    ctx = ssl.create_default_context(cafile=certifi.where())
    geolocator = Nominatim(user_agent="urban_kg_builder_phase1", ssl_context=ctx)
    
    try:
        # Enhanced query for better city boundary detection
        query_variants = [
            f"{city}, {state}, USA",
            f"{city}, {state} County, CA, USA",
            f"City of {city}, {state}, USA"
        ]
        
        location = None
        for query in query_variants:
            try:
                location = geolocator.geocode(query, exactly_one=True, timeout=15)
                if location and 'boundingbox' in location.raw:
                    break
            except:
                continue
        
        if location and 'boundingbox' in location.raw:
            # Nominatim returns [lat_min, lat_max, lon_min, lon_max]
            bbox = [float(coord) for coord in location.raw['boundingbox']]
            
            # Validate bounding box makes sense for California
            lat_min, lat_max, lon_min, lon_max = bbox
            
            # Basic validation for California coordinates
            if not (32 <= lat_min <= 42 and 32 <= lat_max <= 42):
                print(f"WARNING: Latitude {lat_min}-{lat_max} outside California range")
            if not (-125 <= lon_min <= -114 and -125 <= lon_max <= -114):
                print(f"WARNING: Longitude {lon_min}-{lon_max} outside California range")
            
            # Ensure reasonable bounding box size (not too small or too large)
            lat_span = lat_max - lat_min
            lon_span = lon_max - lon_min
            
            if lat_span < 0.01 or lon_span < 0.01:
                print(f"WARNING: Very small bounding box for {city} (may miss suburbs)")
            elif lat_span > 1.0 or lon_span > 1.0:
                print(f"WARNING: Very large bounding box for {city} (may include other cities)")
            
            print(f"Found bounding box: {bbox}")
            print(f"  Coverage: ~{lat_span*111:.1f} km x {lon_span*111:.1f} km")
            return bbox
        else:
            print(f"Could not find location or bounding box for {city}, {state}")
            return None
            
    except Exception as e:
        print(f"An error occurred during geocoding: {e}")
        return None

def download_pbf(url: str, data_dir: str, force: bool = False) -> str | None:
    """
    Downloads a PBF file to a specified data directory, with a progress bar.
    Enhanced with better error handling and SSL verification.
    
    Args:
        url: The URL of the PBF file.
        data_dir: The directory to store the file in.
        force: If True, re-downloads the file even if it exists.

    Returns:
        The local path to the downloaded file, or None on failure.
    """
    local_filename = url.split('/')[-1]
    
    # Ensure the data directory exists
    os.makedirs(data_dir, exist_ok=True)
    
    pbf_filepath = os.path.join(data_dir, local_filename)
    
    if not os.path.exists(pbf_filepath) or force:
        print(f"PBF file not found in '{data_dir}'. Downloading from {url}...")
        print(f"Target file: {pbf_filepath}")
        
        try:
            # Enhanced SSL handling
            session = requests.Session()
            session.verify = certifi.where()
            
            # Add headers to avoid being blocked
            headers = {
                'User-Agent': 'Urban-KG-Builder/1.0 (https://urban-kg.org; contact@urban-kg.org)'
            }
            
            response = session.get(url, stream=True, headers=headers, timeout=30)
            response.raise_for_status()
            
            # Get file size for progress bar
            total_length = response.headers.get('content-length')
            if total_length is not None:
                total_length = int(total_length)
                print(f"File size: {total_length:,} bytes ({total_length/1024/1024:.1f} MB)")
            else:
                print("File size unknown")
            
            # Download with progress bar
            with open(pbf_filepath, 'wb') as f:
                if total_length is not None:
                    with tqdm(total=total_length, unit='iB', unit_scale=True, desc=local_filename) as pbar:
                        for chunk in response.iter_content(chunk_size=8192):
                            if chunk:  # Filter out keep-alive chunks
                                f.write(chunk)
                                pbar.update(len(chunk))
                else:
                    # Fallback without progress bar if size unknown
                    for chunk in response.iter_content(chunk_size=8192):
                        if chunk:
                            f.write(chunk)
            
            # Verify file was downloaded successfully
            if os.path.exists(pbf_filepath):
                file_size = os.path.getsize(pbf_filepath)
                print(f"Download complete. File size: {file_size:,} bytes")
                
                # Basic file validation
                if file_size < 1024:  # Less than 1KB is suspicious
                    print("WARNING: Downloaded file is very small - may be corrupted")
                    return None
                
                return pbf_filepath
            else:
                print("ERROR: Downloaded file not found after download")
                return None
                
        except requests.exceptions.Timeout:
            print("ERROR: Download timed out. Please check your internet connection.")
            return None
        except requests.exceptions.ConnectionError:
            print("ERROR: Connection failed. Please check your internet connection.")
            return None
        except requests.exceptions.HTTPError as e:
            print(f"ERROR: HTTP error during download: {e}")
            return None
        except requests.exceptions.RequestException as e:
            print(f"ERROR: Request error during download: {e}")
            return None
        except IOError as e:
            print(f"ERROR: File I/O error during download: {e}")
            return None
        except Exception as e:
            print(f"ERROR: Unexpected error during download: {e}")
            return None
    else:
        # Verify existing file
        file_size = os.path.getsize(pbf_filepath)
        print(f"Using existing PBF file: {pbf_filepath}")
        print(f"File size: {file_size:,} bytes ({file_size/1024/1024:.1f} MB)")
        
        # Basic validation of existing file
        if file_size < 1024*1024:  # Less than 1MB is suspicious for California
            print("WARNING: Existing PBF file seems very small - may be corrupted")
            print("Consider using --force_download to re-download")
        
        return pbf_filepath

def validate_bounding_boxes(bboxes: list) -> bool:
    """
    Validate that bounding boxes are reasonable for the target cities.
    
    Args:
        bboxes: List of bounding boxes in [lat_min, lat_max, lon_min, lon_max] format
        
    Returns:
        True if bounding boxes seem reasonable, False otherwise
    """
    if not bboxes:
        print("ERROR: No bounding boxes provided")
        return False
    
    print(f"Validating {len(bboxes)} bounding boxes...")
    
    for i, bbox in enumerate(bboxes):
        if len(bbox) != 4:
            print(f"ERROR: Bounding box {i} has {len(bbox)} coordinates, expected 4")
            return False
        
        lat_min, lat_max, lon_min, lon_max = bbox
        
        # Check coordinate order
        if lat_min >= lat_max:
            print(f"ERROR: Bounding box {i} has invalid latitude order: {lat_min} >= {lat_max}")
            return False
        
        if lon_min >= lon_max:
            print(f"ERROR: Bounding box {i} has invalid longitude order: {lon_min} >= {lon_max}")
            return False
        
        # Check reasonable ranges for California
        if not (30 <= lat_min <= 45 and 30 <= lat_max <= 45):
            print(f"WARNING: Bounding box {i} latitude {lat_min}-{lat_max} outside expected range for California")
        
        if not (-130 <= lon_min <= -110 and -130 <= lon_max <= -110):
            print(f"WARNING: Bounding box {i} longitude {lon_min}-{lon_max} outside expected range for California")
    
    # Check if bounding boxes are reasonably close to each other (Contra Costa County)
    all_lats = [coord for bbox in bboxes for coord in [bbox[0], bbox[1]]]
    all_lons = [coord for bbox in bboxes for coord in [bbox[2], bbox[3]]]
    
    lat_range = max(all_lats) - min(all_lats)
    lon_range = max(all_lons) - min(all_lons)
    
    if lat_range > 2.0 or lon_range > 2.0:
        print(f"WARNING: Cities span a large area (lat: {lat_range:.2f}°, lon: {lon_range:.2f}°)")
        print("This may result in a very large knowledge graph")
    
    print("✓ Bounding box validation completed")
    return True