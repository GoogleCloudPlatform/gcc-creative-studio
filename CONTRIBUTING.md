# How to Contribute

Thanks for helping! We welcome new templates, features, bug fixes and docs.

## 1. Before you start

- Have a **GitHub account** with **2-Factor Authentication (2FA)** on.
- Sign the Google [Contributor License Agreement](https://cla.developers.google.com/about) (CLA).
  You keep the copyright. The CLA only lets us use your work.
  If you signed it before (for any Google project), you are done.
  Check your status at <https://cla.developers.google.com/>.
- Read our [Code of Conduct](./CODE_OF_CONDUCT.md). We follow
  [Google's Open Source Community Guidelines](https://opensource.google/conduct/).

## 2. Set up

Follow the [Local Development Guide](./DEVELOPMENT.md). It runs everything with Docker Compose.

Then install the pre-commit hook (once):

```bash
cp pre-commit-hook.sh .git/hooks/pre-commit && chmod +x .git/hooks/pre-commit
```

## 3. Make your change

- **Branch:** We use [Git Flow](https://nvie.com/posts/a-successful-git-branching-model/).
  Create your branch from `develop`.
- **Python:** Follow the [Google Python Style Guide](https://google.github.io/styleguide/pyguide.html) (`black` + `pylint`).
- **TypeScript:** Follow the [Angular Style Guide](https://angular.dev/style-guide) and [gts](https://github.com/google/gts).
  Use Angular **Signals** for state. Put API calls in a **service**, not in components.
- **Commits:** Use the [Angular commit format](https://github.com/angular/angular/blob/main/contributing-docs/commit-message-guidelines.md),
  e.g. `fix(images): handle empty prompt`.
- **Docs:** Update the docs if your change affects them.

## 4. Check your work

Run linters in Docker (never on your machine):

```bash
docker compose run --rm pre-commit run --all-files
```

Run backend tests (coverage must be **80% or more**):

```bash
cd backend
uv run pytest tests -v --asyncio-mode=auto --cov=src --cov-fail-under=80
```

## 5. Open a pull request

Open your PR against `develop`. Every PR needs a review, even from team members.
See [GitHub Help](https://help.github.com/articles/about-pull-requests/) if you are new to PRs.

### Good PR practices

- **Keep it small.** Short PRs are easier and faster to review.
- **One thing per PR.** One fix or one feature. Do not mix them.
- **Write a short, clear description.** Use simple words. Say what changed, why,
  and how you tested it, in a few lines. Add screenshots for UI changes.
- **Write readable code.** Use clear names and small functions.
- **Comment the "why", not the "what".** Keep comments short and easy to understand.
- **No leftovers.** Remove debug logs, dead code and unrelated changes.

### Automated checks

GitHub Actions checks every PR to `develop`, `test` or `main`:

| Check | Rule |
| --- | --- |
| Pre-commit | Style and license headers pass |
| Backend tests | Coverage 80% or more (`pytest-cov`) |
| Backend lint | `pylint` score 9.0/10 or more |
| Frontend lint | `gts` passes |

### AI review (on demand)

Gemini can review your PR. To start it, add the **`ai-review`** label to the PR.
Only people with triage or write access can add labels. Ask a maintainer if you can't.

It reviews:

- **Code:** bugs, security, performance, readability, tests and error logging.
- **PR description:** if it is unclear, too long, or mixes many changes, it asks you to fix it.

Each comment has a severity: 🔴 critical, 🟠 high, 🟡 medium, 🟢 low.
Fix 🔴 and 🟠 before merge. It never approves or blocks a PR. A person still reviews it.

Fix any failing check, push again, and wait for a review. Thank you! 🎉