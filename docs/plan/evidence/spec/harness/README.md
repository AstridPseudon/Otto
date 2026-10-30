# Harness research (30 Oct)

Three Claude research sub-agents ran on 30 Oct. Their reports were relayed in the session; the key facts are folded into `../../../13-spec.md` (v3, §B2–B3).

- **oh-my-pi** (can1357/oh-my-pi, 18.14.0, MIT):
  - **Login:** subscription OAuth for Anthropic Pro/Max (PKCE, paste-redirect), OpenAI Codex (device code) and others. Credentials live in the SQLite store `~/.omp/agent/agent.db`, with refresh leases across processes, multiple accounts, and an auth broker and gateway.
  - **Control:** an RPC mode with `prompt_result` and `session_settled`, `open_session`, and a Python RPC client.
  - **Sub-agents:** markdown agent definitions in `task`, with a model or account per agent and recursion depth 2.
  - **Other:** a built-in advisor and watchdog; skills in the Agent Skills format; config in `~/.omp/agent/config.yml` with `modelRoles`.
  - **Risks:** releases are roughly daily, it needs Bun 1.4.4 or newer, and Anthropic may restrict third-party subscription use.
- **Upstream Pi** (earendil-works/pi, formerly badlogic/pi-mono, 1.4.0, MIT):
  - **Control:** an RPC mode; `agent_settled` means done, and a prompt response only means it was accepted. Sessions are JSONL trees, with no lock across processes.
  - **Instructions:** `--append-system-prompt` and skills.
  - **Login:** subscription OAuth for Anthropic and ChatGPT.
  - **Gaps:** no built-in sub-agents.
- **Astrid's existing omp integration:**
  - **Install:** `@oh-my-pi/pi-coding-agent@18.12.6` from a recipe with checksum-pinned binaries and Bun 1.3.14.
  - **Launch:** with `--system-prompt` / `--append-system-prompt`; the app runs `omp acp` over stdio JSON-RPC.
  - **Login:** done by the user through omp's `/login`. Astrid checks status via RPC `get_login_providers`, never by reading tokens.
  - **Open:** the R7-F1 env-leak fix isn't on Astrid main.
