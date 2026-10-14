import { useCallback } from "react";
import { useNavigate } from "react-router";

// eslint-disable-next-line no-restricted-imports
import { StudioQuickSearch } from "@/studio/components/QuickSearch/StudioQuickSearch";
// eslint-disable-next-line no-restricted-imports
import type { QuickSearchNavigateOptions } from "@/studio/components/QuickSearch/quickSearchNavigation";

import { useProjects } from "../../contexts/ProjectContext";

export function DesktopStudioQuickSearch() {
  const navigate = useNavigate();
  const { clearActiveProject } = useProjects();
  const onNavigate = useCallback(
    (path: string, options: QuickSearchNavigateOptions) => {
      if (options.clearActiveProject) clearActiveProject();
      navigate(path);
    },
    [clearActiveProject, navigate],
  );
  return <StudioQuickSearch onNavigate={onNavigate} />;
}
