from PyQt6.QtCore import QThread
import time
import socket
import json
import queue
import logging
from datetime import datetime, timezone

logger = logging.getLogger("ADSBReceiver.SenderWorker")

def format_sbs(icao, res, timestamp):
    """
    Formats a pyModeS decoded dict 'res' to an SBS BaseStation message string.
    Supports positions, velocities, callsigns, altitudes, and squawks.
    """
    dt = datetime.fromtimestamp(timestamp, timezone.utc)
    date_str = dt.strftime("%Y/%m/%d")
    time_str = dt.strftime("%H:%M:%S.%f")[:-3]  # Milliseconds
    
    icao = icao.upper()
    lines = []
    
    # 1. Position update (Transmission Type 3)
    if "latitude" in res and res["latitude"] is not None:
        lat = res["latitude"]
        lng = res["longitude"]
        alt = res.get("altitude")
        lines.append(f"MSG,3,1,1,{icao},1,{date_str},{time_str},{date_str},{time_str},,{alt if alt is not None else ''},,,{lat:.5f},{lng:.5f},,,,0,0,0,0")
        
    # 2. Velocity update (Transmission Type 4)
    speed = res.get("groundspeed") or res.get("speed")
    heading = res.get("track") or res.get("heading")
    if speed is not None or heading is not None:
        spd = f"{int(speed)}" if speed is not None else ""
        hdg = f"{int(heading)}" if heading is not None else ""
        lines.append(f"MSG,4,1,1,{icao},1,{date_str},{time_str},{date_str},{time_str},,,{spd},{hdg},,,,,,0,0,0,0")
        
    # 3. Identification update (Transmission Type 1)
    if "callsign" in res and res["callsign"]:
        callsign = res["callsign"].strip()
        if callsign:
            lines.append(f"MSG,1,1,1,{icao},1,{date_str},{time_str},{date_str},{time_str},{callsign},,,,,,,,,,0,0,0,0")
            
    # 4. Altitude update (Transmission Type 5) - if altitude present but no position
    if "latitude" not in res and "altitude" in res and res["altitude"] is not None:
        alt = res["altitude"]
        lines.append(f"MSG,5,1,1,{icao},1,{date_str},{time_str},{date_str},{time_str},,,{alt},,,,,,,,0,0,0,0")
        
    # 5. Squawk update (Transmission Type 6)
    if "squawk" in res and res["squawk"]:
        sq = res["squawk"]
        lines.append(f"MSG,6,1,1,{icao},1,{date_str},{time_str},{date_str},{time_str},,,,,,,,{sq},,,,0,0,0,0")
        
    if not lines:
        # Fallback (Transmission Type 8)
        alt = res.get("altitude")
        lines.append(f"MSG,8,1,1,{icao},1,{date_str},{time_str},{date_str},{time_str},,{alt if alt is not None else ''},,,,,,,,0,0,0,0")
        
    return "".join(line + "\r\n" for line in lines)


class SenderWorker(QThread):
    def __init__(self, stop_event, sender_queue, db_client, log_callback=None):
        super().__init__()
        self.stop_event = stop_event
        self.sender_queue = sender_queue
        self.db_client = db_client
        self.log_callback = log_callback
        
        self.total_forwarded = 0
        
        # Sockets management
        self.tcp_connections = {}  # (host, port) -> socket
        self.udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        
        # Config cache
        self.active_senders = []
        self.last_config_check = 0
        self.config_check_interval = 5.0  # Check DB configurations every 5 seconds

    def run(self):
        logger.info("Stream rebroadcaster worker started.")
        if self.log_callback:
            self.log_callback("System", "Rebroadcaster / Forwarder streaming worker started.")

        while not self.stop_event.is_set():
            current_time = time.time()
            
            # 1. Periodically check DB for active senders configurations
            if current_time - self.last_config_check >= self.config_check_interval:
                self.active_senders = self.db_client.get_active_senders()
                self.last_config_check = current_time
                self._prune_unused_tcp_connections()
            
            if not self.active_senders:
                # Idle sleep if no rebroadcasters are active
                self._wait_with_interrupt(1.0)
                continue

            # 2. Get next message from queue
            try:
                item = self.sender_queue.get(timeout=0.2)
            except queue.Empty:
                continue

            raw_msg = item.get('raw_msg')
            icao = item.get('icao')
            decoded = item.get('decoded')
            timestamp = item.get('time', current_time)

            # 3. Rebroadcast to all active senders
            for sender in self.active_senders:
                host = sender['host']
                port = int(sender['port'])
                protocol = sender['network'].lower()
                fmt = sender.get('format', 'SBS').upper()
                
                # Format payload based on configured sender format
                payload = ""
                if fmt == 'AVR':
                    # Append semicolon and standard line ending to raw AVR hex string
                    payload = f"{raw_msg};\r\n"
                elif fmt == 'SBS':
                    payload = format_sbs(icao, decoded, timestamp)
                elif fmt == 'JSON':
                    track_data = {
                        'time': datetime.fromtimestamp(timestamp, timezone.utc).isoformat(),
                        'icao24': icao,
                        'callsign': decoded.get('callsign'),
                        'lat': decoded.get('latitude'),
                        'lng': decoded.get('longitude'),
                        'altitude': decoded.get('altitude'),
                        'velocity': decoded.get('groundspeed') or decoded.get('speed'),
                        'heading': decoded.get('track') or decoded.get('heading'),
                        'squawk': decoded.get('squawk')
                    }
                    payload = json.dumps(track_data) + "\n"
                
                if not payload:
                    continue
                
                # Send payload
                try:
                    if protocol == 'udp':
                        self.udp_socket.sendto(payload.encode('utf-8'), (host, port))
                        self.total_forwarded += 1
                    elif protocol == 'tcp':
                        conn = self._get_tcp_connection(host, port)
                        if conn:
                            conn.sendall(payload.encode('utf-8'))
                            self.total_forwarded += 1
                except Exception as e:
                    logger.error(f"Rebroadcaster: Error sending to {host}:{port} ({protocol}, {fmt}): {e}")
                    if protocol == 'tcp':
                        self._close_tcp_connection(host, port)

            self.sender_queue.task_done()

        # Cleanup connections on stop
        self._close_all_connections()
        self.udp_socket.close()
        logger.info("Stream rebroadcaster worker stopped.")
        if self.log_callback:
            self.log_callback("System", "Rebroadcaster / Forwarder streaming worker stopped.")

    def _get_tcp_connection(self, host, port):
        key = (host, port)
        conn = self.tcp_connections.get(key)
        if conn:
            return conn
            
        try:
            logger.info(f"Rebroadcaster: Connecting TCP client to {host}:{port}...")
            new_conn = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            new_conn.settimeout(2.0)
            new_conn.connect((host, port))
            self.tcp_connections[key] = new_conn
            if self.log_callback:
                self.log_callback("Sender", f"Connected TCP rebroadcaster to {host}:{port}")
            return new_conn
        except Exception as e:
            logger.error(f"Rebroadcaster: Failed to establish TCP connection to {host}:{port}: {e}")
            return None

    def _close_tcp_connection(self, host, port):
        key = (host, port)
        conn = self.tcp_connections.pop(key, None)
        if conn:
            try:
                conn.close()
            except Exception as e:
                logger.debug(f"Failed to close TCP connection to {host}:{port}: {e}")
            if self.log_callback:
                self.log_callback("Error", f"TCP rebroadcaster disconnected from {host}:{port}")

    def _prune_unused_tcp_connections(self):
        """Closes TCP connections that are no longer configured as active senders."""
        active_keys = set((s['host'], int(s['port'])) for s in self.active_senders if s['network'].lower() == 'tcp')
        current_keys = list(self.tcp_connections.keys())
        for key in current_keys:
            if key not in active_keys:
                self._close_tcp_connection(key[0], key[1])

    def _close_all_connections(self):
        for key in list(self.tcp_connections.keys()):
            self._close_tcp_connection(key[0], key[1])

    def _wait_with_interrupt(self, duration_sec):
        steps = int(duration_sec * 10)
        for _ in range(steps):
            if self.stop_event.is_set():
                break
            self.msleep(100)

    def get_stats(self):
        return {
            "total_forwarded": self.total_forwarded
        }
