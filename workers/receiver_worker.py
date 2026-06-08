from PyQt6.QtCore import QThread
import receiver
import logging

logger = logging.getLogger("ADSBReceiver.ReceiverWorker")

class ReceiverWorker(QThread):
    def __init__(self, stop_event, db_client, output_queue, log_callback=None):
        super().__init__()
        self.stop_event = stop_event
        self.db_client = db_client
        self.output_queue = output_queue
        self.log_callback = log_callback

    def run(self):
        try:
            logger.info("Receiver worker started.")
            if self.log_callback:
                self.log_callback("Receiver", "Multi-receiver worker thread started.")

            threads = receiver.start_multi_receiver(
                self.db_client, 
                self.stop_event, 
                self.output_queue, 
                self.log_callback
            )
            
            while not self.stop_event.is_set():
                alive_threads = [t for t in threads if t.is_alive()]
                if not alive_threads and threads:
                    logger.warning("All receiver sub-threads have exited.")
                    if self.log_callback:
                        self.log_callback("Receiver", "Warning: All active receiver feeds closed.")
                    break
                self.msleep(500)
        except Exception as e:
            self.stop_event.set()
            logger.error(f"Error in Receiver worker: {e}")
            if self.log_callback:
                self.log_callback("Error", f"Receiver worker exception: {e}")
        finally:
            logger.info("Receiver worker exiting.")
            if self.log_callback:
                self.log_callback("Receiver", "Multi-receiver worker thread stopped.")
