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
