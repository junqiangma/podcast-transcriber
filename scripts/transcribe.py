#!/usr/bin/env python3
"""
小宇宙播客转逐字稿 (CI 版)
基于 podcast-extractor 技能 turbo_pipeline v4.2 的「解析链接 + 转录」部分改造。

流程: 解析小宇宙直链 -> 下载音频 -> 切分15分钟段 -> faster-whisper 转录
输出: <输出目录>/transcription.txt (带时间戳逐字稿)

用法:
  python scripts/transcribe.py <小宇宙链接> [输出目录] [--beam N] [--model tiny|base|small]
"""
import sys
import os
import subprocess
import gc
import time
import re
import threading

CHUNK_SECONDS = 900  # 15分钟/段

# GitHub Actions 海外 runner 直连 HuggingFace 即可;
# 国内本地运行时取消下一行注释使用镜像:
# os.environ['HF_ENDPOINT'] = 'https://hf-mirror.com'


def fetch_episode_page(xiaoyuzhou_url):
    """抓取节目页, 返回 (音频直链, 标题)"""
    import requests

    headers = {'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
                             'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36'}
    resp = requests.get(xiaoyuzhou_url, headers=headers, timeout=30)
    html = resp.text

    audio_url = None
    match = re.search(r'https://media\.xyzcdn\.net/[^"\s\\]+\.m4a', html)
    if match:
        audio_url = match.group(0)

    title = None
    tmatch = re.search(r'"title"\s*:\s*"([^"]+)"', html)
    if tmatch:
        title = tmatch.group(1)

    return audio_url, title


def resolve_audio_url(xiaoyuzhou_url):
    """解析音频直链: 优先节目页直取, 回退 xyzdownloader"""
    import requests
    from urllib.parse import quote

    print("[解析] 尝试直接解析节目页...")
    try:
        audio_url, title = fetch_episode_page(xiaoyuzhou_url)
        if title:
            print("[解析] 节目标题: {}".format(title))
        if audio_url:
            print("[解析] 直链获取成功 (节目页)")
            return audio_url, title
    except Exception as e:
        print("[解析] 节目页抓取异常: {}".format(e))

    print("[解析] 回退 xyzdownloader 解析...")
    headers = {'User-Agent': 'Mozilla/5.0'}
    parse_url = "https://xyzdownloader.xyz/zh-CN?q={}".format(quote(xiaoyuzhou_url, safe=''))
    resp = requests.get(parse_url, headers=headers, timeout=30)
    match = re.search(r'https://media\.xyzcdn\.net/[^"\s\\]+\.m4a', resp.text)
    if not match:
        raise ValueError("无法提取音频链接，请检查链接是否正确")
    print("[解析] 直链获取成功 (xyzdownloader)")
    return match.group(0), None


def download_audio(xiaoyuzhou_url, out_dir):
    """解析并下载音频, 返回 (音频路径, 标题)"""
    import requests
    audio_link, title = resolve_audio_url(xiaoyuzhou_url)
    audio_path = os.path.join(out_dir, "episode.m4a")
    r = requests.get(audio_link, stream=True, timeout=180,
                     headers={'User-Agent': 'Mozilla/5.0'})
    r.raise_for_status()
    with open(audio_path, "wb") as f:
        for chunk in r.iter_content(chunk_size=8192):
            f.write(chunk)
    size_mb = os.path.getsize(audio_path) / (1024 * 1024)
    print("[下载] 完成: {:.1f}MB".format(size_mb))
    return audio_path, title


def preload_model(model_size):
    """后台线程: 预下载模型 (与音频下载并行)"""
    try:
        from huggingface_hub import snapshot_download
        repo = {'tiny': 'Systran/faster-whisper-tiny',
                'base': 'Systran/faster-whisper-base',
                'small': 'Systran/faster-whisper-small'}[model_size]
        print("[模型] 后台预下载 {} ...".format(model_size))
        snapshot_download(repo)
        print("[模型] 预下载完成")
    except Exception as e:
        print("[模型] 预下载失败(不影响, 加载时会重试): {}".format(e))


def split_audio(m4a_path, out_dir):
    """直接从M4A切分为15分钟段 (不生成中间WAV大文件)"""
    print("\n[切分] 音频预处理...")
    seg_dir = os.path.join(out_dir, "segments")
    os.makedirs(seg_dir, exist_ok=True)
    subprocess.run([
        "ffmpeg", "-y", "-v", "error", "-i", m4a_path,
        "-ar", "16000", "-ac", "1",
        "-f", "segment", "-segment_time", str(CHUNK_SECONDS),
        "-c:a", "pcm_s16le",
        os.path.join(seg_dir, "chunk_%03d.wav")
    ], capture_output=True, check=True)
    chunks = sorted([f for f in os.listdir(seg_dir) if f.endswith('.wav')])
    print("[切分] 完成: {}段 x {}分钟".format(len(chunks), CHUNK_SECONDS // 60))
    return seg_dir, chunks


def transcribe(seg_dir, chunks, out_file, model_size, beam_size, title, source_url):
    """逐段转录: VAD + cond_prev=False + 可调beam, 每段后gc"""
    from faster_whisper import WhisperModel

    print("\n[模型] 加载 {} ...".format(model_size))
    model = WhisperModel(model_size, device='cpu', compute_type='int8')
    print("[模型] 加载成功 (beam_size={}, VAD=on, cond_prev=off)".format(beam_size))

    total_segments = 0
    start_all = time.time()

    with open(out_file, 'w', encoding='utf-8') as f:
        f.write('# {}\n'.format(title or 'Podcast Transcription'))
        f.write('# Source: {}\n'.format(source_url))
        f.write('# Generated: {} UTC\n'.format(time.strftime('%Y-%m-%d %H:%M:%S', time.gmtime())))
        f.write('# Engine: faster-whisper {} beam{} + VAD\n\n'.format(model_size, beam_size))

        for i, chunk in enumerate(chunks):
            offset = i * CHUNK_SECONDS
            print('[{}/{}] 转录 {}...'.format(i + 1, len(chunks), chunk), flush=True)
            chunk_start = time.time()
            try:
                segments, info = model.transcribe(
                    os.path.join(seg_dir, chunk),
                    language='zh',
                    beam_size=beam_size,
                    vad_filter=True,
                    vad_parameters=dict(min_silence_duration_ms=500),
                    condition_on_previous_text=False,
                    initial_prompt='以下是简体中文播客访谈内容，使用规范简体字。',
                )
                count = 0
                for seg in segments:
                    line = '[{:07.1f}s -> {:07.1f}s] {}'.format(
                        seg.start + offset, seg.end + offset, seg.text.strip())
                    f.write(line + '\n')
                    count += 1
                f.flush()
                total_segments += count
                elapsed = time.time() - chunk_start
                print('  {} segments ({:.1f}s)'.format(count, elapsed), flush=True)
                del segments
                gc.collect()
            except Exception as e:
                print('  [错误] {} 转录失败: {}'.format(chunk, e), flush=True)
                continue

    total_time = time.time() - start_all
    print('\n[转录] 完成! 共{}个片段, 耗时{:.1f}分钟'.format(total_segments, total_time / 60))
    return total_segments


def parse_args():
    args = [a for a in sys.argv[1:] if not a.startswith('--')]
    beam = 2
    model_size = 'base'
    for i, a in enumerate(sys.argv):
        if a == '--beam' and i + 1 < len(sys.argv):
            beam = int(sys.argv[i + 1])
        if a == '--model' and i + 1 < len(sys.argv):
            model_size = sys.argv[i + 1]
    return args, model_size, beam


def main():
    args, model_size, beam = parse_args()
    if len(args) < 1:
        print("用法: python scripts/transcribe.py <小宇宙链接> [输出目录] [--beam N] [--model tiny|base|small]")
        sys.exit(1)

    url = args[0]
    out_dir = args[1] if len(args) > 1 else "output"
    os.makedirs(out_dir, exist_ok=True)
    start_all = time.time()

    try:
        # Step 1: 并行下载 — 音频 (主线程) + 模型 (后台线程)
        print("\n" + "=" * 60)
        print("Step 1: 解析下载 (音频 + 模型并行)")
        print("=" * 60)
        model_thread = threading.Thread(target=preload_model, args=(model_size,))
        model_thread.start()
        audio_path, title = download_audio(url, out_dir)
        model_thread.join()

        # Step 2: 切分
        print("\n" + "=" * 60)
        print("Step 2: 音频切分")
        print("=" * 60)
        seg_dir, chunks = split_audio(audio_path, out_dir)

        # Step 3: 转录
        print("\n" + "=" * 60)
        print("Step 3: Whisper 转录")
        print("=" * 60)
        trans_file = os.path.join(out_dir, "transcription.txt")
        transcribe(seg_dir, chunks, trans_file, model_size, beam, title, url)

        # 供 GitHub Actions 读取标题 (写入 GITHUB_OUTPUT)
        github_output = os.environ.get('GITHUB_OUTPUT')
        if github_output and title:
            with open(github_output, 'a', encoding='utf-8') as f:
                f.write('episode_title={}\n'.format(title))

        elapsed = time.time() - start_all
        print("\n" + "=" * 60)
        print("全部完成! 总耗时: {:.1f}分钟".format(elapsed / 60))
        print("输出文件: {}".format(trans_file))
        print("=" * 60)

    except Exception as e:
        print("\n[错误] {}".format(e))
        import traceback
        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()
