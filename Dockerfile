FROM public.ecr.aws/docker/library/python:3.11-slim
WORKDIR /app

# Install ZeroTier
RUN apt-get update && apt-get install -y curl
RUN curl -s https://install.zerotier.com | bash

# Copy application files
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
COPY . .

# Create startup script
RUN echo '#!/bin/bash\n\
# Start ZeroTier service with full TUN/TAP access\n\
zerotier-one -d\n\
# Wait for ZeroTier to initialize\n\
sleep 5\n\
# Start the application\n\
exec python -m gunicorn --bind 0.0.0.0:8080 app:app\n'\
> /app/start.sh && chmod +x /app/start.sh

EXPOSE 8080
# Use the startup script as the entry point
CMD ["/app/start.sh"]