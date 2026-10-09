# GeoPulse: Team Build Guide

*Major Project PR1107, Institute of Engineering and Technology (IET) | Faculty guide: Dr. Pranab Roy* *Team of four | 10-week build plan with weekly deliverables*

## 1. How to use this guide

This is the single source of truth for who builds what, what is due each week, and how we know it works. Read sections 1 to 5 together in Week 1. After that, open section 6 every Monday and treat the week's checklist as the sprint.

The test suite (`geopulse-tests.zip`) and `tests/CONTRACT.md` define every interface. If this guide and the tests ever disagree, the tests win and this guide gets corrected in a pull request.

## 2. The project on one page

**What we build.** A prototype that tracks simulated vehicles, turns slow or bunched-up traffic into higher road costs, and serves routes that avoid those roads. Flow: Fleet simulator -> WebSocket `/ws/ingest` -> Redis Streams buffer -> Congestion worker -> PostGIS edge multipliers -> `/route` API -> Leaflet map.

**What done means (maps to the synopsis objectives).**

- Ingestion: simulated fleet streams pings without overloading the backend; a slow worker never causes lost pings.
- Map: one real neighbourhood (OpenStreetMap extract) is routable through PostGIS and pgRouting.
- Congestion: density and speed produce edge cost multipliers that rise during a jam and decay afterwards.
- API: `/route` returns routes reflecting current costs, with a `static=true` baseline for comparison.
- Demonstration: routes visibly change when a jam is introduced, backed by measured results (adaptive vs static), plus rough throughput and latency numbers.

**Honest scope note.** The core heuristic reacts to live density and speed, so it is congestion-aware routing rather than true forecasting. Forecasting (trend extrapolation) is a stretch goal with a go or no-go decision at the end of Week 6. Whatever we build, the report must describe it accurately.

## 3. Roles and ownership

Each person owns specific modules and the green status of the tests that cover them. Change someone else's module only through a pull request that the owner approves.

| Member | Role | Owns (code) | Owns (tests) | Reviews PRs of |
| --- | --- | --- | --- | --- |
| Member 1 | Maps, routing and route API | `app/routing.py`, `app/api_route.py`, `db/` | `test_routing.py`, `test_api.py` | Member 3 |
| Member 2 | Ingestion, reliability and DevOps | `app/main.py`, `app/api_ingest.py`, `docker-compose.yml`, `Dockerfile`, metrics | `test_ingestion.py`, `perf/` | Member 4 |
| Member 3 | Congestion engine | `app/worker.py`, `app/congestion.py`, tuning scripts | `test_congestion.py`, `test_worker.py` | Member 1 |
| Member 4 | Simulator, visualisation and evaluation | `sim/`, `web/`, `eval/`, `.github/` | `test_fleet.py`, `e2e/` | Member 2 |

Fill in names in the first row of the team table on Monday of Week 1. Every member also writes one chapter of the final report (section 10).

## 4. Contracts every member must know

**Edge cost (seconds)** = `length_m / (base_speed_kmh / 3.6) * multiplier`. Multipliers are finite and at least 1.

**Ping** (WebSocket JSON and Redis stream fields, all strings in Redis): `vehicle_id, lat, lon, speed_kmh, ts` (epoch seconds). Invalid pings are rejected at the edge of the system and never reach the stream. Unparseable stream messages go to `<stream>:dead`.

**Congestion heuristic** (already implemented in `app/congestion.py`):

- Each vehicle counts once per window, using its latest ping.
- `score = clamp(1 - avg_speed / free_flow) * clamp(vehicles / jam_vehicles)`. Both slow speed and enough vehicles are needed, so one car at a signal is not a jam.
- `multiplier = 1 + (max_multiplier - 1) * score`, then smoothed: `new = alpha * target + (1 - alpha) * previous`. Edges with no fresh evidence decay toward 1.
- Defaults to tune in Week 5: `window_s=60, jam_vehicles=5, alpha=0.3, max_multiplier=5.0`.

**Delivery guarantee.** The worker applies multipliers first and acknowledges (XACK) afterwards, so delivery is at least once. A crashed consumer's messages are reclaimed after `claim_idle_ms`.

**API.** `WS /ws/ingest`, `GET /route?src_lat&src_lon&dst_lat&dst_lon[&static=true]`, `GET /health`, plus `GET /vehicles` and `GET /multipliers` for the map (added in Weeks 3 and 4). Error codes: 404 `no_route`, 422 `outside_coverage`, 422 for bad input, 503 when the database is down.

**Contract changes.** Edit `tests/CONTRACT.md` in a PR and get a thumbs-up from every member who consumes the changed interface. Never change a contract silently.

## 5. Working agreements

**Git.** Short-lived branches `m<N>/<topic>`, pull requests into `main`, squash merge. `main` must always be green. Tag `v0.9` at feature freeze and `v1.0` at submission.

**Pull requests.** One reviewer from the table in section 3, review within 24 hours. A PR needs: passing CI, tests for new behaviour, and updated docs if it touches a contract. Keep PRs under about 400 changed lines.

**Definition of done** for any task: code merged, tests passing in CI, documented in `docs/` or the README, and shown at the Friday demo.

**Rhythm.**

- Monday, 20 min: read the weekly checklist, confirm who does what, name blockers.
- Wednesday, 15 min: sync. Anything slipping is raised here, not on Friday.
- Friday, 45 min: integration and demo. Everyone shows their deliverable running on `main`, then we tag the week.
- Suggested: a 30-minute check-in with Dr. Roy after the Friday demo, with the demo as the agenda.

**Unblocking without waiting.** Dependencies are handled with stand-ins so nobody idles:

- Member 3 builds against `FakeRouting` (in `tests/fakes.py`, same interface as `RoutingService`) until Member 1 lands the real one.
- Member 4 uses `sim.run --dry-run` to print pings until Member 2's endpoint is up.
- Member 2 tests ingestion with a plain `websockets` script, independent of the simulator.

**Cut order if we fall behind** (cut from the top, never from the bottom): 1) forecasting stretch goal, 2) side-by-side map toggle, 3) A\* vs Dijkstra comparison, 4) the third baseline mode (reactive). Never cut: tests, the failure demos, and the evaluation.

## 6. Weekly deliverables

Every week lists: the goal, what each member delivers, the exit check (a command or a demo that must work), and the Friday demo. Phases from the earlier plan overlap here because four people work in parallel.

### Week 1: Foundations

**Goal.** Everyone can run everything. No product features yet.

- **All.** Clone the starter project, read the synopsis and `CONTRACT.md`, run `pytest -m unit` (50 tests pass). Agree the demo area on Wednesday.
- **Member 1.** Propose the area: 2 to 5 km2, grid-like streets with genuine alternate routes, ideally somewhere the team knows well. Download the OpenStreetMap extract and write `docs/area.md` (bounding box and reasons). Draft `db/schema.sql` matching `tests/graph_fixture.py`. Run `osm2pgrouting` once locally on the extract.
- **Member 2.** `docker-compose.yml` with `db`, `redis` and `api`; a `Dockerfile`; Makefile targets `up`, `down`, `test`, `logs`; a FastAPI skeleton with `/health`.
- **Member 3.** Write `docs/heuristic.md` explaining each parameter with a worked example. Prototype the worker loop in a notebook using ten hand-made pings.
- **Member 4.** Create the repo with branch protection, CI (use the provided `ci.yml`), pre-commit with ruff, CODEOWNERS and issue labels. Add a `python -m sim.run --help` skeleton and a Leaflet page showing a base map.

**Exit check.** CI is green on `main`; `make up` works on all four laptops; the area is chosen.

**Friday demo.** Each person shows their setup running.

### Week 2: Components, part 1

**Goal.** Each core component works in isolation against the fixture graphs.

- **Member 1.** `RoutingService` passes `test_routing.py`: `connect/close`, `route` (pgr\_dijkstra with the cost expression), `snap_to_edge` (`ST_DWithin` plus nearest-neighbour `<->` on a GiST index), `apply_multipliers` (one `UPDATE ... FROM unnest` after validating all values), `get_multipliers`, `reset_multipliers`.
- **Member 2.** `create_app` plus `/ws/ingest` per the contract: lazy Redis connection so startup survives an outage, exact `MAXLEN` trimming, error acknowledgements that keep the socket open. `test_ingestion.py` green.
- **Member 3.** `CongestionWorker` against `FakeRouting`: `setup`, read, parse, dead-letter, aggregate, score, smooth, decay, ack-after-apply. Switch to real Redis tests and the real routing service as soon as Member 1 merges (target Thursday).
- **Member 4.** `sim.run`: N vehicles over WebSockets, rate limiting (default one ping per second per vehicle), reconnect with exponential backoff and jitter, `--seed`, `--slow-segment ID@T1..T2`. `sim/export_graph.py` to dump nodes and edges from the database as JSON for `Fleet`. Unit tests for the backoff function.

**Exit check.** `test_routing.py`, `test_ingestion.py` and the worker logic tests (with the fake) are green.

**Friday demo.** Member 4's simulator feeds Member 2's endpoint while `redis-cli XLEN` climbs.

### Week 3: Components, part 2

**Goal.** Everything runs against the real map, still as separate pieces.

- **Member 1.** Import the real area. Real data has one-way streets and different road classes, which the fixtures ignore, so add a one-way column (or reverse cost) with new tests: a one-way edge is traversable only forward and routes detour around it. Set `base_speed_kmh` by road class (start with residential 20, secondary 30, primary 40 and note the source). Measure route latency on the real graph (target p95 under 100 ms) and keep `EXPLAIN` notes. Implement `GET /route` in `app/api_route.py`; `test_api.py` green.
- **Member 2.** First throughput number from `pytest -m perf -s` (print only, no thresholds yet). Compose services for worker and simulator. Structured logging. `GET /vehicles` reading the Redis hash `vehicles:latest`.
- **Member 3.** Worker on the real `RoutingService`; `test_worker.py` fully green. Add `run_forever` with backoff. Write `vehicles:latest` once per batch (one `HSET`, not one per ping). Worker runs as a compose service.
- **Member 4.** `Fleet` runs on the real-area graph: 100 vehicles for 10 minutes with no crash or lost pings. `test_congestion_loop.py` runs in CI. Start the Leaflet vehicles layer polling `/vehicles`.

**Exit check.** `test_routing`, `test_ingestion`, `test_worker` and `test_api` all green in CI.

**Friday demo.** Vehicles drive around the real map on the page.

### Week 4: Vertical slice (Gate 1)

**Goal.** One live end-to-end demonstration of a reroute on the real map. Integration only, no new features.

- **Member 1.** `/route` verified on ten chosen origin-destination pairs with `scripts/demo_od.py`. Add `GET /multipliers`.
- **Member 2.** `make demo` starts the whole stack plus the simulator in one command. Fix cross-component bugs. Write the README quickstart.
- **Member 3.** Pick the jam edge on the real map and check the worker raises its multiplier within a measured time of the jam starting (log time-to-detect). Log the share of pings that fail to snap to a road and bring it under 5 percent by adjusting the snapping distance or investigating bad coordinates.
- **Member 4.** Leaflet: moving vehicles, click two points to draw a route, colour edges by multiplier. Record a 2-minute screen video of the reroute.

**Exit check (Gate 1).** Start the fleet, inject a jam with `--slow-segment`, and the route between two clicked points changes within about 30 seconds; when the jam ends, the route returns. If this is not true by Friday, Week 5 is spent fixing it and tuning is postponed.

**Friday demo.** The Gate 1 demonstration, shown to Dr. Roy.

### Week 5: Realism and tuning

**Goal.** Congestion arises from traffic itself, and parameters are chosen with evidence.

- **Member 4.** Add a speed-versus-density model to the simulator (BPR form: `speed = free_flow / (1 + 0.15 * (n / capacity)^4)`) so roads slow down as vehicles pile on. Create scenario files S1, S2, S3 (section 8). Vehicles request their route at trip start through `/route`.
- **Member 3.** Tuning harness: run a scenario across the parameter grid in the appendix and log time-to-detect, false-positive rate (multiplier above 1.5 with no incident) and oscillation (how often a route flips back and forth). Choose defaults and record them in `docs/tuning.md`.
- **Member 1.** Routing hardening. Document the limitation of snapping a start point to the nearest vertex rather than mid-edge, and add a test showing the error is bounded. Add a concurrency test with 50 parallel `/route` requests.
- **Member 2.** `GET /metrics` (JSON): `pings_in`, `pings_rejected`, `stream_lag`, `worker_last_tick`. The worker (Member 3) writes a heartbeat key in Redis; Member 2 reads it for `/health`.

**Exit check.** Scenario S2 runs unattended from start to finish; defaults chosen with plots in `docs/tuning.md`.

**Friday demo.** A jam forms by itself because too many vehicles use one road.

### Week 6: Reliability and hardening

**Goal.** The failure modes promised in the synopsis are real, scripted and tested.

- **Member 2 (lead).** Staleness rule: if the worker heartbeat is older than 60 seconds, `/route` returns `costs_stale: true` and old multipliers decay toward 1 (without this, a dead worker leaves a road penalised forever). Chaos scripts `scripts/chaos_worker.sh`, `chaos_redis.sh`, `chaos_db.sh` using `docker compose stop/start`; write down the expected behaviour for each and verify it.
- **Member 3.** Worker robustness: bounded memory under a flood of one million pings, de-duplication of redelivered pings by stream id, and a snapping cache keyed by rounded coordinates (report the speedup). Deliver a one-page go or no-go memo on forecasting by Friday.
- **Member 1.** Route latency under load with numbers. Return 503 with a retry hint if the database is unavailable. Optional: A\* versus Dijkstra timing.
- **Member 4.** UI polish: static versus adaptive toggle, legend, stats panel (pings per second, number of congested edges). Freeze the demo scenarios.

**Exit check.** Three failure demos (worker down, Redis down, database down) reproduce from scripts and each has a test; the stale-cost flag is tested.

**Friday demo.** Kill the worker live and show `/route` still answering.

### Week 7: Evaluation harness and feature freeze (Gate 2)

**Goal.** We can measure, repeatably, whether the system helps. After Friday, no new features.

- **Member 4.** `eval/run_experiment.py --scenario --mode --seed` runs the closed loop and writes one CSV row per trip: depart time, arrival time, distance, edges used, whether the jammed edge was used. Same seed gives identical output. Modes: `static`, `adaptive`, and optionally `reactive` (reroute only after being stuck).
- **Member 3.** Metric extraction: time-to-detect, false-positive rate, flip count, from worker logs and Redis.
- **Member 1.** Deterministic tie-breaking in routing (order by edge id) so runs are reproducible. Add a timing header to `/route` responses.
- **Member 2.** Performance runs on fixed hardware, three repeats each: pings per second, p50 and p95 latency, and the saturation point (add clients until p95 exceeds 50 ms). Document the machine used.

**Exit check (Gate 2).** One smoke run produces a CSV; the repo is tagged `v0.9`. Forecasting enters only if Gate 1 was met on time and the memo is approved, and then only behind `FORECAST=0` by default.

**Friday demo.** The harness runs a scenario in both modes and prints the comparison.

### Week 8: Experiments and results (Gate 3)

**Goal.** Produce the numbers for the report, whatever they turn out to be.

- **Member 4.** Run the full matrix: 3 scenarios x 2 or 3 modes x 10 seeds (60 to 90 runs). Nothing else runs on the machine during experiments.
- **Member 2.** Monitor and record hardware load during runs; re-run any run that was disturbed. Finalise the throughput and latency table.
- **Member 3.** Analysis notebook: means with bootstrap 95 percent confidence intervals, sensitivity plots for `alpha` and `jam_vehicles`.
- **Member 1.** Routing analysis: detour ratio (route distance divided by shortest distance), route latency, share of trips that avoided the jammed edge.

**Exit check (Gate 3).** A `results/` folder with raw CSVs, the notebook, figures, and a one-page summary stating: did adaptive routing help, by how much, and where did it hurt or make no difference. The no-incident control (S1) must show no harm.

**Friday demo.** Walk through the results table and figures.

### Week 9: Report, documentation and demo

**Goal.** A reader who was never in the room can understand, run and trust the project.

- **All.** Write your chapter (section 10). Remove or explain every skipped test.
- **Member 2.** README with a one-command quickstart. Run the fresh-clone test: a member who did not write the README clones into a clean machine or VM and follows it exactly; fix every gap found.
- **Member 4.** Compile the report. Write the 5-minute demo script, record a backup video, prepare slides.
- **Member 3.** Limitations and future work section (forecasting, directed congestion, real GPS noise).
- **Member 1.** Architecture figure and a data-model diagram for the report.

**Exit check.** Report draft to Dr. Roy by Wednesday; fresh-clone checklist signed off.

**Friday demo.** Full rehearsal of the 5-minute demo.

### Week 10: Buffer, rehearsal and submission

**Goal.** Finish calmly.

- Apply supervisor feedback. Fix only bugs, never new features.
- Two full rehearsals with questions. Rotate who answers, so each member can explain every component.
- Tag `v1.0`. Archive the code, report PDF, results folder and demo video. Submit.
- Prepare answers to likely questions: why Redis Streams instead of Kafka, why pgRouting, what the system cannot do, what the word predictive does and does not mean here.

## 7. Gates

| Gate | When | Passes when |
| --- | --- | --- |
| Gate 1: vertical slice | End of Week 4 | Live reroute demo on the real map |
| Gate 2: feature freeze | End of Week 7 | Harness smoke run works; `v0.9` tagged |
| Gate 3: results | End of Week 8 | `results/` and one-page summary complete |

If a gate is missed, the following week's plan is replaced by fixing it. Use the cut order in section 5 to recover time.

## 8. Evaluation design

**Question.** Does feeding observed congestion back into route costs reduce trip times compared with routing on a static map?

**Scenarios.**

- S1, control: normal demand, no incident. Adaptive should be about equal to static.
- S2, incident: one road slows sharply from t=120 s to t=420 s.
- S3, demand surge: vehicle release rate doubles for 5 minutes.

**Modes.** `static` (`static=true`), `adaptive` (default). Optional `reactive`: vehicles reroute only after being stuck, which is the behaviour the synopsis argues against.

**Protocol.** 10 seeds per scenario and mode; vehicles request a route at trip start and follow it; same machine, nothing else running; record hardware and parameters.

**Metrics.** Mean and 95th percentile trip time, detour ratio, share of trips avoiding the jammed edge, time-to-detect, false-positive rate, route flip count, `/route` p95 latency, ingestion pings per second and p95 latency.

**Reporting rule.** Report every result, including scenarios where adaptive routing helps little or hurts. A clear null or negative result with an explanation is acceptable; an unexplained claim is not. Watch for herding: if many vehicles divert at once, the alternate road can jam next, and smoothing is the mitigation to evaluate.

## 9. Risk register

| Risk | Likelihood | Impact | Mitigation | Owner |
| --- | --- | --- | --- | --- |
| Integration surprises in Week 4 | High | High | Fixtures and contracts from Week 1; Friday integration every week | All |
| Snapping pings to wrong roads | Medium | High | Log unsnapped share; tune distance; fallback to grid buckets from the synopsis | Member 3 |
| One-way streets and road classes break assumptions | High | Medium | Handle in Week 3 with tests | Member 1 |
| Herding or route flip-flopping | Medium | Medium | Smoothing, tuning in Week 5, flip-count metric | Member 3 |
| Experiments not reproducible | Medium | High | Seeded sim, deterministic tie-breaks, fixed hardware | Member 4 |
| One member blocked or ill | Medium | High | Review pairs know each other's modules; stand-ins in section 5 | All |
| Scope creep into forecasting | Medium | High | Go or no-go memo Week 6; feature freeze Week 7; flag off by default | Member 3 |

## 10. Report and demo outline

**Report chapters and authors.** 1 Introduction, problem and objectives (Member 4). 2 Architecture and data model (Member 1). 3 Map import, routing and API (Member 1). 4 Ingestion, buffering, reliability and performance (Member 2). 5 Congestion estimation and tuning (Member 3). 6 Simulator and visualisation (Member 4). 7 Evaluation method and results (Members 3 and 4). 8 Limitations and future work (Member 3). Appendices: contract, test summary, reproduction steps.

**5-minute demo.** 0:00 problem in one sentence. 0:45 show the map with vehicles. 1:30 inject a jam and watch the multiplier colours change. 2:30 the route between two points changes; toggle static to compare. 3:30 kill the worker and show `/route` still serving with the stale flag. 4:15 results table. 4:45 limitations and what is next.

## Appendix A: Setup and commands

```
pip install -r requirements-test.txt
pytest -m unit                              # no services, seconds
docker compose -f docker-compose.test.yml up -d --wait
pytest -m 'integration or e2e'              # needs PostGIS and Redis
pytest -m perf -s                           # throughput and latency numbers
REQUIRE_SERVICES=1 pytest                   # CI mode: missing services fail, not skip
```

The `pgrouting/pgrouting` image tag in `docker-compose.test.yml` should be checked against Docker Hub on first use.

## Appendix B: Tuning grid (Week 5)

| Parameter | Values to try | What to look for |
| --- | --- | --- |
| `window_s` | 30, 60, 120 | Shorter detects faster but is noisier |
| `alpha` | 0.1, 0.3, 0.5 | Higher reacts faster but flips more |
| `jam_vehicles` | 3, 5, 8 | Lower raises false positives |
| `max_multiplier` | 3, 5, 8 | Higher diverts more aggressively and risks herding |

Choose defaults by time-to-detect, false-positive rate and flip count together, never by one metric alone, and record the reasoning in `docs/tuning.md`.
