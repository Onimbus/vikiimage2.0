import telebot
import wikipedia
import re
import os
import json
import time
import requests
import base64
from PIL import Image
from io import BytesIO
from config import TOKEN, API_FB, SECRET_KEY
from pathlib import Path

bot = telebot.TeleBot(TOKEN)
wikipedia.set_lang("ru")

user_stats = {}
generated_images = {}
user_folders = {}

class Text2ImageAPI:
    def __init__(self, url, api_key, secret_key):
        self.URL = url
        self.AUTH_HEADERS = {
            'X-Key': f'Key {api_key}',
            'X-Secret': f'Secret {secret_key}',
        }

    def get_model(self):
        response = requests.get(self.URL + 'key/api/v1/models', headers=self.AUTH_HEADERS)
        data = response.json()
        return data[0]['id']

    def generate(self, prompt, model, images=1, width=1024, height=1024):
        params = {
            "type": "GENERATE",
            "numImages": images,
            "width": width,
            "height": height,
            "generateParams": {
                "query": f"{prompt}"
            }
        }
        data = {
            'model_id': (None, model),
            'params': (None, json.dumps(params), 'application/json')
        }
        response = requests.post(self.URL + 'key/api/v1/text2image/run', headers=self.AUTH_HEADERS, files=data)
        data = response.json()
        return data['uuid']

    def check_generation(self, request_id, attempts=10, delay=10):
        while attempts > 0:
            response = requests.get(self.URL + 'key/api/v1/text2image/status/' + request_id, headers=self.AUTH_HEADERS)
            data = response.json()
            if data['status'] == 'DONE':
                return data['images']
            attempts -= 1
            time.sleep(delay)

    def save_image(self, base64_string, file_path):
        decoded_data = base64.b64decode(base64_string)
        image = Image.open(BytesIO(decoded_data))
        image.save(file_path)

def getwiki(s):
    try:
        ny = wikipedia.page(s)
        wikitext = ny.content[:1000]
        wikimas = wikitext.split('.')[:-1]
        wikitext2 = ''
        for x in wikimas:
            if '==' not in x:
                if len(x.strip()) > 3:
                    wikitext2 += x + '.'
                else:
                    break
        wikitext2 = re.sub(r'$[^()]*$', '', wikitext2)
        wikitext2 = re.sub(r'\{[^\{\}]*\}', '', wikitext2)
        return wikitext2
    except Exception:
        return 'В энциклопедии нет информации об этом'

def create_user_folder(user_id):
    folder_path = Path(f'users_data/{user_id}')
    folder_path.mkdir(parents=True, exist_ok=True)
    return folder_path

def update_stats(user_id, action):
    if user_id not in user_stats:
        user_stats[user_id] = {'image_requests': 0, 'wiki_requests': 0}
    user_stats[user_id][action] += 1

def create_keyboard():
    keyboard = telebot.types.ReplyKeyboardMarkup(resize_keyboard=True)
    keyboard.add(
        telebot.types.KeyboardButton("Генерировать изображение"),
        telebot.types.KeyboardButton("Получить информацию из Wikipedia"),
        telebot.types.KeyboardButton("Статистика"),
        telebot.types.KeyboardButton("Галерея изображений"),
        telebot.types.KeyboardButton("Помощник")
    )
    return keyboard

@bot.message_handler(commands=['start', 'help'])
def send_welcome(message):
    bot.reply_to(message, "Привет! Я бот для генерации изображений и поиска информации в Wikipedia.\nВыберите действие:", reply_markup=create_keyboard())

@bot.message_handler(func=lambda message: True)
def handle_message(message):
    user_id = message.chat.id
    if message.text == "Генерировать изображение":
        prompt_message = bot.send_message(user_id, "Введите текстовый запрос (начните с '!' для генерации изображения):")
        bot.register_next_step_handler(prompt_message, handle_image_generation)
    elif message.text == "Получить информацию из Wikipedia":
        info_message = bot.send_message(user_id, "Введите слово или фразу, чтобы получить информацию:")
        bot.register_next_step_handler(info_message, handle_wiki_request)
    elif message.text == "Статистика":
        stats = user_stats.get(user_id, {'image_requests': 0, 'wiki_requests': 0})
        bot.send_message(user_id, f"Статистика:\nИзображения запрошены: {stats['image_requests']}\nWikipedia запросы: {stats['wiki_requests']}")
    elif message.text == "Галерея изображений":
        show_image_gallery(user_id, 0)  
    elif message.text == "Помощник":
        show_helper_examples(user_id)
    else:
        bot.send_message(user_id, "Пожалуйста, выберите одно из действий на клавиатуре.")

def handle_image_generation(message):
    prompt = message.text[1:]  
    typing_message = bot.send_message(message.chat.id, "Генерирую картинку...")

    api = Text2ImageAPI('https://api-key.fusionbrain.ai/', API_FB, SECRET_KEY)
    model_id = api.get_model()
    uuid = api.generate(prompt, model_id)
    images = api.check_generation(uuid)

    
    user_folder = create_user_folder(message.chat.id)

    
    new_image_paths = []
    for i, img in enumerate(images):
        image_path = user_folder / f'generated_image_{i}.jpg'
        api.save_image(img, str(image_path))
        new_image_paths.append(str(image_path))  

    
    if message.chat.id not in generated_images:
        generated_images[message.chat.id] = []

    
    generated_images[message.chat.id].extend(new_image_paths)

    
    for index, image_path in enumerate(new_image_paths):
        with open(image_path, 'rb') as photo:
            bot.send_photo(message.chat.id, photo)

        
        add_to_gallery_button = telebot.types.InlineKeyboardMarkup()
        add_to_gallery_button.add(
            telebot.types.InlineKeyboardButton(
                text=f"Добавить {len(generated_images[message.chat.id]) + 1}",
                callback_data=f"add_{message.chat.id}_{index}"
            ),
            telebot.types.InlineKeyboardButton(
                text="Переделать",
                callback_data=f"retry_{message.chat.id}_{prompt}"  
            )
        )

        
        bot.send_message(message.chat.id, "Какое действие хотите выполнить?", reply_markup=add_to_gallery_button)

    bot.delete_message(message.chat.id, typing_message.message_id)
    update_stats(message.chat.id, 'image_requests')

@bot.callback_query_handler(func=lambda call: call.data.startswith("add_"))
def add_to_gallery(call):
    parts = call.data.split("_")
    if len(parts) != 3:
        bot.send_message(call.from_user.id, "Ошибка: данные повреждены.")
        return

    _, user_id, image_index = parts
    user_id = int(user_id)

    
    if user_id not in generated_images or not generated_images[user_id]:
        bot.send_message(user_id, "Ошибка: нет сохраненных изображений.")
        return

    
    full_image_path = generated_images[user_id][int(image_index)]

    
    if not os.path.exists(full_image_path):
        bot.send_message(user_id, f"Ошибка: Изображение {full_image_path} не найдено.")
        return

    
    generated_images[user_id].append(full_image_path)
    bot.send_message(user_id, f"Изображение {full_image_path} было добавлено в галерею!")

@bot.callback_query_handler(func=lambda call: call.data.startswith("retry_"))
def retry_image(call):
    parts = call.data.split("_")
    if len(parts) != 3:
        bot.send_message(call.from_user.id, "Ошибка: данные повреждены.")
        return

    _, user_id, prompt = parts
    user_id = int(user_id)

    
    prompt = f"!{prompt}"  
    bot.send_message(user_id, f"Генерирую новое изображение по вашему запросу: {prompt}")
    
    handle_image_generation(telebot.types.Message(chat={"id": user_id}, text=prompt))

def show_image_gallery(user_id, index):
    if user_id in generated_images and generated_images[user_id]:
        images = generated_images[user_id]
        if index < 0 or index >= len(images):
            bot.send_message(user_id, "Нет доступных изображений в галерее.")
            return

        with open(images[index], 'rb') as photo:
            bot.send_photo(user_id, photo)

        
        keyboard = telebot.types.InlineKeyboardMarkup()
        if index > 0:
            keyboard.add(telebot.types.InlineKeyboardButton("Назад", callback_data=f"gallery_{user_id}_{index - 1}"))
        if index < len(images) - 1:
            keyboard.add(telebot.types.InlineKeyboardButton("Вперед", callback_data=f"gallery_{user_id}_{index + 1}"))

        bot.send_message(user_id, "Используйте кнопки для навигации:", reply_markup=keyboard)
    else:
        bot.send_message(user_id, "Галерея пустая.")

@bot.callback_query_handler(func=lambda call: call.data.startswith("gallery_"))
def handle_gallery_navigation(call):
    parts = call.data.split("_")
    if len(parts) != 3:
        bot.send_message(call.from_user.id, "Ошибка: данные повреждены.")
        return

    _, user_id, index = parts
    user_id = int(user_id)
    index = int(index)  

    show_image_gallery(user_id, index)

def handle_wiki_request(message):
    result = getwiki(message.text)
    bot.send_message(message.chat.id, result)
    update_stats(message.chat.id, 'wiki_requests')

def show_helper_examples(user_id):
    examples = (
        "1. !Кошка на луне\n"
        "2. !Пейзаж природы\n"
        "3. !Абстрактное искусство\n"
        "4. !Городская сценка\n"
        "5. !Портрет человека"
    )
    bot.send_message(user_id, f"Примеры запросов для генерации изображений:\n{examples}")

bot.polling(none_stop=True, interval=0)