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
"""Backend audio waveform peak extraction (single source of truth).

Computes normalized ``[MIN_WAVEFORM_BAR, 1.0]`` amplitude bars from generated
audio bytes at write time and stores them under
``audio_analysis["tracks"][i]["waveform"]``. The frontend renders those bars
verbatim when present and falls back to a plain slider when absent.

Like ``lyria3_text.py``, this module stays free of application imports.
"""

from array import array
from collections.abc import Callable
import io
import logging
import math
import subprocess
import sys
import wave

logger = logging.getLogger(__name__)

DEFAULT_WAVEFORM_BARS = 120
MIN_WAVEFORM_BAR = 0.05
_FFMPEG_TIMEOUT_SECONDS = 15
_MAX_SAMPLES_PER_BUCKET = 512


def _compute_bars_from_frame_reader(
    total_frames: int,
    read_frame_mag: Callable[[int], float],
    num_bars: int,
) -> list[float]:
    """Computes blended RMS + peak bars normalized into ``[MIN_WAVEFORM_BAR, 1.0]``."""
    if total_frames <= 0:
        return [MIN_WAVEFORM_BAR] * num_bars

    raw_bars: list[float] = []
    global_max = 0.0

    for idx in range(num_bars):
        start = int(idx * total_frames / num_bars)
        end = (
            total_frames
            if idx == num_bars - 1
            else max(start + 1, int((idx + 1) * total_frames / num_bars))
        )
        start = min(start, total_frames - 1)
        end = max(start + 1, min(end, total_frames))

        span = end - start
        stride = max(1, span // _MAX_SAMPLES_PER_BUCKET)

        sum_sq = 0.0
        peak = 0.0
        count = 0
        for pos in range(start, end, stride):
            mag = read_frame_mag(pos)
            if mag > peak:
                peak = mag
            sum_sq += mag * mag
            count += 1

        rms = math.sqrt(sum_sq / count) if count > 0 else 0.0
        blended = 0.45 * rms + 0.55 * peak
        raw_bars.append(blended)
        if blended > global_max:
            global_max = blended

    if global_max <= 0.0:
        return [MIN_WAVEFORM_BAR] * num_bars

    min_val = min(raw_bars)
    span = global_max - min_val
    floor = min_val * 0.78 if span > 0.05 * global_max else 0.0
    denom = max(global_max - floor, 1e-9)

    bars: list[float] = []
    for val in raw_bars:
        normalized = max(0.0, (val - floor) / denom) ** 1.15
        clamped = min(1.0, max(MIN_WAVEFORM_BAR, normalized))
        bars.append(round(clamped, 3))
    return bars


_PCM_ARRAY_FORMATS: dict[int, tuple[str, int, float]] = {
    1: ("B", 128, 128.0),  # 8-bit unsigned [0..255] centered at 128
    2: ("h", 0, 32768.0),
    4: ("i", 0, 2147483648.0),
}


def _bars_from_pcm_samples(
    raw_frames: bytes,
    sample_width: int,
    n_channels: int,
    frame_rate: int,
    num_bars: int,
) -> tuple[list[float] | None, float | None] | None:
    """Decodes 8/16/24/32-bit little-endian PCM bytes into ``(bars, duration_sec)``."""
    read_frame_mag: Callable[[int], float]
    if sample_width in _PCM_ARRAY_FORMATS:
        typecode, offset, scale = _PCM_ARRAY_FORMATS[sample_width]
        samples = array(typecode)
        samples.frombytes(
            raw_frames[: len(raw_frames) - (len(raw_frames) % sample_width)]
        )
        if sample_width > 1 and sys.byteorder != "little":
            samples.byteswap()
        total_frames = len(samples) // n_channels
        read_frame_mag = (
            (lambda f: min(1.0, abs(samples[f] - offset) / scale))
            if n_channels == 1
            else (
                lambda f: sum(
                    min(
                        1.0,
                        abs(samples[f * n_channels + ch] - offset) / scale,
                    )
                    for ch in range(n_channels)
                )
                / n_channels
            )
        )
    elif sample_width == 3:
        frame_bytes = 3 * n_channels
        total_frames = len(raw_frames) // frame_bytes

        def _read_24bit_frame(frame_idx: int) -> float:
            base = frame_idx * frame_bytes
            return (
                sum(
                    min(
                        1.0,
                        abs(
                            int.from_bytes(
                                raw_frames[base + ch * 3 : base + (ch + 1) * 3],
                                byteorder="little",
                                signed=True,
                            )
                        )
                        / 8388608.0,
                    )
                    for ch in range(n_channels)
                )
                / n_channels
            )

        read_frame_mag = _read_24bit_frame
    else:
        return None

    if total_frames <= 0:
        return (None, None)
    duration_sec = (
        round(total_frames / frame_rate, 1)
        if frame_rate and frame_rate > 0
        else None
    )
    bars = _compute_bars_from_frame_reader(
        total_frames, read_frame_mag, num_bars
    )
    return (bars, duration_sec)


def _decode_wav_bars_and_duration(
    audio_bytes: bytes,
    num_bars: int,
) -> tuple[list[float] | None, float | None] | None:
    """Computes waveform bars and duration directly from uncompressed PCM WAV bytes.

    Returns ``None`` when ``audio_bytes`` is not a decodable PCM WAV (so callers
    can fall back to ``ffmpeg``), or ``(None, None)`` for valid empty/0-frame WAVs.
    """
    if len(audio_bytes) < 44 or audio_bytes[:4] != b"RIFF":
        return None
    try:
        with wave.open(io.BytesIO(audio_bytes), "rb") as wav_file:
            n_channels = wav_file.getnchannels()
            sample_width = wav_file.getsampwidth()
            n_frames = wav_file.getnframes()
            frame_rate = wav_file.getframerate()
            if n_channels <= 0 or n_frames <= 0:
                return (None, None)
            raw_frames = wav_file.readframes(n_frames)
    except wave.Error:
        return None

    if not raw_frames:
        return (None, None)
    return _bars_from_pcm_samples(
        raw_frames, sample_width, n_channels, frame_rate, num_bars
    )


def _decode_ffmpeg_bars_and_duration(
    audio_bytes: bytes,
    num_bars: int,
) -> tuple[list[float] | None, float | None]:
    """Decodes compressed audio (MP3, etc.) to 8 kHz mono s16le via ffmpeg."""
    result = subprocess.run(
        [
            "ffmpeg",
            "-nostdin",
            "-v",
            "error",
            "-i",
            "pipe:0",
            "-f",
            "s16le",
            "-ac",
            "1",
            "-ar",
            "8000",
            "pipe:1",
        ],
        input=audio_bytes,
        capture_output=True,
        timeout=_FFMPEG_TIMEOUT_SECONDS,
        check=False,
    )
    if result.returncode != 0 or not result.stdout:
        stderr_msg = result.stderr.decode("utf-8", errors="replace").strip()
        logger.warning(
            "ffmpeg waveform decode failed (code=%s): %s",
            result.returncode,
            stderr_msg,
        )
        return (None, None)

    return _bars_from_pcm_samples(result.stdout, 2, 1, 8000, num_bars) or (
        None,
        None,
    )


def extract_audio_waveform_and_duration(
    audio_bytes: bytes | None,
    mime_type: str | None = None,
    num_bars: int = DEFAULT_WAVEFORM_BARS,
) -> tuple[list[float] | None, float | None]:
    """Extracts ``(waveform_bars, duration_seconds)`` from raw audio bytes.

    Uses Python's stdlib ``wave`` parser for uncompressed WAV outputs and falls
    back to an in-memory ``ffmpeg`` pipe for compressed formats (such as Lyria 3
    ``audio/mpeg``). Never raises: returns ``(None, None)`` if decoding fails.
    """
    if not audio_bytes or num_bars <= 0:
        return (None, None)

    try:
        normalized_mime = (mime_type or "").lower()
        if normalized_mime in (
            "",
            "audio/wav",
            "audio/x-wav",
            "audio/wave",
        ) or (audio_bytes[:4] == b"RIFF"):
            wav_result = _decode_wav_bars_and_duration(audio_bytes, num_bars)
            if wav_result is not None:
                return wav_result

        return _decode_ffmpeg_bars_and_duration(audio_bytes, num_bars)
    except Exception:  # pylint: disable=broad-exception-caught
        logger.warning(
            "Unexpected error extracting audio waveform; skipping.",
            exc_info=True,
        )
        return (None, None)
