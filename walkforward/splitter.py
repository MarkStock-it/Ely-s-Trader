from dataclasses import dataclass
from typing import Iterator

from backtesting.data_loader import validate_ohlcv
from .models import WalkForwardConfig


@dataclass(frozen=True)
class Window:
    number: int
    train_start: int
    train_end: int
    validation_start: int
    validation_end: int
    test_start: int
    test_end: int

    def slices(self):
        return (slice(self.train_start, self.train_end),
                slice(self.validation_start, self.validation_end),
                slice(self.test_start, self.test_end))


def split_windows(data, config: WalkForwardConfig) -> Iterator[Window]:
    df = validate_ohlcv(data)
    required = config.train_size + config.validation_size + config.test_size
    for number, start in enumerate(range(0, len(df) - required + 1, config.step_size), 1):
        train_end = start + config.train_size
        validation_end = train_end + config.validation_size
        yield Window(number, start, train_end, train_end, validation_end,
                     validation_end, validation_end + config.test_size)
