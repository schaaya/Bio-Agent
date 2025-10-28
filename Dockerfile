# Use the Python version as specified in your Azure DevOps pipeline
FROM python:3.10.13

RUN pip install --upgrade pip

# Install wget for downloading LFS file
RUN apt-get update && \
    apt-get install -y wget

WORKDIR /app
COPY . .

# Download the actual LFS file from GitHub
# Get the LFS pointer and extract the OID
RUN LFS_OID=$(grep 'oid sha256:' NSLC/bio_gene_expression.db | cut -d':' -f2 | tr -d ' ') && \
    echo "Downloading LFS file with OID: $LFS_OID" && \
    wget -O NSLC/bio_gene_expression.db \
    "https://media.githubusercontent.com/media/schaaya/Bio-Agent/main/NSLC/bio_gene_expression.db" || \
    echo "WARNING: Failed to download database file"

# Verify the database file exists and is large enough
RUN ls -lh NSLC/bio_gene_expression.db && \
    FILE_SIZE=$(stat -c%s NSLC/bio_gene_expression.db) && \
    echo "Database file size: $FILE_SIZE bytes" && \
    [ "$FILE_SIZE" -gt 100000000 ] || echo "WARNING: Database file seems too small!"
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