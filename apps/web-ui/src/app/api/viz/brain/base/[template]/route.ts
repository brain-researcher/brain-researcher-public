import { NextRequest, NextResponse } from 'next/server'
import { promises as fs } from 'fs'
import path from 'path'
export const dynamic = 'force-dynamic'

const TEMPLATE_DIR = path.resolve(process.cwd(), '..', '..', 'data', 'viz', 'templates')

export async function GET(
  _request: NextRequest,
  { params }: { params: { template: string } }
) {
  const rawName = params.template || 'mni152.nii.gz'
  const normalizedName = rawName.endsWith('.nii') || rawName.endsWith('.nii.gz')
    ? rawName
    : `${rawName}.nii.gz`
  const templateKey = normalizedName.replace(/\.nii(\.gz)?$/i, '')
  const filePath = path.join(TEMPLATE_DIR, `${templateKey}.nii.gz`)

  try {
    const data = await fs.readFile(filePath)
    return new NextResponse(new Uint8Array(data), {
      headers: {
        'Content-Type': 'application/octet-stream',
        'Content-Length': String(data.length),
        'Cache-Control': 'public, max-age=86400',
        'Content-Disposition': `inline; filename="${templateKey}.nii.gz"`,
      },
    })
  } catch (error) {
    console.error(`Failed to load brain template ${templateKey}`, error)
    return NextResponse.json(
      { error: `Template ${templateKey} not found` },
      { status: 404 }
    )
  }
}
