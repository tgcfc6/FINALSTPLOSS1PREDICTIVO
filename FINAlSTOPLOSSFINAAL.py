#!/usr/bin/env python3
# GitHub

import sys
import random
import string
import time
import ccxt
import requests
import pandas as pd
import pandas_ta as ta
import numpy as np
from datetime import datetime
from binance.client import Client
from math import floor

# --------------------------------------------------------------------------------
# Configuración global
# --------------------------------------------------------------------------------
EPSILON_PENDIENTE = 0.005      # Umbral para considerar pendiente verdaderamente bajista

# Restricción de recompra
ultimo_precio_venta = None
tiempo_ultima_venta = 0

# Stop‐Loss predictivo
stop_loss_activado = True
stop_loss_percent = 0.98
precio_stop_loss = None

# Contador señales bajistas predictivas
bajista_consecutivo = 0

# --------------------------------------------------------------------------------
# Clientes Binance / Copy Trading
# --------------------------------------------------------------------------------
API_KEY        = "wNmoR7nXAk2rNR5KjqeeKPfF7sEWeQFCgzjFqSLvMYEsqI3T4LEw4R0Q9TtjhBTV"
API_SECRET     = "EQG2eGIdB4ibN0ua4vlTTqSqlGIvcxK2wsoif5k6Ch0DyLFgnBJ3z6Vv6dvMSZnC"
client         = Client(API_KEY, API_SECRET)

COPY_API_KEY   = "Xb4SIWG5FzQR5fAzTcRigalhughRm5u3uovVCWSidOIcMzpV78KXXO7hezrY53Hq"
COPY_API_SECRET= "yBbmeWOjc70SbGwNYcNuspnUw5gMfe7uIKmd9eO1N5EvIejhLz0x4W9ezci0RXqT"
client_lead    = Client(COPY_API_KEY, COPY_API_SECRET)

# --------------------------------------------------------------------------------
# Utilidades
# --------------------------------------------------------------------------------
def ajustar_cantidad(cantidad, step_size):
    return floor(cantidad / step_size) * step_size

# --------------------------------------------------------------------------------
# Funciones de Trading
# --------------------------------------------------------------------------------
def comprar_btc() -> bool:
    """
    Compra BTC con todo el saldo USDT.
    Devuelve True si compra, False si se bloquea o falla.
    """
    global ultimo_precio_venta, tiempo_ultima_venta, precio_stop_loss

    # Restricción de recompra
    if ultimo_precio_venta and time.time() - tiempo_ultima_venta < 1200:
        precio_actual = float(client.get_symbol_ticker(symbol="BTCUSDT")["price"])
        if precio_actual > ultimo_precio_venta:
            print("[RECOMPRA] Bloqueada, mantengo USDT")
            return False

    usdt_balance = float(client.get_asset_balance(asset="USDT")["free"])
    if usdt_balance <= 0:
        print("[COMPRA] Saldo USDT insuficiente")
        return False

    symbol = "BTCUSDT"
    precio = float(client.get_symbol_ticker(symbol=symbol)["price"])
    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Comprando BTC a {precio:.2f} USDT")

    # Guardar stop‐loss
    if stop_loss_activado:
        precio_stop_loss = precio * stop_loss_percent
        print(f"[STOP-LOSS] Activado: venderé si baja de {precio_stop_loss:.2f} USDT")

    # Calcular cantidad
    info = client.get_symbol_info(symbol)
    for f in info["filters"]:
        if f["filterType"] == "LOT_SIZE":
            min_qty, step_size = float(f["minQty"]), float(f["stepSize"])
            break

    qty = ajustar_cantidad(usdt_balance / precio, step_size)
    qty = round(qty, 6)
    if qty < min_qty:
        print(f"[COMPRA] qty {qty} < mínimo {min_qty}")
        return False

    # Ejecutar órdenes
    try:
        order = client.order_market_buy(symbol=symbol, quantity=qty)
        print("[Spot] Orden ejecutada:", order)
    except Exception as e:
        print("[Spot] Error compra:", e)
        return False

    try:
        order2 = client_lead.order_market_buy(symbol=symbol, quantity=qty)
        print("[Lead] Orden ejecutada:", order2)
    except Exception as e:
        print("[Lead] Error copy trading:", e)

    return True

def vender_btc():
    """
    Vende todo el BTC disponible.
    """
    global ultimo_precio_venta, tiempo_ultima_venta, precio_stop_loss

    symbol = "BTCUSDT"
    btc_balance = float(client.get_asset_balance(asset="BTC")["free"])
    if btc_balance <= 0:
        print("[VENTA] No hay BTC para vender")
        return

    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] Vendiendo BTC ({btc_balance:.6f})")

    # Cantidad permitida
    info = client.get_symbol_info(symbol)
    for f in info["filters"]:
        if f["filterType"] == "LOT_SIZE":
            min_qty, step_size = float(f["minQty"]), float(f["stepSize"])
            break

    qty = ajustar_cantidad(btc_balance, step_size)
    qty = round(qty, 6)
    if qty < min_qty:
        print(f"[VENTA] qty {qty} < mínimo {min_qty}")
        return

    # Ejecutar órdenes
    try:
        order = client.order_market_sell(symbol=symbol, quantity=qty)
        print("[Spot] Venta ejecutada:", order)
    except Exception as e:
        print("[Spot] Error venta:", e)

    try:
        lead_btc = float(client_lead.get_asset_balance(asset="BTC")["free"])
        qty2 = round(ajustar_cantidad(lead_btc, step_size), 6)
        if qty2 >= min_qty:
            order2 = client_lead.order_market_sell(symbol=symbol, quantity=qty2)
            print("[Lead] Venta ejecutada:", order2)
    except Exception as e:
        print("[Lead] Error venta copy:", e)

    # Actualizar restricción y limpiar stop‐loss
    ultimo_precio_venta = float(client.get_symbol_ticker(symbol=symbol)["price"])
    tiempo_ultima_venta = time.time()
    precio_stop_loss = None

# --------------------------------------------------------------------------------
# Funciones de Precio e Indicadores
# --------------------------------------------------------------------------------
def obtener_precio_bitcoin():
    try:
        return ccxt.binance().fetch_ticker('BTC/USDT')['last']
    except:
        return None

def obtener_indicadores(exchange, symbol='BTC/USDT', timeframe='1m', limit=60):
    ohlcv = exchange.fetch_ohlcv(symbol, timeframe=timeframe, limit=limit)
    df = pd.DataFrame(ohlcv, columns=['timestamp','open','high','low','close','volume'])
    df['timestamp'] = pd.to_datetime(df['timestamp'], unit='ms')
    if len(df) < 14:
        return None

    df['rsi'] = ta.rsi(df['close'], length=5).fillna(method='bfill')
    macd = ta.macd(df['close'], fast=5, slow=13, signal=4)
    df['macd']        = macd['MACD_5_13_4'].fillna(method='bfill')
    df['macd_signal'] = macd['MACDs_5_13_4'].fillna(method='bfill')
    df['adx']         = ta.adx(df['high'], df['low'], df['close'], length=5)['ADX_5'].fillna(method='bfill')

    st = ta.supertrend(df['high'], df['low'], df['close'], length=10, multiplier=3)
    dir_col = next(c for c in st.columns if c.startswith('SUPERTd'))
    df['supertrend_dir'] = st[dir_col].fillna(method='bfill')
    return df

def verificar_tendencia_largo_plazo(exchange):
    df = obtener_indicadores(exchange, timeframe='1h', limit=100)
    if df is None: return False
    df['ma50']  = ta.sma(df['close'], length=50).fillna(method='bfill')
    df['rsi14'] = ta.rsi(df['close'], length=14).fillna(method='bfill')
    return df['close'].iloc[-1] < df['ma50'].iloc[-1] and df['rsi14'].iloc[-1] < 30

def supertrend_bajista(df):
    return df['supertrend_dir'].iloc[-1] == -1

def evitar_caida(df):
    if df is None: return True
    rsi, macd, sig, adx = df['rsi'].iloc[-1], df['macd'].iloc[-1], df['macd_signal'].iloc[-1], df['adx'].iloc[-1]
    if any(pd.isna(v) for v in (rsi, macd, sig, adx)): return True
    if not (30 < rsi < 70): return True
    if macd <= sig: return True
    if adx < 25: return True
    return False

def verificar_tendencia_mediano_plazo(exchange):
    df = obtener_indicadores(exchange, timeframe='15m', limit=60)
    if df is None: return False
    return df['rsi'].iloc[-1] > 50 and df['macd'].iloc[-1] > df['macd_signal'].iloc[-1]

def forecast_pendiente_alcista(exchange):
    ohlcv = exchange.fetch_ohlcv('BTC/USDT', timeframe='1m', limit=180)
    precios = np.array([c[4] for c in ohlcv])
    x = np.arange(len(precios))
    pendiente, _ = np.polyfit(x, precios, 1)
    
    return pendiente > -EPSILON_PENDIENTE

# --------------------------------------------------------------------------------
# Bloque validaciones adicionales
# --------------------------------------------------------------------------------
CRYPTOPANIC_API_TOKEN = "37b99aaaf91a61655f4d64f82d16aeccfe7223b2"
CRYPTOPANIC_ENDPOINT    = f"https://cryptopanic.com/api/v1/posts/?auth_token={CRYPTOPANIC_API_TOKEN}&filter=negative,important"
FEAR_GREED_ENDPOINT      = "https://api.alternative.me/fng/"

def check_noticias_negativas():
    try:
        r = requests.get(CRYPTOPANIC_ENDPOINT, timeout=10).json().get("results",[])
        ahora = datetime.utcnow()
        recientes = [p for p in r if "published_at" in p and (ahora - datetime.fromisoformat(p["published_at"][:-1])).total_seconds() <= 21600]
        return len(recientes) >= 40
    except:
        return False

def check_horarios_preferidos():
    h = datetime.now().hour
    return not (23 <= h < 1)

def check_fear_and_greed():
    try:
        data = requests.get(FEAR_GREED_ENDPOINT, timeout=10).json().get("data",[])
        return int(data[0].get("value","50")) >= 20
    except:
        return True

def check_atr_alto(exchange):
    try:
        o = exchange.fetch_ohlcv('BTC/USDT', timeframe='1h', limit=50)
        df = pd.DataFrame(o, columns=['t','o','h','l','c','v'])
        atr = ta.atr(df['h'], df['l'], df['c'], length=14).iloc[-1]
        return atr > df['c'].iloc[-1] * 0.005
    except:
        return False

def check_volumen_bajo(exchange):
    try:
        o = exchange.fetch_ohlcv('BTC/USDT', timeframe='1h', limit=10)
        df = pd.DataFrame(o, columns=['t','o','h','l','c','v'])
        return df['v'].mean() < 50
    except:
        return False

def check_heikin_ashi(exchange):
    try:
        o = exchange.fetch_ohlcv('BTC/USDT', timeframe='15m', limit=30)
        df = pd.DataFrame(o, columns=['t','o','h','l','c','v'])
        ha = df.copy()
        ha['HA_close'] = (df['o']+df['h']+df['l']+df['c'])/4
        ha['HA_open']  = ha['HA_close'].shift(1).fillna((df['o']+df['c'])/2)
        ha['HA_high']  = ha[['HA_open','HA_close','h']].max(axis=1)
        ha['HA_low']   = ha[['HA_open','HA_close','l']].min(axis=1)
        last3 = ha.tail(3)
        return all(last3['HA_close'] > last3['HA_open'])
    except:
        return True

def check_rsi_multiple_timeframes(exchange):
    for tf in ['5m','15m','1h']:
        try:
            df = pd.DataFrame(exchange.fetch_ohlcv('BTC/USDT', timeframe=tf, limit=30),
                              columns=['t','o','h','l','c','v'])
            if ta.rsi(df['c'], length=14).iloc[-1] < 40:
                return False
        except:
            return False
    return True

def check_binance_24h_ticker():
    try:
        pct = float(requests.get("https://api.binance.com/api/v3/ticker/24hr?symbol=BTCUSDT", timeout=10).json()["priceChangePercent"])
        return abs(pct) <= 10
    except:
        return True

def validacion_adicional(exchange):
    return (not check_noticias_negativas() and
            check_horarios_preferidos() and
            check_fear_and_greed() and
            not check_atr_alto(exchange) and
            not check_volumen_bajo(exchange) and
            check_heikin_ashi(exchange) and
            check_rsi_multiple_timeframes(exchange) and
            check_binance_24h_ticker())

# --------------------------------------------------------------------------------
# Bucle principal
# --------------------------------------------------------------------------------
def main():
    global bajista_consecutivo
    exchange = ccxt.binance()

    # Inicializar
    precio0 = None
    while precio0 is None:
        precio0 = obtener_precio_bitcoin()
        time.sleep(5)

    en_dolares = True
    ultima_op = time.time() - 1
    compra_realizada = False
    bajista_consecutivo = 0

    while True:
        try:
            precio = obtener_precio_bitcoin()
            if precio is None:
                time.sleep(0.2)
                continue

            df = obtener_indicadores(exchange)
            if df is None:
                time.sleep(5)
                continue

            variacion = (precio - precio0) / precio0 * 100
            largo_ok   = not verificar_tendencia_largo_plazo(exchange)
            super_ok   = not supertrend_bajista(df)
            mediano_ok = verificar_tendencia_mediano_plazo(exchange)
            forecast_ok= forecast_pendiente_alcista(exchange)

            if en_dolares:
                cond1 = (precio <= precio0 * 0.995 - 0.1) or (time.time() - ultima_op >= 1800 and not evitar_caida(df))
                if cond1 and largo_ok and super_ok and mediano_ok and forecast_ok and validacion_adicional(exchange):
                    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] ** COMPRA BTC a {precio:.2f} **")
                    if comprar_btc():
                        precio0 = precio
                        en_dolares = False
                        ultima_op = time.time()
                        compra_realizada = True

            else:
                # STOP-LOSS predictivo
                if stop_loss_activado:
                    if not forecast_ok:
                        bajista_consecutivo += 1
                    else:
                        bajista_consecutivo = 0

                    if bajista_consecutivo >= 2:
                        print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] ** Forecast bajista confirmado: VENDO **")
                        vender_btc()
                        precio0 = precio
                        en_dolares = True
                        ultima_op = time.time()
                        compra_realizada = False
                        bajista_consecutivo = 0
                        time.sleep(5)
                        continue

                # Venta +0.5%
                if variacion >= 0.5:
                    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] ** VENTA +0.5% a {precio:.2f} **")
                    vender_btc()
                    precio0 = precio
                    en_dolares = True
                    ultima_op = time.time()
                    compra_realizada = False

                # Venta anticipada
                elif not evitar_caida(df) and precio > precio0 * 1.0079:
                    print(f"[{datetime.now():%Y-%m-%d %H:%M:%S}] ** Venta anticipada a {precio:.2f} **")
                    vender_btc()
                    precio0 = precio
                    en_dolares = True
                    ultima_op = time.time()
                    compra_realizada = False

            time.sleep(5)
        except Exception:
            time.sleep(0.2)

if __name__ == "__main__":
    main()

