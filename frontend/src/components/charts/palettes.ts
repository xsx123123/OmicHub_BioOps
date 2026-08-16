/** Shared color systems for OmicHub visualisation tools. */
export const DISCRETE_PALETTES = {
  Friendly: ['#0072B2', '#56B4E9', '#009E73', '#F5C710', '#E69F00', '#D55E00'],
  Seaside: ['#8ecae6', '#219ebc', '#023047', '#ffb703', '#fb8500'],
  Apple: ['#ff3b30', '#ff9500', '#ffcc00', '#4cd964', '#5ac8fa', '#007aff', '#5856d6'],
  IBM: ['#5B8DFE', '#725DEE', '#DD227D', '#FE5F00', '#FFB109'],
  Candy: ['#9b5de5', '#f15bb5', '#fee440', '#00bbf9', '#00f5d4'],
} as const

export const CONTINUOUS_PALETTES = {
  Viridis: ['#440154', '#3b528b', '#21918c', '#5ec962', '#fde725'],
  RdBu: ['#2166ac', '#67a9cf', '#d1e5f0', '#f7f7f7', '#fddbc7', '#ef8a62', '#b2182b'],
  Blues: ['#f7fbff', '#c6dbef', '#6baed6', '#2171b5', '#08306b'],
  Plasma: ['#0d0887', '#7e03a8', '#cc4778', '#f89540', '#f0f921'],
  BluePinkYellow: ['#00034D', '#000F9F', '#001CEF', '#241EF5', '#5823F6', '#A033E0', '#E85AB1', '#F1907C', '#F4AF63', '#FCE552', '#FFFB6D'],
} as const

/** Additional Explorer palettes remain centralised here for cross-tool consistency. */
export const EXPLORER_DISCRETE_PALETTES = {
  'Friendly Long': ['#CC79A7', '#0072B2', '#56B4E9', '#009E73', '#F5C710', '#E69F00', '#D55E00'],
  'Friendly Long 2': ['#fe65b3', '#CC79A7', '#ffd2d8', '#0072B2', '#007aff', '#56B4E9', '#009E73', '#4cd964', '#F5C710', '#E69F00', '#D55E00', '#ff3b30'],
  'Color 1': ['#ECA669', '#E06681', '#8087E2', '#E2D269'],
  Set2: ['#66c2a5', '#fc8d62', '#8da0cb', '#e78ac3', '#a6d854', '#ffd92f', '#e5c494', '#b3b3b3'],
  Set1: ['#e41a1c', '#377eb8', '#4daf4a', '#984ea3', '#ff7f00', '#ffff33', '#a65628', '#f781bf', '#999999'],
  Set3: ['#8dd3c7', '#ffffb3', '#bebada', '#fb8072', '#80b1d3', '#fdb462', '#b3de69', '#fccde5', '#d9d9d9'],
  Pastel1: ['#fbb4ae', '#b3cde3', '#ccebc5', '#decbe4', '#fed9a6', '#ffffcc', '#e5d8bd', '#fddaec', '#f2f2f2'],
  Dark24: ['#2ca02c', '#d62728', '#9467bd', '#8c564b', '#e377c2', '#7f7f7f', '#bcbd22', '#17becf', '#1f77b4', '#ff7f0e', '#33a02c', '#fb9a99', '#e31a1c', '#fdbf6f', '#ff7f00', '#cab2d6'],
} as const

export type DiscretePaletteName = keyof typeof DISCRETE_PALETTES
export type ContinuousPaletteName = keyof typeof CONTINUOUS_PALETTES

export function getDiscreteColors(name: DiscretePaletteName, count: number): string[] {
  const palette = DISCRETE_PALETTES[name]
  return Array.from({ length: Math.max(0, count) }, (_, index) => palette[index % palette.length])
}
