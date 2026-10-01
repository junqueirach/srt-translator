#!/usr/bin/env python3
"""
SRT Subtitle Translator
========================
Translates .srt subtitle files while preserving exact structure.

Two translation engines:
  1. Claude API (recommended) — high-quality, context-aware
  2. MyMemory API (free) — no API key needed, less nuanced

Usage:
  python srt_translator.py input.srt --target pt-BR --engine claude --api-key sk-ant-...
  python srt_translator.py input.srt --target es-ES --engine free

Install dependencies:
  pip install anthropic requests
"""

import re
import sys
import json
import time
import argparse
from pathlib import Path

try:
    import requests
except ImportError:
    print("Missing dependency: pip install requests")
    sys.exit(1)


# ─── SRT Parser ─────────────────────────────────────────────────────────

def parse_srt(filepath: str) -> list[dict]:
    """Parse an SRT file into a list of blocks."""
    with open(filepath, 'r', encoding='utf-8-sig') as f:
        content = f.read()
    
    blocks = []
    raw_blocks = re.split(r'\r?\n\r?\n+', content.strip())
    for rb in raw_blocks:
        lines = rb.strip().split('\n')
        lines = [l.strip() for l in lines]
        if len(lines) >= 3 and '-->' in lines[1]:
            blocks.append({
                'id': lines[0],
                'timestamp': lines[1],
                'text_lines': lines[2:],
            })
    return blocks


def write_srt(blocks: list[dict], filepath: str):
    """Write blocks to an SRT file with BOM and CRLF."""
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write('\ufeff')  # BOM
        for i, block in enumerate(blocks):
            f.write(f"{block['id']}\r\n")
            f.write(f"{block['timestamp']}\r\n")
            for line in block['text_lines']:
                f.write(f"{line}\r\n")
            f.write('\r\n')


# ─── Translation Engines ────────────────────────────────────────────────

def translate_claude(text_lines: list[str], source_lang: str, target_lang: str,
                     api_key: str, context: str = "") -> list[str]:
    """Translate using Claude API."""
    line_count = len(text_lines)
    joined = '\n'.join(text_lines)
    
    system_prompt = f"""You are a professional subtitle translator. Translate the following subtitle text from {source_lang} to {target_lang}.

CRITICAL RULES:
- The input has exactly {line_count} line(s). Your output MUST have exactly {line_count} line(s).
- Each line in your output corresponds to the same line in the input.
- Preserve tone, humor, slang, interjections, and emphasis.
- Use natural, idiomatic language for the target locale.
- Character names and proper nouns stay unchanged.
- Do NOT add quotes, numbering, labels, or any formatting — output ONLY the translated lines.
- If a line is a sound effect in brackets like [gunshot], translate the description inside the brackets.
- If a line is just punctuation or a name, keep it as-is.
{f'Context from surrounding dialogue: {context}' if context else ''}"""

    headers = {
        'Content-Type': 'application/json',
        'x-api-key': api_key,
        'anthropic-version': '2023-06-01',
    }
    
    payload = {
        'model': 'claude-sonnet-4-20250514',
        'max_tokens': 300,
        'system': system_prompt,
        'messages': [{'role': 'user', 'content': joined}],
    }
    
    response = requests.post(
        'https://api.anthropic.com/v1/messages',
        headers=headers,
        json=payload,
        timeout=30,
    )
    response.raise_for_status()
    
    data = response.json()
    translated = data['content'][0]['text'].strip().split('\n')
    
    # Enforce line count
    if len(translated) == line_count:
        return translated
    if len(translated) > line_count:
        return translated[:line_count]
    while len(translated) < line_count:
        translated.append('')
    return translated


def translate_free(text_lines: list[str], source_lang: str, target_lang: str) -> list[str]:
    """Translate using MyMemory free API."""
    lang_map = {
        'pt-BR': 'pt', 'es-ES': 'es', 'es-LATAM': 'es', 'en-US': 'en',
        'en-GB': 'en', 'de-DE': 'de', 'fr-FR': 'fr', 'it-IT': 'it',
        'ja-JP': 'ja', 'ko-KR': 'ko', 'zh-CN': 'zh-CN',
    }
    src = lang_map.get(source_lang, source_lang.split('-')[0])
    tgt = lang_map.get(target_lang, target_lang.split('-')[0])
    
    results = []
    for line in text_lines:
        if not line.strip() or re.match(r'^[^\w\s]*$', line):
            results.append(line)
            continue
        try:
            url = f"https://api.mymemory.translated.net/get?q={requests.utils.quote(line)}&langpair={src}|{tgt}"
            resp = requests.get(url, timeout=10)
            data = resp.json()
            if data.get('responseStatus') == 200 and data.get('responseData', {}).get('translatedText'):
                results.append(data['responseData']['translatedText'])
            else:
                results.append(line)
        except Exception:
            results.append(line)
    return results


# ─── Main Translation Loop ──────────────────────────────────────────────

def translate_srt(input_path: str, output_path: str, source_lang: str,
                  target_lang: str, engine: str, api_key: str = ""):
    """
    Translate an SRT file using the streaming READ → TRANSLATE → WRITE pattern.
    Each block is translated and verified inline — no separate lookup structure.
    """
    print(f"\n{'='*60}")
    print(f"  SRT Subtitle Translator")
    print(f"{'='*60}")
    print(f"  Input:    {input_path}")
    print(f"  Output:   {output_path}")
    print(f"  Source:   {source_lang}")
    print(f"  Target:   {target_lang}")
    print(f"  Engine:   {engine}")
    print(f"{'='*60}\n")
    
    # Parse source
    blocks = parse_srt(input_path)
    total = len(blocks)
    print(f"Parsed {total} subtitle blocks.\n")
    
    if total == 0:
        print("ERROR: No subtitle blocks found.")
        sys.exit(1)
    
    # Translate block by block (streaming pattern)
    translated_blocks = []
    errors = []
    
    for i, block in enumerate(blocks):
        # Build context from surrounding blocks
        ctx_before = ' | '.join(
            ' '.join(b['text_lines']) for b in blocks[max(0, i-2):i]
        )
        ctx_after = ' | '.join(
            ' '.join(b['text_lines']) for b in blocks[i+1:min(total, i+3)]
        )
        context = f"Before: {ctx_before}\nAfter: {ctx_after}" if ctx_before or ctx_after else ""
        
        # Translate
        retries = 3
        translated_lines = None
        for attempt in range(retries):
            try:
                if engine == 'claude':
                    translated_lines = translate_claude(
                        block['text_lines'], source_lang, target_lang, api_key, context
                    )
                else:
                    translated_lines = translate_free(
                        block['text_lines'], source_lang, target_lang
                    )
                break
            except Exception as e:
                if attempt < retries - 1:
                    wait = 2 ** (attempt + 1)
                    print(f"  ⚠ Block {block['id']} attempt {attempt+1} failed: {e}. Retrying in {wait}s...")
                    time.sleep(wait)
                else:
                    err = f"Block {block['id']}: {e}"
                    errors.append(err)
                    print(f"  ✗ {err} — using original text")
                    translated_lines = block['text_lines'][:]
        
        # ── INLINE VERIFICATION ──
        # Enforce line count match (the critical structural guarantee)
        expected = len(block['text_lines'])
        actual = len(translated_lines)
        if actual != expected:
            print(f"  ⚠ Block {block['id']}: line count {actual} → fixed to {expected}")
            if actual > expected:
                translated_lines = translated_lines[:expected]
            while len(translated_lines) < expected:
                translated_lines.append('')
        
        # Write block immediately (streaming pattern — no decoupled storage)
        translated_blocks.append({
            'id': block['id'],
            'timestamp': block['timestamp'],
            'text_lines': translated_lines,
        })
        
        # Progress
        pct = (i + 1) / total * 100
        if (i + 1) % 50 == 0 or i == 0 or i == total - 1:
            print(f"  [{pct:5.1f}%] Translated block {block['id']} ({i+1}/{total})")
        
        # Rate limiting for free API
        if engine == 'free' and (i + 1) % 5 == 0:
            time.sleep(1.0)
    
    # Write output
    write_srt(translated_blocks, output_path)
    
    # ── FINAL VERIFICATION ──
    print(f"\n{'─'*40}")
    print("  VERIFICATION")
    print(f"{'─'*40}")
    
    out_blocks = parse_srt(output_path)
    checks = {
        'Block count':         len(out_blocks) == total,
        'First ID':            out_blocks[0]['id'] == blocks[0]['id'],
        'Last ID':             out_blocks[-1]['id'] == blocks[-1]['id'],
        'All IDs match':       all(out_blocks[i]['id'] == blocks[i]['id'] for i in range(total)),
        'All timestamps':      all(out_blocks[i]['timestamp'] == blocks[i]['timestamp'] for i in range(total)),
        'All line counts':     all(len(out_blocks[i]['text_lines']) == len(blocks[i]['text_lines']) for i in range(total)),
    }
    
    all_pass = True
    for name, ok in checks.items():
        status = '✓' if ok else '✗'
        print(f"  {status} {name}")
        if not ok:
            all_pass = False
    
    print(f"\n{'='*60}")
    if all_pass:
        print(f"  ✅ SUCCESS — {total} blocks translated and verified")
    else:
        print(f"  ⚠ COMPLETED WITH ISSUES — check log above")
    
    if errors:
        print(f"\n  {len(errors)} error(s) during translation:")
        for e in errors[:10]:
            print(f"    • {e}")
        if len(errors) > 10:
            print(f"    ... and {len(errors) - 10} more")
    
    print(f"\n  Output saved to: {output_path}")
    print(f"{'='*60}\n")


# ─── CLI ─────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description='SRT Subtitle Translator — preserves structure exactly',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s movie.srt --target pt-BR --engine claude --api-key sk-ant-xxx
  %(prog)s movie.srt --target es-ES --engine free
  %(prog)s movie.srt --target de-DE --source English --engine claude --api-key sk-ant-xxx
        """
    )
    parser.add_argument('input', help='Input .srt file path')
    parser.add_argument('--target', '-t', default='pt-BR',
                        help='Target language code (default: pt-BR). Options: pt-BR, es-ES, es-LATAM, en-US, en-GB, de-DE, fr-FR, it-IT, ja-JP, ko-KR, zh-CN')
    parser.add_argument('--source', '-s', default='English',
                        help='Source language name (default: auto-detect as English)')
    parser.add_argument('--engine', '-e', choices=['claude', 'free'], default='claude',
                        help='Translation engine (default: claude)')
    parser.add_argument('--api-key', '-k', default='',
                        help='Anthropic API key (required for claude engine)')
    parser.add_argument('--output', '-o', default='',
                        help='Output file path (default: input_LANG.srt)')
    
    args = parser.parse_args()
    
    # Validate
    input_path = Path(args.input)
    if not input_path.exists():
        print(f"ERROR: File not found: {args.input}")
        sys.exit(1)
    
    if args.engine == 'claude' and not args.api_key:
        # Check environment variable
        import os
        args.api_key = os.environ.get('ANTHROPIC_API_KEY', '')
        if not args.api_key:
            print("ERROR: Claude engine requires an API key.")
            print("  Use --api-key sk-ant-xxx or set ANTHROPIC_API_KEY environment variable.")
            sys.exit(1)
    
    output_path = args.output or str(input_path.with_suffix('')) + f'_{args.target}.srt'
    
    translate_srt(
        input_path=str(input_path),
        output_path=output_path,
        source_lang=args.source,
        target_lang=args.target,
        engine=args.engine,
        api_key=args.api_key,
    )


if __name__ == '__main__':
    main()
