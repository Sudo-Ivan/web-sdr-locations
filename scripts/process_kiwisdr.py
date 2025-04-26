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

def fetch_kiwisdr_data(url: str) -> str:
    """Fetches the KiwiSDR data from the specified URL."""
    print(f"Fetching data from {url}...")
    try:
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        # Attempt to decode potential Mojibake (assuming source is latin-1 misinterpreted as utf-8)
        try:
            return response.content.decode('utf-8')
        except UnicodeDecodeError:
            print("Initial UTF-8 decoding failed, trying latin-1...")
            return response.content.decode('latin-1') # Common alternative if UTF-8 fails
    except requests.exceptions.RequestException as e:
        print(f"Error fetching data: {e}")
        raise

def parse_js_data(js_content: str) -> tuple[list, str, str]:
    """Parses the JavaScript content to extract the data list and timestamps."""
    print("Parsing JavaScript data...")
    # Extract the list data assigned to var kiwisdr_com
    match = re.search(r"var\s+kiwisdr_com\s*=\s*(\[.*?\]);", js_content, re.DOTALL | re.MULTILINE)
    if not match:
        raise ValueError("Could not find 'var kiwisdr_com' assignment in the JavaScript file.")
    json_str = match.group(1)

    # Extract timestamps from comments
    kiwi_timestamp_match = re.search(r"KiwiSDR.com data timestamp:\s*(.*)", js_content)
    gen_timestamp_match = re.search(r"File generation timestamp:\s*(.*)", js_content)

    kiwi_timestamp = kiwi_timestamp_match.group(1).strip() if kiwi_timestamp_match else "N/A"
    original_gen_timestamp = gen_timestamp_match.group(1).strip() if gen_timestamp_match else "N/A"

    # Use json.loads for robust parsing after extraction
    try:
        data = json.loads(json_str)
        print(f"Successfully parsed {len(data)} entries.")
        return data, kiwi_timestamp, original_gen_timestamp
    except json.JSONDecodeError as e:
        print(f"Error decoding JSON: {e}")
        # Provide context for the error
        error_context = json_str[max(0, e.pos-20):min(len(json_str), e.pos+20)]
        print(f"Context: ...{error_context}...")
        raise

def clean_entry(entry: dict) -> dict:
    """Cleans specific fields within a single KiwiSDR entry."""
    # Clean sdr_hw field - replace common Mojibake/symbols
    if 'sdr_hw' in entry:
        hw_str = entry['sdr_hw']
        
        # Define patterns to clean up common encoding issues
        patterns = [
            (r'[^\x00-\x7F]+', ' '),  # Replace non-ASCII characters with space
            (r'\s+', ' '),            # Replace multiple spaces with single space
            (r'GPS\s*\|', 'GPS |'),   # Fix GPS separator
            (r'Limits\s*\|', 'Limits |'), # Fix Limits separator
            (r'\|\s*$', ''),          # Remove trailing separator
            (r'^\s*\|', ''),          # Remove leading separator
        ]
        
        # Apply all patterns
        for pattern, replacement in patterns:
            hw_str = re.sub(pattern, replacement, hw_str)
        
        # Clean up any remaining issues
        hw_str = hw_str.strip()
        entry['sdr_hw'] = hw_str

    # Clean name field
    if 'name' in entry:
        entry['name'] = re.sub(r'\s+', ' ', entry['name']).strip()

    # Ensure essential fields exist, provide defaults if necessary
    entry.setdefault('name', 'N/A')
    entry.setdefault('url', '#')
    entry.setdefault('status', 'unknown')
    entry.setdefault('gps', '(0, 0)') # Default GPS if missing

    return entry

def create_geojson(data: list) -> dict:
    """Converts the cleaned data list into a GeoJSON FeatureCollection."""
    print("Creating GeoJSON...")
    features = []
    processed_count = 0
    skipped_count = 0
    for entry in data:
        # Extract and validate GPS coordinates
        gps_match = re.match(r"\(\s*(-?\d+\.?\d*)\s*,\s*(-?\d+\.?\d*)\s*\)", entry.get('gps', ''))
        if gps_match:
            try:
                lat = float(gps_match.group(1))
                lon = float(gps_match.group(2))

                # Basic validation for latitude and longitude ranges
                if -90 <= lat <= 90 and -180 <= lon <= 180:
                    feature = {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [lon, lat]
                        },
                        "properties": {
                            # Include a selection of useful properties
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
            # print(f"Skipping entry '{entry.get('name', entry.get('id'))}' due to missing or invalid GPS format: {entry.get('gps')}")
            skipped_count += 1

    print(f"GeoJSON: Processed {processed_count} entries, skipped {skipped_count} due to missing/invalid GPS.")
    return {
        "type": "FeatureCollection",
        "features": features
    }

def write_json(filepath: str, data: list):
    """Writes the data list to a JSON file."""
    print(f"Writing JSON data to {filepath}...")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(data, f, indent='\t', ensure_ascii=False) # Use tabs for indent, keep unicode chars
    print("JSON writing complete.")

def write_geojson(filepath: str, geojson_data: dict):
    """Writes the GeoJSON data to a file."""
    print(f"Writing GeoJSON data to {filepath}...")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    with open(filepath, 'w', encoding='utf-8') as f:
        json.dump(geojson_data, f, ensure_ascii=False) # No indent for smaller file size
    print("GeoJSON writing complete.")

def write_js(filepath: str, data: list, kiwi_ts: str, original_gen_ts: str):
    """Writes the data list back into the JavaScript variable format with headers."""
    print(f"Writing cleaned JS data to {filepath}...")
    os.makedirs(os.path.dirname(filepath), exist_ok=True)
    current_time_gmt = datetime.now(timezone.utc).strftime("%A, %d-%b-%Y %H:%M:%S GMT")
    current_time_local = datetime.now().strftime("%a %b %d %H:%M:%S %Y") # Local time format like original

    # Use json.dumps for proper escaping within the JS string
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

        # Write Raw JSON
        write_json(OUTPUT_JSON, cleaned_data)

        # Create and Write GeoJSON
        geojson_data = create_geojson(cleaned_data)
        write_geojson(OUTPUT_GEOJSON, geojson_data)

        # Write Cleaned JavaScript File
        write_js(OUTPUT_JS, cleaned_data, kiwi_timestamp, original_gen_timestamp)

        print("\nProcessing finished successfully!")

    except Exception as e:
        print(f"\nAn error occurred during processing: {e}")
        # In a real scenario, you might want to exit with a non-zero code
        # import sys
        # sys.exit(1) 