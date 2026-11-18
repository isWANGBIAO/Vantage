import { createContext } from 'react';

export const CHINESE_FONT_FAMILIES = {
  'microsoft-yahei': '"Microsoft YaHei", "微软雅黑"',
  'noto-sans-sc': '"Noto Sans SC"',
  'microsoft-jhenghei': '"Microsoft JhengHei", "微軟正黑體"',
  'pingfang-sc': '"PingFang SC"',
};

export function getFontFamilies(value = 'microsoft-yahei') {
  const selected = Object.hasOwn(CHINESE_FONT_FAMILIES, value) ? CHINESE_FONT_FAMILIES[value] : CHINESE_FONT_FAMILIES['microsoft-yahei'];
  const chinese = `${selected}, "Microsoft YaHei", "微软雅黑", "PingFang SC"`;
  return { main: `Inter, "Segoe UI", ${chinese}, system-ui, -apple-system, sans-serif`,
    mono: `Consolas, ${chinese}, ui-monospace, monospace` };
}

export const FontFamilyContext = createContext(getFontFamilies());

export function withChartFont(option, fontFamily) {
  if (!option) return option;
  const tooltip = (item) => ({ ...item, textStyle: { ...item?.textStyle, fontFamily } });
  return { ...option, textStyle: { ...option.textStyle, fontFamily },
    ...(option.tooltip ? { tooltip: Array.isArray(option.tooltip) ? option.tooltip.map(tooltip) : tooltip(option.tooltip) } : {}) };
}
