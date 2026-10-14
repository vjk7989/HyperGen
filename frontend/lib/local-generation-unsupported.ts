/** Copy for Explore when local generation is not viable. Must not mention the API. */

export const LOCAL_GENERATION_UNSUPPORTED_TITLE = 'HyperGen local generation is coming soon'
export const LOCAL_GENERATION_UNSUPPORTED_BODY =
  "Local generation isn't available on this device yet.\nFollow HyperGen for platform support and setup guidance."
export const LOCAL_GENERATION_UNSUPPORTED_WEB_APP_LABEL = 'View HyperGen'
export const LOCAL_GENERATION_UNSUPPORTED_REQUIREMENTS_LABEL = 'View HyperGen requirements'

export const LOCAL_GENERATION_UNSUPPORTED_URLS = {
  webApp: 'https://github.com/vjk7989/HyperGen',
  systemRequirements: 'https://github.com/vjk7989/HyperGen',
} as const

export const LOCAL_GENERATION_UNSUPPORTED_VIDEO_URL = new URL(
  '../assets/home/water-simulation/discover-preview.mp4',
  import.meta.url,
).href
