import streamlit as st
import requests
import pandas as pd
import pandas_ta as ta

st.set_page_config(page_title="Scanner Forex/Crypto", page_icon="📊", layout="wide")

st.title("📊 Scanner Multi-Timeframe")
st.caption("Filtres : Sweep HTF + EMA 200/800 + RSI Baseline")

st.sidebar.header("⚙️ Configuration")
API_KEY = st.sidebar.text_input("Clé API Twelve Data", type="password")
SYMBOLS = st.sidebar.multiselect("Paires", ["EUR/USD", "GBP/USD", "XAU/USD", "BTC/USD", "ETH/USD"], default=["EUR/USD", "XAU/USD", "BTC/USD"])
HTF = st.sidebar.selectbox("Timeframe Supérieur", ["1day", "4h", "1week"])

TIMEFRAME_MAP = {"1week": "4h", "1day": "4h", "4h": "15min"}

def fetch_data(symbol, interval):
    url = f"https://api.twelvedata.com/time_series?symbol={symbol}&interval={interval}&outputsize=900&apikey={API_KEY}"
    try:
        res = requests.get(url).json()
        if "values" not in res: return pd.DataFrame()
        df = pd.DataFrame(res["values"])
        df['datetime'] = pd.to_datetime(df['datetime'])
        df = df.sort_values('datetime').reset_index(drop=True)
        for c in ['open', 'high', 'low', 'close']: df[c] = df[c].astype(float)
        return df
    except: return pd.DataFrame()

def analyze(symbol):
    ltf = TIMEFRAME_MAP.get(HTF, "15min")
    df_htf = fetch_data(symbol, HTF)
    df_ltf = fetch_data(symbol, ltf)

    if df_htf.empty or df_ltf.empty or len(df_htf) < 3:
        return {"Paire": symbol, "Signal": "NEUTRE", "Raison": "Données manquantes"}

    b_prev, b_curr = df_htf.iloc[-2], df_htf.iloc[-1]
    prev_mid = (b_prev['open'] + b_prev['close']) / 2
    
    swept_low = b_curr['low'] < b_prev['low'] and b_curr['close'] > prev_mid and b_curr['close'] > b_curr['open']
    swept_high = b_curr['high'] > b_prev['high'] and b_curr['close'] < prev_mid and b_curr['close'] < b_curr['open']

    df_ltf['EMA200'] = ta.ema(df_ltf['close'], length=200)
    df_ltf['EMA800'] = ta.ema(df_ltf['close'], length=800)
    df_ltf['RSI'] = ta.rsi(df_ltf['close'], length=14)
    df_ltf['Base'] = ta.sma(df_ltf['RSI'], length=14)

    price = df_ltf['close'].iloc[-1]
    e200, e800 = df_ltf['EMA200'].iloc[-1], df_ltf['EMA800'].iloc[-1]
    rsi_c, base_c = df_ltf['RSI'].iloc[-1], df_ltf['Base'].iloc[-1]
    rsi_p, base_p = df_ltf['RSI'].iloc[-2], df_ltf['Base'].iloc[-2]

    ema_bull = price > e200 and price > e800
    ema_bear = price < e200 and price < e800

    rsi_buy = (rsi_p <= base_p and rsi_c >= base_c) or ((base_c - rsi_c) <= 2.5 and rsi_c < base_c)
    rsi_sell = (rsi_p >= base_p and rsi_c <= base_c) or ((rsi_c - base_c) <= 2.5 and rsi_c > base_c)

    if swept_low and ema_bull and rsi_buy:
        return {"Paire": symbol, "Signal": "🚀 ACHAT", "Prix": price, "EMA": "Support OK", "RSI": f"{rsi_c:.1f}/{base_c:.1f}"}
    elif swept_high and ema_bear and rsi_sell:
        return {"Paire": symbol, "Signal": "🔻 VENTE", "Prix": price, "EMA": "Résistance OK", "RSI": f"{rsi_c:.1f}/{base_c:.1f}"}

    return {"Paire": symbol, "Signal": "NEUTRE", "Raison": "Conditions non alignées"}

if API_KEY:
    if st.button("🔄 Scanner le marché"):
        st.cache_data.clear()
    
    with st.spinner("Analyse en cours..."):
        data = [analyze(s) for s in SYMBOLS]
    
    st.dataframe(pd.DataFrame(data), use_container_width=True)
else:
    st.warning("Insère ta clé Twelve Data dans le menu à gauche pour afficher les résultats.")
