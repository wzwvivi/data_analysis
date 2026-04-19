/** 与后端 PARSE_ELIGIBLE_ASSET_KEYS 对应：可用于解析/比对/事件分析的 PCAP 类平台文件 */

const PCAP_EXT = new Set(['pcapng', 'pcap', 'cap'])
const PARSE_ASSET_KEYS = new Set(['tsn_switch_1', 'tsn_switch_2', 'ground_network', 'fcc_recorder'])

export function fileExtensionLower(filename) {
  if (!filename || typeof filename !== 'string') return ''
  const i = filename.lastIndexOf('.')
  if (i < 0) return ''
  return filename.slice(i + 1).toLowerCase()
}

/** 是否可作为 TSN 解析、双机比对、事件分析等流程的数据源（平台共享文件） */
export function isParseCompatibleSharedItem(item) {
  if (!item) return false
  const ext = fileExtensionLower(item.original_filename)
  const okExt = PCAP_EXT.has(ext)
  const key = item.asset_type
  if (!key) return okExt
  return PARSE_ASSET_KEYS.has(key) && okExt
}

/** 双交换机比对：通常选两台交换机的抓包 */
export function isCompareSwitchSharedItem(item) {
  if (!isParseCompatibleSharedItem(item)) return false
  const key = item.asset_type
  if (!key) return true
  return key === 'tsn_switch_1' || key === 'tsn_switch_2'
}
