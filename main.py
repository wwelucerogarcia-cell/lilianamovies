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
    port = int(os.environ.get("PORT", 10000))
    server = HTTPServer(("0.0.0.0", port), SimpleHTTPRequestHandler)
    server.serve_forever()

# Iniciar servidor web en un hilo secundario para cumplir el chequeo de puertos de Render
threading.Thread(target=run_http_server, daemon=True).start()


# --- 2. CONFIGURACIÓN DEL BOT Y CONEXIÓN A BASE DE DATOS ---
TOKEN = os.environ.get('TOKEN')
DATABASE_URL = os.environ.get('DATABASE_URL')

bot = telebot.TeleBot(TOKEN)

MAX_STEPS = 1
ACORTADOR_API_URL = "https://tu-web-acortadora.com/api?api=TU_API_KEY&url="

def get_db_connection():
    return psycopg2.connect(DATABASE_URL, sslmode='require')

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
    user_id = message