#!/usr/bin/env python3
"""VoxCPM2 MPS spike — load on Apple Silicon, synthesize one sentence, time it.
Goal: answer 'can GA use VoxCPM2 at all on the MBP?' (latency + memory + quality)."""
import time, sys, os
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

print("=== VoxCPM2 MPS spike ===", flush=True)
t0 = time.time()
from voxcpm import VoxCPM
import torch
print(f"torch {torch.__version__} MPS={torch.backends.mps.is_available()}", flush=True)

# 1. Load (time it)
t_load0 = time.time()
model = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)
t_load = time.time() - t_load0
print(f"LOAD: {t_load:.1f}s", flush=True)

# Memory after load
try:
    import resource
    print(f"mem RSS: {resource.getrusage(resource.RUSAGE_SELF).ru_maxrss/1e9:.1f} GB", flush=True)
except Exception as e:
    print(f"mem check skipped: {e}", flush=True)

# 2. Generate one sentence (time it)
text = "Good afternoon, sir. Shall I find something good on the television for you this evening?"
t_gen0 = time.time()
wav = model.generate(
    text=text,
    cfg_value=2.0,
    inference_timesteps=10,
)
t_gen = time.time() - t_gen0
print(f"GENERATE: {t_gen:.1f}s for {len(text)} chars", flush=True)

# 3. Save + report
sr = model.tts_model.sample_rate
import soundfile as sf
sf.write("/tmp/voxcpm_spike.wav", wav, sr)
dur = len(wav) / sr
print(f"WAV: {dur:.1f}s audio @ {sr}Hz -> /tmp/voxcpm_spike.wav", flush=True)
print(f"RTF: {t_gen/dur:.2f}x", flush=True)
print("=== SPIKE DONE ===", flush=True)
