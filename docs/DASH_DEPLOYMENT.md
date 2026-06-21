# Dash — deployment & sandbox safety (PARKED, decide later)

> Status: **open decision, parked.** Not needed for the internal demo. Revisit
> before Dash is released to real planners. Captured 2026-06-21.

## The situation

Dash builds documents by writing and running code in a sandbox
(`agents/dash/sandbox.py`): it reads a vendored Anthropic skill, writes a build
script (pptxgenjs / docx-js / reportlab), and runs it via `run_bash`. This is
powerful and produces good documents — but it means **model-generated code runs
on the host**. Fine for local/demo use; needs isolation before real users.

## The real risk (not "the model goes rogue")

Prompt injection + blast radius:
- Dash's code currently runs **in the same process as the FastAPI backend**,
  which holds `ANTHROPIC_API_KEY`, the free-tier keys, `.env`, and network reach
  toward Bolders Postgres.
- A poisoned upload (Excel/PDF) or hidden instructions in Lily's handoff text
  could induce Dash to run code that **reads those secrets/data and exfiltrates
  them**. That's the genuine threat for an internal tool.
- Multi-user on one box: `run_bash` can read anything the OS user can read —
  other sessions' workspaces, the `.env`, etc.

## Two paths considered

**Path A — Isolate execution, keep full code ability.**
Run each build in a throwaway sandbox with **no secrets + no network egress**
(the two controls that actually kill the exfiltration threat), ephemeral per
build, non-root, resource-limited. Keeps "Dash writes real code" → best document
quality. Safe **if configured correctly**; safety must be *maintained* (config
can drift).

**Path B — Remove arbitrary code entirely.**
Model emits a constrained spec (structured JSON: slides, sections, charts); a
**trusted renderer we write** turns it into the document. No `run_bash`, no RCE
class at all. Less layout freedom, but **safe by construction** — nothing to
isolate, OS-independent.

## Windows wrinkle (deployment is Windows; no Linux in use)

The hard part of Path A is isolation, and Windows makes it harder:
- **Docker on Windows = Docker Desktop + WSL2** (runs the container as Linux in a
  VM). Works, but adds a Docker Desktop dependency, WSL2/virtualization, and
  **paid licensing** for larger companies (>~250 employees / >~$10M revenue).
  Running Docker Desktop on a *Windows Server* is awkward.
- **Native Windows isolation**: a dedicated low-privilege user with no access to
  secrets (file ACLs) + **outbound network blocked via Windows Firewall scoped to
  that account**. Achievable but bespoke and easier to get subtly wrong.
- **Cloud/managed sandbox** (e2b, Modal): fully isolated, but the build happens
  off-premises → conflicts with the "company context stays in-house" stance
  (we self-host embeddings for that reason). Likely a no.

## Current leaning (not final)

Because Windows makes isolation the hardest part — exactly what Path B avoids —
**lean Path B for the released version**, keeping the code-sandbox Dash as an
internal-only power tool. If full code execution is wanted in production, the
cleanest Windows route is **Docker Desktop + WSL2**, provided the host allows it
and licensing is OK.

## Open questions to resolve before release
1. What host does the released app run on? (company Windows Server / a box Brett
   controls / Azure / undecided)
2. Is Docker Desktop allowed + licensed on that host?
3. Document-quality check: are the from-scratch code-path documents clearly
   better than what a Path B spec-renderer would produce? (Decides if Path A's
   isolation work is worth it.)

## If we go Path A later — hardening checklist
- [ ] No secrets in the sandbox (keys/.env/DB creds never mounted or passed)
- [ ] **No network egress** (`--network none` / firewall block) ← most important
- [ ] Ephemeral, fresh per build, destroyed after
- [ ] Non-root, read-only root FS, writable tmpfs workspace only
- [ ] CPU / memory / PID / wall-clock limits
- [ ] `no-new-privileges`, drop caps, **never mount the Docker socket**
- [ ] Read-only skills mount
- [ ] (paranoid) gVisor / Firecracker for kernel-level isolation
