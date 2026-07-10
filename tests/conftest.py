"""Pytest configuration — add repo root to sys.path for all tests."""
import sys
import os

# Ensure repo root is on sys.path so tests can import project modules directly.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
