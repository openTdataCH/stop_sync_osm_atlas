-- Drop the existing database 'db'
DROP DATABASE IF EXISTS stops_db;

-- Create the new database 'stops_db'
CREATE DATABASE stops_db CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci;

-- Create the user and grant permissions
-- Note: Using % allows connections from any host, which is needed for Docker networking
CREATE USER IF NOT EXISTS 'stops_user'@'%' IDENTIFIED BY '1234';
GRANT ALL PRIVILEGES ON stops_db.* TO 'stops_user'@'%';

-- Also create with localhost for local connections if needed
CREATE USER IF NOT EXISTS 'stops_user'@'localhost' IDENTIFIED BY '1234';
GRANT ALL PRIVILEGES ON stops_db.* TO 'stops_user'@'localhost';

-- Apply the changes
FLUSH PRIVILEGES;

-- Use the new database
USE stops_db;

-- Create the main stops table (optimized for map rendering)
CREATE TABLE stops (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sloid VARCHAR(100),
    stop_type VARCHAR(50),
    match_type VARCHAR(50),

    -- Core location and linking attributes
    atlas_lat FLOAT,
    atlas_lon FLOAT,
    uic_ref VARCHAR(100),
    osm_node_id VARCHAR(100),
    osm_lat FLOAT,
    osm_lon FLOAT,
    distance_m FLOAT,

    -- OSM node type for marker rendering
    osm_node_type VARCHAR(50),

    atlas_duplicate_sloid VARCHAR(100) DEFAULT NULL,

    INDEX (sloid),
    INDEX (osm_node_id),
    INDEX (uic_ref),
    INDEX idx_atlas_lat_lon (atlas_lat, atlas_lon),
    INDEX idx_osm_lat_lon (osm_lat, osm_lon),
    INDEX idx_stop_type_match_type (stop_type, match_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Create the problems table
CREATE TABLE problems (
    id INT AUTO_INCREMENT PRIMARY KEY,
    stop_id INT,
    problem_type VARCHAR(50) NOT NULL,
    solution VARCHAR(500),
    is_persistent BOOLEAN DEFAULT FALSE,
    INDEX (stop_id),
    INDEX (problem_type),
    FOREIGN KEY (stop_id) REFERENCES stops(id) ON DELETE CASCADE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Create the persistent_data table
CREATE TABLE persistent_data (
    id INT AUTO_INCREMENT PRIMARY KEY,
    sloid VARCHAR(100),
    osm_node_id VARCHAR(100),
    problem_type VARCHAR(50),
    solution VARCHAR(500),
    note_type VARCHAR(20),  -- 'atlas', 'osm', or NULL for problem solutions
    note TEXT,              -- For storing persistent notes
    created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
    updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
    INDEX (sloid),
    INDEX (osm_node_id),
    INDEX (problem_type),
    INDEX (note_type),
    UNIQUE KEY unique_problem (sloid, osm_node_id, problem_type, note_type)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Create the atlas_stops table (new)
CREATE TABLE atlas_stops (
    sloid VARCHAR(100) PRIMARY KEY,
    atlas_designation VARCHAR(255),
    atlas_designation_official VARCHAR(255),
    atlas_business_org_abbr VARCHAR(100),
    routes_atlas JSON,
    routes_hrdf JSON,
    atlas_note TEXT,
    atlas_note_is_persistent BOOLEAN DEFAULT FALSE,
    INDEX idx_atlas_operator (atlas_business_org_abbr)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Create the osm_nodes table (new)
CREATE TABLE osm_nodes (
    osm_node_id VARCHAR(100) PRIMARY KEY,
    osm_local_ref VARCHAR(100),
    osm_name VARCHAR(255),
    osm_uic_name VARCHAR(255),
    osm_network VARCHAR(255),
    osm_public_transport VARCHAR(255),
    osm_railway VARCHAR(255),
    osm_amenity VARCHAR(255),
    osm_aerialway VARCHAR(255),
    osm_operator VARCHAR(255),
    routes_osm JSON,
    osm_note TEXT,
    osm_note_is_persistent BOOLEAN DEFAULT FALSE
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;

-- Create the routes_and_directions table
CREATE TABLE routes_and_directions (
    id INT AUTO_INCREMENT PRIMARY KEY,
    direction_id VARCHAR(20),
    osm_route_id VARCHAR(100),
    osm_nodes_json JSON,        -- List of node_ids that belong to this OSM route
    atlas_route_id VARCHAR(100),
    atlas_sloids_json JSON,     -- List of sloids that belong to this ATLAS route
    route_name VARCHAR(255),
    route_short_name VARCHAR(50),
    route_long_name VARCHAR(255),
    route_type VARCHAR(50),
    match_type VARCHAR(50),     -- 'matched', 'osm_only', 'atlas_only'
    INDEX (osm_route_id, direction_id),
    INDEX (atlas_route_id, direction_id)
) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4 COLLATE=utf8mb4_unicode_ci;