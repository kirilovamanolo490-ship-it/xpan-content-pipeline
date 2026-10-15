# 首视频下载器依赖

来源：Cp0204/quark_auto_save。上游仓库：https://github.com/Cp0204/quark_auto_save 。许可证见 `LICENSE`。

本项目仅保留 `download_first_video.py`、`quark_auto_save.py`、依赖清单和许可证。下载助手包含本项目的固定 FID、文件名/大小核对、分段续传与网络重试修改。

由现有发布流水线使用根 `.venv` 调用，认证配置通过 `--config config/quark-storage.json` 显式传入。不要在本目录重复安装 Python 环境。完整运行规则见根 README 和 `.codex/skills/telegram-auto-publish/SKILL.md`。
