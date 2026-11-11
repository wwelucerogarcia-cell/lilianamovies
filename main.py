import os
import threading
import time
import psycopg2
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- 1. SERVIDOR HTTP EN SEGUNDO PLANO (PARA RENDER) ---
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK - Bot activo")

def run_http_server():
    try:
        port = int(os.environ.get("PORT", 10000))
        server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
        print(f"Servidor HTTP corriendo en el puerto {port}")
        server.serve_forever()
    except Exception as e:
        print(f"Error en servidor HTTP: {e}")

# Iniciar servidor web en un hilo secundario
threading.Thread(target=run_http_server, daemon=True).start()


# --- 2. CONFIGURACIÓN Y VALIDACIÓN ---
TOKEN = os.environ.get('TOKEN')
DATABASE_URL = os.environ.get('DATABASE_URL')

if not TOKEN:
    raise ValueError("¡Falta la variable de entorno 'TOKEN' en Render!")
if not DATABASE_URL:
    raise ValueError("¡Falta la variable de entorno 'DATABASE_URL' en Render!")

bot = telebot.TeleBot(TOKEN)

MAX_STEPS = 1
ACORTADOR_API_URL = "https://tu-web-acortadora.com/api?api=TU_API_KEY&url="

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

# Crear la tabla de usuarios automáticamente si no existe
def init_db():
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            CREATE TABLE IF NOT EXISTS users (
                user_id BIGINT PRIMARY KEY,
                name TEXT,
                step INT DEFAULT 1,
                verified BOOLEAN DEFAULT FALSE,
                updated_at TIMESTAMP DEFAULT NOW()
            )
        """)
        conn.commit()
        cur.close()
        conn.close()
        print("Base de datos inicializada correctamente.")
    except Exception as e:
        print(f"Error al inicializar la base de datos: {e}")

def get_user(user_id):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("SELECT user_id, name, step, verified FROM users WHERE user_id = %s", (user_id,))
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row:
            return {"user_id": row[0], "name": row[1], "step": row[2], "verified": row[3]}
    except Exception as e:
        print(f"Error BD al obtener usuario: {e}")
    return None

def create_or_update_user(user_id, name, step=1, verified=False):
    try:
        conn = get_db_connection()
        cur = conn.cursor()
        cur.execute("""
            INSERT INTO users (user_id, name, step, verified, updated_at)
            VALUES (%s, %s, %s, %s, NOW())
            ON CONFLICT (user_id) 
            DO UPDATE SET name = EXCLUDED.name, step = EXCLUDED.step, verified = EXCLUDED.verified, updated_at = NOW()
        """, (user_id, name, step, verified))
        conn.commit()
        cur.close()
        conn.close()
    except Exception as e:
        print(f"Error BD al actualizar usuario: {e}")


# --- 3. AUTO-BORRADO DE MENSAJES (2 MINUTOS) ---
def delete_message_after_delay(chat_id, message_id, delay_seconds=120):
    def worker():
        time.sleep(delay_seconds)
        try:
            bot.delete_message(chat_id=chat_id, message_id=message_id)
            print(f"Mensaje {message_id} borrado automáticamente tras {delay_seconds} segundos.")
        except Exception as e:
            print(f"No se pudo borrar el mensaje {message_id}: {e}")

    threading.Thread(target=worker, daemon=True).start()


# --- 4. COMANDOS Y FLUJO DEL BOT ---
@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id
    name = message.from_user.first_name
    text_payload = message.text

    user = get_user(user_id)
    if not user:
        create_or_update_user(user_id, name, step=1, verified=False)
        user = {"user_id": user_id, "name": name, "step": 1, "verified": False}

    if "verify_" in text_payload:
        new_step = user["step"] + 1
        if new_step > MAX_STEPS:
            create_or_update_user(user_id, name, step=new_step, verified=True)
            send_success_verification(message.chat.id, name)
        else:
            create_or_update_user(user_id, name, step=new_step, verified=False)
            send_verification_step(message.chat.id, user_id, name)
        return

    if user["verified"]:
        send_success_verification(message.chat.id, name)
    else:
        send_verification_step(message.chat.id, user_id, name)

def send_verification_step(chat_id, user_id, name):
    user = get_user(user_id)
    current_step = user["step"] if user else 1

    text = (
        f"👋 **HEY** {name},\n\n"
        f"📌 **YOU ARE NOT VERIFIED TODAY, PLEASE CLICK ON VERIFY & GET UNLIMITED ACCESS FOR TILL NEXT VERIFICATION.**\n\n"
        f"#VERIFICATION:- {current_step}/{MAX_STEPS} ✓\n\n"
        f"_IF YOU WANT DIRECT FILES THEN YOU CAN TAKE PREMIUM SERVICE (NO NEED TO VERIFY)._"
    )
    
    markup = InlineKeyboardMarkup()
    bot_username = bot.get_me().username
    bot_link = f"https://t.me/{bot_username}?start=verify_{user_id}"
    final_verify_url = ACORTADOR_API_URL + bot_link
    
    markup.add(InlineKeyboardButton("🟢 CLICK HERE TO VERIFY 🟢", url=final_verify_url))
    markup.add(InlineKeyboardButton("❓❓ HOW TO VERIFY ❓❓", url="https://t.me/TuCanalDeAyuda"))
    
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")

def send_success_verification(chat_id, name):
    banner_url = "https://i.imgur.com/TusImágenesEjemplo.jpg"
    text = (
        f"👋 **HEY** {name},\n\n"
        f"**YOU HAVE COMPLETED THE VERIFICATION ✓**\n\n"
        f"**NOW YOU HAVE UNLIMITED ACCESS FOR NEXT VERIFICATION.**"
    )
    
    markup = InlineKeyboardMarkup()
    markup.add(InlineKeyboardButton("✅ CLICK HERE TO GET FILE ✅", callback_data="get_movie_file"))
    
    try:
        bot.send_photo(chat_id, banner_url, caption=text, reply_markup=markup, parse_mode="Markdown")
    except Exception:
        bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data == "get_movie_file")
def deliver_movie(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    user = get_user(user_id)
    
    if user and user["verified"]:
        movie_title = "TOXiC 2026 720p UNCENSORED HDRip Hindi Kannada Telugu"
        file_id_or_url = "AQUÍ_EL_FILE_ID_DE_TELEGRAM_DE_TU_PELICULA"
        
        markup = InlineKeyboardMarkup()
        markup.add(InlineKeyboardButton("🚀 FAST DOWNLOAD / WATCH ONLINE 💻", url="https://t.me/TuReproductorWeb"))
        markup.add(InlineKeyboardButton("ℹ️ VIEW AUDIO & SUBS INFO ℹ️", callback_data="audio_info"))
        markup.add(InlineKeyboardButton("📌 JOIN UPDATES CHANNEL 📌", url="https://t.me/TuCanalDeActualizaciones"))
        
        caption_text = (
            f"🎬 **{movie_title}**\n\n"
            f"⚠️ *THIS MOVIE FILE/VIDEO WILL BE DELETED BY USER REFORWARD*\n\n"
            f"_PLEASE FORWARD THIS FILE TO SOMEWHERE ELSE & START DOWNLOADING THERE_"
        )
        
        sent_msg = bot.send_video(chat_id=chat_id, video=file_id_or_url, caption=caption_text, reply_markup=markup, parse_mode="Markdown")
        delete_message_after_delay(chat_id=chat_id, message_id=sent_msg.message_id, delay_seconds=120)
    else:
        bot.answer_callback_query(call.id, "❌ Debes completar la verificación primero.", show_alert=True)


# --- 5. BUCLE PRINCIPAL DEL BOT ---
if __name__ == "__main__":
    print("Inicializando base de datos...")
    init_db()
    print("Bot en marcha y escuchando eventos...")
    bot.infinity_polling(skip_pending=True)