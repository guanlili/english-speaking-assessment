#!/usr/bin/env python3
"""整校模块授权回填 / 调整脚本（#516 / #517）。

口径：
- 授权粒度 = 整校 × module_key（``speaking`` / ``vocabulary``）；无班级
  override、无白名单、无按班灰度。PK / 农场 / FSRS 随 vocabulary 整体开关。
- 缺行 = 未购买（默认关）；迁移回填口径为 speaking=on、vocabulary=off。
- 幂等：目标状态一致则不重复写；``--revert`` 删除目标行（回滚用）。
- 不猜试点校：``--tenant-slug`` 显式指定；不传 slug 仅用于全量回填默认口径。
- 脚本回填不写 ``tenant_module_audit`` 业务审计（审计只记录平台运营后台改写）。

用法（backend 容器或本地 uv 环境）：

    # 演练：只打租户清单与变更计划，不写库
    python scripts/backfill_tenant_modules.py --dry-run

    # 全量回填默认口径：speaking=on、vocabulary=off
    python scripts/backfill_tenant_modules.py

    # 给指定试点校整校开启 vocabulary（--tenant-slug 可重复）
    python scripts/backfill_tenant_modules.py --tenant-slug school-a --enable vocabulary

    # 关闭某校 vocabulary
    python scripts/backfill_tenant_modules.py --tenant-slug school-a --disable vocabulary

    # 回滚：删除目标校模块授权行
    python scripts/backfill_tenant_modules.py --tenant-slug school-a --revert
"""

from __future__ import annotations

import argparse
import sys
from datetime import UTC, datetime

from sqlalchemy import create_engine
from sqlmodel import Session, select

from app.core.config import settings
from app.models import MODULE_KEYS, Tenant, TenantModule


def _now() -> datetime:
    return datetime.now(UTC)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="整校模块授权回填/调整")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只打印租户清单与变更计划，不写库",
    )
    parser.add_argument(
        "--tenant-slug",
        action="append",
        default=[],
        help="目标学校码（可重复）；不传 = 全部学校（仅默认回填口径）",
    )
    parser.add_argument(
        "--enable",
        choices=list(MODULE_KEYS),
        help="开启指定模块（upsert enabled=true）",
    )
    parser.add_argument(
        "--disable",
        choices=list(MODULE_KEYS),
        help="关闭指定模块（upsert enabled=false）",
    )
    parser.add_argument(
        "--revert",
        action="store_true",
        help="删除目标校的模块授权行（回滚）",
    )
    parser.add_argument(
        "--allow-production",
        action="store_true",
        help="显式允许在 production 环境执行（默认拒绝连生产库）",
    )
    args = parser.parse_args()

    if args.revert and (args.enable or args.disable):
        parser.error("--revert 不能与 --enable/--disable 同用")
    if args.enable and args.disable:
        parser.error("--enable 与 --disable 不能同用")
    return args


def _resolve_tenants(session: Session, slugs: list[str]) -> list[Tenant]:
    if not slugs:
        return list(session.exec(select(Tenant).order_by(Tenant.slug)).all())
    tenants: list[Tenant] = []
    available = [
        t.slug
        for t in session.exec(select(Tenant).order_by(Tenant.slug)).all()
    ]
    for slug in slugs:
        normalized = slug.strip().lower()
        row = session.exec(select(Tenant).where(Tenant.slug == normalized)).first()
        if row is None:
            sys.exit(
                f"学校码不存在：{normalized}；库内现有 slug：{', '.join(available) or '（空）'}"
            )
        tenants.append(row)
    return tenants


def _planned_states(args: argparse.Namespace) -> dict[str, bool]:
    """返回本次要落到的 module_key → enabled 计划。"""
    if args.revert:
        return {}
    if args.enable:
        return {args.enable: True}
    if args.disable:
        return {args.disable: False}
    # 默认回填口径：speaking=on、vocabulary=off
    return {"speaking": True, "vocabulary": False}


def main() -> None:
    args = _parse_args()

    if settings.ENVIRONMENT == "production" and not args.allow_production:
        sys.exit(
            "拒绝在 production 环境直接执行：回填前先在演练环境 dry-run 核对清单；"
            "确需对生产执行请显式加 --allow-production。"
        )

    engine = create_engine(str(settings.SQLALCHEMY_ADMIN_DATABASE_URI))
    planned = _planned_states(args)

    with Session(engine) as session:
        tenants = _resolve_tenants(session, args.tenant_slug)
        if not tenants:
            print("库内没有匹配的学校，退出。")
            return

        print(f"目标学校 {len(tenants)} 所；dry-run={args.dry_run}；revert={args.revert}")
        header = f"{'slug':<28} {'status':<10} 计划"
        print(header)
        print("-" * len(header))

        for tenant in tenants:
            if args.revert:
                action = "revert（删除授权行）"
            else:
                action = ", ".join(
                    f"{key}={'on' if enabled else 'off'}"
                    for key, enabled in planned.items()
                )
            print(f"{tenant.slug:<28} {tenant.status:<10} {action}")

            if args.dry_run:
                continue

            if args.revert:
                rows = session.exec(
                    select(TenantModule).where(TenantModule.tenant_id == tenant.id)
                ).all()
                for row in rows:
                    session.delete(row)
                continue

            for key, enabled in planned.items():
                row = session.exec(
                    select(TenantModule).where(
                        TenantModule.tenant_id == tenant.id,
                        TenantModule.module_key == key,
                    )
                ).first()
                if row is None:
                    session.add(
                        TenantModule(
                            tenant_id=tenant.id,
                            module_key=key,
                            enabled=enabled,
                            effective_at=None,
                        )
                    )
                elif row.enabled != enabled:
                    row.enabled = enabled
                    row.effective_at = None
                    row.updated_at = _now()
                    row.updated_by = None
        if not args.dry_run:
            session.commit()
            print("已提交。")
        else:
            print("dry-run：未写库。")

    engine.dispose()


if __name__ == "__main__":
    main()
