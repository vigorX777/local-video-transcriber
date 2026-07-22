# Local Video Transcriber

在 Apple Silicon Mac 上本地完成视频语音识别，再生成经过翻译、润色和章节整理的中文 JSON 与 Markdown。既可以使用命令行，也可以通过仅本机访问的浏览器工作台操作。

## 当前状态

默认流程由 Gemini 2.5 Flash 负责英文翻译、中文润色、总标题和章节标题；Whisper 原始 JSON、时间轴与验证仍保留在本机。浏览器工作台支持选择本地视频，或粘贴 YouTube、B站、抖音的公开单视频链接，随后统一查看下载、识别和整理进度，并预览、下载、复制或导入 Markdown 到 Obsidian。

输入视频位于项目外部，例如 `/path/to/video.mp4`。

项目不会复制或修改用户选择的本地原视频。网络导入的媒体默认保存在 `~/Movies/Quiet Transcript/`，模型文件、中间音频、网络媒体和转写结果均不提交 Git。

## 使用

首次执行会安装 Python Web 依赖、前端依赖、`ffmpeg`、`whisper-cpp`，下载并校验官方 `yt-dlp_macos`，以及约 1.6GB 的 Whisper 模型：

```bash
./scripts/setup.sh
```

一键启动并打开浏览器工作台：

```bash
./start-workbench.sh
```

它会复用已运行的本机工作台；若服务尚未启动，则注册项目专属的 macOS 用户级后台服务后自动打开 <http://127.0.0.1:8765>。服务只在本机回环地址运行，日志位于 `work/web-server-8765.log`。

如需在当前终端查看服务日志或用 `Ctrl+C` 停止服务：

```bash
./scripts/start-web.sh
```

服务只监听本机回环地址；在“设置”中保存 Gemini Key 时，凭据只进入 macOS Keychain，不会写入项目、日志或最终 JSON。首次导入 Obsidian 时，在设置页选择 Vault 和可选子目录。

网络视频可从首页选择“粘贴视频链接”：先验证公开视频的标题、作者、时长和平台，再选择下载模式后创建任务。

- “仅转写”是默认模式，只保存最佳音频与来源封面。
- “保留原视频”保存最高 1080p 视频；同一来源已有文稿时只补视频，不重复 ASR 或 Gemini。
- 首版仅支持公开的 YouTube、B站和抖音单视频 / 单作品，不支持 Cookie、登录、播放列表、批量、直播、付费、私密、地区受限或 DRM 内容。
- 下载、Whisper 和 Gemini 属于同一条七阶段时间线；失败后点击“继续任务”会复用已经完成的下载、音频、Whisper 与 Gemini 缓存。

先用前 60 秒验证本机环境：

```bash
read -s GEMINI_API_KEY
export GEMINI_API_KEY
./scripts/test.sh '/path/to/video.mp4'
```

执行完整转写：

```bash
./scripts/transcribe-video.sh '/path/to/video.mp4'
```

命令行模式下，`GEMINI_API_KEY` 只从当前终端环境读取，不写入项目文件。若 Gemini 暂不可用，可显式回退到本地 Qwen：

```bash
TRANSCRIPT_PROVIDER=ollama ./scripts/transcribe-video.sh '/path/to/video.mp4'
```

每次任务的时间轴证据位于 `outputs/<video-name>/transcript.final.json`；阅读与导入交付物为从它生成的 `transcript.final.md`。Whisper 原始 JSON 仅作为 `work/` 中的中间证据保留。旧版 SRT 字幕仍在输出目录中，仅用于回退。

升级后的流程会复用已有有效 WAV 和 Whisper JSON，避免重复执行 ASR。首次 Gemini 成功写入前，现有 Qwen 最终 JSON 会备份为 `transcript.qwen.json`；Gemini 候选结果通过完整校验后才原子替换 `transcript.final.json`。现有 SRT 脚本在迁移阶段保留作为回退，不再作为默认输出路径。

## 文档

- [设计记录](docs/design.md)
