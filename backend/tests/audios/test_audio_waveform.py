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
"""Tests for backend audio waveform peak extraction."""

from array import array
import io
import math
import shutil
import subprocess
import wave

import pytest

from src.audios.audio_waveform import (
    DEFAULT_WAVEFORM_BARS,
    MIN_WAVEFORM_BAR,
    extract_audio_waveform_and_duration,
)


def _build_wav_bytes(
    frames_i16: list[int],
    n_channels: int = 1,
    framerate: int = 8000,
) -> bytes:
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wav_file:
        wav_file.setnchannels(n_channels)
        wav_file.setsampwidth(2)
        wav_file.setframerate(framerate)
        pcm = array("h", frames_i16)
        wav_file.writeframes(pcm.tobytes())
    return buf.getvalue()


class TestExtractAudioWaveformAndDuration:
    """Unit tests for ``extract_audio_waveform_and_duration``."""

    def test_returns_none_for_empty_or_invalid_inputs(self):
        assert extract_audio_waveform_and_duration(None) == (None, None)
        assert extract_audio_waveform_and_duration(b"") == (None, None)
        assert extract_audio_waveform_and_duration(b"RIFF", num_bars=0) == (
            None,
            None,
        )
        assert extract_audio_waveform_and_duration(
            _build_wav_bytes([]), "audio/wav"
        ) == (None, None)
        assert extract_audio_waveform_and_duration(
            b"not-valid-audio-bytes", "audio/mpeg"
        ) == (None, None)

    def test_extracts_dynamic_envelope_from_16bit_mono_wav(self):
        # First half quiet (~10% full scale), second half loud (~90% full scale)
        samples: list[int] = []
        for i in range(4000):
            amp = 3000 if i < 2000 else 29000
            samples.append(int(amp * math.sin(2 * math.pi * 440 * i / 8000)))

        wav_bytes = _build_wav_bytes(samples, n_channels=1)
        bars, duration_sec = extract_audio_waveform_and_duration(
            wav_bytes, "audio/wav", num_bars=8
        )

        assert bars is not None
        assert duration_sec == 0.5
        assert len(bars) == 8
        assert all(MIN_WAVEFORM_BAR <= b <= 1.0 for b in bars)
        # Quiet intro bars must be strictly lower than loud second-half bars
        assert max(bars[:4]) < min(bars[4:])
        assert max(bars[4:]) == 1.0

    def test_extracts_stereo_and_8bit_and_24bit_and_32bit_wavs(self):
        # Stereo 16-bit WAV
        stereo_samples = [12000, -12000] * 1000 + [28000, -28000] * 1000
        stereo_wav = _build_wav_bytes(stereo_samples, n_channels=2)
        stereo_bars, stereo_dur = extract_audio_waveform_and_duration(
            stereo_wav, "audio/wav", num_bars=4
        )
        assert stereo_bars is not None
        assert stereo_dur == 0.2
        assert len(stereo_bars) == 4
        assert stereo_bars[0] < stereo_bars[2]

        # 8-bit unsigned WAV
        buf_8 = io.BytesIO()
        with wave.open(buf_8, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(1)
            wf.setframerate(8000)
            wf.writeframes(bytes([140] * 400 + [250] * 400))
        bars_8, _ = extract_audio_waveform_and_duration(
            buf_8.getvalue(), "audio/wav", num_bars=4
        )
        assert bars_8 is not None
        assert bars_8[0] < bars_8[2]

        # 24-bit signed WAV
        buf_24 = io.BytesIO()
        with wave.open(buf_24, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(3)
            wf.setframerate(8000)
            low = (500_000).to_bytes(3, "little", signed=True) * 400
            high = (7_000_000).to_bytes(3, "little", signed=True) * 400
            wf.writeframes(low + high)
        bars_24, _ = extract_audio_waveform_and_duration(
            buf_24.getvalue(), "audio/wav", num_bars=4
        )
        assert bars_24 is not None
        assert bars_24[0] < bars_24[2]

        # 32-bit signed WAV
        buf_32 = io.BytesIO()
        with wave.open(buf_32, "wb") as wf:
            wf.setnchannels(1)
            wf.setsampwidth(4)
            wf.setframerate(8000)
            pcm_32 = array("i", [100_000_000] * 400 + [1_800_000_000] * 400)
            wf.writeframes(pcm_32.tobytes())
        bars_32, _ = extract_audio_waveform_and_duration(
            buf_32.getvalue(), "audio/wav", num_bars=4
        )
        assert bars_32 is not None
        assert bars_32[0] < bars_32[2]

    def test_silent_wav_returns_minimum_bar_floor(self):
        wav_bytes = _build_wav_bytes([0] * 1600)
        bars, duration_sec = extract_audio_waveform_and_duration(
            wav_bytes, "audio/wav"
        )

        assert bars == [MIN_WAVEFORM_BAR] * DEFAULT_WAVEFORM_BARS
        assert duration_sec == 0.2

    @pytest.mark.skipif(
        shutil.which("ffmpeg") is None, reason="ffmpeg binary not installed"
    )
    def test_decodes_mp3_bytes_via_ffmpeg_pipe(self):
        samples = [
            int(
                (4000 if i < 2000 else 28000)
                * math.sin(2 * math.pi * 440 * i / 8000)
            )
            for i in range(4000)
        ]
        wav_bytes = _build_wav_bytes(samples)
        encoded = subprocess.run(
            [
                "ffmpeg",
                "-nostdin",
                "-v",
                "error",
                "-i",
                "pipe:0",
                "-f",
                "mp3",
                "pipe:1",
            ],
            input=wav_bytes,
            capture_output=True,
            check=True,
        )

        bars, duration_sec = extract_audio_waveform_and_duration(
            encoded.stdout, "audio/mpeg", num_bars=8
        )
        assert bars is not None
        assert duration_sec is not None and duration_sec > 0
        assert len(bars) == 8
        assert bars[0] < bars[-2]
