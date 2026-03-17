import os
import telebot
import yfinance as yf
import ta
import io
import time
import json
import schedule
import threading
import requests
import pdfplumber
import warnings
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from datetime import datetime
from flask import Flask

warnings.filterwarnings("ignore")

# --- 1. AYARLAR VE SERVER ---
app = Flask(__name__)
@app.route('/')
def home(): return "Borsa Botu Aktif (Railway)", 200

def run_web_server():
    # Railway'in atadığı portu dinamik alır
    port = int(os.environ.get("PORT", 8080))
    app.run(host='0.0.0.0', port=port, debug=False, use_reloader=False)

# Ortam Değişkenleri
TOKEN = os.environ.get("TELEGRAM_TOKEN")
MY_CHAT_ID = os.environ.get("MY_CHAT_ID")
bot = telebot.TeleBot(TOKEN)
DATA_FILE = "borsa_verileri.json"

# --- 2. LİSTE YÖNETİMİ (PDF TABANLI) ---
def listeleri_yukle():
    if os.path.exists(DATA_FILE):
        try:
            with open(DATA_FILE, "r") as f: return json.load(f)
        except: pass
    return {"last_update": "", "lists": {"katilim": [], "bist30": []}}

def katilim_listesini_guncelle():
    """BIST PDF'inden güncel listeyi çeker, çıkanları siler, girenleri ekler."""
    print("📄 BIST Katılım Listesi PDF'den kontrol ediliyor...")
    try:
        # Borsa İstanbul Resmi PDF Linki
        pdf_url = "https://www.borsaistanbul.com/files/bist_katilim_endeksleri_pay_listesi.pdf"
        headers = {'User-Agent': 'Mozilla/5.0'}
        response = requests.get(pdf_url, headers=headers, timeout=20)
        
        if response.status_code != 200: return False

        with pdfplumber.open(io.BytesIO(response.content)) as pdf:
            cekilen = []
            for page in pdf.pages:
                text = page.extract_text()
                if text:
                    for line in text.split('\n'):
                        for word in line.split():
                            # Hisse kodlarını (3-6 karakter, Büyük harf) ayıkla
                            if 3 <= len(word) <= 6 and word.isupper() and word.isalpha():
                                cekilen.append(word + ".IS")
        
        yeni_liste = sorted(list(set(cekilen)))
        if len(yeni_liste) > 50:
            data = listeleri_yukle()
            # Değişiklik varsa listeyi güncelle
            if data["lists"]["katilim"] != yeni_liste:
                data["lists"]["katilim"] = yeni_liste
                data["last_update"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                with open(DATA_FILE, "w") as f: json.dump(data, f)
                print(f"✅ Liste güncellendi: {len(yeni_liste)} hisse.")
                return True
    except Exception as e:
        print(f"❌ Güncelleme hatası: {e}")
    return False

# --- 3. ANALİZ VE SKORLAMA ---
def hisse_skorla(ticker, donem="manuel"):
    try:
        ticker = str(ticker).strip().upper()
        if not ticker.endswith(".IS"): ticker += ".IS"
        
        # threads=False Railway işlemci kararlılığı için
        df = yf.download(ticker, period="6mo", interval="1d", progress=False, auto_adjust=True, threads=False)
        if df is None or df.empty or len(df) < 20: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        df["RSI"] = ta.momentum.RSIIndicator(df["Close"]).rsi()
        df["EMA9"] = ta.trend.EMAIndicator(df["Close"], window=9).ema_indicator()
        df["EMA21"] = ta.trend.EMAIndicator(df["Close"], window=21).ema_indicator()
        df["BB_U"] = ta.volatility.BollingerBands(df["Close"]).bollinger_hband()

        last = df.iloc[-1]
        fiyat, rsi = float(last["Close"]), float(last["RSI"])
        
        # Strateji: Fiyat EMA9 üstünde ve RSI 40-65 arasındaysa güçlü
        skor = (1 if fiyat > float(last["EMA9"]) else 0) + (2 if 40 < rsi < 65 else 0)
        karar = "🔥 GÜÇLÜ" if skor >= 3 else "📈 OLUMLU" if skor >= 1 else "⚖️ NÖTR"

        return {"ticker": ticker, "fiyat": fiyat, "rsi": rsi, "upper_bb": float(last["BB_U"]), 
                "ema21": float(last["EMA21"]), "ema9": float(last["EMA9"]), "karar": karar, "df": df}
    except: return None

def sonuc_gonder(chat_id, t):
    try:
        p_kar = round(((t["upper_bb"] - t["fiyat"]) / t["fiyat"]) * 100, 2)
        mesaj = (f"🏆 *{t['ticker']}*\n💰 *Fiyat:* {round(t['fiyat'], 2)} | *RSI:* {round(t['rsi'], 1)}\n"
                 f"🏁 *Karar:* `{t['karar']}`\n🎯 *Hedef:* `{round(t['upper_bb'], 2)}` (%{p_kar})\n🟢 *Destek (EMA9):* `{round(t['ema9'], 2)}` ")
        
        plt.figure(figsize=(7, 4))
        plt.plot(t["df"]["Close"].tail(30).values, color="blue", linewidth=2)
        plt.title(f"{t['ticker']} - Analiz")
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(chat_id, buf, caption=mesaj, parse_mode="Markdown")
        plt.close("all")
    except: pass

# --- 4. ZAMANLAYICI VE RAPOR ---
def seans_raporu(donem):
    data = listeleri_yukle()
    hisseler = data["lists"].get("katilim", [])
    bot.send_message(MY_CHAT_ID, f"📢 **TARAMA BAŞLADI ({donem.upper()})**\nİncelenen: {len(hisseler)} Hisse")
    
    bulunan = 0
    for h in hisseler:
        res = hisse_skorla(h, donem)
        if res and res["karar"] in ["🔥 GÜÇLÜ", "📈 OLUMLU"]:
            sonuc_gonder(MY_CHAT_ID, res)
            bulunan += 1
            time.sleep(2) # Ban koruması
            
    bot.send_message(MY_CHAT_ID, f"✅ Tarama bitti. {bulunan} potansiyel fırsat bulundu.")

def zamanlayici():
    katilim_listesini_guncelle() # Bot açılışında PDF kontrolü
    
    # Her sabah 08:00'de PDF'i kontrol eder
    schedule.every().day.at("08:00").do(katilim_listesini_guncelle)
    
    is_gunleri = [schedule.every().monday, schedule.every().tuesday, schedule.every().wednesday, schedule.every().thursday, schedule.every().friday]
    for gun in is_gunleri:
        gun.at("09:55").do(seans_raporu, "sabah")
        gun.at("18:05").do(seans_raporu, "aksam")
        
    while True:
        schedule.run_pending()
        time.sleep(30)

# --- 5. KOMUTLAR ---
@bot.message_handler(commands=['start', 'guncelle'])
def manual_update(message):
    bot.send_message(message.chat.id, "🔄 Liste kontrol ediliyor...")
    if katilim_listesini_guncelle():
        bot.send_message(message.chat.id, "✅ Liste güncellendi!")
    else:
        bot.send_message(message.chat.id, "ℹ️ Liste zaten güncel veya erişim sorunu.")

@bot.message_handler(func=lambda message: True)
def handle_text(message):
    metin = message.text.strip().lower()
    if metin == "katilim":
        seans_raporu("manuel")
    else:
        res = hisse_skorla(metin)
        if res: sonuc_gonder(message.chat.id, res)
        else: bot.send_message(message.chat.id, "❌ Veri alınamadı. Hisse kodunu kontrol edin (Örn: thyao).")

if __name__ == "__main__":
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=zamanlayici, daemon=True).start()
    print("🚀 Bot Başlatıldı!")
    bot.infinity_polling(timeout=20)
