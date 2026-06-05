import psycopg2
from psycopg2.extras import execute_values
import logging
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
        """Checks if the aircraft_tracks table exists. If not, it creates it."""
        try:
            # We check if it exists first.
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
                        PRIMARY KEY (time, icao24)
                    );
                """)
                # Try to create hypertable if TimescaleDB extension is active
                try:
                    self.cursor.execute("SELECT create_hypertable('aircraft_tracks', 'time', if_not_exists => TRUE);")
                    logger.info("Created TimescaleDB hypertable for aircraft_tracks.")
                except Exception as ex:
                    # TimescaleDB might not be active, which is fine, we just fall back to standard postgres table
                    logger.info("Created standard PostgreSQL table (TimescaleDB extension not active/available).")
                self.conn.commit()
            else:
                logger.info("Table 'aircraft_tracks' verified and ready.")
        except Exception as e:
            self.conn.rollback()
            logger.error(f"Error verifying or creating table: {e}")

    def insert_tracks_batch(self, tracks):
        """
        Inserts a list of track updates.
        tracks should be a list of dicts with keys:
        - time (datetime)
        - icao24 (str)
        - callsign (str or None)
        - lat (float)
        - lng (float)
        - altitude (float or None)
        - velocity (float or None)
        - heading (float or None)
        - squawk (str or None)
        """
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
