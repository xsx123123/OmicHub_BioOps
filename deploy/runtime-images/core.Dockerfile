FROM mambaorg/micromamba:2.0.5

LABEL org.opencontainers.image.title="OmicHub Analysis Core"
LABEL org.opencontainers.image.description="Independent micromamba Python/R task runtime for OmicStudio and toolbox executors"
LABEL org.omichub.runtime.family="omichub-analysis"
LABEL org.omichub.runtime.profile="analysis-core"

USER root
COPY requirements-agent.txt /tmp/requirements-agent.txt
RUN usermod --uid 10001 "$MAMBA_USER" \
    && groupmod --gid 10001 "$MAMBA_USER" \
    && chown -R 10001:10001 /home/"$MAMBA_USER" /opt/conda \
    && mkdir -p /opt/omichub \
    && chown -R 10001:10001 /opt/omichub /tmp/requirements-agent.txt \
    && mkdir -p /workspace/.logs \
    && chown -R 10001:10001 /workspace \
    && printf '%s\n' \
      '[global]' \
      'index-url = https://pypi.mirrors.ustc.edu.cn/simple' \
      'extra-index-url = https://mirrors.aliyun.com/pypi/simple/' \
      'timeout = 60' \
      'retries = 10' \
      > /etc/pip.conf

USER "$MAMBA_USER"
# 预置中科大镜像源，加速容器内 micromamba/conda 环境安装
RUN printf '%s\n' \
      'show_channel_urls: true' \
      'default_channels:' \
      '  - https://mirrors.ustc.edu.cn/anaconda/pkgs/main' \
      '  - https://mirrors.ustc.edu.cn/anaconda/pkgs/free' \
      '  - https://mirrors.ustc.edu.cn/anaconda/pkgs/r' \
      '  - https://mirrors.ustc.edu.cn/anaconda/pkgs/msys2' \
      'custom_channels:' \
      '  conda-forge: https://mirrors.ustc.edu.cn/anaconda/cloud' \
      '  bioconda: https://mirrors.ustc.edu.cn/anaconda/cloud' \
      '  menpo: https://mirrors.ustc.edu.cn/anaconda/cloud' \
      '  pytorch: https://mirrors.ustc.edu.cn/anaconda/cloud' \
      'channel_priority: flexible' \
      'channels:' \
      '  - conda-forge' \
      '  - bioconda' \
      '  - menpo' \
      '  - defaults' \
      > ~/.condarc
RUN micromamba install -y -n base -c conda-forge -c bioconda \
      python=3.12 \
      r-base=4.4 \
      pip=24.3 \
      uv=0.5 \

      pandas=2.2.3 \
      numpy=2.1.3 \
      scipy=1.14.1 \
      scikit-learn=1.5.2 \
      statsmodels=0.14.4 \
      openpyxl=3.1.5 \
      pyarrow=18.1.0 \
      bioconductor-deseq2=1.46.0 \
      bioconductor-edger=4.4.0 \
      bioconductor-limma=3.62.1 \
    && micromamba run -n base pip install -r /tmp/requirements-agent.txt \
    && micromamba clean --all --yes

# agent 脚本变动频繁，放在重型依赖层之后，改动时不触发 micromamba 重装
COPY --chown=10001:10001 sandbox_agent.py /opt/omichub/sandbox_agent.py

# 终端体验工具（独立层，与科学生态栈解耦）：btop / zsh / oh-my-posh / oh-my-zsh
# 参考 tool_configs/terminal/docker/Dockerfile；plot/scrna 派生镜像自动继承本层
RUN micromamba install -y -n base -c conda-forge \
      btop \
      zsh \
      git \
      oh-my-posh \
    && micromamba clean --all --yes \
    && micromamba run -n base git clone --depth 1 https://github.com/ohmyzsh/ohmyzsh.git /opt/omichub/oh-my-zsh
COPY --chown=10001:10001 studio-zshrc /opt/omichub/zdotdir/.zshrc
COPY --chown=10001:10001 studio.omp.json /opt/omichub/themes/studio.omp.json

ENV PYTHONUNBUFFERED=1 PYTHONDONTWRITEBYTECODE=1 MPLBACKEND=Agg SANDBOX_WORKSPACE=/workspace
WORKDIR /workspace
CMD ["micromamba", "run", "-n", "base", "sh", "-c", "rm -f /workspace/.agent.sock && exec uvicorn --app-dir /opt/omichub sandbox_agent:app --uds /workspace/.agent.sock"]
