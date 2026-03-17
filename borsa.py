import os, telebot, yfinance as yf, ta, pandas as pd
import google.generativeai as genai
from telebot import types

# --- AI & BOT YAPILANDIRMASI ---
genai.configure(api_key=os.environ.get("GEMINI_API_KEY"))
model = genai.GenerativeModel('gemini-pro')
bot = telebot.TeleBot(os.environ.get("TELEGRAM_TOKEN"))

# --- 1. LİSTE TANIMLAMALARI ---
def get_katilim_list():
    try:
        df = pd.read_csv("hisse_endeks_katilim_ds.csv", sep=';')
        return [str(k).split('.')[0] + ".IS" for k in df.iloc[:,0].tolist()]
    except: return ["THYAO.IS", "BIMAS.IS", "ASELS.IS"]

LİSTELER = {
    "BIST 30": ["AKBNK.IS", "ARCLK.IS", "ASELS.IS", "BIMAS.IS", "BRSAN.IS", "EKGYO.IS", "ENJSA.IS", "EREGL.IS", "FROTO.IS", "GARAN.IS", "GUBRF.IS", "HEKTS.IS", "KCHOL.IS", "KONTR.IS", "KOZAL.IS", "KRDMD.IS", "MGROS.IS", "ODAS.IS", "OYAKC.IS", "PETKM.IS", "PGSUS.IS", "SAHOL.IS", "SASA.IS", "SISE.IS", "TAVHL.IS", "THYAO.IS", "TOASO.IS", "TCELL.IS", "TUPRS.IS", "YKBNK.IS"],
    "BIST 100": ["XU100.IS"], # Endeks takibi için
    "KATILIM": get_katilim_list()
}

# --- 2. PROFESYONEL FİLTRE MOTORU ---
def profesyonel_analiz(ticker, periyot="1d", limit=3):
    """
    Hacim + RSI + EMA + Temel + AI süzgeci.
    periyot: '1d' (Günlük), '1wk' (Haftalık), '1mo' (Aylık)
    """
    try:
        df = yf.download(ticker, period="1y", interval=periyot, progress=False)
        if len(df) < 30: return None
        
        # Teknik Veriler
        c = df["Close"]
        rsi = ta.momentum.RSIIndicator(c).rsi().iloc[-1]
        ema9 = ta.trend.EMAIndicator(c, window=9).ema_indicator().iloc[-1]
        hacim_ort = df["Volume"].rolling(window=10).mean().iloc[-1]
        son_hacim = df["Volume"].iloc[-1]
        fiyat = c.iloc[-1]

        # Skorlama
        skor = 0
        if fiyat > ema9: skor += 1
        if 48 < rsi < 68: skor += 1
        if son_hacim > (hacim_ort * 1.15): skor += 1 # %15 hacim artışı şartı

        # Sadece skor eşiğini geçenleri döndür (Nokta Atışı)
        if skor >= limit:
            prompt = f"{ticker} için {periyot} periyodunda teknik analiz yap. RSI:{rsi}, Fiyat:{fiyat}. Nokta atışı strateji ver."
            ai_cevap = model.generate_content(prompt).text
            return {"ticker": ticker, "fiyat": fiyat, "skor": skor, "ai": ai_cevap, "rsi": rsi}
    except: return None

# --- 3. BAĞIMSIZ TELEGRAM MENÜSÜ ---
@bot.message_handler(commands=['start'])
def send_welcome(message):
    markup = types.ReplyKeyboardMarkup(row_width=2, resize_keyboard=True)
    # Bağımsız Seçenekleri Tanımlıyoruz
    markup.add("📊 BIST 100", "🏆 BIST 30", "🏢 BIST ANA PAZAR")
    markup.add("🔥 BIST 100 FIRSAT", "⭐ BIST 30 FIRSAT", "💎 BIST ANA FIRSAT")
    markup.add("🕌 KATILIM TÜM", "🎯 KATILIM FIRSAT GÜNLÜK")
    markup.add("⏳ KATILIM FIRSAT 2 HAFTALIK", "🗓️ KATILIM FIRSAT AYLIK")
    bot.send_message(message.chat.id, "⚡ **Nokta Atışı Yatırım Sistemine Hoş Geldin!**\nHangi piyasada fırsat arıyoruz?", reply_markup=markup)

# --- 4. BUTON TETİKLEYİCİLERİ ---
@bot.message_handler(func=lambda m: True)
def handle_menu(message):
    msg = message.text
    bot.send_message(message.chat.id, f"🔍 `{msg}` taranıyor, lütfen bekle...")
    
    results = []
    # Seçeneğe göre hedef listeyi ve periyodu belirle
    if "BIST 30 FIRSAT" in msg:
        for t in LİSTELER["BIST 30"]:
            res = profesyonel_analiz(t, "1d", limit=3)
            if res: results.append(res)
            
    elif "KATILIM FIRSAT GÜNLÜK" in msg:
        for t in LİSTELER["KATILIM"]:
            res = profesyonel_analiz(t, "1d", limit=3)
            if res: results.append(res)

    elif "KATILIM FIRSAT 2 HAFTALIK" in msg:
        for t in LİSTELER["KATILIM"]:
            res = profesyonel_analiz(t, "1wk", limit=2) # Orta vade daha esnek skor
            if res: results.append(res)

    # Sonuçları Gönder
    if not results:
        bot.send_message(message.chat.id, "❌ Şu an kriterlere uyan 'Nokta Atışı' bir fırsat bulunamadı.")
    else:
        for r in results:
            bot.send_message(message.chat.id, f"✅ **{r['ticker']}**\n💰 Fiyat: {round(r['fiyat'],2)}\n📊 RSI: {round(r['rsi'],1)}\n{r['ai']}")

bot.polling()
