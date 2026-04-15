# Smart Transcript & DaVinci Cutter — **XTTS v2 edition**

This repository is the **Coqui XTTS v2–only** variant: Tab 5 voice export uses **multilingual XTTS v2** (including **German**, **English**, and other supported languages). There is **no OpenVoice** stack in this build (no MeloTTS, no `checkpoints_v2`, no NLTK g2p path for OpenVoice).

For the full project that also includes optional **OpenVoice v2**, use the separate `Transcript_multi_tool_tts` tree locally if you keep that fork.

## Install (Windows)

1. Run `install.bat` and choose a venv when prompted.
2. Start the app with `start_gui.bat`.
3. In **Tab 5**, set **Runtime** to the same Python where `TTS` (Coqui) is installed, then use **Check local TTS runtime**.

## Tab 5 language

Choose the profile / export language (e.g. `de` for German). XTTS uses that language code for synthesis.

## License / upstream

Application logic is in `transcript.py`. Voice synthesis is provided by [Coqui TTS](https://github.com/coqui-ai/TTS) (XTTS v2). Respect Coqui’s license and model terms for distribution.
