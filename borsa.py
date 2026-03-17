import os
import telebot
import yfinance as yf
import ta
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import io
import time
import pandas as pd
import json
import threading
from sklearn.ensemble import RandomForestClassifier
import google.generativeai as genai
from datetime import datetime
from flask import Flask
import warnings

warnings.filterwarnings("ignore")

# --- 1. AYARLAR VE FLASK ---
app = Flask(__name__)

@app.route('/')
def home(): return "Bot Calisiyor!", 200

def run_web_server():
    # Railway ve Replit için port yapılandırması
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
bot = telebot.TeleBot(TOKEN)
CSV_FILE = "hisse_endeks_katilim_ds.csv"

# Gemini Yapılandırması
genai.configure(api_key=GEMINI_KEY)
model_gemini = genai.GenerativeModel('gemini-1.5-flash')

# --- 2. ANALİZ VE SKORLAMA MOTORU ---
def analiz_et(ticker, vade="günlük"):
    try:
        # Nokta atışı için 1 yıllık veri çekimi
        df = yf.download(ticker, period="1y", interval="1d", progress=False)
        if df.empty or len(df) < 60: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

        # İndikatörler
        df["RSI"] = ta.momentum.RSIIndicator(df["Close"]).rsi()
        df["EMA9"] = ta.trend.EMAIndicator(df["Close"], window=9).ema_indicator()
        df["EMA21"] = ta.trend.EMAIndicator(df["Close"], window=21).ema_indicator()
        df["EMA50"] = ta.trend.EMAIndicator(df["Close"], window=50).ema_indicator()
        df["Vol_Avg"] = df["Volume"].rolling(window=10).mean()

        last = df.iloc[-1]
        prev = df.iloc[-2]
        fiyat = round(last["Close"], 2)
        
        # --- AI Tahmin Modeli ---
        data = df.copy().dropna()
        features = ['RSI', 'EMA9', 'EMA21', 'Volume']
        X = data[features].tail(180)
        y = (data['Close'].shift(-1) > data['Close']).astype(int).tail(180)
        clf = RandomForestClassifier(n_estimators=150, random_state=42)
        clf.fit(X, y)
        ai_skor = round(clf.predict_proba(data[features].tail(1))[0][1] * 100, 1)

        # --- NOKTA ATIŞI FİLTRELERİ ---
        hacim_onayi = last["Volume"] > (last["Vol_Avg"] * 1.15)
        
        uygun = False
        if "günlük" in vade:
            # Günlükte hacim ve yüksek AI skoru şart
            if ai_skor >= 75 and hacim_onayi and last["RSI"] < 68: uygun = True
        elif "3 hafta" in vade:
            # Orta vadede EMA21 üstü kalıcılık
            if ai_skor >= 70 and fiyat > last["EMA21"]: uygun = True
        elif "2 ay" in vade:
            # Uzun vadede ucuzluk ve RSI kontrolü
            if ai_skor >= 65 and last["RSI"] < 55 and fiyat > (last["EMA50"] * 0.97): uygun = True

        if not uygun: return None

        # Gemini Yorumu
        prompt = f"{ticker} için Fiyat {fiyat}, RSI {round(last['RSI'],1)}, AI %{ai_skor}. Bu {vade} vade için 1 cümlelik nokta atışı analiz yap."
        try:
            gemini_cevap = model_gemini.generate_content(prompt).text
        except:
            gemini_cevap = "Teknik göstergeler ve para girişi pozitif."

        return {
            "ticker": ticker, "fiyat": fiyat, "ai": ai_skor, 
            "rsi": round(last["RSI"], 1), "yorum": gemini_cevap, "df": df
        }
    except: return None

def sonuc_gonder(chat_id, r, vade):
    plt.figure(figsize=(7, 4))
    plt.plot(r["df"]["Close"].tail(30).values, color='#27ae60', linewidth=2.5)
    plt.grid(True, linestyle='--', alpha=0.4)
    plt.title(f"{r['ticker']} - 30 Gunluk Trend")
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    
    mesaj = (f"🎯 *NOKTA ATIŞI: {r['ticker']}*\n"
             f"🏁 *Vade:* {vade.upper()}\n"
             f"🤖 *AI Skor:* %{r['ai']}\n"
             f"💰 *Fiyat:* {r['fiyat']} | *RSI:* {r['rsi']}\n"
             f"---------------------------\n"
             f"💬 *GEMİNİ:* {r['yorum']}")
    
    bot.send_photo(chat_id, buf, caption=mesaj, parse_mode="Markdown")
    plt.close()

# --- 3. MENÜ VE MESAJ YÖNETİMİ ---
@bot.message_handler(commands=['start'])
def start(message):
    markup = telebot.types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    markup.add(
        "⚡ Katılım Fırsat (Günlük AL-SAT)", 
        "⏳ Katılım Fırsat (3 Haftalık Vade)", 
        "📈 Katılım Fırsat (2 Aylık Vade)"
    )
    bot.send_message(message.chat.id, "💰 **Nokta Atışı Analiz Sistemi**\nLütfen bir vade seçin:", reply_markup=markup)

@bot.message_handler(func=lambda m: "katılım fırsat" in m.text.lower())
def handle_firsat(message):
    metin = message.text.lower()
    vade = "günlük" if "günlük" in metin else "3 hafta" if "3 hafta" in metin else "2 ay"
    bot.send_message(message.chat.id, f"🔍 {vade.upper()} için Excel listesi taranıyor...")
    
    try:
        # Excel/CSV dosyasından hisseleri oku
        df_csv = pd.read_csv(CSV_FILE, sep=';', skiprows=2, header=None)
        hisseler = [h.split('.')[0].strip().upper() + ".IS" for h in df_csv[0].dropna()]
        
        sayac = 0
        for h in hisseler[:100]: # Hız için ilk 100 hisse
            res = analiz_et(h, vade)
            if res:
                sonuc_goster(message.chat.id, res, vade)
                sayac += 1
                if sayac >= 5: break
                
        if sayac == 0:
            bot.send_message(message.chat.id, "⚠️ Kriterlere uygun (Para Girişi+AI) fırsat bulunamadı.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Hata: {e}")

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    
    # Çakışma önleyici temizlik
    bot.remove_webhook()
    time.sleep(1)
    
    print("🚀 Sistem Hazır! Port 8080 aktif.")
    bot.infinity_polling(skip_pending=True)
