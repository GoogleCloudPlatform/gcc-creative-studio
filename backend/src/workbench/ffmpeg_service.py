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
"""Service for handling FFmpeg video stitching, media probing, and filter graph
processing.
"""

import asyncio
import gc
import json
import logging
import os
import shutil
import subprocess
import tempfile
from typing import Callable

from src.workbench.dto.workbench_dto import VideoClip, VideoTimeline

logger = logging.getLogger(__name__)

TRANSITION_MAP = {
    "fade": "fade",
    "none": "fade",
    "wipe_left": "wipeleft",
    "wipe_right": "wiperight",
}


class FFmpegService:
    """A service dedicated to FFmpeg video processing, filter assembly, and
    clip stitching.
    """

    async def get_media_info(self, path: str) -> dict:
        """Runs ffprobe on a media file and returns parsed JSON metadata."""
        cmd = [
            "ffprobe",
            "-v",
            "quiet",
            "-print_format",
            "json",
            "-show_format",
            "-show_streams",
            path,
        ]
        process = await asyncio.to_thread(
            subprocess.run,
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
        )
        if process.returncode != 0:
            raise RuntimeError(f"ffprobe failed: {process.stderr.decode()}")
        return json.loads(process.stdout.decode())

    async def stitch_timeline(
        self, timeline: VideoTimeline, download_asset_fn: Callable
    ) -> tuple[str, str]:
        """Stitches a VideoTimeline object using FFmpeg and returns
        (output_path, temp_dir).
        """
        temp_dir = tempfile.mkdtemp(prefix="workbench_stitch_")
        try:
            (
                video_input_params,
                video_files,
                video_metadata,
            ) = await self._prepare_video_inputs(
                timeline, temp_dir, download_asset_fn
            )

            (
                audio_input_params,
                audio_files,
                audio_durations,
            ) = await self._prepare_audio_inputs(
                timeline, temp_dir, download_asset_fn
            )

            video_durations = [meta[0] for meta in video_metadata]
            filter_complex, video_output_stream, audio_output_stream = (
                self._build_filter_complex_from_timeline(
                    timeline,
                    video_files,
                    video_durations,
                    audio_files,
                    video_metadata,
                    audio_durations,
                )
            )

            output_path = os.path.join(temp_dir, "output.mp4")
            await asyncio.to_thread(
                self._run_ffmpeg,
                video_input_params,
                audio_input_params,
                filter_complex,
                video_output_stream,
                audio_output_stream,
                bool(video_files),
                output_path,
            )
            return output_path, temp_dir
        except Exception as e:
            if os.path.exists(temp_dir):
                shutil.rmtree(temp_dir)
            raise e

    async def _prepare_video_inputs(
        self,
        timeline: VideoTimeline,
        temp_dir: str,
        download_asset_fn: Callable,
    ) -> tuple[list[str], list[str], list[tuple[float, int, int, float]]]:
        video_input_params = []
        video_files = []
        video_metadata = []

        target_width = 1280
        target_height = 720
        target_fps = 24.0

        downloaded_info = {}
        for i, clip in enumerate(timeline.video_clips):
            if clip.presigned_url or clip.asset_ref:
                url = clip.presigned_url
                if url:
                    ext = ".mp4"
                    if "png" in url.lower():
                        ext = ".png"
                    elif "jpg" in url.lower() or "jpeg" in url.lower():
                        ext = ".jpg"
                    video_path = os.path.join(temp_dir, f"video_src_{i}{ext}")
                    await download_asset_fn(url, video_path)
                    try:
                        info = await self.get_media_info(video_path)
                        v_stream = next(
                            (
                                s
                                for s in info["streams"]
                                if s["codec_type"] == "video"
                            ),
                            None,
                        )
                        if v_stream:
                            w = int(v_stream.get("width", 1280))
                            h = int(v_stream.get("height", 720))
                            dur = float(
                                info.get("format", {}).get("duration", 4.0)
                            )
                            fps_eval = 24.0
                            r_fps = v_stream.get("r_frame_rate", "24/1")
                            if "/" in r_fps:
                                num, den = r_fps.split("/")
                                fps_eval = (
                                    float(num) / float(den)
                                    if float(den) > 0
                                    else 24.0
                                )
                            else:
                                fps_eval = float(r_fps)
                            downloaded_info[i] = (
                                video_path,
                                dur,
                                w,
                                h,
                                fps_eval,
                            )
                    except Exception as e:  # pylint: disable=broad-except
                        logger.warning(
                            "Could not probe video clip %s: %s", i, e
                        )

        if downloaded_info:
            first_idx = sorted(downloaded_info.keys())[0]
            _, _, w, h, fps_val = downloaded_info[first_idx]
            target_width = w
            target_height = h
            target_fps = fps_val

        for i, clip in enumerate(timeline.video_clips):
            if i in downloaded_info:
                v_path, dur, w, h, fps_val = downloaded_info[i]
                is_image = v_path.lower().endswith((".png", ".jpg", ".jpeg"))
                if is_image:
                    v_path = await asyncio.to_thread(
                        self._create_static_video_from_image,
                        v_path,
                        clip,
                        temp_dir,
                        i,
                        target_width,
                        target_height,
                        target_fps,
                    )
                    dur = (
                        clip.trim.duration_seconds
                        if (clip.trim and clip.trim.duration_seconds)
                        else 4.0
                    )
                    w, h, fps_val = target_width, target_height, target_fps

                video_files.append(v_path)
                video_metadata.append((dur, w, h, fps_val))

                params = []
                if clip.trim and clip.trim.offset_seconds > 0:
                    params.extend(["-ss", str(clip.trim.offset_seconds)])
                if clip.trim and clip.trim.duration_seconds:
                    params.extend(["-t", str(clip.trim.duration_seconds)])
                params.extend(["-i", v_path])
                video_input_params.extend(params)
            else:
                placeholder_path = await asyncio.to_thread(
                    self._create_placeholder_clip,
                    clip,
                    temp_dir,
                    i,
                    target_width,
                    target_height,
                )
                video_files.append(placeholder_path)
                dur = (
                    clip.trim.duration_seconds
                    if (clip.trim and clip.trim.duration_seconds)
                    else 4.0
                )
                video_metadata.append(
                    (dur, target_width, target_height, target_fps)
                )
                video_input_params.extend(["-i", placeholder_path])

        return video_input_params, video_files, video_metadata

    def _create_silent_audio_clip(
        self, temp_dir: str, index: int, duration: float
    ) -> str:
        output_path = os.path.join(temp_dir, f"silent_audio_{index}.wav")
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=44100:cl=stereo",
            "-t",
            str(duration if duration > 0 else 1.0),
            output_path,
        ]
        subprocess.run(
            cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return output_path

    async def _prepare_audio_inputs(
        self,
        timeline: VideoTimeline,
        temp_dir: str,
        download_asset_fn: Callable,
    ) -> tuple[list[str], list[str], list[float]]:
        audio_input_params = []
        audio_files = []
        audio_durations = []
        if timeline.audio_clips:
            for i, audio_clip in enumerate(timeline.audio_clips):
                url = audio_clip.presigned_url
                audio_path = None
                if url:
                    ext = ".mp3"
                    url_lower = url.lower()
                    if "wav" in url_lower:
                        ext = ".wav"
                    elif "aac" in url_lower:
                        ext = ".aac"
                    elif "m4a" in url_lower:
                        ext = ".m4a"
                    elif "ogg" in url_lower:
                        ext = ".ogg"
                    download_path = os.path.join(
                        temp_dir, f"audio_src_{i}{ext}"
                    )
                    await download_asset_fn(url, download_path)
                    dur = 0.0
                    try:
                        info = await self.get_media_info(download_path)
                        has_audio = any(
                            s.get("codec_type") == "audio"
                            for s in info.get("streams", [])
                        )
                        if has_audio:
                            audio_path = download_path
                            dur_str = info.get("format", {}).get(
                                "duration", "4.0"
                            )
                            try:
                                dur = float(dur_str)
                            except ValueError:
                                dur = 4.0
                        else:
                            logger.warning(
                                "Audio clip %d (%s) contains no audio stream. "
                                "Using silent audio placeholder.",
                                i,
                                download_path,
                            )
                    except Exception as e:  # pylint: disable=broad-except
                        logger.warning(
                            "Could not probe audio clip %s: %s", i, e
                        )

                    if audio_path:
                        audio_durations.append(dur)

                if not audio_path:
                    dur = (
                        audio_clip.trim.duration_seconds
                        if (
                            audio_clip.trim and audio_clip.trim.duration_seconds
                        )
                        else 4.0
                    )
                    audio_path = await asyncio.to_thread(
                        self._create_silent_audio_clip, temp_dir, i, dur
                    )
                    audio_durations.append(dur)

                audio_files.append(audio_path)
                params = []
                if audio_clip.trim and audio_clip.trim.offset_seconds > 0:
                    params.extend(["-ss", str(audio_clip.trim.offset_seconds)])
                params.extend(["-i", audio_path])
                audio_input_params.extend(params)
        return audio_input_params, audio_files, audio_durations

    def _create_placeholder_clip(
        self,
        clip: VideoClip,
        temp_dir: str,
        index: int,
        width: int,
        height: int,
    ) -> str:
        placeholder_path = os.path.join(temp_dir, f"placeholder_{index}.mp4")
        duration = (
            clip.trim.duration_seconds
            if (clip.trim and clip.trim.duration_seconds)
            else 4.0
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-f",
            "lavfi",
            "-i",
            f"color=c=black:s={width}x{height}:d={duration}",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            placeholder_path,
        ]
        subprocess.run(
            cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return placeholder_path

    def _create_static_video_from_image(
        self,
        image_path: str,
        clip: VideoClip,
        temp_dir: str,
        index: int,
        width: int,
        height: int,
        fps: float,
    ) -> str:
        output_path = os.path.join(temp_dir, f"static_video_{index}.mp4")
        duration = (
            clip.trim.duration_seconds
            if (clip.trim and clip.trim.duration_seconds)
            else 4.0
        )
        cmd = [
            "ffmpeg",
            "-y",
            "-loop",
            "1",
            "-i",
            image_path,
            "-c:v",
            "libx264",
            "-t",
            str(duration),
            "-pix_fmt",
            "yuv420p",
            "-vf",
            (
                f"scale=w={width}:h={height}:"
                "force_original_aspect_ratio=decrease,"
                f"pad=w={width}:h={height}:x=(ow-iw)/2:y=(oh-ih)/2"
            ),
            "-r",
            str(fps),
            output_path,
        ]
        subprocess.run(
            cmd, check=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE
        )
        return output_path

    def _build_filter_complex_from_timeline(
        self,
        timeline: VideoTimeline,
        video_files: list[str],
        video_durations: list[float],
        audio_files: list[str],
        video_metadata: list,
        audio_durations: list[float],
    ) -> tuple[str, str, str]:
        video_filters = []
        audio_filters = []
        video_output_stream = ""
        audio_output_stream = ""
        num_video_files = len(video_files)

        clip_start_times = [0.0] * num_video_files

        if num_video_files > 0:
            width, height, fps = (
                video_metadata[0][1],
                video_metadata[0][2],
                video_metadata[0][3],
            )
            normalized_streams = []
            for i in range(num_video_files):
                norm_str = f"[norm_v{i}]"
                normalized_streams.append(norm_str)
                clip_speed = (
                    timeline.video_clips[i].speed
                    if i < len(timeline.video_clips)
                    else 1.0
                )
                pts_filter = (
                    f"setpts=(PTS-STARTPTS)/{clip_speed},"
                    if clip_speed != 1.0
                    else "setpts=PTS-STARTPTS,"
                )
                video_filters.append(
                    f"[{i}:v]{pts_filter}fps={fps},"
                    f"scale=w={width}:h={height}:"
                    "force_original_aspect_ratio=decrease,"
                    f"pad=w={width}:h={height}:x=(ow-iw)/2:y=(oh-ih)/2,"
                    f"format=yuv420p,settb=AVTB{norm_str}"
                )

            clip_durations = []
            for i in range(num_video_files):
                clip = (
                    timeline.video_clips[i]
                    if i < len(timeline.video_clips)
                    else None
                )
                dur = video_durations[i]
                if clip and clip.trim:
                    if clip.trim.duration_seconds:
                        dur = clip.trim.duration_seconds
                    elif clip.trim.offset_seconds > 0:
                        dur = max(0.1, dur - clip.trim.offset_seconds)
                speed = clip.speed if (clip and clip.speed) else 1.0
                if speed != 1.0:
                    dur = dur / speed
                clip_durations.append(dur)

            accumulated_duration = 0.0
            for i in range(num_video_files):
                clip_start_times[i] = accumulated_duration
                t_dur = 0.0
                if (
                    i < num_video_files - 1
                    and i < len(timeline.transitions)
                    and (transition := timeline.transitions[i]) is not None
                    and transition.type.value != "none"
                ):
                    t_dur = transition.duration_seconds
                accumulated_duration += clip_durations[i] - t_dur / 2

            if num_video_files > 1:
                last_v_stream = normalized_streams[0]
                for i in range(num_video_files - 1):
                    transition = (
                        timeline.transitions[i]
                        if i < len(timeline.transitions)
                        else None
                    )
                    next_v_stream = normalized_streams[i + 1]
                    output_v_stream = f"[v{i + 1}]"

                    if (
                        transition
                        and transition.type.value != "none"
                        and transition.duration_seconds > 0
                    ):
                        offset = clip_start_times[i + 1]
                        t_type = TRANSITION_MAP.get(
                            transition.type.value, transition.type.value
                        )
                        video_filters.append(
                            f"{last_v_stream}{next_v_stream}xfade="
                            f"transition={t_type}:"
                            f"duration={transition.duration_seconds}:"
                            f"offset={offset}{output_v_stream}"
                        )
                    else:
                        video_filters.append(
                            f"{last_v_stream}{next_v_stream}"
                            f"concat=n=2:v=1:a=0{output_v_stream}"
                        )

                    last_v_stream = output_v_stream
                video_output_stream = last_v_stream
            else:
                video_output_stream = normalized_streams[0]

            if (
                timeline.transition_in
                and timeline.transition_in.type.value != "none"
            ):
                t_in = timeline.transition_in
                t_type = TRANSITION_MAP.get(t_in.type.value, t_in.type.value)
                d = t_in.duration_seconds
                if t_type == "fade":
                    video_filters.append(
                        f"{video_output_stream}fade=t=in:st=0:d={d}[v_fadein]"
                    )
                else:
                    video_filters.append(
                        f"color=c=black:s={width}x{height}:d={d},"
                        f"fps={fps},format=yuv420p,settb=AVTB[v_in_black];"
                        f"[v_in_black]{video_output_stream}xfade="
                        f"transition={t_type}:duration={d}:offset=0[v_fadein]"
                    )
                video_output_stream = "[v_fadein]"

            if (
                timeline.transition_out
                and timeline.transition_out.type.value != "none"
            ):
                t_out = timeline.transition_out
                t_type = TRANSITION_MAP.get(t_out.type.value, t_out.type.value)
                d = t_out.duration_seconds
                st_out = max(0.0, accumulated_duration - d)
                if t_type == "fade":
                    video_filters.append(
                        f"{video_output_stream}fade=t=out:st={st_out}:d={d}[v_fadeout]"
                    )
                else:
                    video_filters.append(
                        f"color=c=black:s={width}x{height}:d={d},"
                        f"fps={fps},format=yuv420p,settb=AVTB[v_out_black];"
                        f"{video_output_stream}[v_out_black]xfade="
                        f"transition={t_type}:duration={d}:offset={st_out}[v_fadeout]"
                    )
                video_output_stream = "[v_fadeout]"

        if audio_files:
            audio_outputs = []
            for i, audio_clip in enumerate(timeline.audio_clips):
                if i >= len(audio_files):
                    break
                v_clip_idx = audio_clip.start_at.video_clip_index
                if v_clip_idx < 0 or v_clip_idx >= len(clip_start_times):
                    v_start = 0.0
                else:
                    v_start = clip_start_times[v_clip_idx]
                start_time = v_start + audio_clip.start_at.offset_seconds

                audio_stream_idx = num_video_files + i
                current_stream = f"[{audio_stream_idx}:a]"
                chain = []

                original_audio_dur = (
                    audio_durations[i] if i < len(audio_durations) else 4.0
                )
                eff_dur = original_audio_dur

                if audio_clip.trim:
                    if audio_clip.trim.duration_seconds:
                        eff_dur = audio_clip.trim.duration_seconds
                    elif audio_clip.trim.offset_seconds > 0:
                        eff_dur = max(
                            0.1,
                            eff_dur - audio_clip.trim.offset_seconds,
                        )

                if audio_clip.trim and audio_clip.trim.duration_seconds:
                    trimmed_stream = f"[a{i}_trimmed]"
                    chain.append(
                        f"{current_stream}atrim=duration="
                        f"{audio_clip.trim.duration_seconds},"
                        f"asetpts=PTS-STARTPTS{trimmed_stream}"
                    )
                    current_stream = trimmed_stream

                if audio_clip.speed != 1.0:
                    tempo_stream = f"[a{i}_tempo]"
                    chain.append(
                        f"{current_stream}atempo="
                        f"{audio_clip.speed}{tempo_stream}"
                    )
                    current_stream = tempo_stream
                    if eff_dur is not None:
                        eff_dur = eff_dur / audio_clip.speed

                if audio_clip.fade_in_duration_seconds > 0:
                    fadein_stream = f"[a{i}_fadein]"
                    chain.append(
                        f"{current_stream}afade=t=in:st=0:d="
                        f"{audio_clip.fade_in_duration_seconds}{fadein_stream}"
                    )
                    current_stream = fadein_stream

                if (
                    audio_clip.fade_out_duration_seconds > 0
                    and eff_dur is not None
                ):
                    fadeout_stream = f"[a{i}_fadeout]"
                    fade_out_start = (
                        eff_dur - audio_clip.fade_out_duration_seconds
                    )
                    if fade_out_start >= 0:
                        chain.append(
                            f"{current_stream}afade=t=out:st={fade_out_start}:"
                            f"d={audio_clip.fade_out_duration_seconds}"
                            f"{fadeout_stream}"
                        )
                        current_stream = fadeout_stream

                delayed_stream = f"[a{i}_delayed]"
                delay_ms = max(0, int(start_time * 1000))
                chain.append(
                    f"{current_stream}adelay={delay_ms}:all=1"
                    f"{delayed_stream}"
                )
                current_stream = delayed_stream

                audio_filters.extend(chain)
                audio_outputs.append(current_stream)

            if len(audio_outputs) > 1:
                joined_audio = "".join(audio_outputs)
                audio_filters.append(
                    f"{joined_audio}amix=inputs={len(audio_outputs)}:"
                    "duration=longest:normalize=0[audio_mix]"
                )
                audio_output_stream = "[audio_mix]"
            elif len(audio_outputs) == 1:
                audio_filters.append(f"{audio_outputs[0]}acopy[audio_mix]")
                audio_output_stream = "[audio_mix]"

            if audio_output_stream and accumulated_duration > 0:
                audio_filters.append(
                    f"{audio_output_stream}atrim="
                    f"duration={accumulated_duration},"
                    f"asetpts=PTS-STARTPTS[audio_final]"
                )
                audio_output_stream = "[audio_final]"

        return (
            ";".join(video_filters + audio_filters),
            video_output_stream,
            audio_output_stream,
        )

    def _run_ffmpeg(
        self,
        video_input_params: list[str],
        audio_input_params: list[str],
        filter_complex: str,
        video_output_stream: str,
        audio_output_stream: str,
        has_video: bool,
        output_path: str,
    ) -> None:
        ffmpeg_command = [
            "ffmpeg",
            "-y",
            *video_input_params,
            *audio_input_params,
        ]
        if filter_complex:
            ffmpeg_command.extend(["-filter_complex", filter_complex])
        if has_video and video_output_stream:
            ffmpeg_command.extend(["-map", video_output_stream])
        if audio_output_stream:
            ffmpeg_command.extend(["-map", audio_output_stream])

        ffmpeg_command.extend(
            [
                "-threads",
                "1",
                "-preset",
                "ultrafast",
                "-c:v",
                "libx264",
                "-pix_fmt",
                "yuv420p",
                "-c:a",
                "aac",
                output_path,
            ]
        )
        gc.collect()
        process = subprocess.run(
            ffmpeg_command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
        if process.returncode != 0:
            logger.error("FFmpeg failed: %s", process.stderr.decode())
            raise RuntimeError(f"FFmpeg failed: {process.stderr.decode()}")
