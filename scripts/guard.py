#!/usr/bin/env python3
"""Context Guard middleware — shim entrypoint.

Preserva la invocación original:
    python3 guard.py <command> --context <ctx> [options]

Delega todo al package guard/.
"""
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from guard.cli import main

main()