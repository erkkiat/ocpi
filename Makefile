.PHONY: help claude-context claude-flow test test-unit test-integration test-cov clean

help:
	@echo "Available commands:"
	@echo "  make claude-context    - Generate fresh context for Claude"
	@echo "  make claude-flow FLOW=<n> - Read files for a specific flow"
	@echo "  make list-flows        - List all available flows"
	@echo "  make test              - Run all tests"
	@echo "  make test-unit         - Run unit tests only"
	@echo "  make test-integration  - Run integration tests only"
	@echo "  make test-cov          - Run tests with coverage"
	@echo "  make clean             - Clean cache files"

claude-context:
	@echo "Generating Claude context..."
	@./.claude/scripts/generate_claude_context.sh
	@echo ""
	@echo "✓ Context ready!"
	@echo ""
	@echo "In Claude chat, say:"
	@echo '  "Read .claude/context.md and .claude/context_auto.md"'

claude-flow:
	@if [ -z "$(FLOW)" ]; then \
		echo "Error: FLOW parameter required"; \
		echo "Usage: make claude-flow FLOW=authorization_flow"; \
		echo ""; \
		make list-flows; \
		exit 1; \
	fi
	@./.claude/scripts/read_flow.sh $(FLOW)

list-flows:
	@echo "Available flows:"
	@jq -r 'to_entries[] | "  \(.key) - \(.value.description)"' .claude/file_groups.json

test:
	pytest

test-unit:
	pytest tests/unit/

test-integration:
	pytest tests/integration/

test-cov:
	pytest --cov=ocpi22 --cov=ocpiconnector --cov-report=html --cov-report=term

clean:
	find . -type d -name "__pycache__" -exec rm -rf {} + 2>/dev/null || true
	find . -type f -name "*.pyc" -delete
	rm -rf .pytest_cache
	rm -rf htmlcov
	rm -rf .coverage
