from .base import Action, Signal, Strategy
from .indicators import adx, atr


class EmaAdxTrend(Strategy):
    strategy_id = "ema_adx_trend"
    def __init__(self, fast=12, slow=26, adx_period=14, adx_threshold=25, atr_multiple=1.5, reward_risk=2):
        self.fast, self.slow, self.adx_period = fast, slow, adx_period
        self.adx_threshold, self.atr_multiple, self.reward_risk = adx_threshold, atr_multiple, reward_risk
    def generate(self, df):
        if len(df) < max(self.slow+2, self.adx_period*2+2): return Signal(Action.HOLD, 0, "insufficient history")
        fast=df.close.ewm(span=self.fast,adjust=False).mean(); slow=df.close.ewm(span=self.slow,adjust=False).mean()
        strength=adx(df,self.adx_period).iloc[-1]; volatility=atr(df,self.adx_period).iloc[-1]; price=float(df.close.iloc[-1])
        if fast.iloc[-2] <= slow.iloc[-2] and fast.iloc[-1] > slow.iloc[-1] and strength >= self.adx_threshold:
            confidence=min(1.0, .5 + (strength-self.adx_threshold)/50)
            stop=price-self.atr_multiple*volatility
            return Signal(Action.BUY, confidence, "bullish EMA crossover with ADX trend strength", stop, price+(price-stop)*self.reward_risk)
        if fast.iloc[-2] >= slow.iloc[-2] and fast.iloc[-1] < slow.iloc[-1]: return Signal(Action.SELL, min(1,strength/50), "bearish EMA crossover")
        return Signal(Action.HOLD, 0, "no qualified EMA/ADX setup")
