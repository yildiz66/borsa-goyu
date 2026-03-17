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
import schedule
import threading
import requests
from bs4 import BeautifulSoup
from datetime import datetime
from flask import Flask
import warnings

warnings.filterwarnings("ignore")

# --- 1. FLASK SERVER ---
app = Flask(__name__)

@app.route('/')
def home(): 
    return "Bot Calisiyor!", 200

def run_web_server():
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
MY_CHAT_ID = os.environ.get("MY_CHAT_ID")
bot = telebot.TeleBot(TOKEN)
DATA_FILE = "borsa_verileri.json"

# --- 2. LİSTE YÖNETİMİ ---
GRUPLAR = {"katilim": [], "bist30": [], "bist50": [], "bist100": [], "altin": []}

def listeleri_yonet():
    if not os.path.exists(DATA_FILE):
        data = {"last_update": time.time(), "lists": GRUPLAR}
        with open(DATA_FILE, "w") as f: json.dump(data, f)
        return GRUPLAR
    with open(DATA_FILE, "r") as f: return json.load(f)["lists"]

# --- 3. KATILIM (CSV'DEN OKUMA) ---
def katilim_csv_guncelle():
    csv_dosya = "hisse_endeks_katilim_ds.csv"
    print(f"📂 {csv_dosya} okunuyor...")
    try:
        if not os.path.exists(csv_dosya):
            print(f"⚠️ {csv_dosya} bulunamadı!")
            return False
        
        # CSV ayracını otomatik tespit etmeye çalış
        try:
            df = pd.read_csv(csv_dosya, sep=';', encoding='utf-8')
        except:
            df = pd.read_csv(csv_dosya, sep=',', encoding='utf-8')
            
        kolon = [c for c in df.columns if any(k in str(c).upper() for k in ["KOD", "SEMBOL", "TICKER"])][0]
        hisseler = [str(h).strip().upper() for h in df[kolon].dropna().tolist()]
        hisseler = [h + ".IS" if not h.endswith(".IS") else h for h in hisseler]
        
        aktif = listeleri_yonet()
        aktif["katilim"] = hisseler
        with open(DATA_FILE, "w") as f: json.dump({"last_update": time.time(), "lists": aktif}, f)
        print(f"✅ CSV'den {len(hisseler)} katılım hissesi yüklendi.")
        return True
    except Exception as e:
        print(f"❌ CSV Hatası: {e}")
        return False

# --- 4. DİĞER ENDEKSLER (İŞ YATIRIM) ---
def is_yatirim_guncelle(endeks_adi):
    mapping = {"bist30": "XU030", "bist50": "XU050", "bist100": "XU100"}
    kod = mapping.get(endeks_adi, "XU100")
    url = f"https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/Endeks-Bilesenleri.aspx?endeks={kod}"
    try:
        headers = {"User-Agent": "Mozilla/5.0"}
        r = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        table = soup.find('table', {'id': 'hisse_takip_table'}) or soup.find('table', class_='table')
        hisseler = [row.find_all('td')[0].text.strip() + ".IS" for row in table.find_all('tr')[1:] if row.find_all('td')]
        
        if len(hisseler) > 5:
            aktif = listeleri_yonet()
            aktif[endeks_adi] = hisseler
            with open(DATA_FILE, "w") as f: json.dump({"last_update": time.time(), "lists": aktif}, f)
            print(f"✅ İş Yatırım: {endeks_adi.upper()} güncellendi.")
            return True
    except Exception as e:
        print(f"❌ İş Yatırım Hatası ({endeks_adi}): {e}")
    return False

# --- 5. ANALİZ VE MESAJ MANTIĞI ---
def hisse_skorla(ticker, donem="manuel"):
    try:
        ticker = str(ticker).strip().upper().replace("/", "")
        if not any(x in ticker for x in [".IS", "=", "-"]):
            if ticker not in ["GLDTR", "ALTIN1GOLD"]: ticker += ".IS"
        
        df = yf.download(ticker, period="6mo", interval="1d", progress=False)
        if df.empty or len(df) < 20: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        df["RSI"] = ta.momentum.RSIIndicator(df["Close"]).rsi()
        df["EMA9"] = ta.trend.EMAIndicator(df["Close"], window=9).ema_indicator()
        df["EMA21"] = ta.trend.EMAIndicator(df["Close"], window=21).ema_indicator()
        df["BB_U"] = ta.volatility.BollingerBands(df["Close"]).bollinger_hband()
        
        last = df.iloc[-1]
        fiyat, rsi = float(last["Close"]), float(last["RSI"])
        skor = (1 if fiyat > float(last["EMA9"]) else 0) + (2 if 40 < rsi < 65 else 0)
        karar = "🔥 GÜÇLÜ" if skor >= 3 else "📈 OLUMLU" if skor >= 1 else "⚖️ NÖTR"
        
        return {
            "ticker": ticker, "fiyat": fiyat, "rsi": rsi, "upper_bb": float(last["BB_U"]),
            "ema21": float(last["EMA21"]), "ema9": float(last["EMA9"]),
            "karar": karar, "df": df
        }
    except: return None

def sonuc_gonder(chat_id, t):
    try:
        mesaj = (f"🏆 *{t['ticker']}*\n💰 Fiyat: {t['fiyat']:.2f} | RSI: {t['rsi']:.1f}\n🏁 Karar: `{t['karar']}`\n"
                 f"---------------------------\n🟢 Destek: {t['ema9']:.2f}\n🎯 Hedef: {t['upper_bb']:.2f}\n🛑 Stop: {t['ema21']:.2f}")
        plt.figure(figsize=(7, 4)); plt.plot(t["df"]["Close"].tail(30).values, color="blue", linewidth=2)
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(chat_id, buf, caption=mesaj, parse_mode="Markdown")
        plt.close("all")
        time.sleep(1)
    except: pass

# --- 6. ZAMANLAYICI ---
def tum_listeleri_yenile():
    katilim_csv_guncelle()
    is_yatirim_guncelle("bist30")
    is_yatirim_guncelle("bist100")

def zamanlayici():
    schedule.every().day.at("08:30").do(tum_listeleri_yenile)
    while True:
        schedule.run_pending()
        time.sleep(30)

# --- 7. MESAJ YÖNETİMİ ---
@bot.message_handler(func=lambda message: True)
def handle_text(message):
    metin = message.text.strip().replace("/", "").lower()
    aktif_listeler = listeleri_yonet()
    
    # "tum_" komutları için tetikleyici
    if "tum_" in metin:
        target = metin.replace("tum_", "")
        if target == "katilim": katilim_csv_guncelle()
        elif target in ["bist30", "bist100"]: is_yatirim_guncelle(target)
        bot.send_message(message.chat.id, "✅ Liste güncellendi.")
    
    elif metin in aktif_listeler:
        bot.send_message(message.chat.id, f"🔍 {metin.upper()} taranıyor...")
        for h in aktif_listeler[metin]:
            res = hisse_skorla(h)
            if res and res["karar"] in ["🔥 GÜÇLÜ", "📈 OLUMLU"]: sonuc_gonder(message.chat.id, res)
    else:
        res = hisse_skorla(metin)
        if res: sonuc_gonder(message.chat.id, res)
        else: bot.reply_to(message, "❌ Veri alınamadı.")

# --- 8. BAŞLATICI ---
if __name__ == "__main__":
    bot.remove_webhook()
    tum_listeleri_yenile()
    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=zamanlayici, daemon=True).start()
    print("🚀 Sistem Hazır!")
    bot.infinity_polling()
