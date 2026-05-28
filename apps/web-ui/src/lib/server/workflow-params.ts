import type {
  WorkflowDetail,
  WorkflowInputProperty,
  WorkflowInputsSchema,
  WorkflowParamPrimitiveType,
} from '@/lib/api/workflows'

const INPUT_REF_PATTERN = /\$\{inputs\.([a-zA-Z0-9_]+)(?::-(.*?))?\}/g
const INTEGER_PATTERN = /^[+-]?\d+$/
const NUMBER_PATTERN = /^[+-]?(?:\d+\.?\d*|\.\d+)(?:[eE][+-]?\d+)?$/

const COMMON_HEURISTIC_DEFAULTS: Record<string, unknown> = {
  n_perm: 1000,
  n_permutations: 1000,
  n_splits: 5,
  radius: 6,
  smoothing_fwhm: 6,
  standardize: true,
  detrend: true,
  low_pass: 0.1,
  high_pass: 0.01,
  t_r: 2,
  cv_type: 'kfold',
  task_type: 'classification',
  container_type: 'docker',
  dry_run: false,
}

type PlainObject = Record<string, unknown>

export type ParamValidationIssue = {
  field: string
  code: 'required' | 'type' | 'enum' | 'minimum' | 'maximum'
  message: string
}

export type WorkflowParamContract = {
  schema: WorkflowInputsSchema
  discoveredInputKeys: string[]
  missingContractFields: string[]
  required: string[]
  defaultsBySource: {
    schema_property_defaults: Record<string, unknown>
    workflow_defaults: Record<string, unknown>
    placeholder_inferred_defaults: Record<string, unknown>
    heuristic_inferred_defaults: Record<string, unknown>
    merged: Record<string, unknown>
  }
}

function safeObject(value: unknown): PlainObject {
  if (!value || typeof value !== 'object' || Array.isArray(value)) return {}
  return value as PlainObject
}

function uniqueStrings(values: unknown): string[] {
  if (!Array.isArray(values)) return []
  const out: string[] = []
  const seen = new Set<string>()
  for (const value of values) {
    if (typeof value !== 'string') continue
    const normalized = value.trim()
    if (!normalized || seen.has(normalized)) continue
    seen.add(normalized)
    out.push(normalized)
  }
  return out
}

function normalizeProperty(raw: unknown): WorkflowInputProperty {
  const input = safeObject(raw)
  const out: WorkflowInputProperty = {}
  if (typeof input.type === 'string') out.type = input.type as WorkflowInputProperty['type']
  if (typeof input.title === 'string') out.title = input.title
  if (typeof input.description === 'string') out.description = input.description
  if (Array.isArray(input.enum)) out.enum = input.enum
  if (Object.prototype.hasOwnProperty.call(input, 'default')) out.default = input.default
  if (typeof input.minimum === 'number') out.minimum = input.minimum
  if (typeof input.maximum === 'number') out.maximum = input.maximum
  if (typeof input.ui_component === 'string') out.ui_component = input.ui_component
  if (Object.prototype.hasOwnProperty.call(input, 'example')) out.example = input.example
  return out
}

function inferTypeFromValue(value: unknown): WorkflowParamPrimitiveType {
  if (Array.isArray(value)) return 'array'
  if (typeof value === 'boolean') return 'boolean'
  if (typeof value === 'number') return Number.isInteger(value) ? 'integer' : 'number'
  return 'string'
}

function inferDefaultValue(rawDefault: string): unknown {
  const trimmed = rawDefault.trim()
  if (!trimmed) return ''

  const booleanValue = parseBoolean(trimmed)
  if (booleanValue !== undefined) return booleanValue

  if (INTEGER_PATTERN.test(trimmed)) {
    return Number.parseInt(trimmed, 10)
  }

  if (NUMBER_PATTERN.test(trimmed)) {
    const parsed = Number.parseFloat(trimmed)
    if (Number.isFinite(parsed)) return parsed
  }

  if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
    try {
      const parsed = JSON.parse(trimmed)
      if (Array.isArray(parsed)) return parsed
    } catch {
      // Keep the original string if this is not valid JSON.
    }
  }

  return trimmed
}

function parseDefaultForPropertyType(
  rawDefault: string,
  propertyType: WorkflowParamPrimitiveType | undefined,
): unknown {
  const trimmed = rawDefault.trim()
  if (!propertyType) return inferDefaultValue(trimmed)

  if (propertyType === 'string') return trimmed

  if (propertyType === 'boolean') {
    const parsed = parseBoolean(trimmed)
    return parsed === undefined ? trimmed : parsed
  }

  if (propertyType === 'integer') {
    if (INTEGER_PATTERN.test(trimmed)) return Number.parseInt(trimmed, 10)
    if (NUMBER_PATTERN.test(trimmed)) {
      const parsed = Number.parseFloat(trimmed)
      if (Number.isFinite(parsed)) return Math.trunc(parsed)
    }
    return trimmed
  }

  if (propertyType === 'number') {
    if (NUMBER_PATTERN.test(trimmed)) {
      const parsed = Number.parseFloat(trimmed)
      if (Number.isFinite(parsed)) return parsed
    }
    return trimmed
  }

  if (propertyType === 'array') {
    if (trimmed.startsWith('[') && trimmed.endsWith(']')) {
      try {
        const parsed = JSON.parse(trimmed)
        if (Array.isArray(parsed)) return parsed
      } catch {
        // Keep the original string if this is not valid JSON.
      }
    }
    return trimmed
  }

  if (propertyType === 'object') {
    if (trimmed.startsWith('{') && trimmed.endsWith('}')) {
      try {
        const parsed = JSON.parse(trimmed)
        if (parsed && typeof parsed === 'object' && !Array.isArray(parsed)) return parsed
      } catch {
        // Keep the original string if this is not valid JSON.
      }
    }
    return trimmed
  }

  return inferDefaultValue(trimmed)
}

function extractWorkflowInputUsage(workflow: WorkflowDetail): {
  discoveredInputKeys: string[]
  placeholderDefaultsRaw: Record<string, string>
} {
  const keys = new Set<string>()
  const placeholderDefaultsRaw: Record<string, string> = {}

  const visit = (value: unknown) => {
    if (typeof value === 'string') {
      const pattern = new RegExp(INPUT_REF_PATTERN.source, 'g')
      let match = pattern.exec(value)
      while (match) {
        const key = match[1]?.trim()
        if (key) {
          keys.add(key)
          if (
            match[2] !== undefined &&
            !Object.prototype.hasOwnProperty.call(placeholderDefaultsRaw, key)
          ) {
            placeholderDefaultsRaw[key] = match[2]
          }
        }
        match = pattern.exec(value)
      }
      return
    }
    if (Array.isArray(value)) {
      value.forEach(visit)
      return
    }
    if (value && typeof value === 'object') {
      Object.values(value).forEach(visit)
    }
  }

  for (const step of workflow.runtime?.steps ?? []) {
    visit(step.params)
  }

  return {
    discoveredInputKeys: Array.from(keys).sort(),
    placeholderDefaultsRaw,
  }
}

function inferPlaceholderDefaults(
  placeholderDefaultsRaw: Record<string, string>,
  explicitProperties: Record<string, WorkflowInputProperty>,
): Record<string, unknown> {
  const inferredDefaults: Record<string, unknown> = {}
  for (const [key, rawDefault] of Object.entries(placeholderDefaultsRaw)) {
    inferredDefaults[key] = parseDefaultForPropertyType(rawDefault, explicitProperties[key]?.type)
  }
  return inferredDefaults
}

function inferHeuristicDefaults(
  workflowId: string,
  discoveredInputKeys: string[],
): Record<string, unknown> {
  const inferredDefaults: Record<string, unknown> = {}
  for (const key of discoveredInputKeys) {
    if (key === 'output_dir') {
      inferredDefaults[key] = `/tmp/brain-researcher/${workflowId}`
      continue
    }
    if (Object.prototype.hasOwnProperty.call(COMMON_HEURISTIC_DEFAULTS, key)) {
      inferredDefaults[key] = COMMON_HEURISTIC_DEFAULTS[key]
    }
  }
  return inferredDefaults
}

function parseBoolean(value: string): boolean | undefined {
  const normalized = value.trim().toLowerCase()
  if (['true', '1', 'yes', 'y', 'on'].includes(normalized)) return true
  if (['false', '0', 'no', 'n', 'off'].includes(normalized)) return false
  return undefined
}

function coerceValue(value: unknown, property: WorkflowInputProperty): unknown {
  if (value == null) return value
  const targetType = property.type
  if (!targetType) return value

  if (targetType === 'boolean') {
    if (typeof value === 'boolean') return value
    if (typeof value === 'string') {
      const parsed = parseBoolean(value)
      return parsed === undefined ? value : parsed
    }
    return value
  }

  if (targetType === 'integer' || targetType === 'number') {
    if (typeof value === 'number') {
      return targetType === 'integer' ? Math.trunc(value) : value
    }
    if (typeof value === 'string' && value.trim()) {
      const parsed = Number(value)
      if (Number.isFinite(parsed)) {
        return targetType === 'integer' ? Math.trunc(parsed) : parsed
      }
    }
    return value
  }

  if ((targetType === 'array' || targetType === 'object') && typeof value === 'string') {
    const trimmed = value.trim()
    if (!trimmed) return value
    try {
      return JSON.parse(trimmed)
    } catch {
      return value
    }
  }

  return value
}

export function resolveWorkflowParamContract(workflow: WorkflowDetail): WorkflowParamContract {
  const { discoveredInputKeys, placeholderDefaultsRaw } = extractWorkflowInputUsage(workflow)
  const explicitSchemaRaw = safeObject(workflow.params?.schema)
  const explicitPropertiesRaw = safeObject(explicitSchemaRaw.properties)
  const explicitRequired = uniqueStrings(explicitSchemaRaw.required)

  const explicitProperties: Record<string, WorkflowInputProperty> = {}
  for (const [key, rawProperty] of Object.entries(explicitPropertiesRaw)) {
    explicitProperties[key] = normalizeProperty(rawProperty)
  }

  const placeholderInferredDefaults = inferPlaceholderDefaults(
    placeholderDefaultsRaw,
    explicitProperties,
  )
  const heuristicInferredDefaults = inferHeuristicDefaults(workflow.id, discoveredInputKeys)
  const inferredDefaults = {
    ...heuristicInferredDefaults,
    ...placeholderInferredDefaults,
  }

  const normalizedProperties: Record<string, WorkflowInputProperty> = { ...explicitProperties }
  const missingContractFields = discoveredInputKeys.filter((key) => !(key in normalizedProperties))
  for (const key of missingContractFields) {
    normalizedProperties[key] = {
      type: inferTypeFromValue(inferredDefaults[key]),
      description: `Input parameter ${key}.`,
    }
  }

  const schemaPropertyDefaults: Record<string, unknown> = {}
  for (const [key, property] of Object.entries(normalizedProperties)) {
    if (Object.prototype.hasOwnProperty.call(property, 'default')) {
      schemaPropertyDefaults[key] = property.default
    }
  }

  const workflowDefaults = safeObject(workflow.params?.defaults)
  const mergedDefaults = {
    ...heuristicInferredDefaults,
    ...placeholderInferredDefaults,
    ...schemaPropertyDefaults,
    ...workflowDefaults,
  }

  const requiredSet = new Set<string>(
    explicitRequired.length > 0 ? explicitRequired : discoveredInputKeys,
  )
  for (const key of Object.keys(mergedDefaults)) {
    if (requiredSet.has(key)) requiredSet.delete(key)
  }
  for (const [key] of Object.entries(inferredDefaults)) {
    if (!(key in explicitProperties) && requiredSet.has(key)) requiredSet.delete(key)
  }

  const required = Array.from(requiredSet)

  return {
    schema: {
      type: 'object',
      properties: normalizedProperties,
      required,
    },
    discoveredInputKeys,
    missingContractFields,
    required,
    defaultsBySource: {
      schema_property_defaults: schemaPropertyDefaults,
      workflow_defaults: workflowDefaults,
      placeholder_inferred_defaults: placeholderInferredDefaults,
      heuristic_inferred_defaults: heuristicInferredDefaults,
      merged: mergedDefaults,
    },
  }
}

export function mergeWorkflowParams(
  contract: WorkflowParamContract,
  rawParams: unknown,
): Record<string, unknown> {
  const merged: Record<string, unknown> = {
    ...contract.defaultsBySource.merged,
    ...safeObject(rawParams),
  }
  const properties = contract.schema.properties ?? {}

  for (const [key, property] of Object.entries(properties)) {
    merged[key] = coerceValue(merged[key], property)
  }

  return merged
}

export function validateWorkflowParams(
  contract: WorkflowParamContract,
  params: Record<string, unknown>,
): ParamValidationIssue[] {
  const issues: ParamValidationIssue[] = []
  const properties = contract.schema.properties ?? {}

  for (const field of contract.required) {
    const value = params[field]
    if (value == null) {
      issues.push({
        field,
        code: 'required',
        message: `Provide parameter "${field}" before running this workflow.`,
      })
      continue
    }
    if (typeof value === 'string' && !value.trim()) {
      issues.push({
        field,
        code: 'required',
        message: `Provide parameter "${field}" before running this workflow.`,
      })
    }
  }

  for (const [field, property] of Object.entries(properties)) {
    const value = params[field]
    if (value == null || value === '') continue

    if (property.type === 'string' && typeof value !== 'string') {
      issues.push({
        field,
        code: 'type',
        message: `Parameter "${field}" must be a string.`,
      })
      continue
    }

    if (property.type === 'boolean' && typeof value !== 'boolean') {
      issues.push({
        field,
        code: 'type',
        message: `Parameter "${field}" must be true or false.`,
      })
      continue
    }

    if ((property.type === 'number' || property.type === 'integer') && typeof value !== 'number') {
      issues.push({
        field,
        code: 'type',
        message: `Parameter "${field}" must be a number.`,
      })
      continue
    }

    if (property.type === 'integer' && typeof value === 'number' && !Number.isInteger(value)) {
      issues.push({
        field,
        code: 'type',
        message: `Parameter "${field}" must be an integer.`,
      })
      continue
    }

    if (property.type === 'array' && !Array.isArray(value)) {
      issues.push({
        field,
        code: 'type',
        message: `Parameter "${field}" must be an array.`,
      })
      continue
    }

    if (
      property.type === 'object' &&
      (typeof value !== 'object' || Array.isArray(value) || value == null)
    ) {
      issues.push({
        field,
        code: 'type',
        message: `Parameter "${field}" must be an object.`,
      })
      continue
    }

    if (Array.isArray(property.enum) && property.enum.length > 0 && !property.enum.includes(value)) {
      issues.push({
        field,
        code: 'enum',
        message: `Parameter "${field}" must be one of: ${property.enum.join(', ')}.`,
      })
      continue
    }

    if (typeof property.minimum === 'number' && typeof value === 'number' && value < property.minimum) {
      issues.push({
        field,
        code: 'minimum',
        message: `Parameter "${field}" must be greater than or equal to ${property.minimum}.`,
      })
      continue
    }

    if (typeof property.maximum === 'number' && typeof value === 'number' && value > property.maximum) {
      issues.push({
        field,
        code: 'maximum',
        message: `Parameter "${field}" must be less than or equal to ${property.maximum}.`,
      })
    }
  }

  return issues
}
