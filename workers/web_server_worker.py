# workers/web_server_worker.py

from PyQt6.QtCore import QThread
import logging
import uvicorn
from fastapi import FastAPI, Depends, HTTPException, Security
from fastapi.security import APIKeyHeader
from fastapi.middleware.cors import CORSMiddleware
from starlette.status import HTTP_403_FORBIDDEN
import config

logger = logging.getLogger("ADSBReceiver.WebServerWorker")

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)

def verify_api_key(api_key: str = Depends(api_key_header)):
    expected_key = getattr(config, "WEB_SERVER_API_KEY", "")
    if not api_key or api_key != expected_key:
        raise HTTPException(
            status_code=HTTP_403_FORBIDDEN,
            detail="Could not validate credentials"
        )
    return api_key

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
                if getattr(config, "IS_API_KEY_AUTO_GENERATED", False):
                    self.log_callback("Security", f"WEB_SERVER_API_KEY not configured. Auto-generated temporary key: {config.WEB_SERVER_API_KEY}")
                    logger.warning(f"WEB_SERVER_API_KEY not configured. Auto-generated temporary key: {config.WEB_SERVER_API_KEY}")
                else:
                    self.log_callback("Security", "API key loaded from configuration.")
                    logger.info("WEB_SERVER_API_KEY loaded from configuration.")

            app = FastAPI(title="ADS-B Receiver API", description="API serving live flight telemetry")

            # Enable restricted CORS
            allowed_origins = getattr(config, "CORS_ALLOWED_ORIGINS", [])
            if not allowed_origins:
                allowed_origins = ["http://localhost:3000", "http://localhost:5173"]

            app.add_middleware(
                CORSMiddleware,
                allow_origins=allowed_origins,
                allow_credentials=False,
                allow_methods=["GET"],
                allow_headers=["*"],
            )

            @app.get("/api/aircraft", dependencies=[Depends(verify_api_key)])
            def get_aircraft():
                """Exposes active aircraft state dictionary."""
                return self.decoder.get_aircraft_states()

            # Config Uvicorn Server programmatically
            srv_config = uvicorn.Config(
                app,
                host=self.host,
                port=self.port,
                log_level="warning", # Reduce console log pollution
                loop="asyncio"
            )
            self.server = uvicorn.Server(srv_config)
            
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
