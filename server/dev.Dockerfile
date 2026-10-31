FROM python:3.12

WORKDIR /app

# PyPI is not reachable from inside build containers on this network (TLS reset),
# so every pip call goes through a mirror. Override with --build-arg if needed.
ARG PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple
ENV PIP_INDEX_URL=${PIP_INDEX_URL}

# Copy requirements first for better caching
COPY server/requirements.txt .
RUN pip install -r requirements.txt

# Test-only dependencies. Kept in a separate file so the runtime image stays lean
# and versions are pinned instead of floating with a bare `pip install pytest`.
COPY server/requirements-dev.txt .
RUN pip install -r requirements-dev.txt

# Install mem0 in editable mode. pip only — the poetry CLI installed above was
# never used, and its installer hangs on GitHub downloads in this network.
WORKDIR /app/packages
COPY pyproject.toml .
COPY poetry.lock .
COPY README.md .
COPY mem0 ./mem0
RUN pip install -e .[graph]

# Return to app directory and copy server code
WORKDIR /app
COPY server .

CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000", "--reload"]
