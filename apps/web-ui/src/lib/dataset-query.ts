export type NumericFilters = {
  min_subjects?: number
  max_subjects?: number
  age_min?: number
  age_max?: number
  tr_min?: number
  tr_max?: number
  voxel_min?: number
  voxel_max?: number
}

export type FilterChip = {
  id: string
  label: string
  clearKeys: (keyof NumericFilters)[]
}

export type NumericInputState = {
  min_subjects: string
  max_subjects: string
  age_min: string
  age_max: string
  tr_min: string
  tr_max: string
  voxel_min: string
  voxel_max: string
}

type InlineParseResult = {
  query: string
  filters: NumericFilters
  errors: string[]
  hasInlineFilters: boolean
}

const FIELD_ALIASES: Record<string, string> = {
  n: 'subjects',
  subject: 'subjects',
  subjects: 'subjects',
  participants: 'subjects',
  sample: 'subjects',
  sample_size: 'subjects',
  min_subjects: 'min_subjects',
  max_subjects: 'max_subjects',
  age: 'age',
  age_min: 'age_min',
  age_max: 'age_max',
  tr: 'tr',
  tr_min: 'tr_min',
  tr_max: 'tr_max',
  voxel: 'voxel',
  voxel_mm: 'voxel',
  voxel_min: 'voxel_min',
  voxel_max: 'voxel_max',
}

const FILTER_TOKEN_RE = /\b([a-zA-Z_]+)\s*(<=|>=|=|<|>)\s*([0-9]*\.?[0-9]+)([a-zA-Z]+)?/gi

const isFiniteNumber = (value: unknown): value is number =>
  typeof value === 'number' && Number.isFinite(value)

const parseNumber = (value: string | null | undefined) => {
  if (!value) return undefined
  const parsed = Number(value)
  return Number.isFinite(parsed) ? parsed : undefined
}

const normalizeUnits = (field: string, value: number, unit?: string) => {
  if (!unit) return value
  const normalized = unit.toLowerCase()
  if (field.startsWith('tr')) {
    if (['ms', 'msec', 'milliseconds'].includes(normalized)) {
      return value / 1000
    }
    return value
  }
  return value
}

function applyRangeFilter(
  filters: NumericFilters,
  field: 'subjects' | 'age' | 'tr' | 'voxel',
  op: string,
  value: number,
  errors: string[],
) {
  const minKey = `${field === 'subjects' ? 'min_subjects' : `${field}_min`}` as keyof NumericFilters
  const maxKey = `${field === 'subjects' ? 'max_subjects' : `${field}_max`}` as keyof NumericFilters
  if (op === '>' || op === '>=') {
    filters[minKey] = value
  } else if (op === '<' || op === '<=') {
    filters[maxKey] = value
  } else if (op === '=') {
    filters[minKey] = value
    filters[maxKey] = value
  } else {
    errors.push(`Unsupported operator "${op}" for ${field}`)
  }
}

function applyExplicitBound(
  filters: NumericFilters,
  key: keyof NumericFilters,
  op: string,
  value: number,
  errors: string[],
) {
  if (key === 'min_subjects' || key.endsWith('_min')) {
    if (op === '<' || op === '<=') {
      errors.push(`Use >= or = for ${key} filters`)
      return
    }
    filters[key] = value
    return
  }
  if (key === 'max_subjects' || key.endsWith('_max')) {
    if (op === '>' || op === '>=') {
      errors.push(`Use <= or = for ${key} filters`)
      return
    }
    filters[key] = value
    return
  }
}

export function parseInlineFilters(raw: string): InlineParseResult {
  const errors: string[] = []
  const filters: NumericFilters = {}
  let hasInlineFilters = false

  FILTER_TOKEN_RE.lastIndex = 0
  const matches = Array.from(raw.matchAll(FILTER_TOKEN_RE))
  for (const match of matches) {
    const fieldRaw = match[1]?.toLowerCase()
    const op = match[2]
    const valueStr = match[3]
    const unit = match[4]
    const field = FIELD_ALIASES[fieldRaw]
    if (!field) {
      continue
    }
    const parsed = parseNumber(valueStr)
    if (!isFiniteNumber(parsed)) {
      errors.push(`Could not parse filter "${match[0].trim()}"`)
      continue
    }
    const value = normalizeUnits(field, parsed, unit)
    hasInlineFilters = true

    if (field === 'subjects' || field === 'age' || field === 'tr' || field === 'voxel') {
      applyRangeFilter(filters, field as 'subjects' | 'age' | 'tr' | 'voxel', op, value, errors)
      continue
    }

    if (
      field === 'min_subjects' ||
      field === 'max_subjects' ||
      field === 'age_min' ||
      field === 'age_max' ||
      field === 'tr_min' ||
      field === 'tr_max' ||
      field === 'voxel_min' ||
      field === 'voxel_max'
    ) {
      applyExplicitBound(filters, field as keyof NumericFilters, op, value, errors)
      continue
    }
  }

  FILTER_TOKEN_RE.lastIndex = 0
  const cleaned = raw.replace(FILTER_TOKEN_RE, ' ').replace(/\s+/g, ' ').trim()

  const tokens = raw.split(/\s+/).filter(Boolean)
  for (const token of tokens) {
    const lower = token.toLowerCase()
    const hasOperator = /[<>]=?|=/.test(lower)
    if (!hasOperator) continue
    const fieldName = lower.split(/[<>]=?|=/)[0]
    if (!FIELD_ALIASES[fieldName]) continue
    FILTER_TOKEN_RE.lastIndex = 0
    if (!FILTER_TOKEN_RE.test(token)) {
      errors.push(`Could not parse filter "${token}"`)
    }
    FILTER_TOKEN_RE.lastIndex = 0
  }

  const validateRange = (minKey: keyof NumericFilters, maxKey: keyof NumericFilters, label: string) => {
    const minVal = filters[minKey]
    const maxVal = filters[maxKey]
    if (isFiniteNumber(minVal) && isFiniteNumber(maxVal) && minVal > maxVal) {
      errors.push(`${label} minimum cannot exceed maximum`)
    }
  }

  validateRange('min_subjects', 'max_subjects', 'Subjects')
  validateRange('age_min', 'age_max', 'Age')
  validateRange('tr_min', 'tr_max', 'TR')
  validateRange('voxel_min', 'voxel_max', 'Voxel')

  return { query: cleaned, filters, errors, hasInlineFilters }
}

export function numericFiltersFromSearchParams(searchParams: Record<string, string | string[] | undefined>): NumericFilters {
  const getParam = (key: string) => {
    const value = searchParams[key]
    if (Array.isArray(value)) return value[0]
    return value
  }

  const minSubjects = parseNumber(getParam('min_subjects'))
  const maxSubjects = parseNumber(getParam('max_subjects'))
  const ageMin = parseNumber(getParam('age_min'))
  const ageMax = parseNumber(getParam('age_max'))
  const trMin = parseNumber(getParam('tr_min'))
  const trMax = parseNumber(getParam('tr_max'))
  const voxelMin = parseNumber(getParam('voxel_min'))
  const voxelMax = parseNumber(getParam('voxel_max'))
  const trExact = parseNumber(getParam('tr'))
  const voxelExact = parseNumber(getParam('voxel_mm') ?? getParam('voxel'))

  return {
    min_subjects: minSubjects,
    max_subjects: maxSubjects,
    age_min: ageMin,
    age_max: ageMax,
    tr_min: trExact ?? trMin,
    tr_max: trExact ?? trMax,
    voxel_min: voxelExact ?? voxelMin,
    voxel_max: voxelExact ?? voxelMax,
  }
}

export function numericInputsFromFilters(filters: NumericFilters): NumericInputState {
  return {
    min_subjects: isFiniteNumber(filters.min_subjects) ? String(filters.min_subjects) : '',
    max_subjects: isFiniteNumber(filters.max_subjects) ? String(filters.max_subjects) : '',
    age_min: isFiniteNumber(filters.age_min) ? String(filters.age_min) : '',
    age_max: isFiniteNumber(filters.age_max) ? String(filters.age_max) : '',
    tr_min: isFiniteNumber(filters.tr_min) ? String(filters.tr_min) : '',
    tr_max: isFiniteNumber(filters.tr_max) ? String(filters.tr_max) : '',
    voxel_min: isFiniteNumber(filters.voxel_min) ? String(filters.voxel_min) : '',
    voxel_max: isFiniteNumber(filters.voxel_max) ? String(filters.voxel_max) : '',
  }
}

export function numericFiltersFromInputs(inputs: NumericInputState): { filters: NumericFilters; errors: string[] } {
  const errors: string[] = []
  const parseField = (label: string, value: string) => {
    if (!value.trim()) return undefined
    const parsed = Number(value)
    if (!Number.isFinite(parsed)) {
      errors.push(`Invalid ${label} value`)
      return undefined
    }
    return parsed
  }

  const filters: NumericFilters = {
    min_subjects: parseField('min subjects', inputs.min_subjects),
    max_subjects: parseField('max subjects', inputs.max_subjects),
    age_min: parseField('age min', inputs.age_min),
    age_max: parseField('age max', inputs.age_max),
    tr_min: parseField('TR min', inputs.tr_min),
    tr_max: parseField('TR max', inputs.tr_max),
    voxel_min: parseField('voxel min', inputs.voxel_min),
    voxel_max: parseField('voxel max', inputs.voxel_max),
  }

  const validateRange = (minKey: keyof NumericFilters, maxKey: keyof NumericFilters, label: string) => {
    const minVal = filters[minKey]
    const maxVal = filters[maxKey]
    if (isFiniteNumber(minVal) && isFiniteNumber(maxVal) && minVal > maxVal) {
      errors.push(`${label} minimum cannot exceed maximum`)
    }
  }

  validateRange('min_subjects', 'max_subjects', 'Subjects')
  validateRange('age_min', 'age_max', 'Age')
  validateRange('tr_min', 'tr_max', 'TR')
  validateRange('voxel_min', 'voxel_max', 'Voxel')

  return { filters, errors }
}

export function mergeNumericFilters(base: NumericFilters, incoming: NumericFilters): NumericFilters {
  return {
    min_subjects: incoming.min_subjects ?? base.min_subjects,
    max_subjects: incoming.max_subjects ?? base.max_subjects,
    age_min: incoming.age_min ?? base.age_min,
    age_max: incoming.age_max ?? base.age_max,
    tr_min: incoming.tr_min ?? base.tr_min,
    tr_max: incoming.tr_max ?? base.tr_max,
    voxel_min: incoming.voxel_min ?? base.voxel_min,
    voxel_max: incoming.voxel_max ?? base.voxel_max,
  }
}

export function hasAnyNumericFilters(filters: NumericFilters) {
  return Object.values(filters).some((value) => isFiniteNumber(value))
}

export function appendNumericFilters(params: URLSearchParams, filters: NumericFilters) {
  if (isFiniteNumber(filters.min_subjects)) params.set('min_subjects', String(filters.min_subjects))
  if (isFiniteNumber(filters.max_subjects)) params.set('max_subjects', String(filters.max_subjects))
  if (isFiniteNumber(filters.age_min)) params.set('age_min', String(filters.age_min))
  if (isFiniteNumber(filters.age_max)) params.set('age_max', String(filters.age_max))
  if (isFiniteNumber(filters.tr_min)) params.set('tr_min', String(filters.tr_min))
  if (isFiniteNumber(filters.tr_max)) params.set('tr_max', String(filters.tr_max))
  if (isFiniteNumber(filters.voxel_min)) params.set('voxel_min', String(filters.voxel_min))
  if (isFiniteNumber(filters.voxel_max)) params.set('voxel_max', String(filters.voxel_max))
}

const formatNumber = (value: number) => {
  const rounded = Math.round(value * 100) / 100
  return Number.isInteger(rounded) ? String(rounded) : String(rounded)
}

export function buildFilterChips(filters: NumericFilters): FilterChip[] {
  const chips: FilterChip[] = []

  const addRangeChips = (
    label: string,
    minKey: keyof NumericFilters,
    maxKey: keyof NumericFilters,
    unit?: string,
  ) => {
    const minVal = filters[minKey]
    const maxVal = filters[maxKey]
    if (isFiniteNumber(minVal) && isFiniteNumber(maxVal) && minVal === maxVal) {
      chips.push({
        id: `${label}-eq-${minVal}`,
        label: `${label} = ${formatNumber(minVal)}${unit ?? ''}`,
        clearKeys: [minKey, maxKey],
      })
      return
    }
    if (isFiniteNumber(minVal)) {
      chips.push({
        id: `${label}-min-${minVal}`,
        label: `${label} >= ${formatNumber(minVal)}${unit ?? ''}`,
        clearKeys: [minKey],
      })
    }
    if (isFiniteNumber(maxVal)) {
      chips.push({
        id: `${label}-max-${maxVal}`,
        label: `${label} <= ${formatNumber(maxVal)}${unit ?? ''}`,
        clearKeys: [maxKey],
      })
    }
  }

  addRangeChips('N', 'min_subjects', 'max_subjects')
  addRangeChips('Age', 'age_min', 'age_max', 'y')
  addRangeChips('TR', 'tr_min', 'tr_max', 's')
  addRangeChips('Voxel', 'voxel_min', 'voxel_max', 'mm')

  return chips
}
