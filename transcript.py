import os
import re
import time
import threading
import warnings
import subprocess
import json
import tempfile
import shutil
import sys
import importlib.util
import customtkinter as ctk
from tkinter import filedialog, messagebox
from tkinterdnd2 import TkinterDnD, DND_FILES
import whisper
import torch
try:
    from deep_translator import GoogleTranslator
except Exception:
    GoogleTranslator = None

ctk.set_appearance_mode('Dark')
ctk.set_default_color_theme('dark-blue')

LANGUAGE_CODES = ["auto", "de", "en", "fr", "es", "it", "pt", "ru", "ja", "zh", "ko", "ar", "hi", "tr"]
TTS_CREATION_PRESETS = {
    "balanced_default": {
        "label": "Balanced (recommended)",
        "preprocess": "voice_clean",
        "description": "Good general clarity and natural tone."
    },
    "clear_voice": {
        "label": "Clear voice",
        "preprocess": "speech_boost",
        "description": "Sharper, more focused speech."
    },
    "room_noise_cleanup": {
        "label": "Room/noise cleanup",
        "preprocess": "music_heavy_cleanup",
        "description": "More aggressive cleanup for noisy/echo rooms."
    }
}
TTS_DELIVERY_STYLES = ["neutral", "calm", "fast"]
TTS_PAUSE_LEVELS = ["none", "low", "medium", "high"]
TTS_CLEAR_SPEECH_STRENGTHS = ["soft", "medium", "strong"]
TTS_BREATH_CONTROL_LEVELS = ["off", "low", "medium", "high"]
TTS_RESULT_PRESETS = {
    "clear_narration": {
        "label": "Clear Narration",
        "output_style": "clear_speech",
        "clear_strength": "medium",
        "breath_control": "medium",
        "delivery_style": "neutral",
        "pause_level": "low",
        "chunk_chars": 0,
        "prefer_full_sentences": True,
        "description": "Clean, intelligible, minimal distractions."
    },
    "calm_story": {
        "label": "Calm Story",
        "output_style": "natural",
        "breath_control": "low",
        "delivery_style": "calm",
        "pause_level": "medium",
        "chunk_chars": 0,
        "prefer_full_sentences": True,
        "description": "Relaxed pacing with natural pauses."
    },
    "fast_tight": {
        "label": "Fast Tight",
        "output_style": "clear_speech",
        "clear_strength": "strong",
        "breath_control": "high",
        "delivery_style": "fast",
        "pause_level": "none",
        "chunk_chars": 300,
        "prefer_full_sentences": False,
        "description": "Compact and energetic, very few pauses."
    },
    "expressive": {
        "label": "Expressive",
        "output_style": "clear_speech",
        "clear_strength": "soft",
        "breath_control": "medium",
        "delivery_style": "calm",
        "pause_level": "medium",
        "chunk_chars": 0,
        "prefer_full_sentences": True,
        "description": "Expressive pacing with cleaner voice and controlled pauses."
    }
}
# Tab 5: persisted in ui_settings as "tts_engine". This repo build is XTTS v2 only.
TTS_ENGINE_XTTS_V2 = "xtts_v2"
TTS_ENGINES = (TTS_ENGINE_XTTS_V2,)
DEFAULT_FILTER_PRESETS = {
    "Casual DE": {"delete": "ähm, ah, also, hm, hmm", "replace": ""},
    "Podcast Clean": {"delete": "um, uh, er, ah, hmm", "replace": ""},
    "Tutorial Tech": {"delete": "ähm, also, quasi, irgendwie", "replace": "ffmpg:ffmpeg"}
}

class DnD_CTk(ctk.CTk, TkinterDnD.DnDWrapper):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.TkdndVersion = TkinterDnD._require(self)

class TranskriptionApp(DnD_CTk):
    def __init__(self):
        super().__init__()
        self.geometry("950x800")
        
        self.video_path = ""
        self.original_text = ""
        self.working_text = ""
        self.gefilterter_text = ""
        self.word_timestamps = [] # Speichert jedes Wort mit Start-/Endzeit
        self.last_imported_clip = None
        self.transcription_stage = "idle"
        self.transcription_start_time = None
        self.transcription_running = False
        self.transcription_eta_total_seconds = None
        self.auto_punctuation_enabled = True
        self.change_history = []
        self.redo_history = []
        self.max_history = 200
        self.initial_state = None
        self.copy_block_cycle_index = 0
        self.auto_chunk_after_transcription = True
        self.tts_profiles_root = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_profiles")
        self.tts_profiles_index_path = os.path.join(self.tts_profiles_root, "profiles.json")
        self.tts_profiles = {}
        self.tts_selected_reference_path = ""
        self.tts_multi_ref_paths = []
        self.tts_runtime_mode = "conda_env"
        self.tts_conda_env_name = "autocut_env"
        self.tts_python_path = ""
        self.tts_cancel_requested = False
        self.tts_active_process = None
        self.tts_hf_download_busy = False
        self._ffmpeg_exe_cached = None
        self.ui_settings_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ui_settings.json")
        self.ui_settings = self._load_ui_settings()
        saved_ui_lang = str(self.ui_settings.get("ui_language", "EN")).strip().upper()
        if saved_ui_lang not in {"EN", "DE"}:
            saved_ui_lang = "EN"
        self.ui_lang_var = ctk.StringVar(value=saved_ui_lang)
        self.title(
            self._tr(
                "Smart Transcript & DaVinci Cutter (XTTS v2)",
                "Smart Transkript & DaVinci Cutter (XTTS v2)",
            )
        )

        self.top_controls = ctk.CTkFrame(self, fg_color="transparent")
        self.top_controls.pack(fill='x', padx=20, pady=(10, 0))
        self.language_toggle = ctk.CTkSegmentedButton(
            self.top_controls,
            values=["EN", "DE"],
            variable=self.ui_lang_var,
            command=self.on_ui_language_changed,
            width=120
        )
        self.language_toggle.pack(side='right')

        self.tabs = ctk.CTkTabview(self)
        self.tabs.pack(fill='both', expand=True, padx=20, pady=15)
        
        self.tab_source = self.tabs.add(self._tr("1. Source & Whisper", "1. Quelle & Whisper"))
        self.tab_filter = self.tabs.add(self._tr("2. Filter & Replace", "2. Filter & Ersetzen"))
        self.tab_export = self.tabs.add(self._tr("3. Editor & Text Export", "3. Editor & Textexport"))
        self.tab_davinci = self.tabs.add(self._tr("4. DaVinci Resolve Export", "4. DaVinci-Resolve-Export"))
        self.tab_tts = self.tabs.add(self._tr("5. Voice Export (TTS)", "5. Stimmenexport (TTS)"))

        self.build_source_tab()
        self.build_filter_tab()
        self.build_export_tab()
        self.build_davinci_tab()
        self.build_tts_tab()
        self.bind_all("<c>", self.on_copy_block_shortcut)
        self.bind_all("<C>", self.on_copy_block_shortcut)
        self.bind_all("<Control-Shift-C>", self.on_copy_block_shortcut)
        self.bind_all("<Control-Shift-c>", self.on_copy_block_shortcut)
        self._init_tts_storage()
        self.initial_state = self._capture_current_state()

        self.frame_progress = ctk.CTkFrame(self, fg_color='transparent')
        self.frame_progress.pack(fill='x', padx=20, pady=(0, 20))
        self.lbl_status = ctk.CTkLabel(self.frame_progress, text=self._tr("Ready", "Bereit"), font=('Arial', 12))
        self.lbl_status.pack(anchor='w')
        self.progress = ctk.CTkProgressBar(self.frame_progress)
        self.progress.pack(fill='x', pady=6)
        self.progress.set(0)
        self.apply_ui_language()
        self._apply_tts_availability()

    def _tr(self, en_text, de_text):
        try:
            return de_text if self.ui_lang_var.get() == "DE" else en_text
        except Exception:
            return en_text

    def _is_tts_available(self):
        try:
            if bool(self.ui_settings.get("tts_enabled", True)) is False:
                return False, self._tr("TTS was disabled during install.", "TTS wurde bei der Installation deaktiviert.")
        except Exception:
            pass
        # Keep Tab 5 available when TTS is enabled. Engine/runtime checks are done
        # by "Check local TTS runtime" and at export start, not by a hard startup gate.
        return True, ""

    def _set_widget_state_recursive(self, widget, state):
        try:
            widget.configure(state=state)
        except Exception:
            pass
        try:
            for child in widget.winfo_children():
                self._set_widget_state_recursive(child, state)
        except Exception:
            pass

    def _apply_tts_availability(self):
        if not hasattr(self, "tab_tts"):
            return
        ok, reason = self._is_tts_available()
        if ok:
            if hasattr(self, "lbl_tts_disabled_info"):
                self.lbl_tts_disabled_info.configure(text="")
            if hasattr(self, "tts_main_frame"):
                self._set_widget_state_recursive(self.tts_main_frame, "normal")
            return
        if hasattr(self, "lbl_tts_disabled_info"):
            self.lbl_tts_disabled_info.configure(
                text=self._tr(f"Tab 5 disabled: {reason}", f"Tab 5 deaktiviert: {reason}"),
                text_color="orange"
            )
        if hasattr(self, "tts_main_frame"):
            self._set_widget_state_recursive(self.tts_main_frame, "disabled")
        self.lbl_status.configure(text=reason, text_color="orange")

    def on_ui_language_changed(self, value):
        lang = str(value or "EN").strip().upper()
        if lang not in {"EN", "DE"}:
            lang = "EN"
        self.ui_lang_var.set(lang)
        self.ui_settings["ui_language"] = lang
        self._save_ui_settings()
        self.apply_ui_language()

    def _apply_tab_titles(self):
        pairs = [
            ("1. Source & Whisper", "1. Quelle & Whisper"),
            ("2. Filter & Replace", "2. Filter & Ersetzen"),
            ("3. Editor & Text Export", "3. Editor & Textexport"),
            ("4. DaVinci Resolve Export", "4. DaVinci-Resolve-Export"),
            ("5. Voice Export (TTS)", "5. Stimmenexport (TTS)"),
        ]
        try:
            tv = self.tabs
            names = list(tv._name_list)
        except Exception:
            return
        for i, (en, de) in enumerate(pairs):
            want = self._tr(en, de)
            if i >= len(names):
                break
            cur = names[i]
            if cur == want:
                continue
            try:
                tv.rename(cur, want)
            except Exception:
                continue
            try:
                names = list(tv._name_list)
            except Exception:
                break

    def apply_ui_language(self):
        self.title(self._tr("Smart Transcript & DaVinci Cutter (XTTS v2)", "Smart Transkript & DaVinci Cutter (XTTS v2)"))
        self._apply_tab_titles()
        if hasattr(self, "drop_zone"):
            self.drop_zone.configure(text=self._tr("📁 Drop video here\n(Drag & Drop)", "📁 Video hier ablegen\n(Drag & Drop)"))
        if hasattr(self, "chk_cut"):
            self.chk_cut.configure(
                text=self._tr(
                    "Capture timestamps for video export (recommended)",
                    "Zeitstempel fuer Videoexport erfassen (empfohlen)"
                )
            )
        if hasattr(self, "lbl_cut_hint"):
            self.lbl_cut_hint.configure(
                text=self._tr(
                    "Keep this ON for DaVinci/FFmpeg export. OFF = text only.",
                    "Wenn du DaVinci/FFmpeg Export nutzen willst: eingeschaltet lassen. (AUS = nur Transkript, keine Cut/Beep-Bereiche.)"
                )
            )
        if hasattr(self, "lbl_whisper_note"):
            self.lbl_whisper_note.configure(
                text=self._tr(
                    "Whisper note: bigger model = better text, but slower.",
                    "Hinweis: groesseres Whisper-Modell = besserer Text, aber langsamer."
                )
            )
        if hasattr(self, "lbl_device"):
            self.lbl_device.configure(text=self._tr("Device:", "Geraet:"))
        if hasattr(self, "lbl_chunk_words"):
            self.lbl_chunk_words.configure(text=self._tr("Chunk size (words):", "Chunk-Groesse (Woerter):"))
        if hasattr(self, "lbl_chunk_chars"):
            self.lbl_chunk_chars.configure(text=self._tr("Max chars per block:", "Max. Zeichen pro Block:"))
        if hasattr(self, "lbl_chunk_hint"):
            self.lbl_chunk_hint.configure(
                text=self._tr(
                    "Set 0 to disable a limit. Example: chars=0, words=500 -> word limit only.",
                    "0 = kein Limit. Beispiel: Zeichen=0, Woerter=500 -> nur Wortlimit."
                )
            )
        if hasattr(self, "chk_auto_punct"):
            self.chk_auto_punct.configure(
                text=self._tr("Auto punctuation fallback", "Automatische Satzzeichen (Fallback)")
            )
        if hasattr(self, "lbl_auto_punct_hint"):
            self.lbl_auto_punct_hint.configure(
                text=self._tr(
                    "If text has little punctuation, add basic punctuation automatically.",
                    "Wenn kaum Satzzeichen vorkommen, werden einfache Zeichen ergaenzt."
                )
            )
        if hasattr(self, "chk_auto_chunk"):
            self.chk_auto_chunk.configure(
                text=self._tr(
                    "Split transcript into sections after transcription (off = plain text only)",
                    "Nach Transkription in Blocke teilen (aus = nur Fliesstext)"
                )
            )
        if hasattr(self, "lbl_audio_preprocess"):
            self.lbl_audio_preprocess.configure(text=self._tr("Audio preprocessing:", "Audio-Vorverarbeitung:"))
        if hasattr(self, "lbl_audio_preprocess_hint"):
            self.lbl_audio_preprocess_hint.configure(
                text=self._tr(
                    "voice_clean: balanced, speech_boost: stronger voice focus, music_heavy_cleanup: aggressive bg-music reduction.",
                    "voice_clean: ausgewogen, speech_boost: staerkere Sprachbetonung, music_heavy_cleanup: aggressiver bei Hintergrundmusik."
                )
            )
        if hasattr(self, "btn_transcribe"):
            self.btn_transcribe.configure(text=self._tr("▶ Start transcription", "▶ Transkription starten"))
        if hasattr(self, "btn_stop_transcribe"):
            self.btn_stop_transcribe.configure(text=self._tr("Stop", "Stopp"))
        if hasattr(self, "lbl_whisper_model"):
            self.lbl_whisper_model.configure(text=self._tr("Whisper model:", "Whisper-Modell:"))
        if hasattr(self, "lbl_source_language"):
            self.lbl_source_language.configure(text=self._tr("Language:", "Sprache:"))
        if hasattr(self, "lbl_filter_preset"):
            self.lbl_filter_preset.configure(text=self._tr("Filter preset:", "Filter-Preset:"))
        if hasattr(self, "btn_apply_preset"):
            self.btn_apply_preset.configure(text=self._tr("Apply preset", "Preset anwenden"))
        if hasattr(self, "btn_save_preset"):
            self.btn_save_preset.configure(text=self._tr("Save current as preset", "Aktuelles als Preset speichern"))
        if hasattr(self, "btn_delete_preset"):
            self.btn_delete_preset.configure(text=self._tr("Delete preset", "Preset loeschen"))
        if hasattr(self, "lbl_filter_delete"):
            self.lbl_filter_delete.configure(
                text=self._tr("Delete words/phrases (comma-separated):", "Woerter/Phrasen loeschen (Komma-getrennt):")
            )
        if hasattr(self, "lbl_filter_replace"):
            self.lbl_filter_replace.configure(
                text=self._tr("Replace (format old:new, comma-separated):", "Ersetzen (Format alt:neu, Komma-getrennt):")
            )
        if hasattr(self, "chk_cleanup_text"):
            self.chk_cleanup_text.configure(
                text=self._tr(
                    "Auto-clean punctuation and spacing after filtering",
                    "Nach Filter: Zeichensetzung und Abstaende bereinigen"
                )
            )
        if hasattr(self, "btn_apply_filter"):
            self.btn_apply_filter.configure(text=self._tr("Apply filter", "Filter anwenden"))
        if hasattr(self, "btn_undo_last"):
            self.btn_undo_last.configure(text=self._tr("Undo last change", "Letzte Aenderung rueckgaengig"))
        if hasattr(self, "btn_redo_last"):
            self.btn_redo_last.configure(text=self._tr("Redo", "Wiederholen"))
        if hasattr(self, "btn_reset_all"):
            self.btn_reset_all.configure(text=self._tr("Reset all changes", "Alle Aenderungen zuruecksetzen"))
        if hasattr(self, "lbl_translate_heading"):
            self.lbl_translate_heading.configure(
                text=self._tr("Translate current editor text:", "Aktuellen Editor-Text uebersetzen:")
            )
        if hasattr(self, "lbl_translate_action"):
            self.lbl_translate_action.configure(text=self._tr("Action:", "Aktion:"))
        if hasattr(self, "btn_translate_swap"):
            self.btn_translate_swap.configure(text=self._tr("Swap", "Tauschen"))
        if hasattr(self, "btn_translate_run"):
            self.btn_translate_run.configure(text=self._tr("Run", "Start"))
        if hasattr(self, "lbl_translate_hint"):
            self.lbl_translate_hint.configure(
                text=self._tr(
                    "Uses Google Translate backend. Keeps block style.",
                    "Nutzt Google Translate. Blockformat bleibt erhalten."
                )
            )
        if hasattr(self, "btn_import_text"):
            self.btn_import_text.configure(text=self._tr("Import TXT", "TXT importieren"))
        if hasattr(self, "btn_clear_editor"):
            self.btn_clear_editor.configure(text=self._tr("Clear Editor", "Editor leeren"))
        if hasattr(self, "btn_export_clean"):
            self.btn_export_clean.configure(text=self._tr("Save TXT (No Headers)", "TXT speichern (ohne Koepfe)"))
        if hasattr(self, "btn_export"):
            self.btn_export.configure(text=self._tr("Save TXT", "TXT speichern"))
        if hasattr(self, "btn_copy_block"):
            self.btn_copy_block.configure(
                text=self._tr("Copy Block (Cursor/Next)  C", "Block kopieren (Cursor/Naechster)  C")
            )
        if hasattr(self, "lbl_davinci_desc"):
            self.lbl_davinci_desc.configure(
                text=self._tr(
                    "Send video to DaVinci and remove words deleted in Tab 2.",
                    "Exportiert das Video ohne die in Tab 2 geloeschten Woerter direkt nach DaVinci Resolve."
                )
            )
        if hasattr(self, "lbl_davinci_file_hint"):
            self.lbl_davinci_file_hint.configure(
                text=self._tr(
                    "Uses the same file as Tab 1 (drag & drop). Temp WAV is not used in Resolve.",
                    "Gleiche Datei wie Tab 1 (Drag & Drop). Temp-WAV wird in Resolve nicht genutzt."
                )
            )
        if hasattr(self, "lbl_engine"):
            self.lbl_engine.configure(text=self._tr("Engine:", "Engine:"))
        if hasattr(self, "lbl_export_action"):
            self.lbl_export_action.configure(text=self._tr("Action:", "Aktion:"))
        if hasattr(self, "lbl_tone_freq"):
            self.lbl_tone_freq.configure(text=self._tr("Tone frequency (Hz):", "Ton-Frequenz (Hz):"))
        if hasattr(self, "lbl_tone_freq_hint"):
            self.lbl_tone_freq_hint.configure(
                text=self._tr(
                    "Lower Hz is deeper, higher Hz is sharper. 900 Hz is a good middle value.",
                    "Niedrigere Hz = tiefer, hoehere Hz = schaerfer. 900 Hz ist ein guter Mittelwert."
                )
            )
        if hasattr(self, "lbl_beep_level"):
            self.lbl_beep_level.configure(text=self._tr("Beep level:", "Beep-Lautstaerke:"))
        if hasattr(self, "lbl_beep_hint"):
            self.lbl_beep_hint.configure(
                text=self._tr(
                    "Loudness of the sine beep in replaced segments (FFmpeg → replace with tone only). 0% ≈ off.",
                    "Lautstaerke des Sinus-Beeps in ersetzten Segmenten (nur FFmpeg „Ton ersetzen“). 0% ≈ aus."
                )
            )
        if hasattr(self, "lbl_min_segment"):
            self.lbl_min_segment.configure(text=self._tr("Min segment duration (sec):", "Min. Segmentlaenge (s):"))
        if hasattr(self, "lbl_min_segment_hint"):
            self.lbl_min_segment_hint.configure(
                text=self._tr(
                    "Shorter segments are ignored to avoid choppy edits. 0.20s is a good default.",
                    "Kuerzere Segmente werden ignoriert (weniger Ruckeln). 0,20 s ist ein guter Standard."
                )
            )
        if hasattr(self, "chk_export_srt"):
            self.chk_export_srt.configure(
                text=self._tr("Export subtitles (.srt) with video export", "Untertitel (.srt) beim Videoexport mit ausgeben")
            )
        if hasattr(self, "chk_embed_srt_ffmpeg"):
            self.chk_embed_srt_ffmpeg.configure(
                text=self._tr("FFmpeg: embed SRT into MP4", "FFmpeg: SRT in MP4 einbetten")
            )
        if hasattr(self, "chk_embed_srt_davinci"):
            self.chk_embed_srt_davinci.configure(
                text=self._tr("DaVinci: after render embed SRT into MP4", "DaVinci: nach Render SRT in MP4 einbetten")
            )
        if hasattr(self, "lbl_srt_lang"):
            self.lbl_srt_lang.configure(text=self._tr("SRT lang:", "SRT-Sprache:"))
        if hasattr(self, "lbl_srt_max_words"):
            self.lbl_srt_max_words.configure(text=self._tr("Max words:", "Max. Woerter:"))
        if hasattr(self, "chk_srt_apply_replace"):
            self.chk_srt_apply_replace.configure(
                text=self._tr("Apply Tab 2 replace rules to SRT", "Tab-2-Ersetzungen auf SRT anwenden")
            )
        if hasattr(self, "chk_davinci_timeline_only"):
            self.chk_davinci_timeline_only.configure(
                text=self._tr("DaVinci: create timeline only (skip render)", "DaVinci: nur Timeline anlegen (ohne Render)")
            )
        if hasattr(self, "lbl_davinci_api_path"):
            self.lbl_davinci_api_path.configure(
                text=self._tr("DaVinci API path (optional):", "DaVinci-API-Pfad (optional):"),
            )
        if hasattr(self, "entry_davinci_api_path"):
            self.entry_davinci_api_path.configure(
                placeholder_text=self._tr(
                    "Optional — path to DaVinciResolveScript.py if not on PATH",
                    "Optional — Pfad zu DaVinciResolveScript.py falls nicht im PATH",
                )
            )
        if hasattr(self, "btn_davinci_api_browse"):
            self.btn_davinci_api_browse.configure(
                text=self._tr("Browse...", "Durchsuchen..."),
            )
        if hasattr(self, "lbl_render_preset"):
            self.lbl_render_preset.configure(text=self._tr("Render preset:", "Render-Preset:"))
        if hasattr(self, "btn_save_davinci_preset"):
            self.btn_save_davinci_preset.configure(text=self._tr("Save", "Speichern"))
        if hasattr(self, "btn_delete_davinci_preset"):
            self.btn_delete_davinci_preset.configure(text=self._tr("Delete", "Loeschen"))
        if hasattr(self, "lbl_davinci_preset_tip"):
            self.lbl_davinci_preset_tip.configure(
                text=self._tr(
                    "Tip: Type a preset name once, click Save, then pick it from the dropdown next time.",
                    "Tipp: Preset-Namen einmal eintragen, Speichern, dann beim naechsten Mal aus der Liste waehlen."
                )
            )
        if hasattr(self, "btn_davinci"):
            self.btn_davinci.configure(text=self._tr("Start Video Export", "Videoexport starten"))
        if hasattr(self, "export_engine_var"):
            eng = (self.export_engine_var.get() or "").strip().lower()
            if hasattr(self, "lbl_engine_hint"):
                if eng == "davinci":
                    self.lbl_engine_hint.configure(
                        text=self._tr(
                            "Replace options are available with FFmpeg only.",
                            "Ersetzen-Optionen sind nur mit FFmpeg verfuegbar."
                        )
                    )
                else:
                    self.lbl_engine_hint.configure(text="")
        if hasattr(self, "lbl_status") and self.lbl_status.cget("text").strip() in {"Ready", "Bereit"}:
            self.lbl_status.configure(text=self._tr("Ready", "Bereit"))
        if hasattr(self, "btn_tts_check"):
            self.btn_tts_check.configure(
                text=self._tr("Check local TTS runtime", "Lokale TTS-Laufzeit pruefen")
            )
        if hasattr(self, "tts_env_entry"):
            self.tts_env_entry.configure(
                placeholder_text=self._tr("Conda env name", "Conda-Umgebungsname")
            )
        if hasattr(self, "tts_py_entry"):
            self.tts_py_entry.configure(
                placeholder_text=self._tr(
                    "Full python.exe path (or relative to app folder)",
                    "Voller Pfad zu python.exe (oder relativ zum App-Ordner)",
                )
            )
        if hasattr(self, "btn_tts_ref_browse"):
            self.btn_tts_ref_browse.configure(text=self._tr("Browse...", "Durchsuchen..."))
        if hasattr(self, "tts_drop_zone"):
            cur = self.tts_drop_zone.cget("text") or ""
            if "Reference loaded" not in cur and "Referenz" not in cur and "✅" not in cur:
                self.tts_drop_zone.configure(
                    text=self._tr(
                        "Drop reference media here\n(audio/video)",
                        "Referenz-Medien hier ablegen\n(Audio/Video)"
                    )
                )
        if hasattr(self, "btn_tts_save_profile"):
            self.btn_tts_save_profile.configure(text=self._tr("Save profile", "Profil speichern"))
        if hasattr(self, "chk_tts_multi_ref"):
            self.chk_tts_multi_ref.configure(
                text=self._tr("Multi-reference (optional)", "Multi-Referenz (optional)")
            )
        if hasattr(self, "btn_tts_multi_add"):
            self.btn_tts_multi_add.configure(text=self._tr("Add files", "Dateien hinzufuegen"))
        if hasattr(self, "btn_tts_multi_clear"):
            self.btn_tts_multi_clear.configure(text=self._tr("Clear list", "Liste leeren"))
        if hasattr(self, "btn_tts_multi_build"):
            self.btn_tts_multi_build.configure(text=self._tr("Build model", "Modell bauen"))
        if hasattr(self, "chk_tts_multi_quality"):
            self.chk_tts_multi_quality.configure(
                text=self._tr("Quality picker (cleanest segments)", "Qualitaetsauswahl (sauberste Segmente)")
            )
        if hasattr(self, "btn_tts_reload_profiles"):
            self.btn_tts_reload_profiles.configure(text=self._tr("Reload", "Neu laden"))
        if hasattr(self, "btn_tts_delete_profile"):
            self.btn_tts_delete_profile.configure(text=self._tr("Delete profile", "Profil loeschen"))
        if hasattr(self, "chk_tts_advanced"):
            self.chk_tts_advanced.configure(text=self._tr("Advanced controls", "Erweiterte Optionen"))
        if hasattr(self, "chk_tts_expert"):
            self.chk_tts_expert.configure(text=self._tr("Expert tuning", "Experten-Feineinstellung"))
        if hasattr(self, "btn_tts_export"):
            self.btn_tts_export.configure(
                text=self._tr("Export MP3 (local voice)", "MP3 exportieren (lokale Stimme)")
            )
        if hasattr(self, "btn_tts_cancel"):
            self.btn_tts_cancel.configure(text=self._tr("Cancel TTS", "TTS abbrechen"))
        if hasattr(self, "lbl_tts_intro1"):
            self.lbl_tts_intro1.configure(
                text=self._tr(
                    "Generate MP3 voice output locally (no API).",
                    "MP3-Stimmausgabe lokal erzeugen (ohne API).",
                )
            )
        if hasattr(self, "lbl_tts_intro2"):
            self.lbl_tts_intro2.configure(
                text=self._tr(
                    "Use a short reference clip, save a named voice profile by language, then export MP3.",
                    "Kurzes Referenz-Audio nutzen, Stimmprofil nach Sprache speichern, dann MP3 exportieren.",
                )
            )
        if hasattr(self, "lbl_tts_voice_engine_fixed"):
            self.lbl_tts_voice_engine_fixed.configure(
                text=self._tr(
                    "Voice engine: Coqui XTTS v2 only (fixed in this build; multilingual, e.g. DE/EN).",
                    "Stimmen-Engine: Nur Coqui XTTS v2 (in dieser fest eingestellt; mehrsprachig, z.B. DE/EN).",
                )
            )
        self._update_tts_engine_hint()

    # --- TAB 1: SOURCE ---
    def build_source_tab(self):
        src_outer = ctk.CTkScrollableFrame(self.tab_source, fg_color='transparent')
        src_outer.pack(fill='both', expand=True)
        src = ctk.CTkFrame(src_outer, fg_color='transparent', width=980)
        src.pack(anchor='n', pady=(0, 4))

        self.drop_zone = ctk.CTkLabel(
            src,
            text=self._tr("📁 Drop video here\n(Drag & Drop)", "📁 Video hier ablegen\n(Drag & Drop)"),
            corner_radius=10,
            fg_color='#2a2d2e',
            font=('Arial', 14)
        )
        self.drop_zone.pack(fill='x', padx=10, pady=20, ipady=40)
        self.drop_zone.drop_target_register(DND_FILES)
        self.drop_zone.dnd_bind('<<Drop>>', self.on_drop)

        cut_frame = ctk.CTkFrame(src, fg_color="#1f2a33", corner_radius=10)
        cut_frame.pack(fill="x", padx=10, pady=(0, 10))
        self.cut_var = ctk.IntVar(value=1)
        self.chk_cut = ctk.CTkCheckBox(
            cut_frame,
            text="Capture timestamps for video export (recommended)",
            variable=self.cut_var,
            onvalue=1,
            offvalue=0,
        )
        self.chk_cut.pack(anchor="w", padx=12, pady=(10, 2))
        self.lbl_cut_hint = ctk.CTkLabel(
            cut_frame,
            text=self._tr(
                "Keep this ON for DaVinci/FFmpeg export. OFF = text only.",
                "Wenn du DaVinci/FFmpeg Export nutzen willst: eingeschaltet lassen. (AUS = nur Transkript, keine Cut/Beep-Bereiche.)"
            ),
            text_color="gray70",
            anchor="w",
        )
        self.lbl_cut_hint.pack(fill="x", padx=12, pady=(0, 10))

        self.lbl_whisper_note = ctk.CTkLabel(
            src,
            text=self._tr(
                "Whisper note: bigger model = better text, but slower.",
                "Hinweis: groesseres Whisper-Modell = besserer Text, aber langsamer."
            ),
            text_color="gray70",
            anchor="w"
        )
        self.lbl_whisper_note.pack(fill='x', padx=10, pady=(0, 6))

        options_frame = ctk.CTkFrame(src, fg_color='transparent')
        options_frame.pack(fill='x', padx=10, pady=(0, 10))

        self.lbl_whisper_model = ctk.CTkLabel(options_frame, text=self._tr("Whisper model:", "Whisper Modell:"))
        self.lbl_whisper_model.pack(side='left', padx=(0, 8))
        self.model_var = ctk.StringVar(value="large-v3")
        self.model_menu = ctk.CTkOptionMenu(
            options_frame,
            variable=self.model_var,
            values=["tiny", "base", "small", "medium", "large-v3"]
        )
        self.model_menu.pack(side='left', padx=(0, 18))

        self.lbl_source_language = ctk.CTkLabel(options_frame, text=self._tr("Language:", "Sprache:"))
        self.lbl_source_language.pack(side='left', padx=(0, 8))
        self.language_var = ctk.StringVar(value="auto")
        self.language_menu = ctk.CTkOptionMenu(
            options_frame,
            variable=self.language_var,
            values=LANGUAGE_CODES
        )
        self.language_menu.pack(side='left', padx=(0, 18))

        self.lbl_device = ctk.CTkLabel(options_frame, text=self._tr("Device:", "Geraet:"))
        self.lbl_device.pack(side='left', padx=(0, 8))
        self.device_var = ctk.StringVar(value="auto")
        self.device_menu = ctk.CTkOptionMenu(
            options_frame,
            variable=self.device_var,
            values=["auto", "cpu", "cuda"],
            command=lambda _v: self.refresh_whisper_runtime_info()
        )
        self.device_menu.pack(side='left')
        self.lbl_runtime_info = ctk.CTkLabel(src, text="", text_color="gray70", anchor="w")
        self.lbl_runtime_info.pack(fill="x", padx=10, pady=(0, 8))
        self.refresh_whisper_runtime_info()

        chunk_frame = ctk.CTkFrame(src, fg_color='transparent')
        chunk_frame.pack(fill='x', padx=10, pady=(0, 10))
        self.lbl_chunk_words = ctk.CTkLabel(chunk_frame, text=self._tr("Chunk size (words):", "Chunk-Groesse (Woerter):"))
        self.lbl_chunk_words.pack(side='left', padx=(0, 8))
        self.chunk_size_var = ctk.StringVar(value="0")
        self.entry_chunk_size = ctk.CTkEntry(chunk_frame, textvariable=self.chunk_size_var, width=110)
        self.entry_chunk_size.pack(side='left', padx=(0, 10))
        self.lbl_chunk_chars = ctk.CTkLabel(chunk_frame, text=self._tr("Max chars per block:", "Max. Zeichen pro Block:"))
        self.lbl_chunk_chars.pack(side='left', padx=(0, 8))
        self.chunk_char_limit_var = ctk.StringVar(value="500")
        self.entry_chunk_char_limit = ctk.CTkEntry(chunk_frame, textvariable=self.chunk_char_limit_var, width=110)
        self.entry_chunk_char_limit.pack(side='left', padx=(0, 10))
        self.lbl_chunk_hint = ctk.CTkLabel(
            chunk_frame,
            text=self._tr(
                "Set 0 to disable a limit. Example: chars=0, words=500 -> word limit only.",
                "0 = kein Limit. Beispiel: Zeichen=0, Woerter=500 -> nur Wortlimit."
            ),
            text_color="gray70"
        )
        self.lbl_chunk_hint.pack(side='left')

        punctuation_frame = ctk.CTkFrame(src, fg_color='transparent')
        punctuation_frame.pack(fill='x', padx=10, pady=(0, 10))
        self.auto_punct_var = ctk.StringVar(value="1")
        self.chk_auto_punct = ctk.CTkCheckBox(
            punctuation_frame,
            text="Auto punctuation fallback",
            variable=self.auto_punct_var,
            onvalue="1",
            offvalue="0"
        )
        self.chk_auto_punct.pack(side='left', padx=(0, 10))
        self.lbl_auto_punct_hint = ctk.CTkLabel(
            punctuation_frame,
            text=self._tr(
                "If text has little punctuation, add basic punctuation automatically.",
                "Wenn kaum Satzzeichen vorkommen, werden einfache Zeichen ergaenzt."
            ),
            text_color="gray70"
        )
        self.lbl_auto_punct_hint.pack(side='left')

        auto_chunk_frame = ctk.CTkFrame(src, fg_color='transparent')
        auto_chunk_frame.pack(fill='x', padx=10, pady=(0, 10))
        self.auto_chunk_var = ctk.StringVar(value="1")
        self.chk_auto_chunk = ctk.CTkCheckBox(
            auto_chunk_frame,
            text="Split transcript into sections after transcription (off = plain text only)",
            variable=self.auto_chunk_var,
            onvalue="1",
            offvalue="0"
        )
        self.chk_auto_chunk.pack(side='left')

        preprocess_frame = ctk.CTkFrame(src, fg_color='transparent')
        preprocess_frame.pack(fill='x', padx=10, pady=(0, 10))
        self.lbl_audio_preprocess = ctk.CTkLabel(
            preprocess_frame, text=self._tr("Audio preprocessing:", "Audio-Vorverarbeitung:")
        )
        self.lbl_audio_preprocess.pack(side='left', padx=(0, 8))
        self.audio_preprocess_var = ctk.StringVar(value="off")
        self.audio_preprocess_menu = ctk.CTkOptionMenu(
            preprocess_frame,
            variable=self.audio_preprocess_var,
            values=["off", "voice_clean", "speech_boost", "music_heavy_cleanup"]
        )
        self.audio_preprocess_menu.pack(side='left', padx=(0, 10))
        self.lbl_audio_preprocess_hint = ctk.CTkLabel(
            preprocess_frame,
            text=self._tr(
                "voice_clean: balanced, speech_boost: stronger voice focus, music_heavy_cleanup: aggressive bg-music reduction.",
                "voice_clean: ausgewogen, speech_boost: staerkere Sprachbetonung, music_heavy_cleanup: aggressiver bei Hintergrundmusik."
            ),
            text_color="gray70"
        )
        self.lbl_audio_preprocess_hint.pack(side='left')

        self.transcription_cancel_requested = False
        action_row = ctk.CTkFrame(src, fg_color="transparent")
        action_row.pack(fill="x", padx=10, pady=20)
        self.btn_transcribe = ctk.CTkButton(
            action_row,
            text="▶ Start transcription",
            height=42,
            fg_color="#4b0082",
            hover_color="#300052",
            command=self.start_transkription,
        )
        self.btn_transcribe.pack(side="left", fill="x", expand=True)
        self.btn_stop_transcribe = ctk.CTkButton(
            action_row,
            text="Stop",
            height=42,
            width=110,
            fg_color="#b02a37",
            hover_color="#8a202a",
            command=self.stop_transcription,
            state="disabled",
        )
        self.btn_stop_transcribe.pack(side="left", padx=(10, 0))

    def stop_transcription(self):
        if not getattr(self, "transcription_running", False):
            return
        self.transcription_cancel_requested = True
        try:
            self.btn_stop_transcribe.configure(state="disabled")
        except Exception:
            pass
        self.lbl_status.configure(
            text="Stopping requested… (will cancel as soon as the current step finishes)",
            text_color="yellow",
        )

    def _resolve_transcription_device(self):
        selected = (self.device_var.get().strip().lower() if hasattr(self, "device_var") else "auto")
        if selected == "auto":
            return "cuda" if torch.cuda.is_available() else "cpu"
        return selected

    def refresh_whisper_runtime_info(self):
        if not hasattr(self, "lbl_runtime_info"):
            return
        try:
            torch_version = getattr(torch, "__version__", "unknown")
            cuda_available = bool(torch.cuda.is_available())
            cuda_build = getattr(torch.version, "cuda", None)
            gpu_name = ""
            if cuda_available:
                try:
                    gpu_name = torch.cuda.get_device_name(0)
                except Exception:
                    gpu_name = "GPU detected"
            selected = (self.device_var.get().strip().lower() if hasattr(self, "device_var") else "auto")
            resolved = self._resolve_transcription_device()
            parts = [
                f"Whisper runtime: Python {sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
                f"torch {torch_version}",
                f"device={selected}->{resolved}",
                f"cuda_available={cuda_available}",
            ]
            if cuda_build:
                parts.append(f"torch_cuda={cuda_build}")
            if gpu_name:
                parts.append(f"gpu={gpu_name}")
            self.lbl_runtime_info.configure(text=" | ".join(parts))
        except Exception:
            self.lbl_runtime_info.configure(text="Whisper runtime info unavailable.")

    def on_drop(self, event):
        try:
            paths = self.winfo_toplevel().tk.splitlist(event.data)
        except Exception:
            paths = []
        if not paths:
            raw = (event.data or "").strip().strip("{}")
            paths = [raw] if raw else []
        path = os.path.normpath(paths[0]) if paths else ""
        if not path:
            return
        self.video_path = path
        self.last_imported_clip = None
        self.drop_zone.configure(
            text=f"{self._tr('✅ Loaded:', '✅ Geladen:')}\n{os.path.basename(path)}",
            fg_color='#1f538d'
        )
        ext = os.path.splitext(path)[1].lower()
        if ext in {".mp3", ".wav", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}:
            self.lbl_status.configure(
                text=self._tr(
                    "Source loaded (audio only). Transcription works, but DaVinci video export needs e.g. mp4/mov.",
                    "Quelle geladen (nur Audio). Transkription: OK — DaVinci-Videoexport braucht z. B. mp4/mov."
                ),
                text_color="yellow",
            )
        else:
            self.lbl_status.configure(
                text=self._tr("Source loaded. Ready for transcription.", "Quelle geladen. Bereit zur Transkription."),
                text_color="white"
            )
        self.refresh_whisper_runtime_info()

    # --- TAB 2: FILTER ---
    def build_filter_tab(self):
        scroll = ctk.CTkScrollableFrame(self.tab_filter, fg_color='transparent')
        scroll.pack(fill='both', expand=True, padx=10, pady=10)
        frame = ctk.CTkFrame(scroll, fg_color='transparent', width=1080)
        frame.pack(anchor='n', pady=(0, 4))

        presets_frame = ctk.CTkFrame(frame, fg_color='transparent')
        presets_frame.pack(fill='x', padx=10, pady=(8, 2))
        self.lbl_filter_preset = ctk.CTkLabel(presets_frame, text=self._tr("Filter preset:", "Filter-Preset:"), anchor='w')
        self.lbl_filter_preset.pack(side='left', padx=(0, 8))
        self.preset_var = ctk.StringVar(value="")
        self.preset_menu = ctk.CTkOptionMenu(presets_frame, variable=self.preset_var, values=[], width=220)
        self.preset_menu.pack(side='left', padx=(0, 8))
        self.btn_apply_preset = ctk.CTkButton(presets_frame, text="Apply preset", command=self.apply_selected_preset, width=102)
        self.btn_apply_preset.pack(side='left')

        preset_actions_frame = ctk.CTkFrame(frame, fg_color='transparent')
        preset_actions_frame.pack(fill='x', padx=10, pady=(0, 6))
        self.btn_save_preset = ctk.CTkButton(
            preset_actions_frame,
            text="Save current as preset",
            command=self.save_current_as_preset,
            width=154
        )
        self.btn_save_preset.pack(side='left', padx=(0, 8))
        self.btn_delete_preset = ctk.CTkButton(preset_actions_frame, text="Delete preset", command=self.delete_selected_preset, width=102)
        self.btn_delete_preset.pack(side='left')

        self.lbl_filter_delete = ctk.CTkLabel(
            frame,
            text=self._tr("Delete words/phrases (comma-separated):", "Woerter/Phrasen loeschen (Komma-getrennt):"),
            anchor='w'
        )
        self.lbl_filter_delete.pack(fill='x', padx=10, pady=(10, 0))
        self.entry_loeschen = ctk.CTkTextbox(frame, height=80)
        self.entry_loeschen.insert("0.0", "ähm, ah, also")
        self.entry_loeschen.pack(fill='x', padx=10, pady=5)

        self.lbl_filter_replace = ctk.CTkLabel(
            frame,
            text=self._tr("Replace (format old:new, comma-separated):", "Ersetzen (Format alt:neu, Komma-getrennt):"),
            anchor='w'
        )
        self.lbl_filter_replace.pack(fill='x', padx=10, pady=(10, 0))
        self.entry_ersetzen = ctk.CTkTextbox(frame, height=80)
        self.entry_ersetzen.pack(fill='x', padx=10, pady=5)

        cleanup_frame = ctk.CTkFrame(frame, fg_color='transparent')
        cleanup_frame.pack(fill='x', padx=10, pady=(4, 0))
        self.cleanup_text_var = ctk.StringVar(value="1")
        self.chk_cleanup_text = ctk.CTkCheckBox(
            cleanup_frame,
            text="Auto-clean punctuation and spacing after filtering",
            variable=self.cleanup_text_var,
            onvalue="1",
            offvalue="0"
        )
        self.chk_cleanup_text.pack(side='left')

        self.btn_apply_filter = ctk.CTkButton(frame, text='Apply filter', command=self.text_filtern)
        self.btn_apply_filter.pack(pady=(20, 8))
        undo_frame = ctk.CTkFrame(frame, fg_color='transparent')
        undo_frame.pack(fill='x', padx=10, pady=(0, 10))
        self.btn_undo_last = ctk.CTkButton(
            undo_frame,
            text="Undo last change",
            command=self.undo_last_change,
            width=140
        )
        self.btn_undo_last.pack(side='left', padx=(0, 8))
        self.btn_redo_last = ctk.CTkButton(
            undo_frame,
            text="Redo",
            command=self.redo_last_change,
            width=90
        )
        self.btn_redo_last.pack(side='left', padx=(0, 8))
        self.btn_reset_all = ctk.CTkButton(
            undo_frame,
            text="Reset all changes",
            command=self.reset_all_changes,
            width=150
        )
        self.btn_reset_all.pack(side='left')
        self._load_filter_presets()

    # --- TAB 3: TEXT EXPORT ---
    def build_export_tab(self):
        self.txt_editor = ctk.CTkTextbox(self.tab_export, wrap="word")
        self.txt_editor.pack(fill='both', expand=True, padx=10, pady=10)

        translate_frame = ctk.CTkFrame(self.tab_export)
        translate_frame.pack(fill='x', padx=10, pady=(0, 8))
        self.lbl_translate_heading = ctk.CTkLabel(
            translate_frame,
            text=self._tr("Translate current editor text:", "Aktuellen Editor-Text uebersetzen:")
        )
        self.lbl_translate_heading.pack(side='left', padx=(10, 8), pady=8)
        self.translate_source_var = ctk.StringVar(value="en")
        self.translate_target_var = ctk.StringVar(value="de")
        self.translate_source_menu = ctk.CTkOptionMenu(translate_frame, variable=self.translate_source_var, values=LANGUAGE_CODES, width=90)
        self.translate_source_menu.pack(side='left', padx=(0, 6))
        ctk.CTkLabel(translate_frame, text="->").pack(side='left', padx=(0, 6))
        self.translate_target_menu = ctk.CTkOptionMenu(
            translate_frame,
            variable=self.translate_target_var,
            values=[c for c in LANGUAGE_CODES if c != "auto"],
            width=90
        )
        self.translate_target_menu.pack(side='left', padx=(0, 8))
        self.btn_translate_swap = ctk.CTkButton(
            translate_frame,
            text="Swap",
            width=56,
            command=self.swap_translate_languages
        )
        self.btn_translate_swap.pack(side='left', padx=(0, 10))
        self.lbl_translate_action = ctk.CTkLabel(translate_frame, text=self._tr("Action:", "Aktion:"))
        self.lbl_translate_action.pack(side='left', padx=(6, 6))
        translate_actions = [
            "Translate + Replace",
            "Translate + Save TXT",
            "Translate + Save TXT (No Headers)"
        ]
        last_action = (self.ui_settings.get("translate_action") or "Translate + Replace").strip()
        if last_action not in translate_actions:
            last_action = "Translate + Replace"
        self.translate_action_var = ctk.StringVar(value=last_action)
        self.translate_action_menu = ctk.CTkOptionMenu(
            translate_frame,
            variable=self.translate_action_var,
            values=translate_actions,
            command=self.on_translate_action_changed,
            width=230
        )
        self.translate_action_menu.pack(side='left', padx=(0, 6))
        self.btn_translate_run = ctk.CTkButton(
            translate_frame,
            text="Run",
            command=self.start_translate_from_action,
            width=62
        )
        self.btn_translate_run.pack(side='left', padx=(0, 6))
        self.lbl_translate_hint = ctk.CTkLabel(
            translate_frame,
            text=self._tr(
                "Uses Google Translate backend. Keeps block style.",
                "Nutzt Google Translate. Blockformat bleibt erhalten."
            ),
            text_color="gray70"
        )
        self.lbl_translate_hint.pack(side='left', padx=(10, 0))

        quick_actions_frame = ctk.CTkFrame(self.tab_export, fg_color='transparent')
        quick_actions_frame.pack(fill='x', padx=10, pady=(0, 8))
        self.btn_translate_replace = self.btn_translate_run
        self.btn_translate_save = self.btn_translate_run
        self.btn_translate_save_clean = self.btn_translate_run

        self.btn_import_text = ctk.CTkButton(
            quick_actions_frame,
            text='Import TXT',
            command=self.import_text_into_editor,
            width=86
        )
        self.btn_import_text.pack(side='left')
        self.btn_clear_editor = ctk.CTkButton(
            quick_actions_frame,
            text='Clear Editor',
            command=self.clear_editor_text,
            width=92
        )
        self.btn_clear_editor.pack(side='left', padx=(8, 0))

        self.btn_export_clean = ctk.CTkButton(
            quick_actions_frame,
            text='Save TXT (No Headers)',
            command=self.export_text_clean,
            width=146
        )
        self.btn_export_clean.pack(side='left', padx=(8, 0))

        self.btn_export = ctk.CTkButton(
            quick_actions_frame,
            text='Save TXT',
            command=self.export_text,
            width=78
        )
        self.btn_export.pack(side='left', padx=(8, 0))

        copy_block_frame = ctk.CTkFrame(self.tab_export, fg_color='transparent')
        copy_block_frame.pack(fill='x', padx=10, pady=(0, 10))
        self.btn_copy_block = ctk.CTkButton(
            copy_block_frame,
            text="Copy Block (Cursor/Next)  C",
            command=self.copy_block_from_editor,
            width=196
        )
        self.btn_copy_block.pack(side='left')

    # --- TAB 4: DAVINCI EXPORT ---
    def build_davinci_tab(self):
        outer = ctk.CTkScrollableFrame(self.tab_davinci, fg_color='transparent')
        outer.pack(fill='both', expand=True, padx=10, pady=10)
        frame = ctk.CTkFrame(outer, fg_color='transparent', width=980)
        frame.pack(anchor='n', pady=(0, 4))
        
        self.lbl_davinci_desc = ctk.CTkLabel(
            frame,
            text=self._tr(
                "Send video to DaVinci and remove words deleted in Tab 2.",
                "Exportiert das Video ohne die in Tab 2 geloeschten Woerter direkt nach DaVinci Resolve."
            ),
            wraplength=400
        )
        self.lbl_davinci_desc.pack(pady=10)
        self.lbl_davinci_file_hint = ctk.CTkLabel(
            frame,
            text=self._tr(
                "Uses the same file as Tab 1 (drag & drop). Temp WAV is not used in Resolve.",
                "Gleiche Datei wie Tab 1 (Drag & Drop). Temp-WAV wird in Resolve nicht genutzt."
            ),
            text_color="gray70",
            wraplength=420,
        )
        self.lbl_davinci_file_hint.pack(pady=(0, 6))

        options_frame = ctk.CTkFrame(frame, fg_color='transparent')
        options_frame.pack(fill='x', padx=20, pady=(0, 10))
        self.lbl_engine = ctk.CTkLabel(options_frame, text=self._tr("Engine:", "Engine:"))
        self.lbl_engine.pack(side='left', padx=(0, 8))
        self.export_engine_var = ctk.StringVar(value="davinci")
        self.export_engine_menu = ctk.CTkOptionMenu(
            options_frame,
            variable=self.export_engine_var,
            values=["davinci", "ffmpeg"],
            command=self.on_export_engine_changed
        )
        self.export_engine_menu.pack(side='left', padx=(0, 16))

        self.lbl_export_action = ctk.CTkLabel(options_frame, text=self._tr("Action:", "Aktion:"))
        self.lbl_export_action.pack(side='left', padx=(0, 8))
        self.export_action_var = ctk.StringVar(value="cut")
        self.export_action_menu = ctk.CTkOptionMenu(
            options_frame,
            variable=self.export_action_var,
            values=["cut", "replace_with_silence", "replace_with_tone"]
        )
        self.export_action_menu.pack(side='left')
        self.lbl_engine_hint = ctk.CTkLabel(
            options_frame,
            text="",
            text_color="gray70"
        )
        self.lbl_engine_hint.pack(side='left', padx=(12, 0))
        self.on_export_engine_changed(self.export_engine_var.get())

        ffmpeg_frame = ctk.CTkFrame(frame, fg_color='transparent')
        ffmpeg_frame.pack(fill='x', padx=20, pady=(0, 8))
        self.lbl_tone_freq = ctk.CTkLabel(ffmpeg_frame, text=self._tr("Tone frequency (Hz):", "Ton-Frequenz (Hz):"))
        self.lbl_tone_freq.pack(side='left', padx=(0, 8))
        self.tone_freq_var = ctk.StringVar(value="900")
        self.entry_tone_freq = ctk.CTkEntry(ffmpeg_frame, textvariable=self.tone_freq_var, width=100)
        self.entry_tone_freq.pack(side='left', padx=(0, 10))
        self.lbl_tone_freq_hint = ctk.CTkLabel(
            ffmpeg_frame,
            text=self._tr(
                "Lower Hz is deeper, higher Hz is sharper. 900 Hz is a good middle value.",
                "Niedrigere Hz = tiefer, hoehere Hz = schaerfer. 900 Hz ist ein guter Mittelwert."
            ),
            text_color="gray70"
        )
        self.lbl_tone_freq_hint.pack(side='left')

        beep_frame = ctk.CTkFrame(frame, fg_color='transparent')
        beep_frame.pack(fill='x', padx=20, pady=(0, 8))
        beep_row = ctk.CTkFrame(beep_frame, fg_color='transparent')
        beep_row.pack(fill='x')
        self.lbl_beep_level = ctk.CTkLabel(beep_row, text=self._tr("Beep level:", "Beep-Lautstaerke:"))
        self.lbl_beep_level.pack(side='left', padx=(0, 8))
        self.beep_slider = ctk.CTkSlider(beep_row, from_=0, to=100, width=220, number_of_steps=100)
        self.lbl_beep_level_val = ctk.CTkLabel(beep_row, text="35%", width=44)

        def _on_beep_slider(v):
            self.lbl_beep_level_val.configure(text=f"{int(round(float(v)))}%")

        self.beep_slider.configure(command=_on_beep_slider)
        self.beep_slider.pack(side='left', padx=(0, 10), fill='x', expand=True)
        self.lbl_beep_level_val.pack(side='left')
        self.beep_slider.set(35)
        self.lbl_beep_hint = ctk.CTkLabel(
            beep_frame,
            text=self._tr(
                "Loudness of the sine beep in replaced segments (FFmpeg → replace with tone only). 0% ≈ off.",
                "Lautstaerke des Sinus-Beeps in ersetzten Segmenten (nur FFmpeg „Ton ersetzen“). 0% ≈ aus."
            ),
            text_color="gray70",
            anchor="w",
        )
        self.lbl_beep_hint.pack(fill='x', pady=(4, 0))

        segment_frame = ctk.CTkFrame(frame, fg_color='transparent')
        segment_frame.pack(fill='x', padx=20, pady=(0, 8))
        self.lbl_min_segment = ctk.CTkLabel(
            segment_frame, text=self._tr("Min segment duration (sec):", "Min. Segmentlaenge (s):")
        )
        self.lbl_min_segment.pack(side='left', padx=(0, 8))
        self.min_segment_var = ctk.StringVar(value="0.20")
        self.entry_min_segment = ctk.CTkEntry(segment_frame, textvariable=self.min_segment_var, width=100)
        self.entry_min_segment.pack(side='left', padx=(0, 10))
        self.lbl_min_segment_hint = ctk.CTkLabel(
            segment_frame,
            text=self._tr(
                "Shorter segments are ignored to avoid choppy edits. 0.20s is a good default.",
                "Kuerzere Segmente werden ignoriert (weniger Ruckeln). 0,20 s ist ein guter Standard."
            ),
            text_color="gray70"
        )
        self.lbl_min_segment_hint.pack(side='left')

        subtitle_frame = ctk.CTkFrame(frame, fg_color='transparent')
        subtitle_frame.pack(fill='x', padx=20, pady=(0, 8))
        self.export_srt_var = ctk.StringVar(value="0")
        self.chk_export_srt = ctk.CTkCheckBox(
            subtitle_frame,
            text="Export subtitles (.srt) with video export",
            variable=self.export_srt_var,
            onvalue="1",
            offvalue="0",
        )
        self.chk_export_srt.pack(side='left')
        self.embed_srt_ffmpeg_var = ctk.StringVar(value="0")
        self.chk_embed_srt_ffmpeg = ctk.CTkCheckBox(
            subtitle_frame,
            text="FFmpeg: embed SRT into MP4",
            variable=self.embed_srt_ffmpeg_var,
            onvalue="1",
            offvalue="0",
        )
        self.chk_embed_srt_ffmpeg.pack(side='left', padx=(14, 0))
        self.embed_srt_davinci_var = ctk.StringVar(value="0")
        self.chk_embed_srt_davinci = ctk.CTkCheckBox(
            subtitle_frame,
            text="DaVinci: after render embed SRT into MP4",
            variable=self.embed_srt_davinci_var,
            onvalue="1",
            offvalue="0",
        )
        self.chk_embed_srt_davinci.pack(side='left', padx=(14, 0))
        self.lbl_srt_lang = ctk.CTkLabel(subtitle_frame, text=self._tr("SRT lang:", "SRT-Sprache:"))
        self.lbl_srt_lang.pack(side='left', padx=(14, 6))
        self.srt_lang_var = ctk.StringVar(value="de")
        self.entry_srt_lang = ctk.CTkEntry(subtitle_frame, textvariable=self.srt_lang_var, width=54)
        self.entry_srt_lang.pack(side='left')
        self.lbl_srt_max_words = ctk.CTkLabel(subtitle_frame, text=self._tr("Max words:", "Max. Woerter:"))
        self.lbl_srt_max_words.pack(side='left', padx=(12, 6))
        self.srt_max_words_var = ctk.StringVar(value="10")
        self.entry_srt_max_words = ctk.CTkEntry(subtitle_frame, textvariable=self.srt_max_words_var, width=54)
        self.entry_srt_max_words.pack(side='left')
        self.srt_apply_replace_var = ctk.StringVar(value="1")
        self.chk_srt_apply_replace = ctk.CTkCheckBox(
            subtitle_frame,
            text="Apply Tab 2 replace rules to SRT",
            variable=self.srt_apply_replace_var,
            onvalue="1",
            offvalue="0",
        )
        self.chk_srt_apply_replace.pack(side='left', padx=(14, 0))

        render_mode_frame = ctk.CTkFrame(frame, fg_color='transparent')
        render_mode_frame.pack(fill='x', padx=20, pady=(0, 8))
        self.davinci_timeline_only_var = ctk.StringVar(value="0")
        self.chk_davinci_timeline_only = ctk.CTkCheckBox(
            render_mode_frame,
            text="DaVinci: create timeline only (skip render)",
            variable=self.davinci_timeline_only_var,
            onvalue="1",
            offvalue="0",
        )
        self.chk_davinci_timeline_only.pack(side='left')

        api_frame = ctk.CTkFrame(frame, fg_color='transparent')
        api_frame.pack(fill='x', padx=20, pady=(0, 8))
        self.lbl_davinci_api_path = ctk.CTkLabel(
            api_frame,
            text=self._tr("DaVinci API path (optional):", "DaVinci-API-Pfad (optional):"),
            text_color="gray60",
            anchor="w",
        )
        self.lbl_davinci_api_path.pack(side='left', padx=(0, 8))
        self.davinci_api_path_var = ctk.StringVar(value=str(self.ui_settings.get("davinci_api_path", "")).strip())
        self.entry_davinci_api_path = ctk.CTkEntry(
            api_frame,
            textvariable=self.davinci_api_path_var,
            width=430,
            placeholder_text=self._tr(
                "Optional — path to DaVinciResolveScript.py if not on PATH",
                "Optional — Pfad zu DaVinciResolveScript.py falls nicht im PATH",
            ),
            fg_color="#2a2d30",
            border_color="#45494e",
            text_color="gray72",
            placeholder_text_color="gray52",
        )
        self.entry_davinci_api_path.pack(side='left', padx=(0, 8))
        self.btn_davinci_api_browse = ctk.CTkButton(
            api_frame,
            text=self._tr("Browse...", "Durchsuchen..."),
            width=82,
            command=self.browse_davinci_api_path
        )
        self.btn_davinci_api_browse.pack(side='left')

        preset_frame = ctk.CTkFrame(frame, fg_color="transparent")
        preset_frame.pack(fill="x", padx=20, pady=(8, 8))
        self.lbl_render_preset = ctk.CTkLabel(preset_frame, text=self._tr("Render preset:", "Render-Preset:"))
        self.lbl_render_preset.pack(side="left", padx=(0, 8))

        history = self._get_davinci_preset_history()
        default_preset = history[0] if history else "(none)"
        self.davinci_preset_choice_var = ctk.StringVar(value=default_preset)
        self.davinci_preset_menu = ctk.CTkOptionMenu(
            preset_frame,
            variable=self.davinci_preset_choice_var,
            values=(history if history else ["(none)"]),
            command=self.on_davinci_preset_selected,
            width=190,
        )
        self.davinci_preset_menu.pack(side="left", padx=(0, 8))

        self.davinci_preset_name_var = ctk.StringVar(value=(history[0] if history else ""))
        self.entry_preset = ctk.CTkEntry(
            preset_frame,
            textvariable=self.davinci_preset_name_var,
            width=210,
        )
        self.entry_preset.pack(side="left", padx=(0, 8))

        self.btn_save_davinci_preset = ctk.CTkButton(
            preset_frame, text="Save", width=64, command=self.save_davinci_preset_name
        )
        self.btn_save_davinci_preset.pack(side="left", padx=(0, 6))
        self.btn_delete_davinci_preset = ctk.CTkButton(
            preset_frame, text="Delete", width=74, command=self.delete_davinci_preset_name
        )
        self.btn_delete_davinci_preset.pack(side="left")

        self.lbl_davinci_preset_tip = ctk.CTkLabel(
            frame,
            text=self._tr(
                "Tip: Type a preset name once, click Save, then pick it from the dropdown next time.",
                "Tipp: Preset-Namen einmal eintragen, Speichern, dann beim naechsten Mal aus der Liste waehlen."
            ),
            text_color="gray70",
            wraplength=520,
            anchor="w",
        )
        self.lbl_davinci_preset_tip.pack(fill="x", padx=20, pady=(0, 6))

        self.btn_davinci = ctk.CTkButton(
            frame,
            text="Start Video Export",
            height=42,
            fg_color="#4b0082",
            hover_color="#300052",
            command=self.start_davinci_export,
        )
        self.btn_davinci.pack(pady=16)

    # --- TAB 5: VOICE EXPORT (TTS) ---
    def build_tts_tab(self):
        outer = ctk.CTkFrame(self.tab_tts)
        outer.pack(fill='both', expand=True, padx=10, pady=10)
        scroll = ctk.CTkScrollableFrame(outer)
        scroll.pack(fill='both', expand=True)
        frame = ctk.CTkFrame(scroll, fg_color='transparent', width=980)
        frame.pack(anchor='n', pady=(0, 4))
        self.tts_main_frame = frame
        self.lbl_tts_disabled_info = ctk.CTkLabel(frame, text="", text_color="orange", anchor="w")
        self.lbl_tts_disabled_info.pack(fill='x', padx=10, pady=(6, 2))

        self.lbl_tts_intro1 = ctk.CTkLabel(
            frame,
            text=self._tr(
                "Generate MP3 voice output locally (no API).",
                "MP3-Stimmausgabe lokal erzeugen (ohne API).",
            ),
            text_color="gray70",
            anchor="w",
        )
        self.lbl_tts_intro1.pack(fill='x', padx=10, pady=(10, 4))
        self.lbl_tts_intro2 = ctk.CTkLabel(
            frame,
            text=self._tr(
                "Use a short reference clip, save a named voice profile by language, then export MP3.",
                "Kurzes Referenz-Audio nutzen, Stimmprofil nach Sprache speichern, dann MP3 exportieren.",
            ),
            text_color="gray70",
            anchor="w",
        )
        self.lbl_tts_intro2.pack(fill='x', padx=10, pady=(0, 12))

        engine_block = ctk.CTkFrame(frame, fg_color='transparent')
        engine_block.pack(fill='x', padx=10, pady=(0, 10))
        row_eng = ctk.CTkFrame(engine_block, fg_color='transparent')
        row_eng.pack(fill='x')
        self.tts_engine_var = ctk.StringVar(value=TTS_ENGINE_XTTS_V2)
        try:
            self.ui_settings["tts_engine"] = TTS_ENGINE_XTTS_V2
            self.ui_settings.pop("openvoice_ckpt_dir", None)
            self._save_ui_settings()
        except Exception:
            pass
        self.lbl_tts_voice_engine_fixed = ctk.CTkLabel(
            row_eng,
            text=self._tr(
                "Voice engine: Coqui XTTS v2 only (fixed in this build; multilingual, e.g. DE/EN).",
                "Stimmen-Engine: Nur Coqui XTTS v2 (in dieser fest eingestellt; mehrsprachig, z.B. DE/EN).",
            ),
            text_color="gray80",
            anchor="w",
            justify="left",
        )
        self.lbl_tts_voice_engine_fixed.pack(side='left', fill='x', expand=True)
        self.lbl_tts_engine_hint = ctk.CTkLabel(
            engine_block,
            text="",
            text_color="gray70",
            anchor="w",
            justify="left",
            wraplength=900,
        )
        self.lbl_tts_engine_hint.pack(fill='x', pady=(6, 0))
        self._update_tts_engine_hint()

        ctk.CTkLabel(frame, text="Runtime", font=('Arial', 14, 'bold'), anchor='w').pack(fill='x', padx=10, pady=(2, 6))
        runtime_top = ctk.CTkFrame(frame, fg_color='transparent')
        runtime_top.pack(fill='x', padx=10, pady=(0, 8))
        runtime_left = ctk.CTkFrame(runtime_top, fg_color='transparent')
        runtime_left.pack(side='left', fill='x', expand=True)
        runtime_right = ctk.CTkFrame(runtime_top, fg_color='transparent')
        runtime_right.pack(side='left', padx=(12, 0), anchor='n')

        check_frame = ctk.CTkFrame(runtime_left, fg_color='transparent')
        check_frame.pack(fill='x', pady=(0, 8))
        self.btn_tts_check = ctk.CTkButton(check_frame, text="Check local TTS runtime", command=self.check_local_tts_setup, width=164)
        self.btn_tts_check.pack(side='left', padx=(0, 10))
        self.lbl_tts_check = ctk.CTkLabel(check_frame, text="Not checked yet.", text_color="gray70")
        self.lbl_tts_check.pack(side='left')

        runtime_frame = ctk.CTkFrame(runtime_left, fg_color='transparent')
        runtime_frame.pack(fill='x', pady=(0, 8))
        ctk.CTkLabel(runtime_frame, text="TTS runtime:").pack(side='left', padx=(0, 8))
        runtime_default = str(self.ui_settings.get("tts_runtime_mode", "conda_env")).strip().lower()
        if runtime_default not in {"conda_env", "current_python", "python_path"}:
            runtime_default = "conda_env"
        self.tts_runtime_var = ctk.StringVar(value=runtime_default)
        self.tts_runtime_menu = ctk.CTkOptionMenu(
            runtime_frame,
            variable=self.tts_runtime_var,
            values=["conda_env", "current_python", "python_path"],
            command=self.on_tts_runtime_changed,
            width=130
        )
        self.tts_runtime_menu.pack(side='left', padx=(0, 8))
        self.tts_env_entry = ctk.CTkEntry(runtime_frame, width=160, placeholder_text="Conda env name")
        self.tts_env_entry.pack(side='left')
        env_default = str(self.ui_settings.get("tts_conda_env", "")).strip()
        if env_default:
            self.tts_env_entry.insert(0, env_default)
        python_path_frame = ctk.CTkFrame(runtime_left, fg_color='transparent')
        python_path_frame.pack(fill='x', pady=(0, 2))
        ctk.CTkLabel(python_path_frame, text="Python path (optional):").pack(side='left', padx=(0, 8))
        self.tts_py_entry = ctk.CTkEntry(
            python_path_frame,
            width=260,
            placeholder_text=self._tr(
                "Full python.exe path (or relative to app folder)",
                "Voller Pfad zu python.exe (oder relativ zum App-Ordner)",
            ),
        )
        self.tts_py_entry.pack(side='left')
        py_default = str(self.ui_settings.get("tts_python_path", "")).strip()
        if py_default:
            self.tts_py_entry.insert(0, py_default)

        drop_wrap = ctk.CTkFrame(runtime_right, fg_color='transparent', width=280)
        drop_wrap.pack(anchor='w')
        drop_wrap.pack_propagate(False)

        self.tts_drop_zone = ctk.CTkLabel(
            drop_wrap,
            text="Drop reference media here\n(audio/video)",
            corner_radius=10,
            fg_color='#2a2d2e',
            font=('Arial', 12),
            width=280,
            height=86
        )
        self.tts_drop_zone.pack(anchor='w')
        self.tts_drop_zone.drop_target_register(DND_FILES)
        self.tts_drop_zone.dnd_bind('<<Drop>>', self.on_tts_reference_drop)
        self.btn_tts_ref_browse = ctk.CTkButton(drop_wrap, text="Browse...", command=self.browse_tts_reference, width=100)
        self.btn_tts_ref_browse.pack(anchor='center', pady=(8, 0))
        self.on_tts_runtime_changed(self.tts_runtime_var.get())
        self.tts_env_entry.bind("<FocusOut>", lambda _e: self._save_tts_runtime_settings())
        self.tts_py_entry.bind("<FocusOut>", self._on_tts_py_path_focus_out)

        ctk.CTkLabel(frame, text="Model / Profile", font=('Arial', 14, 'bold'), anchor='w').pack(fill='x', padx=10, pady=(8, 6))
        profile_frame = ctk.CTkFrame(frame, fg_color='transparent')
        profile_frame.pack(fill='x', padx=10, pady=(0, 8))
        ctk.CTkLabel(profile_frame, text="Language:").pack(side='left', padx=(0, 8))
        self.tts_language_var = ctk.StringVar(value="de")
        self.tts_language_menu = ctk.CTkOptionMenu(
            profile_frame,
            variable=self.tts_language_var,
            values=[c for c in LANGUAGE_CODES if c != "auto"],
            command=self.on_tts_language_changed,
            width=90
        )
        self.tts_language_menu.pack(side='left', padx=(0, 12))
        ctk.CTkLabel(profile_frame, text="Profile name:").pack(side='left', padx=(0, 8))
        self.tts_profile_name_entry = ctk.CTkEntry(profile_frame, placeholder_text="e.g. MyVoice_DE", width=260)
        self.tts_profile_name_entry.pack(side='left', padx=(0, 8))
        self.btn_tts_save_profile = ctk.CTkButton(profile_frame, text="Save profile", command=self.save_tts_profile, width=96)
        self.btn_tts_save_profile.pack(side='left')

        multi_ref_toggle_frame = ctk.CTkFrame(frame, fg_color='transparent')
        multi_ref_toggle_frame.pack(fill='x', padx=10, pady=(0, 4))
        self.tts_multi_ref_var = ctk.StringVar(value="0")
        self.chk_tts_multi_ref = ctk.CTkCheckBox(
            multi_ref_toggle_frame,
            text="Multi-reference (optional)",
            variable=self.tts_multi_ref_var,
            onvalue="1",
            offvalue="0",
            command=self.on_tts_multi_reference_toggle_changed
        )
        self.chk_tts_multi_ref.pack(side='left')
        ctk.CTkLabel(
            multi_ref_toggle_frame,
            text="Combine multiple clips for a more stable voice profile.",
            text_color="gray70"
        ).pack(side='left', padx=(10, 0))

        self.tts_multi_ref_frame = ctk.CTkFrame(frame, fg_color='transparent', width=776)
        self.tts_multi_ref_frame.pack_propagate(False)
        multi_ref_buttons = ctk.CTkFrame(self.tts_multi_ref_frame, fg_color='transparent')
        multi_ref_buttons.pack(fill='x', padx=8, pady=(8, 6))
        self.btn_tts_multi_add = ctk.CTkButton(
            multi_ref_buttons,
            text="Add files",
            command=self.add_tts_multi_reference_files,
            width=78
        )
        self.btn_tts_multi_add.pack(side='left')
        self.btn_tts_multi_clear = ctk.CTkButton(
            multi_ref_buttons,
            text="Clear list",
            command=self.clear_tts_multi_reference_files,
            width=78
        )
        self.btn_tts_multi_clear.pack(side='left', padx=(6, 0))
        self.btn_tts_multi_build = ctk.CTkButton(
            multi_ref_buttons,
            text=self._tr("Build model", "Modell bauen"),
            command=self.build_tts_multi_reference_preview,
            width=136
        )
        self.btn_tts_multi_build.pack(side='left', padx=(6, 0))
        self.tts_multi_ref_quality_var = ctk.StringVar(value="1")
        self.chk_tts_multi_quality = ctk.CTkCheckBox(
            multi_ref_buttons,
            text="Quality picker (cleanest segments)",
            variable=self.tts_multi_ref_quality_var,
            onvalue="1",
            offvalue="0"
        )
        self.chk_tts_multi_quality.pack(side='left', padx=(10, 0))
        self.tts_multi_ref_list = ctk.CTkTextbox(self.tts_multi_ref_frame, height=84, width=760)
        self.tts_multi_ref_list.pack(anchor='w', padx=8, pady=(0, 8))
        self.tts_multi_ref_list.insert("end", "No multi-reference files added.")
        self.tts_multi_ref_list.configure(state="disabled")
        self.on_tts_multi_reference_toggle_changed()

        model_frame = ctk.CTkFrame(frame, fg_color='transparent')
        model_frame.pack(fill='x', padx=10, pady=(0, 8))
        ctk.CTkLabel(model_frame, text="Saved profile:").pack(side='left', padx=(0, 8))
        self.tts_profile_var = ctk.StringVar(value="")
        self.tts_profile_menu = ctk.CTkOptionMenu(
            model_frame,
            variable=self.tts_profile_var,
            values=["(none)"],
            command=self.on_tts_profile_changed,
            width=240,
        )
        self.tts_profile_menu.pack(side='left', padx=(0, 8))
        self.btn_tts_reload_profiles = ctk.CTkButton(model_frame, text="Reload", command=self.reload_tts_profiles, width=72)
        self.btn_tts_reload_profiles.pack(side='left')
        self.btn_tts_delete_profile = ctk.CTkButton(model_frame, text="Delete profile", command=self.delete_tts_profile, width=96)
        self.btn_tts_delete_profile.pack(side='left', padx=(8, 0))
        self.lbl_tts_profile_hint = ctk.CTkLabel(
            frame,
            text="",
            text_color="gray70",
            anchor="w",
            justify="left",
            wraplength=900,
        )
        self.lbl_tts_profile_hint.pack(fill='x', padx=10, pady=(0, 6))

        preprocess_frame = ctk.CTkFrame(frame, fg_color='transparent')
        preprocess_frame.pack(fill='x', padx=10, pady=(0, 8))
        ctk.CTkLabel(preprocess_frame, text="Creation preset:").pack(side='left', padx=(0, 8))
        self.tts_creation_preset_var = ctk.StringVar(value=TTS_CREATION_PRESETS["balanced_default"]["label"])
        self.tts_creation_preset_menu = ctk.CTkOptionMenu(
            preprocess_frame,
            variable=self.tts_creation_preset_var,
            values=[x["label"] for x in TTS_CREATION_PRESETS.values()],
            command=self.on_tts_creation_preset_changed,
            width=170
        )
        self.tts_creation_preset_menu.pack(side='left', padx=(0, 8))
        ctk.CTkLabel(preprocess_frame, text="Reference preprocess:").pack(side='left', padx=(0, 8))
        self.tts_preprocess_var = ctk.StringVar(value="off")
        self.tts_preprocess_menu = ctk.CTkOptionMenu(
            preprocess_frame,
            variable=self.tts_preprocess_var,
            values=["off", "voice_clean", "speech_boost", "music_heavy_cleanup"]
        )
        self.tts_preprocess_menu.pack(side='left', padx=(0, 8))
        self.lbl_tts_preset_info = ctk.CTkLabel(preprocess_frame, text="", text_color="gray70")
        self.lbl_tts_preset_info.pack(side='left')

        ctk.CTkLabel(frame, text="Export / Creation", font=('Arial', 14, 'bold'), anchor='w').pack(fill='x', padx=10, pady=(8, 6))
        preset_frame = ctk.CTkFrame(frame, fg_color='transparent')
        preset_frame.pack(fill='x', padx=10, pady=(0, 8))
        ctk.CTkLabel(preset_frame, text="Voice result preset:").pack(side='left', padx=(0, 8))
        self.tts_result_preset_var = ctk.StringVar(value=TTS_RESULT_PRESETS["clear_narration"]["label"])
        self.tts_result_preset_menu = ctk.CTkOptionMenu(
            preset_frame,
            variable=self.tts_result_preset_var,
            values=[x["label"] for x in TTS_RESULT_PRESETS.values()],
            command=self.on_tts_result_preset_changed,
            width=170
        )
        self.tts_result_preset_menu.pack(side='left', padx=(0, 8))
        self.lbl_tts_result_preset_info = ctk.CTkLabel(preset_frame, text="", text_color="gray70")
        self.lbl_tts_result_preset_info.pack(side='left')

        basic_source_frame = ctk.CTkFrame(frame, fg_color='transparent')
        basic_source_frame.pack(fill='x', padx=10, pady=(0, 8))
        ctk.CTkLabel(basic_source_frame, text="Text source:").pack(side='left', padx=(0, 8))
        self.tts_source_var = ctk.StringVar(value="editor")
        self.tts_source_menu = ctk.CTkOptionMenu(
            basic_source_frame,
            variable=self.tts_source_var,
            values=["editor", "clean_text"],
            command=self.on_tts_live_setting_changed
        )
        self.tts_source_menu.pack(side='left')
        self.tts_advanced_var = ctk.StringVar(value="0")
        self.chk_tts_advanced = ctk.CTkCheckBox(
            basic_source_frame,
            text="Advanced controls",
            variable=self.tts_advanced_var,
            onvalue="1",
            offvalue="0",
            command=self.on_tts_advanced_toggle_changed
        )
        self.chk_tts_advanced.pack(side='left', padx=(14, 0))
        self.tts_expert_var = ctk.StringVar(value="0")
        self.chk_tts_expert = ctk.CTkCheckBox(
            basic_source_frame,
            text="Expert tuning",
            variable=self.tts_expert_var,
            onvalue="1",
            offvalue="0",
            command=self.on_tts_advanced_toggle_changed
        )
        self.chk_tts_expert.pack(side='left', padx=(10, 0))

        self.tts_style_frame = ctk.CTkFrame(frame, fg_color='transparent')
        self.tts_style_frame.pack(fill='x', padx=10, pady=(0, 8))
        ctk.CTkLabel(self.tts_style_frame, text="Output style:").pack(side='left', padx=(0, 8))
        self.tts_output_style_var = ctk.StringVar(value="natural")
        self.tts_output_style_menu = ctk.CTkOptionMenu(
            self.tts_style_frame,
            variable=self.tts_output_style_var,
            values=["natural", "clear_speech"],
            command=self.on_tts_live_setting_changed
        )
        self.tts_output_style_menu.pack(side='left', padx=(0, 8))
        ctk.CTkLabel(self.tts_style_frame, text="Clear strength:").pack(side='left', padx=(0, 8))
        self.tts_clear_strength_var = ctk.StringVar(value="medium")
        self.tts_clear_strength_menu = ctk.CTkOptionMenu(
            self.tts_style_frame,
            variable=self.tts_clear_strength_var,
            values=TTS_CLEAR_SPEECH_STRENGTHS,
            command=self.on_tts_live_setting_changed,
            width=110
        )
        self.tts_clear_strength_menu.pack(side='left', padx=(0, 8))
        ctk.CTkLabel(
            self.tts_style_frame,
            text="clear_speech reduces roomy sound; strong = tighter but more processed.",
            text_color="gray70"
        ).pack(side='left')

        self.tts_delivery_frame = ctk.CTkFrame(frame, fg_color='transparent')
        self.tts_delivery_frame.pack(fill='x', padx=10, pady=(0, 8))
        ctk.CTkLabel(self.tts_delivery_frame, text="Delivery:").pack(side='left', padx=(0, 8))
        self.tts_delivery_style_var = ctk.StringVar(value="neutral")
        self.tts_delivery_style_menu = ctk.CTkOptionMenu(
            self.tts_delivery_frame,
            variable=self.tts_delivery_style_var,
            values=TTS_DELIVERY_STYLES,
            command=self.on_tts_live_setting_changed
        )
        self.tts_delivery_style_menu.pack(side='left', padx=(0, 8))
        ctk.CTkLabel(self.tts_delivery_frame, text="Pauses:").pack(side='left', padx=(0, 8))
        self.tts_pause_level_var = ctk.StringVar(value="medium")
        self.tts_pause_level_menu = ctk.CTkOptionMenu(
            self.tts_delivery_frame,
            variable=self.tts_pause_level_var,
            values=TTS_PAUSE_LEVELS,
            command=self.on_tts_live_setting_changed
        )
        self.tts_pause_level_menu.pack(side='left', padx=(0, 8))
        ctk.CTkLabel(self.tts_delivery_frame, text="Control speaking feel and pause amount.", text_color="gray70").pack(side='left')
        ap_saved = bool(self.ui_settings.get("tts_artificial_sentence_pauses", False))
        self.tts_artificial_sentence_pauses_var = ctk.StringVar(value="1" if ap_saved else "0")
        self.chk_tts_artificial_sentence_pauses = ctk.CTkCheckBox(
            self.tts_delivery_frame,
            text=self._tr(
                "Artificial pauses (between sentences inside a chunk, XTTS)",
                "Künstliche Pausen (zwischen Sätzen im Block, XTTS)",
            ),
            variable=self.tts_artificial_sentence_pauses_var,
            onvalue="1",
            offvalue="0",
            command=self._on_tts_artificial_sentence_pauses_changed,
        )
        self.chk_tts_artificial_sentence_pauses.pack(side='left', padx=(14, 0))

        self.tts_chunk_frame = ctk.CTkFrame(frame, fg_color='transparent')
        self.tts_chunk_frame.pack(fill='x', padx=10, pady=(0, 8))
        ctk.CTkLabel(self.tts_chunk_frame, text="Max chars per TTS chunk:").pack(side='left', padx=(0, 8))
        self.tts_chunk_chars_var = ctk.StringVar(value="0")
        self.tts_chunk_chars_entry = ctk.CTkEntry(self.tts_chunk_frame, width=90, textvariable=self.tts_chunk_chars_var)
        self.tts_chunk_chars_entry.pack(side='left', padx=(0, 8))
        self.tts_chunk_chars_entry.bind("<FocusOut>", lambda _e: self.on_tts_live_setting_changed())
        ctk.CTkLabel(self.tts_chunk_frame, text="Breath control:").pack(side='left', padx=(0, 8))
        self.tts_breath_control_var = ctk.StringVar(value="medium")
        self.tts_breath_control_menu = ctk.CTkOptionMenu(
            self.tts_chunk_frame,
            variable=self.tts_breath_control_var,
            values=TTS_BREATH_CONTROL_LEVELS,
            command=self.on_tts_live_setting_changed,
            width=110
        )
        self.tts_breath_control_menu.pack(side='left', padx=(0, 8))
        self.tts_prefer_sentence_chunks_var = ctk.StringVar(value="1")
        self.chk_tts_prefer_sentence_chunks = ctk.CTkCheckBox(
            self.tts_chunk_frame,
            text="Prefer full sentences",
            variable=self.tts_prefer_sentence_chunks_var,
            onvalue="1",
            offvalue="0",
            command=self.on_tts_live_setting_changed
        )
        self.chk_tts_prefer_sentence_chunks.pack(side='left', padx=(0, 8))
        ctk.CTkLabel(
            self.tts_chunk_frame,
            text="0 = auto. If enabled, chunks may exceed max chars slightly to keep sentences intact.",
            text_color="gray70"
        ).pack(side='left')

        details_frame = ctk.CTkFrame(frame, fg_color='transparent', width=776)
        details_frame.pack_propagate(False)
        details_frame.pack(anchor='center', pady=(0, 8))
        ctk.CTkLabel(details_frame, text="Selected profile settings (saved):", anchor='w').pack(fill='x', padx=8, pady=(8, 2))
        self.tts_profile_details = ctk.CTkTextbox(details_frame, height=86, width=760)
        self.tts_profile_details.pack(anchor='w', padx=8, pady=(0, 8))
        self.lbl_tts_current_settings = ctk.CTkLabel(details_frame, text="", text_color="gray70", anchor='w')
        self.lbl_tts_current_settings.pack(fill='x', padx=8, pady=(0, 8))

        self.btn_tts_export = ctk.CTkButton(
            frame,
            text=self._tr("Export MP3 (local voice)", "MP3 exportieren (lokale Stimme)"),
            command=self.start_tts_export,
            fg_color="#4b0082",
            hover_color="#300052",
        )
        self.btn_tts_export.pack(padx=10, pady=(16, 6), anchor='w')
        self.btn_tts_cancel = ctk.CTkButton(
            frame,
            text="Cancel TTS",
            command=self.cancel_tts_export,
            state="disabled",
            fg_color="#b02a37",
            hover_color="#8a202a"
        )
        self.btn_tts_cancel.pack(padx=10, pady=(0, 10), anchor='w')
        self.on_tts_creation_preset_changed(self.tts_creation_preset_var.get())
        self.on_tts_result_preset_changed(self.tts_result_preset_var.get())
        self.on_tts_advanced_toggle_changed()
        self._refresh_tts_current_settings()

    def _init_tts_storage(self):
        os.makedirs(self.tts_profiles_root, exist_ok=True)
        if os.path.exists(self.tts_profiles_index_path):
            try:
                with open(self.tts_profiles_index_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    self.tts_profiles = loaded
            except Exception:
                self.tts_profiles = {}
        if not isinstance(self.tts_profiles, dict):
            self.tts_profiles = {}
        self.on_tts_language_changed(self.tts_language_var.get())

    def on_tts_runtime_changed(self, runtime_mode):
        mode = (runtime_mode or "conda_env").strip()
        if mode == "conda_env":
            self.tts_env_entry.configure(state="normal")
            self.tts_py_entry.configure(state="disabled")
        elif mode == "python_path":
            self.tts_env_entry.configure(state="disabled")
            self.tts_py_entry.configure(state="normal")
        else:
            self.tts_env_entry.configure(state="disabled")
            self.tts_py_entry.configure(state="disabled")
        self._save_tts_runtime_settings()

    def _save_tts_runtime_settings(self):
        try:
            mode = (self.tts_runtime_var.get() or "conda_env").strip()
            env_name = (self.tts_env_entry.get() or "").strip() if hasattr(self, "tts_env_entry") else ""
            py_path = (self.tts_py_entry.get() or "").strip() if hasattr(self, "tts_py_entry") else ""
            if mode == "python_path" and py_path:
                py_path = self._normalize_tts_python_path(py_path)
            self.ui_settings["tts_runtime_mode"] = mode
            self.ui_settings["tts_conda_env"] = env_name
            self.ui_settings["tts_python_path"] = py_path
            self._save_ui_settings()
        except Exception:
            pass

    def _on_tts_py_path_focus_out(self, _e=None):
        if hasattr(self, "tts_py_entry"):
            raw = (self.tts_py_entry.get() or "").strip()
            if raw:
                n = self._normalize_tts_python_path(raw)
                if n and n != raw and os.path.isfile(n):
                    self.tts_py_entry.delete(0, "end")
                    self.tts_py_entry.insert(0, n)
        self._save_tts_runtime_settings()

    def _normalize_tts_python_path(self, raw: str) -> str:
        """Accept full python.exe path or path relative to this app directory (or cwd)."""
        p = (raw or "").strip().strip('"')
        if not p:
            return ""
        p = p.replace("/", os.sep)
        p = os.path.expandvars(os.path.expanduser(p))
        if os.path.isabs(p):
            return os.path.normpath(os.path.abspath(p))
        app_dir = os.path.dirname(os.path.abspath(__file__))
        cand = os.path.normpath(os.path.join(app_dir, p))
        if os.path.isfile(cand):
            return os.path.abspath(cand)
        cand2 = os.path.normpath(os.path.join(os.getcwd(), p))
        if os.path.isfile(cand2):
            return os.path.abspath(cand2)
        return os.path.abspath(cand)

    def _update_tts_engine_hint(self) -> None:
        """Short hint for XTTS-only Tab 5 (language selection lives below)."""
        if not hasattr(self, "lbl_tts_engine_hint"):
            return
        self.lbl_tts_engine_hint.configure(
            text=self._tr(
                "Tip: set the profile / tab language (e.g. de) to match your text so XTTS uses the right language code.",
                "Tipp: Profil- bzw. Tab-Sprache (z.B. de) passend zum Text waehlen, damit XTTS den richtigen Sprachcode nutzt.",
            ),
            text_color="gray70",
        )

    def on_tts_engine_changed(self, value=None):
        """No engine switch in XTTS-only build; keep settings aligned."""
        try:
            self.tts_engine_var.set(TTS_ENGINE_XTTS_V2)
            self.ui_settings["tts_engine"] = TTS_ENGINE_XTTS_V2
            self._save_ui_settings()
            self._update_tts_engine_hint()
        except Exception:
            pass

    def _resolve_conda_executable(self):
        # 1) Environment variable from activated shells
        conda_exe = (os.environ.get("CONDA_EXE") or "").strip()
        if conda_exe and os.path.exists(conda_exe):
            return conda_exe

        # 2) PATH lookup
        path_conda = shutil.which("conda")
        if path_conda:
            return path_conda

        # 3) Typical Windows installation locations
        home = os.path.expanduser("~")
        candidates = [
            os.path.join(home, "miniconda3", "Scripts", "conda.exe"),
            os.path.join(home, "anaconda3", "Scripts", "conda.exe"),
            os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "miniconda3", "Scripts", "conda.exe"),
            os.path.join(os.environ.get("ProgramData", r"C:\ProgramData"), "anaconda3", "Scripts", "conda.exe"),
        ]
        for candidate in candidates:
            if os.path.exists(candidate):
                return candidate

        raise Exception("Conda executable not found. Set runtime to 'python_path' or install/add conda to PATH.")

    def _build_tts_python_command(self):
        mode = (self.tts_runtime_var.get() or "conda_env").strip().lower() if hasattr(self, "tts_runtime_var") else "conda_env"
        if mode == "current_python":
            return [sys.executable]
        if mode == "python_path":
            py_path = (self.tts_py_entry.get() or "").strip()
            if not py_path:
                py_path = self._default_tts_python_path_from_installer_hint()
                if py_path and hasattr(self, "tts_py_entry"):
                    try:
                        self.tts_py_entry.delete(0, "end")
                        self.tts_py_entry.insert(0, py_path)
                        self.ui_settings["tts_python_path"] = py_path
                        self._save_ui_settings()
                    except Exception:
                        pass
            if not py_path:
                raise Exception(
                    self._tr(
                        "Please set a python.exe path for TTS export (Tab 5) or run install.bat again.",
                        "Bitte einen python.exe Pfad fuer den TTS Export setzen (Tab 5) oder install.bat erneut ausfuehren.",
                    )
                )
            raw_path = py_path
            py_path = self._normalize_tts_python_path(py_path)
            if py_path and hasattr(self, "tts_py_entry") and py_path != raw_path:
                try:
                    self.tts_py_entry.delete(0, "end")
                    self.tts_py_entry.insert(0, py_path)
                    self.ui_settings["tts_python_path"] = py_path
                    self._save_ui_settings()
                except Exception:
                    pass
            if not os.path.isfile(py_path):
                app_dir = os.path.dirname(os.path.abspath(__file__))
                raise Exception(
                    self._tr(
                        f"TTS Python not found: {py_path}\n"
                        f"(Relative paths are resolved from the app folder: {app_dir})",
                        f"TTS Python nicht gefunden: {py_path}\n"
                        f"(Relative Pfade werden vom App-Ordner aus aufgeloest: {app_dir})",
                    )
                )
            return [py_path]
        env_name = (self.tts_env_entry.get() or "").strip() if hasattr(self, "tts_env_entry") else "autocut_env"
        if not env_name:
            raise Exception("Please provide a conda environment name.")
        conda_cmd = self._resolve_conda_executable()
        if not os.path.isfile(conda_cmd):
            raise Exception(
                self._tr(
                    f"Conda executable not found: {conda_cmd}",
                    f"Conda Programm nicht gefunden: {conda_cmd}",
                )
            )
        return [conda_cmd, "run", "-n", env_name, "python"]

    def _default_tts_python_path_from_installer_hint(self):
        """
        install.bat writes .python_for_start_gui.txt with either:
          - full path to python.exe
          - conda:envname
        For TTS subprocess export we only use the python.exe form.
        """
        try:
            hint_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), ".python_for_start_gui.txt")
            if not os.path.isfile(hint_path):
                return ""
            with open(hint_path, "r", encoding="utf-8", errors="ignore") as f:
                raw = (f.read() or "").strip()
            if not raw or raw.lower().startswith("conda:"):
                return ""
            if os.path.isfile(raw):
                return raw
        except Exception:
            return ""
        return ""

    def _resolve_ffmpeg_executable(self):
        if self._ffmpeg_exe_cached is not None:
            return self._ffmpeg_exe_cached
        which = shutil.which("ffmpeg")
        if which and os.path.isfile(which):
            self._ffmpeg_exe_cached = which
            return which
        pf = os.environ.get("ProgramFiles", r"C:\Program Files")
        pf86 = os.environ.get("ProgramFiles(x86)", r"C:\Program Files (x86)")
        local = os.environ.get("LOCALAPPDATA", "")
        candidates = [
            os.path.join(pf, "ffmpeg", "bin", "ffmpeg.exe"),
            os.path.join(pf86, "ffmpeg", "bin", "ffmpeg.exe"),
            os.path.join(local, "Programs", "ffmpeg", "bin", "ffmpeg.exe") if local else "",
            os.path.join(os.path.expanduser("~"), "ffmpeg", "bin", "ffmpeg.exe"),
            os.path.join(os.path.expanduser("~"), "scoop", "shims", "ffmpeg.exe"),
            os.path.join(os.path.expanduser("~"), "scoop", "apps", "ffmpeg", "current", "bin", "ffmpeg.exe"),
            r"C:\ffmpeg\bin\ffmpeg.exe",
        ]
        for c in candidates:
            if c and os.path.isfile(c):
                self._ffmpeg_exe_cached = c
                return c
        self._ffmpeg_exe_cached = ""
        return ""

    def _ffmpeg_exe(self):
        exe = self._resolve_ffmpeg_executable()
        if not exe:
            raise Exception(
                self._tr(
                    "FFmpeg not found. Install FFmpeg and add it to PATH (or put ffmpeg.exe under Program Files\\ffmpeg\\bin).",
                    "FFmpeg nicht gefunden. Bitte FFmpeg installieren und in PATH legen (oder ffmpeg.exe unter Program Files\\ffmpeg\\bin).",
                )
            )
        return exe

    def _save_tts_index(self):
        os.makedirs(self.tts_profiles_root, exist_ok=True)
        with open(self.tts_profiles_index_path, "w", encoding="utf-8") as f:
            json.dump(self.tts_profiles, f, ensure_ascii=False, indent=2)

    def reload_tts_profiles(self):
        self._init_tts_storage()
        self.lbl_status.configure(text="TTS profiles reloaded.", text_color="lightgreen")

    def delete_tts_profile(self):
        profile_name = (self.tts_profile_var.get() or "").strip()
        if not profile_name or profile_name == "(none)" or profile_name not in self.tts_profiles:
            messagebox.showwarning("No profile", "Select a valid profile to delete.")
            return
        if not messagebox.askyesno("Delete profile", f"Delete TTS profile '{profile_name}'?"):
            return
        meta = self.tts_profiles.pop(profile_name, None)
        try:
            if isinstance(meta, dict):
                ref_wav = meta.get("reference_wav", "")
                if ref_wav and os.path.exists(ref_wav):
                    profile_dir = os.path.dirname(ref_wav)
                    shutil.rmtree(profile_dir, ignore_errors=True)
        except Exception:
            pass
        self._save_tts_index()
        self.on_tts_language_changed(self.tts_language_var.get())
        self.lbl_status.configure(text=f"TTS profile deleted: {profile_name}", text_color="lightgreen")

    def on_tts_reference_drop(self, event):
        path = event.data.strip('{}')
        self._set_tts_reference_path(path)

    def on_tts_multi_reference_toggle_changed(self):
        show = hasattr(self, "tts_multi_ref_var") and self.tts_multi_ref_var.get() == "1"
        if show:
            self.tts_multi_ref_frame.pack(anchor='center', pady=(0, 8))
        else:
            self.tts_multi_ref_frame.pack_forget()

    def browse_tts_reference(self):
        path = filedialog.askopenfilename(
            filetypes=[
                ("Media (audio/video)", "*.wav *.mp3 *.m4a *.flac *.ogg *.mp4 *.mkv *.mov *.webm *.avi"),
                ("Audio", "*.wav *.mp3 *.m4a *.flac *.ogg"),
                ("Video", "*.mp4 *.mkv *.mov *.webm *.avi"),
                ("All files", "*.*")
            ]
        )
        if path:
            self._set_tts_reference_path(path)

    def _set_tts_reference_path(self, path):
        if not path or not os.path.exists(path):
            messagebox.showwarning("Invalid reference", "Selected reference file does not exist.")
            return
        self.tts_selected_reference_path = path
        self.tts_drop_zone.configure(
            text=f"✅ Reference loaded:\n{os.path.basename(path)}",
            fg_color="#1f538d"
        )

    def add_tts_multi_reference_files(self):
        paths = filedialog.askopenfilenames(
            filetypes=[
                ("Media (audio/video)", "*.wav *.mp3 *.m4a *.flac *.ogg *.mp4 *.mkv *.mov *.webm *.avi"),
                ("All files", "*.*")
            ]
        )
        if not paths:
            return
        added = 0
        current = set(self.tts_multi_ref_paths)
        for p in paths:
            if p and os.path.exists(p) and p not in current:
                self.tts_multi_ref_paths.append(p)
                current.add(p)
                added += 1
        self._refresh_tts_multi_reference_list()
        if added > 0:
            self.lbl_status.configure(text=f"Added {added} multi-reference file(s).", text_color="lightgreen")

    def clear_tts_multi_reference_files(self):
        self.tts_multi_ref_paths = []
        self._refresh_tts_multi_reference_list()
        self.lbl_status.configure(text="Multi-reference list cleared.", text_color="white")

    def _refresh_tts_multi_reference_list(self):
        if not hasattr(self, "tts_multi_ref_list"):
            return
        self.tts_multi_ref_list.configure(state="normal")
        self.tts_multi_ref_list.delete("0.0", "end")
        if not self.tts_multi_ref_paths:
            self.tts_multi_ref_list.insert("end", "No multi-reference files added.")
        else:
            lines = []
            for idx, p in enumerate(self.tts_multi_ref_paths, start=1):
                dur = self._get_media_duration_seconds(p)
                dur_text = f"{dur:.1f}s" if dur else "?"
                lines.append(f"{idx:02d}. {os.path.basename(p)} ({dur_text})")
            self.tts_multi_ref_list.insert("end", "\n".join(lines))
        self.tts_multi_ref_list.configure(state="disabled")

    def _build_multi_reference_wav(self, input_paths, output_wav_path, preprocess_mode, use_quality_picker):
        if not input_paths:
            raise ValueError("No multi-reference input files.")
        temp_dir = tempfile.mkdtemp(prefix="tts_multiref_")
        try:
            ff = self._ffmpeg_exe()
            prepared = []
            for i, src in enumerate(input_paths, start=1):
                out_wav = os.path.join(temp_dir, f"ref_{i:03d}.wav")
                self._preprocess_audio_with_mode(src, out_wav, preprocess_mode)
                prepared.append(out_wav)

            if use_quality_picker:
                cleaned = []
                silence_filter = "silenceremove=start_periods=1:start_silence=0.25:start_threshold=-35dB:stop_periods=-1:stop_silence=0.20:stop_threshold=-35dB"
                for i, src_wav in enumerate(prepared, start=1):
                    cleaned_wav = os.path.join(temp_dir, f"clean_{i:03d}.wav")
                    cmd = [ff, "-y", "-i", src_wav, "-af", silence_filter, "-ar", "24000", "-ac", "1", cleaned_wav]
                    run = subprocess.run(cmd, capture_output=True, text=True, check=False)
                    if run.returncode == 0 and os.path.exists(cleaned_wav) and os.path.getsize(cleaned_wav) > 0:
                        cleaned.append(cleaned_wav)
                    else:
                        cleaned.append(src_wav)
                prepared = cleaned

            concat_file = os.path.join(temp_dir, "concat.txt")
            with open(concat_file, "w", encoding="utf-8") as f:
                for wav in prepared:
                    safe = wav.replace("\\", "/")
                    f.write(f"file '{safe}'\n")
            cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", concat_file, "-ar", "24000", "-ac", "1", output_wav_path]
            run = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if run.returncode != 0:
                err = (run.stderr or "FFmpeg concat failed").strip()
                raise Exception(err[-500:])
            if not os.path.exists(output_wav_path) or os.path.getsize(output_wav_path) <= 0:
                raise Exception("Merged reference file was not created.")
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)

    def build_tts_multi_reference_preview(self):
        if not self.tts_multi_ref_paths:
            messagebox.showwarning("No files", "Add at least 2 files for multi-reference preview.")
            return
        if not self._ffmpeg_available():
            messagebox.showwarning("FFmpeg missing", "FFmpeg is required for multi-reference merge.")
            return
        mode = (self.tts_preprocess_var.get() or "off").strip().lower()
        use_quality_picker = self.tts_multi_ref_quality_var.get() == "1" if hasattr(self, "tts_multi_ref_quality_var") else True
        preview_wav = os.path.join(tempfile.gettempdir(), f"tts_multiref_preview_{int(time.time())}.wav")
        try:
            self._build_multi_reference_wav(self.tts_multi_ref_paths, preview_wav, mode, use_quality_picker)
            self._set_tts_reference_path(preview_wav)
            self.lbl_status.configure(text="Multi-reference preview built and selected.", text_color="lightgreen")
        except Exception as e:
            messagebox.showerror("Multi-reference failed", str(e))

    def on_tts_language_changed(self, selected_language):
        lang = (selected_language or "de").strip().lower()
        names = [n for n, meta in self.tts_profiles.items() if isinstance(meta, dict)]
        matched = sorted(
            [
                n
                for n in names
                if str((self.tts_profiles.get(n) or {}).get("language") or "").strip().lower() == lang
            ],
            key=lambda x: x.lower(),
        )
        show_fallback = False
        if matched:
            names = matched
        else:
            names = sorted(names, key=lambda x: x.lower())
            show_fallback = bool(names)
        if not names:
            names = ["(none)"]
        self.tts_profile_menu.configure(values=names, command=self.on_tts_profile_changed)
        current = (self.tts_profile_var.get() or "").strip()
        if current not in names:
            self.tts_profile_var.set(names[0])
        self.on_tts_profile_changed(self.tts_profile_var.get())
        try:
            if show_fallback and hasattr(self, "lbl_tts_profile_hint"):
                extra = self._tr(
                    f"No saved profiles tagged as language '{lang}'. Showing all profiles — pick one that matches '{lang}' or save a new profile under this language.",
                    f"Keine gespeicherten Profile mit Sprache '{lang}'. Zeige alle Profile — bitte eines waehlen, das zu '{lang}' passt, oder neu speichern.",
                )
                existing = (self.lbl_tts_profile_hint.cget("text") or "").strip()
                if existing:
                    self.lbl_tts_profile_hint.configure(text=f"{existing}\n{extra}", text_color="orange")
                else:
                    self.lbl_tts_profile_hint.configure(text=extra, text_color="orange")
        except Exception:
            pass
        self._update_tts_engine_hint()

    def on_tts_creation_preset_changed(self, preset_key):
        key_or_label = (preset_key or TTS_CREATION_PRESETS["balanced_default"]["label"]).strip()
        key = "balanced_default"
        if key_or_label in TTS_CREATION_PRESETS:
            key = key_or_label
        else:
            for k, v in TTS_CREATION_PRESETS.items():
                if v.get("label") == key_or_label:
                    key = k
                    break
        preset = TTS_CREATION_PRESETS.get(key, TTS_CREATION_PRESETS["balanced_default"])
        self.tts_creation_preset_var.set(preset["label"])
        self.tts_preprocess_var.set(preset["preprocess"])
        self.lbl_tts_preset_info.configure(text=f"{preset['label']}: {preset['description']}")
        self._refresh_tts_current_settings()

    def on_tts_result_preset_changed(self, preset_key):
        key_or_label = (preset_key or TTS_RESULT_PRESETS["clear_narration"]["label"]).strip()
        key = "clear_narration"
        if key_or_label in TTS_RESULT_PRESETS:
            key = key_or_label
        else:
            for k, v in TTS_RESULT_PRESETS.items():
                if v.get("label") == key_or_label:
                    key = k
                    break
        preset = TTS_RESULT_PRESETS.get(key, TTS_RESULT_PRESETS["clear_narration"])
        self.tts_result_preset_var.set(preset["label"])
        self.tts_output_style_var.set(preset["output_style"])
        clear_strength = (preset.get("clear_strength") or "medium").strip().lower()
        self.tts_clear_strength_var.set(clear_strength if clear_strength in TTS_CLEAR_SPEECH_STRENGTHS else "medium")
        breath_control = (preset.get("breath_control") or "medium").strip().lower()
        self.tts_breath_control_var.set(breath_control if breath_control in TTS_BREATH_CONTROL_LEVELS else "medium")
        self.tts_delivery_style_var.set(preset["delivery_style"])
        self.tts_pause_level_var.set(preset["pause_level"])
        self.tts_chunk_chars_var.set(str(int(preset.get("chunk_chars", 0))) if str(preset.get("chunk_chars", 0)).strip().isdigit() else "0")
        self.tts_prefer_sentence_chunks_var.set("1" if bool(preset.get("prefer_full_sentences", True)) else "0")
        self.lbl_tts_result_preset_info.configure(text=f"{preset['label']}: {preset['description']}")
        self._refresh_tts_current_settings()

    def on_tts_advanced_toggle_changed(self):
        show = self.tts_advanced_var.get() == "1"
        show_expert = show and self.tts_expert_var.get() == "1"
        if show:
            self.tts_style_frame.pack(fill='x', padx=10, pady=(0, 8))
            self.tts_delivery_frame.pack(fill='x', padx=10, pady=(0, 8))
        else:
            self.tts_style_frame.pack_forget()
            self.tts_delivery_frame.pack_forget()
        if show_expert:
            self.tts_chunk_frame.pack(fill='x', padx=10, pady=(0, 8))
        else:
            self.tts_chunk_frame.pack_forget()

    def on_tts_live_setting_changed(self, _value=None):
        self._refresh_tts_current_settings()

    def _on_tts_artificial_sentence_pauses_changed(self):
        self.ui_settings["tts_artificial_sentence_pauses"] = self.tts_artificial_sentence_pauses_var.get() == "1"
        self._save_ui_settings()
        self.on_tts_live_setting_changed()

    def _refresh_tts_current_settings(self):
        source = (self.tts_source_var.get() or "editor").strip()
        style = (self.tts_output_style_var.get() or "natural").strip()
        clear_strength = (self.tts_clear_strength_var.get() or "medium").strip()
        breath_control = (self.tts_breath_control_var.get() or "medium").strip() if hasattr(self, "tts_breath_control_var") else "medium"
        delivery = (self.tts_delivery_style_var.get() or "neutral").strip()
        pauses = (self.tts_pause_level_var.get() or "medium").strip()
        chunk_chars = (self.tts_chunk_chars_var.get() or "0").strip() if hasattr(self, "tts_chunk_chars_var") else "0"
        prefer_sentences = (self.tts_prefer_sentence_chunks_var.get() == "1") if hasattr(self, "tts_prefer_sentence_chunks_var") else True
        result_preset = (self.tts_result_preset_var.get() or "clear_narration").strip() if hasattr(self, "tts_result_preset_var") else "clear_narration"
        strength_part = f" | clear={clear_strength}" if style == "clear_speech" else ""
        breath_part = f" | breath={breath_control}" if style == "clear_speech" else ""
        chunk_part = f" | chunk_chars={chunk_chars}"
        sentence_part = " | full_sentences=on" if prefer_sentences else " | full_sentences=off"
        art_part = ""
        if hasattr(self, "tts_artificial_sentence_pauses_var") and self.tts_artificial_sentence_pauses_var.get() == "1":
            art_part = " | artificial_sentence_pauses=on"
        self.lbl_tts_current_settings.configure(
            text=f"Current export settings: preset={result_preset} | source={source} | output={style}{strength_part}{breath_part} | delivery={delivery} | pauses={pauses}{chunk_part}{sentence_part}{art_part}"
        )

    def on_tts_profile_changed(self, profile_name):
        name = (profile_name or "").strip()
        self.tts_profile_details.delete("0.0", "end")
        if hasattr(self, "lbl_tts_profile_hint"):
            self.lbl_tts_profile_hint.configure(text="")
        if not name or name == "(none)" or name not in self.tts_profiles:
            self.tts_profile_details.insert("end", "No profile selected.")
            self._refresh_tts_current_settings()
            return
        meta = self.tts_profiles.get(name, {})
        delivery_style = meta.get("delivery_style", "neutral")
        pause_level = meta.get("pause_level", "medium")
        self.tts_delivery_style_var.set(delivery_style if delivery_style in TTS_DELIVERY_STYLES else "neutral")
        self.tts_pause_level_var.set(pause_level if pause_level in TTS_PAUSE_LEVELS else "medium")
        creation_preset_key = meta.get("creation_preset", "-")
        creation_preset_label = creation_preset_key
        if creation_preset_key in TTS_CREATION_PRESETS:
            creation_preset_label = TTS_CREATION_PRESETS[creation_preset_key].get("label", creation_preset_key)
        lines = [
            f"Name: {name}",
            f"Language: {meta.get('language', '-')}",
            f"Creation preset: {creation_preset_label}",
            f"Reference preprocess: {meta.get('preprocess', '-')}",
            f"Reference clips: {meta.get('reference_count', 1)}",
            f"Delivery style: {delivery_style}",
            f"Pause level: {pause_level}",
            f"Reference file: {os.path.basename(meta.get('reference_wav', ''))}",
        ]
        created_at = meta.get("created_at")
        if created_at:
            try:
                created_str = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(int(created_at)))
                lines.append(f"Created: {created_str}")
            except Exception:
                pass
        self.tts_profile_details.insert("end", "\n".join(lines))
        try:
            tab_lang = (self.tts_language_var.get() or "").strip().lower()
            prof_lang = (meta.get("language") or "").strip().lower()
            if tab_lang and prof_lang and tab_lang != prof_lang and hasattr(self, "lbl_tts_profile_hint"):
                self.lbl_tts_profile_hint.configure(
                    text=self._tr(
                        f"Note: Profile language is '{prof_lang}', but Tab 5 language is '{tab_lang}'. Pick the matching language for best results.",
                        f"Hinweis: Profil-Sprache ist '{prof_lang}', aber Tab-5-Sprache ist '{tab_lang}'. Bitte passende Sprache waehlen fuer beste Ergebnisse.",
                    ),
                    text_color="orange",
                )
        except Exception:
            pass
        self._refresh_tts_current_settings()

    def _sanitize_profile_name(self, name):
        cleaned = re.sub(r'[^a-zA-Z0-9_\- ]+', '', name).strip()
        return cleaned.replace(" ", "_")

    def _pause_ms_from_level(self, level):
        pause_map = {"none": 0, "low": 80, "medium": 180, "high": 320}
        return pause_map.get((level or "medium").strip().lower(), 180)

    def _sentence_pause_ms_from_level(self, level):
        """Extra silence between sentences inside one GUI chunk (XTTS), not Coqui concat."""
        base = self._pause_ms_from_level(level)
        if base <= 0:
            return 0
        return min(620, int(base * 1.55))

    def _chunk_chars_from_delivery(self, delivery):
        d = (delivery or "neutral").strip().lower()
        if d == "calm":
            return 260
        if d == "fast":
            return 340
        return 280

    def _parse_tts_chunk_chars_limit(self):
        raw = (self.tts_chunk_chars_var.get() or "0").strip() if hasattr(self, "tts_chunk_chars_var") else "0"
        try:
            value = int(raw)
        except Exception:
            value = 0
        if value < 0:
            value = 0
        return value

    def _split_text_for_tts(self, text, max_chars, prefer_full_sentences=True):
        clean = (text or "").strip()
        if not clean:
            return []
        if max_chars <= 0:
            return [clean]

        sentences = re.split(r'(?<=[.!?])\s+', clean)
        chunks = []
        current = []
        current_len = 0

        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue

            if prefer_full_sentences and len(sentence) > max_chars:
                if current:
                    chunks.append(" ".join(current).strip())
                    current = []
                    current_len = 0
                chunks.append(sentence)
                continue

            sentence_parts = [sentence] if prefer_full_sentences else self._split_sentence_by_chars(sentence, max_chars)
            for part in sentence_parts:
                add_len = len(part) + (1 if current else 0)
                if current and (current_len + add_len > max_chars):
                    chunks.append(" ".join(current).strip())
                    current = [part]
                    current_len = len(part)
                else:
                    current.append(part)
                    current_len += add_len

        if current:
            chunks.append(" ".join(current).strip())
        return [c for c in chunks if c]

    def _build_clear_speech_filter(self, strength, breath_control):
        s = (strength or "medium").strip().lower()
        b = (breath_control or "medium").strip().lower()
        if s == "soft":
            base = "highpass=f=100,lowpass=f=8200,afftdn=nr=6,agate=threshold=0.01:range=0.04:attack=5:release=90,acompressor=threshold=-20dB:ratio=2.0:attack=8:release=120,loudnorm"
        elif s == "strong":
            base = "highpass=f=130,lowpass=f=7000,afftdn=nr=12,agate=threshold=0.03:range=0.14:attack=5:release=90,acompressor=threshold=-17dB:ratio=2.8:attack=8:release=120,loudnorm"
        else:
            base = "highpass=f=120,lowpass=f=7600,afftdn=nr=10,agate=threshold=0.02:range=0.10:attack=5:release=90,acompressor=threshold=-18dB:ratio=2.5:attack=8:release=120,loudnorm"

        if b == "off":
            return base
        if b == "low":
            breath_gate = "agate=threshold=0.010:range=0.03:attack=4:release=70"
        elif b == "high":
            breath_gate = "agate=threshold=0.022:range=0.10:attack=3:release=45"
        else:
            breath_gate = "agate=threshold=0.015:range=0.06:attack=4:release=60"
        return f"{base},{breath_gate}"

    def _prepare_tts_text_for_delivery(self, text, delivery_style, pause_level):
        t = re.sub(r'\s+', ' ', (text or "")).strip()
        if not t:
            return t
        d = (delivery_style or "neutral").strip().lower()
        p = (pause_level or "medium").strip().lower()

        if p == "none":
            # Minimize pauses by reducing comma/semicolon-driven micro-pauses.
            t = re.sub(r'[;,]+', ' ', t)
            t = re.sub(r'\s+', ' ', t).strip()
        elif p == "high":
            # Encourage stronger pausing at conjunctions.
            t = re.sub(r'\b(und|aber|denn|weil|and|but|so|however)\b', r', \1', t, flags=re.IGNORECASE)
            t = re.sub(r',\s*,+', ', ', t)

        if d == "fast":
            # Keep punctuation simpler for a more direct cadence.
            t = re.sub(r'\s*[,;:]\s*', ' ', t)
            t = re.sub(r'\s+', ' ', t).strip()
        elif d == "calm":
            if t and t[-1] not in ".!?":
                t += "."

        return t

    def _preprocess_audio_with_mode(self, input_path, output_wav_path, mode):
        ff = self._ffmpeg_exe()
        if mode == "off":
            cmd = [
                ff, "-y",
                "-i", input_path,
                "-ar", "24000",
                "-ac", "1",
                output_wav_path
            ]
        else:
            filter_map = {
                "voice_clean": "highpass=f=80,lowpass=f=8000,afftdn,loudnorm",
                "speech_boost": "highpass=f=100,lowpass=f=7000,afftdn=nr=18,acompressor=threshold=-20dB:ratio=2:attack=20:release=250,loudnorm",
                "music_heavy_cleanup": "highpass=f=120,lowpass=f=5000,afftdn=nr=24,agate=threshold=-28dB:range=12dB:attack=15:release=220,acompressor=threshold=-24dB:ratio=2.5:attack=15:release=220,loudnorm"
            }
            filter_chain = filter_map.get(mode, filter_map["voice_clean"])
            cmd = [
                ff, "-y",
                "-i", input_path,
                "-vn",
                "-af", filter_chain,
                "-ar", "24000",
                "-ac", "1",
                output_wav_path
            ]
        run = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if run.returncode != 0:
            err = (run.stderr or "Unknown FFmpeg error").strip()
            raise Exception(err[-500:])

    def save_tts_profile(self):
        multi_enabled = hasattr(self, "tts_multi_ref_var") and self.tts_multi_ref_var.get() == "1"
        multi_paths = [p for p in self.tts_multi_ref_paths if p and os.path.exists(p)]
        if multi_enabled and len(multi_paths) < 2:
            messagebox.showwarning(
                "Multi-reference",
                self._tr(
                    "Multi-reference is ON, but you need at least 2 files (or turn multi-reference OFF and use a single reference).",
                    "Multi-Referenz ist AN, aber es werden mindestens 2 Dateien gebraucht (oder Multi-Referenz AUS und eine einzelne Referenz).",
                ),
            )
            return
        if not multi_paths and (not self.tts_selected_reference_path or not os.path.exists(self.tts_selected_reference_path)):
            messagebox.showwarning("No reference", "Please drop/browse a reference file or add multi-reference files first.")
            return
        profile_name_raw = (self.tts_profile_name_entry.get() or "").strip()
        profile_name = self._sanitize_profile_name(profile_name_raw)
        if not profile_name:
            messagebox.showwarning("Invalid name", "Please enter a valid profile name.")
            return
        lang = (self.tts_language_var.get() or "de").strip().lower()
        mode = (self.tts_preprocess_var.get() or "off").strip().lower()
        creation_preset_value = (self.tts_creation_preset_var.get() or TTS_CREATION_PRESETS["balanced_default"]["label"]).strip()
        creation_preset = "balanced_default"
        if creation_preset_value in TTS_CREATION_PRESETS:
            creation_preset = creation_preset_value
        else:
            for k, v in TTS_CREATION_PRESETS.items():
                if v.get("label") == creation_preset_value:
                    creation_preset = k
                    break
        delivery_style = (self.tts_delivery_style_var.get() or "neutral").strip().lower()
        pause_level = (self.tts_pause_level_var.get() or "medium").strip().lower()
        if not self._ffmpeg_available():
            messagebox.showwarning("FFmpeg missing", "FFmpeg is required to store normalized profile audio.")
            return

        profile_dir = os.path.join(self.tts_profiles_root, lang, profile_name)
        os.makedirs(profile_dir, exist_ok=True)
        ref_wav = os.path.join(profile_dir, "reference.wav")
        try:
            if multi_enabled and len(multi_paths) >= 2:
                use_quality_picker = self.tts_multi_ref_quality_var.get() == "1" if hasattr(self, "tts_multi_ref_quality_var") else True
                self._build_multi_reference_wav(multi_paths, ref_wav, mode, use_quality_picker)
            else:
                self._preprocess_audio_with_mode(self.tts_selected_reference_path, ref_wav, mode)
        except Exception as e:
            messagebox.showerror("Profile save failed", f"Could not preprocess reference audio:\n{str(e)}")
            return

        self.tts_profiles[profile_name] = {
            "language": lang,
            "reference_wav": ref_wav,
            "created_at": int(time.time()),
            "preprocess": mode,
            "creation_preset": creation_preset,
            "delivery_style": delivery_style,
            "pause_level": pause_level,
            "reference_count": len(multi_paths) if (multi_enabled and len(multi_paths) >= 2) else 1
        }
        self._save_tts_index()
        self.on_tts_language_changed(lang)
        self.tts_profile_var.set(profile_name)
        self.on_tts_profile_changed(profile_name)
        self.lbl_status.configure(text=f"TTS profile saved: {profile_name} ({lang})", text_color="lightgreen")

    def check_local_tts_setup(self):
        try:
            cmd = self._build_tts_python_command() + [
                "-c",
                "import sys; from TTS.api import TTS; m='tts_models/multilingual/multi-dataset/xtts_v2'; "
                "import torch; print(sys.version.split()[0]); print(m); "
                "print('cuda=' + ('1' if torch.cuda.is_available() else '0'))",
            ]
            run = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if run.returncode != 0:
                raise Exception((run.stderr or run.stdout or "TTS check failed").strip()[-300:])
            lines = [ln for ln in (run.stdout or "").strip().splitlines() if ln.strip()]
            py = lines[0] if lines else "unknown"
            cuda_on = any(ln.strip().lower() == "cuda=1" for ln in lines)
            cuda_txt_en = "CUDA ON" if cuda_on else "CUDA OFF (CPU)"
            cuda_txt_de = "CUDA AN" if cuda_on else "CUDA AUS (CPU)"
            self.lbl_tts_check.configure(
                text=self._tr(
                    f"OK: Coqui XTTS v2 on Python {py} - {cuda_txt_en}",
                    f"OK: Coqui XTTS v2 mit Python {py} - {cuda_txt_de}",
                ),
                text_color="lightgreen",
            )
        except Exception as e:
            self.lbl_tts_check.configure(text=f"Missing local TTS: {str(e)}", text_color="orange")

    def _get_tts_source_text(self):
        source_mode = (self.tts_source_var.get() or "editor").strip().lower()
        if source_mode == "clean_text":
            return self._strip_block_metadata(self.txt_editor.get("0.0", "end")).strip()
        return self.txt_editor.get("0.0", "end").strip()

    def cancel_tts_export(self):
        self.tts_cancel_requested = True
        proc = self.tts_active_process
        if proc and proc.poll() is None:
            try:
                proc.terminate()
            except Exception:
                pass
        self.lbl_status.configure(text="TTS: cancel requested...", text_color="orange")

    @staticmethod
    def _read_utf8_file_tail(path, max_bytes=16384):
        if not path or not os.path.isfile(path):
            return ""
        try:
            size = os.path.getsize(path)
            start = max(0, size - max_bytes)
            with open(path, "rb") as f:
                if start > 0:
                    f.seek(start)
                raw = f.read()
            return raw.decode("utf-8", errors="replace").strip()
        except OSError:
            return ""

    def _ask_tts_continue_waiting(self):
        decision = {"continue": False}
        done = threading.Event()

        def _show_dialog():
            choice = messagebox.askyesno(
                "TTS still loading",
                "TTS is still at chunk 0 after 5 minutes.\n\nContinue waiting?"
            )
            decision["continue"] = bool(choice)
            done.set()

        self.after(0, _show_dialog)
        done.wait()
        return decision["continue"]

    def start_tts_export(self):
        text = self._get_tts_source_text()
        if not text:
            messagebox.showwarning("No text", "No text available for TTS export.")
            return
        profile_name = (self.tts_profile_var.get() or "").strip()
        if not profile_name or profile_name == "(none)" or profile_name not in self.tts_profiles:
            messagebox.showwarning("No profile", "Select a saved TTS profile first.")
            return
        profile = self.tts_profiles[profile_name]
        reference_wav = profile.get("reference_wav", "")
        if not reference_wav or not os.path.exists(reference_wav):
            messagebox.showwarning("Missing reference", "Saved profile audio is missing. Re-save the profile.")
            return
        out_default = f"{profile_name}_tts.mp3"
        if self.video_path:
            base = os.path.splitext(os.path.basename(self.video_path))[0]
            out_default = f"{base}_{profile_name}_tts.mp3"
        output_path = filedialog.asksaveasfilename(
            defaultextension=".mp3",
            initialfile=out_default,
            filetypes=[("MP3", "*.mp3")]
        )
        if not output_path:
            return
        output_style = (self.tts_output_style_var.get() or "natural").strip().lower() if hasattr(self, "tts_output_style_var") else "natural"
        clear_strength = (self.tts_clear_strength_var.get() or "medium").strip().lower() if hasattr(self, "tts_clear_strength_var") else "medium"
        breath_control = (self.tts_breath_control_var.get() or "medium").strip().lower() if hasattr(self, "tts_breath_control_var") else "medium"
        delivery_style = (self.tts_delivery_style_var.get() or "neutral").strip().lower() if hasattr(self, "tts_delivery_style_var") else "neutral"
        pause_level = (self.tts_pause_level_var.get() or "medium").strip().lower() if hasattr(self, "tts_pause_level_var") else "medium"
        chunk_chars_limit = self._parse_tts_chunk_chars_limit()
        prefer_full_sentences = (self.tts_prefer_sentence_chunks_var.get() == "1") if hasattr(self, "tts_prefer_sentence_chunks_var") else True
        tts_engine = TTS_ENGINE_XTTS_V2
        try:
            _ = self._ffmpeg_exe()
            py_cmd = self._build_tts_python_command()
        except Exception as e:
            messagebox.showwarning(
                self._tr("TTS setup", "TTS Setup"),
                str(e),
            )
            return
        self.tts_cancel_requested = False
        self.tts_active_process = None
        self.btn_tts_export.configure(state="disabled")
        self.btn_tts_cancel.configure(state="normal")
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0.02)
        self.lbl_status.configure(
            text=self._tr("TTS: loading voice model...", "TTS: lade Stimmen-Modell..."),
            text_color="yellow",
        )
        export_lang = (self.tts_language_var.get() or "").strip().lower() if hasattr(self, "tts_language_var") else ""
        if export_lang not in LANGUAGE_CODES or export_lang == "auto":
            export_lang = (profile.get("language") or "en").strip().lower()
        threading.Thread(
            target=self._tts_export_thread,
            args=(
                text,
                profile,
                output_path,
                output_style,
                clear_strength,
                breath_control,
                delivery_style,
                pause_level,
                chunk_chars_limit,
                prefer_full_sentences,
                tts_engine,
                export_lang,
            ),
            daemon=True
        ).start()

    def _tts_export_thread(
        self,
        text,
        profile,
        output_path,
        output_style,
        clear_strength,
        breath_control,
        delivery_style,
        pause_level,
        chunk_chars_limit,
        prefer_full_sentences,
        tts_engine,
        export_lang,
    ):
        temp_dir = tempfile.mkdtemp(prefix="tts_export_")
        try:
            lang = (export_lang or profile.get("language") or "en").strip().lower()
            reference_wav = profile.get("reference_wav")
            prepared_text = self._prepare_tts_text_for_delivery(text, delivery_style, pause_level)
            chunk_chars = chunk_chars_limit if chunk_chars_limit > 0 else self._chunk_chars_from_delivery(delivery_style)
            chunks = self._split_text_for_tts(prepared_text, max_chars=chunk_chars, prefer_full_sentences=prefer_full_sentences) or [prepared_text]
            total_chunks = len(chunks)
            self.after(
                0,
                lambda tc=total_chunks: self.lbl_status.configure(
                    text=self._tr(
                        f"TTS: starting synthesis (0/{tc} chunks)...",
                        f"TTS: Start Synthese (0/{tc} Bloecke)...",
                    ),
                    text_color="yellow",
                ),
            )
            self.after(0, lambda: self.progress.set(0.05))
            payload_path = os.path.join(temp_dir, "payload.json")
            te = str(tts_engine or TTS_ENGINE_XTTS_V2).strip().lower()
            if te not in TTS_ENGINES:
                te = TTS_ENGINE_XTTS_V2
            payload = {
                "engine": te,
                "reference_wav": reference_wav,
                "language": lang,
                "chunks": chunks,
                "out_dir": temp_dir,
                "coqui_model": "tts_models/multilingual/multi-dataset/xtts_v2",
                "sentence_pause_ms": (
                    self._sentence_pause_ms_from_level(pause_level)
                    if (
                        hasattr(self, "tts_artificial_sentence_pauses_var")
                        and self.tts_artificial_sentence_pauses_var.get() == "1"
                    )
                    else 0
                ),
            }
            with open(payload_path, "w", encoding="utf-8") as f:
                json.dump(payload, f, ensure_ascii=False)

            runner_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tts_subprocess_runner.py")
            if not os.path.isfile(runner_path):
                raise Exception(f"TTS runner missing: {runner_path}")

            cmd = self._build_tts_python_command() + ["-u", runner_path, payload_path]
            env = os.environ.copy()
            # Prevent interactive ToS prompt in non-interactive subprocess runs.
            env["COQUI_TOS_AGREED"] = "1"
            synth_log_out = os.path.join(temp_dir, "tts_subprocess_stdout.log")
            synth_log_err = os.path.join(temp_dir, "tts_subprocess_stderr.log")
            log_out_fp = None
            log_err_fp = None
            try:
                log_out_fp = open(synth_log_out, "w", encoding="utf-8", newline="\n")
                log_err_fp = open(synth_log_err, "w", encoding="utf-8", newline="\n")
                try:
                    synth_run = subprocess.Popen(
                        cmd,
                        stdout=log_out_fp,
                        stderr=log_err_fp,
                        env=env,
                    )
                except FileNotFoundError as e:
                    raise Exception(
                        self._tr(
                            f"Could not start TTS process (missing program in PATH?): {e}",
                            f"TTS-Prozess konnte nicht starten (fehlendes Programm in PATH?): {e}",
                        )
                    ) from e
            finally:
                try:
                    if log_out_fp:
                        log_out_fp.close()
                except OSError:
                    pass
                try:
                    if log_err_fp:
                        log_err_fp.close()
                except OSError:
                    pass
            self.tts_active_process = synth_run
            start_wait = time.time()
            last_done = -1
            zero_chunk_warned = False
            while synth_run.poll() is None:
                if self.tts_cancel_requested:
                    try:
                        synth_run.terminate()
                    except Exception:
                        pass
                    raise Exception("TTS export cancelled by user.")

                done = len([x for x in os.listdir(temp_dir) if x.startswith("chunk_") and x.endswith(".wav")])
                if done != last_done:
                    last_done = done
                    if done > 0:
                        pct = done / max(total_chunks, 1)
                        self.after(
                            0,
                            lambda d=done, t=total_chunks, p=pct: (
                                self.lbl_status.configure(text=f"TTS: synthesizing chunks {d}/{t}...", text_color="yellow"),
                                self.progress.set(min(0.75, 0.05 + p * 0.70))
                            )
                        )
                if done == 0:
                    waited = time.time() - start_wait
                    if (not zero_chunk_warned) and waited > 120:
                        zero_chunk_warned = True
                        self.after(
                            0,
                            lambda: self.lbl_status.configure(
                                text="TTS: still loading model (chunk 0). This can happen on first run...",
                                text_color="orange"
                            )
                        )
                    if waited > 300:
                        should_continue = self._ask_tts_continue_waiting()
                        if not should_continue:
                            try:
                                synth_run.terminate()
                            except Exception:
                                pass
                            raise Exception("TTS cancelled after extended chunk-0 wait.")
                        start_wait = time.time()
                        zero_chunk_warned = False
                time.sleep(1.0)

            return_code = synth_run.returncode
            if return_code != 0:
                merged_out = self._read_utf8_file_tail(synth_log_out)
                err_tail = self._read_utf8_file_tail(synth_log_err)
                err = (err_tail or merged_out or "Local TTS synthesis failed").strip()
                raise Exception(err[-500:])

            wav_files = sorted(
                [os.path.join(temp_dir, x) for x in os.listdir(temp_dir) if x.startswith("chunk_") and x.endswith(".wav")]
            )
            if not wav_files:
                raise Exception("No WAV chunks were generated by local TTS.")

            ff = self._ffmpeg_exe()
            pause_ms = self._pause_ms_from_level(pause_level)
            if pause_ms > 0 and len(wav_files) > 1:
                silence_wav = os.path.join(temp_dir, "silence.wav")
                sil_cmd = [
                    ff, "-y",
                    "-f", "lavfi",
                    "-i", f"anullsrc=r=24000:cl=mono",
                    "-t", f"{pause_ms/1000.0:.3f}",
                    silence_wav
                ]
                sil_run = subprocess.run(sil_cmd, capture_output=True, text=True, check=False)
                if sil_run.returncode == 0 and os.path.exists(silence_wav):
                    interleaved = []
                    for i, w in enumerate(wav_files):
                        interleaved.append(w)
                        if i < len(wav_files) - 1:
                            interleaved.append(silence_wav)
                    wav_files = interleaved

            self.after(0, lambda: self.lbl_status.configure(text="TTS: merging chunks...", text_color="yellow"))
            self.after(0, lambda: self.progress.set(0.82))
            concat_list = os.path.join(temp_dir, "concat.txt")
            with open(concat_list, "w", encoding="utf-8") as f:
                for w in wav_files:
                    safe = w.replace("\\", "/")
                    f.write(f"file '{safe}'\n")

            merged_wav = os.path.join(temp_dir, "merged.wav")
            join_cmd = [ff, "-y", "-f", "concat", "-safe", "0", "-i", concat_list, "-c", "copy", merged_wav]
            join_run = subprocess.run(join_cmd, capture_output=True, text=True, check=False)
            if join_run.returncode != 0:
                err = (join_run.stderr or "FFmpeg concat failed").strip()
                raise Exception(err[-500:])

            self.after(0, lambda: self.lbl_status.configure(text="TTS: encoding MP3...", text_color="yellow"))
            self.after(0, lambda: self.progress.set(0.92))
            if output_style == "clear_speech":
                # Mild gate helps suppress breath spikes between generated chunks.
                # Keep agate params in normalized range for broad FFmpeg compatibility.
                clear_filter = self._build_clear_speech_filter(clear_strength, breath_control)
                mp3_cmd = [
                    ff, "-y",
                    "-i", merged_wav,
                    "-af", clear_filter,
                    "-codec:a", "libmp3lame",
                    "-q:a", "2",
                    output_path
                ]
            else:
                mp3_cmd = [ff, "-y", "-i", merged_wav, "-codec:a", "libmp3lame", "-q:a", "2", output_path]
            mp3_run = subprocess.run(mp3_cmd, capture_output=True, text=True, check=False)
            if mp3_run.returncode != 0:
                err = (mp3_run.stderr or "FFmpeg MP3 export failed").strip()
                raise Exception(err[-500:])

            if not os.path.exists(output_path):
                raise Exception(f"MP3 export reported success but file was not found at: {output_path}")
            if os.path.getsize(output_path) <= 0:
                raise Exception(f"MP3 file is empty: {output_path}")

            self.after(0, lambda: self.progress.set(1.0))
            self.after(0, lambda p=output_path: self.lbl_status.configure(text=f"TTS MP3 exported: {p}", text_color="lightgreen"))
        except Exception as e:
            err_text = str(e)
            is_user_cancel = err_text in {
                "TTS export cancelled by user.",
                "TTS cancelled after extended chunk-0 wait.",
            }
            if is_user_cancel:
                self.after(
                    0,
                    lambda: self.lbl_status.configure(
                        text="TTS export cancelled.",
                        text_color="orange",
                    ),
                )
            else:
                self.after(0, lambda err=err_text: messagebox.showerror("TTS export failed", err))
                self.after(0, lambda err=err_text: self.lbl_status.configure(text=f"TTS error: {err}", text_color="red"))
        finally:
            self.after(0, lambda: self.btn_tts_export.configure(state="normal"))
            self.after(0, lambda: self.btn_tts_cancel.configure(state="disabled"))
            self.tts_active_process = None
            self.tts_cancel_requested = False
            try:
                shutil.rmtree(temp_dir, ignore_errors=True)
            except Exception:
                pass

    # --- LOGIK: TRANSKRIPTION ---
    def _format_mmss(self, seconds_value):
        total = max(0, int(seconds_value))
        minutes = total // 60
        seconds = total % 60
        return f"{minutes:02d}:{seconds:02d}"

    def _get_media_duration_seconds(self, input_path):
        try:
            probe = subprocess.run(
                [
                    "ffprobe", "-v", "error",
                    "-show_entries", "format=duration",
                    "-of", "default=noprint_wrappers=1:nokey=1",
                    input_path
                ],
                capture_output=True,
                text=True,
                check=False
            )
            if probe.returncode != 0:
                return None
            value = (probe.stdout or "").strip()
            duration = float(value) if value else 0.0
            return duration if duration > 0 else None
        except Exception:
            return None

    def _media_file_has_video_stream(self, path):
        """
        True/False if ffprobe sees a video stream; None if ffprobe missing or failed.
        Used to avoid false 'audio only' errors when Resolve omits Image Width metadata.
        """
        if not path or not os.path.isfile(path):
            return False
        try:
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=codec_type",
                    "-of",
                    "default=noprint_wrappers=1:nokey=1",
                    path,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            if probe.returncode != 0:
                return None
            line = (probe.stdout or "").strip().lower()
            return line == "video"
        except (OSError, subprocess.SubprocessError, ValueError):
            return None

    def _davinci_parse_ffprobe_fps(self, raw):
        if not raw:
            return None
        s = str(raw).strip()
        if s in ("0/0", "nan"):
            return None
        if "/" in s:
            a, b = s.split("/", 1)
            try:
                q = float(a) / float(b)
                return q if q > 0.001 else None
            except ValueError:
                return None
        try:
            q = float(s)
            return q if q > 0.001 else None
        except ValueError:
            return None

    def _davinci_probe_video_fps_duration(self, path):
        """ffprobe video stream FPS + container duration — trims match real media better than wrong Resolve FPS."""
        if not path or not os.path.isfile(path):
            return None, None
        try:
            probe = subprocess.run(
                [
                    "ffprobe",
                    "-v",
                    "error",
                    "-select_streams",
                    "v:0",
                    "-show_entries",
                    "stream=avg_frame_rate,r_frame_rate",
                    "-show_entries",
                    "format=duration",
                    "-of",
                    "json",
                    path,
                ],
                capture_output=True,
                text=True,
                check=False,
                timeout=120,
            )
            if probe.returncode != 0:
                return None, None
            data = json.loads(probe.stdout or "{}")
            fmt = data.get("format") or {}
            dur_raw = fmt.get("duration")
            duration_sec = float(dur_raw) if dur_raw else None
            streams = data.get("streams") or []
            fps = None
            if streams:
                st = streams[0]
                for key in ("avg_frame_rate", "r_frame_rate"):
                    fps = self._davinci_parse_ffprobe_fps(st.get(key))
                    if fps:
                        break
            return duration_sec, fps
        except (OSError, subprocess.SubprocessError, ValueError, json.JSONDecodeError, TypeError):
            return None, None

    def _estimate_transcription_total_seconds(self):
        media_duration = self._get_media_duration_seconds(self.video_path) if self.video_path else None
        if not media_duration:
            return None

        model = (self.model_var.get() or "large-v3").strip().lower()
        device = (self.device_var.get() or "auto").strip().lower()
        preprocess = (self.audio_preprocess_var.get() if hasattr(self, "audio_preprocess_var") else "off").strip().lower()
        if device == "auto":
            device = "cuda" if torch.cuda.is_available() else "cpu"

        speed_map = {
            "cuda": {"tiny": 3.5, "base": 2.8, "small": 1.9, "medium": 1.2, "large-v3": 0.8},
            "cpu": {"tiny": 0.65, "base": 0.45, "small": 0.30, "medium": 0.18, "large-v3": 0.08}
        }
        realtime_factor = speed_map.get(device, speed_map["cpu"]).get(model, 0.2)
        if preprocess == "voice_clean":
            media_duration *= 1.12
        elif preprocess == "speech_boost":
            media_duration *= 1.18
        elif preprocess == "music_heavy_cleanup":
            media_duration *= 1.30

        estimated_total = media_duration / max(realtime_factor, 0.05)
        return max(1, int(estimated_total))

    def _update_transcription_status(self):
        if not self.transcription_running:
            return
        elapsed = 0
        if self.transcription_start_time is not None:
            elapsed = int(time.time() - self.transcription_start_time)
        dots = "." * ((elapsed % 3) + 1)
        remaining_text = ""
        if self.transcription_eta_total_seconds:
            remaining = max(0, self.transcription_eta_total_seconds - elapsed)
            remaining_text = f" | ETA ~{self._format_mmss(remaining)}"

        if self.transcription_stage == "loading_model":
            self.lbl_status.configure(
                text=f"Loading Whisper model{dots}{remaining_text}",
                text_color='yellow'
            )
            self.progress.configure(mode="determinate")
            self.progress.set(min(0.35, 0.05 + elapsed * 0.01))
        elif self.transcription_stage == "preprocessing_audio":
            self.lbl_status.configure(
                text=f"Preprocessing audio with FFmpeg{dots}{remaining_text}",
                text_color='yellow'
            )
            self.progress.configure(mode="determinate")
            self.progress.set(min(0.55, 0.20 + elapsed * 0.01))
        elif self.transcription_stage == "transcribing":
            self.lbl_status.configure(
                text=f"Transcribing audio{dots}{remaining_text} - check console for segment logs",
                text_color='yellow'
            )
            self.progress.configure(mode="determinate")
            self.progress.set(min(0.95, 0.35 + elapsed * 0.005))
        else:
            self.lbl_status.configure(text=f"Preparing{dots} ({elapsed}s)", text_color='yellow')
            self.progress.configure(mode="indeterminate")
            self.progress.start()

        self.after(1000, self._update_transcription_status)

    def start_transkription(self):
        if not self.video_path:
            self.lbl_status.configure(
                text=self._tr("Please load a video file first (Drag & Drop).", "Bitte zuerst eine Video-Datei laden (Drag & Drop)."),
                text_color='red'
            )
            messagebox.showwarning(
                self._tr("No source", "Keine Quelle"),
                self._tr("Please load a video file first.", "Bitte zuerst eine Video-Datei laden.")
            )
            return
        self.transcription_cancel_requested = False
        self.btn_transcribe.configure(state='disabled')
        if hasattr(self, "btn_stop_transcribe"):
            self.btn_stop_transcribe.configure(state="normal")
        self.auto_punctuation_enabled = self.auto_punct_var.get() == "1"
        self.refresh_whisper_runtime_info()
        resolved_device = self._resolve_transcription_device()
        self.lbl_status.configure(
            text=f"Starting transcription on {resolved_device.upper()}...",
            text_color="yellow",
        )
        self.transcription_eta_total_seconds = self._estimate_transcription_total_seconds()
        self.transcription_stage = "loading_model"
        self.transcription_start_time = time.time()
        self.transcription_running = True
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(0.02)
        self._update_transcription_status()
        threading.Thread(target=self.transkription_thread, daemon=True).start()

    def _ffmpeg_available(self):
        exe = self._resolve_ffmpeg_executable()
        if not exe:
            return False
        check = subprocess.run([exe, "-version"], capture_output=True, text=True, check=False)
        return check.returncode == 0

    def _prepare_audio_for_transcription(self, input_path):
        mode = (self.audio_preprocess_var.get() if hasattr(self, "audio_preprocess_var") else "off").strip().lower()
        if mode == "off":
            return input_path, None

        if not self._ffmpeg_available():
            raise Exception("Audio preprocessing needs FFmpeg, but FFmpeg was not found in PATH.")

        self.transcription_stage = "preprocessing_audio"
        fd, temp_path = tempfile.mkstemp(prefix="transcript_pre_", suffix=".wav")
        os.close(fd)

        filter_map = {
            "voice_clean": "highpass=f=80,lowpass=f=8000,afftdn,loudnorm",
            "speech_boost": "highpass=f=100,lowpass=f=7000,afftdn=nr=18,acompressor=threshold=-20dB:ratio=2:attack=20:release=250,loudnorm",
            "music_heavy_cleanup": "highpass=f=120,lowpass=f=5000,afftdn=nr=24,agate=threshold=-28dB:range=12dB:attack=15:release=220,acompressor=threshold=-24dB:ratio=2.5:attack=15:release=220,loudnorm"
        }
        filter_chain = filter_map.get(mode, filter_map["voice_clean"])
        cmd = [
            self._ffmpeg_exe(), "-y",
            "-i", input_path,
            "-vn",
            "-af", filter_chain,
            "-ar", "16000",
            "-ac", "1",
            temp_path
        ]
        run = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if run.returncode != 0:
            err = (run.stderr or "Unknown FFmpeg preprocessing error").strip()
            try:
                if os.path.exists(temp_path):
                    os.remove(temp_path)
            except Exception:
                pass
            raise Exception(f"FFmpeg preprocessing failed: {err[-400:]}")
        return temp_path, temp_path

    def transkription_thread(self):
        temp_audio_path = None
        try:
            selected_model = self.model_var.get().strip() or "large-v3"
            selected_language = self.language_var.get().strip()
            selected_device = (self.device_var.get().strip() or "auto").lower()
            device = selected_device
            if selected_device == "auto":
                device = "cuda" if torch.cuda.is_available() else "cpu"
            if device == "cuda" and not torch.cuda.is_available():
                raise Exception(self._tr("CUDA selected, but no CUDA-capable GPU detected.", "CUDA ausgewaehlt, aber keine CUDA-faehige GPU erkannt."))

            prepared_audio_path, temp_audio_path = self._prepare_audio_for_transcription(self.video_path)
            if self.transcription_cancel_requested:
                raise Exception("Cancelled.")
            model = whisper.load_model(selected_model, device=device)
            self.transcription_stage = "transcribing"
            word_timestamps = bool(self.chk_cut.get() == 1)

            transcribe_kwargs = {"word_timestamps": word_timestamps}
            if selected_language and selected_language.lower() != "auto":
                transcribe_kwargs["language"] = selected_language.lower()
            if device == "cpu":
                transcribe_kwargs["fp16"] = False
            transcribe_kwargs["verbose"] = True

            # Whisper may warn when optional Triton CUDA kernels are unavailable on Windows.
            # Transcription still works; it just uses slower alignment fallbacks.
            with warnings.catch_warnings():
                warnings.filterwarnings(
                    "ignore",
                    message=r"Failed to launch Triton kernels.*",
                    category=UserWarning,
                    module=r"whisper\.timing",
                )
                result = model.transcribe(prepared_audio_path, **transcribe_kwargs)
            if self.transcription_cancel_requested:
                raise Exception("Cancelled.")
            self.original_text = result["text"].strip()
            if self.auto_punctuation_enabled and self._needs_punctuation_fallback(self.original_text):
                self.original_text = self._apply_basic_punctuation_fallback(self.original_text)
                self.after(
                    0,
                    lambda: self.lbl_status.configure(
                        text=self._tr(
                            "Transcription finished (basic punctuation fallback applied).",
                            "Transkription fertig (basic punctuation fallback applied)."
                        ),
                        text_color='yellow'
                    )
                )
            self.working_text = self.original_text
            
            self.word_timestamps = []
            if word_timestamps and "segments" in result:
                for segment in result["segments"]:
                    for word_info in segment.get("words", []):
                        self.word_timestamps.append({
                            "word": word_info["word"].strip(),
                            "start": word_info["start"],
                            "end": word_info["end"],
                            "keep": True
                        })

            self.after(0, self.transkription_fertig)
        except Exception as e:
            self.transcription_running = False
            self.transcription_stage = "idle"
            self.transcription_eta_total_seconds = None
            msg = str(e)
            if msg.strip().lower() == "cancelled." or msg.strip().lower() == "cancelled":
                self.after(0, lambda: self.lbl_status.configure(text="Transcription cancelled.", text_color="yellow"))
            else:
                self.after(0, lambda m=msg: self.lbl_status.configure(text=f"{self._tr('Error', 'Fehler')}: {m}"))
            self.after(0, self.progress.stop)
            self.after(0, lambda: self.btn_transcribe.configure(state='normal'))
            if hasattr(self, "btn_stop_transcribe"):
                self.after(0, lambda: self.btn_stop_transcribe.configure(state="disabled"))
        finally:
            if temp_audio_path and os.path.exists(temp_audio_path):
                try:
                    os.remove(temp_audio_path)
                except Exception:
                    pass

    def transkription_fertig(self):
        self._push_history_snapshot()
        self.transcription_running = False
        self.transcription_stage = "idle"
        self.transcription_eta_total_seconds = None
        self.progress.stop()
        self.progress.configure(mode="determinate")
        self.progress.set(1)
        self.lbl_status.configure(text=self._tr('Transcription completed.', 'Transkription abgeschlossen.'), text_color='lightgreen')
        self.btn_transcribe.configure(state='normal')
        if hasattr(self, "btn_stop_transcribe"):
            self.btn_stop_transcribe.configure(state="disabled")
        self.txt_editor.delete("0.0", "end")
        self.auto_chunk_after_transcription = self.auto_chunk_var.get() == "1"
        if self.auto_chunk_after_transcription:
            try:
                chunk_size = self._get_chunk_size()
                chunk_char_limit = self._get_chunk_char_limit()
                if chunk_size == 0 and chunk_char_limit == 0:
                    rendered_text = self.original_text
                else:
                    chunks = self._chunk_text_by_sentences(
                        self.original_text,
                        max_words=chunk_size,
                        max_chars=chunk_char_limit
                    )
                    rendered_text = self._format_chunks_for_export(chunks) if chunks else self.original_text
                self.txt_editor.insert("end", rendered_text)
                self.working_text = self.original_text
            except Exception:
                self.txt_editor.insert("end", self.original_text)
                self.working_text = self.original_text
        else:
            self.txt_editor.insert("end", self.original_text)
            self.working_text = self.original_text
        self.tabs.set('2. Filter & Replace')

    # --- LOGIK: FILTERN ---
    def _capture_current_state(self):
        state = {
            "delete_text": "",
            "replace_text": "",
            "editor_text": "",
            "original_text": self.original_text,
            "working_text": self.working_text
        }
        if hasattr(self, "entry_loeschen"):
            state["delete_text"] = self.entry_loeschen.get("0.0", "end").strip()
        if hasattr(self, "entry_ersetzen"):
            state["replace_text"] = self.entry_ersetzen.get("0.0", "end").strip()
        if hasattr(self, "txt_editor"):
            state["editor_text"] = self.txt_editor.get("0.0", "end").strip()
        return state

    def _push_history_snapshot(self):
        snapshot = self._capture_current_state()
        self.change_history.append(snapshot)
        if len(self.change_history) > self.max_history:
            self.change_history = self.change_history[-self.max_history:]
        self.redo_history.clear()

    def _restore_state(self, state):
        if not state:
            return
        if hasattr(self, "entry_loeschen"):
            self.entry_loeschen.delete("0.0", "end")
            self.entry_loeschen.insert("0.0", state.get("delete_text", ""))
        if hasattr(self, "entry_ersetzen"):
            self.entry_ersetzen.delete("0.0", "end")
            self.entry_ersetzen.insert("0.0", state.get("replace_text", ""))
        if hasattr(self, "txt_editor"):
            self.txt_editor.delete("0.0", "end")
            self.txt_editor.insert("end", state.get("editor_text", ""))
        self.original_text = state.get("original_text", self.original_text)
        self.working_text = state.get("working_text", self.working_text)

    def undo_last_change(self):
        if not self.change_history:
            self.lbl_status.configure(text="No more undo steps available.", text_color="red")
            return
        current_state = self._capture_current_state()
        previous_state = self.change_history.pop()
        self.redo_history.append(current_state)
        if len(self.redo_history) > self.max_history:
            self.redo_history = self.redo_history[-self.max_history:]
        self._restore_state(previous_state)
        self.lbl_status.configure(text="Undo applied.", text_color="lightgreen")

    def redo_last_change(self):
        if not self.redo_history:
            self.lbl_status.configure(text="No redo steps available.", text_color="red")
            return
        current_state = self._capture_current_state()
        next_state = self.redo_history.pop()
        self.change_history.append(current_state)
        if len(self.change_history) > self.max_history:
            self.change_history = self.change_history[-self.max_history:]
        self._restore_state(next_state)
        self.lbl_status.configure(text="Redo applied.", text_color="lightgreen")

    def reset_all_changes(self):
        if not self.initial_state:
            self.lbl_status.configure(text="No initial state available.", text_color="red")
            return
        if not messagebox.askyesno("Reset all changes", "Reset editor/filter fields to initial state?"):
            return
        self._restore_state(self.initial_state)
        self.change_history.clear()
        self.redo_history.clear()
        self.lbl_status.configure(text="All changes reset.", text_color="lightgreen")

    def _get_presets_file_path(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "filter_presets.json")

    def _load_ui_settings(self):
        if not os.path.exists(self.ui_settings_path):
            return {}
        try:
            with open(self.ui_settings_path, "r", encoding="utf-8") as f:
                data = json.load(f)
            return data if isinstance(data, dict) else {}
        except Exception:
            return {}

    def _save_ui_settings(self):
        try:
            with open(self.ui_settings_path, "w", encoding="utf-8") as f:
                json.dump(self.ui_settings, f, ensure_ascii=False, indent=2)
        except Exception:
            pass

    def _get_davinci_preset_history(self):
        raw = self.ui_settings.get("davinci_render_preset_history", [])
        if not isinstance(raw, list):
            raw = []
        out = []
        seen = set()
        for x in raw:
            s = str(x or "").strip()
            if not s:
                continue
            k = s.lower()
            if k in seen:
                continue
            out.append(s)
            seen.add(k)
        return out

    def _set_davinci_preset_history(self, items):
        cleaned = []
        seen = set()
        for x in items or []:
            s = str(x or "").strip()
            if not s:
                continue
            k = s.lower()
            if k in seen:
                continue
            cleaned.append(s)
            seen.add(k)
        self.ui_settings["davinci_render_preset_history"] = cleaned[:30]
        self._save_ui_settings()

    def _push_davinci_preset_to_history(self, name):
        s = str(name or "").strip()
        if not s:
            return
        items = [s] + [x for x in self._get_davinci_preset_history() if x.lower() != s.lower()]
        self._set_davinci_preset_history(items)

    def _refresh_davinci_preset_menu(self):
        if not hasattr(self, "davinci_preset_menu"):
            return
        values = self._get_davinci_preset_history()
        if not values:
            values = ["(none)"]
        self.davinci_preset_menu.configure(values=values)

        if hasattr(self, "davinci_preset_choice_var"):
            current = (self.davinci_preset_choice_var.get() or "").strip()
            if current not in values:
                self.davinci_preset_choice_var.set(values[0])

    def on_davinci_preset_selected(self, selected):
        name = (selected or "").strip()
        if not name:
            return
        if name == "(none)":
            if hasattr(self, "davinci_preset_name_var"):
                self.davinci_preset_name_var.set("")
            return
        if hasattr(self, "davinci_preset_name_var"):
            self.davinci_preset_name_var.set(name)

    def save_davinci_preset_name(self):
        name = (self.davinci_preset_name_var.get() if hasattr(self, "davinci_preset_name_var") else "").strip()
        if not name:
            return
        self._push_davinci_preset_to_history(name)
        if hasattr(self, "davinci_preset_choice_var"):
            self.davinci_preset_choice_var.set(name)
        self._refresh_davinci_preset_menu()
        self.lbl_status.configure(text=f"Render preset saved: {name}", text_color="lightgreen")

    def delete_davinci_preset_name(self):
        name = (self.davinci_preset_choice_var.get() if hasattr(self, "davinci_preset_choice_var") else "").strip()
        if not name:
            return
        if name == "(none)":
            return
        if not messagebox.askyesno("Delete preset", f"Remove '{name}' from the preset list?"):
            return
        items = [x for x in self._get_davinci_preset_history() if x.lower() != name.lower()]
        self._set_davinci_preset_history(items)
        self._refresh_davinci_preset_menu()
        self.lbl_status.configure(text=f"Render preset removed: {name}", text_color="lightgreen")

    def browse_davinci_api_path(self):
        path = filedialog.askopenfilename(
            title="Select DaVinciResolveScript.py",
            filetypes=[("Python file", "*.py"), ("All files", "*.*")]
        )
        if not path:
            return
        self.davinci_api_path_var.set(path)
        self.ui_settings["davinci_api_path"] = path
        self._save_ui_settings()

    def _refresh_preset_menu(self):
        names = sorted(self.filter_presets.keys(), key=lambda x: x.lower())
        if not names:
            names = ["Custom"]
        self.preset_menu.configure(values=names)
        current = self.preset_var.get()
        if current not in names:
            self.preset_var.set(names[0])

    def _load_filter_presets(self):
        self.filter_presets = dict(DEFAULT_FILTER_PRESETS)
        self.custom_preset_names = set()
        file_path = self._get_presets_file_path()
        if os.path.exists(file_path):
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    loaded = json.load(f)
                if isinstance(loaded, dict):
                    for name, payload in loaded.items():
                        if isinstance(payload, dict):
                            self.filter_presets[name] = {
                                "delete": str(payload.get("delete", "")),
                                "replace": str(payload.get("replace", ""))
                            }
                            self.custom_preset_names.add(name)
            except Exception:
                pass
        self._refresh_preset_menu()

    def _persist_custom_presets(self):
        file_path = self._get_presets_file_path()
        payload = {}
        for name in sorted(self.custom_preset_names, key=lambda x: x.lower()):
            if name in self.filter_presets:
                payload[name] = self.filter_presets[name]
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, ensure_ascii=False, indent=2)

    def apply_selected_preset(self):
        preset_name = self.preset_var.get().strip()
        preset = self.filter_presets.get(preset_name)
        if not preset:
            self.lbl_status.configure(text="Preset not found.", text_color="red")
            return
        self._push_history_snapshot()
        self.entry_loeschen.delete("0.0", "end")
        self.entry_loeschen.insert("0.0", preset.get("delete", ""))
        self.entry_ersetzen.delete("0.0", "end")
        self.entry_ersetzen.insert("0.0", preset.get("replace", ""))
        self.lbl_status.configure(text=f"Preset applied: {preset_name}", text_color="lightgreen")

    def save_current_as_preset(self):
        dialog = ctk.CTkInputDialog(text="Preset name:", title="Save filter preset")
        preset_name = (dialog.get_input() or "").strip()
        if not preset_name:
            return
        self.filter_presets[preset_name] = {
            "delete": self.entry_loeschen.get("0.0", "end").strip(),
            "replace": self.entry_ersetzen.get("0.0", "end").strip()
        }
        self.custom_preset_names.add(preset_name)
        try:
            self._persist_custom_presets()
        except Exception as e:
            self.lbl_status.configure(text=f"Could not save preset: {str(e)}", text_color="red")
            return
        self._refresh_preset_menu()
        self.preset_var.set(preset_name)
        self.lbl_status.configure(text=f"Preset saved: {preset_name}", text_color="lightgreen")

    def delete_selected_preset(self):
        preset_name = self.preset_var.get().strip()
        if preset_name in DEFAULT_FILTER_PRESETS:
            self.lbl_status.configure(text="Built-in presets cannot be deleted.", text_color="red")
            return
        if preset_name not in self.custom_preset_names:
            self.lbl_status.configure(text="Select a custom preset to delete.", text_color="red")
            return
        if not messagebox.askyesno("Delete preset", f"Delete preset '{preset_name}'?"):
            return
        self.custom_preset_names.discard(preset_name)
        self.filter_presets.pop(preset_name, None)
        try:
            self._persist_custom_presets()
        except Exception as e:
            self.lbl_status.configure(text=f"Could not delete preset: {str(e)}", text_color="red")
            return
        self._refresh_preset_menu()
        self.lbl_status.configure(text=f"Preset deleted: {preset_name}", text_color="lightgreen")

    def _word_boundary_pattern(self, term):
        # Exakte Wortgrenzen: "un" matcht nicht in "hund".
        return re.compile(r'(?<!\w)' + re.escape(term) + r'(?!\w)', flags=re.IGNORECASE)

    def _cleanup_filtered_text(self, text):
        text = re.sub(r'\s+,', ',', text)
        text = re.sub(r'\s+\.', '.', text)
        text = re.sub(r'\s+([!?;:])', r'\1', text)
        text = re.sub(r',\s*,+', ', ', text)
        text = re.sub(r'\.{2,}', '.', text)
        text = re.sub(r'([!?])\1+', r'\1', text)
        text = re.sub(r'\(\s*\)', '', text)
        text = re.sub(r'\s{2,}', ' ', text)
        return text.strip()

    def _needs_punctuation_fallback(self, text):
        stripped = (text or "").strip()
        if not stripped:
            return False
        words = stripped.split()
        if len(words) < 20:
            return False
        punctuation_hits = len(re.findall(r'[.,!?;:]', stripped))
        ratio = punctuation_hits / max(len(words), 1)
        return ratio < 0.01

    def _apply_basic_punctuation_fallback(self, text):
        words = re.split(r'\s+', text.strip())
        if not words:
            return text

        out = []
        words_in_sentence = 0
        min_words = 12
        max_words = 20
        soft_break_words = {"und", "aber", "denn", "weil", "however", "and", "but", "so"}

        for idx, word in enumerate(words):
            token = word.strip()
            if not token:
                continue
            if words_in_sentence == 0:
                token = token[:1].upper() + token[1:] if token else token
            out.append(token)
            words_in_sentence += 1

            is_last = idx == len(words) - 1
            next_word = words[idx + 1].lower() if not is_last else ""
            should_break = words_in_sentence >= max_words or (
                words_in_sentence >= min_words and next_word in soft_break_words
            )
            if should_break and not is_last:
                out.append(".")
                words_in_sentence = 0

        if out and out[-1] not in {".", "!", "?"}:
            out.append(".")

        text_out = " ".join(out)
        text_out = re.sub(r'\s+([.,!?;:])', r'\1', text_out)
        text_out = re.sub(r'\s{2,}', ' ', text_out).strip()
        return text_out

    def _split_sentence_by_chars(self, sentence, max_chars):
        sentence = sentence.strip()
        if not sentence:
            return []
        if len(sentence) <= max_chars:
            return [sentence]
        words = sentence.split()
        parts = []
        current = ""
        for word in words:
            proposal = f"{current} {word}".strip() if current else word
            if len(proposal) <= max_chars:
                current = proposal
            else:
                if current:
                    parts.append(current.strip())
                    current = word
                else:
                    # If one word is longer than max_chars, hard-cut it.
                    start = 0
                    while start < len(word):
                        parts.append(word[start:start + max_chars])
                        start += max_chars
                    current = ""
        if current:
            parts.append(current.strip())
        return [p for p in parts if p]

    def _simple_char_chunks(self, text, max_chars):
        text = re.sub(r'\s+', ' ', (text or "")).strip()
        if not text:
            return []
        if max_chars <= 0:
            return [text]
        chunks = []
        start = 0
        length = len(text)
        while start < length:
            end = min(start + max_chars, length)
            if end < length:
                split_at = text.rfind(" ", start, end)
                if split_at > start:
                    end = split_at
            chunk = text[start:end].strip()
            if chunk:
                chunks.append(chunk)
            start = end
            while start < length and text[start] == " ":
                start += 1
        return chunks

    def _chunk_text_by_sentences(self, text, max_words=400, max_chars=500):
        text = re.sub(r'\s+', ' ', text).strip()
        if not text:
            return []

        # Satzbasiert splitten; Chunk-Grenzen immer zwischen vollständigen Sätzen.
        saetze = re.split(r'(?<=[.!?])\s+', text)
        saetze = [s.strip() for s in saetze if s and s.strip()]
        if not saetze:
            return [text]

        chunks = []
        current_sentences = []
        current_words = 0

        for satz in saetze:
            sentence_parts = self._split_sentence_by_chars(satz, max_chars) if max_chars > 0 else [satz]
            for sentence_part in sentence_parts:
                satz_words = len(sentence_part.split())
                proposal = " ".join(current_sentences + [sentence_part]).strip()
                exceeds_word_limit = bool(max_words > 0 and current_sentences and (current_words + satz_words > max_words))
                exceeds_char_limit = bool(max_chars > 0 and current_sentences and (len(proposal) > max_chars))

                if exceeds_word_limit or exceeds_char_limit:
                    chunks.append(" ".join(current_sentences).strip())
                    current_sentences = [sentence_part]
                    current_words = satz_words
                else:
                    current_sentences.append(sentence_part)
                    current_words += satz_words

        if current_sentences:
            chunks.append(" ".join(current_sentences).strip())

        if max_chars > 0:
            safe_chunks = []
            for chunk in chunks:
                if len(chunk) <= max_chars:
                    safe_chunks.append(chunk)
                else:
                    safe_chunks.extend(self._split_sentence_by_chars(chunk, max_chars))
            chunks = safe_chunks

        return [c for c in chunks if c]

    def _split_text_for_translation(self, text, max_chars=3500):
        text = text.strip()
        if not text:
            return []
        if len(text) <= max_chars:
            return [text]
        parts = []
        current = []
        current_len = 0
        sentences = re.split(r'(?<=[.!?])\s+', text)
        for sentence in sentences:
            sentence = sentence.strip()
            if not sentence:
                continue
            add_len = len(sentence) + (1 if current else 0)
            if current and (current_len + add_len > max_chars):
                parts.append(" ".join(current).strip())
                current = [sentence]
                current_len = len(sentence)
            else:
                current.append(sentence)
                current_len += add_len
        if current:
            parts.append(" ".join(current).strip())
        return parts

    def _get_chunk_size(self):
        raw = self.chunk_size_var.get().strip() if hasattr(self, "chunk_size_var") else "400"
        try:
            size = int(raw)
        except ValueError:
            raise ValueError("Chunk size must be a number (e.g. 400, 500, 1000, or 0).")
        if size < 0:
            raise ValueError("Chunk size cannot be negative. Use 0 for no blocks.")
        return size

    def _get_chunk_char_limit(self):
        raw = self.chunk_char_limit_var.get().strip() if hasattr(self, "chunk_char_limit_var") else "500"
        try:
            limit = int(raw)
        except ValueError:
            raise ValueError("Max chars per block must be a number (e.g. 450, 500, 800).")
        if limit < 0:
            raise ValueError("Max chars per block cannot be negative. Use 0 to disable.")
        return limit

    def _format_chunks_for_export(self, chunks):
        if not chunks:
            return ""
        lines = []
        separator = "-" * 60
        for idx, chunk in enumerate(chunks, start=1):
            word_count = len(chunk.split())
            lines.append(f"[Block {idx} | {word_count} Words]")
            lines.append(chunk.strip())
            if idx < len(chunks):
                lines.append("")
                lines.append(separator)
                lines.append("")
        return "\n".join(lines).strip()

    def _strip_block_metadata(self, text):
        lines = text.replace('\r\n', '\n').replace('\r', '\n').split('\n')
        cleaned_lines = []
        for line in lines:
            stripped = line.strip()
            if re.fullmatch(r'\[Block\s+\d+\s+\|\s+\d+\s+(Woerter|Words)\]', stripped):
                continue
            if re.fullmatch(r'-{40,}', stripped):
                continue
            cleaned_lines.append(line)

        cleaned = "\n".join(cleaned_lines)
        cleaned = re.sub(r'\n{3,}', '\n\n', cleaned).strip()
        return cleaned

    def _has_block_format(self, text):
        has_header = re.search(r'^\[Block\s+\d+\s+\|\s+\d+\s+(Woerter|Words)\]\s*$', text, flags=re.MULTILINE) is not None
        has_separator = re.search(r'^\-{40,}\s*$', text, flags=re.MULTILINE) is not None
        return has_header or has_separator

    def _extract_blocks_from_text(self, text):
        separator_pattern = r'\n\s*\-{40,}\s*\n'
        raw_blocks = re.split(separator_pattern, text.strip())
        blocks = []
        for block in raw_blocks:
            block = block.strip()
            if not block:
                continue
            lines = block.splitlines()
            if lines and re.fullmatch(r'\[Block\s+\d+\s+\|\s+\d+\s+(Woerter|Words)\]', lines[0].strip()):
                lines = lines[1:]
            cleaned_block = "\n".join(lines).strip()
            if cleaned_block:
                blocks.append(cleaned_block)
        return blocks

    def _extract_blocks_with_positions(self, text):
        text = text.replace('\r\n', '\n').replace('\r', '\n')
        separator_pattern = r'\n\s*\-{40,}\s*\n'
        blocks = []
        # Split with spans manually to map cursor position.
        separators = list(re.finditer(separator_pattern, text))
        starts = [0]
        ends = []
        for m in separators:
            ends.append(m.start())
            starts.append(m.end())
        ends.append(len(text))
        for idx, (start, end) in enumerate(zip(starts, ends), start=1):
            raw = text[start:end].strip()
            if not raw:
                continue
            lines = raw.splitlines()
            if lines and re.fullmatch(r'\[Block\s+\d+\s+\|\s+\d+\s+(Woerter|Words)\]', lines[0].strip()):
                lines = lines[1:]
            clean = "\n".join(lines).strip()
            if clean:
                blocks.append({"index": idx, "start": start, "end": end, "text": clean})
        return blocks

    def on_copy_block_shortcut(self, _event=None):
        if hasattr(self, "tabs") and self.tabs.get() != "3. Editor & Text Export":
            return
        focus_widget = self.focus_get()
        if focus_widget is self.txt_editor or (hasattr(self.txt_editor, "_textbox") and focus_widget is self.txt_editor._textbox):
            return
        widget_class = ""
        try:
            widget_class = str(focus_widget.winfo_class()).lower() if focus_widget else ""
        except Exception:
            widget_class = ""
        if "entry" in widget_class:
            return
        self.copy_block_from_editor()

    def copy_block_from_editor(self):
        raw_text = self.txt_editor.get("0.0", "end").strip()
        if not raw_text:
            self.lbl_status.configure(text="No text to copy.", text_color="red")
            return

        blocks = self._extract_blocks_with_positions(raw_text) if self._has_block_format(raw_text) else []
        if not blocks:
            copied_text = self._strip_block_metadata(raw_text).strip()
            if not copied_text:
                copied_text = raw_text
            self.clipboard_clear()
            self.clipboard_append(copied_text)
            self.lbl_status.configure(text="Copied text to clipboard (without block headers).", text_color="lightgreen")
            if hasattr(self, "btn_copy_block"):
                self.btn_copy_block.focus_set()
            return

        focus_widget = self.focus_get()
        editor_has_focus = bool(
            focus_widget is self.txt_editor
            or (hasattr(self.txt_editor, "_textbox") and focus_widget is self.txt_editor._textbox)
        )
        selected_block = None
        if editor_has_focus:
            cursor_offset = len(self.txt_editor.get("0.0", "insert"))
            for block in blocks:
                if block["start"] <= cursor_offset <= block["end"]:
                    selected_block = block
                    # Continue with next block after a cursor-based copy.
                    self.copy_block_cycle_index = block["index"] % len(blocks)
                    break

        if selected_block is None:
            selected_block = blocks[self.copy_block_cycle_index % len(blocks)]

        copied_text = self._strip_block_metadata(selected_block["text"]).strip() or selected_block["text"]
        self.clipboard_clear()
        self.clipboard_append(copied_text)
        self.copy_block_cycle_index = selected_block["index"] % len(blocks)
        self.copy_block_cycle_index = (self.copy_block_cycle_index + 1) % len(blocks)
        if hasattr(self, "btn_copy_block"):
            self.btn_copy_block.focus_set()
        self.lbl_status.configure(
            text=f"Copied Block {selected_block['index']} to clipboard (no header).",
            text_color="lightgreen"
        )

    def _translate_block(self, translator, block_text):
        pieces = self._split_text_for_translation(block_text, max_chars=3500)
        translated_pieces = []
        for piece in pieces:
            translated_pieces.append(translator.translate(piece))
        translated = " ".join([p.strip() for p in translated_pieces if p and p.strip()]).strip()
        translated = re.sub(r'\s+', ' ', translated).strip()
        return translated

    def _build_default_translate_filename(self, target_language):
        default_name = f"transcript_translated_{target_language}.txt"
        if self.video_path:
            base = os.path.splitext(os.path.basename(self.video_path))[0].strip()
            if base:
                default_name = f"{base}_translated_{target_language}.txt"
        return default_name

    def start_translate_editor_text(self, mode="replace"):
        if GoogleTranslator is None:
            messagebox.showwarning(
                "Translator missing",
                "Package 'deep-translator' is not installed.\nInstall with: pip install deep-translator"
            )
            self.lbl_status.configure(text="Translation unavailable: deep-translator not installed.", text_color='red')
            return

        source = (self.translate_source_var.get() or "auto").strip().lower()
        target = (self.translate_target_var.get() or "").strip().lower()
        if source == target:
            self.lbl_status.configure(text='Source and target language are identical.', text_color='red')
            return

        text = self.txt_editor.get("0.0", "end").strip()
        if not text:
            self.lbl_status.configure(text='No text in editor to translate.', text_color='red')
            messagebox.showwarning("No text", "There is no text in the editor.")
            return

        save_path = None
        if mode in ("save", "save_clean"):
            default_name = self._build_default_translate_filename(target)
            if mode == "save_clean":
                default_name = default_name.replace(".txt", "_clean.txt")
            save_path = filedialog.asksaveasfilename(
                defaultextension=".txt",
                initialfile=default_name,
                filetypes=[(self._tr("Text file", "Textdatei"), "*.txt")]
            )
            if not save_path:
                return

        keep_block_format = self._has_block_format(text)
        self.btn_translate_replace.configure(state='disabled')
        self.btn_translate_save.configure(state='disabled')
        self.btn_translate_save_clean.configure(state='disabled')
        self.lbl_status.configure(text=f'Translating {source} -> {target}...', text_color='yellow')
        threading.Thread(
            target=self.translate_editor_thread,
            args=(text, source, target, keep_block_format, mode, save_path),
            daemon=True
        ).start()

    def start_translate_editor_text_save(self):
        self.start_translate_editor_text(mode="save")

    def start_translate_editor_text_save_clean(self):
        self.start_translate_editor_text(mode="save_clean")

    def on_translate_action_changed(self, selected_action):
        action = (selected_action or "Translate + Replace").strip()
        self.ui_settings["translate_action"] = action
        self._save_ui_settings()

    def swap_translate_languages(self):
        source = (self.translate_source_var.get() or "auto").strip().lower()
        target = (self.translate_target_var.get() or "de").strip().lower()
        if target == "auto":
            target = "de"
        self.translate_source_var.set(target)
        self.translate_target_var.set(source if source != "auto" else "de")

    def start_translate_from_action(self):
        action = (self.translate_action_var.get() or "Translate + Replace").strip() if hasattr(self, "translate_action_var") else "Translate + Replace"
        self.on_translate_action_changed(action)
        if action == "Translate + Save TXT":
            self.start_translate_editor_text(mode="save")
            return
        if action == "Translate + Save TXT (No Headers)":
            self.start_translate_editor_text(mode="save_clean")
            return
        self.start_translate_editor_text(mode="replace")

    def translate_editor_thread(self, text, source, target, keep_block_format, mode, save_path):
        try:
            translator = GoogleTranslator(source=source, target=target)
            if keep_block_format:
                blocks = self._extract_blocks_from_text(text)
                if not blocks:
                    blocks = [self._strip_block_metadata(text)]
                translated_blocks = [self._translate_block(translator, block) for block in blocks if block.strip()]
                output_text = self._format_chunks_for_export(translated_blocks)
            else:
                clean_text = text.strip()
                output_text = self._translate_block(translator, clean_text)

            self.after(0, lambda: self._finish_translation(output_text, source, target, mode, save_path))
        except Exception as e:
            self.after(0, lambda msg=str(e): self._translation_failed(msg))

    def _finish_translation(self, output_text, source, target, mode, save_path):
        if mode in ("save", "save_clean") and save_path:
            final_text = output_text
            if mode == "save_clean":
                final_text = self._strip_block_metadata(final_text)
                if not final_text.strip():
                    raise ValueError("No translatable content remains after removing block headers.")
            normalized_text = final_text.replace('\r\n', '\n').replace('\r', '\n')
            with open(save_path, 'w', encoding='utf-8', newline='\n') as f:
                f.write(normalized_text + "\n")
            self.lbl_status.configure(
                text=f'Translation saved: {os.path.basename(save_path)} ({source} -> {target})',
                text_color='lightgreen'
            )
        else:
            self._push_history_snapshot()
            self.working_text = self._strip_block_metadata(output_text).strip()
            self.txt_editor.delete("0.0", "end")
            self.txt_editor.insert("end", output_text)
            self.lbl_status.configure(text=f'Translation complete: {source} -> {target}', text_color='lightgreen')
        self.btn_translate_replace.configure(state='normal')
        self.btn_translate_save.configure(state='normal')
        self.btn_translate_save_clean.configure(state='normal')

    def _translation_failed(self, error_text):
        self.btn_translate_replace.configure(state='normal')
        self.btn_translate_save.configure(state='normal')
        self.btn_translate_save_clean.configure(state='normal')
        self.lbl_status.configure(text=f'Translation failed: {error_text}', text_color='red')
        messagebox.showerror("Translation error", error_text)

    def text_filtern(self):
        editor_text = self.txt_editor.get("0.0", "end").strip() if hasattr(self, "txt_editor") else ""
        source_text = self._strip_block_metadata(editor_text).strip()
        if not source_text:
            source_text = (self.working_text or self.original_text or "").strip()
        if not source_text:
            return
        self._push_history_snapshot()
        try:
            chunk_size = self._get_chunk_size()
            chunk_char_limit = self._get_chunk_char_limit()
            if chunk_size == 0 and chunk_char_limit == 0:
                chunk_mode = "no_blocks"
            else:
                chunk_mode = "chunked"
        except ValueError as e:
            self.lbl_status.configure(text=str(e), text_color='red')
            messagebox.showwarning("Invalid chunk size", str(e))
            return

        text = source_text
        loeschen_raw = self.entry_loeschen.get("0.0", "end").replace('\n', ',')
        loeschen_liste = [x.strip().lower() for x in loeschen_raw.split(',') if x.strip()]

        # Zeitstempel-Daten aktualisieren
        for wp in self.word_timestamps:
            clean_word = re.sub(r'[^\w\s]', '', wp["word"]).lower()
            if clean_word in loeschen_liste:
                wp["keep"] = False
            else:
                wp["keep"] = True

        # Text für den Editor filtern (identisch zu vorheriger Logik)
        ersetzen_raw = self.entry_ersetzen.get("0.0", "end").replace('\n', ',')
        ersetzen_liste = [x.strip() for x in ersetzen_raw.split(',') if ':' in x]
        for paar in ersetzen_liste:
            alt, neu = paar.split(':', 1)
            alt = alt.strip()
            neu = neu.strip()
            if not alt:
                continue
            text = self._word_boundary_pattern(alt).sub(neu, text)

        for wort in loeschen_liste:
            if not wort:
                continue
            text = self._word_boundary_pattern(wort).sub('', text)

        if self.cleanup_text_var.get() == "1":
            text = self._cleanup_filtered_text(text)
        else:
            text = re.sub(r'\s+', ' ', text).strip()
        self.working_text = text

        if chunk_mode == "no_blocks":
            chunked_text = text
            self.lbl_status.configure(
                text=f"Block formatting disabled (words={chunk_size}, chars={chunk_char_limit}).",
                text_color="yellow"
            )
        elif chunk_size == 0 and chunk_char_limit > 0:
            chunks = self._chunk_text_by_sentences(text, max_words=0, max_chars=chunk_char_limit)
            chunked_text = self._format_chunks_for_export(chunks)
            self.lbl_status.configure(
                text=f"Block mode: chars-only ({chunk_char_limit} max chars).",
                text_color="lightgreen"
            )
        elif chunk_size > 0 and chunk_char_limit == 0:
            chunks = self._chunk_text_by_sentences(text, max_words=chunk_size, max_chars=0)
            chunked_text = self._format_chunks_for_export(chunks)
            self.lbl_status.configure(
                text=f"Block mode: words-only ({chunk_size} max words).",
                text_color="lightgreen"
            )
        else:
            chunks = self._chunk_text_by_sentences(text, max_words=chunk_size, max_chars=chunk_char_limit)
            chunked_text = self._format_chunks_for_export(chunks)
            self.lbl_status.configure(
                text=f"Block mode: words+chars ({chunk_size} words / {chunk_char_limit} chars).",
                text_color="lightgreen"
            )

        if chunk_mode != "no_blocks" and "[Block " not in chunked_text:
            # Safety fallback: always emit block format when block mode is active.
            if chunk_char_limit > 0:
                fallback_chunks = self._simple_char_chunks(text, chunk_char_limit)
            else:
                fallback_chunks = self._chunk_text_by_sentences(text, max_words=max(chunk_size, 1), max_chars=0)
            chunked_text = self._format_chunks_for_export(fallback_chunks)
            self.lbl_status.configure(
                text="Block mode fallback applied to enforce headers.",
                text_color="yellow"
            )
        self.txt_editor.delete("0.0", "end")
        self.txt_editor.insert("end", chunked_text)
        self.tabs.set('3. Editor & Text Export')

    def import_text_into_editor(self):
        path = filedialog.askopenfilename(filetypes=[("Text files", "*.txt"), ("All files", "*.*")])
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                text = f.read()
        except Exception:
            with open(path, "r", encoding="latin-1") as f:
                text = f.read()
        self._push_history_snapshot()
        self.txt_editor.delete("0.0", "end")
        self.txt_editor.insert("end", text.strip())
        self.working_text = self._strip_block_metadata(text).strip()
        self.lbl_status.configure(text=f"Imported text: {os.path.basename(path)}", text_color="lightgreen")

    def clear_editor_text(self):
        if not messagebox.askyesno("Clear editor", "Clear the editor text?"):
            return
        self._push_history_snapshot()
        self.txt_editor.delete("0.0", "end")
        self.working_text = ""
        self.lbl_status.configure(text="Editor cleared.", text_color="lightgreen")

    def export_text(self):
        text = self.txt_editor.get("0.0", "end").strip()
        if not text:
            self.lbl_status.configure(text=self._tr('No text available for export.', 'Kein Text zum Exportieren vorhanden.'), text_color='red')
            messagebox.showwarning(
                self._tr("No content", "Kein Inhalt"),
                self._tr("There is no text to save.", "Es gibt keinen Text zum Speichern.")
            )
            return

        default_name = "transcript_formatted.txt"
        if self.video_path:
            base = os.path.splitext(os.path.basename(self.video_path))[0].strip()
            if base:
                default_name = f"{base}_transcript_formatted.txt"

        pfad = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[(self._tr("Text file", "Textdatei"), "*.txt")]
        )
        if pfad:
            normalized_text = text.replace('\r\n', '\n').replace('\r', '\n')
            with open(pfad, 'w', encoding='utf-8', newline='\n') as f:
                f.write(normalized_text + "\n")
            self.lbl_status.configure(
                text=f"{self._tr('Text exported successfully', 'Text erfolgreich exportiert')}: {os.path.basename(pfad)}",
                text_color='lightgreen'
            )

    def export_text_clean(self):
        text = self.txt_editor.get("0.0", "end").strip()
        if not text:
            self.lbl_status.configure(text=self._tr('No text available for export.', 'Kein Text zum Exportieren vorhanden.'), text_color='red')
            messagebox.showwarning(
                self._tr("No content", "Kein Inhalt"),
                self._tr("There is no text to save.", "Es gibt keinen Text zum Speichern.")
            )
            return

        clean_text = self._strip_block_metadata(text)
        if not clean_text:
            self.lbl_status.configure(text=self._tr('No text remains after cleanup.', 'Nach Bereinigung ist kein Text uebrig.'), text_color='red')
            messagebox.showwarning(
                self._tr("No content", "Kein Inhalt"),
                self._tr(
                    "No text remains after removing block headers.",
                    "Nach Entfernen der Block-Infos ist kein Text mehr vorhanden."
                )
            )
            return

        default_name = "transcript_clean.txt"
        if self.video_path:
            base = os.path.splitext(os.path.basename(self.video_path))[0].strip()
            if base:
                default_name = f"{base}_transcript_clean.txt"

        pfad = filedialog.asksaveasfilename(
            defaultextension=".txt",
            initialfile=default_name,
            filetypes=[(self._tr("Text file", "Textdatei"), "*.txt")]
        )
        if pfad:
            normalized_text = clean_text.replace('\r\n', '\n').replace('\r', '\n')
            with open(pfad, 'w', encoding='utf-8', newline='\n') as f:
                f.write(normalized_text + "\n")
            self.lbl_status.configure(
                text=f"{self._tr('Text exported without block headers', 'Text ohne Block-Infos exportiert')}: {os.path.basename(pfad)}",
                text_color='lightgreen'
            )

    # --- LOGIK: DAVINCI EXPORT ---
    def on_export_engine_changed(self, selected_engine):
        engine = (selected_engine or "").strip().lower()
        if engine == "davinci":
            self.export_action_menu.configure(values=["cut"])
            self.export_action_var.set("cut")
            self.lbl_engine_hint.configure(
                text=self._tr(
                    "Replace options are available with FFmpeg only.",
                    "Ersetzen-Optionen sind nur mit FFmpeg verfuegbar."
                )
            )
        else:
            self.export_action_menu.configure(values=["cut", "replace_with_silence", "replace_with_tone"])
            if self.export_action_var.get() not in ["cut", "replace_with_silence", "replace_with_tone"]:
                self.export_action_var.set("cut")
            self.lbl_engine_hint.configure(text="")

    def _get_min_segment_duration(self):
        raw = (self.min_segment_var.get() or "0.20").strip()
        try:
            value = float(raw)
        except ValueError:
            raise ValueError("Min segment duration must be numeric (e.g. 0.20).")
        if value < 0:
            raise ValueError("Min segment duration cannot be negative.")
        return value

    def _collect_intervals(self, keep_value=True):
        min_duration = self._get_min_segment_duration()
        intervals = []
        current_start = None
        current_end = None
        for wt in self.word_timestamps:
            if wt["keep"] == keep_value:
                if current_start is None:
                    current_start = wt["start"]
                current_end = wt["end"]
            else:
                if current_start is not None:
                    if (current_end - current_start) >= min_duration:
                        intervals.append((current_start, current_end))
                    current_start = None
                    current_end = None
        if current_start is not None:
            if (current_end - current_start) >= min_duration:
                intervals.append((current_start, current_end))
        return intervals

    def _build_volume_chain(self, intervals, volume_value):
        parts = []
        for start, end in intervals:
            parts.append(f"volume=enable='between(t,{start:.3f},{end:.3f})':volume={volume_value}")
        return ",".join(parts)

    def _build_tone_volume_expression(self, intervals, linear_amp):
        """
        Single volume expression for the sine input. Do NOT chain volume=0 before enable= — that zeros the signal first,
        so later enabled gains still multiply 0 and you hear only silence.
        """
        if not intervals:
            return "0"
        terms = "+".join(f"between(t,{s:.6f},{e:.6f})" for s, e in intervals)
        return f"{linear_amp}*min(1,({terms}))"

    def _srt_timestamp(self, sec):
        sec = max(0.0, float(sec))
        h = int(sec // 3600)
        m = int((sec % 3600) // 60)
        s = int(sec % 60)
        ms = int(round((sec - int(sec)) * 1000))
        if ms >= 1000:
            ms = 999
        return f"{h:02d}:{m:02d}:{s:02d},{ms:03d}"

    def _parse_srt_max_words(self):
        raw = (self.srt_max_words_var.get() if hasattr(self, "srt_max_words_var") else "10").strip()
        try:
            v = int(raw)
        except ValueError:
            v = 10
        return max(1, min(30, v))

    def _subtitle_language_tag(self):
        code = (self.srt_lang_var.get() if hasattr(self, "srt_lang_var") else "und").strip().lower()
        if not code:
            return "und"
        m = {
            "de": "deu",
            "en": "eng",
            "fr": "fra",
            "es": "spa",
            "it": "ita",
            "pt": "por",
            "ru": "rus",
            "ja": "jpn",
            "zh": "zho",
            "ko": "kor",
            "ar": "ara",
            "hi": "hin",
            "tr": "tur",
            "nl": "nld",
            "pl": "pol",
            "cs": "ces",
            "sv": "swe",
            "no": "nor",
            "da": "dan",
            "fi": "fin",
        }
        if len(code) == 2:
            return m.get(code, "und")
        if len(code) == 3 and code.isalpha():
            return code
        return "und"

    def _embed_srt_into_mp4(self, video_path, srt_path):
        if not (video_path and srt_path):
            return False
        if (not os.path.exists(video_path)) or (not os.path.exists(srt_path)):
            return False
        if not video_path.lower().endswith(".mp4"):
            return False
        try:
            ff = self._ffmpeg_exe()
        except Exception:
            return False
        ffmpeg_check = subprocess.run([ff, "-version"], capture_output=True, text=True, check=False)
        if ffmpeg_check.returncode != 0:
            return False

        embedded_tmp = os.path.splitext(video_path)[0] + "_subtitled.mp4"
        cmd_sub = [
            ff,
            "-y",
            "-i",
            video_path,
            "-i",
            srt_path,
            "-map",
            "0:v",
            "-map",
            "0:a?",
            "-map",
            "1:0",
            "-c:v",
            "copy",
            "-c:a",
            "copy",
            "-c:s",
            "mov_text",
            "-metadata:s:s:0",
            f"language={self._subtitle_language_tag()}",
            embedded_tmp,
        ]
        run_sub = subprocess.run(cmd_sub, capture_output=True, text=True, check=False)
        if run_sub.returncode == 0 and os.path.exists(embedded_tmp):
            os.replace(embedded_tmp, video_path)
            return True
        try:
            if os.path.exists(embedded_tmp):
                os.remove(embedded_tmp)
        except Exception:
            pass
        return False

    def _subtitle_replace_map(self):
        if not hasattr(self, "entry_ersetzen"):
            return {}
        raw = self.entry_ersetzen.get("0.0", "end").replace("\n", ",")
        pairs = [x.strip() for x in raw.split(",") if ":" in x]
        repl = {}
        for p in pairs:
            old, new = p.split(":", 1)
            old = old.strip()
            new = new.strip()
            if old:
                repl[old.lower()] = new
        return repl

    def _build_srt_entries_from_words(self, max_words=10, max_duration=4.0):
        if not self.word_timestamps:
            return []
        apply_replace = hasattr(self, "srt_apply_replace_var") and self.srt_apply_replace_var.get() == "1"
        replace_map = self._subtitle_replace_map() if apply_replace else {}
        entries = []
        current_words = []
        start_t = None
        end_t = None
        for wt in self.word_timestamps:
            if not wt.get("keep", True):
                if current_words:
                    entries.append((start_t, end_t, " ".join(current_words).strip()))
                    current_words = []
                    start_t = None
                    end_t = None
                continue
            w = (wt.get("word") or "").strip()
            if not w:
                continue
            if replace_map:
                key = re.sub(r"[^\w]", "", w).lower()
                if key in replace_map:
                    w = replace_map[key]
            ws = float(wt.get("start", 0.0))
            we = float(wt.get("end", ws))
            if start_t is None:
                start_t = ws
            end_t = we
            current_words.append(w)
            if len(current_words) >= max_words or (end_t - start_t) >= max_duration:
                entries.append((start_t, end_t, " ".join(current_words).strip()))
                current_words = []
                start_t = None
                end_t = None
        if current_words:
            entries.append((start_t, end_t, " ".join(current_words).strip()))
        cleaned = []
        for st, et, txt in entries:
            t = re.sub(r"\s+", " ", txt).strip()
            t = re.sub(r"\s+([.,!?;:])", r"\1", t)
            if t:
                cleaned.append((st, max(et, st + 0.05), t))
        return cleaned

    def _write_srt_file(self, srt_path):
        entries = self._build_srt_entries_from_words(max_words=self._parse_srt_max_words())
        if not entries:
            raise Exception("No subtitle entries available (timestamps missing or all words deleted).")
        lines = []
        for i, (st, et, txt) in enumerate(entries, start=1):
            lines.append(str(i))
            lines.append(f"{self._srt_timestamp(st)} --> {self._srt_timestamp(et)}")
            lines.append(txt)
            lines.append("")
        with open(srt_path, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines).strip() + "\n")
        return srt_path

    def start_davinci_export(self):
        if not self.word_timestamps:
            self.lbl_status.configure(
                text=self._tr(
                    'No timestamps available. Re-run transcription with timestamp checkbox enabled.',
                    'Keine Zeitstempel vorhanden. Transkription mit Checkbox wiederholen.'
                ),
                text_color='red'
            )
            return
        try:
            _ = self._get_min_segment_duration()
        except ValueError as e:
            self.lbl_status.configure(text=str(e), text_color='red')
            messagebox.showwarning("Invalid min segment duration", str(e))
            return

        engine = (self.export_engine_var.get() or "davinci").strip().lower()
        action = (self.export_action_var.get() or "cut").strip().lower()

        if engine == "davinci":
            if action != "cut":
                self.lbl_status.configure(
                    text=self._tr(
                        'DaVinci API supports only cut mode here. Use FFmpeg for silence/tone.',
                        'DaVinci API unterstuetzt hier nur Cut. Fuer Silence/Tone bitte FFmpeg waehlen.'
                    ),
                    text_color='red'
                )
                return
            self.lbl_status.configure(text=self._tr('Starting DaVinci Resolve API export...', 'Starte DaVinci Resolve API Export...'), text_color='yellow')
            threading.Thread(target=self.davinci_thread, daemon=True).start()
            return

        if engine == "ffmpeg":
            if action == "cut":
                self.lbl_status.configure(
                    text=self._tr(
                        'FFmpeg mode is intended for silence/tone. Use DaVinci for cut export.',
                        'FFmpeg-Mode ist fuer Silence/Tone gedacht. Fuer Cut bitte DaVinci waehlen.'
                    ),
                    text_color='red'
                )
                return
            base_name = os.path.splitext(os.path.basename(self.video_path))[0] if self.video_path else "output"
            suffix = "silence" if action == "replace_with_silence" else "tone"
            output_path = filedialog.asksaveasfilename(
                defaultextension=".mp4",
                initialfile=f"{base_name}_{suffix}.mp4",
                filetypes=[("MP4 Video", "*.mp4"), (self._tr("All files", "Alle Dateien"), "*.*")]
            )
            if not output_path:
                self.lbl_status.configure(text=self._tr('FFmpeg export cancelled.', 'FFmpeg Export abgebrochen.'), text_color='white')
                return
            self.lbl_status.configure(text=self._tr('Starting FFmpeg export...', 'Starte FFmpeg Export...'), text_color='yellow')
            threading.Thread(target=self.ffmpeg_thread, args=(action, output_path), daemon=True).start()
            return

        self.lbl_status.configure(text=self._tr('Unknown export engine.', 'Unbekannte Export-Engine.'), text_color='red')

    def ffmpeg_thread(self, action, output_path):
        try:
            deleted_intervals = self._collect_intervals(keep_value=False)
            if not deleted_intervals:
                raise Exception(self._tr("No deleted word ranges found. Apply a filter first.", "Keine geloeschten Wortbereiche vorhanden. Bitte erst Filter anwenden."))

            if not self.video_path or not os.path.exists(self.video_path):
                raise Exception(self._tr("Video source not found.", "Videoquelle nicht gefunden."))

            ff = self._ffmpeg_exe()
            ffmpeg_check = subprocess.run(
                [ff, "-version"],
                capture_output=True,
                text=True,
                check=False
            )
            if ffmpeg_check.returncode != 0:
                raise Exception(self._tr("FFmpeg not found. Please install FFmpeg and add it to PATH.", "FFmpeg wurde nicht gefunden. Bitte FFmpeg installieren und in PATH verfuegbar machen."))

            if action == "replace_with_silence":
                mute_chain = self._build_volume_chain(deleted_intervals, 0)
                if not mute_chain:
                    raise Exception(self._tr("Could not create silence filter.", "Konnte Silence-Filter nicht erstellen."))
                filter_complex = f"[0:a]{mute_chain}[aout]"
                cmd = [
                    ff, "-y",
                    "-i", self.video_path,
                    "-filter_complex", filter_complex,
                    "-map", "0:v",
                    "-map", "[aout]",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    output_path
                ]
            else:
                try:
                    tone_freq = int((self.tone_freq_var.get() or "1000").strip())
                except ValueError:
                    raise Exception(self._tr("Tone frequency must be numeric (e.g. 1000).", "Tone frequency muss eine Zahl sein (z. B. 1000)."))
                if tone_freq <= 0:
                    raise Exception(self._tr("Tone frequency must be greater than 0.", "Tone frequency muss groesser als 0 sein."))

                mute_chain = self._build_volume_chain(deleted_intervals, 0)
                if not mute_chain:
                    raise Exception(self._tr("Could not create tone filter.", "Konnte Tone-Filter nicht erstellen."))
                pct = float(self.beep_slider.get()) if hasattr(self, "beep_slider") else 35.0
                tone_amp = max(0.0, min(1.0, pct / 100.0))
                tone_expr = self._build_tone_volume_expression(deleted_intervals, tone_amp)
                filter_complex = (
                    f"[0:a]aresample=48000,{mute_chain}[orig_muted];"
                    f"[1:a]aresample=48000,volume='{tone_expr}':eval=frame[tone];"
                    f"[orig_muted][tone]amix=inputs=2:normalize=0:duration=first[aout]"
                )
                cmd = [
                    ff, "-y",
                    "-i", self.video_path,
                    "-f", "lavfi",
                    "-i", f"sine=frequency={tone_freq}:sample_rate=48000",
                    "-filter_complex", filter_complex,
                    "-map", "0:v",
                    "-map", "[aout]",
                    "-c:v", "copy",
                    "-c:a", "aac",
                    "-shortest",
                    output_path
                ]

            run = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if run.returncode != 0:
                err = (run.stderr or self._tr("Unknown FFmpeg error", "Unbekannter FFmpeg Fehler")).strip()
                err_tail = err[-900:]

                def _is_copy_mp4_failure(msg):
                    m = (msg or "")
                    return (
                        "Could not write header" in m
                        or "Invalid argument" in m
                        or "Could not find tag for codec" in m
                        or "codec not currently supported" in m.lower()
                    )

                # Fallback: if stream copy to MP4 fails, re-encode video to H.264 (more compatible).
                if ("-c:v" in cmd) and ("copy" in cmd) and _is_copy_mp4_failure(err):
                    cmd2 = []
                    i = 0
                    while i < len(cmd):
                        if cmd[i] == "-c:v" and i + 1 < len(cmd):
                            cmd2.extend(["-c:v", "libx264", "-preset", "veryfast", "-crf", "20"])
                            i += 2
                            continue
                        cmd2.append(cmd[i])
                        i += 1
                    run2 = subprocess.run(cmd2, capture_output=True, text=True, check=False)
                    if run2.returncode != 0:
                        err2 = (run2.stderr or "").strip()
                        raise Exception((err2[-900:] if err2 else err_tail))
                else:
                    raise Exception(err_tail)

            srt_msg = ""
            if hasattr(self, "export_srt_var") and self.export_srt_var.get() == "1":
                srt_path = os.path.splitext(output_path)[0] + ".srt"
                self._write_srt_file(srt_path)
                srt_msg = f" + SRT ({os.path.basename(srt_path)})"

                if (
                    hasattr(self, "embed_srt_ffmpeg_var")
                    and self.embed_srt_ffmpeg_var.get() == "1"
                    and output_path.lower().endswith(".mp4")
                ):
                    if self._embed_srt_into_mp4(output_path, srt_path):
                        srt_msg += " + embedded subtitle track"

            self.after(
                0,
                lambda extra=srt_msg: self.lbl_status.configure(
                    text=f'FFmpeg Export erfolgreich: {os.path.basename(output_path)}{extra}',
                    text_color='lightgreen'
                )
            )
        except Exception as e:
            self.after(0, lambda msg=str(e): self.lbl_status.configure(text=f'FFmpeg Fehler: {msg}', text_color='red'))

    def _davinci_normalize_pool_path(self, path):
        if not path:
            return ""
        return path.replace("\\", "/").strip().lower()

    def _davinci_paths_same_file(self, path_a, path_b):
        if not path_a or not path_b:
            return False
        na = self._davinci_normalize_pool_path(path_a)
        nb = self._davinci_normalize_pool_path(path_b)
        if na == nb:
            return True
        try:
            pa = os.path.normcase(os.path.normpath(str(path_a).replace("/", os.sep)))
            pb = os.path.normcase(os.path.normpath(str(path_b).replace("/", os.sep)))
            if pa == pb:
                return True
        except (OSError, ValueError, TypeError):
            pass
        try:
            if os.path.isfile(path_a) and os.path.isfile(path_b):
                if os.path.samefile(path_a, path_b):
                    return True
        except (OSError, ValueError, TypeError):
            pass
        return False

    def _davinci_enumerate_all_pool_clips(self, media_pool):
        clips_out = []
        seen_clip_ids = set()
        try:
            root = media_pool.GetRootFolder()
        except Exception:
            root = None
        if not root:
            return clips_out
        stack = [root]
        seen_folders = set()
        while stack:
            folder = stack.pop()
            fid = id(folder)
            if fid in seen_folders:
                continue
            seen_folders.add(fid)
            try:
                for c in folder.GetClipList() or []:
                    if c and id(c) not in seen_clip_ids:
                        clips_out.append(c)
                        seen_clip_ids.add(id(c))
            except Exception:
                pass
            try:
                for sub in folder.GetSubFolderList() or []:
                    if sub:
                        stack.append(sub)
            except Exception:
                pass
        return clips_out

    def _davinci_import_media_variants(self, media_pool, video_path):
        """Try dict + string import and path spellings; Resolve is picky on Windows."""
        if not video_path:
            return [], self._tr("No video_path set.", "Kein video_path gesetzt.")
        if not os.path.isfile(video_path):
            return [], f"{self._tr('File not found', 'Datei nicht gefunden')}: {video_path}"
        abs_path = os.path.normpath(os.path.abspath(video_path))
        variants = []
        for p in (abs_path, abs_path.replace("\\", "/"), os.path.normpath(video_path)):
            if p and p not in variants:
                variants.append(p)
        last_err = ""
        for p in variants:
            for use_dict in (True, False):
                try:
                    payload = [{"FilePath": p}] if use_dict else [p]
                    clips = media_pool.ImportMedia(payload)
                    clips = list(clips) if clips else []
                    clips = [c for c in clips if c]
                    if clips:
                        return clips, ""
                except Exception as ex:
                    last_err = str(ex)
        return [], (last_err or self._tr("ImportMedia returned no clips.", "ImportMedia lieferte keine Clips."))

    def _davinci_parse_pixel_dimension(self, raw):
        if raw is None:
            return None
        s = str(raw).strip()
        if not s:
            return None
        try:
            v = int(float(s))
            return v if v > 0 else None
        except ValueError:
            pass
        m = re.search(r"(\d+)\s*[xX×]\s*(\d+)", s)
        if m:
            w, h = int(m.group(1)), int(m.group(2))
            return w if w > 0 else (h if h > 0 else None)
        m = re.search(r"\d+", s)
        if m:
            try:
                v = int(m.group(0))
                return v if v > 0 else None
            except ValueError:
                pass
        return None

    def _davinci_clip_has_video(self, clip):
        if not clip:
            return False
        w = self._davinci_parse_pixel_dimension(clip.GetClipProperty("Image Width"))
        h = self._davinci_parse_pixel_dimension(clip.GetClipProperty("Image Height"))
        if w or h:
            return True
        try:
            vf = clip.GetClipProperty("Video Frame Rate") or clip.GetClipProperty("FPS")
            if vf is not None and str(vf).strip():
                f = float(re.findall(r"[\d.]+", str(vf))[0])
                return f > 0
        except (TypeError, ValueError, IndexError):
            pass
        return False

    def _davinci_pick_target_clip(self, media_pool, source_path_os, imported_clips):
        """Resolve clip for source_path_os: import result, current bin, then whole pool."""
        base = os.path.basename(source_path_os or "").strip().lower()
        path_norm = self._davinci_normalize_pool_path(
            (source_path_os or "").replace("\\", "/")
        )

        def matches_source(clip):
            fp_raw = clip.GetClipProperty("File Path") or ""
            if self._davinci_paths_same_file(fp_raw, source_path_os):
                return True
            fp = self._davinci_normalize_pool_path(fp_raw)
            name = (clip.GetName() or "").strip().lower()
            if fp == path_norm or name == base or fp.endswith("/" + base):
                return True
            return os.path.basename(fp) == base and base != ""

        ordered = []
        seen_ids = set()
        for c in imported_clips or []:
            if c and id(c) not in seen_ids:
                ordered.append(c)
                seen_ids.add(id(c))
        try:
            folder = media_pool.GetCurrentFolder()
        except Exception:
            folder = None
        if folder:
            try:
                for c in folder.GetClipList() or []:
                    if c and id(c) not in seen_ids:
                        ordered.append(c)
                        seen_ids.add(id(c))
            except Exception:
                pass
        for c in self._davinci_enumerate_all_pool_clips(media_pool):
            if c and id(c) not in seen_ids:
                ordered.append(c)
                seen_ids.add(id(c))

        matched = [c for c in ordered if matches_source(c)]
        pool = matched if matched else ordered

        for c in pool:
            if self._davinci_clip_has_video(c):
                return c
        return pool[0] if pool else None

    def _davinci_load_render_preset(self, project, preferred_names):
        tried = []
        for name in preferred_names:
            n = (name or "").strip()
            if not n or n in tried:
                continue
            tried.append(n)
            if project.LoadRenderPreset(n):
                return n, tried
        return None, tried

    def _davinci_track_items_nonempty(self, items):
        if items is None:
            return False
        if isinstance(items, dict):
            return len(items) > 0
        try:
            return len(list(items)) > 0
        except TypeError:
            return bool(items)

    def _davinci_timeline_has_video_clips(self, timeline):
        if not timeline:
            return False
        try:
            n = timeline.GetTrackCount("video") or 0
            for i in range(1, int(n) + 1):
                for getter in (
                    lambda idx=i: timeline.GetItemListInTrack("video", idx),
                    lambda idx=i: timeline.GetItemsInTrack("video", idx),
                ):
                    try:
                        if self._davinci_track_items_nonempty(getter()):
                            return True
                    except Exception:
                        continue
        except Exception:
            pass
        return False

    def _davinci_append_clipinfos_resolve(self, media_pool, batch, strat):
        """Resolve sometimes drops video when one huge AppendToTimeline list is used — append in chunks."""
        if not batch:
            return False
        step = 2 if strat.startswith("paired_") else 1
        for i in range(0, len(batch), step):
            chunk = batch[i : i + step]
            try:
                media_pool.AppendToTimeline(chunk)
            except Exception:
                return False
            time.sleep(0.04)
        return True

    def _davinci_clamp_src_frames_0(self, sf, ef, duration_sec, eff_fps):
        if duration_sec and eff_fps and eff_fps > 0:
            mxf = max(1, int(round(duration_sec * eff_fps)))
            ef = min(int(ef), mxf)
            sf = min(int(sf), max(0, mxf - 1))
            if ef <= sf:
                ef = min(mxf, sf + 1)
        return sf, ef

    def _davinci_clamp_src_frames_1(self, sf, ef, duration_sec, eff_fps):
        if duration_sec and eff_fps and eff_fps > 0:
            mxf = max(1, int(round(duration_sec * eff_fps)))
            sf = max(1, min(int(sf), mxf))
            ef = max(sf, min(int(ef), mxf))
        return sf, ef

    def _davinci_build_segment_clip_batch(self, target_clip, eff_fps, duration_sec, subclips, strat):
        """
        clipInfo batches for AppendToTimeline. Prefer linked A+V (single clipInfo) first; paired V/A last
        (can confuse some builds). eff_fps/duration_sec from ffprobe when possible to avoid wrong trims (black video).
        """
        batch = []
        fps = float(eff_fps) if eff_fps and eff_fps > 0 else 30.0
        if strat == "paired_1based_rec":
            record_frame = 1
            for start_sec, end_sec in subclips:
                sf0 = int(start_sec * fps)
                ef0 = int(end_sec * fps)
                if ef0 <= sf0:
                    continue
                sf = sf0 + 1
                ef = max(sf, ef0)
                sf, ef = self._davinci_clamp_src_frames_1(sf, ef, duration_sec, fps)
                if ef <= sf:
                    continue
                dur = max(1, ef - sf + 1)
                base = {
                    "mediaPoolItem": target_clip,
                    "startFrame": sf,
                    "endFrame": ef,
                    "recordFrame": record_frame,
                    "trackIndex": 1,
                }
                batch.append(dict(base, **{"mediaType": 1}))
                batch.append(dict(base, **{"mediaType": 2}))
                record_frame += dur
        elif strat == "paired_0based_rec":
            record_frame = 1
            for start_sec, end_sec in subclips:
                sf0 = int(start_sec * fps)
                ef0 = int(end_sec * fps)
                if ef0 <= sf0:
                    continue
                sf = sf0
                ef = max(sf0 + 1, ef0)
                sf, ef = self._davinci_clamp_src_frames_0(sf, ef, duration_sec, fps)
                if ef <= sf:
                    continue
                dur = max(1, ef - sf + 1)
                base = {
                    "mediaPoolItem": target_clip,
                    "startFrame": sf,
                    "endFrame": ef,
                    "recordFrame": record_frame,
                    "trackIndex": 1,
                }
                batch.append(dict(base, **{"mediaType": 1}))
                batch.append(dict(base, **{"mediaType": 2}))
                record_frame += dur
        elif strat == "single_0based_norec":
            for start_sec, end_sec in subclips:
                sf0 = int(start_sec * fps)
                ef0 = int(end_sec * fps)
                if ef0 <= sf0:
                    continue
                sf0, ef0 = self._davinci_clamp_src_frames_0(sf0, ef0, duration_sec, fps)
                if ef0 <= sf0:
                    continue
                batch.append({
                    "mediaPoolItem": target_clip,
                    "startFrame": sf0,
                    "endFrame": ef0,
                })
        elif strat == "single_1based_norec":
            for start_sec, end_sec in subclips:
                sf0 = int(start_sec * fps)
                ef0 = int(end_sec * fps)
                if ef0 <= sf0:
                    continue
                sf = sf0 + 1
                ef = max(sf, ef0)
                sf, ef = self._davinci_clamp_src_frames_1(sf, ef, duration_sec, fps)
                if ef <= sf:
                    continue
                batch.append({
                    "mediaPoolItem": target_clip,
                    "startFrame": sf,
                    "endFrame": ef,
                })
        elif strat == "single_0based_rec":
            record_frame = 1
            for start_sec, end_sec in subclips:
                sf0 = int(start_sec * fps)
                ef0 = int(end_sec * fps)
                if ef0 <= sf0:
                    continue
                sf0, ef0 = self._davinci_clamp_src_frames_0(sf0, ef0, duration_sec, fps)
                if ef0 <= sf0:
                    continue
                dur = max(1, ef0 - sf0)
                batch.append({
                    "mediaPoolItem": target_clip,
                    "startFrame": sf0,
                    "endFrame": ef0,
                    "recordFrame": record_frame,
                })
                record_frame += dur
        return batch

    def _davinci_clear_timeline_items(self, timeline):
        if not timeline:
            return
        collected = []
        for tt in ("video", "audio"):
            try:
                nc = timeline.GetTrackCount(tt) or 0
                for idx in range(1, int(nc) + 1):
                    chunk = None
                    try:
                        chunk = timeline.GetItemListInTrack(tt, idx)
                    except Exception:
                        try:
                            chunk = timeline.GetItemsInTrack(tt, idx)
                        except Exception:
                            chunk = None
                    if chunk is None:
                        continue
                    if isinstance(chunk, dict):
                        collected.extend(chunk.values())
                    else:
                        try:
                            collected.extend(list(chunk))
                        except TypeError:
                            pass
            except Exception:
                continue
        if not collected:
            return
        try:
            timeline.DeleteClips(collected, False)
        except Exception:
            for it in collected:
                try:
                    it.Delete()
                except Exception:
                    pass
        time.sleep(0.25)

    def _davinci_append_segments_with_strategies(
        self, media_pool, project, target_clip, eff_fps, duration_sec, subclips, time_suffix
    ):
        """
        One timeline only; clear between strategies (avoids many Autocut_* timelines / duplicate imports feeling).
        Try linked clip append before splitting A/V.
        """
        strategies = [
            "single_0based_norec",
            "single_1based_norec",
            "single_0based_rec",
            "paired_0based_rec",
            "paired_1based_rec",
        ]
        timeline_name = f"Autocut_{time_suffix}"
        timeline = media_pool.CreateEmptyTimeline(timeline_name)
        if not timeline:
            return False, None
        project.SetCurrentTimeline(timeline)

        for strat in strategies:
            self._davinci_clear_timeline_items(project.GetCurrentTimeline())
            batch = self._davinci_build_segment_clip_batch(
                target_clip, eff_fps, duration_sec, subclips, strat
            )
            if not batch:
                continue
            ok = self._davinci_append_clipinfos_resolve(media_pool, batch, strat)
            if not ok:
                try:
                    media_pool.AppendToTimeline(batch)
                except Exception:
                    continue
            time.sleep(0.45)
            tl = project.GetCurrentTimeline()
            if self._davinci_timeline_has_video_clips(tl):
                return True, timeline_name
        self._davinci_clear_timeline_items(project.GetCurrentTimeline())
        return False, timeline_name

    def _davinci_apply_render_output_settings(self, project, target_clip, video_path):
        """AddRenderJob often fails without TargetDir (and sometimes without SelectAllFrames)."""
        target_dir = os.path.dirname(os.path.abspath(video_path or ""))
        if not target_dir or not os.path.isdir(target_dir):
            target_dir = tempfile.gettempdir()
        stem = os.path.splitext(os.path.basename(video_path or "autocut"))[0] or "autocut"
        custom_name = stem + "_autocut"
        settings = {
            "TargetDir": target_dir,
            "CustomName": custom_name,
            "SelectAllFrames": True,
        }
        pw = self._davinci_parse_pixel_dimension(target_clip.GetClipProperty("Image Width"))
        ph = self._davinci_parse_pixel_dimension(target_clip.GetClipProperty("Image Height"))
        if pw and ph:
            settings["FormatWidth"] = int(pw)
            settings["FormatHeight"] = int(ph)
        try:
            project.SetRenderSettings(settings)
        except Exception:
            pass
        return target_dir, custom_name

    def _find_latest_render_mp4(self, target_dir, name_prefix):
        if not target_dir or not os.path.isdir(target_dir):
            return None
        candidates = []
        prefix = (name_prefix or "").lower()
        for fn in os.listdir(target_dir):
            if not fn.lower().endswith(".mp4"):
                continue
            if prefix and not fn.lower().startswith(prefix):
                continue
            full = os.path.join(target_dir, fn)
            try:
                mtime = os.path.getmtime(full)
            except OSError:
                continue
            candidates.append((mtime, full))
        if not candidates and prefix:
            for fn in os.listdir(target_dir):
                if fn.lower().endswith(".mp4"):
                    full = os.path.join(target_dir, fn)
                    try:
                        mtime = os.path.getmtime(full)
                    except OSError:
                        continue
                    candidates.append((mtime, full))
        if not candidates:
            return None
        candidates.sort(key=lambda x: x[0], reverse=True)
        return candidates[0][1]

    def _load_davinci_script_module(self):
        """
        Import DaVinciResolveScript either via normal import or from a user-provided file path.
        """
        custom = (self.davinci_api_path_var.get() if hasattr(self, "davinci_api_path_var") else "").strip()
        if custom:
            if not os.path.exists(custom):
                raise Exception(f"DaVinci API path not found: {custom}")
            import importlib.util
            spec = importlib.util.spec_from_file_location("DaVinciResolveScript", custom)
            if not spec or not spec.loader:
                raise Exception("Could not load DaVinciResolveScript from selected path.")
            mod = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(mod)
            self.ui_settings["davinci_api_path"] = custom
            self._save_ui_settings()
            return mod
        import DaVinciResolveScript as dvr
        return dvr

    def davinci_thread(self):
        # 1. Subclips berechnen (aneinanderhängende behaltene Wörter verschmelzen)
        subclips = self._collect_intervals(keep_value=True)

        # 2. DaVinci API Ausführung
        try:
            time.sleep(2)  # File-Lock Prävention
            dvr = self._load_davinci_script_module()
            resolve = dvr.scriptapp("Resolve")
            if not resolve:
                raise Exception(self._tr("Resolve is not running or API is not reachable.", "Resolve laeuft nicht oder API nicht erreichbar."))

            projectManager = resolve.GetProjectManager()
            project = projectManager.GetCurrentProject()
            if not project:
                raise Exception(self._tr("No active project is open.", "Kein aktives Projekt geoeffnet."))

            mediaPool = project.GetMediaPool()

            # Same media as Tab 1 — never the temp preprocessing WAV (that path is never stored here).
            resolve_path = os.path.normpath(os.path.abspath(self.video_path))
            if not os.path.isfile(resolve_path):
                raise Exception(f"{self._tr('Source file not found', 'Quelldatei nicht gefunden')}: {resolve_path}")

            imported_clips, import_hint = self._davinci_import_media_variants(
                mediaPool, resolve_path
            )
            time.sleep(1.2)

            target_clip = self._davinci_pick_target_clip(
                mediaPool, resolve_path, imported_clips
            )
            self.last_imported_clip = target_clip

            if not target_clip:
                hint = (import_hint or "")[:220]
                raise Exception(
                    self._tr(
                        "Clip not found in Media Pool. Add file manually, then try again. Check path and codec. ",
                        "Clip konnte nicht im Media Pool gefunden werden. Datei manuell in den Pool ziehen und erneut versuchen; Pfad und Codec pruefen. "
                    )
                    + (hint if hint else "")
                )

            resolve_video = self._davinci_clip_has_video(target_clip)
            file_video = self._media_file_has_video_stream(resolve_path)
            if not resolve_video and file_video is True:
                # Resolve often leaves Image Width empty for some codecs; file still has video.
                pass
            elif not resolve_video and file_video is False:
                raise Exception(
                    self._tr(
                        "Source file has no video track (audio only). Please use a video file for DaVinci export.",
                        "Die Quelldatei hat keine Videospur (nur Audio). Transkription aendert die Datei nicht — bitte eine Video-Datei fuer den DaVinci-Export waehlen."
                    )
                )
            elif not resolve_video:
                raise Exception(
                    self._tr(
                        "DaVinci shows no video metadata for this clip (or ffprobe is missing). Check source file and Media Pool folder.",
                        "DaVinci meldet fuer diesen Clip keine Videometadaten (oder ffprobe fehlt). Quelldatei und Media-Pool-Ordner pruefen; ffprobe im PATH verbessert die Erkennung."
                    )
                )

            fps_str = target_clip.GetClipProperty("FPS")
            fps_clip = float(fps_str) if fps_str else 30.0
            dur_probe, fps_probe = self._davinci_probe_video_fps_duration(resolve_path)
            eff_fps = fps_probe if fps_probe and fps_probe > 3.0 else fps_clip
            duration_sec = (
                dur_probe
                if dur_probe and dur_probe > 0
                else self._get_media_duration_seconds(resolve_path)
            )

            if not subclips:
                raise Exception(
                    self._tr(
                        "No keep ranges found. Segments may be too short, or all words were removed. Try lower 'Min segment duration'.",
                        "Keine Zeitbereiche zum Behalten (alle Segmente zu kurz oder alle Woerter entfernt). 'Min segment duration' in Tab 4 z. B. auf 0.05 senken oder Filter pruefen."
                    )
                )

            time_suffix = time.strftime("%Y%m%d_%H%M%S")
            placed, timeline_name = self._davinci_append_segments_with_strategies(
                mediaPool, project, target_clip, eff_fps, duration_sec, subclips, time_suffix
            )
            if not placed or not timeline_name:
                raise Exception(
                    self._tr(
                        "No video track on timeline after all append tries. Check file type, fps, and timeline settings.",
                        "Keine Video-Spur auf der Timeline nach allen Append-Varianten. Der Export nutzt dieselbe Datei wie in Tab 1 (keine temp. Transkriptions-WAV). Framerate fuer Schnitte: ffprobe wenn verfuegbar, sonst Resolve. HDR/Log kann in der Vorschau dunkel wirken. Alte 'Autocut_*'-Timelines kannst du loeschen."
                    )
                )

            srt_note = ""
            if hasattr(self, "export_srt_var") and self.export_srt_var.get() == "1":
                srt_path = os.path.splitext(resolve_path)[0] + "_autocut.srt"
                self._write_srt_file(srt_path)
                srt_note = f" + SRT ({os.path.basename(srt_path)})"

            timeline_only = hasattr(self, "davinci_timeline_only_var") and self.davinci_timeline_only_var.get() == "1"
            if timeline_only:
                if (
                    srt_note
                    and hasattr(self, "embed_srt_davinci_var")
                    and self.embed_srt_davinci_var.get() == "1"
                ):
                    srt_note += " (embed skipped: no render)"
                ok_msg = f"DaVinci timeline created (no render): {timeline_name}{srt_note}."
                self.after(0, lambda m=ok_msg: self.lbl_status.configure(text=m, text_color="lightgreen"))
                return

            user_preset = (self.entry_preset.get() or "").strip()
            preset_used, tried = self._davinci_load_render_preset(
                project,
                [user_preset, "AutocutPreset", "H.265 Master", "YouTube 1080p"],
            )
            if not preset_used:
                raise Exception(
                    self._tr("No render preset loaded. Tried: ", "Kein Render-Preset geladen. Versucht: ")
                    + ", ".join(tried)
                    + self._tr(". Create it in Resolve, or type an existing preset name.", ". Bitte Preset in Resolve anlegen oder Namen im Feld eintragen.")
                )

            target_dir, render_name = self._davinci_apply_render_output_settings(
                project, target_clip, resolve_path
            )

            project.DeleteAllRenderJobs()
            render_job_id = None
            for _attempt in range(8):
                render_job_id = project.AddRenderJob()
                if render_job_id:
                    break
                time.sleep(0.35)
            if not render_job_id:
                raise Exception(
                    self._tr("Could not create render job. Output folder: ", "Render-Job konnte nicht erstellt werden. Ausgabeordner: ")
                    + target_dir
                    + self._tr(". Check Resolve Render Queue, preset, and output folder.", ". In Resolve Deliver / Render Queue pruefen; Preset oder Zielordner anpassen.")
                )
            project.StartRendering()

            timeout = 3600
            start_time = time.time()
            while project.IsRenderingInProgress():
                if time.time() - start_time > timeout:
                    project.StopRendering()
                    raise Exception(self._tr("Render timeout exceeded.", "Render-Timeout ueberschritten."))
                time.sleep(2)

            if (
                srt_note
                and hasattr(self, "embed_srt_davinci_var")
                and self.embed_srt_davinci_var.get() == "1"
            ):
                rendered_mp4 = self._find_latest_render_mp4(target_dir, render_name)
                srt_path = os.path.splitext(resolve_path)[0] + "_autocut.srt"
                if rendered_mp4 and os.path.exists(srt_path):
                    if self._embed_srt_into_mp4(rendered_mp4, srt_path):
                        srt_note += " + embedded subtitle track"

            ok_msg = self._tr(
                f"DaVinci done (Preset: {preset_used}, Timeline: {timeline_name}){srt_note}.",
                f"DaVinci fertig (Preset: {preset_used}, Timeline: {timeline_name}){srt_note}."
            )
            self.after(0, lambda m=ok_msg: self.lbl_status.configure(text=m, text_color="lightgreen"))

        except Exception as e:
            err_msg = str(e)

            def _report_err(m=err_msg):
                self.lbl_status.configure(text=f"{self._tr('DaVinci error', 'DaVinci Fehler')}: {m}", text_color="red")
                messagebox.showerror("DaVinci Resolve", m)

            self.after(0, _report_err)

if __name__ == "__main__":
    app = TranskriptionApp()
    app.mainloop()