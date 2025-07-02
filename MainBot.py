import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
import httpx
from bs4 import BeautifulSoup
import re
import json
import os
import logging
import asyncio
from datetime import datetime

TOKEN = '*'
bot = telebot.TeleBot(TOKEN)

USER_DATA_FILE = 'user_codes.json'
NOTIFY_TIMES_FILE = 'notify_times.json'
USER_URLS_FILE = 'user_urls.json'
USER_RESULTS_FILE = 'user_results.json'

logging.basicConfig(level=logging.INFO)

user_codes = {}
notify_times = {}
user_urls = {}
user_results = {}

URLS = [
    'Ссылки'
]

def load_json_file(filepath):
    if not os.path.exists(filepath):
        return {}
    try:
        with open(filepath, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception as e:
        logging.error(f"Error loading {filepath}: {e}")
        return {}

def save_json_file(filepath, data):
    try:
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        logging.error(f"Error saving {filepath}: {e}")

def load_all_data():
    global user_codes, notify_times, user_urls, user_results
    user_codes = load_json_file(USER_DATA_FILE)
    notify_times = load_json_file(NOTIFY_TIMES_FILE)
    user_urls = load_json_file(USER_URLS_FILE)
    user_results = load_json_file(USER_RESULTS_FILE)

def save_all_data():
    save_json_file(USER_DATA_FILE, user_codes)
    save_json_file(NOTIFY_TIMES_FILE, notify_times)
    save_json_file(USER_URLS_FILE, user_urls)
    save_json_file(USER_RESULTS_FILE, user_results)

def get_user_code(user_id):
    return user_codes.get(str(user_id))

def set_user_code(user_id, code):
    user_codes[str(user_id)] = code
    save_json_file(USER_DATA_FILE, user_codes)

def set_user_notify_time(user_id, time_str):
    notify_times[str(user_id)] = time_str
    save_json_file(NOTIFY_TIMES_FILE, notify_times)

def get_user_notify_time(user_id):
    return notify_times.get(str(user_id))

def set_user_urls(user_id, urls):
    user_urls[str(user_id)] = urls
    save_json_file(USER_URLS_FILE, user_urls)

def get_user_urls(user_id):
    return user_urls.get(str(user_id))

def set_user_results(user_id, results):
    user_results[str(user_id)] = results
    save_json_file(USER_RESULTS_FILE, user_results)

def get_user_results(user_id):
    return user_results.get(str(user_id), [])

def get_keyboard():
    markup = InlineKeyboardMarkup()
    markup.row(
        InlineKeyboardButton("Проверить результат", callback_data='check'),
        InlineKeyboardButton("Изменить код", callback_data='change')
    )
    markup.row(
        InlineKeyboardButton("Настроить уведомления", callback_data='set_notify')
    )
    return markup

@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id
    code = get_user_code(user_id)
    if code:
        bot.send_message(message.chat.id, f"Привет! Ваш код: {code}\nВыберите действие:", reply_markup=get_keyboard())
    else:
        bot.send_message(message.chat.id, "Введите ваш уникальный код поступающего:")
        bot.register_next_step_handler(message, save_code)

def save_code(message):
    code = message.text.strip()
    if not code.isdigit():
        bot.send_message(message.chat.id, "Пожалуйста, введите только числовой код.")
        bot.register_next_step_handler(message, save_code)
        return
    user_id = message.from_user.id
    set_user_code(user_id, code)
    bot.send_message(message.chat.id, f"Код сохранён: {code}\nОжидайте, первая проверка может занять несколько минут")
    asyncio.run(run_check(message.chat.id, code, True))

@bot.callback_query_handler(func=lambda call: call.data == 'change')
def callback_change(call):
    bot.send_message(call.message.chat.id, "Введите новый уникальный код поступающего:")
    bot.register_next_step_handler(call.message, save_code)

@bot.callback_query_handler(func=lambda call: call.data == 'check')
def callback_check(call):
    code = get_user_code(call.from_user.id)
    if not code:
        bot.send_message(call.message.chat.id, "Сначала введите код. Отправьте его сообщением.")
        return
    bot.send_message(call.message.chat.id, "Проверяем данные...")
    asyncio.run(run_check(call.message.chat.id, code, False))

@bot.callback_query_handler(func=lambda call: call.data == 'set_notify')
def callback_notify(call):
    bot.send_message(call.message.chat.id, "🕓 Введите время в формате ЧЧ:ММ, когда хотите получать уведомления (например, 14:30):")
    bot.register_next_step_handler(call.message, save_notify_time)

def save_notify_time(message):
    user_id = message.from_user.id
    try:
        datetime.strptime(message.text.strip(), "%H:%M")
        set_user_notify_time(user_id, message.text.strip())
        bot.send_message(message.chat.id, f"Уведомления будут приходить в {message.text.strip()}")
        code = get_user_code(user_id)
        if code:
            asyncio.run(run_check(message.chat.id, code, False))
    except ValueError:
        bot.send_message(message.chat.id, "Неверный формат. Попробуйте снова (ЧЧ:ММ)")
        bot.register_next_step_handler(message, save_notify_time)

async def run_check(chat_id, code, first_check):
    await check_all_lists(chat_id, code, first_check)

async def check_all_lists(chat_id, unique_code, first_check=False):
    found_any = False
    found_urls = []
    results = []

    urls_to_check = URLS if first_check else get_user_urls(chat_id) or []

    if not urls_to_check:
        bot.send_message(chat_id, "Нет сохранённых ссылок. Выполните полную проверку сначала (например, измените код).")
        return

    async with httpx.AsyncClient(timeout=15.0) as client:
        tasks = [client.get(url) for url in urls_to_check]
        responses = await asyncio.gather(*tasks, return_exceptions=True)

        for idx, response in enumerate(responses):
            url = urls_to_check[idx]
            if isinstance(response, Exception):
                logging.error(f"Ошибка при запросе {url}: {response}")
                continue

            try:
                response.raise_for_status()
                soup = BeautifulSoup(response.text, 'html.parser')
                program_name_tag = soup.find('div', class_='competitive-group')
                program_name = program_name_tag.text.strip() if program_name_tag else url

                timestamp = "неизвестно"
                for tag in soup.find_all(string=re.compile(r'данные на')):
                    m = re.search(r'данные на ([\d:. ]+\d{4})', tag.strip())
                    if m:
                        timestamp = m.group(1)
                        break

                vacant_places = 0
                vacant_text = soup.find(string=re.compile(r'Количество вакантных мест'))
                if vacant_text:
                    m = re.search(r'(\d+)', vacant_text)
                    if m:
                        vacant_places = int(m.group(1))

                position = 0
                found_in_this_url = False
                for row in soup.find_all('tr'):
                    cells = row.find_all('td')
                    if cells and cells[0].text.strip().isdigit():
                        position += 1
                        if cells[0].text.strip() == unique_code:
                            score = cells[1].text.strip() if len(cells) >= 2 else "не указано"
                            try:
                                numeric_score = int(score)
                            except ValueError:
                                numeric_score = 0

                            if numeric_score <= 120:
                                msg = (
                                    f"📌 *{program_name}*\n"
                                    f"🕒 Данные на: {timestamp}\n"
                                    f"👤 Ваш код: `{unique_code}`\n"
                                    f"📊 Позиция в списке: *{position}*\n"
                                    f"🎯 Баллы: *{score}*\n"
                                    f"🪑 Вакантных мест: *{vacant_places}*\n"
                                    f"❌ **Статус: НЕ ПРОХОДИШЬ (баллы ≤ 120)**"
                                )
                            else:
                                if position <= vacant_places:
                                    found_any = True
                                    found_in_this_url = True
                                    msg = (
                                        f"📌 *{program_name}*\n"
                                        f"🕒 Данные на: {timestamp}\n"
                                        f"👤 Ваш код: `{unique_code}`\n"
                                        f"📊 Позиция в списке: *{position}*\n"
                                        f"🎯 Баллы: *{score}*\n"
                                        f"🪑 Вакантных мест: *{vacant_places}*\n"
                                        f"✅ **Статус: ПРОХОДИШЬ**"
                                    )
                                else:
                                    msg = (
                                        f"📌 *{program_name}*\n"
                                        f"🕒 Данные на: {timestamp}\n"
                                        f"👤 Ваш код: `{unique_code}`\n"
                                        f"📊 Позиция в списке: *{position}*\n"
                                        f"🎯 Баллы: *{score}*\n"
                                        f"🪑 Вакантных мест: *{vacant_places}*\n"
                                        f"❌ **Статус: НЕ ПРОХОДИШЬ (мест не хватает)**"
                                    )

                            results.append(msg)
                            break

                if first_check and found_in_this_url:
                    found_urls.append(url)

            except Exception as e:
                logging.error(f"Ошибка при обработке {url}: {e}")

    if not results:
        bot.send_message(chat_id, f"Код {unique_code} не найден в списках.")
    else:
        set_user_results(chat_id, results)
        if first_check:
            set_user_urls(chat_id, found_urls)
        send_result_with_navigation(chat_id, 0)

    bot.send_message(chat_id, "Выберите действие:", reply_markup=get_keyboard())

def send_result_with_navigation(chat_id, index):
    results = get_user_results(chat_id)
    if not results:
        bot.send_message(chat_id, "Нет направлений для отображения.")
        return

    text = results[index]
    markup = InlineKeyboardMarkup()
    if len(results) > 1:
        markup.row(
            InlineKeyboardButton("◀️ Предыдущее", callback_data=f'prev_{index}'),
            InlineKeyboardButton("▶️ Следующее", callback_data=f'next_{index}')
        )
    bot.send_message(chat_id, text, parse_mode='Markdown', reply_markup=markup)

@bot.callback_query_handler(func=lambda call: call.data.startswith('prev_') or call.data.startswith('next_'))
def callback_navigation(call):
    user_id = call.from_user.id
    results = get_user_results(user_id)
    if not results:
        bot.answer_callback_query(call.id, "Нет направлений.")
        return

    parts = call.data.split('_')
    action = parts[0]
    current_index = int(parts[1])

    if action == 'prev':
        new_index = (current_index - 1) % len(results)
    else:
        new_index = (current_index + 1) % len(results)

    new_text = results[new_index]
    markup = InlineKeyboardMarkup()
    if len(results) > 1:
        markup.row(
            InlineKeyboardButton("◀️ Предыдущее", callback_data=f'prev_{new_index}'),
            InlineKeyboardButton("▶️ Следующее", callback_data=f'next_{new_index}')
        )
    bot.edit_message_text(new_text, call.message.chat.id, call.message.message_id, parse_mode='Markdown', reply_markup=markup)
    bot.answer_callback_query(call.id)

async def notify_scheduler():
    while True:
        now_str = datetime.now().strftime("%H:%M")
        for user_id_str, notify_time in notify_times.items():
            if notify_time == now_str:
                user_id = int(user_id_str)
                code = get_user_code(user_id)
                if code:
                    try:
                        await check_all_lists(user_id, code, False)
                    except Exception as e:
                        logging.error(f"Ошибка при уведомлении пользователя {user_id}: {e}")
        await asyncio.sleep(60)

if __name__ == '__main__':
    load_all_data()
    loop = asyncio.get_event_loop()
    loop.create_task(notify_scheduler())
    bot.infinity_polling()
