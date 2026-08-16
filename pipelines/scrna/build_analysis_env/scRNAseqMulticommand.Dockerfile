# Author  : JZHANG
# Date    : 2025-12-23
# Version : v4.1.1-alpha

# ---------------------------------------------------------
# 1. Base Image
# ---------------------------------------------------------
FROM mambaorg/micromamba:latest

# Set metadata
LABEL org.opencontainers.image.authors="zhang jian zhangjian199567@outlook.com"
LABEL org.opencontainers.image.title="scRNAseqMulticommand Docker Image"
LABEL org.opencontainers.image.description="Docker image for scRNAseqMulticommand analysis."
LABEL org.opencontainers.image.version="0.4.8v"

# ---------------------------------------------------------
# 2. System Dependencies & Timezone (Run as root)
# NOTE: Placed at the top to maximize Docker layer caching.
# System configurations rarely change, so they should be cached early.
# ---------------------------------------------------------
USER root
ENV TZ=Asia/Shanghai
RUN apt-get update && \
    DEBIAN_FRONTEND=noninteractive apt-get install -y tzdata && \
    ln -snf /usr/share/zoneinfo/$TZ /etc/localtime && \
    echo $TZ > /etc/timezone && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# ---------------------------------------------------------
# 3. Directories & Conda Environment (Run as mambauser)
# ---------------------------------------------------------
USER mambauser
RUN mkdir -p /home/mambauser/scRNAseqMulticommand && \
    mkdir -p /home/mambauser/workdir

# Copy ONLY the environment file first. 
# This ensures the heavy conda installation is cached unless the .yml changes.
COPY --chown=mambauser:mambauser ./build_analysis_env/scRNAseqMulticommand_environment.yml /home/mambauser/scRNAseqMulticommand/

# Install dependencies via micromamba and clean up to reduce image size
RUN micromamba env create -f /home/mambauser/scRNAseqMulticommand/scRNAseqMulticommand_environment.yml && \
    micromamba clean --all --yes

# ---------------------------------------------------------
# 4. Application Source Code
# NOTE: Placed after environment creation so code changes don't trigger re-installation.
# ---------------------------------------------------------
# Copy all analysis scripts and grant ownership
COPY --chown=mambauser:mambauser ./ /home/mambauser/scRNAseqMulticommand/

# Grant execution permissions to the main script and working directory
RUN chmod +x /home/mambauser/scRNAseqMulticommand/scRNAseqMulticommand && \
    chmod -R u+rwx /home/mambauser/workdir

# ---------------------------------------------------------
# 5. Runtime Configuration
# ---------------------------------------------------------
# Update PATH to include the command directory
ENV PATH="/home/mambauser/scRNAseqMulticommand:${PATH}"
ENV TZ=Asia/Shanghai

# Set working directory for input/output files
WORKDIR /home/mambauser/workdir

# Execute the main scRNA-seq analysis command by default
CMD ["/home/mambauser/scRNAseqMulticommand/scRNAseqMulticommand"]