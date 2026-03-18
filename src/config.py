from os import getenv

TOKEN = getenv("TOKEN")

DB_NAME = getenv("DB_NAME", "mydatabase")
DB_USER = getenv("DB_USER", "myuser")
DB_PASS = getenv("DB_PASS", "mypassword")
DB_HOST = getenv("DB_HOST", "localhost")
PROXY = getenv("PROXY", None)
DB_PORT = getenv("DB_PORT", "5432")
ADMIN_IDS = list(
    set(
        map(
            int,
            getenv("ADMIN_IDS", "1057741026, 1268851631, 5086271521")
            .replace(" ", "")
            .split(","),
        )
    )
)
