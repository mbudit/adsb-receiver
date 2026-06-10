# CLAUDE.md — ADS-B Receiver Desktop App

This document outlines the command reference, project structure, and coding conventions for the standalone ADS-B Receiver & Decoder application.

## 🛠 Commands

### Environment Setup
Create a virtual environment and install dependencies:
```bash
# Create virtual environment (optional but recommended)
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate

# Install required packages
pip install -r requirements.txt
```

### Running the Application
Launch the PyQt6 desktop GUI:
```bash
python main.py
```

### Static Analysis & Syntax Verification
Compile and verify all Python files for syntax correctness:
```bash
python -m py_compile main.py config.py db.py receiver.py decoder.py gui.py icao_ranges.py workers/worker_manager.py workers/receiver_worker.py workers/decoder_worker.py workers/uploader_worker.py workers/sender_worker.py workers/web_server_worker.py
```

---

## 📂 Project Structure

```
adsb_receiver/
├── requirements.txt      # External dependencies (PyQt6, psycopg2, python-dotenv, PyQt6, requests, fastapi, uvicorn)
├── CLAUDE.md             # Developer instructions and guide (this file)
├── config.py             # Configuration manager (.env reader)
├── db.py                 # PostgreSQL DatabaseClient, SQLite OfflineDatabase helper & seeds
├── receiver.py           # Network & Serial AVR hex listeners, plus simulated MockReceiver
├── decoder.py            # Mode S/ADS-B parser QThread and active aircraft state cache
├── icao_ranges.py        # ICAO 24-bit range lookup for country and code mapping
├── gui.py                # PyQt6 window and dynamic configuration tabs (dark theme dashboard)
├── main.py               # Application entry point and coordinator
└── workers/              # PyQt6 QThread workers engine
    ├── __init__.py
    ├── worker_manager.py # Coordinates and polls active background workers
    ├── receiver_worker.py# Manages multi-connection ingestion (TCP, UDP, Serial COM)
    ├── decoder_worker.py # Decoder wrapper worker thread
    ├── uploader_worker.py# Automatic DB Offline Buffer Sync worker thread
    ├── sender_worker.py  # Forwarder / Rebroadcaster worker thread
    └── web_server_worker.py# FastAPI/Uvicorn HTTP API server background worker thread
```

---

## 🎨 Code Conventions

### Python Style & Structure
* **Formatting:** Standard PEP 8 conventions. Use 4 spaces for indentation.
* **Imports:** Use absolute imports within the project directory (e.g., `import config`, `from db import DatabaseClient`) to allow direct script execution (`python main.py`).
* **Naming:**
  * Classes: CamelCase (e.g., `ADSBDecoder`, `DatabaseClient`).
  * Functions & Variables: snake_case (e.g., `start_acquisition`, `batch_buffer`).
  * Constants: UPPER_SNAKE_CASE (e.g., `BATCH_INTERVAL_SEC`, `DB_PORT`).

### Multithreading & Worker Engine
* **Decoupling:** Never block the PyQt GUI event loop. Run long-running tasks in dedicated background worker threads (`QThread`) managed by the `WorkerManager`.
* **Worker Manager Orchestration**: Start/stop background worker tasks asynchronously by registering them in the manager's worker pool and setting/clearing the cooperative `stop_event` flag.
* **Thread Safety:** Do not manipulate PyQt GUI widgets directly from background threads. Use **PyQt Signals and Slots** (`pyqtSignal` and `@pyqtSlot`) or thread-safe buffers to safely dispatch logs and status updates to the UI thread.
* **Offline Resilience:** If connection to the main PostgreSQL database fails, the decoder flushes data into a local SQLite database (`offline_buffer.db`). When connection is restored, the `UploaderWorker` automatically syncs records to the main database and clears the buffer.
* **Output Rebroadcasting:** Real-time stream forwarding runs as a decoupled `SenderWorker` thread consuming from a thread-safe `sender_queue`. It dynamically formats raw/decoded items into **SBS-1 (BaseStation)**, **AVR Raw Hex** (appended with `;\r\n`), and **JSON** tracks, sending them over UDP or cached TCP connections (reusing connections to avoid socket exhaustion).
* **Antenna CPR Decoding & Calibration:** The decoder uses reference coordinates (`ANTENNA_LAT`, `ANTENNA_LON`) for local CPR fallback decoding (resolving position on the first message). It validates all decoded positions using a Great-Circle **Haversine formula** distance check against a max range (`MAX_RECEIVER_RANGE_KM`); coordinates exceeding this limit are discarded to block CPR wrapping anomalies.
* **In-Memory Tracking & Web API**: The decoder maintains a thread-safe active aircraft state dictionary protected by a `threading.Lock` (`state_lock`). The `WebServerWorker` exposes this cache as a JSON endpoint at `GET /api/aircraft` using a background **FastAPI** app running on **Uvicorn**. It identifies registered aircraft countries and country codes by performing integer comparisons against parsed ICAO range blocks defined in `icao_ranges.py`.
* **Database Normalization & Migration**: Static plane metadata (country, registration, type) is isolated in the `aircraft` table, while dynamic telemetry coordinates are saved in the `aircraft_tracks` TimescaleDB hypertable. Database schema changes are managed via TypeORM migrations in the main NestJS project (e.g. `1781074719000-OptimizeADSB.ts`). The Python ingestion `db.py` module is aligned with this by executing a multi-table bulk insert that upserts unique plane metadata into the `aircraft` table before inserting telemetry records into `aircraft_tracks` to avoid foreign key constraint violations. For newly seen aircraft missing registration details, the database client queries the `hexdb.io` API to retrieve and cache their registration, ICAO type, and model.
