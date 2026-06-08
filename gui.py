import sys
from PyQt6.QtWidgets import (
    QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QGridLayout,
    QLabel, QLineEdit, QPushButton, QCheckBox, QTextEdit, QTableWidget,
    QTableWidgetItem, QHeaderView, QGroupBox, QFormLayout, QFrame,
    QTabWidget, QDialog, QComboBox, QDialogButtonBox, QMessageBox
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
        self.val_label.setStyleSheet(f"color: {val_color}; font-size: 20px; font-weight: bold;")
        
        layout.addWidget(self.title_label)
        layout.addWidget(self.val_label)

class ConnectionDialog(QDialog):
    """Dialog to add/edit connection feeds."""
    def __init__(self, parent=None, conn_data=None):
        super().__init__(parent)
        self.conn_data = conn_data or {}
        self.setWindowTitle("Connection Settings" if conn_data else "Add Connection")
        self.resize(400, 300)
        self.setStyleSheet("background-color: #1e1e1e; color: #ffffff;")
        
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        
        self.name_input = QLineEdit(self.conn_data.get('name', ''))
        self.type_combo = QComboBox()
        self.type_combo.addItems(['network', 'serial'])
        self.type_combo.setCurrentText(self.conn_data.get('type', 'network'))
        self.type_combo.currentTextChanged.connect(self.toggle_type_fields)
        
        self.net_combo = QComboBox()
        self.net_combo.addItems(['tcp', 'udp'])
        self.net_combo.setCurrentText(self.conn_data.get('network', 'tcp'))
        
        self.address_input = QLineEdit(self.conn_data.get('address', '127.0.0.1'))
        self.port_input = QLineEdit(self.conn_data.get('port', '30002'))
        
        self.serial_port_input = QLineEdit(self.conn_data.get('data_port', 'COM1'))
        self.baudrate_input = QLineEdit(self.conn_data.get('baudrate', '115200'))
        
        self.active_check = QCheckBox("Enabled")
        self.active_check.setChecked(self.conn_data.get('active', 1) == 1)
        
        form_layout.addRow("Connection Name:", self.name_input)
        form_layout.addRow("Type:", self.type_combo)
        form_layout.addRow("Network Protocol:", self.net_combo)
        form_layout.addRow("Host Address:", self.address_input)
        form_layout.addRow("Port:", self.port_input)
        form_layout.addRow("Serial Port (e.g. COM3):", self.serial_port_input)
        form_layout.addRow("Baud Rate:", self.baudrate_input)
        form_layout.addRow("", self.active_check)
        
        layout.addLayout(form_layout)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)
        
        # Initial field toggles
        self.toggle_type_fields(self.type_combo.currentText())

    def toggle_type_fields(self, conn_type):
        is_net = conn_type == 'network'
        self.net_combo.setEnabled(is_net)
        self.address_input.setEnabled(is_net)
        self.port_input.setEnabled(is_net)
        
        self.serial_port_input.setEnabled(not is_net)
        self.baudrate_input.setEnabled(not is_net)

    def get_data(self):
        data = {
            'name': self.name_input.text().strip(),
            'type': self.type_combo.currentText(),
            'network': self.net_combo.currentText() if self.type_combo.currentText() == 'network' else None,
            'address': self.address_input.text().strip() if self.type_combo.currentText() == 'network' else None,
            'port': self.port_input.text().strip() if self.type_combo.currentText() == 'network' else None,
            'data_port': self.serial_port_input.text().strip() if self.type_combo.currentText() == 'serial' else None,
            'baudrate': self.baudrate_input.text().strip() if self.type_combo.currentText() == 'serial' else None,
            'active': 1 if self.active_check.isChecked() else 0
        }
        if self.conn_data.get('id'):
            data['id'] = self.conn_data['id']
        return data

class SenderDialog(QDialog):
    """Dialog to add/edit rebroadcaster destinations."""
    def __init__(self, parent=None, sender_data=None):
        super().__init__(parent)
        self.sender_data = sender_data or {}
        self.setWindowTitle("Rebroadcaster Destination" if sender_data else "Add Destination")
        self.resize(380, 220)
        self.setStyleSheet("background-color: #1e1e1e; color: #ffffff;")
        
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        
        self.name_input = QLineEdit(self.sender_data.get('name', ''))
        self.host_input = QLineEdit(self.sender_data.get('host', '127.0.0.1'))
        self.port_input = QLineEdit(self.sender_data.get('port', '30005'))
        self.net_combo = QComboBox()
        self.net_combo.addItems(['udp', 'tcp'])
        self.net_combo.setCurrentText(self.sender_data.get('network', 'udp'))
        
        self.active_check = QCheckBox("Active")
        self.active_check.setChecked(self.sender_data.get('active', 1) == 1)
        
        form_layout.addRow("Destination Name:", self.name_input)
        form_layout.addRow("Host IP:", self.host_input)
        form_layout.addRow("Port:", self.port_input)
        form_layout.addRow("Network Protocol:", self.net_combo)
        form_layout.addRow("", self.active_check)
        
        layout.addLayout(form_layout)
        
        buttons = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel, self)
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        layout.addWidget(buttons)

    def get_data(self):
        data = {
            'name': self.name_input.text().strip(),
            'host': self.host_input.text().strip(),
            'port': self.port_input.text().strip(),
            'network': self.net_combo.currentText(),
            'active': 1 if self.active_check.isChecked() else 0
        }
        if self.sender_data.get('id'):
            data['id'] = self.sender_data['id']
        return data

class MainWindow(QMainWindow):
    # Signals to safely communicate between backend threads and UI thread
    log_signal = pyqtSignal(str, str, str) # timestamp, source, message
    status_signal = pyqtSignal(bool, str)  # connected, message
    worker_status_signal = pyqtSignal(str, str) # worker_type, status

    def __init__(self, start_callback, stop_callback, initial_config, db_client):
        super().__init__()
        self.start_callback = start_callback
        self.stop_callback = stop_callback
        self.config = initial_config
        self.db_client = db_client
        
        # Log queues
        self.log_queue = queue.Queue()
        
        self.setWindowTitle("ADS-B Receiver & Decoder (Worker Engine)")
        self.resize(1200, 780)
        
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
                padding: 8px;
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
            QTabWidget::pane {
                border: 1px solid #2d2d2d;
                background-color: #161616;
                border-radius: 6px;
            }
            QTabBar::tab {
                background-color: #1a1a1a;
                border: 1px solid #2d2d2d;
                padding: 8px 12px;
                border-top-left-radius: 4px;
                border-top-right-radius: 4px;
                margin-right: 2px;
                font-weight: bold;
                color: #888888;
            }
            QTabBar::tab:selected {
                background-color: #161616;
                color: #00ADB5;
                border-bottom-color: #161616;
            }
        """)

        self.init_ui()
        
        # Connect signals
        self.log_signal.connect(self.add_log_to_ui)
        self.status_signal.connect(self.update_sdr_status)
        self.worker_status_signal.connect(self.update_worker_badge)
        
        # Timer to poll stats and update GUI (10 FPS)
        self.timer = QTimer()
        self.timer.timeout.connect(self.update_gui_stats)
        self.timer.start(100)

        # Active aircraft dictionary for tracking table rows
        self.aircraft_table_data = {}

        # Initial list renders
        self.refresh_connections_table()
        self.refresh_senders_table()

    def init_ui(self):
        central_widget = QWidget()
        self.setCentralWidget(central_widget)
        
        main_layout = QHBoxLayout(central_widget)
        main_layout.setContentsMargins(15, 15, 15, 15)
        main_layout.setSpacing(15)
        
        # ----------------- LEFT SIDE: TABBED CONFIGURATOR -----------------
        left_layout = QVBoxLayout()
        left_layout.setSpacing(10)
        
        header_label = QLabel("ADS-B Engine Dashboard")
        header_label.setStyleSheet("font-size: 18px; font-weight: bold; color: #ffffff;")
        left_layout.addWidget(header_label)
        
        self.tab_widget = QTabWidget()
        
        # --- TAB 1: CONTROLS & WORKERS STATUS ---
        controls_tab = QWidget()
        controls_layout = QVBoxLayout(controls_tab)
        controls_layout.setSpacing(15)
        
        # System status card group
        status_group = QGroupBox("Engine Worker Status")
        status_form = QGridLayout(status_group)
        status_form.setContentsMargins(10, 15, 10, 10)
        status_form.setSpacing(10)
        
        self.status_indicators = {}
        workers = [
            ('receiver', 'Receiver Ingestion'),
            ('decoder', 'ADS-B Decoder'),
            ('uploader', 'API Bulk Uploader'),
            ('sender', 'UDP/TCP Rebroadcaster')
        ]
        for i, (w_key, w_name) in enumerate(workers):
            lbl = QLabel(w_name)
            lbl.setStyleSheet("font-weight: bold; color: #aaaaaa;")
            ind = QLabel("STOPPED")
            ind.setStyleSheet("background-color: #ff1744; color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold; text-align: center;")
            ind.setAlignment(Qt.AlignmentFlag.AlignCenter)
            
            status_form.addWidget(lbl, i, 0)
            status_form.addWidget(ind, i, 1)
            self.status_indicators[w_key] = ind
            
        controls_layout.addWidget(status_group)
        
        # Settings group
        settings_group = QGroupBox("Configuration Settings")
        settings_form = QFormLayout(settings_group)
        settings_form.setContentsMargins(10, 15, 10, 10)
        
        self.batch_interval_input = QLineEdit(str(self.config.BATCH_INTERVAL_SEC))
        self.mock_checkbox = QCheckBox("Simulate inputs using local log file")
        self.mock_checkbox.setChecked(False)
        self.mock_checkbox.stateChanged.connect(self.toggle_mock_mode)
        
        settings_form.addRow("Batch Interval (s):", self.batch_interval_input)
        settings_form.addRow("", self.mock_checkbox)
        controls_layout.addWidget(settings_group)
        
        # Control Buttons
        btn_layout = QHBoxLayout()
        self.start_btn = QPushButton("START ENGINE")
        self.start_btn.setStyleSheet("""
            QPushButton {
                background-color: #00e676;
                color: #121212;
                font-size: 13px;
                padding: 12px;
            }
            QPushButton:hover {
                background-color: #69f0ae;
            }
        """)
        self.start_btn.clicked.connect(self.on_start_clicked)
        
        self.stop_btn = QPushButton("STOP ENGINE")
        self.stop_btn.setEnabled(False)
        self.stop_btn.setStyleSheet("""
            QPushButton {
                background-color: #ff1744;
                color: #ffffff;
                font-size: 13px;
                padding: 12px;
            }
            QPushButton:hover {
                background-color: #ff5252;
            }
        """)
        self.stop_btn.clicked.connect(self.on_stop_clicked)
        
        btn_layout.addWidget(self.start_btn)
        btn_layout.addWidget(self.stop_btn)
        controls_layout.addLayout(btn_layout)
        controls_layout.addStretch()
        
        self.tab_widget.addTab(controls_tab, "Dashboard")
        
        # --- TAB 2: INPUT FEEDS (CONNECTIONS) ---
        connections_tab = QWidget()
        connections_layout = QVBoxLayout(connections_tab)
        
        self.conns_table = QTableWidget(0, 4)
        self.conns_table.setHorizontalHeaderLabels(["Name", "Type", "Address/Port", "Active"])
        self.conns_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.conns_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.conns_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        connections_layout.addWidget(self.conns_table)
        
        conn_btns = QHBoxLayout()
        self.add_conn_btn = QPushButton("Add")
        self.add_conn_btn.clicked.connect(self.add_connection)
        self.edit_conn_btn = QPushButton("Edit")
        self.edit_conn_btn.clicked.connect(self.edit_connection)
        self.delete_conn_btn = QPushButton("Delete")
        self.delete_conn_btn.clicked.connect(self.delete_connection)
        self.toggle_conn_btn = QPushButton("Toggle Active")
        self.toggle_conn_btn.clicked.connect(self.toggle_connection_active)
        
        conn_btns.addWidget(self.add_conn_btn)
        conn_btns.addWidget(self.edit_conn_btn)
        conn_btns.addWidget(self.delete_conn_btn)
        conn_btns.addWidget(self.toggle_conn_btn)
        connections_layout.addLayout(conn_btns)
        
        self.tab_widget.addTab(connections_tab, "Feeds")
        
        # --- TAB 3: FORWARDERS (SENDERS) ---
        senders_tab = QWidget()
        senders_layout = QVBoxLayout(senders_tab)
        
        self.senders_table = QTableWidget(0, 4)
        self.senders_table.setHorizontalHeaderLabels(["Name", "Host", "Port", "Active"])
        self.senders_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.senders_table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.senders_table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        senders_layout.addWidget(self.senders_table)
        
        sender_btns = QHBoxLayout()
        self.add_sender_btn = QPushButton("Add")
        self.add_sender_btn.clicked.connect(self.add_sender)
        self.edit_sender_btn = QPushButton("Edit")
        self.edit_sender_btn.clicked.connect(self.edit_sender)
        self.delete_sender_btn = QPushButton("Delete")
        self.delete_sender_btn.clicked.connect(self.delete_sender)
        self.toggle_sender_btn = QPushButton("Toggle Active")
        self.toggle_sender_btn.clicked.connect(self.toggle_sender_active)
        
        sender_btns.addWidget(self.add_sender_btn)
        sender_btns.addWidget(self.edit_sender_btn)
        sender_btns.addWidget(self.delete_sender_btn)
        sender_btns.addWidget(self.toggle_sender_btn)
        senders_layout.addLayout(sender_btns)
        
        self.tab_widget.addTab(senders_tab, "Forwarders")
        
        # --- TAB 4: DATABASE CONFIG ---
        db_tab = QWidget()
        db_layout = QVBoxLayout(db_tab)
        db_form = QFormLayout()
        db_form.setContentsMargins(10, 15, 10, 10)
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
        
        db_layout.addLayout(db_form)
        db_layout.addStretch()
        
        self.tab_widget.addTab(db_tab, "Database")
        
        left_layout.addWidget(self.tab_widget)
        main_layout.addLayout(left_layout, stretch=1)
        
        # ----------------- RIGHT SIDE: DASHBOARD & LOGS -----------------
        right_layout = QVBoxLayout()
        right_layout.setSpacing(15)
        
        # KPI Cards Row
        cards_layout = QHBoxLayout()
        cards_layout.setSpacing(10)
        
        self.card_sdr_status = MutedFrame("Ingest State", "#ff5252")
        self.card_sdr_status.val_label.setText("Offline")
        
        self.card_db_status = MutedFrame("TimescaleDB", "#ff5252")
        self.card_db_status.val_label.setText("Offline")
        
        self.card_total_msgs = MutedFrame("Total Messages", "#00b0ff")
        self.card_total_msgs.val_label.setText("0")
        
        self.card_active_skies = MutedFrame("Active Skies", "#ffd600")
        self.card_active_skies.val_label.setText("0")
        
        self.card_db_saves = MutedFrame("Saved Tracks", "#00e676")
        self.card_db_saves.val_label.setText("0")
        
        self.card_uploaded = MutedFrame("Buffer Sync", "#a855f7")
        self.card_uploaded.val_label.setText("0")

        self.card_forwarded = MutedFrame("Forwarded", "#f97316")
        self.card_forwarded.val_label.setText("0")
        
        cards_layout.addWidget(self.card_sdr_status)
        cards_layout.addWidget(self.card_db_status)
        cards_layout.addWidget(self.card_total_msgs)
        cards_layout.addWidget(self.card_active_skies)
        cards_layout.addWidget(self.card_db_saves)
        cards_layout.addWidget(self.card_uploaded)
        cards_layout.addWidget(self.card_forwarded)
        
        right_layout.addLayout(cards_layout)
        
        # Middle Section (Split horizontally: Table vs Logs)
        mid_layout = QHBoxLayout()
        mid_layout.setSpacing(15)
        
        # Active Aircraft Table
        table_layout = QVBoxLayout()
        table_label = QLabel("Detected Aircraft")
        table_label.setStyleSheet("font-weight: bold; color: #ffffff;")
        table_layout.addWidget(table_label)
        
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels(["ICAO24", "Callsign", "Last Active"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.setSelectionBehavior(QTableWidget.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QTableWidget.EditTrigger.NoEditTriggers)
        table_layout.addWidget(self.table)
        
        mid_layout.addLayout(table_layout, stretch=4)
        
        # Live Console Log Terminal
        console_layout = QVBoxLayout()
        console_label = QLabel("System Log Console")
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
        
        mid_layout.addLayout(console_layout, stretch=5)
        
        right_layout.addLayout(mid_layout, stretch=3)
        main_layout.addLayout(right_layout, stretch=2)

    def toggle_mock_mode(self, state):
        is_checked = state == Qt.CheckState.Checked.value
        # Disable feed edit buttons when mock mode is enabled since it bypasses config database
        self.conns_table.setEnabled(not is_checked)
        self.add_conn_btn.setEnabled(not is_checked)
        self.edit_conn_btn.setEnabled(not is_checked)
        self.delete_conn_btn.setEnabled(not is_checked)
        self.toggle_conn_btn.setEnabled(not is_checked)

    def on_start_clicked(self):
        # Apply database connection changes
        self.config.DB_HOST = self.db_host_input.text()
        self.config.DB_PORT = int(self.db_port_input.text())
        self.config.DB_NAME = self.db_name_input.text()
        self.config.DB_USER = self.db_user_input.text()
        self.config.DB_PASSWORD = self.db_pass_input.text()
        self.config.BATCH_INTERVAL_SEC = int(self.batch_interval_input.text())
        
        mock_mode = self.mock_checkbox.isChecked()
        
        # Disable editing during acquisition
        self.db_host_input.setEnabled(False)
        self.db_port_input.setEnabled(False)
        self.db_name_input.setEnabled(False)
        self.db_user_input.setEnabled(False)
        self.db_pass_input.setEnabled(False)
        self.batch_interval_input.setEnabled(False)
        self.mock_checkbox.setEnabled(False)
        
        self.add_conn_btn.setEnabled(False)
        self.edit_conn_btn.setEnabled(False)
        self.delete_conn_btn.setEnabled(False)
        self.toggle_conn_btn.setEnabled(False)
        self.add_sender_btn.setEnabled(False)
        self.edit_sender_btn.setEnabled(False)
        self.delete_sender_btn.setEnabled(False)
        self.toggle_sender_btn.setEnabled(False)
        
        self.start_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self.console.clear()
        
        # Trigger start callback
        self.start_callback(mock_mode)

    def on_stop_clicked(self):
        self.stop_callback()
        
        # Re-enable UI inputs
        mock_mode = self.mock_checkbox.isChecked()
        self.db_host_input.setEnabled(True)
        self.db_port_input.setEnabled(True)
        self.db_name_input.setEnabled(True)
        self.db_user_input.setEnabled(True)
        self.db_pass_input.setEnabled(True)
        self.batch_interval_input.setEnabled(True)
        self.mock_checkbox.setEnabled(True)
        
        if not mock_mode:
            self.add_conn_btn.setEnabled(True)
            self.edit_conn_btn.setEnabled(True)
            self.delete_conn_btn.setEnabled(True)
            self.toggle_conn_btn.setEnabled(True)
        self.add_sender_btn.setEnabled(True)
        self.edit_sender_btn.setEnabled(True)
        self.delete_sender_btn.setEnabled(True)
        self.toggle_sender_btn.setEnabled(True)
        
        self.start_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        
        self.card_sdr_status.val_label.setText("Offline")
        self.card_sdr_status.val_label.setStyleSheet("color: #ff5252; font-size: 20px; font-weight: bold;")
        self.card_db_status.val_label.setText("Offline")
        self.card_db_status.val_label.setStyleSheet("color: #ff5252; font-size: 20px; font-weight: bold;")

    @pyqtSlot(bool, str)
    def update_sdr_status(self, connected, message):
        """Thread-safe slot to update connection status card."""
        if connected:
            self.card_sdr_status.val_label.setText("Active")
            self.card_sdr_status.val_label.setStyleSheet("color: #00e676; font-size: 20px; font-weight: bold;")
        else:
            self.card_sdr_status.val_label.setText("Offline")
            self.card_sdr_status.val_label.setStyleSheet("color: #ff5252; font-size: 20px; font-weight: bold;")
        
        self.add_log_to_ui(datetime.now().strftime("%H:%M:%S"), "SDR", message)

    @pyqtSlot(str, str)
    def update_worker_badge(self, worker_type, status):
        """Thread-safe slot to update visual light status of background threads."""
        ind = self.status_indicators.get(worker_type)
        if not ind:
            return
            
        ind.setText(status.upper())
        if status == 'running':
            ind.setStyleSheet("background-color: #00e676; color: #121212; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold; text-align: center;")
        else:
            ind.setStyleSheet("background-color: #ff1744; color: white; padding: 2px 6px; border-radius: 4px; font-size: 10px; font-weight: bold; text-align: center;")

    @pyqtSlot(str, str, str)
    def add_log_to_ui(self, timestamp, source, message):
        """Thread-safe slot to append text to log terminal."""
        color = "#ffffff"
        if source == "Error":
            color = "#ff1744"
        elif source == "Database":
            color = "#a855f7"
        elif source == "Receiver":
            color = "#00e676"
        elif source == "Sender" or source == "System":
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
            self.card_db_status.val_label.setStyleSheet("color: #00e676; font-size: 20px; font-weight: bold;")
        else:
            self.card_db_status.val_label.setText("Offline")
            self.card_db_status.val_label.setStyleSheet("color: #ff5252; font-size: 20px; font-weight: bold;")

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
        
        # Sync and Forwarder counts
        pending_buf = stats.get("pending_upload_count", 0)
        self.card_uploaded.val_label.setText(f"{stats.get('total_sent', 0):,} ({pending_buf})")
        self.card_forwarded.val_label.setText(f"{stats.get('total_forwarded', 0):,}")
        
        # Refresh Active Skies Aircraft table
        active_list = list(stats.get("active_aircraft", []))
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

    # --- Connections Management UI callbacks ---

    def refresh_connections_table(self):
        self.conns_table.setRowCount(0)
        try:
            conns = self.db_client.get_all_connections()
            for r in conns:
                row = self.conns_table.rowCount()
                self.conns_table.insertRow(row)
                
                # Format endpoint details
                endpoint = ""
                if r['type'] == 'network':
                    endpoint = f"{r['network'].upper()} {r['address']}:{r['port']}"
                else:
                    endpoint = f"Serial {r['data_port']} ({r['baudrate']} baud)"
                
                name_item = QTableWidgetItem(r['name'])
                type_item = QTableWidgetItem(r['type'].upper())
                end_item = QTableWidgetItem(endpoint)
                active_item = QTableWidgetItem("YES" if r['active'] == 1 else "NO")
                
                # Center align
                for item in (name_item, type_item, end_item, active_item):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    
                # Store connection ID in Name item metadata
                name_item.setData(Qt.ItemDataRole.UserRole, r['id'])
                
                self.conns_table.setItem(row, 0, name_item)
                self.conns_table.setItem(row, 1, type_item)
                self.conns_table.setItem(row, 2, end_item)
                self.conns_table.setItem(row, 3, active_item)
        except Exception as e:
            logger.error(f"Error rendering connections table: {e}")

    def add_connection(self):
        dialog = ConnectionDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if self.db_client.save_connection(data):
                self.refresh_connections_table()
                self.queue_log("System", f"Added connection feed: {data['name']}")
            else:
                QMessageBox.critical(self, "Error", "Failed to save connection to database.")

    def edit_connection(self):
        selected_row = self.conns_table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "Warning", "Please select a connection to edit.")
            return
            
        name_item = self.conns_table.item(selected_row, 0)
        conn_id = name_item.data(Qt.ItemDataRole.UserRole)
        
        # Load from DB
        conns = self.db_client.get_all_connections()
        conn_data = next((c for c in conns if c['id'] == conn_id), None)
        
        if conn_data:
            dialog = ConnectionDialog(self, conn_data)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                data = dialog.get_data()
                if self.db_client.save_connection(data):
                    self.refresh_connections_table()
                    self.queue_log("System", f"Updated connection feed: {data['name']}")
                else:
                    QMessageBox.critical(self, "Error", "Failed to update connection.")

    def delete_connection(self):
        selected_row = self.conns_table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "Warning", "Please select a connection to delete.")
            return
            
        name_item = self.conns_table.item(selected_row, 0)
        conn_id = name_item.data(Qt.ItemDataRole.UserRole)
        name = name_item.text()
        
        confirm = QMessageBox.question(
            self, "Confirm Delete", 
            f"Are you sure you want to delete connection '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            if self.db_client.delete_connection(conn_id):
                self.refresh_connections_table()
                self.queue_log("System", f"Deleted connection: {name}")
            else:
                QMessageBox.critical(self, "Error", "Failed to delete connection.")

    def toggle_connection_active(self):
        selected_row = self.conns_table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "Warning", "Please select a connection feed.")
            return
            
        name_item = self.conns_table.item(selected_row, 0)
        conn_id = name_item.data(Qt.ItemDataRole.UserRole)
        
        # Fetch current state
        conns = self.db_client.get_all_connections()
        conn_data = next((c for c in conns if c['id'] == conn_id), None)
        
        if conn_data:
            conn_data['active'] = 1 if conn_data['active'] == 0 else 0
            if self.db_client.save_connection(conn_data):
                self.refresh_connections_table()
                status = "enabled" if conn_data['active'] == 1 else "disabled"
                self.queue_log("System", f"Feed '{conn_data['name']}' has been {status}.")

    # --- Senders (Forwarders) UI callbacks ---

    def refresh_senders_table(self):
        self.senders_table.setRowCount(0)
        try:
            senders = self.db_client.get_all_senders()
            for r in senders:
                row = self.senders_table.rowCount()
                self.senders_table.insertRow(row)
                
                name_item = QTableWidgetItem(r['name'])
                host_item = QTableWidgetItem(r['host'])
                port_item = QTableWidgetItem(f"{r['network'].upper()}:{r['port']}")
                active_item = QTableWidgetItem("YES" if r['active'] == 1 else "NO")
                
                # Center align
                for item in (name_item, host_item, port_item, active_item):
                    item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
                    
                name_item.setData(Qt.ItemDataRole.UserRole, r['id'])
                
                self.senders_table.setItem(row, 0, name_item)
                self.senders_table.setItem(row, 1, host_item)
                self.senders_table.setItem(row, 2, port_item)
                self.senders_table.setItem(row, 3, active_item)
        except Exception as e:
            logger.error(f"Error rendering senders table: {e}")

    def add_sender(self):
        dialog = SenderDialog(self)
        if dialog.exec() == QDialog.DialogCode.Accepted:
            data = dialog.get_data()
            if self.db_client.save_sender(data):
                self.refresh_senders_table()
                self.queue_log("System", f"Added rebroadcaster: {data['name']}")
            else:
                QMessageBox.critical(self, "Error", "Failed to save forwarder.")

    def edit_sender(self):
        selected_row = self.senders_table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "Warning", "Please select a forwarder to edit.")
            return
            
        name_item = self.senders_table.item(selected_row, 0)
        sender_id = name_item.data(Qt.ItemDataRole.UserRole)
        
        # Load from DB
        senders = self.db_client.get_all_senders()
        sender_data = next((s for s in senders if s['id'] == sender_id), None)
        
        if sender_data:
            dialog = SenderDialog(self, sender_data)
            if dialog.exec() == QDialog.DialogCode.Accepted:
                data = dialog.get_data()
                if self.db_client.save_sender(data):
                    self.refresh_senders_table()
                    self.queue_log("System", f"Updated forwarder: {data['name']}")
                else:
                    QMessageBox.critical(self, "Error", "Failed to update forwarder.")

    def delete_sender(self):
        selected_row = self.senders_table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "Warning", "Please select a forwarder to delete.")
            return
            
        name_item = self.senders_table.item(selected_row, 0)
        sender_id = name_item.data(Qt.ItemDataRole.UserRole)
        name = name_item.text()
        
        confirm = QMessageBox.question(
            self, "Confirm Delete", 
            f"Are you sure you want to delete forwarder '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
        )
        
        if confirm == QMessageBox.StandardButton.Yes:
            if self.db_client.delete_sender(sender_id):
                self.refresh_senders_table()
                self.queue_log("System", f"Deleted forwarder: {name}")
            else:
                QMessageBox.critical(self, "Error", "Failed to delete forwarder.")

    def toggle_sender_active(self):
        selected_row = self.senders_table.currentRow()
        if selected_row < 0:
            QMessageBox.warning(self, "Warning", "Please select a forwarder.")
            return
            
        name_item = self.senders_table.item(selected_row, 0)
        sender_id = name_item.data(Qt.ItemDataRole.UserRole)
        
        # Fetch current state
        senders = self.db_client.get_all_senders()
        sender_data = next((s for s in senders if s['id'] == sender_id), None)
        
        if sender_data:
            sender_data['active'] = 1 if sender_data['active'] == 0 else 0
            if self.db_client.save_sender(sender_data):
                self.refresh_senders_table()
                status = "enabled" if sender_data['active'] == 1 else "disabled"
                self.queue_log("System", f"Forwarder '{sender_data['name']}' has been {status}.")

    def closeEvent(self, event):
        # Clean shutdown of threads on close window
        self.on_stop_clicked()
        event.accept()
