# Use a specific Python version for consistency
FROM python:3.11.5-slim

# Set the working directory inside the container
WORKDIR /app

# Add the testing directory to the Python path
ENV PYTHONPATH "${PYTHONPATH}:/app"

# Copy and install requirements first to leverage Docker's layer caching
COPY testing/requirements.txt /app/testing/requirements.txt
RUN apt-get update && apt-get install -y curl netcat-openbsd && pip install --no-cache-dir -r /app/testing/requirements.txt

COPY testing/wait-for-it.sh /usr/local/bin/wait-for-it.sh

# Copy the actual test code
COPY testing/ /app/testing/
COPY examples/ /app/examples/

# The command to run when the container starts.
# Runs pytest with verbose output.
CMD ["pytest", "-v", "/app/testing/test_integration.py"]
