# Use the Python version as specified in your Azure DevOps pipeline
FROM python:3.10.13

RUN pip install --upgrade pip

WORKDIR /app
COPY . .
# Install Python dependencies
RUN pip install -r requirements.txt
 
# Install unixODBC development headers
RUN apt-get update && \
    apt-get install -y unixodbc-dev
 
# Install Tessseract
RUN apt-get install -y tesseract-ocr
 
# Install Ghostscript
 
RUN apt-get update && \
    apt-get install -y ghostscript
 
# Install Microsoft ODBC driver 17 and mssql-tools
RUN curl https://packages.microsoft.com/keys/microsoft.asc | apt-key add - && \
    curl https://packages.microsoft.com/config/ubuntu/20.04/prod.list | tee /etc/apt/sources.list.d/mssql-release.list && \
    apt-get update && \
    ACCEPT_EULA=Y apt-get install -y msodbcsql17 mssql-tools
 
 
# Set the timezone as needed
ENV TZ=Asia/Kolkata
 
# Install libGL for OpenCV
RUN apt-get update && apt-get install -y libgl1 && rm -rf /var/lib/apt/lists/*
 
# Expose port 8400
EXPOSE 8400
 
# Define the command to run the app using uvicorn
CMD ["uvicorn", "main:app", "--workers", "4", "--port", "8400", "--host", "0.0.0.0"]