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

COPY . /app
CMD ["uv", "run", "fastapi", "run", "web.py", "--port", "80", "--workers", "4", "--proxy-headers"]
