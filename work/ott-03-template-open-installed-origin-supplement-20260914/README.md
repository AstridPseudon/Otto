# OTT-03 same-process installed-origin supplement

This versioned supplement repairs provenance granularity in the v3 packet without changing product source or the v3 sealed artifacts. Each affected installed command imports `otto`, `herzchen`, and `PortfolioOwnerBootstrap` in the same Python process that runs the tests or the selected-template create-and-open observation. The process ran from a temporary directory outside the Otto checkout with `PYTHONPATH` and `PYTHONHOME` unset.

- Product source: commit `14510f49514587ecda265fb3e38c632f9ebe3179`, tree `2d213ad75bb3a730bfed8c31eff9c4d2597ec4df`.
- Candidate Otto wheel: `../ott-03-template-open-receipt-20260914-v3/dist/otto_local_candidate-0.0.0-py3-none-any.whl`, SHA-256 `578c72f042a915510dc4dd1a10d78f82350231ac5029d2bf10f7a55b2febdf19`.
- Accepted Herzchen wheel: SHA-256 `2681daaeb673cd636050c3805977a01a670ed6bcfc113fe9d85903af5eeae9bc`.
- Installed full Otto suite: 47 passed, return code 0, same process origin is venv `site-packages` for both Otto and Herzchen.
- Installed focused selected-template suite: 18 passed, return code 0, same process origin is venv `site-packages` for both Otto and Herzchen.
- Installed selected create-and-open observation: return code 0, same process origin is venv `site-packages`; raw output contains the durable six-event create/open, typed `work.task` record, exact replay, resource/parameter conflict, invalid-resource no-write, reopen and replay observations.

The v3 failed observation attempt remains historical and is not replaced. The v3 full/focused installed runs remain historical receipts; this supplement is the current same-process provenance evidence for those claims.
