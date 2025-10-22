from PyQt5 import QtWidgets, QtGui, QtCore
from masterMainScripts import MongoDBHandler
from datetime import datetime


class GetUserByIDWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("SBSK | Get User by ID")
        self.resize(550, 400)
        self.setWindowIcon(QtGui.QIcon("icon.png"))
        self.setStyleSheet("background-color: #1E1E2E; color: white; font-family: 'Segoe UI';")

        # Initialize MongoDB handler
        self.db_handler = MongoDBHandler(
            db_uri="mongodb+srv://sbskproject_db_user:sbskAdmin@sbskcardfacecluster.pfvqhtz.mongodb.net/?retryWrites=true&w=majority&appName=sbskCardFaceCluster",
            db_name="sbsk_card_face_system"
        )

        self.setup_ui()

    def setup_ui(self):
        main_layout = QtWidgets.QVBoxLayout(self)
        main_layout.setContentsMargins(40, 40, 40, 40)

        # --- Header ---
        title = QtWidgets.QLabel("🔍 Find User: (Enter UserID)")
        title.setAlignment(QtCore.Qt.AlignCenter)
        title.setStyleSheet("""
            font-size: 22px;
            font-weight: bold;
            color: #E2BBE9;
            margin-bottom: 15px;
        """)
        main_layout.addWidget(title)

        # --- Search Section ---
        input_layout = QtWidgets.QHBoxLayout()
        self.user_id_input = QtWidgets.QLineEdit()
        self.user_id_input.setPlaceholderText("Enter User ID (e.g., UID123)")
        self.user_id_input.setMinimumHeight(35)
        self.user_id_input.setStyleSheet("""
            QLineEdit {
                background-color: #3C3F58;
                border-radius: 8px;
                border: 1px solid #7776B3;
                color: white;
                padding: 6px 10px;
                font-size: 14px;
            }
            QLineEdit:focus {
                border: 1px solid #E2BBE9;
            }
        """)

        self.search_button = QtWidgets.QPushButton("Search")
        self.search_button.setMinimumHeight(36)
        self.search_button.setCursor(QtGui.QCursor(QtCore.Qt.PointingHandCursor))
        self.search_button.setStyleSheet("""
            QPushButton {
                background-color: #5A639C;
                color: white;
                border-radius: 8px;
                font-weight: bold;
                font-size: 14px;
                padding: 6px 15px;
            }
            QPushButton:hover { background-color: #7776B3; }
            QPushButton:pressed { background-color: #9B86BD; }
        """)

        self.search_button.clicked.connect(self.get_user_by_id)
        input_layout.addWidget(self.user_id_input)
        input_layout.addWidget(self.search_button)
        main_layout.addLayout(input_layout)

        # --- Info Card Frame ---
        self.info_card = QtWidgets.QFrame()
        self.info_card.setStyleSheet("""
            QFrame {
                background-color: #2B2D42;
                border-radius: 12px;
                padding: 20px;
                border: 1px solid #5A639C;
            }
        """)
        info_layout = QtWidgets.QFormLayout(self.info_card)

        self.user_id_label = QtWidgets.QLabel("")
        self.username_label = QtWidgets.QLabel("")
        self.balance_label = QtWidgets.QLabel("")


        for lbl in (self.user_id_label, self.username_label, self.balance_label):
            lbl.setStyleSheet("color: #E2E2E2; font-size: 14px;")

        info_layout.addRow("🆔 User ID:", self.user_id_label)
        info_layout.addRow("👤 Username:", self.username_label)
        info_layout.addRow("💰 Balance:", self.balance_label)


        main_layout.addWidget(self.info_card)

        # --- Buttons ---
        btn_layout = QtWidgets.QHBoxLayout()
        btn_layout.setAlignment(QtCore.Qt.AlignCenter)

        self.clear_button = QtWidgets.QPushButton("Clear")
        self.exit_button = QtWidgets.QPushButton("Exit")

        for btn in (self.clear_button, self.exit_button):
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
                }
                QPushButton:hover { background-color: #7776B3; }
                QPushButton:pressed { background-color: #9B86BD; }
            """)

        self.clear_button.clicked.connect(self.clear_fields)
        self.exit_button.clicked.connect(QtWidgets.qApp.quit)

        btn_layout.addWidget(self.clear_button)
        btn_layout.addWidget(self.exit_button)
        main_layout.addLayout(btn_layout)

        # --- Status Bar ---
        self.status_label = QtWidgets.QLabel("💡 Enter a User ID to fetch details.")
        self.status_label.setAlignment(QtCore.Qt.AlignCenter)
        self.status_label.setStyleSheet("color: #AFAFCF; font-size: 13px; margin-top: 10px;")
        main_layout.addWidget(self.status_label)

        # --- Footer ---
        footer = QtWidgets.QLabel("© 2025 SBSK Project — All Rights Reserved")
        footer.setAlignment(QtCore.Qt.AlignCenter)
        footer.setStyleSheet("color: #7776B3; font-size: 11px; margin-top: 15px;")
        main_layout.addWidget(footer)

    def clear_fields(self):
        self.user_id_input.clear()
        self.user_id_label.clear()
        self.username_label.clear()
        self.balance_label.clear()
        self.status_label.setText("🧹 Cleared all fields.")

    def get_user_by_id(self):
        user_id = self.user_id_input.text().strip()
        if not user_id:
            QtWidgets.QMessageBox.warning(self, "Missing Input", "Please enter a User ID.")
            return

        try:
            # Fetch user document from MongoDB
            user = self.db_handler.db["users"].find_one({"_id": user_id})
            if user:
                self.user_id_label.setText(user.get("_id", ""))
                self.username_label.setText(user.get("username", ""))
                self.balance_label.setText(f"₹ {user.get('balance', 0.0):.2f}")
                self.status_label.setText(f"✅ User '{user_id}' found successfully.")
            else:
                QtWidgets.QMessageBox.information(self, "Not Found", f"No user found with ID '{user_id}'.")
                self.status_label.setText("⚠️ No record found.")
                self.clear_fields()
        except Exception as e:
            QtWidgets.QMessageBox.critical(self, "Error", f"❌ Failed to get user:\n{str(e)}")
            self.status_label.setText("❌ Database error.")


def main():
    import sys
    app = QtWidgets.QApplication(sys.argv)
    app.setStyle("Fusion")
    palette = QtGui.QPalette()
    palette.setColor(QtGui.QPalette.Window, QtGui.QColor("#1E1E2E"))
    palette.setColor(QtGui.QPalette.WindowText, QtCore.Qt.white)
    app.setPalette(palette)

    window = GetUserByIDWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
