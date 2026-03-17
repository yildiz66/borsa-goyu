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
matplotlib.use("Agg") # Sunucuda grafik çizimi için gerekli
import matplotlib.pyplot as plt
import io
import warnings

warnings.filterwarnings("ignore")

# --- 1. AYARLAR ---
app = Flask(__name__)
TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
bot = telebot.TeleBot(TOKEN)
# Excel/CSV dosya adın (Dosyayı Railway'e bu isimle yükle)
CSV_FILE = "hisse_endeks_katilim_ds.csv"

# Gemini Kurulumu
genai.configure(api_key=GEMINI_KEY)
model_gemini = genai.GenerativeModel('gemini-1.5-flash')

@app.route('/')
def home(): return "Nokta Atisi Sistemi Aktif!", 200

# --- 2. AI VE TEKNİK ANALİZ MOTORU ---
def analiz_et(ticker, vade="günlük"):
    try:
        # 1 yıllık veri (Nokta atışı hassasiyeti için)
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
        
        # --- AI Tahmin (Random Forest) ---
        data = df.copy().dropna()
        features = ['RSI', 'EMA9', 'EMA21', 'Volume']
        X = data[features].tail(180)
        y = (data['Close'].shift(-1) > data['Close']).astype(int).tail(180)
        clf = RandomForestClassifier(n_estimators=150, random_state=42)
        clf.fit(X, y)
        ai_skor = round(clf.predict_proba(data[features].tail(1))[0][1] * 100, 1)

        # --- NOKTA ATIŞI FİLTRELERİ (Hacim + Trend) ---
        hacim_onayi = last["Volume"] > (last["Vol_Avg"] * 1.15)
        
        uygun = False
        if "günlük" in vade:
            if ai_skor >= 75 and hacim_onayi and last["RSI"] < 68: uygun = True
        elif "3 haftalık" in vade:
            if ai_skor >= 70 and fiyat > last["EMA21"]: uygun = True
        elif "2 aylık" in vade:
            if ai_skor >= 65 and last["RSI"] < 55 and fiyat > (last["EMA50"] * 0.97): uygun = True

        if not uygun: return None

        # --- Gemini Stratejik Yorum ---
        prompt = (f"{ticker} için teknik veriler: Fiyat {fiyat}, RSI {round(last['RSI'],1)}, "
                  f"AI Güven %{ai_skor}. Bu hisseyi {vade} vade için 1 kısa cümlede analiz et.")
        try:
            gemini_cevap = model_gemini.generate_content(prompt).text
        except:
            gemini_cevap = "Hacim ve AI onayı mevcut, teknik görünüm pozitif."

        return {
            "ticker": ticker, "fiyat": fiyat, "ai": ai_skor, 
            "rsi": round(last["RSI"], 1), "yorum": gemini_cevap, "df": df
        }
    except: return None

# --- 3. GÖRSEL VE MESAJ GÖNDERİMİ ---
def sonuc_goster(chat_id, r, vade):
    plt.figure(figsize=(7, 4))
    plt.plot(r["df"]["Close"].tail(30).values, color='#16a085', linewidth=2.5)
    plt.grid(True, linestyle='--', alpha=0.5)
    plt.title(f"{r['ticker']} - 30 Gunluk Trend")
    
    buf = io.BytesIO()
    plt.savefig(buf, format='png')
    buf.seek(0)
    
    mesaj = (f"🎯 *NOKTA ATIŞI: {r['ticker']}*\n"
             f"🏁 *Vade Stratejisi:* {vade.upper()}\n"
             f"🤖 *AI Skor:* %{r['ai']}\n"
             f"💰 *Fiyat:* {r['fiyat']} | *RSI:* {r['rsi']}\n"
             f"---------------------------\n"
             f"💬 *GEMİNİ:* {r['yorum']}\n"
             f"---------------------------")
    
    bot.send_photo(chat_id, buf, caption=mesaj, parse_mode="Markdown")
    plt.close()

# --- 4. BOT KOMUTLARI VE DÖNGÜ ---
@bot.message_handler(commands=['start'])
def start(message):
    markup = telebot.types.ReplyKeyboardMarkup(row_width=1, resize_keyboard=True)
    markup.add("⚡ Katılım Fırsat Günlük AL-SAT", 
               "⏳ Katılım Fırsat (3 Haftalık Vade)", 
               "📈 Katılım Fırsat (2 Aylık Vade)")
    bot.send_message(message.chat.id, "💰 **Nokta Atışı Analiz Sistemi**\nLütfen stratejinize uygun vadeyi seçin:", reply_markup=markup)

@bot.message_handler(func=lambda m: "katılım fırsat" in m.text.lower())
def handle_text(message):
    vade = "günlük" if "günlük" in message.text.lower() else "3 haftalık" if "3 haftalık" in message.text.lower() else "2 aylık"
    bot.send_message(message.chat.id, f"🔍 Excel listesindeki hisseler {vade.upper()} vade için taranıyor...")
    
    try:
        # Excel (CSV) dosyasını oku
        df_csv = pd.read_csv(CSV_FILE, sep=';', skiprows=2, header=None)
        hisseler = [h.split('.')[0].strip().upper() + ".IS" for h in df_csv[0].dropna()]
        
        sayac = 0
        for h in hisseler[:120]: # Performans için ilk 120 hisse
            res = analiz_et(h, vade)
            if res:
                sonuc_goster(message.chat.id, res, vade)
                sayac += 1
                if sayac >= 5: break # En iyi 5 kağıtta dur
                
        if sayac == 0:
            bot.send_message(message.chat.id, "⚠️ Kriterlere uygun (Hacim+Trend+AI) bir fırsat şu an bulunamadı.")
    except Exception as e:
        bot.send_message(message.chat.id, f"❌ Excel okuma hatası: {e}\nDosyanın {CSV_FILE} adıyla yüklendiğinden emin olun.")

if __name__ == "__main__":
    # Flask sunucusunu ayrı bir kanalda başlat
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080)).start()
    print("🚀 Bot başlatıldı...")
    bot.infinity_polling()
