// Shared date/label helpers, ported from web/static/index.html.

export const DAILY_TARGET_KCAL = 2500;

export const SOURCE_LABELS = { manual: '手动', immich: 'Immich', photoprism: 'PhotoPrism' };
export const CONF_LABELS = { high: '高', medium: '中', low: '低' };
export const CONF_TITLES = { high: '置信度：高', medium: '置信度：中', low: '置信度：低' };

export const API = '';

export function fmtDate(d) {
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

export function parseDate(s) {
  const [y, m, d] = s.split('-');
  return new Date(+y, +m - 1, +d);
}

// "2026年08月27日"（photo picker 等处使用）
export function displayDate(ds) {
  const d = parseDate(ds);
  const mm = String(d.getMonth() + 1).padStart(2, '0');
  const dd = String(d.getDate()).padStart(2, '0');
  return `${d.getFullYear()}年${mm}月${dd}日`;
}

const WEEKDAYS = ['日', '一', '二', '三', '四', '五', '六'];

// 顶栏 / 分隔线格式："8月27日" + "周三"
export function shortDate(ds) {
  const d = parseDate(ds);
  return `${d.getMonth() + 1}月${d.getDate()}日`;
}

export function weekdayLabel(ds) {
  return '周' + WEEKDAYS[parseDate(ds).getDay()];
}

export function hktNow() {
  const now = new Date();
  return new Date(now.toLocaleString('en-US', { timeZone: 'Asia/Hong_Kong' }));
}

export function mondayOf(d) {
  const m = new Date(d);
  m.setDate(d.getDate() - ((d.getDay() + 6) % 7));
  return m;
}

export function addDays(d, n) {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
}

export function fmtTimeHM(isoStr) {
  if (!isoStr) return '';
  return isoStr.slice(11, 16); // "HH:MM"
}

export function fmtPhotoTimeDetail(isoStr) {
  if (!isoStr) return '';
  const s = isoStr.replace('T', ' ');
  const base = s.slice(0, 16);
  const tzMatch = isoStr.match(/([+-]\d{2}:\d{2})$/);
  if (tzMatch) {
    return base + ' ' + tzMatch[1];
  }
  return base;
}

// 卡片 / lightbox 图片地址（与旧版 mealCard() 一致）
export function cardImageSrc(r) {
  if (r.replacement_image) {
    return `${API}/api/local-image?path=${encodeURIComponent(r.replacement_image)}`;
  }
  if (r.thumbnail_url) {
    return `${API}/api/image?url=${encodeURIComponent(r.thumbnail_url.replace('/original', '/thumbnail?size=thumbnail'))}`;
  }
  return '';
}

export function lightboxImageSrc(r) {
  if (r.replacement_image) {
    return `${API}/api/local-image?path=${encodeURIComponent(r.replacement_image)}`;
  }
  if (r.thumbnail_url) {
    return `${API}/api/image?url=${encodeURIComponent(r.thumbnail_url)}`;
  }
  return '';
}

export function sourceTypeOf(r) {
  return r.source_type || (r.asset_id && r.asset_id.startsWith('manual-') ? 'manual' : 'immich');
}
