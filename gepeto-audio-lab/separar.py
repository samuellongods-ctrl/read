"""Processo de separação do Gepeto Audio Lab.

Roda em um processo separado (para poder ser cancelado) e conversa com o app.py
pela saída padrão:  STAGE <texto> · RESULT <json> · ERROR <mensagem>
"""
from __future__ import annotations

import argparse
import json
import logging
import re
import shutil
import sys
import time
from pathlib import Path

PEAKS = 180  # a página desenha 180 barras (viewBox 540 / 3)

MODELS = {
    "htdemucs": {"file": "htdemucs.yaml", "label": "Demucs v4 (htdemucs)"},
    "htdemucs_6s": {"file": "htdemucs_6s.yaml", "label": "Demucs v4 6 faixas (htdemucs_6s)"},
    "roformer": {"file": "vocals_mel_band_roformer.ckpt", "label": "MelBand RoFormer (Kim)"},
    "karaoke": {"file": "mel_band_roformer_karaoke_aufr33_viperx_sdr_10.1956.ckpt",
                "label": "MelBand RoFormer Karaoke (aufr33/viperx)"},
}

LABELS = {
    "vocals": "Voz", "drums": "Bateria", "bass": "Baixo", "other": "Outros",
    "guitar": "Guitarra", "piano": "Piano", "instrumental": "Instrumental (harmonia)",
    "lead": "Vocal principal", "backing": "Backing vocal",
}


def emit(kind: str, text: str) -> None:
    print(f"{kind} {text}".replace("\r", " "), flush=True)


def stage(text: str) -> None:
    emit("STAGE", text)


def stem_key(path: str) -> str:
    """Extrai o nome da faixa do arquivo gerado: musica_(Vocals)_modelo.wav -> vocals."""
    found = re.findall(r"_\(([^)]+)\)_", Path(path).name)
    name = (found[-1] if found else Path(path).stem).lower().replace(" ", "_")
    if name in ("no_vocals", "instrumental", "inst", "karaoke", "no_vocal"):
        return "instrumental"
    if name.startswith("vocal"):
        return "vocals"
    return name


class Runner:
    def __init__(self, models_dir: Path, work_dir: Path) -> None:
        from audio_separator.separator import Separator

        self.Separator = Separator
        self.models_dir = models_dir
        self.work_dir = work_dir
        self.used: list[str] = []

    def run(self, model: str, source: Path, step: str) -> dict[str, Path]:
        info = MODELS[model]
        out = self.work_dir / model
        out.mkdir(parents=True, exist_ok=True)
        separator = self.Separator(
            log_level=logging.WARNING,
            model_file_dir=str(self.models_dir),
            output_dir=str(out),
            output_format="WAV",
            normalization_threshold=1.0,  # mantém o volume relativo entre as faixas
        )
        stage(f"{step} · carregando {info['label']} (o primeiro uso baixa o modelo)")
        separator.load_model(model_filename=info["file"])
        stage(f"{step} · separando com {info['label']}")
        files = separator.separate(str(source))
        self.used.append(info["label"])
        stems: dict[str, Path] = {}
        for name in files:
            path = Path(name)
            if not path.is_absolute():
                path = out / path
            stems[stem_key(str(path))] = path
        return stems


def read(path: Path):
    import soundfile as sf
    data, rate = sf.read(str(path), dtype="float32", always_2d=True)
    return data, rate


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--perfil", required=True)
    parser.add_argument("--entrada", required=True)
    parser.add_argument("--saida", required=True)
    parser.add_argument("--modelos", required=True)
    args = parser.parse_args()

    source = Path(args.entrada)
    final_dir = Path(args.saida)
    work_dir = final_dir.parent / "tmp"
    shutil.rmtree(work_dir, ignore_errors=True)
    final_dir.mkdir(parents=True, exist_ok=True)
    work_dir.mkdir(parents=True, exist_ok=True)

    stage("Preparando os modelos de IA")
    try:
        import numpy as np
        import soundfile as sf
        runner = Runner(Path(args.modelos), work_dir)
    except ImportError as exc:
        emit("ERROR", f"Dependência ausente ({exc.name}). Rode o instalador (instalar.bat) novamente.")
        return 2

    import torch
    device = "GPU" if torch.cuda.is_available() else "CPU"
    started = time.time()
    profile = args.perfil
    order: list[str]
    stems: dict[str, Path]

    if profile == "four":
        stems = runner.run("htdemucs", source, "Etapa 1 de 1")
        order = ["vocals", "drums", "bass", "other"]
    elif profile == "six":
        stems = runner.run("htdemucs_6s", source, "Etapa 1 de 1")
        order = ["vocals", "drums", "bass", "guitar", "piano", "other"]
    elif profile == "vocal":
        found = runner.run("roformer", source, "Etapa 1 de 1")
        vocals = found.pop("vocals", None)
        rest = next(iter(found.values()), None)
        if not vocals or not rest:
            emit("ERROR", f"O modelo não gerou as faixas esperadas: {sorted(found)}")
            return 3
        stems = {"vocals": vocals, "instrumental": rest}
        order = ["vocals", "instrumental"]
    elif profile == "vocal_legacy":
        found = runner.run("htdemucs", source, "Etapa 1 de 2")
        stage("Etapa 2 de 2 · somando os instrumentos")
        parts = [read(found[key])[0] for key in ("drums", "bass", "other") if key in found]
        length = min(len(part) for part in parts)
        mix = np.clip(sum(part[:length] for part in parts), -1, 1)
        instrumental = work_dir / "instrumental.wav"
        sf.write(str(instrumental), mix, read(found["vocals"])[1])
        stems = {"vocals": found["vocals"], "instrumental": instrumental}
        order = ["vocals", "instrumental"]
    elif profile == "backing":
        band = runner.run("htdemucs_6s", source, "Etapa 1 de 2")
        voices = runner.run("karaoke", band["vocals"], "Etapa 2 de 2")
        lead = voices.pop("vocals", None)
        backing = next(iter(voices.values()), None)
        if not lead or not backing:
            emit("ERROR", f"O modelo de vozes não gerou as faixas esperadas: {sorted(voices)}")
            return 3
        stems = {**band, "lead": lead, "backing": backing}
        stems.pop("vocals", None)
        order = ["lead", "backing", "drums", "bass", "guitar", "piano", "other"]
    else:
        emit("ERROR", f"Modo desconhecido: {profile}")
        return 2

    missing = [key for key in order if key not in stems]
    if missing:
        emit("ERROR", f"O modelo não gerou as faixas: {', '.join(missing)}")
        return 3

    stage("Finalizando as faixas em WAV")
    tracks = []
    for number, key in enumerate(order, start=1):
        data, rate = read(stems[key])
        data = np.clip(data, -1, 1)
        label = LABELS.get(key, key.title())
        filename = f"{number:02d} {label}.wav"
        sf.write(str(final_dir / filename), data, rate, subtype="PCM_16")
        mono = np.abs(data).max(axis=1)
        windows = np.array_split(mono, PEAKS) if len(mono) >= PEAKS else [mono]
        peaks = [round(float(window.max()) if len(window) else 0.0, 4) for window in windows]
        tracks.append({"id": key, "label": label, "file": filename, "peaks": peaks})

    shutil.rmtree(work_dir, ignore_errors=True)
    main_model = {"four": "htdemucs", "six": "htdemucs_6s", "vocal": "roformer",
                  "vocal_legacy": "htdemucs", "backing": "htdemucs_6s"}[profile]
    provenance = {
        "model": {"id": MODELS[main_model]["file"], "label": MODELS[main_model]["label"]},
        "models": runner.used,
        "device": device,
        "seconds": round(time.time() - started, 1),
    }
    emit("RESULT", json.dumps({"tracks": tracks, "provenance": provenance}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except Exception as exc:  # noqa: BLE001
        import traceback
        traceback.print_exc()
        message = str(exc).replace("\n", "\\n")[:800]
        emit("ERROR", f"{type(exc).__name__}: {message}")
        sys.exit(1)
