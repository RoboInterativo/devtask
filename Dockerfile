FROM python:3.11

ENV PYTHONUNBUFFERED=1
ENV POSTGRES_PASSWORD=postgres123
ENV DJANGO_DEBUG=1

RUN apt-get update && apt-get install -y gcc libpq-dev vim curl netcat-openbsd

WORKDIR /srv/syncapp
COPY . .
RUN pip install -r app/requirements.txt

WORKDIR /srv/syncapp/app
EXPOSE 8000

CMD ["sh", "/srv/syncapp/docker-entrypoint.sh"]
