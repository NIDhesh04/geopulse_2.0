# Congestion Heuristic

This document explains the heuristic used to translate raw vehicle speeds and densities into an edge weight multiplier.

## Parameters

*   `window_s`: Time window (in seconds) to consider for vehicle pings.
*   `jam_vehicles`: Number of vehicles on an edge required to consider it a "jam" (threshold).
*   `alpha`: Smoothing factor for exponential moving average (0 < alpha <= 1).
*   `max_multiplier`: The maximum cost multiplier an edge can have.

## Logic

1.  Calculate current score:
    `score = clamp(1 - (avg_speed / free_flow)) * clamp(vehicles / jam_vehicles)`
    *(Note: `clamp` limits the value between 0 and 1).*
2.  Calculate raw target multiplier:
    `target_multiplier = 1 + (max_multiplier - 1) * score`
3.  Smooth the multiplier using EWMA:
    `new_multiplier = (alpha * target_multiplier) + ((1 - alpha) * previous_multiplier)`

## Step-by-Step Example

Given:
*   `free_flow` = 50 km/h
*   `jam_vehicles` = 5
*   `max_multiplier` = 5.0
*   `alpha` = 0.3
*   `previous_multiplier` = 1.0

Scenario: 8 vehicles on an edge, moving at an average of 15 km/h.

| Step | Calculation | Result |
| :--- | :--- | :--- |
| 1. Speed factor | `clamp(1 - (15 / 50))` | `clamp(1 - 0.3) = 0.7` |
| 2. Density factor| `clamp(8 / 5)` | `clamp(1.6) = 1.0` |
| 3. Raw Score | `0.7 * 1.0` | `0.7` |
| 4. Target Mult | `1 + (5.0 - 1) * 0.7` | `1 + (4.0 * 0.7) = 3.8` |
| 5. New Mult | `(0.3 * 3.8) + (0.7 * 1.0)` | `1.14 + 0.7 = 1.84` |

The edge weight is now multiplied by **1.84**.
