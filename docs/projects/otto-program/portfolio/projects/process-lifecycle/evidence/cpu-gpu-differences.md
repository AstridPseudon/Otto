# Where CPU and GPU should differ (claim for review, 15 Oct)

The cleanup-obligation model is shared. Each resource class carries its own **policy**: cost ceiling, idle retention, release evidence, conflict key, and admission measure. GPU differs in values, not in machinery.

| Dimension | CPU (local tasks) | GPU (engines, pods) | Consequence |
|---|---|---|---|
| Cost of a leak | memory/CPU, ~free | money per second (pods) or a scarce device | GPU: maximum billable lifetime and short idle retention; a leak is an alarm |
| Warm-up | cheap start | minutes of model load, VRAM filled | GPU engines are service scopes reused through leases; CPU is a task scope per attempt |
| Ending one task | kill its process group | the engine is shared; don't kill it | cancel through the engine's control protocol; stop the engine only by idle or billing policy |
| Release evidence | process gone = settled | process gone does not prove VRAM or the CUDA context is freed; "terminate requested" is not terminated | GPU settlement needs device or provider evidence |
| What unresolved blocks | its scratch/outputs | that device or pod | conflict keys per device or pod, never the host |
| Admission | shareable | exclusive, quantitative VRAM | VRAM accounting as a reservation quantity (Runtime has min `vram_bytes` facts, not allocation); no GPU scheduler |
| Health | rarely matters | driver hang or OOM can wedge the device | cheap device health check before admitting GPU work |
| Location here | local Mac | mostly remote (RunPod); the Mac has no CUDA, Metal runs in ordinary processes | remote: provider authority and intent before acquire. Mac: the scarce resource is 8 GB unified memory |
