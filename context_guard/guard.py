#!/usr/bin/env python3
"""Context Guard middleware — shim entrypoint.

Preserva la invocación original:
    python3 guard.py <command> --context <ctx> [options]

Delega todo al package guard/.
"""
import sys
import os

from context_guard.guard.cli import main

main()