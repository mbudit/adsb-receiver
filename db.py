import psycopg2
from psycopg2.extras import execute_values
import logging
import sqlite3
import os
from datetime import datetime
import config

logger = logging.getLogger("ADSBReceiver.DB")

class DatabaseClient:
    def __init__(self):
        self.conn = None
        self.cursor = None

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

    def close(self):
        try:
            if self.cursor:
                self.cursor.close()
            if self.conn:
                self.conn.close()
            logger.info("Database connection closed.")
        except Exception as e:
            logger.error(f"Error closing database connection: {e}")

    def is_connected(self):
        if not self.conn:
            return False
        try:
            self.cursor.execute("SELECT 1;")
            return True
        except Exception:
            return False

    def _ensure_table_exists(self):
        """Checks if required tables exist. If not, it creates them."""
        try:
            # 1. Create aircraft_tracks
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
                        icao24 VARCHAR(24) NOT NULL,
                        callsign VARCHAR(24),
                        lat DOUBLE PRECISION NOT NULL,
                        lng DOUBLE PRECISION NOT NULL,
                        altitude DOUBLE PRECISION,
                        velocity DOUBLE PRECISION,
                        heading DOUBLE PRECISION,
                        squawk VARCHAR(10),
                        uploaded BOOLEAN DEFAULT FALSE,
                        PRIMARY KEY (time, icao24)
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
                # Ensure uploaded column exists if table was created before
                self.cursor.execute("""
                    ALTER TABLE aircraft_tracks 
                    ADD COLUMN IF NOT EXISTS uploaded BOOLEAN DEFAULT FALSE;
                """)

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
                    active INTEGER DEFAULT 1,
                    last_send_time TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    created_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP,
                    updated_at TIMESTAMPTZ DEFAULT CURRENT_TIMESTAMP
                );
            """)

            # Seed default sender if none exists
            self.cursor.execute("SELECT COUNT(*) FROM senders;")
            if self.cursor.fetchone()[0] == 0:
                self.cursor.execute("""
                    INSERT INTO senders (name, host, port, network, active)
                    VALUES ('Local Rebroadcaster', '127.0.0.1', '30005', 'udp', 0);
                """)
                logger.info("Seeded default senders table.")

            self.conn.commit()
            logger.info("All database tables verified and ready.")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error verifying or creating tables: {e}")

    def insert_tracks_batch(self, tracks):
        """Inserts a list of track updates."""
        if not self.is_connected():
            logger.warning("Not connected to the database. Attempting reconnect...")
            if not self.connect():
                logger.error("Database reconnect failed. Batch data lost.")
                return False

        if not tracks:
            return True

        query = """
            INSERT INTO aircraft_tracks (time, icao24, callsign, lat, lng, altitude, velocity, heading, squawk)
            VALUES %s
            ON CONFLICT (time, icao24) DO UPDATE SET
                callsign = EXCLUDED.callsign,
                lat = EXCLUDED.lat,
                lng = EXCLUDED.lng,
                altitude = EXCLUDED.altitude,
                velocity = EXCLUDED.velocity,
                heading = EXCLUDED.heading,
                squawk = EXCLUDED.squawk;
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
                t["squawk"]
            )
            for t in tracks
        ]

        try:
            execute_values(self.cursor, query, values)
            self.conn.commit()
            logger.info(f"Successfully inserted {len(tracks)} track points into database.")
            return True
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Failed to batch insert tracks: {e}")
            return False

    # --- Connections Management Methods ---
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
            return [{
                'id': r[0],
                'name': r[1],
                'type': r[2],
                'network': r[3],
                'address': r[4],
                'port': r[5],
                'data_port': r[6],
                'baudrate': r[7]
            } for r in rows]
        except Exception as e:
            logger.error(f"Error fetching active connections: {e}")
            if self.conn:
                self.conn.rollback()
            return []

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
            return [{
                'id': r[0],
                'name': r[1],
                'type': r[2],
                'network': r[3],
                'address': r[4],
                'port': r[5],
                'data_port': r[6],
                'baudrate': r[7],
                'active': r[8]
            } for r in rows]
        except Exception as e:
            logger.error(f"Error fetching all connections: {e}")
            if self.conn:
                self.conn.rollback()
            return []

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
    def get_active_senders(self):
        if not self.is_connected():
            self.connect()
        try:
            self.cursor.execute("""
                SELECT id, name, host, port, network 
                FROM senders 
                WHERE active = 1;
            """)
            rows = self.cursor.fetchall()
            return [{
                'id': r[0],
                'name': r[1],
                'host': r[2],
                'port': r[3],
                'network': r[4]
            } for r in rows]
        except Exception as e:
            logger.error(f"Error fetching active senders: {e}")
            if self.conn:
                self.conn.rollback()
            return []

    def get_all_senders(self):
        if not self.is_connected():
            self.connect()
        try:
            self.cursor.execute("""
                SELECT id, name, host, port, network, active 
                FROM senders 
                ORDER BY id;
            """)
            rows = self.cursor.fetchall()
            return [{
                'id': r[0],
                'name': r[1],
                'host': r[2],
                'port': r[3],
                'network': r[4],
                'active': r[5]
            } for r in rows]
        except Exception as e:
            logger.error(f"Error fetching all senders: {e}")
            if self.conn:
                self.conn.rollback()
            return []

    def save_sender(self, sender_data):
        if not self.is_connected():
            self.connect()
        try:
            if sender_data.get('id'):
                # Update
                self.cursor.execute("""
                    UPDATE senders
                    SET name=%s, host=%s, port=%s, network=%s, active=%s, updated_at=CURRENT_TIMESTAMP
                    WHERE id=%s;
                """, (
                    sender_data['name'], sender_data['host'], sender_data['port'],
                    sender_data['network'], sender_data.get('active', 1), sender_data['id']
                ))
            else:
                # Insert
                self.cursor.execute("""
                    INSERT INTO senders (name, host, port, network, active)
                    VALUES (%s, %s, %s, %s, %s);
                """, (
                    sender_data['name'], sender_data['host'], sender_data['port'],
                    sender_data['network'], sender_data.get('active', 1)
                ))
            self.conn.commit()
            return True
        except Exception as e:
            logger.error(f"Error saving sender: {e}")
            if self.conn:
                self.conn.rollback()
            return False

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
    def get_unsent_tracks(self, limit=100):
        if not self.is_connected():
            self.connect()
        try:
            self.cursor.execute("""
                SELECT time, icao24, callsign, lat, lng, altitude, velocity, heading, squawk
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
                'squawk': r[8]
            } for r in rows]
        except Exception as e:
            logger.error(f"Error fetching unsent tracks: {e}")
            if self.conn:
                self.conn.rollback()
            return []

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

    def get_latest_tracks_since(self, since_time, limit=500):
        if not self.is_connected():
            self.connect()
        try:
            self.cursor.execute("""
                SELECT time, icao24, callsign, lat, lng, altitude, velocity, heading, squawk
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
                'squawk': r[8]
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
                        squawk TEXT,
                        PRIMARY KEY (time, icao24)
                    );
                """)
                conn.commit()
        except Exception as e:
            logger.error(f"Failed to initialize offline database: {e}")
            
    def save_tracks(self, tracks):
        if not tracks:
            return True
        try:
            with sqlite3.connect(self.db_path) as conn:
                cursor = conn.cursor()
                cursor.executemany("""
                    INSERT OR REPLACE INTO offline_tracks (time, icao24, callsign, lat, lng, altitude, velocity, heading, squawk)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?);
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
                        t.get('squawk')
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
                    SELECT time, icao24, callsign, lat, lng, altitude, velocity, heading, squawk
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
                        'squawk': r[8]
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
