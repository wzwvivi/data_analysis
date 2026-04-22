/** 与独立任务 listTasks 的 page / page_size 入参一致 */
export const HISTORY_TASK_LIST_PAGE = 1
export const HISTORY_TASK_LIST_PAGE_SIZE = 50

/**
 * 列表按 created_at 降序（最新在上、最旧在下）时，本页第 index 行（0=本页最新）的全局任务编号。
 * 全局最早创建 = 1，越新数字越大；顶部一行编号最大。
 */
export function newestFirstTaskNo(total, page, pageSize, index) {
  if (total == null || total < 1) return null
  const n = total - (page - 1) * pageSize - index
  return n > 0 ? n : null
}
