import sys
from PyQt6.QtWidgets import QApplication, QMainWindow, QPushButton, QInputDialog, QMessageBox

class TestApp(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Test")
        self.setGeometry(100, 100, 400, 200)
        btn = QPushButton("Test Dialog", self)
        btn.clicked.connect(self.test_dialog)
        btn.setGeometry(50, 50, 100, 30)

    def test_dialog(self):
        print("Dialog opening")
        name, ok = QInputDialog.getText(self, "Test", "Name:")
        print(f"Dialog result: {name}, {ok}")
        if ok:
            QMessageBox.information(self, "Success", "Done")

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = TestApp()
    window.show()
    sys.exit(app.exec())