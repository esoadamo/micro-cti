FROM python:3.12

WORKDIR /app

RUN pip install --no-cache-dir uv
COPY ./pyproject.toml /app/pyproject.toml
COPY ./.python-version /app/.python-version
COPY ./uv.lock /app/uv.lock
RUN uv sync --locked
COPY ./schema.prisma /app/schema.prisma
ENV DATABASE_URL="mysql://root:microcti1234@micro-cti-db:3306/microcti"
RUN uv run prisma generate
ENV UCTI_LOG_DIR="/var/log/ucti"
ENV UCTI_DATA_DIR="/data"
ENV UCTI_BACKUP_DIR="/backup"
ENV UCTI_CACHE_DIR="/cache"
ENV UCTI_CONFIG_DIR="/config"
RUN mkdir -p "$UCTI_LOG_DIR" "$UCTI_DATA_DIR" "$UCTI_BACKUP_DIR" "$UCTI_CACHE_DIR" "$UCTI_CONFIG_DIR"
COPY . /app
RUN chmod +x /app/entrypoint.sh
CMD ["/app/entrypoint.sh"]
