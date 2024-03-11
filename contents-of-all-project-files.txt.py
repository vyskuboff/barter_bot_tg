api.py
from flask import Flask, jsonify, request
from database import DatabaseManager
import hashlib
import requests


class API:
    def __init__(self, token: str, db: DatabaseManager):
        self.app = Flask("telegram_flashback_api")
        self.db = db
        self.token = token

        # Manually set routes up
        self.app.route('/pending', methods=['GET'])(self.pending)
        self.app.route('/approve/<int:id>', methods=['POST'])(self.approve)
        self.app.route('/remove/<int:id>', methods=['POST'])(self.remove)
        self.app.route('/lastkey', methods=['GET'])(self.lastkey)

    def send_message(self, chat_id, text):
        base_url = f"https://api.telegram.org/bot{self.token}/sendMessage"
        params = {
            'chat_id': chat_id,
            'text': text,
        }

        response = requests.post(base_url, params=params)
        result = response.json()
        if not result['ok']:
            print(f"Failed to send message. Telegram API response: {result}")

    def lastkey(self):
        md5 = self.db.get_last_md5()
        if md5:
            return md5[0]
        else:
            return "NO", 200

    async def auth(self, received_md5):
        latest_md5 = self.db.get_last_md5()

        if not received_md5:
            return None

        if not latest_md5:
            return received_md5

        calculated_md5 = hashlib.md5(received_md5.encode()).hexdigest()

        if calculated_md5 == latest_md5[0]:
            return received_md5
        else:
            return None

    # Return pending actions
    async def pending(self):
        md5 = await self.auth(request.args.get('md5'))
        if not md5:
            return jsonify({'error': 'Failed to authenticate'}), 401

        pending_actions = self.db.get_all_pending_actions()
        result = []
        for action in pending_actions:
            balance = self.db.get_balance(action[1])
            ltz = balance[0] < action[3]
            result.append({
                'id': action[0],
                'sender_phone': action[1],
                'receiver_phone': action[2],
                'amount': action[3],
                'comment': action[4],
                'less_than_zero': ltz,
            })
        return jsonify(result)

    # Move pending action to a db with correct md5
    async def approve(self, id):
        md5 = await self.auth(request.json.get('md5'))
        if not md5:
            return jsonify({'error': 'Failed to authenticate'}), 401

        dbres = self.db.apply_pending_action(id, md5)

        if not (dbres == None):
            # Send message
            snd_phone, recv_phone, amount = dbres
            snd_id = self.db.get_reverse_assoc(snd_phone)[0]
            recv_id = self.db.get_reverse_assoc(recv_phone)[0]
            self.send_message(snd_id, f"Заявка на передачу {amount} BCR одобрена. Вы отправили {amount} BCR пользователю {recv_phone}. Не забудьте оплатить налог самозанятого с потраченной суммы!")
            self.send_message(recv_id, f"Вы получили {amount} BCR от пользователя {snd_phone}")
            return jsonify({'message': 'Action moved to actions successfully'})
        else:
            return jsonify({'error': 'Action ID not found'}), 400

    # Remove a pending action
    async def remove(self, id):
        md5 = await self.auth(request.json.get('md5'))
        if not md5:
            return jsonify({'error': 'Failed to authenticate'}), 401
        result = self.db.remove_pending_action(id)
        if result:
            # Send message
            recv_phone, amount = result
            snd_id = self.db.get_reverse_assoc(recv_phone)[0]
            self.send_message(snd_id, f"Заявка на передачу {amount} BCR, пользователю {recv_phone} отклонена")
            return jsonify({'message': 'Action removed successfully'})
        else:
            return jsonify({'error': 'Action ID not found'}), 400

    def run(self):
        from waitress import serve
        serve(self.app, host="0.0.0.0", port=5000)


bot.py
import re
import math
import asyncio
from decimal import Decimal
from database import DatabaseManager
from telegram import Update, ReplyKeyboardMarkup, InlineKeyboardMarkup, KeyboardButton, InlineKeyboardButton, ReplyKeyboardRemove
from telegram.ext import (
    Application,
    CallbackContext,
    CallbackQueryHandler,
    CommandHandler,
    MessageHandler,
    filters,
)

class TelegramBot:

    def __init__(self, TOKEN: str, db: DatabaseManager):
        self._db = db
        self.application = Application.builder().token(TOKEN).build()

    # Operating markup
    op_markup = InlineKeyboardMarkup(
        [
            [
                InlineKeyboardButton("Баланс", callback_data="balance"),
                InlineKeyboardButton("Отправить", callback_data="send"),
            ]
        ]
    )

    # Command handler for /start command
    async def start(self, update: Update, context: CallbackContext) -> None:
        # Check if the user is already registered
        phone = self._db.get_assoc(update.message.chat.id)
        markup = ReplyKeyboardMarkup(
            [[KeyboardButton("Отправить номер телефона", request_contact=True)]],
            one_time_keyboard=True,
        )

        if phone:
            await update.message.reply_text("Вы уже авторизовались ранее")
        else:
            await update.message.reply_text(
                "Пожалуйста, укажите ваш номер телефона для входа", reply_markup=markup
            )


    # Message handler for receiving phone number
    async def phone_auth(self, update: Update, context: CallbackContext) -> None:
        def clean_phone(phone_number):
            match = re.findall(r'\d', phone_number)
            cleaned_number = '+' + ''.join(match)
            return cleaned_number

        user_id = update.message.chat.id
        phone_number = clean_phone(update.message.contact.phone_number)
        contact_id = update.message.contact.user_id
        phone = self._db.get_assoc(update.message.chat.id)

        if phone:
            await update.message.reply_text(
                "Контекст отправки контакта неясен", reply_markup=self.op_markup
            )
        
        elif not contact_id == user_id:
            await update.message.reply_text(
                "Вероятно, вы отправили не свой контакт, повторите попытку входа",
                reply_markup=self.op_markup
            )
        else:
            # Store the user in the database
            self._db.add_assoc(user_id, phone_number)

            if (not self._db.get_user(phone_number)):
                self._db.add_user(phone_number)

            await update.message.reply_text(
                f"Номер {phone_number} был успешно связан с вашей учётной записью",
                reply_markup=ReplyKeyboardRemove()
            )
            await update.message.reply_text(
                "Используйте кнопки ниже для выполнения действий",
                reply_markup=self.op_markup
            )

    # 'balance' and 'send' handler
    async def keyboard_handler(self, update: Update, context: CallbackContext) -> None:
        user_id = update.callback_query.from_user.id
        button_data = update.callback_query.data
        query = update.callback_query
        phone = self._db.get_assoc(user_id)
        if not phone:
            await update.callback_query.message.reply_text("Вы не авторизованы, попробуйте прописать /start")
            await query.answer()
            return
        


        # Effectively disabling sending
        context.user_data['sending'] = False

        # Check if the pressed button has the callback_data 'button_A'
        if button_data == 'balance':
            await update.callback_query.message.reply_text(f"Ваш баланс: {self._db.get_balance(phone)[0]}", reply_markup=self.op_markup)
        elif button_data == 'send':
            await update.callback_query.message.reply_text("Введите номер телефона контрагента для перевода")
            context.user_data['sending'] = True
            context.user_data['phone'] = None
            context.user_data['amount'] = None
        else:
            await update.callback_query.message.reply_text("Неизвестная команда")
        
        await query.answer()

    # Message handler for sending balance
    async def send_handler(self, update: Update, context: CallbackContext) -> None:
        def clean_phone_number(phone_number):

            if not phone_number.startswith("+"):
                return None
            
            if len(phone_number) > 15:
                return None

            match = re.findall(r'\d', phone_number)

            if match:
                cleaned_number = '+' + ''.join(match)
                return cleaned_number
            else:
                return None

        def clean_int(input_string):
            if len(input_string) > 16:
                return 0
            try:
                # Try to convert the input string to a Decimal
                number = Decimal(input_string)
                
                # Check if the number is a rational number
                if number % 1 == 0:
                    # If it's an integer, return it as is
                    return int(number)
                else:
                    # If it's a rational number, ceil it
                    return math.ceil(number)
            except:
                # If the conversion fails, it's not a number
                return 0

        if context.user_data.get("sending") == False:
            return

        user_id = context._user_id
        snd_phone = self._db.get_assoc(user_id)
        recv_phone = context.user_data.get("phone")
        recv_amount = context.user_data.get("amount")
        phone = self._db.get_assoc(user_id)
        if not phone:
            await update.message.reply_text("Вы не авторизованы, попробуйте прописать /start")
            return
        
        
        if recv_phone == None:
            # Handling phone
            phone = clean_phone_number(update.message.text)
            if phone:
                user = self._db.get_user(phone)
                
                if not user:
                    await update.message.reply_text("Пользователь не найден. Введите номер телефона контрагента для перевода")
                    return

                context.user_data['phone'] = phone
                await update.message.reply_text("Введите количество")
            else:
                await update.message.reply_text("Номер введён неверно, попробуйте ещё раз. Формат: +x (xxx) xxx xx-xx")
        elif recv_amount == None:
            # Handling amount
            amount = clean_int(update.message.text)
            if (amount > 0):
                context.user_data['amount'] = amount
                await update.message.reply_text("Введите комментарий")
            else:
                await update.message.reply_text("Число введёно неверно, попробуйте ещё раз")
        else:
            # Handling comment
            comment = update.message.text
            context.user_data['phone'] = None
            context.user_data['amount'] = None
            self._db.create_pending_action(amount=recv_amount, user_phone_number=snd_phone[0], receiver_phone_number=recv_phone, comment=comment)
            await update.message.reply_text(f"Запрос на передачу баланса в размере {recv_amount} BCR, пользователю {recv_phone} отправлен")


    def run(self):
        # Add command handlers
        self.application.add_handler(CommandHandler("start", self.start))

        # Add message handler for receiving phone number for authentication
        self.application.add_handler(MessageHandler(filters.CONTACT, self.phone_auth))

        # Add message handler for receiving button callbacks
        self.application.add_handler(CallbackQueryHandler(self.keyboard_handler))

        # Add message handler for sending
        self.application.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, self.send_handler))

        # Start the bot
        self.application.run_polling(allowed_updates=Update.ALL_TYPES)


config.py
TOKEN_TG_BOT = 'TOKEN'
passworddb = "password"

database.py
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

            self.cursor.execute('SELECT user_phone_number, amount FROM pending_actions WHERE id=%s', (id,))
            result = self.cursor.fetchone()
            if result:
                recv_phone, amount = result
                self.cursor.execute('DELETE FROM pending_actions WHERE id=%s', (id,))
                self.conn.commit()
                return recv_phone, amount
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

                return (user_phone_number, receiver_phone_number, amount)
            return None

    def get_last_md5(self):
        # Self-explanatory
        with self.lock:
            self.cursor.execute('SELECT md5 FROM actions ORDER BY id DESC LIMIT 1')
            return self.cursor.fetchone()



main.py
import logging
from multiprocessing import Process
from database import DatabaseManager
from bot import TelegramBot
from api import API
from config import TOKEN_TG_BOT, passworddb

# Telegram API token
TOKEN = TOKEN_TG_BOT

if __name__ == "__main__":
    # Set up logging
    logging.basicConfig(
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        level=logging.INFO,
    )

    # Set up database
    db_manager = DatabaseManager(
        {
            "host": "127.0.0.1",
            "port": "5432",
            "database": "postgres",
            "user": "postgres",
            "password": passworddb,
        }
    )

    # Run bot
    tb = TelegramBot(TOKEN, db_manager)
    tb_th = Process(target=tb.run)
    tb_th.start()

    # Run API
    api = API(TOKEN, db_manager)
    api.run()

    # Shutdown a bot after an API
    tb_th.terminate()
    tb_th.join()
