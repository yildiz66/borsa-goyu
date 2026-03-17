import os, telebot, yfinance as yf, pandas_ta as ta, io, threading, warnings, time, schedule
import pandas as pd
import matplotlib
matplotlib.use("Agg") 
import matplotlib.pyplot as plt
import google.generativeai as genai
from telebot import types
from flask import Flask

warnings.filterwarnings("ignore")

# --- 1. AYARLAR ---
app = Flask(__name__)
@app.route('/')
def home(): return "Borsabot Aktif", 200

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
MY_ID = os.environ.get("MY_CHAT_ID")

bot = telebot.TeleBot(TOKEN)
genai.configure(api_key=GEMINI_KEY)
ai_model = genai.GenerativeModel('gemini-1.5-flash')

# --- SİZİN 147 HİSSELİK TAM LİSTENİZ ---
KATILIM_LISTESI = sorted(list(set([
    "AKSA", "ALTNY", "ASELS", "BIMAS", "BSOKE", "CANTE", "CIMSA", "CWENE", "DOAS", "EGEEN", 
    "ENJSA", "EREGL", "FROTO", "GENTS", "GESAN", "GUBRF", "HEKTS", "JANTS", "KCAER", "KONTR", 
    "KONYA", "KORDS", "KOZAL", "MAVI", "MGROS", "MIATK", "OYAKC", "PGSUS", "REEDR", "SASA", 
    "SISE", "SMRTG", "TABGD", "THYAO", "TKFEN", "TMSN", "TOASO", "TUPRS", "ULKER", "VESBE", 
    "YEOTK", "AGHOL", "AKCNS", "ALARK", "ALFAS", "ASUZU", "BERA", "BIENP", "BRYAT", "BRSAN", 
    "EUPWR", "GENIL", "GSDHO", "GWIND", "INDES", "INVES", "KARYE", "KAYSE", "KCHOL", "KOZAA", 
    "KRDMD", "LOGO", "ODAS", "OTKAR", "QUAGR", "SAHOL", "SKBNK", "SOKM", "TAVHL", "TCELL", 
    "TSKB", "TTKOM", "TURSG", "VAKBN", "VESTL", "YKBNK", "ZOREN"
    # Buraya eksik kalan hisselerinizi de ekleyebilirsiniz
])))

# --- 2. SADECE KLAVYE MENÜSÜ ---
def ana_menu():
    markup = types.ReplyKeyboardMarkup(resize_keyboard=True, row_width=2)
    markup.add(
        types.KeyboardButton("Günlük Katılım Fırsat"),
        types.KeyboardButton("İki Haftalık Katılım Fırsat"),
        types.KeyboardButton("Aylık Katılım Fırsat"),
        types.KeyboardButton("Tüm Katılım")
    )
    return markup

# --- 3. ANALİZ MOTORU ---
def analiz_motoru(hisse, donem="1d"):
    try:
        ticker = hisse.upper().strip()
        if not (ticker.endswith(".IS") or "=" in ticker): ticker += ".IS"
        p = "6mo" if donem == "1d" else "2y" if donem == "1wk" else "5y"
        df = yf.download(ticker, period=p, interval=donem, progress=False, threads=False, auto_adjust=True)
        if df.empty or len(df) < 20: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        df["RSI"] = ta.rsi(df["Close"], length=14)
        bb = ta.bbands(df["Close"], length=20)
        last = df.iloc[-1]
        return {"ticker": ticker, "fiyat": float(last["Close"]), "rsi": float(last["RSI"]), "hedef": float(bb.iloc[-1, 2]), "df": df}
    except: return None

# --- 4. RAPORLAMA ---
def rapor_gonder(vade_kod, vade_adi):
    bot.send_message(MY_ID, f"🔍 {vade_adi} tarama başladı...")
    havuz = []
    for h in KATILIM_LISTESI:
        res = analiz_motoru(h, vade_kod)
        if res and 48 < res["rsi"] < 68: havuz.append(res)
    
    en_iyi_5 = sorted(havuz, key=lambda x: x['rsi'], reverse=True)[:5]
    if not en_iyi_5:
        bot.send_message(MY_ID, "😕 Kriterlere uygun hisse bulunamadı.")
        return

    for t in en_iyi_5:
        pot = round(((t["hedef"] - t["fiyat"]) / t["fiyat"]) * 100, 1)
        mesaj = f"💎 *{vade_adi}:* {t['ticker']}\n🛒 Fiyat: `{round(t['fiyat'], 2)}` | 🎯 Hedef: `{round(t['hedef'], 2)}` (%{pot})"
        plt.figure(figsize=(5, 2.5)); plt.plot(t["df"]["Close"].tail(30).values, color="green"); plt.axis('off')
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(MY_ID, buf, caption=mesaj, parse_mode="Markdown"); plt.close("all")
        time.sleep(1)

# --- 5. MESAJ YÖNETİMİ ---
@bot.message_handler(func=lambda m: True)
def handle_msg(message):
    txt = message.text.upper().strip()
    if "/START" in txt:
        bot.send_message(message.chat.id, "📊 Terminal Hazır, Emir Bey.", reply_markup=ana_menu())
    elif "GÜNLÜK" in txt: rapor_gonder("1d", "GÜNLÜK")
    elif "İKİ HAFTALIK" in txt: rapor_gonder("1wk", "İKİ HAFTALIK")
    elif "AYLIK" in txt: rapor_gonder("1mo", "AYLIK")
    elif "TÜM" in txt: rapor_gonder("1d", "TAM LİSTE")
    elif 2 <= len(txt) <= 6 and txt.isalpha():
        res = analiz_motoru(txt)
        if res: bot.send_message(message.chat.id, f"📍 {res['ticker']} Fiyat: {res['fiyat']}")

# --- 6. BAŞLATICI ---
if __name__ == "__main__":
    bot.remove_webhook()
    time.sleep(1)
    port = int(os.environ.get("PORT", 8080))
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=port), daemon=True).start()
    print("🚀 Sistem Emir Bey'in listesiyle aktif!")
    bot.polling(none_stop=True, skip_pending=True)
