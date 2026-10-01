#!/usr/bin/env python3
"""
╔═══════════════════════════════════════════════════════════╗
║       SRT Subtitle Translator  v0.4.0 — Desktop GUI       ║
║                                                           ║
║  Structure-preserving subtitle translation for .srt files ║
║  Engines: Claude API · MyMemory (free)                    ║
║  Author:  Luiz Junqueira & Claude AI                      ║
╚═══════════════════════════════════════════════════════════╝
"""

import tkinter as tk
from tkinter import ttk, filedialog, messagebox, scrolledtext
import threading
import concurrent.futures
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
# VERSION
# ═══════════════════════════════════════════════════════════════════════

APP_VERSION = "v0.4.0"
APP_TITLE   = f"SRT Subtitle Translator  {APP_VERSION}"


# ═══════════════════════════════════════════════════════════════════════
# PERSISTENT CONFIG
# ═══════════════════════════════════════════════════════════════════════

CONFIG_PATH = Path.home() / ".srt_translator_config.json"

def load_config() -> dict:
    try:
        if CONFIG_PATH.exists():
            with open(CONFIG_PATH, 'r', encoding='utf-8') as f:
                return json.load(f)
    except Exception:
        pass
    return {}

def save_config(data: dict):
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
    "key_bg":       "#0a1628",
}

FONTS = {
    "title":   ("Segoe UI", 16, "bold"),
    "heading": ("Segoe UI", 13, "bold"),
    "body":    ("Segoe UI", 11),
    "small":   ("Segoe UI", 10),
    "tiny":    ("Segoe UI", 9),
    "mono":    ("Consolas", 10),
    "mono_sm": ("Consolas", 9),
    "badge":   ("Segoe UI", 8, "bold"),
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
    sample = ' '.join(' '.join(b['text_lines']) for b in blocks[:30]).lower()
    patterns = [
        ("English",    r"\b(the|and|is|are|you|have|what|this|that|with|for|not|but|they|was|will|would|could|can|how|who|where|when|why)\b"),
        ("Portuguese", r"\b(que|nao|uma|com|para|esta|isso|como|mas|mais|ele|ela|voce|tem|sao|muito|pode|entao|tambem|fazer|quando)\b"),
        ("Spanish",    r"\b(que|los|las|una|por|con|para|esta|esto|como|pero|mas|tiene|son|muy|puede|tambien|hacer|cuando)\b"),
        ("French",     r"\b(les|des|une|que|est|pas|pour|dans|avec|qui|sur|sont|mais|plus|tout|peut|cette|aussi|faire|comme)\b"),
        ("German",     r"\b(und|der|die|das|ist|nicht|ein|eine|ich|sie|wir|auf|mit|den|von|hat|fur|sind|auch|aber|oder|wenn)\b"),
        ("Italian",    r"\b(che|non|una|per|sono|con|come|piu|questo|anche|della|quello|hanno|essere|fare|tutto)\b"),
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


def suggest_batch_size(blocks: list) -> int:
    """Auto-suggest batch size based on average block text length."""
    if not blocks:
        return 25
    avg = sum(len(' '.join(b['text_lines'])) for b in blocks) / len(blocks)
    if avg < 50:
        return 40
    elif avg < 120:
        return 25
    else:
        return 15


# ═══════════════════════════════════════════════════════════════════════
# TRANSLATION ENGINES
# ═══════════════════════════════════════════════════════════════════════

_SYSTEM_PROMPT_TEMPLATE = (
    "You are a professional subtitle translator. "
    "Translate from {src} to {tgt}. "
    "Rules: preserve tone/humor/slang/names; natural idiomatic {tgt}; "
    "translate [sound effects] inside brackets; keep pure punctuation as-is. "
    "Input: numbered blocks like [1] text. "
    "Output: ONLY the same numbered blocks with translated text. "
    "Exact same block count and numbers. No extra text."
)

_PASSTHROUGH_RE = re.compile(
    r'^([\-\u2013\u2014\.\,\!\?\:\s]*|\[.*?\]|\(.*?\))$'
)

def _is_passthrough(line: str) -> bool:
    s = line.strip()
    return not s or bool(_PASSTHROUGH_RE.match(s))


def _call_claude_api(prompt_text: str, system: str, api_key: str,
                     model: str, max_tokens: int = 2048) -> str:
    headers = {
        "Content-Type": "application/json",
        "x-api-key": api_key.strip(),
        "anthropic-version": "2023-06-01",
    }
    payload = {
        "model": model,
        "max_tokens": max_tokens,
        "system": system,
        "messages": [{"role": "user", "content": prompt_text}],
    }
    resp = requests.post(
        "https://api.anthropic.com/v1/messages",
        headers=headers, json=payload, timeout=90,
    )
    if not resp.ok:
        try:
            err_body = resp.json()
            err_msg = err_body.get("error", {}).get("message", resp.text)
        except Exception:
            err_msg = resp.text
        raise RuntimeError(f"HTTP {resp.status_code}: {err_msg}")
    return resp.json()["content"][0]["text"].strip()


def translate_batch_claude(blocks: list, source_lang: str, target_lang: str,
                           api_key: str, model: str) -> list:
    system = _SYSTEM_PROMPT_TEMPLATE.format(src=source_lang, tgt=target_lang)
    to_translate = []
    results = [None] * len(blocks)

    for i, block in enumerate(blocks):
        needs = [j for j, ln in enumerate(block["text_lines"]) if not _is_passthrough(ln)]
        if not needs:
            results[i] = {**block, "text_lines": block["text_lines"][:]}
        else:
            to_translate.append((i, block, needs))

    if not to_translate:
        return results

    parts = []
    for local_idx, (_, block, needs) in enumerate(to_translate, 1):
        text = "\n".join(block["text_lines"][j] for j in needs)
        parts.append(f"[{local_idx}]\n{text}")
    prompt = "\n\n".join(parts)

    raw = _call_claude_api(prompt, system, api_key, model,
                           max_tokens=max(2048, len(prompt) * 2))

    parsed = {}
    for m in re.finditer(r'\[(\d+)\]\s*(.*?)(?=\[\d+\]|$)', raw, re.DOTALL):
        parsed[int(m.group(1))] = m.group(2).strip().split("\n")

    for local_idx, (global_idx, block, needs) in enumerate(to_translate, 1):
        translated_lines = parsed.get(local_idx, [])
        new_lines = block["text_lines"][:]
        for k, line_idx in enumerate(needs):
            if k < len(translated_lines):
                new_lines[line_idx] = translated_lines[k]
        results[global_idx] = {**block, "text_lines": new_lines}

    return results


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
            results.append(data['responseData']['translatedText']
                           if data.get('responseStatus') == 200 else line)
        except Exception:
            results.append(line)
    return results


# ═══════════════════════════════════════════════════════════════════════
# HELP TEXT
# ═══════════════════════════════════════════════════════════════════════

HELP_TEXT = f"""\
{APP_TITLE}
Structure-preserving subtitle translation for .srt files.

WHAT IT DOES
------------
Loads a .srt subtitle file, translates all dialogue blocks into
the chosen language, and saves a new .srt file with identical
structure: block IDs, timestamps, and line counts are preserved.

TRANSLATION ENGINES
-------------------
Claude API (recommended)
  Uses Anthropic's Claude AI. Requires an API key obtained from
  console.anthropic.com. Understands tone, humor, slang, and
  cultural context. Small cost per file (see estimates below).

  Models:
  Haiku 4.5   Fast, cheap. Recommended for most films.
              Quality is excellent for subtitle content.
  Sonnet 4.5  Higher quality, higher cost. Use for literary
              or very complex dialogue.
  Sonnet 4    Older stable model. Similar to Sonnet 4.5.

MyMemory (free)
  Free translation API, no key required. Output is literal
  and word-for-word. Misses idioms and tone. Good for testing.

API KEY
-------
The key is stored locally in your home folder as
  .srt_translator_config.json
It is never sent anywhere other than api.anthropic.com.
The key field shows only a masked summary (first 7 + last 4
characters) and cannot be accidentally edited in the main UI.
Use the Edit button to open a secure dialog when you need to
update or replace the key.

BATCH SIZE
----------
Number of subtitle blocks sent in a single API call.
Sending multiple blocks together gives the model conversational
context (it sees surrounding dialogue), which improves
translation quality compared to translating one block at a time.

  Conservative (10-15)  For dense narration or documentary
                        files where blocks are long sentences.
  Recommended  (25-40)  Best for standard film and TV files.
  Fast         (50)     Short conversational lines only
                        (average under 30 characters/block).

The app auto-suggests a value when you load a file based on
average line length. You can override it at any time.

PARALLEL WORKERS
----------------
Number of simultaneous API calls. Does not affect quality.
Higher values are faster but use more API rate allowance.

  1   Sequential. Safe for all accounts.
  3   Moderate. Good for standard API tier.
  5   Recommended. Fast without overloading the API.
  8   Use only with a high-rate-limit API plan.

RIGHT-PANEL TABS
----------------
Source Preview   First 50 blocks of the loaded file.
                 Verify the file parsed correctly before starting.
Comparison       Side-by-side view of original vs translated text
                 (first 60 blocks) shown after translation completes.
Activity Log     Real-time log of batch progress, errors, and the
                 final structural verification report.

COST ESTIMATES (Claude API, typical 1,300-block film)
------------------------------------------------------
  Haiku 4.5    approx. $0.01-0.03 per file
  Sonnet 4.5   approx. $0.15-0.25 per file

Actual cost depends on line length. Longer lines cost more.
"""


# ═══════════════════════════════════════════════════════════════════════
# CONSTANTS
# ═══════════════════════════════════════════════════════════════════════

LANGUAGES = [
    ("pt-BR",    "Portuguese — Brazilian",   "🇧🇷"),
    ("es-ES",    "Spanish — European",       "🇪🇸"),
    ("es-LATAM", "Spanish — Latin American", "🇲🇽"),
    ("en-US",    "English — US",             "🇺🇸"),
    ("en-GB",    "English — UK",             "🇬🇧"),
    ("de-DE",    "German",                   "🇩🇪"),
    ("fr-FR",    "French",                   "🇫🇷"),
    ("it-IT",    "Italian",                  "🇮🇹"),
    ("ja-JP",    "Japanese",                 "🇯🇵"),
    ("ko-KR",    "Korean",                   "🇰🇷"),
    ("zh-CN",    "Chinese — Simplified",     "🇨🇳"),
]

CLAUDE_MODELS = [
    ("claude-haiku-4-5-20251001",  "Haiku 4.5  — Fast & cheap (recommended)"),
    ("claude-sonnet-4-5-20250929", "Sonnet 4.5 — Best quality"),
    ("claude-sonnet-4-20250514",   "Sonnet 4   — Older, stable"),
]

BATCH_OPTIONS = [
    (10, "10  — Conservative"),
    (25, "25  — Recommended"),
    (40, "40  — Fast"),
    (50, "50  — Max throughput"),
]

WORKER_OPTIONS = [
    (1, "1  — Safe / sequential"),
    (3, "3  — Moderate"),
    (5, "5  — Recommended"),
    (8, "8  — High-rate plan only"),
]


# ═══════════════════════════════════════════════════════════════════════
# MAIN APP
# ═══════════════════════════════════════════════════════════════════════

class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title(APP_TITLE)
        self.geometry("1020x760")
        self.minsize(860, 640)
        self.configure(bg=COLORS["bg_dark"])
        self.resizable(True, True)

        _cfg = load_config()

        self.source_blocks     = []
        self.translated_blocks = []
        self.input_path        = ""
        self.output_path       = ""
        self.detected_lang     = tk.StringVar(value="")
        self.source_lang       = tk.StringVar(value="English")
        self.target_lang       = tk.StringVar(value=_cfg.get('target_lang', 'pt-BR'))
        self.engine            = tk.StringVar(value=_cfg.get('engine', 'claude'))
        self.claude_model      = tk.StringVar(value=_cfg.get('claude_model', 'claude-haiku-4-5-20251001'))
        self.is_translating    = False
        self.cancel_flag       = False
        self.progress_var      = tk.DoubleVar(value=0)
        self.status_text       = tk.StringVar(value="Ready")
        self.batch_size        = tk.IntVar(value=int(_cfg.get('batch_size', 25)))
        self.workers           = tk.IntVar(value=int(_cfg.get('workers', 5)))

        # API key kept as plain string in memory — NOT bound to a widget StringVar
        self._api_key = _cfg.get('api_key') or os.environ.get('ANTHROPIC_API_KEY', '')

        self._build_ui()
        self.protocol('WM_DELETE_WINDOW', self._on_close)

    # ── Lifecycle ────────────────────────────────────────────────────

    def _on_close(self):
        save_config({
            'api_key':      self._api_key,
            'claude_model': self.claude_model.get(),
            'target_lang':  self.target_lang.get(),
            'engine':       self.engine.get(),
            'batch_size':   self.batch_size.get(),
            'workers':      self.workers.get(),
        })
        self.destroy()

    # ── UI Build ─────────────────────────────────────────────────────

    def _build_ui(self):
        # Header
        hdr = tk.Frame(self, bg=COLORS["bg_mid"], height=52)
        hdr.pack(fill="x")
        hdr.pack_propagate(False)
        tk.Label(hdr, text=f"◈  {APP_TITLE}",
                 font=FONTS["title"], fg=COLORS["accent"], bg=COLORS["bg_mid"],
                 padx=20).pack(side="left", pady=10)
        tk.Button(hdr, text="?  Help", font=FONTS["small"],
                  bg=COLORS["bg_input"], fg=COLORS["text_dim"], relief="flat",
                  activebackground=COLORS["border"], activeforeground=COLORS["text_bright"],
                  cursor="hand2", padx=12, pady=4,
                  command=self._show_help).pack(side="right", padx=16, pady=10)

        # Body
        body = tk.Frame(self, bg=COLORS["bg_dark"])
        body.pack(fill="both", expand=True, padx=16, pady=12)

        left = tk.Frame(body, bg=COLORS["bg_card"], width=430,
                        highlightbackground=COLORS["border"], highlightthickness=1)
        left.pack(side="left", fill="y", padx=(0, 10))
        left.pack_propagate(False)
        self._build_left(left)

        right = tk.Frame(body, bg=COLORS["bg_dark"])
        right.pack(side="left", fill="both", expand=True)
        self._build_right(right)

        # Footer
        ftr = tk.Frame(self, bg=COLORS["bg_mid"], height=42)
        ftr.pack(fill="x", side="bottom")
        ftr.pack_propagate(False)
        self._build_footer(ftr)

    def _build_left(self, parent):
        canvas = tk.Canvas(parent, bg=COLORS["bg_card"], highlightthickness=0)
        sb = ttk.Scrollbar(parent, orient="vertical", command=canvas.yview)
        sf = tk.Frame(canvas, bg=COLORS["bg_card"])
        sf.bind("<Configure>", lambda e: canvas.configure(scrollregion=canvas.bbox("all")))
        canvas.create_window((0, 0), window=sf, anchor="nw", width=420)
        canvas.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y")
        canvas.pack(side="left", fill="both", expand=True)
        canvas.bind_all("<MouseWheel>",
                        lambda e: canvas.yview_scroll(int(-1*(e.delta/120)), "units"))

        p = {"padx": 16}
        f = sf

        # 01 Source file
        self._sec(f, "01", "SOURCE FILE")
        fr = tk.Frame(f, bg=COLORS["bg_card"])
        fr.pack(fill="x", **p)
        self.file_label = tk.Label(fr, text="No file selected",
            font=FONTS["small"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w")
        self.file_label.pack(side="left", fill="x", expand=True)
        tk.Button(fr, text="Browse…", font=FONTS["small"],
            bg=COLORS["bg_input"], fg=COLORS["text"], relief="flat",
            activebackground=COLORS["border"], activeforeground=COLORS["text_bright"],
            cursor="hand2", padx=14, pady=4,
            command=self._browse).pack(side="right", padx=(8, 0))
        self.file_info = tk.Label(f, text="", font=FONTS["tiny"],
            fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w")
        self.file_info.pack(fill="x", **p, pady=(4, 1))
        self.batch_hint = tk.Label(f, text="", font=FONTS["tiny"],
            fg=COLORS["accent"], bg=COLORS["bg_card"], anchor="w")
        self.batch_hint.pack(fill="x", **p, pady=(0, 8))

        # 02 Source language
        self._sec(f, "02", "SOURCE LANGUAGE")
        sf2 = tk.Frame(f, bg=COLORS["bg_card"])
        sf2.pack(fill="x", **p, pady=(0, 2))
        self.src_entry = tk.Entry(sf2, textvariable=self.source_lang,
            font=FONTS["body"], bg=COLORS["bg_input"], fg=COLORS["text"],
            insertbackground=COLORS["text"], relief="flat",
            highlightbackground=COLORS["border"], highlightthickness=1,
            highlightcolor=COLORS["border_focus"])
        self.src_entry.pack(fill="x", ipady=6)
        tk.Label(f, text="Auto-detected from file. Edit if incorrect.",
            font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w"
            ).pack(fill="x", **p, pady=(2, 8))

        # 03 Target language
        self._sec(f, "03", "TARGET LANGUAGE")
        self.lang_frame = tk.Frame(f, bg=COLORS["bg_card"])
        self.lang_frame.pack(fill="x", **p, pady=(0, 8))
        self._build_lang_btns()

        # 04 Engine
        self._sec(f, "04", "TRANSLATION ENGINE")
        eng = tk.Frame(f, bg=COLORS["bg_card"])
        eng.pack(fill="x", **p, pady=(0, 4))
        self._eng_btn(eng, "claude", "Claude API", "RECOMMENDED", COLORS["success"],
                      "Best quality — tone, humor, cultural nuances")
        self._eng_btn(eng, "free",   "MyMemory",  "FREE",        COLORS["accent2"],
                      "No API key — literal, less nuanced")

        # Claude options (hidden when MyMemory selected)
        self.claude_frame = tk.Frame(f, bg=COLORS["bg_card"])
        self.claude_frame.pack(fill="x", **p, pady=(4, 4))
        self._build_claude_options(self.claude_frame)

        self.engine.trace_add("write", self._on_engine_change)
        self._on_engine_change()

        # Action buttons
        tk.Frame(f, bg=COLORS["bg_card"], height=8).pack(fill="x")
        bf = tk.Frame(f, bg=COLORS["bg_card"])
        bf.pack(fill="x", **p, pady=(0, 16))
        self.start_btn = tk.Button(bf, text="▶  Start Translation",
            font=FONTS["heading"], bg=COLORS["btn_primary"], fg="#ffffff", relief="flat",
            activebackground=COLORS["btn_hover"], activeforeground="#ffffff",
            cursor="hand2", pady=10, command=self._start)
        self.start_btn.pack(fill="x", pady=(0, 6))
        self.cancel_btn = tk.Button(bf, text="✕  Cancel",
            font=FONTS["body"], bg=COLORS["btn_danger"], fg="#ffffff", relief="flat",
            cursor="hand2", pady=6, state="disabled", command=self._cancel)
        self.cancel_btn.pack(fill="x")

    def _build_claude_options(self, parent):
        """API key (protected) + model + batch + workers."""
        # ── API Key ──
        tk.Label(parent, text="Claude API Key",
            font=FONTS["small"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w"
            ).pack(fill="x")

        key_row = tk.Frame(parent, bg=COLORS["bg_card"])
        key_row.pack(fill="x", pady=(4, 0))

        self.key_display = tk.Label(key_row,
            text=self._mask_key(self._api_key),
            font=FONTS["mono_sm"], bg=COLORS["key_bg"], fg=COLORS["text_dim"],
            anchor="w", padx=8, pady=5, relief="flat",
            highlightbackground=COLORS["border"], highlightthickness=1,
            cursor="arrow")
        self.key_display.pack(side="left", fill="x", expand=True)

        tk.Button(key_row, text="✎  Edit", font=FONTS["tiny"],
            bg=COLORS["bg_input"], fg=COLORS["text_dim"], relief="flat",
            activebackground=COLORS["border"], activeforeground=COLORS["text_bright"],
            cursor="hand2", padx=10, pady=5,
            command=self._edit_key).pack(side="right", padx=(6, 0))

        tk.Label(parent,
            text="Masked and read-only. Click Edit to update.",
            font=FONTS["tiny"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w"
            ).pack(fill="x", pady=(3, 0))

        # ── Model ──
        tk.Label(parent, text="Claude Model",
            font=FONTS["small"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w"
            ).pack(fill="x", pady=(10, 2))
        for val, lbl in CLAUDE_MODELS:
            tk.Radiobutton(parent, text=lbl, variable=self.claude_model, value=val,
                font=FONTS["tiny"], fg=COLORS["text"], bg=COLORS["bg_card"],
                selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_card"],
                anchor="w").pack(fill="x", padx=4)

        # ── Batch size ──
        tk.Label(parent, text="Batch size  (subtitle blocks per API call)",
            font=FONTS["small"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w"
            ).pack(fill="x", pady=(10, 2))
        for bval, blbl in BATCH_OPTIONS:
            tk.Radiobutton(parent, text=blbl, variable=self.batch_size, value=bval,
                font=FONTS["tiny"], fg=COLORS["text"], bg=COLORS["bg_card"],
                selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_card"],
                anchor="w").pack(fill="x", padx=4)

        # ── Workers ──
        tk.Label(parent, text="Parallel workers  (concurrent API calls)",
            font=FONTS["small"], fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w"
            ).pack(fill="x", pady=(10, 2))
        for wval, wlbl in WORKER_OPTIONS:
            tk.Radiobutton(parent, text=wlbl, variable=self.workers, value=wval,
                font=FONTS["tiny"], fg=COLORS["text"], bg=COLORS["bg_card"],
                selectcolor=COLORS["bg_input"], activebackground=COLORS["bg_card"],
                anchor="w").pack(fill="x", padx=4)

    def _build_right(self, parent):
        sty = ttk.Style()
        sty.theme_use('default')
        sty.configure("T.TNotebook", background=COLORS["bg_dark"], borderwidth=0)
        sty.configure("T.TNotebook.Tab", background=COLORS["bg_mid"],
                      foreground=COLORS["text_dim"], padding=[16, 8],
                      font=FONTS["small"], borderwidth=0)
        sty.map("T.TNotebook.Tab",
                background=[("selected", COLORS["bg_card"])],
                foreground=[("selected", COLORS["text_bright"])])

        nb = ttk.Notebook(parent, style="T.TNotebook")
        nb.pack(fill="both", expand=True)
        self.notebook = nb

        # Tab 1: Preview
        t1 = tk.Frame(nb, bg=COLORS["bg_card"])
        nb.add(t1, text="  Source Preview  ")
        self.preview_text = scrolledtext.ScrolledText(
            t1, font=FONTS["mono_sm"], bg=COLORS["bg_card"], fg=COLORS["text"],
            insertbackground=COLORS["text"], selectbackground=COLORS["accent"],
            relief="flat", state="disabled", wrap="word", highlightthickness=0)
        self.preview_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.preview_text.tag_configure("id",  foreground=COLORS["accent"], font=("Consolas", 10, "bold"))
        self.preview_text.tag_configure("ts",  foreground=COLORS["text_dim"], font=("Consolas", 9))
        self.preview_text.tag_configure("txt", foreground=COLORS["text"])

        # Tab 2: Comparison
        t2 = tk.Frame(nb, bg=COLORS["bg_card"])
        nb.add(t2, text="  Comparison  ")
        ch = tk.Frame(t2, bg=COLORS["bg_card"])
        ch.pack(fill="x", padx=8, pady=(8, 4))
        tk.Label(ch, text="ORIGINAL",   font=FONTS["badge"], fg=COLORS["text_dim"],
                 bg=COLORS["bg_card"]).pack(side="left",  expand=True)
        tk.Label(ch, text="TRANSLATED", font=FONTS["badge"], fg=COLORS["success"],
                 bg=COLORS["bg_card"]).pack(side="right", expand=True)
        cb = tk.Frame(t2, bg=COLORS["bg_card"])
        cb.pack(fill="both", expand=True, padx=8, pady=(0, 8))
        self.compare_orig = scrolledtext.ScrolledText(cb, font=FONTS["mono_sm"],
            bg=COLORS["bg_input"], fg=COLORS["text"], relief="flat",
            state="disabled", wrap="word", highlightthickness=0, width=40)
        self.compare_orig.pack(side="left", fill="both", expand=True, padx=(0, 4))
        self.compare_trans = scrolledtext.ScrolledText(cb, font=FONTS["mono_sm"],
            bg=COLORS["bg_input"], fg=COLORS["success"], relief="flat",
            state="disabled", wrap="word", highlightthickness=0, width=40)
        self.compare_trans.pack(side="right", fill="both", expand=True, padx=(4, 0))
        self.compare_orig.configure(yscrollcommand=lambda *a: None)
        self.compare_trans.configure(yscrollcommand=lambda *a: None)

        # Tab 3: Log
        t3 = tk.Frame(nb, bg=COLORS["bg_card"])
        nb.add(t3, text="  Activity Log  ")
        self.log_text = scrolledtext.ScrolledText(
            t3, font=FONTS["mono_sm"], bg=COLORS["bg_card"], fg=COLORS["text_dim"],
            insertbackground=COLORS["text"], relief="flat",
            state="disabled", wrap="word", highlightthickness=0)
        self.log_text.pack(fill="both", expand=True, padx=8, pady=8)
        self.log_text.tag_configure("info",    foreground=COLORS["text_dim"])
        self.log_text.tag_configure("success", foreground=COLORS["success"])
        self.log_text.tag_configure("warn",    foreground=COLORS["warning"])
        self.log_text.tag_configure("error",   foreground=COLORS["error"])
        self.log_text.tag_configure("accent",  foreground=COLORS["accent"])

    def _build_footer(self, parent):
        sty = ttk.Style()
        sty.configure("P.Horizontal.TProgressbar",
                      troughcolor=COLORS["bg_dark"], background=COLORS["accent"],
                      borderwidth=0, thickness=6)
        ttk.Progressbar(parent, variable=self.progress_var, maximum=100,
                        style="P.Horizontal.TProgressbar"
                        ).pack(fill="x", padx=16, pady=(8, 0))
        sr = tk.Frame(parent, bg=COLORS["bg_mid"])
        sr.pack(fill="x", padx=16)
        tk.Label(sr, textvariable=self.status_text, font=FONTS["tiny"],
                 fg=COLORS["text_dim"], bg=COLORS["bg_mid"], anchor="w").pack(side="left")
        self.pct_label = tk.Label(sr, text="", font=FONTS["tiny"],
                                  fg=COLORS["accent"], bg=COLORS["bg_mid"], anchor="e")
        self.pct_label.pack(side="right")

    # ── Widget Helpers ────────────────────────────────────────────────

    def _sec(self, parent, num, title):
        fr = tk.Frame(parent, bg=COLORS["bg_card"])
        fr.pack(fill="x", padx=16, pady=(14, 6))
        tk.Label(fr, text=num, font=FONTS["badge"],
                 fg=COLORS["accent"], bg="#1a2744", padx=6, pady=1).pack(side="left")
        tk.Label(fr, text=f"  {title}", font=FONTS["badge"],
                 fg=COLORS["text_dim"], bg=COLORS["bg_card"], anchor="w").pack(side="left")

    def _build_lang_btns(self):
        for w in self.lang_frame.winfo_children():
            w.destroy()
        for i, (code, label, flag) in enumerate(LANGUAGES):
            sel = self.target_lang.get() == code
            tk.Button(self.lang_frame, text=f" {flag}  {label}",
                font=FONTS["small"], anchor="w", padx=10, pady=5, relief="flat",
                cursor="hand2",
                bg="#1a2744" if sel else COLORS["bg_input"],
                fg=COLORS["accent"] if sel else COLORS["text_dim"],
                activebackground="#1a2744", activeforeground=COLORS["accent"],
                highlightbackground=COLORS["accent"] if sel else COLORS["border"],
                highlightthickness=1,
                command=lambda c=code: self._sel_lang(c),
            ).grid(row=i//2, column=i%2, padx=2, pady=2, sticky="ew")
        self.lang_frame.grid_columnconfigure(0, weight=1)
        self.lang_frame.grid_columnconfigure(1, weight=1)

    def _sel_lang(self, code):
        self.target_lang.set(code)
        self._build_lang_btns()

    def _eng_btn(self, parent, value, name, badge_text, badge_color, desc):
        sel = self.engine.get() == value
        fr = tk.Frame(parent,
            bg="#1a2744" if sel else COLORS["bg_input"],
            highlightbackground=COLORS["accent"] if sel else COLORS["border"],
            highlightthickness=1, cursor="hand2")
        fr.pack(fill="x", pady=3)

        def select(e=None):
            self.engine.set(value)
            for w in parent.winfo_children():
                w.destroy()
            self._eng_btn(parent, "claude", "Claude API", "RECOMMENDED",
                          COLORS["success"], "Best quality — tone, humor, cultural nuances")
            self._eng_btn(parent, "free", "MyMemory", "FREE",
                          COLORS["accent2"], "No API key — literal, less nuanced")

        fr.bind("<Button-1>", select)
        top = tk.Frame(fr, bg=fr["bg"])
        top.pack(fill="x", padx=10, pady=(8, 2))
        top.bind("<Button-1>", select)
        rb = tk.Radiobutton(top, variable=self.engine, value=value,
                            bg=fr["bg"], fg=COLORS["text"],
                            selectcolor=COLORS["bg_input"], activebackground=fr["bg"])
        rb.pack(side="left")
        nm = tk.Label(top, text=name, font=FONTS["body"],
                      fg=COLORS["text_bright"] if sel else COLORS["text"], bg=fr["bg"])
        nm.pack(side="left")
        nm.bind("<Button-1>", select)
        bd = tk.Label(top, text=f" {badge_text} ", font=FONTS["badge"],
                      fg="#ffffff", bg=badge_color)
        bd.pack(side="right")
        bd.bind("<Button-1>", select)
        dl = tk.Label(fr, text=desc, font=FONTS["tiny"],
                      fg=COLORS["text_dim"], bg=fr["bg"], anchor="w", wraplength=350)
        dl.pack(fill="x", padx=30, pady=(0, 8))
        dl.bind("<Button-1>", select)

    def _on_engine_change(self, *args):
        if self.engine.get() == "claude":
            self.claude_frame.pack(fill="x", padx=16, pady=(4, 4))
        else:
            self.claude_frame.pack_forget()

    # ── API Key Protection ────────────────────────────────────────────

    def _mask_key(self, key: str) -> str:
        k = key.strip()
        if not k:
            return "No key set — click Edit to add one"
        if len(k) <= 8:
            return "•" * len(k)
        return k[:7] + " ••••••••••••••••••••• " + k[-4:]

    def _edit_key(self):
        dlg = tk.Toplevel(self)
        dlg.title("Edit Claude API Key")
        dlg.configure(bg=COLORS["bg_card"])
        dlg.resizable(False, False)
        dlg.transient(self)
        dlg.grab_set()

        self.update_idletasks()
        w, h = 460, 210
        x = self.winfo_rootx() + (self.winfo_width()  - w) // 2
        y = self.winfo_rooty() + (self.winfo_height() - h) // 2
        dlg.geometry(f"{w}x{h}+{x}+{y}")

        tk.Label(dlg, text="Update Claude API Key",
                 font=FONTS["heading"], fg=COLORS["text_bright"],
                 bg=COLORS["bg_card"]).pack(pady=(18, 2))
        tk.Label(dlg,
                 text="Paste your key below. Stored locally, sent only to api.anthropic.com.",
                 font=FONTS["tiny"], fg=COLORS["text_dim"],
                 bg=COLORS["bg_card"], justify="center").pack()

        var = tk.StringVar(value=self._api_key)
        ent = tk.Entry(dlg, textvariable=var, show="•",
                       font=FONTS["mono_sm"], bg=COLORS["bg_input"], fg=COLORS["text"],
                       insertbackground=COLORS["text"], relief="flat",
                       highlightbackground=COLORS["border"], highlightthickness=1, width=48)
        ent.pack(padx=20, pady=(10, 4), ipady=6)
        ent.focus_set()

        show_var = tk.BooleanVar(value=False)
        def toggle():
            show_var.set(not show_var.get())
            ent.configure(show="" if show_var.get() else "•")
            sb2.configure(text="Hide" if show_var.get() else "Show")
        sb2 = tk.Button(dlg, text="Show", font=FONTS["tiny"],
                        bg=COLORS["bg_input"], fg=COLORS["text_dim"],
                        relief="flat", cursor="hand2", command=toggle)
        sb2.pack()

        def save():
            self._api_key = var.get().strip()
            self.key_display.configure(text=self._mask_key(self._api_key))
            save_config({'api_key': self._api_key})
            dlg.destroy()

        br = tk.Frame(dlg, bg=COLORS["bg_card"])
        br.pack(pady=(10, 0))
        tk.Button(br, text="Save", font=FONTS["small"],
                  bg=COLORS["btn_primary"], fg="#ffffff", relief="flat",
                  cursor="hand2", padx=18, pady=4,
                  command=save).pack(side="left", padx=6)
        tk.Button(br, text="Cancel", font=FONTS["small"],
                  bg=COLORS["bg_input"], fg=COLORS["text_dim"], relief="flat",
                  cursor="hand2", padx=18, pady=4,
                  command=dlg.destroy).pack(side="left", padx=6)

        ent.bind("<Return>", lambda e: save())
        ent.bind("<Escape>", lambda e: dlg.destroy())
        dlg.wait_window()

    # ── Help Window ───────────────────────────────────────────────────

    def _show_help(self):
        dlg = tk.Toplevel(self)
        dlg.title(f"Help — {APP_TITLE}")
        dlg.configure(bg=COLORS["bg_card"])
        dlg.transient(self)
        self.update_idletasks()
        w, h = 660, 580
        x = self.winfo_rootx() + max(0, (self.winfo_width()  - w) // 2)
        y = self.winfo_rooty() + max(0, (self.winfo_height() - h) // 2)
        dlg.geometry(f"{w}x{h}+{x}+{y}")
        dlg.minsize(500, 400)
        dlg.resizable(True, True)

        txt = scrolledtext.ScrolledText(dlg, font=("Consolas", 9),
            bg=COLORS["bg_dark"], fg=COLORS["text"], relief="flat",
            wrap="word", padx=18, pady=14, highlightthickness=0)
        txt.pack(fill="both", expand=True)
        txt.insert("1.0", HELP_TEXT)

        # Highlight section headings
        txt.tag_configure("hdr", foreground=COLORS["accent"],
                          font=("Consolas", 9, "bold"))
        for m in re.finditer(r'^([A-Z][A-Z /()-]{3,})\n-{3,}', HELP_TEXT, re.MULTILINE):
            line_no = HELP_TEXT[:m.start()].count('\n') + 1
            txt.tag_add("hdr", f"{line_no}.0", f"{line_no}.end")

        txt.configure(state="disabled")

        tk.Button(dlg, text="  Close  ", font=FONTS["small"],
                  bg=COLORS["btn_primary"], fg="#ffffff", relief="flat",
                  cursor="hand2", padx=20, pady=5,
                  command=dlg.destroy).pack(pady=(0, 14))

    # ── File Handling ─────────────────────────────────────────────────

    def _browse(self):
        path = filedialog.askopenfilename(
            title="Select SRT subtitle file",
            filetypes=[("SRT files", "*.srt"), ("All files", "*.*")])
        if not path:
            return
        try:
            self.source_blocks = parse_srt(path)
        except Exception as e:
            messagebox.showerror("Parse Error", f"Could not parse file:\n{e}")
            return
        if not self.source_blocks:
            messagebox.showwarning("Empty File", "No subtitle blocks found.")
            return

        self.input_path = path
        name = Path(path).stem
        self.file_label.configure(text=name + ".srt", fg=COLORS["text_bright"])
        self.file_info.configure(
            text=f"{len(self.source_blocks):,} blocks  •  "
                 f"IDs {self.source_blocks[0]['id']}–{self.source_blocks[-1]['id']}")

        avg = sum(len(' '.join(b['text_lines'])) for b in self.source_blocks) / len(self.source_blocks)
        sug = suggest_batch_size(self.source_blocks)
        self.batch_size.set(sug)
        self.batch_hint.configure(text=f"Auto batch: {sug}  (avg {avg:.0f} chars/block)")

        lang = detect_language(self.source_blocks)
        self.detected_lang.set(lang)
        self.source_lang.set(lang)

        self._log(f"Loaded: {name}.srt — {len(self.source_blocks):,} blocks", "accent")
        self._log(f"Detected: {lang}  •  avg {avg:.0f} chars/block  •  auto batch={sug}", "info")
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
            self.preview_text.insert("end",
                f"\n... and {len(self.source_blocks)-50:,} more blocks\n", "ts")
        self.preview_text.configure(state="disabled")

    # ── Translation ───────────────────────────────────────────────────

    def _start(self):
        if not self.source_blocks:
            messagebox.showwarning("No File", "Please load an SRT file first.")
            return
        if self.engine.get() == "claude" and not self._api_key.strip():
            messagebox.showwarning("API Key",
                "No Claude API key set.\nClick the Edit button next to the key field.")
            return

        default_name = Path(self.input_path).stem + f"_{self.target_lang.get()}.srt"
        output = filedialog.asksaveasfilename(
            title="Save translated file as", defaultextension=".srt",
            initialfile=default_name, filetypes=[("SRT files", "*.srt")])
        if not output:
            return
        self.output_path = output

        self.is_translating = True
        self.cancel_flag = False
        self.translated_blocks = []
        self.progress_var.set(0)
        self.start_btn.configure(state="disabled")
        self.cancel_btn.configure(state="normal")
        self.notebook.select(2)

        total    = len(self.source_blocks)
        bsize    = self.batch_size.get()
        n_bat    = (total + bsize - 1) // bsize
        model_lbl = self.claude_model.get() if self.engine.get() == "claude" else "MyMemory (Free)"

        self._log("═" * 50, "info")
        self._log(f"Starting: {self.source_lang.get()} → {self.target_lang.get()}", "accent")
        self._log(f"Engine  : {model_lbl}", "info")
        self._log(f"Blocks  : {total:,}  │  Batch: {bsize}  │  Workers: {self.workers.get()}", "info")
        self._log(f"Est. API calls: {n_bat}", "info")
        self._log("═" * 50, "info")

        threading.Thread(target=self._worker, daemon=True).start()

    def _worker(self):
        blocks    = self.source_blocks
        total     = len(blocks)
        engine    = self.engine.get()
        api_key   = self._api_key
        src       = self.source_lang.get()
        tgt       = self.target_lang.get()
        model     = self.claude_model.get()
        bsize     = self.batch_size.get()
        n_workers = self.workers.get() if engine == "claude" else 1
        errors    = []

        batches          = [blocks[i:i+bsize] for i in range(0, total, bsize)]
        n_batches        = len(batches)
        results_by_batch = [None] * n_batches
        completed        = [0]
        lock             = threading.Lock()

        def do_batch(idx, batch):
            if self.cancel_flag:
                return idx, [{**b, "text_lines": b["text_lines"][:]} for b in batch]
            for attempt in range(3):
                try:
                    if engine == "claude":
                        out = translate_batch_claude(batch, src, tgt, api_key, model)
                    else:
                        out = [{**b, "text_lines": translate_free(b["text_lines"], src, tgt)}
                               for b in batch]
                    return idx, out
                except Exception as e:
                    if attempt < 2:
                        wait = 2 ** (attempt + 1)
                        self._log(f"Batch {idx+1} attempt {attempt+1} failed: {e}. Retry in {wait}s…", "warn")
                        time.sleep(wait)
                    else:
                        self._log(f"✗ Batch {idx+1} failed: {e} — keeping originals", "error")
                        errors.append(f"Batch {idx+1}: {e}")
                        return idx, [{**b, "text_lines": b["text_lines"][:]} for b in batch]

        def upd(n_done, bat_num):
            pct = n_done / total * 100
            self.after(0, lambda: self.progress_var.set(pct))
            self.after(0, lambda: self.status_text.set(
                f"Batch {bat_num}/{n_batches}  —  {n_done:,}/{total:,} blocks  ({pct:.0f}%)"))
            self.after(0, lambda: self.pct_label.configure(text=f"{pct:.0f}%"))

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
            futs = {pool.submit(do_batch, i, b): i for i, b in enumerate(batches)}
            for fut in concurrent.futures.as_completed(futs):
                if self.cancel_flag:
                    break
                bidx, bres = fut.result()
                results_by_batch[bidx] = bres
                with lock:
                    completed[0] += len(bres)
                    done = completed[0]
                upd(done, bidx + 1)
                self._log(f"  ✓ Batch {bidx+1:3d}/{n_batches}  ({len(bres)} blocks)", "info")

        if self.cancel_flag:
            self._log("Translation cancelled.", "warn")

        self.translated_blocks = [
            blk
            for br in results_by_batch if br is not None
            for blk in br
        ]

        if len(self.translated_blocks) == total and not self.cancel_flag:
            try:
                write_srt(self.translated_blocks, self.output_path)
                self._log(f"\nFile saved: {self.output_path}", "success")
            except Exception as e:
                self._log(f"✗ Failed to write: {e}", "error")
                self.after(0, self._done)
                return

            self._log("\n─── VERIFICATION ───", "accent")
            try:
                ob = parse_srt(self.output_path)
                checks = [
                    ("Block count",     len(ob) == total),
                    ("First ID",        ob[0]['id'] == blocks[0]['id']),
                    ("Last ID",         ob[-1]['id'] == blocks[-1]['id']),
                    ("All IDs match",   all(ob[j]['id'] == blocks[j]['id'] for j in range(total))),
                    ("All timestamps",  all(ob[j]['timestamp'] == blocks[j]['timestamp'] for j in range(total))),
                    ("All line counts", all(len(ob[j]['text_lines']) == len(blocks[j]['text_lines']) for j in range(total))),
                ]
                ok_all = all(ok for _, ok in checks)
                for nm, ok in checks:
                    self._log(f"  {'✓' if ok else '✗'} {nm}", "success" if ok else "error")
                self._log(
                    f"\n{'✅ SUCCESS' if ok_all else '⚠ Completed with issues'}"
                    f" — {total:,} blocks translated & verified",
                    "success" if ok_all else "warn")
            except Exception as e:
                self._log(f"Verification error: {e}", "error")

            if errors:
                self._log(f"\n{len(errors)} batch error(s):", "warn")
                for err in errors[:10]:
                    self._log(f"  • {err}", "warn")

            self.after(0, self._show_comparison)

        self.after(0, self._done)

    def _done(self):
        self.is_translating = False
        self.start_btn.configure(state="normal")
        self.cancel_btn.configure(state="disabled")
        if self.translated_blocks and len(self.translated_blocks) == len(self.source_blocks):
            self.status_text.set(f"Done — {len(self.translated_blocks):,} blocks translated")
            self.notebook.select(1)
        elif self.cancel_flag:
            self.status_text.set("Cancelled")
        else:
            self.status_text.set("Completed with errors — check Activity Log")

    def _cancel(self):
        self.cancel_flag = True

    def _show_comparison(self):
        self.compare_orig.configure(state="normal")
        self.compare_trans.configure(state="normal")
        self.compare_orig.delete("1.0", "end")
        self.compare_trans.delete("1.0", "end")
        for i in range(min(60, len(self.source_blocks))):
            s = self.source_blocks[i]
            o = self.translated_blocks[i] if i < len(self.translated_blocks) else None
            self.compare_orig.insert("end", f"[{s['id']}] {s['timestamp']}\n")
            for ln in s['text_lines']:
                self.compare_orig.insert("end", f"  {ln}\n")
            self.compare_orig.insert("end", "\n")
            if o:
                self.compare_trans.insert("end", f"[{o['id']}] {o['timestamp']}\n")
                for ln in o['text_lines']:
                    self.compare_trans.insert("end", f"  {ln}\n")
                self.compare_trans.insert("end", "\n")
        self.compare_orig.configure(state="disabled")
        self.compare_trans.configure(state="disabled")

    # ── Logging ───────────────────────────────────────────────────────

    def _log(self, message, tag="info"):
        def _ins():
            self.log_text.configure(state="normal")
            self.log_text.insert("end", f"[{time.strftime('%H:%M:%S')}] {message}\n", tag)
            self.log_text.see("end")
            self.log_text.configure(state="disabled")
        self.after(0, _ins)


# ═══════════════════════════════════════════════════════════════════════
# ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    app = App()
    app.mainloop()
