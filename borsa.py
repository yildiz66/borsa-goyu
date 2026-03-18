import os, telebot, yfinance as yf, pandas_ta as ta, io, threading, warnings, time, requests
import pandas as pd
import matplotlib.pyplot as plt
from google import genai
from flask import Flask

warnings.filterwarnings("ignore")
app = Flask(__name__)
@app.route('/')
def home(): return "Borsabot Aktif", 200

TOKEN = os.environ.get("TELEGRAM_TOKEN")
GEMINI_KEY = os.environ.get("GEMINI_API_KEY")
MY_ID = os.environ.get("MY_CHAT_ID")

bot = telebot.TeleBot(TOKEN)
client = genai.Client(api_key=GEMINI_KEY)

# DOSYANIZDAKİ TÜM KATILIM HİSSELERİ (TOPLAM 215 ADET)
KATILIM_TUMU = [
    "ACSEL", "AHSGY", "AKFYE", "AKHAN", "AKSA", "AKYHO", "ALBRK", "ALCTL", "ALKA", "ALKIM", 
    "ALKLC", "ALTNY", "ALVES", "ANGEN", "ARASE", "ARDYZ", "ARFYE", "ASELS", "ATAKP", "ATATP", 
    "AVPGY", "AYEN", "BAHKM", "BAKAB", "BANVT", "BASGZ", "BEGYO", "BERA", "BESTE", "BIENY", 
    "BIMAS", "BINBN", "BINHO", "BMSTL", "BNTAS", "BORSK", "BOSSA", "BRISA", "BRKSN", "BRLSM", 
    "BSOKE", "BURCE", "BURVA", "CANTE", "CATES", "CELHA", "CEMTS", "CEMZY", "CIMSA", "CMBTN", 
    "COSMO", "CVKMD", "CWENE", "DAPGM", "DARDL", "DCTTR", "DENGE", "DESPC", "DGATE", "DGNMO", 
    "DMSAS", "DOFER", "DOFRB", "DOGUB", "DYOBY", "EBEBK", "EDATA", "EDIP", "EFOR", "EGEPO", 
    "EGGUB", "EGPRO", "EKGYO", "EKSUN", "ELITE", "EMPAE", "ENJSA", "EREGL", "ESCOM", "EUPWR", 
    "EYGYO", "FADE", "FONET", "FORMT", "FORTE", "FRMPL", "FZLGY", "GEDZA", "GENIL", "GENKM", 
    "GENTS", "GEREL", "GESAN", "GLRMK", "GOKNR", "GOLTS", "GOODY", "GRSEL", "GRTHO", "GUBRF", 
    "GUNDG", "HATSN", "HKTM", "HOROZ", "HRKET", "IDGYO", "IHEVA", "IHLAS", "IHLGM", "IHYAY", 
    "IMASM", "INTEM", "ISDMR", "ISSEN", "IZFAS", "IZINV", "JANTS", "KARSN", "KATMR", "KBORU", 
    "KCAER", "KIMMR", "KLSYN", "KNFRT", "KOCMT", "KONKA", "KONTR", "KONYA", "KOPOL", "KOTON", 
    "KRDMA", "KRDMB", "KRDMD", "KRGYO", "KRONT", "KRPLS", "KRSTL", "KRVGD", "KTLEV", "KUTPO", 
    "KUYAS", "KZBGY", "LKMNH", "LMKDC", "LOGO", "LXGYO", "MAGEN", "MAKIM", "MARBL", "MAVI", 
    "MCARD", "MEDTR", "MEKAG", "MERCN", "MEYSU", "MNDRS", "MNDTR", "MOBTL", "MPARK", "NETAS", 
    "NTGAZ", "OBAMS", "OBASE", "OFSYM", "ONCSM", "ORGE", "OSTIM", "OZRDN", "OZYSR", "PAGYO", 
    "PARSN", "PASEU", "PENGD", "PENTA", "PETKM", "PETUN", "PKART", "PLTUR", "PNLSN", "POLHO", 
    "QUAGR", "RGYAS", "RNPOL", "RODRG", "RUBNS", "SAFKR", "SAMAT", "SANEL", "SANKO", "SARKY", 
    "SAYAS", "SEKUR", "SELEC", "SELVA", "SILVR", "SMART", "SMRTG", "SNGYO", "SNICA", "SOKE", 
    "SRVGY", "SUNTK", "SURGY", "SUWEN", "TARKM", "TDGYO", "TEZOL", "TKNSA", "TMSN"
]

FON_LISTESI = ["GC=F", "GMSTR.IS", "SI=F", "USDTRY=X"]

def set_commands():
    try:
        bot.delete_my_commands()
        time.sleep(1)
        commands = [
            telebot.types.BotCommand("gunluk", "Günlük Tarama"),
            telebot.types.BotCommand("ikihaftalik", "2 Haftalık Tarama"),
            telebot.types.BotCommand("aylik", "Aylık Tarama"),
            telebot.types.BotCommand("fonlar", "Metal ve Döviz"),
            telebot.types.BotCommand("start", "Başlat")
        ]
        bot.set_my_commands(commands)
    except: pass

def analiz_motoru(hisse, donem="1d"):
    try:
        ticker = hisse.upper().strip()
        f_t = ticker if ("=" in ticker or ".IS" in ticker) else f"{ticker}.IS"
        
        df = yf.download(f_t, period="2y", interval=donem, progress=False, threads=False, timeout=7)
        
        if df is None or df.empty or len(df) < 15: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        df["RSI"] = ta.rsi(df["Close"], length=14)
        bb = ta.bbands(df["Close"], length=20)
        
        return {
            "ticker": ticker, 
            "fiyat": float(df.iloc[-1]["Close"]), 
            "rsi": float(df.iloc[-1]["RSI"]), 
            "ust": float(bb.iloc[-1, 2]), 
            "df": df
        }
    except: return None

def rapor_gonder(liste, vade, baslik):
    bot.send_message(MY_ID, f"🔍 {baslik} tarama başladı Emir Bey...")
    havuz = []
    for h in liste:
        res = analiz_motoru(h, vade)
        if res and 30 < res["rsi"] < 75: 
            havuz.append(res)
        time.sleep(0.1)

    en_iyi = sorted(havuz, key=lambda x: ((x['ust'] - x['fiyat']) / x['fiyat']), reverse=True)[:5]
    
    if not en_iyi:
        bot.send_message(MY_ID, "⚠️ Uygun hisse bulunamadı.")
        return

    ai_data = []
    for t in en_iyi:
        pot = round(((t["ust"] - t["fiyat"]) / t["fiyat"]) * 100, 1)
        ai_data.append(f"{t['ticker']}: Fiyat {round(t['fiyat'],2)}, RSI {round(t['rsi'],1)}, Potansiyel %{pot}")
        
        plt.figure(figsize=(4, 2)); plt.plot(t["df"]["Close"].tail(20).values, color='green'); plt.axis('off')
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(MY_ID, buf, caption=f"💎 *{t['ticker']}*\nFiyat: {round(t['fiyat'], 2)} | RSI: {round(t['rsi'], 1)} | Pot: %{pot}")
        plt.close()

    # YENİ GEMINI ANALİZ BLOĞU
    try:
        if ai_data:
            prompt = f"Bir borsa uzmanı olarak bu teknik verileri ({baslik} vade) yorumla: {ai_data}. Emir Bey'e kısa, net ve profesyonel bir analiz sun."
            # Gemini 2.0 Flash kullanımı
            response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
            bot.send_message(MY_ID, f"🤖 *Gemini Analizi:*\n\n{response.text}", parse_mode="Markdown")
    except Exception as e:
        print(f"Gemini Hatası: {e}")

@bot.message_handler(commands=['start'])
def start(m): bot.send_message(m.chat.id, "📈 Terminal Hazır. Yeni Gemini 2.0 motoru devrede.")

@bot.message_handler(commands=['gunluk'])
def cmd_1(m): rapor_gonder(KATILIM_TUMU, "1d", "GÜNLÜK")

@bot.message_handler(commands=['ikihaftalik'])
def cmd_2(m): rapor_gonder(KATILIM_TUMU, "1wk", "2 HAFTALIK")

@bot.message_handler(commands=['aylik'])
def cmd_3(m): rapor_gonder(KATILIM_TUMU, "1mo", "AYLIK")

@bot.message_handler(commands=['fonlar'])
def cmd_4(m): rapor_gonder(FON_LISTESI, "1d", "METAL/DÖVİZ")

if __name__ == "__main__":
    requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True")
    time.sleep(1)
    set_commands()
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080)), daemon=True).start()
    bot.infinity_polling(timeout=20)
