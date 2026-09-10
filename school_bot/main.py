import asyncio
import os
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


os.makedirs(
    "downloads",
    exist_ok=True
)


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
    )



# Главное меню


def main_menu(admin=False):
    buttons = [
        [InlineKeyboardButton(text="Расписание на сегодня", callback_data="day_today")],
        [InlineKeyboardButton(text="Расписание на завтра", callback_data="day_tomorrow")],
        [InlineKeyboardButton(text="Расписание на неделю", callback_data="day_week")]
    ]
    if admin:
        buttons.append([InlineKeyboardButton(text="📥 Загрузить расписание", callback_data="upload_schedule")])
        buttons.append([InlineKeyboardButton(text="✏ Изменить расписание", callback_data="edit_schedule")])
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
            text="« Назад",
            callback_data=back
        )
    ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


@dp.callback_query(F.data == "back_main")
async def back_main(callback: types.CallbackQuery):
    await callback.answer()
    await callback.message.edit_text(
        "Выберите действие:",
        reply_markup=main_menu(is_admin(callback.from_user.username, callback.from_user.id))
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

            await message.answer(
                "Сегодня выходной"
            )

            return

        show_days = [
            days[today]
        ]

    elif mode == "Расписание на завтра":

        if today >= 4:

            await message.answer(
                "Завтра выходной"
            )

            return

        show_days = [
            days[today + 1]
        ]

    else:

        show_days = days

    clear_old_changes(
        datetime.today().strftime(
            "%Y-%m-%d"
        )
    )

    text = (
        f"Класс: "
        f"{class_name.upper()}\n\n"
    )

    for day in show_days:

        valid_date = get_week_date(
            day
        )

        changes = {
            row[0]: row

            for row in get_schedule_changes(
                class_name,
                day,
                valid_date
            )
        }

        if changes:

            text += (
                f"{day} "
                f"(изменено)\n"
            )

        else:

            text += (
                f"{day}\n"
            )

        lessons = get_schedule(
            class_name,
            day
        )

        if not lessons:

            text += (
                "Нет уроков\n\n"
            )

            continue

        for lesson in lessons:

            lesson_no = lesson[0]
            subject = lesson[1]
            cabinet = lesson[2]
            teacher = lesson[3]

            change = changes.get(
                lesson_no
            )

            if change:

                if change[1]:

                    teacher = change[1]

                if change[2]:

                    cabinet = change[2]

            line = (
                f"{lesson_no} урок - "
                f"{subject}"
            )

            if teacher:

                line += (
                    f" — "
                    f"{teacher}"
                )

            if cabinet:

                line += (
                    f" (каб. {cabinet})"
                )

            text += (
                line + "\n"
            )

        text += "\n"

    await message.edit_text(
        text,
        reply_markup=main_menu(
            is_admin(
                username,
                user_id
            )
        )
    )



# Загрузка расписания


@dp.callback_query(F.data == "upload_schedule")
async def upload(callback: types.CallbackQuery):
    if not is_admin(callback.from_user.username, callback.from_user.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    await callback.answer()
    await callback.message.edit_text(
        "📥 Пришлите Excel файл\n\n"
        "Формат:\n"
        "День | Урок | Предмет | Кабинет | Учитель | Предмет | Кабинет | Учитель ..."
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

    os.makedirs(
        "uploads",
        exist_ok=True
    )

    path = os.path.join(
        "uploads",
        message.document.file_name
    )

    await bot.download(
        message.document,
        destination=path
    )

    await message.answer(
        "Читаю Excel..."
    )

    try:

        df = pd.read_excel(
            path,
            header=None
        )

        clear_schedule()

        classes = []

        for col in range(
            2,
            len(df.columns),
            3
        ):

            cls = str(
                df.iloc[1, col]
            ).strip()

            if (
                cls
                and
                cls.lower() != "nan"
            ):

                classes.append(
                    (
                        cls.lower(),
                        col
                    )
                )

        count = 0

        for row in range(
            2,
            len(df)
        ):

            day = str(
                df.iloc[row, 0]
            ).strip()

            if (
                not day
                or
                day.lower() == "nan"
            ):

                continue

            try:

                lesson = int(
                    df.iloc[row, 1]
                )

            except:

                continue

            for cls, col in classes:

                subject = (
                    df.iloc[row, col]
                )

                cabinet = (
                    df.iloc[
                        row,
                        col + 1
                    ]
                )

                teacher = (
                    df.iloc[
                        row,
                        col + 2
                    ]
                )

                if pd.isna(
                    subject
                ):

                    continue

                subject = str(
                    subject
                ).strip()

                if pd.isna(
                    cabinet
                ):

                    cabinet = ""

                else:

                    cabinet = str(
                        cabinet
                    ).strip()

                if pd.isna(
                    teacher
                ):

                    teacher = ""

                else:

                    teacher = str(
                        teacher
                    ).strip()

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
            "Учителя сохранены.",
            reply_markup=main_menu(True)
        )

    except Exception as e:

        await message.answer(
            f"❌ Ошибка:\n{e}"
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
            "⚠️ Сначала загрузите расписание.",
            reply_markup=main_menu(True)
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

    await callback.message.edit_text(
        f"{class_name.upper()}\n\n"
        "Выберите день:",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=buttons
        )
    )


# =====================
# Выбор урока
# =====================

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

# Показать новое расписание


async def finish_change(
        callback,
        state
):

    class_name = state[
        "class_name"
    ]

    day = state[
        "day"
    ]

    valid_date = get_week_date(
        day
    )

    changes = {
        row[0]: row

        for row in get_schedule_changes(
            class_name,
            day,
            valid_date
        )
    }

    lessons = get_schedule(
        class_name,
        day
    )

    text = (
        "✅ Расписание изменено!\n\n"
        f"{class_name.upper()}\n\n"
        f"{day} (изменено)\n\n"
    )

    for lesson in lessons:

        lesson_no = lesson[0]
        subject = lesson[1]
        cabinet = lesson[2]
        teacher = lesson[3]

        change = changes.get(
            lesson_no
        )

        if change:

            if change[1]:

                teacher = change[1]

            if change[2]:

                cabinet = change[2]

        line = (
            f"{lesson_no} урок - "
            f"{subject}"
        )

        if teacher:

            line += (
                f" — {teacher}"
            )

        if cabinet:

            line += (
                f" (каб. {cabinet})"
            )

        text += (
            line + "\n"
        )

    edit_state.pop(
        callback.from_user.id,
        None
    )

    await callback.answer(
        "Готово!"
    )

    await callback.message.edit_text(
        text
    )



# Запуск


async def main():

    init_db()

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