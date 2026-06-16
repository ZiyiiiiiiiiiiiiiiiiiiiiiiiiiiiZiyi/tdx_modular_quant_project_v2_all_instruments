# -*- coding: utf-8 -*-
"""
Universe Modes Verification

验证universe模式的正确性：
- 每个universe模式是否有效
- Fallback/Strict/Blocked模式是否正确配置
- 指数代码是否有效
- 质量过滤参数是否合理
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from functions.universe_registry import UNIVERSE_REGISTRY


def verify_universe_registry_completeness() -> list[str]:
    """验证universe注册中心的完整性"""
    errors = []
    
    for name in UNIVERSE_REGISTRY.list_names():
        spec = UNIVERSE_REGISTRY.get(name)
        
        # 检查必填字段
        if not spec.name:
            errors.append(f"Universe '{name}' missing name")
        if not spec.mode:
            errors.append(f"Universe '{name}' missing mode")
        if not spec.description:
            errors.append(f"Universe '{name}' missing description")
    
    return errors


def verify_universe_modes() -> list[str]:
    """验证universe模式是否有效"""
    errors = []
    valid_modes = {"index_pool_strict", "quality_fallback", "blocked", "all_a_share_research"}
    
    for name in UNIVERSE_REGISTRY.list_names():
        spec = UNIVERSE_REGISTRY.get(name)
        if spec.mode not in valid_modes:
            errors.append(f"Universe '{name}' has invalid mode '{spec.mode}'")
    
    return errors


def verify_universe_index_codes() -> list[str]:
    """验证universe的指数代码"""
    errors = []
    
    for name in UNIVERSE_REGISTRY.list_names():
        spec = UNIVERSE_REGISTRY.get(name)
        
        # index_pool_strict模式必须有target_index_codes
        if spec.mode == "index_pool_strict" and not spec.target_index_codes:
            errors.append(f"Universe '{name}' is index_pool_strict but has no target_index_codes")
        
        # 检查指数代码格式
        for code in spec.target_index_codes:
            if not isinstance(code, str) or len(code) != 6:
                errors.append(f"Universe '{name}' has invalid index code '{code}'")
    
    return errors


def verify_universe_fallback_config() -> list[str]:
    """验证universe的fallback配置"""
    errors = []
    
    for name in UNIVERSE_REGISTRY.list_names():
        spec = UNIVERSE_REGISTRY.get(name)
        
        # require_constituents=True且allow_fallback=True是矛盾的
        if spec.require_constituents and spec.allow_fallback:
            errors.append(f"Universe '{name}' has conflicting config: require_constituents=True and allow_fallback=True")
        
        # quality_fallback模式必须设置allow_fallback=True
        if spec.mode == "quality_fallback" and not spec.allow_fallback:
            errors.append(f"Universe '{name}' is quality_fallback but allow_fallback=False")
    
    return errors


def verify_universe_quality_filters() -> list[str]:
    """验证universe的质量过滤参数"""
    errors = []
    
    for name in UNIVERSE_REGISTRY.list_names():
        spec = UNIVERSE_REGISTRY.get(name)
        
        # 检查参数合理性
        if spec.min_history_days < 0:
            errors.append(f"Universe '{name}' has negative min_history_days")
        if spec.min_avg_amount_20 < 0:
            errors.append(f"Universe '{name}' has negative min_avg_amount_20")
        if spec.max_amihud_20 < 0:
            errors.append(f"Universe '{name}' has negative max_amihud_20")
        if spec.abnormal_return_threshold < 0 or spec.abnormal_return_threshold > 1:
            errors.append(f"Universe '{name}' has invalid abnormal_return_threshold")
    
    return errors


def verify_universe_instrument_types() -> list[str]:
    """验证universe的instrument类型"""
    errors = []
    valid_types = {"stock", "etf_fund", "index", "bond", "convertible_bond", "b_share", "unknown"}
    
    for name in UNIVERSE_REGISTRY.list_names():
        spec = UNIVERSE_REGISTRY.get(name)
        
        for inst_type in spec.allowed_instrument_types:
            if inst_type not in valid_types:
                errors.append(f"Universe '{name}' has invalid instrument type '{inst_type}'")
    
    return errors


def verify_all() -> dict[str, list[str]]:
    """运行所有验证"""
    results = {}
    
    print("\n=== Universe Modes Verification ===\n")
    
    # 1. 注册中心完整性
    print("1. Verifying registry completeness...")
    results["registry_completeness"] = verify_universe_registry_completeness()
    
    # 2. 模式验证
    print("2. Verifying universe modes...")
    results["modes"] = verify_universe_modes()
    
    # 3. 指数代码
    print("3. Verifying index codes...")
    results["index_codes"] = verify_universe_index_codes()
    
    # 4. Fallback配置
    print("4. Verifying fallback config...")
    results["fallback_config"] = verify_universe_fallback_config()
    
    # 5. 质量过滤参数
    print("5. Verifying quality filters...")
    results["quality_filters"] = verify_universe_quality_filters()
    
    # 6. Instrument类型
    print("6. Verifying instrument types...")
    results["instrument_types"] = verify_universe_instrument_types()
    
    # 打印结果
    print("\n=== Results ===")
    total_errors = 0
    for check_name, errors in results.items():
        if errors:
            print(f"\n{check_name}: {len(errors)} error(s)")
            for error in errors:
                print(f"  - {error}")
            total_errors += len(errors)
        else:
            print(f"\n{check_name}: PASSED")
    
    print("\n=== Summary ===")
    print(f"Total errors: {total_errors}")
    if total_errors == 0:
        print("All universe modes verifications PASSED!")
    
    return results


if __name__ == "__main__":
    results = verify_all()
    sys.exit(1 if any(results.values()) else 0)
