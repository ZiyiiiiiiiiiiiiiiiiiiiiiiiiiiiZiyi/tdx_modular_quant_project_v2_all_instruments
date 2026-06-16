# -*- coding: utf-8 -*-
"""
Universe Registry - 股票池注册中心

职责：
- 注册不同股票池模式（universe spec）
- 提供统一接口查询、切换股票池
- 分离"定义"与"执行"：本文件只负责定义，investable_universe.py负责执行

Universe Spec 字段：
- name: 唯一标识符
- mode: universe模式 (index_pool_strict / quality_fallback / blocked / all_a_share_research)
- require_constituents: 是否强制要求成分股数据
- allow_fallback: 是否允许降级到quality_fallback
- target_index_codes: 目标指数代码列表
- quality_filter_enabled: 是否启用质量过滤
- description: 描述
- status: 状态 (active / experimental / deprecated)
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class UniverseSpec:
    """股票池规格定义"""
    name: str
    mode: str
    require_constituents: bool
    allow_fallback: bool
    target_index_codes: list[str]
    quality_filter_enabled: bool
    description: str
    status: str = "active"
    # 扩展字段
    min_history_days: int = 120
    min_avg_amount_20: float = 10_000_000.0
    max_amihud_20: float = 5e-8
    abnormal_return_threshold: float = 0.11
    require_adjustment: bool = False
    allowed_instrument_types: tuple[str, ...] = ("stock",)
    extra: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """转换为字典，用于序列化"""
        return {
            "name": self.name,
            "mode": self.mode,
            "require_constituents": self.require_constituents,
            "allow_fallback": self.allow_fallback,
            "target_index_codes": self.target_index_codes,
            "quality_filter_enabled": self.quality_filter_enabled,
            "description": self.description,
            "status": self.status,
            "min_history_days": self.min_history_days,
            "min_avg_amount_20": self.min_avg_amount_20,
            "max_amihud_20": self.max_amihud_20,
            "abnormal_return_threshold": self.abnormal_return_threshold,
            "require_adjustment": self.require_adjustment,
            "allowed_instrument_types": list(self.allowed_instrument_types),
            "extra": self.extra,
        }


class UniverseRegistry:
    """股票池注册中心"""

    def __init__(self):
        self._specs: dict[str, UniverseSpec] = {}
        self._register_builtins()

    def _register_builtins(self):
        """注册内置股票池模式"""

        # 1. HS300 + CSI500 + A500 严格模式
        self.register(UniverseSpec(
            name="hs300_csi500_a500_strict",
            mode="index_pool_strict",
            require_constituents=True,
            allow_fallback=False,
            target_index_codes=["000300", "000905", "000510"],
            quality_filter_enabled=True,
            description="沪深300+中证500+中证A500严格股票池，要求成分股数据可用",
            status="active",
        ))

        # 2. HS300 严格模式
        self.register(UniverseSpec(
            name="hs300_strict",
            mode="index_pool_strict",
            require_constituents=True,
            allow_fallback=False,
            target_index_codes=["000300"],
            quality_filter_enabled=True,
            description="沪深300严格股票池",
            status="active",
        ))

        # 3. CSI500 严格模式
        self.register(UniverseSpec(
            name="csi500_strict",
            mode="index_pool_strict",
            require_constituents=True,
            allow_fallback=False,
            target_index_codes=["000905"],
            quality_filter_enabled=True,
            description="中证500严格股票池",
            status="active",
        ))

        # 4. A500 严格模式
        self.register(UniverseSpec(
            name="a500_strict",
            mode="index_pool_strict",
            require_constituents=True,
            allow_fallback=False,
            target_index_codes=["000510"],
            quality_filter_enabled=True,
            description="中证A500严格股票池",
            status="active",
        ))

        # 5. Quality Fallback 模式（成分股缺失时降级到质量过滤）
        self.register(UniverseSpec(
            name="quality_fallback",
            mode="quality_fallback",
            require_constituents=False,
            allow_fallback=True,
            target_index_codes=["000300", "000905", "000510"],
            quality_filter_enabled=True,
            description="质量降级模式：成分股数据缺失时使用质量过滤替代",
            status="active",
        ))

        # 6. 全A股研究模式（不做成分股约束，仅做质量过滤）
        self.register(UniverseSpec(
            name="all_a_share_research",
            mode="all_a_share_research",
            require_constituents=False,
            allow_fallback=True,
            target_index_codes=[],
            quality_filter_enabled=True,
            description="全A股研究模式：不做成分股约束，仅做基础质量过滤",
            status="experimental",
            allowed_instrument_types=("stock", "etf_fund"),
        ))

        # 7. 自定义指数组合模式
        self.register(UniverseSpec(
            name="custom_index_bundle",
            mode="index_pool_strict",
            require_constituents=True,
            allow_fallback=False,
            target_index_codes=["000300", "000905"],
            quality_filter_enabled=True,
            description="自定义指数组合：默认HS300+CSI500，可通过extra.target_index_codes覆盖",
            status="experimental",
        ))

        # 8. ETF研究模式
        self.register(UniverseSpec(
            name="etf_research",
            mode="all_a_share_research",
            require_constituents=False,
            allow_fallback=True,
            target_index_codes=[],
            quality_filter_enabled=False,
            description="ETF研究模式：包含所有ETF/基金，不做成分股约束",
            status="active",
            allowed_instrument_types=("etf_fund",),
            min_history_days=30,
            min_avg_amount_20=1_000_000.0,
        ))

        # 9. Blocked 模式（用于测试/验证）
        self.register(UniverseSpec(
            name="blocked",
            mode="blocked",
            require_constituents=True,
            allow_fallback=False,
            target_index_codes=[],
            quality_filter_enabled=False,
            description="阻塞模式：成分股数据缺失时直接阻塞，用于测试严格模式",
            status="experimental",
        ))

    def register(self, spec: UniverseSpec) -> None:
        """注册一个股票池规格"""
        if spec.name in self._specs:
            raise ValueError(f"Universe '{spec.name}' already registered")
        self._specs[spec.name] = spec

    def get(self, name: str) -> UniverseSpec:
        """获取股票池规格"""
        if name not in self._specs:
            available = sorted(self._specs.keys())
            raise KeyError(f"Unknown universe '{name}'. Available: {available}")
        return self._specs[name]

    def list_names(self, *, status: str | None = None) -> list[str]:
        """列出所有股票池名称"""
        if status is None:
            return sorted(self._specs.keys())
        return sorted(name for name, spec in self._specs.items() if spec.status == status)

    def list_active(self) -> list[str]:
        """列出所有active状态的股票池"""
        return self.list_names(status="active")

    def list_experimental(self) -> list[str]:
        """列出所有experimental状态的股票池"""
        return self.list_names(status="experimental")

    def to_dataframe(self):
        """转换为DataFrame，用于报告"""
        import pandas as pd
        return pd.DataFrame([spec.to_dict() for spec in self._specs.values()])

    def validate(self) -> list[str]:
        """验证所有注册的股票池"""
        errors = []
        for name, spec in self._specs.items():
            if not spec.name:
                errors.append("Universe spec missing name")
            if spec.mode not in {"index_pool_strict", "quality_fallback", "blocked", "all_a_share_research"}:
                errors.append(f"Universe '{name}' has invalid mode '{spec.mode}'")
            if spec.mode == "index_pool_strict" and not spec.target_index_codes:
                errors.append(f"Universe '{name}' is index_pool_strict but has no target_index_codes")
        return errors


# 全局单例
UNIVERSE_REGISTRY = UniverseRegistry()


def get_universe_spec(name: str) -> UniverseSpec:
    """获取股票池规格（便捷函数）"""
    return UNIVERSE_REGISTRY.get(name)


def list_universe_names(*, status: str | None = None) -> list[str]:
    """列出股票池名称（便捷函数）"""
    return UNIVERSE_REGISTRY.list_names(status=status)


def list_active_universes() -> list[str]:
    """列出active状态的股票池（便捷函数）"""
    return UNIVERSE_REGISTRY.list_active()
