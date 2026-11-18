#!/usr/bin/env python3
"""Compatibility entry point for the canonical ``python -m pytest`` command."""
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main():
    import pytest
    return pytest.main(sys.argv[1:])


if __name__ == '__main__':
    raise SystemExit(main())
