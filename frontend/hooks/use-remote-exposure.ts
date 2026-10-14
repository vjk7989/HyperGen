import { useCallback } from 'react'
import { useAppSettings } from '../contexts/AppSettingsContext'
import {
  isRemoteExposureEnabled,
  nextRemoteExposure,
  type RemoteExposure,
} from '../lib/remote-exposure'

export function useRemoteExposure() {
  const { settings, updateSettings } = useAppSettings()
  const enabled = isRemoteExposureEnabled(settings.remoteExposure)
  const toggle = useCallback(() => {
    updateSettings((prev) => ({
      ...prev,
      remoteExposure: nextRemoteExposure(prev.remoteExposure),
    }))
  }, [updateSettings])
  const setExposure = useCallback((remoteExposure: RemoteExposure) => {
    updateSettings((prev) => ({ ...prev, remoteExposure }))
  }, [updateSettings])
  return { enabled, exposure: settings.remoteExposure, toggle, setExposure }
}
