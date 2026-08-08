import sys
from PySide6.QtWidgets import QApplication
from ui.window import MainWindow

def main():
    app = QApplication(sys.argv)
    app.setApplicationName("Antigravity Drive Media Organizer")
    app.setOrganizationName("Antigravity")

    win = MainWindow()
    win.show()

    sys.exit(app.exec())

if __name__ == "__main__":
    main()
