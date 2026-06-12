from PyQt6.QtWidgets import QFrame, QVBoxLayout, QLabel

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
