import sys
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QFormLayout, QFrame
)
from PyQt6.QtCore import QTimer, Qt, pyqtSignal, pyqtSlot
from PyQt6.QtGui import QFont, QColor, QTextCursor
import queue
from datetime import datetime

class MutedFrame(QFrame):
    """Custom styled frame for KPI Cards."""
    def __init__(self, title, val_color="#00ADB5"):
        super().__init__()
        self.setFrameShape(QFrame.Shape.StyledPanel)
        self.setStyleSheet(f"""
            QFrame {{
                background-color: #1e1e1e;
                border: 1px solid #2d2d2d;
                border-radius: 8px;
            }}
        """)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(10, 10, 10, 10)
        
        self.title_label = QLabel(title)
        self.title_label.setStyleSheet("color: #888888; font-size: 11px; font-weight: bold; text-transform: uppercase;")
        
        self.val_label = QLabel("N/A")
        self.val_label.setStyleSheet(f"color: {val_color}; font-size: 24px; font-weight: bold;")
        
        layout.addWidget(self.title_label)
        layout.addWidget(self.val_label)

class MainWindow(QMainWindow):
    # Signals to safely communicate between backend threads and UI thread
    log_signal = pyqtSignal(str, str, str) # timestamp, source, message
    status_signal = pyqtSignal(bool, str)  # connected, message

    def __init__(self, start_callback, stop_callback, initial_config):
        super().__init__()
        self.start_callback = start_callback
        self.stop_callback = stop_callback
        self.config = initial_config
        
        # Log and status queues
        self.log_queue = queue.Queue()
        
        self.setWindowTitle("ADS-B Real-Time Desktop Receiver & Decoder")
        self.resize(1100, 750)
        
        # Set Dark Palette stylesheet
        self.setStyleSheet("""
            QMainWindow {
                background-color: #121212;
            }
            QWidget {
                color: #e0e0e0;
                font-family: 'Outfit', 'Inter', 'Segoe UI', sans-serif;
                font-size: 13px;
            }
            QGroupBox {
                border: 1px solid #2d2d2d;
                border-radius: 6px;
                margin-top: 12px;
                font-weight: bold;
                color: #00ADB5;
            }
            QGroupBox::title {
                subcontrol-origin: margin;
                left: 10px;
                padding: 0 3px 0 3px;
            }
            QLineEdit {
                background-color: #1a1a1a;
                border: 1px solid #333333;
                border-radius: 4px;
                padding: 6px;
                color: #ffffff;
            }
            QLineEdit:focus {
                border: 1px solid #00ADB5;
            }
            QPushButton {
                background-color: #00ADB5;
                color: #121212;
                border: none;
                border-radius: 4px;
                padding: 10px;
                font-weight: bold;
            }
            QPushButton:hover {
                background-color: #00fff2;
            }
            QPushButton:disabled {
                background-color: #2a2a2a;
                color: #555555;
            }
            QCheckBox {
                spacing: 5px;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
                background-color: #1a1a1a;
                border: 1px solid #333333;
                border-radius: 3px;
            }
            QCheckBox::indicator:checked {
                background-color: #00ADB5;
                border: 1px solid #00ADB5;
            }
            QTableWidget {
                background-color: #1e1e1e;
                gridline-color: #2d2d2d;
                border: 1px solid #2d2d2d;
                border-radius: 6px;
            }
            QHeaderView::section {
                background-color: #1a1a1a;
                color: #888888;
                padding: 6px;
                border: 1px solid #2d2d2d;
                font-weight: bold;
            }
        """)

        self.init_ui()
        
        # Connect signals
        self.log_signal.connect(self.add_log_to_ui)
        self.status_signal.connect(self.update_sdr_status)
        
        # Timer to poll stats and update GUI (10 FPS)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_gui_stats)
        self.timer.start(100)

        # Active aircraft dictionary for tracking table rows
        self.aircraft_table_data = {}

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)
        
        # ----------------- LEFT SIDE: CONFIGURATION & CONTROLS -----------------
        left_layout = QVBoxLayout()
        left_layout.setSpacing(15)
        
        # Title Header
        header_label = QLabel("ADS-B Receiver")
        header_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #ffffff;")
        left_layout.addWidget(header_label)
        
        # SDR Config Group
        sdr_group = QGroupBox("RTL-SDR Connection")
        sdr_form = QFormLayout(sdr_group)
        sdr_form.setContentsMargins(12, 18, 12, 12)
        sdr_form.setSpacing(10)
        
        self.sdr_host_input = QLineEdit(self.config.SDR_HOST)
        self.sdr_port_input = QLineEdit(str(self.config.SDR_PORT))
        self.mock_checkbox = QCheckBox("Simulate skies using log file")
        self.mock_checkbox.setChecked(False)
        self.mock_checkbox.stateChanged.connect(self.toggle_mock_mode)
        
        sdr_form.addRow("Host IP:", self.sdr_host_input)
        sdr_form.addRow("Port:", self.sdr_port_input)
        sdr_form.addRow("", self.mock_checkbox)
        
        left_layout.addWidget(sdr_group)
        
        # DB Config Group
        db_group = QGroupBox("TimescaleDB / PostgreSQL")
        db_form = QFormLayout(db_group)
        db_form.setContentsMargins(12, 18, 12, 12)
        db_form.setSpacing(10)
        
        self.db_host_input = QLineEdit(self.config.DB_HOST)
        self.db_port_input = QLineEdit(str(self.config.DB_PORT))
        self.db_name_input = QLineEdit(self.config.DB_NAME)
        self.db_user_input = QLineEdit(self.config.DB_USER)
        self.db_pass_input = QLineEdit(self.config.DB_PASSWORD)
        self.db_pass_input.setEchoMode(QLineEdit.EchoMode.Password)
        
        db_form.addRow("DB Host:", self.db_host_input)
        db_form.addRow("DB Port:", self.db_port_input)
        db_form.addRow("DB Name:", self.db_name_input)
        db_form.addRow("Username:", self.db_user_input)
        db_form.addRow("Password:", self.db_pass_input)
        
        left_layout.addWidget(db_group)
        
        # Batch Config Group
        batch_group = QGroupBox("Batch Settings")
        batch_form = QFormLayout(batch_group)
        batch_form.setContentsMargins(12, 18, 12, 12)
        self.batch_interval_input = QLineEdit(str(self.config.BATCH_INTERVAL_SEC))
        batch_form.addRow("Batch Interval (s):", self.batch_interval_input)
        left_layout.addWidget(batch_group)
        
        # Control Buttons
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("START")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #00e676;
                color: #121212;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #69f0ae;
            }
        """)
        self.start_btn.clicked.connect(self.on_start_clicked)
        
        self.stop_btn = QPushButton("STOP")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff1744;
                color: #ffffff;
                font-size: 14px;
            }
            QPushButton:hover {
                background-color: #ff5252;
            }
        """)
        self.stop_btn.clicked.connect(self.on_stop_clicked)
        
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        left_layout.addLayout(btn_layout)
        
        # Spacer
        left_layout.addStretch()
        
        main_layout.addLayout(left_layout, stretch=1)
        
        # ----------------- RIGHT SIDE: DASHBOARD & LOGS -----------------
        right_layout = QVBoxLayout()
        right_layout.setSpacing(15)
        
        # KPI Cards Row
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(10)
        
        self.card_sdr_status = MutedFrame("SDR Status", "#ff5252")
        self.card_sdr_status.val_label.setText("Offline")
        
        self.card_db_status = MutedFrame("DB Status", "#ff5252")
        self.card_db_status.val_label.setText("Offline")
        
        self.card_total_msgs = MutedFrame("Messages", "#00b0ff")
        self.card_total_msgs.val_label.setText("0")
        
        self.card_active_skies = MutedFrame("Active Skies", "#ffd600")
        self.card_active_skies.val_label.setText("0")
        
        self.card_db_saves = MutedFrame("Saved to DB", "#00e676")
        self.card_db_saves.val_label.setText("0")
        
        cards_layout.addWidget(self.card_sdr_status)
        cards_layout.addWidget(self.card_db_status)
        cards_layout.addWidget(self.card_total_msgs)
        cards_layout.addWidget(self.card_active_skies)
        cards_layout.addWidget(self.card_db_saves)
        
        right_layout.addLayout(cards_layout)
        
        # Middle Section (Split horizontally: Table vs Logs)
        mid_layout = QHBoxLayout()
        mid_layout.setSpacing(15)
        
        # Active Aircraft Table
        table_layout = QVBoxLayout()
        table_label = QLabel("Active Skies Aircraft")
        table_label.setStyleSheet("font-weight: bold; color: #ffffff;")
        table_layout.addWidget(table_label)
        
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["ICAO24", "Callsign", "Last Msg"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table_layout.addWidget(self.table)
        
        mid_layout.addLayout(table_layout, stretch=1)
        
        # Live Console Log Terminal
        console_layout = QVBoxLayout()
        console_label = QLabel("Live Decoder Logs")
        console_label.setStyleSheet("font-weight: bold; color: #ffffff;")
        console_layout.addWidget(console_label)
        
        self.console = QTextEdit()
        self.console.setReadOnly(True)
        self.console.setStyleSheet("""
            QTextEdit {
                background-color: #0b0b0b;
                border: 1px solid #2d2d2d;
                border-radius: 6px;
                color: #00ff66;
                font-family: 'Consolas', 'Courier New', monospace;
                font-size: 11px;
            }
        """)
        console_layout.addWidget(self.console)
        
        mid_layout.addLayout(console_layout, stretch=1)
        
        right_layout.addLayout(mid_layout, stretch=3)
        
        main_layout.addLayout(right_layout, stretch=3)

    def toggle_mock_mode(self, state):
        is_checked = state == Qt.CheckState.Checked.value
        self.sdr_host_input.setEnabled(not is_checked)
        self.sdr_port_input.setEnabled(not is_checked)

    def on_start_clicked(self):
        # Gather configurations
        self.config.SDR_HOST = self.sdr_host_input.text()
        self.config.SDR_PORT = int(self.sdr_port_input.text())
        self.config.DB_HOST = self.db_host_input.text()
        self.config.DB_PORT = int(self.db_port_input.text())
        self.config.DB_NAME = self.db_name_input.text()
        self.config.DB_USER = self.db_user_input.text()
        self.config.DB_PASSWORD = self.db_pass_input.text()
        self.config.BATCH_INTERVAL_SEC = int(self.batch_interval_input.text())
        
        mock_mode = self.mock_checkbox.isChecked()
        
        # Disable editing during acquisition
        self.sdr_host_input.setEnabled(False)
        self.sdr_port_input.setEnabled(False)
        self.db_host_input.setEnabled(False)
        self.db_port_input.setEnabled(False)
        self.db_name_input.setEnabled(False)
        self.db_user_input.setEnabled(False)
        self.db_pass_input.setEnabled(False)
        self.batch_interval_input.setEnabled(False)
        self.mock_checkbox.setEnabled(False)
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        
        self.console.clear()
        
        # Trigger start callback
        self.start_callback(mock_mode)

    def on_stop_clicked(self):
        self.stop_callback()
        
        # Re-enable UI inputs
        mock_mode = self.mock_checkbox.isChecked()
        self.sdr_host_input.setEnabled(not mock_mode)
        self.sdr_port_input.setEnabled(not mock_mode)
        self.db_host_input.setEnabled(True)
        self.db_port_input.setEnabled(True)
        self.db_name_input.setEnabled(True)
        self.db_user_input.setEnabled(True)
        self.db_pass_input.setEnabled(True)
        self.batch_interval_input.setEnabled(True)
        self.mock_checkbox.setEnabled(True)
        
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        
        self.card_sdr_status.val_label.setText("Offline")
        self.card_sdr_status.val_label.setStyleSheet("color: #ff5252; font-size: 24px; font-weight: bold;")
        self.card_db_status.val_label.setText("Offline")
        self.card_db_status.val_label.setStyleSheet("color: #ff5252; font-size: 24px; font-weight: bold;")

    @pyqtSlot(bool, str)
    def update_sdr_status(self, connected, message):
        """Thread-safe slot to update connection status card."""
        if connected:
            self.card_sdr_status.val_label.setText("Connected")
            self.card_sdr_status.val_label.setStyleSheet("color: #00e676; font-size: 24px; font-weight: bold;")
        else:
            self.card_sdr_status.val_label.setText("Offline")
            self.card_sdr_status.val_label.setStyleSheet("color: #ff5252; font-size: 24px; font-weight: bold;")
        
        self.add_log_to_ui(datetime.now().strftime("%H:%M:%S"), "SDR", message)

    @pyqtSlot(str, str, str)
    def add_log_to_ui(self, timestamp, source, message):
        """Thread-safe slot to append text to log terminal."""
        color = "#ffffff"
        if source == "Error":
            color = "#ff1744"
        elif source == "Database":
            color = "#00e676"
        elif source == "SDR" or source == "System":
            color = "#00b0ff"
        else:
            # Aircraft specific
            color = "#ffd600"
            
        log_html = f'<span style="color: #666666;">[{timestamp}]</span> <span style="color: {color}; font-weight: bold;">[{source}]</span> {message}'
        self.console.append(log_html)
        self.console.moveCursor(QTextCursor.MoveOperation.End)

    def queue_log(self, source, message):
        """Can be called from background threads to buffer logs."""
        ts = datetime.now().strftime("%H:%M:%S")
        self.log_signal.emit(ts, source, message)

    def update_db_status(self, connected):
        if connected:
            self.card_db_status.val_label.setText("Online")
            self.card_db_status.val_label.setStyleSheet("color: #00e676; font-size: 24px; font-weight: bold;")
        else:
            self.card_db_status.val_label.setText("Offline")
            self.card_db_status.val_label.setStyleSheet("color: #ff5252; font-size: 24px; font-weight: bold;")

    # We will poll stats from this function running in the UI thread
    self_stats_provider = None
    
    def set_stats_provider(self, provider):
        self.self_stats_provider = provider

    def update_gui_stats(self):
        if not self.self_stats_provider:
            return
            
        stats = self.self_stats_provider()
        if not stats:
            return
            
        # Update KPI values
        self.card_total_msgs.val_label.setText(f"{stats['total_msgs']:,}")
        self.card_active_skies.val_label.setText(str(stats['active_aircraft_count']))
        
        # Batch size pending
        pending = stats.get("batch_size", 0)
        self.card_db_saves.val_label.setText(f"{stats['db_saves']:,} ({pending})")
        
        # Check active aircraft updates
        # Update Table. For simplicity, we keep track of active aircraft seen
        # To avoid table redraw lag, we update or add rows selectively
        # We query the pipeline's active list
        # In a real app, you'd list ICAO, last callsign, last msg details.
        # We can reconstruct active aircraft updates from decoder's state
        active_list = list(stats.get("active_aircraft", []))
        # Keep table limited to top/recent active ones
        for icao in active_list:
            if icao not in self.aircraft_table_data:
                row_idx = self.table.rowCount()
                self.table.insertRow(row_idx)
                
                # Create items
                icao_item = QTableWidgetItem(icao)
                icao_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                callsign_item = QTableWidgetItem("Scanning...")
                callsign_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                time_item = QTableWidgetItem(datetime.now().strftime("%H:%M:%S"))
                time_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                
                self.table.setItem(row_idx, 0, icao_item)
                self.table.setItem(row_idx, 1, callsign_item)
                self.table.setItem(row_idx, 2, time_item)
                
                self.aircraft_table_data[icao] = {
                    "row": row_idx,
                    "callsign": None,
                    "last_time": datetime.now().strftime("%H:%M:%S")
                }
                
        # If the decoder updated a callsign, let's catch it.
        # We can query the pipe state from PipeDecoder for each aircraft
        # Wait, instead of calling pyModeS inside the GUI loop, we can let the log thread do it
        # Or check if any new aircraft callsign was found.
        # To keep it lightweight, if a log callback informs us of a callsign, we save it.
        
    def update_table_callsign(self, icao, callsign):
        if icao in self.aircraft_table_data:
            self.aircraft_table_data[icao]["callsign"] = callsign
            row = self.aircraft_table_data[icao]["row"]
            item = self.table.item(row, 1)
            if item:
                item.setText(callsign)
                
    def update_table_time(self, icao):
        if icao in self.aircraft_table_data:
            ts = datetime.now().strftime("%H:%M:%S")
            self.aircraft_table_data[icao]["last_time"] = ts
            row = self.aircraft_table_data[icao]["row"]
            item = self.table.item(row, 2)
            if item:
                item.setText(ts)

    def closeEvent(self, event):
        # Clean shutdown of threads on close window
        self.on_stop_clicked()
        event.accept()
