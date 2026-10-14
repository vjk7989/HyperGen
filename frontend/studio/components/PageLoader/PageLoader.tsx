import { Flex } from "@ds/layout/Flex/Flex";
import Lottie from "react-lottie";

import HyperGenLogo from "@/assets/hypergen-logo.svg?react";
import animationData from "@/studio/assets/lottie/infinite-progress.json";

import styles from "./PageLoader.module.scss";

export function PageLoader() {
  return (
    <Flex
      direction="column"
      align="center"
      justify="center"
      gap="lg"
      height="100%"
      width="100%"
    >
      <Flex
        direction="column"
        align="center"
        justify="center"
        gap="lg"
        height="48px"
        width="120px"
      >
        <div className={styles.logo}>
          <HyperGenLogo role="img" aria-label="HyperGen" />
        </div>
        <div className={styles.animation}>
          <Lottie
            options={{
              loop: true,
              autoplay: true,
              animationData,
              rendererSettings: {
                preserveAspectRatio: "xMidYMid slice",
              },
            }}
          />
        </div>
      </Flex>
    </Flex>
  );
}
