FROM apify/actor-python:3.13
WORKDIR /usr/src/app
RUN pip install --no-cache-dir apify==4.2.0
COPY src/ ./src/
CMD ["python", "src/storage.py"]
