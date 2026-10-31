PYTHON ?= python3
NODE ?= node

.PHONY: help serve test fetch

help:
	@echo "Public data dashboard starter"
	@echo "  make serve   Serve app/ at http://127.0.0.1:8000/"
	@echo "  make test    Run the Node test suite"
	@echo "  make fetch   Refresh app/data/indicators.json from the World Bank API"

serve:
	$(PYTHON) -m http.server 8000 --directory app

test:
	$(NODE) --test tests/*.test.mjs

fetch:
	$(PYTHON) scripts/fetch_data.py
