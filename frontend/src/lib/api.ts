// Typed client for the Borealis backend. All external input is validated with
// Zod before it crosses into the app (project rule).

import { z } from 'zod'

export const healthSchema = z.object({
  status: z.string(),
  service: z.string(),
  version: z.string(),
})

export type Health = z.infer<typeof healthSchema>

export async function fetchHealth(): Promise<Health> {
  const res = await fetch('/health')
  if (!res.ok) {
    throw new Error(`Backend /health responded ${res.status}`)
  }
  const json: unknown = await res.json()
  return healthSchema.parse(json)
}
