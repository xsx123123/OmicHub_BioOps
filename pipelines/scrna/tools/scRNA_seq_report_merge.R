#!/titan3/local_zhang_jian/miniconda3/miniconda3/envs/R/bin/Rscript
# author: zhang jian
# special: This is the scRNA-seq report merge script
#-----------------------------------####---------------------------------------#
suppressMessages(library("yaml"))
suppressMessages(library("log4r"))
suppressMessages(library("getopt"))
suppressMessages(library("stringr"))
suppressMessages(library("crayon"))
suppressMessages(library("praise"))
# LOG
#-----------------------------------####---------------------------------------#
# Get multi sample command parameter
scRNAseqmultiSampleCommand <- function() {
  # Setting run parameter
  spec <- matrix(
    c(
      "scRNADir",  "s", 2, "character", "Cellranger/DNBC4tools count result info tsv",
      'scRNAtype','t',2,"character","scRNA-seq library (BGI | 10x)",
      'conf','c',2,'character',"scRNA-seq Analysis Conf",
      "help", "h", 0, "logical", "Show help message",
      "version", "v", 0, "logical", "Show script version"
    ),
    byrow = TRUE, ncol = 5
  )
  # Input run parameter
  opt <- getopt(spec = spec)
  # Automatically show help if no parameters are provided
  if (length(opt) == 0) {
    cat("\033[1;34mThis is the scRNA-seq report merge script!\033[0m\n")
    cat("\033[1;32mUsage:scRNA_seq_report_merge -c scRNADir -t 10x  \033[0m\n")
    cat("   -s, --scRNADir        | Cellranger/DNBC4tools Result dir \n")
    cat("   -t, --scRNAtype       | scRNA-seq library (BGI | 10x) \n")
    cat("   -c, --conf            | scRNA-seq Analysis Conf \n")
    cat("   -h, --help            | Show help message\n")
    cat("   -v, --version         | Show script version\n")
    quit(status = 0)
  }
  # Custom help message
  if (!is.null(opt$help)) {
    cat("\033[1;34mThis is the scRNA-seq report merge script!\033[0m\n")
    cat("\033[1;32mUsage:scRNA_seq_report_merge -c scRNADir -t 10x  \033[0m\n")
    cat("   -s, --scRNADir        | Cellranger/DNBC4tools Result dir \n")
    cat("   -t, --scRNAtype       | scRNA-seq library (BGI | 10x) \n")
    cat("   -c, --conf            | scRNA-seq Analysis Conf \n")
    cat("   -h, --help            | Show help message\n")
    cat("   -v, --version         | Show script version\n")
    quit(status = 0)
  }
  
  # Version information
  if (!is.null(opt$version)) {
    cat("\033[1;34m scRNA_seq_report_merge : This is the scRNA-seq report merge script version: 1.1av\033[0m\n")
    quit(status = 0)
  }
  # Ensure mandatory parameters are provided
  if (is.null(opt$scRNADir) || is.null(opt$scRNAtype)|| is.null(opt$conf)) {
    cat("\033[1;31mError:\033[0m Missing Required parameters!\n")
    cat("Use '--help' for usage information.\n")
    quit(status = 1)
  }
  return(opt)
}
# function-1 merge data
merge_data <- function(folder_list,library,root_dir){
  i <- folder_list[1]
  if (library == "BGI"){
    temp_dir <- file.path(getwd(),i,"output","metrics_summary.xls")
    temp_data <- read.csv(temp_dir,sep = "\t")
  }else{
    temp_dir <- file.path(getwd(),paste0(i,"_Cellranger"),i,'outs',"metrics_summary.csv")
    temp_data <- read.csv(temp_dir)
  }
  temp_data_frame <-  as.data.frame(t(temp_data))
  colnames(temp_data_frame) <- sub(".*/", "", i)
  merge_data <- temp_data_frame
  folder_list <- folder_list[-1]
  for (i in folder_list){
    # i <- folder_list[1]
    if (library == "BGI"){
      temp_dir <- file.path(getwd(),i,"output","metrics_summary.xls")
      temp_data <- read.csv(temp_dir,sep = "\t")
    }else{
      temp_dir <- file.path(getwd(),paste0(i,"_Cellranger"),i,"outs","metrics_summary.csv")
      temp_data <- read.csv(temp_dir)
    }
    temp_data_frame <-  as.data.frame(t(temp_data))
    colnames(temp_data_frame) <- sub(".*/", "", i)
    merge_data <- cbind(merge_data,temp_data_frame)
  }
  rownames(merge_data) <- gsub("\\."," ",rownames(merge_data))
  if (library == "BGI"){
    print(data)
    write.csv(merge_data,file.path(root_dir,"DNBC4Tools_report_merge.csv"))
  }else{
    write.csv(merge_data,file.path(root_dir,"CellRanger_report_merge.csv"))
  }
  return(merge_data)
}
##----------------------------------------------------------------------------##
opt <- scRNAseqmultiSampleCommand()
root_dir <- opt$scRNADir 
library <- opt$scRNAtype
conf <- opt$conf
# PATH-4 run merge data
setwd(root_dir)
data <- read.csv(opt$conf)
folder_list <- data$sample
# merge data
data <- merge_data(folder_list,library,root_dir)
##----------------------------------------------------------------------------##