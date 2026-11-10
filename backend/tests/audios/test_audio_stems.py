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
"""Unit tests for the pure-numpy/ONNX CPU audio stem engine."""

import io
from pathlib import Path
import shutil
from unittest.mock import MagicMock, patch

import numpy as np
import pytest

from src.audios import audio_stems
from src.audios.audio_stems import (
    DEFAULT_MODEL_FILENAME,
    HTDEMUCS_6S_SOURCES,
    N_SAMPLES,
    SAMPLE_RATE,
    compute_stem_cache_key,
    compute_stem_energy,
    decode_audio_to_stereo_f32,
    encode_stereo_f32_to_mp3,
    encode_stereo_f32_to_wav,
    ensure_model_file,
    get_ort_session,
    mix_stem_arrays,
    separate_audio_bytes,
    separate_stereo_44k,
)


class _DummyIdentitySession:
    """Fake ONNX session splitting input energy across the 6 Demucs stems."""

    def __init__(self):
        self.calls = 0

    def run(self, _outputs, feed_dict):
        self.calls += 1
        mix = feed_dict["mix"]  # (1, 2, N_SAMPLES)
        weights = np.array(
            [0.25, 0.20, 0.10, 0.25, 0.10, 0.10],
            dtype=np.float32,
        )[:, np.newaxis, np.newaxis]
        stems = mix[:, np.newaxis, :, :] * weights[np.newaxis, ...]
        return [stems]


def test_compute_stem_cache_key_deterministic_and_validates_empty():
    key1 = compute_stem_cache_key("gs://bucket/audio/track.mp3")
    key2 = compute_stem_cache_key("  gs://bucket/audio/track.mp3  ")
    key3 = compute_stem_cache_key("gs://bucket/audio/other.mp3")

    assert key1 == key2
    assert len(key1) == 24
    assert key1 != key3

    with pytest.raises(ValueError, match="cannot be empty"):
        compute_stem_cache_key("   ")


def test_compute_stem_energy_distinguishes_silence_and_signal():
    assert compute_stem_energy(np.zeros((2, 0), dtype=np.float32)) == (
        0.0,
        False,
    )

    quiet = np.full((2, 4096), 0.0005, dtype=np.float32)
    peak_q, has_q = compute_stem_energy(quiet)
    assert has_q is False
    assert peak_q < 0.01

    active = np.full((2, 4096), 0.35, dtype=np.float32)
    peak_a, has_a = compute_stem_energy(active)
    assert has_a is True
    assert peak_a == pytest.approx(0.35, abs=1e-3)


def test_mix_stem_arrays_sums_and_limits_peaks():
    with pytest.raises(ValueError, match="At least one stem"):
        mix_stem_arrays([])

    with pytest.raises(ValueError, match="Expected non-empty stereo"):
        mix_stem_arrays([np.zeros((1, 100), dtype=np.float32)])

    s1 = np.full((2, 1000), 0.7, dtype=np.float32)
    s2 = np.full((2, 800), 0.6, dtype=np.float32)
    mixed = mix_stem_arrays([s1, s2])

    assert mixed.shape == (2, 1000)
    assert float(np.max(np.abs(mixed))) <= 0.9901
    # Tail beyond 800 samples should reflect s1 scaled by same limiter ratio
    assert float(mixed[0, 950]) < float(mixed[0, 100])


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg binary not installed"
)
def test_encode_and_decode_roundtrip_wav_and_mp3():
    t = np.linspace(0.0, 0.25, int(SAMPLE_RATE * 0.25), endpoint=False)
    tone = (0.4 * np.sin(2 * np.pi * 440.0 * t)).astype(np.float32)
    stereo = np.stack([tone, -tone], axis=0)

    wav_bytes = encode_stereo_f32_to_wav(stereo)
    decoded_wav = decode_audio_to_stereo_f32(wav_bytes)
    assert decoded_wav.shape == stereo.shape
    assert float(np.max(np.abs(decoded_wav - stereo))) < 0.01

    mp3_bytes = encode_stereo_f32_to_mp3(stereo, bitrate="192k")
    assert len(mp3_bytes) > 200
    decoded_mp3 = decode_audio_to_stereo_f32(mp3_bytes)
    assert decoded_mp3.shape[0] == 2
    assert decoded_mp3.shape[1] > 0

    with pytest.raises(ValueError, match="up to 0s"):
        decode_audio_to_stereo_f32(wav_bytes, max_duration_seconds=0.05)


def test_decode_and_encode_validation_errors():
    with pytest.raises(ValueError, match="empty"):
        decode_audio_to_stereo_f32(b"")

    with pytest.raises(ValueError, match="Failed to decode"):
        decode_audio_to_stereo_f32(b"not-valid-audio")

    with pytest.raises(ValueError, match="Expected stereo"):
        encode_stereo_f32_to_mp3(np.zeros((1, 100), dtype=np.float32))

    with pytest.raises(ValueError, match="empty audio"):
        encode_stereo_f32_to_wav(np.zeros((2, 0), dtype=np.float32))


def test_ensure_model_file_uses_gcs_cache_and_https_fallback(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.delenv("AUDIO_STEM_MODEL_PATH", raising=False)
    fake_payload = b"x" * 1_100_000

    # 1. GCS cache hit
    gcs_dir = tmp_path / "gcs_case"

    def _gcs_hit(dest: Path) -> bool:
        dest.write_bytes(fake_payload)
        return True

    resolved_gcs = ensure_model_file(
        gcs_dir,
        "https://example.com/model.onnx",
        gcs_download_fn=_gcs_hit,
    )
    assert resolved_gcs == gcs_dir / DEFAULT_MODEL_FILENAME
    assert resolved_gcs.stat().st_size == len(fake_payload)

    # 2. HTTPS download + GCS mirror upload
    https_dir = tmp_path / "https_case"
    mirrored: list[Path] = []

    class _FakeHttpResponse(io.BytesIO):
        def __enter__(self):
            return self

        def __exit__(self, *args):
            self.close()

    with patch(
        "urllib.request.urlopen",
        return_value=_FakeHttpResponse(fake_payload),
    ):
        resolved_https = ensure_model_file(
            https_dir,
            "https://example.com/model.onnx",
            gcs_download_fn=lambda _p: False,
            gcs_upload_fn=mirrored.append,
        )

    assert resolved_https == https_dir / DEFAULT_MODEL_FILENAME
    assert len(mirrored) == 1

    # 3. Explicit env override validation
    monkeypatch.setenv("AUDIO_STEM_MODEL_PATH", str(resolved_https))
    assert (
        ensure_model_file(tmp_path / "unused", "https://example.com/m.onnx")
        == resolved_https
    )

    monkeypatch.setenv("AUDIO_STEM_MODEL_PATH", str(tmp_path / "missing.onnx"))
    with pytest.raises(FileNotFoundError):
        ensure_model_file(tmp_path / "unused", "https://example.com/m.onnx")


def test_get_ort_session_caches_instance(tmp_path: Path):
    fake_model = tmp_path / "dummy.onnx"
    fake_model.write_bytes(b"onnx")
    mock_session = MagicMock()

    audio_stems._SESSION_CACHE.clear()
    with patch(
        "onnxruntime.InferenceSession", return_value=mock_session
    ) as ctor:
        s1 = get_ort_session(fake_model, intra_op_threads=2)
        s2 = get_ort_session(fake_model, intra_op_threads=2)

    assert s1 is mock_session
    assert s2 is mock_session
    assert ctor.call_count == 1
    audio_stems._SESSION_CACHE.clear()


def test_separate_stereo_44k_overlap_add_reconstructs_mix():
    total_len = int(N_SAMPLES * 1.4)  # Exercises multi-chunk overlap-add
    rng = np.random.default_rng(42)
    mix = rng.uniform(-0.5, 0.5, size=(2, total_len)).astype(np.float32)

    session = _DummyIdentitySession()
    stems = separate_stereo_44k(mix, session)

    assert session.calls == 2
    assert tuple(stems.keys()) == HTDEMUCS_6S_SOURCES
    reconstructed = sum(stems.values())
    assert reconstructed.shape == mix.shape
    assert np.allclose(reconstructed, mix, atol=1e-5)

    # Mono input auto-expands to stereo
    mono_stems = separate_stereo_44k(mix[:1, :2000], session)
    assert mono_stems["vocals"].shape == (2, 2000)


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg binary not installed"
)
def test_separate_audio_bytes_end_to_end_with_mock_ort(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fake_model = tmp_path / DEFAULT_MODEL_FILENAME
    fake_model.write_bytes(b"m" * 1_100_000)
    monkeypatch.setenv("AUDIO_STEM_MODEL_PATH", str(fake_model))

    stereo = np.full((2, 8000), 0.25, dtype=np.float32)
    wav_bytes = encode_stereo_f32_to_wav(stereo)

    with patch(
        "src.audios.audio_stems.get_ort_session",
        return_value=_DummyIdentitySession(),
    ):
        stems = separate_audio_bytes(
            wav_bytes,
            cache_dir=tmp_path,
            model_url="https://example.com/model.onnx",
        )

    assert set(stems.keys()) == set(HTDEMUCS_6S_SOURCES)
    assert stems["vocals"].shape[0] == 2


@pytest.mark.skipif(
    shutil.which("ffmpeg") is None, reason="ffmpeg binary not installed"
)
def test_separate_and_encode_stems_mp3_streams_multi_chunk_accurately(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    fake_model = tmp_path / DEFAULT_MODEL_FILENAME
    fake_model.write_bytes(b"m" * 1_100_000)
    monkeypatch.setenv("AUDIO_STEM_MODEL_PATH", str(fake_model))

    # 1.25 chunks exercises carry-window overlap-add across chunk boundaries
    total_len = int(N_SAMPLES * 1.25)
    t = np.linspace(0.0, total_len / SAMPLE_RATE, total_len, endpoint=False)
    tone = (0.4 * np.sin(2 * np.pi * 330.0 * t)).astype(np.float32)
    stereo = np.stack([tone, tone], axis=0)
    wav_bytes = encode_stereo_f32_to_wav(stereo)

    ref_session = _DummyIdentitySession()
    expected_arrays = separate_stereo_44k(stereo, ref_session)

    stream_session = _DummyIdentitySession()
    with patch(
        "src.audios.audio_stems.get_ort_session",
        return_value=stream_session,
    ):
        encoded = audio_stems.separate_and_encode_stems_mp3(
            wav_bytes,
            cache_dir=tmp_path,
            model_url="https://example.com/model.onnx",
        )

    assert stream_session.calls == 2
    assert set(encoded.keys()) == set(HTDEMUCS_6S_SOURCES)
    for stem_name in HTDEMUCS_6S_SOURCES:
        exp_peak, exp_energy = compute_stem_energy(expected_arrays[stem_name])
        res = encoded[stem_name]
        assert len(res.mp3_bytes) > 500
        assert res.peak_level == pytest.approx(exp_peak, abs=1e-4)
        assert res.has_energy is exp_energy
        assert res.duration_seconds == pytest.approx(
            total_len / SAMPLE_RATE, abs=0.02
        )
