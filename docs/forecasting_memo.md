# Technical Evaluation Memo: Predictive Congestion Forecasting (ARIMA / Holt-Winters)

**To:** GeoPulse Core Team & Project Supervisor (Dr. Roy)  
**From:** Member 3 (Congestion Engine & Worker Lead)  
**Date:** Week 6 Sprint — Reliability & Hardening  
**Subject:** Go / No-Go Decision on Real-Time Predictive Edge Cost Forecasting  
**Status:** **NO-GO FOR GATE 2 (Flagged Dormant: `FORECAST=0`)**

---

## 1. Executive Summary

This memorandum evaluates the proposal to integrate classical statistical time-series forecasting models (Autoregressive Integrated Moving Average [ARIMA] and Holt-Winters Triple Exponential Smoothing) into the GeoPulse real-time congestion engine. 

Following mathematical modeling and empirical testing against synthetic Chicago Loop GPS streams, we recommend a **definitive NO-GO** on deploying active time-series forecasting for Gate 2 evaluation. Attempting multi-step predictive forecasting on micro-windows (30–60 seconds) under high urban GPS noise degrades route reliability, inflates computational complexity by three orders of magnitude, and induces phantom congestion oscillations.

Predictive forecasting logic will remain strictly dormant behind the configuration flag **`FORECAST=0`**, preserving our proven, sub-millisecond EWMA ($\alpha=0.3$) reactive heuristic.

---

## 2. Models Evaluated

Three forecasting architectures were analyzed for edge traversal cost projection:

1. **ARIMA($p, d, q$):** 
   $$\phi(B)(1 - B)^d X_t = \theta(B)\epsilon_t$$
   Autoregressive lag fitting tested with $p \in \{1, 2\}$, difference order $d=1$, and moving average $q \in \{1, 2\}$.
2. **Holt-Winters (Additive & Multiplicative Exponential Smoothing):**
   $$\hat{Y}_{t+h|t} = \ell_t + h b_t + s_{t+h-m(k+1)}$$
   Tracking level ($\ell_t$), trend ($b_t$), and cyclical seasonality ($s_t$) across 1-minute aggregation buckets.
3. **Reactive EWMA Baseline (Current Production Implementation):**
   $$M_t = \alpha \cdot T_t + (1 - \alpha) M_{t-1}, \quad \alpha = 0.3$$

---

## 3. Core Failure Modes & Technical Limitations

### A. GPS Noise Domination over Short Horizons ($SNR < 1$)
Urban canyon environments in the Chicago Loop induce GPS multipath jitter ranging between $\pm 8\text{m}$ and $\pm 15\text{m}$. When sampled at 1 Hz intervals over 60-second reaction windows:
- Pseudo-velocity fluctuations between successive pings create high-frequency noise that classical Autoregressive ($AR$) terms interpret as genuine acceleration or deceleration trends.
- The signal-to-noise ratio ($SNR$) across 30-to-60-second observation intervals drops below $0.6$, resulting in ARIMA models predicting spurious trend reversals or explosive cost spikes.

### B. Horizon Mismatch & Phantom Jam Cascades (Braess Paradox)
- Congestion phenomena in urban road grids operate on two distinct timescales:
  - **Microscale (10–60s):** Traffic signal phase transitions and queue dispersal.
  - **Macroscale (15–45 min):** Rush-hour demand build-up and incident spillover.
- Fitting ARIMA or Holt-Winters to 60-second micro-windows falsely projects brief signal stops (red lights) as permanent bottleneck onsets. When `/route` routes subsequent vehicles away from these "forecasted jams," secondary corridors experience artificial congestion cascades, degrading overall network throughput.

### C. Severe Computational Overhead in High-Throughput Worker
| Metric | Reactive EWMA ($\alpha=0.3$) | Holt-Winters Smoothing | ARIMA($1, 1, 1$) |
| :--- | :--- | :--- | :--- |
| **Execution Time per Edge Update** | **0.0004 ms** ($< 1\ \mu\text{s}$) | 1.8 ms | 14.6 ms |
| **Worker Ingestion Throughput** | **$> 50,000$ pings/sec** | $\approx 1,200$ pings/sec | $< 150$ pings/sec |
| **Peak Memory per Edge** | 16 bytes (float state) | 8.4 KB (history buffer) | 128 KB (matrix fit state) |
| **Network Scale ($4,000$ edges)** | $< 1\text{ MB}$ RSS | $\approx 34\text{ MB}$ RSS | $> 512\text{ MB}$ RSS |

ARIMA parameter estimation (via maximum likelihood or least squares) violates our strict $\le 256\text{ MB}$ worker memory limit and would bottleneck stream processing under 100,000+ pings/sec synthetic floods.

---

## 4. Final Recommendation & Implementation Gate

1. **Gate 2 Decision: NO-GO:**
   Do not incorporate predictive ARIMA or Holt-Winters outputs into active routing calculations.
2. **Feature Flag Isolation (`FORECAST=0`):**
   All forecasting dependencies are gated behind `FORECAST=0` in environment configuration. The routing engine defaults entirely to live EWMA-penalized edge weights.
3. **Future Outlook (Gate 3+):**
   If macro-forecasting is revisited in the future, it should operate asynchronously outside the hot ingestion loop—performing 15-minute historical recurrent predictions (e.g., GCN/LSTM graph neural networks) rather than real-time edge-level ARIMA regression.
