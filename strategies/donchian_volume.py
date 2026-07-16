from .base import Action, Signal, Strategy
from .indicators import atr


class DonchianVolumeBreakout(Strategy):
    strategy_id = "donchian_volume_breakout"
    def __init__(self, period=20, exit_period=10, volume_period=20, volume_ratio=1.2, atr_multiple=2):
        self.period,self.exit_period,self.volume_period,self.volume_ratio,self.atr_multiple=period,exit_period,volume_period,volume_ratio,atr_multiple
    def generate(self,df):
        needed=max(self.period,self.volume_period)+2
        if len(df)<needed:return Signal(Action.HOLD,0,"insufficient history")
        # Channels exclude the current candle, preventing self-referential breakout levels.
        upper=df.high.shift(1).rolling(self.period).max(); lower=df.low.shift(1).rolling(self.exit_period).min()
        average_volume=df.volume.shift(1).rolling(self.volume_period).mean(); price=float(df.close.iloc[-1]); vol=float(df.volume.iloc[-1]); volatility=atr(df,14).iloc[-1]
        if price>upper.iloc[-1] and vol>=average_volume.iloc[-1]*self.volume_ratio:
            confidence=min(1,.5+(vol/average_volume.iloc[-1]-self.volume_ratio)/2)
            return Signal(Action.BUY,confidence,"Donchian breakout confirmed by volume",price-self.atr_multiple*volatility,price+3*self.atr_multiple*volatility)
        if price<lower.iloc[-1]:return Signal(Action.SELL,.65,"Donchian exit-channel breakdown")
        return Signal(Action.HOLD,0,"no volume-confirmed breakout")
