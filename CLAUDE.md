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
python -m py_compile main.py config.py receiver.py decoder.py icao_ranges.py db/__init__.py db/postgres_client.py db/offline_db.py gui/__init__.py gui/main_window.py gui/dialogs.py gui/widgets.py gui/styles.py workers/worker_manager.py workers/receiver_worker.py workers/decoder_worker.py workers/uploader_worker.py workers/sender_worker.py workers/web_server_worker.py
```

---

## 📂 Project Structure

```
adsb_receiver/
├── requirements.txt      # External dependencies (PyQt6, psycopg2, python-dotenv, requests, fastapi, uvicorn)
├── CLAUDE.md             # Developer instructions and guide (this file)
├── config.py             # Configuration manager (.env reader)
├── db/                   # Database package
│   ├── __init__.py       # Exposes DatabaseClient, OfflineDatabase
│   ├── postgres_client.py# PostgreSQL DatabaseClient connection and tables setup
│   └── offline_db.py     # Local SQLite OfflineDatabase backup buffer client
├── receiver.py           # Network & Serial AVR hex listeners, plus simulated MockReceiver
├── decoder.py            # Mode S/ADS-B parser QThread and active aircraft state cache
├── icao_ranges.py        # ICAO 24-bit range lookup for country and code mapping
├── gui/                  # GUI package
│   ├── __init__.py       # Exposes MainWindow
│   ├── main_window.py    # MainWindow core layout & action slots
│   ├── dialogs.py        # ConnectionDialog & SenderDialog configuration screens
│   ├── widgets.py        # MutedFrame styled KPI card dashboard widget
│   └── styles.py         # DARK_STYLESHEET layout theme values
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
* **Deduplicate a batch on `(time, icao24)` before inserting.** Postgres rejects an `INSERT ... ON CONFLICT DO UPDATE` whose `VALUES` touch the same key twice and fails the *entire* batch, so a single collision discards every point in it. Collisions are routine, not exotic: the decoder stamps points with `time.time()` read once per loop iteration, and Windows advances that clock only every ~15ms, so messages drained in a burst share a timestamp. The symptom is silent — tracks still reach the database via the SQLite fallback (whose `INSERT OR REPLACE` collapses duplicates) and the uploader, so only the counters betray it.
* **"Saved Tracks" counts both persistence routes.** A point is either written straight to Postgres by the decoder (`db_saves`) or buffered to SQLite and later pushed by the uploader (`total_synced`); the routes are mutually exclusive, so the card sums them. Counting only direct writes made it read 0 for as long as the fallback was carrying the load, which hid a broken insert path. The parenthesised figure is the batch still awaiting flush, and the separate "Buffer Sync" card still breaks out the uploader's share.
* **Track timestamps must be timezone-aware UTC.** `datetime.fromtimestamp()` without a `tz` returns *local* time, and psycopg2 hands a naive value to a `timestamptz` column as though it were already UTC — storing every point one whole UTC offset in the future (7h for WIB). `decoder.py` passes `tz=timezone.utc`. This is silent: nothing errors, the data simply reads hours ahead of reality.
* **ICAO addresses are lowercased at the decode entry point.** The format check accepts either case and pyModeS returns uppercase, so `decoder.py` normalises immediately after validating. Skipping this writes the same airframe under two spellings and silently splits its history — it previously produced 152 duplicate `aircraft` rows. The SBS parse path already lowercases; `format_sbs()` re-uppercases for the wire, which is the SBS-1 convention and does not reach the database.
* **Database Normalization & Migration**: Static plane metadata (country, registration, type) is isolated in the `aircraft` table, while dynamic telemetry coordinates are saved in the `aircraft_tracks` TimescaleDB hypertable. Database schema changes are managed via TypeORM migrations in the main NestJS project (e.g. `1781074719000-OptimizeADSB.ts`). The Python ingestion `db.py` module is aligned with this by executing a multi-table bulk insert that upserts unique plane metadata into the `aircraft` table before inserting telemetry records into `aircraft_tracks` to avoid foreign key constraint violations. For newly seen aircraft missing registration details, the database client queries the `hexdb.io` API to retrieve and cache their registration, ICAO type, and model.
* **Persistent Session Statistics**: UI dashboard statistics (Total Messages, Active Skies, Saved Tracks, Buffer Sync, and Forwarded) are cached in a persistent session cache `self.aggregated_stats` on the UI thread. The stats are frozen at their last captured values when the acquisition engine is stopped (preventing numbers from instantly zeroing out when background threads exit). This cache is reset only when starting a new acquisition session.
