#!/usr/bin/env python3
"""VoxCPM2 Voice Design spike — create a Jeeves persona from description only."""
import time, os
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")

print("=== VoxCPM2 Voice Design spike ===", flush=True)
from voxcpm import VoxCPM
import soundfile as sf

t0 = time.time()
model = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)
print(f"LOAD: {time.time()-t0:.1f}s", flush=True)

# Jeeves persona via natural-language description (no reference audio)
# Format: "(voice description)Text to synthesize."
DESCRIPTIONS = [
    "A warm, dignified English butler in his mid-50s, calm and reassuring, with a refined and gently authoritative tone.",
    "A cheerful, friendly elderly gentleman, gentle and unhurried, with a soft warm voice and a hint of good humor.",
]

VOICES_TEXTS = [
    "Good afternoon, sir. I've taken the liberty of looking up the local carpet prices. Shall we have a look at the living room measurements?",
    "Good morning, Andrea. The weather today looks pleasant, so it might be a lovely day for a short walk in the garden.",
]

os.makedirs("/tmp/voxcpm_voice", exist_ok=True)
for i, (desc, txt) in enumerate(zip(DESCRIPTIONS, VOICES_TEXTS)):
    prompt = f"({desc}){txt}"
    print(f"--- voice {i+1}: {desc[:40]}... ---", flush=True)
    t_gen = time.time()
    wav = model.generate(text=prompt, cfg_value=2.0, inference_timesteps=10)
    sr = model.tts_model.sample_rate
    out = f"/tmp/voxcpm_voice/jeeves_{i+1}.wav"
    sf.write(out, wav, sr)
    dur = len(wav)/sr
    print(f"  generated {dur:.1f}s in {time.time()-t_gen:.1f}s -> {out}", flush=True)

print("=== VOICE DESIGN DONE ===", flush=True)
