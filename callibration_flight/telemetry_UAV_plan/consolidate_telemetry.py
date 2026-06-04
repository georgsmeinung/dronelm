import json
import os
import csv
from datetime import datetime, timezone
from pathlib import Path

def facebook_timestamp_to_iso(timestamp_ms):
    """
    Convert Facebook timestamp (milliseconds since epoch) to ISO 8601 format.
    
    Args:
        timestamp_ms: Timestamp in milliseconds (as integer or string)
    
    Returns:
        ISO 8601 formatted datetime string
    """
    try:
        timestamp_ms = int(timestamp_ms)
        # Convert milliseconds to seconds
        timestamp_s = timestamp_ms / 1000.0
        dt = datetime.fromtimestamp(timestamp_s, timezone.utc)
        return dt.isoformat().replace('+00:00', 'Z')
    except (ValueError, OverflowError) as e:
        print(f"Error converting timestamp {timestamp_ms}: {e}")
        return None

def extract_timestamp_from_filename(filename):
    """
    Extract the timestamp from filename in format: message_TIMESTAMP.json
    
    Args:
        filename: Filename string
    
    Returns:
        Timestamp integer or None
    """
    try:
        # Extract the number between "message_" and ".json"
        name_without_ext = filename.replace('.json', '')
        timestamp_str = name_without_ext.replace('message_', '')
        return int(timestamp_str)
    except ValueError:
        return None

def load_telemetry_files(directory_paths):
    """
    Load all JSON telemetry files from the given directories.
    
    Args:
        directory_paths: List of directory paths to search
    
    Returns:
        List of dictionaries containing telemetry data with ISO timestamps
    """
    telemetry_data = []
    
    for dir_path in directory_paths:
        if not os.path.exists(dir_path):
            print(f"Warning: Directory {dir_path} not found")
            continue
        
        print(f"Processing directory: {dir_path}")
        
        # Get all JSON files sorted by timestamp
        json_files = sorted(
            [f for f in os.listdir(dir_path) if f.endswith('.json')],
            key=lambda f: extract_timestamp_from_filename(f) or 0
        )
        
        for filename in json_files:
            filepath = os.path.join(dir_path, filename)
            timestamp_ms = extract_timestamp_from_filename(filename)
            
            if timestamp_ms is None:
                print(f"Warning: Could not extract timestamp from {filename}")
                continue
            
            try:
                with open(filepath, 'r') as f:
                    data = json.load(f)
                
                # Add the ISO timestamp to the data
                data['timestamp_iso'] = facebook_timestamp_to_iso(timestamp_ms)
                data['timestamp_ms'] = timestamp_ms
                
                telemetry_data.append(data)
                
            except json.JSONDecodeError as e:
                print(f"Error reading JSON from {filename}: {e}")
            except Exception as e:
                print(f"Error processing {filename}: {e}")
    
    return telemetry_data

def save_to_csv(telemetry_data, output_path):
    """
    Save telemetry data to CSV file.
    
    Args:
        telemetry_data: List of telemetry dictionaries
        output_path: Path to output CSV file
    """
    if not telemetry_data:
        print("Error: No telemetry data to save")
        return False
    
    # Get all unique keys to use as CSV headers
    all_keys = set()
    for record in telemetry_data:
        all_keys.update(record.keys())
    
    # Sort keys, with timestamp first
    headers = ['timestamp_iso', 'timestamp_ms']
    other_keys = sorted([k for k in all_keys if k not in headers])
    headers.extend(other_keys)
    
    try:
        with open(output_path, 'w', newline='', encoding='utf-8') as csvfile:
            writer = csv.DictWriter(csvfile, fieldnames=headers)
            writer.writeheader()
            writer.writerows(telemetry_data)
        
        print(f"Successfully saved {len(telemetry_data)} records to {output_path}")
        return True
    except Exception as e:
        print(f"Error writing CSV file: {e}")
        return False

def main():
    """Main function."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    
    # Define directories to process
    drone1_dir = os.path.join(script_dir, "UAV_telemetry_dataset", "flightplan_drone1")
    drone2_dir = os.path.join(script_dir, "UAV_telemetry_dataset", "flightplan_drone2")
    
    # Define output path
    output_csv = os.path.join(script_dir, "consolidated_telemetry.csv")
    
    print(f"Consolidating telemetry data from two drone flights")
    print(f"Output will be saved to: {output_csv}\n")
    
    # Load telemetry data from both directories
    telemetry_data = load_telemetry_files([drone1_dir, drone2_dir])
    
    # Sort by timestamp
    telemetry_data.sort(key=lambda x: x.get('timestamp_ms', 0))
    
    # Save to CSV
    if save_to_csv(telemetry_data, output_csv):
        print(f"\nConsolidation complete!")
        print(f"Total records: {len(telemetry_data)}")
    else:
        print(f"\nConsolidation failed!")

if __name__ == "__main__":
    main()
