DARK_STYLESHEET = """
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
"""
