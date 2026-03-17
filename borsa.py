import os
import telebot
import yfinance as yf
import ta
import pandas as pd
import numpy as np
from sklearn.ensemble import RandomForestClassifier
import google.generativeai as genai
import time
import threading
from flask import Flask
import matplotlib
matplotlib.use("Agg") 
import matplotlib.pyplot as plt
import io
import warnings

warnings.filterwarnings("ignore")

# --- 1. AYARLAR ---
app = Flask(__name__)
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
bot = telebot.TeleBot(TOKEN)
CSV_FILE = "hisse_endeks_katilim_ds.csv"

genai.configure(api_key=GEMINI_KEY)
model_gemini = genai.GenerativeModel('gemini-1.5-flash')

@app.route('/')
def home(): return "Sistem Aktif!", 200

# --- 2. ANALİZ MOTORU ---
def analiz_et(ticker, vade):
    try:
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if df.empty or len(df) < 60: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

        df["RSI"] = ta.momentum.RSIIndicator(df["Close"]).rsi()
        df["EMA9"] = ta.trend.EMAIndicator(df["Close"], window=9).ema_indicator()
        df["EMA21"] = ta.trend.EMAIndicator(df["Close"], window=21).ema_indicator()
        df["Vol_Avg"] = df["Volume"].rolling(window=10).mean()

        last = df.iloc[-1]
        fiyat = round(last["Close"], 2)
        
        # AI Tahmin
        data = df.copy().dropna()
        features = ['RSI', 'EMA9', 'EMA21', 'Volume']
        X = data[features].tail(150)
        y = (data['Close'].shift(-1) > data['Close']).astype(int).tail(150)
        clf = RandomForestClassifier(n_estimators=100, random_state=42)
        clf.fit(X, y)
        ai_skor = round(clf.predict_proba(data[features].tail(1))[0][1] * 100, 1)

        # Filtreleme (Nokta Atışı)
        hacim_onayi = last["Volume"] > (last["Vol_Avg"] * 1.1)
        uygun = False
        
        if "günlük" in vade:
            if ai_skor >= 75 and hacim_onayi: uygun = True
        elif "3 hafta" in vade:
            if ai_skor >= 70 and fiyat > last["EMA21"]: uygun = True
        elif "2 ay" in vade:
            if ai_skor >= 65 and last["RSI"] < 55: uygun = True

        if not uygun: return None

        return {"ticker": ticker, "fiyat": fiyat, "ai": ai_skor, "df": df}
    except: return None

# --- 3. MENÜ VE KOMUTLAR ---
@bot.message_handler(commands=['start'])
def start(message):
    markup = telebot.types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    # Tam istediğin buton isimleri:
    markup.add(
        "⚡ Katılım Fırsat (Günlük AL-SAT)", 
        "⏳ Katılım Fırsat (3 Haftalık Vade)", 
        "📈 Katılım Fırsat (2 Aylık Vade)"
    )
    bot.send_message(message.chat.id, "🤖 **Gemini & AI Analiz Sistemi**\nLütfen bir seçenek belirleyin:", reply_markup=markup)

@bot.message_handler(func=lambda m: "katılım fırsat" in m.text.lower())
def handle_firsat(message):
    metin = message.text.lower()
    vade = "günlük" if "günlük" in metin else "3 hafta" if "3 hafta" in metin else "2 ay"
    
    bot.send_message(message.chat.id, f"🔍 {vade.upper()} vade için Excel listesi taranıyor...")
    
    try:
        df_csv = pd.read_csv(CSV_FILE, sep=';', skiprows=2, header=None)
        hisseler = [h.split('.')[0].strip().upper() + ".IS" for h in df_csv[0].dropna()]
        
        sayac = 0
        for h in hisseler[:100]:
            res = analiz_et(h, vade)
            if res:
                # Grafik ve Mesaj Gönderimi
                plt.figure(figsize=(6, 3))
                plt.plot(res["df"]["Close"].tail(30).values, color='green')
                plt.title(f"{res['ticker']} Trend")
                buf = io.BytesIO(); plt.savefig(buf, format='png'); buf.seek(0)
                
                msg = f"🎯 *{res['ticker']}* | %{res['ai']} Güven\n💰 Fiyat: {res['fiyat']}\n📅 Vade: {vade.upper()}"
                bot.send_photo(message.chat.id, buf, caption=msg, parse_mode="Markdown")
                plt.close()
                sayac += 1
                if sayac >= 5: break
                
        if sayac == 0: bot.send_message(message.chat.id, "⚠️ Şu an uygun fırsat bulunamadı.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Liste hatası: {e}")

# --- 4. ÇAKIŞMA ÇÖZÜCÜ BAŞLATICI ---
if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080), daemon=True).start()
    bot.remove_webhook()
    time.sleep(1)
    print("🚀 Bot başlatıldı...")
    bot.infinity_polling(skip_pending=True)
