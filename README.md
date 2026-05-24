# TDX Modular Quant Project V2

This version keeps all local TDX .day instruments by default.

Main change:
- Uses `symbol`, not only `code`.
- `sh000001` and `sz000001` will not be mixed.
- Supports stock, ETF/fund, index, bond, convertible bond, B-share, unknown.

Run:
```python
main.py
```

Edit:
```python
config.py
```

For all instruments:
```python
READ_LIMIT = None
```

If you only want beginner-tradable instruments:
```python
INCLUDE_INSTRUMENT_TYPES = ("stock", "etf_fund", "convertible_bond")
```

Note:
- Index is not directly tradable, but useful as benchmark.
- Unknown files are kept by default for exploration.
