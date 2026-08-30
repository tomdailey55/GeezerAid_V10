#!/usr/bin/env python3
"""Isolated server launcher for GeezerAid V10 — bypasses all shell rc/profile files."""
import os
import sys
import subprocess

# Completely clean environment
env = {
    "PATH": "/Users/tomdailey/.venvs/jeeves-voice/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin",
    "HOME": "/Users/tomdailey",
    "PYTHONDONTWRITEBYTECODE": "1",
    "PYTHONPATH": "",  # BLOCK inherited PYTHONPATH (prevents torch from wrong venv)
    "PYTHONNOUSERSITE": "1",  # Block user site-packages
    "VIRTUAL_ENV": "/Users/tomdailey/.venvs/jeeves-voice",
    "GA_HOST": "0.0.0.0",
    "GA_PORT": "8766",
    "HERMES_GATEWAY": "http://127.0.0.1:8642",
    # GA_MBP_* is the FAST/chat tier — normal Jeeves conversation. Point it at
    # the Gemma 4 31B Q4_K_M now served on Strix :8083 (eval winner, 68%, clean
    # grounding). Revert by restoring GA_MBP_LLAMACPP=http://127.0.0.1:8081.
    "GA_MBP_LLAMACPP": "http://100.103.195.22:8083",
    "GA_MBP_MODEL": "gemma-4-31B-it-Q4_K_M",
    "GA_LOCAL_LLAMACPP": "http://127.0.0.1:8081",
}

os.chdir("/Users/tomdailey/Public/GeezerAid_V10")
os.execve(
    "/Users/tomdailey/.venvs/jeeves-voice/bin/python",
    ["python", "server/server_v10.py"],
    env,
)
