/** 一题的最新作答反馈（含重试次数；重试在练习模式随时可以） */
export interface AnswerState {
  isCorrect: boolean
  correctSpelling: string
  attemptNo: number
}

/** 测验进度点的提交态占位：只表示已提交，不携带对错 */
export const QUIZ_SUBMITTED_DOT: AnswerState = {
  isCorrect: false,
  correctSpelling: "",
  attemptNo: 1,
}
