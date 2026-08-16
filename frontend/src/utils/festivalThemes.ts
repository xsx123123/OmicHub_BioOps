/**
 * 节日主题配置 —— 每个节日独立的视觉、文案、动画、装饰
 *
 * 与后端返回的 FestivalConfig 通过节日名称（name）进行匹配。
 * 主题只负责前端展示层，额度逻辑仍由后端驱动。
 */

export type FestivalAnimationType =
  | 'lanterns'
  | 'dragon_boat'
  | 'milky_way'
  | 'moon_rise'
  | 'climbing'
  | 'gears'
  | 'hearts_rise'
  | 'snowfall'
  | 'sprout'
  | 'sun_pulse'
  | 'maple_fall'
  | 'snow_warm'
  | 'national_day'
  | 'code_rain'
  | 'nebula'

export type FestivalTexture =
  | 'silk'
  | 'paper'
  | 'mist'
  | 'lattice'
  | 'code'
  | 'frost'
  | 'grain'
  | 'bamboo'
  | 'brocade'
  | 'jade'
  | 'porcelain'
  | 'book'

export type FestivalForm =
  | 'tablet'
  | 'scroll'
  | 'moon'
  | 'ripple'
  | 'jade'
  | 'mountain'
  | 'banner'
  | 'petal'
  | 'frost'
  | 'terminal'
  | 'orbital'

export type FestivalLayout =
  | 'classic'
  | 'couplet'
  | 'moon-arc'
  | 'river'
  | 'vertical-rain'
  | 'mountain'
  | 'bridge'
  | 'field'
  | 'code'
  | 'star-map'

export type FestivalMotionProfile = 'gentle' | 'water' | 'botanical' | 'crystal' | 'astral' | 'firm'

export interface FestivalTheme {
  id: string
  name: string
  title: string
  emoji: string
  poem: string
  poemAuthor: string
  message: string
  gradient: string
  borderColor: string
  titleColor: string
  textColor: string
  amountColor: string
  amountGlow: string
  buttonGradient: string
  buttonTextColor: string
  buttonShadow: string
  taglineColor: string
  particleColors: string[]
  animationType: FestivalAnimationType
  decoration: string
  fontFamily?: string
  buttonText: string
  specialEffect?: string
  ambientColor?: string
  surfaceColor?: string
  highlightColor?: string
  texture?: FestivalTexture
  form?: FestivalForm
  layout?: FestivalLayout
  phenology?: string
  motionProfile?: FestivalMotionProfile
}

export const FESTIVAL_THEMES: FestivalTheme[] = [
  {
    id: 'spring_festival',
    name: '春节',
    title: '新春大吉',
    emoji: '🎊',
    poem: '爆竹声中一岁除，春风送暖入屠苏',
    poemAuthor: '王安石《元日》',
    message: '在这辞旧迎新的时刻，愿星光为你指引前路。OmicHub 送你 {amount} 额度，开启新一年的探索之旅！',
    gradient: 'linear-gradient(145deg, #1a0505 0%, #2d0a0a 40%, #1a0508 100%)',
    borderColor: 'rgba(255,215,0,0.45)',
    titleColor: '#FFD700',
    textColor: '#ffe4c4',
    amountColor: '#FFD700',
    amountGlow: '0 0 40px rgba(255,215,0,0.6), 0 0 80px rgba(255,215,0,0.2)',
    buttonGradient: 'linear-gradient(135deg, #c41e1e 0%, #e83030 100%)',
    buttonTextColor: '#FFD700',
    buttonShadow: '0 0 20px rgba(255,50,50,0.5)',
    taglineColor: '#d4a574',
    particleColors: ['#FFD700', '#FF6B35', '#FF4444', '#FFA500'],
    animationType: 'nebula',
    decoration: 'spring_couplets',
    buttonText: '领取新年红包 🧧',
  },
  {
    id: 'lantern_festival',
    name: '元宵节',
    title: '元宵喜乐',
    emoji: '🏮',
    poem: '众里寻他千百度，蓦然回首，那人却在，灯火阑珊处',
    poemAuthor: '辛弃疾《青玉案·元夕》',
    message: '花灯如昼，月圆人团圆。每一盏灯笼都是一颗坠落的星星，照亮我们短暂而美丽的旅程。送你 {amount} 额度！',
    gradient: 'linear-gradient(145deg, #1a1008 0%, #2d1f12 40%, #1a140a 100%)',
    borderColor: 'rgba(255,165,0,0.4)',
    titleColor: '#FFA500',
    textColor: '#ffe8d6',
    amountColor: '#FFB347',
    amountGlow: '0 0 40px rgba(255,165,0,0.5)',
    buttonGradient: 'linear-gradient(135deg, #e8780a 0%, #ff9f2e 100%)',
    buttonTextColor: '#fff',
    buttonShadow: '0 0 20px rgba(255,165,0,0.4)',
    taglineColor: '#d4a574',
    particleColors: ['#FFA500', '#FFD700', '#FF8C00', '#FFB347'],
    animationType: 'lanterns',
    decoration: 'lanterns',
    buttonText: '收下这份星光 ✨',
  },
  {
    id: 'dragon_boat',
    name: '端午节',
    title: '端午安康',
    emoji: '🐲',
    poem: '路漫漫其修远兮，吾将上下而求索',
    poemAuthor: '屈原《离骚》',
    message: '粽叶飘香，龙舟竞渡。我们如原子般短暂汇聚，又终将散入星河。送你 {amount} 额度，端午安康！',
    gradient: 'linear-gradient(145deg, #081a10 0%, #122d1f 40%, #0a1a12 100%)',
    borderColor: 'rgba(0,200,150,0.4)',
    titleColor: '#4ECDC4',
    textColor: '#d4f5e9',
    amountColor: '#4ECDC4',
    amountGlow: '0 0 40px rgba(78,205,196,0.5)',
    buttonGradient: 'linear-gradient(135deg, #0d8a6a 0%, #1aad8a 100%)',
    buttonTextColor: '#fff',
    buttonShadow: '0 0 20px rgba(0,200,150,0.4)',
    taglineColor: '#6ab09a',
    particleColors: ['#4ECDC4', '#44A08D', '#96E6A1', '#00C896'],
    animationType: 'dragon_boat',
    decoration: 'bamboo',
    buttonText: '领取 🎋',
  },
  {
    id: 'qixi',
    name: '七夕节',
    title: '七夕快乐',
    emoji: '💕',
    poem: '两情若是久长时，又岂在朝朝暮暮',
    poemAuthor: '秦观《鹊桥仙》',
    message: '在浩瀚宇宙中相遇，是千万分之一的奇迹。就像两颗原子在星云中偶然碰撞，绽放出独特的光芒。送你 {amount} 额度～',
    gradient: 'linear-gradient(145deg, #1a0820 0%, #2d1238 40%, #1a0a2a 100%)',
    borderColor: 'rgba(200,100,255,0.4)',
    titleColor: '#FF85C0',
    textColor: '#f0d4ff',
    amountColor: '#FF69B4',
    amountGlow: '0 0 40px rgba(255,105,180,0.5)',
    buttonGradient: 'linear-gradient(135deg, #b030b0 0%, #e050a0 100%)',
    buttonTextColor: '#fff',
    buttonShadow: '0 0 20px rgba(200,80,200,0.4)',
    taglineColor: '#c090d0',
    particleColors: ['#FF85C0', '#DA70D6', '#DDA0DD', '#FF69B4'],
    animationType: 'milky_way',
    decoration: 'stars_heart',
    buttonText: '领取星河礼物 💕',
  },
  {
    id: 'mid_autumn',
    name: '中秋节',
    title: '中秋团圆',
    emoji: '🌕',
    poem: '但愿人长久，千里共婵娟',
    poemAuthor: '苏轼《水调歌头》',
    message: '这一轮明月，不过是宇宙中一颗普通的卫星，却因为仰望它的人而被赋予了意义。送你 {amount} 额度！',
    gradient: 'linear-gradient(145deg, #080a1a 0%, #0a1025 40%, #060818 100%)',
    borderColor: 'rgba(200,200,255,0.35)',
    titleColor: '#E8DCC8',
    textColor: '#d0e0f8',
    amountColor: '#E8DCC8',
    amountGlow: '0 0 40px rgba(232,220,200,0.5), 0 0 80px rgba(150,180,255,0.15)',
    buttonGradient: 'linear-gradient(135deg, #3a5a8c 0%, #5a80b0 100%)',
    buttonTextColor: '#fff',
    buttonShadow: '0 0 20px rgba(100,150,255,0.3)',
    taglineColor: '#8aa0c0',
    particleColors: ['#E8DCC8', '#C0D6F5', '#B0C4DE', '#DDA0DD'],
    animationType: 'moon_rise',
    decoration: 'moon_rabbit',
    fontFamily: "'Noto Serif SC', 'STKaiti', 'KaiTi', serif",
    buttonText: '赏月领额度 🌙',
    specialEffect: 'moon_rising',
  },
  {
    id: 'double_ninth',
    name: '重阳节',
    title: '重阳登高',
    emoji: '🍂',
    poem: '遥知兄弟登高处，遍插茱萸少一人',
    poemAuthor: '王维《九月九日忆山东兄弟》',
    message: '登高望远，秋风送爽。我们来自星辰，终将回归星辰。送你 {amount} 额度！',
    gradient: 'linear-gradient(145deg, #1a1408 0%, #2d2512 40%, #1a160a 100%)',
    borderColor: 'rgba(218,165,32,0.35)',
    titleColor: '#DAA520',
    textColor: '#f5e6c8',
    amountColor: '#DAA520',
    amountGlow: '0 0 40px rgba(218,165,32,0.5)',
    buttonGradient: 'linear-gradient(135deg, #b8860b 0%, #daa520 100%)',
    buttonTextColor: '#1a1408',
    buttonShadow: '0 0 20px rgba(218,165,32,0.4)',
    taglineColor: '#c0a060',
    particleColors: ['#DAA520', '#CD853F', '#DEB887', '#F4A460'],
    animationType: 'climbing',
    decoration: 'chrysanthemum',
    buttonText: '登高领取',
  },
  {
    id: 'new_year',
    name: '元旦',
    title: '新年快乐',
    emoji: '🎉',
    poem: '新年都未有芳华，二月初惊见草芽',
    poemAuthor: '韩愈《春雪》',
    message: '新的一年，新的宇宙。每一个新的开始，都像是一次超新星爆发。OmicHub 送你 {amount} 额度，新年快乐！',
    gradient: 'linear-gradient(145deg, #050520 0%, #101040 40%, #080830 100%)',
    borderColor: 'rgba(100,150,255,0.5)',
    titleColor: '#ffffff',
    textColor: '#c8d8ff',
    amountColor: '#FFD700',
    amountGlow: '0 0 40px rgba(255,215,0,0.6)',
    buttonGradient: 'linear-gradient(135deg, #4a30d0 0%, #7a50ff 50%, #d040d0 100%)',
    buttonTextColor: '#fff',
    buttonShadow: '0 0 25px rgba(100,80,255,0.5)',
    taglineColor: '#8890ff',
    particleColors: ['#FFD700', '#FF6B6B', '#4ECDC4', '#A78BFA', '#FF85C0'],
    animationType: 'nebula',
    decoration: 'dawn_banner',
    buttonText: '开启新宇宙 🚀',
  },
  {
    id: 'labor_day',
    name: '劳动节',
    title: '劳动节快乐',
    emoji: '🛠️',
    poem: '锄禾日当午，汗滴禾下土。谁知盘中餐，粒粒皆辛苦',
    poemAuthor: '李绅《悯农》',
    message: '劳动最光荣！每一行代码、每一次实验，都是在为这个世界创造价值。送你 {amount} 额度！',
    gradient: 'linear-gradient(145deg, #0a0e1a 0%, #151a28 40%, #0a1020 100%)',
    borderColor: 'rgba(255,180,50,0.35)',
    titleColor: '#FFB732',
    textColor: '#d8e4f0',
    amountColor: '#FFB732',
    amountGlow: '0 0 40px rgba(255,183,50,0.5)',
    buttonGradient: 'linear-gradient(135deg, #d08000 0%, #ffa020 100%)',
    buttonTextColor: '#fff',
    buttonShadow: '0 0 20px rgba(255,160,0,0.4)',
    taglineColor: '#a0a8b8',
    particleColors: ['#FFB732', '#FFD700', '#FFA500'],
    animationType: 'gears',
    decoration: 'tools',
    buttonText: '领取',
  },
  {
    id: 'national_day',
    name: '国庆节',
    title: '国庆快乐',
    emoji: '🇨🇳',
    poem: '山河无恙，烟火寻常，这盛世如您所愿',
    poemAuthor: '——',
    message: '盛世华诞，举国同庆。送你 {amount} 额度，祝福祖国！',
    gradient: 'linear-gradient(145deg, #1a0505 0%, #2d0a0a 40%, #1a0508 100%)',
    borderColor: 'rgba(255,50,50,0.5)',
    titleColor: '#FF4444',
    textColor: '#ffd4d4',
    amountColor: '#FFD700',
    amountGlow: '0 0 40px rgba(255,215,0,0.6)',
    buttonGradient: 'linear-gradient(135deg, #cc0000 0%, #ff2222 100%)',
    buttonTextColor: '#FFD700',
    buttonShadow: '0 0 25px rgba(255,0,0,0.5)',
    taglineColor: '#d4a060',
    particleColors: ['#FF0000', '#FFD700', '#FF6B35', '#FF4444'],
    animationType: 'national_day',
    decoration: 'national_banner',
    buttonText: '庆祝 🎆',
  },
  {
    id: 'valentine',
    name: '情人节',
    title: '情人节快乐',
    emoji: '❤️',
    poem: '身无彩凤双飞翼，心有灵犀一点通',
    poemAuthor: '李商隐《无题》',
    message: '爱与被爱，都是幸福。就像两颗恒星在引力中相互环绕，永不分离。送你 {amount} 额度！',
    gradient: 'linear-gradient(145deg, #1a0810 0%, #2d1218 40%, #1a0a12 100%)',
    borderColor: 'rgba(255,80,120,0.4)',
    titleColor: '#FF6B9D',
    textColor: '#ffd0e0',
    amountColor: '#FF6B9D',
    amountGlow: '0 0 40px rgba(255,107,157,0.5)',
    buttonGradient: 'linear-gradient(135deg, #c44569 0%, #e86890 100%)',
    buttonTextColor: '#fff',
    buttonShadow: '0 0 20px rgba(255,80,120,0.4)',
    taglineColor: '#d080a0',
    particleColors: ['#FF6B9D', '#FF85C0', '#FFB6C1', '#FF69B4'],
    animationType: 'hearts_rise',
    decoration: 'hearts',
    buttonText: '领取 💝',
  },
  {
    id: 'christmas',
    name: '圣诞节',
    title: '圣诞快乐',
    emoji: '🎄',
    poem: 'Silent night, holy night, all is calm, all is bright',
    poemAuthor: '《Silent Night》',
    message: 'Merry Christmas！愿你的代码永远无 bug，愿你的实验永远有阳性结果！送你 {amount} 额度！',
    gradient: 'linear-gradient(145deg, #080a1a 0%, #0f1528 40%, #0a1020 100%)',
    borderColor: 'rgba(100,200,150,0.4)',
    titleColor: '#87CEEB',
    textColor: '#d0e8f0',
    amountColor: '#90EE90',
    amountGlow: '0 0 40px rgba(144,238,144,0.5)',
    buttonGradient: 'linear-gradient(135deg, #1a6b3a 0%, #2a9a5a 100%)',
    buttonTextColor: '#fff',
    buttonShadow: '0 0 20px rgba(50,150,80,0.4)',
    taglineColor: '#80b0a0',
    particleColors: ['#ffffff', '#87CEEB', '#90EE90', '#C0E8D0'],
    animationType: 'snowfall',
    decoration: 'christmas_tree',
    buttonText: 'Ho Ho Ho 🎁',
  },
  {
    id: 'li_chun',
    name: '立春',
    title: '立春',
    emoji: '🌱',
    poem: '东风带雨逐西风，大地阳和暖气生',
    poemAuthor: '左河水',
    message: '春回大地，万物复苏。那些沉睡的种子，终将在星光的滋养下破土而出。送你 {amount} 额度！',
    gradient: 'linear-gradient(145deg, #081a0a 0%, #0a1e0c 40%, #061808 100%)',
    borderColor: 'rgba(100,255,150,0.35)',
    titleColor: '#90EE90',
    textColor: '#d0f5d8',
    amountColor: '#90EE90',
    amountGlow: '0 0 40px rgba(144,238,144,0.5)',
    buttonGradient: 'linear-gradient(135deg, #2a8a3a 0%, #4aaa5a 100%)',
    buttonTextColor: '#fff',
    buttonShadow: '0 0 20px rgba(50,180,80,0.4)',
    taglineColor: '#70c080',
    particleColors: ['#90EE90', '#98FB98', '#FFB6C1', '#F0FFF0'],
    animationType: 'sprout',
    decoration: 'sprout',
    buttonText: '迎春 🌸',
  },
  {
    id: 'xia_zhi',
    name: '夏至',
    title: '夏至',
    emoji: '☀️',
    poem: '昼晷已云极，宵漏自此长',
    poemAuthor: '韦应物《夏至避暑北池》',
    message: '昼最长，夜最短。恒星也以最炽烈的姿态燃烧自己，照亮周遭的黑暗。送你 {amount} 额度！',
    gradient: 'linear-gradient(145deg, #1a1208 0%, #2d1f10 40%, #1a1608 100%)',
    borderColor: 'rgba(255,200,50,0.35)',
    titleColor: '#FFD700',
    textColor: '#f5e8c0',
    amountColor: '#FFD700',
    amountGlow: '0 0 40px rgba(255,215,0,0.5)',
    buttonGradient: 'linear-gradient(135deg, #e0a000 0%, #ffd030 100%)',
    buttonTextColor: '#1a1208',
    buttonShadow: '0 0 20px rgba(255,200,0,0.4)',
    taglineColor: '#d0b870',
    particleColors: ['#FFD700', '#FFA500', '#FF8C00', '#F0E68C'],
    animationType: 'sun_pulse',
    decoration: 'sun',
    buttonText: '领取',
  },
  {
    id: 'qiu_fen',
    name: '秋分',
    title: '秋分',
    emoji: '🍁',
    poem: '自古逢秋悲寂寥，我言秋日胜春朝',
    poemAuthor: '刘禹锡《秋词》',
    message: '昼夜均分，秋意渐浓。每一片落叶都是大自然写给我们的一封信。送你 {amount} 额度！',
    gradient: 'linear-gradient(145deg, #1a1008 0%, #1e140a 40%, #160e06 100%)',
    borderColor: 'rgba(210,130,50,0.35)',
    titleColor: '#D2691E',
    textColor: '#f5dcc8',
    amountColor: '#DAA520',
    amountGlow: '0 0 40px rgba(218,165,32,0.5)',
    buttonGradient: 'linear-gradient(135deg, #b8620a 0%, #d08020 100%)',
    buttonTextColor: '#fff',
    buttonShadow: '0 0 20px rgba(200,120,0,0.4)',
    taglineColor: '#c09860',
    particleColors: ['#D2691E', '#CD853F', '#DEB887', '#DAA520'],
    animationType: 'maple_fall',
    decoration: 'maple',
    buttonText: '拾叶领取 🍂',
  },
  {
    id: 'dong_zhi',
    name: '冬至',
    title: '冬至',
    emoji: '❄️',
    poem: '天时人事日相催，冬至阳生春又来',
    poemAuthor: '杜甫《小至》',
    message: '冬至大如年。在最长的黑夜里，愿 OmicHub 的一点点温暖能照亮你的路。送你 {amount} 额度！',
    gradient: 'linear-gradient(145deg, #0a0a1a 0%, #101028 40%, #080820 100%)',
    borderColor: 'rgba(180,200,255,0.35)',
    titleColor: '#E0E8FF',
    textColor: '#c8d4f0',
    amountColor: '#B0C4DE',
    amountGlow: '0 0 40px rgba(176,196,222,0.5)',
    buttonGradient: 'linear-gradient(135deg, #3a4a7a 0%, #5a70a0 100%)',
    buttonTextColor: '#fff',
    buttonShadow: '0 0 20px rgba(100,130,200,0.4)',
    taglineColor: '#8090b0',
    particleColors: ['#ffffff', '#C0D6F5', '#B0C4DE', '#E0E8FF'],
    animationType: 'snow_warm',
    decoration: 'snowflake',
    buttonText: '吃饺子领额度 🥟',
  },
  {
    id: 'programmers_day',
    name: '程序员节',
    title: '1024 程序员节',
    emoji: '💻',
    poem: 'Hello World!',
    poemAuthor: '每一个程序员的起点',
    message: '// 在这个特别的日子里\n// 愿你代码无bug，实验有结果\n// 愿你编译通过，论文accepted\n// OmicHub.send(amount: {amount})\n// → 领取成功 ✓',
    gradient: 'linear-gradient(145deg, #000000 0%, #0a0a0a 40%, #050505 100%)',
    borderColor: 'rgba(0,255,100,0.5)',
    titleColor: '#00FF66',
    textColor: '#00cc44',
    amountColor: '#00FF66',
    amountGlow: '0 0 40px rgba(0,255,100,0.6)',
    buttonGradient: 'linear-gradient(135deg, #000000 0%, #001a00 100%)',
    buttonTextColor: '#00FF66',
    buttonShadow: '0 0 20px rgba(0,255,100,0.4)',
    taglineColor: '#008830',
    particleColors: ['#00FF66', '#00CC44', '#00AA33'],
    animationType: 'code_rain',
    decoration: 'terminal',
    fontFamily: "'JetBrains Mono', 'Fira Code', 'Courier New', monospace",
    buttonText: 'console.log("领取")',
  },
  {
    id: 'anniversary',
    name: 'OmicHub 周年庆',
    title: 'OmicHub 一岁啦！',
    emoji: '🎂',
    poem: 'We are made of star-stuff',
    poemAuthor: 'Carl Sagan',
    message: '从第一行代码到今天，OmicHub 已经陪伴大家走过了一整年。感谢每一个深夜还在分析数据的你。送你 {amount} 额度！',
    gradient: 'linear-gradient(145deg, #0a0e27 0%, #1a1040 40%, #0e0a30 100%)',
    borderColor: 'rgba(167,139,250,0.5)',
    titleColor: '#A78BFA',
    textColor: '#d4c8ff',
    amountColor: '#A78BFA',
    amountGlow: '0 0 50px rgba(167,139,250,0.7)',
    buttonGradient: 'linear-gradient(135deg, #5b3ec0 0%, #8b5cf6 50%, #c084fc 100%)',
    buttonTextColor: '#fff',
    buttonShadow: '0 0 30px rgba(139,92,246,0.5)',
    taglineColor: '#9b8ad0',
    particleColors: ['#A78BFA', '#C084FC', '#818CF8', '#F472B6', '#FFD700'],
    animationType: 'nebula',
    decoration: 'galaxy',
    buttonText: '一起探索宇宙 🌌',
  },
]



const REFINED_THEME_OVERRIDES: Record<string, Partial<FestivalTheme>> = {
  spring_festival: {
    gradient: 'linear-gradient(145deg, rgba(31,18,20,0.94) 0%, rgba(54,28,28,0.88) 46%, rgba(24,16,18,0.94) 100%)',
    borderColor: 'rgba(216, 180, 106, 0.34)',
    titleColor: '#F2D6A2',
    textColor: '#F4E7D2',
    amountColor: '#E7C27E',
    amountGlow: '0 0 30px rgba(216,180,106,0.28), 0 0 70px rgba(151,77,68,0.16)',
    buttonGradient: 'linear-gradient(135deg, rgba(118,55,55,0.96), rgba(185,128,83,0.92))',
    buttonTextColor: '#FFF5DD',
    buttonShadow: '0 16px 42px rgba(72,25,24,0.32), inset 0 1px 0 rgba(255,255,255,0.18)',
    taglineColor: '#C8AF86',
    particleColors: ['#E7C27E', '#A8675D', '#F4E7D2'],
    ambientColor: '#D8B46A',
    surfaceColor: 'rgba(28,18,18,0.72)',
    highlightColor: '#F8E6BF',
    texture: 'paper',
    buttonText: '领取节日额度',
  },
  lantern_festival: {
    gradient: 'linear-gradient(145deg, rgba(32,24,22,0.94), rgba(58,37,30,0.86) 52%, rgba(24,18,18,0.94))',
    borderColor: 'rgba(205, 154, 95, 0.32)',
    titleColor: '#E3BE88',
    textColor: '#F0DDC8',
    amountColor: '#D8A767',
    amountGlow: '0 0 30px rgba(205,154,95,0.24)',
    buttonGradient: 'linear-gradient(135deg, rgba(101,65,50,0.96), rgba(195,139,84,0.9))',
    buttonTextColor: '#FFF1DD',
    buttonShadow: '0 15px 40px rgba(60,34,26,0.34), inset 0 1px 0 rgba(255,255,255,0.16)',
    taglineColor: '#BFA07C',
    particleColors: ['#E3BE88', '#A66F52', '#F2D8B8'],
    ambientColor: '#C9985A',
    surfaceColor: 'rgba(31,23,22,0.72)',
    highlightColor: '#FFE1AD',
    texture: 'silk',
    buttonText: '收下这束微光',
  },
  dragon_boat: {
    gradient: 'linear-gradient(145deg, rgba(14,28,24,0.95), rgba(27,49,41,0.86) 50%, rgba(11,24,23,0.95))',
    borderColor: 'rgba(132, 167, 139, 0.32)',
    titleColor: '#B9CDB5',
    textColor: '#DCE8D8',
    amountColor: '#A8C7A6',
    amountGlow: '0 0 30px rgba(132,167,139,0.24)',
    buttonGradient: 'linear-gradient(135deg, rgba(52,86,72,0.96), rgba(121,150,111,0.9))',
    buttonTextColor: '#F4FAEF',
    buttonShadow: '0 15px 40px rgba(17,47,38,0.34), inset 0 1px 0 rgba(255,255,255,0.16)',
    taglineColor: '#A3B59E',
    particleColors: ['#B9CDB5', '#78966F', '#DDE7D8'],
    ambientColor: '#84A78B',
    surfaceColor: 'rgba(15,29,25,0.72)',
    highlightColor: '#E7F0E3',
    texture: 'grain',
    buttonText: '领取节日额度',
  },
  qixi: {
    gradient: 'linear-gradient(145deg, rgba(24,20,34,0.95), rgba(43,34,58,0.88) 48%, rgba(21,18,32,0.95))',
    borderColor: 'rgba(191, 154, 180, 0.34)',
    titleColor: '#E1B8CC',
    textColor: '#E9D9E8',
    amountColor: '#D8A8C0',
    amountGlow: '0 0 34px rgba(191,154,180,0.28), 0 0 72px rgba(111,101,151,0.16)',
    buttonGradient: 'linear-gradient(135deg, rgba(89,72,119,0.96), rgba(184,132,160,0.9))',
    buttonTextColor: '#FFF2FA',
    buttonShadow: '0 15px 42px rgba(36,28,59,0.34), inset 0 1px 0 rgba(255,255,255,0.16)',
    taglineColor: '#C8ABC6',
    particleColors: ['#E1B8CC', '#8F82B0', '#F1E3EE'],
    ambientColor: '#B894B5',
    surfaceColor: 'rgba(25,21,35,0.74)',
    highlightColor: '#F4D9E8',
    texture: 'silk',
    buttonText: '领取星河微光',
  },
  mid_autumn: {
    gradient: 'linear-gradient(145deg, rgba(16,22,34,0.96), rgba(26,31,43,0.88) 52%, rgba(10,15,26,0.96))',
    borderColor: 'rgba(218, 208, 186, 0.32)',
    titleColor: '#E9E0CF',
    textColor: '#DDE4EC',
    amountColor: '#D9C8A8',
    amountGlow: '0 0 34px rgba(218,208,186,0.28), 0 0 76px rgba(114,139,171,0.16)',
    buttonGradient: 'linear-gradient(135deg, rgba(54,72,94,0.96), rgba(191,150,88,0.88))',
    buttonTextColor: '#FFF7E8',
    buttonShadow: '0 16px 42px rgba(13,21,35,0.38), inset 0 1px 0 rgba(255,255,255,0.16)',
    taglineColor: '#AEB9C8',
    particleColors: ['#E9E0CF', '#C99655', '#9DB4D0'],
    ambientColor: '#DAD0BA',
    surfaceColor: 'rgba(15,21,33,0.76)',
    highlightColor: '#FFF5DC',
    texture: 'frost',
    buttonText: '领取月光额度',
  },
  double_ninth: {
    gradient: 'linear-gradient(145deg, rgba(28,23,18,0.95), rgba(50,39,28,0.86) 50%, rgba(21,18,15,0.95))',
    borderColor: 'rgba(191, 146, 88, 0.30)',
    titleColor: '#D8B06F',
    textColor: '#E9D8BF',
    amountColor: '#D3A967',
    amountGlow: '0 0 28px rgba(191,146,88,0.24)',
    buttonGradient: 'linear-gradient(135deg, rgba(94,67,45,0.96), rgba(179,129,75,0.9))',
    buttonTextColor: '#FFF0DA',
    buttonShadow: '0 14px 38px rgba(55,37,24,0.34), inset 0 1px 0 rgba(255,255,255,0.15)',
    taglineColor: '#BCA27F',
    particleColors: ['#D8B06F', '#A87952', '#EADAC2'],
    ambientColor: '#BF9258',
    surfaceColor: 'rgba(28,23,18,0.72)',
    highlightColor: '#F0D6A7',
    texture: 'paper',
    buttonText: '登高领取',
  },
  new_year: {
    gradient: 'linear-gradient(145deg, rgba(15,20,38,0.96), rgba(27,35,62,0.88) 50%, rgba(11,15,30,0.96))',
    borderColor: 'rgba(154, 178, 217, 0.34)',
    titleColor: '#DCE6FF',
    textColor: '#D5DEEF',
    amountColor: '#CBD8F4',
    amountGlow: '0 0 32px rgba(154,178,217,0.28)',
    buttonGradient: 'linear-gradient(135deg, rgba(64,82,125,0.96), rgba(131,158,202,0.9))',
    buttonTextColor: '#F6F9FF',
    buttonShadow: '0 16px 42px rgba(17,25,52,0.38), inset 0 1px 0 rgba(255,255,255,0.16)',
    taglineColor: '#A9B7D5',
    particleColors: ['#DCE6FF', '#8FA8D6', '#D5C8F1'],
    ambientColor: '#9AB2D9',
    surfaceColor: 'rgba(15,20,38,0.74)',
    highlightColor: '#F3F7FF',
    texture: 'frost',
    buttonText: '开启新年额度',
  },
  labor_day: {
    gradient: 'linear-gradient(145deg, rgba(20,23,29,0.96), rgba(36,40,48,0.88) 50%, rgba(15,18,24,0.96))',
    borderColor: 'rgba(198, 159, 94, 0.28)',
    titleColor: '#D3B27A',
    textColor: '#DCE0E6',
    amountColor: '#D0A866',
    amountGlow: '0 0 28px rgba(198,159,94,0.23)',
    buttonGradient: 'linear-gradient(135deg, rgba(68,75,86,0.96), rgba(184,139,76,0.88))',
    buttonTextColor: '#FFF3DE',
    buttonShadow: '0 14px 38px rgba(20,22,28,0.36), inset 0 1px 0 rgba(255,255,255,0.16)',
    taglineColor: '#AEB4BE',
    particleColors: ['#D3B27A', '#8E98A8', '#E7E0D3'],
    ambientColor: '#C69F5E',
    surfaceColor: 'rgba(20,23,29,0.74)',
    highlightColor: '#E9D4A4',
    texture: 'lattice',
    buttonText: '领取劳动礼遇',
  },
  national_day: {
    gradient: 'linear-gradient(145deg, rgba(37,18,20,0.96), rgba(72,30,30,0.88) 48%, rgba(24,15,18,0.96))',
    borderColor: 'rgba(207, 174, 107, 0.34)',
    titleColor: '#E5C984',
    textColor: '#F0D9C9',
    amountColor: '#D9BB73',
    amountGlow: '0 0 32px rgba(207,174,107,0.26), 0 0 70px rgba(143,46,44,0.14)',
    buttonGradient: 'linear-gradient(135deg, rgba(112,43,43,0.96), rgba(199,151,89,0.9))',
    buttonTextColor: '#FFF3D9',
    buttonShadow: '0 16px 44px rgba(75,23,25,0.36), inset 0 1px 0 rgba(255,255,255,0.16)',
    taglineColor: '#C9AA78',
    particleColors: ['#E5C984', '#9B4E4A', '#F1DEB2'],
    ambientColor: '#CFAE6B',
    surfaceColor: 'rgba(36,18,20,0.74)',
    highlightColor: '#F3DCA3',
    texture: 'silk',
    buttonText: '领取节日额度',
  },
  valentine: {
    gradient: 'linear-gradient(145deg, rgba(32,22,28,0.96), rgba(58,39,50,0.86) 50%, rgba(22,17,24,0.96))',
    borderColor: 'rgba(201, 154, 174, 0.32)',
    titleColor: '#E2B9CA',
    textColor: '#EBD8E1',
    amountColor: '#D9A9BC',
    amountGlow: '0 0 30px rgba(201,154,174,0.25)',
    buttonGradient: 'linear-gradient(135deg, rgba(104,72,91,0.96), rgba(193,132,158,0.9))',
    buttonTextColor: '#FFF2F7',
    buttonShadow: '0 15px 40px rgba(48,30,40,0.35), inset 0 1px 0 rgba(255,255,255,0.16)',
    taglineColor: '#C7A7B5',
    particleColors: ['#E2B9CA', '#A88DA8', '#F1E2E8'],
    ambientColor: '#C99AAE',
    surfaceColor: 'rgba(32,22,28,0.72)',
    highlightColor: '#F5D7E3',
    texture: 'silk',
    buttonText: '领取心意额度',
  },
  christmas: {
    gradient: 'linear-gradient(145deg, rgba(14,24,28,0.96), rgba(26,43,44,0.88) 52%, rgba(12,20,25,0.96))',
    borderColor: 'rgba(151, 181, 172, 0.32)',
    titleColor: '#D7E4EA',
    textColor: '#D5E2E0',
    amountColor: '#BFD7CC',
    amountGlow: '0 0 30px rgba(151,181,172,0.25)',
    buttonGradient: 'linear-gradient(135deg, rgba(55,85,75,0.96), rgba(139,169,160,0.88))',
    buttonTextColor: '#F5FBFA',
    buttonShadow: '0 15px 40px rgba(12,29,30,0.36), inset 0 1px 0 rgba(255,255,255,0.16)',
    taglineColor: '#A6BDB8',
    particleColors: ['#D7E4EA', '#97B5AC', '#EEF4F4'],
    ambientColor: '#97B5AC',
    surfaceColor: 'rgba(14,24,28,0.74)',
    highlightColor: '#F4FBFD',
    texture: 'frost',
    buttonText: '领取冬日额度',
  },
  li_chun: {
    gradient: 'linear-gradient(145deg, rgba(17,29,23,0.96), rgba(31,49,39,0.86) 50%, rgba(13,24,20,0.96))',
    borderColor: 'rgba(152, 181, 144, 0.31)',
    titleColor: '#C8DDBF',
    textColor: '#DFEBDD',
    amountColor: '#BFD6B6',
    amountGlow: '0 0 28px rgba(152,181,144,0.24)',
    buttonGradient: 'linear-gradient(135deg, rgba(65,92,73,0.96), rgba(143,174,136,0.88))',
    buttonTextColor: '#F6FBF2',
    buttonShadow: '0 14px 38px rgba(18,44,30,0.33), inset 0 1px 0 rgba(255,255,255,0.15)',
    taglineColor: '#AAC0A5',
    particleColors: ['#C8DDBF', '#8FAE8F', '#E4EAD8'],
    ambientColor: '#98B590',
    surfaceColor: 'rgba(17,29,23,0.73)',
    highlightColor: '#EDF5E7',
    texture: 'grain',
    buttonText: '领取节气额度',
  },
  xia_zhi: {
    gradient: 'linear-gradient(145deg, rgba(33,27,18,0.96), rgba(58,47,29,0.86) 52%, rgba(23,20,15,0.96))',
    borderColor: 'rgba(214, 181, 109, 0.30)',
    titleColor: '#E8CF92',
    textColor: '#EDE0C0',
    amountColor: '#D9B66E',
    amountGlow: '0 0 30px rgba(214,181,109,0.24)',
    buttonGradient: 'linear-gradient(135deg, rgba(92,75,44,0.96), rgba(190,150,80,0.88))',
    buttonTextColor: '#FFF5DA',
    buttonShadow: '0 14px 38px rgba(45,34,20,0.34), inset 0 1px 0 rgba(255,255,255,0.15)',
    taglineColor: '#C4AA78',
    particleColors: ['#E8CF92', '#B88F52', '#F1E4C2'],
    ambientColor: '#D6B56D',
    surfaceColor: 'rgba(33,27,18,0.73)',
    highlightColor: '#F5DFAD',
    texture: 'silk',
    buttonText: '领取节气额度',
  },
  qiu_fen: {
    gradient: 'linear-gradient(145deg, rgba(33,24,19,0.96), rgba(58,39,29,0.86) 50%, rgba(22,18,15,0.96))',
    borderColor: 'rgba(199, 144, 94, 0.30)',
    titleColor: '#DDB284',
    textColor: '#EBD9C9',
    amountColor: '#D0A064',
    amountGlow: '0 0 28px rgba(199,144,94,0.23)',
    buttonGradient: 'linear-gradient(135deg, rgba(96,65,44,0.96), rgba(188,128,76,0.88))',
    buttonTextColor: '#FFF1E1',
    buttonShadow: '0 14px 38px rgba(48,31,22,0.34), inset 0 1px 0 rgba(255,255,255,0.15)',
    taglineColor: '#C0A082',
    particleColors: ['#DDB284', '#A87252', '#EBD6BE'],
    ambientColor: '#C7905E',
    surfaceColor: 'rgba(33,24,19,0.73)',
    highlightColor: '#F0D0A8',
    texture: 'paper',
    buttonText: '领取节气额度',
  },
  dong_zhi: {
    gradient: 'linear-gradient(145deg, rgba(16,22,32,0.96), rgba(30,38,52,0.88) 52%, rgba(12,17,28,0.96))',
    borderColor: 'rgba(174, 187, 209, 0.31)',
    titleColor: '#DCE5F3',
    textColor: '#D5DEEA',
    amountColor: '#BFCBE0',
    amountGlow: '0 0 30px rgba(174,187,209,0.25)',
    buttonGradient: 'linear-gradient(135deg, rgba(58,72,98,0.96), rgba(143,160,188,0.88))',
    buttonTextColor: '#F7FAFF',
    buttonShadow: '0 15px 40px rgba(12,19,32,0.36), inset 0 1px 0 rgba(255,255,255,0.16)',
    taglineColor: '#A9B5C8',
    particleColors: ['#DCE5F3', '#AEBBD1', '#EEF3FA'],
    ambientColor: '#AEBBD1',
    surfaceColor: 'rgba(16,22,32,0.74)',
    highlightColor: '#F4F8FF',
    texture: 'frost',
    buttonText: '领取节气额度',
  },
  programmers_day: {
    gradient: 'linear-gradient(145deg, rgba(9,14,14,0.96), rgba(14,28,24,0.88) 52%, rgba(6,10,11,0.96))',
    borderColor: 'rgba(112, 198, 166, 0.32)',
    titleColor: '#A8E4CE',
    textColor: '#C8DDD6',
    amountColor: '#92D7BF',
    amountGlow: '0 0 28px rgba(112,198,166,0.26)',
    buttonGradient: 'linear-gradient(135deg, rgba(30,60,52,0.96), rgba(83,150,124,0.88))',
    buttonTextColor: '#ECFFF8',
    buttonShadow: '0 15px 40px rgba(4,18,16,0.38), inset 0 1px 0 rgba(255,255,255,0.14)',
    taglineColor: '#82B6A2',
    particleColors: ['#A8E4CE', '#70C6A6', '#D9F2EA'],
    ambientColor: '#70C6A6',
    surfaceColor: 'rgba(9,14,14,0.76)',
    highlightColor: '#D7FFF1',
    texture: 'code',
    buttonText: 'Run claim()',
  },
  anniversary: {
    gradient: 'linear-gradient(145deg, rgba(18,22,42,0.96), rgba(36,31,62,0.88) 50%, rgba(13,16,32,0.96))',
    borderColor: 'rgba(175, 162, 212, 0.34)',
    titleColor: '#D7CCF1',
    textColor: '#DDE0F4',
    amountColor: '#C8B9E8',
    amountGlow: '0 0 34px rgba(175,162,212,0.28)',
    buttonGradient: 'linear-gradient(135deg, rgba(77,72,126,0.96), rgba(159,143,202,0.9))',
    buttonTextColor: '#F8F5FF',
    buttonShadow: '0 16px 44px rgba(18,20,52,0.38), inset 0 1px 0 rgba(255,255,255,0.16)',
    taglineColor: '#B4AED0',
    particleColors: ['#D7CCF1', '#AFA2D4', '#DCE6FF'],
    ambientColor: '#AFA2D4',
    surfaceColor: 'rgba(18,22,42,0.74)',
    highlightColor: '#EFE9FF',
    texture: 'frost',
    buttonText: '领取周年礼遇',
  },
}

const SOLAR_TERM_REFINEMENTS: Record<string, Partial<FestivalTheme>> = {
  立春: { ambientColor: '#A7BE9E', titleColor: '#D6E7CE', borderColor: 'rgba(167,190,158,0.32)', particleColors: ['#D6E7CE', '#A7BE9E', '#EDF5E8'], texture: 'grain' },
  雨水: { ambientColor: '#93AFC2', titleColor: '#D5E6EC', borderColor: 'rgba(147,175,194,0.32)', particleColors: ['#D5E6EC', '#93AFC2', '#E8F0F2'], texture: 'mist' },
  惊蛰: { ambientColor: '#A3B88A', titleColor: '#D7E4BE', borderColor: 'rgba(163,184,138,0.32)', particleColors: ['#D7E4BE', '#A3B88A', '#EAF0DB'], texture: 'lattice' },
  春分: { ambientColor: '#B2BE9C', titleColor: '#DFE7CD', borderColor: 'rgba(178,190,156,0.32)', particleColors: ['#DFE7CD', '#B2BE9C', '#F1F4E7'], texture: 'silk' },
  清明: { ambientColor: '#9FB7B0', titleColor: '#D7E5DF', borderColor: 'rgba(159,183,176,0.32)', particleColors: ['#D7E5DF', '#9FB7B0', '#EDF2EF'], texture: 'mist' },
  谷雨: { ambientColor: '#9BB68A', titleColor: '#DCE9CF', borderColor: 'rgba(155,182,138,0.32)', particleColors: ['#DCE9CF', '#9BB68A', '#EDF4E7'], texture: 'grain' },
  立夏: { ambientColor: '#CDB676', titleColor: '#E9D79A', borderColor: 'rgba(205,182,118,0.31)', particleColors: ['#E9D79A', '#CDB676', '#F3E7C6'], texture: 'silk' },
  小满: { ambientColor: '#B9B77D', titleColor: '#E0DEAA', borderColor: 'rgba(185,183,125,0.31)', particleColors: ['#E0DEAA', '#B9B77D', '#F0EED1'], texture: 'grain' },
  芒种: { ambientColor: '#C4A669', titleColor: '#E8D095', borderColor: 'rgba(196,166,105,0.31)', particleColors: ['#E8D095', '#C4A669', '#F2E1B8'], texture: 'paper' },
  夏至: { ambientColor: '#D0B06F', titleColor: '#EFD59A', borderColor: 'rgba(208,176,111,0.32)', particleColors: ['#EFD59A', '#D0B06F', '#F6E8C0'], texture: 'silk' },
  小暑: { ambientColor: '#C99C68', titleColor: '#E8C595', borderColor: 'rgba(201,156,104,0.31)', particleColors: ['#E8C595', '#C99C68', '#F4DFC2'], texture: 'mist' },
  大暑: { ambientColor: '#C28A63', titleColor: '#E7B88D', borderColor: 'rgba(194,138,99,0.31)', particleColors: ['#E7B88D', '#C28A63', '#F0D1B9'], texture: 'grain' },
  立秋: { ambientColor: '#C59A70', titleColor: '#E5C09A', borderColor: 'rgba(197,154,112,0.31)', particleColors: ['#E5C09A', '#C59A70', '#F1D9BF'], texture: 'paper' },
  处暑: { ambientColor: '#B98F73', titleColor: '#E0BDA4', borderColor: 'rgba(185,143,115,0.31)', particleColors: ['#E0BDA4', '#B98F73', '#EDD6C7'], texture: 'silk' },
  白露: { ambientColor: '#B8A890', titleColor: '#E3D8C6', borderColor: 'rgba(184,168,144,0.31)', particleColors: ['#E3D8C6', '#B8A890', '#F1EBE0'], texture: 'frost' },
  秋分: { ambientColor: '#C7905E', titleColor: '#DDB284', borderColor: 'rgba(199,144,94,0.31)', particleColors: ['#DDB284', '#C7905E', '#EBD6BE'], texture: 'paper' },
  寒露: { ambientColor: '#A88772', titleColor: '#D7B8A4', borderColor: 'rgba(168,135,114,0.31)', particleColors: ['#D7B8A4', '#A88772', '#E9D6CB'], texture: 'mist' },
  霜降: { ambientColor: '#B28368', titleColor: '#D8AA87', borderColor: 'rgba(178,131,104,0.31)', particleColors: ['#D8AA87', '#B28368', '#E8CCBA'], texture: 'frost' },
  立冬: { ambientColor: '#9CAAC0', titleColor: '#D6DFEC', borderColor: 'rgba(156,170,192,0.31)', particleColors: ['#D6DFEC', '#9CAAC0', '#EEF2F7'], texture: 'frost' },
  小雪: { ambientColor: '#A8B7C8', titleColor: '#DCE7F0', borderColor: 'rgba(168,183,200,0.31)', particleColors: ['#DCE7F0', '#A8B7C8', '#F1F5F8'], texture: 'mist' },
  大雪: { ambientColor: '#B7C2D1', titleColor: '#E3EAF2', borderColor: 'rgba(183,194,209,0.31)', particleColors: ['#E3EAF2', '#B7C2D1', '#F6F8FB'], texture: 'frost' },
  冬至: { ambientColor: '#AEBBD1', titleColor: '#DCE5F3', borderColor: 'rgba(174,187,209,0.31)', particleColors: ['#DCE5F3', '#AEBBD1', '#EEF3FA'], texture: 'frost' },
  小寒: { ambientColor: '#9CAEC7', titleColor: '#D6E2F0', borderColor: 'rgba(156,174,199,0.31)', particleColors: ['#D6E2F0', '#9CAEC7', '#EDF3F9'], texture: 'frost' },
  大寒: { ambientColor: '#8FA3BD', titleColor: '#D1DEED', borderColor: 'rgba(143,163,189,0.31)', particleColors: ['#D1DEED', '#8FA3BD', '#EAF1F8'], texture: 'frost' },
}


const FESTIVAL_FORM_REFINEMENTS: Record<string, Partial<FestivalTheme>> = {
  spring_festival: { form: 'scroll', layout: 'couplet', phenology: 'spring-scroll', motionProfile: 'firm', texture: 'brocade' },
  lantern_festival: { form: 'ripple', layout: 'moon-arc', phenology: 'lantern-orbit', motionProfile: 'water', texture: 'silk' },
  dragon_boat: { form: 'jade', layout: 'river', phenology: 'reed-river', motionProfile: 'water', texture: 'bamboo' },
  qixi: { form: 'petal', layout: 'bridge', phenology: 'star-bridge', motionProfile: 'astral', texture: 'silk' },
  mid_autumn: { form: 'moon', layout: 'moon-arc', phenology: 'moon-tide', motionProfile: 'astral', texture: 'porcelain' },
  double_ninth: { form: 'mountain', layout: 'mountain', phenology: 'chrysanthemum-slope', motionProfile: 'gentle', texture: 'book' },
  new_year: { form: 'tablet', layout: 'classic', phenology: 'dawn-ring', motionProfile: 'astral', texture: 'frost' },
  labor_day: { form: 'tablet', layout: 'field', phenology: 'grain-grid', motionProfile: 'firm', texture: 'lattice' },
  national_day: { form: 'banner', layout: 'mountain', phenology: 'mountain-dawn', motionProfile: 'firm', texture: 'brocade' },
  valentine: { form: 'petal', layout: 'bridge', phenology: 'silk-knot', motionProfile: 'gentle', texture: 'silk' },
  christmas: { form: 'frost', layout: 'classic', phenology: 'winter-window', motionProfile: 'crystal', texture: 'frost' },
  li_chun: { form: 'jade', layout: 'field', phenology: 'spring-sprout', motionProfile: 'botanical', texture: 'grain' },
  xia_zhi: { form: 'ripple', layout: 'field', phenology: 'solar-arc', motionProfile: 'water', texture: 'silk' },
  qiu_fen: { form: 'mountain', layout: 'mountain', phenology: 'autumn-balance', motionProfile: 'gentle', texture: 'paper' },
  dong_zhi: { form: 'frost', layout: 'moon-arc', phenology: 'yang-return', motionProfile: 'crystal', texture: 'frost' },
  programmers_day: { form: 'terminal', layout: 'code', phenology: 'code-lattice', motionProfile: 'firm', texture: 'code' },
  anniversary: { form: 'orbital', layout: 'star-map', phenology: 'nebula-orbit', motionProfile: 'astral', texture: 'frost' },
}

const SOLAR_TERM_FORM_REFINEMENTS: Record<string, Partial<FestivalTheme>> = {
  立春: { form: 'jade', layout: 'field', phenology: 'spring-sprout', motionProfile: 'botanical', texture: 'grain' },
  雨水: { form: 'ripple', layout: 'river', phenology: 'rain-ripple', motionProfile: 'water', texture: 'mist' },
  惊蛰: { form: 'tablet', layout: 'field', phenology: 'thunder-crack', motionProfile: 'firm', texture: 'lattice' },
  春分: { form: 'scroll', layout: 'couplet', phenology: 'equinox-balance', motionProfile: 'gentle', texture: 'silk' },
  清明: { form: 'ripple', layout: 'vertical-rain', phenology: 'clear-rain', motionProfile: 'water', texture: 'paper' },
  谷雨: { form: 'jade', layout: 'river', phenology: 'rice-rain', motionProfile: 'water', texture: 'grain' },
  立夏: { form: 'ripple', layout: 'field', phenology: 'tomato-vine', motionProfile: 'botanical', texture: 'silk' },
  小满: { form: 'tablet', layout: 'field', phenology: 'rice-wheat-fill', motionProfile: 'botanical', texture: 'grain' },
  芒种: { form: 'scroll', layout: 'field', phenology: 'wheat-awn-seed', motionProfile: 'botanical', texture: 'paper' },
  夏至: { form: 'moon', layout: 'moon-arc', phenology: 'solar-arc', motionProfile: 'astral', texture: 'silk' },
  小暑: { form: 'ripple', layout: 'river', phenology: 'heat-haze', motionProfile: 'water', texture: 'mist' },
  大暑: { form: 'ripple', layout: 'field', phenology: 'lotus-heat', motionProfile: 'water', texture: 'grain' },
  立秋: { form: 'mountain', layout: 'mountain', phenology: 'autumn-leaf', motionProfile: 'gentle', texture: 'book' },
  处暑: { form: 'scroll', layout: 'classic', phenology: 'cooling-cloud', motionProfile: 'gentle', texture: 'silk' },
  白露: { form: 'frost', layout: 'classic', phenology: 'dew-beads', motionProfile: 'crystal', texture: 'porcelain' },
  秋分: { form: 'mountain', layout: 'mountain', phenology: 'autumn-balance', motionProfile: 'gentle', texture: 'paper' },
  寒露: { form: 'frost', layout: 'vertical-rain', phenology: 'cold-dew', motionProfile: 'crystal', texture: 'mist' },
  霜降: { form: 'frost', layout: 'classic', phenology: 'frost-vein', motionProfile: 'crystal', texture: 'frost' },
  立冬: { form: 'frost', layout: 'classic', phenology: 'winter-mist', motionProfile: 'crystal', texture: 'frost' },
  小雪: { form: 'frost', layout: 'vertical-rain', phenology: 'snow-mist', motionProfile: 'crystal', texture: 'mist' },
  大雪: { form: 'frost', layout: 'classic', phenology: 'snow-field', motionProfile: 'crystal', texture: 'frost' },
  冬至: { form: 'moon', layout: 'moon-arc', phenology: 'yang-return', motionProfile: 'crystal', texture: 'porcelain' },
  小寒: { form: 'frost', layout: 'mountain', phenology: 'cold-ridge', motionProfile: 'crystal', texture: 'frost' },
  大寒: { form: 'frost', layout: 'mountain', phenology: 'ice-ring', motionProfile: 'crystal', texture: 'frost' },
}

function withThemeRefinement(theme: FestivalTheme, festivalName?: string): FestivalTheme {
  const baseOverride = REFINED_THEME_OVERRIDES[theme.id] ?? {}
  const formOverride = FESTIVAL_FORM_REFINEMENTS[theme.id] ?? {}
  const solarTermOverride = festivalName ? SOLAR_TERM_REFINEMENTS[festivalName] ?? {} : {}
  const solarTermFormOverride = festivalName ? SOLAR_TERM_FORM_REFINEMENTS[festivalName] ?? {} : {}
  return {
    ...theme,
    ...baseOverride,
    ...formOverride,
    ...solarTermOverride,
    ...solarTermFormOverride,
  }
}

const SOLAR_TERM_THEME_BY_NAME: Record<string, string> = {
  雨水: 'li_chun',
  惊蛰: 'li_chun',
  春分: 'li_chun',
  清明: 'li_chun',
  谷雨: 'li_chun',
  立夏: 'xia_zhi',
  小满: 'xia_zhi',
  芒种: 'xia_zhi',
  小暑: 'xia_zhi',
  大暑: 'xia_zhi',
  立秋: 'qiu_fen',
  处暑: 'qiu_fen',
  白露: 'qiu_fen',
  寒露: 'qiu_fen',
  霜降: 'qiu_fen',
  立冬: 'dong_zhi',
  小雪: 'dong_zhi',
  大雪: 'dong_zhi',
  小寒: 'dong_zhi',
  大寒: 'dong_zhi',
}

function findFestivalThemeById(id: string, festivalName?: string): FestivalTheme | undefined {
  const theme = FESTIVAL_THEMES.find((t) => t.id === id)
  return theme ? withThemeRefinement(theme, festivalName) : undefined
}
/**
 * 根据节日名称查找主题。
 * 匹配逻辑：后端返回的节日 name 包含主题 name（例如"春节"匹配"春节"）。
 * 24 节气按四季复用结构，但通过 SOLAR_TERM_REFINEMENTS 注入独立色盘与肌理。
 */
export function findFestivalTheme(name: string): FestivalTheme | undefined {
  const exactTheme = FESTIVAL_THEMES.find((t) => name.includes(t.name))
  if (exactTheme) return withThemeRefinement(exactTheme, name)

  const solarTermThemeId = SOLAR_TERM_THEME_BY_NAME[name]
  if (solarTermThemeId) return findFestivalThemeById(solarTermThemeId, name)

  return undefined
}

/**
 * 获取默认主题，兜底使用春节。
 */
export function getDefaultTheme(): FestivalTheme {
  return withThemeRefinement(FESTIVAL_THEMES[0], FESTIVAL_THEMES[0].name)
}

/**
 * 安全获取主题：优先按名称匹配，否则返回默认主题。
 */
export function resolveFestivalTheme(name?: string | null): FestivalTheme {
  if (!name) return getDefaultTheme()
  return findFestivalTheme(name) ?? getDefaultTheme()
}
