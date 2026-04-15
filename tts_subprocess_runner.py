"""
Subprocess worker for Tab 5 voice export (XTTS v2 edition).

Engine:
  - xtts_v2: Coqui TTS XTTS v2 only (multilingual, including German).
"""
from __future__ import annotations

import json
import os
import re
import shutil
import sys
import wave


def _progress(i: int, total: int) -> None:
    print(f"PROGRESS {i}/{total}", flush=True)


def _split_sentences_for_chunk(text: str) -> list[str]:
    t = (text or "").strip()
    if not t:
        return []
    parts = [p.strip() for p in re.split(r"(?<=[.!?])\s+", t) if p.strip()]
    return parts if parts else [t]


def _concat_wavs_with_silence_ms(part_paths: list[str], silence_ms: int, out_path: str) -> None:
    if not part_paths:
        raise RuntimeError("concat: no input wavs")
    if len(part_paths) == 1:
        shutil.copyfile(part_paths[0], out_path)
        return
    silence_ms = max(0, int(silence_ms))
    with wave.open(part_paths[0], "rb") as w0:
        nch = w0.getnchannels()
        sw = w0.getsampwidth()
        fr = w0.getframerate()
        blobs: list[bytes] = [w0.readframes(w0.getnframes())]
    silence_frames = int(fr * (silence_ms / 1000.0))
    silence_b = b"\x00" * (silence_frames * nch * sw)
    for p in part_paths[1:]:
        blobs.append(silence_b)
        with wave.open(p, "rb") as wn:
            if (
                wn.getnchannels() != nch
                or wn.getsampwidth() != sw
                or wn.getframerate() != fr
            ):
                raise RuntimeError("concat: wav format mismatch between sentence parts")
            blobs.append(wn.readframes(wn.getnframes()))
    merged = b"".join(blobs)
    with wave.open(out_path, "wb") as out:
        out.setnchannels(nch)
        out.setsampwidth(sw)
        out.setframerate(fr)
        out.writeframes(merged)


def run_xtts_v2(p: dict) -> None:
    import torch
    from torch.serialization import add_safe_globals
    from TTS.config.shared_configs import BaseAudioConfig, BaseDatasetConfig, BaseTrainingConfig
    from TTS.tts.configs.xtts_config import XttsConfig
    from TTS.tts.models.xtts import XttsArgs, XttsAudioConfig
    from TTS.api import TTS

    add_safe_globals(
        [
            BaseAudioConfig,
            BaseDatasetConfig,
            BaseTrainingConfig,
            XttsConfig,
            XttsAudioConfig,
            XttsArgs,
        ]
    )

    ref = p["reference_wav"]
    lang = p["language"]
    chunks = p["chunks"]
    out_dir = p["out_dir"]
    model_name = p.get("coqui_model") or "tts_models/multilingual/multi-dataset/xtts_v2"
    tts = TTS(model_name=model_name, progress_bar=False)
    if torch.cuda.is_available():
        try:
            tts = tts.to("cuda")
        except Exception:
            pass
    sentence_pause_ms = int(p.get("sentence_pause_ms") or 0)
    total = len(chunks)
    for i, chunk in enumerate(chunks, start=1):
        out = os.path.join(out_dir, f"chunk_{i:04d}.wav")
        sents = _split_sentences_for_chunk(chunk)
        if len(sents) > 1 and sentence_pause_ms > 0:
            part_paths: list[str] = []
            try:
                for j, s in enumerate(sents):
                    pw = os.path.join(out_dir, f"_c{i:04d}_p{j:03d}.wav")
                    sl = len(s or "")
                    tts.tts_to_file(
                        text=s,
                        speaker_wav=ref,
                        language=lang,
                        file_path=pw,
                        split_sentences=sl > 800,
                    )
                    part_paths.append(pw)
                _concat_wavs_with_silence_ms(part_paths, sentence_pause_ms, out)
            finally:
                for pw in part_paths:
                    try:
                        if os.path.isfile(pw):
                            os.remove(pw)
                    except OSError:
                        pass
        else:
            chunk_len = len(chunk or "")
            split_sentences = chunk_len > 800
            tts.tts_to_file(
                text=chunk,
                speaker_wav=ref,
                language=lang,
                file_path=out,
                split_sentences=split_sentences,
            )
        _progress(i, total)
    print("ok", flush=True)


def main() -> None:
    if len(sys.argv) < 2:
        raise SystemExit("usage: python tts_subprocess_runner.py <payload.json>")
    with open(sys.argv[1], "r", encoding="utf-8") as f:
        p = json.load(f)
    eng = (p.get("engine") or "xtts_v2").strip().lower()
    if eng in {"xtts_v2", "xtts"}:
        run_xtts_v2(p)
    else:
        raise SystemExit(
            f"This repo build supports only Coqui XTTS v2 (engine xtts_v2). Got: {eng!r}"
        )


if __name__ == "__main__":
    main()
