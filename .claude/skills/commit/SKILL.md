---
name: commit
description: Analyze git changes and commit with a clear, well-structured message. Use whenever the user says "commit", "commit my changes", "generate commit message", or asks to save/record their work to git. Also triggers on "what did I change" when followed by a commit intent.
---

# Smart Commit

Analyze git changes and create a clear commit — no friction, no fluff.

## Workflow

### 1. Understand the changes

Run both commands to get the full picture:

```bash
git status
git diff
git diff --cached
```

Determine what to commit:
- **If there are staged changes** → commit only staged changes
- **If nothing is staged** → stage all tracked modified/deleted files (`git add -u`), then commit
- **Never stage untracked files automatically** — if untracked files exist, mention them briefly so the user can decide

If the diff is empty (nothing to commit), say so and stop.

### 2. Analyze and classify

Read the diff carefully. Determine:
- **What changed**: files, functions, config, dependencies
- **Why it changed**: bug fix, new feature, refactor, cleanup, docs, config tweak
- **Scope**: which module, component, or area of the codebase is affected

### 3. Generate the commit message

Format:

```
<type>(<scope>): <subject>

<body>
```

**Types** (lowercase):
- `feat` — new functionality
- `fix` — bug fix
- `refactor` — restructuring without behavior change
- `chore` — deps, config, tooling, build
- `docs` — documentation only
- `style` — formatting, whitespace, naming
- `perf` — performance improvement
- `test` — test additions or fixes

**Rules:**
- Subject line: imperative mood, ≤72 chars, no period
- Scope: short identifier for the affected area (e.g., `api`, `auth`, `db`, `ui`). Omit parentheses entirely if changes are too broad to scope
- Body: bullet points explaining *what* and *why*, only if the subject alone isn't sufficient. Skip for trivial changes (typos, version bumps, single-line fixes)
- If multiple unrelated changes exist, warn the user and suggest splitting — but commit anyway if they confirm

### 4. Commit

Show the generated message to the user, then commit:

```bash
git commit -m "$(cat <<'EOF'
<message here>
EOF
)"
```

Run `git status` after to confirm success.

### 5. Done

After committing, stop. Do not push, do not suggest pushing.

## Edge Cases

- **Merge conflicts in diff**: stop, report the conflict, do not commit
- **Only whitespace/formatting changes**: use `style` type, keep message minimal
- **Large changesets (>500 lines)**: still commit, but note in the message body that this is a large change and summarize the key areas
- **User provides a message hint** (e.g., "commit — fixed the login bug"): use their hint as the basis, but still analyze the diff to ensure accuracy and add detail if needed
- **Mixed staged/unstaged**: commit only what's staged, mention that unstaged changes remain
