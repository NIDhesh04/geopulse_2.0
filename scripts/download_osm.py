import requests
import os

def download_osm_data():
    bbox = "41.8750,-87.6350,41.8900,-87.6150"
    overpass_url = "http://overpass-api.de/api/interpreter"
    
    query = f"""
    [out:xml][timeout:25];
    (
      way["highway"]({bbox});
      node(w);
    );
    out body;
    """
    
    print(f"Downloading OSM data for bounding box {bbox}...")
    headers = {'User-Agent': 'GeoPulse-Dev-Agent'}
    response = requests.post(overpass_url, data=query, headers=headers)
    
    if response.status_code == 200:
        os.makedirs('data', exist_ok=True)
        with open('data/map.osm', 'w', encoding='utf-8') as f:
            f.write(response.text)
        print("Successfully downloaded map data to data/map.osm")
    else:
        print(f"Failed to download data: {response.status_code}")
        print(response.text)

if __name__ == "__main__":
    download_osm_data()
