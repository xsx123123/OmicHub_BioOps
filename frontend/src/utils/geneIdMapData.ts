/**
 * IdConverter 内置 mock 映射数据（人 / 小鼠）。
 *
 * - symbol 为真实常见基因名；ensembl / entrez / uniprot 仅为「风格正确」的演示 ID，
 *   不保证与真实数据库一一对应。
 * - 未来接入真实数据库（IndexedDB / 后端 API）时，只需替换本模块的数据来源，
 *   对外的 GeneMapEntry 结构保持不变。
 */

export interface SpeciesMockData {
  symbols: string[]
  ensemblPrefix: string
  entrezStart: number
}

/** 人常见基因 symbol（真实基因名）。 */
const HUMAN_SYMBOLS = [
  'TP53', 'BRCA1', 'BRCA2', 'EGFR', 'ACTB', 'GAPDH', 'MYC', 'KRAS', 'NRAS', 'HRAS',
  'AKT1', 'AKT2', 'AKT3', 'PTEN', 'PIK3CA', 'PIK3R1', 'RB1', 'CDKN1A', 'CDKN2A', 'CDKN2B',
  'MDM2', 'MDM4', 'BCL2', 'BAX', 'BAK1', 'BID', 'CASP3', 'CASP8', 'CASP9', 'APAF1',
  'CYCS', 'FAS', 'FADD', 'TNF', 'TNFRSF1A', 'IL6', 'IL1B', 'IL2', 'IL4', 'IL10',
  'IFNG', 'TGFB1', 'VEGFA', 'HIF1A', 'EP300', 'CREBBP', 'JUN', 'FOS', 'STAT3', 'STAT1',
  'STAT5A', 'STAT5B', 'JAK1', 'JAK2', 'SOCS3', 'NFKB1', 'RELA', 'IKBKB', 'MAPK1', 'MAPK3',
  'MAPK14', 'RAF1', 'BRAF', 'SOS1', 'GRB2', 'SHC1', 'PTK2', 'SRC', 'YES1', 'FYN',
  'LCK', 'ZAP70', 'CD4', 'CD8A', 'CD8B', 'CD19', 'MS4A1', 'TUBB', 'TUBA1A', 'LMNA',
  'VIM', 'DES', 'KRT19', 'KRT18', 'KRT5', 'EPCAM', 'CDH1', 'CDH2', 'SNAI1', 'SNAI2',
  'ZEB1', 'TWIST1', 'FN1', 'COL1A1', 'COL3A1', 'MMP2', 'MMP9', 'TIMP1', 'TIMP2', 'VWF',
  'PECAM1', 'KDR', 'FLT1', 'TEK', 'ANGPT1', 'ANGPT2', 'NOS3', 'EDN1', 'ACE', 'AGT',
  'REN', 'ALB', 'APOE', 'APOB', 'LDLR', 'PCSK9', 'HMGCR', 'INS', 'GCG', 'PPY',
  'SST', 'PAX6', 'PDX1', 'SLC2A1', 'SLC2A4', 'HK1', 'HK2', 'PFKL', 'PKM', 'LDHA',
  'LDHB', 'G6PD', 'PGAM1', 'ENO1', 'TPI1', 'ALDOA', 'FBP1', 'PCK1', 'PCK2', 'CPT1A',
  'ACACA', 'FASN', 'SCD', 'ELOVL6', 'PPARG', 'PPARA', 'PPARD', 'RXRA', 'NR1H3', 'NR1H2',
  'SREBF1', 'SREBF2', 'MTOR', 'RPTOR', 'RICTOR', 'TSC1', 'TSC2', 'RHEB', 'AKT1S1', 'DEPTOR',
  'ULK1', 'ATG5', 'ATG7', 'BECN1', 'MAP1LC3B', 'SQSTM1', 'LAMP1', 'TFEB', 'FOXO1', 'FOXO3',
  'SIRT1', 'SIRT3', 'SIRT6', 'PARP1', 'XRCC5', 'XRCC6', 'RAD51', 'ATM', 'ATR', 'CHEK1',
  'CHEK2', 'TP53BP1', 'H2AFX', 'PALB2', 'BARD1', 'MLH1', 'MSH2', 'MSH6', 'PMS2', 'ERCC1',
  'XPA', 'ERCC2', 'POLB', 'APEX1', 'MGMT', 'OGG1', 'NTH1', 'UNG', 'ESR1', 'ESR2',
  'AR', 'PGR', 'PRL', 'PRLR', 'GH1', 'GHR', 'IGF1', 'IGF1R', 'IGF2', 'IGF2R',
  'IRS1', 'IRS2', 'INSR', 'CYP19A1', 'CYP17A1', 'HSD3B1', 'STAR', 'CYP11A1', 'NR5A1', 'SOX9',
  'SRY', 'WT1', 'GATA4', 'TBX5', 'MEF2C', 'MYH7', 'MYH6', 'MYL2', 'MYL3', 'TNNT2',
  'TNNI3', 'TPM1', 'ACTC1', 'TTN', 'MYBPC3', 'SCN5A', 'KCNQ1', 'KCNH2', 'CACNA1C', 'RYR2',
  'ATP2A2', 'PLN', 'SLC8A1', 'GJA1', 'GJA5', 'NPPA', 'NPPB', 'MB', 'HBB', 'HBA1',
  'HBA2', 'F2', 'F5', 'F7', 'F8', 'F9', 'VWF', 'SERPINC1', 'PROC', 'PROS1',
]

/** 小鼠常见基因 symbol（真实小鼠命名规范：首字母大写）。 */
const MOUSE_SYMBOLS = [
  'Trp53', 'Brca1', 'Brca2', 'Egfr', 'Actb', 'Gapdh', 'Myc', 'Kras', 'Nras', 'Hras',
  'Akt1', 'Akt2', 'Akt3', 'Pten', 'Pik3ca', 'Pik3r1', 'Rb1', 'Cdkn1a', 'Cdkn2a', 'Cdkn2b',
  'Mdm2', 'Mdm4', 'Bcl2', 'Bax', 'Bak1', 'Bid', 'Casp3', 'Casp8', 'Casp9', 'Apaf1',
  'Cycs', 'Fas', 'Fadd', 'Tnf', 'Tnfrsf1a', 'Il6', 'Il1b', 'Il2', 'Il4', 'Il10',
  'Ifng', 'Tgfb1', 'Vegfa', 'Hif1a', 'Ep300', 'Crebbp', 'Jun', 'Fos', 'Stat3', 'Stat1',
  'Stat5a', 'Stat5b', 'Jak1', 'Jak2', 'Socs3', 'Nfkb1', 'Rela', 'Ikbkb', 'Mapk1', 'Mapk3',
  'Mapk14', 'Raf1', 'Braf', 'Sos1', 'Grb2', 'Shc1', 'Ptk2', 'Src', 'Yes1', 'Fyn',
  'Lck', 'Zap70', 'Cd4', 'Cd8a', 'Cd8b1', 'Cd19', 'Ms4a1', 'Tubb5', 'Tuba1a', 'Lmna',
  'Vim', 'Des', 'Krt19', 'Krt18', 'Krt5', 'Epcam', 'Cdh1', 'Cdh2', 'Snai1', 'Snai2',
  'Zeb1', 'Twist1', 'Fn1', 'Col1a1', 'Col3a1', 'Mmp2', 'Mmp9', 'Timp1', 'Timp2', 'Vwf',
  'Pecam1', 'Kdr', 'Flt1', 'Tek', 'Angpt1', 'Angpt2', 'Nos3', 'Edn1', 'Ace', 'Agt',
  'Ren1', 'Alb', 'Apoe', 'Apob', 'Ldlr', 'Pcsk9', 'Hmgcr', 'Ins1', 'Ins2', 'Gcg',
  'Ppy', 'Sst', 'Pax6', 'Pdx1', 'Slc2a1', 'Slc2a4', 'Hk1', 'Hk2', 'Pfkl', 'Pkm',
  'Ldha', 'Ldhb', 'G6pdx', 'Pgam1', 'Eno1', 'Tpi1', 'Aldoa', 'Fbp1', 'Pck1', 'Pck2',
  'Cpt1a', 'Acaca', 'Fasn', 'Scd1', 'Elovl6', 'Pparg', 'Ppara', 'Ppard', 'Rxra', 'Nr1h3',
  'Nr1h2', 'Srebf1', 'Srebf2', 'Mtor', 'Rptor', 'Rictor', 'Tsc1', 'Tsc2', 'Rheb', 'Akt1s1',
  'Deptor', 'Ulk1', 'Atg5', 'Atg7', 'Becn1', 'Map1lc3b', 'Sqstm1', 'Lamp1', 'Tfeb', 'Foxo1',
  'Foxo3', 'Sirt1', 'Sirt3', 'Sirt6', 'Parp1', 'Xrcc5', 'Xrcc6', 'Rad51', 'Atm', 'Atr',
  'Chek1', 'Chek2', 'Trp53bp1', 'H2afx', 'Palb2', 'Bard1', 'Mlh1', 'Msh2', 'Msh6', 'Pms2',
  'Ercc1', 'Xpa', 'Ercc2', 'Polb', 'Apex1', 'Mgmt', 'Ogg1', 'Nth1', 'Ung', 'Esr1',
  'Esr2', 'Ar', 'Pgr', 'Prl', 'Prlr', 'Gh1', 'Ghr', 'Igf1', 'Igf1r', 'Igf2',
  'Igf2r', 'Irs1', 'Irs2', 'Insr', 'Cyp19a1', 'Cyp17a1', 'Hsd3b1', 'Star', 'Cyp11a1', 'Nr5a1',
  'Sox9', 'Sry', 'Wt1', 'Gata4', 'Tbx5', 'Mef2c', 'Myh7', 'Myh6', 'Myl2', 'Myl3',
  'Tnnt2', 'Tnni3', 'Tpm1', 'Actc1', 'Ttn', 'Mybpc3', 'Scn5a', 'Kcnq1', 'Kcnh2', 'Cacna1c',
]

export const MOCK_SPECIES_DATA: Record<'human' | 'mouse', SpeciesMockData> = {
  human: { symbols: HUMAN_SYMBOLS, ensemblPrefix: 'ENSG', entrezStart: 1000 },
  mouse: { symbols: MOUSE_SYMBOLS, ensemblPrefix: 'ENSMUSG', entrezStart: 10000 },
}

/** UniProt 风格编号前缀池（真实风格的首字母）。 */
const UNIPROT_PREFIXES = ['P', 'Q', 'O', 'A', 'B']

/** 由 symbol 列表确定性生成 mock 映射条目。 */
export function buildMockEntries(species: 'human' | 'mouse') {
  const cfg = MOCK_SPECIES_DATA[species]
  return cfg.symbols.map((symbol, i) => ({
    symbol,
    ensembl: `${cfg.ensemblPrefix}${String(10000000000 + i * 37).slice(0, 11)}`,
    entrez: String(cfg.entrezStart + i * 7 + 1),
    uniprot: `${UNIPROT_PREFIXES[i % UNIPROT_PREFIXES.length]}${10000 + i * 13}`,
  }))
}
