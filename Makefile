PYTHON ?= python3
NODE ?= node

.PHONY: help build serve validate test check clean ai-list ai-serve ai-check ai-live ai-test starter-test

help:
	@echo "OpenToolHub development commands"
	@echo "  make build     Stage data/*.json into site/data/"
	@echo "  make serve     Stage data, then serve site/ at http://127.0.0.1:8000/"
	@echo "  make validate  Validate the catalog with --strict"
	@echo "  make test      Run the Python test suite"
	@echo "  make check     Validate, test, stage, and verify the site artifact"
	@echo "  make starter-test  Run the Node tests of every runnable template"
	@echo "  make ai-list   List configured AI providers (fine with none)"
	@echo "  make ai-check  Send one real request and report the model's answer"
	@echo "  make ai-live   Run the opt-in live provider suite against that provider"
	@echo "  make ai-serve  Serve site/ with the optional loopback AI endpoint"
	@echo "  make ai-test   Run only the AI layer tests"
	@echo "  make clean     Remove staged data and Python caches"

build:
	$(PYTHON) scripts/build_site.py

serve:
	$(PYTHON) scripts/build_site.py --serve

validate:
	$(PYTHON) scripts/validate.py --strict

test:
	$(PYTHON) -m unittest discover -s tests -v

check:
	$(PYTHON) scripts/validate.py --strict
	$(PYTHON) -m unittest discover -s tests -v
	$(PYTHON) scripts/build_site.py
	$(PYTHON) scripts/build_site.py --check

ai-list:
	$(PYTHON) scripts/ai_chat.py --list

ai-serve:
	$(PYTHON) scripts/ai_proxy.py

ai-check:
	$(PYTHON) scripts/ai_chat.py --check

ai-live:
	OPEN_TOOL_HUB_AI_LIVE=1 $(PYTHON) -m unittest tests.test_ai_live -v

ai-test:
	$(PYTHON) -m unittest tests.test_ai -v

starter-test:
	@found=0; last=""; \
	for suite in templates/*/tests/*.test.mjs; do \
		[ -e "$$suite" ] || continue; \
		starter=$$(dirname "$$(dirname "$$suite")"); \
		if [ "$$starter" = "$$last" ]; then continue; fi; \
		last=$$starter; found=1; \
		echo "== $$starter"; \
		( cd "$$starter" && $(NODE) --test tests/*.test.mjs ) || exit 1; \
	done; \
	if [ "$$found" -eq 0 ]; then echo "No template test suites found."; fi

clean:
	rm -rf site/data scripts/__pycache__ tests/__pycache__ templates/*/scripts/__pycache__
