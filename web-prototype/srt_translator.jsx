import { useState, useRef, useCallback, useEffect } from "react";

// ─── SRT Parser & Writer ───────────────────────────────────────────────
function parseSRT(text) {
  const blocks = [];
  const raw = text.replace(/\r\n/g, "\n").trim().split(/\n\n+/);
  for (const rb of raw) {
    const lines = rb.trim().split("\n");
    if (lines.length >= 3 && lines[1].includes("-->")) {
      blocks.push({
        id: lines[0].trim(),
        timestamp: lines[1].trim(),
        textLines: lines.slice(2).map((l) => l.trim()),
      });
    }
  }
  return blocks;
}

function buildSRT(blocks) {
  const BOM = "\uFEFF";
  return (
    BOM +
    blocks
      .map((b) => `${b.id}\r\n${b.timestamp}\r\n${b.textLines.join("\r\n")}`)
      .join("\r\n\r\n") +
    "\r\n\r\n"
  );
}

// ─── Language Config ───────────────────────────────────────────────────
const LANGUAGES = [
  { code: "pt-BR", label: "Portuguese — Brazilian", flag: "🇧🇷" },
  { code: "es-ES", label: "Spanish — European", flag: "🇪🇸" },
  { code: "es-LATAM", label: "Spanish — Latin American", flag: "🇲🇽" },
  { code: "en-US", label: "English — US", flag: "🇺🇸" },
  { code: "en-GB", label: "English — UK", flag: "🇬🇧" },
  { code: "de-DE", label: "German", flag: "🇩🇪" },
  { code: "fr-FR", label: "French", flag: "🇫🇷" },
  { code: "it-IT", label: "Italian", flag: "🇮🇹" },
  { code: "ja-JP", label: "Japanese", flag: "🇯🇵" },
  { code: "ko-KR", label: "Korean", flag: "🇰🇷" },
  { code: "zh-CN", label: "Chinese — Simplified", flag: "🇨🇳" },
];

const ENGINES = [
  {
    id: "claude",
    name: "Claude API",
    badge: "RECOMMENDED",
    desc: "Best quality — preserves tone, humor, slang, and cultural nuances",
    requiresKey: true,
  },
  {
    id: "free",
    name: "Free Translation",
    badge: "NO API KEY",
    desc: "Uses MyMemory API — literal, less nuanced, but free and no setup",
    requiresKey: false,
  },
];

// ─── Translation Engines ───────────────────────────────────────────────

async function translateWithClaude(textLines, sourceLang, targetLang, apiKey, context = "") {
  const lineCount = textLines.length;
  const joined = textLines.join("\n");

  const systemPrompt = `You are a professional subtitle translator. Translate the following subtitle text from ${sourceLang} to ${targetLang}.

CRITICAL RULES:
- The input has exactly ${lineCount} line(s). Your output MUST have exactly ${lineCount} line(s).
- Each line in your output corresponds to the same line in the input.
- Preserve tone, humor, slang, interjections, and emphasis.
- Use natural, idiomatic language for the target locale.
- Character names and proper nouns stay unchanged.
- Do NOT add quotes, numbering, labels, or any formatting — output ONLY the translated lines.
- If a line is a sound effect in brackets like [gunshot], translate the description inside the brackets.
- If a line is just punctuation or a name, keep it as-is.
${context ? `\nContext from surrounding dialogue:\n${context}` : ""}`;

  const response = await fetch("https://api.anthropic.com/v1/messages", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "x-api-key": apiKey,
      "anthropic-version": "2023-06-01",
      "anthropic-dangerous-direct-browser-access": "true",
    },
    body: JSON.stringify({
      model: "claude-sonnet-4-20250514",
      max_tokens: 300,
      system: systemPrompt,
      messages: [{ role: "user", content: joined }],
    }),
  });

  if (!response.ok) {
    const err = await response.text();
    throw new Error(`Claude API error ${response.status}: ${err}`);
  }

  const data = await response.json();
  const translated = data.content[0].text.trim().split("\n");

  // Enforce line count
  if (translated.length === lineCount) return translated;
  if (translated.length > lineCount) return translated.slice(0, lineCount);
  while (translated.length < lineCount) translated.push("");
  return translated;
}

async function translateWithFree(textLines, sourceLang, targetLang) {
  const langMap = {
    "pt-BR": "pt", "es-ES": "es", "es-LATAM": "es", "en-US": "en",
    "en-GB": "en", "de-DE": "de", "fr-FR": "fr", "it-IT": "it",
    "ja-JP": "ja", "ko-KR": "ko", "zh-CN": "zh-CN",
  };
  const src = langMap[sourceLang] || sourceLang.split("-")[0];
  const tgt = langMap[targetLang] || targetLang.split("-")[0];
  const results = [];

  for (const line of textLines) {
    if (!line.trim() || /^[^\w\s]*$/.test(line)) {
      results.push(line);
      continue;
    }
    try {
      const url = `https://api.mymemory.translated.net/get?q=${encodeURIComponent(line)}&langpair=${src}|${tgt}`;
      const res = await fetch(url);
      const data = await res.json();
      if (data.responseStatus === 200 && data.responseData?.translatedText) {
        results.push(data.responseData.translatedText);
      } else {
        results.push(line);
      }
    } catch {
      results.push(line);
    }
  }
  return results;
}

// ─── Batch Processing Logic ────────────────────────────────────────────

async function translateBatchClaude(blocks, startIdx, batchSize, sourceLang, targetLang, apiKey) {
  const end = Math.min(startIdx + batchSize, blocks.length);
  const results = [];

  // Build context window: combine a few surrounding blocks for better translations
  for (let i = startIdx; i < end; i++) {
    const contextBefore = blocks.slice(Math.max(0, i - 2), i).map(b => b.textLines.join(" ")).join(" | ");
    const contextAfter = blocks.slice(i + 1, Math.min(blocks.length, i + 3)).map(b => b.textLines.join(" ")).join(" | ");
    const context = contextBefore || contextAfter ? `Before: ${contextBefore}\nAfter: ${contextAfter}` : "";

    const translated = await translateWithClaude(
      blocks[i].textLines, sourceLang, targetLang, apiKey, context
    );
    results.push({
      id: blocks[i].id,
      timestamp: blocks[i].timestamp,
      textLines: translated,
    });
  }
  return results;
}

async function translateBatchFree(blocks, startIdx, batchSize, sourceLang, targetLang) {
  const end = Math.min(startIdx + batchSize, blocks.length);
  const results = [];

  for (let i = startIdx; i < end; i++) {
    const translated = await translateWithFree(blocks[i].textLines, sourceLang, targetLang);
    results.push({
      id: blocks[i].id,
      timestamp: blocks[i].timestamp,
      textLines: translated,
    });
    // Rate limiting for free API
    if ((i - startIdx) % 5 === 4) await new Promise(r => setTimeout(r, 1000));
  }
  return results;
}

// ─── Detect Language ───────────────────────────────────────────────────
function detectLanguage(blocks) {
  const sample = blocks.slice(0, 30).map(b => b.textLines.join(" ")).join(" ").toLowerCase();
  const patterns = [
    { lang: "English", re: /\b(the|and|is|are|you|have|what|this|that|with|for|not|but|from|they|was|were|been|will|would|could|should|can|how|who|where|when|why)\b/g },
    { lang: "Portuguese", re: /\b(que|não|uma|com|para|está|isso|como|mas|mais|ele|ela|você|tem|são|muito|pode|aqui|então|também|fazer|quando|este|essa|pelo|pela)\b/g },
    { lang: "Spanish", re: /\b(que|los|las|una|por|con|para|está|esto|como|pero|más|tiene|son|muy|puede|aquí|también|hacer|cuando|este|esta|ese|esa)\b/g },
    { lang: "French", re: /\b(les|des|une|que|est|pas|pour|dans|avec|qui|sur|son|sont|mais|plus|tout|peut|cette|ces|aux|aussi|faire|comme|bien)\b/g },
    { lang: "German", re: /\b(und|der|die|das|ist|nicht|ein|eine|ich|sie|wir|auf|mit|den|dem|von|hat|für|sind|auch|aber|oder|wenn|nach|noch)\b/g },
    { lang: "Italian", re: /\b(che|non|una|per|sono|con|come|più|questo|anche|della|quello|hanno|essere|fare|tutto|così|quando|solo|molto|bene)\b/g },
  ];
  let best = { lang: "Unknown", count: 0 };
  for (const { lang, re } of patterns) {
    const count = (sample.match(re) || []).length;
    if (count > best.count) best = { lang, count };
  }
  return best.lang;
}

// ─── Main App ──────────────────────────────────────────────────────────
export default function SubtitleTranslator() {
  // State
  const [step, setStep] = useState("upload"); // upload | configure | translating | done
  const [sourceBlocks, setSourceBlocks] = useState([]);
  const [fileName, setFileName] = useState("");
  const [detectedLang, setDetectedLang] = useState("");
  const [sourceLang, setSourceLang] = useState("");
  const [targetLang, setTargetLang] = useState("pt-BR");
  const [engine, setEngine] = useState("claude");
  const [apiKey, setApiKey] = useState("");
  const [showKey, setShowKey] = useState(false);
  const [progress, setProgress] = useState(0);
  const [totalBlocks, setTotalBlocks] = useState(0);
  const [translatedBlocks, setTranslatedBlocks] = useState([]);
  const [errors, setErrors] = useState([]);
  const [log, setLog] = useState([]);
  const [isTranslating, setIsTranslating] = useState(false);
  const [outputSRT, setOutputSRT] = useState("");
  const [verificationResult, setVerificationResult] = useState(null);
  const [dragOver, setDragOver] = useState(false);
  const cancelRef = useRef(false);
  const fileInputRef = useRef(null);

  const addLog = useCallback((msg, type = "info") => {
    setLog((prev) => [...prev, { msg, type, time: new Date().toLocaleTimeString() }]);
  }, []);

  // ─── File Upload ─────────────────────────────────────────────────────
  const handleFile = useCallback((file) => {
    if (!file) return;
    const reader = new FileReader();
    reader.onload = (e) => {
      const text = e.target.result;
      const blocks = parseSRT(text);
      if (blocks.length === 0) {
        alert("Could not parse any subtitle blocks from this file. Please check the format.");
        return;
      }
      setSourceBlocks(blocks);
      setTotalBlocks(blocks.length);
      setFileName(file.name.replace(/\.srt$/i, ""));
      const lang = detectLanguage(blocks);
      setDetectedLang(lang);
      setSourceLang(lang);
      addLog(`Loaded "${file.name}" — ${blocks.length} blocks detected`);
      addLog(`Detected language: ${lang}`);
      setStep("configure");
    };
    reader.readAsText(file, "utf-8");
  }, [addLog]);

  const handleDrop = useCallback((e) => {
    e.preventDefault();
    setDragOver(false);
    const file = e.dataTransfer.files[0];
    if (file && file.name.endsWith(".srt")) handleFile(file);
  }, [handleFile]);

  // ─── Translation Process ─────────────────────────────────────────────
  const startTranslation = useCallback(async () => {
    if (engine === "claude" && !apiKey.trim()) {
      alert("Please enter your Claude API key.");
      return;
    }

    setStep("translating");
    setIsTranslating(true);
    cancelRef.current = false;
    setProgress(0);
    setTranslatedBlocks([]);
    setErrors([]);
    setLog([]);
    addLog(`Starting translation: ${sourceLang} → ${targetLang}`);
    addLog(`Engine: ${engine === "claude" ? "Claude API (Sonnet)" : "MyMemory (Free)"}`);
    addLog(`Total blocks: ${sourceBlocks.length}`);

    const BATCH = engine === "claude" ? 1 : 3; // Claude: 1 at a time for quality, Free: 3
    const allTranslated = [];
    const allErrors = [];

    for (let i = 0; i < sourceBlocks.length; i += BATCH) {
      if (cancelRef.current) {
        addLog("Translation cancelled by user.", "warn");
        break;
      }

      try {
        let batch;
        if (engine === "claude") {
          batch = await translateBatchClaude(
            sourceBlocks, i, BATCH, sourceLang, targetLang, apiKey.trim()
          );
        } else {
          batch = await translateBatchFree(
            sourceBlocks, i, BATCH, sourceLang, targetLang
          );
        }

        // Inline verification: check line counts match
        for (let j = 0; j < batch.length; j++) {
          const srcIdx = i + j;
          const src = sourceBlocks[srcIdx];
          const out = batch[j];
          if (out.id !== src.id) {
            addLog(`⚠ ID mismatch at block ${srcIdx}: expected ${src.id}, got ${out.id}`, "error");
            out.id = src.id;
          }
          if (out.timestamp !== src.timestamp) {
            out.timestamp = src.timestamp;
          }
          if (out.textLines.length !== src.textLines.length) {
            addLog(`⚠ Line count mismatch at block ${src.id}: expected ${src.textLines.length}, got ${out.textLines.length}. Auto-fixing.`, "warn");
            // Auto-fix
            if (out.textLines.length > src.textLines.length) {
              out.textLines = out.textLines.slice(0, src.textLines.length);
            }
            while (out.textLines.length < src.textLines.length) {
              out.textLines.push("");
            }
          }
        }

        allTranslated.push(...batch);
        setProgress(Math.min(allTranslated.length, sourceBlocks.length));
        setTranslatedBlocks([...allTranslated]);

        if (allTranslated.length % 50 === 0 || allTranslated.length === sourceBlocks.length) {
          addLog(`Translated ${allTranslated.length}/${sourceBlocks.length} blocks`);
        }
      } catch (err) {
        const errMsg = `Error at block ${i}: ${err.message}`;
        addLog(errMsg, "error");
        allErrors.push(errMsg);

        // On error, copy original block to keep alignment
        for (let j = 0; j < BATCH && i + j < sourceBlocks.length; j++) {
          allTranslated.push({ ...sourceBlocks[i + j] });
        }
        setProgress(allTranslated.length);

        // If too many consecutive errors, pause
        if (allErrors.length > 10) {
          addLog("Too many errors. Stopping.", "error");
          break;
        }

        // Wait before retry on API errors
        await new Promise((r) => setTimeout(r, 3000));
      }
    }

    setErrors(allErrors);

    if (allTranslated.length === sourceBlocks.length && !cancelRef.current) {
      // Build output
      const srt = buildSRT(allTranslated);
      setOutputSRT(srt);

      // Verification
      const outParsed = parseSRT(srt);
      const checks = {
        blockCount: outParsed.length === sourceBlocks.length,
        firstId: outParsed[0]?.id === sourceBlocks[0]?.id,
        lastId: outParsed[outParsed.length - 1]?.id === sourceBlocks[sourceBlocks.length - 1]?.id,
        allIdsMatch: outParsed.every((b, idx) => b.id === sourceBlocks[idx]?.id),
        allTimestampsMatch: outParsed.every((b, idx) => b.timestamp === sourceBlocks[idx]?.timestamp),
        allLineCountsMatch: outParsed.every((b, idx) => b.textLines.length === sourceBlocks[idx]?.textLines.length),
      };
      setVerificationResult(checks);
      const allPass = Object.values(checks).every(Boolean);
      addLog(allPass ? "✅ All verification checks passed!" : "⚠ Some verification checks failed.", allPass ? "success" : "error");
      addLog(`Translation complete! ${allTranslated.length} blocks processed.`, "success");
      setStep("done");
    }

    setIsTranslating(false);
  }, [engine, apiKey, sourceLang, targetLang, sourceBlocks, addLog]);

  const cancelTranslation = () => {
    cancelRef.current = true;
  };

  const downloadFile = () => {
    const blob = new Blob([outputSRT], { type: "text/plain;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `${fileName}_${targetLang}.srt`;
    a.click();
    URL.revokeObjectURL(url);
  };

  const reset = () => {
    setStep("upload");
    setSourceBlocks([]);
    setFileName("");
    setDetectedLang("");
    setSourceLang("");
    setTargetLang("pt-BR");
    setProgress(0);
    setTranslatedBlocks([]);
    setErrors([]);
    setLog([]);
    setOutputSRT("");
    setVerificationResult(null);
    cancelRef.current = false;
  };

  // ─── Render ──────────────────────────────────────────────────────────
  const pct = totalBlocks > 0 ? Math.round((progress / totalBlocks) * 100) : 0;

  return (
    <div style={styles.root}>
      {/* Background grain */}
      <div style={styles.grain} />

      {/* Header */}
      <header style={styles.header}>
        <div style={styles.headerInner}>
          <div style={styles.logoRow}>
            <div style={styles.logoIcon}>◈</div>
            <div>
              <h1 style={styles.title}>SRT Translator</h1>
              <p style={styles.subtitle}>Subtitle translation with structure preservation</p>
            </div>
          </div>
          {step !== "upload" && (
            <button onClick={reset} style={styles.resetBtn}>
              ↺ New File
            </button>
          )}
        </div>
      </header>

      <main style={styles.main}>
        {/* ─── STEP: Upload ─────────────────────────────────────── */}
        {step === "upload" && (
          <div style={styles.centerCard}>
            <div
              style={{
                ...styles.dropZone,
                ...(dragOver ? styles.dropZoneActive : {}),
              }}
              onDragOver={(e) => { e.preventDefault(); setDragOver(true); }}
              onDragLeave={() => setDragOver(false)}
              onDrop={handleDrop}
              onClick={() => fileInputRef.current?.click()}
            >
              <div style={styles.dropIcon}>⬆</div>
              <p style={styles.dropTitle}>Drop your .srt file here</p>
              <p style={styles.dropSub}>or click to browse</p>
              <input
                ref={fileInputRef}
                type="file"
                accept=".srt"
                style={{ display: "none" }}
                onChange={(e) => handleFile(e.target.files[0])}
              />
            </div>
            <div style={styles.featureGrid}>
              <div style={styles.featureCard}>
                <div style={styles.featureIcon}>🎯</div>
                <h3 style={styles.featureTitle}>Structure Preservation</h3>
                <p style={styles.featureDesc}>IDs, timestamps, and line counts are preserved exactly</p>
              </div>
              <div style={styles.featureCard}>
                <div style={styles.featureIcon}>🧠</div>
                <h3 style={styles.featureTitle}>Claude API</h3>
                <p style={styles.featureDesc}>Context-aware translation with tone and humor preserved</p>
              </div>
              <div style={styles.featureCard}>
                <div style={styles.featureIcon}>🆓</div>
                <h3 style={styles.featureTitle}>Free Option</h3>
                <p style={styles.featureDesc}>MyMemory fallback — no API key required</p>
              </div>
            </div>
          </div>
        )}

        {/* ─── STEP: Configure ──────────────────────────────────── */}
        {step === "configure" && (
          <div style={styles.configGrid}>
            {/* Left: Settings */}
            <div style={styles.configPanel}>
              <div style={styles.sectionHeader}>
                <span style={styles.sectionNumber}>01</span>
                <h2 style={styles.sectionTitle}>File Info</h2>
              </div>
              <div style={styles.infoRow}>
                <span style={styles.infoLabel}>File</span>
                <span style={styles.infoValue}>{fileName}.srt</span>
              </div>
              <div style={styles.infoRow}>
                <span style={styles.infoLabel}>Blocks</span>
                <span style={styles.infoValue}>{totalBlocks.toLocaleString()}</span>
              </div>
              <div style={styles.infoRow}>
                <span style={styles.infoLabel}>Detected</span>
                <span style={styles.infoValue}>{detectedLang}</span>
              </div>

              <div style={{ ...styles.sectionHeader, marginTop: 32 }}>
                <span style={styles.sectionNumber}>02</span>
                <h2 style={styles.sectionTitle}>Source Language</h2>
              </div>
              <input
                type="text"
                value={sourceLang}
                onChange={(e) => setSourceLang(e.target.value)}
                style={styles.textInput}
                placeholder="e.g. English, Portuguese, French..."
              />

              <div style={{ ...styles.sectionHeader, marginTop: 32 }}>
                <span style={styles.sectionNumber}>03</span>
                <h2 style={styles.sectionTitle}>Target Language</h2>
              </div>
              <div style={styles.langGrid}>
                {LANGUAGES.map((l) => (
                  <button
                    key={l.code}
                    onClick={() => setTargetLang(l.code)}
                    style={{
                      ...styles.langBtn,
                      ...(targetLang === l.code ? styles.langBtnActive : {}),
                    }}
                  >
                    <span>{l.flag}</span>
                    <span style={styles.langLabel}>{l.label}</span>
                  </button>
                ))}
              </div>

              <div style={{ ...styles.sectionHeader, marginTop: 32 }}>
                <span style={styles.sectionNumber}>04</span>
                <h2 style={styles.sectionTitle}>Translation Engine</h2>
              </div>
              <div style={styles.engineGrid}>
                {ENGINES.map((eng) => (
                  <button
                    key={eng.id}
                    onClick={() => setEngine(eng.id)}
                    style={{
                      ...styles.engineBtn,
                      ...(engine === eng.id ? styles.engineBtnActive : {}),
                    }}
                  >
                    <div style={styles.engineTop}>
                      <span style={styles.engineName}>{eng.name}</span>
                      <span style={{
                        ...styles.engineBadge,
                        background: eng.id === "claude" ? "#10b981" : "#6366f1",
                      }}>
                        {eng.badge}
                      </span>
                    </div>
                    <p style={styles.engineDesc}>{eng.desc}</p>
                  </button>
                ))}
              </div>

              {engine === "claude" && (
                <div style={styles.apiKeySection}>
                  <label style={styles.apiKeyLabel}>Claude API Key</label>
                  <div style={styles.apiKeyRow}>
                    <input
                      type={showKey ? "text" : "password"}
                      value={apiKey}
                      onChange={(e) => setApiKey(e.target.value)}
                      placeholder="sk-ant-..."
                      style={styles.apiKeyInput}
                    />
                    <button onClick={() => setShowKey(!showKey)} style={styles.eyeBtn}>
                      {showKey ? "◉" : "◎"}
                    </button>
                  </div>
                  <p style={styles.apiKeyHint}>
                    Your key is used only in-browser and never stored or sent anywhere else.
                  </p>
                </div>
              )}

              <button onClick={startTranslation} style={styles.startBtn}>
                Start Translation →
              </button>
            </div>

            {/* Right: Preview */}
            <div style={styles.previewPanel}>
              <div style={styles.sectionHeader}>
                <span style={styles.sectionNumber}>⬡</span>
                <h2 style={styles.sectionTitle}>Source Preview</h2>
              </div>
              <div style={styles.previewScroll}>
                {sourceBlocks.slice(0, 25).map((b, idx) => (
                  <div key={idx} style={styles.previewBlock}>
                    <div style={styles.previewId}>{b.id}</div>
                    <div style={styles.previewTs}>{b.timestamp}</div>
                    {b.textLines.map((l, li) => (
                      <div key={li} style={styles.previewText}>{l}</div>
                    ))}
                  </div>
                ))}
                {sourceBlocks.length > 25 && (
                  <div style={styles.previewMore}>
                    + {sourceBlocks.length - 25} more blocks...
                  </div>
                )}
              </div>
            </div>
          </div>
        )}

        {/* ─── STEP: Translating ────────────────────────────────── */}
        {step === "translating" && (
          <div style={styles.translatingLayout}>
            <div style={styles.progressCard}>
              <div style={styles.progressTop}>
                <h2 style={styles.progressTitle}>Translating...</h2>
                <span style={styles.progressPct}>{pct}%</span>
              </div>
              <div style={styles.progressBarBg}>
                <div style={{ ...styles.progressBarFill, width: `${pct}%` }} />
              </div>
              <div style={styles.progressStats}>
                <span>{progress.toLocaleString()} / {totalBlocks.toLocaleString()} blocks</span>
                <span>{engine === "claude" ? "Claude Sonnet" : "MyMemory"}</span>
              </div>
              <button onClick={cancelTranslation} style={styles.cancelBtn}>
                ✕ Cancel
              </button>
            </div>

            {/* Live comparison */}
            {translatedBlocks.length > 0 && (
              <div style={styles.liveCompare}>
                <div style={styles.sectionHeader}>
                  <span style={styles.sectionNumber}>⬡</span>
                  <h2 style={styles.sectionTitle}>Live Preview (last translated)</h2>
                </div>
                <div style={styles.compareGrid}>
                  <div style={styles.compareCol}>
                    <div style={styles.compareLabel}>ORIGINAL</div>
                    {(() => {
                      const lastIdx = Math.min(translatedBlocks.length, sourceBlocks.length) - 1;
                      const showFrom = Math.max(0, lastIdx - 2);
                      return sourceBlocks.slice(showFrom, lastIdx + 1).map((b, idx) => (
                        <div key={idx} style={styles.compareBlock}>
                          <span style={styles.compareId}>{b.id}</span>
                          {b.textLines.map((l, li) => <div key={li}>{l}</div>)}
                        </div>
                      ));
                    })()}
                  </div>
                  <div style={styles.compareCol}>
                    <div style={styles.compareLabel}>TRANSLATED</div>
                    {(() => {
                      const lastIdx = translatedBlocks.length - 1;
                      const showFrom = Math.max(0, lastIdx - 2);
                      return translatedBlocks.slice(showFrom, lastIdx + 1).map((b, idx) => (
                        <div key={idx} style={styles.compareBlock}>
                          <span style={styles.compareId}>{b.id}</span>
                          {b.textLines.map((l, li) => <div key={li}>{l}</div>)}
                        </div>
                      ));
                    })()}
                  </div>
                </div>
              </div>
            )}

            {/* Log */}
            <div style={styles.logCard}>
              <div style={styles.sectionHeader}>
                <span style={styles.sectionNumber}>⬡</span>
                <h2 style={styles.sectionTitle}>Activity Log</h2>
              </div>
              <div style={styles.logScroll}>
                {log.map((entry, idx) => (
                  <div key={idx} style={{
                    ...styles.logEntry,
                    color: entry.type === "error" ? "#ef4444" : entry.type === "warn" ? "#f59e0b" : entry.type === "success" ? "#10b981" : "#94a3b8",
                  }}>
                    <span style={styles.logTime}>{entry.time}</span> {entry.msg}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}

        {/* ─── STEP: Done ───────────────────────────────────────── */}
        {step === "done" && (
          <div style={styles.doneLayout}>
            <div style={styles.doneCard}>
              <div style={styles.doneIcon}>✓</div>
              <h2 style={styles.doneTitle}>Translation Complete</h2>
              <p style={styles.doneSub}>
                {totalBlocks.toLocaleString()} blocks translated from {sourceLang} to {LANGUAGES.find(l => l.code === targetLang)?.label || targetLang}
              </p>

              {verificationResult && (
                <div style={styles.verifyGrid}>
                  {Object.entries(verificationResult).map(([key, val]) => (
                    <div key={key} style={styles.verifyRow}>
                      <span style={{ color: val ? "#10b981" : "#ef4444", marginRight: 8 }}>
                        {val ? "✓" : "✗"}
                      </span>
                      <span style={styles.verifyLabel}>
                        {key.replace(/([A-Z])/g, " $1").replace(/^./, s => s.toUpperCase())}
                      </span>
                    </div>
                  ))}
                </div>
              )}

              <div style={styles.doneActions}>
                <button onClick={downloadFile} style={styles.downloadBtn}>
                  ⬇ Download {fileName}_{targetLang}.srt
                </button>
                <button onClick={reset} style={styles.newFileBtn}>
                  ↺ Translate Another File
                </button>
              </div>

              {errors.length > 0 && (
                <div style={styles.errorSummary}>
                  <h3 style={styles.errorTitle}>⚠ {errors.length} error(s) during translation</h3>
                  <div style={styles.errorList}>
                    {errors.map((e, i) => (
                      <div key={i} style={styles.errorItem}>{e}</div>
                    ))}
                  </div>
                </div>
              )}
            </div>

            {/* Side-by-side comparison */}
            <div style={styles.finalCompare}>
              <div style={styles.sectionHeader}>
                <span style={styles.sectionNumber}>⬡</span>
                <h2 style={styles.sectionTitle}>Side-by-Side Comparison (first 30 blocks)</h2>
              </div>
              <div style={styles.compareGrid}>
                <div style={styles.compareCol}>
                  <div style={styles.compareLabel}>ORIGINAL</div>
                  {sourceBlocks.slice(0, 30).map((b, idx) => (
                    <div key={idx} style={styles.compareBlock}>
                      <span style={styles.compareId}>{b.id}</span>
                      <span style={styles.compareTs}>{b.timestamp}</span>
                      {b.textLines.map((l, li) => <div key={li}>{l}</div>)}
                    </div>
                  ))}
                </div>
                <div style={styles.compareCol}>
                  <div style={styles.compareLabel}>TRANSLATED</div>
                  {translatedBlocks.slice(0, 30).map((b, idx) => (
                    <div key={idx} style={styles.compareBlock}>
                      <span style={styles.compareId}>{b.id}</span>
                      <span style={styles.compareTs}>{b.timestamp}</span>
                      {b.textLines.map((l, li) => <div key={li}>{l}</div>)}
                    </div>
                  ))}
                </div>
              </div>
            </div>

            {/* Log */}
            <div style={styles.logCard}>
              <div style={styles.sectionHeader}>
                <span style={styles.sectionNumber}>⬡</span>
                <h2 style={styles.sectionTitle}>Activity Log</h2>
              </div>
              <div style={styles.logScroll}>
                {log.map((entry, idx) => (
                  <div key={idx} style={{
                    ...styles.logEntry,
                    color: entry.type === "error" ? "#ef4444" : entry.type === "warn" ? "#f59e0b" : entry.type === "success" ? "#10b981" : "#94a3b8",
                  }}>
                    <span style={styles.logTime}>{entry.time}</span> {entry.msg}
                  </div>
                ))}
              </div>
            </div>
          </div>
        )}
      </main>
    </div>
  );
}

// ─── Styles ────────────────────────────────────────────────────────────
const styles = {
  root: {
    minHeight: "100vh",
    background: "#0a0e17",
    color: "#e2e8f0",
    fontFamily: "'DM Sans', 'Segoe UI', system-ui, sans-serif",
    position: "relative",
    overflow: "hidden",
  },
  grain: {
    position: "fixed",
    inset: 0,
    opacity: 0.03,
    backgroundImage: `url("data:image/svg+xml,%3Csvg viewBox='0 0 256 256' xmlns='http://www.w3.org/2000/svg'%3E%3Cfilter id='noise'%3E%3CfeTurbulence type='fractalNoise' baseFrequency='0.9' numOctaves='4' stitchTiles='stitch'/%3E%3C/filter%3E%3Crect width='100%25' height='100%25' filter='url(%23noise)'/%3E%3C/svg%3E")`,
    pointerEvents: "none",
    zIndex: 0,
  },
  header: {
    borderBottom: "1px solid #1e293b",
    padding: "16px 24px",
    position: "relative",
    zIndex: 1,
    background: "rgba(10,14,23,0.8)",
    backdropFilter: "blur(12px)",
  },
  headerInner: {
    maxWidth: 1200,
    margin: "0 auto",
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
  },
  logoRow: {
    display: "flex",
    alignItems: "center",
    gap: 14,
  },
  logoIcon: {
    fontSize: 28,
    color: "#60a5fa",
    fontWeight: 700,
  },
  title: {
    fontSize: 20,
    fontWeight: 700,
    margin: 0,
    letterSpacing: "-0.02em",
    background: "linear-gradient(135deg, #60a5fa, #a78bfa)",
    WebkitBackgroundClip: "text",
    WebkitTextFillColor: "transparent",
  },
  subtitle: {
    fontSize: 12,
    color: "#64748b",
    margin: 0,
    marginTop: 2,
    letterSpacing: "0.05em",
    textTransform: "uppercase",
  },
  resetBtn: {
    background: "transparent",
    border: "1px solid #334155",
    color: "#94a3b8",
    padding: "8px 16px",
    borderRadius: 8,
    cursor: "pointer",
    fontSize: 13,
    transition: "all 0.2s",
  },
  main: {
    maxWidth: 1200,
    margin: "0 auto",
    padding: "32px 24px",
    position: "relative",
    zIndex: 1,
  },

  // Upload
  centerCard: {
    maxWidth: 640,
    margin: "40px auto",
  },
  dropZone: {
    border: "2px dashed #334155",
    borderRadius: 16,
    padding: "64px 32px",
    textAlign: "center",
    cursor: "pointer",
    transition: "all 0.3s",
    background: "rgba(30,41,59,0.3)",
  },
  dropZoneActive: {
    borderColor: "#60a5fa",
    background: "rgba(96,165,250,0.08)",
  },
  dropIcon: {
    fontSize: 40,
    marginBottom: 16,
    color: "#60a5fa",
  },
  dropTitle: {
    fontSize: 18,
    fontWeight: 600,
    margin: "0 0 6px",
  },
  dropSub: {
    fontSize: 14,
    color: "#64748b",
    margin: 0,
  },
  featureGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(3, 1fr)",
    gap: 16,
    marginTop: 32,
  },
  featureCard: {
    background: "rgba(30,41,59,0.4)",
    border: "1px solid #1e293b",
    borderRadius: 12,
    padding: "20px 16px",
    textAlign: "center",
  },
  featureIcon: { fontSize: 24, marginBottom: 10 },
  featureTitle: { fontSize: 13, fontWeight: 600, margin: "0 0 6px" },
  featureDesc: { fontSize: 12, color: "#64748b", margin: 0, lineHeight: 1.5 },

  // Configure
  configGrid: {
    display: "grid",
    gridTemplateColumns: "1fr 380px",
    gap: 32,
    alignItems: "start",
  },
  configPanel: {
    background: "rgba(30,41,59,0.3)",
    border: "1px solid #1e293b",
    borderRadius: 16,
    padding: 28,
  },
  previewPanel: {
    background: "rgba(30,41,59,0.3)",
    border: "1px solid #1e293b",
    borderRadius: 16,
    padding: 20,
    maxHeight: "80vh",
    overflow: "hidden",
    display: "flex",
    flexDirection: "column",
  },
  previewScroll: {
    overflowY: "auto",
    flex: 1,
    maxHeight: "70vh",
  },
  previewBlock: {
    padding: "8px 0",
    borderBottom: "1px solid rgba(51,65,85,0.4)",
    fontSize: 13,
  },
  previewId: { color: "#60a5fa", fontSize: 11, fontWeight: 700 },
  previewTs: { color: "#475569", fontSize: 11, fontFamily: "monospace" },
  previewText: { color: "#cbd5e1" },
  previewMore: { padding: 16, textAlign: "center", color: "#475569", fontSize: 13 },
  sectionHeader: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    marginBottom: 16,
  },
  sectionNumber: {
    fontSize: 11,
    fontWeight: 700,
    color: "#60a5fa",
    background: "rgba(96,165,250,0.1)",
    padding: "3px 8px",
    borderRadius: 6,
    fontFamily: "monospace",
  },
  sectionTitle: {
    fontSize: 15,
    fontWeight: 600,
    margin: 0,
  },
  infoRow: {
    display: "flex",
    justifyContent: "space-between",
    padding: "8px 0",
    borderBottom: "1px solid rgba(51,65,85,0.3)",
    fontSize: 14,
  },
  infoLabel: { color: "#64748b" },
  infoValue: { fontWeight: 600 },
  textInput: {
    width: "100%",
    padding: "10px 14px",
    background: "rgba(15,23,42,0.6)",
    border: "1px solid #334155",
    borderRadius: 8,
    color: "#e2e8f0",
    fontSize: 14,
    outline: "none",
    boxSizing: "border-box",
  },
  langGrid: {
    display: "grid",
    gridTemplateColumns: "repeat(2, 1fr)",
    gap: 8,
  },
  langBtn: {
    display: "flex",
    alignItems: "center",
    gap: 10,
    padding: "10px 14px",
    background: "rgba(15,23,42,0.4)",
    border: "1px solid #1e293b",
    borderRadius: 8,
    color: "#94a3b8",
    cursor: "pointer",
    fontSize: 13,
    textAlign: "left",
    transition: "all 0.2s",
  },
  langBtnActive: {
    borderColor: "#60a5fa",
    color: "#e2e8f0",
    background: "rgba(96,165,250,0.1)",
  },
  langLabel: { flex: 1 },
  engineGrid: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 12,
  },
  engineBtn: {
    padding: 16,
    background: "rgba(15,23,42,0.4)",
    border: "1px solid #1e293b",
    borderRadius: 10,
    cursor: "pointer",
    textAlign: "left",
    color: "#94a3b8",
    transition: "all 0.2s",
  },
  engineBtnActive: {
    borderColor: "#60a5fa",
    color: "#e2e8f0",
    background: "rgba(96,165,250,0.08)",
  },
  engineTop: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 8,
  },
  engineName: { fontWeight: 600, fontSize: 14 },
  engineBadge: {
    fontSize: 9,
    fontWeight: 700,
    padding: "3px 7px",
    borderRadius: 4,
    color: "#fff",
    letterSpacing: "0.05em",
  },
  engineDesc: {
    fontSize: 12,
    margin: 0,
    lineHeight: 1.5,
    color: "#64748b",
  },
  apiKeySection: { marginTop: 20 },
  apiKeyLabel: { fontSize: 13, fontWeight: 600, marginBottom: 6, display: "block" },
  apiKeyRow: { display: "flex", gap: 8 },
  apiKeyInput: {
    flex: 1,
    padding: "10px 14px",
    background: "rgba(15,23,42,0.6)",
    border: "1px solid #334155",
    borderRadius: 8,
    color: "#e2e8f0",
    fontSize: 13,
    fontFamily: "monospace",
    outline: "none",
  },
  eyeBtn: {
    background: "rgba(51,65,85,0.5)",
    border: "1px solid #334155",
    borderRadius: 8,
    color: "#94a3b8",
    padding: "0 14px",
    cursor: "pointer",
    fontSize: 18,
  },
  apiKeyHint: {
    fontSize: 11,
    color: "#475569",
    marginTop: 6,
    fontStyle: "italic",
  },
  startBtn: {
    marginTop: 28,
    width: "100%",
    padding: "14px 24px",
    background: "linear-gradient(135deg, #2563eb, #7c3aed)",
    border: "none",
    borderRadius: 10,
    color: "#fff",
    fontSize: 15,
    fontWeight: 600,
    cursor: "pointer",
    letterSpacing: "0.02em",
    transition: "all 0.2s",
  },

  // Translating
  translatingLayout: {
    display: "flex",
    flexDirection: "column",
    gap: 24,
  },
  progressCard: {
    background: "rgba(30,41,59,0.4)",
    border: "1px solid #1e293b",
    borderRadius: 16,
    padding: 28,
  },
  progressTop: {
    display: "flex",
    justifyContent: "space-between",
    alignItems: "center",
    marginBottom: 16,
  },
  progressTitle: { fontSize: 18, fontWeight: 600, margin: 0 },
  progressPct: {
    fontSize: 28,
    fontWeight: 700,
    background: "linear-gradient(135deg, #60a5fa, #a78bfa)",
    WebkitBackgroundClip: "text",
    WebkitTextFillColor: "transparent",
    fontFamily: "monospace",
  },
  progressBarBg: {
    height: 8,
    background: "#1e293b",
    borderRadius: 4,
    overflow: "hidden",
  },
  progressBarFill: {
    height: "100%",
    background: "linear-gradient(90deg, #2563eb, #7c3aed, #a78bfa)",
    borderRadius: 4,
    transition: "width 0.3s ease",
  },
  progressStats: {
    display: "flex",
    justifyContent: "space-between",
    fontSize: 13,
    color: "#64748b",
    marginTop: 10,
  },
  cancelBtn: {
    marginTop: 16,
    padding: "8px 20px",
    background: "transparent",
    border: "1px solid #dc2626",
    color: "#ef4444",
    borderRadius: 8,
    cursor: "pointer",
    fontSize: 13,
  },
  liveCompare: {
    background: "rgba(30,41,59,0.3)",
    border: "1px solid #1e293b",
    borderRadius: 16,
    padding: 20,
  },
  compareGrid: {
    display: "grid",
    gridTemplateColumns: "1fr 1fr",
    gap: 16,
  },
  compareCol: {},
  compareLabel: {
    fontSize: 10,
    fontWeight: 700,
    letterSpacing: "0.1em",
    color: "#475569",
    marginBottom: 10,
    textTransform: "uppercase",
  },
  compareBlock: {
    padding: "8px 10px",
    background: "rgba(15,23,42,0.4)",
    borderRadius: 6,
    marginBottom: 6,
    fontSize: 13,
    lineHeight: 1.5,
  },
  compareId: {
    fontSize: 10,
    fontWeight: 700,
    color: "#60a5fa",
    marginRight: 8,
  },
  compareTs: {
    fontSize: 10,
    color: "#475569",
    fontFamily: "monospace",
    marginLeft: 4,
  },

  // Log
  logCard: {
    background: "rgba(30,41,59,0.3)",
    border: "1px solid #1e293b",
    borderRadius: 16,
    padding: 20,
  },
  logScroll: {
    maxHeight: 200,
    overflowY: "auto",
    fontFamily: "monospace",
    fontSize: 12,
    lineHeight: 1.8,
  },
  logEntry: {},
  logTime: { color: "#334155", marginRight: 8 },

  // Done
  doneLayout: {
    display: "flex",
    flexDirection: "column",
    gap: 24,
  },
  doneCard: {
    background: "rgba(30,41,59,0.4)",
    border: "1px solid #1e293b",
    borderRadius: 16,
    padding: 36,
    textAlign: "center",
  },
  doneIcon: {
    width: 64,
    height: 64,
    background: "linear-gradient(135deg, #10b981, #059669)",
    borderRadius: "50%",
    display: "flex",
    alignItems: "center",
    justifyContent: "center",
    fontSize: 28,
    color: "#fff",
    margin: "0 auto 20px",
    fontWeight: 700,
  },
  doneTitle: { fontSize: 22, fontWeight: 700, margin: "0 0 8px" },
  doneSub: { fontSize: 14, color: "#64748b", margin: "0 0 24px" },
  verifyGrid: {
    display: "inline-grid",
    gridTemplateColumns: "1fr 1fr",
    gap: "6px 32px",
    textAlign: "left",
    margin: "0 auto 24px",
    fontSize: 13,
  },
  verifyRow: { display: "flex", alignItems: "center" },
  verifyLabel: { color: "#94a3b8" },
  doneActions: {
    display: "flex",
    gap: 12,
    justifyContent: "center",
    flexWrap: "wrap",
  },
  downloadBtn: {
    padding: "14px 28px",
    background: "linear-gradient(135deg, #10b981, #059669)",
    border: "none",
    borderRadius: 10,
    color: "#fff",
    fontSize: 15,
    fontWeight: 600,
    cursor: "pointer",
  },
  newFileBtn: {
    padding: "14px 28px",
    background: "transparent",
    border: "1px solid #334155",
    borderRadius: 10,
    color: "#94a3b8",
    fontSize: 14,
    cursor: "pointer",
  },
  errorSummary: {
    marginTop: 24,
    padding: 16,
    background: "rgba(239,68,68,0.08)",
    border: "1px solid rgba(239,68,68,0.2)",
    borderRadius: 10,
    textAlign: "left",
  },
  errorTitle: { fontSize: 14, color: "#ef4444", margin: "0 0 8px" },
  errorList: { fontSize: 12, color: "#fca5a5" },
  errorItem: { padding: "2px 0" },
  finalCompare: {
    background: "rgba(30,41,59,0.3)",
    border: "1px solid #1e293b",
    borderRadius: 16,
    padding: 20,
    maxHeight: 500,
    overflow: "auto",
  },
};
