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

# --- LİSTELER ---
KATILIM_LISTESI = ["AKSA", "ALTNY", "ASELS", "BIMAS", "BSOKE", "CANTE", "CIMSA", "CWENE", "DOAS", "EGEEN", "ENJSA", "EREGL", "FROTO", "GENTS", "GESAN", "GUBRF", "HEKTS", "JANTS", "KCAER", "KONTR", "KONYA", "KORDS", "KOZAL", "MAVI", "MGROS", "MIATK", "OYAKC", "PGSUS", "REEDR", "SASA", "SISE", "SMRTG", "TABGD", "THYAO", "TKFEN", "TMSN", "TOASO", "TUPRS", "ULKER", "VESBE", "YEOTK"]
FON_LISTESI = ["ALTINS.IS", "ZGOLD.IS", "GMSTR.IS", "GLDGR.IS"]

# --- 1. MAVİ MENÜYÜ TANIMLA (KOMUTLAR) ---
def set_commands():
    commands = [
        telebot.types.BotCommand("gunluk", "Katılım: Günlük Analiz"),
        telebot.types.BotCommand("ikihaftalik", "Katılım: 2 Haftalık Analiz"),
        telebot.types.BotCommand("aylik", "Katılım: Aylık Analiz"),
        telebot.types.BotCommand("fonlar", "Altın, Gümüş ve Fonlar"),
        telebot.types.BotCommand("start", "Sistemi Başlat / Yardım")
    ]
    bot.set_my_commands(commands)

# --- 2. ANALİZ MOTORU ---
def analiz_motoru(hisse, donem="1d"):
    try:
        ticker = hisse.upper().strip()
        f_t = ticker + ".IS" if not ticker.endswith(".IS") else ticker
        p = "6mo" if donem == "1d" else "2y" if donem == "1wk" else "5y"
        
        df = yf.download(f_t, period=p, interval=donem, progress=False, threads=False)
        if df is None or df.empty or len(df) < 15: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        df["RSI"] = ta.rsi(df["Close"], length=14)
        bb = ta.bbands(df["Close"], length=20)
        last = df.iloc[-1]
        return {"ticker": ticker, "fiyat": float(last["Close"]), "rsi": float(last["RSI"]), "hedef": float(bb.iloc[-1, 2]), "df": df}
    except: return None

def ai_yorumla(hisse_verileri):
    try:
        prompt = f"""Bir borsa uzmanı gibi davran. Aşağıdaki 5 hisse senedi verisine bakarak Emir Bey için en potansiyelli olanı seç ve nedenini 3 cümlede açıkla. Veriler: {hisse_verileri}"""
        response = ai_model.generate_content(prompt)
        return response.text
    except: return "⚠️ Yapay zeka yorumu şu an alınamadı."

# --- 3. RAPORLAMA ---
def rapor_gonder(liste, vade_kod, vade_adi):
    bot.send_message(MY_ID, f"🔍 {vade_adi} tarama başladı...")
    havuz = []
    for h in liste:
        res = analiz_motoru(h, vade_kod)
        if res and 40 < res["rsi"] < 70: havuz.append(res)
    
    en_iyi_5 = sorted(havuz, key=lambda x: ((x['hedef'] - x['fiyat']) / x['fiyat']), reverse=True)[:5]
    
    ai_data = []
    for t in en_iyi_5:
        pot = round(((t["hedef"] - t["fiyat"]) / t["fiyat"]) * 100, 1)
        ai_data.append(f"{t['ticker']} (Fiyat:{t['fiyat']}, RSI:{round(t['rsi'],2)}, Pot:%{pot})")
        
        mesaj = f"💎 *{t['ticker']}*\nFiyat: `{round(t['fiyat'], 2)}` | Potansiyel: `%{pot}`"
        plt.figure(figsize=(4, 2)); plt.plot(t["df"]["Close"].tail(20).values); plt.axis('off')
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(MY_ID, buf, caption=mesaj, parse_mode="Markdown"); plt.close()

    if ai_data:
        bot.send_message(MY_ID, "🤖 *Gemini Değerlendirmesi:*", parse_mode="Markdown")
        bot.send_message(MY_ID, ai_yorumla(ai_data))

# --- 4. KOMUT YÖNETİMİ ---
@bot.message_handler(commands=['start'])
def start(m):
    bot.send_message(m.chat.id, "📈 Terminal Aktif. Mavi menü butonundan tarama seçebilirsiniz.")

@bot.message_handler(commands=['gunluk'])
def cmd_gunluk(m): rapor_gonder(KATILIM_LISTESI, "1d", "GÜNLÜK")

@bot.message_handler(commands=['ikihaftalik'])
def cmd_haftalik(m): rapor_gonder(KATILIM_LISTESI, "1wk", "2 HAFTALIK")

@bot.message_handler(commands=['aylik'])
def cmd_aylik(m): rapor_gonder(KATILIM_LISTESI, "1mo", "AYLIK")

@bot.message_handler(commands=['fonlar'])
def cmd_fon(m): rapor_gonder(FON_LISTESI, "1d", "ALTIN/FON")

if __name__ == "__main__":
    set_commands()
    requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True")
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080)), daemon=True).start()
    bot.polling(none_stop=True)
