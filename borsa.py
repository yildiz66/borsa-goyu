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
import schedule
import threading
from datetime import datetime
from flask import Flask
import warnings

warnings.filterwarnings("ignore")

# --- 1. AYARLAR ---
app = Flask(__name__)
TOKEN = os.environ.get("TELEGRAM_TOKEN")
MY_CHAT_ID = os.environ.get("MY_CHAT_ID")
bot = telebot.TeleBot(TOKEN)
CSV_FILE = "hisse_endeks_katilim_ds.csv"

@app.route('/')
def home(): return "Borsa Botu Aktif (Railway)", 200

# Kod içinde duran yedek listeler (BIST30 ve Altın)
VARSAYILAN_GRUPLAR = {
    "bist30": ["AKBNK.IS", "ARCLK.IS", "ASELS.IS", "BIMAS.IS", "EREGL.IS", "FROTO.IS", "GARAN.IS", "KCHOL.IS", "THYAO.IS", "TUPRS.IS"],
    "altin": ["ALTINS.IS", "ZGOLD.IS", "GMSTR.IS", "GLDGR.IS"]
}

# --- 2. DİNAMİK LİSTE YÖNETİMİ (CSV OKUMA) ---
def listeleri_yukle():
    """Katılımı CSV'den (noktalı virgül ayracı ile), diğerlerini koddan çeker."""
    son_listeler = VARSAYILAN_GRUPLAR.copy()
    
    if os.path.exists(CSV_FILE):
        try:
            # Noktalı virgül ayracı ile oku, ilk 2 satırı (header ve açıklama) atla
            df = pd.read_csv(CSV_FILE, sep=';', skiprows=2, header=None)
            
            # İlk sütundaki (BILESEN KODU) verileri al
            ham_liste = df.iloc[:, 0].dropna().astype(str).tolist()
            
            temiz_katilim = []
            for h in ham_liste:
                # 'AKSA.E' gibi verileri 'AKSA.IS' formatına çevirir
                sembol = h.split('.')[0].strip().upper()
                if sembol and len(sembol) >= 2:
                    temiz_katilim.append(f"{sembol}.IS")
            
            # Mükerrer kayıtları sil (set kullanarak)
            son_listeler["katilim"] = sorted(list(set(temiz_katilim)))
            print(f"✅ {len(son_listeler['katilim'])} adet benzersiz katılım hissesi yüklendi.")
        except Exception as e:
            print(f"❌ CSV okuma hatası: {e}")
            son_listeler["katilim"] = []
    else:
        print(f"⚠️ {CSV_FILE} bulunamadı, katılım listesi boş.")
        son_listeler["katilim"] = []
        
    return son_listeler

# --- 3. ANALİZ VE SKORLAMA ---
def hisse_skorla(ticker, donem="manuel"):
    try:
        ticker = ticker.strip().upper()
        if not any(x in ticker for x in [".IS", "=", "-"]): ticker += ".IS"

        df = yf.download(ticker, period="6mo", interval="1d", progress=False)
        if df.empty or len(df) < 20: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

        df["RSI"] = ta.momentum.RSIIndicator(df["Close"]).rsi()
        df["EMA9"] = ta.trend.EMAIndicator(df["Close"], window=9).ema_indicator()
        df["EMA21"] = ta.trend.EMAIndicator(df["Close"], window=21).ema_indicator()
        df["BB_U"] = ta.volatility.BollingerBands(df["Close"]).bollinger_hband()

        last = df.iloc[-1]
        fiyat = float(last["Close"])
        rsi = float(last["RSI"])
        
        # Skorlama Mantığı
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
        p_kar = round(((t["upper_bb"] - t["fiyat"]) / t["fiyat"]) * 100, 2)
        mesaj = (f"🏆 *{t['ticker']}*\n💰 *Fiyat:* {round(t['fiyat'], 2)} | *RSI:* {round(t['rsi'], 1)}\n🏁 *Karar:* `{t['karar']}`\n"
                 f"---------------------------\n🟢 *Destek (EMA9):* `{round(t['ema9'], 2)}` \n🎯 *Hedef:* `{round(t['upper_bb'], 2)}` (%{p_kar})\n")

        plt.figure(figsize=(7, 4))
        plt.plot(t["df"]["Close"].tail(30).values, color="blue", linewidth=2)
        plt.title(f"{t['ticker']} Analiz")
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(chat_id, buf, caption=mesaj, parse_mode="Markdown")
        plt.close("all")
    except: pass

# --- 4. OTOMATİK RAPOR VE ZAMANLAYICI ---
def seans_raporu(donem):
    aktif = listeleri_yukle()
    target_list = aktif.get("katilim", [])
    if not target_list: return

    bot.send_message(MY_CHAT_ID, f"📢 **{donem.upper()} KATILIM ANALİZİ (GÜNCEL)**")
    for h in target_list:
        res = hisse_skorla(h, donem)
        # Sadece güçlü ve olumlu olanları otomatik raporla
        if res and res["karar"] in ["🔥 GÜÇLÜ", "📈 OLUMLU"]:
            sonuc_gonder(MY_CHAT_ID, res)

def zamanlayici():
    is_gunleri = [schedule.every().monday, schedule.every().tuesday, schedule.every().wednesday, schedule.every().thursday, schedule.every().friday]
    for gun in is_gunleri:
        gun.at("09:55").do(seans_raporu, "sabah")
        gun.at("18:05").do(seans_raporu, "aksam")
    while True:
        schedule.run_pending()
        time.sleep(30)

# --- 5. MESAJ YÖNETİMİ ---
@bot.message_handler(func=lambda message: True)
def handle_text(message):
    metin = message.text.strip().lower()
    aktif_listeler = listeleri_yukle()

    if metin in aktif_listeler:
        bot.send_message(message.chat.id, f"🔍 {metin.upper()} listesi taranıyor (Toplam: {len(aktif_listeler[metin])})...")
        for h in aktif_listeler[metin]:
            res = hisse_skorla(h)
            if res: sonuc_gonder(message.chat.id, res)
        bot.send_message(message.chat.id, "✅ Tarama tamamlandı.")
    else:
        # Tekil hisse sorgulama
        res = hisse_skorla(metin)
        if res:
            sonuc_gonder(message.chat.id, res)
        else:
            bot.send_message(message.chat.id, "❌ Hata: Liste ismi ('katilim', 'bist30') veya geçerli bir hisse kodu yazın.")

if __name__ == "__main__":
    # Flask ve Zamanlayıcıyı ayrı threadlerde başlat
    threading.Thread(target=zamanlayici, daemon=True).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=int(os.environ.get("PORT", 8080))), daemon=True).start()
    
    print("🚀 Bot Railway üzerinde çalışıyor...")
    bot.infinity_polling()
