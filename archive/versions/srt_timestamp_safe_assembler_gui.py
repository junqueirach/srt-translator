#!/usr/bin/env python3
"""SRT Timestamp-Safe Assembler (GUI)

Build a FINAL SRT using:
  * File A (Original SRT): authoritative numbering + timestamps + structure
  * File B (Translated): translated dialogue keyed by subtitle number

Guarantee
---------
Timestamps and subtitle indices in the output are copied *verbatim* from File A.
Only the dialogue lines are taken from File B (if an ID is missing, it falls back to File A dialogue).

Encoding / Special characters (ê, ç, á, ã, …)
-------------------------------------------
This tool reads input using an automatic encoding detector (tries UTF-8 BOM, UTF-8, CP1252, Latin-1)
so Portuguese characters are preserved. Output is written as UTF-8 with BOM (utf-8-sig) for maximum
compatibility with Windows subtitle players/editors.

File B formats supported
------------------------
1) Full SRT (may contain timestamps) -> we ignore its timestamps, use its dialogue per ID.
2) ID mapping format from Pass 1:
      ###ID=123
      translated line 1
      translated line 2

Output
------
Writes a .srt file you choose in the GUI.
"""

import re
import sys
from pathlib import Path

try:
    import tkinter as tk
    from tkinter import filedialog, messagebox
except Exception as e:
    print("Tkinter is required for the GUI but is not available:", e)
    sys.exit(1)

TS_RE = re.compile(r"\d\d:\d\d:\d\d[,.]\d\d\d\s+-->\s+\d\d:\d\d:\d\d[,.]\d\d\d")


def normalize_newlines(text: str) -> str:
    return text.replace("\r\n", "\n").replace("\r", "\n")


def read_text_auto(p: Path) -> str:
    """Read text trying common encodings for SRT on Windows.

    Priority:
      1) UTF-8 with BOM (utf-8-sig)
      2) UTF-8
      3) Windows-1252 (cp1252)  [very common for Portuguese on Windows]
      4) Latin-1

    Returns text with normalized \n line endings.
    """
    for enc in ("utf-8-sig", "utf-8", "cp1252", "latin-1"):
        try:
            s = p.read_text(encoding=enc)
            return normalize_newlines(s)
        except UnicodeDecodeError:
            continue
    # Last resort: replacement avoids crash but may lose a few chars
    return normalize_newlines(p.read_text(encoding="utf-8", errors="replace"))


def split_blocks(text: str):
    # Split on one or more blank lines
    blocks = re.split(r"\n\s*\n", text.strip())
    return [b.strip("\n") for b in blocks if b.strip("\n")]


def parse_srt_blocks(text: str):
    """Parse SRT into list of (id_str, ts_line, dialogue_lines).

    Assumes each block begins with ID line then timestamp line.
    Dialogue lines can be zero or more.
    """
    blocks = split_blocks(text)
    parsed = []
    for b in blocks:
        lines = b.split("\n")
        if len(lines) < 2:
            continue
        idx = lines[0].strip()
        ts = lines[1]
        dlg = lines[2:]
        parsed.append((idx, ts, dlg))
    return parsed


def parse_translation_file(text: str):
    """Return dict: id_str -> dialogue_lines.

    Supports:
      A) SRT-like blocks (ID + timestamp + dialogue)  -> dialogue extracted
      B) ###ID=<n> mapping blocks                     -> dialogue extracted

    IMPORTANT:
    We NEVER use timestamps from File B.
    """
    text = text.strip()
    if "###ID=" in text:
        blocks = split_blocks(text)
        out = {}
        for b in blocks:
            lines = b.split("\n")
            if not lines:
                continue
            m = re.match(r"^###ID=(.+)$", lines[0].strip())
            if not m:
                continue
            idx = m.group(1).strip()
            out[idx] = lines[1:]
        return out

    parsed = parse_srt_blocks(text)
    out = {}
    for idx, _ts, dlg in parsed:
        out[idx] = dlg
    return out


def assemble(file_a_path: Path, file_b_path: Path, out_path: Path):
    a_text = read_text_auto(file_a_path)
    b_text = read_text_auto(file_b_path)

    a_blocks = parse_srt_blocks(a_text)
    if not a_blocks:
        raise ValueError("File A does not look like a valid SRT (no blocks found).")

    # Warn (do not modify!) if some timestamps look unusual
    bad_ts = [idx for idx, ts, _ in a_blocks if ("-->" in ts and not TS_RE.search(ts))]

    b_map = parse_translation_file(b_text)

    rebuilt_blocks = []
    missing_ids = []

    for idx, ts, dlg_a in a_blocks:
        dlg_b = b_map.get(idx)
        if dlg_b is None:
            missing_ids.append(idx)
            dlg = dlg_a
        else:
            dlg = dlg_b
        rebuilt_blocks.append("\n".join([idx, ts] + dlg))

    out_text = "\n\n".join(rebuilt_blocks) + "\n"
    # Write as UTF-8 with BOM for best compatibility on Windows players/editors.
    out_path.write_text(out_text, encoding="utf-8-sig")

    return {
        "blocks": len(a_blocks),
        "missing_ids": missing_ids,
        "bad_ts_ids": bad_ts,
        "output": str(out_path),
    }


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("SRT Timestamp-Safe Assembler")
        self.geometry("760x460")

        self.file_a = tk.StringVar()
        self.file_b = tk.StringVar()
        self.out_file = tk.StringVar()

        header = tk.Label(self, text="SRT Timestamp-Safe Assembler", font=("Arial", 16, "bold"))
        header.pack(pady=(12, 6))

        desc = (
            "File A (Original SRT): authoritative subtitle numbers + timestamps + structure.\n"
            "File B (Translated): translated dialogue keyed by subtitle number (can be full SRT or ###ID mapping).\n\n"
            "Output: a new SRT where ALL numbers and timestamps are copied verbatim from File A; dialogue is taken from File B.\n"
            "Encoding: reads UTF-8/CP1252 safely and writes UTF-8 with BOM to preserve Portuguese characters (ê, ç, á, ã…)."
        )
        tk.Label(self, text=desc, justify="left", wraplength=720).pack(padx=12, pady=(0, 14), anchor="w")

        self._row("File A (Original SRT):", self.file_a, self.pick_a)
        self._row("File B (Translated):", self.file_b, self.pick_b)
        self._row("Output .srt file:", self.out_file, self.pick_out, save=True)

        tk.Button(self, text="Assemble", font=("Arial", 12, "bold"), command=self.run).pack(pady=18)

        self.log = tk.Text(self, height=10, width=95)
        self.log.pack(padx=12, pady=(0, 12))
        self.log.insert("end", "Ready. Choose File A and File B, then choose an output file.\n")
        self.log.configure(state="disabled")

    def _row(self, label, var, cmd, save=False):
        frame = tk.Frame(self)
        frame.pack(fill="x", padx=12, pady=4)
        tk.Label(frame, text=label, width=24, anchor="w").pack(side="left")
        tk.Entry(frame, textvariable=var).pack(side="left", fill="x", expand=True, padx=(0, 6))
        tk.Button(frame, text=("Save As" if save else "Browse"), command=cmd).pack(side="left")

    def pick_a(self):
        p = filedialog.askopenfilename(
            title="Select File A (Original SRT)",
            filetypes=[("SRT/TXT", "*.srt *.txt"), ("All files", "*")]
        )
        if p:
            self.file_a.set(p)

    def pick_b(self):
        p = filedialog.askopenfilename(
            title="Select File B (Translated)",
            filetypes=[("SRT/TXT", "*.srt *.txt"), ("All files", "*")]
        )
        if p:
            self.file_b.set(p)

    def pick_out(self):
        p = filedialog.asksaveasfilename(
            title="Save output SRT as",
            defaultextension=".srt",
            filetypes=[("SRT", "*.srt"), ("All files", "*")]
        )
        if p:
            self.out_file.set(p)

    def _append_log(self, msg):
        self.log.configure(state="normal")
        self.log.insert("end", msg + "\n")
        self.log.see("end")
        self.log.configure(state="disabled")

    def run(self):
        a = self.file_a.get().strip()
        b = self.file_b.get().strip()
        o = self.out_file.get().strip()

        if not a or not b or not o:
            messagebox.showerror("Missing input", "Please select File A, File B, and an output file.")
            return

        try:
            result = assemble(Path(a), Path(b), Path(o))
            self._append_log(f"Assembled {result['blocks']} subtitle blocks.")
            if result["bad_ts_ids"]:
                self._append_log(
                    "Warning: Some timestamp lines in File A look unusual (still copied verbatim). IDs: "
                    + ", ".join(result["bad_ts_ids"][:20])
                    + (" ..." if len(result["bad_ts_ids"]) > 20 else "")
                )
            if result["missing_ids"]:
                self._append_log(
                    "Note: Missing translated IDs in File B; fell back to File A dialogue for IDs: "
                    + ", ".join(result["missing_ids"][:20])
                    + (" ..." if len(result["missing_ids"]) > 20 else "")
                )
            self._append_log(f"Output written to: {result['output']}")
            messagebox.showinfo("Done", f"Output written to:\n{result['output']}")
        except Exception as e:
            messagebox.showerror("Error", str(e))
            self._append_log("ERROR: " + str(e))


def main():
    app = App()
    app.mainloop()


if __name__ == "__main__":
    main()
