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
from db import DatabaseClient, OfflineDatabase
from receiver import MockReceiver
from gui import MainWindow

# Import background workers
from workers.worker_manager import WorkerManager
from workers.receiver_worker import ReceiverWorker
from workers.decoder_worker import DecoderWorker
from workers.uploader_worker import UploaderWorker
from workers.sender_worker import SenderWorker
from workers.web_server_worker import WebServerWorker

class ADSBApp:
    def __init__(self):
        self.app = QApplication(sys.argv)
        self.db_client = DatabaseClient()
        self.offline_db = OfflineDatabase()
        self.msg_queue = queue.Queue()
        self.sender_queue = queue.Queue()
        
        self.receiver = None  # Holds MockReceiver if replaying logs
        self.worker_manager = WorkerManager()
        
        # Persistent cache to retain statistics after stopping the engine
        self.aggregated_stats = {
            "total_msgs": 0,
            "active_aircraft_count": 0,
            "active_aircraft": set(),
            "batch_size": 0,
            "db_saves": 0,
            "total_sent": 0,
            "total_forwarded": 0,
            "pending_upload_count": 0
        }
        
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
        # Check if any worker is currently running
        workers_running = False
        for w_info in self.worker_manager.workers.values():
            w = w_info.get('worker')
            if w and w.isRunning():
                workers_running = True
                break
                
        # If workers are running, update the aggregated stats
        if workers_running:
            stats = {
                "total_msgs": 0,
                "active_aircraft_count": 0,
                "active_aircraft": set(),
                "batch_size": 0,
                "db_saves": 0,
                "total_sent": 0,
                "total_forwarded": 0,
                "pending_upload_count": 0
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
                
            self.aggregated_stats = stats
            
        try:
            self.aggregated_stats["pending_upload_count"] = self.offline_db.get_pending_count()
            self.aggregated_stats["offline_db_size"] = self.offline_db.get_db_file_size()
        except Exception:
            pass
            
        self.aggregated_stats["db_online"] = self.db_client.online_status
        return self.aggregated_stats

    def start_acquisition(self, mock_mode=False, enable_db=True, enable_sender=True, enable_feeder=True, mock_file_path=None, mock_speed=1.0):
        logger.info(f"Starting acquisition (mock={mock_mode}, enable_db={enable_db}, enable_sender={enable_sender}, enable_feeder={enable_feeder}, mock_file={mock_file_path}, mock_speed={mock_speed})...")
        
        # Reset session statistics for the new session
        self.aggregated_stats = {
            "total_msgs": 0,
            "active_aircraft_count": 0,
            "active_aircraft": set(),
            "batch_size": 0,
            "db_saves": 0,
            "total_sent": 0,
            "total_forwarded": 0,
            "pending_upload_count": 0
        }
        
        # 1. Connect to Database (only required if enable_db is True OR mock_mode is False and we need connections/senders list)
        db_required = enable_db or (not mock_mode and (enable_feeder or enable_sender))
        db_connected = False
        
        if db_required:
            self.window.queue_log("System", "Starting database connection...")
            db_connected = self.db_client.connect()
            self.window.update_db_status(db_connected)
            
            if not db_connected:
                self.window.queue_log("Error", "Could not connect to database. Check credentials in Settings tab.")
                self.window.on_stop_clicked()
                return
        else:
            self.window.update_db_status(False)
            self.window.queue_log("System", "Database connection not required. Skipping connection.")
            
        # 2. Start ADS-B Decoder Worker (pass enable_db flag)
        antenna_coords = (config.ANTENNA_LAT, config.ANTENNA_LON) if (config.ANTENNA_LAT != 0.0 or config.ANTENNA_LON != 0.0) else None
        self.worker_manager.start_worker(
            'decoder',
            DecoderWorker,
            self.msg_queue,
            self.sender_queue,
            self.db_client,
            config.BATCH_INTERVAL_SEC,
            antenna_coords,
            config.MAX_RECEIVER_RANGE_KM,
            enable_db
        )
        dec_worker = self.worker_manager.workers['decoder']['worker']
        if dec_worker:
            dec_worker.set_log_callback(self.on_decoder_log)

        # Start Web Server Worker
        self.worker_manager.start_worker(
            'web_server',
            WebServerWorker,
            config.WEB_SERVER_HOST,
            config.WEB_SERVER_PORT,
            dec_worker,
            self.on_web_server_log
        )

        # 3. Start Ingestion Feeds (Feeder)
        if enable_feeder:
            if mock_mode:
                # Use the provided log file for simulation
                log_file = mock_file_path if mock_file_path else r"c:\dev-projects\hidrometeo-be\adsb_murni_hex.log.txt"
                if not os.path.exists(log_file):
                    log_file = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "adsb_murni_hex.log.txt")
                    
                self.window.queue_log("System", f"Starting mock stream from: {log_file} at {mock_speed}x speed")
                self.receiver = MockReceiver(log_file, self.msg_queue, speed_multiplier=mock_speed)
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
        else:
            self.window.queue_log("System", "Receiver Input Feeder is disabled. Skipping receiver feeds.")
            self.window.worker_status_signal.emit('receiver', 'stopped')
            self.window.status_signal.emit(False, "Feeder Disabled")

        # 4. Start Uploader Worker
        if enable_db:
            self.window.queue_log("System", "Starting background API uploader...")
            self.worker_manager.start_worker(
                'uploader',
                UploaderWorker,
                self.db_client,
                100, # batch size
                15,  # upload interval seconds
                self.on_uploader_log
            )
        else:
            self.window.queue_log("System", "Database logging is disabled. Skipping bulk uploader.")
            self.window.worker_status_signal.emit('uploader', 'stopped')

        # 5. Start Forwarder / Rebroadcaster Worker
        if enable_sender:
            self.window.queue_log("System", "Starting background rebroadcaster...")
            self.worker_manager.start_worker(
                'sender',
                SenderWorker,
                self.sender_queue,
                self.db_client,
                self.on_sender_log
            )
        else:
            self.window.queue_log("System", "Output Rebroadcasting is disabled. Skipping forwarder.")
            self.window.worker_status_signal.emit('sender', 'stopped')

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

    def on_web_server_log(self, source, message):
        """Forwards web server logs to GUI."""
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
