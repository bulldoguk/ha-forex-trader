ARG BUILD_FROM
FROM $BUILD_FROM

WORKDIR /app

# Install dependencies
COPY requirements.txt .
RUN pip3 install --no-cache-dir -r requirements.txt

# Copy source code
COPY backtester/ ./backtester/
COPY trader/     ./trader/
COPY webapp.py   entrypoint.py ./

# Copy run script
COPY run.sh /run.sh
RUN chmod +x /run.sh

CMD ["/run.sh"]
