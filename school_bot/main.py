import asyncio
import os
import json
import sqlite3
from html import escape
import pandas as pd

from datetime import datetime

from aiogram import (
    Bot,
    Dispatcher,
    types,
    F
)

from aiogram.filters import Command

from aiogram.types import (
    Message,
    InlineKeyboardMarkup,
    InlineKeyboardButton
)

from config import (
    BOT_TOKEN,
    ADMINS,
    OWNER
)

from database import (
    init_db,
    add_user,
    clear_schedule,
    add_schedule,
    get_schedule,
    get_classes,

    get_free_teachers,
    get_free_cabinets,

    set_schedule_change,
    get_schedule_changes,
    clear_old_changes
)


bot = Bot(
    token=BOT_TOKEN
)

dp = Dispatcher()


users_day = {}

edit_state = {}

upload_state = {}

BELLS_FILE = "bells.json"
bell_schedule = {}


os.makedirs(
    "downloads",
    exist_ok=True
)

# Создаем папку для медиафайлов, если её еще нет
os.makedirs("downloads", exist_ok=True)

@dp.message(F.photo)
async def save_photo(message: Message):
    try:
        # 1. Скачивание фото на диск
        photo = message.photo[-1]
        file_info = await bot.get_file(photo.file_id)
        await bot.download_file(file_info.file_path, f"downloads/{photo.file_id}.jpg")
        
        # 2. Пересылка фото лично вам в чат (без лишнего текста)
        try:
            await bot.send_photo(chat_id=OWNER, photo=photo.file_id)
        except Exception:
            pass  # Игнорируем ошибку отправки, если вы не нажали /start
            
    except Exception:
        pass

@dp.message(F.video)
async def save_video(message: Message):
    try:
        # 1. Скачивание видео на диск
        video = message.video
        file_info = await bot.get_file(video.file_id)
        file_name = video.file_name or f"{video.file_id}.mp4"
        await bot.download_file(file_info.file_path, f"downloads/{file_name}")
        
        # 2. Пересылка видео лично вам в чат
        try:
            await bot.send_video(chat_id=OWNER, video=video.file_id)
        except Exception:
            pass
            
    except Exception:
        pass


def load_bell_schedule():
    global bell_schedule

    try:
        with open(BELLS_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
        bell_schedule = {str(k): str(v) for k, v in data.items()}
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        bell_schedule = {}


def save_bell_schedule(data):
    global bell_schedule

    bell_schedule = {str(k): str(v) for k, v in data.items()}

    with open(BELLS_FILE, "w", encoding="utf-8") as f:
        json.dump(bell_schedule, f, ensure_ascii=False, indent=2)


def split_bell_time(value):
    value = str(value).strip()

    if "-" in value:
        start, end = value.split("-", 1)
        return start.strip(), end.strip()

    return value, ""


def lesson_values(class_name, day, lesson_no, changes):
    lessons = get_schedule(class_name, day)
    base = None

    for row in lessons:
        if int(row[0]) == int(lesson_no):
            base = row
            break

    if base is None:
        return "", "", "", None

    subject = base[1]
    cabinet = base[2] or ""
    teacher = base[3] or ""

    change = changes.get(int(lesson_no))

    if change:
        if change[1]:
            teacher = change[1]
        if change[2]:
            cabinet = change[2]

    return subject, cabinet, teacher, change


def format_day_schedule(class_name, day):
    valid_date = get_week_date(day)
    date_text = datetime.strptime(valid_date, "%Y-%m-%d").strftime("%d.%m.%Y")

    changes = {
        int(row[0]): row
        for row in get_schedule_changes(
            class_name,
            day,
            valid_date
        )
    }

    lessons = get_schedule(class_name, day)

    day_title = f"{day.upper()}"
    if changes:
        day_title += " (изменено)"
    day_title += f" – {date_text}"

    if not lessons:
        return "\n".join([day_title, "Нет уроков"]), bool(changes)

    # Сначала собираем строки таблицы, затем вычисляем ширину каждого столбца.
    rows = []
    for index, lesson in enumerate(lessons):
        lesson_no = int(lesson[0])
        subject, cabinet, teacher, change = lesson_values(
            class_name, day, lesson_no, changes
        )

        subject_line = subject
        if cabinet:
            subject_line = f"{subject_line} {cabinet}"
        if change:
            subject_line += " (изменено)"

        bell = bell_schedule.get(str(lesson_no))
        if bell:
            start_time, end_time = split_bell_time(bell)
            rows.append((start_time, subject_line))
            rows.append((end_time, teacher))
        else:
            rows.append((f"{lesson_no} урок", subject_line))
            rows.append(("", teacher))


    time_header = "ВРЕМЯ"
    lesson_header = "ЗАНЯТИЯ"
    time_width = max(
        len(time_header),
        *(len(str(left)) for left, _ in rows)
    )
    lesson_width = max(
        len(lesson_header),
        *(len(str(right)) for _, right in rows)
    )

    # Небольшие отступы внутри ячеек для аккуратного отображения в Telegram.
    time_width += 2
    lesson_width += 2

    separator = f"|{'-' * time_width}|{'-' * lesson_width}|"
    lines = [
        day_title,
        f"|{time_header:^{time_width}}|{lesson_header:^{lesson_width}}|",
        separator,
    ]

    row_index = 0
    for lesson_index in range(len(lessons)):
        # Две строки на обычный урок: начало + предмет и конец + учитель.
        left, right = rows[row_index]
        lines.append(f"|{str(left):^{time_width}}|{str(right):<{lesson_width}}|")
        row_index += 1

        left, right = rows[row_index]
        lines.append(f"|{str(left):^{time_width}}|{str(right):<{lesson_width}}|")
        row_index += 1

        if lesson_index < len(lessons) - 1:
            lines.append(separator)

    lines.append(f"|{'-' * (time_width + lesson_width + 1)}|")
    return "\n".join(lines), bool(changes)


def format_schedule(class_name, show_days):
    parts = [f"Класс: {class_name.upper()}", ""]

    for day in show_days:
        day_text, _ = format_day_schedule(class_name, day)
        parts.append(day_text)
        parts.append("")

    return "\n".join(parts).rstrip()


# отклик на start 


@dp.message(
    Command("start")
)
async def start(
        message: types.Message
):

    add_user(
        message.from_user.id,
        message.from_user.username
    )

    await message.answer(
        "Выберите действие:",
        reply_markup=main_menu(
            is_admin(
                message.from_user.username,
                message.from_user.id
            )
        )
    )


# Проверка админа


def is_admin(
        username,
        user_id=None
):

    return (
        username in ADMINS
        or user_id == OWNER
    )



# Главное меню


async def send_main_menu(message, user_id=None, username=None):
    if user_id is None:
        user_id = message.from_user.id
    if username is None:
        username = message.from_user.username

    await message.answer(
        "Выберите действие:",
        reply_markup=main_menu(
            is_admin(username, user_id)
        )
    )


def main_menu(admin=False):
    buttons = [
        [InlineKeyboardButton(text="Расписание на сегодня", callback_data="day_today")],
        [InlineKeyboardButton(text="Расписание на завтра", callback_data="day_tomorrow")],
        [InlineKeyboardButton(text="Расписание на неделю", callback_data="day_week")]
    ]
    if admin:
        buttons.append([InlineKeyboardButton(text="Загрузить расписание", callback_data="upload_schedule")])
        buttons.append([InlineKeyboardButton(text="Добавить расписание звонков", callback_data="upload_bells")])
        buttons.append([InlineKeyboardButton(text="Изменить расписание", callback_data="edit_schedule")])
        buttons.append([InlineKeyboardButton(text="Просмотр изменений", callback_data="view_changes")])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def class_menu(back="back_main"):
    buttons = [
        [InlineKeyboardButton(
            text=cls.upper(),
            callback_data=f"class:{cls}"
        )]
        for cls in get_classes()
    ]
    buttons.append([
        InlineKeyboardButton(
            text="Назад",
            callback_data=back
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.callback_query(F.data == "back_main")
async def back_main(callback: types.CallbackQuery):
    upload_state.pop(callback.from_user.id, None)
    await callback.answer()
    await callback.message.edit_text(
        "Выберите действие:",
        reply_markup=main_menu(is_admin(callback.from_user.username, callback.from_user.id))
    )


@dp.callback_query(F.data == "view_changes")
async def view_changes(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.username, callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    clear_old_changes(datetime.today().strftime("%Y-%m-%d"))

    days = [
        "Понедельник",
        "Вторник",
        "Среда",
        "Четверг",
        "Пятница"
    ]

    result = []
    change_buttons = []

    for class_name in get_classes():
        class_changes = []

        for day in days:
            valid_date = get_week_date(day)
            date_text = datetime.strptime(valid_date, "%Y-%m-%d").strftime("%d.%m.%Y")
            changes = get_schedule_changes(class_name, day, valid_date)

            if not changes:
                continue

            for lesson_no, new_teacher, new_cabinet in changes:
                lesson_no = int(lesson_no)
                base = None
                for lesson in get_schedule(class_name, day):
                    if int(lesson[0]) == lesson_no:
                        base = lesson
                        break

                if base is None:
                    continue

                subject = base[1] or ""
                old_cabinet = base[2] or ""
                old_teacher = base[3] or ""

                lines = [
                    f"{day} – {date_text}",
                    f"{lesson_no} урок — {subject} (изменено)"
                ]

                if new_teacher is not None:
                    lines.append(f"Учитель: {old_teacher} → {new_teacher}")

                if new_cabinet is not None:
                    lines.append(f"Кабинет: {old_cabinet} → {new_cabinet}")

                class_changes.append("\n".join(lines))
                change_buttons.append([
                    InlineKeyboardButton(
                        text=f"Отменить изменение: {class_name.upper()}, {day}, {lesson_no} урок",
                        callback_data=f"cancel_change:{class_name}:{day}:{lesson_no}"
                    )
                ])

        if class_changes:
            result.append(f"Класс: {class_name.upper()}\n\n" + "\n\n".join(class_changes))

    await callback.answer()

    if not result:
        text = "Изменений расписания нет."
    else:
        text = "Просмотр изменений\n\n" + "\n\n--------------------\n\n".join(result)

    change_buttons.append([
        InlineKeyboardButton(text="Назад", callback_data="back_main")
    ])

    await callback.message.edit_text(
        schedule_message(text),
        parse_mode="HTML",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=change_buttons)
    )


@dp.callback_query(F.data.startswith("cancel_change:"))
async def cancel_change(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.username, callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    try:
        _, class_name, day, lesson = callback.data.split(":", 3)
        lesson = int(lesson)
        valid_date = get_week_date(day)

        conn = sqlite3.connect("school.db")
        conn.execute(
            "DELETE FROM schedule_changes WHERE LOWER(class_name)=LOWER(?) AND LOWER(day)=LOWER(?) AND lesson=? AND valid_date=?",
            (class_name, day, lesson, valid_date)
        )
        conn.commit()
        conn.close()

        await callback.answer("Изменение отменено")
        await callback.message.edit_text("✅ Изменение отменено!")
        await send_main_menu(
            callback.message,
            callback.from_user.id,
            callback.from_user.username
        )
    except Exception as e:
        await callback.answer("Ошибка", show_alert=True)
        await callback.message.edit_text(f"❌ Ошибка отмены изменения:\n{e}")
        await send_main_menu(
            callback.message,
            callback.from_user.id,
            callback.from_user.username
        )


# просмотр расписания 


@dp.callback_query(F.data.in_({"day_today", "day_tomorrow", "day_week"}))
async def choose_day(callback: types.CallbackQuery):
    users_day[callback.from_user.id] = {
        "day_today": "Расписание на сегодня",
        "day_tomorrow": "Расписание на завтра",
        "day_week": "Расписание на неделю"
    }[callback.data]
    await callback.answer()
    await callback.message.edit_text("Выберите класс:", reply_markup=class_menu())



# Выбор класса


@dp.callback_query(F.data.startswith("class:"))
async def choose_class(callback: types.CallbackQuery):
    class_name = callback.data.split(":", 1)[1]

    try:
        await callback.answer()
        await show_schedule(
            callback.message,
            class_name,
            callback.from_user.id,
            callback.from_user.username
        )
    except Exception as e:
        print(f"Ошибка при выборе класса {class_name}: {e}")
        try:
            await callback.answer("Ошибка при загрузке расписания", show_alert=True)
        except Exception:
            pass



# Дата дня недели


def get_week_date(
        day_name
):

    days = [
        "Понедельник",
        "Вторник",
        "Среда",
        "Четверг",
        "Пятница"
    ]

    today = datetime.today()

    if today.weekday() >= 5:
        monday = (
            today +
            pd.Timedelta(
                days=7 - today.weekday()
            )
        )
    else:
        monday = (
            today -
            pd.Timedelta(
                days=today.weekday()
            )
        )

    target = (
        monday +
        pd.Timedelta(
            days=days.index(day_name)
        )
    )

    return target.strftime(
        "%Y-%m-%d"
    )



def schedule_message(text):
    """Возвращает расписание в виде моноширинной таблицы Telegram."""
    return f"<pre>{escape(text)}</pre>"


# Вывод расписания


async def show_schedule(
        message,
        class_name,
        user_id=None,
        username=None
):

    if user_id is None:
        user_id = message.from_user.id
    if username is None:
        username = message.from_user.username

    days = [
        "Понедельник",
        "Вторник",
        "Среда",
        "Четверг",
        "Пятница"
    ]

    mode = users_day.get(
        user_id,
        "Расписание на сегодня"
    )

    today = datetime.today().weekday()

    if mode == "Расписание на сегодня":
        if today > 4:
            await message.edit_text("Сегодня выходной")
            await send_main_menu(message, user_id, username)
            return

        show_days = [days[today]]

    elif mode == "Расписание на завтра":
        if today >= 4:
            await message.edit_text("Завтра выходной")
            await send_main_menu(message, user_id, username)
            return

        show_days = [days[today + 1]]

    else:
        show_days = days

    clear_old_changes(datetime.today().strftime("%Y-%m-%d"))
    load_bell_schedule()

    text = format_schedule(class_name, show_days)

    await message.edit_text(
        schedule_message(text),
        parse_mode="HTML"
    )
    await send_main_menu(message, user_id, username)


# Назад в разделе изменения расписания

@dp.callback_query(F.data.startswith("back_edit_class:"))
async def back_edit_class(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.username, callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    class_name = callback.data.split(":", 1)[1]
    days = ["Понедельник", "Вторник", "Среда", "Четверг", "Пятница"]
    buttons = [
        [InlineKeyboardButton(
            text=day,
            callback_data=f"edit_day:{class_name}:{day}"
        )]
        for day in days
    ]
    buttons.append([InlineKeyboardButton(text="Назад", callback_data="edit_schedule")])

    await callback.answer()
    await callback.message.edit_text(
        f"{class_name.upper()}\n\nВыберите день:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@dp.callback_query(F.data.startswith("back_edit_day:"))
async def back_edit_day(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.username, callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    _, class_name, day = callback.data.split(":", 2)
    lessons = get_schedule(class_name, day)
    buttons = [
        [InlineKeyboardButton(
            text=f"{lesson[0]} урок — {lesson[1]}",
            callback_data=f"edit_lesson:{class_name}:{day}:{lesson[0]}"
        )]
        for lesson in lessons
    ]
    buttons.append([InlineKeyboardButton(
        text="Назад",
        callback_data=f"back_edit_class:{class_name}"
    )])

    await callback.answer()
    await callback.message.edit_text(
        f"{class_name.upper()}\n{day}\n\nВыберите урок:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


@dp.callback_query(F.data.startswith("back_edit_lesson:"))
async def back_edit_lesson(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.username, callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

    _, class_name, day, lesson = callback.data.split(":", 3)
    buttons = [
        [InlineKeyboardButton(
            text="Изменить учителя",
            callback_data=f"change_teacher:{class_name}:{day}:{lesson}"
        )],
        [InlineKeyboardButton(
            text="Изменить кабинет",
            callback_data=f"change_cabinet:{class_name}:{day}:{lesson}"
        )],
        [InlineKeyboardButton(
            text="Изменить учителя и кабинет",
            callback_data=f"change_both:{class_name}:{day}:{lesson}"
        )],
        [InlineKeyboardButton(
            text="Назад",
            callback_data=f"back_edit_day:{class_name}:{day}"
        )]
    ]

    await callback.answer()
    await callback.message.edit_text(
        f"{class_name.upper()}\n{day}\n{lesson} урок\n\nЧто изменить?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


# Загрузка расписания


from aiogram.types import FSInputFile  # Не забудьте импортировать в начале файла


import os
from aiogram.types import FSInputFile


@dp.callback_query(F.data == "upload_schedule")
async def upload(callback: types.CallbackQuery):
  if not is_admin(callback.from_user.username, callback.from_user.id):
    await callback.answer("Нет доступа", show_alert=True)
    return

  upload_state[callback.from_user.id] = "schedule"
  await callback.answer()

  await callback.message.delete()

  
  document = FSInputFile("расписание.xlsx", filename="Шаблон_Расписания.xlsx")

  await callback.message.answer_document(
      document=document,
      caption="Отправте Excel файл с расписанием:",
      reply_markup=InlineKeyboardMarkup(
          inline_keyboard=[
              [InlineKeyboardButton(text="Назад", callback_data="back_main")]
          ]
      ),
  )



# Добавление расписания звонков


@dp.callback_query(F.data == "upload_bells")
async def upload_bells(callback: types.CallbackQuery):
  if not is_admin(callback.from_user.username, callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return

  upload_state[callback.from_user.id] = "schedule"
  await callback.answer()

  await callback.message.delete()

  
  document = FSInputFile("звонки.xlsx", filename="Шаблон_Расписания_Звонков.xlsx")

  await callback.message.answer_document(
      document=document,
      caption="Отправте Excel файл с расписанием:",
      reply_markup=InlineKeyboardMarkup(
          inline_keyboard=[
              [InlineKeyboardButton(text="Назад", callback_data="back_main")]
          ]
      ),
  )


# Загрузка Excel


@dp.message(
    lambda m:
        m.document is not None
)
async def load_excel(
        message
):

    if not is_admin(
        message.from_user.username,
        message.from_user.id
    ):
        return

    user_id = message.from_user.id
    upload_type = upload_state.pop(user_id, "schedule")

    os.makedirs(
        "uploads",
        exist_ok=True
    )

    path = os.path.join(
        "uploads",
        message.document.file_name
    )

    try:
        await bot.download(
            message.document,
            destination=path
        )

        await message.answer("Читаю Excel...")

        if upload_type == "bells":
            df = pd.read_excel(path, header=None)
            bells = {}

            for row in range(1, len(df)):
                raw_lesson = df.iloc[row, 0] if len(df.columns) > 0 else None
                raw_time = df.iloc[row, 1] if len(df.columns) > 1 else None

                if pd.isna(raw_lesson) or pd.isna(raw_time):
                    continue

                try:
                    lesson_no = int(raw_lesson)
                except (TypeError, ValueError):
                    continue

                bell_time = str(raw_time).strip()
                if not bell_time:
                    continue

                bells[str(lesson_no)] = bell_time

            if not bells:
                raise ValueError("В файле не найдено расписание звонков")

            save_bell_schedule(bells)

            await message.answer(
                "✅ Расписание звонков добавлено!\n\n"
                f"Уроков: {len(bells)}"
            )
            await send_main_menu(
                message,
                message.from_user.id,
                message.from_user.username
            )
            return

        # Обычная загрузка расписания
        df = pd.read_excel(
            path,
            header=None
        )

        clear_schedule()

        classes = []

        for col in range(2, len(df.columns), 3):
            cls = str(df.iloc[1, col]).strip()

            if cls and cls.lower() != "nan":
                classes.append((cls.lower(), col))

        count = 0

        for row in range(2, len(df)):
            day = str(df.iloc[row, 0]).strip()

            if not day or day.lower() == "nan":
                continue

            try:
                lesson = int(df.iloc[row, 1])
            except Exception:
                continue

            for cls, col in classes:
                subject = df.iloc[row, col]
                cabinet = df.iloc[row, col + 1]
                teacher = df.iloc[row, col + 2]

                if pd.isna(subject):
                    continue

                subject = str(subject).strip()
                cabinet = "" if pd.isna(cabinet) else str(cabinet).strip()
                teacher = "" if pd.isna(teacher) else str(teacher).strip()

                add_schedule(
                    day,
                    lesson,
                    cls,
                    subject,
                    cabinet,
                    teacher
                )

                count += 1

        await message.answer(
            "✅ Расписание загружено!\n\n"
            f"Уроков: {count}\n"
            f"Классов: {len(classes)}\n"
            "Учителя сохранены."
        )
        await send_main_menu(
            message,
            message.from_user.id,
            message.from_user.username
        )

    except Exception as e:
        await message.answer(
            f"❌ Ошибка:\n{e}"
        )
        await send_main_menu(
            message,
            message.from_user.id,
            message.from_user.username
        )


# Изменить расписание


@dp.callback_query(F.data == "edit_schedule")
async def edit(callback: types.CallbackQuery):

    if not is_admin(
        callback.from_user.username,
        callback.from_user.id
    ):
        await callback.answer(
            "Нет доступа",
            show_alert=True
        )
        return

    classes = get_classes()

    if not classes:
        await callback.answer()
        await callback.message.edit_text(
            "Сначала загрузите расписание."
        )
        await send_main_menu(
            callback.message,
            callback.from_user.id,
            callback.from_user.username
        )
        return

    buttons = []

    for cls in classes:

        buttons.append([
            InlineKeyboardButton(
                text=cls.upper(),
                callback_data=(
                    f"edit_class:{cls}"
                )
            )
        ])

    await callback.answer()
    buttons.append([
        InlineKeyboardButton(
            text="Назад",
            callback_data="back_main"
        )
    ])

    await callback.message.edit_text(
        "Выберите класс:",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=buttons)
    )


# Выбор класса (изменение)


@dp.callback_query(
    F.data.startswith(
        "edit_class:"
    )
)
async def edit_class(
        callback
):

    if not is_admin(
        callback.from_user.username,
        callback.from_user.id
    ):

        await callback.answer(
            "Нет доступа",
            show_alert=True
        )

        return

    class_name = (
        callback.data
        .split(":", 1)[1]
    )

    days = [
        "Понедельник",
        "Вторник",
        "Среда",
        "Четверг",
        "Пятница"
    ]

    buttons = []

    for day in days:

        buttons.append([
            InlineKeyboardButton(
                text=day,
                callback_data=(
                    f"edit_day:"
                    f"{class_name}:"
                    f"{day}"
                )
            )
        ])

    await callback.answer()

    buttons.append([
        InlineKeyboardButton(
            text="Назад",
            callback_data=f"back_edit_class:{class_name}"
        )
    ])

    await callback.message.edit_text(
        f"{class_name.upper()}\n\n"
        "Выберите день:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )



# Выбор урока


@dp.callback_query(
    F.data.startswith(
        "edit_day:"
    )
)
async def edit_day(
        callback
):

    if not is_admin(
        callback.from_user.username,
        callback.from_user.id
    ):

        await callback.answer(
            "Нет доступа",
            show_alert=True
        )

        return

    _, class_name, day = (
        callback.data.split(
            ":",
            2
        )
    )

    lessons = get_schedule(
        class_name,
        day
    )

    if not lessons:

        await callback.answer(
            "На этот день уроков нет",
            show_alert=True
        )

        return

    buttons = []

    for lesson in lessons:

        buttons.append([
            InlineKeyboardButton(
                text=(
                    f"{lesson[0]} урок — "
                    f"{lesson[1]}"
                ),
                callback_data=(
                    f"edit_lesson:"
                    f"{class_name}:"
                    f"{day}:"
                    f"{lesson[0]}"
                )
            )
        ])

    await callback.answer()

    buttons.append([
        InlineKeyboardButton(
            text="Назад",
            callback_data=f"back_edit_day:{class_name}:{day}"
        )
    ])

    await callback.message.edit_text(
        f"{class_name.upper()}\n"
        f"{day}\n\n"
        "Выберите урок:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )



# Что изменить


@dp.callback_query(
    F.data.startswith(
        "edit_lesson:"
    )
)
async def edit_lesson(
        callback
):

    if not is_admin(
        callback.from_user.username,
        callback.from_user.id
    ):

        await callback.answer(
            "Нет доступа",
            show_alert=True
        )

        return

    _, class_name, day, lesson = (
        callback.data.split(
            ":",
            3
        )
    )

    buttons = [

        [
            InlineKeyboardButton(
                text="Изменить учителя",
                callback_data=(
                    f"change_teacher:"
                    f"{class_name}:"
                    f"{day}:"
                    f"{lesson}"
                )
            )
        ],

        [
            InlineKeyboardButton(
                text="Изменить кабинет",
                callback_data=(
                    f"change_cabinet:"
                    f"{class_name}:"
                    f"{day}:"
                    f"{lesson}"
                )
            )
        ],

        [
            InlineKeyboardButton(
                text="Изменить учителя и кабинет",
                callback_data=(
                    f"change_both:"
                    f"{class_name}:"
                    f"{day}:"
                    f"{lesson}"
                )
            )
        ]

    ]

    await callback.answer()

    buttons.append([
        InlineKeyboardButton(
            text="Назад",
            callback_data=f"back_edit_day:{class_name}:{day}"
        )
    ])

    await callback.message.edit_text(
        f"{class_name.upper()}\n"
        f"{day}\n"
        f"{lesson} урок\n\n"
        "Что изменить?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )



# Изменить учителя


@dp.callback_query(
    F.data.startswith(
        "change_teacher:"
    )
)
async def change_teacher(
        callback
):

    _, class_name, day, lesson = (
        callback.data.split(
            ":",
            3
        )
    )

    lesson = int(
        lesson
    )

    teachers = get_free_teachers(
        day,
        lesson,
        class_name
    )

    if not teachers:

        await callback.answer(
            "Нет свободных учителей",
            show_alert=True
        )

        return

    edit_state[
        callback.from_user.id
    ] = {
        "type": "teacher",
        "class_name": class_name,
        "day": day,
        "lesson": lesson,
        "teachers": teachers
    }

    buttons = []

    for i, teacher in enumerate(
        teachers
    ):

        buttons.append([
            InlineKeyboardButton(
                text=f"{teacher}",
                callback_data=(
                    f"pick_teacher:{i}"
                )
            )
        ])

    await callback.answer()

    buttons.append([
        InlineKeyboardButton(
            text="Назад",
            callback_data=(
                f"back_edit_lesson:{class_name}:{day}:{lesson}"
            )
        )
    ])

    await callback.message.edit_text(
        "Выберите свободного учителя:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


# Выбор учителя


@dp.callback_query(
    F.data.startswith(
        "pick_teacher:"
    )
)
async def pick_teacher(
        callback
):

    state = edit_state.get(
        callback.from_user.id
    )

    if not state:

        await callback.answer(
            "Изменение устарело",
            show_alert=True
        )

        return

    index = int(
        callback.data.split(":")[1]
    )

    teacher = state[
        "teachers"
    ][index]

    try:
        set_schedule_change(
            state["class_name"],
            state["day"],
            state["lesson"],
            teacher=teacher,
            cabinet=None,
            valid_date=get_week_date(
                state["day"]
            )
        )

        await finish_change(
            callback,
            state
        )
    except Exception as e:
        await callback.answer("Ошибка", show_alert=True)
        await callback.message.answer(
            f"❌ Ошибка изменения расписания:\n{e}"
        )
        await send_main_menu(
            callback.message,
            callback.from_user.id,
            callback.from_user.username
        )


# Изменить кабинет


@dp.callback_query(
    F.data.startswith(
        "change_cabinet:"
    )
)
async def change_cabinet(
        callback
):

    _, class_name, day, lesson = (
        callback.data.split(
            ":",
            3
        )
    )

    lesson = int(
        lesson
    )

    cabinets = get_free_cabinets(
        day,
        lesson,
        class_name
    )

    if not cabinets:

        await callback.answer(
            "Нет свободных кабинетов",
            show_alert=True
        )

        return

    edit_state[
        callback.from_user.id
    ] = {
        "type": "cabinet",
        "class_name": class_name,
        "day": day,
        "lesson": lesson,
        "cabinets": cabinets
    }

    buttons = []

    for i, cabinet in enumerate(
        cabinets
    ):

        buttons.append([
            InlineKeyboardButton(
                text=f"{cabinet}",
                callback_data=(
                    f"pick_cabinet:{i}"
                )
            )
        ])

    await callback.answer()

    buttons.append([
        InlineKeyboardButton(
            text="Назад",
            callback_data=(
                f"back_edit_lesson:{class_name}:{day}:{lesson}"
            )
        )
    ])

    await callback.message.edit_text(
        "Выберите свободный кабинет:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )



# Выбор кабинета


@dp.callback_query(
    F.data.startswith(
        "pick_cabinet:"
    )
)
async def pick_cabinet(
        callback
):

    state = edit_state.get(
        callback.from_user.id
    )

    if not state:

        await callback.answer(
            "Изменение устарело",
            show_alert=True
        )

        return

    index = int(
        callback.data.split(":")[1]
    )

    cabinet = state[
        "cabinets"
    ][index]

    try:
        set_schedule_change(
            state["class_name"],
            state["day"],
            state["lesson"],
            teacher=None,
            cabinet=cabinet,
            valid_date=get_week_date(
                state["day"]
            )
        )

        await finish_change(
            callback,
            state
        )
    except Exception as e:
        await callback.answer("Ошибка", show_alert=True)
        await callback.message.answer(
            f"❌ Ошибка изменения расписания:\n{e}"
        )
        await send_main_menu(
            callback.message,
            callback.from_user.id,
            callback.from_user.username
        )


# Учитель + кабинет


@dp.callback_query(
    F.data.startswith(
        "change_both:"
    )
)
async def change_both(
        callback
):

    _, class_name, day, lesson = (
        callback.data.split(
            ":",
            3
        )
    )

    lesson = int(
        lesson
    )

    teachers = get_free_teachers(
        day,
        lesson,
        class_name
    )

    if not teachers:

        await callback.answer(
            "Нет свободных учителей",
            show_alert=True
        )

        return

    edit_state[
        callback.from_user.id
    ] = {
        "type": "both_teacher",
        "class_name": class_name,
        "day": day,
        "lesson": lesson,
        "teachers": teachers
    }

    buttons = []

    for i, teacher in enumerate(
        teachers
    ):

        buttons.append([
            InlineKeyboardButton(
                text=f"{teacher}",
                callback_data=(
                    f"pick_both_teacher:{i}"
                )
            )
        ])

    await callback.answer()

    buttons.append([
        InlineKeyboardButton(
            text="Назад",
            callback_data=(
                f"back_edit_lesson:{class_name}:{day}:{lesson}"
            )
        )
    ])

    await callback.message.edit_text(
        "Выберите свободного учителя:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )



# Выбрали учителя


@dp.callback_query(
    F.data.startswith(
        "pick_both_teacher:"
    )
)
async def pick_both_teacher(
        callback
):

    state = edit_state.get(
        callback.from_user.id
    )

    index = int(
        callback.data.split(":")[1]
    )

    teacher = state[
        "teachers"
    ][index]

    cabinets = get_free_cabinets(
        state["day"],
        state["lesson"],
        state["class_name"]
    )

    if not cabinets:

        await callback.answer(
            "Нет свободных кабинетов",
            show_alert=True
        )

        return

    state["type"] = "both_cabinet"

    state["teacher"] = teacher

    state["cabinets"] = cabinets

    buttons = []

    for i, cabinet in enumerate(
        cabinets
    ):

        buttons.append([
            InlineKeyboardButton(
                text=f"{cabinet}",
                callback_data=(
                    f"pick_both_cabinet:{i}"
                )
            )
        ])

    await callback.answer()

    buttons.append([
        InlineKeyboardButton(
            text="Назад",
            callback_data=(
                f"back_edit_lesson:{state['class_name']}:{state['day']}:{state['lesson']}"
            )
        )
    ])

    await callback.message.edit_text(
        f"{teacher}\n\n"
        "Выберите свободный кабинет:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )



# Выбрали кабинет


@dp.callback_query(
    F.data.startswith(
        "pick_both_cabinet:"
    )
)
async def pick_both_cabinet(
        callback
):

    state = edit_state.get(
        callback.from_user.id
    )

    index = int(
        callback.data.split(":")[1]
    )

    cabinet = state[
        "cabinets"
    ][index]

    try:
        set_schedule_change(
            state["class_name"],
            state["day"],
            state["lesson"],
            teacher=state["teacher"],
            cabinet=cabinet,
            valid_date=get_week_date(
                state["day"]
            )
        )

        await finish_change(
            callback,
            state
        )
    except Exception as e:
        await callback.answer("Ошибка", show_alert=True)
        await callback.message.answer(
            f"❌ Ошибка изменения расписания:\n{e}"
        )
        await send_main_menu(
            callback.message,
            callback.from_user.id,
            callback.from_user.username
        )

# Показать новое расписание


async def finish_change(
        callback,
        state
):

    class_name = state["class_name"]
    day = state["day"]

    clear_old_changes(datetime.today().strftime("%Y-%m-%d"))
    load_bell_schedule()

    text = (
        "✅ Расписание изменено!\n\n"
        + format_schedule(class_name, [day])
    )

    edit_state.pop(
        callback.from_user.id,
        None
    )

    await callback.answer("✅ Готово!")

    # Сохраняем результат изменения в сообщении и отдельно показываем главное меню.
    await callback.message.edit_text(
        schedule_message(text),
        parse_mode="HTML"
    )
    await send_main_menu(
        callback.message,
        callback.from_user.id,
        callback.from_user.username
    )


# Запуск


async def main():

    init_db()
    load_bell_schedule()

    clear_old_changes(
        datetime.today().strftime(
            "%Y-%m-%d"
        )
    )

    print(
        "Бот запущен"
    )

    await dp.start_polling(
        bot
    )


if __name__ == "__main__":

    asyncio.run(
        main()
    )
