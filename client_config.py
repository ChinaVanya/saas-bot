import os

# URL Mini App (тот же что в master_config)
MINI_APP_URL = os.environ.get("MINI_APP_URL", "https://your-project.railway.app/app")

# CLIENT_TOKENS больше не нужен — токены клиентов хранятся в базе данных
# client_bot.py сам читает их из БД при старте
