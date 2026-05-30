# local_llm — DFlash-MLX OpenAI server

A local LLM endpoint for Borealis, served with **[DFlash](https://z-lab.ai/projects/dflash/)**
block-diffusion **speculative decoding** on Apple Silicon via the
[`dflash-mlx`](https://github.com/bstnxbt/dflash-mlx) library.

DFlash pairs a small **draft** model (proposes a block of tokens in one parallel
pass) with the full **target** model (verifies them). Because the target verifies
every token, the output is **bit-for-bit identical to plain target decoding** — it
is pure latency reduction (up to ~6×), not a quality trade-off.

The server exposes an **OpenAI-compatible API**, so anything that speaks the
OpenAI protocol (the `openai` SDK, `curl`, LangChain, etc.) can call it.

## Layout
```
local_llm/
  .venv/        Python 3.11 virtualenv (created with uv; gitignored)
  serve.sh      launches the OpenAI-compatible DFlash server
  README.md     this file
```

## Setup (already done, for reference)
```bash
cd local_llm
python3.12 -m venv .venv
.venv/bin/python -m pip install --upgrade pip
.venv/bin/python -m pip install -r requirements.txt   # or: pip install dflash-mlx
```
Requires Python 3.10+ (this venv uses 3.12) and an Apple-Silicon Mac (MLX/Metal).

## Models
Target models live under `~/Downloads/Models`. A "model" is any directory
containing a `config.json`. The matching DFlash **draft** is auto-resolved from
the [z-lab HuggingFace registry](https://huggingface.co/z-lab) for supported
targets, so you usually only need the target.

Supported target → draft pairs (`dflash models`):

| Target            | Draft (auto-pulled)              |
|-------------------|----------------------------------|
| Qwen3.5-4B        | z-lab/Qwen3.5-4B-DFlash          |
| Qwen3.5-9B        | z-lab/Qwen3.5-9B-DFlash          |
| Qwen3.5-27B       | z-lab/Qwen3.5-27B-DFlash         |
| Qwen3.5-35B-A3B   | z-lab/Qwen3.5-35B-A3B-DFlash     |
| Qwen3.6-27B       | z-lab/Qwen3.6-27B-DFlash         |
| Qwen3.6-35B-A3B   | z-lab/Qwen3.6-35B-A3B-DFlash     |
| Qwen3-4B          | z-lab/Qwen3-4B-DFlash-b16        |
| Qwen3-8B          | z-lab/Qwen3-8B-DFlash-b16        |
| gemma-4-31b-it    | z-lab/gemma-4-31B-it-DFlash      |
| gemma-4-26b-a4b-it| z-lab/gemma-4-26B-A4B-it-DFlash  |

## Run
```bash
./serve.sh                          # auto-discovers the model in ~/Downloads/Models
MODEL="Qwen3.6-27B-4bit" ./serve.sh # pick a model by folder name
MODEL=/abs/path/to/model ./serve.sh # or an absolute path / HF repo id
PORT=8001 ./serve.sh                # change the port (default 8000)
DRAFT=/abs/path/to/draft ./serve.sh # force a local draft (otherwise auto-resolved)
```
Env vars: `MODEL`, `DRAFT`, `MODELS_DIR` (default `~/Downloads/Models`),
`HOST` (default `127.0.0.1`), `PORT` (default `8000`). Any extra args are passed
straight through to `dflash serve` (run `.venv/bin/dflash serve --help` for the
full list, e.g. `--temp`, `--max-tokens`, `--enable-thinking`).

## Call it
The endpoint is `http://127.0.0.1:8000/v1`.

curl:
```bash
curl http://127.0.0.1:8000/v1/chat/completions \
  -H "Content-Type: application/json" \
  -d '{
    "model": "local",
    "messages": [{"role": "user", "content": "Two-sentence summary of speculative decoding."}]
  }'
```

OpenAI Python SDK:
```python
from openai import OpenAI

client = OpenAI(base_url="http://127.0.0.1:8000/v1", api_key="not-needed")
resp = client.chat.completions.create(
    model="local",
    messages=[{"role": "user", "content": "Hello!"}],
)
print(resp.choices[0].message.content)
```

## Troubleshooting
- `no model found under ~/Downloads/Models` — set `MODEL` to a folder name, an
  absolute path, or a HuggingFace repo id.
- `multiple models found` — set `MODEL` to choose one.
- Environment check: `.venv/bin/dflash doctor`
