from PyQt6.QtCore import QThread
import time
import logging
from datetime import datetime
from db import OfflineDatabase

logger = logging.getLogger("ADSBReceiver.UploaderWorker")

class UploaderWorker(QThread):
    def __init__(self, stop_event, db_client, batch_size=100, poll_interval=10, log_callback=None):
        super().__init__()
        self.stop_event = stop_event
        self.db_client = db_client
        self.batch_size = batch_size
        self.poll_interval = poll_interval
        self.log_callback = log_callback
        
        # Local offline database
        self.offline_db = OfflineDatabase()
        
        # Stats
        self.total_synced = 0
        self.pending_count = 0

    def run(self):
        logger.info("Sync uploader worker started.")
        if self.log_callback:
            self.log_callback("Database", "Offline Sync / Uploader worker started.")

        while not self.stop_event.is_set():
            try:
                # 1. Update pending count for GUI
                self.pending_count = self.offline_db.get_pending_count()

                if self.pending_count == 0:
                    # Nothing to sync, wait and loop
                    self._wait_with_interrupt(self.poll_interval)
                    continue

                logger.info(f"Sync: Found {self.pending_count} buffered tracks locally.")
                
                # 2. Check if main PostgreSQL is online
                is_online = self.db_client.is_connected()
                if not is_online:
                    # Attempt connection reconnect
                    logger.info("Sync: Main database is offline. Attempting to reconnect...")
                    is_online = self.db_client.connect()

                if not is_online:
                    # Still offline, wait and try again next loop
                    logger.info("Sync: Main database connection attempt failed. Staying offline.")
                    self._wait_with_interrupt(30.0) # Backoff
                    continue

                # 3. If online, fetch a batch of tracks to sync
                tracks_to_sync = self.offline_db.get_unsent_tracks(limit=self.batch_size)
                if not tracks_to_sync:
                    self._wait_with_interrupt(self.poll_interval)
                    continue

                logger.info(f"Sync: Uploading {len(tracks_to_sync)} tracks to main database...")
                if self.log_callback:
                    self.log_callback("Database", f"Syncing {len(tracks_to_sync)} tracks from offline buffer to database...")

                # 4. Upload to main PostgreSQL DB
                success = self.db_client.insert_tracks_batch(tracks_to_sync)

                if success:
                    # 5. On success, delete those records from the local SQLite buffer
                    keys_to_delete = [(t['time'], t['icao24']) for t in tracks_to_sync]
                    self.offline_db.delete_tracks(keys_to_delete)
                    
                    self.total_synced += len(tracks_to_sync)
                    self.pending_count = self.offline_db.get_pending_count()
                    
                    logger.info(f"Sync: Successfully uploaded {len(tracks_to_sync)} records. {self.pending_count} remaining.")
                    if self.log_callback:
                        self.log_callback("Database", f"Successfully synced {len(tracks_to_sync)} tracks. {self.pending_count} remaining in buffer.")
                else:
                    logger.error("Sync: Failed to save batch to main database. Will retry.")
                    if self.log_callback:
                        self.log_callback("Error", "Sync: PostgreSQL save failed. Local records retained.")
                    self._wait_with_interrupt(10.0)

                # Brief pause between batches
                self._wait_with_interrupt(2.0)

            except Exception as e:
                logger.error(f"Unexpected error in uploader/sync worker: {e}")
                if self.log_callback:
                    self.log_callback("Error", f"Sync Worker Exception: {e}")
                self._wait_with_interrupt(self.poll_interval)

        logger.info("Sync uploader worker stopped.")
        if self.log_callback:
            self.log_callback("Database", "Offline Sync / Uploader worker stopped.")

    def _wait_with_interrupt(self, duration_sec):
        steps = int(duration_sec * 10)
        for _ in range(steps):
            if self.stop_event.is_set():
                break
            self.msleep(100)

    def get_stats(self):
        return {
            "total_sent": self.total_synced,
            "pending_upload_count": self.pending_count
        }
