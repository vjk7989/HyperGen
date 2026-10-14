import path from 'path'
import { DEEP_LINK_SCHEME } from '../shared/deep-link.ts'

export function registerDeepLinkProtocolClient(
  setAsDefaultProtocolClient: (scheme: string, execPath?: string, args?: string[]) => boolean,
  options: { defaultApp: boolean; execPath: string; argv: readonly string[] },
): boolean {
  let args: [string] | [string, string, string[]]
  if (options.defaultApp) {
    const appPath = options.argv[1]
    if (appPath) {
      args = [DEEP_LINK_SCHEME, options.execPath, [path.resolve(appPath)]]
    } else {
      args = [DEEP_LINK_SCHEME]
    }
  } else {
    args = [DEEP_LINK_SCHEME]
  }

  return setAsDefaultProtocolClient(...args)
}
