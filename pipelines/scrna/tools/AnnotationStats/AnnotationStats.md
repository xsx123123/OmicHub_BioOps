*author* : zhang jian
*date* : 2025-1-13
*version* :1.0v
## Introduce
`AnnotationStats` 文件夹下的相关脚本是对注释后的seurat对象进行统计与可视化的工具。
### Scripts list
`AnnotationStats` 主要由一下工具：
- `Compositional_analysis` :文件夹下的脚本是可以对注释后不同组的细胞类型比例进行显著性统计的工具；
- `DrawCellTypePropDEGGene` : 文件夹下的脚本为对注释后不同组的细胞类型差异分析基因数量与细胞比例统计&可视化工具；
  - `DrawCellTypePropDEGGene` 函数分析 & 可视化如图搜索
    ![DrawCellTypePropDEGGene示例](./AnnotationStats/DrawCellTypePropDEGGene/ALL_cell.png)
### How to use
```R
# Compositional_analysis文件夹
CalculationRatefisherTest(seurat = seurat_object,
                          celltype = 'celltype',
                          group = 'group',
                          pair = c('Control','Treate'))
# Description : this is celltype prop status fisher test function
# @seurat   : analysis seurat object 
# @celltype : cell annotation result in meta.data
# @group    : group infor in meta.data
# @pair     : group pair infor
CalculationRateglmTest(seurat = seurat_object,
                       celltype = 'celltype',
                       group = 'group',
                       pair = c('Control','Treate'))  
# Description : this is celltype prop status fisher test function
# @seurat   : analysis seurat object 
# @celltype : cell annotation result in meta.data
# @group    : group infor in meta.data
# @pair     : group pair infor
Robustness_analysis(seurat,pair = c('Control', 'Treate'),
                    celltype = 'celltype_main',
                    group = 'group',
                    name = 'Robustness_analysis',
                    output_dir = "./")
# DrawCellTypePropDEGGene
# 创建样本配对信息list
group_list <- list('Group_1' = list(tread = "LC",
                                    control = "N"),
                   'Group_2' = list(tread = "LC",
                                    control = "C"),
                   'Group_3' = list(tread = "C",
                                    control = "N"))
# DrawCellTypePropDEGGene
DrawCellTypePropDEGGene(Seurat,group_list,
                        celltype = 'Celltype',
                        color_low = "#ffffff",
                        color_heigh = "#f6416c",
                        save_dir = './',
                        project_id = 'satas cell & deg infor')
```