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

# Import local application modules
import config
from db import DatabaseClient
from receiver import MockReceiver
from gui import MainWindow

# Import background workers
from workers.worker_manager import WorkerManager
from workers.receiver_worker import ReceiverWorker
from workers.decoder_worker import DecoderWorker
from workers.uploader_worker import UploaderWorker
from workers.sender_worker import SenderWorker

class ADSBApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.db_client = DatabaseClient()
        self.msg_queue = queue.Queue()
        self.sender_queue = queue.Queue()
        
        self.receiver = None  # Holds MockReceiver if replaying logs
        self.worker_manager = WorkerManager()
        
        # Instantiate main UI window
        self.window = MainWindow(
            start_callback=self.start_acquisition,
            stop_callback=self.stop_acquisition,
            initial_config=config,
            db_client=self.db_client
        )
        
        # Bind worker manager signal to GUI slots
        self.worker_manager.status_changed.connect(self.window.worker_status_signal.emit)
        
        # Link statistics to UI
        self.window.set_stats_provider(self.get_system_stats)

    def get_system_stats(self):
        """Aggregates statistics from active workers for dashboard rendering."""
        stats = {
            "total_msgs": 0,
            "active_aircraft_count": 0,
            "active_aircraft": set(),
            "batch_size": 0,
            "db_saves": 0,
            "total_sent": 0,
            "total_forwarded": 0
        }
        
        # 1. Decoder Stats
        dec_worker = self.worker_manager.workers['decoder']['worker']
        if dec_worker and dec_worker.isRunning():
            stats.update(dec_worker.get_stats())
            
        # 2. Uploader Stats
        up_worker = self.worker_manager.workers['uploader']['worker']
        if up_worker and up_worker.isRunning():
            stats.update(up_worker.get_stats())
            
        # 3. Sender Stats
        send_worker = self.worker_manager.workers['sender']['worker']
        if send_worker and send_worker.isRunning():
            stats.update(send_worker.get_stats())
            
        return stats

    def start_acquisition(self, mock_mode=False):
        logger.info("Starting acquisition...")
        self.window.queue_log("System", "Starting database connection...")
        
        # 1. Connect to Database
        db_connected = self.db_client.connect()
        self.window.update_db_status(db_connected)
        
        if not db_connected:
            self.window.queue_log("Error", "Could not connect to database. Check credentials in Settings tab.")
            self.window.on_stop_clicked()
            return
            
        # 2. Start ADS-B Decoder Worker
        self.worker_manager.start_worker(
            'decoder',
            DecoderWorker,
            self.msg_queue,
            self.sender_queue,
            self.db_client,
            config.BATCH_INTERVAL_SEC
        )
        dec_worker = self.worker_manager.workers['decoder']['worker']
        if dec_worker:
            dec_worker.set_log_callback(self.on_decoder_log)

        # 3. Start Ingestion Feeds
        if mock_mode:
            # Use the local log file for simulation
            log_file = r"c:\dev-projects\hidrometeo-be\adsb_murni_hex.log.txt"
            if not os.path.exists(log_file):
                log_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "adsb_murni_hex.log.txt")
                
            self.window.queue_log("System", f"Starting mock stream from: {log_file}")
            self.receiver = MockReceiver(log_file, self.msg_queue, speed_multiplier=2.0)
            self.receiver.set_status_callback(self.on_receiver_status_change)
            self.receiver.start()
            
            # Mock worker status update for receiver to look uniform
            self.window.worker_status_signal.emit('receiver', 'running')
        else:
            self.window.queue_log("System", "Starting receiver ingestion worker feeds...")
            self.worker_manager.start_worker(
                'receiver',
                ReceiverWorker,
                self.db_client,
                self.msg_queue,
                self.on_receiver_log
            )
            # Update connection status indicator
            self.window.status_signal.emit(True, "Receiver Ingestion Running")

        # 4. Start Uploader Worker
        self.window.queue_log("System", "Starting background API uploader...")
        self.worker_manager.start_worker(
            'uploader',
            UploaderWorker,
            self.db_client,
            100, # batch size
            15,  # upload interval seconds
            self.on_uploader_log
        )

        # 5. Start Forwarder / Rebroadcaster Worker
        self.window.queue_log("System", "Starting background rebroadcaster...")
        self.worker_manager.start_worker(
            'sender',
            SenderWorker,
            self.sender_queue,
            self.db_client,
            self.on_sender_log
        )

    def on_receiver_status_change(self, connected, message):
        """Dispatches status updates from MockReceiver to GUI main loop."""
        self.window.status_signal.emit(connected, message)

    def on_receiver_log(self, source, message):
        """Forwards receiver worker logs to GUI."""
        self.window.queue_log(source, message)

    def on_decoder_log(self, source, message):
        """Handles decoder updates and forwards them to GUI logs and tables."""
        self.window.queue_log(source, message)
        
        # Extract table updates from text logs
        if source not in ["Database", "System", "Error"] and source is not None:
            self.window.update_table_time(source)
            if "Callsign updated" in message:
                parts = message.split(": ")
                if len(parts) > 1:
                    callsign = parts[1].strip()
                    self.window.update_table_callsign(source, callsign)

    def on_uploader_log(self, source, message):
        """Forwards uploader logs to GUI."""
        self.window.queue_log(source, message)

    def on_sender_log(self, source, message):
        """Forwards sender/forwarder logs to GUI."""
        self.window.queue_log(source, message)

    def stop_acquisition(self):
        logger.info("Stopping acquisition...")
        
        # Stop mock receiver first if it was used
        if self.receiver:
            self.receiver.stop()
            self.receiver = None
            self.window.worker_status_signal.emit('receiver', 'stopped')
            
        # Stop all worker threads managed by WorkerManager
        self.worker_manager.stop_all()
            
        # Close database connection
        self.db_client.close()
        self.window.update_db_status(False)
        self.window.queue_log("System", "Acquisition stopped successfully.")

    def run(self):
        self.window.show()
        sys.exit(self.app.exec())

if __name__ == "__main__":
    app = ADSBApp()
    app.run()
