"use client";

import { Moon, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { Button } from "@/components/ui/button";

// Both icons render and CSS shows the right one, so the server HTML matches whatever theme the client resolves.
export function ThemeToggle() {
  const { resolvedTheme, setTheme } = useTheme();
  return (
    <Button variant="ghost" size="icon" aria-label="Toggle dark mode" onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}>
      <Sun aria-hidden className="dark:hidden" />
      <Moon aria-hidden className="hidden dark:block" />
    </Button>
  );
}
