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

def clean_json_string(json_str: str) -> str:
    """
    Cleans the JSON string to handle common issues:
    - Removes trailing commas
    - Fixes unterminated strings
    - Removes invalid escape sequences
    - Adds missing commas before closing brackets/braces
    - Removes control characters
    """
    # Attempt to add missing commas before closing brackets/braces
    # Handles cases like "key": "value" } or "key": 123 } or "key": true }
    # This is applied BEFORE removing trailing commas to handle cases where both issues exist.
    json_str = re.sub(r'([^\s,{}\[\]])\s*([}\]])', r'\1,\2', json_str)

    # Remove trailing commas before closing brackets/braces (applied after potential comma insertion)
    json_str = re.sub(r',(\s*[}\]])', r'\1', json_str)

    # Fix potentially unterminated strings (simple approach - commented out as potentially risky)
    # json_str = re.sub(r'([^\\])"([^"]*?)([^\\])(\\s*[}\\]])', r'\\1"\\2\\3"\\4', json_str)

    # Remove invalid escape sequences (simple approach - commented out as potentially risky)
    # json_str = re.sub(r'\\\\([^"\\\\/bfnrtu])', r'\\1', json_str)

    # Remove control characters except for \t, \n, \r, \f which are valid in JSON strings
    json_str = re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f]', '', json_str)

    return json_str

def parse_js_data(js_content: str) -> tuple[list, str, str]:
    """
    Parses the JavaScript content to extract the data list and timestamps.
    Extracts the 'kiwisdr_com' variable and timestamps from comments.
    Attempts to parse each JSON object in the array individually, skipping malformed ones.
    Returns a tuple containing the data list, Kiwi timestamp, and original generation timestamp.
    Raises ValueError if 'kiwisdr_com' assignment is not found.
    """
    print("Parsing JavaScript data...")

    # Extract timestamps from comments first
    kiwi_timestamp_match = re.search(r"KiwiSDR.com data timestamp:\\s*(.*)", js_content)
    gen_timestamp_match = re.search(r"File generation timestamp:\\s*(.*)", js_content)

    kiwi_timestamp = kiwi_timestamp_match.group(1).strip() if kiwi_timestamp_match else "N/A"
    original_gen_timestamp = gen_timestamp_match.group(1).strip() if gen_timestamp_match else "N/A"

    # Try different patterns to find the data array assignment
    patterns = [
        r"var\s+kiwisdr_com\s*=\s*(\[.*?\]);",  # Original pattern
        r"kiwisdr_com\s*=\s*(\[.*?\]);",        # Without 'var'
        r"var\s+kiwisdr_com\s*=\s*(\[.*?\])",   # Without semicolon
        r"kiwisdr_com\s*=\s*(\[.*?\])"          # Without 'var' and semicolon
    ]

    json_str = None
    for pattern in patterns:
        match = re.search(pattern, js_content, re.DOTALL | re.MULTILINE)
        if match:
            json_str = match.group(1)
            break

    if json_str is None:
        print("Could not find 'kiwisdr_com' assignment in the JavaScript file.")
        print("Content preview:")
        print(js_content[:1000])
        raise ValueError("Could not find 'kiwisdr_com' assignment in the JavaScript file.")

    # --- Start individual object parsing ---
    json_content = json_str.strip()
    if not (json_content.startswith('[') and json_content.endswith(']')):
        raise ValueError("Extracted data does not look like a JSON array (missing brackets).")

    # Get content inside brackets
    inner_content = json_content[1:-1].strip()

    if not inner_content: # Handle empty array
        print("Parsed 0 entries (empty array).")
        return [], kiwi_timestamp, original_gen_timestamp

    # --- Use brace counting to find individual objects --- 
    object_strs = []
    brace_level = 0
    current_obj_start = -1
    in_string = False
    escape_next = False

    for i, char in enumerate(inner_content):
        if escape_next:
            escape_next = False
            continue
        
        if char == '\\':
            escape_next = True
            continue
            
        if char == '"' :
             # Toggle in_string state only if not escaped
             in_string = not in_string
        
        if not in_string: # Only count braces outside of strings
            if char == '{':
                if brace_level == 0:
                    current_obj_start = i
                brace_level += 1
            elif char == '}':
                brace_level -= 1
                if brace_level == 0 and current_obj_start != -1:
                    object_strs.append(inner_content[current_obj_start : i + 1])
                    current_obj_start = -1
                elif brace_level < 0: # Malformed, reset
                    print(f"Warning: Encountered closing brace without matching open brace near index {i}. Resetting.")
                    brace_level = 0
                    current_obj_start = -1 
    # --- End brace counting ---

    parsed_data = []
    success_count = 0
    fail_count = 0

    print(f"Attempting to parse {len(object_strs)} potential objects...")

    for i, obj_str in enumerate(object_strs):
        obj_str = obj_str.strip()
        if not obj_str: continue # Skip empty splits resulting from regex

        # Basic check/fix for braces (sometimes split might remove them at edges)
        if not obj_str.startswith('{'):
             # Avoid adding if it already starts correctly due to split edge case
             if not re.match(r"^\\s*\\{", obj_str):
                obj_str = '{' + obj_str
        if not obj_str.endswith('}'):
             # Avoid adding if it already ends correctly
             if not re.search(r"\\}\\s*$", obj_str):
                obj_str = obj_str + '}'

        # Final check if it looks like an object
        if not (obj_str.startswith('{') and obj_str.endswith('}')):
            print(f"Skipping malformed segment #{i+1}: Not a valid object structure ...{obj_str[:100]}...")
            fail_count += 1
            continue

        try:
            # Clean THIS object string before parsing
            cleaned_obj_str = clean_json_string(obj_str)
            data_item = json.loads(cleaned_obj_str)
            parsed_data.append(data_item)
            success_count += 1
        except json.JSONDecodeError as e:
            fail_count += 1
            print(f"Failed to parse object #{i+1}: {e}")
            # Print context if possible
            error_pos = getattr(e, 'pos', 0) # Use getattr for safety
            start = max(0, error_pos - 40)
            end = min(len(cleaned_obj_str), error_pos + 40)
            context = cleaned_obj_str[start:end].replace('\\n', ' ') # Show context on one line
            print(f"Context: ...{context}...")
        except Exception as e: # Catch other potential errors during parsing/cleaning
             fail_count += 1
             print(f"Unexpected error parsing object #{i+1}: {e}")
             print(f"Problematic object string: ...{obj_str[:200]}...")


    print(f"Finished parsing: Successfully parsed {success_count} entries, failed/skipped {fail_count} entries.")
    return parsed_data, kiwi_timestamp, original_gen_timestamp
    # --- End individual object parsing ---

def clean_entry(entry: dict) -> dict:
    """
    Cleans specific fields within a single KiwiSDR entry.
    Specifically cleans the 'sdr_hw' and 'name' fields.
    Ensures essential fields ('name', 'url', 'status', 'gps') exist, providing defaults if necessary.
    """
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
        # Extract and validate GPS coordinates
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