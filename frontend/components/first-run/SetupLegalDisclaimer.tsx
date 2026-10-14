import { Text } from '@ds/Text/Text'

import {
  HYPERGEN_PRIVACY_URL,
  LTX_COMMUNITY_LICENSE_URL,
  openLegalUrl,
} from '@/lib/legal-links'
import styles from '../FirstRunSetup.module.scss'

function LegalLink({ href, children }: { href: string; children: string }) {
  return (
    <a
      className={styles.legalLink}
      href={href}
      onClick={(event) => {
        event.preventDefault()
        openLegalUrl(href)
      }}
    >
      {children}
    </a>
  )
}

export function SetupLegalDisclaimer({ className }: { className?: string }) {
  return (
    <Text as="p" variant="body" size="md" className={className}>
      By using this software, you agree to the{' '}
      <LegalLink href={LTX_COMMUNITY_LICENSE_URL}>LTX Community License</LegalLink>
      {' '}and acknowledge the{' '}
      <LegalLink href={HYPERGEN_PRIVACY_URL}>HyperGen privacy statement</LegalLink>.
    </Text>
  )
}
