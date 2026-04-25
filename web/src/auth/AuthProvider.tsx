import type { PropsWithChildren } from "react";

import LoginPage from "./LoginPage";
import { useAuth } from "./useAuth";

/** Wrap the app: show login page until ``/api/auth/me`` returns a session. */
export default function AuthProvider({
  children,
}: PropsWithChildren): JSX.Element {
  const { me, loading } = useAuth();
  if (loading) {
    return (
      <div
        aria-busy="true"
        className="min-h-screen flex items-center justify-center bg-slate-950 text-slate-400"
      >
        Loading…
      </div>
    );
  }
  if (!me) return <LoginPage />;
  return <>{children}</>;
}
