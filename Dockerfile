
# Use an official Python runtime as a parent image
FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    tzdata \
    && rm -rf /var/lib/apt/lists/*

ENV TZ=Asia/Tashkent
ENV LANG=C.UTF-8
ENV LC_ALL=C.UTF-8
ENV PYTHONIOENCODING=UTF-8

# 3. Устанавливаем переменные окружения, чтобы Python не буферизовал вывод.
ENV PYTHONDONTWRITEBYTECODE=1
ENV PYTHONUNBUFFERED=1

# Set the working directory in the container
WORKDIR /app

# Copy auth-connector package first (from parent directory context)
COPY auth-connector /app/auth-connector

# Copy the requirements file into the container at /app
COPY client_service/requirements.txt .

# Install any needed packages specified in requirements.txt
# Use --no-cache-dir to reduce image size
RUN pip install --no-cache-dir -r requirements.txt

# Copy the rest of the application code into the container at /app
COPY client_service /app

# Make port 5002 available to the world outside this container
EXPOSE 80

# Define environment variables
ENV FLASK_APP=run.py
ENV FLASK_RUN_HOST=0.0.0.0
ENV FLASK_RUN_PORT=80

# Run app.py when the container launches
CMD ["python", "run.py"]
