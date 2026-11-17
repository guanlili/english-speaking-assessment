# 本地试点规模数据集（seed）

本地开发库长期只有十几名用户、1 名学生、0 条作答，导致：恢复演练只能验机制不能验业务、性能基线没有体量、前端多数页面在空列表上跑。本脚本造一套**贴近试点规模的最小真实数据**。

## 规模（默认参数）

| 维度 | 数量 |
|---|---|
| 学校 | 2（`seedpilot-01`、`seedpilot-02`，含新建的第二校） |
| 班级 | 每校 3 班，共 6 |
| 教师 | 每班 1 名 + 每校 1 名校级管理员 |
| 学生 | 每班 20 人，共 120 |
| 作答 | 每生 4 条（跟读 / 复述 / 情景问答），共 480 |
| 篇目 | 12 篇 `[seed]` 前缀的 B1 篇目（另复用默认校 1 篇） |
| 音频 | 每条作答一份真实 wav（0.5s 静音，落 `AUDIO_STORAGE_DIR` 根目录），共 480 份 ≈ 4 MB |

作答带 `status=done`、四维分数（68–95）、转写文本与建议，分布在最近 20 天，可直接用于趋势/仪表盘/导出类验证。

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
- 学生：学号 `s0101`…`s0203xx`（`s` + 学校号 + 班号 + 序号）

## 纪律

- 只写 `seedpilot%` 前缀的租户与 `[seed]` 前缀篇目，**不碰默认演示校**；`--reset` 只清自己造的数据。
- 走 admin 连接写库（与 `initial_data.py` 同口径），归属租户由脚本显式指定。
- 幂等：学校已存在则跳过该校；该校已有作答题则跳过造作答。重复执行只会补齐缺失的部分。

## 2026-11-17 首次建库实测

- 数据量：2 校 / 6 班 / 120 学生 / 480 作答 / 13 篇目；音频卷 484 文件、3.9 MB。
- 隔离：教师 `t01@seedpilot-01.seed` 登录后 `/classes` 只见 1 个自有班；`admin@seedpilot-01.seed` 见本校 3 班，看不到 `seedpilot-02` 的 3 班——RLS + owner 归属同时生效。
- 分租户计数：`seedpilot-01` 3 班 / 60 学生 / 240 作答，`seedpilot-02` 同量。
