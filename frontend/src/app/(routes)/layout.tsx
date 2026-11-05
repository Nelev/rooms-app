import Link from "next/link";
import { ThemeToggle } from "./theme-toggle";

export default function RoutesLayout({ children }: LayoutProps<"/">) {
  return (
    <>
      <a
        href="#main"
        className="sr-only rounded-md bg-primary px-4 py-2 text-sm font-medium text-primary-foreground focus:not-sr-only focus:fixed focus:top-3 focus:left-3 focus:z-50"
      >
        Skip to main content
      </a>
      <header className="sticky top-0 z-20 border-b bg-background/85 backdrop-blur">
        <div className="mx-auto flex h-14 w-full max-w-6xl items-center gap-4 px-4 md:px-6">
          <Link href="/" className="rounded-md font-semibold outline-none focus-visible:ring-2 focus-visible:ring-ring">
            rooms-app
          </Link>
          <div className="ml-auto">
            <ThemeToggle />
          </div>
        </div>
      </header>
      <main id="main" tabIndex={-1} className="mx-auto flex w-full max-w-6xl flex-1 flex-col gap-5 p-4 outline-none md:p-6">
        {children}
      </main>
    </>
  );
}
