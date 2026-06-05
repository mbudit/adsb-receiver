import socket
import threading
import queue
import time
import logging

logger = logging.getLogger("ADSBReceiver.Receiver")

class SDRReceiver(threading.Thread):
    def __init__(self, host, port, output_queue):
        """
        Background thread that connects to dump1090/SDR TCP port (typically 30002)
        and listens for raw AVR hex strings starting with '*' and ending with ';'.
        """
        super().__init__()
        self.host = host
        self.port = port
        self.queue = output_queue
        self.running = False
        self.connected = False
        self.daemon = True
        self.socket = None
        self.status_callback = None  # Callback function: f(connected: bool, message: str)

    def set_status_callback(self, callback):
        self.status_callback = callback

    def run(self):
        self.running = True
        buffer = ""
        while self.running:
            try:
                logger.info(f"Connecting to SDR TCP stream at {self.host}:{self.port}...")
                if self.status_callback:
                    self.status_callback(False, f"Connecting to {self.host}:{self.port}...")

                self.socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                self.socket.settimeout(5.0)
                self.socket.connect((self.host, self.port))
                
                self.connected = True
                logger.info("Connected to SDR TCP stream.")
                if self.status_callback:
                    self.status_callback(True, f"Connected to {self.host}:{self.port}")
                
                while self.running:
                    try:
                        data = self.socket.recv(4096)
                        if not data:
                            logger.warning("SDR stream connection closed by remote host.")
                            break
                        
                        buffer += data.decode("utf-8", errors="ignore")
                        
                        # Process buffer and split messages by semicolon
                        while ";" in buffer:
                            parts = buffer.split(";", 1)
                            msg = parts[0].strip()
                            buffer = parts[1]
                            
                            # Valid AVR message format starts with *
                            if msg.startswith("*"):
                                self.queue.put(msg)
                    except socket.timeout:
                        # Timeout is normal, loop again to check running state
                        continue
                            
            except (ConnectionRefusedError, socket.error) as e:
                self.connected = False
                err_msg = f"Connection error: {e}"
                logger.error(f"{err_msg}. Retrying in 5 seconds...")
                if self.status_callback:
                    self.status_callback(False, f"Offline (retry in 5s): {e}")
                time.sleep(5.0)
            except Exception as e:
                self.connected = False
                logger.error(f"Unexpected receiver error: {e}")
                if self.status_callback:
                    self.status_callback(False, f"Error: {e}")
                time.sleep(5.0)
            finally:
                if self.socket:
                    try:
                        self.socket.close()
                    except Exception:
                        pass
                    self.socket = None
                self.connected = False

    def stop(self):
        self.running = False
        self.connected = False
        if self.socket:
            try:
                self.socket.shutdown(socket.SHUT_RDWR)
                self.socket.close()
            except Exception:
                pass
            self.socket = None
        logger.info("Receiver stop requested.")
        if self.status_callback:
            self.status_callback(False, "Stopped")
class MockReceiver(threading.Thread):
    def __init__(self, log_file_path, output_queue, speed_multiplier=1.0):
        """
        Mock receiver for testing without an active SDR.
        Reads messages from a log file and pushes them at a simulated real-time rate.
        """
        super().__init__()
        self.log_file_path = log_file_path
        self.queue = output_queue
        self.running = False
        self.connected = False
        self.daemon = True
        self.speed_multiplier = speed_multiplier
        self.status_callback = None

    def set_status_callback(self, callback):
        self.status_callback = callback

    def run(self):
        self.running = True
        self.connected = True
        logger.info(f"Starting Mock Receiver reading from {self.log_file_path}...")
        if self.status_callback:
            self.status_callback(True, f"Mocking from file: {self.log_file_path}")

        try:
            with open(self.log_file_path, "r") as f:
                while self.running:
                    line = f.readline()
                    if not line:
                        logger.info("Mock Receiver reached end of log file. Restarting...")
                        f.seek(0)
                        continue
                    
                    line = line.strip()
                    if line.startswith("*") and line.endswith(";"):
                        self.queue.put(line)
                        # Simulate delay between messages (approx 10-20 ms)
                        time.sleep(0.01 / self.speed_multiplier)
        except Exception as e:
            logger.error(f"Mock receiver error: {e}")
            if self.status_callback:
                self.status_callback(False, f"Mock Error: {e}")
        finally:
            self.connected = False
            logger.info("Mock Receiver stopped.")
            if self.status_callback:
                self.status_callback(False, "Stopped")

    def stop(self):
        self.running = False
        logger.info("Mock Receiver stop requested.")
