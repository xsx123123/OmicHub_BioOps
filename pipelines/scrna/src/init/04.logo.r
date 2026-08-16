#!/usr/bin/env Rscript
# RecombTracer Logo Display Module for R with Colors
# ======================================

# 定义颜色代码
color_codes <- list(
  red = "\033[31m",
  green = "\033[32m",
  yellow = "\033[33m",
  blue = "\033[34m",
  magenta = "\033[35m",
  cyan = "\033[36m",
  white = "\033[37m",
  bold_red = "\033[1;31m",
  bold_green = "\033[1;32m",
  bold_yellow = "\033[1;33m",
  bold_blue = "\033[1;34m",
  bold_magenta = "\033[1;35m",
  bold_cyan = "\033[1;36m",
  bold_white = "\033[1;37m",
  reset = "\033[0m"
)

# 获取随机颜色
get_random_color <- function() {
  colors <- c("red", "green", "yellow", "blue", "magenta", "cyan", "white",
              "bold_red", "bold_green", "bold_yellow", "bold_blue", "bold_magenta", "bold_cyan", "bold_white")
  return(sample(colors, 1))
}

# 用颜色包装文本
color_text <- function(text, color_name) {
  if (color_name %in% names(color_codes)) {
    return(paste0(color_codes[[color_name]], text, color_codes$reset))
  } else {
    return(text)
  }
}

show_logo <- function(style = "welcome",
                     version = "v1.0.0",
                     app_name = "RecombTracer",
                     description = "Genome Recombination Analysis Tool",
                     use_random_color = TRUE) {
  
  # 定义多个ASCII logos
  ascii_logos <- list(
    "
        ▖▖▄▖▖▖▗ ▄▖▄▖▗ ▄▖▄▖
        ▚▘▚ ▚▘▜ ▄▌▄▌▜ ▄▌▄▌
        ▌▌▄▌▌▌▟▖▙▖▄▌▟▖▙▖▄▌
    ",
    "
        ██   ██ ███████ ██   ██  ██ ██████  ██████   ██ ██████  ██████  
         ██ ██  ██       ██ ██  ███      ██      ██ ███      ██      ██ 
          ███   ███████   ███    ██  █████   █████   ██  █████   █████  
         ██ ██       ██  ██ ██   ██ ██           ██  ██ ██           ██ 
        ██   ██ ███████ ██   ██  ██ ███████ ██████   ██ ███████ ██████
    ",
    "
        ▒██   ██▒  ██████ ▒██   ██▒
        ▒▒ █ █ ▒░▒██    ▒ ▒▒ █ █ ▒░
        ░░  █   ░░ ▓██▄   ░░  █   ░
        ░ █ █ ▒   ▒   ██▒ ░ █ █ ▒ 
        ▒██▒ ▒██▒▒██████▒▒▒██▒ ▒██▒
    ",
    "
        ░█░█░█▀▀░█░█░▀█░░▀▀▄░▀▀█░▀█░░▀▀▄░▀▀█
        ░▄▀▄░▀▀█░▄▀▄░░█░░▄▀░░░▀▄░░█░░▄▀░░░▀▄
        ░▀░▀░▀▀▀░▀░▀░▀▀▀░▀▀▀░▀▀░░▀▀▀░▀▀▀░▀▀░
    ",
    "
        __  ______  ___ ____  _____ _ ____  _____ 
        \\\\ \\\\/ / _\\\\ \\\\/ / |___ \\\\|___ // |___ \\\\|___ / 
         \\\\  /\\\\ \\\\ \\\\  /| | __) | |_ \\\\| | __) | |_ \\\\ 
         /  \\\\_\\\\ \\\\/  \\\\| |/ __/ ___) | |/ __/ ___) |
        /_/\\\\_\\\\__/_/\\\\_\\\\_|_____|____/|_|_____|____/ 
    ",
    "
        ▗▖  ▗▖ ▗▄▄▖▗▖  ▗▖
         ▝▚▞▘ ▐▌    ▝▚▞▘ 
          ▐▌   ▝▀▚▖  ▐▌  
        ▗▞▘▝▚▖▗▄▄▞▘▗▞▘▝▚▖
    ",
    "
        ┏┓┏┓┏┓┏┓┏┓┓┏┓┏┓┓┏┓┏┓
         ┃┃ ┗┓ ┃┃ ┃┏┛ ┫┃┏┛ ┫
        ┗┛┗┛┗┛┗┛┗┛┻┗━┗┛┻┗━┗┛
    ",
    "
        ╻ ╻┏━┓╻ ╻╺┓ ┏━┓┏━┓╺┓ ┏━┓┏━┓
        ┏╋┛┗━┓┏╋┛ ┃ ┏━┛╺━┫ ┃ ┏━┛╺━┫
        ╹ ╹┗━┛╹ ╹╺┻╸┗━╸┗━┛╺┻╸┗━╸┗━┛
    ",
    "
           _     _      _     _      _     _
          (c).-.(c)    (c).-.(c)    (c).-.(c)
           / ._. \\\\      / ._. \\\\      / ._. \\\\
         __\\\\( Y )/__  __\\\\( Y )/__  __\\\\( Y )/__  
        (.-/'-'\\\\\\.-.)(.-/'-'\\\\\\.-.)(.-/'-'\\\\\\.-.)
           || X ||      || S ||      || X ||
         .' `-' .'  .' `-' .'  .' `-' .'
        (.-./`-'\\\\.-.)(.-./`-'\\\\.-.)(.-./`-'\\\\.-.)
         -'     -'  -'     -'  -'     -'
    "
  )
  
  # 随机选择logo和颜色
  selected_logo <- ascii_logos[[sample(length(ascii_logos), 1)]]
  logo_color <- if(use_random_color) get_random_color() else "cyan"
  text_color <- if(use_random_color) get_random_color() else "white"
  
  # 清屏
  cat("\014")
  
  if (style == "welcome") {
    # 显示带颜色的logo
    cat(color_text(selected_logo, logo_color))
    # cat("\n")
    # 显示应用信息
    app_info <- sprintf("        %s:%s\n        %s\n", app_name, version, description)
    cat(color_text(app_info, text_color))
    # cat("\n")
  } else if (style == "mini") {
    mini_text <- sprintf("%s:%s\n", app_name, version)
    cat(color_text(mini_text, text_color))
  }
}

# 彩虹色logo版本
show_rainbow_logo <- function(version = "v1.0.0",
                             app_name = "RecombTracer",
                             description = "Genome Recombination Analysis Tool") {
  
  rainbow_logo <- "
        ▖▖▄▖▖▖▗ ▄▖▄▖▗ ▄▖▄▖
        ▚▘▚ ▚▘▜ ▄▌▄▌▜ ▄▌▄▌
        ▌▌▄▌▌▌▟▖▙▖▄▌▟▖▙▖▄▌
  "
  
  # 彩虹色显示
  cat('\n')
  lines <- strsplit(rainbow_logo, "\n")[[1]]
  rainbow_colors <- c("red", "yellow", "green", "cyan", "blue", "magenta")
  
  # cat("\014")  # 清屏
  
  for (i in seq_along(lines)) {
    if (nchar(lines[i]) > 0) {
      color_idx <- (i - 1) %% length(rainbow_colors) + 1
      cat(color_text(lines[i], rainbow_colors[color_idx]))
      cat("\n")
    }
  }
  
  # cat("\n")
  # 彩虹色应用信息
  info_lines <- c(
    sprintf("        %s:%s", app_name, version),
    sprintf("        %s", description),
    ""
  )
  
  for (i in seq_along(info_lines)) {
    color_idx <- (i - 1) %% length(rainbow_colors) + 1
    cat(color_text(info_lines[i], rainbow_colors[color_idx]))
    cat("\n")
  }
}

# 渐变色logo显示
show_gradient_logo <- function(version = "v1.0.0",
                              app_name = "RecombTracer",
                              description = "Genome Recombination Analysis Tool") {
  
  simple_logo <- "
        ▖▖▄▖▖▖▗ ▄▖▄▖▗ ▄▖▄▖
        ▚▘▚ ▚▘▜ ▄▌▄▌▜ ▄▌▄▌
        ▌▌▄▌▌▌▟▖▙▖▄▌▟▖▙▖▄▌
  "
  
  # 渐变色 (蓝到紫到红)
  cat('\n')
  lines <- strsplit(simple_logo, "\n")[[1]]
  gradient_colors <- c("blue", "cyan", "green", "yellow", "magenta", "red")
  
  # cat("\014")  # 清屏
  
  for (i in seq_along(lines)) {
    if (nchar(lines[i]) > 0) {
      color_idx <- min(length(gradient_colors), max(1, round(i / length(lines) * length(gradient_colors))))
      cat(color_text(lines[i], gradient_colors[color_idx]))
      cat("\n")
    }
  }
  
  # cat("\n")
  # 渐变色应用信息
  info_text <- sprintf("        %s:%s\n        %s\n", app_name, version, description)
  info_lines <- strsplit(info_text, "\n")[[1]]
  
  for (i in seq_along(info_lines)) {
    if (nchar(info_lines[i]) > 0) {
      color_idx <- min(length(gradient_colors), max(1, round(i / length(info_lines) * length(gradient_colors))))
      cat(color_text(info_lines[i], gradient_colors[color_idx]))
      cat("\n")
    }
  }
}

# 简单版本
show_simple_logo <- function(use_color = TRUE) {
  logo <- "
        ▖▖▄▖▖▖▗ ▄▖▄▖▗ ▄▖▄▖
        ▚▘▚ ▚▘▜ ▄▌▄▌▜ ▄▌▄▌
        ▌▌▄▌▌▌▟▖▙▖▄▌▟▖▙▖▄▌
  "
  
  # cat("\014")  # 清屏
  cat('\n')
  if (use_color) {
    cat(color_text(logo, "cyan"))
    cat(color_text("\n    RecombTracer: Genome Recombination Analysis Tool\n\n", "white"))
  } else {
    cat(logo)
    cat("\n    RecombTracer: Genome Recombination Analysis Tool\n\n")
  }
}

# 随机选择logo样式显示
show_random_logo <- function(version = "v1.0.0",
                            app_name = "RecombTracer",
                            description = "Genome Recombination Analysis Tool") {
  cat(crayon::yellow(crayon::bold('<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<<\n')))
  logo_types <- c("random_color", "rainbow", "gradient", "simple")
  selected_type <- sample(logo_types, 1)
  
  switch(selected_type,
    "random_color" = show_logo(version = version, app_name = app_name, description = description, use_random_color = TRUE),
    "rainbow" = show_rainbow_logo(version = version, app_name = app_name, description = description),
    "gradient" = show_gradient_logo(version = version, app_name = app_name, description = description),
    "simple" = show_simple_logo(use_color = TRUE)
  )
  cat('\n')
  cat(crayon::yellow(crayon::bold('>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>>\n')))
  cat('\n')
}
# ==============================================================================
# END 
# ==============================================================================