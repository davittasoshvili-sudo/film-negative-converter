#!/usr/bin/env python3
"""
FilmScan — Film Negative Converter
===================================
Entry point.  Run with:

    python main.py

Or if installed as a package:

    python -m filmscan
"""

import sys
import os

# Ensure the package root is on the path when run directly
_HERE = os.path.dirname(os.path.abspath(__file__))
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

from PyQt5.QtWidgets import QApplication
from PyQt5.QtCore import Qt, QCoreApplication
from PyQt5.QtGui import QFont

from gui.main_window import MainWindow


def main():
    # High-DPI support
    QCoreApplication.setAttribute(Qt.AA_EnableHighDpiScaling, True)
    QCoreApplication.setAttribute(Qt.AA_UseHighDpiPixmaps, True)

    app = QApplication(sys.argv)
    app.setApplicationName("FilmScan")
    app.setOrganizationName("FilmScan")

    # Base font
    font = QFont("Segoe UI", 10)
    app.setFont(font)

    window = MainWindow()
    window.show()

    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
