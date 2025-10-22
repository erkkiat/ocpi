#!/bin/bash

# Install git hooks for automatic Claude context regeneration
# Run this once after cloning the repo

set -e

echo "Installing git hooks for Claude context auto-regeneration..."

# Create post-commit hook
cat > .git/hooks/post-commit << 'EOF'
#!/bin/bash

# Auto-regenerate Claude context after each commit
# This ensures Claude always has the latest project state

./.claude/scripts/generate_claude_context.sh > /dev/null 2>&1

# Exit successfully regardless of script result
exit 0
EOF

# Create post-merge hook
cat > .git/hooks/post-merge << 'EOF'
#!/bin/bash

# Auto-regenerate Claude context after merging/pulling
# This ensures Claude has context for newly pulled changes

echo "🤖 Updating Claude context..."
./.claude/scripts/generate_claude_context.sh

exit 0
EOF

# Make hooks executable
chmod +x .git/hooks/post-commit
chmod +x .git/hooks/post-merge

echo "✓ Git hooks installed successfully!"
echo ""
echo "What this does:"
echo "  - After each commit: Context auto-regenerates silently"
echo "  - After git pull/merge: Context auto-regenerates with notification"
echo ""
echo "You can now work normally and Claude context will stay up-to-date!"
