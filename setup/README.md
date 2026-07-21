# 一次性设置（约 30 秒）

由于 GitHub 安全限制，工作流文件无法通过 API 直接写入 `.github/workflows/` 目录，需要在网页端手动挪一下位置：

1. 打开本目录下的 `transcribe.yml`
2. 点击右上角的编辑（铅笔图标）
3. 把文件名从 `setup/transcribe.yml` 改为 `.github/workflows/transcribe.yml`
   （直接输入，GitHub 会自动识别斜杠为目录）
4. 页面底部点 **Commit changes**

完成后，本 `setup/` 目录可以删除。之后在 Actions 标签页即可看到「小宇宙播客转逐字稿」工作流。
