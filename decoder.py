from PyQt6.QtCore import QThread
import queue
import time
import logging
import math
import threading
from datetime import datetime
import pyModeS as pms
from pyModeS import PipeDecoder
from db import OfflineDatabase
import icao_ranges

logger = logging.getLogger("ADSBReceiver.Decoder")

class ADSBDecoder(QThread):
    def __init__(self, stop_event, input_queue, sender_queue, db_client, batch_interval=60, antenna_coords=None, max_range_km=500.0, enable_db=True):
        """
        Background QThread that consumes raw hex messages from input_queue,
        decodes them using pyModeS PipeDecoder, buffers track points,
        and batches inserts to the database every batch_interval seconds.
        """
        super().__init__()
        self.stop_event = stop_event
        self.input_queue = input_queue
        self.sender_queue = sender_queue
        self.db_client = db_client
        self.batch_interval = batch_interval
        self.antenna_coords = antenna_coords
        self.max_range_km = max_range_km
        self.enable_db = enable_db
        
        # Local offline database buffer
        self.offline_db = OfflineDatabase()
        
        # State tracking
        self.pipe = PipeDecoder()
        self.batch_buffer = []
        self.last_flush_time = time.time()
        self.last_gc_time = time.time()
        self.gc_interval = 30  # Check every 30s
        self.state_ttl = 60  # Expire states if no messages for 60s
        self.state_lock = threading.Lock()
        self.aircraft_states = {} # icao -> state dict
        
        # Live Stats (thread-safe updates)
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
                        
                        # Local CPR fallback decoding if global CPR is not ready but coordinates exist raw
                        if 'cpr_lat' in res and 'latitude' not in res and self.antenna_coords:
                            ref_lat, ref_lon = self.antenna_coords
                            tc = res.get('typecode')
                            try:
                                decoded_pos = None
                                # Surface CPR decoding (typecode 5-8)
                                if tc in [5, 6, 7, 8]:
                                    decoded_pos = pms.decode(msg, surface_ref=(ref_lat, ref_lon))
                                # Airborne CPR decoding (typecode 9-18, 20-22)
                                elif tc in list(range(9, 19)) + [20, 21, 22]:
                                    decoded_pos = pms.decode(msg, reference=(ref_lat, ref_lon))
                                
                                if decoded_pos and 'latitude' in decoded_pos and 'longitude' in decoded_pos:
                                    res['latitude'] = decoded_pos['latitude']
                                    res['longitude'] = decoded_pos['longitude']
                                    logger.debug(f"Decoder: CPR locally decoded {icao} using reference: "
                                                 f"({res['latitude']:.4f}, {res['longitude']:.4f})")
                            except Exception as e:
                                logger.debug(f"Decoder: Local CPR fallback failed for {icao}: {e}")

                        # CPR Calibration & Range Validation Check
                        if 'latitude' in res and res['latitude'] is not None and self.antenna_coords:
                            lat = res['latitude']
                            lng = res['longitude']
                            ref_lat, ref_lon = self.antenna_coords
                            dist_km = self._haversine(ref_lat, ref_lon, lat, lng)
                            
                            max_limit = self.max_range_km or 500.0
                            if dist_km > max_limit:
                                logger.warning(
                                    f"CPR Calibration Alert: Aircraft {icao} position ({lat:.4f}, {lng:.4f}) "
                                    f"exceeds max range ({dist_km:.1f} km > {max_limit} km). Discarding position."
                                )
                                if self.log_callback:
                                    self.log_callback(
                                        "System",
                                        f"CPR Calibration: Purged position for {icao} ({dist_km:.1f} km away)"
                                    )
                                res.pop('latitude', None)
                                res.pop('longitude', None)
                        
                        # Update Statistics
                        with self.stats_lock:
                            self.stats["total_msgs"] += 1
                            self.stats["active_aircraft"].add(icao)
                            self.stats["last_aircraft_seen"] = icao
                            
                        # Stream to sender queue if connected
                        if self.sender_queue is not None:
                            self.sender_queue.put({
                                'raw_msg': raw_msg,
                                'icao': icao,
                                'decoded': res,
                                'time': current_time
                            })

                        tp_callsign = None
                        tp_altitude = None
                        tp_velocity = None
                        tp_heading = None
                        tp_squawk = None

                        with self.state_lock:
                            # Ensure ICAO state tracking exists
                            if icao not in self.aircraft_states:
                                country_info = icao_ranges.find_icao_range(icao)
                                self.aircraft_states[icao] = {
                                    "icao": icao,
                                    "callsign": None,
                                    "altitude": None,
                                    "velocity": None,
                                    "heading": None,
                                    "squawk": None,
                                    "lat": None,
                                    "lng": None,
                                    "vertical_rate": None,
                                    "messages": 0,
                                    "distance": None,
                                    "country": country_info["country"],
                                    "country_code": country_info["country_code"],
                                    "last_seen": current_time
                                }
                            state = self.aircraft_states[icao]
                            state["last_seen"] = current_time
                            state["messages"] += 1
                            
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
                                
                            # Cache vertical rate
                            vr = res.get("vertical_rate")
                            if vr is not None:
                                state["vertical_rate"] = vr
                                
                            # Cache squawk
                            if "squawk" in res and res["squawk"]:
                                state["squawk"] = res["squawk"]

                            # Cache lat/lng if present
                            if "latitude" in res and res["latitude"] is not None:
                                state["lat"] = res["latitude"]
                                state["lng"] = res["longitude"]
                                if self.antenna_coords:
                                    ref_lat, ref_lon = self.antenna_coords
                                    dist_km = self._haversine(ref_lat, ref_lon, state["lat"], state["lng"])
                                    state["distance"] = round(dist_km * 0.539957, 1)

                            tp_callsign = state["callsign"]
                            tp_altitude = res.get("altitude") if res.get("altitude") is not None else state["altitude"]
                            tp_velocity = state["velocity"]
                            tp_heading = state["heading"]
                            tp_squawk = state["squawk"]
                            tp_vertical_rate = state["vertical_rate"]
                            tp_distance = state["distance"]

                        # We capture a track point when a full position (lat/lng) is resolved
                        if "latitude" in res and res["latitude"] is not None:
                            with self.stats_lock:
                                self.stats["decoded_positions"] += 1
                                
                            track_point = {
                                "time": datetime.fromtimestamp(current_time),
                                "icao24": icao,
                                "callsign": tp_callsign,
                                "lat": res["latitude"],
                                "lng": res["longitude"],
                                "altitude": tp_altitude,
                                "velocity": tp_velocity,
                                "heading": tp_heading,
                                "squawk": tp_squawk,
                                "vertical_rate": tp_vertical_rate,
                                "distance": tp_distance
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

        if not self.enable_db:
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

    def _haversine(self, lat1, lon1, lat2, lon2):
        """Calculates Great-Circle distance in kilometers between two coordinates."""
        R = 6371.0  # Earth radius in km
        d_lat = math.radians(lat2 - lat1)
        d_lon = math.radians(lon2 - lon1)
        a = (math.sin(d_lat / 2.0) ** 2 +
             math.cos(math.radians(lat1)) * math.cos(math.radians(lat2)) * (math.sin(d_lon / 2.0) ** 2))
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return R * c

    def _run_state_gc(self, current_time):
        """Removes aircraft states that haven't been updated for state_ttl seconds."""
        stale_icaos = []
        with self.state_lock:
            for icao, state in list(self.aircraft_states.items()):
                last_seen = state.get("last_seen", 0)
                if current_time - last_seen > self.state_ttl:
                    stale_icaos.append(icao)
                    
            if stale_icaos:
                for icao in stale_icaos:
                    self.aircraft_states.pop(icao, None)
                
        if stale_icaos:
            with self.stats_lock:
                self.stats["active_aircraft"].difference_update(stale_icaos)
                
            logger.info(f"Decoder GC: Cleaned up {len(stale_icaos)} inactive aircraft from cache.")
            if self.log_callback:
                self.log_callback("System", f"Garbage Collector: Removed {len(stale_icaos)} inactive aircraft from cache.")
                
        self.last_gc_time = current_time

    def get_aircraft_states(self):
        """Returns a thread-safe deep copy of the active aircraft states."""
        import copy
        with self.state_lock:
            return copy.deepcopy(self.aircraft_states)

    def stop(self):
        self.stop_event.set()
        logger.info("Decoder stop requested.")
