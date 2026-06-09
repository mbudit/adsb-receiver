# workers/web_server_worker.py

from PyQt6.QtCore import QThread
import logging
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

logger = logging.getLogger("ADSBReceiver.WebServerWorker")

class WebServerWorker(QThread):
    def __init__(self, stop_event, host, port, decoder, log_callback=None):
        super().__init__()
        self.stop_event = stop_event
        self.host = host
        self.port = port
        self.decoder = decoder
        self.log_callback = log_callback
        self.server = None

    def run(self):
        try:
            logger.info(f"Web Server starting on {self.host}:{self.port}...")
            if self.log_callback:
                self.log_callback("System", f"Starting FastAPI server on {self.host}:{self.port}...")

            app = FastAPI(title="ADS-B Receiver API", description="API serving live flight telemetry")

            # Enable CORS for future frontend integration (e.g. Leaflet map)
            app.add_middleware(
                CORSMiddleware,
                allow_origins=["*"],
                allow_credentials=True,
                allow_methods=["*"],
                allow_headers=["*"],
            )

            @app.get("/api/aircraft")
            def get_aircraft():
                """Exposes active aircraft state dictionary."""
                return self.decoder.get_aircraft_states()

            # Config Uvicorn Server programmatically
            config = uvicorn.Config(
                app,
                host=self.host,
                port=self.port,
                log_level="warning", # Reduce console log pollution
                loop="asyncio"
            )
            self.server = uvicorn.Server(config)
            
            # Start Uvicorn loop (blocks until should_exit is set to True)
            self.server.run()

        except Exception as e:
            self.stop_event.set()
            logger.error(f"Error in Web Server worker: {e}")
            if self.log_callback:
                self.log_callback("Error", f"Web Server worker exception: {e}")
        finally:
            logger.info("Web Server worker exiting.")
            if self.log_callback:
                self.log_callback("System", "FastAPI server stopped.")

    def stop(self):
        """Triggers graceful shutdown of the Uvicorn server."""
        self.stop_event.set()
        if self.server:
            self.server.should_exit = True
