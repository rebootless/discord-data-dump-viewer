"""
main.py — entry point for the Discord JSON Viewer
"""

import sys
from PyQt6.QtWidgets import QApplication
from main_window import DiscordExportViewer


def main():
    app = QApplication(sys.argv)
    win = DiscordExportViewer()
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
