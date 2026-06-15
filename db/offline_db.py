import sqlite3
import os
import logging
from datetime import datetime

logger = logging.getLogger("ADSBReceiver.DB")

class OfflineDatabase:
    def __init__(self, db_path=None):
        if db_path is None:
            # Save in the parent directory (root of adsb_receiver) for backward compatibility
            db_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "offline_buffer.db")
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

    def get_db_file_size(self):
        try:
            if os.path.exists(self.db_path):
                size_bytes = os.path.getsize(self.db_path)
                if size_bytes < 1024:
                    return f"{size_bytes} B"
                elif size_bytes < 1024 * 1024:
                    return f"{size_bytes / 1024:.1f} KB"
                else:
                    return f"{size_bytes / (1024 * 1024):.1f} MB"
            return "0 B"
        except Exception:
            return "N/A"

