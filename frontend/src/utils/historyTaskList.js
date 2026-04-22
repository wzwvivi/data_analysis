/** 与独立任务 listTasks 的 page / page_size 入参一致 */
export const HISTORY_TASK_LIST_PAGE = 1
export const HISTORY_TASK_LIST_PAGE_SIZE = 50

/**
 * 历史列表接口按 created_at 升序返回时，本页第 index 行（0 起）的全局任务编号。
 * 最早创建的任务 = 1，同页中往下递增；翻页时与 offset 连续。
 */
export function chronologicalTaskNo(page, pageSize, index) {
  return (page - 1) * pageSize + index + 1
}
