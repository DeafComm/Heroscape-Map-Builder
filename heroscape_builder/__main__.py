import sys

from PySide6.QtWidgets import QApplication

from .gui.main_window import MainWindow


def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Heroscape Map Builder")
    window = MainWindow()
    if len(sys.argv) > 1:
        window.load(sys.argv[1])
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
