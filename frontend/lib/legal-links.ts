import { openExternalBrowserUrl } from '@/components/home/home-external-links'

/** LTX-2 Community License — same URL the catalog and Home already use. */
export const LTX_COMMUNITY_LICENSE_URL =
  'https://github.com/Lightricks/LTX-2/blob/main/LICENSE'

/** HyperGen privacy statement for local data and configured provider requests. */
export const HYPERGEN_PRIVACY_URL =
  'https://github.com/vjk7989/HyperGen/blob/main/docs/PRIVACY.md'

export function openLegalUrl(url: string): void {
  openExternalBrowserUrl(url)
}
