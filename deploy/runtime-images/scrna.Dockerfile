FROM omichub-analysis:plot-2026.07

LABEL org.opencontainers.image.title="OmicHub Analysis Single Cell"
LABEL org.omichub.runtime.profile="analysis-scrna"

USER "$MAMBA_USER"
RUN micromamba install -y -n base -c conda-forge -c bioconda \
      scanpy=1.10.4 \
      anndata=0.11.1 \
      leidenalg=0.10.2 \
      python-igraph=0.11.8 \
      h5py=3.12.1 \
      r-seurat=5.1.0 \
      bioconductor-singlecellexperiment=1.28.0 \
    && micromamba clean --all --yes
