PHONY: prepare-environment

ifeq ($(OS), Windows_NT)
    PYTHON = .venv\Scripts\python
else
    PYTHON = .venv/bin/python
endif

prepare-environment:
	uv sync
	$(PYTHON) -m pre-commit install
