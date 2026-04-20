// -*- coding: utf-8 -*-
// 通用的文件/字节数展示工具。历史上曾在这里实现 SHA-256 秒传指纹，
// 现在去重功能已下线，文件保留 formatBytes 方便多处复用。

/**
 * 人类可读的字节数。
 * @param {number} bytes
 */
export function formatBytes(bytes) {
  if (!Number.isFinite(bytes) || bytes < 0) return '-'
  const units = ['B', 'KB', 'MB', 'GB', 'TB']
  let value = bytes
  let idx = 0
  while (value >= 1024 && idx < units.length - 1) {
    value /= 1024
    idx += 1
  }
  return `${value.toFixed(value >= 10 || idx === 0 ? 0 : 1)} ${units[idx]}`
}
