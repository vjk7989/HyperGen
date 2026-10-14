import { app } from 'electron'
import path from 'path'
import os from 'os'

export const APP_FOLDER_NAME = 'HyperGen'

function resolveUserDataBasePath(): string {
  if (process.platform === 'win32') {
    return process.env.LOCALAPPDATA
      || path.join(os.homedir(), 'AppData', 'Local')
  }
  if (process.platform === 'darwin') {
    return path.join(
      os.homedir(),
      'Library',
      'Application Support',
    )
  }
  return process.env.XDG_DATA_HOME || path.join(os.homedir(), '.local', 'share')
}

const userDataBasePath = resolveUserDataBasePath()
const userDataPath = path.join(userDataBasePath, APP_FOLDER_NAME)

app.setPath('userData', userDataPath)

export function getAppDataDir(): string {
  return app.getPath('userData')
}

export function getLogDir(): string {
  return path.join(app.getPath('userData'), 'logs')
}
