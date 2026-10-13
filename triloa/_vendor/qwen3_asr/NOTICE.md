# Qwen3-ASR Transformers backend

The Python files in this directory are copied unchanged from Alibaba Qwen's
`qwen-asr` 0.0.6 wheel (Apache-2.0). Copyright notices are retained in each file.

Upstream: https://github.com/QwenLM/Qwen3-ASR

Wheel SHA256: `b9c55a38413298f3a990a4475467399daec6e8f4172363053fc42e2166c2dfd3`

Triloa uses only the model, configuration and processor classes, with its own
local audio capture and subtitle adapter in `triloa/qwen_asr.py`. This avoids
installing the upstream demos, forced aligner, Japanese tokenization runtime
and vLLM for Windows speech recognition. Model weights are downloaded separately.
