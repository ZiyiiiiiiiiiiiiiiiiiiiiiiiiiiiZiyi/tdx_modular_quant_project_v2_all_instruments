# -*- coding: utf-8 -*-
"""
Install dependencies for Governance ML versions.
Run this script first before using the ML versions.
"""
import subprocess
import sys


def install_package(package_name, import_name=None):
    """Install a package using pip."""
    if import_name is None:
        import_name = package_name
    
    try:
        __import__(import_name)
        print(f"✓ {package_name} already installed")
        return True
    except ImportError:
        print(f"Installing {package_name}...")
        try:
            subprocess.check_call([sys.executable, "-m", "pip", "install", package_name])
            print(f"✓ {package_name} installed successfully")
            return True
        except subprocess.CalledProcessError:
            print(f"✗ Failed to install {package_name}")
            return False


def main():
    print("=" * 60)
    print("Installing dependencies for Governance ML versions")
    print("=" * 60)
    print()
    
    # Check Python version
    print(f"Python version: {sys.version}")
    print(f"Python executable: {sys.executable}")
    print()
    
    # Install packages
    packages = [
        ("lightgbm", "lightgbm"),
        ("numpy", "numpy"),
        ("pandas", "pandas"),
        ("pyarrow", "pyarrow"),
        ("scikit-learn", "sklearn"),
    ]
    
    # Add PyTorch and TabNet for TabNet version
    tabnet_packages = [
        ("torch", "torch"),
        ("pytorch-tabnet", "pytorch_tabnet"),
    ]
    
    print("Installing basic packages...")
    for package, import_name in packages:
        install_package(package, import_name)
    
    print()
    print("Installing TabNet packages (for TabNet and Ensemble versions)...")
    for package, import_name in tabnet_packages:
        install_package(package, import_name)
    
    print()
    print("=" * 60)
    print("Installation complete!")
    print("=" * 60)
    print()
    print("You can now run:")
    print("  1. run_governance_lightgbm.py   - LightGBM only")
    print("  2. run_governance_tabnet.py     - TabNet only")
    print("  3. run_governance_ensemble.py   - LightGBM + TabNet ensemble")
    print()
    
    # Verify installations
    print("Verifying installations...")
    print()
    
    try:
        import lightgbm
        print(f"✓ LightGBM {lightgbm.__version__}")
    except ImportError:
        print("✗ LightGBM not available")
    
    try:
        import torch
        print(f"✓ PyTorch {torch.__version__}")
        print(f"  CUDA available: {torch.cuda.is_available()}")
    except ImportError:
        print("✗ PyTorch not available")
    
    try:
        import pytorch_tabnet
        print(f"✓ pytorch-tabnet installed")
    except ImportError:
        print("✗ pytorch-tabnet not available")
    
    print()


if __name__ == "__main__":
    main()
