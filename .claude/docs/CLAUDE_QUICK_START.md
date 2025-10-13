# Claude Context System - Quick Start

## 🚀 5-Second Start

```bash
make claude-context
```

Then in Claude chat:
```
"Read .claude_context.md and .claude_context_auto.md"
```

Done! Claude now understands your project.

---

## 📋 Common Commands

| Task | Command |
|------|---------|
| Generate context | `make claude-context` |
| List all flows | `make list-flows` |
| Read a specific flow | `make claude-flow FLOW=authorization_flow` |
| Run tests | `make test` |
| Run unit tests | `make test-unit` |
| See all commands | `make help` |

---

## 💬 Common Claude Prompts

### Starting Work
```
"Read .claude_context.md and .claude_context_auto.md for project context"
```

### Understanding a Flow
```
"Read files in the authorization_flow group and explain how it works"
```

Or:
```
"Run: make claude-flow FLOW=authorization_flow"
```

### Writing Tests
```
"Read .claude_context.md"
"Read ocpi22/cpo/mqtt/tasks.py"
"Generate unit tests for process_authorization_request following my test preferences"
```

### Debugging
```
"Read .claude_context_auto.md - what changed recently?"
"The authorization flow is failing after the latest changes. What might be wrong?"
```

### Adding Features
```
"Read .claude_context.md"
"I need to add a new MQTT message type for remote diagnostics. Guide me through it."
```

---

## 📁 What Gets Generated

### `.claude_context.md` (Static - you edit this)
- Project architecture
- Key flows
- Technology stack
- Testing guidelines
- Common patterns

### `.claude_context_auto.md` (Auto - regenerate often)
- Last 10 commits
- Recent changes
- Current branch
- Test inventory
- Celery tasks
- Models summary
- API endpoints

### `.claude/file_groups.json` (Flow definitions)
- Logical groupings of files
- 32 predefined flows covering your entire codebase

---

## 🔄 Typical Workflow

### Morning Routine
```bash
git pull
make claude-context
```

### Working on a Feature
```bash
# 1. Understand the area
make claude-flow FLOW=authorization_flow

# 2. In Claude
"Read the authorization_flow files"
"I want to add X feature. What should I modify?"

# 3. Make changes
# ... edit files ...

# 4. Generate tests
"Generate unit tests for my changes"

# 5. Run tests
make test
```

### After Major Changes
```bash
git commit -m "..."
make claude-context  # Refresh for next session
```

---

## 🎯 Available Flows (32 Total)

### Business Logic Flows (4)
- **authorization_flow** - Token auth from MQTT to OCPI
- **session_management_flow** - Session lifecycle
- **meter_values_flow** - Energy metering
- **remote_commands_flow** - Commands to charge points

### Infrastructure Flows (4)
- **mqtt_infrastructure** - MQTT messaging layer
- **ocpi_protocol** - Core OCPI implementation
- **celery_tasks** - Async tasks
- **webhooks_system** - Webhook handling

### API Flows (2)
- **cpo_api** - CPO API endpoints
- **msp_functionality** - MSP functionality

### Data Management Flows (5)
- **location_management** - Locations and EVSEs
- **tariff_system** - Pricing system
- **credentials_management** - Partner credentials
- **sessions_module** - Session utilities
- **data_models** - Supporting data models

### Integration Flows (2)
- **hubject_integration** - Hubject/OICP
- **pull_sync_operations** - Pulling data from partners

### Cross-Cutting Flows (4)
- **serialization_layer** - DRF serializers
- **middleware_layer** - Request/response middleware
- **admin_interface** - Django admin
- **test_infrastructure** - Test setup

### Deployment & DevOps Flows (7)
- **docker_infrastructure** - Docker & containerization
- **cicd_pipelines** - GitHub Actions workflows
- **deployment_scripts** - Deployment & DB init scripts
- **service_startup** - Service entrypoints
- **project_configuration** - Requirements & config files
- **django_settings** - Settings for all environments
- **performance_testing** - Locust performance tests

### Supporting Modules (2)
- **utility_modules** - Root-level utilities
- **development_tools** - Development tools

### Financial Operations (2)
- **payment_system** - Payment processing with Stripe
- **settlement_reporting** - CDR reporting and billing

Use `make list-flows` to see detailed descriptions of each flow.

---

## ⚡ Pro Tips

### Tip 1: Use Flows Instead of Reading Everything
❌ Bad:
```
"Read all files in ocpi22/cpo/"
```

✅ Good:
```
"Show me the authorization_flow"
```

### Tip 2: Regenerate After Pulls
```bash
git pull && make claude-context
```

### Tip 3: Reference Context in Prompts
```
"Based on my testing preferences in .claude_context.md, generate tests for..."
```

### Tip 4: Ask for Specific Context
```
"What files are in the session_management_flow?"
"Show me recent changes related to MQTT"
```

### Tip 5: Combine Context with Specific Files
```
"Read .claude_context.md"
"Now read ocpi22/cpo/mqtt/tasks.py"
"Add error handling for database timeouts"
```

---

## 🐛 Troubleshooting

| Problem | Solution |
|---------|----------|
| Script not found | `chmod +x .claude/scripts/*.sh` |
| Flow not found | `make list-flows` to see available |
| Context too old | `make claude-context` to regenerate |
| Tree command missing | `brew install tree` (macOS) or `apt install tree` (Linux) |

---

## 📚 Full Documentation

See [.claude/docs/CLAUDE_CONTEXT_README.md](.claude/docs/CLAUDE_CONTEXT_README.md) for complete documentation.

---

**Remember**: Run `make claude-context` before each work session for best results!
