from PyQt6.QtCore import QThread
import time
import socket
import json
import logging
from datetime import datetime, timezone

logger = logging.getLogger("ADSBReceiver.SenderWorker")

class SenderWorker(QThread):
    def __init__(self, stop_event, db_client, log_callback=None):
        super().__init__()
        self.stop_event = stop_event
        self.db_client = db_client
        self.log_callback = log_callback
        
        # Initialize last_send_time to current time (UTC)
        self.last_send_time = datetime.now(timezone.utc)
        self.total_forwarded = 0

    def run(self):
        logger.info("Sender worker started.")
        if self.log_callback:
            self.log_callback("System", "Sender / Rebroadcaster worker started.")

        # UDP Socket (reusable)
        udp_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)

        while not self.stop_event.is_set():
            try:
                # 1. Fetch active sender configurations
                active_senders = self.db_client.get_active_senders()
                
                if not active_senders:
                    # No active senders, wait and loop
                    self._wait_with_interrupt(5.0)
                    continue

                # 2. Get new tracks since last run
                new_tracks = self.db_client.get_latest_tracks_since(self.last_send_time, limit=200)
                
                if not new_tracks:
                    self._wait_with_interrupt(1.0)
                    continue

                logger.info(f"Sender: Found {len(new_tracks)} new tracks to forward.")
                
                # Group messages to send
                messages_to_send = []
                max_time = self.last_send_time
                for track in new_tracks:
                    # Keep track of the latest record timestamp
                    track_time = track['time']
                    if track_time.tzinfo is None:
                        # Ensure timezone awareness
                        track_time = track_time.replace(tzinfo=timezone.utc)
                    if track_time > max_time:
                        max_time = track_time

                    # Create JSON payload
                    track_data = {
                        'time': track['time'].isoformat() if hasattr(track['time'], 'isoformat') else str(track['time']),
                        'icao24': track['icao24'],
                        'callsign': track['callsign'],
                        'lat': track['lat'],
                        'lng': track['lng'],
                        'altitude': track['altitude'],
                        'velocity': track['velocity'],
                        'heading': track['heading'],
                        'squawk': track['squawk']
                    }
                    messages_to_send.append(json.dumps(track_data) + "\n")

                # 3. Rebroadcast to each active destination
                for sender in active_senders:
                    host = sender['host']
                    port = int(sender['port'])
                    protocol = sender['network'].lower()

                    count = 0
                    try:
                        if protocol == 'udp':
                            for msg in messages_to_send:
                                udp_socket.sendto(msg.encode('utf-8'), (host, port))
                                count += 1
                        elif protocol == 'tcp':
                            # Connect once for the batch
                            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as tcp_socket:
                                tcp_socket.settimeout(3.0)
                                tcp_socket.connect((host, port))
                                for msg in messages_to_send:
                                    tcp_socket.sendall(msg.encode('utf-8'))
                                    count += 1
                        
                        # Update sender last send time in database
                        self.db_client.update_sender_time(sender['id'], max_time)
                        logger.info(f"Sender: Forwarded {count} tracks to {host}:{port} ({protocol})")
                        self.total_forwarded += count
                    except Exception as send_ex:
                        logger.error(f"Sender: Failed sending to {host}:{port} via {protocol}: {send_ex}")
                        if self.log_callback:
                            self.log_callback("Error", f"Sender failed to {host}:{port}: {send_ex}")

                # Update local watermark
                self.last_send_time = max_time

                # Brief sleep
                self._wait_with_interrupt(1.0)

            except Exception as e:
                logger.error(f"Unexpected error in sender worker: {e}")
                if self.log_callback:
                    self.log_callback("Error", f"Sender Exception: {e}")
                self._wait_with_interrupt(5.0)

        udp_socket.close()
        logger.info("Sender worker stopped.")
        if self.log_callback:
            self.log_callback("System", "Sender / Rebroadcaster worker stopped.")

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
