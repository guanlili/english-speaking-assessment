import {
  type ColumnDef,
  flexRender,
  getCoreRowModel,
  getPaginationRowModel,
  type PaginationState,
  useReactTable,
} from "@tanstack/react-table"
import {
  ChevronLeft,
  ChevronRight,
  ChevronsLeft,
  ChevronsRight,
} from "lucide-react"

import { Button } from "@/components/ui/button"
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select"
import {
  Table,
  TableBody,
  TableCell,
  TableHead,
  TableHeader,
  TableRow,
} from "@/components/ui/table"
import { useI18n } from "@/lib/i18n"

/** 服务端分页（受控）：总数来自服务器，翻页由调用方发新请求 */
export interface ManualPagination {
  rowCount: number
  pageIndex: number
  pageSize: number
  onPageChange: (pageIndex: number) => void
  onPageSizeChange: (pageSize: number) => void
  loading?: boolean
}

interface DataTableProps<TData, TValue> {
  columns: ColumnDef<TData, TValue>[]
  data: TData[]
  /** 不传 = 默认客户端分页（现有调用方行为不变） */
  manualPagination?: ManualPagination
}

const PAGE_SIZE_OPTIONS = [10, 25, 50, 100]

export function DataTable<TData, TValue>({
  columns,
  data,
  manualPagination,
}: DataTableProps<TData, TValue>) {
  const { t } = useI18n()
  const isManual = manualPagination !== undefined
  const total = isManual ? manualPagination.rowCount : data.length

  const table = useReactTable({
    data,
    columns,
    getCoreRowModel: getCoreRowModel(),
    // 服务端分页：行模型不分页（data 已是当前页），页数与状态由外部受控
    getPaginationRowModel: isManual ? undefined : getPaginationRowModel(),
    manualPagination: isManual,
    pageCount: isManual
      ? Math.max(
          1,
          Math.ceil(manualPagination.rowCount / manualPagination.pageSize),
        )
      : undefined,
    state: isManual
      ? {
          pagination: {
            pageIndex: manualPagination.pageIndex,
            pageSize: manualPagination.pageSize,
          } satisfies PaginationState,
        }
      : undefined,
    onPaginationChange: isManual
      ? (updater) => {
          const next =
            typeof updater === "function"
              ? updater({
                  pageIndex: manualPagination.pageIndex,
                  pageSize: manualPagination.pageSize,
                })
              : updater
          if (next.pageIndex !== manualPagination.pageIndex) {
            manualPagination.onPageChange(next.pageIndex)
          }
          if (next.pageSize !== manualPagination.pageSize) {
            manualPagination.onPageSizeChange(next.pageSize)
          }
        }
      : undefined,
  })

  const { pageIndex, pageSize } = table.getState().pagination
  const firstRow = total === 0 ? 0 : pageIndex * pageSize + 1
  const lastRow = Math.min((pageIndex + 1) * pageSize, total)

  return (
    <div className="flex flex-col gap-4">
      <div
        aria-busy={manualPagination?.loading || undefined}
        className={
          manualPagination?.loading
            ? "opacity-60 transition-opacity"
            : undefined
        }
      >
        <Table>
          <TableHeader>
            {table.getHeaderGroups().map((headerGroup) => (
              <TableRow key={headerGroup.id} className="hover:bg-transparent">
                {headerGroup.headers.map((header) => {
                  return (
                    <TableHead key={header.id}>
                      {header.isPlaceholder
                        ? null
                        : flexRender(
                            header.column.columnDef.header,
                            header.getContext(),
                          )}
                    </TableHead>
                  )
                })}
              </TableRow>
            ))}
          </TableHeader>
          <TableBody>
            {table.getRowModel().rows.length ? (
              table.getRowModel().rows.map((row) => (
                <TableRow key={row.id}>
                  {row.getVisibleCells().map((cell) => (
                    <TableCell key={cell.id}>
                      {flexRender(
                        cell.column.columnDef.cell,
                        cell.getContext(),
                      )}
                    </TableCell>
                  ))}
                </TableRow>
              ))
            ) : (
              <TableRow className="hover:bg-transparent">
                <TableCell
                  colSpan={columns.length}
                  className="h-32 text-center text-muted-foreground"
                >
                  {t({ zh: "暂无数据", en: "No results found." })}
                </TableCell>
              </TableRow>
            )}
          </TableBody>
        </Table>
      </div>

      {table.getPageCount() > 1 && (
        <div className="flex flex-col sm:flex-row items-start sm:items-center justify-between gap-4 p-4 border-t bg-muted/20">
          <div className="flex flex-col sm:flex-row sm:items-center gap-4">
            <div className="text-sm text-muted-foreground">
              {t({
                zh: `第 ${firstRow}-${lastRow} 条 / 共 ${total} 条`,
                en: `Showing ${firstRow} to ${lastRow} of ${total} entries`,
              })}
            </div>
            <div className="flex items-center gap-x-2">
              <p className="text-sm text-muted-foreground">
                {t({ zh: "每页条数", en: "Rows per page" })}
              </p>
              <Select
                value={`${table.getState().pagination.pageSize}`}
                onValueChange={(value) => {
                  table.setPageSize(Number(value))
                }}
              >
                <SelectTrigger
                  className="h-11 w-[90px] text-base"
                  aria-label={t({ zh: "每页条数", en: "Rows per page" })}
                >
                  <SelectValue
                    placeholder={table.getState().pagination.pageSize}
                  />
                </SelectTrigger>
                <SelectContent side="top">
                  {PAGE_SIZE_OPTIONS.map((pageSize) => (
                    <SelectItem key={pageSize} value={`${pageSize}`}>
                      {pageSize}
                    </SelectItem>
                  ))}
                </SelectContent>
              </Select>
            </div>
          </div>

          <div className="flex items-center gap-x-6">
            <div className="flex items-center gap-x-1 text-sm text-muted-foreground">
              {t({
                zh: `第 ${table.getState().pagination.pageIndex + 1} / ${table.getPageCount()} 页`,
                en: `Page ${table.getState().pagination.pageIndex + 1} of ${table.getPageCount()}`,
              })}
            </div>

            <div className="flex items-center gap-x-1">
              <Button
                variant="outline"
                size="sm"
                className="h-11 w-11 p-0"
                onClick={() => table.setPageIndex(0)}
                disabled={!table.getCanPreviousPage()}
              >
                <span className="sr-only">
                  {t({ zh: "第一页", en: "Go to first page" })}
                </span>
                <ChevronsLeft className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-11 w-11 p-0"
                onClick={() => table.previousPage()}
                disabled={!table.getCanPreviousPage()}
              >
                <span className="sr-only">
                  {t({ zh: "上一页", en: "Go to previous page" })}
                </span>
                <ChevronLeft className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-11 w-11 p-0"
                onClick={() => table.nextPage()}
                disabled={!table.getCanNextPage()}
              >
                <span className="sr-only">
                  {t({ zh: "下一页", en: "Go to next page" })}
                </span>
                <ChevronRight className="h-4 w-4" />
              </Button>
              <Button
                variant="outline"
                size="sm"
                className="h-11 w-11 p-0"
                onClick={() => table.setPageIndex(table.getPageCount() - 1)}
                disabled={!table.getCanNextPage()}
              >
                <span className="sr-only">
                  {t({ zh: "最后一页", en: "Go to last page" })}
                </span>
                <ChevronsRight className="h-4 w-4" />
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  )
}
