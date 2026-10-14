import { useCallback } from "react";
import { useNavigate } from "react-router";

import { StudioQuickSearch } from "./StudioQuickSearch.tsx";
import type { QuickSearchNavigateOptions } from "./quickSearchNavigation.ts";

export function RemoteStudioQuickSearch() {
  const navigate = useNavigate();
  const onNavigate = useCallback(
    (path: string, _options: QuickSearchNavigateOptions) => {
      navigate(path);
    },
    [navigate],
  );
  return <StudioQuickSearch onNavigate={onNavigate} />;
}
