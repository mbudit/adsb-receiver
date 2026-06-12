from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QFormLayout, QLineEdit, QComboBox, QCheckBox, QDialogButtonBox
)

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
        self.resize(380, 260)
        self.setStyleSheet("background-color: #1e1e1e; color: #ffffff;")
        
        layout = QVBoxLayout(self)
        form_layout = QFormLayout()
        
        self.name_input = QLineEdit(self.sender_data.get('name', ''))
        self.host_input = QLineEdit(self.sender_data.get('host', '127.0.0.1'))
        self.port_input = QLineEdit(self.sender_data.get('port', '30005'))
        self.net_combo = QComboBox()
        self.net_combo.addItems(['udp', 'tcp'])
        self.net_combo.setCurrentText(self.sender_data.get('network', 'udp'))
        
        self.format_combo = QComboBox()
        self.format_combo.addItems(['SBS', 'AVR', 'JSON'])
        self.format_combo.setCurrentText(self.sender_data.get('format', 'SBS'))
        
        self.active_check = QCheckBox("Active")
        self.active_check.setChecked(self.sender_data.get('active', 1) == 1)
        
        form_layout.addRow("Destination Name:", self.name_input)
        form_layout.addRow("Host IP:", self.host_input)
        form_layout.addRow("Port:", self.port_input)
        form_layout.addRow("Network Protocol:", self.net_combo)
        form_layout.addRow("Output Format:", self.format_combo)
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
            'format': self.format_combo.currentText(),
            'active': 1 if self.active_check.isChecked() else 0
        }
        if self.sender_data.get('id'):
            data['id'] = self.sender_data['id']
        return data
