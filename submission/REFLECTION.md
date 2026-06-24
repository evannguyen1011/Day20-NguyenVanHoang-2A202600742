# Reflection — Lab 20 (Personal Report)

> **Đây là báo cáo cá nhân.** Mỗi học viên chạy lab trên laptop của mình, với spec của mình. Số liệu của bạn không so sánh được với bạn cùng lớp — chỉ so sánh **before vs after trên chính máy bạn**. Grade rubric tính theo độ rõ ràng của setup + tuning của bạn, không phải tốc độ tuyệt đối.

---

**Họ Tên:** Nguyễn Văn Hoàng (MSSV 2A202600742)
**Cohort:** _<điền cohort của bạn, vd A20-K1>_
**Ngày submit:** 2026-06-24

---

## 1. Hardware spec (từ `00-setup/detect-hardware.py`)

- **OS:** Windows 11 (build 10.0.26200)
- **CPU:** AMD Ryzen 5 5500U with Radeon Graphics (Zen 2)
- **Cores:** 6 physical / 12 logical
- **CPU extensions:** AVX2, FMA, F16C (KHÔNG có AVX-512)
- **RAM:** 15.3 GB
- **Accelerator:** NVIDIA GeForce GTX 1650 4 GB (có) — nhưng chạy **CPU-only**
- **llama.cpp backend đã chọn:** CPU (AVX2). `detect-hardware.py` recommend CUDA vì thấy `nvidia-smi`, nhưng mình dùng prebuilt CPU wheel vì GTX 1650 chỉ 4 GB VRAM và máy chưa cài CUDA Toolkit + cmake.
- **Recommended model tier:** Qwen2.5-1.5B-Instruct (Q4_K_M)

**Setup story** (≤ 80 chữ): Ba thứ phải sửa cho Windows 11: (1) `wmic` đã bị gỡ trong build mới nên `detect-hardware.py` báo RAM 0 GB / CPU unknown → patch fallback sang PowerShell CIM + ctypes `GlobalMemoryStatusEx`; (2) không có `pwsh` → chạy thủ công từng bước thay vì script `.ps1`; (3) prebuilt wheel `0.3.30` crash `STATUS_ILLEGAL_INSTRUCTION` (build AVX-512, mà Zen 2 chỉ có AVX2) → pin `llama-cpp-python==0.3.19` từ CPU wheel index. Console cp1252 → set `PYTHONUTF8=1`.

---

## 2. Track 01 — Quickstart numbers (từ `benchmarks/01-quickstart-results.md`)

Settings: `n_threads=6`, `n_ctx=2048`, `n_batch=512`, `n_gpu_layers=0`.

| Model | Load (ms) | TTFT P50/P95 (ms) | TPOT P50/P95 (ms) | E2E P50/P95/P99 (ms) | Decode rate (tok/s) |
|---|--:|--:|--:|--:|--:|
| qwen2.5-1.5b-instruct-**Q4_K_M** | 1413 | 143 / 152 | 39.6 / 43.3 | 2640 / 2879 / 2945 | 25.3 |
| qwen2.5-1.5b-instruct-**Q2_K**   | 750  | 162 / 193 | 29.4 / 31.9 | 2020 / 2176 / 2188 | 34.0 |

**Một quan sát** (≤ 50 chữ): Q2_K decode nhanh hơn ~34% (34.0 vs 25.3 tok/s) và load nhẹ hơn ~2×, nhưng output ngắn/nông hơn rõ. Trên CPU bandwidth-bound, ít byte/weight = nhanh hơn. Mình vẫn chọn Q4_K_M làm primary vì chất lượng đáng đánh đổi cho RAM 15 GB.

---

## 3. Track 02 — llama-server load test

Server: `python -m llama_cpp.server` (0.3.19, CPU/AVX2) trên `127.0.0.1:8080`, model Q4_K_M, `n_threads=6`, `n_ctx=2048`.
Load gen: `locust --headless -r 1 -t 1m` (80% short / 20% long-RAG). Locust client đo **full response time** (non-streaming), nên cột "TTFB P50" ở đây là response-P50.

| Concurrency | Total RPS | Response P50 (ms) | E2E P95 (ms) | E2E P99 (ms) | Failures |
|--:|--:|--:|--:|--:|--:|
| 10 | 0.21 | 25000 | 46000 | 46000 | 0 (0.00%) |
| 50 | 0.33 | 20000 | 44000 | 44000 | 0 (0.00%) |

**Batching observation:** Python `llama_cpp.server` **không có** endpoint `/metrics` nên không đọc được `llamacpp:n_busy_slots_per_decode`. Bằng chứng gián tiếp về thiếu continuous batching: tăng 10 → 50 user gần như **không** cải thiện throughput (12 → 19 request hoàn thành trong 60s) và **không** giảm P95. Server decode **tuần tự** một slot trên CPU, nên thêm concurrency chỉ làm sâu hàng đợi — goodput bị chặn bởi tốc độ decode single-stream (~25 tok/s). Đây chính là động lực của continuous batching / PagedAttention (deck §2); muốn quan sát `n_busy_slots` cần native `llama-server` (`--parallel`, `--metrics`) build từ source.

---

## 4. Track 03 — Milestone integration

Pipeline `03-milestone-integration/pipeline.py` chạy end-to-end 3 query, gọi llama-server qua OpenAI-compat API, in ra provenance của context retrieved.

- **N16 (Cloud/IaC):** stub — chạy localhost trên 1 laptop, không có cluster/IaC.
- **N17 (Data pipeline):** stub — dữ liệu nạp in-memory, không có Airflow/batch job.
- **N18 (Lakehouse):** stub — không có Delta/Iceberg; corpus là list Python.
- **N19 (Vector + Feature Store):** stub — `retrieve()` dùng keyword-overlap trên `TOY_DOCS`, chưa nối vector index thật.

> Lý do stub: N16–N19 của mình nằm ở repo khác; lab này tập trung vào serving layer (N20), nên mình giữ retrieval ở mức skeleton để xác nhận đường gọi OpenAI-compat trước, sẽ thay STUB bằng vector index N19 sau.

**Nơi tốn nhiều ms nhất** trong pipeline (đo bằng `time.perf_counter`):

- embed: N/A (không có embedder ở stub)
- retrieve: ~0.0–0.1 ms (keyword overlap in-memory)
- llama-server: 3459 / 6741 / 10479 ms (3 query)

**Reflection** (≤ 60 chữ): Bottleneck gần như 100% ở LLM generation — retrieve chỉ ~0.1 ms còn LLM 3.5–10.5 s (>99.9% tổng thời gian). Khớp hoàn toàn kỳ vọng: trên CPU, decode token là phần đắt nhất; tối ưu retrieval ở đây vô nghĩa, đòn bẩy nằm ở serving (quant, batching, GPU offload).

---

## 5. Bonus — The single change that mattered most

**Change:** Chuyển quantization từ **Q4_K_M → Q2_K** cho cùng model Qwen2.5-1.5B trên cùng CPU (6 threads, n_gpu_layers=0).

> (Note: thay đổi *enabling* lớn hơn về mặt "chạy được hay không" là pin wheel `0.3.19` AVX2 thay cho `0.3.30` AVX-512 — nhưng đó là fix crash, không phải speedup, nên mình chọn quant để có before/after định lượng.)

**Before vs after** (từ `benchmarks/01-quickstart-results.md`):

```
before (Q4_K_M): decode 25.3 tok/s | TPOT P50 39.6 ms | E2E P50 2640 ms | load 1413 ms
after  (Q2_K):   decode 34.0 tok/s | TPOT P50 29.4 ms | E2E P50 2020 ms | load 750 ms
speedup: ~1.34× decode (và ~1.9× load time)
```

**Tại sao nó work:**

Trên CPU, vòng decode autoregressive là **memory-bandwidth-bound**, không phải compute-bound: mỗi token sinh ra phải đọc *toàn bộ* trọng số model từ RAM một lần (1.5B tham số). Tốc độ token/s ≈ bandwidth RAM ÷ số byte phải đọc mỗi token. Q4_K_M là ~5.0 bit/weight, Q2_K chỉ ~2.8 bit/weight, nên Q2_K cần đọc ít hơn ~44% số byte mỗi token → đọc xong nhanh hơn → nhiều token/s hơn. Vì cùng kiến trúc, cùng số phép nhân, khác biệt gần như chỉ do lượng byte stream qua memory bus. Đó là lý do speedup (~1.34×) xấp xỉ tỉ lệ giảm bytes-per-weight chứ không phải tỉ lệ FLOPs.

Điều đáng nói: speedup **không** lớn bằng tỉ lệ giảm file (1.04 GB → 0.68 GB) vì một phần trọng số (q6_K cho embedding/output) không nén thêm, và overhead dequant của Q2_K trên CPU bù lại một ít. Đánh đổi: Q2_K trả lời ngắn/nông hơn rõ rệt — nên với RAM 15 GB mình vẫn deploy Q4_K_M, chỉ dùng Q2_K khi RAM thực sự chật. Bài học khớp deck §1: quantization là cú đánh đổi RAM/latency-vs-quality, và trên hardware bandwidth-bound thì nó **trực tiếp** mua được tok/s.

---

## 6. (Optional) Điều ngạc nhiên nhất

50 user gần như không tệ hơn 10 user (19 vs 12 request/60s, P95 còn nhỉnh hơn chút) — minh hoạ trực quan rằng không có continuous batching thì thêm concurrency = thêm hàng đợi chứ không thêm goodput. Và cú crash `0xc000001d` của wheel AVX-512 trên CPU AVX2 là bài học nhớ đời về việc "prebuilt wheel" không phải lúc nào cũng khớp instruction set.

---

## 7. Self-graded checklist

- [x] `hardware.json` đã commit
- [x] `models/active.json` đã commit (hoặc paste path snapshot vào section 1)
- [x] `benchmarks/01-quickstart-results.md` đã commit
- [x] `benchmarks/02-server-results.md` (hoặc CSV từ `record-metrics.py`) đã commit
- [ ] `benchmarks/bonus-*.md` đã commit (ít nhất 1 sweep) — *chưa làm bonus track*
- [ ] Ít nhất 6 screenshots trong `submission/screenshots/` (xem `submission/screenshots/README.md`)
- [ ] `make verify` exit 0 (chạy ngay trước khi push)
- [ ] Repo trên GitHub ở chế độ **public**
- [ ] Đã paste public repo URL vào VinUni LMS

---

**Quan trọng:** repo phải **public** đến khi điểm được công bố. Nếu private, grader không xem được → 0 điểm.
