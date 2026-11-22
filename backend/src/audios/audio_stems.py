# Copyright 2026 Google LLC
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""In-process CPU audio stem separation and mixing via ONNX Runtime.

Uses the 6-stem HT-Demucs ONNX graph (``drums``, ``bass``, ``other``,
``vocals``, ``guitar``, ``piano``) with pure ``numpy`` + ``onnxruntime`` +
``ffmpeg`` (no PyTorch dependency). Like ``lyria3_text.py`` and
``audio_waveform.py``, this module stays free of application imports.
"""

from collections.abc import Callable, Sequence
from contextlib import contextmanager
from dataclasses import dataclass
import fcntl
import hashlib
import io
import logging
import os
from pathlib import Path
import subprocess
import tempfile
import threading
from typing import Any
import urllib.request
import wave

import numpy as np
import onnxruntime as ort

logger = logging.getLogger(__name__)

# Exact output axis-1 order of StemSplitio/htdemucs-6s-onnx.
HTDEMUCS_6S_SOURCES: tuple[str, ...] = (
    "drums",
    "bass",
    "other",
    "vocals",
    "guitar",
    "piano",
)

# Friendly display order presented in the Creative Studio stem mixer UI.
UI_STEM_ORDER: tuple[str, ...] = (
    "vocals",
    "drums",
    "bass",
    "guitar",
    "piano",
    "other",
)

STEM_LABELS: dict[str, str] = {
    "vocals": "Vocals",
    "drums": "Drums",
    "bass": "Bass",
    "guitar": "Guitar",
    "piano": "Piano",
    "other": "Other",
}

SAMPLE_RATE = 44100
SEGMENT_SECONDS = 7.8
N_SAMPLES = int(SEGMENT_SECONDS * SAMPLE_RATE)  # 343_980 samples
N_CHANNELS = 2
MAX_STEM_DURATION_SECONDS = 300.0

DEFAULT_MODEL_FILENAME = "htdemucs_6s_fp16weights.onnx"
GCS_MODEL_BLOB_PATH = f"_models/{DEFAULT_MODEL_FILENAME}"
STEM_CACHE_SCHEMA_VERSION = "htdemucs_6s_v1"

_MIN_VALID_MODEL_BYTES = 1_000_000
_FFMPEG_DECODE_TIMEOUT_SECONDS = 60
_FFMPEG_ENCODE_TIMEOUT_SECONDS = 60
_MODEL_DOWNLOAD_TIMEOUT_SECONDS = 300
_DOWNLOAD_CHUNK_BYTES = 1024 * 1024

_SESSION_LOCK = threading.Lock()
_SESSION_CACHE: dict[tuple[str, int], Any] = {}


def compute_stem_cache_key(gcs_uri: str) -> str:
    """Computes a deterministic cache key for a source audio GCS URI."""
    normalized = (gcs_uri or "").strip()
    if not normalized:
        raise ValueError("gcs_uri cannot be empty.")
    digest = hashlib.sha256(
        f"{STEM_CACHE_SCHEMA_VERSION}:{normalized}".encode("utf-8")
    ).hexdigest()
    return digest[:24]


@contextmanager
def _exclusive_file_lock(lock_path: Path):
    """Acquires an exclusive cross-process POSIX file lock."""
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    with open(lock_path, "a+b") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def decode_audio_to_stereo_f32(
    audio_bytes: bytes,
    sample_rate: int = SAMPLE_RATE,
    max_duration_seconds: float = MAX_STEM_DURATION_SECONDS,
) -> np.ndarray:
    """Decodes arbitrary audio bytes into stereo float32 PCM ``(2, samples)``."""
    if not audio_bytes:
        raise ValueError("Audio payload is empty.")

    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-i",
                "pipe:0",
                "-f",
                "f32le",
                "-ac",
                str(N_CHANNELS),
                "-ar",
                str(sample_rate),
                "pipe:1",
            ],
            input=audio_bytes,
            capture_output=True,
            timeout=_FFMPEG_DECODE_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise ValueError(
            "Failed to decode audio for stem separation: ffmpeg binary is not installed."
        ) from exc
    if result.returncode != 0 or not result.stdout:
        stderr_msg = result.stderr.decode("utf-8", errors="replace").strip()
        raise ValueError(
            f"Failed to decode audio for stem separation: {stderr_msg or 'empty output'}"
        )

    bytes_per_frame = 4 * N_CHANNELS
    usable_len = len(result.stdout) - (len(result.stdout) % bytes_per_frame)
    if usable_len <= 0:
        raise ValueError("Decoded audio contains zero frames.")

    interleaved = np.frombuffer(result.stdout[:usable_len], dtype="<f4")
    stereo = interleaved.reshape(-1, N_CHANNELS).T.astype(np.float32, copy=True)
    total_samples = stereo.shape[1]
    duration_sec = total_samples / float(sample_rate)
    if duration_sec > max_duration_seconds:
        raise ValueError(
            f"Audio is {duration_sec:.1f}s long; stem separation supports tracks "
            f"up to {int(max_duration_seconds)}s."
        )
    return stereo


def encode_stereo_f32_to_mp3(
    samples: np.ndarray,
    sample_rate: int = SAMPLE_RATE,
    bitrate: str = "192k",
) -> bytes:
    """Encodes stereo float32 PCM ``(2, samples)`` into MP3 bytes via ffmpeg."""
    if samples.ndim != 2 or samples.shape[0] != N_CHANNELS:
        raise ValueError(
            f"Expected stereo array of shape (2, N), got {samples.shape}."
        )
    if samples.shape[1] <= 0:
        raise ValueError("Cannot encode empty audio array.")

    clamped = np.clip(samples, -1.0, 1.0)
    raw_bytes = np.ascontiguousarray(clamped.T, dtype="<f4").tobytes()
    try:
        result = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-f",
                "f32le",
                "-ac",
                str(N_CHANNELS),
                "-ar",
                str(sample_rate),
                "-i",
                "pipe:0",
                "-vn",
                "-codec:a",
                "libmp3lame",
                "-b:a",
                bitrate,
                "-f",
                "mp3",
                "pipe:1",
            ],
            input=raw_bytes,
            capture_output=True,
            timeout=_FFMPEG_ENCODE_TIMEOUT_SECONDS,
            check=False,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Failed to encode stem MP3 audio: ffmpeg binary is not installed."
        ) from exc
    if result.returncode != 0 or not result.stdout:
        stderr_msg = result.stderr.decode("utf-8", errors="replace").strip()
        raise RuntimeError(
            f"Failed to encode stem MP3 audio: {stderr_msg or 'empty output'}"
        )
    return result.stdout


def encode_stereo_f32_to_wav(
    samples: np.ndarray,
    sample_rate: int = SAMPLE_RATE,
) -> bytes:
    """Encodes stereo float32 PCM ``(2, samples)`` into 16-bit PCM WAV bytes."""
    if samples.ndim != 2 or samples.shape[0] != N_CHANNELS:
        raise ValueError(
            f"Expected stereo array of shape (2, N), got {samples.shape}."
        )
    if samples.shape[1] <= 0:
        raise ValueError("Cannot encode empty audio array.")

    pcm16 = np.clip(np.round(samples.T * 32767.0), -32768, 32767).astype("<i2")
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(N_CHANNELS)
        wav_file.setsampwidth(2)
        wav_file.setframerate(sample_rate)
        wav_file.writeframes(pcm16.tobytes())
    return buf.getvalue()


def compute_stem_energy(samples: np.ndarray) -> tuple[float, bool]:
    """Returns ``(peak_level, has_energy)`` for a separated stem ``(2, N)``."""
    if samples.size == 0:
        return (0.0, False)
    peak = float(np.max(np.abs(samples)))
    rms = float(np.sqrt(np.mean(np.square(samples, dtype=np.float64))))
    has_energy = bool(rms >= 0.0025 or peak >= 0.015)
    return (round(min(1.0, peak), 4), has_energy)


def mix_stem_arrays(stem_arrays: Sequence[np.ndarray]) -> np.ndarray:
    """Sums one or more stereo stem arrays ``(2, N)`` with transparent peak limiting."""
    if not stem_arrays:
        raise ValueError("At least one stem array is required to mix.")

    max_len = 0
    for arr in stem_arrays:
        if arr.ndim != 2 or arr.shape[0] != N_CHANNELS or arr.shape[1] <= 0:
            raise ValueError(
                f"Expected non-empty stereo array (2, N), got {arr.shape}."
            )
        if arr.shape[1] > max_len:
            max_len = arr.shape[1]

    mixed = np.zeros((N_CHANNELS, max_len), dtype=np.float32)
    for arr in stem_arrays:
        mixed[:, : arr.shape[1]] += arr.astype(np.float32, copy=False)

    peak = float(np.max(np.abs(mixed)))
    if peak > 0.99:
        mixed *= np.float32(0.99 / peak)
    return mixed


def ensure_model_file(
    cache_dir: str | Path,
    model_url: str,
    *,
    gcs_download_fn: Callable[[Path], bool] | None = None,
    gcs_upload_fn: Callable[[Path], None] | None = None,
) -> Path:
    """Ensures the HT-Demucs 6-stem ONNX file is cached locally on disk.

    Checks ``AUDIO_STEM_MODEL_PATH`` first, then ``<cache_dir>/htdemucs_6s_fp16weights.onnx``
    under a cross-process file lock, then GCS (if ``gcs_download_fn`` is provided),
    and finally downloads over HTTPS from ``model_url`` (mirroring into GCS best-effort).
    """
    override_path = (os.getenv("AUDIO_STEM_MODEL_PATH") or "").strip()
    if override_path:
        explicit = Path(override_path)
        if (
            explicit.is_file()
            and explicit.stat().st_size >= _MIN_VALID_MODEL_BYTES
        ):
            return explicit
        raise FileNotFoundError(
            f"AUDIO_STEM_MODEL_PATH does not point to a valid ONNX model: {override_path}"
        )

    cache_root = Path(cache_dir)
    cache_root.mkdir(parents=True, exist_ok=True)
    target_path = cache_root / DEFAULT_MODEL_FILENAME
    if (
        target_path.is_file()
        and target_path.stat().st_size >= _MIN_VALID_MODEL_BYTES
    ):
        return target_path

    lock_path = cache_root / f"{DEFAULT_MODEL_FILENAME}.lock"
    with _exclusive_file_lock(lock_path):
        if (
            target_path.is_file()
            and target_path.stat().st_size >= _MIN_VALID_MODEL_BYTES
        ):
            return target_path

        temp_path = cache_root / f"{DEFAULT_MODEL_FILENAME}.part.{os.getpid()}"
        try:
            if gcs_download_fn is not None:
                try:
                    if (
                        gcs_download_fn(temp_path)
                        and temp_path.is_file()
                        and temp_path.stat().st_size >= _MIN_VALID_MODEL_BYTES
                    ):
                        os.replace(temp_path, target_path)
                        logger.info(
                            "Loaded ONNX stem model from GCS cache into %s",
                            target_path,
                        )
                        return target_path
                except Exception as gcs_err:
                    logger.warning(
                        "GCS cache lookup for ONNX stem model failed, falling back to HTTPS: %s",
                        gcs_err,
                    )

            clean_url = (model_url or "").strip()
            if not clean_url.startswith("https://"):
                raise ValueError(
                    "AUDIO_STEM_MODEL_URL must be a valid https:// URL."
                )

            logger.info("Downloading ONNX stem model from %s ...", clean_url)
            req = urllib.request.Request(
                clean_url,
                headers={"User-Agent": "google-cloud-creative-studio/1.0"},
            )
            with (
                urllib.request.urlopen(
                    req, timeout=_MODEL_DOWNLOAD_TIMEOUT_SECONDS
                ) as response,
                open(temp_path, "wb") as out_file,
            ):
                while True:
                    chunk = response.read(_DOWNLOAD_CHUNK_BYTES)
                    if not chunk:
                        break
                    out_file.write(chunk)

            if (
                not temp_path.is_file()
                or temp_path.stat().st_size < _MIN_VALID_MODEL_BYTES
            ):
                raise RuntimeError(
                    "Downloaded ONNX stem model file is incomplete or invalid."
                )

            os.replace(temp_path, target_path)
            logger.info(
                "Cached ONNX stem model at %s (%d bytes).",
                target_path,
                target_path.stat().st_size,
            )

            if gcs_upload_fn is not None:
                try:
                    gcs_upload_fn(target_path)
                except Exception as upload_err:
                    logger.warning(
                        "Best-effort upload of ONNX stem model to GCS skipped: %s",
                        upload_err,
                    )
            return target_path
        finally:
            if temp_path.exists():
                try:
                    temp_path.unlink()
                except OSError:
                    pass


def get_ort_session(model_path: Path, intra_op_threads: int = 2) -> Any:
    """Returns a cached CPU ``onnxruntime.InferenceSession`` with bounded memory."""
    threads = max(1, int(intra_op_threads))
    key = (str(model_path), threads)
    with _SESSION_LOCK:
        cached = _SESSION_CACHE.get(key)
        if cached is not None:
            return cached

        sess_opts = ort.SessionOptions()
        sess_opts.graph_optimization_level = (
            ort.GraphOptimizationLevel.ORT_ENABLE_ALL
        )
        sess_opts.intra_op_num_threads = threads
        sess_opts.inter_op_num_threads = 1
        # Release intermediate activation buffers back to the OS after each chunk
        # so multi-worker Gunicorn containers stay comfortably within Cloud Run RAM.
        sess_opts.enable_cpu_mem_arena = False

        session = ort.InferenceSession(
            str(model_path),
            sess_options=sess_opts,
            providers=["CPUExecutionProvider"],
        )
        _SESSION_CACHE[key] = session
        return session


def separate_stereo_44k(
    mix: np.ndarray,
    session: Any,
) -> dict[str, np.ndarray]:
    """Runs chunked overlap-add 6-stem separation on ``mix`` ``(2, samples)``."""
    if mix.ndim != 2 or mix.shape[0] not in (1, N_CHANNELS):
        raise ValueError(
            f"Expected audio shape (1|2, samples), got {mix.shape}."
        )
    if mix.shape[1] <= 0:
        raise ValueError("Cannot separate empty audio array.")
    if mix.shape[0] == 1:
        mix = np.repeat(mix, N_CHANNELS, axis=0)

    total = mix.shape[1]
    overlap = N_SAMPLES // 4
    stride = N_SAMPLES - overlap
    n_chunks = (
        1
        if total <= N_SAMPLES
        else 1 + (total - N_SAMPLES + stride - 1) // stride
    )
    fade_in = (
        np.linspace(0.0, 1.0, overlap, dtype=np.float32)
        if overlap > 0
        else np.empty(0, dtype=np.float32)
    )
    fade_out = 1.0 - fade_in

    out = np.zeros(
        (len(HTDEMUCS_6S_SOURCES), N_CHANNELS, total), dtype=np.float32
    )
    weight = np.zeros(total, dtype=np.float32)

    for idx in range(n_chunks):
        start = idx * stride
        end = min(start + N_SAMPLES, total)
        chunk = mix[:, start:end]
        if chunk.shape[1] < N_SAMPLES:
            chunk = np.pad(
                chunk,
                ((0, 0), (0, N_SAMPLES - chunk.shape[1])),
                mode="constant",
            )
        tensor_in = chunk[np.newaxis, ...].astype(np.float32, copy=False)
        raw_stems = session.run(["stems"], {"mix": tensor_in})[0][0]
        chunk_len = end - start
        win_slice = np.ones(chunk_len, dtype=np.float32)
        if overlap > 0:
            if idx > 0:
                fade_len = min(overlap, chunk_len)
                win_slice[:fade_len] *= fade_in[:fade_len]
            if idx < n_chunks - 1 and chunk_len >= overlap:
                win_slice[-overlap:] *= fade_out
        out[:, :, start:end] += raw_stems[:, :, :chunk_len] * win_slice
        weight[start:end] += win_slice

    out /= np.maximum(weight, 1e-8)
    return {stem: out[i] for i, stem in enumerate(HTDEMUCS_6S_SOURCES)}


def separate_audio_bytes(
    audio_bytes: bytes,
    *,
    cache_dir: str | Path,
    model_url: str,
    intra_op_threads: int = 2,
    gcs_download_fn: Callable[[Path], bool] | None = None,
    gcs_upload_fn: Callable[[Path], None] | None = None,
) -> dict[str, np.ndarray]:
    """Decodes ``audio_bytes`` and runs cross-process serialized CPU ONNX separation."""
    stereo = decode_audio_to_stereo_f32(audio_bytes)
    model_path = ensure_model_file(
        cache_dir=cache_dir,
        model_url=model_url,
        gcs_download_fn=gcs_download_fn,
        gcs_upload_fn=gcs_upload_fn,
    )
    infer_lock_path = Path(cache_dir) / "htdemucs_6s.infer.lock"
    with _exclusive_file_lock(infer_lock_path):
        session = get_ort_session(
            model_path=model_path,
            intra_op_threads=intra_op_threads,
        )
        return separate_stereo_44k(stereo, session)


@dataclass(frozen=True)
class EncodedStemResult:
    """MP3 bytes and amplitude summary produced by streaming stem separation."""

    mp3_bytes: bytes
    peak_level: float
    has_energy: bool
    duration_seconds: float


def _spawn_mp3_encoder_process(
    output_path: Path,
    sample_rate: int,
    bitrate: str,
) -> subprocess.Popen[bytes]:
    """Starts an ffmpeg process consuming f32le stereo stdin into ``output_path``."""
    try:
        return subprocess.Popen(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-y",
                "-f",
                "f32le",
                "-ac",
                str(N_CHANNELS),
                "-ar",
                str(sample_rate),
                "-i",
                "pipe:0",
                "-vn",
                "-codec:a",
                "libmp3lame",
                "-b:a",
                bitrate,
                "-f",
                "mp3",
                str(output_path),
            ],
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
        )
    except FileNotFoundError as exc:
        raise RuntimeError(
            "Failed to start MP3 stem encoder: ffmpeg binary is not installed."
        ) from exc


def separate_and_encode_stems_mp3(
    audio_bytes: bytes,
    *,
    cache_dir: str | Path,
    model_url: str,
    intra_op_threads: int = 2,
    bitrate: str = "192k",
    gcs_download_fn: Callable[[Path], bool] | None = None,
    gcs_upload_fn: Callable[[Path], None] | None = None,
) -> dict[str, EncodedStemResult]:
    """Separates ``audio_bytes`` and streams overlap-add frames directly to MP3.

    Avoids allocating the full ``(6, 2, total_samples)`` float32 array in RAM
    (~635 MB for a 5-minute track), keeping only a single ``overlap`` carry
    window (~4 MB) in memory across chunks.
    """
    stereo = decode_audio_to_stereo_f32(audio_bytes)
    total = stereo.shape[1]
    duration_sec = round(total / float(SAMPLE_RATE), 3)

    model_path = ensure_model_file(
        cache_dir=cache_dir,
        model_url=model_url,
        gcs_download_fn=gcs_download_fn,
        gcs_upload_fn=gcs_upload_fn,
    )

    n_sources = len(HTDEMUCS_6S_SOURCES)
    overlap = N_SAMPLES // 4
    stride = N_SAMPLES - overlap
    n_chunks = (
        1
        if total <= N_SAMPLES
        else 1 + (total - N_SAMPLES + stride - 1) // stride
    )
    fade_in = (
        np.linspace(0.0, 1.0, overlap, dtype=np.float32)
        if overlap > 0
        else np.empty(0, dtype=np.float32)
    )
    fade_out = 1.0 - fade_in

    peaks = [0.0] * n_sources
    sum_squares = [0.0] * n_sources

    with tempfile.TemporaryDirectory(prefix="cs_stems_") as tmp_dir_str:
        tmp_dir = Path(tmp_dir_str)
        procs: dict[str, subprocess.Popen[bytes]] = {}
        try:
            for stem_name in HTDEMUCS_6S_SOURCES:
                procs[stem_name] = _spawn_mp3_encoder_process(
                    tmp_dir / f"{stem_name}.mp3",
                    sample_rate=SAMPLE_RATE,
                    bitrate=bitrate,
                )

            infer_lock_path = Path(cache_dir) / "htdemucs_6s.infer.lock"
            with _exclusive_file_lock(infer_lock_path):
                session = get_ort_session(
                    model_path=model_path,
                    intra_op_threads=intra_op_threads,
                )
                carry_stems: np.ndarray | None = None
                carry_weight: np.ndarray | None = None

                for idx in range(n_chunks):
                    start = idx * stride
                    end = min(start + N_SAMPLES, total)
                    chunk_len = end - start
                    chunk = stereo[:, start:end]
                    if chunk_len < N_SAMPLES:
                        chunk = np.pad(
                            chunk,
                            ((0, 0), (0, N_SAMPLES - chunk_len)),
                            mode="constant",
                        )
                    tensor_in = chunk[np.newaxis, ...].astype(
                        np.float32, copy=False
                    )
                    raw_stems = session.run(["stems"], {"mix": tensor_in})[0][0]

                    win_slice = np.ones(chunk_len, dtype=np.float32)
                    if overlap > 0:
                        if idx > 0:
                            fade_len = min(overlap, chunk_len)
                            win_slice[:fade_len] *= fade_in[:fade_len]
                        if idx < n_chunks - 1 and chunk_len >= overlap:
                            win_slice[-overlap:] *= fade_out

                    weighted = (raw_stems[:, :, :chunk_len] * win_slice).astype(
                        np.float32, copy=False
                    )
                    chunk_weight = win_slice.copy()

                    if carry_stems is not None and carry_weight is not None:
                        ov_len = carry_stems.shape[2]
                        weighted[:, :, :ov_len] += carry_stems
                        chunk_weight[:ov_len] += carry_weight

                    if idx < n_chunks - 1 and overlap > 0:
                        ready_end = chunk_len - overlap
                        carry_stems = weighted[:, :, ready_end:].copy()
                        carry_weight = chunk_weight[ready_end:].copy()
                    else:
                        ready_end = chunk_len
                        carry_stems = None
                        carry_weight = None

                    ready = weighted[:, :, :ready_end] / np.maximum(
                        chunk_weight[:ready_end], 1e-8
                    )
                    for src_idx, stem_name in enumerate(HTDEMUCS_6S_SOURCES):
                        stem_slice = ready[src_idx]
                        chunk_peak = float(np.max(np.abs(stem_slice)))
                        if chunk_peak > peaks[src_idx]:
                            peaks[src_idx] = chunk_peak
                        sum_squares[src_idx] += float(
                            np.sum(np.square(stem_slice, dtype=np.float64))
                        )
                        clamped = np.clip(stem_slice, -1.0, 1.0)
                        pcm_bytes = np.ascontiguousarray(
                            clamped.T, dtype="<f4"
                        ).tobytes()
                        stdin_pipe = procs[stem_name].stdin
                        if stdin_pipe is None:
                            raise RuntimeError(
                                f"ffmpeg stdin closed unexpectedly for '{stem_name}'."
                            )
                        stdin_pipe.write(pcm_bytes)

            results: dict[str, EncodedStemResult] = {}
            total_values = float(max(1, N_CHANNELS * total))
            for src_idx, stem_name in enumerate(HTDEMUCS_6S_SOURCES):
                proc = procs[stem_name]
                if proc.stdin is not None:
                    proc.stdin.close()
                    proc.stdin = None
                _, stderr_bytes = proc.communicate(
                    timeout=_FFMPEG_ENCODE_TIMEOUT_SECONDS
                )
                out_file = tmp_dir / f"{stem_name}.mp3"
                if proc.returncode != 0 or not out_file.is_file():
                    stderr_msg = stderr_bytes.decode(
                        "utf-8", errors="replace"
                    ).strip()
                    raise RuntimeError(
                        f"Failed to encode '{stem_name}' MP3 stem: "
                        f"{stderr_msg or 'empty output'}"
                    )
                mp3_bytes = out_file.read_bytes()
                if not mp3_bytes:
                    raise RuntimeError(
                        f"Encoded '{stem_name}' MP3 stem is empty."
                    )
                peak_val = peaks[src_idx]
                rms = float(np.sqrt(sum_squares[src_idx] / total_values))
                has_energy = bool(rms >= 0.0025 or peak_val >= 0.015)
                results[stem_name] = EncodedStemResult(
                    mp3_bytes=mp3_bytes,
                    peak_level=round(min(1.0, peak_val), 4),
                    has_energy=has_energy,
                    duration_seconds=duration_sec,
                )
            return results
        finally:
            for proc in procs.values():
                if proc.stdin is not None:
                    try:
                        proc.stdin.close()
                    except OSError:
                        pass
                if proc.poll() is None:
                    proc.kill()
                    proc.wait(timeout=5)
