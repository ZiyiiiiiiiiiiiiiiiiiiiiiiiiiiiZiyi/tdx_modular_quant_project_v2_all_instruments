# -*- coding: utf-8 -*-
"""
Alpha Bundle Matrix Verification

验证alpha bundle矩阵的正确性：
- 每个bundle的alpha因子是否都已注册
- bundle的blend mode是否有效
- bundle的alpha因子是否支持治理/策略选择
- alpha因子的输入列是否可用
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from functions.alpha_registry import ALPHA_REGISTRY
from functions.alpha_bundles import ALPHA_BUNDLE_REGISTRY


def verify_bundle_registry_completeness() -> list[str]:
    """验证alpha bundle注册中心的完整性"""
    errors = []
    
    for name in ALPHA_BUNDLE_REGISTRY.list_names():
        bundle = ALPHA_BUNDLE_REGISTRY.get(name)
        
        # 检查必填字段
        if not bundle.bundle_name:
            errors.append(f"Bundle '{name}' missing bundle_name")
        if not bundle.alpha_names:
            errors.append(f"Bundle '{name}' has no alpha factors")
        if not bundle.blend_mode:
            errors.append(f"Bundle '{name}' missing blend_mode")
        
        # 检查所有alpha因子是否已注册
        for alpha_name in bundle.alpha_names:
            if alpha_name not in ALPHA_REGISTRY._specs:
                errors.append(f"Bundle '{name}' references unknown alpha '{alpha_name}'")
    
    return errors


def verify_bundle_blend_modes() -> list[str]:
    """验证bundle的blend mode是否有效"""
    errors = []
    valid_blend_modes = {
        "equal_weight", "confidence_weighted", "reputation_weighted",
        "rank_ensemble", "stacked_meta_score"
    }
    
    for name in ALPHA_BUNDLE_REGISTRY.list_names():
        bundle = ALPHA_BUNDLE_REGISTRY.get(name)
        if bundle.blend_mode not in valid_blend_modes:
            errors.append(f"Bundle '{name}' has invalid blend_mode '{bundle.blend_mode}'")
    
    return errors


def verify_bundle_alpha_compatibility() -> list[str]:
    """验证bundle中的alpha因子是否支持治理模式"""
    errors = []
    
    for name in ALPHA_BUNDLE_REGISTRY.list_names():
        bundle = ALPHA_BUNDLE_REGISTRY.get(name)
        
        governance_compatible = []
        strategy_compatible = []
        
        for alpha_name in bundle.alpha_names:
            try:
                spec = ALPHA_REGISTRY.get(alpha_name)
                if spec.supports_governance:
                    governance_compatible.append(alpha_name)
                if spec.supports_strategy_selection:
                    strategy_compatible.append(alpha_name)
            except KeyError:
                pass  # 已在其他验证中报告
        
        # 警告：如果bundle中没有governance兼容的alpha
        if not governance_compatible:
            errors.append(f"Bundle '{name}' has no governance-compatible alphas")
    
    return errors


def verify_bundle_alpha_status() -> list[str]:
    """验证bundle中的alpha因子状态"""
    errors = []
    
    for name in ALPHA_BUNDLE_REGISTRY.list_names():
        bundle = ALPHA_BUNDLE_REGISTRY.get(name)
        
        deprecated_alphas = []
        disabled_alphas = []
        
        for alpha_name in bundle.alpha_names:
            try:
                spec = ALPHA_REGISTRY.get(alpha_name)
                if spec.status == "deprecated":
                    deprecated_alphas.append(alpha_name)
                elif spec.status == "disabled":
                    disabled_alphas.append(alpha_name)
            except KeyError:
                pass
        
        if deprecated_alphas:
            errors.append(f"Bundle '{name}' contains deprecated alphas: {deprecated_alphas}")
        if disabled_alphas:
            errors.append(f"Bundle '{name}' contains disabled alphas: {disabled_alphas}")
    
    return errors


def verify_bundle_score_columns() -> list[str]:
    """验证bundle中的alpha因子score列名"""
    errors = []
    
    for name in ALPHA_BUNDLE_REGISTRY.list_names():
        bundle = ALPHA_BUNDLE_REGISTRY.get(name)
        
        for alpha_name in bundle.alpha_names:
            try:
                spec = ALPHA_REGISTRY.get(alpha_name)
                if not spec.score_column:
                    errors.append(f"Alpha '{alpha_name}' in bundle '{name}' missing score_column")
            except KeyError:
                pass
    
    return errors


def verify_all() -> dict[str, list[str]]:
    """运行所有验证"""
    results = {}
    
    print("\n=== Alpha Bundle Matrix Verification ===\n")
    
    # 1. 注册中心完整性
    print("1. Verifying registry completeness...")
    results["registry_completeness"] = verify_bundle_registry_completeness()
    
    # 2. Blend mode验证
    print("2. Verifying blend modes...")
    results["blend_modes"] = verify_bundle_blend_modes()
    
    # 3. Alpha兼容性
    print("3. Verifying alpha compatibility...")
    results["alpha_compatibility"] = verify_bundle_alpha_compatibility()
    
    # 4. Alpha状态
    print("4. Verifying alpha status...")
    results["alpha_status"] = verify_bundle_alpha_status()
    
    # 5. Score列名
    print("5. Verifying score columns...")
    results["score_columns"] = verify_bundle_score_columns()
    
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
        print("All alpha bundle matrix verifications PASSED!")
    
    return results


if __name__ == "__main__":
    results = verify_all()
    sys.exit(1 if any(results.values()) else 0)
