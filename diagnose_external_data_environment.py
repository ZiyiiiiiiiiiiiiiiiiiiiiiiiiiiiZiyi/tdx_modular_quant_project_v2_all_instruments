# -*- coding: utf-8 -*-
"""Classify external-data failures as missing dependency or likely network/VPN issues."""
from __future__ import annotations

import argparse
import importlib.util
import socket

from config import (
    EXTERNAL_DIAGNOSIS_DEPENDENCIES,
    EXTERNAL_DIAGNOSIS_HOSTS,
    EXTERNAL_DIAGNOSIS_SOCKET_TIMEOUT_SECONDS,
    EXTERNAL_DIAGNOSIS_TCP_ENDPOINTS,
)

DEPENDENCIES = EXTERNAL_DIAGNOSIS_DEPENDENCIES
HOSTS = EXTERNAL_DIAGNOSIS_HOSTS
TCP_ENDPOINTS = EXTERNAL_DIAGNOSIS_TCP_ENDPOINTS


def diagnose():
    failures = []
    print("=== External data environment diagnosis ===")
    for package in DEPENDENCIES:
        installed = importlib.util.find_spec(package) is not None
        print(f"{package}: {'installed' if installed else 'missing'}")
        if not installed:
            failures.append(f"MISSING_DEPENDENCY:{package}")
    for host in HOSTS:
        try:
            address = socket.gethostbyname(host)
            print(f"{host}: DNS_OK {address}")
        except OSError as exc:
            print(f"{host}: DNS_FAILED {type(exc).__name__}: {exc}")
            failures.append(f"NETWORK_OR_VPN_DNS:{host}")
    for host, port in TCP_ENDPOINTS:
        try:
            with socket.create_connection(
                (host, port),
                timeout=EXTERNAL_DIAGNOSIS_SOCKET_TIMEOUT_SECONDS,
            ):
                print(f"{host}:{port}: TCP_OK")
        except OSError as exc:
            print(f"{host}:{port}: TCP_FAILED {type(exc).__name__}: {exc}")
            failures.append(f"NETWORK_OR_VPN_TCP:{host}:{port}")
    print("Diagnosis codes:", failures or ["OK"])
    return failures


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--require-network", action="store_true")
    args = parser.parse_args()
    issues = diagnose()
    if args.require_network and issues:
        raise SystemExit(1)
