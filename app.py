import streamlit as st
import requests
import pandas as pd
import ta
import time

st.set_page_config(page_title="Scanner Forex/Crypto", page_icon="📊", layout="wide")

st.title("📊 Scanner Multi-Timeframe")
st.caption("Filtres : Sweep HTF + EMA 200/800 + RSI Baseline")

# Récupération automatique de la clé API depuis les Secrets Streamlit
API_KEY_SECRET = st.secrets.get("TWELVEDATA_API_KEY", "")

st.sidebar.header("⚙️ Configuration")
API_KEY = st.sidebar.text_input("Clé API Twelve Data", value=API_KEY_SECRET, type="password")

# Liste complète : Forex Majeures, Croisées, Or & Bitcoin
ALL_PAIRS = [
    # Métaux & Cryptos
    "XAU/USD", "BTC/USD",
    # Majeures Forex
    "EUR/USD", "GBP/USD", "USD/JPY", "USD/CHF", "AUD/USD", "USD/CAD", "NZD/USD",
    # Croisées Forex
    "EUR/GBP", "EUR/JPY", "EUR/CHF", "EUR/CAD", "EUR/AUD", "EUR/NZD",
    "GBP/JPY", "GBP/CHF", "GBP/CAD", "GBP/AUD", "GBP/NZD",
    "AUD/JPY", "AUD/NZD", "AUD/CAD", "AUD/CHF",
    "NZD/JPY", "NZD/CAD", "NZD/CHF",
    "CAD/JPY", "CAD/CHF", "CHF/JPY"
]

SYMBOLS = st.sidebar.multiselect("Paires analysées", ALL_PAIRS, default=ALL_PAIRS)

# Options de Timeframes Supérieurs demandées : Monthly, Weekly, Daily, H4
HTF = st.sidebar.selectbox("Timeframe Supérieur (HTF)", ["1month", "1week", "1day", "4h"])

# Mapping automatique avec les Timeframes Inférieurs (LTF)
TIMEFRAME_MAP = {
    "1month": "1day",
    "1week": "4h",
    "1day": "4h",
    "4h": "15min"
}

def fetch_data(symbol, interval):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize=900&apikey={API_KEY}"
    try:
        res = requests.get(url).json()
        if "values" not in res: 
            return pd.DataFrame()
        df = pd.DataFrame(res["values"])
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime').reset_index(drop=True)
        for c in ['open', 'high', 'low', 'close']: 
            df[c] = df[c].astype(float)
        return df
    except: 
        return pd.DataFrame()

def analyze(symbol):
    ltf = TIMEFRAME_MAP.get(HTF, "15min")
    df_htf = fetch_data(symbol, HTF)
    df_ltf = fetch_data(symbol, ltf)

    if df_htf.empty or df_ltf.empty or len(df_htf) < 3:
        return {"Paire": symbol, "Signal": "NEUTRE", "Prix": "-", "EMA": "-", "RSI": "-", "Raison": "Données manquantes ou limite API"}

    b_prev, b_curr = df_htf.iloc[-2], df_htf.iloc[-1]
    prev_mid = (b_prev['open'] + b_prev['close']) / 2
    
    swept_low = b_curr['low'] < b_prev['low'] and b_curr['close'] > prev_mid and b_curr['close'] > b_curr['open']
    swept_high = b_curr['high'] > b_prev['high'] and b_curr['close'] < prev_mid and b_curr['close'] < b_curr['open']

    df_ltf['EMA200'] = ta.trend.ema_indicator(df_ltf['close'], window=200)
    df_ltf['EMA800'] = ta.trend.ema_indicator(df_ltf['close'], window=800)
    df_ltf['RSI'] = ta.momentum.rsi(df_ltf['close'], window=14)
    df_ltf['Base'] = ta.trend.sma_indicator(df_ltf['RSI'], window=14)

    price = df_ltf['close'].iloc[-1]
    e200, e800 = df_ltf['EMA200'].iloc[-1], df_ltf['EMA800'].iloc[-1]
    rsi_c, base_c = df_ltf['RSI'].iloc[-1], df_ltf['Base'].iloc[-1]
    rsi_p, base_p = df_ltf['RSI'].iloc[-2], df_ltf['Base'].iloc[-2]

    ema_bull = price > e200 and price > e800
    ema_bear = price < e200 and price < e800

    rsi_buy = (rsi_p <= base_p and rsi_c >= base_c) or ((base_c - rsi_c) <= 2.5 and rsi_c < base_c)
    rsi_sell = (rsi_p >= base_p and rsi_c <= base_c) or ((rsi_c - base_c) <= 2.5 and rsi_c > base_c)

    if swept_low and ema_bull and rsi_buy:
        return {"Paire": symbol, "Signal": "🚀 ACHAT", "Prix": price, "EMA": "Support OK", "RSI": f"{rsi_c:.1f}/{base_c:.1f}", "Raison": "Sweep + Tendance OK"}
    elif swept_high and ema_bear and rsi_sell:
        return {"Paire": symbol, "Signal": "🔻 VENTE", "Prix": price, "EMA": "Résistance OK", "RSI": f"{rsi_c:.1f}/{base_c:.1f}", "Raison": "Sweep + Tendance OK"}

    return {"Paire": symbol, "Signal": "NEUTRE", "Prix": price, "EMA": "-", "RSI": f"{rsi_c:.1f}/{base_c:.1f}", "Raison": "Conditions non alignées"}

if API_KEY:
    if st.button("🔄 Scanner le marché"):
        st.cache_data.clear()
    
    progress_bar = st.progress(0)
    status_text = st.empty()
    
    results = []
    total = len(SYMBOLS)
    
    for idx, symbol in enumerate(SYMBOLS):
        status_text.text(f"Analyse en cours ({HTF}) : {symbol} ({idx+1}/{total})...")
        res = analyze(symbol)
        results.append(res)
        progress_bar.progress((idx + 1) / total)
        time.sleep(0.3)
        
    status_text.text("Analyse terminée !")
    st.dataframe(pd.DataFrame(results), use_container_width=True)
else:
    st.warning("Insère ta clé Twelve Data dans le menu à gauche pour afficher les résultats.")
