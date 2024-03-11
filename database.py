import psycopg2
from threading import Lock

class DatabaseManager:
    def __init__(self, db_params={'host': 'your_host', 'database': 'your_database', 'user': 'your_user', 'password': 'your_password', 'port': 'your_port'}):
        # Connect to the database
        self.conn = psycopg2.connect(**db_params)
        self.cursor = self.conn.cursor()
        self.lock = Lock()

        # Create the users table if it does not exist
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id SERIAL PRIMARY KEY,
                phone_number TEXT NOT NULL,
                balance BIGINT NOT NULL
            )
        ''')

        # Create the telegram-phone table if it does not exist
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS assoc (
                user_id BIGINT NOT NULL PRIMARY KEY,
                phone_number TEXT NOT NULL
            )
        ''')

        # Create the pending_actions table if it does not exist
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS pending_actions (
                id SERIAL PRIMARY KEY,
                user_phone_number TEXT NOT NULL,
                receiver_phone_number TEXT NOT NULL,
                amount BIGINT NOT NULL,
                comment TEXT NOT NULL
            )
        ''')

        # Create the actions table if it does not exist
        self.cursor.execute('''
            CREATE TABLE IF NOT EXISTS actions (
                id SERIAL PRIMARY KEY,
                user_phone_number TEXT NOT NULL,
                receiver_phone_number TEXT NOT NULL,
                amount BIGINT NOT NULL,
                md5 TEXT NOT NULL
            )
        ''')

        self.conn.commit()

    def add_user(self, phone_number):
        # Self-explanatory
        with self.lock:
            self.cursor.execute('INSERT INTO users (phone_number, balance) VALUES (%s, 0)', (phone_number,))
            self.conn.commit()

    def get_user(self, phone_number):
        # Self-explanatory
        with self.lock:
            self.cursor.execute('SELECT * FROM users WHERE phone_number=%s', (phone_number,))
            return self.cursor.fetchone()

    def add_assoc(self, user_id, phone_number):
        with self.lock:
            # Add association between telegram user id and a phone number
            self.cursor.execute('INSERT INTO assoc (user_id, phone_number) VALUES (%s, %s)', (user_id, phone_number))
            self.conn.commit()

    def get_assoc(self, user_id):
        with self.lock:
            # Self-explanatory
            self.cursor.execute('SELECT phone_number FROM assoc WHERE user_id=%s', (user_id,))
            return self.cursor.fetchone()

    def get_reverse_assoc(self, phone_number):
        with self.lock:
            # Self-explanatory
            self.cursor.execute('SELECT user_id FROM assoc WHERE phone_number=%s', (phone_number,))
            return self.cursor.fetchone()

    def get_balance(self, phone_number):
        with self.lock:
            self.cursor.execute('SELECT balance FROM users WHERE phone_number=%s', (phone_number,))
            return self.cursor.fetchone()

    def get_all_pending_actions(self):
        with self.lock:
            self.cursor.execute('SELECT * FROM pending_actions')
            return self.cursor.fetchall()

    def create_pending_action(self, user_phone_number, receiver_phone_number, amount, comment):
        # Self-explanatory
        with self.lock:
            self.cursor.execute('INSERT INTO pending_actions (user_phone_number, receiver_phone_number, amount, comment) VALUES (%s, %s, %s, %s)', (user_phone_number, receiver_phone_number, amount, comment))
            self.conn.commit()

    def remove_pending_action(self, id):
        # Self-explanatory
        with self.lock:

            self.cursor.execute('SELECT user_phone_number FROM pending_actions WHERE id=%s', (id,))
            recv_phone = self.cursor.fetchone()
            if recv_phone:
                self.cursor.execute('DELETE FROM pending_actions WHERE id=%s', (id,))
                self.conn.commit()
                return recv_phone[0]
            return None

    def apply_pending_action(self, id, md5):
        # Retrieve data from pending_actions
        with self.lock:
            self.cursor.execute('SELECT user_phone_number, receiver_phone_number, amount FROM pending_actions WHERE id=%s', (id,))
            pending_action_data = self.cursor.fetchone()

            if pending_action_data:
                user_phone_number, receiver_phone_number, amount = pending_action_data

                # Update sender's balance (decrease by amount)
                self.cursor.execute('UPDATE users SET balance = balance - %s WHERE phone_number=%s', (amount, user_phone_number))

                # Update receiver's balance (increase by amount)
                self.cursor.execute('UPDATE users SET balance = balance + %s WHERE phone_number=%s', (amount, receiver_phone_number))

                # Remove from pending_actions
                self.cursor.execute('DELETE FROM pending_actions WHERE id=%s', (id,))
                self.conn.commit()

                # Add to actions
                self.cursor.execute('INSERT INTO actions (user_phone_number, receiver_phone_number, amount, md5) VALUES (%s, %s, %s, %s)', (user_phone_number, receiver_phone_number, amount, md5))
                self.conn.commit()

                return (user_phone_number, receiver_phone_number)
            return None

    def get_last_md5(self):
        # Self-explanatory
        with self.lock:
            self.cursor.execute('SELECT md5 FROM actions ORDER BY id DESC LIMIT 1')
            return self.cursor.fetchone()
