import sys
import os
import queue
import logging
from PyQt6.QtWidgets import QApplication

# Configure Python logging (console fallback)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("ADSBReceiver.Main")

# Import our local application modules
import config
from db import DatabaseClient
from receiver import SDRReceiver, MockReceiver
from decoder import ADSBDecoder
from gui import MainWindow

class ADSBApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.db_client = DatabaseClient()
        self.msg_queue = queue.Queue()
        
        self.receiver = None
        self.decoder = None
        
        # Instantiate main UI window
        self.window = MainWindow(
            start_callback=self.start_acquisition,
            stop_callback=self.stop_acquisition,
            initial_config=config
        )
        
        # Link statistics to UI
        self.window.set_stats_provider(self.get_decoder_stats)

    def get_decoder_stats(self):
        if self.decoder and self.decoder.is_alive():
            return self.decoder.get_stats()
        return None

    def start_acquisition(self, mock_mode=False):
        logger.info("Starting acquisition...")
        self.window.queue_log("System", "Starting database connection...")
        
        # 1. Connect to Database
        db_connected = self.db_client.connect()
        self.window.update_db_status(db_connected)
        
        if not db_connected:
            self.window.queue_log("Error", "Could not connect to database. Check settings in .env.")
            self.window.on_stop_clicked()
            return
            
        # 2. Setup Decoder Thread
        self.decoder = ADSBDecoder(
            input_queue=self.msg_queue,
            db_client=self.db_client,
            batch_interval=config.BATCH_INTERVAL_SEC
        )
        
        # Configure callbacks from decoder to GUI
        self.decoder.set_log_callback(self.on_decoder_log)
        self.decoder.start()
        
        # 3. Setup Receiver Thread
        if mock_mode:
            # Use the local log file for simulation
            log_file = r"c:\dev-projects\hidrometeo-be\adsb_murni_hex.log.txt"
            if not os.path.exists(log_file):
                # Fallback to check relative path
                log_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "adsb_murni_hex.log.txt")
                
            self.window.queue_log("System", f"Starting mock stream from: {log_file}")
            self.receiver = MockReceiver(log_file, self.msg_queue, speed_multiplier=2.0)
        else:
            self.window.queue_log("System", f"Connecting to live RTL-SDR stream...")
            self.receiver = SDRReceiver(config.SDR_HOST, config.SDR_PORT, self.msg_queue)
            
        # Set receiver connection status callback
        self.receiver.set_status_callback(self.on_receiver_status_change)
        self.receiver.start()

    def on_receiver_status_change(self, connected, message):
        """Dispatches status updates from receiver thread to GUI main loop."""
        self.window.status_signal.emit(connected, message)

    def on_decoder_log(self, source, message):
        """Handles decoder updates and forwards them to logs and table."""
        self.window.queue_log(source, message)
        
        # Extract table updates from text logs
        if source not in ["Database", "System", "Error"] and source is not None:
            self.window.update_table_time(source)
            if "Callsign updated" in message:
                parts = message.split(": ")
                if len(parts) > 1:
                    callsign = parts[1].strip()
                    self.window.update_table_callsign(source, callsign)

    def stop_acquisition(self):
        logger.info("Stopping acquisition...")
        
        # Stop receiver first (stops new queue items)
        if self.receiver:
            self.receiver.stop()
            self.receiver = None
            
        # Stop decoder (flushes queue and database)
        if self.decoder:
            self.decoder.stop()
            self.decoder = None
            
        # Close database connection
        self.db_client.close()
        self.window.update_db_status(False)
        self.window.queue_log("System", "Acquisition stopped successfully.")

    def run(self):
        self.window.show()
        # Start Qt Application Loop
        sys.exit(self.app.exec())

if __name__ == "__main__":
    app = ADSBApp()
    app.run()
