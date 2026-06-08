from PyQt6.QtCore import QThread
import queue
import time
import logging
from datetime import datetime
from pyModeS import PipeDecoder
from db import OfflineDatabase

logger = logging.getLogger("ADSBReceiver.Decoder")

class ADSBDecoder(QThread):
    def __init__(self, stop_event, input_queue, db_client, batch_interval=60):
        """
        Background QThread that consumes raw hex messages from input_queue,
        decodes them using pyModeS PipeDecoder, buffers track points,
        and batches inserts to the database every batch_interval seconds.
        """
        super().__init__()
        self.stop_event = stop_event
        self.input_queue = input_queue
        self.db_client = db_client
        self.batch_interval = batch_interval
        
        # Local offline database buffer
        self.offline_db = OfflineDatabase()
        
        # State tracking
        self.pipe = PipeDecoder()
        self.batch_buffer = []
        self.last_flush_time = time.time()
        self.last_gc_time = time.time()
        self.gc_interval = 30  # Check every 30s
        self.state_ttl = 60  # Expire states if no messages for 60s
        self.aircraft_states = {} # icao -> {callsign, altitude, velocity, heading, squawk, last_seen}
        
        # Live Stats (thread-safe updates)
        import threading
        self.stats_lock = threading.Lock()
        self.stats = {
            "total_msgs": 0,
            "decoded_positions": 0,
            "decoded_callsigns": 0,
            "decoded_velocities": 0,
            "active_aircraft": set(),
            "last_aircraft_seen": None,
            "db_saves": 0,
            "batch_size": 0
        }
        
        # Callbacks for GUI
        self.gui_update_callback = None
        self.log_callback = None

    def set_gui_callback(self, callback):
        self.gui_update_callback = callback

    def set_log_callback(self, callback):
        self.log_callback = callback

    def get_stats(self):
        with self.stats_lock:
            # Return copy of stats
            stats_copy = self.stats.copy()
            stats_copy["active_aircraft_count"] = len(self.stats["active_aircraft"])
            return stats_copy

    def run(self):
        logger.info("ADSB Decoder thread started.")
        if self.log_callback:
            self.log_callback("System", "ADSB Decoder thread started.")
            
        while not self.stop_event.is_set():
            try:
                # Read from queue with a timeout to check stop_event
                try:
                    raw_msg = self.input_queue.get(timeout=0.5)
                except queue.Empty:
                    raw_msg = None

                current_time = time.time()
                
                if raw_msg:
                    # Clean and decode message
                    msg = raw_msg.replace("*", "").replace(";", "").strip()
                    res = self.pipe.decode(msg, timestamp=current_time)
                    
                    if res and res.get("icao"):
                        icao = res["icao"]
                        
                        # Ensure ICAO state tracking exists
                        if icao not in self.aircraft_states:
                            self.aircraft_states[icao] = {
                                "callsign": None,
                                "altitude": None,
                                "velocity": None,
                                "heading": None,
                                "squawk": None,
                                "last_seen": current_time
                            }
                        state = self.aircraft_states[icao]
                        state["last_seen"] = current_time
                        
                        # Update Statistics
                        with self.stats_lock:
                            self.stats["total_msgs"] += 1
                            self.stats["active_aircraft"].add(icao)
                            self.stats["last_aircraft_seen"] = icao
                        
                        # Cache callsign
                        if "callsign" in res and res["callsign"]:
                            c = res["callsign"].strip()
                            if c:
                                state["callsign"] = c
                                with self.stats_lock:
                                    self.stats["decoded_callsigns"] += 1
                                if self.log_callback:
                                    self.log_callback(icao, f"Callsign updated: {c}")
                        
                        # Cache altitude
                        if "altitude" in res and res["altitude"] is not None:
                            state["altitude"] = res["altitude"]
                                
                        # Cache velocity
                        speed = res.get("groundspeed") or res.get("speed")
                        if speed is not None:
                            state["velocity"] = speed
                            with self.stats_lock:
                                self.stats["decoded_velocities"] += 1
                                
                        # Cache heading
                        heading = res.get("track") or res.get("heading")
                        if heading is not None:
                            state["heading"] = heading
                            
                        # Cache squawk
                        if "squawk" in res and res["squawk"]:
                            state["squawk"] = res["squawk"]
                                
                        # We capture a track point when a full position (lat/lng) is resolved
                        if "latitude" in res and res["latitude"] is not None:
                            with self.stats_lock:
                                self.stats["decoded_positions"] += 1
                                
                            track_point = {
                                "time": datetime.fromtimestamp(current_time),
                                "icao24": icao,
                                "callsign": state["callsign"],
                                "lat": res["latitude"],
                                "lng": res["longitude"],
                                "altitude": res.get("altitude") if res.get("altitude") is not None else state["altitude"],
                                "velocity": state["velocity"],
                                "heading": state["heading"],
                                "squawk": state["squawk"]
                            }
                            
                            self.batch_buffer.append(track_point)
                            
                            with self.stats_lock:
                                self.stats["batch_size"] = len(self.batch_buffer)
                                
                            if self.log_callback:
                                self.log_callback(
                                    icao, 
                                    f"Position: {track_point['lat']:.4f}, {track_point['lng']:.4f} | Alt: {track_point['altitude'] or 'N/A'} ft"
                                )
                                
                    self.input_queue.task_done()
                
                # Check if it's time to flush the batch to the database
                if current_time - self.last_flush_time >= self.batch_interval:
                    self._flush_batch()
                    
                # Check if it's time to run stale state GC
                if current_time - self.last_gc_time >= self.gc_interval:
                    self._run_state_gc(current_time)
                    
            except Exception as e:
                logger.error(f"Error in decoder thread: {e}")
                if self.log_callback:
                    self.log_callback("Error", f"Decoder Exception: {e}")
                    
        # Flush any remaining items in buffer before exiting
        if self.batch_buffer:
            self._flush_batch()
            
        logger.info("ADSB Decoder thread stopped.")
        if self.log_callback:
            self.log_callback("System", "ADSB Decoder thread stopped.")

    def _flush_batch(self):
        """Flushes buffered track points to the database, falling back to local SQLite if offline."""
        points_to_save = list(self.batch_buffer)
        self.batch_buffer.clear()
        self.last_flush_time = time.time()
        
        with self.stats_lock:
            self.stats["batch_size"] = 0

        if not points_to_save:
            return

        logger.info(f"Triggering database batch insert of {len(points_to_save)} points...")
        if self.log_callback:
            self.log_callback("Database", f"Saving batch of {len(points_to_save)} track points...")
            
        success = self.db_client.insert_tracks_batch(points_to_save)
        
        if success:
            with self.stats_lock:
                self.stats["db_saves"] += len(points_to_save)
            if self.log_callback:
                self.log_callback("Database", f"Saved {len(points_to_save)} track points successfully.")
        else:
            logger.warning("Main database offline. Buffering tracks to local SQLite...")
            offline_success = self.offline_db.save_tracks(points_to_save)
            if offline_success:
                if self.log_callback:
                    self.log_callback("Database", f"Database offline. Buffered {len(points_to_save)} tracks locally.")
            else:
                if self.log_callback:
                    self.log_callback("Error", f"Failed to save {len(points_to_save)} tracks to local buffer.")

    def _run_state_gc(self, current_time):
        """Removes aircraft states that haven't been updated for state_ttl seconds."""
        stale_icaos = []
        for icao, state in list(self.aircraft_states.items()):
            last_seen = state.get("last_seen", 0)
            if current_time - last_seen > self.state_ttl:
                stale_icaos.append(icao)
                
        if stale_icaos:
            for icao in stale_icaos:
                self.aircraft_states.pop(icao, None)
                
            with self.stats_lock:
                self.stats["active_aircraft"].difference_update(stale_icaos)
                
            logger.info(f"Decoder GC: Cleaned up {len(stale_icaos)} inactive aircraft from cache.")
            if self.log_callback:
                self.log_callback("System", f"Garbage Collector: Removed {len(stale_icaos)} inactive aircraft from cache.")
                
        self.last_gc_time = current_time

    def stop(self):
        self.stop_event.set()
        logger.info("Decoder stop requested.")
