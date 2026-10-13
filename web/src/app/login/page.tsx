import { LoginForm } from "./login-form";

export const metadata = { title: "Sign in" };

export default function LoginPage() {
  return (
    <div className="flex min-h-screen items-center justify-center px-4">
      <div className="w-full max-w-sm rounded-md border border-border bg-panel p-6">
        <div className="mb-5">
          <div className="text-[13px] font-semibold tracking-wide">CRYPTO INTELLIGENCE TERMINAL</div>
          <p className="mt-1 text-xs text-fg-dim">Private research platform. Invitation only; there is no sign-up.</p>
        </div>
        <LoginForm />
      </div>
    </div>
  );
}
