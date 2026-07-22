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
  Home,
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
  Link2,
  ArrowRight,
  RotateCcw,
  HardDrive,
  Wifi,
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
    const detail = typeof body.detail === "object" ? body.detail?.message : body.detail;
    const error = new Error(detail || "操作未完成，请稍后再试。");
    error.code = typeof body.detail === "object" ? body.detail?.code : "";
    throw error;
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
  const labels = task?.stages || stageLabels;
  const stageIndex = task?.stages ? stageIndexFor(task) : active < 13 ? 0 : active < 34 ? 1 : active < 93 ? 2 : active < 97 ? 3 : 4;
  return <ol className={`timeline ${labels.length > 5 ? "timeline-wide" : ""}`} aria-label="转写进度">
    {labels.map((label, index) => {
      const isDone = task?.status === "completed" || index < stageIndex;
      const isActive = task?.status === "running" && index === stageIndex;
      return <li className={`${isDone ? "done" : ""} ${isActive ? "active" : ""}`} key={label}><span className="step-dot">{isDone ? <Check size={14} strokeWidth={3} /> : index + 1}</span><span>{label}</span></li>;
    })}
  </ol>;
}

function TaskLogs({ logs }) {
  return <details className="task-log-details"><summary>查看运行日志 <ChevronDown size={14} /></summary><pre>{logs?.join("\n") || "正在等待第一条日志…"}</pre></details>;
}

function VideoCard({ video, task, onPick, onStart, disabled }) {
  const shown = video || task?.source;
  const coverUrl = task?.cover_url || video?.cover_url;
  const isNetwork = task?.source_kind === "network" && !video;
  const sourceLabel = isNetwork ? `网络视频 · ${task.source?.platform_label || "网络来源"}` : "本地视频";
  const sourceKind = isNetwork ? (task.download_mode === "keep_video" ? "保留原视频" : "仅转写") : shown?.name.split(".").pop().toUpperCase();
  const actionLabel = task?.can_retry ? "重新转写" : isNetwork && task?.status === "completed" ? "已完成" : "开始转写";
  return <section className={`video-card ${shown ? "ready" : ""}`}>
    <div className="video-art"><Cover src={coverUrl} /></div>
    <div className="video-copy"><p className="eyebrow">{sourceLabel}</p><h2>{shown?.name || "尚未选择视频"}</h2><p className="video-meta">{shown ? `${formatDuration(shown.duration_seconds)}　·　${formatSize(shown.size_bytes)}　·　${sourceKind}` : "视频不会上传、复制或离开这台 Mac。"}</p></div>
    <div className="video-actions"><button className="quiet-button" onClick={onPick} disabled={disabled}><FolderOpen size={17} />选择本地视频</button><button className="primary-button" onClick={onStart} disabled={(!video && !task?.can_retry) || disabled}><Play size={17} fill="currentColor" />{actionLabel}</button></div>
  </section>;
}

function formatMonthlyDuration(value) {
  const seconds = Math.max(0, Math.round(Number(value) || 0));
  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  return hours ? `${hours} 小时 ${minutes} 分` : `${minutes} 分钟`;
}

function FlipNumber({ value, label }) {
  return <span className="flip-number" aria-label={label}>{String(value).split("").map((character, index) => /\d/.test(character) ? <span className="flip-digit" key={`${index}-${character}`}>{character}</span> : <span className="flip-symbol" key={`${index}-${character}`}>{character}</span>)}</span>;
}

function HomeView({ video, task, dashboard, onPick, onStart, onOpenNetwork, onOpenHistory, onViewHistory, onWorkbench }) {
  const running = task?.status === "running" || task?.status === "queued";
  const month = dashboard?.month || { duration_seconds: 0, completed_count: 0 };
  const recent = dashboard?.recent_records || [];
  const progressDescription = task?.block_total ? `已完成 ${task.block_index} / ${task.block_total} 组文字整理` : task?.message || "正在准备本机转写流程。";
  return <main className="home-view">
    <header className="home-hero"><div><p className="eyebrow">本地转写工作台</p><h1>把一段视频，<br />安静地整理成文章。</h1><p>从本地文件开始，或先验证一条公开视频链接。确认前不会下载、不会创建任务，也不会占用磁盘。</p></div></header>

    <section className="home-import" aria-label="新建单视频转写">
      {video ? <div className="home-selected-video"><div className="home-selected-art"><Cover src={video.cover_url} /></div><div><p className="eyebrow">已选择视频</p><strong>{video.name}</strong><span>{formatDuration(video.duration_seconds)}　·　{formatSize(video.size_bytes)}　·　{video.name.split(".").pop().toUpperCase()}</span></div><div className="home-selected-actions"><button className="quiet-button" onClick={onPick} disabled={running}>更换</button><button className="primary-button" onClick={onStart} disabled={running}><Play size={17} fill="currentColor" />开始转写</button></div></div> : <button className="home-import-pick" onClick={onPick} disabled={running}><span className="home-import-icon"><Upload size={24} /></span><span><strong>选择一段本地视频</strong><small>视频只在这台 Mac 上读取，不会上传或复制。</small></span><span className="home-import-action">选择视频 <FolderOpen size={16} /></span></button>}
      <button className="home-network-entry" onClick={onOpenNetwork} disabled={running}><span className="home-import-icon"><Link2 size={22} /></span><span><strong>粘贴视频链接</strong><small>YouTube、B站、抖音的公开单视频</small></span><span className="home-import-action">验证链接 <ArrowRight size={15} /></span></button>
    </section>

    <section className="home-current-heading"><div><p className="eyebrow">当前任务</p><h2>一条任务链，不分下载与转写</h2></div><button className="home-text-button" onClick={onWorkbench}>查看工作台 <ArrowRight size={13} /></button></section>
    <section className="home-current-grid" aria-label="转写概览">
      <article className={`home-unified-task ${running ? "is-running" : ""}`}>
        {running ? <><div className="home-unified-main"><div className="home-card-heading"><span>{task.source_kind === "network" ? `网络来源 · ${task.source?.platform_label}` : "本地视频"}</span><span>任务 ID：{task.id}</span></div><div className="home-task-title"><span className="home-live"><i /></span><div><strong>{task.source?.name}</strong><small>{task.stage} · {task.message}</small></div></div><div className="home-progress"><span style={{ width: `${task.percent}%` }} /></div><div className="home-task-meta"><span>{progressDescription}</span><button onClick={onWorkbench}>打开任务</button></div></div><aside><FlipNumber value={`${task.percent}%`} label={`当前进度 ${task.percent}%`} /><p>{task.source_kind === "network" && task.download?.speed_bytes ? `${formatSize(task.download.speed_bytes)}/s` : task.stage}<br />下载、识别与整理共用同一任务。</p></aside></> : <div className="home-idle"><Clock3 size={23} /><div><strong>当前没有正在运行的转写</strong><span>选择本地视频或验证网络链接后，真实进度会显示在这里。</span></div></div>}
      </article>
      <article className="home-month-card">
        <div className="home-card-heading"><span>本月已转写</span><span>{month.completed_count} 份完成</span></div>
        <strong className="home-month-number"><FlipNumber value={formatMonthlyDuration(month.duration_seconds)} label={`本月已转写 ${formatMonthlyDuration(month.duration_seconds)}`} /></strong>
        <p>仅统计本月已完成且通过验证的视频时长。</p>
      </article>
    </section>
    <div className="home-boundary"><ShieldCheck size={17} /><span><strong>网络导入边界：</strong>仅支持公开的单视频。Cookie、登录、播放列表、直播与受限内容不会作为可用入口出现。</span></div>

    <section className="home-recent" aria-labelledby="home-recent-heading">
      <header><div><p className="eyebrow">回顾</p><h2 id="home-recent-heading">最近转写</h2></div><button className="home-text-button" onClick={onViewHistory}>查看全部</button></header>
      {recent.length ? <div className="home-recent-list">{recent.map((record) => <button className="home-recent-item" key={record.id} onClick={() => onOpenHistory(record)}><div className="home-recent-cover"><Cover src={record.cover_url} /></div><div><strong>{record.title}</strong><span>{record.source_name}</span></div><small>{formatDuration(record.duration_seconds)}</small><time>{formatDate(record.completed_at)}</time></button>)}</div> : <div className="home-recent-empty"><BookOpen size={23} /><span>完成第一份转写后，它会在这里出现。</span></div>}
    </section>
  </main>;
}

function NetworkImportView({ settings, onBack, onCreate }) {
  const [url, setUrl] = useState("");
  const [media, setMedia] = useState(null);
  const [mode, setMode] = useState("transcribe_only");
  const [loading, setLoading] = useState(false);
  const [creating, setCreating] = useState(false);
  const [error, setError] = useState("");
  const inspect = async () => {
    setLoading(true); setError(""); setMedia(null);
    try { setMedia(await api("/api/network/inspect", { method: "POST", body: JSON.stringify({ url }) })); }
    catch (caught) { setError(caught.message); }
    finally { setLoading(false); }
  };
  const create = async () => {
    setCreating(true); setError("");
    try { await onCreate(media, mode); }
    catch (caught) { setError(caught.message); setCreating(false); }
  };
  return <main className="network-page">
    <header><p className="eyebrow">新建网络转写</p><h1>先看清来源，<br />再开始下载。</h1><p>粘贴一条公开单视频链接。系统会先校验平台与内容类型，不会在预检阶段保存媒体或创建任务。</p></header>
    <section className="network-form-shell"><div className="network-form-card"><label htmlFor="network-url">公开视频链接</label><div className="network-input-row"><input id="network-url" value={url} onChange={(event) => setUrl(event.target.value)} placeholder="粘贴 YouTube、B站或抖音的视频链接" onKeyDown={(event) => event.key === "Enter" && url && inspect()} /><button className="primary-button" disabled={!url || loading} onClick={inspect}>{loading ? <LoaderCircle className="spin" size={17} /> : <Link2 size={17} />}{loading ? "正在验证" : "验证链接"}</button></div><div className="platform-row">{["YouTube", "B站", "抖音"].map((item) => <span key={item}><i />{item}</span>)}</div><p className="network-helper">仅接受 http / https 的公开单视频链接。频道、播放列表、直播、本机地址与需要登录的内容会被明确拒绝。</p>{error && <div className="network-inline-error"><AlertCircle size={16} />{error}</div>}</div><aside className="network-help"><h2>为什么先验证？</h2><ul><li>避免频道、长列表或错误链接直接占用网络与磁盘。</li><li>确认平台、标题、时长和下载模式后，才建立唯一任务。</li><li>短链接跳转后会再次校验是否仍属于受支持平台。</li></ul></aside></section>
    {media && <section className="network-inspect-card"><div className="network-cover">{media.thumbnail_url ? <img src={media.thumbnail_url} alt="来源封面" referrerPolicy="no-referrer" /> : <Video size={42} />}<span>来源封面 · 预检返回</span></div><div className="network-inspect-content"><p className="eyebrow">已验证 · {media.platform_label}公开单视频</p><h2>{media.title}</h2><p className="network-meta-line">作者：{media.author}　·　时长 {formatDuration(media.duration_seconds)}　·　内容 ID：{media.content_id}</p><div className="network-metadata"><span><b>来源</b> {media.platform_label}</span><span><b>保存位置</b> {settings?.network_download_dir ? "Quiet Transcript" : "待设置"}</span><span><b>任务</b> 尚未创建</span></div><div className="network-modes">{[["transcribe_only", "仅转写 · 默认", "仅保存最佳音频与来源封面；后续照常生成 JSON、Markdown 与文章阅读面。"], ["keep_video", "保留原视频", "下载最高 1080p 视频与最佳音频。若曾转写过同一来源，只补视频文件，不重复成功步骤。"]].map(([value, title, copy]) => <label className={mode === value ? "selected" : ""} key={value}><input type="radio" name="download-mode" checked={mode === value} onChange={() => setMode(value)} /><span><strong>{title}</strong><small>{copy}</small></span></label>)}</div><footer><small>{mode === "keep_video" ? "将下载最高 1080p 原视频、最佳音频与来源封面。" : "将仅下载最佳音频与来源封面。"}确认后会创建一个可恢复的本地任务。</small><button className="primary-button" disabled={creating} onClick={create}><ArrowRight size={17} />{creating ? "正在创建" : "下载并转写"}</button></footer></div></section>}
    <button className="network-back" onClick={onBack}>返回首页</button>
  </main>;
}

function stageIndexFor(task) {
  const stage = task?.stage || "";
  const labels = task?.stages || stageLabels;
  const aliases = { "下载媒体": "下载素材", "Gemini 整理": "内容整理", "Ollama 整理": "内容整理", "生成 Markdown": "生成文章", "已完成": labels[labels.length - 1] };
  const normalized = aliases[stage] || stage;
  const index = labels.findIndex((label) => label === normalized || stage.includes(label));
  return index < 0 ? 0 : index;
}

function NetworkTaskView({ task, onRetry, onHome, retrying }) {
  const stageIndex = stageIndexFor(task);
  const labels = task.stages || [];
  const downloading = task.stage === "下载媒体";
  const displayPercent = downloading ? Math.round(task.download?.percent || 0) : task.percent;
  const speed = task.download?.speed_bytes ? `${formatSize(task.download.speed_bytes)}/s` : "正在准备";
  const downloaded = formatSize(task.download?.downloaded_bytes);
  const eta = task.download?.eta_seconds ? `预计剩余 ${Math.ceil(task.download.eta_seconds / 60)} 分钟` : "完成后自动进入下一阶段";
  if (task.status === "failed") {
    const downloadFailure = task.stage?.includes("下载") || task.error_code === "download_failed";
    return <main className="network-page network-error-page"><header><p className="eyebrow">任务需要处理 · {task.stage}</p><h1>{downloadFailure ? <>下载暂时停住，<br />已完成的部分还在。</> : <>转写暂时停住，<br />已完成的部分还在。</>}</h1><p>{downloadFailure ? "系统已保留可恢复的媒体片段。重新尝试将继续复用已有产物，不会新建下载目录或重复已完成步骤。" : "系统已保留下载媒体、音频和 Whisper 结果。重新尝试将从失败阶段继续，不会重复已成功的步骤。"}</p></header><section className="network-error-card"><div><AlertCircle size={22} /></div><h2>{task.error || (downloadFailure ? "网络连接在下载过程中中断" : "转写流程未成功完成")}</h2><p>{downloadFailure ? "请恢复网络后重试；如果平台要求登录、会员或地区访问，系统会明确停止，不会尝试绕过限制。" : "请继续任务；系统会复用已下载媒体和现有缓存，并重新执行尚未通过的整理或校验步骤。"}</p><code>{task.error_code || (downloadFailure ? "DOWNLOAD_INTERRUPTED" : "TRANSCRIPT_FAILED")} · {task.source?.platform_label || "网络来源"} · 已安全保留可恢复产物</code><TaskLogs logs={task.logs} /><footer><button className="primary-button" onClick={onRetry} disabled={retrying}>{retrying ? <LoaderCircle className="spin" size={17} /> : <RotateCcw size={17} />}{retrying ? "正在继续" : "继续任务"}</button><button className="quiet-button" onClick={onHome}>返回首页</button></footer></section><div className="network-danger-notice"><ShieldCheck size={17} /><span><strong>安全边界未变化：</strong>日志中不会显示 Cookie、请求 Header、CDN 地址或下载目录绝对路径。</span></div></main>;
  }
  return <main className="network-page network-task-page"><header className="network-task-header"><div><p className="eyebrow">网络转写 · {task.source?.platform_label}</p><h1>{task.source?.name}</h1><p>{task.download_mode === "keep_video" ? "保留原视频" : "仅转写"}模式 · {formatDuration(task.source?.duration_seconds)} · 任务 ID：{task.id}</p></div><button className="quiet-button" onClick={onHome}>返回首页</button></header><TaskTimeline task={task} /><div className="network-task-grid"><section className="network-task-panel"><div className="network-task-title"><div><p className="eyebrow">{task.stage}</p><h2>{downloading ? "保留可恢复的下载片段" : task.message}</h2></div><strong>{displayPercent}%</strong></div><div className="home-progress large"><span style={{ width: `${displayPercent}%` }} /></div><p className="network-task-note">{speed} · {downloaded ? `已下载 ${downloaded} · ` : ""}{eta}。下载、识别与内容整理都属于同一个可恢复任务。</p><div className="network-task-log"><p>✓ 已确认来源：{task.source?.platform_label} / {task.source?.content_id}</p><p className="current">● {task.message}</p><p>○ 不保存 Cookie、请求 Header 或带查询参数的分享链接</p></div><TaskLogs logs={task.logs} /><div className="network-artifacts"><div><span>来源清单</span><b>已写入 · 已脱敏</b></div><div><span>媒体下载片段</span><b>{stageIndex > 1 ? "已完成" : "可断点续传"}</b></div><div><span>Whisper JSON</span><b>{stageIndex > 3 ? "已生成" : "尚未生成"}</b></div></div></section><aside><div className="home-boundary"><ShieldCheck size={17} /><span><strong>恢复语义：</strong>若在后续识别或整理阶段失败，已验证媒体不会重新下载。</span></div><div className="network-help"><h2>本次来源</h2><ul><li>模式：{task.download_mode === "keep_video" ? "保留原视频" : "仅转写"}</li><li>保存：网络来源目录</li><li>封面：来源封面随任务缓存</li></ul></div></aside></div></main>;
}

function HistoryView({ history, selected, markdown, settings, onOpen, onCopy, onImport, onSettings }) {
  return <main className="history-view">
    <header className="view-heading"><p className="eyebrow">已完成的文稿</p><h1>回到任何一次转写</h1><p>所有记录都从本机输出目录读取，可继续浏览、导出或导入知识库。</p></header>
    {!history.length ? <section className="history-empty"><BookOpen size={31} /><h2>还没有可阅读的转写结果</h2><p>完成第一份视频转写后，它会自动出现在这里。</p></section> : <section className="history-layout"><aside className="history-list" aria-label="转写历史列表">{history.map((record) => <button className={selected?.id === record.id ? "history-item selected" : "history-item"} key={record.id} onClick={() => onOpen(record)}><div className="history-cover"><Cover src={record.cover_url} /></div><div><strong>{record.title}</strong><span>{record.source_name}</span><small><Clock3 size={12} />{formatDate(record.completed_at)}　·　{record.model}</small></div></button>)}</aside><div className="history-reader">{selected ? <DocumentReader markdown={markdown} record={{ ...selected, kind: "history" }} settings={settings} onCopy={onCopy} onImport={onImport} onSettings={onSettings} /> : <div className="history-select"><BookOpen size={30} /><h2>选择一份文稿开始阅读</h2><p>右侧会显示完整正文、章节大纲与交付操作。</p></div>}</div></section>}
  </main>;
}

function SettingsView({ settings, setSettings, onSave, onPickVault, onPickDownloadDirectory, onSaveKey, onDeleteKey, saving, toast }) {
  const [keyInput, setKeyInput] = useState("");
  if (!settings) return <div className="loading-page"><LoaderCircle className="spin" />正在读取本机设置…</div>;
  const update = (key, value) => setSettings({ ...settings, [key]: value });
  return <main className="settings-view">
    <header className="view-heading"><p className="eyebrow">本机配置</p><h1>让工具按你的方式工作</h1><p>普通设置保存在本机应用目录；Gemini 凭据只保存在 macOS Keychain。</p></header>
    <section className="settings-section network-storage-setting"><div className="section-heading"><HardDrive size={19} /><div><h2>网络媒体保存位置</h2><p>同一来源重试或升级为“保留原视频”时，会继续复用已有产物。</p></div></div><div className="vault-row"><div><span>{settings.network_download_dir || "尚未选择下载目录"}</span><small>{settings.network_downloader?.installed ? `yt-dlp ${settings.network_downloader.version} 已就绪` : "网络下载组件尚未安装"}</small></div><button className="quiet-button" onClick={onPickDownloadDirectory}><FolderOpen size={16} />更改位置</button></div><div className="network-settings-boundary"><ShieldCheck size={16} /><span><strong>首版支持：</strong>YouTube、B站、抖音公开单视频；不支持 Cookie、登录、播放列表、直播和受限内容。</span></div></section>
    <section className="settings-section"><div className="section-heading"><SlidersHorizontal size={19} /><div><h2>文本模型</h2><p>选择本次转写使用的编辑模型。</p></div></div><div className="provider-switch" role="group" aria-label="文本模型提供方">{[["gemini", "Gemini"], ["ollama", "本机 Ollama"]].map(([value, label]) => <button key={value} className={settings.provider === value ? "selected" : ""} onClick={() => update("provider", value)}>{label}</button>)}</div>{settings.provider === "gemini" ? <div className="settings-grid"><label>Gemini 模型<select value={settings.gemini_model} onChange={(event) => update("gemini_model", event.target.value)}>{settings.gemini_models.map((model) => <option key={model}>{model}</option>)}</select></label><label>思考预算<select value={settings.gemini_thinking_budget} onChange={(event) => update("gemini_thinking_budget", Number(event.target.value))}><option value={0}>关闭（推荐）</option><option value={1024}>1,024 tokens</option><option value={4096}>4,096 tokens</option></select></label><label>温度<select value={settings.gemini_temperature} onChange={(event) => update("gemini_temperature", Number(event.target.value))}><option value={0}>0（稳定）</option><option value={0.2}>0.2</option><option value={0.5}>0.5</option></select></label></div> : <label className="settings-field">本机模型<input value={settings.ollama_model} onChange={(event) => update("ollama_model", event.target.value)} placeholder="qwen2.5:14b-instruct" /></label>}<div className="key-row"><div><KeyRound size={18} /><span>Gemini API Key</span><small className={settings.gemini_key_configured ? "configured" : ""}>{settings.gemini_key_configured ? "已安全保存在 Keychain" : "尚未配置"}</small></div><div className="key-actions"><input type="password" value={keyInput} onChange={(event) => setKeyInput(event.target.value)} placeholder="粘贴新的 API Key" aria-label="Gemini API Key" /><button className="quiet-button" onClick={() => { onSaveKey(keyInput); setKeyInput(""); }} disabled={!keyInput}>保存</button>{settings.gemini_key_configured && <button className="icon-button danger" aria-label="删除 Gemini API Key" onClick={onDeleteKey}><Trash2 size={17} /></button>}</div></div></section>
    <section className="settings-section"><div className="section-heading"><FolderOpen size={19} /><div><h2>Obsidian</h2><p>导入时只会向你明确选择的 Vault 写入 Markdown。</p></div></div><div className="vault-row"><div><span>{settings.obsidian_vault || "尚未选择 Vault"}</span>{settings.obsidian_vault && <small>{settings.obsidian_subdir ? `子目录：${settings.obsidian_subdir}` : "根目录"}</small>}</div><button className="quiet-button" onClick={onPickVault}><FolderOpen size={16} />选择 Vault</button></div><label className="settings-field">导入子目录（可选）<input value={settings.obsidian_subdir} onChange={(event) => update("obsidian_subdir", event.target.value)} placeholder="例如：收件箱/视频转写" /></label></section>
    <div className="settings-footer"><button className="primary-button" onClick={onSave} disabled={saving}><Save size={17} />{saving ? "正在保存" : "保存设置"}</button>{toast && <span className="inline-toast">{toast}</span>}</div>
  </main>;
}

export function App() {
  const [view, setView] = useState("home");
  const [theme, setTheme] = useState(() => window.localStorage.getItem("quiet-transcript-theme") === "dark" ? "dark" : "light");
  const [settings, setSettings] = useState(null);
  const [selectedVideo, setSelectedVideo] = useState(null);
  const [task, setTask] = useState(null);
  const [markdown, setMarkdown] = useState("");
  const [history, setHistory] = useState([]);
  const [selectedHistory, setSelectedHistory] = useState(null);
  const [historyMarkdown, setHistoryMarkdown] = useState("");
  const [dashboard, setDashboard] = useState(null);
  const [toast, setToast] = useState("");
  const [saving, setSaving] = useState(false);
  const [startingTask, setStartingTask] = useState(false);

  const showToast = (message) => { setToast(message); window.setTimeout(() => setToast(""), 3600); };
  const loadHistory = async () => { try { setHistory((await api("/api/history")).records); } catch (error) { showToast(error.message); } };
  const loadDashboard = async () => { try { const next = await api("/api/dashboard"); setDashboard(next); setTask((current) => current || next.current_task); if (next.current_task?.has_markdown) loadMarkdown(next.current_task.id); } catch (error) { showToast(error.message); } };
  const loadMarkdown = async (id) => { try { setMarkdown(await api(`/api/tasks/${encodeURIComponent(id)}/markdown`)); } catch { setMarkdown(""); } };
  const openHistory = async (record) => { setSelectedHistory(record); setHistoryMarkdown(""); try { setHistoryMarkdown(await api(`/api/history/${encodeURIComponent(record.id)}/markdown`)); } catch (error) { showToast(error.message); } };
  useEffect(() => {
    api("/api/settings").then(setSettings).catch((error) => showToast(error.message));
    loadDashboard();
  }, []);
  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    window.localStorage.setItem("quiet-transcript-theme", theme);
  }, [theme]);
  useEffect(() => {
    if (!task?.id || !["queued", "running"].includes(task.status)) return undefined;
    const events = new EventSource(`/api/tasks/${encodeURIComponent(task.id)}/events`);
    events.addEventListener("task", (event) => { const next = JSON.parse(event.data); setTask(next); if (next.status === "completed") { loadMarkdown(next.id); loadHistory(); loadDashboard(); } });
    events.onerror = () => events.close();
    return () => events.close();
  }, [task?.id, task?.status]);

  const chooseVideo = async () => { try { const result = await api("/api/picker/video", { method: "POST" }); if (!result.cancelled) setSelectedVideo(result.video); } catch (error) { showToast(error.message); } };
  const startTask = async () => {
    if (startingTask) return;
    setStartingTask(true);
    try {
      const next = task?.can_retry && (task.source_kind === "network" || !selectedVideo)
        ? await api(`/api/tasks/${encodeURIComponent(task.id)}/retry`, { method: "POST" })
        : await api("/api/tasks", { method: "POST", body: JSON.stringify({ source: selectedVideo.path }) });
      setTask(next); setMarkdown("");
    } catch (error) { showToast(error.message); }
    finally { setStartingTask(false); }
  };
  const startNetworkTask = async (media, mode) => { const next = await api("/api/network/tasks", { method: "POST", body: JSON.stringify({ media, mode }) }); setSelectedVideo(null); setTask(next); setMarkdown(""); setView("workbench"); };
  const saveSettings = async () => { setSaving(true); try { setSettings(await api("/api/settings", { method: "PUT", body: JSON.stringify(settings) })); showToast("设置已保存在本机。"); } catch (error) { showToast(error.message); } finally { setSaving(false); } };
  const pickVault = async () => { try { const result = await api("/api/picker/vault", { method: "POST" }); if (!result.cancelled) setSettings({ ...settings, obsidian_vault: result.path }); } catch (error) { showToast(error.message); } };
  const pickDownloadDirectory = async () => { try { const result = await api("/api/picker/download-directory", { method: "POST" }); if (!result.cancelled) setSettings({ ...settings, network_download_dir: result.path }); } catch (error) { showToast(error.message); } };
  const saveKey = async (apiKey) => { try { await api("/api/settings/gemini-key", { method: "PUT", body: JSON.stringify({ api_key: apiKey }) }); setSettings({ ...settings, gemini_key_configured: true }); showToast("Gemini Key 已保存到 macOS Keychain。"); } catch (error) { showToast(error.message); } };
  const deleteKey = async () => { try { await api("/api/settings/gemini-key", { method: "DELETE" }); setSettings({ ...settings, gemini_key_configured: false }); showToast("Gemini Key 已从 Keychain 删除。"); } catch (error) { showToast(error.message); } };
  const copyMarkdown = async (content) => { try { await navigator.clipboard.writeText(content); showToast("已复制完整 Markdown。"); } catch { showToast("浏览器没有授予剪贴板权限。请使用下载文件。"); } };
  const importDocument = async (record) => { const base = record?.kind === "history" ? "/api/history" : "/api/tasks"; try { const result = await api(`${base}/${encodeURIComponent(record.id)}/obsidian`, { method: "POST" }); showToast(`已写入 Obsidian：${result.name}`); } catch (error) { showToast(error.message); } };
  const openHistoryFromHome = (record) => { setView("history"); openHistory(record); loadHistory(); };
  const running = task?.status === "running" || task?.status === "queued";
  const taskRecord = task ? { id: task.id, kind: "task" } : null;

  return <div className="app-shell">
    <aside className="sidebar"><div className="brand"><span className="brand-mark"><Leaf size={25} fill="currentColor" /></span><div><strong>Quiet Transcript</strong><small>安静地，把视频变成文字</small></div></div><nav aria-label="主导航"><button className={view === "home" ? "nav-item selected" : "nav-item"} onClick={() => { setView("home"); loadDashboard(); }}><Home size={19} />首页</button><button className={view === "workbench" ? "nav-item selected" : "nav-item"} onClick={() => setView("workbench")}><FileText size={19} />转写工作台</button><button className={view === "history" ? "nav-item selected" : "nav-item"} onClick={() => { setView("history"); loadHistory(); }}><Clock3 size={19} />历史记录</button><button className={view === "settings" ? "nav-item selected" : "nav-item"} onClick={() => setView("settings")}><Settings size={19} />设置</button><button className="nav-item theme-toggle" aria-label={theme === "dark" ? "切换至浅色模式" : "切换至夜间模式"} aria-pressed={theme === "dark"} onClick={() => setTheme((current) => current === "dark" ? "light" : "dark")}>{theme === "dark" ? <Sun size={19} /> : <Moon size={19} />}<span>{theme === "dark" ? "浅色模式" : "夜间模式"}</span></button></nav><div className="sidebar-footer"><span><CircleDot size={11} fill="currentColor" />本机工作台 · 安全控制</span><small>macOS · Apple Silicon</small></div></aside>
    <div className="page-shell">{view === "settings" ? <SettingsView settings={settings} setSettings={setSettings} onSave={saveSettings} onPickVault={pickVault} onPickDownloadDirectory={pickDownloadDirectory} onSaveKey={saveKey} onDeleteKey={deleteKey} saving={saving} toast={toast} /> : view === "history" ? <HistoryView history={history} selected={selectedHistory} markdown={historyMarkdown} settings={settings} onOpen={openHistory} onCopy={copyMarkdown} onImport={importDocument} onSettings={() => setView("settings")} /> : view === "network" ? <NetworkImportView settings={settings} onBack={() => setView("home")} onCreate={startNetworkTask} /> : view === "home" ? <HomeView video={selectedVideo} task={task} dashboard={dashboard} onPick={chooseVideo} onStart={startTask} onOpenNetwork={() => setView("network")} onOpenHistory={openHistoryFromHome} onViewHistory={() => { setView("history"); loadHistory(); }} onWorkbench={() => setView("workbench")} /> : task?.source_kind === "network" && task.status !== "completed" ? <NetworkTaskView task={task} onRetry={startTask} onHome={() => setView("home")} retrying={startingTask} /> : <main className="workbench"><header className="hero"><p className="eyebrow">{task?.source_kind === "network" ? "网络视频转写" : "本地视频转写"}</p><h1>把视频变成一篇好读的文章</h1></header><VideoCard video={selectedVideo} task={task} onPick={chooseVideo} onStart={startTask} disabled={running} /><TaskTimeline task={task} />{task?.status === "failed" && <div className="failure"><AlertCircle size={19} /><div><strong>{task.stage}</strong><p>{task.error}</p></div></div>}{running && <section className="progress-panel"><div className="progress-heading"><div><Sparkles size={22} /><div><strong>{task.stage}</strong><span>{task.message}</span></div></div><span>{task.percent}%</span></div><div className="progress-track"><span style={{ width: `${task.percent}%` }} /></div><div className="progress-meta">{task.block_total ? `已完成 ${task.block_index} / ${task.block_total} 组文字整理` : "任务在本机运行；完成后会自动显示 Markdown。"}<details><summary>查看运行日志 <ChevronDown size={14} /></summary><pre>{task.logs.join("\n") || "正在等待第一条日志…"}</pre></details></div></section>}<DocumentReader markdown={markdown} record={taskRecord} settings={settings} onCopy={copyMarkdown} onImport={importDocument} onSettings={() => setView("settings")} /></main>}</div>
    {toast && <div className="toast" role="status">{toast}</div>}
  </div>;
}
