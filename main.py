import os
import threading
import time
import psycopg2
import telebot
from telebot.types import InlineKeyboardMarkup, InlineKeyboardButton
from http.server import HTTPServer, BaseHTTPRequestHandler

# --- 1. SERVIDOR HTTP PARA RENDER ---
class SimpleHTTPRequestHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.end_headers()
        self.wfile.write(b"OK - Bot activo")

def run_http_server():
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()

threading.Thread(target=run_http_server, daemon=True).start()

# --- 2. CONFIGURACIÓN ---
TOKEN = os.environ.get('TOKEN')
DATABASE_URL = os.environ.get('DATABASE_URL')

bot = telebot.TeleBot(TOKEN)
MAX_STEPS = 1

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

# Inicializar tablas en Supabase
def init_db():
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        CREATE TABLE IF NOT EXISTS users (
            user_id BIGINT PRIMARY KEY,
            name TEXT,
            step INT DEFAULT 1,
            verified BOOLEAN DEFAULT FALSE,
            pending_movie_id INT,
            updated_at TIMESTAMP DEFAULT NOW()
        )
    """)
    cur.execute("""
        CREATE TABLE IF NOT EXISTS movies (
            id SERIAL PRIMARY KEY,
            title TEXT NOT NULL,
            file_id TEXT NOT NULL,
            shortener_url TEXT NOT NULL,
            created_at TIMESTAMP DEFAULT NOW()
        )
    """)
    conn.commit()
    cur.close()
    conn.close()

def get_user(user_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT user_id, name, step, verified, pending_movie_id FROM users WHERE user_id = %s", (user_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return {"user_id": row[0], "name": row[1], "step": row[2], "verified": row[3], "pending_movie_id": row[4]}
    return None

def update_user_state(user_id, name, step=1, verified=False, pending_movie_id=None):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("""
        INSERT INTO users (user_id, name, step, verified, pending_movie_id, updated_at)
        VALUES (%s, %s, %s, %s, %s, NOW())
        ON CONFLICT (user_id) 
        DO UPDATE SET name = EXCLUDED.name, step = EXCLUDED.step, verified = EXCLUDED.verified, 
                      pending_movie_id = COALESCE(EXCLUDED.pending_movie_id, users.pending_movie_id), updated_at = NOW()
    """, (user_id, name, step, verified, pending_movie_id))
    conn.commit()
    cur.close()
    conn.close()

def get_movie(movie_id):
    conn = get_db_connection()
    cur = conn.cursor()
    cur.execute("SELECT id, title, file_id, shortener_url FROM movies WHERE id = %s", (movie_id,))
    row = cur.fetchone()
    cur.close()
    conn.close()
    if row:
        return {"id": row[0], "title": row[1], "file_id": row[2], "shortener_url": row[3]}
    return None

# --- 3. AUTO-BORRADO DE MENSAJES ---
def delete_message_after_delay(chat_id, message_id, delay_seconds=120):
    def worker():
        time.sleep(delay_seconds)
        try:
            bot.delete_message(chat_id=chat_id, message_id=message_id)
        except Exception:
            pass
    threading.Thread(target=worker, daemon=True).start()

# --- 4. MANEJO DE COMANDOS ---
@bot.message_handler(commands=['start'])
def handle_start(message):
    user_id = message.from_user.id
    name = message.from_user.first_name
    text_payload = message.text

    # Detectar si el usuario viene pidiendo una película específica (ej: /start movie_3)
    target_movie_id = None
    if "movie_" in text_payload:
        try:
            target_movie_id = int(text_payload.split("movie_")[1])
        except ValueError:
            pass

    user = get_user(user_id)
    if not user:
        update_user_state(user_id, name, step=1, verified=False, pending_movie_id=target_movie_id)
        user = {"user_id": user_id, "name": name, "step": 1, "verified": False, "pending_movie_id": target_movie_id}
    elif target_movie_id:
        update_user_state(user_id, name, pending_movie_id=target_movie_id)
        user["pending_movie_id"] = target_movie_id

    # Si el usuario completó la verificación y regresa al bot con verify_
    if "verify_" in text_payload:
        update_user_state(user_id, name, step=1, verified=True)
        send_success_verification(message.chat.id, name, user.get("pending_movie_id"))
        return

    # Validar estado de verificación actual en la BD
    if user["verified"]:
        send_success_verification(message.chat.id, name, user.get("pending_movie_id"))
    else:
        send_verification_step(message.chat.id, user_id, name)

def send_verification_step(chat_id, user_id, name):
    user = get_user(user_id)
    movie_id = user.get("pending_movie_id") if user else None

    # Obtener el acortador específico de la película o uno por defecto
    shortener_url = "https://tu-web-acortadora.com/api?api=TU_API_KEY&url="
    if movie_id:
        movie = get_movie(movie_id)
        if movie and movie["shortener_url"]:
            shortener_url = movie["shortener_url"]

    text = (
        f"👋 **HEY** {name},\n\n"
        f"📌 **DEBES VERIFICARTE PARA ACCEDER A LA PELÍCULA.**\n\n"
        f"#VERIFICATION:- 1/1 ✓"
    )
    
    markup = InlineKeyboardMarkup()
    bot_username = bot.get_me().username
    bot_link = f"https://t.me/{bot_username}?start=verify_{user_id}"
    
    # Asegurar que el enlace del acortador reciba correctamente el destino
    if "=" in shortener_url:
        final_verify_url = shortener_url + bot_link
    else:
        final_verify_url = shortener_url + f"&url={bot_link}" if "?" in shortener_url else shortener_url + f"?url={bot_link}"
    
    markup.add(InlineKeyboardButton("🟢 CLICK AQUÍ PARA VERIFICAR 🟢", url=final_verify_url))
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")

def send_success_verification(chat_id, name, movie_id):
    text = (
        f"👋 **HEY** {name},\n\n"
        f"**¡VERIFICACIÓN COMPLETADA ✓!**"
    )
    
    markup = InlineKeyboardMarkup()
    if movie_id:
        markup.add(InlineKeyboardButton("✅ DESCARGAR / VER PELÍCULA ✅", callback_data=f"get_movie_{movie_id}"))
    else:
        markup.add(InlineKeyboardButton("🎬 VER CATÁLOGO DE PELÍCULAS", callback_data="show_catalog"))
    
    bot.send_message(chat_id, text, reply_markup=markup, parse_mode="Markdown")

@bot.callback_query_handler(func=lambda call: call.data.startswith("get_movie_"))
def deliver_movie(call):
    user_id = call.from_user.id
    chat_id = call.message.chat.id
    user = get_user(user_id)
    
    if user and user["verified"]:
        try:
            movie_id = int(call.data.split("get_movie_")[1])
            movie = get_movie(movie_id)
            
            if movie:
                caption_text = f"🎬 **{movie['title']}**\n\n⚠️ *Este archivo se borrará en 2 minutos. Reenvíalo a otro chat.*"
                sent_msg = bot.send_video(chat_id=chat_id, video=movie['file_id'], caption=caption_text, parse_mode="Markdown")
                delete_message_after_delay(chat_id, sent_msg.message_id, 120)
                bot.answer_callback_query(call.id, "¡Película enviada!")
            else:
                bot.answer_callback_query(call.id, "❌ Película no encontrada.", show_alert=True)
        except Exception as e:
            bot.answer_callback_query(call.id, "❌ Error al enviar la película.", show_alert=True)
    else:
        bot.answer_callback_query(call.id, "❌ Debes completar la verificación primero.", show_alert=True)

# --- 5. INICIO DEL BOT ---
if __name__ == "__main__":
    init_db()
    print("Bot dinámico con Supabase en marcha...")
    bot.infinity_polling(skip_pending=True)