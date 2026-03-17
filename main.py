import asyncio
import json
import logging
import os
import random
from typing import Optional, Union

import asyncpg
from aiogram import Bot, Dispatcher, F, Router
from aiogram.filters import Command, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.fsm.storage.memory import MemoryStorage
from aiogram.types import (
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    Message,
    ReplyKeyboardMarkup,
    ReplyKeyboardRemove,
)

logging.basicConfig(
    format="%(asctime)s - %(name)s - %(levelname)s",
    level=logging.INFO,
)
logger = logging.getLogger(__name__)

TOKEN = ""
api_key = ""

DB_NAME = "mydatabase"
DB_USER = "myuser"
DB_PASSWORD = "mypassword"
DB_HOST = "localhost"
DB_PORT = "5432"

ADMIN_IDS = {1057741026, 1268851631, 5086271521}

router = Router()
db_pool: Optional[asyncpg.Pool] = None


class ProfileStates(StatesGroup):
    NAME = State()
    SEX = State()
    AGE = State()
    CITY = State()
    DESCRIPTION = State()
    PHOTO = State()
    SONG = State()
    AUDIO = State()
    PREFERENCES = State()


class AdminStates(StatesGroup):
    waiting_admin_id = State()
    waiting_recover_id = State()


class BroadcastStates(StatesGroup):
    waiting_for_text = State()
    waiting_for_photo = State()


class MessageStates(StatesGroup):
    awaiting_message = State()


async def create_db_pool():
    global db_pool
    db_pool = await asyncpg.create_pool(
        database=DB_NAME,
        user=DB_USER,
        password=DB_PASSWORD,
        host=DB_HOST,
        port=int(DB_PORT),
        min_size=1,
        max_size=10,
    )


def get_pool() -> asyncpg.Pool:
    if db_pool is None:
        raise RuntimeError("DB pool is not initialized")
    return db_pool


async def fetchval(query: str, *args):
    async with get_pool().acquire() as conn:
        return await conn.fetchval(query, *args)


async def fetchrow(query: str, *args):
    async with get_pool().acquire() as conn:
        return await conn.fetchrow(query, *args)


async def fetch(query: str, *args):
    async with get_pool().acquire() as conn:
        return await conn.fetch(query, *args)


async def execute(query: str, *args):
    async with get_pool().acquire() as conn:
        return await conn.execute(query, *args)


async def executemany(query: str, args_list):
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            await conn.executemany(query, args_list)


async def reply_denied(target: Union[Message, CallbackQuery]):
    text = (
        "Это клуб для крутых и им пользутся только админы.\n"
        "Возвращайся, когда станешь достаточно хорош"
    )
    if isinstance(target, CallbackQuery):
        if target.message:
            await target.message.answer(text)
        return
    await target.answer(text)


async def ensure_admin_roles():
    async with get_pool().acquire() as conn:
        for admin_id in ADMIN_IDS:
            await conn.execute(
                "UPDATE users SET role = 2 WHERE telegram_id = $1",
                admin_id,
            )


async def create_tables():
    async with get_pool().acquire() as conn:
        await conn.execute("""
            CREATE TABLE IF NOT EXISTS preferences (
                pref_id integer NOT NULL,
                preference character varying(32) NOT NULL,
                PRIMARY KEY (pref_id)
            );
        """)
        check = await conn.fetch("SELECT * FROM preferences")
        if not check:
            await conn.execute("INSERT INTO preferences (pref_id, preference) VALUES (1, 'Мужчины')")
            await conn.execute("INSERT INTO preferences (pref_id, preference) VALUES (2, 'Девушки')")
            await conn.execute("INSERT INTO preferences (pref_id, preference) VALUES (3, 'Все')")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS roles (
                role_id integer NOT NULL,
                role character varying(8) NOT NULL,
                PRIMARY KEY (role_id)
            );
        """)
        check = await conn.fetch("SELECT * FROM roles")
        if not check:
            await conn.execute("INSERT INTO roles (role_id, role) VALUES (1, 'User')")
            await conn.execute("INSERT INTO roles (role_id, role) VALUES (2, 'Admin')")
            await conn.execute("INSERT INTO roles (role_id, role) VALUES (3, 'Banned')")
            await conn.execute("INSERT INTO roles (role_id, role) VALUES (4, 'Premium')")
            await conn.execute("INSERT INTO roles (role_id, role) VALUES (5, 'True')")

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS users (
                telegram_id bigint NOT NULL,
                name character varying(16) NOT NULL,
                sex character varying(8) NOT NULL,
                age integer NOT NULL,
                city character varying(32) NOT NULL,
                description text,
                photo text,
                song text,
                region character varying(32),
                preferences integer DEFAULT 3,
                reports integer DEFAULT 0,
                role integer DEFAULT 1,
                PRIMARY KEY (telegram_id),
                CONSTRAINT preferences FOREIGN KEY (preferences)
                    REFERENCES preferences (pref_id)
                    NOT VALID,
                CONSTRAINT roles FOREIGN KEY (role)
                    REFERENCES roles (role_id)
                    NOT VALID
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS likes (
                like_id serial NOT NULL,
                liker_id bigint,
                liked_id bigint,
                content text,
                PRIMARY KEY (like_id),
                CONSTRAINT liker_id FOREIGN KEY (liker_id)
                    REFERENCES users (telegram_id)
                    NOT VALID,
                CONSTRAINT liked_id FOREIGN KEY (liked_id)
                    REFERENCES users (telegram_id)
                    NOT VALID
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS dislikes (
                dlike_id serial NOT NULL,
                dliker_id bigint,
                dliked_id bigint,
                PRIMARY KEY (dlike_id),
                CONSTRAINT dliker_id FOREIGN KEY (dliker_id)
                    REFERENCES users (telegram_id)
                    NOT VALID,
                CONSTRAINT dliked_id FOREIGN KEY (dliked_id)
                    REFERENCES users (telegram_id)
                    NOT VALID
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS reports (
                rep_id serial NOT NULL,
                reporter bigint,
                reported bigint,
                PRIMARY KEY (rep_id),
                CONSTRAINT reporter FOREIGN KEY (reporter)
                    REFERENCES users (telegram_id)
                    NOT VALID,
                CONSTRAINT reported FOREIGN KEY (reported)
                    REFERENCES users (telegram_id)
                    NOT VALID
            );
        """)

        await conn.execute("""
            CREATE TABLE IF NOT EXISTS location (
                name VARCHAR(255),
                district VARCHAR(255),
                subject VARCHAR(255),
                population INTEGER,
                lat NUMERIC,
                lon NUMERIC
            );
        """)
        await conn.execute("CREATE INDEX IF NOT EXISTS idx_district ON location (district);")

    logger.info("Все таблицы успешно созданы.")


async def create_and_populate_location_table():
    path = "/home/ubuntu/countries"
    if not os.path.exists(path):
        logger.warning("Директория %s не найдена, пропускаю заполнение location", path)
        return

    files = [f for f in os.listdir(path) if f.endswith(".json")]
    rows = []

    for file in files:
        with open(os.path.join(path, file), "r", encoding="utf-8") as f:
            data = json.load(f)
            for city in data:
                rows.append((
                    city["name"],
                    city["district"],
                    city["subject"],
                    city["population"],
                    city["coords"]["lat"],
                    city["coords"]["lon"],
                ))

    if rows:
        await executemany("""
            INSERT INTO location (name, district, subject, population, lat, lon)
            VALUES ($1, $2, $3, $4, $5, $6)
        """, rows)


async def update_users_table_with_location():
    async with get_pool().acquire() as conn:
        await conn.execute("""
            ALTER TABLE users
            ADD COLUMN IF NOT EXISTS district VARCHAR(255)
        """)

        users = await conn.fetch("SELECT city, region FROM users")
        for user in users:
            city = user["city"]

            location_match = await conn.fetchrow("""
                SELECT district, subject FROM location WHERE name = $1
            """, city)

            if location_match:
                district = location_match["district"]
                subject = location_match["subject"]
                await conn.execute("""
                    UPDATE users
                    SET region = $1, district = $2
                    WHERE city = $3
                """, subject, district, city)
            else:
                await conn.execute("""
                    UPDATE users
                    SET district = 'Центральный'
                    WHERE city = $1
                """, city)


async def check_db_connection() -> str:
    try:
        user_count = await fetchval("SELECT COUNT(*) FROM users")
        return (
            "Приветствую! Подключение к базе данных успешно установлено. "
            f"Количество пользователей в системе: {user_count}."
        )
    except Exception as e:
        logger.error("Ошибка при подключении к базе данных: %s", e)
        return f"Ошибка при подключении к базе данных: {e}"


async def check_user_exists(user_id: int):
    try:
        return await fetchrow("SELECT * FROM users WHERE telegram_id = $1", user_id)
    except Exception as e:
        logger.error("Ошибка при проверке пользователя: %s", e)
        return None


async def is_user_banned(telegram_id: int) -> bool:
    role = await fetchval("SELECT role FROM users WHERE telegram_id = $1", telegram_id)
    return role == 3


async def checkrole(telegram_id: int) -> bool:
    role = await fetchval("SELECT role FROM users WHERE telegram_id = $1", telegram_id)
    return role == 2


async def getpref(pref_id: int):
    return await fetchval("SELECT preference FROM preferences WHERE pref_id = $1", pref_id)


async def getrole(role_id: int):
    return await fetchval("SELECT role FROM roles WHERE role_id = $1", role_id)


async def save_data(user_id, name, sex, age, city, description, photo, song, region, preferences):
    await execute("""
        INSERT INTO users (
            telegram_id, name, sex, age, city, description, photo, song, region, preferences
        ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
    """, user_id, name, sex, age, city, description, photo, song, region, preferences)


async def delete_data(user_id: int):
    async with get_pool().acquire() as conn:
        async with conn.transaction():
            await conn.execute("DELETE FROM likes WHERE liker_id = $1 OR liked_id = $2", user_id, user_id)
            await conn.execute("DELETE FROM dislikes WHERE dliker_id = $1 OR dliked_id = $2", user_id, user_id)
            await conn.execute("DELETE FROM reports WHERE reporter = $1 OR reported = $2", user_id, user_id)
            await conn.execute("DELETE FROM users WHERE telegram_id = $1", user_id)


RULES_TEXT = """ Бот принадлежит сообществу 'Мы знакомимся с худыми блэкаршами' https://t.me/metaldating
Ознакомьтесь с пользовательским соглашением! https://t.me/c/2162958124/49

Простыми словами:
1) Пользователь обязуется предоставлять достоверные и актуальные данные при регистрации и использовании Бота.
2) Запрещено нарушать любые законы Российской Федерации (никакого экстризма, эротики, пропаганды).
3) Пользователь использует Бот на свой страх и риск, мы не несем ответственности за любые убытки, возникшие в результате использования.

Касаемо наших пожеланий к вам: смело и активно кидайте жалобы 🚩 на всех, кто нарушает правила сообщества.
В том числе кидайте жалобы всем, кто здесь не по теме Бота! Мы обязательно будет банить.
Уважайте друг друга!
"""


@router.message(Command("rules"))
async def rules(message: Message):
    await message.answer(RULES_TEXT)


@router.message(Command("start"))
async def start(message: Message, state: FSMContext):
    user_id = message.from_user.id

    if await is_user_banned(user_id):
        await message.answer(
            "Вы заблокированы и не можете создать анкету. Бот для вас теперь платный. "
            "Если хотите разбан, пишите сюда: @Ebalteadm\n"
            "Этот бот вам пригодится: @userinfobot"
        )
        await state.clear()
        return

    db_status = await check_db_connection()
    await message.answer(db_status)

    user = await check_user_exists(user_id)
    if user:
        await message.answer("Вы уже зарегистрированы. Вот ваша анкета:")
        await show_profile(message, my=False)
        return

    await message.answer("Введите ваше имя (слитно):")
    await state.set_state(ProfileStates.NAME)


@router.message(Command("editprofile"))
async def editprofile(message: Message, state: FSMContext):
    user = await check_user_exists(message.from_user.id)
    if user:
        await delete_profile(message, state, edit=True)
        await message.answer("Введите ваше имя (слитно):")
        await state.set_state(ProfileStates.NAME)


@router.message(ProfileStates.NAME, F.text)
async def handle_name(message: Message, state: FSMContext):
    name = message.text
    if not name.isalpha():
        await message.answer("Имя должно быть слитным и содержать только буквы. Попробуйте снова:")
        return

    await state.update_data(name=name)
    await message.answer(
        "Выберите ваш пол:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="Мужской"), KeyboardButton(text="Женский")]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )
    await state.set_state(ProfileStates.SEX)


@router.message(ProfileStates.SEX, F.text)
async def handle_sex(message: Message, state: FSMContext):
    sex = message.text
    if "м" in sex.lower():
        await state.update_data(sex="Мужской")
    elif "ж" in sex.lower():
        await state.update_data(sex="Женский")
    else:
        await message.answer("Выберите пол из предложенных вариантов: Мужской или Женский.")
        return

    await message.answer("Введите ваш возраст (от 14 до 80 лет):")
    await state.set_state(ProfileStates.AGE)


@router.message(ProfileStates.AGE, F.text)
async def handle_age(message: Message, state: FSMContext):
    age = message.text
    if not age.isdigit() or not (14 <= int(age) <= 80):
        await message.answer("Возраст должен быть числом от 14 до 80. Попробуйте снова:")
        return

    await state.update_data(age=int(age))
    await message.answer("Введите ваш город (на русском языке):", reply_markup=ReplyKeyboardRemove())
    await state.set_state(ProfileStates.CITY)


@router.message(ProfileStates.CITY, F.text)
async def handle_city(message: Message, state: FSMContext):
    city = message.text.strip().title()
    await message.answer(f"Вы ввели город: {city}")

    try:
        async with get_pool().acquire() as conn:
            result = await conn.fetchrow(
                "SELECT name, district, subject FROM location WHERE name = $1",
                city,
            )

            if result:
                city_name = result["name"]
                district = result["district"]
                region = result["subject"]

                await state.update_data(city=city_name, region=region, district=district)

                # Сохраняю тот же UPDATE, что и в исходнике.
                await conn.execute("""
                    UPDATE users
                    SET city = $1, district = $2, region = $3
                    WHERE telegram_id = $4
                """, city_name, district, region, message.from_user.id)

                await message.answer(f"Город {city_name} найден. Введите описание вашего профиля:")
                await state.set_state(ProfileStates.DESCRIPTION)
            else:
                await message.answer("Такого города нет в базе данных. Попробуйте снова:")
    except Exception as e:
        logger.error("Ошибка при обработке города: %s", e)
        await message.answer("Произошла ошибка при обработке запроса. Попробуйте снова:")


@router.message(ProfileStates.DESCRIPTION, F.text)
async def handle_description(message: Message, state: FSMContext):
    description = message.text
    if not description.strip():
        await message.answer("Описание не должно быть пустым. Попробуйте снова:")
        return

    await state.update_data(description=description)
    await message.answer("Загрузите ваше фото. Не размещайте запрещенный контент.")
    await state.set_state(ProfileStates.PHOTO)


@router.message(ProfileStates.PHOTO, F.photo)
async def handle_photo(message: Message, state: FSMContext):
    await state.update_data(photo=message.photo[-1].file_id)
    await message.answer(
        "Хотите добавить песню? Можно переслать из другого чата. (да/нет)",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[KeyboardButton(text="да"), KeyboardButton(text="нет")]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )
    await state.set_state(ProfileStates.SONG)


@router.message(ProfileStates.SONG, F.text)
async def handle_song(message: Message, state: FSMContext):
    if message.text.lower() == "да":
        await message.answer("Отправьте аудиофайл вашей песни:")
        await state.set_state(ProfileStates.AUDIO)
    else:
        await state.update_data(song=None)
        await handle_preferences(message, state)


@router.message(ProfileStates.AUDIO, F.audio)
async def handle_audio(message: Message, state: FSMContext):
    await state.update_data(song=message.audio.file_id if message.audio else None)
    await handle_preferences(message, state)


async def handle_preferences(message: Message, state: FSMContext):
    await message.answer(
        "Пожалуйста, выберите предпочтения по полу:",
        reply_markup=ReplyKeyboardMarkup(
            keyboard=[[
                KeyboardButton(text="девушки"),
                KeyboardButton(text="мужчины"),
                KeyboardButton(text="девушки и мужчины"),
            ]],
            resize_keyboard=True,
            one_time_keyboard=True,
        ),
    )
    await state.set_state(ProfileStates.PREFERENCES)


@router.message(ProfileStates.PREFERENCES, F.text)
async def handle_preferences_response(message: Message, state: FSMContext):
    preferences = message.text.lower()

    if preferences == "мужчины":
        pref_value = 1
    elif preferences == "девушки":
        pref_value = 2
    elif preferences == "девушки и мужчины":
        pref_value = 3
    else:
        await message.answer(
            "Пожалуйста, укажите действительные предпочтения: "
            "'девушки', 'мужчины' или 'девушки и мужчины'."
        )
        return

    await state.update_data(preferences=pref_value)
    await message.answer("Анкета заполнена!", reply_markup=ReplyKeyboardRemove())
    await handle_confirmation(message, state)


async def handle_confirmation(message: Message, state: FSMContext):
    data = await state.get_data()
    user_id = message.from_user.id

    await save_data(
        user_id,
        data["name"],
        data["sex"],
        data["age"],
        data["city"],
        data["description"],
        data["photo"],
        data.get("song"),
        data["region"],
        data.get("preferences", 3),
    )

    pref = await getpref(data.get("preferences", 3))
    profile_text = (
        f"Ваши настройки:\n\n"
        f"Имя: {data['name']}\n"
        f"Пол: {data['sex']}\n"
        f"Возраст: {data['age']}\n"
        f"Город: {data['city']}, {data['region']}\n"
        f"Описание: {data['description']}\n"
        f"Предпочтения: {pref}\n"
    )

    if data.get("photo"):
        await message.bot.send_photo(
            chat_id=message.chat.id,
            photo=data["photo"],
            caption=profile_text[:1024],
        )
    else:
        await message.answer(profile_text)

    if data.get("song"):
        await message.bot.send_audio(chat_id=message.chat.id, audio=data["song"])

    await state.clear()


async def show_profile(target: Message, my: bool = False):
    user = await check_user_exists(target.from_user.id)
    if not user:
        await target.answer("Профиль не найден. Пожалуйста, зарегистрируйтесь.")
        return

    pref = await getpref(user[9])
    role = await getrole(user[11])

    if not my:
        profile_text = ""
        if user[11] == 2:
            profile_text += "\nAdmin★\n"
        if user[11] == 4:
            profile_text += "\nPremium★\n"
        profile_text += f"{user[1]}, {user[3]}, {user[4]}, {user[8]}\n{user[5]}"
    else:
        profile_text = (
            f"Ваши настройки:\n\n"
            f"Имя: {user[1]}\n"
            f"Пол: {user[2]}\n"
            f"Возраст: {user[3]}\n"
            f"Город: {user[4]}, {user[8]}\n"
            f"Предпочтения: {pref}\n"
            f"Статус: {role}\n\n"
            f"Описание:\n{user[5]}\n"
        )

    if user[6]:
        await target.bot.send_photo(
            chat_id=target.chat.id,
            photo=user[6],
            caption=profile_text[:1024],
        )
    else:
        await target.answer(profile_text)

    if user[7]:
        await target.bot.send_audio(chat_id=target.chat.id, audio=user[7])


@router.message(Command("myprofile"))
async def my_profile(message: Message):
    await show_profile(message, my=True)


@router.message(Command("deleteprofile"))
async def delete_profile(message: Message, state: FSMContext, edit: bool = False):
    user_id = message.from_user.id
    if await is_user_banned(user_id):
        await message.answer("Ваш профиль заблокирован и не может быть удален. Плати налог, упырь")
        return

    user_exists = await check_user_exists(user_id)
    if user_exists:
        await delete_data(user_id)
        await message.answer("Ваш профиль был успешно удален.")
        if edit:
            await message.answer("Внесите изменения:")
    else:
        await message.answer(
            "Профиль не найден. Возможно, вы не были зарегистрированы или ваше анкету обнулили."
        )


async def get_random_user(user_id: int):
    async with get_pool().acquire() as conn:
        user_data = await conn.fetchrow(
            "SELECT preferences, sex, age FROM users WHERE telegram_id = $1",
            user_id,
        )
        if not user_data:
            return None

        user_preferences = user_data["preferences"]
        user_sex = user_data["sex"]
        user_age = user_data["age"]

        age_min = max(((user_age // 2) + 7), 14)
        age_max = min(((user_age - 7) * 2), 80)

        if user_preferences == 2:
            search_sex = "Женский"
        elif user_preferences == 1:
            search_sex = "Мужской"
        else:
            search_sex = None

        search_pref = 1 if user_sex == "Мужской" else 2
        matched_users = []

        city_result = await conn.fetchrow("SELECT city FROM users WHERE telegram_id = $1", user_id)
        if city_result:
            city = city_result["city"]
            query = """
                SELECT * FROM users
                WHERE city = $1
                AND telegram_id != $2
                AND telegram_id NOT IN (SELECT liked_id FROM likes WHERE liker_id = $3)
                AND telegram_id NOT IN (SELECT dliked_id FROM dislikes WHERE dliker_id = $4)
                AND telegram_id NOT IN (SELECT reported FROM reports WHERE reporter = $5)
                AND (preferences = $6 OR preferences = 3)
                AND age BETWEEN $7 AND $8
            """
            if search_sex:
                query += " AND sex = $9"
                matched_users = await conn.fetch(query, city, user_id, user_id, user_id, user_id, search_pref, age_min, age_max, search_sex)
            else:
                matched_users = await conn.fetch(query, city, user_id, user_id, user_id, user_id, search_pref, age_min, age_max)

        return random.choice(matched_users) if matched_users else None


@router.message(Command("searchprofile"))
async def search_profile(message: Message):
    user_id = message.from_user.id
    user = await get_random_user(user_id)
    if not user:
        await message.answer("Нет подходящих анкет. Измените критерии поиска или зайдите позже.")
        return

    profile_text = ""
    if user[11] == 2:
        profile_text += "\nAdmin★\n"
    if user[11] == 4:
        profile_text += "\nPremium★\n"
    profile_text += f"{user[1]}, {user[3]}, {user[4]}\n{user[5]}"

    keyboard = InlineKeyboardMarkup(inline_keyboard=[[
        InlineKeyboardButton(text="🖤", callback_data=f"like:{user[0]}"),
        InlineKeyboardButton(text="✉︎", callback_data=f"message:{user[0]}"),
        InlineKeyboardButton(text="➔", callback_data=f"dislike:{user[0]}"),
        InlineKeyboardButton(text="🚩", callback_data=f"report:{user[0]}"),
    ]])

    if user[6]:
        await message.bot.send_photo(
            chat_id=message.chat.id,
            photo=user[6],
            caption=profile_text[:1024],
            reply_markup=keyboard,
        )
    else:
        await message.answer(profile_text, reply_markup=keyboard)

    if user[7]:
        await message.bot.send_audio(chat_id=message.chat.id, audio=user[7])


@router.callback_query()
async def handle_like_dislike(query: CallbackQuery, state: FSMContext):
    action, target_id = query.data.split(":")
    target_id = int(target_id)
    user_id = query.from_user.id

    try:
        async with get_pool().acquire() as conn:
            been = await conn.fetch(
                "SELECT like_id FROM likes WHERE liker_id = $1 AND liked_id = $2",
                user_id, target_id,
            )

            if (action == "like" or action == "message") and not been:
                if action == "like":
                    await conn.execute(
                        "INSERT INTO likes (liker_id, liked_id) VALUES ($1, $2)",
                        user_id, target_id,
                    )

                if action == "message":
                    await conn.execute(
                        "INSERT INTO likes (liker_id, liked_id) VALUES ($1, $2)",
                        user_id, target_id,
                    )
                    await state.update_data(message_target=target_id)
                    await query.message.answer("Пожалуйста, введите текст сообщения, который вы хотите отправить.")
                    await state.set_state(MessageStates.awaiting_message)
                    return

            elif action == "dislike":
                await conn.execute(
                    "INSERT INTO dislikes (dliker_id, dliked_id) VALUES ($1, $2)",
                    user_id, target_id,
                )
                await query.message.answer("Вы поставили дизлайк этому профилю.")

            elif action == "report":
                prev = await conn.fetch(
                    "SELECT rep_id FROM reports WHERE reporter = $1 AND reported = $2",
                    user_id, target_id,
                )
                if not prev and target_id != user_id:
                    await conn.execute("UPDATE users SET reports = reports + 1 WHERE telegram_id = $1", target_id)
                    await conn.execute("INSERT INTO reports (reporter, reported) VALUES ($1, $2)", user_id, target_id)
                    await query.message.answer("Вы пожаловались на этот профиль. Мы рассмотрим ваш запрос.")
                else:
                    await query.message.answer("Вы уже жаловались на этот профиль ранее.")

        await query.message.answer("Ищем новый профиль...")
        await search_profile(query.message)

    except Exception as e:
        logger.error("Ошибка при обработке действия: %s", e)
        await query.message.answer("Произошла ошибка при обработке вашего действия.")


@router.message(MessageStates.awaiting_message, F.text)
async def handle_message(message: Message, state: FSMContext):
    data = await state.get_data()
    target_id = data.get("message_target")
    if not target_id:
        await message.answer("Ошибка: нет цели для сообщения.")
        return

    try:
        async with get_pool().acquire() as conn:
            await conn.execute(
                "UPDATE likes SET content = $1 WHERE liker_id = $2 AND liked_id = $3",
                message.text, message.from_user.id, target_id,
            )

            liker_profile = await conn.fetchrow(
                "SELECT * FROM users WHERE telegram_id = $1",
                message.from_user.id,
            )

        liker_info = "Вас лайкнул\n"
        if liker_profile[11] == 2:
            liker_info += "Admin★\n"
        if liker_profile[11] == 4:
            liker_info += "Premium★\n"

        liker_info += (
            f"{liker_profile[1]}, {liker_profile[3]}, {liker_profile[4]}, {liker_profile[8]}\n"
            f"{liker_profile[5]}\n\n"
            f"Вам сообщение от пользователя: {message.text}"
        )

        keyboard = InlineKeyboardMarkup(inline_keyboard=[[
            InlineKeyboardButton(text="🖤", callback_data=f"like:{message.from_user.id}"),
            InlineKeyboardButton(text="➔", callback_data=f"dislike:{message.from_user.id}"),
            InlineKeyboardButton(text="🚩", callback_data=f"report:{message.from_user.id}"),
        ]])

        if liker_profile[6]:
            await message.bot.send_photo(
                chat_id=target_id,
                photo=liker_profile[6],
                caption=liker_info[:1024],
                reply_markup=keyboard,
            )
        if liker_profile[7]:
            await message.bot.send_audio(chat_id=target_id, audio=liker_profile[7])

        await message.answer("Ваше сообщение было отправлено.")
        await state.clear()
        await search_profile(message)

    except Exception as e:
        logger.error("Ошибка при отправке сообщения: %s", e)
        await message.answer("Произошла ошибка при отправке вашего сообщения.")


@router.message(Command("adminstart"))
async def adminstart(message: Message):
    await ensure_admin_roles()
    if not await checkrole(message.from_user.id):
        await reply_denied(message)
        return

    await message.answer(
        "Добро пожаловать в админтул, о Великий.\n"
        "/stats - статистика\n"
        "/banlist - список забаненных\n"
        "/premiumlist - список премиумов\n"
        "/ban_by_id <id> - забанить по id\n"
        "/adminsearch - просмотр анкет на бан\n"
        "/admin - выдать статус админа\n"
        "/reset - сброс истории событий\n"
        "/recover - разбан по id\n"
        "/broadcast - рассылка\n"
        "/totalunban - разбан всем\n"
        "/totalban - бан всем, кто не админ\n"
        "/premium <id> - выдать premium"
    )


@router.message(Command("admin"))
async def admin(message: Message, state: FSMContext):
    await message.answer("Конечно я могу выдать роль админа. Дайте мне id этого счастливчика")
    await state.set_state(AdminStates.waiting_admin_id)


@router.message(AdminStates.waiting_admin_id, F.text)
async def makeadmin(message: Message, state: FSMContext):
    if not await checkrole(message.from_user.id):
        await reply_denied(message)
        await state.clear()
        return

    await execute("UPDATE users SET role = 2 WHERE telegram_id = $1", int(message.text))
    await state.clear()


@router.message(Command("recover"))
async def getrecover(message: Message, state: FSMContext):
    await message.answer("Я могу восстановить забаненного. Дайте мне id участника")
    await state.set_state(AdminStates.waiting_recover_id)


@router.message(AdminStates.waiting_recover_id, F.text)
async def recover(message: Message, state: FSMContext):
    if not await checkrole(message.from_user.id):
        await reply_denied(message)
        await state.clear()
        return

    given_id = int(message.text)
    if not await checkrole(given_id):
        await execute("UPDATE users SET role = 1 WHERE telegram_id = $1", given_id)
    await state.clear()


@router.message(Command("broadcast"))
async def broadcast(message: Message, state: FSMContext):
    if not await checkrole(message.from_user.id):
        await reply_denied(message)
        return

    await message.answer("Введите текст для рассылки:")
    await state.set_data({"waiting_for_text": True})
    await state.set_state(BroadcastStates.waiting_for_text)


@router.message(BroadcastStates.waiting_for_text, F.text)
async def text_handler(message: Message, state: FSMContext):
    await state.update_data(text=message.text, waiting_for_text=False)
    await message.answer("Отправьте фото для рассылки:")
    await state.set_state(BroadcastStates.waiting_for_photo)


@router.message(BroadcastStates.waiting_for_photo, F.photo)
async def photo_handler1(message: Message, state: FSMContext):
    data = await state.get_data()
    await state.update_data(photo=message.photo[-1].file_id)

    photo = message.photo[-1].file_id
    text = data.get("text")

    await message.answer("Рассылка началась...")

    user_ids = await fetch("SELECT telegram_id FROM users")
    for row in user_ids:
        try:
            await message.bot.send_photo(
                chat_id=row["telegram_id"],
                photo=photo,
                caption=text,
            )
        except Exception as e:
            logger.error("Failed to send message to %s: %s", row["telegram_id"], e)

    await message.answer("Рассылка завершена.")
    await state.clear()


@router.message(Command("stats"))
async def handle_stats(message: Message):
    try:
        total_users = await fetchval("SELECT COUNT(*) FROM users")
        total_women = await fetchval("SELECT COUNT(*) FROM users WHERE sex = 'Женский'")
        total_men = await fetchval("SELECT COUNT(*) FROM users WHERE sex = 'Мужской'")

        women_percentage = (total_women / total_users) * 100 if total_users > 0 else 0
        men_percentage = (total_men / total_users) * 100 if total_users > 0 else 0

        top_cities = await fetch("""
            SELECT city, COUNT(*) as user_count
            FROM users
            GROUP BY city
            ORDER BY user_count DESC
            LIMIT 10
        """)

        stats_message = (
            f"Статистика пользователей:\n\n"
            f"Общее количество пользователей: {total_users}\n"
            f"Женщины: {total_women} ({women_percentage:.2f}%)\n"
            f"Мужчины: {total_men} ({men_percentage:.2f}%)\n\n"
            f"Топ 10 городов:\n"
        )
        for row in top_cities:
            stats_message += f"{row['city']}: {row['user_count']} пользователей\n"

        await message.answer(stats_message)
    except Exception as e:
        logger.error("Ошибка при получении статистики: %s", e)
        await message.answer("Произошла ошибка при получении статистики.")


@router.message(Command("premium"))
async def handle_premium(message: Message, command: CommandObject):
    try:
        args = command.args.split() if command.args else []
        if len(args) != 1:
            await message.answer("Пожалуйста, укажите id пользователя.")
            return

        result = await execute("UPDATE users SET role = 4 WHERE telegram_id = $1", int(args[0]))
        if result.endswith("1"):
            await message.answer(f"Пользователь с id {args[0]} успешно стал премиум-пользователем!")
        else:
            await message.answer(f"Пользователь с id {args[0]} не найден.")
    except Exception as e:
        logger.error("Ошибка при обновлении роли пользователя: %s", e)
        await message.answer("Произошла ошибка при обновлении роли.")


@router.message(Command("ban_by_id"))
async def ban_user(message: Message, command: CommandObject):
    if not await checkrole(message.from_user.id):
        await reply_denied(message)
        return

    try:
        args = command.args.split() if command.args else []
        target_id = int(args[0])

        result = await fetchrow("SELECT name FROM users WHERE telegram_id = $1", target_id)
        if result is None:
            await message.answer(f"Пользователь с ID {target_id} не найден.")
            return

        await execute("UPDATE users SET role = 3 WHERE telegram_id = $1", target_id)
        await message.answer(f"Пользователь с ID {target_id} ({result[0]}) забанен.")
    except (IndexError, ValueError):
        await message.answer("Пожалуйста, укажите действительный ID пользователя.")
    except Exception as e:
        await message.answer(f"Произошла ошибка при попытке забанить пользователя: {e}")


@router.message(Command("hidden"))
async def hidden_command(message: Message):
    await message.answer("Начинаю обновление таблицы users...")
    await update_users_table_with_location()
    await message.answer("Обновление завершено!")


async def main():
    await asyncio.sleep(2)
    await create_db_pool()
    await create_tables()
    await create_and_populate_location_table()
    await ensure_admin_roles()

    bot = Bot(token=TOKEN)
    dp = Dispatcher(storage=MemoryStorage())
    dp.include_router(router)
    await dp.start_polling(bot)


if __name__ == "__main__":
    asyncio.run(main())