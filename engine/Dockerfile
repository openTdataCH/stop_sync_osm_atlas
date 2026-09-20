FROM python:3.13-slim-bookworm
WORKDIR /opt/transport-matcher
COPY . .
RUN pip install --no-cache-dir '.[swiss,gtfs,acquisition]'
WORKDIR /work
ENTRYPOINT ["transport-matcher"]
