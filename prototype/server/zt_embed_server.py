# -*- coding: utf-8 -*-
"""zt_embed_server.py —— 语义编码 GPU 服务（跑在实验室 8×2080Ti 服务器上）。

把 sentence-transformers 编码从本地 CPU 挪到 GPU 服务器：
  - 本地流水线（agent_cluster_v2 等）通过 ZT_EMBED_ENDPOINT 远程调用，
    本地不再加载模型（省显存/启动时间），采集层 870+ 条全量归簇成为日常可做；
  - 与本地同模型同参数（normalize_embeddings=True），结果可复现可对比。

部署（服务器上，一次性）：
  python3 -m venv ~/zt_nlp && ~/zt_nlp/bin/pip install torch sentence-transformers fastapi uvicorn
  # 模型缓存从本机 scp：.hf_cache/hub/models--* → ~/zt_models/hf_cache/hub/
  HF_HOME=~/zt_models/hf_cache HF_HUB_OFFLINE=1 nohup ~/zt_nlp/bin/python zt_embed_server.py >/dev/null 2>&1 &

接口：
  GET  /health → {"model","device","ready"}
  POST /embed  {"texts":[...]} → {"vectors":[[f32]...]}（L2 归一化）
"""
import os
from pathlib import Path

MODEL = os.environ.get("ZT_EMBED_MODEL", "paraphrase-multilingual-MiniLM-L12-v2")
PORT = int(os.environ.get("ZT_EMBED_PORT", "8765"))
HOST = os.environ.get("ZT_EMBED_HOST", "0.0.0.0")

os.environ.setdefault("HF_HUB_OFFLINE", "1")
os.environ.setdefault("HF_HUB_DISABLE_SYMLINKS_WARNING", "1")
os.environ.setdefault("HF_HUB_DISABLE_XET", "1")
os.environ.setdefault("TOKENIZERS_PARALLELISM", "false")

from fastapi import FastAPI
from pydantic import BaseModel
import torch
from sentence_transformers import SentenceTransformer

app = FastAPI(title="zt-embed")
_model: SentenceTransformer | None = None


def get_model() -> SentenceTransformer:
    global _model
    if _model is None:
        _model = SentenceTransformer(MODEL)
    return _model


class EmbedIn(BaseModel):
    texts: list[str]


@app.get("/health")
def health():
    m = get_model()
    return {"model": MODEL, "device": str(m.device), "ready": True}


@app.post("/embed")
def embed(inp: EmbedIn):
    m = get_model()
    vecs = m.encode(inp.texts, batch_size=64, show_progress_bar=False,
                    normalize_embeddings=True)
    return {"vectors": vecs.tolist()}


if __name__ == "__main__":
    import uvicorn
    print(f"zt-embed on {HOST}:{PORT} model={MODEL} torch={torch.__version__} "
          f"cuda={torch.cuda.is_available()}")
    uvicorn.run(app, host=HOST, port=PORT, log_level="warning")
