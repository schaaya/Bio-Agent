# Use the Python version as specified in your Azure DevOps pipeline
FROM python:3.10.13

RUN pip install --upgrade pip

# Install Git LFS
RUN apt-get update && \
    apt-get install -y git-lfs && \
    git lfs install

WORKDIR /app
COPY . .

# Pull LFS files (including the bio database)
RUN git lfs pull || echo "Git LFS pull failed or no LFS files"

# Verify the database file exists
RUN ls -lh NSLC/bio_gene_expression.db || echo "WARNING: Database file not found!"
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
 
# Expose port 8000 (Railway uses PORT env var)
EXPOSE 8000

# Define the command to run the app using uvicorn
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8000"]