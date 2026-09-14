from __future__ import annotations

import os
from pathlib import Path

import torch
from huggingface_hub import snapshot_download
from transformers import AutoConfig
from transformers import AutoModelForCausalLM

root = Path(__file__).resolve().parents[2]
cache = root / "model-cache" / "huggingface"
cache.mkdir(parents=True, exist_ok=True)
os.environ.setdefault("HF_HOME", str(cache))
os.environ.setdefault("HF_HUB_CACHE", str(cache / "hub"))

tokenizer_dir = root / "model-cache" / "starmie-v1"
snapshot_download("moondream/starmie-v1", local_dir=str(tokenizer_dir))
os.environ["MOONDREAM_TOKENIZER_PATH"] = str(tokenizer_dir)

# The pinned HF model code hard-codes the tokenizer repo. Patch only the
# ignored local cache so Windows can run without symlink privileges.
AutoConfig.from_pretrained("vikhyatk/moondream2", revision="2025-06-21", trust_remote_code=True, cache_dir=str(cache))
for module in cache.joinpath("modules", "transformers_modules").rglob("moondream.py"):
    text = module.read_text(encoding="utf-8")
    if "MOONDREAM_TOKENIZER_PATH" not in text:
        text = text.replace("import torch", "import os\nimport torch", 1)
        text = text.replace('Tokenizer.from_pretrained("moondream/starmie-v1")', 'Tokenizer.from_file(os.environ.get("MOONDREAM_TOKENIZER_PATH") + "/tokenizer.json") if os.environ.get("MOONDREAM_TOKENIZER_PATH") else Tokenizer.from_pretrained("moondream/starmie-v1")')
        module.write_text(text, encoding="utf-8")

print("Downloading official vikhyatk/moondream2 revision 2025-06-21")
model = AutoModelForCausalLM.from_pretrained(
    "vikhyatk/moondream2",
    revision="2025-06-21",
    trust_remote_code=True,
    cache_dir=str(cache),
    torch_dtype=torch.float16 if torch.cuda.is_available() else torch.float32,
)
del model
print(f"Cached under {cache}")
