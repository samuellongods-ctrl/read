"""Gepeto Audio Lab: servidor local que serve a página e faz a separação de áudio.

Uso:  python app.py [--host 0.0.0.0] [--porta 8000]
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
import uuid
import zipfile
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

VERSION = "1.0.0"
BASE = Path(__file__).resolve().parent
WEB = BASE / "web"
DATA = Path(os.environ.get("GEPETO_DADOS", BASE / "dados"))
JOBS_DIR = DATA / "trabalhos"
DOWNLOADS_DIR = DATA / "downloads"
FILES_DIR = DATA / "arquivos"
MODELS_DIR = DATA / "modelos"
BIN_DIR = BASE / "bin"

# Navegador de onde o yt-dlp lê os cookies do YouTube (evita o "confirme que você não é um robô").
# Mude com a variável GEPETO_COOKIES (chrome, edge, firefox...) ou deixe vazia / "nenhum" para desligar.
COOKIES_BROWSER = os.environ.get("GEPETO_COOKIES", "chrome").strip().lower()
if COOKIES_BROWSER in ("", "nenhum", "none", "0"):
    COOKIES_BROWSER = ""

MAX_BYTES = 150 * 1024 * 1024
MAX_SHARED_BYTES = 1024 * 1024 * 1024  # limite de cada arquivo enviado em "Arquivos entre aparelhos"
MAX_SECONDS = 15 * 60
AUDIO_EXT = {".mp3", ".wav", ".flac", ".m4a", ".ogg", ".aac", ".aiff", ".opus"}
PROFILES = {"four", "six", "vocal", "vocal_legacy", "backing"}

for folder in (JOBS_DIR, DOWNLOADS_DIR, FILES_DIR, MODELS_DIR):
    folder.mkdir(parents=True, exist_ok=True)


# ---------------------------------------------------------------- ffmpeg

def ensure_ffmpeg() -> str | None:
    """Garante um ffmpeg no PATH. Usa o do sistema ou o do pacote imageio-ffmpeg."""
    exe_name = "ffmpeg.exe" if os.name == "nt" else "ffmpeg"
    local = BIN_DIR / exe_name
    if local.exists():
        os.environ["PATH"] = str(BIN_DIR) + os.pathsep + os.environ.get("PATH", "")
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg
        source = Path(imageio_ffmpeg.get_ffmpeg_exe())
        BIN_DIR.mkdir(exist_ok=True)
        shutil.copy2(source, local)
        os.environ["PATH"] = str(BIN_DIR) + os.pathsep + os.environ.get("PATH", "")
        return str(local)
    except Exception:
        return None


FFMPEG = ensure_ffmpeg()


def detect_device() -> str:
    try:
        out = subprocess.run(
            [sys.executable, "-c", "import torch;print('GPU' if torch.cuda.is_available() else 'CPU')"],
            capture_output=True, text=True, timeout=60,
        )
        return out.stdout.strip() or "CPU"
    except Exception:
        return "CPU"


DEVICE = "CPU"


# ---------------------------------------------------------------- trabalhos

class Store:
    def __init__(self) -> None:
        self.lock = threading.Lock()
        self.jobs: dict[str, dict] = {}
        self.procs: dict[str, subprocess.Popen] = {}
        self.load()

    def load(self) -> None:
        for path in JOBS_DIR.glob("*/job.json"):
            try:
                job = json.loads(path.read_text("utf-8"))
            except Exception:
                continue
            if job.get("status") in ("running", "uploading"):
                job["status"] = "error"
                job["error"] = "O aplicativo foi fechado durante o processamento. Tente novamente."
                self._write(job)
            self.jobs[job["id"]] = job

    def _write(self, job: dict) -> None:
        folder = JOBS_DIR / job["id"]
        folder.mkdir(parents=True, exist_ok=True)
        tmp = folder / "job.json.tmp"
        tmp.write_text(json.dumps(job, ensure_ascii=False, indent=1), "utf-8")
        os.replace(tmp, folder / "job.json")

    def save(self, job: dict) -> None:
        with self.lock:
            self.jobs[job["id"]] = job
            self._write(job)

    def update(self, job_id: str, **fields) -> dict:
        with self.lock:
            job = self.jobs[job_id]
            if job["status"] == "cancelled" and fields.get("status") != "cancelled":
                return job
            job.update(fields)
            self._write(job)
            return job

    def get(self, job_id: str) -> dict:
        job = self.jobs.get(job_id)
        if not job:
            raise HTTPException(404, "Música não encontrada na biblioteca.")
        return job

    def busy(self) -> bool:
        return any(job["status"] in ("running", "uploading") for job in self.jobs.values())

    def listing(self) -> list[dict]:
        return sorted(self.jobs.values(), key=lambda job: job["created"], reverse=True)


store = Store()


def public(job: dict) -> dict:
    return {key: value for key, value in job.items() if not key.startswith("_")}


def safe_name(text: str, fallback: str = "audio") -> str:
    text = re.sub(r'[\\/:*?"<>|\x00-\x1f]', "", text).strip().strip(".")
    return text[:120] or fallback


PERCENT = re.compile(r"(\d{1,3})%\|")


def follow_stderr(job_id: str, proc: subprocess.Popen, log_file, current: dict) -> None:
    """Copia o stderr para o log e mostra o percentual das barras de progresso (tqdm) na página."""
    import codecs
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    buffer = ""
    last = -1
    while True:
        raw = os.read(proc.stderr.fileno(), 4096)  # devolve o que já chegou, sem esperar encher
        if not raw:
            break
        buffer += decoder.decode(raw)
        parts = re.split(r"[\r\n]", buffer)
        buffer = parts.pop()
        if PERCENT.search(buffer):  # a barra do tqdm chega inteira, sem quebra de linha no fim
            parts.append(buffer)
            buffer = ""
        for part in parts:
            if not part.strip():
                continue
            match = PERCENT.search(part)
            if match and "iB/s" in part and current["stage"]:
                percent = int(match.group(1))
                if percent != last:
                    last = percent
                    store.update(job_id, stage=f"{current['stage']} · baixando modelo {percent}%")
            elif match and current["stage"]:
                percent = int(match.group(1))
                if percent != last:
                    last = percent
                    store.update(job_id, stage=f"{current['stage']} · {percent}%")
            else:
                log_file.write(part + "\n")
                log_file.flush()
    if buffer.strip():
        log_file.write(buffer + "\n")


def run_job(job_id: str) -> None:
    job = store.jobs[job_id]
    folder = JOBS_DIR / job_id
    source = folder / job["_input"]
    wav = folder / "original.wav"
    log = folder / "processamento.log"
    try:
        if not FFMPEG:
            raise RuntimeError("ffmpeg não foi encontrado. Rode o instalador novamente.")
        store.update(job_id, stage="Convertendo o áudio para WAV")
        convert = subprocess.run(
            [FFMPEG, "-y", "-v", "error", "-i", str(source), "-vn", "-ac", "2", "-ar", "44100",
             "-c:a", "pcm_s16le", str(wav)],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
        if convert.returncode != 0 or not wav.exists():
            raise RuntimeError("Não foi possível ler este arquivo de áudio.\n" + convert.stderr[-600:])
        import wave
        with wave.open(str(wav)) as handle:
            duration = handle.getnframes() / handle.getframerate()
        if duration > MAX_SECONDS:
            raise RuntimeError("O limite é de 15 minutos por música.")
        if duration < 1:
            raise RuntimeError("O áudio é curto demais para separar.")
        store.update(job_id, duration=round(duration, 3))
        if store.jobs[job_id]["status"] == "cancelled":
            return

        command = [sys.executable, "-u", str(BASE / "separar.py"), "--perfil", job["profile"],
                   "--entrada", str(wav), "--saida", str(folder / "faixas"), "--modelos", str(MODELS_DIR)]
        env = {**os.environ, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        with open(log, "w", encoding="utf-8") as log_file:
            proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                                    encoding="utf-8", errors="replace", env=env, creationflags=flags)
            store.procs[job_id] = proc
            current = {"stage": ""}
            reader = threading.Thread(target=follow_stderr, args=(job_id, proc, log_file, current), daemon=True)
            reader.start()
            result = None
            error = None
            for line in proc.stdout:
                line = line.rstrip("\n")
                if line.startswith("STAGE "):
                    current["stage"] = line[6:]
                    store.update(job_id, stage=line[6:])
                elif line.startswith("RESULT "):
                    result = json.loads(line[7:])
                elif line.startswith("ERROR "):
                    error = line[6:].replace("\\n", "\n")
            proc.wait()
            reader.join(timeout=5)
            store.procs.pop(job_id, None)
        if store.jobs[job_id]["status"] == "cancelled":
            return
        if proc.returncode != 0 or not result:
            if not error:
                tail = log.read_text("utf-8", errors="replace").strip().splitlines()[-6:]
                error = "O processo de separação terminou com erro.\n" + "\n".join(tail)
            raise RuntimeError(error)
        tracks = result["tracks"]
        for track in tracks:
            track["_path"] = str(Path("faixas") / track["file"])
        provenance = {**result.get("provenance", {}), "app": f"Gepeto Audio Lab {VERSION}",
                      "profile": job["profile"], "finished": time.time()}
        store.update(job_id, status="done", stage="Concluído", tracks=tracks, provenance=provenance)
        wav.unlink(missing_ok=True)
    except Exception as exc:  # noqa: BLE001 - qualquer falha vira mensagem para a página
        store.update(job_id, status="error", error=str(exc), stage="Erro")


def worker_loop() -> None:
    while True:
        pending = [job for job in store.listing() if job["status"] == "running" and not job.get("_started")]
        if pending:
            job = pending[-1]
            store.update(job["id"], _started=True)
            run_job(job["id"])
        else:
            time.sleep(0.5)


# ---------------------------------------------------------------- API

app = FastAPI(title="Gepeto Audio Lab", version=VERSION, docs_url=None, redoc_url=None)

import links  # noqa: E402  (links salvos: rotas /api/links e /links.js)
app.include_router(links.router)


@app.middleware("http")
async def local_header(request: Request, call_next):
    # Pedidos que alteram dados precisam do cabeçalho enviado pela página (proteção contra CSRF).
    if request.url.path.startswith("/api/") and request.method not in ("GET", "HEAD", "OPTIONS"):
        if request.headers.get("x-gepeto-local") != "1":
            return JSONResponse({"detail": "Pedido recusado: cabeçalho X-Gepeto-Local ausente."}, 403)
    return await call_next(request)


@app.get("/")
def index():
    return FileResponse(WEB / "index.html", headers={"Cache-Control": "no-cache"})


@app.get("/api/info")
def info():
    return {"app": "Gepeto Audio Lab", "version": VERSION, "device": DEVICE, "ffmpeg": bool(FFMPEG)}


@app.get("/api/jobs")
def list_jobs():
    return [public(job) for job in store.listing()]


@app.post("/api/jobs")
async def create_job(file: UploadFile = File(...), profile: str = Form("vocal")):
    if profile not in PROFILES:
        raise HTTPException(400, "Modo de separação desconhecido.")
    name = Path(file.filename or "audio").name
    ext = Path(name).suffix.lower()
    if ext not in AUDIO_EXT:
        raise HTTPException(400, "Escolha um arquivo de áudio compatível.")
    if store.busy():
        raise HTTPException(409, "Já existe uma separação em andamento. Aguarde ou cancele antes de começar outra.")
    job_id = uuid.uuid4().hex[:12]
    folder = JOBS_DIR / job_id
    folder.mkdir(parents=True)
    target = folder / f"entrada{ext}"
    size = 0
    with open(target, "wb") as out:
        while chunk := await file.read(1024 * 1024):
            size += len(chunk)
            if size > MAX_BYTES:
                out.close()
                shutil.rmtree(folder, ignore_errors=True)
                raise HTTPException(413, "O limite é de 150 MB por arquivo.")
            out.write(chunk)
    if not size:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(400, "Este arquivo está vazio.")
    job = {"id": job_id, "name": Path(name).stem, "file": name, "profile": profile, "status": "running",
           "stage": "Na fila para processar", "created": time.time(), "duration": 0, "tracks": [],
           "provenance": {}, "error": None, "_input": target.name}
    store.save(job)
    return public(job)


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str):
    job = store.get(job_id)
    if job["status"] != "running":
        return public(job)
    store.update(job_id, status="cancelled", stage="Cancelado")
    proc = store.procs.get(job_id)
    if proc and proc.poll() is None:
        try:
            if os.name == "nt":
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)], capture_output=True)
            else:
                proc.kill()
        except Exception:
            pass
    return public(store.jobs[job_id])


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str):
    return public(store.get(job_id))


@app.delete("/api/jobs/{job_id}")
def delete_job(job_id: str):
    job = store.get(job_id)
    if job["status"] == "running":
        raise HTTPException(409, "Cancele o processamento antes de apagar.")
    with store.lock:
        store.jobs.pop(job_id, None)
    shutil.rmtree(JOBS_DIR / job_id, ignore_errors=True)
    return {"ok": True}


@app.get("/api/jobs/{job_id}/tracks/{track_id}")
def get_track(job_id: str, track_id: str):
    job = store.get(job_id)
    track = next((item for item in job.get("tracks", []) if item["id"] == track_id), None)
    if not track:
        raise HTTPException(404, "Faixa não encontrada.")
    path = JOBS_DIR / job_id / track["_path"]
    if not path.exists():
        raise HTTPException(404, "O arquivo desta faixa não está mais no computador.")
    return FileResponse(path, media_type="audio/wav", filename=track["file"])


@app.get("/api/jobs/{job_id}/zip")
def get_zip(job_id: str):
    job = store.get(job_id)
    if job["status"] != "done":
        raise HTTPException(409, "As faixas ainda não estão prontas.")
    folder = JOBS_DIR / job_id
    target = folder / "faixas.zip"
    if not target.exists():
        tmp = folder / "faixas.zip.tmp"
        with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as archive:
            for track in job["tracks"]:
                archive.write(folder / track["_path"], track["file"])
        os.replace(tmp, target)
    return FileResponse(target, media_type="application/zip", filename=f"{safe_name(job['name'])} - faixas.zip")


# ---------------------------------------------------------------- YouTube

class YoutubeRequest(BaseModel):
    url: str
    format: str = "mp3"
    auto_import: bool = False
    name: str = ""


@app.post("/api/youtube")
def youtube(body: YoutubeRequest):
    url = body.url.strip()
    if not re.match(r"^https?://", url, re.I):
        raise HTTPException(400, "Por favor, insira um link do YouTube válido.")
    if body.format not in ("mp3", "mp4"):
        raise HTTPException(400, "Formato inválido. Use MP3 ou MP4.")
    try:
        import yt_dlp
    except ImportError:
        raise HTTPException(500, "O yt-dlp não está instalado. Rode o instalador novamente.")
    if not FFMPEG:
        raise HTTPException(500, "ffmpeg não foi encontrado. Rode o instalador novamente.")

    download_id = uuid.uuid4().hex[:12]
    folder = DOWNLOADS_DIR / download_id
    folder.mkdir(parents=True)
    options = {
        "outtmpl": str(folder / "%(title).150B.%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "no_warnings": True,
        "restrictfilenames": False,
        "windowsfilenames": True,
        "ffmpeg_location": FFMPEG,
        "max_filesize": 1024 * 1024 * 1024,
    }
    if body.format == "mp3":
        options.update({
            "format": "bestaudio/best",
            "postprocessors": [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3", "preferredquality": "320"}],
        })
    else:
        options.update({
            "format": "bv*[ext=mp4]+ba[ext=m4a]/bv*+ba/b[ext=mp4]/b",
            "merge_output_format": "mp4",
        })
    def download(opts: dict):
        with yt_dlp.YoutubeDL(opts) as ydl:
            return ydl.extract_info(url, download=True)

    try:
        if COOKIES_BROWSER:
            try:
                info = download({**options, "cookiesfrombrowser": (COOKIES_BROWSER,)})
            except Exception as exc:  # noqa: BLE001
                # Chrome aberto/bloqueado ou cookies ilegíveis: tenta de novo sem cookies.
                if not re.search(r"cookie|dpapi|decrypt|database|profile", str(exc), re.I):
                    raise
                for leftover in folder.iterdir():
                    leftover.unlink(missing_ok=True)
                info = download(options)
        else:
            info = download(options)
    except Exception as exc:  # noqa: BLE001
        shutil.rmtree(folder, ignore_errors=True)
        text = re.sub(r"\x1b\[[0-9;]*m", "", str(exc)).replace("ERROR: ", "")
        raise HTTPException(400, f"Não foi possível baixar este link. {text[:400]}")
    files = [path for path in folder.iterdir() if path.suffix.lower() == f".{body.format}"]
    if not files:
        shutil.rmtree(folder, ignore_errors=True)
        raise HTTPException(500, "O download terminou, mas o arquivo final não foi gerado.")
    final = files[0]
    custom = safe_name(body.name, "") if body.name.strip() else ""
    if custom:
        renamed = final.with_name(f"{custom}{final.suffix}")
        final.replace(renamed)
        final = renamed
    if body.format == "mp3" and final.stat().st_size > MAX_BYTES and body.auto_import:
        raise HTTPException(413, "O áudio baixado passa de 150 MB e não pode ser separado.")
    title = custom or (info or {}).get("title") or final.stem
    return {"title": title, "file": final.name, "format": body.format,
            "download_url": f"/api/downloads/{download_id}/{final.name}"}


@app.get("/api/downloads/{download_id}/{filename}")
def get_download(download_id: str, filename: str):
    if not re.fullmatch(r"[0-9a-f]{12}", download_id):
        raise HTTPException(404, "Arquivo não encontrado.")
    folder = DOWNLOADS_DIR / download_id
    path = folder / Path(filename).name
    if not path.is_file() or path.parent != folder:
        raise HTTPException(404, "Arquivo não encontrado.")
    media = "audio/mpeg" if path.suffix.lower() == ".mp3" else "video/mp4"
    return FileResponse(path, media_type=media, filename=path.name)


# ---------------------------------------------------------------- arquivos entre aparelhos

def shared_entry(folder: Path) -> dict | None:
    items = [item for item in folder.iterdir() if item.is_file()] if folder.is_dir() else []
    if not items:
        return None
    path = items[0]
    stat = path.stat()
    return {"id": folder.name, "name": path.name, "size": stat.st_size, "created": stat.st_mtime}


@app.get("/api/files")
def list_shared_files():
    entries = [entry for entry in (shared_entry(folder) for folder in FILES_DIR.iterdir()) if entry]
    return sorted(entries, key=lambda entry: entry["created"], reverse=True)


@app.post("/api/files")
async def upload_shared_files(files: list[UploadFile] = File(...)):
    saved = []
    for upload in files:
        name = safe_name(Path(upload.filename or "arquivo").name, "arquivo")
        file_id = uuid.uuid4().hex[:12]
        folder = FILES_DIR / file_id
        folder.mkdir(parents=True)
        target = folder / name
        size = 0
        too_big = False
        with open(target, "wb") as out:
            while chunk := await upload.read(1024 * 1024):
                size += len(chunk)
                if size > MAX_SHARED_BYTES:
                    too_big = True
                    break
                out.write(chunk)
        if too_big or not size:
            shutil.rmtree(folder, ignore_errors=True)
            if too_big:
                raise HTTPException(413, f"O arquivo \"{name}\" passa do limite de 1 GB.")
            raise HTTPException(400, f"O arquivo \"{name}\" está vazio.")
        saved.append(shared_entry(folder))
    return saved


@app.get("/api/files/{file_id}/download")
def download_shared_file(file_id: str):
    if not re.fullmatch(r"[0-9a-f]{12}", file_id):
        raise HTTPException(404, "Arquivo não encontrado.")
    entry = shared_entry(FILES_DIR / file_id)
    if not entry:
        raise HTTPException(404, "Arquivo não encontrado.")
    # Sempre como anexo e sem adivinhar o tipo, para um HTML enviado nunca rodar dentro do app.
    return FileResponse(FILES_DIR / file_id / entry["name"], filename=entry["name"],
                        media_type="application/octet-stream",
                        headers={"X-Content-Type-Options": "nosniff"})


@app.delete("/api/files/{file_id}")
def delete_shared_file(file_id: str):
    if not re.fullmatch(r"[0-9a-f]{12}", file_id):
        raise HTTPException(404, "Arquivo não encontrado.")
    folder = FILES_DIR / file_id
    if not folder.is_dir():
        raise HTTPException(404, "Arquivo não encontrado.")
    shutil.rmtree(folder, ignore_errors=True)
    return {"ok": True}


# ---------------------------------------------------------------- início

def lan_addresses() -> list[str]:
    found: list[str] = []
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as probe:
            probe.connect(("10.255.255.255", 1))
            found.append(probe.getsockname()[0])
    except OSError:
        pass
    try:
        for item in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            address = item[4][0]
            if address not in found and not address.startswith("127."):
                found.append(address)
    except OSError:
        pass
    return found


def main() -> None:
    global DEVICE
    parser = argparse.ArgumentParser(description="Gepeto Audio Lab")
    parser.add_argument("--host", default=os.environ.get("GEPETO_HOST", "0.0.0.0"))
    parser.add_argument("--porta", "--port", type=int, default=int(os.environ.get("GEPETO_PORTA", "8000")))
    parser.add_argument("--abrir", action="store_true", help="abre o navegador ao iniciar")
    args = parser.parse_args()

    DEVICE = detect_device()
    threading.Thread(target=worker_loop, daemon=True).start()

    line = "=" * 60
    print(line)
    print(f"  Gepeto Audio Lab {VERSION}  ·  processamento: {DEVICE}")
    print(f"  Neste computador:   http://127.0.0.1:{args.porta}")
    if args.host in ("0.0.0.0", ""):
        for address in lan_addresses():
            print(f"  Na rede (IPv4):     http://{address}:{args.porta}")
    else:
        print(f"  Endereço:           http://{args.host}:{args.porta}")
    if not FFMPEG:
        print("  ATENÇÃO: ffmpeg não encontrado. Rode o instalador novamente.")
    print(f"  Arquivos salvos em: {DATA}")
    if COOKIES_BROWSER:
        print(f"  YouTube: usando os cookies do navegador ({COOKIES_BROWSER})")
    print("  Para encerrar, feche esta janela ou aperte Ctrl+C.")
    print(line, flush=True)

    if args.abrir:
        import webbrowser
        threading.Timer(2.0, webbrowser.open, [f"http://127.0.0.1:{args.porta}"]).start()

    import uvicorn
    uvicorn.run(app, host=args.host, port=args.porta, log_level="warning")


if __name__ == "__main__":
    main()
