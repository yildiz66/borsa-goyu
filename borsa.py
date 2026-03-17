import os, telebot, yfinance as yf, pandas_ta as ta, io, threading, warnings, time, schedule
import matplotlib.pyplot as plt
import google.generativeai as genai
from telebot import types
from flask import Flask

# Uyarıları ve Grafik Arayüzünü Kapat
warnings.filterwarnings("ignore")
matplotlib.use("Agg")

# --- 1. AYARLAR VE API BAĞLANTILARI ---
app = Flask(__name__)
@app.route('/')
def home(): return "Borsabot Aktif", 200

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
MY_ID = os.environ.get("MY_CHAT_ID")

bot = telebot.TeleBot(TOKEN)
genai.configure(api_key=GEMINI_KEY)
ai_model = genai.GenerativeModel('gemini-1.5-flash')

# 147 Hisse - Sabit Katılım Listesi
KATILIM_LISTESI = sorted(list(set([
    "AKSA", "ALTNY", "ASELS", "BIMAS", "BSOKE", "CANTE", "CIMSA", "CWENE", "DOAS", "EGEEN", 
    "ENJSA", "EREGL", "FROTO", "GENTS", "GESAN", "GUBRF", "HEKTS", "JANTS", "KCAER", "KONTR", 
    "KONYA", "KORDS", "KOZAL", "MAVI", "MGROS", "MIATK", "OYAKC", "PGSUS", "REEDR", "SASA", 
    "SISE", "SMRTG", "TABGD", "THYAO", "TKFEN", "TMSN", "TOASO", "TUPRS", "ULKER", "VESBE", 
    "YEOTK", "AGHOL", "AKCNS", "ALARK", "ALFAS", "ASUZU", "BERA", "BIENP", "BRYAT", "BRSAN", 
    "EUPWR", "GENIL", "GSDHO", "GWIND", "INDES", "INVES", "KARYE", "KAYSE", "KCHOL", "KOZAA", 
    "KRDMD", "LOGO", "ODAS", "OTKAR", "QUAGR", "SAHOL", "SKBNK", "SOKM", "TAVHL", "TCELL", 
    "TSKB", "TTKOM", "TURSG", "VAKBN", "VESTL", "YKBNK", "ZOREN", "ADEL", "ADESE", "AGESA", 
    "AGROT", "AHGAZ", "AKFGY", "AKFYE", "AKPGR", "AKSUE", "ALBRK", "ALCTL", "ALKA", "ALMAD", 
    "ANELE", "ARCLK", "ARDYZ", "ARENA", "ARZUM", "ASGEY", "ASGYO", "ATATP", "ATEKS", "AVPGY", 
    "AYDEM", "AYEN", "AYGAZ", "BAGFS", "BAKAB", "BANVT", "BARMA", "BEYAZ", "BIGCH", "BIOEN", 
    "BLCYT", "BNTAS", "BOBET", "BORSK", "BRISA", "BRLSM", "BUCIM", "BURCE", "CELHA", "CEMTS", 
    "CONSE", "CVKMD", "DAGI", "DESPC", "DESAS", "DMSAS", "DOGUB", "DURDO", "DYOBY", "DZGYO", 
    "EDATA", "EGGUB", "EGSER", "EKGYO", "EKLPI", "ELITE", "ENKAI", "ERBOS", "ERSU", "ESCOM", 
    "EUHOL", "EYGY"
])))

# --- 2. ANALİZ VE AI ZEKASI ---

def analiz_motoru(hisse, donem="1d"):
    try:
        ticker = hisse.upper().strip()
        if not (ticker.endswith(".IS") or "=" in ticker): ticker += ".IS"
        p = "6mo" if donem == "1d" else "2y" if donem == "1wk" else "5y"
        
        df = yf.download(ticker, period=p, interval=donem, progress=False, threads=False)
        if df.empty or len(df) < 20: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)

        df["RSI"] = ta.rsi(df["Close"], length=14)
        df["EMA9"] = ta.ema(df["Close"], length=9)
        df["EMA21"] = ta.ema(df["Close"], length=21)
        bb = ta.bbands(df["Close"], length=20)
        
        last = df.iloc[-1]
        res = {
            "ticker": ticker, "fiyat": float(last["Close"]), "rsi": float(last["RSI"]),
            "ema9": float(last["EMA9"]), "ema21": float(last["EMA21"]),
            "hedef": float(bb.iloc[-1, 2]), "df": df, "vade": donem
        }
        
        # Skorlama: Teknik Güç
        res["skor"] = (10 if res["fiyat"] > res["ema9"] else 0) + (10 if 48 < res["rsi"] < 68 else 0)
        return res
    except: return None

def gemini_strateji_al(hisse_listesi, vade_adi):
    try:
        ozet = "".join([f"{h['ticker']}: Fiyat {h['fiyat']}, RSI {h['rsi']}. " for h in hisse_listesi])
        prompt = (f"Sen uzman bir borsa stratejistisin. Şu 5 hisseyi kıyasla: {ozet}. "
                  f"Hacim artışlarını ve piyasa haberlerini düşünerek Emir Bey için en iyi 1 veya 2 tanesini seç. "
                  f"Nedenini kısa ve öz açıkla, net bir al-sat emri ver.")
        return ai_model.generate_content(prompt).text
    except: return "AI yorumu şu an alınamıyor."

# --- 3. MESAJ VE RAPORLAMA ---

def rapor_gonder(vade_kod="1d", vade_adi="GÜNLÜK"):
    havuz = []
    for h in KATILIM_LISTESI:
        res = analiz_motoru(h, vade_kod)
        if res and res["skor"] >= 20: havuz.append(res)
    
    en_iyi_5 = sorted(havuz, key=lambda x: x['skor'], reverse=True)[:5]
    if not en_iyi_5: 
        bot.send_message(MY_ID, f"😕 {vade_adi} için uygun fırsat bulunamadı.")
        return

    for t in en_iyi_5:
        potansiyel = round(((t["hedef"] - t["fiyat"]) / t["fiyat"]) * 100, 1)
        mesaj = (f"💎 *{vade_adi} ANALİZ:* {t['ticker']}\n"
                 f"---------------------------\n"
                 f"🛒 *Alım:* `{round(t['fiyat'], 2)}` | 🎯 *Hedef:* `{round(t['hedef'], 2)}` (%{potansiyel})\n"
                 f"🛑 *Stop:* `{round(t['ema21'], 2)}` \n")
        
        plt.figure(figsize=(5, 2)); plt.plot(t["df"]["Close"].tail(30).values, color="green"); plt.axis('off')
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(MY_ID, buf, caption=mesaj, parse_mode="Markdown"); plt.close("all")
        time.sleep(1)

    ai_yorum = gemini_strateji_al(en_iyi_5, vade_adi)
    bot.send_message(MY_ID, f"⭐ *EMİR BEY İÇİN ÖZEL SEÇİM*\n\n{ai_yorum}", parse_mode="Markdown")

# --- 4. KLAVYE VE KOMUTLAR ---

def ana_menu():
    m = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    m.add("Günlük Katılım Fırsat", "İki Haftalık Katılım Fırsat", "Aylık Katılım Fırsat", "Tüm Katılım")
    return m

@bot.message_handler(func=lambda message: True)
def handle_requests(message):
    txt = message.text.upper().strip()
    if "FIRSAT" in txt:
        v = "1wk" if "HAFTALIK" in txt else "1mo" if "AYLIK" in txt else "1d"
        rapor_gonder(v, txt)
    elif "TÜM KATILIM" in txt:
        bot.send_message(message.chat.id, "🧾 147 Hisse Taranıyor...")
        # (Kısa özet listeleme kodu buraya gelebilir)
    elif 2 <= len(txt) <= 6: # Tekil Hisse Arama
        res = analiz_motoru(txt)
        if res:
            ai_notu = gemini_strateji_al([res], "ÖZEL SORGULAMA")
            mesaj = (f"📍 *HİSSE:* {res['ticker']}\n"
                     f"🛒 *Fiyat:* `{res['fiyat']}` | 🎯 *Hedef:* `{res['hedef']}`\n"
                     f"🤖 *AI:* {ai_notu}")
            plt.figure(figsize=(5, 2)); plt.plot(res["df"]["Close"].tail(30).values); plt.axis('off')
            buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
            bot.send_photo(message.chat.id, buf, caption=mesaj, parse_mode="Markdown"); plt.close("all")

# --- 5. ZAMANLAYICI DÖNGÜSÜ ---
def scheduler_start():
    schedule.every().monday.to.friday.at("09:55").do(lambda: rapor_gonder("1d", "SABAH AÇILIŞ"))
    schedule.every().monday.to.friday.at("17:50").do(lambda: rapor_gonder("1d", "AKŞAM KAPANIŞ"))
    while True:
        schedule.run_pending()
        time.sleep(30)

if __name__ == "__main__":
    threading.Thread(target=scheduler_start, daemon=True).start()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=8080), daemon=True).start()
    bot.infinity_polling()
