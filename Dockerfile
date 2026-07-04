FROM ghcr.io/astral-sh/uv:python3.12-bookworm-slim AS build
WORKDIR /app
COPY pyproject.toml ./
COPY src ./src
RUN uv pip install --system .

FROM python:3.12-slim-bookworm
RUN useradd -m janus
WORKDIR /app
COPY --from=build /usr/local/lib/python3.12/site-packages /usr/local/lib/python3.12/site-packages
COPY --from=build /usr/local/bin /usr/local/bin
COPY src ./src
ENV PYTHONPATH=/app/src
USER janus
EXPOSE 8000
CMD ["uvicorn", "janus.main:app", "--host", "0.0.0.0", "--port", "8000"]
