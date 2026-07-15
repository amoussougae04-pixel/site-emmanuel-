from __future__ import annotations

import os
import shutil
import subprocess
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

from fastapi import BackgroundTasks, FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

BASE_DIR = Path(__file__).resolve().parent.parent
APP_DATA = BASE_DIR / "app_data"
UPLOADS_DIR = APP_DATA / "uploads"
JOBS_DIR = APP_DATA / "jobs"
OUTPUTS_DIR = APP_DATA / "outputs"
AUDIO_DIR = APP_DATA / "audio"
SUBTITLES_DIR = APP_DATA / "subtitles"
TEMPLATES_DIR = BASE_DIR / "templates"
STATIC_DIR = BASE_DIR / "static"

for folder in [UPLOADS_DIR, JOBS_DIR, OUTPUTS_DIR, AUDIO_DIR, SUBTITLES_DIR, TEMPLATES_DIR, STATIC_DIR]:
    folder.mkdir(parents=True, exist_ok=True)

app = FastAPI(
    title="Shorts Studio",
    description="Mini application web gratuite pour transformer vos propres vidéos en format vertical avec sous-titres.",
    version="1.0.0",
)

templates = Jinja2Templates(directory=str(TEMPLATES_DIR))
app.mount("/static", StaticFiles(directory=str(STATIC_DIR)), name="static")

jobs: dict[str, dict[str, Any]] = {}

ALLOWED_EXTENSIONS = {".mp4", ".mov", ".mkv", ".webm"}
MAX_FILE_SIZE_MB = 500

SUBTITLE_STYLES = {
    "classic": "FontName=Arial,FontSize=18,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H64000000,BorderStyle=3,Outline=1,Shadow=0,Alignment=2,MarginV=40",
    "yellow": "FontName=Arial,FontSize=20,PrimaryColour=&H0000FFFF,OutlineColour=&H00000000,BackColour=&H64000000,BorderStyle=3,Outline=1,Shadow=0,Alignment=2,MarginV=40",
    "bold": "FontName=Arial,FontSize=22,PrimaryColour=&H00FFFFFF,OutlineColour=&H00000000,BackColour=&H96000000,BorderStyle=3,Outline=2,Shadow=0,Alignment=2,MarginV=55",
}

LANGUAGE_MAP = {
    "fr": "French",
    "en": "English",
    "es": "Spanish",
    "pt": "Portuguese",
    "de": "German",
}


def now_iso() -> str:
    return datetime.utcnow().isoformat() + "Z"


@app.get("/", response_class=HTMLResponse)
def home(request: Request) -> HTMLResponse:
    return templates.TemplateResponse("index.html", {"request": request})


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok", "time": now_iso()}


@app.post("/api/process")
async def process_video(
    background_tasks: BackgroundTasks,
    video: UploadFile = File(...),
    language: str = Form("fr"),
    whisper_model: str = Form("base"),
    subtitle_style: str = Form("classic"),
    narration_text: str = Form(""),
    auto_highlight: bool = Form(False),
    highlight_duration: int = Form(30),
) -> JSONResponse:
    ext = Path(video.filename or "").suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(status_code=400, detail="Format non supporté. Utilisez mp4, mov, mkv ou webm.")

    content = await video.read()
    size_mb = len(content) / (1024 * 1024)
    if size_mb > MAX_FILE_SIZE_MB:
        raise HTTPException(status_code=400, detail=f"Fichier trop lourd ({size_mb:.1f} MB). Maximum {MAX_FILE_SIZE_MB} MB.")

    highlight_duration = max(10, min(highlight_duration, 90))

    job_id = uuid.uuid4().hex[:12]
    safe_name = f"source{ext}"
    input_path = UPLOADS_DIR / job_id
    input_path.mkdir(parents=True, exist_ok=True)
    source_file = input_path / safe_name
    source_file.write_bytes(content)

    jobs[job_id] = {
        "id": job_id,
        "status": "queued",
        "step": "Fichier reçu",
        "progress": 5,
        "created_at": now_iso(),
        "updated_at": now_iso(),
        "error": None,
        "output_url": None,
        "subtitle_url": None,
        "meta": {
            "filename": video.filename,
            "language": language,
            "whisper_model": whisper_model,
            "subtitle_style": subtitle_style,
            "narration": bool(narration_text.strip()),
            "auto_highlight": auto_highlight,
            "highlight_duration": highlight_duration,
        },
    }

    background_tasks.add_task(
        run_pipeline,
        job_id=job_id,
        input_file=source_file,
        language=language,
        whisper_model=whisper_model,
        subtitle_style=subtitle_style,
        narration_text=narration_text.strip(),
        auto_highlight=auto_highlight,
        highlight_duration=highlight_duration,
    )

    return JSONResponse({"job_id": job_id, "message": "Traitement lancé"}, status_code=202)


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict[str, Any]:
    job = jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Job introuvable")
    return job


@app.get("/api/jobs/{job_id}/download")
def download_output(job_id: str):
    job = jobs.get(job_id)
    if not job or not job.get("output_path"):
        raise HTTPException(status_code=404, detail="Fichier final introuvable")
    output_path = Path(job["output_path"])
    if not output_path.exists():
        raise HTTPException(status_code=404, detail="Fichier final introuvable")
    return FileResponse(output_path, media_type="video/mp4", filename=f"shorts-studio-{job_id}.mp4")


@app.get("/api/jobs/{job_id}/subtitle")
def download_subtitle(job_id: str):
    job = jobs.get(job_id)
    if not job or not job.get("subtitle_path"):
        raise HTTPException(status_code=404, detail="Sous-titres introuvables")
    subtitle_path = Path(job["subtitle_path"])
    if not subtitle_path.exists():
        raise HTTPException(status_code=404, detail="Sous-titres introuvables")
    return FileResponse(subtitle_path, media_type="text/plain", filename=f"shorts-studio-{job_id}.srt")


@app.get("/api/tools")
def tools_status() -> dict[str, bool]:
    return {
        "ffmpeg": tool_exists("ffmpeg"),
        "ffprobe": tool_exists("ffprobe"),
        "whisper": whisper_available(),
        "piper": piper_available(),
    }


def update_job(job_id: str, *, status: str | None = None, step: str | None = None, progress: int | None = None, error: str | None = None, **extra: Any) -> None:
    job = jobs[job_id]
    if status is not None:
        job["status"] = status
    if step is not None:
        job["step"] = step
    if progress is not None:
        job["progress"] = progress
    if error is not None:
        job["error"] = error
    if extra:
        job.update(extra)
    job["updated_at"] = now_iso()


def tool_exists(name: str) -> bool:
    return shutil.which(name) is not None


def whisper_available() -> bool:
    if tool_exists("whisper"):
        return True
    result = subprocess.run([shutil.which("python3") or "python3", "-m", "whisper", "--help"], capture_output=True, text=True)
    return result.returncode == 0


def piper_available() -> bool:
    model_path = os.getenv("PIPER_MODEL", "").strip()
    return tool_exists("piper") and bool(model_path) and Path(model_path).exists()


def run_command(command: list[str], job_id: str, step: str) -> None:
    update_job(job_id, step=step)
    result = subprocess.run(command, capture_output=True, text=True)
    if result.returncode != 0:
        stderr = (result.stderr or result.stdout or "Erreur inconnue").strip()
        raise RuntimeError(f"{step}: {stderr}")


def escape_subtitle_path(path: Path) -> str:
    return str(path).replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")


def parse_srt_timestamp(value: str) -> float:
    hours, minutes, rest = value.split(":")
    seconds, millis = rest.split(",")
    return int(hours) * 3600 + int(minutes) * 60 + int(seconds) + int(millis) / 1000


def format_srt_timestamp(seconds: float) -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours = total_ms // 3_600_000
    remainder = total_ms % 3_600_000
    minutes = remainder // 60_000
    remainder %= 60_000
    secs = remainder // 1000
    millis = remainder % 1000
    return f"{hours:02}:{minutes:02}:{secs:02},{millis:03}"


def parse_srt_entries(path: Path) -> list[dict[str, Any]]:
    content = path.read_text(encoding="utf-8", errors="ignore").strip()
    if not content:
        return []

    entries: list[dict[str, Any]] = []
    for block in content.split("\n\n"):
        lines = [line.strip("\ufeff") for line in block.splitlines() if line.strip()]
        if len(lines) < 2 or "-->" not in lines[1]:
            continue
        start_raw, end_raw = [part.strip() for part in lines[1].split("-->")]
        text = " ".join(lines[2:]).strip()
        start = parse_srt_timestamp(start_raw)
        end = parse_srt_timestamp(end_raw)
        if end <= start:
            continue
        word_count = len(text.split())
        bonus = text.count("!") * 2 + text.count("?") * 1.5
        entries.append({
            "start": start,
            "end": end,
            "text": text,
            "words": word_count,
            "score": word_count + bonus,
        })
    return entries


def media_duration(path: Path) -> float:
    result = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(f"Impossible de lire la durée média: {(result.stderr or result.stdout).strip()}")
    return float((result.stdout or "0").strip() or 0)


def choose_highlight_window(entries: list[dict[str, Any]], total_duration: float, target_duration: int) -> tuple[float, float, float]:
    duration = min(float(target_duration), max(total_duration, 1.0))
    if total_duration <= duration:
        score = sum(entry.get("score", 0) for entry in entries)
        return 0.0, total_duration, score

    candidate_starts = {0.0, max(0.0, total_duration - duration)}
    for entry in entries:
        candidate_starts.add(max(0.0, min(entry["start"], total_duration - duration)))
        candidate_starts.add(max(0.0, min(entry["end"] - duration, total_duration - duration)))

    best_start = 0.0
    best_score = -1.0
    for start in sorted(candidate_starts):
        end = min(total_duration, start + duration)
        score = 0.0
        for entry in entries:
            overlap = max(0.0, min(end, entry["end"]) - max(start, entry["start"]))
            if overlap <= 0:
                continue
            entry_duration = max(0.1, entry["end"] - entry["start"])
            score += entry["score"] * (overlap / entry_duration)
        if score > best_score:
            best_start = start
            best_score = score

    return best_start, min(total_duration, best_start + duration), best_score


def write_trimmed_srt(entries: list[dict[str, Any]], clip_start: float, clip_end: float, output_path: Path) -> int:
    blocks: list[str] = []
    index = 1
    for entry in entries:
        overlap_start = max(entry["start"], clip_start)
        overlap_end = min(entry["end"], clip_end)
        if overlap_end <= overlap_start:
            continue
        blocks.append(
            "\n".join(
                [
                    str(index),
                    f"{format_srt_timestamp(overlap_start - clip_start)} --> {format_srt_timestamp(overlap_end - clip_start)}",
                    entry["text"],
                ]
            )
        )
        index += 1

    output_path.write_text("\n\n".join(blocks), encoding="utf-8")
    return index - 1


def run_pipeline(
    job_id: str,
    input_file: Path,
    language: str,
    whisper_model: str,
    subtitle_style: str,
    narration_text: str,
    auto_highlight: bool,
    highlight_duration: int,
) -> None:
    output_dir = OUTPUTS_DIR / job_id
    audio_dir = AUDIO_DIR / job_id
    subtitle_dir = SUBTITLES_DIR / job_id
    output_dir.mkdir(parents=True, exist_ok=True)
    audio_dir.mkdir(parents=True, exist_ok=True)
    subtitle_dir.mkdir(parents=True, exist_ok=True)

    audio_file = audio_dir / "audio.mp3"
    narration_file = audio_dir / "narration.wav"
    mixed_audio_file = audio_dir / "mixed_audio.mp3"
    subtitle_file = subtitle_dir / "captions.srt"
    vertical_file = output_dir / "vertical.mp4"
    final_file = output_dir / "final.mp4"

    try:
        if not tool_exists("ffmpeg") or not tool_exists("ffprobe"):
            raise RuntimeError("FFmpeg et ffprobe doivent être installés sur la machine.")
        if not whisper_available():
            raise RuntimeError("Whisper n'est pas installé. Installez-le avec: pip install openai-whisper")

        update_job(job_id, status="processing", step="Analyse de la vidéo", progress=10)

        run_command([
            "ffmpeg", "-y", "-i", str(input_file), "-vn", "-acodec", "mp3", str(audio_file)
        ], job_id, "Extraction de l'audio")
        update_job(job_id, progress=25)

        whisper_language = LANGUAGE_MAP.get(language, language)
        whisper_cmd = ["whisper", str(audio_file), "--model", whisper_model, "--language", whisper_language, "--output_format", "srt", "--output_dir", str(subtitle_dir)]
        if not tool_exists("whisper"):
            whisper_cmd = [shutil.which("python3") or "python3", "-m", "whisper", str(audio_file), "--model", whisper_model, "--language", whisper_language, "--output_format", "srt", "--output_dir", str(subtitle_dir)]
        run_command(whisper_cmd, job_id, "Transcription et génération des sous-titres")

        generated_srt = subtitle_dir / f"{audio_file.stem}.srt"
        if generated_srt.exists() and generated_srt != subtitle_file:
            generated_srt.rename(subtitle_file)
        if not subtitle_file.exists():
            raise RuntimeError("Le fichier de sous-titres n'a pas été généré.")

        source_for_edit = input_file
        source_audio_for_edit = audio_file
        active_subtitle_file = subtitle_file
        highlight_meta: dict[str, Any] = {"enabled": False}

        if auto_highlight:
            entries = parse_srt_entries(subtitle_file)
            total_duration = media_duration(input_file)
            clip_start, clip_end, clip_score = choose_highlight_window(entries, total_duration, highlight_duration)
            clip_duration = max(0.1, clip_end - clip_start)
            highlighted_source = output_dir / "highlight_source.mp4"
            highlighted_audio = audio_dir / "highlight_audio.mp3"
            highlighted_subtitles = subtitle_dir / "captions_highlight.srt"

            update_job(job_id, progress=60, step="Sélection automatique du meilleur moment")
            run_command([
                "ffmpeg", "-y", "-ss", f"{clip_start:.3f}", "-i", str(input_file), "-t", f"{clip_duration:.3f}",
                "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac",
                str(highlighted_source),
            ], job_id, "Découpe du meilleur moment vidéo")
            run_command([
                "ffmpeg", "-y", "-ss", f"{clip_start:.3f}", "-i", str(audio_file), "-t", f"{clip_duration:.3f}",
                "-acodec", "mp3",
                str(highlighted_audio),
            ], job_id, "Découpe du meilleur moment audio")
            kept_subtitles = write_trimmed_srt(entries, clip_start, clip_end, highlighted_subtitles)
            if kept_subtitles <= 0:
                shutil.copyfile(subtitle_file, highlighted_subtitles)

            source_for_edit = highlighted_source
            source_audio_for_edit = highlighted_audio
            active_subtitle_file = highlighted_subtitles
            highlight_meta = {
                "enabled": True,
                "start": round(clip_start, 3),
                "end": round(clip_end, 3),
                "duration": round(clip_duration, 3),
                "score": round(clip_score, 2),
                "subtitle_blocks": kept_subtitles,
            }

        update_job(
            job_id,
            progress=65,
            subtitle_path=str(active_subtitle_file),
            subtitle_url=f"/api/jobs/{job_id}/subtitle",
            highlight=highlight_meta,
        )

        run_command([
            "ffmpeg", "-y", "-i", str(source_for_edit),
            "-vf", "scale=1080:1920:force_original_aspect_ratio=increase,crop=1080:1920",
            "-preset", "veryfast",
            str(vertical_file),
        ], job_id, "Conversion en format vertical 9:16")
        update_job(job_id, progress=78)

        video_input = vertical_file
        audio_input = source_audio_for_edit
        if narration_text:
            piper_model = os.getenv("PIPER_MODEL", "").strip()
            if not piper_available():
                raise RuntimeError("Le texte de narration a été fourni, mais Piper TTS n'est pas prêt. Installez Piper et définissez la variable PIPER_MODEL vers un modèle .onnx valide.")
            run_command([
                "bash", "-lc", f"printf '%s' {shell_quote(narration_text)} | piper --model {shell_quote(piper_model)} --output_file {shell_quote(str(narration_file))}"
            ], job_id, "Génération de la voix IA")
            run_command([
                "ffmpeg", "-y", "-i", str(source_audio_for_edit), "-i", str(narration_file),
                "-filter_complex", "[0:a][1:a]amix=inputs=2:duration=longest:weights=0.6 1.0",
                str(mixed_audio_file),
            ], job_id, "Mixage de la narration")
            audio_input = mixed_audio_file
            update_job(job_id, progress=86)

        subtitle_style_value = SUBTITLE_STYLES.get(subtitle_style, SUBTITLE_STYLES["classic"])
        subtitle_filter = f"subtitles='{escape_subtitle_path(active_subtitle_file)}':force_style='{subtitle_style_value}'"
        run_command([
            "ffmpeg", "-y", "-i", str(video_input), "-i", str(audio_input),
            "-vf", subtitle_filter,
            "-map", "0:v:0", "-map", "1:a:0",
            "-c:v", "libx264", "-preset", "veryfast", "-c:a", "aac", "-shortest",
            str(final_file),
        ], job_id, "Incrustation des sous-titres et export final")

        update_job(
            job_id,
            status="completed",
            step="Terminé",
            progress=100,
            output_path=str(final_file),
            output_url=f"/api/jobs/{job_id}/download",
        )
    except Exception as exc:
        update_job(job_id, status="failed", step="Échec", progress=100, error=str(exc))


def shell_quote(value: str) -> str:
    return "'" + value.replace("'", "'\\''") + "'"
