PYTHON ?= python3

.PHONY: help build serve validate test check clean

help:
	@echo "OpenToolHub development commands"
	@echo "  make build     Stage data/*.json into site/data/"
	@echo "  make serve     Stage data, then serve site/ at http://127.0.0.1:8000/"
	@echo "  make validate  Validate the catalog with --strict"
	@echo "  make test      Run the Python test suite"
	@echo "  make check     Validate, test, stage, and verify the site artifact"
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

clean:
	rm -rf site/data scripts/__pycache__ tests/__pycache__
