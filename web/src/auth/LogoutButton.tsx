import { useAuth } from "./useAuth";

function readCookie(name: string): string | undefined {
  const match = document.cookie
    .split("; ")
    .find((c) => c.startsWith(`${name}=`));
  return match?.split("=")[1];
}

export default function LogoutButton(): JSX.Element {
  const { me, refetch } = useAuth();
  if (!me) return <></>;
  return (
    <button
      data-testid="logout-button"
      className="text-sm text-slate-400 hover:text-slate-100 focus:outline-none focus:ring"
      onClick={async () => {
        const csrf = readCookie("csrf_token");
        await fetch("/api/auth/logout", {
          method: "POST",
          credentials: "include",
          headers: csrf ? { "X-CSRF-Token": csrf } : undefined,
        });
        refetch();
        window.location.href = "/";
      }}
      title={`Signed in as ${me.user_upn}`}
    >
      Sign out · {me.user_upn}
    </button>
  );
}
