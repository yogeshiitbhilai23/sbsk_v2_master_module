import csv
import os
import tkinter as tk
from tkinter import scrolledtext, ttk, messagebox
import serial
import serial.tools.list_ports
from threading import Thread, Event
import queue
import time
import re
import sv_ttk
from PIL import Image, ImageTk
from pymongo import MongoClient
import pymongo.errors
from datetime import datetime
from datetime import timedelta


class MongoDBHandler:
    def __init__(self,
                 db_uri="mongodb+srv://ybandhe:sbsk2023@databasesbskv2.wxatskm.mongodb.net/?retryWrites=true&w=majority&appName=databaseSBSKV2",
                 db_name="attendance_system",
                 per_attendance=100):
        self.request_amount_file = None
        self.client = MongoClient(db_uri)
        self.db = self.client[db_name]
        self.users = self.db.users
        self.attendance = self.db.attendance
        self.transactions = self.db.transactions
        self.per_attendance = per_attendance

        # Handle index creation/update
        index_name = "unique_transaction"
        desired_keys = [("user_id", 1), ("timestamp", 1), ("amount", 1), ("type", 1)]
        current_indexes = self.transactions.index_information()

        if index_name in current_indexes:
            existing_index = current_indexes[index_name]
            existing_keys = existing_index['key']
            existing_key_list = [(k, int(v)) for k, v in existing_keys]

            if existing_key_list != desired_keys or not existing_index.get('unique', False):
                self.transactions.drop_index(index_name)
                self.transactions.create_index(
                    desired_keys,
                    unique=True,
                    name=index_name
                )
        else:
            self.transactions.create_index(
                desired_keys,
                unique=True,
                name=index_name
            )

    def create_user(self, user_id, username, initial_balance=0):
        """Create a new user if they don't exist."""
        if self.users.find_one({"_id": user_id}):
            return False
        self.users.insert_one({
            "_id": user_id,
            "username": username,
            "balance": initial_balance
        })
        return True

    def is_duplicate_transaction(self, user_id, amount, timestamp):
        """Check for duplicates ACROSS ALL NODES"""
        time_threshold = timestamp - timedelta(minutes=5)
        query = {
            "user_id": user_id,
            "amount": float(amount),
            "timestamp": {"$gte": time_threshold},
            "$or": [{"type": "request"}, {"type": "receipt"}]
        }
        return bool(self.transactions.find_one(query))

    def record_request(self, node_address, user_id, username, amount, timestamp):
        """Record a payment request in MongoDB with datetime"""
        try:
            self.transactions.insert_one({
                "node_address": node_address,
                "user_id": user_id,
                "username": username,
                "amount": float(amount),
                "timestamp": timestamp,  # Store as datetime
                "type": "request"
            })
        except pymongo.errors.DuplicateKeyError:
            raise
        except Exception as e:
            raise RuntimeError(f"Failed to record request: {str(e)}")

    def process_payment(self, user_id, amount, node_address=None):
        """Process payment and return receipt data with proper datetime handling"""
        try:
            with self.client.start_session() as session:
                with session.start_transaction():
                    user = self.users.find_one({"_id": user_id}, session=session)
                    if not user:
                        raise ValueError("User not found")
                    current_balance = user.get("balance", 0.0)
                    if current_balance < amount:
                        raise ValueError("Insufficient balance")

                    new_balance = current_balance - amount
                    self.users.update_one(
                        {"_id": user_id},
                        {"$set": {"balance": new_balance}},
                        session=session
                    )

                    receipt_timestamp = datetime.now()  # Use datetime object
                    receipt_data = {
                        "node_address": node_address,
                        "user_id": user_id,
                        "username": user.get("username", ""),
                        "previous_balance": current_balance,
                        "request_amount": amount,
                        "new_balance": new_balance,
                        "timestamp": receipt_timestamp,
                        "type": "receipt"
                    }
                    self.transactions.insert_one(receipt_data, session=session)
                    return receipt_data
        except Exception as e:
            session.abort_transaction()
            raise RuntimeError(f"Payment processing error: {str(e)}")

    def record_attendance(self, node_address, user_id, username, timestamp):
        """Record attendance with node address"""
        if self.attendance.find_one({"user_id": user_id, "timestamp": timestamp}):
            return False

        try:
            with self.client.start_session() as session:
                with session.start_transaction():
                    self.attendance.insert_one({
                        "node_address": node_address,
                        "user_id": user_id,
                        "timestamp": timestamp,
                        "recorded_at": datetime.now()
                    }, session=session)

                    result = self.users.update_one(
                        {"_id": user_id},
                        {
                            "$setOnInsert": {"username": username},
                            "$inc": {"balance": self.per_attendance}
                        },
                        upsert=True,
                        session=session
                    )
                    return True
        except Exception as e:
            raise RuntimeError(f"Attendance error: {str(e)}")

    def get_balance(self, user_id):
        """Retrieve current balance for a user."""
        user = self.users.find_one({"_id": user_id})
        return user.get("balance", 0.00) if user else 0.00


class LoRaSerialMonitor:
    def __init__(self, root):
        self.message_display = None
        self.root = root
        self.root.title("LoRa Master Serial Monitor")

        # Set minimum window size for small screens
        self.root.minsize(800, 600)
        self.root.geometry("1000x700")

        # Make window responsive
        self.root.columnconfigure(0, weight=1)
        self.root.rowconfigure(0, weight=1)

        # Set theme using sv_ttk
        sv_ttk.set_theme("dark")

        # MongoDB integration
        self.mongo_handler = MongoDBHandler()

        # Serial connection variables
        self.serial_conn = None
        self.serial_thread = None
        self.stop_event = Event()
        self.message_queue = queue.Queue()
        self.message_history = []

        # GUI elements
        self.create_widgets()

        # Start processing the message queue
        self.process_queue()

        # File setup
        self.attendance_file = "attendance_records.csv"
        self.request_amount_file = "request_amount_records.csv"
        self.initialize_files()

    def initialize_files(self):
        """Create the CSV files with headers if they don't exist"""
        try:
            # Initialize attendance file
            att_file_path = os.path.abspath(self.attendance_file)
            if not os.path.exists(att_file_path):
                with open(att_file_path, mode='w', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerow(["Node", "Name", "ID", "Timestamp"])

            # Initialize request amount file
            req_file_path = os.path.abspath(self.request_amount_file)
            if not os.path.exists(req_file_path):
                with open(req_file_path, mode='w', newline='') as file:
                    writer = csv.writer(file)
                    writer.writerow(["Node", "Name", "ID", "Amount", "Timestamp"])
        except Exception as e:
            self.log_message(f"Error initializing files: {str(e)}\n", "system")

    def is_duplicate_request(self, user_id, timestamp, amount=None):
        """
        Check if a request with the same user_id, timestamp, and amount exists in CSV or MongoDB
        """
        # Check CSV
        csv_duplicate = False
        if os.path.exists(self.request_amount_file):
            try:
                with open(self.request_amount_file, mode='r', newline='') as file:
                    reader = csv.reader(file)
                    next(reader)  # Skip header row
                    for row in reader:
                        if len(row) >= 5 and row[2] == user_id and row[4] == timestamp:
                            if amount is None or row[3] == amount:
                                csv_duplicate = True
                                break
            except Exception as e:
                self.log_message(f"Error checking CSV for duplicates: {str(e)}\n", "info")

        # Check MongoDB for existing REQUEST type transactions
        mongo_duplicate = False
        try:
            query = {"user_id": user_id, "timestamp": timestamp, "type": "request"}
            if amount is not None:
                query["amount"] = float(amount)
            existing = self.mongo_handler.transactions.find_one(query)
            mongo_duplicate = existing is not None
        except Exception as e:
            self.log_message(f"Error checking MongoDB for duplicates: {str(e)}\n", "info")

        return csv_duplicate or mongo_duplicate

    def is_duplicate_attendance(self, user_id, timestamp):
        """Check if an attendance entry with the same user_id and timestamp already exists"""
        if not os.path.exists(self.attendance_file):
            return False

        try:
            with open(self.attendance_file, mode='r', newline='') as file:
                reader = csv.reader(file)
                next(reader)  # Skip header row
                for row in reader:
                    if len(row) >= 4 and row[2] == user_id and row[3] == timestamp:
                        return True
        except Exception as e:
            self.log_message(f"Error checking for duplicate attendance: {str(e)}\n", "info")
        return False

    def process_serial_message(self, message):
        # Skip ESP32 boot messages
        skip_patterns = [
            "Using existing attendance file at:",
            "Using existing request amount file at:",
            "ets Jul 29 2019",
            "rst:0x1",
            "configsip:",
            "clk_drv:",
            "mode:DIO",
            "load:0x",
            "entry 0x"
        ]

        if any(pattern in message for pattern in skip_patterns):
            return

        # Extract node address from message if available
        node_address = "00"  # Default if not found
        if "From:0x" in message:
            try:
                # Extract first 2 hex characters after From:0x
                addr_part = message.split("From:0x")[1].split()[0][:2]
                node_address = addr_part.upper().zfill(2)  # Ensure 2-digit format
            except Exception as e:
                self.log_message(f"Node address extraction error: {str(e)}\n", "error")
                return

        # Process messages
        if "ATTENDANCE|" in message:
            self.process_attendance(message, node_address)
        elif "REQUEST_AMOUNT " in message:
            self.process_payment_request(message, node_address)
        else:
            # Handle other message types
            if "COMPLETE from" in message:
                self.log_message(message + "\n", "complete")
            elif "From:0x" in message:
                self.log_message(message + "\n", "chunk")
            elif "Sent chunk" in message:
                self.log_message(message + "\n", "sent")
            else:
                self.log_message(message + "\n", "info")

    def process_payment_request(self, message, node_address):
        """Handle payment requests with proper datetime and node address handling"""
        try:
            payload = message.split("REQUEST_AMOUNT", 1)[1].strip()
            parts = payload.split()

            if len(parts) < 4:
                self.log_message(f"Invalid request format: {message}\n", "error")
                return

            user_id = parts[0].strip()
            name = ' '.join(parts[1:-1]).strip()
            amount = parts[-1].strip()
            timestamp = datetime.now()  # Correct datetime object

            try:
                amount_float = float(amount)
                if amount_float <= 0:
                    raise ValueError("Invalid amount")
            except ValueError:
                self.log_message(f"Invalid amount: {amount}\n", "error")
                return

            # Check for duplicates using datetime
            if self.mongo_handler.is_duplicate_transaction(user_id, amount_float, timestamp):
                self.log_message(f"Duplicate transaction prevented: {user_id}, ₹{amount_float}\n", "error")
                return

            # Save to CSV with formatted timestamp
            timestamp_str = timestamp.strftime("%Y-%m-%d %H:%M:%S")
            self.write_to_csv([node_address, name, user_id, amount, timestamp_str])

            # MongoDB operations
            try:
                self.mongo_handler.record_request(node_address, user_id, name, amount_float, timestamp)
            except pymongo.errors.DuplicateKeyError:
                self.log_message("Duplicate request in MongoDB\n", "error")
                return

            # Process payment
            try:
                receipt_data = self.mongo_handler.process_payment(user_id, amount_float, node_address)
                self.write_transaction_to_csv(receipt_data)
                self.log_receipt(receipt_data)
                self.update_balance_display(user_id)
                self.transmit_receipt(receipt_data)
                self.send_message_to_node(node_address, "TRX_COMPLETE")
            except Exception as e:
                self.log_message(f"Payment error: {str(e)}\n", "error")
                self.send_message_to_node(node_address, f"TRX_ERROR|{str(e)}")

        except Exception as e:
            self.log_message(f"Request processing failed: {str(e)}\n", "error")

    def transmit_receipt(self, receipt_data):
        """Send receipt with formatted timestamp and retries"""
        node = receipt_data.get('node_address', '00').upper().zfill(2)
        formatted_time = receipt_data['timestamp'].strftime("%Y-%m-%d %H:%M:%S")

        receipt_msg = (
            f"RECEIPT|{receipt_data['user_id']}|"
            f"{receipt_data['request_amount']:.2f}|"
            f"{receipt_data['new_balance']:.2f}|"
            f"{formatted_time}"
        )

        for _ in range(3):  # 3 retries
            self.send_message_to_node(node, receipt_msg)
            time.sleep(0.5)

    def send_message_to_node(self, node, message):
        """Send message with proper node formatting"""
        if not self.serial_conn or not self.serial_conn.is_open:
            return

        # Validate and format node address
        node = node.zfill(2).upper()
        if not re.match(r'^[0-9A-F]{2}$', node):
            self.log_message(f"Invalid node: {node}\n", "error")
            return

        try:
            command = f"{node} {message}\n"
            self.serial_conn.write(command.encode('utf-8'))
            self.log_message(f"Sent to {node}: {message}\n", "sent")
        except Exception as e:
            self.log_message(f"Send error: {str(e)}\n", "error")

    def write_transaction_to_csv(self, data):
        """Write transaction receipt to transaction.csv"""
        try:
            timestamp_str = data['timestamp'].strftime("%Y-%m-%d %H:%M:%S")
            filtered_data = {
                'node_address': data.get('node_address', ''),
                'user_id': data['user_id'],
                'username': data['username'],
                'previous_balance': data['previous_balance'],
                'request_amount': data['request_amount'],
                'new_balance': data['new_balance'],
                'timestamp': timestamp_str
            }

            file_exists = os.path.isfile('transaction.csv')
            with open('transaction.csv', 'a', newline='') as csvfile:
                fieldnames = ['node_address', 'user_id', 'username', 'previous_balance',
                              'request_amount', 'new_balance', 'timestamp']
                writer = csv.DictWriter(csvfile, fieldnames=fieldnames)

                if not file_exists:
                    writer.writeheader()

                writer.writerow(filtered_data)
        except Exception as e:
            self.log_message(f"Error writing to transaction.csv: {str(e)}\n", "error")

    def log_receipt(self, data):
        """Log receipt details to the message display"""
        receipt_msg = (
            f"Receipt - Node: {data.get('node_address', 'N/A')} | User ID: {data['user_id']} | Name: {data['username']} | "
            f"Previous Balance: ₹{data['previous_balance']:.2f} | "
            f"Requested Amount: ₹{data['request_amount']:.2f} | "
            f"New Balance: ₹{data['new_balance']:.2f} | "
            f"Timestamp: {data['timestamp']}\n"
        )
        self.log_message(receipt_msg, "receipt")

    def write_to_csv(self, data):
        """Atomic CSV write operation"""
        try:
            temp_file = self.request_amount_file + ".tmp"
            with open(temp_file, 'a', newline='') as f:
                writer = csv.writer(f)
                if f.tell() == 0:
                    writer.writerow(["Node", "Name", "ID", "Amount", "Timestamp"])
                writer.writerow(data)
            os.replace(temp_file, self.request_amount_file)
        except Exception as e:
            self.log_message(f"CSV Error: {str(e)}\n", "error")

    def process_attendance(self, message, node_address):
        try:
            parts = message.split("ATTENDANCE|")[1].split("|")
            if len(parts) >= 3:
                name = parts[0].strip()
                user_id = parts[1].strip()
                timestamp = parts[2].strip()

                if self.is_duplicate_attendance(user_id, timestamp):
                    self.log_message(f"Duplicate attendance skipped: {name}, {user_id}, {timestamp}\n", "info")
                    return

                # Save to CSV with node address
                self.write_to__attendance_data_csv(self.attendance_file, [node_address, name, user_id, timestamp])

                # Save to MongoDB
                try:
                    success = self.mongo_handler.record_attendance(node_address, user_id, name, timestamp)
                    if success:
                        new_balance = self.mongo_handler.get_balance(user_id)
                        log_msg = (f"Attendance recorded from node {node_address}: {name}, {user_id}, {timestamp}\n"
                                   f"Current balance: ₹{new_balance}\n")
                    else:
                        log_msg = f"Duplicate attendance from node {node_address}: {name}, {user_id}, {timestamp}\n"

                    self.log_message(log_msg, "complete")
                except Exception as mongo_error:
                    self.log_message(f"MongoDB Error: {str(mongo_error)}\n", "info")

            else:
                self.log_message(f"Invalid attendance format: {message}\n", "info")
        except Exception as e:
            self.log_message(f"Error processing attendance: {str(e)}\n", "info")

    def write_to__attendance_data_csv(self, filename, data):
        """Helper method to write data to CSV files"""
        try:
            with open(filename, 'a', newline='') as f:
                csv.writer(f).writerow(data)
        except Exception as e:
            self.log_message(f"CSV Error: {str(e)}", "info")

    def update_balance_display(self, user_id):
        """Update the balance display in the UI"""
        balance = self.mongo_handler.get_balance(user_id)
        self.balance_display.config(text=f"Balance: ₹{balance:.2f}")

    def show_balance(self):
        user_id = self.balance_id_entry.get().strip()
        if user_id:
            try:
                balance = self.mongo_handler.get_balance(user_id)
                self.balance_display.config(text=f"Balance: ₹{balance:.2f}")
            except Exception as e:
                messagebox.showerror("Error", f"Failed to get balance: {str(e)}")

    def create_widgets(self):
        # Create main container with responsive design
        main_container = ttk.Frame(self.root, padding="5")
        main_container.pack(fill=tk.BOTH, expand=True)
        main_container.columnconfigure(0, weight=1)
        main_container.rowconfigure(2, weight=1)  # Message display gets most space

        # Configure style for smaller screens
        style = ttk.Style()
        style.configure('TLabel', font=('Segoe UI', 9))
        style.configure('TButton', font=('Segoe UI', 9))
        style.configure('TEntry', font=('Segoe UI', 9))
        style.configure('TCombobox', font=('Segoe UI', 9))
        style.configure('TLabelFrame', font=('Segoe UI', 9, 'bold'))

        # ========== LOGOS SECTION ==========
        logo_paths = ["logo1.png", "logo2.png", "logo3.png", "logo4.png"]
        logo_images = []

        for path in logo_paths:
            try:
                image = Image.open(path)
                # Smaller logo size for small screens
                image = image.resize((80, 80), Image.LANCZOS)
                logo_images.append(ImageTk.PhotoImage(image))
            except Exception as e:
                print(f"Error loading logo {path}: {e}")
                continue

        if logo_images:
            logo_frame = ttk.Frame(main_container)
            logo_frame.grid(row=0, column=0, sticky="ew", pady=(0, 5))
            logo_frame.columnconfigure(0, weight=1)

            # Center logos in a compact layout
            inner_logo_frame = ttk.Frame(logo_frame)
            inner_logo_frame.pack(expand=True)

            for logo_img in logo_images:
                logo_label = ttk.Label(inner_logo_frame, image=logo_img)
                logo_label.image = logo_img
                logo_label.pack(side=tk.LEFT, padx=3)

        # ========== BALANCE SECTION ==========
        balance_frame = ttk.LabelFrame(main_container, text="User Balance", padding=(8, 4))
        balance_frame.grid(row=1, column=0, sticky="ew", pady=(0, 5))
        balance_frame.columnconfigure(1, weight=1)

        # Compact balance layout
        ttk.Label(balance_frame, text="User ID:").grid(row=0, column=0, sticky="w", padx=(0, 2))
        self.balance_id_entry = ttk.Entry(balance_frame, width=12)
        self.balance_id_entry.grid(row=0, column=1, sticky="w", padx=2)

        self.check_balance_button = ttk.Button(balance_frame, text="Check Balance",
                                               command=self.show_balance)
        self.check_balance_button.grid(row=0, column=2, padx=2)

        self.balance_display = ttk.Label(balance_frame, text="Balance: ₹0.00",
                                         font=('Segoe UI', 9, 'bold'))
        self.balance_display.grid(row=0, column=3, padx=(10, 0), sticky="e")

        # ========== SERIAL CONNECTION SECTION ==========
        connection_frame = ttk.LabelFrame(main_container, text="Serial Connection", padding=(8, 4))
        connection_frame.grid(row=2, column=0, sticky="ew", pady=(0, 5))

        # Responsive grid for connection controls
        connection_frame.columnconfigure(1, weight=1)
        connection_frame.columnconfigure(3, weight=1)

        # Row 0: Port selection
        ttk.Label(connection_frame, text="Port:").grid(row=0, column=0, sticky="w", padx=(0, 2), pady=2)
        self.port_combobox = ttk.Combobox(connection_frame, width=20)
        self.port_combobox.grid(row=0, column=1, sticky="ew", padx=2, pady=2)

        self.refresh_button = ttk.Button(connection_frame, text="Refresh",
                                         command=self.refresh_ports)
        self.refresh_button.grid(row=0, column=2, padx=2, pady=2)

        # Row 1: Baud rate and connect
        ttk.Label(connection_frame, text="Baud:").grid(row=1, column=0, sticky="w", padx=(0, 2), pady=2)
        self.baud_entry = ttk.Entry(connection_frame, width=8)
        self.baud_entry.insert(0, "115200")
        self.baud_entry.grid(row=1, column=1, sticky="w", padx=2, pady=2)

        self.connect_button = ttk.Button(connection_frame, text="Connect",
                                         command=self.toggle_connection)
        self.connect_button.grid(row=1, column=2, padx=2, pady=2)

        # Status indicator
        self.status_label = ttk.Label(connection_frame, text="Disconnected",
                                      font=('Segoe UI', 9, 'bold'), foreground='red')
        self.status_label.grid(row=0, column=3, rowspan=2, padx=10, pady=2, sticky="e")

        # ========== MESSAGE DISPLAY SECTION ==========
        display_frame = ttk.LabelFrame(main_container, text="Messages", padding=(5, 2))
        display_frame.grid(row=3, column=0, sticky="nsew", pady=(0, 5))
        display_frame.columnconfigure(0, weight=1)
        display_frame.rowconfigure(0, weight=1)

        # Message display with smaller font
        self.message_display = scrolledtext.ScrolledText(
            display_frame,
            wrap=tk.WORD,
            state='disabled',
            font=('Consolas', 8),  # Smaller font for small screens
            padx=8,
            pady=8,
            height=12,  # Fixed height that works on small screens
            bd=1,
            relief=tk.SOLID
        )
        self.message_display.grid(row=0, column=0, sticky="nsew")

        # Configure tags for colored text
        self.message_display.tag_config("system", foreground="#4ec9b0")
        self.message_display.tag_config("complete", foreground="#4fc1ff")
        self.message_display.tag_config("chunk", foreground="#d4d4d4")
        self.message_display.tag_config("sent", foreground="#ce9178")
        self.message_display.tag_config("info", foreground="#9cdcfe")
        self.message_display.tag_config("receipt", foreground="#4CAF50", font=('Consolas', 8, 'bold'))
        self.message_display.tag_config("error", foreground="#ff6b6b", font=('Consolas', 8, 'bold'))

        # ========== COMMAND SECTION ==========
        command_frame = ttk.Frame(main_container)
        command_frame.grid(row=4, column=0, sticky="ew", pady=(0, 5))
        command_frame.columnconfigure(1, weight=1)
        command_frame.columnconfigure(3, weight=1)

        ttk.Label(command_frame, text="Node:").grid(row=0, column=0, sticky="w", padx=(0, 2))
        self.node_entry = ttk.Entry(command_frame, width=6)
        self.node_entry.grid(row=0, column=1, sticky="w", padx=2)

        ttk.Label(command_frame, text="Message:").grid(row=0, column=2, sticky="w", padx=(5, 2))
        self.message_entry = ttk.Entry(command_frame)
        self.message_entry.grid(row=0, column=3, sticky="ew", padx=2)

        self.send_button = ttk.Button(command_frame, text="Send",
                                      command=self.send_message)
        self.send_button.grid(row=0, column=4, padx=(5, 0))

        # ========== FILTER & ACTIONS SECTION ==========
        action_frame = ttk.Frame(main_container)
        action_frame.grid(row=5, column=0, sticky="ew", pady=(0, 5))
        action_frame.columnconfigure(1, weight=1)

        # Left side - Filter
        filter_container = ttk.Frame(action_frame)
        filter_container.grid(row=0, column=0, sticky="w")

        ttk.Label(filter_container, text="Filter:").pack(side=tk.LEFT, padx=(0, 2))
        self.filter_entry = ttk.Entry(filter_container, width=15)
        self.filter_entry.pack(side=tk.LEFT, padx=2)
        self.filter_entry.bind('<KeyRelease>', self.apply_filter)

        # Right side - Action buttons (compact layout)
        button_container = ttk.Frame(action_frame)
        button_container.grid(row=0, column=1, sticky="e")

        # Smaller buttons for file access
        self.open_attendance_button = ttk.Button(button_container, text="Attendance",
                                                 command=lambda: self.open_file(self.attendance_file),
                                                 width=10)
        self.open_attendance_button.pack(side=tk.RIGHT, padx=(2, 0))

        self.open_request_button = ttk.Button(button_container, text="Requests",
                                              command=lambda: self.open_file(self.request_amount_file),
                                              width=8)
        self.open_request_button.pack(side=tk.RIGHT, padx=2)

        self.clear_button = ttk.Button(button_container, text="Clear",
                                       command=self.clear_display, width=6)
        self.clear_button.pack(side=tk.RIGHT, padx=2)

        # Populate ports
        self.refresh_ports()

        # Bind Enter key to send message
        self.message_entry.bind('<Return>', lambda e: self.send_message())
        self.balance_id_entry.bind('<Return>', lambda e: self.show_balance())

    def open_file(self, filename):
        try:
            os.startfile(filename)
        except:
            try:
                import subprocess
                subprocess.call(('open', filename))
            except:
                messagebox.showinfo("File Location", f"File saved to:\n{os.path.abspath(filename)}")

    def refresh_ports(self):
        ports = serial.tools.list_ports.comports()
        self.port_combobox['values'] = [port.device for port in ports]
        if ports:
            self.port_combobox.current(0)

    def toggle_connection(self):
        if self.serial_conn and self.serial_conn.is_open:
            self.disconnect_serial()
        else:
            self.connect_serial()

    def connect_serial(self):
        port = self.port_combobox.get()
        baud = self.baud_entry.get()

        if not port:
            messagebox.showerror("Error", "Please select a serial port")
            return

        try:
            baud = int(baud)
        except ValueError:
            messagebox.showerror("Error", "Invalid baud rate")
            return

        try:
            self.serial_conn = serial.Serial(port, baud, timeout=1)
            self.serial_conn.reset_input_buffer()
            self.stop_event.clear()
            self.serial_thread = Thread(target=self.read_serial, daemon=True)
            self.serial_thread.start()

            self.connect_button.config(text="Disconnect")
            self.status_label.config(text="Connected", foreground='green')
            self.log_message(f"Connected to {port} at {baud} baud\n", "system")

        except serial.SerialException as e:
            messagebox.showerror("Error", f"Failed to connect: {str(e)}")

    def disconnect_serial(self):
        self.stop_event.set()
        if self.serial_thread and self.serial_thread.is_alive():
            self.serial_thread.join()

        if self.serial_conn and self.serial_conn.is_open:
            self.serial_conn.close()

        self.connect_button.config(text="Connect")
        self.status_label.config(text="Disconnected", foreground='red')
        self.log_message("Disconnected from serial port\n", "system")

    def read_serial(self):
        while not self.stop_event.is_set():
            if self.serial_conn and self.serial_conn.is_open:
                try:
                    line = self.serial_conn.readline().decode('utf-8', errors='replace').strip()
                    if line:
                        self.message_queue.put(("serial", line))
                except serial.SerialException as e:
                    self.message_queue.put(("system", f"Serial error: {str(e)}"))
                    time.sleep(0.1)
                except UnicodeDecodeError:
                    self.message_queue.put(("system", "Received non-UTF-8 data"))
            else:
                time.sleep(0.1)

    def process_queue(self):
        try:
            while not self.message_queue.empty():
                source, message = self.message_queue.get_nowait()
                self.message_history.append((source, message))

                if source == "serial":
                    self.process_serial_message(message)
                else:
                    self.log_message(message + "\n", source)
        except queue.Empty:
            pass

        self.root.after(100, self.process_queue)

    def log_message(self, message, msg_type):
        self.message_display.config(state='normal')

        filter_text = self.filter_entry.get().lower()
        if not filter_text or filter_text in message.lower():
            self.message_display.insert(tk.END, message, msg_type)
            self.message_display.see(tk.END)

        self.message_display.config(state='disabled')

    def send_message(self):
        if not self.serial_conn or not self.serial_conn.is_open:
            messagebox.showerror("Error", "Not connected to serial port")
            return

        node = self.node_entry.get().strip()
        message = self.message_entry.get().strip()

        if not node or not message:
            messagebox.showerror("Error", "Please enter both node ID and message")
            return

        if not re.match(r'^[0-9a-fA-F]+$', node):
            messagebox.showerror("Error", "Node ID must be in hex format (e.g., '01' or 'AA')")
            return

        command = f"{node} {message}\n"
        try:
            self.serial_conn.write(command.encode('utf-8'))
            self.log_message(f"Sent: {command}", "sent")
            self.message_entry.delete(0, tk.END)
        except serial.SerialException as e:
            messagebox.showerror("Error", f"Failed to send message: {str(e)}")

    def apply_filter(self, event=None):
        self.message_display.config(state='normal')
        self.message_display.delete(1.0, tk.END)

        filter_text = self.filter_entry.get().lower()

        for source, message in self.message_history:
            if source == "serial":
                if "COMPLETE from" in message:
                    msg_type = "complete"
                elif "From:0x" in message:
                    msg_type = "chunk"
                elif "Sent chunk" in message:
                    msg_type = "sent"
                else:
                    msg_type = "info"
            else:
                msg_type = source

            if not filter_text or filter_text in message.lower():
                self.message_display.insert(tk.END, message + "\n", msg_type)

        self.message_display.see(tk.END)
        self.message_display.config(state='disabled')

    def clear_display(self):
        self.message_display.config(state='normal')
        self.message_display.delete(1.0, tk.END)
        self.message_display.config(state='disabled')
        self.message_history = []

    def on_closing(self):
        self.disconnect_serial()
        self.root.destroy()


def main():
    root = tk.Tk()
    app = LoRaSerialMonitor(root)
    root.protocol("WM_DELETE_WINDOW", app.on_closing)
    root.mainloop()


if __name__ == "__main__":
    main()