import type { CSSProperties } from 'react'

import HyperGenLogo from '@/assets/hypergen-logo.svg?react'
import styles from './EndpageLockup.module.scss'

/** Preserve the original three-second splash sequencing contract. */
export const ENDPAGE_SETTLED_FRAME = 90
export const ENDPAGE_SETTLED_MS = Math.round((ENDPAGE_SETTLED_FRAME / 30) * 1000)

type EndpageLockupProps = {
  /** Hold the settled frame instead of playing in — the install screen's lockup. */
  still?: boolean
  /** Hold frame 0 until the caller is ready, so picture and soundtrack start together. */
  paused?: boolean
  className?: string
  style?: CSSProperties
}

/**
 * HyperGen's startup lockup. The logo reveal keeps the existing splash timing
 * contract so callers can continue to hold, play, or settle it.
 */
export function EndpageLockup({ still = false, paused = false, className, style }: EndpageLockupProps) {
  const logoClassName = `${styles.logo}${still ? ` ${styles.logoStill}` : ''}${paused ? ` ${styles.logoPaused}` : ''}`

  return (
    <div className={`${styles.stage}${className ? ` ${className}` : ''}`} style={style}>
      <div className={styles.frame}>
        <HyperGenLogo className={logoClassName} role="img" aria-label="HyperGen" />
      </div>
    </div>
  )
}
