# 小宇宙播客转逐字稿

给小宇宙播客链接，自动还你一份带时间戳的完整逐字稿。**全程在 GitHub 网页端操作，无需安装任何东西。**

## ⚡ 首次使用：一次性设置（约 30 秒）

由于 GitHub 安全限制，工作流文件需要先手动就位一次：打开 [`setup/transcribe.yml`](setup/transcribe.yml)，按该目录下的说明，把文件重命名移动到 `.github/workflows/transcribe.yml` 并提交即可。之后永久可用。

## 使用方法（二选一）

### 方式一：Actions 手动触发（推荐）

1. 打开本仓库的 **Actions** 标签页
2. 左侧选择 **「小宇宙播客转逐字稿」**
3. 点击 **Run workflow**，粘贴小宇宙节目链接
4. 等待运行完成（时间预估见下表）

### 方式二：开 Issue 触发

新建一个 Issue，正文中贴上小宇宙链接即可。转录完成后机器人会自动在 Issue 下评论，附上逐字稿链接。

## 结果在哪看

- **仓库 `transcripts/` 目录**：逐字稿自动提交回仓库，按时间戳命名
- **Artifact**：在运行记录页面可下载（保留 30 天）

## 转录时间预估

GitHub 免费 runner（2 核 CPU）+ base 模型 + 均衡档实测参考：

| 播客时长 | 预计耗时 |
|---------|---------|
| 30 分钟 | ~5 分钟 |
| 60 分钟 | ~10 分钟 |
| 90 分钟 | ~14 分钟 |
| 120 分钟 | ~18 分钟 |

## 参数说明

| 参数 | 选项 | 说明 |
|------|------|------|
| model | `base`（默认）/ `small` / `tiny` | small 更准但慢一倍；tiny 精度不足不推荐 |
| beam | `2`（默认）/ `1` / `5` | 1=极速档，5=保守档，默认 2 是速度与精度平衡点 |

## 本地运行

```bash
pip install -r requirements.txt
# 需要系统已安装 ffmpeg
python scripts/transcribe.py <小宇宙链接> output --model base --beam 2
```

国内本地运行时如 HuggingFace 模型下载超时，取消 `scripts/transcribe.py` 顶部 `HF_ENDPOINT` 镜像行的注释。

## 技术栈

- 直链解析：直接解析小宇宙节目页内嵌的 `media.xyzcdn.net` 音频直链（回退 xyzdownloader）
- 音频预处理：ffmpeg 直接从 M4A 切分为 15 分钟 16kHz 单声道片段
- 语音识别：faster-whisper（VAD 过滤静音 + beam 可调，实测较朴素配置提速 1.7-2.1x 且精度无损）

## License

MIT
