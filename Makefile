PYTHON ?= python3

.PHONY: help build serve validate test check clean ai-list ai-serve ai-test

help:
	@echo "OpenToolHub development commands"
	@echo "  make build     Stage data/*.json into site/data/"
	@echo "  make serve     Stage data, then serve site/ at http://127.0.0.1:8000/"
	@echo "  make validate  Validate the catalog with --strict"
	@echo "  make test      Run the Python test suite"
	@echo "  make check     Validate, test, stage, and verify the site artifact"
	@echo "  make ai-list   List configured AI providers (fine with none)"
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

ai-test:
	$(PYTHON) -m unittest tests.test_ai -v

clean:
	rm -rf site/data scripts/__pycache__ tests/__pycache__
