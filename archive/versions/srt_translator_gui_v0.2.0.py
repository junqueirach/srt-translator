#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════╗
║           SRT SUBTITLE TRANSLATOR — Desktop GUI           ║
║                                                           ║
║  A polished desktop application for translating .srt      ║
║  subtitle files with structure preservation.              ║
║                                                           ║
║  Engines:                                                 ║
║    • Claude API  (recommended — nuanced, context-aware)   ║
║    • MyMemory    (free — no API key, more literal)        ║
║                                                           ║
║  Requirements:                                            ║
║    pip install requests                                   ║
║                                                           ║
║  Run:                                                     ║
║    python srt_translator_gui.py                           ║
╚═══════════════════════════════════════════════════════════╝
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import re
import time
import os
import json
from pathlib import Path

try:
    import requests

except ImportError:
    import subprocess, sys
    subprocess.check_call([sys.executable, "-m", "pip", "install", "requests"])
    import requests


# ═══════════════════════════════════════════════════════════════════════
# PERSISTENT CONFIG
# ═══════════════════════════════════════════════════════════════════════

CONFIG_PATH = Path.home() / ".srt_translator_config.json"

def load_config() -> dict:
    """Load saved settings from disk."""
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_config(data: dict):
    """Persist settings to disk."""
    try:
        existing = load_config()
        existing.update(data)
        with open(CONFIG_PATH, 'w', encoding='utf-8') as f:
            json.dump(existing, f, indent=2)
    except Exception:
        pass



# ═══════════════════════════════════════════════════════════════════════
# THEME & COLORS
# ═══════════════════════════════════════════════════════════════════════

COLORS = {
    "bg_dark":      "#0d1117",
    "bg_mid":       "#161b22",
    "bg_card":      "#1c2333",
    "bg_input":     "#0d1117",
    "border":       "#30363d",
    "border_focus": "#58a6ff",
    "text":         "#c9d1d9",
    "text_dim":     "#8b949e",
    "text_bright":  "#f0f6fc",
    "accent":       "#58a6ff",
    "accent2":      "#bc8cff",
    "success":      "#3fb950",
    "warning":      "#d29922",
    "error":        "#f85149",
    "btn_primary":  "#238636",
    "btn_hover":    "#2ea043",
    "btn_danger":   "#da3633",
}

FONTS = {
    "title":    ("Segoe UI", 18, "bold"),
    "heading":  ("Segoe UI", 13, "bold"),
    "body":     ("Segoe UI", 11),
    "small":    ("Segoe UI", 10),
    "tiny":     ("Segoe UI", 9),
    "mono":     ("Consolas", 10),
    "mono_sm":  ("Consolas", 9),
    "badge":    ("Segoe UI", 8, "bold"),
}


# ═══════════════════════════════════════════════════════════════════════
# SRT PARSER & WRITER
# ═══════════════════════════════════════════════════════════════════════

def parse_srt(filepath: str) -> list:
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        content = f.read()
    blocks = []
    raw = re.split(r'\r?\n\r?\n+', content.strip())
    for rb in raw:
        lines = rb.strip().split('\n')
        lines = [l.strip() for l in lines]
        if len(lines) >= 3 and '-->' in lines[1]:
            blocks.append({
                'id': lines[0],
                'timestamp': lines[1],
                'text_lines': lines[2:],
            })
    return blocks


def write_srt(blocks: list, filepath: str):
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\ufeff')
        for block in blocks:
            f.write(f"{block['id']}\r\n")
            f.write(f"{block['timestamp']}\r\n")
            for line in block['text_lines']:
                f.write(f"{line}\r\n")
            f.write('\r\n')


def detect_language(blocks: list) -> str:
    sample = ' '.join(
        ' '.join(b['text_lines']) for b in blocks[:30]
    ).lower()
    patterns = [
        ("English",    r"\b(the|and|is|are|you|have|what|this|that|with|for|not|but|they|was|will|would|could|can|how|who|where|when|why)\b"),
        ("Portuguese", r"\b(que|não|uma|com|para|está|isso|como|mas|mais|ele|ela|você|tem|são|muito|pode|então|também|fazer|quando)\b"),
        ("Spanish",    r"\b(que|los|las|una|por|con|para|está|esto|como|pero|más|tiene|son|muy|puede|también|hacer|cuando)\b"),
        ("French",     r"\b(les|des|une|que|est|pas|pour|dans|avec|qui|sur|sont|mais|plus|tout|peut|cette|aussi|faire|comme)\b"),
        ("German",     r"\b(und|der|die|das|ist|nicht|ein|eine|ich|sie|wir|auf|mit|den|von|hat|für|sind|auch|aber|oder|wenn)\b"),
        ("Italian",    r"\b(che|non|una|per|sono|con|come|più|questo|anche|della|quello|hanno|essere|fare|tutto)\b"),
        ("Japanese",   r"[\u3040-\u309f\u30a0-\u30ff\u4e00-\u9fff]"),
        ("Korean",     r"[\uac00-\ud7af]"),
        ("Chinese",    r"[\u4e00-\u9fff]{3,}"),
    ]
    best = ("Unknown", 0)
    for lang, pattern in patterns:
        count = len(re.findall(pattern, sample))
        if count > best[1]:
            best = (lang, count)
    return best[0]


# ═══════════════════════════════════════════════════════════════════════
# TRANSLATION ENGINES
# ═══════════════════════════════════════════════════════════════════════

def translate_claude(text_lines, source_lang, target_lang, api_key, context="", model="claude-haiku-4-5-20251001"):
    line_count = len(text_lines)
    joined = '\n'.join(text_lines)

    system_prompt = f"""You are a professional subtitle translator. Translate the following subtitle text from {source_lang} to {target_lang}.

CRITICAL RULES:
- The input has exactly {line_count} line(s). Your output MUST have exactly {line_count} line(s).
- Each line in your output corresponds to the same line in the input.
- Preserve tone, humor, slang, interjections, and emphasis.
- Use natural, idiomatic language for the target locale.
- Character names and proper nouns stay unchanged.
- Do NOT add quotes, numbering, labels, or formatting — output ONLY the translated lines.
- If a line is a sound effect in brackets like [gunshot], translate the description inside the brackets.
- If a line is just punctuation or a name, keep it as-is.
{f'Context from surrounding dialogue: {context}' if context else ''}"""

    headers = {
        'Content-Type': 'application/json',
        'x-api-key': api_key.strip(),
        'anthropic-version': '2023-06-01',
    }
    payload = {
        'model': model,
        'max_tokens': 1024,
        'system': system_prompt,
        'messages': [{'role': 'user', 'content': joined}],
    }

    resp = requests.post(
        'https://api.anthropic.com/v1/messages',
        headers=headers, json=payload, timeout=60,
    )
    if not resp.ok:
        try:
            err_body = resp.json()
            err_msg = err_body.get('error', {}).get('message', resp.text)
        except Exception:
            err_msg = resp.text
        raise RuntimeError(f"HTTP {resp.status_code}: {err_msg}")
    data = resp.json()
    translated = data['content'][0]['text'].strip().split('\n')

    if len(translated) == line_count:
        return translated
    if len(translated) > line_count:
        return translated[:line_count]
    while len(translated) < line_count:
        translated.append('')
    return translated


def translate_free(text_lines, source_lang, target_lang):
    lang_map = {
        'pt-BR': 'pt', 'es-ES': 'es', 'es-LATAM': 'es', 'en-US': 'en',
        'en-GB': 'en', 'de-DE': 'de', 'fr-FR': 'fr', 'it-IT': 'it',
        'ja-JP': 'ja', 'ko-KR': 'ko', 'zh-CN': 'zh-CN',
    }
    src = lang_map.get(source_lang, source_lang.split('-')[0].lower()[:2])
    tgt = lang_map.get(target_lang, target_lang.split('-')[0].lower()[:2])

    results = []
    for line in text_lines:
        if not line.strip() or re.match(r'^[^\w\s]*$', line):
            results.append(line)
            continue
        try:
            url = f"https://api.mymemory.translated.net/get?q={requests.utils.quote(line)}&langpair={src}|{tgt}"
            r = requests.get(url, timeout=10)
            data = r.json()
            if data.get('responseStatus') == 200:
                results.append(data['responseData']['translatedText'])
            else:
                results.append(line)
        except Exception:
            results.append(line)
    return results


# ═══════════════════════════════════════════════════════════════════════
# MAIN GUI APPLICATION
# ═══════════════════════════════════════════════════════════════════════

LANGUAGES = [
    ("pt-BR",    "Portuguese — Brazilian",  "🇧🇷"),
    ("es-ES",    "Spanish — European",      "🇪🇸"),
    ("es-LATAM", "Spanish — Latin American", "🇲🇽"),
    ("en-US",    "English — US",            "🇺🇸"),
    ("en-GB",    "English — UK",            "🇬🇧"),
    ("de-DE",    "German",                  "🇩🇪"),
    ("fr-FR",    "French",                  "🇫🇷"),
    ("it-IT",    "Italian",                 "🇮🇹"),
    ("ja-JP",    "Japanese",                "🇯🇵"),
    ("ko-KR",    "Korean",                  "🇰🇷"),
    ("zh-CN",    "Chinese — Simplified",    "🇨🇳"),
]


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SRT Subtitle Translator")
        self.geometry("980x740")
        self.minsize(820, 620)
        self.configure(bg=COLORS["bg_dark"])
        self.resizable(True, True)

        # State
        self.source_blocks = []
        self.translated_blocks = []
        self.input_path = ""
        self.output_path = ""
        self.detected_lang = tk.StringVar(value="")
        self.source_lang = tk.StringVar(value="English")
        self.target_lang = tk.StringVar(value="pt-BR")
        self.engine = tk.StringVar(value="claude")
        _cfg = load_config()
        self.api_key = tk.StringVar(
            value=_cfg.get('api_key') or os.environ.get('ANTHROPIC_API_KEY', ''))
        self.claude_model = tk.StringVar(
            value=_cfg.get('claude_model', 'claude-haiku-4-5-20251001'))
        self.target_lang.set(_cfg.get('target_lang', 'pt-BR'))
        self.engine.set(_cfg.get('engine', 'claude'))
        self.show_key = tk.BooleanVar(value=False)
        self.is_translating = False
        self.cancel_flag = False
        self.progress_var = tk.DoubleVar(value=0)
        self.status_text = tk.StringVar(value="Ready")

        self._build_ui()
        self.protocol('WM_DELETE_WINDOW', self._on_close)

    # ─── UI Construction ─────────────────────────────────────────────

    def _on_close(self):
        """Save settings then exit."""
        save_config({
            'api_key':      self.api_key.get().strip(),
            'claude_model': self.claude_model.get(),
            'target_lang':  self.target_lang.get(),
            'engine':       self.engine.get(),
        })
        self.destroy()

    def _build_ui(self):
        # Header
        header = tk.Frame(self, bg=COLORS["bg_mid"], height=56)
        header.pack(fill="x")
        header.pack_propagate(False)

        tk.Label(
            header, text="◈  SRT Subtitle Translator",
            font=FONTS["title"], fg=COLORS["accent"], bg=COLORS["bg_mid"],
            padx=20,
        ).pack(side="left", pady=10)

        tk.Label(
            header, text="Structure-preserving subtitle translation",
            font=FONTS["small"], fg=COLORS["text_dim"], bg=COLORS["bg_mid"],
        ).pack(side="left", padx=(0, 20), pady=10)

        # Main area: left panel (config) + right panel (preview/log)
        body = tk.Frame(self, bg=COLORS["bg_dark"])
        body.pack(fill="both", expand=True, padx=16, pady=12)

        # LEFT: Configuration
        left = tk.Frame(body, bg=COLORS["bg_card"], width=380,
                        highlightbackground=COLORS["border"], highlightthickness=1)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)
        left.configure(width=400)
        self._build_left_panel(left)

        # RIGHT: Preview + Log
        right = tk.Frame(body, bg=COLORS["bg_dark"])
        right.pack(side="left", fill="both", expand=True)
        self._build_right_panel(right)

        # Footer: progress bar + status
        footer = tk.Frame(self, bg=COLORS["bg_mid"], height=42)
        footer.pack(fill="x", side="bottom")
        footer.pack_propagate(False)
        self._build_footer(footer)

    def _build_left_panel(self, parent):
        canvas = tk.Canvas(parent, bg=COLORS["bg_card"], highlightthickness=0)
        scrollbar = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        scroll_frame = tk.Frame(canvas, bg=COLORS["bg_card"])

        scroll_frame.bind(
            "<Configure>",
            lambda e: canvas.configure(scrollregion=canvas.bbox("all"))
        )
        canvas.create_window((0, 0), window=scroll_frame, anchor="nw", width=380)
        canvas.configure(yscrollcommand=scrollbar.set)

        scrollbar.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)

        # Enable mousewheel scrolling
        def _on_mousewheel(event):
            canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")
        canvas.bind_all("<MouseWheel>", _on_mousewheel)

        pad = {"padx": 16}
        f = scroll_frame

        # ── Section 1: File ──
        self._section_header(f, "01", "SOURCE FILE")

        file_frame = tk.Frame(f, bg=COLORS["bg_card"])
        file_frame.pack(fill="x", **pad)

        self.file_label = tk.Label(
            file_frame, text="No file selected",
            font=FONTS["small"], fg=COLORS["text_dim"], bg=COLORS["bg_card"],
            anchor="w",
        )
        self.file_label.pack(side="left", fill="x", expand=True)

        btn_browse = tk.Button(
            file_frame, text="Browse…", font=FONTS["small"],
            bg=COLORS["bg_input"], fg=COLORS["text"], relief="flat",
            activebackground=COLORS["border"], activeforeground=COLORS["text_bright"],
            cursor="hand2", padx=14, pady=4,
            command=self._browse_file,
        )
        btn_browse.pack(side="right", padx=(8, 0))

        self.file_info = tk.Label(
            f, text="", font=FONTS["tiny"], fg=COLORS["text_dim"],
            bg=COLORS["bg_card"], anchor="w",
        )
        self.file_info.pack(fill="x", **pad, pady=(4, 12))

        # ── Section 2: Source Language ──
        self._section_header(f, "02", "SOURCE LANGUAGE")

        src_frame = tk.Frame(f, bg=COLORS["bg_card"])
        src_frame.pack(fill="x", **pad, pady=(0, 12))

        self.src_entry = tk.Entry(
            src_frame, textvariable=self.source_lang,
            font=FONTS["body"], bg=COLORS["bg_input"], fg=COLORS["text"],
            insertbackground=COLORS["text"], relief="flat",
            highlightbackground=COLORS["border"], highlightthickness=1,
            highlightcolor=COLORS["border_focus"],
        )
        self.src_entry.pack(fill="x", ipady=6)

        tk.Label(
            f, text="Auto-detected from file. Edit if incorrect.",
            font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w",
        ).pack(fill="x", **pad, pady=(0, 12))

        # ── Section 3: Target Language ──
        self._section_header(f, "03", "TARGET LANGUAGE")

        self.lang_frame = tk.Frame(f, bg=COLORS["bg_card"])
        self.lang_frame.pack(fill="x", **pad, pady=(0, 12))
        self._build_language_buttons()

        # ── Section 4: Engine ──
        self._section_header(f, "04", "TRANSLATION ENGINE")

        eng_frame = tk.Frame(f, bg=COLORS["bg_card"])
        eng_frame.pack(fill="x", **pad, pady=(0, 4))

        self._engine_button(eng_frame, "claude", "Claude API",
                            "RECOMMENDED", COLORS["success"],
                            "Best quality — tone, humor, cultural nuances")
        self._engine_button(eng_frame, "free", "MyMemory",
                            "FREE", COLORS["accent2"],
                            "No API key needed — literal, less nuanced")

        # API Key
        self.key_frame = tk.Frame(f, bg=COLORS["bg_card"])
        self.key_frame.pack(fill="x", **pad, pady=(4, 4))

        tk.Label(
            self.key_frame, text="Claude API Key",
            font=FONTS["small"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w",
        ).pack(fill="x")

        key_row = tk.Frame(self.key_frame, bg=COLORS["bg_card"])
        key_row.pack(fill="x", pady=(4, 0))

        self.key_entry = tk.Entry(
            key_row, textvariable=self.api_key, show="•",
            font=FONTS["mono_sm"], bg=COLORS["bg_input"], fg=COLORS["text"],
            insertbackground=COLORS["text"], relief="flat",
            highlightbackground=COLORS["border"], highlightthickness=1,
            highlightcolor=COLORS["border_focus"],
        )
        self.key_entry.pack(side="left", fill="x", expand=True, ipady=5)

        self.eye_btn = tk.Button(
            key_row, text="👁", font=FONTS["small"],
            bg=COLORS["bg_input"], fg=COLORS["text_dim"], relief="flat",
            cursor="hand2", width=3,
            command=self._toggle_key_visibility,
        )
        self.eye_btn.pack(side="right", padx=(4, 0))

        tk.Label(
            self.key_frame, text="Or set ANTHROPIC_API_KEY env variable",
            font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w",
        ).pack(fill="x", pady=(4, 0))

        # Model selector
        tk.Label(
            self.key_frame, text="Claude Model",
            font=FONTS["small"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w",
        ).pack(fill="x", pady=(8, 0))
        model_row = tk.Frame(self.key_frame, bg=COLORS["bg_card"])
        model_row.pack(fill="x", pady=(4, 0))
        CLAUDE_MODELS = [
            ("claude-haiku-4-5-20251001",  "Haiku 4.5  — Fast & cheap"),
            ("claude-sonnet-4-5-20250929", "Sonnet 4.5 — Best quality"),
            ("claude-sonnet-4-20250514",   "Sonnet 4   — Older, stable"),
        ]
        for val, lbl in CLAUDE_MODELS:
            tk.Radiobutton(
                model_row, text=lbl, variable=self.claude_model, value=val,
                font=FONTS["tiny"], fg=COLORS["text"], bg=COLORS["bg_card"],
                selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_card"],
                anchor="w",
            ).pack(fill="x")

        self.engine.trace_add("write", self._on_engine_change)
        self._on_engine_change()

        # ── Action Buttons ──
        spacer = tk.Frame(f, bg=COLORS["bg_card"], height=12)
        spacer.pack(fill="x")

        btn_frame = tk.Frame(f, bg=COLORS["bg_card"])
        btn_frame.pack(fill="x", **pad, pady=(0, 16))

        self.start_btn = tk.Button(
            btn_frame, text="▶  Start Translation", font=FONTS["heading"],
            bg=COLORS["btn_primary"], fg="#ffffff", relief="flat",
            activebackground=COLORS["btn_hover"], activeforeground="#ffffff",
            cursor="hand2", pady=10,
            command=self._start_translation,
        )
        self.start_btn.pack(fill="x", pady=(0, 6))

        self.cancel_btn = tk.Button(
            btn_frame, text="✕  Cancel", font=FONTS["body"],
            bg=COLORS["btn_danger"], fg="#ffffff", relief="flat",
            cursor="hand2", pady=6, state="disabled",
            command=self._cancel_translation,
        )
        self.cancel_btn.pack(fill="x")

    def _build_right_panel(self, parent):
        # Notebook with tabs: Preview / Comparison / Log
        style = ttk.Style()
        style.theme_use('default')
        style.configure("Custom.TNotebook", background=COLORS["bg_dark"],
                        borderwidth=0)
        style.configure("Custom.TNotebook.Tab",
                        background=COLORS["bg_mid"], foreground=COLORS["text_dim"],
                        padding=[16, 8], font=FONTS["small"],
                        borderwidth=0)
        style.map("Custom.TNotebook.Tab",
                   background=[("selected", COLORS["bg_card"])],
                   foreground=[("selected", COLORS["text_bright"])])

        self.notebook = ttk.Notebook(parent, style="Custom.TNotebook")
        self.notebook.pack(fill="both", expand=True)

        # Tab 1: Source Preview
        tab_preview = tk.Frame(self.notebook, bg=COLORS["bg_card"])
        self.notebook.add(tab_preview, text="  Source Preview  ")
        self.preview_text = scrolledtext.ScrolledText(
            tab_preview, font=FONTS["mono_sm"],
            bg=COLORS["bg_card"], fg=COLORS["text"],
            insertbackground=COLORS["text"],
            selectbackground=COLORS["accent"],
            relief="flat", state="disabled", wrap="word",
            highlightthickness=0,
        )
        self.preview_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.preview_text.tag_configure("id", foreground=COLORS["accent"], font=("Consolas", 10, "bold"))
        self.preview_text.tag_configure("ts", foreground=COLORS["text_dim"], font=("Consolas", 9))
        self.preview_text.tag_configure("txt", foreground=COLORS["text"])

        # Tab 2: Side-by-Side Comparison
        tab_compare = tk.Frame(self.notebook, bg=COLORS["bg_card"])
        self.notebook.add(tab_compare, text="  Comparison  ")

        compare_header = tk.Frame(tab_compare, bg=COLORS["bg_card"])
        compare_header.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(compare_header, text="ORIGINAL", font=FONTS["badge"],
                 fg=COLORS["text_dim"], bg=COLORS["bg_card"]).pack(side="left", expand=True)
        tk.Label(compare_header, text="TRANSLATED", font=FONTS["badge"],
                 fg=COLORS["success"], bg=COLORS["bg_card"]).pack(side="right", expand=True)

        compare_body = tk.Frame(tab_compare, bg=COLORS["bg_card"])
        compare_body.pack(fill="both", expand=True, padx=8, pady=(0, 8))

        self.compare_orig = scrolledtext.ScrolledText(
            compare_body, font=FONTS["mono_sm"],
            bg=COLORS["bg_input"], fg=COLORS["text"],
            relief="flat", state="disabled", wrap="word",
            highlightthickness=0, width=40,
        )
        self.compare_orig.pack(side="left", fill="both", expand=True, padx=(0, 4))

        self.compare_trans = scrolledtext.ScrolledText(
            compare_body, font=FONTS["mono_sm"],
            bg=COLORS["bg_input"], fg=COLORS["success"],
            relief="flat", state="disabled", wrap="word",
            highlightthickness=0, width=40,
        )
        self.compare_trans.pack(side="right", fill="both", expand=True, padx=(4, 0))

        # Sync scrolling
        def sync_scroll(*args):
            self.compare_orig.yview(*args)
            self.compare_trans.yview(*args)

        self.compare_orig.configure(yscrollcommand=lambda *a: None)
        self.compare_trans.configure(yscrollcommand=lambda *a: None)

        # Tab 3: Activity Log
        tab_log = tk.Frame(self.notebook, bg=COLORS["bg_card"])
        self.notebook.add(tab_log, text="  Activity Log  ")
        self.log_text = scrolledtext.ScrolledText(
            tab_log, font=FONTS["mono_sm"],
            bg=COLORS["bg_card"], fg=COLORS["text_dim"],
            insertbackground=COLORS["text"],
            relief="flat", state="disabled", wrap="word",
            highlightthickness=0,
        )
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.log_text.tag_configure("info", foreground=COLORS["text_dim"])
        self.log_text.tag_configure("success", foreground=COLORS["success"])
        self.log_text.tag_configure("warn", foreground=COLORS["warning"])
        self.log_text.tag_configure("error", foreground=COLORS["error"])
        self.log_text.tag_configure("accent", foreground=COLORS["accent"])

    def _build_footer(self, parent):
        # Progress bar
        style = ttk.Style()
        style.configure("Custom.Horizontal.TProgressbar",
                        troughcolor=COLORS["bg_dark"],
                        background=COLORS["accent"],
                        borderwidth=0, thickness=6)

        self.progress_bar = ttk.Progressbar(
            parent, variable=self.progress_var,
            maximum=100, style="Custom.Horizontal.TProgressbar",
        )
        self.progress_bar.pack(fill="x", padx=16, pady=(8, 0))

        status_row = tk.Frame(parent, bg=COLORS["bg_mid"])
        status_row.pack(fill="x", padx=16)

        self.status_label = tk.Label(
            status_row, textvariable=self.status_text,
            font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["bg_mid"],
            anchor="w",
        )
        self.status_label.pack(side="left")

        self.pct_label = tk.Label(
            status_row, text="",
            font=FONTS["tiny"], fg=COLORS["accent"], bg=COLORS["bg_mid"],
            anchor="e",
        )
        self.pct_label.pack(side="right")

    # ─── Widget Helpers ──────────────────────────────────────────────

    def _section_header(self, parent, number, title):
        frame = tk.Frame(parent, bg=COLORS["bg_card"])
        frame.pack(fill="x", padx=16, pady=(14, 6))

        num_label = tk.Label(
            frame, text=number, font=FONTS["badge"],
            fg=COLORS["accent"], bg="#1a2744",
            padx=6, pady=1,
        )
        num_label.pack(side="left")

        tk.Label(
            frame, text=f"  {title}", font=FONTS["badge"],
            fg=COLORS["text_dim"], bg=COLORS["bg_card"],
            anchor="w",
        ).pack(side="left")

    def _build_language_buttons(self):
        for widget in self.lang_frame.winfo_children():
            widget.destroy()

        for i, (code, label, flag) in enumerate(LANGUAGES):
            row = i // 2
            col = i % 2
            btn = tk.Button(
                self.lang_frame, text=f" {flag}  {label}",
                font=FONTS["small"], anchor="w", padx=10, pady=5,
                relief="flat", cursor="hand2",
                bg=COLORS["bg_input"] if self.target_lang.get() != code else "#1a2744",
                fg=COLORS["text_dim"] if self.target_lang.get() != code else COLORS["accent"],
                activebackground="#1a2744", activeforeground=COLORS["accent"],
                highlightbackground=COLORS["border"] if self.target_lang.get() != code else COLORS["accent"],
                highlightthickness=1,
                command=lambda c=code: self._select_lang(c),
            )
            btn.grid(row=row, column=col, padx=2, pady=2, sticky="ew")

        self.lang_frame.grid_columnconfigure(0, weight=1)
        self.lang_frame.grid_columnconfigure(1, weight=1)

    def _select_lang(self, code):
        self.target_lang.set(code)
        self._build_language_buttons()

    def _engine_button(self, parent, value, name, badge_text, badge_color, desc):
        is_selected = self.engine.get() == value

        frame = tk.Frame(
            parent, bg=COLORS["bg_input"] if not is_selected else "#1a2744",
            highlightbackground=COLORS["border"] if not is_selected else COLORS["accent"],
            highlightthickness=1, cursor="hand2",
        )
        frame.pack(fill="x", pady=3)

        def select(e=None):
            self.engine.set(value)
            # Rebuild engine buttons
            for w in parent.winfo_children():
                w.destroy()
            self._engine_button(parent, "claude", "Claude API",
                                "RECOMMENDED", COLORS["success"],
                                "Best quality — tone, humor, cultural nuances")
            self._engine_button(parent, "free", "MyMemory",
                                "FREE", COLORS["accent2"],
                                "No API key needed — literal, less nuanced")

        frame.bind("<Button-1>", select)

        top_row = tk.Frame(frame, bg=frame["bg"])
        top_row.pack(fill="x", padx=10, pady=(8, 2))
        top_row.bind("<Button-1>", select)

        rb = tk.Radiobutton(
            top_row, variable=self.engine, value=value,
            bg=frame["bg"], fg=COLORS["text"], selectcolor=COLORS["bg_input"],
            activebackground=frame["bg"],
        )
        rb.pack(side="left")

        name_label = tk.Label(
            top_row, text=name, font=FONTS["body"],
            fg=COLORS["text_bright"] if is_selected else COLORS["text"],
            bg=frame["bg"],
        )
        name_label.pack(side="left")
        name_label.bind("<Button-1>", select)

        badge = tk.Label(
            top_row, text=f" {badge_text} ", font=FONTS["badge"],
            fg="#ffffff", bg=badge_color,
        )
        badge.pack(side="right")
        badge.bind("<Button-1>", select)

        desc_label = tk.Label(
            frame, text=desc, font=FONTS["tiny"],
            fg=COLORS["text_dim"], bg=frame["bg"], anchor="w", wraplength=320,
        )
        desc_label.pack(fill="x", padx=30, pady=(0, 8))
        desc_label.bind("<Button-1>", select)

    def _toggle_key_visibility(self):
        current = self.show_key.get()
        self.show_key.set(not current)
        self.key_entry.configure(show="" if not current else "•")
        self.eye_btn.configure(text="🔒" if not current else "👁")

    def _on_engine_change(self, *args):
        if self.engine.get() == "claude":
            self.key_frame.pack(fill="x", padx=16, pady=(4, 4))
        else:
            self.key_frame.pack_forget()

    # ─── File Handling ───────────────────────────────────────────────

    def _browse_file(self):
        path = filedialog.askopenfilename(
            title="Select SRT subtitle file",
            filetypes=[("SRT files", "*.srt"), ("All files", "*.*")],
        )
        if not path:
            return

        try:
            self.source_blocks = parse_srt(path)
        except Exception as e:
            messagebox.showerror("Parse Error", f"Could not parse file:\n{e}")
            return

        if not self.source_blocks:
            messagebox.showwarning("Empty File", "No subtitle blocks found in this file.")
            return

        self.input_path = path
        name = Path(path).stem
        self.file_label.configure(text=name + ".srt", fg=COLORS["text_bright"])
        self.file_info.configure(
            text=f"{len(self.source_blocks):,} blocks  •  "
                 f"IDs {self.source_blocks[0]['id']}–{self.source_blocks[-1]['id']}"
        )

        lang = detect_language(self.source_blocks)
        self.detected_lang.set(lang)
        self.source_lang.set(lang)

        self._log(f"Loaded: {name}.srt — {len(self.source_blocks):,} blocks", "accent")
        self._log(f"Detected language: {lang}", "info")
        self._show_preview()

    def _show_preview(self):
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")

        for b in self.source_blocks[:50]:
            self.preview_text.insert("end", f"{b['id']}\n", "id")
            self.preview_text.insert("end", f"{b['timestamp']}\n", "ts")
            for line in b['text_lines']:
                self.preview_text.insert("end", f"{line}\n", "txt")
            self.preview_text.insert("end", "\n")

        if len(self.source_blocks) > 50:
            self.preview_text.insert("end", f"\n... and {len(self.source_blocks) - 50:,} more blocks\n", "ts")

        self.preview_text.configure(state="disabled")

    # ─── Translation ─────────────────────────────────────────────────

    def _start_translation(self):
        if not self.source_blocks:
            messagebox.showwarning("No File", "Please load an SRT file first.")
            return

        if self.engine.get() == "claude" and not self.api_key.get().strip():
            messagebox.showwarning("API Key", "Please enter your Claude API key.")
            return

        # Ask for output path
        default_name = Path(self.input_path).stem + f"_{self.target_lang.get()}.srt"
        output = filedialog.asksaveasfilename(
            title="Save translated file as",
            defaultextension=".srt",
            initialfile=default_name,
            filetypes=[("SRT files", "*.srt")],
        )
        if not output:
            return
        self.output_path = output

        self.is_translating = True
        self.cancel_flag = False
        self.translated_blocks = []
        self.progress_var.set(0)
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.notebook.select(2)  # Switch to log tab

        self._log("═" * 50, "info")
        self._log(f"Starting translation: {self.source_lang.get()} → {self.target_lang.get()}", "accent")
        self._log(f"Engine: {self.claude_model.get() if self.engine.get() == 'claude' else 'MyMemory (Free)'}", "info")
        self._log(f"Blocks: {len(self.source_blocks):,}", "info")
        self._log("═" * 50, "info")

        # Run in thread
        thread = threading.Thread(target=self._translate_worker, daemon=True)
        thread.start()

    def _translate_worker(self):
        blocks = self.source_blocks
        total = len(blocks)
        engine = self.engine.get()
        api_key = self.api_key.get().strip()
        src = self.source_lang.get()
        tgt = self.target_lang.get()
        results = []
        errors = []

        for i, block in enumerate(blocks):
            if self.cancel_flag:
                self._log("Translation cancelled.", "warn")
                break

            # Context
            ctx_before = ' | '.join(' '.join(b['text_lines']) for b in blocks[max(0, i-2):i])
            ctx_after = ' | '.join(' '.join(b['text_lines']) for b in blocks[i+1:min(total, i+3)])
            context = f"Before: {ctx_before}\nAfter: {ctx_after}" if ctx_before or ctx_after else ""

            # Translate with retries
            translated_lines = None
            for attempt in range(3):
                try:
                    if engine == "claude":
                        translated_lines = translate_claude(block['text_lines'], src, tgt, api_key, context, model=self.claude_model.get())
                    else:
                        translated_lines = translate_free(block['text_lines'], src, tgt)
                    break
                except Exception as e:
                    if attempt < 2:
                        wait = 2 ** (attempt + 1)
                        self._log(f"Block {block['id']} attempt {attempt+1} failed: {e}. Retrying in {wait}s...", "warn")
                        time.sleep(wait)
                    else:
                        err = f"Block {block['id']}: {e}"
                        errors.append(err)
                        self._log(f"✗ {err} — keeping original", "error")
                        translated_lines = block['text_lines'][:]

            # Inline verification
            expected = len(block['text_lines'])
            actual = len(translated_lines)
            if actual != expected:
                self._log(f"⚠ Block {block['id']}: line count {actual} → fixed to {expected}", "warn")
                if actual > expected:
                    translated_lines = translated_lines[:expected]
                while len(translated_lines) < expected:
                    translated_lines.append('')

            results.append({
                'id': block['id'],
                'timestamp': block['timestamp'],
                'text_lines': translated_lines,
            })

            # Update progress
            pct = (i + 1) / total * 100
            self.after(0, lambda p=pct: self.progress_var.set(p))
            self.after(0, lambda p=pct, n=i+1: self.status_text.set(
                f"Translating block {n:,}/{total:,}..."
            ))
            self.after(0, lambda p=pct: self.pct_label.configure(text=f"{p:.0f}%"))

            if (i + 1) % 50 == 0:
                self._log(f"  [{pct:5.1f}%] {i+1:,}/{total:,} blocks done", "info")

            # Rate limiting
            if engine == "free" and (i + 1) % 5 == 0:
                time.sleep(1.0)
            elif engine == "claude":
                time.sleep(0.3)  # avoid hammering the API

        self.translated_blocks = results

        if len(results) == total and not self.cancel_flag:
            # Write output
            try:
                write_srt(results, self.output_path)
                self._log(f"\nFile saved: {self.output_path}", "success")
            except Exception as e:
                self._log(f"✗ Failed to write file: {e}", "error")
                self.after(0, self._translation_done)
                return

            # Final verification
            self._log("\n─── VERIFICATION ───", "accent")
            try:
                out_blocks = parse_srt(self.output_path)
                checks = [
                    ("Block count",      len(out_blocks) == total),
                    ("First ID",         out_blocks[0]['id'] == blocks[0]['id']),
                    ("Last ID",          out_blocks[-1]['id'] == blocks[-1]['id']),
                    ("All IDs match",    all(out_blocks[j]['id'] == blocks[j]['id'] for j in range(total))),
                    ("All timestamps",   all(out_blocks[j]['timestamp'] == blocks[j]['timestamp'] for j in range(total))),
                    ("All line counts",  all(len(out_blocks[j]['text_lines']) == len(blocks[j]['text_lines']) for j in range(total))),
                ]
                all_pass = True
                for name, ok in checks:
                    tag = "success" if ok else "error"
                    self._log(f"  {'✓' if ok else '✗'} {name}", tag)
                    if not ok:
                        all_pass = False

                if all_pass:
                    self._log(f"\n✅ SUCCESS — {total:,} blocks translated & verified", "success")
                else:
                    self._log(f"\n⚠ Completed with issues", "warn")
            except Exception as e:
                self._log(f"Verification error: {e}", "error")

            if errors:
                self._log(f"\n{len(errors)} error(s) occurred:", "warn")
                for err in errors[:10]:
                    self._log(f"  • {err}", "warn")

            # Update comparison tab
            self.after(0, self._show_comparison)

        self.after(0, self._translation_done)

    def _translation_done(self):
        self.is_translating = False
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")

        if self.translated_blocks and len(self.translated_blocks) == len(self.source_blocks):
            self.status_text.set(f"Done — {len(self.translated_blocks):,} blocks translated")
            self.notebook.select(1)  # Switch to comparison tab
        elif self.cancel_flag:
            self.status_text.set("Cancelled")
        else:
            self.status_text.set("Completed with errors")

    def _cancel_translation(self):
        self.cancel_flag = True

    def _show_comparison(self):
        self.compare_orig.configure(state="normal")
        self.compare_trans.configure(state="normal")
        self.compare_orig.delete("1.0", "end")
        self.compare_trans.delete("1.0", "end")

        show = min(60, len(self.source_blocks))
        for i in range(show):
            src = self.source_blocks[i]
            out = self.translated_blocks[i] if i < len(self.translated_blocks) else None

            self.compare_orig.insert("end", f"[{src['id']}] {src['timestamp']}\n")
            for line in src['text_lines']:
                self.compare_orig.insert("end", f"  {line}\n")
            self.compare_orig.insert("end", "\n")

            if out:
                self.compare_trans.insert("end", f"[{out['id']}] {out['timestamp']}\n")
                for line in out['text_lines']:
                    self.compare_trans.insert("end", f"  {line}\n")
                self.compare_trans.insert("end", "\n")

        self.compare_orig.configure(state="disabled")
        self.compare_trans.configure(state="disabled")

    # ─── Logging ─────────────────────────────────────────────────────

    def _log(self, message, tag="info"):
        def _insert():
            self.log_text.configure(state="normal")
            ts = time.strftime("%H:%M:%S")
            self.log_text.insert("end", f"[{ts}] {message}\n", tag)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, _insert)


# ═══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = App()
    app.mainloop()
