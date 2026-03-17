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
from Flask import Flask
import warnings

warnings.filterwarnings("ignore")

# --- 1. AYARLAR VE FLASK ---
app = Flask(__name__)

@app.route('/')
def home(): 
    return "Bot Calisiyor! (Ana Dizin)", 200

@app.route('/api')
def health_check(): 
    return "Sistem Aktif (API)", 200

def run_web_server():
    app.run(host='0.0.0.0', port=8080, debug=False, use_reloader=False)

TOKEN = os.environ.get("TELEGRAM_TOKEN")
MY_CHAT_ID = os.environ.get("MY_CHAT_ID")
bot = telebot.TeleBot(TOKEN)
DATA_FILE = "borsa_verileri.json"
CSV_FILE = "hisse_endeks_katilim_ds.csv" # Senin yüklediğin dosya adı

# İlk Kurulum Listeleri (Katılım buraya boş gelecek, dosyadan dolacak)
GRUPLAR = {
    "katilim": [], 
    "bist30": ["AKBNK.IS", "ARCLK.IS", "ASELS.IS", "BIMAS.IS", "EREGL.IS", "FROTO.IS", "GARAN.IS", "KCHOL.IS", "THYAO.IS", "TUPRS.IS"],
    "altin": ["ALTINS.IS", "ZGOLD.IS", "GMSTR.IS", "GLDGR.IS"]
}

# --- 2. LİSTE VE VERİ YÖNETİMİ (DOSYA ENTEGRASYONU) ---
def listeleri_yonet():
    # Önce CSV'den katılım listesini güncelleyelim
    katilim_listesi = []
    if os.path.exists(CSV_FILE):
        try:
            # Noktalı virgül ayracı ve ilk 2 satırı atlayarak oku
            df_csv = pd.read_csv(CSV_FILE, sep=';', skiprows=2, header=None)
            ham_liste = df_csv.iloc[:, 0].dropna().astype(str).tolist()
            for h in ham_liste:
                sembol = h.split('.')[0].strip().upper()
                if sembol:
                    katilim_listesi.append(f"{sembol}.IS")
            # Mükerrerleri temizle
            katilim_listesi = sorted(list(set(katilim_listesi)))
        except Exception as e:
            print(f"❌ CSV Okuma Hatası: {e}")

    # JSON dosyasını yönet
    if not os.path.exists(DATA_FILE):
        data_to_save = GRUPLAR.copy()
        if katilim_listesi:
            data_to_save["katilim"] = katilim_listesi
        
        data = {"last_update": time.time(), "lists": data_to_save}
        with open(DATA_FILE, "w") as f: json.dump(data, f)
        return data_to_save
    
    with open(DATA_FILE, "r") as f:
        mevcut_data = json.load(f)
        aktif_listeler = mevcut_data["lists"]
        # Katılım listesini her zaman dosyadan gelenle güncelle
        if katilim_listesi:
            aktif_listeler["katilim"] = katilim_listesi
        return aktif_listeler

def listeleri_internetten_guncelle():
    print("🌐 BIST listeleri internetten güncelleniyor...")
    try:
        url = "https://www.isyatirim.com.tr/tr-tr/analiz/hisse/Sayfalar/temel-veriler.aspx"
        r = requests.get(url, timeout=15)
        soup = BeautifulSoup(r.text, 'html.parser')
        cekilen = [tag.text.strip() + ".IS" for tag in soup.find_all('th') if 2 <= len(tag.text.strip()) <= 6]

        if len(cekilen) > 50:
            aktif = listeleri_yonet()
            aktif["bist100"] = cekilen[:100]
            aktif["bist30"] = cekilen[:30]
            with open(DATA_FILE, "w") as f:
                json.dump({"last_update": time.time(), "lists": aktif}, f)
            print("✅ Listeler başarıyla güncellendi.")
            return True
    except Exception as e:
        print(f"❌ Güncelleme hatası: {e}")
        return False

# --- 3. ANALİZ VE SKORLAMA ---
def gemini_yorumu_ekle(ticker, rsi, fiyat, ema9, upper_bb, donem):
    alim = round(ema9, 2)
    strateji = f"\n💡 *Strateji:* {alim} desteği takip edilebilir." if donem != "sabah" else f"\n🚀 *Strateji:* {fiyat} üstü kalıcılık pozitif."
    if rsi < 32: return f"\n💎 **Gemini:** Hisse dipte, toplama bölgesi.{strateji}"
    elif rsi > 72 or fiyat >= upper_bb: return f"\n⚠️ **Gemini:** Doyumda, kâr alımı uygun olabilir.{strateji}"
    elif fiyat > ema9: return f"\n📈 **Gemini:** Trend yukarı canlı duruyor.{strateji}"
    else: return f"\n⚖️ **Gemini:** Güç topluyor, destek beklenmeli.{strateji}"

def hisse_skorla(ticker, donem="manuel"):
    try:
        ticker = str(ticker).strip().upper().replace("/", "")
        if not any(x in ticker for x in [".IS", "=", "-"]): ticker += ".IS"

        df = yf.download(ticker, period="6mo", interval="1d", progress=False)
        if df.empty or len(df) < 20: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df = df.dropna(subset=['Close'])

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
            "karar": karar, "df": df, "yorum": gemini_yorumu_ekle(ticker, rsi, fiyat, float(last["EMA9"]), float(last["BB_U"]), donem)
        }
    except: return None

def sonuc_gonder(chat_id, t):
    try:
        p_kar = round(((t["upper_bb"] - t["fiyat"]) / t["fiyat"]) * 100, 2)
        risk = round(((t["fiyat"] - t["ema21"]) / t["fiyat"]) * 100, 2)
        mesaj = (f"🏆 *{t['ticker']}*\n💰 *Fiyat:* {round(t['fiyat'], 2)} | *RSI:* {round(t['rsi'], 1)}\n🏁 *Karar:* `{t['karar']}`\n"
                 f"---------------------------\n🟢 *Destek (EMA9):* `{round(t['ema9'], 2)}` \n🎯 *Hedef:* `{round(t['upper_bb'], 2)}` (%{p_kar})\n"
                 f"🛑 *Stop (EMA21):* `{round(t['ema21'], 2)}` (%{risk})\n---------------------------\n{t['yorum']}")

        plt.figure(figsize=(7, 4)); plt.plot(t["df"]["Close"].tail(30).values, color="blue", linewidth=2)
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(chat_id, buf, caption=mesaj, parse_mode="Markdown")
        plt.close("all")
    except: pass

# --- 4. ZAMANLAYICI ---
def seans_raporu(donem):
    aktif = listeleri_yonet()
    bot.send_message(MY_CHAT_ID, f"📢 **RAPOR: {donem.upper()}**", parse_mode="Markdown")
    for h in aktif.get("katilim", []):
        res = hisse_skorla(h, donem)
        if res and res["karar"] in ["🔥 GÜÇLÜ", "📈 OLUMLU"]: sonuc_gonder(MY_CHAT_ID, res)

def zamanlayici():
    def donemsel_kontrol():
        simdi = datetime.now()
        if simdi.day == 1 and simdi.month in [1, 4, 7, 10]:
            listeleri_internetten_guncelle()

    schedule.every().day.at("08:00").do(donemsel_kontrol)
    is_gunleri = [schedule.every().monday, schedule.every().tuesday, 
                  schedule.every().wednesday, schedule.every().thursday, schedule.every().friday]

    for gun in is_gunleri:
        gun.at("09:55").do(seans_raporu, "sabah")
        gun.at("18:05").do(seans_raporu, "aksam")

    schedule.every().sunday.at("21:00").do(seans_raporu, "pazar")

    while True:
        schedule.run_pending()
        time.sleep(30)

# --- 5. MESAJ YÖNETİMİ ---
@bot.message_handler(func=lambda message: True)
def handle_text(message):
    metin = message.text.strip().replace("/", "").lower()
    temiz_metin = metin.replace("tum_", "") 

    aktif_listeler = listeleri_yonet()

    if temiz_metin in aktif_listeler:
        bot.send_message(message.chat.id, f"🔍 {metin.upper()} listesi taranıyor (Toplam: {len(aktif_listeler[temiz_metin])} hisse)...")
        for h in aktif_listeler[temiz_metin]:
            res = hisse_skorla(h)
            if res: sonuc_gonder(message.chat.id, res)
        bot.send_message(message.chat.id, "✅ Tarama bitti.")
    else:
        bot.send_message(message.chat.id, f"🔍 {metin.upper()} analiz ediliyor...")
        res = hisse_skorla(metin)
        if res: sonuc_gonder(message.chat.id, res)
        else: bot.send_message(message.chat.id, "❌ Veri alınamadı.")

if __name__ == "__main__":
    # Çakışmaları önlemek için webhook temizleme
    bot.remove_webhook()
    time.sleep(1)

    threading.Thread(target=run_web_server, daemon=True).start()
    threading.Thread(target=zamanlayici, daemon=True).start()

    print("🚀 Sistem Hazır! Katılım listesi CSV'den okunuyor.")
    bot.infinity_polling(timeout=10, long_polling_timeout=5)
