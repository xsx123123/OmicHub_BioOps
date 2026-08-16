# author  : zhang jian
# date    : 2025-12-23
# version : v4.0.4-alpha
# description : this is scRNAseqMulticommand docker images dockerfile
# setting base docker images

# ==========================================
# Stage 1: Build environment & Setup
# ==========================================
FROM mambaorg/micromamba:latest AS builder

# Set the maintainer
LABEL org.opencontainers.image.authors="zhang jian zhangjian199567@outlook.com"
LABEL org.opencontainers.image.title="scRNAseqMulticommand Docker Image"
LABEL org.opencontainers.image.description="Docker image for scRNAseqMulticommand analysis."
LABEL org.opencontainers.image.version="0.4.7v"

# Create directories
RUN mkdir -p /home/mambauser/scRNAseqMulticommand && \
    mkdir -p /home/mambauser/workdir

# Copy environment file
# Assumes build context is the project root
COPY ./build_analysis_env/scRNAseqMulticommand_environment.yml /home/mambauser/scRNAseqMulticommand/

# Install dependencies using micromamba
# The environment name 'scrna' is defined in the .yml file
# Default location for micromamba envs is /opt/conda/envs/
RUN micromamba env create -f /home/mambauser/scRNAseqMulticommand/scRNAseqMulticommand_environment.yml && \
    micromamba clean --all --yes

# Copy all analysis scripts (entire project context)
COPY ./ /home/mambauser/scRNAseqMulticommand/

# Change ownership and permissions in builder
USER root
RUN chown -R mambauser:mambauser /home/mambauser/scRNAseqMulticommand/ && \
    chmod +x /home/mambauser/scRNAseqMulticommand/scRNAseqMulticommand && \
    chown -R mambauser:mambauser /home/mambauser/workdir && \
    chmod -R u+rwx /home/mambauser/workdir

# ==========================================
# Stage 2: Final image (Runtime)
# ==========================================
FROM mambaorg/micromamba:latest

# Metadata
LABEL org.opencontainers.image.authors="zhang jian zhangjian199567@outlook.com"
LABEL org.opencontainers.image.version="0.4.7v"

# 1. Copy the Conda environment from builder
# Note: 'scrna' is the name defined in the yaml file
COPY --from=builder --chown=mambauser:mambauser /opt/conda/envs/scrna /opt/conda/envs/scrna

# 2. Copy project files and workdir from builder
COPY --from=builder --chown=mambauser:mambauser /home/mambauser/scRNAseqMulticommand /home/mambauser/scRNAseqMulticommand
COPY --from=builder --chown=mambauser:mambauser /home/mambauser/workdir /home/mambauser/workdir

# Switch to non-root user
USER mambauser

# 3. CRITICAL: Update PATH to include the Conda environment bin
# This ensures 'R', 'Rscript', 'python' etc. come from our installed env
ENV PATH="/opt/conda/envs/scrna/bin:/home/mambauser/scRNAseqMulticommand:${PATH}"

# Set working directory
WORKDIR /home/mambauser/workdir

# Default command
CMD ["/home/mambauser/scRNAseqMulticommand/scRNAseqMulticommand"]