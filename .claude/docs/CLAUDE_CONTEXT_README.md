# Claude Context System

This directory contains the context management system for working efficiently with Claude AI on the OCPI Connector project.

## Overview

The context system solves the problem of Claude needing to understand your codebase without reading hundreds of files every time. It provides:

1. **Static Architecture Documentation** (`.claude_context.md`) - Manual, comprehensive overview
2. **Auto-Generated Context** (`.claude_context_auto.md`) - Fresh data about recent changes
3. **Flow-Based File Groups** (`docs/file_groups.json`) - Logical groupings of related files
4. **Helper Scripts** - Easy commands to generate and read context

## Quick Start

### Before Working with Claude

```bash
# Generate fresh context
make claude-context

# Or directly
./scripts/generate_claude_context.sh
```

### In Claude Chat

```
"Read .claude_context.md and .claude_context_auto.md for project context"
```

That's it! Claude now has:
- ✅ Project architecture understanding
- ✅ Recent git changes
- ✅ Current branch and commits
- ✅ Test structure
- ✅ Key file locations

## Available Commands

### Generate Context
```bash
make claude-context
```
Generates `.claude_context_auto.md` with:
- Recent commits (last 10)
- Files changed in last 24 hours
- Current git status
- Project structure
- Test inventory
- Celery tasks
- Django models
- API endpoints

### List Available Flows
```bash
make list-flows
```
Shows all logical flow groups you can explore.

### Read Specific Flow
```bash
make claude-flow FLOW=authorization_flow
```
Displays all files in a flow group (e.g., authorization, session management).

In Claude, you can then say:
```
"Run: make claude-flow FLOW=authorization_flow and show me the output"
```

### Run Tests
```bash
make test              # All tests
make test-unit         # Unit tests only
make test-integration  # Integration tests only
make test-cov          # With coverage report
```

## File Structure

```
.
├── .claude_context.md              # Static architecture doc (manual)
├── .claude_context_auto.md         # Auto-generated (git ignored)
├── docs/
│   ├── file_groups.json            # Flow definitions
│   └── CLAUDE_CONTEXT_README.md    # This file
└── scripts/
    ├── generate_claude_context.sh  # Context generator
    └── read_flow.sh                # Flow reader
```

## Available Flows (32 Total)

The following logical flows are defined in `.claude/file_groups.json`:

### Business Logic Flows (4)
1. **authorization_flow** - Token authorization from MQTT to OCPI
2. **session_management_flow** - Session lifecycle and CDR generation
3. **meter_values_flow** - Energy metering and cost calculation
4. **remote_commands_flow** - Commands from OCPI to charge points

### Infrastructure Flows (4)
5. **mqtt_infrastructure** - MQTT client and messaging layer
6. **ocpi_protocol** - Core OCPI protocol implementation
7. **celery_tasks** - All async task definitions
8. **webhooks_system** - Webhook handling for OCPI events

### API Flows (2)
9. **cpo_api** - Charge Point Operator API endpoints
10. **msp_functionality** - Mobility Service Provider functionality

### Data Management Flows (5)
11. **location_management** - Location and EVSE management
12. **tariff_system** - Pricing and tariff system
13. **credentials_management** - Partner credentials
14. **sessions_module** - Session utilities and services
15. **data_models** - Supporting data models (business details, hours, images)

### Integration Flows (2)
16. **hubject_integration** - Hubject/OICP integration
17. **pull_sync_operations** - Pulling data from OCPI partners

### Cross-Cutting Flows (4)
18. **serialization_layer** - Django REST serializers and data validation
19. **middleware_layer** - Request/response middleware
20. **admin_interface** - Django admin configuration and views
21. **test_infrastructure** - Test configs and fixtures

### Deployment & DevOps Flows (7)
22. **docker_infrastructure** - Docker and containerization
23. **cicd_pipelines** - GitHub Actions CI/CD workflows
24. **deployment_scripts** - Deployment and initialization scripts
25. **service_startup** - Service entrypoints (entrypoint.sh, manage.py)
26. **project_configuration** - Requirements and config files
27. **django_settings** - Django settings for different environments
28. **performance_testing** - Locust performance testing setup

### Supporting Modules (2)
29. **utility_modules** - Root-level utility modules and helpers
30. **development_tools** - Development and debugging tools

### Financial Operations (2)
31. **payment_system** - Payment processing with Stripe integration
32. **settlement_reporting** - CDR reporting and billing settlement

Use `make list-flows` to see detailed descriptions of each flow.

## Usage Patterns

### Pattern 1: Starting a New Feature
```bash
# 1. Generate fresh context
make claude-context

# 2. In Claude
"Read .claude_context.md and .claude_context_auto.md"
"I need to add a new MQTT message type for X. What files should I modify?"
```

### Pattern 2: Understanding Existing Flow
```bash
# 1. List flows to find relevant one
make list-flows

# 2. In Claude
"Run: make claude-flow FLOW=authorization_flow and show the output"
"Explain how the authorization flow works"
```

### Pattern 3: Writing Tests
```bash
# 1. Generate context
make claude-context

# 2. In Claude
"Read .claude_context.md and .claude_context_auto.md"
"Read ocpi22/cpo/mqtt/tasks.py"
"Generate unit tests for process_authorization_request following my test preferences"
```

### Pattern 4: Debugging
```bash
# 1. Check what changed recently
make claude-context

# 2. In Claude
"Read .claude_context_auto.md"
"The authorization flow is failing. Based on recent changes, what might be wrong?"
```

### Pattern 5: Daily Work Session
```bash
# Morning routine
git pull
make claude-context

# Then use Claude throughout the day
# Regenerate context after major changes:
git commit -m "..."
make claude-context
```

## Customizing the System

### Adding a New Flow

Edit `docs/file_groups.json`:

```json
{
  "my_new_flow": {
    "description": "Description of what this flow does",
    "files": [
      "path/to/file1.py",
      "path/to/file2.py"
    ]
  }
}
```

### Updating Static Context

Edit `.claude_context.md` manually to:
- Add new architectural patterns
- Document new modules
- Update key flows
- Add testing notes

### Modifying Auto-Context

Edit `scripts/generate_claude_context.sh` to add:
- More git information
- Additional project metrics
- Custom analysis
- Environment checks

## Best Practices

### DO ✅

- Run `make claude-context` before starting work
- Regenerate context after pulling changes
- Reference specific flows when asking about features
- Update `.claude_context.md` when architecture changes
- Add new flows to `file_groups.json` for complex features

### DON'T ❌

- Commit `.claude_context_auto.md` (it's in .gitignore)
- Read entire modules unnecessarily - use flows instead
- Forget to regenerate after major changes
- Ask Claude to read hundreds of files at once

## Git Integration

The `.gitignore` already includes:
```
.claude_context_auto.md
```

The static files ARE committed:
- `.claude_context.md`
- `docs/file_groups.json`
- `scripts/*.sh`

## Troubleshooting

### "tree command not available"
The auto-generation script gracefully handles missing `tree`. On macOS:
```bash
brew install tree
```

On Ubuntu/Debian:
```bash
sudo apt-get install tree
```

### Scripts not executable
```bash
chmod +x scripts/*.sh
```

### Flow not found
```bash
make list-flows  # See available flows
```

### Context too large
Use flows instead of reading entire context:
```
"Run: make claude-flow FLOW=authorization_flow"
```

## Advanced Usage

### Custom Context Queries

You can create custom scripts in `scripts/` for specific queries:

```bash
# scripts/list_untested_files.sh
find ocpi22 -name "*.py" | while read f; do
    test_file=$(echo $f | sed 's/\.py$//' | sed 's|ocpi22/|ocpi22/tests/test_|')_test.py
    if [ ! -f "$test_file" ]; then
        echo "$f (no test found)"
    fi
done
```

### Integration with Git Hooks

Add to `.git/hooks/post-merge`:
```bash
#!/bin/bash
./scripts/generate_claude_context.sh
echo "✓ Claude context updated after merge"
```

### CI/CD Context Validation

In your CI pipeline:
```yaml
- name: Validate Context
  run: |
    ./scripts/generate_claude_context.sh
    # Add validation logic
```

## Questions?

- **Where's the static context?** → `.claude_context.md` (root)
- **How do I update it?** → Edit `.claude_context.md` manually
- **Auto-context not generating?** → Check script permissions and dependencies
- **Flow not working?** → Verify paths in `docs/file_groups.json`
- **Context too old?** → Run `make claude-context` again

## Contributing

When adding new modules or major features:

1. Update `.claude_context.md` with architecture info
2. Add relevant flows to `docs/file_groups.json`
3. Update this README if adding new patterns
4. Test context generation works: `make claude-context`

---

*This system is designed to make Claude highly effective at understanding and working with the OCPI Connector codebase while minimizing context overhead.*
