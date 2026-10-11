-- Set base speeds based on road class
ALTER TABLE ways ADD COLUMN IF NOT EXISTS base_speed_kmh DOUBLE PRECISION;

UPDATE ways SET base_speed_kmh = 40 WHERE highway_type IN ('primary', 'primary_link');
UPDATE ways SET base_speed_kmh = 30 WHERE highway_type IN ('secondary', 'secondary_link', 'tertiary', 'tertiary_link');
UPDATE ways SET base_speed_kmh = 20 WHERE highway_type IN ('residential', 'unclassified', 'living_street');
UPDATE ways SET base_speed_kmh = 10 WHERE base_speed_kmh IS NULL; -- fallback

-- Ensure one-way streets have reverse_cost set to a high penalty (-1 for pgRouting)
-- osm2pgrouting typically sets reverse_cost = -1 for one-way streets. 
-- We'll ensure any edge explicitly marked one-way has reverse_cost = -1.
UPDATE ways SET reverse_cost = -1 WHERE reverse_cost IS NULL AND cost > 0;
