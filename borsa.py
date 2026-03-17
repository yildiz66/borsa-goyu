import os, telebot, yfinance as yf, pandas_ta as ta, io, threading, warnings, time, requests
import pandas as pd
import matplotlib
matplotlib.use("Agg") 
import matplotlib.pyplot as plt
import google.generativeai as genai
from telebot import types
from flask import Flask

warnings.filterwarnings("ignore")

app = Flask(__name__)
@app.route('/')
def home(): return "Borsabot Aktif", 200

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
MY_ID = os.environ.get("MY_CHAT_ID")

bot = telebot.TeleBot(TOKEN)
genai.configure(api_key=GEMINI_KEY)
ai_model = genai.GenerativeModel('gemini-1.5-flash')

# Sizin 147 Hisselik Listeniz (Özetlendi, tam listeyi koruyun)
KATILIM_LISTESI = ["AKSA", "ASELS", "THYAO", "TUPRS", "SASA", "EREGL", "SISE", "MGROS", "FROTO"] # + 147 hisse

def inline_menu():
    markup = types.InlineKeyboardMarkup(row_width=2)
    markup.add(
        types.InlineKeyboardButton("📊 Günlük Fırsatlar", callback_data="vade_1d"),
        types.InlineKeyboardButton("📈 Aylık Fırsatlar", callback_data="vade_1mo")
    )
    return markup

def analiz_motoru(hisse, donem="1d"):
    try:
        ticker = hisse.upper().strip()
        f_t = ticker + ".IS" if not ticker.endswith(".IS") else ticker
        p = "6mo" if donem == "1d" else "5y"
        df = yf.download(f_t, period=p, interval=donem, progress=False, threads=False)
        if df is None or df.empty or len(df) < 20: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df["RSI"] = ta.rsi(df["Close"], length=14)
        bb = ta.bbands(df["Close"], length=20)
        last = df.iloc[-1]
        return {"ticker": ticker, "fiyat": float(last["Close"]), "rsi": float(last["RSI"]), "hedef": float(bb.iloc[-1, 2]), "df": df}
    except: return None

def ai_yorumla(hisse_verileri):
    try:
        prompt = f"""
        Bir borsa uzmanı gibi davran. Aşağıdaki 5 hisse senedi teknik verilerine (RSI ve Bollinger Hedefi) bakarak, 
        Emir Bey için içlerinden en potansiyelli olan 1 veya 2 tanesini seç. 
        Neden seçtiğini çok kısa ve öz bir şekilde (maksimum 3 cümle) açıkla.
        Hisseler: {hisse_verileri}
        """
        response = ai_model.generate_content(prompt)
        return response.text
    except:
        return "⚠️ Yapay zeka yorumu şu an alınamadı."

def rapor_gonder(vade_kod, vade_adi):
    bot.send_message(MY_ID, f"🔍 {vade_adi} tarama başladı...")
    havuz = []
    for h in KATILIM_LISTESI:
        res = analiz_motoru(h, vade_kod)
        if res and 45 < res["rsi"] < 65: havuz.append(res)
    
    en_iyi_5 = sorted(havuz, key=lambda x: x['rsi'], reverse=True)[:5]
    
    ai_data = []
    for t in en_iyi_5:
        pot = round(((t["hedef"] - t["fiyat"]) / t["fiyat"]) * 100, 1)
        ai_data.append(f"{t['ticker']} (Fiyat:{t['fiyat']}, RSI:{round(t['rsi'],2)}, Potansiyel:%{pot})")
        
        # Grafik ve Mesaj Gönderimi
        mesaj = f"💎 *{t['ticker']}*\nFiyat: `{round(t['fiyat'], 2)}` | RSI: `{round(t['rsi'], 2)}`"
        plt.figure(figsize=(4, 2)); plt.plot(t["df"]["Close"].tail(20).values); plt.axis('off')
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(MY_ID, buf, caption=mesaj, parse_mode="Markdown"); plt.close()

    # --- GEMINI YORUMU BURADA ÇALIŞIYOR ---
    if ai_data:
        bot.send_message(MY_ID, "🤖 *Gemini'nin Seçimi ve Analizi:*", parse_mode="Markdown")
        yorum = ai_yorumla(ai_data)
        bot.send_message(MY_ID, yorum, reply_markup=inline_menu())

@bot.callback_query_handler(func=lambda call: True)
def callback_query(call):
    if call.data == "vade_1d": rapor_gonder("1d", "GÜNLÜK")
    elif call.data == "vade_1mo": rapor_gonder("1mo", "AYLIK")
    bot.answer_callback_query(call.id)

@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, "📈 Terminal Aktif Emir Bey.", reply_markup=inline_menu())

if __name__ == "__main__":
    requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True")
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080)), daemon=True).start()
    bot.polling(none_stop=True)
