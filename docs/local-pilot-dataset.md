# 本地试点规模数据集（seed）

本地开发库长期只有十几名用户、1 名学生、0 条作答，导致：恢复演练只能验机制不能验业务、性能基线没有体量、前端多数页面在空列表上跑。本脚本造一套**贴近试点规模的最小真实数据**。

## 规模（默认参数）

| 维度 | 数量 |
|---|---|
| 学校 | 2（`seedpilot-01`、`seedpilot-02`，含新建的第二校） |
| 班级 | 每校 3 班，共 6 |
| 教师 | 每班 1 名 + 每校 1 名校级管理员 |
| 学生 | 每班 20 人，共 120 |
| 已发布练习 | 每班 1 次（`version_no=1`、`status=published`），共 6 |
| 今日会话 | 每生 1 条今天（`PRACTICE_TZ`）的 daily `PracticeSession`，共 120 |
| 作答 | 每生 4 条（跟读 / 复述 / 情景问答），共 480，全部挂到当日会话上 |
| 篇目 | 每校 12 篇 `[seed]` B1 篇目（共 24） |
| 复述句 | 每校 12 句（每篇一句，共 24） |
| 情景问法 | 每校 1 个主题 4 条问法（共 8） |
| 音频 | 每条作答一份真实 wav（0.5s 静音，落 `AUDIO_STORAGE_DIR` 根目录），共 480 份 ≈ 4 MB |

作答带 `status=done`、四维分数（68–95）、转写文本与建议，`created_at` 落在**今天 7:00–21:59**（跨日会让教师面板的今日提交数变 0）。

**内容必须按校建**：篇目/复述句/情景题都归属各自学校。建在默认校时，种子校学生提交作答会被 `content_access.require_same_tenant` 与 RLS 双重拦成 404（首次版本踩过这个坑，已修）。

**作答必须挂会话**：教师面板 `GET /api/v1/classes/{code}/board` 只取 `session_date == 今天` 的 daily 会话，按 `(student_id, practice_session.id)` 匹配作答，题位骨架来自 `classroom.current_exercise_id` 指向的发布快照。早期版本直接写 `attempt` 不建会话，结果是「库里有 480 条作答，教师面板显示已提交 0/20」。现在每班先造一次已发布 `ClassroomExercise`（1 篇目 + 1 复述 + 2 问答）并写回 `classroom.current_exercise_id`，再为每名学生造今日会话、把作答挂上去。

## 用法

脚本不进镜像（dev 容器没有源码挂载），所以用一次性挂载跑：

```bash
# 建默认规模
docker compose run --rm -T -v "$PWD/backend:/app/backend" backend \
  python scripts/seed_pilot_dataset.py

# 清掉上次 seed 再重建
docker compose run --rm -T -v "$PWD/backend:/app/backend" backend \
  python scripts/seed_pilot_dataset.py --reset

# 改规模
docker compose run --rm -T -v "$PWD/backend:/app/backend" backend \
  python scripts/seed_pilot_dataset.py --classes 4 --students 25 --attempts 5 --reset
```

## 账号

统一密码 `SeedPilot2026`（同时作为脚本默认值）：

- 校级管理员：`admin@seedpilot-01.seed`、`admin@seedpilot-02.seed`
- 教师：`t01@seedpilot-01.seed` … `t03@seedpilot-02.seed`
- 学生：学号 `s10001`…（`s` + 学校号 + 班号两位 + 序号两位，如 `s10001` = 1 校 1 班 1 号）；登录需带学校码 `?school=seedpilot-01`

## 纪律

- 只写 `seedpilot%` 前缀的租户与 `[seed]` 前缀篇目，**不碰默认演示校**；`--reset` 只清自己造的数据。
- 走 admin 连接写库（与 `initial_data.py` 同口径），归属租户由脚本显式指定。
- 幂等：学校已存在则跳过造校，内容按「本校缺失才补」处理；该校已有作答则跳过造作答。重复执行只会补齐缺失的部分。
- `--reset` 按租户清理，顺序为 `attempt` → `practice_session` → `classroom_exercise`（会话与发布快照都引用作答/课堂，倒序删才不撞外键）。删 `attempt` 行前先按 `audio_path` 删音频文件——`attempt` 是音频的唯一引用方，只删行会让每次重跑都留一批孤儿 wav（实测连跑几轮后卷里 7800+ 文件、63 MB，而库里只有 4000 条作答）。
- 库里已有但当天才产生的孤儿音频，由 `app/core/audio_retention.py` 的保留清理器在 24 小时竞态窗口后自动回收，脚本不越权删。

## 2026-11-17 首次建库实测

- 数据量：2 校 / 6 班 / 120 学生 / 480 作答 / 13 篇目；音频卷 484 文件、3.9 MB。
- 隔离：教师 `t01@seedpilot-01.seed` 登录后 `/classes` 只见 1 个自有班；`admin@seedpilot-01.seed` 见本校 3 班，看不到 `seedpilot-02` 的 3 班——RLS + owner 归属同时生效。
- 分租户计数：`seedpilot-01` 3 班 / 60 学生 / 240 作答，`seedpilot-02` 同量。
- **学生端链路实测**（`s10001` 登录 → 提交 → 轮询 → 结果）：跟读 / 复述 / 情景问答三类题均 `queued → done`，拿到分数与转写，`/attempts/{id}/comparison` 返回 1 条历史；作答音频 `GET /attempts/{id}/audio` 返回 200、`audio/wav`、8044 bytes。验证用的 3 条作答已删除，数据集回到 480 条。
- 注：`engine=mock` 的转写是固定样例句，分数不代表真实评分质量；本数据集用来验「链路与体量」，不是评分标定集。

## 2026-11-17 教师端按班看结果实测

发布 + 会话造完后的口径：2 校 / 6 班 / 120 学生 / **120 会话** / 480 作答。

- 接口 `GET /api/v1/classes/SD100X/board`（教师 token）：`submitted 20 / completed 20 / pending 0`，名单 20 人；样例学生「学生1-1」`done 4/4`、`round_status=all_done`，题位 `[passage:done, repeat:done, question:done, question:done]`。
- 六个班抽查（`SD100X`/`SD101X`/`SD200X`/`SD202X`）全部 `submitted 20 / completed 20`，`current_exercise` 均为「seed 今日练习」。
- 前端实测（教师 `t01@seedpilot-01.seed` → `/classrooms` → `/t/SD100X`）：页头显示「**已提交 20/20**」，学生结果 Tab「已完成 20 人」，名单行「4/4 + 分数 + 已提交」。截图：`/tmp/ui-teacher-board.png`。
- 学生端未受影响：`s10001` 的今日练习接口 `GET /classes/SD100X/today` 返回 200 且读出发布快照题位（1 passage + 1 repeat + 2 question）。

## 2026-11-17 千级体量实测

用来回答「这套栈在 1000+ 作答时会不会掉链子」。两组规模，都是 2 校 × 5 班，`--reset` 重建：

| 规模 | 学生 | 会话 | 作答 | 单班面板耗时 | 面板体积 |
|---|---|---|---|---|---|
| 60 人/班 | 600 | 600 | 2400 | 11–16 ms | 64 KB |
| 100 人/班 | 1000 | 1000 | 4000 | 13–16 ms | 107 KB |

单班 100 人时：接口 `submitted 100 / completed 100 / pending 0`；前端 `/t/SD100X` 整页加载 **1.1 s**，学生结果表 100 行全部渲染、无一截断（截图 `/tmp/ui-teacher-board-100.png`）。

同体量下其它读写端点（教师/学生 token，各 3 次）：

| 端点 | 耗时 | 返回 |
|---|---|---|
| `GET /classes/{code}/board` | 13–16 ms | 107 KB |
| `GET /classes/{code}/weak-spots` | 8 ms | 456 B |
| `GET /classes/{code}/trail?student_id=…` | 7 ms | 317 B |
| `GET /classes/{code}/learning-report?student_id=…` | 6 ms | 951 B |
| `GET /classes/{code}/today`（学生） | 9 ms | 4.2 KB |
| `GET /students/me/classrooms`（学生） | 6 ms | 275 B |

库与卷：`attempt=4000`、`practice_session=1001`、`student=1001`，`pg_database_size('app')` **19 MB**；音频卷 4000 份作答音频约 **16 MB**（不含内容音）。

**结论**：教师面板是「一次列表 + 按学生内存组装」（`_load_board_sessions` 一次拉今日会话、`_load_attempts_map` 一次拉全部作答），单班 100 人仍毫秒级，没有 N+1；前端 100 行一次渲染 1.1 s 可接受。局限：这是单机本地栈 + `engine=mock`，**不代表并发压测结果**——AC-08（公平调度/并发）仍暂缓，本次不覆盖。

**顺带修掉的问题**：`--reset` 只删库不删音频，连跑几轮后音频卷涨到 7800+ 文件 / 63 MB（库内只有 4000 条作答），已改为删 `attempt` 行前按 `audio_path` 删文件。
