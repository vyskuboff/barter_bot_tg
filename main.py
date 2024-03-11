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
