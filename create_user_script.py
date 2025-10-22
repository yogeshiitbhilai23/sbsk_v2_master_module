from PyQt5 import QtWidgets, QtGui, QtCore
from datetime import datetime
from masterMainScripts import MongoDBHandler  # replace with your actual filename


class UserRegistrationWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SBSK | New User Registration")
        self.resize(600, 400)
        self.setWindowIcon(QtGui.QIcon("icon.png"))  # optional app icon
        self.setStyleSheet("background-color: #1E1E2E; color: white; font-family: 'Segoe UI';")

        self.db_handler = MongoDBHandler(
            db_uri="mongodb+srv://sbskproject_db_user:sbskAdmin@sbskcardfacecluster.pfvqhtz.mongodb.net/?retryWrites=true&w=majority&appName=sbskCardFaceCluster",
            db_name="sbsk_card_face_system"
        )

        self.setup_ui()

    def setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(40, 40, 40, 40)

        # --- Header Section ---
        header = QtWidgets.QLabel("🆕 SBSK User Registration Portal")
        header.setAlignment(QtCore.Qt.AlignCenter)
        header.setStyleSheet("""
            font-size: 22px;
            font-weight: bold;
            color: #E2BBE9;
            margin-bottom: 20px;
        """)
        main_layout.addWidget(header)

        # --- Central Card Frame ---
        card = QtWidgets.QFrame()
        card.setStyleSheet("""
            QFrame {
                background-color: #2B2D42;
                border-radius: 15px;
                padding: 25px;
                border: 1px solid #5A639C;
            }
        """)
        card_layout = QtWidgets.QFormLayout(card)
        card_layout.setLabelAlignment(QtCore.Qt.AlignLeft)
        card_layout.setFormAlignment(QtCore.Qt.AlignCenter)

        # --- Inputs ---
        self.user_id_input = QtWidgets.QLineEdit()
        self.username_input = QtWidgets.QLineEdit()
        self.balance_input = QtWidgets.QLineEdit()
        self.balance_input.setPlaceholderText("0.00")

        for field in (self.user_id_input, self.username_input, self.balance_input):
            field.setMinimumHeight(35)
            field.setStyleSheet("""
                QLineEdit {
                    border-radius: 8px;
                    background-color: #3C3F58;
                    border: 1px solid #7776B3;
                    color: white;
                    padding: 6px 10px;
                    font-size: 14px;
                }
                QLineEdit:focus {
                    border: 1px solid #E2BBE9;
                }
            """)

        card_layout.addRow("👤 User ID:", self.user_id_input)
        card_layout.addRow("🧾 Username:", self.username_input)
        card_layout.addRow("💰 Initial Balance (₹):", self.balance_input)
        main_layout.addWidget(card)

        # --- Buttons ---
        button_layout = QtWidgets.QHBoxLayout()
        button_layout.setAlignment(QtCore.Qt.AlignCenter)

        self.create_button = QtWidgets.QPushButton("Create User")
        self.clear_button = QtWidgets.QPushButton("Clear Fields")

        for btn in (self.create_button, self.clear_button):
            btn.setMinimumHeight(36)
            btn.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
            btn.setStyleSheet("""
                QPushButton {
                    background-color: #5A639C;
                    color: white;
                    border-radius: 8px;
                    font-weight: bold;
                    font-size: 14px;
                    padding: 6px 15px;
                    transition: 0.3s;
                }
                QPushButton:hover {
                    background-color: #7776B3;
                }
                QPushButton:pressed {
                    background-color: #9B86BD;
                }
            """)

        self.create_button.setIcon(QtGui.QIcon.fromTheme("user-new"))
        self.clear_button.setIcon(QtGui.QIcon.fromTheme("edit-clear"))

        self.create_button.clicked.connect(self.create_user)
        self.clear_button.clicked.connect(self.clear_fields)

        button_layout.addWidget(self.create_button)
        button_layout.addWidget(self.clear_button)
        main_layout.addLayout(button_layout)

        # --- Status Bar ---
        self.status_bar = QtWidgets.QLabel("")
        self.status_bar.setAlignment(QtCore.Qt.AlignCenter)
        self.status_bar.setStyleSheet("color: #AFAFCF; font-size: 13px; margin-top: 10px;")
        main_layout.addWidget(self.status_bar)

        # --- Footer ---
        footer = QtWidgets.QLabel("© 2025 SBSK Project — All Rights Reserved")
        footer.setAlignment(QtCore.Qt.AlignCenter)
        footer.setStyleSheet("color: #7776B3; font-size: 11px; margin-top: 15px;")
        main_layout.addWidget(footer)

    def clear_fields(self):
        self.user_id_input.clear()
        self.username_input.clear()
        self.balance_input.clear()
        self.status_bar.setText("🧹 Cleared all fields.")

    def create_user(self):
        user_id = self.user_id_input.text().strip()
        username = self.username_input.text().strip()
        balance_text = self.balance_input.text().strip()

        if not user_id or not username:
            QtWidgets.QMessageBox.warning(self, "Missing Data", "Please enter both User ID and Username.")
            return

        try:
            initial_balance = float(balance_text) if balance_text else 0.0
        except ValueError:
            QtWidgets.QMessageBox.warning(self, "Invalid Input", "Initial balance must be a valid number.")
            return

        try:
            success = self.db_handler.create_user(user_id, username, initial_balance)
            timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

            if success:
                msg = (f"✅ User created successfully!\n\n"
                       f"User ID: {user_id}\n"
                       f"Username: {username}\n"
                       f"Initial Balance: ₹{initial_balance:.2f}\n"
                       f"Timestamp: {timestamp}")
                QtWidgets.QMessageBox.information(self, "Success", msg)
                self.status_bar.setText(f"✅ User '{user_id}' registered successfully.")
                self.clear_fields()
            else:
                QtWidgets.QMessageBox.warning(self, "Duplicate User", f"⚠️ User ID '{user_id}' already exists.")
                self.status_bar.setText(f"⚠️ Duplicate user: {user_id}")

        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"❌ Failed to create user:\n{str(e)}")
            self.status_bar.setText("❌ Error occurred while creating user.")


def main():
    import sys
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")  # More professional theme on Windows
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#1E1E2E"))
    palette.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
    app.setPalette(palette)

    window = UserRegistrationWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
