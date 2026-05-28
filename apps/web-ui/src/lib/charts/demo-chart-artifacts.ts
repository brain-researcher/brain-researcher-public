export type DemoBundleArtifactItem = {
  id?: string
  name?: string
  path: string
  title?: string | null
  stage?: string | null
  roles?: string[]
  mime_type?: string
  download_url: string
}

export type DemoChartArtifactGroups = {
  images: DemoBundleArtifactItem[]
  csvs: DemoBundleArtifactItem[]
}

export type CsvPreview = {
  header: string[]
  rows: string[][]
  truncated: boolean
}

const IMAGE_EXTENSIONS = new Set(['png', 'jpg', 'jpeg', 'svg', 'webp', 'gif'])
const CSV_EXTENSIONS = new Set(['csv', 'tsv'])

function getExtension(value: string): string {
  const clean = value.split('?')[0] || value
  const tail = clean.split('.').pop() || ''
  return tail.trim().toLowerCase()
}

function normalizeMime(value: string | undefined): string {
  return String(value || '')
    .split(';')[0]
    .trim()
    .toLowerCase()
}

export function isChartImageArtifact(item: DemoBundleArtifactItem): boolean {
  const mime = normalizeMime(item.mime_type)
  if (mime.startsWith('image/')) return true

  const pathExt = getExtension(item.path)
  const nameExt = getExtension(item.name || '')
  return IMAGE_EXTENSIONS.has(pathExt) || IMAGE_EXTENSIONS.has(nameExt)
}

export function isChartCsvArtifact(item: DemoBundleArtifactItem): boolean {
  const mime = normalizeMime(item.mime_type)
  if (mime === 'text/csv' || mime === 'application/csv') return true
  if (mime === 'text/tab-separated-values') return true

  const pathExt = getExtension(item.path)
  const nameExt = getExtension(item.name || '')
  return CSV_EXTENSIONS.has(pathExt) || CSV_EXTENSIONS.has(nameExt)
}

export function splitDemoChartArtifacts(
  items: DemoBundleArtifactItem[],
): DemoChartArtifactGroups {
  const images: DemoBundleArtifactItem[] = []
  const csvs: DemoBundleArtifactItem[] = []

  for (const item of items) {
    if (isChartImageArtifact(item)) {
      images.push(item)
      continue
    }
    if (isChartCsvArtifact(item)) {
      csvs.push(item)
    }
  }

  return { images, csvs }
}

function parseCsvLine(line: string): string[] {
  const cells: string[] = []
  let current = ''
  let inQuotes = false

  for (let i = 0; i < line.length; i += 1) {
    const ch = line[i]
    if (ch === '"') {
      if (inQuotes && line[i + 1] === '"') {
        current += '"'
        i += 1
        continue
      }
      inQuotes = !inQuotes
      continue
    }
    if (ch === ',' && !inQuotes) {
      cells.push(current.trim())
      current = ''
      continue
    }
    current += ch
  }
  cells.push(current.trim())
  return cells
}

export function parseCsvPreview(
  content: string,
  maxRows = 10,
  maxCols = 8,
): CsvPreview | null {
  const lines = content
    .split(/\r?\n/g)
    .map((line) => line.trim())
    .filter(Boolean)

  if (lines.length === 0) return null

  const parsed = lines
    .slice(0, maxRows)
    .map((line) => parseCsvLine(line).slice(0, maxCols))

  if (parsed.length === 0) return null

  return {
    header: parsed[0],
    rows: parsed.slice(1),
    truncated: lines.length > maxRows,
  }
}
