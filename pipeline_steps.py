# -*- coding: utf-8 -*-
"""Centralized main-pipeline step switches.

Edit this file when you want `main.py` to skip or include whole stages.
Keep parameter tuning in `config.py`; keep step on/off control here.
"""

RUN_STEP_1_CONVERT_TDX = True
RUN_STEP_2_CLEAN_DATA = True
RUN_STEP_3_FEATURES = True
RUN_STEP_4_STRATEGY_SELECTION = True
RUN_STEP_5_VIEW_SELECTION = True
RUN_STEP_6_BACKTEST = True
