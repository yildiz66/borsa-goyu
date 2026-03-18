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

# Dosyanızdaki 215 hisselik tam liste
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
    "SRVGY", "SUNTK", "SURGY", "SUWEN", "TARKM", "TDGYO", "TEZOL", "TKNSA", "TMSN", "TOASO",
    "TRILC", "TSPOR", "TUCLK", "TUKAS", "TUPRS", "TURGG", "TUREX", "ULAS", "ULKER", "ULUFA",
    "ULUSE", "UNLU", "USAK", "VAKFN", "VANGD", "VBTYZ", "VERTU", "VESBE", "VESTL", "YEOTK",
    "YGGYO", "YGYO", "YUNSA", "YYLGD", "ZEDUR"
]

def analiz_motoru(hisse, vade="1d"):
    try:
        f_t = f"{hisse.upper().strip()}.IS"
        df = yf.download(f_t, period="1y", interval=vade, progress=False, timeout=10)
        if df is None or df.empty or len(df) < 20: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        df["RSI"] = ta.rsi(df["Close"], length=14)
        bb = ta.bbands(df["Close"], length=20)
        df["Vol_Avg"] = df["Volume"].rolling(window=5).mean()
        
        c_price = float(df.iloc[-1]["Close"])
        c_rsi = float(df.iloc[-1]["RSI"])
        u_band = float(bb.iloc[-1, 2])
        c_vol = float(df.iloc[-1]["Volume"])
        a_vol = float(df.iloc[-1]["Vol_Avg"])
        
        # Hacim desteği ve potansiyel hesabı
        vol_score = 1.3 if c_vol > a_vol else 1.0
        potential = ((u_band - c_price) / c_price) * 100 * vol_score
        
        return {"ticker": hisse, "fiyat": c_price, "rsi": c_rsi, "pot": potential, "df": df}
    except: return None

def rapor_gonder(liste, vade, baslik):
    bot.send_message(MY_ID, f"🚀 {baslik} Strateji Analizi Başladı Emir Bey...\n(215 Hisse taranıp en iyi 5 tanesi seçilecek)")
    havuz = []
    
    for h in liste:
        res = analiz_motoru(h, vade)
        if res and 30 < res["rsi"] < 70: 
            havuz.append(res)
        time.sleep(0.05)

    # Teknik olarak en iyi 5 finalist
    en_iyi = sorted(havuz, key=lambda x: x['pot'], reverse=True)[:5]
    
    if not en_iyi:
        bot.send_message(MY_ID, "⚠️ Kriterlere uygun hisse bulunamadı.")
        return

    ai_data = []
    for t in en_iyi:
        # SADECE SEÇİLEN 5 HİSSE İÇİN GRAFİK
        plt.figure(figsize=(5, 3))
        plt.plot(t["df"]["Close"].tail(30).values, color='green', linewidth=2)
        plt.title(f"{t['ticker']} Trend", fontsize=10)
        plt.grid(True, alpha=0.2)
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(MY_ID, buf, caption=f"💎 *{t['ticker']}*\nFiyat: {round(t['fiyat'],2)} | RSI: {round(t['rsi'],1)}")
        plt.close()
        ai_data.append(f"{t['ticker']}: Fiyat {t['fiyat']}, RSI {t['rsi']}, Puan {round(t['pot'],1)}")

    # SADECE SEÇİLEN 5 HİSSE İÇİN GEMINI
    try:
        time.sleep(2)
        prompt = (f"Sen borsa stratejistisin. Şu 5 hisse ön elemeyi geçti: {ai_data}. "
                  "Bu hisseleri haber ve sektör bazlı analiz et. Emir Bey'e her biri için "
                  "net 'AL' veya 'BEKLE' tavsiyesi ver ve nedenini kısa açıkla.")
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        bot.send_message(MY_ID, f"🤖 *Gemini Karar Odası:*\n\n{response.text}", parse_mode="Markdown")
    except:
        bot.send_message(MY_ID, "⚠️ Analiz kısmında yoğunluk var, teknik veriler yukarıdadır.")

@bot.message_handler(commands=['start'])
def start(m): bot.send_message(m.chat.id, "📈 Terminal Hazır Emir Bey. /gunluk yazarak 5 elması bulabiliriz.")

@bot.message_handler(commands=['gunluk'])
def cmd_1(m): rapor_gonder(KATILIM_TUMU, "1d", "GÜNLÜK")

# (Diğer komutlar aynı yapıda...)

if __name__ == "__main__":
    try: requests.get(f"https://api.telegram.org/bot{TOKEN}/deleteWebhook?drop_pending_updates=True")
    except: pass
    threading.Thread(target=lambda: app.run(host='0.0.0.0', port=os.environ.get("PORT", 8080)), daemon=True).start()
    bot.infinity_polling()
