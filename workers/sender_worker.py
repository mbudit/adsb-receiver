from PyQt6.QtCore import QThread
import time
import socket
import json
import queue
import logging
from datetime import datetime, timezone

logger = logging.getLogger("ADSBReceiver.SenderWorker")

# SBS-1 (BaseStation) field layout. A record is exactly 22 comma-separated
# fields; naming the indices is what keeps the trailing run of empty columns
# countable. The previous hand-written f-strings were one field long and put
# the alert/emergency/spi/is_on_ground flags at 19-22 instead of 18-21 — the
# columns downstream actually reads (altitude, speed, track, lat, lng, squawk)
# happened to be correct, so nothing caught it.
SBS_FIELD_COUNT = 22
IDX_CALLSIGN = 10
IDX_ALTITUDE = 11
IDX_GROUND_SPEED = 12
IDX_TRACK = 13
IDX_LATITUDE = 14
IDX_LONGITUDE = 15
IDX_VERTICAL_RATE = 16
IDX_SQUAWK = 17
IDX_ALERT = 18
IDX_EMERGENCY = 19
IDX_SPI = 20
IDX_IS_ON_GROUND = 21


def _sbs_line(transmission_type, icao, date_str, time_str, values=None):
    """
    Builds one SBS-1 record. `values` maps field index to value; None and
    missing indices are emitted as empty columns.
    """
    parts = [""] * SBS_FIELD_COUNT
    parts[0] = "MSG"
    parts[1] = str(transmission_type)
    parts[2] = "1"                      # session_id
    parts[3] = "1"                      # aircraft_id
    parts[4] = icao
    parts[5] = "1"                      # flight_id
    parts[6] = date_str
    parts[7] = time_str
    parts[8] = date_str
    parts[9] = time_str

    # Emitted as 0 rather than blank, matching BaseStation. These are not
    # decoded yet — is_on_ground in particular is always 0, not observed.
    parts[IDX_ALERT] = "0"
    parts[IDX_EMERGENCY] = "0"
    parts[IDX_SPI] = "0"
    parts[IDX_IS_ON_GROUND] = "0"

    for index, value in (values or {}).items():
        parts[index] = "" if value is None else str(value)

    return ",".join(parts)


def format_sbs(icao, res, timestamp):
    """
    Formats a pyModeS decoded dict 'res' to an SBS BaseStation message string.
    Supports positions, velocities, callsigns, altitudes, squawks and vertical
    rate.
    """
    dt = datetime.fromtimestamp(timestamp, timezone.utc)
    date_str = dt.strftime("%Y/%m/%d")
    time_str = dt.strftime("%H:%M:%S.%f")[:-3]  # Milliseconds

    icao = icao.upper()
    lines = []

    # 1. Position update (Transmission Type 3)
    if "latitude" in res and res["latitude"] is not None:
        alt = res.get("altitude")
        lines.append(_sbs_line(3, icao, date_str, time_str, {
            IDX_ALTITUDE: alt,
            IDX_LATITUDE: f"{res['latitude']:.5f}",
            IDX_LONGITUDE: f"{res['longitude']:.5f}",
        }))

    # 2. Velocity update (Transmission Type 4)
    #
    # Vertical rate rides here and nowhere else: pyModeS decodes it from the
    # same ADS-B velocity message (TC=19) as speed and track, and MSG,4 is the
    # only BaseStation type with a vertical_rate column. Omitting it used to
    # strand the value in the decoder — the receiver's own database writes had
    # it, the rebroadcast feed never did.
    speed = res.get("groundspeed") or res.get("speed")
    heading = res.get("track") or res.get("heading")
    vertical_rate = res.get("vertical_rate")
    if speed is not None or heading is not None or vertical_rate is not None:
        lines.append(_sbs_line(4, icao, date_str, time_str, {
            IDX_GROUND_SPEED: int(speed) if speed is not None else None,
            IDX_TRACK: int(heading) if heading is not None else None,
            IDX_VERTICAL_RATE: int(vertical_rate) if vertical_rate is not None else None,
        }))

    # 3. Identification update (Transmission Type 1)
    if "callsign" in res and res["callsign"]:
        callsign = res["callsign"].strip()
        if callsign:
            lines.append(_sbs_line(1, icao, date_str, time_str, {
                IDX_CALLSIGN: callsign,
            }))

    # 4. Altitude update (Transmission Type 5) - if altitude present but no position
    if "latitude" not in res and "altitude" in res and res["altitude"] is not None:
        lines.append(_sbs_line(5, icao, date_str, time_str, {
            IDX_ALTITUDE: res["altitude"],
        }))

    # 5. Squawk update (Transmission Type 6)
    if "squawk" in res and res["squawk"]:
        lines.append(_sbs_line(6, icao, date_str, time_str, {
            IDX_SQUAWK: res["squawk"],
        }))

    if not lines:
        # Fallback (Transmission Type 8)
        lines.append(_sbs_line(8, icao, date_str, time_str, {
            IDX_ALTITUDE: res.get("altitude"),
        }))

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
