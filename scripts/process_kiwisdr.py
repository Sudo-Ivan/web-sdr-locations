import requests
import json
import re
import os
from datetime import datetime, timezone

DATA_DIR = "data"
OUTPUT_JSON = os.path.join(DATA_DIR, "kiwisdr_locations.json")
OUTPUT_GEOJSON = os.path.join(DATA_DIR, "kiwisdr_locations.geojson")
OUTPUT_JS = os.path.join(DATA_DIR, "kiwisdr_com_cleaned.js")
SOURCE_URL = "https://rx.skywavelinux.com/kiwisdr_com.js"

# Ensure data directory exists
os.makedirs(DATA_DIR, exist_ok=True)

def fetch_kiwisdr_data(url: str) -> str:
    """
    Fetches the KiwiSDR data from the specified URL.
    Tries UTF-8 decoding, falls back to latin-1 if needed.
    Raises an exception if the request fails.
    """
    print(f"Fetching data from {url}...")
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        try:
            content = response.content.decode('utf-8')
        except UnicodeDecodeError:
            print("Initial UTF-8 decoding failed, trying latin-1...")
            content = response.content.decode('latin-1')
        
        # Debug: Print first 500 characters of content
        print("First 500 characters of received content:")
        print(content[:500])
        return content
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        raise

def parse_js_data(js_content: str) -> tuple[list, str, str]:
    """
    Parses the JavaScript content to extract the data list and timestamps.
    Extracts the 'kiwisdr_com' variable and timestamps from comments.
    Returns a tuple containing the data list, Kiwi timestamp, and original generation timestamp.
    Raises ValueError if 'kiwisdr_com' is not found or if JSON decoding fails.
    """
    print("Parsing JavaScript data...")
    
    # Extract timestamps from comments first
    kiwi_timestamp_match = re.search(r"KiwiSDR.com data timestamp:\s*(.*)", js_content)
    gen_timestamp_match = re.search(r"File generation timestamp:\s*(.*)", js_content)

    kiwi_timestamp = kiwi_timestamp_match.group(1).strip() if kiwi_timestamp_match else "N/A"
    original_gen_timestamp = gen_timestamp_match.group(1).strip() if gen_timestamp_match else "N/A"

    # Try different patterns to find the data array
    patterns = [
        r"var\s+kiwisdr_com\s*=\s*(\[.*?\]);",  # Original pattern
        r"kiwisdr_com\s*=\s*(\[.*?\]);",        # Without 'var'
        r"var\s+kiwisdr_com\s*=\s*(\[.*?\])",   # Without semicolon
        r"kiwisdr_com\s*=\s*(\[.*?\])"          # Without 'var' and semicolon
    ]

    for pattern in patterns:
        match = re.search(pattern, js_content, re.DOTALL | re.MULTILINE)
        if match:
            json_str = match.group(1)
            try:
                data = json.loads(json_str)
                print(f"Successfully parsed {len(data)} entries.")
                return data, kiwi_timestamp, original_gen_timestamp
            except json.JSONDecodeError as e:
                print(f"Error decoding JSON with pattern '{pattern}': {e}")
                continue

    # If we get here, none of the patterns worked
    print("Could not find valid data array in the JavaScript file.")
    print("Content preview:")
    print(js_content[:1000])  # Print first 1000 characters for debugging
    raise ValueError("Could not find 'kiwisdr_com' assignment in the JavaScript file.")

def clean_entry(entry: dict) -> dict:
    """
    Cleans specific fields within a single KiwiSDR entry.
    Specifically cleans the 'sdr_hw' and 'name' fields.
    Ensures essential fields ('name', 'url', 'status', 'gps') exist, providing defaults if necessary.
    """
    if 'sdr_hw' in entry:
        hw_str = entry['sdr_hw']
        
        patterns = [
            (r'[^\x00-\x7F]+', ' '),
            (r'\s+', ' '),
            (r'GPS\s*\|', 'GPS |'),
            (r'Limits\s*\|', 'Limits |'),
            (r'\|\s*$', ''),
            (r'^\s*\|', ''),
        ]
        
        for pattern, replacement in patterns:
            hw_str = re.sub(pattern, replacement, hw_str)
        
        hw_str = hw_str.strip()
        entry['sdr_hw'] = hw_str

    if 'name' in entry:
        entry['name'] = re.sub(r'\s+', ' ', entry['name']).strip()

    entry.setdefault('name', 'N/A')
    entry.setdefault('url', '#')
    entry.setdefault('status', 'unknown')
    entry.setdefault('gps', '(0, 0)')

    return entry

def create_geojson(data: list) -> dict:
    """
    Converts the cleaned data list into a GeoJSON FeatureCollection.
    Extracts and validates GPS coordinates from each entry.
    Skips entries with missing or invalid GPS data.
    Returns a GeoJSON FeatureCollection dictionary.
    """
    print("Creating GeoJSON...")
    features = []
    processed_count = 0
    skipped_count = 0
    for entry in data:
        gps_match = re.match(r"\(\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*\)", entry.get('gps', ''))
        if gps_match:
            try:
                lat = float(gps_match.group(1))
                lon = float(gps_match.group(2))

                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    feature = {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [lon, lat]
                        },
                        "properties": {
                            "name": entry.get('name', 'N/A'),
                            "url": entry.get('url', '#'),
                            "status": entry.get('status', 'unknown'),
                            "users": entry.get('users', 'N/A'),
                            "users_max": entry.get('users_max', 'N/A'),
                            "loc": entry.get('loc', 'N/A'),
                            "antenna": entry.get('antenna', 'N/A'),
                            "sw_version": entry.get('sw_version', 'N/A'),
                            "sdr_hw": entry.get('sdr_hw', 'N/A'),
                            "id": entry.get('id')
                        }
                    }
                    features.append(feature)
                    processed_count += 1
                else:
                    print(f"Skipping entry '{entry.get('name', entry.get('id'))}' due to invalid coordinates: ({lat}, {lon})")
                    skipped_count += 1
            except ValueError:
                print(f"Skipping entry '{entry.get('name', entry.get('id'))}' due to non-numeric GPS part: {entry.get('gps')}")
                skipped_count += 1
        else:
            skipped_count += 1

    print(f"GeoJSON: Processed {processed_count} entries, skipped {skipped_count} due to missing/invalid GPS.")
    return {
        "type": "FeatureCollection",
        "features": features
    }

def write_json(filepath: str, data: list):
    """
    Writes the data list to a JSON file.
    Uses tabs for indentation and ensures ASCII characters are not escaped.
    """
    print(f"Writing JSON data to {filepath}...")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent='\t', ensure_ascii=False)
    print("JSON writing complete.")

def write_geojson(filepath: str, geojson_data: dict):
    """
    Writes the GeoJSON data to a file.
    Ensures ASCII characters are not escaped.
    """
    print(f"Writing GeoJSON data to {filepath}...")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(geojson_data, f, ensure_ascii=False)
    print("GeoJSON writing complete.")

def write_js(filepath: str, data: list, kiwi_ts: str, original_gen_ts: str):
    """
    Writes the data list back into the JavaScript variable format with headers.
    Includes timestamps for KiwiSDR data, original file generation, and current file generation.
    """
    print(f"Writing cleaned JS data to {filepath}...")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    current_time_gmt = datetime.now(timezone.utc).strftime("%A, %d-%b-%Y %H:%M:%S GMT")
    current_time_local = datetime.now().strftime("%a %b %d %H:%M:%S %Y")

    json_string = json.dumps(data, indent='\t', ensure_ascii=False)

    js_output = f"""// KiwiSDR.com receiver list
// Automatically generated from {SOURCE_URL}
// KiwiSDR.com data timestamp: {kiwi_ts}
// Original file generation timestamp: {original_gen_ts}
// This file generation timestamp: {current_time_local} ({current_time_gmt})

var kiwisdr_com =
{json_string};
"""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(js_output)
    print("JS writing complete.")


if __name__ == "__main__":
    try:
        js_content = fetch_kiwisdr_data(SOURCE_URL)
        raw_data, kiwi_timestamp, original_gen_timestamp = parse_js_data(js_content)

        print("Cleaning data entries...")
        cleaned_data = [clean_entry(entry) for entry in raw_data]
        print("Cleaning complete.")

        write_json(OUTPUT_JSON, cleaned_data)

        geojson_data = create_geojson(cleaned_data)
        write_geojson(OUTPUT_GEOJSON, geojson_data)

        write_js(OUTPUT_JS, cleaned_data, kiwi_timestamp, original_gen_timestamp)

        print("\nProcessing finished successfully!")

    except Exception as e:
        print(f"\nAn error occurred during processing: {e}")