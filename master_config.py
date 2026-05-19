import os

# Токен главного бота — берётся из переменной окружения
MASTER_TOKEN = os.environ["MASTER_TOKEN"]

# Твой Telegram ID (можно несколько через запятую в .env: "123,456")
_ids = os.environ.get("MASTER_IDS", "")
MASTER_IDS = [int(x.strip()) for x in _ids.split(",") if x.strip()]

# URL мини-апа после деплоя на Railway
MINI_APP_URL = os.environ.get("MINI_APP_URL", "https://your-project.railway.app/app")
