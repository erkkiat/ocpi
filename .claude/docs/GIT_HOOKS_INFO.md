# Git Hooks for Claude Context Auto-Update

## Overview

Git hooks have been installed to automatically keep Claude context up-to-date as you work.

## What's Installed

### 1. Post-Commit Hook (`.git/hooks/post-commit`)
**Trigger**: After every `git commit`  
**Action**: Silently regenerates `.claude_context_auto.md`  
**Result**: Claude always has access to your latest committed changes

### 2. Post-Merge Hook (`.git/hooks/post-merge`)
**Trigger**: After `git pull` or `git merge`  
**Action**: Regenerates context with a notification  
**Result**: Context includes newly pulled changes immediately

## How It Works

```bash
# You work normally
vim ocpi22/cpo/mqtt/tasks.py

# Commit your changes
git commit -m "Add new MQTT task"
# → Context auto-regenerates (silently)

# Pull changes from team
git pull origin develop
# → Context auto-regenerates
# → Shows: "🤖 Updating Claude context..."
```

## For Team Members

If you're setting up the repo for the first time:

```bash
git clone <repo>
cd ocpiconnector
./scripts/install_git_hooks.sh
```

This installs the hooks automatically.

## Manual Installation

If hooks aren't working, reinstall them:

```bash
./scripts/install_git_hooks.sh
```

Or set permissions manually:

```bash
chmod +x .git/hooks/post-commit
chmod +x .git/hooks/post-merge
```

## Benefits

### Before Git Hooks
```bash
# Make changes
git commit -m "..."
make claude-context         # Manual step
```

### After Git Hooks
```bash
# Make changes
git commit -m "..."
# Context updates automatically!
```

**Time saved**: No need to remember `make claude-context`  
**Always current**: Context updates with every commit  
**Team friendly**: Works for everyone who has hooks installed

## Disabling Hooks (if needed)

To temporarily disable:

```bash
# Rename to disable
mv .git/hooks/post-commit .git/hooks/post-commit.disabled
mv .git/hooks/post-merge .git/hooks/post-merge.disabled
```

To re-enable:

```bash
mv .git/hooks/post-commit.disabled .git/hooks/post-commit
mv .git/hooks/post-merge.disabled .git/hooks/post-merge
```

## Troubleshooting

### Hook not running?

Check permissions:
```bash
ls -la .git/hooks/post-*
# Should show: -rwxr-xr-x (executable)
```

Fix permissions:
```bash
chmod +x .git/hooks/post-commit
chmod +x .git/hooks/post-merge
```

### Context not updating?

Test manually:
```bash
./scripts/generate_claude_context.sh
```

If this fails, the hook will fail too. Check:
- Script is executable: `chmod +x scripts/generate_claude_context.sh`
- You're in project root when committing
- Required tools are installed (`git`, `jq`, etc.)

### Hooks slowing down commits?

The post-commit hook runs silently in the background and shouldn't add noticeable delay. If it does:

1. Check if script has errors:
   ```bash
   ./scripts/generate_claude_context.sh
   ```

2. Temporarily disable for large commits:
   ```bash
   mv .git/hooks/post-commit .git/hooks/post-commit.disabled
   # ... do your work ...
   mv .git/hooks/post-commit.disabled .git/hooks/post-commit
   make claude-context  # Manual refresh
   ```

## What Gets Updated

After each commit, the auto-generated context includes:

- ✅ Your latest commit message
- ✅ Updated file list
- ✅ New git status
- ✅ Recent commit history (last 10)
- ✅ Changes from last 24 hours
- ✅ Updated test inventory
- ✅ New tasks/models/endpoints if added

## Notes

- Git hooks are **local** (not tracked in git)
- Each team member needs to install hooks once
- The `install_git_hooks.sh` script makes this easy
- Hooks work with all git commands (commit, pull, merge, rebase)

---

**Installed**: Yes ✅  
**Status**: Active and working  
**Manual command**: Still available via `make claude-context` if needed
