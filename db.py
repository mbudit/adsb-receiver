import psycopg2
from psycopg2.extras import execute_values
import logging
import sqlite3
import os
from datetime import datetime
import config
import icao_ranges
import requests

logger = logging.getLogger("ADSBReceiver.DB")

def _fetch_aircraft_metadata(icao):
    """Fetches registration, type code, and model from hexdb.io for an ICAO hex code."""
    icao_clean = icao.lower().strip()
    url = f"https://hexdb.io/api/v1/aircraft/{icao_clean}"
    try:
        response = requests.get(url, timeout=3.0)
        if response.status_code == 200:
            data = response.json()
            return {
                "registration": data.get("Registration"),
                "type_code": data.get("ICAOTypeCode"),
                "model": data.get("Type") or data.get("Manufacturer")
            }
    except Exception as e:
        logger.debug(f"Failed to fetch metadata from hexdb.io for {icao_clean}: {e}")
    return None

import threading
import functools

def db_lock(method):
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        with self.lock:
            return method(self, *args, **kwargs)
    return wrapper

class DatabaseClient:
    def __init__(self):
        self.conn = None
        self.cursor = None
        self.lock = threading.RLock()

    @db_lock
    def connect(self):
        try:
            conn_str = config.get_connection_string()
            self.conn = psycopg2.connect(conn_str)
            self.cursor = self.conn.cursor()
            logger.info("Successfully connected to the database.")
            self._ensure_table_exists()
            return True
        except Exception as e:
            logger.error(f"Failed to connect to the database: {e}")
            self.conn = None
            self.cursor = None
            return False

    @db_lock
    def close(self):
        try:
            if self.cursor:
                self.cursor.close()
            if self.conn:
                self.conn.close()
            logger.info("Database connection closed.")
        except Exception as e:
            logger.error(f"Error closing database connection: {e}")

    @db_lock
    def is_connected(self):
        if not self.conn:
            return False
        try:
            self.cursor.execute("SELECT 1;")
            return True
        except Exception:
            return False

    @db_lock
    def _ensure_table_exists(self):
        """Checks if required tables exist. If not, it creates them."""
        try:
            # 1. Create aircraft metadata table
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS aircraft (
                    icao24 VARCHAR(6) PRIMARY KEY,
                    registration VARCHAR(12),
                    type_code VARCHAR(4),
                    model VARCHAR(100),
                    country VARCHAR(50),
                    country_code VARCHAR(2),
                    is_military BOOLEAN NOT NULL DEFAULT FALSE,
                    first_seen TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    last_seen TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # 2. Create aircraft_tracks
            self.cursor.execute("""
                SELECT EXISTS (
                    SELECT FROM information_schema.tables 
                    WHERE table_name = 'aircraft_tracks'
                );
            """)
            exists = self.cursor.fetchone()[0]
            if not exists:
                logger.warning("Table 'aircraft_tracks' does not exist. Creating table...")
                self.cursor.execute("""
                    CREATE TABLE IF NOT EXISTS aircraft_tracks (
                        time TIMESTAMPTZ NOT NULL,
                        icao24 VARCHAR(6) NOT NULL,
                        callsign VARCHAR(8),
                        lat DOUBLE PRECISION NOT NULL,
                        lng DOUBLE PRECISION NOT NULL,
                        altitude DOUBLE PRECISION,
                        velocity DOUBLE PRECISION,
                        heading DOUBLE PRECISION,
                        vertical_rate DOUBLE PRECISION,
                        squawk VARCHAR(4),
                        distance DOUBLE PRECISION,
                        uploaded BOOLEAN DEFAULT FALSE,
                        PRIMARY KEY (time, icao24),
                        CONSTRAINT FK_aircraft_tracks_aircraft FOREIGN KEY (icao24) REFERENCES aircraft(icao24) ON DELETE CASCADE
                    );
                """)
                # Try to create hypertable if TimescaleDB extension is active
                try:
                    self.cursor.execute("SELECT create_hypertable('aircraft_tracks', 'time', if_not_exists => TRUE);")
                    logger.info("Created TimescaleDB hypertable for aircraft_tracks.")
                except Exception:
                    logger.info("Created standard PostgreSQL table (TimescaleDB extension not active/available).")
            else:
                logger.info("Table 'aircraft_tracks' verified.")
                # Ensure new columns exist if table was created before
                self.cursor.execute("ALTER TABLE aircraft_tracks ADD COLUMN IF NOT EXISTS vertical_rate DOUBLE PRECISION;")
                self.cursor.execute("ALTER TABLE aircraft_tracks ADD COLUMN IF NOT EXISTS distance DOUBLE PRECISION;")
                self.cursor.execute("ALTER TABLE aircraft_tracks ADD COLUMN IF NOT EXISTS uploaded BOOLEAN DEFAULT FALSE;")
                
            # Create indexing helpers
            self.cursor.execute('CREATE INDEX IF NOT EXISTS "IDX_aircraft_tracks_unsent" ON aircraft_tracks (time) WHERE (uploaded = FALSE OR uploaded IS NULL);')

            # 2. Create connections table
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS connections (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100),
                    type VARCHAR(50) NOT NULL, -- 'network' or 'serial'
                    network VARCHAR(50), -- 'tcp' or 'udp'
                    address VARCHAR(100), -- IP or Host
                    port VARCHAR(10),
                    data_port VARCHAR(100), -- Serial COM port name
                    baudrate VARCHAR(50),
                    active INTEGER DEFAULT 1,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Seed default connection if none exists
            self.cursor.execute("SELECT COUNT(*) FROM connections;")
            if self.cursor.fetchone()[0] == 0:
                self.cursor.execute("""
                    INSERT INTO connections (name, type, network, address, port, active)
                    VALUES ('Local SDR Client', 'network', 'tcp', '127.0.0.1', '30002', 1);
                """)
                logger.info("Seeded default connections table.")

            # 3. Create senders table
            self.cursor.execute("""
                CREATE TABLE IF NOT EXISTS senders (
                    id SERIAL PRIMARY KEY,
                    name VARCHAR(100),
                    host VARCHAR(100) NOT NULL,
                    port VARCHAR(10) NOT NULL,
                    network VARCHAR(50) NOT NULL, -- 'tcp' or 'udp'
                    format VARCHAR(50) DEFAULT 'SBS',
                    active INTEGER DEFAULT 1,
                    last_send_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Ensure format column exists if table was created before
            self.cursor.execute("""
                ALTER TABLE senders 
                ADD COLUMN IF NOT EXISTS format VARCHAR(50) DEFAULT 'SBS';
            """)

            # Seed default sender if none exists
            self.cursor.execute("SELECT COUNT(*) FROM senders;")
            if self.cursor.fetchone()[0] == 0:
                self.cursor.execute("""
                    INSERT INTO senders (name, host, port, network, format, active)
                    VALUES ('Local Rebroadcaster', '127.0.0.1', '30005', 'udp', 'SBS', 0);
                """)
                logger.info("Seeded default senders table.")

            self.conn.commit()
            logger.info("All database tables verified and ready.")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error verifying or creating tables: {e}")

    @db_lock
    def insert_tracks_batch(self, tracks):
        """Inserts a list of track updates."""
        if not self.is_connected():
            logger.warning("Not connected to the database. Attempting reconnect...")
            if not self.connect():
                logger.error("Database reconnect failed. Batch data lost.")
                return False

        if not tracks:
            return True

        try:
            # 1. Extract unique ICAOs
            unique_icaos = {t["icao24"] for t in tracks}

            # Find which ICAOs already have metadata cached in the database
            self.cursor.execute("""
                SELECT icao24 
                FROM aircraft 
                WHERE icao24 = ANY(%s) AND registration IS NOT NULL;
            """, (list(unique_icaos),))
            cached_icaos = {row[0] for row in self.cursor.fetchall()}

            # Resolve metadata for new/uncached ICAOs
            aircraft_values = []
            for icao in unique_icaos:
                c_info = icao_ranges.find_icao_range(icao)
                country = c_info["country"]
                country_code = c_info["country_code"]
                
                registration = None
                type_code = None
                model = None

                if icao not in cached_icaos:
                    # Query API (blocks briefly up to 3s if slow, but usually <50ms)
                    api_data = _fetch_aircraft_metadata(icao)
                    if api_data:
                        registration = api_data.get("registration")
                        type_code = api_data.get("type_code")
                        model = api_data.get("model")
                        logger.info(f"API Metadata fetched for {icao}: {registration} ({type_code})")

                aircraft_values.append((
                    icao,
                    registration,
                    type_code,
                    model,
                    country,
                    country_code
                ))

            # 2. Upsert into aircraft table
            if aircraft_values:
                ac_query = """
                    INSERT INTO aircraft (icao24, registration, type_code, model, country, country_code)
                    VALUES %s
                    ON CONFLICT (icao24) DO UPDATE SET
                        registration = COALESCE(EXCLUDED.registration, aircraft.registration),
                        type_code = COALESCE(EXCLUDED.type_code, aircraft.type_code),
                        model = COALESCE(EXCLUDED.model, aircraft.model),
                        country = EXCLUDED.country,
                        country_code = EXCLUDED.country_code,
                        last_seen = NOW();
                """
                execute_values(self.cursor, ac_query, aircraft_values)

            # 3. Insert telemetry track points
            query = """
                INSERT INTO aircraft_tracks (time, icao24, callsign, lat, lng, altitude, velocity, heading, vertical_rate, squawk, distance, uploaded)
                VALUES %s
                ON CONFLICT (time, icao24) DO UPDATE SET
                    callsign = EXCLUDED.callsign,
                    lat = EXCLUDED.lat,
                    lng = EXCLUDED.lng,
                    altitude = EXCLUDED.altitude,
                    velocity = EXCLUDED.velocity,
                    heading = EXCLUDED.heading,
                    vertical_rate = EXCLUDED.vertical_rate,
                    squawk = EXCLUDED.squawk,
                    distance = EXCLUDED.distance,
                    uploaded = EXCLUDED.uploaded;
            """

            values = [
                (
                    t["time"],
                    t["icao24"],
                    t["callsign"],
                    t["lat"],
                    t["lng"],
                    t["altitude"],
                    t["velocity"],
                    t["heading"],
                    t.get("vertical_rate"),
                    t["squawk"],
                    t.get("distance"),
                    t.get("uploaded", False)
                )
                for t in tracks
            ]

            execute_values(self.cursor, query, values)
            self.conn.commit()
            logger.info(f"Successfully inserted {len(tracks)} track points into database.")
            return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to batch insert tracks: {e}")
            return False

    # --- Connections Management Methods ---
    @db_lock
    def get_active_connections(self):
        if not self.is_connected():
            self.connect()
        try:
            self.cursor.execute("""
                SELECT id, name, type, network, address, port, data_port, baudrate 
                FROM connections 
                WHERE active = 1;
            """)
            rows = self.cursor.fetchall()
            logger.info(f"DB: get_active_connections returned {len(rows)} rows. Description: {[desc[0] for desc in self.cursor.description]}")
            
            result = []
            for r in rows:
                row_list = list(r)
                if len(row_list) < 8:
                    logger.warning(f"DB: Row has fewer than 8 columns: {row_list} (len={len(row_list)})")
                    row_list += [None] * (8 - len(row_list))
                result.append({
                    'id': row_list[0],
                    'name': row_list[1],
                    'type': row_list[2],
                    'network': row_list[3],
                    'address': row_list[4],
                    'port': row_list[5],
                    'data_port': row_list[6],
                    'baudrate': row_list[7]
                })
            return result
        except Exception as e:
            logger.error(f"Error fetching active connections: {e}")
            if self.conn:
                self.conn.rollback()
            return []

    @db_lock
    def get_all_connections(self):
        if not self.is_connected():
            self.connect()
        try:
            self.cursor.execute("""
                SELECT id, name, type, network, address, port, data_port, baudrate, active 
                FROM connections 
                ORDER BY id;
            """)
            rows = self.cursor.fetchall()
            logger.info(f"DB: get_all_connections returned {len(rows)} rows. Description: {[desc[0] for desc in self.cursor.description]}")
            
            result = []
            for r in rows:
                row_list = list(r)
                if len(row_list) < 9:
                    logger.warning(f"DB: Row has fewer than 9 columns: {row_list} (len={len(row_list)})")
                    row_list += [None] * (9 - len(row_list))
                result.append({
                    'id': row_list[0],
                    'name': row_list[1],
                    'type': row_list[2],
                    'network': row_list[3],
                    'address': row_list[4],
                    'port': row_list[5],
                    'data_port': row_list[6],
                    'baudrate': row_list[7],
                    'active': row_list[8]
                })
            return result
        except Exception as e:
            logger.error(f"Error fetching all connections: {e}")
            if self.conn:
                self.conn.rollback()
            return []

    @db_lock
    def save_connection(self, conn_data):
        if not self.is_connected():
            self.connect()
        try:
            if conn_data.get('id'):
                # Update
                self.cursor.execute("""
                    UPDATE connections
                    SET name=%s, type=%s, network=%s, address=%s, port=%s, data_port=%s, baudrate=%s, active=%s, updated_at=CURRENT_TIMESTAMP
                    WHERE id=%s;
                """, (
                    conn_data['name'], conn_data['type'], conn_data.get('network'),
                    conn_data.get('address'), conn_data.get('port'), conn_data.get('data_port'),
                    conn_data.get('baudrate'), conn_data.get('active', 1), conn_data['id']
                ))
            else:
                # Insert
                self.cursor.execute("""
                    INSERT INTO connections (name, type, network, address, port, data_port, baudrate, active)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s);
                """, (
                    conn_data['name'], conn_data['type'], conn_data.get('network'),
                    conn_data.get('address'), conn_data.get('port'), conn_data.get('data_port'),
                    conn_data.get('baudrate'), conn_data.get('active', 1)
                ))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error saving connection: {e}")
            if self.conn:
                self.conn.rollback()
            return False

    @db_lock
    def delete_connection(self, conn_id):
        if not self.is_connected():
            self.connect()
        try:
            self.cursor.execute("DELETE FROM connections WHERE id = %s;", (conn_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error deleting connection: {e}")
            if self.conn:
                self.conn.rollback()
            return False

    # --- Senders Management Methods ---
    @db_lock
    def get_active_senders(self):
        if not self.is_connected():
            self.connect()
        try:
            self.cursor.execute("""
                SELECT id, name, host, port, network, format 
                FROM senders 
                WHERE active = 1;
            """)
            rows = self.cursor.fetchall()
            logger.info(f"DB: get_active_senders returned {len(rows)} rows. Description: {[desc[0] for desc in self.cursor.description]}")
            
            result = []
            for r in rows:
                row_list = list(r)
                if len(row_list) < 6:
                    logger.warning(f"DB: Row has fewer than 6 columns: {row_list} (len={len(row_list)})")
                    row_list += [None] * (6 - len(row_list))
                result.append({
                    'id': row_list[0],
                    'name': row_list[1],
                    'host': row_list[2],
                    'port': row_list[3],
                    'network': row_list[4],
                    'format': row_list[5]
                })
            return result
        except Exception as e:
            logger.error(f"Error fetching active senders: {e}")
            if self.conn:
                self.conn.rollback()
            return []

    @db_lock
    def get_all_senders(self):
        if not self.is_connected():
            self.connect()
        try:
            self.cursor.execute("""
                SELECT id, name, host, port, network, active, format 
                FROM senders 
                ORDER BY id;
            """)
            rows = self.cursor.fetchall()
            logger.info(f"DB: get_all_senders returned {len(rows)} rows. Description: {[desc[0] for desc in self.cursor.description]}")
            
            result = []
            for r in rows:
                row_list = list(r)
                if len(row_list) < 7:
                    logger.warning(f"DB: Row has fewer than 7 columns: {row_list} (len={len(row_list)})")
                    row_list += [None] * (7 - len(row_list))
                result.append({
                    'id': row_list[0],
                    'name': row_list[1],
                    'host': row_list[2],
                    'port': row_list[3],
                    'network': row_list[4],
                    'active': row_list[5],
                    'format': row_list[6]
                })
            return result
        except Exception as e:
            logger.error(f"Error fetching all senders: {e}")
            if self.conn:
                self.conn.rollback()
            return []

    @db_lock
    def save_sender(self, sender_data):
        if not self.is_connected():
            self.connect()
        try:
            if sender_data.get('id'):
                # Update
                self.cursor.execute("""
                    UPDATE senders
                    SET name=%s, host=%s, port=%s, network=%s, format=%s, active=%s, updated_at=CURRENT_TIMESTAMP
                    WHERE id=%s;
                """, (
                    sender_data['name'], sender_data['host'], sender_data['port'],
                    sender_data['network'], sender_data.get('format', 'SBS'),
                    sender_data.get('active', 1), sender_data['id']
                ))
            else:
                # Insert
                self.cursor.execute("""
                    INSERT INTO senders (name, host, port, network, format, active)
                    VALUES (%s, %s, %s, %s, %s, %s);
                """, (
                    sender_data['name'], sender_data['host'], sender_data['port'],
                    sender_data['network'], sender_data.get('format', 'SBS'),
                    sender_data.get('active', 1)
                ))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error saving sender: {e}")
            if self.conn:
                self.conn.rollback()
            return False

    @db_lock
    def delete_sender(self, sender_id):
        if not self.is_connected():
            self.connect()
        try:
            self.cursor.execute("DELETE FROM senders WHERE id = %s;", (sender_id,))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error deleting sender: {e}")
            if self.conn:
                self.conn.rollback()
            return False

    @db_lock
    def update_sender_time(self, sender_id, timestamp):
        if not self.is_connected():
            self.connect()
        try:
            self.cursor.execute("""
                UPDATE senders
                SET last_send_time = %s
                WHERE id = %s;
            """, (timestamp, sender_id))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error updating sender time: {e}")
            if self.conn:
                self.conn.rollback()
            return False

    # --- Data Retrieval / Upload Sync Queries ---
    @db_lock
    def get_unsent_tracks(self, limit=100):
        if not self.is_connected():
            self.connect()
        try:
            self.cursor.execute("""
                SELECT time, icao24, callsign, lat, lng, altitude, velocity, heading, vertical_rate, squawk, distance
                FROM aircraft_tracks
                WHERE uploaded = FALSE OR uploaded IS NULL
                ORDER BY time ASC
                LIMIT %s;
            """, (limit,))
            rows = self.cursor.fetchall()
            return [{
                'time': r[0],
                'icao24': r[1],
                'callsign': r[2],
                'lat': r[3],
                'lng': r[4],
                'altitude': r[5],
                'velocity': r[6],
                'heading': r[7],
                'vertical_rate': r[8],
                'squawk': r[9],
                'distance': r[10]
            } for r in rows]
        except Exception as e:
            logger.error(f"Error fetching unsent tracks: {e}")
            if self.conn:
                self.conn.rollback()
            return []

    @db_lock
    def mark_tracks_as_uploaded(self, track_keys):
        """Marks track updates as uploaded. track_keys is a list of dicts/tuples with time and icao24."""
        if not self.is_connected() or not track_keys:
            return False
        try:
            # Batch update
            self.cursor.executemany("""
                UPDATE aircraft_tracks
                SET uploaded = TRUE
                WHERE time = %s AND icao24 = %s;
            """, track_keys)
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error marking tracks as uploaded: {e}")
            if self.conn:
                self.conn.rollback()
            return False

    @db_lock
    def get_latest_tracks_since(self, since_time, limit=500):
        if not self.is_connected():
            self.connect()
        try:
            self.cursor.execute("""
                SELECT time, icao24, callsign, lat, lng, altitude, velocity, heading, vertical_rate, squawk, distance
                FROM aircraft_tracks
                WHERE time > %s
                ORDER BY time ASC
                LIMIT %s;
            """, (since_time, limit))
            rows = self.cursor.fetchall()
            return [{
                'time': r[0],
                'icao24': r[1],
                'callsign': r[2],
                'lat': r[3],
                'lng': r[4],
                'altitude': r[5],
                'velocity': r[6],
                'heading': r[7],
                'vertical_rate': r[8],
                'squawk': r[9],
                'distance': r[10]
            } for r in rows]
        except Exception as e:
            logger.error(f"Error fetching latest tracks: {e}")
            if self.conn:
                self.conn.rollback()
            return []


class OfflineDatabase:
    def __init__(self, db_path=None):
        if db_path is None:
            # Save in the same directory as db.py
            db_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "offline_buffer.db")
        self.db_path = db_path
        self._init_db()
        
    def _init_db(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                conn.execute("""
                    CREATE TABLE IF NOT EXISTS offline_tracks (
                        time TEXT,
                        icao24 TEXT,
                        callsign TEXT,
                        lat REAL,
                        lng REAL,
                        altitude REAL,
                        velocity REAL,
                        heading REAL,
                        vertical_rate REAL,
                        squawk TEXT,
                        distance REAL,
                        PRIMARY KEY (time, icao24)
                    );
                """)
                conn.commit()

            # Ensure SQLite table has new columns if it was created previously
            with sqlite3.connect(self.db_path) as conn:
                try:
                    conn.execute("ALTER TABLE offline_tracks ADD COLUMN vertical_rate REAL;")
                except sqlite3.OperationalError:
                    pass
                try:
                    conn.execute("ALTER TABLE offline_tracks ADD COLUMN distance REAL;")
                except sqlite3.OperationalError:
                    pass
        except Exception as e:
            logger.error(f"Failed to initialize offline database: {e}")
            
    def save_tracks(self, tracks):
        if not tracks:
            return True
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.executemany("""
                    INSERT OR REPLACE INTO offline_tracks (time, icao24, callsign, lat, lng, altitude, velocity, heading, vertical_rate, squawk, distance)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?);
                """, [
                    (
                        t['time'].isoformat() if hasattr(t['time'], 'isoformat') else str(t['time']),
                        t['icao24'],
                        t.get('callsign'),
                        t['lat'],
                        t['lng'],
                        t.get('altitude'),
                        t.get('velocity'),
                        t.get('heading'),
                        t.get('vertical_rate'),
                        t.get('squawk'),
                        t.get('distance')
                    )
                    for t in tracks
                ])
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error saving to offline buffer: {e}")
            return False
            
    def get_unsent_tracks(self, limit=100):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    SELECT time, icao24, callsign, lat, lng, altitude, velocity, heading, vertical_rate, squawk, distance
                    FROM offline_tracks
                    ORDER BY time ASC
                    LIMIT ?;
                """, (limit,))
                rows = cursor.fetchall()
                tracks = []
                for r in rows:
                    try:
                        dt = datetime.fromisoformat(r[0])
                    except Exception:
                        dt = r[0]
                    tracks.append({
                        'time': dt,
                        'icao24': r[1],
                        'callsign': r[2],
                        'lat': r[3],
                        'lng': r[4],
                        'altitude': r[5],
                        'velocity': r[6],
                        'heading': r[7],
                        'vertical_rate': r[8],
                        'squawk': r[9],
                        'distance': r[10]
                    })
                return tracks
        except Exception as e:
            logger.error(f"Error reading from offline buffer: {e}")
            return []
            
    def delete_tracks(self, keys):
        if not keys:
            return True
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.executemany("""
                    DELETE FROM offline_tracks
                    WHERE time = ? AND icao24 = ?;
                """, [
                    (k[0].isoformat() if hasattr(k[0], 'isoformat') else str(k[0]), k[1])
                    for k in keys
                ])
                conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error deleting from offline buffer: {e}")
            return False
            
    def get_pending_count(self):
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT COUNT(*) FROM offline_tracks;")
                return cursor.fetchone()[0]
        except Exception as e:
            logger.error(f"Error counting offline buffer: {e}")
            return 0
