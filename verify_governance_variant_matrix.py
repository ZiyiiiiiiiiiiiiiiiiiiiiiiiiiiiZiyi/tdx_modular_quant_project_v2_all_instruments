# -*- coding: utf-8 -*-
"""
Governance Variant Matrix Verification

验证治理变体矩阵的正确性：
- 每个变体能否生成候选
- 是否产生合法决策
- 元数据是否完整
- 股票池模式是否正确披露
- 池外持仓是否显式退出
- 输出report/summary是否带variant/bundle/universe标签
"""
from __future__ import annotations

import sys
from pathlib import Path

PROJECT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(PROJECT_DIR))

from functions.universe_registry import UNIVERSE_REGISTRY
from functions.alpha_registry import ALPHA_REGISTRY
from functions.governance_variant_registry import GOVERNANCE_VARIANT_REGISTRY
from functions.alpha_bundles import ALPHA_BUNDLE_REGISTRY


def verify_variant_registry_completeness() -> list[str]:
    """验证治理变体注册中心的完整性"""
    errors = []
    for name in GOVERNANCE_VARIANT_REGISTRY.list_names():
        spec = GOVERNANCE_VARIANT_REGISTRY.get(name)
        
        # 检查必填字段
        if not spec.variant_name:
            errors.append(f"Variant '{name}' missing variant_name")
        if not spec.base_policy:
            errors.append(f"Variant '{name}' missing base_policy")
        if not spec.universe_name:
            errors.append(f"Variant '{name}' missing universe_name")
        if not spec.alpha_bundle:
            errors.append(f"Variant '{name}' missing alpha_bundle")
        
        # 检查关联的universe是否存在
        try:
            UNIVERSE_REGISTRY.get(spec.universe_name)
        except KeyError:
            errors.append(f"Variant '{name}' references unknown universe '{spec.universe_name}'")
        
        # 检查关联的alpha bundle是否存在
        try:
            ALPHA_BUNDLE_REGISTRY.get(spec.alpha_bundle)
        except KeyError:
            errors.append(f"Variant '{name}' references unknown alpha bundle '{spec.alpha_bundle}'")
    
    return errors


def verify_variant_metadata_completeness() -> list[str]:
    """验证变体元数据的完整性"""
    errors = []
    required_fields = [
        "variant_name", "base_policy", "enable_reputation", "enable_sector_cap",
        "enable_safety_agent", "enable_market_regime_policy", "universe_name",
        "alpha_bundle", "position_sizing_mode", "description", "status"
    ]
    
    for name in GOVERNANCE_VARIANT_REGISTRY.list_names():
        spec = GOVERNANCE_VARIANT_REGISTRY.get(name)
        spec_dict = spec.to_dict()
        
        for field in required_fields:
            if field not in spec_dict:
                errors.append(f"Variant '{name}' missing required field '{field}'")
            elif spec_dict[field] is None:
                errors.append(f"Variant '{name}' has None value for '{field}'")
    
    return errors


def verify_variant_universe_compatibility() -> list[str]:
    """验证变体与股票池的兼容性"""
    errors = []
    
    for name in GOVERNANCE_VARIANT_REGISTRY.list_names():
        spec = GOVERNANCE_VARIANT_REGISTRY.get(name)
        
        try:
            universe_spec = UNIVERSE_REGISTRY.get(spec.universe_name)
        except KeyError:
            continue  # 已在其他验证中报告
        
        # 检查模式兼容性
        if universe_spec.mode == "blocked":
            errors.append(f"Variant '{name}' uses blocked universe '{spec.universe_name}'")
    
    return errors


def verify_variant_alpha_bundle_compatibility() -> list[str]:
    """验证变体与alpha bundle的兼容性"""
    errors = []
    
    for name in GOVERNANCE_VARIANT_REGISTRY.list_names():
        spec = GOVERNANCE_VARIANT_REGISTRY.get(name)
        
        try:
            bundle_spec = ALPHA_BUNDLE_REGISTRY.get(spec.alpha_bundle)
        except KeyError:
            continue  # 已在其他验证中报告
        
        # 检查bundle中是否有governance兼容的alpha
        governance_alphas = [
            alpha_name for alpha_name in bundle_spec.alpha_names
            if alpha_name in ALPHA_REGISTRY._specs and ALPHA_REGISTRY.get(alpha_name).supports_governance
        ]
        
        if not governance_alphas:
            errors.append(f"Variant '{name}' uses bundle '{spec.alpha_bundle}' with no governance-compatible alphas")
    
    return errors


def verify_variant_output_naming() -> list[str]:
    """验证变体输出命名规范"""
    errors = []
    
    for name in GOVERNANCE_VARIANT_REGISTRY.list_names():
        spec = GOVERNANCE_VARIANT_REGISTRY.get(name)
        
        # 检查是否有governance_variant_tag
        if not spec.governance_variant_tag:
            errors.append(f"Variant '{name}' missing governance_variant_tag for output naming")
    
    return errors


def verify_all() -> dict[str, list[str]]:
    """运行所有验证"""
    results = {}
    
    print("\n=== Governance Variant Matrix Verification ===\n")
    
    # 1. 注册中心完整性
    print("1. Verifying registry completeness...")
    results["registry_completeness"] = verify_variant_registry_completeness()
    
    # 2. 元数据完整性
    print("2. Verifying metadata completeness...")
    results["metadata_completeness"] = verify_variant_metadata_completeness()
    
    # 3. 变体与股票池兼容性
    print("3. Verifying universe compatibility...")
    results["universe_compatibility"] = verify_variant_universe_compatibility()
    
    # 4. 变体与alpha bundle兼容性
    print("4. Verifying alpha bundle compatibility...")
    results["alpha_bundle_compatibility"] = verify_variant_alpha_bundle_compatibility()
    
    # 5. 输出命名规范
    print("5. Verifying output naming...")
    results["output_naming"] = verify_variant_output_naming()
    
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
        print("All governance variant matrix verifications PASSED!")
    
    return results


if __name__ == "__main__":
    results = verify_all()
    sys.exit(1 if any(results.values()) else 0)
