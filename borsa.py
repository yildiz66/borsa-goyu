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

# --- AYARLAR ---
app = Flask(__name__)
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
bot = telebot.TeleBot(TOKEN)
CSV_FILE = "hisse_endeks_katilim_ds.csv"

genai.configure(api_key=GEMINI_KEY)
model_gemini = genai.GenerativeModel('gemini-1.5-flash')

# Analiz Motoru
def analiz_et(ticker):
    try:
        df = yf.download(ticker, period="6mo", interval="1d", progress=False)
        if df.empty or len(df) < 30: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

        df["RSI"] = ta.momentum.RSIIndicator(df["Close"]).rsi()
        df["EMA9"] = ta.trend.EMAIndicator(df["Close"], window=9).ema_indicator()
        
        # AI Tahmini
        data = df.copy()
        data['Target'] = (data['Close'].shift(-1) > data['Close']).astype(int)
        features = ['RSI', 'EMA9', 'Volume']
        data = data.dropna()
        clf = RandomForestClassifier(n_estimators=50)
        clf.fit(data[features].tail(100), data['Target'].tail(100))
        ai_skor = round(clf.predict_proba(data[features].tail(1))[0][1] * 100, 1)

        last = df.iloc[-1]
        return {"ticker": ticker, "fiyat": round(last["Close"], 2), "ai": ai_skor, "rsi": round(last["RSI"], 1)}
    except: return None

@bot.message_handler(func=lambda m: True)
def handle_text(message):
    metin = message.text.strip().lower()
    hisseler = []
    filtre_uygula = "fırsat" in metin

    # Liste Seçimi
    if "altın" in metin or "altin" in metin or "fon" in metin:
        hisseler = ["ALTINS.IS", "GMSTR.IS", "ZGOLD.IS", "GLDGR.IS", "MKP.IS", "KPT.IS", "GGK.IS", "KGC.IS"]
    elif "bist 30" in metin or "bist30" in metin:
        hisseler = ["AKBNK.IS", "ARCLK.IS", "ASELS.IS", "BIMAS.IS", "EREGL.IS", "FROTO.IS", "GARAN.IS", "KCHOL.IS", "THYAO.IS", "TUPRS.IS"]
    elif "katılım" in metin:
        df_csv = pd.read_csv(CSV_FILE, sep=';', skiprows=2, header=None)
        hisseler = [h.split('.')[0].strip().upper() + ".IS" for h in df_csv[0].dropna()]
    else:
        res = analiz_et(metin.upper())
        if res: bot.send_message(message.chat.id, f"📊 *{res['ticker']}*\nAI Skor: %{res['ai']}\nFiyat: {res['fiyat']}\nRSI: {res['rsi']}", parse_mode="Markdown")
        return

    # Analiz ve Gönderim
    bot.send_message(message.chat.id, f"🔍 {len(hisseler)} enstrüman taranıyor...")
    sonuclar = []
    limit = 100 if "katılım" in metin else len(hisseler)

    for h in hisseler[:limit]:
        res = analiz_et(h)
        if res:
            if filtre_uygula:
                if res['ai'] >= 70: sonuclar.append(res)
            else:
                sonuclar.append(res)
    
    if filtre_uygula: sonuclar = sorted(sonuclar, key=lambda x: x['ai'], reverse=True)[:5]
    
    msg_chunk = "📋 *ANALİZ SONUÇLARI*\n\n"
    for i, r in enumerate(sonuclar):
        msg_chunk += f"🔸 *{r['ticker']}* | AI: %{r['ai']} | F: {r['fiyat']}\n"
        if (i + 1) % 10 == 0:
            bot.send_message(message.chat.id, msg_chunk, parse_mode="Markdown")
            msg_chunk = ""
            time.sleep(0.5)
    if msg_chunk: bot.send_message(message.chat.id, msg_chunk, parse_mode="Markdown")

if __name__ == "__main__":
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    bot.infinity_polling()
