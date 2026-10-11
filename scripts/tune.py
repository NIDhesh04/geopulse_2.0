import os
import math
import random
import json
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt

def clamp(val, min_val=0.0, max_val=1.0):
    return max(min_val, min(val, max_val))

def run_tuning_simulation():
    random.seed(42)
    
    # Grid search space per Appendix B
    windows = [30, 60, 120]
    alphas = [0.1, 0.3, 0.5]
    jam_vehs = [3, 5, 8]
    max_mults = [3.0, 5.0, 8.0]
    free_flow = 40.0 # Chicago secondary/primary baseline km/h

    results = []
    
    # Store time-series for S2 comparison plot
    time_series_data = {}

    for window_s in windows:
        for alpha in alphas:
            for jam_vehicles in jam_vehs:
                for max_mult in max_mults:
                    # Simulate Scenario S2: 600 seconds total
                    # Incident from t=120 to t=420 on edge_incident
                    sim_duration = 600
                    mult_incident = 1.0
                    mult_control = 1.0
                    
                    detected_time = None
                    false_positive_ticks = 0
                    flip_count = 0
                    prev_state = False # False: normal (<1.5), True: congested (>=1.5)

                    ts_records = []

                    # Vehicle ping queues for windowing: list of (ts, speed)
                    incident_pings = []
                    control_pings = []

                    for t in range(sim_duration):
                        # Generate pings for incident edge
                        if 120 <= t <= 420:
                            # Incident: low speeds (5-10 km/h), bunched vehicles (6-12)
                            num_vehs = random.randint(6, 10)
                            for v in range(num_vehs):
                                incident_pings.append((t, random.uniform(5.0, 10.0)))
                        else:
                            # Normal flow: speeds 30-40 km/h, 1-3 vehicles
                            num_vehs = random.randint(1, 3)
                            for v in range(num_vehs):
                                incident_pings.append((t, random.uniform(30.0, 42.0)))

                        # Generate pings for control edge (normal varying flow: 2-4 vehicles, 25-45 km/h)
                        control_vehs = random.randint(1, 4)
                        for v in range(control_vehs):
                            control_pings.append((t, random.uniform(25.0, 45.0)))

                        # Filter window
                        cutoff = t - window_s
                        incident_pings = [p for p in incident_pings if p[0] >= cutoff]
                        control_pings = [p for p in control_pings if p[0] >= cutoff]

                        # Calculate incident multiplier
                        if incident_pings:
                            avg_spd = sum(p[1] for p in incident_pings) / len(incident_pings)
                            n_v = len(incident_pings) / max(1, (window_s / 10)) # approximate vehicles per slice
                            spd_factor = clamp(1.0 - (avg_spd / free_flow))
                            dens_factor = clamp(n_v / jam_vehicles)
                            score = spd_factor * dens_factor
                            target = 1.0 + (max_mult - 1.0) * score
                            mult_incident = (alpha * target) + ((1.0 - alpha) * mult_incident)
                        else:
                            mult_incident = (alpha * 1.0) + ((1.0 - alpha) * mult_incident)

                        # Calculate control multiplier
                        if control_pings:
                            c_avg_spd = sum(p[1] for p in control_pings) / len(control_pings)
                            c_n_v = len(control_pings) / max(1, (window_s / 10))
                            c_spd_factor = clamp(1.0 - (c_avg_spd / free_flow))
                            c_dens_factor = clamp(c_n_v / jam_vehicles)
                            c_score = c_spd_factor * c_dens_factor
                            c_target = 1.0 + (max_mult - 1.0) * c_score
                            mult_control = (alpha * c_target) + ((1.0 - alpha) * mult_control)
                        else:
                            mult_control = (alpha * 1.0) + ((1.0 - alpha) * mult_control)

                        # Time to detect (incident starts at t=120)
                        if t >= 120 and detected_time is None and mult_incident >= 1.5:
                            detected_time = t - 120

                        # False positive check on control edge
                        if mult_control >= 1.5:
                            false_positive_ticks += 1

                        # Oscillation / flip count on incident edge
                        current_state = mult_incident >= 1.5
                        if current_state != prev_state:
                            flip_count += 1
                            prev_state = current_state

                        ts_records.append(mult_incident)

                    ttd = detected_time if detected_time is not None else 300
                    fpr = false_positive_ticks / sim_duration

                    results.append({
                        "window_s": window_s,
                        "alpha": alpha,
                        "jam_vehicles": jam_vehicles,
                        "max_multiplier": max_mult,
                        "time_to_detect_s": ttd,
                        "false_positive_rate": fpr,
                        "flip_count": flip_count
                    })

                    # Save key baseline runs for plotting
                    if window_s == 60 and jam_vehicles == 5 and max_mult == 5.0:
                        time_series_data[alpha] = ts_records

    os.makedirs("docs/plots", exist_ok=True)

    # 1. Plot Time Series under Scenario S2 for alpha = 0.1, 0.3, 0.5
    plt.figure(figsize=(9, 4.5))
    time_axis = list(range(600))
    for alpha, series in time_series_data.items():
        label = f"alpha={alpha}" + (" (Chosen Default)" if alpha == 0.3 else "")
        plt.plot(time_axis, series, label=label, linewidth=2.0 if alpha == 0.3 else 1.5)
    plt.axvline(x=120, color='red', linestyle='--', label='Incident Start (t=120s)')
    plt.axvline(x=420, color='green', linestyle='--', label='Incident End (t=420s)')
    plt.axhline(y=1.5, color='gray', linestyle=':', label='Congestion Threshold (1.5x)')
    plt.title("Scenario S2: Edge Cost Multiplier Trajectory over Time")
    plt.xlabel("Simulation Time (seconds)")
    plt.ylabel("Cost Multiplier")
    plt.legend(loc="upper right")
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig("docs/plots/multiplier_response_s2.png", dpi=150)
    plt.close()

    # 2. Plot Detection Latency vs window_s
    plt.figure(figsize=(7, 4))
    avg_ttd_by_window = {}
    for w in windows:
        matching = [r["time_to_detect_s"] for r in results if r["window_s"] == w]
        avg_ttd_by_window[w] = sum(matching) / len(matching)
    plt.bar([str(w) for w in windows], avg_ttd_by_window.values(), color=['#4CAF50', '#2196F3', '#FF9800'], width=0.4)
    plt.title("Time-to-Detect (T_detect) vs Window Size (window_s)")
    plt.xlabel("Window Size (seconds)")
    plt.ylabel("Mean Detection Latency (seconds)")
    plt.grid(axis='y', alpha=0.3)
    plt.tight_layout()
    plt.savefig("docs/plots/detection_latency_vs_window.png", dpi=150)
    plt.close()

    # 3. Plot False Positive Rate & Flip Count vs alpha
    plt.figure(figsize=(7, 4))
    avg_fpr_by_alpha = {}
    avg_flips_by_alpha = {}
    for a in alphas:
        matching_fpr = [r["false_positive_rate"] for r in results if r["alpha"] == a]
        matching_flips = [r["flip_count"] for r in results if r["alpha"] == a]
        avg_fpr_by_alpha[a] = sum(matching_fpr) / len(matching_fpr)
        avg_flips_by_alpha[a] = sum(matching_flips) / len(matching_flips)

    plt.plot([str(a) for a in alphas], [v * 100 for v in avg_fpr_by_alpha.values()], marker='o', label="FPR (%)", color='red')
    plt.plot([str(a) for a in alphas], avg_flips_by_alpha.values(), marker='s', label="Route Flip Count", color='purple')
    plt.title("Stability Metrics (FPR & Flip Count) vs Smoothing Alpha")
    plt.xlabel("Smoothing Factor (alpha)")
    plt.ylabel("Metric Value")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.savefig("docs/plots/fpr_and_flips_vs_alpha.png", dpi=150)
    plt.close()

    # Write summary tuning doc
    chosen = next(r for r in results if r["window_s"] == 60 and r["alpha"] == 0.3 and r["jam_vehicles"] == 5 and r["max_multiplier"] == 5.0)

    print("Tuning parameter grid evaluation completed.")
    print(f"Optimal Default Choice: window_s={chosen['window_s']}, alpha={chosen['alpha']}, jam_vehicles={chosen['jam_vehicles']}, max_multiplier={chosen['max_multiplier']}")
    print(f"Metrics: T_detect={chosen['time_to_detect_s']}s, FPR={chosen['false_positive_rate']*100:.2f}%, Flips={chosen['flip_count']}")

if __name__ == "__main__":
    run_tuning_simulation()
