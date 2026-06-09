from PyQt6.QtCore import QObject, pyqtSignal, QTimer
import threading
import logging

logger = logging.getLogger("ADSBReceiver.WorkerManager")

class WorkerManager(QObject):
    status_changed = pyqtSignal(str, str)  # (worker_type, status)
    error_occurred = pyqtSignal(str)

    def __init__(self):
        super().__init__()
        self.workers = {
            'receiver': {'worker': None, 'stop_event': threading.Event()},
            'decoder': {'worker': None, 'stop_event': threading.Event()},
            'uploader': {'worker': None, 'stop_event': threading.Event()},
            'sender': {'worker': None, 'stop_event': threading.Event()},
            'web_server': {'worker': None, 'stop_event': threading.Event()}
        }

    def start_worker(self, worker_type, worker_class, *args):
        """Starts a background QThread worker of worker_type with given arguments."""
        if self.workers[worker_type]['worker'] and self.workers[worker_type]['worker'].isRunning():
            logger.info(f"Worker {worker_type} is already running.")
            return

        logger.info(f"Starting worker: {worker_type}")
        self.workers[worker_type]['stop_event'].clear()
        
        # Instantiate worker passing the stop_event and any extra args
        self.workers[worker_type]['worker'] = worker_class(
            self.workers[worker_type]['stop_event'],
            *args
        )
        self.workers[worker_type]['worker'].start()
        self.status_changed.emit(worker_type, 'running')

    def stop_worker(self, worker_type, callback=None):
        """Asynchronously stops a worker thread and checks its status periodically."""
        worker_info = self.workers.get(worker_type)
        if not worker_info:
            if callback: callback()
            return

        worker = worker_info['worker']
        if not worker or not worker.isRunning():
            if callback: callback()
            return

        logger.info(f"Requesting stop for worker: {worker_type}")
        worker_info['stop_event'].set()
        if hasattr(worker, 'stop'):
            try:
                worker.stop()
            except Exception as e:
                logger.error(f"Error calling stop() on worker {worker_type}: {e}")
 
        # Stop via timer polling
        timer = QTimer(self)
        timer.timeout.connect(lambda: self._check_stop_status(worker_type, timer, callback))
        timer.start(100)

    def _check_stop_status(self, worker_type, timer, callback):
        worker = self.workers[worker_type]['worker']
        if not worker or not worker.isRunning():
            timer.stop()
            self.workers[worker_type]['worker'] = None
            self.status_changed.emit(worker_type, 'stopped')
            logger.info(f"Worker {worker_type} stopped successfully.")
            if callback: 
                callback()

    def is_running(self, worker_type):
        worker = self.workers[worker_type]['worker']
        return worker is not None and worker.isRunning()

    def stop_all(self):
        logger.info("Stopping all workers...")
        for worker_type in self.workers:
            self.stop_worker(worker_type)
