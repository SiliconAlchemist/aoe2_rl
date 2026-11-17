# Publishing this repository to GitHub

The local Git repository has been initialized on `main`. The repository uses MIT for project-authored material, with separate third-party notes. No remote has been configured and nothing has been pushed by the preparation work.

## Review the first commit

From the repository root in Windows Command Prompt:

```cmd
git status --short
git diff --cached --stat
git diff --cached
```

The prepared source includes code, docs, configuration examples and contribution templates. Generated data, reports, model weights, game recordings, environments and downloaded tools are ignored. The public README describes measured milestones and outstanding validation; it does not claim a trained full-game bot.

Set your own commit identity if needed, substituting your actual values:

```cmd
git config user.name "YOUR NAME"
git config user.email "YOUR GITHUB COMMIT EMAIL"
git add .
git commit -m "Initial AoE II RL research project"
```

## Create and push the remote

If GitHub CLI is not installed:

```cmd
winget install --id GitHub.cli --exact
```

Reopen Command Prompt after installation, navigate back to the repository, and authenticate:

```cmd
gh auth login --hostname github.com --git-protocol https --web
gh auth setup-git
```

Choose the repository name and visibility. The following creates a **public** repository; use `--private` if desired. Replace `YOUR-REPO-NAME`:

```cmd
gh repo create YOUR-REPO-NAME --public --source=. --remote=origin --push
gh repo view --web
```

This uploads the commit. If you create the repository on github.com instead, create it empty without an initial README/license/gitignore, then use its actual HTTPS URL:

```cmd
git remote add origin https://github.com/YOUR-ACCOUNT/YOUR-REPO-NAME.git
git push -u origin main
```

Use one creation method, not both. See [GitHub's existing-source guide](https://docs.github.com/en/migrations/importing-source-code/using-the-command-line-to-import-source-code/adding-locally-hosted-code-to-github).

## Repository presentation

Suggested description:

> Research tools for an Age of Empires II DE agent: game control, replay imitation data, and experimental reinforcement learning.

Suggested topics: `age-of-empires`, `reinforcement-learning`, `imitation-learning`, `rts`, `pytorch`, `replay-parser`.

Once a real remote exists, add its verified repository and issue URLs to `pyproject.toml` if package metadata links are wanted. The README currently uses relative internal links, so it works under any GitHub account/repository name. Add a demonstration video or screenshot when there is an artifact you want to publish; no synthetic image or unverified benchmark badge is included.

The repository includes issue and pull-request templates. There is no CI workflow yet; the existing test suite and live game behavior have different validation needs. No tests or training were run during publication preparation.
