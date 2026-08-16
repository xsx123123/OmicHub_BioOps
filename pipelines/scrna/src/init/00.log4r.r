# This is log4r Functions module
# date : 2024.12.11
# author : zhang jian

#' Print a beautiful step header
#' @param logger Logger object
#' @param step_number Step number
#' @param title Step title
log_step <- function(logger, step_number, title) {
  require(crayon)
  full_title <- paste0("STEP ", step_number, ": ", title)
  
  info(logger, "")
  info(logger, bold(cyan(paste0(">>> ", full_title, " <<<"))))
  info(logger, silver(strrep("─", 58)))
}

#' Print a section divider
#' @param logger Logger object
log_divider <- function(logger) {
  require(crayon)
  info(logger, silver(strrep("─", 58)))
}

#' Quietly load a package without output
#' @param package Package name
#' @param logger Optional logger object to log loading
quiet_load_package <- function(package, logger = NULL) {
  if (!is.null(logger)) {
    debug(logger, paste0("Loading package: ", package))
  }
  suppressPackageStartupMessages({
    suppressMessages({
      suppressWarnings({
        require(package, character.only = TRUE, quietly = TRUE)
      })
    })
  })
}

#' Capture and log standard output/error
#' @param logger Logger object
#' @param expr Expression to evaluate
#' @param level Log level for captured output (default: "INFO")
#' @param prefix Prefix for captured output lines
capture_output_to_log <- function(logger, expr, level = "INFO", prefix = "  ") {
  # Capture both stdout and stderr (as messages)
  output <- capture.output({
    result <- withVisible(eval(expr, envir = parent.frame()))
  }, type = "output")
  
  error_output <- capture.output({
    eval(expr, envir = parent.frame())
  }, type = "message")

  all_output <- c(output, error_output)
  
  # Log captured output
  if (length(all_output) > 0) {
    for (line in all_output) {
      if (nzchar(trimws(line))) {
        log_msg <- paste0(prefix, line)
        switch(level,
               "INFO" = info(logger, log_msg),
               "WARN" = warn(logger, log_msg),
               "ERROR" = error(logger, log_msg),
               "DEBUG" = debug(logger, log_msg),
               info(logger, log_msg))
      }
    }
  }
  
  # Return the result invisibly
  if (result$visible) {
    result$value
  } else {
    invisible(result$value)
  }
}

#' Capture messages, warnings, and other conditions to log
#' @param logger Logger object
#' @param expr Expression to evaluate
#' @param prefix Prefix for log messages
capture_messages_to_log <- function(logger, expr, prefix = "  ") {
  withCallingHandlers({
    expr
  }, message = function(m) {
    msg <- conditionMessage(m)
    if (nzchar(trimws(msg))) {
      # Remove trailing newlines which are common in messages
      clean_msg <- gsub("\n$", "", msg)
      info(logger, paste0(prefix, clean_msg))
    }
    invokeRestart("muffleMessage")
  }, warning = function(w) {
    msg <- conditionMessage(w)
    if (nzchar(trimws(msg))) {
      clean_msg <- gsub("\n$", "", msg)
      warn(logger, paste0(prefix, clean_msg))
    }
    invokeRestart("muffleWarning")
  }, error = function(e) {
    # We don't muffle errors, just log them before they propagate
    msg <- conditionMessage(e)
    error(logger, paste0("ERROR: ", msg))
  })
}

#' Execute code and redirect ALL output (stdout/stderr) to logger
#' Improved version: Shows real-time output for stdout and captures messages
#' @param logger Logger object
#' @param expr Expression to evaluate
#' @param level Log level for output (default: "INFO")
with_logging <- function(logger, expr, level = "INFO") {
  # This uses a temporary file to capture everything including low-level cat() to stdout/stderr
  tmp <- tempfile()
  con <- file(tmp, open = "wt")
  
  # Track connection state to avoid 'invalid connection' errors on double close
  con_is_open <- TRUE
  
  # Ensure sinks are restored and connections closed on exit
  on.exit({
    if (sink.number() > 0) sink()
    if (con_is_open) {
      close(con)
      con_is_open <<- FALSE
    }
    if (file.exists(tmp)) unlink(tmp)
  }, add = TRUE)
  
  # For messages, we use a calling handler to log them in REAL-TIME
  result <- withCallingHandlers({
    # Sink stdout, use split=TRUE so user sees progress bars in real-time
    sink(con, split = TRUE)
    
    withVisible(eval(expr, envir = parent.frame()))
    
  }, message = function(m) {
    msg <- conditionMessage(m)
    if (nzchar(trimws(msg))) {
      # Log message in real-time with log4r decoration
      clean_msg <- gsub("\n$", "", msg)
      info(logger, paste0("  [Msg] ", clean_msg))
    }
    # Muffle the message so it doesn't print the raw version to console
    invokeRestart("muffleMessage")
  }, warning = function(w) {
    msg <- conditionMessage(w)
    if (nzchar(trimws(msg))) {
      warn(logger, paste0("  [Warn] ", gsub("\n$", "", msg)))
    }
    invokeRestart("muffleWarning")
  })
  
  # Restore sink and close connection now so we can read the file
  if (sink.number() > 0) sink()
  if (con_is_open) {
    close(con)
    con_is_open <- FALSE
  }
  
  # Read the captured stdout (the parts that went to the file)
  if (file.exists(tmp)) {
    lines <- readLines(tmp, warn = FALSE)
    for (line in lines) {
      if (nzchar(trimws(line))) {
        # Log to the requested level (INFO or DEBUG)
        log_msg <- paste0("  [Out] ", line)
        switch(level,
               "INFO" = info(logger, log_msg),
               "DEBUG" = debug(logger, log_msg),
               "WARN" = warn(logger, log_msg),
               info(logger, log_msg))
      }
    }
  }
  
  if (result$visible) return(result$value)
  return(invisible(result$value))
}

#' Execute code silently and capture ALL output to log
#' @param logger Logger object
#' @param expr Expression to evaluate
#' @param output_level Log level for stdout (default: "DEBUG")
#' @param message_level Log level for messages (default: "DEBUG")
#' @param show_in_console Whether to also show output in console (default: FALSE)
silent_exec <- function(logger, expr, output_level = "DEBUG", message_level = "DEBUG", show_in_console = FALSE) {
  .level_map <- list(
    "DEBUG" = debug,
    "INFO" = info,
    "WARN" = warn,
    "ERROR" = error,
    "FATAL" = fatal
  )
  
  output_log_fun <- .level_map[[output_level]] %||% info
  message_log_fun <- .level_map[[message_level]] %||% info
  
  # Try to set package-specific verbose options to FALSE globally within this scope
  # This helps reduce noise from packages that respect these options
  old_opts <- options(
    Seurat.verbose = FALSE,
    future.verbose = FALSE,
    Matrix.verbose = FALSE,
    ask = FALSE
  )
  on.exit(options(old_opts), add = TRUE)

  result <- NULL
  
  withCallingHandlers({
    if (show_in_console) {
      output <- capture.output({
        result <- withVisible(eval(expr, envir = parent.frame()))
      }, type = "output", split = TRUE)
    } else {
      output <- capture.output({
        result <- withVisible(eval(expr, envir = parent.frame()))
      }, type = "output")
    }
    
    if (length(output) > 0) {
      for (line in output) {
        if (nzchar(trimws(line))) {
          output_log_fun(logger, paste0("  ", line))
        }
      }
    }
  }, message = function(m) {
    msg <- conditionMessage(m)
    if (nzchar(trimws(msg))) {
      message_log_fun(logger, paste0("  ", trimws(msg)))
    }
    if (!show_in_console) {
      invokeRestart("muffleMessage")
    }
  }, warning = function(w) {
    msg <- conditionMessage(w)
    if (nzchar(trimws(msg))) {
      warn(logger, paste0("  ", trimws(msg)))
    }
    if (!show_in_console) {
      invokeRestart("muffleWarning")
    }
  })
  
  if (!is.null(result) && result$visible) {
    result$value
  } else {
    invisible(result$value)
  }
}

#' Set global options for the pipeline to suppress noise and set consistent behavior
#' @param logger Logger object
set_pipeline_options <- function(logger) {
  info(logger, "🔧 Setting global pipeline options to suppress package noise...")

  options(
    Seurat.verbose = FALSE,
    future.verbose = FALSE,
    Matrix.verbose = FALSE,
    scvi.verbose = FALSE,
    ask = FALSE,
    stringsAsFactors = FALSE
  )

  # Set future backend if possible to be quiet
  if (requireNamespace("future", quietly = TRUE)) {
    options(future.rng.onMisuse = "ignore")
  }

  invisible(NULL)
}

#' Global output sink manager
#' @description Redirects all stdout/stderr to logger
#' @param logger Logger object
#' @param enable Whether to enable global sink (default: TRUE)
global_sink <- function(logger, enable = TRUE) {
  if (enable) {
    .GlobalEnv$.original_stdout <- sink(number = NULL, type = "output")
    .GlobalEnv$.original_stderr <- sink(number = NULL, type = "message")
    
    sink_connection <- textConnection("global_sink_buffer", open = "w", local = TRUE)
    .GlobalEnv$.sink_connection <- sink_connection
    
    sink(sink_connection, type = "output")
    sink(sink_connection, type = "message")
    
    .GlobalEnv$.sink_enabled <- TRUE
    
    info(logger, "Global output sink enabled")
  } else {
    if (exists(".sink_enabled", envir = .GlobalEnv) && .GlobalEnv$.sink_enabled) {
      sink(type = "output")
      sink(type = "message")
      
      if (exists(".sink_connection", envir = .GlobalEnv)) {
        close(.GlobalEnv$.sink_connection)
      }
      
      if (exists("global_sink_buffer", envir = .GlobalEnv)) {
        for (line in global_sink_buffer) {
          if (nzchar(trimws(line))) {
            debug(logger, paste0("  ", line))
          }
        }
        rm("global_sink_buffer", envir = .GlobalEnv)
      }
      
      .GlobalEnv$.sink_enabled <- FALSE
      info(logger, "Global output sink disabled")
    }
  }
}

#' Helper: Null-coalescing operator
`%||%` <- function(x, y) if (is.null(x)) y else x

#' Initialize Logger
#'
#' @param level Character. Log level: "DEBUG", "INFO", "WARN", "ERROR", "FATAL". Default "INFO".
#' @param log_file Character. Optional path to the log file. If NULL, logging to file is disabled.
#' @return A logger object.
log4r_init <- function(level = "INFO", log_file = NULL){
  require(log4r)
  require(crayon)
  
  # Define clean file layout (without colors and emojis)
  my_file_layout <- function(level, ...) {
    time_str <- format(Sys.time(), "%Y-%m-%d %H:%M:%S")
    msg <- paste0(..., collapse = "\n")
    level_str <- sprintf("%-5s", level)
    paste0(time_str, " [", level_str, "] ", msg, "\n")
  }
  
  # Define beautiful console layout
  my_console_layout <- function(level, ...) {
    time_str <- format(Sys.time(), "%H:%M:%S")
    msg <- paste0(..., collapse = "\n")
    
    # Symbols for different log levels
    symbols <- list(
      INFO = "●",
      WARN = "▲",
      ERROR = "✗",
      FATAL = "✖",
      DEBUG = "◆"
    )
    symbol <- ifelse(level %in% names(symbols), symbols[[level]], "○")
    
    if (level == 'INFO'){
      paste0(silver("│ "), cyan(time_str), silver(" │ "), 
             bold(green(symbol, " INFO")), silver("  │ "), msg, '\n')
    } else if (level == 'WARN'){
      paste0(silver("│ "), cyan(time_str), silver(" │ "), 
             bold(yellow(symbol, " WARN")), silver("  │ "), msg, '\n')
    } else if (level == 'ERROR'){
      paste0(silver("│ "), cyan(time_str), silver(" │ "), 
             bold(red(symbol, " ERROR")), silver(" │ "), msg, '\n')
    } else if (level == 'FATAL'){
      paste0(silver("│ "), cyan(time_str), silver(" │ "), 
             bold(bgRed(white(" ", symbol, " FATAL ", " "))), silver(" │ "), msg, '\n')
    } else if (level == 'DEBUG'){
      paste0(silver("│ "), cyan(time_str), silver(" │ "), 
             bold(blue(symbol, " DEBUG")), silver(" │ "), msg, '\n')
    } else {
      paste0(silver("│ "), cyan(time_str), silver(" │ "), 
             symbol, " ", level, " │ ", msg, '\n')
    }
  }

  appenders_list <- list(console_appender(my_console_layout))
  
  # Add file appender if log_file is provided
  if (!is.null(log_file)) {
    file_out <- log4r::file_appender(log_file, layout = my_file_layout)
    appenders_list <- c(appenders_list, file_out)
  }
  
  logger <- log4r::logger(threshold = level, appenders = appenders_list)
  return(logger)
}
# ==============================================================================
# END 
# ==============================================================================