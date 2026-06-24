# 02 — Server Load Test Results

Server: `python -m llama_cpp.server` (llama-cpp-python 0.3.19, CPU/AVX2) on `127.0.0.1:8080`.
Model: `qwen2.5-1.5b-instruct-q4_k_m.gguf` · `n_threads=6` · `n_ctx=2048` · `n_gpu_layers=0`.
Hardware: AMD Ryzen 5 5500U (6c/12t), 15.3 GB RAM, no GPU offload (CPU wheel).
Load generator: `locust -f 02-llama-cpp-server/load-test.py --headless -r 1 -t 1m` (80% short / 20% long-RAG mix).

## Aggregated results

| Concurrency | # reqs | # fails | P50 (ms) | P95 (ms) | Max (ms) | req/s |
|---|---:|---:|---:|---:|---:|---:|
| `-u 10` | 12 | 0 (0.00%) | 25000 | 46000 | 45754 | 0.21 |
| `-u 50` | 19 | 0 (0.00%) | 20000 | 44000 | 44253 | 0.33 |

(P95 from locust's "Response time percentiles (approximated)" aggregated row.)

## Per-endpoint P95 (ms)

| Concurrency | short P95 | long-rag P95 |
|---|---:|---:|
| `-u 10` | 42000 | 46000 |
| `-u 50` | 44000 | 38000 |

## Observation — no continuous batching

Going from 10 → 50 concurrent users barely changed total throughput (12 → 19
completed requests in 60s) and did **not** improve P95. The Python
`llama_cpp.server` decodes requests **serially** on CPU with a single slot, so
extra concurrency only deepens the queue — goodput is capped by single-stream
decode speed (~25 tok/s for Q4_K_M, from Track 01). This is the textbook
motivation for **continuous batching / PagedAttention** (deck §2): to raise
goodput under load you need the server to interleave decode across many
sequences in one forward pass, which requires the native `llama-server`
(`--parallel N`, `--cont-batching`) built from source — see `make build-llama` /
`make serve-native`. The Python server has no `/metrics` endpoint, so
`n_busy_slots_per_decode` cannot be observed here.

NOTE: take screenshots `04-locust-10.png` and `05-locust-50.png` of the locust
summary tables for rubric Q7 + Q8.
