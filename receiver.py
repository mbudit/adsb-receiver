import socket
import threading
import queue
import time
import logging

try:
    import serial
except ImportError:
    serial = None

logger = logging.getLogger("ADSBReceiver.Receiver")

class SDRReceiver(threading.Thread):
    def __init__(self, host, port, output_queue):
        """
        Background thread that connects to dump1090/SDR TCP port (typically 30002)
        and listens for raw AVR hex strings starting with '*' and ending with ';'.
        This remains for backwards compatibility and single SDR client connections.
        """
        super().__init__()
        self.host = host
        self.port = port
        self.queue = output_queue
        self.running = False
        self.connected = False
        self.daemon = True
        self.socket = None
        self.status_callback = None

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


# --- Multi-Protocol Receiver Helper Loops ---

def receive_avr_tcp_client(host, port, stop_event, output_queue, log_callback=None):
    """Connects to a remote TCP server supplying AVR messages."""
    buffer = ""
    if log_callback:
        log_callback("Receiver", f"TCP Client: connecting to {host}:{port}...")

    while not stop_event.is_set():
        try:
            with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
                sock.settimeout(5.0)
                sock.connect((host, port))
                if log_callback:
                    log_callback("Receiver", f"TCP Client: connected to {host}:{port}")

                while not stop_event.is_set():
                    try:
                        data = sock.recv(4096)
                        if not data:
                            if log_callback:
                                log_callback("Receiver", "TCP Client: Connection closed by remote host")
                            break
                        
                        buffer += data.decode("utf-8", errors="ignore")
                        while ";" in buffer:
                            parts = buffer.split(";", 1)
                            msg = parts[0].strip()
                            buffer = parts[1]
                            if msg.startswith("*"):
                                output_queue.put(msg)
                    except socket.timeout:
                        continue
        except Exception as e:
            if log_callback:
                log_callback("Receiver", f"TCP Client error to {host}:{port}: {e}. Retrying in 5s...")
            # Wait with interrupt
            for _ in range(50):
                if stop_event.is_set():
                    break
                time.sleep(0.1)


def receive_avr_tcp_server(host, port, stop_event, output_queue, log_callback=None):
    """Binds to a port acting as a TCP server waiting for client AVR feeds."""
    if log_callback:
        log_callback("Receiver", f"TCP Server: listening on {host}:{port}...")

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            sock.listen(5)
            sock.settimeout(1.0)

            while not stop_event.is_set():
                try:
                    conn, addr = sock.accept()
                    if log_callback:
                        log_callback("Receiver", f"TCP Server: client connected from {addr[0]}:{addr[1]}")
                    
                    # Spawn client reader thread
                    client_thread = threading.Thread(
                        target=_read_tcp_client,
                        args=(conn, stop_event, output_queue, log_callback),
                        daemon=True
                    )
                    client_thread.start()
                except socket.timeout:
                    continue
    except Exception as e:
        if log_callback:
            log_callback("Receiver", f"TCP Server bind error on {host}:{port}: {e}")


def _read_tcp_client(conn, stop_event, output_queue, log_callback=None):
    buffer = ""
    with conn:
        conn.settimeout(1.0)
        while not stop_event.is_set():
            try:
                data = conn.recv(4096)
                if not data:
                    break
                buffer += data.decode("utf-8", errors="ignore")
                while ";" in buffer:
                    parts = buffer.split(";", 1)
                    msg = parts[0].strip()
                    buffer = parts[1]
                    if msg.startswith("*"):
                        output_queue.put(msg)
            except socket.timeout:
                continue
            except Exception as e:
                break


def receive_avr_udp(host, port, stop_event, output_queue, log_callback=None):
    """Binds to a port listening for incoming UDP packets with AVR data."""
    if log_callback:
        log_callback("Receiver", f"UDP Server: binding {host}:{port}...")

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as sock:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind((host, port))
            sock.settimeout(1.0)
            buffer = ""

            while not stop_event.is_set():
                try:
                    data, addr = sock.recvfrom(65535)
                    buffer += data.decode("utf-8", errors="ignore")
                    while ";" in buffer:
                        parts = buffer.split(";", 1)
                        msg = parts[0].strip()
                        buffer = parts[1]
                        if msg.startswith("*"):
                            output_queue.put(msg)
                except socket.timeout:
                    continue
    except Exception as e:
        if log_callback:
            log_callback("Receiver", f"UDP Server error on {host}:{port}: {e}")


def receive_avr_serial(port, baudrate, stop_event, output_queue, log_callback=None):
    """Ingests AVR data from a local Serial COM port."""
    if serial is None:
        if log_callback:
            log_callback("Receiver", "Serial error: 'pyserial' is not installed.")
        return

    if log_callback:
        log_callback("Receiver", f"Serial: opening port {port} at {baudrate} baud...")

    while not stop_event.is_set():
        try:
            with serial.Serial(port=port, baudrate=baudrate, timeout=1.0) as ser:
                if log_callback:
                    log_callback("Receiver", f"Serial: port {port} opened successfully")
                buffer = ""
                
                while not stop_event.is_set():
                    if ser.in_waiting:
                        buffer += ser.read(ser.in_waiting).decode("utf-8", errors="ignore")
                        while ";" in buffer:
                            parts = buffer.split(";", 1)
                            msg = parts[0].strip()
                            buffer = parts[1]
                            if msg.startswith("*"):
                                output_queue.put(msg)
                    time.sleep(0.05)
        except Exception as e:
            if log_callback:
                log_callback("Receiver", f"Serial error on {port}: {e}. Retrying in 5s...")
            # Wait with interrupt
            for _ in range(50):
                if stop_event.is_set():
                    break
                time.sleep(0.1)


def start_multi_receiver(db_client, stop_event, output_queue, log_callback=None):
    """Queries active database connection entries and spawns receiving helper threads."""
    active_conns = db_client.get_active_connections()
    threads = []
    
    if not active_conns:
        if log_callback:
            log_callback("Receiver", "No active connection configurations found in database.")
        return threads

    for conn in active_conns:
        thread = None
        conn_type = conn.get('type')
        name = conn.get('name')
        
        if conn_type == 'network':
            net_proto = conn.get('network', 'tcp').lower()
            address = conn.get('address', '127.0.0.1')
            port = int(conn.get('port', 30002))
            
            if net_proto == 'tcp':
                # For ADS-B, we act as a TCP client connecting to dump1090/readsb 30002 feed.
                # If host is empty or '0.0.0.0'/'localhost', we can act as a TCP Server.
                if address in ('', '0.0.0.0', '::'):
                    thread = threading.Thread(
                        target=receive_avr_tcp_server,
                        args=(address, port, stop_event, output_queue, log_callback),
                        name=f"RecTCP_Server_{name}",
                        daemon=True
                    )
                else:
                    thread = threading.Thread(
                        target=receive_avr_tcp_client,
                        args=(address, port, stop_event, output_queue, log_callback),
                        name=f"RecTCP_Client_{name}",
                        daemon=True
                    )
            elif net_proto == 'udp':
                thread = threading.Thread(
                    target=receive_avr_udp,
                    args=(address, port, stop_event, output_queue, log_callback),
                    name=f"RecUDP_{name}",
                    daemon=True
                )
                
        elif conn_type == 'serial':
            serial_port = conn.get('data_port')
            baud = int(conn.get('baudrate', 115200))
            if serial_port:
                thread = threading.Thread(
                    target=receive_avr_serial,
                    args=(serial_port, baud, stop_event, output_queue, log_callback),
                    name=f"RecSerial_{name}",
                    daemon=True
                )
                
        if thread:
            thread.start()
            threads.append(thread)
            if log_callback:
                log_callback("Receiver", f"Spawned receiver thread: {thread.name}")
                
    return threads


# --- Mock Receiver for testing offline ---

class MockReceiver(threading.Thread):
    def __init__(self, log_file_path, output_queue, speed_multiplier=1.0):
        """
        Mock receiver for testing without an active SDR.
        Reads messages from a log file and pushes them at a simulated rate.
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
