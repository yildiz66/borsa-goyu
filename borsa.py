import os, telebot, yfinance as yf, pandas_ta as ta, io, threading, warnings, time, requests
import pandas as pd
import matplotlib.pyplot as plt
from google import genai
from flask import Flask

# Uyarıları kapat
warnings.filterwarnings("ignore")

# Flask (Railway Health Check için)
app = Flask(__name__)
@app.route('/')
def home(): return "Borsabot Aktif", 200

# Değişkenleri Çek
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
MY_ID = os.environ.get("MY_CHAT_ID")

# Bot ve Gemini Başlat
bot = telebot.TeleBot(TOKEN)
client = genai.Client(api_key=GEMINI_KEY)

# 215 Hisselik Liste (Kısaltılmış örnek, siz tamamını kullanabilirsiniz)
KATILIM_TUMU = ["AKSA", "ALTNY", "ASELS", "BIMAS", "BSOKE", "CANTE", "CIMSA", "CWENE", "DOAS", "EGEEN", "ENJSA", "EREGL", "FROTO", "GENTS", "GESAN", "GUBRF", "HEKTS", "JANTS", "KCAER", "KONTR", "KONYA", "KORDS", "MAVI", "MGROS", "MIATK", "OYAKC", "PGSUS", "REEDR", "SASA", "SISE", "SMRTG", "TABGD", "THYAO", "TKFEN", "TMSN", "TOASO", "TUPRS", "ULKER", "VESBE", "YEOTK", "LOGO", "LKMNH", "NTGAZ", "PAGYO", "PLTUR", "ZEDUR"] 

def analiz_motoru(hisse):
    try:
        f_t = f"{hisse.upper()}.IS"
        df = yf.download(f_t, period="6mo", interval="1d", progress=False)
        if df is None or df.empty: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        df["RSI"] = ta.rsi(df["Close"], length=14)
        bb = ta.bbands(df["Close"], length=20)
        
        return {
            "ticker": hisse,
            "fiyat": float(df.iloc[-1]["Close"]),
            "rsi": float(df.iloc[-1]["RSI"]),
            "ust": float(bb.iloc[-1, 2]),
            "df": df
        }
    except: return None

@bot.message_handler(commands=['start'])
def send_welcome(message):
    bot.reply_to(message, "Merhaba Emir Bey! Terminal hazır. /gunluk komutu ile taramayı başlatabilirsiniz.")

@bot.message_handler(commands=['gunluk'])
def daily_scan(message):
    bot.send_message(MY_ID, "🔍 Tarama başladı, lütfen bekleyin...")
    havuz = []
    for h in KATILIM_TUMU:
        res = analiz_motoru(h)
        if res and 30 < res["rsi"] < 70:
            havuz.append(res)
        time.sleep(0.1)
    
    # En iyi 5 potansiyeli seç
    en_iyi = sorted(havuz, key=lambda x: (x['ust'] - x['fiyat'])/x['fiyat'], reverse=True)[:5]
    
    for t in en_iyi:
        pot = round(((t["ust"] - t["fiyat"]) / t["fiyat"]) * 100, 1)
        bot.send_message(MY_ID, f"💎 *{t['ticker']}*\nFiyat: {round(t['fiyat'],2)}\nRSI: {round(t['rsi'],1)}\nPotansiyel: %{pot}", parse_mode="Markdown")

# Ana Döngü
if __name__ == "__main__":
    # Bağlantıyı temizle
    requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True")
    
    # Flask'ı ayrı kanalda başlat
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080)), daemon=True).start()
    
    print("Bot başlatılıyor...")
    bot.infinity_polling()
