import os
import pandas as pd
# 定义当前目录和搜索模式
current_dir = '/titan3/local_zhang_jian/scRNA-seq/UNIVERscRNAseq/10xRNAVDJ/cellranger7/03.seurat/s2754a82001/output/T/DEG'
file_pattern = "-DEG-infor.csv"
# Search for files matching the pattern in the current directory and subdirectories
csv_files = []
for root, dirs, files in os.walk(current_dir):
    for file in files:
        if file_pattern in file:
            csv_files.append(os.path.join(root, file))
# Check if any files were found
if not csv_files:
    print(f"No files with pattern '{file_pattern}' found.")
else:
    print(f"Found {len(csv_files)} files: {csv_files}")
    # Initialize an empty DataFrame for merging the results
    merged_df = pd.DataFrame()
    # Read and merge all files, adding filename as a new column
    for file in csv_files:
        df = pd.read_csv(file)
        # Extract filename without the .csv extension and remove '-infor'
        file_name_without_ext = os.path.splitext(os.path.basename(file))[0].replace('-infor', '') 
        # Add a column to store the modified filename
        df['filename'] = file_name_without_ext
        # Concatenate to the main DataFrame
        merged_df = pd.concat([merged_df, df], ignore_index=True)
    # Set 'filename' column as the index
    merged_df.set_index('filename', inplace=True)
    # Save the merged results to a new CSV file
    output_file = os.path.join(current_dir,"merged_DEG_infor_with_filenames.csv")
    merged_df.to_csv(output_file)
    print(f"All files have been merged into {output_file}.")