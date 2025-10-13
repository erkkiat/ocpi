# 🤖 Claude AI Context System

This project includes an intelligent context management system for working efficiently with Claude AI.

## Quick Start

```bash
# Generate fresh context
make claude-context
```

Then in Claude chat:
```
"Read .claude/context.md and .claude/context_auto.md"
```

That's it! Claude now understands your entire project architecture, recent changes, and can generate tests following your strict guidelines.

## What This Gives You

✅ **Instant Project Understanding** - Claude knows your architecture in 10 seconds  
✅ **Always Current** - Auto-generates context from latest git state  
✅ **Smart File Organization** - 30 predefined flows for logical code groups  
✅ **Minimal Token Usage** - Read only what you need  
✅ **Test Generation** - Follows your strict testing preferences automatically  

## Project Structure

```
.claude/
├── README.md                      # This file
├── context.md                     # Static architecture (edit manually)
├── context_auto.md                # Auto-generated (gitignored)
├── file_groups.json               # Flow definitions
├── docs/                          # Documentation
│   ├── CLAUDE_CONTEXT_README.md   # Complete guide
│   ├── CLAUDE_QUICK_START.md      # Quick reference
│   ├── FILE_GROUPS_VALIDATION.md  # Flow validation
│   └── GIT_HOOKS_INFO.md          # Git hooks info
└── scripts/                       # Automation scripts
    ├── generate_claude_context.sh # Context generator
    ├── read_flow.sh               # Flow reader
    └── install_git_hooks.sh       # Hook installer
```

## Common Commands

```bash
make claude-context              # Generate fresh context
make list-flows                  # See available code flows
make claude-flow FLOW=<name>     # Read files for a specific flow
make test                        # Run all tests
make help                        # See all commands
```

## Available Flows (30 Total)

Your project has 30 comprehensive flows covering:

**Business Logic**
- authorization_flow, session_management_flow, meter_values_flow, remote_commands_flow

**Infrastructure**  
- mqtt_infrastructure, ocpi_protocol, celery_tasks, webhooks_system

**APIs**
- cpo_api, msp_functionality

**Data Management**
- location_management, tariff_system, credentials_management, sessions_module, data_models

**Integrations**
- hubject_integration, pull_sync_operations

**Cross-Cutting**
- serialization_layer, middleware_layer, admin_interface, test_infrastructure, utility_modules

**Deployment & DevOps**
- docker_infrastructure, cicd_pipelines, deployment_scripts, service_startup,  
  project_configuration, django_settings, performance_testing

**Development**
- development_tools

Run `make list-flows` to see full descriptions.

## Example Workflow

```bash
# 1. Start your day
git pull
make claude-context

# 2. In Claude
"Read .claude/context.md and .claude/context_auto.md"
"I need to modify the authorization flow. Show me the relevant files."

# 3. Claude understands and helps
# - Knows your architecture
# - Suggests correct files
# - Follows your test preferences
# - Generates proper code

# 4. After changes
git commit -m "..."
# Context auto-updates via git hooks!
```

## Documentation

- **This README**: `.claude/README.md` - Overview
- **Quick Start**: `.claude/docs/CLAUDE_QUICK_START.md` - 5-second start
- **Complete Guide**: `.claude/docs/CLAUDE_CONTEXT_README.md` - Full docs
- **Flow Definitions**: `.claude/file_groups.json` - All 30 flows

## Git Hooks (Automatic Updates)

Context automatically regenerates:
- **After each commit** (silent)
- **After git pull/merge** (with notification)

### Team Setup

```bash
# One-time setup after cloning
./.claude/scripts/install_git_hooks.sh
```

## Why This System?

### Without Context System
- ❌ Manually copy-paste 10+ files per conversation
- ❌ Re-explain architecture every time
- ❌ Claude forgets project patterns
- ❌ 15-30 minutes setup per session

### With Context System
- ✅ One command: `make claude-context`
- ✅ Claude knows everything instantly
- ✅ Remembers your testing preferences
- ✅ 10 seconds setup per session
- ✅ Auto-updates via git hooks

## Your Testing Preferences

Claude automatically follows your strict testing guidelines defined in `.claude/context.md`:

- **Unit tests**: Mock boundaries, test logic
- **Integration tests**: Real DB/Redis/MQTT, minimal mocks
- **E2E tests**: Full system, minimal mocks
- **Never mock**: Business logic, ORM, schemas
- **Always mock**: External APIs, time, random, email

---

**Built**: October 2025  
**Location**: `.claude/` directory  
**Status**: Production-ready  
**Team**: Shared via git  
**Maintenance**: Auto-generated files gitignored, docs committed
