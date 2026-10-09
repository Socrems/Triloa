"""Download required Argos packages once; normal translation stays offline."""

from __future__ import annotations

from .paths import configure_paths


def main() -> None:
    configure_paths()
    from argostranslate import package

    required = (("en", "zh"), ("ja", "en"))
    installed = {(item.from_code, item.to_code) for item in package.get_installed_packages()}
    if all(pair in installed for pair in required):
        print("离线模型已经安装，跳过下载。", flush=True)
        return
    package.update_package_index()
    available = package.get_available_packages()
    for source, target in required:
        if (source, target) in installed:
            continue
        candidate = next((item for item in available if item.from_code == source and item.to_code == target), None)
        if candidate is None:
            raise RuntimeError(f"模型索引没有 {source}→{target} 包")
        print(f"下载 {source}→{target} 模型到项目模型目录…", flush=True)
        package.install_from_path(candidate.download())
    print("离线翻译模型安装完成。", flush=True)


if __name__ == "__main__":
    main()
