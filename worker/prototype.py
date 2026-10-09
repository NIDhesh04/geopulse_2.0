import time
import random

def clamp(val, min_val=0.0, max_val=1.0):
    return max(min_val, min(val, max_val))

def calculate_multiplier(pings, prev_multiplier, params):
    if not pings:
        # Decay towards 1.0
        return (params['alpha'] * 1.0) + ((1 - params['alpha']) * prev_multiplier)
    
    avg_speed = sum(p['speed'] for p in pings) / len(pings)
    num_vehicles = len(pings)
    
    speed_factor = clamp(1.0 - (avg_speed / params['free_flow']))
    density_factor = clamp(num_vehicles / params['jam_vehicles'])
    
    score = speed_factor * density_factor
    target = 1.0 + (params['max_multiplier'] - 1.0) * score
    
    return (params['alpha'] * target) + ((1 - params['alpha']) * prev_multiplier)

if __name__ == "__main__":
    params = {
        'jam_vehicles': 5,
        'max_multiplier': 5.0,
        'alpha': 0.3,
        'free_flow': 50.0
    }
    
    # Mock dataset of 10 vehicle pings on a single edge
    print("Generating mock pings...")
    mock_pings = []
    current_time = int(time.time())
    for i in range(10):
        mock_pings.append({
            'vehicle_id': f'v_{i}',
            'timestamp': current_time,
            'edge_id': 'edge_101',
            'speed': random.uniform(5.0, 25.0) # Slow speeds
        })
    
    print(f"Dataset generated: {len(mock_pings)} pings.")
    
    prev_mult = 1.0
    print(f"Initial multiplier: {prev_mult}")
    
    # Process
    new_mult = calculate_multiplier(mock_pings, prev_mult, params)
    print(f"Calculated new multiplier: {new_mult:.2f}")
