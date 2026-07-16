import pandas as pd


def atr(df, period=14):
    previous = df.close.shift(1)
    tr = pd.concat([(df.high-df.low), (df.high-previous).abs(), (df.low-previous).abs()], axis=1).max(axis=1)
    return tr.ewm(alpha=1/period, adjust=False, min_periods=period).mean()


def adx(df, period=14):
    up, down = df.high.diff(), -df.low.diff()
    plus_dm = up.where((up > down) & (up > 0), 0.0)
    minus_dm = down.where((down > up) & (down > 0), 0.0)
    tr = atr(df, period)
    plus = 100 * plus_dm.ewm(alpha=1/period, adjust=False, min_periods=period).mean() / tr
    minus = 100 * minus_dm.ewm(alpha=1/period, adjust=False, min_periods=period).mean() / tr
    dx = 100 * (plus-minus).abs() / (plus+minus)
    return dx.ewm(alpha=1/period, adjust=False, min_periods=period).mean()


def rsi(close, period=14):
    delta = close.diff(); gain = delta.clip(lower=0); loss = -delta.clip(upper=0)
    rs = gain.ewm(alpha=1/period, adjust=False, min_periods=period).mean() / loss.ewm(alpha=1/period, adjust=False, min_periods=period).mean()
    return 100 - 100/(1+rs)
