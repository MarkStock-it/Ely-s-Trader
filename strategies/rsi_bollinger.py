from .base import Action, Signal, Strategy
from .indicators import atr, rsi


class RsiBollingerMeanReversion(Strategy):
    strategy_id = "rsi_bollinger_mean_reversion"
    def __init__(self, period=20, rsi_period=14, oversold=30, exit_rsi=55, deviations=2, atr_multiple=1.5):
        self.period,self.rsi_period,self.oversold,self.exit_rsi,self.deviations,self.atr_multiple=period,rsi_period,oversold,exit_rsi,deviations,atr_multiple
    def generate(self, df):
        if len(df)<max(self.period,self.rsi_period)+2:return Signal(Action.HOLD,0,"insufficient history")
        mid=df.close.rolling(self.period).mean(); std=df.close.rolling(self.period).std(); lower=mid-self.deviations*std
        momentum=rsi(df.close,self.rsi_period); price=float(df.close.iloc[-1]); volatility=atr(df,self.rsi_period).iloc[-1]
        if price < lower.iloc[-1] and momentum.iloc[-1] <= self.oversold:
            confidence=min(1,.5+(self.oversold-momentum.iloc[-1])/40)
            return Signal(Action.BUY,confidence,"oversold RSI below lower Bollinger band",price-self.atr_multiple*volatility,float(mid.iloc[-1]))
        if price >= mid.iloc[-1] or momentum.iloc[-1]>=self.exit_rsi:return Signal(Action.SELL,.6,"mean reverted to Bollinger midline or RSI exit")
        return Signal(Action.HOLD,0,"no mean-reversion setup")
