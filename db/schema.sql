-- PostgreSQL/PostGIS Schema for GeoPulse

CREATE EXTENSION IF NOT EXISTS postgis;
CREATE EXTENSION IF NOT EXISTS pgrouting;

-- Nodes table for the spatial graph
CREATE TABLE IF NOT EXISTS ways_vertices_pgr (
    id BIGSERIAL PRIMARY KEY,
    osm_id BIGINT UNIQUE,
    lon NUMERIC(11,8),
    lat NUMERIC(11,8),
    the_geom GEOMETRY(Point, 4326)
);

-- Edges (Ways) table for the spatial graph
CREATE TABLE IF NOT EXISTS ways (
    id BIGSERIAL PRIMARY KEY,
    osm_id BIGINT,
    source_node_id BIGINT REFERENCES ways_vertices_pgr(id),
    target_node_id BIGINT REFERENCES ways_vertices_pgr(id),
    length_m DOUBLE PRECISION,
    cost DOUBLE PRECISION, -- Cost for pgrouting (e.g., length or time)
    reverse_cost DOUBLE PRECISION,
    x1 DOUBLE PRECISION,
    y1 DOUBLE PRECISION,
    x2 DOUBLE PRECISION,
    y2 DOUBLE PRECISION,
    maxspeed_kmh INTEGER,
    highway_type VARCHAR(50),
    the_geom GEOMETRY(LineString, 4326)
);

-- Indices for pgRouting and PostGIS performance
CREATE INDEX IF NOT EXISTS ways_source_idx ON ways(source_node_id);
CREATE INDEX IF NOT EXISTS ways_target_idx ON ways(target_node_id);
CREATE INDEX IF NOT EXISTS ways_the_geom_idx ON ways USING GIST(the_geom);
CREATE INDEX IF NOT EXISTS ways_vertices_pgr_the_geom_idx ON ways_vertices_pgr USING GIST(the_geom);
