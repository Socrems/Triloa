"""Install the multilingual base ASR model under the project model directory."""

from __future__ import annotations

from .paths import MODELS, configure_paths


def main() -> None:
    configure_paths()
    destination = MODELS / "faster-whisper" / "base"
    required = ("model.bin", "config.json", "tokenizer.json", "vocabulary.txt")
    if all((destination / name).is_file() for name in required):
        print("本地语音模型已经安装，跳过下载。", flush=True)
        return

    from huggingface_hub import snapshot_download

    print(f"正在下载多语言语音模型到 {destination}", flush=True)
    snapshot_download(
        repo_id="Systran/faster-whisper-base",
        local_dir=str(destination),
        allow_patterns=list(required),
    )
    if not all((destination / name).is_file() for name in required):
        raise RuntimeError("语音模型下载不完整")
    print("本地语音模型安装完成。", flush=True)


if __name__ == "__main__":
    main()
