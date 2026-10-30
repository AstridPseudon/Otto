# Decisions

**The owner** is the person who commissioned this plan. They approve scope, defaults and releases. Everything below was decided by the owner, unless it's marked *recommended default*. A recommended default stands until the owner changes it.

## 1. Decided
| # | Decision | Where it's specified |
|---|---|---|
| D1 | **Build a new, small tool beside old Otto,** not on it. Old Otto is frozen and mined for parts. | `16-three-reviews.md` §1 |
| D2 | **One machine** (a Mac or a Linux cloud box) runs everything. **One local SQLite file** holds the tool's state; Turso sync is for later. | spec B1, B4 |
| D3 | **oh-my-pi is the harness.** We use its subscription logins and its model choice, and pin the **latest release at S0**. | spec B2, B3 |
| D4 | **Any model, chosen in oh-my-pi's model picker,** with arbitrary seeded defaults; the **advisor's seed is Opus 5.5**. A change applies to new agents. | spec A2 |
| D5 | **Five fixed ranks in the tool; roles are defined by the pack,** including specialists such as a sense-checker or an over-engineering checker, each with fixed instructions. | spec A2 |
| D6 | **Managers dispatch;** there's no automatic dispatch. There's an idle-manager nudge, then an escalation. | spec A4 |
| D7 | **No spend controls,** and no excessive controls. | spec A5 |
| D8 | **Default intervals:** the orchestrator checks in every **60 minutes**; the advisor is consulted every **180 minutes**. | spec A1 |
| D9 | **Projects are spec folders** with all-or-nothing check-out and check-in to SQLite. | spec A4 |
| D10 | **The pilot is the attach project** (`projects/attach/`), built by the tool on its own repo. | plan §6, §10 |
| D11 | **v1 runs as four parallel projects** (state, runtime, pack, delivery), each with its own manager, integrating into `main` of `AstridPseudon/Otto` (restarted fresh). | plan §3, §11 |
| D12 | **Testing:** real storage, Git and processes, with faked models, in a 3–5 minute credential-free CI run. There's one end-to-end journey test, and live models only at S0, VS and the pilot. | spec B7 |
| D13 | *Recommended default:* **one orchestrator and one advisor per database.** A separate organisation uses another file. | spec decisions |
| D14 | *Recommended default:* **"a repeated message does no harm"** covers the tool's own state, not arbitrary shell or external effects. | spec A4 |
| D15 | **Preserve, never delete:** every old Otto ref, and every plan-repo branch. | `16-three-reviews.md` §1 |

## 2. Day-1 answers (owner, 30 Oct)
| # | Question | Answer |
|---|---|---|
| O1 | **What is the product called?** | **`otto`.** The predecessor is **"old Otto"**. The package installs in its own pipx environment, with state under `~/.otto/`. S0 checks for clashes with any old Otto install on the Mac. |
| O2 | **Where does the code live?** | **The existing repo, `AstridPseudon/Otto`.** **`main` was restarted fresh** for the new tool (a new history). **Old Otto moved to the `deprecated` branch** (at `a70b3f2`), and every `transfer/20261028/*` branch stays. *No new repo.* |
| O3 | **Which machines?** | *Recommended default, not yet confirmed:* the owner's **Mac**, plus one **Linux cloud box** (any small VM with 4+ cores and 8 GB of RAM). |
| O4 | **Who fills each seat during the bootstrap?** | **The owner hands the repo to one orchestrator session,** which farms the four projects out to four manager sessions and keeps an eye on them. Workers are short sessions. The owner watches and approves. See `POLICY.md`. |
| O5 | **Which models?** | **Claude and ChatGPT, for most of the implementation,** on the owner's existing subscriptions. There's no API-key spend by default. |
| O6 | **Who approves release?** | **The owner.** During the pilot the candidate runs in a separate test organisation. At release, the new version is installed side by side, `otto run` restarts on it at a settled point, and the old version stays available to roll back to. |
| O7 | **How do we judge the pilot's real goal?** | *Recommended default, not yet confirmed:* log owner interventions, stalls over 2 hours, and idle-check false alarms during the pilot. The owner judges. |

## 3. How decisions are made and recorded
- **A disagreement** between current documents, or a question a manager can't answer, goes to the orchestrator. Anything that changes scope, defaults, cost or release goes to the owner.
- **Every answer is added here,** dated, with the documents it changes. The documents are then updated to match.
