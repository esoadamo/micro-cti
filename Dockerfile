FROM python:3.11

WORKDIR /app

COPY ./requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade -r requirements.txt
COPY ./schema.prisma /app/schema.prisma
ENV DATABASE_URL="mysql://root:microcti1234@micro-cti-db:3306/microcti"
RUN prisma generate

COPY . /app
CMD ["fastapi", "run", "web.py", "--port", "80", "--workers", "4", "--proxy-headers"]
