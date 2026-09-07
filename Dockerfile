FROM python:3.12-slim

WORKDIR /app
COPY . /app
RUN pip install --no-cache-dir .

ENV MODAL_PLUGIN_TRANSPORT=streamable-http \
    MODAL_PLUGIN_HOST=0.0.0.0 \
    MODAL_PLUGIN_PORT=8000 \
    MODAL_PLUGIN_DATA_DIR=/data

EXPOSE 8000
CMD ["modal-plugin", "--transport", "streamable-http", "--host", "0.0.0.0", "--port", "8000"]
