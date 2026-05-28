import { headers } from "next/headers"
import Link from "next/link"
import { notFound } from "next/navigation"

import { DatasetDetailView } from "@/components/datasets/dataset-detail-view"
import type {
  DatasetDetailResponse,
  DatasetResourceAddresses,
} from "@/types/datasets-search"

const DATASET_API_PATH = "/api/catalog/datasets"
const DATASET_RESOURCES_API_PATH = "/api/catalog/datasets"

function resolveBaseUrl(): string {
  const headerList = headers()
  const protoHeader = headerList.get("x-forwarded-proto")
  const proto = (protoHeader ? protoHeader.split(",")[0] : null) ?? (process.env.NODE_ENV === "production" ? "https" : "http")
  const hostHeader = headerList.get("x-forwarded-host") ?? headerList.get("host")
  const host = (hostHeader ? hostHeader.split(",")[0] : null) ?? "127.0.0.1:3000"
  const explicit = process.env.NEXT_PUBLIC_SITE_URL
  if (explicit) return explicit.replace(/\/$/, "")
  return `${proto}://${host}`
}

function normalizeDatasetId(datasetId: string): string {
  let normalized = datasetId.trim()
  for (let i = 0; i < 2; i += 1) {
    try {
      const next = decodeURIComponent(normalized).trim()
      if (!next || next === normalized) break
      normalized = next
    } catch {
      break
    }
  }
  return normalized
}

function buildDatasetApiHeaders(): HeadersInit | undefined {
  const cookieHeader = headers().get("cookie")
  return cookieHeader ? { cookie: cookieHeader } : undefined
}

async function fetchDataset(
  datasetId: string,
  baseUrl: string,
  requestHeaders: HeadersInit | undefined,
): Promise<DatasetDetailResponse> {
  const normalizedDatasetId = normalizeDatasetId(datasetId)
  const response = await fetch(
    `${baseUrl}${DATASET_API_PATH}/${encodeURIComponent(normalizedDatasetId)}`,
    { cache: "no-store", headers: requestHeaders },
  )
  if (response.status === 404) {
    notFound()
  }
  if (!response.ok) {
    throw new Error("Failed to load dataset details")
  }
  return response.json()
}

async function fetchDatasetResources(
  datasetId: string,
  baseUrl: string,
  requestHeaders: HeadersInit | undefined,
): Promise<DatasetResourceAddresses | undefined> {
  const normalizedDatasetId = normalizeDatasetId(datasetId)
  try {
    const response = await fetch(
      `${baseUrl}${DATASET_RESOURCES_API_PATH}/${encodeURIComponent(normalizedDatasetId)}/resources`,
      { cache: "no-store", headers: requestHeaders },
    )
    if (!response.ok) return undefined
    const payload = (await response.json()) as DatasetResourceAddresses
    if (!payload || typeof payload !== "object" || !("dataset_ref" in payload)) {
      return undefined
    }
    return payload
  } catch {
    return undefined
  }
}

interface DatasetDetailPageProps {
  params: { datasetId: string }
}

export default async function DatasetDetailPage({ params }: DatasetDetailPageProps) {
  const baseUrl = resolveBaseUrl()
  const requestHeaders = buildDatasetApiHeaders()
  const [dataset, resourceAddresses] = await Promise.all([
    fetchDataset(params.datasetId, baseUrl, requestHeaders),
    fetchDatasetResources(params.datasetId, baseUrl, requestHeaders),
  ])
  const datasetWithResources: DatasetDetailResponse = {
    ...dataset,
    resource_addresses: resourceAddresses,
  }
  return (
    <div className="mx-auto max-w-5xl space-y-6 py-6">
      <div>
        <Link href="/finder/datasets" className="text-sm text-primary hover:underline">
          ← Back to search
        </Link>
      </div>
      <DatasetDetailView dataset={datasetWithResources} />
    </div>
  )
}
