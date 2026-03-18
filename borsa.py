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

def analiz_motoru(hisse, donem="1d"):
    try:
        ticker = hisse.upper().strip()
        f_t = ticker if ("=" in ticker or ".IS" in ticker) else f"{ticker}.IS"
        df = yf.download(f_t, period="1y", interval=donem, progress=False, timeout=10)
        
        if df is None or df.empty or len(df) < 20: return None
        if isinstance(df.columns, pd.MultiIndex): df.columns = df.columns.get_level_values(0)
        
        # Teknik Göstergeler
        df["RSI"] = ta.rsi(df["Close"], length=14)
        bb = ta.bbands(df["Close"], length=20)
        df["Vol_Avg"] = df["Volume"].rolling(window=5).mean() # 5 günlük hacim ortalaması
        
        curr_price = float(df.iloc[-1]["Close"])
        curr_rsi = float(df.iloc[-1]["RSI"])
        upper_band = float(bb.iloc[-1, 2])
        curr_vol = float(df.iloc[-1]["Volume"])
        avg_vol = float(df.iloc[-1]["Vol_Avg"])
        
        # HACİM TAKİBİ: Hacim ortalamanın üzerindeyse puan artır
        vol_score = 1.2 if curr_vol > avg_vol else 1.0
        potential = ((upper_band - curr_price) / curr_price) * 100 * vol_score
        
        return {"ticker": ticker, "fiyat": curr_price, "rsi": curr_rsi, "pot": potential, "df": df}
    except: return None

def rapor_gonder(liste, vade, baslik):
    bot.send_message(MY_ID, f"🚀 {baslik} Strateji Analizi Başladı (215 Hisse + Hacim Filtresi)...")
    havuz = []
    
    for h in liste:
        res = analiz_motoru(h, vade)
        if res and 30 < res["rsi"] < 70: havuz.append(res)
        time.sleep(0.05) # Hızlı tarama

    # En yüksek potansiyelli (ve hacimli) ilk 5'i seç
    en_iyi = sorted(havuz, key=lambda x: x['pot'], reverse=True)[:5]
    
    if not en_iyi:
        bot.send_message(MY_ID, "⚠️ Şu an kriterlere uyan fırsat bulunamadı.")
        return

    ai_data = []
    for t in en_iyi:
        # Grafik Gönderimi
        plt.figure(figsize=(4, 2))
        plt.plot(t["df"]["Close"].tail(30).values, color='green')
        plt.title(f"{t['ticker']} Trend", fontsize=8)
        plt.axis('off')
        buf = io.BytesIO(); plt.savefig(buf, format="png"); buf.seek(0)
        bot.send_photo(MY_ID, buf, caption=f"💎 {t['ticker']}\nFiyat: {round(t['fiyat'],2)}\nRSI: {round(t['rsi'],1)}")
        plt.close()
        ai_data.append(f"{t['ticker']}: Fiyat {t['fiyat']}, RSI {t['rsi']}, Puan {round(t['pot'],1)}")

    # GEMINI KARAR MEKANİZMASI
    try:
        time.sleep(2)
        prompt = (f"Sen uzman bir borsa analistisin. Teknik ve hacim puanları şunlar: {ai_data}. "
                  f"Bu hisseleri piyasa haberleri ve sektör durumlarıyla harmanla. "
                  f"Emir Bey'e her biri için 'AL' veya 'BEKLE' kararı ver ve nedenini 1 cümleyle açıkla. "
                  f"Çok net ve otoriter bir dil kullan.")
        
        response = client.models.generate_content(model="gemini-2.0-flash", contents=prompt)
        bot.send_message(MY_ID, f"🤖 *Gemini Karar Odası:*\n\n{response.text}", parse_mode="Markdown")
    except Exception as e:
        bot.send_message(MY_ID, "⚠️ Gemini kota doldu, teknik liste yukarıdadır.")

# ... (Start ve Polling kısımları aynı kalacak şekilde devam eder)
