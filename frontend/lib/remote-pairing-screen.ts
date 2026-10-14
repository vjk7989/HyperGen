type PairingStatus = {
  permitted: boolean
  serving: boolean
  reason?: string | null
  mode?: "off" | "lan" | "cloudflare" | null
  url?: string | null
  localUrl?: string | null
  lanUrl?: string | null
  publicUrl?: string | null
  tunnelState?: "off" | "starting" | "ready" | "error"
}

function validPairingUrl(
  raw: string | null | undefined,
  { publicOnly = false }: { publicOnly?: boolean } = {},
): string | null {
  if (!raw) return null
  try {
    const parsed = new URL(raw)
    if (!parsed.searchParams.get("t") || parsed.pathname !== "/pairing") return null
    if (publicOnly) {
      const hostname = parsed.hostname.toLowerCase()
      if (
        parsed.protocol !== "https:" ||
        !hostname.endsWith(".trycloudflare.com") ||
        hostname === "trycloudflare.com"
      ) {
        return null
      }
    } else if (parsed.protocol !== "http:" && parsed.protocol !== "https:") {
      return null
    }
    return raw
  } catch {
    return null
  }
}

export function pairingUrlFromStatus(status: PairingStatus | null): string | null {
  if (!status?.serving) return null
  if (status.mode === "cloudflare") {
    return (
      validPairingUrl(status.publicUrl, { publicOnly: true }) ??
      validPairingUrl(status.lanUrl ?? status.url)
    )
  }
  return validPairingUrl(status.lanUrl ?? status.url)
}

const STARTUP_REASONS = new Set([
  "starting",
  "stopped",
  "not started",
  // Controller stores this while Off. After On, settings sync + the 2s poll still return it.
  "disabled in Settings",
  "starting Cloudflare Tunnel",
])

function isPairingLoading(status: PairingStatus | null): boolean {
  if (!status?.permitted) {
    return false
  }
  if (status.serving) {
    return false
  }
  const reason = status.reason
  if (reason == null || reason === "") {
    return true
  }
  return STARTUP_REASONS.has(reason)
}

/** Laptop copy while Remote is On but not yet serving a pairing URL. */
export function pairingErrorMessage(
  on: boolean,
  serving: boolean,
  status: PairingStatus | null,
  unreachable: boolean,
): string | null {
  if (!on || serving) {
    return null
  }
  if (!status) {
    return unreachable ? "Remote is not available" : null
  }
  if (!status.permitted) {
    return status.reason ?? "Remote is not available"
  }
  if (isPairingLoading(status)) {
    return null
  }
  return status.reason ?? "Remote is not available"
}
