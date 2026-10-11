# GeoPulse

GeoPulse is a live, congestion-aware routing prototype. It ingests simulated vehicle traffic, calculates real-time congestion multipliers, and provides dynamic routes that actively avoid traffic jams.

## Architecture Stack
- **API**: FastAPI
- **Database**: PostgreSQL with PostGIS & pgRouting
- **Message Broker**: Redis Streams
- **Frontend**: HTML/JS with Leaflet.js

## Quickstart

### Prerequisites
1. **Docker Desktop** installed and running (with WSL2 integration if on Windows).
2. **Python 3.11+** installed locally for running scripts or the frontend server.

### Running the Demo (Vertical Slice)
1. **Start the Stack:** In the root directory, run the following command. This will build and launch the database, Redis, API, the congestion worker, and the traffic simulator all at once.
   ```bash
   make demo
   ```
2. **View the Map:** Open a new terminal in the project root directory and start a local HTTP server:
   ```bash
   python -m http.server 8080
   ```
   Then open your browser to `http://localhost:8080/web/`.
3. **Interact:** 
   - Click twice on the map to draw an Origin-Destination route.
   - You will see the route dynamically avoid roads that turn yellow or red as the simulator injects traffic.

### Shutting Down
To tear down the stack and remove containers:
```bash
make down
```
