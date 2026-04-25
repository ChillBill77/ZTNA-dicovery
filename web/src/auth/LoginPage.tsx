export default function LoginPage(): JSX.Element {
  return (
    <main className="min-h-screen flex flex-col items-center justify-center bg-slate-950 text-slate-100 gap-6">
      <h1 className="text-2xl font-semibold">ZTNA Flow Discovery</h1>
      <p className="text-slate-400 text-sm">Authentication required to view live flows.</p>
      <a
        href="/api/auth/login"
        className="rounded border border-slate-600 px-6 py-2 hover:bg-slate-800 focus:outline-none focus:ring focus:ring-okabe-sky"
        data-testid="login-button"
      >
        Sign in with Entra ID
      </a>
    </main>
  );
}
