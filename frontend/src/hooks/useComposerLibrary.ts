import {
  keepPreviousData,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query"
import { useEffect, useMemo, useState } from "react"
import {
  AdminService,
  type AssignmentItemIn,
  type ComposerLibraryData,
  type InstructionPublic,
  type PassageWithSentences,
  type ScenarioOut,
  type SentenceWithPassage,
} from "@/client"
import { COMPOSER_PRESET_KEY } from "@/lib/questionImport"

const PAGE_SIZE = 20
type LibraryData = Required<ComposerLibraryData>
const EMPTY: LibraryData = {
  passages: [],
  sentences: [],
  scenarios: [],
  instructions: [],
  missing_ids: [],
}
type Kind = "passages" | "sentences" | "scenarios" | "instructions"

export interface ComposerPage {
  keyword: string
  setKeyword: (value: string) => void
  page: number
  setPage: (page: number) => void
  hasNext: boolean
  pending: boolean
  failed: boolean
  retry: () => void
}

function useCatalog<T>(
  kind: Kind,
  fetchPage: (q: string, skip: number) => Promise<T[]>,
) {
  const [keyword, setKeyword] = useState("")
  const [search, setSearch] = useState("")
  const [page, setPage] = useState(0)
  useEffect(() => {
    if (keyword.trim() === search) return
    const timer = setTimeout(() => {
      setSearch(keyword.trim())
      setPage(0)
    }, 250)
    return () => clearTimeout(timer)
  }, [keyword, search])
  const query = useQuery({
    queryKey: ["admin", kind, "composer", search, page],
    queryFn: () => fetchPage(search, page * PAGE_SIZE),
    placeholderData: keepPreviousData,
  })
  const control: ComposerPage = {
    keyword,
    setKeyword: (value) => setKeyword(value.slice(0, 200)),
    page,
    setPage,
    hasNext: (query.data?.length ?? 0) > PAGE_SIZE,
    pending: query.isFetching,
    failed: query.isError,
    retry: () => {
      void query.refetch()
    },
  }
  return { query, control, rows: query.data?.slice(0, PAGE_SIZE) ?? [] }
}

function merge<T extends { id?: string }>(...groups: (T[] | undefined)[]): T[] {
  return [
    ...new Map(
      groups.flatMap((group) => group ?? []).map((row) => [row.id, row]),
    ).values(),
  ]
}
function combine(a: LibraryData, b: Partial<ComposerLibraryData>): LibraryData {
  return {
    passages: merge(a.passages, b.passages),
    sentences: merge(a.sentences, b.sentences),
    scenarios: merge(a.scenarios, b.scenarios),
    instructions: merge(a.instructions, b.instructions),
    missing_ids: b.missing_ids ?? [],
  }
}

export function useComposerLibrary(
  assignedItems: { [key: string]: string }[] | null | undefined,
) {
  const client = useQueryClient()
  const passages = useCatalog<PassageWithSentences>(
    "passages",
    async (q, skip) =>
      (await AdminService.listPassages({ q, skip, limit: PAGE_SIZE + 1 }))
        .data ?? [],
  )
  const sentences = useCatalog<SentenceWithPassage>("sentences", (q, skip) =>
    AdminService.listSentencesFlat({ q, skip, limit: PAGE_SIZE + 1 }),
  )
  const scenarios = useCatalog<ScenarioOut>(
    "scenarios",
    async (q, skip) =>
      (await AdminService.listScenarios({ q, skip, limit: PAGE_SIZE + 1 }))
        .data ?? [],
  )
  const instructions = useCatalog<InstructionPublic>(
    "instructions",
    (q, skip) =>
      AdminService.listInstructions({ q, skip, limit: PAGE_SIZE + 1 }),
  )
  const [selected, setSelected] = useState<AssignmentItemIn[]>([])
  const [preset] = useState(() => {
    try {
      const value = JSON.parse(
        sessionStorage.getItem(COMPOSER_PRESET_KEY) ?? "{}",
      ) as Record<string, unknown>
      return Object.entries({
        passages: "passage",
        sentences: "repeat",
        questions: "question",
        instructions: "instruction",
      }).flatMap(([key, type]) => {
        const ids = value[key]
        return Array.isArray(ids)
          ? ids
              .filter((id): id is string => typeof id === "string")
              .map((id) => ({ type, id }))
          : []
      })
    } catch {
      return []
    }
  })
  const refs = [
    ...new Map(
      [
        ...(assignedItems ?? []).map((item) => ({
          type: item.type,
          id: item.id,
        })),
        ...preset,
        ...selected,
      ].map((item) => [`${item.type}:${item.id}`, item]),
    ).values(),
  ]
  const signature = JSON.stringify(refs)
  const selectionKey = ["admin", "composer-selection", signature] as const
  const cached = useMemo(() => {
    let data = EMPTY
    for (const [, value] of client.getQueriesData<
      PassageWithSentences[] | { data?: PassageWithSentences[] }
    >({ queryKey: ["admin", "passages"] }))
      data = combine(data, {
        passages: Array.isArray(value) ? value : value?.data,
      })
    for (const [, value] of client.getQueriesData<
      SentenceWithPassage[] | { data: SentenceWithPassage[] }
    >({ queryKey: ["admin", "sentences"] }))
      data = combine(data, {
        sentences: Array.isArray(value) ? value : value?.data,
      })
    for (const [, value] of client.getQueriesData<
      ScenarioOut[] | { data?: ScenarioOut[] }
    >({ queryKey: ["admin", "scenarios"] }))
      data = combine(data, {
        scenarios: Array.isArray(value) ? value : value?.data,
      })
    for (const [, value] of client.getQueriesData<InstructionPublic[]>({
      queryKey: ["admin", "instructions"],
    }))
      data = combine(data, { instructions: Array.isArray(value) ? value : [] })
    return data
  }, [client])
  const selection = useQuery({
    queryKey: selectionKey,
    queryFn: () =>
      AdminService.readComposerSelection({
        requestBody: { items: JSON.parse(signature) as AssignmentItemIn[] },
      }),
    placeholderData: (previous) => previous ?? cached,
  })
  const [visited, setVisited] = useState(EMPTY)
  useEffect(() => {
    setVisited((prev) =>
      combine(prev, {
        passages: passages.query.data,
        sentences: sentences.query.data,
        scenarios: scenarios.query.data,
        instructions: instructions.query.data,
      }),
    )
  }, [
    passages.query.data,
    sentences.query.data,
    scenarios.query.data,
    instructions.query.data,
  ])
  const merged = combine(
    combine(combine(cached, visited), {
      passages: passages.query.data,
      sentences: sentences.query.data,
      scenarios: scenarios.query.data,
      instructions: instructions.query.data,
    }),
    selection.data ?? EMPTY,
  )
  const missing = new Set(selection.data?.missing_ids ?? [])
  const data = {
    ...merged,
    passages: merged.passages.filter((row) => !missing.has(row.id ?? "")),
    sentences: merged.sentences.filter((row) => !missing.has(row.id ?? "")),
    scenarios: merged.scenarios.map((row) => ({
      ...row,
      questions: row.questions.filter((q) => !missing.has(q.id)),
    })),
    instructions: merged.instructions.filter(
      (row) => !missing.has(row.id ?? ""),
    ),
  }
  const catalogs = [passages, sentences, scenarios, instructions]
  return {
    data,
    passages,
    sentences,
    scenarios,
    instructions,
    selectionKey,
    setSelected,
    pending:
      catalogs.some((catalog) => catalog.query.isPending) ||
      (refs.length > 0 &&
        selection.isFetching &&
        !selection.isPlaceholderData &&
        !selection.data),
    failed:
      catalogs.some(
        (catalog) => catalog.query.isError && !catalog.query.data,
      ) ||
      (selection.isError && refs.length > 0 && !selection.data),
    retry: () => {
      for (const catalog of catalogs) void catalog.query.refetch()
      void selection.refetch()
    },
  }
}
export type ComposerLibrary = ReturnType<typeof useComposerLibrary>
