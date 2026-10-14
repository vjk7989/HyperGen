export type RemoteExposure = 'off' | 'lan' | 'cloudflare'

export function isRemoteExposureEnabled(exposure: RemoteExposure): boolean {
  switch (exposure) {
    case 'off':
      return false
    case 'lan':
    case 'cloudflare':
      return true
    default: {
      const exhaustive: never = exposure
      return exhaustive
    }
  }
}

export function nextRemoteExposure(exposure: RemoteExposure): RemoteExposure {
  switch (exposure) {
    case 'off':
      return 'lan'
    case 'lan':
    case 'cloudflare':
      return 'off'
    default: {
      const exhaustive: never = exposure
      return exhaustive
    }
  }
}
