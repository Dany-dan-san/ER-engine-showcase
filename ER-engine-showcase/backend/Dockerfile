# Use the same major R version used to inspect/train the model.
FROM rocker/r-ver:4.4.1

# Install Python and compilers needed by Python/R packages.
RUN apt-get update && apt-get install -y \
    python3 \
    python3-pip \
    python3-venv \
    build-essential \
    gfortran \
    glpk-utils \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Create an isolated Python environment inside the container.
RUN python3 -m venv /opt/venv

ENV PATH="/opt/venv/bin:${PATH}"
ENV PYTHONUNBUFFERED=1

# Install Python dependencies.
COPY requirements.txt .

RUN python -m pip install --upgrade pip \
    && python -m pip install --no-cache-dir -r requirements.txt

# Install Chromium and Linux libraries required by Playwright.
RUN python -m playwright install --with-deps chromium

# Install the R package required by the frozen RF2 model.
RUN Rscript -e \
    "install.packages('randomForest', repos='https://cloud.r-project.org')"

# Copy backend application code.
COPY app ./app
COPY models ./models
COPY r ./r

# Verify resources that ARE intentionally stored in GitHub.
RUN test -f models/RF2_frozen_model_predictor_columns.csv \
    && test -f r/score_rf2.R

# Verify runtimes.
RUN Rscript --version \
    && python --version

# Cloud Run provides PORT automatically.
CMD ["sh", "-c", "exec uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
