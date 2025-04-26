# Web SDR Locations

This repository automatically fetches, processes, and stores location data for KiwiSDR receivers listed on `rx.skywavelinux.com`. The data is made available in JSON, GeoJSON, and cleaned JavaScript formats.

## Project Overview

The core of this project is a Python script (`scripts/process_kiwisdr.py`) that:

1.  **Fetches Data:** Downloads the KiwiSDR list from `https://rx.skywavelinux.com/kiwisdr_com.js`.
2.  **Parses Robustly:** Extracts the receiver data from the JavaScript file. It's designed to handle potential inconsistencies and errors in the source data by parsing each receiver entry individually and skipping any malformed entries rather than failing entirely.
3.  **Cleans Data:** Applies cleaning steps to fields like hardware description (`sdr_hw`) and name, and ensures essential fields are present.
4.  **Generates Outputs:** Saves the processed data into three files within the `data/` directory:
    *   `kiwisdr_locations.json`: A standard JSON array of receiver objects.
    *   `kiwisdr_locations.geojson`: A GeoJSON FeatureCollection suitable for mapping applications (only includes receivers with valid GPS coordinates).
    *   `kiwisdr_com_cleaned.js`: A JavaScript file containing the cleaned data in the original `var kiwisdr_com = [...]` format, along with timestamps.

## Generated Data

The processed data files are located in the `data/` directory of this repository:

*   **JSON:** [`data/kiwisdr_locations.json`](https://github.com/Sudo-Ivan/web-sdr-locations/blob/main/data/kiwisdr_locations.json)
*   **GeoJSON:** [`data/kiwisdr_locations.geojson`](https://github.com/Sudo-Ivan/web-sdr-locations/blob/main/data/kiwisdr_locations.geojson)
*   **Cleaned JS:** [`data/kiwisdr_com_cleaned.js`](https://github.com/Sudo-Ivan/web-sdr-locations/blob/main/data/kiwisdr_com_cleaned.js)

## Accessing the Data (API Examples)

You can directly access the raw data files using GitHub's raw content URLs.

**Base URL:** `https://raw.githubusercontent.com/Sudo-Ivan/web-sdr-locations/main/data/`

**Example: Fetching JSON using `curl`**

```bash
curl -L https://raw.githubusercontent.com/Sudo-Ivan/web-sdr-locations/main/data/kiwisdr_locations.json
```

**Example: Fetching GeoJSON using JavaScript `fetch`**

```javascript
const geoJsonUrl = 'https://raw.githubusercontent.com/Sudo-Ivan/web-sdr-locations/main/data/kiwisdr_locations.geojson';

fetch(geoJsonUrl)
  .then(response => {
    if (!response.ok) {
      throw new Error(`HTTP error! status: ${response.status}`);
    }
    return response.json(); // Parse the response as JSON
  })
  .then(data => {
    console.log('Successfully fetched GeoJSON data:');
    console.log(data);
    // Now you can use the GeoJSON data (e.g., add it to a map)
    // Example: L.geoJSON(data).addTo(map); // If using Leaflet
  })
  .catch(error => {
    console.error('Error fetching data:', error);
  });
```

**Example: Fetching JSON using Python `requests`**

```python
import requests
import json

json_url = 'https://raw.githubusercontent.com/Sudo-Ivan/web-sdr-locations/main/data/kiwisdr_locations.json'

try:
    response = requests.get(json_url)
    response.raise_for_status() # Raise an exception for bad status codes
    data = response.json()
    print(f"Successfully fetched {len(data)} KiwiSDR entries.")
    # Process the data list
    # for entry in data:
    #     print(entry.get('name', 'N/A'))
except requests.exceptions.RequestException as e:
    print(f"Error fetching data: {e}")
except json.JSONDecodeError:
    print("Error decoding JSON data.")

```