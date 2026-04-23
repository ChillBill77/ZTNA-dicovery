import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { api } from "./client";
import type { Application, ApplicationIn, SaasEntry } from "./types";

export const useApplications = () =>
  useQuery({ queryKey: ["apps"], queryFn: () => api<Application[]>("/api/applications") });

export const useCreateApplication = () => {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (body: ApplicationIn) =>
      api<Application>("/api/applications", { method: "POST", body: JSON.stringify(body) }),
    onSuccess: () => qc.invalidateQueries({ queryKey: ["apps"] }),
  });
};

export const useSaas = () =>
  useQuery({ queryKey: ["saas"], queryFn: () => api<SaasEntry[]>("/api/saas") });
