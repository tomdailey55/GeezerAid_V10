#!/usr/bin/env python3
"""VoxCPM2 Voice Design — Jeeves persona refinement. Inspired-by description."""
import time, os
os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
from voxcpm import VoxCPM
import soundfile as sf

print("=== Jeeves persona voice ===", flush=True)
model = VoxCPM.from_pretrained("openbmb/VoxCPM2", load_denoiser=False)
print("loaded", flush=True)

DESC = (
    "An immaculate English valet from the late Victorian era, late middle-aged. "
    "Cultivated received pronunciation, precise and courteous, with the dry, "
    "wry wit and quiet authority of a perfect gentleman's gentleman. "
    "A hint of sardonic good humor beneath flawless composure."
)

TEXTS = [
    "Good evening, sir. Might I suggest the study is rather more suited to a spot of contemplation this evening?",
    "I shall see to it at once, madam. Though I confess the carpet arithmetic does rather strain the patience.",
    "Very good, sir. I have taken the liberty of laying out the figures for the living room and the master bedroom.",
]

os.makedirs("/tmp/voxcpm_jeeves", exist_ok=True)
for i, txt in enumerate(TEXTS):
    prompt = f"({DESC}){txt}"
    t = time.time()
    wav = model.generate(text=prompt, cfg_value=2.0, inference_timesteps=10)
    sr = model.tts_model.sample_rate
    out = f"/tmp/voxcpm_jeeves/jeeves_persona_{i+1}.wav"
    sf.write(out, wav, sr)
    print(f"{i+1}: {len(wav)/sr:.1f}s in {time.time()-t:.1f}s -> {out}", flush=True)
print("DONE", flush=True)
