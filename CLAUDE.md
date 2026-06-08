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
python -m py_compile main.py config.py db.py receiver.py decoder.py gui.py workers/worker_manager.py workers/receiver_worker.py workers/decoder_worker.py workers/uploader_worker.py workers/sender_worker.py
```

---

## 📂 Project Structure

```
adsb_receiver/
├── requirements.txt      # External dependencies (PyQt6, pymodes, psycopg2, pyserial, requests)
├── CLAUDE.md             # Developer instructions and guide (this file)
├── config.py             # Configuration manager (.env reader)
├── db.py                 # PostgreSQL DatabaseClient, SQLite OfflineDatabase helper & seeds
├── receiver.py           # Network & Serial AVR hex listeners, plus simulated MockReceiver
├── decoder.py            # Mode S/ADS-B parser QThread and active aircraft state cache
├── gui.py                # PyQt6 window and dynamic configuration tabs (dark theme dashboard)
├── main.py               # Application entry point and coordinator
└── workers/              # PyQt6 QThread workers engine
    ├── __init__.py
    ├── worker_manager.py # Coordinates and polls active background workers
    ├── receiver_worker.py# Manages multi-connection ingestion (TCP, UDP, Serial COM)
    ├── decoder_worker.py # Decoder wrapper worker thread
    ├── uploader_worker.py# Automatic DB Offline Buffer Sync worker thread
    └── sender_worker.py  # Forwarder / Rebroadcaster worker thread
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
