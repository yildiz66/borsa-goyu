import os, telebot, yfinance as yf, pandas_ta as ta, io, threading, warnings, time, requests
import pandas as pd
import matplotlib.pyplot as plt
import google.generativeai as genai
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

# KOZAL LİSTEDEN ÇIKARILDI
KATILIM_TUMU = [
    "AKSA", "ALTNY", "ASELS", "BIMAS", "BSOKE", "CANTE", "CIMSA", "CWENE", 
    "DOAS", "EGEEN", "ENJSA", "EREGL", "FROTO", "GENTS", "GESAN", "GUBRF", 
    "HEKTS", "JANTS", "KCAER", "KONTR", "KONYA", "KORDS", "MAVI", "MGROS", 
    "MIATK", "OYAKC", "PGSUS", "REEDR", "SASA", "SISE", "SMRTG", "TABGD", 
    "THYAO", "TKFEN", "TMSN", "TOASO", "TUPRS", "ULKER", "VESBE", "YEOTK"
]

FON_LISTESI = ["ALTINS1.IS", "GC=F", "GMSTR.IS", "SI=F", "USDTRY=X"]

def set_commands():
    try:
        bot.delete_my_commands()
        time.sleep(1)
        commands = [
            telebot.types.BotCommand("gunluk", "Günlük Tarama"),
            telebot.types.BotCommand("ikihaftalik", "2 Haftalık Tarama"),
            telebot.types.BotCommand("aylik", "Aylık Tarama"),
            telebot.types.BotCommand("fonlar", "Metal ve Döviz"),
            telebot.types.BotCommand("start", "Başlat")
        ]
        bot.set_my_commands(commands)
    except: pass

def analiz_motoru(hisse, donem="1d"):
    try:
        ticker = hisse.upper().strip()
        f_t = ticker if ("=" in ticker or ".IS" in ticker) else f"{ticker}.IS"
        
        # Yahoo Finance verisi
        df = yf.download(f_t, period="2y", interval=donem, progress=False, threads=False, timeout=7)
        
        if df is None or df.empty or len(df) < 15: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        df["RSI"] = ta.rsi(df["Close"], length=14)
        bb = ta.bbands(df["Close"], length=20)
        
        return {
            "ticker": ticker, 
            "fiyat": float(df.iloc[-1]["Close"]), 
            "rsi": float(df.iloc[-1]["RSI"]), 
            "ust": float(bb.iloc[-1, 2]), 
            "df": df
        }
    except: return None

def rapor_gonder(liste, vade, baslik):
    bot.send_message(MY_ID, f"🔍 {baslik} tarama başladı Emir Bey...")
    havuz = []
    for h in liste:
        res = analiz_motoru(h, vade)
        if res and 30 < res["rsi"] < 75: 
            havuz.append(res)
        time.sleep(0.1)

    en_iyi = sorted(havuz, key=lambda x: ((x['ust'] - x['fiyat']) / x['fiyat']), reverse=True)[:5]
    
    if not en_iyi:
        bot.send_message(MY_ID, "⚠️ Uygun hisse bulunamadı.")
        return

    ai_data = []
    for t in en_iyi:
        pot = round(((t["ust"] - t["fiyat"]) / t["fiyat"]) * 100, 1)
        ai_data.append(f"{t['ticker']}(%{pot})")
        
        plt.figure(figsize=(4, 2)); plt.plot(t["df"]["Close"].tail(20).values, color='green'); plt.axis('off')
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(MY_ID, buf, caption=f"💎 *{t['ticker']}*\nFiyat: {round(t['fiyat'], 2)} | RSI: {round(t['rsi'], 1)} | Pot: %{pot}")
        plt.close()

    try:
        prompt = f"Borsa uzmanı olarak bu hisseleri yorumla: {ai_data}"
        bot.send_message(MY_ID, f"🤖 *Gemini:* {ai_model.generate_content(prompt).text}")
    except: pass

@bot.message_handler(commands=['start'])
def start(m): bot.send_message(m.chat.id, "📈 Terminal Hazır. KOZAL çıkarıldı, tüm listeler güncel.")

@bot.message_handler(commands=['gunluk'])
def cmd_1(m): rapor_gonder(KATILIM_TUMU, "1d", "GÜNLÜK")

@bot.message_handler(commands=['ikihaftalik'])
def cmd_2(m): rapor_gonder(KATILIM_TUMU, "1wk", "2 HAFTALIK")

@bot.message_handler(commands=['aylik'])
def cmd_3(m): rapor_gonder(KATILIM_TUMU, "1mo", "AYLIK")

@bot.message_handler(commands=['fonlar'])
def cmd_4(m): rapor_gonder(FON_LISTESI, "1d", "METAL/DÖVİZ")

if __name__ == "__main__":
    # Conflict hatasını önlemek için webhook'u temizle
    requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True")
    time.sleep(1)
    set_commands()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080)), daemon=True).start()
    bot.infinity_polling(timeout=20)
