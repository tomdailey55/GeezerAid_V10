#!/usr/bin/env python3
"""
GeezerAid V10 Server — fast HTTP facade + Hermes-backed smart path
HTTP-based. Keyword intent (fast path). Kokoro TTS. Smart path delegates to
the local Hermes gateway (`hermes serve`) so model selection / fallback /
memory / tools live in Hermes, not here.

FROZEN CLIENT CONTRACT (iOS/iPad unchanged):
  POST /chat  {text: "..."}  ->  {text: "...", audio: "base64...",
                                    intent, tier, latency_ms}
  GET  /health              ->  {ok: true, uptime: N, version: "v10"}

Architecture (see tasks/TASK_SERVER_HERMES_INTEGRATION.md):
  - FAST/HOT path (edge + local 4B voice model): handled in-process, no Hermes.
  - SMART path (reasoning / coding / hermes memory / tools): delegate to the
    persistent local Hermes gateway on 127.0.0.1:9119. If the gateway is down,
    fall back to `hermes chat` subprocess. The reasoner is whatever Hermes is
    running (cloud today; flip Hermes default to local when eval says ready).
  - Strix/Fedora is DEV-ONLY and is NOT in the prod path. No remote routing.
"""

import os, sys, json, time, base64, tempfile, re, subprocess, random, argparse, socket, csv
from http.server import ThreadingHTTPServer, BaseHTTPRequestHandler
from pathlib import Path
from typing import Optional, Tuple, List, Dict, Any
from collections import deque
import threading
import urllib.request


def _extract_bot_reply(out: str) -> str:
    """Extract just Jeeves' final answer from `hermes chat -q` stdout.

    The answer is the LAST non-empty line after stripping ANSI codes and
    known metadata/warning lines. Reasoning blocks and warnings precede it.
    """
    if not out:
        return ""
    # Strip ANSI escape codes
    ansi = re.compile(r"\x1b\[[0-9;]*m")
    out = ansi.sub("", out)
    lines = out.splitlines()
    # Walk from the end: the first non-empty, non-metadata line is the answer
    for ln in reversed(lines):
        s = ln.strip()
        if not s:
            continue
        # Skip warnings / metadata / reasoning borders
        if any(k in s for k in ("Deprecated .env", "TERMINAL_CWD", "Move to config.yaml",
                                "tirith security scanner", "command scanning will use",
                                "remove the old entries", "boot] stripped", "[TTS]",
                                "[ocr]", "[gate]", "[MoA]", "Resume this session",
                                "hermes --resume", "Session:", "session_id:", "Title:",
                                "Duration:", "Messages:", "Query:", "Goodbye")):
            continue
        if s.startswith("┌") or s.startswith("└") or s.startswith("╭") or s.startswith("╰"):
            continue
        return s
    return ""

# ─────────────────────────────────────────────────────────────────────────────
# PYTHONPATH sanitization (durable TTS fix)
# ---------------------------------------------------------------------------
# The Hermes desktop app injects PYTHONPATH pointing into its own agent venv
# (python3.11 site-packages) into the environment of every child process.
# This server runs on python3.12, so that leaked path makes numpy's C-extensions
# fail to import ("No module named 'numpy._core._multiarray_umath'"), which takes
# Kokoro TTS down with it (tts_ready: false) — even though the server's own venv
# has a correct numpy 2.4.6.
#
# Fix: strip any hermes-agent venv paths from PYTHONPATH and sys.path BEFORE any
# third-party import (numpy/kokoro) so the server always uses its own venv's
# packages. This makes TTS self-healing across manual restarts, launchd, and reboots.
#
# UNDO / MODIFY:
#   - To disable this sanitization entirely (e.g. debugging), set env
#     GA_KEEP_PYTHONPATH=1 before launching — the block below becomes a no-op.
#   - To widen/narrow what gets stripped, edit _PYTHONPATH_BLOCKLIST below.
#   - This only affects THIS process's view of the path; it does NOT modify your
#     shell profile, the Hermes app, or any other process.
# ─────────────────────────────────────────────────────────────────────────────
_PYTHONPATH_BLOCKLIST = (
    "/.hermes/hermes-agent",
)
if not os.environ.get("GA_KEEP_PYTHONPATH"):
    _orig_pp = os.environ.get("PYTHONPATH", "")
    if _orig_pp:
        _kept = [p for p in _orig_pp.split(os.pathsep)
                 if not any(b in p for b in _PYTHONPATH_BLOCKLIST)]
        if _kept:
            os.environ["PYTHONPATH"] = os.pathsep.join(_kept)
        else:
            os.environ.pop("PYTHONPATH", None)
    # Also scrub sys.path (already-imported entries) so a leaked numpy isn't found.
    _sys_blocked = [p for p in sys.path
                    if any(b in p for b in _PYTHONPATH_BLOCKLIST)]
    for _p in _sys_blocked:
        sys.path.remove(_p)
    if _sys_blocked:
        print(f"[boot] stripped {len(_sys_blocked)} hermes-agent path(s) from "
              f"PYTHONPATH/sys.path for numpy/kokoro compatibility")

# OCR (camera-read text feature)
try:
    import pytesseract
    from PIL import Image
    import io
    _OCR_READY = True
except Exception as _ocr_err:
    print(f"[ocr] pytesseract/PIL unavailable: {_ocr_err}")
    _OCR_READY = False

# EasyOCR — much better accuracy for real-world photos
try:
    import easyocr
    _EASYOCR_READER = easyocr.Reader(['en'], gpu=False, verbose=False)
    _EASYOCR_READY = True
    print("[ocr] EasyOCR ready (better accuracy on real photos)")
except Exception as _eo_err:
    print(f"[ocr] EasyOCR unavailable: {_eo_err}")
    _EASYOCR_READY = False
    _EASYOCR_READER = None

# GA-specific safety (from V8) + local Strix MoA engine (first hop before Hermes)
try:
    import confirmation_gates as _cg_mod
    _gate = _cg_mod.ConfirmationGate()
except Exception as _cg_err:
    print(f"[gate] confirmation_gates unavailable: {_cg_err}")
    _gate = None

try:
    from moa_engine import MoAEngine as _MoAEngine
    _moa = _MoAEngine()
except Exception as _moa_err:
    print(f"[MoA] engine unavailable: {_moa_err}")
    _moa = None

# ═══════════════════════════════════════════════════════════════════
# OpenAI Privacy Filter — lazy-loaded, used only for frontier tier
# ═══════════════════════════════════════════════════════════════════
_privacy_filter = None   # (tokenizer, model) or None

def _load_privacy_filter():
    """Lazy-load the 1.5B-parameter PII detection model on first frontier query."""
    global _privacy_filter
    if _privacy_filter is not None:
        return _privacy_filter
    try:
        from transformers import AutoTokenizer, AutoModelForTokenClassification
        import torch
        mdl = "openai/privacy-filter"
        # NOTE: openai/privacy-filter is a standard AutoModelForTokenClassification
        # checkpoint — it does NOT ship custom model code. trust_remote_code=True
        # here would silently execute arbitrary remote code at load time. Dropped.
        tok = AutoTokenizer.from_pretrained(mdl)
        model = AutoModelForTokenClassification.from_pretrained(
            mdl, torch_dtype=torch.float16
        )
        model.eval()
        if torch.cuda.is_available():
            model = model.cuda()
        elif torch.backends.mps.is_available():
            model = model.to("mps")
        _privacy_filter = (tok, model)
        print(f"[PrivacyFilter] loaded {mdl}")
        return _privacy_filter
    except Exception as e:
        print(f"[PrivacyFilter] load failed: {e}")
        return None

def _decode_spans(tokenizer, input_ids, predictions, id2label):
    """Decode BIOES tags into coherent redaction spans."""
    tokens = tokenizer.convert_ids_to_tokens(input_ids)
    spans = []
    i = 0
    while i < len(tokens):
        tok = tokens[i]
        pred = int(predictions[i])
        label = id2label.get(pred, "O")
        if label.startswith("B-") or label.startswith("S-"):
            cat = label.split("-")[-1]
            start = i
            # collect contiguous span (B-I*-E or S)
            j = i + 1
            while j < len(tokens):
                nxt_label = id2label.get(int(predictions[j]), "O")
                if nxt_label.startswith("I-") or nxt_label.startswith("E-"):
                    j += 1
                else:
                    break
            spans.append((start, j, cat))
            i = j
        else:
            i += 1
    return spans

def redact_pii(text: str) -> str:
    """Redact PII from text. Returns original if model unavailable."""
    pf = _load_privacy_filter()
    if pf is None:
        return text
    tokenizer, model = pf
    import torch

    # Tokenize with offsets so we can map back to char positions
    enc = tokenizer(text, return_offsets_mapping=True,
                    truncation=True, max_length=128000,
                    return_tensors="pt")
    offsets = enc.pop("offset_mapping")[0].tolist()

    if torch.cuda.is_available() or torch.backends.mps.is_available():
        enc = {k: v.to(model.device) for k, v in enc.items()}

    with torch.no_grad():
        logits = model(**enc).logits[0]

    predictions = torch.argmax(logits, dim=-1).cpu().numpy()
    id2label = model.config.id2label

    spans = _decode_spans(tokenizer, enc["input_ids"][0].cpu().numpy(),
                          predictions, id2label)

    if not spans:
        return text

    cat_map = {
        "private_person":   "PERSON",
        "private_address":  "ADDRESS",
        "private_email":    "EMAIL",
        "private_phone":    "PHONE",
        "private_url":      "URL",
        "private_date":     "DATE",
        "account_number":   "ACCOUNT",
        "secret":           "SECRET",
    }

    # Build redacted text by replacing character spans
    result = list(text)
    for start_tok, end_tok, cat in reversed(spans):
        char_start = offsets[start_tok][0]
        char_end   = offsets[end_tok - 1][1]
        placeholder = f"[REDACTED_{cat_map.get(cat, 'PII')}]"
        result[char_start:char_end] = list(placeholder)
        # pad remaining with empty so indices stay valid
        for k in range(char_start + len(placeholder), char_end):
            result[k] = ""

    return "".join(result)

HOST       = os.getenv("GA_HOST", "0.0.0.0")
PORT       = int(os.getenv("GA_PORT", "8765"))
LOG_FILE   = os.getenv("GA_LOG", str(Path.home() / "Public" / "GA-V9" / "conversations.jsonl"))
TTS_VOICE  = os.getenv("GA_TTS_VOICE", "bm_lewis")
TTS_SPEED  = float(os.getenv("GA_TTS_SPEED", "0.9"))

# Max POST body size (bytes) — guards against unbounded rfile.read() in do_POST.
MAX_BODY_BYTES = int(os.getenv("GA_MAX_BODY", "10485760"))  # 10 MiB (allow for OCR image uploads)

HERMES_USERS = {
    "100.105.38.43": {"name": "Tom", "title": "sir"},
    "100.85.123.9":  {"name": "Tom", "title": "sir"},
}

# Shared vault-trigger keywords — used by BOTH IntentClassifier.classify() and
# ChatHandler._handle_chat() so the two lists can't drift apart.
VAULT_KEYWORDS = (
    "elder brain", "elder-brain", "my notes", "my note", "my notes on", "my memory",
    "my brain", "my files", "my recipes", "my recipe", "my appointments", "my family",
    "my health", "my records", "recipe for", "recipes with", "recipes using",
    "do i have a recipe", "do i have notes", "do i have a note",
    "did i save", "did i write", "what did i save",
    "find my", "show me my",
    "check elder", "check elder brain", "check my", "check my notes", "check my brain", "check my files",
    "from my notes", "from my vault",
    "look up",
)

class KokoroTTS:
    _inst = None
    _ready = False

    def __new__(cls):
        if cls._inst is None:
            cls._inst = super().__new__(cls)
        return cls._inst

    def __init__(self):
        if self._ready:
            return
        print(f"[TTS] Loading Kokoro ({TTS_VOICE}, speed={TTS_SPEED}) ...")
        try:
            from kokoro import KPipeline
            self.pipe = KPipeline(lang_code="a")
            self.voice = TTS_VOICE
            self.speed = TTS_SPEED
            self._ready = True
            print("[TTS] Kokoro ready.")
        except Exception as e:
            print(f"[TTS] error: {e}")
            self.pipe = None

    def generate(self, text: str, voice: Optional[str] = None) -> Optional[bytes]:
        if not self.pipe:
            return None
        try:
            import numpy as np, soundfile as sf, io
            use_voice = voice or self.voice
            chunks = []
            for _, _, audio in self.pipe(text, voice=use_voice, speed=self.speed):
                chunks.append(audio)
            if not chunks:
                return None
            combined = np.concatenate(chunks) if len(chunks) > 1 else chunks[0]
            buf = io.BytesIO()
            sf.write(buf, combined, 24000, format="WAV")
            return buf.getvalue()
        except Exception as e:
            print(f"[TTS] error: {e}")
            return None

class _AppleFallthrough(Exception):
    """Internal signal: not an Apple intent, continue normal chat flow."""
    pass


class IntentClassifier:
    """Hybrid classifier: fast regex for common cases, model fallback for edge cases.
    Training data is logged to JSONL for weekly fine-tuning improvement."""
    
    # Path to store training examples (text, model_prediction, regex_result)
    TRAINING_LOG = os.path.expanduser("~/Public/GA-V9/intent_training_data.jsonl")
    
    # MBP endpoint for model-based classification (fine-tuned Qwen2.5-7B)
    MBP_LLAMACPP = os.getenv("GA_MBP_LLAMACPP", "http://127.0.0.1:8081")
    MBP_MODEL = os.getenv("GA_MBP_MODEL", "qwen")
    # MLX-served Qwen3.5-9B (fine-tuned) — preferred classifier when reachable
    MLX_ENDPOINT = os.getenv("GA_MLX_ENDPOINT", "http://127.0.0.1:8085")
    MLX_MODEL = os.getenv("GA_MLX_MODEL", "unsloth/Qwen3.5-9B")
    
    INTENTS = {
        "light_on":  ["turn on", "light on", "switch on", "lights on", "brighten", "fan on", "turn on the fan"],
        "light_off": ["turn off", "light off", "switch off", "lights off", "darken", "fan off", "turn off the fan"],
        "timer":     ["timer", "set timer", "countdown"],
        "alarm":     ["alarm", "set alarm", "wake me up", "wake me at"],
        "reminder":  ["remind me to", "remind me about", "set a reminder", "don't let me forget", "don't forget", "remind me"],
        "call":      ["call my", "call the", "call someone", "facetime", "phone call", "dial"],
        "message":   ["text my", "text the", "message my", "send a text", "send a message"],
        "contacts":  ["find contact", "look up number", "phone number", "contact info", "what's the number for"],
        "emergency": ["call 911", "emergency", "ambulance", "fire department", "police"],
        "volume_up":   ["volume up", "louder", "turn it up", "increase volume"],
        "volume_down": ["volume down", "quieter", "turn it down", "decrease volume"],
        "brightness_up":   ["brightness up", "brighter", "screen brighter", "increase brightness"],
        "brightness_down": ["brightness down", "dimmer", "screen dimmer", "decrease brightness", "dim", "dim the screen", "dim screen"],
        "flashlight_on":  ["flashlight on", "torch on", "turn on flashlight", "turn on the flashlight", "light on flashlight"],
        "flashlight_off": ["flashlight off", "torch off", "turn off flashlight", "turn off the flashlight", "light off flashlight"],
        "read_text":  ["what does this say", "read this", "read the label", "read this label", "what's on this label", "what does the label say", "read this for me", "what's written here", "what does this paper say", "read the prescription"],
        "weather":   ["forecast", "temperature", "will it rain", "is it going to rain", "sunny today", "cloudy today"],
        "calendar":  ["calendar", "schedule", "appointment", "meeting", "what's on my schedule", "what do i have"],
        "notes":     ["make a note", "take a note", "write a note", "save a note", "add a note",
                      "search my notes", "find my notes", "look at my notes", "my notes",
                      "apple notes", "add to notes", "write this down", "note to self"],
        "joke":      ["joke", "funny", "tell me a joke"],
        "greeting":  ["hello", "hi", "good morning", "good afternoon", "good evening", "howdy", "how are you", "what's up"],
        "thanks":    ["thank", "thanks", "appreciate"],
        "goodbye":   ["bye", "goodbye", "see you", "good night"],
        "time":      ["what time", "current time", "clock"],
        "date":      ["what day", "what date", "today is", "what's the date", "what is the date", "current date"],
        "suggestion_request": [
            "anything good on", "what's new this week", "what's new on netflix",
            "what should i watch", "recommend something", "what do you recommend",
            "anything worth watching", "what's trending", "what's on",
        ],
        "ipad": [
            "on the ipad", "on my ipad", "ipad screen", "the ipad",
            "open the", "open an app", "open app", "go home on the ipad",
            "what's on the ipad", "ipad control", "volume up on ipad",
            "volume down on ipad", "launch the app on the ipad",
        ],
        "hermes_memory": [
            "what did we decide", "what did we say", "what did we agree",
            "remind me about", "what did we discuss", "what was decided",
            "what did hermes say", "what did the assistant say",
            "search my notes", "look up", "find in my notes",
            "what do you know about", "what did we talk about",
            "show me my", "do i have a recipe", "recipe for",
            "my recipe", "my notes about", "my notes on",
            "my saved recipe", "recipe i saved", "recipes i have",
            "check elder brain", "check my notes", "check my recipes",
            "find my", "any recipes", "recipes with", "recipes using",
            "what recipes", "tell me about the recipes",
            "did i save", "did i write", "do i have notes",
            "what did i save", "what did i write",
            "what is in my", "what do i have in my",
            "tell me about my", "what about my",
        ],
        "hermes_tools": [
            "check the server", "is the server running", "server status",
            "run a command", "execute", "check logs", "check the logs",
            "what's on fedora", "what's on the server", "fix the code",
            "patch the file", "edit the file",
        ],
        "reasoning": [
            "solve", "calculate", "prove", "derivative", "integral", "equation",
            "explain why", "why does", "how does it work", "what causes",
            "compare and contrast", "advantages and disadvantages",
            "proof", "theorem", "lemma", "probability", "statistics",
        ],
        "coding": [
            "code", "program", "function", "script", "write a", "implement",
            "debug", "code review", "refactor", "algorithm", "compile",
            "python", "javascript", "sql", "regex", "bash", "shell",
            "git commit", "pull request", "api", "endpoint", "database",
            "class", "method", "variable", "loop", "recursion",
        ],
    }
    TIER_MAP = {
        "light_on": "edge", "light_off": "edge", "timer": "edge",
        "alarm": "edge", "greeting": "edge", "thanks": "edge",
        "goodbye": "edge", "volume_up": "edge", "volume_down": "edge",
        "brightness_up": "edge", "brightness_down": "edge",
        "flashlight_on": "edge", "flashlight_off": "edge",
        "read_text": "camera",
        "weather": "cloud", "joke": "cloud", "chat": "cloud",
        "calendar": "server", "time": "cloud", "date": "cloud",
        "reminder": "server", "call": "server", "message": "server",
        "contacts": "server", "notes": "server", "email": "server", "cast": "server", "lg_tv": "server", "tv_adb": "server", "emergency": "cloud",
        "hermes_memory": "hermes", "hermes_tools": "hermes_tools",
        "suggestion_request": "server",
        "ipad": "server",
        "reasoning": "reasoning", "coding": "coding",
    }
    RESPONSES = {
        "light_on":  "I've turned on the lights, sir.",
        "light_off": "The lights are now off, sir.",
        "timer":     "Very good, sir. The timer has been set.",
        "alarm":     "Very good, sir. The alarm has been set.",
        "greeting":  "Good day, sir. How may I assist?",
        "thanks":    "You are most welcome, sir.",
        "goodbye":   "Very good, sir. Do call if you need anything.",
        "volume_up":   "Volume increased, sir.",
        "volume_down": "Volume decreased, sir.",
        "brightness_up":   "Brightness increased, sir.",
        "brightness_down": "Brightness decreased, sir.",
        "flashlight_on":  "The flashlight is on, sir.",
        "flashlight_off": "The flashlight is off, sir.",
        "read_text":  "Point your camera at the text, sir.",
    }

    def __init__(self):
        # Ensure training log directory exists
        os.makedirs(os.path.dirname(self.TRAINING_LOG), exist_ok=True)

    def _model_classify(self, text: str) -> Tuple[str, str, Optional[str]]:
        """Query the fine-tuned model for intent classification.
        Tries the MLX-served Qwen3.5 first (preferred), falls back to the
        llama.cpp 7B. Returns (intent, tier, canned)."""
        valid_intents = set(self.INTENTS.keys()) | {"time", "date", "chat"}
        # System prompt matches the fine-tune's training format for best results
        prompt = (
            "Classify the user query into exactly ONE of these intents: "
            "time, date, weather, greeting, thanks, goodbye, light_on, light_off, "
            "timer, alarm, reminder, call, message, contacts, emergency, volume_up, "
            "volume_down, brightness_up, brightness_down, flashlight_on, flashlight_off, "
            "read_text, calendar, joke, hermes_memory, hermes_tools, reasoning, coding, chat.\n\n"
            "Respond with ONLY the intent name. No explanation.\n\n"
            f"Query: {text}\nIntent:"
        )
        payload = json.dumps({
            "model": "qwen",
            "messages": [{"role": "user", "content": prompt}],
            "stream": False,
            "max_tokens": 10,
            "temperature": 0.0,
        }).encode()

        # 1. Try MLX-served Qwen3.5 (fine-tuned) — the preferred classifier.
        #    Uses the EXACT training format (system + user messages) for best match.
        mlx_system = (
            "You are Jeeves, a refined British valet assisting Tom. Address him as 'sir'. "
            "Classify the user query into exactly one intent. Valid intents: "
            "time, date, weather, greeting, thanks, goodbye, light_on, light_off, "
            "timer, alarm, reminder, call, message, contacts, emergency, volume_up, "
            "volume_down, brightness_up, brightness_down, flashlight_on, flashlight_off, "
            "read_text, calendar, joke, hermes_memory, hermes_tools, reasoning, coding, chat. "
            "Reply with ONLY the intent name."
        )
        for endpoint, model in ((self.MLX_ENDPOINT, self.MLX_MODEL),
                                (self.MBP_LLAMACPP, self.MBP_MODEL)):
            try:
                if endpoint == self.MLX_ENDPOINT:
                    msgs = [
                        {"role": "system", "content": mlx_system},
                        {"role": "user", "content": text.strip()},
                    ]
                else:
                    msgs = [{"role": "user", "content": prompt}]
                payload = json.dumps({
                    "model": model,
                    "messages": msgs,
                    "stream": False,
                    "max_tokens": 10,
                    "temperature": 0.0,
                }).encode()
                req = urllib.request.Request(
                    f"{endpoint}/v1/chat/completions",
                    data=payload,
                    headers={"Content-Type": "application/json"}, method="POST")
                # MLX 9B inference is minutes-scale on this MBP (18GB multimodal +
                # LoRA; serial queue) — keep the timeout short so GA falls back to
                # the 7B classifier fast instead of stalling every /chat.
                with urllib.request.urlopen(req, timeout=6) as resp:
                    result = json.loads(resp.read())
                model_intent = result["choices"][0]["message"]["content"].strip().lower()
                if model_intent not in valid_intents:
                    model_intent = "chat"
                tier = self.TIER_MAP.get(model_intent, "cloud")
                canned = self.RESPONSES.get(model_intent)
                return model_intent, tier, canned
            except Exception as e:
                print(f"[Intent][model] {endpoint} error: {e}")
                continue
        return "chat", "cloud", None

    def _log_training(self, text: str, regex_intent: str, model_intent: str, used: str, tier: str):
        """Log a training example to JSONL for weekly fine-tuning."""
        try:
            import datetime
            entry = {
                "timestamp": datetime.datetime.now().isoformat(),
                "text": text,
                "regex_intent": regex_intent,
                "model_intent": model_intent,
                "used": used,
                "tier": tier,
            }
            with open(self.TRAINING_LOG, "a") as f:
                f.write(json.dumps(entry) + "\n")
        except Exception:
            pass

    def classify(self, text: str) -> Tuple[str, str, Optional[str]]:
        lo = text.lower().strip()
        
        # Strip common disfluencies/filler words AND punctuation for robust matching
        import re
        clean = re.sub(r'\b(um|uh|hmm|er|ah|like|you know)\b[,\s]*', ' ', lo)
        clean = re.sub(r'[,.;!?]', ' ', clean)
        clean = re.sub(r'\.{2,}', ' ', clean)
        clean = re.sub(r'\s+', ' ', clean).strip()
        
        # === PHASE 1: FAST-PATH REGEX for common, unambiguous queries ===
        # Time / Date: explicit patterns — zero latency, no false positives
        if re.search(r'\bwhat\s+time\s+(is\s+it|now)\b', lo):
            return "time", "cloud", None
        if re.search(r'what\s+is\s+the\s+(time|current\s+time)', lo):
            return "time", "cloud", None
        if re.search(r'\b(current\s+time|time\s+is\s+it|time\s+now)\b', lo):
            return "time", "cloud", None
        if re.search(r'\bwhat\s+(day|date)\s+(is\s+it|today|now)\b', lo):
            return "date", "cloud", None
        # Weather: only trigger when it's clearly a weather query
        if re.search(r'\b(what\s+(is\s+the\s+)?weather|how\s+(is\s+the\s+)?weather|what\'s\s+the\s+weather|how\'s\s+the\s+weather|weather\s+forecast|forecast\s+for|temperature\s+(is\s+it|will\s+it|was))\b', lo):
            return "weather", "cloud", None
        if re.search(r'\b(will\s+it\s+rain|is\s+it\s+going\s+to\s+rain|rain\s+today|rain\s+tomorrow|sunny\s+today|cloudy\s+today|windy\s+today|snow\s+today|foggy\s+today)\b', lo):
            return "weather", "cloud", None
        if re.search(r'\bhow\s+(hot|cold|warm|chilly)\s+(is\s+it|will\s+it\s+be)\b', lo):
            return "weather", "cloud", None
        
        # === PHASE 2: PHRASE MATCH for known command intents ===
        # Apple native fast-paths — MUST run BEFORE vault-keyword and phrase
        # matching so "what's on" (suggestion), "my notes" (vault) and
        # "remind" collisions can't hijack them.
        if re.search(r"\b(?:what's|what is|what do i have|whats)\s+on\s+(?:my\s+)?calendar\b", lo):
            return "calendar", "server", None
        if re.search(r"\b(?:calendar|appointment|meeting)\b", lo) and re.search(
                r"\b(?:what|any|today|tomorrow|week|next|upcoming|add|create|schedule)\b", lo):
            return "calendar", "server", None
        if re.search(r"\b(?:what|which|my)\s+notes?\b", lo) or re.search(
                r"\b(?:make|take|write|save|add|search|find|look at|show)\s+(?:a\s+|my\s+)?notes?\b", lo):
            return "notes", "server", None
        # Message send: "text <name> saying <body>" — must beat greeting phrases
        # like "hello" that appear inside the message body.
        if re.search(r"\b(?:text|message|send\s+(?:a\s+)?(?:text|message))\s+(?:\w+[\w'\-.]*\s+)+(?:saying|that|about|:\s*|\b)\b", lo) or \
           re.search(r"\b(?:text|message)\s+[a-z][a-z0-9'\-.]*(\s|\b)", lo):
            return "message", "server", None
        # Email: read/send/search — "email", "mail", "inbox" — must beat generic chat
        if re.search(r"\b(?:email|e-?mail|inbox|send\s+(?:an?\s+)?(?:email|e-?mail)|read\s+(?:my\s+)?(?:email|e-?mail)|unread\s+mail)\b", lo):
            return "email", "server", None
        # Cast control: Chromecast/Google TV — "play X on the TV", "pause the tv"
        if re.search(r"\b(?:on\s+(?:andrea'?s\s+)?(?:the\s+)?tv\b|pause\s+the\s+tv|turn\s+(?:it|the\s+tv)\s+(?:up|down)|put\s+on\s+(?:netflix|youtube)|play\s+(?:netflix|youtube|hulu|plex)\s+on)", lo) or \
           re.search(r"\b(?:mute|unmute)\s+(?:the\s+)?tv\b", lo):
            return "cast", "server", None
        # LG webOS TV control — "the LG tv", "the LG", "LG" as target
        if re.search(r"\b(?:the\s+)?lg\s+tv\b|\bon\s+the\s+lg\b|\bswitch\s+the\s+lg\b|\bturn\s+(?:on|off)\s+the\s+lg\b", lo):
            return "lg_tv", "server", None
        # ADB TV control — screencap/read the TV screen, Fire TV power off
        if re.search(r"\b(?:take\s+a\s+)?screenshot\s+(?:of\s+)?(?:the\s+)?tv\b|\bread\s+the\s+tv\s+screen\b|\bwhat'?s\s+on\s+the\s+fire\s+tv\b|\bturn\s+off\s+the\s+fire\s+tv\b", lo):
            return "tv_adb", "server", None
        # Theater (Panasonic Fire TV Edition) — ADB deep control
        if re.search(r"\b(?:the\s+)?theater\b", lo) and re.search(r"\b(?:on|off|play|pause|screen|what'?s|netflix|volume|turn)\b", lo):
            return "tv_adb", "server", None

        # ── Genius TV dashboard ────────────────────────────────────────────
        # Must be tested BEFORE the vault-keyword short-circuit below, because
        # "show me my recipe for X" would otherwise be swallowed by
        # hermes_memory and answered as spoken text instead of being put on
        # the screen. The distinguishing signal is an explicit request to SHOW
        # something on the dashboard (a screen verb, or "with the video").
        # GA-Desk (3-state surface): "bring up my dashboard"/"desk down" map
        # to the SAME intent — _handle_dashboard translates to desk open/close.
        if re.search(r"\b(?:on\s+the\s+)?dash(?:board)?\b|\bshow\s+(?:me\s+)?.*\bwith\s+the\s+video\b"
                     r"|\bwith\s+the\s+video\s+it\s+came\s+from\b"
                     r"|\bput\s+.*\bon\s+the\s+screen\b|\bon\s+the\s+big\s+screen\b", lo):
            return "dashboard", "server", None
        # Desk: open the full user dashboard (Hermes desktop over kiosk)
        if re.search(r"\b(?:bring|pull|put)\s+up\s+(?:my\s+)?(?:user\s+)?(dash-?board|desk)\b"
                     r"|\bopen\s+(?:my\s+)?(?:dash-?board|desk)\b"
                     r"|\bshow\s+(?:my\s+)?(?:dash-?board|desk)\b", lo):
            return "dashboard", "server", None
        # Desk: close — back to ambient art
        if re.search(r"\b(?:desk|dash-?board)\s+(?:down|away|off|close[d]?)\b"
                     r"|\bback\s+to\s+(?:the\s+)?art\b|\bhide\s+(?:my\s+)?desk\b"
                     r"|\bput\s+(?:my\s+)?desk\s+away\b", lo):
            return "dashboard", "server", None
        # Dashboard navigation / dismissal
        if re.search(r"\b(?:back\s+to\s+the\s+(?:room|art|screensaver)|hide\s+the\s+dash(?:board)?"
                     r"|clear\s+the\s+screen|dismiss\s+the\s+dash(?:board)?)\b", lo):
            return "dashboard", "server", None
        # Dialogue clarity — "I can't hear the words", slow down, louder
        if re.search(r"\b(?:can'?t\s+(?:hear|make\s+out)|hard\s+to\s+hear)\b"
                     r"|\bdialogue\s+(?:boost|clarity)\b|\bboost\s+(?:the\s+)?(?:dialogue|voices?|speech)\b"
                     r"|\bclearer\s+(?:voices?|dialogue|speech)\b"
                     r"|\bslow\s+(?:that|it|this)\s+down\b|\bspeed\s+(?:that|it|this)\s+up\b"
                     r"|\bnormal\s+speed\b", lo):
            return "dashboard", "server", None
        # "sign me in to Netflix" — one-time service login
        if re.search(r"\bsign\s+(?:me\s+)?in(?:to)?\b|\blog\s+(?:me\s+)?in(?:to)?\b", lo):
            return "dashboard", "server", None
        # "play it" / "play it on Netflix" — start the thing on screen
        if re.search(r"^\s*play\s+(?:it|that|this)\b|\bplay\s+(?:it|that|this)\s+on\s+\w+"
                     r"|\bwatch\s+(?:it|that)\s+on\s+\w+", lo):
            return "dashboard", "server", None
        # Reviews / info about a show or film, put on the screen
        if re.search(r"\bshow\s+(?:me\s+)?(?:the\s+)?reviews?\b|\breviews?\s+of\b"
                     r"|\breviews?\s+for\b|\bwhat\s+do\s+(?:the\s+)?critics\b", lo):
            return "dashboard", "server", None
        # Step navigation while a recipe is on screen
        if re.search(r"\b(?:back\s+up\s+to|go\s+to|jump\s+to|show\s+me)\s+(?:the\s+)?"
                     r"(?:step\s+\d+|\w+\s+step)\b", lo):
            return "dashboard", "server", None

        # Force elder-brain for obvious vault keywords
        vault_keywords = VAULT_KEYWORDS
        for kw in vault_keywords:
            if kw in lo:
                return "hermes_memory", self.TIER_MAP.get("hermes_memory", "hermes"), self.RESPONSES.get("hermes_memory")
        if re.search(r'my\s+.+?\s+(?:recipe|recipes|note|notes)', lo):
            return "hermes_memory", self.TIER_MAP.get("hermes_memory", "hermes"), self.RESPONSES.get("hermes_memory")
        if re.search(r'(?:recipe|recipes|note|notes)\s+i\s+(?:have|saved|wrote)', lo):
            return "hermes_memory", self.TIER_MAP.get("hermes_memory", "hermes"), self.RESPONSES.get("hermes_memory")
        
        for intent, phrases in sorted(self.INTENTS.items(), key=lambda x: -max(len(p) for p in x[1])):
            for phrase in phrases:
                if len(phrase) <= 3:
                    if re.search(r'\b' + re.escape(phrase) + r'\b', clean):
                        return intent, self.TIER_MAP.get(intent, "cloud"), self.RESPONSES.get(intent)
                else:
                    if phrase in clean:
                        return intent, self.TIER_MAP.get(intent, "cloud"), self.RESPONSES.get(intent)
        
        # === PHASE 3: MODEL CLASSIFICATION for uncertain queries ===
        regex_intent = "chat"
        regex_tier = "cloud"
        regex_canned = None
        
        model_intent, model_tier, model_canned = self._model_classify(text)
        
        # Log for training data collection regardless of match
        self._log_training(text, regex_intent, model_intent, "model", model_tier)
        
        # If model disagrees with regex (which defaulted to chat), use model
        if model_intent != "chat":
            print(f"[Intent] Model override: regex={regex_intent} -> model={model_intent} for: '{text}'")
            return model_intent, model_tier, model_canned
        
        # Default to chat
        print(f"[Intent] Defaulting to LLM for: '{text}'")
        intent = "chat"
        tier = "cloud"
        canned = None
        return intent, tier, canned

class ElderBrainBridge:
    """Lightweight bridge to the elder-brain knowledge vault."""
    VAULT    = Path.home() / "elder-brain"
    INDEX_DIRS = ("memory", "notes", "appointments", "family", "health", "inbox", "recipes", "raw_sources", "topics", "research", "products", "projects", "wwdc26", "obsidian", "daily", "weekly", "archive")
    STOP_WORDS = frozenset({"the", "and", "for", "you", "are", "can", "what", "kind", "used", "tell", "about", "that", "have", "has", "had", "with", "from", "they", "she", "her", "him", "his", "was", "were", "been", "not", "but", "this", "will", "would", "could", "should", "may", "might", "must", "shall", "than", "when", "where", "which", "while", "who", "why", "how", "did", "does", "doing", "done", "get", "got", "use", "using", "just", "only", "also", "then", "them", "their", "there", "some", "any", "all", "each", "every", "both", "few", "more", "most", "other", "such", "many", "much", "very", "well", "make", "made", "take", "took", "give", "given", "say", "said", "know", "knows", "think", "thought", "see", "seen", "look", "looking", "like", "want", "wanted", "need", "needed", "find", "found", "call", "called", "come", "came", "put", "work", "working", "try", "trying", "seem", "seems", "turn", "turned", "start", "started", "show", "shown", "play", "playing", "run", "running", "move", "moving", "live", "living", "believe", "leave", "left", "feel", "felt", "become", "became", "happen", "happened", "stand", "stood", "understand", "understood", "bring", "brought", "keep", "kept", "let", "help", "helps", "part", "place", "hand", "set", "end", "eyes", "head", "home", "side", "way", "back", "now", "here", "today", "good", "new", "first", "last", "long", "great", "little", "own", "old", "right", "big", "high", "small", "large", "next", "early", "young", "important", "public", "sure", "enough", "able", "bad", "best", "better", "same", "different", "late", "local", "true", "whole", "ask", "asking", "asked", "told", "telling", "talk", "talked", "talking", "mean", "meant", "meaning", "seemed", "leaving", "puts", "begin", "began", "beginning", "helped", "helping", "showed", "showing", "hear", "heard", "hearing", "ran", "moved", "lived", "believed", "believing", "happen", "happening", "standing", "understanding", "keeping", "lets", "letting", "begins", "says", "things", "something", "anything", "everything", "nothing", "someone", "anyone", "everyone", "nobody", "time", "times", "year", "years", "day", "days", "week", "weeks", "month", "months", "being", "having", "going", "getting", "making", "taking", "coming", "looking", "saying", "going", "went", "gone", "still", "curious", "wonder", "wondering", "thinking", "thought"})
    TYPE_KEYWORDS = {
        "recipe": "recipe", "recipes": "recipe",
        "appointment": "appointment", "appointments": "appointment",
        "health": "health", "medication": "health", "medications": "health",
        "person": "person", "people": "person", "contact": "person", "contacts": "person",
        "family": "family",
        "routine": "routine", "routines": "routine",
        "memory": "memory", "memories": "memory",
        "project": "project", "projects": "project",
        "topic": "topic", "topics": "topic",
        "research": "research",
        "transcript": "transcript", "wwdc": "transcript",
        "clipping": "clipping", "article": "clipping", "articles": "clipping",
        "product": "product", "products": "product",
        "vehicle": "vehicle", "vehicles": "vehicle", "car": "vehicle", "cars": "vehicle",
        "wiki": "wiki",
        "note": "note", "notes": "note",
    }

    def __init__(self):
        self._cache: Dict[str, Tuple[str, float]] = {}  # path -> (text, mtime)
        self._cache_lock = threading.Lock()

    def _read_file(self, path: Path) -> str:
        """Read a file, cache by mtime."""
        try:
            mtime = path.stat().st_mtime
            if str(path) in self._cache and self._cache[str(path)][1] == mtime:
                return self._cache[str(path)][0]
            text = path.read_text(encoding="utf-8", errors="ignore")
            # Server is ThreadingHTTPServer — multiple handler threads can
            # read/evict the cache concurrently. Guard the write.
            with self._cache_lock:
                self._cache[str(path)] = (text, mtime)
            return text
        except Exception:
            return ""

    def _all_files(self) -> List[Path]:
        files: List[Path] = []
        for dname in self.INDEX_DIRS:
            d = self.VAULT / dname
            if d.exists():
                files.extend(p for p in d.rglob("*.md") if p.is_file())
        return files

    def _get_type_from_query(self, query: str) -> Optional[str]:
        """Extract type filter from natural language query."""
        lo = query.lower()
        for word, t in sorted(self.TYPE_KEYWORDS.items(), key=lambda x: -len(x[0])):
            if word in lo:
                return t
        return None

    def _search_recipes_indexed(self, query: str, limit: int = 5) -> List[str]:
        """Fast recipe search using pre-built inverted index."""
        import json
        
        index_path = self.VAULT / "recipe_index.json"
        meta_path = self.VAULT / "recipe_meta.json"
        
        # Cache index in memory (lazy load)
        if not hasattr(self, '_recipe_index'):
            self._recipe_index = None
            self._recipe_meta = None
        
        if self._recipe_index is None or not index_path.exists():
            if not index_path.exists():
                # Build on demand
                try:
                    sys.path.insert(0, str(Path.home() / "Public/GeezerAid_V10/tools"))
                    from recipe_indexer import build_index
                    build_index()
                except Exception as e:
                    print(f"[ElderBrain] Index build failed: {e}")
                    return []
            try:
                with open(index_path) as fh:
                    self._recipe_index = json.load(fh)
                with open(meta_path) as fh:
                    self._recipe_meta = json.load(fh)
                print(f"[ElderBrain] Loaded recipe index: {len(self._recipe_index)} words, {len(self._recipe_meta)} recipes")
            except Exception as e:
                print(f"[ElderBrain] Failed to load recipe index: {e}")
                return []
        
        # Tokenize query — strip type keywords so we don't require them in index
        search_query = query.lower()
        for kw in ["recipe", "recipes", "using", "with", "for", "about"]:
            search_query = search_query.replace(kw, " ")
        q_words = [w for w in search_query.split() if len(w) > 2 and w not in self.STOP_WORDS]
        if not q_words:
            return []
        
        # Score recipes by number of matching keywords
        from collections import Counter
        recipe_scores = Counter()
        
        for w in q_words:
            if w in self._recipe_index:
                for rel_path in self._recipe_index[w]:
                    recipe_scores[rel_path] += 1
        
        # Require ALL query keywords to match (AND logic)
        min_score = len(q_words)
        recipe_scores = Counter({k: v for k, v in recipe_scores.items() if v >= min_score})
        
        if not recipe_scores:
            return []
        
        # Sort by score (desc), take top matches
        results = []
        for rel_path, score in recipe_scores.most_common(limit):
            info = self._recipe_meta.get(rel_path, {})
            title = info.get("title", rel_path)
            ingredients = info.get("ingredients", [])
            summary = info.get("summary", "")
            
            # Build snippet
            snippet = f"Title: {title}\n"
            if ingredients:
                snippet += f"Ingredients: {', '.join(ingredients[:8])}\n"
            if summary:
                snippet += f"Summary: {summary[:200]}"
            
            results.append(snippet)
        
        print(f"[ElderBrain] Recipe index search: '{query}' → {len(results)} results in <1ms")
        return results

    def search(self, query: str, limit: int = 5, type_filter: Optional[str] = None) -> List[str]:
        """Keyword search across elder-brain markdown files with weighted scoring.
        If type_filter is set, only search files with that `type:` in frontmatter.
        Uses fast inverted index for recipe queries."""
        # Auto-detect type from query if not explicitly provided
        if type_filter is None:
            type_filter = self._get_type_from_query(query)
            if type_filter:
                print(f"[ElderBrain] type filter auto-detected: {type_filter}")
        
        # FAST PATH: use pre-built index for recipes
        if type_filter == "recipe":
            return self._search_recipes_indexed(query, limit)
        
        q_words = [w.lower() for w in query.split() if len(w) > 2 and w.lower() not in self.STOP_WORDS]
        if not q_words:
            return []
        
        scored: List[Tuple[float, Path]] = []
        for fpath in self._all_files():
            text = self._read_file(fpath)
            if not text:
                continue
            
            # If type_filter is set, check YAML frontmatter for `type:` match
            if type_filter:
                fm_match = re.match(r'^---\s*\n(.*?)\n---\s*\n', text, re.DOTALL)
                if fm_match:
                    fm_text = fm_match.group(1)
                    type_m = re.search(r'^type:\s*(\S+)', fm_text, re.MULTILINE)
                    if not type_m or type_m.group(1) != type_filter:
                        continue
                else:
                    continue  # no frontmatter, skip when type filter active
            
            text_lo = text.lower()
            fname_lo = fpath.name.lower()
            lines = text.splitlines()
            
            # Score components
            filename_score = 0
            keyword_freq = 0
            keyword_coverage = 0
            proximity_bonus = 0
            
            # Filename match (strong signal)
            for w in q_words:
                if w in fname_lo:
                    filename_score += 15
            
            # Keyword frequency and coverage across entire file
            for w in q_words:
                count = text_lo.count(w)
                if count > 0:
                    keyword_coverage += 1
                    keyword_freq += min(count, 10)  # cap per-word at 10
            
            # Proximity bonus: keywords appearing together on same line
            for line in lines:
                line_lo = line.lower()
                matched = sum(1 for w in q_words if w in line_lo)
                if matched >= 2:
                    proximity_bonus += matched * 3
                if matched >= len(q_words):
                    proximity_bonus += 10  # all keywords on same line
            
            # Coverage multiplier: files matching ALL keywords get big boost
            coverage_mult = 1.0
            if keyword_coverage == len(q_words):
                coverage_mult = 2.5
            elif keyword_coverage >= 2:
                coverage_mult = 1.5
            
            total_score = (filename_score + keyword_freq + proximity_bonus) * coverage_mult
            
            if total_score > 0:
                # Tiebreak by recency
                try:
                    mtime = fpath.stat().st_mtime
                except Exception:
                    mtime = 0
                scored.append((total_score, mtime, fpath))
        
        # Sort by score descending, then by mtime descending (newer first)
        scored.sort(key=lambda x: (-x[0], -x[1]))
        
        results = []
        for score, _, fpath in scored[:limit]:
            text = self._read_file(fpath)
            # Extract most relevant section (first paragraph containing keywords)
            best_section = self._extract_best_section(text, q_words)
            header = f"[{fpath.name}]"
            results.append(f"{header}\n{best_section}")
        return results
    
    def _extract_best_section(self, text: str, keywords: List[str], max_chars: int = 1200) -> str:
        """Extract the most relevant section of text containing the keywords."""
        if not keywords:
            return text[:max_chars]
        
        lines = text.splitlines()
        line_scores = []
        for i, line in enumerate(lines):
            lo = line.lower()
            score = sum(1 for w in keywords if w in lo)
            if score > 0:
                line_scores.append((score, i))
        
        if not line_scores:
            # No keyword matches — return first chunk
            return text[:max_chars]
        
        # Sort by score and pick best-scoring line as anchor
        line_scores.sort(key=lambda x: -x[0])
        anchor = line_scores[0][1]
        
        # Build section: 3 lines before anchor + anchor + 20 lines after
        start = max(0, anchor - 3)
        end = min(len(lines), anchor + 21)
        section = '\n'.join(lines[start:end])
        
        # Truncate to max_chars but try to end at a line boundary
        if len(section) > max_chars:
            section = section[:max_chars]
            last_newline = section.rfind('\n')
            if last_newline > max_chars * 0.7:
                section = section[:last_newline]
        
        return section

    def list_recent(self, days: int = 7, limit: int = 10) -> List[str]:
        """List recently modified files."""
        files = self._all_files()
        cutoff = time.time() - days * 86400
        recent = [(p.stat().st_mtime, p) for p in files if p.exists() and p.stat().st_mtime > cutoff]
        recent.sort(key=lambda x: -x[0])
        return [f"{p.name} ({time.strftime('%Y-%m-%d', time.localtime(m))})" for m, p in recent[:limit]]

    def quick_status(self) -> Dict[str, Any]:
        return {
            "vault_exists": self.VAULT.exists(),
            "files_indexed": len(self._all_files()),
            "recent": self.list_recent(days=7, limit=5),
        }

class LLMBridge:
    """Local-first bridge for FAST path + Hermes delegate for SMART path.

    FAST path (edge / local 4B voice model): direct Ollama HTTP on localhost
    (bypasses Hermes so it stays sub-second). This is the latency-critical tier.

    SMART path (reasoning / coding / hermes memory / tools): delegate to the
    persistent local Hermes gateway (hermes serve) on HERMES_GATEWAY, so model
    selection, fallback_providers, memory and tools live in Hermes. If the
    gateway is unreachable, fall back to `hermes chat` subprocess. The reasoner
    is whatever Hermes is running (cloud today; local when eval says ready).

    Strix/Fedora is DEV-ONLY and is intentionally NOT in the prod path.
    """
    OLLAMA_LOCAL   = "http://localhost:11434"
    HERMES_GATEWAY = os.getenv("HERMES_GATEWAY", "http://127.0.0.1:8642")

    def _flag_speculation(self, reply: str, title: str) -> str:
        """Honesty backstop for the /chat path: if Jeeves asserts a constructed
        scenario or concrete plan but forgot to label it, prepend a soft marker.
        Conservative — only fires on clear scenario-building cues without an
        existing hedge, so plain factual answers are untouched."""
        if not reply:
            return reply
        r = reply.strip()
        low = r.lower()
        hedges = ("if i may speculate", "i'm inferring", "were i to guess",
                  "i speculate", "i suspect", "perhaps", "maybe", "it seems",
                  "i imagine", "likely", "probably", "i'm guessing", "i would guess")
        if any(h in low for h in hedges):
            return r  # already labeled
        # Scenario/planning cues that should carry a label when unmarked.
        cues = ("you should", "why don't you", "i suggest", "i recommend",
                "you might want", "have you considered", "your appointment",
                "your meeting", "your drive", "on your way", "when you get",
                "you could", "what if", "i think you", "i'd plan")
        if any(c in low for c in cues):
            return f"If I may speculate, {title}, {r[0].lower()}{r[1:]}" if r else r
        return r

    # ── Local llama.cpp (Vulkan) backend ──
    # Ollama's bundled llama-server crashes on gemma4 (GGML_SCHED_MAX_SPLIT_INPUTS
    # assert) and gemma3:4b/27b aren't installed, so the local fast/chat path is
    # dead through Ollama. Route it to the running llama.cpp Vulkan servers instead.
    # OpenAI-compatible. Overridable via env so the mix can be repointed w/o code.
    LOCAL_LLAMACPP = os.getenv("GA_LOCAL_LLAMACPP", "http://localhost:11453")
    # gemma4coder (A4B MoE, Q4_K_M) — fast, Jeeves-good local model @ :11453
    FAST_MODEL = os.getenv("GA_FAST_MODEL", "gemma4coder")
    # Emergency fallback model for SMART tiers (used by both the local llama.cpp
    # @ :11453 path and the last-resort Ollama path). Single definition,
    # env-overridable. Default "gemma4coder" matches the model actually served
    # at LOCAL_LLAMACPP, so the fallback isn't pointed at a model that isn't
    # installed (the old "gemma3:27b" default was not present in Ollama).
    FALLBACK_MODEL = os.getenv("GA_FALLBACK_MODEL", "gemma4coder")

    # ── MBP specialist endpoint (9B Q4_K_M, fast for routine GA tasks) ──
    MBP_LLAMACPP = os.getenv("GA_MBP_LLAMACPP", "http://127.0.0.1:8081")
    MBP_MODEL    = os.getenv("GA_MBP_MODEL", "qwen")

    # ── Strix heavy lifter (122B Q4_K_M, for complex/open-ended queries) ──
    STRIX_LLAMACPP = os.getenv("GA_STRIX_LLAMACPP", "http://100.103.195.22:8080")
    STRIX_MODEL    = os.getenv("GA_STRIX_MODEL", "qwen")

    # SMART tiers are NOT mapped to a local model here — they go to Hermes.
    SMART_TIERS = frozenset({"reasoning", "coding", "hermes", "hermes_tools", "frontier"})

    _gateway_ok: Optional[bool] = None
    _gateway_checked: float = 0.0
    GATEWAY_TTL = 30.0

    def __init__(self):
        self._ollama = self.OLLAMA_LOCAL

    def client_info(self, client_ip: str) -> dict:
        return HERMES_USERS.get(client_ip.replace("client:", ""), {"name": "sir", "title": "sir"})

    # ── Strix MoA / llama.cpp Vulkan health (cached) ──
    # The local Mixture-of-Agents mix runs on Strix (this box = localhost, or the
    # Tailscale IP when the server runs on the Mac). Probe the aggregator endpoint
    # so we can warn early instead of failing mid-query.
    _moa_ok: Optional[bool] = None
    _moa_checked: float = 0.0
    MOA_TTL = 30.0

    def _moa_reachable(self) -> bool:
        """Check if Strix MoA aggregator (122B on :8080) is reachable."""
        now = time.time()
        if self._moa_ok is not None and now - self._moa_checked < self.MOA_TTL:
            return self._moa_ok
        # Check aggregator endpoint — the 122B model on Strix :8080
        url = f"http://{os.getenv('GA_MOA_HOST', '10.99.99.2')}:8080/health"
        try:
            req = urllib.request.Request(url, method="GET")
            with urllib.request.urlopen(req, timeout=3) as resp:
                data = json.loads(resp.read())
            self._moa_ok = data.get("status") == "ok"
        except Exception:
            self._moa_ok = False
        self._moa_checked = now
        if not self._moa_ok:
            print(f"[LLM][moa-heartbeat] Strix MoA aggregator UNREACHABLE @ {url} "
                  f"— reasoning/coding will fall back to Hermes")
        return self._moa_ok

    # ── Hermes gateway health (cached) ──
    def _gateway_reachable(self) -> bool:
        now = time.time()
        if self._gateway_ok is not None and now - self._gateway_checked < self.GATEWAY_TTL:
            return self._gateway_ok
        try:
            req = urllib.request.Request(self.HERMES_GATEWAY + "/", method="GET")
            with urllib.request.urlopen(req, timeout=2) as resp:
                _ = resp.status
            self._gateway_ok = True
        except Exception:
            self._gateway_ok = False
        self._gateway_checked = now
        return self._gateway_ok

    # ── Local llama.cpp (Vulkan) backend: OpenAI-compatible ──
    def _local_generate(self, prompt: str, model: str, timeout: int = 120) -> Optional[str]:
        """Generate via the local llama.cpp Vulkan server (replaces broken Ollama)."""
        try:
            url = f"{self.LOCAL_LLAMACPP}/v1/chat/completions"
            payload = json.dumps({
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "max_tokens": 1000,
            }).encode()
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
                return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"[LLM][local-llamacpp] model={model}@{self.LOCAL_LLAMACPP} error: {e}")
            return None

    # ── MBP specialist endpoint (9B Q4_K_M, fast for routine GA tasks) ──
    def _mbp_generate(self, text: str, timeout: int = 30, history: Optional[str] = None) -> Optional[str]:
        """Generate via the MBP llama.cpp server (9B Q4_K_M, fast).
        If history is provided, parse it into proper user/assistant message turns
        so the model understands the conversation flow."""
        try:
            url = f"{self.MBP_LLAMACPP}/v1/chat/completions"
            messages = [{"role": "system", "content": text}]
            # Parse history into proper user/assistant message turns
            if history:
                messages = []
                # Extract system prompt if present in the combined text
                if "You are Jeeves" in text:
                    # text is full_prompt (system + history + question)
                    # Split to get just the system prompt and current question
                    parts = text.split("Recent conversation:")
                    if len(parts) == 2:
                        system_part = parts[0].strip()
                        rest = parts[1]
                        # Find "Question:" in the rest
                        q_idx = rest.rfind("Question:")
                        if q_idx != -1:
                            conversation = rest[:q_idx].strip()
                            current_q = rest[q_idx + len("Question:"):].strip().rstrip("Answer:").strip()
                            # Build proper messages array
                            if system_part:
                                messages.append({"role": "system", "content": system_part})
                            # Parse conversation lines
                            for line in conversation.split("\n"):
                                line = line.strip()
                                if line.startswith("User:"):
                                    messages.append({"role": "user", "content": line[len("User:"):].strip()})
                                elif line.startswith("Jeeves:"):
                                    messages.append({"role": "assistant", "content": line[len("Jeeves:"):].strip()})
                            messages.append({"role": "user", "content": current_q})
                if not messages:
                    # Fallback: send as-is
                    messages = [{"role": "user", "content": text}]
            payload = json.dumps({
                "model": self.MBP_MODEL,
                "messages": messages,
                "stream": False,
                "max_tokens": 500,
            }).encode()
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
                return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"[LLM][mbp] error: {e}")
            return None

    # ── Strix heavy lifter (122B Q4_K_M, for complex/open-ended queries) ──
    def _strix_generate(self, text: str, timeout: int = 120, history: Optional[str] = None) -> Optional[str]:
        """Generate via the Strix llama.cpp server (122B Q4_K_M)."""
        try:
            url = f"{self.STRIX_LLAMACPP}/v1/chat/completions"
            messages = [{"role": "user", "content": text}]
            if history:
                messages.insert(0, {"role": "system", "content": history})
            payload = json.dumps({
                "model": self.STRIX_MODEL,
                "messages": messages,
                "stream": False,
                "max_tokens": 1000,
            }).encode()
            req = urllib.request.Request(
                url, data=payload,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
                return result["choices"][0]["message"]["content"].strip()
        except Exception as e:
            print(f"[LLM][strix] error: {e}")
            return None

    # ── FAST path: direct Ollama on localhost (kept only as last-resort fallback) ──
    def _ollama_generate(self, prompt: str, model: str, timeout: int = 120) -> Optional[str]:
        try:
            req = urllib.request.Request(
                f"{self.OLLAMA_LOCAL}/api/generate",
                data=json.dumps({"model": model, "prompt": prompt,
                                 "stream": False, "options": {"num_predict": 1000}}).encode(),
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                result = json.loads(resp.read())
                return result.get("response", "")
        except Exception as e:
            print(f"[LLM][fast] model={model} error: {e}")
            return None

    # ── SMART path: delegate to Hermes gateway, fallback to subprocess ──
    def _hermes_generate(self, text: str, client_ip: str,
                         context: Optional[str] = None,
                         history: Optional[str] = None) -> Optional[str]:
        # Prepend conversation history if available so Hermes sees prior turns
        if history:
            prompt = f"{history}\nUser: {text}"
        else:
            prompt = text if not context else f"{context}\n\n{text}"
        if self._gateway_reachable():
            try:
                # Hermes API server (OpenAI-compatible) with Bearer auth.
                # Gateway key lives in ~/.hermes/.env as API_SERVER_KEY.
                key = os.getenv("HERMES_GATEWAY_KEY", "")
                if not key:
                    env_path = os.path.expanduser("~/.hermes/.env")
                    try:
                        with open(env_path) as f:
                            for line in f:
                                if line.startswith("API_SERVER_KEY="):
                                    key = line.strip().split("=", 1)[1]
                                    break
                    except Exception:
                        pass
                headers = {"Content-Type": "application/json"}
                if key:
                    headers["Authorization"] = f"Bearer {key}"
                payload = json.dumps({
                    "model": os.getenv("HERMES_GATEWAY_MODEL", "mbp-eng"),
                    "messages": [{"role": "user", "content": prompt}],
                    "max_tokens": 512,
                    "temperature": 0.6,
                }).encode()
                req = urllib.request.Request(
                    self.HERMES_GATEWAY + "/v1/chat/completions", data=payload,
                    headers=headers, method="POST")
                with urllib.request.urlopen(req, timeout=150) as resp:
                    data = json.loads(resp.read())
                    ans = (data.get("choices") or [{}])[0].get("message", {}).get("content") or ""
                    if ans:
                        return ans.strip()
            except Exception as e:
                print(f"[LLM][hermes-gw] error: {e} — falling back to subprocess")
        # Fallback: hermes chat subprocess (reasoner = Hermes default)
        cmd = ["hermes", "chat", "-q", prompt, "--quiet"]
        try:
            res = subprocess.run(cmd, capture_output=True, text=True, timeout=180)
            raw = res.stdout
            lines = [l for l in raw.splitlines() if not l.startswith("session_id:")]
            ans = "\n".join(lines).strip()
            if ans and not ans.lower().startswith(("http ", "api call failed", "error:")):
                return ans
            if res.returncode == 0 and ans:
                return ans
        except Exception as e:
            print(f"[LLM][hermes-cli] error: {e}")
        return None

    def _moa_generate(self, text: str, context: Optional[str] = None) -> Optional[str]:
        """First hop for hard queries: local Strix MoA (strix_verified mix).
        Returns aggregated text, or None if Strix is unreachable."""
        if _moa is None:
            return None
        prompt = f"{context}\n\n{text}" if context else text
        try:
            answer, _refs, ok = _moa.run(prompt)
            if ok and answer:
                return answer
        except Exception as e:
            print(f"[LLM][moa] error: {e}")
        return None

    def generate(self, text: str, client_ip: str, tier: str = "cloud",
                 context: Optional[str] = None, history: Optional[str] = None) -> Optional[str]:
        """Route: reasoning/coding -> Strix MoA, then MBP/Strix/Hermes.
        Other queries -> MBP 9B (with history), then Strix 122B, then Hermes, then local fallback."""
        info = self.client_info(client_ip)
        # Build a warmer, more natural Jeeves persona with anti-apology guard.
        system_prompt = (
            f"You are Jeeves, {info['name']}'s personal assistant. "
            f"Speak warmly and naturally to {info['name']}. "
            f"Use '{info['title']}' occasionally but not every sentence. "
            f"Be conversational — not stiff or formal. "
            f"Keep answers to 1-2 sentences. "
            f"NEVER apologize unless {info['name']} explicitly says something is wrong. "
            f"NEVER say 'I'm afraid', 'I do not have', or 'I'm unable to'. "
            f"If you don't know something, say it plainly without drama. "
            f"HONESTY LABELING (critical): If you are guessing, inferring, or "
            f"constructing a scenario beyond what is known or asked, you MUST flag "
            f"it explicitly — e.g. begin with 'If I may speculate, {info['title']},' "
            f"or 'I'm inferring this, {info['title']},' or 'Were I to guess,'. Never "
            f"present a speculation as established fact. If you state a concrete "
            f"detail (a name, place, time, or event) that wasn't given to you, it "
            f"must be clearly marked as your own inference. Plain answers to known "
            f"facts need no label.\n\n"
            f"CAPABILITIES — you CAN and DO perform these functions directly; never "
            f"claim otherwise: retrieve live weather for any city, fetch current date/time "
            f"for any timezone, search the Elder Brain recipe index, search the user's "
            f"personal notes vault, and answer general knowledge questions.\n\n"
        )
        full_prompt = system_prompt + (history or "") + f"Question: {text}\nAnswer:"

        if tier in self.SMART_TIERS:
            # Hard queries: try the local Strix MoA first (zero cloud cost).
            if tier in ("reasoning", "coding"):
                if not self._moa_reachable():
                    print(f"[LLM][WARN] Strix MoA down — routing {tier} "
                          f"directly to Hermes")
                reply = self._moa_generate(text, context)
                if reply:
                    return reply
                print(f"[LLM] Strix MoA unavailable; falling back to MBP")
            # All smart tiers: try MBP 9B with history first (fast + contextual)
            reply = self._mbp_generate(full_prompt, history=history)
            if reply:
                return reply
            print(f"[LLM] MBP 9B unavailable; falling back to Strix 122B")
            reply = self._strix_generate(full_prompt, history=history)
            if reply:
                return reply
            print(f"[LLM] Strix 122B unavailable; falling back to Hermes")
            reply = self._hermes_generate(text, client_ip, context, history=history)
            if reply:
                return reply
            print(f"[LLM] Hermes unreachable; emergency local fallback -> {self.FALLBACK_MODEL}")
            reply = self._local_generate(text, self.FALLBACK_MODEL)
            if reply:
                return reply
            return self._ollama_generate(text, self.FALLBACK_MODEL)
        # FAST / chat path: MBP 9B (fast), then Strix 122B (quality), then Hermes.
        reply = self._mbp_generate(full_prompt, history=history)
        if reply:
            return self._flag_speculation(reply, info["title"])
        print(f"[LLM] MBP 9B unavailable; falling back to Strix 122B")
        reply = self._strix_generate(full_prompt, history=history)
        if reply:
            return self._flag_speculation(reply, info["title"])
        print(f"[LLM] Strix 122B unavailable; falling back to Hermes")
        reply = self._hermes_generate(text, client_ip, context, history=history)
        if reply:
            return self._flag_speculation(reply, info["title"])
        print(f"[LLM] Hermes unreachable; emergency local fallback -> {self.FALLBACK_MODEL}")
        reply = self._local_generate(text, self.FALLBACK_MODEL)
        if reply:
            return self._flag_speculation(reply, info["title"])
        return self._flag_speculation(self._ollama_generate(text, self.FALLBACK_MODEL), info["title"])

class DebugState:
    """Lightweight debug telemetry for GeezerAid iOS app."""
    MAX_LOGS = 100
    MAX_ERRORS = 50
    MAX_SESSIONS = 20
    MAX_HISTORY = 10  # recent conversation turns for context

    def __init__(self):
        self.last_transcript: str = ""
        self.is_recording: bool = False
        self.last_intent: str = ""
        self.last_tier: str = ""
        self.audio_engine_state: str = "stopped"
        self.speech_recognizer_state: str = "stopped"
        self.device_battery: Optional[float] = None
        self.device_network: str = "unknown"
        self.app_version: str = "unknown"
        self.last_ping: float = 0
        self.strix_moa_ok: Optional[bool] = None   # Strix Vulkan MoA reachability
        self.strix_moa_checked: float = 0.0
        self.logs: deque = deque(maxlen=self.MAX_LOGS)
        self.errors: deque = deque(maxlen=self.MAX_ERRORS)
        self.sessions: deque = deque(maxlen=self.MAX_SESSIONS)
        # conversation_history: list of {"role": "user"/"bot", "text": "..."}
        self.conversation_history: deque = deque(maxlen=self.MAX_HISTORY)
        self.started = time.time()

    def add_history(self, role: str, text: str):
        """Append a turn to conversation history."""
        self.conversation_history.append({"role": role, "text": text[:500]})

    def get_history_text(self, max_turns: int = 5) -> str:
        """Format recent history for LLM prompt."""
        recent = list(self.conversation_history)[-max_turns:]
        if not recent:
            return ""
        lines = []
        for turn in recent:
            label = "User" if turn["role"] == "user" else "Jeeves"
            lines.append(f"{label}: {turn['text']}")
        return "Recent conversation:\n" + "\n".join(lines) + "\n\n"

    def ping(self):
        self.last_ping = time.time()

    def add_log(self, message: str, level: str = "info"):
        entry = {"t": time.time(), "level": level, "msg": message}
        self.logs.append(entry)
        if level in ("error", "fault", "critical"):
            self.errors.append(entry)

    def add_session(self, transcript: str, intent: str, tier: str, response: str, latency_ms: float):
        self.sessions.append({
            "t": time.time(), "transcript": transcript, "intent": intent,
            "tier": tier, "response": response[:200], "latency_ms": round(latency_ms, 1)
        })
        # Also add to conversation history for context tracking
        self.add_history("user", transcript)
        self.add_history("bot", response)

    def snapshot(self) -> Dict[str, Any]:
        age = time.time() - self.last_ping if self.last_ping else None
        return {
            "ok": True,
            "server_uptime_sec": round(time.time() - self.started, 1),
            "device_connected": self.last_ping > 0 and age is not None and age < 300,
            "device_last_ping_sec_ago": round(age, 1) if age else None,
            "last_transcript": self.last_transcript,
            "is_recording": self.is_recording,
            "last_intent": self.last_intent,
            "last_tier": self.last_tier,
            "audio_engine_state": self.audio_engine_state,
            "speech_recognizer_state": self.speech_recognizer_state,
            "device_battery": self.device_battery,
            "device_network": self.device_network,
            "app_version": self.app_version,
            "strix_moa_ok": self.strix_moa_ok,
            "strix_moa_checked_sec_ago": round(time.time() - self.strix_moa_checked, 1)
                if self.strix_moa_checked else None,
            "recent_logs": list(self.logs)[-20:],
            "recent_errors": list(self.errors)[-10:],
            "recent_sessions": list(self.sessions)[-10:],
            "total_logs": len(self.logs),
            "total_errors": len(self.errors),
            "total_sessions": len(self.sessions),
        }

def get_time_context(location: str = None) -> str:
    from datetime import datetime
    from zoneinfo import ZoneInfo
    
    # Default: local timezone (Eastern)
    local_tz = ZoneInfo(os.getenv("GA_TZ", "America/New_York"))
    now_local = datetime.now(local_tz)
    
    if location:
        loc = location.lower().strip()
        # Map common locations to IANA timezone names
        tz_map = {
            "scotland": "Europe/London",
            "edinburgh": "Europe/London",
            "glasgow": "Europe/London",
            "london": "Europe/London",
            "uk": "Europe/London",
            "england": "Europe/London",
            "paris": "Europe/Paris",
            "france": "Europe/Paris",
            "berlin": "Europe/Berlin",
            "germany": "Europe/Berlin",
            "tokyo": "Asia/Tokyo",
            "japan": "Asia/Tokyo",
            "sydney": "Australia/Sydney",
            "australia": "Australia/Sydney",
            "california": "America/Los_Angeles",
            "la": "America/Los_Angeles",
            "los angeles": "America/Los_Angeles",
            "seattle": "America/Los_Angeles",
            "san francisco": "America/Los_Angeles",
            "las vegas": "America/Los_Angeles",
            "pacific": "America/Los_Angeles",
            "denver": "America/Denver",
            "mountain": "America/Denver",
            "chicago": "America/Chicago",
            "central": "America/Chicago",
            "houston": "America/Chicago",
            "dallas": "America/Chicago",
            "new york": "America/New_York",
            "ny": "America/New_York",
            "nyc": "America/New_York",
            "eastern": "America/New_York",
            "boston": "America/New_York",
            "miami": "America/New_York",
            "sarasota": "America/New_York",
            "florida": "America/New_York",
            "atlanta": "America/New_York",
            "dc": "America/New_York",
            "washington": "America/New_York",
            # Middle East
            "iran": "Asia/Tehran",
            "tehran": "Asia/Tehran",
            "persia": "Asia/Tehran",
            "baghdad": "Asia/Baghdad",
            "iraq": "Asia/Baghdad",
            "dubai": "Asia/Dubai",
            "uae": "Asia/Dubai",
            "abudhabi": "Asia/Dubai",
            "abu dhabi": "Asia/Dubai",
            "riyadh": "Asia/Riyadh",
            "saudi": "Asia/Riyadh",
            "saudi arabia": "Asia/Riyadh",
            "jeddah": "Asia/Riyadh",
            "mecca": "Asia/Riyadh",
            "medina": "Asia/Riyadh",
            "jerusalem": "Asia/Jerusalem",
            "israel": "Asia/Jerusalem",
            "tel aviv": "Asia/Jerusalem",
            "telaviv": "Asia/Jerusalem",
            "beirut": "Asia/Beirut",
            "lebanon": "Asia/Beirut",
            "amman": "Asia/Amman",
            "jordan": "Asia/Amman",
            "kuwait": "Asia/Kuwait",
            "kuwait city": "Asia/Kuwait",
            "doha": "Asia/Qatar",
            "qatar": "Asia/Qatar",
            "muscat": "Asia/Muscat",
            "oman": "Asia/Muscat",
            "manama": "Asia/Bahrain",
            "bahrain": "Asia/Bahrain",
            "sanaa": "Asia/Aden",
            "yemen": "Asia/Aden",
            # Asia
            "tokyo": "Asia/Tokyo",
            "japan": "Asia/Tokyo",
            "osaka": "Asia/Tokyo",
            "kyoto": "Asia/Tokyo",
            "beijing": "Asia/Shanghai",
            "china": "Asia/Shanghai",
            "shanghai": "Asia/Shanghai",
            "hong kong": "Asia/Hong_Kong",
            "hongkong": "Asia/Hong_Kong",
            "taipei": "Asia/Taipei",
            "taiwan": "Asia/Taipei",
            "seoul": "Asia/Seoul",
            "korea": "Asia/Seoul",
            "busan": "Asia/Seoul",
            "singapore": "Asia/Singapore",
            "bangkok": "Asia/Bangkok",
            "thailand": "Asia/Bangkok",
            "phuket": "Asia/Bangkok",
            "kuala lumpur": "Asia/Kuala_Lumpur",
            "malaysia": "Asia/Kuala_Lumpur",
            "jakarta": "Asia/Jakarta",
            "indonesia": "Asia/Jakarta",
            "bali": "Asia/Makassar",
            "manila": "Asia/Manila",
            "philippines": "Asia/Manila",
            "ho chi minh": "Asia/Ho_Chi_Minh",
            "vietnam": "Asia/Ho_Chi_Minh",
            "hanoi": "Asia/Ho_Chi_Minh",
            "mumbai": "Asia/Kolkata",
            "india": "Asia/Kolkata",
            "delhi": "Asia/Kolkata",
            "new delhi": "Asia/Kolkata",
            "bangalore": "Asia/Kolkata",
            "chennai": "Asia/Kolkata",
            "kolkata": "Asia/Kolkata",
            "hyderabad": "Asia/Kolkata",
            "pune": "Asia/Kolkata",
            "islamabad": "Asia/Karachi",
            "pakistan": "Asia/Karachi",
            "karachi": "Asia/Karachi",
            "lahore": "Asia/Karachi",
            "dhaka": "Asia/Dhaka",
            "bangladesh": "Asia/Dhaka",
            "colombo": "Asia/Colombo",
            "sri lanka": "Asia/Colombo",
            "kathmandu": "Asia/Kathmandu",
            "nepal": "Asia/Kathmandu",
            "yangon": "Asia/Yangon",
            "myanmar": "Asia/Yangon",
            "rangoon": "Asia/Yangon",
            "ulaanbaatar": "Asia/Ulaanbaatar",
            "mongolia": "Asia/Ulaanbaatar",
            "tashkent": "Asia/Tashkent",
            "uzbekistan": "Asia/Tashkent",
            "almaty": "Asia/Almaty",
            "kazakhstan": "Asia/Almaty",
            "baku": "Asia/Baku",
            "azerbaijan": "Asia/Baku",
            "tbilisi": "Asia/Tbilisi",
            "georgia": "Asia/Tbilisi",
            "yerevan": "Asia/Yerevan",
            "armenia": "Asia/Yerevan",
            "astana": "Asia/Almaty",
            "nur-sultan": "Asia/Almaty",
            "dushanbe": "Asia/Dushanbe",
            "tajikistan": "Asia/Dushanbe",
            "ashgabat": "Asia/Ashgabat",
            "turkmenistan": "Asia/Ashgabat",
            "bishkek": "Asia/Bishkek",
            "kyrgyzstan": "Asia/Bishkek",
            "kabul": "Asia/Kabul",
            "afghanistan": "Asia/Kabul",
            # Europe
            "london": "Europe/London",
            "england": "Europe/London",
            "uk": "Europe/London",
            "britain": "Europe/London",
            "great britain": "Europe/London",
            "scotland": "Europe/London",
            "edinburgh": "Europe/London",
            "glasgow": "Europe/London",
            "wales": "Europe/London",
            "cardiff": "Europe/London",
            "northern ireland": "Europe/London",
            "belfast": "Europe/London",
            "paris": "Europe/Paris",
            "france": "Europe/Paris",
            "marseille": "Europe/Paris",
            "lyon": "Europe/Paris",
            "nice": "Europe/Paris",
            "berlin": "Europe/Berlin",
            "germany": "Europe/Berlin",
            "munich": "Europe/Berlin",
            "hamburg": "Europe/Berlin",
            "frankfurt": "Europe/Berlin",
            "cologne": "Europe/Berlin",
            "rome": "Europe/Rome",
            "italy": "Europe/Rome",
            "milan": "Europe/Rome",
            "naples": "Europe/Rome",
            "turin": "Europe/Rome",
            "florence": "Europe/Rome",
            "venice": "Europe/Rome",
            "madrid": "Europe/Madrid",
            "spain": "Europe/Madrid",
            "barcelona": "Europe/Madrid",
            "valencia": "Europe/Madrid",
            "lisbon": "Europe/Lisbon",
            "portugal": "Europe/Lisbon",
            "amsterdam": "Europe/Amsterdam",
            "netherlands": "Europe/Amsterdam",
            "holland": "Europe/Amsterdam",
            "brussels": "Europe/Brussels",
            "belgium": "Europe/Brussels",
            "vienna": "Europe/Vienna",
            "austria": "Europe/Vienna",
            "zurich": "Europe/Zurich",
            "switzerland": "Europe/Zurich",
            "geneva": "Europe/Zurich",
            "bern": "Europe/Zurich",
            "basel": "Europe/Zurich",
            "lausanne": "Europe/Zurich",
            "copenhagen": "Europe/Copenhagen",
            "denmark": "Europe/Copenhagen",
            "stockholm": "Europe/Stockholm",
            "sweden": "Europe/Stockholm",
            "oslo": "Europe/Oslo",
            "norway": "Europe/Oslo",
            "helsinki": "Europe/Helsinki",
            "finland": "Europe/Helsinki",
            "dublin": "Europe/Dublin",
            "ireland": "Europe/Dublin",
            "athens": "Europe/Athens",
            "greece": "Europe/Athens",
            "warsaw": "Europe/Warsaw",
            "poland": "Europe/Warsaw",
            "krakow": "Europe/Warsaw",
            "prague": "Europe/Prague",
            "czech": "Europe/Prague",
            "czech republic": "Europe/Prague",
            "brno": "Europe/Prague",
            "budapest": "Europe/Budapest",
            "hungary": "Europe/Budapest",
            "bucharest": "Europe/Bucharest",
            "romania": "Europe/Bucharest",
            "sofia": "Europe/Sofia",
            "bulgaria": "Europe/Sofia",
            "zagreb": "Europe/Zagreb",
            "croatia": "Europe/Zagreb",
            "belgrade": "Europe/Belgrade",
            "serbia": "Europe/Belgrade",
            "ljubljana": "Europe/Ljubljana",
            "slovenia": "Europe/Ljubljana",
            "sarajevo": "Europe/Sarajevo",
            "bosnia": "Europe/Sarajevo",
            "tirana": "Europe/Tirane",
            "albania": "Europe/Tirane",
            "skopje": "Europe/Skopje",
            "north macedonia": "Europe/Skopje",
            "macedonia": "Europe/Skopje",
            "podgorica": "Europe/Podgorica",
            "montenegro": "Europe/Podgorica",
            "pristina": "Europe/Belgrade",
            "kosovo": "Europe/Belgrade",
            "tallinn": "Europe/Tallinn",
            "estonia": "Europe/Tallinn",
            "riga": "Europe/Riga",
            "latvia": "Europe/Riga",
            "vilnius": "Europe/Vilnius",
            "lithuania": "Europe/Vilnius",
            "minsk": "Europe/Minsk",
            "belarus": "Europe/Minsk",
            "kiev": "Europe/Kiev",
            "kyiv": "Europe/Kiev",
            "ukraine": "Europe/Kiev",
            "kharkiv": "Europe/Kiev",
            "odessa": "Europe/Kiev",
            "moscow": "Europe/Moscow",
            "russia": "Europe/Moscow",
            "st petersburg": "Europe/Moscow",
            "saint petersburg": "Europe/Moscow",
            "istanbul": "Europe/Istanbul",
            "turkey": "Europe/Istanbul",
            "ankara": "Europe/Istanbul",
            "izmir": "Europe/Istanbul",
            "antalya": "Europe/Istanbul",
            "nicosia": "Asia/Nicosia",
            "cyprus": "Asia/Nicosia",
            "malta": "Europe/Malta",
            "valletta": "Europe/Malta",
            "luxembourg": "Europe/Luxembourg",
            "monaco": "Europe/Monaco",
            "monte carlo": "Europe/Monaco",
            "andorra": "Europe/Andorra",
            "liechtenstein": "Europe/Vaduz",
            "vaduz": "Europe/Vaduz",
            "san marino": "Europe/San_Marino",
            "vatican": "Europe/Vatican",
            "vatican city": "Europe/Vatican",
            "gibraltar": "Europe/Gibraltar",
            "reykjavik": "Atlantic/Reykjavik",
            "iceland": "Atlantic/Reykjavik",
            # Australia / Oceania
            "sydney": "Australia/Sydney",
            "australia": "Australia/Sydney",
            "melbourne": "Australia/Melbourne",
            "brisbane": "Australia/Brisbane",
            "perth": "Australia/Perth",
            "adelaide": "Australia/Adelaide",
            "darwin": "Australia/Darwin",
            "canberra": "Australia/Canberra",
            "hobart": "Australia/Hobart",
            "auckland": "Pacific/Auckland",
            "new zealand": "Pacific/Auckland",
            "wellington": "Pacific/Auckland",
            "christchurch": "Pacific/Auckland",
            "fiji": "Pacific/Fiji",
            "suva": "Pacific/Fiji",
            "papua new guinea": "Pacific/Port_Moresby",
            "port moresby": "Pacific/Port_Moresby",
            "noumea": "Pacific/Noumea",
            "new caledonia": "Pacific/Noumea",
            "apia": "Pacific/Apia",
            "samoa": "Pacific/Apia",
            "tongatapu": "Pacific/Tongatapu",
            "tonga": "Pacific/Tongatapu",
            "guam": "Pacific/Guam",
            "saipan": "Pacific/Saipan",
            "northern mariana": "Pacific/Saipan",
            "palau": "Pacific/Palau",
            "majuro": "Pacific/Majuro",
            "marshall islands": "Pacific/Majuro",
            "tarawa": "Pacific/Tarawa",
            "kiribati": "Pacific/Tarawa",
            "funafuti": "Pacific/Funafuti",
            "tuvalu": "Pacific/Funafuti",
            "nauru": "Pacific/Nauru",
            "south tarawa": "Pacific/Tarawa",
            "pohnpei": "Pacific/Pohnpei",
            "kosrae": "Pacific/Kosrae",
            "chuuk": "Pacific/Chuuk",
            "yap": "Pacific/Yap",
            "honolulu": "Pacific/Honolulu",
            "hawaii": "Pacific/Honolulu",
            "tahiti": "Pacific/Tahiti",
            "french polynesia": "Pacific/Tahiti",
            "rarotonga": "Pacific/Rarotonga",
            "cook islands": "Pacific/Rarotonga",
            "niue": "Pacific/Niue",
            "pago pago": "Pacific/Pago_Pago",
            "american samoa": "Pacific/Pago_Pago",
            # Africa
            "cairo": "Africa/Cairo",
            "egypt": "Africa/Cairo",
            "alexandria": "Africa/Cairo",
            "lagos": "Africa/Lagos",
            "nigeria": "Africa/Lagos",
            "johannesburg": "Africa/Johannesburg",
            "south africa": "Africa/Johannesburg",
            "pretoria": "Africa/Johannesburg",
            "cape town": "Africa/Johannesburg",
            "durban": "Africa/Johannesburg",
            "nairobi": "Africa/Nairobi",
            "kenya": "Africa/Nairobi",
            "mombasa": "Africa/Nairobi",
            "casablanca": "Africa/Casablanca",
            "morocco": "Africa/Casablanca",
            "rabat": "Africa/Casablanca",
            "marrakesh": "Africa/Casablanca",
            "tunis": "Africa/Tunis",
            "tunisia": "Africa/Tunis",
            "algiers": "Africa/Algiers",
            "algeria": "Africa/Algiers",
            "tripoli": "Africa/Tripoli",
            "libya": "Africa/Tripoli",
            "khartoum": "Africa/Khartoum",
            "sudan": "Africa/Khartoum",
            "addis ababa": "Africa/Addis_Ababa",
            "ethiopia": "Africa/Addis_Ababa",
            "dar es salaam": "Africa/Dar_es_Salaam",
            "tanzania": "Africa/Dar_es_Salaam",
            "kampala": "Africa/Kampala",
            "uganda": "Africa/Kampala",
            "kigali": "Africa/Kigali",
            "rwanda": "Africa/Kigali",
            "kinshasa": "Africa/Kinshasa",
            "congo": "Africa/Kinshasa",
            "brazzaville": "Africa/Brazzaville",
            "luanda": "Africa/Luanda",
            "angola": "Africa/Luanda",
            "maputo": "Africa/Maputo",
            "mozambique": "Africa/Maputo",
            "harare": "Africa/Harare",
            "zimbabwe": "Africa/Harare",
            "lusaka": "Africa/Lusaka",
            "zambia": "Africa/Lusaka",
            "gaborone": "Africa/Gaborone",
            "botswana": "Africa/Gaborone",
            "windhoek": "Africa/Windhoek",
            "namibia": "Africa/Windhoek",
            "accra": "Africa/Accra",
            "ghana": "Africa/Accra",
            "dakar": "Africa/Dakar",
            "senegal": "Africa/Dakar",
            "abidjan": "Africa/Abidjan",
            "ivory coast": "Africa/Abidjan",
            "cote d'ivoire": "Africa/Abidjan",
            "monrovia": "Africa/Monrovia",
            "liberia": "Africa/Monrovia",
            "freetown": "Africa/Freetown",
            "sierra leone": "Africa/Freetown",
            "conakry": "Africa/Conakry",
            "guinea": "Africa/Conakry",
            "bamako": "Africa/Bamako",
            "mali": "Africa/Bamako",
            "ouagadougou": "Africa/Ouagadougou",
            "burkina faso": "Africa/Ouagadougou",
            "niamey": "Africa/Niamey",
            "niger": "Africa/Niamey",
            "n'djamena": "Africa/N_Djamena",
            "chad": "Africa/N_Djamena",
            "bangui": "Africa/Bangui",
            "central african republic": "Africa/Bangui",
            "yaounde": "Africa/Douala",
            "cameroon": "Africa/Douala",
            "douala": "Africa/Douala",
            "malabo": "Africa/Malabo",
            "equatorial guinea": "Africa/Malabo",
            "libreville": "Africa/Libreville",
            "gabon": "Africa/Libreville",
            "brazzaville": "Africa/Brazzaville",
            "saotome": "Africa/Sao_Tome",
            "sao tome": "Africa/Sao_Tome",
            "praia": "Atlantic/Cape_Verde",
            "cape verde": "Atlantic/Cape_Verde",
            "bissau": "Africa/Bissau",
            "guinea-bissau": "Africa/Bissau",
            "banjul": "Africa/Banjul",
            "gambia": "Africa/Banjul",
            "djibouti": "Africa/Djibouti",
            "mogadishu": "Africa/Mogadishu",
            "somalia": "Africa/Mogadishu",
            "asmara": "Africa/Asmara",
            "eritrea": "Africa/Asmara",
            "port louis": "Indian/Mauritius",
            "mauritius": "Indian/Mauritius",
            "victoria": "Indian/Mahe",
            "seychelles": "Indian/Mahe",
            "antananarivo": "Indian/Antananarivo",
            "madagascar": "Indian/Antananarivo",
            "moroni": "Indian/Comoro",
            "comoros": "Indian/Comoro",
            "mamoudzou": "Indian/Mayotte",
            "mayotte": "Indian/Mayotte",
            # South America
            "sao paulo": "America/Sao_Paulo",
            "brazil": "America/Sao_Paulo",
            "brasilia": "America/Sao_Paulo",
            "rio de janeiro": "America/Sao_Paulo",
            "rio": "America/Sao_Paulo",
            "recife": "America/Recife",
            "salvador": "America/Bahia",
            "fortaleza": "America/Fortaleza",
            "belem": "America/Belem",
            "manaus": "America/Manaus",
            "curitiba": "America/Sao_Paulo",
            "porto alegre": "America/Sao_Paulo",
            "buenos aires": "America/Argentina/Buenos_Aires",
            "argentina": "America/Argentina/Buenos_Aires",
            "cordoba": "America/Argentina/Cordoba",
            "mendoza": "America/Argentina/Mendoza",
            "santiago": "America/Santiago",
            "chile": "America/Santiago",
            "valparaiso": "America/Santiago",
            "bogota": "America/Bogota",
            "colombia": "America/Bogota",
            "medellin": "America/Bogota",
            "cali": "America/Bogota",
            "cartagena": "America/Bogota",
            "lima": "America/Lima",
            "peru": "America/Lima",
            "quito": "America/Guayaquil",
            "ecuador": "America/Guayaquil",
            "guayaquil": "America/Guayaquil",
            "caracas": "America/Caracas",
            "venezuela": "America/Caracas",
            "maracaibo": "America/Caracas",
            "la paz": "America/La_Paz",
            "bolivia": "America/La_Paz",
            "sucre": "America/La_Paz",
            "santa cruz": "America/La_Paz",
            "asuncion": "America/Asuncion",
            "paraguay": "America/Asuncion",
            "montevideo": "America/Montevideo",
            "uruguay": "America/Montevideo",
            "georgetown": "America/Guyana",
            "guyana": "America/Guyana",
            "paramaribo": "America/Paramaribo",
            "suriname": "America/Paramaribo",
            "cayenne": "America/Cayenne",
            "french guiana": "America/Cayenne",
            "montevideo": "America/Montevideo",
            "falkland islands": "Atlantic/Stanley",
            "stanley": "Atlantic/Stanley",
            # Central America / Caribbean
            "mexico city": "America/Mexico_City",
            "mexico": "America/Mexico_City",
            "cancun": "America/Cancun",
            "guadalajara": "America/Mexico_City",
            "tijuana": "America/Tijuana",
            "monterrey": "America/Monterrey",
            "merida": "America/Merida",
            "oaxaca": "America/Mexico_City",
            "acapulco": "America/Mexico_City",
            "puerto vallarta": "America/Mexico_City",
            "guatemala city": "America/Guatemala",
            "guatemala": "America/Guatemala",
            "san salvador": "America/El_Salvador",
            "el salvador": "America/El_Salvador",
            "tegucigalpa": "America/Tegucigalpa",
            "honduras": "America/Tegucigalpa",
            "managua": "America/Managua",
            "nicaragua": "America/Managua",
            "san jose": "America/Costa_Rica",
            "costa rica": "America/Costa_Rica",
            "panama city": "America/Panama",
            "panama": "America/Panama",
            "havana": "America/Havana",
            "cuba": "America/Havana",
            "santo domingo": "America/Santo_Domingo",
            "dominican republic": "America/Santo_Domingo",
            "san juan": "America/Puerto_Rico",
            "puerto rico": "America/Puerto_Rico",
            "port-au-prince": "America/Port-au-Prince",
            "haiti": "America/Port-au-Prince",
            "kingston": "America/Jamaica",
            "jamaica": "America/Jamaica",
            "nassau": "America/Nassau",
            "bahamas": "America/Nassau",
            "bridgetown": "America/Barbados",
            "barbados": "America/Barbados",
            "port of spain": "America/Port_of_Spain",
            "trinidad": "America/Port_of_Spain",
            "tobago": "America/Port_of_Spain",
            "trinidad and tobago": "America/Port_of_Spain",
            "st john's": "America/Antigua",
            "antigua": "America/Antigua",
            "barbuda": "America/Antigua",
            "castries": "America/St_Lucia",
            "st lucia": "America/St_Lucia",
            "roseau": "America/Dominica",
            "dominica": "America/Dominica",
            "st george's": "America/Grenada",
            "grenada": "America/Grenada",
            "basseterre": "America/St_Kitts",
            "st kitts": "America/St_Kitts",
            "nevis": "America/St_Kitts",
            "st kitts and nevis": "America/St_Kitts",
            "kingstown": "America/St_Vincent",
            "st vincent": "America/St_Vincent",
            "grena": "America/Grenada",
        }
        
        target_tz_name = tz_map.get(loc)
        if not target_tz_name:
            # Try stripping state/country codes: "Sarasota,FL" -> "sarasota"
            loc_stripped = re.split(r'[,;]', loc)[0].strip().lower()
            target_tz_name = tz_map.get(loc_stripped)
        if not target_tz_name:
            # Dynamic lookup: try common patterns
            loc_cap = loc.title()  # "iran" -> "Iran", "copenhagen" -> "Copenhagen"
            # Try continent prefixes
            for prefix in ["Europe/", "Asia/", "Africa/", "America/", "Pacific/", "Atlantic/", "Indian/"]:
                try:
                    test_tz = ZoneInfo(prefix + loc_cap)
                    # Verify it works
                    datetime.now(test_tz)
                    target_tz_name = prefix + loc_cap
                    break
                except Exception:
                    continue
        if target_tz_name:
            try:
                target_tz = ZoneInfo(target_tz_name)
                now_target = datetime.now(target_tz)
                # Capitalize location for display
                display_loc = location.strip().rstrip(".!?").title()
                return f"The time in {display_loc} is {now_target.strftime('%I:%M %p')} on {now_target.strftime('%A, %B %d')}, sir."
            except Exception:
                pass
        
        # Location mentioned but not in our map — return local time with note
        display_loc = location.strip().rstrip(".!?").title()
        return f"The local time here is {now_local.strftime('%I:%M %p on %A, %B %d')}, sir. I don't have timezone data for {display_loc}."
    
    return f"The current local time is {now_local.strftime('%I:%M %p on %A, %B %d')}, sir."

def extract_location(text: str) -> str:
    """Extract location from weather query. Falls back to default if ambiguous."""
    import re
    lo = text.lower().strip().rstrip(".?!")

    # "here" with weather keywords means current/default location
    if 'here' in lo and any(kw in lo for kw in ('weather', 'rain', 'snow', 'storm', 'raining', 'snowing', 'temperature', 'forecast')):
        return os.getenv("GA_LOCATION", "Sarasota,FL")

    # Follow-up patterns: "how about X", "what about X"
    follow_up_patterns = [
        r"^(?:how about|what about)\s+(.+)",
    ]
    for p in follow_up_patterns:
        m = re.search(p, lo)
        if m:
            loc = _strip_temporal(m.group(1).strip().rstrip(".!?"))
            if loc and len(loc) > 2:
                return loc

    # Bare location names removed — too risky with natural speech.
    # Use "how about X" or "what about X" for follow-up locations.
    pass

    # Common patterns: "weather in X", "forecast for X", etc.
    patterns = [
        r"(?:what's|what is|how's)\s+the\s+weather\s+(?:in|for|at|near)\s+(.+)",
        r"weather\s+(?:going\s+to\s+be\s+)?(?:like\s+)?(?:in|for|at|near)\s+(.+)",
        r"forecast\s+(?:in|for|at|near)\s+(.+)",
        r"temperature\s+(?:in|for|at|near)\s+(.+)",
        r"what\s+will\s+the\s+weather\s+be\s+(?:in|for|at|near)\s+(.+)",
        r"what\s+will\s+the\s+weather\s+be\s+like\s+(?:in|for|at|near)\s+(.+)",
        r"(?:what's|what is|how's)\s+the\s+weather\s+going\s+to\s+be\s+like\s+(?:in|for|at|near)\s+(.+)",
        r"(?:going\s+to\s+be\s+)?(?:like\s+)?\b(?:in|for|at|near)\b\s+(.+)",
    ]
    for p in patterns:
        m = re.search(p, lo)
        if m:
            loc = _strip_temporal(m.group(1).strip().rstrip(".!?"))
            if loc and len(loc) > 2 and loc not in ('continue',):
                return loc

    # Last resort: find " in " after "weather" or "forecast"
    for keyword in ("weather", "forecast", "temperature"):
        if keyword in lo:
            kw_pos = lo.index(keyword)
            after_kw = lo[kw_pos:]
            m = re.search(r"\bin\s+([^,.!?;]+)", after_kw)
            if m:
                loc = _strip_temporal(m.group(1).strip().rstrip(".!?"))
                if loc and len(loc) > 2 and loc not in ('continue',):
                    return loc

    # Rain/snow without explicit location → default
    if any(kw in lo for kw in ('rain', 'snow', 'storm', 'raining', 'snowing')):
        return os.getenv("GA_LOCATION", "Sarasota,FL")

    return os.getenv("GA_LOCATION", "Sarasota,FL")


def _strip_temporal(loc: str) -> str:
    """Strip temporal qualifiers and filler words from a location candidate."""
    import re
    loc = re.sub(r"\s+(?:right\s+now)$", "", loc).strip()
    loc = re.sub(r"\s+(?:today|tomorrow|now|currently|please|sir|like|here|right)$", "", loc).strip()
    loc = re.sub(r"\s+this\s+(?:afternoon|morning|evening|week|weekend)\b", "", loc).strip()
    loc = re.sub(r"\s+for\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tomorrow)\b", "", loc).strip()
    loc = re.sub(r"\s+on\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday|today|tomorrow)\b", "", loc).strip()
    loc = re.sub(r"\s+(?:monday|tuesday|wednesday|thursday|friday|saturday|sunday)\b", "", loc).strip()
    loc = re.sub(r"\s+in\s+(?:(?:early|mid|late)\s+)?(?:january|february|march|april|may|june|july|august|september|october|november|december)\b", "", loc).strip()
    loc = re.sub(r"\s+(?:(?:early|mid|late)\s+)?(?:january|february|march|april|may|june|july|august|september|october|november|december)\b", "", loc).strip()
    loc = re.sub(r"\s+for$", "", loc).strip()
    loc = re.sub(r"\s+continue\b", "", loc).strip()
    loc = re.sub(r"\s+yet\b", "", loc).strip()
    return loc

def get_weather_context(location: str = "Sarasota,FL") -> Optional[str]:
    """Current conditions only: 'Patchy rain nearby +80F'."""
    try:
        import urllib.request
        loc = location.replace(" ", "+")
        with urllib.request.urlopen(f"https://wttr.in/{loc}?format=%C+%t", timeout=5) as r:
            return r.read().decode().strip()
    except Exception:
        return None


def get_weather_forecast(location: str = "Sarasota,FL", day: Optional[str] = None) -> Optional[str]:
    """Multi-day forecast from wttr.in JSON API (3 days: today, +1, +2).

    day: optional weekday name ('wednesday') or relative day ('tomorrow') to select.
    Returns a human-readable summary like
    'Wednesday: High 88F, Low 74F, Patchy rain nearby' or today+tomorrow overview.
    """
    try:
        import urllib.request, json as _json
        from datetime import datetime, timedelta
        loc = location.replace(" ", "+")
        with urllib.request.urlopen(f"https://wttr.in/{loc}?format=j1", timeout=8) as r:
            data = _json.loads(r.read().decode())

        days = data.get("weather", [])  # list of {date, mintempC, maxtempC, hourly: [...]}
        if not days:
            return get_weather_context(location)

        day_map = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
                   "friday": 4, "saturday": 5, "sunday": 6}

        def day_desc(d):
            h = d.get("hourly", [{}])[0]
            cond = h.get("weatherDesc", [{}])[0].get("value", "?")
            return cond

        selected = None
        if day:
            dl = day.lower()
            if dl == "tomorrow":
                selected = days[1] if len(days) > 1 else days[0]
            elif dl in day_map:
                # Match the requested weekday in the available forecast window
                for d in days:
                    dt = datetime.strptime(d["date"], "%Y-%m-%d")
                    if dt.weekday() == day_map[dl]:
                        selected = d
                        break
            elif dl in ("tonight", "this evening", "this afternoon"):
                selected = days[0]

        if selected:
            high = int(selected.get("maxtempC", 0))
            low = int(selected.get("mintempC", 0))
            cond = day_desc(selected)
            dt = datetime.strptime(selected["date"], "%Y-%m-%d")
            label = dt.strftime("%A")
            return f"{label}: High {high*9//5+32}°F, Low {low*9//5+32}°F, {cond}"

        # Overview: today + tomorrow
        parts = []
        for i, d in enumerate(days[:2]):
            dt = datetime.strptime(d["date"], "%Y-%m-%d")
            label = "Today" if i == 0 else "Tomorrow"
            high = d.get("maxtempC", "?")
            low = d.get("mintempC", "?")
            cond = day_desc(d)
            parts.append(f"{label}: {cond}, High {int(high)*9//5+32}°F / Low {int(low)*9//5+32}°F")
        return "; ".join(parts)
    except Exception:
        return get_weather_context(location)


FORECAST_MARKERS = ("forecast", "tomorrow", "tonight", "this afternoon", "this evening",
                    "this morning", "next week", "weekend", "later",
                    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday",
                    "high", "low", "going to be", "will it", "be like")

def search_youtube(query: str, max_results: int = 3) -> Optional[List[Dict[str, str]]]:
    """Search YouTube for videos matching the query. Returns list of {title, video_id, url}."""
    try:
        import urllib.request, urllib.parse
        # Use YouTube Data API if available, otherwise use web scrape
        api_key = os.getenv("YOUTUBE_API_KEY")
        if api_key:
            url = f"https://www.googleapis.com/youtube/v3/search?part=snippet&q={urllib.parse.quote(query)}&maxResults={max_results}&type=video&key={api_key}"
            with urllib.request.urlopen(url, timeout=10) as resp:
                data = json.loads(resp.read())
                results = []
                for item in data.get("items", []):
                    video_id = item.get("id", {}).get("videoId", "")
                    snippet = item.get("snippet", {})
                    results.append({
                        "title": snippet.get("title", ""),
                        "video_id": video_id,
                        "url": f"https://www.youtube.com/watch?v={video_id}",
                    })
                return results if results else None
        else:
            # Fallback: scrape YouTube search results
            search_url = f"https://www.youtube.com/results?search_query={urllib.parse.quote(query)}"
            with urllib.request.urlopen(search_url, timeout=10) as resp:
                html = resp.read().decode()
                import re
                # Extract video IDs from search results
                video_ids = re.findall(r'"videoId":"([^"]+)"', html)[:max_results]
                if not video_ids:
                    return None
                results = []
                # Get titles (limited without API)
                for i, vid in enumerate(video_ids):
                    results.append({
                        "title": f"Video {i+1}",
                        "video_id": vid,
                        "url": f"https://www.youtube.com/watch?v={vid}",
                    })
                return results
    except Exception as e:
        print(f"[YouTube] search error: {e}")
        return None

class ChatHandler(BaseHTTPRequestHandler):
    tts    = KokoroTTS()
    intent = IntentClassifier()
    hermes = LLMBridge()
    elder_brain = ElderBrainBridge()
    started = time.time()
    debug   = DebugState()
    # Per-device OCR context: device_id -> {text, raw_text, timestamp}
    # Used to inject OCR text as context for follow-up chat questions
    _ocr_context: Dict[str, Dict[str, Any]] = {}
    # Last weather query context for follow-ups: {"location": ..., "intent": ...}
    _last_weather: Dict[str, Any] = {}
    # Pending message send confirmation: {"to": ..., "body": ..., "asked_at": ts}
    _pending_message: Dict[str, Any] = {}
    # Pending email send confirmation: {"to": ..., "subject": ..., "body": ...}
    _pending_email: Dict[str, Any] = {}

    def _json(self, status: int, obj: dict):
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(json.dumps(obj).encode())

    # ── LLM slot extraction fallback (generalization beyond regexes) ──
    _MLX_ENDPOINT = os.getenv("GA_MLX_ENDPOINT", "http://127.0.0.1:8085")
    _MLX_MODEL = os.getenv("GA_MLX_MODEL", "unsloth/Qwen3.5-9B")
    _GATEWAY = os.getenv("HERMES_GATEWAY", "http://127.0.0.1:8642")

    def _gateway_key(self) -> str:
        key = os.getenv("HERMES_GATEWAY_KEY", "")
        if key:
            return key
        try:
            env_path = os.path.expanduser("~/.hermes/.env")
            with open(env_path) as f:
                for line in f:
                    if line.startswith("API_SERVER_KEY="):
                        key = line.strip().split("=", 1)[1]
        except Exception:
            pass
        return key

    def _extract_slots_llm(self, text: str, intent: str = "weather") -> Optional[Dict[str, Any]]:
        """Ask the fine-tuned Qwen3.5 (MLX) for structured slots as JSON.
        Returns {"location": str|None, "period": str|None} or None on failure.
        Used as a generalization fallback when regex extraction is ambiguous."""
        system = (
            "You are a query parser for a weather/time assistant. Extract structured "
            "slots from the user query. Reply with ONLY a JSON object, no prose:\n"
            '{"location": "city or region name or null", '
            '"period": "time reference like tomorrow, Wednesday, early September, tonight, or null"}'
        )
        payload = json.dumps({
            "model": self._MLX_MODEL,
            "messages": [
                {"role": "system", "content": system},
                {"role": "user", "content": text.strip()},
            ],
            "stream": False,
            "max_tokens": 60,
            "temperature": 0.0,
        }).encode()
        try:
            req = urllib.request.Request(
                f"{self._MLX_ENDPOINT}/v1/chat/completions",
                data=payload,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
            raw = result["choices"][0]["message"]["content"].strip()
            # Extract JSON object (model may wrap in markdown fences or prose)
            import re as _re
            m = _re.search(r"\{.*\}", raw, _re.S)
            if not m:
                print(f"[slots] no JSON in reply: {raw[:80]!r}")
                return None
            data = json.loads(m.group(0))
            loc = (data.get("location") or "").strip().lower()
            period = (data.get("period") or "").strip().lower()
            slots = {}
            if loc and loc != "null" and len(loc) > 1:
                slots["location"] = loc
            if period and period != "null" and len(period) > 1:
                slots["period"] = period
            print(f"[slots] {text[:50]!r} -> {slots}")
            return slots or None
        except Exception as e:
            print(f"[slots] error: {e}")
            return None

    def _serve_room_terminal(self):
        """Serve static files from the room-terminal directory."""
        import mimetypes
        base_dir = Path(__file__).parent / "room-terminal"
        # Map URL path to file path
        rel_path = self.path[len("/room-terminal"):].lstrip("/")
        if not rel_path or rel_path.endswith("/"):
            rel_path = "index.html"
        file_path = base_dir / rel_path
        # Security: prevent path traversal
        try:
            resolved = file_path.resolve()
            base_resolved = base_dir.resolve()
            if not str(resolved).startswith(str(base_resolved)):
                self._json(403, {"error": "forbidden"})
                return
        except (OSError, ValueError):
            self._json(403, {"error": "forbidden"})
            return
        if not resolved.exists() or not resolved.is_file():
            self._json(404, {"error": "not found"})
            return
        content_type, _ = mimetypes.guess_type(str(resolved))
        if not content_type:
            content_type = "application/octet-stream"
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        with open(resolved, "rb") as f:
            self.wfile.write(f.read())

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "POST, GET, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        # Strip query string for routing ("/recommendations?user=andrea" → "/recommendations")
        from urllib.parse import urlparse
        route = urlparse(self.path).path
        if route == "/health":
            self._json(200, {"ok": True, "uptime": round(time.time() - self.started, 1),
                             "tts_ready": self.tts._ready, "version": "v10"})
        elif route == "/debug":
            self._json(200, self.debug.snapshot())
        elif route == "/recommendations":
            self._handle_recommendations()
        elif route.startswith("/room-terminal"):
            self._serve_room_terminal()
        else:
            self._json(404, {"error": "not found"})

    def do_POST(self):
        if self.path not in ("/chat", "/stt", "/ocr", "/photo", "/debug/push", "/tools", "/hermes", "/contextual_brief", "/bot"):
            self._json(404, {"error": "not found"}); return
        length = int(self.headers.get("Content-Length", 0))
        if length > MAX_BODY_BYTES:
            self._json(413, {"error": "payload too large",
                             "max_bytes": MAX_BODY_BYTES}); return
        body = self.rfile.read(length).decode()
        try:
            data = json.loads(body)
        except json.JSONDecodeError:
            self._json(400, {"error": "invalid json"}); return
        if self.path == "/chat":
            self._handle_chat(data)
        elif self.path == "/stt":
            self._handle_stt(data)
        elif self.path == "/ocr":
            self._handle_ocr(data)
        elif self.path == "/photo":
            self._handle_photo(data)
        elif self.path == "/debug/push":
            self._handle_debug_push(data)
        elif self.path == "/tools":
            self._handle_tools(data)
        elif self.path == "/hermes":
            self._handle_hermes(data)
        elif self.path == "/contextual_brief":
            self._handle_contextual_brief(data)
        elif self.path == "/bot":
            self._handle_bot(data)

    def _handle_ocr(self, data: dict):
        """Camera OCR: extract text from image, summarize as Jeeves."""
        if not _OCR_READY and not _EASYOCR_READY:
            self._json(503, {"error": "OCR engine unavailable on server"})
            return
        t0 = time.time()
        image_b64 = data.get("image_base64", "")
        if not image_b64:
            self._json(400, {"error": "missing image_base64"}); return
        # Strip data URL prefix if present
        if "," in image_b64 and image_b64.startswith("data:"):
            image_b64 = image_b64.split(",", 1)[1]
        try:
            img_bytes = base64.b64decode(image_b64)
            # EasyOCR primary, Tesseract fallback
            raw_text = ""
            if _EASYOCR_READY:
                try:
                    import numpy as np
                    # Decode image via cv2 to a proper BGR numpy array (EasyOCR expects this)
                    import cv2
                    nparr = np.frombuffer(img_bytes, dtype=np.uint8)
                    img_cv = cv2.imdecode(nparr, cv2.IMREAD_COLOR)
                    if img_cv is not None:
                        results = _EASYOCR_READER.readtext(img_cv, detail=0, paragraph=True)
                        raw_text = "\n".join(results).strip()
                        print(f"[ocr] EasyOCR extracted {len(raw_text)} chars")
                    else:
                        print("[ocr] cv2.imdecode returned None, falling back to Tesseract")
                except Exception as e:
                    import traceback
                    print(f"[ocr] EasyOCR failed: {e}")
                    traceback.print_exc()
            if not raw_text and _OCR_READY:
                fallback_img = Image.open(io.BytesIO(img_bytes))
                w, h = fallback_img.size
                if max(w, h) < 2000:
                    scale = 2000 / max(w, h)
                    fallback_img = fallback_img.resize((int(w*scale), int(h*scale)), Image.LANCZOS)
                fallback_img = fallback_img.convert('L')
                raw_text = pytesseract.image_to_string(
                    fallback_img, config='--oem 1 --psm 6'
                ).strip()
        except Exception as e:
            self._json(500, {"error": f"OCR failed: {e}"}); return
        if not raw_text:
            no_text_msg = "I'm afraid I couldn't make out any text in that image, sir."
            audio_b64 = None
            if self.tts._ready:
                try:
                    audio_b64 = base64.b64encode(self.tts.generate(no_text_msg)).decode()
                except Exception:
                    pass
            self._json(200, {
                "text": no_text_msg,
                "raw_text": "",
                "audio": audio_b64,
                "latency_ms": int((time.time() - t0) * 1000)
            })
            return
        # Jeeves-style summary via local 7B
        summary_prompt = (
            f"You are Jeeves, the perfect English valet. The user showed you an image containing this text:\n\n"
            f"--- OCR TEXT ---\n{raw_text}\n--- END ---\n\n"
            f"Read it aloud to them in Jeeves' warm, slightly formal style. "
            f"Be concise (1-2 sentences). If the text is a question or instruction, "
            f"answer it helpfully. If it's a menu/list, give a quick summary."
        )
        summary = self.hermes._mbp_generate(summary_prompt)
        if not summary:
            summary = f"The text reads: {raw_text[:200]}"
        # Generate TTS
        audio_b64 = None
        if self.tts._ready:
            try:
                audio_b64 = base64.b64encode(self.tts.generate(summary)).decode()
            except Exception as e:
                print(f"[ocr] TTS failed: {e}")
        # Store OCR context for follow-up questions
        device_id = self.headers.get("X-Device-Id") or self.client_address[0]
        ChatHandler._ocr_context[device_id] = {
            "text": summary,
            "raw_text": raw_text,
            "timestamp": time.time()
        }
        # Expire contexts older than 10 minutes
        cutoff = time.time() - 600
        ChatHandler._ocr_context = {
            k: v for k, v in ChatHandler._ocr_context.items()
            if v.get("timestamp", 0) > cutoff
        }
        self._json(200, {
            "text": summary,
            "raw_text": raw_text,
            "audio": audio_b64,
            "latency_ms": int((time.time() - t0) * 1000)
        })

    def _handle_photo(self, data: dict):
        """Read-this-for-me: send the image to the LOCAL multimodal VLM (:8086)
        so Jeeves can READ + INTERPRET it (pill bottle, label, letter, receipt,
        measurements...), not just dump OCR text. Falls back to the OCR path if
        the VLM is unavailable (graceful degradation)."""
        t0 = time.time()
        image_b64 = data.get("image_base64", "")
        if not image_b64:
            self._json(400, {"error": "missing image_base64"}); return
        if "," in image_b64 and image_b64.startswith("data:"):
            image_b64 = image_b64.split(",", 1)[1]
        prompt = data.get("prompt") or (
            "The user took a photo and wants help reading and understanding it. "
            "Describe the text on it, identify what it is (pill bottle, label, "
            "letter, appliance, receipt, etc.), and call out anything important "
            "(dosage, expiry, measurements, instructions, prices). Be accurate "
            "and plain-spoken. If the image is unclear or you cannot read part "
            "of it, say so explicitly — do NOT invent dosage or medical details "
            "you cannot verify. Keep it to a few sentences."
        )
        vlm_url = os.getenv("GA_MLX_VLM_ENDPOINT", "http://127.0.0.1:8086")
        vlm_model = os.getenv("GA_MLX_VLM_MODEL", "unsloth/Qwen3.5-9B")
        try:
            # Downsample is handled client-side; just send as-is to the VLM.
            payload = json.dumps({
                "model": vlm_model,
                "messages": [{"role": "user", "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
                    {"type": "text", "text": prompt},
                ]}],
                "max_tokens": 300,
            }).encode()
            req = urllib.request.Request(
                f"{vlm_url}/v1/chat/completions", data=payload,
                headers={"Content-Type": "application/json"}, method="POST")
            with urllib.request.urlopen(req, timeout=120) as resp:
                result = json.loads(resp.read())
            desc = result["choices"][0]["message"]["content"].strip()
            if not desc:
                raise ValueError("empty VLM response")
            print(f"[photo] VLM described image ({len(desc)} chars)")
        except Exception as e:
            print(f"[photo] VLM unavailable ({e}); falling back to OCR")
            # Graceful fallback: reuse the OCR text path (today's behavior).
            self._handle_ocr({"image_base64": image_b64})
            return
        # TTS the spoken answer
        audio_b64 = None
        if self.tts._ready:
            try:
                tts_bytes = self.tts.generate(desc)
                if tts_bytes:
                    audio_b64 = base64.b64encode(tts_bytes).decode()
            except Exception as e:
                print(f"[photo] TTS failed: {e}")
        self._json(200, {
            "text": desc,
            "raw_text": desc,
            "audio": audio_b64,
            "engine": "vlm",
            "latency_ms": int((time.time() - t0) * 1000)
        })

    def _handle_ocr_research(self, question: str, ocr_text: str) -> str:
        """Escalate OCR follow-up to cloud LLM with web search.

        Uses GPT-4o-mini with web_search_options for fast, web-augmented answers.
        Falls back to local 7B if cloud is unavailable.
        """
        nous_key = os.environ.get("NOUS_API_KEY", "")
        if not nous_key:
            print("[ocr_research] NOUS_API_KEY not set, falling back to local 7B")
            prompt = (
                f"You are Jeeves. The user asked about this text from an image:\n\n"
                f"=== OCR TEXT ===\n{ocr_text}\n=== END ===\n\n"
                f"Question: {question}\n\n"
                f"Answer in Jeeves' style, be concise."
            )
            return self.hermes._mbp_generate(prompt) or "I'm afraid I can't research that right now, sir."

        # Build a focused research prompt
        # Extract a short topic from OCR text (first 200 chars)
        topic = ocr_text[:300].replace("\n", " ").strip()
        if len(topic) > 200:
            topic = topic[:200] + "..."

        research_prompt = (
            f"You are Jeeves, a courteous English valet. The user showed you a product label or document with this text:\n\n"
            f"--- OCR TEXT ---\n{topic}\n--- END ---\n\n"
            f"The user is asking: \"{question}\"\n\n"
            f"Use web search to find current authoritative information. "
            f"Synthesize a concise answer (2-3 sentences) in Jeeves' warm, slightly formal style. "
            f"If this is about safety, ingredients, medication, or health, prioritize FDA/Mayo Clinic/WebMD sources. "
            f"Quote specific facts you find."
        )

        try:
            # Use GPT-4o-mini (no web_search_options - provider rejects it)
            # Falls back to local 7B for off-line accuracy
            resp = urllib.request.Request(
                "https://inference-api.nousresearch.com/v1/chat/completions",
                data=json.dumps({
                    "model": "openai/gpt-4o-mini",
                    "messages": [{"role": "user", "content": research_prompt}],
                    "max_tokens": 400,
                    "temperature": 0.3
                }).encode(),
                headers={
                    "Authorization": f"Bearer {nous_key}",
                    "Content-Type": "application/json"
                },
                method="POST"
            )
            with urllib.request.urlopen(resp, timeout=60) as r:
                result = json.loads(r.read())
                answer = result["choices"][0]["message"]["content"]
                print(f"[ocr_research] Cloud GPT-4o-mini returned {len(answer)} chars")
                return answer.strip()
        except Exception as e:
            print(f"[ocr_research] Cloud call failed: {e}, falling back to local 7B")
            prompt = (
                f"You are Jeeves. OCR text: {ocr_text[:500]}\n\n"
                f"Question: {question}\n\n"
                f"Answer in Jeeves' style."
            )
            return self.hermes._mbp_generate(prompt) or "I'm afraid I can't research that right now, sir."

    def _handle_debug_push(self, data: dict):
        """Receive telemetry push from iOS app."""
        self.debug.ping()
        if "transcript" in data:
            self.debug.last_transcript = data["transcript"]
        if "is_recording" in data:
            self.debug.is_recording = data["is_recording"]
        if "audio_engine" in data:
            self.debug.audio_engine_state = data["audio_engine"]
        if "speech_recognizer" in data:
            self.debug.speech_recognizer_state = data["speech_recognizer"]
        if "battery" in data:
            self.debug.device_battery = data["battery"]
        if "network" in data:
            self.debug.device_network = data["network"]
        if "app_version" in data:
            self.debug.app_version = data["app_version"]
        if "logs" in data and isinstance(data["logs"], list):
            for entry in data["logs"]:
                if isinstance(entry, dict):
                    self.debug.add_log(entry.get("msg", ""), entry.get("level", "info"))
        self._json(200, {"ok": True, "received": True})

    def _handle_chat(self, data: dict):
        text = data.get("text", "")
        room = data.get("room", "")
        user = data.get("user", "tom")
        source = data.get("source", "")
        # Stable device identity: prefer the app's X-Device-Id (a per-device UUID
        # that survives IP/DHCP/Tailscale rotation). Fall back to IP for clients
        # that don't send it. (Phase 3, fix K)
        device_id = self.headers.get("X-Device-Id") or \
            self.headers.get("X-Forwarded-For", self.client_address[0])
        # ── Persona resolution: wake word = identity ──
        # "Hey Jeeves" -> Tom, "Hey Circe" -> Andrea. Sticky per device until a
        # different "Hey <name>" arrives. The persona sets the user + TTS voice.
        try:
            sys.path.insert(0, os.path.expanduser("~/Public/GeezerAid_V10/tools"))
            from persona_registry import get_session
            get_session().resolve(device_id, text)
            pcfg = get_session().get(device_id)
            user = pcfg["user"].lower()
            # Set the persona title on the Apple tool modules so canned
            # responses use "dear" (Andrea) instead of "sir" (Tom).
            try:
                from apple_tools import set_title as _at_set_title
                _at_set_title(pcfg.get("title", "sir"))
            except Exception:
                pass
            try:
                from apple_mail import set_title as _am_set_title
                _am_set_title(pcfg.get("title", "sir"))
            except Exception:
                pass
            # Strip the wake word from the text so it isn't classified as a command
            for ww in pcfg["wake_words"]:
                if text.lower().strip().startswith(ww):
                    text = text[len(ww):].strip()
                    break
            # Remember the persona's TTS voice for this request
            self._persona_voice = pcfg.get("tts_voice")
        except Exception:
            self._persona_voice = None
        # Store for logging in _respond
        self._last_room = room
        self._last_user = user
        self._last_source = source
        # If OCR context was injected, append it to the text
        ocr_addition = data.get("_ocr_context_addition", "")
        if ocr_addition:
            text = text + ocr_addition
        client_ip = device_id
        start = time.time()
        # Access log — write directly to a file (launchd stdout isn't flushed
        # live, so print() is unreliable for monitoring).
        try:
            with open(os.path.expanduser("~/Library/Logs/GeezerAid/v9-access.log"), "a") as _af:
                _af.write(f"[ACC] {time.strftime('%H:%M:%S')} ip={client_ip} text={text!r}\n")
        except Exception:
            pass
        intent, tier, canned = self.intent.classify(text)
        print(f"[DEBUG] Intent classification: text='{text}', intent='{intent}', tier='{tier}', canned='{canned}'")

        # ── Conversation context: follow-up detection ──
        import re
        # If the previous turn was weather/time/recipe and the current query looks
        # like a follow-up (just a location, or "how about X"), inherit the intent.
        last_session = self.debug.sessions[-1] if self.debug.sessions else None
        if last_session:
            last_intent = last_session.get("intent", "")
            text_lower = text.lower().strip().rstrip(".?!")
            # Location-only follow-ups after weather: "How about Pittsburgh?", "Philadelphia"
            if last_intent == "weather":
                text_lower = text.lower().strip().rstrip(".?!")
                # Reject anything that looks like a new question, not a location follow-up
                question_words = ("what", "when", "where", "why", "who", "how is",
                                  "is it", "will", "does", "do ", "can", "could",
                                  "time", "forecast", "temperature", "weather")
                # Also reject greetings / small talk — "good morning" is not a place
                non_location_phrases = ("good morning", "good afternoon", "good evening",
                                        "good night", "hello", "hi ", "hey", "how are you",
                                        "thank", "thanks", "bye", "goodbye", "see you",
                                        "what's up", "how's it going", "nice to meet")
                is_question = any(q in text_lower for q in question_words)
                is_smalltalk = any(p in text_lower for p in non_location_phrases)
                is_explicit_followup = text_lower.startswith(("how about", "what about", "and "))
                is_bare_location = re.match(r"^[a-z\s]+$", text_lower) and len(text_lower.split()) <= 4
                # Sentence-starter pronouns/verbs: a trailing fragment of speech
                # ("i think we need") is NOT a location follow-up — send it to
                # the LLM chat path instead of forcing weather.
                sentence_starters = ("i", "we", "you", "he", "she", "they", "it",
                                     "let", "lets", "can", "will", "would",
                                     "should", "do", "does", "did", "is", "are",
                                     "was", "were", "my", "the", "this", "that",
                                     "there", "then", "so", "but", "well", "hey")
                starts_with_starter = text_lower.split()[0] in sentence_starters if text_lower.split() else True
                if is_explicit_followup or (is_bare_location and not is_question and not is_smalltalk and not starts_with_starter):
                    intent = "weather"
                    tier = "cloud"
                    print(f"[chat] weather follow-up detected: '{text}' -> forcing intent=weather")
            # Time follow-ups: "what time is it in London?" (only when it clearly mentions time)
            elif last_intent in ("time", "date"):
                time_markers = ("what time", "the time", "clock", "current time",
                                "time is it", "time now", "what day", "what date",
                                "what's the date", "today is")
                if any(tm in text_lower for tm in time_markers):
                    intent = last_intent
                    tier = "cloud"
                    print(f"[chat] time/date follow-up detected: '{text}' -> forcing intent={last_intent}")
            # "I was asking about X" / "I meant X" — re-ask the previous intent with stored context
            if text_lower.startswith(("i was asking about", "i asked about", "i meant", "i was talking about",
                                      "i was referring to", "i mean")):
                prev = ChatHandler._last_weather
                if prev.get("intent") == "weather":
                    intent = "weather"
                    tier = "cloud"
                    # Reuse stored location; the follow-up text may name a day/month qualifier
                    print(f"[chat] 'was asking about' follow-up -> weather (loc={prev.get('location')})")
                elif last_intent in ("time", "date"):
                    intent = last_intent
                    tier = "cloud"
                    print(f"[chat] 'was asking about' follow-up -> {last_intent}")

        # ── Dangerous-action guard (from V8): refuse outright, no execution ──
        if _gate is not None and _gate.is_dangerous(text, intent):
            latency_ms = round((time.time() - start) * 1000, 1)
            refusal = "I'm afraid I can't do that, Dave."
            audio_b64 = None
            if self.tts._ready:
                audio = self.tts.generate(refusal)
                if audio:
                    audio_b64 = base64.b64encode(audio).decode()
            self._json(200, {
                "text": refusal,
                "audio": audio_b64,
                "intent": intent,
                "tier": "refused",
                "latency_ms": latency_ms,
            })
            self.debug.add_session(text, intent, "refused", refusal, latency_ms)
            return
        
        # Follow-up detection: if last turn was hermes_memory and current query
        # is a pronoun-based follow-up ("does it", "what about", "what else", etc.)
        # force hermes_memory context
        last_session = self.debug.sessions[-1] if self.debug.sessions else None
        if last_session and last_session.get("intent") == "hermes_memory":
            follow_up_markers = ["does it", "did it", "what about", "what else", 
                                  "how about", "tell me more", "anything else",
                                  "is there", "are there", "what is it", "what are they",
                                  "what does it", "what did it", "and the", "and what about"]
            if any(marker in text.lower() for marker in follow_up_markers):
                intent = "hermes_memory"
                tier = "hermes"
                print(f"[chat] follow-up detected, forcing hermes_memory")

        # OCR context: if device has recent OCR text, inject it as context
        device_id = self.headers.get("X-Device-Id") or self.client_address[0]
        ocr_ctx = ChatHandler._ocr_context.get(device_id)
        if ocr_ctx and (time.time() - ocr_ctx.get("timestamp", 0)) < 600:
            age_sec = int(time.time() - ocr_ctx["timestamp"])
            print(f"[chat] OCR context available (age={age_sec}s, {len(ocr_ctx.get('raw_text',''))} chars)")
            # For follow-up style questions OR direct chat about the text, use OCR context
            ocr_followup_markers = ["this", "that", "it", "they", "the text", "the image",
                                    "the menu", "the label", "the bottle", "the package",
                                    "the ingredients", "the warning", "the warnings",
                                    "the directions", "the instructions", "what does it",
                                    "what did it", "is it", "are they", "can i", "should i"]
            text_lower = text.lower()
            # Check for ESCALATION keywords (research / look up / etc.)
            escalation_markers = ["research", "look up", "find out", "search",
                                  "what's the latest", "whats the latest", "deep dive",
                                  "analyze", "investigate", "tell me more about",
                                  "explain in detail", "what does the fda say",
                                  "what does the doctor", "is this safe", "is it safe",
                                  "side effects", "interactions", "warnings about"]
            is_followup = any(marker in text_lower for marker in ocr_followup_markers) or tier == "hermes_memory"
            is_escalation = any(marker in text_lower for marker in escalation_markers)
            if is_escalation:
                # Research mode: route to cloud with web search
                ocr_prompt_addition = (
                    f"\n\nThe user previously showed you an image with this text:\n"
                    f"--- OCR TEXT ---\n{ocr_ctx.get('raw_text', '')}\n--- END ---\n"
                    f"Your previous summary was: \"{ocr_ctx.get('text', '')}\"\n"
                    f"Now they want you to RESEARCH and answer: {text}\n"
                    f"Use web search to find current authoritative information. "
                    f"Answer in Jeeves' warm, slightly formal style. Be concise (2-3 sentences)."
                )
                data['_ocr_context_addition'] = ocr_prompt_addition
                intent = "ocr_research"
                tier = "ocr_research"
                print(f"[chat] OCR RESEARCH: escalating to cloud with web search")
            elif is_followup:
                # Build prompt with OCR context
                ocr_prompt_addition = (
                    f"\n\nThe user previously showed you an image with this text:\n"
                    f"--- OCR TEXT ---\n{ocr_ctx.get('raw_text', '')}\n--- END ---\n"
                    f"Your previous summary was: \"{ocr_ctx.get('text', '')}\"\n"
                    f"Now they're asking: {text}\n"
                    f"Answer their question using the OCR text above as context. Be concise and in Jeeves' style."
                )
                # We'll prepend this to the prompt by overriding text
                data['_ocr_context_addition'] = ocr_prompt_addition
                # Route to local 7B with OCR context (not elder-brain search)
                intent = "ocr_followup"
                tier = "ocr_followup"
                print(f"[chat] OCR follow-up: routing to local 7B with OCR context")

        self.debug.last_intent = intent
        self.debug.last_tier = tier
        # Probe Strix MoA reachability per request (cached 30s) so /debug + logs
        # reflect current state, and so a down MoA is caught before fallback.
        if tier in ("reasoning", "coding", "hermes", "hermes_tools", "frontier"):
            self.debug.strix_moa_ok = self.hermes._moa_reachable()
            self.debug.strix_moa_checked = time.time()
            if self.debug.strix_moa_ok is False:
                self.debug.add_log("Strix MoA UNREACHABLE — hard queries fall back to Hermes",
                                   level="error")
        print(f"[chat] intent={intent} tier={tier} text='{text[:50]}...'")
        
        # Camera intents: open camera on device, canned response (fast)
        if tier == "camera" and canned:
            response_text = canned
            self._respond(text, intent, tier, response_text, start)
            return
        
        # Edge intents: immediate canned response (no vault search for greetings)
        if tier == "edge" and canned:
            response_text = canned
            self._respond(text, intent, tier, response_text, start)
            return
        
        # For chat/cloud intents, check if query contains vault keywords before forcing elder-brain
        lo = text.lower()
        # Apple Notes queries (intent == "notes") must NOT be swallowed by the
        # elder-brain vault search — "my notes" is a vault keyword, but the user
        # means Apple Notes (syncs to their iPad).
        if intent == "notes":
            has_vault_keyword = False
        else:
            vault_keywords = VAULT_KEYWORDS
            has_vault_keyword = any(kw in lo for kw in vault_keywords)
        
        # Only force elder-brain for non-edge intents that look like vault queries
        if has_vault_keyword or intent == "hermes_memory":
            # FAST PATH: recipe queries — use indexed search, skip LLM synthesis
            type_filter = self.elder_brain._get_type_from_query(text)
            if type_filter == "recipe":
                print(f"[ElderBrain] FAST PATH: recipe query")
                results = self.elder_brain.search(text, limit=5, type_filter="recipe")
                if results:
                    lines = [f"{i+1}. {r.split(chr(10))[0].replace('Title: ', '')}" for i, r in enumerate(results)]
                    response_text = "I found these recipes, sir:\n\n" + "\n".join(lines)
                    self._respond(text, intent, "hermes", response_text, start)
                    return
            
            # Normal vault search with LLM synthesis
            context = "\n".join(self.elder_brain.search(text, limit=3)[:2])
            if context.strip():
                hr = self.hermes.generate(text, client_ip, tier="hermes", context=context)
                if hr:
                    self._respond(text, intent, "hermes", hr, start)
                    return
                # Hermes unreachable: fall through to the regular chat path below
                # instead of returning a canned failure (don't dead-end the query).
                print("[chat] elder-brain context found but Hermes down; "
                      "falling through to local model")
        
        # Time/date: immediate REAL data (check BEFORE hard_indicators)
        if intent in ("time", "date"):
            loc = None
            lo_text = text.lower()
            if " in " in lo_text:
                # Extract text after "time is it in" or just "in "
                import re
                m = re.search(r"in\s+([^,.?!;]+)", lo_text)
                if m:
                    loc = m.group(1).strip().rstrip(".!?")
            response_text = get_time_context(location=loc)
            self._respond(text, intent, tier, response_text, start)
            return
        
        # Weather: fetch REAL data
        if intent == "weather":
            # If this is a follow-up re-asking the previous weather query, reuse its location
            text_lower_0 = text.lower().strip()
            is_reask = text_lower_0.startswith(("i was asking about", "i asked about", "i meant",
                                                "i was talking about", "i was referring to", "i mean"))
            if is_reask and ChatHandler._last_weather.get("intent") == "weather":
                loc = ChatHandler._last_weather.get("location") or extract_location(text)
            else:
                loc = extract_location(text)
            # LLM slot fallback: if regex extraction was ambiguous (default location)
            # or the query has phrasings regexes can't handle, ask the fine-tuned model.
            slots = None
            default_loc = os.getenv("GA_LOCATION", "Sarasota,FL").lower()
            has_explicit_loc_words = any(w in text_lower_0 for w in
                                         (" in ", " for ", " at ", " near ", "around ", "about "))
            if (loc.lower() == default_loc and has_explicit_loc_words) or (
                    loc.lower() == default_loc and any(m in text_lower_0 for m in
                    ("typically", "usually", "like in", "going to be like", "weather is like"))):
                slots = self._extract_slots_llm(text, intent="weather")
                if slots and slots.get("location"):
                    loc = slots["location"]
                    print(f"[weather] regex->default, LLM slots resolved location={loc!r}")
            # Store context for follow-ups ("I was asking about X")
            ChatHandler._last_weather = {"intent": "weather", "location": loc}
            # Forecast-y queries get the multi-day forecast; otherwise current conditions
            text_lower = text.lower()
            is_forecast = any(marker in text_lower for marker in FORECAST_MARKERS)
            display_loc = loc.strip().rstrip(".!?").title() if loc else "there"
            if is_forecast:
                # Try to find a specific day mentioned in the query
                day = None
                for wd in ("monday", "tuesday", "wednesday", "thursday", "friday",
                           "saturday", "sunday", "tomorrow", "tonight",
                           "this afternoon", "this evening"):
                    if wd in text_lower:
                        day = wd
                        break
                # LLM period fallback: if no weekday matched but slots found one
                if day is None and slots:
                    period = slots.get("period")
                    if period:
                        for wd in ("monday", "tuesday", "wednesday", "thursday", "friday",
                                   "saturday", "sunday", "tomorrow", "tonight",
                                   "this afternoon", "this evening"):
                            if wd in period:
                                day = wd
                                break
                w = get_weather_forecast(loc, day=day)
                response_text = (f"The forecast for {display_loc}: {w}, sir." if w
                                 else f"Couldn't fetch forecast for {display_loc}, sir.")
            else:
                w = get_weather_context(loc)
                # Fetch-failure retry: regex produced a bad location → ask LLM for slots
                if not w:
                    llm_loc = None
                    if slots and slots.get("location"):
                        llm_loc = slots["location"]
                    else:
                        slot_retry = self._extract_slots_llm(text, intent="weather")
                        if slot_retry:
                            llm_loc = slot_retry.get("location")
                            if slot_retry.get("period"):
                                for wd in ("monday", "tuesday", "wednesday", "thursday", "friday",
                                           "saturday", "sunday", "tomorrow", "tonight",
                                           "this afternoon", "this evening"):
                                    if wd in slot_retry["period"]:
                                        break
                    if llm_loc and llm_loc.lower() != loc.lower():
                        print(f"[weather] fetch failed for {loc!r}; LLM slots -> {llm_loc!r}")
                        loc = llm_loc
                        display_loc = loc.strip().rstrip(".!?").title() if loc else "there"
                        ChatHandler._last_weather = {"intent": "weather", "location": loc}
                        w = get_weather_context(loc)
                response_text = f"The weather in {display_loc} is {w}, sir." if w else f"Couldn't fetch weather for {display_loc}, sir."
            self._respond(text, intent, tier, response_text, start)
            return
        
        # OCR follow-up: ask local 7B with OCR context
        if intent == "ocr_followup":
            # Get OCR context and rebuild prompt with question first
            ocr_addition = data.get("_ocr_context_addition", "")
            if ocr_addition:
                # Strip the OCR addition from text, then build a clean prompt
                base_text = text.replace(ocr_addition, "").strip()
                # Extract raw_text and summary from the addition
                raw_text = ocr_ctx.get("raw_text", "")
                summary = ocr_ctx.get("text", "")
                # Build a structured prompt: instruction + context + question
                prompt = (
                    f"You are Jeeves, a courteous English valet. The user previously asked you to read an image, and you extracted this text from it:\n\n"
                    f"=== IMAGE TEXT ===\n{raw_text}\n=== END IMAGE TEXT ===\n\n"
                    f"You summarized it as: \"{summary}\"\n\n"
                    f"The user now asks: \"{base_text}\"\n\n"
                    f"Answer their question in Jeeves' warm, slightly formal style. "
                    f"Be concise (1-2 sentences). Reference specific information from the image text. "
                    f"If the question is about warnings, ingredients, or details, quote the relevant parts."
                )
            else:
                prompt = f"You are Jeeves, the perfect English valet. {text}"
            response_text = self.hermes._mbp_generate(prompt) or "I'm afraid I couldn't answer that, sir."
            self._respond(text, intent, tier, response_text, start)
            return

        # OCR research: escalate to cloud LLM with web search
        if intent == "ocr_research":
            ocr_addition = data.get("_ocr_context_addition", "")
            if ocr_addition:
                base_text = text.replace(ocr_addition, "").strip()
            else:
                base_text = text
            raw_text = ocr_ctx.get("raw_text", "") if ocr_ctx else ""
            response_text = self._handle_ocr_research(base_text, raw_text)
            self._respond(text, intent, tier, response_text, start)
            return

        # Hermes memory: explicit vault search
        if intent == "hermes_memory":
            response_text = self._handle_hermes_memory(text)
            self._respond(text, intent, tier, response_text, start)
            return
        
        # ── Cast control: Chromecast / Google TV (Andrea's TCL etc.) ──
        #    Uses the standard Cast protocol — no ADB/developer mode needed.
        if intent == "cast":
            try:
                sys.path.insert(0, os.path.expanduser("~/Public/GeezerAid_V10/tools"))
                from cast_tools import cast_action
                response_text = cast_action(text)
                self._respond(text, intent, "server", response_text, start)
                return
            except Exception as e:
                print(f"[cast] integration error: {e}")
                response_text = "I'm having trouble reaching the TV, sir. Is it on and on the same network?"
                self._respond(text, intent, "server", response_text, start)
                return

        # ── LG webOS TV control (full control: power, inputs, apps) ──
        if intent == "lg_tv":
            try:
                sys.path.insert(0, os.path.expanduser("~/Public/GeezerAid_V10/tools"))
                from lg_tools import lg_action
                response_text = lg_action(text)
                self._respond(text, intent, "server", response_text, start)
                return
            except Exception as e:
                print(f"[lg] integration error: {e}")
                response_text = "I'm having trouble reaching the LG TV, sir. Is it on and on the same network?"
                self._respond(text, intent, "server", response_text, start)
                return

        # ── ADB TV control (Fire TV / Google TV deep control) ──
        #    Screencap + OCR, power off, reliable app launch. Requires dev mode.
        if intent == "tv_adb":
            try:
                sys.path.insert(0, os.path.expanduser("~/Public/GeezerAid_V10/tools"))
                from tv_adb import tv_action
                response_text = tv_action(text)
                self._respond(text, intent, "server", response_text, start)
                return
            except Exception as e:
                print(f"[tv_adb] integration error: {e}")
                response_text = "I'm having trouble with the TV's remote control link, sir."
                self._respond(text, intent, "server", response_text, start)
                return

        # ── Genius TV dashboard ("show me X on the screen") ──────────────
        #    Puts content on the 43" Genius TV rather than speaking it. The
        #    dashboard is a Chrome-hosted web app on Strix; we POST a command
        #    to its server, which relays over SSE to the browser.
        if intent == "dashboard":
            try:
                response_text = self._handle_dashboard(text)
                self._respond(text, intent, "server", response_text, start)
                return
            except Exception as e:
                print(f"[dashboard] error: {e}")
                response_text = "I couldn't reach the screen, sir."
                self._respond(text, intent, "server", response_text, start)
                return

        # ── iPad control via WebDriverAgent (semantic element control) ──
        #    Open apps by name, press buttons, read the screen. Requires the
        #    WDA test running on the device + `remote tunneld` up.
        if intent == "ipad":
            try:
                sys.path.insert(0, os.path.expanduser("~/Public/GeezerAid_V10/tools"))
                from wda_control import wda_action
                response_text = wda_action(text)
                self._respond(text, intent, "server", response_text, start)
                return
            except Exception as e:
                print(f"[wda_control] integration error: {e}")
                response_text = "I'm having trouble with the iPad's control link, sir."
                self._respond(text, intent, "server", response_text, start)
                return

        # ── Apple native integrations: reminders, calendar, notes, messages, ──
        #    contacts, email. Jeeves drives the real apps on the Mac; results
        #    sync to the iPad/iPhone via iCloud.
        if intent in ("reminder", "calendar", "notes", "message", "contacts", "call", "email", "chat"):
            try:
                sys.path.insert(0, os.path.expanduser("~/Public/GeezerAid_V10/tools"))
                from apple_tools import apple_action, message_send
                from apple_mail import mail_action, mail_send as apple_mail_send

                # Email-send confirmation flow (checked before message flow so
                # "yes, send it" after an email proposal resolves the email)
                if ChatHandler._pending_email:
                    lo = text.lower().strip()
                    is_confirm = bool(re.search(r"\b(?:yes|send it|go ahead|please send|do it|confirm)\b", lo))
                    is_cancel = bool(re.search(r"\b(?:no|nope|cancel|don't send|stop|never mind|forget it)\b", lo))
                    if is_cancel:
                        ChatHandler._pending_email = {}
                        response_text = "Very good, sir — I won't send the email."
                        self._respond(text, intent, "server", response_text, start)
                        return
                    if is_confirm:
                        to = ChatHandler._pending_email.get("to", "")
                        subject = ChatHandler._pending_email.get("subject", "")
                        body = ChatHandler._pending_email.get("body", "")
                        result = apple_mail_send(to, subject, body)
                        ChatHandler._pending_email = {}
                        ok = "sent" in result.lower() or "error" not in result.lower()
                        response_text = (f"Sent, sir — '{subject}' to {to}." if ok
                                         else f"I couldn't send that email, sir. ({result[:100]})")
                        self._respond(text, intent, "server", response_text, start)
                        return

                # Message-send confirmation flow: "yes, send it" completes a pending send
                # (runs for chat intent too, so a bare "yes, send it" still works)
                if ChatHandler._pending_message:
                    lo = text.lower().strip()
                    # Word-boundary matching: "no" must not match inside "notes"
                    is_confirm = bool(re.search(r"\b(?:yes|send it|go ahead|please send|do it|confirm)\b", lo))
                    is_cancel = bool(re.search(r"\b(?:no|nope|cancel|don't send|stop|never mind|forget it)\b", lo))
                    if is_cancel:
                        ChatHandler._pending_message = {}
                        response_text = "Very good, sir — I won't send it."
                        self._respond(text, intent, "server", response_text, start)
                        return
                    if is_confirm:
                        to = ChatHandler._pending_message.get("number") or ChatHandler._pending_message.get("to", "")
                        body = ChatHandler._pending_message.get("body", "")
                        result = message_send(to, body)
                        ChatHandler._pending_message = {}
                        ok = ("sent" in result.lower()) or ("delivered" in result.lower()) or (not result)
                        response_text = (f"Sent, sir — '{body}'." if ok
                                         else f"I couldn't send that, sir. ({result[:80]})")
                        self._respond(text, intent, "server", response_text, start)
                        return

                # Only continue the Apple flow for actual Apple intents
                if intent == "chat":
                    # Not an Apple intent — fall through to generic chat
                    raise _AppleFallthrough()
                elif intent == "email":
                    response_text = mail_action(intent, text)
                    # If an email-send was proposed, stash it for confirmation
                    if "I can send this email" in response_text:
                        m_to = re.search(r"To:\s*([^\n]+)", response_text)
                        m_sub = re.search(r"Subject:\s*([^\n]+)", response_text)
                        m_body = re.search(r"Body:\s*([^\n]+)", response_text)
                        if m_to and m_sub:
                            ChatHandler._pending_email = {
                                "to": m_to.group(1).strip(),
                                "subject": m_sub.group(1).strip(),
                                "body": m_body.group(1).strip() if m_body else "",
                                "asked_at": time.time(),
                            }
                else:
                    response_text = apple_action(intent, text)
                # If a message-send was proposed, stash it for confirmation
                if intent == "message" and "I can send" in response_text:
                    # New format: "I can send '<body>' to <label> (<number>), sir."
                    m = re.search(r"I can send '(.+?)' to (.+?) \((\+?[\d\-(). ]+)\), sir", response_text)
                    if m:
                        ChatHandler._pending_message = {
                            "to": m.group(2).strip(),
                            "number": m.group(3).strip(),
                            "body": m.group(1).strip(),
                            "asked_at": time.time(),
                        }
                    else:
                        # Legacy fallback: "I can send '<body>' to <target>, sir."
                        m = re.search(r"I can send '(.+?)' to ([^,]+), sir", response_text)
                        if m:
                            ChatHandler._pending_message = {
                                "to": m.group(2).strip(),
                                "number": "",
                                "body": m.group(1).strip(),
                                "asked_at": time.time(),
                            }
                self._respond(text, intent, "server", response_text, start)
                return
            except _AppleFallthrough:
                # Not an Apple intent — continue normal chat flow below
                pass
            except Exception as e:
                print(f"[apple] integration error: {e}")
                # Fall through to generic chat on any failure

        # Tools: run command
        if intent == "hermes_tools":
            response_text = self._handle_hermes_tools(text)
            self._respond(text, intent, tier, response_text, start)
            return
        
        # Suggestion request: user asks for recommendations
        if intent == "suggestion_request":
            try:
                # NOTE: os/sys already imported at module level — do NOT re-import
                # locally here; a local `import os` makes `os` function-local and
                # breaks os.getenv calls elsewhere in _handle_chat.
                sys.path.insert(0, os.path.expanduser("~/Public/GeezerAid_V10/tools"))
                from suggestion_engine import SuggestionEngine
                # Per-user recommendations: Andrea gets her own viewing affinity
                engine = SuggestionEngine(owner=user or "tom")
                suggestion_text, actions = engine.get_suggestions(
                    user_initiated=True, count=3
                )
                if suggestion_text:
                    # Build response WITH TTS audio and action chips
                    self._respond(text, intent, "server", suggestion_text, start)
                    # NOTE: actions are not currently passed through _respond;
                    # they would need a custom response path. For now, text + audio.
                    return
                else:
                    response_text = "I'm afraid I haven't found anything new this week, sir."
                    self._respond(text, intent, tier, response_text, start)
                    return
            except Exception as e:
                print(f"[suggestion] error: {e}")
                response_text = "I'm having trouble with suggestions at the moment, sir."
                self._respond(text, intent, tier, response_text, start)
                return
        
        # Auto-detect hard queries and bump to reasoning tier
        hard_indicators = [
            "solve", "calculate", "prove", "derivative", "integral", "equation",
            "debug", "code review", "refactor", "algorithm", "explain why",
            "why does", "how does it work", "compare and contrast",
            "proof", "theorem", "lemma", "probability", "programming",
            "python", "javascript", "sql", "regex", "complex",
        ]
        if intent == "chat" and any(kw in lo for kw in hard_indicators):
            intent = "reasoning"
            tier = "reasoning"
            print(f"[chat] auto-promoted to reasoning tier")
        elif any(kw in lo for kw in ["code", "program", "function", "script", "implement", "debug", "refactor", "python", "javascript", "bash"]):
            intent = "coding"
            tier = "coding"
            print(f"[chat] auto-promoted to coding tier")
        
        # Regular chat — inject real-time context so LLM doesn't hallucinate
        llm_text = text
        if tier == "frontier":
            llm_text = redact_pii(text)
            if llm_text != text:
                print(f"[PrivacyFilter] redacted frontier query")
        
        # === INJECT REAL CONTEXT ===
        # Prepend current time/location context to prevent hallucinations
        from datetime import datetime
        now = datetime.now()
        real_context = f"[SYSTEM: Today is {now.strftime('%A, %B %d, %Y')}. The current local time is {now.strftime('%I:%M %p')}. The user is in the US Eastern timezone. If asked about time, use this real time. If asked about weather, say you don't have live weather data and ask them to check a weather app.]\\n\\n"
        
        # Check if user is asking about YouTube videos - do this BEFORE LLM call
        # so we can return video URL even if LLM says it can't play videos
        video_url = None
        lo = text.lower()
        youtube_markers = ["youtube", "play video", "watch video", "play a video", "watch a video",
                          "find a video", "find video", "search for video", "video about",
                          "video on", "video of", "music video", "song video", "play it", 
                          "play me", "show me a video", "find me a video", "get me a video",
                          "ufo", "physicist", "physics video", "play this"]
        if any(marker in lo for marker in youtube_markers):
            import re
            query = lo
            for prefix in ["youtube", "play", "watch", "find", "search for", "search", "a ", "the ", "me ", "it "]:
                query = re.sub(r'^' + re.escape(prefix) + r'\s*', '', query)
            query = query.strip()
            if query and len(query) > 2:
                print(f"[YouTube] Searching for: {query}")
                results = search_youtube(query)
                if results and len(results) > 0:
                    video_url = results[0]["url"]
                    print(f"[YouTube] Found: {video_url}")
        
        history_text = self.debug.get_history_text(max_turns=5)
        hr = self.hermes.generate(real_context + llm_text, client_ip, tier=tier, history=history_text)
        response_text = hr or "Having trouble right now, sir."
        
        # Append video URL info to response if we found one
        if video_url:
            response_text += " I found a video for you to watch."
        
        self._respond(text, intent, tier, response_text, start, video_url=video_url)
    
    def _validate_brief(self, brief: str, facts: dict) -> bool:
        """Coyle-style guardrail: the LLM is the proposer, this is the validator.
        Reject a brief that asserts specifics NOT present in the grounded facts
        (route/road/state/traffic claims when no directions were supplied). The
        caller falls back to the template (also fact-bound) on rejection."""
        if not brief:
            return False
        b = brief.lower()
        # Grounded road/state tokens we actually have (from facts).
        grounded = set()
        if facts.get("directions"):
            d = facts["directions"]
            for k in ("primary_road", "alternate_road", "delay_note"):
                v = d.get(k)
                if isinstance(v, str):
                    for tok in v.replace(",", " ").split():
                        if len(tok) > 2 and tok.replace("-", "").isalnum():
                            grounded.add(tok.lower())
        _d = facts.get("directions")
        has_directions = bool(_d and (_d.get("primary_road") or _d.get("alternate_road")
                                      or _d.get("delay_note") or _d.get("eta_minutes")))
        # Route/traffic vocabulary that must NOT appear unless grounded.
        route_words = ("alternate route", "alternate", "reroute", "rerouting",
                       "take the", "via ", "interstate", "traffic", "delay",
                       "congestion", "detour", "highway", "freeway", "primary route",
                       "eta", "estimated time", "arrival", "minutes", "en route",
                       "on the way there", "drive")
        if not has_directions:
            for w in route_words:
                if w in b:
                    print(f"[brief-validate] REJECTED: '{w}' mentioned but no "
                          f"directions in facts")
                    return False
        # If a route word IS allowed (directions present), it must use a grounded
        # token, not invent one. Check the specific banned inventions.
        banned_roads = ("state road", "sr-", "us-", "route 70", "i-", "i–")
        for br in banned_roads:
            if br in b and br.replace("-", "").replace(" ", "") not in (
                    g.replace("-", "").replace(" ", "") for g in grounded):
                print(f"[brief-validate] REJECTED: invented road '{br}'")
                return False
        return True

    def _handle_contextual_brief(self, data: dict):

        """Proactive context brief (beacon-triggered). Phase-0: tools are seeded
        from ~/Public/GA-V9/ga_context.json so the experience is demoable with no
        external API keys. Swap each stub for a live call later (same schema)."""
        start = time.time()
        context = (data.get("context") or "car").lower()
        discreet = bool(data.get("discreet", False))
        ctx_file = os.path.expanduser("~/Public/GA-V9/ga_context.json")
        try:
            with open(ctx_file) as fh:
                cfg = json.load(fh)
        except Exception as e:
            self._json(500, {"error": f"context config unavailable: {e}"}); return

        # ── Phase-0 STUB TOOLS (same output shape as live calls) ──
        def tool_calendar_today():
            return cfg.get("calendar_today", [])
        def tool_location():
            loc = data.get("device_location")
            return loc or {"label": cfg.get("home", {}).get("label", "home")}
        def tool_todos_pending():
            return cfg.get("todos_pending", [])
        def tool_directions(origin_label, destination):
            d = cfg.get("directions", {})
            return {
                "origin": origin_label,
                "destination": destination,
                "eta_minutes": d.get("eta_minutes", 20),
                "primary_road": d.get("primary_road"),
                "alternate_road": d.get("alternate_road"),
                "primary_delayed": d.get("primary_delayed", False),
                "delay_note": d.get("delay_note"),
            }
        def tool_send_to_nav(destination, provider="google"):
            # Prefer a live, destination-specific deep link built from the
            # appointment location (so "Navigate" goes to Dr. Patel, not home).
            # Falls back to the static seed URL only if destination is empty.
            from urllib.parse import quote
            if destination and destination.strip():
                if provider == "google":
                    url = f"https://www.google.com/maps/dir/?api=1&destination={quote(destination.strip())}&travelmode=driving"
                else:
                    url = f"https://waze.com/ul?q={quote(destination.strip())}&navigate=yes"
            else:
                nav = cfg.get("nav", {})
                url = nav.get("google_maps_url") if provider == "google" else nav.get("waze_url")
            return {"url": url, "provider": provider, "destination": destination}

        # Run the tool chain for the "car" context (and gracefully degrade others).
        facts = {
            "context": context,
            "calendar": tool_calendar_today(),
            "location": tool_location(),
            "todos": tool_todos_pending(),
            "directions": None,
            "nav": None,
        }
        appointment = facts["calendar"][0] if facts["calendar"] else None
        if appointment:
            dest = appointment.get("location") or "your appointment"
            facts["directions"] = tool_directions(facts["location"].get("label", "home"), dest)
            facts["nav"] = tool_send_to_nav(dest)
        # Todos that could be done on the way home/back.
        on_the_way = [t for t in facts["todos"] if t.get("near_route_home")]
        facts["todos_on_the_way"] = on_the_way
        # Directions are only "present" if they carry real content (not just a
        # dict of nulls). This drives both the prompt branch and the validator.
        _d = facts.get("directions")
        dirs_present = bool(_d and (_d.get("primary_road") or _d.get("alternate_road")
                                    or _d.get("delay_note") or _d.get("eta_minutes")))

        # ── Synthesize the Jeeves brief ──
        name = cfg.get("user", {}).get("name", "sir")
        title = cfg.get("user", {}).get("title", "sir")
        system_prompt = (
            f"You are Jeeves, {name}'s personal assistant. Speak warmly and "
            f"naturally to {name}; use '{title}' occasionally. Be conversational, "
            f"not stiff. Keep the spoken brief to 3-5 sentences. NEVER apologize. "
            f"NEVER say 'I'm afraid' or 'I do not have'. If discreet is true, avoid "
            f"names and street numbers — say 'your appointment' / 'the usual road'. "
            f"End with EXACTLY ONE short question and then stop.\n\n"
            f"FACT-LOCK (critical): Use ONLY the facts supplied in the user message. "
            f"Do NOT invent, embellish, or add any specifics not present in 'Facts' — "
            f"no accident types, no crash/wreck causes, no cities/states/roads beyond "
            f"what is named, no new appointments or details. If a delay is mentioned, "
            f"repeat the given note verbatim (e.g. 'there's a delay on 49'); do NOT "
            f"explain why. State the destination as given; do not infer a location "
            f"the facts don't state. If the facts say nothing about something, say "
            f"nothing about it. SPECIFICALLY: if 'directions' are absent or null "
            f"(no primary_road / alternate_road / delay_note), say NOTHING about "
            f"routes, roads, traffic, or how to get there — do not suggest an "
            f"'alternate route' or any driving advice. If 'todos_on_the_way' is "
            f"empty, do not refer to tasks or offer to read them."
        )
        user_prompt = (
            f"A beacon placed {name} in context='{context}'. "
            f"Facts:\n{json.dumps(facts, indent=2)}\n"
            f"Discreet mode: {discreet}.\n\n"
            "Produce Jeeves's proactive spoken brief. For 'car': acknowledge the "
            "car, and state the destination from the calendar as a confirm-able "
            "assumption (not a question). "
            + (f"Directions ARE provided in Facts — give the ETA and the "
               f"alternate-road recommendation using the delay_note verbatim. "
               if dirs_present else
               "No directions are provided in Facts — say NOTHING about routes, "
               "roads, traffic, or how to get there; do not suggest any alternate "
               "route. ")
            + (f"Name the on-the-way todos from Facts and end with one question "
               f"about whether to hear them. "
               if on_the_way else
               "There are no on-the-way todos in Facts — do not refer to tasks or "
               "offer to read them. End with a single natural closing question.")
        )
        brief = None
        try:
            brief = self.hermes._mbp_generate(system_prompt + "\n\n" + user_prompt)
        except Exception as e:
            print(f"[brief] LLM error: {e}")
        if not brief:
            # Template fallback so the endpoint still delivers the experience.
            if appointment and dirs_present:
                d = facts["directions"]
                rec = ""
                if d.get("primary_delayed") and d.get("alternate_road"):
                    rec = f" {d.get('delay_note') or 'there is a delay'} — take {d['alternate_road']} instead."
                eta = d.get("eta_minutes")
                eta_line = f" Travel time is about {eta} minutes." if eta else ""
                todos_line = ""
                if on_the_way:
                    n = len(on_the_way)
                    todos_line = (f" You have {n} item"
                                  f"{'s' if n != 1 else ''} on your list that could "
                                  f"be done on the way back")
                ask = " Would you like me to tell you about them?" if on_the_way else ""
                brief = (f"I see you're in your car, {title}. I assume you're headed "
                         f"to your appointment with {appointment.get('title')}"
                         f"{rec}{eta_line}{todos_line}{ask}")
            else:
                if appointment:
                    brief = (f"I see you're in your car, {title}. You have an "
                             f"appointment with {appointment.get('title')}. "
                             f"Shall I hear the details?")
                else:
                    brief = (f"I see you're in your car, {title}. I don't have an "
                             f"appointment on the books right now — anything I can do?")

        # Coyle-style validator: if the LLM's brief asserts anything not grounded
        # in facts (e.g. invented route when no directions exist), reject and use
        # the fact-bound template instead.
        if not self._validate_brief(brief, facts):
            print("[brief] validator rejected LLM output; using template fallback")
            if appointment and dirs_present:
                d = facts["directions"]
                rec = ""
                if d.get("primary_delayed") and d.get("alternate_road"):
                    rec = f" {d.get('delay_note') or 'there is a delay'} — take {d['alternate_road']} instead."
                eta = d.get("eta_minutes")
                eta_line = f" Travel time is about {eta} minutes." if eta else ""
                todos_line = ""
                if on_the_way:
                    n = len(on_the_way)
                    todos_line = (f" You have {n} item"
                                  f"{'s' if n != 1 else ''} on your list that could "
                                  f"be done on the way back")
                ask = " Would you like me to tell you about them?" if on_the_way else ""
                brief = (f"I see you're in your car, {title}. I assume you're headed "
                         f"to your appointment with {appointment.get('title')}"
                         f"{rec}{eta_line}{todos_line}{ask}")
            else:
                # No real directions (or no appointment): say nothing invented.
                if appointment:
                    brief = (f"I see you're in your car, {title}. You have an "
                             f"appointment with {appointment.get('title')}. "
                             f"Shall I hear the details?")
                else:
                    brief = (f"I see you're in your car, {title}. I don't have an "
                             f"appointment on the books right now — anything I can do?")

        # Build actions (nav deep link) if we have one.
        actions = []

        # ── LEISURE CONTEXT: offer a prepared suggestion ──
        if context == "leisure" and not appointment:
            try:
                import sys
                sys.path.insert(0, os.path.expanduser("~/Public/GeezerAid_V10/tools"))
                from suggestion_engine import SuggestionEngine
                engine = SuggestionEngine(owner=user or "tom")
                suggestion_text, suggestion_actions = engine.get_suggestions(
                    user_initiated=False, context=context, count=1
                )
                if suggestion_text:
                    brief = suggestion_text
                    actions = suggestion_actions
            except Exception as e:
                print(f"[brief] suggestion engine error: {e}")

        if context == "car" and facts.get("nav") and facts["nav"].get("url"):
            actions.append({"type": "nav_deeplink",
                            "url": facts["nav"]["url"],
                            "label": "Navigate",
                            "provider": facts["nav"].get("provider", "google")})

        # TTS the brief through the existing Kokoro path.
        audio_b64 = None
        if self.tts._ready:
            audio = self.tts.generate(brief)
            if audio:
                audio_b64 = base64.b64encode(audio).decode()
        latency_ms = (time.time() - start) * 1000
        self._json(200, {
            "text": brief,
            "audio": audio_b64,
            "actions": actions,
            "context": context,
            "tools_called": ["calendar_today", "location", "todos_pending",
                             "directions", "send_to_nav"] if appointment else
                            ["calendar_today", "location", "todos_pending"],
            "latency_ms": round(latency_ms, 1),
        })

    def _respond(self, text, intent, tier, response_text, start, video_url: str = None):
        audio_b64 = None
        if self.tts._ready:
            # Use the persona's TTS voice (set in _handle_chat) if available
            persona_voice = getattr(self, "_persona_voice", None)
            audio = self.tts.generate(response_text, voice=persona_voice)
            if audio:
                audio_b64 = base64.b64encode(audio).decode()
        latency_ms = (time.time() - start) * 1000
        self.debug.add_session(text, intent, tier, response_text, latency_ms)
        self.debug.add_log(f"chat: intent={intent} tier={tier} latency={latency_ms:.0f}ms", "info")
        
        # Log every conversation to file for training data
        # For frontier tier, redact PII from logged text before writing
        log_text = text
        if tier == "frontier":
            log_text = redact_pii(text)
        try:
            entry = {
                "ts": time.strftime("%Y-%m-%dT%H:%M:%S"),
                "unix": round(time.time(), 3),
                "text": log_text,
                "intent": intent,
                "tier": tier,
                "response": response_text,
                "latency_ms": round(latency_ms, 1),
                "room": getattr(self, '_last_room', ''),
                "user": getattr(self, '_last_user', ''),
                "source": getattr(self, '_last_source', ''),
            }
            with open(LOG_FILE, "a", encoding="utf-8") as fh:
                fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except Exception as e:
            print(f"[log error] {e}")
        
        # Build response with optional video URL
        response_data = {"text": response_text, "intent": intent, "tier": tier, "audio": audio_b64, "latency_ms": round(latency_ms, 1)}
        if video_url:
            response_data["video_url"] = video_url
        
        self._json(200, response_data)

    def _handle_hermes_memory(self, text: str) -> str:
        """Search elder-brain vault, then ask the LLM to synthesize an answer."""
        try:
            # Strip filler words from query so search actually finds matches
            query = re.sub(r"what did we (decide|say|agree|discuss)|remind me about|what did we talk about|what was decided|search my notes|look up|find in my notes|what do you know about|show me my|can you (show|find|look up)|do i have a|my (recipe|notes) (for|about)", "", text, flags=re.IGNORECASE).strip(",. ")
            if not query or len(query) < 3:
                query = re.sub(r"^[^a-zA-Z0-9]*", "", text.lower())
                query = re.sub(r"[^a-zA-Z0-9 ]", "", query)
            # Detect type for targeted search
            type_filter = self.elder_brain._get_type_from_query(text)
            print(f"[ElderBrain] search: '{query}' type={type_filter or 'auto'}")
            results = self.elder_brain.search(query, limit=5, type_filter=type_filter)
            if not results:
                return "I haven't found any notes on that topic, sir."

            # FAST PATH: recipe queries — return directly, skip LLM synthesis
            if type_filter == "recipe":
                if results:
                    lines = [f"{i+1}. {r.split(chr(10))[0].replace('Title: ', '')}" for i, r in enumerate(results)]
                    return "I found these recipes, sir:\n\n" + "\n".join(lines)
                return "I haven't found any recipes matching that, sir."

            # Clean up ANSI and non-printable, strip YAML frontmatter
            import re as regex
            clean_results = []
            for r in results:
                r = regex.sub(r'\x1b\[[0-9;]*[A-Za-z]', '', r)
                r = regex.sub(r'[^\x20-\x7E\n]', ' ', r)
                # Strip YAML frontmatter (--- ... ---)
                r = regex.sub(r'^---\n.*?\n---\n', '', r, flags=regex.S)
                # Strip markdown image links
                r = regex.sub(r'!\[.*?\]\(.*?\)', '', r)
                clean_results.append(r[:1200])
            
            context = "\n---\n".join(clean_results)
            prompt = (
                f"You are Jeeves, a refined British valet. "
                f"The ONLY information you have is in these notes. "
                f"Do NOT use any outside knowledge or training data. "
                f"Answer the question using only the notes below. Be brief and direct. "
                f"If the notes don't contain the answer, say \"I don't have that in my notes, sir.\"\n\n"
                f"Notes:\n{context}\n\n"
                f"Question: {text}\n"
                f"Answer:"
            )
            answer = self.hermes.generate(prompt, client_ip="127.0.0.1", tier="hermes")
            return answer or "I found some notes but couldn't make sense of them, sir."
        except Exception as e:
            print(f"[ElderBrain] search error: {e}")
            return "I'm having trouble recalling that, sir."

    def _handle_hermes_tools(self, text: str) -> str:
        """Run a tool locally via Hermes delegate (Strix is dev-only, not prod)."""
        try:
            tool_map = {
                "check the server": ["hermes", "tools", "terminal", "--", "curl -s -o /dev/null -w '%{http_code}' http://127.0.0.1:8765/health || echo 'server down'"],
                "server status": ["hermes", "tools", "terminal", "--", "launchctl list | grep geezeraid || echo 'no launchd job'"],
                "check logs": ["hermes", "tools", "terminal", "--", "tail -n 20 ~/Public/GA-V9/conversations.jsonl 2>/dev/null || echo 'No log found'"],
            }
            cmd = None
            for phrase, command in tool_map.items():
                if phrase in text.lower():
                    cmd = command
                    break
            if not cmd:
                return "I'm not sure which tool to run for that, sir. Try asking about server status or logs."
            print(f"[Hermes] running tool: {' '.join(cmd)}")
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=30)
            output = result.stdout.strip() or result.stderr.strip() or "No output."
            return f"Tool result: {output[:300]}, sir."
        except Exception as e:
            print(f"[Hermes] tool error: {e}")
            return "The tool didn't respond, sir."

    def _handle_bot(self, data: dict):
        """Delegate a task to the Jeeves bot (Hermes profile) headlessly.
        POST /bot  {text: "...", user: "tom"}  ->  {text: "...", audio: "base64..."}
        Runs `hermes -p jeeves chat -q <text>` and returns the bot's reply.
        """
        text = data.get("text", "").strip()
        user = data.get("user", "tom")
        if not text:
            self._json(400, {"error": "missing text"}); return
        print(f"[Bot] delegating to jeeves: {text[:80]}")
        try:
            # Run the Jeeves bot headlessly. -Q quiet, --yolo to avoid approval
            # prompts on a delegated task. Capture the reply.
            hermes_bin = os.getenv("HERMES_BIN", "/Users/tomdailey/.local/bin/hermes")
            cmd = [hermes_bin, "-p", "jeeves", "chat", "-q", text, "-Q", "--yolo"]
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
            out = result.stdout.strip() or result.stderr.strip()
            # Extract just Jeeves' final answer: strip reasoning blocks, the
            # tirith warning, box-drawing chars, and the session footer.
            reply = _extract_bot_reply(out)
            # Fall back to a clean message if nothing usable
            if not reply or "No usable credentials" in reply:
                reply = "I'm afraid I'm not available at the moment, sir."
            self._json(200, {"text": reply, "user": user, "source": "jeeves-bot"})
        except subprocess.TimeoutExpired:
            print("[Bot] jeeves timed out")
            self._json(504, {"error": "jeeves timed out"})
        except Exception as e:
            print(f"[Bot] error: {e}")
            self._json(500, {"error": str(e)})

    def _handle_dashboard(self, text: str) -> str:
        """Drive the Genius TV dashboard (Chrome web app on Strix).

        Translates spoken requests into dashboard commands:
          "show me my recipe for X with the video"  -> recipe sheet
          "back up to the flambé step" / "step 5"   -> highlight a step
          "back to the room"                        -> ambient screensaver
        """
        import urllib.request, urllib.error
        lo = text.lower()
        base = os.getenv("GTV_DASH_URL", "http://100.103.195.22:8770")

        def post(cmd: dict, timeout: int = 20):
            req = urllib.request.Request(
                base + "/api/command",
                data=json.dumps(cmd).encode(),
                headers={"Content-Type": "application/json"})
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return json.loads(r.read())

        # ── GA-Desk: open the full user dashboard (3-state surface) ──
        # "bring up my dashboard" / "open my desk" → broadcast desk:open over
        # the GTV SSE plane; every display shows the handoff card, and the
        # client-side switcher (kiosk on TCL, Hermes desktop over kiosk on the
        # iMac) comes forward. Timeout daemon closes it back to art.
        if re.search(r"\b(?:bring|pull|put)\s+up\s+(?:my\s+)?(?:user\s+)?(dash-?board|desk)\b"
                     r"|\bopen\s+(?:my\s+)?(?:dash-?board|desk)\b"
                     r"|\bshow\s+(?:my\s+)?(?:dash-?board|desk)\b", lo):
            try:
                post({"type": "desk", "desk": "open", "said": text})
            except Exception:
                pass
            try:
                import urllib.request as _u
                _req = _u.Request("http://127.0.0.1:8771/api/gtv_publish", method="POST",
                                  data=json.dumps({"action": "desk_open", "said": text}).encode(),
                                  headers={"Content-Type": "application/json"})
                _u.urlopen(_req, timeout=5).read()
            except Exception:
                pass
            return "Bringing up your desk, sir. Say 'desk down' or 'back to the art' when you're finished."

        # ── GA-Desk: close — back to the ambient art layer ──
        if re.search(r"\b(?:desk|dash-?board)\s+(?:down|away|off|close[d]?)\b"
                     r"|\bback\s+to\s+(?:the\s+)?art\b|\bhide\s+(?:my\s+)?desk\b"
                     r"|\bput\s+(?:my\s+)?desk\s+away\b", lo):
            try:
                post({"type": "idle", "said": text})
            except Exception:
                pass
            try:
                req2 = urllib.request.Request("http://127.0.0.1:8771/api/gtv_publish", method="POST",
                                              data=json.dumps({"action": "desk_close", "said": text}).encode(),
                                              headers={"Content-Type": "application/json"})
                urllib.request.urlopen(req2, timeout=5).read()
            except Exception:
                pass
            return "Back to the art, sir."

        # ── dismissal: return to the ambient art layer ──
        if re.search(r"back\s+to\s+the\s+(?:room|art|screensaver)|hide\s+the\s+dash|"
                     r"clear\s+the\s+screen|dismiss\s+the\s+dash", lo):
            try:
                post({"type": "idle", "said": text})
            except Exception:
                pass
            subprocess.Popen(
                ["ssh", "-o", "GSSAPIAuthentication=no", "-o", "ConnectTimeout=10",
                 "tomdailey@100.103.195.22",
                 "~/mbp-public/GA-V9/gtv-dashboard.sh hide"],
                stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            return "Back to the room, sir."

        # ── dialogue clarity: EQ boost, volume, playback rate ──
        # "I can't hear the words" is the commonest TV complaint and no TV
        # solves it well. An EQ lift in the speech band beats raising volume,
        # which just makes the explosions louder too.
        if re.search(r"can'?t\s+(?:hear|make\s+out)|hard\s+to\s+hear|dialogue|clearer|"
                     r"slow\s+(?:that|it|this)\s+down|speed\s+(?:that|it|this)\s+up|"
                     r"normal\s+speed", lo):
            def strix(args: str) -> str:
                r = subprocess.run(
                    ["ssh", "-o", "GSSAPIAuthentication=no", "-o", "ConnectTimeout=12",
                     "tomdailey@100.103.195.22",
                     f"~/mbp-public/GA-V9/gtv-dialogue.sh {args}"],
                    capture_output=True, text=True, timeout=60)
                return (r.stdout or r.stderr).strip()

            if re.search(r"\bnormal\s+speed\b", lo):
                strix("normal")
                return "Normal speed, sir."
            if re.search(r"\bslow\s+(?:that|it|this)\s+down\b", lo):
                strix("slower")
                return "Slowing it down, sir."
            if re.search(r"\bspeed\s+(?:that|it|this)\s+up\b", lo):
                strix("faster")
                return "Speeding it up, sir."
            if re.search(r"\b(?:turn\s+it\s+)?off\b|\bstop\s+(?:the\s+)?boost\b", lo):
                strix("boost off")
                return "Dialogue boost off, sir."

            # Default for "I can't hear the words": boost speech AND nudge
            # volume, because the honest answer to that complaint is both.
            out = strix("boost on")
            strix("louder 5")
            if "ON" in out:
                return ("Dialogue boost on and a little louder, sir. "
                        "Say clearer voices off to undo it.")
            return ("I couldn't enable the dialogue filter, sir — "
                    "I've raised the volume instead.")

        # ── sign in to a streaming service (one-time) ──
        if re.search(r"\bsign\s+(?:me\s+)?in|\blog\s+(?:me\s+)?in", lo):
            svc = ""
            for name in ("netflix", "hbo", "max", "prime", "amazon", "hulu",
                         "disney", "paramount", "peacock", "apple", "youtube"):
                if re.search(r"\b" + name + r"\b", lo):
                    svc = name
                    break
            if not svc:
                return "Sign in to which service, sir?"
            post({"type": "signin", "service": svc, "said": text})
            return (f"{svc.title()} sign-in is on the screen, sir. "
                    "Use the mouse and keyboard — I'll remember the login.")

        # ── "play it" — open the thing on screen in a streaming window ──
        if re.search(r"\bplay\s+(?:it|that|this)\b|\bwatch\s+(?:it|that)\s+on\b", lo):
            # Which service? Default to the first that matches, else netflix.
            svc = "netflix"
            for name in ("netflix", "hbo", "max", "prime", "amazon", "hulu",
                         "disney", "paramount", "peacock", "apple", "youtube"):
                if re.search(r"\b" + name + r"\b", lo):
                    svc = name
                    break
            full = bool(re.search(r"\bfull\s*screen\b|\bbig\s+screen\b", lo))
            try:
                res = post({"type": "play", "service": svc,
                            "fullscreen": full, "said": text})
                return f"Playing {res.get('played')} on {svc.title()}, sir."
            except urllib.error.HTTPError as e:
                if e.code == 400:
                    return ("There's nothing on the screen to play yet, sir. "
                            "Show me something first.")
                raise

        # ── reviews / show info on the screen ──
        if re.search(r"\breviews?\b|\bcritics\b", lo):
            # Extract the title being asked about.
            t = re.sub(r".*?\breviews?\s+(?:of|for)\s+", "", lo)
            if t == lo:  # "show me reviews game of thrones" (no of/for)
                t = re.sub(r".*?\breviews?\s+", "", lo)
            t = re.sub(r"\bon\s+the\s+(?:screen|dash\w*|big\s+screen|tv).*$"
                       r"|\band\s+(?:season|episode).*$", "", t).strip(" ,.?")
            if not t:
                return "Reviews of what, sir?"

            slug = re.sub(r"[^a-z0-9]+", "_", t).strip("_")
            # Wikipedia and Metacritic both allow iframing; Rotten Tomatoes
            # does not (X-Frame-Options), so the server will open it in its own
            # window and the tile will say so.
            wiki = ("https://en.wikipedia.org/wiki/"
                    + "_".join(w.capitalize() for w in t.split()))
            meta = f"https://www.metacritic.com/tv/{slug.replace('_','-')}/"
            post({
                "type": "web",
                "said": text,
                "subject": t.title(),   # so "play it" knows what "it" is
                "data": {"tiles": [
                    {"title": f"{t.title()} — overview", "url": wiki},
                    {"title": "Critics", "url": meta},
                ]},
            })
            return f"Reviews of {t.title()} on the screen, sir."

        # ── step navigation within a displayed recipe ──
        m = re.search(r"step\s+(\d+)", lo)
        if m:
            n = int(m.group(1))
            post({"type": "step", "n": n, "said": text})
            return f"Step {n}, sir."
        # named step ("the flambé step") — map the word to its instruction index
        m = re.search(r"(?:back\s+up\s+to|go\s+to|jump\s+to|show\s+me)\s+the\s+(\w+)\s+step", lo)
        if m:
            word = m.group(1)
            post({"type": "step_by_word", "word": word, "said": text})
            return f"The {word} step, sir."

        # ── recipe request ──
        # Strip the framing so the vault search gets just the dish name.
        # Two orderings occur in speech:
        #   "show me my recipe FOR cherries jubilee ..."  (name after)
        #   "put the cherries jubilee RECIPE on screen"   (name before)
        if re.search(r"\brecipes?\s+for\b", lo):
            q = re.sub(r".*?\brecipes?\s+for\s+", "", lo)
        elif re.search(r"\brecipes?\b", lo):
            # Name precedes "recipe" — take what's between the lead-in and it.
            q = re.sub(r"^(?:show|put|display|bring\s+up)\s+(?:me\s+)?(?:my\s+|the\s+)?", "", lo)
            q = re.sub(r"\s*\brecipes?\b.*$", "", q)
        else:
            q = re.sub(r"^(?:show|put|display|bring\s+up)\s+(?:me\s+)?(?:my\s+|the\s+)?", "", lo)
        # Drop any trailing framing in either case.
        q = re.sub(r"\bwith\s+the\s+video.*$"
                   r"|\bon\s+the\s+(?:screen|dash\w*|big\s+screen|tv).*$"
                   r"|\bit\s+came\s+from.*$", "", q)
        q = q.strip(" ,.?")

        if q:
            try:
                res = post({"type": "recipe", "q": q, "said": text})
                if res.get("delivered_to", 0) == 0:
                    return ("The recipe's ready, sir, but the screen isn't "
                            "showing the dashboard yet.")
                return "On the screen, sir."
            except urllib.error.HTTPError as e:
                if e.code == 404:
                    return f"I haven't found a recipe for {q}, sir."
                raise
        return "What would you like me to show you, sir?"

    def _handle_stt(self, data: dict):
        """Server-side STT using Whisper. Accepts base64-encoded audio (WAV/MP3/CAF)."""
        import tempfile, os, subprocess
        t0 = time.time()
        audio_b64 = data.get("audio_base64", "")
        if not audio_b64:
            self._json(400, {"error": "missing audio_base64"}); return
        try:
            audio_bytes = base64.b64decode(audio_b64)
        except Exception:
            self._json(400, {"error": "invalid base64 audio"}); return
        if len(audio_bytes) < 100:
            self._json(400, {"error": "audio too short"}); return

        # Write to temp file, convert to WAV for Whisper
        try:
            with tempfile.NamedTemporaryFile(suffix=".tmp", delete=False) as f:
                f.write(audio_bytes)
                tmp_path = f.name
            # Convert to 16kHz mono WAV if needed
            wav_path = tmp_path + ".wav"
            result = subprocess.run(
                ["/opt/homebrew/bin/ffmpeg", "-y", "-i", tmp_path, "-ar", "16000", "-ac", "1", wav_path],
                capture_output=True, text=True, timeout=10
            )
            if result.returncode != 0 or not os.path.exists(wav_path):
                # Try direct (already WAV?)
                os.rename(tmp_path, wav_path)
        except Exception as e:
            print(f"[stt] ffmpeg conversion failed: {e}")
            wav_path = tmp_path

        # Transcribe with Whisper
        try:
            import whisper
            if not hasattr(self, '_whisper_model'):
                print("[stt] Loading Whisper base.en model...")
                self._whisper_model = whisper.load_model("base.en")
                print("[stt] Whisper model loaded")
            result = self._whisper_model.transcribe(wav_path, fp16=False, language="en")
            text = result.get("text", "").strip()
            latency_ms = int((time.time() - t0) * 1000)
            print(f"[stt] Whisper transcribed '{text[:50]}' in {latency_ms}ms")
            self._json(200, {"text": text, "source": "whisper", "latency_ms": latency_ms})
        except Exception as e:
            print(f"[stt] Whisper failed: {e}")
            self._json(503, {"error": "whisper transcription failed", "detail": str(e)})
        finally:
            for p in (tmp_path, wav_path):
                try:
                    if os.path.exists(p):
                        os.unlink(p)
                except Exception:
                    pass

    def _handle_recommendations(self):
        """GET /recommendations?user=NAME — scored candidates for Flutter browse.
        Per-user: owner's viewing affinity re-ranks the candidate list."""
        try:
            import sys, os
            from urllib.parse import urlparse, parse_qs
            qs = parse_qs(urlparse(self.path).query)
            owner = (qs.get("user") or ["tom"])[0]
            sys.path.insert(0, os.path.expanduser("~/Public/GeezerAid_V10/tools"))
            from suggestion_engine import SuggestionEngine
            engine = SuggestionEngine(owner=owner)
            candidates = engine.candidates.get("candidates", [])
            candidates = engine._rank_by_affinity(candidates)
            # Take top 50, include all fields Flutter needs
            results = []
            for c in candidates[:50]:
                # Only show available_now and coming_soon (not future releases)
                availability = c.get("availability", "")
                if availability == "future":
                    continue
                results.append({
                    "type": c.get("type", "unknown"),
                    "service": c.get("service", "unknown"),
                    "title": c.get("title", ""),
                    "artist": c.get("artist", ""),
                    "description": c.get("description", ""),
                    "year": c.get("year", ""),
                    "genres": c.get("genres", []),
                    "match_score": c.get("match_score", 0),
                    "match_reason": c.get("match_reason", ""),
                    "vote_average": c.get("vote_average", 0),
                    "poster_path": c.get("poster_path", ""),
                    "url": c.get("url", ""),
                    "availability": availability,
                    "days_until": c.get("days_until", 0),
                })
            self._json(200, {
                "candidates": results,
                "count": len(results),
                "generated_at": engine.candidates.get("generated_at", ""),
            })
        except Exception as e:
            print(f"[recommendations] error: {e}")
            self._json(500, {"error": str(e), "candidates": []})

    def _handle_tools(self, data: dict):
        """Direct tool endpoint for programmatic access."""
        tool = data.get("tool")
        params = data.get("params", {})
        if tool == "memory_search":
            query = params.get("query", "")
            results = self.elder_brain.search(query, limit=params.get("limit", 5))
            self._json(200, {"tool": tool, "results": results})
        elif tool == "elderbrain_status":
            self._json(200, {"tool": tool, "status": self.elder_brain.quick_status()})
        else:
            self._json(400, {"error": f"Unknown tool: {tool}"})

    def _handle_hermes(self, data: dict):
        """Generic elder-brain query endpoint."""
        action = data.get("action", "memory")
        query = data.get("query", "")
        if action == "memory":
            results = self.elder_brain.search(query, limit=5)
            self._json(200, {"action": action, "results": results})
        elif action == "recent":
            results = self.elder_brain.list_recent(days=data.get("days", 7), limit=data.get("limit", 10))
            self._json(200, {"action": action, "results": results})
        else:
            self._json(400, {"error": f"Unknown action: {action}"})

    def log_message(self, fmt, *args):
        print(f"[{time.strftime('%H:%M:%S')}] {fmt % args}")

def main():
    # Preload the PII privacy filter in the background so startup stays fast and
    # the first frontier query doesn't stall on model download/init. (Phase 3, D)
    # Failures are non-fatal — redact_pii() degrades to passthrough.
    threading.Thread(target=_load_privacy_filter, daemon=True).start()
    p = argparse.ArgumentParser(description="GeezerAid V10 Server")
    p.add_argument("--port", type=int, default=PORT, help=f"Port (default {PORT})")
    p.add_argument("--host", default=HOST, help=f"Host (default {HOST})")
    args = p.parse_args()
    def port_in_use(port: int) -> bool:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            return s.connect_ex((args.host, port)) == 0
    if port_in_use(args.port):
        print(f"[WARNING] Port {args.port} in use.")
        alt = args.port + 1
        while port_in_use(alt) and alt < args.port + 10: alt += 1
        if not port_in_use(alt):
            print(f"[FIX] Using port {alt}"); args.port = alt
        else:
            print("[ERROR] No free port found."); sys.exit(1)
    print(f"\nGeezerAid V10 Server\nPort: {args.port} | TTS: {TTS_VOICE} | Hermes: {shutil.which('hermes') or 'NOT IN PATH'}\n")
    srv = ThreadingHTTPServer((args.host, args.port), ChatHandler)
    print(f"[READY] http://{args.host}:{args.port}/health")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n[SHUTDOWN] Server stopped."); srv.shutdown()

if __name__ == "__main__":
    import shutil
    main()
