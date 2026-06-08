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
python -m py_compile main.py config.py db.py receiver.py decoder.py gui.py
```

---

## 📂 Project Structure

```
adsb_receiver/
├── requirements.txt      # External dependencies (PyQt6, pymodes, psycopg2-binary, python-dotenv)
├── CLAUDE.md             # Developer instructions and guide (this file)
├── config.py             # Configuration manager (.env reader)
├── db.py                 # TimescaleDB / PostgreSQL database driver and batch writer
├── receiver.py           # Background sockets listener (and simulated mock receiver)
├── decoder.py            # Mode S/ADS-B parser and active aircraft state cache
├── gui.py                # PyQt6 window and UI controls (dark mode dashboard)
└── main.py               # Application entry point and thread coordinator
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

### Multithreading & Event Loop
* **Decoupling:** Never block the PyQt GUI event loop. Run long-running operations (network sockets, file I/O, database bulk flushes) in dedicated background threads (`threading.Thread`).
* **Thread Safety:** Do not manipulate PyQt GUI widgets directly from background threads. Use **PyQt Signals and Slots** (`pyqtSignal` and `@pyqtSlot`) or thread-safe buffers to safely dispatch messages and stats updates to the UI thread.
* **State Management:** Keep parsing states (like aircraft callsigns, positions, and motion attributes) in the background thread's state cache (`self.aircraft_states` in `decoder.py`) to construct complete records before database insertion.
