import requests
import time

# 10 OD pairs roughly around the Chicago bounding box (41.8750,-87.6350 to 41.8900,-87.6150)
OD_PAIRS = [
    (41.8800, -87.6300, 41.8850, -87.6200),
    (41.8760, -87.6340, 41.8880, -87.6160),
    (41.8890, -87.6320, 41.8770, -87.6180),
    (41.8820, -87.6250, 41.8840, -87.6250),
    (41.8850, -87.6330, 41.8850, -87.6170),
    (41.8780, -87.6220, 41.8870, -87.6310),
    (41.8810, -87.6190, 41.8860, -87.6290),
    (41.8880, -87.6200, 41.8760, -87.6300),
    (41.8830, -87.6340, 41.8830, -87.6160),
    (41.8755, -87.6255, 41.8895, -87.6255),
]

def run_demo():
    print("Testing 10 Origin-Destination Pairs via /route API...")
    url = "http://localhost:8000/route"
    
    for i, (src_lat, src_lon, dst_lat, dst_lon) in enumerate(OD_PAIRS, 1):
        params = {
            "src_lat": src_lat,
            "src_lon": src_lon,
            "dst_lat": dst_lat,
            "dst_lon": dst_lon
        }
        
        start = time.time()
        resp = requests.get(url, params=params)
        latency_ms = (time.time() - start) * 1000
        
        assert resp.status_code == 200, f"Failed request {i}: {resp.status_code}"
        data = resp.json()
        assert "path" in data, f"No path returned for request {i}: {data}"
        
        path_len = len(data["path"])
        print(f"Pair {i:02d} | Latency: {latency_ms:6.2f}ms | Nodes in path: {path_len}")

if __name__ == "__main__":
    run_demo()
