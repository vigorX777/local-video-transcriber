import { useEffect, useMemo, useRef, useState } from "react";
import {
  AlertCircle,
  BookOpen,
  Check,
  ChevronDown,
  CircleDot,
  Clock3,
  Copy,
  Download,
  Eye,
  FileText,
  FolderOpen,
  KeyRound,
  Leaf,
  ListTree,
  LoaderCircle,
  Play,
  Save,
  Settings,
  ShieldCheck,
  SlidersHorizontal,
  Sparkles,
  Sun,
  Trash2,
  Upload,
  Video,
  Moon,
} from "lucide-react";

const stageLabels = ["音频提取", "Whisper 识别", "内容整理", "结构校验", "生成文章"];

function formatDuration(value) {
  if (value == null) return "时长待识别";
  const seconds = Math.round(value);
  return `${Math.floor(seconds / 60)}:${String(seconds % 60).padStart(2, "0")}`;
}

function formatSize(value) {
  if (!value) return "";
  return value >= 1024 ** 3 ? `${(value / 1024 ** 3).toFixed(1)} GB` : `${Math.round(value / 1024 ** 2)} MB`;
}

function formatDate(value) {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "完成时间未知";
  return new Intl.DateTimeFormat("zh-CN", { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" }).format(date);
}

async function api(path, options = {}) {
  const response = await fetch(path, {
    headers: { "Content-Type": "application/json", ...(options.headers || {}) },
    ...options,
  });
  if (!response.ok) {
    const body = await response.json().catch(() => ({}));
    throw new Error(body.detail || "操作未完成，请稍后再试。");
  }
  const contentType = response.headers.get("content-type") || "";
  return contentType.includes("application/json") ? response.json() : response.text();
}

function Cover({ src, alt = "视频封面" }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [src]);
  return src && !failed ? <img src={src} alt={alt} onError={() => setFailed(true)} /> : <Video size={31} aria-label="无可用视频封面" />;
}

function parseMarkdown(markdown) {
  const blocks = [];
  let paragraph = [];
  let headingIndex = 0;
  const flush = () => {
    if (paragraph.length) {
      blocks.push({ type: "paragraph", content: paragraph.join("") });
      paragraph = [];
    }
  };
  markdown.split(/\r?\n/).forEach((line) => {
    if (!line.trim()) return flush();
    if (line.startsWith("# ")) {
      flush();
      blocks.push({ type: "h1", id: `heading-${headingIndex++}`, content: line.slice(2) });
    } else if (line.startsWith("## ")) {
      flush();
      blocks.push({ type: "h2", id: `heading-${headingIndex++}`, content: line.slice(3) });
    } else if (line.startsWith("> ")) {
      flush();
      blocks.push({ type: "quote", content: line.slice(2) });
    } else {
      paragraph.push(line);
    }
  });
  flush();
  return blocks;
}

function MarkdownPreview({ blocks }) {
  return <article className="markdown-body">{blocks.map((block, index) => {
    if (block.type === "h1") return <h1 id={block.id} key={index}>{block.content}</h1>;
    if (block.type === "h2") return <h2 id={block.id} key={index}>{block.content}</h2>;
    if (block.type === "quote") return <blockquote key={index}>{block.content}</blockquote>;
    return <p key={index}>{block.content}</p>;
  })}</article>;
}

function DocumentReader({ markdown, record, settings, onCopy, onImport, onSettings }) {
  const blocks = useMemo(() => parseMarkdown(markdown), [markdown]);
  const headings = blocks.filter((block) => block.type === "h2");
  const previewScrollRef = useRef(null);
  const [readerPreferences, setReaderPreferences] = useState(() => {
    try {
      const stored = JSON.parse(window.localStorage.getItem("quiet-transcript-reader") || "{}");
      return {
        width: [560, 680, 800].includes(stored.width) ? stored.width : 680,
        fontSize: [14, 16, 18].includes(stored.fontSize) ? stored.fontSize : 16,
      };
    } catch {
      return { width: 680, fontSize: 16 };
    }
  });
  const base = record?.kind === "history" ? `/api/history/${encodeURIComponent(record.id)}` : `/api/tasks/${encodeURIComponent(record?.id || "")}`;
  const updatePreference = (key, value) => setReaderPreferences((current) => {
    const next = { ...current, [key]: value };
    window.localStorage.setItem("quiet-transcript-reader", JSON.stringify(next));
    return next;
  });
  const jumpTo = (id) => {
    const container = previewScrollRef.current;
    const target = container?.querySelector(`#${id}`);
    if (container && target) container.scrollTo({ top: target.getBoundingClientRect().top - container.getBoundingClientRect().top + container.scrollTop - 20, behavior: "smooth" });
  };
  const readerStyle = { "--reader-width": `${readerPreferences.width}px`, "--reader-font-size": `${readerPreferences.fontSize}px` };
  return <section className="document-reader" style={readerStyle}>
    <header className="reader-delivery">
      <div className="delivery-copy"><div><FileText size={17} /><h2>文稿交付</h2></div><p>下载、复制和导入都来自同一份已验证的 Markdown。</p></div>
      <div className="delivery-actions">{settings?.obsidian_vault ? <button className="action-button primary-action" disabled={!markdown} onClick={() => onImport(record)}><Upload size={18} />导入 Obsidian</button> : <button className="action-button primary-action" disabled={!markdown} onClick={onSettings}><Settings size={18} />设置 Obsidian Vault</button>}<a className={`action-button ${!markdown ? "disabled" : ""}`} href={markdown && record ? `${base}/download` : undefined}><Download size={18} />下载 Markdown</a><button className="action-button" disabled={!markdown} onClick={() => onCopy(markdown)}><Copy size={18} />复制全文</button></div>
    </header>
    <div className="reader-security"><ShieldCheck size={15} />源视频和结果保留在本机；Gemini 只会收到整理所需的文字内容。</div>
    <div className="result-area">
      <div className="preview-surface">
        <div className="preview-heading"><span><Eye size={17} />Markdown 预览</span><div className="reader-controls" aria-label="阅读设置"><span><SlidersHorizontal size={14} />阅读设置</span><div role="group" aria-label="展示宽度">{[[560, "紧凑"], [680, "标准"], [800, "宽屏"]].map(([value, label]) => <button key={value} className={readerPreferences.width === value ? "selected" : ""} aria-pressed={readerPreferences.width === value} onClick={() => updatePreference("width", value)}>{label}</button>)}</div><div role="group" aria-label="字体大小">{[[14, "小"], [16, "标准"], [18, "大"]].map(([value, label]) => <button key={value} className={readerPreferences.fontSize === value ? "selected" : ""} aria-pressed={readerPreferences.fontSize === value} onClick={() => updatePreference("fontSize", value)}>{label}</button>)}</div></div>{markdown && <span className="preview-note">已通过结构校验</span>}</div>
        <div className="preview-scroll" ref={previewScrollRef}>{markdown ? <MarkdownPreview blocks={blocks} /> : <div className="preview-empty"><FileText size={31} /><h2>{record ? "Markdown 正在载入" : "文章会在校验通过后出现"}</h2><p>{record ? "请稍候，正在读取已生成的文稿。" : "标题、章节和段落会在完整流程结束后一次性展示，避免阅读到未校验的半成品。"}</p></div>}</div>
      </div>
      <aside className="reader-sidebar">
        <section className="outline-panel" aria-label="文章章节大纲">
          <div className="outline-heading"><ListTree size={17} /><h2>文章大纲</h2></div>
          {headings.length ? <nav className="outline-list" aria-label="章节定位">{headings.map((heading, index) => <button key={heading.id} onClick={() => jumpTo(heading.id)}><span>{String(index + 1).padStart(2, "0")}</span>{heading.content}</button>)}</nav> : <p className="outline-empty">章节将在文稿载入后显示。</p>}
        </section>
      </aside>
    </div>
  </section>;
}

function TaskTimeline({ task }) {
  const active = task?.percent || 0;
  const stageIndex = active < 13 ? 0 : active < 34 ? 1 : active < 93 ? 2 : active < 97 ? 3 : 4;
  return <ol className="timeline" aria-label="转写进度">
    {stageLabels.map((label, index) => {
      const isDone = task?.status === "completed" || index < stageIndex;
      const isActive = task?.status === "running" && index === stageIndex;
      return <li className={`${isDone ? "done" : ""} ${isActive ? "active" : ""}`} key={label}><span className="step-dot">{isDone ? <Check size={14} strokeWidth={3} /> : index + 1}</span><span>{label}</span></li>;
    })}
  </ol>;
}

function VideoCard({ video, task, onPick, onStart, disabled }) {
  const shown = video || task?.source;
  const coverUrl = task?.cover_url || video?.cover_url;
  return <section className={`video-card ${shown ? "ready" : ""}`}>
    <div className="video-art"><Cover src={coverUrl} /></div>
    <div className="video-copy"><p className="eyebrow">本地视频</p><h2>{shown?.name || "尚未选择视频"}</h2><p className="video-meta">{shown ? `${formatDuration(shown.duration_seconds)}　·　${formatSize(shown.size_bytes)}　·　${shown.name.split(".").pop().toUpperCase()}` : "视频不会上传、复制或离开这台 Mac。"}</p></div>
    <div className="video-actions"><button className="quiet-button" onClick={onPick} disabled={disabled}><FolderOpen size={17} />选择视频</button><button className="primary-button" onClick={onStart} disabled={(!video && !task?.can_retry) || disabled}><Play size={17} fill="currentColor" />{task?.can_retry ? "重新转写" : "开始转写"}</button></div>
  </section>;
}

function HistoryView({ history, selected, markdown, settings, onOpen, onCopy, onImport, onSettings }) {
  return <main className="history-view">
    <header className="view-heading"><p className="eyebrow">已完成的文稿</p><h1>回到任何一次转写</h1><p>所有记录都从本机输出目录读取，可继续浏览、导出或导入知识库。</p></header>
    {!history.length ? <section className="history-empty"><BookOpen size={31} /><h2>还没有可阅读的转写结果</h2><p>完成第一份视频转写后，它会自动出现在这里。</p></section> : <section className="history-layout"><aside className="history-list" aria-label="转写历史列表">{history.map((record) => <button className={selected?.id === record.id ? "history-item selected" : "history-item"} key={record.id} onClick={() => onOpen(record)}><div className="history-cover"><Cover src={record.cover_url} /></div><div><strong>{record.title}</strong><span>{record.source_name}</span><small><Clock3 size={12} />{formatDate(record.completed_at)}　·　{record.model}</small></div></button>)}</aside><div className="history-reader">{selected ? <DocumentReader markdown={markdown} record={{ ...selected, kind: "history" }} settings={settings} onCopy={onCopy} onImport={onImport} onSettings={onSettings} /> : <div className="history-select"><BookOpen size={30} /><h2>选择一份文稿开始阅读</h2><p>右侧会显示完整正文、章节大纲与交付操作。</p></div>}</div></section>}
  </main>;
}

function SettingsView({ settings, setSettings, onSave, onPickVault, onSaveKey, onDeleteKey, saving, toast }) {
  const [keyInput, setKeyInput] = useState("");
  if (!settings) return <div className="loading-page"><LoaderCircle className="spin" />正在读取本机设置…</div>;
  const update = (key, value) => setSettings({ ...settings, [key]: value });
  return <main className="settings-view">
    <header className="view-heading"><p className="eyebrow">本机配置</p><h1>让工具按你的方式工作</h1><p>普通设置保存在本机应用目录；Gemini 凭据只保存在 macOS Keychain。</p></header>
    <section className="settings-section"><div className="section-heading"><SlidersHorizontal size={19} /><div><h2>文本模型</h2><p>选择本次转写使用的编辑模型。</p></div></div><div className="provider-switch" role="group" aria-label="文本模型提供方">{[["gemini", "Gemini"], ["ollama", "本机 Ollama"]].map(([value, label]) => <button key={value} className={settings.provider === value ? "selected" : ""} onClick={() => update("provider", value)}>{label}</button>)}</div>{settings.provider === "gemini" ? <div className="settings-grid"><label>Gemini 模型<select value={settings.gemini_model} onChange={(event) => update("gemini_model", event.target.value)}>{settings.gemini_models.map((model) => <option key={model}>{model}</option>)}</select></label><label>思考预算<select value={settings.gemini_thinking_budget} onChange={(event) => update("gemini_thinking_budget", Number(event.target.value))}><option value={0}>关闭（推荐）</option><option value={1024}>1,024 tokens</option><option value={4096}>4,096 tokens</option></select></label><label>温度<select value={settings.gemini_temperature} onChange={(event) => update("gemini_temperature", Number(event.target.value))}><option value={0}>0（稳定）</option><option value={0.2}>0.2</option><option value={0.5}>0.5</option></select></label></div> : <label className="settings-field">本机模型<input value={settings.ollama_model} onChange={(event) => update("ollama_model", event.target.value)} placeholder="qwen2.5:14b-instruct" /></label>}<div className="key-row"><div><KeyRound size={18} /><span>Gemini API Key</span><small className={settings.gemini_key_configured ? "configured" : ""}>{settings.gemini_key_configured ? "已安全保存在 Keychain" : "尚未配置"}</small></div><div className="key-actions"><input type="password" value={keyInput} onChange={(event) => setKeyInput(event.target.value)} placeholder="粘贴新的 API Key" aria-label="Gemini API Key" /><button className="quiet-button" onClick={() => { onSaveKey(keyInput); setKeyInput(""); }} disabled={!keyInput}>保存</button>{settings.gemini_key_configured && <button className="icon-button danger" aria-label="删除 Gemini API Key" onClick={onDeleteKey}><Trash2 size={17} /></button>}</div></div></section>
    <section className="settings-section"><div className="section-heading"><FolderOpen size={19} /><div><h2>Obsidian</h2><p>导入时只会向你明确选择的 Vault 写入 Markdown。</p></div></div><div className="vault-row"><div><span>{settings.obsidian_vault || "尚未选择 Vault"}</span>{settings.obsidian_vault && <small>{settings.obsidian_subdir ? `子目录：${settings.obsidian_subdir}` : "根目录"}</small>}</div><button className="quiet-button" onClick={onPickVault}><FolderOpen size={16} />选择 Vault</button></div><label className="settings-field">导入子目录（可选）<input value={settings.obsidian_subdir} onChange={(event) => update("obsidian_subdir", event.target.value)} placeholder="例如：收件箱/视频转写" /></label></section>
    <div className="settings-footer"><button className="primary-button" onClick={onSave} disabled={saving}><Save size={17} />{saving ? "正在保存" : "保存设置"}</button>{toast && <span className="inline-toast">{toast}</span>}</div>
  </main>;
}

export function App() {
  const [view, setView] = useState("workbench");
  const [theme, setTheme] = useState(() => window.localStorage.getItem("quiet-transcript-theme") === "dark" ? "dark" : "light");
  const [settings, setSettings] = useState(null);
  const [selectedVideo, setSelectedVideo] = useState(null);
  const [task, setTask] = useState(null);
  const [markdown, setMarkdown] = useState("");
  const [history, setHistory] = useState([]);
  const [selectedHistory, setSelectedHistory] = useState(null);
  const [historyMarkdown, setHistoryMarkdown] = useState("");
  const [toast, setToast] = useState("");
  const [saving, setSaving] = useState(false);

  const showToast = (message) => { setToast(message); window.setTimeout(() => setToast(""), 3600); };
  const loadHistory = async () => { try { setHistory((await api("/api/history")).records); } catch (error) { showToast(error.message); } };
  const loadMarkdown = async (id) => { try { setMarkdown(await api(`/api/tasks/${encodeURIComponent(id)}/markdown`)); } catch { setMarkdown(""); } };
  const openHistory = async (record) => { setSelectedHistory(record); setHistoryMarkdown(""); try { setHistoryMarkdown(await api(`/api/history/${encodeURIComponent(record.id)}/markdown`)); } catch (error) { showToast(error.message); } };
  useEffect(() => {
    api("/api/settings").then(setSettings).catch((error) => showToast(error.message));
    loadHistory();
    api("/api/tasks/current").then((current) => { if (current) { setTask(current); if (current.has_markdown) loadMarkdown(current.id); } }).catch(() => {});
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("quiet-transcript-theme", theme);
  }, [theme]);
  useEffect(() => {
    if (!task?.id || task.status !== "running") return undefined;
    const events = new EventSource(`/api/tasks/${encodeURIComponent(task.id)}/events`);
    events.addEventListener("task", (event) => { const next = JSON.parse(event.data); setTask(next); if (next.status === "completed") { loadMarkdown(next.id); loadHistory(); } });
    events.onerror = () => events.close();
    return () => events.close();
  }, [task?.id, task?.status]);

  const chooseVideo = async () => { try { const result = await api("/api/picker/video", { method: "POST" }); if (!result.cancelled) setSelectedVideo(result.video); } catch (error) { showToast(error.message); } };
  const startTask = async () => { try { const next = task?.can_retry && !selectedVideo ? await api(`/api/tasks/${encodeURIComponent(task.id)}/retry`, { method: "POST" }) : await api("/api/tasks", { method: "POST", body: JSON.stringify({ source: selectedVideo.path }) }); setTask(next); setMarkdown(""); } catch (error) { showToast(error.message); } };
  const saveSettings = async () => { setSaving(true); try { setSettings(await api("/api/settings", { method: "PUT", body: JSON.stringify(settings) })); showToast("设置已保存在本机。"); } catch (error) { showToast(error.message); } finally { setSaving(false); } };
  const pickVault = async () => { try { const result = await api("/api/picker/vault", { method: "POST" }); if (!result.cancelled) setSettings({ ...settings, obsidian_vault: result.path }); } catch (error) { showToast(error.message); } };
  const saveKey = async (apiKey) => { try { await api("/api/settings/gemini-key", { method: "PUT", body: JSON.stringify({ api_key: apiKey }) }); setSettings({ ...settings, gemini_key_configured: true }); showToast("Gemini Key 已保存到 macOS Keychain。"); } catch (error) { showToast(error.message); } };
  const deleteKey = async () => { try { await api("/api/settings/gemini-key", { method: "DELETE" }); setSettings({ ...settings, gemini_key_configured: false }); showToast("Gemini Key 已从 Keychain 删除。"); } catch (error) { showToast(error.message); } };
  const copyMarkdown = async (content) => { try { await navigator.clipboard.writeText(content); showToast("已复制完整 Markdown。"); } catch { showToast("浏览器没有授予剪贴板权限。请使用下载文件。"); } };
  const importDocument = async (record) => { const base = record?.kind === "history" ? "/api/history" : "/api/tasks"; try { const result = await api(`${base}/${encodeURIComponent(record.id)}/obsidian`, { method: "POST" }); showToast(`已写入 Obsidian：${result.name}`); } catch (error) { showToast(error.message); } };
  const running = task?.status === "running" || task?.status === "queued";
  const taskRecord = task ? { id: task.id, kind: "task" } : null;

  return <div className="app-shell">
    <aside className="sidebar"><div className="brand"><span className="brand-mark"><Leaf size={25} fill="currentColor" /></span><div><strong>Quiet Transcript</strong><small>安静地，把视频变成文字</small></div></div><nav aria-label="主导航"><button className={view === "workbench" ? "nav-item selected" : "nav-item"} onClick={() => setView("workbench")}><FileText size={19} />转写工作台</button><button className={view === "history" ? "nav-item selected" : "nav-item"} onClick={() => { setView("history"); loadHistory(); }}><Clock3 size={19} />历史记录</button><button className={view === "settings" ? "nav-item selected" : "nav-item"} onClick={() => setView("settings")}><Settings size={19} />设置</button><button className="nav-item theme-toggle" aria-label={theme === "dark" ? "切换至浅色模式" : "切换至夜间模式"} aria-pressed={theme === "dark"} onClick={() => setTheme((current) => current === "dark" ? "light" : "dark")}>{theme === "dark" ? <Sun size={19} /> : <Moon size={19} />}<span>{theme === "dark" ? "浅色模式" : "夜间模式"}</span></button></nav><div className="sidebar-footer"><span><CircleDot size={11} fill="currentColor" />本机工作台 · 安全控制</span><small>macOS · Apple Silicon</small></div></aside>
    <div className="page-shell">{view === "settings" ? <SettingsView settings={settings} setSettings={setSettings} onSave={saveSettings} onPickVault={pickVault} onSaveKey={saveKey} onDeleteKey={deleteKey} saving={saving} toast={toast} /> : view === "history" ? <HistoryView history={history} selected={selectedHistory} markdown={historyMarkdown} settings={settings} onOpen={openHistory} onCopy={copyMarkdown} onImport={importDocument} onSettings={() => setView("settings")} /> : <main className="workbench"><header className="hero"><p className="eyebrow">本地视频转写</p><h1>把视频变成一篇好读的文章</h1></header><VideoCard video={selectedVideo} task={task} onPick={chooseVideo} onStart={startTask} disabled={running} /><TaskTimeline task={task} />{task?.status === "failed" && <div className="failure"><AlertCircle size={19} /><div><strong>{task.stage}</strong><p>{task.error}</p></div></div>}{running && <section className="progress-panel"><div className="progress-heading"><div><Sparkles size={22} /><div><strong>{task.stage}</strong><span>{task.message}</span></div></div><span>{task.percent}%</span></div><div className="progress-track"><span style={{ width: `${task.percent}%` }} /></div><div className="progress-meta">{task.block_total ? `已完成 ${task.block_index} / ${task.block_total} 组文字整理` : "任务在本机运行；完成后会自动显示 Markdown。"}<details><summary>查看运行日志 <ChevronDown size={14} /></summary><pre>{task.logs.join("\n") || "正在等待第一条日志…"}</pre></details></div></section>}<DocumentReader markdown={markdown} record={taskRecord} settings={settings} onCopy={copyMarkdown} onImport={importDocument} onSettings={() => setView("settings")} /></main>}</div>
    {toast && <div className="toast" role="status">{toast}</div>}
  </div>;
}
