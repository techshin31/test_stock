# 지표 계산 전용 (pure functions)

```
strategies/
├── __init__.py
├── indicators/          ← 지표 계산 전용 (pure functions)
│   ├── adx_strategy.py
│   └── obv_strategy.py
├── base/                ← 단일 지표 전략
│   ├── golden_cross.py
│   ├── macd_strategy.py
│   ├── rsi_strategy.py
│   └── bollinger_band.py
└── combined/            ← 조합/메타 전략
    ├── ma_regime_strategy.py
    └── partial_sizing_strategy.py
```